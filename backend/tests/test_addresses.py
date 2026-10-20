"""Address search. Tests use a stand-in provider and do not call Google."""

import os
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.addresses.google import AddressLookupError, AddressSuggestion, GooglePlacesProvider
from app.core.config import get_settings
from app.main import app

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[2]


class StandInProvider:
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def suggest(self, query: str) -> list[AddressSuggestion]:
        if query == "fail":
            raise AddressLookupError("Address search is unavailable.")
        if query == "none":
            return []
        return [AddressSuggestion(place_id="place-1", label="1 Long Street, Pretoria")]

    def select(self, place_id: str):
        from app.addresses.google import AddressSelection

        if place_id == "abroad":
            raise AddressLookupError("Delivery is limited to South Africa.")
        if place_id == "partial":
            return AddressSelection(
                line1="1 Long Street",
                line2="",
                suburb="Arcadia",
                city="",
                province="Gauteng",
                postal_code="0002",
                country="ZA",
            )
        return AddressSelection(
            line1="1 Long Street",
            line2="Unit 2",
            suburb="Arcadia",
            city="Pretoria",
            province="Gauteng",
            postal_code="0002",
            country="ZA",
        )


def _enable(monkeypatch) -> None:
    monkeypatch.setenv("ADDRESS_PROVIDER", "google")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "test-key-not-real")
    monkeypatch.setattr("app.api.v1.addresses.GooglePlacesProvider", StandInProvider)
    get_settings.cache_clear()


def test_suggestions_are_returned_for_a_search(monkeypatch) -> None:
    _enable(monkeypatch)
    response = client.get("/api/v1/addresses/suggestions", params={"q": "Long"})
    assert response.status_code == 200
    body = response.json()
    assert body["enabled"] is True
    assert body["suggestions"] == [{"id": "place-1", "label": "1 Long Street, Pretoria"}]
    assert "test-key" not in response.text


def test_selecting_a_result_returns_only_supplied_components(monkeypatch) -> None:
    _enable(monkeypatch)
    full = client.get("/api/v1/addresses/selection", params={"id": "place-1"})
    assert full.status_code == 200
    assert full.json()["line1"] == "1 Long Street"
    assert full.json()["line2"] == "Unit 2"
    assert full.json()["local_area"] == "Arcadia"
    assert full.json()["city"] == "Pretoria"
    assert full.json()["region"] == "Gauteng"
    assert full.json()["postal_code"] == "0002"
    assert full.json()["country"] == "ZA"
    partial = client.get("/api/v1/addresses/selection", params={"id": "partial"})
    assert partial.status_code == 200
    assert partial.json()["line2"] == ""
    assert partial.json()["city"] == ""
    assert partial.json()["line1"] == "1 Long Street"


def test_empty_results_and_provider_failure_do_not_invent_addresses(monkeypatch) -> None:
    _enable(monkeypatch)
    empty = client.get("/api/v1/addresses/suggestions", params={"q": "none"})
    assert empty.status_code == 200
    assert empty.json()["suggestions"] == []
    failed = client.get("/api/v1/addresses/suggestions", params={"q": "fail"})
    assert failed.status_code == 503
    assert "Long Street" not in failed.text
    assert "unavailable" in failed.json()["detail"]


def test_address_search_stays_manual_when_it_is_not_configured(monkeypatch) -> None:
    monkeypatch.setenv("ADDRESS_PROVIDER", "")
    monkeypatch.setenv("GOOGLE_PLACES_API_KEY", "")

    def refuse(*args, **kwargs):
        raise AssertionError("Google was called")

    monkeypatch.setattr("app.addresses.google.httpx.Client", refuse)
    get_settings.cache_clear()
    response = client.get("/api/v1/addresses/suggestions", params={"q": "Pretoria"})
    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["suggestions"] == []
    assert "manually" in response.json()["detail"]


def test_non_south_african_place_is_rejected(monkeypatch) -> None:
    _enable(monkeypatch)
    response = client.get("/api/v1/addresses/selection", params={"id": "abroad"})
    assert response.status_code == 422
    assert "South Africa" in response.json()["detail"]


def test_google_parser_uses_returned_components_only() -> None:
    payload = {
        "addressComponents": [
            {"longText": "12", "shortText": "12", "types": ["street_number"]},
            {"longText": "Long Street", "shortText": "Long Street", "types": ["route"]},
            {"longText": "Arcadia", "shortText": "Arcadia", "types": ["sublocality_level_1"]},
            {"longText": "Pretoria", "shortText": "Pretoria", "types": ["locality"]},
            {"longText": "Gauteng", "shortText": "GP", "types": ["administrative_area_level_1"]},
            {"longText": "0002", "shortText": "0002", "types": ["postal_code"]},
            {"longText": "South Africa", "shortText": "ZA", "types": ["country"]},
        ]
    }

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return payload

    class Client:
        def request(self, method: str, url: str, headers: dict | None = None, json: dict | None = None) -> Response:
            assert headers is not None
            assert "test-key" == headers.get("X-Goog-Api-Key")
            return Response()

        def close(self) -> None:
            return None

    selected = GooglePlacesProvider("test-key", client=Client()).select("place-1")
    assert selected.line1 == "12 Long Street"
    assert selected.line2 == ""
    assert selected.suburb == "Arcadia"
    assert selected.city == "Pretoria"
    assert selected.province == "Gauteng"
    assert selected.postal_code == "0002"
    assert selected.country == "ZA"


def test_google_parser_rejects_a_failed_request() -> None:
    class Client:
        def request(self, method: str, url: str, headers: dict | None = None, json: dict | None = None):
            raise httpx.ConnectError("down")

        def close(self) -> None:
            return None

    with pytest.raises(AddressLookupError):
        GooglePlacesProvider("test-key", client=Client()).suggest("Pretoria")


def test_stale_search_results_and_manual_fields() -> None:
    script = r"""
const search = require(process.env.ADDRESS_SEARCH_FILE);
const state = search.createSearchState();
const first = search.nextGeneration(state);
const second = search.nextGeneration(state);
if (search.isCurrentGeneration(state, first)) process.exit(2);
if (!search.isCurrentGeneration(state, second)) process.exit(3);
const applied = search.applyAddress(
  {line1:"", line2:"Unit 4", local_area:"", city:"Pretoria", region:"", postal_code:"", country:""},
  {line1:"1 Long Street", line2:"", local_area:"Arcadia", city:"", region:"Gauteng", postal_code:"0002", country:"ZA"}
);
if (applied.fields.line1 !== "1 Long Street") process.exit(4);
if (applied.fields.line2 !== "Unit 4") process.exit(5);
if (applied.fields.city !== "Pretoria") process.exit(6);
if (applied.fields.local_area !== "Arcadia") process.exit(7);
const empty = search.applyAddress(
  {line1:"", line2:"", local_area:"", city:"", region:"", postal_code:"", country:""},
  {line1:"", line2:"", local_area:"", city:"", region:"", postal_code:"", country:""}
);
if (!empty.missing.includes("line1") || !empty.missing.includes("city")) process.exit(8);
search.rememberSelection(state, "place-1", "1 Long Street");
if (!search.selectionStillMatches(state, "1 Long Street")) process.exit(9);
if (search.selectionStillMatches(state, "2 Other Street")) process.exit(10);
"""
    env = os.environ.copy()
    env["ADDRESS_SEARCH_FILE"] = str(ROOT / "js" / "address-search.js")
    completed = subprocess.run(
        ["node", "-e", script],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr + completed.stdout
    source = (ROOT / "js" / "address-search.js").read_text(encoding="utf-8")
    assert "isCurrentGeneration" in source
    assert "Enter the address manually" in source
    checkout = (ROOT / "checkout.html").read_text(encoding="utf-8")
    assert 'name="line1"' in checkout
    assert 'name="line2"' in checkout
