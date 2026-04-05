"""Alpha Vantage API adapter — REAL implementation."""
import os
import requests
import logging
from decimal import Decimal
from django.utils import timezone
from core.rate_limiter import rate_limiter

logger = logging.getLogger(__name__)

API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY", "")
BASE_URL = "https://www.alphavantage.co/query"
CALLS_PER_MINUTE = 5


def _request(params):
    """Make a rate-limited request to Alpha Vantage."""
    rate_limiter.wait_if_needed("alpha_vantage", CALLS_PER_MINUTE)
    params["apikey"] = API_KEY
    try:
        resp = requests.get(BASE_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        if "Error Message" in data or "Note" in data:
            logger.warning(f"Alpha Vantage: {data.get('Error Message', data.get('Note', ''))}")
            return None
        return data
    except Exception as e:
        logger.error(f"Alpha Vantage request failed: {e}")
        return None


def fetch_quote(symbol):
    """Fetch real-time quote for a symbol. Returns dict or None."""
    if not API_KEY:
        return None
    data = _request({"function": "GLOBAL_QUOTE", "symbol": symbol})
    if not data or "Global Quote" not in data:
        return None
    q = data["Global Quote"]
    return {
        "symbol": q.get("01. symbol", symbol),
        "last": Decimal(q.get("05. price", "0")),
        "open": Decimal(q.get("02. open", "0")),
        "high": Decimal(q.get("03. high", "0")),
        "low": Decimal(q.get("04. low", "0")),
        "volume": int(q.get("06. volume", "0")),
        "change_pct": Decimal(q.get("10. change percent", "0%").replace("%", "")),
        "previous_close": Decimal(q.get("08. previous close", "0")),
    }


def fetch_daily_history(symbol, outputsize="compact"):
    """Fetch daily OHLCV history. Returns list of dicts."""
    if not API_KEY:
        return []
    data = _request({
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "outputsize": outputsize,
    })
    if not data or "Time Series (Daily)" not in data:
        return []

    results = []
    for date_str, values in data["Time Series (Daily)"].items():
        results.append({
            "date": date_str,
            "open": Decimal(values["1. open"]),
            "high": Decimal(values["2. high"]),
            "low": Decimal(values["3. low"]),
            "close": Decimal(values["4. close"]),
            "volume": int(values["5. volume"]),
        })
    return sorted(results, key=lambda x: x["date"])


def fetch_forex_rate(from_currency, to_currency):
    """Fetch a forex exchange rate."""
    if not API_KEY:
        return None
    data = _request({
        "function": "CURRENCY_EXCHANGE_RATE",
        "from_currency": from_currency,
        "to_currency": to_currency,
    })
    if not data or "Realtime Currency Exchange Rate" not in data:
        return None
    r = data["Realtime Currency Exchange Rate"]
    return {
        "from": r.get("1. From_Currency Code"),
        "to": r.get("3. To_Currency Code"),
        "rate": Decimal(r.get("5. Exchange Rate", "0")),
        "bid": Decimal(r.get("8. Bid Price", "0")),
        "ask": Decimal(r.get("9. Ask Price", "0")),
    }


def fetch_commodity_price(symbol):
    """Fetch commodity monthly data (WTI, Brent, Natural Gas, Copper, etc.)."""
    if not API_KEY:
        return None
    func_map = {
        "WTI": "WTI", "BRENT": "BRENT",
        "NATURAL_GAS": "NATURAL_GAS", "COPPER": "COPPER",
        "ALUMINUM": "ALUMINUM", "WHEAT": "WHEAT",
        "CORN": "CORN", "COTTON": "COTTON",
        "SUGAR": "SUGAR", "COFFEE": "COFFEE",
    }
    av_symbol = func_map.get(symbol.upper().replace("USD", ""), symbol)
    data = _request({"function": av_symbol, "interval": "daily"})
    if not data or "data" not in data:
        return None
    latest = data["data"][0] if data["data"] else None
    if latest:
        return {"date": latest["date"], "value": Decimal(latest["value"])}
    return None


def save_quote_to_db(symbol):
    """Fetch a quote and save it to LiveQuote model."""
    from instruments.models import Instrument
    from market_data.models import LiveQuote

    quote = fetch_quote(symbol)
    if not quote:
        return None

    try:
        instrument = Instrument.objects.get(symbol=symbol)
    except Instrument.DoesNotExist:
        return None

    obj, _ = LiveQuote.objects.update_or_create(
        instrument=instrument,
        defaults={
            "last": quote["last"],
            "bid": quote.get("last"),  # AV doesn't give bid/ask for stocks
            "ask": quote.get("last"),
            "change_pct": quote["change_pct"],
            "volume": quote["volume"],
            "source": "alpha_vantage",
        }
    )
    return obj


def save_history_to_db(symbol, outputsize="compact"):
    """Fetch daily history and save to PriceData model."""
    from instruments.models import Instrument
    from market_data.models import PriceData
    from datetime import datetime

    history = fetch_daily_history(symbol, outputsize)
    if not history:
        return 0

    try:
        instrument = Instrument.objects.get(symbol=symbol)
    except Instrument.DoesNotExist:
        return 0

    created = 0
    for bar in history:
        _, was_created = PriceData.objects.get_or_create(
            instrument=instrument,
            timeframe="1d",
            timestamp=datetime.strptime(bar["date"], "%Y-%m-%d"),
            defaults={
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar["volume"],
                "source": "alpha_vantage",
            }
        )
        if was_created:
            created += 1
    return created
