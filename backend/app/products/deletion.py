"""Permanent product deletion.

Rows are removed in one transaction. The product's files are listed in file_cleanups
inside that same transaction and removed from disk only after it commits, so a rollback
never loses a file and a failed removal stays recorded for retry.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.audit import ProductAuditEvent
from app.models.carousel import CarouselSlide
from app.models.file_cleanup import FileCleanup
from app.models.product import Product, ProductImage, ProductSlugAlias, ProductSpecification
from app.products.images import image_directory, remove_empty_slug_directory, stored_image_path
from app.products.service import ProductNotFound, get_product
from app.products.specifications import specification_directory, stored_specification_path

logger = logging.getLogger(__name__)

IMAGES = "product_images"
SPECIFICATIONS = "product_specifications"


@dataclass(frozen=True)
class StorageRoots:
    images: Path
    specifications: Path
    carousel: Path


@dataclass(frozen=True)
class DeletionResult:
    product_id: uuid.UUID
    files_removed: int
    files_pending: int


def storage_roots(settings: Settings) -> StorageRoots:
    carousel = Path(settings.carousel_image_dir)
    if not carousel.is_absolute():
        carousel = Path.cwd() / carousel
    return StorageRoots(image_directory(settings), specification_directory(settings), carousel)


def delete_product_permanently(session: Session, product_id: uuid.UUID, roots: StorageRoots, actor: str) -> DeletionResult:
    product = get_product(session, product_id)
    if product is None:
        raise ProductNotFound("The product does not exist.")
    slug = product.slug
    images = session.scalars(select(ProductImage).where(ProductImage.product_id == product.id)).all()
    image_names = {name for image in images for name in (image.stored_name, image.thumb_name) if name}
    if product.image_filename:
        image_names.add(product.image_filename)
    sheet_names = {product.specification_stored_name} if product.specification_stored_name else set()
    folders = {slug} | {name.split("/", 1)[0] for name in image_names if "/" in name}
    try:
        session.execute(delete(ProductAuditEvent).where(ProductAuditEvent.product_id == product.id))
        session.execute(delete(ProductImage).where(ProductImage.product_id == product.id))
        session.execute(delete(ProductSpecification).where(ProductSpecification.product_id == product.id))
        session.execute(delete(ProductSlugAlias).where(ProductSlugAlias.product_id == product.id))
        session.delete(product)
        session.flush()
        queued = [
            _queue(session, IMAGES, name, product_id)
            for name in sorted(image_names)
            if not _in_use(session, IMAGES, name, roots)
        ]
        queued += [
            _queue(session, SPECIFICATIONS, name, product_id)
            for name in sorted(sheet_names)
            if not _in_use(session, SPECIFICATIONS, name, roots)
        ]
        session.flush()
        queued_ids = [row.id for row in queued]
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    logger.info("Product %s (%s) was permanently deleted by %s.", product_id, slug, actor)
    pending = run_file_cleanups(session, roots, queued_ids)
    for folder in folders:
        remove_empty_slug_directory(roots.images, folder)
    return DeletionResult(product_id=product_id, files_removed=len(queued_ids) - len(pending), files_pending=len(pending))


def run_file_cleanups(session: Session, roots: StorageRoots, ids: list[uuid.UUID] | None = None) -> list[uuid.UUID]:
    """Remove queued files. Rows that fail stay queued with the error so they can be retried."""
    statement = select(FileCleanup).order_by(FileCleanup.created_at, FileCleanup.id)
    if ids is not None:
        if not ids:
            return []
        statement = statement.where(FileCleanup.id.in_(ids))
    pending: list[uuid.UUID] = []
    for row in session.scalars(statement).all():
        if _in_use(session, row.storage, row.stored_name, roots):
            logger.warning("Kept %s file %s because another record still uses it.", row.storage, row.stored_name)
            session.delete(row)
            continue
        try:
            _remove(row, roots)
        except (OSError, ValueError) as exc:
            row.attempts += 1
            row.last_error = _describe(exc)
            row.last_attempt_at = datetime.now(timezone.utc)
            pending.append(row.id)
            logger.error(
                "Could not remove %s file %s for deleted product %s: %s. It stays queued in file_cleanups for retry.",
                row.storage,
                row.stored_name,
                row.product_id,
                row.last_error,
            )
            continue
        session.delete(row)
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        logger.exception("File cleanup results could not be saved. The queued files will be checked again on retry.")
    return pending


def _queue(session: Session, storage: str, name: str, product_id: uuid.UUID) -> FileCleanup:
    existing = session.scalar(select(FileCleanup).where(FileCleanup.storage == storage, FileCleanup.stored_name == name))
    if existing is not None:
        existing.product_id = product_id
        return existing
    row = FileCleanup(storage=storage, stored_name=name, product_id=product_id)
    session.add(row)
    return row


def _in_use(session: Session, storage: str, name: str, roots: StorageRoots) -> bool:
    if storage == SPECIFICATIONS:
        return bool(session.scalar(select(func.count()).select_from(Product).where(Product.specification_stored_name == name)))
    gallery = session.scalar(
        select(func.count())
        .select_from(ProductImage)
        .where(or_(ProductImage.stored_name == name, ProductImage.thumb_name == name))
    )
    legacy = session.scalar(select(func.count()).select_from(Product).where(Product.image_filename == name))
    shared_folder = roots.carousel.resolve() == roots.images.resolve()
    carousel = shared_folder and session.scalar(
        select(func.count()).select_from(CarouselSlide).where(CarouselSlide.image_filename == name)
    )
    return bool(gallery or legacy or carousel)


def _remove(row: FileCleanup, roots: StorageRoots) -> None:
    if row.storage == IMAGES:
        path = stored_image_path(roots.images, row.stored_name)
    elif row.storage == SPECIFICATIONS:
        path = stored_specification_path(roots.specifications, row.stored_name)
    else:
        path = None
    if path is None:
        raise ValueError("The stored name is not a file this service manages.")
    path.unlink(missing_ok=True)


def _describe(exc: Exception) -> str:
    if isinstance(exc, OSError):
        detail = exc.strerror or exc.__class__.__name__
        return f"{exc.__class__.__name__}: {detail}"[:240]
    return str(exc)[:240]
