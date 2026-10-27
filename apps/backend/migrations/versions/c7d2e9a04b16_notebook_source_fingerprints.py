"""Track the body version supported by each source relation.

Existing relations remain nullable until a known active body can be observed.
No historical evidence or body is rewritten or removed.
"""

import sqlalchemy as sa
from alembic import op

revision = "c7d2e9a04b16"
down_revision = "b3f1c7d92a10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notebook_block_sources", sa.Column("body_fingerprint", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("notebook_block_sources") as batch:
        batch.drop_column("body_fingerprint")
