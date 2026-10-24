"""Add notebook covers and reversible notebook deletion."""

import sqlalchemy as sa
from alembic import op

revision = "a14c6e82d903"
down_revision = "f82c4a1d9e60"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("notebooks", sa.Column("cover_filename", sa.String(255), nullable=True))
    op.add_column("notebooks", sa.Column("cover_mime", sa.String(120), nullable=True))
    op.add_column("notebooks", sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("notebooks", "deleted_at")
    op.drop_column("notebooks", "cover_mime")
    op.drop_column("notebooks", "cover_filename")
