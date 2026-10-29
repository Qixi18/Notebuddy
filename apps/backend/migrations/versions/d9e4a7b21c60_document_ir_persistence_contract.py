"""Persist canonical DocumentIR metadata without duplicating the IR payload.

Revision ID: d9e4a7b21c60
Revises: a41d9c7e2b60
Create Date: 2026-10-29
"""

from alembic import op
import sqlalchemy as sa

revision = "d9e4a7b21c60"
down_revision = "a41d9c7e2b60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("document_parse_runs") as batch:
        batch.add_column(sa.Column(
            "document_warnings_json", sa.Text(), nullable=False,
            server_default=sa.text("'[]'"),
        ))
    with op.batch_alter_table("document_pages") as batch:
        batch.add_column(sa.Column("logical_page_id", sa.Text(), nullable=True))
    with op.batch_alter_table("document_blocks") as batch:
        batch.add_column(sa.Column("source_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("document_blocks") as batch:
        batch.drop_column("source_json")
    with op.batch_alter_table("document_pages") as batch:
        batch.drop_column("logical_page_id")
    with op.batch_alter_table("document_parse_runs") as batch:
        batch.drop_column("document_warnings_json")
