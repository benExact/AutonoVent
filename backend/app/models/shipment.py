"""Fulfilment shipments. Parcel size and collection address stay unset until confirmed."""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'booked', 'in_transit', 'delivered', 'failed', 'cancelled')",
            name="ck_shipments_status",
        ),
        CheckConstraint("weight_grams IS NULL OR weight_grams > 0", name="ck_shipments_weight"),
        CheckConstraint("length_mm IS NULL OR length_mm > 0", name="ck_shipments_length"),
        CheckConstraint("width_mm IS NULL OR width_mm > 0", name="ck_shipments_width"),
        CheckConstraint("height_mm IS NULL OR height_mm > 0", name="ck_shipments_height"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", server_default="pending")
    tracking_number: Mapped[str | None] = mapped_column(String(80), index=True)
    service_code: Mapped[str | None] = mapped_column(String(80))
    weight_grams: Mapped[int | None] = mapped_column(Integer)
    length_mm: Mapped[int | None] = mapped_column(Integer)
    width_mm: Mapped[int | None] = mapped_column(Integer)
    height_mm: Mapped[int | None] = mapped_column(Integer)
    collection_line1: Mapped[str | None] = mapped_column(String(200))
    collection_city: Mapped[str | None] = mapped_column(String(120))
    collection_postal_code: Mapped[str | None] = mapped_column(String(20))
    collection_country: Mapped[str | None] = mapped_column(String(2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
