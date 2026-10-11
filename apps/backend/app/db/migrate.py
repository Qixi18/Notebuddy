"""Versioned SQLite startup migration with a verified pre-upgrade checkpoint."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, text

from app.core.config import settings
from app.db import models  # noqa: F401 - register tables
from app.db.checkpoint import create_checkpoint
from app.db.database import Base, engine

INITIAL_REVISION = "964d70a06320"
NOTEBOOK_COLUMNS = {
    "courses": {"notebook_order_revision"},
    "materials": {"chapter_order"},
    "notes": {"material_id", "section_key", "section_order"},
}
PHASE_ONE_COLUMNS = {
    "courses": {"deleted_at"},
    "materials": {"content_hash", "deleted_at"},
    "processing_jobs": {
        "error_code", "attempt_count", "idempotency_key", "started_at",
        "finished_at", "heartbeat_at",
    },
}
PHASE_TWO_COLUMNS = {
    "materials": {"parser_version", "document_warning"},
    "material_pages": {"location_type", "location_label", "stable_location_key", "extraction_method", "confidence", "is_active"},
    "page_blocks": {"object_id", "location_label", "extraction_method", "confidence", "warning"},
    "source_refs": {"status", "target_label", "parser_version"},
}
PHASE_THREE_TABLES = {
    "conversations", "conversation_messages", "message_evidence",
    "knowledge_proposals", "knowledge_changes", "note_suggestions",
    "feedback", "backup_records", "provider_calls",
}
LEGACY_COLUMNS = {
    "materials": {"topic_title": "VARCHAR(200)"},
    "processing_jobs": {
        "phase": "VARCHAR(30) NOT NULL DEFAULT 'queued'",
        "web_search_status": "VARCHAR(30) NOT NULL DEFAULT 'not_started'",
    },
}


def _config() -> Config:
    return Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))


def _revision() -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def _prepare_legacy_schema() -> None:
    """Bridge pre-Alembic databases to the frozen initial revision."""
    found = set(inspect(engine).get_table_names())
    if not found or found == {"alembic_version"}:
        return
    required = {table.name for table in Base.metadata.sorted_tables} - {
        "web_sources", "note_source_mappings", *PHASE_THREE_TABLES,
    }
    if not required.issubset(found):
        raise RuntimeError(f"Unsupported legacy schema; missing tables: {sorted(required - found)}")
    with engine.begin() as connection:
        for table, columns in LEGACY_COLUMNS.items():
            existing = {column["name"] for column in inspect(connection).get_columns(table)}
            for name, declaration in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}"))
    # Create only legacy bridge tables here. Phase three/four tables must be
    # created by their Alembic revision below, otherwise the revision would
    # attempt to create tables that this compatibility bridge already made.
    Base.metadata.create_all(
        engine,
        tables=[table for table in Base.metadata.sorted_tables if table.name not in PHASE_THREE_TABLES],
    )
    with engine.connect() as connection:
        inspector = inspect(connection)
        for table in Base.metadata.sorted_tables:
            if table.name in PHASE_THREE_TABLES:
                continue
            existing = {column["name"] for column in inspector.get_columns(table.name)}
            baseline = {column.name for column in table.columns} - PHASE_ONE_COLUMNS.get(table.name, set()) - PHASE_TWO_COLUMNS.get(table.name, set()) - NOTEBOOK_COLUMNS.get(table.name, set())
            if not baseline.issubset(existing):
                raise RuntimeError(f"Unsupported legacy columns in {table.name}: {sorted(baseline - existing)}")


def migrate_database() -> Path | None:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.originals_dir.mkdir(parents=True, exist_ok=True)
    settings.derived_dir.mkdir(parents=True, exist_ok=True)
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    config = _config()
    head = ScriptDirectory.from_config(config).get_current_head()
    database = settings.data_dir / "notebook.sqlite3"
    current = _revision() if database.exists() else None
    if current == head:
        return None
    checkpoint = None
    if database.exists() and database.stat().st_size:
        suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        checkpoint = create_checkpoint(settings.data_dir, settings.backups_dir / f"pre-migration-{suffix}")
    if current is None and database.exists() and inspect(engine).get_table_names():
        _prepare_legacy_schema()
        command.stamp(config, INITIAL_REVISION)
    command.upgrade(config, "head")
    return checkpoint
