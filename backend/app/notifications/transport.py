"""Email transports. Capture never opens a network connection."""

import re
import smtplib
import uuid
from dataclasses import dataclass
from email.message import EmailMessage

import resend
from resend.exceptions import ResendError

from app.core.config import Settings


class EmailDeliveryError(Exception):
    pass


@dataclass(frozen=True)
class DeliveryReceipt:
    provider: str
    message_id: str


@dataclass(frozen=True)
class OutgoingEmail:
    recipient: str
    subject: str
    text_body: str
    html_body: str


CAPTURED: list[OutgoingEmail] = []


def clear_captured() -> None:
    CAPTURED.clear()


class CaptureTransport:
    name = "capture"

    def send(self, message: OutgoingEmail) -> DeliveryReceipt:
        CAPTURED.append(message)
        return DeliveryReceipt(provider=self.name, message_id=f"capture-{uuid.uuid4().hex}")


class SmtpTransport:
    name = "smtp"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, message: OutgoingEmail) -> DeliveryReceipt:
        email = EmailMessage()
        message_id = f"<{uuid.uuid4().hex}@autonovent.local>"
        email["From"] = self.settings.email_from
        email["To"] = message.recipient
        email["Subject"] = message.subject
        email["Message-ID"] = message_id
        email.set_content(message.text_body)
        email.add_alternative(message.html_body, subtype="html")
        try:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=10) as smtp:
                if self.settings.smtp_use_tls:
                    smtp.starttls()
                if self.settings.smtp_username:
                    smtp.login(self.settings.smtp_username, self.settings.smtp_password)
                smtp.send_message(email)
        except (OSError, smtplib.SMTPException) as exc:
            raise EmailDeliveryError(_safe_error(exc)) from None
        return DeliveryReceipt(provider=self.name, message_id=message_id)


class ResendTransport:
    name = "resend"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, message: OutgoingEmail) -> DeliveryReceipt:
        resend.api_key = self.settings.resend_api_key
        try:
            result = resend.Emails.send(
                {
                    "from": self.settings.email_from,
                    "to": [message.recipient],
                    "subject": message.subject,
                    "text": message.text_body,
                    "html": message.html_body,
                }
            )
        except (ResendError, OSError, ValueError) as exc:
            raise EmailDeliveryError(_safe_error(exc, self.settings.resend_api_key)) from None
        message_id = _resend_id(result)
        if not message_id:
            raise EmailDeliveryError("Resend did not accept the message.")
        return DeliveryReceipt(provider=self.name, message_id=message_id)


def build_transport(settings: Settings) -> CaptureTransport | SmtpTransport | ResendTransport:
    if settings.email_transport == "smtp":
        return SmtpTransport(settings)
    if settings.email_transport == "resend":
        return ResendTransport(settings)
    return CaptureTransport()


def _resend_id(result: object) -> str:
    if isinstance(result, dict):
        return str(result.get("id") or "").strip()
    return str(getattr(result, "id", "") or "").strip()


def _safe_error(exc: Exception, secret: str = "") -> str:
    text = " ".join(str(exc).split())
    if secret:
        text = text.replace(secret, "[redacted]")
    text = re.sub(r"re_[A-Za-z0-9_\-]+", "[redacted]", text)
    lowered = text.lower()
    if any(word in lowered for word in ("password", "secret", "token", "credential", "api_key", "api key")):
        text = "The email transport rejected the connection."
    return text[:300] or "The email could not be accepted."
