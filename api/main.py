import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from config.prompts import PromptManager
from core.agent_runner import TestCaseAgent, normalize_cases_data
from core.document_parser import extract_pdf_text, render_pdf_pages
from core.evaluator import Evaluator
from core.llm_client import extract_json_from_text, get_chat_response
from core.rag_engine import RAGEngine


JSON_REPAIR_SYSTEM_PROMPT = "你是 JSON 修复器。只输出合法 JSON，不要输出解释、Markdown 或代码块。"


def _repair_cases_json(config: "ModelConfig", raw_text: str, prd_text: str):
    repair_prompt = f"""
下面是模型生成测试用例时的原始输出，但它不是可解析的 JSON。
请把它转换为合法 JSON 数组。

PRD：
{prd_text}

要求：
1. 顶层必须是数组。
2. 每条用例必须包含 id, module, precondition, step, expected, priority, design_strategy。
3. PRD 是唯一被测对象，所有用例都必须直接围绕 PRD 的业务对象和业务规则。
4. 如果原始输出与 PRD 主题不一致，请丢弃原始输出，并根据 PRD 重新生成高质量测试用例。
5. 如果原文没有足够用例，请根据 PRD 语义补全。
6. 只输出 JSON 数组。

原始输出：
{raw_text}
"""
    repaired_text, _ = get_chat_response(
        config.api_key,
        config.model_name,
        [],
        repair_prompt,
        system_instruction=JSON_REPAIR_SYSTEM_PROMPT,
        provider=config.provider,
        base_url=config.base_url,
    )
    _raise_if_model_error(repaired_text)
    return extract_json_from_text(repaired_text), repaired_text


class ModelConfig(BaseModel):
    provider: str = "openai_compatible"
    api_key: str = Field(default="", alias="apiKey")
    base_url: str = Field(default="https://api.openai.com/v1", alias="baseUrl")
    model_name: str = Field(default="gpt-4o-mini", alias="modelName")
    embedding_model: str = Field(default="text-embedding-3-small", alias="embeddingModel")
    vision_model: str = Field(default="", alias="visionModel")


class GenerateRequest(BaseModel):
    config: ModelConfig
    prd_text: str = Field(alias="prdText")
    use_kb: bool = Field(default=True, alias="useKb")
    use_history: bool = Field(default=True, alias="useHistory")


class OptimizeRequest(BaseModel):
    config: ModelConfig
    prd_text: str = Field(alias="prdText")
    cases: Any
    rag_context: str = Field(default="", alias="ragContext")
    target_score: int = Field(default=85, alias="targetScore")
    max_rounds: int = Field(default=2, alias="maxRounds")


class EvaluateRequest(BaseModel):
    config: ModelConfig
    prd_text: str = Field(alias="prdText")
    cases: Any
    rag_context: str = Field(default="", alias="ragContext")


class KbListRequest(BaseModel):
    config: ModelConfig
    collection_type: str = Field(default="knowledge", alias="collectionType")


class KbDeleteRequest(BaseModel):
    config: ModelConfig
    doc_id: str = Field(alias="docId")
    collection_type: str = Field(default="knowledge", alias="collectionType")


class HistorySaveRequest(BaseModel):
    config: ModelConfig
    prd_text: str = Field(alias="prdText")
    cases: Any
    summary: str = "历史用例"


app = FastAPI(title="Auto PRD Test Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_key(config: ModelConfig):
    if not config.api_key or config.api_key.startswith("YOUR_"):
        raise HTTPException(status_code=400, detail="Please provide a valid API key.")


def _error(message: str):
    raise HTTPException(status_code=500, detail=message)


def _raise_if_model_error(response_text: str):
    text = str(response_text or "").strip()
    error_prefixes = (
        "OpenAI-compatible 模型调用出错:",
        "模型调用出错:",
        "摘要生成失败:",
    )
    if text.startswith(error_prefixes):
        raise HTTPException(status_code=502, detail=text)


def _flatten_case_text(cases: Any) -> str:
    if isinstance(cases, str):
        return cases
    if isinstance(cases, list):
        return "\n".join(_flatten_case_text(item) for item in cases)
    if isinstance(cases, dict):
        return "\n".join(_flatten_case_text(value) for value in cases.values())
    return str(cases or "")


def _extract_relevance_terms(text: str) -> set[str]:
    lowered = text.lower()
    terms = set(re.findall(r"[a-z][a-z0-9_-]{2,}", lowered))
    generic = {
        "用户", "系统", "页面", "功能", "流程", "操作", "状态", "异常", "成功", "失败",
        "输入", "输出", "展示", "点击", "提交", "校验", "数据", "信息", "进行",
        "可以", "需要", "支持", "返回", "生成", "使用",
    }
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        max_size = min(4, len(chunk))
        for size in range(2, max_size + 1):
            for index in range(0, len(chunk) - size + 1):
                term = chunk[index:index + size]
                if term not in generic:
                    terms.add(term)
    return terms


def _looks_irrelevant_to_prd(prd_text: str, cases: Any) -> bool:
    case_text = _flatten_case_text(cases)
    if not case_text.strip():
        return False

    prd_lower = prd_text.lower()
    case_lower = case_text.lower()
    technical_terms = [
        "openai", "compatible", "api key", "base url", "embedding", "deepseek", "qwen",
        "大模型", "模型调用", "模型接口", "向量模型", "视觉模型", "知识库", "llm",
    ]
    if any(term in case_lower and term not in prd_lower for term in technical_terms):
        return True

    prd_terms = _extract_relevance_terms(prd_text)
    if len(prd_terms) < 6:
        return False

    overlap = [term for term in prd_terms if term in case_text or term.lower() in case_lower]
    return len(overlap) < 2


def _generate_cases_once(config: "ModelConfig", prd_text: str, rag_context: str):
    prompt = PromptManager.get_initial_prompt(prd_text, rag_context)
    response_text, _ = get_chat_response(
        config.api_key,
        config.model_name,
        [],
        prompt,
        system_instruction=PromptManager.CORE_SYSTEM_PROMPT,
        provider=config.provider,
        base_url=config.base_url,
    )
    _raise_if_model_error(response_text)
    parsed = extract_json_from_text(response_text)
    repaired_text = ""
    if not parsed:
        parsed, repaired_text = _repair_cases_json(config, response_text, prd_text)
    cases = normalize_cases_data(parsed) if parsed else []
    return response_text, repaired_text, parsed, cases


def _rag_from_config(config: ModelConfig):
    return RAGEngine(
        config.api_key,
        provider=config.provider,
        base_url=config.base_url,
        embedding_model=config.embedding_model,
    )


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/parse-file")
async def parse_file(
    file: UploadFile = File(...),
    config: Optional[str] = Form(None),
    enableVision: bool = Form(False),
):
    raw = await file.read()
    content_type = file.content_type or ""
    name = file.filename or "uploaded"
    lower_name = name.lower()

    def parse_model_config():
        if not config:
            raise HTTPException(status_code=400, detail="启用多模态解析需要先配置模型。")
        try:
            return ModelConfig.model_validate(json.loads(config))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid config: {e}")

    def analyze_images(model_config: ModelConfig, images: List[Dict[str, Any]]):
        _require_key(model_config)
        vision_model = model_config.vision_model or model_config.model_name
        prompt = (
            "你是测试分析助手。请解析这些 UI 图、原型图或 PDF 页面截图，输出中文结构化说明，"
            "包括页面名称、主要组件、用户操作路径、校验点、异常状态、测试风险点。"
            "不要生成最终测试用例，只提取可用于后续生成测试用例的页面信息。"
        )
        content: List[Any] = [prompt]
        for image in images:
            content.append(f"第 {image['page']} 页/图：")
            content.append({
                "mime_type": image["mime_type"],
                "data": image["data"],
            })
        response_text, _ = get_chat_response(
            model_config.api_key,
            vision_model,
            [],
            content,
            system_instruction="你负责把视觉输入转成结构化需求上下文。",
            provider=model_config.provider,
            base_url=model_config.base_url,
        )
        return response_text

    try:
        if "pdf" in content_type or lower_name.endswith(".pdf"):
            text = ""
            try:
                text = extract_pdf_text(raw)
            except Exception as e:
                if not enableVision:
                    raise e
                text = f"[PDF 文本抽取为空或失败：{e}]"

            if enableVision:
                model_config = parse_model_config()
                pages = render_pdf_pages(raw, max_pages=3)
                vision_text = analyze_images(model_config, pages)
                text = f"{text}\n\n[多模态页面解析]\n{vision_text}".strip()
        elif content_type.startswith("image/") or lower_name.endswith((".png", ".jpg", ".jpeg", ".webp")):
            if not enableVision:
                raise HTTPException(status_code=400, detail="图片文件需要开启多模态解析。")
            model_config = parse_model_config()
            text = analyze_images(model_config, [{
                "page": 1,
                "mime_type": content_type or "image/png",
                "data": raw,
            }])
        else:
            text = RAGEngine._decode_text(raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"filename": name, "text": text, "visionUsed": enableVision}


@app.post("/api/generate")
def generate_cases(req: GenerateRequest):
    _require_key(req.config)
    rag_context = ""
    sources: List[str] = []

    try:
        rag = _rag_from_config(req.config)
        if req.use_kb or req.use_history:
            rag_context, sources = rag.search_context(
                req.prd_text,
                use_history=req.use_history,
                use_knowledge=req.use_kb,
            )
    except Exception:
        rag_context = ""
        sources = []

    try:
        response_text, repaired_text, parsed, cases = _generate_cases_once(
            req.config,
            req.prd_text,
            rag_context,
        )
        rag_ignored = False
        if rag_context and _looks_irrelevant_to_prd(req.prd_text, cases):
            response_text, repaired_text, parsed, cases = _generate_cases_once(
                req.config,
                req.prd_text,
                "",
            )
            rag_ignored = True

        return {
            "text": response_text,
            "repairedText": repaired_text,
            "cases": cases,
            "rawJson": parsed,
            "ragContext": "" if rag_ignored else rag_context,
            "sources": [] if rag_ignored else sources,
            "ragIgnored": rag_ignored,
        }
    except Exception as e:
        _error(str(e))


@app.post("/api/kb/list")
def list_kb(req: KbListRequest):
    _require_key(req.config)
    try:
        rag = _rag_from_config(req.config)
        return {"items": rag.list_documents(req.collection_type)}
    except Exception as e:
        _error(str(e))


@app.post("/api/kb/upload")
async def upload_kb(config: str = Form(...), file: UploadFile = File(...), docType: str = Form("技术文档")):
    try:
        data = json.loads(config)
        model_config = ModelConfig.model_validate(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid config: {e}")

    _require_key(model_config)
    raw = await file.read()
    content_type = file.content_type or ""
    filename = file.filename or "knowledge.txt"

    try:
        if "pdf" in content_type or filename.lower().endswith(".pdf"):
            parsed_text = extract_pdf_text(raw)
        else:
            parsed_text = RAGEngine._decode_text(raw)

        class MemoryUpload:
            def __init__(self, name, file_type, data_bytes):
                self.name = name
                self.type = file_type
                self._data = data_bytes

            def seek(self, *_args):
                return None

            def read(self):
                return self._data

            def getvalue(self):
                return self._data

        rag = _rag_from_config(model_config)
        summary = filename
        rag.add_knowledge(
            MemoryUpload(filename, content_type or "text/plain", raw),
            summary=summary,
            content_text=parsed_text,
            model_name=model_config.model_name,
            doc_type=docType,
        )
        return {"ok": True, "filename": filename, "summary": summary, "docType": docType}
    except Exception as e:
        _error(str(e))


@app.post("/api/kb/delete")
def delete_kb(req: KbDeleteRequest):
    _require_key(req.config)
    try:
        rag = _rag_from_config(req.config)
        rag.delete_document(req.doc_id, req.collection_type)
        return {"ok": True}
    except Exception as e:
        _error(str(e))


@app.post("/api/history/save")
def save_history_case(req: HistorySaveRequest):
    _require_key(req.config)
    try:
        rag = _rag_from_config(req.config)
        normalized_cases = normalize_cases_data(req.cases)
        summary = req.summary or f"历史用例（{len(normalized_cases)} 条）"
        rag.add_history_case(req.prd_text, normalized_cases, summary=summary)
        return {"ok": True, "summary": summary, "count": len(normalized_cases)}
    except Exception as e:
        _error(str(e))


@app.post("/api/evaluate")
def evaluate_cases(req: EvaluateRequest):
    _require_key(req.config)
    evaluator = Evaluator(req.config.api_key, provider=req.config.provider, base_url=req.config.base_url)
    report = evaluator.evaluate_cases(
        req.config.model_name,
        req.prd_text,
        req.cases,
        rag_context=req.rag_context,
    )
    return {"report": report}


@app.post("/api/agent-optimize")
def agent_optimize(req: OptimizeRequest):
    _require_key(req.config)
    evaluator = Evaluator(req.config.api_key, provider=req.config.provider, base_url=req.config.base_url)
    agent = TestCaseAgent(
        req.config.api_key,
        req.config.model_name,
        provider=req.config.provider,
        base_url=req.config.base_url,
        evaluator=evaluator,
        target_score=req.target_score,
        max_rounds=req.max_rounds,
    )
    try:
        return agent.run(req.prd_text, req.cases, rag_context=req.rag_context)
    except Exception as e:
        _error(str(e))
