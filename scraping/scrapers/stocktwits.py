"""StockTwits sentiment API.

Fetches symbol-level sentiment and trending symbols from the public
StockTwits API v2.  No API key is required for basic access, but the
rate limiter is used to stay within the generous but finite limits.
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import requests

logger = logging.getLogger(__name__)

STOCKTWITS_BASE = "https://api.stocktwits.com/api/2"
STREAM_SYMBOL_URL = f"{STOCKTWITS_BASE}/streams/symbol/{{symbol}}.json"
TRENDING_URL = f"{STOCKTWITS_BASE}/trending/symbols.json"

HEADERS = {
    "User-Agent": "SauronVision/1.0 (financial intelligence platform)",
    "Accept": "application/json",
}


def _get(url: str, params: dict | None = None, timeout: int = 15) -> Optional[dict]:
    """Rate-limited GET request, returns parsed JSON or None."""
    try:
        from core.rate_limiter import rate_limiter
        rate_limiter.wait_if_needed("stocktwits", calls_per_minute=20)
    except Exception:
        pass

    try:
        resp = requests.get(url, params=params, headers=HEADERS, timeout=timeout)

        if resp.status_code == 429:
            logger.warning("StockTwits: rate limit hit (429) for %s", url)
            return None

        if resp.status_code == 200:
            return resp.json()

        logger.warning("StockTwits: unexpected status %d for %s", resp.status_code, url)
        return None

    except requests.exceptions.Timeout:
        logger.error("StockTwits: request timed out for %s", url)
        return None
    except requests.RequestException as exc:
        logger.error("StockTwits: request error for %s: %s", url, exc)
        return None
    except ValueError as exc:
        logger.error("StockTwits: JSON decode error for %s: %s", url, exc)
        return None


def _extract_message_sentiment(messages: list[dict]) -> tuple[int, int, int]:
    """Count bullish / bearish / neutral from a list of StockTwits messages."""
    bullish = bearish = neutral = 0
    for msg in messages:
        entities = msg.get("entities", {})
        sentiment = msg.get("entities", {}).get("sentiment", None)
        # Some messages carry sentiment at top level
        if sentiment is None:
            sentiment = msg.get("sentiment", None)

        if sentiment is None:
            neutral += 1
        elif isinstance(sentiment, dict):
            label = (sentiment.get("basic") or "").lower()
            if label == "bullish":
                bullish += 1
            elif label == "bearish":
                bearish += 1
            else:
                neutral += 1
        else:
            neutral += 1

    return bullish, bearish, neutral


def fetch_symbol_sentiment(symbol: str, trending: bool = False) -> dict:
    """Fetch the latest message stream and compute sentiment for a symbol.

    Args:
        symbol: Uppercase ticker symbol, e.g. "AAPL".
        trending: whether this symbol is currently trending. It has to be an
            argument rather than something the caller sets afterwards, because
            this function persists before it returns — setting the flag on the
            dict you get back would change nothing about the row already
            written, which is exactly the trap the previous shape laid.

    Returns:
        Dict with keys: symbol, bullish_count, bearish_count, neutral_count,
        composite_score, volume, watchlist_count, trending, messages (list).
        Returns a zeroed-out structure on any error.
    """
    empty = {
        "symbol": symbol.upper(),
        "bullish_count": 0,
        "bearish_count": 0,
        "neutral_count": 0,
        "composite_score": 0.0,
        "volume": 0,
        "watchlist_count": 0,
        "trending": False,
        "messages": [],
    }

    url = STREAM_SYMBOL_URL.format(symbol=symbol.upper())
    data = _get(url)

    if data is None:
        return empty

    # StockTwits response shape:
    # { "response": {"status": 200}, "symbol": {...}, "messages": [...], "cursor": {...} }
    if data.get("response", {}).get("status") != 200:
        logger.warning("StockTwits: non-200 response body for %s: %s",
                       symbol, data.get("response"))
        return empty

    sym_info: dict = data.get("symbol", {})
    messages: list[dict] = data.get("messages", [])

    bullish, bearish, neutral = _extract_message_sentiment(messages)
    total = bullish + bearish + neutral or 1
    composite = (bullish - bearish) / total

    result = {
        "symbol": sym_info.get("symbol", symbol.upper()),
        "title": sym_info.get("title", ""),
        "watchlist_count": sym_info.get("watchlist_count", 0),
        "bullish_count": bullish,
        "bearish_count": bearish,
        "neutral_count": neutral,
        "composite_score": round(composite, 4),
        "volume": len(messages),
        "trending": trending,
        "messages": [
            {
                "id": m.get("id"),
                "body": m.get("body", ""),
                "created_at": m.get("created_at", ""),
                "likes": m.get("likes", {}).get("total", 0),
                "sentiment": (
                    m.get("entities", {}).get("sentiment", {}) or {}
                ).get("basic", "neutral"),
                "user": m.get("user", {}).get("username", ""),
            }
            for m in messages[:20]
        ],
    }

    # Persist if Django is available
    _persist_sentiment_snapshot(result)
    return result


def _catalogue_symbols() -> set[str]:
    """Upper-cased symbols a snapshot can actually be written against.

    Anything outside this set costs a rate-limited stream call and stores
    nothing, because _persist_sentiment_snapshot has no instrument to hang
    the row on. An empty set on a DB error is the safe answer: skip the pass
    rather than spend thirty calls we know we cannot keep.
    """
    try:
        from instruments.models import Instrument
        return {(s or "").upper() for s in Instrument.objects.filter(
            is_active=True).values_list("symbol", flat=True) if s}
    except Exception as exc:  # noqa: BLE001
        logger.warning("StockTwits: instrument catalogue unavailable: %s", exc)
        return set()


"""How many trending symbols we actually pull a message stream for.

_get is rate-limited to 20 calls/minute and StockTwits typically returns
around thirty trending symbols, so fetching every one of them would make this
task block for minutes on a queue shared with other scrapers. The trending
list is ordered by how much attention a symbol is getting, so the head of it
carries nearly all of the signal."""
TRENDING_SENTIMENT_LIMIT = 12


def fetch_trending(with_sentiment: bool = True) -> list[dict]:
    """Fetch the list of currently trending symbols on StockTwits.

    This used to fetch the trending list, loop over it setting
    item["trending"] = True on dictionaries nobody kept, and return. The
    persist helper below it was real and correct, and its only caller,
    fetch_symbol_sentiment, had zero call sites anywhere in the codebase — so
    the entire StockTwits integration ran on schedule and stored nothing.

    Returns:
        List of dicts with keys: symbol, watchlist_count, title, and (when a
        stream was fetched) the sentiment counts and composite score.
        Returns empty list on any error.
    """
    data = _get(TRENDING_URL)
    if data is None:
        return []

    if data.get("response", {}).get("status") != 200:
        logger.warning("StockTwits: trending endpoint returned non-200: %s",
                       data.get("response"))
        return []

    symbols: list[dict] = data.get("symbols", [])
    results = []

    for sym in symbols:
        results.append({
            "symbol": sym.get("symbol", ""),
            "title": sym.get("title", ""),
            "watchlist_count": sym.get("watchlist_count", 0),
        })

    logger.info("StockTwits trending: %d symbols", len(results))

    if not with_sentiment:
        for item in results:
            item["trending"] = True
        return results

    # Intersect BEFORE spending stream calls. _persist_sentiment_snapshot
    # drops anything outside the catalogue, and most trending StockTwits
    # names are small caps we do not carry — so the pass burned a
    # rate-limited call per symbol to report parsed=30/stored=1, which reads
    # as "handled 30 rows and stored none of them" forever. Walking only the
    # symbols we can persist makes the two numbers describe one universe.
    catalogue = _catalogue_symbols()
    in_catalogue = [item for item in results
                    if (item.get("symbol") or "").upper() in catalogue]
    covered = in_catalogue[:TRENDING_SENTIMENT_LIMIT]
    logger.info("StockTwits trending: %d of %d symbols are in the catalogue, "
                "pulling streams for %d",
                len(in_catalogue), len(results), len(covered))

    # Each call persists a SentimentSnapshot, which is the only way this
    # integration produces data.
    stored = 0
    for item in covered:
        detail = fetch_symbol_sentiment(item["symbol"], trending=True)
        item.update({
            "trending": True,
            "bullish_count": detail.get("bullish_count", 0),
            "bearish_count": detail.get("bearish_count", 0),
            "neutral_count": detail.get("neutral_count", 0),
            "composite_score": detail.get("composite_score", 0.0),
            "volume": detail.get("volume", 0),
        })
        if detail.get("volume"):
            stored += 1

    logger.info("StockTwits: fetched sentiment for %d of %d trending symbols",
                stored, len(covered))
    # Only the symbols a stream was actually pulled for. The caller counts
    # this list as `parsed`, and parsed has to be measured on the same
    # universe as stored or the task grades itself against work it never did.
    return covered


"""How many of the operator's own symbols get a message-stream pass."""
WATCHLIST_SENTIMENT_LIMIT = 8


def _sentiment_universe(limit: int) -> tuple[list[str], str]:
    """The equities a per-symbol pass should walk, and which set they came from.

    This filtered on is_watchlist=True alone, and nothing in the platform
    sets that flag — not one of the 179 active instruments has it. So the one
    pass whose entire job is to guarantee a snapshot row iterated zero times
    and returned 0, which is why "Social Sentiment ran and produced nothing"
    survived the trending fix as well.

    An empty watchlist is a configuration the operator has not got round to,
    not an instruction to do nothing, so fall back the way
    scraping.tasks._scan_universe does: the active instruments we actually
    have prices for, which is the set any of this can say something about.
    Stocks and ETFs only — StockTwits spells crypto BTC.X, which the
    catalogue does not, so a crypto row would spend a call on a 404.
    """
    from instruments.models import Instrument

    equities = Instrument.objects.filter(
        is_active=True, asset_class__in=("stock", "etf"))

    starred = list(equities.filter(is_watchlist=True).order_by("symbol")
                   .values_list("symbol", flat=True)[:limit])
    if starred:
        return starred, "watchlist"

    priced = list(equities.filter(prices__isnull=False).distinct()
                  .order_by("symbol").values_list("symbol", flat=True)[:limit])
    if priced:
        logger.info("No equities are flagged is_watchlist; falling back to "
                    "%d active instruments that have price history. Run "
                    "`manage.py seed_watchlist` to set a real watchlist.",
                    len(priced))
        return priced, "priced"

    logger.warning("No watchlist and no equities with price history — "
                   "StockTwits per-symbol sentiment has nothing to walk.")
    return [], "empty"


def fetch_watchlist_sentiment(limit: int = WATCHLIST_SENTIMENT_LIMIT) -> int:
    """Message-stream sentiment for the equities we can persist rows for.

    Trending-only coverage sampled StockTwits' universe instead of ours:
    most trending names are small caps outside the catalogue, so a pass
    could fetch thirty symbols and persist zero rows — "Social Sentiment
    ran and produced nothing" was the DESIGNED outcome on most days. The
    symbols this walks are in the catalogue by definition, so their
    snapshots always land.

    Returns the number of symbols whose stream produced messages.
    """
    try:
        symbols, universe = _sentiment_universe(limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("StockTwits watchlist selection failed: %s", exc)
        return 0

    covered = 0
    for sym in symbols:
        detail = fetch_symbol_sentiment(sym)
        if detail.get("volume"):
            covered += 1
    logger.info("StockTwits %s pass: sentiment for %d of %d equities",
                universe, covered, len(symbols))
    return covered


def _persist_sentiment_snapshot(data: dict) -> int:
    """Save a SentimentSnapshot row if the instrument is in our DB.

    Returns 1 if a row was written, 0 otherwise — the caller needs to be able
    to distinguish "nothing to store" from "stored nothing".
    """
    try:
        from django.utils import timezone as dj_tz
        from scraping.models import SentimentSnapshot
        from instruments.models import Instrument

        symbol = data.get("symbol", "")
        if not symbol:
            return 0

        instrument = Instrument.objects.filter(symbol__iexact=symbol).first()
        if instrument is None:
            # Most trending StockTwits symbols are small caps outside our
            # catalogue, so this is the common case rather than an error — but
            # it was previously a bare `return` and the drops were invisible.
            logger.debug("StockTwits: %s is not in the instrument catalogue", symbol)
            return 0

        SentimentSnapshot.objects.create(
            instrument=instrument,
            source="stocktwits",
            timestamp=dj_tz.now(),
            # .get with defaults, not subscripts: the trending payload has a
            # different shape to the stream payload, and hard subscripts here
            # raised KeyError straight into the DEBUG-level swallow below.
            bullish_count=data.get("bullish_count", 0),
            bearish_count=data.get("bearish_count", 0),
            neutral_count=data.get("neutral_count", 0),
            composite_score=data.get("composite_score", 0.0),
            volume=data.get("volume", 0),
            trending=data.get("trending", False),
        )
        return 1

    except Exception as exc:
        # WARNING, not DEBUG. At DEBUG an IntegrityError mid-batch was
        # completely invisible at the default log level.
        logger.warning("StockTwits SentimentSnapshot persistence failed: %s", exc)
        return 0
