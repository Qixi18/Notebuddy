"""v6 §7 第二批：quiz_items.difficulty（难度分层，标签可由用户自定义）。"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "b7f1c9d2e4a6"
down_revision = "d3b4c6e8f0a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("quiz_items", sa.Column("difficulty", sa.String(length=30), nullable=True))


def downgrade() -> None:
    op.drop_column("quiz_items", "difficulty")
