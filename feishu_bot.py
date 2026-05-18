"""
飞书爆款文案机器人

【范围限定】只做三件事：
  1. 文案改写
  2. 文案评分
  3. 原创文案

其他需求 (开发任务、shell、直播项目等) 一律不处理，回复让用户去对应工具。

【交互】
- 同一会话内首次发消息 → 弹卡片选引擎 (Claude Code / Codex / 直接 API)
- 选完后该会话内都用这个引擎，不再重弹卡片
- 30 分钟没说话 → 会话失效，下次再弹
- 长消息自动分段
- 所有消息进出写 logs/feishu_chat.log
"""

import json
import os
import re
import base64
import http
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from openai import OpenAI
import lark_oapi as lark
from dotenv import load_dotenv
from lark_oapi.core.const import UTF_8
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
    P2ImMessageReceiveV1,
    ReplyMessageRequest,
    ReplyMessageRequestBody,
)
from lark_oapi.event.callback.model.p2_card_action_trigger import (
    P2CardActionTrigger,
    P2CardActionTriggerResponse,
)
from lark_oapi.ws.client import Client as LarkWsClient, _get_by_key
from lark_oapi.ws.const import (
    HEADER_BIZ_RT,
    HEADER_MESSAGE_ID,
    HEADER_SEQ,
    HEADER_SUM,
    HEADER_TRACE_ID,
    HEADER_TYPE,
)
from lark_oapi.ws.enum import MessageType
from lark_oapi.ws.model import Response

from prompts import (
    MODEL,
    REWRITE_MODES,
    build_create_prompt,
    build_rewrite_prompt,
    build_score_prompt,
)

# ── 配置 ──────────────────────────────────────────────────────────────────────

# 项目 .env：非敏感配置（CLI 路径、模型名、超时等）
load_dotenv()
# 用户级凭证：%APPDATA%\baokuan-rewrite\.env，永久不被项目脱敏波及
_user_creds = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "baokuan-rewrite" / ".env"
if _user_creds.exists():
    load_dotenv(_user_creds, override=True)

APP_ID = os.environ.get("FEISHU_APP_ID", "")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
DEEPSEEK_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", MODEL)
CLAUDE_CMD = os.environ.get("CLAUDE_CMD", "claude")
CODEX_CMD = os.environ.get("CODEX_CMD", "codex")
SESSION_TIMEOUT = int(os.environ.get("SESSION_TIMEOUT", "1800"))  # 默认 30 分钟
ENGINE_PICKER_MODE = os.environ.get("ENGINE_PICKER_MODE", "card").strip().lower()
if ENGINE_PICKER_MODE not in {"text", "card"}:
    ENGINE_PICKER_MODE = "text"

if not APP_ID or not APP_SECRET:
    raise SystemExit("缺少 FEISHU_APP_ID 或 FEISHU_APP_SECRET")

PROJ_DIR = Path(__file__).parent.resolve()
# PC 端推送目标：bot 收到第一条消息后写入这里，push_to_feishu.py 读取
TARGET_FILE = _user_creds.parent / "target.json" if _user_creds.parent.exists() else PROJ_DIR / ".target.json"
LOG_FILE = PROJ_DIR / "logs" / "feishu_chat.log"
TASKS_DIR = PROJ_DIR / "tasks"
TASK_INBOX_FILE = TASKS_DIR / "inbox.md"
TASK_HISTORY_FILE = TASKS_DIR / "history.md"
TASK_LOG_FILE = PROJ_DIR / "logs" / "feishu_tasks.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
TASKS_DIR.mkdir(parents=True, exist_ok=True)

# 草稿推送：从本项目 scripts/ 读 .md，按日期升序排
# 默认一次只发一篇；多篇时让用户选；发过后删除本地草稿文件，避免二次推送
SCRIPTS_DIR = PROJ_DIR / "scripts"
DRAFT_SELECTION_TIMEOUT = 600  # 列表展示后 10 分钟内回数字算选择，超时失效

# 待选草稿状态：user_id -> {"files": [Path, ...], "ts": float}
PENDING_DRAFT_SELECTION: dict[str, dict] = {}

feishu = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()

# 会话状态: open_id -> {"engine": "claude"/"codex"/"api", "last_active_ts": float}
SESSION: dict[str, dict] = {}

# 待执行任务: task_id -> {"intent": str, "text": str, "message_id": str, "chat_id": str, "user_id": str, "expire_ts": float}
PENDING_TASK: dict[str, dict] = {}

# ── 意图识别 (只识别三类) ────────────────────────────────────────────────────

INTENT_KEYWORDS = {
    "rewrite": ["改写", "重写", "润色", "换种说法", "改一下", "再写一版"],
    "score":   ["评分", "打分", "评估", "打个分", "测一下分", "几分"],
    "create":  ["原创", "写一篇", "帮我写", "出一篇", "写个文案", "新写", "出个标题",
                "写个口播", "写条视频", "主题", "题目", "我要写", "你写", "给我写",
                "再来一条", "再来一篇", "新写一条", "新写一篇", "再写一条"],
}

INTENT_LABEL = {"rewrite": "文案改写", "score": "文案评分", "create": "原创文案"}
ENGINE_LABEL = {"claude": "Claude Code", "codex": "Codex", "api": "直接 API"}
ENGINE_CHOICE = {
    "1": "claude",
    "claude": "claude",
    "claude code": "claude",
    "2": "codex",
    "codex": "codex",
    "3": "api",
    "api": "api",
    "直接api": "api",
    "直接 api": "api",
    "直接API": "api",
}

OUT_OF_SCOPE_REPLY = (
    "这个机器人只负责**文案改写 / 评分 / 原创**三件事，其它需求请到对应工具处理。\n\n"
    "支持的发法：\n"
    "• 改写：`帮我改写下面这段：[贴文案]`\n"
    "• 评分：`帮我给这段打分：[贴文案]`\n"
    "• 原创：`帮我写一篇关于 xxx 的文案`\n"
    "• 草稿推送：发`草稿`或`推送草稿`；多篇时先列列表让你选，发出后删除本地草稿"
)


def detect_intent(text: str) -> str | None:
    """返回 rewrite / score / create，否则 None（不处理）。"""
    low = text.lower()
    for intent, words in INTENT_KEYWORDS.items():
        if any(w.lower() in low for w in words):
            return intent
    return None


# ── 草稿推送 (改写/原创的配套：把 scripts/ 下的稿子推到手机) ───────────────

DRAFT_TRIGGER_RE = re.compile(
    r"^\s*(?:草稿|/草稿|今天的稿|我的稿子|(?:给我)?(?:发|推送|看|拿)(?:一下)?草稿)\s*$"
)


def _extract_composite_score(text: str) -> str | None:
    """从稿件或模型输出里提取 0-10 综合分，兼容多种中文/英文写法。"""
    for line in text.splitlines():
        if not re.search(r"(Composite|综合分)", line, re.IGNORECASE):
            continue

        m = re.search(r"=\s*\**\s*([\d.]+)\s*/\s*10", line)
        if m:
            return m.group(1)

        m = re.search(r"=\s*\**\s*([\d.]+)\s*$", line)
        if m:
            return m.group(1)

        nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", line)]
        candidates = [n for n in nums if 0 <= n <= 10]
        if candidates:
            # 兼容 "composite = (...)/7*2 = 8.57"；如果结尾是 "/10"，前面第一个正则已处理。
            value = candidates[-1]
            return f"{value:.2f}".rstrip("0").rstrip(".")

    return None


def _estimate_forecast(score_text: str | None, text: str = "") -> dict:
    """模型漏写预测时的保底估算，避免飞书结果缺中位押注/预计播放量。"""
    try:
        score = float(score_text) if score_text not in (None, "?") else None
    except ValueError:
        score = None

    if score is None:
        return {
            "views": "1000-4000 播放",
            "bucket": "冷启动保守区间（未抓到综合分，未使用固定账号基线）",
            "probs": [15, 35, 35, 12, 3, 0],
        }

    adjusted = min(score, 10)
    if adjusted >= 8.7:
        return {"views": "8000-15000 播放", "bucket": "命中区间上沿到小爆下沿", "probs": [4, 12, 34, 30, 16, 4]}
    if adjusted >= 8.3:
        return {"views": "5000-10000 播放", "bucket": "命中区间靠上", "probs": [6, 16, 40, 25, 10, 3]}
    if adjusted >= 7.8:
        return {"views": "2500-8000 播放", "bucket": "命中区间中段", "probs": [8, 22, 42, 20, 7, 1]}
    if adjusted >= 7.0:
        return {"views": "1000-4000 播放", "bucket": "持平中位到命中区间下沿", "probs": [12, 34, 36, 13, 4, 1]}
    return {"views": "500-2500 播放", "bucket": "持平中位区间", "probs": [22, 44, 24, 8, 2, 0]}


def _forecast_table_md(forecast: dict) -> str:
    probs = forecast["probs"]
    return (
        "| 区间 | 范围 | 概率 |\n"
        "|---|---:|---:|\n"
        f"| 低于基线 | < 500 | {probs[0]}% |\n"
        f"| 普通表现 | 500 - 2500 | {probs[1]}% |\n"
        f"| 命中选题 | 2500 - 10000 | {probs[2]}% |\n"
        f"| 小爆 | 10000 - 50000 | {probs[3]}% |\n"
        f"| 大爆 | 50000 - 200000 | {probs[4]}% |\n"
        f"| 复刻顶流 | > 200000 | {probs[5]}% |"
    )


def ensure_create_forecast(result: str, intent: str) -> str:
    """原创结果如果漏了播放量预测，发给用户前自动补齐关键字段。"""
    if intent != "create" or result.startswith("["):
        return result

    has_section = "播放量预测" in result
    has_median = "中位押注" in result
    has_expected = "预计播放量" in result
    if has_section and has_median and has_expected:
        return result

    score = _extract_composite_score(result)
    forecast = _estimate_forecast(score, result)
    views = forecast["views"]
    bucket = forecast["bucket"]

    if has_section:
        additions = ["", "## 播放量预测补充"]
        if not has_median:
            additions.append(f"**中位押注：{views}**（{bucket}）")
        if not has_expected:
            additions.append(f"**预计播放量：{views}**")
        return result.rstrip() + "\n\n" + "\n".join(additions).strip()

    section = (
        "## 播放量预测\n"
        "基于当前综合分、稿件结构和可用 context 做系统保底估算；"
        "如果还没有填写历史后台数据，这只是冷启动参考：\n\n"
        f"{_forecast_table_md(forecast)}\n\n"
        f"**中位押注：{views}**（{bucket}）\n"
        f"**预计播放量：{views}**"
    )
    return result.rstrip() + "\n\n" + section


def parse_draft_summary(md_path: Path) -> dict:
    """从 scripts/*.md 抽出：首句钩子 / 抖音口播稿 / 综合分 / 中位押注 / 预计播放量。"""
    info = {"name": md_path.stem, "hook": "(未抓到)", "body": "(未抓到)",
            "composite": "?", "bucket": "?", "median_bet": "?", "views": "?"}
    try:
        text = md_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        info["hook"] = f"[读取失败] {e}"
        return info

    m = re.search(r"##\s*首句钩子[^\n]*\n+(?:>[^\n]*\n+)?>\s*\**\s*([^\n*][^\n]*?)\s*\**\s*\n",
                  text)
    if m:
        info["hook"] = m.group(1).strip()

    m = re.search(r"##\s*抖音主版本[^\n]*\n+(.*?)(?=\n##\s)", text, re.DOTALL)
    if m:
        body = m.group(1).strip()
        # 去掉 "> ..." 引导块
        body = re.sub(r"^>.*$\n?", "", body, flags=re.MULTILINE).strip()
        info["body"] = body

    composite = _extract_composite_score(text)
    if composite:
        info["composite"] = composite

    # 中位押注同时给出"预计播放量"（加粗里的数字范围）和"档位说明"（括号里的描述）
    # 例：**中位押注：8000-15000 播放**（命中区间上沿到小爆下沿）
    m = re.search(r"\*\*中位押注[:：]\s*([^*\n]+?)\*\*(?:\s*[（(]([^）)\n]+)[）)])?", text)
    if m:
        info["median_bet"] = m.group(1).strip()
        info["views"] = info["median_bet"]
        if m.group(2):
            info["bucket"] = m.group(2).strip()

    m = re.search(r"(?:\*\*)?预计播放量(?:\*\*)?[:：]\s*(?:\*\*)?([^*\n]+?)(?:\*\*)?(?=\n|$)", text)
    if m:
        info["views"] = m.group(1).strip()
        if info["median_bet"] == "?":
            info["median_bet"] = info["views"]

    # 兜底：如果稿子里写的是旧字段名"中枢押注"，再抓一次
    if info["bucket"] == "?":
        m = re.search(r"\*\*中枢押注\*\*[:：]\s*([^（(\n]+)", text)
        if m:
            info["bucket"] = m.group(1).strip()

    if info["median_bet"] == "?" or info["views"] == "?":
        forecast = _estimate_forecast(info["composite"], text)
        if info["median_bet"] == "?":
            info["median_bet"] = forecast["views"]
        if info["views"] == "?":
            info["views"] = forecast["views"]
        if info["bucket"] == "?":
            info["bucket"] = forecast["bucket"]

    return info


def _list_pending_drafts() -> list[Path]:
    """scripts/ 下还没发的 .md，按日期升序（旧的先拍）。scripts/sent/ 是归档不算。"""
    if not SCRIPTS_DIR.exists():
        return []
    return sorted([f for f in SCRIPTS_DIR.glob("*.md") if f.is_file()])


def _delete_sent_draft(f: Path, user_id: str) -> None:
    """发过的稿子从本地草稿队列删除，确保同一篇不会被二次推送。"""
    try:
        f.unlink()
        log_debug("DRAFT_DELETE", f"已删除已发送草稿 {f.name}", user_id)
    except Exception as e:
        log_debug("DRAFT_DELETE", f"删除已发送草稿 {f.name} 失败: {e}", user_id)


def _send_one_draft(message_id: str, user_id: str, f: Path, idx: int | None = None, total: int | None = None) -> None:
    info = parse_draft_summary(f)
    head = f"📌 {info['name']}" if idx is None else f"📌 第 {idx}/{total} 条 | {info['name']}"
    msg = (
        f"━━━━━━━━━━━━━\n"
        f"{head}\n"
        f"━━━━━━━━━━━━━\n\n"
        f"【首句钩子（不动）】\n{info['hook']}\n\n"
        f"【抖音口播稿】\n{info['body']}\n\n"
        f"【综合分】{info['composite']}/10\n"
        f"【中位押注】{info['median_bet']}\n"
        f"【预计播放量】{info['views']}\n"
        f"【档位说明】{info['bucket']}"
    )
    reply_text(message_id, msg, user_id)
    _delete_sent_draft(f, user_id)


def _cleanup_draft_selection() -> None:
    now = time.time()
    for uid in [k for k, v in PENDING_DRAFT_SELECTION.items() if now - v.get("ts", 0) > DRAFT_SELECTION_TIMEOUT]:
        PENDING_DRAFT_SELECTION.pop(uid, None)


def push_drafts_to_user(message_id: str, user_id: str, requested_count: int | None = None):
    """草稿推送主入口。规则（2026-05-18 用户定）：
    - 0 篇：提示无草稿
    - 1 篇：直接发那一篇，发完删除本地草稿
    - 多篇 + 用户没指定数量：列表让用户选（数字 / "发 N 篇" / "全部"）
    - 多篇 + 用户指定数量（如"发 3 篇"）：按日期升序发前 N 篇，发完删除已发送草稿
    """
    if not SCRIPTS_DIR.exists():
        reply_text(message_id, f"❌ 草稿目录不存在：{SCRIPTS_DIR}", user_id)
        return

    pending = _list_pending_drafts()
    if not pending:
        reply_text(message_id, "❌ 当前没有未发送的草稿。新写的稿子会自动出现在草稿队列里。", user_id)
        return

    # 用户指定了数量（或"全部"）
    if requested_count is not None:
        n = min(requested_count, len(pending))
        to_send = pending[:n]
        PENDING_DRAFT_SELECTION.pop(user_id, None)
        if n > 1:
            reply_text(message_id, f"📤 一次发 {n} 条（按日期升序）", user_id)
        for i, f in enumerate(to_send, 1):
            _send_one_draft(message_id, user_id, f, i if n > 1 else None, n if n > 1 else None)
        log_debug("DRAFT_PUSH", f"批量发 {n} 条草稿", user_id)
        return

    # 只剩一篇 → 直接发
    if len(pending) == 1:
        _send_one_draft(message_id, user_id, pending[0])
        PENDING_DRAFT_SELECTION.pop(user_id, None)
        log_debug("DRAFT_PUSH", f"队列只剩 1 条，直接发", user_id)
        return

    # 多篇 → 列表让用户选
    PENDING_DRAFT_SELECTION[user_id] = {"files": pending, "ts": time.time()}
    lines = [f"📋 当前有 {len(pending)} 篇未发送草稿（按日期升序）：", ""]
    for i, f in enumerate(pending, 1):
        info = parse_draft_summary(f)
        composite = info["composite"]
        views = info["views"]
        median_bet = info["median_bet"]
        lines.append(f"  {i}. {f.stem}    综合分 {composite}/10  中位押注 {median_bet}  预计播放量 {views}")
    lines.append("")
    lines.append("💬 回复方式：")
    lines.append("  • `1` / `2` / `3` ... → 发对应那一篇")
    lines.append("  • `发 2 篇` / `发 3 篇` → 按日期升序发前 N 篇")
    lines.append("  • `全部` → 一次发完全部")
    lines.append(f"  • 10 分钟内不回复列表失效")
    reply_text(message_id, "\n".join(lines), user_id)
    log_debug("DRAFT_PUSH", f"展示草稿列表 {len(pending)} 篇待用户选", user_id)


def try_handle_draft_selection(text: str, message_id: str, user_id: str) -> bool:
    """检查用户消息是不是在响应草稿列表。返回 True 表示已处理（消息消费），False 表示不是草稿选择，让消息走后续逻辑。"""
    _cleanup_draft_selection()
    sel = PENDING_DRAFT_SELECTION.get(user_id)
    if not sel:
        return False
    files: list[Path] = sel["files"]
    t = text.strip()

    # "全部"
    if re.match(r"^\s*(全部|所有|all)\s*$", t, re.IGNORECASE):
        push_drafts_to_user(message_id, user_id, requested_count=len(files))
        return True

    # "发 N 篇" / "推 N 篇" / "N 篇"
    m = re.match(r"^\s*(?:发|推送|推)?\s*(\d+)\s*(?:篇|条)\s*$", t)
    if m:
        n = int(m.group(1))
        if n < 1:
            reply_text(message_id, "至少要发 1 篇。", user_id)
            return True
        push_drafts_to_user(message_id, user_id, requested_count=n)
        return True

    # 单个数字
    m = re.match(r"^\s*(\d+)\s*$", t)
    if m:
        idx = int(m.group(1))
        if idx < 1 or idx > len(files):
            reply_text(message_id, f"序号超范围，列表里有 1-{len(files)} 可选。", user_id)
            return True
        f = files[idx - 1]
        # 确认这文件还在（理论上没被人 delete 过；保险起见 check）
        if not f.exists():
            reply_text(message_id, f"❌ 第 {idx} 条对应的文件已经不在了（可能被删了或已归档）。", user_id)
            PENDING_DRAFT_SELECTION.pop(user_id, None)
            return True
        _send_one_draft(message_id, user_id, f)
        # 刷新待选清单（这篇已删除，剩下的可能还有）
        remaining = _list_pending_drafts()
        if remaining:
            PENDING_DRAFT_SELECTION[user_id] = {"files": remaining, "ts": time.time()}
            reply_text(message_id, f"✅ 已发送。剩余 {len(remaining)} 篇待选——回数字继续选，或发新消息结束草稿选择。", user_id)
        else:
            PENDING_DRAFT_SELECTION.pop(user_id, None)
        return True

    # 不是草稿选择 → 结束当前草稿选择，走原逻辑
    PENDING_DRAFT_SELECTION.pop(user_id, None)
    return False


# ── 日志 ──────────────────────────────────────────────────────────────────────

def log_event(direction: str, user: str, text: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{direction}] [{(user or '?')[-8:]}] {text.replace(chr(10), ' | ')}\n"
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def log_debug(tag: str, text: str, user: str = "?"):
    print(f"[{tag}] {text}", flush=True)
    log_event(tag, user, text)


def user_tail(user_id: str) -> str:
    return (user_id or "?")[-8:]


def task_preview(text: str, limit: int = 160) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    return compact[:limit] + ("..." if len(compact) > limit else "")


def ensure_task_record_files():
    if not TASK_INBOX_FILE.exists():
        TASK_INBOX_FILE.write_text(
            "# 任务收件箱\n\n"
            "手机飞书进入 bot 的文案任务会追加到这里。任务完成后在 `tasks/history.md` 记录结果。\n\n",
            encoding="utf-8",
        )
    if not TASK_HISTORY_FILE.exists():
        TASK_HISTORY_FILE.write_text(
            "# 任务历史\n\n"
            "已完成或失败的飞书任务记录在这里。\n\n",
            encoding="utf-8",
        )
    if not TASK_LOG_FILE.exists():
        TASK_LOG_FILE.write_text(
            "# feishu task log\n",
            encoding="utf-8",
        )


def append_text(path: Path, text: str):
    try:
        ensure_task_record_files()
        with path.open("a", encoding="utf-8") as f:
            f.write(text)
    except Exception as e:
        log_debug("TASK_LOG", f"写入 {path.name} 失败: {e}")


def log_task(task_id: str, user_id: str, stage: str, detail: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    append_text(
        TASK_LOG_FILE,
        f"[{ts}] [{stage}] [task={task_id}] [user={user_tail(user_id)}] {detail.replace(chr(10), ' | ')}\n",
    )


def record_task_inbox(task_id: str, task: dict, source: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    append_text(
        TASK_INBOX_FILE,
        "\n"
        f"## {task_id}\n\n"
        f"- 时间：{ts}\n"
        f"- 来源：{source}\n"
        f"- 用户：{user_tail(task.get('user_id', '?'))}\n"
        f"- 意图：{INTENT_LABEL.get(task.get('intent'), task.get('intent'))}\n"
        f"- 状态：待选择引擎/待执行\n"
        f"- 内容预览：{task_preview(task.get('text', ''))}\n",
    )
    log_task(task_id, task.get("user_id", "?"), "queued", f"{source} {task.get('intent')} {task_preview(task.get('text', ''))}")


def record_task_history(task: dict, engine: str, status: str, result: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    task_id = task.get("task_id", "unknown")
    append_text(
        TASK_HISTORY_FILE,
        "\n"
        f"## {task_id}\n\n"
        f"- 完成时间：{ts}\n"
        f"- 用户：{user_tail(task.get('user_id', '?'))}\n"
        f"- 意图：{INTENT_LABEL.get(task.get('intent'), task.get('intent'))}\n"
        f"- 引擎：{ENGINE_LABEL.get(engine, engine)}\n"
        f"- 状态：{status}\n"
        f"- 输入预览：{task_preview(task.get('text', ''))}\n"
        f"- 输出预览：{task_preview(result)}\n",
    )
    log_task(task_id, task.get("user_id", "?"), status, f"engine={engine} result={task_preview(result)}")


def patch_lark_ws_card_dispatch():
    """lark-oapi 1.6.5 drops MessageType.CARD frames before the callback dispatcher.

    Keep this patch local to this project so interactive card clicks can reach
    register_p2_card_action_trigger without modifying the global site-package.
    """
    if getattr(LarkWsClient, "_cheat_card_dispatch_patched", False):
        return

    async def _handle_data_frame(self, frame):
        hs = frame.headers
        msg_id = _get_by_key(hs, HEADER_MESSAGE_ID)
        trace_id = _get_by_key(hs, HEADER_TRACE_ID)
        sum_ = _get_by_key(hs, HEADER_SUM)
        seq = _get_by_key(hs, HEADER_SEQ)
        type_ = _get_by_key(hs, HEADER_TYPE)

        pl = frame.payload
        if int(sum_) > 1:
            pl = self._combine(msg_id, int(sum_), int(seq), pl)
            if pl is None:
                return

        try:
            message_type = MessageType(type_)
        except ValueError:
            log_debug("WS_FRAME", f"收到未知 WS 帧 type={type_} trace_id={trace_id}")
            frame.payload = lark.JSON.marshal(Response(code=http.HTTPStatus.OK)).encode(UTF_8)
            await self._write_message(frame.SerializeToString())
            return

        log_debug("WS_FRAME", f"收到 WS 帧 type={message_type.value} trace_id={trace_id}")
        if message_type == MessageType.CARD:
            log_debug("WS_PATCH", f"收到 CARD 帧 trace_id={trace_id}")

        resp = Response(code=http.HTTPStatus.OK)
        try:
            start = int(round(time.time() * 1000))
            if message_type in (MessageType.EVENT, MessageType.CARD):
                result = self._event_handler._do_without_validation(pl)
            else:
                return

            end = int(round(time.time() * 1000))
            header = hs.add()
            header.key = HEADER_BIZ_RT
            header.value = str(end - start)
            if result is not None:
                resp.data = base64.b64encode(lark.JSON.marshal(result).encode(UTF_8))
        except Exception as e:
            log_debug(
                "WS_PATCH",
                f"处理 WS 帧失败 message_type={message_type.value} trace_id={trace_id}: {e}",
            )
            resp = Response(code=http.HTTPStatus.INTERNAL_SERVER_ERROR)

        frame.payload = lark.JSON.marshal(resp).encode(UTF_8)
        await self._write_message(frame.SerializeToString())

    LarkWsClient._handle_data_frame = _handle_data_frame
    LarkWsClient._cheat_card_dispatch_patched = True


# ── 会话 ──────────────────────────────────────────────────────────────────────

def get_session_engine(user_id: str) -> str | None:
    s = SESSION.get(user_id)
    if not s:
        return None
    if time.time() - s["last_active_ts"] > SESSION_TIMEOUT:
        SESSION.pop(user_id, None)
        return None
    return s["engine"]


def update_session(user_id: str, engine: str):
    SESSION[user_id] = {"engine": engine, "last_active_ts": time.time()}


def touch_session(user_id: str):
    if user_id in SESSION:
        SESSION[user_id]["last_active_ts"] = time.time()


def remember_target_user(open_id: str):
    """把最近跟 bot 说话的 user 的 open_id 写到用户级 target.json，
    PC 端 push_to_feishu.py 读这里决定推给谁。"""
    if not open_id:
        return
    try:
        TARGET_FILE.parent.mkdir(parents=True, exist_ok=True)
        TARGET_FILE.write_text(
            json.dumps(
                {"open_id": open_id, "last_seen": datetime.now().isoformat()},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
    except Exception as e:
        log_debug("TARGET_SAVE", f"保存 target.json 失败: {e}")


# ── 飞书 IM ───────────────────────────────────────────────────────────────────

def reply_text(message_id: str, text: str, user_id: str = "?"):
    log_event("out", user_id, text)
    chunks = [text[i:i + 4500] for i in range(0, len(text), 4500)] or [""]
    for chunk in chunks:
        req = ReplyMessageRequest.builder() \
            .message_id(message_id) \
            .request_body(
                ReplyMessageRequestBody.builder()
                .content(json.dumps({"text": chunk}, ensure_ascii=False))
                .msg_type("text")
                .build()
            ).build()
        feishu.im.v1.message.reply(req)


def reply_engine_picker(message_id: str, chat_id: str | None, task_id: str, intent: str, preview: str, user_id: str):
    log_event("out", user_id, f"[卡片] 选引擎 intent={intent} task_id={task_id}")
    button_style = {
        "claude": "primary_filled",
        "codex": "default",
        "api": "default",
    }
    # 写作类任务（原创/改写）禁用 DeepSeek——质量不够，必须用 Claude Code 或 Codex
    if intent in ("create", "rewrite"):
        engine_options = [("claude", "Claude Code"), ("codex", "Codex")]
    else:
        engine_options = [("claude", "Claude Code"), ("codex", "Codex"), ("api", "直接 API")]
    buttons = []
    for engine, label in engine_options:
        buttons.append({
            "tag": "column",
            "width": "auto",
            "elements": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": label},
                "type": button_style[engine],
                "width": "default",
                "name": f"engine_{engine}",
                "behaviors": [{
                    "type": "callback",
                    "value": {"engine": engine, "task_id": task_id},
                }],
            }],
        })

    card = {
        "schema": "2.0",
        "config": {
            "wide_screen_mode": True,
            "update_multi": True,
        },
        "header": {
            "title": {"tag": "plain_text",
                      "content": f"识别到: {INTENT_LABEL.get(intent, intent)}"},
            "template": "blue",
        },
        "body": {
            "direction": "vertical",
            "elements": [
                {
                    "tag": "markdown",
                    "content": f"**内容预览**\n{preview[:300]}",
                    "text_align": "left",
                    "text_size": "normal",
                },
                {
                    "tag": "markdown",
                    "content": f"**用哪个引擎跑？**\n_选完后 {SESSION_TIMEOUT//60} 分钟内都用这个，不再问_",
                    "text_align": "left",
                    "text_size": "normal",
                },
                {
                    "tag": "column_set",
                    "horizontal_spacing": "8px",
                    "horizontal_align": "left",
                    "columns": buttons,
                },
            ],
        },
    }
    content = json.dumps(card, ensure_ascii=False)

    if chat_id:
        req = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .content(content)
                .msg_type("interactive")
                .uuid(task_id)
                .build()
            ).build()
        resp = feishu.im.v1.message.create(req)
        code = getattr(resp, "code", None)
        msg = getattr(resp, "msg", None)
        log_debug("CARD_SEND", f"create interactive chat={chat_id[-8:]} code={code} msg={msg}", user_id)
        if code == 0:
            return
        reply_text(message_id, f"[卡片发送失败] create interactive code={code} msg={msg}", user_id)
        return

    log_debug("CARD_SEND", "message event 里没有 chat_id，退回 reply interactive", user_id)
    req = ReplyMessageRequest.builder() \
        .message_id(message_id) \
        .request_body(
            ReplyMessageRequestBody.builder()
            .content(content)
            .msg_type("interactive")
            .build()
        ).build()
    resp = feishu.im.v1.message.reply(req)
    code = getattr(resp, "code", None)
    msg = getattr(resp, "msg", None)
    log_debug("CARD_SEND", f"reply interactive code={code} msg={msg}", user_id)


def reply_engine_text_picker(message_id: str, task_id: str, intent: str, preview: str, user_id: str):
    log_event("out", user_id, f"[文本选择] 选引擎 intent={intent} task_id={task_id}")
    reply_text(
        message_id,
        "识别到：{intent}\n\n"
        "内容预览：\n{preview}\n\n"
        "请选择引擎，直接回复数字或名称：\n"
        "1 = Claude Code\n"
        "2 = Codex\n"
        "3 = 直接 API\n\n"
        "当前先用文本选择，绕开飞书卡片按钮回调错误。".format(
            intent=INTENT_LABEL.get(intent, intent),
            preview=preview[:300],
        ),
        user_id,
    )


# ── 引擎调用 ──────────────────────────────────────────────────────────────────

def run_via_api(prompt: str) -> str:
    if not DEEPSEEK_KEY:
        return "[错误] 未配置 DEEPSEEK_API_KEY，请在 %APPDATA%\\baokuan-rewrite\\.env 添加密钥后重启 bot。"
    try:
        client = OpenAI(api_key=DEEPSEEK_KEY, base_url=DEEPSEEK_BASE_URL)
        resp = client.chat.completions.create(
            model=DEEPSEEK_MODEL, max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"[API 异常] {e}"


def _decode_cli_output(b: bytes) -> str:
    """CLI 输出 Windows 上可能是 UTF-8 也可能是 GBK（系统 locale），都试一下。"""
    if not b:
        return ""
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


def run_via_cli(cli: str, prompt: str, timeout: int = 600) -> str:
    """Prompt 走 stdin 而不是命令行参数——Windows 命令行硬上限 ~32KB，
    注入完整 context 后 prompt 经常 40KB+ 会被 OS 直接拒。"""
    cli_cmd = CLAUDE_CMD if cli == "claude" else CODEX_CMD
    label = ENGINE_LABEL.get(cli, cli)
    if cli == "claude":
        # claude -p 不传 prompt 参数时从 stdin 读
        args = [cli_cmd, "-p", "--output-format", "text"]
    else:
        # codex exec 同款行为：没参数则从 stdin 读
        args = [cli_cmd, "exec"]
    use_shell = cli_cmd.lower().endswith((".cmd", ".bat"))
    try:
        result = subprocess.run(
            args, cwd=str(PROJ_DIR), timeout=timeout,
            input=prompt.encode("utf-8"),
            capture_output=True, shell=use_shell,
        )
        out = _decode_cli_output(result.stdout).strip()
        err = _decode_cli_output(result.stderr).strip()
        if result.returncode != 0:
            detail = err or out or "(无 stderr/stdout 输出)"
            if cli == "claude" and "hit your limit" in detail.lower():
                reset_match = re.search(r"resets?\s+(.+)", detail, re.IGNORECASE)
                reset_text = reset_match.group(1).strip() if reset_match else "限额重置后"
                return (
                    "[Claude Code 已限额]\n"
                    f"{detail}\n\n"
                    f"请等到 {reset_text} 后再试；现在可以发 `重选引擎` 切到 Codex。"
                )
            return f"[{label} 调用失败 exit={result.returncode}]\n{detail}"
        return out or "(无输出)"
    except FileNotFoundError:
        return f"[错误] 找不到 `{cli_cmd}`。确认 {label} 已安装且 .env 里路径正确。"
    except subprocess.TimeoutExpired:
        return f"[超时] {label} 超过 {timeout} 秒未结束"
    except Exception as e:
        return f"[{label} 调用异常] {e}"


def call_engine(engine: str, prompt: str) -> str:
    if engine == "claude":
        return run_via_cli("claude", prompt)
    if engine == "codex":
        return run_via_cli("codex", prompt)
    return run_via_api(prompt)


# ── 文案任务处理 ──────────────────────────────────────────────────────────────

def build_prompt(intent: str, text: str) -> str:
    if intent == "rewrite":
        mode = "自动改写"
        for m in REWRITE_MODES:
            if m in text:
                mode = m
                break
        content = text
        for kw in INTENT_KEYWORDS["rewrite"]:
            content = content.replace(kw, "")
        content = content.replace(mode, "").strip(" :：")
        return build_rewrite_prompt(content, mode)

    if intent == "score":
        content = text
        for kw in INTENT_KEYWORDS["score"]:
            content = content.replace(kw, "")
        return build_score_prompt(content.strip(" :："))

    # create
    topic = text
    for kw in INTENT_KEYWORDS["create"]:
        topic = topic.replace(kw, "")
    return build_create_prompt(topic.strip(" :："))


def execute_task(task: dict, engine: str) -> str:
    prompt = build_prompt(task["intent"], task["text"])
    result = call_engine(engine, prompt)
    return ensure_create_forecast(result, task["intent"])


def is_engine_failure(result: str) -> bool:
    return result.startswith((
        "[错误]",
        "[超时]",
        "[执行异常]",
        "[API 异常]",
        "[Claude Code 已限额]",
        "[Claude Code 调用失败",
        "[Codex 调用失败",
        "[直接 API 调用失败",
    ))


def cleanup_pending_tasks():
    now = time.time()
    for tid in [k for k, v in PENDING_TASK.items() if v["expire_ts"] < now]:
        PENDING_TASK.pop(tid, None)


def find_pending_task_for_user(user_id: str) -> tuple[str, dict] | tuple[None, None]:
    cleanup_pending_tasks()
    candidates = [
        (task_id, task)
        for task_id, task in PENDING_TASK.items()
        if task.get("user_id") == user_id
    ]
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: item[1].get("created_ts", 0), reverse=True)
    return candidates[0]


def parse_engine_choice(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text.strip()).lower()
    compact = normalized.replace(" ", "")
    return ENGINE_CHOICE.get(normalized) or ENGINE_CHOICE.get(compact)


def start_task_worker(task: dict, engine: str, user_id: str):
    message_id = task["message_id"]
    task_id = task.get("task_id", "unknown")
    update_session(user_id, engine)
    log_task(task_id, user_id, "engine_selected", f"engine={engine}")

    def worker():
        log_task(task_id, user_id, "started", f"engine={engine} intent={task.get('intent')}")
        reply_text(
            message_id,
            f"⏳ 用 {ENGINE_LABEL.get(engine, engine)} 处理中… ({INTENT_LABEL.get(task['intent'], '')})",
            user_id,
        )
        try:
            result = execute_task(task, engine)
            status = "failed" if is_engine_failure(result) else "completed"
        except Exception as e:
            result = f"[执行异常] {e}"
            status = "failed"
        if status == "failed" and SESSION.get(user_id, {}).get("engine") == engine:
            SESSION.pop(user_id, None)
            log_task(task_id, user_id, "session_reset", f"engine={engine} failed; next task will ask again")
        record_task_history(task, engine, status, result)
        reply_text(message_id, result, user_id)

    threading.Thread(target=worker, daemon=True).start()


# ── 消息入口 ──────────────────────────────────────────────────────────────────

def on_message(data: P2ImMessageReceiveV1) -> None:
    """事件入口：立刻把活儿丢到后台线程，让 WS 帧能马上 ack。
    避免飞书因 ack 超时（阻塞 > 8 秒）重发同一事件导致卡片被重复推送。"""
    threading.Thread(target=_process_message, args=(data,), daemon=True).start()


def _process_message(data: P2ImMessageReceiveV1) -> None:
    try:
        msg = data.event.message
        message_id = msg.message_id
        chat_id = msg.chat_id
        user_id = data.event.sender.sender_id.open_id

        if msg.message_type != "text":
            reply_text(message_id, "只支持文本消息。", user_id)
            return

        text = json.loads(msg.content).get("text", "").strip()
        text = re.sub(r"@_user_\d+\s*", "", text).strip()
        if not text:
            return
        log_event("in", user_id, text)
        remember_target_user(user_id)

        # 检查"重选引擎"指令(用户主动切换)
        if re.match(r"^\s*(重选引擎|切引擎|换引擎|重新选)\s*$", text):
            SESSION.pop(user_id, None)
            reply_text(message_id, "已重置会话，下一条消息会重新选择引擎。", user_id)
            return

        # 检查"草稿推送"指令(绕开引擎，直接读 scripts/ 文件)
        if DRAFT_TRIGGER_RE.match(text):
            push_drafts_to_user(message_id, user_id)
            return

        # 草稿列表展示后，用户回数字/发 N 篇/全部时要优先消费，避免数字被误当成选引擎。
        if try_handle_draft_selection(text, message_id, user_id):
            return

        chosen_engine = parse_engine_choice(text)
        if chosen_engine:
            task_id, task = find_pending_task_for_user(user_id)
            if not task:
                reply_text(message_id, "没有待执行的文案任务。请先发一条改写 / 评分 / 原创需求。", user_id)
                return
            PENDING_TASK.pop(task_id, None)
            start_task_worker(task, chosen_engine, user_id)
            return

        intent = detect_intent(text)

        # 范围外 → 礼貌拒绝
        if intent is None:
            reply_text(message_id, OUT_OF_SCOPE_REPLY, user_id)
            return

        # 范围内 → 看会话引擎
        session_engine = get_session_engine(user_id)

        if session_engine:
            # 沿用会话引擎，不弹卡片
            touch_session(user_id)
            task_id = f"t{int(time.time()*1000) % 1000000:06d}_{user_id[-4:]}"
            task = {
                "task_id": task_id, "intent": intent, "text": text,
                "message_id": message_id, "chat_id": chat_id, "user_id": user_id,
            }
            record_task_inbox(task_id, task, "feishu_session")
            start_task_worker(task, session_engine, user_id)
            return

        # 没会话或已超时 → 选择引擎
        task_id = f"t{int(time.time()*1000) % 1000000:06d}_{user_id[-4:]}"
        PENDING_TASK[task_id] = {
            "task_id": task_id, "intent": intent, "text": text, "message_id": message_id, "chat_id": chat_id,
            "user_id": user_id, "created_ts": time.time(), "expire_ts": time.time() + 600,
        }
        record_task_inbox(task_id, PENDING_TASK[task_id], "feishu_card")
        cleanup_pending_tasks()

        if ENGINE_PICKER_MODE == "card":
            reply_engine_picker(message_id, chat_id, task_id, intent, text, user_id)
        else:
            reply_engine_text_picker(message_id, task_id, intent, text, user_id)

    except Exception as e:
        try:
            reply_text(data.event.message.message_id, f"[消息处理异常] {e}", "?")
        except Exception:
            pass


def on_card_action(data: P2CardActionTrigger) -> P2CardActionTriggerResponse:
    """卡片按钮点击。所有工作放后台线程，立刻返回空 response（SDK 推荐范式）。"""
    log_debug("CARD_ACTION", "收到卡片点击事件")
    try:
        raw_value = data.event.action.value if data.event and data.event.action else None
        log_debug("CARD_ACTION", f"action.value 类型={type(raw_value).__name__} 内容={raw_value!r}")

        # 飞书可能把 value 序列化成字符串
        if isinstance(raw_value, str):
            try:
                raw_value = json.loads(raw_value)
            except Exception:
                raw_value = {}
        action_value = raw_value or {}

        engine = action_value.get("engine", "api")
        task_id = action_value.get("task_id", "")
        user_id = (data.event.operator.open_id
                   if data.event and data.event.operator else "?")
        log_debug("CARD_ACTION", f"engine={engine} task_id={task_id} user={user_id[-6:]}", user_id)

        task = PENDING_TASK.pop(task_id, None)
        if not task:
            log_debug("CARD_ACTION", f"任务 {task_id} 不在 PENDING_TASK 里", user_id)
            # 通过消息回贴提示（不依赖 toast 序列化）
            ctx_msg_id = data.event.context.open_message_id if data.event and data.event.context else None
            if ctx_msg_id:
                reply_text(ctx_msg_id, "任务已失效（bot 可能重启过），请重新发消息触发卡片。", user_id)
            return P2CardActionTriggerResponse({})

        start_task_worker(task, engine, user_id)
        log_debug("CARD_ACTION", "已派发 worker 线程", user_id)
        return P2CardActionTriggerResponse({})
    except Exception as e:
        import traceback
        log_debug("CARD_ACTION", f"异常: {e}\n{traceback.format_exc()}")
        return P2CardActionTriggerResponse({})


def main():
    patch_lark_ws_card_dispatch()

    print(f"[启动] App ID: {APP_ID[:8]}...")
    print(f"[配置] Claude CLI: {CLAUDE_CMD}")
    print(f"[配置] Codex  CLI: {CODEX_CMD}")
    print(f"[配置] DeepSeek 模型: {DEEPSEEK_MODEL} (base={DEEPSEEK_BASE_URL})  Key 已配置={'是' if DEEPSEEK_KEY else '否'}")
    print(f"[配置] 会话超时: {SESSION_TIMEOUT} 秒 ({SESSION_TIMEOUT//60} 分钟)")
    print(f"[配置] 引擎选择: {ENGINE_PICKER_MODE}")
    print(f"[配置] 日志: {LOG_FILE}")
    print(f"[范围] 只处理: 文案改写 / 评分 / 原创")
    print(f"[就绪] 等待飞书消息……")

    handler = lark.EventDispatcherHandler.builder("", "") \
        .register_p2_im_message_receive_v1(on_message) \
        .register_p2_card_action_trigger(on_card_action) \
        .build()
    # INFO 会把飞书 WS 连接 URL 写进 stdout，其中包含 access_key/ticket。
    cli = lark.ws.Client(APP_ID, APP_SECRET, event_handler=handler, log_level=lark.LogLevel.WARNING)
    cli.start()


if __name__ == "__main__":
    main()
