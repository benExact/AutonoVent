"""Rand amounts become integer cents without binary floating point."""

import re
from decimal import Decimal, InvalidOperation

_RANDS = re.compile(r"^[0-9]+(?:[.,][0-9]{1,2})?$")
_MAX_CENTS = 2_147_483_647


def rands_to_cents(value: str) -> int:
    text = value.strip()
    if not _RANDS.fullmatch(text):
        raise ValueError("Enter the selling price in rands, using up to two decimal places.")
    try:
        amount = Decimal(text.replace(",", "."))
    except InvalidOperation:
        raise ValueError("Enter the selling price in rands, using up to two decimal places.") from None
    if amount <= 0:
        raise ValueError("Enter a selling price greater than R0.00.")
    cents = int(amount * 100)
    if cents < 1 or cents > _MAX_CENTS:
        raise ValueError("Enter a selling price greater than R0.00.")
    return cents
