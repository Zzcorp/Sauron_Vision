"""forex-python adapter — free ECB / exchangerate-api rates.

Primary:  forex_python library (ECB data, no API key required)
Fallback: exchangerate-api.com free tier (no API key required)
"""
import logging
import requests

logger = logging.getLogger(__name__)

# Attempt to import forex_python once at module load so we know which path to take.
try:
    from forex_python.converter import CurrencyRates as _CurrencyRates
    _FOREX_PYTHON_AVAILABLE = True
except ImportError:
    _FOREX_PYTHON_AVAILABLE = False
    logger.info(
        "forex_python library not installed — will use exchangerate-api.com as fallback"
    )

_FALLBACK_BASE_URL = "https://api.exchangerate-api.com/v4/latest"


def fetch_rate(from_currency: str, to_currency: str) -> float:
    """Fetch current exchange rate from from_currency to to_currency.

    Returns the rate as a float, or 0.0 on failure.
    """
    from_currency = from_currency.upper()
    to_currency = to_currency.upper()

    if _FOREX_PYTHON_AVAILABLE:
        try:
            c = _CurrencyRates()
            rate = c.get_rate(from_currency, to_currency)
            return float(rate)
        except Exception as exc:  # forex_python raises various undocumented exceptions
            logger.warning(
                "forex_python failed for %s->%s (%s), falling back to exchangerate-api",
                from_currency, to_currency, exc,
            )

    # Fallback: exchangerate-api.com
    return _fetch_rate_fallback(from_currency, to_currency)


def fetch_rates_bulk(base: str = "USD", targets: list = None) -> dict:
    """Fetch exchange rates for multiple target currencies against a base.

    Args:
        base:    The base currency (default "USD").
        targets: Optional list of target currency codes to filter results.
                 If None, all available rates are returned.

    Returns a dict of {currency_code: rate}, or an empty dict on failure.
    """
    base = base.upper()

    if _FOREX_PYTHON_AVAILABLE:
        try:
            c = _CurrencyRates()
            all_rates = c.get_rates(base)
            if targets:
                targets_upper = [t.upper() for t in targets]
                return {k: v for k, v in all_rates.items() if k in targets_upper}
            return dict(all_rates)
        except Exception as exc:
            logger.warning(
                "forex_python bulk fetch failed for base=%s (%s), falling back to exchangerate-api",
                base, exc,
            )

    # Fallback: exchangerate-api.com
    return _fetch_rates_bulk_fallback(base, targets)


# ---------------------------------------------------------------------------
# Internal fallback helpers
# ---------------------------------------------------------------------------

def _fetch_rate_fallback(from_currency: str, to_currency: str) -> float:
    """Single-pair rate via exchangerate-api.com free endpoint."""
    rates = _fetch_rates_bulk_fallback(from_currency, [to_currency])
    rate = rates.get(to_currency, 0.0)
    if rate == 0.0:
        logger.error(
            "exchangerate-api fallback: no rate found for %s->%s", from_currency, to_currency
        )
    return rate


def _fetch_rates_bulk_fallback(base: str, targets: list = None) -> dict:
    """All (or filtered) rates for base currency via exchangerate-api.com."""
    url = f"{_FALLBACK_BASE_URL}/{base.upper()}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        all_rates = data.get("rates", {})

        if targets:
            targets_upper = [t.upper() for t in targets]
            return {k: v for k, v in all_rates.items() if k in targets_upper}

        return all_rates

    except requests.exceptions.HTTPError as exc:
        logger.error("exchangerate-api HTTP error for base=%s: %s", base, exc)
    except requests.exceptions.RequestException as exc:
        logger.error("exchangerate-api request error for base=%s: %s", base, exc)
    except (ValueError, KeyError) as exc:
        logger.error("exchangerate-api JSON parse error for base=%s: %s", base, exc)

    return {}
