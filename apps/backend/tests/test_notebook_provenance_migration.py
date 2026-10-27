"""Upgrade/downgrade provenance metadata only in an isolated SQLite vault."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def test_source_fingerprint_migration_preserves_existing_rows(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    data_dir = tmp_path / "migration-vault"
    data_dir.mkdir()
    env = dict(os.environ, NOTEBOOK_DATA_DIR=str(data_dir), DEEPSEEK_API_KEY="")

    def migrate(*args):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", *args], cwd=backend, env=env,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    migrate("upgrade", "b3f1c7d92a10")
    path = data_dir / "notebook.sqlite3"
    with sqlite3.connect(path) as connection:
        # A representative historical edge; the migration must not infer a
        # fingerprint from body content it has not verified.
        connection.execute(
            "INSERT INTO notebook_block_sources "
            "(id, notebook_id, block_id, parse_run_id, document_block_id, page_number, "
            "status, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("source-1", "book-1", "body-1", "run-1", "ir-1", 1, "stale", "2026-10-27"),
        )
        # Satisfy the existing Notebook foreign key for Alembic's integrity
        # check without depending on ORM metadata from the newer revision.
        connection.execute(
            "INSERT INTO notebooks (id, title, tree_slot, display_order, is_default, "
            "next_note_slot, order_revision, created_at, updated_at) "
            "VALUES (?, ?, 0, 0, 0, 0, 0, ?, ?)",
            ("book-1", "migration fixture", "2026-10-27", "2026-10-27"),
        )
    migrate("upgrade", "head")
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT id, status, body_fingerprint FROM notebook_block_sources",
        ).fetchall() == [("source-1", "stale", None)]
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    migrate("downgrade", "b3f1c7d92a10")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT id, status FROM notebook_block_sources").fetchall() == [
            ("source-1", "stale"),
        ]
        assert "body_fingerprint" not in {
            row[1] for row in connection.execute("PRAGMA table_info(notebook_block_sources)")
        }
