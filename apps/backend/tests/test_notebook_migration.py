"""Populated previous-head database keeps note identity and all references."""
import os
import subprocess
import sys
import textwrap


def test_upgrade_preserves_single_shared_and_unlocated_notes(tmp_path):
    code = textwrap.dedent("""
        import sqlite3
        from alembic import command
        from app.db.migrate import _config, migrate_database
        from app.core.config import settings
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        settings.originals_dir.mkdir(parents=True, exist_ok=True)
        for i in (1,2):
            (settings.originals_dir / f'{i}.pptx').write_bytes(b'x')
        command.upgrade(_config(), 'f7b9c2d6e401')
        now = '2026-10-06 00:00:00'
        database = settings.data_dir / 'notebook.sqlite3'
        with sqlite3.connect(database) as db:
            db.execute('INSERT INTO courses (id,name,created_at) VALUES (?,?,?)', ('c','课程',now))
            for i in (1,2):
                db.execute('INSERT INTO materials (id,course_id,lecture_title,original_filename,stored_filename,size_bytes,status,page_count,created_at) VALUES (?,?,?,?,?,?,?,?,?)', (f'm{i}','c',f'讲{i}','a.pptx',f'{i}.pptx',1,'completed',1,now))
                db.execute('INSERT INTO material_pages (id,material_id,page_number,raw_text,parse_status,location_type,extraction_method,is_active) VALUES (?,?,?,?,?,?,?,?)', (f'p{i}',f'm{i}',i,'原文','parsed','page','native_text',1))
                db.execute('INSERT INTO page_blocks (id,page_id,block_type,content,position,is_bold,extraction_method) VALUES (?,?,?,?,?,?,?)', (f'b{i}',f'p{i}','text','原文',0,0,'native_text'))
                db.execute('INSERT INTO source_refs (id,page_block_id,source_type,quote,created_at,status) VALUES (?,?,?,?,?,?)', (f's{i}',f'b{i}','course_material','原文',now,'active'))
            for i in (1,2,3):
                db.execute('INSERT INTO knowledge_nodes (id,course_id,name,status,created_at,updated_at) VALUES (?,?,?,?,?,?)', (f'k{i}','c',f'点{i}','active',now,now))
                db.execute('INSERT INTO notes (id,course_id,knowledge_node_id,title,content_markdown,content_origin,user_locked,revision_number,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)', (f'n{i}','c',f'k{i}',f'点{i}','用户正文','user',1,2,now,now))
                db.execute('INSERT INTO note_revisions VALUES (?,?,?,?,?,?,?)', (f'r{i}',f'n{i}',2,'用户正文','user',1,now))
            db.execute('INSERT INTO note_source_refs VALUES (?,?)', ('n1','s1'))
            db.execute('INSERT INTO note_source_refs VALUES (?,?)', ('n2','s1'))
            db.execute('INSERT INTO note_source_refs VALUES (?,?)', ('n2','s2'))
        assert migrate_database() is not None
        assert migrate_database() is None
        with sqlite3.connect(database) as db:
            assert db.execute('SELECT id,material_id FROM notes ORDER BY id').fetchall() == [('n1','m1'),('n2',None),('n3',None)]
            assert db.execute('SELECT content_markdown,revision_number,user_locked FROM notes').fetchall() == [('用户正文',2,1)] * 3
            assert db.execute('SELECT note_id FROM note_revisions ORDER BY note_id').fetchall() == [('n1',),('n2',),('n3',)]
            assert db.execute('SELECT count(*) FROM note_source_refs').fetchone()[0] == 3
            db.execute("INSERT INTO notes (id,course_id,knowledge_node_id,title,content_markdown,content_origin,user_locked,revision_number,created_at,updated_at,material_id,section_key,section_order) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", ('new','c','k1','新讲','独立正文','ai',0,1,now,now,'m2','page:1',1))
            assert db.execute('PRAGMA foreign_key_check').fetchall() == []
        print('notebook-upgrade-ok')
    """)
    env = os.environ.copy()
    env.update(NOTEBOOK_DATA_DIR=str(tmp_path), DEEPSEEK_API_KEY="", TAVILY_API_KEY="")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                            env=env, timeout=90, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "notebook-upgrade-ok" in result.stdout
