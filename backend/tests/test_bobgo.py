"""Bob Go sandbox client tests. They do not contact Bob Go."""

import json

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.shipping.bobgo import (
    SANDBOX_BASE_URL,
    BobGoAuthenticationError,
    BobGoConfigurationError,
    BobGoInvalidResponseError,
    BobGoSandboxClient,
    BobGoTimeoutError,
    BobGoUnavailableError,
    PackedParcel,
    SouthAfricanAddress,
)

TOKEN = "sandbox-token-for-tests"


def address(city: str = "Pretoria", postal_code: str = "0002") -> SouthAfricanAddress:
    return SouthAfricanAddress(
        street_address="Example Street 1",
        local_area="Example suburb",
        city=city,
        zone="Gauteng",
        postal_code=postal_code,
        company="Example company",
    )


def parcel() -> PackedParcel:
    return PackedParcel(
        description="Packed carton",
        length_mm=200,
        width_mm=100,
        height_mm=41,
        weight_grams=1500,
    )


def client(handler) -> BobGoSandboxClient:
    return BobGoSandboxClient(
        base_url=SANDBOX_BASE_URL,
        api_token=TOKEN,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )


def test_valid_rates_use_packed_measurements_and_documented_fields() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={
                "rates": [
                    {"provider_slug": "sandbox", "service_level_code": "ECO", "total_price": 44.61},
                    {"provider_slug": "demo", "service_level_code": "EXPRESS"},
                ]
            },
        )

    quote = client(handler).quote(collection=address(), delivery=address("Johannesburg", "2191"), parcels=[parcel()])

    assert seen["url"] == "https://api.sandbox.bobgo.co.za/v2/rates"
    assert seen["authorization"] == f"Bearer {TOKEN}"
    assert "declared_value" not in seen["body"]
    parcel_body = seen["body"]["parcels"][0]
    assert parcel_body["submitted_length_cm"] == 20
    assert parcel_body["submitted_width_cm"] == 10
    assert parcel_body["submitted_height_cm"] == 4.1
    assert parcel_body["submitted_weight_kg"] == 1.5
    assert [rate.provider_slug for rate in quote.rates] == ["sandbox", "demo"]
    assert quote.rates[0].service_level_code == "ECO"
    assert quote.rates[0].total_price_cents == 4461
    assert quote.rates[1].total_price_cents is None
    assert TOKEN not in repr(client(handler))


def test_no_available_rates() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rates": []})

    quote = client(handler).quote(collection=address(), delivery=address(), parcels=[parcel()])
    assert quote.rates == []


def test_incomplete_rate_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rates": [{"provider_slug": "sandbox", "total_price": 10}]})

    with pytest.raises(BobGoInvalidResponseError):
        client(handler).quote(collection=address(), delivery=address(), parcels=[parcel()])


def test_invalid_json_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    with pytest.raises(BobGoInvalidResponseError):
        client(handler).quote(collection=address(), delivery=address(), parcels=[parcel()])


def test_timeout_does_not_fabricate_a_rate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    with pytest.raises(BobGoTimeoutError) as caught:
        client(handler).quote(collection=address(), delivery=address(), parcels=[parcel()])
    assert TOKEN not in str(caught.value)


def test_authentication_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthenticated"})

    with pytest.raises(BobGoAuthenticationError) as caught:
        client(handler).quote(collection=address(), delivery=address(), parcels=[parcel()])
    assert TOKEN not in str(caught.value)


def test_server_error_does_not_fabricate_a_rate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "unavailable"})

    with pytest.raises(BobGoUnavailableError):
        client(handler).quote(collection=address(), delivery=address(), parcels=[parcel()])


def test_missing_token_and_production_url_are_refused() -> None:
    sandbox = BobGoSandboxClient(base_url=SANDBOX_BASE_URL, api_token="", timeout_seconds=5)
    with pytest.raises(BobGoConfigurationError):
        sandbox.quote(collection=address(), delivery=address(), parcels=[parcel()])
    with pytest.raises(BobGoConfigurationError):
        BobGoSandboxClient(base_url="https://api.bobgo.co.za/v2", api_token=TOKEN, timeout_seconds=5)


def test_missing_collection_street_is_refused_before_the_request() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"rates": []})

    collection = address()
    incomplete = SouthAfricanAddress(
        street_address=" ",
        local_area=collection.local_area,
        city=collection.city,
        zone=collection.zone,
        postal_code=collection.postal_code,
    )
    with pytest.raises(BobGoConfigurationError):
        client(handler).quote(collection=incomplete, delivery=address(), parcels=[parcel()])
    assert called is False


def test_settings_reject_the_production_api() -> None:
    with pytest.raises(ValidationError):
        Settings(bobgo_base_url="https://api.bobgo.co.za/v2", bobgo_api_token="")
