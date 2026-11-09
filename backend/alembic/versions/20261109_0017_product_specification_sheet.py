"""One optional PDF specification sheet per product.

Renames the generic download columns so existing values are kept. A sheet that
is not a PDF stays recorded but is no longer offered publicly. The unused
download_button_label column is left in place so no saved value is dropped.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261109_0017"
down_revision: str | None = "20261109_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RENAMES = (
    ("download_enabled", "specification_enabled"),
    ("download_stored_name", "specification_stored_name"),
    ("download_original_name", "specification_original_name"),
    ("download_content_type", "specification_content_type"),
    ("download_size_bytes", "specification_size_bytes"),
)


def upgrade() -> None:
    op.drop_constraint("ck_products_download_has_file", "products", type_="check")
    for old, new in RENAMES:
        op.alter_column("products", old, new_column_name=new)
    op.execute(
        sa.text(
            "UPDATE products SET specification_enabled = false "
            "WHERE specification_stored_name IS NOT NULL AND specification_stored_name NOT LIKE '%.pdf'"
        )
    )
    op.create_check_constraint(
        "ck_products_published_specification_has_file",
        "products",
        "specification_enabled = false OR active = false OR specification_stored_name IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_products_published_specification_has_file", "products", type_="check")
    op.execute(sa.text("UPDATE products SET specification_enabled = false WHERE specification_stored_name IS NULL"))
    for old, new in RENAMES:
        op.alter_column("products", new, new_column_name=old)
    op.create_check_constraint(
        "ck_products_download_has_file",
        "products",
        "download_enabled = false OR download_stored_name IS NOT NULL",
    )
