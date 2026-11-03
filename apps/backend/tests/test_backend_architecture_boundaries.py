"""Regression checks for the application boundaries introduced by this plan."""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
BACKEND = APP.parent


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(("." * node.level) + node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def _function_calls(path: Path, function_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name == function_name)
    return {
        node.func.attr for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def test_notebook_application_services_do_not_depend_on_http_or_request_schemas():
    modules = (
        "notebook_lifecycle.py", "notebook_resources.py", "notebook_suggestions.py",
        "generation_jobs.py", "notebook_relations.py", "asset_processing.py",
        "agent_execution.py", "notebook_generation_inputs.py", "asset_uploads.py",
        "deletion.py",
    )
    for name in modules:
        imported = _imports(APP / "services" / name)
        assert not any(module == "fastapi" or module.startswith("fastapi.")
                       for module in imported), name
        assert not any(module.startswith(("app.api", "app.schemas"))
                       for module in imported), name


def test_refactored_write_routes_delegate_transaction_boundaries():
    cases = {
        APP / "api/v1/notebook_routes/relations.py": (
            "create_notebook_relation", "delete_notebook_relation",
        ),
        APP / "api/v1/forest.py": ("create_relation", "refresh_relation", "delete_relation"),
        APP / "api/v1/generation.py": ("retry_generation_job", "cancel_generation_job"),
        APP / "api/v1/materials.py": (
            "retry_material", "reparse_material", "request_material_ocr",
            "switch_asset_processing_route",
        ),
        APP / "api/v1/material_routes/processing.py": (
            "switch_asset_processing_route_route", "cancel_asset_processing_route",
            "retry_asset_parse_route", "retry_material", "reparse_material_route",
            "request_material_ocr_route",
        ),
        APP / "api/v1/material_routes/uploads.py": (
            "upload_notebook_asset_route", "complete_notebook_upload_batch",
            "upload_material_route", "upload_notebook_file_route",
        ),
        APP / "api/v1/material_routes/assets.py": (
            "restore_notebook_asset", "mark_asset_inline", "delete_notebook_asset",
        ),
        APP / "api/v1/material_routes/materials.py": (
            "restore_material", "delete_material",
        ),
        APP / "api/v1/agent.py": ("send_agent_message",),
    }
    for path, functions in cases.items():
        for name in functions:
            calls = _function_calls(path, name)
            assert "commit" not in calls and "rollback" not in calls, f"{path.name}:{name}"


def test_document_processing_service_uses_config_compatibility_shim_only():
    service_imports = _imports(APP / "document_processing/service.py")
    assert "app.document_processing.routes" not in service_imports
    for path in (APP / "document_processing").rglob("*.py"):
        if path.name == "routes.py":
            continue
        imports = _imports(path)
        assert "app.document_processing.routes" not in imports, path.relative_to(APP)


def test_inadvertent_zero_byte_web_files_stay_removed():
    for name in ("--run", "build", "run", "test"):
        path = BACKEND.parent / "web" / name
        assert not path.exists(), path
