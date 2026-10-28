"""Rebuildable retrieval indexes for Document IR and Notebook body."""

from __future__ import annotations

import argparse
import json
import math

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Asset,
    DocumentChunk,
    Material,
)
from app.document_processing.service import current_run, rebuild_views
from app.notes.index import rebuild_notebook_index
from app.retrieval.embedding import EmbeddingClient, EmbeddingError
from app.services.course_scope import materials_for_course, notebooks_for_course


def rebuild_material_index(db: Session, material_id: str) -> int:
    material = db.get(Material, material_id)
    if material is None:
        return 0
    asset = db.get(Asset, material.asset_id) if material.asset_id else db.get(Asset, material.id)
    run = current_run(db, asset.id) if asset is not None else None
    if run is None:
        return 0
    rebuild_views(db, run.id)
    return int(db.scalar(select(func.count(DocumentChunk.id)).where(
        DocumentChunk.parse_run_id == run.id,
    )) or 0)


def rebuild_course_index(db: Session, course_id: str) -> dict[str, int]:
    materials = materials_for_course(db, course_id)
    chunks = sum(rebuild_material_index(db, material.id) for material in materials)
    notebooks = notebooks_for_course(db, course_id)
    sections = sum(rebuild_notebook_index(db, notebook.id) for notebook in notebooks)
    return {"materials": len(materials), "chunks": chunks,
            "notebooks": len(notebooks), "sections": sections}


def embed_run_chunks(db: Session, run_id: str, *, client: EmbeddingClient | None = None,
                     batch_size: int = 32) -> dict[str, int]:
    """Populate an optional, rebuildable index; never part of document parsing."""
    client = client or EmbeddingClient()
    if not client.configured:
        raise EmbeddingError("Embedding 服务未配置")
    if batch_size < 1 or batch_size > 128:
        raise ValueError("batch_size must be between 1 and 128")
    rows = list(db.scalars(select(DocumentChunk).where(
        DocumentChunk.parse_run_id == run_id,
    ).order_by(DocumentChunk.order)).all())
    done = failed = 0
    expected_dimension: int | None = None
    for start in range(0, len(rows), batch_size):
        batch = rows[start:start + batch_size]
        try:
            vectors = client.embed([row.text for row in batch])
            if len(vectors) != len(batch) or not vectors:
                raise EmbeddingError("Embedding 返回数量不一致")
            dimension = len(vectors[0])
            if (not dimension or (expected_dimension is not None and dimension != expected_dimension)
                    or any(
                len(vector) != dimension or any(
                    not isinstance(value, (int, float)) or not math.isfinite(value)
                    for value in vector
                ) for vector in vectors
            )):
                raise EmbeddingError("Embedding 返回向量维度或数值无效")
        except (EmbeddingError, TypeError, ValueError):
            failed += len(batch)
            continue
        for row, vector in zip(batch, vectors, strict=True):
            row.embedding_json = json.dumps(vector, allow_nan=False)
            row.embedding_model = client.settings.embedding_model
        expected_dimension = dimension
        done += len(batch)
    db.flush()
    return {"total": len(rows), "indexed": done, "failed": failed}


def main() -> None:
    from app.db.database import SessionLocal

    parser = argparse.ArgumentParser(description="Rebuild derived NoteBuddy indexes")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--course-id")
    group.add_argument("--material-id")
    group.add_argument("--embed-run-id", help="Populate optional embeddings for one parse run")
    args = parser.parse_args()
    with SessionLocal() as db:
        result = (embed_run_chunks(db, args.embed_run_id) if args.embed_run_id else (
            rebuild_course_index(db, args.course_id)
            if args.course_id
            else {"chunks": rebuild_material_index(db, args.material_id)}
        ))
        db.commit()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
