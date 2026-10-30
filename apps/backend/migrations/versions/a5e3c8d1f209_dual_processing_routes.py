"""Preserve processing routes and resumable model results."""
from alembic import op
import sqlalchemy as sa

revision = "a5e3c8d1f209"
down_revision = "d9e4a7b21c60"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('notebook_relation_suppressions',
        sa.Column('pair_key', sa.String(64), primary_key=True),
        sa.Column('left_notebook_id', sa.String(36), sa.ForeignKey('notebooks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('right_notebook_id', sa.String(36), sa.ForeignKey('notebooks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('anchors_json', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False))
    op.add_column('notebook_generation_jobs', sa.Column('relation_job_id', sa.String(36), nullable=True))
    for table in ('processing_jobs', 'asset_processing_jobs'):
        for column in ('completed_pages', 'total_pages'):
            op.add_column(table, sa.Column(column, sa.Integer(), nullable=False, server_default='0'))
    op.add_column('asset_processing_jobs', sa.Column('phase', sa.String(30), nullable=False, server_default='parse'))
    for table in ("assets", "materials", "notebook_upload_batches"):
        op.add_column(table, sa.Column("processing_route", sa.String(20),
                                     nullable=False, server_default="standard"))
    op.add_column("assets", sa.Column("processing_config_json", sa.Text(),
                                    nullable=False, server_default="{}"))
    op.create_table("processing_steps",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("scope", sa.String(100), nullable=False),
        sa.Column("stage", sa.String(40), nullable=False),
        sa.Column("step_key", sa.String(100), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=False),
        sa.Column("usage_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("scope", "stage", "step_key", "fingerprint",
                            name="uq_processing_steps_identity"))
    op.create_index("ix_processing_steps_scope", "processing_steps", ["scope"])


def downgrade():
    op.drop_column('notebook_generation_jobs', 'relation_job_id')
    op.drop_table('notebook_relation_suppressions')
    op.drop_column('asset_processing_jobs', 'phase')
    for table in ('asset_processing_jobs', 'processing_jobs'):
        for column in ('total_pages', 'completed_pages'):
            op.drop_column(table, column)
    op.drop_table("processing_steps")
    op.drop_column("assets", "processing_config_json")
    for table in ("notebook_upload_batches", "materials", "assets"):
        op.drop_column(table, "processing_route")
