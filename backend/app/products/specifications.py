"""One optional PDF specification sheet per product. Files stay outside the website directory."""

import os
import re
import secrets
from pathlib import Path

from app.core.config import Settings

MAX_SPECIFICATION_BYTES = 25 * 1024 * 1024
PDF_TYPE = "application/pdf"
DECLARED_TYPES = {"application/pdf", "application/x-pdf"}
STORED_NAME = re.compile(r"^[0-9a-f]{32}\.pdf$")
DEFAULT_DOWNLOAD_NAME = "specification-sheet.pdf"


class SpecificationRejected(Exception):
    """The upload cannot be stored as a specification sheet."""


def specification_directory(settings: Settings) -> Path:
    path = Path(settings.product_specification_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def max_specification_bytes(settings: Settings) -> int:
    limit = settings.product_specification_max_bytes
    if limit < 1:
        return MAX_SPECIFICATION_BYTES
    return limit


def inspect_specification(data: bytes, upload_name: str, declared_type: str | None) -> None:
    if not data:
        raise SpecificationRejected("Choose a PDF file to upload.")
    name = Path((upload_name or "").replace("\\", "/")).name
    if not name.lower().endswith(".pdf"):
        raise SpecificationRejected("Upload the specification sheet as a PDF file.")
    declared = (declared_type or "").split(";", 1)[0].strip().lower()
    if declared not in DECLARED_TYPES:
        raise SpecificationRejected("Upload the specification sheet as a PDF file.")
    if not data.startswith(b"%PDF-") or b"%%EOF" not in data[-2048:]:
        raise SpecificationRejected("The file is not a valid PDF document.")


def save_specification(
    directory: Path,
    data: bytes,
    upload_name: str,
    declared_type: str | None,
    limit: int,
) -> tuple[str, int]:
    if len(data) > limit:
        raise SpecificationRejected(f"The file is too large. The limit is {limit // (1024 * 1024) or 1} MB.")
    inspect_specification(data, upload_name, declared_type)
    directory.mkdir(parents=True, exist_ok=True)
    stored = secrets.token_hex(16) + ".pdf"
    path = _stored_path(directory, stored)
    if path is None:
        raise SpecificationRejected("The file could not be stored.")
    partial = path.with_name(path.name + ".part")
    partial.write_bytes(data)
    os.replace(partial, path)
    return stored, len(data)


def remove_specification(directory: Path, stored_name: str | None) -> None:
    path = _stored_path(directory, stored_name)
    if path is not None and path.is_file():
        path.unlink()


def open_specification(directory: Path, stored_name: str | None) -> Path | None:
    path = _stored_path(directory, stored_name)
    if path is None or not path.is_file():
        return None
    return path


def original_name(upload_name: str | None) -> str:
    name = Path((upload_name or "").replace("\\", "/")).name
    name = "".join(character for character in name if character.isprintable()).strip()
    if not name or name in {".", ".."}:
        return DEFAULT_DOWNLOAD_NAME
    return name[:160]


def public_specification_name(original: str | None) -> str:
    cleaned = Path((original or "").replace("\\", "/")).name
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    if cleaned.lower().endswith(".pdf"):
        cleaned = cleaned[:-4].rstrip(". ")
    if not cleaned:
        return DEFAULT_DOWNLOAD_NAME
    return cleaned[:116] + ".pdf"


def _stored_path(directory: Path, stored_name: str | None) -> Path | None:
    if stored_name is None or not STORED_NAME.fullmatch(stored_name):
        return None
    root = directory.resolve()
    path = (directory / stored_name).resolve()
    if path.parent != root:
        return None
    return path
