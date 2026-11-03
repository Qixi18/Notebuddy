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


def test_services_never_import_fastapi_or_http_exceptions():
    for path in (APP / "services").rglob("*.py"):
        imported = _imports(path)
        assert not any(module == "fastapi" or module.startswith("fastapi.")
                       for module in imported), path.relative_to(APP)


def test_business_route_queries_are_delegated_to_services():
    paths = (
        APP / "api/v1/notebook_routes/documents.py",
        APP / "api/v1/notebook_routes/revisions.py",
        APP / "api/v1/notebook_routes/lifecycle.py",
        APP / "api/v1/notebook_routes/resources.py",
        APP / "api/v1/material_routes/materials.py",
        APP / "api/v1/material_routes/assets.py",
        APP / "api/v1/material_routes/processing.py",
        APP / "api/v1/material_routes/uploads.py",
    )
    forbidden = {"query", "scalar", "scalars", "execute", "get", "commit", "rollback"}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = [node.func.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr in forbidden
                 and isinstance(node.func.value, ast.Name)
                 and node.func.value.id == "db"]
        assert calls == [], f"{path.relative_to(APP)} still accesses the database: {calls}"


def test_conversation_router_delegates_answer_pipeline_and_persistence():
    path = APP / "api/v1/conversations.py"
    imports = _imports(path)
    assert not any(module.startswith("app.ai") for module in imports)
    assert "app.api.v1.shared" not in imports
    for function in ("list_messages", "send_message"):
        calls = _function_calls(path, function)
        assert "commit" not in calls and "rollback" not in calls
    tree = ast.parse(path.read_text(encoding="utf-8"))
    send_message = next(node for node in tree.body
                        if isinstance(node, ast.FunctionDef) and node.name == "send_message")
    called_names = {node.func.id for node in ast.walk(send_message)
                    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert "send_conversation_message" in called_names
    assert "record_user_turn" not in called_names
    assert "idempotent_assistant_message" not in called_names


def test_forest_and_knowledge_business_routes_delegate_queries_and_transactions():
    strict_paths = (
        APP / "api/v1/forest.py",
        APP / "api/v1/forest_imports.py",
        APP / "api/v1/knowledge.py",
    )
    forbidden = {"query", "scalar", "scalars", "execute", "get", "add", "delete",
                 "commit", "rollback", "flush", "refresh"}
    for path in strict_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls = [node.func.attr for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and node.func.attr in forbidden and isinstance(node.func.value, ast.Name)
                 and node.func.value.id == "db"]
        assert calls == [], f"{path.relative_to(APP)} still owns ORM/transaction calls: {calls}"

    imports = _imports(APP / "api/v1/knowledge.py")
    assert "app.knowledge.proposals" not in imports


def test_courses_keep_simple_list_reads_but_delegate_aggregates_and_transactions():
    path = APP / "api/v1/courses.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for function in (
        "visit_course", "create_course", "rename_course", "course_overview",
        "preview_course_deletion", "delete_course", "restore_course", "purge_deleted_course",
    ):
        definition = next(node for node in tree.body
                          if isinstance(node, ast.FunctionDef) and node.name == function)
        calls = {node.func.attr for node in ast.walk(definition)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                 and isinstance(node.func.value, ast.Name) and node.func.value.id == "db"}
        assert not calls & {"commit", "rollback", "add", "delete", "flush", "refresh"}, function
    overview = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "course_overview")
    overview_db_calls = {node.func.attr for node in ast.walk(overview)
                         if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                         and isinstance(node.func.value, ast.Name) and node.func.value.id == "db"}
    assert not overview_db_calls & {"query", "scalar", "scalars", "execute", "get"}


def test_forest_domain_and_workers_do_not_depend_on_http_or_api_routers():
    paths = [*(APP / "forest").rglob("*.py"), *(APP / "knowledge").rglob("*.py"),
             *(APP / "workers").rglob("*.py")]
    for path in paths:
        imported = _imports(path)
        assert not any(module == "fastapi" or module.startswith("fastapi.")
                       for module in imported), path.relative_to(APP)
        assert not any(module == "app.api" or module.startswith("app.api.")
                       for module in imported), path.relative_to(APP)


def test_http_routes_do_not_remap_application_errors_individually():
    paths = [*(APP / "api/v1/notebook_routes").glob("*.py"),
             *(APP / "api/v1/material_routes").glob("*.py"),
             APP / "api/v1/shared.py"]
    for path in paths:
        imported = _imports(path)
        assert "app.services.errors" not in imported, path.relative_to(APP)
        text = path.read_text(encoding="utf-8")
        assert "except ApplicationError" not in text, path.relative_to(APP)


def test_material_compatibility_and_resource_routes_remain_registered():
    from app.main import app

    spec = app.openapi()["paths"]
    expected = {
        ("get", "/api/v1/courses/{course_id}/notebook-files"),
        ("get", "/api/v1/courses/{course_id}/deleted-materials"),
        ("get", "/api/v1/materials/{material_id}/deletion-preview"),
        ("delete", "/api/v1/materials/{material_id}"),
        ("post", "/api/v1/materials/{material_id}/restore"),
        ("get", "/api/v1/notebooks/{notebook_id}/files"),
        ("get", "/api/v1/materials/{material_id}/pages"),
        ("get", "/api/v1/materials/{material_id}/pages/{page_number}/evidence"),
        ("get", "/api/v1/materials/{material_id}/latest-job"),
        ("get", "/api/v1/courses/{course_id}/web-sources"),
        ("get", "/api/v1/materials/{material_id}/web-sources"),
        ("get", "/api/v1/notebooks/{notebook_id}/assets"),
        ("get", "/api/v1/notebooks/{notebook_id}/detached-assets"),
        ("get", "/api/v1/notebooks/{notebook_id}/assets/{asset_id}/processing-jobs"),
        ("get", "/api/v1/assets/{asset_id}/processing-budget"),
        ("get", "/api/v1/notebooks/{notebook_id}/upload-batches"),
        ("get", "/api/v1/notebooks/{notebook_id}/upload-batches/{batch_id}"),
        ("post", "/api/v1/notebooks/{notebook_id}/upload-batches/{batch_id}/complete"),
    }
    missing = sorted(item for item in expected
                     if item[1] not in spec or item[0] not in spec[item[1]])
    assert missing == [], f"兼容路由缺失：{missing}"
