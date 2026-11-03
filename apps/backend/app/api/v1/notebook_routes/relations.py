"""Notebook 路由 · relations。

拆分自 api/v1/notebook.py，仅搬运路由实现，未改路径/状态码/响应模型。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.notebook import NotebookRelationCreate, NotebookRelationRead
from app.services.notebook_relations import (
    create_notebook_relation as create_notebook_relation_service,
)
from app.services.notebook_relations import (
    delete_notebook_relation as delete_notebook_relation_service,
)
from app.services.notebook_relations import (
    list_notebook_relations as list_notebook_relations_service,
)

router = APIRouter()

@router.get("/notebooks/{notebook_id}/relations", response_model=list[NotebookRelationRead])
def list_notebook_relations(notebook_id: str, db: Session = Depends(get_db)):
    return list_notebook_relations_service(db, notebook_id)

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
