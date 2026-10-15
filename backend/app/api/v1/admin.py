"""Owner product management. These routes are not part of the public catalogue."""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.auth import require_csrf, require_owner
from app.core.config import get_settings
from app.db.session import get_session
from app.models.admin import AdminUser
from app.models.auth import AdminSession
from app.models.product import Product
from app.products.service import (
    ProductConflict,
    ProductNotFound,
    create_product,
    list_audit_events,
    list_products,
    selling_price_status,
    update_product,
)
from app.schemas.admin_product import (
    ManagedProduct,
    ProductAuditEventView,
    ProductAuditList,
    ProductList,
    ProductPatch,
    ProductWrite,
    ReadinessItem,
    ReadinessReport,
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
        product = create_product(session, body.model_dump(), owner.email)
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
    changes = body.model_dump(exclude_unset=True)
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


@router.get("/readiness", response_model=ReadinessReport)
def readiness(
    _principal: tuple[AdminUser, AdminSession] = Depends(require_owner),
    session: Session = Depends(get_session),
) -> ReadinessReport:
    try:
        price_ready, price_detail = selling_price_status(session)
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    token_configured = bool(get_settings().bobgo_api_token.strip())
    courier = "A Bob Go sandbox token is configured." if token_configured else "No Bob Go sandbox token is configured."
    courier += " No successful sandbox rate test has been recorded."
    return ReadinessReport(
        checkout_enabled=False,
        checkout_simulation_enabled=get_settings().checkout_simulation_active,
        items=[
            ReadinessItem(key="selling_price", label="Confirmed selling price", ready=price_ready, detail=price_detail),
            ReadinessItem(
                key="collection_address",
                label="Collection address and postal code",
                ready=False,
                detail="The collection street address, suburb, zone, and postal code have not been recorded.",
            ),
            ReadinessItem(
                key="packed_parcel",
                label="Packed parcel dimensions and weight",
                ready=False,
                detail="Packed parcel dimensions and weight have not been recorded.",
            ),
            ReadinessItem(
                key="bobgo",
                label="Bob Go sandbox rate test",
                ready=False,
                detail=courier,
            ),
            ReadinessItem(
                key="payment",
                label="Payment provider",
                ready=False,
                detail="Payment setup is deferred until business registration is complete.",
            ),
        ],
    )
