"""Public and owner homepage carousel."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.v1.auth import require_csrf, require_owner
from app.carousel.service import (
    SlideNotFound,
    SlideRejected,
    carousel_directory,
    clean_text,
    create_slide,
    delete_slide,
    get_slide,
    list_slides,
    slide_payload,
    update_slide,
)
from app.core.config import get_settings
from app.db.session import get_session
from app.products.images import ImageRejected, remove_product_image, save_product_image

router = APIRouter(prefix="/carousel", tags=["carousel"])
admin_router = APIRouter(prefix="/carousel", tags=["admin"])


class SlideChange(BaseModel):
    title: str | None = None
    message: str | None = None
    display_order: int | None = Field(default=None, ge=0, le=9999)
    enabled: bool | None = None


def _fields(title: str | None, message: str | None, display_order: int, enabled: bool) -> dict:
    if display_order < 0 or display_order > 9999:
        raise SlideRejected("Choose a display order from 0 to 9999.")
    return {
        "title": clean_text(title, 120),
        "message": clean_text(message, 280),
        "display_order": display_order,
        "enabled": enabled,
    }


@router.get("")
def public_slides(session: Annotated[Session, Depends(get_session)]) -> dict:
    try:
        slides = list_slides(session, enabled_only=True)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="The carousel is temporarily unavailable.") from exc
    return {"slides": [slide_payload(slide) for slide in slides]}


@admin_router.get("")
def owner_slides(
    session: Annotated[Session, Depends(get_session)],
    _: Annotated[object, Depends(require_owner)],
) -> dict:
    try:
        slides = list_slides(session, enabled_only=False)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="The carousel is temporarily unavailable.") from exc
    return {"slides": [slide_payload(slide) for slide in slides]}


@admin_router.post("", status_code=201)
async def owner_create(
    session: Annotated[Session, Depends(get_session)],
    _: Annotated[object, Depends(require_csrf)],
    image: UploadFile = File(...),
    title: str = Form(""),
    message: str = Form(""),
    display_order: int = Form(0),
    enabled: str = Form("true"),
) -> dict:
    data = await image.read()
    directory = carousel_directory(get_settings())
    filename = None
    try:
        filename = save_product_image(directory, data)
        slide = create_slide(
            session,
            filename,
            _fields(title, message, display_order, enabled.strip().lower() in {"1", "true", "yes", "on"}),
        )
    except (ImageRejected, SlideRejected) as exc:
        remove_product_image(directory, filename)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        remove_product_image(directory, filename)
        raise HTTPException(status_code=503, detail="The slide could not be saved.") from exc
    return slide_payload(slide)


@admin_router.patch("/{slide_id}")
def owner_update(
    slide_id: uuid.UUID,
    body: SlideChange,
    session: Annotated[Session, Depends(get_session)],
    _: Annotated[object, Depends(require_csrf)],
) -> dict:
    changes = body.model_dump(exclude_unset=True)
    try:
        if "title" in changes:
            changes["title"] = clean_text(changes["title"], 120)
        if "message" in changes:
            changes["message"] = clean_text(changes["message"], 280)
        slide = update_slide(session, slide_id, changes)
    except SlideNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SlideRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="The slide could not be saved.") from exc
    return slide_payload(slide)


@admin_router.post("/{slide_id}/image")
async def owner_replace_image(
    slide_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    _: Annotated[object, Depends(require_csrf)],
    image: UploadFile = File(...),
) -> dict:
    data = await image.read()
    directory = carousel_directory(get_settings())
    try:
        current = get_slide(session, slide_id)
        filename = save_product_image(directory, data)
        previous = current.image_filename
        slide = update_slide(session, slide_id, {"image_filename": filename})
    except SlideNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ImageRejected as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        remove_product_image(directory, filename if "filename" in locals() else None)
        raise HTTPException(status_code=503, detail="The image could not be saved.") from exc
    remove_product_image(directory, previous)
    return slide_payload(slide)


@admin_router.delete("/{slide_id}", status_code=204)
def owner_delete(
    slide_id: uuid.UUID,
    session: Annotated[Session, Depends(get_session)],
    _: Annotated[object, Depends(require_csrf)],
) -> None:
    directory = carousel_directory(get_settings())
    try:
        filename = delete_slide(session, slide_id)
    except SlideNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="The slide could not be deleted.") from exc
    remove_product_image(directory, filename)
