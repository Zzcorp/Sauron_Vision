"""Circuit breakers, shadow mode and heartbeats for the multi-asset bots.

Equivalents existed for the legacy crypto bot (bot_program/engine/*) but
were keyed to `BotConfig` and had **zero call sites in any trading path** —
four finished safety modules that never ran. These are AssetBotConfig-native
and are wired into the tick loop.

State lives in `AssetBotConfig.extras` rather than new tables: the values
are small, per-config and self-expiring, and this keeps the safety layer
free of a migration.

  extras["shadow_until"]      ISO timestamp — compute but never submit
  extras["max_loss_streak"]   consecutive losing trades before halting
  extras["max_drawdown_pct"]  drawdown from peak equity before halting
  extras["last_tick_at"]      heartbeat, written every tick
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

logger = logging.getLogger(__name__)

DEFAULT_MAX_LOSS_STREAK = 4
DEFAULT_MAX_DRAWDOWN_PCT = 10.0
# A bot that hasn't ticked in this long is presumed dead by the health page.
HEARTBEAT_STALE_SECONDS = 1800


def _extras(cfg) -> dict:
    return getattr(cfg, "extras", None) or {}


def _save_extras(cfg, **updates) -> None:
    extras = dict(_extras(cfg))
    extras.update(updates)
    cfg.extras = extras
    try:
        cfg.save(update_fields=["extras", "updated_at"])
    except Exception:  # a heartbeat must never break a tick
        logger.debug("[safety] could not persist extras for config %s", cfg.id)


# ── shadow mode ─────────────────────────────────────────────────────────

def is_shadow(cfg) -> bool:
    """True while the config is in shadow mode: decide everything, submit
    nothing. The way to validate a change against live data for 24-48h
    without risking money."""
    raw = _extras(cfg).get("shadow_until")
    if not raw:
        return False
    try:
        from django.utils.dateparse import parse_datetime
        until = parse_datetime(str(raw))
    except Exception:
        return False
    if until is None:
        return False
    if timezone.is_naive(until):
        until = timezone.make_aware(until)
    return until > timezone.now()


def enable_shadow(cfg, hours: int = 24):
    """Put a config into shadow mode for N hours. Returns the expiry."""
    until = timezone.now() + timedelta(hours=hours)
    _save_extras(cfg, shadow_until=until.isoformat())
    logger.warning("[shadow] config %s (%s) in shadow mode until %s",
                   cfg.id, cfg.name, until)
    return until


def log_shadow_entry(cfg, symbol: str, decision, price: float, qty: float):
    """Record the entry that would have been submitted."""
    logger.info("[SHADOW] %s would %s %s qty=%.6f @ %s (score %.3f, rule %s)",
                cfg.name, decision.direction, symbol, qty, price,
                decision.score, decision.rule_name or "?")
    try:
        from brain.observations import record_observation
        record_observation(
            kind="shadow_entry",
            payload={"config_id": cfg.id, "symbol": symbol,
                      "direction": decision.direction, "qty": qty,
                      "price": price, "score": decision.score,
                      "rule_name": decision.rule_name or ""},
            source="asset_bot_shadow",
        )
    except Exception:
        pass


# ── heartbeats ──────────────────────────────────────────────────────────

def write_heartbeat(cfg, status: str = "OK", note: str = "") -> None:
    _save_extras(cfg, last_tick_at=timezone.now().isoformat(),
                 last_tick_status=status, last_tick_note=note[:200])


def heartbeat_age_seconds(cfg):
    raw = _extras(cfg).get("last_tick_at")
    if not raw:
        return None
    try:
        from django.utils.dateparse import parse_datetime
        seen = parse_datetime(str(raw))
        if seen is None:
            return None
        if timezone.is_naive(seen):
            seen = timezone.make_aware(seen)
        return (timezone.now() - seen).total_seconds()
    except Exception:
        return None


# ── circuit breakers ────────────────────────────────────────────────────

class CircuitBreakers:
    """Halt NEW entries when the recent record says something is wrong.

    Deliberately never force-closes: an automated system that starts
    closing positions on a heuristic is more dangerous than one that
    simply stops opening them.
    """

    def __init__(self, cfg):
        self.cfg = cfg
        self.extras = _extras(cfg)

    def _closed_trades(self, limit: int = 20):
        from bot_program.models import AssetBotTrade
        return list(AssetBotTrade.objects
                    .filter(config=self.cfg, status="CLOSED")
                    .order_by("-closed_at")[:limit])

    def check_consecutive_losses(self) -> tuple:
        max_streak = int(self.extras.get("max_loss_streak",
                                          DEFAULT_MAX_LOSS_STREAK))
        if max_streak <= 0:
            return True, ""
        streak = 0
        for trade in self._closed_trades(max_streak):
            pnl = trade.pnl if trade.pnl is not None else Decimal("0")
            if pnl < 0:
                streak += 1
            else:
                break
        if streak >= max_streak:
            return False, f"{streak} consecutive losing trades (max {max_streak})"
        return True, ""

    def check_drawdown_from_peak(self) -> tuple:
        """Halt when cumulative realised P&L has fallen far from its peak."""
        max_dd = float(self.extras.get("max_drawdown_pct",
                                        DEFAULT_MAX_DRAWDOWN_PCT))
        if max_dd <= 0:
            return True, ""
        from bot_program.models import AssetBotTrade

        trades = list(AssetBotTrade.objects
                      .filter(config=self.cfg, status="CLOSED")
                      .order_by("closed_at")
                      .values_list("pnl", flat=True))
        if len(trades) < 5:
            return True, ""

        capital = float(self.cfg.capital or 0) or 1.0
        equity = capital
        peak = capital
        for pnl in trades:
            equity += float(pnl or 0)
            peak = max(peak, equity)
        drawdown_pct = (peak - equity) / peak * 100 if peak > 0 else 0
        if drawdown_pct >= max_dd:
            return False, (f"drawdown {drawdown_pct:.1f}% from peak "
                           f"(max {max_dd:.1f}%)")
        return True, ""

    def check_all(self) -> tuple:
        """(allowed, reasons)."""
        reasons = []
        for check in (self.check_consecutive_losses,
                      self.check_drawdown_from_peak):
            try:
                ok, reason = check()
            except Exception as e:
                logger.warning("[safety] %s failed for config %s: %s",
                               check.__name__, self.cfg.id, e)
                continue
            if not ok:
                reasons.append(reason)
        return (not reasons), reasons


def notify_circuit_breaker(cfg, reasons: list) -> None:
    """Alert once an hour while a breaker is tripped."""
    try:
        from alerts.models import Notification
        title = f"🔌 Circuit breaker: {cfg.name}"
        recent = Notification.objects.filter(
            user=cfg.user, notification_type="bot", title=title,
            created_at__gte=timezone.now() - timedelta(hours=1)).exists()
        if not recent:
            Notification.objects.create(
                user=cfg.user, notification_type="bot", title=title,
                body=(f"{cfg.asset_class} bot '{cfg.name}' has stopped opening "
                      f"new positions: {'; '.join(reasons)}. Existing positions "
                      f"are left alone."),
                url="/health/")
    except Exception as e:
        logger.warning("[safety] breaker notification failed: %s", e)
