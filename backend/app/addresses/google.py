"""Google Places address search. The API key stays on the server."""

from dataclasses import dataclass

import httpx

from app.shipping.simulated import PROVINCES

PLACES_AUTOCOMPLETE = "https://places.googleapis.com/v1/places:autocomplete"
PLACES_DETAILS = "https://places.googleapis.com/v1/places/"
_PROVINCE_CODES = {
    "EC": "Eastern Cape",
    "FS": "Free State",
    "GP": "Gauteng",
    "KZN": "KwaZulu-Natal",
    "LP": "Limpopo",
    "MP": "Mpumalanga",
    "NC": "Northern Cape",
    "NW": "North West",
    "WC": "Western Cape",
}
_PROVINCE_NAMES = {name.casefold(): name for name in PROVINCES}


class AddressLookupError(Exception):
    """The address provider did not return a usable result."""


@dataclass(frozen=True)
class AddressSuggestion:
    place_id: str
    label: str


@dataclass(frozen=True)
class AddressSelection:
    line1: str
    line2: str
    suburb: str
    city: str
    province: str
    postal_code: str
    country: str


class GooglePlacesProvider:
    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client

    def suggest(self, query: str) -> list[AddressSuggestion]:
        payload = {"input": query, "includedRegionCodes": ["za"], "languageCode": "en"}
        body = self._post(PLACES_AUTOCOMPLETE, payload)
        suggestions: list[AddressSuggestion] = []
        for item in body.get("suggestions") or []:
            prediction = item.get("placePrediction") or {}
            place_id = str(prediction.get("placeId") or "").strip()
            text = prediction.get("text") or {}
            label = str(text.get("text") or "").strip()
            if place_id and label:
                suggestions.append(AddressSuggestion(place_id=place_id, label=label))
        return suggestions[:8]

    def select(self, place_id: str) -> AddressSelection:
        cleaned = place_id.strip()
        if not cleaned or len(cleaned) > 300 or "/" in cleaned:
            raise AddressLookupError("That address suggestion is not valid.")
        body = self._get(
            PLACES_DETAILS + cleaned,
            headers={"X-Goog-FieldMask": "addressComponents"},
        )
        components = _index_components(body.get("addressComponents") or [])
        country = components.get("country", "")
        if country.upper() not in {"ZA", "SOUTH AFRICA"}:
            raise AddressLookupError("Delivery is limited to South Africa.")
        street_number = components.get("street_number", "")
        route = components.get("route", "")
        line1 = " ".join(part for part in (street_number, route) if part).strip()
        postal = components.get("postal_code", "")
        if postal and (len(postal) != 4 or not postal.isdigit()):
            postal = ""
        return AddressSelection(
            line1=line1,
            line2=components.get("subpremise", ""),
            suburb=components.get("sublocality_level_1") or components.get("sublocality") or components.get("neighborhood") or "",
            city=components.get("locality") or components.get("postal_town") or "",
            province=_province(components.get("administrative_area_level_1", "")),
            postal_code=postal,
            country="ZA",
        )

    def _post(self, url: str, payload: dict) -> dict:
        return self._request("POST", url, json=payload)

    def _get(self, url: str, headers: dict) -> dict:
        return self._request("GET", url, extra_headers=headers)

    def _request(self, method: str, url: str, json: dict | None = None, extra_headers: dict | None = None) -> dict:
        headers = {"X-Goog-Api-Key": self._api_key, "Content-Type": "application/json"}
        if extra_headers:
            headers.update(extra_headers)
        client = self._client or httpx.Client(timeout=8)
        close = self._client is None
        try:
            response = client.request(method, url, headers=headers, json=json)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AddressLookupError("Address search is unavailable.") from exc
        finally:
            if close:
                client.close()
        if not isinstance(body, dict):
            raise AddressLookupError("Address search is unavailable.")
        return body


def _index_components(components: list) -> dict[str, str]:
    indexed: dict[str, str] = {}
    for component in components:
        if not isinstance(component, dict):
            continue
        text = str(component.get("longText") or component.get("shortText") or "").strip()
        types = component.get("types") or []
        for kind in types:
            if kind and text and kind not in indexed:
                indexed[str(kind)] = text
        if "country" in types:
            short = str(component.get("shortText") or "").strip()
            if short:
                indexed["country"] = short
        if "administrative_area_level_1" in types:
            short = str(component.get("shortText") or text).strip()
            if short:
                indexed["administrative_area_level_1"] = short
    return indexed


def _province(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        return ""
    mapped = _PROVINCE_CODES.get(cleaned.upper()) or _PROVINCE_NAMES.get(cleaned.casefold())
    return mapped or ""
