import streamlit as st
from config.settings import load_config, save_config, is_valid_api_key
from core.llm_client import get_available_models
from core.openai_compatible import DEFAULT_BASE_URL, DEFAULT_CHAT_MODEL, DEFAULT_EMBEDDING_MODEL

def render_sidebar():
    """渲染侧边栏并返回配置"""
    config = load_config()
    
    with st.sidebar:
        st.header("🔑 配置中心")
        
        provider_options = {
            "Gemini": "gemini",
            "OpenAI-compatible": "openai_compatible",
        }
        current_provider = config.get("provider", "gemini")
        provider_label = st.selectbox(
            "模型服务",
            list(provider_options.keys()),
            index=1 if current_provider == "openai_compatible" else 0,
        )
        provider = provider_options[provider_label]

        # 1. API Key 输入
        api_key = st.text_input("API Key", value=config.get('api_key', ''), type="password")
        base_url = config.get("base_url", DEFAULT_BASE_URL)
        chat_model = config.get("model_name", DEFAULT_CHAT_MODEL)
        embedding_model = config.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
        if provider == "openai_compatible":
            base_url = st.text_input("Base URL", value=base_url, help="例如 https://api.deepseek.com 或 https://dashscope.aliyuncs.com/compatible-mode")
            chat_model = st.text_input("默认模型名", value=chat_model)
            embedding_model = st.text_input("Embedding 模型", value=embedding_model)
        
        # 保存按钮
        if st.button("💾 保存配置"):
            save_config({
                'provider': provider,
                'api_key': api_key,
                'base_url': base_url,
                'model_name': chat_model,
                'embedding_model': embedding_model,
            })
            st.success("配置已保存")

        st.divider()

        # 2. 动态模型选择
        selected_model = chat_model if provider == "openai_compatible" else "models/gemini-1.5-flash" # 默认兜底
        if is_valid_api_key(api_key):
            with st.spinner("正在联网获取模型列表..."):
                available_models = get_available_models(api_key, provider=provider, base_url=base_url)
            
            if available_models:
                # 智能默认选中 Pro，因为效果更好
                default_idx = 0
                if provider == "openai_compatible" and selected_model in available_models:
                    default_idx = available_models.index(selected_model)
                else:
                    for i, name in enumerate(available_models):
                        if "gemini-1.5-pro" in name and "latest" in name:
                            default_idx = i
                            break
                        elif "gemini-1.5-pro" in name: # 次优选择
                            default_idx = i
                
                selected_model = st.selectbox("🤖 选择模型", available_models, index=default_idx)
            else:
                st.warning("无法获取模型列表，请手动填写模型名")
                selected_model = st.text_input("模型名", value=config.get("model_name", selected_model))
        else:
            st.info("请输入 API Key 以解锁高级模型选择")
            
        # 3. 清空按钮
        st.divider()
        if st.button("🗑️ 清空工作台", type="secondary"):
            # 清除 session_state
            for key in [
                'res_df', 'res_data', 'prd_cache', 'messages', 'gemini_history',
                'prd_context', 'rag_context', 'rag_sources_display',
                'rag_sources_list', 'processed_files', 'eval_report',
                'current_prompt_content', 'active_provider', 'agent_trace'
            ]:
                if key in st.session_state:
                    del st.session_state[key]
            st.rerun()
            
    return api_key, selected_model, provider, base_url, embedding_model
