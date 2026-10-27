"""Render the Document IR as a readable Markdown view.

Markdown is a *derived* view for inspection and export; it is never the
authoritative learning note and never the only place a table/formula is stored.
"""

from __future__ import annotations

from app.document_processing.ir import BlockIR, DocumentIR, TableData


def render_markdown(document: DocumentIR, *, include_page_markers: bool = True) -> str:
    lines: list[str] = []
    for page in sorted(document.pages, key=lambda item: item.page_number):
        if include_page_markers:
            lines.append(f"<!-- page:{page.page_number} -->")
        for block in sorted(page.blocks, key=lambda item: (item.order, item.global_order)):
            rendered = render_block(block)
            if rendered:
                lines.append(rendered)
        if include_page_markers and page.warnings:
            lines.append("<!-- warnings: " + "；".join(page.warnings)[:500] + " -->")
    return "\n\n".join(part for part in lines if part).strip() + "\n"


def render_block(block: BlockIR) -> str:
    kind = block.type
    text = block.text.strip()
    if kind == "heading":
        level = max(1, min(block.level or 1, 6))
        return f"{'#' * level} {text}" if text else ""
    if kind == "paragraph":
        return text
    if kind == "list":
        items = [line.strip(" \t-•·") for line in text.splitlines() if line.strip(" \t-•·")]
        return "\n".join(f"- {item}" for item in items)
    if kind == "list_item":
        return f"- {text}" if text else ""
    if kind == "code":
        language = ""
        return f"```{language}\n{text}\n```" if text else ""
    if kind == "equation":
        latex = (block.latex or "").strip()
        if latex:
            return f"$$\n{latex}\n$$"
        return f"> 公式（未结构化）：{text}" if text else ""
    if kind == "table":
        return render_table(block.table) if block.table else (text or "> 表格（结构未识别）")
    if kind == "figure":
        return render_figure(block)
    if kind == "image":
        return f"> [图片] 第 {block.page_number} 页"
    if kind == "caption":
        return f"*{text}*" if text else ""
    return text


def render_table(table: TableData) -> str:
    rows = [[cell.replace("|", "\\|").strip() for cell in row] for row in table.rows]
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    header_index = min(max(table.header_rows, 1), len(rows)) - 1
    header = rows[header_index]
    body = [row for index, row in enumerate(rows) if index != header_index]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def render_figure(block: BlockIR) -> str:
    figure = block.figure
    parts: list[str] = []
    if figure is not None:
        if figure.description:
            parts.append(f"> [图·{figure.kind}] {figure.description}")
        elif figure.latex:
            parts.append(f"$$\n{figure.latex}\n$$")
        else:
            parts.append(f"> [图·{figure.kind}] 图像内容未解析（第 {block.page_number} 页）")
        if figure.nodes:
            parts.append("- 节点：" + "、".join(figure.nodes[:30]))
        if figure.edges:
            parts.append("- 关系：" + "；".join(figure.edges[:30]))
        if figure.uncertain:
            parts.append("> 说明：图形识别结果不确定，需人工核对原图。")
    else:
        parts.append(f"> [图] 图像内容未解析（第 {block.page_number} 页）")
    return "\n".join(parts)
