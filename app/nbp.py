"""Client for the National Bank of Poland (NBP) exchange-rate API.

Docs: https://api.nbp.pl/en.html
NBP publishes rates only on working days, so for weekends and holidays
we look back over the previous days and take the latest published rate.
"""

import os
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import httpx

NBP_API_URL = os.getenv("NBP_API_URL", "https://api.nbp.pl/api")
TIMEOUT_SECONDS = 5.0
LOOKBACK_DAYS = 10


@dataclass(frozen=True)
class Rate:
    currency: str
    rate: Decimal      # how many PLN for 1 unit of the currency
    rate_date: date    # the day NBP published this rate


class CurrencyNotSupported(Exception):
    """NBP doesn't know this currency."""


class ExchangeRateUnavailable(Exception):
    """We couldn't get through to NBP."""


class NBPClient:
    def __init__(self, base_url: str = NBP_API_URL, timeout: float = TIMEOUT_SECONDS):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_rate(self, currency: str, on: date | None = None) -> Rate:
        currency = currency.upper()
        on = on or date.today()

        # PLN to PLN is always 1, no need to call anyone.
        if currency == "PLN":
            return Rate("PLN", Decimal("1"), on)

        start = on - timedelta(days=LOOKBACK_DAYS)
        url = f"{self.base_url}/exchangerates/rates/a/{currency.lower()}/{start}/{on}/"

        try:
            response = httpx.get(url, params={"format": "json"}, timeout=self.timeout)
        except httpx.HTTPError as exc:
            raise ExchangeRateUnavailable(f"Could not reach NBP API: {exc}") from exc

        if response.status_code == 404:
            raise CurrencyNotSupported(
                f"No NBP rate for {currency} between {start} and {on}"
            )
        if response.status_code != 200:
            raise ExchangeRateUnavailable(f"NBP API returned HTTP {response.status_code}")

        rates = response.json().get("rates", [])
        if not rates:
            raise CurrencyNotSupported(f"No NBP rate for {currency}")

        latest = rates[-1]
        return Rate(
            currency=currency,
            rate=Decimal(str(latest["mid"])),
            rate_date=date.fromisoformat(latest["effectiveDate"]),
        )


def get_nbp_client() -> NBPClient:
    """FastAPI dependency. In tests we'll swap it for a fake."""
    return NBPClient()