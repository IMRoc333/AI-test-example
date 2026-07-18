import chromadb
import os
import json
import uuid
import sys
from datetime import datetime
import google.generativeai as genai
from PIL import Image

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config.prompts import PromptManager
from core.openai_compatible import DEFAULT_EMBEDDING_MODEL, OpenAICompatibleClient
from core.document_parser import extract_pdf_text

# 路径配置
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE_DIR, 'data', 'vector_db')
DOC_PATH = os.path.join(BASE_DIR, 'data', 'raw_files') 

if not os.path.exists(DOC_PATH):
    os.makedirs(DOC_PATH)

class TextSplitter:
    """
    简易的递归文本切片器 (纯Python实现，不依赖LangChain)
    """
    @staticmethod
    def recursive_split(text, chunk_size=500, chunk_overlap=100):
        """
        将长文本切分为带有重叠的片段。
        """
        if not text:
            return []
        
        # 【修复点 1】: 如果文本本身比 chunk_size 还短，直接返回全文，避免进入循环逻辑
        if len(text) <= chunk_size:
            return [text]
        
        chunks = []
        start = 0
        text_len = len(text)
        
        while start < text_len:
            end = start + chunk_size
            
            # 如果不是最后一段，尝试在结束点附近找句号或换行符
            if end < text_len:
                look_ahead = text[end:end+50]
                separators = ["\n", "。", "！", "？", ".", "!", "?"]
                best_end = end
                for sep in separators:
                    if sep in look_ahead:
                        best_end = end + look_ahead.index(sep) + 1
                        break
                end = best_end
            
            # 截取
            chunk = text[start:min(end, text_len)]
            
            # 防止空块
            if not chunk: 
                break
                
            chunks.append(chunk)
            
            # 【修复点 2】: 退出条件优化
            # 如果当前截取的块已经是最后一部分（长度不够 chunk_size，或者 end 已经到了尽头）
            if len(chunk) < chunk_size or end >= text_len:
                break
            
            # 【修复点 3】: 指针步进保护
            # 正常步进是 len(chunk) - overlap
            step = len(chunk) - chunk_overlap
            # 如果 overlap 比 chunk 还大（极端情况），强制至少步进 1，防止死循环
            if step <= 0:
                step = 1
                
            start += step
            
            # 双重保险：防止 start 没动
            if start >= text_len:
                break
                
        return chunks

class RAGEngine:
    def __init__(self, api_key, provider="gemini", base_url=None, embedding_model=None):
        if not api_key: raise ValueError("RAG Engine 需要 API Key")
        self.client = chromadb.PersistentClient(path=DB_PATH)
        self.provider = provider
        self.base_url = base_url
        self.embedding_model = embedding_model
        if provider == "openai_compatible":
            self.embedding_fn = OpenAICompatibleEmbeddingFunction(
                api_key,
                base_url=base_url,
                model_name=embedding_model or DEFAULT_EMBEDDING_MODEL,
            )
        else:
            self.embedding_fn = GeminiEmbeddingFunction(api_key)
        self.api_key = api_key 

        suffix = "_openai" if provider == "openai_compatible" else ""
        self.history_coll = self.client.get_or_create_collection(name=f"history_cases{suffix}", embedding_function=self.embedding_fn)
        self.knowledge_coll = self.client.get_or_create_collection(name=f"company_knowledge{suffix}", embedding_function=self.embedding_fn)

    def _save_raw_file(self, file_obj, filename):
        safe_name = f"{uuid.uuid4().hex[:8]}_{os.path.basename(filename)}"
        file_path = os.path.join(DOC_PATH, safe_name)
        file_obj.seek(0)
        with open(file_path, "wb") as f:
            f.write(file_obj.read())
        return file_path

    @staticmethod
    def _decode_text(raw_bytes):
        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                return raw_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw_bytes.decode("utf-8", errors="ignore")

    def parse_file_content(self, file_obj, file_type, model_name="models/gemini-1.5-flash"):
        """利用 AI 解析图片/PDF 内容为文本"""
        try:
            if self.provider == "openai_compatible":
                file_obj.seek(0)
                if "pdf" in file_type:
                    return extract_pdf_text(file_obj.read())
                if "image" in file_type:
                    image_bytes = file_obj.read()
                    response_text, _ = OpenAICompatibleClient(self.api_key, self.base_url).chat(
                        model_name,
                        [],
                        [PromptManager.MULTIMODAL_PARSE_PROMPT, {"mime_type": file_type, "data": image_bytes}],
                    )
                    return response_text
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(model_name)
            
            content_part = []
            file_obj.seek(0)
            
            prompt = PromptManager.MULTIMODAL_PARSE_PROMPT
            
            if "image" in file_type:
                img = Image.open(file_obj)
                content_part = [prompt, img]
            elif "pdf" in file_type:
                file_bytes = file_obj.read()
                content_part = [prompt, {"mime_type": "application/pdf", "data": file_bytes}]
            else:
                return self._decode_text(file_obj.read())
            
            resp = model.generate_content(content_part)
            return resp.text
        except Exception as e:
            return f"[解析失败] {str(e)}"

    def add_knowledge(self, file_obj, summary="", content_text=None, model_name="models/gemini-1.5-flash", doc_type="技术文档"):
        """支持 Chunking 切片存储"""
        final_content = ""
        if content_text:
            final_content = content_text
        else:
            if "text" in file_obj.type or "md" in file_obj.name:
                file_obj.seek(0)
                final_content = self._decode_text(file_obj.getvalue())
            else:
                final_content = self.parse_file_content(file_obj, file_obj.type, model_name)

        if not final_content or not final_content.strip():
            raise ValueError("文档内容为空，未写入知识库")
        if final_content.startswith("[解析失败]"):
            raise ValueError(final_content)

        saved_path = self._save_raw_file(file_obj, file_obj.name)

        # 执行切片
        chunks = TextSplitter.recursive_split(final_content, chunk_size=500, chunk_overlap=100)
        
        file_doc_id = str(uuid.uuid4())
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        ids = []
        documents = []
        metadatas = []
        
        for i, chunk in enumerate(chunks):
            chunk_id = f"{file_doc_id}_chunk_{i}"
            ids.append(chunk_id)
            documents.append(chunk)
            metadatas.append({
                "doc_id": file_doc_id,
                "source": file_obj.name,
                "summary": summary if summary else "暂无摘要",
                "file_path": saved_path,
                "chunk_index": i,
                "type": "spec",
                "doc_type": doc_type,
                "date": current_time
            })

        if not documents:
            raise ValueError("文档切片为空，未写入知识库")
        self.knowledge_coll.add(documents=documents, metadatas=metadatas, ids=ids)

    def add_history_case(self, prd_text, final_json, summary=""):
        if isinstance(final_json, (dict, list)):
            final_json = json.dumps(final_json, ensure_ascii=False)
        file_doc_id = str(uuid.uuid4())
        self.history_coll.add(
            documents=[prd_text],
            metadatas=[{"doc_id": file_doc_id, "answer": final_json, "source": summary, "summary": summary, "type": "history", "date": datetime.now().strftime("%Y-%m-%d %H:%M"), "file_path": "N/A"}],
            ids=[file_doc_id]
        )

    def list_documents(self, collection_type="knowledge"):
        coll = self.history_coll if collection_type == "history" else self.knowledge_coll
        data = coll.get()
        unique_docs = {}
        if data['ids']:
            for i, _ in enumerate(data['ids']):
                meta = data['metadatas'][i]
                doc_id = meta.get('doc_id')
                if not doc_id: # 兼容旧数据
                    unique_docs[data['ids'][i]] = {"ID": data['ids'][i], "文件名/标题": meta.get('source', 'unknown'), "AI摘要": meta.get('summary', '-'), "类型": "历史用例" if collection_type == "history" else "技术文档", "doc_type": meta.get('doc_type', "历史用例" if collection_type == "history" else "技术文档"), "录入时间": meta.get('date', '-'), "原始路径": meta.get('file_path', 'N/A')}
                    continue
                if doc_id not in unique_docs:
                    unique_docs[doc_id] = {"ID": doc_id, "文件名/标题": meta.get('source', 'unknown'), "AI摘要": meta.get('summary', '-'), "类型": "历史用例" if collection_type == "history" else "技术文档", "doc_type": meta.get('doc_type', "历史用例" if collection_type == "history" else "技术文档"), "录入时间": meta.get('date', '-'), "原始路径": meta.get('file_path', 'N/A')}
        return list(unique_docs.values())

    def get_doc_content(self, file_path, doc_id=None, collection_type="knowledge"):
        coll = self.history_coll if collection_type == "history" else self.knowledge_coll
        if doc_id:
            try:
                item = coll.get(where={"doc_id": doc_id}, limit=1)
                if not item['ids']: item = coll.get(ids=[doc_id], limit=1)
                if item['documents'] and item['documents'][0]:
                    if collection_type == "history" and item['metadatas']:
                        json_str = item['metadatas'][0].get('answer', '{}')
                        try:
                            parsed = json.loads(json_str)
                            return json.dumps(parsed, indent=2, ensure_ascii=False)
                        except: return json_str
                    return item['documents'][0]
            except Exception: pass
        if os.path.exists(file_path):
            try:
                if file_path.endswith(('.txt', '.md', '.json', '.yaml', '.csv')):
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f: return f.read()
            except: pass
        return "无法获取文档内容"

    def delete_document(self, doc_id, collection_type="knowledge"):
        coll = self.history_coll if collection_type == "history" else self.knowledge_coll
        items = coll.get(where={"doc_id": doc_id}, limit=1)
        if not items['ids']: items = coll.get(ids=[doc_id], limit=1)
        if items['metadatas']:
            path = items['metadatas'][0].get('file_path')
            if path and path != "N/A" and os.path.exists(path):
                try: os.remove(path)
                except: pass
        coll.delete(where={"doc_id": doc_id})
        coll.delete(ids=[doc_id])

    def search_context(self, query, use_history=True, use_knowledge=True):
        context_parts = []
        sources = []
        if use_knowledge:
            res_k = self.knowledge_coll.query(query_texts=[query], n_results=3)
            if res_k['documents'] and res_k['documents'][0]:
                for i, doc in enumerate(res_k['documents'][0]):
                    meta = res_k['metadatas'][0][i]
                    src = meta.get('source', 'unknown')
                    context_parts.append(f"【技术规范片段 ({src})】:\n...{doc}...")
                    sources.append(f"📚 {src}")
        if use_history:
            res_h = self.history_coll.query(query_texts=[query], n_results=1)
            if res_h['documents'] and res_h['documents'][0]:
                for i, doc in enumerate(res_h['documents'][0]):
                    summary = res_h['metadatas'][0][i].get('summary', '历史案例')
                    ans = res_h['metadatas'][0][i].get('answer', '')
                    context_parts.append(f"【参考历史 ({summary})】:\n参考用例:{ans[:800]}...")
                    sources.append(f"🕰️ {summary}")
        return "\n\n<<<RAG_SEP>>>\n\n".join(context_parts), list(set(sources))

class GeminiEmbeddingFunction(chromadb.EmbeddingFunction):
    def __init__(self, api_key):
        genai.configure(api_key=api_key)
    def __call__(self, input):
        if isinstance(input, str): input = [input]
        try:
            result = genai.embed_content(model="models/text-embedding-004", content=input, task_type="retrieval_document")
            return result['embedding']
        except: return [[0.0] * 768 for _ in input]


class OpenAICompatibleEmbeddingFunction(chromadb.EmbeddingFunction):
    def __init__(self, api_key, base_url=None, model_name=DEFAULT_EMBEDDING_MODEL):
        self.client = OpenAICompatibleClient(api_key, base_url)
        self.model_name = model_name

    def __call__(self, input):
        if isinstance(input, str):
            input = [input]
        try:
            return self.client.embed(self.model_name, input)
        except Exception as e:
            print(f"OpenAI-compatible embedding 失败: {e}")
            return [[0.0] * 1536 for _ in input]
