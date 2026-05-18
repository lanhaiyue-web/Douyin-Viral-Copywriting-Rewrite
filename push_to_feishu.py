"""PC 端 → 飞书 主动推送助手。

用法：
    python push_to_feishu.py "想推送给手机的内容"
    或：echo "内容" | python push_to_feishu.py -

复用 feishu_bot.py 的同款凭证（user-level .env）和 target.json（最后跟 bot 说话的 user_id）。
不依赖 bot 进程在跑——但 bot 至少要被你在飞书上说过一句话，target.json 才会有内容。
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import lark_oapi as lark
from dotenv import load_dotenv
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
)

# 加载凭证：项目 .env 提供非敏感配置，user-level .env 覆盖真实 key
load_dotenv()
USER_CREDS = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "baokuan-rewrite" / ".env"
if USER_CREDS.exists():
    load_dotenv(USER_CREDS, override=True)

APP_ID = os.environ.get("FEISHU_APP_ID", "")
APP_SECRET = os.environ.get("FEISHU_APP_SECRET", "")
TARGET_FILE = USER_CREDS.parent / "target.json"

CHUNK_SIZE = 4500
TARGET_MAX_AGE_DAYS = 30


def die(msg: str) -> None:
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(1)


def load_target_user() -> str:
    if not APP_ID or not APP_SECRET:
        die(f"缺少 FEISHU_APP_ID / FEISHU_APP_SECRET。检查 {USER_CREDS}")
    if not TARGET_FILE.exists():
        die(
            "还没识别到推送目标。请先在飞书里给 bot 发一条任意消息（如「在线」），"
            f"bot 会把你的 open_id 写到 {TARGET_FILE}，之后再来推送。"
        )
    try:
        data = json.loads(TARGET_FILE.read_text(encoding="utf-8"))
    except Exception as e:
        die(f"target.json 解析失败: {e}")

    open_id = data.get("open_id") or ""
    last_seen = data.get("last_seen") or ""
    if not open_id:
        die("target.json 没有 open_id 字段，飞书 bot 收到消息后会自动写入。")

    if last_seen:
        try:
            age = datetime.now() - datetime.fromisoformat(last_seen)
            if age > timedelta(days=TARGET_MAX_AGE_DAYS):
                print(
                    f"⚠️ 目标 user 已经 {age.days} 天没和 bot 互动了，"
                    f"open_id 可能已失效。如果推送失败，先在飞书发一句话刷新。",
                    file=sys.stderr,
                )
        except Exception:
            pass

    return open_id


def read_content_from_args() -> str:
    if len(sys.argv) < 2:
        die("用法: python push_to_feishu.py \"要推送的内容\"  或  python push_to_feishu.py -  (从 stdin 读)")
    arg = sys.argv[1]
    if arg == "-":
        return sys.stdin.read()
    if Path(arg).is_file():
        return Path(arg).read_text(encoding="utf-8")
    return arg


def send_text(client: lark.Client, open_id: str, text: str) -> None:
    chunks = [text[i:i + CHUNK_SIZE] for i in range(0, len(text), CHUNK_SIZE)] or [""]
    for idx, chunk in enumerate(chunks, 1):
        req = CreateMessageRequest.builder() \
            .receive_id_type("open_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(open_id)
                .content(json.dumps({"text": chunk}, ensure_ascii=False))
                .msg_type("text")
                .build()
            ).build()
        resp = client.im.v1.message.create(req)
        code = getattr(resp, "code", None)
        msg = getattr(resp, "msg", None)
        if code != 0:
            die(f"第 {idx}/{len(chunks)} 段发送失败 code={code} msg={msg}")
        print(f"  ✅ 第 {idx}/{len(chunks)} 段 ({len(chunk)} 字)")


def main() -> None:
    content = read_content_from_args().strip()
    if not content:
        die("内容为空，没东西可推")

    open_id = load_target_user()
    client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()

    print(f"📤 推送到飞书 open_id={open_id[-8:]} 共 {len(content)} 字")
    send_text(client, open_id, content)
    print("🎉 推送完成")


if __name__ == "__main__":
    main()
