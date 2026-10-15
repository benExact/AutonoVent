"""Widen status-event actor so an owner email fits. No commercial data is inserted."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261015_0002"
down_revision: str | None = "20261015_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "order_status_events",
        "actor",
        existing_type=sa.String(length=160),
        type_=sa.String(length=254),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "order_status_events",
        "actor",
        existing_type=sa.String(length=254),
        type_=sa.String(length=160),
        existing_nullable=True,
    )
