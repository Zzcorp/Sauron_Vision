"""Metrics endpoints — v2 with sentiment trend, R-distribution, P&L bars."""
import json
from collections import Counter
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone


# ── Signals ─────────────────────────────────────────────────────────────
@login_required
def signals_metrics(request):
    ctx = {"setups": [], "totals": {}, "chart_data": "{}",
           "setup_dist": "{}", "r_hist": "{}"}
    try:
        from signals.models_smc import SmcSignal
        from signals.performance import setup_performance_summary

        active = SmcSignal.objects.filter(status__in=["ACTIVE", "TRIGGERED"])
        ctx["totals"] = {
            "active": active.count(),
            "long": active.filter(direction="LONG").count(),
            "short": active.filter(direction="SHORT").count(),
            "avg_conviction": round(
                sum(s.conviction or 0 for s in active) / max(active.count(), 1), 1
            ),
        }
        perf = setup_performance_summary(days=30)
        ctx["setups"] = [
            {"name": k, "hit_rate": v["hit_rate"], "expectancy": v["expectancy_r"],
             "n_closed": v["n_closed"], "is_empirical": v["is_empirical"]}
            for k, v in perf.items()
        ]
        # Dict order here is DB arrival order — sort so the busiest setups lead.
        ctx["setups"].sort(key=lambda r: -(r["n_closed"] or 0))

        # Chart 1: signals per day stacked long/short
        since = timezone.now() - timedelta(days=14)
        recent = SmcSignal.objects.filter(created_at__gte=since)
        per_day = {}
        for s in recent:
            day = s.created_at.date().isoformat()
            per_day.setdefault(day, {"long": 0, "short": 0})
            per_day[day]["long" if s.direction == "LONG" else "short"] += 1
        days_sorted = sorted(per_day.keys())
        ctx["chart_data"] = json.dumps({
            "labels": days_sorted,
            "long": [per_day[d]["long"] for d in days_sorted],
            "short": [per_day[d]["short"] for d in days_sorted],
        })

        # Chart 2: setup distribution donut (active signals)
        # most_common() gives one aligned (label, value) sequence, largest first.
        setup_counts = Counter(s.setup for s in active)
        setup_pairs = setup_counts.most_common()
        ctx["setup_dist"] = json.dumps({
            "labels": [k for k, _ in setup_pairs],
            "values": [v for _, v in setup_pairs],
        })

        # Chart 3: R-multiple histogram from closed signals (90d)
        closed = SmcSignal.objects.filter(
            closed_at__gte=timezone.now() - timedelta(days=90),
            realized_r__isnull=False,
        )
        bins = [-3, -2, -1, 0, 1, 2, 3, 5]
        hist = [0] * (len(bins) - 1)
        for s in closed:
            r = float(s.realized_r)
            for i in range(len(bins) - 1):
                if bins[i] <= r < bins[i + 1]:
                    hist[i] += 1
                    break
        ctx["r_hist"] = json.dumps({
            "labels": [f"{bins[i]} to {bins[i+1]}R" for i in range(len(bins) - 1)],
            "values": hist,
        })
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_signals_metrics.html", ctx)


# ── Strategies ──────────────────────────────────────────────────────────
@login_required
def strategies_metrics(request):
    ctx = {"by_status": [], "chart_data": "{}", "totals": {}, "pnl_data": "{}"}
    try:
        from strategies.models import Strategy
        all_strats = Strategy.objects.all()
        status_counts = Counter(s.status for s in all_strats)
        # Fixed lifecycle order — Counter order is arrival order, which shuffles
        # the table and chart between reloads. Zero-count statuses are skipped.
        status_order = ["active", "approved", "proposed", "completed", "paused", "rejected"]
        by_status = [
            {"status": k, "count": status_counts.get(k, 0)}
            for k in status_order if status_counts.get(k, 0)
        ]
        ctx["by_status"] = by_status
        ctx["totals"] = {
            "total": all_strats.count(),
            "active": status_counts.get("active", 0),
            "proposed": status_counts.get("proposed", 0),
            "completed": status_counts.get("completed", 0),
        }
        ctx["chart_data"] = json.dumps({
            "labels": [r["status"] for r in by_status],
            "values": [r["count"] for r in by_status],
        })
        # Per-strategy P&L bar (uses any 'realized_pnl' or 'pnl' field if present)
        labels = []
        values = []
        for s in all_strats[:20]:
            pnl = getattr(s, "realized_pnl", None) or getattr(s, "pnl", None) or 0
            try:
                pnl = float(pnl)
            except (ValueError, TypeError):
                pnl = 0
            if pnl != 0:
                labels.append((s.name or f"#{s.id}")[:24])
                values.append(round(pnl, 2))
        ctx["pnl_data"] = json.dumps({"labels": labels, "values": values})
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_strategies_metrics.html", ctx)


# ── News & sentiment ────────────────────────────────────────────────────
@login_required
def news_metrics(request):
    ctx = {"totals": {}, "chart_data": "{}", "sentiment_data": "{}",
           "current_sentiment": None}
    try:
        from scraping.models import NewsItem
        since = timezone.now() - timedelta(days=14)
        # NewsItem may not have published_at; tolerate both
        ts_field = None
        for f in ("published_at", "created_at", "scraped_at", "timestamp"):
            if hasattr(NewsItem, f):
                ts_field = f
                break
        if ts_field is None:
            ctx["totals"]["count_14d"] = 0
            return render(request, "dashboard/_news_metrics.html", ctx)

        items = list(NewsItem.objects.filter(**{f"{ts_field}__gte": since}).order_by(ts_field))
        ctx["totals"]["count_14d"] = len(items)

        per_day = {}
        sentiment_per_day = {}
        for n in items:
            ts = getattr(n, ts_field) or timezone.now()
            day = ts.date().isoformat()
            per_day[day] = per_day.get(day, 0) + 1
            score = getattr(n, "ai_sentiment_score", None)
            if score is not None:
                try:
                    score_f = float(score)
                except (ValueError, TypeError):
                    continue
                sentiment_per_day.setdefault(day, []).append(score_f)

        days_sorted = sorted(per_day.keys())
        ctx["chart_data"] = json.dumps({
            "labels": days_sorted,
            "values": [per_day[d] for d in days_sorted],
        })

        # Sentiment trend: average per day, only days with data
        sent_days = [d for d in days_sorted if d in sentiment_per_day]
        sent_values = [
            round(sum(sentiment_per_day[d]) / len(sentiment_per_day[d]), 3)
            for d in sent_days
        ]
        ctx["sentiment_data"] = json.dumps({
            "labels": sent_days, "values": sent_values,
        })
        if sent_values:
            current = sent_values[-1]
            ctx["current_sentiment"] = current
            ctx["totals"]["sentiment_label"] = (
                "BULLISH" if current > 0.2
                else "BEARISH" if current < -0.2
                else "NEUTRAL"
            )
    except Exception as e:
        ctx["error"] = str(e)
        ctx["totals"]["count_14d"] = 0
    return render(request, "dashboard/_news_metrics.html", ctx)


# ── Backtest ────────────────────────────────────────────────────────────
@login_required
def backtest_metrics(request):
    ctx = {"runs": [], "chart_data": "{}"}
    try:
        from backtester.models_v2 import BacktestRunV2
        recent = BacktestRunV2.objects.all()[:10]
        ctx["runs"] = list(recent)
        if recent:
            latest = recent[0]
            curve = latest.equity_curve or []
            ctx["chart_data"] = json.dumps({
                "labels": [str(p.get("ts", i)) for i, p in enumerate(curve)],
                "equity": [p.get("equity", 0) for p in curve],
                "name": latest.name,
            })
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_backtest_metrics.html", ctx)


# ── Portfolio ───────────────────────────────────────────────────────────
@login_required
def portfolio_metrics(request):
    ctx = {"exposure": {}, "chart_data": "{}"}
    try:
        from strategies.portfolio_analyzer import analyze_exposure
        from portfolio.services import get_or_create_default_portfolio
        # `Portfolio` has NO user column — ownership is carried by the name,
        # which is why `get_or_create_default_portfolio` exists. The previous
        # `Portfolio.objects.filter(user=request.user)` therefore raised
        # FieldError into the bare except below on every single request, and
        # the panel rendered empty forever — the same failure Position
        # Analytics was fixed for, in the panel directly beside it.
        portfolio = get_or_create_default_portfolio(user=request.user)
        if portfolio:
            exposure = analyze_exposure(portfolio)
            ctx["exposure"] = exposure
            asset_break = exposure.get("by_asset_class", {})
            ctx["chart_data"] = json.dumps({
                "labels": list(asset_break.keys()),
                "values": [round(v * 100, 2) for v in asset_break.values()],
            })
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_portfolio_metrics.html", ctx)


# ── Positions ───────────────────────────────────────────────────────────

#: How many bars a card gets before the tick row is ellipsising to nothing.
#: The series that hit this are per-position, so the cap is a display limit
#: and the caption says how many rows it left out.
_POSITION_BARS = 12

#: R buckets for the open book, half-open [lo, hi). A position sitting
#: exactly at entry is 0.0R and belongs at the bottom of the winning side,
#: not with the losers — and `None` on either end means unbounded, so the
#: two tail buckets catch the outliers instead of dropping them.
# Half-open [low, high), so every R lands in exactly one bucket and a
# position sitting at entry falls in "0 to +1R".
#
# The labels say "under" and "over", not "<=" and ">=". The first bucket
# holds r < -2.0, so a position at exactly -2.00R is in the SECOND — and a
# label reading "<= -2R" claimed a boundary it did not hold, which showed a
# measured zero in the tail-risk bucket while the operator was carrying a
# position at exactly -2R. R is rounded to two places upstream, so exact
# boundary values are ordinary, not exotic.
_R_BUCKETS = (
    ("under -2R", None, -2.0, "red"),
    ("-2 to -1R", -2.0, -1.0, "red"),
    ("-1 to 0R", -1.0, 0.0, "red"),
    ("0 to +1R", 0.0, 1.0, "accent"),
    ("+1 to +2R", 1.0, 2.0, "accent"),
    ("+2R and over", 2.0, None, "accent"),
)


def _age_text(hours):
    """A holding period at the precision a person reads it at.

    Minutes below the hour, then hours, then days: "0.0d" for a position
    opened forty minutes ago is a rounding artefact that reads as "brand
    new" on a book where a fresh entry is exactly the thing worth seeing.
    """
    if hours < 1:
        return "{:.0f}m".format(hours * 60)
    if hours < 48:
        return "{:.1f}h".format(hours)
    return "{:.1f}d".format(hours / 24)


def _median(values):
    """Middle value of a non-empty list; the caller owns the empty case,
    because "no median" and "a median of zero" are different answers."""
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _exposure_shares(by_key):
    """{key: notional} → donut rows, largest slice first.

    No `n` on the rows on purpose: these are shares of a VALUE, and the
    donut legend prints "n · pct" when it is given one — which would read
    as though the percentage divided the position count rather than the
    money. The count lives in the caption underneath instead.
    """
    total = sum(by_key.values())
    if total <= 0:
        return []
    return sorted(
        ({"key": key, "pct": round(value / total * 100, 1)}
         for key, value in by_key.items() if value > 0),
        key=lambda row: -row["pct"])


@login_required
def positions_metrics(request):
    """Position Analytics under /positions/ — the OPEN book, both halves.

    This panel had never rendered a single number. It filtered
    `Position.objects.filter(portfolio=..., is_open=True)`, and
    portfolio.Position has no `is_open` — an open row is one whose
    `closed_at` is null — so every request raised FieldError. A bare
    `except Exception` around the whole body then caught it and rendered
    the empty state, which is why a permanently broken query was
    indistinguishable from a book with nothing in it. Its third defect was
    the book itself: it read `Portfolio.objects.filter(user=...)`, and the
    pipeline maintains the shared "Main" portfolio while every interactive
    trade writes bot_program.AssetBotTrade — so even a valid query would
    have described a third place that is always empty.

    The read now goes through views._live_open_book, which wraps
    views_command._open_book — the platform's one union of the two position
    books, with the legacy half re-priced in memory — and denominates R by
    the stop each position OPENED with. Same rows as the table above this
    panel, so the two cannot quote different numbers for the same position.

    What it shows is deliberately not that table again: where the money is
    concentrated, how the book is spread across R, which way and into what
    the exposure leans, and how long it has been sitting.
    """
    import logging

    from portfolio.services import get_or_create_default_portfolio
    from .views import (LIVE_DASH, _as_float, _live_num, _live_open_book,
                        _live_tone)

    logger = logging.getLogger(__name__)
    ctx = {
        "error": "", "n_open": 0, "strip": [],
        "pnl_bars": [], "pnl_max": 0, "pnl_peak": "", "pnl_note": "",
        "r_bars": [], "r_max": 0, "r_peak": "", "r_note": "",
        "dir_rows": [], "class_rows": [], "exposure_note": "",
        "age_bars": [], "age_max": 0, "age_peak": "", "age_note": "",
        "oldest": [],
    }

    try:
        # The OPERATOR'S OWN book — the same one the positions table this
        # panel sits underneath now reads. It used to take the shared "Main"
        # row, on the reasoning that Main was the only book the pipeline
        # marked and snapshotted; that stopped being true when
        # recalculate_exposure and create_daily_snapshot began walking every
        # portfolio, and the consequence in the meantime was two panels on
        # one screen counting two different books.
        portfolio = get_or_create_default_portfolio(user=request.user)
        rows, n_priced = _live_open_book(request.user, portfolio)[1:3]
    except Exception as e:
        # Said out loud, in the panel and in the log. The predecessor put
        # the exception string in ctx["error"] and the template never
        # rendered it, so a FieldError on every single request looked
        # exactly like an empty book — for as long as nobody opened a
        # shell to ask.
        logger.error("Position analytics could not read the open book: %s",
                     e, exc_info=True)
        ctx["error"] = (
            "The open position book could not be read, so nothing here is "
            "measured. The reason is in the server log.")
        return render(request, "dashboard/_positions_metrics.html", ctx)

    ctx["n_open"] = n_open = len(rows)
    if not n_open:
        return render(request, "dashboard/_positions_metrics.html", ctx)

    now = timezone.now()

    # ── One pass over the book ───────────────────────────────────────
    # Exposure is NOTIONAL — quantity x price — sized at the live mark
    # where there is one and at entry cost otherwise. A row valued at zero
    # because no quote arrived would silently shrink the book, and this is
    # the same convention the asset-class table above this panel applies,
    # so the two agree on what the book is worth.
    gross = 0.0
    n_at_cost = 0
    by_symbol: dict = {}
    by_direction: dict = {}
    by_class: dict = {}
    aged = []
    for p in rows:
        mark = _as_float(p["current_price"])
        if mark is None:
            n_at_cost += 1
        price = mark if mark is not None else _as_float(p["entry_price"])
        exposure = abs(_as_float(p["quantity"]) or 0.0) * abs(price or 0.0)
        gross += exposure

        symbol = p["symbol"] or "?"
        agg = by_symbol.setdefault(
            symbol, {"pnl": None, "n": 0, "n_priced": 0, "exposure": 0.0})
        agg["n"] += 1
        agg["exposure"] += exposure
        # None survives until the first priced row in the symbol: a symbol
        # nothing could mark has an UNKNOWN P&L, and seeding the sum at 0.0
        # would draw it flat next to symbols that really are.
        #
        # n_priced is counted alongside because "some of this symbol could
        # be marked" is a THIRD state, and it was being drawn as the first.
        # Options are the reachable case: portfolio.services stores the
        # UNDERLYING in AssetBotTrade.symbol and deliberately leaves every
        # options row unpriced, so an equity holding and an option on the
        # same underlying share one key here. Summing only the priced legs
        # and presenting the total as measured counts the unpriced leg as
        # zero — the exact failure this panel exists to refuse.
        if p["unrealized_pnl"] is not None:
            agg["pnl"] = (agg["pnl"] or 0.0) + p["unrealized_pnl"]
            agg["n_priced"] += 1

        side = ("long" if (p["direction"] or "").lower() in ("long", "buy")
                else "short")
        by_direction[side] = by_direction.get(side, 0.0) + exposure
        asset_class = p["asset_class"] or "other"
        by_class[asset_class] = by_class.get(asset_class, 0.0) + exposure

        if p["opened_at"] is not None:
            # Clamped at zero: a clock that ran backwards must not hand the
            # bar chart a negative height, which is an SVG error and not a
            # short position.
            aged.append((max(0.0, (now - p["opened_at"]).total_seconds()
                             / 3600.0), p))

    r_values = [p["r_multiple"] for p in rows if p["r_multiple"] is not None]

    # ── Unrealized P&L by symbol ─────────────────────────────────────
    # Ranked by MAGNITUDE, so the biggest loser is as visible as the
    # biggest winner; symbols nothing could price sort last and are handed
    # over with value None, which the bars partial draws as an explicit
    # "not measured" marker rather than as a flat zero.
    ranked = sorted(by_symbol.items(),
                    key=lambda kv: (kv[1]["pnl"] is None,
                                    -abs(kv[1]["pnl"] or 0.0)))
    ctx["pnl_bars"] = [
        {"label": symbol[:9], "value": agg["pnl"],
         "display": _live_num(agg["pnl"]),
         # Three states, three notes. A PARTIALLY priced symbol used to
         # read exactly like a fully priced one, so a bar drawn from two
         # of three legs claimed to be the symbol's whole P&L. The count
         # is part of every note — an earlier form put the ternary around
         # the whole format() and dropped it from the unpriced case.
         "note": "{} position{}{}".format(
             agg["n"],
             "" if agg["n"] == 1 else "s",
             ", none priced" if agg["pnl"] is None
             else ("" if agg["n_priced"] == agg["n"]
                   else ", {} of {} priced".format(agg["n_priced"], agg["n"])))}
        for symbol, agg in ranked[:_POSITION_BARS]
    ]
    pnl_max = max((abs(agg["pnl"]) for _s, agg in ranked
                   if agg["pnl"] is not None), default=0)
    ctx["pnl_max"] = pnl_max
    ctx["pnl_peak"] = _live_num(pnl_max, "{:,.2f}") if pnl_max else ""
    ctx["pnl_note"] = (
        "{} symbol{} in the book, {} plotted · {} of {} rows carry a live "
        "mark".format(len(by_symbol), "" if len(by_symbol) == 1 else "s",
                      min(len(by_symbol), _POSITION_BARS), n_priced, n_open))

    # ── R distribution across the open book ──────────────────────────
    if r_values:
        counts = [0] * len(_R_BUCKETS)
        for r in r_values:
            for i, (_label, low, high, _tone) in enumerate(_R_BUCKETS):
                if (low is None or r >= low) and (high is None or r < high):
                    counts[i] += 1
                    break
        # A bucket nobody landed in really does hold zero positions — that
        # is a measurement, so it stays 0 and draws as an empty slot above
        # the baseline rather than as the partial's "unknown" marker.
        ctx["r_bars"] = [
            {"label": label, "value": counts[i], "tone": tone,
             "display": "{} open".format(counts[i])}
            for i, (label, _low, _high, tone) in enumerate(_R_BUCKETS)
        ]
        ctx["r_max"] = max(counts)
        ctx["r_peak"] = "{} position{} in one bucket".format(
            max(counts), "" if max(counts) == 1 else "s")
    ctx["r_note"] = (
        "{} of {} open positions carry an R. The rest have no entry stop "
        "recorded or no live mark, so there is no risk to divide the move "
        "by — they are left out rather than counted at 0.0R.".format(
            len(r_values), n_open))

    # ── Exposure, by direction and by asset class ────────────────────
    ctx["dir_rows"] = _exposure_shares(by_direction)
    ctx["class_rows"] = _exposure_shares(by_class)
    ctx["exposure_note"] = (
        "{:,.0f} notional across {} position{}{}".format(
            gross, n_open, "" if n_open == 1 else "s",
            "" if not n_at_cost else
            " · {} sized at entry cost, no quote arrived".format(n_at_cost)))

    # ── Age / time held ──────────────────────────────────────────────
    # Four decimals, not two: a position taken a minute ago is 0.0167h, and
    # rounding it to 0.0 makes it FALSY — the bars partial would then draw
    # nothing for the newest entry on the book, which is the one an
    # operator is most likely to be looking for.
    aged.sort(key=lambda row: -row[0])
    ctx["age_bars"] = [
        {"label": p["symbol"][:9], "value": round(hours, 4),
         "display": _age_text(hours), "tone": "blue",
         "note": "{} · {}".format(p["direction"], p["asset_class"])}
        for hours, p in aged[:_POSITION_BARS]
    ]
    age_max = max((hours for hours, _p in aged), default=0)
    ctx["age_max"] = round(age_max, 4)
    ctx["age_peak"] = _age_text(age_max) if aged else ""
    ctx["age_note"] = (
        "{} of {} open position{} plotted, oldest first{}".format(
            min(len(aged), _POSITION_BARS), n_open,
            "" if n_open == 1 else "s",
            "" if len(aged) == n_open else
            " · {} carry no open time and cannot be aged".format(
                n_open - len(aged))))
    ctx["oldest"] = [
        {"symbol": p["symbol"], "direction": p["direction"],
         "asset_class": p["asset_class"], "age_text": _age_text(hours),
         "r_text": _live_num(p["r_multiple"], "{:+.2f}R"),
         "r_tone": _live_tone(p["r_multiple"])}
        for hours, p in aged[:5]
    ]

    # ── The strip ────────────────────────────────────────────────────
    # Five readings the table above this panel does not carry. None of
    # them repeats the page's own stat strip, which already prints open
    # count, unrealized P&L and exposure.
    sum_r = round(sum(r_values), 2) if r_values else None
    bias_pct = (round(by_direction.get("long", 0.0) / gross * 100, 1)
                if gross > 0 else None)
    top_symbol, top_agg = max(by_symbol.items(),
                              key=lambda kv: kv[1]["exposure"])
    concentration = (round(top_agg["exposure"] / gross * 100, 1)
                     if gross > 0 else None)
    median_hours = _median([hours for hours, _p in aged]) if aged else None
    ctx["strip"] = [
        {"label": "OPEN R", "text": _live_num(sum_r, "{:+.2f}R"),
         "tone": _live_tone(sum_r),
         "sub": "{} of {} graded".format(len(r_values), n_open),
         "title": ("Live R summed across the open book, each position "
                   "measured against the stop it opened with. Positions "
                   "with no recorded entry stop or no mark are left out.")},
        {"label": "NET BIAS", "tone": "",
         "text": _live_num(bias_pct, "{:.0f}% long"),
         "sub": "of notional exposure",
         "title": ("Long share of gross notional — by MONEY, not by "
                   "position count, which is what the direction donut at "
                   "the top of this page divides.")},
        {"label": "CONCENTRATION", "tone": "",
         "text": _live_num(concentration, "{:.0f}%"),
         "sub": "in {}".format(top_symbol),
         "title": ("Largest single symbol as a share of gross notional. "
                   "{} of {} positions are in {}.".format(
                       top_agg["n"], n_open, top_symbol))},
        {"label": "MEDIAN AGE", "tone": "",
         "text": _age_text(median_hours) if median_hours is not None
                 else LIVE_DASH,
         "sub": "half the book is older",
         "title": ("Median time held across every position that records "
                   "when it opened.")},
        {"label": "OLDEST", "tone": "",
         "text": _age_text(age_max) if aged else LIVE_DASH,
         "sub": aged[0][1]["symbol"] if aged else "",
         "title": ("The position that has been on longest. A book whose "
                   "oldest row keeps growing is one nothing is closing.")},
    ]

    return render(request, "dashboard/_positions_metrics.html", ctx)
