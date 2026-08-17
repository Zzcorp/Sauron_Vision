"""Reddit sentiment scraper via PRAW — r/wallstreetbets, r/investing.

Fetches hot posts from financial subreddits, extracts ticker mentions,
and applies a simple keyword-based bullish/bearish sentiment score.
Falls back gracefully when PRAW is not installed or credentials are missing.
"""
import os
import re
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword lists for simple heuristic sentiment
# ---------------------------------------------------------------------------
BULLISH_WORDS = {"bull", "calls", "moon", "buy", "long", "green", "rocket", "pump"}
BEARISH_WORDS = {"bear", "puts", "short", "sell", "crash", "dump", "red", "drill"}

# Words that look like tickers but are not
COMMON_WORDS = {
    "A", "I", "AM", "AN", "AS", "AT", "BE", "BY", "DO", "GO", "HE", "IF",
    "IN", "IS", "IT", "ME", "MY", "NO", "OF", "ON", "OR", "SO", "TO", "UP",
    "US", "WE", "AND", "ARE", "BUT", "FOR", "GET", "HAD", "HAS", "HIM",
    "HIS", "HOW", "ITS", "NEW", "NOT", "NOW", "OLD", "OUR", "OUT", "OWN",
    "SAY", "SHE", "THE", "TOO", "USE", "WAS", "WAY", "WHO", "WHY", "WILL",
    "WITH", "YOU", "YOUR", "FROM", "HAVE", "BEEN", "THAT", "THEY", "THIS",
    "WERE", "WHAT", "WHEN", "THEN", "THAN", "SOME", "INTO", "MORE", "OVER",
    "ALSO", "LIKE", "JUST", "YEAR", "TIME", "WEEK", "DAYS", "HIGH", "VERY",
    "MUCH", "MAKE", "TAKE", "WELL", "BACK", "GOOD", "EVEN", "ONLY", "COME",
    "DOES", "DOWN", "EACH", "GIVE", "HERE", "KNOW", "LAST", "LONG", "LOOK",
    "MADE", "MANY", "MOST", "MOVE", "NEED", "NEXT", "OPEN", "PART", "PLAN",
    "PLAY", "PUTS", "RATE", "SAID", "SAME", "SELL", "SENT", "SHOW", "SIDE",
    "SOON", "SUCH", "SURE", "TELL", "TEND", "TEST", "TILL", "TURN", "USED",
    "WANT", "WENT", "WORD", "WORK", "CALL", "CALLS", "HOLD", "LOSS", "GAIN",
    "BULL", "BEAR", "MOON", "PUMP", "DUMP", "CASH", "DEBT", "FUND", "GOLD",
    "NEWS", "POOR", "RISK", "SALE", "STOP", "TRADE", "BUYS", "SOLD",
    "SEC", "IPO", "ETF", "CEO", "CFO", "CTO", "EPS", "ROI", "GDP", "CPI",
    "ALL", "ANY", "BIG", "DID", "END", "FAR", "FEW", "GOT", "HAD", "LET",
    "LOT", "MAN", "MAY", "MEN", "OFF", "OWN", "PER", "PUT", "SET", "SIT",
    "SIX", "STO", "TAX", "TEN", "TRY", "TWO", "WAR", "WIN", "YET",
}

# CryptoCurrency and Bitcoin were absent from the first cut — the platform
# scored social sentiment for stocks only while quoting a crypto fleet.
DEFAULT_SUBREDDITS = ["wallstreetbets", "investing", "stocks",
                      "CryptoCurrency", "Bitcoin"]

# Ticker patterns
DOLLAR_TICKER_RE = re.compile(r'\$([A-Z]{1,5})')
WORD_TICKER_RE = re.compile(r'\b([A-Z]{2,5})\b')


def _score_sentiment(text: str) -> tuple[int, int]:
    """Return (bullish_count, bearish_count) keyword hits in text."""
    lower = text.lower()
    words = set(re.findall(r'\b\w+\b', lower))
    bullish = len(words & BULLISH_WORDS)
    bearish = len(words & BEARISH_WORDS)
    return bullish, bearish


def _extract_tickers(text: str) -> list[str]:
    """Extract probable ticker symbols from post text."""
    tickers = set(DOLLAR_TICKER_RE.findall(text))
    for word in WORD_TICKER_RE.findall(text):
        if word not in COMMON_WORDS and len(word) >= 2:
            tickers.add(word)
    return sorted(tickers)


def fetch_reddit_sentiment(subreddits: list[str] | None = None, limit: int = 50) -> list[dict]:
    """Fetch hot posts from financial subreddits and compute sentiment.

    Args:
        subreddits: List of subreddit names to scrape.  Defaults to
                    ["wallstreetbets", "investing", "stocks"].
        limit:      Maximum posts to fetch per subreddit.

    Returns:
        List of dicts with keys: title, score, num_comments, created_utc,
        subreddit, bullish_count, bearish_count, tickers, sentiment_label.
        Returns empty list on any fatal error.
    """
    try:
        import praw  # noqa: F401
    except ImportError:
        logger.warning("PRAW is not installed — reddit_sentiment scraper disabled. "
                       "Install with: pip install praw")
        return []

    client_id = os.getenv("REDDIT_CLIENT_ID", "")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET", "")
    user_agent = os.getenv("REDDIT_USER_AGENT", "SauronVision/1.0 (financial intelligence bot)")

    if not client_id or not client_secret:
        logger.warning("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET not set — "
                       "reddit_sentiment scraper returning empty list.")
        return []

    if subreddits is None:
        subreddits = DEFAULT_SUBREDDITS

    try:
        reddit = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent,
            read_only=True,
        )
    except Exception as exc:
        logger.error("Failed to initialise PRAW Reddit client: %s", exc)
        return []

    results: list[dict] = []

    for sub_name in subreddits:
        try:
            from core.rate_limiter import rate_limiter
            rate_limiter.wait_if_needed("reddit", calls_per_minute=10)

            subreddit = reddit.subreddit(sub_name)
            hot_posts = list(subreddit.hot(limit=limit))
            logger.debug("r/%s — fetched %d posts", sub_name, len(hot_posts))

            for post in hot_posts:
                if post.stickied:
                    continue

                title: str = post.title or ""
                body: str = getattr(post, "selftext", "") or ""
                full_text = f"{title} {body}"

                bullish, bearish = _score_sentiment(full_text)
                tickers = _extract_tickers(full_text)

                if bullish > bearish:
                    sentiment_label = "bullish"
                elif bearish > bullish:
                    sentiment_label = "bearish"
                else:
                    sentiment_label = "neutral"

                created_utc = datetime.fromtimestamp(post.created_utc, tz=timezone.utc).isoformat()

                results.append({
                    "title": title,
                    "score": post.score,
                    "num_comments": post.num_comments,
                    "created_utc": created_utc,
                    "subreddit": sub_name,
                    "bullish_count": bullish,
                    "bearish_count": bearish,
                    "tickers": tickers,
                    "sentiment_label": sentiment_label,
                    "url": f"https://www.reddit.com{post.permalink}",
                })

        except Exception as exc:
            logger.error("Error scraping r/%s: %s", sub_name, exc)
            continue

    logger.info("reddit_sentiment: fetched %d posts from %d subreddits",
                len(results), len(subreddits))

    # Optionally persist aggregated snapshot per ticker
    _persist_snapshots(results)
    return results


def _persist_snapshots(posts: list[dict]) -> None:
    """Aggregate posts by ticker and upsert SentimentSnapshot rows."""
    if not posts:
        return

    try:
        from django.utils import timezone as dj_tz
        from scraping.models import SentimentSnapshot
        from instruments.models import Instrument

        ticker_agg: dict[str, dict] = {}
        for post in posts:
            for ticker in post.get("tickers", []):
                if ticker not in ticker_agg:
                    ticker_agg[ticker] = {"bullish": 0, "bearish": 0, "neutral": 0, "volume": 0}
                agg = ticker_agg[ticker]
                label = post["sentiment_label"]
                agg[label] = agg.get(label, 0) + 1
                agg["volume"] += 1

        now = dj_tz.now()
        for ticker, agg in ticker_agg.items():
            try:
                instrument = Instrument.objects.get(symbol=ticker)
                total = agg["volume"] or 1
                composite = (agg["bullish"] - agg["bearish"]) / total
                SentimentSnapshot.objects.create(
                    instrument=instrument,
                    source="reddit",
                    timestamp=now,
                    bullish_count=agg["bullish"],
                    bearish_count=agg["bearish"],
                    neutral_count=agg["neutral"],
                    composite_score=composite,
                    volume=agg["volume"],
                )
            except Instrument.DoesNotExist:
                pass  # Ticker not in our watchlist — skip silently
            except Exception as exc:
                logger.debug("Could not persist SentimentSnapshot for %s: %s", ticker, exc)

    except Exception as exc:
        logger.debug("SentimentSnapshot persistence skipped (DB unavailable?): %s", exc)
