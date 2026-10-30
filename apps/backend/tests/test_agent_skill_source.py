from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import Notebook
from app.notes.document import dump_document
from app.services.skills import _skill_source


def test_course_skill_source_reads_only_canonical_notebooks(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'skills.sqlite3').as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for course, title, body, deleted in (
            ("course-a", "Active", "canonical A", False),
            ("course-b", "Other", "private B", False),
            ("course-a", "Removed", "deleted text", True),
        ):
            book = Notebook(
                course_id=course,
                title=title,
                tree_slot=0 if title != "Removed" else 1,
                document_json=dump_document({
                    "type": "doc", "content": [{"type": "paragraph", "content": [
                        {"type": "text", "text": body},
                    ]}],
                }),
            )
            if deleted:
                book.deleted_at = datetime.now(UTC)
            db.add(book)
        db.commit()

        source = _skill_source(db, course_id="course-a", material_id=None, notebook_id=None)
        assert "canonical A" in source
        assert "private B" not in source
        assert "deleted text" not in source
