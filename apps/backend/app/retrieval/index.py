"""Rebuildable retrieval indexes for Document IR and Notebook body."""

from __future__ import annotations

import argparse
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Asset,
    DocumentChunk,
    Material,
)
from app.document_processing.service import current_run, rebuild_views
from app.notes.index import rebuild_notebook_index
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


def main() -> None:
    from app.db.database import SessionLocal

    parser = argparse.ArgumentParser(description="Rebuild derived NoteBuddy indexes")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--course-id")
    group.add_argument("--material-id")
    args = parser.parse_args()
    with SessionLocal() as db:
        result = (
            rebuild_course_index(db, args.course_id)
            if args.course_id
            else {"chunks": rebuild_material_index(db, args.material_id)}
        )
        db.commit()
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
