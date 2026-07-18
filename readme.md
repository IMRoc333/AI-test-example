# AI 测试用例生成平台

基于 React、FastAPI、RAG、Multi-Agent 和 OpenAI-compatible 大模型接口的 PRD 测试用例生成平台。

项目面向“不规范需求文档到结构化测试用例”的真实测试场景，支持上传 PRD、PDF、UI 截图或直接粘贴需求文本，并结合知识库、历史缺陷和 Agent 式质量评估生成测试用例。

## 核心能力

- PRD 测试用例自动生成
- OpenAI-compatible 通用接口，支持国产大模型平台
- 向量知识库召回，支持业务规则、历史缺陷、测试经验沉淀
- PDF 文本抽取与图片/PDF 多模态解析
- LLM-as-Judge 质量评估
- Agent 式迭代优化，根据评分和缺口自动修正用例
- 测试用例导出为 JSON、CSV、Markdown
- 历史任务和历史用例管理
- 需求结构化与测试模块树确认
- Multi-Agent 拆工：文档解析 Agent、模块生成 Agent、用例生成 Agent、优化 Agent
- Agent 优化后提炼可复用测试规则，并沉淀到知识库

## 技术架构

```text
React 前端
  -> FastAPI 后端
    -> 文档解析 / 多模态解析
    -> 文档解析 Agent
    -> 模块生成 Agent
    -> 人工确认模块树
    -> RAG 知识库召回
    -> 用例生成 Agent
    -> JSON 解析与修复
    -> 评估优化 Agent
    -> 规则沉淀 Agent
```

主要目录：

```text
api/                 FastAPI 接口层
core/                LLM、RAG、Multi-Agent、文档解析等核心逻辑
config/              Prompt 和配置
web/                 React 前端
tests/               单元测试
test_prd/            示例 PRD 和测试素材
data/                本地数据目录，运行时向量库不提交
```

## 模型配置

在前端“模型设置”页配置：

```text
接口类型：OpenAI-compatible 通用接口
API Key：模型平台密钥
Base URL：平台兼容接口地址
对话模型：用于生成、评估、优化
向量模型：用于知识库 embedding
视觉模型：用于 UI 图、PDF 页面截图解析
```

DashScope 示例：

```text
Base URL: https://dashscope.aliyuncs.com/compatible-mode
对话模型: qwen3.7-plus
向量模型: text-embedding-v4
视觉模型: qwen3.7-plus
```

后端会自动补齐 `/v1`，上面的地址实际请求为：

```text
https://dashscope.aliyuncs.com/compatible-mode/v1
```

## 本地启动

安装 Python 依赖：

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

启动后端：

```bash
.venv\Scripts\python -m uvicorn api.main:app --host 127.0.0.1 --port 8000
```

安装并启动前端：

```bash
cd web
npm install
npm run dev
```

访问：

```text
http://127.0.0.1:5173
```

## 测试

```bash
.venv\Scripts\python -m unittest discover -s tests -v
```

前端构建：

```bash
cd web
npm run build
```

## 项目亮点

这个项目不是简单的大模型文本生成，而是把测试用例生成拆成多个工程阶段：

1. 需求解析：支持文本、PDF、图片和多模态输入。
2. 文档解析 Agent：抽取需求摘要、角色、业务对象、核心流程、明确规则和疑点。
3. 模块生成 Agent：把文档解析结果转成测试模块树、测试点、风险点和待确认问题。
4. 人工确认：用户确认或编辑模块树后再生成用例，避免 AI 直出跑偏。
5. 知识召回：基于向量检索召回业务规则、历史缺陷和测试经验。
6. 用例生成 Agent：基于确认后的模块树生成结构化 JSON 测试用例。
7. 跑偏防护：PRD 是唯一被测对象，知识库只作为参考。
8. 评估优化 Agent：从覆盖率、逻辑一致性、重复度、缺失场景等维度评分并迭代修正。
9. 规则沉淀 Agent：从优化结果中提炼可复用测试规则，并由用户确认保存到知识库。

适合在简历中描述为：

> 参考快手智能测试用例生成系统的多阶段演进思路，设计并实现了基于 RAG 增强和 Multi-Agent 协作的 PRD 测试用例生成平台。系统将非规范需求处理拆分为文档解析 Agent、模块生成 Agent、用例生成 Agent、评估优化 Agent 和规则沉淀 Agent，支持 OpenAI-compatible 国产大模型、多模态 PRD 解析、人工确认模块树、知识库召回和 LLM-as-Judge 质量评估，解决直接调用大模型时业务理解不足、输出不稳定和覆盖不完整的问题。
