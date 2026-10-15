"""Internal order records. There is no public submission route."""

import hashlib
import json
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.models.order import FULFILMENT_STATUSES, FULFILMENT_TRANSITIONS, PAYMENT_STATUSES, Order, OrderItem, OrderStatusEvent
from app.models.payment import Payment
from app.models.product import Product


class OrderError(Exception):
    """An order could not be recorded."""


class OrderValidationError(OrderError):
    """The order request is incomplete or inconsistent."""


class IdempotencyConflict(OrderError):
    """The same idempotency key was sent with a different order."""


@dataclass(frozen=True)
class OrderLine:
    product_id: uuid.UUID
    quantity: int


@dataclass(frozen=True)
class DeliveryAddress:
    name: str
    line1: str
    city: str
    region: str
    postal_code: str
    line2: str | None = None
    country: str = "ZA"


@dataclass(frozen=True)
class OrderDraft:
    idempotency_key: str
    customer_name: str
    customer_email: str
    delivery: DeliveryAddress
    lines: list[OrderLine]
    shipping_cents: int
    customer_phone: str | None = None
    is_simulation: bool = False
    shipping_provider: str | None = None
    shipping_service_code: str | None = None
    shipping_quote_reference: str | None = None


def create_order(session: Session, draft: OrderDraft) -> Order:
    key = _idempotency_key(draft.idempotency_key)
    fingerprint = _fingerprint(draft)
    try:
        with _begin(session):
            existing = session.scalar(select(Order).where(Order.idempotency_key == key))
            if existing is not None:
                if existing.idempotency_fingerprint != fingerprint:
                    raise IdempotencyConflict("This idempotency key was already used for a different order.")
                order_id = existing.id
            else:
                order = _build_order(session, draft, key, fingerprint)
                session.add(order)
                session.flush()
                order_id = order.id
    except IntegrityError:
        session.rollback()
        existing = session.scalar(select(Order).where(Order.idempotency_key == key))
        if existing is None:
            raise
        return _existing_match(existing, fingerprint)
    stored = session.get(Order, order_id)
    if stored is None:
        raise OrderError("The order could not be read after it was saved.")
    if session.in_transaction():
        session.commit()
    return stored


def allowed_fulfilment_statuses(current: str) -> list[str]:
    allowed = FULFILMENT_TRANSITIONS.get(current, frozenset())
    return [status for status in ("processing", "shipped", "delivered", "cancelled") if status in allowed]


def update_fulfilment_status(session: Session, order_id: uuid.UUID, status: str, actor: str) -> Order:
    if status not in FULFILMENT_STATUSES:
        raise OrderValidationError("That fulfilment status is not recognised.")
    cleaned_actor = actor.strip()
    if not cleaned_actor:
        raise OrderValidationError("A fulfilment change needs an actor.")
    if len(cleaned_actor) > 254:
        raise OrderValidationError("The fulfilment actor is too long.")
    with _begin(session):
        order = session.get(Order, order_id)
        if order is None:
            raise OrderValidationError("The order does not exist.")
        if status == order.fulfilment_status:
            raise OrderValidationError("The order is already in that fulfilment status.")
        if status not in FULFILMENT_TRANSITIONS.get(order.fulfilment_status, frozenset()):
            raise OrderValidationError("That fulfilment change is not allowed.")
        previous = order.fulfilment_status
        order.fulfilment_status = status
        session.add(
            OrderStatusEvent(
                order_id=order.id,
                field_name="fulfilment_status",
                from_status=previous,
                to_status=status,
                actor=cleaned_actor,
            )
        )
    stored = session.get(Order, order_id)
    if stored is None:
        raise OrderValidationError("The order does not exist.")
    if session.in_transaction():
        session.commit()
    return stored


def list_orders(
    session: Session,
    *,
    limit: int,
    offset: int,
    fulfilment_status: str | None,
    payment_status: str | None,
) -> tuple[list[Order], int]:
    if limit < 1 or limit > 50 or offset < 0:
        raise OrderValidationError("The page size or offset is not valid.")
    filters = []
    if fulfilment_status:
        if fulfilment_status not in FULFILMENT_STATUSES:
            raise OrderValidationError("That fulfilment status is not recognised.")
        filters.append(Order.fulfilment_status == fulfilment_status)
    if payment_status:
        if payment_status not in PAYMENT_STATUSES:
            raise OrderValidationError("That payment status is not recognised.")
        filters.append(Order.payment_status == payment_status)
    total = session.scalar(select(func.count()).select_from(Order).where(*filters)) or 0
    rows = session.scalars(
        select(Order).where(*filters).order_by(Order.created_at.desc(), Order.order_number).offset(offset).limit(limit)
    ).all()
    return list(rows), int(total)


def get_order(session: Session, order_id: uuid.UUID) -> Order | None:
    return session.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items), selectinload(Order.status_events))
    )


def order_summary(session: Session) -> tuple[int, dict[str, int], dict[str, int]]:
    total = int(session.scalar(select(func.count()).select_from(Order)) or 0)
    payment = {status: 0 for status in PAYMENT_STATUSES}
    fulfilment = {status: 0 for status in FULFILMENT_STATUSES}
    for status, count in session.execute(select(Order.payment_status, func.count()).group_by(Order.payment_status)):
        if status in payment:
            payment[status] = int(count)
    for status, count in session.execute(select(Order.fulfilment_status, func.count()).group_by(Order.fulfilment_status)):
        if status in fulfilment:
            fulfilment[status] = int(count)
    return total, payment, fulfilment


def latest_payment_reference(session: Session, order_id: uuid.UUID) -> str | None:
    provider, reference = latest_payment_identity(session, order_id)
    del provider
    return reference


def latest_payment_identity(session: Session, order_id: uuid.UUID) -> tuple[str | None, str | None]:
    payment = session.scalar(
        select(Payment)
        .where(Payment.order_id == order_id)
        .order_by(Payment.created_at.desc(), Payment.id.desc())
        .limit(1)
    )
    if payment is None:
        return None, None
    provider = payment.provider.strip() or None
    reference = (payment.provider_reference or "").strip() or None
    return provider, reference


def _begin(session: Session):
    if session.in_transaction():
        return session.begin_nested()
    return session.begin()


def _build_order(session: Session, draft: OrderDraft, key: str, fingerprint: str) -> Order:
    if draft.shipping_cents < 0:
        raise OrderValidationError("Shipping amount cannot be negative.")
    if not draft.lines:
        raise OrderValidationError("An order needs at least one item.")
    _require_text(draft.customer_name, "customer name")
    email = _require_text(draft.customer_email, "customer email").lower()
    delivery = draft.delivery
    if delivery.country != "ZA":
        raise OrderValidationError("Delivery is limited to South Africa.")
    for field_name, value in (
        ("delivery name", delivery.name),
        ("delivery address", delivery.line1),
        ("delivery city", delivery.city),
        ("delivery region", delivery.region),
        ("delivery postal code", delivery.postal_code),
    ):
        _require_text(value, field_name)

    items: list[OrderItem] = []
    subtotal = 0
    for line in draft.lines:
        if not isinstance(line.quantity, int) or isinstance(line.quantity, bool) or line.quantity <= 0 or line.quantity > 20:
            raise OrderValidationError("Quantity must be a positive integer.")
        product = session.get(Product, line.product_id)
        if product is None or not product.active or product.unit_price_cents is None:
            raise OrderValidationError("An item is not available at a confirmed price.")
        if product.unit_price_cents > 2_000_000_000 // line.quantity:
            raise OrderValidationError("The line total is too large.")
        line_total = line.quantity * product.unit_price_cents
        subtotal += line_total
        items.append(
            OrderItem(
                product_id=product.id,
                product_name=product.name,
                sku=product.sku,
                quantity=line.quantity,
                unit_price_cents=product.unit_price_cents,
                line_total_cents=line_total,
            )
        )

    provider, service_code, quote_reference = _simulation_quote(draft)
    order = Order(
        order_number=f"AV-{uuid.uuid4().hex[:10].upper()}",
        customer_name=draft.customer_name.strip(),
        customer_email=email,
        customer_phone=draft.customer_phone.strip() if draft.customer_phone else None,
        currency="ZAR",
        subtotal_cents=subtotal,
        shipping_cents=draft.shipping_cents,
        total_cents=subtotal + draft.shipping_cents,
        payment_status="pending",
        fulfilment_status="unfulfilled",
        delivery_name=delivery.name.strip(),
        delivery_line1=delivery.line1.strip(),
        delivery_line2=delivery.line2.strip() if delivery.line2 else None,
        delivery_city=delivery.city.strip(),
        delivery_region=delivery.region.strip(),
        delivery_postal_code=delivery.postal_code.strip(),
        delivery_country="ZA",
        idempotency_key=key,
        idempotency_fingerprint=fingerprint,
        is_simulation=draft.is_simulation,
        shipping_provider=provider,
        shipping_service_code=service_code,
        shipping_quote_reference=quote_reference,
        items=items,
        status_events=[
            OrderStatusEvent(field_name="payment_status", from_status=None, to_status="pending", actor="system"),
            OrderStatusEvent(field_name="fulfilment_status", from_status=None, to_status="unfulfilled", actor="system"),
        ],
    )
    return order


def _existing_match(existing: Order, fingerprint: str) -> Order:
    if existing.idempotency_fingerprint != fingerprint:
        raise IdempotencyConflict("This idempotency key was already used for a different order.")
    return existing


def _idempotency_key(value: str) -> str:
    key = value.strip()
    if len(key) < 16 or len(key) > 80:
        raise OrderValidationError("An idempotency key is required.")
    return key


def _fingerprint(draft: OrderDraft) -> str:
    payload = {
        "customer_email": draft.customer_email.strip().lower(),
        "customer_name": draft.customer_name.strip(),
        "customer_phone": (draft.customer_phone or "").strip(),
        "delivery_city": draft.delivery.city.strip(),
        "delivery_country": "ZA",
        "delivery_line1": draft.delivery.line1.strip(),
        "delivery_line2": (draft.delivery.line2 or "").strip(),
        "delivery_name": draft.delivery.name.strip(),
        "delivery_postal_code": draft.delivery.postal_code.strip(),
        "delivery_region": draft.delivery.region.strip(),
        "is_simulation": draft.is_simulation,
        "lines": sorted(
            ({"product_id": str(line.product_id), "quantity": line.quantity} for line in draft.lines),
            key=lambda item: item["product_id"],
        ),
        "shipping_cents": draft.shipping_cents,
        "shipping_provider": draft.shipping_provider,
        "shipping_quote_reference": draft.shipping_quote_reference,
        "shipping_service_code": draft.shipping_service_code,
    }
    encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _simulation_quote(draft: OrderDraft) -> tuple[str | None, str | None, str | None]:
    provider = draft.shipping_provider.strip() if draft.shipping_provider else None
    service_code = draft.shipping_service_code.strip() if draft.shipping_service_code else None
    reference = draft.shipping_quote_reference.strip() if draft.shipping_quote_reference else None
    if draft.is_simulation:
        if provider != "simulated-courier" or not service_code or not reference:
            raise OrderValidationError("A simulated order needs its simulated delivery quote.")
        return provider, service_code, reference
    if provider or service_code or reference:
        raise OrderValidationError("A delivery quote can only be stored on a simulated order.")
    return None, None, None


def _require_text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OrderValidationError(f"A {label} is required.")
    return value.strip()
