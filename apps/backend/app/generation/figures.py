"""Copy selected immutable source figures into notebook-owned image assets."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import DocumentBlock, DocumentPage, DocumentParseRun
from app.notes.assets import AssetUnavailable, assert_notebook_asset
from app.notes.attachments import AttachmentRejected, store_attachment
from app.notes.document import DocumentValidationError


def planned_figures(snapshot: dict[str, Any], plan: dict[str, Any]) -> list[dict[str, str]]:
    selected = {(unit.get("parse_run_id"), block_id)
                for unit in plan.get("units", []) if unit.get("intent") != "skip"
                for block_id in unit.get("block_ids", [])}
    figures: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for source in snapshot.get("sources", []):
        run_id, asset_id = source.get("parse_run_id"), source.get("asset_id")
        for section in source.get("sections", []):
            for block in section.get("blocks", []):
                figure = block.get("figure") or {}
                ref = figure.get("evidence_ref")
                identity = (run_id, ref)
                if (ref and ref == block.get("block_id") and identity in selected
                        and identity not in seen):
                    seen.add(identity)
                    figures.append({"run_id": run_id, "asset_id": asset_id, "block_id": ref,
                                    "fingerprint": source.get("ir_fingerprint")})
    return figures


def append_source_figures(
    db: Session, notebook_id: str, snapshot: dict[str, Any], plan: dict[str, Any],
    nodes: list[dict[str, Any]], source_map: dict[str, list[str]], created: list[Path],
) -> None:
    """Trust only persisted run/block data and an actively owned source asset."""
    candidates: list[tuple[DocumentBlock, DocumentPage, dict[str, Any], Path]] = []
    for ref in planned_figures(snapshot, plan):
        run = db.get(DocumentParseRun, ref["run_id"])
        if (run is None or run.status != "completed" or run.asset_id != ref["asset_id"]
                or not ref["fingerprint"] or run.fingerprint != ref["fingerprint"]):
            raise DocumentValidationError("图像来源解析版本不可用")
        try:
            assert_notebook_asset(db, run.asset_id, notebook_id)
        except AssetUnavailable as exc:
            raise DocumentValidationError("图像来源不属于当前笔记或已不可用") from exc
        block = db.scalar(select(DocumentBlock).where(
            DocumentBlock.parse_run_id == run.id, DocumentBlock.block_id == ref["block_id"],
        ))
        page = db.get(DocumentPage, block.page_id) if block else None
        if page is None:
            raise DocumentValidationError("图像来源页面不存在")
        try:
            figure = json.loads(block.figure_json or "{}") if block else {}
        except (ValueError, TypeError):
            figure = {}
        key = figure.get("image_key") if isinstance(figure, dict) else None
        prefix = f"derived/figures/{run.asset_id}/{run.id}/"
        if not isinstance(key, str) or not key.startswith(prefix):
            raise DocumentValidationError("图像来源不存在或不属于该解析版本")
        root = settings.data_dir.resolve()
        candidate = root / key
        try:
            path = candidate.resolve()
            run_root = (root / prefix).resolve()
            if (".." in Path(key).parts or not run_root.is_relative_to(root)
                    or not path.is_relative_to(run_root) or not path.is_file()):
                raise DocumentValidationError("图像证据文件不可用")
            current = candidate
            while current != root:
                if current.is_symlink():
                    raise DocumentValidationError("图像证据路径包含符号链接")
                current = current.parent
            if path.stat().st_size > 10 * 1024 * 1024:
                raise DocumentValidationError("图像证据超过 10 MB")
        except OSError as exc:
            raise DocumentValidationError("图像证据无法作为笔记图片保存") from exc
        candidates.append((block, page, figure, path))

    for (block, _page, figure, path), related in _group_overlapping_figures(candidates):
        try:
            attachment = store_attachment(db, notebook_id=notebook_id,
                                          filename=path.name, data=path.read_bytes())
        except (OSError, AttachmentRejected) as exc:
            raise DocumentValidationError("图像证据无法作为笔记图片保存") from exc
        created.append(settings.data_dir / "notebooks" / notebook_id / "images" /
                       attachment.stored_filename)
        node_id = f"ai-{uuid.uuid4().hex[:20]}"
        alt = str(figure.get("description") or "来源图片，内容需核对")[:200]
        image_node = {"type": "callout", "attrs": {
            "blockId": node_id, "tone": "warning" if figure.get("uncertain") else "note",
            "title": "来源图片，内容需核对" if figure.get("uncertain") else "来源图片",
        }, "content": [{"type": "image", "attrs": {
            "assetId": attachment.asset_id, "src": f"/api/v1/assets/{attachment.asset_id}/content",
            "alt": alt,
        }}]}
        source_map[node_id] = [block.block_id, *related]
        anchor = _figure_anchor_index(nodes, source_map, {block.block_id, *related})
        # Insert beside a generated node that cites this validated evidence.
        # If no generated node uses it, append as a predictable safe fallback.
        nodes.insert(anchor + 1 if anchor is not None else len(nodes), image_node)


def _figure_anchor_index(
    nodes: list[dict[str, Any]], source_map: dict[str, list[str]], evidence_ids: set[str],
) -> int | None:
    matches: list[int] = []
    for index, node in enumerate(nodes):
        attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
        node_id = attrs.get("blockId")
        cited = source_map.get(node_id, []) if isinstance(node_id, str) else []
        if evidence_ids.intersection(cited):
            matches.append(index)
    return matches[-1] if matches else None


def _group_overlapping_figures(candidates):
    """Group only one-to-one, substantially overlapping MinerU/native PDF images.

    MinerU V2 boxes use 0..1000; native PDF image boxes use page points.
    Missing geometry, rotations, ambiguous pairings, and small subfigures stay
    separate. The full native image is retained and both sources are cited.
    """
    pairs: list[tuple[int, int]] = []
    for native_i, (native, page, _figure, _path) in enumerate(candidates):
        if (native.block_type != "image" or native.extraction != "native_text"
                or page.rotation or not page.width or not page.height):
            continue
        try:
            original = json.loads(native.bbox_json or "null")
            if not isinstance(original, list) or len(original) != 4:
                continue
            x0, y0, x1, y1 = map(float, original)
            original_area = max(0, x1 - x0) * max(0, y1 - y0)
            if not original_area:
                continue
        except (TypeError, ValueError):
            continue
        for visual_i, (visual, visual_page, _fig, _file) in enumerate(candidates):
            if (visual.block_type != "figure" or visual.extraction != "mineru"
                    or visual.parse_run_id != native.parse_run_id or visual_page.id != page.id):
                continue
            try:
                bbox = json.loads(visual.bbox_json or "null")
                if not isinstance(bbox, list) or len(bbox) != 4:
                    continue
                a, b, c, d = map(float, bbox)
                if not all(0 <= value <= 1000 for value in (a, b, c, d)):
                    continue
                a, c = a * page.width / 1000, c * page.width / 1000
                b, d = b * page.height / 1000, d * page.height / 1000
                visual_area = max(0, c - a) * max(0, d - b)
                overlap = max(0, min(x1, c) - max(x0, a)) * max(0, min(y1, d) - max(y0, b))
                if (visual_area and overlap / visual_area >= 0.9
                        and overlap / original_area >= 0.6):
                    pairs.append((native_i, visual_i))
            except (TypeError, ValueError):
                continue
    matched: dict[int, int] = {}
    for native_i, visual_i in pairs:
        if (sum(a == native_i for a, _ in pairs) == 1
                and sum(b == visual_i for _, b in pairs) == 1):
            matched[native_i] = visual_i
    skipped = set(matched.values())
    for index, item in enumerate(candidates):
        if index in skipped:
            continue
        related = [candidates[matched[index]][0].block_id] if index in matched else []
        yield item, related
