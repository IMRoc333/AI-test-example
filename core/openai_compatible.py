import base64
import json
import socket
import urllib.error
import urllib.request


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"


class OpenAICompatibleClient:
    def __init__(self, api_key, base_url=DEFAULT_BASE_URL, timeout=180):
        if not api_key:
            raise ValueError("OpenAI-compatible API Key is required")
        self.api_key = api_key
        self.base_url = self._normalize_base_url(base_url)
        self.timeout = timeout

    @staticmethod
    def _normalize_base_url(base_url):
        base_url = (base_url or DEFAULT_BASE_URL).strip().rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = f"{base_url}/v1"
        return base_url

    def _request(self, method, path, payload=None):
        data = None
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {e.code}: {body[:500]}") from e
        except (TimeoutError, socket.timeout) as e:
            raise TimeoutError(f"模型接口响应超时，已等待 {self.timeout} 秒。请稍后重试，或换用更快的模型。") from e
        except urllib.error.URLError as e:
            reason = getattr(e, "reason", e)
            raise RuntimeError(f"模型接口网络请求失败：{reason}") from e

    @staticmethod
    def _image_part(item):
        mime_type = item.get("mime_type", "image/png")
        data = item.get("data", b"")
        if isinstance(data, str):
            encoded = data
        else:
            encoded = base64.b64encode(data).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
        }

    @classmethod
    def to_chat_content(cls, content):
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, str):
                    parts.append({"type": "text", "text": item})
                elif isinstance(item, dict) and str(item.get("mime_type", "")).startswith("image/"):
                    parts.append(cls._image_part(item))
                elif isinstance(item, dict) and item.get("mime_type") == "application/pdf":
                    raise ValueError("OpenAI-compatible mode expects PDF content to be extracted as text first.")
                else:
                    raise ValueError("Unsupported OpenAI-compatible message content.")
            return parts
        return str(content)

    @classmethod
    def flatten_content(cls, content):
        converted = cls.to_chat_content(content)
        if isinstance(converted, str):
            return converted

        text_parts = []
        for item in converted:
            if item.get("type") == "text":
                text_parts.append(item.get("text", ""))
            elif item.get("type") == "image_url":
                text_parts.append("[image]")
        return "\n\n".join(part for part in text_parts if part)

    def list_models(self):
        data = self._request("GET", "/models")
        models = []
        for item in data.get("data", []):
            model_id = item.get("id")
            if model_id:
                models.append(model_id)
        return sorted(models)

    def chat(self, model_name, history, user_input, system_instruction=None):
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})

        for msg in history or []:
            if isinstance(msg, dict) and msg.get("role") in {"user", "assistant", "system"}:
                messages.append({"role": msg["role"], "content": self.to_chat_content(msg.get("content", ""))})

        messages.append({"role": "user", "content": self.to_chat_content(user_input)})

        data = self._request(
            "POST",
            "/chat/completions",
            {
                "model": model_name,
                "messages": messages,
                "temperature": 0.2,
                "max_tokens": 4096,
            },
        )
        text = data["choices"][0]["message"].get("content", "")
        updated_history = list(history or [])
        updated_history.append({"role": "user", "content": self.flatten_content(user_input)})
        updated_history.append({"role": "assistant", "content": text})
        return text, updated_history

    def summarize(self, model_name, prompt, content):
        text, _ = self.chat(model_name, [], f"{prompt}\n\n{str(content)[:8000]}")
        return text.strip()

    def embed(self, model_name, inputs):
        if isinstance(inputs, str):
            inputs = [inputs]
        data = self._request(
            "POST",
            "/embeddings",
            {
                "model": model_name,
                "input": inputs,
            },
        )
        rows = sorted(data.get("data", []), key=lambda item: item.get("index", 0))
        return [row["embedding"] for row in rows]
