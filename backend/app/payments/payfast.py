"""PayFast sandbox hosted checkout and ITN checks.

The process URL and the validation URL are the sandbox hosts only.
Card numbers are never accepted or stored.
"""

import hashlib
import ipaddress
from collections.abc import Mapping
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import quote_plus

import httpx

SANDBOX_PROCESS_URL = "https://sandbox.payfast.co.za/eng/process"
SANDBOX_VALIDATE_URL = "https://sandbox.payfast.co.za/eng/query/validate"
CHECKOUT_FIELD_ORDER = (
    "merchant_id",
    "merchant_key",
    "return_url",
    "cancel_url",
    "notify_url",
    "name_first",
    "name_last",
    "email_address",
    "cell_number",
    "m_payment_id",
    "amount",
    "item_name",
    "item_description",
    "custom_int1",
    "custom_int2",
    "custom_int3",
    "custom_int4",
    "custom_int5",
    "custom_str1",
    "custom_str2",
    "custom_str3",
    "custom_str4",
    "custom_str5",
    "email_confirmation",
    "confirmation_address",
    "payment_method",
)
PAYFAST_NETWORKS = (
    ipaddress.ip_network("197.97.145.144/28"),
    ipaddress.ip_network("41.74.179.192/27"),
    ipaddress.ip_network("102.216.36.0/28"),
    ipaddress.ip_network("102.216.36.128/28"),
    ipaddress.ip_network("144.126.193.139/32"),
)


class PayfastError(Exception):
    """A PayFast sandbox step could not be completed."""


class PayfastConfigurationError(PayfastError):
    """Sandbox settings are missing or point outside the sandbox."""


class PayfastVerificationError(PayfastError):
    """The notification did not pass PayFast's checks."""


def zar_amount(cents: int) -> str:
    if not isinstance(cents, int) or isinstance(cents, bool) or cents < 0:
        raise PayfastConfigurationError("The payable amount is not valid.")
    return f"{cents // 100}.{cents % 100:02d}"


def payfast_encode(value: str) -> str:
    return quote_plus(value, safe="").replace("~", "%7E")


def signature(fields: Mapping[str, str], passphrase: str, *, order: tuple[str, ...] = CHECKOUT_FIELD_ORDER) -> str:
    parts = [f"{name}={payfast_encode(fields[name])}" for name in order if fields.get(name, "").strip()]
    if passphrase.strip():
        parts.append(f"passphrase={payfast_encode(passphrase.strip())}")
    return hashlib.md5("&".join(parts).encode()).hexdigest()


def checkout_fields(
    *,
    merchant_id: str,
    merchant_key: str,
    passphrase: str,
    return_url: str,
    cancel_url: str,
    notify_url: str,
    name_first: str,
    name_last: str,
    email_address: str,
    cell_number: str,
    payment_id: str,
    amount_cents: int,
    item_name: str,
) -> dict[str, str]:
    if not merchant_id.strip() or not merchant_key.strip():
        raise PayfastConfigurationError("PayFast sandbox merchant details are not configured.")
    if not notify_url.lower().startswith("https://"):
        raise PayfastConfigurationError("PayFast needs an https notification URL.")
    for label, url in (("return", return_url), ("cancel", cancel_url)):
        if not url.strip().lower().startswith(("http://", "https://")):
            raise PayfastConfigurationError(f"PayFast needs an absolute {label} URL.")
    fields = {
        "merchant_id": merchant_id.strip(),
        "merchant_key": merchant_key.strip(),
        "return_url": return_url.strip(),
        "cancel_url": cancel_url.strip(),
        "notify_url": notify_url.strip(),
        "name_first": name_first.strip(),
        "name_last": name_last.strip(),
        "email_address": email_address.strip(),
        "cell_number": cell_number.strip(),
        "m_payment_id": payment_id.strip(),
        "amount": zar_amount(amount_cents),
        "item_name": item_name.strip(),
        "item_description": "Autonovent sandbox order",
        "custom_str1": "sandbox",
    }
    fields["signature"] = signature(fields, passphrase)
    return {name: value for name, value in fields.items() if value.strip()}


def itn_parameter_string(pairs: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    for name, value in pairs:
        if name == "signature":
            break
        parts.append(f"{name}={payfast_encode(value)}")
    return "&".join(parts)


def itn_signature_matches(parameter_string: str, passphrase: str, received: str) -> bool:
    signed = parameter_string
    if passphrase.strip():
        signed = f"{parameter_string}&passphrase={payfast_encode(passphrase.strip())}"
    expected = hashlib.md5(signed.encode()).hexdigest()
    return expected == received.strip().lower()


def ip_is_payfast(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return any(address in network for network in PAYFAST_NETWORKS)


def amount_matches(cents: int, gross: str) -> bool:
    try:
        reported = int((Decimal(gross) * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except Exception:
        return False
    return reported == cents


def validate_with_payfast(parameter_string: str, *, transport: httpx.BaseTransport | None = None, timeout_seconds: float = 15) -> bool:
    try:
        with httpx.Client(transport=transport, timeout=timeout_seconds) as http:
            response = http.post(
                SANDBOX_VALIDATE_URL,
                content=parameter_string,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except httpx.HTTPError:
        return False
    return response.status_code == 200 and response.text.strip().upper() == "VALID"
