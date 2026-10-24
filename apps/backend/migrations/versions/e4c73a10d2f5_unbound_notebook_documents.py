"""Keep editable content in notebooks before they are bound to a course."""

import sqlalchemy as sa
from alembic import op

revision = "e4c73a10d2f5"
down_revision = "b93a1c7e5d20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("unbound_notebooks", sa.Column("document_json", sa.Text(), nullable=False, server_default="[]"))
    op.add_column("unbound_notebooks", sa.Column("document_revision", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("unbound_notebooks", "document_revision")
    op.drop_column("unbound_notebooks", "document_json")
