"""The System Map — Sauron drawn as a machine you can reach into.

The first version of this page was a list of cards. Cards tell you the state of
each part and nothing about how the parts are joined, which is the half of the
picture you need when something upstream has quietly stopped and three things
downstream look broken.

So this is a topology. The Eye sits in the middle because that is what it is —
everything to its left is the platform gathering evidence, everything to its
right is the platform acting on it, and the loop underneath is what it learns
from having acted. Every node carries its own switch, so the map is not a
report you read and then go elsewhere to act on.

The layer a component belongs to, and what it writes, is declared in WIRING
below rather than guessed from its name — a component called "TradingView
Ideas" wrote nothing at all for as long as it existed, and a map that inferred
an edge from the name would have drawn a lie.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.decorators import login_required, user_passes_test
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

LAYERS = [
    {"key": "ingest",  "title": "Ingest",  "side": "left",
     "blurb": "Evidence arriving from outside."},
    {"key": "enrich",  "title": "Enrich",  "side": "left",
     "blurb": "Raw rows become features."},
    {"key": "eye",     "title": "The Eye", "side": "centre",
     "blurb": "Where evidence becomes an opinion."},
    {"key": "gate",    "title": "Gate",    "side": "right",
     "blurb": "The last chance to say no."},
    {"key": "execute", "title": "Execute", "side": "right",
     "blurb": "The only stage that spends money."},
    {"key": "learn",   "title": "Learn",   "side": "loop",
     "blurb": "What it does with the outcome."},
]

# key -> where it sits, what it writes, and what it feeds.
#
# Traced, not guessed. An earlier hand-written version of this table claimed
# pipeline_indicators feeds pipeline_signals; it does not — every rule loads
# its own bars through signals/smc/dataframe.load_ohlcv, and the indicator
# table's only machine consumer is the bot's ATR sizing in risk_levels.py. A
# map that draws an edge nobody traced is a map that lies confidently, which
# is the failure mode this whole page exists to correct.
#
# `feeds` names other node keys. An edge is drawn only when both ends exist,
# so a component whose output nothing consumes is left visibly unconnected —
# that is a finding, not an oversight.
#
# `note` carries what the trace found that a run record cannot show: a missing
# credential, an unreachable write, a task that does not exist.
WIRING = {
    # ── ingest ────────────────────────────────────────────────────────
    "scraper_live_quotes":  {"layer": "ingest", "writes": ["LiveQuote"], "feeds": ["execute_bots", "kill_switch"],
                             "note": "Universe is watchlist + enabled-bot symbols; with no watchlist flagged it polls a short list."},
    "scraper_crypto":       {"layer": "ingest", "writes": ["LiveQuote"], "feeds": ["execute_bots", "kill_switch", "pipeline_opportunity_scanner"],
                             "note": "Keyless Binance public ticker — the healthiest feed on the platform."},
    "scraper_commodities":  {"layer": "ingest", "writes": ["LiveQuote"], "feeds": ["execute_bots", "kill_switch", "pipeline_opportunity_scanner"],
                             "note": "Universe is the commodity catalogue through the shared Yahoo symbol map. The LME base metals and the gold crosses have no free source and are skipped by name rather than warned about forever."},
    "scraper_forex":        {"layer": "ingest", "writes": ["LiveQuote"], "feeds": ["execute_bots", "kill_switch", "pipeline_opportunity_scanner"],
                             "note": "Alpha Vantage first when a key is configured (25/day, budgeted in-task); every pair the budget does not reach gets a keyless yfinance mark, so a forex bot always has a price to measure its stop against."},
    "scraper_indices":      {"layer": "ingest", "writes": ["LiveQuote"], "feeds": ["pipeline_opportunity_scanner"],
                             "note": "Indices have no bot class, so nothing here reaches execution — the dashboard headband and the scanner are the consumers."},
    "scraper_eod":          {"layer": "ingest", "writes": ["PriceData 1d"], "feeds": ["pipeline_indicators", "pipeline_opportunity_scanner"],
                             "note": "Has never run: zero PriceData rows carry timeframe=1d. All 5,600 bars come from the bot-bar refresh instead."},
    "feed_bot_bars":        {"layer": "ingest", "writes": ["PriceData 1h/4h"], "feeds": ["pipeline_indicators", "pipeline_signals", "execute_bots"],
                             "synthetic": True, "task": "market_data.tasks.refresh_bot_bars_task", "interval": 600,
                             "note": "The actual writer of every bar the rule layer reads — scheduled, ungated, and absent from the component registry, so there is no switch for it. Its universe is the enabled bots PLUS starred instruments (keyless feeds), so the star delivers bars as well as quotes."},
    "scraper_news":         {"layer": "ingest", "writes": ["NewsArticle"], "feeds": ["agent_news_analyst"]},
    "scraper_crypto_news":  {"layer": "ingest", "writes": ["NewsArticle"], "feeds": ["agent_news_analyst"]},
    "scraper_sentiment":    {"layer": "ingest", "writes": ["SentimentSnapshot"], "feeds": ["pipeline_sentiment_agg", "pipeline_opportunity_scanner"],
                             "note": "Reddit half needs REDDIT_CLIENT_ID/SECRET; the StockTwits half is keyless and now wired."},
    "scraper_tradingview":  {"layer": "ingest", "writes": ["SentimentSnapshot"], "feeds": ["pipeline_sentiment_agg", "pipeline_opportunity_scanner"]},
    "scraper_calendar":     {"layer": "ingest", "writes": ["EconomicEvent"], "feeds": ["execute_bots", "pipeline_opportunity_scanner"],
                             "note": "Needs FMP_API_KEY. While this table is empty the bot's earnings blackout cannot fire."},
    "scraper_sec":          {"layer": "ingest", "writes": ["InstitutionalFiling"], "feeds": ["pipeline_opportunity_scanner"],
                             "note": "Form-4 issuers resolve to catalogue instruments through SEC's CIK map, so insider rows reach the evaluator. 13F rows stay filer-level (the holdings live in an attachment this scraper does not follow) and are unlinked by design."},
    "scraper_cot":          {"layer": "ingest", "writes": ["COTReport"], "feeds": ["pipeline_opportunity_scanner"],
                             "note": "Reads the CFTC legacy sources in their verified formats (the old code decoded an Excel workbook as text, so it stored zero rows for its whole life). Market names map to catalogue symbols by exact name."},
    "scraper_fred":         {"layer": "ingest", "writes": ["MacroIndicator"], "feeds": ["pipeline_opportunity_scanner"],
                             "note": "Writes indicator shells; zero observations have ever landed."},
    "scraper_etoro":        {"layer": "ingest", "writes": ["Position"], "feeds": ["pipeline_exposure", "pipeline_snapshot"],
                             "note": "No task and no schedule — reachable only from the manual Sync button, which never checks this switch."},

    # ── enrich ────────────────────────────────────────────────────────
    "pipeline_indicators":    {"layer": "enrich", "writes": ["TechnicalIndicator"], "feeds": ["execute_bots"],
                               "note": "Feeds the bot's ATR sizing only. The signal rules do NOT read this table — they load their own bars."},
    "agent_news_analyst":     {"layer": "enrich", "writes": ["NewsArticle.ai_*"], "feeds": ["pipeline_opportunity_scanner"],
                               "note": "Needs ANTHROPIC_API_KEY. Instrument tagging also happens keylessly at ingest."},
    "pipeline_sentiment_agg": {"layer": "enrich", "writes": ["SentimentSnapshot"], "feeds": ["pipeline_opportunity_scanner"]},

    # ── the eye: where it decides ─────────────────────────────────────
    "pipeline_signals":             {"layer": "eye", "writes": ["Signal", "SmcSignal"], "feeds": ["gate_orchestrator", "execute_bots"]},
    "pipeline_opportunity_scanner": {"layer": "eye", "writes": ["OpportunityFlag"], "feeds": ["execute_bots"]},
    "pipeline_event_engine":        {"layer": "eye", "writes": ["Signal", "FastEvent"], "feeds": ["execute_bots"],
                                     "note": "The switch gates the async dispatch wrapper (dispatch_event_task). Direct synchronous dispatch_event calls bypass it by design, so the admin test-fire button works even with the platform stopped."},
    "agent_strategy":               {"layer": "eye", "writes": ["StrategyAdjustment"], "feeds": [],
                                     "note": "Needs ANTHROPIC_API_KEY. Its adjustments are written and rendered nowhere."},
    "agent_anomaly":                {"layer": "eye", "writes": ["AgentTask"], "feeds": [],
                                     "note": "Needs ANTHROPIC_API_KEY. Produces prose for a human, nothing machine-readable."},

    # ── gate ──────────────────────────────────────────────────────────
    "kill_switch":              {"layer": "gate", "writes": ["forced closes"], "feeds": ["execute_bots"],
                                 "synthetic": True,
                                 "note": "Deliberately ungated: it must keep working when everything else is switched off. Operator-triggered only."},
    "feature_ai_pretrade_gate": {"layer": "gate", "writes": ["AgentPrediction"], "feeds": [],
                                 "note": "Consulted only by the legacy crypto bot, which is itself unscheduled."},
    "pipeline_exposure":        {"layer": "gate", "writes": ["Portfolio.current_value", "Position marks"], "feeds": ["execute_bots"],
                                 "note": "Marks open positions to market (current_price + unrealized P&L, day-fresh data only), then recomputes exposure. The three per-category breakdowns are still returned without being stored."},

    # ── learn ─────────────────────────────────────────────────────────
    "pipeline_snapshot":        {"layer": "learn", "writes": ["PortfolioSnapshot"], "feeds": ["eye_core"],
                                 "note": "Drawdown and daily P&L are computed from these; with none taken, both read as unknown platform-wide."},
    "pipeline_calibration":     {"layer": "learn", "writes": ["RuleControl"], "feeds": ["pipeline_signals"]},
    "pipeline_actuator":        {"layer": "learn", "writes": ["RuleControl"], "feeds": ["pipeline_signals", "execute_bots"]},
    "pipeline_meta_allocator":  {"layer": "learn", "writes": ["RuleControl.weight"], "feeds": ["execute_bots"]},
    "pipeline_promotion":       {"layer": "learn", "writes": ["RuleControl.stage"], "feeds": ["pipeline_signals", "execute_bots"]},
    "pipeline_ai_decay":        {"layer": "learn", "writes": ["RuleControl"], "feeds": ["pipeline_actuator"],
                                 "note": "Needs ANTHROPIC_API_KEY."},
    "pipeline_ai_journal":      {"layer": "learn", "writes": ["Signal.journal"], "feeds": [],
                                 "note": "Event-driven from signal grading rather than scheduled, which is correct."},
    "pipeline_evolution":       {"layer": "learn", "writes": [], "feeds": [],
                                 "note": "Writes nothing — there is no proposal for it to read."},
    "pipeline_pattern_miner":   {"layer": "learn", "writes": [], "feeds": ["pipeline_opportunity_scanner"]},
    "agent_daily_briefing":     {"layer": "learn", "writes": ["AgentTask"], "feeds": [], "note": "Needs ANTHROPIC_API_KEY."},
    "agent_weekly_review":      {"layer": "learn", "writes": ["AgentTask"], "feeds": [], "note": "Needs ANTHROPIC_API_KEY."},
    "agent_optimization":       {"layer": "learn", "writes": ["StrategyAdjustment"], "feeds": [], "note": "Needs ANTHROPIC_API_KEY."},
    "agent_monday_plan":        {"layer": "learn", "writes": ["AgentTask"], "feeds": [], "note": "Needs ANTHROPIC_API_KEY."},
}

# Components whose only job is to be a mode flag on another component. Drawn as
# a toggle inside their parent rather than as a node of their own, because they
# have no task, no schedule and no output — as nodes they would be four boxes
# with no edges, which reads as four broken things.
MODE_FLAGS = {
    "actuator_mode_live": "pipeline_actuator",
    "meta_allocator_mode_live": "pipeline_meta_allocator",
}

STATE_META = {
    "broken":  {"label": "BROKEN", "glyph": "✕", "tone": "critical"},
    "stale":   {"label": "STALE",  "glyph": "▲", "tone": "serious"},
    "silent":  {"label": "SILENT", "glyph": "◌", "tone": "warning"},
    "off":     {"label": "OFF",    "glyph": "⏻", "tone": "muted"},
    "idle":    {"label": "IDLE",   "glyph": "·", "tone": "muted"},
    "live":    {"label": "LIVE",   "glyph": "●", "tone": "good"},
}
STATE_ORDER = ["broken", "stale", "silent", "off", "idle", "live"]


def _fmt_age(seconds):
    if seconds is None:
        return "never"
    if seconds < 90:
        return f"{int(seconds)}s"
    if seconds < 5400:
        return f"{int(seconds / 60)}m"
    if seconds < 172800:
        return f"{int(seconds / 3600)}h"
    return f"{int(seconds / 86400)}d"


def _age(dt):
    return None if dt is None else max(0.0, (timezone.now() - dt).total_seconds())


def _component_state(comp):
    """A component's state, from its own run record.

    The distinction that matters and that the registry never drew: a task can
    run, not raise, and store nothing. The gate now records that as 'warning',
    and here it becomes SILENT — present, running, producing nothing.
    """
    if not comp.is_enabled:
        return "off", "Switched off."
    status = (comp.last_status or "").lower()
    # No truncation: the model already caps last_message at 500 chars, and a
    # clipped reason in the inspector is a reason the operator cannot act on.
    if status == "error":
        return "broken", f"Last run failed: {comp.last_message or ''}"
    if status == "warning":
        return "silent", f"Ran, stored nothing: {comp.last_message or ''}"
    if not comp.last_run_at:
        return "idle", "Enabled, but has never run."
    age = _age(comp.last_run_at)
    if age and age > 172800:
        return "stale", f"Last ran {_fmt_age(age)} ago."
    return "live", f"Ran {_fmt_age(age)} ago · {comp.run_count} runs, {comp.error_count} errors."


def _synthetic_node(key, wiring):
    """A real moving part that the component registry does not know about.

    Two of these matter enough to draw. The bar refresh writes every price bar
    the rule layer reads and has no registry entry, so there is no switch for
    it anywhere in the admin panel — a map that omitted it would show the
    signal layer being fed by a scraper that has never run. The kill switch is
    deliberately ungated for the opposite reason: it must keep working when
    everything else is off.

    They carry can_toggle=False because there is genuinely nothing to toggle,
    which is itself worth seeing.
    """
    state, why, metric, label = "unknown", "", None, ""

    if key == "feed_bot_bars":
        try:
            from market_data.models import PriceData
            total = PriceData.objects.count()
            newest = PriceData.objects.aggregate(m=Max("timestamp"))["m"]
            age = _age(newest)
            metric, label = total, "bars"
            if total == 0:
                state, why = "idle", "No bars have ever been written."
            elif age is not None and age > 172800:
                state, why = "stale", f"{total:,} bars, newest {_fmt_age(age)} old — the refresh has stopped."
            else:
                state, why = "live", f"{total:,} bars, newest {_fmt_age(age)} old."
        except Exception:                                    # pragma: no cover
            state, why = "unknown", "Could not read the bar table."
    elif key == "kill_switch":
        try:
            from bot_program.models import AssetBotTrade
            pending = AssetBotTrade.objects.filter(status="CLOSE_PENDING").count()
            metric, label = pending, "stranded"
            if pending:
                state, why = "broken", f"{pending} position(s) failed to close and are still open at the broker."
            else:
                state, why = "idle", "Armed and unused — nothing is stranded."
        except Exception:                                    # pragma: no cover
            state, why = "unknown", "Could not read the trade table."

    return {
        "key": key, "kind": "synthetic", "label": key.replace("_", " ").title(),
        "purpose": wiring.get("note", ""), "layer": wiring["layer"],
        "category": "unregistered", "state": state, "why": why,
        "meta": STATE_META.get(state, STATE_META["idle"]),
        "enabled": True, "writes": wiring["writes"], "feeds": wiring["feeds"],
        "last_run": "—", "last_status": "not in the component registry",
        "last_message": "", "runs": 0, "errors": 0, "flags": [],
        "can_toggle": False, "note": wiring.get("note", ""),
        "metric": metric, "metric_label": label,
    }


def build_topology(user):
    """Nodes, edges and live state for the map."""
    from core.platform_control import PlatformComponent

    comps = {c.key: c for c in PlatformComponent.objects.all()}
    nodes = []

    for key, wiring in WIRING.items():
        comp = comps.get(key)
        if comp is None:
            if wiring.get("synthetic"):
                nodes.append(_synthetic_node(key, wiring))
            continue
        state, why = _component_state(comp)
        flags = [
            {"key": fk, "label": comps[fk].name, "on": comps[fk].is_enabled}
            for fk, parent in MODE_FLAGS.items()
            if parent == key and fk in comps
        ]
        nodes.append({
            "key": key,
            "kind": "component",
            "label": comp.name,
            "purpose": comp.description,
            "layer": wiring["layer"],
            "category": comp.category,
            "state": state, "why": why,
            "meta": STATE_META[state],
            "enabled": comp.is_enabled,
            "writes": wiring["writes"],
            "feeds": wiring["feeds"],
            "last_run": _fmt_age(_age(comp.last_run_at)),
            "last_status": comp.last_status or "never run",
            "last_message": comp.last_message or "",
            "runs": comp.run_count, "errors": comp.error_count,
            "flags": flags,
            "can_toggle": True,
            # What the trace found that a run record cannot show: a missing
            # credential, an unreachable write, a task that does not exist.
            "note": wiring.get("note", ""),
        })

    # ── The Eye itself ────────────────────────────────────────────────
    # Not a component: it is the union of what the deciding layer produced, and
    # the master switch that can stop all of it.
    try:
        from signals.models import Signal
        day_ago = timezone.now() - timedelta(hours=24)
        active = Signal.objects.filter(is_active=True).count()
        r24 = Signal.objects.filter(created_at__gte=day_ago).count()
        newest = Signal.objects.aggregate(m=Max("created_at"))["m"]
    except Exception:                                        # pragma: no cover
        active = r24 = 0
        newest = None

    master = comps.get("platform_master")
    master_on = bool(master and master.is_enabled)
    if not master_on:
        eye_state, eye_why = "off", "The master switch is off — nothing is running."
    elif r24:
        eye_state, eye_why = "live", f"{active} active signals, {r24} raised in 24h."
    elif active:
        eye_state, eye_why = "idle", f"{active} active signals, none new in 24h."
    else:
        eye_state, eye_why = "idle", "No active signals."

    nodes.append({
        "key": "eye_core", "kind": "eye", "label": "THE EYE",
        "purpose": "Everything left of here is evidence. Everything right of here is action.",
        "layer": "eye", "category": "system",
        "state": eye_state, "why": eye_why, "meta": STATE_META[eye_state],
        "enabled": master_on,
        "writes": ["Signal"], "feeds": ["gate_orchestrator"],
        "last_run": _fmt_age(_age(newest)),
        "last_status": "master " + ("armed" if master_on else "OFF"),
        "last_message": "", "runs": active, "errors": 0, "flags": [],
        "can_toggle": True, "toggle_key": "platform_master",
        "metric": active, "metric_label": "active signals",
    })

    # ── The gate ──────────────────────────────────────────────────────
    try:
        from bot_program.models import OrchestratorEvent
        day_ago = timezone.now() - timedelta(hours=24)
        recent = OrchestratorEvent.objects.filter(created_at__gte=day_ago)
        n = recent.count()
        rejects = recent.filter(decision="reject").count()
        if not master_on:
            g_state, g_why = "off", "Master switch is off."
        elif n == 0:
            g_state, g_why = "idle", "No decisions in 24h — nothing reached the gate."
        elif n and rejects / n >= 0.95:
            g_state, g_why = "stale", f"{rejects} of {n} rejected — almost everything is blocked."
        else:
            g_state, g_why = "live", f"{n} decisions in 24h, {rejects} rejected."
        nodes.append({
            "key": "gate_orchestrator", "kind": "gate", "label": "Risk gate",
            "purpose": "The last check before an order leaves the platform.",
            "layer": "gate", "category": "system",
            "state": g_state, "why": g_why, "meta": STATE_META[g_state],
            "enabled": master_on, "writes": ["OrchestratorEvent"],
            "feeds": ["execute_bots"], "last_run": "—",
            "last_status": "", "last_message": "", "runs": n, "errors": rejects,
            "flags": [], "can_toggle": False,
            "metric": n, "metric_label": "decisions 24h",
            "link": "/eye/gate-events/",
        })
    except Exception:                                        # pragma: no cover
        pass

    # ── The bots ──────────────────────────────────────────────────────
    try:
        from bot_program.models import AssetBotConfig, AssetBotTrade
        for cfg in AssetBotConfig.objects.filter(user=user).order_by("asset_class"):
            open_n = AssetBotTrade.objects.filter(config=cfg, status="OPEN").count()
            pending = AssetBotTrade.objects.filter(
                config=cfg, status="CLOSE_PENDING").count()
            last = AssetBotTrade.objects.filter(config=cfg).aggregate(
                m=Max("opened_at"))["m"]
            if pending:
                b_state = "broken"
                b_why = f"{pending} close(s) failed — still open at the broker."
            elif not cfg.enabled:
                b_state, b_why = "off", "Disabled."
            elif open_n:
                b_state, b_why = "live", f"{open_n} open, last entry {_fmt_age(_age(last))} ago."
            elif last and _age(last) < 172800:
                b_state, b_why = "live", f"Flat, last entry {_fmt_age(_age(last))} ago."
            else:
                b_state, b_why = "idle", "Enabled, nothing opened recently."
            nodes.append({
                "key": f"bot_{cfg.id}", "kind": "bot", "label": cfg.name or cfg.asset_class,
                "purpose": f"{cfg.asset_class} engine · {cfg.mode}",
                "layer": "execute", "category": "bot",
                "state": b_state, "why": b_why, "meta": STATE_META[b_state],
                "enabled": cfg.enabled, "writes": ["AssetBotTrade"], "feeds": [],
                "last_run": _fmt_age(_age(last)), "last_status": cfg.mode,
                "last_message": "", "runs": open_n, "errors": pending, "flags": [],
                "can_toggle": True, "config_id": cfg.id,
                "mode": cfg.mode, "paper": cfg.mode == "paper",
                "metric": open_n, "metric_label": "open",
                "link": "/asset-bots/",
                "actions": ["shadow", "reset-circuit", "reconcile"],
            })
    except Exception:                                        # pragma: no cover
        pass

    # A fleet node so ingest has somewhere to point even with no bots defined.
    if not any(n["kind"] == "bot" for n in nodes):
        nodes.append({
            "key": "execute_bots", "kind": "bot", "label": "Bots",
            "purpose": "No bots are configured for this account.",
            "layer": "execute", "category": "bot",
            "state": "idle", "why": "Nothing to run.", "meta": STATE_META["idle"],
            "enabled": False, "writes": [], "feeds": [], "last_run": "never",
            "last_status": "", "last_message": "", "runs": 0, "errors": 0,
            "flags": [], "can_toggle": False, "link": "/asset-bots/",
        })

    by_key = {n["key"]: n for n in nodes}
    bot_keys = [n["key"] for n in nodes if n["kind"] == "bot"]

    edges = []
    for n in nodes:
        for target in n.get("feeds", []):
            # "execute_bots" is a stand-in for the fleet: fan it out to each
            # real bot so the drawn edge matches what actually consumes.
            targets = bot_keys if target == "execute_bots" and bot_keys else [target]
            for t in targets:
                if t in by_key and t != n["key"]:
                    edges.append({
                        "from": n["key"], "to": t,
                        "via": ", ".join(n["writes"]) or "—",
                        # An edge is only carrying data if its source is.
                        "live": n["state"] == "live",
                    })

    counts = {k: 0 for k in STATE_ORDER}
    for n in nodes:
        counts[n["state"]] += 1

    orphans = [n["key"] for n in nodes
               if n["kind"] == "component"
               and not any(e["from"] == n["key"] for e in edges)]

    return {
        "layers": LAYERS, "nodes": nodes, "edges": edges,
        "counts": counts, "orphans": orphans,
        "state_meta": STATE_META,
        "legend": [{"key": k, "count": counts[k], **STATE_META[k]} for k in STATE_ORDER],
        "master_on": master_on,
        "generated_at": timezone.now(),
    }


@login_required
@user_passes_test(lambda u: u.is_staff)
def system_map(request):
    ctx = build_topology(request.user)
    ctx["page_id"] = "hq"
    # Nodes grouped by layer, so the template lays out columns without needing
    # a custom filter to index by key.
    ctx["columns"] = [
        {**layer, "nodes": [n for n in ctx["nodes"] if n["layer"] == layer["key"]]}
        for layer in LAYERS
    ]
    # The map shows how the machine is wired; this says which part to look at
    # first. It measures the data stores directly rather than the component
    # switches, which is how it catches a task that reports success and writes
    # nothing.
    try:
        from dashboard.views_system_map import collect_system_map
        ctx["problems"] = collect_system_map(request.user)["problems"]
    except Exception:                                        # pragma: no cover
        ctx["problems"] = []

    # Handed to the browser through json_script, not interpolated: a Python
    # dict rendered into a <script> is repr(), which is not JSON — single
    # quotes, True, None — and would be a syntax error the moment a node
    # carried an apostrophe.
    ctx["nodes_payload"] = ctx["nodes"]
    ctx["edges_payload"] = ctx["edges"]
    return render(request, "dashboard/system_map.html", ctx)


@login_required
@user_passes_test(lambda u: u.is_staff)
def system_map_state(request):
    """Live state only, for the map's own refresh.

    Re-rendering the whole page would lose the inspector, the hover highlight
    and the scroll position every fifteen seconds.
    """
    topo = build_topology(request.user)
    return JsonResponse({
        "nodes": [{"key": n["key"], "state": n["state"], "why": n["why"],
                   "enabled": n["enabled"], "meta": n["meta"],
                   "last_run": n["last_run"], "metric": n.get("metric")}
                  for n in topo["nodes"]],
        "edges": [{"from": e["from"], "to": e["to"], "live": e["live"]}
                  for e in topo["edges"]],
        "counts": topo["counts"],
        "master_on": topo["master_on"],
    })


@login_required
@user_passes_test(lambda u: u.is_superuser)
@require_POST
def system_map_toggle(request):
    """Switch one node from the map itself.

    Superuser only, and deliberately narrower than the page: reading the map
    is a staff activity, arming and disarming the platform is not.

    The existing admin toggle redirects to the dashboard, which would throw
    away the map. This returns the new state so the node can update in place.
    """
    kind = request.POST.get("kind", "component")
    key = request.POST.get("key", "")

    if kind == "bot":
        from bot_program.models import AssetBotConfig
        cfg = AssetBotConfig.objects.filter(pk=key, user=request.user).first()
        if cfg is None:
            return JsonResponse({"ok": False, "error": "bot not found"}, status=404)
        cfg.enabled = not cfg.enabled
        cfg.save(update_fields=["enabled"])
        return JsonResponse({"ok": True, "enabled": cfg.enabled,
                             "label": cfg.name or cfg.asset_class})

    from core.platform_control import PlatformComponent
    comp = PlatformComponent.objects.filter(key=key).first()
    if comp is None:
        return JsonResponse({"ok": False, "error": f"no component '{key}'"}, status=404)
    comp.is_enabled = not comp.is_enabled
    comp.save(update_fields=["is_enabled"])
    return JsonResponse({"ok": True, "enabled": comp.is_enabled, "label": comp.name})
