"""ShipLogic sandbox client tests. They do not contact ShipLogic."""

import json

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.shipping.shiplogic import (
    SANDBOX_BASE_URL,
    PackedParcel,
    ShipLogicAuthenticationError,
    ShipLogicConfigurationError,
    ShipLogicInvalidResponseError,
    ShipLogicSandboxClient,
    ShipLogicTimeoutError,
    ShipLogicUnavailableError,
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


def client(handler) -> ShipLogicSandboxClient:
    return ShipLogicSandboxClient(
        base_url=SANDBOX_BASE_URL,
        api_token=TOKEN,
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )


def _rates(*items):
    return {"message": "Success", "rates": list(items)}


def _rate(code: str, name: str, service_id: int, price: float) -> dict:
    return {
        "rate": price,
        "service_level": {"id": service_id, "code": code, "name": name},
    }


def test_valid_rates_use_the_documented_sandbox_contract() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json=_rates(
                _rate("LOF", "Local Overnight Flyer", 212573, 116.25),
                _rate("ECO", "Economy", 212570, 120),
            ),
        )

    quote = client(handler).quote(collection=address(), delivery=address("Johannesburg", "2191"), parcels=[parcel()])

    assert seen["url"] == "https://api.shiplogic.com/rates"
    assert seen["authorization"] == f"Bearer {TOKEN}"
    assert "declared_value" not in seen["body"]
    assert seen["body"]["collection_address"]["type"] == "business"
    assert seen["body"]["collection_address"]["code"] == "0002"
    assert "type" not in seen["body"]["delivery_address"]
    parcel_body = seen["body"]["parcels"][0]
    assert parcel_body == {
        "submitted_length_cm": 20,
        "submitted_width_cm": 10,
        "submitted_height_cm": 4.1,
        "submitted_weight_kg": 1.5,
    }
    assert [rate.service_level_code for rate in quote.rates] == ["LOF", "ECO"]
    assert quote.rates[0].service_name == "Local Overnight Flyer"
    assert quote.rates[0].total_price_cents == 11625
    assert quote.rates[0].rate_id == "212573"
    assert quote.rates[1].total_price_cents == 12000
    assert TOKEN not in repr(client(handler))


def test_same_day_service_is_omitted_after_its_collection_cut_off() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_rates(
                {
                    "rate": 86.25,
                    "service_level": {
                        "id": 212572,
                        "code": "LSF",
                        "name": "Local Sameday Flyer",
                        "collection_cut_off_time": "2020-01-01T10:30:00+02:00",
                        "delivery_date_from": "2020-01-01T09:00:00+02:00",
                        "delivery_date_to": "2020-01-01T15:00:00+02:00",
                    },
                },
                {
                    "rate": 95,
                    "rate_excluding_vat": 82.61,
                    "service_level": {
                        "id": 212570,
                        "code": "ECO",
                        "name": "Economy",
                        "collection_cut_off_time": "2020-01-01T15:00:00+02:00",
                        "delivery_date_from": "2020-01-03T08:00:00+02:00",
                        "delivery_date_to": "2020-01-06T17:00:00+02:00",
                    },
                },
            ),
        )

    quote = client(handler).quote(collection=address(), delivery=address(), parcels=[parcel()])
    assert [rate.service_level_code for rate in quote.rates] == ["ECO"]
    assert quote.rates[0].total_price_cents == 9500
    assert quote.rates[0].collection_cut_off == "2020-01-01T15:00:00+02:00"


def test_future_same_day_cut_off_stays_available() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_rates(
                {
                    "rate": 86.25,
                    "service_level": {
                        "id": 9,
                        "code": "LSF",
                        "name": "Local Sameday Flyer",
                        "collection_cut_off_time": "2099-01-01T10:30:00+02:00",
                        "delivery_date_from": "2099-01-01T09:00:00+02:00",
                        "delivery_date_to": "2099-01-01T15:00:00+02:00",
                    },
                }
            ),
        )

    quote = client(handler).quote(collection=address(), delivery=address(), parcels=[parcel()])
    assert quote.rates[0].service_level_code == "LSF"
    assert quote.rates[0].total_price_cents == 8625


def test_empty_rates_do_not_invent_a_price() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_rates())

    quote = client(handler).quote(collection=address(), delivery=address(), parcels=[parcel()])
    assert quote.rates == []


def test_incomplete_rate_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"rates": [{"rate": 10}]})

    with pytest.raises(ShipLogicInvalidResponseError):
        client(handler).quote(collection=address(), delivery=address(), parcels=[parcel()])


def test_negative_rate_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_rates(_rate("ECO", "Economy", 1, -1)))

    with pytest.raises(ShipLogicInvalidResponseError):
        client(handler).quote(collection=address(), delivery=address(), parcels=[parcel()])


def test_invalid_json_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json")

    with pytest.raises(ShipLogicInvalidResponseError):
        client(handler).quote(collection=address(), delivery=address(), parcels=[parcel()])


def test_timeout_does_not_fabricate_a_rate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    with pytest.raises(ShipLogicTimeoutError) as caught:
        client(handler).quote(collection=address(), delivery=address(), parcels=[parcel()])
    assert TOKEN not in str(caught.value)


def test_authentication_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Unauthenticated"})

    with pytest.raises(ShipLogicAuthenticationError) as caught:
        client(handler).quote(collection=address(), delivery=address(), parcels=[parcel()])
    assert TOKEN not in str(caught.value)


def test_server_error_does_not_fabricate_a_rate() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "unavailable"})

    with pytest.raises(ShipLogicUnavailableError):
        client(handler).quote(collection=address(), delivery=address(), parcels=[parcel()])


def test_missing_token_and_other_hosts_are_refused() -> None:
    sandbox = ShipLogicSandboxClient(base_url=SANDBOX_BASE_URL, api_token="", timeout_seconds=5)
    with pytest.raises(ShipLogicConfigurationError):
        sandbox.quote(collection=address(), delivery=address(), parcels=[parcel()])
    with pytest.raises(ShipLogicConfigurationError):
        ShipLogicSandboxClient(base_url="https://sandbox.shiplogic.com", api_token=TOKEN, timeout_seconds=5)


def test_missing_collection_street_is_refused_before_the_request() -> None:
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json=_rates())

    collection = address()
    incomplete = SouthAfricanAddress(
        street_address=" ",
        local_area=collection.local_area,
        city=collection.city,
        zone=collection.zone,
        postal_code=collection.postal_code,
    )
    with pytest.raises(ShipLogicConfigurationError):
        client(handler).quote(collection=incomplete, delivery=address(), parcels=[parcel()])
    assert called is False


def test_settings_reject_live_mode_and_another_host() -> None:
    with pytest.raises(ValidationError):
        Settings(shiplogic_mode="live", shiplogic_api_token="")
    with pytest.raises(ValidationError):
        Settings(shiplogic_sandbox_base_url="https://api.example.test", shiplogic_api_token="")
