"""merge main notebook-generation and agent-dialogue review heads

Revision ID: 78fabfb3dcb4
Revises: 9a4b7c2d1e60, e7c4d8f2a6b0
Create Date: 2026-10-27 14:12:01.640321

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '78fabfb3dcb4'
down_revision: Union[str, Sequence[str], None] = ('9a4b7c2d1e60', 'e7c4d8f2a6b0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
