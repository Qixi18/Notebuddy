"""Legacy Material rows are never assigned to arbitrary Notebooks."""

import os
import subprocess
import sys
import textwrap


def test_assets_migration_preserves_unbound_rows_and_skips_storage_collisions(tmp_path):
    code = textwrap.dedent("""
        import sqlite3
        from pathlib import Path
        from alembic import command
        from app.core.config import settings
        from app.db.migrate import _config, migrate_database

        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.originals_dir.mkdir(parents=True, exist_ok=True)
        command.upgrade(_config(), 'b7c2e5a910df')
        now = '2026-10-26 00:00:00'
        (settings.originals_dir / 'collision.pdf').write_bytes(b'collision-source')
        (settings.originals_dir / 'ok.pdf').write_bytes(b'valid-source')
        with sqlite3.connect(settings.data_dir / 'notebook.sqlite3') as db:
            db.execute('INSERT INTO courses(id,name,created_at) VALUES (?,?,?)', ('c','course',now))
            for notebook_id, title, slot in [('n1','first',0),('n2','second',1)]:
                db.execute('INSERT INTO notebooks(id,course_id,title,display_order,order_revision,is_default,tree_slot,next_note_slot,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
                           (notebook_id,'c',title,slot,0,slot == 0,slot,0,now,now))
            rows = [
                ('owned-collision','n1','collision.pdf'),
                ('course-only',None,'collision.pdf'),
                ('owned-ok','n2','ok.pdf'),
                ('owned-missing','n1','missing.pdf'),
            ]
            for material_id, notebook_id, stored_name in rows:
                db.execute('''INSERT INTO materials
                    (id,course_id,notebook_id,lecture_title,topic_title,original_filename,stored_filename,
                     media_type,size_bytes,status,page_count,created_at,content_hash,parser_version,
                     document_warning,deleted_at,chapter_order)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (material_id,'c',notebook_id,material_id,None,stored_name,stored_name,
                     'application/pdf',10,'pending',0,now,None,None,None,None,0))
        migrate_database()
        with sqlite3.connect(settings.data_dir / 'notebook.sqlite3') as db:
            mapped = dict((row[0], row[1]) for row in db.execute(
                'SELECT id,asset_id FROM materials'))
            assert mapped['owned-collision'] is None
            assert mapped['course-only'] is None
            assert mapped['owned-ok'] == 'owned-ok'
            assert mapped['owned-missing'] == 'owned-missing'
            assert db.execute('SELECT notebook_id,course_id FROM materials WHERE id="course-only"').fetchone() == (None,'c')
            assert db.execute('SELECT notebook_id FROM notebook_assets WHERE asset_id="owned-ok"').fetchone() == ('n2',)
            assert db.execute('SELECT state FROM assets WHERE id="owned-missing"').fetchone() == ('missing',)
            issues = set(db.execute('SELECT source_id,issue_code FROM asset_migration_issues'))
            assert ('owned-collision','unsafe_or_ambiguous_storage_key') in issues
            assert ('owned-missing','missing_file') in issues
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        print('asset-migration-cases-ok')
    """)
    env = os.environ.copy()
    env["NOTEBOOK_DATA_DIR"] = str(tmp_path / "isolated-data")
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        env=env, timeout=90, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "asset-migration-cases-ok" in result.stdout
