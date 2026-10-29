"""Agent 学习产物的迁移必须能升级、能回滚、能重入，且不碰既有 Notebook 正文。

覆盖 `e29a10c7f501_agent_learning_artifacts`：
- upgrade：建 quizzes / quiz_items / quiz_attempts / review_artifacts，
  给 conversation_messages 加 process_json / suggestions_json；
- 历史库（已带 suggestions_json）升级时把旧建议回填成 review_artifacts，
  并写回确定性的 artifact_id；干净库升级时空转，不产生伪造产物；
- downgrade：新表与新列原样移除，其余业务数据不动，且回滚后可再次升级；
- 部分应用状态（只有部分表）能被续上，不撞 duplicate column / already exists。

只用 tmp_path 下的临时 SQLite，绝不触碰真实用户库。
"""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PARENT_REVISION = "d9e4a7b21c60"
NEW_REVISION = "e29a10c7f501"

NOTEBOOK_DOCUMENT = json.dumps(
    {
        "schema_version": 2,
        "doc": {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "attrs": {"blockId": "block-keep-me"},
                    "content": [{"type": "text", "text": "迁移期间必须原样保留的正文"}],
                }
            ],
        },
    },
    ensure_ascii=False,
)

LEGACY_SUGGESTIONS = [
    {
        "type": "review_outline",
        "title": "期中复习提纲",
        "modules": [
            {"title": "第一章", "priority": "high", "items": [{"point": "要点", "ref": "第 1 页"}]}
        ],
        "favorite": True,
    },
    {
        "type": "concept_contrast",
        "artifact_id": "artifact-fixed-id",
        "pairs": [{"a": "梯度下降", "b": "牛顿法"}],
    },
    # 非学习产物类型的建议必须被忽略，不能变成 review_artifacts
    {"type": "notebook_edit", "title": "无关建议"},
]


def _migrate(tmp_path: Path, *args: str):
    env = dict(os.environ, NOTEBOOK_DATA_DIR=str(tmp_path), DEEPSEEK_API_KEY="")
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def _seed(db_path: Path) -> None:
    """在父版本 schema 上写入一门课、一本有正文的 Notebook、一条会话消息。"""
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "INSERT INTO courses (id, name, notebook_order_revision, created_at) "
            "VALUES ('course-1', '数据结构', 0, '2026-10-29')"
        )
        connection.execute(
            "INSERT INTO notebooks (id, course_id, title, tree_slot, document_json, "
            "document_revision, created_at, updated_at) "
            "VALUES ('book-1', 'course-1', '第一讲', 0, ?, 7, '2026-10-29', '2026-10-29')",
            (NOTEBOOK_DOCUMENT,),
        )
        connection.execute(
            "INSERT INTO conversations (id, course_id, title, default_scope, created_at, updated_at) "
            "VALUES ('conv-1', 'course-1', '答疑', 'course', '2026-10-29', '2026-10-29')"
        )
        connection.execute(
            "INSERT INTO conversation_messages (id, conversation_id, role, content, status, created_at) "
            "VALUES ('msg-1', 'conv-1', 'assistant', '带复习建议的回答', 'complete', '2026-10-29')"
        )


def _assert_notebook_intact(db_path: Path) -> None:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT document_json, document_revision FROM notebooks WHERE id = 'book-1'"
        ).fetchone()
    assert row is not None, "Notebook 在迁移过程中丢失"
    document_json, document_revision = row
    assert document_revision == 7
    stored = json.loads(document_json)
    assert stored["doc"]["content"][0]["attrs"]["blockId"] == "block-keep-me"
    assert stored["doc"]["content"][0]["content"][0]["text"] == "迁移期间必须原样保留的正文"


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _indexes(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA index_list({table})")}


def test_agent_learning_migration_backfills_legacy_suggestions_and_rolls_back(tmp_path):
    """历史库（父版本 + 已有 suggestions_json 列）升级要真的搬迁旧建议。"""
    db_path = tmp_path / "notebook.sqlite3"

    _migrate(tmp_path, "upgrade", PARENT_REVISION)
    _seed(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("ALTER TABLE conversation_messages ADD COLUMN suggestions_json TEXT")
        connection.execute(
            "UPDATE conversation_messages SET suggestions_json = ? WHERE id = 'msg-1'",
            (json.dumps(LEGACY_SUGGESTIONS, ensure_ascii=False),),
        )

    _migrate(tmp_path, "upgrade", NEW_REVISION)

    with sqlite3.connect(db_path) as connection:
        tables = _tables(connection)
        for table in ("quizzes", "quiz_items", "quiz_attempts", "review_artifacts"):
            assert table in tables
        message_columns = _columns(connection, "conversation_messages")
        assert {"process_json", "suggestions_json"} <= message_columns
        assert _columns(connection, "quiz_items") >= {
            "stem", "answer", "favorite", "marked", "dismissed",
        }
        assert _columns(connection, "review_artifacts") >= {
            "kind", "payload_json", "favorite", "dismissed",
        }

        # 回填：只有 review_outline / concept_contrast 变成产物，notebook_edit 被忽略
        artifacts = connection.execute(
            "SELECT id, kind, title, favorite FROM review_artifacts ORDER BY kind"
        ).fetchall()
        assert [row[1] for row in artifacts] == ["concept_contrast", "review_outline"]
        by_kind = {row[1]: row for row in artifacts}
        # 中文标题必须逐字保留（防止编码回归把标题写成乱码）
        assert by_kind["review_outline"][2] == "期中复习提纲"
        assert by_kind["review_outline"][3] == 1
        assert by_kind["concept_contrast"][0] == "artifact-fixed-id"
        assert by_kind["concept_contrast"][2] == "「梯度下降 vs 牛顿法」"
        # 没有 artifact_id 的建议要拿到确定性 id，并把 id 写回消息
        assert by_kind["review_outline"][0].startswith("bf-")
        stored_suggestions = json.loads(connection.execute(
            "SELECT suggestions_json FROM conversation_messages WHERE id = 'msg-1'"
        ).fetchone()[0])
        outlines = [entry for entry in stored_suggestions if entry.get("type") == "review_outline"]
        assert outlines and outlines[0]["artifact_id"] == by_kind["review_outline"][0]
        # 非学习产物原样留着，不会被删除
        assert any(entry.get("type") == "notebook_edit" for entry in stored_suggestions)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    _assert_notebook_intact(db_path)

    # 回滚到父版本：新表与新列必须干净移除，业务数据保留
    _migrate(tmp_path, "downgrade", PARENT_REVISION)

    with sqlite3.connect(db_path) as connection:
        tables = _tables(connection)
        for table in ("quizzes", "quiz_items", "quiz_attempts", "review_artifacts"):
            assert table not in tables
        message_columns = _columns(connection, "conversation_messages")
        assert "process_json" not in message_columns
        assert "suggestions_json" not in message_columns
        assert connection.execute("SELECT count(*) FROM conversation_messages").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM conversations").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM courses").fetchone() == (1,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    _assert_notebook_intact(db_path)

    # 回滚后可以再次升级（迁移可重复执行，不留半成品状态）
    _migrate(tmp_path, "upgrade", NEW_REVISION)
    with sqlite3.connect(db_path) as connection:
        assert "quizzes" in _tables(connection)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    _assert_notebook_intact(db_path)


def test_clean_upgrade_creates_no_phantom_artifacts_and_resumes_partial_state(tmp_path):
    """干净库升级不能凭空造出复习产物；只有部分表的半应用状态要能被续上。"""
    db_path = tmp_path / "notebook.sqlite3"

    _migrate(tmp_path, "upgrade", PARENT_REVISION)
    _seed(db_path)

    # 模拟上次迁移中途失败：只有 quizzes 建好了
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE quizzes (id VARCHAR(36) NOT NULL, course_id VARCHAR(36) NOT NULL, "
            "conversation_id VARCHAR(36), material_id VARCHAR(36), title VARCHAR(300) NOT NULL, "
            "status VARCHAR(30) NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (id))"
        )

    _migrate(tmp_path, "upgrade", NEW_REVISION)

    with sqlite3.connect(db_path) as connection:
        tables = _tables(connection)
        for table in ("quizzes", "quiz_items", "quiz_attempts", "review_artifacts"):
            assert table in tables
        # 半应用状态里表在、索引缺：续跑必须把索引补上，而不是只管建表
        assert "ix_quizzes_course_status" in _indexes(connection, "quizzes")
        # 干净升级：列刚建、全为 NULL，回填必须空转
        assert connection.execute("SELECT count(*) FROM review_artifacts").fetchone() == (0,)
        assert connection.execute(
            "SELECT suggestions_json FROM conversation_messages WHERE id = 'msg-1'"
        ).fetchone() == (None,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    _assert_notebook_intact(db_path)
