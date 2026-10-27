"""v6 §7 学习闭环：复习产物实体 + 题目用户状态 + 建议随消息持久化。

- review_artifacts：复习提纲 / 易混概念对比落库，复习面板跨会话可见、可收藏可删除；
- quiz_items：favorite / marked / dismissed（收藏、标记、移出复习）；
- conversation_messages.suggestions_json：技能卡负载随消息持久化，刷新后卡片还原。
"""

import sqlalchemy as sa
from alembic import op

revision = "e6a8b2c4d0f2"
down_revision = "b7f1c9d2e4a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "review_artifacts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("course_id", sa.String(length=36),
                  sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", sa.String(length=36),
                  sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("favorite", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_review_artifacts_course_kind", "review_artifacts", ["course_id", "kind"],
    )
    op.add_column("quiz_items", sa.Column("favorite", sa.Boolean(), server_default=sa.text("0"), nullable=False))
    op.add_column("quiz_items", sa.Column("marked", sa.Boolean(), server_default=sa.text("0"), nullable=False))
    op.add_column("quiz_items", sa.Column("dismissed", sa.Boolean(), server_default=sa.text("0"), nullable=False))
    op.add_column("conversation_messages", sa.Column("suggestions_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversation_messages", "suggestions_json")
    op.drop_column("quiz_items", "dismissed")
    op.drop_column("quiz_items", "marked")
    op.drop_column("quiz_items", "favorite")
    op.drop_index("ix_review_artifacts_course_kind", table_name="review_artifacts")
    op.drop_table("review_artifacts")
