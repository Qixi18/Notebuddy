"""Add per-Asset CNY processing budgets and usage reservations."""
from alembic import op
import sqlalchemy as sa


revision = "b6e1a9d420fc"
down_revision = "a7c4d2e91b60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "file_processing_budgets",
        sa.Column("asset_id", sa.String(length=36), primary_key=True),
        sa.Column("notebook_id", sa.String(length=36), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="CNY", nullable=False),
        sa.Column("limit_fen", sa.Integer(), server_default="1000", nullable=False),
        sa.Column("settled_fen", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reserved_fen", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("currency = 'CNY'", name="ck_file_budget_currency"),
        sa.CheckConstraint("limit_fen >= 0 AND settled_fen >= 0 AND reserved_fen >= 0",
                           name="ck_file_budget_amounts_nonnegative"),
        sa.CheckConstraint("status IN ('active','exhausted','uncertain','overrun','closed')",
                           name="ck_file_budget_status"),
    )
    op.create_index("ix_file_processing_budgets_notebook", "file_processing_budgets",
                    ["notebook_id", "status"])
    op.create_table(
        "provider_usage_reservations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("call_id", sa.String(length=36), nullable=False),
        sa.Column("asset_id", sa.String(length=36), nullable=False),
        sa.Column("notebook_id", sa.String(length=36), nullable=True),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=True),
        sa.Column("step_key", sa.String(length=200), nullable=True),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("tariff_version", sa.String(length=120), nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="CNY", nullable=False),
        sa.Column("fx_snapshot_json", sa.Text(), nullable=False),
        sa.Column("pricing_snapshot_json", sa.Text(), nullable=False),
        sa.Column("reserved_fen", sa.Integer(), nullable=False),
        sa.Column("charged_fen", sa.Integer(), nullable=True),
        sa.Column("provider_usage_json", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=20), server_default="reserved", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("settled_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("call_id", "asset_id", name="uq_provider_usage_call_asset"),
        sa.CheckConstraint("currency = 'CNY'", name="ck_provider_usage_currency"),
        sa.CheckConstraint("reserved_fen >= 0 AND (charged_fen IS NULL OR charged_fen >= 0)",
                           name="ck_provider_usage_amounts_nonnegative"),
        sa.CheckConstraint("state IN ('reserved','settled','uncertain','overrun')",
                           name="ck_provider_usage_state"),
    )
    op.create_index("ix_provider_usage_asset_created", "provider_usage_reservations",
                    ["asset_id", "created_at"])
    op.create_index("ix_provider_usage_job", "provider_usage_reservations", ["job_id", "stage"])


def downgrade() -> None:
    bind = op.get_bind()
    live = bind.execute(sa.text(
        "SELECT 1 FROM provider_usage_reservations WHERE state IN ('reserved','uncertain') LIMIT 1"
    )).first()
    if live:
        raise RuntimeError("Cannot downgrade while budget reservations remain unresolved")
    op.drop_index("ix_provider_usage_job", table_name="provider_usage_reservations")
    op.drop_index("ix_provider_usage_asset_created", table_name="provider_usage_reservations")
    op.drop_table("provider_usage_reservations")
    op.drop_index("ix_file_processing_budgets_notebook", table_name="file_processing_budgets")
    op.drop_table("file_processing_budgets")
