"""Persistent notebook ownership, immutable tree slots and reading positions."""
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

revision = "e61a9b3c4d82"
down_revision = "d51e8f0a2b63"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("courses", sa.Column("last_opened_at", sa.DateTime(), nullable=True))
    op.create_table("notebooks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("course_id", sa.String(36), sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("order_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("tree_slot", sa.Integer(), nullable=False),
        sa.Column("next_note_slot", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("course_id", "tree_slot", name="uq_notebooks_course_slot"))
    op.create_index("uq_notebooks_default", "notebooks", ["course_id"], unique=True, sqlite_where=sa.text("is_default = 1"))
    for table in ("materials", "notes"):
        # SQLite supports a nullable REFERENCES column inline; avoid rebuilding
        # populated materials/notes and cascading away their evidence tables.
        op.execute(sa.text(f"ALTER TABLE {table} ADD COLUMN notebook_id VARCHAR(36) REFERENCES notebooks(id)"))
        op.create_index(f"ix_{table}_notebook_id", table, ["notebook_id"])
    op.add_column("notes", sa.Column("tree_slot", sa.Integer(), server_default="0", nullable=False))
    op.create_table("notebook_reading_positions",
        sa.Column("notebook_id", sa.String(36), sa.ForeignKey("notebooks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("chapter_id", sa.String(36), nullable=True),
        sa.Column("note_id", sa.String(36), nullable=True),
        sa.Column("mode", sa.String(10), nullable=False),
        sa.Column("section_offset", sa.Float(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False))
    db = op.get_bind()
    courses = db.execute(sa.text("""SELECT id,name,created_at,notebook_order_revision FROM courses
        WHERE EXISTS(SELECT 1 FROM materials WHERE course_id=courses.id)
           OR EXISTS(SELECT 1 FROM notes WHERE course_id=courses.id)""")).mappings().all()
    for course in courses:
        book_id = str(uuid4())
        db.execute(sa.text("""INSERT INTO notebooks
            (id,course_id,title,display_order,order_revision,is_default,tree_slot,created_at,updated_at)
            VALUES (:id,:course,:title,0,:revision,1,0,:created,:created)"""),
            dict(id=book_id, course=course["id"], title=f"{course['name']}·课程笔记",
                 revision=course["notebook_order_revision"], created=course["created_at"]))
        for table in ("materials", "notes"):
            db.execute(sa.text(f"UPDATE {table} SET notebook_id=:book WHERE course_id=:course"),
                       dict(book=book_id, course=course["id"]))
        notes = db.execute(sa.text("SELECT id FROM notes WHERE course_id=:course ORDER BY created_at,id"),
                           dict(course=course["id"])).scalars().all()
        for slot, note_id in enumerate(notes):
            db.execute(sa.text("UPDATE notes SET tree_slot=:slot WHERE id=:id"), dict(slot=slot, id=note_id))
        db.execute(sa.text("UPDATE notebooks SET next_note_slot=:count WHERE id=:id"), dict(count=len(notes), id=book_id))


def downgrade():
    op.drop_table("notebook_reading_positions")
    op.drop_column("notes", "tree_slot")
    for table in ("notes", "materials"):
        op.drop_index(f"ix_{table}_notebook_id", table_name=table)
        op.drop_column(table, "notebook_id")
    op.drop_table("notebooks")
    op.drop_column("courses", "last_opened_at")
