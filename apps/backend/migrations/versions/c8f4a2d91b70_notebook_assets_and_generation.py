"""Introduce Notebook-owned assets and durable generation candidates.

Legacy course-only Material rows remain untouched. Only Material rows which
already have an owning Notebook are mapped into the new Asset registry.
"""

import json
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "c8f4a2d91b70"
down_revision = "b7c2e5a910df"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("notebook_document_revisions") as batch:
        batch.create_unique_constraint(
            "uq_notebook_revision_id_notebook", ["id", "notebook_id"]
        )

    op.create_table(
        "assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("media_type", sa.String(20), nullable=False),
        sa.Column("mime_type", sa.String(120), nullable=False),
        sa.Column("extension", sa.String(20), nullable=False),
        sa.Column("original_name", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False, unique=True),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("state", sa.String(20), server_default="ready", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "state IN ('staging','ready','missing','quarantined','delete_pending','deleted')",
            name="ck_assets_state",
        ),
    )
    op.create_index("ix_assets_state_created", "assets", ["state", "created_at"])
    op.create_index("ix_assets_sha256", "assets", ["sha256"])
    op.create_table(
        "asset_migration_issues",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_table", sa.String(80), nullable=False),
        sa.Column("source_id", sa.String(36), nullable=False),
        sa.Column("issue_code", sa.String(60), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column("detected_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint(
            "source_table", "source_id", "issue_code",
            name="uq_asset_migration_issue_source_code",
        ),
    )
    op.create_index("ix_asset_migration_issues_unresolved", "asset_migration_issues",
                    ["resolved_at", "source_table"])
    op.create_table(
        "notebook_cover_assets",
        sa.Column("notebook_id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.String(36), nullable=False, unique=True),
        sa.Column("owner_link_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_link_id", "notebook_id", "asset_id"],
            ["notebook_assets.id", "notebook_assets.notebook_id", "notebook_assets.asset_id"],
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "notebook_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("notebook_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("is_owner", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("detached_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("id", "notebook_id", "asset_id", name="uq_notebook_asset_owner_ref"),
    )
    op.create_index(
        "uq_notebook_assets_one_active_owner_per_asset", "notebook_assets", ["asset_id"],
        unique=True, sqlite_where=sa.text("is_owner = 1 AND detached_at IS NULL"),
    )
    op.create_index(
        "uq_notebook_assets_active_use", "notebook_assets", ["notebook_id", "asset_id", "role"],
        unique=True, sqlite_where=sa.text("detached_at IS NULL"),
    )
    op.create_index("ix_notebook_assets_notebook", "notebook_assets", ["notebook_id", "created_at"])

    with op.batch_alter_table("materials") as batch:
        batch.add_column(sa.Column("asset_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_materials_asset_id_assets", "assets", ["asset_id"], ["id"], ondelete="SET NULL")
        batch.create_unique_constraint("uq_materials_asset_id", ["asset_id"])
    with op.batch_alter_table("notebook_attachments") as batch:
        batch.add_column(sa.Column("asset_id", sa.String(36), nullable=True))
        batch.create_foreign_key("fk_notebook_attachments_asset_id_assets", "assets", ["asset_id"], ["id"], ondelete="SET NULL")
        batch.create_unique_constraint("uq_notebook_attachments_asset_id", ["asset_id"])

    op.create_table(
        "notebook_revision_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("revision_id", sa.String(36), nullable=False),
        sa.Column("notebook_id", sa.String(36), nullable=False),
        sa.Column("owner_link_id", sa.String(36), nullable=False),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("node_id", sa.String(64), nullable=True),
        sa.ForeignKeyConstraint(
            ["revision_id", "notebook_id"],
            ["notebook_document_revisions.id", "notebook_document_revisions.notebook_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["owner_link_id", "notebook_id", "asset_id"],
            ["notebook_assets.id", "notebook_assets.notebook_id", "notebook_assets.asset_id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("revision_id", "asset_id", name="uq_notebook_revision_asset"),
    )
    op.create_index("ix_notebook_revision_assets_asset", "notebook_revision_assets", ["asset_id"])

    op.create_table(
        "asset_processing_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("notebook_id", sa.String(36), nullable=False),
        sa.Column("owner_link_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(30), server_default="image_parse", nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["owner_link_id", "notebook_id", "asset_id"],
            ["notebook_assets.id", "notebook_assets.notebook_id", "notebook_assets.asset_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_asset_processing_jobs_asset", "asset_processing_jobs", ["asset_id", "created_at"])
    op.create_index(
        "uq_asset_processing_jobs_active", "asset_processing_jobs", ["asset_id"],
        unique=True, sqlite_where=sa.text("status IN ('pending', 'processing')"),
    )
    op.create_table(
        "asset_parse_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("asset_id", sa.String(36), nullable=False),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("parser_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("warnings_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["job_id"], ["asset_processing_jobs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_asset_parse_results_asset", "asset_parse_results", ["asset_id", "created_at"])

    op.create_table(
        "notebook_generation_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("notebook_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending", nullable=False),
        sa.Column("base_document_revision", sa.Integer(), nullable=False),
        sa.Column("input_snapshot_json", sa.Text(), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="2", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(60), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("notebook_id", "idempotency_key", name="uq_notebook_generation_idempotency"),
        sa.UniqueConstraint("id", "notebook_id", name="uq_notebook_generation_job_id_notebook"),
    )
    op.create_index("ix_notebook_generation_status", "notebook_generation_jobs", ["status", "created_at"])
    op.create_table(
        "notebook_generation_candidates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_id", sa.String(36), nullable=False),
        sa.Column("notebook_id", sa.String(36), nullable=False),
        sa.Column("document_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending_review", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["notebook_id"], ["notebooks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["job_id", "notebook_id"],
            ["notebook_generation_jobs.id", "notebook_generation_jobs.notebook_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("job_id", name="uq_notebook_candidate_job"),
    )

    # Stable IDs for legacy image attachments preserve editor references. Files
    # remain at their existing paths; reconciliation verifies their presence.
    connection = op.get_bind()
    import hashlib
    import warnings
    from collections import Counter
    from pathlib import Path
    from uuid import uuid4

    from app.core.config import settings

    def record_issue(source_table: str, source_id: str, issue_code: str, **details: object) -> None:
        connection.execute(sa.text("""
            INSERT OR IGNORE INTO asset_migration_issues
                (id, source_table, source_id, issue_code, details_json, detected_at)
            VALUES (:id, :table, :source_id, :code, :details, :detected_at)
        """), {
            "id": str(uuid4()), "table": source_table, "source_id": source_id,
            "code": issue_code, "details": json.dumps(details, ensure_ascii=False),
            "detected_at": datetime.now(UTC).replace(tzinfo=None),
        })

    def file_digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def safe_path(candidate: Path, root: Path) -> Path | None:
        try:
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root) or resolved == root:
                return None
            current = candidate
            while current != root:
                if current.is_symlink():
                    return None
                current = current.parent
            return resolved
        except (OSError, RuntimeError):
            return None

    attachments = connection.execute(sa.text(
        "SELECT id, notebook_id, original_filename, stored_filename, mime, size_bytes, created_at "
        "FROM notebook_attachments"
    )).mappings().all()
    attachment_path_counts = Counter(
        f"{row['notebook_id']}/{row['stored_filename']}".casefold() for row in attachments
    )
    attachment_root = (settings.data_dir / "notebook-attachments").resolve()
    for row in attachments:
        name = row["stored_filename"] or ""
        path_key = f"{row['notebook_id']}/{name}".casefold()
        if (not name or attachment_path_counts[path_key] != 1 or Path(name).name != name
                or "/" in name or "\\" in name):
            record_issue("notebook_attachments", row["id"], "unsafe_or_ambiguous_storage_key",
                         stored_filename=name)
            warnings.warn(f"Attachment {row['id']} kept on legacy path: unsafe stored filename")
            continue
        storage_key = f"notebook-attachments/{row['notebook_id']}/{name}"
        candidate = attachment_root / row["notebook_id"] / name
        path = safe_path(candidate, attachment_root)
        if path is None:
            record_issue("notebook_attachments", row["id"], "unsafe_storage_path",
                         stored_filename=name)
            warnings.warn(f"Attachment {row['id']} kept on legacy path: unsafe file path")
            continue
        exists = path.is_file()
        state = "ready" if exists else "missing"
        if exists:
            try:
                actual_size, actual_hash = path.stat().st_size, file_digest(path)
            except OSError:
                exists = False
                state = "quarantined"
                record_issue("notebook_attachments", row["id"], "unreadable_file",
                             stored_filename=name)
        if not exists and state == "missing":
            record_issue("notebook_attachments", row["id"], "missing_file",
                         stored_filename=name)
        mime = row["mime"] or "application/octet-stream"
        extension = {"image/png": ".png", "image/jpeg": ".jpg",
                     "image/webp": ".webp", "image/gif": ".gif"}.get(mime, "")
        connection.execute(sa.text("""
            INSERT INTO assets (id, source_type, media_type, mime_type, extension, original_name,
                                storage_key, byte_size, sha256, state, created_at, verified_at)
            VALUES (:id, 'user_upload', 'image', :mime, :ext, :name,
                    :storage_key, :size, :hash, :state, :created, :verified)
        """), {
            "id": row["id"], "mime": mime, "ext": extension,
            "name": row["original_filename"] or name, "storage_key": storage_key,
            "size": actual_size if exists else row["size_bytes"],
            "hash": actual_hash if exists else None,
            "state": state, "created": row["created_at"],
            "verified": row["created_at"] if exists else None,
        })
        connection.execute(sa.text("""
            INSERT INTO notebook_assets (id, notebook_id, asset_id, role, is_owner, created_at, detached_at)
            VALUES (:link_id, :notebook_id, :asset_id, 'inline_image', 1, :created, NULL)
        """), {"link_id": str(uuid4()), "notebook_id": row["notebook_id"],
               "asset_id": row["id"], "created": row["created_at"]})
        connection.execute(sa.text(
            "UPDATE notebook_attachments SET asset_id=:asset_id WHERE id=:attachment_id"
        ), {"asset_id": row["id"], "attachment_id": row["id"]})

    # Map only Notebook-owned Materials with a unique, safe storage name. This
    # migration inspects local files before asserting their hash/path. Ambiguous
    # and course-only rows remain untouched in the legacy Material API.
    material_rows = connection.execute(sa.text("""
        SELECT m.id, m.notebook_id, m.course_id, n.id AS matched_notebook_id,
               n.course_id AS notebook_course_id,
               m.original_filename, m.stored_filename, m.media_type,
               m.size_bytes, m.content_hash, m.created_at
        FROM materials AS m
        LEFT JOIN notebooks AS n ON n.id = m.notebook_id
        WHERE m.notebook_id IS NOT NULL
    """)).mappings().all()
    # Storage keys share one originals/ directory. A course-only legacy row
    # can therefore collide with a Notebook-owned row even though it is not
    # itself eligible for Asset backfill.
    counts = Counter(
        (row[0] or "").casefold()
        for row in connection.execute(sa.text("SELECT stored_filename FROM materials"))
    )
    originals_root = settings.originals_dir.resolve()
    for row in material_rows:
        if row["matched_notebook_id"] is None:
            record_issue("materials", row["id"], "missing_notebook",
                         notebook_id=row["notebook_id"], course_id=row["course_id"])
            warnings.warn(f"Material {row['id']} retained in legacy mapping: Notebook is missing")
            continue
        if (row["course_id"] is not None and row["notebook_course_id"] is not None
                and row["course_id"] != row["notebook_course_id"]):
            record_issue("materials", row["id"], "course_notebook_mismatch",
                         course_id=row["course_id"], notebook_course_id=row["notebook_course_id"],
                         notebook_id=row["notebook_id"])
            warnings.warn(f"Material {row['id']} retained in legacy mapping: Course/Notebook mismatch")
            continue
        stored_name = row["stored_filename"] or ""
        if (counts[stored_name.casefold()] != 1 or not stored_name or
                Path(stored_name).name != stored_name or "/" in stored_name or "\\" in stored_name):
            record_issue("materials", row["id"], "unsafe_or_ambiguous_storage_key",
                         stored_filename=stored_name)
            warnings.warn(f"Material {row['id']} retained in legacy mapping: ambiguous storage name")
            continue
        candidate = originals_root / stored_name
        path = safe_path(candidate, originals_root)
        if path is None:
            record_issue("materials", row["id"], "unsafe_storage_path",
                         stored_filename=stored_name)
            warnings.warn(f"Material {row['id']} retained in legacy mapping: unsafe storage path")
            continue
        exists = path.is_file() and not path.is_symlink()
        actual_size = row["size_bytes"]
        actual_hash = row["content_hash"]
        state = "ready" if exists else "missing"
        if exists:
            try:
                actual_size, actual_hash = path.stat().st_size, file_digest(path)
            except OSError:
                exists = False
                state = "quarantined"
                record_issue("materials", row["id"], "unreadable_file",
                             stored_filename=stored_name)
        if not exists and state == "missing":
            record_issue("materials", row["id"], "missing_file",
                         stored_filename=stored_name)
        if exists and row["content_hash"] and actual_hash != row["content_hash"]:
            state = "quarantined"
            record_issue("materials", row["id"], "hash_mismatch",
                         stored_filename=stored_name)
        collision = connection.scalar(sa.text("SELECT 1 FROM assets WHERE id=:id"), {"id": row["id"]})
        if collision:
            record_issue("materials", row["id"], "asset_id_collision")
            warnings.warn(f"Material {row['id']} retained in legacy mapping: Asset ID collision")
            continue
        connection.execute(sa.text("""
            INSERT INTO assets (id, source_type, media_type, mime_type, extension, original_name,
                                storage_key, byte_size, sha256, state, created_at, verified_at)
            VALUES (:id, 'user_upload', 'document', :mime, :ext, :name,
                    :storage_key, :size, :hash, :state, :created, :verified)
        """), {
            "id": row["id"], "mime": row["media_type"] or "application/octet-stream",
            "ext": Path(row["original_filename"] or stored_name).suffix.lower(),
            "name": row["original_filename"] or stored_name,
            "storage_key": f"originals/{stored_name}", "size": actual_size,
            "hash": actual_hash, "state": state, "created": row["created_at"],
            "verified": row["created_at"] if exists else None,
        })
        connection.execute(sa.text("""
            INSERT INTO notebook_assets (id, notebook_id, asset_id, role, is_owner, created_at, detached_at)
            VALUES (:link_id, :notebook_id, :asset_id, 'source_material', 1, :created, NULL)
        """), {"link_id": str(uuid4()), "notebook_id": row["notebook_id"],
               "asset_id": row["id"], "created": row["created_at"]})
        connection.execute(sa.text(
            "UPDATE materials SET asset_id=:asset_id WHERE id=:material_id"
        ), {"asset_id": row["id"], "material_id": row["id"]})

    # Keep legacy cover columns/API intact while mapping verifiable covers into
    # the unified Asset registry for subsequent reads and lifecycle management.
    cover_rows = connection.execute(sa.text(
        "SELECT id, cover_filename, cover_mime, created_at FROM notebooks "
        "WHERE cover_filename IS NOT NULL"
    )).mappings().all()
    cover_root = (settings.data_dir / "notebook-covers").resolve()
    cover_counts = Counter((row["cover_filename"] or "").casefold() for row in cover_rows)
    for row in cover_rows:
        name = row["cover_filename"] or ""
        if (not name or cover_counts[name.casefold()] != 1 or Path(name).name != name
                or "/" in name or "\\" in name):
            record_issue("notebooks", row["id"], "unsafe_or_ambiguous_cover_path",
                         cover_filename=name)
            warnings.warn(f"Notebook {row['id']} cover retained on legacy path: unsafe filename")
            continue
        candidate = cover_root / name
        path = safe_path(candidate, cover_root)
        if path is None:
            record_issue("notebooks", row["id"], "unsafe_cover_path",
                         cover_filename=name)
            warnings.warn(f"Notebook {row['id']} cover retained on legacy path: unsafe path")
            continue
        exists = path.is_file()
        state = "ready" if exists else "missing"
        size = 0
        content_hash = None
        if exists:
            try:
                size, content_hash = path.stat().st_size, file_digest(path)
            except OSError:
                exists = False
                state = "quarantined"
                record_issue("notebooks", row["id"], "unreadable_cover_file",
                             cover_filename=name)
        if not exists and state == "missing":
            record_issue("notebooks", row["id"], "missing_cover_file",
                         cover_filename=name)
        mime = row["cover_mime"] or "application/octet-stream"
        extension = Path(name).suffix.lower()
        asset_id = str(uuid4())
        connection.execute(sa.text("""
            INSERT INTO assets (id, source_type, media_type, mime_type, extension, original_name,
                                storage_key, byte_size, sha256, state, created_at, verified_at)
            VALUES (:id, 'user_upload', 'image', :mime, :ext, :name,
                    :storage_key, :size, :hash, :state, :created, :verified)
        """), {
            "id": asset_id, "mime": mime, "ext": extension, "name": name,
            "storage_key": f"notebook-covers/{name}",
            "size": size,
            "hash": content_hash,
            "state": state,
            "created": row["created_at"], "verified": row["created_at"] if exists else None,
        })
        cover_link_id = str(uuid4())
        connection.execute(sa.text("""
            INSERT INTO notebook_assets (id, notebook_id, asset_id, role, is_owner, created_at, detached_at)
            VALUES (:link_id, :notebook_id, :asset_id, 'cover', 1, :created, NULL)
        """), {"link_id": cover_link_id, "notebook_id": row["id"],
               "asset_id": asset_id, "created": row["created_at"]})
        connection.execute(sa.text("""
            INSERT INTO notebook_cover_assets (notebook_id, asset_id, owner_link_id, created_at)
            VALUES (:notebook_id, :asset_id, :owner_link_id, :created)
        """), {"notebook_id": row["id"], "asset_id": asset_id,
               "owner_link_id": cover_link_id, "created": row["created_at"]})
    # Pin all images found in retained snapshots before the old attachment
    # cleanup worker can decide they are orphaned.
    revisions = connection.execute(sa.text(
        "SELECT id, notebook_id, document_json FROM notebook_document_revisions"
    )).mappings()
    for revision in revisions:
        try:
            doc = json.loads(revision["document_json"])
        except (TypeError, ValueError):
            record_issue("notebook_document_revisions", revision["id"], "invalid_document_json")
            continue
        stack = [doc]
        seen: set[str] = set()
        while stack:
            node = stack.pop()
            if isinstance(node, dict):
                attrs = node.get("attrs") if isinstance(node.get("attrs"), dict) else {}
                for key in ("attachmentId", "assetId"):
                    asset_id = attrs.get(key)
                    if isinstance(asset_id, str) and asset_id not in seen:
                        seen.add(asset_id)
                stack.extend(node.values())
            elif isinstance(node, list):
                stack.extend(node)
        for asset_id in seen:
            owner_link_id = connection.scalar(sa.text(
                "SELECT id FROM notebook_assets WHERE notebook_id=:notebook_id "
                "AND asset_id=:asset_id AND is_owner=1"
            ), {"notebook_id": revision["notebook_id"], "asset_id": asset_id})
            if owner_link_id:
                connection.execute(sa.text(
                    "INSERT OR IGNORE INTO notebook_revision_assets "
                    "(id, revision_id, notebook_id, owner_link_id, asset_id, node_id) "
                    "VALUES (:id, :revision_id, :notebook_id, :owner_link_id, :asset_id, NULL)"
                ), {"id": str(uuid4()), "revision_id": revision["id"],
                    "notebook_id": revision["notebook_id"], "owner_link_id": owner_link_id,
                    "asset_id": asset_id})
            else:
                record_issue("notebook_document_revisions", revision["id"],
                             "unmapped_asset_reference", asset_id=asset_id)


def downgrade() -> None:
    raise RuntimeError(
        "This resource migration backfills durable Asset identities. Restore from a pre-migration backup instead of downgrading."
    )
