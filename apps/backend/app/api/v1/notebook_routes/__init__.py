"""Notebook 路由包：按业务群拆分的薄聚合入口。

注册顺序固定为 生命周期 → 文档 → 历史 → 资源 → 建议 → 关系 → 阅读位置；
聚合后由 api/v1/routes.py 只 include 一次，路径与状态码保持不变。
"""
from __future__ import annotations

from fastapi import APIRouter

from . import documents, lifecycle, reading_position, relations, resources, revisions, suggestions

router = APIRouter()
router.include_router(lifecycle.router)
router.include_router(documents.router)
router.include_router(revisions.router)
router.include_router(resources.router)
router.include_router(suggestions.router)
router.include_router(relations.router)
router.include_router(reading_position.router)

__all__ = [
    "documents",
    "lifecycle",
    "reading_position",
    "relations",
    "resources",
    "revisions",
    "router",
    "suggestions",
]
