"""v6 §7 学习闭环：复习产物改软移除 + 回填历史建议为产物实体。

- review_artifacts.dismissed：面板「移出复习」不再硬删，会话卡片保留、可恢复；
- 回填：把历史消息 suggestions_json 里没有 artifact_id 的提纲/对比建议补建成
  review_artifacts 行并写回 artifact_id——旧会话的技能卡从此可收藏/移出/恢复。
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "e7c4d8f2a6b0"
down_revision = "e6a8b2c4d0f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("review_artifacts", sa.Column("dismissed", sa.Boolean(), server_default=sa.text("0"), nullable=False))
    _backfill_from_messages()


def downgrade() -> None:
    op.drop_column("review_artifacts", "dismissed")


def _backfill_from_messages() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            "SELECT m.id, m.conversation_id, c.course_id, m.suggestions_json "
            "FROM conversation_messages m JOIN conversations c ON c.id = m.conversation_id "
            "WHERE m.suggestions_json IS NOT NULL"
        )
    ).fetchall()
    for message_id, conversation_id, course_id, raw in rows:
        try:
            suggestions = json.loads(raw)
        except ValueError:
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
            if kind == "review_outline":
                payload = {"title": suggestion.get("title") or "", "modules": suggestion.get("modules") or []}
                title = str(payload["title"])[:300] or "复习提纲"
            else:
                pairs = suggestion.get("pairs") or []
                payload = {"pairs": pairs}
                title = "、".join(f"「{pair.get('a')} vs {pair.get('b')}」" for pair in pairs)[:300] or "易混概念对比"

            artifact_id = str(suggestion.get("id") or "")
            if not artifact_id:
                artifact_id = f"bf-{str(message_id)[:8]}-{kind}"
            # 幂等：同 id 已有实体就只补写引用，不重复建行
            # 引用存在但实体缺失（如曾硬删）→ 也重建，保证卡片操作不落空
            existing = bind.execute(
                sa.text("SELECT id FROM review_artifacts WHERE id = :id"), {"id": artifact_id},
            ).fetchone()
            if not existing:
                bind.execute(
                    sa.text(
                        "INSERT INTO review_artifacts "
                        "(id, course_id, conversation_id, kind, title, payload_json, favorite, dismissed, created_at) "
                        "VALUES (:id, :course_id, :conversation_id, :kind, :title, :payload_json, :favorite, 0, CURRENT_TIMESTAMP)"
                    ),
                    {
                        "id": artifact_id,
                        "course_id": course_id,
                        "conversation_id": conversation_id,
                        "kind": kind,
                        "title": title,
                        "payload_json": json.dumps(payload, ensure_ascii=False),
                        "favorite": bool(suggestion.get("favorite")),
                    },
                )
            suggestion["artifact_id"] = artifact_id
            changed = True
        if changed:
            bind.execute(
                sa.text("UPDATE conversation_messages SET suggestions_json = :raw WHERE id = :id"),
                {"raw": json.dumps(suggestions, ensure_ascii=False), "id": message_id},
            )
