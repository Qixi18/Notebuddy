from __future__ import annotations

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.db.models import (
    AssetProcessingJob,
    Course,
    Material,
    Notebook,
    NotebookAsset,
    NotebookGenerationInput,
    NotebookGenerationJob,
    NotebookSection,
    ProcessingJob,
    default_notebook_id,
)
from app.schemas.notebook import (
    ChapterRead,
    NotebookRead,
    SectionRead,
)


def default_notebook(db: Session, course: Course, *, create: bool = True) -> Notebook | None:
    book = db.scalar(select(Notebook).where(
        Notebook.course_id == course.id, Notebook.is_default.is_(True),
        Notebook.deleted_at.is_(None),
    ))
    if book is None and create:
        # This helper is reserved for course-scoped navigation compatibility;
        # uploads and Note/Notebook creation require an explicit notebook_id.
        book = db.get(Notebook, default_notebook_id(db.connection(), course.id))
    return book


def list_course_notebooks(db: Session, course_id: str) -> list[Notebook]:
    return list(db.scalars(select(Notebook).where(
        Notebook.course_id == course_id, Notebook.deleted_at.is_(None),
    ).order_by(Notebook.display_order, Notebook.created_at, Notebook.id)).all())


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


def _section_read(book: Notebook, row: NotebookSection) -> SectionRead:
    # Keep the historical SectionRead field names so existing tree components
    # work, but every value now comes from the Notebook body, not from Note.
    return SectionRead(
        id=row.block_id,
        block_id=row.block_id,
        notebook_id=book.id,
        tree_slot=row.order,
        knowledge_node_id="",
        material_id=None,
        section_key=row.block_id,
        section_order=row.order,
        title=row.heading or f"第 {row.order + 1} 节",
        revision_number=row.revision,
        user_locked=False,
        updated_at=book.updated_at,
    )


def notebook_processing(db: Session, notebook_id: str) -> bool:
    """Tasks are independent of the body outline, including an empty body."""

    material_task = select(ProcessingJob.id).join(
        Material, Material.id == ProcessingJob.material_id,
    ).where(
        Material.notebook_id == notebook_id, Material.deleted_at.is_(None),
        ProcessingJob.status.in_(("pending", "processing")),
    ).exists()
    image_task = select(AssetProcessingJob.id).join(
        NotebookAsset, NotebookAsset.id == AssetProcessingJob.owner_link_id,
    ).where(
        AssetProcessingJob.notebook_id == notebook_id,
        AssetProcessingJob.status.in_(("pending", "processing")),
        NotebookAsset.detached_at.is_(None), NotebookAsset.role == "source_material",
    ).exists()
    generation_task = select(NotebookGenerationJob.id).where(
        NotebookGenerationJob.notebook_id == notebook_id,
        NotebookGenerationJob.status.in_(("pending", "processing", "cancel_requested")),
    ).exists()
    generation_input = select(NotebookGenerationInput.id).where(
        NotebookGenerationInput.notebook_id == notebook_id,
        NotebookGenerationInput.status.in_(("waiting_parse", "parsing", "ready", "generating")),
    ).exists()
    return bool(db.scalar(select(or_(material_task, image_task, generation_task, generation_input))))


def notebook_outline(db: Session, course: Course, book: Notebook | None = None) -> NotebookRead:
    book = book or default_notebook(db, course)
    if book is None:
        return NotebookRead(
            id="", course_id=course.id, title="", tree_slot=0, order_revision=0,
            chapters=[], historical_sections=[], removed_chapters=[],
        )
    rows = list(db.scalars(select(NotebookSection).where(
        NotebookSection.notebook_id == book.id,
    ).order_by(NotebookSection.order)).all())
    if not rows and book.document_json not in ("", "[]", None):
        # A document can exist before its derived index is rebuilt (e.g. an old
        # database upgraded without backfill); render the tree in memory rather
        # than showing an empty outline.
        from app.notes.document import load_document
        from app.notes.index import build_sections

        stored = load_document(book.document_json)
        drafts = build_sections(stored.content)
        rows = [
            NotebookSection(
                notebook_id=book.id, course_id=book.course_id, block_id=draft.block_id,
                order=draft.order, level=draft.level, heading=draft.heading,
                text=draft.text, revision=book.document_revision,
            )
            for draft in drafts
        ]

    chapters: list[ChapterRead] = []
    current: ChapterRead | None = None
    for row in rows:
        section = _section_read(book, row)
        if row.level <= 1:
            current = ChapterRead(
                id=section.id, title=section.title, chapter_order=len(chapters),
                status="parsed", deleted_at=None, sections=[],
            )
            chapters.append(current)
            # A level-1 heading is both the chapter title and its first section
            # so searching/navigating to it still yields a target.
            current.sections.append(section)
        elif current is None:
            current = ChapterRead(
                id=section.id, title="笔记正文", chapter_order=len(chapters),
                status="parsed", deleted_at=None, sections=[],
            )
            chapters.append(current)
            current.sections.append(section)
        else:
            current.sections.append(section)
    return NotebookRead(
        id=book.id,
        course_id=book.course_id or course.id,
        title=book.title,
        tree_slot=book.tree_slot,
        order_revision=book.order_revision,
        processing=notebook_processing(db, book.id),
        chapters=chapters,
        historical_sections=[],
        removed_chapters=[],
    )


def material_chapters(db: Session, notebook_id: str) -> list[Material]:
    """Source materials of a notebook, ordered; used by the resources sidebar."""
    return list(db.scalars(select(Material).where(
        Material.notebook_id == notebook_id, Material.deleted_at.is_(None),
    ).order_by(Material.chapter_order, Material.created_at, Material.id)).all())
