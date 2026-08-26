"""Yahoo Finance adapter via yfinance — FREE, no API key needed."""
import logging
from decimal import Decimal
from datetime import datetime, timezone as dt_timezone

logger = logging.getLogger(__name__)


def session_timestamp(idx, interval):
    """Bar timestamp in the platform's convention, which is UTC.

    yfinance localises a NON-INTRADAY index to the EXCHANGE timezone at
    local midnight (scrapers/history.py: `tz_localize(tz_exchange)` for
    every interval that is not minutes or hours). For any exchange east of
    UTC that midnight falls on the PREVIOUS UTC calendar day, so the raw
    index stops identifying the session it describes: ^N225's Monday
    session arrives as Sunday 15:00Z and ^GDAXI's as Sunday 22:00Z.

    What that costs, once the row is in PriceData: a day_of_week seasonal
    bucket reads the wrong weekday and trades Tuesday's edge as Monday's;
    two daily frames from different exchanges intersect on zero timestamps,
    so anything aligning them silently finds nothing; and an as-of replay
    bounded by `timestamp__lte=now` is handed a session that had not closed
    at the instant being replayed.

    Daily rows are therefore stamped at midnight UTC of the session's own
    calendar date — the same thing every other daily writer stores (the
    alpha_vantage adapter parses the date string under TIME_ZONE="UTC",
    and a Binance 1d kline already opens at 00:00Z). Intraday rows are real
    instants and are left exactly as they came.
    """
    if (interval or "").strip()[-1:] in ("m", "h"):
        return idx
    try:
        return datetime(idx.year, idx.month, idx.day, tzinfo=dt_timezone.utc)
    except (AttributeError, TypeError, ValueError):
        return idx


def _get_ticker(symbol):
    """Get yfinance Ticker object."""
    try:
        import yfinance as yf
        return yf.Ticker(symbol)
    except ImportError:
        logger.error("yfinance not installed: pip install yfinance")
        return None


def fetch_history(symbol, period="1mo", interval="1d"):
    """Fetch historical OHLCV data. Returns list of dicts."""
    ticker = _get_ticker(symbol)
    if not ticker:
        return []
    try:
        df = ticker.history(period=period, interval=interval)
        if df.empty:
            return []
        results = []
        for idx, row in df.iterrows():
            results.append({
                "date": idx.strftime("%Y-%m-%d") if hasattr(idx, "strftime") else str(idx),
                "timestamp": session_timestamp(idx, interval),
                "open": Decimal(str(round(row["Open"], 6))),
                "high": Decimal(str(round(row["High"], 6))),
                "low": Decimal(str(round(row["Low"], 6))),
                "close": Decimal(str(round(row["Close"], 6))),
                "volume": int(row.get("Volume", 0)),
            })
        return results
    except Exception as e:
        logger.error(f"yfinance history failed for {symbol}: {e}")
        return []


def fetch_quote(symbol):
    """Fetch current quote data."""
    ticker = _get_ticker(symbol)
    if not ticker:
        return None
    try:
        info = ticker.info
        return {
            "symbol": symbol,
            "last": Decimal(str(info.get("currentPrice", info.get("regularMarketPrice", 0)))),
            "open": Decimal(str(info.get("regularMarketOpen", 0))),
            "high": Decimal(str(info.get("dayHigh", 0))),
            "low": Decimal(str(info.get("dayLow", 0))),
            "volume": int(info.get("volume", 0)),
            "change_pct": Decimal(str(round(info.get("regularMarketChangePercent", 0), 4))),
            "market_cap": info.get("marketCap", 0),
            "pe_ratio": info.get("trailingPE"),
            "name": info.get("shortName", symbol),
        }
    except Exception as e:
        logger.error(f"yfinance quote failed for {symbol}: {e}")
        return None


def fetch_info(symbol):
    """Fetch instrument fundamentals."""
    ticker = _get_ticker(symbol)
    if not ticker:
        return None
    try:
        return ticker.info
    except Exception as e:
        logger.error(f"yfinance info failed for {symbol}: {e}")
        return None


def save_history_to_db(symbol, period="3mo", fetch_symbol=None):
    """Fetch history and save to PriceData.

    `fetch_symbol` is the Yahoo spelling when it differs from the platform
    one (CORNUSD -> ZC=F, SPX500 -> ^GSPC) — without it, only identity-
    mapped classes (stocks, ETFs) could ever get daily bars.
    """
    from instruments.models import Instrument
    from market_data.models import PriceData

    history = fetch_history(fetch_symbol or symbol, period=period, interval="1d")
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
            timestamp=bar["timestamp"],
            defaults={
                "open": bar["open"],
                "high": bar["high"],
                "low": bar["low"],
                "close": bar["close"],
                "volume": bar["volume"],
                "source": "yfinance",
            }
        )
        if was_created:
            created += 1
    return created


def save_quote_to_db(symbol):
    """Fetch quote and save to LiveQuote."""
    from instruments.models import Instrument
    from market_data.models import LiveQuote

    quote = fetch_quote(symbol)
    if not quote or quote["last"] == 0:
        return None

    try:
        instrument = Instrument.objects.get(symbol=symbol)
    except Instrument.DoesNotExist:
        return None

    # yfinance is ~15 minutes delayed for most US listings, so it must not
    # overwrite a live stream (Finnhub/IBKR/Alpaca) that wrote recently.
    from market_data.quotes import write_quote
    if not write_quote(symbol, last=quote["last"], source="yfinance",
                        change_pct=quote["change_pct"],
                        volume=quote["volume"], instrument=instrument):
        return None
    return LiveQuote.objects.filter(instrument=instrument).first()
