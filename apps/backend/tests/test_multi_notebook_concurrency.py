from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier

from pypdf import PdfWriter
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import Course, KnowledgeNode, Note, Notebook


def test_concurrent_note_additions_allocate_distinct_monotonic_slots(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'slots.sqlite3'}", connect_args={"timeout": 30})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        course = Course(id="c", name="课程")
        db.add(course)
        db.flush()
        db.add_all([Notebook(id="book", course_id="c", title="本", tree_slot=0, is_default=True),
                    KnowledgeNode(id="k", course_id="c", name="同名")])
        db.commit()
    barrier = Barrier(2)

    def add_note(worker):
        with Session(engine) as db:
            notes = [Note(course_id="c", notebook_id="book", knowledge_node_id="k",
                          title=f"{worker}-{i}", content_markdown="独立正文") for i in range(3)]
            db.add_all(notes)
            barrier.wait(timeout=10)
            db.commit()
            return [(n.id, n.tree_slot) for n in notes]

    with ThreadPoolExecutor(max_workers=2) as executor:
        a = executor.submit(add_note, "a")
        b = executor.submit(add_note, "b")
        results = a.result(timeout=40) + b.result(timeout=40)
    assert sorted(slot for _, slot in results) == list(range(6))
    with Session(engine) as db:
        last = db.scalar(select(Note).where(Note.tree_slot == 5))
        db.delete(last)
        db.commit()
        new = Note(course_id="c", notebook_id="book", knowledge_node_id="k", title="追加", content_markdown="正文")
        db.add(new)
        db.commit()
        assert new.tree_slot == 6
        assert db.get(Notebook, "book").next_note_slot == 7
    engine.dispose()


def test_concurrent_upload_retry_returns_same_book_material_and_job(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.services import uploads

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    engine = create_engine(f"sqlite:///{tmp_path / 'upload.sqlite3'}", connect_args={"timeout": 30})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Course(id="c", name="课程"))
        db.flush()
        db.add(Notebook(id="book", course_id="c", title="本", tree_slot=0, is_default=True))
        db.commit()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    stream = BytesIO()
    writer.write(stream)
    barrier = Barrier(2)
    real_validate = uploads._validate_container

    def validate(path, extension):
        real_validate(path, extension)
        barrier.wait(timeout=10)

    monkeypatch.setattr(uploads, "_validate_container", validate)

    def upload():
        with Session(engine) as db:
            material, job = uploads.ingest_document(
                db, course_id="c", notebook_id="book", source=BytesIO(stream.getvalue()),
                filename="a.pdf", lecture_title="讲", topic_title="", media_type="application/pdf",
                idempotency_key="retry")
            return material.id, job.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        a, b = executor.submit(upload), executor.submit(upload)
        assert a.result(timeout=40) == b.result(timeout=40)
    assert len(list(settings.originals_dir.glob("*.pdf"))) == 1
    engine.dispose()
