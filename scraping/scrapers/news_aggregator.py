"""News aggregator — fetches from RSS feeds and MarketAux API."""
import os
import logging
import feedparser
import requests
from datetime import datetime
from django.utils import timezone
from core.proxy import get_session

logger = logging.getLogger(__name__)

MARKETAUX_KEY = os.getenv("MARKETAUX_API_KEY", "")

# Free RSS feeds for financial news
RSS_FEEDS = {
    "reuters_business": "https://feeds.reuters.com/reuters/businessNews",
    "reuters_markets": "https://feeds.reuters.com/reuters/marketsNews",
    "cnbc_top": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
    "cnbc_world": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100727362",
    "wsj_markets": "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "ft_markets": "https://www.ft.com/markets?format=rss",
    "investing_news": "https://www.investing.com/rss/news.rss",
    "yahoo_finance": "https://finance.yahoo.com/news/rssindex",
    "marketwatch": "https://feeds.marketwatch.com/marketwatch/topstories/",
    "bloomberg_markets": "https://feeds.bloomberg.com/markets/news.rss",
    "seeking_alpha": "https://seekingalpha.com/market_currents.xml",
}


def fetch_rss_news(max_per_feed=10):
    """Fetch news from all RSS feeds."""
    from scraping.models import NewsArticle

    total_created = 0

    for source_key, feed_url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(feed_url)
            source_name = source_key.replace("_", " ").title()

            for entry in feed.entries[:max_per_feed]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if not title or not link:
                    continue

                # Parse published date
                published = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    except Exception:
                        published = timezone.now()
                else:
                    published = timezone.now()

                # Get summary
                summary = entry.get("summary", entry.get("description", ""))[:1000]

                # Save if not duplicate
                _, was_created = NewsArticle.objects.get_or_create(
                    url=link[:200],
                    defaults={
                        "title": title[:500],
                        "source": source_name,
                        "published_at": published,
                        "content_summary": summary,
                    }
                )
                if was_created:
                    total_created += 1

        except Exception as e:
            logger.warning(f"RSS feed {source_key} failed: {e}")

    logger.info(f"RSS scraper: {total_created} new articles")
    return total_created


def fetch_marketaux_news(tickers=None, limit=50):
    """Fetch news from MarketAux API (structured, with sentiment)."""
    if not MARKETAUX_KEY:
        return 0

    from scraping.models import NewsArticle

    params = {
        "api_token": MARKETAUX_KEY,
        "language": "en",
        "limit": limit,
    }
    if tickers:
        params["symbols"] = ",".join(tickers)

    try:
        resp = requests.get("https://api.marketaux.com/v1/news/all", params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.error(f"MarketAux API error: {e}")
        return 0

    created = 0
    for article in data.get("data", []):
        url = article.get("url", "")
        if not url:
            continue

        published = timezone.now()
        if article.get("published_at"):
            try:
                published = datetime.fromisoformat(article["published_at"].replace("Z", "+00:00"))
            except Exception:
                pass

        _, was_created = NewsArticle.objects.get_or_create(
            url=url[:200],
            defaults={
                "title": article.get("title", "")[:500],
                "source": article.get("source", "MarketAux"),
                "published_at": published,
                "content_summary": article.get("description", "")[:1000],
            }
        )
        if was_created:
            created += 1

    return created
