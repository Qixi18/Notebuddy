"""Make every note a notebook; a course is an optional folder."""

from alembic import op
import sqlalchemy as sa

revision = "f7a5c2d901be"
down_revision = "e4c73a10d2f5"
branch_labels = None
depends_on = None


def _rebuild_notebooks(*, ondelete: str) -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("""
        CREATE TABLE notebooks_new (
            id VARCHAR(36) NOT NULL PRIMARY KEY,
            course_id VARCHAR(36),
            title VARCHAR(200) NOT NULL,
            display_order INTEGER NOT NULL DEFAULT 0,
            order_revision INTEGER NOT NULL DEFAULT 0,
            document_json TEXT NOT NULL DEFAULT '[]',
            document_revision INTEGER NOT NULL DEFAULT 0,
            is_default BOOLEAN NOT NULL DEFAULT 0,
            tree_slot INTEGER NOT NULL,
            next_note_slot INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL,
            CONSTRAINT uq_notebooks_course_slot UNIQUE (course_id, tree_slot),
            FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE %s
        )
    """ % ondelete)
    connection.exec_driver_sql("""
        INSERT INTO notebooks_new
        (id, course_id, title, display_order, order_revision, document_json,
         document_revision, is_default, tree_slot, next_note_slot, created_at, updated_at)
        SELECT id, course_id, title, display_order, order_revision, document_json,
               document_revision, is_default, tree_slot, next_note_slot, created_at, updated_at
        FROM notebooks
    """)
    connection.exec_driver_sql("DROP TABLE notebooks")
    connection.exec_driver_sql("ALTER TABLE notebooks_new RENAME TO notebooks")
    connection.exec_driver_sql(
        "CREATE UNIQUE INDEX uq_notebooks_default ON notebooks(course_id) WHERE is_default = 1"
    )


def _rebuild_attachments(*, nullable: bool, ondelete: str) -> None:
    connection = op.get_bind()
    course_null = "" if nullable else " NOT NULL"
    connection.exec_driver_sql(f"""
        CREATE TABLE notebook_attachments_new (
            id VARCHAR(36) NOT NULL PRIMARY KEY,
            notebook_id VARCHAR(36) NOT NULL,
            course_id VARCHAR(36){course_null},
            original_filename VARCHAR(255) NOT NULL,
            stored_filename VARCHAR(255) NOT NULL,
            mime VARCHAR(120) NOT NULL,
            size_bytes INTEGER NOT NULL,
            created_at DATETIME NOT NULL,
            FOREIGN KEY(notebook_id) REFERENCES notebooks(id) ON DELETE CASCADE,
            FOREIGN KEY(course_id) REFERENCES courses(id) ON DELETE {ondelete}
        )
    """)
    connection.exec_driver_sql("""
        INSERT INTO notebook_attachments_new
        (id, notebook_id, course_id, original_filename, stored_filename, mime, size_bytes, created_at)
        SELECT id, notebook_id, course_id, original_filename, stored_filename, mime, size_bytes, created_at
        FROM notebook_attachments
    """)
    connection.exec_driver_sql("DROP TABLE notebook_attachments")
    connection.exec_driver_sql("ALTER TABLE notebook_attachments_new RENAME TO notebook_attachments")
    connection.exec_driver_sql(
        "CREATE INDEX ix_notebook_attachments_notebook ON notebook_attachments(notebook_id)"
    )


def upgrade() -> None:
    connection = op.get_bind()
    connection.exec_driver_sql("""
        INSERT INTO notebooks
        (id, course_id, title, display_order, order_revision, document_json,
         document_revision, is_default, tree_slot, next_note_slot, created_at, updated_at)
        SELECT id, NULL, title, 0, 0, document_json, document_revision,
               0, 0, 0, created_at, updated_at
        FROM unbound_notebooks
    """)
    connection.exec_driver_sql("DROP TABLE unbound_notebooks")
    _rebuild_notebooks(ondelete="SET NULL")
    _rebuild_attachments(nullable=True, ondelete="SET NULL")


def downgrade() -> None:
    connection = op.get_bind()
    has_history = connection.scalar(sa.text("""
        SELECT EXISTS(SELECT 1 FROM notebook_document_revisions r JOIN notebooks n
                      ON r.notebook_id=n.id WHERE n.course_id IS NULL)
    """))
    has_attachments = connection.scalar(sa.text("""
        SELECT EXISTS(SELECT 1 FROM notebook_attachments a JOIN notebooks n
                      ON a.notebook_id=n.id WHERE n.course_id IS NULL)
    """))
    if has_history or has_attachments:
        raise RuntimeError("Cannot downgrade: unbound notes now have history or attachments")
    connection.exec_driver_sql("""
        CREATE TABLE unbound_notebooks (
            id VARCHAR(36) NOT NULL PRIMARY KEY,
            title VARCHAR(200) NOT NULL,
            document_json TEXT NOT NULL DEFAULT '[]',
            document_revision INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL
        )
    """)
    connection.exec_driver_sql("""
        INSERT INTO unbound_notebooks
        (id,title,document_json,document_revision,created_at,updated_at)
        SELECT id,title,document_json,document_revision,created_at,updated_at
        FROM notebooks WHERE course_id IS NULL
    """)
    connection.exec_driver_sql("DELETE FROM notebooks WHERE course_id IS NULL")
    _rebuild_notebooks(ondelete="CASCADE")
    _rebuild_attachments(nullable=False, ondelete="CASCADE")
