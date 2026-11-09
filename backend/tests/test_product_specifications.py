"""Optional product downloads. Existing products stay available without a file."""

import io
import re
import urllib.parse
import zipfile

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from tests.test_owner_products import PRODUCT, _cookie, _login, _owner, _use_database, client

STORED = re.compile(r"^[0-9a-f]{32}\.(pdf|doc|docx|xls|xlsx|zip)$")
OLE = bytes.fromhex("d0cf11e0a1b11ae1") + b"\x00" * 64


def _prepare(monkeypatch, database_url: str, directory, max_bytes: int | None = None) -> None:
    _use_database(monkeypatch, database_url)
    monkeypatch.setenv("PRODUCT_DOWNLOAD_DIR", str(directory))
    if max_bytes is not None:
        monkeypatch.setenv("PRODUCT_DOWNLOAD_MAX_BYTES", str(max_bytes))
    get_settings.cache_clear()
    _owner(database_url)
    _login()


def _headers() -> dict[str, str]:
    return {"X-CSRF-Token": _cookie("autonovent_csrf")}


def _product(slug: str, *, active: bool = True) -> dict:
    created = client.post(
        "/api/v1/admin/products",
        json={**PRODUCT, "slug": slug, "sku": slug.upper(), "active": active, "unit_price_cents": 1500},
        headers=_headers(),
    )
    assert created.status_code == 201
    body = created.json()
    assert body["download_enabled"] is False
    assert body["download_configured"] is False
    return body


def _upload(product_id: str, name: str, data: bytes, content_type: str):
    return client.post(
        f"/api/v1/admin/products/{product_id}/download",
        files={"download": (name, data, content_type)},
        headers=_headers(),
    )


def _pdf() -> bytes:
    return b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def _zip(kind: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if kind == "docx":
            archive.writestr("word/document.xml", "<document/>")
        elif kind == "xlsx":
            archive.writestr("xl/workbook.xml", "<workbook/>")
        else:
            archive.writestr("readme.txt", "hello")
    return buffer.getvalue()


def test_a_product_without_a_download_keeps_working(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    _prepare(monkeypatch, isolated_database_url, tmp_path)
    assert get_settings().product_download_max_bytes == 25 * 1024 * 1024
    product = _product("plain-product")
    public = client.get("/api/v1/products/plain-product")
    assert public.status_code == 200
    assert public.json()["download_enabled"] is False
    assert public.json()["download_filename"] is None
    assert "download_stored_name" not in public.json()
    assert client.get("/api/v1/products/plain-product/download").status_code == 404
    blocked = client.patch(
        f"/api/v1/admin/products/{product['id']}",
        json={"download_enabled": True},
        headers=_headers(),
    )
    assert blocked.status_code == 422
    assert list(tmp_path.iterdir()) == []


def test_owner_can_upload_replace_disable_and_remove_a_download(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    _prepare(monkeypatch, isolated_database_url, tmp_path)
    product = _product("guided-product")
    uploaded = _upload(product["id"], "Installation Guide.pdf", _pdf(), "application/pdf")
    assert uploaded.status_code == 200
    saved = uploaded.json()
    assert saved["download_configured"] is True
    assert saved["download_enabled"] is False
    assert saved["download_original_name"] == "Installation Guide.pdf"
    assert "download_stored_name" not in saved
    assert str(tmp_path) not in uploaded.text
    stored = [path.name for path in tmp_path.iterdir()]
    assert len(stored) == 1 and STORED.fullmatch(stored[0])

    enabled = client.patch(
        f"/api/v1/admin/products/{product['id']}",
        json={"download_enabled": True, "download_button_label": "Download Installation Guide"},
        headers=_headers(),
    )
    assert enabled.status_code == 200
    public = client.get("/api/v1/products/guided-product")
    assert public.json()["download_enabled"] is True
    assert public.json()["download_label"] == "Download Installation Guide"
    assert public.json()["download_filename"] == "Installation Guide.pdf"
    assert stored[0] not in public.text
    downloaded = client.get("/api/v1/products/guided-product/download")
    assert downloaded.status_code == 200
    assert downloaded.content == _pdf()
    disposition = downloaded.headers["content-disposition"]
    assert disposition.lower().startswith("attachment;")
    assert "Installation Guide.pdf" in urllib.parse.unquote(disposition)
    assert downloaded.headers["x-robots-tag"] == "noindex"
    assert str(tmp_path) not in disposition

    replacement = _pdf() + b"\n% replacement\n"
    replaced = _upload(product["id"], "Updated Guide.pdf", replacement, "application/pdf")
    assert replaced.status_code == 200
    assert replaced.json()["download_original_name"] == "Updated Guide.pdf"
    assert [path.name for path in tmp_path.iterdir()] != stored
    assert client.get("/api/v1/products/guided-product/download").content == replacement

    disabled = client.patch(
        f"/api/v1/admin/products/{product['id']}",
        json={"download_enabled": False},
        headers=_headers(),
    )
    assert disabled.status_code == 200
    assert disabled.json()["download_configured"] is True
    assert client.get("/api/v1/products/guided-product/download").status_code == 404
    assert client.get("/api/v1/products/guided-product").json()["download_enabled"] is False
    restored = client.patch(
        f"/api/v1/admin/products/{product['id']}",
        json={"download_enabled": True},
        headers=_headers(),
    )
    assert restored.status_code == 200
    assert client.get("/api/v1/products/guided-product/download").status_code == 200

    removed = client.delete(f"/api/v1/admin/products/{product['id']}/download", headers=_headers())
    assert removed.status_code == 200
    assert removed.json()["download_configured"] is False
    assert removed.json()["download_enabled"] is False
    assert list(tmp_path.iterdir()) == []
    again = client.patch(
        f"/api/v1/admin/products/{product['id']}",
        json={"download_enabled": True},
        headers=_headers(),
    )
    assert again.status_code == 422


def test_download_files_are_checked_and_unsafe_names_stay_inside_storage(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    _prepare(monkeypatch, isolated_database_url, tmp_path)
    product = _product("files-product")
    samples = {
        "notes.doc": (OLE, "application/msword"),
        "notes.docx": (_zip("docx"), "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
        "sheet.xls": (OLE, "application/vnd.ms-excel"),
        "sheet.xlsx": (_zip("xlsx"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        "bundle.zip": (_zip("zip"), "application/zip"),
    }
    for name, (data, content_type) in samples.items():
        uploaded = _upload(product["id"], name, data, content_type)
        assert uploaded.status_code == 200, uploaded.text
        assert uploaded.json()["download_original_name"] == name

    rejected = [
        ("program.exe", _pdf(), "application/pdf"),
        ("notes.pdf", b"MZ" + _pdf(), "application/pdf"),
        ("notes.pdf", _pdf(), "text/html"),
        ("notes.txt", _pdf(), "application/pdf"),
        ("../../secret.pdf", b"not a pdf", "application/pdf"),
    ]
    for name, data, content_type in rejected:
        response = _upload(product["id"], name, data, content_type)
        assert response.status_code == 422

    outside = tmp_path.parent / "secret.pdf"
    assert not outside.exists()
    traversed = _upload(product["id"], "../../secret.pdf", _pdf(), "application/pdf")
    assert traversed.status_code == 200
    assert traversed.json()["download_original_name"] == "secret.pdf"
    assert all(STORED.fullmatch(path.name) and path.parent == tmp_path for path in tmp_path.iterdir())
    assert not outside.exists()


def test_oversized_anonymous_csrf_unpublished_and_missing_downloads_are_refused(
    monkeypatch, isolated_database_url: str, tmp_path
) -> None:
    _prepare(monkeypatch, isolated_database_url, tmp_path, max_bytes=80)
    product = _product("guarded-product", active=False)
    oversized = _upload(product["id"], "large.pdf", _pdf() + b"x" * 80, "application/pdf")
    assert oversized.status_code == 422
    assert "too large" in oversized.json()["detail"].lower()

    anonymous = TestClient(app)
    anonymous_response = anonymous.post(
        f"/api/v1/admin/products/{product['id']}/download",
        files={"download": ("notes.pdf", _pdf(), "application/pdf")},
    )
    assert anonymous_response.status_code == 401

    missing_csrf = client.post(
        f"/api/v1/admin/products/{product['id']}/download",
        files={"download": ("notes.pdf", _pdf(), "application/pdf")},
    )
    assert missing_csrf.status_code == 403

    uploaded = _upload(product["id"], "notes.pdf", _pdf(), "application/pdf")
    assert uploaded.status_code == 200
    enabled = client.patch(
        f"/api/v1/admin/products/{product['id']}",
        json={"download_enabled": True},
        headers=_headers(),
    )
    assert enabled.status_code == 200
    assert client.get("/api/v1/products/guarded-product/download").status_code == 404

    published = client.patch(
        f"/api/v1/admin/products/{product['id']}",
        json={"active": True},
        headers=_headers(),
    )
    assert published.status_code == 200
    assert client.get("/api/v1/products/guarded-product/download").status_code == 200
    for path in tmp_path.iterdir():
        path.unlink()
    missing = client.get("/api/v1/products/guarded-product/download")
    assert missing.status_code == 404
    assert str(tmp_path) not in missing.text

    archived = client.delete(f"/api/v1/admin/products/{product['id']}", headers=_headers())
    assert archived.status_code == 204
    assert client.get("/api/v1/products/guarded-product/download").status_code == 404
