"""One writer for LiveQuote, with source precedence and symbol mapping.

Two silent data defects this exists to stop:

1. LAST WRITER WINS. `LiveQuote` is one row per instrument with a single
   `source` column, and several pollers/streamers write the same row with
   no precedence. A 60-second yfinance poll (15-minute delayed) would
   happily overwrite a live Finnhub tick, so the "live" price was whichever
   feed happened to run last. Now a lower-quality source cannot clobber a
   recent higher-quality one.

2. EXCHANGE SYMBOLS NEVER MATCHED INSTRUMENTS. The Binance streamer
   normalises to `BTCUSDT` while the Instrument row is `BTCUSD`, so the
   lookup missed and every tick from the best crypto feed was dropped on
   the floor. Resolution now tries the exchange symbol and its instrument
   equivalent.
"""
from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation

from django.utils import timezone

logger = logging.getLogger(__name__)

# Higher wins. A source may always overwrite itself.
SOURCE_PRIORITY = {
    "binance_ws": 100,     # real-time exchange stream
    "oanda_stream": 100,
    "finnhub_ws": 90,
    "ibkr": 80,
    "alpaca": 70,
    "oanda": 70,           # broker REST
    "binance": 70,
    "coingecko": 40,
    "alpha_vantage": 30,
    "twelve_data": 30,
    "fmp": 30,
    "yfinance": 20,        # 15-minute delayed for most US listings
}
DEFAULT_PRIORITY = 50

# A better source only "holds" the row for this long; after that anything
# may write, so one dead premium stream can't freeze the price forever.
PRIORITY_HOLD_SECONDS = 300

# Common quote-currency aliases between venues and our instrument symbols.
_STABLE_SUFFIXES = ("USDT", "BUSD", "USDC")


def instrument_symbol_candidates(symbol: str) -> list[str]:
    """Symbols to try when resolving an exchange symbol to an Instrument."""
    s = (symbol or "").upper().replace("-", "").replace("/", "").replace(":", "")
    out = [s]
    for suffix in _STABLE_SUFFIXES:
        if s.endswith(suffix):
            out.append(s[: -len(suffix)] + "USD")   # BTCUSDT -> BTCUSD
    if s.endswith("USD"):
        for suffix in _STABLE_SUFFIXES:
            out.append(s[:-3] + suffix)             # BTCUSD -> BTCUSDT
    if len(s) == 6:
        out.append(f"{s[:3]}_{s[3:]}")              # EURUSD -> EUR_USD
    seen, unique = set(), []
    for candidate in out:
        if candidate and candidate not in seen:
            seen.add(candidate)
            unique.append(candidate)
    return unique


def resolve_instrument(symbol: str):
    """Instrument for an exchange symbol, or None."""
    from instruments.models import Instrument

    candidates = instrument_symbol_candidates(symbol)
    inst = Instrument.objects.filter(symbol__in=candidates).first()
    if inst is None:
        inst = Instrument.objects.filter(symbol__iexact=symbol).first()
    return inst


def _priority(source: str) -> int:
    return SOURCE_PRIORITY.get((source or "").lower(), DEFAULT_PRIORITY)


def should_write(existing, source: str) -> bool:
    """Whether `source` may overwrite the existing quote."""
    if existing is None:
        return True
    current = (existing.source or "").lower()
    if current == (source or "").lower():
        return True
    if _priority(source) >= _priority(current):
        return True
    age = (timezone.now() - existing.updated_at).total_seconds()
    return age > PRIORITY_HOLD_SECONDS


def _dec(value):
    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    # Decimal("nan") parses cleanly — the except above never fires — and any
    # ordering comparison against it raises InvalidOperation, so a NaN that
    # reached `price <= 0` would kill the caller mid-task. Yahoo genuinely
    # serves NaN closes (in-progress FX candles, thin listings): non-finite
    # is "no value", not a value.
    return d if d.is_finite() else None


def write_quote(symbol: str, *, last, source: str, change_pct=None,
                bid=None, ask=None, volume=None, instrument=None) -> bool:
    """Persist a quote, honouring source precedence. True when written.

    A zero/None price is refused outright: several adapters default missing
    fields to 0, and a 0 written into LiveQuote reads downstream as a real
    price of zero.
    """
    from market_data.models import LiveQuote

    price = _dec(last)
    if price is None or price <= 0:
        return False

    inst = instrument or resolve_instrument(symbol)
    if inst is None:
        logger.debug("[quotes] no Instrument for %s — dropping", symbol)
        return False

    existing = LiveQuote.objects.filter(instrument=inst).first()
    if not should_write(existing, source):
        logger.debug("[quotes] %s: %s did not overwrite fresher %s",
                     inst.symbol, source, existing.source)
        return False

    defaults = {"last": price, "source": source}
    if change_pct is not None:
        defaults["change_pct"] = _dec(round(float(change_pct), 4)) or Decimal("0")
    if bid is not None:
        defaults["bid"] = _dec(bid)
    if ask is not None:
        defaults["ask"] = _dec(ask)
    if volume is not None:
        try:
            defaults["volume"] = int(float(volume))
        except (TypeError, ValueError):
            pass

    LiveQuote.objects.update_or_create(instrument=inst, defaults=defaults)
    return True
