"""The quotation maths, kept in one small file so it is easy to read and to check.

Per line:  line total = unit price x quantity, less the line's discount percentage.
Whole quote:  subtotal = sum of line totals (excluding VAT)
              VAT      = subtotal x VAT rate (15%)
              total    = subtotal + VAT
Every money amount is rounded to the cent, half-up, using Decimal (never floats).
"""
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from app import config

CENT = Decimal("0.01")


def money(amount: Decimal) -> Decimal:
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def line_total(unit_price: Decimal | None, quantity: int, discount_percent: Decimal | None) -> Decimal | None:
    """None until the line has a price."""
    if unit_price is None:
        return None
    discount = Decimal(discount_percent or 0)
    return money(unit_price * quantity * (Decimal(100) - discount) / Decimal(100))


def quote_totals(line_totals: list[Decimal | None], vat_rate: Decimal) -> dict[str, Decimal] | None:
    """Subtotal, VAT and total, or None while any line is still unpriced."""
    if not line_totals or any(total is None for total in line_totals):
        return None
    subtotal = sum(line_totals, Decimal("0"))
    vat = money(subtotal * vat_rate)
    return {"subtotal": subtotal, "vat": vat, "total": subtotal + vat}


def today_in_south_africa() -> date:
    return datetime.now(ZoneInfo(config.BUSINESS_TIMEZONE)).date()
