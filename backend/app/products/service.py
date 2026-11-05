"""Owner product records. Prices are saved only when the owner supplies them."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.audit import ProductAuditEvent
from app.models.product import Product

AUDITED_FIELDS = ("name", "slug", "description", "sku", "unit_price_cents", "currency", "active", "archived_at", "image_filename")


class ProductError(Exception):
    """A product could not be saved."""


class ProductNotFound(ProductError):
    """The product does not exist."""


class ProductConflict(ProductError):
    """The slug or SKU is already used."""


def list_products(session: Session) -> list[Product]:
    return list(
        session.scalars(
            select(Product).where(Product.archived_at.is_(None)).order_by(Product.name, Product.slug)
        )
    )


def get_product(session: Session, product_id: uuid.UUID) -> Product | None:
    product = session.get(Product, product_id)
    if product is None or product.archived_at is not None:
        return None
    return product


def create_product(session: Session, fields: dict[str, object], actor: str) -> Product:
    try:
        product = Product(**fields)
        session.add(product)
        session.flush()
        _record(session, product.id, actor, _changes({field: None for field in AUDITED_FIELDS}, fields, include_unchanged=True))
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ProductConflict("A product with that slug or SKU already exists.") from None
    return product


def update_product(session: Session, product_id: uuid.UUID, fields: dict[str, object], actor: str) -> Product:
    product = get_product(session, product_id)
    if product is None:
        raise ProductNotFound("The product does not exist.")
    previous = {field: getattr(product, field) for field in AUDITED_FIELDS}
    changes = _changes(previous, fields, include_unchanged=False)
    for key, value in fields.items():
        setattr(product, key, value)
    if changes:
        _record(session, product.id, actor, changes)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ProductConflict("A product with that slug or SKU already exists.") from None
    return product


def archive_product(session: Session, product_id: uuid.UUID, actor: str) -> None:
    product = get_product(session, product_id)
    if product is None:
        raise ProductNotFound("The product does not exist.")
    previous_active = product.active
    archived_at = datetime.now(timezone.utc)
    product.active = False
    product.archived_at = archived_at
    _record(
        session,
        product.id,
        actor,
        [
            {"field": "active", "previous": previous_active, "new": False},
            {"field": "archived_at", "previous": None, "new": archived_at.isoformat()},
        ],
    )
    session.commit()


def list_audit_events(session: Session, product_id: uuid.UUID) -> list[ProductAuditEvent]:
    if get_product(session, product_id) is None:
        raise ProductNotFound("The product does not exist.")
    return list(
        session.scalars(
            select(ProductAuditEvent)
            .where(ProductAuditEvent.product_id == product_id)
            .order_by(ProductAuditEvent.created_at, ProductAuditEvent.id)
        )
    )


def _changes(previous: dict[str, object], fields: dict[str, object], *, include_unchanged: bool) -> list[dict[str, object]]:
    changes = []
    for field in AUDITED_FIELDS:
        if field not in fields:
            continue
        new_value = fields[field]
        old_value = previous.get(field)
        if include_unchanged or old_value != new_value:
            changes.append({"field": field, "previous": old_value, "new": new_value})
    return changes


def _record(session: Session, product_id: uuid.UUID, actor: str, changes: list[dict[str, object]]) -> None:
    cleaned = actor.strip()
    if not cleaned or len(cleaned) > 254:
        raise ProductError("A product change needs an owner.")
    if not changes:
        return
    session.add(ProductAuditEvent(product_id=product_id, actor=cleaned, changes=changes))
