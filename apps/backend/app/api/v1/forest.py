from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.schemas.forest import (
    ForestCourseRead,
    ForestCourseUpdate,
    ForestRead,
    ForestSearchRead,
    NotebookRelationCreate,
    NotebookRelationRead,
)
from app.schemas.notebook import CourseTreeRead
from app.services.forest_reads import (
    course_tree as read_course_tree,
)
from app.services.forest_reads import (
    get_forest as read_forest,
)
from app.services.forest_reads import (
    get_relations as read_relations,
)
from app.services.forest_reads import (
    patch_profile as update_forest_profile,
)
from app.services.forest_reads import (
    search_forest as search_forest_use_case,
)
from app.services.notebook_relations import (
    create_forest_relation,
    delete_notebook_relation,
    refresh_forest_relation,
)

router = APIRouter()


@router.get("/forest/courses/{course_id}/tree", response_model=CourseTreeRead)
def course_tree(course_id: str, db: Session = Depends(get_db)) -> dict:
    return read_course_tree(db, course_id)


@router.get("/forest", response_model=ForestRead)
def get_forest(db: Session = Depends(get_db)) -> dict:
    return read_forest(db)


@router.get("/forest/search", response_model=list[ForestSearchRead])
def search_forest(
    q: str = Query(min_length=1, max_length=200), db: Session = Depends(get_db)
) -> list[dict]:
    return search_forest_use_case(db, q)


@router.patch("/forest/courses/{course_id}", response_model=ForestCourseRead)
def patch_profile(
    course_id: str, payload: ForestCourseUpdate, db: Session = Depends(get_db)
) -> dict:
    return update_forest_profile(
        db, course_id, expected_revision=payload.expected_revision,
        changes=payload.model_dump(exclude_unset=True, exclude={"expected_revision"}),
    )


@router.get("/forest/relations", response_model=list[NotebookRelationRead])
def get_relations(db: Session = Depends(get_db)) -> list[dict]:
    return read_relations(db)


@router.post("/forest/relations", response_model=NotebookRelationRead, status_code=201)
def create_relation(payload: NotebookRelationCreate, db: Session = Depends(get_db)) -> dict:
    return create_forest_relation(
        db, source_id=payload.source_notebook_id, target_id=payload.target_notebook_id,
        relation_type=payload.relation_type, reason=payload.reason,
        source_block_id=payload.source_block_id, target_block_id=payload.target_block_id,
    )


@router.post("/forest/relations/{relation_id}/refresh", response_model=NotebookRelationRead)
def refresh_relation(relation_id: str, db: Session = Depends(get_db)) -> dict:
    return refresh_forest_relation(db, relation_id)


@router.delete("/forest/relations/{relation_id}")
def delete_relation(relation_id: str, db: Session = Depends(get_db)) -> dict:
    delete_notebook_relation(db, relation_id)
    return {"deleted": True}
