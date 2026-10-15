"""Product change history. No commercial data or secrets are inserted."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0003"
down_revision: str | None = "20261015_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "product_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("product_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("products.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor", sa.String(length=254), nullable=False),
        sa.Column("changes", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_product_audit_events_product_id", "product_audit_events", ["product_id"])
    op.create_index("ix_product_audit_events_created_at", "product_audit_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_product_audit_events_created_at", table_name="product_audit_events")
    op.drop_index("ix_product_audit_events_product_id", table_name="product_audit_events")
    op.drop_table("product_audit_events")
