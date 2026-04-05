"""Crypto news scraper — RSS feeds for crypto markets."""
import feedparser
import logging
from django.utils import timezone
from datetime import datetime

logger = logging.getLogger(__name__)

CRYPTO_RSS_FEEDS = {
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
    "theblock": "https://www.theblock.co/rss.xml",
    "decrypt": "https://decrypt.co/feed",
    "bitcoinmagazine": "https://bitcoinmagazine.com/.rss/full/",
}


def fetch_crypto_news(max_per_feed=5):
    """Fetch crypto news from RSS feeds."""
    from scraping.models import NewsArticle
    total = 0
    for source, url in CRYPTO_RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if not title or not link:
                    continue
                published = timezone.now()
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    except Exception:
                        pass
                _, was_created = NewsArticle.objects.get_or_create(
                    url=link[:200],
                    defaults={
                        "title": title[:500],
                        "source": source.title(),
                        "published_at": published,
                        "content_summary": entry.get("summary", "")[:1000],
                    }
                )
                if was_created:
                    total += 1
        except Exception as e:
            logger.warning(f"Crypto RSS {source} failed: {e}")
    return total
