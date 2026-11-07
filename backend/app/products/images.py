"""One stored product image. The saved name is generated here, not taken from the upload."""

import io
import re
import secrets
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.core.config import Settings, get_settings

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_SOURCE_EDGE = 8000
MAIN_EDGE = 1600
THUMB_EDGE = 480
IMAGE_NAME = re.compile(r"^[0-9a-f]{32}\.(jpg|png|webp)$")
GALLERY_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*/[0-9a-f]{16}(?:-thumb)?\.webp$")
SLUG_DIR = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
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
    if filename is None or not (IMAGE_NAME.fullmatch(filename) or GALLERY_NAME.fullmatch(filename)):
        return None
    return "/media/products/" + filename


def _inside(directory: Path, relative: str) -> Path | None:
    if not GALLERY_NAME.fullmatch(relative):
        return None
    root = directory.resolve()
    path = (directory / relative).resolve()
    if not path.is_relative_to(root):
        return None
    return path


def save_gallery_image(directory: Path, slug: str, data: bytes) -> tuple[str, str]:
    """Store a WebP main image and thumbnail under the product slug directory."""
    if not SLUG_DIR.fullmatch(slug):
        raise ImageRejected("The product slug cannot be used for image storage.")
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ImageRejected("The image is too large. Use a JPEG, PNG, or WebP under 5 MB.")
    if image_kind(data) is None:
        raise ImageRejected("Use a JPEG, PNG, or WebP image.")
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise ImageRejected("The image could not be prepared.") from exc
    try:
        with Image.open(io.BytesIO(data)) as source:
            source.load()
            if source.width > MAX_SOURCE_EDGE or source.height > MAX_SOURCE_EDGE:
                raise ImageRejected("The image dimensions are too large.")
            prepared = source.convert("RGBA") if source.mode in {"RGBA", "LA", "P"} else source.convert("RGB")
            main = prepared.copy()
            main.thumbnail((MAIN_EDGE, MAIN_EDGE))
            thumb = prepared.copy()
            thumb.thumbnail((THUMB_EDGE, THUMB_EDGE))
    except ImageRejected:
        raise
    except (UnidentifiedImageError, OSError) as exc:
        raise ImageRejected("Use a JPEG, PNG, or WebP image.") from exc
    directory.mkdir(parents=True, exist_ok=True)
    folder = directory / slug
    folder.mkdir(parents=True, exist_ok=True)
    token = secrets.token_hex(8)
    main_name = f"{slug}/{token}.webp"
    thumb_name = f"{slug}/{token}-thumb.webp"
    main_path = _inside(directory, main_name)
    thumb_path = _inside(directory, thumb_name)
    if main_path is None or thumb_path is None:
        raise ImageRejected("The image could not be stored.")
    main.save(main_path, "WEBP", quality=82, method=4)
    thumb.save(thumb_path, "WEBP", quality=76, method=4)
    return main_name, thumb_name


def remove_gallery_file(directory: Path, relative: str | None) -> None:
    if relative is None:
        return
    if IMAGE_NAME.fullmatch(relative):
        remove_product_image(directory, relative)
        return
    path = _inside(directory, relative)
    if path is not None and path.is_file():
        path.unlink()


def relocate_slug_directory(directory: Path, old_slug: str, new_slug: str) -> None:
    if old_slug == new_slug or not SLUG_DIR.fullmatch(old_slug) or not SLUG_DIR.fullmatch(new_slug):
        return
    source = (directory / old_slug).resolve()
    root = directory.resolve()
    if not source.is_relative_to(root) or not source.is_dir():
        return
    destination = (directory / new_slug).resolve()
    if not destination.is_relative_to(root) or destination.exists():
        raise ImageRejected("The image folder could not be moved for the new slug.")
    source.rename(destination)


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


def _named_file(directory: Path, filename: str) -> Path | None:
    if not IMAGE_NAME.fullmatch(filename):
        return None
    path = directory / filename
    if not path.is_file():
        return None
    return path


@router.get("/media/products/{product_slug}/{filename}")
def gallery_image(product_slug: str, filename: str) -> FileResponse:
    relative = product_slug + "/" + filename
    path = _inside(image_directory(get_settings()), relative)
    if path is None or not path.is_file():
        raise HTTPException(status_code=404, detail="The image does not exist.")
    return FileResponse(path, media_type="image/webp")


@router.get("/media/products/{filename}")
def product_image(filename: str) -> FileResponse:
    path = _stored_file(filename)
    if path is None:
        raise HTTPException(status_code=404, detail="The image does not exist.")
    return FileResponse(path, media_type=MEDIA_TYPES[path.suffix[1:]])


@router.get("/media/carousel/{filename}")
def carousel_image(filename: str) -> FileResponse:
    settings = get_settings()
    directory = Path(settings.carousel_image_dir)
    if not directory.is_absolute():
        directory = Path.cwd() / directory
    path = _named_file(directory, filename)
    if path is None:
        raise HTTPException(status_code=404, detail="The image does not exist.")
    return FileResponse(path, media_type=MEDIA_TYPES[path.suffix[1:]])
