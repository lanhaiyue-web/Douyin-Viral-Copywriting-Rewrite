"""共享 Prompt 模板：Streamlit 应用和飞书 Bot 都从这里取。

【核心规则】写/改文案永远必须 ground 在用户账号 context：
- context/my-voice-profile.md          —— 用户语气
- context/my-history-backend.md        —— 用户抖音后台历史数据
- context/benchmarks/*.md              —— 用户自己选择的对标账号数据

后续如果用户说"加个 XX 博主作为对标"，往 benchmarks/ 加一个 .md 即可，
prompts 会自动读到，不需要改代码。
"""

from pathlib import Path

SCORE_DIMS = {
    "ER": "情绪共鸣 — 开头是否命中痛点或爽点，让观众感同身受",
    "HP": "钩子强度 — 前3秒是否有强冲突或强反差，留住观众",
    "QL": "金句密度 — 是否有可传播的一句话，适合截图或转发",
    "NA": "叙事性   — 是否有清晰的旧认知→新认知→结论结构",
    "AB": "受众广度 — 内容能覆盖多大范围的目标受众",
    "SR": "社会议题 — 是否踩中当下热门焦虑或社会情绪",
    "SAT": "讽刺深度 — 是否有让人会心一笑的反转或讽刺",
}

REWRITE_MODES = {
    "降AI痕迹": '去掉模板感、删除"首先/其次/总而言之"等套话，改成人说话的方式',
    "口语化": "把书面长句拆成短句，加语气词，像真人在聊天",
    "提升留存": "在中间加悬念句或转折，防止观众划走",
    "提升情绪感": "加强情绪词、感叹、场景代入，让读者有感觉",
    "提升转化": "强化 CTA，让结尾的行动指令更清晰、更有吸引力",
    "重构结构": "按 钩子→冲突→解法→结论 重排段落",
    "提炼爆点": "找出最值得传播的一句话并放到开头或结尾单独高亮",
    "自动改写": "综合以上所有维度，输出一版完整改写稿",
}

MODEL = "deepseek-chat"

PROJ_DIR = Path(__file__).parent
CONTEXT_DIR = PROJ_DIR / "context"


def load_account_context() -> str:
    """读取 context/ 下所有 .md 拼成一个长 string，给 create/rewrite 的 prompt 做 grounding。

    顺序：先 voice，再 backend，最后所有 benchmarks（按文件名字母序）。
    """
    if not CONTEXT_DIR.exists():
        return ""

    parts: list[str] = []
    priority = ["my-voice-profile.md", "my-history-backend.md"]
    seen: set[Path] = set()

    for name in priority:
        f = CONTEXT_DIR / name
        if f.exists():
            parts.append(f"### context/{name}\n\n{f.read_text(encoding='utf-8')}")
            seen.add(f.resolve())

    bm_dir = CONTEXT_DIR / "benchmarks"
    if bm_dir.exists():
        for f in sorted(bm_dir.glob("*.md")):
            if f.resolve() in seen:
                continue
            parts.append(f"### context/benchmarks/{f.name}\n\n{f.read_text(encoding='utf-8')}")

    return "\n\n---\n\n".join(parts)


GROUNDING_RULES = """\
=========== 用户账号 context（写作时必须严格 ground 在这些数据上）===========

{context}

=========== 写作硬规则（不能违背）===========

1. **语气**：完全按 `my-voice-profile.md` 描述的口吻写。不要把模板里的示例当成用户真实人设；如果口吻档案缺失，就明确提示用户先填写。
2. **对标账号**：`context/benchmarks/*.md` 只用于提炼钩子、结构、节奏、选题角度和变现路径。不要照搬对标账号的人设、原话、专有案例或身份标签。
3. **后台校准**：参考 `my-history-backend.md` 里真实高播/低播样本，动态判断什么题材、结构、开头有效。不要预设某个母题必爆，也不要写死固定播放基线。
4. **预测口径**：播放量预测必须基于当前 context 的可用证据；如果历史数据不足，就标注"历史基线不足"，用冷启动保守估算。
5. **避免泛泛之词**：每段尽量有具体场景、具体数字、具体人群和具体行动，不要只写宏大趋势、空泛效率或工具名堆砌。

=========== 任务 ===========

"""


def _grounding_block() -> str:
    ctx = load_account_context()
    if not ctx:
        return ""
    return GROUNDING_RULES.format(context=ctx)


def build_score_prompt(script: str) -> str:
    dims = "\n".join(f"- {k}（{v}）：0-5分" for k, v in SCORE_DIMS.items())
    return f"""你是一个短视频爆款文案评审专家。请对以下口播稿按7个维度打分，每个维度给出0-5的整数分和一句简短理由。

评分维度：
{dims}

评分完成后，计算综合分：composite = (所有维度总分 / 7) × 2，保留两位小数。

输出格式（严格按此格式，不要有其他内容）：
| 维度 | 分 | 理由 |
|---|---:|---|
| ER 情绪共鸣 | X | 理由 |
| HP 钩子强度 | X | 理由 |
| QL 金句密度 | X | 理由 |
| NA 叙事性   | X | 理由 |
| AB 受众广度 | X | 理由 |
| SR 社会议题 | X | 理由 |
| SAT 讽刺深度 | X | 理由 |

综合分：X.XX / 10

主要风险：一句话指出最大的播放风险。

---口播稿---
{script}"""


def build_rewrite_prompt(script: str, mode: str) -> str:
    instruction = REWRITE_MODES[mode]
    return f"""{_grounding_block()}请按以下要求改写口播稿：

改写目标：{mode}
具体要求：{instruction}

**改写硬约束**：
1. **首句一字不动** —— 不管别的怎么改，第一句保留原样。
2. 保持原稿核心观点不变。
3. 改写后直接输出改写稿，不要加解释。
4. 在改写稿之后，用"【改写说明】"标注你改了什么、为什么这样改（3-5条），并说明改写时引用了 context 里哪一份数据。

---原稿---
{script}"""


def build_create_prompt(topic: str) -> str:
    return f"""{_grounding_block()}请围绕以下主题，原创一篇约 2 分钟（700-800字）的爆款口播稿，并按 7 个维度打分。

主题：{topic}

输出格式严格如下。`## 播放量预测`、`**中位押注：...**`、`**预计播放量：...**` 三项必须输出，不能省略：

## 标题备选
1. ...
2. ...
3. ...

## 开头备选
**A · 最狠版**
...

**B · 反常识版**
...

**C · 痛点版**
...

## 推荐拍摄版（约 2 分钟）
完整口播稿，语言要口语化、有金句、有冲突、有 CTA

## 结尾 CTA 备选
1. ...
2. ...
3. ...

## 数据分析（7 维度评分）
| 维度 | 分 | 理由 |
|---|---:|---|
| ER 情绪共鸣 | X | ... |
| HP 钩子强度 | X | ... |
| QL 金句密度 | X | ... |
| NA 叙事性   | X | ... |
| AB 受众广度 | X | ... |
| SR 社会议题 | X | ... |
| SAT 讽刺深度 | X | ... |

**综合分**：(总分 / 7) × 2 = X.XX / 10

## 播放量预测
基于 `my-history-backend.md` 里的可用历史数据、`my-voice-profile.md` 的账号口吻、对标账号里可迁移的结构信号，以及本文案自身的 7 维评分，按下面 6 档给出概率分布。若历史数据不足，请明确写出"历史基线不足，本预测为冷启动估算"：

| 区间 | 范围 | 概率 |
|---|---:|---:|
| 扑街 | < 500 | X% |
| 持平中位 | 500 - 2500 | X% |
| 命中 | 2500 - 10000 | X% |
| 小爆 | 10000 - 50000 | X% |
| 大爆 | 50000 - 200000 | X% |
| 复刻顶流 | > 200000 | X% |

**中位押注：XXXX-XXXX 播放**（一句话档位说明，如"命中区间靠上"/"小爆区间下沿"等）
**预计播放量：XXXX-XXXX 播放**

## 主要风险
- ...
- ...

## context 引用说明
- 写作过程中引用了 context 里哪一份数据（用户后台 / 语气画像 / 哪个对标账号的哪条），用 3-5 行简述。
"""
