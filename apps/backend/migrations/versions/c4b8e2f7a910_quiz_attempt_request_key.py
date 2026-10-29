"""Add a per-request idempotency key to quiz attempts.

区分两件此前无法区分的事：
- 网络重试：同一次作答动作被重复发送，必须只落一行（严格 exactly-once）；
- 用户重新答题：即使选了同一个选项，也是一次新的作答，应当各自留痕。

``request_key`` 允许为空：NULL 在唯一索引里互不相同，所以不传键的旧客户端仍按
「最近一次答案相同即视为重试」的旧规则处理，不会被这次变更打断。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "c4b8e2f7a910"
down_revision = "e29a10c7f501"
branch_labels = None
depends_on = None


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("quiz_attempts"):
        return set()
    return {column["name"] for column in inspector.get_columns("quiz_attempts")}


def _indexes() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("quiz_attempts"):
        return set()
    return {index["name"] for index in inspector.get_indexes("quiz_attempts")}


def upgrade() -> None:
    if "request_key" not in _columns():
        op.add_column("quiz_attempts", sa.Column("request_key", sa.String(64), nullable=True))
    if "uq_quiz_attempts_item_request" not in _indexes():
        op.create_index(
            "uq_quiz_attempts_item_request", "quiz_attempts",
            ["item_id", "request_key"], unique=True,
        )


def downgrade() -> None:
    if "uq_quiz_attempts_item_request" in _indexes():
        op.drop_index("uq_quiz_attempts_item_request", table_name="quiz_attempts")
    if "request_key" in _columns():
        op.drop_column("quiz_attempts", "request_key")
