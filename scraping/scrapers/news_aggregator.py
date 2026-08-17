"""News aggregator — fetches from RSS feeds and MarketAux API.

Three things were wrong here and every one of them was invisible.

1. Every published_at was fabricated. Line 51 built the timestamp with
   `tzinfo=timezone.utc` where `timezone` is django.utils.timezone — an
   attribute Django 5.0 removed. So the expression raised AttributeError on
   every single entry, a bare `except` quietly substituted `timezone.now()`,
   and the article was stored with the time we scraped it instead of the time
   it was published. It fired 100% of the time: all the live feeds supply
   published_parsed. The damage is not local — every "last 24 hours" window in
   the platform reads this column, so news sentiment, the digests, the
   opportunity scanner and the pattern miner were all measuring time since we
   happened to poll.

2. Two of the eleven feeds are gone. feeds.reuters.com no longer resolves, and
   feedparser does not raise for a dead host — it returns bozo=1 with zero
   entries, so the `except` never fired and the dead feeds cost a request every
   fifteen minutes while looking exactly like a quiet news day.

3. The URL was truncated to 200 characters against a unique column. Modern
   article links carry tracking parameters well past that, so two different
   articles sharing a 200-character prefix silently collapsed into one row —
   and the link that got stored was the truncated one, which does not resolve.

The functions now return what they stored rather than what they fetched, so a
scraper that parses two hundred articles and writes none can no longer report
itself as healthy.
"""
import os
import logging
import re
from datetime import datetime, timezone as dt_timezone

import feedparser
import requests
from django.utils import timezone

from core.proxy import get_session

logger = logging.getLogger(__name__)

MARKETAUX_KEY = os.getenv("MARKETAUX_API_KEY", "")

# Free RSS feeds for financial news.
# reuters_business / reuters_markets were removed: feeds.reuters.com stopped
# resolving and every poll was a guaranteed silent miss.
RSS_FEEDS = {
    "cnbc_top": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "cnbc_world": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362",
    "wsj_markets": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "ft_markets": "https://www.ft.com/markets?format=rss",
    "investing_news": "https://www.investing.com/rss/news.rss",
    "yahoo_finance": "https://finance.yahoo.com/news/rssindex",
    "marketwatch": "https://feeds.marketwatch.com/marketwatch/topstories/",
    "bloomberg_markets": "https://feeds.bloomberg.com/markets/news.rss",
    "seeking_alpha": "https://seekingalpha.com/market_currents.xml",
    # Crypto — the original nine feeds were all equities/macro, so the
    # platform traded BTC and ETH while structurally unable to hear a word
    # about them. All three verified live and keyless (2026-08-18);
    # coindesk 308s on the trailing-slash spelling, hence the exact URL.
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss",
    "cointelegraph": "https://cointelegraph.com/rss",
    "decrypt": "https://decrypt.co/feed",
}

# Words that are also tickers. Matching these bare would tag half the feed.
_TICKER_STOPWORDS = {
    "ALL", "AND", "ANY", "ARE", "BIG", "BUY", "CAN", "CEO", "CFO", "EPS",
    "FOR", "GDP", "HAS", "HIS", "ITS", "NEW", "NOW", "ONE", "OUT", "PLC",
    "SEC", "SEE", "THE", "TOP", "TWO", "USA", "WAS", "WHO", "YOU", "IPO",
    "ETF", "FED", "CPI", "PPI", "AI", "IT", "ON", "AT", "BY", "IN", "OF",
    "OR", "SO", "TO", "UP", "US", "EU", "UK",
}


def _published_at(entry):
    """The time the article says it was published, or None if it does not say.

    Returning None rather than now() matters: a fabricated timestamp is worse
    than a missing one, because every downstream window treats it as fact.
    """
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=dt_timezone.utc)
    except (TypeError, ValueError) as exc:
        logger.warning("unparseable feed timestamp %r: %s", parsed, exc)
        return None


def _instrument_index():
    """symbol/name lookup used to tag an article without an LLM.

    The AI news analyst fills ai_affected_instruments, but it needs a key that
    this deployment does not have, so the column has never been written. A
    plain text match gets most of the value for nothing.
    """
    from instruments.models import Instrument

    by_symbol, by_name = {}, []
    for pk, symbol, name in Instrument.objects.filter(
            is_active=True).values_list("id", "symbol", "name"):
        sym = (symbol or "").upper()
        if sym:
            by_symbol[sym] = pk
        if name and len(name) >= 5:
            by_name.append((name.lower(), pk))
    return by_symbol, by_name


def _match_instruments(text, index):
    """Instrument ids this text plausibly concerns.

    Deliberately conservative. A cashtag is unambiguous. A bare symbol is only
    trusted at three characters or more and outside the stopword list, because
    tagging every article containing the word "ALL" would poison the per
    instrument news feeds far more than missing a few tags would.
    """
    by_symbol, by_name = index
    hits = set()
    upper = text.upper()
    lower = text.lower()

    for tag in re.findall(r"\$([A-Za-z][A-Za-z0-9.\-]{0,9})", text):
        pk = by_symbol.get(tag.upper())
        if pk:
            hits.add(pk)

    for word in set(re.findall(r"\b[A-Z][A-Z0-9]{2,9}\b", upper)):
        if word in _TICKER_STOPWORDS:
            continue
        pk = by_symbol.get(word)
        if pk:
            hits.add(pk)

    for name, pk in by_name:
        if name in lower:
            hits.add(pk)

    return hits


def fetch_rss_news(max_per_feed=10):
    """Fetch news from all RSS feeds.

    Returns {"parsed", "stored", "feeds_ok", "feeds_dead"} — the caller needs
    to be able to tell "no new articles" from "no feed answered".
    """
    from scraping.models import NewsArticle

    parsed = stored = 0
    feeds_ok, feeds_dead = 0, []
    index = _instrument_index()

    for source_key, feed_url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(feed_url)

            # feedparser does not raise for a dead host, an HTTP error or
            # unparseable XML — it sets bozo and hands back zero entries. That
            # is why two long-dead feeds sat here unnoticed.
            if not feed.entries:
                feeds_dead.append(source_key)
                logger.warning(
                    "RSS feed %s returned no entries (bozo=%s: %s)",
                    source_key, getattr(feed, "bozo", "?"),
                    getattr(feed, "bozo_exception", ""))
                continue
            feeds_ok += 1
            source_name = source_key.replace("_", " ").title()

            for entry in feed.entries[:max_per_feed]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if not title or not link:
                    continue
                parsed += 1

                summary = entry.get("summary", entry.get("description", ""))[:1000]
                published = _published_at(entry) or timezone.now()

                article, was_created = NewsArticle.objects.get_or_create(
                    url=link[:500],
                    defaults={
                        "title": title[:500],
                        "source": source_name,
                        "published_at": published,
                        "content_summary": summary,
                    },
                )
                if was_created:
                    stored += 1
                    matched = _match_instruments(title + " " + summary, index)
                    if matched:
                        article.ai_affected_instruments.set(matched)

        except Exception as e:
            feeds_dead.append(source_key)
            logger.warning("RSS feed %s failed: %s", source_key, e)

    logger.info("RSS scraper: parsed=%s stored=%s feeds_ok=%s dead=%s",
                parsed, stored, feeds_ok, feeds_dead)
    return {"parsed": parsed, "stored": stored,
            "feeds_ok": feeds_ok, "feeds_dead": feeds_dead}


def fetch_marketaux_news(tickers=None, limit=50):
    """Fetch news from MarketAux API (structured, with sentiment)."""
    from scraping.models import NewsArticle

    if not MARKETAUX_KEY:
        # Distinguishable from "the API returned nothing": without this the
        # task reported success and a count of zero, which reads as a quiet
        # news day rather than as an unconfigured integration.
        logger.warning("MarketAux skipped: MARKETAUX_API_KEY is not set")
        return {"parsed": 0, "stored": 0, "skipped": "no_api_key"}

    params = {"api_token": MARKETAUX_KEY, "language": "en", "limit": limit}
    if tickers:
        params["symbols"] = ",".join(tickers)

    try:
        resp = get_session().get(
            "https://api.marketaux.com/v1/news/all", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error("MarketAux API error: %s", e)
        return {"parsed": 0, "stored": 0, "error": str(e)}

    parsed = stored = 0
    index = _instrument_index()

    for article in data.get("data", []):
        url = article.get("url", "")
        if not url:
            continue
        parsed += 1

        published = None
        if article.get("published_at"):
            try:
                published = datetime.fromisoformat(
                    article["published_at"].replace("Z", "+00:00"))
            except (TypeError, ValueError):
                logger.warning("unparseable MarketAux timestamp %r",
                               article.get("published_at"))

        title = article.get("title", "")[:500]
        summary = article.get("description", "")[:1000]

        row, was_created = NewsArticle.objects.get_or_create(
            url=url[:500],
            defaults={
                "title": title,
                "source": article.get("source", "MarketAux"),
                "published_at": published or timezone.now(),
                "content_summary": summary,
            },
        )
        if was_created:
            stored += 1
            matched = _match_instruments(title + " " + summary, index)
            if matched:
                row.ai_affected_instruments.set(matched)

    logger.info("MarketAux: parsed=%s stored=%s", parsed, stored)
    return {"parsed": parsed, "stored": stored}
