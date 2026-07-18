import unittest

import pandas as pd

from config.settings import is_valid_api_key
from core.agent_runner import TestCaseAgent, normalize_cases_data
from core.llm_client import extract_json_from_text
from core.openai_compatible import OpenAICompatibleClient
from core.rag_engine import RAGEngine, TextSplitter
from ui.components import dataframe_to_markdown


class CoreFixesTest(unittest.TestCase):
    def test_placeholder_api_key_is_invalid(self):
        self.assertFalse(is_valid_api_key(""))
        self.assertFalse(is_valid_api_key("YOUR_GEMINI_API_KEY_HERE"))
        self.assertTrue(is_valid_api_key("AIzaSy_realistic_key_value"))

    def test_extract_json_after_explanation(self):
        text = '分析完成。\n[{"id": "TC_001", "module": "login"}]'
        self.assertEqual(
            extract_json_from_text(text),
            [{"id": "TC_001", "module": "login"}],
        )

    def test_extract_json_from_fenced_block(self):
        text = '结果如下：\n```json\n{"cases": [{"id": "TC_001"}]}\n```'
        self.assertEqual(
            extract_json_from_text(text),
            {"cases": [{"id": "TC_001"}]},
        )

    def test_markdown_export_without_tabulate(self):
        df = pd.DataFrame([{"id": "TC_001", "step": "a|b\nc"}])
        self.assertEqual(
            dataframe_to_markdown(df),
            "| id | step |\n| --- | --- |\n| TC_001 | a\\|b<br>c |",
        )

    def test_decode_gb18030_text(self):
        self.assertEqual(RAGEngine._decode_text("登录".encode("gb18030")), "登录")

    def test_text_splitter_empty_text(self):
        self.assertEqual(TextSplitter.recursive_split(""), [])

    def test_openai_base_url_normalization(self):
        self.assertEqual(
            OpenAICompatibleClient._normalize_base_url("https://api.deepseek.com"),
            "https://api.deepseek.com/v1",
        )
        self.assertEqual(
            OpenAICompatibleClient._normalize_base_url("https://api.example.com/v1"),
            "https://api.example.com/v1",
        )

    def test_openai_flatten_rejects_pdf_payload(self):
        with self.assertRaises(ValueError):
            OpenAICompatibleClient.flatten_content([{"mime_type": "application/pdf", "data": b"x"}])

    def test_openai_image_payload_uses_image_url(self):
        content = OpenAICompatibleClient.to_chat_content([
            "look",
            {"mime_type": "image/png", "data": b"abc"},
        ])
        self.assertEqual(content[0], {"type": "text", "text": "look"})
        self.assertEqual(content[1]["type"], "image_url")
        self.assertTrue(content[1]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_normalize_cases_data_from_wrapped_dict(self):
        self.assertEqual(normalize_cases_data({"cases": [{"id": "TC_001"}]}), [{"id": "TC_001"}])

    def test_agent_revises_until_target_score(self):
        calls = {"evaluate": 0, "revise": 0}

        def fake_evaluate(cases):
            calls["evaluate"] += 1
            if calls["evaluate"] == 1:
                return {"score": 70, "summary": "missing edge cases", "coverage_gap": ["edge"], "logic_issues": [], "duplicates": [], "suggestions": []}
            return {"score": 90, "summary": "ok", "coverage_gap": [], "logic_issues": [], "duplicates": [], "suggestions": []}

        def fake_revise(cases, report):
            calls["revise"] += 1
            return cases + [{"id": "TC_002"}]

        agent = TestCaseAgent(
            api_key="sk-test",
            model_name="test-model",
            evaluate_func=fake_evaluate,
            revise_func=fake_revise,
            target_score=85,
            max_rounds=2,
        )
        result = agent.run("prd", [{"id": "TC_001"}])
        self.assertEqual(calls, {"evaluate": 2, "revise": 1})
        self.assertEqual(result["cases"], [{"id": "TC_001"}, {"id": "TC_002"}])
        self.assertEqual(result["report"]["score"], 90)
        self.assertEqual([step["action"] for step in result["trace"]], ["evaluate", "revise", "evaluate", "finish"])


if __name__ == "__main__":
    unittest.main()
