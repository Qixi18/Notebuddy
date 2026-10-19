"""Deterministic Markdown section edits used when proposing note changes."""

from __future__ import annotations

import re
from typing import Any

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
EDIT_OPS = ("append", "insert_after_heading", "replace_section", "remove_section")


def _content_lines(content: str) -> list[str]:
    return content.strip("\n").split("\n") if content.strip() else []


def _headings(lines: list[str]) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = HEADING_RE.match(line)
        if match:
            out.append((index, len(match.group(1)), match.group(2).strip()))
    return out


def _section_range(headings: list[tuple[int, int, str]], start: int, level: int, total: int) -> tuple[int, int]:
    """小节范围 = 标题行起，到下一个同级或更高级标题前（含所有子小节）。"""
    end = total
    for index, heading_level, _title in headings:
        if index > start and heading_level <= level:
            return start, index
    return start, end


def _resolve_anchor(lines: list[str], anchor: str, op_index: int) -> tuple[int, int]:
    headings = _headings(lines)
    exact = [(index, level) for index, level, title in headings if title == anchor]
    if len(exact) == 1:
        return _section_range(headings, exact[0][0], exact[0][1], len(lines))
    partial = [(index, level, title) for index, level, title in headings if anchor in title]
    if len(partial) == 1:
        return _section_range(headings, partial[0][0], partial[0][1], len(lines))
    titles = [title for _index, _level, title in headings]
    if len(partial) > 1:
        shown = "、".join(f"『{title}』" for title, _ in [(t, None) for t in titles[:8]])
        raise ValueError(f"第 {op_index} 个操作的标题『{anchor}』匹配到多个小节（{shown}），请改用完整标题原文")
    hint = "、".join(f"『{title}』" for title in titles[:8]) or "（笔记当前没有任何标题）"
    raise ValueError(f"第 {op_index} 个操作找不到标题『{anchor}』；当前笔记的标题有：{hint}")


def apply_note_edits(current: str, edits: list[dict[str, Any]]) -> str:
    """把操作列表依次应用到正文工作副本；任何一步失败抛 ValueError（含中文原因）。"""
    lines = current.splitlines()
    for op_index, edit in enumerate(edits, start=1):
        if not isinstance(edit, dict):
            edit = {}
        op = str(edit.get("op") or "")
        if op not in EDIT_OPS:
            raise ValueError(f"第 {op_index} 个操作类型无效：{op or '（不是对象）'}；可用 append / insert_after_heading / replace_section / remove_section")
        if op == "append":
            block = _content_lines(str(edit.get("content") or ""))
            if not block:
                raise ValueError(f"第 {op_index} 个操作（append）content 为空")
            if lines and lines[-1].strip():
                lines.append("")
            lines.extend(block)
            continue
        anchor = str(edit.get("anchor") or "").strip()
        if not anchor:
            raise ValueError(f"第 {op_index} 个操作（{op}）缺少 anchor：请填笔记里某个标题的原文（不含 # 号）")
        start, end = _resolve_anchor(lines, anchor, op_index)
        if op == "remove_section":
            del lines[start:end]
        elif op == "replace_section":
            block = _content_lines(str(edit.get("content") or ""))
            if not block:
                raise ValueError(f"第 {op_index} 个操作（replace_section）content 为空")
            lines[start + 1:end] = block
        else:  # insert_after_heading：插入到该小节末尾（下一个同级或更高级标题之前）
            block = _content_lines(str(edit.get("content") or ""))
            if not block:
                raise ValueError(f"第 {op_index} 个操作（insert_after_heading）content 为空")
            lines[end:end] = [""] + block
    return "\n".join(lines)
