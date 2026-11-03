#!/usr/bin/env python3
"""Check enforceable architecture boundaries in current and changed source files.

This is intentionally a small stdlib-only static gate. Legacy service files are
not all framework-independent yet, so the FastAPI dependency rule is enforced
for changed service files while the single-writer and route boundaries are
checked across the full source tree.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "apps" / "backend" / "app"
AGGREGATE_ROUTES = {
    Path("apps/backend/app/api/v1/notebook.py"),
    Path("apps/backend/app/api/v1/materials.py"),
}


def python_sources(root: Path) -> list[Path]:
    return sorted(path for path in root.rglob("*.py") if "__pycache__" not in path.parts)


def parse(path: Path) -> ast.AST:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def changed_paths(base_ref: str | None) -> set[Path] | None:
    if not base_ref:
        return None
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{base_ref}^{{commit}}"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if exists.returncode:
        print(f"[architecture] Base {base_ref!r} is unavailable; changed-file checks are skipped.")
        return set()
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", f"{base_ref}...HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return {Path(line.strip()) for line in result.stdout.splitlines() if line.strip()}


def imports_fastapi(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            if any(alias.name == "fastapi" or alias.name.startswith("fastapi.") for alias in node.names):
                return True
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "fastapi" or node.module.startswith("fastapi.")):
                return True
    return False


def imports_or_calls_document_writer(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and node.module.endswith("notes.store"):
                if any(alias.name == "write_document" for alias in node.names):
                    return True
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "write_document":
                return True
            if isinstance(node.func, ast.Attribute) and node.func.attr == "write_document":
                return True
            if any(keyword.arg == "document_json" for keyword in node.keywords):
                return True
            if isinstance(node.func, ast.Attribute) and node.func.attr == "update":
                if any(
                    isinstance(child, ast.Attribute) and child.attr == "document_json"
                    for argument in node.args
                    for child in ast.walk(argument)
                ):
                    return True
            if isinstance(node.func, ast.Name) and node.func.id == "setattr":
                if (
                    len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value == "document_json"
                ):
                    return True
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(
                isinstance(target, ast.Attribute) and target.attr == "document_json"
                for assigned in targets
                for target in ast.walk(assigned)
            ):
                return True
    return False


def adds_registered_endpoint(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "router"
            ):
                return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-ref", help="Compare changed source files against this Git ref.")
    args = parser.parse_args()

    errors: list[str] = []

    # The authoritative implementation is a single function in notes/store.py.
    writer_path = BACKEND / "notes" / "store.py"
    writer_tree = parse(writer_path)
    writer_defs = [
        node
        for node in ast.walk(writer_tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "write_document"
    ]
    if len(writer_defs) != 1:
        errors.append(
            f"{writer_path.relative_to(ROOT)} must define exactly one write_document; found {len(writer_defs)}"
        )

    # HTTP routes may read/shape documents, but writes must use an application service.
    api_root = BACKEND / "api" / "v1"
    for path in python_sources(api_root):
        try:
            tree = parse(path)
        except SyntaxError as exc:
            errors.append(f"{path.relative_to(ROOT)} cannot be parsed: {exc}")
            continue
        if imports_or_calls_document_writer(tree):
            errors.append(
                f"{path.relative_to(ROOT)} imports/calls write_document directly; route writes must go through a service"
            )

    changed = changed_paths(args.base_ref)
    if changed is None:
        print("[architecture] No base ref supplied; changed-file-only rules were not evaluated.")
    elif changed:
        # Newly changed application services must stay independent from FastAPI.
        for relative in sorted(changed):
            if relative.parts[:4] == ("apps", "backend", "app", "services") and relative.suffix == ".py":
                path = ROOT / relative
                if path.exists() and imports_fastapi(parse(path)):
                    errors.append(
                        f"{relative} imports FastAPI; services must use framework-independent application errors"
                    )

            # Preserve these import-compatibility aggregators as routing shells.
            if relative in AGGREGATE_ROUTES:
                path = ROOT / relative
                if path.exists() and adds_registered_endpoint(parse(path)):
                    errors.append(
                        f"{relative} registers an endpoint; add new routes in its dedicated route module"
                    )

            # Page components use domain API modules rather than raw HTTP calls.
            if relative.parts[:4] == ("apps", "web", "src", "pages") and relative.suffix in {".ts", ".tsx", ".js", ".jsx"}:
                path = ROOT / relative
                if path.exists() and re.search(r"\bfetch\s*\(", path.read_text(encoding="utf-8")):
                    errors.append(f"{relative} calls fetch directly; page requests must use the api/ modules")
    else:
        print("[architecture] No changed files found against the supplied base ref.")

    if errors:
        print("Architecture boundary check failed:")
        for error in errors:
            print(f"- {error}")
        return 1

    print("Architecture boundary check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
