"""Optional product downloads. Files stay outside the public website directory."""

import re
import secrets
import zipfile
from io import BytesIO
from pathlib import Path

from app.core.config import Settings

MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
STORED_NAME = re.compile(r"^[0-9a-f]{32}\.(pdf|doc|docx|xls|xlsx|zip)$")
OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
KIND_TYPES = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "zip": "application/zip",
}
DECLARED_TYPES = {
    "pdf": {"application/pdf", "application/octet-stream"},
    "doc": {"application/msword", "application/octet-stream"},
    "docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/octet-stream",
    },
    "xls": {"application/vnd.ms-excel", "application/octet-stream"},
    "xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    },
    "zip": {"application/zip", "application/x-zip-compressed", "application/octet-stream"},
}


class DownloadRejected(Exception):
    """The upload cannot be stored as a product download."""


def download_directory(settings: Settings) -> Path:
    path = Path(settings.product_download_dir)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def max_download_bytes(settings: Settings) -> int:
    limit = settings.product_download_max_bytes
    if limit < 1:
        return MAX_DOWNLOAD_BYTES
    return limit


def inspect_download(data: bytes, upload_name: str, declared_type: str | None = None) -> tuple[str, str]:
    if not data:
        raise DownloadRejected("Choose a file to upload.")
    if data.startswith((b"MZ", b"\x7fELF", b"#!")):
        raise DownloadRejected("That file type cannot be uploaded.")
    suffix = Path(upload_name or "").name.lower().rsplit(".", 1)[-1] if "." in Path(upload_name or "").name else ""
    if suffix not in KIND_TYPES:
        raise DownloadRejected("Use a PDF, Word, Excel, or ZIP file.")
    declared = (declared_type or "").split(";", 1)[0].strip().lower()
    if declared and declared not in DECLARED_TYPES[suffix]:
        raise DownloadRejected("The file type is not allowed.")
    kind = _kind_from_bytes(data)
    if suffix in {"doc", "xls"}:
        if kind != "ole":
            raise DownloadRejected("The file contents do not match a PDF, Word, Excel, or ZIP file.")
    elif kind != suffix:
        raise DownloadRejected("The file contents do not match a PDF, Word, Excel, or ZIP file.")
    return suffix, KIND_TYPES[suffix]


def save_download(
    directory: Path,
    data: bytes,
    upload_name: str,
    limit: int,
    declared_type: str | None = None,
) -> tuple[str, str, int]:
    if len(data) > limit:
        raise DownloadRejected("The file is too large. The limit is 25 MB.")
    kind, content_type = inspect_download(data, upload_name, declared_type)
    directory.mkdir(parents=True, exist_ok=True)
    stored = secrets.token_hex(16) + "." + kind
    path = _stored_path(directory, stored)
    if path is None:
        raise DownloadRejected("The file could not be stored.")
    path.write_bytes(data)
    return stored, content_type, len(data)


def remove_download(directory: Path, stored_name: str | None) -> None:
    path = _stored_path(directory, stored_name)
    if path is not None and path.is_file():
        path.unlink()


def open_download(directory: Path, stored_name: str | None) -> Path | None:
    path = _stored_path(directory, stored_name)
    if path is None or not path.is_file():
        return None
    return path


def public_download_name(original: str | None, stored_name: str) -> str:
    extension = stored_name.rsplit(".", 1)[-1]
    cleaned = Path(original or "").name
    cleaned = re.sub(r"[^A-Za-z0-9._ -]", "", cleaned).strip().strip(".")
    if not cleaned:
        cleaned = "download." + extension
    if not cleaned.lower().endswith("." + extension):
        cleaned = cleaned[:110] + "." + extension
    return cleaned[:120]


def _stored_path(directory: Path, stored_name: str | None) -> Path | None:
    if stored_name is None or not STORED_NAME.fullmatch(stored_name):
        return None
    root = directory.resolve()
    path = (directory / stored_name).resolve()
    if not path.is_relative_to(root) or path.parent != root:
        return None
    return path


def _kind_from_bytes(data: bytes) -> str | None:
    if data.startswith(b"%PDF"):
        return "pdf"
    if data.startswith(OLE):
        return "ole"
    if data.startswith(b"PK\x03\x04"):
        return _zip_kind(data)
    return None


def _zip_kind(data: bytes) -> str | None:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = {item.replace("\\", "/") for item in archive.namelist()}
    except zipfile.BadZipFile:
        return None
    if any(name == "word/document.xml" or name.startswith("word/") for name in names):
        return "docx"
    if any(name == "xl/workbook.xml" or name.startswith("xl/") for name in names):
        return "xlsx"
    return "zip"
