"""Homepage carousel. Public visitors only see enabled slides."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from app.auth.service import create_initial_owner
from app.core.config import get_settings
from app.db.session import reset_engine
from app.main import app
from sqlalchemy.orm import Session

client = TestClient(app)
EMAIL = "carousel-owner@example.com"
PASSWORD = "fixture-password-1"
JPEG = b"\xff\xd8\xff" + b"\x00" * 32


def _use_database(monkeypatch, database_url: str, image_dir: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("CAROUSEL_IMAGE_DIR", image_dir)
    get_settings.cache_clear()
    reset_engine()
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM auth_login_attempts"))
        connection.execute(text("DELETE FROM admin_sessions"))
        connection.execute(text("DELETE FROM admin_users"))
        connection.execute(text("DELETE FROM carousel_slides"))
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


def _csrf() -> str:
    response = client.get("/api/v1/auth/csrf")
    token = response.json()["csrf_token"] or _cookie("autonovent_csrf")
    client.cookies.set("autonovent_csrf", token)
    return token


def _set_cookie(response, name: str) -> str:
    matches = [value for value in response.headers.get_list("set-cookie") if value.startswith(name + "=")]
    assert matches
    return matches[-1].split("=", 1)[1].split(";", 1)[0]


def _login() -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": EMAIL, "password": PASSWORD},
        headers={"X-CSRF-Token": _csrf()},
    )
    assert response.status_code == 200
    client.cookies.set("autonovent_session", _set_cookie(response, "autonovent_session"))
    client.cookies.set("autonovent_csrf", _set_cookie(response, "autonovent_csrf"))


def _create(order: str, enabled: str) -> dict:
    response = client.post(
        "/api/v1/admin/carousel",
        data={
            "title": "Banner " + order,
            "message": "A short promotion.",
            "display_order": order,
            "enabled": enabled,
        },
        files={"image": ("banner.jpg", JPEG, "image/jpeg")},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_carousel_management_requires_an_owner(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    _use_database(monkeypatch, isolated_database_url, str(tmp_path))
    assert client.get("/api/v1/admin/carousel").status_code == 401
    assert client.post("/api/v1/admin/carousel").status_code == 401
    assert client.patch(f"/api/v1/admin/carousel/{uuid.uuid4()}", json={"enabled": False}).status_code == 401
    assert client.delete(f"/api/v1/admin/carousel/{uuid.uuid4()}").status_code == 401
    assert client.get("/api/v1/carousel").status_code == 200
    assert client.get("/api/v1/carousel").json() == {"slides": []}


def test_owner_manages_slides_and_the_public_list_hides_disabled_ones(monkeypatch, isolated_database_url: str, tmp_path) -> None:
    _use_database(monkeypatch, isolated_database_url, str(tmp_path))
    _owner(isolated_database_url)
    _login()
    later = _create("2", "true")
    hidden = _create("0", "false")
    first = _create("1", "true")
    public = client.get("/api/v1/carousel")
    assert public.status_code == 200
    public_ids = [item["id"] for item in public.json()["slides"]]
    assert public_ids == [first["id"], later["id"]]
    assert hidden["id"] not in public_ids
    assert "destination_url" not in public.json()["slides"][0]
    assert "button_label" not in public.json()["slides"][0]
    bad_file = client.post(
        "/api/v1/admin/carousel",
        data={"display_order": "0", "enabled": "true"},
        files={"image": ("notes.txt", b"not-an-image", "text/plain")},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert bad_file.status_code == 422
    updated = client.patch(
        f"/api/v1/admin/carousel/{hidden['id']}",
        json={"enabled": True, "display_order": 3, "title": "Now visible"},
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert updated.status_code == 200
    assert updated.json()["enabled"] is True
    listed = client.get("/api/v1/admin/carousel")
    assert [item["id"] for item in listed.json()["slides"]] == [first["id"], later["id"], hidden["id"]]
    deleted = client.delete(
        f"/api/v1/admin/carousel/{later['id']}",
        headers={"X-CSRF-Token": _cookie("autonovent_csrf")},
    )
    assert deleted.status_code == 204
    remaining = [item["id"] for item in client.get("/api/v1/carousel").json()["slides"]]
    assert later["id"] not in remaining
