from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Course, Material, Note
from app.schemas.notebook import ChapterRead, NotebookRead, SectionRead


def bump_order_revision(db: Session, course_id: str) -> None:
    db.execute(update(Course).where(Course.id == course_id).values(
        notebook_order_revision=Course.notebook_order_revision + 1))


def notebook_outline(db: Session, course: Course) -> NotebookRead:
    materials = db.scalars(select(Material).where(Material.course_id == course.id)
                           .order_by(Material.chapter_order, Material.created_at, Material.id)).all()
    notes = db.scalars(select(Note).where(Note.course_id == course.id)
                       .order_by(Note.section_order, Note.created_at, Note.id)).all()
    groups: dict[str | None, list[SectionRead]] = {}
    for note in notes:
        groups.setdefault(note.material_id, []).append(SectionRead.model_validate(note))
    chapters = [ChapterRead(id=m.id, title=m.lecture_title, chapter_order=m.chapter_order,
                            status=m.status, deleted_at=m.deleted_at, sections=groups.get(m.id, []))
                for m in materials]
    return NotebookRead(course_id=course.id, title=course.name,
                        order_revision=course.notebook_order_revision,
                        chapters=[c for c in chapters if c.deleted_at is None],
                        removed_chapters=[c for c in chapters if c.deleted_at is not None],
                        historical_sections=groups.get(None, []))
