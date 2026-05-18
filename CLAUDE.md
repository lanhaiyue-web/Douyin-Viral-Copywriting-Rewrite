# Claude Code 工作规则

本项目名称：爆款文案改写。

每次处理本项目任务前，优先读取：

- `docs/PROJECT_RULES.md`
- `README.md`
- `docs/快速开始.md`
- `docs/抖音后台抓取.md`
- `docs/飞书集成可选.md`

工作原则：

- 不把开发任务、Shell、直播功能加入 `feishu_bot.py`
- 不删除 Claude Code / Codex / 直接 API 三个入口
- 不保存 API Key、App Secret、账号密码或后台 Secret
- 停止 bot 时只停止当前项目的 `feishu_bot.py` 精确进程，不批量杀 Python
- 修改后同步更新公开文档
