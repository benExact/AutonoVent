"""ShipLogic and PayFast sandbox checkout. Prices come from the server and the providers."""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.checkout.service import (
    CheckoutConflict,
    CheckoutNotFound,
    CheckoutResult,
    CheckoutUnavailable,
    CheckoutValidationError,
    QuotedLine,
    _begin,
    _email,
    _phone,
    _priced_lines,
    _province,
    _require_text,
    _result,
)
from app.core.config import Settings, get_settings
from app.legal import TERMS_VERSION
from app.models.order import Order, OrderStatusEvent
from app.models.payment import Payment
from app.notifications.service import queue_payment_confirmation, release_notifications
from app.orders.service import (
    DeliveryAddress,
    IdempotencyConflict,
    OrderDraft,
    OrderLine,
    OrderValidationError,
    create_order,
)
from app.payments.payfast import (
    SANDBOX_PROCESS_URL,
    PayfastConfigurationError,
    amount_matches,
    checkout_fields,
    ip_is_payfast,
    itn_parameter_string,
    itn_signature_matches,
    validate_with_payfast,
)
from app.shipping.shiplogic import (
    SANDBOX_BASE_URL,
    ShipLogicError,
    ShipLogicSandboxClient,
    PackedParcel,
    SouthAfricanAddress,
)
from app.shipping.simulated import SimulatedRate

SHIPLOGIC_PROVIDER = "shiplogic"
PAYFAST_PROVIDER = "payfast"
SANDBOX_LABEL = "ShipLogic sandbox rate. This is not a confirmed live courier booking."
SANDBOX_PAYMENT_LABEL = "PayFast sandbox payment. This is not a live payment."


@dataclass(frozen=True)
class PayfastRedirect:
    action: str
    fields: dict[str, str]


def quote_sandbox(session: Session, settings: Settings, *, delivery: DeliveryAddress, lines: list[OrderLine]):
    from app.checkout.service import QuoteResult

    province = _province(delivery)
    priced = _priced_lines(session, settings, lines)
    subtotal = sum(line.line_total_cents for line in priced)
    options = _fresh_rates(settings, delivery, province, priced, subtotal)
    return QuoteResult(currency="ZAR", subtotal_cents=subtotal, lines=priced, rates=options, label=SANDBOX_LABEL)


def place_sandbox_order(
    session: Session,
    settings: Settings,
    *,
    idempotency_key: str,
    customer_name: str,
    customer_email: str,
    customer_phone: str | None,
    delivery: DeliveryAddress,
    lines: list[OrderLine],
    service_code: str,
    expected_shipping_cents: int | None,
    accept_terms: bool,
    terms_version: str,
) -> CheckoutResult:
    province = _province(delivery)
    email = _email(customer_email)
    phone = _phone(customer_phone, required=True)
    _require_text(customer_name, "customer name")
    if accept_terms is not True or terms_version.strip() != TERMS_VERSION:
        raise CheckoutValidationError("Accept the current Terms and Conditions before payment.")
    quoted = _priced_lines(session, settings, lines)
    subtotal = sum(line.line_total_cents for line in quoted)
    selected = _match_rate(settings, delivery, province, quoted, subtotal, service_code, expected_shipping_cents)
    draft = OrderDraft(
        idempotency_key=idempotency_key,
        customer_name=customer_name,
        customer_email=email,
        customer_phone=phone,
        delivery=DeliveryAddress(
            name=delivery.name,
            line1=delivery.line1,
            line2=delivery.line2,
            city=delivery.city,
            region=province,
            postal_code=delivery.postal_code.strip(),
            suburb=delivery.suburb,
            country="ZA",
        ),
        lines=[
            OrderLine(product_id=item.product_id, quantity=item.quantity, unit_price_cents=item.unit_price_cents)
            for item in quoted
        ],
        shipping_cents=selected.shipping_cents,
        is_simulation=False,
        shipping_provider=SHIPLOGIC_PROVIDER,
        shipping_service_code=selected.service_code,
        shipping_quote_reference=selected.quote_reference,
        terms_version=TERMS_VERSION,
        allow_demo_price=any(item.price_is_demo for item in quoted),
    )
    try:
        order = create_order(session, draft)
    except IdempotencyConflict as exc:
        raise CheckoutConflict(str(exc)) from None
    except OrderValidationError as exc:
        raise CheckoutValidationError(str(exc)) from None
    result = _result(session, order)
    return CheckoutResult(
        order=result.order,
        payment_provider=result.payment_provider,
        payment_reference=result.payment_reference,
        label="PayFast sandbox order",
        payment_label=SANDBOX_PAYMENT_LABEL,
    )


def payfast_redirect(session: Session, settings: Settings, order_id: uuid.UUID) -> PayfastRedirect:
    order = session.get(Order, order_id)
    if order is None or order.is_simulation or order.shipping_provider != SHIPLOGIC_PROVIDER:
        raise CheckoutNotFound("The sandbox order does not exist.")
    if order.payment_status == "paid":
        raise CheckoutConflict("This order is already paid.")
    if order.terms_accepted is not True:
        raise CheckoutValidationError("Accept the current Terms and Conditions before payment.")
    first, last = _split_name(order.customer_name)
    try:
        fields = checkout_fields(
            merchant_id=settings.payfast_merchant_id,
            merchant_key=settings.payfast_merchant_key,
            passphrase=settings.payfast_passphrase,
            return_url=settings.payfast_return_url,
            cancel_url=settings.payfast_cancel_url,
            notify_url=settings.payfast_notify_url,
            name_first=first,
            name_last=last,
            email_address=order.customer_email,
            cell_number=order.customer_phone or "",
            payment_id=order.order_number,
            amount_cents=order.total_cents,
            item_name=order.order_number,
        )
    except PayfastConfigurationError as exc:
        raise CheckoutValidationError(str(exc)) from None
    key = f"payfast-start:{order.id}"
    existing = session.scalar(select(Payment).where(Payment.idempotency_key == key))
    if existing is None:
        session.add(
            Payment(
                order_id=order.id,
                provider=PAYFAST_PROVIDER,
                idempotency_key=key,
                status="initiated",
                amount_cents=order.total_cents,
                currency=order.currency,
                notification={"sandbox": True, "stage": "redirect"},
            )
        )
        session.commit()
    elif existing.order_id != order.id or existing.amount_cents != order.total_cents or existing.provider != PAYFAST_PROVIDER:
        raise CheckoutConflict("This payment attempt does not match the saved order.")
    return PayfastRedirect(action=SANDBOX_PROCESS_URL, fields=fields)


def apply_payfast_itn(
    session: Session,
    settings: Settings,
    *,
    pairs: list[tuple[str, str]],
    source_ip: str,
    transport=None,
) -> None:
    data = {name: value for name, value in pairs if name != "signature"}
    received = ""
    for name, value in pairs:
        if name == "signature":
            received = value
            break
    parameter_string = itn_parameter_string(pairs)
    if not received or not itn_signature_matches(parameter_string, settings.payfast_passphrase, received):
        raise CheckoutValidationError("The payment notification could not be verified.")
    if not ip_is_payfast(source_ip):
        raise CheckoutValidationError("The payment notification could not be verified.")
    if data.get("merchant_id", "").strip() != settings.payfast_merchant_id.strip():
        raise CheckoutValidationError("The payment notification could not be verified.")
    if not validate_with_payfast(parameter_string, transport=transport):
        raise CheckoutUnavailable("The payment notification could not be confirmed with PayFast.")
    order_number = data.get("m_payment_id", "").strip()
    order = session.scalar(select(Order).where(Order.order_number == order_number))
    if order is None or order.is_simulation or order.shipping_provider != SHIPLOGIC_PROVIDER:
        raise CheckoutValidationError("The payment notification could not be verified.")
    gross = data.get("amount_gross", "")
    if not amount_matches(order.total_cents, gross):
        raise CheckoutValidationError("The payment notification could not be verified.")
    status = _itn_status(data.get("payment_status", ""))
    reference = data.get("pf_payment_id", "").strip()
    if not reference:
        raise CheckoutValidationError("The payment notification could not be verified.")
    if status is None:
        _store_unconfirmed(session, order, reference, data)
        return
    _store_confirmed(session, order, status, reference, data)
    release_notifications(session)


def missing_sandbox_configuration(settings: Settings) -> list[str]:
    missing: list[str] = []
    checks = (
        ("collection street address", settings.collection_street_address),
        ("collection suburb", settings.collection_local_area),
        ("collection city", settings.collection_city),
        ("collection zone", settings.collection_zone),
        ("collection postal code", settings.collection_postal_code),
        ("packed parcel description", settings.packed_parcel_description),
    )
    for label, value in checks:
        if not value.strip():
            missing.append(label)
    for label, value in (
        ("packed parcel length", settings.packed_parcel_length_mm),
        ("packed parcel width", settings.packed_parcel_width_mm),
        ("packed parcel height", settings.packed_parcel_height_mm),
        ("packed parcel weight", settings.packed_parcel_weight_grams),
    ):
        if value is None:
            missing.append(label)
    return missing


def source_ip(peer: str | None, header_value: str | None, settings: Settings) -> str:
    if peer in {"127.0.0.1", "::1"} and settings.payfast_forwarded_ip_header.strip() and header_value:
        return header_value.strip()
    return (peer or "").strip()


def _fresh_rates(settings: Settings, delivery: DeliveryAddress, province: str, priced: list[QuotedLine], subtotal: int) -> list[SimulatedRate]:
    missing = missing_sandbox_configuration(settings)
    if missing:
        raise CheckoutValidationError("ShipLogic sandbox rates need " + ", ".join(missing) + ". No delivery price has been estimated.")
    parcels = _parcels(settings, priced)
    try:
        quote = ShipLogicSandboxClient(
            base_url=settings.shiplogic_sandbox_base_url or SANDBOX_BASE_URL,
            api_token=settings.shiplogic_api_token,
            timeout_seconds=settings.shiplogic_timeout_seconds,
        ).quote(
            collection=_collection(settings),
            delivery=_delivery(delivery, province),
            parcels=parcels,
        )
    except ShipLogicError as exc:
        raise CheckoutUnavailable("Delivery quotes are unavailable. No delivery price has been estimated.") from exc
    options: list[SimulatedRate] = []
    for rate in quote.rates:
        service_code = rate.service_level_code
        reference = rate.rate_id
        if len(service_code) > 80 or len(reference) > 120:
            continue
        options.append(
            SimulatedRate(
                service_code=service_code,
                service_name=rate.service_name,
                shipping_cents=rate.total_price_cents,
                quote_reference=reference,
                provider=SHIPLOGIC_PROVIDER,
                label=SANDBOX_LABEL,
            )
        )
    if not options:
        raise CheckoutUnavailable("ShipLogic returned no delivery rates. No delivery price has been estimated.")
    return options


def _match_rate(settings, delivery, province, priced, subtotal, service_code: str, expected: int | None) -> SimulatedRate:
    cleaned = service_code.strip()
    for rate in _fresh_rates(settings, delivery, province, priced, subtotal):
        if rate.service_code != cleaned:
            continue
        if expected is not None and expected != rate.shipping_cents:
            raise CheckoutValidationError("The delivery amount does not match the ShipLogic sandbox quote.")
        return rate
    raise CheckoutValidationError("That ShipLogic sandbox delivery option is no longer available.")


def _collection(settings: Settings) -> SouthAfricanAddress:
    return SouthAfricanAddress(
        street_address=settings.collection_street_address,
        local_area=settings.collection_local_area,
        city=settings.collection_city,
        zone=settings.collection_zone,
        postal_code=settings.collection_postal_code,
        company=settings.collection_company or None,
    )


def _delivery(delivery: DeliveryAddress, province: str) -> SouthAfricanAddress:
    street = delivery.line1.strip()
    if delivery.line2 and delivery.line2.strip():
        street = f"{street}, {delivery.line2.strip()}"
    return SouthAfricanAddress(
        street_address=street,
        local_area=delivery.suburb,
        city=delivery.city,
        zone=province,
        postal_code=delivery.postal_code,
    )


def _parcels(settings: Settings, priced: list[QuotedLine]) -> list[PackedParcel]:
    parcel = PackedParcel(
        description=settings.packed_parcel_description,
        length_mm=settings.packed_parcel_length_mm or 0,
        width_mm=settings.packed_parcel_width_mm or 0,
        height_mm=settings.packed_parcel_height_mm or 0,
        weight_grams=settings.packed_parcel_weight_grams or 0,
    )
    copies: list[PackedParcel] = []
    for line in priced:
        copies.extend([parcel] * line.quantity)
    return copies


def _split_name(value: str) -> tuple[str, str]:
    parts = value.strip().split(None, 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _itn_status(value: str) -> str | None:
    cleaned = value.strip().upper()
    if cleaned == "COMPLETE":
        return "paid"
    if cleaned == "CANCELLED":
        return "cancelled"
    return None


def _store_unconfirmed(session: Session, order: Order, reference: str, data: dict[str, str]) -> None:
    if order.payment_status == "paid":
        return
    _upsert_payment(session, order, "pending", reference, data)
    session.commit()


def _store_confirmed(session: Session, order: Order, status: str, reference: str, data: dict[str, str]) -> None:
    try:
        with _begin(session):
            current = session.get(Order, order.id)
            if current is None:
                raise CheckoutNotFound("The sandbox order does not exist.")
            if current.payment_status == "paid" and status != "paid":
                return
            existing = session.scalar(
                select(Payment).where(Payment.provider == PAYFAST_PROVIDER, Payment.provider_reference == reference)
            )
            if existing is not None:
                if existing.order_id != current.id or existing.amount_cents != current.total_cents:
                    raise CheckoutConflict("This payment notification does not match the saved order.")
                if existing.status == status and current.payment_status == status:
                    return
            if status == "paid" and current.payment_status == "paid":
                return
            previous = current.payment_status
            payment = existing or session.scalar(select(Payment).where(Payment.idempotency_key == f"payfast-start:{current.id}"))
            if payment is None:
                payment = Payment(
                    order_id=current.id,
                    provider=PAYFAST_PROVIDER,
                    idempotency_key=f"payfast-itn:{reference}",
                    status=status,
                    amount_cents=current.total_cents,
                    currency=current.currency,
                )
                session.add(payment)
            payment.provider_reference = reference
            payment.status = status
            payment.amount_cents = current.total_cents
            payment.notification = {"sandbox": True, "payment_status": data.get("payment_status", "")}
            if previous != status:
                current.payment_status = status
                session.add(
                    OrderStatusEvent(
                        order_id=current.id,
                        field_name="payment_status",
                        from_status=previous,
                        to_status=status,
                        actor="payfast-sandbox",
                    )
                )
                if status == "paid":
                    queue_payment_confirmation(session, current, get_settings())
            session.flush()
    except IntegrityError:
        session.rollback()
        return
    if session.in_transaction():
        session.commit()


def _upsert_payment(session: Session, order: Order, status: str, reference: str, data: dict[str, str]) -> None:
    payment = session.scalar(select(Payment).where(Payment.provider == PAYFAST_PROVIDER, Payment.provider_reference == reference))
    if payment is None:
        payment = session.scalar(select(Payment).where(Payment.idempotency_key == f"payfast-start:{order.id}"))
    if payment is None:
        session.add(
            Payment(
                order_id=order.id,
                provider=PAYFAST_PROVIDER,
                provider_reference=reference,
                idempotency_key=f"payfast-itn:{reference}",
                status=status,
                amount_cents=order.total_cents,
                currency=order.currency,
                notification={"sandbox": True, "payment_status": data.get("payment_status", "")},
            )
        )
    else:
        payment.provider_reference = reference
        payment.status = status
        payment.notification = {"sandbox": True, "payment_status": data.get("payment_status", "")}
