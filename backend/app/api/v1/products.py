"""Read-only public catalogue. Prices come from PostgreSQL or the development test price."""

import logging
from collections.abc import Generator
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models.product import Product
from app.models.product import ProductImage, ProductSlugAlias, ProductSpecification
from app.products.gallery import images_by_product, specifications_by_product
from app.products.images import public_image_url
from app.products.specifications import PDF_TYPE, open_specification, public_specification_name, specification_directory
from app.schemas.product import (
    CatalogueResponse,
    PublicImage,
    PublicProduct,
    PublicSpecification,
    PublicSpecificationSheet,
)

router = APIRouter()
logger = logging.getLogger(__name__)


def get_catalogue_session() -> Generator[Session, None, None]:
    generator = get_session()
    try:
        session = next(generator)
    except RuntimeError as exc:
        if "DATABASE_URL" not in str(exc):
            raise
        raise HTTPException(status_code=503, detail="The catalogue is temporarily unavailable.") from None
    try:
        yield session
    finally:
        generator.close()


def _catalogue_settings() -> Settings | None:
    try:
        return get_settings()
    except ValidationError:
        return None


@router.get("/products", response_model=CatalogueResponse)
def list_products(session: Session = Depends(get_catalogue_session)) -> CatalogueResponse:
    settings = _catalogue_settings()
    demo_cents = None
    if settings is not None and settings.checkout_simulation_active:
        demo_cents = settings.checkout_simulation_demo_unit_price_cents
    statement = select(Product).where(Product.active.is_(True), Product.archived_at.is_(None))
    if demo_cents is None:
        statement = statement.where(Product.unit_price_cents.is_not(None))
    statement = statement.order_by(Product.name, Product.slug)
    try:
        rows = session.scalars(statement).all()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="The catalogue is temporarily unavailable.") from None
    gallery, details = _load_related(session, list(rows))
    products: list[PublicProduct] = []
    for row in rows:
        if row.unit_price_cents is not None:
            cents = row.unit_price_cents
            price_is_demo = False
        elif demo_cents is not None:
            cents = demo_cents
            price_is_demo = True
        else:
            continue
        images = gallery.get(row.id, [])
        specs = details.get(row.id, [])
        products.append(_public_product(row, cents, price_is_demo, images, specs))
    return CatalogueResponse(products=products)


def _load_related(session: Session, rows: list[Product]) -> tuple[dict, dict]:
    ids = [row.id for row in rows]
    return images_by_product(session, ids), specifications_by_product(session, ids)


def _public_images(rows: list[ProductImage]) -> list[PublicImage]:
    images: list[PublicImage] = []
    for row in rows:
        url = public_image_url(row.stored_name)
        if url is None:
            continue
        images.append(PublicImage(url=url, thumb_url=public_image_url(row.thumb_name), position=row.position))
    return images


def _card_image(images: list[PublicImage], legacy: str | None) -> str | None:
    if images:
        return images[0].thumb_url or images[0].url
    return public_image_url(legacy)


def _public_product(row: Product, cents: int, price_is_demo: bool, images: list[ProductImage], specs: list[ProductSpecification]) -> PublicProduct:
    public_images = _public_images(images)
    sheet_path = _sheet_path(row, _catalogue_settings())
    return PublicProduct(
        id=row.id,
        slug=row.slug,
        name=row.name,
        description=row.description,
        short_description=row.short_description,
        sku=row.sku,
        unit_price_cents=cents,
        currency=row.currency,
        active=row.active,
        in_stock=row.in_stock,
        price_is_demo=price_is_demo,
        image_url=_card_image(public_images, row.image_filename),
        images=public_images,
        specifications=[PublicSpecification(label=item.label, value=item.value) for item in specs],
        specification_enabled=sheet_path is not None,
        specification_sheet=_public_sheet(row, sheet_path),
    )


def _sheet_path(row: Product, settings: Settings | None) -> Path | None:
    if settings is None or not row.specification_enabled:
        return None
    path = open_specification(specification_directory(settings), row.specification_stored_name)
    if path is None and row.specification_stored_name:
        logger.warning("Specification sheet for product %s is enabled but the PDF is not available.", row.id)
    return path


def _public_sheet(row: Product, path: Path | None) -> PublicSpecificationSheet | None:
    if path is None:
        return None
    return PublicSpecificationSheet(
        filename=public_specification_name(row.specification_original_name),
        size_bytes=row.specification_size_bytes,
    )


@router.get("/products/{slug}/specification")
def product_specification_sheet(slug: str, session: Session = Depends(get_catalogue_session)) -> FileResponse:
    settings = _catalogue_settings()
    try:
        published = _published(_by_slug(session, slug), settings)
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="The catalogue is temporarily unavailable.") from None
    path = _sheet_path(published[0], settings) if published is not None else None
    if published is None or path is None:
        raise HTTPException(
            status_code=404,
            detail="The specification sheet is not available.",
            headers={"X-Robots-Tag": "noindex"},
        )
    filename = public_specification_name(published[0].specification_original_name)
    return FileResponse(
        path,
        media_type=PDF_TYPE,
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "X-Robots-Tag": "noindex",
        },
    )


def _by_slug(session: Session, slug: str) -> Product | None:
    cleaned = slug.strip().lower()
    row = session.scalar(select(Product).where(Product.slug == cleaned))
    if row is None:
        alias = session.get(ProductSlugAlias, cleaned)
        row = session.get(Product, alias.product_id) if alias is not None else None
    return row


def _published(row: Product | None, settings: Settings | None) -> tuple[Product, int, bool] | None:
    if row is None or not row.active or row.archived_at is not None:
        return None
    demo_cents = settings.checkout_simulation_demo_unit_price_cents if settings is not None and settings.checkout_simulation_active else None
    if row.unit_price_cents is not None:
        return row, row.unit_price_cents, False
    if demo_cents is not None:
        return row, demo_cents, True
    return None


@router.get("/products/{slug}/page", include_in_schema=False)
def product_page(slug: str, session: Session = Depends(get_catalogue_session)) -> Response:
    """Nginx asks this before serving /product/{slug}, so a missing product page answers 404."""
    try:
        published = _published(_by_slug(session, slug), _catalogue_settings())
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="The catalogue is temporarily unavailable.") from None
    if published is None:
        raise HTTPException(status_code=404, detail="The product is not available.", headers={"X-Robots-Tag": "noindex"})
    return Response(status_code=200, headers={"X-Accel-Redirect": "/_product_shell", "Cache-Control": "no-cache"})


@router.get("/products/{slug}", response_model=PublicProduct)
def product_by_slug(slug: str, response: Response, session: Session = Depends(get_catalogue_session)) -> PublicProduct:
    settings = _catalogue_settings()
    try:
        published = _published(_by_slug(session, slug), settings)
        if published is None or published[0].archived_at is not None:
            raise HTTPException(status_code=404, detail="The product is not available.")
        product, cents, price_is_demo = published
        gallery, details = _load_related(session, [product])
    except HTTPException:
        raise
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="The catalogue is temporarily unavailable.") from None
    response.headers["Cache-Control"] = "no-store"
    return _public_product(product, cents, price_is_demo, gallery.get(product.id, []), details.get(product.id, []))
