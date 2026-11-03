"""Classify web results and judge—lexically—whether a source really supports a claim.

设计边界（见 2026-11-01 复审路线图 §3）：

- 域名后缀只是"来源类型"的弱信号，**不能**当作事实正确性的证据；
- 搜索摘要/标题也不等于原文，所以这里只输出"弱支持 / 不清楚"，
  真正的"已证实"必须由拿到原文的人工或受控抓取给出；
- 本模块是纯函数，不联网、不读数据库，方便直接单测。
"""

from __future__ import annotations

import re
from collections import defaultdict
from urllib.parse import urlparse

# 来源类型：这是"出版者性质"，不是"正确性等级"。
_SOURCE_TYPES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("standard", ("iso.org", "iec.ch", "w3.org", "ietf.org")),
    ("institutional", (".edu", ".ac.uk", ".gov", ".gov.cn", ".mil", ".edu.cn")),
    ("academic", (".ac.cn", "arxiv.org", "doi.org", "springer.com", "sciencedirect.com",
                  "nature.com", "science.org", "ieee.org", "acm.org", "cnki.net")),
    ("organization", (".org",)),
    ("encyclopedia", ("wikipedia.org", "baike.baidu.com", "britannica.com")),
    ("community", ("zhihu.com", "csdn.net", "jianshu.com", "reddit.com", "stackoverflow.com",
                   "blog.", "medium.com", "bilibili.com")),
)

# 来源风险提示：越靠前越需要"看原文再下结论"。
_SOURCE_RISK: dict[str, str] = {
    "standard": "标准原文属高可信，但仍需核对版本、条款号与发布日期",
    "institutional": "机构站点只说明发布者性质，正文是否支持该主张仍需核验",
    "academic": "学术来源需核对论文正文、版本与是否被后续研究推翻",
    "organization": "组织站点可能带立场，需核对原文与发布时间",
    "encyclopedia": "百科条目可编辑，只能作为线索，不能作为最终证据",
    "community": "社区内容可信度低，必须找到其引用的原始来源",
    "web": "普通网页来源，需核对作者、发布时间与原文",
}


def classify_source(item: dict) -> str:
    host = urlparse(str(item.get("url") or "")).netloc.casefold()
    for source_type, markers in _SOURCE_TYPES:
        if any(host.endswith(marker) for marker in markers):
            return source_type
    return "web"


def _host(item: dict) -> str:
    return urlparse(str(item.get("url") or "")).netloc.casefold()


def _published_year(item: dict) -> int | None:
    raw = str(item.get("published_at") or "")
    match = re.search(r"(19|20)\d{2}", raw)
    if match:
        return int(match.group(0))
    # 退一步：从 URL 里找年份（很多机构页面把年份放在路径里）
    match = re.search(r"/(19|20)\d{2}/", str(item.get("url") or ""))
    return int(match.group(0)[1:5]) if match else None


def _normalized_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for token in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", (text or "").lower()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            if len(token) == 1:
                tokens.add(token)
            tokens.update(token[index:index + 2] for index in range(len(token) - 1))
        elif len(token) > 1:
            tokens.add(token)
    return tokens


def evidence_support(claim: str, item: dict, *, min_overlap: int | None = None) -> dict:
    """词面重合度评估"这条来源是否可能支持这条主张"。

    返回 ``verdict``：
    - ``likely_supports``：标题/摘要与主张有足够词面重合（仍只是"可能"，需原文）；
    - ``unclear``：重合不足，最多算线索；
    - ``no_text``：来源没有可用的标题/摘要。

    绝不在只有域名/分数的情况下返回支持。阈值按主张长度自适应：短主张（术语、
    单句定义）只要求 1 个共同片段，长主张要求 2 个以上，避免"短主张永远判不清"。
    """

    title = str(item.get("title") or "")
    snippet = str(item.get("snippet") or "")
    text = f"{title} {snippet}".strip()
    if not text:
        return {"verdict": "no_text", "overlap": 0, "reason": "来源没有标题或摘要"}
    claim_tokens = _normalized_tokens(claim)
    source_tokens = _normalized_tokens(text)
    overlap = len(claim_tokens & source_tokens)
    threshold = min_overlap if min_overlap is not None else (1 if len(claim_tokens) <= 4 else 2)
    if overlap >= threshold:
        return {
            "verdict": "likely_supports",
            "overlap": overlap,
            "reason": "标题/摘要与主张存在词面重合，仍需核对原文",
        }
    return {
        "verdict": "unclear",
        "overlap": overlap,
        "reason": "标题/摘要与主张重合不足，不能据此声称支持",
    }


def review_results(results: list[dict]) -> dict:
    groups: dict[str, list[dict]] = defaultdict(list)
    reviewed = []
    for item in results:
        row = dict(item)
        source_type = classify_source(row)
        row["source_type"] = source_type
        row["source_risk"] = _SOURCE_RISK.get(source_type, _SOURCE_RISK["web"])
        row["published_year"] = _published_year(row)
        row["review_warning"] = "搜索结果是待核对资料；域名和分数不等于事实证明"
        reviewed.append(row)
        title_key = " ".join(str(row.get("title") or "").casefold().split())
        if title_key:
            groups[title_key].append(row)
    conflict_groups = []
    conflict_index = 0
    for items in groups.values():
        unique_urls = {str(item.get("url") or "") for item in items}
        if len(items) < 2 or len(unique_urls) < 2:
            continue
        conflict_index += 1
        group_id = f"title-conflict-{conflict_index}"
        for item in items:
            item["conflict_group_id"] = group_id
            item["review_warning"] += "；同标题存在多个来源，需人工核对是否矛盾"
        conflict_groups.append(items)
    return {"results": reviewed, "conflict_groups": conflict_groups}


def assess_claim_sources(claim: str, sources: list[dict]) -> dict:
    """对一条主张和一组来源做逐条弱评估，供核验链在校验模型结论时使用。"""

    assessments = []
    for item in sources:
        row = evidence_support(claim, item)
        assessments.append({
            "url": item.get("url"),
            "source_type": item.get("source_type") or classify_source(item),
            "verdict": row["verdict"],
            "overlap": row["overlap"],
            "reason": row["reason"],
        })
    likely = [row for row in assessments if row["verdict"] == "likely_supports"]
    return {
        "claim": claim[:500],
        "supported_by": [row["url"] for row in likely],
        "assessments": assessments,
        "verified": False,  # 词面评估永远不构成"已核实"
        "summary": (
            "存在可能支持该主张的来源，但未经原文核对" if likely
            else "没有来源在词面上支持该主张"
        ),
    }


__all__ = [
    "assess_claim_sources",
    "classify_source",
    "evidence_support",
    "review_results",
]
