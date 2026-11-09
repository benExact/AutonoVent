"""Sellable products. Price and SKU stay unset until they are confirmed."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("unit_price_cents IS NULL OR unit_price_cents > 0", name="ck_products_price_positive"),
        CheckConstraint(
            "specification_enabled = false OR active = false OR specification_stored_name IS NOT NULL",
            name="ck_products_published_specification_has_file",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sku: Mapped[str | None] = mapped_column(String(64), unique=True)
    unit_price_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="ZAR", server_default="ZAR")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    image_filename: Mapped[str | None] = mapped_column(String(64))
    short_description: Mapped[str | None] = mapped_column(Text)
    in_stock: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    specification_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    specification_stored_name: Mapped[str | None] = mapped_column(String(64))
    specification_original_name: Mapped[str | None] = mapped_column(String(160))
    specification_content_type: Mapped[str | None] = mapped_column(String(120))
    specification_size_bytes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ProductImage(Base):
    """A gallery file stored on disk. The database keeps the relative name only."""

    __tablename__ = "product_images"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(160), nullable=False)
    thumb_name: Mapped[str | None] = mapped_column(String(160))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProductSpecification(Base):
    __tablename__ = "product_specifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    label: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class ProductSlugAlias(Base):
    """Previous public slug. The product id does not change."""

    __tablename__ = "product_slug_aliases"

    slug: Mapped[str] = mapped_column(String(80), primary_key=True)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
