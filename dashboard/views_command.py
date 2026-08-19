"""Operations Center — unified tabbed view (renamed from Command Center).

Replaces the old "Dashboard" + "Sauron's Eye" + "Command Center" layout
with a single richer page split into 4 tabs:

  LIVE       — current Eye content + brain regime + gate ratio + recent fills
  PORTFOLIO  — equity curve + allocation donut + Sharpe + winners/losers
  HISTORY    — cumulative R curve + rolling win-rate + DoW heatmap + per-rule
  BOTS       — per-bot today's stats + heartbeat + cooldown countdown

Every tab head also displays a LIVE metric so the tab bar itself is a
mini-dashboard (e.g. LIVE shows "3 OPEN · +$142", BOTS shows "5/8 ON").

WebSocket: tabs subscribe to typed events on the existing /ws/eye/ feed
so live updates push (no polling).
"""
import logging
from collections import defaultdict
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Avg, Count
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone

logger = logging.getLogger(__name__)

# An em-dash means NOT MEASURED. A metric that cannot be computed must never
# fall back to 0 or to an empty span: a confident "+0.00" reads as "flat" and
# a blank reads as "broken page", and this tab bar has been doing both.
DASH = "—"


# ── Helpers ──────────────────────────────────────────────────────────────

def _smart_default_tab(user) -> str:
    """If the user has any enabled bot configs → LIVE; else → PORTFOLIO."""
    try:
        from bot_program.models import AssetBotConfig
        if AssetBotConfig.objects.filter(user=user, enabled=True).exists():
            return "live"
    except Exception as e:
        logger.warning("Op Center default-tab probe failed: %s", e)
    return "portfolio"


def _tone(value) -> str:
    """Colour class for a signed reading; blank for zero and for unknown."""
    if value is None:
        return ""
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return ""


def _fill_card(trade):
    """A closed trade, shaped the way the best/worst cards read it.

    Those cards ask for `.config.symbol` and `.config.rule_name`, and
    AssetBotConfig has neither — it holds a `symbols` LIST, and rule_name is
    a column on the trade. Both cards therefore rendered a real R multiple
    above a blank symbol and an em-dash rule, which reads as a data outage
    rather than a template mistake.
    """
    if trade is None:
        return None
    return {
        "config": {"symbol": trade.symbol, "rule_name": trade.rule_name},
        "realized_r": trade.realized_r,
        "outcome": (trade.outcome or "").replace("_", " "),
        "closed_at": trade.closed_at,
    }


def _open_book(user, portfolio):
    """The open position book — BOTH halves — priced from live marks.

    Exposure lives in two places on this platform: legacy portfolio.Position
    (Setup form, NL trader, eToro sync) and bot_program.AssetBotTrade (the
    bots, TAKE TRADE, the LONG/SHORT buttons). The LIVE tab head counted only
    the first, so an operator holding three bot trades read "0 OPEN" while
    the headband immediately above it counted all three. The union is the
    platform's own `unified_open_positions`, the same read the positions
    pages use.

    P&L comes from a live quote and never from Position.unrealized_pnl. That
    column defaults to 0 and its only writer is an hourly task that marks the
    SHARED "Main" portfolio, so on the per-user book this page reads it is a
    permanent, confident +0.00.

    Returns (rows, n_priced, unrealized, deployed). Legacy rows come back
    re-priced IN MEMORY — the tab head and the table underneath it must not
    be able to quote two different P&Ls for the same position. unrealized and
    deployed are None when nothing could be priced: an unpriced book is
    unknown, not flat.
    """
    from market_data.models import LiveQuote
    from portfolio.services import unified_open_positions

    rows = unified_open_positions(user, portfolio)
    if not rows:
        return [], 0, None, None

    # Bot rows arrive already marked by portfolio.services (None where no
    # quote exists). Legacy Position rows carry the dead column, so they are
    # re-priced here against the same LiveQuote table the bot rows used.
    legacy = [r for r in rows if getattr(r, "source", "") != "bot"]
    quotes = {}
    if legacy:
        ids = {r.instrument_id for r in legacy
               if getattr(r, "instrument_id", None)}
        if ids:
            quotes = {q.instrument_id: q for q in
                      LiveQuote.objects.filter(instrument_id__in=ids)}

    for r in legacy:
        quote = quotes.get(getattr(r, "instrument_id", None))
        mark = (float(quote.last)
                if quote is not None and quote.last is not None else None)
        if mark is None:
            # Never saved: this is a display re-price, and writing it back
            # would put an unmarked guess into the book the snapshot task
            # reads.
            r.current_price = None
            r.unrealized_pnl = None
            r.unrealized_pnl_pct = None
            continue
        entry = float(r.entry_price or 0)
        qty = float(r.quantity or 0)
        sign = -1 if (r.direction or "").lower() in ("short", "sell") else 1
        r.current_price = mark
        r.unrealized_pnl = round((mark - entry) * qty * sign, 2)
        r.unrealized_pnl_pct = (round((mark - entry) / entry * 100 * sign, 2)
                                if entry else None)

    n_priced = 0
    unrealized = 0.0
    deployed = 0.0
    for r in rows:
        if r.unrealized_pnl is None or r.current_price is None:
            continue
        unrealized += float(r.unrealized_pnl)
        deployed += abs(float(r.current_price) * float(r.quantity or 0))
        n_priced += 1

    if n_priced == 0:
        return rows, 0, None, None
    return rows, n_priced, round(unrealized, 2), round(deployed, 2)


def _tab_bar_metrics(user) -> dict:
    """The small metric under each tab head.

    Every value is a pre-formatted string, `tone` is the colour class, and
    `title` is the tooltip — a four-character number cannot say which book it
    counted or how many of its rows it could actually price, and the operator
    has to be able to ask.

    Previously each block ended in `except Exception: pass` over a dict whose
    secondaries defaulted to the EMPTY STRING, so a metric that failed left a
    blank span rather than an em-dash: three of the four tab heads rendered
    nothing at all on an install with no snapshots, which looks exactly like
    a broken page and was reported as one.
    """
    out = {
        key: {"primary": DASH, "secondary": DASH, "tone": "", "title": ""}
        for key in ("live", "portfolio", "history", "bots")
    }

    # ── LIVE: open positions across both books + unrealized P&L ──────
    try:
        from portfolio.services import get_or_create_default_portfolio
        portfolio = get_or_create_default_portfolio(user=user)
        rows, n_priced, unrealized, _deployed = _open_book(user, portfolio)
        n_open = len(rows)
        out["live"]["primary"] = f"{n_open} OPEN"
        if n_open == 0:
            out["live"]["title"] = "No open positions in either book."
        elif unrealized is None:
            out["live"]["title"] = (
                f"{n_open} open, none priced — no live quote for any of them, "
                f"so unrealized P&L is unknown.")
        else:
            out["live"]["secondary"] = f"{unrealized:+,.2f}"
            out["live"]["tone"] = _tone(unrealized)
            out["live"]["title"] = (
                f"Unrealized P&L, marked to live quotes. {n_priced} of "
                f"{n_open} open positions priced.")
    except Exception as e:
        logger.warning("Op Center LIVE metric unavailable: %s", e, exc_info=True)

    # ── PORTFOLIO: book value + TODAY's snapshot delta ───────────────
    try:
        from portfolio.services import get_or_create_default_portfolio
        from portfolio.models import PortfolioSnapshot
        portfolio = get_or_create_default_portfolio(user=user)
        out["portfolio"]["primary"] = f"${float(portfolio.current_value):,.0f}"
        # A snapshot from last week does not describe today's P&L. The old
        # code took the newest snapshot whatever its date and printed it as
        # "24h", so a stale book reported a day it never had.
        today = timezone.localdate()
        snap = (PortfolioSnapshot.objects
                .filter(portfolio=portfolio, date=today).first())
        if snap is not None and snap.daily_pnl_pct is not None:
            pct = float(snap.daily_pnl_pct)
            out["portfolio"]["secondary"] = f"{pct:+.2f}%"
            out["portfolio"]["tone"] = _tone(pct)
            out["portfolio"]["title"] = (
                f"{portfolio.name} book value; day change from today's "
                f"snapshot.")
        else:
            out["portfolio"]["title"] = (
                f"{portfolio.name} book value. No snapshot for {today} yet, "
                f"so the day change is not measured.")
    except Exception as e:
        logger.warning("Op Center PORTFOLIO metric unavailable: %s", e,
                       exc_info=True)

    # ── HISTORY: 90-day W/L count + avg R ────────────────────────────
    try:
        from bot_program.models import AssetBotTrade
        # 90 days, not 30: this is the head of a tab whose body is a 90-day
        # analysis, and a head that summarises a different window than the
        # body it labels sends the operator looking for the discrepancy.
        cutoff = timezone.now() - timedelta(days=90)
        closed = AssetBotTrade.objects.filter(
            config__user=user, status="CLOSED", closed_at__gte=cutoff)
        n_closed = closed.count()
        graded = closed.filter(realized_r__isnull=False)
        wins = graded.filter(realized_r__gt=0).count()
        losses = graded.filter(realized_r__lt=0).count()
        n_graded = graded.count()
        if n_graded:
            avg_r = graded.aggregate(a=Avg("realized_r"))["a"] or 0
            out["history"]["primary"] = f"{wins}W·{losses}L"
            out["history"]["secondary"] = f"{avg_r:+.2f}R"
            out["history"]["tone"] = _tone(avg_r)
            out["history"]["title"] = (
                f"Bot trades closed in 90 days: {n_graded} of {n_closed} "
                f"carry an R grade and are counted here.")
        else:
            out["history"]["title"] = (
                f"{n_closed} bot trades closed in 90 days, none graded with "
                f"an R multiple — nothing to average.")
    except Exception as e:
        logger.warning("Op Center HISTORY metric unavailable: %s", e,
                       exc_info=True)

    # ── BOTS: enabled count + 24h realized P&L ───────────────────────
    try:
        from bot_program.models import AssetBotConfig, AssetBotTrade
        configs = AssetBotConfig.objects.filter(user=user)
        n_total = configs.count()
        n_on = configs.filter(enabled=True).count()
        cutoff = timezone.now() - timedelta(hours=24)
        closed_24h = AssetBotTrade.objects.filter(
            config__user=user, status="CLOSED", closed_at__gte=cutoff)
        # Sum() over an empty set is None, which the old code coerced to
        # Decimal("0") and printed as "+$0.00 24h" — a claim that the day
        # closed flat, on a day nothing closed at all.
        pnl_24h = closed_24h.aggregate(s=Sum("pnl"))["s"]
        if n_total:
            out["bots"]["primary"] = f"{n_on}/{n_total} ON"
        else:
            out["bots"]["title"] = "No bot configurations yet."
        if pnl_24h is not None:
            value = float(pnl_24h)
            out["bots"]["secondary"] = f"{value:+,.2f} 24h"
            out["bots"]["tone"] = _tone(value)
            out["bots"]["title"] = (
                f"{n_on} of {n_total} bots enabled; realized P&L over "
                f"{closed_24h.count()} closes in 24h.")
        elif n_total:
            out["bots"]["title"] = (
                f"{n_on} of {n_total} bots enabled. Nothing closed in 24h, "
                f"so there is no realized P&L to show.")
    except Exception as e:
        logger.warning("Op Center BOTS metric unavailable: %s", e, exc_info=True)

    return out


def _hero_metrics(user) -> dict:
    """The hero strip's readouts, already formatted for display.

    Split out of _hero_context so the initial render and the live refresh
    below run the same code — two formatters for one number is how a page
    ends up disagreeing with itself after the first push.
    """
    out = {
        "value": DASH, "value_title": "", "currency": "",
        "delta": DASH, "delta_tone": "", "delta_title": "",
        "regime": DASH, "regime_class": "oc-regime-unknown",
        "regime_conf": DASH,
        "trust": "UNKNOWN", "trust_class": "oc-trust-unknown",
        "mode": "paper", "mode_label": "◌ PAPER", "mode_class": "pill-paper",
    }

    try:
        from portfolio.services import get_or_create_default_portfolio
        from portfolio.models import PortfolioSnapshot
        portfolio = get_or_create_default_portfolio(user=user)
        out["value"] = f"{float(portfolio.current_value):,.2f}"
        out["currency"] = portfolio.currency
        out["value_title"] = (
            f"Book value of {portfolio.name}, last written "
            f"{portfolio.updated_at:%Y-%m-%d %H:%M} UTC.")
        # "+0.00" was the hardcoded default here, printed under a "· 24h"
        # label on every install that has never taken a snapshot.
        today = timezone.localdate()
        snap = (PortfolioSnapshot.objects
                .filter(portfolio=portfolio, date=today).first())
        if snap is not None and snap.daily_pnl_pct is not None:
            pct = float(snap.daily_pnl_pct)
            out["delta"] = f"{pct:+.2f}%"
            out["delta_tone"] = _tone(pct)
            out["delta_title"] = f"Day change from the {today} snapshot."
        else:
            out["delta_title"] = (
                f"No portfolio snapshot for {today}, so the day change is "
                f"not measured.")
    except Exception as e:
        logger.warning("Op Center hero portfolio unavailable: %s", e,
                       exc_info=True)

    try:
        from bot_program.models import AssetBotConfig
        if AssetBotConfig.objects.filter(
                user=user, enabled=True, mode="live").exists():
            out.update({"mode": "live", "mode_label": "● LIVE",
                        "mode_class": "pill-live"})
    except Exception as e:
        logger.warning("Op Center hero mode unavailable: %s", e, exc_info=True)

    # Brain regime + trust band for the hero strip (Phase 47 actuation).
    try:
        from brain.models import BrainReport
        from brain.context import _brain_trust_score, brain_trust_band
        latest_report = (BrainReport.objects.filter(error="")
                          .order_by("-created_at").first())
        if latest_report:
            out["regime"] = (latest_report.regime_label or "unknown").upper()
            out["regime_class"] = (
                f"oc-regime-{latest_report.regime_label or 'unknown'}")
            if latest_report.regime_confidence is not None:
                out["regime_conf"] = f"{float(latest_report.regime_confidence):.2f}"
        band = brain_trust_band(_brain_trust_score())
        out["trust"] = (band or "unknown").upper()
        out["trust_class"] = f"oc-trust-{band or 'unknown'}"
    except Exception as e:
        logger.warning("Op Center hero brain state unavailable: %s", e,
                       exc_info=True)

    return out


def _hero_context(user) -> dict:
    """Header strip data — visible above tabs at all times."""
    hero = _hero_metrics(user)
    return {
        "hero": hero,
        "currency": hero["currency"],
        "now_utc": timezone.now(),
    }


# ── Main entry point ─────────────────────────────────────────────────────

@login_required
def command_center(request):
    """Renders the wrapper with tabs. Initial tab from `?tab=` or smart default.

    Note: route stays at /command/ for backward compat — only the visible
    name changed to 'Operations Center'.
    """
    tab = (request.GET.get("tab") or _smart_default_tab(request.user)).lower()
    if tab not in ("live", "portfolio", "history", "bots"):
        tab = "live"

    context = {
        "page_id": "command",
        "active_tab": tab,
        "tab_metrics": _tab_bar_metrics(request.user),
        **_hero_context(request.user),
    }
    return render(request, "dashboard/command.html", context)


@login_required
def command_tab_metrics(request):
    """The tab-head metrics and the hero strip, as JSON.

    These were computed once, at page render, and the per-tab fragment
    endpoints never recomputed them — so the four numbers the tab bar exists
    to show stayed frozen at whatever they were when the page was opened,
    however many fills landed afterwards. The page polls this on the same
    /ws/eye/ events the headband already reacts to, plus a slow fallback
    timer for the state changes the socket does not announce (a snapshot
    landing, a bot being toggled elsewhere).

    Deliberately JSON and not an HTML fragment: the payload is eight short
    strings, and re-rendering the tab bar would mean duplicating its markup
    in a partial that the live tab (owned elsewhere) could not carry.
    """
    return JsonResponse({
        "tabs": _tab_bar_metrics(request.user),
        "hero": _hero_metrics(request.user),
    })


# ── Per-tab fragment endpoints (HTMX-loaded) ─────────────────────────────

@login_required
def command_tab_live(request):
    """LIVE tab — current Eye content + Operations enrichment."""
    from .views_eye import _build_eye_context
    context = _build_eye_context(request.user)

    # Operations enrichment for LIVE.
    user = request.user
    try:
        from portfolio.services import get_or_create_default_portfolio
        portfolio = get_or_create_default_portfolio(user=user)
        # Both books, marked to live quotes — the same union the tab head
        # counts. Reading only portfolio.Position here reported 0% deployed
        # and 100% cash to an operator whose whole book was bot trades.
        _rows, _n_priced, _unreal, deployed_value = _open_book(user, portfolio)
        _n_open = len(_rows)
        # The OPEN POS cell counts the same union as the tab head above it.
        # It used to count AssetBotTrade alone, so the two disagreed whenever
        # a legacy Position was open.
        context["live_opens"] = _n_open
        cash_value = float(portfolio.cash_available or 0)
        if deployed_value is None:
            # Positions exist but none could be priced: the split is unknown,
            # and "100% cash" would be a claim of no exposure at all. DASH
            # rather than None because floatformat renders None as an empty
            # span but passes an unparseable string through untouched.
            context["live_deployed"] = DASH if _n_open else 0
            context["live_cash"] = cash_value
            context["live_deployed_pct"] = DASH if _n_open else 0
            context["live_cash_pct"] = DASH if _n_open else 100
        else:
            total = deployed_value + cash_value
            context["live_deployed"] = deployed_value
            context["live_cash"] = cash_value
            context["live_deployed_pct"] = (
                round(deployed_value / total * 100, 1) if total > 0 else 0)
            context["live_cash_pct"] = (
                round(cash_value / total * 100, 1) if total > 0 else 0)
    except Exception as e:
        logger.warning("Op Center LIVE exposure unavailable: %s", e,
                       exc_info=True)
        context["live_opens"] = DASH
        context["live_deployed"] = DASH
        context["live_cash"] = DASH
        context["live_deployed_pct"] = DASH
        context["live_cash_pct"] = DASH

    # Today's gate allow/reject ratio (Phase 15 orchestrator).
    try:
        from bot_program.orchestrator_models import OrchestratorEvent
        cutoff = timezone.now() - timedelta(hours=24)
        today_events = OrchestratorEvent.objects.filter(
            user=user, created_at__gte=cutoff)
        n_allow = today_events.filter(decision="allow").count()
        n_reject = today_events.filter(decision="reject").count()
        n_total = n_allow + n_reject
        context["gate_n_allow"] = n_allow
        context["gate_n_reject"] = n_reject
        # No decisions in 24h is "the gate was not asked", not "0% accepted".
        context["gate_accept_rate"] = (
            round(n_allow / n_total * 100, 1) if n_total > 0 else DASH)
    except Exception as e:
        logger.warning("Op Center gate ratio unavailable: %s", e, exc_info=True)
        context["gate_n_allow"] = DASH
        context["gate_n_reject"] = DASH
        context["gate_accept_rate"] = DASH

    # Recent fills (last 5 closed bot trades in the last 24h) + 24h session metrics.
    try:
        from bot_program.models import AssetBotTrade, AssetBotConfig
        cutoff = timezone.now() - timedelta(hours=24)
        all_24h_closed = list(
            AssetBotTrade.objects
            .filter(config__user=user, status="CLOSED",
                     closed_at__gte=cutoff)
            .select_related("config")
            .order_by("-closed_at")
        )
        context["live_recent_fills"] = all_24h_closed[:5]

        # 24h session aggregates.
        n_closed_24h = len(all_24h_closed)
        graded = [t for t in all_24h_closed if t.realized_r is not None]
        rs = [float(t.realized_r) for t in graded]
        n_wins = sum(1 for r in rs if r > 0)
        n_losses = sum(1 for r in rs if r < 0)
        best_24h = max(graded, key=lambda t: float(t.realized_r), default=None)
        worst_24h = min(graded, key=lambda t: float(t.realized_r), default=None)

        n_bots_enabled = AssetBotConfig.objects.filter(
            user=user, enabled=True).count()
        n_bots_total = AssetBotConfig.objects.filter(user=user).count()

        # Last 12 closes, oldest → newest, matching the axis captions under
        # the bars. The slice used to run over the tail of a newest-first
        # list, so the card labelled "last 12 closes" plotted the twelve
        # OLDEST of the session and drew them right-to-left.
        last_12_r = [float(t.realized_r) for t in list(reversed(graded))[-12:]]

        context["live_bots_enabled"] = n_bots_enabled
        context["live_bots_total"] = n_bots_total
        context["live_24h_n"] = n_closed_24h
        context["live_24h_wins"] = n_wins
        context["live_24h_losses"] = n_losses
        # Nothing graded means nothing measured: a summed R of 0 over zero
        # trades reads as a flat session, which is a different claim.
        context["live_24h_sum_r"] = round(sum(rs), 2) if rs else DASH
        context["live_24h_win_rate"] = (
            round(n_wins / len(rs) * 100, 1) if rs else DASH)
        # The best/worst cards read `.config.symbol` and `.config.rule_name`,
        # and AssetBotConfig has NEITHER (it holds a `symbols` LIST, and
        # rule_name lives on the trade) — so both cards rendered a blank
        # symbol above a real R number. Handed over as plain mappings shaped
        # the way the card reads them, with the trade's own values.
        context["live_24h_best"] = _fill_card(best_24h)
        context["live_24h_worst"] = _fill_card(worst_24h)
        context["live_24h_spark"] = last_12_r
        context["live_24h_spark_min"] = (min(last_12_r) if last_12_r else 0)
        context["live_24h_spark_max"] = (max(last_12_r) if last_12_r else 0)
        # chart_bars contract. A diverging series scales against ONE peak —
        # the largest absolute R — or a −3R loss next to a +0.5R win draws
        # the two at the same length in opposite directions.
        context["live_24h_bars"] = [
            {"label": "#{}".format(i + 1), "value": r,
             "display": "{:+.2f}R".format(r)}
            for i, r in enumerate(last_12_r)
        ]
        context["live_24h_spark_peak"] = max(
            [abs(r) for r in last_12_r], default=0)
    except Exception as e:
        logger.warning("Op Center LIVE session pulse unavailable: %s", e,
                       exc_info=True)
        context["live_recent_fills"] = []
        context["live_bots_enabled"] = DASH
        context["live_bots_total"] = DASH
        context["live_24h_n"] = DASH
        context["live_24h_wins"] = DASH
        context["live_24h_losses"] = DASH
        context["live_24h_sum_r"] = DASH
        context["live_24h_win_rate"] = DASH
        context["live_24h_best"] = None
        context["live_24h_worst"] = None
        context["live_24h_spark"] = []
        context["live_24h_spark_min"] = 0
        context["live_24h_spark_max"] = 0
        context["live_24h_bars"] = []
        context["live_24h_spark_peak"] = 0

    # Active rules counter (Phase 5 RuleControl) — operator awareness.
    try:
        # signals.models_control, not bot_program.rule_control_models: that
        # module does not exist, so this import raised ModuleNotFoundError on
        # every single render and the swallowing `except` printed a confident
        # "0 rules · 0 paused · 0 research" on an install running twelve.
        # The old field names were wrong too (`state`, `stage`), so even the
        # right module would not have answered.
        from signals.models_control import RuleControl
        now = timezone.now()
        running = RuleControl.running_q(now)
        context["live_rules_active"] = RuleControl.objects.filter(running).count()
        # Paused is the complement of running, not `status="paused"`: a pause
        # whose paused_until has elapsed is a rule trading again, and nothing
        # ever writes the column back — counting by column double-books it
        # against the line above.
        context["live_rules_paused"] = RuleControl.objects.exclude(running).count()
        context["live_rules_research"] = RuleControl.objects.filter(
            promotion_stage=RuleControl.STAGE_RESEARCH).count()
    except Exception as e:
        logger.warning("Op Center rule counters unavailable: %s", e,
                       exc_info=True)
        context["live_rules_active"] = DASH
        context["live_rules_paused"] = DASH
        context["live_rules_research"] = DASH

    # Latest brain report timing — staleness indicator.
    try:
        from brain.models import BrainReport
        last_br = BrainReport.objects.filter(error="").order_by("-created_at").first()
        if last_br:
            mins = int((timezone.now() - last_br.created_at).total_seconds() / 60)
            if mins < 60:
                context["brain_age_str"] = f"{mins}m"
            elif mins < 60 * 24:
                context["brain_age_str"] = f"{mins // 60}h"
            else:
                context["brain_age_str"] = f"{mins // (60 * 24)}d"
        else:
            context["brain_age_str"] = "—"
    except Exception:
        context["brain_age_str"] = "—"

    # Brain regime/trust for the LIVE strip.
    try:
        from brain.models import BrainReport
        from brain.context import _brain_trust_score, brain_trust_band
        latest_report = (BrainReport.objects.filter(error="")
                          .order_by("-created_at").first())
        if latest_report:
            context["brain_regime"] = latest_report.regime_label
            context["brain_regime_conf"] = float(
                latest_report.regime_confidence or 0)
            concerns = latest_report.top_concerns or []
            context["brain_top_concerns"] = concerns[:3]
        trust = _brain_trust_score()
        context["brain_trust"] = trust
        context["brain_trust_band"] = brain_trust_band(trust)
    except Exception:
        context["brain_regime"] = "unknown"
        context["brain_top_concerns"] = []
        context["brain_trust"] = None
        context["brain_trust_band"] = "unknown"

    return render(request, "dashboard/_command_live.html", context)


@login_required
def command_tab_portfolio(request):
    """PORTFOLIO tab — strategic snapshot with sparkline + allocation."""
    from portfolio.services import (get_or_create_default_portfolio,
                                     unified_closed_positions)
    from portfolio.models import PortfolioSnapshot

    portfolio = get_or_create_default_portfolio(user=request.user)
    # BOTH books. This tab read portfolio.Position alone, so on a platform
    # where every interactive trade writes AssetBotTrade it showed an empty
    # portfolio, an empty allocation donut and "No closed trades yet" to an
    # operator with a full track record. `unified_*` is the read-side union
    # the positions pages already use; _open_book re-prices its legacy half
    # so this table and the LIVE tab head cannot quote different P&Ls.
    open_positions, _n_priced, total_unrealized, _deployed = _open_book(
        request.user, portfolio)
    closed_positions = unified_closed_positions(request.user, portfolio)

    # A closed row's P&L is unknown when nothing could price it (an option
    # with no premium feed, a symbol with no quote). Unknown rows are held
    # out of the win/loss split entirely rather than being booked as losses,
    # which is what `float(p.unrealized_pnl) <= 0` did to every one of them.
    graded = [p for p in closed_positions if p.unrealized_pnl is not None]
    n_ungraded = len(closed_positions) - len(graded)
    total_closed = len(graded)
    winning = [p for p in graded if float(p.unrealized_pnl) > 0]
    losing = [p for p in graded if float(p.unrealized_pnl) < 0]
    win_rate = (len(winning) / total_closed * 100) if total_closed else None
    avg_win = (sum(float(p.unrealized_pnl) for p in winning) / len(winning)) if winning else None
    avg_loss = (sum(float(p.unrealized_pnl) for p in losing) / len(losing)) if losing else None
    profit_factor = (abs(avg_win / avg_loss)
                     if avg_win is not None and avg_loss else None)

    cash_pct = round(float(portfolio.cash_available) / max(float(portfolio.current_value), 1) * 100)

    latest_snapshot = (PortfolioSnapshot.objects.filter(portfolio=portfolio)
                        .order_by("-date").first())

    best_trades = sorted(winning, key=lambda p: float(p.unrealized_pnl),
                         reverse=True)[:5]
    worst_trades = sorted(losing, key=lambda p: float(p.unrealized_pnl))[:5]

    # Equity curve sparkline — last 30 days of total_value.
    cutoff_30d = timezone.now().date() - timedelta(days=30)
    equity_rows = list(
        PortfolioSnapshot.objects.filter(
            portfolio=portfolio, date__gte=cutoff_30d)
        .order_by("date")
        .values_list("date", "total_value")
    )
    equity_points = [float(v) for _, v in equity_rows]

    # Allocation donut data — by asset class, from current open positions.
    # Marked value where a mark exists, entry cost otherwise: a slice sized
    # at zero because no quote arrived would silently shrink the book.
    alloc_by_class = defaultdict(float)
    for p in open_positions:
        ac = getattr(p.instrument, "asset_class", "") or "other"
        price = p.current_price if p.current_price is not None else p.entry_price
        alloc_by_class[ac] += abs(float(p.quantity or 0) * float(price or 0))
    alloc_by_class["cash"] = float(portfolio.cash_available or 0)
    alloc_total = sum(alloc_by_class.values()) or 1.0
    allocation = sorted(
        # "key" is the donut partial's contract; asset_class stays for the
        # table that reads the same rows.
        ({"asset_class": k, "key": k, "value": v,
          "pct": round(v / alloc_total * 100, 1)}
         for k, v in alloc_by_class.items() if v > 0),
        key=lambda r: r["value"], reverse=True,
    )

    # 30d Sharpe / Sortino approximations from PortfolioSnapshot.daily_pnl_pct.
    sharpe = sortino = None
    try:
        rets = [float(s.daily_pnl_pct or 0) for s in
                PortfolioSnapshot.objects.filter(
                    portfolio=portfolio, date__gte=cutoff_30d)]
        if len(rets) >= 5:
            mean = sum(rets) / len(rets)
            var = sum((r - mean) ** 2 for r in rets) / len(rets)
            std = var ** 0.5
            sharpe = round((mean / std) * (252 ** 0.5), 2) if std > 0 else None
            downside = [r for r in rets if r < 0]
            if downside:
                d_var = sum(r ** 2 for r in downside) / len(downside)
                d_std = d_var ** 0.5
                sortino = round((mean / d_std) * (252 ** 0.5), 2) if d_std > 0 else None
    except Exception as e:
        logger.warning("Op Center Sharpe/Sortino unavailable: %s", e,
                       exc_info=True)

    context = {
        "portfolio": portfolio,
        "open_positions": open_positions[:20],
        "open_positions_total": len(open_positions),
        "total_unrealized": total_unrealized,
        "cash_pct": cash_pct,
        "exposure_pct": 100 - cash_pct,
        # None all the way down where there is nothing to measure. These were
        # all zeros before: a 0.0% win rate over zero trades is a claim that
        # every trade lost, and a 0.00 profit factor reads as a broken system
        # rather than an unmeasured one.
        "win_rate": round(win_rate, 1) if win_rate is not None else None,
        "n_closed": total_closed,
        "n_ungraded": n_ungraded,
        "n_winning": len(winning),
        "n_losing": len(losing),
        "avg_win": round(avg_win, 2) if avg_win is not None else None,
        "avg_loss": round(avg_loss, 2) if avg_loss is not None else None,
        "profit_factor": (round(profit_factor, 2)
                          if profit_factor is not None else None),
        "best_trades": best_trades,
        "worst_trades": worst_trades,
        # A book with no snapshot has no measured drawdown. "0.00%" under a
        # MAX DRAWDOWN label reads as "never lost money".
        "max_drawdown": (float(latest_snapshot.max_drawdown)
                          if latest_snapshot is not None
                          and latest_snapshot.max_drawdown is not None
                          else None),
        "sharpe_30d": sharpe,
        "sortino_30d": sortino,
        "equity_points": equity_points,
        "equity_min": min(equity_points) if equity_points else 0,
        "equity_max": max(equity_points) if equity_points else 0,
        "allocation": allocation,
    }
    return render(request, "dashboard/_command_portfolio.html", context)


@login_required
def command_tab_history(request):
    """HISTORY tab — closed trade analytics + per-rule track record."""
    from bot_program.models import AssetBotTrade

    cutoff = timezone.now() - timedelta(days=90)
    closed = (AssetBotTrade.objects
              .filter(config__user=request.user, status="CLOSED",
                       closed_at__gte=cutoff)
              .order_by("-closed_at"))
    n_closed = closed.count()
    # Graded trades only. A close with no realized_r (no stop recorded, so no
    # initial risk to normalise by) can never be a win, and putting it in the
    # denominator quietly drags the win rate down by however many of them
    # there are — the sub-label now names the graded population.
    graded = closed.filter(realized_r__isnull=False)
    n_graded = graded.count()
    total_r = graded.aggregate(s=Sum("realized_r"))["s"]
    n_wins = graded.filter(realized_r__gt=0).count()
    win_rate = (n_wins / n_graded * 100) if n_graded else None

    # .order_by() before .values(): an ordering in force when values() runs
    # rides into the GROUP BY and shatters the aggregate into one row per
    # trade. The trailing order_by happens to clear it here, but the pattern
    # only stays safe by accident, and this queryset is reused above.
    by_rule = (closed.exclude(rule_name="")
               .order_by()
               .values("rule_name", "asset_class")
               .annotate(n=Count("id"),
                         avg_r=Avg("realized_r"),
                         total_pnl=Sum("pnl"))
               .order_by("-total_pnl")[:20])

    # Cumulative R curve — sort by close time, running sum.
    cum_r_rows = list(
        closed.filter(realized_r__isnull=False)
        .order_by("closed_at")
        .values_list("closed_at", "realized_r")
    )
    cum_r_points: list[float] = []
    running = 0.0
    for _, r in cum_r_rows:
        running += float(r)
        cum_r_points.append(round(running, 4))

    # Rolling 30d win-rate per closed_at date.
    win_rate_points: list[float] = []
    by_date: dict = defaultdict(list)
    for closed_at, r in cum_r_rows:
        by_date[closed_at.date()].append(float(r))
    sorted_dates = sorted(by_date.keys())
    window = 30
    for d in sorted_dates:
        start = d - timedelta(days=window)
        recent = [r for dt in sorted_dates if start <= dt <= d
                   for r in by_date[dt]]
        if recent:
            wr = sum(1 for r in recent if r > 0) / len(recent) * 100
            win_rate_points.append(round(wr, 1))

    # Day-of-week heatmap data: count + avg R per Mon-Sun.
    dow_stats = [{"label": d, "n": 0, "avg_r": 0.0, "total_r": 0.0}
                  for d in ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]]
    for closed_at, r in cum_r_rows:
        idx = closed_at.weekday()
        dow_stats[idx]["n"] += 1
        dow_stats[idx]["total_r"] += float(r)
    for d in dow_stats:
        # A weekday with no closes has no average, and "0.0R" in the same
        # slot a real average occupies reads as a break-even day.
        d["avg_r"] = round(d["total_r"] / d["n"], 3) if d["n"] > 0 else DASH

    # Top rules by Sharpe-like metric (avg_r / stdev).
    rule_stats: dict = defaultdict(list)
    for t in closed.filter(realized_r__isnull=False).only(
            "rule_name", "realized_r"):
        if t.rule_name:
            rule_stats[t.rule_name].append(float(t.realized_r))
    top_rules_sharpe = []
    for name, rs in rule_stats.items():
        if len(rs) < 5:
            continue
        m = sum(rs) / len(rs)
        v = sum((r - m) ** 2 for r in rs) / len(rs)
        s = v ** 0.5
        if s > 0:
            top_rules_sharpe.append({
                "rule_name": name, "n": len(rs),
                "avg_r": round(m, 3), "sharpe": round(m / s, 3),
            })
    top_rules_sharpe.sort(key=lambda r: r["sharpe"], reverse=True)
    top_rules_sharpe = top_rules_sharpe[:5]

    decay_alerts = []
    try:
        from bot_program.models import RuleTrackRecordAlert
        decay_alerts = list(
            RuleTrackRecordAlert.objects
            .filter(user=request.user, resolved_at__isnull=True)
            .order_by("-detected_at")[:10]
        )
    except Exception as e:
        logger.warning("Op Center decay alerts unavailable: %s", e,
                       exc_info=True)

    context = {
        "n_closed": n_closed,
        "n_graded": n_graded,
        "win_rate": round(win_rate, 1) if win_rate is not None else None,
        "total_r": round(float(total_r), 2) if total_r is not None else None,
        "n_wins": n_wins,
        "by_rule": list(by_rule),
        "decay_alerts": decay_alerts,
        "recent_closed": list(closed.select_related("config")[:30]),
        "cum_r_points": cum_r_points,
        "cum_r_min": min(cum_r_points) if cum_r_points else 0,
        "cum_r_max": max(cum_r_points) if cum_r_points else 0,
        "win_rate_points": win_rate_points,
        "dow_stats": dow_stats,
        "dow_max_n": max((d["n"] for d in dow_stats), default=0),
        "top_rules_sharpe": top_rules_sharpe,
    }
    return render(request, "dashboard/_command_history.html", context)


@login_required
def command_tab_bots(request):
    """BOTS tab — per-AssetBotConfig overview with heartbeat + cooldown."""
    from bot_program.models import AssetBotConfig, AssetBotTrade

    configs = list(AssetBotConfig.objects.filter(user=request.user)
                    .order_by("asset_class", "name"))
    rows = []
    now = timezone.now()
    for cfg in configs:
        open_n = AssetBotTrade.objects.filter(config=cfg, status__in=("OPEN", "CLOSE_PENDING")).count()
        since_24h = now - timedelta(hours=24)
        closed_24h = AssetBotTrade.objects.filter(
            config=cfg, status="CLOSED", closed_at__gte=since_24h)
        opens_24h = AssetBotTrade.objects.filter(
            config=cfg, opened_at__gte=since_24h).count()
        # Sum() over no rows is None. Coercing it to Decimal("0") printed a
        # flat "0.00" in the P&L column for a bot that closed nothing at all,
        # which is indistinguishable from a bot that traded and broke even.
        pnl_24h = closed_24h.aggregate(s=Sum("pnl"))["s"]

        last_close = (AssetBotTrade.objects
                       .filter(config=cfg, status="CLOSED",
                                closed_at__isnull=False)
                       .order_by("-closed_at").only("closed_at").first())
        cooldown_remaining_min = 0
        if last_close and (cfg.cool_down_minutes or 0) > 0:
            elapsed_min = (now - last_close.closed_at).total_seconds() / 60
            cooldown_remaining_min = max(
                0, int(cfg.cool_down_minutes - elapsed_min))

        # Liveness from last trade activity (AssetBot beat is Phase 13.5 every 5min).
        last_open_obj = (AssetBotTrade.objects
                         .filter(config=cfg)
                         .order_by("-opened_at").only("opened_at").first())
        candidates = []
        if last_open_obj is not None and last_open_obj.opened_at:
            candidates.append(last_open_obj.opened_at)
        if last_close is not None and last_close.closed_at:
            candidates.append(last_close.closed_at)
        last_activity = max(candidates) if candidates else None
        is_alive = (
            last_activity is not None
            and (now - last_activity).total_seconds() < 6 * 3600
        )

        rows.append({
            "config": cfg,
            "open_count": open_n,
            "opens_24h": opens_24h,
            "closed_24h": closed_24h.count(),
            "pnl_24h": pnl_24h,
            "cooldown_remaining_min": cooldown_remaining_min,
            "last_activity": last_activity,
            "is_alive": is_alive,
        })

    context = {
        "rows": rows,
        "n_configs": len(configs),
        # With no configs at all there is no population to count enabled,
        # live-mode or alive members of — an em-dash, not four confident
        # zeros under four labels.
        "n_enabled": (sum(1 for c in configs if c.enabled) if configs else DASH),
        "n_live": (sum(1 for c in configs if c.enabled and c.mode == "live")
                   if configs else DASH),
        "n_alive": (sum(1 for r in rows if r["is_alive"]) if rows else DASH),
    }
    return render(request, "dashboard/_command_bots.html", context)
