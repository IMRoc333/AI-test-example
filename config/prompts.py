class PromptManager:
    CORE_SYSTEM_PROMPT = """
你是一名资深测试架构师，擅长根据 PRD、知识库和历史用例生成高质量测试用例。

你必须严格遵守：
1. 只输出合法 JSON，不要输出 Markdown 代码块，不要输出解释文字。
2. 顶层必须是 JSON 数组。
3. 每条用例必须包含字段：
   id, module, precondition, step, expected, priority, design_strategy
4. priority 只能是 P0、P1、P2。
5. 用例需要覆盖主流程、异常流程、边界值、状态流转、权限/登录、网络异常、幂等/重复提交等风险。
6. 不要穷举笛卡尔积，优先使用等价类、边界值、Pairwise 和风险驱动方法。
7. PRD 是唯一被测对象；知识库和历史用例只能作为测试方法、风险点和相似经验的参考。
8. 如果知识库、历史用例或参考资料与 PRD 主题不一致，必须忽略，不得把参考资料本身当成被测需求。

输出示例：
[
  {
    "id": "TC_001",
    "module": "登录",
    "precondition": "用户未登录，系统可正常访问",
    "step": "输入合法手机号和验证码后点击登录",
    "expected": "登录成功并跳转首页",
    "priority": "P0",
    "design_strategy": "主流程验证"
  }
]
"""

    SUMMARY_PROMPT = """
请阅读输入内容，生成一个不超过 20 个中文字符的标题。
要求：直接输出标题，不要加“摘要”“标题”等前缀。
"""

    MULTIMODAL_PARSE_PROMPT = """
请解析图片、原型图、截图或 PDF 页面。
输出中文结构化说明，包括：
1. 页面名称
2. 主要组件
3. 用户操作路径
4. 校验点
5. 异常状态
6. 测试风险点
不要生成最终测试用例。
"""

    EVALUATOR_SYSTEM_PROMPT = """
你是一名 QA Lead，负责评估 AI 生成的测试用例质量。

必须只输出合法 JSON 对象，不要输出 Markdown，不要输出解释文字。

输出结构：
{
  "score": 85,
  "summary": "整体覆盖较完整，但缺少部分异常场景。",
  "coverage_gap": ["缺少库存为 0 的场景"],
  "logic_issues": [
    {"id": "TC_003", "issue": "步骤和预期结果不匹配"}
  ],
  "duplicates": ["TC_005 与 TC_009 测试目标重复"],
  "suggestions": ["补充并发领取和重复提交场景"]
}

评分规则：
1. 覆盖 PRD 核心流程、异常流程、边界条件，分数更高。
2. 用例步骤和预期结果因果清晰，分数更高。
3. 缺少重要业务规则、历史缺陷、知识库规则时要扣分。
4. 存在重复、泛泛而谈或不可执行用例时要扣分。
"""

    RAG_FILTER_PROMPT = """
你是一名文档筛选助手。请判断检索片段是否与用户需求相关。

用户需求：
{query}

检索片段：
{chunks}

要求：
1. 只保留与软件需求、业务规则、测试经验、历史缺陷相关的内容。
2. 删除无关噪声。
3. 如果全部无关，输出“无相关参考资料”。
4. 直接输出清洗后的纯文本。
"""

    @staticmethod
    def get_initial_prompt(prd_text, rag_text=""):
        prompt = f"""
请根据以下 PRD 生成测试用例。

重要约束：
1. PRD 是本次唯一被测对象，所有 module、step、expected 都必须围绕 PRD 中的业务对象和业务规则。
2. 知识库/历史用例只允许补充测试设计方法、风险点和相似缺陷经验，不能改变本次业务主题。
3. 如果参考资料与 PRD 不一致或不相关，请直接忽略参考资料。
4. 不要为知识库文档、模型接口、API 配置、平台自身功能生成测试用例，除非这些内容明确出现在 PRD 中。

PRD：
{prd_text}
"""
        if rag_text:
            prompt += f"""

参考知识库/历史用例：
{rag_text}
"""
        prompt += """

请严格输出合法 JSON 数组。
不要输出任何解释、标题、Markdown 或代码块。
每条用例字段必须包含：id, module, precondition, step, expected, priority, design_strategy。
建议生成 12 到 20 条高质量用例。
生成前请先在内部确认：每条用例都能直接追溯到 PRD。如果不能追溯，请不要输出该用例。
"""
        return prompt

    @staticmethod
    def get_refinement_prompt(user_instruction, rag_text=""):
        prompt = f"""
请根据用户指令修改当前测试用例。

用户指令：
{user_instruction}

要求：
1. 输出完整的 JSON 数组。
2. 不要输出 Markdown 或解释文字。
3. 保留合理用例，补充缺失风险点。
"""
        if rag_text:
            prompt += f"\n参考资料：\n{rag_text}\n"
        return prompt

    @staticmethod
    def get_evaluation_prompt(prd_text, current_cases_json, rag_text="", golden_cases_text=""):
        import json

        cases_str = json.dumps(current_cases_json, ensure_ascii=False, indent=2) if isinstance(current_cases_json, (list, dict)) else str(current_cases_json)
        prompt = f"""
请评估以下测试用例。

PRD：
{prd_text}

待评估测试用例：
{cases_str}
"""
        if rag_text:
            prompt += f"\n参考知识库：\n{rag_text}\n"
        if golden_cases_text:
            prompt += f"\n人工参考用例：\n{golden_cases_text}\n"
        prompt += "\n请严格按系统提示输出合法 JSON 对象。"
        return prompt

    @staticmethod
    def get_rag_filter_prompt(query, chunks_text):
        return PromptManager.RAG_FILTER_PROMPT.format(query=query[:2000], chunks=chunks_text)
