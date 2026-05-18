import os
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

from prompts import (
    MODEL,
    REWRITE_MODES,
    build_create_prompt,
    build_rewrite_prompt,
    build_score_prompt,
)

# 项目 .env：非敏感配置；然后用户级 .env 覆盖（包含真实 DEEPSEEK_API_KEY 等）
load_dotenv()
_user_creds = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "baokuan-rewrite" / ".env"
if _user_creds.exists():
    load_dotenv(_user_creds, override=True)

DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", MODEL)


def call_llm(prompt: str, api_key: str) -> str:
    client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)
    resp = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content


# ── UI ────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="爆款文案改写", layout="wide")
st.title("爆款文案改写")

# 接口密钥
with st.sidebar:
    st.header("设置")
    api_key = st.text_input(
        "DeepSeek API Key",
        value=os.environ.get("DEEPSEEK_API_KEY", ""),
        type="password",
        help="在 platform.deepseek.com/api_keys 创建并复制密钥，粘贴到这里",
    )
    st.divider()
    st.caption(f"使用模型：{DEEPSEEK_MODEL}")
    st.caption("评分维度：ER / HP / QL / NA / AB / SR / SAT")

# 输入区
st.subheader("输入口播稿")
col_input, col_space = st.columns([3, 1])

with col_input:
    uploaded = st.file_uploader("上传 .md / .txt 文件", type=["md", "txt"])
    if uploaded:
        script_text = uploaded.read().decode("utf-8")
    else:
        script_text = ""

    script = st.text_area(
        "或直接粘贴文案",
        value=script_text,
        height=350,
        placeholder="把你的口播稿粘贴到这里……",
    )

st.divider()

# 功能区：三列（评分 / 改写 / 原创）
col_score, col_rewrite, col_create = st.columns(3)

# ── 评分 ──
with col_score:
    st.subheader("文案评分")
    if st.button("开始评分", use_container_width=True, type="primary", key="btn_score"):
        if not api_key:
            st.error("请先在左侧填入 DeepSeek API Key")
        elif not script.strip():
            st.error("请先输入口播稿")
        else:
            with st.spinner("评分中……"):
                try:
                    result = call_llm(build_score_prompt(script), api_key)
                    st.markdown(result)
                except Exception as e:
                    st.error(f"调用失败：{e}")

# ── 改写 ──
with col_rewrite:
    st.subheader("文案改写")
    mode = st.selectbox(
        "改写模式",
        options=list(REWRITE_MODES.keys()),
        help="\n".join(f"**{k}**：{v}" for k, v in REWRITE_MODES.items()),
    )
    st.caption(REWRITE_MODES[mode])

    if st.button("开始改写", use_container_width=True, type="primary", key="btn_rewrite"):
        if not api_key:
            st.error("请先在左侧填入 DeepSeek API Key")
        elif not script.strip():
            st.error("请先输入口播稿")
        else:
            with st.spinner(f"正在{mode}……"):
                try:
                    result = call_llm(build_rewrite_prompt(script, mode), api_key)
                    st.markdown(result)
                    st.download_button(
                        "下载改写稿",
                        data=result,
                        file_name=f"rewrite_{mode}.md",
                        mime="text/markdown",
                    )
                except Exception as e:
                    st.error(f"调用失败：{e}")

# ── 原创 ──
with col_create:
    st.subheader("原创文案")
    topic = st.text_input("主题关键词", placeholder="例：普通人怎么做副业")
    if st.button("生成原创文案", use_container_width=True, type="primary", key="btn_create"):
        if not api_key:
            st.error("请先在左侧填入 DeepSeek API Key")
        elif not topic.strip():
            st.error("请先输入主题")
        else:
            with st.spinner("创作中……"):
                try:
                    result = call_llm(build_create_prompt(topic), api_key)
                    st.markdown(result)
                    st.download_button(
                        "下载原创稿",
                        data=result,
                        file_name=f"create_{topic[:20]}.md",
                        mime="text/markdown",
                    )
                except Exception as e:
                    st.error(f"调用失败：{e}")
