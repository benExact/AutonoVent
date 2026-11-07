"""Add gallery images, specifications, stock, and previous slugs. Existing products stay."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261107_0015"
down_revision: str | None = "20261103_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("short_description", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("in_stock", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.create_table(
        "product_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stored_name", sa.String(160), nullable=False),
        sa.Column("thumb_name", sa.String(160), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("stored_name", name="uq_product_images_stored_name"),
    )
    op.create_index("ix_product_images_product_id", "product_images", ["product_id"])
    op.create_table(
        "product_specifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("value", sa.String(200), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_product_specifications_product_id", "product_specifications", ["product_id"])
    op.create_table(
        "product_slug_aliases",
        sa.Column("slug", sa.String(80), primary_key=True, nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="CASCADE"), nullable=False),
    )
    op.execute(
        """
        INSERT INTO product_images (id, product_id, stored_name, thumb_name, position, created_at)
        SELECT gen_random_uuid(), id, image_filename, NULL, 0, now()
        FROM products
        WHERE image_filename IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_table("product_slug_aliases")
    op.drop_index("ix_product_specifications_product_id", table_name="product_specifications")
    op.drop_table("product_specifications")
    op.drop_index("ix_product_images_product_id", table_name="product_images")
    op.drop_table("product_images")
    op.drop_column("products", "in_stock")
    op.drop_column("products", "short_description")
