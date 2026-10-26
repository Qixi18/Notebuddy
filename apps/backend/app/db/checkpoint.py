"""Small, verifiable local data checkpoints used before migrations and deletion."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def referenced_original_names(connection: sqlite3.Connection, *, include_removed: bool = True) -> set[str]:
    """Read only stored originals; old databases need no forest tables."""
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    names = set()
    if "materials" in tables:
        suffix = "" if include_removed else " WHERE deleted_at IS NULL"
        names.update(row[0] for row in connection.execute("SELECT stored_filename FROM materials" + suffix))
    if "curriculum_imports" in tables:
        names.update(row[0] for row in connection.execute("SELECT stored_filename FROM curriculum_imports WHERE stored_filename IS NOT NULL"))
    return names


def validate_original_name(name: str) -> None:
    if not isinstance(name, str) or not name or name in {".", ".."} or any(character in name for character in ("/", "\\", ":")) or Path(name).name != name:
        raise ValueError("Unsafe stored filename in database")


def _copy_asset_key(data_dir: Path, destination: Path, key: str) -> dict:
    if (not isinstance(key, str) or not key or Path(key).is_absolute()
            or "\\" in key or ":" in key or ".." in Path(key).parts):
        raise ValueError("Unsafe asset storage key in database")
    source_root = data_dir.resolve()
    candidate = source_root / key
    source = candidate.resolve()
    if not source.is_relative_to(source_root):
        raise ValueError(f"Asset path is unsafe: {key}")
    current = candidate
    while current != source_root:
        if current.is_symlink():
            raise ValueError(f"Asset path contains a symlink: {key}")
        current = current.parent
    if not source.is_file():
        raise FileNotFoundError(key)
    target = destination / key
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if (not target.is_file() or target.stat().st_size != source.stat().st_size
                or _sha256(target) != _sha256(source)):
            raise FileExistsError(target)
    else:
        shutil.copy2(source, target)
    return {"key": key, "bytes": target.stat().st_size, "sha256": _sha256(target)}


def create_checkpoint(data_dir: Path, destination: Path) -> Path:
    """Snapshot SQLite online, then copy immutable originals into a new directory."""
    database = data_dir / "notebook.sqlite3"
    if not database.is_file():
        raise FileNotFoundError(database)
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    try:
        with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(
            destination / "notebook.sqlite3"
        )) as target:
            source.backup(target)
        originals = destination / "originals"
        originals.mkdir()
        asset_files = []
        unavailable_assets = []
        files = []
        unavailable_originals = []
        with closing(sqlite3.connect(destination / "notebook.sqlite3")) as snapshot:
            raw_names = referenced_original_names(snapshot)
            filenames = sorted(name for name in raw_names
                               if isinstance(name, str) and not Path(name).is_absolute()
                               and "/" not in name and "\\" not in name)
            if raw_names - set(filenames):
                raise ValueError("Unsafe stored filename in database")
            tables = {row[0] for row in snapshot.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            asset_keys = sorted(row[0] for row in snapshot.execute(
                "SELECT storage_key FROM assets WHERE state NOT IN ('deleted','missing')"
            )) if "assets" in tables else []
        for name in filenames:
            validate_original_name(name)
            source = data_dir / "originals" / name
            if source.is_symlink() or source.parent.is_symlink():
                raise ValueError(f"Original path is unsafe: {name}")
            if not source.exists():
                unavailable_originals.append({"name": name, "status": "missing"})
                continue
            if not source.is_file():
                unavailable_originals.append({"name": name, "status": "unreadable"})
                continue
            target = originals / name
            try:
                shutil.copy2(source, target)
            except OSError:
                unavailable_originals.append({"name": name, "status": "unreadable"})
                target.unlink(missing_ok=True)
                continue
            files.append({"name": name, "bytes": target.stat().st_size, "sha256": _sha256(target)})
        for key in asset_keys:
            try:
                asset_files.append(_copy_asset_key(data_dir, destination, key))
            except FileNotFoundError:
                unavailable_assets.append({"key": key, "status": "missing"})
            except OSError:
                unavailable_assets.append({"key": key, "status": "unreadable"})
        manifest = {
            "format": 1,
            "created_at": datetime.now(UTC).isoformat(),
            "database_sha256": _sha256(destination / "notebook.sqlite3"),
            "originals": files,
            "assets": asset_files,
            "unavailable_originals": unavailable_originals,
            "unavailable_assets": unavailable_assets,
        }
        (destination / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        verify_checkpoint(destination)
        return destination
    except Exception:
        shutil.rmtree(destination)
        raise


def verify_checkpoint(checkpoint: Path) -> dict:
    manifest = json.loads((checkpoint / "manifest.json").read_text(encoding="utf-8"))
    database = checkpoint / "notebook.sqlite3"
    if manifest["format"] != 1 or _sha256(database) != manifest["database_sha256"]:
        raise ValueError("Checkpoint database hash mismatch")
    with closing(sqlite3.connect(database)) as connection:
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Checkpoint database integrity check failed")
        expected_originals = referenced_original_names(connection)
        recorded_originals = {entry["name"] for entry in manifest["originals"]}
        recorded_originals.update(entry["name"] for entry in manifest.get("unavailable_originals", []))
        if expected_originals != recorded_originals:
            raise ValueError("Checkpoint database references an unlisted original")
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        db_asset_keys = {row[0] for row in connection.execute(
            "SELECT storage_key FROM assets WHERE state NOT IN ('deleted','missing')"
        )} if "assets" in tables else set()
    manifest_asset_keys = {entry["key"] for entry in manifest.get("assets", [])}
    manifest_asset_keys.update(entry["key"] for entry in manifest.get("unavailable_assets", []))
    if db_asset_keys != manifest_asset_keys:
        raise ValueError("Checkpoint database Asset references do not match the manifest")
    for entry in manifest["originals"]:
        name = entry["name"]
        validate_original_name(name)
        path = checkpoint / "originals" / name
        if path.stat().st_size != entry["bytes"] or _sha256(path) != entry["sha256"]:
            raise ValueError(f"Checkpoint original hash mismatch: {name}")
    for entry in manifest.get("unavailable_originals", []):
        name = entry["name"]
        validate_original_name(name)
        if (checkpoint / "originals" / name).exists():
            raise ValueError(f"Unavailable original unexpectedly exists: {name}")
    for entry in manifest.get("assets", []):
        key = entry["key"]
        if (not isinstance(key, str) or not key or Path(key).is_absolute()
                or "\\" in key or ":" in key or ".." in Path(key).parts):
            raise ValueError("Unsafe asset storage key in checkpoint manifest")
        path = (checkpoint / key).resolve()
        if (not path.is_relative_to(checkpoint.resolve()) or not path.is_file()
                or path.stat().st_size != entry["bytes"] or _sha256(path) != entry["sha256"]):
            raise ValueError(f"Checkpoint asset hash mismatch: {key}")
    for entry in manifest.get("unavailable_assets", []):
        key = entry["key"]
        if (not isinstance(key, str) or not key or Path(key).is_absolute()
                or "\\" in key or ":" in key or ".." in Path(key).parts):
            raise ValueError("Unsafe unavailable asset key in checkpoint manifest")
        if (checkpoint / key).exists():
            raise ValueError(f"Unavailable Asset unexpectedly exists: {key}")
    return manifest


def restore_checkpoint(checkpoint: Path, destination: Path) -> None:
    """Restore only into an empty directory; never replace a live data directory."""
    verify_checkpoint(checkpoint)
    if destination.exists() and any(destination.iterdir()):
        raise FileExistsError(destination)
    destination.mkdir(parents=True, exist_ok=True)
    shutil.copy2(checkpoint / "notebook.sqlite3", destination / "notebook.sqlite3")
    shutil.copytree(checkpoint / "originals", destination / "originals", dirs_exist_ok=True)
    for entry in verify_checkpoint(checkpoint).get("assets", []):
        key = entry["key"]
        target = destination / key
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(checkpoint / key, target)


def main() -> None:
    parser = argparse.ArgumentParser(description="Create, verify or restore a NoteBuddy checkpoint")
    parser.add_argument("action", choices=("create", "verify", "restore"))
    parser.add_argument("path", type=Path, help="Checkpoint directory")
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    if args.action == "create":
        if args.data_dir is None:
            parser.error("create requires --data-dir")
        create_checkpoint(args.data_dir.resolve(), args.path.resolve())
    elif args.action == "verify":
        verify_checkpoint(args.path.resolve())
    else:
        if args.destination is None:
            parser.error("restore requires --destination")
        restore_checkpoint(args.path.resolve(), args.destination.resolve())
    print(f"{args.action} verified: {args.path.resolve()}")


if __name__ == "__main__":
    main()
