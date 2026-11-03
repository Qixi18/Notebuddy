"""Allow conversations to belong to one Notebook without a course.

Revision ID: f2b7d9a1406c
Revises: f1a7c9d3e620
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "f2b7d9a1406c"
down_revision = "f1a7c9d3e620"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("conversations") as batch:
        batch.alter_column(
            "course_id", existing_type=sa.String(length=36), nullable=True,
        )
        batch.add_column(sa.Column("notebook_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_conversations_notebook_id_notebooks",
            "notebooks", ["notebook_id"], ["id"], ondelete="SET NULL",
        )
        batch.create_check_constraint(
            "ck_conversations_notebook_scope_no_course",
            "scope != 'notebook' OR course_id IS NULL",
        )
    op.create_index("ix_conversations_notebook_id", "conversations", ["notebook_id"])


def downgrade() -> None:
    bind = op.get_bind()
    count = bind.execute(sa.text(
        "SELECT COUNT(*) FROM conversations WHERE scope = 'notebook'"
    )).scalar_one()
    if count:
        raise RuntimeError(
            "Cannot downgrade: Notebook-scoped conversations exist; export or remove them first."
        )
    op.drop_index("ix_conversations_notebook_id", table_name="conversations")
    with op.batch_alter_table("conversations") as batch:
        batch.drop_constraint("ck_conversations_notebook_scope_no_course", type_="check")
        batch.drop_constraint("fk_conversations_notebook_id_notebooks", type_="foreignkey")
        batch.drop_column("notebook_id")
        batch.alter_column(
            "course_id", existing_type=sa.String(length=36), nullable=False,
        )
