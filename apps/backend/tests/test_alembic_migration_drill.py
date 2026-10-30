"""Alembic 演练：单 head、从零升级、逐级回滚限制、既有 Notebook 数据保留。

全部在 tmp_path 下的临时 SQLite 上执行，不触碰真实用户数据库。
回滚限制用断言写死：
- 回到 e29a10c7f501 只会丢掉 request_key 这一列，Quiz/复习产物表仍在；
- 回到 d9e4a7b21c60 会整表删除 quiz / quiz_items / quiz_attempts / review_artifacts，
  以及 conversation_messages 的两列 —— 这就是不可逆点，合并前必须知道；
- 任何一级回滚都不得改动 Notebook.document_json 与 document_revision。
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
BASE_REVISION = "d9e4a7b21c60"
AGENT_REVISION = "e29a10c7f501"
HEAD_REVISION = "f1a7c9d3e620"
PROCESSING_REVISION = "a5e3c8d1f209"

NOTEBOOK_DOCUMENT = json.dumps(
    {
        "schema_version": 2,
        "doc": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "attrs": {"blockId": "block-drill"},
                    "content": [{"type": "text", "text": "迁移演练必须原样保留的正文"}],
                }
            ],
        },
    },
    ensure_ascii=False,
)


def _migrate(data_dir: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ, NOTEBOOK_DATA_DIR=str(data_dir), DEEPSEEK_API_KEY="")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _indexes(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA index_list({table})")}


def _version(connection: sqlite3.Connection) -> str:
    return connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def _seed_notebook(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO notebooks (id, title, tree_slot, document_json, document_revision, "
            "created_at, updated_at) "
            "VALUES ('book-drill', '演练笔记', 0, ?, 9, '2026-10-29', '2026-10-29')",
            (NOTEBOOK_DOCUMENT,),
        )


def _assert_notebook_intact(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT document_json, document_revision FROM notebooks WHERE id = 'book-drill'"
        ).fetchone()
    assert row is not None, "Notebook 在迁移过程中丢失"
    stored = json.loads(row[0])
    assert row[1] == 9
    assert stored["doc"]["content"][0]["content"][0]["text"] == "迁移演练必须原样保留的正文"


def test_single_alembic_head():
    """合并前必须只有一个 head，否则升级路径不确定。"""
    env = dict(os.environ, DEEPSEEK_API_KEY="")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=BACKEND, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120, check=False,
    )
    assert result.returncode == 0, result.stderr
    heads = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(heads) == 1, heads
    assert HEAD_REVISION in heads[0]


def test_upgrade_from_scratch_and_stepwise_downgrade(tmp_path):
    data_dir = tmp_path
    db_path = data_dir / "notebook.sqlite3"

    # 1) 从零升级到 head
    _migrate(data_dir, "upgrade", "head")
    with sqlite3.connect(db_path) as connection:
        assert _version(connection) == HEAD_REVISION
        tables = _tables(connection)
        for table in ("quizzes", "quiz_items", "quiz_attempts", "review_artifacts"):
            assert table in tables
        assert "request_key" in _columns(connection, "quiz_attempts")
        assert "uq_quiz_attempts_item_request" in _indexes(connection, "quiz_attempts")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    # 2) 写入既有 Notebook 与一条作答，验证升级后可正常使用
    _seed_notebook(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO courses (id, name, notebook_order_revision, created_at) "
            "VALUES ('course-drill', '演练课程', 0, '2026-10-29')"
        )
        connection.execute(
            "INSERT INTO quizzes (id, course_id, title, status, created_at) "
            "VALUES ('quiz-drill', 'course-drill', '演练卷', 'active', '2026-10-29')"
        )
    _assert_notebook_intact(db_path)

    # 3) 唯一索引真的生效：(item_id, request_key) 不能重复
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO quiz_items (id, quiz_id, seq, item_type, stem, options_json, answer, "
            "explanation, favorite, marked, dismissed, created_at) "
            "VALUES ('item-drill', 'quiz-drill', 1, 'choice', '题', '[\"A\"]', 'A', '', 0, 0, 0, '2026-10-29')"
        )
        connection.execute(
            "INSERT INTO quiz_attempts (id, quiz_id, item_id, request_key, answer, correct, created_at) "
            "VALUES ('a1', 'quiz-drill', 'item-drill', 'rk', 'A', 1, '2026-10-29')"
        )
        try:
            connection.execute(
                "INSERT INTO quiz_attempts (id, quiz_id, item_id, request_key, answer, correct, created_at) "
                "VALUES ('a2', 'quiz-drill', 'item-drill', 'rk', 'A', 1, '2026-10-29')"
            )
            raise AssertionError("(item_id, request_key) 唯一索引没有生效")
        except sqlite3.IntegrityError:
            pass

    # 4) 回滚一级：只丢 request_key，作答与产物表仍在
    _migrate(data_dir, "downgrade", AGENT_REVISION)
    with sqlite3.connect(db_path) as connection:
        # Downgrading the agent branch keeps the independent processing
        # migration applied; the Alembic version table therefore points at it.
        assert _version(connection) == PROCESSING_REVISION
        assert "request_key" not in _columns(connection, "quiz_attempts")
        assert "uq_quiz_attempts_item_request" not in _indexes(connection, "quiz_attempts")
        assert "quizzes" in _tables(connection)
        assert connection.execute("SELECT count(*) FROM quiz_attempts").fetchone() == (1,)
    _assert_notebook_intact(db_path)

    # 5) 再回滚一级：这是不可逆点，agent 学习相关表整表消失
    _migrate(data_dir, "downgrade", BASE_REVISION)
    with sqlite3.connect(db_path) as connection:
        tables = _tables(connection)
        for table in ("quizzes", "quiz_items", "quiz_attempts", "review_artifacts"):
            assert table not in tables
        message_columns = _columns(connection, "conversation_messages")
        assert "process_json" not in message_columns
        assert "suggestions_json" not in message_columns
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    _assert_notebook_intact(db_path)

    # 6) 回滚后可以再次升级（迁移可重入，不留半成品）
    _migrate(data_dir, "upgrade", "head")
    with sqlite3.connect(db_path) as connection:
        assert _version(connection) == HEAD_REVISION
        assert "uq_quiz_attempts_item_request" in _indexes(connection, "quiz_attempts")
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        # 回滚时被删掉的作答不会复活 —— 回滚是有数据代价的，这里如实记录
        assert connection.execute("SELECT count(*) FROM quiz_attempts").fetchone() == (0,)
    _assert_notebook_intact(db_path)
