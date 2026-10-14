"""Read-only public catalogue. Prices come from PostgreSQL."""

from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.session import get_session
from app.models.product import Product
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


@router.get("/products", response_model=CatalogueResponse)
def list_products(session: Session = Depends(get_catalogue_session)) -> CatalogueResponse:
    statement = (
        select(Product)
        .where(Product.active.is_(True), Product.unit_price_cents.is_not(None))
        .order_by(Product.name, Product.slug)
    )
    try:
        rows = session.scalars(statement).all()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="The catalogue is temporarily unavailable.") from None
    return CatalogueResponse(products=[PublicProduct.model_validate(row) for row in rows])
