"""add status column to songs table

Revision ID: 4a094f27bb65
Revises: 7d952c1de7c5
Create Date: 2026-05-11 08:35:55.523387

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4a094f27bb65'
down_revision: Union[str, Sequence[str], None] = '7d952c1de7c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # SQLite doesn't support adding NOT NULL columns without a default.
    # Use server_default so SQLite applies it to existing rows during ALTER.
    op.add_column('songs', sa.Column('status', sa.String(length=16), nullable=False, server_default='pending'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('songs', 'status')
