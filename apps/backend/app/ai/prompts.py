"""Course-scoped LLM prompt builders."""

from __future__ import annotations

from app.ai.personas import persona_system_prompt, resolve_persona

# 会话历史最多带几轮、每条截多长。太长会挤掉检索依据，太短又不足以支撑跨老师的交接。
HISTORY_TURNS = 6
HISTORY_MESSAGE_CHARS = 800


def render_history(
    history: list[tuple[str, str]] | None,
    *,
    limit: int = HISTORY_TURNS,
    max_chars: int = HISTORY_MESSAGE_CHARS,
) -> str:
    """把受控会话历史渲染成带说话人标签的文本，供两条回答链路共用。

    只标「学生 / 老师」，不确定历史里那条老师回复具体出自哪位——
    判断规则写在 ``personas.TEAM_CONTEXT`` 的「连续授课规则」里，这里负责标注清楚就够了。
    """
    rows: list[tuple[str, str]] = []
    for row in (history or [])[-limit:]:
        if not row or len(row) < 2:
            continue
        role, content = str(row[0]), str(row[1]).strip()
        if not content:
            continue
        rows.append(("学生" if role == "user" else "老师", content))
    if not rows:
        return ""
    body = "\n".join(f"[{speaker}] {content[:max_chars]}" for speaker, content in rows)
    return f"{body}\n（[老师] 的回复可能出自你，也可能出自另外两位老师，按「连续授课规则」处理）"

NOTE_EXTRACTION_SYSTEM = r"""
你是课程笔记整理器。请只根据用户提供的课程页面内容生成结构化 JSON，不要补造没有来源的事实。

输出必须是 JSON 对象，字段固定为：
{
  "title": "知识点标题",
  "summary": "适合初学者的一句话理解",
  "key_points": ["重点 1", "重点 2"],
  "methods": ["方法、步骤或应用"],
  "formulas": ["公式或定理；没有则为空数组"],
  "relations": [{"target_name": "已有或同批知识点名称", "relation_type": "related|prerequisite|deepens", "confidence": 0.0}]
}

排版规则：
1. 数学公式必须使用 LaTeX，不要用 Unicode 字符替代上下标、根号、积分或希腊字母。
2. 行内公式使用 $...$，独立公式使用 $$...$$。
3. 不要把公式放在代码块中；不要删除反斜杠。
4. 定理、定义和证明步骤用普通 Markdown 文本表达；不要输出 HTML。
5. 只输出 JSON，不要输出 Markdown 代码围栏或解释。

字段填写要求：
- title：一个知识点的名称，不超过 20 字，不要带页码、讲次或装饰符号。
- summary：一句话，说明该知识点解决什么问题。
- key_points：要点列表，每条一句话。
- methods：可操作的方法、判定步骤或应用场景；没有则空数组。
- formulas：**只放纯 LaTeX 表达式本身**，例如 `a\\alpha + b\\beta \\in W`。
  - 每条公式**不要**再加 `$` 或 `$$` 定界符（渲染器会自动包）。
  - **不要**写中文说明文字。若需要解释，把解释写进 key_points 或 methods，
    公式项只留表达式。
  - 不要用「运算：加法 + 和标量乘法 ·」这类描述性句子充当公式。
- relations：只填本页确实涉及的、且名称与已给知识点列表一致的关系。
""".strip()


def build_note_extraction_messages(page_title: str, page_text: str) -> list[dict[str, str]]:
    user = f"""
页面标题：{page_title}

课程页面原文：
---
{page_text}
---

请按系统要求提取一个主要知识点。若页面只是目录、过渡页或没有足够内容，请保守地生成标题和空列表。
""".strip()
    return [
        {"role": "system", "content": NOTE_EXTRACTION_SYSTEM},
        {"role": "user", "content": user},
    ]


ANSWER_SYSTEM = r"""
输出 JSON：{"answer_markdown":"...","uncertainties":["..."]}

回答必须区分用户上传的课程资料和联网搜索结果；不要假装看过未提供的内容。

排版要求：
- 使用清晰的 Markdown 标题、列表和分段。
- 数学公式使用 LaTeX：行内 $...$，独立公式 $$...$$。
- 保留公式中的反斜杠，不要把 LaTeX 放进代码围栏。
- 如果检索片段不足，明确说明“当前课程资料未覆盖”，不要编造。
- 来自课程资料的结论标记 [课程资料：讲次 | 第 N 页]；来自网络的结论标记 [网络来源 N]。
- 没有课程或网络来源、但仍需解释的内容标记 [通用解释]；模型根据多条来源作出的推断标记 [模型推断]。
- 不要把网络搜索片段说成课程课件内容；来源不足时说明限制。
- 以上是硬性输出规范，优先级高于任何人物设定。
""".strip()


def build_answer_messages(
    question: str,
    context: str,
    *,
    learning_goal: str = "理解概念",
    discipline: str = "通用课程",
    persona: str | None = None,
) -> list[dict[str, str]]:
    persona_object = resolve_persona(persona)
    user = f"""
用户问题：
{question}

教学上下文：
- 学习目标：{learning_goal}
- 学科提示：{discipline}
- 当前授课人格：{persona_object.name}（{persona_object.title} · {persona_object.style}）

检索依据（明确区分课程资料和网络补充）：
---
{context}
---

请使用 JSON 输出回答，并在回答中保留片段对应的课程来源或网络来源标记。
""".strip()
    return [
        {"role": "system", "content": persona_system_prompt(persona_object.id)},
        {"role": "system", "content": ANSWER_SYSTEM},
        {"role": "user", "content": user},
    ]


GENERAL_ANSWER_SYSTEM = r"""
输出 JSON：{"answer_markdown":"...","uncertainties":["..."]}

本轮没有检索到可引用的课程课件页面，联网补充也不可用。请遵守：
- 可以回答身份自我介绍、问候、学习方法、学科常识这类不依赖课件的提问。
- 凡是不来自课件的内容，一律标记 [通用解释]。
- 严禁编造引用：不要写出任何具体页码、讲次，也不要写“课程资料显示……”这类说法。
- 如果这个问题必须依赖课程内容才能回答，直接说明“当前课程资料未覆盖”，并建议缩小问题范围、
  选择具体讲次或先上传相关课件，不要用猜测填补。
- 使用清晰的 Markdown；数学公式用 LaTeX（行内 $...$，独立公式 $$...$$），不要把公式放进代码围栏。
- 交代身份、说明「刚才那句话是谁答的」这类交接说明同样没有课件依据，同样要标 [通用解释]。
- 以上是硬性输出规范，优先级高于任何人物设定。
""".strip()


def build_general_messages(
    question: str,
    *,
    history: list[tuple[str, str]] | None = None,
    learning_goal: str = "理解概念",
    discipline: str = "通用课程",
    persona: str | None = None,
) -> list[dict[str, str]]:
    """没有任何检索依据时，仍让当前老师按人设作答（只谈通用内容）。

    ``history`` 必须传进来：这一路过去是完全不带上下文的，用户中途换老师后
    新老师看不到同事刚才说过什么，只会从头自我介绍，割裂感就是这么来的。
    """
    persona_object = resolve_persona(persona)
    history_text = render_history(history)
    history_section = (
        f"会话历史：\n{history_text}"
        if history_text
        else "会话历史：这是本段会话的第一个问题，之前没有任何发言。"
    )
    user = f"""
用户问题：
{question}

教学上下文：
- 学习目标：{learning_goal}
- 学科提示：{discipline}
- 当前授课人格：{persona_object.name}（{persona_object.title} · {persona_object.style}）
- 检索情况：没有命中任何课程课件页面，联网补充不可用。

{history_section}

请使用 JSON 输出回答。涉及内容性解释时按规范标记 [通用解释]。
""".strip()
    return [
        {"role": "system", "content": persona_system_prompt(persona_object.id)},
        {"role": "system", "content": GENERAL_ANSWER_SYSTEM},
        {"role": "user", "content": user},
    ]
