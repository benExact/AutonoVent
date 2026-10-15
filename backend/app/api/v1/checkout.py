"""Development-only simulated checkout. Owner routes stay on their own router."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth.service import CSRF_FAILED, anonymous_csrf_ok
from app.checkout.service import (
    PAYMENT_LABEL,
    SIMULATED_LABEL,
    CheckoutConflict,
    CheckoutError,
    CheckoutNotFound,
    CheckoutResult,
    CheckoutValidationError,
    address_from_parts,
    place_simulated_order,
    quote_delivery,
    record_simulated_payment,
)
from app.core.config import Settings, get_settings
from app.db.session import get_session
from app.orders.service import OrderLine
from app.schemas.checkout import (
    CheckoutOrderView,
    CheckoutStatus,
    OrderRequest,
    PaymentRequest,
    QuoteOptionView,
    QuoteRequest,
    QuoteResponse,
    QuotedLineView,
)
from app.shipping.simulated import SIMULATED_PROVIDER

router = APIRouter()
UNAVAILABLE = "Checkout simulation is temporarily unavailable."


def require_simulation() -> Settings:
    try:
        settings = get_settings()
    except ValidationError:
        raise HTTPException(status_code=404, detail="Checkout simulation is not available.") from None
    if not settings.checkout_simulation_active:
        raise HTTPException(status_code=404, detail="Checkout simulation is not available.")
    return settings


def _csrf(request: Request) -> None:
    if not anonymous_csrf_ok(request.headers.get("x-csrf-token"), request.cookies.get("autonovent_csrf")):
        raise HTTPException(status_code=403, detail=CSRF_FAILED)


def _view(result: CheckoutResult) -> CheckoutOrderView:
    order = result.order
    return CheckoutOrderView(
        simulation=True,
        label=result.label,
        payment_label=PAYMENT_LABEL if result.payment_provider == "simulated" else PAYMENT_LABEL,
        id=order.id,
        order_number=order.order_number,
        currency=order.currency,
        subtotal_cents=order.subtotal_cents,
        shipping_cents=order.shipping_cents,
        total_cents=order.total_cents,
        payment_status=order.payment_status,
        fulfilment_status=order.fulfilment_status,
        payment_provider=result.payment_provider,
        payment_reference=result.payment_reference,
        shipping_provider=order.shipping_provider,
        shipping_service_code=order.shipping_service_code,
        shipping_quote_reference=order.shipping_quote_reference,
    )


def _lines(body_lines) -> list[OrderLine]:
    return [OrderLine(product_id=line.product_id, quantity=line.quantity) for line in body_lines]


def _address(body):
    return address_from_parts(
        name=body.name,
        line1=body.line1,
        line2=body.line2,
        city=body.city,
        region=body.region,
        postal_code=body.postal_code,
        country=body.country,
    )


@router.get("/checkout/status", response_model=CheckoutStatus)
def checkout_status() -> CheckoutStatus:
    try:
        settings = get_settings()
    except ValidationError:
        return CheckoutStatus(simulation_enabled=False)
    return CheckoutStatus(simulation_enabled=settings.checkout_simulation_active)


@router.post("/checkout/quotes", response_model=QuoteResponse)
def checkout_quotes(
    body: QuoteRequest,
    request: Request,
    settings: Settings = Depends(require_simulation),
    session: Session = Depends(get_session),
) -> QuoteResponse:
    _csrf(request)
    try:
        quoted = quote_delivery(session, settings, delivery=_address(body.delivery), lines=_lines(body.lines))
    except CheckoutValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return QuoteResponse(
        simulation=True,
        provider=SIMULATED_PROVIDER,
        label=SIMULATED_LABEL,
        currency=quoted.currency,
        subtotal_cents=quoted.subtotal_cents,
        lines=[
            QuotedLineView(
                product_id=line.product_id,
                product_name=line.product_name,
                quantity=line.quantity,
                unit_price_cents=line.unit_price_cents,
                line_total_cents=line.line_total_cents,
            )
            for line in quoted.lines
        ],
        quotes=[
            QuoteOptionView(
                provider=rate.provider,
                service_code=rate.service_code,
                service_name=rate.service_name,
                shipping_cents=rate.shipping_cents,
                total_cents=quoted.subtotal_cents + rate.shipping_cents,
                quote_reference=rate.quote_reference,
                label=rate.label,
            )
            for rate in quoted.rates
        ],
    )


@router.post("/checkout/orders", response_model=CheckoutOrderView)
def checkout_order(
    body: OrderRequest,
    request: Request,
    settings: Settings = Depends(require_simulation),
    session: Session = Depends(get_session),
) -> CheckoutOrderView:
    _csrf(request)
    try:
        result = place_simulated_order(
            session,
            settings,
            idempotency_key=body.idempotency_key,
            customer_name=body.customer_name,
            customer_email=body.customer_email,
            customer_phone=body.customer_phone,
            delivery=_address(body.delivery),
            lines=_lines(body.lines),
            service_code=body.service_code,
            expected_shipping_cents=body.expected_shipping_cents,
        )
    except CheckoutConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except CheckoutValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return _view(result)


@router.post("/checkout/orders/{order_id}/payment", response_model=CheckoutOrderView)
def checkout_payment(
    order_id: uuid.UUID,
    body: PaymentRequest,
    request: Request,
    _settings: Settings = Depends(require_simulation),
    session: Session = Depends(get_session),
) -> CheckoutOrderView:
    _csrf(request)
    try:
        result = record_simulated_payment(
            session,
            order_id=order_id,
            outcome=body.outcome,
            idempotency_key=body.idempotency_key,
        )
    except CheckoutNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    except CheckoutConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    except CheckoutError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return _view(result)
