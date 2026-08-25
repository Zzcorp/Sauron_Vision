"""Crypto news scraper — RSS feeds for crypto markets.

Three things were wrong here, and all three were the same failures
news_aggregator.py already carries fixes for.

1. Every published_at was the scrape time. The timestamp was built with
   `tzinfo=timezone.utc`, where `timezone` is django.utils.timezone — an
   attribute Django 5 removed. So the expression raised AttributeError on
   every entry that carried a date (which is all of them), the bare `except`
   swallowed it, and the row kept the timezone.now() default. Every crypto
   article on the platform was stamped with when we polled rather than when
   it was published, and every "last 24 hours" window downstream — news
   sentiment, the digests, the scanner — read that column as fact. The parse
   now lives in exactly one place, news_aggregator._published_at: a third
   copy would be a third thing to miss the next time an attribute goes.

2. A dead feed and a fully-deduplicated one looked identical. feedparser does
   not raise for a host that stopped resolving, an HTTP error or unparseable
   XML — it sets bozo and hands back zero entries, so the try/except never
   fired and a dead feed cost a request every ten minutes while looking
   exactly like a quiet news day.

3. The link was truncated to 200 characters against a unique 500-character
   column. Two crypto articles sharing a 200-character prefix collapsed into
   one row, the stored link did not resolve — and because fetch_rss_news
   stores the SAME article at its full length, a long URL wrote two rows
   instead of deduplicating against the one already there.

The return shape changed for a reason worth stating: coindesk, cointelegraph
and decrypt are the exact URLs fetch_rss_news already polls, so this scraper
is dedupe-bound by design and creating no new rows is its HEALTHY state.
Graded on new rows alone it reads silent forever, so it now also reports
whether the feeds ANSWERED — parsed/feeds_ok/feeds_dead — which is the thing
this task can actually be wrong about.
"""
import logging

import feedparser
from django.utils import timezone

# Imported, not re-implemented: the timestamp parse is the bug above and one
# copy of it is the fix.
from scraping.scrapers.news_aggregator import _published_at

logger = logging.getLogger(__name__)

CRYPTO_RSS_FEEDS = {
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
    "theblock": "https://www.theblock.co/rss.xml",
    "decrypt": "https://decrypt.co/feed",
    "bitcoinmagazine": "https://bitcoinmagazine.com/.rss/full/",
}


def fetch_crypto_news(max_per_feed=5):
    """Fetch crypto news from RSS feeds.

    Returns {"parsed", "stored", "feeds_ok", "feeds_dead"} — a bare count of
    new rows cannot tell the caller whether five feeds answered and said
    nothing new or five feeds are gone.
    """
    from scraping.models import NewsArticle

    parsed = stored = 0
    feeds_ok, feeds_dead = 0, []

    for source, url in CRYPTO_RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)

            if not getattr(feed, "entries", None):
                feeds_dead.append(source)
                logger.warning(
                    "Crypto RSS %s returned no entries (bozo=%s: %s)",
                    source, getattr(feed, "bozo", "?"),
                    getattr(feed, "bozo_exception", ""))
                continue
            feeds_ok += 1

            for entry in feed.entries[:max_per_feed]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if not title or not link:
                    continue
                parsed += 1

                # now() only when the entry itself does not say. A fabricated
                # timestamp is worse than a missing one because every window
                # downstream treats it as the publication time.
                published = _published_at(entry) or timezone.now()

                _, was_created = NewsArticle.objects.get_or_create(
                    # 500, matching the column and fetch_rss_news. At 200 the
                    # same article stored here and there became two rows.
                    url=link[:500],
                    defaults={
                        "title": title[:500],
                        "source": source.title(),
                        "published_at": published,
                        "content_summary": entry.get("summary", "")[:1000],
                    }
                )
                if was_created:
                    stored += 1

        except Exception as e:
            feeds_dead.append(source)
            logger.warning("Crypto RSS %s failed: %s", source, e)

    logger.info("Crypto RSS: parsed=%s stored=%s feeds_ok=%s dead=%s",
                parsed, stored, feeds_ok, feeds_dead)
    return {"parsed": parsed, "stored": stored,
            "feeds_ok": feeds_ok, "feeds_dead": feeds_dead}
