"""Add INACTIVE status value to conversationstatus enum

The initial migration created the `conversationstatus` enum with only
WAITING, ACTIVE, ENDED and DELETED. The application now relies on an
INACTIVE state (set when the last participant leaves), so the enum type
must be extended before any row can transition to that state.

Revision ID: d4f9c2e1a7b3
Revises: 261560cee1a4
Create Date: 2026-09-14 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd4f9c2e1a7b3'
down_revision: Union[str, Sequence[str], None] = '261560cee1a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # `ALTER TYPE ... ADD VALUE` runs inside Alembic's transaction; on
    # PostgreSQL 12+ this is allowed as long as the new value is not
    # referenced within the same transaction (it isn't).
    op.execute("ALTER TYPE conversationstatus ADD VALUE 'INACTIVE'")


def downgrade() -> None:
    """Downgrade schema."""
    # PostgreSQL does not support removing a single enum value. Doing so
    # would require recreating the type, which is destructive; leave the
    # column in place as a no-op.
    pass