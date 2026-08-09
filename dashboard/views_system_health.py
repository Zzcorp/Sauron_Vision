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


def _check(key, label, state, detail, hint=""):
    return {"key": key, "label": label, "state": state,
            "detail": detail, "hint": hint}


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
                      "no enabled bot configs — nothing to feed")

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


def check_quote_freshness() -> dict:
    """Per-source LiveQuote freshness — a frozen streamer is invisible
    otherwise."""
    from market_data.models import LiveQuote

    rows = (LiveQuote.objects.values("source")
            .annotate(latest=Max("updated_at")))
    fresh, stale = [], []
    for row in rows:
        src = (row["source"] or "unknown").strip() or "unknown"
        age = _age(row["latest"])
        (stale if age is None or age > QUOTE_STALE_SECONDS else fresh).append(
            f"{src} {_fmt_age(age)}")
    if not fresh and not stale:
        return _check("quotes", "Quote feeds", "warn", "no quotes at all")
    if stale:
        return _check("quotes", "Quote feeds", "warn",
                      f"{len(fresh)} fresh · stale: " + ", ".join(sorted(stale)[:4]),
                      "Paper marks and alerts skip stale quotes, but check the "
                      "streamer/poller for that source")
    return _check("quotes", "Quote feeds", "ok",
                  f"{len(fresh)} sources fresh: " + ", ".join(sorted(fresh)[:4]))


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
        return _check("bots", "Bot activity", "ok", "no enabled bots")

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
        (check_beat_registration, False, True),
        (check_quote_freshness, False, True),
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

    return render(request, "dashboard/system_health.html", {
        "page_id": "system_health",
        "checks": checks,
        "counts": counts,
        "overall": overall,
    })
