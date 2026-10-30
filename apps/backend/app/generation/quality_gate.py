"""Deterministic checks for AI-generated math nodes.

This module is intentionally a pure function: it does not read or write the
database, call a model, or attempt to prove mathematical correctness. KaTeX's
actual parser is exercised in the frontend test suite using the same package
and security options as the editor.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from app.notes.document import MAX_LATEX

_FORBIDDEN_COMMAND = re.compile(
    r"\\(?:href|url|html[A-Za-z]*|includegraphics|input|include|write\w*|"
    r"csname|endcsname|def|gdef|xdef|edef|catcode|style|class)\b",
)
_MATH_TEXT = re.compile(
    r"\\(?:mathbb|mathcal|mathrm|frac|sqrt|sum|prod|int|lim|cdot|times|"
    r"cup|cap|setminus|in|notin|subseteq?|supseteq?|mid|to|rightarrow|"
    r"leq?|geq?|neq|approx|equiv|overline)\b"
    r"|(?<![A-Za-z0-9])(?:[A-Za-z](?:_[{A-Za-z0-9]+|\^[{A-Za-z0-9]+))",
)
_FILENAME = re.compile(r"\b[\w.-]+_[\w.-]+\.(?:py|ts|tsx|js|jsx|json|csv|pdf|docx)\b", re.IGNORECASE)
_ENVIRONMENT = re.compile(r"\\(begin|end)\s*\{([^{}]+)\}")
_MATH_DELIMITER = re.compile(r"(?<!\\)\$|\\[()]|\\[\[\]]")
_LEFT_RIGHT = re.compile(r"\\(?:left|right)(?![A-Za-z])")


@dataclass(frozen=True)
class MathIssue:
    code: str
    block_id: str | None
    node_path: str
    node_type: str
    severity: str = "error"


@dataclass
class MathQualityReport:
    inline_math_count: int = 0
    block_math_count: int = 0
    suspected_unstructured_math_count: int = 0
    issues: list[MathIssue] = field(default_factory=list)
    elapsed_ms: float = 0.0

    @property
    def passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def failure_codes(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for issue in self.issues:
            if issue.severity == "error":
                counts[issue.code] = counts.get(issue.code, 0) + 1
        return counts


def inspect_generated_math(document: dict[str, Any]) -> MathQualityReport:
    """Inspect a schema-validated AI fragment without changing its meaning."""
    started = perf_counter()
    report = MathQualityReport()

    def visit(
        node: Any,
        path: str,
        block_id: str | None,
        *,
        in_code: bool = False,
    ) -> None:
        if not isinstance(node, dict):
            return
        node_type = node.get("type")
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        if path.count("content[") == 1:
            candidate_id = attrs.get("blockId")
            if isinstance(candidate_id, str) and candidate_id:
                block_id = candidate_id
        in_code = in_code or node_type == "codeBlock"

        if node_type in {"inlineMath", "blockMath"}:
            if node_type == "inlineMath":
                report.inline_math_count += 1
            else:
                report.block_math_count += 1
            latex = attrs.get("latex")
            issue_code: str | None = None
            if not isinstance(latex, str) or not latex.strip() or len(latex) > MAX_LATEX:
                issue_code = "invalid_inline_math" if node_type == "inlineMath" else "invalid_block_math"
            elif (
                _has_unbalanced_groups(latex)
                or _has_unbalanced_delimiters(latex)
                or _has_unbalanced_environments(latex)
                or _has_unbalanced_left_right(latex)
            ):
                issue_code = "math_structure_invalid"
            elif _MATH_DELIMITER.search(latex):
                issue_code = "math_delimiter_invalid"
            elif _FORBIDDEN_COMMAND.search(latex):
                issue_code = "math_command_forbidden"
            if issue_code:
                report.issues.append(MathIssue(issue_code, block_id, path, str(node_type)))

        if node_type == "text" and not in_code:
            text = node.get("text")
            marks = node.get("marks") or []
            if isinstance(text, str) and not any(
                isinstance(mark, dict) and mark.get("type") == "code" for mark in marks
            ) and not _FILENAME.search(text) and _MATH_TEXT.search(text):
                report.suspected_unstructured_math_count += 1
                report.issues.append(MathIssue(
                    "suspected_unstructured_math", block_id, path, "text", "diagnostic",
                ))

        children = node.get("content")
        if isinstance(children, list):
            for index, child in enumerate(children):
                visit(child, f"{path}.content[{index}]", block_id, in_code=in_code)

    for index, node in enumerate(document.get("content") or []):
        visit(node, f"doc.content[{index}]", None)
    report.elapsed_ms = round((perf_counter() - started) * 1000, 3)
    return report


def _is_escaped(value: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and value[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _has_unbalanced_groups(latex: str) -> bool:
    depth = 0
    for index, char in enumerate(latex):
        if _is_escaped(latex, index):
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return True
    return depth != 0


def _has_unbalanced_environments(latex: str) -> bool:
    stack: list[str] = []
    for match in _ENVIRONMENT.finditer(latex):
        action, name = match.groups()
        if action == "begin":
            stack.append(name)
        elif not stack or stack.pop() != name:
            return True
    return bool(stack)


def _has_unbalanced_delimiters(latex: str) -> bool:
    matching = {"(": ")", "[": "]"}
    stack: list[str] = []
    for index, char in enumerate(latex):
        if char in matching and not _is_escaped(latex, index):
            stack.append(matching[char])
        elif (
            char in {")", "]"}
            and not _is_escaped(latex, index)
            and (not stack or stack.pop() != char)
        ):
            return True
    return bool(stack)


def _has_unbalanced_left_right(latex: str) -> bool:
    commands = [match.group() for match in _LEFT_RIGHT.finditer(latex)]
    depth = 0
    for command in commands:
        if command == r"\left":
            depth += 1
        elif depth == 0:
            return True
        else:
            depth -= 1
    return depth != 0

