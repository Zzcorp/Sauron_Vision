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
from decimal import Decimal, InvalidOperation
from typing import Optional

from django.utils import timezone

logger = logging.getLogger(__name__)


# How far into its own ceiling a position gets before the operator is told.
# A fraction rather than a fixed lead time, because the ceilings in
# DEFAULT_MAX_HOLD_HOURS span 192h to 720h and one lead time cannot be both
# "enough notice" on a forex macro trade and "not the whole trade" on a
# tightened intraday config. At 0.8 there is always a fifth of the window
# left to act in — at least a session and a half for every shipped default.
TIME_STOP_WARN_FRACTION = 0.8

# Written on the trade the first time it is warned about. The dedupe has to
# be per TRADE and permanent: the bot ticks every five minutes, so an
# hour-window dedupe on the title would still fire twelve alerts a day for
# the last fifth of a thirty-day ceiling, and a symbol re-entered next week
# is a different position that deserves its own warning.
TIME_STOP_WARNED_META_KEY = "time_stop_warned"

# What one SMC/ICT composite vote may contribute to a consensus at full
# conviction.
#
# 0.25 is exactly `aggregation.MIN_WEIGHT` — the floor this platform already
# assigns to a rule it has MEASURED as its worst. A lane with no record at all
# has not earned more than the weight a demonstrated loser carries, and this
# lane has no record for a precise reason: `smc_score_for_symbol` returned 0.0
# through a dead import for its entire life, so no ICT setup has ever once
# reached an order. At full conviction (|score| = 1.0) it therefore contributes
# 0.25 against the default entry bar of min_signals_for_entry x entry_score_min
# = 0.60 — enough to tip a close call, never enough to make one.
SMC_VOTE_WEIGHT = 0.25

# The rule name the vote carries. Real, not cosmetic: `rule_weight` looks the
# lane's own closed trades up under it, so the moment this lane has outcomes it
# starts being weighed by them like every other rule, and a trade it topped is
# attributable in the ledger rather than filed under the consensus.
SMC_RULE_NAME = "smc_composite"


def time_stop_status(position, *, config=None, now=None) -> dict:
    """How much of its time-stop ceiling `position` has spent.

    The read side of the time stop, exposed for whatever renders a position
    — the position card, a table, a WebSocket payload. Returns:

        {"applies": bool,      # False when nothing here governs this row
         "enabled": bool,      # False when the ceiling is 0 (time stop off)
         "max_hold_hours": float | None,
         "hours_held": float,
         "hours_left": float | None,
         "fraction": float | None,   # 0..1+, share of the ceiling spent
         "approaching": bool,  # past TIME_STOP_WARN_FRACTION, not yet hit
         "hit": bool,
         "source": str}       # "extras" | "config" | "class-default" | ""

    `applies` is the important one. This platform keeps TWO position books —
    `portfolio.Position` and `bot_program.AssetBotTrade` — and a caller that
    unions them will hand rows from both here. A Position has an `opened_at`
    too, so a duck-typed reading of it would produce a confident countdown
    for a manually held position that no bot manages and no time stop will
    ever close. Those get applies=False, which a card must render as an
    em-dash rather than a number.
    """
    blank = {"applies": False, "enabled": False, "max_hold_hours": None,
             "hours_held": 0.0, "hours_left": None, "fraction": None,
             "approaching": False, "hit": False, "source": ""}

    from bot_program.models import AssetBotTrade
    if not isinstance(position, AssetBotTrade):
        return blank
    if position.opened_at is None:
        # Only reachable on an unsaved row; auto_now_add fills it otherwise.
        return blank

    cfg = config if config is not None else position.config
    if cfg is None:
        return blank

    setting = cfg.time_stop_setting()
    now = now or timezone.now()
    end = position.closed_at or now
    hours_held = max(0.0, (end - position.opened_at).total_seconds() / 3600.0)

    max_hold = float(setting["hours"])
    if not setting["enabled"]:
        # The ceiling is off, deliberately. The age is still true and still
        # worth showing — "unbounded" is a fact an operator should be able
        # to read off the row.
        return {**blank, "applies": True, "max_hold_hours": 0.0,
                "hours_held": round(hours_held, 2),
                "source": setting["source"]}

    fraction = hours_held / max_hold
    hit = fraction >= 1.0
    return {
        "applies": True, "enabled": True, "max_hold_hours": max_hold,
        "hours_held": round(hours_held, 2),
        "hours_left": round(max(0.0, max_hold - hours_held), 2),
        "fraction": round(fraction, 4),
        "approaching": (not hit) and fraction >= TIME_STOP_WARN_FRACTION,
        "hit": hit, "source": setting["source"],
    }


@dataclass
class BotDecision:
    direction: str  # "BUY" | "SELL" | "HOLD"
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    rule_name: str = ""


@dataclass
class SmcVote:
    """The SMC/ICT composite score, shaped the way the consensus reads votes.

    `weighted_consensus` and `decide()` between them read exactly three
    attributes off a vote — `score`, `rule_name`, `title` — so this is the
    whole contract. It is not a Signal row and is deliberately not persisted:
    the SmcSignal rows behind it already exist, and writing a second row per
    tick would double-count the same evidence anywhere that reads Signals.
    """
    score: float
    title: str
    rule_name: str = SMC_RULE_NAME


class AssetBot(ABC):
    """Base class. Subclass per asset_class to specialise decide()/sizing."""

    asset_class: str = ""

    def __init__(self, config):
        self.cfg = config
        self.user = config.user

    # ── tick loop ────────────────────────────────────────────────────────

    def tick(self) -> dict:
        """Run one cycle. Returns a summary dict for logging."""
        from bot_program.asset_engine.safety import write_heartbeat

        # Heartbeat first: a bot that dies mid-tick should still show when
        # it was last alive on the health page.
        write_heartbeat(self.cfg, status="RUNNING")

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

        write_heartbeat(self.cfg, status="OK", note=gate_reason)
        return {
            "asset_class": self.asset_class, "config_id": self.cfg.id,
            "managed": managed, "opened": opened, "gate_reason": gate_reason,
        }

    # ── position management ──────────────────────────────────────────────

    def manage_positions(self) -> int:
        """Walk OPEN trades, close any that hit stop_loss, take_profit, or
        the config's time-stop ceiling; warn once on the ones approaching it.
        Returns number of trades closed this tick.
        """
        from bot_program.models import AssetBotTrade
        from bot_program.engine.broker_router import client_for_symbol

        closed = 0
        for trade in AssetBotTrade.objects.filter(config=self.cfg, status="OPEN"):
            try:
                protected = bool((trade.metadata or {}).get("protected"))
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

                # The time stop runs for protected trades too. It is the one
                # exit the broker knows nothing about: a bracket holds SL and
                # TP, but nothing at the broker will release capital from a
                # thesis that simply never moved. _close_trade cancels the
                # resting legs if the flatten is rejected, so there is no
                # window where the position sits live and unprotected.
                if self._time_stop_hit(trade):
                    if self._close_trade(trade, price, client, reason="TIME"):
                        closed += 1
                    continue

                # Warned only when the ceiling has NOT been reached. A bot
                # that was stopped for a week comes back to positions already
                # past their ceiling, and "this will close soon" arriving in
                # the same tick as "this closed" is noise, not a warning.
                ts = self._time_stop_status(trade)
                if ts["approaching"]:
                    self._warn_time_stop_near(trade, ts)

                # Past here the broker owns SL/TP for protected trades
                # (bracket or on-fill orders). Managing those here too would
                # double-close — our market order flattens, then the broker's
                # resting stop fires later and opens a REVERSE position.
                # Reconciliation detects the broker-side close and finalises
                # the row.
                if protected:
                    # ...but say so when the operator has asked for stop
                    # rules this position cannot honour. Its stop rests AT
                    # THE BROKER and no client here can modify a resting
                    # order, so break-even and trailing are inert on
                    # exactly the configs most likely to hold real money.
                    # Silence there is how a form promising stop
                    # management becomes a false sense of protection.
                    self._manage_broker_stop(trade, price, client)
                    continue

                # Exits carry most of a trend system's P&L: a trailing stop
                # locks in a move that would otherwise round-trip.
                self._update_trailing_stop(trade, price)

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

    # ── exit management ──────────────────────────────────────────────────

    def _skip(self, symbol: str, code: str, detail: str = ""):
        """Record why this symbol produced no trade, and return None.

        Every `return None` in scan_symbol goes through here. Several were
        silent, which made "the market was quiet" and "this bot has never
        been capable of trading" indistinguishable from outside.
        """
        from bot_program.asset_engine import skips
        skips.record(self.cfg, symbol, code, detail)
        return None

    def _extras_float(self, key: str, default: float = 0.0) -> float:
        """Read a numeric knob out of cfg.extras without ever raising.

        extras is user-editable JSON. A typo there ("2%" instead of 0.02)
        used to raise out of the exit block and take SL/TP checking down
        with it — the trade would then run unmanaged until reconciliation
        noticed. A bad value now just means "knob off".
        """
        extras = getattr(self.cfg, "extras", None) or {}
        raw = extras.get(key, default)
        try:
            return float(raw if raw is not None else default)
        except (TypeError, ValueError):
            logger.warning("[%s_bot] cfg %s: extras[%r]=%r is not numeric — "
                           "treating as %s", self.asset_class, self.cfg.id,
                           key, raw, default)
            return float(default)

    def _manage_broker_stop(self, trade, price, client) -> bool:
        """Run the stop rules against a position whose stop is AT THE BROKER.

        The same arithmetic as the bot-managed path — `trailing` exposes
        the derivations without the write, so there is ONE answer to
        "where should this stop be" and two ways to apply it. Two copies
        would drift, and the copy that drifted would be the one moving a
        live stop.

        The order is the whole point. The leg moves at the BROKER first,
        and the row is written only if that worked. The other order
        leaves the database claiming a level the venue never accepted,
        which is worse than not moving it: the operator would read a
        protected position at a stop that exists nowhere but here.
        """
        breakeven_at_r = self._extras_float("breakeven_at_r")
        trail_pct = self._extras_float("trail_pct")
        if breakeven_at_r <= 0 and trail_pct <= 0:
            return False
        if trade.stop_loss is None:
            return False

        try:
            from bot_program.engine.trailing import (
                breakeven_candidate, is_improvement, trail_candidate,
            )
            candidate, why = None, ""
            if breakeven_at_r > 0:
                candidate = breakeven_candidate(
                    trade, price, breakeven_at_r,
                    self._extras_float("breakeven_buffer_r"))
                why = "breakeven"
            if candidate is None and trail_pct > 0:
                candidate = trail_candidate(
                    trade, price, trail_pct,
                    self._extras_float("trail_start_r"))
                why = "trail"
            # Asked BEFORE anything reaches a broker: a leg modified and
            # then refused by our own tighten-only rule would be a round
            # trip that changed the venue and not the row.
            if not is_improvement(trade, candidate, price):
                return False
        except Exception as e:  # noqa: BLE001 — a knob typo must not
            # take the exit block down with it; the trade would then run
            # unmanaged until reconciliation noticed.
            logger.warning("[%s_bot] stop rules failed for %s: %s",
                           self.asset_class, trade.symbol, e)
            return False

        mover = getattr(client, "modify_protective", None)
        if not callable(mover):
            # This broker cannot move a resting order. Say so once and
            # leave the stop where the bracket put it — a row-only write
            # here is the exact lie this method exists to avoid.
            self._note_stop_rules_inert(trade)
            return False

        meta_now = trade.metadata or {}
        # A trade-level handle wins: on OANDA the stop is not a standalone
        # order at all, and the trade id is the only thing that can move it.
        # Then a NAMED stop leg, where the venue told us which one it is.
        # The flat list is the last resort, and it is a list precisely
        # because it does not say which id is which — which is why the
        # venue client must refuse a leg that is not a stop rather than
        # move whatever it is handed.
        handle = (meta_now.get("protective_trade_id")
                  or meta_now.get("protective_stop_id"))
        ids = [handle] if handle else (
            meta_now.get("protective_order_ids") or [])
        if not ids:
            self._note_stop_rules_inert(trade)
            return False

        moved, note, accepted = False, "no leg matched", None
        for oid in ids:
            try:
                res = mover(str(oid), float(candidate))
            except Exception as e:  # noqa: BLE001
                note = str(e)
                continue
            if res and res.get("ok"):
                moved, note = True, str(res.get("price"))
                accepted = res.get("price")
                break
            note = (res or {}).get("reason") or note

        if not moved:
            logger.warning(
                "[%s_bot] %s: %s wanted the stop at %s but the broker leg "
                "could not be moved (%s) — the position is still protected "
                "at its old level",
                self.asset_class, trade.symbol, why, candidate, note)
            return False

        # The venue accepted it, so the row may now say so — and it says
        # what the VENUE took, not what we asked for. A stop is snapped onto
        # the contract's minTick before it is sent (0.05 on many options,
        # 0.25 on ES), so the accepted price can differ from `candidate` by
        # up to a tick. Recording the request left the row, the forensics
        # timeline and the operator's "protected at" reading describing a
        # level that rests nowhere — and it biased the ratchet, because
        # `is_improvement` compares the next candidate against this field.
        resting = candidate
        if accepted is not None:
            try:
                resting = Decimal(str(accepted))
            except (TypeError, ValueError, InvalidOperation):
                resting = candidate      # keep the request rather than none
        meta = dict(trade.metadata or {})
        moves = list(meta.get("stop_moves") or [])
        moves.append({"to": str(resting), "asked": str(candidate),
                      "at": str(price), "why": why + ":broker"})
        meta["stop_moves"] = moves[-20:]
        if why == "breakeven":
            meta["breakeven_armed"] = True
        # A leg that MOVED is proof the rules are not inert after all.
        meta.pop("stop_rules_inert", None)
        trade.stop_loss = resting
        trade.metadata = meta
        trade.save(update_fields=["stop_loss", "metadata"])
        logger.info("[%s_bot] %s %s moved the BROKER stop to %s (asked %s) "
                    "at mark %s", self.asset_class, trade.symbol, why,
                    resting, candidate, price)
        return True

    def _note_stop_rules_inert(self, trade) -> None:
        """Warn once per trade that its stop rules cannot run.

        Only for positions whose config actually asked for one: a config
        with no stop rules configured is not owed a warning about them.
        """
        if not (self._extras_float("breakeven_at_r") > 0
                or self._extras_float("trail_pct") > 0):
            return
        meta = trade.metadata or {}
        if meta.get("stop_rules_inert"):
            return
        logger.warning(
            "[%s_bot] %s: break-even/trailing are configured but this "
            "position's stop RESTS AT THE BROKER, which no client can "
            "modify yet - the stop stays where the bracket put it",
            self.asset_class, trade.symbol)
        try:
            meta = dict(meta)
            meta["stop_rules_inert"] = "broker_protected"
            trade.metadata = meta
            trade.save(update_fields=["metadata"])
        except Exception as e:  # pragma: no cover - never block the tick
            logger.warning("[%s_bot] could not stamp stop_rules_inert: %s",
                           self.asset_class, e)

    def _update_trailing_stop(self, trade, price: Decimal) -> bool:
        """Move the stop as the trade runs. True if it moved.

        Two rules, applied in order, both opt-in and both off by default:

          extras['breakeven_at_r']  - once the trade has run this many R,
              put the stop at entry (plus extras['breakeven_buffer_r'],
              also in R, so the spread and both commissions come out of
              the winning side rather than turning a "break-even" exit
              into a small loss). Fires once.
          extras['trail_pct']       - ratchet the stop to a percentage
              below the mark, no sooner than extras['trail_start_r'].

        Break-even runs FIRST: it is the cheap, one-off move that stops a
        winner becoming a loser, and the trail takes the stop from there.
        Running them the other way round would let a trail that has
        already passed entry be dragged back to it.

        Neither rule can loosen a stop, and neither can place one on the
        wrong side of the mark - see bot_program.engine.trailing.
        """
        breakeven_at_r = self._extras_float("breakeven_at_r")
        trail_pct = self._extras_float("trail_pct")
        if breakeven_at_r <= 0 and trail_pct <= 0:
            return False
        if trade.stop_loss is None:
            return False

        # Defensive only. manage_positions already skips protected rows
        # and calls _note_stop_rules_inert at that skip, which is where
        # the disclosure belongs - putting it here made it unreachable
        # from production while a direct-call test kept passing.
        if (trade.metadata or {}).get("protected"):
            return False

        moved = False
        try:
            from bot_program.engine.trailing import (
                apply_breakeven, update_trailing_stop,
            )
            if breakeven_at_r > 0:
                moved = bool(apply_breakeven(
                    trade, price, breakeven_at_r,
                    self._extras_float("breakeven_buffer_r")))
            if trail_pct > 0:
                moved = bool(update_trailing_stop(
                    trade, price, trail_pct,
                    self._extras_float("trail_start_r"))) or moved
        except Exception as e:
            # A knob typo must never take the exit block down with it: the
            # trade would then run unmanaged until reconciliation noticed.
            logger.warning("[%s_bot] stop management failed for %s: %s",
                           self.asset_class, trade.symbol, e)
            return False
        if moved:
            logger.info("[%s_bot] %s stop moved to %s at mark %s",
                        self.asset_class, trade.symbol,
                        trade.stop_loss, price)
        return moved

    def _time_stop_status(self, trade) -> dict:
        """This config's time-stop reading for `trade`. See `time_stop_status`.

        Passes `self.cfg` explicitly so managing N positions does not fetch
        the same config N times.
        """
        return time_stop_status(trade, config=self.cfg)

    def _time_stop_hit(self, trade) -> bool:
        """True when a trade has been open longer than its config's ceiling.

        Capital tied up in a thesis that never resolved is capital not
        available to the next setup. The ceiling comes from
        `AssetBotConfig.time_stop_setting()` — the visible `max_hold_hours`
        field, the legacy `extras["max_hold_hours"]` key when an install
        already set one, or the asset-class default. It was previously read
        only out of extras, which nothing ever wrote, so this exit could
        never fire.
        """
        status = self._time_stop_status(trade)
        if not status["hit"]:
            return False
        logger.info("[%s_bot] time stop on %s after %.1fh (max %.1fh, %s)",
                    self.asset_class, trade.symbol, status["hours_held"],
                    status["max_hold_hours"], status["source"])
        return True

    def _warn_time_stop_near(self, trade, status: dict) -> bool:
        """Tell the operator once, before the engine flattens the position.

        A time stop that only announces itself by closing the trade is a
        surprise: the operator finds a position gone and a TIME exit in the
        ledger, with no window in which they could have added to it, cut it
        early, or raised the ceiling because the thesis is still alive.

        Built inline rather than through `notifications.dispatch_notification`
        for the same reason as the two alerts below it: this is a
        position-safety event, and it should not be muted by the preference
        that silences routine fill chatter.
        """
        if (trade.metadata or {}).get(TIME_STOP_WARNED_META_KEY):
            return False
        try:
            from alerts.links import page_url
            from alerts.models import Notification as _N
            hours_left = status["hours_left"]
            _N.objects.create(
                user=self.user, notification_type="bot",
                title=f"⧗ Time stop nearing: {trade.symbol}",
                body=(f"{self.asset_class.upper()} {trade.side} {trade.symbol} "
                      f"has been open {status['hours_held']:.0f}h of a "
                      f"{status['max_hold_hours']:.0f}h ceiling "
                      f"({status['source']}). In about {hours_left:.0f}h the "
                      f"bot will flatten it with reason TIME — the thesis has "
                      f"not resolved. Close it, add to it, or raise the "
                      f"config's max hold."),
                # The trade's own page: the rule that fired, the signals that
                # voted and the levels. "Should this run longer?" is answered
                # there and nowhere on a list page.
                url=page_url("forensics_detail", trade.id) or "/asset-bots/",
            )
        except Exception as e:
            logger.warning("[%s_bot] time-stop warning failed for %s: %s",
                           self.asset_class, trade.symbol, e)
            # Not marking it warned: a failed alert should be retried on the
            # next tick, not swallowed for the rest of the position's life.
            return False

        # Marked only after the row exists, and on the trade rather than in a
        # dedupe query, so the warning survives a notification purge and can
        # never fire twice for the same position.
        meta = dict(trade.metadata or {})
        meta[TIME_STOP_WARNED_META_KEY] = True
        trade.metadata = meta
        trade.save(update_fields=["metadata"])
        return True

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
        """Submit the broker order that flattens `trade`. Raise on failure.

        RETURNS the broker's response. The caller books the exit at the fill
        that response reports, exactly as the entry path books its own fill:
        an exit recorded at the mark we read BEFORE the order hides all the
        exit slippage, and stop-outs — where most of it lives — fire into
        fast one-sided markets. Overrides must return it too; one that
        returns None degrades to a mark-priced exit, flagged as such.
        """
        close_side = "SELL" if trade.side == "BUY" else "BUY"
        return client.market_order(trade.symbol, close_side, float(trade.qty),
                                   client_order_id=client_order_id)

    # A broker that ANSWERS with a refusal has not closed anything. Only
    # an exception used to reach the failure path, so a client that
    # returns {"status": "REJECTED"} instead of raising — which is
    # exactly what the IBKR client does — took the success branch and
    # stripped the bracket off a position that is still live.
    CLOSE_REFUSED_STATUSES = frozenset({
        "REJECTED", "DUPLICATE", "CANCELLED", "CANCELED",
        "INACTIVE", "EXPIRED", "ERROR",
    })

    def _submit_close_or_raise(self, trade, client, client_order_id):
        """The close, with a refusal RESPONSE raised like a refusal."""
        res = self._submit_close_order(trade, client, client_order_id)
        if isinstance(res, dict):
            status = (res.get("status") or "").strip().upper()
            try:
                filled = float(res.get("executedQty") or 0)
            except (TypeError, ValueError):
                filled = 0.0
            if status in self.CLOSE_REFUSED_STATUSES and filled <= 0:
                reason = ""
                raw = res.get("raw")
                if isinstance(raw, dict):
                    reason = str(raw.get("reason") or "")
                raise RuntimeError(
                    f"broker refused the close ({status}"
                    + (f": {reason}" if reason else "") + ")")
        return res

    def _cancel_protective_orders(self, trade, client) -> bool:
        """Cancel resting broker-side SL/TP legs before a flatten.

        Returns True only when every leg was confirmed handled. A stop
        left behind fires against a flat book and OPENS a brand-new
        reverse position, so "we could not tell" must never be recorded
        as "done" — the caller marks the row when this comes back False.
        """
        ids = (trade.metadata or {}).get("protective_order_ids") or []
        cancel = getattr(client, "cancel_order", None)
        if not ids:
            return True
        if not callable(cancel):
            logger.error("[%s_bot] %s carries protective legs but this "
                         "broker client cannot cancel orders — they may "
                         "still be resting",
                         self.asset_class, trade.symbol)
            return False
        ok = True
        for oid in ids:
            try:
                cancel(oid)
            except Exception as e:
                ok = False
                logger.error("[%s_bot] cancel protective order %s failed: "
                             "%s — it may still be resting at the broker",
                             self.asset_class, oid, e)
        return ok

    def _close_trade(self, trade, price: Decimal, client, *, reason: str) -> bool:
        """Close a trade — pnl is realised in the config's base_currency.

        The broker order is attempted FIRST; the row is finalised CLOSED only
        when that succeeded (or the trade is paper). On broker failure the row
        moves to CLOSE_PENDING — the position is still live at the broker —
        and the retry_pending_closes beat task drains it. Returns True when
        the trade ended CLOSED.
        """
        stripped = False
        close_result = None
        if not trade.paper:
            # A row that already recorded a partly filled close belongs to
            # the retry loop, which knows the residual and submits THAT size.
            # Sending trade.qty from here would sell units the account no
            # longer holds — that does not close anything, it opens a
            # position the other way. Reachable because the options expiry
            # sweep re-closes CLOSE_PENDING rows.
            from bot_program.pending_closes import residual_qty
            outstanding = residual_qty(trade)
            if outstanding < trade.qty:
                logger.error(
                    "[%s_bot] %s already filled %s of %s on an earlier close "
                    "— leaving the %s residual to the retry loop rather than "
                    "resubmitting the full size",
                    self.asset_class, trade.symbol,
                    trade.qty - outstanding, trade.qty, outstanding)
                return False

            try:
                # Phase-33 idempotency on close — id derived from trade.id so
                # a retry of the same close uses the same id.
                from bot_program.engine.idempotency import make_client_order_id
                client_order_id = make_client_order_id(
                    config_id=self.cfg.id, symbol=trade.symbol,
                    signal_id=str(trade.id), intent="EXIT",
                    bar_ts=timezone.now().strftime("%Y%m%d%H%M"),
                )
                # Try the close FIRST and only strip the broker's protective
                # legs if the close is rejected because they hold the shares.
                # Cancelling up-front would leave a live, unprotected position
                # whenever the close then fails.
                try:
                    close_result = self._submit_close_or_raise(
                        trade, client, client_order_id)
                except Exception:
                    if not (trade.metadata or {}).get("protective_order_ids"):
                        raise
                    logger.warning(
                        "[%s_bot] close rejected for %s — cancelling "
                        "protective legs and retrying once",
                        self.asset_class, trade.symbol)
                    # The answer matters on THIS branch too. The success
                    # branch below records an unconfirmed leg on the row;
                    # here it was dropped on the floor, so a stop we
                    # could not confirm cancelled left no trace at all
                    # once the retry succeeded and the row went CLOSED.
                    # A resting exit against a flat book does not close
                    # anything - it opens a position the other way.
                    if not self._cancel_protective_orders(trade, client):
                        meta = dict(trade.metadata or {})
                        meta["protective_legs_unconfirmed"] = True
                        trade.metadata = meta
                        trade.save(update_fields=["metadata"])
                        logger.critical(
                            "[%s_bot] %s: a protective leg could not be "
                            "confirmed cancelled while clearing the way "
                            "for a close retry - check the broker for a "
                            "resting order",
                            self.asset_class, trade.symbol)
                    # From here the position has no broker-side stop. If the
                    # retry also fails the row goes CLOSE_PENDING with a live,
                    # UNPROTECTED position behind it — a materially worse
                    # state than an ordinary pending close, and the retry task
                    # and the operator both need to know which one it is.
                    stripped = True
                    close_result = self._submit_close_or_raise(
                        trade, client, client_order_id)
                    stripped = False
                else:
                    # The close went through, so the bracket's resting legs
                    # are now orphaned. Left alone, the stop eventually
                    # fires against a flat book and opens a brand-new
                    # position in the opposite direction — unmonitored,
                    # because no row in our database describes it.
                    if not self._cancel_protective_orders(trade, client):
                        # Say so on the row: a leg we could not confirm
                        # gone is the operator's problem now, and a
                        # silent flag would hide it forever.
                        meta = dict(trade.metadata or {})
                        meta["protective_legs_unconfirmed"] = True
                        trade.metadata = meta
                        trade.save(update_fields=["metadata"])
                        logger.critical(
                            "[%s_bot] %s closed, but a protective leg could "
                            "not be confirmed cancelled — check the broker "
                            "for a resting order",
                            self.asset_class, trade.symbol)
            except Exception as e:
                logger.error("[%s_bot] live close order failed for %s: %s — "
                             "marking CLOSE_PENDING",
                             self.asset_class, trade.symbol, e)
                trade.status = "CLOSE_PENDING"
                if "close-failed" not in (trade.reason or ""):
                    trade.reason = ((trade.reason or "")
                                    + f" | close-failed:{reason}").strip()[:1000]
                fields = ["status", "reason"]
                if stripped:
                    logger.critical(
                        "[%s_bot] %s is LIVE AND UNPROTECTED: its bracket was "
                        "cancelled to allow a close that then failed",
                        self.asset_class, trade.symbol)
                    meta = dict(trade.metadata or {})
                    meta["protection_stripped"] = True
                    meta["protected"] = False
                    trade.metadata = meta
                    fields.append("metadata")
                trade.save(update_fields=fields)
                self._notify_close_pending(trade, reason)
                try:
                    from dashboard.consumers import push_eye_event
                    push_eye_event(self.user, "close_pending", {
                        "trade_id": trade.id, "asset_class": self.asset_class,
                        "symbol": trade.symbol,
                    })
                except Exception as e:
                    logger.warning("[%s_bot] WS push (close_pending) failed: %s",
                                   self.asset_class, e)
                return False

        # ── Book the exit ────────────────────────────────────────────────
        # The two venues differ here, deliberately. A LIVE exit is read back
        # off the broker (avgPrice / executedQty), the same way the entry
        # path reads its fill, so real slippage lands in pnl and realized_r.
        # A PAPER exit has no broker fill to read: paper_fill_price charges
        # the adverse half of the modelled round trip, and that IS the paper
        # venue's slippage model. "Reading a fill" on paper would just mean
        # reading back the number we invented, so paper keeps booking exactly
        # what it always booked.
        from bot_program.pending_closes import paper_exit_fill, resolve_exit_fill
        if trade.paper:
            # The exit half of the round trip. Without this a paper trade
            # books a free entry and a free exit, and its expectancy is
            # overstated by the full round trip — the exact quantity the cost
            # filter rejects trades for being unable to cover.
            #
            # Charged on every exit, including take-profits. A take-profit
            # is a limit order and would not cross the spread, so this is
            # deliberately CONSERVATIVE rather than precise — the cost model
            # is a single blended round-trip number and does not separate
            # spread from commission, and for evidence you intend to bet
            # real money on, erring toward overstating cost is the right
            # direction. It no longer affects classification: grading reads
            # the recorded close reason, not the post-cost fill price.
            from bot_program.asset_engine.risk_levels import paper_fill_price
            exit_side = "SELL" if trade.side == "BUY" else "BUY"
            fill = paper_exit_fill(trade, Decimal(str(paper_fill_price(
                self.cfg, trade.symbol, float(price), exit_side))))
        else:
            fill = resolve_exit_fill(trade, close_result, mark=price)

        if not fill["complete"]:
            return self._book_partial_close(trade, fill, reason)

        price = fill["price"]
        trade.metadata = {**(trade.metadata or {}), **fill["metadata"]}
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
                trade_id=trade.id,
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

    def _book_partial_close(self, trade, fill: dict, reason: str) -> bool:
        """The broker filled only PART of the close. Keep the row live.

        Marking it CLOSED would be the worst outcome in this file: the
        residual stays open at the broker, `reconcile_asset` only ever scans
        OPEN/CLOSE_PENDING rows, and the retry beat task only drains
        CLOSE_PENDING — so a CLOSED row with a live remainder behind it is
        watched by nothing, permanently. In CLOSE_PENDING with the residual
        recorded, the retry loop, reconciliation and the concurrency gate all
        see it. Returns False: this close did not finish.
        """
        trade.status = "CLOSE_PENDING"
        trade.metadata = {**(trade.metadata or {}), **fill["metadata"]}
        if "partial-close" not in (trade.reason or ""):
            trade.reason = ((trade.reason or "")
                            + f" | partial-close:{reason}").strip()[:1000]
        trade.save(update_fields=["status", "metadata", "reason"])
        logger.error(
            "[%s_bot] close for %s filled %s of %s — %s is STILL OPEN at the "
            "broker; row left CLOSE_PENDING for the retry task",
            self.asset_class, trade.symbol, fill["filled_qty"], trade.qty,
            fill["residual_qty"])

        self._notify_partial_close(trade, fill)
        try:
            from dashboard.consumers import push_eye_event
            push_eye_event(self.user, "close_pending", {
                "trade_id": trade.id, "asset_class": self.asset_class,
                "symbol": trade.symbol, "partial": True,
                "residual_qty": str(fill["residual_qty"]),
            })
        except Exception as e:
            logger.warning("[%s_bot] WS push (partial close) failed: %s",
                           self.asset_class, e)
        return False

    def _notify_partial_close(self, trade, fill: dict):
        """Alert the operator that a close only partly filled.

        Separate from `_notify_close_pending` because the two situations ask
        for different things. A rejected close means nothing moved and the
        retry will handle it. A PARTIAL means the order was accepted, some of
        the position is gone, and what is left is a smaller live position
        than the row's qty shows — so a human reading their broker screen
        against this platform will see two different numbers until it drains.
        """
        try:
            from datetime import timedelta as _td
            from alerts.links import page_url
            from alerts.models import Notification as _N
            title = f"◧ Partial close: {trade.symbol}"
            recent = _N.objects.filter(
                user=self.user, notification_type="bot", title=title,
                created_at__gte=timezone.now() - _td(hours=1),
            ).exists()
            if recent:
                return
            n = _N(
                user=self.user, notification_type="bot", title=title,
                body=(f"The broker filled only {fill['filled_qty']} of "
                      f"{trade.qty} on the close of {self.asset_class} trade "
                      f"#{trade.id}. {fill['residual_qty']} is still open at "
                      f"the broker; the row stays CLOSE_PENDING and the "
                      f"residual is retried every 5 min."),
                url=page_url("forensics_detail", trade.id) or "/eye/fills/",
            )
            # Same rule as _notify_close_pending: the caller pushes the sticky
            # close_pending banner, so this must not also draw a transient card.
            n._banner_silent = True
            n.save()
        except Exception as e:
            logger.warning("[%s_bot] partial-close notification failed: %s",
                           self.asset_class, e)

    def _notify_close_pending(self, trade, reason: str):
        """Best-effort alert for a failed live close, deduped per trade/hour."""
        try:
            from datetime import timedelta as _td
            from alerts.links import page_url
            from alerts.models import Notification as _N
            title = f"⟳ Close pending: {trade.symbol}"
            recent = _N.objects.filter(
                user=self.user, notification_type="bot", title=title,
                created_at__gte=timezone.now() - _td(hours=1),
            ).exists()
            if not recent:
                n = _N(
                    user=self.user, notification_type="bot", title=title,
                    body=(f"Broker close order failed for {self.asset_class} "
                          f"trade #{trade.id} ({reason}). The position is "
                          f"still open at the broker; retrying every 5 min."),
                    # Straight to the trade the body names — the fill list
                    # makes the operator search for it while it is still
                    # open at the broker.
                    url=page_url("forensics_detail", trade.id) or "/eye/fills/",
                )
                # The caller pushes the sticky red close_pending banner
                # right after this — the same incident must not also draw
                # a green transient "Bot event" card. Badge still moves.
                n._banner_silent = True
                n.save()
        except Exception as e:
            logger.warning("[%s_bot] close-pending notification failed: %s",
                           self.asset_class, e)

    # ── gating ───────────────────────────────────────────────────────────

    def _still_armed(self) -> bool:
        """Is this config STILL enabled, according to the database?

        `execute_kill_switch` disables every config, flattens every open row
        and hands back a result an operator reads as "everything is closed".
        A tick already running holds `self.cfg` in memory from before that
        sweep and never asks again — and can_open_new checked the breakers,
        the book, the concurrency count and the 24h loss without once
        reading `enabled`. So the surviving tick kept opening at the broker
        for each remaining symbol, AFTER the flatten pass had walked past
        them.

        Nothing manages what it opens, either: the runner refuses a disabled
        config, so bot-side trailing and the time stop never run on those
        units. Only the entry bracket protects them.

        Fails OPEN on a database error, deliberately and loudly: the same
        posture `preflight` takes, because halting the whole fleet on a
        transient hiccup is the worse failure. A disarm is a deliberate act
        that will still be true on the next tick; a dropped connection is
        not.
        """
        from bot_program.models import AssetBotConfig
        try:
            still = (AssetBotConfig.objects
                     .filter(pk=self.cfg.pk)
                     .values_list("enabled", flat=True)
                     .first())
        except Exception as e:  # noqa: BLE001 — see the docstring
            logger.warning("[%s_bot] %s: could not re-read `enabled` (%s) — "
                           "continuing this pass", self.asset_class,
                           self.cfg.name, e)
            return True
        return bool(still)

    def can_open_new(self) -> tuple[bool, str]:
        from bot_program.models import AssetBotTrade
        from bot_program.asset_engine.safety import (
            CircuitBreakers, notify_circuit_breaker,
        )

        if not self._still_armed():
            return (False, "config was disarmed mid-tick (kill switch or "
                           "operator) — no entries this pass")

        # Circuit breakers: stop opening when the recent record says
        # something is wrong. Never force-closes — an automated system that
        # starts closing on a heuristic is worse than one that just stops.
        breakers = CircuitBreakers(self.cfg)
        allowed, reasons = breakers.check_all()
        if not allowed:
            notify_circuit_breaker(self.cfg, reasons)
            return (False, "circuit breaker: " + "; ".join(reasons))
        # A breaker that could not run did not clear — it stood aside, for
        # the same reason preflight does (see check_all). Carried to the
        # heartbeat so the note the operator reads says which of the two
        # kinds of "ok" this is.
        self._breakers_blind = "; ".join(breakers.blind)

        # The operator's own numbers from /setup/ — MAX DAILY LOSS and MAX
        # TOTAL EXPOSURE — measured across BOTH position books. Reported ahead
        # of the per-config limits below because it is the answer to "why is
        # nothing trading": a book-level halt stops every config at once, and
        # an operator staring at one bot's heartbeat should read the reason
        # that actually applies rather than that bot's own concurrency count.
        #
        # These are a SECOND ceiling, not a replacement for the per-config
        # ones underneath. `halt_on_drawdown` governs this config's own
        # drawdown limit and deliberately does not reach here — turning off one
        # bot's drawdown halt is not consent to trade through the book's.
        from portfolio.risk_gate import preflight
        book = preflight(self.user)
        if not book["ok"]:
            return (False, book["reason"])
        # preflight FAILS OPEN by design - halting a fleet on a
        # transient database hiccup is worse than one unenforced tick.
        # But its own docstring asks callers to read `failed_open`
        # rather than `ok` alone, precisely because `ok` True carries
        # two opposite meanings: the limits cleared, or nobody could
        # read them. Reading `ok` alone painted the most reassuring
        # heartbeat note this bot has exactly when the book limits
        # were binding nothing at all.
        self._book_gate_blind = (book.get("reason") or "book unreadable") \
            if book.get("failed_open") else ""

        # CLOSE_PENDING still holds capital/exposure at the broker.
        open_count = AssetBotTrade.objects.filter(
            config=self.cfg, status__in=("OPEN", "CLOSE_PENDING")).count()
        if open_count >= self.cfg.max_concurrent_positions:
            return (False,
                    f"max {self.cfg.max_concurrent_positions} concurrent positions reached")

        # 24h realized P&L vs daily-loss limit
        since = timezone.now() - timedelta(hours=24)
        closed = list(AssetBotTrade.objects.filter(
            config=self.cfg, status="CLOSED", closed_at__gte=since))
        # An exit reconciliation could not price carries pnl=None, and
        # summing it raised TypeError right here — in the daily-loss gate,
        # so one unpriceable close took the whole entry preflight down.
        # Summing it AS zero would be worse than the crash: a real stop-out
        # would read as a scratch against the one floor an operator trusts
        # to stop the day.
        #
        # The measured rows are summed; the unmeasured ones are named. The
        # limit still applies to what was measured — if that alone breaches,
        # the bot halts — and where it does not, the gate reports itself
        # blind rather than "ok", the same way an unreadable book does
        # thirty lines above.
        realized = sum((t.pnl for t in closed if t.pnl is not None),
                       Decimal(0))
        n_unmeasured = sum(1 for t in closed if t.pnl is None)
        self._pnl_gate_blind = (
            f"{n_unmeasured} of {len(closed)} closes in the last 24h could "
            f"not be priced; realized is at least {realized:.2f}"
        ) if n_unmeasured else ""
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
                    title__startswith="▲ Drawdown limit reached",
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
        # The POOL this config sizes from, against the account that funds
        # it. Every limit above is a percentage of `cfg.capital`, which is
        # a number typed into a form — so a pool declared larger than the
        # broker's equity makes all of them looser than they read, and the
        # heartbeat is where an operator looks when they wonder why.
        #
        # Cached for 15 minutes inside capital_truth, so this is not a
        # broker round trip per tick. Never gates: it says so and lets the
        # operator decide, which is the same posture as the other two
        # blind notes here.
        self._pool_note = ""
        try:
            from bot_program.capital_truth import broker_equity
            equity = broker_equity(self.user, self.cfg)
            declared = float(self.cfg.capital or 0)
            if equity and declared > 0:
                drift = abs(declared - equity) / equity * 100.0
                if drift > 5.0 and declared > equity:
                    self._pool_note = (
                        f"pool declares {declared:,.0f} against "
                        f"{equity:,.0f} at the broker, so every limit here "
                        f"is {declared / equity:.1f}x looser than it reads")
        except Exception as e:  # noqa: BLE001 — a note must never gate
            logger.debug("[%s_bot] pool check unavailable: %s",
                         self.asset_class, e)

        unchecked = [b for b in (getattr(self, "_breakers_blind", ""),
                                 getattr(self, "_book_gate_blind", ""),
                                 getattr(self, "_pnl_gate_blind", ""),
                                 getattr(self, "_pool_note", "")) if b]
        if unchecked:
            return (True, "ok (UNCHECKED: " + "; ".join(unchecked) + ")")
        return (True, "ok")

    # ── per-symbol scan ─────────────────────────────────────────────────

    def scan_symbol(self, symbol: str) -> Optional[dict]:
        from bot_program.models import AssetBotTrade
        from bot_program.engine.broker_router import client_for_symbol
        from bot_program.asset_engine import skips

        # Skip if a trade for this symbol is already open (or awaiting a
        # retried close — the broker position is still live) under this config.
        if AssetBotTrade.objects.filter(
                config=self.cfg, symbol=symbol,
                status__in=("OPEN", "CLOSE_PENDING")).exists():
            return self._skip(symbol, skips.ALREADY_OPEN,
                              "a position is already on")

        # Cooldown: skip if a CLOSED trade for this symbol was created within cool_down_minutes.
        cool = self.cfg.cool_down_minutes or 0
        if cool > 0:
            recent = AssetBotTrade.objects.filter(
                config=self.cfg, symbol=symbol, status="CLOSED",
                closed_at__gte=timezone.now() - timedelta(minutes=cool),
            ).exists()
            if recent:
                return self._skip(symbol, skips.COOLDOWN,
                                  f"closed a trade within {cool}m")

        decision = self.decide(symbol)
        if decision.direction == "HOLD":
            reason = (decision.reasons or [""])[0]
            code = (skips.STALE_SIGNALS if "stale" in reason
                    else skips.NO_SIGNALS if "no active signals" in reason
                    else skips.HOLD)
            return self._skip(symbol, code, reason)

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
                return self._skip(symbol, skips.GATE_BLOCKED, reason)
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
            return self._skip(symbol, skips.PAPER_FALLBACK,
                              "live config fell back to PaperTrader")

        try:
            tk = client.ticker(symbol)
        except Exception as e:
            logger.warning("[%s_bot] ticker(%s) failed: %s",
                           self.asset_class, symbol, e)
            return self._skip(symbol, skips.NO_PRICE, f"ticker failed: {e}")
        try:
            price = float(tk.get("lastPrice", "0") or 0)
        except (TypeError, ValueError):
            price = 0
        if price <= 0:
            return self._skip(symbol, skips.NO_PRICE, "ticker returned 0")

        # A paper entry used to be recorded at the raw ticker, because the
        # order block below sits inside `if not paper:` and PaperTrader is
        # therefore never reached. Charge the realistic fill here, before
        # levels and sizing, so the stop and the quantity are both relative
        # to the price actually obtained — which is how a real bracket is
        # placed.
        market_price = price
        paper_now = (self.cfg.mode == "paper")
        if paper_now:
            from bot_program.asset_engine.risk_levels import paper_fill_price
            price = paper_fill_price(self.cfg, symbol, price, decision.direction)

        # ── Levels FIRST, because the stop is an input to the size ───────
        # Volatility-normalised levels: a fixed 2% stop is a different bet on
        # every instrument and in every regime, and it makes realized_r
        # incomparable across the book. Falls back to the configured
        # percentages when no ATR is available, so this never returns None.
        from bot_program.asset_engine.risk_levels import (
            passes_cost_filter, stop_and_target,
        )
        sl, tp, level_meta = stop_and_target(
            self.cfg, symbol, price, decision.direction)

        # A planned move smaller than the round trip is negative-EV however
        # good the signal is.
        ok, cost_reason = passes_cost_filter(self.cfg, symbol, price, tp,
                                              stop=sl)
        if not ok:
            logger.info("[%s_bot] skipping %s — %s",
                        self.asset_class, symbol, cost_reason)
            return self._skip(symbol, skips.COST_FILTER, cost_reason)

        # ── What the promotion stage permits ─────────────────────────────
        # A stage is a venue, not a size. Applying it as a multiplier meant
        # `paper` mapped to 0.0 and a paper-stage rule could never take the
        # paper trade the ladder was asking for.
        stage = {"may_trade": True, "force_paper": False,
                 "live_size_factor": 1.0, "stage": "", "reason": ""}
        if decision.rule_name:
            from signals.rule_actuator import stage_policy
            stage = stage_policy(decision.rule_name)
            if not stage["may_trade"]:
                logger.info("[%s_bot] %s not traded: %s", self.asset_class,
                            symbol, stage["reason"])
                return self._skip(symbol, skips.STAGE_BLOCKED, stage["reason"])

        # ── Size by RISK, not by notional ────────────────────────────────
        sizing = self._size_for_entry(symbol, price, sl, decision)
        qty = sizing["qty"]
        sl = sizing["stop"]          # may have been widened; place THIS one

        # Admin and allocator lanes still scale the bet. The promotion lane
        # does not — it decided the venue above.
        if decision.rule_name:
            try:
                from signals.rule_actuator import admin_allocator_multiplier
                qty *= admin_allocator_multiplier(decision.rule_name)
            except Exception as e:
                logger.error("[%s_bot] sizing multiplier failed for %s: %s — "
                             "refusing to trade at unscaled size",
                             self.asset_class, symbol, e)
                return self._skip(symbol, skips.ERROR, f"sizing lane: {e}")
        if not stage["force_paper"]:
            qty *= float(stage["live_size_factor"])

        # CORRELATION SIZE TAPER — the book's max_correlation_threshold from
        # /setup/. It sits with the other multipliers because that is what it
        # is: a second position 0.9-correlated to one already on is most of
        # the same bet, and the honest response is to take less of it rather
        # than to pretend the first position is not there. Unmeasured
        # correlation returns 1.0 and says why; a size is never scaled on an
        # absent measurement.
        #
        # A failed read costs the taper, not the trade. It is a 90-day
        # correlation over PriceData — the most fragile input on this path —
        # and refusing an entry the rest of the platform has approved because
        # a price history is thin would be the taper acting as a gate, which
        # is exactly what it is not.
        try:
            from instruments.models import Instrument
            from portfolio.risk_gate import correlation_state
            corr = correlation_state(
                self.user, Instrument.objects.filter(symbol=symbol).first())
        except Exception as e:  # noqa: BLE001 — see above
            logger.warning("[%s_bot] correlation taper unavailable for %s: "
                           "%s — sizing untapered", self.asset_class, symbol, e)
            corr = {"scale": 1.0, "reason": ""}
        if corr["scale"] < 1.0:
            qty *= float(corr["scale"])
            logger.info("[%s_bot] %s correlation taper: %s",
                        self.asset_class, symbol, corr["reason"])

        qty = self._round_qty(qty, price)

        # THE CAP, ENFORCED WHERE THE FINAL QUANTITY EXISTS.
        # `risk_fraction()` clamps to MAX_RISK_FRACTION and its docstring
        # promised "no config value and no multiplier may exceed it". That
        # was false here: size_position returns a qty risking exactly the
        # capped fraction, and the allocator lane above then multiplies it
        # by anything the meta-allocator wrote in [0.10, 3.00]. Nothing
        # downstream re-checked risk. The hand-taken path, where a human is
        # present to object, refuses on the final quantity; this path, where
        # nobody is, did not.
        #
        # It is dormant only while every multiplier is <= 1.0, and they
        # exceed 1.0 the day rules start clearing the promotion gate — so
        # this lands BEFORE that, not after.
        #
        # REFUSE rather than clamp: a size the platform quietly shrank is a
        # different trade from the one the lane asked for, and the operator
        # should see that it wanted more than the ceiling allows.
        try:
            from bot_program.asset_engine.sizing import MAX_RISK_FRACTION
            risk_ceiling = float(self.cfg.capital or 0) * MAX_RISK_FRACTION
            per_unit_risk = abs(float(price) - float(sl))
            realised_risk = qty * per_unit_risk * self._value_per_unit(symbol)
        except Exception as e:  # noqa: BLE001 — see below
            # A cap that cannot be computed must not silently pass the
            # trade: this is arithmetic on values already in hand, so a
            # failure here means something is wrong enough to stop.
            logger.error("[%s_bot] %s: risk ceiling uncomputable (%s) — "
                         "refusing the entry", self.asset_class, symbol, e)
            return self._skip(symbol, skips.ERROR, f"risk ceiling: {e}")
        # The 1e-9 slack is for float noise at exactly the cap, not
        # tolerance — the same slack the manual path uses.
        if (risk_ceiling > 0 and per_unit_risk > 0
                and realised_risk > risk_ceiling + 1e-9):
            logger.warning(
                "[%s_bot] %s REFUSED: %.4f units risk $%.2f, past the $%.2f "
                "ceiling (%.1f%% of the pool)", self.asset_class, symbol,
                qty, realised_risk, risk_ceiling, MAX_RISK_FRACTION * 100)
            return self._skip(
                symbol, skips.GATE_BLOCKED,
                f"sized to ${realised_risk:,.2f} of risk, past the "
                f"${risk_ceiling:,.2f} ceiling "
                f"({MAX_RISK_FRACTION * 100:.1f}% of the bot pool) — the "
                f"allocator lane scaled past the cap")

        if qty <= 0:
            logger.info("[%s_bot] %s sized to zero (risk budget %.2f%% of "
                        "%s, stop %.3f%% away) — skipping", self.asset_class,
                        symbol, sizing["risk_fraction"] * 100, self.cfg.capital,
                        abs(price - sl) / price * 100 if price else 0)
            return self._skip(
                symbol, skips.SIZED_TO_ZERO,
                f"risk budget {sizing['risk_fraction'] * 100:.2f}% of "
                f"{self.cfg.capital} is below one tradeable unit")

        # MAX SINGLE POSITION from /setup/, judged on the size actually about
        # to be sent — after every multiplier and after rounding, because a
        # cap that bites on the pre-multiplier number is a cap on a quantity
        # nobody trades. A refusal rather than a clamp: silently shrinking to
        # the ceiling would change the risk this entry was sized for, and the
        # bot cannot ask the operator which of the two they meant.
        #
        # Left unguarded on purpose, unlike `preflight` above, which fails
        # open. An exception here reaches tick()'s handler and costs ONE
        # symbol one pass; preflight's would cost the whole fleet every pass,
        # and that difference in blast radius is the whole reason the two
        # gates answer a failed read differently.
        from portfolio.risk_gate import limits_book, single_position_state
            # The pool this position is sized FROM is the pool it must fit
            # inside. `AssetBotConfig.capital` is what `_size_position`
            # divided the risk budget by; the portfolio book is a separate
            # number no bot consults, so measuring against it refused every
            # entry on any account whose pool exceeds its recorded book.
        notional = qty * price * self._value_per_unit(symbol)
        cap = single_position_state(
            limits_book(), asset_class=self.asset_class,
            notional=notional,
            capital_base=float(self.cfg.capital or 0),
            base_label="bot pool")
        if not cap["ok"]:
            logger.info("[%s_bot] %s refused by the book's single-position "
                        "limit: %s", self.asset_class, symbol, cap["reason"])
            return self._skip(symbol, skips.GATE_BLOCKED, cap["reason"])

        # NOT a per-ticket total-exposure pre-check here, deliberately.
        #
        # `exposure_state` now accepts `adding=` so a caller can ask "would
        # THIS position put me over?" rather than only "am I already over?",
        # which closes a real gap: a book at 99,500 of a 100,000 ceiling
        # clears `preflight` in can_open_new, this scan opens at the
        # single-position cap, and the pass ends at 119.5% of a limit
        # nothing refused.
        #
        # But the denominator that gate uses is the BOOK's value, and the
        # comment on the cap above records what happens when a bot entry is
        # measured against it: sizing divides the risk budget by
        # `AssetBotConfig.capital`, so on any account whose pool exceeds its
        # recorded book value, a book-denominated ceiling refuses every
        # entry. That is why the single-position check passes
        # `capital_base=self.cfg.capital` with `base_label="bot pool"`.
        # Adding a book-denominated total here would reintroduce exactly
        # the bug that comment exists to prevent.
        #
        # The gap is real and the fix belongs where the book IS the right
        # denominator — the manual ticket path, where the operator's own
        # capital is what is being spent. Bounding a config's total against
        # its OWN pool is a different limit that does not exist yet, and
        # inventing one on a live money path is not tonight's change.

        # ONE EXPRESSION PER BET, and a leg cap per currency theme — the
        # two holes every money limit above walks past. EURGBP BUY under
        # bollinger_squeeze_breakout while manual_take already BUYs it is
        # 2x one idea wearing two tickets, each leg comfortably inside the
        # concentration and single-position ceilings; and six EUR crosses
        # were one ECB headline away from marking together while every
        # symbol-scoped gate stayed green. Hard refusals here because
        # nobody is present on a beat to weigh a duplicate on purpose.
        # Unguarded like the single-position cap above, for the same blast
        # radius: an exception costs this symbol this pass, not the fleet.
        from portfolio.risk_gate import duplicate_state, theme_state
        dup = duplicate_state(self.user, symbol=symbol,
                              side=decision.direction,
                              config_id=self.cfg.id)
        if not dup["ok"]:
            logger.info("[%s_bot] %s refused as a duplicate expression: %s",
                        self.asset_class, symbol, dup["reason"])
            return self._skip(symbol, skips.GATE_BLOCKED, dup["reason"])
        theme = theme_state(self.user, symbol=symbol,
                            side=decision.direction,
                            asset_class=self.asset_class)
        if not theme["ok"]:
            logger.info("[%s_bot] %s refused by the theme-leg cap: %s",
                        self.asset_class, symbol, theme["reason"])
            return self._skip(symbol, skips.GATE_BLOCKED, theme["reason"])

        # Shadow mode: everything is computed, nothing is submitted and no
        # row is written. The way to validate a change against live data
        # for 24-48h without risking money.
        from bot_program.asset_engine.safety import is_shadow, log_shadow_entry
        if is_shadow(self.cfg):
            log_shadow_entry(self.cfg, symbol, decision, price, qty)
            return self._skip(symbol, skips.SHADOW,
                              "shadow mode — computed, not submitted")

        # A paper-STAGE rule trades on the paper venue even in a live config:
        # that is the whole point of the stage, and it is how the evidence to
        # promote it gets produced.
        paper = (self.cfg.mode == "paper") or bool(stage["force_paper"])
        order_id = ""
        entry_meta = dict(level_meta)
        entry_meta["cost_check"] = cost_reason
        # Frozen at entry so a trailing stop cannot rewrite the risk
        # denominator that realized_r (and therefore sizing) depends on. This
        # is the POST-floor stop — the one actually placed.
        entry_meta["initial_stop_loss"] = round(float(sl), 8)
        if paper or paper_now:
            from bot_program.asset_engine.risk_levels import (
                round_trip_cost_fraction,
            )
            entry_meta["paper_fill"] = True
            entry_meta["market_price"] = round(float(market_price), 8)
            entry_meta["cost_applied_fraction"] = round(
                round_trip_cost_fraction(self.cfg, symbol) / 2.0, 8)
        entry_meta["risk_fraction"] = sizing["risk_fraction"]
        entry_meta["risk_dollars"] = sizing["risk_dollars"]
        entry_meta["notional_fraction"] = sizing["notional_fraction"]
        # The entry-time account-currency value of one price point per unit
        # (the quote->USD rate for forex, 1.0 for USD-quoted classes).
        # forex_usd_multiplier reads this on every close path and in
        # grading, so P&L and the R denominator convert by the same number.
        entry_meta["value_per_unit"] = sizing.get("value_per_unit", 1.0)
        if sizing["stop_widened"]:
            entry_meta["stop_widened"] = True
        if stage.get("stage"):
            entry_meta["promotion_stage"] = stage["stage"]
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
            if not self._still_armed():
                return self._skip(symbol, skips.GATE_BLOCKED,
                                  "config was disarmed mid-tick — refusing "
                                  "to submit")
            try:
                # The LAST read before real units move. can_open_new ran
                # before this symbol's scan; a disarm landing between then
                # and now would otherwise still reach the broker, and what
                # it opened would go unmanaged — the runner refuses a
                # disabled config, so no later tick trails or time-stops it.
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
                # Detect broker-side refusals: log + skip trade row.
                # CANCELLED/INACTIVE/EXPIRED belong here too — brokers
                # whose raw vocabulary never says "REJECTED" (IBKR) used
                # to sail past this check and book a phantom live row.
                status = (res.get("status") or "").upper()
                # ...but only when NOTHING printed. The close path in
                # this same file has always got this right
                # (CLOSE_REFUSED_STATUSES is honoured only when
                # `filled <= 0`); the entry path did not. A broker that
                # fills part of an order and then cancels the remainder
                # has still put real units in the account, and IBKR
                # reaches exactly that state because
                # `_dead_order_reason` deliberately returns None once
                # anything is filled. Treating it as a refusal meant
                # logging a DEDUP warning and creating NO ROW AT ALL -
                # live units at the broker that no part of this
                # platform knows about, and that reconciliation cannot
                # find, because reconciliation walks rows.
                try:
                    refused_qty = float(res.get("executedQty") or 0)
                except (TypeError, ValueError):
                    refused_qty = 0.0
                if status in ("REJECTED", "DUPLICATE", "CANCELLED",
                              "CANCELED", "INACTIVE", "EXPIRED") \
                        and refused_qty <= 0:
                    logger.warning("[%s_bot] live order DEDUP for %s "
                                    "(status=%s, client_order_id=%s)",
                                    self.asset_class, symbol, status,
                                    client_order_id)
                    return self._skip(symbol, skips.ORDER_REJECTED,
                                      f"broker status {status}")

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
                    # Venues where protection rides the TRADE rather than
                    # standalone orders (OANDA) report the trade instead.
                    # It is the handle for moving the stop later, and it
                    # is offered exactly once — in the fill.
                    trade_handle = res.get("protectiveTradeId")
                    if trade_handle:
                        entry_meta["protective_trade_id"] = str(trade_handle)
                    # Venues that name their legs (Alpaca) say which one is
                    # the stop. Recorded so the stop rules move THAT one
                    # rather than walking a flat list and taking whichever
                    # answers first — which on a long bracket is the target.
                    target_leg = res.get("protectiveTargetId")
                    if target_leg:
                        entry_meta["protective_target_id"] = str(target_leg)
                    stop_leg = res.get("protectiveStopId")
                    if stop_leg:
                        entry_meta["protective_stop_id"] = str(stop_leg)
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
                trade_id=trade.id,
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

        skips.clear(self.cfg, symbol)
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
            title = f"✕ Live bot blocked: {self.cfg.name}"
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
        """LEGACY notional sizing. Kept only for callers outside the entry
        path (backtests, the admin preview) — `_size_for_entry` is what sizes
        a real trade, because this cannot see the stop and therefore cannot
        control risk. See asset_engine/sizing.py for why that matters."""
        cap = float(self.cfg.capital)
        dollars = cap * (self.cfg.position_size_pct / 100.0)
        if price <= 0:
            return 0.0
        return round(dollars / price, 6)

    # ── risk-denominated sizing ──────────────────────────────────────────

    def _value_per_unit(self, symbol: str) -> float:
        """Account-currency loss per point of price, per unit held.

        1.0 for anything quoted directly in the account currency; ForexBot is
        the one override, converting the quote currency. OptionsBot is not:
        its entry and stop are premium-per-share while its P&L is premium x
        shares, but the multiplier that bridges the two belongs to the
        CONTRACT and cannot be answered from a symbol, so its own scan_symbol
        passes `contract.multiplier` into sizing directly.
        """
        return 1.0

    def _size_for_entry(self, symbol: str, price: float, stop: float,
                        decision) -> dict:
        """Units to buy so that a stop-out costs a fixed fraction of equity."""
        from bot_program.asset_engine.sizing import size_position
        return size_position(
            self.cfg, asset_class=self.asset_class, entry=price, stop=stop,
            direction=decision.direction,
            value_per_unit=self._value_per_unit(symbol),
        )

    def _round_qty(self, qty: float, price: float) -> float:
        """Snap a size to what the venue will actually accept.

        Applied LAST, after every multiplier, so rounding never silently
        rescales the risk budget by more than one tick of granularity.
        """
        return round(float(qty), 6)

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

        # Age bound. `is_active` is cleared by the lifecycle pass, which
        # needs a fresh quote to evaluate an outcome — so a signal on an
        # instrument that stops being quoted stays active forever and votes
        # forever. Five fabricated sv_sample_* rows from April are still
        # active in the dev database at scores of 0.68-0.92, comfortably
        # above the 0.60 default threshold: without this the first trade any
        # new config takes is against months-old invented data, re-entered
        # every cooldown for as long as the bot runs.
        max_age_hours = self._extras_float("max_signal_age_hours", 24.0)
        qs = Signal.objects.filter(instrument=inst, is_active=True)
        if max_age_hours > 0:
            cutoff = timezone.now() - timedelta(hours=max_age_hours)
            qs = qs.filter(created_at__gte=cutoff)
        # Pulled wider than the 8-vote consensus window because the stage
        # filter below must run BEFORE that cap: research forks tie their
        # parent's hardcoded score, and letting them occupy top-8 slots
        # they cannot vote from would silently crowd tradeable signals out
        # of the consensus. Per-rule dedupe keeps the real row count near
        # the rule count; 32 merely bounds pathological data.
        candidates = list(qs.order_by("-score")[:32])
        if not candidates:
            stale = Signal.objects.filter(instrument=inst, is_active=True).count()
            if stale:
                return BotDecision("HOLD", 0, [
                    f"{stale} active signal(s) but none within "
                    f"{max_age_hours:.0f}h — stale"])
            return BotDecision("HOLD", 0, ["no active signals"])

        # Research-stage rules are watched, not traded — and that has to
        # include their VOTES. An applied evolution fork is the same
        # detector as its parent with different constants; letting its
        # research-stage signals count toward min_signals_for_entry (or
        # stack net weight) manufactures "independent" confirmations for
        # the parent's live orders. The stage gate below only inspects the
        # single winning rule_name, so the filter must happen here, before
        # the consensus ever sees the row.
        may_vote: dict = {}
        for s in candidates:
            rn = s.rule_name or ""
            if rn and rn not in may_vote:
                try:
                    from signals.rule_actuator import stage_policy
                    may_vote[rn] = bool(stage_policy(rn)["may_trade"])
                except Exception:
                    may_vote[rn] = True
        active = [s for s in candidates
                  if may_vote.get(s.rule_name or "", True)][:8]
        if not active:
            return BotDecision("HOLD", 0, [
                "only research-stage signals — watched, not traded"])

        bullish = [s for s in active if s.direction == "bullish"
                   and s.score >= self.cfg.entry_score_min]
        bearish = [s for s in active if s.direction == "bearish"
                   and s.score >= self.cfg.entry_score_min]

        # Evidence-weighted path (opt-out): weigh each rule's vote by its own
        # measured expectancy instead of counting heads, and net the two
        # sides so one stale counter-signal can't veto a strong setup.
        extras = getattr(self.cfg, "extras", None) or {}
        if extras.get("use_weighted_consensus", True):
            from bot_program.asset_engine.aggregation import weighted_consensus
            from bot_program.bot_grading import VENUE_LIVE, VENUE_PAPER
            # Default threshold mirrors what the headcount rule demanded
            # (min_signals_for_entry × entry_score_min), so weighting is a
            # strict generalisation of the config rather than a new bar.
            default_threshold = (self.cfg.min_signals_for_entry
                                 * self.cfg.entry_score_min)
            # The venue this config trades on: `mode` is what `_enter` writes
            # into `paper` on the resulting AssetBotTrade, so it is the venue
            # the ledger will file this entry under and therefore the venue
            # whose closes may vouch for the rule. It has to be passed —
            # `rule_weight` SKIPS the bot-trade lane entirely when the venue is
            # unstated, so omitting it here left weighted consensus running on
            # signal evidence alone, including on the paper-only and live-only
            # configs where the bot-trade lane was always right.
            # A paper-stage rule can still be forced onto the paper venue
            # after the vote, so a live config's entry occasionally lands on
            # paper having been weighed with live evidence. That error only
            # runs one way — toward the venue where the rule's record is
            # empty and its weight neutral — and under-using evidence is the
            # side to be wrong on when the other side spends money.
            venue = VENUE_PAPER if self.cfg.mode == "paper" else VENUE_LIVE
            # The ICT lane joins the vote here and only here. The headcount
            # path below counts heads, and a fractional vote has no meaning in
            # a headcount — it would either be a whole confirmation it has not
            # earned or nothing at all.
            bullish, bearish = self._with_smc_vote(symbol, bullish, bearish)
            verdict = weighted_consensus(
                bullish, bearish, asset_class=self.asset_class,
                min_net_weight=float(
                    extras.get("min_net_weight", default_threshold)),
                min_signals=self.cfg.min_signals_for_entry,
                venue=venue)
            if verdict["direction"] == "HOLD":
                return BotDecision("HOLD", 0, [verdict["detail"]])
            side = bullish if verdict["direction"] == "BUY" else bearish
            return BotDecision(
                verdict["direction"],
                self._conviction_score(verdict, side, venue=venue),
                reasons=([verdict["detail"]]
                          + [f"{s.rule_name}: {s.title}" for s in side[:3]]),
                rule_name=verdict["rule_name"] or "asset_bot_weighted_consensus",
            )

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

    # ── the ICT/SMC lane's vote ──────────────────────────────────────────

    def _with_smc_vote(self, symbol: str, bullish: list, bearish: list):
        """Return (bullish, bearish) with the SMC composite added as one vote.

        `signals.bot_bridge.smc_score_for_symbol` returns a directional score
        in [-1, +1], weighted by each setup's own measured hit rate. Its only
        consumer until now was `bot_program/engine/strategy.py`, on the legacy
        crypto path that no beat runs — so the ICT setups have produced
        evidence for months without a single one of them ever reaching a
        position. This is the wire.

        Two rules keep an unproven lane from behaving like a proven one:

          size    The vote enters at SMC_VOTE_WEIGHT x its conviction, which
                  caps it at the weight this platform gives a rule it has
                  measured as its worst. See that constant for the arithmetic.

          quorum  It is added ONLY to a side that already carries
                  `min_signals_for_entry` distinct rule votes. So it can
                  neither satisfy the headcount nor be the lone voter on a
                  winning side: it confirms a case other rules already made,
                  and when it points somewhere nobody else does it is dropped
                  rather than allowed to veto. An unproven lane that could
                  block trades would be exactly as unearned as one that could
                  open them, and this way the asymmetry runs the safe way —
                  the lane's first live positions are ones the rest of the
                  book already wanted.

          score   It gets no seat in the conviction recorded on the trade.
                  A vote capped below every rule it joins can only drag an
                  average of them, so confirming a setup would have made the
                  setup look weaker. See `_conviction_score`.

        A broken bridge degrades to no vote, loudly. `smc_score_for_symbol`
        RAISES on a missing `get_hit_rate` on purpose — a lane that cannot
        weight its own evidence is broken, not degrading — but letting that
        propagate here would take every entry decision on the platform down
        with one lane. The ERROR line with the traceback is what keeps it from
        being the silent zero it spent its life as.
        """
        try:
            from signals.bot_bridge import smc_score_for_symbol
            score, _reasons = smc_score_for_symbol(symbol)
        except Exception as e:  # noqa: BLE001 — see the docstring
            logger.error("[%s_bot] SMC lane unavailable for %s: %s — voting "
                         "without it", self.asset_class, symbol, e,
                         exc_info=True)
            return bullish, bearish

        score = float(score or 0.0)
        if score == 0.0:
            # No recent SMC cards, or they cancelled out. Both are "this lane
            # has nothing to say", which is not a vote for HOLD.
            return bullish, bearish

        side = bullish if score > 0 else bearish
        quorum = max(1, int(self.cfg.min_signals_for_entry or 1))
        if len({getattr(s, "rule_name", "") for s in side}) < quorum:
            logger.debug("[%s_bot] SMC %+.2f on %s dropped — that side has "
                         "fewer than %d rule votes of its own",
                         self.asset_class, score, symbol, quorum)
            return bullish, bearish

        vote = SmcVote(
            score=round(abs(score) * SMC_VOTE_WEIGHT, 4),
            title=(f"ICT/SMC composite {score:+.2f} "
                   f"(entering at {SMC_VOTE_WEIGHT:.2f} weight — this lane "
                   f"has no closed trades yet)"),
        )
        if score > 0:
            return bullish + [vote], bearish
        return bullish, bearish + [vote]

    def _conviction_score(self, verdict: dict, side: list, *,
                          venue: str) -> float:
        """The winning side's conviction, with the SMC seat taken back out.

        `weighted_consensus` scores a side as its total evidence divided by
        the number of votes in it, so every member pulls that average toward
        its own contribution. The SMC vote's is capped at SMC_VOTE_WEIGHT
        while every real vote beside it had to clear `entry_score_min` first,
        which puts the lane structurally BELOW the average of the rules it is
        there to confirm — arming it wrote a WORSE composite_score onto
        exactly the entries it agreed with. A confirmation that makes the
        ledger read an entry as less convinced is not a confirmation.

        So: the vote keeps its seat in the NET weight, which is the gate it
        exists to tip and the only place a quarter-weight opinion belongs, and
        gives up its seat in the average. The number recorded on the trade is
        then the one the real rules earned — identical to what it would have
        been with the lane switched off, in either direction.

        The re-weigh asks the same function the same question with the gate
        opened rather than re-deriving its arithmetic here, where the two
        would drift apart. It costs one more pass over the evidence, and only
        on an entry the lane actually joined.
        """
        # By identity, not by rule name. The name is a real one — the signal
        # engine loads an SMC composite rule of its own — and a Signal row
        # that happened to carry it is a genuine vote that has earned its seat
        # here. Only the object this file built is the one being taken out.
        real = [s for s in side if not isinstance(s, SmcVote)]
        if not real or len(real) == len(side):
            return verdict["score"]

        from bot_program.asset_engine.aggregation import weighted_consensus
        # The winning side alone, against an opened gate. Nothing is being
        # decided a second time here — the direction is already settled — so
        # the empty opposing side and the 0.0 bar are simply how that function
        # is asked for a side's average and answers with a number instead of
        # a HOLD.
        buy = verdict["direction"] == "BUY"
        rules_only = weighted_consensus(
            real if buy else [], [] if buy else real,
            asset_class=self.asset_class, min_net_weight=0.0, min_signals=1,
            venue=venue)
        return rules_only["score"]

    # ── Phase-17: optional bot-trade track-record feedback ──────────────

    def _apply_track_record(self, raw_score: float, rule_name: str) -> float:
        """If the config opts in via extras['use_bot_track_record']=True,
        multiply the consensus score by the rule's bot-trade confidence
        multiplier on this asset class AND on the venue this config trades.
        Returns the (possibly unchanged) score, capped at 1.0 so
        high-confidence rules don't exceed 100%.

        This is the headcount path's half of the venue split — reached when a
        config sets use_weighted_consensus False and use_bot_track_record
        True. It asked for the pooled record, so paper fills went on scaling a
        live config's entry score here long after the weighted path stopped
        letting them.
        """
        extras = getattr(self.cfg, "extras", None) or {}
        if not extras.get("use_bot_track_record"):
            return raw_score
        if not rule_name:
            return raw_score
        try:
            from bot_program.bot_grading import (
                VENUE_LIVE, VENUE_PAPER, bot_trade_track_record,
            )
            # Same rule as the weighted path: the venue follows the config's
            # mode, because that is what decides `paper` on the row this
            # decision will write.
            venue = VENUE_PAPER if self.cfg.mode == "paper" else VENUE_LIVE
            mult = bot_trade_track_record(rule_name, self.asset_class,
                                          venue=venue)
        except Exception as e:
            # Unscaled is the safe direction — the multiplier only ever
            # shrinks or grows a score that already cleared the entry bar —
            # but a ledger that cannot answer is worth a line, or the feedback
            # loop can be dead for weeks without anyone noticing.
            logger.warning("[%s_bot] track record lookup failed for %s: %s — "
                           "scoring unweighted", self.asset_class, rule_name, e)
            return raw_score
        return min(1.0, raw_score * mult)


# ── Factory ─────────────────────────────────────────────────────────────────

def make_bot(config) -> AssetBot:
    """Return the right subclass for `config.asset_class`."""
    from .stock_bot import StockBot
    from .forex_bot import ForexBot
    from .commodity_bot import CommodityBot
    from .options_bot import OptionsBot
    from .crypto_bot import CryptoBot

    cls_map = {
        "stock": StockBot,
        "forex": ForexBot,
        "commodity": CommodityBot,
        "options": OptionsBot,
        "crypto": CryptoBot,
    }
    cls = cls_map.get(config.asset_class)
    if cls is None:
        # `cfd` is selectable in the admin form and has no implementation, so
        # a CFD config raises here on every tick. Name the gap rather than
        # letting the runner swallow a bare ValueError.
        raise ValueError(
            f"No AssetBot implementation for asset_class={config.asset_class!r}. "
            f"Implemented: {', '.join(sorted(cls_map))}")
    return cls(config)
