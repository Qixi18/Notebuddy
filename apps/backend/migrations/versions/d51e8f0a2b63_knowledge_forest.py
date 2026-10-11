"""Forest course profiles, curriculum imports and reviewed cross-course relations."""

import sqlalchemy as sa
from alembic import op

revision = "d51e8f0a2b63"
down_revision = "a81c6e204f35"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "forest_course_profiles",
        sa.Column(
            "course_id",
            sa.String(36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("semester", sa.Integer(), nullable=True),
        sa.Column("level", sa.String(30), server_default="unspecified", nullable=False),
        sa.Column("learning_state", sa.String(30), server_default="planned", nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("prerequisites_json", sa.Text(), server_default="[]", nullable=False),
    )
    op.create_table(
        "curriculum_imports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("filename", sa.String(255), nullable=True),
        sa.Column("stored_filename", sa.String(255), nullable=True),
        sa.Column("input_text", sa.Text(), server_default="", nullable=False),
        sa.Column("status", sa.String(30), server_default="pending", nullable=False),
        sa.Column("mode", sa.String(40), nullable=True),
        sa.Column("warnings_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("rows_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
    )
    op.create_table(
        "forest_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(50), nullable=False),
        sa.Column(
            "course_id",
            sa.String(36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "curriculum_import_id",
            sa.String(36),
            sa.ForeignKey("curriculum_imports.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("status", sa.String(30), server_default="pending", nullable=False),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("idempotency_key", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_forest_jobs_status", "forest_jobs", ["status", "created_at"])
    op.create_index(
        "uq_forest_jobs_idempotency_key", "forest_jobs", ["idempotency_key"], unique=True
    )
    op.create_table(
        "cross_course_relations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_course_id",
            sa.String(36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_course_id",
            sa.String(36),
            sa.ForeignKey("courses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_note_id",
            sa.String(36),
            sa.ForeignKey("notes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_note_id",
            sa.String(36),
            sa.ForeignKey("notes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_revision", sa.Integer(), nullable=False),
        sa.Column("target_revision", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), server_default="pending", nullable=False),
        sa.Column("origin", sa.String(30), server_default="ai", nullable=False),
        sa.Column("source_ref_ids_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("target_ref_ids_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "source_note_id",
            "target_note_id",
            "relation_type",
            name="uq_cross_course_relations_endpoints_type",
        ),
    )
    op.create_index("ix_cross_course_relations_status", "cross_course_relations", ["status"])


def downgrade():
    for table in (
        "cross_course_relations",
        "forest_jobs",
        "curriculum_imports",
        "forest_course_profiles",
    ):
        op.drop_table(table)
