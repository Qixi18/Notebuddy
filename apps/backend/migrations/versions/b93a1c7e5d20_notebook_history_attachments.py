"""Add notebook document history snapshots and notebook attachments."""

import sqlalchemy as sa
from alembic import op

revision = "b93a1c7e5d20"
down_revision = "d0a6f3c9b812"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notebook_document_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("notebook_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="2", nullable=False),
        sa.Column("document_json", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(length=20), server_default="autosave", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("notebook_id", "revision", name="uq_notebook_document_revisions"),
    )
    op.create_index(
        "ix_notebook_document_revisions_notebook",
        "notebook_document_revisions",
        ["notebook_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "notebook_attachments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("notebook_id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.String(length=36), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("mime", sa.String(length=120), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notebook_attachments_notebook",
        "notebook_attachments",
        ["notebook_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_notebook_attachments_notebook", table_name="notebook_attachments")
    op.drop_table("notebook_attachments")
    op.drop_index("ix_notebook_document_revisions_notebook", table_name="notebook_document_revisions")
    op.drop_table("notebook_document_revisions")
