"""Homepage carousel slides."""

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.carousel import CarouselSlide
from app.products.images import IMAGE_NAME


class SlideNotFound(Exception):
    pass


class SlideRejected(Exception):
    pass


def carousel_directory(settings: Settings) -> Path:
    path = Path(settings.carousel_image_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def public_slide_image(filename: str | None) -> str | None:
    if filename is None or not IMAGE_NAME.fullmatch(filename):
        return None
    return "/media/carousel/" + filename


def clean_text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    text = " ".join(value.split())
    if not text:
        return None
    if len(text) > limit:
        raise SlideRejected("One of the text fields is too long.")
    return text


def list_slides(session: Session, *, enabled_only: bool) -> list[CarouselSlide]:
    statement = select(CarouselSlide)
    if enabled_only:
        statement = statement.where(CarouselSlide.enabled.is_(True))
    statement = statement.order_by(CarouselSlide.display_order.asc(), CarouselSlide.created_at.asc())
    return list(session.scalars(statement))


def get_slide(session: Session, slide_id: uuid.UUID) -> CarouselSlide:
    slide = session.get(CarouselSlide, slide_id)
    if slide is None:
        raise SlideNotFound("The slide could not be found.")
    return slide


def create_slide(session: Session, filename: str, fields: dict) -> CarouselSlide:
    slide = CarouselSlide(image_filename=filename, **fields)
    session.add(slide)
    session.commit()
    session.refresh(slide)
    return slide


def update_slide(session: Session, slide_id: uuid.UUID, changes: dict) -> CarouselSlide:
    slide = get_slide(session, slide_id)
    for key, value in changes.items():
        setattr(slide, key, value)
    session.commit()
    session.refresh(slide)
    return slide


def delete_slide(session: Session, slide_id: uuid.UUID) -> str:
    slide = get_slide(session, slide_id)
    filename = slide.image_filename
    session.delete(slide)
    session.commit()
    return filename


def slide_payload(slide: CarouselSlide) -> dict:
    return {
        "id": slide.id,
        "image_url": public_slide_image(slide.image_filename),
        "title": slide.title,
        "message": slide.message,
        "display_order": slide.display_order,
        "enabled": slide.enabled,
        "created_at": slide.created_at,
        "updated_at": slide.updated_at,
    }

