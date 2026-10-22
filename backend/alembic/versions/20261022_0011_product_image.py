"""One optional image filename per product. Existing prices and rows stay in place."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261022_0011"
down_revision: str | None = "20261020_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("image_filename", sa.String(length=64), nullable=True))
    op.drop_constraint("ck_products_price_nonnegative", "products", type_="check")
    op.create_check_constraint(
        "ck_products_price_positive",
        "products",
        "unit_price_cents IS NULL OR unit_price_cents > 0",
    )


def downgrade() -> None:
    op.drop_constraint("ck_products_price_positive", "products", type_="check")
    op.create_check_constraint(
        "ck_products_price_nonnegative",
        "products",
        "unit_price_cents IS NULL OR unit_price_cents >= 0",
    )
    op.drop_column("products", "image_filename")
