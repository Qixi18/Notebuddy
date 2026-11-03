"""Notebook 路由 · relations。

拆分自 api/v1/notebook.py，仅搬运路由实现，未改路径/状态码/响应模型。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Notebook, NotebookRelation
from app.schemas.notebook import NotebookRelationCreate, NotebookRelationRead
from app.services.notebook_relations import (
    create_notebook_relation as create_notebook_relation_service,
)
from app.services.notebook_relations import (
    delete_notebook_relation as delete_notebook_relation_service,
)

router = APIRouter()

@router.get("/notebooks/{notebook_id}/relations", response_model=list[NotebookRelationRead])
def list_notebook_relations(notebook_id: str, db: Session = Depends(get_db)):
    book = db.get(Notebook, notebook_id)
    if book is None or book.deleted_at is not None:
        raise HTTPException(404, "笔记不存在")
    outgoing = db.scalars(select(NotebookRelation).where(
        NotebookRelation.source_notebook_id == notebook_id,
    )).all()
    incoming = db.scalars(select(NotebookRelation).where(
        NotebookRelation.target_notebook_id == notebook_id,
    )).all()
    relations = [
        {"id": rel.id, "source_notebook_id": rel.source_notebook_id,
         "target_notebook_id": rel.target_notebook_id,
         "related_notebook_id": rel.target_notebook_id,
         "related_notebook_title": db.get(Notebook, rel.target_notebook_id).title,
         "direction": "outgoing", "relation_type": rel.relation_type,
         "description": rel.description, "created_at": rel.created_at}
        for rel in outgoing
    ]
    relations.extend(
        {"id": rel.id, "source_notebook_id": rel.source_notebook_id,
         "target_notebook_id": rel.target_notebook_id,
         "related_notebook_id": rel.source_notebook_id,
         "related_notebook_title": db.get(Notebook, rel.source_notebook_id).title,
         "direction": "incoming", "relation_type": rel.relation_type,
         "description": rel.description, "created_at": rel.created_at}
        for rel in incoming
    )
    return sorted(relations, key=lambda rel: (rel["created_at"], rel["id"]), reverse=True)

@router.post("/notebooks/{notebook_id}/relations", response_model=NotebookRelationRead,
             status_code=201)
def create_notebook_relation(notebook_id: str, payload: NotebookRelationCreate,
                             db: Session = Depends(get_db)):
    return create_notebook_relation_service(
        db, source_id=notebook_id, target_id=payload.target_notebook_id,
        relation_type=payload.relation_type, description=payload.description,
    )

@router.delete("/notebooks/{notebook_id}/relations/{relation_id}", status_code=204)
def delete_notebook_relation(notebook_id: str, relation_id: str,
                             db: Session = Depends(get_db)):
    delete_notebook_relation_service(db, relation_id, notebook_id=notebook_id)
