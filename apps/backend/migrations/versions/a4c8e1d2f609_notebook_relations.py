"""Add explicit links between independent notebooks."""

import sqlalchemy as sa
from alembic import op


revision = "a4c8e1d2f609"
down_revision = ("f82c4a1d9e60", "b29f17c5a640")
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notebook_relations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("source_notebook_id", sa.String(length=36), nullable=False),
        sa.Column("target_notebook_id", sa.String(length=36), nullable=False),
        sa.Column("relation_type", sa.String(length=40), nullable=False, server_default="related"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "source_notebook_id", "target_notebook_id", "relation_type",
            name="uq_notebook_relations_endpoints_type",
        ),
        sa.CheckConstraint(
            "source_notebook_id <> target_notebook_id", name="ck_notebook_relations_no_self_link",
        ),
    )
    op.create_index(
        "ix_notebook_relations_target", "notebook_relations", ["target_notebook_id"],
    )


def downgrade():
    op.drop_index("ix_notebook_relations_target", table_name="notebook_relations")
    op.drop_table("notebook_relations")
