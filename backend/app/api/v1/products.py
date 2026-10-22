"""Read-only public catalogue. Prices come from PostgreSQL or the development test price."""

from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.models.product import Product
from app.products.images import public_image_url
from app.schemas.product import CatalogueResponse, PublicProduct

router = APIRouter()


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
    statement = select(Product).where(Product.active.is_(True))
    if demo_cents is None:
        statement = statement.where(Product.unit_price_cents.is_not(None))
    statement = statement.order_by(Product.name, Product.slug)
    try:
        rows = session.scalars(statement).all()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="The catalogue is temporarily unavailable.") from None
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
        products.append(
            PublicProduct(
                id=row.id,
                slug=row.slug,
                name=row.name,
                description=row.description,
                sku=row.sku,
                unit_price_cents=cents,
                currency=row.currency,
                active=row.active,
                price_is_demo=price_is_demo,
                image_url=public_image_url(row.image_filename),
            )
        )
    return CatalogueResponse(products=products)
