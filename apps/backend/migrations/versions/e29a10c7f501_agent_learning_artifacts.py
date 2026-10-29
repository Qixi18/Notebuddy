"""Persist agent quizzes, review artifacts and message process traces.

本迁移按「可重入」编写：先探测已有表/列，只创建缺失的部分。原因有两条，
都不是假设出来的：

1. Alembic 在同一事务里执行 DDL，中途失败只留下部分结构；重跑时必须能续上，
   而不是撞 ``duplicate column name`` / ``table already exists``。
2. ``_backfill_review_artifacts`` 只有在 ``suggestions_json`` 已经存在时才可能
   找到数据。对干净的 ``d9e4a7b21c60`` 库它是空转（列刚建、全为 NULL），这点
   必须写明白，不能让人误以为它在迁移旧数据；对已经带该列的历史库，它才真正
   把旧建议转成 ``review_artifacts``。按 id 存在性查重，因此可以安全重跑。
"""

from __future__ import annotations

import json

import sqlalchemy as sa
from alembic import op

revision = "e29a10c7f501"
down_revision = "d9e4a7b21c60"
branch_labels = None
depends_on = None


def _inspect_schema() -> tuple[set[str], set[str]]:
    """返回（已存在的表名集合, conversation_messages 已有的列名集合）。"""
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names()), {
        column["name"] for column in inspector.get_columns("conversation_messages")
    }


def _existing_indexes(table: str) -> set[str]:
    """表已存在时返回其索引名；表不存在返回空集（避免 inspector 对缺表抛错）。"""
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(table):
        return set()
    return {index["name"] for index in inspector.get_indexes(table)}


def upgrade() -> None:
    tables, message_columns = _inspect_schema()

    if "process_json" not in message_columns:
        op.add_column("conversation_messages", sa.Column("process_json", sa.Text(), nullable=True))
    if "suggestions_json" not in message_columns:
        op.add_column(
            "conversation_messages", sa.Column("suggestions_json", sa.Text(), nullable=True)
        )

    if "quizzes" not in tables:
        op.create_table(
            "quizzes",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("course_id", sa.String(36), nullable=False),
            sa.Column("conversation_id", sa.String(36), nullable=True),
            sa.Column("material_id", sa.String(36), nullable=True),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("status", sa.String(30), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["material_id"], ["materials.id"], ondelete="SET NULL"),
        )
    if "ix_quizzes_course_status" not in _existing_indexes("quizzes"):
        op.create_index("ix_quizzes_course_status", "quizzes", ["course_id", "status"])

    if "quiz_items" not in tables:
        op.create_table(
            "quiz_items",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("quiz_id", sa.String(36), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("item_type", sa.String(20), nullable=False),
            sa.Column("stem", sa.Text(), nullable=False),
            sa.Column("options_json", sa.Text(), nullable=False),
            sa.Column("answer", sa.Text(), nullable=False),
            sa.Column("explanation", sa.Text(), nullable=False),
            sa.Column("difficulty", sa.String(30), nullable=True),
            sa.Column("favorite", sa.Boolean(), server_default=sa.text("0"), nullable=False),
            sa.Column("marked", sa.Boolean(), server_default=sa.text("0"), nullable=False),
            sa.Column("dismissed", sa.Boolean(), server_default=sa.text("0"), nullable=False),
            sa.Column("knowledge_node_id", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["knowledge_node_id"], ["knowledge_nodes.id"], ondelete="SET NULL"
            ),
        )
    if "ix_quiz_items_quiz_seq" not in _existing_indexes("quiz_items"):
        op.create_index("ix_quiz_items_quiz_seq", "quiz_items", ["quiz_id", "seq"])

    if "quiz_attempts" not in tables:
        op.create_table(
            "quiz_attempts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("quiz_id", sa.String(36), nullable=False),
            sa.Column("item_id", sa.String(36), nullable=False),
            sa.Column("answer", sa.Text(), nullable=False),
            sa.Column("correct", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["quiz_id"], ["quizzes.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["item_id"], ["quiz_items.id"], ondelete="CASCADE"),
        )
    if "ix_quiz_attempts_item_created" not in _existing_indexes("quiz_attempts"):
        op.create_index(
            "ix_quiz_attempts_item_created", "quiz_attempts", ["item_id", "created_at"]
        )

    if "review_artifacts" not in tables:
        op.create_table(
            "review_artifacts",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("course_id", sa.String(36), nullable=False),
            sa.Column("conversation_id", sa.String(36), nullable=True),
            sa.Column("kind", sa.String(30), nullable=False),
            sa.Column("title", sa.String(300), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("favorite", sa.Boolean(), server_default=sa.text("0"), nullable=False),
            sa.Column("dismissed", sa.Boolean(), server_default=sa.text("0"), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(
                ["conversation_id"], ["conversations.id"], ondelete="SET NULL"
            ),
        )
    if "ix_review_artifacts_course_kind" not in _existing_indexes("review_artifacts"):
        op.create_index(
            "ix_review_artifacts_course_kind", "review_artifacts", ["course_id", "kind"]
        )

    _backfill_review_artifacts()


def downgrade() -> None:
    tables, message_columns = _inspect_schema()
    indexes = {
        table: _existing_indexes(table)
        for table in ("review_artifacts", "quiz_attempts", "quiz_items", "quizzes")
    }

    if "review_artifacts" in tables:
        if "ix_review_artifacts_course_kind" in indexes["review_artifacts"]:
            op.drop_index("ix_review_artifacts_course_kind", table_name="review_artifacts")
        op.drop_table("review_artifacts")
    if "quiz_attempts" in tables:
        if "ix_quiz_attempts_item_created" in indexes["quiz_attempts"]:
            op.drop_index("ix_quiz_attempts_item_created", table_name="quiz_attempts")
        op.drop_table("quiz_attempts")
    if "quiz_items" in tables:
        if "ix_quiz_items_quiz_seq" in indexes["quiz_items"]:
            op.drop_index("ix_quiz_items_quiz_seq", table_name="quiz_items")
        op.drop_table("quiz_items")
    if "quizzes" in tables:
        if "ix_quizzes_course_status" in indexes["quizzes"]:
            op.drop_index("ix_quizzes_course_status", table_name="quizzes")
        op.drop_table("quizzes")
    if "suggestions_json" in message_columns:
        op.drop_column("conversation_messages", "suggestions_json")
    if "process_json" in message_columns:
        op.drop_column("conversation_messages", "process_json")


def _backfill_review_artifacts() -> None:
    """把消息里已存的学习建议转成 review_artifacts，并把 artifact_id 写回建议。

    对干净升级（suggestions_json 刚建、全 NULL）这是空转；只有历史库已带该列时
    才会真正搬迁数据。按 id 查重，重复执行不会产生重复产物。
    """
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT m.id, m.conversation_id, c.course_id, m.suggestions_json "
        "FROM conversation_messages m JOIN conversations c ON c.id = m.conversation_id "
        "WHERE m.suggestions_json IS NOT NULL"
    )).fetchall()
    for message_id, conversation_id, course_id, raw in rows:
        try:
            suggestions = json.loads(raw)
        except (TypeError, ValueError):
            continue
        if not isinstance(suggestions, list):
            continue
        changed = False
        for suggestion in suggestions:
            if not isinstance(suggestion, dict):
                continue
            kind = suggestion.get("type")
            if kind not in ("review_outline", "concept_contrast"):
                continue
            artifact_id = str(suggestion.get("artifact_id") or suggestion.get("id") or "")
            if not artifact_id:
                artifact_id = f"bf-{str(message_id)[:8]}-{kind}"
            if kind == "review_outline":
                payload = {
                    "title": suggestion.get("title") or "",
                    "modules": suggestion.get("modules") or [],
                }
                title = str(payload["title"])[:300] or "复习提纲"
            else:
                payload = {"pairs": suggestion.get("pairs") or []}
                title = "、".join(
                    f"「{pair.get('a')} vs {pair.get('b')}」"
                    for pair in payload["pairs"] if isinstance(pair, dict)
                )[:300] or "易混概念对比"
            exists = bind.execute(
                sa.text("SELECT id FROM review_artifacts WHERE id = :id"), {"id": artifact_id},
            ).fetchone()
            if not exists:
                bind.execute(sa.text(
                    "INSERT INTO review_artifacts "
                    "(id, course_id, conversation_id, kind, title, payload_json, favorite, "
                    "dismissed, created_at) "
                    "VALUES (:id, :course_id, :conversation_id, :kind, :title, :payload_json, "
                    ":favorite, 0, CURRENT_TIMESTAMP)"
                ), {
                    "id": artifact_id, "course_id": course_id,
                    "conversation_id": conversation_id,
                    "kind": kind, "title": title,
                    "payload_json": json.dumps(payload, ensure_ascii=False),
                    "favorite": bool(suggestion.get("favorite")),
                })
            suggestion["artifact_id"] = artifact_id
            changed = True
        if changed:
            bind.execute(sa.text(
                "UPDATE conversation_messages SET suggestions_json = :raw WHERE id = :id"
            ), {"raw": json.dumps(suggestions, ensure_ascii=False), "id": message_id})
