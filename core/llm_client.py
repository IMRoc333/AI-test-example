import google.generativeai as genai
import streamlit as st
import json
import re
import sys
import os

# 确保能引用到 config
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config.prompts import PromptManager
from config.settings import is_valid_api_key
from core.openai_compatible import DEFAULT_CHAT_MODEL, OpenAICompatibleClient


def get_available_models(api_key, provider="gemini", base_url=None):
    if provider == "openai_compatible":
        if not is_valid_api_key(api_key):
            return []
        try:
            return OpenAICompatibleClient(api_key, base_url).list_models()
        except Exception as e:
            print(f"获取 OpenAI-compatible 模型列表失败: {e}")
            return []
    return get_gemini_available_models(api_key)

@st.cache_data(ttl=3600)
def get_gemini_available_models(api_key):
    """动态获取当前Key可用的所有Chat模型"""
    if not is_valid_api_key(api_key):
        return []
    model_list = []
    try:
        genai.configure(api_key=api_key)
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                if "gemini" in m.name.lower():
                    model_list.append(m.name)
        model_list.sort()
    except Exception as e:
        print(f"获取模型列表失败: {e}")
        return []
    return model_list


def extract_json_from_text(text):
    """从 AI 的对话回复中提取 JSON 代码块"""
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    pattern = r"```(?:json)?\s*(.*?)```"
    matches = re.findall(pattern, text, re.DOTALL)
    
    if matches:
        longest_match = max(matches, key=len)
        try:
            return json.loads(longest_match.strip())
        except json.JSONDecodeError:
            pass

    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{]", text):
        try:
            obj, _ = decoder.raw_decode(text[match.start():])
            return obj
        except json.JSONDecodeError:
            continue
            
    return None


def get_chat_response(api_key, model_name, history, user_input, system_instruction=None, provider="gemini", base_url=None):
    if provider == "openai_compatible":
        try:
            return OpenAICompatibleClient(api_key, base_url).chat(
                model_name or DEFAULT_CHAT_MODEL,
                history,
                user_input,
                system_instruction=system_instruction,
            )
        except Exception as e:
            error_msg = f"OpenAI-compatible 模型调用出错: {str(e)}"
            print(error_msg)
            return error_msg, history
    return get_gemini_chat_response(api_key, model_name, history, user_input, system_instruction)


def get_gemini_chat_response(api_key, model_name, history, user_input, system_instruction=None):
    """支持上下文的对话接口"""
    genai.configure(api_key=api_key)
    
    try:
        model = genai.GenerativeModel(
            model_name, 
            system_instruction=system_instruction
        )
        chat = model.start_chat(history=history)
        response = chat.send_message(user_input)
        return response.text, chat.history
    except Exception as e:
        error_msg = f"模型调用出错: {str(e)}"
        print(error_msg)
        return error_msg, history

def generate_summary(api_key, content, model_name="models/gemini-1.5-flash", provider="gemini", base_url=None):
    if provider == "openai_compatible":
        try:
            return OpenAICompatibleClient(api_key, base_url).summarize(
                model_name or DEFAULT_CHAT_MODEL,
                PromptManager.SUMMARY_PROMPT,
                content,
            )
        except Exception as e:
            print(f"摘要生成失败: {e}")
            return "未命名业务文档"

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        input_str = str(content)[:8000]
        
        # 使用配置中的 Prompt
        prompt = PromptManager.SUMMARY_PROMPT
        
        response = model.generate_content([prompt, input_str])
        return response.text.strip()
    except Exception as e:
        print(f"摘要生成失败: {e}")
        return "未命名业务文档"
