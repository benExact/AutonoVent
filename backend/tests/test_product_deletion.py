"""Permanent product deletion. Fixture rows stay in the isolated database and files in temporary folders."""

import io
import logging
import sys
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.admin import retry_file_cleanups
from app.core.config import get_settings
from app.db.session import reset_engine
from app.main import app
from app.models.audit import ProductAuditEvent
from app.models.file_cleanup import FileCleanup
from app.models.product import Product, ProductImage, ProductSlugAlias, ProductSpecification
from app.products import deletion
from app.products.deletion import IMAGES, run_file_cleanups, storage_roots
from tests.test_owner_products import _cookie, _create, _login, _owner, _use_database, client

PDF = b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"


def _ready(monkeypatch, database_url: str, tmp_path: Path) -> tuple[Path, Path]:
    images = tmp_path / "images"
    sheets = tmp_path / "sheets"
    images.mkdir()
    sheets.mkdir()
    _use_database(monkeypatch, database_url, str(images))
    monkeypatch.setenv("PRODUCT_SPECIFICATION_DIR", str(sheets))
    monkeypatch.setenv("CAROUSEL_IMAGE_DIR", str(tmp_path / "carousel"))
    get_settings.cache_clear()
    _owner(database_url)
    _login()
    return images, sheets


def _headers() -> dict[str, str]:
    return {"X-CSRF-Token": _cookie("autonovent_csrf")}


def _picture() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (20, 40, 60)).save(buffer, "PNG")
    return buffer.getvalue()


def _product(slug: str, **fields) -> dict:
    body = {
        "name": slug.replace("-", " ").title(),
        "slug": slug,
        "description": "Automated test row. Not a commercial product.",
        "sku": slug.upper(),
        "price_rands": "1200.00",
        "currency": "ZAR",
        "active": True,
        **fields,
    }
    created = _create(body)
    assert created.status_code == 201, created.text
    return created.json()


def _legacy_image(product_id: str) -> None:
    response = client.post(
        f"/api/v1/admin/products/{product_id}/image",
        files={"image": ("photo.png", _picture(), "image/png")},
        headers=_headers(),
    )
    assert response.status_code == 200, response.text


def _gallery_image(product_id: str) -> None:
    response = client.post(
        f"/api/v1/admin/products/{product_id}/images",
        files={"image": ("photo.png", _picture(), "image/png")},
        headers=_headers(),
    )
    assert response.status_code == 201, response.text


def _sheet(product_id: str) -> None:
    response = client.post(
        f"/api/v1/admin/products/{product_id}/specification",
        files={"specification": ("Spec.pdf", PDF, "application/pdf")},
        headers=_headers(),
    )
    assert response.status_code == 200, response.text


def _delete(product_id: str):
    return client.delete(f"/api/v1/admin/products/{product_id}", headers=_headers())


def _files(root: Path) -> list[str]:
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def _rows(database_url: str, product_id: str) -> dict[str, int]:
    key = uuid.UUID(product_id)
    engine = create_engine(database_url)
    with Session(engine) as session:
        counts = {
            "products": session.scalar(select(func.count()).select_from(Product).where(Product.id == key)),
            "images": session.scalar(select(func.count()).select_from(ProductImage).where(ProductImage.product_id == key)),
            "specifications": session.scalar(
                select(func.count()).select_from(ProductSpecification).where(ProductSpecification.product_id == key)
            ),
            "aliases": session.scalar(select(func.count()).select_from(ProductSlugAlias).where(ProductSlugAlias.product_id == key)),
            "audit": session.scalar(select(func.count()).select_from(ProductAuditEvent).where(ProductAuditEvent.product_id == key)),
        }
    engine.dispose()
    return counts


def _cleanups(database_url: str) -> list[FileCleanup]:
    engine = create_engine(database_url)
    with Session(engine, expire_on_commit=False) as session:
        rows = list(session.scalars(select(FileCleanup)))
    engine.dispose()
    return rows


def _assert_gone(product_id: str, slugs: list[str]) -> None:
    for slug in slugs:
        assert client.get(f"/api/v1/products/{slug}").status_code == 404
        assert client.get(f"/api/v1/products/{slug}/page").status_code == 404
        assert client.get(f"/api/v1/products/{slug}/specification").status_code == 404
    assert client.patch(f"/api/v1/admin/products/{product_id}", json={"name": "Gone"}, headers=_headers()).status_code == 404
    assert client.get(f"/api/v1/admin/products/{product_id}/audit").status_code == 404
    assert client.get(f"/api/v1/admin/products/{product_id}/specification").status_code == 404
    assert _delete(product_id).status_code == 404
    assert product_id not in [item["id"] for item in client.get("/api/v1/admin/products").json()["products"]]


def _finish() -> None:
    reset_engine()
    get_settings.cache_clear()


def test_deleting_a_product_with_one_image_removes_the_row_and_the_file(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    images, _sheets = _ready(monkeypatch, isolated_database_url, tmp_path)
    product = _product("single-image")
    _legacy_image(product["id"])
    assert len(_files(images)) == 1
    page = client.get("/api/v1/products/single-image/page")
    assert page.status_code == 200
    assert page.headers["x-accel-redirect"] == "/_product_shell"

    assert _delete(product["id"]).status_code == 204

    assert _files(images) == []
    assert _rows(isolated_database_url, product["id"]) == {"products": 0, "images": 0, "specifications": 0, "aliases": 0, "audit": 0}
    assert _cleanups(isolated_database_url) == []
    missing = client.get("/api/v1/products/single-image/page")
    assert missing.headers["x-robots-tag"] == "noindex"
    _assert_gone(product["id"], ["single-image"])
    _finish()


def test_gallery_thumbnails_specifications_sheet_and_aliases_are_all_removed(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    images, sheets = _ready(monkeypatch, isolated_database_url, tmp_path)
    kept = _product("kept-product", specifications=[{"label": "Colour", "value": "Green"}])
    _gallery_image(kept["id"])
    _sheet(kept["id"])
    assert client.patch(f"/api/v1/admin/products/{kept['id']}", json={"specification_enabled": True}, headers=_headers()).status_code == 200
    kept_images = _files(images)
    kept_sheets = _files(sheets)

    product = _product(
        "full-product",
        specifications=[{"label": "Material", "value": "Aluminium"}, {"label": "Weight", "value": "2 kg"}],
    )
    _legacy_image(product["id"])
    for _ in range(3):
        _gallery_image(product["id"])
    _sheet(product["id"])
    renamed = client.patch(f"/api/v1/admin/products/{product['id']}", json={"slug": "full-product-renamed"}, headers=_headers())
    assert renamed.status_code == 200
    assert len(_files(images)) == len(kept_images) + 1 + 3 * 2
    assert len(_files(sheets)) == 2
    before = _rows(isolated_database_url, product["id"])
    assert before["images"] == 3 and before["specifications"] == 2 and before["aliases"] == 1 and before["audit"] >= 1

    assert _delete(product["id"]).status_code == 204

    assert _rows(isolated_database_url, product["id"]) == {"products": 0, "images": 0, "specifications": 0, "aliases": 0, "audit": 0}
    assert _files(images) == kept_images
    assert _files(sheets) == kept_sheets
    assert not (images / "full-product-renamed").exists()
    assert not (images / "full-product").exists()
    assert _cleanups(isolated_database_url) == []
    _assert_gone(product["id"], ["full-product", "full-product-renamed"])

    survivor = client.get("/api/v1/products/kept-product")
    assert survivor.status_code == 200
    assert survivor.json()["specifications"] == [{"label": "Colour", "value": "Green"}]
    assert survivor.json()["specification_sheet"] is not None
    assert client.get("/api/v1/products/kept-product/specification").status_code == 200
    _finish()


def test_files_shared_with_another_product_are_kept_until_the_last_reference_goes(
    monkeypatch, isolated_database_url: str, tmp_path
) -> None:
    images, sheets = _ready(monkeypatch, isolated_database_url, tmp_path)
    first = _product("first-owner")
    _legacy_image(first["id"])
    _gallery_image(first["id"])
    _sheet(first["id"])
    second = _product("second-owner")
    engine = create_engine(isolated_database_url)
    with Session(engine) as session:
        original = session.get(Product, uuid.UUID(first["id"]))
        other = session.get(Product, uuid.UUID(second["id"]))
        other.image_filename = original.image_filename
        other.specification_stored_name = original.specification_stored_name
        session.commit()
    engine.dispose()
    shared_images = [name for name in _files(images) if "/" not in name]
    shared_sheets = _files(sheets)

    assert _delete(first["id"]).status_code == 204
    assert _files(images) == shared_images
    assert _files(sheets) == shared_sheets
    assert _cleanups(isolated_database_url) == []

    assert _delete(second["id"]).status_code == 204
    assert _files(images) == []
    assert _files(sheets) == []
    _finish()


def test_only_a_signed_in_owner_with_csrf_can_delete(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    images, sheets = _ready(monkeypatch, isolated_database_url, tmp_path)
    product = _product("protected-product")
    _gallery_image(product["id"])
    _sheet(product["id"])
    path = f"/api/v1/admin/products/{product['id']}"

    assert TestClient(app).delete(path).status_code == 401
    assert client.delete(path).status_code == 403
    assert client.delete(path, headers={"X-CSRF-Token": "not-the-cookie"}).status_code == 403
    assert TestClient(app).delete("/api/v1/products/protected-product").status_code == 405
    assert TestClient(app).delete("/api/v1/products/protected-product/specification").status_code == 405

    assert _rows(isolated_database_url, product["id"])["products"] == 1
    assert len(_files(images)) == 2
    assert len(_files(sheets)) == 1
    assert client.get("/api/v1/products/protected-product").status_code == 200
    _finish()


def test_a_failed_database_delete_keeps_every_record_and_file(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    images, sheets = _ready(monkeypatch, isolated_database_url, tmp_path)
    product = _product("rollback-product", specifications=[{"label": "Size", "value": "Large"}])
    _gallery_image(product["id"])
    _sheet(product["id"])
    before_rows = _rows(isolated_database_url, product["id"])
    before_images = _files(images)
    before_sheets = _files(sheets)

    def failing_queue(*_args, **_kwargs):
        raise OperationalError("INSERT INTO file_cleanups", {}, Exception("simulated outage"))

    original_queue = deletion._queue
    monkeypatch.setattr(deletion, "_queue", failing_queue)
    failed = _delete(product["id"])
    monkeypatch.setattr(deletion, "_queue", original_queue)

    assert failed.status_code == 503
    assert failed.json()["detail"] == "The product could not be deleted. Nothing was removed. Try again."
    assert "simulated" not in failed.text
    assert _rows(isolated_database_url, product["id"]) == before_rows
    assert _files(images) == before_images
    assert _files(sheets) == before_sheets
    assert _cleanups(isolated_database_url) == []
    assert client.get("/api/v1/products/rollback-product").status_code == 200
    _finish()


def test_a_file_that_cannot_be_removed_is_logged_and_retried(monkeypatch, isolated_database_url: str, tmp_path, caplog) -> None:
    images, sheets = _ready(monkeypatch, isolated_database_url, tmp_path)
    product = _product("stubborn-product")
    _gallery_image(product["id"])
    _sheet(product["id"])

    original_unlink = Path.unlink

    def locked(self, missing_ok=False):
        if self.suffix == ".pdf":
            raise PermissionError(13, "Permission denied")
        return original_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", locked)
    with caplog.at_level(logging.ERROR, logger="app.products.deletion"):
        assert _delete(product["id"]).status_code == 204
    monkeypatch.setattr(Path, "unlink", original_unlink)

    assert _rows(isolated_database_url, product["id"])["products"] == 0
    assert _files(images) == []
    assert len(_files(sheets)) == 1
    queued = _cleanups(isolated_database_url)
    assert len(queued) == 1
    assert queued[0].storage == "product_specifications"
    assert queued[0].product_id == uuid.UUID(product["id"])
    assert queued[0].attempts == 1
    assert queued[0].last_error.startswith("PermissionError")
    assert any("stays queued in file_cleanups" in record.getMessage() for record in caplog.records)

    reset_engine()
    monkeypatch.setattr(sys, "argv", ["retry_file_cleanups"])
    assert retry_file_cleanups.main() == 0
    assert _files(sheets) == []
    assert _cleanups(isolated_database_url) == []
    _finish()


def test_cleanup_refuses_names_outside_the_storage_folders(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    images, _sheets = _ready(monkeypatch, isolated_database_url, tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("keep me")
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        session.add(FileCleanup(storage=IMAGES, stored_name="../outside.txt"))
        session.commit()
        pending = run_file_cleanups(session, storage_roots(get_settings()))
    engine.dispose()
    assert len(pending) == 1
    assert outside.read_text() == "keep me"
    assert images.exists()
    row = _cleanups(isolated_database_url)[0]
    assert row.attempts == 1
    assert "not a file this service manages" in row.last_error
    _finish()
