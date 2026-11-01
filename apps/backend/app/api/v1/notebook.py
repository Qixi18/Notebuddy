"""Notebook API 聚合入口。

实现已按业务群拆到 ``app.api.v1.notebook_routes``；本模块保留原有导入路径，
把 ``router`` 与路由函数名重新导出，外部（含测试）引用方式不变。
"""
from __future__ import annotations

from app.api.v1.notebook_routes import router

# documents
from app.api.v1.notebook_routes.documents import (  # noqa: F401
    get_block_sources,
    get_notebook_document,
    get_notebook_sections,
    get_unbound_document,
    put_notebook_document,
    put_unbound_document,
)

# lifecycle
from app.api.v1.notebook_routes.lifecycle import (  # noqa: F401
    bind_notebook,
    bulk_manage_notebooks,
    create_notebook,
    create_unbound_notebook,
    delete_course_notebook,
    delete_unbound_notebook,
    get_named_notebook,
    get_notebook,
    get_unbound_notebook,
    list_deleted_notebooks,
    list_notebooks,
    list_unbound_notebooks,
    move_notebook,
    purge_deleted_notebook,
    rename_notebook,
    rename_unbound_notebook,
    reorder_named_notebook,
    reorder_notebook,
    restore_deleted_notebook,
    unbind_notebook,
)

# reading_position
from app.api.v1.notebook_routes.reading_position import (  # noqa: F401
    get_position,
    put_position,
)

# relations
from app.api.v1.notebook_routes.relations import (  # noqa: F401
    create_notebook_relation,
    delete_notebook_relation,
    list_notebook_relations,
)

# resources
from app.api.v1.notebook_routes.resources import (  # noqa: F401
    delete_notebook_cover,
    get_asset_content,
    get_notebook_attachment,
    get_notebook_cover,
    upload_notebook_attachment,
    upload_notebook_cover,
    upload_unbound_notebook_attachment,
)

# revisions
from app.api.v1.notebook_routes.revisions import (  # noqa: F401
    list_notebook_revisions,
    list_unbound_revisions,
    read_notebook_revision,
    read_unbound_revision,
    restore_notebook_revision,
    restore_unbound_revision,
)

# suggestions
from app.api.v1.notebook_routes.suggestions import (  # noqa: F401
    apply_course_edit_suggestions,
    list_course_edit_suggestions,
    list_edit_suggestions,
    review_edit_suggestion,
)

__all__ = ["router"]
