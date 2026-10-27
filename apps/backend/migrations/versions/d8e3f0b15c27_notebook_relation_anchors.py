"""Optional body section anchors for Notebook relations; retain whole-book links."""

import sqlalchemy as sa
from alembic import op

revision = "d8e3f0b15c27"
down_revision = "c7d2e9a04b16"
branch_labels = None
depends_on = None

FIELDS = ("source_block_id", "target_block_id", "source_fingerprint", "target_fingerprint")


def upgrade() -> None:
    for field in FIELDS:
        op.add_column("notebook_relations", sa.Column(field, sa.String(64), nullable=True))
    op.add_column("notebook_relations", sa.Column("origin", sa.String(20), server_default="manual", nullable=False))
    with op.batch_alter_table("notebook_relations") as batch:
        batch.drop_constraint("uq_notebook_relations_endpoints_type", type_="unique")
    op.create_index(
        "uq_notebook_relations_endpoints_anchors", "notebook_relations",
        ["source_notebook_id", "target_notebook_id", "relation_type",
         sa.text("coalesce(source_block_id, '')"), sa.text("coalesce(target_block_id, '')")],
        unique=True,
    )


def downgrade() -> None:
    duplicates = op.get_bind().execute(sa.text(
        "SELECT 1 FROM notebook_relations GROUP BY source_notebook_id, target_notebook_id, "
        "relation_type HAVING count(*) > 1 LIMIT 1"
    )).first()
    if duplicates:
        raise RuntimeError("Cannot downgrade section relations without losing distinct links; export and reconcile them first")
    op.drop_index("uq_notebook_relations_endpoints_anchors", table_name="notebook_relations")
    with op.batch_alter_table("notebook_relations") as batch:
        batch.drop_column("origin")
        for field in reversed(FIELDS):
            batch.drop_column(field)
        batch.create_unique_constraint("uq_notebook_relations_endpoints_type",
                                       ["source_notebook_id", "target_notebook_id", "relation_type"])
