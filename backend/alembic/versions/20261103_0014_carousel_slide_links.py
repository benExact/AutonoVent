"""Remove carousel button and destination link."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261103_0014"
down_revision: str | None = "20261103_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("carousel_slides", "button_label")
    op.drop_column("carousel_slides", "destination_url")


def downgrade() -> None:
    op.add_column("carousel_slides", sa.Column("button_label", sa.String(40), nullable=True))
    op.add_column("carousel_slides", sa.Column("destination_url", sa.String(500), nullable=True))
