from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Course, Material, Note, Notebook, default_notebook_id
from app.schemas.notebook import ChapterRead, NotebookRead, SectionRead


def default_notebook(db: Session, course: Course, *, create: bool = True) -> Notebook | None:
    book = db.scalar(select(Notebook).where(Notebook.course_id == course.id, Notebook.is_default.is_(True)))
    if book is None and create:
        book = db.get(Notebook, default_notebook_id(db.connection(), course.id))
    return book


def bump_order_revision(db: Session, course_id: str, notebook_id: str | None = None) -> None:
    if notebook_id is None:
        notebook_id = default_notebook(db, db.get(Course, course_id)).id
    db.execute(update(Notebook).where(Notebook.id == notebook_id, Notebook.course_id == course_id)
               .values(order_revision=Notebook.order_revision + 1))
    db.execute(update(Course).where(Course.id == course_id).values(
        notebook_order_revision=Course.notebook_order_revision + 1))


def notebook_outline(db: Session, course: Course, book: Notebook | None = None) -> NotebookRead:
    book = book or default_notebook(db, course)
    materials = db.scalars(select(Material).where(Material.course_id == course.id, Material.notebook_id == book.id)
                           .order_by(Material.chapter_order, Material.created_at, Material.id)).all()
    notes = db.scalars(select(Note).where(Note.course_id == course.id, Note.notebook_id == book.id)
                       .order_by(Note.section_order, Note.created_at, Note.id)).all()
    groups: dict[str | None, list[SectionRead]] = {}
    for note in notes:
        groups.setdefault(note.material_id, []).append(SectionRead.model_validate(note))
    chapters = [ChapterRead(id=m.id, title=m.lecture_title, chapter_order=m.chapter_order,
                            status=m.status, deleted_at=m.deleted_at, sections=groups.get(m.id, []))
                for m in materials]
    return NotebookRead(id=book.id, course_id=course.id, title=book.title, tree_slot=book.tree_slot,
                        order_revision=book.order_revision,
                        chapters=[c for c in chapters if c.deleted_at is None],
                        removed_chapters=[c for c in chapters if c.deleted_at is not None],
                        historical_sections=groups.get(None, []))
