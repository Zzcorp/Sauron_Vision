"""News risk per asset class — a tighten-only input to the share allocator.

Two legs. Leg A is the news analyst's own grading: articles published in
the window whose `ai_sentiment_score` is set, joined through the
instruments the analyst tagged to their asset class, one count per
article per class (an article on AAPL and MSFT is ONE stock article).
Rows the analyst could not parse (`ai_summary == 'Failed to parse AI
response'`) are excluded: the parser's fallback stamps a sentiment of
0.0 and a low urgency, which would drag every class's average toward
neutral and hide a bad tape. Leg C is the macro calendar: high-impact
`fmp_macro` events in the NEXT 24h, per currency — forex is exposed when
the currency is a leg of any active pair, everything else to USD events.

Leg A goes BLIND when the analyst is idle: `Max(ai_processed_at)` None
or older than 2h means the scores on file describe a tape nobody has
read since, and the allocator treats blind as neutral (1.0) with the
reason recorded. Blind is never a good score — it is no score. The
allocator maps the numbers here to a factor; this module only measures.

Pure DB reads, no broker I/O (2026-09-12).
"""
from datetime import timedelta

from django.utils import timezone

FAILED_PARSE_SUMMARY = "Failed to parse AI response"
# The analyst runs every 5 minutes when on; 2h idle is a stopped agent,
# not a quiet news day.
ANALYST_IDLE_SECONDS = 2 * 3600
URGENT_LEVELS = ("critical", "high")
MACRO_SOURCE = "fmp_macro"


def _classes():
    from core.constants import AssetClass
    return [ac for ac, _label in AssetClass.CHOICES]


def news_risk_by_class(now=None, window_hours=24, min_articles=3) -> dict:
    """{asset_class: {n_graded, avg_sent, n_urgent, events_24h, blind,
                      reason}} for every asset class the platform knows.

    `avg_sent` is None below `min_articles` (too thin to state) and the
    allocator applies the sentiment term only above it. `events_24h` is
    the count of high-impact macro events in the next 24h this class is
    exposed to, and it is counted whether or not leg A is blind.
    """
    from django.db.models import Max

    from instruments.models import Instrument
    from market_data.models import EconomicEvent
    from scraping.models import NewsArticle

    now = now or timezone.now()
    since = now - timedelta(hours=window_hours)
    out = {ac: {"n_graded": 0, "avg_sent": None, "n_urgent": 0,
                "events_24h": 0, "blind": False, "reason": ""}
           for ac in _classes()}

    # ── Leg A: the analyst's grading, gated on the analyst being awake ──
    last = NewsArticle.objects.aggregate(m=Max("ai_processed_at"))["m"]
    idle = (last is None
            or (now - last).total_seconds() > ANALYST_IDLE_SECONDS)
    if idle:
        when = f"{last:%Y-%m-%d %H:%M} UTC" if last else "ever"
        for slot in out.values():
            slot["blind"] = True
            slot["reason"] = f"news analyst idle since {when}"
    else:
        rows = (NewsArticle.objects
                .filter(ai_sentiment_score__isnull=False,
                        published_at__gte=since, published_at__lte=now)
                .exclude(ai_summary=FAILED_PARSE_SUMMARY)
                .values_list("id", "ai_sentiment_score", "ai_urgency",
                             "ai_affected_instruments__asset_class"))
        seen: dict = {}
        for art_id, sent, urgency, ac in rows:
            if ac is None:
                continue                       # an article tagged to nothing
            bucket = seen.setdefault(ac, {})
            bucket[art_id] = (float(sent), (urgency or "").lower())
        for ac, arts in seen.items():
            slot = out.setdefault(ac, {"n_graded": 0, "avg_sent": None,
                                       "n_urgent": 0, "events_24h": 0,
                                       "blind": False, "reason": ""})
            n = len(arts)
            slot["n_graded"] = n
            slot["n_urgent"] = sum(1 for _s, u in arts.values()
                                   if u in URGENT_LEVELS)
            if n >= min_articles:
                slot["avg_sent"] = sum(s for s, _u in arts.values()) / n
                slot["reason"] = (f"{n} graded articles in {window_hours}h, "
                                  f"avg sentiment {slot['avg_sent']:+.2f}")
            else:
                slot["reason"] = (f"{n} graded article(s) in {window_hours}h "
                                  f"— below {min_articles}, sentiment not "
                                  f"stated")
        for ac, slot in out.items():
            if not slot["reason"]:
                slot["reason"] = f"no graded articles in {window_hours}h"

    # ── Leg C: the macro calendar, next 24h, per currency ───────────────
    events = (EconomicEvent.objects
              .filter(source=MACRO_SOURCE, impact__iexact="high",
                      datetime__gte=now, datetime__lte=now + timedelta(hours=24))
              .values_list("currency_affected", flat=True))
    by_ccy: dict = {}
    for ccy in events:
        key = (ccy or "").upper()
        by_ccy[key] = by_ccy.get(key, 0) + 1
    if by_ccy:
        pairs = [s.upper() for s in Instrument.objects
                 .filter(is_active=True, asset_class="forex")
                 .values_list("symbol", flat=True)]
        for ac, slot in out.items():
            if ac == "forex":
                if pairs:
                    n = sum(cnt for ccy, cnt in by_ccy.items()
                            if ccy and any(ccy in p for p in pairs))
                else:
                    n = sum(by_ccy.values())
            else:
                n = by_ccy.get("USD", 0)
            slot["events_24h"] = n
            if n:
                slot["reason"] = (slot["reason"] + "; " if slot["reason"]
                                  else "") + f"{n} high-impact macro event(s) in 24h"
    return out
