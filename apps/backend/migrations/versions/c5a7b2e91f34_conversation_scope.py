"""Persist conversation ownership: scope / note_id / note_title.

Scope vocabulary is unified to course / global / note. The legacy
material and page values both meant "整门课程", so they are folded into
course here instead of being carried forward as a third axis.
"""
import sqlalchemy as sa
from alembic import op

revision = "c5a7b2e91f34"
down_revision = "f82c4a1d9e60"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("conversations", sa.Column("scope", sa.String(20), nullable=True))
    op.add_column("conversations", sa.Column("note_id", sa.String(36), nullable=True))
    op.add_column("conversations", sa.Column("note_title", sa.String(300), nullable=True))
    # 存量会话：旧词 material / page 都归一到 course；scope 补齐为 course。
    op.execute("UPDATE conversations SET default_scope = 'course' WHERE default_scope IN ('material', 'page')")
    op.execute("UPDATE conversations SET scope = 'course' WHERE scope IS NULL")


def downgrade():
    with op.batch_alter_table("conversations") as batch:
        batch.drop_column("note_title")
        batch.drop_column("note_id")
        batch.drop_column("scope")
