"""Owner product management. These routes are not part of the public catalogue."""

import uuid
from urllib.parse import urlparse

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


def _payment_readiness(settings) -> list[ReadinessItem]:
    selected = settings.payment_provider == "payfast" and settings.payfast_mode == "sandbox"
    if settings.payfast_mode not in {"", "sandbox"}:
        configuration = "PAYFAST_MODE is not sandbox. Live PayFast is disabled."
        configured = False
    elif not selected:
        configuration = "PayFast sandbox is not selected. Checkout still uses the simulated payment flow."
        configured = False
    else:
        missing = []
        if not settings.payfast_merchant_id.strip():
            missing.append("PAYFAST_MERCHANT_ID")
        if not settings.payfast_merchant_key.strip():
            missing.append("PAYFAST_MERCHANT_KEY")
        notify = settings.payfast_notify_url.strip()
        host = (urlparse(notify).hostname or "").lower()
        local_host = host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".local")
        if missing:
            configuration = "Missing PayFast sandbox credentials: " + ", ".join(missing) + "."
            configured = False
        elif not notify.lower().startswith("https://"):
            configuration = "PAYFAST_NOTIFY_URL must be https. PayFast cannot notify a local address."
            configured = False
        elif local_host:
            configuration = "The notification URL is not reachable from PayFast. Point PAYFAST_NOTIFY_URL at a temporary https tunnel for POST /api/v1/payments/payfast/itn."
            configured = False
        elif not settings.payfast_return_url.strip().lower().startswith(("http://", "https://")) or not settings.payfast_cancel_url.strip().lower().startswith(("http://", "https://")):
            configuration = "PAYFAST_RETURN_URL and PAYFAST_CANCEL_URL must be absolute http or https addresses."
            configured = False
        else:
            configuration = "PayFast sandbox merchant details and a public https notification URL are configured."
            configured = True
    return [
        ReadinessItem(key="payment", label="PayFast sandbox configuration", ready=configured, detail=configuration),
        ReadinessItem(
            key="payfast_notification_test",
            label="PayFast sandbox payment test",
            ready=False,
            detail="No successful sandbox payment notification has been recorded. A browser return does not count as payment.",
        ),
    ]


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
                detail="Parcel description, dimensions, and weight are configured from product specifications. They have not been confirmed as packed-parcel measurements."
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
            *_payment_readiness(settings),
        ],
    )
