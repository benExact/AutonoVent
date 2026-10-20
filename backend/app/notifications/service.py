"""Queue customer emails with the order change, then deliver them after commit."""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.models.email_notification import EmailNotification
from app.models.order import Order, OrderStatusEvent
from app.models.shipment import Shipment
from app.notifications.messages import fulfilment_update, payment_confirmation
from app.notifications.transport import EmailDeliveryError, OutgoingEmail, build_transport

logger = logging.getLogger("autonovent.email")


def queue_payment_confirmation(session: Session, order: Order, settings: Settings) -> None:
    if order.payment_status != "paid":
        return
    key = f"payment-confirmed:{order.id}"
    if session.scalar(select(EmailNotification.id).where(EmailNotification.dedupe_key == key)) is not None:
        return
    subject, text, html_body = payment_confirmation(
        order,
        logo_url=settings.email_logo_url,
        sandbox=order.shipping_provider in {"bobgo", "shiplogic"},
    )
    session.add(
        EmailNotification(
            order_id=order.id,
            kind="payment_confirmation",
            dedupe_key=key,
            recipient=order.customer_email,
            subject=subject,
            text_body=text,
            html_body=html_body,
            status="queued",
        )
    )


def queue_fulfilment_update(session: Session, order: Order, event: OrderStatusEvent, settings: Settings) -> None:
    if event.field_name != "fulfilment_status" or event.from_status == event.to_status:
        return
    key = f"fulfilment:{event.id}"
    if session.scalar(select(EmailNotification.id).where(EmailNotification.dedupe_key == key)) is not None:
        return
    shipment = session.scalar(select(Shipment).where(Shipment.order_id == order.id).order_by(Shipment.created_at.desc()).limit(1))
    updated_at = event.created_at or datetime.now(timezone.utc)
    subject, text, html_body = fulfilment_update(order, event.to_status, updated_at, shipment, logo_url=settings.email_logo_url)
    session.add(
        EmailNotification(
            order_id=order.id,
            kind="fulfilment_update",
            dedupe_key=key,
            recipient=order.customer_email,
            subject=subject,
            text_body=text,
            html_body=html_body,
            status="queued",
        )
    )


def deliver_pending(session: Session, settings: Settings | None = None) -> int:
    active = settings or get_settings()
    rows = session.scalars(
        select(EmailNotification)
        .where(EmailNotification.status.in_(("queued", "failed")), EmailNotification.attempt_count < active.email_max_attempts)
        .order_by(EmailNotification.created_at, EmailNotification.id)
    ).all()
    transport = build_transport(active)
    delivered = 0
    for row in rows:
        row.attempt_count += 1
        try:
            receipt = transport.send(
                OutgoingEmail(
                    recipient=row.recipient,
                    subject=row.subject,
                    text_body=row.text_body,
                    html_body=row.html_body,
                )
            )
        except EmailDeliveryError as exc:
            row.status = "failed"
            row.provider = transport.name
            row.last_error = str(exc)[:300]
            logger.warning("Email notification %s was not accepted.", row.id)
        else:
            row.status = "accepted"
            row.provider = receipt.provider
            row.provider_message_id = receipt.message_id
            row.accepted_at = datetime.now(timezone.utc)
            row.last_error = None
            delivered += 1
        session.commit()
    return delivered


def release_notifications(session: Session) -> None:
    if session.in_transaction():
        session.commit()
    fresh = Session(bind=session.get_bind(), expire_on_commit=False)
    try:
        deliver_pending(fresh)
    except Exception as exc:
        logger.warning("Email dispatch stopped before every queued notification was attempted (%s).", exc.__class__.__name__)
        fresh.rollback()
    finally:
        fresh.close()
