import streamlit as st
import pandas as pd
import json
import yaml


def dataframe_to_markdown(df):
    if df is None or df.empty:
        return ""

    def cell(value):
        try:
            empty = pd.isna(value)
            if not isinstance(empty, bool):
                empty = False
        except Exception:
            empty = False
        text = "" if empty else str(value)
        return text.replace("\n", "<br>").replace("|", "\\|")

    headers = [cell(col) for col in df.columns]
    rows = ["| " + " | ".join(headers) + " |"]
    rows.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for _, row in df.iterrows():
        rows.append("| " + " | ".join(cell(row[col]) for col in df.columns) + " |")
    return "\n".join(rows)


def display_results(df, raw_json):
    """渲染结果表格和下载区"""
    if df is not None:
        st.divider()
        st.subheader("📊 结果预览")
        
        # 展示前5条
        st.table(df.head(5))
        if len(df) > 5:
            st.caption(f"... 还有 {len(df)-5} 条用例未在页面展示，请下载完整文件查看。")
        
        st.subheader("💾 导出结果")
        c1, c2, c3, c4 = st.columns(4)
        
        # 1. CSV
        csv = df.to_csv(index=False).encode('utf-8-sig')
        c1.download_button("CSV", csv, "cases.csv", "text/csv")
        
        # 2. JSON
        json_str = json.dumps(raw_json, ensure_ascii=False, indent=2)
        c2.download_button("JSON", json_str, "cases.json", "application/json")
        
        # 3. YAML
        yaml_str = yaml.dump(raw_json, allow_unicode=True, sort_keys=False)
        c3.download_button("YAML", yaml_str, "cases.yaml", "text/yaml")
        
        # 4. Markdown
        md_str = dataframe_to_markdown(df)
        c4.download_button("Markdown", md_str, "cases.md", "text/markdown")
