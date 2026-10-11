"""Deterministic course-local candidate matching used before model integration."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import KnowledgeNode


@dataclass(frozen=True)
class MatchCandidate:
    node: KnowledgeNode
    score: float
    reasons: tuple[str, ...]


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().casefold()
    value = re.sub(r"[（(【\[]\s*[一二三四五六七八九十百上下中0-9]+\s*[）)】\]]\s*$", "", value)
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", value)


def similarity(left: str, right: str) -> float:
    a, b = normalize_name(left), normalize_name(right)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    sequence = SequenceMatcher(None, a, b).ratio()
    left_chars, right_chars = set(a), set(b)
    overlap = len(left_chars & right_chars) / max(len(left_chars | right_chars), 1)
    return round(0.65 * sequence + 0.35 * overlap, 4)


def find_candidates(
    db: Session, *, course_id: str, name: str, summary: str = "", limit: int = 5
) -> list[MatchCandidate]:
    candidates: list[MatchCandidate] = []
    for node in db.scalars(
        select(KnowledgeNode).where(KnowledgeNode.course_id == course_id)
    ).all():
        score = similarity(name, node.name)
        reasons: list[str] = []
        if normalize_name(name) == normalize_name(node.name):
            reasons.append("名称完全一致")
        if summary and node.summary:
            summary_tokens = set(re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", summary.casefold()))
            old_tokens = set(re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", node.summary.casefold()))
            if summary_tokens and len(summary_tokens & old_tokens) / len(summary_tokens) >= 0.25:
                score = min(1.0, score + 0.08)
                reasons.append("摘要有共同术语")
        if score >= 0.45:
            candidates.append(MatchCandidate(node=node, score=round(score, 4), reasons=tuple(reasons)))
    candidates.sort(key=lambda item: item.score, reverse=True)
    return candidates[:limit]


def classify_match(score: float, *, exact_name: bool = False) -> tuple[str, str]:
    if exact_name or score >= 0.98:
        return "repeat", "名称完全一致，可自动补充来源"
    if score >= 0.72:
        return "deepen", "候选名称或摘要相似，需要核对是否为深化内容"
    return "new", "没有达到课程内自动合并阈值"
