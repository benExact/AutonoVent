"""Owner product edits. These shapes are not used by the public catalogue."""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.products.money import rands_to_cents

_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _clean_text(value: str | None, *, limit: int, label: str, required: bool) -> str | None:
    if value is None:
        if required:
            raise ValueError(f"A {label} is required.")
        return None
    cleaned = value.strip()
    if not cleaned:
        if required:
            raise ValueError(f"A {label} is required.")
        return None
    if len(cleaned) > limit:
        raise ValueError(f"The {label} is too long.")
    return cleaned


def storage_fields(model: BaseModel, *, exclude_unset: bool) -> dict[str, object]:
    data = model.model_dump(exclude_unset=exclude_unset, exclude={"price_rands"})
    price = getattr(model, "price_rands", None)
    if isinstance(price, str):
        data["unit_price_cents"] = rands_to_cents(price)
    return data


class ProductWrite(BaseModel):
    name: str = Field(max_length=160)
    slug: str = Field(max_length=80)
    description: str | None = Field(default=None, max_length=4000)
    sku: str | None = Field(default=None, max_length=64)
    unit_price_cents: int | None = Field(default=None, strict=True)
    price_rands: str | None = None
    currency: str = "ZAR"
    active: bool = Field(default=False, strict=True)

    @field_validator("name")
    @classmethod
    def name_required(cls, value: str) -> str:
        cleaned = _clean_text(value, limit=160, label="name", required=True)
        assert cleaned is not None
        return cleaned

    @field_validator("slug")
    @classmethod
    def slug_shape(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if not _SLUG.fullmatch(cleaned):
            raise ValueError("Use a slug made of lowercase letters, numbers, and hyphens.")
        return cleaned

    @field_validator("description", "sku")
    @classmethod
    def optional_text(cls, value: str | None, info) -> str | None:
        limit = 4000 if info.field_name == "description" else 64
        return _clean_text(value, limit=limit, label=info.field_name or "field", required=False)

    @field_validator("currency")
    @classmethod
    def zar_only(cls, value: str) -> str:
        if value.strip().upper() != "ZAR":
            raise ValueError("Currency must be ZAR.")
        return "ZAR"

    @field_validator("unit_price_cents")
    @classmethod
    def price_is_positive(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("Enter a selling price greater than R0.00.")
        return value

    @field_validator("price_rands")
    @classmethod
    def price_in_rands(cls, value: str | None) -> str | None:
        if value is None:
            return None
        rands_to_cents(value)
        return value.strip()

    def stored(self) -> dict[str, object]:
        return storage_fields(self, exclude_unset=False)


class ProductPatch(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    slug: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=4000)
    sku: str | None = Field(default=None, max_length=64)
    unit_price_cents: int | None = Field(default=None, strict=True)
    price_rands: str | None = None
    currency: str | None = None
    active: bool | None = Field(default=None, strict=True)

    @field_validator("name")
    @classmethod
    def name_required(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = _clean_text(value, limit=160, label="name", required=True)
        assert cleaned is not None
        return cleaned

    @field_validator("slug")
    @classmethod
    def slug_shape(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if not _SLUG.fullmatch(cleaned):
            raise ValueError("Use a slug made of lowercase letters, numbers, and hyphens.")
        return cleaned

    @field_validator("description", "sku")
    @classmethod
    def optional_text(cls, value: str | None, info) -> str | None:
        limit = 4000 if info.field_name == "description" else 64
        return _clean_text(value, limit=limit, label=info.field_name or "field", required=False)

    @field_validator("currency")
    @classmethod
    def zar_only(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value.strip().upper() != "ZAR":
            raise ValueError("Currency must be ZAR.")
        return "ZAR"

    @field_validator("unit_price_cents")
    @classmethod
    def price_is_positive(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("Enter a selling price greater than R0.00.")
        return value

    @field_validator("price_rands")
    @classmethod
    def price_in_rands(cls, value: str | None) -> str | None:
        if value is None:
            return None
        rands_to_cents(value)
        return value.strip()

    def stored(self) -> dict[str, object]:
        return storage_fields(self, exclude_unset=True)


class ManagedProduct(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    sku: str | None
    unit_price_cents: int | None
    currency: str
    active: bool
    image_url: str | None
    created_at: datetime
    updated_at: datetime


class ProductList(BaseModel):
    products: list[ManagedProduct]


class AuditChange(BaseModel):
    field: str
    previous: str | int | bool | None
    new: str | int | bool | None


class ProductAuditEventView(BaseModel):
    created_at: datetime
    actor: str
    changes: list[AuditChange]


class ProductAuditList(BaseModel):
    events: list[ProductAuditEventView]
