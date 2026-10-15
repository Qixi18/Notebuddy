import sqlite3
from contextlib import closing

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.models import Course, Note, Notebook, NotebookReadingPosition
from app.services.backup import create_backup_archive, restore_backup_to_empty

pytest_plugins = ["tests.test_forest_backup"]


def test_full_and_course_backup_keep_books_positions_and_slots_without_foreign_body(forest_data, tmp_path):
    engine = create_engine(f"sqlite:///{forest_data / 'notebook.sqlite3'}")
    with Session(engine) as db:
        course = db.get(Course, "course-0")
        default = db.scalar(select(Notebook).where(Notebook.course_id == course.id))
        for slot in (1, 2):
            book = Notebook(course_id=course.id, title=f"本{slot}", tree_slot=slot, display_order=slot)
            db.add(book)
            db.flush()
            note = Note(course_id=course.id, notebook_id=book.id, knowledge_node_id="node-0",
                        title="同名", content_markdown=f"独立正文{slot}", user_locked=True)
            db.add(note)
            db.flush()
            db.add(NotebookReadingPosition(notebook_id=book.id, chapter_id=None, note_id=note.id,
                                           mode="book", section_offset=0.6, revision=7))
        db.add(NotebookReadingPosition(notebook_id=default.id, chapter_id="material", note_id="note-0",
                                       mode="chapter", section_offset=0.25, revision=3))
        db.commit()
    engine.dispose()
    with closing(sqlite3.connect(forest_data / "notebook.sqlite3")) as db:
        books = db.execute("SELECT id,course_id,title,tree_slot,next_note_slot FROM notebooks ORDER BY id").fetchall()
        positions = db.execute("SELECT * FROM notebook_reading_positions ORDER BY notebook_id").fetchall()
        notes = db.execute("SELECT id,notebook_id,tree_slot,content_markdown,user_locked FROM notes ORDER BY id").fetchall()
    for scope in (None, "course-0"):
        package = tmp_path / f"{scope or 'full'}.zip"
        destination = tmp_path / (scope or "full")
        create_backup_archive(forest_data, package, course_id=scope)
        restore_backup_to_empty(package, destination)
        with closing(sqlite3.connect(destination / "notebook.sqlite3")) as db:
            expected_books = books if scope is None else [row for row in books if row[1] == scope]
            assert db.execute("SELECT id,course_id,title,tree_slot,next_note_slot FROM notebooks ORDER BY id").fetchall() == expected_books
            assert db.execute("SELECT * FROM notebook_reading_positions ORDER BY notebook_id").fetchall() == positions
            expected_notes = notes if scope is None else [row for row in notes if row[0] != "note-1"]
            assert db.execute("SELECT id,notebook_id,tree_slot,content_markdown,user_locked FROM notes ORDER BY id").fetchall() == expected_notes
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
