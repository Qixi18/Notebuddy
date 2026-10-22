"""Map answer-level source markers to stable course and web evidence links."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from app.retrieval.service import RetrievedChunk

COURSE_MARKER = re.compile(
    r"\[课程资料：([^\]|]+?)\s*\|\s*第\s*([\d、,，\s\-–—~至到]+?)\s*页[^\]]*\]"
)
WEB_MARKER = re.compile(r"\[网络来源\s+(\d+)[^\]]*\]")
GENERAL_MARKER = re.compile(r"\[通用解释\]")
INFERENCE_MARKER = re.compile(r"\[模型推断\]")

# 单个标记最多展开的页码数，防止「第 1-9999 页」这类异常数据炸开
_MAX_PAGES_PER_MARKER = 50


def parse_page_numbers(raw: str) -> list[int]:
    """把「第 N 页」里的 N 解析成页码列表。

    支持枚举（2、3、5 / 2,3,5）、区间（2-5）和连接词（2 到 5）。
    模型经常在一次引用里列多页，只认单页会让整段引用解析失败。
    """
    text = re.sub(r"[至到—–]", "-", raw)
    pages: list[int] = []
    for token in re.split(r"[^0-9\-]+", text):
        if not token:
            continue
        parts = [int(part) for part in token.split("-") if part.isdigit() and int(part) > 0]
        if len(parts) >= 2 and parts[0] < parts[1]:
            pages.extend(range(parts[0], min(parts[1], parts[0] + _MAX_PAGES_PER_MARKER - 1) + 1))
        else:
            pages.extend(parts)
    return sorted(set(pages))


@dataclass(frozen=True)
class EvidenceClaim:
    claim_key: str
    chunk_indexes: tuple[int, ...]
    web_indexes: tuple[int, ...]
    support_level: str
    evidence_type: str


def claim_payload(claim: EvidenceClaim) -> dict:
    return asdict(claim)


def _paragraphs(answer: str) -> list[str]:
    paragraphs = [item.strip() for item in re.split(r"\n\s*\n", answer.strip()) if item.strip()]
    return paragraphs or ([answer.strip()] if answer.strip() else [])


def extract_claims(
    answer: str,
    chunks: list[RetrievedChunk],
    web_results: list[dict],
) -> list[EvidenceClaim]:
    """Return one claim link per answer paragraph.

    Explicit markers take precedence. If a model omits markers, the paragraph is
    linked to retrieved sources with ``related`` support so the UI cannot imply
    a stronger conclusion-to-source relationship than the answer provided.
    """
    claims: list[EvidenceClaim] = []
    for index, paragraph in enumerate(_paragraphs(answer), start=1):
        chunk_indexes: list[int] = []
        for lecture_title, page_text in COURSE_MARKER.findall(paragraph):
            for page_number in parse_page_numbers(page_text):
                chunk_indexes.extend(
                    chunk_index
                    for chunk_index, chunk in enumerate(chunks)
                    if chunk.lecture_title.strip() == lecture_title.strip() and chunk.page_number == page_number
                )
        web_indexes = [int(item) - 1 for item in WEB_MARKER.findall(paragraph)]
        chunk_indexes = sorted({item for item in chunk_indexes if 0 <= item < len(chunks)})
        web_indexes = sorted({item for item in web_indexes if 0 <= item < len(web_results)})
        if not chunk_indexes and not web_indexes and not GENERAL_MARKER.search(paragraph):
            chunk_indexes = list(range(len(chunks)))
            web_indexes = list(range(len(web_results)))
        direct = any(chunks[item].direct_support for item in chunk_indexes)
        support_level = "direct" if direct else "related"
        if not chunk_indexes and web_indexes:
            support_level = "supplement"
        if not chunk_indexes and not web_indexes:
            support_level = "unverified"
        if GENERAL_MARKER.search(paragraph):
            evidence_type = "general_explanation"
        elif INFERENCE_MARKER.search(paragraph):
            evidence_type = "model_inference"
        elif chunk_indexes and web_indexes:
            evidence_type = "mixed"
        elif web_indexes:
            evidence_type = "web_supplement"
        elif chunk_indexes:
            evidence_type = "course_direct" if direct else "course_related"
        else:
            evidence_type = "general_explanation"
        claims.append(EvidenceClaim(
            claim_key=f"claim-{index}",
            chunk_indexes=tuple(chunk_indexes),
            web_indexes=tuple(web_indexes),
            support_level=support_level,
            evidence_type=evidence_type,
        ))
    return claims
