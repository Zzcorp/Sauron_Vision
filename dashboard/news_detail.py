"""News article detail view with sentiment, key info and impact scoring.

Everything on the page is computed server-side and every value the data
cannot support is None so the template can render the muted em-dash
instead of a fabricated zero: a reaction with no bar before publication
is "unmeasured", not "0.00%".
"""
import math
import re
from collections import Counter
from urllib.parse import urlparse

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache

URGENCY_WEIGHT = {"critical": 5, "high": 4, "medium": 3, "low": 2, "": 1, None: 1}

def _impact_score(article) -> dict:
    """Return dict with stars (0..5), percent (0..100), label."""
    u = (article.ai_urgency or "").lower()
    base = URGENCY_WEIGHT.get(u, 1)                                     # 1..5
    sent = abs(float(article.ai_sentiment_score or 0))                   # 0..1
    try:
        affected = article.ai_affected_instruments.count()
    except Exception:
        affected = 0
    # Composite 0..100
    raw = (base / 5) * 60 + sent * 25 + min(affected, 5) * 3
    pct = int(max(0, min(100, round(raw))))
    stars = max(1, min(5, round(pct / 20)))
    label = {1:"MINOR",2:"LOW",3:"MODERATE",4:"HIGH",5:"CRITICAL"}[stars]
    return {"stars": stars, "percent": pct, "label": label}

def _extract_key_points(text: str, limit: int = 5) -> list[str]:
    if not text: return []
    # Split on sentence boundaries, filter short/noisy ones
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    out = []
    for s in parts:
        s = s.strip()
        if 20 <= len(s) <= 240:
            out.append(s)
        if len(out) >= limit: break
    return out


# ---------------------------------------------------------------- keywords
# Function words plus the newswire filler ("said", "according", "shares")
# that would otherwise top every article's chip row and tell the operator
# nothing about THIS story.
STOPWORDS = frozenset("""
a about above after again against all also am an and any are as at be
because been before being below between both but by can could did do does
doing down during each few for from further had has have having he her here
hers herself him himself his how i if in into is it its itself just let me
more most my myself no nor not now of off on once only or other our ours
ourselves out over own same she should so some such than that the their
theirs them themselves then there these they this those through to too under
until up very was we were what when where which while who whom why will with
would you your yours yourself yourselves
said says say saying according told reported report reports reuters
bloomberg news article story week weeks month months year years today
yesterday tomorrow monday tuesday wednesday thursday friday saturday sunday
january february march april may june july august september october
november december percent per cent since amid among however although
still already another around back even every first last late later
made make makes many much must new next people rather really seen shares
stock stocks market markets company companies group including like long
need one two three four five six seven eight nine ten well whether within
without yet across ahead early earlier high higher low lower time times
way analyst analysts investors investor trading trader traders
""".split())

# Words that ride into an entity only because a sentence starts with them
# ("The Federal Reserve" must become "Federal Reserve").
_ENTITY_LEAD_NOISE = frozenset(
    "the a an in on at by for from with and but or as of to this that these "
    "those it its his her their our".split())

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z'\-]*[A-Za-z]|[A-Za-z]")
_WORD_RE = re.compile(r"\S+")
# Lookarounds, NOT \b: `'` and `-` live inside the word class but are
# non-word characters to \b, so every capital after a hyphen was a fresh
# match start and the engine backtracked character by character — a
# 50KB "Fed-Holds-Rates-..." slug pinned a worker for minutes. And
# [ \t]+ rather than \s+, so a run can never bridge the newline that
# separates the title from the body.
_ENTITY_RE = re.compile(
    r"(?<![A-Za-z'\-])([A-Z][a-zA-Z'\-]+(?:[ \t]+[A-Z][a-zA-Z'\-]+)+)"
    r"(?![a-zA-Z'\-])")
# A lone capitalised word is a name only mid-sentence — sentence-initial
# capitals are grammar, not "Fed".
_SOLO_ENTITY_RE = re.compile(
    r"(?<=[a-z,;:]\s)([A-Z][a-zA-Z'\-]{2,})(?![a-zA-Z'\-])")
_TICKER_RE = re.compile(r"^[A-Z]{2,5}$")
# Caps that are not symbols. They out-frequency real tickers on the wire
# and would take every ticker slot.
_ACRONYM_NOISE = frozenset(
    "us uk eu un ceo cfo coo cto gdp cpi ppi pce ai ipo etf fed ecb boj "
    "boe imf nyse sec fomc q1 q2 q3 q4 usd eur gbp jpy ytd yoy qoq eps "
    "ath api url faq ok no vs".split())
# The regex work is linear now, but the text is still unbounded: a body
# nobody capped is not a reason to hold a request open.
_SCAN_CAP = 20000
_ENTITY_MAX_WORDS = 4


def _is_title_case(text: str) -> bool:
    """True when most of the meaningful words are capitalised — the
    headline house style of every wire, and useless as name evidence."""
    words = [w for w in _TOKEN_RE.findall(text or "") if len(w) >= 4]
    if len(words) < 4:
        return False
    caps = sum(1 for w in words if w[0].isupper())
    return caps / len(words) >= 0.7


def _known_symbols(article) -> set:
    """The symbols the analyst pass linked to this article."""
    try:
        return set(article.ai_affected_instruments
                   .values_list("symbol", flat=True))
    except Exception:
        return set()


def _extract_keywords(article, limit: int = 14) -> list[dict]:
    """Top keyword chips for the article: multi-word capitalised entities
    first ("Federal Reserve", "Jerome Powell"), then ALL-CAPS tickers and
    frequent terms. Each chip is {"text", "kind": "entity"|"ticker"|"term",
    "count"}. [] when the article carries no text at all."""
    title = (article.title or "")[:_SCAN_CAP]
    summary = (article.ai_summary or "")[:_SCAN_CAP]
    scraped = (article.content_summary or "")[:_SCAN_CAP]
    raw = (article.raw_content or "")[:_SCAN_CAP]
    term_text = "\n\n".join((title, summary, scraped))
    # A Title Case wire headline is every word capitalised — read as
    # entities it collapses into one chip the width of the headline. The
    # body still names the same institutions in ordinary prose.
    entity_parts = [summary, scraped, raw]
    if not _is_title_case(title):
        entity_parts.insert(0, title)
    entity_text = "\n\n".join(entity_parts)
    if not "".join((title, summary, scraped, raw)).strip():
        return []

    entities: Counter = Counter()
    for m in _ENTITY_RE.finditer(entity_text):
        words = m.group(1).split()
        while words and words[0].lower() in _ENTITY_LEAD_NOISE:
            words = words[1:]
        while words and words[-1].lower() in _ENTITY_LEAD_NOISE:
            words = words[:-1]
        # A run of ALL-CAPS words is tickers, not a name.
        if len(words) < 2 or all(_TICKER_RE.match(w) for w in words):
            continue
        # "Fed Chair Jerome Powell Told Reporters Yesterday That" is not a
        # name — a name is short. Keep the head.
        entities[" ".join(words[:_ENTITY_MAX_WORDS])] += 1
    for m in _SOLO_ENTITY_RE.finditer(entity_text):
        word = m.group(1)
        low = word.lower()
        if low in STOPWORDS or low in _ENTITY_LEAD_NOISE:
            continue
        if _TICKER_RE.match(word) and word.isupper():
            continue
        # Only if it never appeared as part of a longer name.
        if any(word in e.split() for e in entities):
            continue
        entities[word] += 1

    terms: Counter = Counter()
    tickers: Counter = Counter()
    known = _known_symbols(article)
    for tok in _TOKEN_RE.findall(term_text):
        low = tok.lower()
        if _TICKER_RE.match(tok) and low not in STOPWORDS:
            # Caps that are not symbols go to the term pile, so the four
            # ticker slots hold tickers.
            if low in _ACRONYM_NOISE and tok not in known:
                pass
            else:
                tickers[tok] += 1
                continue
        # Three letters, not four: "fed", "oil", "gas", "war", "tax" are
        # the macro vocabulary, and STOPWORDS already holds the 3-letter
        # function words.
        if len(low) < 3 or low in STOPWORDS or low.strip("'-") in STOPWORDS:
            continue
        terms[low] += 1

    # A term already inside a captured entity ("reserve" in "Federal
    # Reserve") would be a duplicate chip.
    entity_words = {w.lower() for e in entities for w in e.split()}
    entity_cap = max(4, limit // 2)
    chips = [{"text": e, "kind": "entity", "count": c}
             for e, c in entities.most_common(entity_cap)]
    # A symbol the analyst pass actually linked outranks a stray capital.
    ranked = sorted(tickers.items(),
                    key=lambda kv: (kv[0] in known, kv[1]), reverse=True)
    chips += [{"text": t, "kind": "ticker", "count": c}
              for t, c in ranked[:4]]
    for t, c in terms.most_common():
        if len(chips) >= limit:
            break
        if t in entity_words:
            continue
        chips.append({"text": t, "kind": "term", "count": c})
    return chips[:limit]


# ---------------------------------------------------------------- facts
def _age_label(delta) -> str | None:
    if delta is None:
        return None
    secs = max(0, int(delta.total_seconds()))
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86400:
        h, m = divmod(secs // 60, 60)
        return f"{h}h {m:02d}m" if m else f"{h}h"
    return f"{secs // 86400}d"


def _source_domain(url: str) -> str | None:
    try:
        host = urlparse(url or "").netloc.lower()
    except ValueError:
        return None
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _reading_facts(article) -> dict:
    """Word count and read time of the fullest text the article carries,
    scrape-to-analysis latency, and the source domain. None where unmeasured."""
    text = article.raw_content or article.ai_summary or article.content_summary or ""
    # Whitespace tokens, not letter runs: "Q2 EPS $1.23 vs $1.10" is six
    # words, and a numeric table is not a measured zero.
    words = len(_WORD_RE.findall(text)) if text.strip() else None
    # 220 wpm is the usual adult prose pace; ceil so a 30-word blurb reads
    # "1 min", never "0 min".
    read_min = max(1, math.ceil(words / 220)) if words else None
    if words == 0:
        words = None   # non-empty but wordless — unmeasured, never "0 words"
    text_kind = ("full text" if article.raw_content else
                 "AI summary" if article.ai_summary else
                 "summary" if article.content_summary else None)
    latency = None
    if article.ai_processed_at and article.scraped_at:
        latency = _age_label(article.ai_processed_at - article.scraped_at)
    return {
        "words": words, "read_min": read_min, "text_kind": text_kind,
        "latency": latency, "domain": _source_domain(article.url),
    }


# ---------------------------------------------------------------- reaction
def _pct(now_v, then_v) -> float | None:
    try:
        then_f, now_f = float(then_v), float(now_v)
    except (TypeError, ValueError):
        return None
    if then_f == 0:
        return None
    return (now_f - then_f) / then_f * 100.0


def _tone(v) -> str:
    if v is None:
        return "unknown"
    return "up" if v > 0 else "down" if v < 0 else "flat"


def _sent_tone(score) -> str:
    if score is None:
        return "unknown"
    return "up" if score > 0.2 else "down" if score < -0.2 else "flat"


def _instrument_rows(article, affected, now=None) -> list[dict]:
    """Per affected instrument (max 6): price move since publication and the
    latest sentiment snapshot. Missing pieces stay None for the em-dash."""
    from market_data.models import LiveQuote, PriceData
    from scraping.models import SentimentSnapshot
    now = now or timezone.now()
    rows = []
    for inst in affected[:6]:
        row = {"inst": inst, "symbol": inst.symbol,
               "base_close": None, "base_at": None, "last": None,
               "since_pct": None, "since_tone": "unknown",
               "day_pct": None, "day_tone": "unknown", "quote_age": None,
               "sent_score": None, "sent_tone": "unknown", "bull": None,
               "bear": None, "neutral": None, "trending": None,
               "sent_at": None, "sent_source": None}
        try:
            quote = LiveQuote.objects.get(instrument=inst)
        except LiveQuote.DoesNotExist:
            quote = None
        # Daily bars are stamped at their OPEN by every ingester, so the
        # bar whose stamp precedes publication is the SAME session — its
        # close lands hours AFTER the news and would price the reaction
        # into the baseline. Take the last session that had already
        # closed, and refuse a baseline older than a week: a month-old
        # bar is not "since publication", it is a different market.
        cutoff = article.published_at - timezone.timedelta(hours=24)
        bar = (PriceData.objects
               .filter(instrument=inst, timeframe="1d",
                       timestamp__lte=cutoff,
                       timestamp__gte=article.published_at - timezone.timedelta(days=7))
               .order_by("-timestamp").first())
        if bar is not None:
            row["base_close"] = bar.close
            row["base_at"] = bar.timestamp
        if quote is not None:
            row["last"] = quote.last
            # STALENESS is the honest unmeasured signal, not zero: the
            # writers store real zeros for a genuinely flat tape, and an
            # em-dash on a flat day would be its own small lie. A quote
            # nobody has touched in a day says nothing either way.
            cp = quote.change_pct
            fresh = bool(quote.updated_at
                         and (now - quote.updated_at) <= timezone.timedelta(hours=24))
            row["day_pct"] = (float(cp) if (cp is not None and fresh
                                            and float(cp) != 0.0) else None)
            row["day_tone"] = _tone(row["day_pct"])
            row["quote_age"] = _age_label(now - quote.updated_at) if quote.updated_at else None
        if bar is not None and quote is not None:
            row["since_pct"] = _pct(quote.last, bar.close)
            row["since_tone"] = _tone(row["since_pct"])
        snap = (SentimentSnapshot.objects.filter(instrument=inst)
                .order_by("-timestamp").first())
        if snap is not None:
            row.update({
                "sent_score": snap.composite_score,
                "sent_tone": _sent_tone(snap.composite_score),
                "bull": snap.bullish_count, "bear": snap.bearish_count,
                "neutral": snap.neutral_count, "trending": snap.trending,
                "sent_at": snap.timestamp, "sent_source": snap.source,
            })
        rows.append(row)
    return rows


# ---------------------------------------------------------------- coverage
def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _coverage(article, affected, now=None) -> dict | None:
    """Articles on the same instruments in the last 7 days, the top sources,
    and where this article sits in the timeline. None when the article
    names no instrument: there is nothing to count coverage OF."""
    from django.db.models import Count, Q
    from scraping.models import NewsArticle
    if not affected:
        return None
    now = now or timezone.now()
    since = now - timezone.timedelta(days=7)
    ids = (NewsArticle.objects
           .filter(ai_affected_instruments__in=affected, published_at__gte=since)
           .values_list("id", flat=True).distinct())
    ids = list(ids)
    total = len(ids)
    by_source = list(
        NewsArticle.objects.filter(id__in=ids)
        .values("source").annotate(n=Count("id")).order_by("-n", "source")[:5])
    # Rank against everything ever filed on these instruments, not the
    # 7-day window: a story first reported nine days ago is still "9th",
    # not "1st" because the earlier reports aged out.
    # Wires stamp to the minute, so two reports routinely share an
    # instant — without a tiebreak they were all "1st · FIRST".
    earlier = (NewsArticle.objects
               .filter(ai_affected_instruments__in=affected)
               .filter(Q(published_at__lt=article.published_at)
                       | Q(published_at=article.published_at,
                           id__lt=article.id))
               .exclude(id=article.id).distinct().count())
    ties = (NewsArticle.objects
            .filter(ai_affected_instruments__in=affected,
                    published_at=article.published_at)
            .exclude(id=article.id).distinct().count())
    rank = earlier + 1
    return {
        "total": total, "by_source": by_source, "ties": ties,
        "max_source": by_source[0]["n"] if by_source else None,
        "rank": rank, "rank_label": _ordinal(rank), "first": rank == 1,
    }


def _related(article, affected, limit: int = 8) -> list[dict]:
    from scraping.models import NewsArticle
    if not affected:
        return []
    qs = (NewsArticle.objects.filter(ai_affected_instruments__in=affected)
          .exclude(id=article.id).distinct().order_by("-published_at")[:limit])
    return [{
        "article": r,
        "tone": _sent_tone(r.ai_sentiment_score),
        "urgency": (r.ai_urgency or "").lower() or None,
    } for r in qs]


@login_required
def news_detail(request, pk: int):
    from scraping.models import NewsArticle
    article = get_object_or_404(NewsArticle, pk=pk)
    impact = _impact_score(article)
    sentiment = float(article.ai_sentiment_score or 0)
    sentiment_label = ("Bullish" if sentiment > 0.2 else
                       "Bearish" if sentiment < -0.2 else "Neutral")
    sentiment_pct = int(round((sentiment + 1) * 50))  # map -1..+1 → 0..100
    key_points = _extract_key_points(article.ai_summary or article.content_summary or "")
    try:
        affected = list(article.ai_affected_instruments.all()[:20])
    except Exception:
        affected = []
    try:
        related = _related(article, affected)
    except Exception:
        related = []
    try:
        instrument_rows = _instrument_rows(article, affected)
    except Exception:
        instrument_rows = []
    try:
        coverage = _coverage(article, affected)
    except Exception:
        coverage = None
    return render(request, "dashboard/news_detail.html", {
        "page_id": "news", "article": article, "impact": impact,
        "sentiment": sentiment, "sentiment_label": sentiment_label,
        "sentiment_pct": sentiment_pct, "key_points": key_points,
        "affected": affected, "related": related,
        "keywords": _extract_keywords(article),
        "facts": _reading_facts(article),
        "instrument_rows": instrument_rows,
        "coverage": coverage,
        "sentiment_measured": article.ai_sentiment_score is not None,
    })


@never_cache
@login_required
def live_metrics_json(request):
    """Lightweight polling endpoint. Frontend calls every 15s."""
    from core.context_ui import ui_extras
    ctx = ui_extras(request)
    return JsonResponse({
        "metrics": ctx.get("ui_metrics", {}),
        "headband": ctx.get("ui_headband", []),
        "watchlist": ctx.get("ui_watchlist", []),
    })
