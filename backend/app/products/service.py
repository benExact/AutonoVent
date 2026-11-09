"""Owner product records. Prices are saved only when the owner supplies them."""

import math
import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from pathlib import Path

from app.models.audit import ProductAuditEvent
from app.models.product import Product, ProductSlugAlias
from app.products.gallery import rewrite_slug_names
from app.products.images import ImageRejected, relocate_slug_directory

AUDITED_FIELDS = (
    "name",
    "slug",
    "description",
    "short_description",
    "sku",
    "unit_price_cents",
    "currency",
    "active",
    "in_stock",
    "archived_at",
    "image_filename",
    "specification_enabled",
    "specification_original_name",
)
SPECIFICATION_REQUIRED = "Upload a PDF specification sheet before publishing with the download enabled."
HISTORY_ZONE = ZoneInfo("Africa/Johannesburg")
HISTORY_PAGE_SIZES = (25, 50, 100)
HISTORY_FIELDS = set(AUDITED_FIELDS) | {"deleted"}


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


def _check_specification(active: object, enabled: object, stored_name: object) -> None:
    if active is True and enabled is True and not stored_name:
        raise ProductError(SPECIFICATION_REQUIRED)


def create_product(session: Session, fields: dict[str, object], actor: str) -> Product:
    _check_specification(fields.get("active"), fields.get("specification_enabled"), fields.get("specification_stored_name"))
    try:
        product = Product(**fields)
        session.add(product)
        session.flush()
        _record(
            session,
            product.id,
            product.name,
            actor,
            _changes({field: None for field in AUDITED_FIELDS}, fields, include_unchanged=True),
        )
        session.commit()
    except IntegrityError:
        session.rollback()
        raise ProductConflict("A product with that slug or SKU already exists.") from None
    return product


def update_product(
    session: Session,
    product_id: uuid.UUID,
    fields: dict[str, object],
    actor: str,
    image_root: Path | None = None,
) -> Product:
    product = get_product(session, product_id)
    if product is None:
        raise ProductNotFound("The product does not exist.")
    previous = {field: getattr(product, field) for field in AUDITED_FIELDS}
    changes = _changes(previous, fields, include_unchanged=False)
    old_slug = product.slug
    new_slug = fields.get("slug", old_slug)
    _check_specification(
        fields.get("active", product.active),
        fields.get("specification_enabled", product.specification_enabled),
        fields.get("specification_stored_name", product.specification_stored_name),
    )
    moved = False
    if isinstance(new_slug, str) and new_slug != old_slug:
        owned_alias = session.get(ProductSlugAlias, new_slug)
        if owned_alias is not None and owned_alias.product_id == product.id:
            session.delete(owned_alias)
            session.flush()
        session.add(ProductSlugAlias(slug=old_slug, product_id=product.id))
        rewrite_slug_names(session, product.id, old_slug, new_slug)
        if image_root is not None:
            try:
                relocate_slug_directory(image_root, old_slug, new_slug)
            except ImageRejected as exc:
                session.rollback()
                raise ProductError(str(exc)) from None
            moved = True
    for key, value in fields.items():
        setattr(product, key, value)
    if changes:
        recorded_name = fields.get("name", previous.get("name"))
        _record(session, product.id, str(recorded_name or product.name), actor, changes)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        if moved and image_root is not None and isinstance(new_slug, str):
            relocate_slug_directory(image_root, new_slug, old_slug)
        raise ProductConflict("A product with that slug or SKU already exists.") from None
    return product


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


def record_product_deletion(session: Session, product: Product, actor: str) -> None:
    _record(
        session,
        product.id,
        product.name,
        actor,
        [{"field": "deleted", "previous": None, "new": "Permanently deleted"}],
    )


def search_audit_history(
    session: Session,
    *,
    start: date | None,
    end: date | None,
    product: str,
    changed_by: str,
    field: str,
    limit: int,
    offset: int,
) -> dict[str, object]:
    if limit not in HISTORY_PAGE_SIZES:
        raise ProductError("Choose 25, 50, or 100 records per page.")
    if offset < 0:
        raise ProductError("The page is not valid.")
    if len(product) > 160 or len(changed_by) > 254:
        raise ProductError("The filter is too long.")
    if field and field not in HISTORY_FIELDS:
        raise ProductError("That field is not part of the product history.")
    start_at, end_at = _history_window(start, end)
    filters = """
        event.created_at >= :start_at
        AND event.created_at < :end_at
        AND (:product = '' OR event.product_name ILIKE :product ESCAPE '\\')
        AND (:actor = '' OR event.actor ILIKE :actor ESCAPE '\\')
        AND (:field = '' OR change.value->>'field' = :field)
    """
    params = {
        "start_at": start_at,
        "end_at": end_at,
        "product": _contains(product),
        "actor": _contains(changed_by),
        "field": field,
        "limit": limit,
        "offset": offset,
    }
    total = session.scalar(
        text(
            f"""
            SELECT count(*)
            FROM product_audit_events AS event
            CROSS JOIN LATERAL jsonb_array_elements(event.changes) WITH ORDINALITY AS change(value, ordinality)
            WHERE {filters}
            """
        ),
        params,
    )
    total = int(total or 0)
    rows = session.execute(
        text(
            f"""
            SELECT event.id, event.created_at, event.product_id, event.product_name, event.actor, change.value AS change
            FROM product_audit_events AS event
            CROSS JOIN LATERAL jsonb_array_elements(event.changes) WITH ORDINALITY AS change(value, ordinality)
            WHERE {filters}
            ORDER BY event.created_at DESC, event.id DESC, change.ordinality ASC
            LIMIT :limit OFFSET :offset
            """
        ),
        params,
    ).mappings()
    records = []
    for row in rows:
        change = row["change"] if isinstance(row["change"], dict) else {}
        records.append(
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "product_id": row["product_id"],
                "product_name": row["product_name"],
                "actor": row["actor"],
                "field": str(change.get("field") or ""),
                "previous": change.get("previous"),
                "new": change.get("new"),
            }
        )
    pages = math.ceil(total / limit) if total else 0
    return {
        "records": records,
        "total": total,
        "page": (offset // limit) + 1,
        "page_size": limit,
        "total_pages": pages,
    }


def _history_window(start: date | None, end: date | None) -> tuple[datetime, datetime]:
    today = datetime.now(HISTORY_ZONE).date()
    if start is None and end is None:
        end = today
        start = today - timedelta(days=29)
    if start is None or end is None:
        raise ProductError("Choose both a start date and an end date.")
    if start > end:
        raise ProductError("The start date cannot be later than the end date.")
    start_at = datetime.combine(start, time.min, tzinfo=HISTORY_ZONE)
    end_at = datetime.combine(end + timedelta(days=1), time.min, tzinfo=HISTORY_ZONE)
    return start_at, end_at


def _contains(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    escaped = cleaned.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _record(session: Session, product_id: uuid.UUID, product_name: str, actor: str, changes: list[dict[str, object]]) -> None:
    cleaned = actor.strip()
    if not cleaned or len(cleaned) > 254:
        raise ProductError("A product change needs an owner.")
    name = product_name.strip()
    if not name:
        raise ProductError("A product change needs a product name.")
    if not changes:
        return
    session.add(ProductAuditEvent(product_id=product_id, product_name=name[:160], actor=cleaned, changes=changes))
