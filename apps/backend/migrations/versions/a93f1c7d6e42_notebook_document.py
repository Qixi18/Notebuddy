"""Add an independently editable document to each notebook."""

import sqlalchemy as sa
from alembic import op

revision = "a93f1c7d6e42"
down_revision = "f82c4a1d9e60"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("notebooks", sa.Column("document_json", sa.Text(), server_default="[]", nullable=False))
    op.add_column("notebooks", sa.Column("document_revision", sa.Integer(), server_default="0", nullable=False))


def downgrade():
    op.drop_column("notebooks", "document_revision")
    op.drop_column("notebooks", "document_json")
