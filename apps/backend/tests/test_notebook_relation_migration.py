"""Relation schema changes preserve existing links and refuse lossy rollback."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest


def test_relation_anchor_migration_preserves_links_and_guards_rollback(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    env = dict(os.environ, NOTEBOOK_DATA_DIR=str(tmp_path), DEEPSEEK_API_KEY="")

    def migrate(*args, succeeds=True):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=backend, env=env, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=60, check=False,
        )
        assert (result.returncode == 0) is succeeds, result.stdout + result.stderr
        return result

    migrate("upgrade", "c7d2e9a04b16")
    path = tmp_path / "notebook.sqlite3"
    with sqlite3.connect(path) as connection:
        for identity in ("a", "b"):
            connection.execute(
                "INSERT INTO notebooks (id, title, tree_slot, display_order, is_default, "
                "next_note_slot, order_revision, created_at, updated_at) "
                "VALUES (?, ?, 0, 0, 0, 0, 0, ?, ?)",
                (identity, identity, "2026-10-27", "2026-10-27"),
            )
        connection.execute(
            "INSERT INTO notebook_relations (id, source_notebook_id, target_notebook_id, "
            "relation_type, description, created_at) VALUES ('old', 'a', 'b', 'related', 'original', '2026-10-27')"
        )
    migrate("upgrade", "head")
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT id, description, origin, source_block_id FROM notebook_relations"
        ).fetchall() == [("old", "original", "manual", None)]
        connection.execute(
            "INSERT INTO notebook_relations (id, source_notebook_id, target_notebook_id, relation_type, "
            "source_block_id, target_block_id, created_at) "
            "VALUES ('section', 'a', 'b', 'related', 'h-1', 'h-2', '2026-10-27')"
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO notebook_relations (id, source_notebook_id, target_notebook_id, relation_type, "
                "source_block_id, target_block_id, created_at) "
                "VALUES ('duplicate', 'a', 'b', 'related', 'h-1', 'h-2', '2026-10-27')"
            )
    blocked = migrate("downgrade", "c7d2e9a04b16", succeeds=False)
    assert "without losing distinct links" in blocked.stderr
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT count(*) FROM notebook_relations").fetchone() == (2,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        connection.execute("DELETE FROM notebook_relations WHERE id = 'section'")
    migrate("downgrade", "c7d2e9a04b16")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT id, description FROM notebook_relations").fetchall() == [
            ("old", "original"),
        ]
        assert "origin" not in {row[1] for row in connection.execute("PRAGMA table_info(notebook_relations)")}
