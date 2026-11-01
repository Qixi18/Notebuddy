"""Allow verified web evidence to belong to unbound Notebooks."""
import sqlalchemy as sa
from alembic import op

revision = "a7c4d2e91b60"
down_revision = "f2b7d9a1406c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("web_sources") as batch:
        batch.alter_column("course_id", existing_type=sa.String(length=36), nullable=True)
        batch.add_column(sa.Column("notebook_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key("fk_web_sources_notebook_id_notebooks", "notebooks", ["notebook_id"], ["id"], ondelete="CASCADE")
        batch.create_index("ix_web_sources_notebook_id", ["notebook_id"])


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM web_sources WHERE notebook_id IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade while Notebook-scoped web evidence exists")
    with op.batch_alter_table("web_sources") as batch:
        batch.drop_index("ix_web_sources_notebook_id")
        batch.drop_constraint("fk_web_sources_notebook_id_notebooks", type_="foreignkey")
        batch.drop_column("notebook_id")
        batch.alter_column("course_id", existing_type=sa.String(length=36), nullable=False)
