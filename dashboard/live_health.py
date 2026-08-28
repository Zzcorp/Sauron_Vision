"""Streamer health endpoint — reports every declared feed, not just the
ones that happen to have written.

The old version grouped `LiveQuote.source` and reported what it found. See
`market_data/feeds.py` for why that could not say the three things the
operator most needed: a feed with no credentials was ABSENT rather than off,
a feed outranked on every instrument VANISHED rather than yielding, and a
feed whose market is shut went RED every night rather than idle.
"""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache


@never_cache
@login_required
def live_health(request):
    """Freshness and configuration for every feed this platform declares.

    Each row carries `state` from the vocabulary in `market_data.feeds`,
    plus `configured`, a human `label` and a one-line `note` saying what the
    state means. The aggregate `pill` is computed here rather than in the
    browser: the client used to derive it with a pessimistic dot (any red
    wins) and an optimistic label (any green wins), so one green feed among
    five red ones painted a red dot beside the word LIVE.
    """
    from django.db.models import Max

    from market_data.feeds import BY_KEY, BENIGN_STATES, FEEDS, is_configured
    from market_data.models import LiveQuote

    try:
        now = timezone.now()

        # ONE verdict, shared with the digest and the health page. Three
        # copies of this loop existed and had already drifted: the digest
        # walked the registry (so a never-delivering feed was caught) while
        # the health page grouped by rows that had been written (so it was
        # not), and the digest mailed an alarm linking to a page that said
        # everything was fine.
        from market_data.feeds import feed_states

        sources = [{
            "source": r["source"], "label": r["label"], "kind": r["kind"],
            "configured": r["configured"], "state": r["state"],
            "note": r["note"], "age_seconds": r["age_seconds"],
            "latest": r["latest"].isoformat() if r["latest"] else None,
        } for r in feed_states(now)]

        # Declared order first, then the strays — the operator reads the
        # same list in the same order every time, which is what makes a
        # changed dot noticeable.
        watched = [s for s in sources
                   if s["state"] not in BENIGN_STATES
                   and s["state"] != "unregistered"]
        live = [s for s in watched if s["state"] == "green"]

        # ONE verdict, and the word is derived from the dot rather than
        # computed beside it. The client used to reach these separately —
        # a pessimistic dot (any red wins) and an optimistic label (any
        # green wins) — so one green feed among five dead ones painted a
        # red dot next to the word LIVE. Deriving the second from the first
        # is what makes that shape impossible rather than merely fixed.
        if not watched:
            pill_state = "flat"
        elif len(live) == len(watched):
            pill_state = "green"
        elif live or any(s["state"] == "yellow" for s in watched):
            pill_state = "yellow"
        else:
            pill_state = "red"
        pill = {"green": "live", "yellow": "degraded",
                "red": "offline", "flat": "idle"}[pill_state]

        from market_data.models import FundingRate, LiquidationEvent
        try:
            last_liq = (LiquidationEvent.objects.order_by("-timestamp")
                        .values_list("timestamp", flat=True).first())
            last_fund = (FundingRate.objects.order_by("-timestamp")
                         .values_list("timestamp", flat=True).first())
        except Exception:  # noqa: BLE001
            last_liq = last_fund = None

        return JsonResponse({
            "sources": sources,
            "pill": pill,
            "pill_state": pill_state,
            "watched": len(watched),
            "last_liquidation_age": ((now - last_liq).total_seconds()
                                     if last_liq else None),
            "last_funding_age": ((now - last_fund).total_seconds()
                                 if last_fund else None),
        })
    except Exception as e:  # noqa: BLE001 — a health panel must never 500
        return JsonResponse({"error": str(e), "sources": [],
                             "pill": "offline", "pill_state": "flat"},
                            status=200)
