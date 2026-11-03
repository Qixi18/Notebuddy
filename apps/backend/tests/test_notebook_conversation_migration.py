"""Notebook-conversation schema migration safety on isolated SQLite databases."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
BASE = "f1a7c9d3e620"
HEAD = "a7c4d2e91b60"


def _alembic(data_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args], cwd=BACKEND,
        env=dict(os.environ, NOTEBOOK_DATA_DIR=str(data_dir), DEEPSEEK_API_KEY=""),
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180,
        check=False,
    )


def _column(connection: sqlite3.Connection, name: str) -> tuple:
    return next(row for row in connection.execute("PRAGMA table_info(conversations)") if row[1] == name)


def test_upgrade_preserves_course_history_and_downgrade_guards_notebook_sessions(tmp_path: Path) -> None:
    db_path = tmp_path / "notebook.sqlite3"
    result = _alembic(tmp_path, "upgrade", BASE)
    assert result.returncode == 0, result.stdout + result.stderr
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO courses (id, name, notebook_order_revision, created_at) "
            "VALUES ('course-old', '旧课程', 0, '2026-11-01')"
        )
        connection.execute(
            "INSERT INTO conversations "
            "(id, course_id, title, default_scope, scope, note_id, note_title, created_at, updated_at) "
            "VALUES ('conversation-old', 'course-old', '旧会话', 'note', 'note', 'legacy-note', '旧笔记', "
            "'2026-11-01', '2026-11-01')"
        )
    result = _alembic(tmp_path, "upgrade", HEAD)
    assert result.returncode == 0, result.stdout + result.stderr

    with sqlite3.connect(db_path) as connection:
        assert _column(connection, "course_id")[3] == 0  # nullable
        assert "notebook_id" in {row[1] for row in connection.execute("PRAGMA table_info(conversations)")}
        assert "ix_conversations_notebook_id" in {
            row[1] for row in connection.execute("PRAGMA index_list(conversations)")
        }
        old = connection.execute(
            "SELECT course_id, scope, note_id, note_title FROM conversations WHERE id='conversation-old'"
        ).fetchone()
        assert old == ("course-old", "note", "legacy-note", "旧笔记")
        connection.execute(
            "INSERT INTO notebooks (id, title, tree_slot, created_at, updated_at) "
            "VALUES ('notebook-new', '新笔记', 0, '2026-11-01', '2026-11-01')"
        )
        connection.execute(
            "INSERT INTO conversations "
            "(id, course_id, notebook_id, title, default_scope, scope, created_at, updated_at) "
            "VALUES ('conversation-new', NULL, 'notebook-new', '新会话', 'notebook', 'notebook', "
            "'2026-11-01', '2026-11-01')"
        )
        connection.commit()
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("DELETE FROM notebooks WHERE id='notebook-new'")
        conversation_target = connection.execute(
            "SELECT scope, course_id, notebook_id FROM conversations WHERE id='conversation-new'"
        ).fetchone()
        assert conversation_target == ("notebook", None, None)
        connection.commit()

    blocked = _alembic(tmp_path, "downgrade", BASE)
    assert blocked.returncode != 0
    assert "Notebook-scoped conversations exist" in blocked.stdout + blocked.stderr

    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM conversations WHERE id='conversation-new'")
        connection.commit()
    result = _alembic(tmp_path, "downgrade", BASE)
    assert result.returncode == 0, result.stdout + result.stderr
    with sqlite3.connect(db_path) as connection:
        columns = {row[1]: row for row in connection.execute("PRAGMA table_info(conversations)")}
        assert "notebook_id" not in columns
        assert columns["course_id"][3] == 1  # restored NOT NULL
        assert connection.execute(
            "SELECT course_id, scope, note_id, note_title FROM conversations WHERE id='conversation-old'"
        ).fetchone() == ("course-old", "note", "legacy-note", "旧笔记")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
