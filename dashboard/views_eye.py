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
import logging
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count
from django.shortcuts import render
from django.utils import timezone

logger = logging.getLogger(__name__)


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


def _build_eye_context(user, *, for_command=False) -> dict:
    """Aggregate everything the Eye needs into a single context dict.

    `for_command` (2026-11-07, the Operations Center OC0): the LIVE tab of
    /command/ draws this body too. There the 24 h P&L is per world and
    carries no percentage of the limits book, the recent fills (which the
    body never prints) are not read, and the footer says when the body was
    read rather than "auto-refresh every 10s" (true on /eye/, false on
    /command/, which re-reads the tab on fills only)."""
    from .views_command import WHY
    now = timezone.now()
    rule_control, rule_unread = _rule_control_counts(user)
    bot_health = _bot_health(user)
    ctx = {
        "now": now,
        "eye_on_command": for_command,
        "why": WHY,
        # "Active bots" counted every config beside an ENABLED count that
        # disagreed: the configs and the enabled ones, both said.
        "bot_counts": {"n": len(bot_health),
                       "on": sum(1 for b in bot_health if b["enabled"])},
        "theme_exposure": _theme_exposure(user),
        "open_positions": _open_positions(user),
        "gate_events": _dated(_recent_gate_events(user), now),
        "rule_control": rule_control,
        "rule_control_unread": rule_unread,
        "bot_health": bot_health,
        "pnl_24h": _pnl_24h(user, with_pct=not for_command),
    }
    if not for_command:
        ctx["recent_fills"] = _recent_fills(user)
    return ctx


def _dated(events, now):
    """Each gate decision with the time it was taken, dated when it was not
    today (2026-11-07: "H:i:s" over sixty hours of decisions read as one
    afternoon)."""
    today = now.date()
    for ev in events:
        at = getattr(ev, "created_at", None)
        if at is None:
            ev.when_text = ""
        elif at.date() == today:
            ev.when_text = at.strftime("%H:%M:%S")
        else:
            ev.when_text = at.strftime("%Y-%m-%d %H:%M")
    return events


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
        from dashboard.position_summary import quantity, world_of
        rows = (AssetBotTrade.objects
                .filter(config__user=user, status__in=("OPEN", "CLOSE_PENDING"))
                .select_related("config")
                .order_by("-opened_at")[:50])
        for t in rows:
            out.append({
                # id + status make the row actionable: the CLOSE control
                # needs the trade to aim at, and CLOSE_PENDING must offer a
                # RETRY rather than a second close.
                "id": t.id,
                "status": t.status,
                "asset_class": t.asset_class,
                "symbol": t.symbol,
                "side": t.side,
                "qty": t.qty,
                # A quantity as a person counts it: 1,000, never
                # 1000.00000000 (2026-11-07, the Operations Center OC0).
                "qty_text": quantity(t.qty),
                "entry_price": t.entry_price,
                "stop_loss": t.stop_loss,
                "take_profit": t.take_profit,
                "opened_at": t.opened_at,
                "config_name": t.config.name,
                "score": t.composite_score,
                "rule": t.rule_name,
                "paper": t.paper,
                # THE ROW'S OWN WORLD (2026-11-07): a dict with no metadata
                # read as live in world_of, and the money_world chip printed
                # an eToro DEMO row as REAL MONEY. The stamps ride with the
                # row, and the world is read off them, the one rule.
                "metadata": t.metadata or {},
                "world": world_of(t),
                "key": f"bot-{t.id}",
                "kind": "asset",
            })
    except Exception:
        pass

    try:
        from bot_program.models import BotTrade
        legacy = (BotTrade.objects
                  .filter(config__user=user, exit_price__isnull=True)
                  .order_by("-id")[:50])
        from dashboard.position_summary import quantity, world_of
        for t in legacy:
            paper = getattr(t, "paper", True)
            out.append({
                "asset_class": "crypto",
                "symbol": t.symbol,
                "side": t.side,
                "qty": t.qty,
                "qty_text": quantity(t.qty),
                "world": world_of({"paper": paper, "metadata": {}}),
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
    """The three counts, as they always were (see _rule_control_counts)."""
    return _rule_control_counts(user)[0]


def _rule_control_counts(user):
    """The three rule-control numbers in the Eye's pill row, counted apart.

    They used to share one `try/except Exception: pass`, and the middle one
    filtered on `size_multiplier` — a field `RuleControl` has never declared.
    Django resolves lookup names inside `filter()`, so the FieldError was
    raised before `.count()`, the swallow ate it, and the two statements AFTER
    it never ran either: `reduced` and `actions/24h` both showed a confident 0
    on every install, for unrelated reasons, beside a `paused` that worked.
    That is what made the dead pair look authoritative. Each counter now owns
    its guard, and a failure is logged rather than absorbed.

    `reduced` is `status == "reduced"`, not `weight_multiplier < 1.0` on an
    ACTIVE row: `rule_actuator.apply_action` writes STATUS_REDUCED when it
    reduces a rule, and `rule_size_multiplier` honours `weight_multiplier`
    only in that status. Both conjuncts of the old filter were wrong, so
    renaming the field alone would still have counted zero forever.

    `paused` is the model's own `running_q()` inverted rather than
    `status == "paused"`: nothing writes the column back when `paused_until`
    elapses, so the raw status would keep reporting a rule that has been
    signalling again for weeks as stopped.

    The import keeps its own guard — the Phase-5 module really may be absent
    in a stripped-down deployment, and that is the one failure here that is
    expected rather than a bug.
    """
    out = {"paused_rules": 0, "reduced_rules": 0, "live_actions_24h": 0}
    # (counts, the keys that could not be read): a counter left at 0 by a
    # failure is no figure, and the panel prints a dash with its reason for
    # it (2026-11-07, the Operations Center OC0); the counts keep their 0
    # for every reader that sums them.
    try:
        from signals.models import RuleControl, RuleAction
    except Exception:  # noqa: BLE001
        logger.info("[eye] rule-control models unavailable — panel left at 0")
        return out, set(out)

    now = timezone.now()
    counters = (
        ("paused_rules",
         lambda: RuleControl.objects.exclude(
             RuleControl.running_q(now)).count()),
        ("reduced_rules",
         lambda: RuleControl.objects.filter(
             status=RuleControl.STATUS_REDUCED).count()),
        ("live_actions_24h",
         lambda: RuleAction.objects.filter(
             applied_at__gte=now - timedelta(hours=24)).count()),
    )
    unread = set()
    for key, count in counters:
        try:
            out[key] = count()
        except Exception:  # noqa: BLE001
            logger.exception("[eye] rule-control counter %s failed", key)
            unread.add(key)
    return out, unread


# ── Bot health ───────────────────────────────────────────────────────────

def _bot_health(user) -> list:
    """Per-AssetBotConfig: enabled, mode, open count. Also include the legacy
    crypto BotConfig so a single "bot health" panel lists everything."""
    out = []
    try:
        from bot_program.models import AssetBotConfig, AssetBotTrade
        # One grouped count for every config's open rows (2026-11-07): a
        # query per config cost the Eye and the LIVE tab one read per bot.
        open_by = dict(AssetBotTrade.objects
                       .filter(config__user=user,
                               status__in=("OPEN", "CLOSE_PENDING"))
                       .values("config_id").annotate(n=Count("id"))
                       .order_by().values_list("config_id", "n"))
        for cfg in AssetBotConfig.objects.filter(user=user).order_by("asset_class", "name"):
            open_n = open_by.get(cfg.id, 0)
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

def _pnl_24h(user, with_pct=True) -> dict:
    """Realised P&L over the trailing day, in money AND as a share of the book.

    A gain of 250 is a different day on a 1,000 book than on a 100,000 one,
    and the currency figure alone cannot say which. `pct` is None — never 0 —
    when the book value has never been set: a percentage of an unknown base
    is not a small percentage, it is not a percentage, and the template
    renders that as an em-dash rather than as a flat zero.
    """
    since = timezone.now() - timedelta(hours=24)
    total = Decimal("0")
    by_class: dict = {}
    # PER WORLD (2026-11-07, the Operations Center OC0): REAL, DEMO and
    # PAPER are never added. The same one read, grouped by the rows' own
    # stamps too; each group's world is world_of's (the platform's one
    # rule), applied here to the stamps, never a second rule in SQL. The
    # currency is the config's (a close books its P&L in it).
    by_world: dict = {}
    by_world_class: dict = {}
    try:
        from django.db.models.fields.json import KeyTextTransform
        from bot_program.models import AssetBotTrade
        from dashboard.position_summary import money, world_of
        rows = (AssetBotTrade.objects
                .filter(config__user=user, status="CLOSED",
                        closed_at__gte=since)
                .annotate(w_broker=KeyTextTransform("broker", "metadata"),
                          w_env=KeyTextTransform("broker_env", "metadata"))
                .values("asset_class", "paper", "w_broker", "w_env",
                        "config__base_currency")
                # Sum SKIPS NULLs, Count does not — so a class holding
                # one unmeasured exit would divide a real total by a count
                # that includes a trade contributing nothing to it. The
                # measured count is the denominator that matches the sum;
                # the other is kept so the page can say how many are not
                # in the figure.
                .annotate(s=Sum("pnl"), n=Count("id"),
                          measured=Count("pnl"))
                .order_by())
        for r in rows:
            v = r["s"] or Decimal("0")
            info = by_class.setdefault(r["asset_class"], {
                "pnl": Decimal("0"), "count": 0, "measured": 0,
                "unmeasured": 0})
            info["pnl"] += v
            info["count"] += r["n"]
            info["measured"] += r["measured"]
            info["unmeasured"] += r["n"] - r["measured"]
            total += v
            world = world_of({"paper": r["paper"],
                              "metadata": {"broker": r["w_broker"],
                                           "broker_env": r["w_env"]}})
            ccy = (r["config__base_currency"] or "USD").strip().upper()
            for key, book in (((world, ccy), by_world),
                              ((world, ccy, r["asset_class"]),
                               by_world_class)):
                slot = book.setdefault(key, {"pnl": 0.0, "n": 0,
                                             "measured": 0})
                if r["s"] is not None:
                    slot["pnl"] += float(r["s"])
                slot["n"] += r["n"]
                slot["measured"] += r["measured"]
    except Exception:
        logger.warning("[eye] the 24 h P&L is unreadable", exc_info=True)

    order = {"live": 0, "demo": 1, "paper": 2, "": 3}

    def _rows(book, with_class):
        out = []
        for key, slot in sorted(book.items(),
                                key=lambda kv: (order.get(kv[0][0], 9),) + kv[0][1:]):
            pnl = round(slot["pnl"], 2) if slot["measured"] else None
            out.append({"world": key[0], "ccy": key[1],
                        "asset_class": key[2] if with_class else "",
                        "pnl": pnl, "n": slot["n"],
                        "unmeasured": slot["n"] - slot["measured"],
                        "text": money(pnl, key[1], signed=True)})
        return out

    base = None
    if with_pct:
        try:
            from portfolio.risk_gate import book_value, limits_book
            base = book_value(limits_book())
        except Exception as e:  # noqa: BLE001 — a missing book is not a 500
            logger.debug("[eye] book value unavailable for the 24h pct: %s", e)

    pct = (round(float(total) / base * 100, 2)
           if base not in (None, 0) else None)
    for info in by_class.values():
        info["pct"] = (round(float(info["pnl"]) / base * 100, 2)
                       if base not in (None, 0) else None)
    return {"total": total, "by_class": by_class, "pct": pct,
            "book_value": base,
            "by_world": _rows(by_world, False),
            "by_world_class": _rows(by_world_class, True)}
