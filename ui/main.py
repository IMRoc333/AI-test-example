import streamlit as st
import pandas as pd
import json
import sys
import os
from PIL import Image

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config.settings import setup_proxy, is_valid_api_key
from config.prompts import PromptManager
from ui.sidebar import render_sidebar
from ui.components import display_results
from core.llm_client import get_chat_response, generate_summary, extract_json_from_text
from core.rag_engine import RAGEngine
from core.agent_runner import TestCaseAgent
from core.document_parser import extract_pdf_text
from core.evaluator import Evaluator # 新增引用

def split_text_and_json(text):
    """分离 AI 回复中的【分析说明】和【JSON数据】"""
    json_data = extract_json_from_text(text)
    if not json_data:
        return text, None
    
    text_stripped = text.strip()
    split_idx_list = text_stripped.find('[')
    split_idx_dict = text_stripped.find('{')
    split_idx = -1
    if split_idx_list != -1 and split_idx_dict != -1:
        split_idx = min(split_idx_list, split_idx_dict)
    elif split_idx_list != -1:
        split_idx = split_idx_list
    elif split_idx_dict != -1:
        split_idx = split_idx_dict
    
    if split_idx > 0:
        explanation = text_stripped[:split_idx].strip()
        explanation = explanation.replace("```json", "").replace("```", "").strip()
        if len(explanation) < 2: 
            explanation = "✅ 已根据指令生成最新测试用例数据（详情请见右侧预览）"
        return explanation, json_data
    
    if text_stripped.startswith("[") or text_stripped.startswith("{") or text_stripped.startswith("```"):
        return "✅ 已根据指令生成最新测试用例数据（详情请见右侧预览）", json_data
        
    return text, json_data


def normalize_cases_data(data):
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("cases", "test_cases", "data", "items"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return []

def main():
    setup_proxy()
    st.set_page_config(page_title="Auto_prd_test_expert", layout="wide")
    
    # Session 初始化
    if 'messages' not in st.session_state: st.session_state['messages'] = [] 
    if 'gemini_history' not in st.session_state: st.session_state['gemini_history'] = [] 
    if 'res_data' not in st.session_state: st.session_state['res_data'] = None 
    if 'prd_context' not in st.session_state: st.session_state['prd_context'] = "" 
    if 'rag_context' not in st.session_state: st.session_state['rag_context'] = "" 
    if 'rag_sources_display' not in st.session_state: st.session_state['rag_sources_display'] = None
    if 'processed_files' not in st.session_state: st.session_state['processed_files'] = []
    # 新增：评估报告状态
    if 'eval_report' not in st.session_state: st.session_state['eval_report'] = None
    if 'agent_trace' not in st.session_state: st.session_state['agent_trace'] = []

    api_key, selected_model, provider, base_url, embedding_model = render_sidebar()
    provider_state_key = f"{provider}:{base_url}"
    if st.session_state.get('active_provider') != provider_state_key:
        st.session_state['gemini_history'] = []
        st.session_state['active_provider'] = provider_state_key
    rag_engine = None
    evaluator = None # 初始化评估器

    if is_valid_api_key(api_key):
        try:
            rag_engine = RAGEngine(api_key, provider=provider, base_url=base_url, embedding_model=embedding_model)
            evaluator = Evaluator(api_key, provider=provider, base_url=base_url) # 实例化评估器
        except Exception as e:
            st.sidebar.error(f"引擎初始化失败: {e}")

    st.title("🤖 Auto_prd_test_expert")

    tab_work, tab_manage = st.tabs(["💬 智能共创工作台", "📚 知识库管理"])

    # ==================== Tab 1: 共创工作台 ====================
    with tab_work:
        col_chat, col_preview = st.columns([0.4, 0.6], gap="medium")

        # --- 左侧：对话交互区 ---
        with col_chat:
            st.subheader("需求对话")
            
            # 1. 常驻文件上传区
            with st.expander("📂 上传/补充需求文档", expanded=not st.session_state['messages']):
                uploaded_files = st.file_uploader("拖拽文件至此", accept_multiple_files=True, key="chat_uploader")
                
                c1, c2 = st.columns(2)
                use_kb = c1.checkbox("📚 参考技术规范", value=True)
                use_hist = c2.checkbox("🕰️ 参考历史案例", value=True)

                if uploaded_files and rag_engine and is_valid_api_key(api_key):
                    current_file_names = [f.name for f in uploaded_files]
                    if current_file_names != st.session_state['processed_files']:
                        with st.spinner("正在预处理文档并检索知识库..."):
                            preview_txt = ""
                            prompt_content = []
                            for file in uploaded_files:
                                file.seek(0)
                                if "image" in file.type:
                                    if provider == "openai_compatible":
                                        prompt_content.extend([f"图片 {file.name}:", {"mime_type": file.type, "data": file.read()}])
                                    else:
                                        img = Image.open(file)
                                        prompt_content.extend([f"图片 {file.name}:", img])
                                    preview_txt += f"[图片 {file.name}] "
                                elif "pdf" in file.type:
                                    pdf_bytes = file.read()
                                    if provider == "openai_compatible":
                                        txt = extract_pdf_text(pdf_bytes)
                                        prompt_content.append(f"文档 {file.name}:\n{txt}")
                                        preview_txt += txt[:500]
                                    else:
                                        prompt_content.extend([f"文档 {file.name}:", {"mime_type": "application/pdf", "data": pdf_bytes}])
                                        preview_txt += f"[PDF {file.name}] "
                                else:
                                    txt = RAGEngine._decode_text(file.read())
                                    prompt_content.append(f"文档 {file.name}:\n{txt}")
                                    preview_txt += txt[:500]
                            # 1. 粗筛：检索 RAG (这里稍微放大一点召回范围，比如 n_results=3 或 5，rag_engine里改不改都行，暂保持3)
                            raw_rag_info, sources = rag_engine.search_context(preview_txt, use_history=use_hist, use_knowledge=use_kb)

                            # --- 新增：LLM 细筛 (Filtering) ---
                            final_rag_context = ""
                            if raw_rag_info:
                                with st.spinner("正在进行知识提纯 (去除无关噪音)..."):
                                    # 构造过滤指令
                                    filter_prompt = PromptManager.get_rag_filter_prompt(preview_txt, raw_rag_info)
                                    
                                    # 调用 LLM (建议用 Flash 模型，速度快)
                                    # 注意：这里直接复用统一的 chat 接口
                                    # 为了方便，假设我们复用现有的 chat 接口，但不带历史记录
                                    filtered_text, _ = get_chat_response(
                                        api_key, 
                                        selected_model, # 或者强制指定 "models/gemini-1.5-flash" 以提速
                                        [], # 无历史
                                        filter_prompt,
                                        provider=provider,
                                        base_url=base_url
                                    )
                                    
                                    # 判断清洗结果
                                    if "无相关参考资料" in filtered_text:
                                        final_rag_context = ""
                                    else:
                                        final_rag_context = filtered_text

                            # 2. 更新 Session
                            st.session_state['rag_context'] = final_rag_context
                            st.session_state['prd_context'] = preview_txt 
                            st.session_state['current_prompt_content'] = prompt_content

                            if sources and final_rag_context:
                                source_list = "\n".join(sources)
                                # 展示时，展示清洗后的纯净内容
                                st.session_state['rag_sources_list'] = f"\n{source_list}\n"
                            else:
                                st.session_state['rag_sources_list'] = "经 AI 分析，知识库中暂无与当前 PRD 强相关的技术规范。"
                                
                            st.session_state['processed_files'] = current_file_names
                            st.toast("✅ 知识库检索完成！")

            # 2. 按钮逻辑
            btn_label = "🚀 开始生成" if not st.session_state['messages'] else "📤 发送补充文件并分析"
            if st.button(btn_label, type="primary", use_container_width=True):
                if not is_valid_api_key(api_key): st.error("请配置 API Key"); st.stop()
                
                if 'current_prompt_content' in st.session_state:
                    with st.spinner(f"正在使用 {selected_model} 分析..."):
                        initial_prompt = PromptManager.get_initial_prompt(
                            st.session_state['prd_context'], 
                            st.session_state['rag_context']
                        )
                        full_payload = initial_prompt + st.session_state.get('current_prompt_content', [])
                        
                        resp_text, updated_history = get_chat_response(
                            api_key, selected_model, 
                            st.session_state['gemini_history'], 
                            full_payload, 
                            system_instruction=PromptManager.CORE_SYSTEM_PROMPT,
                            provider=provider,
                            base_url=base_url
                        )
                        
                        st.session_state['gemini_history'] = updated_history
                        st.session_state['messages'].append({"role": "assistant", "content": resp_text})
                        
                        json_data = extract_json_from_text(resp_text)
                        if json_data:
                            st.session_state['res_data'] = json_data
                            st.session_state['eval_report'] = None # 重新生成后清空旧的评估报告
                            st.session_state['agent_trace'] = []
                        
                        del st.session_state['current_prompt_content'] 
                        st.rerun()
                else:
                    if not st.session_state['messages']: st.warning("请先上传文件")
                    else: st.info("请在下方输入框继续对话")

            # 3. 聊天流渲染
            chat_container = st.container(height=500)
            with chat_container:
                if st.session_state.get('rag_context'):
                    with st.expander("📚 本次对话参考的知识库片段 (RAG Context)", expanded=False):
                        
                        # 1. 顶部统一显示所有来源 (Header)
                        raw_sources = st.session_state.get('rag_sources_list', '未知来源')
                        header_title = raw_sources.replace("\n- ", "  &  ").replace("- ", "").strip()
                        
                        # 用 caption 或者 markdown 显示在最上方，不占用蓝色框的位置
                        st.markdown(f"**📄 引用来源:** *{header_title}*")
                        
                        # 2. 内容分段渲染 (Body)
                        # 使用双换行符 \n\n 进行切分，通常 LLM 会用空行来区分不同的逻辑段落
                        # 这样可以将一大段文本拆解成几个独立的蓝色卡片，视觉上更轻松
                        fragments = st.session_state['rag_context'].split('<<<RAG_SEP>>>')
                        
                        for frag in fragments:
                            if frag.strip():
                                # 为每一段核心内容生成一个独立的蓝色方块
                                st.info(frag.strip())

                for msg in st.session_state['messages']:
                    with st.chat_message(msg["role"]):
                        if msg["role"] == "user":
                            st.markdown(msg["content"])
                        else:
                            explanation, _ = split_text_and_json(msg["content"])
                            st.markdown(explanation)
                            if "```json" in msg["content"] or "[" in msg["content"]:
                                with st.expander("🔍 查看 JSON 数据", expanded=False):
                                    st.code(msg["content"][-1000:] if len(msg["content"]) > 1000 else msg["content"], language="json")

            # 4. 底部对话输入
            if prompt := st.chat_input("输入指令 (如: '增加几个异常场景')"):
                if not is_valid_api_key(api_key): st.stop()
                st.session_state['messages'].append({"role": "user", "content": prompt})
                with chat_container:
                    with st.chat_message("user"):
                        st.markdown(prompt)

                with chat_container:
                    with st.chat_message("assistant"):
                        with st.spinner("AI 正在思考..."):
                            refine_prompt_str = PromptManager.get_refinement_prompt(
                                prompt, st.session_state['rag_context']
                            )
                            
                            resp_text, updated_history = get_chat_response(
                                api_key, selected_model, 
                                st.session_state['gemini_history'], 
                                refine_prompt_str,
                                system_instruction=PromptManager.CORE_SYSTEM_PROMPT,
                                provider=provider,
                                base_url=base_url
                            )
                            
                            explanation, new_json = split_text_and_json(resp_text)
                            st.markdown(explanation)
                            if new_json:
                                with st.expander("查看数据详情"):
                                    st.caption("数据已更新")
                            
                            st.session_state['gemini_history'] = updated_history
                            st.session_state['messages'].append({"role": "assistant", "content": resp_text})
                            
                            if new_json:
                                st.session_state['res_data'] = new_json
                                st.session_state['eval_report'] = None # 数据更新后清空评估
                                st.session_state['agent_trace'] = []
                                st.rerun()

        # --- 右侧：预览、归档与评估 ---
        with col_preview:
            st.subheader("📄 实时结果预览")
            
            if st.session_state['res_data']:
                cases_data = normalize_cases_data(st.session_state['res_data'])
                df = pd.DataFrame(cases_data)
                module_list = df['module'].unique() if 'module' in df.columns else []
                st.caption(f"📊 当前共 **{len(df)}** 条用例 | 覆盖模块: {', '.join(module_list)}")
                
                # 新增 "⚖️ 智能评估" Tab
                tab_table, tab_json, tab_eval = st.tabs(["📊 表格视图", "🔍 源码/编辑", "⚖️ 智能评估"])
                
                with tab_table:
                    display_results(df, st.session_state['res_data'])
                
                with tab_json:
                    json_str_val = json.dumps(st.session_state['res_data'], indent=2, ensure_ascii=False)
                    edited_json_str = st.text_area("直接编辑 JSON", value=json_str_val, height=600)
                    if st.button("应用 JSON 修改", use_container_width=True):
                        try:
                            st.session_state['res_data'] = json.loads(edited_json_str)
                            st.session_state['eval_report'] = None
                            st.session_state['agent_trace'] = []
                            st.success("JSON 修改已应用")
                            st.rerun()
                        except json.JSONDecodeError as e:
                            st.error(f"JSON 格式错误: {e}")

                # ==================== 智能评估模块 (新增) ====================
                with tab_eval:
                    st.markdown("### 🕵️ 质量质检 & 智能对抗评估")
                    st.info("利用 AI 扮演 'QA 验收负责人'，基于 PRD 和 RAG 规范对当前生成的用例进行查漏补缺。")
                    
                    # 1. 选填：上传标准答案
                    golden_file = st.file_uploader("上传标准参考用例 (可选，作为对比标杆)", type=['json', 'txt', 'md'], help="如果有已存在的正确用例，上传后 AI 将进行对比分析")
                    golden_content = ""
                    if golden_file:
                        golden_content = RAGEngine._decode_text(golden_file.getvalue())[:10000] # 限制长度

                    agent_col1, agent_col2 = st.columns(2)
                    target_score = agent_col1.number_input("Agent target score", min_value=50, max_value=100, value=85, step=5)
                    max_rounds = agent_col2.number_input("Max revise rounds", min_value=1, max_value=5, value=2, step=1)

                    if st.button("Run Agentic Auto-Optimize", use_container_width=True):
                        if evaluator:
                            with st.spinner("Agent is evaluating and revising cases..."):
                                agent = TestCaseAgent(
                                    api_key,
                                    selected_model,
                                    provider=provider,
                                    base_url=base_url,
                                    evaluator=evaluator,
                                    target_score=target_score,
                                    max_rounds=max_rounds,
                                )
                                result = agent.run(
                                    st.session_state.get('prd_context', ''),
                                    st.session_state['res_data'],
                                    rag_context=st.session_state.get('rag_context', ''),
                                    golden_cases_content=golden_content,
                                )
                                st.session_state['res_data'] = result['cases']
                                st.session_state['eval_report'] = result['report']
                                st.session_state['agent_trace'] = result['trace']
                                st.success("Agentic optimization finished")
                                st.rerun()
                        else:
                            st.error("Evaluator is not initialized")

                    if st.session_state.get('agent_trace'):
                        with st.expander("Agent execution trace", expanded=True):
                            for step in st.session_state['agent_trace']:
                                score_text = "" if step.get("score") is None else f" | score={step.get('score')}"
                                st.markdown(f"**Round {step.get('round')} - {step.get('action')}**{score_text}")
                                if step.get("summary"):
                                    st.caption(step.get("summary"))
                                if step.get("details"):
                                    st.json(step.get("details"))

                    # 2. 评估按钮
                    if st.button("⚖️ 开始全面评估", use_container_width=True):
                        if evaluator:
                            with st.spinner("QA 专家正在审查用例... (检查覆盖率、逻辑一致性、去重)"):
                                report = evaluator.evaluate_cases(
                                    selected_model,
                                    st.session_state.get('prd_context', '无详细PRD'),
                                    st.session_state['res_data'],
                                    rag_context=st.session_state.get('rag_context', ''),
                                    golden_cases_content=golden_content
                                )
                                st.session_state['eval_report'] = report
                                st.toast("评估完成！")
                        else:
                            st.error("评估器未初始化")

                    # 3. 结果渲染
                    if st.session_state['eval_report']:
                        report = st.session_state['eval_report']
                        
                        # 仪表盘
                        c_score, c_sum = st.columns([1, 3])
                        score = report.get('score', 0)
                        
                        # 颜色逻辑
                        color = "normal"
                        if score >= 90: color = "normal" # Streamlit metric 不支持直接绿色，这里用默认
                        elif score < 60: color = "off" # 变灰或红

                        c_score.metric("质量评分", f"{score} 分", delta=None)
                        c_sum.info(f"**总评**: {report.get('summary', '无')}")

                        st.divider()

                        # 详情列表
                        e1, e2 = st.columns(2)
                        with e1:
                            st.markdown("#### ⚠️ 发现问题")
                            if report.get('coverage_gap'):
                                st.error(f"**漏测风险 (Gap)**:\n" + "\n".join([f"- {i}" for i in report['coverage_gap']]))
                            else:
                                st.success("未发现明显覆盖率缺失")
                                
                            if report.get('logic_issues'):
                                logic_lines = []
                                for item in report['logic_issues']:
                                    if isinstance(item, dict):
                                        logic_lines.append(f"- {item.get('id', '-')}: {item.get('issue', item)}")
                                    else:
                                        logic_lines.append(f"- {item}")
                                st.warning(f"**逻辑/幻觉风险**:\n" + "\n".join(logic_lines))
                            else:
                                st.success("逻辑一致性良好")
                        
                        with e2:
                            st.markdown("#### 💡 优化建议")
                            if report.get('duplicates'):
                                st.warning(f"**重复冗余**:\n" + "\n".join([f"- {i}" for i in report['duplicates']]))
                            else:
                                st.success("无重复用例")
                            
                            if report.get('suggestions'):
                                st.info(f"**改进方向**:\n" + "\n".join([f"- {i}" for i in report['suggestions']]))

                st.divider()
                # 归档按钮
                if st.button("💾 确认最终版并归档入库", type="primary", use_container_width=True):
                    if rag_engine:
                        try:
                            final_data = json.loads(edited_json_str) if 'edited_json_str' in locals() else st.session_state['res_data']
                            with st.spinner("归档中..."):
                                summary = generate_summary(api_key, str(final_data), model_name=selected_model, provider=provider, base_url=base_url)
                                rag_engine.add_history_case(st.session_state.get('prd_context', '对话生成的用例'), final_data, summary=summary)
                                st.success(f"已归档: {summary}")
                                st.balloons()
                        except Exception as e:
                            st.error(f"归档失败: {e}")
            else:
                st.info("👈 请在左侧上传 PRD 文档")

    # ==================== Tab 2: 知识库管理 ====================
    with tab_manage:
        st.header("🗂️ 知识库管理后台")
        
        with st.expander("➕ 上传新知识", expanded=False):
            kb_file = st.file_uploader("上传规范文档/历史资料", type=["txt", "md", "pdf", "jpg", "png"], key="kb_upload")
            if kb_file and st.button("上传并处理", key="kb_btn"):
                if rag_engine:
                    with st.spinner(f"正在智能解析..."):
                        kb_file.seek(0)
                        parsed_text = ""
                        if "text" in kb_file.type:
                            parsed_text = RAGEngine._decode_text(kb_file.getvalue())
                        else:
                            parsed_text = rag_engine.parse_file_content(kb_file, kb_file.type, model_name=selected_model)
                        
                        summary = generate_summary(api_key, parsed_text[:5000], model_name=selected_model, provider=provider, base_url=base_url)
                        kb_file.seek(0)
                        rag_engine.add_knowledge(kb_file, summary=summary, content_text=parsed_text, model_name=selected_model)
                        st.success(f"✅ 已存入！摘要：{summary}")
                        st.rerun()

        st.divider()
        col_kb, col_hist = st.columns(2)
        
        def render_doc_list(doc_type, title, icon):
            st.subheader(f"{icon} {title}")
            if rag_engine:
                docs = rag_engine.list_documents(doc_type)
                if docs:
                    df = pd.DataFrame(docs)
                    st.dataframe(df[["文件名/标题", "AI摘要", "录入时间", "ID"]], use_container_width=True, hide_index=True)
                    c1, c2 = st.columns([3, 1])
                    input_key = f"id_{doc_type}"
                    del_id = c1.text_input("输入 ID 进行操作", key=input_key, placeholder=f"粘贴 ID")
                    
                    if c2.button("🗑️ 删除", key=f"del_{doc_type}"):
                        if del_id:
                            rag_engine.delete_document(del_id, doc_type)
                            st.success(f"ID {del_id} 已删除"); st.rerun()
                            
                    if c2.button("👀 预览", key=f"view_{doc_type}"):
                        if del_id:
                            target = next((d for d in docs if d['ID'] == del_id), None)
                            if target:
                                st.info(f"正在预览: {target['文件名/标题']}")
                                content = rag_engine.get_doc_content(target['原始路径'], doc_id=target['ID'], collection_type=doc_type)
                                lang = "json" if doc_type == "history" else "markdown"
                                if lang == "json":
                                    try:
                                        content_obj = json.loads(content)
                                        content = json.dumps(content_obj, indent=2, ensure_ascii=False)
                                    except: pass
                                if "无法获取" in content: st.warning(content)
                                else: st.code(content, language=lang)
        with col_kb: render_doc_list("knowledge", "技术规范", "📚")
        with col_hist: render_doc_list("history", "历史案例", "🕰️")

if __name__ == "__main__":
    main()
