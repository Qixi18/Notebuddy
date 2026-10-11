"""Forest evidence and curriculum originals survive full backups and checkpoints."""

import json
import sqlite3
import zipfile
from contextlib import closing

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.checkpoint import create_checkpoint, restore_checkpoint
from app.db.database import Base
from app.db.models import (
    Course,
    CrossCourseRelation,
    CurriculumImport,
    ForestCourseProfile,
    ForestJob,
    KnowledgeNode,
    Material,
    Note,
)
from app.services.backup import create_backup_archive, preview_backup, restore_backup_to_empty


@pytest.fixture
def forest_data(tmp_path):
    data = tmp_path / "data"
    originals = data / "originals"
    originals.mkdir(parents=True)
    for name in ("material.pdf", "curriculum.pdf"):
        (originals / name).write_bytes(name.encode())
    (data / ".env").write_text("DO_NOT_BACK_UP_THIS_SECRET", encoding="utf-8")
    engine = create_engine(f"sqlite:///{data / 'notebook.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        courses = [Course(id=f"course-{i}", name=f"课程{i}") for i in range(2)]
        db.add_all(courses); db.flush()
        material = Material(id="material", course_id=courses[0].id, lecture_title="讲", original_filename="display.pdf", stored_filename="material.pdf", size_bytes=12)
        curriculum = CurriculumImport(id="curriculum", filename="../../.env", stored_filename="curriculum.pdf", status="confirmed", input_text="方案", rows_json="[]")
        db.add_all([material, curriculum]); db.flush()
        notes = []
        for i, course in enumerate(courses):
            node = KnowledgeNode(id=f"node-{i}", course_id=course.id, name="概念")
            db.add(node); db.flush()
            note = Note(id=f"note-{i}", course_id=course.id, knowledge_node_id=node.id, material_id=material.id if i == 0 else None, title="小节", content_markdown="用户正文", user_locked=True, revision_number=4)
            db.add(note); notes.append(note)
            db.add(ForestCourseProfile(course_id=course.id, position=i, semester=2, learning_state="completed"))
        db.flush()
        db.add(CrossCourseRelation(source_course_id=courses[0].id, target_course_id=courses[1].id, source_note_id=notes[0].id, target_note_id=notes[1].id, source_revision=4, target_revision=4, relation_type="related", reason="真实关联", status="confirmed"))
        db.add_all([ForestJob(kind="curriculum_import", curriculum_import_id=curriculum.id), ForestJob(kind="cross_course_relations", course_id=courses[0].id), ForestJob(kind="cross_course_relations")])
        db.commit()
    engine.dispose()
    return data


def test_full_backup_includes_only_stored_curriculum_original_and_preserves_relations(forest_data, tmp_path):
    package = tmp_path / "full.zip"
    manifest = create_backup_archive(forest_data, package)
    assert {entry["name"] for entry in manifest["originals"]} == {"material.pdf", "curriculum.pdf"}
    assert preview_backup(package)["valid"]
    restored = tmp_path / "restored"
    restore_backup_to_empty(package, restored)
    assert (restored / "originals" / "curriculum.pdf").read_bytes() == b"curriculum.pdf"
    assert not (restored / ".env").exists()
    with closing(sqlite3.connect(restored / "notebook.sqlite3")) as db:
        assert db.execute("SELECT source_note_id,target_note_id FROM cross_course_relations").fetchall() == [("note-0", "note-1")]
        assert db.execute("SELECT revision_number,content_markdown,user_locked FROM notes").fetchall() == [(4, "用户正文", 1)] * 2
        assert db.execute("SELECT count(*) FROM forest_jobs").fetchone()[0] == 3
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_single_course_backup_removes_global_curriculum_jobs_and_cross_course_relations(forest_data, tmp_path):
    package = tmp_path / "single.zip"
    manifest = create_backup_archive(forest_data, package, course_id="course-0")
    assert [entry["name"] for entry in manifest["originals"]] == ["material.pdf"]
    restored = tmp_path / "single-restored"
    restore_backup_to_empty(package, restored)
    with closing(sqlite3.connect(restored / "notebook.sqlite3")) as db:
        assert db.execute("SELECT course_id FROM forest_course_profiles").fetchall() == [("course-0",)]
        for table in ("curriculum_imports", "forest_jobs", "cross_course_relations"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_checkpoint_restores_curriculum_original_and_referenced_forest_data(forest_data, tmp_path):
    checkpoint = tmp_path / "checkpoint"
    create_checkpoint(forest_data, checkpoint)
    assert (checkpoint / "originals" / "curriculum.pdf").read_bytes() == b"curriculum.pdf"
    restored = tmp_path / "checkpoint-restored"
    restore_checkpoint(checkpoint, restored)
    assert (restored / "originals" / "curriculum.pdf").read_bytes() == b"curriculum.pdf"
    with closing(sqlite3.connect(restored / "notebook.sqlite3")) as db:
        assert db.execute("SELECT stored_filename FROM curriculum_imports").fetchall() == [("curriculum.pdf",)]
        assert db.execute("SELECT count(*) FROM cross_course_relations").fetchone()[0] == 1


def test_preview_rejects_unlisted_curriculum_original(forest_data, tmp_path):
    valid = tmp_path / "valid.zip"
    create_backup_archive(forest_data, valid)
    damaged = tmp_path / "damaged.zip"
    with zipfile.ZipFile(valid) as original, zipfile.ZipFile(damaged, "w") as output:
        for name in original.namelist():
            if name == "originals/curriculum.pdf":
                continue
            content = original.read(name)
            if name == "manifest.json":
                manifest = json.loads(content)
                manifest["originals"] = [entry for entry in manifest["originals"] if entry["name"] != "curriculum.pdf"]
                content = json.dumps(manifest).encode()
            output.writestr(name, content)
    preview = preview_backup(damaged)
    assert not preview["valid"]
    assert "database references missing original: curriculum.pdf" in preview["errors"]


@pytest.mark.parametrize("unsafe", ["../.env", "..\\.env", "C:\\Users\\file.pdf"])
def test_unsafe_curriculum_stored_name_is_rejected(forest_data, tmp_path, unsafe):
    with closing(sqlite3.connect(forest_data / "notebook.sqlite3")) as db:
        db.execute("UPDATE curriculum_imports SET stored_filename=?", (unsafe,)); db.commit()
    with pytest.raises(ValueError):
        create_backup_archive(forest_data, tmp_path / "unsafe.zip")
    with pytest.raises(ValueError):
        create_checkpoint(forest_data, tmp_path / "unsafe-checkpoint")


def test_v2_archive_without_forest_tables_still_restores(forest_data, tmp_path):
    with closing(sqlite3.connect(forest_data / "notebook.sqlite3")) as db:
        for table in ("cross_course_relations", "forest_jobs", "forest_course_profiles", "curriculum_imports"):
            db.execute(f"DROP TABLE {table}")
        db.commit()
    package = tmp_path / "old-v2.zip"
    manifest = create_backup_archive(forest_data, package)
    assert manifest["format"] == 2
    assert [entry["name"] for entry in manifest["originals"]] == ["material.pdf"]
    restored = tmp_path / "old-restored"
    assert restore_backup_to_empty(package, restored)["valid"]
