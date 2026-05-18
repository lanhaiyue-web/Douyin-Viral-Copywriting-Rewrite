"""抖音创作者中心后台抓取 —— 爆款文案改写项目的固定入口。

复用项目根 .auth/ 的 Playwright 持久化登录态（首次扫码登录后保存在那里）。
抓视频列表 + 章节摘要，可选抓最近评论。

跑法（推荐用 抓后台.bat 包一层避免编码问题）：
  python tools/fetch_douyin_backend.py                  # 视频列表 → context/my-history-backend.md
  python tools/fetch_douyin_backend.py --with-comments  # 同上 + 最近 2 条评论
  python tools/fetch_douyin_backend.py --top 5 --with-comments
  python tools/fetch_douyin_backend.py --limit 50

输出：
  context/my-history-backend.md            视频后台摘要（覆盖）
  context/comments/<aweme_id>.md           评论按点赞排序（仅 --with-comments）
  .cache/videos.json                       原始 videos.json（debug 用）

首次使用：先双击 扫码登录抖音.bat 完成扫码。
session 过期判断：脚本返回 exit code 1 并提示重新扫码登录。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = Path(__file__).resolve().parent

# 切到项目根，让 douyin_session/paths.py 的 auth_dir() 找到 项目根/.auth
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(TOOLS_DIR))

from douyin_session.crawler import Session, fetch_recent_videos, fetch_comments  # noqa: E402

CONTEXT_DIR = PROJECT_ROOT / "context"
HISTORY_FILE = CONTEXT_DIR / "my-history-backend.md"
COMMENTS_DIR = CONTEXT_DIR / "comments"
CACHE_DIR = PROJECT_ROOT / ".cache"
TZ_CN = timezone(timedelta(hours=8))


def fmt_ts(ts: int) -> str:
    if not ts:
        return "?"
    return datetime.fromtimestamp(ts, tz=TZ_CN).strftime("%Y-%m-%d %H:%M")


def render_history_backend(videos: list[dict]) -> str:
    now = datetime.now(tz=TZ_CN).strftime("%Y-%m-%d %H:%M")
    lines = [
        "# 我的历史视频后台摘要",
        "",
        f"> 来源：抖音创作者中心，{now} 抓取，共 {len(videos)} 条。",
        "> 由 tools/fetch_douyin_backend.py 自动生成；下次刷新会覆盖。",
        "",
    ]
    videos_sorted = sorted(videos, key=lambda v: v.get("create_time") or 0, reverse=True)
    for v in videos_sorted:
        raw = v.get("raw") or {}
        dur_s = round((v.get("duration_ms") or 0) / 1000, 1)
        lines.append(f"## {v['aweme_id']}")
        lines.append("")
        lines.append(f"- 发布：{fmt_ts(v.get('create_time') or 0)}")
        lines.append(f"- 标题：{(v.get('desc') or '').strip()}")
        lines.append(
            f"- 数据：播放 {v.get('play_count') or 0}，点赞 {v.get('digg_count') or 0}，"
            f"评论 {v.get('comment_count') or 0}，分享 {v.get('share_count') or 0}，"
            f"收藏 {v.get('collect_count') or 0}，时长 {dur_s}s"
        )
        abstract = raw.get("chapter_abstract")
        if abstract:
            lines.append(f"- 后台摘要：{abstract}")
        chapter_list = raw.get("chapter_list") or []
        if chapter_list:
            lines.append("- 后台章节：")
            for ch in chapter_list:
                ts_s = round((ch.get("timestamp") or 0) / 1000, 1)
                desc = ch.get("desc", "")
                detail = ch.get("detail", "")
                line = f"  - {ts_s}s：{desc}"
                if detail:
                    line += f" - {detail}"
                lines.append(line)
        lines.append("")
    return "\n".join(lines)


def render_comments(aweme_id: str, video_meta: dict | None, comments: list[dict]) -> str:
    lines = ["# 视频评论（按点赞排序）", ""]
    if video_meta:
        lines.append(f"- aweme_id：`{aweme_id}`")
        lines.append(f"- 标题：{(video_meta.get('desc') or '').strip()}")
        lines.append(f"- 发布：{fmt_ts(video_meta.get('create_time') or 0)}")
        lines.append(
            f"- 数据：播放 {video_meta.get('play_count') or 0}，"
            f"点赞 {video_meta.get('digg_count') or 0}，"
            f"评论 {video_meta.get('comment_count') or 0}"
        )
        lines.append("")
    lines.append(f"共抓到 {len(comments)} 条评论。")
    lines.append("")
    lines.append("| 赞 | 用户 | IP | 评论 |")
    lines.append("|---:|---|---|---|")
    for c in comments:
        text = (c.get("text") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {c.get('digg_count', 0)} | {c.get('user_name', '')} | "
            f"{c.get('ip_label', '')} | {text} |"
        )
    return "\n".join(lines)


def session_expired_help() -> None:
    print("")
    print("[失败] 视频列表为空。多半是抖音 session 过期或未登录。")
    print("       双击或运行：扫码登录抖音.bat")
    print("       扫完码再跑这个脚本即可。")


async def main_async(args: argparse.Namespace) -> int:
    CONTEXT_DIR.mkdir(parents=True, exist_ok=True)
    COMMENTS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    auth_path = PROJECT_ROOT / ".auth"
    if not auth_path.exists():
        print("[错误] 还没登录抖音创作者中心。请先双击 扫码登录抖音.bat 完成扫码。")
        return 1

    print(f"[启动] 打开 Chromium，复用 .auth/ 的登录态")
    sess = await Session.open(headless=False)
    try:
        print(f"[抓取] 视频列表 limit={args.limit}")
        videos = await fetch_recent_videos(sess, limit=args.limit)
        if not videos:
            session_expired_help()
            return 1

        (CACHE_DIR / "videos.json").write_text(
            json.dumps(videos, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        HISTORY_FILE.write_text(render_history_backend(videos), encoding="utf-8")
        print(f"[写入] context/{HISTORY_FILE.name}（{len(videos)} 条）")

        print("\n[最近 5 条]")
        for v in sorted(videos, key=lambda x: x.get("create_time") or 0, reverse=True)[:5]:
            dur = round((v.get("duration_ms") or 0) / 1000, 1)
            title = (v.get("desc") or "").strip()[:60]
            print(
                f"  - {v['aweme_id']} | {fmt_ts(v.get('create_time') or 0)} | "
                f"{dur}s | 播放 {v.get('play_count')} | {title}"
            )

        if args.with_comments:
            top = sorted(videos, key=lambda x: x.get("create_time") or 0, reverse=True)[: args.top]
            print(f"\n[抓取] 最近 {len(top)} 条视频的评论")
            for v in top:
                aid = v["aweme_id"]
                title = (v.get("desc") or "")[:30]
                print(f"  → {aid} {title}")
                cmts = await fetch_comments(sess, aid, max_pages=args.max_pages)
                if not cmts:
                    print("    (没拿到评论 — 可能是 0 评论视频或前台限流)")
                    continue
                out_path = COMMENTS_DIR / f"{aid}.md"
                out_path.write_text(render_comments(aid, v, cmts), encoding="utf-8")
                print(f"    {len(cmts)} 条 → context/comments/{out_path.name}")

        print("\n[完成]")
        return 0
    finally:
        await sess.close()


def main() -> int:
    p = argparse.ArgumentParser(description="抖音创作者中心后台抓取（爆款文案改写项目入口）")
    p.add_argument("--limit", type=int, default=30, help="抓多少条视频，默认 30")
    p.add_argument("--with-comments", action="store_true", help="同时抓最近 N 条视频的评论")
    p.add_argument("--top", type=int, default=2, help="抓评论的视频数，默认 2")
    p.add_argument("--max-pages", type=int, default=60, help="评论页面滚动次数，默认 60")
    args = p.parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    sys.exit(main())
