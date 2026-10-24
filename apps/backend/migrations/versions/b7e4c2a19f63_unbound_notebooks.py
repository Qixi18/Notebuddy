"""Store blank notebooks before they are assigned to a course."""

import sqlalchemy as sa
from alembic import op

revision = "b7e4c2a19f63"
down_revision = "a93f1c7d6e42"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "unbound_notebooks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade():
    op.drop_table("unbound_notebooks")
