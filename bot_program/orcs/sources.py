"""THE DOSSIER'S READERS (spec §5.2a): every number the platform already
holds about the day, read as of a moment, each returned as

    {"value": ..., "dash": ""}       or       {"value": None, "dash": "— (why)"}

so a missing input prints a dash with its reason and is never a zero
("unknown is not zero"). Every reader is fenced: it never raises. Reads
only; nothing here writes, sends, or calls a model.

  board_session   MK2: a board symbol's 1h bars inside a session, as % from
                  the day's open, its range in ATR(1h), its PO3 phase; any
                  source, labelled (the venue's first)
  posture         MK4: the stress reading in force at a moment; with
                  `crisis_mode` OFF it is never measured (market_stress is
                  read by a task that switch gates): "— (not measured:
                  crisis_mode off)"
  vix_term, fred  MK5: VIX/VIX3M (market_stress._vix_term) and FRED series
                  fresh within 5 days
  calendar        MK6, MK-now, IN11: high-impact prints in a window; an
                  unread calendar says so (unlike upcoming_events, which
                  reads as empty)
  mind, brief,    MK7, MK8, MK9: the Mind's report BY ITS ID (persona_mix.
  horizon         latest_report gives only the id and the age), the
                  strategist's brief, the Horizon's tilts
  headlines       MK12, IN9: the TITLE and the analyst's tags only; a news
                  body and the analyst's summary are never loaded (a filter
                  on the parser's failure sentinel loads no text)
  analyst_blind   news_risk's idle rule (2 h)
  quote, book,    the board's live move (LiveQuote), the book as SHARES of
  correlation     its limits (never money), the measured correlations
  actuals_measurement   how many past high-impact prints carry an actual
"""
import logging
import math
from datetime import timedelta

from bot_program.orcs import fence
from bot_program.orcs.constants import FENCE_CAPS

logger = logging.getLogger(__name__)

US10Y_DASH = ("— (no instrument for US10Y; the 10-year yield is DGS10 in the "
              "macro line)")
STRESS_DASH = "— (not measured: crisis_mode off)"
CALENDAR_DASH = "— (calendar unread)"
FRED_FRESH_DAYS = 5
MIND_FRESH_MIN = 75
BRIEF_MAX_H = 30
POSTURE_FRESH_H = 2.0
BOARD_ATR_BARS = 15
#: FRED series MK5 prints (core/constants.py FRED list).
MK5_SERIES = ("VIXCLS", "BAMLH0A0HYM2", "DGS2", "DGS10", "T10Y2Y")


def ok(value) -> dict:
    return {"value": value, "dash": ""}


def dash(why) -> dict:
    why = str(why or "unread")
    return {"value": None, "dash": why if why.startswith("—")
            else f"— ({why})"}


def shown(out):
    """The value, or its dash."""
    return out["value"] if not out.get("dash") else out["dash"]


def _f(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _hhmm(at) -> str:
    try:
        return f"{at:%H:%M}"
    except (TypeError, ValueError):
        return "--:--"


def _utc(at) -> str:
    try:
        return f"{at:%Y-%m-%d %H:%M} UTC"
    except (TypeError, ValueError):
        return "an unread time"


def _pct(x, base) -> str:
    return f"{100.0 * (x - base) / base:+.2f}%"


# ── MK2: the board ───────────────────────────────────────────────────────

def _instrument(symbol):
    from instruments.models import Instrument
    return Instrument.objects.filter(symbol=symbol).first()


def _bars_between(inst, start, end, *, source=None):
    from market_data.models import PriceData
    qs = PriceData.objects.filter(instrument=inst, timeframe="1h",
                                  timestamp__gte=start,
                                  timestamp__lte=end - timedelta(hours=1))
    if source:
        qs = qs.filter(source=source)
    return list(qs.order_by("timestamp").values(
        "timestamp", "open", "high", "low", "close", "source"))


def _source_in(inst, start, end):
    """The venue's own bars when it holds any in the window, else the
    newest other source: one source, never mixed."""
    from market_data.models import PriceData
    qs = PriceData.objects.filter(instrument=inst, timeframe="1h",
                                  timestamp__gte=start,
                                  timestamp__lte=end - timedelta(hours=1))
    if qs.filter(source="etoro").exists():
        return "etoro"
    return (qs.order_by("-timestamp").values_list("source", flat=True)
            .first())


def board_session(symbol, start, end, *, day_open_at=None) -> dict:
    """MK2 for one board symbol over [start, end): open, high, low, close
    as % from the trading day's open (o, h, l, c), the range in ATR(1h),
    the source, the last bar's time and the PO3 phase at `end`. Stale past
    two 1h bars: a dash with the last bar's time."""
    try:
        if symbol == "US10Y":
            return dash(US10Y_DASH)
        inst = _instrument(symbol)
        if inst is None:
            return dash(f"no instrument for {symbol}")
        source = _source_in(inst, day_open_at or start, end)
        rows = _bars_between(inst, start, end, source=source) if source \
            else []
        last = None
        if rows:
            last = rows[-1]["timestamp"] + timedelta(hours=1)
        if not rows or (end - last) > timedelta(hours=2):
            from market_data.models import PriceData
            newest = (PriceData.objects.filter(
                instrument=inst, timeframe="1h",
                timestamp__lte=end - timedelta(hours=1))
                .order_by("-timestamp").values_list("timestamp", flat=True)
                .first())
            if newest is None:
                return dash("no fresh 1h bar")
            return dash(f"no fresh 1h bar since "
                        f"{_utc(newest + timedelta(hours=1))}")
        first = _bars_between(inst, day_open_at or start, end,
                              source=source)[:1] or rows[:1]
        base = _f(first[0]["open"]) or _f(rows[0]["open"])
        hi = max(_f(r["high"]) or 0 for r in rows)
        lo = min(_f(r["low"]) or 0 for r in rows)
        o, c = _f(rows[0]["open"]), _f(rows[-1]["close"])
        # short keys: eleven symbols a session, six sessions a day
        out = {"o": _pct(o, base), "h": _pct(hi, base),
               "l": _pct(lo, base), "c": _pct(c, base),
               "src": "etoro" if source == "etoro" else "platform",
               "last": _hhmm(last)}
        atr = _atr_until(symbol, end, source)
        out["rng_atr"] = (f"{(hi - lo) / atr:.1f}" if atr
                          else "— (no ATR(1h))")
        out["po3"] = _po3_at(symbol, end)
        return ok(out)
    except Exception as e:  # noqa: BLE001 — an unread board row is a dash
        logger.info("[orcs] board %s unread: %s", symbol, e)
        return dash(f"unread: {type(e).__name__}")


def _atr_until(symbol, end, source):
    from market_data.models import PriceData
    rows = list(PriceData.objects
                .filter(instrument__symbol=symbol, timeframe="1h",
                        source=source, timestamp__lte=end - timedelta(hours=1))
                .order_by("-timestamp")
                .values_list("high", "low", "close")[:BOARD_ATR_BARS + 1])
    rows.reverse()
    if len(rows) < 3:
        return None
    trs = []
    for (h, lo, _c), (_h0, _l0, c0) in zip(rows[1:], rows):
        h, lo, c0 = float(h), float(lo), float(c0)
        trs.append(max(h - lo, abs(h - c0), abs(lo - c0)))
    atr = sum(trs) / len(trs) if trs else 0.0
    return atr if atr > 0 else None


def _po3_at(symbol, end) -> str:
    """The day's three parts at `end`, read on the bars complete then (no
    look-ahead)."""
    try:
        from bot_program import power_of_three as po3
        from bot_program.orcs import bars
        f = bars.frame(symbol, "1h", now=end, until=end)
        if f is None:
            return "unread: no 1h bars"
        day = po3.power_of_three(symbol, now=end,
                                 bars=(f.df, f.swings, "1h"))
        if not day.get("ok"):
            return f"unread: {fence.sanitize(day.get('why') or '', 60)}"
        direction = day.get("direction") or ""
        return f"{day.get('phase')}{' ' + direction if direction else ''}"
    except Exception as e:  # noqa: BLE001
        return f"unread: {type(e).__name__}"


# ── MK4, MK5: the posture and the macro line ─────────────────────────────

def _crisis_on() -> bool:
    try:
        from core.platform_control import is_component_enabled
        return bool(is_component_enabled("crisis_mode"))
    except Exception:  # noqa: BLE001
        return False


def posture(at) -> dict:
    """The stress reading in force at `at` (level, score, words), fresh
    within 2 h; else a dash. With crisis_mode OFF the posture is never
    measured (bot_program/tasks.py read_market_stress is gated by it)."""
    try:
        from bot_program.aragorn_models import MarketStressReading
        from bot_program.market_stress import POSTURE_WORDS
        r = (MarketStressReading.objects.filter(at__lte=at)
             .order_by("-at").first())
        if r is None or (at - r.at) > timedelta(hours=POSTURE_FRESH_H):
            if not _crisis_on():
                return dash(STRESS_DASH)
            if r is None:
                return dash("no stress reading yet")
            hours = (at - r.at).total_seconds() / 3600.0
            return dash(f"stale: last reading {hours:.0f} h old")
        return ok({"level": r.level,
                   "score": (f"{r.score:.0f}" if r.score is not None
                             else "—"),
                   "words": POSTURE_WORDS.get(r.level, ""),
                   "at": _hhmm(r.at), "fresh": True})
    except Exception as e:  # noqa: BLE001
        return dash(f"posture unread: {type(e).__name__}")


def posture_changed_h(at, since) -> object:
    """Hours since the posture's level last changed, when it changed after
    `since` (the roll), else None."""
    try:
        from bot_program.aragorn_models import MarketStressReading
        rows = list(MarketStressReading.objects.filter(at__lte=at)
                    .order_by("-at").values_list("at", "level")[:50])
        for (t1, l1), (_t0, l0) in zip(rows, rows[1:]):
            if l1 != l0:
                return ((at - t1).total_seconds() / 3600.0
                        if t1 >= since else None)
    except Exception:  # noqa: BLE001
        return None
    return None


def vix_term(at) -> dict:
    try:
        from bot_program.market_stress import _vix_term
        v = _vix_term(at)
        if v is None:
            return dash("VIX/VIX3M unread within 5 days")
        return ok(f"{float(v):.2f}")
    except Exception as e:  # noqa: BLE001
        return dash(f"VIX/VIX3M unread: {type(e).__name__}")


def fred(series, at) -> dict:
    try:
        from market_data.models import MacroIndicator, MacroObservation
        ind = MacroIndicator.objects.filter(series_id=series).first()
        if ind is None:
            return dash(f"no reading within {FRED_FRESH_DAYS} days")
        obs = (MacroObservation.objects.filter(indicator=ind,
                                               date__lte=at.date())
               .order_by("-date").values_list("date", "value").first())
        if obs is None or (at.date() - obs[0]).days > FRED_FRESH_DAYS:
            return dash(f"no reading within {FRED_FRESH_DAYS} days")
        return ok(f"{float(obs[1]):.2f} ({obs[0]:%m-%d})")
    except Exception as e:  # noqa: BLE001
        return dash(f"unread: {type(e).__name__}")


# ── the calendar ─────────────────────────────────────────────────────────

def calendar(start, end, currencies=None) -> dict:
    """High-impact prints in [start, end): [{at, title (fenced, 80), ccy,
    impact, forecast, previous, actual}] in time order; an actual not
    printed is "—", never 0. Unread on any error (unlike
    position_care.upcoming_events, which reads as empty)."""
    try:
        from market_data.models import EconomicEvent

        from bot_program.position_care import EVENT_IMPACT, EVENT_SOURCES
        qs = (EconomicEvent.objects
              .filter(datetime__gte=start, datetime__lt=end,
                      source__in=EVENT_SOURCES, impact__iexact=EVENT_IMPACT)
              .order_by("datetime", "id"))
        if currencies:
            qs = qs.filter(currency_affected__in=list(currencies))
        rows = []
        for e in qs.values("id", "datetime", "title", "currency_affected",
                           "impact", "forecast", "previous", "actual"):
            rows.append({
                "at": e["datetime"], "id": e["id"],
                "title": str(e["title"] or ""),
                "t": fence.untrusted("calendar_title", f"C{e['id']}",
                                     e["title"],
                                     FENCE_CAPS["calendar_title"]),
                "ccy": fence.sanitize(e["currency_affected"], 6),
                "impact": fence.sanitize(e["impact"], 8).lower(),
                "forecast": fence.sanitize(e["forecast"], 16) or "—",
                "previous": fence.sanitize(e["previous"], 16) or "—",
                "actual": fence.sanitize(e["actual"], 16) or "—"})
        return ok(rows)
    except Exception as e:  # noqa: BLE001
        logger.info("[orcs] calendar unread: %s", e)
        return {"value": None, "dash": CALENDAR_DASH, "unread": True}


def calendar_rows(rows, now) -> list:
    """The calendar rows as printed: time UTC, the fenced title, the rest."""
    out = []
    for r in rows or ():
        out.append({"time": _hhmm(r["at"]), "title": r["t"], "ccy": r["ccy"],
                    "impact": r["impact"], "forecast": r["forecast"],
                    "previous": r["previous"],
                    "actual": r["actual"] if r["at"] <= now else "—"})
    return out


# ── MK7, MK8, MK9: the Mind, the brief, the long view ────────────────────

def mind(at) -> dict:
    """The Mind's newest usable report at `at`, read BY ITS ID: regime,
    confidence, health, concerns and themes (each fenced), the narrative's
    first 300 characters as a view, its age. Over 75 min: overdue."""
    try:
        from bot_program.persona_mix import latest_report
        rep = latest_report(at)
        rid = rep.get("report_id")
        if rid is None:
            return dash("no Mind report")
        age = int(round(float(rep.get("age_minutes") or 0)))
        if age > MIND_FRESH_MIN:
            return dash(f"overdue: last report {age} min ago")
        from brain.models import BrainReport
        row = BrainReport.objects.filter(pk=rid).only(
            "portfolio_health_score", "top_concerns", "theme_pressures",
            "narrative_md", "regime_label", "regime_confidence").first()
        if row is None:
            return dash("the Mind's report is gone")
        concerns = [fence.view("mind", c, 120)
                    for c in (row.top_concerns or [])[:3]]
        themes = row.theme_pressures if isinstance(row.theme_pressures,
                                                   dict) else {}
        return ok({"report": f"#{rid}", "regime": rep.get("regime"),
                   "confidence": f"{float(rep.get('confidence') or 0):.2f}",
                   "health": f"{float(row.portfolio_health_score or 0):.2f}",
                   "concerns": concerns or "—",
                   "themes": {fence.sanitize(k, 24): (
                       f"{float(v):+.2f}" if _f(v) is not None else "—")
                       for k, v in sorted(themes.items())[:6]} or "—",
                   "narrative": fence.view("mind", row.narrative_md,
                                           FENCE_CAPS["mind"]),
                   "age_min": age,
                   "trust": "— (the Mind's calibration is not read in O1)"})
    except Exception as e:  # noqa: BLE001
        return dash(f"the Mind unread: {type(e).__name__}")


def brief(at, *, since=None) -> dict:
    """The strategist's newest brief at `at` (or the one that landed after
    `since`): its posture, rationale and outlook as views, the watchlist,
    up to 5 ideas, its age. Older than 30 h: "—"."""
    try:
        from brain.briefing_models import StrategistBriefing
        qs = StrategistBriefing.objects.filter(created_at__lte=at, error="")
        if since is not None:
            qs = qs.filter(created_at__gte=since)
        row = qs.order_by("-created_at").first()
        if row is None:
            return dash("no brief" if since is None else "no brief landed")
        hours = (at - row.created_at).total_seconds() / 3600.0
        if hours > BRIEF_MAX_H:
            return {"value": None, "dash": "—"}
        ideas = []
        for idea in (row.ideas or [])[:5]:
            text = idea if isinstance(idea, str) else (
                (idea or {}).get("symbol") or (idea or {}).get("title") or "")
            ideas.append(fence.view("strategist", text, 120))
        return ok({"posture": fence.sanitize(row.posture, 20),
                   "rationale": fence.view("strategist",
                                           row.posture_rationale, 500),
                   "outlook": fence.view("strategist", row.outlook_md, 600),
                   "watchlist": [fence.sanitize(s, 16)
                                 for s in (row.watchlist or [])[:10]
                                 if isinstance(s, str)],
                   "ideas": ideas or "—",
                   "age": f"{hours:.0f} h old"})
    except Exception as e:  # noqa: BLE001
        return dash(f"the brief unread: {type(e).__name__}")


def horizon(at) -> dict:
    try:
        from brain.horizon_models import latest_view
        v = latest_view()
        if v is None or v.created_at > at:
            return dash("no standing view")
        tilts = {}
        for cls, t in sorted((v.asset_class_tilts or {}).items()):
            t = t if isinstance(t, dict) else {}
            tilt = _f(t.get("tilt"))
            tilts[fence.sanitize(cls, 16)] = (f"{tilt:+.0f}" if tilt is not None
                                              else "—")
        return ok(tilts or "— (no tilt)")
    except Exception as e:  # noqa: BLE001
        return dash(f"no standing view ({type(e).__name__})")


# ── MK12, IN9: the news, titles and tags only ────────────────────────────

def analyst_blind(at) -> tuple:
    """(blind, since): the analyst idle over 2 h (news_risk's rule)."""
    try:
        from django.db.models import Max

        from bot_program.news_risk import ANALYST_IDLE_SECONDS
        from scraping.models import NewsArticle
        last = NewsArticle.objects.filter(ai_processed_at__lte=at) \
            .aggregate(m=Max("ai_processed_at"))["m"]
        if last is None:
            return True, "the analyst's last run: never"
        if (at - last).total_seconds() > ANALYST_IDLE_SECONDS:
            return True, f"{last:%Y-%m-%d %H:%M}"
        return False, f"{last:%Y-%m-%d %H:%M}"
    except Exception:  # noqa: BLE001
        return True, "the analyst's last run: unread"


def headlines(start, end, *, symbols=None, n=6, blind=None) -> dict:
    """The day's news in [start, end): at most `n`, urgent first then the
    newest, each its TITLE fenced as untrusted (N-id, 120 characters),
    the analyst's sentiment and urgency (a failed parse: "—"; a blind
    analyst: the tags say so), the matched instruments, the publisher."""
    try:
        from django.db.models import BooleanField, Case, Q, Value, When

        from bot_program.news_risk import FAILED_PARSE_SUMMARY, URGENT_LEVELS
        from scraping.models import NewsArticle
        qs = NewsArticle.objects.filter(published_at__gte=start,
                                        published_at__lt=end)
        if symbols:
            qs = qs.filter(ai_affected_instruments__symbol__in=list(symbols))
        qs = qs.annotate(
            failed=Case(When(Q(ai_summary=FAILED_PARSE_SUMMARY),
                             then=Value(True)), default=Value(False),
                        output_field=BooleanField()),
            urgent=Case(When(ai_urgency__in=list(URGENT_LEVELS),
                             then=Value(True)), default=Value(False),
                        output_field=BooleanField()))
        rows = list(qs.order_by("-urgent", "-published_at", "-id")
                    .values("id", "title", "source", "published_at",
                            "ai_sentiment_score", "ai_urgency", "failed",
                            "urgent")
                    .distinct()[:int(n)])
        if not rows:
            return ok([])
        from scraping.models import NewsArticle as NA
        through = NA.ai_affected_instruments.through
        matched = {}
        for aid, sym in through.objects.filter(
                newsarticle_id__in=[r["id"] for r in rows]).values_list(
                    "newsarticle_id", "instrument__symbol"):
            matched.setdefault(aid, []).append(sym)
        out = []
        for r in rows:
            if blind:
                tags = {"sent": "— (tags blind)", "urgency": "— (tags blind)"}
            elif r["failed"] or r["ai_sentiment_score"] is None:
                tags = {"sent": "—", "urgency": "—"}
            else:
                tags = {"sent": f"{float(r['ai_sentiment_score']):+.2f}",
                        "urgency": fence.sanitize(r["ai_urgency"], 12) or "—"}
            out.append({"id": f"N{r['id']}", "time": _hhmm(r["published_at"]),
                        "t": fence.untrusted("headline", f"N{r['id']}",
                                             r["title"],
                                             FENCE_CAPS["headline"]),
                        "publisher": fence.sanitize(r["source"], 32),
                        "instruments": sorted(matched.get(r["id"], []))[:6],
                        **tags})
        return ok(out)
    except Exception as e:  # noqa: BLE001
        logger.info("[orcs] headlines unread: %s", e)
        return dash(f"the news unread: {type(e).__name__}")


def news_ratio(asset_class, at) -> dict:
    """Urgent items over 24 h on the class's instruments, over the class's
    30-day daily median (a failed parse never counts)."""
    try:
        from django.db.models import Count, Q
        from django.db.models.functions import TruncDate

        from bot_program.news_risk import FAILED_PARSE_SUMMARY, URGENT_LEVELS
        from scraping.models import NewsArticle
        base = (NewsArticle.objects
                .filter(ai_urgency__in=list(URGENT_LEVELS),
                        ai_affected_instruments__asset_class=asset_class,
                        published_at__lte=at,
                        published_at__gte=at - timedelta(days=30))
                .exclude(Q(ai_summary=FAILED_PARSE_SUMMARY)))
        last24 = base.filter(published_at__gte=at - timedelta(hours=24)) \
            .values("id").distinct().count()
        per_day = sorted(r["n"] for r in base.annotate(
            d=TruncDate("published_at")).values("d").annotate(
                n=Count("id", distinct=True)))
        if not per_day:
            return ok(None if not last24 else float(last24))
        days = per_day + [0] * max(0, 30 - len(per_day))
        days.sort()
        median = days[len(days) // 2] or 1
        return ok(round(last24 / float(median), 2))
    except Exception as e:  # noqa: BLE001
        return dash(f"the news unread: {type(e).__name__}")


# ── quotes, the book, the correlations ───────────────────────────────────

def quotes(symbols) -> dict:
    """{symbol: quote(symbol)} in one query."""
    out = {s: dash("no live quote") for s in symbols or ()}
    try:
        from market_data.models import LiveQuote
        for q in (LiveQuote.objects
                  .filter(instrument__symbol__in=list(out))
                  .select_related("instrument")
                  .only("last", "bid", "ask", "change_pct", "updated_at",
                        "instrument__symbol")):
            out[q.instrument.symbol] = ok({
                "last": _f(q.last), "bid": _f(q.bid), "ask": _f(q.ask),
                "change_pct": _f(q.change_pct), "at": q.updated_at})
    except Exception as e:  # noqa: BLE001
        return {s: dash(f"quote unread: {type(e).__name__}") for s in out}
    return out


def quote(symbol) -> dict:
    try:
        from market_data.models import LiveQuote
        q = (LiveQuote.objects.filter(instrument__symbol=symbol)
             .only("last", "bid", "ask", "change_pct", "updated_at").first())
        if q is None:
            return dash("no live quote")
        return ok({"last": _f(q.last), "bid": _f(q.bid), "ask": _f(q.ask),
                   "change_pct": _f(q.change_pct), "at": q.updated_at})
    except Exception as e:  # noqa: BLE001
        return dash(f"quote unread: {type(e).__name__}")


def book(user, *, real=True, cache=None) -> dict:
    """The book as SHARES of its limits: the daily-loss mode, open risk as
    a share of its limit. Never a money figure. Once per pass with `cache`."""
    key = ("orcs:book", getattr(user, "pk", None), bool(real))
    if isinstance(cache, dict) and key in cache:
        return cache[key]
    try:
        from portfolio.models import Portfolio
        from portfolio.risk_gate import daily_loss_state, open_risk_state
        # the shared limits book, READ, never created (risk_gate.limits_book
        # creates it: an Orc writes nothing outside its own tables)
        pf = Portfolio.objects.filter(name="Main").first()
        if pf is None:
            raise LookupError("no limits book yet")
        venue = "live" if real else "paper"
        dl = daily_loss_state(user, portfolio=pf, venue=venue)
        orisk = open_risk_state(user, portfolio=pf, venue=venue)
        limit = _f(orisk.get("limit_money"))
        used = _f(orisk.get("open_risk"))
        share = (used / limit) if limit and used is not None else None
        out = ok({"daily_loss_mode": str(dl.get("mode") or "open"),
                  "open_risk_share": share,
                  "open_risk_t": (f"{share:.0%} of its limit"
                                  if share is not None else
                                  "— (no open-risk limit measured)")})
        out["_limit"] = limit           # code only: the size term's divisor
    except Exception as e:  # noqa: BLE001
        out = dash("book unreadable")
        logger.info("[orcs] book unread: %s", e)
    if isinstance(cache, dict):
        cache[key] = out
    return out


def correlation(user, symbols) -> dict:
    """{"pairs": {"A/B": "+0.82" | "—"}, "matrix": raw} on the platform's
    measured matrix (capital_desk.correlation_matrix): an unmeasured pair
    reads "—", never 0.0."""
    try:
        from bot_program.capital_desk import correlation_matrix
        syms = sorted({s for s in symbols or () if s})
        if len(syms) < 2:
            return ok({"pairs": {}, "matrix": {"rho": {}, "measured": set()}})
        m = correlation_matrix(user, syms)
        pairs = {}
        for i, a in enumerate(syms):
            for b in syms[i + 1:]:
                pair = (a, b)
                if pair in (m.get("measured") or set()):
                    pairs[f"{a}/{b}"] = f"{float(m['rho'].get(pair, 0)):+.2f}"
                else:
                    pairs[f"{a}/{b}"] = "—"
        return ok({"pairs": pairs, "matrix": m})
    except Exception as e:  # noqa: BLE001
        return dash(f"correlations unread: {type(e).__name__}")


# ── the calendar's actuals (§5.2a item 7) ────────────────────────────────

def actuals_measurement(days, now) -> dict:
    """How many past high-impact prints in the last `days` carry an actual,
    per source: whether the free feed prints them is unmeasured until
    this says so."""
    from market_data.models import EconomicEvent

    from bot_program.position_care import EVENT_IMPACT, EVENT_SOURCES
    days = max(1, int(days or 14))
    rows = list(EconomicEvent.objects
                .filter(datetime__lt=now,
                        datetime__gte=now - timedelta(days=days),
                        source__in=EVENT_SOURCES, impact__iexact=EVENT_IMPACT)
                .values_list("source", "actual"))
    by = {}
    for source, actual in rows:
        slot = by.setdefault(str(source), {"n": 0, "with_actual": 0})
        slot["n"] += 1
        if str(actual or "").strip():
            slot["with_actual"] += 1
    n = sum(s["n"] for s in by.values())
    w = sum(s["with_actual"] for s in by.values())
    if not n:
        words = f"— (no high-impact print in the last {days} days)"
    else:
        parts = "; ".join(f"{src} {s['with_actual']} of {s['n']}"
                          for src, s in sorted(
                              by.items(), key=lambda kv: (-kv[1]["n"],
                                                          kv[0])))
        words = (f"{w} of {n} high-impact prints in the last {days} days "
                 f"carry an actual ({parts}).")
    return {"days": days, "n": n, "with_actual": w,
            "share": round(w / n, 3) if n else None, "by_source": by,
            "at": now.isoformat(), "words": words}
