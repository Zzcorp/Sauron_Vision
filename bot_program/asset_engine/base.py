"""AssetBot — base class for all asset-class-specific bots.

Common loop (tick):
  1. manage_positions — for every OPEN trade, check current price vs SL/TP, close if hit.
  2. can_open_new — gate: max concurrent + daily loss limit.
  3. scan_for_entries — for each symbol in cfg.symbols, decide() and open if BUY/SELL.

Default `decide()` consumes Phase-1 active Signal rows for the instrument:
sufficient bullish/bearish agreement with score ≥ entry_score_min triggers an
entry. Subclasses can override for asset-specific logic.

Sizing default is dollar-based:
    qty = (capital × position_size_pct%) / current_price

Subclasses can override `position_size()` for forex lot sizing, etc.

Every trade is tagged with `rule_name` so Phase 1–12 grade and act on it
the same way they do Signal rows.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


@dataclass
class BotDecision:
    direction: str  # "BUY" | "SELL" | "HOLD"
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    rule_name: str = ""


class AssetBot(ABC):
    """Base class. Subclass per asset_class to specialise decide()/sizing."""

    asset_class: str = ""

    def __init__(self, config):
        self.cfg = config
        self.user = config.user

    # ── tick loop ────────────────────────────────────────────────────────

    def tick(self) -> dict:
        """Run one cycle. Returns a summary dict for logging."""
        managed = self.manage_positions()
        ok, gate_reason = self.can_open_new()
        opened = []
        if ok:
            for symbol in (self.cfg.symbols or []):
                try:
                    res = self.scan_symbol(symbol)
                    if res:
                        opened.append(res)
                    ok, gate_reason = self.can_open_new()
                    if not ok:
                        break
                except Exception as e:
                    logger.warning("[%s_bot] scan_symbol(%s) failed: %s",
                                   self.asset_class, symbol, e)
        return {
            "asset_class": self.asset_class, "config_id": self.cfg.id,
            "managed": managed, "opened": opened, "gate_reason": gate_reason,
        }

    # ── position management ──────────────────────────────────────────────

    def manage_positions(self) -> int:
        """Walk OPEN trades, close any that hit stop_loss or take_profit.
        Returns number of trades closed this tick.
        """
        from bot_program.models import AssetBotTrade
        from bot_program.engine.broker_router import client_for_symbol

        closed = 0
        for trade in AssetBotTrade.objects.filter(config=self.cfg, status="OPEN"):
            try:
                # Broker-side protected trades: the broker owns SL/TP (bracket
                # or on-fill orders). Managing them here too would double-close
                # — our market order flattens, then the broker's resting stop
                # fires later and opens a REVERSE position. Reconciliation
                # detects the broker-side close and finalises the row.
                if (trade.metadata or {}).get("protected"):
                    continue
                client = client_for_symbol(self.user, trade.symbol, self.cfg)

                # Money-safety: the entry path refuses to trade when a LIVE
                # config falls back to PaperTrader; managing must refuse too.
                # Otherwise a stale LiveQuote read through PaperTrader can
                # cross SL/TP, PaperTrader returns a synthetic FILLED order,
                # and the row is stamped CLOSED while the real position is
                # still open at the broker.
                if not trade.paper and self._is_paper_client(client):
                    logger.error(
                        "[%s_bot] LIVE trade %s cannot be managed: broker "
                        "unavailable (PaperTrader fallback) — leaving OPEN",
                        self.asset_class, trade.symbol)
                    continue

                price = self._mark_price(trade, client)
                if price is None or price <= 0:
                    continue
                hit_sl = (
                    (trade.side == "BUY" and trade.stop_loss is not None
                     and price <= trade.stop_loss)
                    or (trade.side == "SELL" and trade.stop_loss is not None
                        and price >= trade.stop_loss)
                )
                hit_tp = (
                    (trade.side == "BUY" and trade.take_profit is not None
                     and price >= trade.take_profit)
                    or (trade.side == "SELL" and trade.take_profit is not None
                        and price <= trade.take_profit)
                )
                if hit_sl or hit_tp:
                    if self._close_trade(trade, price, client,
                                          reason="TP" if hit_tp else "SL"):
                        closed += 1
            except Exception as e:
                logger.warning("[%s_bot] manage(%s) failed: %s",
                               self.asset_class, trade.symbol, e)
        return closed

    # ── overridable marking / pnl / close-order hooks ────────────────────
    # OptionsBot overrides all three: its trades are premium-denominated and
    # close via option orders, never by trading the underlying.

    def _mark_price(self, trade, client) -> Optional[Decimal]:
        """Current mark for SL/TP checks. Default: broker ticker last price.
        Return None to skip managing this trade on this tick."""
        tk = client.ticker(trade.symbol)
        price = Decimal(str(tk.get("lastPrice", "0") or "0"))
        return price if price > 0 else None

    def _trade_pnl(self, trade, price: Decimal) -> Decimal:
        """Realised pnl for closing `trade` at `price` (config base_currency)."""
        if trade.side == "BUY":
            return (price - trade.entry_price) * trade.qty
        return (trade.entry_price - price) * trade.qty

    def _submit_close_order(self, trade, client, client_order_id: str):
        """Submit the broker order that flattens `trade`. Raise on failure."""
        close_side = "SELL" if trade.side == "BUY" else "BUY"
        client.market_order(trade.symbol, close_side, float(trade.qty),
                            client_order_id=client_order_id)

    def _cancel_protective_orders(self, trade, client):
        """Best-effort cancel of resting broker-side SL/TP orders before a
        manual/expiry/kill flatten — a stop left behind would fire against a
        flat book and open a brand-new reverse position."""
        ids = (trade.metadata or {}).get("protective_order_ids") or []
        cancel = getattr(client, "cancel_order", None)
        if not ids or not callable(cancel):
            return
        for oid in ids:
            try:
                cancel(oid)
            except Exception as e:
                logger.warning("[%s_bot] cancel protective order %s failed: %s",
                               self.asset_class, oid, e)

    def _close_trade(self, trade, price: Decimal, client, *, reason: str) -> bool:
        """Close a trade — pnl is realised in the config's base_currency.

        The broker order is attempted FIRST; the row is finalised CLOSED only
        when that succeeded (or the trade is paper). On broker failure the row
        moves to CLOSE_PENDING — the position is still live at the broker —
        and the retry_pending_closes beat task drains it. Returns True when
        the trade ended CLOSED.
        """
        if not trade.paper:
            try:
                # Phase-33 idempotency on close — id derived from trade.id so
                # a retry of the same close uses the same id.
                from bot_program.engine.idempotency import make_client_order_id
                client_order_id = make_client_order_id(
                    config_id=self.cfg.id, symbol=trade.symbol,
                    signal_id=str(trade.id), intent="EXIT",
                    bar_ts=timezone.now().strftime("%Y%m%d%H%M"),
                )
                self._cancel_protective_orders(trade, client)
                self._submit_close_order(trade, client, client_order_id)
            except Exception as e:
                logger.error("[%s_bot] live close order failed for %s: %s — "
                             "marking CLOSE_PENDING",
                             self.asset_class, trade.symbol, e)
                trade.status = "CLOSE_PENDING"
                if "close-failed" not in (trade.reason or ""):
                    trade.reason = ((trade.reason or "")
                                    + f" | close-failed:{reason}").strip()[:1000]
                trade.save(update_fields=["status", "reason"])
                self._notify_close_pending(trade, reason)
                try:
                    from dashboard.consumers import push_eye_event
                    push_eye_event(self.user, "close_pending", {
                        "trade_id": trade.id, "asset_class": self.asset_class,
                        "symbol": trade.symbol,
                    })
                except Exception:
                    pass
                return False

        pnl = self._trade_pnl(trade, price)
        trade.exit_price = price
        trade.pnl = pnl
        trade.status = "CLOSED"
        trade.closed_at = timezone.now()
        trade.reason = ((trade.reason or "") + f" | closed:{reason}").strip()[:1000]
        trade.save()

        # Phase-17: self-grade on close. Failure here never blocks the close.
        try:
            from bot_program.bot_grading import grade_bot_trade
            grade_bot_trade(trade)
        except Exception as e:
            logger.warning("[%s_bot] grade_bot_trade failed for %s: %s",
                           self.asset_class, trade.symbol, e)

        # Phase-20: notify on close (after grading so outcome is set).
        try:
            from bot_program.notifications import notify_bot_fill_close
            notify_bot_fill_close(
                self.user, asset_class=self.asset_class, symbol=trade.symbol,
                side=trade.side, qty=trade.qty, exit_price=trade.exit_price,
                pnl=trade.pnl, outcome=trade.outcome or "",
            )
        except Exception as e:
            logger.warning("[%s_bot] close notification failed: %s",
                           self.asset_class, e)

        # Phase-28: append to immutable audit log.
        try:
            from bot_program.audit import record_trade_close
            record_trade_close(self.user, trade=trade)
        except Exception as e:
            logger.warning("[%s_bot] audit record_trade_close failed: %s",
                           self.asset_class, e)

        # Phase-27: consume tax lots for the realised P&L.
        try:
            from bot_program.tax_lots import close_lots_for
            close_lots_for(trade)
        except Exception as e:
            logger.warning("[%s_bot] tax_lots.close_lots_for failed: %s",
                           self.asset_class, e)

        # Phase-23: push the close event to the user's Eye WebSocket.
        try:
            from dashboard.consumers import push_eye_event
            push_eye_event(self.user, "fill_close", {
                "trade_id": trade.id, "asset_class": self.asset_class,
                "symbol": trade.symbol, "side": trade.side,
                "outcome": trade.outcome or "",
                "pnl": str(trade.pnl) if trade.pnl is not None else "0",
            })
        except Exception as e:
            logger.warning("[%s_bot] WS push (close) failed: %s",
                           self.asset_class, e)
        return True

    def _notify_close_pending(self, trade, reason: str):
        """Best-effort alert for a failed live close, deduped per trade/hour."""
        try:
            from datetime import timedelta as _td
            from alerts.models import Notification as _N
            title = f"⏳ Close pending: {trade.symbol}"
            recent = _N.objects.filter(
                user=self.user, notification_type="bot", title=title,
                created_at__gte=timezone.now() - _td(hours=1),
            ).exists()
            if not recent:
                _N.objects.create(
                    user=self.user, notification_type="bot", title=title,
                    body=(f"Broker close order failed for {self.asset_class} "
                          f"trade #{trade.id} ({reason}). The position is "
                          f"still open at the broker; retrying every 5 min."),
                    url="/eye/fills/",
                )
        except Exception as e:
            logger.warning("[%s_bot] close-pending notification failed: %s",
                           self.asset_class, e)

    # ── gating ───────────────────────────────────────────────────────────

    def can_open_new(self) -> tuple[bool, str]:
        from bot_program.models import AssetBotTrade
        # CLOSE_PENDING still holds capital/exposure at the broker.
        open_count = AssetBotTrade.objects.filter(
            config=self.cfg, status__in=("OPEN", "CLOSE_PENDING")).count()
        if open_count >= self.cfg.max_concurrent_positions:
            return (False,
                    f"max {self.cfg.max_concurrent_positions} concurrent positions reached")

        # 24h realized P&L vs daily-loss limit
        since = timezone.now() - timedelta(hours=24)
        closed = AssetBotTrade.objects.filter(
            config=self.cfg, status="CLOSED", closed_at__gte=since)
        realized = sum((t.pnl for t in closed), Decimal(0))
        limit = -self.cfg.capital * Decimal(str(self.cfg.max_daily_loss_pct / 100))
        if realized <= limit and self.cfg.halt_on_drawdown:
            # Phase-20: notify drawdown limit hit. Best-effort dedupe via the
            # in-app Notification — only fire if we haven't sent one in the
            # last hour for this config (avoids spamming on every tick).
            try:
                from datetime import timedelta as _td
                from alerts.models import Notification as _N
                recent = _N.objects.filter(
                    user=self.user, notification_type="bot",
                    title__startswith="⚠ Drawdown limit reached",
                    created_at__gte=timezone.now() - _td(hours=1),
                ).exists()
                if not recent:
                    from bot_program.notifications import notify_drawdown_warning
                    notify_drawdown_warning(
                        self.user, asset_class=self.asset_class,
                        config_name=self.cfg.name,
                        realized_pnl=float(realized), limit=float(limit),
                    )
            except Exception as e:
                logger.warning("[%s_bot] drawdown notification failed: %s",
                               self.asset_class, e)
            return (False,
                    f"daily loss limit hit ({realized:.2f} {self.cfg.base_currency})")
        return (True, "ok")

    # ── per-symbol scan ─────────────────────────────────────────────────

    def scan_symbol(self, symbol: str) -> Optional[dict]:
        from bot_program.models import AssetBotTrade
        from bot_program.engine.broker_router import client_for_symbol

        # Skip if a trade for this symbol is already open (or awaiting a
        # retried close — the broker position is still live) under this config.
        if AssetBotTrade.objects.filter(
                config=self.cfg, symbol=symbol,
                status__in=("OPEN", "CLOSE_PENDING")).exists():
            return None

        # Cooldown: skip if a CLOSED trade for this symbol was created within cool_down_minutes.
        cool = self.cfg.cool_down_minutes or 0
        if cool > 0:
            recent = AssetBotTrade.objects.filter(
                config=self.cfg, symbol=symbol, status="CLOSED",
                closed_at__gte=timezone.now() - timedelta(minutes=cool),
            ).exists()
            if recent:
                return None

        decision = self.decide(symbol)
        if decision.direction == "HOLD":
            return None

        # Phase-39 brain advisory — if the central synthesizer flagged this
        # rule pause_recommended (via KnowledgeNode rule_state or latest
        # BrainReport overlay), soft-block the entry. Always advisory — fails
        # open if the brain is unreachable.
        try:
            from brain.context import brain_rule_advisory
            from brain.observations import record_observation
            status, why = brain_rule_advisory(decision.rule_name or "")
            if status == "pause_recommended":
                logger.info("[%s_bot] brain pause_recommended for %s "
                            "(rule=%s, %s) — skipping entry",
                            self.asset_class, symbol,
                            decision.rule_name or "?", why)
                record_observation(
                    kind="gate_reject",
                    payload={"reason": "brain_rule_pause", "symbol": symbol,
                              "rule_name": decision.rule_name or "",
                              "advisory_source": why},
                    source="brain_advisory",
                )
                # Phase-54 — also chain to immutable audit log so the
                # AI-driven block can be replayed forensically.
                try:
                    from bot_program.audit import record_brain_soft_block
                    record_brain_soft_block(
                        user=self.user, asset_class=self.asset_class,
                        symbol=symbol, rule_name=decision.rule_name or "",
                        advisory_source=why, status=status,
                    )
                except Exception:
                    pass
                return None
        except Exception:
            pass  # Brain advisory is never fatal.

        # Phase-15 cross-asset orchestrator gate. Opt-in per user; closes are
        # never gated, only new entries.
        try:
            from bot_program.orchestrator import gate_new_entry
            allowed, reason = gate_new_entry(
                self.user, self.asset_class, symbol, decision.direction,
            )
            if not allowed:
                logger.info("[%s_bot] orchestrator declined %s: %s",
                            self.asset_class, symbol, reason)
                return None
        except Exception as e:
            logger.warning("[%s_bot] orchestrator check failed for %s: %s",
                           self.asset_class, symbol, e)

        client = client_for_symbol(self.user, symbol, self.cfg)

        # Money-safety: a live-mode config whose broker creds are missing or
        # broken gets a PaperTrader back from the router. Refuse to trade —
        # recording a paper fill as paper=False fabricates live history that
        # reconciliation and grading then treat as real.
        if self.cfg.mode == "live" and self._is_paper_client(client):
            logger.error(
                "[%s_bot] LIVE config %s fell back to PaperTrader for %s "
                "(missing/invalid broker credentials?) — refusing to trade",
                self.asset_class, self.cfg.id, symbol)
            self._notify_paper_fallback(symbol)
            return None

        try:
            tk = client.ticker(symbol)
        except Exception as e:
            logger.warning("[%s_bot] ticker(%s) failed: %s",
                           self.asset_class, symbol, e)
            return None
        try:
            price = float(tk.get("lastPrice", "0") or 0)
        except (TypeError, ValueError):
            price = 0
        if price <= 0:
            return None

        qty = self.position_size(price)
        if qty <= 0:
            return None

        # Apply Phase-5/7/8 rule_size_multiplier (admin × allocator × promotion).
        if decision.rule_name:
            try:
                from signals.rule_actuator import rule_size_multiplier
                qty *= rule_size_multiplier(decision.rule_name)
            except Exception:
                pass
        if qty <= 0:
            return None

        sl = price * (1 - self.cfg.stop_loss_pct / 100) if decision.direction == "BUY" \
            else price * (1 + self.cfg.stop_loss_pct / 100)
        tp = price * (1 + self.cfg.take_profit_pct / 100) if decision.direction == "BUY" \
            else price * (1 - self.cfg.take_profit_pct / 100)

        paper = (self.cfg.mode == "paper")
        order_id = ""
        entry_meta = {}
        if not paper:
            # Phase-33 idempotency — deterministic clientOrderId derived from
            # (config, symbol, signal/rule, minute-bucket). Retrying the same
            # logical entry within the bucket reuses the id, so the broker
            # rejects the duplicate instead of double-filling.
            from bot_program.engine.idempotency import make_client_order_id
            bar_ts = timezone.now().strftime("%Y%m%d%H%M")
            client_order_id = make_client_order_id(
                config_id=self.cfg.id, symbol=symbol,
                signal_id=decision.rule_name or "", intent="ENTRY",
                bar_ts=bar_ts,
            )
            try:
                # Brokers that support it attach SL/TP atomically (Alpaca
                # bracket, OANDA on-fill, IBKR bracket) so the position is
                # protected even when this worker is down. Clients without
                # the capability ignore the kwargs; bot-side management then
                # remains the safety net.
                res = client.market_order(
                    symbol, decision.direction, float(qty),
                    client_order_id=client_order_id,
                    stop_loss=float(sl), take_profit=float(tp),
                )
                order_id = str(res.get("orderId", ""))
                # Detect broker-side dedup rejections: log + skip trade row.
                status = (res.get("status") or "").upper()
                if status in ("REJECTED", "DUPLICATE"):
                    logger.warning("[%s_bot] live order DEDUP for %s "
                                    "(status=%s, client_order_id=%s)",
                                    self.asset_class, symbol, status,
                                    client_order_id)
                    return None

                # Real fills: prefer the broker's average fill price and
                # filled quantity over the pre-order ticker, so slippage
                # flows into P&L and grading.
                fill_px = float(res.get("avgPrice") or 0)
                fill_qty = float(res.get("executedQty") or 0)
                if fill_px > 0:
                    price = fill_px
                    entry_meta["fill_source"] = "broker"
                else:
                    entry_meta["fill_source"] = "ticker"
                if fill_qty > 0:
                    qty = fill_qty

                # Broker-side protection bookkeeping. "protected" trades are
                # skipped by bot-side SL/TP management (no double-close).
                protective_ids = [str(x) for x in
                                  (res.get("protectiveOrders") or [])]
                if protective_ids or res.get("protectedOnFill"):
                    entry_meta["protected"] = True
                    entry_meta["protective_order_ids"] = protective_ids
            except Exception as e:
                logger.error("[%s_bot] live order failed for %s: %s",
                             self.asset_class, symbol, e)
                return None

        from bot_program.models import AssetBotTrade
        trade = AssetBotTrade.objects.create(
            config=self.cfg, asset_class=self.asset_class,
            symbol=symbol, side=decision.direction,
            qty=Decimal(str(round(qty, 8))),
            entry_price=Decimal(str(price)),
            stop_loss=Decimal(str(sl)),
            take_profit=Decimal(str(tp)),
            composite_score=decision.score,
            reason=" · ".join(decision.reasons)[:1000],
            rule_name=decision.rule_name,
            paper=paper, broker_order_id=order_id,
            metadata=entry_meta,
        )

        # Phase-20: notify on open
        try:
            from bot_program.notifications import notify_bot_fill_open
            notify_bot_fill_open(
                self.user, asset_class=self.asset_class, symbol=symbol,
                side=decision.direction, qty=trade.qty,
                entry_price=trade.entry_price, rule_name=trade.rule_name,
            )
        except Exception as e:
            logger.warning("[%s_bot] open notification failed: %s",
                           self.asset_class, e)

        # Phase-28: append to immutable audit log.
        try:
            from bot_program.audit import record_trade_open
            record_trade_open(self.user, trade=trade)
        except Exception as e:
            logger.warning("[%s_bot] audit record_trade_open failed: %s",
                           self.asset_class, e)

        # Phase-27: open a tax lot for long entries.
        try:
            from bot_program.tax_lots import open_lot
            open_lot(trade)
        except Exception as e:
            logger.warning("[%s_bot] tax_lots.open_lot failed: %s",
                           self.asset_class, e)

        # Phase-23: push the open event to the user's Eye WebSocket.
        try:
            from dashboard.consumers import push_eye_event
            push_eye_event(self.user, "fill_open", {
                "trade_id": trade.id, "asset_class": self.asset_class,
                "symbol": symbol, "side": decision.direction,
            })
        except Exception as e:
            logger.warning("[%s_bot] WS push (open) failed: %s",
                           self.asset_class, e)

        return {"trade_id": trade.id, "symbol": symbol,
                "side": decision.direction, "qty": float(qty),
                "entry": price, "score": decision.score}

    # ── live-mode paper-fallback guard ───────────────────────────────────

    @staticmethod
    def _is_paper_client(client) -> bool:
        from bot_program.engine.paper_trader import PaperTrader
        return isinstance(client, PaperTrader)

    def _notify_paper_fallback(self, symbol: str):
        """Best-effort alert, deduped to at most one per config per hour."""
        try:
            from datetime import timedelta as _td
            from alerts.models import Notification as _N
            title = f"🛑 Live bot blocked: {self.cfg.name}"
            recent = _N.objects.filter(
                user=self.user, notification_type="bot",
                title=title,
                created_at__gte=timezone.now() - _td(hours=1),
            ).exists()
            if not recent:
                _N.objects.create(
                    user=self.user, notification_type="bot", title=title,
                    body=(
                        f"{self.asset_class} config '{self.cfg.name}' is in LIVE "
                        f"mode but its broker is unavailable (missing or invalid "
                        f"credentials?). Entry on {symbol} was refused rather "
                        f"than silently traded on paper."
                    ),
                    url="/asset-bots/",
                )
        except Exception as e:
            logger.warning("[%s_bot] paper-fallback notification failed: %s",
                           self.asset_class, e)

    # ── default sizing ──────────────────────────────────────────────────

    def position_size(self, price: float) -> float:
        """Default: dollar-based. Override per asset class for lot conventions."""
        cap = float(self.cfg.capital)
        dollars = cap * (self.cfg.position_size_pct / 100.0)
        if price <= 0:
            return 0.0
        return round(dollars / price, 6)

    # ── default decision: consume Phase-1 Signal rows ────────────────────

    def decide(self, symbol: str) -> BotDecision:
        """Default decision: weighted vote over recent active Signal rows.

        Subclasses can override for asset-specific logic. Returns a BotDecision
        with rule_name=<top contributing rule> so Phase 5/7/8 multipliers apply.
        """
        from signals.models import Signal
        from instruments.models import Instrument

        inst = Instrument.objects.filter(symbol=symbol).first()
        if inst is None:
            return BotDecision("HOLD", 0, [f"no Instrument record for {symbol}"])

        active = list(
            Signal.objects.filter(instrument=inst, is_active=True)
            .order_by("-score")[:8]
        )
        if not active:
            return BotDecision("HOLD", 0, ["no active signals"])

        bullish = [s for s in active if s.direction == "bullish"
                   and s.score >= self.cfg.entry_score_min]
        bearish = [s for s in active if s.direction == "bearish"
                   and s.score >= self.cfg.entry_score_min]

        if len(bullish) >= self.cfg.min_signals_for_entry and not bearish:
            avg = sum(s.score for s in bullish) / len(bullish)
            top = max(bullish, key=lambda s: s.score)
            score = self._apply_track_record(avg, top.rule_name)
            return BotDecision(
                "BUY", round(score, 4),
                reasons=[f"{s.rule_name}: {s.title}" for s in bullish[:3]],
                rule_name=top.rule_name or "asset_bot_signal_consensus",
            )
        if len(bearish) >= self.cfg.min_signals_for_entry and not bullish:
            avg = sum(s.score for s in bearish) / len(bearish)
            top = max(bearish, key=lambda s: s.score)
            score = self._apply_track_record(avg, top.rule_name)
            return BotDecision(
                "SELL", round(score, 4),
                reasons=[f"{s.rule_name}: {s.title}" for s in bearish[:3]],
                rule_name=top.rule_name or "asset_bot_signal_consensus",
            )

        return BotDecision("HOLD", 0,
                           [f"{len(bullish)}↑ {len(bearish)}↓ — no consensus"])

    # ── Phase-17: optional bot-trade track-record feedback ──────────────

    def _apply_track_record(self, raw_score: float, rule_name: str) -> float:
        """If the config opts in via extras['use_bot_track_record']=True,
        multiply the consensus score by the rule's bot-trade confidence
        multiplier on this asset class. Returns the (possibly unchanged)
        score, capped at 1.0 so high-confidence rules don't exceed 100%.
        """
        extras = getattr(self.cfg, "extras", None) or {}
        if not extras.get("use_bot_track_record"):
            return raw_score
        if not rule_name:
            return raw_score
        try:
            from bot_program.bot_grading import bot_trade_track_record
            mult = bot_trade_track_record(rule_name, self.asset_class)
        except Exception:
            return raw_score
        return min(1.0, raw_score * mult)


# ── Factory ─────────────────────────────────────────────────────────────────

def make_bot(config) -> AssetBot:
    """Return the right subclass for `config.asset_class`."""
    from .stock_bot import StockBot
    from .forex_bot import ForexBot
    from .commodity_bot import CommodityBot
    from .options_bot import OptionsBot

    cls_map = {
        "stock": StockBot,
        "forex": ForexBot,
        "commodity": CommodityBot,
        "options": OptionsBot,
    }
    cls = cls_map.get(config.asset_class)
    if cls is None:
        raise ValueError(f"No AssetBot for asset_class={config.asset_class!r}")
    return cls(config)
