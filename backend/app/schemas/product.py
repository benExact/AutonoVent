"""Public catalogue shapes. Administrative columns are not included."""

import uuid

from pydantic import BaseModel, ConfigDict


class PublicProduct(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    sku: str | None
    unit_price_cents: int
    currency: str
    active: bool


class CatalogueResponse(BaseModel):
    products: list[PublicProduct]
