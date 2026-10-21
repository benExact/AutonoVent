"""Shared fixtures. Database tests stay on the local isolated database."""

import pytest

from app.core.config import get_settings
from tests.local_db import ensure_isolated_database


@pytest.fixture(scope="module")
def isolated_database_url() -> str:
    return ensure_isolated_database()


@pytest.fixture(autouse=True)
def capture_customer_email(monkeypatch):
    monkeypatch.setenv("EMAIL_TRANSPORT", "capture")
    monkeypatch.setenv("CHECKOUT_SIMULATION_ENABLED", "true")
    monkeypatch.setenv("COURIER_PROVIDER", "")
    monkeypatch.setenv("PAYMENT_PROVIDER", "")
    monkeypatch.setenv("PAYFAST_MODE", "")
    monkeypatch.setenv("PAYFAST_MERCHANT_ID", "")
    monkeypatch.setenv("PAYFAST_MERCHANT_KEY", "")
    monkeypatch.setenv("PAYFAST_PASSPHRASE", "")
    monkeypatch.setenv("PAYFAST_NOTIFY_URL", "")
    monkeypatch.setenv("SHIPLOGIC_API_TOKEN", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
