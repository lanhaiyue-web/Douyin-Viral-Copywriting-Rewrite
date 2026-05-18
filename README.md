# 爆款文案改写

> 本地 AI 短视频文案助手：抖音口播稿的**改写 / 评分 / 原创**三件套，附带抖音创作者中心后台数据自动抓取。

这是一个为短视频博主自己用的「文案工坊」，可以：

- **看后台**：一键抓抖音创作者中心，把你的视频数据、章节摘要、评论一并落到本地
- **写文案**：基于你自己的口吻档案 + 对标账号 + 历史后台数据生成原创口播稿，自动打分 + 预测播放量
- **改文案**：把别人的爆款套到你自己的风格上
- **可选飞书**：手机飞书私聊触发电脑写稿（不用飞书也能跑）

这个仓库是干净模板：不包含作者本人的抖音登录态、后台数据、飞书 ID、API Key、对标账号数据或真实草稿。首次使用时请按下面步骤登录自己的账号，并填写自己的 `context/`。

## 5 分钟快速开始

### 1. 装 Python 3.10+

到 [python.org](https://www.python.org/downloads/) 下载安装。Windows 装的时候勾选 **Add python.exe to PATH**。

### 2. 装依赖

打开 PowerShell，cd 到项目目录后跑：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m playwright install chromium
```

（如果你不想用 venv 也可以 `pip install --user -r requirements.txt`，bat 会自动 fallback。）

### 2.5 可选：安装 Claude Code / Codex CLI

如果你只用本地网页 `start_app.bat`，这一步可以先跳过。

如果你想在飞书机器人里点 **Claude Code 运行** / **Codex 运行**，或者想让本项目调用本地 coding agent，先装 Node.js 18+，然后在新的 PowerShell 里贴下面几行：

```powershell
# Claude Code
npm install -g @anthropic-ai/claude-code
claude --version

# Codex CLI
npm install -g @openai/codex
codex --version
codex login
```

首次运行 `claude` 或 `codex login` 会让你按提示登录自己的账号。真实账号凭证存在各自 CLI 的用户目录里，不会进这个项目，也不会上传 GitHub。

如果安装后提示找不到 `claude` / `codex`，先关闭 PowerShell 重新打开；仍然不行，再在 `%APPDATA%\baokuan-rewrite\.env` 里把 `CLAUDE_CMD` / `CODEX_CMD` 写成你本机的绝对路径。

### 3. 填 API Key

新建文件 `%APPDATA%\baokuan-rewrite\.env`（Windows）：

```ini
# 必填：DeepSeek API Key（用于文案评分）
DEEPSEEK_API_KEY=你的 deepseek api key

# 可选：飞书自建应用（如果你要手机端触发本地写稿，详见 docs/飞书集成可选.md）
FEISHU_APP_ID=
FEISHU_APP_SECRET=
```

> 凭证放在 `%APPDATA%` 而不是项目目录，是为了让你脱敏 / 删项目 / 上传 git 都不会泄露 key。
> DeepSeek API Key 注册：https://platform.deepseek.com/

### 4. 扫码登录抖音创作者中心

双击 `扫码登录抖音.bat`，会弹一个 Chromium 窗口，用**手机抖音 App** 扫窗口里的二维码。扫完后 cookies 会持久化到 `.auth/`（已 .gitignore），下次直接 `抓后台.bat` 不用再扫。

session 大约 3-5 天没用就过期，过期了再跑一次扫码即可。

### 5. 抓后台 + 写文案

```powershell
# 拉最新视频列表 → context/my-history-backend.md
抓后台.bat

# 加抓最近 2 条视频的评论 → context/comments/<aweme_id>.md
抓后台.bat --with-comments

# 启动本地 Streamlit 写文案工坊
start_app.bat
```

浏览器会自动开 http://localhost:8501。

## 文件结构

```text
爆款文案改写/
├── app.py                          ← Streamlit 本地网页（评分/改写/原创）
├── feishu_bot.py                   ← 可选：飞书机器人
├── push_to_feishu.py               ← 可选：PC 主动推送到飞书
├── prompts.py                      ← 共享 prompt 模块
├── start_app.bat                   ← 启动 Streamlit
├── start_bot.bat                   ← 启动飞书 bot（可选）
├── 抓后台.bat                       ← 抓抖音创作者中心
├── 扫码登录抖音.bat                 ← session 过期时扫码
│
├── tools/
│   ├── fetch_douyin_backend.py     ← 抓取主脚本
│   └── douyin_session/             ← Playwright + 抖音接口封装
│
├── context/                        ← 写稿上下文（核心）
│   ├── my-voice-profile.template.md   你的口吻档案（自己填写后改名 .md）
│   ├── benchmarks/
│   │   └── 对标账号-模板.template.md  对标账号数据（自己填写）
│   ├── my-history-backend.md       ← 本地运行后自动生成，不进 git
│   └── comments/<aweme_id>.md      ← 本地运行后自动生成，不进 git
│
├── scripts/                        ← 已写文案
│   └── _template.md                标准稿子结构（参考用）
│
├── docs/
│   ├── 快速开始.md
│   ├── 抖音后台抓取.md
│   └── 飞书集成可选.md
│
├── requirements.txt
├── .env.example
└── .gitignore
```

## 首次使用必做：填 context

文案质量 100% 取决于 `context/` 里的三类材料。少一类都不行：

1. **`context/my-voice-profile.md`** — 你的口吻档案。复制 `my-voice-profile.template.md` 改名后**自己填**。
2. **`context/benchmarks/<对标账号>.md`** — 选 3 个对标账号，每个抓 30 条近期数据。复制 `对标账号-模板.template.md` 改名后填。
3. **`context/my-history-backend.md`** — 你自己的后台数据。**双击 抓后台.bat 自动生成**，不用手填。

没有这三份，AI 写出来的稿就是空中楼阁。

## 飞书是可选的

如果你只在电脑前写，**完全不需要飞书**，跑 `start_app.bat` 就够了。

只有当你想：「躺在床上用手机飞书发一句 → 电脑自动写稿 → 推回飞书读」，才需要飞书。

要用的话看：[`docs/飞书集成可选.md`](docs/飞书集成可选.md)

## 模型说明

- **评分**：默认用 DeepSeek（便宜、稳定、够用）
- **原创 / 改写**：建议用 Claude Code 或 Codex（本地命令行 CLI）。默认会找 PATH 上的 `claude` / `codex`；如果找不到，就在 `%APPDATA%\baokuan-rewrite\.env` 里指定 `CLAUDE_CMD` / `CODEX_CMD`
- DeepSeek 不适合写原创口播稿（生成偏书面化，不适合短视频），所以只用来打分

## 常见问题

**Q: 抓后台.bat 报错"视频列表为空"？**
A: cookie 过期了，跑 `扫码登录抖音.bat` 重新扫码。

**Q: 扫完码提示 "[登录] 超时未检测到登录态"？**
A: 这是误报。cookies 已经写盘了，直接跑 `抓后台.bat` 验证。详见 [`docs/抖音后台抓取.md`](docs/抖音后台抓取.md)。

**Q: PowerShell 跑 python 中文乱码？**
A: bat 都已设 `PYTHONUTF8=1`。手动跑的话加 `$env:PYTHONUTF8="1"` 再跑。

**Q: 飞书机器人收不到消息？**
A: 看 [`docs/飞书集成可选.md`](docs/飞书集成可选.md) 的「调试清单」。

## License

仅供个人/学习使用。抖音 API 接口为非官方逆向，**请勿用于商业爬虫**。
