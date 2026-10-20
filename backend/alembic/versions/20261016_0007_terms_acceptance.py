"""Record the terms version accepted with an order."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261016_0007"
down_revision: str | None = "20261016_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("terms_accepted", sa.Boolean(), nullable=True))
    op.add_column("orders", sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("orders", sa.Column("terms_version", sa.String(length=40), nullable=True))
    op.create_check_constraint(
        "ck_orders_terms_acceptance",
        "orders",
        "(terms_accepted IS NULL AND terms_accepted_at IS NULL AND terms_version IS NULL) OR (terms_accepted = true AND terms_accepted_at IS NOT NULL AND terms_version IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_orders_terms_acceptance", "orders", type_="check")
    op.drop_column("orders", "terms_version")
    op.drop_column("orders", "terms_accepted_at")
    op.drop_column("orders", "terms_accepted")
