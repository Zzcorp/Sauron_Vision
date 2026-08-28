"""System health — is the machine actually running?

This platform can fail silently in ways a P&L number never shows: a beat
entry pointing at an unregistered task, a streamer that froze, bars that
stopped arriving so every rule returns HOLD, a live position stranded in
CLOSE_PENDING, a live bot quietly falling back to paper. Each of those has
bitten this codebase. This page surfaces all of them in one place.

Every check returns the same shape:
    {key, label, state: ok|warn|fail, detail, hint}
so the template renders them uniformly and new checks are cheap to add.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Max
from django.shortcuts import render
from django.utils import timezone

# Bars older than this mean the rule layer is deciding on stale structure.
BAR_STALE_SECONDS = 3 * 3600
QUOTE_STALE_SECONDS = 900
HEARTBEAT_STALE_SECONDS = 1800


def _check(key, label, state, detail, hint="", configured=True):
    """One health row.

    `configured=False` marks a check that passes only because there is
    nothing for it to look at — no bots, no feeds, no positions. Both render
    green, and conflating them is how a platform where nothing is set up
    reports HEALTHY in the same colour as one that is working. The page
    needs to be able to tell them apart.
    """
    return {"key": key, "label": label, "state": state,
            "detail": detail, "hint": hint, "configured": configured}


def _age(dt) -> float | None:
    return None if dt is None else (timezone.now() - dt).total_seconds()


def _fmt_age(seconds) -> str:
    if seconds is None:
        return "never"
    if seconds < 90:
        return f"{int(seconds)}s ago"
    if seconds < 5400:
        return f"{int(seconds // 60)}m ago"
    if seconds < 172800:
        return f"{seconds / 3600:.1f}h ago"
    return f"{seconds / 86400:.1f}d ago"


# ── individual checks ───────────────────────────────────────────────────

def check_beat_registration() -> dict:
    """Every beat entry must resolve to a task a worker has registered.

    autodiscover_tasks() only imports <app>.tasks; a task module outside
    that convention is enqueued into the void ("Received unregistered
    task") and its work silently never happens.

    Cached: importing every task module costs ~0.5s cold in the web
    process, and the answer only changes on deploy.
    """
    from django.core.cache import cache

    cached = cache.get("health:beat_registration")
    if cached:
        return cached
    try:
        from config.celery import app
        app.loader.import_default_modules()
        app.finalize()
        registered = set(app.tasks)
        missing = sorted(
            entry["task"] for entry in app.conf.beat_schedule.values()
            if entry["task"] not in registered
        )
        total = len(app.conf.beat_schedule)
    except Exception as e:
        return _check("beat", "Beat schedule", "warn",
                      f"could not inspect: {e}")
    if missing:
        result = _check("beat", "Beat schedule", "fail",
                        f"{len(missing)} of {total} entries unregistered: "
                        + ", ".join(missing[:3]),
                        "Add the module to app.conf.imports in config/celery.py")
    else:
        result = _check("beat", "Beat schedule", "ok",
                        f"all {total} entries resolve to registered tasks")
    cache.set("health:beat_registration", result, 300)
    return result


def check_bot_bars(user) -> dict:
    """The bars the rule layer reads. No 4h bars = that symbol's rules HOLD.

    Checked PER SYMBOL: a global max would let one freshly-fed symbol mask
    every other symbol being stale, which is the exact failure this exists
    to catch.
    """
    from bot_program.models import AssetBotConfig
    from instruments.models import Instrument
    from market_data.models import PriceData

    symbols = set()
    for cfg in AssetBotConfig.objects.filter(user=user, enabled=True):
        symbols.update(cfg.symbols or [])
    if not symbols:
        return _check("bars", "Bot bars (4h)", "ok",
                      "no enabled bot configs — nothing to feed",
                      configured=False)

    inst_by_symbol = {
        i.symbol: i.id for i in Instrument.objects.filter(symbol__in=symbols)
    }
    latest_by_inst = {
        row["instrument_id"]: row["m"]
        for row in (PriceData.objects
                    .filter(instrument_id__in=inst_by_symbol.values(),
                            timeframe="4h")
                    .values("instrument_id").annotate(m=Max("timestamp")))
    }

    missing, stale, fresh = [], [], []
    for symbol in sorted(symbols):
        inst_id = inst_by_symbol.get(symbol)
        latest = latest_by_inst.get(inst_id) if inst_id else None
        if latest is None:
            missing.append(symbol)
        elif _age(latest) > BAR_STALE_SECONDS:
            stale.append(f"{symbol} ({_fmt_age(_age(latest))})")
        else:
            fresh.append(symbol)

    if missing and not fresh and not stale:
        return _check("bars", "Bot bars (4h)", "fail",
                      f"no 4h bars for any of {len(symbols)} bot symbols — "
                      f"every rule returns HOLD",
                      "Run market_data.tasks.refresh_bot_bars_task")
    if missing or stale:
        detail = f"{len(fresh)}/{len(symbols)} symbols fresh"
        if missing:
            detail += " · missing: " + ", ".join(missing[:4])
        if stale:
            detail += " · stale: " + ", ".join(stale[:4])
        return _check("bars", "Bot bars (4h)",
                      "fail" if missing else "warn", detail,
                      "Those symbols' rules cannot fire — check the bar feed "
                      "and that an Instrument row exists for each")
    return _check("bars", "Bot bars (4h)", "ok",
                  f"all {len(symbols)} bot symbols have fresh 4h bars")


def check_capital_truth(user) -> dict:
    """Does the pool every risk limit divides by match the account?

    `AssetBotConfig.capital` is the denominator of the whole per-config
    risk stack — the risk budget, the daily-loss floor, the drawdown
    curve's starting equity, and the base both single-position checks
    measure against. It is written straight from a form POST with no
    reference to any account, and arming live checks only the PIN.

    The direction of the error is the point. A pool declared LARGER than
    the broker's equity makes every limit looser than it reads: a "2%
    daily loss" on a declared 100,000 against a real 20,000 is a 10% daily
    loss. That is the dangerous way, and it is the easy mistake — the pool
    is a plan, the account is what funded it.
    """
    from bot_program.capital_truth import TOLERANCE_PCT, capital_mismatches

    try:
        rows = capital_mismatches(user)
    except Exception as e:  # noqa: BLE001 — a broken check is not a verdict
        return _check("capital", "Bot pool vs account", "warn",
                      f"could not compare: {e}")

    if not rows:
        return _check("capital", "Bot pool vs account", "ok",
                      f"declared pools agree with broker equity "
                      f"(within {TOLERANCE_PCT:.0f}%)", configured=False)

    over = [r for r in rows if r["direction"] == "over"]
    worst = max(rows, key=lambda r: r["ratio"] or 0)
    if over:
        return _check(
            "capital", "Bot pool vs account", "fail",
            f"{len(over)} pool(s) larger than the account — "
            f"{worst['config']} declares {worst['declared']:,.0f} against "
            f"{worst['actual']:,.0f} ({worst['ratio']}x)",
            "Every risk limit is a percentage of the declared pool, so it "
            "is currently looser than you set it. Fix it on /setup/.")
    return _check(
        "capital", "Bot pool vs account", "warn",
        f"{len(rows)} pool(s) smaller than the account — "
        f"{worst['config']} declares {worst['declared']:,.0f} against "
        f"{worst['actual']:,.0f}",
        "Limits are tighter than you set them, which is the safe "
        "direction — but the numbers still disagree.")


def check_component_staleness() -> dict:
    """Are the scheduled components still turning?

    The health page had eight checks and not one read whether the schedule
    was still running. The only thing that reports a stopped component is
    the daily digest — and `render_digest` returns (None, None) when all is
    well, so SILENCE is its healthy signal. A wedged beat, a dead
    worker-fast and a failed Telegram send therefore all produce a message
    an operator cannot tell from a good day.

    The failure correlates, which is what makes it worth a check of its
    own: a stopped worker is exactly the condition that both generates
    faults and suppresses the report about them. A dead beat is a total
    silent stall — bots stop deciding, stranded-close retries stop firing,
    and open positions sit unmanaged behind whatever the broker holds.

    Lateness is judged against each component's OWN cadence, reusing
    `views_topology._component_state`. One 48-hour rule would read the four
    weekly components as stale five days out of seven while they ran
    perfectly.
    """
    from core.platform_control import PlatformComponent
    from dashboard.views_topology import _component_state

    rows = list(PlatformComponent.objects.filter(is_enabled=True))
    if not rows:
        return _check("beat", "Scheduled components", "ok",
                      "no components enabled", configured=False)

    broken, stale, never, live = [], [], [], []
    for comp in rows:
        try:
            state, _note = _component_state(comp)
        except Exception as e:  # noqa: BLE001 — one bad row is not a verdict
            broken.append(f"{comp.key} (unreadable: {e})")
            continue
        if state == "broken":
            broken.append(comp.key)
        elif state == "stale":
            stale.append(comp.key)
        elif state == "idle":
            never.append(comp.key)
        elif state == "live":
            live.append(comp.key)

    if broken or stale:
        bad = broken + stale
        return _check(
            "beat", "Scheduled components", "fail",
            f"{len(bad)} not running to schedule: " + ", ".join(bad[:5]),
            "Check the beat and worker containers — a stopped scheduler "
            "also stops the digest that would have told you")
    if never and not live:
        # Nothing has ever run. An install that was never started, not a
        # platform that stalled — and saying FAIL here trains an operator
        # to ignore the colour.
        return _check(
            "beat", "Scheduled components", "warn",
            f"{len(never)} enabled, none has ever run", "Start the beat "
            "and worker containers", configured=False)
    if never:
        return _check(
            "beat", "Scheduled components", "warn",
            f"{len(live)} on schedule · never run: " + ", ".join(never[:5]))
    return _check("beat", "Scheduled components", "ok",
                  f"{len(live)} running to their own cadence")


def check_quote_freshness() -> dict:
    """Per-feed delivery, from the SAME verdict the digest sends.

    This grouped by the sources that had WRITTEN, so a declared feed that
    has never delivered contributed no row and could not be missed — and
    there was no `fail` branch at all, so no quote condition whatever could
    turn this page red. The digest, meanwhile, walks the registry, detects
    exactly that case, and mails the operator a link to this page. They
    clicked it and read "ok — 3 sources fresh".

    Two surfaces disagreeing is worse than one being blind, because the
    page is the one that looks authoritative.
    """
    from market_data.feeds import BENIGN_STATES, feed_states

    rows = feed_states()
    if not rows:
        return _check("quotes", "Quote feeds", "warn", "no feeds declared")

    dead = [r for r in rows if r["state"] in ("never", "red")]
    strays = [r for r in rows if r["state"] == "unregistered"]
    live = [r for r in rows if r["state"] == "green"]
    benign = [r for r in rows if r["state"] in BENIGN_STATES]

    hint = ("Run `python manage.py check_feeds` — it names the credential "
            "or the container behind each one")
    stray_note = (" · undeclared writer: "
                  + ", ".join(r["source"] for r in strays[:3])) if strays else ""

    # Has any DECLARED feed ever written a quote? That is what separates a
    # platform that regressed from one that has not been started. `benign`
    # is no use for this — an unconfigured feed reads `off`, which is a
    # perfectly healthy state for a platform that has never run at all.
    ever_delivered = [r for r in rows
                      if r["state"] != "unregistered" and r["latest"]]

    if dead and ever_delivered:
        # Some feeds deliver and others never have, or stopped: that is a
        # regression, and it is what the digest mails about.
        return _check(
            "quotes", "Quote feeds", "fail",
            f"{len(dead)} not delivering: "
            + ", ".join(f"{r['label']} ({r['state']})" for r in dead[:4])
            + stray_note, hint)

    if dead:
        # NOTHING has ever delivered. A platform that has not been started
        # is not a platform that broke, and `configured=False` is this
        # page's way of saying "this verdict is about an absence". Screaming
        # FAIL at a fresh install trains an operator to ignore the colour,
        # which costs them the one time it means something.
        return _check(
            "quotes", "Quote feeds", "warn",
            "no declared feed has delivered yet" + stray_note, hint,
            configured=False)

    if strays:
        return _check(
            "quotes", "Quote feeds", "warn",
            f"{len(live)} delivering{stray_note}",
            "A source is writing quotes that market_data/feeds.py does not "
            "declare — the registry is behind, not the platform")

    return _check(
        "quotes", "Quote feeds", "ok",
        f"{len(live)} delivering"
        + (f" · {len(benign)} idle or off" if benign else ""))


def check_close_pending(user) -> dict:
    """CLOSE_PENDING = the bot wanted flat, the broker refused; the
    position is still live."""
    from bot_program.models import AssetBotTrade

    qs = AssetBotTrade.objects.filter(config__user=user, status="CLOSE_PENDING")
    n = qs.count()
    if not n:
        return _check("close_pending", "Stranded closes", "ok",
                      "no trades awaiting a retried close")
    # int(... or 0): the key can exist with a null value.
    worst = max(int((t.metadata or {}).get("close_retry_attempts") or 0)
                for t in qs)
    return _check("close_pending", "Stranded closes", "fail",
                  f"{n} trade(s) still open at the broker after a failed "
                  f"close (worst: {worst} retries)",
                  "retry_pending_closes runs every 5 min; close manually at "
                  "the broker if it persists")


def check_bot_heartbeats(user) -> dict:
    """Enabled bots that haven't ticked recently."""
    from bot_program.models import AssetBotConfig, AssetBotTrade

    configs = list(AssetBotConfig.objects.filter(user=user, enabled=True))
    if not configs:
        return _check("bots", "Bot activity", "ok", "no enabled bots",
                      configured=False)

    # One query for the whole fleet instead of one per config.
    last_by_config = {
        row["config_id"]: row["m"]
        for row in (AssetBotTrade.objects
                    .filter(config__in=configs)
                    .values("config_id").annotate(m=Max("opened_at")))
    }
    quiet = [f"{cfg.name} ({_fmt_age(_age(last_by_config.get(cfg.id)))})"
             for cfg in configs
             if _age(last_by_config.get(cfg.id)) is None
             or _age(last_by_config.get(cfg.id)) > 86400]

    # A bot that hasn't ticked at all is a different (worse) problem than
    # one that ticked and found nothing to do.
    from bot_program.asset_engine.safety import (
        HEARTBEAT_STALE_SECONDS, heartbeat_age_seconds,
    )
    dead = []
    for cfg in configs:
        age = heartbeat_age_seconds(cfg)
        if age is None or age > HEARTBEAT_STALE_SECONDS:
            dead.append(f"{cfg.name} ({_fmt_age(age)})")
    if dead:
        return _check("bots", "Bot activity", "fail",
                      f"{len(dead)}/{len(configs)} bots have not ticked: "
                      + ", ".join(dead[:4]),
                      "The bot tick task may not be running — check the "
                      "worker and the pipeline_asset_bots component")

    active = len(configs) - len(quiet)
    if not quiet:
        return _check("bots", "Bot activity", "ok",
                      f"all {len(configs)} bots traded in the last 24h")
    # Warn on ANY silent bot, not only a fully silent fleet — 9 dead bots
    # out of 10 previously rendered green.
    return _check("bots", "Bot activity", "warn",
                  f"{active}/{len(configs)} bots traded in 24h · quiet: "
                  + ", ".join(quiet[:4]),
                  "Normal if signals are quiet — check bars and signals if "
                  "it persists")


def check_live_mode_readiness(user) -> dict:
    """Live configs whose broker route would fall back to paper. Entries and
    management both refuse in that state, so the bot is effectively off."""
    from bot_program.engine.broker_router import client_for_symbol
    from bot_program.engine.paper_trader import PaperTrader
    from bot_program.models import AssetBotConfig

    # Asset classes with no wired execution broker route to paper by design
    # (broker_router._broker_for_asset_class) — flagging them would make the
    # page permanently red for a condition no credential can fix.
    PAPER_BY_DESIGN = {"commodity"}

    broken, expected = [], []
    for cfg in AssetBotConfig.objects.filter(user=user, enabled=True, mode="live"):
        if cfg.asset_class in PAPER_BY_DESIGN:
            expected.append(cfg.name)
            continue
        # EVERY symbol, not just the first: one config can span venues, and
        # a per-symbol fallback is exactly the silent failure we're hunting.
        for symbol in (cfg.symbols or []):
            try:
                if isinstance(client_for_symbol(user, symbol, cfg), PaperTrader):
                    broken.append(f"{cfg.name}/{symbol}")
            except Exception:
                broken.append(f"{cfg.name}/{symbol}")
    if broken:
        return _check("live_ready", "Live broker credentials", "fail",
                      "live bots falling back to paper: " + ", ".join(broken[:6]),
                      "Add or fix broker credentials — these bots refuse to "
                      "trade rather than record fake live fills")
    detail = "all live bots have a real broker route"
    if expected:
        detail += f" ({len(expected)} paper-only by asset class)"
    return _check("live_ready", "Live broker credentials", "ok", detail)


def check_signal_flow() -> dict:
    """Signals are the bots' input; silence here explains bot silence."""
    from signals.models import Signal

    cutoff = timezone.now() - timedelta(hours=24)
    recent = Signal.objects.filter(created_at__gte=cutoff).count()
    active = Signal.objects.filter(is_active=True).count()
    graded = Signal.objects.filter(is_active=False, realized_r__isnull=False,
                                    expired_at__gte=cutoff).count()
    if recent == 0:
        return _check("signals", "Signal flow", "warn",
                      f"no new signals in 24h ({active} still active)",
                      "Check bars, the signal scan beat entry, and rule state")
    return _check("signals", "Signal flow", "ok",
                  f"{recent} new in 24h · {active} active · {graded} graded")


def check_ai_models() -> dict:
    """Retired/unknown model ids silently 404 every agent call."""
    from ai_agents.catalog import known_model, resolve_tier, TIERS

    bad = [f"{t}={resolve_tier(t)}" for t in TIERS
           if not known_model(resolve_tier(t))]
    if bad:
        return _check("ai_models", "AI models", "fail",
                      "tier(s) resolve outside the catalog: " + ", ".join(bad),
                      "Fix in /ai-models/ or the AI_MODEL_* env vars")
    return _check("ai_models", "AI models", "ok",
                  " · ".join(f"{t}={resolve_tier(t)}" for t in TIERS))


@login_required
def system_health(request):
    # Per-user checks are safe for anyone; the platform-wide ones expose
    # internal task paths, feed names and configured model ids, which the
    # dashboards that own that data gate behind staff.
    plan = [
        (check_bot_bars, True, False),
        (check_close_pending, True, False),
        (check_live_mode_readiness, True, False),
        (check_bot_heartbeats, True, False),
        (check_capital_truth, True, False),
        (check_beat_registration, False, True),
        (check_quote_freshness, False, True),
        (check_component_staleness, False, True),
        (check_signal_flow, False, True),
        (check_ai_models, False, True),
    ]
    checks = []
    for fn, needs_user, staff_only in plan:
        if staff_only and not request.user.is_staff:
            continue
        try:
            checks.append(fn(request.user) if needs_user else fn())
        except Exception as e:  # a broken check must never break the page
            checks.append(_check(getattr(fn, "__name__", "check"),
                                 getattr(fn, "__name__", "check"),
                                 "warn", f"check failed: {e}"))

    counts = {"ok": 0, "warn": 0, "fail": 0}
    for c in checks:
        counts[c["state"]] = counts.get(c["state"], 0) + 1
    overall = "fail" if counts["fail"] else ("warn" if counts["warn"] else "ok")

    # A green page can mean two very different things, and the difference is
    # the whole point of the page. "Everything works" and "nothing is set up
    # so there is nothing to break" both produce all-ok — and on a platform
    # with no bots, no feeds and no positions, the second is what you get.
    # Reporting that as HEALTHY in the same green trains the operator to
    # trust a screen that is telling them nothing.
    unconfigured = [c for c in checks if not c.get("configured", True)]
    if overall == "ok" and unconfigured:
        overall = "unconfigured"

    # Failures first: on a long list the thing needing attention should not
    # be below fifteen passing rows.
    order = {"fail": 0, "warn": 1, "ok": 2}
    checks.sort(key=lambda c: order.get(c["state"], 3))

    return render(request, "dashboard/system_health.html", {
        "page_id": "system_health",
        "checks": checks,
        "counts": counts,
        "overall": overall,
        "unconfigured": unconfigured,
    })
