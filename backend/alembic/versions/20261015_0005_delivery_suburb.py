"""Record the delivery suburb and whether an item used the development test price."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261015_0005"
down_revision: str | None = "20261015_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("delivery_suburb", sa.String(length=120), nullable=True))
    op.add_column(
        "order_items",
        sa.Column("price_is_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )


def downgrade() -> None:
    op.drop_column("order_items", "price_is_demo")
    op.drop_column("orders", "delivery_suburb")
