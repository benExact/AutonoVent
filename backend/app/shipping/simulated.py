"""Test delivery quotes. These amounts are configuration, not ShipLogic prices."""

from dataclasses import dataclass

PROVINCES = (
    "Eastern Cape",
    "Free State",
    "Gauteng",
    "KwaZulu-Natal",
    "Limpopo",
    "Mpumalanga",
    "Northern Cape",
    "North West",
    "Western Cape",
)
_PROVINCE_LOOKUP = {name.casefold(): name for name in PROVINCES}
SIMULATED_PROVIDER = "simulated-courier"
SIMULATED_LABEL = "Simulated delivery. This is not a ShipLogic price."


class SimulatedConfigurationError(Exception):
    """The test delivery configuration cannot be used."""


@dataclass(frozen=True)
class SimulatedRate:
    service_code: str
    service_name: str
    shipping_cents: int
    quote_reference: str
    provider: str = SIMULATED_PROVIDER
    label: str = SIMULATED_LABEL


def canonical_province(value: str) -> str:
    found = _PROVINCE_LOOKUP.get(value.strip().casefold())
    if found is None:
        raise SimulatedConfigurationError("Delivery is limited to a South African province.")
    return found


def parse_simulation_rates(value: str) -> list[tuple[str, int]]:
    return _parse_pairs(value, label="rate")


def parse_region_extras(value: str) -> dict[str, int]:
    extras: dict[str, int] = {}
    for code, cents in _parse_pairs(value, label="region extra"):
        province = _PROVINCE_LOOKUP.get(code.casefold())
        if province is None:
            raise SimulatedConfigurationError("A simulated region extra must use a South African province name.")
        if province in extras:
            raise SimulatedConfigurationError("A simulated region extra is repeated.")
        extras[province] = cents
    return extras


class SimulatedCourier:
    """Returns configured test rates. It does not call a courier API or use parcel dimensions."""

    def __init__(self, *, rates: str, region_extras: str) -> None:
        parsed = parse_simulation_rates(rates)
        if not parsed:
            raise SimulatedConfigurationError("Simulated delivery rates are not configured.")
        self._rates = parsed
        self._extras = parse_region_extras(region_extras)

    def quote(self, *, region: str) -> list[SimulatedRate]:
        province = canonical_province(region)
        extra = self._extras.get(province, 0)
        quoted: list[SimulatedRate] = []
        for code, cents in self._rates:
            shipping_cents = cents + extra
            quoted.append(
                SimulatedRate(
                    service_code=code,
                    service_name=f"Simulated {code.replace('-', ' ')} delivery",
                    shipping_cents=shipping_cents,
                    quote_reference=f"sim-{code}-{shipping_cents}",
                )
            )
        return quoted


def _parse_pairs(value: str, *, label: str) -> list[tuple[str, int]]:
    text = value.strip()
    if not text:
        return []
    pairs: list[tuple[str, int]] = []
    seen: set[str] = set()
    for part in text.split(","):
        item = part.strip()
        if ":" not in item:
            raise SimulatedConfigurationError(f"A simulated {label} must use code:cents.")
        code, raw_cents = item.split(":", 1)
        cleaned = code.strip()
        if not cleaned or len(cleaned) > 32:
            raise SimulatedConfigurationError(f"A simulated {label} code is not valid.")
        if cleaned.casefold() in seen:
            raise SimulatedConfigurationError(f"A simulated {label} is repeated.")
        try:
            cents = int(raw_cents.strip())
        except ValueError as exc:
            raise SimulatedConfigurationError(f"A simulated {label} amount must be whole cents.") from None
        if cents < 0 or cents > 10_000_000:
            raise SimulatedConfigurationError(f"A simulated {label} amount is out of range.")
        seen.add(cleaned.casefold())
        pairs.append((cleaned, cents))
    return pairs
