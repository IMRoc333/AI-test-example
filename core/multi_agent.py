from typing import Any, Dict, List

from config.prompts import PromptManager
from core.llm_client import extract_json_from_text, get_chat_response


def _raise_model_error(response_text: str):
    text = str(response_text or "").strip()
    prefixes = ("OpenAI-compatible 模型调用出错:", "模型调用出错:")
    if text.startswith(prefixes):
        raise RuntimeError(text)


class BaseLLMAgent:
    name = "Base Agent"

    def __init__(self, api_key, model_name, provider="gemini", base_url=None):
        self.api_key = api_key
        self.model_name = model_name
        self.provider = provider
        self.base_url = base_url

    def call_json(self, prompt: str, system_instruction: str):
        response_text, _ = get_chat_response(
            self.api_key,
            self.model_name,
            [],
            prompt,
            system_instruction=system_instruction,
            provider=self.provider,
            base_url=self.base_url,
        )
        _raise_model_error(response_text)
        parsed = extract_json_from_text(response_text)
        if parsed is None:
            raise ValueError(f"{self.name} 未返回有效 JSON: {response_text[:300]}")
        return parsed, response_text


class DocumentAnalysisAgent(BaseLLMAgent):
    name = "文档解析 Agent"

    def run(self, prd_text: str, rag_context: str = ""):
        prompt = PromptManager.get_document_agent_prompt(prd_text, rag_context)
        result, raw_text = self.call_json(prompt, PromptManager.DOCUMENT_AGENT_SYSTEM_PROMPT)
        if not isinstance(result, dict):
            raise ValueError("文档解析 Agent 输出必须是 JSON 对象")
        return result, raw_text


class ModuleTreeAgent(BaseLLMAgent):
    name = "模块生成 Agent"

    def run(self, prd_text: str, document_insight: Dict[str, Any], rag_context: str = ""):
        prompt = PromptManager.get_module_agent_prompt(prd_text, document_insight, rag_context)
        result, raw_text = self.call_json(prompt, PromptManager.MODULE_AGENT_SYSTEM_PROMPT)
        if not isinstance(result, dict):
            raise ValueError("模块生成 Agent 输出必须是 JSON 对象")
        return result, raw_text


class RequirementMultiAgentPipeline:
    def __init__(self, api_key, model_name, provider="gemini", base_url=None):
        self.document_agent = DocumentAnalysisAgent(api_key, model_name, provider, base_url)
        self.module_agent = ModuleTreeAgent(api_key, model_name, provider, base_url)

    @staticmethod
    def _trace_step(agent: str, summary: str, output: Any):
        return {
            "agent": agent,
            "action": "finish",
            "summary": summary,
            "output": output,
        }

    def run(self, prd_text: str, rag_context: str = ""):
        trace: List[Dict[str, Any]] = []

        document_insight, document_raw = self.document_agent.run(prd_text, rag_context)
        trace.append(self._trace_step(
            self.document_agent.name,
            "抽取需求摘要、角色、流程、明确规则和疑点",
            document_insight,
        ))

        analysis, module_raw = self.module_agent.run(prd_text, document_insight, rag_context)
        trace.append(self._trace_step(
            self.module_agent.name,
            "生成测试模块树、测试点、风险点和待确认问题",
            analysis,
        ))

        return {
            "analysis": analysis,
            "documentInsight": document_insight,
            "agentTrace": trace,
            "raw": {
                "documentAgent": document_raw,
                "moduleAgent": module_raw,
            },
        }
