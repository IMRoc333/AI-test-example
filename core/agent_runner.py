import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from config.prompts import PromptManager
from core.llm_client import extract_json_from_text, get_chat_response


def normalize_cases_data(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("cases", "test_cases", "data", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return [data]
    return []


def build_revision_prompt(prd_text, current_cases, report, rag_context=""):
    cases_str = json.dumps(current_cases, ensure_ascii=False, indent=2)
    report_str = json.dumps(report, ensure_ascii=False, indent=2)
    prompt = f"""
你是测试用例修正 Agent。请根据评估报告优化当前测试用例。

要求：
1. 保留合理用例，不要无意义重写。
2. 补充 coverage_gap、logic_issues、duplicates、suggestions 中指出的问题。
3. 删除明显重复或逻辑冲突的用例。
4. 必须输出完整、合法的 JSON 数组。
5. 不要输出 Markdown、解释文字或代码块。
6. 每条用例必须包含 id, module, precondition, step, expected, priority, design_strategy, source, source_detail。
7. source 只能从以下值选择：PRD明确规则、用户澄清、知识库规则、历史缺陷、AI风险推理。
8. source_detail 必须说明该用例可追溯到哪条 PRD、澄清答案、知识库规则或风险推理。

PRD：
{prd_text}

当前测试用例：
{cases_str}

评估报告：
{report_str}
"""
    if rag_context:
        prompt += f"\n参考知识库：\n{rag_context}\n"
    prompt += "\n请直接输出修正后的完整 JSON 数组。"
    return prompt


@dataclass
class AgentStep:
    round: int
    action: str
    score: Optional[int] = None
    summary: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


class TestCaseAgent:
    def __init__(
        self,
        api_key,
        model_name,
        provider="gemini",
        base_url=None,
        evaluator=None,
        target_score=85,
        max_rounds=2,
        evaluate_func: Optional[Callable[[Any], Dict[str, Any]]] = None,
        revise_func: Optional[Callable[[Any, Dict[str, Any]], Any]] = None,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.provider = provider
        self.base_url = base_url
        self.evaluator = evaluator
        self.target_score = int(target_score)
        self.max_rounds = int(max_rounds)
        self.evaluate_func = evaluate_func
        self.revise_func = revise_func

    def evaluate(self, prd_text, cases, rag_context="", golden_cases_content=""):
        if self.evaluate_func:
            return self.evaluate_func(cases)
        if not self.evaluator:
            raise ValueError("TestCaseAgent requires evaluator or evaluate_func")
        return self.evaluator.evaluate_cases(
            self.model_name,
            prd_text,
            cases,
            rag_context=rag_context,
            golden_cases_content=golden_cases_content,
        )

    def revise(self, prd_text, cases, report, rag_context=""):
        if self.revise_func:
            return self.revise_func(cases, report)

        prompt = build_revision_prompt(prd_text, cases, report, rag_context=rag_context)
        response_text, _ = get_chat_response(
            self.api_key,
            self.model_name,
            [],
            prompt,
            system_instruction=PromptManager.CORE_SYSTEM_PROMPT,
            provider=self.provider,
            base_url=self.base_url,
        )
        revised = extract_json_from_text(response_text)
        if not revised:
            raise ValueError(f"修正 Agent 未返回有效 JSON: {response_text[:300]}")
        return normalize_cases_data(revised)

    @staticmethod
    def _score(report):
        try:
            return int(report.get("score", 0))
        except Exception:
            return 0

    @staticmethod
    def _issue_count(report):
        total = 0
        for key in ("coverage_gap", "logic_issues", "duplicates", "suggestions"):
            value = report.get(key)
            if isinstance(value, list):
                total += len(value)
        return total

    def run(self, prd_text, initial_cases, rag_context="", golden_cases_content=""):
        cases = normalize_cases_data(initial_cases)
        trace: List[AgentStep] = []
        final_report = None

        for round_no in range(1, self.max_rounds + 2):
            report = self.evaluate(prd_text, cases, rag_context, golden_cases_content)
            final_report = report
            score = self._score(report)
            trace.append(
                AgentStep(
                    round=round_no,
                    action="evaluate",
                    score=score,
                    summary=report.get("summary", ""),
                    details={
                        "issue_count": self._issue_count(report),
                        "coverage_gap": report.get("coverage_gap", []),
                        "logic_issues": report.get("logic_issues", []),
                        "duplicates": report.get("duplicates", []),
                    },
                )
            )

            if score >= self.target_score:
                trace.append(
                    AgentStep(
                        round=round_no,
                        action="finish",
                        score=score,
                        summary=f"score {score} reached target {self.target_score}",
                    )
                )
                break

            if round_no > self.max_rounds:
                trace.append(
                    AgentStep(
                        round=round_no,
                        action="stop",
                        score=score,
                        summary="max revision rounds reached",
                    )
                )
                break

            cases = self.revise(prd_text, cases, report, rag_context=rag_context)
            trace.append(
                AgentStep(
                    round=round_no,
                    action="revise",
                    score=score,
                    summary=f"revised cases to {len(cases)} items",
                    details={"case_count": len(cases)},
                )
            )

        return {
            "cases": cases,
            "report": final_report,
            "trace": [step.__dict__ for step in trace],
        }
