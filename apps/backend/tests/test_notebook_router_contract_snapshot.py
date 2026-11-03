"""ARC-01：Notebook 路由契约快照（拆分前后必须完全一致）。

冻结的是「方法 + 路径 + 状态码集合」。业务分组（notebook_routes/*）可以继续调整，
但任何路径改名、方法增删、状态码漂移都会在这里立刻失败。这份快照在拆分前生成，
拆分后必须原样通过。
"""

from __future__ import annotations

from app.main import app

# (method, path, 状态码集合)
CONTRACT: list[tuple[str, str, str]] = [
    ('GET', '/api/v1/assets/{asset_id}/content', '200,422'),
    ('GET', '/api/v1/courses/{course_id}/notebook', '200,422'),
    ('GET', '/api/v1/courses/{course_id}/notebook-edit-suggestions', '200,422'),
    ('POST', '/api/v1/courses/{course_id}/notebook-edit-suggestions/apply-all', '200,422'),
    ('GET', '/api/v1/courses/{course_id}/notebook-files', '200,422'),
    ('PATCH', '/api/v1/courses/{course_id}/notebook/order', '200,422'),
    ('GET', '/api/v1/courses/{course_id}/notebooks', '200,422'),
    ('POST', '/api/v1/courses/{course_id}/notebooks', '201,422'),
    ('DELETE', '/api/v1/courses/{course_id}/notebooks/{notebook_id}', '204,422'),
    ('GET', '/api/v1/courses/{course_id}/notebooks/{notebook_id}', '200,422'),
    ('PATCH', '/api/v1/courses/{course_id}/notebooks/{notebook_id}', '200,422'),
    ('POST', '/api/v1/courses/{course_id}/notebooks/{notebook_id}/attachments', '201,422'),
    ('GET', '/api/v1/courses/{course_id}/notebooks/{notebook_id}/document', '200,422'),
    ('PUT', '/api/v1/courses/{course_id}/notebooks/{notebook_id}/document', '200,422'),
    ('PATCH', '/api/v1/courses/{course_id}/notebooks/{notebook_id}/order', '200,422'),
    ('GET', '/api/v1/courses/{course_id}/notebooks/{notebook_id}/reading-position', '200,422'),
    ('PUT', '/api/v1/courses/{course_id}/notebooks/{notebook_id}/reading-position', '200,422'),
    ('GET', '/api/v1/courses/{course_id}/notebooks/{notebook_id}/revisions', '200,422'),
    ('GET', '/api/v1/courses/{course_id}/notebooks/{notebook_id}/revisions/{revision}', '200,422'),
    ('POST', '/api/v1/courses/{course_id}/notebooks/{notebook_id}/revisions/{revision}/restore', '200,422'),
    ('GET', '/api/v1/courses/{course_id}/notebooks/{notebook_id}/sections', '200,422'),
    ('GET', '/api/v1/notebook-attachments/{attachment_id}', '200,422'),
    ('POST', '/api/v1/notebooks/bulk-manage', '200,422'),
    ('GET', '/api/v1/notebooks/deleted', '200'),
    ('GET', '/api/v1/notebooks/unbound', '200'),
    ('POST', '/api/v1/notebooks/unbound', '201,422'),
    ('DELETE', '/api/v1/notebooks/unbound/{notebook_id}', '204,422'),
    ('GET', '/api/v1/notebooks/unbound/{notebook_id}', '200,422'),
    ('PATCH', '/api/v1/notebooks/unbound/{notebook_id}', '200,422'),
    ('GET', '/api/v1/notebooks/unbound/{notebook_id}/document', '200,422'),
    ('PUT', '/api/v1/notebooks/unbound/{notebook_id}/document', '200,422'),
    ('GET', '/api/v1/notebooks/{notebook_id}/assets', '200,422'),
    ('POST', '/api/v1/notebooks/{notebook_id}/assets', '201,422'),
    ('DELETE', '/api/v1/notebooks/{notebook_id}/assets/{asset_id}', '200,422'),
    ('GET', '/api/v1/notebooks/{notebook_id}/assets/{asset_id}/content', '200,422'),
    ('POST', '/api/v1/notebooks/{notebook_id}/assets/{asset_id}/inline', '200,422'),
    ('GET', '/api/v1/notebooks/{notebook_id}/assets/{asset_id}/processing-jobs', '200,422'),
    ('POST', '/api/v1/notebooks/{notebook_id}/assets/{asset_id}/restore', '200,422'),
    ('POST', '/api/v1/notebooks/{notebook_id}/attachments', '201,422'),
    ('POST', '/api/v1/notebooks/{notebook_id}/bind', '200,422'),
    ('GET', '/api/v1/notebooks/{notebook_id}/blocks/{block_id}/sources', '200,422'),
    ('GET', '/api/v1/notebooks/{notebook_id}/conversations', '200,422'),
    ('POST', '/api/v1/notebooks/{notebook_id}/conversations', '201,422'),
    ('DELETE', '/api/v1/notebooks/{notebook_id}/cover', '204,422'),
    ('GET', '/api/v1/notebooks/{notebook_id}/cover', '200,422'),
    ('PUT', '/api/v1/notebooks/{notebook_id}/cover', '200,422'),
    ('GET', '/api/v1/notebooks/{notebook_id}/detached-assets', '200,422'),
    ('GET', '/api/v1/notebooks/{notebook_id}/edit-suggestions', '200,422'),
    ('POST', '/api/v1/notebooks/{notebook_id}/edit-suggestions/{suggestion_id}/review', '200,422'),
    ('GET', '/api/v1/notebooks/{notebook_id}/files', '200,422'),
    ('POST', '/api/v1/notebooks/{notebook_id}/files', '201,422'),
    ('GET', '/api/v1/notebooks/{notebook_id}/generation-jobs', '200,422'),
    ('POST', '/api/v1/notebooks/{notebook_id}/generation-jobs', '202,422'),
    ('GET', '/api/v1/notebooks/{notebook_id}/generation-jobs/{job_id}', '200,422'),
    ('POST', '/api/v1/notebooks/{notebook_id}/generation-jobs/{job_id}/cancel', '200,422'),
    ('POST', '/api/v1/notebooks/{notebook_id}/generation-jobs/{job_id}/retry', '202,422'),
    ('POST', '/api/v1/notebooks/{notebook_id}/move', '200,422'),
    ('DELETE', '/api/v1/notebooks/{notebook_id}/permanent', '204,422'),
    ('GET', '/api/v1/notebooks/{notebook_id}/relations', '200,422'),
    ('POST', '/api/v1/notebooks/{notebook_id}/relations', '201,422'),
    ('DELETE', '/api/v1/notebooks/{notebook_id}/relations/{relation_id}', '204,422'),
    ('POST', '/api/v1/notebooks/{notebook_id}/restore', '200,422'),
    ('GET', '/api/v1/notebooks/{notebook_id}/revisions', '200,422'),
    ('GET', '/api/v1/notebooks/{notebook_id}/revisions/{revision}', '200,422'),
    ('POST', '/api/v1/notebooks/{notebook_id}/revisions/{revision}/restore', '200,422'),
    ('POST', '/api/v1/notebooks/{notebook_id}/unbind', '200,422'),
    ('GET', '/api/v1/notebooks/{notebook_id}/upload-batches', '200,422'),
    ('GET', '/api/v1/notebooks/{notebook_id}/upload-batches/{batch_id}', '200,422'),
    ('POST', '/api/v1/notebooks/{notebook_id}/upload-batches/{batch_id}/complete', '200,422'),]


def _current_contract() -> set[tuple[str, str, str]]:
    spec = app.openapi()
    rows: set[tuple[str, str, str]] = set()
    for path, item in spec["paths"].items():
        if "notebook" not in path and path != "/api/v1/assets/{asset_id}/content":
            continue
        for method, operation in item.items():
            rows.add((method.upper(), path, ",".join(sorted(operation.get("responses", {}).keys()))))
    return rows


def test_notebook_route_contract_is_unchanged():
    expected = set(CONTRACT)
    current = _current_contract()
    assert current - expected == set(), f"新增了未登记的路由：{sorted(current - expected)}"
    assert expected - current == set(), f"路由被删除或状态码变化：{sorted(expected - current)}"


def test_fixed_paths_are_not_swallowed_by_dynamic_routes():
    """`/notebooks/unbound`、`/notebooks/deleted` 这类固定段不能被动态路径吞掉。"""

    spec = app.openapi()
    assert "/api/v1/notebooks/unbound" in spec["paths"]
    assert "/api/v1/notebooks/unbound/{notebook_id}" in spec["paths"]
    assert "/api/v1/notebooks/deleted" in spec["paths"]
    assert "get" in spec["paths"]["/api/v1/notebooks/unbound"]
    assert "get" in spec["paths"]["/api/v1/notebooks/deleted"]
