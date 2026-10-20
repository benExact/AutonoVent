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
    settings = get_settings()
    collection_ready = all(
        value.strip()
        for value in (
            settings.collection_street_address,
            settings.collection_local_area,
            settings.collection_city,
            settings.collection_zone,
            settings.collection_postal_code,
        )
    )
    parcel_ready = bool(settings.packed_parcel_description.strip()) and all(
        value is not None
        for value in (
            settings.packed_parcel_length_mm,
            settings.packed_parcel_width_mm,
            settings.packed_parcel_height_mm,
            settings.packed_parcel_weight_grams,
        )
    )
    provider_ready = settings.courier_provider == "shiplogic"
    mode_ready = settings.shiplogic_mode == "sandbox"
    token_ready = bool(settings.shiplogic_api_token.strip())
    quote_ready = provider_ready and mode_ready and token_ready and collection_ready and parcel_ready
    return ReadinessReport(
        checkout_enabled=False,
        checkout_simulation_enabled=settings.checkout_simulation_active,
        items=[
            ReadinessItem(key="selling_price", label="Confirmed selling price", ready=price_ready, detail=price_detail),
            ReadinessItem(
                key="collection_address",
                label="Collection address and postal code",
                ready=collection_ready,
                detail="The collection street address, suburb, city, zone, and postal code are configured."
                if collection_ready
                else "The collection street address, suburb, city, zone, and postal code have not been recorded.",
            ),
            ReadinessItem(
                key="packed_parcel",
                label="Packed parcel dimensions and weight",
                ready=parcel_ready,
                detail="The packed parcel description, dimensions, and weight are configured."
                if parcel_ready
                else "Packed parcel dimensions and weight have not been recorded.",
            ),
            ReadinessItem(
                key="shiplogic_provider",
                label="ShipLogic provider",
                ready=provider_ready,
                detail="COURIER_PROVIDER is shiplogic." if provider_ready else "COURIER_PROVIDER is not shiplogic.",
            ),
            ReadinessItem(
                key="shiplogic_mode",
                label="ShipLogic sandbox mode",
                ready=mode_ready,
                detail="SHIPLOGIC_MODE is sandbox." if mode_ready else "SHIPLOGIC_MODE is not sandbox. Live courier mode is disabled.",
            ),
            ReadinessItem(
                key="shiplogic_token",
                label="ShipLogic sandbox token",
                ready=token_ready,
                detail="A ShipLogic sandbox token is configured." if token_ready else "No ShipLogic sandbox token is configured.",
            ),
            ReadinessItem(
                key="shiplogic_quote",
                label="ShipLogic sandbox quote test",
                ready=False,
                detail=(
                    "The sandbox configuration is complete. No successful sandbox rate test has been recorded."
                    if quote_ready
                    else "The sandbox configuration is incomplete. No successful sandbox rate test has been recorded."
                ),
            ),
            ReadinessItem(
                key="payment",
                label="Payment provider",
                ready=False,
                detail="Payment setup is deferred until business registration is complete.",
            ),
        ],
    )
