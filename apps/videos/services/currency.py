"""USD -> PKR conversion and formatting for display.

Costs are computed and stored in USD (providers bill in USD); the UI shows PKR.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings


def rate():
    return Decimal(str(settings.USD_TO_PKR))


def usd_to_pkr(usd):
    if usd in (None, ""):
        usd = 0
    return (Decimal(str(usd)) * rate()).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def pkr_to_usd(pkr):
    """The other direction, for amounts a person typed in.

    Budgets are entered in PKR because that is what the UI shows, but every stored
    cost is USD, so the conversion has to happen at the edge rather than leaving two
    currencies in the database.
    """
    if pkr in (None, ""):
        pkr = 0
    return (Decimal(str(pkr)) / rate()).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )


def format_usd_as_pkr(usd):
    """e.g. 0.55 USD -> 'Rs 154.00' (at rate 280)."""
    return "Rs " + f"{usd_to_pkr(usd):,.2f}"
