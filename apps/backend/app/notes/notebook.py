from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Course, Material, Note, Notebook, default_notebook_id
from app.schemas.notebook import ChapterRead, NotebookRead, SectionRead


def default_notebook(db: Session, course: Course, *, create: bool = True) -> Notebook | None:
    book = db.scalar(select(Notebook).where(Notebook.course_id == course.id, Notebook.is_default.is_(True), Notebook.deleted_at.is_(None)))
    if book is None and create:
        # This helper is reserved for course-scoped navigation compatibility;
        # uploads and Note/Notebook creation require an explicit notebook_id.
        book = db.get(Notebook, default_notebook_id(db.connection(), course.id))
    return book


def list_course_notebooks(db: Session, course_id: str) -> list[Notebook]:
    return list(db.scalars(select(Notebook).where(Notebook.course_id == course_id, Notebook.deleted_at.is_(None))
                           .order_by(Notebook.display_order, Notebook.created_at, Notebook.id)).all())


def bump_order_revision(db: Session, course_id: str | None, notebook_id: str | None = None) -> None:
    if notebook_id is None:
        # A legacy course-only Material can still be restored/deleted during
        # the compatibility window. Keep the course aggregate current without
        # guessing which Notebook owns it.
        if course_id is not None:
            db.execute(update(Course).where(Course.id == course_id).values(
                notebook_order_revision=Course.notebook_order_revision + 1,
            ))
        return
    book = db.get(Notebook, notebook_id)
    if book is None:
        raise ValueError("notebook_id does not exist")
    # The Notebook is the file/chapter owner. Ignore a stale or intentionally
    # absent Material.course_id and derive the optional course grouping here.
    course_id = book.course_id
    db.execute(update(Notebook).where(Notebook.id == notebook_id)
               .values(order_revision=Notebook.order_revision + 1))
    if course_id is not None:
        db.execute(update(Course).where(Course.id == course_id).values(
            notebook_order_revision=Course.notebook_order_revision + 1))


def notebook_outline(db: Session, course: Course, book: Notebook | None = None) -> NotebookRead:
    book = book or default_notebook(db, course)
    materials = db.scalars(select(Material).where(Material.notebook_id == book.id)
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
