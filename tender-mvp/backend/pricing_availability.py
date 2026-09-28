"""Shared NULL/zero and evidence rules for every pricing surface."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any


AVAILABLE = "available"
NOT_AVAILABLE = "not_available"
AUTHORIZED_ZERO = "authorized_zero"
NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class PriceAvailability:
    value: Decimal | None
    status: str
    available: bool
    reason: str | None = None


def classify_price(
    value: Any,
    *,
    source_reference: str | None,
    approval_status: str | None = None,
    approved_by: str | None = None,
    zero_price_authorized: bool = False,
) -> PriceAvailability:
    """Return availability without ever coercing a missing value to zero."""
    if value is None or value == "":
        return PriceAvailability(None, NOT_AVAILABLE, False, "Price is not available")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return PriceAvailability(None, NOT_AVAILABLE, False, "Price is invalid")
    if number < 0:
        return PriceAvailability(None, NOT_AVAILABLE, False, "Negative prices are unsupported")
    if not str(source_reference or "").strip():
        return PriceAvailability(None, NOT_AVAILABLE, False, "Authoritative price source is missing")
    if number == 0:
        authorized = zero_price_authorized and approval_status == "approved" and bool(str(approved_by or "").strip())
        if not authorized:
            return PriceAvailability(None, NOT_AVAILABLE, False, "Zero price lacks an authorized decision")
        return PriceAvailability(number, AUTHORIZED_ZERO, True)
    return PriceAvailability(number, AVAILABLE, True)


def display_price(value: Any, available: bool) -> str:
    return "Not available" if not available or value is None else str(value)


def display_price_state(value: Any, status: str) -> str:
    """Human label that keeps structural NULL distinct from missing-price NULL."""
    if status == NOT_APPLICABLE:
        return "Not applicable"
    return display_price(value, status in {AVAILABLE, AUTHORIZED_ZERO})


def price_freshness(
    effective_date: str | None,
    expiry_date: str | None,
    *,
    available: bool,
    today: date | None = None,
) -> str:
    """Describe date freshness independently from numeric availability."""
    if not available:
        return "not_available"
    today = today or date.today()
    try:
        effective = date.fromisoformat(effective_date) if effective_date else None
        expiry = date.fromisoformat(expiry_date) if expiry_date else None
    except ValueError:
        return "invalid_date"
    if effective and effective > today:
        return "not_yet_effective"
    if expiry and expiry < today:
        return "expired"
    return "current" if effective else "effective_date_not_available"
