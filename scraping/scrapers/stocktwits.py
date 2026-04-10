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


def fetch_symbol_sentiment(symbol: str) -> dict:
    """Fetch the latest message stream and compute sentiment for a symbol.

    Args:
        symbol: Uppercase ticker symbol, e.g. "AAPL".

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
        "trending": False,
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


def fetch_trending() -> list[dict]:
    """Fetch the list of currently trending symbols on StockTwits.

    Returns:
        List of dicts with keys: symbol, watchlist_count, title.
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

    # Optionally fetch sentiment for each trending symbol and persist
    for item in results:
        item["trending"] = True

    return results


def _persist_sentiment_snapshot(data: dict) -> None:
    """Save a SentimentSnapshot row if the instrument is in our DB."""
    try:
        from django.utils import timezone as dj_tz
        from scraping.models import SentimentSnapshot
        from instruments.models import Instrument

        symbol = data.get("symbol", "")
        if not symbol:
            return

        instrument = Instrument.objects.filter(symbol=symbol).first()
        if instrument is None:
            return

        SentimentSnapshot.objects.create(
            instrument=instrument,
            source="stocktwits",
            timestamp=dj_tz.now(),
            bullish_count=data["bullish_count"],
            bearish_count=data["bearish_count"],
            neutral_count=data["neutral_count"],
            composite_score=data["composite_score"],
            volume=data["volume"],
            trending=data.get("trending", False),
        )

    except Exception as exc:
        logger.debug("StockTwits SentimentSnapshot persistence skipped: %s", exc)
