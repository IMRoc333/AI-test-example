import os
import sys

import google.generativeai as genai

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.prompts import PromptManager
from core.llm_client import extract_json_from_text
from core.openai_compatible import DEFAULT_CHAT_MODEL, OpenAICompatibleClient


class Evaluator:
    def __init__(self, api_key, provider="gemini", base_url=None):
        if not api_key:
            raise ValueError("Evaluator 需要 API Key")
        self.api_key = api_key
        self.provider = provider
        self.base_url = base_url

    def evaluate_cases(self, model_name, prd_text, current_cases, rag_context=None, golden_cases_content=None):
        try:
            prompt_text = PromptManager.get_evaluation_prompt(
                prd_text,
                current_cases,
                rag_text=rag_context,
                golden_cases_text=golden_cases_content,
            )

            if self.provider == "openai_compatible":
                response_text, _ = OpenAICompatibleClient(self.api_key, self.base_url).chat(
                    model_name or DEFAULT_CHAT_MODEL,
                    [],
                    prompt_text,
                    system_instruction=PromptManager.EVALUATOR_SYSTEM_PROMPT,
                )
            else:
                genai.configure(api_key=self.api_key)
                model = genai.GenerativeModel(
                    model_name,
                    system_instruction=PromptManager.EVALUATOR_SYSTEM_PROMPT,
                )
                response = model.generate_content(prompt_text)
                response_text = response.text

            report_json = extract_json_from_text(response_text)
            if not report_json:
                return {
                    "score": 0,
                    "summary": "AI 未能生成有效的 JSON 格式报告，请重试。",
                    "coverage_gap": [],
                    "logic_issues": [],
                    "duplicates": [],
                    "suggestions": [f"原始响应: {response_text[:200]}..."],
                }

            return report_json

        except Exception as e:
            print(f"评估过程出错: {e}")
            return {
                "score": 0,
                "summary": f"评估服务发生错误: {str(e)}",
                "coverage_gap": [],
                "logic_issues": [],
                "duplicates": [],
                "suggestions": ["请检查网络连接或 API Key 配额"],
            }
