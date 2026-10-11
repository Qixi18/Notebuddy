"""Notebook ordering, independent bodies and source mappings survive course backup."""
import sqlite3
from contextlib import closing

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.database import Base
from app.db.models import (
    Course,
    KnowledgeNode,
    Material,
    MaterialPage,
    Note,
    NoteRevision,
    NoteSourceMapping,
    PageBlock,
    SourceRef,
)
from app.services.backup import create_backup_archive, restore_backup_to_empty


def test_course_backup_preserves_notebook_and_excludes_other_course(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    originals = data / "originals"
    originals.mkdir()
    engine = create_engine(f"sqlite:///{data / 'notebook.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        course, other = Course(name="保留", notebook_order_revision=3), Course(name="排除")
        db.add_all([course, other]); db.flush()
        node = KnowledgeNode(course_id=course.id, name="重复")
        db.add(node); db.flush()
        note_ids = []
        for i in (0, 1):
            (originals / f"{i}.pptx").write_bytes(b"sample")
            material = Material(course_id=course.id, lecture_title=f"讲{i}", chapter_order=1-i,
                                original_filename="sample.pptx", stored_filename=f"{i}.pptx", size_bytes=6)
            db.add(material); db.flush()
            page = MaterialPage(material_id=material.id, page_number=1, raw_text="原文")
            db.add(page); db.flush()
            block = PageBlock(page_id=page.id, block_type="text", position=0, content="原文")
            db.add(block); db.flush()
            source = SourceRef(page_block_id=block.id, quote="原文")
            note = Note(course_id=course.id, knowledge_node_id=node.id, material_id=material.id,
                        section_key="slide:1", title="重复", content_markdown=f"用户正文{i}", user_locked=True)
            db.add_all([source, note]); db.flush()
            note.source_refs.append(source)
            db.add(NoteRevision(note_id=note.id, revision_number=1, content_markdown=note.content_markdown, content_origin="user", user_locked=True))
            db.add(NoteSourceMapping(note_id=note.id, source_ref_id=source.id, fragment_key="whole-note"))
            note_ids.append(note.id)
        db.commit()
        course_id = course.id
    engine.dispose()
    package = tmp_path / "course.zip"
    create_backup_archive(data, package, course_id=course_id)
    destination = tmp_path / "restored"
    restore_backup_to_empty(package, destination)
    with closing(sqlite3.connect(destination / "notebook.sqlite3")) as db:
        assert db.execute("SELECT name,notebook_order_revision FROM courses").fetchall() == [("保留", 3)]
        assert [row[0] for row in db.execute("SELECT id FROM notes ORDER BY content_markdown")] == note_ids
        assert db.execute("SELECT lecture_title FROM materials ORDER BY chapter_order").fetchall() == [("讲1",), ("讲0",)]
        assert db.execute("SELECT count(*) FROM note_revisions").fetchone()[0] == 2
        assert db.execute("SELECT count(*) FROM note_source_mappings").fetchone()[0] == 2
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
