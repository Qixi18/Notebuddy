"""Persist automatic relation provenance and bounded resumable source jobs."""
from datetime import datetime, UTC
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "f82c4a1d9e60"
down_revision = "e61a9b3c4d82"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("cross_course_relations", sa.Column("activation_mode", sa.String(20), nullable=True))
    op.add_column("cross_course_relations", sa.Column("evidence_fingerprint", sa.String(64), nullable=True))
    op.add_column("forest_jobs", sa.Column("source_snapshot_json", sa.Text(), server_default="[]", nullable=False))
    op.add_column("forest_jobs", sa.Column("completed_source_count", sa.Integer(), server_default="0", nullable=False))
    # Every old confirmed transition required an explicit human action, even origin=ai.
    op.execute("UPDATE cross_course_relations SET activation_mode='manual' WHERE status='confirmed'")
    db = op.get_bind()
    for course_id in db.execute(sa.text("SELECT DISTINCT source_course_id FROM cross_course_relations WHERE (status='pending' AND origin='ai') OR status='confirmed'")).scalars():
        now = datetime.now(UTC)
        db.execute(sa.text("""INSERT INTO forest_jobs
            (id,kind,course_id,status,progress,attempt_count,idempotency_key,created_at,updated_at)
            VALUES (:id,'validate_legacy_relations',:course,'pending',0,0,:key,:now,:now)"""),
            {"id": str(uuid4()), "course": course_id, "key": "validate-legacy:" + course_id, "now": now})


def downgrade():
    op.execute("DELETE FROM forest_jobs WHERE kind='validate_legacy_relations'")
    for column in ("completed_source_count", "source_snapshot_json"):
        op.drop_column("forest_jobs", column)
    for column in ("evidence_fingerprint", "activation_mode"):
        op.drop_column("cross_course_relations", column)
