"""Previous-head and unstamped legacy databases upgrade without losing notes."""

import os
import subprocess
import sys
import textwrap

import pytest


@pytest.mark.parametrize("previous,unstamp", [("a81c6e204f35", False), ("964d70a06320", True)])
def test_forest_upgrade_preserves_old_data_and_repeat_startup(tmp_path, previous, unstamp):
    code = textwrap.dedent(f"""
        import sqlite3
        from alembic import command
        from app.db.migrate import _config, migrate_database
        from app.core.config import settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        command.upgrade(_config(), {previous!r})
        database = settings.data_dir / 'notebook.sqlite3'
        now = '2026-10-11 00:00:00'
        with sqlite3.connect(database) as db:
            db.execute('INSERT INTO courses (id,name,created_at) VALUES (?,?,?)', ('c','old course',now))
            db.execute('INSERT INTO knowledge_nodes (id,course_id,name,status,created_at,updated_at) VALUES (?,?,?,?,?,?)', ('k','c','concept','active',now,now))
            db.execute('INSERT INTO notes (id,course_id,knowledge_node_id,title,content_markdown,content_origin,user_locked,revision_number,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)', ('n','c','k','note','user body','user',1,4,now,now))
            if {unstamp!r}:
                db.execute('DROP TABLE alembic_version')
        assert migrate_database() is not None
        assert migrate_database() is None
        with sqlite3.connect(database) as db:
            tables = {{row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}}
            assert {{'forest_course_profiles','curriculum_imports','forest_jobs','cross_course_relations'}} <= tables
            assert db.execute('SELECT id,content_markdown,user_locked,revision_number FROM notes').fetchall() == [('n','user body',1,4)]
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        print('forest-upgrade-ok')
    """)
    env = os.environ.copy()
    env.update(NOTEBOOK_DATA_DIR=str(tmp_path), DEEPSEEK_API_KEY="", TAVILY_API_KEY="")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=90, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "forest-upgrade-ok" in result.stdout
