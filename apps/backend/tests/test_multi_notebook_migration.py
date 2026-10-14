import os
import subprocess
import sys
import textwrap


def test_old_database_default_books_preserve_locked_notes_and_checkpoint(tmp_path):
    code = textwrap.dedent("""
        import sqlite3
        from alembic import command
        from app.db.migrate import _config, migrate_database
        from app.core.config import settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        command.upgrade(_config(), 'd51e8f0a2b63')
        database = settings.data_dir / 'notebook.sqlite3'
        now = '2026-10-06 00:00:00'
        with sqlite3.connect(database) as db:
            for cid in ('c','empty'):
                db.execute('INSERT INTO courses (id,name,created_at) VALUES (?,?,?)', (cid,cid,now))
            db.execute('INSERT INTO knowledge_nodes (id,course_id,name,status,created_at,updated_at) VALUES (?,?,?,?,?,?)', ('k','c','concept','active',now,now))
            db.execute('INSERT INTO notes (id,course_id,knowledge_node_id,title,content_markdown,content_origin,user_locked,revision_number,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)', ('n','c','k','title','user content','user',1,2,now,now))
            db.execute('INSERT INTO note_revisions VALUES (?,?,?,?,?,?,?)', ('r','n',2,'user content','user',1,now))
        checkpoint = migrate_database()
        assert checkpoint is not None and checkpoint.exists()
        assert migrate_database() is None
        with sqlite3.connect(database) as db:
            books = db.execute('SELECT id,course_id,title,is_default FROM notebooks').fetchall()
            assert len(books) == 1 and books[0][1:] == ('c','c·课程笔记',1)
            assert db.execute('SELECT id,content_markdown,user_locked,revision_number,notebook_id,tree_slot FROM notes').fetchone() == ('n','user content',1,2,books[0][0],0)
            assert db.execute('SELECT note_id,content_markdown FROM note_revisions').fetchone() == ('n','user content')
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        print('multi-notebook-upgrade-ok')
    """)
    env = {**os.environ, "NOTEBOOK_DATA_DIR": str(tmp_path), "DEEPSEEK_API_KEY": "", "TAVILY_API_KEY": ""}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            env=env, timeout=90, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_old_package_upgrade_and_failed_migration_recover_from_checkpoint(tmp_path):
    code = textwrap.dedent("""
        import os
        import sqlite3
        import subprocess
        import sys
        from pathlib import Path
        from alembic import command, op
        from app.db.migrate import _config, migrate_database
        from app.db.database import engine
        from app.db.checkpoint import restore_checkpoint, verify_checkpoint
        from app.core.config import settings
        from app.services.backup import create_backup_archive, restore_backup_to_empty
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        command.upgrade(_config(), 'd51e8f0a2b63')
        database = settings.data_dir / 'notebook.sqlite3'
        now = '2026-10-06 00:00:00'
        with sqlite3.connect(database) as db:
            db.execute('INSERT INTO courses (id,name,created_at) VALUES (?,?,?)', ('c','course',now))
            db.execute('INSERT INTO knowledge_nodes (id,course_id,name,status,created_at,updated_at) VALUES (?,?,?,?,?,?)', ('k','c','concept','active',now,now))
            db.execute('INSERT INTO notes (id,course_id,knowledge_node_id,title,content_markdown,content_origin,user_locked,revision_number,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)', ('n','c','k','title','protected user body','user',1,4,now,now))
        package = settings.data_dir.parent / 'old-v2.zip'
        create_backup_archive(settings.data_dir, package)
        old_create = op.create_table
        def fail_after_ddl(name, *args, **kwargs):
            result = old_create(name, *args, **kwargs)
            if name == 'notebooks':
                raise RuntimeError('simulated migration interruption')
            return result
        op.create_table = fail_after_ddl
        try:
            migrate_database()
            raise AssertionError('interruption expected')
        except RuntimeError as exc:
            assert 'simulated migration interruption' in str(exc)
        finally:
            op.create_table = old_create
        engine.dispose()
        checkpoint = next(settings.backups_dir.glob('pre-migration-*'))
        assert verify_checkpoint(checkpoint)['format'] == 1
        destinations = [settings.data_dir.parent / 'from-checkpoint', settings.data_dir.parent / 'from-old-package']
        restore_checkpoint(checkpoint, destinations[0])
        restore_backup_to_empty(package, destinations[1])
        upgrade_code = 'from app.db.migrate import migrate_database; assert migrate_database() is not None; assert migrate_database() is None'
        for destination in destinations:
            completed = subprocess.run([sys.executable, '-c', upgrade_code], capture_output=True, text=True,
                env={**os.environ, 'NOTEBOOK_DATA_DIR': str(destination)}, timeout=60)
            assert completed.returncode == 0, completed.stdout + completed.stderr
            with sqlite3.connect(destination / 'notebook.sqlite3') as db:
                note = db.execute('SELECT id,content_markdown,user_locked,revision_number,notebook_id,tree_slot FROM notes').fetchone()
                assert note[:4] == ('n','protected user body',1,4)
                assert note[4] and note[5] == 0
                assert db.execute('PRAGMA foreign_key_check').fetchall() == []
    """)
    env = {**os.environ, "NOTEBOOK_DATA_DIR": str(tmp_path / "data"), "DEEPSEEK_API_KEY": "", "TAVILY_API_KEY": ""}
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            env=env, timeout=90, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
