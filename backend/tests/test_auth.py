"""Owner authentication tests. Passwords here are fixtures, not real accounts."""

import sys
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.admin.bootstrap import main
from app.auth.service import OwnerExistsError, create_initial_owner
from app.core.config import get_settings
from app.db.session import reset_engine
from app.main import app
from app.models.admin import AdminUser
from app.models.auth import AdminSession

client = TestClient(app)
EMAIL = "fixture-owner@example.com"
PASSWORD = "fixture-password-1"


def _use_database(monkeypatch, database_url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", database_url)
    get_settings.cache_clear()
    reset_engine()
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM auth_login_attempts"))
        connection.execute(text("DELETE FROM admin_sessions"))
        connection.execute(text("DELETE FROM admin_users"))
    engine.dispose()
    client.cookies.clear()


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


def _login(email: str = EMAIL, password: str = PASSWORD):
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers={"X-CSRF-Token": _csrf()},
    )
    if response.status_code == 200:
        _replace_cookie("autonovent_session", _cookie_value(_set_cookie(response, "autonovent_session")))
        _replace_cookie("autonovent_csrf", _cookie_value(_set_cookie(response, "autonovent_csrf")))
    return response


def _cookie_value(set_cookie: str) -> str:
    return set_cookie.split("=", 1)[1].split(";", 1)[0]


def test_owner_can_log_in_and_read_only_safe_profile(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        create_initial_owner(session, EMAIL, PASSWORD)
        stored = session.scalar(select(AdminUser))
        assert stored is not None
        assert stored.password_hash.startswith("$argon2id$")
        assert PASSWORD not in stored.password_hash
    engine.dispose()

    unauthenticated = client.get("/api/v1/auth/me")
    assert unauthenticated.status_code == 401

    logged_in = _login()
    assert logged_in.status_code == 200
    assert logged_in.json() == {"email": EMAIL, "role": "owner"}
    assert "password" not in logged_in.text.lower()
    session_cookie = _set_cookie(logged_in, "autonovent_session")
    csrf_cookie = _set_cookie(logged_in, "autonovent_csrf")
    assert "httponly" in session_cookie.lower()
    assert "samesite=lax" in session_cookie.lower()
    assert "secure" not in session_cookie.lower()
    assert "httponly" not in csrf_cookie.lower()
    assert client.get("/api/v1/auth/me").json()["email"] == EMAIL


def test_invalid_login_is_generic(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        create_initial_owner(session, EMAIL, PASSWORD)
    engine.dispose()
    unknown = _login(email="missing@example.com")
    wrong = _login(password="fixture-password-2")
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json() == {"detail": "The email or password is not correct."}


def test_login_requires_csrf_and_logout_invalidates_the_session(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        create_initial_owner(session, EMAIL, PASSWORD)
    engine.dispose()
    missing = client.post("/api/v1/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert missing.status_code == 403

    logged_in = _login()
    assert logged_in.status_code == 200
    blocked = client.post("/api/v1/auth/logout")
    assert blocked.status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200
    logged_out = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": _cookie("autonovent_csrf")})
    assert logged_out.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_expired_and_revoked_sessions_are_rejected(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        create_initial_owner(session, EMAIL, PASSWORD)
    engine.dispose()
    assert _login().status_code == 200
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        row = session.scalar(select(AdminSession))
        assert row is not None
        row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        session.commit()
    engine.dispose()
    assert client.get("/api/v1/auth/me").status_code == 401

    client.cookies.clear()
    assert _login().status_code == 200
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        current = session.scalar(select(AdminSession).where(AdminSession.revoked_at.is_(None)))
        assert current is not None
        current.revoked_at = datetime.now(timezone.utc)
        session.commit()
    engine.dispose()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_replaces_an_existing_session(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        create_initial_owner(session, EMAIL, PASSWORD)
    engine.dispose()
    assert _login().status_code == 200
    previous = _cookie("autonovent_session")
    assert _login().status_code == 200
    replacement = _cookie("autonovent_session")
    assert previous != replacement
    client.cookies.clear()
    _replace_cookie("autonovent_session", previous)
    assert client.get("/api/v1/auth/me").status_code == 401
    _replace_cookie("autonovent_session", replacement)
    _replace_cookie("autonovent_csrf", "unused")
    assert client.get("/api/v1/auth/me").status_code == 200


def test_login_rate_limit(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    monkeypatch.setenv("AUTH_LOGIN_MAX_FAILURES", "2")
    get_settings.cache_clear()
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        create_initial_owner(session, EMAIL, PASSWORD)
    engine.dispose()
    assert _login(password="fixture-password-2").status_code == 401
    assert _login(password="fixture-password-3").status_code == 401
    blocked = _login()
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Too many login attempts. Try again later."
    get_settings.cache_clear()


def test_secure_cookie_in_production(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("CHECKOUT_SIMULATION_ENABLED", "false")
    monkeypatch.setenv("CHECKOUT_SIMULATION_DEMO_UNIT_PRICE_CENTS", "")
    monkeypatch.setenv("EMAIL_TRANSPORT", "smtp")
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("EMAIL_FROM", "Autonovent <orders@example.com>")
    get_settings.cache_clear()
    engine = create_engine(isolated_database_url)
    with Session(engine, expire_on_commit=False) as session:
        create_initial_owner(session, EMAIL, PASSWORD)
    engine.dispose()
    logged_in = _login()
    assert logged_in.status_code == 200
    session_cookie = _set_cookie(logged_in, "autonovent_session").lower()
    assert "secure" in session_cookie
    assert "httponly" in session_cookie
    assert "samesite=lax" in session_cookie
    monkeypatch.delenv("APP_ENV", raising=False)
    get_settings.cache_clear()


def test_provisioning_refuses_a_second_owner(monkeypatch, isolated_database_url: str) -> None:
    _use_database(monkeypatch, isolated_database_url)
    monkeypatch.setattr(sys, "argv", ["bootstrap"])
    answers = iter([EMAIL, EMAIL])
    passwords = iter([PASSWORD, PASSWORD, PASSWORD, PASSWORD])
    assert main(read_email=lambda _prompt: next(answers), read_password=lambda _prompt: next(passwords)) == 0
    assert main(read_email=lambda _prompt: next(answers), read_password=lambda _prompt: next(passwords)) == 1
    engine = create_engine(isolated_database_url)
    with Session(engine) as session:
        with pytest.raises(OwnerExistsError):
            create_initial_owner(session, "other-fixture@example.com", PASSWORD)
    engine.dispose()
    monkeypatch.setattr(sys, "argv", ["bootstrap", "--password", PASSWORD])
    assert main() == 2


def test_registration_is_not_public() -> None:
    response = client.post("/api/v1/auth/register", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 404


def _set_cookie(response, name: str) -> str:
    matches = [value for value in response.headers.get_list("set-cookie") if value.startswith(name + "=")]
    assert matches
    return matches[0]
