"""Resend transport tests. They mock the SDK and do not call Resend."""

import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.notifications.transport import (
    CaptureTransport,
    EmailDeliveryError,
    OutgoingEmail,
    ResendTransport,
    SmtpTransport,
    build_transport,
)
from resend.exceptions import ResendError


MESSAGE = OutgoingEmail(
    recipient="customer@example.com",
    subject="Autonovent test",
    text_body="Plain text",
    html_body="<p>HTML</p>",
)


def _resend_settings(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("EMAIL_TRANSPORT", "resend")
    monkeypatch.setenv("EMAIL_FROM", "onboarding@resend.dev")
    monkeypatch.setenv("RESEND_API_KEY", "test-key-not-real")
    monkeypatch.setenv("CHECKOUT_SIMULATION_ENABLED", "false")
    monkeypatch.setenv("CHECKOUT_SIMULATION_DEMO_UNIT_PRICE_CENTS", "")
    get_settings.cache_clear()


def test_resend_transport_sends_the_message_and_keeps_the_key_out_of_the_payload(monkeypatch) -> None:
    _resend_settings(monkeypatch)
    captured: dict = {}

    def fake_send(payload):
        captured["payload"] = payload
        return {"id": "email-id-1"}

    monkeypatch.setattr("app.notifications.transport.resend.Emails.send", fake_send)
    receipt = build_transport(get_settings()).send(MESSAGE)
    assert isinstance(build_transport(get_settings()), ResendTransport)
    assert receipt.provider == "resend"
    assert receipt.message_id == "email-id-1"
    assert captured["payload"]["from"] == "onboarding@resend.dev"
    assert captured["payload"]["to"] == ["customer@example.com"]
    assert captured["payload"]["subject"] == "Autonovent test"
    assert captured["payload"]["text"] == "Plain text"
    assert captured["payload"]["html"] == "<p>HTML</p>"
    assert "api_key" not in captured["payload"]
    assert "test-key-not-real" not in str(captured["payload"])


def test_resend_failure_does_not_expose_the_key(monkeypatch) -> None:
    _resend_settings(monkeypatch)

    def fake_send(payload):
        raise ResendError(
            code=403,
            error_type="validation_error",
            message="Rejected test-key-not-real for this recipient.",
            suggested_action="",
        )

    monkeypatch.setattr("app.notifications.transport.resend.Emails.send", fake_send)
    with pytest.raises(EmailDeliveryError) as caught:
        ResendTransport(get_settings()).send(MESSAGE)
    assert "test-key-not-real" not in str(caught.value)
    assert "Rejected" in str(caught.value)


def test_resend_without_an_id_is_not_treated_as_accepted(monkeypatch) -> None:
    _resend_settings(monkeypatch)
    monkeypatch.setattr("app.notifications.transport.resend.Emails.send", lambda payload: {})
    with pytest.raises(EmailDeliveryError, match="did not accept"):
        ResendTransport(get_settings()).send(MESSAGE)


def test_mailpit_smtp_transport_remains_available(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("EMAIL_TRANSPORT", "smtp")
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("EMAIL_FROM", "Autonovent <orders@localhost>")
    monkeypatch.setenv("CHECKOUT_SIMULATION_ENABLED", "false")
    monkeypatch.setenv("CHECKOUT_SIMULATION_DEMO_UNIT_PRICE_CENTS", "")
    get_settings.cache_clear()
    assert isinstance(build_transport(get_settings()), SmtpTransport)


def test_resend_settings_require_a_key_and_production_still_rejects_capture(monkeypatch) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("EMAIL_TRANSPORT", "resend")
    monkeypatch.setenv("EMAIL_FROM", "onboarding@resend.dev")
    monkeypatch.setenv("RESEND_API_KEY", "")
    monkeypatch.setenv("CHECKOUT_SIMULATION_ENABLED", "false")
    monkeypatch.setenv("CHECKOUT_SIMULATION_DEMO_UNIT_PRICE_CENTS", "")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("EMAIL_TRANSPORT", "capture")
    get_settings.cache_clear()
    with pytest.raises(ValidationError):
        get_settings()
    monkeypatch.setenv("EMAIL_TRANSPORT", "resend")
    monkeypatch.setenv("RESEND_API_KEY", "test-key-not-real")
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.email_transport == "resend"
    assert isinstance(build_transport(settings), ResendTransport)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("EMAIL_TRANSPORT", "")
    get_settings.cache_clear()
    assert isinstance(build_transport(get_settings()), CaptureTransport)
