"""persist complete Document IR citation locators"""

import sqlalchemy as sa
from alembic import op

revision = "a41d9c7e2b60"
down_revision = "d8e3f0b15c27"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "message_evidence",
        sa.Column("document_block_ids_json", sa.Text(), server_default="[]", nullable=False),
    )
    op.add_column(
        "message_evidence",
        sa.Column("page_numbers_json", sa.Text(), server_default="[]", nullable=False),
    )
    op.add_column(
        "message_evidence",
        sa.Column("notebook_revision", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("message_evidence", "notebook_revision")
    op.drop_column("message_evidence", "page_numbers_json")
    op.drop_column("message_evidence", "document_block_ids_json")
