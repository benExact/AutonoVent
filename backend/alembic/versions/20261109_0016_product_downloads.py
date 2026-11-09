"""Optional product download metadata. Existing products stay without a file."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261109_0016"
down_revision: str | None = "20261107_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("download_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("products", sa.Column("download_stored_name", sa.String(length=64), nullable=True))
    op.add_column("products", sa.Column("download_original_name", sa.String(length=160), nullable=True))
    op.add_column("products", sa.Column("download_button_label", sa.String(length=80), nullable=True))
    op.add_column("products", sa.Column("download_content_type", sa.String(length=120), nullable=True))
    op.add_column("products", sa.Column("download_size_bytes", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "ck_products_download_has_file",
        "products",
        "download_enabled = false OR download_stored_name IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_products_download_has_file", "products", type_="check")
    op.drop_column("products", "download_size_bytes")
    op.drop_column("products", "download_content_type")
    op.drop_column("products", "download_button_label")
    op.drop_column("products", "download_original_name")
    op.drop_column("products", "download_stored_name")
    op.drop_column("products", "download_enabled")
