"""Public address suggestions. The provider key is not returned."""

from fastapi import APIRouter, HTTPException, Query

from app.addresses.google import AddressLookupError, GooglePlacesProvider
from app.core.config import get_settings
from pydantic import ValidationError

router = APIRouter()
UNAVAILABLE = "Address search is unavailable. Enter the address manually."


def _provider():
    try:
        settings = get_settings()
    except ValidationError:
        return None
    if settings.address_provider != "google":
        return None
    return GooglePlacesProvider(settings.google_places_api_key)


@router.get("/addresses/suggestions")
def address_suggestions(q: str = Query(default="", max_length=120)) -> dict:
    query = q.strip()
    provider = _provider()
    if provider is None:
        return {
            "enabled": False,
            "suggestions": [],
            "detail": "Address search is not configured. Enter the address manually.",
        }
    if len(query) < 3:
        return {"enabled": True, "suggestions": []}
    try:
        suggestions = provider.suggest(query)
    except AddressLookupError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE) from None
    return {
        "enabled": True,
        "suggestions": [{"id": item.place_id, "label": item.label} for item in suggestions],
    }


@router.get("/addresses/selection")
def address_selection(id: str = Query(default="", max_length=300)) -> dict:
    place_id = id
    provider = _provider()
    if provider is None:
        raise HTTPException(status_code=404, detail="Address search is not configured.")
    try:
        selected = provider.select(place_id)
    except AddressLookupError as exc:
        message = str(exc)
        status = 422 if "South Africa" in message or "not valid" in message else 503
        detail = message if status == 422 else UNAVAILABLE
        raise HTTPException(status_code=status, detail=detail) from None
    return {
        "line1": selected.line1,
        "line2": selected.line2,
        "local_area": selected.suburb,
        "city": selected.city,
        "region": selected.province,
        "postal_code": selected.postal_code,
        "country": selected.country,
    }
