"""带类型的答疑证据标识（Notebook 正文 / DocumentIR / 联网来源）。

设计约束（见 2026-11-01 复审路线图 §2.1）：

- Notebook 正文与 DocumentIR **必须使用不同前缀**（``N`` / ``D``），否则
  "未核验初稿只读 Notebook" 无法在证据 ID 层被证明。
- 证据 ID 只在本轮请求内有效；对外只暴露经过 answer gate 白名单过滤的 ID。
- 该模块只做纯数据变换，不查询数据库，因此 course/global 与 notebook 两条
  核验链可以共用同一套编号规则。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.retrieval.service import RetrievedChunk

NOTEBOOK_PREFIX = "N"
DOCUMENT_PREFIX = "D"
WEB_PREFIX = "W"

_KIND_BY_PREFIX = {
    NOTEBOOK_PREFIX: "notebook",
    DOCUMENT_PREFIX: "document",
    WEB_PREFIX: "web",
}


@dataclass(frozen=True)
class EvidenceItem:
    """一条可被引用的证据；``id`` 是模型唯一能看到并回填的编号。"""

    id: str
    kind: str
    chunk: RetrievedChunk

    def payload(self) -> dict[str, Any]:
        chunk = self.chunk
        block_ids = [chunk.block_id] if chunk.block_id else list(chunk.document_block_ids)
        return {
            "id": self.id,
            "kind": self.kind,
            "title": chunk.lecture_title,
            "location": chunk.location_label,
            "block_ids": block_ids,
            "text": chunk.text,
        }


def build_evidence(chunks: Iterable[RetrievedChunk], prefix: str) -> list[EvidenceItem]:
    """按给定前缀重编号，保证 Notebook / DocumentIR 编号不重号。"""

    return [
        EvidenceItem(id=f"{prefix}{index}", kind=_KIND_BY_PREFIX.get(prefix, "document"), chunk=chunk)
        for index, chunk in enumerate(chunks)
    ]


def evidence_payload(items: Iterable[EvidenceItem]) -> list[dict[str, Any]]:
    return [item.payload() for item in items]


def index_by_id(items: Iterable[EvidenceItem]) -> dict[str, EvidenceItem]:
    return {item.id: item for item in items}


def evidence_index(items: Iterable[EvidenceItem]) -> dict[str, int]:
    """证据 ID -> 合并后 chunks 列表下标（Notebook 在前，DocumentIR 在后）。"""

    return {item.id: position for position, item in enumerate(items)}


def chunks_of(items: Iterable[EvidenceItem]) -> list[RetrievedChunk]:
    return [item.chunk for item in items]


def parse_evidence_id(value: Any) -> tuple[str, int] | None:
    if not isinstance(value, str) or len(value) < 2:
        return None
    prefix, number = value[0], value[1:]
    if prefix not in _KIND_BY_PREFIX or not number.isdigit():
        return None
    return prefix, int(number)


def select_valid_ids(values: Any, known: dict[str, EvidenceItem],
                     allowed: Iterable[str] | None = None) -> list[str]:
    """只保留"格式合法 + 确实来自本轮输入 + 在允许集合内"的证据 ID。"""

    if not isinstance(values, list):
        return []
    allowed_set = None if allowed is None else set(allowed)
    selected: list[str] = []
    for value in values:
        parsed = parse_evidence_id(value)
        if parsed is None or value not in known:
            continue
        if allowed_set is not None and value not in allowed_set:
            continue
        if value not in selected:
            selected.append(value)
    return selected


__all__ = [
    "DOCUMENT_PREFIX",
    "NOTEBOOK_PREFIX",
    "WEB_PREFIX",
    "EvidenceItem",
    "build_evidence",
    "chunks_of",
    "evidence_index",
    "evidence_payload",
    "index_by_id",
    "parse_evidence_id",
    "select_valid_ids",
]
