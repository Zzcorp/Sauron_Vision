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


def _knob(cfg, extras: dict, key: str, default: float) -> float:
    """A breaker threshold out of hand-edited JSON, never raising.

    extras is typed by a human. `float("10%")` raised straight out of
    check_drawdown_from_peak into check_all's handler, which continued past
    it with no reason recorded — so a typo in one field turned a circuit
    breaker off while can_open_new read the result as "both breakers ran and
    cleared". A bad value falls back to the shipped default: the breaker
    stays armed, which is the only safe direction for a halt, and a config
    error is not the transient kind that argues for standing aside.
    """
    raw = extras.get(key, default)
    try:
        return float(raw if raw is not None else default)
    except (TypeError, ValueError):
        logger.warning("[safety] cfg %s: extras[%r]=%r is not numeric — "
                       "the breaker stays armed at %s",
                       getattr(cfg, "id", "?"), key, raw, default)
        return float(default)


def _save_extras(cfg, **updates) -> None:
    """Merge `updates` into the config's extras, re-reading the row first.

    extras is not scratch space — risk_per_trade_pct, trail_pct,
    max_notional_fraction, premium_stop_pct, shadow_until and the breaker
    knobs all live in it. The old version merged onto the in-memory `cfg`,
    which asset_engine.runner loads ONCE and holds for the whole tick, then
    wrote the entire JSON column back. A tick takes tens of seconds and
    writes here at least three times (start, every skipped symbol, end), so
    an operator who tightened risk_per_trade_pct on the HQ form mid-tick had
    it silently reverted to the pre-tick value by the next skip — no error,
    no log line, and the next entry sized at the risk they had just removed.
    Only the keys this call actually sets may move; everything else comes
    from the row as it stands now.
    """
    updated = dict(_extras(cfg))
    updated.update(updates)
    pk = getattr(cfg, "pk", None)
    if pk is None:  # unsaved config (tests, dry runs) — nothing to re-read
        cfg.extras = updated
        return
    try:
        from django.db import transaction
        with transaction.atomic():
            row = (cfg.__class__._default_manager
                   .select_for_update().filter(pk=pk).first())
            if row is None:
                cfg.extras = updated
                return
            merged = dict(getattr(row, "extras", None) or {})
            merged.update(updates)
            row.extras = merged
            row.save(update_fields=["extras", "updated_at"])
        # The rest of the tick reads the operator's current values, not the
        # snapshot this process started with.
        cfg.extras = merged
    except Exception:  # a heartbeat must never break a tick
        cfg.extras = updated
        logger.debug("[safety] could not persist extras for config %s",
                     getattr(cfg, "id", "?"))


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
        # Breakers that raised on the last check_all(). See its docstring:
        # not empty is not the same as not tripped.
        self.blind: list = []

    def _closed_trades(self, limit: int = 20):
        from bot_program.models import AssetBotTrade
        return list(AssetBotTrade.objects
                    .filter(config=self.cfg, status="CLOSED")
                    .order_by("-closed_at")[:limit])

    def check_consecutive_losses(self) -> tuple:
        max_streak = int(_knob(self.cfg, self.extras, "max_loss_streak",
                               DEFAULT_MAX_LOSS_STREAK))
        if max_streak <= 0:
            return True, ""
        streak = 0
        skipped = 0
        # Twice the window, because unmeasured rows are stepped OVER rather
        # than counted and a run of them would otherwise starve the count.
        for trade in self._closed_trades(max_streak * 2):
            if trade.pnl is None:
                # Unmeasured is not a loss — and not a win either. Coercing
                # it to Decimal("0") made it non-negative, so it fell to the
                # `else` and BROKE the streak: three real losses with one
                # unpriceable close among them read as a streak of one.
                # Unpriceable exits cluster exactly when the broker link is
                # sick, which is when a bot is most likely to be bleeding and
                # this breaker most needs to fire.
                skipped += 1
                continue
            if trade.pnl < 0:
                streak += 1
            else:
                break
            if streak >= max_streak:
                break
        if streak >= max_streak:
            note = f", {skipped} unmeasured skipped" if skipped else ""
            return False, (f"{streak} consecutive losing trades "
                           f"(max {max_streak}{note})")
        return True, ""

    def check_drawdown_from_peak(self) -> tuple:
        """Halt when cumulative realised P&L has fallen far from its peak.

        PAPER AND LIVE ARE SEPARATE CURVES, judged separately, and either
        can halt the config. Netting them let simulated profit raise the
        peak and hide a live drawdown underneath it — and that is not a
        corner case: while one rule is promoted platform-wide the actuator
        forces most entries to paper at full nominal size, so the closes on
        a LIVE config are mostly simulated. `risk_gate` already refuses to
        net the two for the book; this is the same rule one layer down.

        Separating them does not weaken the breaker. A strategy bleeding on
        paper is still bleeding, and its curve can still halt the config —
        what it can no longer do is cancel out the real one.

        An unpriceable exit is EXCLUDED rather than counted as a scratch.
        `float(pnl or 0)` scored a close nobody could price as break-even,
        which is the fabrication the nullable column exists to prevent. The
        count rides along in the reason so an operator can see how much of
        the record the number was drawn from.
        """
        max_dd = _knob(self.cfg, self.extras, "max_drawdown_pct",
                       DEFAULT_MAX_DRAWDOWN_PCT)
        if max_dd <= 0:
            return True, ""
        from bot_program.models import AssetBotTrade

        rows = list(AssetBotTrade.objects
                    .filter(config=self.cfg, status="CLOSED")
                    .order_by("closed_at")
                    .values_list("pnl", "paper"))
        capital = float(self.cfg.capital or 0) or 1.0

        # Live first: it is the curve made of money that actually moved, so
        # it is the one whose breach should be named if both have drawn down.
        for want_paper, label in ((False, "live"), (True, "paper")):
            curve = [p for p, is_paper in rows if bool(is_paper) is want_paper]
            measured = [p for p in curve if p is not None]
            unmeasured = len(curve) - len(measured)
            if len(measured) < 5:
                continue
            equity = peak = capital
            for pnl in measured:
                equity += float(pnl)
                peak = max(peak, equity)
            drawdown_pct = (peak - equity) / peak * 100 if peak > 0 else 0
            if drawdown_pct >= max_dd:
                note = (f", {unmeasured} unmeasured excluded"
                        if unmeasured else "")
                return False, (f"{label} drawdown {drawdown_pct:.1f}% from "
                               f"peak (max {max_dd:.1f}%{note})")
        return True, ""

    def check_all(self) -> tuple:
        """(allowed, reasons), with `self.blind` naming what could not run.

        A breaker that could not run is NOT a breaker that cleared — but it
        is not a halt either, and the difference is deliberate. Both breakers
        here query AssetBotTrade, so the thing that makes one raise is almost
        always the database, and the database is shared: halting on it stops
        every config in the fleet on a transient hiccup. That is the trade
        `risk_gate.preflight` already weighed for the book limits and settled
        the same way, and a safety layer that fails in one direction here and
        the other there is a layer nobody can reason about under pressure.

        What was actually wrong was the SILENCE. The old handler swallowed
        the exception and continued, so can_open_new received (True, []) —
        byte-identical to both breakers passing — and the bot kept opening
        positions with nothing watching its drawdown while /health/ and the
        headband showed it as fine. `self.blind` is that state made
        answerable rather than inferred, the way preflight's `failed_open`
        is: the caller reports it in the heartbeat instead of printing the
        most reassuring note it has.

        The most likely cause is gone besides — a typo in a threshold no
        longer raises, it falls back to the shipped default with the breaker
        still armed (see `_knob`).
        """
        reasons = []
        self.blind = []
        for check in (self.check_consecutive_losses,
                      self.check_drawdown_from_peak):
            name = getattr(check, "__name__", str(check))
            try:
                ok, reason = check()
            except Exception as e:
                logger.error("[safety] %s could not be evaluated for config "
                             "%s: %s — entries are NOT gated by it this pass",
                             name, getattr(self.cfg, "id", "?"), e)
                self.blind.append(f"{name} could not be evaluated: {e}")
                continue
            if not ok:
                reasons.append(reason)
        return (not reasons), reasons


def notify_circuit_breaker(cfg, reasons: list) -> None:
    """Alert once an hour while a breaker is tripped."""
    try:
        from alerts.models import Notification
        title = f"⊟ Circuit breaker: {cfg.name}"
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
