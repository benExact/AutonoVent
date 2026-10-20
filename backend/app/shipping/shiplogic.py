"""ShipLogic sandbox rate quotes for The Courier Guy.

The documented sandbox host is https://api.shiplogic.com. The sandbox account
token selects the sandbox; this client refuses any other host. It requests
rates only. It does not create shipments, labels, or tracking numbers.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx

SANDBOX_BASE_URL = "https://api.shiplogic.com"
RATES_PATH = "/rates"
PROVIDER = "shiplogic"


class ShipLogicError(Exception):
    """A rate quote could not be completed. No shipping fee is implied."""


class ShipLogicConfigurationError(ShipLogicError):
    """Sandbox settings are missing or point outside the documented sandbox host."""


class ShipLogicAuthenticationError(ShipLogicError):
    """The sandbox rejected the bearer token."""


class ShipLogicTimeoutError(ShipLogicError):
    """The sandbox did not answer before the configured timeout."""


class ShipLogicInvalidResponseError(ShipLogicError):
    """The sandbox answered with a body that does not match the documented rate fields."""


class ShipLogicUnavailableError(ShipLogicError):
    """The sandbox could not provide rates."""


@dataclass(frozen=True)
class SouthAfricanAddress:
    street_address: str
    local_area: str
    city: str
    zone: str
    postal_code: str
    company: str | None = None
    address_type: str | None = None


@dataclass(frozen=True)
class PackedParcel:
    """Confirmed packed size and weight. Unit product measurements are not accepted here."""

    description: str
    length_mm: int
    width_mm: int
    height_mm: int
    weight_grams: int


@dataclass(frozen=True)
class ShippingRate:
    provider_slug: str
    service_level_code: str
    service_name: str
    total_price_cents: int
    rate_id: str


@dataclass(frozen=True)
class ShippingQuote:
    rates: list[ShippingRate]


class ShipLogicSandboxClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        timeout_seconds: float,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        if normalized != SANDBOX_BASE_URL:
            raise ShipLogicConfigurationError("ShipLogic sandbox requests are limited to https://api.shiplogic.com.")
        self._base_url = normalized
        self._api_token = api_token.strip()
        if timeout_seconds <= 0:
            raise ShipLogicConfigurationError("ShipLogic timeout must be positive.")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def __repr__(self) -> str:
        return "ShipLogicSandboxClient(base_url='https://api.shiplogic.com')"

    def quote(
        self,
        *,
        collection: SouthAfricanAddress,
        delivery: SouthAfricanAddress,
        parcels: list[PackedParcel],
    ) -> ShippingQuote:
        if not self._api_token:
            raise ShipLogicConfigurationError("SHIPLOGIC_API_TOKEN is not configured.")
        payload = _rate_payload(collection=collection, delivery=delivery, parcels=parcels)
        try:
            with httpx.Client(transport=self._transport, timeout=self._timeout_seconds) as http:
                response = http.post(
                    f"{self._base_url}{RATES_PATH}",
                    headers={
                        "Authorization": f"Bearer {self._api_token}",
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                    },
                    content=json.dumps(payload),
                )
        except httpx.TimeoutException:
            raise ShipLogicTimeoutError("The ShipLogic sandbox did not respond in time.") from None
        except httpx.HTTPError:
            raise ShipLogicUnavailableError("The ShipLogic sandbox could not be reached.") from None
        return _quote_from_response(response)


def _rate_payload(
    *,
    collection: SouthAfricanAddress,
    delivery: SouthAfricanAddress,
    parcels: list[PackedParcel],
) -> dict[str, Any]:
    if not parcels:
        raise ShipLogicConfigurationError("A packed parcel is required before requesting a rate.")
    return {
        "collection_address": _address_payload(collection, default_type="business"),
        "delivery_address": _address_payload(delivery, default_type=None),
        "parcels": [_parcel_payload(parcel) for parcel in parcels],
    }


def _address_payload(address: SouthAfricanAddress, default_type: str | None) -> dict[str, str]:
    fields = {
        "street_address": address.street_address,
        "local_area": address.local_area,
        "city": address.city,
        "zone": address.zone,
        "country": "ZA",
        "code": address.postal_code,
    }
    for name, value in fields.items():
        if not isinstance(value, str) or not value.strip():
            raise ShipLogicConfigurationError(f"A South African address requires {name}.")
    payload = {name: value.strip() for name, value in fields.items()}
    if address.company and address.company.strip():
        payload["company"] = address.company.strip()
    address_type = (address.address_type or default_type or "").strip()
    if address_type:
        payload["type"] = address_type
    return payload


def _parcel_payload(parcel: PackedParcel) -> dict[str, Any]:
    if not parcel.description.strip():
        raise ShipLogicConfigurationError("A packed parcel requires a description.")
    for name, value in (
        ("length_mm", parcel.length_mm),
        ("width_mm", parcel.width_mm),
        ("height_mm", parcel.height_mm),
        ("weight_grams", parcel.weight_grams),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ShipLogicConfigurationError(f"A packed parcel requires a positive {name}.")
    return {
        "submitted_length_cm": _cm_from_mm(parcel.length_mm),
        "submitted_width_cm": _cm_from_mm(parcel.width_mm),
        "submitted_height_cm": _cm_from_mm(parcel.height_mm),
        "submitted_weight_kg": _kg_from_grams(parcel.weight_grams),
    }


def _cm_from_mm(mm: int) -> int | float:
    whole, remainder = divmod(mm, 10)
    if remainder == 0:
        return whole
    return float((Decimal(mm) / Decimal(10)).quantize(Decimal("0.1")))


def _kg_from_grams(grams: int) -> int | float:
    whole, remainder = divmod(grams, 1000)
    if remainder == 0:
        return whole
    return float((Decimal(grams) / Decimal(1000)).quantize(Decimal("0.001")))


def _quote_from_response(response: httpx.Response) -> ShippingQuote:
    if response.status_code in {401, 403}:
        raise ShipLogicAuthenticationError("The ShipLogic sandbox rejected the API token.")
    if response.status_code >= 400:
        raise ShipLogicUnavailableError("The ShipLogic sandbox could not provide rates.")
    try:
        body = response.json()
    except json.JSONDecodeError:
        raise ShipLogicInvalidResponseError("The ShipLogic sandbox returned invalid JSON.") from None
    if not isinstance(body, Mapping) or not isinstance(body.get("rates"), list):
        raise ShipLogicInvalidResponseError("The ShipLogic sandbox returned an unexpected rate response.")
    return ShippingQuote(rates=[_rate_from_object(item) for item in body["rates"]])


def _rate_from_object(node: Any) -> ShippingRate:
    if not isinstance(node, Mapping):
        raise ShipLogicInvalidResponseError("The ShipLogic sandbox returned an incomplete rate.")
    service = node.get("service_level")
    if not isinstance(service, Mapping):
        raise ShipLogicInvalidResponseError("The ShipLogic sandbox returned an incomplete rate.")
    code = service.get("code")
    name = service.get("name")
    service_id = service.get("id")
    price = node.get("rate")
    if not isinstance(code, str) or not code.strip():
        raise ShipLogicInvalidResponseError("The ShipLogic sandbox returned an incomplete rate.")
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        raise ShipLogicInvalidResponseError("The ShipLogic sandbox returned an unreadable rate price.")
    if price < 0:
        raise ShipLogicInvalidResponseError("The ShipLogic sandbox returned a negative rate price.")
    if isinstance(service_id, bool) or not isinstance(service_id, int):
        raise ShipLogicInvalidResponseError("The ShipLogic sandbox returned an incomplete rate.")
    service_name = name.strip() if isinstance(name, str) and name.strip() else code.strip()
    cents = int((Decimal(str(price)) * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return ShippingRate(
        provider_slug=PROVIDER,
        service_level_code=code.strip(),
        service_name=service_name,
        total_price_cents=cents,
        rate_id=str(service_id),
    )
