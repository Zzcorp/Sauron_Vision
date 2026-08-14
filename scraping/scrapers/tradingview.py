"""TradingView scraper — news, community ideas, technicals.

Uses the TradingView scanner endpoint (no authentication required) to
retrieve technical analysis summaries (BUY/SELL/NEUTRAL) for any symbol,
and scrapes the public ideas feed for trending trade ideas.
"""
import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# TradingView scanner endpoint (unofficial but widely used and stable)
TV_SCANNER_URL = "https://scanner.tradingview.com/global/scan"

# Column names requested from the scanner
SCANNER_COLUMNS = [
    "Recommend.All",           # Overall recommendation
    "Recommend.MA",            # Moving averages summary
    "Recommend.Other",         # Oscillators summary
    "RSI",
    "RSI[1]",
    "Stoch.K",
    "Stoch.D",
    "MACD.macd",
    "MACD.signal",
    "ADX",
    "CCI20",
    "Mom",
    "BB.upper",
    "BB.lower",
    "close",
    "volume",
    "change",
    "SMA20",
    "SMA50",
    "SMA200",
    "EMA20",
    "EMA50",
    "EMA200",
]

# Map numeric recommendation values to labels
def _rec_label(value: Optional[float]) -> str:
    if value is None:
        return "NEUTRAL"
    if value >= 0.5:
        return "STRONG_BUY"
    if value > 0.1:
        return "BUY"
    if value <= -0.5:
        return "STRONG_SELL"
    if value < -0.1:
        return "SELL"
    return "NEUTRAL"


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json",
    "Origin": "https://www.tradingview.com",
    "Referer": "https://www.tradingview.com/",
}


def _resolve_tv_symbol(symbol: str) -> str:
    """Convert a plain ticker to a TradingView exchange:symbol format.

    Tries common US exchanges; falls back to NASDAQ prefix.
    """
    symbol = symbol.upper().strip()
    if ":" in symbol:
        return symbol
    # Common mappings for indices / crypto
    prefix_map = {
        "SPX": "SP:SPX",
        "SPY": "AMEX:SPY",
        "QQQ": "NASDAQ:QQQ",
        "BTC": "BITSTAMP:BTCUSD",
        "ETH": "BITSTAMP:ETHUSD",
        "EURUSD": "FX:EURUSD",
        "GBPUSD": "FX:GBPUSD",
        "USDJPY": "FX:USDJPY",
        "XAUUSD": "TVC:GOLD",
        "GOLD": "TVC:GOLD",
        "OIL": "TVC:USOIL",
        "CL": "NYMEX:CL1!",
        "ES": "CME_MINI:ES1!",
        "NQ": "CME_MINI:NQ1!",
    }
    if symbol in prefix_map:
        return prefix_map[symbol]
    return f"NASDAQ:{symbol}"


def fetch_technical_analysis(symbol: str) -> dict:
    """Fetch technical analysis summary for a symbol from TradingView scanner.

    Args:
        symbol: Ticker symbol (e.g. "AAPL", "NASDAQ:AAPL", "FX:EURUSD").

    Returns:
        Dict with keys: symbol, recommendation, oscillators_summary,
        moving_averages_summary, indicators (dict of raw values).
        Returns a neutral/empty structure on any error.
    """
    try:
        from core.rate_limiter import rate_limiter
        rate_limiter.wait_if_needed("tradingview", calls_per_minute=15)
    except Exception:
        pass

    tv_symbol = _resolve_tv_symbol(symbol)
    empty = {
        "symbol": symbol.upper(),
        "tv_symbol": tv_symbol,
        "recommendation": "NEUTRAL",
        "oscillators_summary": "NEUTRAL",
        "moving_averages_summary": "NEUTRAL",
        "indicators": {},
    }

    payload = {
        "symbols": {"tickers": [tv_symbol]},
        "columns": SCANNER_COLUMNS,
    }

    try:
        resp = requests.post(TV_SCANNER_URL, json=payload, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        logger.error("TradingView: request timed out for %s", tv_symbol)
        return empty
    except requests.RequestException as exc:
        logger.error("TradingView: request error for %s: %s", tv_symbol, exc)
        return empty
    except ValueError as exc:
        logger.error("TradingView: JSON decode error for %s: %s", tv_symbol, exc)
        return empty

    hits = data.get("data", [])
    if not hits:
        logger.warning("TradingView: no data returned for %s", tv_symbol)
        return empty

    row = hits[0]
    values: list = row.get("d", [])
    col_count = len(SCANNER_COLUMNS)

    # Build indicator dict
    indicators: dict = {}
    for i, col in enumerate(SCANNER_COLUMNS):
        if i < len(values):
            indicators[col] = values[i]

    rec_all = indicators.get("Recommend.All")
    rec_ma = indicators.get("Recommend.MA")
    rec_osc = indicators.get("Recommend.Other")

    result = {
        "symbol": symbol.upper(),
        "tv_symbol": tv_symbol,
        "recommendation": _rec_label(rec_all),
        "recommendation_value": rec_all,
        "oscillators_summary": _rec_label(rec_osc),
        "moving_averages_summary": _rec_label(rec_ma),
        "indicators": {
            "rsi": indicators.get("RSI"),
            "rsi_prev": indicators.get("RSI[1]"),
            "stoch_k": indicators.get("Stoch.K"),
            "stoch_d": indicators.get("Stoch.D"),
            "macd": indicators.get("MACD.macd"),
            "macd_signal": indicators.get("MACD.signal"),
            "adx": indicators.get("ADX"),
            "cci": indicators.get("CCI20"),
            "momentum": indicators.get("Mom"),
            "bb_upper": indicators.get("BB.upper"),
            "bb_lower": indicators.get("BB.lower"),
            "close": indicators.get("close"),
            "volume": indicators.get("volume"),
            "change_pct": indicators.get("change"),
            "sma20": indicators.get("SMA20"),
            "sma50": indicators.get("SMA50"),
            "sma200": indicators.get("SMA200"),
            "ema20": indicators.get("EMA20"),
            "ema50": indicators.get("EMA50"),
            "ema200": indicators.get("EMA200"),
        },
    }

    logger.debug("TradingView: %s → %s", tv_symbol, result["recommendation"])
    _persist_recommendation(result)
    return result


def _persist_recommendation(result: dict) -> int:
    """Store the aggregate recommendation as a SentimentSnapshot.

    This module had no write layer of any kind: the task fetched a full
    indicator payload per watchlist symbol and dropped it on the floor,
    keeping only a count of the HTTP round-trips it had made.

    The indicator values themselves are deliberately NOT stored. indicators/
    tasks.py already computes RSI, MACD, the moving averages and the rest from
    local PriceData into TechnicalIndicator, keyed on
    (instrument, timeframe, timestamp). A second writer filling the same rows
    from a different price source would contend on that key and leave nobody
    able to say which number came from where.

    The recommendation is the part worth keeping, because it is not derivable
    from our own bars — it is TradingView's own aggregation across its
    indicator set, and it maps cleanly onto the -1..+1 composite_score that
    SentimentSnapshot already carries.
    """
    value = result.get("recommendation_value")
    if value is None:
        return 0
    try:
        from django.utils import timezone as dj_tz
        from scraping.models import SentimentSnapshot
        from instruments.models import Instrument

        instrument = Instrument.objects.filter(
            symbol__iexact=result.get("symbol", "")).first()
        if instrument is None:
            logger.debug("TradingView: %s is not in the instrument catalogue",
                         result.get("symbol"))
            return 0

        score = max(-1.0, min(1.0, float(value)))
        SentimentSnapshot.objects.create(
            instrument=instrument,
            source="tradingview",
            timestamp=dj_tz.now(),
            # A rating is a direction, not a poll: there are no votes to
            # count, so the tallies stay at zero and the score carries it.
            bullish_count=0, bearish_count=0, neutral_count=0,
            composite_score=round(score, 4),
            volume=0,
            trending=False,
        )
        return 1
    except Exception as exc:
        logger.warning("TradingView recommendation persistence failed: %s", exc)
        return 0


def fetch_trending_ideas(limit: int = 20) -> list[dict]:
    """Fetch trending trade ideas from TradingView's public ideas endpoint.

    Uses the TradingView ideas API (unofficial, no auth required).

    Args:
        limit: Maximum number of ideas to return.

    Returns:
        List of dicts with keys: title, description, symbol, idea_type,
        author, published_at, likes, url.  Returns empty list on any error.
    """
    try:
        from core.rate_limiter import rate_limiter
        rate_limiter.wait_if_needed("tradingview", calls_per_minute=15)
    except Exception:
        pass

    # TradingView public ideas RSS / widget feed
    ideas_url = "https://www.tradingview.com/ideas/page-1/?sort=recent"
    api_url = "https://www.tradingview.com/ideas/"

    results: list[dict] = []

    # Try the JSON API endpoint used by the ideas widget
    try:
        json_url = "https://www.tradingview.com/ideas/page-1/?sort=popular&type=total&per_page=20"
        headers_html = {
            **HEADERS,
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
        }
        resp = requests.get(
            "https://www.tradingview.com/ideas/",
            params={"sort": "recent", "per_page": min(limit, 20)},
            headers=headers_html,
            timeout=20,
        )

        # TradingView often returns HTML for unauthenticated requests
        # Try to parse JSON if available, else fallback to BeautifulSoup
        content_type = resp.headers.get("Content-Type", "")

        if "application/json" in content_type:
            data = resp.json()
            ideas = data.get("ideas", data.get("data", []))
            for idea in ideas[:limit]:
                results.append({
                    "title": idea.get("title", ""),
                    "description": idea.get("description", idea.get("shortDescription", ""))[:500],
                    "symbol": idea.get("symbol", ""),
                    "idea_type": idea.get("type", ""),
                    "author": idea.get("author", {}).get("username", "") if isinstance(idea.get("author"), dict) else idea.get("author", ""),
                    "published_at": idea.get("publishedAt", idea.get("created_at", "")),
                    "likes": idea.get("likes", idea.get("likesCount", 0)),
                    "url": idea.get("url", ""),
                })
        else:
            # Fallback: try BeautifulSoup HTML parsing
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(resp.text, "lxml")
                idea_cards = soup.find_all("div", class_=lambda c: c and "idea-" in c.lower())
                if not idea_cards:
                    # Try generic article cards
                    idea_cards = soup.find_all("article")[:limit]

                for card in idea_cards[:limit]:
                    title_el = card.find(["h3", "h4", "a"], class_=lambda c: c and "title" in (c or "").lower())
                    author_el = card.find(["a", "span"], class_=lambda c: c and "author" in (c or "").lower())
                    symbol_el = card.find(["a", "span"], class_=lambda c: c and "symbol" in (c or "").lower())
                    link_el = card.find("a", href=True)

                    results.append({
                        "title": title_el.get_text(strip=True) if title_el else "",
                        "description": "",
                        "symbol": symbol_el.get_text(strip=True) if symbol_el else "",
                        "idea_type": "",
                        "author": author_el.get_text(strip=True) if author_el else "",
                        "published_at": "",
                        "likes": 0,
                        "url": link_el["href"] if link_el else "",
                    })

            except ImportError:
                logger.debug("TradingView ideas: BeautifulSoup not available for HTML fallback")
            except Exception as html_exc:
                logger.warning("TradingView ideas: HTML parsing failed: %s", html_exc)

    except requests.exceptions.Timeout:
        logger.error("TradingView: ideas request timed out")
        return []
    except requests.RequestException as exc:
        logger.error("TradingView: ideas request error: %s", exc)
        return []

    logger.info("TradingView: fetched %d ideas", len(results))
    return results
