"""Sauron's Eye — Phase-16 unified real-time dashboard.

Surfaces in one view:
  - Live theme exposure (orchestrator's view of you) + caps
  - Open positions across every asset class (AssetBotTrade + crypto BotTrade)
  - Recent orchestrator gate decisions (allow/reject) with reason
  - Recent bot fills (opens + closes, last 30)
  - Active rule-control state summary
  - Per-bot health (last tick, open count)
  - 24h aggregate P&L

Auto-refreshes via HTMX so the page updates without a manual reload.
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count
from django.shortcuts import render
from django.utils import timezone


@login_required
def eye_dashboard(request):
    """Render /eye/ — the all-seeing dashboard."""
    user = request.user
    context = _build_eye_context(user)
    context["page_id"] = "eye"
    return render(request, "dashboard/eye.html", context)


@login_required
def eye_partial(request):
    """HTMX-friendly partial body for auto-refresh."""
    user = request.user
    context = _build_eye_context(user)
    return render(request, "dashboard/_eye_body.html", context)


def _build_eye_context(user) -> dict:
    """Aggregate everything the Eye needs into a single context dict."""
    ctx = {
        "now": timezone.now(),
        "theme_exposure": _theme_exposure(user),
        "open_positions": _open_positions(user),
        "gate_events": _recent_gate_events(user),
        "recent_fills": _recent_fills(user),
        "rule_control": _rule_control_summary(user),
        "bot_health": _bot_health(user),
        "pnl_24h": _pnl_24h(user),
    }
    return ctx


# ── Theme exposure ───────────────────────────────────────────────────────

def _theme_exposure(user) -> dict:
    """Live theme exposure + caps + status flag (under/at/over).

    Phase-24: returns the legacy `exposure` block (USD + equity) plus
    `extras` (vol_long, per-currency rows, per-sector counts) when their
    caps are non-zero on the user's profile.
    """
    from bot_program.orchestrator import current_exposures
    from portfolio.trader_profile import TraderProfile

    full = current_exposures(user)
    profile = TraderProfile.objects.filter(user=user).first()
    enabled = bool(profile and profile.cross_asset_orchestrator_enabled)
    caps = {
        "usd": float(profile.max_usd_theme_exposure) if profile else 3.0,
        "equity": float(profile.max_equity_theme_exposure) if profile else 3.0,
        "vol_long": float(getattr(profile, "max_vol_theme_exposure", 0)) if profile else 0,
        "currency": float(getattr(profile, "max_currency_exposure", 0)) if profile else 0,
        "sector": int(getattr(profile, "max_sector_exposure", 0)) if profile else 0,
    }

    def _status(val, cap):
        if cap <= 0:
            return "off"
        ratio = abs(val) / cap
        if ratio >= 1.0:
            return "over"
        if ratio >= 0.75:
            return "near"
        return "ok"

    themes = full["themes"]
    out = {
        "enabled": enabled,
        "size_weighted": bool(profile and getattr(profile, "size_weighted_orchestrator", False)),
        "exposure": {
            "usd": {"value": round(themes.get("usd", 0), 1),
                    "cap": caps["usd"],
                    "status": _status(themes.get("usd", 0), caps["usd"])},
            "equity": {"value": round(themes.get("equity", 0), 1),
                        "cap": caps["equity"],
                        "status": _status(themes.get("equity", 0), caps["equity"])},
        },
        "extras": {},
    }

    # Phase 24 — only show extras the user has enabled.
    if caps["vol_long"] > 0:
        v = themes.get("vol_long", 0)
        out["extras"]["vol_long"] = {
            "value": round(v, 1), "cap": caps["vol_long"],
            "status": _status(v, caps["vol_long"]),
        }
    if caps["currency"] > 0 and full["currencies"]:
        out["extras"]["currencies"] = []
        for ccy, v in sorted(full["currencies"].items(), key=lambda x: -abs(x[1])):
            out["extras"]["currencies"].append({
                "ccy": ccy, "value": round(v, 1),
                "cap": caps["currency"],
                "status": _status(v, caps["currency"]),
            })
    if caps["sector"] > 0 and full["sectors"]:
        out["extras"]["sectors"] = []
        for sec, n in sorted(full["sectors"].items(), key=lambda x: -x[1]):
            out["extras"]["sectors"].append({
                "sector": sec, "value": n,
                "cap": caps["sector"],
                "status": "over" if n > caps["sector"]
                           else ("near" if n >= caps["sector"] * 0.75 else "ok"),
            })

    return out


# ── Open positions across all classes ────────────────────────────────────

def _open_positions(user) -> list:
    """Unified list across AssetBotTrade + legacy crypto BotTrade."""
    out = []
    try:
        from bot_program.models import AssetBotTrade
        rows = (AssetBotTrade.objects
                .filter(config__user=user, status="OPEN")
                .select_related("config")
                .order_by("-opened_at")[:50])
        for t in rows:
            out.append({
                "asset_class": t.asset_class,
                "symbol": t.symbol,
                "side": t.side,
                "qty": t.qty,
                "entry_price": t.entry_price,
                "stop_loss": t.stop_loss,
                "take_profit": t.take_profit,
                "opened_at": t.opened_at,
                "config_name": t.config.name,
                "score": t.composite_score,
                "rule": t.rule_name,
                "paper": t.paper,
                "kind": "asset",
            })
    except Exception:
        pass

    try:
        from bot_program.models import BotTrade
        legacy = (BotTrade.objects
                  .filter(config__user=user, exit_price__isnull=True)
                  .order_by("-id")[:50])
        for t in legacy:
            out.append({
                "asset_class": "crypto",
                "symbol": t.symbol,
                "side": t.side,
                "qty": t.qty,
                "entry_price": t.entry_price,
                "stop_loss": getattr(t, "stop_loss", None),
                "take_profit": getattr(t, "take_profit", None),
                "opened_at": getattr(t, "opened_at", None),
                "config_name": "Crypto bot",
                "score": getattr(t, "composite_score", 0),
                "rule": getattr(t, "rule_name", ""),
                "paper": getattr(t, "paper", True),
                "kind": "legacy",
            })
    except Exception:
        pass
    return out


# ── Gate events ──────────────────────────────────────────────────────────

def _recent_gate_events(user, limit: int = 30) -> list:
    try:
        from bot_program.orchestrator_models import OrchestratorEvent
        return list(
            OrchestratorEvent.objects.filter(user=user).order_by("-created_at")[:limit]
        )
    except Exception:
        return []


# ── Recent fills ─────────────────────────────────────────────────────────

def _recent_fills(user, limit: int = 30) -> list:
    out = []
    try:
        from bot_program.models import AssetBotTrade
        rows = (AssetBotTrade.objects
                .filter(config__user=user)
                .order_by("-opened_at")[:limit])
        for t in rows:
            out.append({
                "when": t.opened_at,
                "kind": "open",
                "symbol": t.symbol,
                "asset_class": t.asset_class,
                "side": t.side,
                "qty": t.qty,
                "entry_price": t.entry_price,
                "status": t.status,
                "pnl": t.pnl,
                "rule": t.rule_name,
                "paper": t.paper,
            })
    except Exception:
        pass
    out.sort(key=lambda r: r["when"] or timezone.now(), reverse=True)
    return out[:limit]


# ── Rule control state ────────────────────────────────────────────────────

def _rule_control_summary(user) -> dict:
    """Active RuleControl + RuleAction summary. Best-effort — Phase-5 module
    may be missing in stripped-down deployments."""
    out = {"paused_rules": 0, "reduced_rules": 0, "live_actions_24h": 0}
    try:
        from signals.models import RuleControl, RuleAction
        out["paused_rules"] = RuleControl.objects.filter(status="paused").count()
        out["reduced_rules"] = RuleControl.objects.filter(
            status="active", size_multiplier__lt=1.0).count()
        since = timezone.now() - timedelta(hours=24)
        out["live_actions_24h"] = RuleAction.objects.filter(
            applied_at__gte=since).count()
    except Exception:
        pass
    return out


# ── Bot health ───────────────────────────────────────────────────────────

def _bot_health(user) -> list:
    """Per-AssetBotConfig: enabled, mode, open count. Also include the legacy
    crypto BotConfig so a single "bot health" panel lists everything."""
    out = []
    try:
        from bot_program.models import AssetBotConfig, AssetBotTrade
        for cfg in AssetBotConfig.objects.filter(user=user).order_by("asset_class", "name"):
            open_n = AssetBotTrade.objects.filter(config=cfg, status="OPEN").count()
            out.append({
                "name": cfg.name, "asset_class": cfg.asset_class,
                "mode": cfg.mode, "enabled": cfg.enabled,
                "open_count": open_n, "kind": "asset",
            })
    except Exception:
        pass
    try:
        from bot_program.models import BotConfig, BotTrade
        for cfg in BotConfig.objects.filter(user=user):
            open_n = BotTrade.objects.filter(
                config=cfg, exit_price__isnull=True).count()
            out.append({
                "name": "Crypto bot", "asset_class": "crypto",
                "mode": cfg.mode, "enabled": cfg.enabled,
                "open_count": open_n, "kind": "legacy",
            })
    except Exception:
        pass
    return out


# ── 24h aggregate P&L ────────────────────────────────────────────────────

def _pnl_24h(user) -> dict:
    since = timezone.now() - timedelta(hours=24)
    total = Decimal("0")
    by_class: dict = {}
    try:
        from bot_program.models import AssetBotTrade
        rows = (AssetBotTrade.objects
                .filter(config__user=user, status="CLOSED",
                        closed_at__gte=since)
                .values("asset_class")
                .annotate(s=Sum("pnl"), n=Count("id")))
        for r in rows:
            v = r["s"] or Decimal("0")
            by_class[r["asset_class"]] = {"pnl": v, "count": r["n"]}
            total += v
    except Exception:
        pass
    return {"total": total, "by_class": by_class}
