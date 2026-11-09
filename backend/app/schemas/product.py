"""Public catalogue shapes. Administrative columns are not included."""

import uuid

from pydantic import BaseModel, ConfigDict


class PublicImage(BaseModel):
    url: str
    thumb_url: str | None = None
    position: int


class PublicSpecification(BaseModel):
    label: str
    value: str


class PublicProduct(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    name: str
    description: str | None
    short_description: str | None = None
    sku: str | None
    unit_price_cents: int
    currency: str
    active: bool
    in_stock: bool = True
    price_is_demo: bool = False
    image_url: str | None = None
    images: list[PublicImage] = []
    specifications: list[PublicSpecification] = []
    download_enabled: bool = False
    download_label: str | None = None
    download_filename: str | None = None
    download_size_bytes: int | None = None


class CatalogueResponse(BaseModel):
    products: list[PublicProduct]
