"""Add agent process trace column to conversation messages."""

import sqlalchemy as sa
from alembic import op

revision = "d3b4c6e8f0a2"
down_revision = "c9d2e4f6a8b0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("conversation_messages", sa.Column("process_json", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("conversation_messages", "process_json")
