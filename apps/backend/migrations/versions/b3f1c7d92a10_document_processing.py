"""Document Processing: parse runs, Document IR, provenance and derived indexes.

Structure-only migration.  Historical evidence is backfilled afterwards by
``python -m app.migration.document_backfill`` so a long data copy never runs
inside an Alembic transaction.
"""

import sqlalchemy as sa
from alembic import op

revision = "b3f1c7d92a10"
down_revision = "9a4b7c2d1e60"
branch_labels = None
depends_on = None

NEW_TABLES = (
    "document_parse_runs",
    "document_pages",
    "document_blocks",
    "document_sections",
    "document_chunks",
    "notebook_block_sources",
    "notebook_sections",
    "notebook_edit_suggestions",
)


def upgrade() -> None:
    op.create_table(
        "document_parse_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("doc_type", sa.String(20), server_default="unknown", nullable=False),
        sa.Column("ir_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("parser_name", sa.String(80), server_default="unknown", nullable=False),
        sa.Column("parser_version", sa.String(80), server_default="0", nullable=False),
        sa.Column("config_version", sa.String(80), server_default="v1", nullable=False),
        sa.Column("config_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("is_current", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("text_chars", sa.Integer(), server_default="0", nullable=False),
        sa.Column("quality_status", sa.String(20), server_default="failed", nullable=False),
        sa.Column("quality_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("markdown_text", sa.Text(), nullable=True),
        sa.Column("supersedes_id", sa.String(36), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('pending','running','completed','failed')",
            name="ck_document_parse_run_status",
        ),
    )
    op.create_index("ix_document_parse_runs_asset", "document_parse_runs", ["asset_id", "created_at"])
    op.create_index("ix_document_parse_runs_status", "document_parse_runs", ["status", "created_at"])
    op.create_index(
        "uq_document_parse_runs_current", "document_parse_runs", ["asset_id"],
        unique=True, sqlite_where=sa.text("is_current = 1"),
    )

    op.create_table(
        "document_pages",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("parse_run_id", sa.String(36), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("width", sa.Float(), nullable=True),
        sa.Column("height", sa.Float(), nullable=True),
        sa.Column("rotation", sa.Integer(), server_default="0", nullable=False),
        sa.Column("render_key", sa.String(500), nullable=True),
        sa.Column("extraction", sa.String(20), server_default="native_text", nullable=False),
        sa.Column("status", sa.String(20), server_default="parsed", nullable=False),
        sa.Column("text", sa.Text(), server_default="", nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("warnings_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["parse_run_id"], ["document_parse_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("parse_run_id", "page_number", name="uq_document_pages_run_number"),
    )
    op.create_index("ix_document_pages_run", "document_pages", ["parse_run_id", "page_number"])

    op.create_table(
        "document_blocks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("parse_run_id", sa.String(36), nullable=False),
        sa.Column("page_id", sa.String(36), nullable=False),
        sa.Column("block_id", sa.String(64), nullable=False),
        sa.Column("parent_block_id", sa.String(64), nullable=True),
        sa.Column("order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("global_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("block_type", sa.String(30), nullable=False),
        sa.Column("level", sa.Integer(), server_default="0", nullable=False),
        sa.Column("text", sa.Text(), server_default="", nullable=False),
        sa.Column("latex", sa.Text(), nullable=True),
        sa.Column("table_json", sa.Text(), nullable=True),
        sa.Column("figure_json", sa.Text(), nullable=True),
        sa.Column("bbox_json", sa.Text(), nullable=True),
        sa.Column("extraction", sa.String(20), server_default="native_text", nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("warnings_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["parse_run_id"], ["document_parse_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["page_id"], ["document_pages.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("parse_run_id", "block_id", name="uq_document_blocks_run_block"),
    )
    op.create_index("ix_document_blocks_run_order", "document_blocks", ["parse_run_id", "global_order"])
    op.create_index("ix_document_blocks_page_order", "document_blocks", ["page_id", "order"])

    op.create_table(
        "document_sections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("parse_run_id", sa.String(36), nullable=False),
        sa.Column("section_id", sa.String(64), nullable=False),
        sa.Column("order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("title", sa.String(500), server_default="", nullable=False),
        sa.Column("level", sa.Integer(), server_default="0", nullable=False),
        sa.Column("page_start", sa.Integer(), server_default="1", nullable=False),
        sa.Column("page_end", sa.Integer(), server_default="1", nullable=False),
        sa.Column("block_ids_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["parse_run_id"], ["document_parse_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("parse_run_id", "section_id", name="uq_document_sections_run_section"),
    )
    op.create_index("ix_document_sections_run_order", "document_sections", ["parse_run_id", "order"])

    op.create_table(
        "document_chunks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("parse_run_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("section_id", sa.String(64), nullable=True),
        sa.Column("order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page_numbers_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("block_ids_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("embedding_json", sa.Text(), nullable=True),
        sa.Column("embedding_model", sa.String(120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["parse_run_id"], ["document_parse_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_document_chunks_run_order", "document_chunks", ["parse_run_id", "order"])
    op.create_index("ix_document_chunks_asset", "document_chunks", ["asset_id"])

    op.create_table(
        "notebook_block_sources",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("notebook_id", sa.String(36), nullable=False),
        sa.Column("block_id", sa.String(64), nullable=False),
        sa.Column("generation_job_id", sa.String(36), nullable=True),
        sa.Column("parse_run_id", sa.String(36), nullable=False),
        sa.Column("document_block_id", sa.String(36), nullable=False),
        sa.Column("page_number", sa.Integer(), server_default="1", nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("status", sa.String(20), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "notebook_id", "block_id", "document_block_id",
            name="uq_notebook_block_source_edge",
        ),
    )
    op.create_index("ix_notebook_block_sources_block", "notebook_block_sources",
                    ["notebook_id", "block_id"])
    op.create_index("ix_notebook_block_sources_run", "notebook_block_sources", ["parse_run_id"])

    op.create_table(
        "notebook_sections",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("notebook_id", sa.String(36), nullable=False),
        sa.Column("course_id", sa.String(36), nullable=True),
        sa.Column("block_id", sa.String(64), nullable=False),
        sa.Column("order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("level", sa.Integer(), server_default="1", nullable=False),
        sa.Column("heading", sa.String(500), server_default="", nullable=False),
        sa.Column("text", sa.Text(), server_default="", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("notebook_id", "block_id", name="uq_notebook_sections_block"),
    )
    op.create_index("ix_notebook_sections_order", "notebook_sections", ["notebook_id", "order"])
    op.create_index("ix_notebook_sections_course", "notebook_sections", ["course_id"])

    op.create_table(
        "notebook_edit_suggestions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("notebook_id", sa.String(36), nullable=False),
        sa.Column("base_revision", sa.Integer(), nullable=False),
        sa.Column("rationale", sa.Text(), server_default="", nullable=False),
        sa.Column("ops_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("proposed_document_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_notebook_edit_suggestions_status", "notebook_edit_suggestions",
                    ["notebook_id", "status"])

    with op.batch_alter_table("message_evidence") as batch:
        batch.add_column(sa.Column("notebook_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("document_block_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("parse_run_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("body_block_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("source_title", sa.String(500), nullable=True))
        batch.add_column(sa.Column("location_label", sa.String(500), nullable=True))
        batch.add_column(sa.Column("snippet", sa.Text(), nullable=True))

    with op.batch_alter_table("notebook_document_revisions") as batch:
        batch.add_column(sa.Column("legacy_created_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("retention", sa.String(20), server_default="rolling", nullable=False))

    with op.batch_alter_table("notebook_generation_jobs") as batch:
        batch.add_column(sa.Column("parse_run_ids_json", sa.Text(), server_default="[]", nullable=False))
        batch.add_column(sa.Column("ir_fingerprints_json", sa.Text(), server_default="{}", nullable=False))
        batch.add_column(sa.Column("generator", sa.String(40), server_default="deepseek", nullable=False))
        batch.add_column(sa.Column("generator_version", sa.String(40), server_default="1", nullable=False))
        batch.add_column(sa.Column("knowledge_plan_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("source_map_json", sa.Text(), nullable=True))

    with op.batch_alter_table("notes") as batch:
        batch.add_column(sa.Column("migrated_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("migrated_revision", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("migration_batch", sa.String(36), nullable=True))
    op.create_index("ix_notes_migration_batch", "notes", ["migration_batch"])

    with op.batch_alter_table("notebook_reading_positions") as batch:
        batch.add_column(sa.Column("block_id", sa.String(64), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("notebook_reading_positions") as batch:
        batch.drop_column("block_id")
    op.drop_index("ix_notes_migration_batch", table_name="notes")
    with op.batch_alter_table("notes") as batch:
        batch.drop_column("migration_batch")
        batch.drop_column("migrated_revision")
        batch.drop_column("migrated_at")
    with op.batch_alter_table("notebook_generation_jobs") as batch:
        batch.drop_column("source_map_json")
        batch.drop_column("knowledge_plan_json")
        batch.drop_column("generator_version")
        batch.drop_column("generator")
        batch.drop_column("ir_fingerprints_json")
        batch.drop_column("parse_run_ids_json")
    with op.batch_alter_table("notebook_document_revisions") as batch:
        batch.drop_column("retention")
        batch.drop_column("legacy_created_at")
    with op.batch_alter_table("message_evidence") as batch:
        batch.drop_column("snippet")
        batch.drop_column("location_label")
        batch.drop_column("source_title")
        batch.drop_column("body_block_id")
        batch.drop_column("parse_run_id")
        batch.drop_column("document_block_id")
        batch.drop_column("notebook_id")
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
