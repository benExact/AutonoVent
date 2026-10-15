"""Bob Go sandbox rate quotes.

The client asks Bob Go for courier rates. It does not book shipments, and it does not
call the production API. Packed parcel measurements and the collection street address
must be supplied by the caller. Product unit size is not a packed parcel.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import httpx

SANDBOX_BASE_URL = "https://api.sandbox.bobgo.co.za/v2"
RATES_PATH = "/rates"


class BobGoError(Exception):
    """A rate quote could not be completed. No shipping fee is implied."""


class BobGoConfigurationError(BobGoError):
    """Sandbox settings are missing or point outside the sandbox."""


class BobGoAuthenticationError(BobGoError):
    """The sandbox rejected the bearer token."""


class BobGoTimeoutError(BobGoError):
    """The sandbox did not answer before the configured timeout."""


class BobGoInvalidResponseError(BobGoError):
    """The sandbox answered with a body that does not match the documented rate fields."""


class BobGoUnavailableError(BobGoError):
    """The sandbox could not provide rates."""


@dataclass(frozen=True)
class SouthAfricanAddress:
    street_address: str
    local_area: str
    city: str
    zone: str
    postal_code: str
    company: str | None = None


@dataclass(frozen=True)
class PackedParcel:
    """Confirmed packed size and weight. Unit product measurements are not accepted here by default."""

    description: str
    length_mm: int
    width_mm: int
    height_mm: int
    weight_grams: int


@dataclass(frozen=True)
class ShippingRate:
    provider_slug: str
    service_level_code: str
    total_price_cents: int | None


@dataclass(frozen=True)
class ShippingQuote:
    rates: list[ShippingRate]


class BobGoSandboxClient:
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
            raise BobGoConfigurationError("Bob Go requests are limited to the sandbox API.")
        self._base_url = normalized
        self._api_token = api_token.strip()
        if timeout_seconds <= 0:
            raise BobGoConfigurationError("Bob Go timeout must be positive.")
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def __repr__(self) -> str:
        return "BobGoSandboxClient(base_url='https://api.sandbox.bobgo.co.za/v2')"

    def quote(
        self,
        *,
        collection: SouthAfricanAddress,
        delivery: SouthAfricanAddress,
        parcels: list[PackedParcel],
        declared_value_cents: int | None = None,
    ) -> ShippingQuote:
        if not self._api_token:
            raise BobGoConfigurationError("BOBGO_API_TOKEN is not configured.")
        payload = _rate_payload(
            collection=collection,
            delivery=delivery,
            parcels=parcels,
            declared_value_cents=declared_value_cents,
            provider_timeout_ms=int(self._timeout_seconds * 1000),
        )
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
            raise BobGoTimeoutError("The Bob Go sandbox did not respond in time.") from None
        except httpx.HTTPError:
            raise BobGoUnavailableError("The Bob Go sandbox could not be reached.") from None
        return _quote_from_response(response)


def _rate_payload(
    *,
    collection: SouthAfricanAddress,
    delivery: SouthAfricanAddress,
    parcels: list[PackedParcel],
    declared_value_cents: int | None,
    provider_timeout_ms: int,
) -> dict[str, Any]:
    if not parcels:
        raise BobGoConfigurationError("A packed parcel is required before requesting a rate.")
    payload: dict[str, Any] = {
        "collection_address": _address_payload(collection),
        "delivery_address": _address_payload(delivery),
        "parcels": [_parcel_payload(parcel) for parcel in parcels],
        "timeout": provider_timeout_ms,
    }
    if declared_value_cents is not None:
        if declared_value_cents < 0:
            raise BobGoConfigurationError("Declared value cannot be negative.")
        payload["declared_value"] = float(Decimal(declared_value_cents) / Decimal(100))
    return payload


def _address_payload(address: SouthAfricanAddress) -> dict[str, str]:
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
            raise BobGoConfigurationError(f"A South African address requires {name}.")
    if address.company and address.company.strip():
        fields["company"] = address.company.strip()
    return {name: value.strip() for name, value in fields.items()}


def _parcel_payload(parcel: PackedParcel) -> dict[str, Any]:
    if not parcel.description.strip():
        raise BobGoConfigurationError("A packed parcel requires a description.")
    for name, value in (
        ("length_mm", parcel.length_mm),
        ("width_mm", parcel.width_mm),
        ("height_mm", parcel.height_mm),
        ("weight_grams", parcel.weight_grams),
    ):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise BobGoConfigurationError(f"A packed parcel requires a positive {name}.")
    return {
        "description": parcel.description.strip(),
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
        raise BobGoAuthenticationError("The Bob Go sandbox rejected the API token.")
    if response.status_code >= 400:
        raise BobGoUnavailableError("The Bob Go sandbox could not provide rates.")
    try:
        body = response.json()
    except json.JSONDecodeError:
        raise BobGoInvalidResponseError("The Bob Go sandbox returned invalid JSON.") from None
    if not isinstance(body, Mapping):
        raise BobGoInvalidResponseError("The Bob Go sandbox returned an unexpected rate response.")
    return ShippingQuote(rates=_rates_from_body(body))


def _rates_from_body(body: Mapping[str, Any]) -> list[ShippingRate]:
    found: list[ShippingRate] = []
    incomplete = False

    def walk(node: Any) -> None:
        nonlocal incomplete
        if isinstance(node, Mapping):
            has_provider = "provider_slug" in node
            has_service = "service_level_code" in node
            has_price = "total_price" in node
            if has_provider or has_service or has_price:
                if not (has_provider and has_service):
                    incomplete = True
                    return
                found.append(_rate_from_object(node))
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(body)
    if incomplete:
        raise BobGoInvalidResponseError("The Bob Go sandbox returned an incomplete rate.")
    return found


def _rate_from_object(node: Mapping[str, Any]) -> ShippingRate:
    provider_slug = node.get("provider_slug")
    service_level_code = node.get("service_level_code")
    if not isinstance(provider_slug, str) or not provider_slug.strip():
        raise BobGoInvalidResponseError("The Bob Go sandbox returned an incomplete rate.")
    if not isinstance(service_level_code, str) or not service_level_code.strip():
        raise BobGoInvalidResponseError("The Bob Go sandbox returned an incomplete rate.")
    price = node.get("total_price")
    cents: int | None = None
    if price is not None:
        if isinstance(price, bool) or not isinstance(price, (int, float)):
            raise BobGoInvalidResponseError("The Bob Go sandbox returned an unreadable rate price.")
        if price < 0:
            raise BobGoInvalidResponseError("The Bob Go sandbox returned a negative rate price.")
        cents = int((Decimal(str(price)) * Decimal(100)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return ShippingRate(
        provider_slug=provider_slug.strip(),
        service_level_code=service_level_code.strip(),
        total_price_cents=cents,
    )
