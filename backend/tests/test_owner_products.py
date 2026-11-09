"""Owner product management. Fixture rows stay in the isolated database."""

import base64
import logging
import uuid

import pytest
from sqlalchemy.exc import ProgrammingError
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from app.auth.service import create_initial_owner
from app.core.config import get_settings
from app.db.session import reset_engine
from app.main import app
from app.models.audit import ProductAuditEvent
from app.models.product import Product
from app.models.order import OrderItem, OrderStatusEvent
from app.orders.service import DeliveryAddress, OrderDraft, OrderLine, OrderValidationError, create_order

client = TestClient(app)
EMAIL = "fixture-owner@example.com"
PASSWORD = "fixture-password-1"
PRODUCT = {
    "name": "Fixture product",
    "slug": "fixture-product",
    "description": "Automated test row. Not a commercial product.",
    "sku": "FIX-1",
    "currency": "ZAR",
    "active": False,
}


def _use_database(monkeypatch, database_url: str, image_dir: str | None = None) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("CHECKOUT_SIMULATION_ENABLED", "false")
    monkeypatch.setenv("CHECKOUT_SIMULATION_DEMO_UNIT_PRICE_CENTS", "")
    if image_dir is not None:
        monkeypatch.setenv("PRODUCT_IMAGE_DIR", image_dir)
    get_settings.cache_clear()
    reset_engine()
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM auth_login_attempts"))
        connection.execute(text("DELETE FROM admin_sessions"))
        connection.execute(text("DELETE FROM admin_users"))
        connection.execute(text("DELETE FROM order_status_events"))
        connection.execute(text("DELETE FROM order_items"))
        connection.execute(text("DELETE FROM payments"))
        connection.execute(text("DELETE FROM shipments"))
        connection.execute(text("DELETE FROM email_notifications"))
        connection.execute(text("DELETE FROM orders"))
        connection.execute(text("DELETE FROM product_audit_events"))
        connection.execute(text("DELETE FROM products"))
        connection.execute(text("DELETE FROM file_cleanups"))
    engine.dispose()
    client.cookies.clear()


def _owner(database_url: str) -> None:
    engine = create_engine(database_url)
    with Session(engine, expire_on_commit=False) as session:
        create_initial_owner(session, EMAIL, PASSWORD)
    engine.dispose()


def _cookie(name: str) -> str:
    matches = [cookie.value for cookie in client.cookies.jar if cookie.name == name]
    return matches[-1] if matches else ""


def _replace_cookie(name: str, value: str) -> None:
    jar = client.cookies.jar
    for cookie in list(jar):
        if cookie.name == name:
            jar.clear(cookie.domain, cookie.path, cookie.name)
    if value:
        client.cookies.set(name, value)


def _csrf() -> str:
    response = client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    token = response.json()["csrf_token"] or _cookie("autonovent_csrf")
    assert token
    _replace_cookie("autonovent_csrf", token)
    return token


def _set_cookie(response, name: str) -> str:
    matches = [value for value in response.headers.get_list("set-cookie") if value.startswith(name + "=")]
    assert matches
    return matches[-1]


def _login() -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        headers={"X-CSRF-Token": _csrf()},
    )
    assert response.status_code == 200
    _replace_cookie("autonovent_session", _set_cookie(response, "autonovent_session").split("=", 1)[1].split(";", 1)[0])
    _replace_cookie("autonovent_csrf", _set_cookie(response, "autonovent_csrf").split("=", 1)[1].split(";", 1)[0])


def _create(body: dict):
    return client.post("/api/v1/admin/products", json=body, headers={"X-CSRF-Token": _cookie("autonovent_csrf")})


def test_owner_can_preflight_a_product_delete() -> None:
    response = client.options(
        f"/api/v1/admin/products/{uuid.uuid4()}",
        headers={
            "Origin": "http://127.0.0.1:8765",
            "Access-Control-Request-Method": "DELETE",
            "Access-Control-Request-Headers": "x-csrf-token",
        },
    )
    assert response.status_code == 200
    assert "DELETE" in response.headers["access-control-allow-methods"]


def test_product_management_requires_an_owner(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    assert client.get("/api/v1/admin/products").status_code == 401
    assert client.post("/api/v1/admin/products", json=PRODUCT).status_code == 401
    assert client.patch(f"/api/v1/admin/products/{uuid.uuid4()}", json={"name": "Fixture"}).status_code == 401
    assert client.delete(f"/api/v1/admin/products/{uuid.uuid4()}").status_code == 401
    assert client.get("/api/v1/admin/readiness").status_code == 404


def test_a_product_list_failure_is_logged_and_stays_generic(monkeypatch, isolated_database_url: str, caplog) -> None:
    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    _login()

    def fail(_session):
        raise ProgrammingError("SELECT products.specification_enabled", {}, Exception("column products.specification_enabled does not exist"))

    monkeypatch.setattr("app.api.v1.admin.list_products", fail)
    with caplog.at_level(logging.ERROR, logger="app.api.v1.admin"):
        response = client.get("/api/v1/admin/products")
    assert response.status_code == 503
    assert response.json() == {"detail": "Product management is temporarily unavailable."}
    assert "specification_enabled" not in response.text
    assert "column products.specification_enabled does not exist" in caplog.text
    assert "reading the product list" in caplog.text


def test_owner_can_save_several_products_and_the_catalogue_stays_selective(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    _login()
    blocked = client.post("/api/v1/admin/products", json=PRODUCT)
    assert blocked.status_code == 403
    first = _create(PRODUCT)
    assert first.status_code == 201
    assert first.json()["unit_price_cents"] is None
    assert first.json()["active"] is False
    second = _create(
        {
            "name": "Second fixture",
            "slug": "fixture-product-two",
            "description": "Automated test row. Not a commercial product.",
            "sku": None,
            "unit_price_cents": 2500,
            "currency": "ZAR",
            "active": True,
        }
    )
    assert second.status_code == 201
    listed = client.get("/api/v1/admin/products")
    assert listed.status_code == 200
    assert {item["slug"] for item in listed.json()["products"]} == {"fixture-product", "fixture-product-two"}
    public = client.get("/api/v1/products")
    assert [item["slug"] for item in public.json()["products"]] == ["fixture-product-two"]
    inactive = _create(
        {
            "name": "Inactive priced fixture",
            "slug": "fixture-inactive",
            "unit_price_cents": 2500,
            "currency": "ZAR",
            "active": False,
        }
    )
    assert inactive.status_code == 201
    public_again = client.get("/api/v1/products")
    assert [item["slug"] for item in public_again.json()["products"]] == ["fixture-product-two"]
    unpriced = _create(
        {
            "name": "Active unpriced fixture",
            "slug": "fixture-unpriced",
            "currency": "ZAR",
            "active": True,
        }
    )
    assert unpriced.status_code == 201
    assert unpriced.json()["unit_price_cents"] is None
    assert [item["slug"] for item in client.get("/api/v1/products").json()["products"]] == ["fixture-product-two"]
    duplicate = _create(dict(PRODUCT, sku="FIX-2"))
    assert duplicate.status_code == 409
    reset_engine()
    get_settings.cache_clear()


def test_price_and_field_validation(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    _login()
    for price in (-1, 1.5, "2500", True):
        response = _create(dict(PRODUCT, slug=f"fixture-{price}", sku=None, unit_price_cents=price))
        assert response.status_code == 422
    assert _create(dict(PRODUCT, slug="Bad Slug", sku=None)).status_code == 422
    assert _create(dict(PRODUCT, currency="USD", sku=None)).status_code == 422
    assert _create(dict(PRODUCT, name="  ", sku=None)).status_code == 422


def test_product_edits_do_not_change_order_snapshots(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    _login()
    created = _create(
        dict(PRODUCT, unit_price_cents=2500, active=True, sku="FIX-SNAP")
    )
    assert created.status_code == 201
    product_id = uuid.UUID(created.json()["id"])
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        order = create_order(
            session,
            OrderDraft(
                idempotency_key="fixture-product-edit-key",
                customer_name="Fixture Customer",
                customer_email="fixture@example.com",
                delivery=DeliveryAddress(
                    name="Fixture Customer",
                    line1="1 Fixture Street",
                    city="Pretoria",
                    region="Gauteng",
                    postal_code="0002",
                ),
                lines=[OrderLine(product_id=product_id, quantity=1)],
                shipping_cents=1234,
            ),
        )
        order_id = order.id
    engine.dispose()
    updated = client.patch(
        f"/api/v1/admin/products/{product_id}",
        json={"name": "Renamed fixture", "unit_price_cents": 2600, "active": False},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert updated.status_code == 200
    assert updated.json()["unit_price_cents"] == 2600
    assert client.get("/api/v1/products").json()["products"] == []
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        item = session.scalar(select(OrderItem).where(OrderItem.order_id == order_id))
        assert item is not None
        assert item.unit_price_cents == 2500
        assert item.product_name == "Fixture product"
        assert item.line_total_cents == 2500
    engine.dispose()
    reset_engine()
    get_settings.cache_clear()


def test_product_audit_records_owner_changes_and_stays_private(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    created = client.post("/api/v1/admin/products", json=PRODUCT)
    assert created.status_code == 401
    _login()
    saved = _create(PRODUCT)
    assert saved.status_code == 201
    product_id = saved.json()["id"]
    client.cookies.clear()
    assert client.get(f"/api/v1/admin/products/{product_id}/audit").status_code == 401
    _login()
    history = client.get(f"/api/v1/admin/products/{product_id}/audit")
    assert history.status_code == 200
    created_event = history.json()["events"][0]
    assert created_event["actor"] == EMAIL
    price = next(change for change in created_event["changes"] if change["field"] == "unit_price_cents")
    assert price == {"field": "unit_price_cents", "previous": None, "new": None}
    assert {change["field"] for change in created_event["changes"]} <= {
        "name",
        "slug",
        "description",
        "short_description",
        "sku",
        "unit_price_cents",
        "currency",
        "active",
        "in_stock",
        "specification_enabled",
    }
    updated = client.patch(
        f"/api/v1/admin/products/{product_id}",
        json={"name": "Renamed fixture"},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert updated.status_code == 200
    again = client.get(f"/api/v1/admin/products/{product_id}/audit")
    assert again.status_code == 200
    change = again.json()["events"][1]["changes"]
    assert change == [{"field": "name", "previous": "Fixture product", "new": "Renamed fixture"}]
    conflict = _create(dict(PRODUCT, sku="FIX-OTHER"))
    assert conflict.status_code == 409
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        assert session.scalar(select(func.count()).select_from(ProductAuditEvent)) == 2
        assert session.scalar(select(func.count()).select_from(OrderStatusEvent)) == 0
    engine.dispose()
    assert client.get(f"/api/v1/products/{product_id}/audit").status_code == 404
    reset_engine()
    get_settings.cache_clear()


_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _priced(slug: str, sku: str, **extra) -> dict:
    body = dict(PRODUCT, slug=slug, sku=sku, active=True)
    body.update(extra)
    return body


def test_rand_prices_convert_to_cents_and_invalid_prices_are_refused(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    _login()
    expected = {"1.00": 100, "1550.00": 155000, "1550.50": 155050, "1550,50": 155050}
    for index, (price, cents) in enumerate(expected.items()):
        saved = _create(_priced(f"fixture-rand-{index}", f"RAND-{index}", price_rands=price))
        assert saved.status_code == 201
        assert saved.json()["unit_price_cents"] == cents
    edited = client.patch(
        f"/api/v1/admin/products/{saved.json()['id']}",
        json={"price_rands": "10.50"},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert edited.status_code == 200
    assert edited.json()["unit_price_cents"] == 1050
    assert edited.json()["slug"] == "fixture-rand-3"
    for price in ("0", "0.00", "-1", "12.345", "abc", "1.000", "R1550", "1,550.00"):
        refused = _create(_priced("fixture-bad-price", None, price_rands=price))
        assert refused.status_code == 422
    assert _create(_priced("fixture-zero-cents", None, unit_price_cents=0)).status_code == 422
    listed = client.get("/api/v1/admin/products")
    assert listed.status_code == 200
    assert len(listed.json()["products"]) == len(expected)
    reset_engine()
    get_settings.cache_clear()


def test_one_product_image_can_be_replaced_and_is_served_publicly(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    _use_database(monkeypatch, isolated_database_url, str(tmp_path))
    _owner(isolated_database_url)
    assert client.post(
        f"/api/v1/admin/products/{uuid.uuid4()}/image",
        files={"image": ("photo.png", _PNG, "image/png")},
    ).status_code == 401
    _login()
    created = _create(_priced("fixture-image", "IMG-1", price_rands="1550.00"))
    assert created.status_code == 201
    product_id = created.json()["id"]
    blocked = client.post(
        f"/api/v1/admin/products/{product_id}/image",
        files={"image": ("photo.png", _PNG, "image/png")},
    )
    assert blocked.status_code == 403
    refused_type = client.post(
        f"/api/v1/admin/products/{product_id}/image",
        files={"image": ("notes.gif", b"GIF89a", "image/gif")},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert refused_type.status_code == 422
    oversized = b"\xff\xd8\xff" + (b"\x00" * (5 * 1024 * 1024))
    refused_size = client.post(
        f"/api/v1/admin/products/{product_id}/image",
        files={"image": ("large.jpg", oversized, "image/jpeg")},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert refused_size.status_code == 422
    first = client.post(
        f"/api/v1/admin/products/{product_id}/image",
        files={"image": ("../../photo.png", _PNG, "image/png")},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert first.status_code == 200
    first_url = first.json()["image_url"]
    assert first_url.startswith("/media/products/")
    assert "\\" not in first_url and "photo.png" not in first_url
    stored = client.get(first_url)
    assert stored.status_code == 200
    assert stored.headers["content-type"].startswith("image/png")
    assert stored.content == _PNG
    public = client.get("/api/v1/products")
    assert public.json()["products"][0]["image_url"] == first_url
    replacement = b"\xff\xd8\xff" + b"\x00" * 32
    second = client.post(
        f"/api/v1/admin/products/{product_id}/image",
        files={"image": ("other.jpg", replacement, "image/jpeg")},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert second.status_code == 200
    second_url = second.json()["image_url"]
    assert second_url != first_url
    assert client.get(first_url).status_code == 404
    assert client.get(second_url).content == replacement
    assert len(list(tmp_path.iterdir())) == 1
    assert client.get("/api/v1/admin/products").json()["products"].__len__() == 1
    reset_engine()
    get_settings.cache_clear()


def test_permanently_deleting_a_product_keeps_order_history_and_blocks_purchase(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    _owner(isolated_database_url)
    _login()
    created = _create(_priced("fixture-archive", "ARCH-1", name="Archive fixture", price_rands="1500.00"))
    assert created.status_code == 201
    product_id = uuid.UUID(created.json()["id"])
    kept = _create(_priced("fixture-kept", "ARCH-2", name="Kept fixture", price_rands="900.00"))
    assert kept.status_code == 201
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        order = create_order(
            session,
            OrderDraft(
                idempotency_key="fixture-archive-order",
                customer_name="Fixture Customer",
                customer_email="fixture@example.com",
                delivery=DeliveryAddress(
                    name="Fixture Customer",
                    line1="1 Fixture Street",
                    city="Pretoria",
                    region="Gauteng",
                    postal_code="0002",
                ),
                lines=[OrderLine(product_id=product_id, quantity=2)],
                shipping_cents=8500,
            ),
        )
        order_id = order.id
        item_id = order.items[0].id
    engine.dispose()
    client.cookies.clear()
    assert client.delete(f"/api/v1/admin/products/{product_id}").status_code == 401
    _login()
    mismatched = client.delete(
        f"/api/v1/admin/products/{product_id}",
        headers={"X-CSRF-Token": "not-the-cookie"},
    )
    assert mismatched.status_code == 403
    removed = client.delete(
        f"/api/v1/admin/products/{product_id}",
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert removed.status_code == 204
    assert client.delete(
        f"/api/v1/admin/products/{product_id}",
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    ).status_code == 404
    assert client.patch(
        f"/api/v1/admin/products/{product_id}",
        json={"name": "Should stay deleted"},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    ).status_code == 404
    listed = client.get("/api/v1/admin/products")
    assert [item["slug"] for item in listed.json()["products"]] == ["fixture-kept"]
    public = client.get("/api/v1/products")
    assert [item["slug"] for item in public.json()["products"]] == ["fixture-kept"]
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        assert session.get(Product, product_id) is None
        item = session.get(OrderItem, item_id)
        assert item is not None
        assert item.order_id == order_id
        assert item.product_id is None
        assert item.product_name == "Archive fixture"
        assert item.sku == "ARCH-1"
        assert item.quantity == 2
        assert item.unit_price_cents == 150000
        assert item.line_total_cents == 300000
        with pytest.raises(OrderValidationError):
            create_order(
                session,
                OrderDraft(
                    idempotency_key="fixture-archive-second",
                    customer_name="Fixture Customer",
                    customer_email="fixture@example.com",
                    delivery=DeliveryAddress(
                        name="Fixture Customer",
                        line1="1 Fixture Street",
                        city="Pretoria",
                        region="Gauteng",
                        postal_code="0002",
                    ),
                    lines=[OrderLine(product_id=product_id, quantity=1)],
                    shipping_cents=0,
                ),
            )
    engine.dispose()
    reset_engine()
    get_settings.cache_clear()
