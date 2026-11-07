"""Gallery rows and specifications. Files stay in PRODUCT_IMAGE_DIR."""

import uuid
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.product import Product, ProductImage, ProductSpecification
from app.products.images import remove_gallery_file, save_gallery_image

MAX_IMAGES = 4
MAX_SPECIFICATIONS = 24


class GalleryError(Exception):
    """A gallery or specification change was rejected."""


def list_images(session: Session, product_id: uuid.UUID) -> list[ProductImage]:
    return list(
        session.scalars(
            select(ProductImage)
            .where(ProductImage.product_id == product_id)
            .order_by(ProductImage.position, ProductImage.created_at, ProductImage.id)
        )
    )


def list_specifications(session: Session, product_id: uuid.UUID) -> list[ProductSpecification]:
    return list(
        session.scalars(
            select(ProductSpecification)
            .where(ProductSpecification.product_id == product_id)
            .order_by(ProductSpecification.position, ProductSpecification.id)
        )
    )


def images_by_product(session: Session, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[ProductImage]]:
    if not product_ids:
        return {}
    rows = session.scalars(
        select(ProductImage)
        .where(ProductImage.product_id.in_(product_ids))
        .order_by(ProductImage.position, ProductImage.created_at, ProductImage.id)
    ).all()
    grouped: dict[uuid.UUID, list[ProductImage]] = {product_id: [] for product_id in product_ids}
    for row in rows:
        grouped.setdefault(row.product_id, []).append(row)
    return grouped


def specifications_by_product(session: Session, product_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[ProductSpecification]]:
    if not product_ids:
        return {}
    rows = session.scalars(
        select(ProductSpecification)
        .where(ProductSpecification.product_id.in_(product_ids))
        .order_by(ProductSpecification.position, ProductSpecification.id)
    ).all()
    grouped: dict[uuid.UUID, list[ProductSpecification]] = {product_id: [] for product_id in product_ids}
    for row in rows:
        grouped.setdefault(row.product_id, []).append(row)
    return grouped


def add_image(session: Session, product: Product, directory: Path, data: bytes) -> ProductImage:
    current = list_images(session, product.id)
    if len(current) >= MAX_IMAGES:
        raise GalleryError(f"A product can have up to {MAX_IMAGES} images.")
    stored_name, thumb_name = save_gallery_image(directory, product.slug, data)
    image = ProductImage(product_id=product.id, stored_name=stored_name, thumb_name=thumb_name, position=len(current))
    session.add(image)
    session.commit()
    return image


def replace_image(session: Session, product: Product, image_id: uuid.UUID, directory: Path, data: bytes) -> ProductImage:
    image = session.get(ProductImage, image_id)
    if image is None or image.product_id != product.id:
        raise GalleryError("The image does not exist.")
    stored_name, thumb_name = save_gallery_image(directory, product.slug, data)
    previous = (image.stored_name, image.thumb_name)
    image.stored_name = stored_name
    image.thumb_name = thumb_name
    session.commit()
    _remove_unused(session, directory, previous)
    return image


def remove_image(session: Session, product: Product, image_id: uuid.UUID, directory: Path) -> None:
    image = session.get(ProductImage, image_id)
    if image is None or image.product_id != product.id:
        raise GalleryError("The image does not exist.")
    previous = (image.stored_name, image.thumb_name)
    session.delete(image)
    session.flush()
    _resequence(session, product.id)
    session.commit()
    _remove_unused(session, directory, previous)


def reorder_images(session: Session, product: Product, image_ids: list[uuid.UUID]) -> list[ProductImage]:
    current = list_images(session, product.id)
    current_ids = [row.id for row in current]
    if sorted(image_ids, key=str) != sorted(current_ids, key=str) or len(image_ids) != len(current_ids):
        raise GalleryError("Include every product image when reordering.")
    positions = {image_id: index for index, image_id in enumerate(image_ids)}
    for row in current:
        row.position = positions[row.id]
    session.commit()
    return list_images(session, product.id)


def replace_specifications(session: Session, product: Product, rows: list[tuple[str, str]]) -> list[ProductSpecification]:
    if len(rows) > MAX_SPECIFICATIONS:
        raise GalleryError(f"A product can have up to {MAX_SPECIFICATIONS} specifications.")
    session.execute(delete(ProductSpecification).where(ProductSpecification.product_id == product.id))
    for index, (label, value) in enumerate(rows):
        session.add(ProductSpecification(product_id=product.id, label=label, value=value, position=index))
    session.commit()
    return list_specifications(session, product.id)


def rewrite_slug_names(session: Session, product_id: uuid.UUID, old_slug: str, new_slug: str) -> None:
    if old_slug == new_slug:
        return
    prefix = old_slug + "/"
    replacement = new_slug + "/"
    for image in list_images(session, product_id):
        if image.stored_name.startswith(prefix):
            image.stored_name = replacement + image.stored_name[len(prefix) :]
        if image.thumb_name and image.thumb_name.startswith(prefix):
            image.thumb_name = replacement + image.thumb_name[len(prefix) :]


def _resequence(session: Session, product_id: uuid.UUID) -> None:
    for index, image in enumerate(list_images(session, product_id)):
        image.position = index


def _remove_unused(session: Session, directory: Path, names: tuple[str | None, str | None]) -> None:
    for name in names:
        if not name:
            continue
        still_used = session.scalar(
            select(func.count())
            .select_from(ProductImage)
            .where((ProductImage.stored_name == name) | (ProductImage.thumb_name == name))
        )
        legacy_used = session.scalar(select(func.count()).select_from(Product).where(Product.image_filename == name))
        if not still_used and not legacy_used:
            remove_gallery_file(directory, name)
