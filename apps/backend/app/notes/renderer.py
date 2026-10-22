from __future__ import annotations

import re
from collections.abc import Iterable

from app.db.models import SourceRef

# 判定「这一项到底是纯公式，还是夹着说明文字的自然语言」。
# 例：LLM 有时把 formulas 写成
#   「子空间判定条件：对于任意 $a, b \in F$ 和任意 $\alpha, \beta \in W$，有 $a\alpha + b\beta \in W$。」
# 直接套 $$ 会得到 $$ ... $ ... $$ 这种非法嵌套，KaTeX 解析失败、公式渲染不出来。
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# 行内公式定界符：$...$（不跨行、非空、内部不再含 $）
_INLINE_MATH_RE = re.compile(r"\$(?!\$)([^$\n]+?)\$(?!\$)")


def _looks_like_prose(text: str) -> bool:
    """含中文字符或句末标点，且不是纯符号时，视为自然语言描述而非公式。"""
    if not _CJK_RE.search(text):
        return False
    # 去掉行内公式后，若仍有可观的中文文字，则判定为说明性语句
    prose_only = _INLINE_MATH_RE.sub("", text)
    return bool(_CJK_RE.search(prose_only))


def format_formula_entry(formula: str) -> list[str]:
    """把一条 formulas 记录格式化成若干 Markdown 行。

    三种输入形态：
    1. 纯 LaTeX 表达式        → 渲染为块级 `$$ ... $$`
    2. 已自带 `$$...$$`       → 原样保留（避免二次包裹）
    3. 夹着行内 `$...$` 的说明句 → 作为普通段落保留，行内公式照常渲染
       （绝不套 `$$`，否则产生非法嵌套）
    """
    text = formula.strip()
    if not text:
        return []

    # 形态 2：已经是块级公式，直接用
    if text.startswith("$$") and text.endswith("$$") and len(text) > 4:
        return [text, ""]

    # 形态 3：说明性句子——保留为段落，行内 $...$ 不动
    if _looks_like_prose(text):
        return [text, ""]

    # 形态 1：纯公式。剥掉可能残留的单个 $ 定界符后套 $$。
    stripped = text.strip("$").strip()
    if not stripped:
        return []
    return ["$$", stripped, "$$", ""]


def render_note_markdown(
    *,
    title: str,
    summary: str,
    key_points: list[str],
    methods: list[str],
    formulas: list[str],
    source_refs: Iterable[SourceRef],
) -> str:
    lines = [f"# {title}", "", "## 一句话理解", "", summary or "待补充", ""]
    if key_points:
        lines.extend(["## 重点", "", *[f"- {item}" for item in key_points], ""])
    if methods:
        lines.extend(["## 方法与应用", "", *[f"- {item}" for item in methods], ""])
    if formulas:
        lines.extend(["## 公式与定理", ""])
        for formula in formulas:
            lines.extend(format_formula_entry(formula))
    refs = list(source_refs)
    if refs:
        lines.extend(["## 课件来源", ""])
        seen: set[tuple[str, int]] = set()
        for source_ref in refs:
            page = source_ref.page_block.page
            key = (page.material_id, page.page_number)
            if key in seen:
                continue
            seen.add(key)
            quote = source_ref.quote.replace("\n", " ").strip()[:120]
            lines.append(f"- 第 {page.page_number} 页：{quote}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
