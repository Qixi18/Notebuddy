"""Verifiable NoteBuddy backup packages without secrets or derived-only data."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.security import validate_archive_member
from app.db.checkpoint import referenced_original_names, validate_original_name

FORMAT_VERSION = 2
MAX_FILES = 2000
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_sha256(archive: zipfile.ZipFile, member: str) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    with archive.open(member) as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            total += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), total


def _snapshot(database: Path, destination: Path) -> None:
    with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(destination)) as target:
        source.backup(target)


def _asset_source_path(data_dir: Path, storage_key: str) -> Path:
    if (not isinstance(storage_key, str) or not storage_key or "\\" in storage_key
            or ":" in storage_key or Path(storage_key).is_absolute()
            or ".." in Path(storage_key).parts or len(Path(storage_key).parts) < 2
            or storage_key in {".env", "notebook.sqlite3"}):
        raise ValueError("unsafe Asset storage key")
    root = data_dir.resolve()
    candidate = root / storage_key
    source = candidate.resolve()
    if not source.is_relative_to(root) or source == root:
        raise ValueError("Asset storage key escapes the data directory")
    current = candidate
    while current != root:
        if current.is_symlink():
            raise ValueError("Asset storage path contains a symlink")
        current = current.parent
    return source


def _asset_entries(database: Path, data_dir: Path) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(database)) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        if "assets" not in tables:
            return []
        rows = connection.execute(
            "SELECT storage_key FROM assets WHERE state NOT IN ('deleted','missing') "
            "ORDER BY storage_key"
        ).fetchall()
    entries = []
    for (key,) in rows:
        source = _asset_source_path(data_dir, key)
        if not source.is_file():
            raise ValueError(f"Asset missing or not a file: {key}")
        entries.append({"key": key, "bytes": source.stat().st_size, "sha256": _sha256(source)})
    return entries


def _filter_snapshot_to_course(database: Path, course_id: str) -> None:
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        if connection.execute("SELECT 1 FROM courses WHERE id = ?", (course_id,)).fetchone() is None:
            raise ValueError("course does not exist in backup snapshot")
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "notebooks" in tables and "materials" in tables:
            # Course is only a grouping. Keep Materials owned by this course's
            # Notebooks, plus genuinely legacy course-only rows; do not let
            # ON DELETE SET NULL turn other courses' Materials into unowned
            # rows that survive in this package.
            connection.execute("""
                DELETE FROM materials
                WHERE (notebook_id IS NOT NULL AND notebook_id NOT IN
                       (SELECT id FROM notebooks WHERE course_id = ?))
                   OR (notebook_id IS NULL AND (course_id IS NULL OR course_id != ?))
            """, (course_id, course_id))
            connection.execute(
                "DELETE FROM notebooks WHERE course_id IS NULL OR course_id != ?",
                (course_id,),
            )
        # Forest jobs and plans coordinate the whole curriculum; no partial export
        # may carry external course references in their JSON or evidence snapshots.
        for table in ("cross_course_relations", "forest_jobs", "curriculum_imports"):
            if table in tables:
                connection.execute(f"DELETE FROM {table}")
        if "asset_migration_issues" in tables:
            # Migration reconciliation is global operational metadata and is
            # not part of a course content package.
            connection.execute("DELETE FROM asset_migration_issues")
        connection.execute("DELETE FROM courses WHERE id != ?", (course_id,))
        if "assets" in tables and "notebook_assets" in tables:
            connection.execute("""
                DELETE FROM assets
                WHERE id NOT IN (SELECT asset_id FROM notebook_assets)
                  AND id NOT IN (SELECT asset_id FROM materials WHERE asset_id IS NOT NULL)
                  AND id NOT IN (SELECT asset_id FROM notebook_attachments WHERE asset_id IS NOT NULL)
                  AND id NOT IN (SELECT asset_id FROM notebook_cover_assets)
            """)
        connection.commit()


def _original_names(database: Path) -> tuple[list[str], int, int]:
    with closing(sqlite3.connect(database)) as connection:
        courses = int(connection.execute("SELECT COUNT(*) FROM courses WHERE deleted_at IS NULL").fetchone()[0])
        materials = int(connection.execute("SELECT COUNT(*) FROM materials WHERE deleted_at IS NULL").fetchone()[0])
        names = referenced_original_names(connection, include_removed=False)
    return sorted(names), courses, materials


def create_backup_archive(data_dir: Path, destination: Path, *, course_id: str | None = None) -> dict:
    database = data_dir / "notebook.sqlite3"
    originals_dir = data_dir / "originals"
    if not database.is_file():
        raise FileNotFoundError(database)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="notebuddy-backup-") as temp:
        root = Path(temp)
        snapshot = root / "notebook.sqlite3"
        _snapshot(database, snapshot)
        if course_id:
            _filter_snapshot_to_course(snapshot, course_id)
        names, course_count, material_count = _original_names(snapshot)
        assets = _asset_entries(snapshot, data_dir)
        files: list[dict] = []
        for name in names:
            validate_original_name(name)
            source = originals_dir / name
            if not source.is_file() or source.is_symlink():
                raise ValueError(f"original missing or unsafe: {name}")
            files.append({"name": name, "bytes": source.stat().st_size, "sha256": _sha256(source)})
        manifest = {
            "format": FORMAT_VERSION,
            "created_at": datetime.now(UTC).isoformat(),
            "database_sha256": _sha256(snapshot),
            "course_count": course_count,
            "material_count": material_count,
            "originals": files,
            "assets": assets,
            "derived_indexes": "omitted; rebuild from SQLite pages",
        }
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            archive.write(snapshot, "notebook.sqlite3")
            for entry in files:
                archive.write(originals_dir / entry["name"], f"originals/{entry['name']}")
            for entry in assets:
                archive.write(data_dir / entry["key"], f"resources/{entry['key']}")
    preview_backup(destination)
    return manifest


def _read_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        manifest = json.loads(archive.read("manifest.json"))
    except (KeyError, json.JSONDecodeError) as exc:
        raise ValueError("backup manifest is missing or invalid") from exc
    if not isinstance(manifest, dict):
        raise TypeError("backup manifest must be an object")
    if manifest.get("format") != FORMAT_VERSION:
        raise ValueError("unsupported backup format")
    originals = manifest.get("originals")
    if not isinstance(originals, list):
        raise TypeError("backup manifest originals must be a list")
    for entry in originals:
        if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
            raise TypeError("backup manifest contains an invalid original entry")
        name = entry["name"]
        validate_original_name(name)
        if not entry.get("sha256") or not isinstance(entry.get("bytes"), int):
            raise ValueError(f"backup manifest contains an unsafe original: {name}")
    assets = manifest.get("assets", [])
    if not isinstance(assets, list):
        raise TypeError("backup manifest assets must be a list")
    asset_keys = set()
    for entry in assets:
        if not isinstance(entry, dict) or not isinstance(entry.get("key"), str):
            raise TypeError("backup manifest contains an invalid Asset entry")
        key = entry["key"]
        if key in asset_keys:
            raise ValueError("backup manifest contains duplicate Asset keys")
        asset_keys.add(key)
        if not entry.get("sha256") or not isinstance(entry.get("bytes"), int):
            raise ValueError("backup manifest contains an unsafe Asset entry")
        # Validate the archive member form and the destination-relative key.
        validate_archive_member(f"resources/{key}")
        if ("\\" in key or ":" in key or Path(key).is_absolute()
                or ".." in Path(key).parts or len(Path(key).parts) < 2
                or key in {".env", "notebook.sqlite3"}):
            raise ValueError("backup manifest contains an unsafe Asset storage key")
    return manifest


def _database_conflicts(database: Path, manifest: dict[str, Any]) -> list[str]:
    """Compare package original names with the current local data."""
    if not database.is_file():
        return []
    conflicts: list[str] = []
    package_files = {entry["name"]: entry["sha256"] for entry in manifest.get("originals", [])}
    originals_dir = database.parent / "originals"
    for name, digest in package_files.items():
        current = originals_dir / name
        if current.is_file() and _sha256(current) != digest:
            conflicts.append(f"原文件同名但内容不同：{name}")
    return conflicts[:50]


def _course_conflicts(package_database: Path, current_database: Path | None) -> list[str]:
    if current_database is None or not current_database.is_file():
        return []
    try:
        with closing(sqlite3.connect(package_database)) as package_connection, closing(
            sqlite3.connect(current_database)
        ) as current_connection:
            package_courses = dict(package_connection.execute("SELECT id, name FROM courses"))
            current_courses = dict(current_connection.execute("SELECT id, name FROM courses"))
    except sqlite3.Error:
        return []
    conflicts = [
        f"课程 ID 冲突：{course_id}（名称不同）"
        for course_id, name in package_courses.items()
        if course_id in current_courses and current_courses[course_id] != name
    ]
    current_names = {name: course_id for course_id, name in current_courses.items()}
    conflicts.extend(
        f"课程名称冲突：{name}（已有不同 ID）"
        for course_id, name in package_courses.items()
        if name in current_names and current_names[name] != course_id
    )
    return conflicts[:50]


def preview_backup(path: Path, *, current_database: Path | None = None) -> dict:
    if not path.is_file() or path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("backup archive is missing or too large")
    with zipfile.ZipFile(path) as archive:
        if len(archive.infolist()) > MAX_FILES:
            raise ValueError("backup contains too many files")
        names = [info.filename for info in archive.infolist()]
        if len(names) != len(set(names)):
            raise ValueError("backup contains duplicate archive members")
        for info in archive.infolist():
            validate_archive_member(info.filename)
        manifest = _read_manifest(archive)
        errors: list[str] = []
        conflicts: list[str] = _database_conflicts(current_database, manifest) if current_database else []
        try:
            database_hash, _ = _archive_sha256(archive, "notebook.sqlite3")
        except KeyError as exc:
            raise ValueError("backup database is missing") from exc
        if database_hash != manifest.get("database_sha256"):
            errors.append("database hash mismatch")
        manifest_entries = manifest.get("originals", [])
        manifest_names = {entry["name"] for entry in manifest_entries}
        archive_names = {name.removeprefix("originals/") for name in names if name.startswith("originals/") and not name.endswith("/")}
        for extra in sorted(archive_names - manifest_names):
            errors.append(f"original not listed in manifest: {extra}")
        for entry in manifest_entries:
            member = f"originals/{entry['name']}"
            try:
                digest, size = _archive_sha256(archive, member)
            except KeyError:
                errors.append(f"missing original: {entry['name']}")
                continue
            if size != entry.get("bytes") or digest != entry.get("sha256"):
                errors.append(f"original hash mismatch: {entry['name']}")
        asset_entries = manifest.get("assets", [])
        manifest_asset_keys = {entry["key"] for entry in asset_entries}
        archive_asset_keys = {
            name.removeprefix("resources/")
            for name in names
            if name.startswith("resources/") and not name.endswith("/")
        }
        for extra in sorted(archive_asset_keys - manifest_asset_keys):
            errors.append(f"Asset not listed in manifest: {extra}")
        for missing in sorted(manifest_asset_keys - archive_asset_keys):
            errors.append(f"missing Asset: {missing}")
        for entry in asset_entries:
            member = f"resources/{entry['key']}"
            try:
                digest, size = _archive_sha256(archive, member)
            except KeyError:
                continue
            if size != entry["bytes"] or digest != entry["sha256"]:
                errors.append(f"Asset hash mismatch: {entry['key']}")
        database = archive.read("notebook.sqlite3")
        with tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False) as temp:
            temp.write(database)
            temp_path = Path(temp.name)
        try:
            with closing(sqlite3.connect(temp_path)) as connection:
                integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
                if integrity != "ok":
                    errors.append(f"sqlite integrity: {integrity}")
                foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
                if foreign_keys:
                    errors.append(f"sqlite foreign key errors: {len(foreign_keys)}")
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if {"courses", "materials"}.issubset(tables):
                    references = referenced_original_names(connection, include_removed=False)
                    missing = sorted(references - manifest_names)
                    errors.extend(f"database references missing original: {name}" for name in missing[:50])
                    db_asset_keys = set()
                    if "assets" in tables:
                        db_asset_keys = {row[0] for row in connection.execute(
                            "SELECT storage_key FROM assets WHERE state NOT IN ('deleted','missing')"
                        )}
                    for key in sorted(db_asset_keys - manifest_asset_keys):
                        errors.append(f"database references missing Asset: {key}")
                    for key in sorted(manifest_asset_keys - db_asset_keys):
                        errors.append(f"backup lists unreferenced Asset: {key}")
                    conflicts.extend(_course_conflicts(temp_path, current_database))
                else:
                    errors.append("sqlite schema is missing courses or materials")
        finally:
            temp_path.unlink(missing_ok=True)
        return {
            "valid": not errors,
            "format": manifest.get("format"),
            "created_at": manifest.get("created_at"),
            "course_count": manifest.get("course_count", 0),
            "material_count": manifest.get("material_count", 0),
            "original_count": len(manifest.get("originals", [])),
            "assets": manifest.get("assets", []),
            "asset_count": len(manifest.get("assets", [])),
            "total_bytes": (
                sum(int(item.get("bytes", 0)) for item in manifest.get("originals", []))
                + sum(int(item.get("bytes", 0)) for item in manifest.get("assets", []))
            ),
            "conflicts": conflicts,
            "errors": errors,
        }


def restore_backup_to_empty(path: Path, destination: Path) -> dict:
    preview = preview_backup(path)
    if not preview["valid"]:
        raise ValueError("backup failed validation: " + "; ".join(preview["errors"]))
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError("restore destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path) as archive:
        archive.extract("notebook.sqlite3", destination)
        (destination / "originals").mkdir()
        for info in archive.infolist():
            if info.filename.startswith("originals/") and not info.is_dir():
                target = destination / info.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
        for entry in preview.get("assets", []):
            key = entry["key"]
            member = f"resources/{key}"
            target = destination / key
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
    return preview


def main() -> None:
    parser = argparse.ArgumentParser(description="Create, preview or restore a NoteBuddy package")
    parser.add_argument("action", choices=("create", "preview", "restore"))
    parser.add_argument("path", type=Path)
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    if args.action == "create":
        if args.data_dir is None:
            parser.error("create requires --data-dir")
        manifest = create_backup_archive(args.data_dir.resolve(), args.path.resolve())
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    elif args.action == "preview":
        print(json.dumps(preview_backup(args.path.resolve()), ensure_ascii=False, indent=2))
    else:
        if args.destination is None:
            parser.error("restore requires --destination")
        print(json.dumps(restore_backup_to_empty(args.path.resolve(), args.destination.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
