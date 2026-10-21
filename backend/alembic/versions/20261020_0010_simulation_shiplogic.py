"""Allow a ShipLogic sandbox quote on a simulated payment order."""

from collections.abc import Sequence

from alembic import op

revision: str = "20261020_0010"
down_revision: str | None = "20261020_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PREVIOUS = (
    "(is_simulation = false AND shipping_provider IS NULL AND shipping_service_code IS NULL AND shipping_quote_reference IS NULL) "
    "OR (is_simulation = true AND shipping_provider = 'simulated-courier' AND shipping_service_code IS NOT NULL AND shipping_quote_reference IS NOT NULL) "
    "OR (is_simulation = false AND shipping_provider = 'bobgo' AND shipping_service_code IS NOT NULL AND shipping_quote_reference IS NOT NULL) "
    "OR (is_simulation = false AND shipping_provider = 'shiplogic' AND shipping_service_code IS NOT NULL AND shipping_quote_reference IS NOT NULL)"
)
_WITH_SIMULATED_SHIPLOGIC = (
    _PREVIOUS
    + " OR (is_simulation = true AND shipping_provider = 'shiplogic' AND shipping_service_code IS NOT NULL AND shipping_quote_reference IS NOT NULL)"
)


def upgrade() -> None:
    op.drop_constraint("ck_orders_simulation_quote", "orders", type_="check")
    op.create_check_constraint("ck_orders_simulation_quote", "orders", _WITH_SIMULATED_SHIPLOGIC)


def downgrade() -> None:
    op.drop_constraint("ck_orders_simulation_quote", "orders", type_="check")
    op.create_check_constraint("ck_orders_simulation_quote", "orders", _PREVIOUS)
