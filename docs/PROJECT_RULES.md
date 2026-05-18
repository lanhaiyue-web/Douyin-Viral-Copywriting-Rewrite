# 项目规则

更新时间：2026-05-18

## 项目边界

项目名称：爆款文案改写。

本项目只做短视频爆款口播稿相关工作：

- 文案改写
- 文案评分
- 原创文案

飞书机器人 `feishu_bot.py` 也只允许处理这三类意图。不要在这个 bot 里加入开发任务路由、Shell/系统操作、直播相关功能、通用问答或闲聊。未来如果要做直播机器人或开发助手，应新建独立项目、独立飞书应用和独立 bot 进程。

## 主文档

以后恢复项目上下文时，优先读取这些文件：

- `docs/PROJECT_RULES.md`
- `README.md`
- `docs/快速开始.md`
- `docs/抖音后台抓取.md`
- `docs/飞书集成可选.md`

公开仓库不包含本地调试记录、账号数据、任务日志或内部状态文档。

## 飞书工作流

- 使用飞书 WebSocket 长连接，不切换 Webhook / FastAPI。
- 保留 Claude Code / Codex / 直接 API 三个引擎入口。
- 引擎选择使用会话级交互卡片：首次发消息或会话超时后弹卡片，选完后会话内复用。
- 用户发 `重选引擎` / `换引擎` / `切引擎` / `重新选` 后，下条消息重新弹卡片。
- 卡片按钮回调使用 `card.action.trigger`，并通过长连接接收。

## 任务记录

手机飞书进入 bot 的每条有效文案任务必须记录：

- 新任务追加到 `tasks/inbox.md`
- 完成或失败后追加到 `tasks/history.md`
- 执行过程写入 `logs/feishu_tasks.log`

这些记录只保存任务内容、意图、引擎、状态和摘要。不要保存 API Key、App Secret、账号密码或任何后台密钥。

## 安全规则

- **真实凭证一律存在用户目录，不在项目里出现**：`%APPDATA%\baokuan-rewrite\.env`
  - `FEISHU_APP_ID` / `FEISHU_APP_SECRET` / `DEEPSEEK_API_KEY` 都在这里
  - `feishu_bot.py` 和 `app.py` 启动时自动加载并覆盖项目 `.env`
  - 整理项目、脱敏项目 `.env`、删项目目录都不会碰到真实 key
  - 用户填一次永久生效，禁止以任何理由要求用户重新填写
- 项目内 `.env` 只放非敏感配置（CLI 路径、模型名、超时、引擎选择方式）。
- 不在项目里保存真实 API Key、飞书 App Secret、抖音开发者 Secret、Facebook ID、账号密码。
- 示例配置只保留字段名，真实值统一写成 `<请用户本地填写>`。
- `.env` 是本地运行配置，不应提交；如需要整理项目文档，应先脱敏。
- 日志中如出现 `access_key`、`ticket`、完整 open_id/chat_id 等识别信息，应脱敏或只保留尾号。

## 多 AI 助手共存

用户可能同时运行 Claude Code、Codex 和其它 Python/Node 进程。

禁止：

- 批量执行 `taskkill /im python.exe`、`Get-Process python | Stop-Process`
- 删除用户级 npm/Python/配置目录
- 随意修改全局环境变量

需要停止 bot 时，只能匹配当前项目的 `feishu_bot.py` 精确进程。

## 开发偏好

- 优先可运行原型，避免过度设计。
- 保持 Windows 兼容。
- 面向用户的 UI、按钮、错误提示和文档优先中文。
- 修改功能后同步更新主文档，不依赖聊天窗口记忆。
