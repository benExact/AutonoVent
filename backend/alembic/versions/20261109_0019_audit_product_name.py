"""Keep a product name on each audit event so history survives product deletion.

Existing events are copied from the product row. No audit event is deleted.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261109_0019"
down_revision: str | None = "20261109_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("product_audit_events", sa.Column("product_name", sa.String(length=160), nullable=True))
    op.execute(
        """
        UPDATE product_audit_events AS event
        SET product_name = product.name
        FROM products AS product
        WHERE event.product_id = product.id
        """
    )
    op.execute("UPDATE product_audit_events SET product_name = 'Deleted product' WHERE product_name IS NULL")
    op.alter_column("product_audit_events", "product_name", nullable=False)
    op.drop_constraint("product_audit_events_product_id_fkey", "product_audit_events", type_="foreignkey")
    op.alter_column("product_audit_events", "product_id", nullable=True)
    op.create_foreign_key(
        "product_audit_events_product_id_fkey",
        "product_audit_events",
        "products",
        ["product_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_product_audit_events_actor", "product_audit_events", ["actor"])
    op.create_index("ix_product_audit_events_product_name", "product_audit_events", ["product_name"])
    op.create_index("ix_product_audit_events_created_id", "product_audit_events", ["created_at", "id"])


def downgrade() -> None:
    op.drop_index("ix_product_audit_events_created_id", table_name="product_audit_events")
    op.drop_index("ix_product_audit_events_product_name", table_name="product_audit_events")
    op.drop_index("ix_product_audit_events_actor", table_name="product_audit_events")
    op.execute("DELETE FROM product_audit_events WHERE product_id IS NULL")
    op.drop_constraint("product_audit_events_product_id_fkey", "product_audit_events", type_="foreignkey")
    op.alter_column("product_audit_events", "product_id", nullable=False)
    op.create_foreign_key(
        "product_audit_events_product_id_fkey",
        "product_audit_events",
        "products",
        ["product_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_column("product_audit_events", "product_name")
