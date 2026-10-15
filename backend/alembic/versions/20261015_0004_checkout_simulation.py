"""Store simulated delivery quotes and payment attempt keys. No commercial data is inserted."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261015_0004"
down_revision: str | None = "20261015_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("is_simulation", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("orders", sa.Column("shipping_provider", sa.String(length=32), nullable=True))
    op.add_column("orders", sa.Column("shipping_service_code", sa.String(length=32), nullable=True))
    op.add_column("orders", sa.Column("shipping_quote_reference", sa.String(length=80), nullable=True))
    op.create_check_constraint(
        "ck_orders_simulation_quote",
        "orders",
        "(is_simulation = false AND shipping_provider IS NULL AND shipping_service_code IS NULL AND shipping_quote_reference IS NULL) OR (is_simulation = true AND shipping_provider = 'simulated-courier' AND shipping_service_code IS NOT NULL AND shipping_quote_reference IS NOT NULL)",
    )
    op.add_column("payments", sa.Column("idempotency_key", sa.String(length=80), nullable=True))
    op.create_unique_constraint("uq_payments_idempotency_key", "payments", ["idempotency_key"])


def downgrade() -> None:
    op.drop_constraint("uq_payments_idempotency_key", "payments", type_="unique")
    op.drop_column("payments", "idempotency_key")
    op.drop_constraint("ck_orders_simulation_quote", "orders", type_="check")
    op.drop_column("orders", "shipping_quote_reference")
    op.drop_column("orders", "shipping_service_code")
    op.drop_column("orders", "shipping_provider")
    op.drop_column("orders", "is_simulation")
