"""Course notebooks with independent lecture sections."""
import sqlalchemy as sa
from alembic import op

revision = "a81c6e204f35"
down_revision = "f7b9c2d6e401"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("courses", sa.Column("notebook_order_revision", sa.Integer(), server_default="0", nullable=False))
    op.add_column("materials", sa.Column("chapter_order", sa.Integer(), server_default="0", nullable=False))
    with op.batch_alter_table("notes", naming_convention={"uq": "uq_%(table_name)s_%(column_0_name)s"}) as batch:
        batch.drop_constraint("uq_notes_knowledge_node_id", type_="unique")
        batch.add_column(sa.Column("material_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("section_key", sa.String(300), nullable=True))
        batch.add_column(sa.Column("section_order", sa.Integer(), server_default="0", nullable=False))
        batch.create_foreign_key("fk_notes_material", "materials", ["material_id"], ["id"], ondelete="SET NULL")
        batch.create_unique_constraint("uq_notes_material_section", ["material_id", "section_key"])
    bind = op.get_bind()
    courses = bind.execute(sa.text("SELECT id FROM courses")).scalars().all()
    for course_id in courses:
        ids = bind.execute(sa.text("SELECT id FROM materials WHERE course_id=:c ORDER BY created_at,id"), {"c": course_id}).scalars().all()
        for position, material_id in enumerate(ids):
            bind.execute(sa.text("UPDATE materials SET chapter_order=:p WHERE id=:m"), {"p": position, "m": material_id})
    notes = bind.execute(sa.text("SELECT id,course_id FROM notes")).all()
    for note_id, course_id in notes:
        locations = bind.execute(sa.text("""
            SELECT m.id, MIN(p.page_number) FROM note_source_refs ns
            JOIN source_refs s ON s.id=ns.source_ref_id
            JOIN page_blocks b ON b.id=s.page_block_id
            JOIN material_pages p ON p.id=b.page_id
            JOIN materials m ON m.id=p.material_id
            WHERE ns.note_id=:n AND m.course_id=:c GROUP BY m.id
        """), {"n": note_id, "c": course_id}).all()
        if len(locations) == 1:
            material_id, position = locations[0]
            bind.execute(sa.text("UPDATE notes SET material_id=:m,section_key=:k,section_order=:p WHERE id=:n"),
                         {"m": material_id, "k": f"legacy:{note_id}", "p": position, "n": note_id})


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT knowledge_node_id FROM notes GROUP BY knowledge_node_id HAVING count(*)>1 LIMIT 1")).first():
        raise RuntimeError("Multiple lecture notes cannot be downgraded safely; restore a checkpoint")
    with op.batch_alter_table("notes") as batch:
        batch.drop_constraint("uq_notes_material_section", type_="unique")
        batch.drop_constraint("fk_notes_material", type_="foreignkey")
        batch.drop_column("material_id")
        batch.drop_column("section_key")
        batch.drop_column("section_order")
        batch.create_unique_constraint("uq_notes_knowledge_node_id", ["knowledge_node_id"])
    op.drop_column("materials", "chapter_order")
    op.drop_column("courses", "notebook_order_revision")
