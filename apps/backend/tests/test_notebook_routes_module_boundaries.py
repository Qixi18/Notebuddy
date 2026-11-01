"""ARC-03：Notebook 路由包的模块边界。

拆分后的硬约束：
- 路由包不得反向 import API 聚合入口（只允许自上而下：routes → notebook_routes → services）；
- 每个 (method, path) 只注册一次，固定路径不被动态路径吞掉；
- `app/api/v1/notebook.py` 保持薄聚合：只做 include + 重新导出。
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.main import app

ROUTES_DIR = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "notebook_routes"
AGGREGATOR = ROUTES_DIR.parent / "notebook.py"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(("." * (node.level or 0)) + node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_route_package_does_not_import_api_aggregators():
    forbidden = ("app.api.v1.notebook", "app.api.v1.routes", "app.main")
    for file in ROUTES_DIR.glob("*.py"):
        imported = _imports(file)
        for name in forbidden:
            assert name not in imported, f"{file.name} 不得反向依赖 {name}"


def test_aggregator_stays_thin():
    text = AGGREGATOR.read_text(encoding="utf-8")
    # 只允许：模块 docstring、import、__all__；不出现路由装饰器或业务函数定义
    assert "@router." not in text
    assert "\ndef " not in text
    assert "include_router" not in text  # include 统一放在 notebook_routes/__init__.py


def test_each_route_is_registered_once():
    seen: dict[tuple[str, str], int] = {}
    for route in app.routes:
        path = getattr(route, "path", "")
        methods = getattr(route, "methods", None) or set()
        # 新版 FastAPI 用 _IncludedRouter 惰性挂载，逐个展开其原始路由
        inner = getattr(route, "original_router", None)
        if inner is not None:
            for child in inner.routes:
                child_path = getattr(child, "path", "")
                for method in (getattr(child, "methods", None) or set()) - {"HEAD", "OPTIONS"}:
                    key = (method, child_path)
                    seen[key] = seen.get(key, 0) + 1
            continue
        for method in methods - {"HEAD", "OPTIONS"}:
            key = (method, path)
            seen[key] = seen.get(key, 0) + 1
    duplicates = {key: count for key, count in seen.items() if count > 1}
    assert duplicates == {}, f"重复注册的路由：{duplicates}"


def test_notebook_group_files_exist():
    for name in ("common", "lifecycle", "documents", "revisions", "resources",
                 "suggestions", "relations", "reading_position"):
        assert (ROUTES_DIR / f"{name}.py").is_file(), f"缺少 {name}.py"
