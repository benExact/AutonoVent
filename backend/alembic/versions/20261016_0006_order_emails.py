"""Add the packed fulfilment step and the customer email notification queue."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261016_0006"
down_revision: str | None = "20261015_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_orders_fulfilment_status", "orders", type_="check")
    op.create_check_constraint(
        "ck_orders_fulfilment_status",
        "orders",
        "fulfilment_status IN ('unfulfilled', 'processing', 'packed', 'shipped', 'delivered', 'cancelled')",
    )
    op.create_table(
        "email_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("dedupe_key", sa.String(length=120), nullable=False),
        sa.Column("recipient", sa.String(length=254), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("text_body", sa.Text(), nullable=False),
        sa.Column("html_body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=300), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("provider_message_id", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'accepted', 'failed')", name="ck_email_notifications_status"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_email_notifications_attempts"),
        sa.CheckConstraint(
            "kind IN ('payment_confirmation', 'fulfilment_update')",
            name="ck_email_notifications_kind",
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key", name="uq_email_notifications_dedupe_key"),
    )
    op.create_index("ix_email_notifications_order_id", "email_notifications", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_email_notifications_order_id", table_name="email_notifications")
    op.drop_table("email_notifications")
    op.drop_constraint("ck_orders_fulfilment_status", "orders", type_="check")
    op.create_check_constraint(
        "ck_orders_fulfilment_status",
        "orders",
        "fulfilment_status IN ('unfulfilled', 'processing', 'shipped', 'delivered', 'cancelled')",
    )
