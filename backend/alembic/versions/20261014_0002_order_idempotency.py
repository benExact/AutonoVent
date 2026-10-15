"""Store an idempotency key with each order. No commercial data is inserted."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261014_0002"
down_revision: str | None = "20261014_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("idempotency_key", sa.String(length=80), nullable=True))
    op.add_column("orders", sa.Column("idempotency_fingerprint", sa.String(length=64), nullable=True))
    op.create_unique_constraint("uq_orders_idempotency_key", "orders", ["idempotency_key"])
    op.create_check_constraint(
        "ck_orders_idempotency_pair",
        "orders",
        "(idempotency_key IS NULL AND idempotency_fingerprint IS NULL) OR (idempotency_key IS NOT NULL AND idempotency_fingerprint IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_orders_idempotency_pair", "orders", type_="check")
    op.drop_constraint("uq_orders_idempotency_key", "orders", type_="unique")
    op.drop_column("orders", "idempotency_fingerprint")
    op.drop_column("orders", "idempotency_key")
