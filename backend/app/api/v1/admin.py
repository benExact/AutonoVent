"""Owner product management. These routes are not part of the public catalogue."""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.auth import require_csrf, require_owner
from app.core.config import get_settings
from app.db.session import get_session
from app.models.admin import AdminUser
from app.models.auth import AdminSession
from app.models.product import Product
from app.products.images import ImageRejected, image_directory, public_image_url, remove_product_image, save_product_image
from app.products.service import (
    ProductConflict,
    ProductNotFound,
    create_product,
    list_audit_events,
    list_products,
    update_product,
)
from app.schemas.admin_product import (
    ManagedProduct,
    ProductAuditEventView,
    ProductAuditList,
    ProductList,
    ProductPatch,
    ProductWrite,
)

router = APIRouter()
UNAVAILABLE = "Product management is temporarily unavailable."


def _view(product: Product) -> ManagedProduct:
    return ManagedProduct(
        id=product.id,
        slug=product.slug,
        name=product.name,
        description=product.description,
        sku=product.sku,
        unit_price_cents=product.unit_price_cents,
        currency=product.currency,
        active=product.active,
        image_url=public_image_url(product.image_filename),
        created_at=product.created_at,
        updated_at=product.updated_at,
    )


@router.get("/products", response_model=ProductList)
def products(
    _principal: tuple[AdminUser, AdminSession] = Depends(require_owner),
    session: Session = Depends(get_session),
) -> ProductList:
    try:
        rows = list_products(session)
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return ProductList(products=[_view(row) for row in rows])


@router.post("/products", response_model=ManagedProduct, status_code=201)
def add_product(
    body: ProductWrite,
    principal: tuple[AdminUser, AdminSession] = Depends(require_csrf),
    session: Session = Depends(get_session),
) -> ManagedProduct:
    owner, _row = principal
    try:
        product = create_product(session, body.stored(), owner.email)
    except ProductConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return _view(product)


@router.patch("/products/{product_id}", response_model=ManagedProduct)
def edit_product(
    product_id: uuid.UUID,
    body: ProductPatch,
    principal: tuple[AdminUser, AdminSession] = Depends(require_csrf),
    session: Session = Depends(get_session),
) -> ManagedProduct:
    owner, _row = principal
    changes = body.stored()
    if not changes:
        raise HTTPException(status_code=422, detail="Choose a product field to change.")
    try:
        product = update_product(session, product_id, changes, owner.email)
    except ProductNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ProductConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return _view(product)


@router.post("/products/{product_id}/image", response_model=ManagedProduct)
async def replace_product_image(
    product_id: uuid.UUID,
    image: UploadFile = File(...),
    principal: tuple[AdminUser, AdminSession] = Depends(require_csrf),
    session: Session = Depends(get_session),
) -> ManagedProduct:
    owner, _row = principal
    data = await image.read(5 * 1024 * 1024 + 1)
    await image.close()
    directory = image_directory(get_settings())
    try:
        filename = save_product_image(directory, data)
    except ImageRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    previous = None
    try:
        current = session.get(Product, product_id)
        previous = current.image_filename if current is not None else None
        product = update_product(session, product_id, {"image_filename": filename}, owner.email)
    except ProductNotFound as exc:
        remove_product_image(directory, filename)
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except ProductConflict as exc:
        remove_product_image(directory, filename)
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except SQLAlchemyError:
        remove_product_image(directory, filename)
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    if previous and previous != filename:
        remove_product_image(directory, previous)
    return _view(product)


@router.get("/products/{product_id}/audit", response_model=ProductAuditList)
def product_audit(
    product_id: uuid.UUID,
    _principal: tuple[AdminUser, AdminSession] = Depends(require_owner),
    session: Session = Depends(get_session),
) -> ProductAuditList:
    try:
        events = list_audit_events(session, product_id)
    except ProductNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return ProductAuditList(
        events=[
            ProductAuditEventView(created_at=event.created_at, actor=event.actor, changes=event.changes)
            for event in events
        ]
    )


