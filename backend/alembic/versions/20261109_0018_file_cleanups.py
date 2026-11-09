"""Durable list of product files to remove after a permanent product delete.

Adds one table. No existing row is changed.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261109_0018"
down_revision: str | None = "20261109_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "file_cleanups",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("storage", sa.String(length=32), nullable=False),
        sa.Column("stored_name", sa.String(length=160), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=240), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("storage", "stored_name", name="uq_file_cleanups_storage_name"),
    )


def downgrade() -> None:
    op.drop_table("file_cleanups")
