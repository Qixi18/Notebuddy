"""Prove a populated pre-Alembic database survives the versioned upgrade."""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap


def test_legacy_upgrade_preserves_note_and_source(tmp_path):
    code = textwrap.dedent("""
        import sqlite3
        from pathlib import Path
        from alembic import command
        from alembic.script import ScriptDirectory
        from app.db.migrate import _config, migrate_database
        from app.db.checkpoint import verify_checkpoint
        from app.core.config import settings

        command.upgrade(_config(), '964d70a06320')
        database = settings.data_dir / 'notebook.sqlite3'
        originals = settings.data_dir / 'originals'
        originals.mkdir(exist_ok=True)
        (originals / 'old.pptx').write_bytes(b'old')
        now = '2026-10-06 00:00:00'
        with sqlite3.connect(database) as db:
            db.execute('INSERT INTO courses VALUES (?,?,?,?)', ('c', '旧课程', None, now))
            db.execute('INSERT INTO materials (id,course_id,lecture_title,topic_title,original_filename,stored_filename,media_type,size_bytes,status,page_count,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                ('m','c','旧讲次',None,'old.pptx','old.pptx',None,3,'completed',1,now))
            db.execute('INSERT INTO material_pages VALUES (?,?,?,?,?,?,?)', ('p','m',1,'标题','原文','parsed',None))
            db.execute('INSERT INTO page_blocks VALUES (?,?,?,?,?,?,?)', ('b','p','text','原文',0,None,0))
            db.execute('INSERT INTO source_refs VALUES (?,?,?,?,?)', ('s','b','course_material','原文',now))
            db.execute('INSERT INTO knowledge_nodes VALUES (?,?,?,?,?,?,?)', ('k','c','旧知识',None,'active',now,now))
            db.execute('INSERT INTO notes VALUES (?,?,?,?,?,?,?,?,?,?)', ('n','c','k','旧笔记','# 用户正文','user',1,2,now,now))
            db.execute('INSERT INTO note_revisions VALUES (?,?,?,?,?,?,?)', ('r','n',2,'# 用户正文','user',1,now))
            db.execute('INSERT INTO note_source_refs VALUES (?,?)', ('n','s'))
            db.execute('DROP TABLE alembic_version')
        checkpoint = migrate_database()
        assert checkpoint and verify_checkpoint(checkpoint)['format'] == 1
        assert migrate_database() is None
        with sqlite3.connect(database) as db:
            assert db.execute('select content_markdown,revision_number from notes').fetchone() == ('# 用户正文',2)
            assert db.execute('select quote from source_refs').fetchone()[0] == '原文'
            assert db.execute('select note_id,source_ref_id from note_source_refs').fetchone() == ('n','s')
            assert db.execute('select version_num from alembic_version').fetchone()[0] == ScriptDirectory.from_config(_config()).get_current_head()
        print('legacy-upgrade-ok')
    """)
    env = os.environ.copy()
    env.update({"NOTEBOOK_DATA_DIR": str(tmp_path), "DEEPSEEK_API_KEY": "", "TAVILY_API_KEY": ""})
    completed = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                               env=env, timeout=90, check=False)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "legacy-upgrade-ok" in completed.stdout
