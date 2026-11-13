"""Reusable validation for numeric values accepted by services."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def whole_number(value: Any, label: str, minimum: int = 0) -> int:
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label} must be a whole number.") from None
    if not numeric.is_finite() or numeric != numeric.to_integral_value() or numeric < minimum:
        requirement = "a positive whole number" if minimum == 1 else "a non-negative whole number"
        raise ValueError(f"{label} must be {requirement}.")
    return int(numeric)


def nonnegative_money(value: Any, label: str = "Cost") -> Decimal:
    try:
        numeric = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{label} must be a valid amount.") from None
    if not numeric.is_finite() or numeric < 0:
        raise ValueError(f"{label} must be a finite, non-negative amount.")
    return numeric
