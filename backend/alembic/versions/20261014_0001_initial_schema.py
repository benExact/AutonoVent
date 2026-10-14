"""Initial commerce schema. No product price, SKU, or parcel data is inserted."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261014_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("slug", sa.String(80), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("sku", sa.String(64)),
        sa.Column("unit_price_cents", sa.Integer()),
        sa.Column("currency", sa.String(3), nullable=False, server_default="ZAR"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("unit_price_cents IS NULL OR unit_price_cents >= 0", name="ck_products_price_nonnegative"),
        sa.UniqueConstraint("slug", name="uq_products_slug"),
        sa.UniqueConstraint("sku", name="uq_products_sku"),
    )
    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("order_number", sa.String(40), nullable=False),
        sa.Column("customer_name", sa.String(160), nullable=False),
        sa.Column("customer_email", sa.String(254), nullable=False),
        sa.Column("customer_phone", sa.String(40)),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("subtotal_cents", sa.Integer(), nullable=False),
        sa.Column("shipping_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cents", sa.Integer(), nullable=False),
        sa.Column("payment_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("fulfilment_status", sa.String(32), nullable=False, server_default="unfulfilled"),
        sa.Column("delivery_name", sa.String(160)),
        sa.Column("delivery_line1", sa.String(200)),
        sa.Column("delivery_line2", sa.String(200)),
        sa.Column("delivery_city", sa.String(120)),
        sa.Column("delivery_region", sa.String(120)),
        sa.Column("delivery_postal_code", sa.String(20)),
        sa.Column("delivery_country", sa.String(2)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("subtotal_cents >= 0", name="ck_orders_subtotal_nonnegative"),
        sa.CheckConstraint("shipping_cents >= 0", name="ck_orders_shipping_nonnegative"),
        sa.CheckConstraint("total_cents >= 0", name="ck_orders_total_nonnegative"),
        sa.CheckConstraint("total_cents = subtotal_cents + shipping_cents", name="ck_orders_total_matches_parts"),
        sa.CheckConstraint("payment_status IN ('pending', 'paid', 'failed', 'cancelled')", name="ck_orders_payment_status"),
        sa.CheckConstraint(
            "fulfilment_status IN ('unfulfilled', 'processing', 'shipped', 'delivered', 'cancelled')",
            name="ck_orders_fulfilment_status",
        ),
        sa.UniqueConstraint("order_number", name="uq_orders_order_number"),
    )
    op.create_index("ix_orders_customer_email", "orders", ["customer_email"])
    op.create_index("ix_orders_payment_status", "orders", ["payment_status"])
    op.create_index("ix_orders_fulfilment_status", "orders", ["fulfilment_status"])
    op.create_index("ix_orders_created_at", "orders", ["created_at"])
    op.create_table(
        "order_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="SET NULL")),
        sa.Column("product_name", sa.String(160), nullable=False),
        sa.Column("sku", sa.String(64)),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price_cents", sa.Integer(), nullable=False),
        sa.Column("line_total_cents", sa.Integer(), nullable=False),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        sa.CheckConstraint("unit_price_cents >= 0", name="ck_order_items_price_nonnegative"),
        sa.CheckConstraint("line_total_cents = quantity * unit_price_cents", name="ck_order_items_line_total"),
    )
    op.create_index("ix_order_items_order_id", "order_items", ["order_id"])
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_reference", sa.String(128)),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("notification", postgresql.JSONB()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("amount_cents >= 0", name="ck_payments_amount_nonnegative"),
        sa.CheckConstraint("status IN ('initiated', 'pending', 'paid', 'failed', 'cancelled')", name="ck_payments_status"),
        sa.UniqueConstraint("provider", "provider_reference", name="uq_payments_provider_reference"),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"])
    op.create_table(
        "shipments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("provider", sa.String(32)),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("tracking_number", sa.String(80)),
        sa.Column("service_code", sa.String(80)),
        sa.Column("weight_grams", sa.Integer()),
        sa.Column("length_mm", sa.Integer()),
        sa.Column("width_mm", sa.Integer()),
        sa.Column("height_mm", sa.Integer()),
        sa.Column("collection_line1", sa.String(200)),
        sa.Column("collection_city", sa.String(120)),
        sa.Column("collection_postal_code", sa.String(20)),
        sa.Column("collection_country", sa.String(2)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint(
            "status IN ('pending', 'booked', 'in_transit', 'delivered', 'failed', 'cancelled')",
            name="ck_shipments_status",
        ),
        sa.CheckConstraint("weight_grams IS NULL OR weight_grams > 0", name="ck_shipments_weight"),
        sa.CheckConstraint("length_mm IS NULL OR length_mm > 0", name="ck_shipments_length"),
        sa.CheckConstraint("width_mm IS NULL OR width_mm > 0", name="ck_shipments_width"),
        sa.CheckConstraint("height_mm IS NULL OR height_mm > 0", name="ck_shipments_height"),
    )
    op.create_index("ix_shipments_order_id", "shipments", ["order_id"])
    op.create_index("ix_shipments_tracking_number", "shipments", ["tracking_number"])
    op.create_table(
        "order_status_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("field_name", sa.String(32), nullable=False),
        sa.Column("from_status", sa.String(32)),
        sa.Column("to_status", sa.String(32), nullable=False),
        sa.Column("note", sa.Text()),
        sa.Column("actor", sa.String(160)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("field_name IN ('payment_status', 'fulfilment_status')", name="ck_order_status_events_field"),
    )
    op.create_index("ix_order_status_events_order_id", "order_status_events", ["order_id"])
    op.create_index("ix_order_status_events_created_at", "order_status_events", ["created_at"])
    op.create_table(
        "admin_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="owner"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("disabled_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("role IN ('owner')", name="ck_admin_users_role"),
        sa.UniqueConstraint("email", name="uq_admin_users_email"),
    )


def downgrade() -> None:
    op.drop_table("admin_users")
    op.drop_table("order_status_events")
    op.drop_table("shipments")
    op.drop_table("payments")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_table("products")
