"""Private owner order views. There is no public order submission route."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.auth import require_csrf, require_owner
from app.db.session import get_session
from app.models.admin import AdminUser
from app.models.auth import AdminSession
from app.models.order import Order
from app.orders.service import (
    OrderValidationError,
    allowed_fulfilment_statuses,
    get_order,
    latest_payment_identity,
    list_orders,
    order_summary,
    update_fulfilment_status,
)
from app.schemas.order import (
    FulfilmentUpdate,
    OrderDetail,
    OrderItemView,
    OrderListItem,
    OrderListResponse,
    OrderSummary,
    StatusEventView,
)

router = APIRouter()
UNAVAILABLE = "Orders are temporarily unavailable."


def _list_item(order: Order) -> OrderListItem:
    return OrderListItem(
        id=order.id,
        order_number=order.order_number,
        created_at=order.created_at,
        customer_name=order.customer_name,
        customer_email=order.customer_email,
        fulfilment_status=order.fulfilment_status,
        payment_status=order.payment_status,
        currency=order.currency,
        total_cents=order.total_cents,
        is_simulation=order.is_simulation,
    )


def _detail(session: Session, order: Order) -> OrderDetail:
    events = sorted(order.status_events, key=lambda event: (event.created_at, str(event.id)))
    items = sorted(order.items, key=lambda item: (item.product_name, str(item.id)))
    provider, reference = latest_payment_identity(session, order.id)
    return OrderDetail(
        **_list_item(order).model_dump(),
        customer_phone=order.customer_phone,
        subtotal_cents=order.subtotal_cents,
        shipping_cents=order.shipping_cents,
        delivery_name=order.delivery_name,
        delivery_line1=order.delivery_line1,
        delivery_line2=order.delivery_line2,
        delivery_city=order.delivery_city,
        delivery_region=order.delivery_region,
        delivery_postal_code=order.delivery_postal_code,
        delivery_country=order.delivery_country,
        payment_reference=reference,
        payment_provider=provider,
        shipping_provider=order.shipping_provider,
        shipping_service_code=order.shipping_service_code,
        shipping_quote_reference=order.shipping_quote_reference,
        items=[
            OrderItemView(
                product_name=item.product_name,
                sku=item.sku,
                quantity=item.quantity,
                unit_price_cents=item.unit_price_cents,
                line_total_cents=item.line_total_cents,
            )
            for item in items
        ],
        status_events=[
            StatusEventView(
                field_name=event.field_name,
                from_status=event.from_status,
                to_status=event.to_status,
                actor=event.actor,
                created_at=event.created_at,
            )
            for event in events
        ],
        allowed_fulfilment_statuses=allowed_fulfilment_statuses(order.fulfilment_status),
    )


@router.get("/orders/summary", response_model=OrderSummary)
def summary(
    _principal: tuple[AdminUser, AdminSession] = Depends(require_owner),
    session: Session = Depends(get_session),
) -> OrderSummary:
    try:
        total, payment, fulfilment = order_summary(session)
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return OrderSummary(orders=total, payment=payment, fulfilment=fulfilment)


@router.get("/orders", response_model=OrderListResponse)
def orders(
    limit: int = Query(default=20, ge=1, le=50),
    offset: int = Query(default=0, ge=0),
    fulfilment_status: str | None = None,
    payment_status: str | None = None,
    _principal: tuple[AdminUser, AdminSession] = Depends(require_owner),
    session: Session = Depends(get_session),
) -> OrderListResponse:
    try:
        rows, total = list_orders(
            session,
            limit=limit,
            offset=offset,
            fulfilment_status=fulfilment_status,
            payment_status=payment_status,
        )
    except OrderValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return OrderListResponse(orders=[_list_item(row) for row in rows], total=total, limit=limit, offset=offset)


@router.get("/orders/{order_id}", response_model=OrderDetail)
def order_detail(
    order_id: uuid.UUID,
    _principal: tuple[AdminUser, AdminSession] = Depends(require_owner),
    session: Session = Depends(get_session),
) -> OrderDetail:
    try:
        order = get_order(session, order_id)
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    if order is None:
        raise HTTPException(status_code=404, detail="The order does not exist.")
    return _detail(session, order)


@router.patch("/orders/{order_id}/fulfilment", response_model=OrderDetail)
def change_fulfilment(
    order_id: uuid.UUID,
    body: FulfilmentUpdate,
    principal: tuple[AdminUser, AdminSession] = Depends(require_csrf),
    session: Session = Depends(get_session),
) -> OrderDetail:
    owner, _row = principal
    try:
        update_fulfilment_status(session, order_id, body.status, owner.email)
        order = get_order(session, order_id)
    except OrderValidationError as exc:
        status_code = 404 if str(exc) == "The order does not exist." else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from None
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    if order is None:
        raise HTTPException(status_code=404, detail="The order does not exist.")
    return _detail(session, order)
