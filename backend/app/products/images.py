"""One stored product image. The saved name is generated here, not taken from the upload."""

import re
import secrets
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import Settings, get_settings

MAX_IMAGE_BYTES = 5 * 1024 * 1024
IMAGE_NAME = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp)$")
MEDIA_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}

router = APIRouter()


class ImageRejected(Exception):
    """The upload is not one supported product image."""


def image_directory(settings: Settings) -> Path:
    path = Path(settings.product_image_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def image_kind(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def public_image_url(filename: str | None) -> str | None:
    if filename is None or not IMAGE_NAME.fullmatch(filename):
        return None
    return "/media/products/" + filename


def save_product_image(directory: Path, data: bytes) -> str:
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ImageRejected("The image is too large. Use a JPEG, PNG, or WebP under 5 MB.")
    kind = image_kind(data)
    if kind is None:
        raise ImageRejected("Use a JPEG, PNG, or WebP image.")
    directory.mkdir(parents=True, exist_ok=True)
    filename = secrets.token_hex(16) + "." + kind
    (directory / filename).write_bytes(data)
    return filename


def remove_product_image(directory: Path, filename: str | None) -> None:
    if filename is None or not IMAGE_NAME.fullmatch(filename):
        return
    path = directory / filename
    if path.is_file():
        path.unlink()


def _stored_file(filename: str) -> Path | None:
    if not IMAGE_NAME.fullmatch(filename):
        return None
    path = image_directory(get_settings()) / filename
    if not path.is_file():
        return None
    return path


@router.get("/media/products/{filename}")
def product_image(filename: str) -> FileResponse:
    path = _stored_file(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="The image does not exist.")
    return FileResponse(path, media_type=MEDIA_TYPES[path.suffix[1:]])
