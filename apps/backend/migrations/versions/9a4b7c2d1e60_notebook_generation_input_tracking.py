"""Persist upload batches and per-Asset automatic generation state."""

from alembic import op
import sqlalchemy as sa

revision = "9a4b7c2d1e60"
down_revision = "c8f4a2d91b70"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "notebook_upload_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("notebook_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_notebook_upload_batches_notebook", "notebook_upload_batches",
        ["notebook_id", "created_at"],
    )
    with op.batch_alter_table("assets") as batch:
        batch.add_column(sa.Column("upload_batch_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_assets_upload_batch_id_notebook_upload_batches",
            "notebook_upload_batches", ["upload_batch_id"], ["id"], ondelete="SET NULL",
        )

    op.create_table(
        "notebook_generation_inputs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("notebook_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("batch_id", sa.String(36), nullable=False),
        sa.Column("parse_kind", sa.String(20), nullable=False),
        sa.Column("parse_job_id", sa.String(36), nullable=True),
        sa.Column("parse_result_fingerprint", sa.String(64), nullable=True),
        sa.Column("generation_job_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(24), server_default="waiting_parse", nullable=False),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('waiting_parse','parsing','parse_failed','ready','generating',"
            "'generation_failed','completed')",
            name="ck_notebook_generation_input_status",
        ),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["batch_id"], ["notebook_upload_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["generation_job_id"], ["notebook_generation_jobs.id"], ondelete="SET NULL",
        ),
        sa.UniqueConstraint("asset_id", name="uq_notebook_generation_input_asset"),
    )
    op.create_index(
        "ix_notebook_generation_inputs_batch_state", "notebook_generation_inputs",
        ["batch_id", "status", "created_at"],
    )
    op.create_index(
        "ix_notebook_generation_inputs_status", "notebook_generation_inputs",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_notebook_generation_inputs_status", table_name="notebook_generation_inputs")
    op.drop_index("ix_notebook_generation_inputs_batch_state", table_name="notebook_generation_inputs")
    op.drop_table("notebook_generation_inputs")
    with op.batch_alter_table("assets") as batch:
        batch.drop_constraint("fk_assets_upload_batch_id_notebook_upload_batches", type_="foreignkey")
        batch.drop_column("upload_batch_id")
    op.drop_index("ix_notebook_upload_batches_notebook", table_name="notebook_upload_batches")
    op.drop_table("notebook_upload_batches")
