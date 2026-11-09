"""Stored files waiting to be removed after their product was permanently deleted."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class FileCleanup(Base):
    """One file to remove. product_id has no foreign key because the product row is already gone."""

    __tablename__ = "file_cleanups"
    __table_args__ = (UniqueConstraint("storage", "stored_name", name="uq_file_cleanups_storage_name"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    storage: Mapped[str] = mapped_column(String(32), nullable=False)
    stored_name: Mapped[str] = mapped_column(String(160), nullable=False)
    product_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(240))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
