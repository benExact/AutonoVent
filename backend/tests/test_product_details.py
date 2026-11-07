"""Dynamic product details. Fixture images stay in a temporary directory."""

import io
import uuid

from fastapi.testclient import TestClient as FreshClient
from PIL import Image
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.auth.service import create_initial_owner
from app.checkout.service import CheckoutValidationError, _priced_lines
from app.core.config import get_settings
from app.db.session import reset_engine
from app.main import app
from app.models.product import Product
from app.orders.service import OrderLine
from tests.test_owner_products import (
    _cookie,
    _create,
    _login,
    _owner,
    _use_database,
    client,
)


def _picture(fmt: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), (20, 40, 60)).save(buffer, fmt)
    return buffer.getvalue()


def _ready(monkeypatch, database_url: str, image_dir) -> None:
    _use_database(monkeypatch, database_url, str(image_dir))
    _owner(database_url)
    _login()


def _published(slug: str = "fixture-detail") -> dict:
    return {
        "name": "Fixture detail",
        "slug": slug,
        "description": "Full description for the fixture.",
        "short_description": "Short fixture summary.",
        "sku": slug.upper(),
        "price_rands": "1550.00",
        "currency": "ZAR",
        "active": True,
        "in_stock": True,
        "specifications": [{"label": "Material", "value": "Aluminium"}],
    }


def test_public_catalogue_hides_drafts_and_reads_a_slug(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    _ready(monkeypatch, isolated_database_url, tmp_path)
    draft = _create(dict(_published("fixture-draft"), active=False, sku="DRAFT-1"))
    assert draft.status_code == 201
    published = _create(_published())
    assert published.status_code == 201
    assert published.json()["specifications"][0]["label"] == "Material"
    listed = client.get("/api/v1/products")
    slugs = [item["slug"] for item in listed.json()["products"]]
    assert "fixture-detail" in slugs
    assert "fixture-draft" not in slugs
    found = client.get("/api/v1/products/fixture-detail")
    assert found.status_code == 200
    assert found.json()["short_description"] == "Short fixture summary."
    assert found.json()["in_stock"] is True
    assert found.json()["specifications"] == [{"label": "Material", "value": "Aluminium"}]
    assert client.get("/api/v1/products/missing-product").status_code == 404
    duplicate = _create(dict(_published("fixture-detail"), sku="OTHER-1"))
    assert duplicate.status_code == 409


def test_slug_change_keeps_the_previous_url(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    _ready(monkeypatch, isolated_database_url, tmp_path)
    created = _create(_published("fixture-old"))
    product_id = created.json()["id"]
    renamed = client.patch(
        f"/api/v1/admin/products/{product_id}",
        json={"slug": "fixture-new"},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert renamed.status_code == 200
    assert renamed.json()["id"] == product_id
    alias = client.get("/api/v1/products/fixture-old")
    assert alias.status_code == 200
    assert alias.json()["slug"] == "fixture-new"
    assert alias.json()["id"] == product_id


def test_gallery_accepts_four_images_and_rejects_the_fifth(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    _ready(monkeypatch, isolated_database_url, tmp_path)
    created = _create(_published("gallery-fixture"))
    product_id = created.json()["id"]
    anonymous = FreshClient(app)
    assert anonymous.post(f"/api/v1/admin/products/{product_id}/images", files={"image": ("a.png", _picture("PNG"), "image/png")}).status_code == 401
    uploads = []
    for name, fmt, mime in (
        ("a.png", "PNG", "image/png"),
        ("b.jpg", "JPEG", "image/jpeg"),
        ("c.webp", "WEBP", "image/webp"),
        ("../secret.png", "PNG", "image/png"),
    ):
        response = client.post(
            f"/api/v1/admin/products/{product_id}/images",
            files={"image": (name, _picture(fmt), mime)},
            headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
        )
        assert response.status_code == 201
        uploads.append(response.json())
    images = uploads[-1]["images"]
    assert len(images) == 4
    assert [item["position"] for item in images] == [0, 1, 2, 3]
    assert all("/media/products/gallery-fixture/" in item["url"] for item in images)
    assert all(item["thumb_url"] for item in images)
    assert ".." not in images[-1]["url"]
    extra = client.post(
        f"/api/v1/admin/products/{product_id}/images",
        files={"image": ("d.png", _picture("PNG"), "image/png")},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert extra.status_code == 422
    rejected = client.post(
        f"/api/v1/admin/products/{product_id}/images",
        files={"image": ("notes.gif", b"GIF89a", "image/gif")},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert rejected.status_code == 422
    oversized = client.post(
        f"/api/v1/admin/products/{product_id}/images",
        files={"image": ("large.jpg", b"\xff\xd8\xff" + (b"\x00" * (5 * 1024 * 1024)), "image/jpeg")},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert oversized.status_code == 422
    ordered = client.put(
        f"/api/v1/admin/products/{product_id}/images/order",
        json={"image_ids": [images[2]["id"], images[0]["id"], images[1]["id"], images[3]["id"]]},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert ordered.status_code == 200
    assert [item["id"] for item in ordered.json()["images"]] == [images[2]["id"], images[0]["id"], images[1]["id"], images[3]["id"]]
    replaced = client.post(
        f"/api/v1/admin/products/{product_id}/images/{images[2]['id']}",
        files={"image": ("new.png", _picture("PNG"), "image/png")},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert replaced.status_code == 200
    removed = client.delete(
        f"/api/v1/admin/products/{product_id}/images/{images[3]['id']}",
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert removed.status_code == 200
    assert len(removed.json()["images"]) == 3
    public = client.get("/api/v1/products/gallery-fixture")
    assert [item["position"] for item in public.json()["images"]] == [0, 1, 2]
    stored = list(tmp_path.rglob("*.webp"))
    assert stored
    assert all(tmp_path.resolve() in path.resolve().parents for path in stored)


def test_out_of_stock_is_rejected_by_checkout(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    _ready(monkeypatch, isolated_database_url, tmp_path)
    created = _create(_published("stock-fixture"))
    product_id = created.json()["id"]
    updated = client.patch(
        f"/api/v1/admin/products/{product_id}",
        json={"in_stock": False},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert updated.status_code == 200
    assert client.get("/api/v1/products/stock-fixture").json()["in_stock"] is False
    engine = create_engine(isolated_database_url)
    with Session(engine) as session:
        product = session.scalar(select(Product).where(Product.slug == "stock-fixture"))
        assert product is not None
        try:
            _priced_lines(session, get_settings(), [OrderLine(product_id=product.id, quantity=1)])
        except CheckoutValidationError as exc:
            assert "out of stock" in str(exc)
        else:
            raise AssertionError("An out-of-stock product was priced.")
    engine.dispose()
    reset_engine()
