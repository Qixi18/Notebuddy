"""Small security boundaries shared by local backup and external text flows."""

from __future__ import annotations

from pathlib import PurePosixPath


def validate_archive_member(name: str) -> str:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError(f"unsafe archive path: {name}")
    normalized = str(path)
    if normalized in {"", "."}:
        raise ValueError("empty archive path")
    return normalized

