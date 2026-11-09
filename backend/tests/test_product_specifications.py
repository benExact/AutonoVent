"""One optional PDF specification sheet per product. Files stay in a temporary directory."""

import re
import urllib.parse

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app
from tests.test_owner_products import PRODUCT, _cookie, _login, _owner, _use_database, client

STORED = re.compile(r"^[0-9a-f]{32}\.pdf$")
PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


def _prepare(monkeypatch, database_url: str, directory, max_bytes: int | None = None) -> None:
    _use_database(monkeypatch, database_url)
    monkeypatch.setenv("PRODUCT_SPECIFICATION_DIR", str(directory))
    if max_bytes is not None:
        monkeypatch.setenv("PRODUCT_SPECIFICATION_MAX_BYTES", str(max_bytes))
    get_settings.cache_clear()
    _owner(database_url)
    _login()


def _headers() -> dict[str, str]:
    return {"X-CSRF-Token": _cookie("autonovent_csrf")}


def _create(slug: str, **fields):
    body = {**PRODUCT, "slug": slug, "sku": slug.upper(), "unit_price_cents": 1500, "active": True, **fields}
    return client.post("/api/v1/admin/products", json=body, headers=_headers())


def _product(slug: str, **fields) -> dict:
    created = _create(slug, **fields)
    assert created.status_code == 201, created.text
    return created.json()


def _upload(product_id: str, name: str = "Spec Sheet.pdf", data: bytes = PDF, content_type: str = "application/pdf"):
    return client.post(
        f"/api/v1/admin/products/{product_id}/specification",
        files={"specification": (name, data, content_type)},
        headers=_headers(),
    )


def _patch(product_id: str, body: dict):
    return client.patch(f"/api/v1/admin/products/{product_id}", json=body, headers=_headers())


def _sheet_url(slug: str) -> str:
    return f"/api/v1/products/{slug}/specification"


def test_existing_products_without_a_sheet_keep_working(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    _prepare(monkeypatch, isolated_database_url, tmp_path)
    assert get_settings().product_specification_max_bytes == 25 * 1024 * 1024
    product = _product("plain-product")
    assert product["specification_sheet"] == {
        "enabled": False,
        "configured": False,
        "file_available": False,
        "original_name": None,
        "size_bytes": None,
        "content_type": None,
    }
    public = client.get("/api/v1/products/plain-product")
    assert public.status_code == 200
    assert public.json()["specification_sheet"] is None
    listed = client.get("/api/v1/products").json()["products"]
    assert [item["specification_sheet"] for item in listed if item["slug"] == "plain-product"] == [None]
    missing = client.get(_sheet_url("plain-product"))
    assert missing.status_code == 404
    assert missing.headers["x-robots-tag"] == "noindex"
    assert list(tmp_path.iterdir()) == []


def test_enabled_sheet_needs_a_file_before_publishing(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    _prepare(monkeypatch, isolated_database_url, tmp_path)
    refused = _create("early-product", specification_enabled=True)
    assert refused.status_code == 422
    assert "specification sheet" in refused.json()["detail"]

    draft = _product("draft-product", active=False, specification_enabled=True)
    assert draft["specification_sheet"]["enabled"] is True
    assert draft["specification_sheet"]["configured"] is False
    assert _patch(draft["id"], {"active": True}).status_code == 422

    assert _upload(draft["id"]).status_code == 200
    published = _patch(draft["id"], {"active": True})
    assert published.status_code == 200
    assert client.get(_sheet_url("draft-product")).status_code == 200


def test_owner_can_upload_replace_disable_reenable_and_remove(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    _prepare(monkeypatch, isolated_database_url, tmp_path)
    product = _product("guided-product")
    uploaded = _upload(product["id"], "Guided Product – Spec Sheet.pdf")
    assert uploaded.status_code == 200
    sheet = uploaded.json()["specification_sheet"]
    assert sheet["configured"] is True
    assert sheet["file_available"] is True
    assert sheet["enabled"] is False
    assert sheet["original_name"] == "Guided Product – Spec Sheet.pdf"
    assert sheet["size_bytes"] == len(PDF)
    assert str(tmp_path) not in uploaded.text
    stored = [path.name for path in tmp_path.iterdir()]
    assert len(stored) == 1 and STORED.fullmatch(stored[0])
    assert stored[0] not in uploaded.text
    assert client.get(_sheet_url("guided-product")).status_code == 404

    metadata = client.get(f"/api/v1/admin/products/{product['id']}/specification")
    assert metadata.status_code == 200
    assert metadata.json() == sheet
    preview = client.get(f"/api/v1/admin/products/{product['id']}/specification/file")
    assert preview.status_code == 200
    assert preview.content == PDF
    assert preview.headers["content-disposition"].startswith("inline")

    assert _patch(product["id"], {"specification_enabled": True}).status_code == 200
    public = client.get("/api/v1/products/guided-product").json()["specification_sheet"]
    assert public == {"filename": "Guided Product Spec Sheet.pdf", "size_bytes": len(PDF), "content_type": "application/pdf"}
    downloaded = client.get(_sheet_url("guided-product"))
    assert downloaded.status_code == 200
    assert downloaded.content == PDF
    assert downloaded.headers["content-type"] == "application/pdf"
    disposition = downloaded.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="Guided Product Spec Sheet.pdf"')
    assert "Guided Product Spec Sheet.pdf" in urllib.parse.unquote(disposition)
    assert stored[0] not in disposition and str(tmp_path) not in disposition
    assert downloaded.headers["x-robots-tag"] == "noindex"
    assert downloaded.headers["x-content-type-options"] == "nosniff"

    replacement = PDF.replace(b"%%EOF", b"% replaced\n%%EOF")
    replaced = _upload(product["id"], "Updated.pdf", replacement)
    assert replaced.status_code == 200
    assert replaced.json()["specification_sheet"]["original_name"] == "Updated.pdf"
    after_replace = [path.name for path in tmp_path.iterdir()]
    assert len(after_replace) == 1 and after_replace != stored
    assert client.get(_sheet_url("guided-product")).content == replacement

    disabled = _patch(product["id"], {"specification_enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["specification_sheet"]["configured"] is True
    assert client.get(_sheet_url("guided-product")).status_code == 404
    assert client.get("/api/v1/products/guided-product").json()["specification_sheet"] is None
    assert [path.name for path in tmp_path.iterdir()] == after_replace
    assert _patch(product["id"], {"specification_enabled": True}).status_code == 200
    assert client.get(_sheet_url("guided-product")).content == replacement

    removed = client.delete(f"/api/v1/admin/products/{product['id']}/specification", headers=_headers())
    assert removed.status_code == 200
    assert removed.json()["specification_sheet"]["configured"] is False
    assert removed.json()["specification_sheet"]["enabled"] is False
    assert list(tmp_path.iterdir()) == []
    assert client.get(_sheet_url("guided-product")).status_code == 404
    assert _patch(product["id"], {"specification_enabled": True}).status_code == 422


def test_only_real_pdfs_within_the_limit_are_stored(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    _prepare(monkeypatch, isolated_database_url, tmp_path, max_bytes=len(PDF) + 16)
    product = _product("checked-product")
    rejected = [
        ("sheet.docx", PDF, "application/pdf"),
        ("sheet.exe", PDF, "application/pdf"),
        ("sheet.pdf", PDF, "text/html"),
        ("sheet.pdf", PDF, "application/octet-stream"),
        ("sheet.pdf", b"MZ\x90\x00not a pdf %%EOF", "application/pdf"),
        ("sheet.pdf", b"<html><script>alert(1)</script></html>", "application/pdf"),
        ("sheet.pdf", b"%PDF-1.7\ntruncated", "application/pdf"),
        ("sheet.pdf", b"", "application/pdf"),
    ]
    for name, data, content_type in rejected:
        response = _upload(product["id"], name, data, content_type)
        assert response.status_code == 422, (name, content_type)
    oversized = _upload(product["id"], "large.pdf", PDF.replace(b"%%EOF", b"%" + b"x" * 64 + b"\n%%EOF"))
    assert oversized.status_code == 422
    assert "too large" in oversized.json()["detail"].lower()
    assert list(tmp_path.iterdir()) == []

    outside = tmp_path.parent / "escape.pdf"
    traversal = _upload(product["id"], "../../escape.pdf")
    assert traversal.status_code == 200
    assert traversal.json()["specification_sheet"]["original_name"] == "escape.pdf"
    windows = _upload(product["id"], "..\\..\\windows.pdf")
    assert windows.status_code == 200
    assert windows.json()["specification_sheet"]["original_name"] == "windows.pdf"
    assert not outside.exists()
    assert all(STORED.fullmatch(path.name) for path in tmp_path.iterdir())
    assert client.get("/api/v1/products/..%2F..%2Fescape/specification").status_code == 404


def test_owner_routes_need_a_session_and_csrf(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    _prepare(monkeypatch, isolated_database_url, tmp_path)
    product = _product("guarded-product")
    path = f"/api/v1/admin/products/{product['id']}/specification"
    anonymous = TestClient(app)
    files = {"specification": ("sheet.pdf", PDF, "application/pdf")}
    assert anonymous.post(path, files=files).status_code == 401
    assert anonymous.get(path).status_code == 401
    assert anonymous.get(path + "/file").status_code == 401
    assert anonymous.delete(path).status_code == 401
    assert client.post(path, files=files).status_code == 403
    assert client.post(path, files=files, headers={"X-CSRF-Token": "not-the-cookie"}).status_code == 403
    assert client.delete(path).status_code == 403
    assert list(tmp_path.iterdir()) == []


def test_unpublished_deleted_and_missing_sheets_are_not_served(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    _prepare(monkeypatch, isolated_database_url, tmp_path)
    product = _product("hidden-product", active=False)
    assert _upload(product["id"]).status_code == 200
    assert _patch(product["id"], {"specification_enabled": True}).status_code == 200
    assert client.get(_sheet_url("hidden-product")).status_code == 404

    assert _patch(product["id"], {"active": True}).status_code == 200
    assert client.get(_sheet_url("hidden-product")).status_code == 200
    renamed = _patch(product["id"], {"slug": "renamed-product"})
    assert renamed.status_code == 200
    assert client.get(_sheet_url("hidden-product")).status_code == 200

    for path in tmp_path.iterdir():
        path.unlink()
    missing = client.get(_sheet_url("renamed-product"))
    assert missing.status_code == 404
    assert str(tmp_path) not in missing.text
    assert client.get("/api/v1/products/renamed-product").json()["specification_sheet"] is None
    owner_view = client.get(f"/api/v1/admin/products/{product['id']}/specification").json()
    assert owner_view["configured"] is True
    assert owner_view["file_available"] is False

    assert _upload(product["id"]).status_code == 200
    deleted = client.delete(f"/api/v1/admin/products/{product['id']}", headers=_headers())
    assert deleted.status_code == 204
    assert client.get(_sheet_url("renamed-product")).status_code == 404
    assert client.get(_sheet_url("hidden-product")).status_code == 404
    assert list(tmp_path.iterdir()) == []
