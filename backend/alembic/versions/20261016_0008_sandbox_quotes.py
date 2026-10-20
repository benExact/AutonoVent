"""Allow a Bob Go sandbox quote on a non-simulated order."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261016_0008"
down_revision: str | None = "20261016_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SIMULATION_ONLY = (
    "(is_simulation = false AND shipping_provider IS NULL AND shipping_service_code IS NULL AND shipping_quote_reference IS NULL) "
    "OR (is_simulation = true AND shipping_provider = 'simulated-courier' AND shipping_service_code IS NOT NULL AND shipping_quote_reference IS NOT NULL)"
)
_WITH_BOBGO = (
    _SIMULATION_ONLY
    + " OR (is_simulation = false AND shipping_provider = 'bobgo' AND shipping_service_code IS NOT NULL AND shipping_quote_reference IS NOT NULL)"
)


def upgrade() -> None:
    op.alter_column("orders", "shipping_service_code", existing_type=sa.String(length=32), type_=sa.String(length=80), existing_nullable=True)
    op.alter_column("orders", "shipping_quote_reference", existing_type=sa.String(length=80), type_=sa.String(length=120), existing_nullable=True)
    op.drop_constraint("ck_orders_simulation_quote", "orders", type_="check")
    op.create_check_constraint("ck_orders_simulation_quote", "orders", _WITH_BOBGO)


def downgrade() -> None:
    op.drop_constraint("ck_orders_simulation_quote", "orders", type_="check")
    op.create_check_constraint("ck_orders_simulation_quote", "orders", _SIMULATION_ONLY)
    op.alter_column("orders", "shipping_quote_reference", existing_type=sa.String(length=120), type_=sa.String(length=80), existing_nullable=True)
    op.alter_column("orders", "shipping_service_code", existing_type=sa.String(length=80), type_=sa.String(length=32), existing_nullable=True)
