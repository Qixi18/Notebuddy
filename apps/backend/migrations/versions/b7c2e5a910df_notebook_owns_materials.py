"""Preserve legacy course-only materials during Notebook ownership rollout.

This revision intentionally does not assign unowned course materials to an
arbitrary Notebook and does not drop legacy course scope from Materials or
NotebookAttachments. New writes derive course context from Notebook; old
attachment course IDs remain until an explicit data audit approves removal.
"""

import sqlalchemy as sa
from alembic import op

revision = "b7c2e5a910df"
down_revision = "a4c8e1d2f609"
branch_labels = None
depends_on = None


def upgrade():
    # materials.course_id remains nullable compatibility metadata for legacy
    # course-only rows. New uploads keep it NULL and bind only notebook_id.
    # SET NULL prevents deleting a course from deleting files owned by a Notebook.
    with op.batch_alter_table(
        "materials",
        naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
    ) as batch:
        batch.drop_constraint("fk_materials_course_id_courses", type_="foreignkey")
        batch.create_foreign_key(
            "fk_materials_course_id_courses", "courses", ["course_id"], ["id"],
            ondelete="SET NULL",
        )
        batch.alter_column(
            "course_id", existing_type=sa.String(length=36), nullable=True,
        )
    # Keep notebook_attachments.course_id as nullable legacy metadata. Its
    # mapping to Notebook.course_id has not been proven for every old row.


def downgrade():
    connection = op.get_bind()
    unbound_rows = connection.scalar(
        sa.text("SELECT COUNT(*) FROM materials WHERE course_id IS NULL")
    )
    if unbound_rows:
        raise RuntimeError(
            "Cannot downgrade b7c2e5a910df: Materials with NULL course_id cannot satisfy the old schema. "
            "Restore a matching database backup or explicitly map those rows before downgrade."
        )
    with op.batch_alter_table(
        "materials",
        naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
    ) as batch:
        batch.drop_constraint("fk_materials_course_id_courses", type_="foreignkey")
        batch.create_foreign_key(
            "fk_materials_course_id_courses", "courses", ["course_id"], ["id"],
            ondelete="CASCADE",
        )
        batch.alter_column(
            "course_id", existing_type=sa.String(length=36), nullable=False,
        )
