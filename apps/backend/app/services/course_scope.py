"""Single source of course ownership: ``Notebook.course_id``.

``Material.course_id`` is a legacy column.  It is never written by new flows and
must not decide whether a resource can be parsed, generated, searched or opened.
Every course-scoped query goes through this module.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import Asset, Material, Notebook, NotebookAsset


def notebook_course_id(db: Session, notebook_id: str | None) -> str | None:
    if not notebook_id:
        return None
    return db.scalar(select(Notebook.course_id).where(Notebook.id == notebook_id))


def material_course_id(db: Session, material: Material | None) -> str | None:
    if material is None:
        return None
    if material.notebook_id:
        course_id = notebook_course_id(db, material.notebook_id)
        if course_id is not None:
            return course_id
    # Legacy unbound row: keep reading its historical course for display only.
    return material.course_id


def material_in_course(db: Session, material: Material | None, course_id: str) -> bool:
    return material is not None and material_course_id(db, material) == course_id


def asset_course_id(db: Session, asset_id: str) -> str | None:
    owner = db.scalar(select(NotebookAsset).where(
        NotebookAsset.asset_id == asset_id,
        NotebookAsset.is_owner.is_(True),
        NotebookAsset.detached_at.is_(None),
    ))
    if owner is not None:
        return notebook_course_id(db, owner.notebook_id)
    material = db.scalar(select(Material).where(Material.asset_id == asset_id))
    return material_course_id(db, material)


def materials_for_course(
    db: Session, course_id: str, *, include_deleted: bool = False,
) -> list[Material]:
    query = (
        select(Material)
        .outerjoin(Notebook, Notebook.id == Material.notebook_id)
        .where(or_(Notebook.course_id == course_id,
                   (Material.notebook_id.is_(None) & (Material.course_id == course_id))))
    )
    if not include_deleted:
        query = query.where(Material.deleted_at.is_(None))
    return list(db.scalars(query.order_by(Material.chapter_order, Material.created_at,
                                          Material.id)).all())


def notebook_ids_for_course(db: Session, course_id: str, *, include_deleted: bool = False) -> list[str]:
    query = select(Notebook.id).where(Notebook.course_id == course_id)
    if not include_deleted:
        query = query.where(Notebook.deleted_at.is_(None))
    return list(db.scalars(query.all()))


def notebooks_for_course(db: Session, course_id: str) -> list[Notebook]:
    return list(db.scalars(select(Notebook).where(
        Notebook.course_id == course_id, Notebook.deleted_at.is_(None),
    ).order_by(Notebook.display_order, Notebook.created_at, Notebook.id)).all())


def assets_for_notebook(db: Session, notebook_id: str) -> list[Asset]:
    return list(db.scalars(
        select(Asset)
        .join(NotebookAsset, NotebookAsset.asset_id == Asset.id)
        .where(
            NotebookAsset.notebook_id == notebook_id,
            NotebookAsset.detached_at.is_(None),
        )
        .order_by(NotebookAsset.created_at, Asset.id)
    ).all())


def notebook_in_course(db: Session, notebook_id: str, course_id: str) -> bool:
    return notebook_course_id(db, notebook_id) == course_id


def assert_notebook_scope(db: Session, notebook_id: str, course_id: str) -> Notebook:
    notebook = db.get(Notebook, notebook_id)
    if notebook is None or notebook.deleted_at is not None or notebook.course_id != course_id:
        raise LookupError("该课程中的笔记本不存在")
    return notebook


def owned_notebook_ids(db: Session, course_id: str) -> set[str]:
    return set(notebook_ids_for_course(db, course_id))
