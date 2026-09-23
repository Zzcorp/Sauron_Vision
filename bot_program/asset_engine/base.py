"""AssetBot — base class for all asset-class-specific bots.

Common loop (tick):
  1. manage_positions — for every OPEN trade, check current price vs SL/TP, close if hit.
  2. can_open_new — gate: max concurrent + daily loss limit.
  3. scan_for_entries — for each symbol in cfg.symbols, decide() and open if BUY/SELL.
     scan_symbol = execute_entry(propose_entry(symbol)): the proposal is
     every gate and the bot's own size (an EntryCandidate), the execution is
     the shadow branch, the order and the row. The capital desk ranks a
     fleet's candidates between the two.

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


def is_entry_working(trade) -> bool:
    """True when this row is an ORDER at the broker, not yet a position.

    Every consumer that treats an OPEN row as exposure has to ask: a
    working entry has no position to reconcile against, none to flatten,
    and no mark to book. Reconciliation in particular MUST skip these —
    it walks OPEN rows, finds no position at the broker, and closes them
    as orphans while cancelling their protective legs, which is precisely
    how an unfilled parent goes on to fill naked.
    """
    return bool((getattr(trade, "metadata", None) or {}).get("entry_working"))


def cancel_working_entry(trade, client, *, reason: str,
                         cancel_parent: bool = True) -> bool:
    """Withdraw an unfilled entry and mark the row CANCELED. Nothing traded.

    Returns False and leaves the row WORKING when the withdrawal cannot be
    confirmed: an order we could not cancel may still fill, and a CANCELED
    row over a live order is the same lie as a CLOSED row over a live
    position. `cancel_parent=False` is for a broker that has already
    reported the order dead.
    """
    from bot_program.models import AssetBotTrade   # noqa: F401 — doc of type

    meta = dict(trade.metadata or {})
    if cancel_parent and not trade.broker_order_id:
        # NO ID, NO WITHDRAWAL. Falling through here would cancel the
        # protective legs and stamp the row CANCELED — "nothing traded" —
        # over a parent that is still queued at the broker and about to
        # fill NAKED, into a row nothing walks any more. The row stays
        # WORKING instead, which every caller already reports honestly
        # ("it may still fill — cancel it at the broker").
        logger.error("[entry] %s: asked to withdraw a working entry with no "
                     "broker order id — the parent can neither be cancelled "
                     "nor read, so the row stays WORKING; cancel it at the "
                     "broker", trade.symbol)
        try:
            from bot_program.notifications import notify_staff
            notify_staff(
                title=f"⚠ {trade.symbol}: queued order cannot be withdrawn",
                body=(f"Trade #{trade.id} is a WORKING entry with no broker "
                      f"order id, so the platform cannot cancel it or read "
                      f"its state. It may still fill. Cancel it at the "
                      f"broker. ({reason})"),
                url="/positions/")
        except Exception as e:  # noqa: BLE001
            logger.warning("[entry] no-order-id alert failed: %s", e)
        return False
    if cancel_parent and trade.broker_order_id:
        cancel = getattr(client, "cancel_order", None)
        if not callable(cancel):
            logger.error("[entry] %s: cannot withdraw working order %s — this "
                         "broker client has no cancel_order; the row stays "
                         "WORKING", trade.symbol, trade.broker_order_id)
            return False
        try:
            sent = cancel(trade.broker_order_id)
        except Exception as e:  # noqa: BLE001
            logger.error("[entry] %s: withdrawing working order %s failed "
                         "(%s) — the row stays WORKING; it may still fill",
                         trade.symbol, trade.broker_order_id, e)
            return False
        if sent is False:
            # The broker could not find the order to cancel. That is not
            # proof it is gone: an order is visible only to the clientId
            # that placed it, so this is equally "the wrong session asked".
            logger.error("[entry] %s: the broker did not confirm cancelling "
                         "order %s (it may be filled, or placed on another "
                         "session) — the row stays WORKING",
                         trade.symbol, trade.broker_order_id)
            return False
        # PROVE it is dead. This row is about to record that nothing was
        # traded, so nothing short of the broker saying the order is dead
        # will do: an unreadable socket, an exception, an id the session
        # cannot see, all mean "we do not know", and marking a live
        # full-size market order CANCELED is the same lie as marking a
        # live position CLOSED.
        status_fn = getattr(client, "order_status", None)
        if not callable(status_fn):
            logger.error("[entry] %s: no way to confirm order %s is dead — "
                         "the row stays WORKING", trade.symbol,
                         trade.broker_order_id)
            return False
        try:
            st = status_fn(trade.broker_order_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("[entry] %s: post-cancel read failed (%s) — the "
                           "row stays WORKING", trade.symbol, e)
            return False
        if st is None:
            logger.error("[entry] %s: the broker could not be read after the "
                         "cancel — the row stays WORKING rather than claiming "
                         "an order nobody confirmed dead", trade.symbol)
            return False
        state = str(st.get("state") or "")
        if float(st.get("filled") or 0) > 0:
            logger.error("[entry] %s: order %s filled while being withdrawn "
                         "— leaving the row WORKING for the next poll to "
                         "book", trade.symbol, trade.broker_order_id)
            return False
        if state != "dead":
            logger.error("[entry] %s: order %s reads %r after the cancel, not "
                         "dead — the row stays WORKING",
                         trade.symbol, trade.broker_order_id,
                         state or "unknown")
            return False

    # The children go too. TWS cancels a bracket's children with its
    # parent, but a leg that outlives it is a resting order against a
    # position that never opened — and since these legs became GTC it
    # rests for days rather than dying at the session close.
    cancel = getattr(client, "cancel_order", None)
    leaked = []
    for oid in (meta.get("protective_order_ids") or []):
        try:
            if callable(cancel) and cancel(str(oid)):
                continue
        except Exception as e:  # noqa: BLE001
            logger.warning("[entry] %s: leg %s may still rest at the broker "
                           "(%s)", trade.symbol, oid, e)
        leaked.append(str(oid))
    if leaked:
        # The row is still marked CANCELED below — nothing traded, which is
        # true — but the leak is recorded and said out loud, because a
        # resting exit against a flat book OPENS a position when it fires.
        meta["protective_legs_unconfirmed"] = True
        logger.error("[entry] %s: leg(s) %s were NOT confirmed cancelled and "
                     "are GTC — cancel them at the broker; a resting exit "
                     "against a flat book opens a position",
                     trade.symbol, ", ".join(leaked))
        try:
            from bot_program.notifications import notify_staff
            notify_staff(
                title=f"⚠ {trade.symbol}: protective leg may still rest",
                body=(f"The entry order was withdrawn ({reason}) but leg(s) "
                      f"{', '.join(leaked)} were not confirmed cancelled. "
                      f"They are good-till-cancelled: if one fires against a "
                      f"flat book it OPENS a position. Cancel them at the "
                      f"broker."),
                url="/positions/")
        except Exception as e:  # noqa: BLE001
            logger.warning("[entry] leaked-leg alert failed: %s", e)

    meta.pop("entry_working", None)
    meta["entry_withdrawn_at"] = timezone.now().isoformat()
    meta["entry_withdrawn_reason"] = reason
    trade.metadata = meta
    trade.status = "CANCELED"
    trade.closed_at = timezone.now()
    trade.reason = (f"{trade.reason}\nentry withdrawn: {reason}").strip()[:1000]
    # pnl stays 0 and outcome stays blank ON PURPOSE: nothing traded, so
    # there is nothing to grade. A CANCELED row is not a scratch trade.
    trade.save(update_fields=["metadata", "status", "closed_at", "reason"])
    logger.warning("[entry] %s: working entry withdrawn (%s) — nothing traded",
                   trade.symbol, reason)
    return True


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

    # Whether the capital desk may run this lane as propose_entry /
    # execute_entry. OptionsBot overrides scan_symbol wholesale and sets
    # this False (2026-09-12); the desk runs such a lane through
    # scan_symbol as before and files its entries 'not_desked'.
    DESKED = True

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
        # Broker snapshots (resting orders, positions) read once per tick
        # and shared across every protected row on the same client.
        self._tick_broker_cache = {}
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
                    # AND SAY SO. Refusing to manage is correct; doing it
                    # silently is not. This branch used to be a log line and
                    # nothing else, so a real position whose manager had been
                    # switched off left no trace anywhere the operator looks.
                    from bot_program.engine.broker_router import session_busy
                    self._notify_unmanaged_live_position(
                        trade, busy=session_busy(client))
                    continue

                # A WORKING entry is an order, not a position: nothing to
                # mark, stop or time out yet. Ask the broker where it stands.
                if (trade.metadata or {}).get("entry_working"):
                    self._poll_working_entry(trade, client)
                    continue

                # THE MARK IS READ HERE, FIRST, exactly as before — only
                # the GATE below it moved, past the two checks that never look
                # at a price. Nothing between this line and the gate is
                # reordered, so a position the broker CAN price runs the same
                # calls in the same order and ends the tick in the same state.
                #
                # And the read is not allowed to be fatal: a ticker that
                # RAISES (a dead session, a 429) used to land in this loop's
                # own handler and skip the position whole — killing the clock
                # exit for the very reason it exists. An unreadable mark is
                # None, which is what everything below is written for.
                try:
                    price = self._mark_price(trade, client)
                except Exception as e:  # noqa: BLE001 — unreadable is None
                    logger.warning("[%s_bot] %s: the mark could not be read "
                                   "(%s: %s) — the clock exit still runs",
                                   self.asset_class, trade.symbol,
                                   type(e).__name__, e)
                    price = None

                # The time stop runs for protected trades too — AND FOR
                # UNPRICED ONES, which is the point of this ordering. It is
                # the one exit the broker knows nothing about: a bracket holds
                # SL and TP, but nothing at the broker releases capital from a
                # thesis that simply never moved. It compares CLOCKS, not
                # prices — _time_stop_hit reads opened_at against the config's
                # ceiling and never touches a mark — so behind the mark gate
                # it could never fire on a Saxo CFD, whose SIM quote is 0
                # (NoAccess on a demo not linked to a funded live account).
                # Those positions were held for ever, in silence.
                #
                # NOT a claim that the close is seamless: _close_trade strips
                # the resting bracket and then goes to market, and between
                # those two the position is live with no stop at the broker.
                # That window is the close path's, it is stated where it
                # happens, and it is the same window every other exit takes.
                if self._time_stop_hit(trade):
                    # The close needs no mark: _submit_close_order sends a
                    # MARKET order (symbol, side, qty — no price), and
                    # _close_trade books the exit off the broker's OWN fill,
                    # falling back to what we pass only when the broker
                    # reports none. So this is a FALLBACK, never the order.
                    exit_basis = price
                    if exit_basis is None or exit_basis <= 0:
                        # UNMEASURED IS NOT ZERO, AND NOT A GUESS EITHER. A
                        # live row passes None on purpose: resolve_exit_fill
                        # owns that case already — it books the ENTRY price
                        # and says so, which realises exactly 0 rather than a
                        # number nobody quoted. Inventing a mark here would
                        # collapse "could not be priced" into "priced".
                        exit_basis = None
                        if trade.paper:
                            # Except on paper, where the modelled fill does
                            # float(price) and float(None) raises TypeError
                            # out of _close_trade — the row would stay OPEN
                            # for ever, which is this bug re-entering by the
                            # paper door. The entry price is the row's own
                            # real number, and it is already what the options
                            # expiry close falls back to.
                            exit_basis = trade.entry_price
                        # AND THE LEDGER RECORDS THE DECISION, not the fill:
                        # the clock fired with no live mark, which stays true
                        # for ever even if the broker reports a fill a second
                        # later. Three states, read beside exit_fill_source:
                        # the key absent means the exit had a live mark;
                        # present with source "broker" means the fill was
                        # measured anyway; present with source "mark" means
                        # the entry price stood in and the P&L is an
                        # accounting placeholder, not a measured round trip.
                        # Saved BEFORE the close, because a failed close
                        # saves only its own fields and would drop this.
                        meta = dict(trade.metadata or {})
                        meta["time_stop_unpriced"] = True
                        trade.metadata = meta
                        trade.save(update_fields=["metadata"])
                        logger.warning(
                            "[%s_bot] %s: the clock exit fires with NO usable "
                            "mark — the exit books at the broker's own fill, "
                            "or at the entry price if it reports none, and "
                            "the row carries metadata.time_stop_unpriced so "
                            "that 0 is not read as a measured round trip",
                            self.asset_class, trade.symbol)
                    if self._close_trade(trade, exit_basis, client,
                                         reason="TIME"):
                        closed += 1
                    continue

                # Warned only when the ceiling has NOT been reached. A bot
                # that was stopped for a week comes back to positions already
                # past their ceiling, and "this will close soon" arriving in
                # the same tick as "this closed" is noise, not a warning.
                # Above the gate for the same reason as the stop itself:
                # _time_stop_status takes no client and no price, and the
                # warning an operator most needs is the one about a position
                # nobody can price.
                ts = self._time_stop_status(trade)
                if ts["approaching"]:
                    self._warn_time_stop_near(trade, ts)

                # NOW THE GATE. Everything from here down compares AGAINST a
                # price: the vanished-stop net acts only to hand the position
                # to bot-side SL/TP, break-even and trailing measure the move
                # in R, and the SL/TP tests are literally price <= stop_loss.
                # None of it can run on a mark that does not exist — and the
                # net in particular must NOT run here, because its action is
                # to cancel the last resting exit and hand the row to a
                # bot-side stop that cannot compare anything either.
                if price is None or price <= 0:
                    logger.warning("[%s_bot] %s: no usable mark from the "
                                   "broker — the clock exit ran, but NOTHING "
                                   "price-based is managed on this position "
                                   "this tick (no vanished-stop net, no stop "
                                   "move, no bot-side SL/TP)",
                                   self.asset_class, trade.symbol)
                    try:
                        # IMPORTED HERE. `skips` is not a module-level name in
                        # this file — every other user imports it locally — so
                        # the call added on 2026-09-20 raised NameError into
                        # the bare except below and the ledger recorded
                        # nothing: loud in the log, silent on the page.
                        from bot_program.asset_engine import skips as _skips
                        _skips.record(self.cfg, trade.symbol, _skips.NO_PRICE,
                                      "open position only clock-managed: the "
                                      "broker priced it at 0")
                    except Exception as e:  # noqa: BLE001
                        logger.warning("[%s_bot] could not record the "
                                       "unpriced skip for %s: %s",
                                       self.asset_class, trade.symbol, e)
                    continue

                # `protected` is a claim about the BROKER, and the broker is
                # asked whether it still holds. A stop leg that expired,
                # was cancelled at TWS, or was never accepted leaves the row
                # saying protected while nothing rests — and protected rows
                # skip every check below. When the leg is gone and the
                # position is still held, the row is un-protected here and
                # bot-side management takes the position back this tick.
                if protected and not trade.paper and \
                        self._protection_vanished(trade, client):
                    protected = False

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

    # How long a WORKING entry may stay unfilled before the bot withdraws
    # it. IBKR queues a market order sent outside regular hours for the
    # next open, so one overnight is normal; an order still working after
    # a full session is a halted symbol, a dead route, or a book that
    # never opened — none of which the thesis that placed it foresaw.
    ENTRY_WORKING_MAX_HOURS = 26

    def _working_entry_age_hours(self, trade) -> float:
        since = (trade.metadata or {}).get("entry_working_since")
        try:
            from datetime import datetime as _dt
            started = _dt.fromisoformat(since) if since else trade.opened_at
        except (TypeError, ValueError):
            started = trade.opened_at
        if started is None:
            return 0.0
        return (timezone.now() - started).total_seconds() / 3600.0

    #: How long a symbol whose order MAY be live is left alone. Long
    #: enough for a human to look, short enough that the bot is not
    #: silently retired by one network blip. The alert says the number.
    IN_DOUBT_QUIET_HOURS = 12

    def _remember_in_doubt(self, symbol: str, reference: str) -> None:
        """Note on the config that `symbol` has an order nobody can account
        for. Read by propose_entry, which refuses the symbol while it is
        fresh — because the idempotency key buckets by the minute, so the
        next tick would send a SECOND order under a new reference."""
        try:
            extras = dict(self.cfg.extras or {})
            book = dict(extras.get("entry_in_doubt") or {})
            book[str(symbol).upper()] = {
                "reference": reference,
                "at": timezone.now().isoformat(),
            }
            extras["entry_in_doubt"] = book
            self.cfg.extras = extras
            self.cfg.save(update_fields=["extras"])
        except Exception as e:  # noqa: BLE001 — a lost note must not raise
            logger.warning("[%s_bot] could not record the in-doubt order for "
                           "%s: %s", self.asset_class, symbol, e)

    def _in_doubt_note(self, symbol: str):
        """The fresh in-doubt note for `symbol`, or None. Expires by itself:
        a note that never expired would retire the symbol permanently, which
        is the failure mode this whole file argues against."""
        try:
            book = (self.cfg.extras or {}).get("entry_in_doubt") or {}
            note = book.get(str(symbol).upper())
            if not note:
                return None
            from datetime import datetime as _dt
            age_h = ((timezone.now() - _dt.fromisoformat(note["at"]))
                     .total_seconds() / 3600.0)
            return note if age_h < self.IN_DOUBT_QUIET_HOURS else None
        except Exception:  # noqa: BLE001
            return None

    def _poll_working_entry(self, trade, client) -> None:
        """Ask the broker where a WORKING entry stands, and act on it.

        filled           -> the row becomes a position, priced from the fill
        dead, 0 filled   -> the row is CANCELED, nothing traded
        working          -> wait, unless it has outlived ENTRY_WORKING_MAX_HOURS
        unknown          -> the account's position decides; flat and old
                            means withdraw
        unreadable       -> wait; "could not ask" is not an answer
        """
        meta = trade.metadata or {}
        status_fn = getattr(client, "order_status", None)
        if not callable(status_fn):
            logger.error("[%s_bot] %s: entry %s is WORKING but this broker "
                         "client cannot report an order's state — check the "
                         "broker by hand",
                         self.asset_class, trade.symbol, trade.broker_order_id)
            # AND STILL WITHDRAW IT when it has outlived the limit. Returning
            # here made a venue that cannot be polled a venue whose queued
            # orders live forever: the row holds a concurrency slot, blocks
            # its symbol in propose_entry, and reconciliation skips
            # entry_working rows by design. The alert repeats daily.
            self._warn_working_entry_unresolved(
                trade, None,
                detail=("this broker client cannot report an order's state, "
                        "so nothing here can tell a fill from a cancel"))
            if (self._working_entry_age_hours(trade)
                    > self.ENTRY_WORKING_MAX_HOURS):
                cancel_working_entry(
                    trade, client,
                    reason=(f"still working after "
                            f"{self.ENTRY_WORKING_MAX_HOURS}h and this broker "
                            f"cannot report an order's state"),
                    cancel_parent=True)
            return
        try:
            st = status_fn(trade.broker_order_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s_bot] %s: order_status failed: %s",
                           self.asset_class, trade.symbol, e)
            return
        if st is None:
            return
        state = str(st.get("state") or "unknown")
        filled = float(st.get("filled") or 0)
        requested = float(meta.get("qty_requested") or trade.qty)

        if state == "filled" or (filled > 0 and state == "dead"):
            self._finish_working_entry(
                trade, client, qty=filled or requested,
                price=float(st.get("avgPrice") or 0), source="broker")
            return
        if state == "dead":
            cancel_working_entry(
                trade, client,
                reason=f"broker reported {st.get('status') or 'cancelled'} "
                       f"with nothing filled",
                cancel_parent=False)
            return
        if state == "working" and filled > 0:
            # Part of it printed and the rest is still working. The
            # remainder is withdrawn — the legs were sized for the whole
            # order and would over-cover — and what filled becomes the
            # position.
            # Proven, exactly as cancel_working_entry proves it: an
            # unconfirmed withdrawal leaves the rest to fill into a row
            # that claims only the part that printed, and those units are
            # invisible to a reconciliation that walks rows.
            cancel = getattr(client, "cancel_order", None)
            if not callable(cancel):
                logger.error("[%s_bot] %s: partly filled (%s of %s) and this "
                             "client cannot withdraw the remainder — leaving "
                             "the row WORKING", self.asset_class,
                             trade.symbol, filled, requested)
                return
            try:
                sent = cancel(trade.broker_order_id)
            except Exception as e:  # noqa: BLE001
                logger.error("[%s_bot] %s: could not withdraw the unfilled "
                             "remainder of %s (%s) — leaving the row WORKING",
                             self.asset_class, trade.symbol,
                             trade.broker_order_id, e)
                return
            after = None
            try:
                after = status_fn(trade.broker_order_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("[%s_bot] %s: post-cancel read failed: %s",
                               self.asset_class, trade.symbol, e)
            if sent is False or after is None or \
                    str((after or {}).get("state") or "") == "working":
                logger.error("[%s_bot] %s: the remainder of %s was not "
                             "confirmed withdrawn — leaving the row WORKING "
                             "rather than booking a partial the account may "
                             "exceed", self.asset_class, trade.symbol,
                             trade.broker_order_id)
                return
            # Book what actually printed, which the post-cancel read knows
            # better than the pre-cancel one: units can print during it.
            final_filled = float((after or {}).get("filled") or 0) or filled
            final_px = float((after or {}).get("avgPrice") or 0) or \
                float(st.get("avgPrice") or 0)
            self._finish_working_entry(
                trade, client, qty=final_filled, price=final_px,
                source="broker")
            return
        if state == "unknown":
            # The broker does not recognise the id. Two causes it cannot
            # separate: the order belongs to another clientId, or this
            # session lost its trade table in a restart. The ACCOUNT can
            # still settle it — but only when the position is attributable
            # to this row. An account total that another row or a
            # hand-bought lot also claims proves nothing, and booking it
            # would put units on this row that belong to someone else.
            positions = self._broker_snapshot(client, "positions")
            if positions is None:
                return
            held = self._broker_still_holds(trade, positions)
            if held is True:
                pos_fn = getattr(client, "position_avg_cost", None)
                pos = (pos_fn(trade.symbol,
                              sec_types=self._SEC_TYPES.get(trade.asset_class))
                       if callable(pos_fn) else None)
                if pos:
                    self._finish_working_entry(
                        trade, client,
                        qty=min(requested, float(pos.get("qty") or 0)
                                or requested),
                        price=float(pos.get("avg_cost") or 0),
                        source="position")
                    return
            # Not attributable, or flat. Flat is NOT proof the order never
            # filled: the entry may have filled and its GTC stop may have
            # closed the position again while nothing was watching. So the
            # row is never withdrawn on this evidence — it waits, visibly,
            # and the operator is told once.
            self._warn_working_entry_unresolved(trade, held)
            return
        if self._working_entry_age_hours(trade) > self.ENTRY_WORKING_MAX_HOURS:
            cancel_working_entry(
                trade, client,
                reason=f"still working after {self.ENTRY_WORKING_MAX_HOURS}h",
                cancel_parent=True)

    # How often to repeat the "this queued order cannot be resolved" alert.
    # Once is not enough: nothing else resolves such a row, it holds a
    # concurrency slot, and a single email at 03:00 is a message nobody
    # sees. Daily, until a human acts.
    UNRESOLVED_REALERT_HOURS = 24

    def _warn_working_entry_unresolved(self, trade, held,
                                       detail: str = "") -> None:
        """Say — and keep saying — that a working entry cannot be resolved."""
        meta = dict(trade.metadata or {})
        last = meta.get("entry_unresolved_notified_at")
        if last:
            try:
                from datetime import datetime as _dt
                age_h = ((timezone.now() - _dt.fromisoformat(last))
                         .total_seconds() / 3600.0)
                if age_h < self.UNRESOLVED_REALERT_HOURS:
                    return
            except (TypeError, ValueError):
                pass
        elif meta.get("entry_unresolved_notified"):
            # A row stamped by the earlier once-only version: re-alert now
            # and start keeping the timestamp.
            pass
        detail = detail or (
                 "the broker does not recognise the order and the account's "
                  "position cannot be attributed to this row"
                  if held is None else
                  "the broker does not recognise the order and the account "
                  "holds no matching position — it may never have filled, or "
                  "it may have filled and already been stopped out")
        logger.error("[%s_bot] %s: working entry %s unresolved — %s",
                     self.asset_class, trade.symbol, trade.broker_order_id,
                     detail)
        try:
            from bot_program.notifications import notify_staff
            notify_staff(
                title=f"⚠ {trade.symbol}: queued entry cannot be resolved",
                body=(f"{self.asset_class.upper()} order "
                      f"{trade.broker_order_id}: {detail}. The row is left "
                      f"WORKING and is NOT withdrawn — check the broker's "
                      f"orders and executions for it."),
                url="/positions/")
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s_bot] unresolved-entry alert failed: %s",
                           self.asset_class, e)
        meta["entry_unresolved_notified"] = True
        meta["entry_unresolved_notified_at"] = timezone.now().isoformat()
        trade.metadata = meta
        trade.save(update_fields=["metadata"])

    def _finish_working_entry(self, trade, client, *, qty: float, price: float,
                              source: str) -> None:
        """A WORKING entry filled: the row becomes a position.

        Size and price come from the broker. Protection is claimed only if
        the stop leg is seen resting NOW — a partial fill withdraws the legs
        (they would over-cover) and hands the position to bot-side
        management, exactly as market_order does at placement.
        """
        meta = dict(trade.metadata or {})
        requested = float(meta.get("qty_requested") or trade.qty)
        legs = [str(x) for x in (meta.get("protective_order_ids") or [])]
        partial = 0 < qty < requested * 0.999
        if qty > 0:
            trade.qty = Decimal(str(round(qty, 8)))
        if price > 0:
            trade.entry_price = Decimal(str(price))
            meta["fill_source"] = source
        else:
            meta["fill_source"] = "ticker"      # the pre-order price stands
        meta.pop("entry_working", None)
        meta["entry_filled_at"] = timezone.now().isoformat()

        protected = False
        if legs:
            if partial:
                # The legs were sized for the WHOLE order, so on a partial
                # fill they over-cover: one would close what filled and
                # OPEN the remainder the other way. They come down — and an
                # unconfirmed cancel is recorded as unconfirmed, because
                # since these legs became GTC a leaked one rests for days.
                cancel = getattr(client, "cancel_order", None)
                unconfirmed = []
                for oid in legs:
                    try:
                        if callable(cancel) and cancel(str(oid)):
                            continue
                    except Exception as e:  # noqa: BLE001
                        logger.error("[%s_bot] %s: leg %s may still rest "
                                     "after a partial fill (%s)",
                                     self.asset_class, trade.symbol, oid, e)
                    unconfirmed.append(str(oid))
                if unconfirmed:
                    meta["protective_legs_unconfirmed"] = True
                    logger.error(
                        "[%s_bot] %s: leg(s) %s were NOT confirmed cancelled "
                        "after a partial fill — they are GTC and over-cover "
                        "the position; cancel them at the broker",
                        self.asset_class, trade.symbol,
                        ", ".join(unconfirmed))
                meta["protection_note"] = (
                    f"filled {qty} of {requested}; protective legs withdrawn "
                    f"(they would over-cover) — bot-side management"
                    + (f"; NOT CONFIRMED: {', '.join(unconfirmed)}"
                       if unconfirmed else ""))
            else:
                resting = self._broker_snapshot(client, "resting")
                stop_id = meta.get("protective_stop_id")
                want = [str(stop_id)] if stop_id else legs
                if resting is None:
                    # COULD NOT LOOK is not proof, here as everywhere else
                    # (_protection_vanished refuses on exactly this). And
                    # of the two ways to be wrong, only one is unbounded:
                    # saying protected=False while a GTC leg really is
                    # resting arms bot-side exits beside it, and _close_trade
                    # goes to market BEFORE stripping legs — two exits, and
                    # the account ends up reversed with no row describing
                    # it. Saying protected=True when the legs never armed
                    # leaves the position to the broker for one tick, and
                    # the NEXT tick's _protection_vanished is the function
                    # whose whole job is to catch precisely that and hand it
                    # back to bot-side management. So: assume the bracket
                    # armed (which is what a bracket does on a fill), say
                    # so on the row, and let the detector correct it.
                    protected = True
                    meta["protection_note"] = (
                        "the broker's resting orders were unreadable at the "
                        "fill — assuming the bracket armed; the next tick's "
                        "vanished-stop check confirms or corrects it")
                    logger.warning(
                        "[%s_bot] %s: could not read resting orders at the "
                        "fill — leaving the broker in charge for this tick",
                        self.asset_class, trade.symbol)
                elif any(i in resting for i in want):
                    protected = True
                else:
                    meta["protection_note"] = (
                        "stop leg not seen resting at fill — bot-side "
                        "management")
                    # A leg that IS resting while the stop is not would sit
                    # armed beside bot-side exits. Take it down first, and
                    # keep the broker in charge if it will not come down —
                    # the same rule _protection_vanished applies.
                    others = [oid for oid in legs if oid in resting]
                    cancel = getattr(client, "cancel_order", None)
                    stuck = []
                    for oid in others:
                        try:
                            if callable(cancel) and cancel(str(oid)):
                                continue
                        except Exception as e:  # noqa: BLE001
                            logger.error("[%s_bot] %s: cancelling leg %s at "
                                         "the fill failed: %s",
                                         self.asset_class, trade.symbol,
                                         oid, e)
                        stuck.append(str(oid))
                    if stuck:
                        protected = True
                        meta["protective_legs_unconfirmed"] = True
                        meta["protection_note"] = (
                            f"the stop leg did not arm but leg(s) "
                            f"{', '.join(stuck)} rest and could not be "
                            f"cancelled — the broker keeps this position; "
                            f"cancel them at the broker")
                        logger.error(
                            "[%s_bot] %s: leg(s) %s rest and would not "
                            "cancel — NOT arming bot-side exits beside them",
                            self.asset_class, trade.symbol,
                            ", ".join(stuck))
        meta["protected"] = protected
        trade.metadata = meta
        trade.save(update_fields=["qty", "entry_price", "metadata"])
        logger.info("[%s_bot] %s: WORKING entry filled — qty %s @ %s (%s), "
                    "protected=%s", self.asset_class, trade.symbol, trade.qty,
                    trade.entry_price, source, protected)
        # The cost basis is opened HERE, on the real fill, for the real size
        # at the real price — the entry path skips it for a working row
        # precisely so no lot exists for units nobody owns yet.
        try:
            from bot_program.tax_lots import open_lot
            open_lot(trade)
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s_bot] tax_lots.open_lot failed: %s",
                           self.asset_class, e)
        # WHO placed it decides which voice announces it. A manual config is
        # an ordinary enabled AssetBotConfig, so its WORKING rows are polled
        # here too — and announcing a hand-placed order's fill as a bot event
        # puts it behind the bot-alert preference. An operator who muted the
        # fleet's chatter would then have "nothing has filled yet" as the
        # last thing they were ever told about their own live order.
        try:
            from bot_program.manual_trade import MANUAL_RULE as _MANUAL
        except Exception:  # noqa: BLE001
            _MANUAL = "manual_take"
        is_manual = str(trade.rule_name or "") == _MANUAL
        try:
            if is_manual:
                from bot_program.notifications import notify_manual_fill_open
                notify_manual_fill_open(
                    self.user, asset_class=self.asset_class,
                    symbol=trade.symbol, side=trade.side, qty=trade.qty,
                    entry_price=trade.entry_price, trade_id=trade.id,
                    live=not trade.paper)
            else:
                from bot_program.notifications import notify_bot_fill_open
                notify_bot_fill_open(
                    self.user, asset_class=self.asset_class,
                    symbol=trade.symbol, side=trade.side, qty=trade.qty,
                    entry_price=trade.entry_price,
                    rule_name=trade.rule_name, trade_id=trade.id)
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s_bot] fill notification failed: %s",
                           self.asset_class, e)

    def _broker_snapshot(self, client, what: str):
        """`what` in {"resting", "positions"} from this tick's cache.

        None means the broker could not be asked. The cache lives for one
        manage_positions pass, so a fleet of protected rows costs one
        openTrades() and one positions() read, not one pair per row.
        """
        cache = getattr(self, "_tick_broker_cache", None)
        if cache is None:
            cache = self._tick_broker_cache = {}
        # KEYED ON THE VENUE, NEVER ON THE OBJECT'S ADDRESS. `client` is
        # rebound per row inside manage_positions and this cache keeps no
        # reference to the old one, so a freed client's id() can be handed
        # straight to the next — CPython reuses addresses for same-size
        # objects — and the hit would then answer one venue's row out of
        # another venue's book. The worst consumer of that is the in-doubt
        # close, which reads False as "flat, send nothing". One venue, one
        # read per pass is also exactly what the docstring above promises.
        # adapter_key answers "" for a class it does not know, so the class
        # name is the fallback rather than one shared empty bucket.
        from bot_program.engine.capabilities import adapter_key
        key = (what, adapter_key(client) or type(client).__name__)
        if key in cache:
            return cache[key]
        value = None
        try:
            if what == "resting":
                fn = getattr(client, "resting_order_ids", None)
                value = fn() if callable(fn) else None
            elif what == "positions":
                fn = getattr(client, "get_positions", None)
                value = fn() if callable(fn) else None
        except Exception as e:  # noqa: BLE001 — unreachable reads as unknown
            logger.warning("[%s_bot] broker %s snapshot failed: %s",
                           self.asset_class, what, e)
            value = None
        cache[key] = value
        return value

    # The broker's secType for each asset class we route to IBKR. A position
    # is only this row's if the instrument type matches too: IBKR reports an
    # OPTION position under its UNDERLYING symbol, so an AAPL call answers a
    # symbol-only test for an AAPL stock row.
    _SEC_TYPES = {"stock": ("STK",), "etf": ("STK",), "index": ("IND", "STK"),
                  "forex": ("CASH",), "options": ("OPT",),
                  "commodity": ("FUT", "CMDTY", "STK"), "cfd": ("CFD",)}

    def _broker_still_holds(self, trade, positions) -> "Optional[bool]":
        """Does the broker still hold THIS row's position?

        True / False, or None for "held by the account but not attributable
        to this row" — which is not a yes and must never be treated as one.
        Attribution fails when another OPEN row of this user, or a lot the
        operator bought by hand, claims units of the same symbol: the
        account total cannot then say whose they are.
        """
        # OPTIONS CANNOT BE ATTRIBUTED FROM A POSITION LIST. IBKR reports
        # every option position under its UNDERLYING symbol, and the list
        # carries no strike, expiry or right — so a different strike, a
        # different expiry, one leg of a spread or a hand-bought lot all
        # answer to the same (symbol, OPT, side) test. There is no honest
        # yes available here, and a wrong yes books a phantom whose close
        # sells contracts the account does not hold.
        if trade.asset_class == "options":
            return None

        want_sym = trade.symbol.upper()
        want_types = self._SEC_TYPES.get(trade.asset_class)
        mine = [p for p in positions
                if str(p.get("symbol", "")).upper() == want_sym
                and (not want_types or not p.get("sec_type")
                     or str(p.get("sec_type", "")).upper() in want_types)]
        if not mine:
            # NOT NAMED IS NOT NOT THERE. False is read by the in-doubt
            # branch as a positive "the broker is flat and nothing is sent",
            # so a close that may never have landed would never be re-sent.
            # None is this docstring's own "cannot say" and every caller
            # already handles it.
            if any(p.get("symbol_unresolved") is True for p in positions
                   if isinstance(p, dict)):
                return None
            return False
        # Side matters: a SELL row is not held by a long position, and
        # closing it would double the long rather than flatten a short.
        same_side = [p for p in mine
                     if not p.get("side")
                     or str(p.get("side", "")).upper() == trade.side.upper()]
        if not same_side:
            return False
        try:
            held_qty = sum(float(p.get("qty") or 0) for p in same_side)
        except (TypeError, ValueError):
            return None
        if held_qty <= 0:
            return False

        try:
            want_qty = float(trade.qty)
        except (TypeError, ValueError):
            return None

        from bot_program.models import AssetBotTrade
        others = (AssetBotTrade.objects
                  .filter(config__user=self.user, symbol=trade.symbol,
                          side=trade.side, paper=False,
                          asset_class=trade.asset_class,
                          status__in=("OPEN", "CLOSE_PENDING"))
                  .exclude(pk=trade.pk))
        try:
            # A WORKING row holds NOTHING at the broker: its full requested
            # quantity sits on the row while the order is still queued.
            # Counting it as a claim would make attribution impossible for
            # every real position beside it — the vanished-stop net would
            # never fire again. Rows of another asset class are excluded in
            # the query above for the same reason: a CFD on AAPL and a
            # share of AAPL are different positions at the broker.
            claimed = sum(float(t.qty) for t in others
                          if not is_entry_working(t))
        except (TypeError, ValueError):
            return None
        # The broker's size must cover what this row claims — otherwise
        # "the account holds one of the hundred shares this row says it
        # owns" would read as "this row's position is still on", and the
        # bot-side close that follows sells ninety-nine it does not have.
        if held_qty + 1e-9 < want_qty + claimed:
            if held_qty + 1e-9 >= want_qty and claimed <= 0:
                return True
            return None
        return True

    def _protection_vanished(self, trade, client) -> bool:
        """True when the row's stop leg no longer rests at the broker while
        the position is still held — and un-protect the row when it is.

        Three answers are deliberately "no": a venue that cannot list its
        resting orders (PaperTrader, OANDA's on-fill stops), a snapshot
        that could not be read (never turn "could not look" into "gone"),
        and a position the broker no longer holds either (the stop FILLED;
        reconciliation finalises that row, and taking it back here would
        book a second exit). Only a held position with no stop is ours.
        """
        if not callable(getattr(client, "resting_order_ids", None)):
            return False
        meta = trade.metadata or {}
        stop_id = meta.get("protective_stop_id")
        ids = ([str(stop_id)] if stop_id
               else [str(x) for x in (meta.get("protective_order_ids") or [])])
        if not ids:
            return False

        resting = self._broker_snapshot(client, "resting")
        if resting is None:
            return False
        if any(oid in resting for oid in ids):
            return False
        positions = self._broker_snapshot(client, "positions")
        if positions is None:
            return False
        held = self._broker_still_holds(trade, positions)
        if held is None:
            # Held by the account, but not attributable to THIS row (another
            # row or a hand-bought lot claims the same symbol). Un-protecting
            # would hand bot-side SL/TP a position it may not own, and its
            # close would sell someone else's units.
            logger.warning("[%s_bot] %s: the stop leg is gone but the "
                           "broker's position cannot be attributed to this "
                           "row — leaving it protected and alerting instead",
                           self.asset_class, trade.symbol)
            self._notify_protection_vanished(
                trade, "the broker's stop leg is gone and the position "
                       "could not be attributed to this row — check the "
                       "broker's open orders by hand")
            return False
        if not held:
            return False

        reason = (f"stop leg {ids[0]} no longer rests at the broker while "
                  f"the position is still held")
        logger.error("[%s_bot] %s: %s — un-protecting the row; bot-side "
                     "SL/TP management resumes this tick",
                     self.asset_class, trade.symbol, reason)
        # The SURVIVING leg comes down first. Bot-side SL/TP is driven off
        # the same trade.stop_loss / trade.take_profit the resting leg sits
        # at, and _close_trade goes to market BEFORE it strips the legs — so
        # a target left armed beside a bot-side take-profit sells the
        # position twice and leaves the account short. It is cancelled here,
        # while the row is still marked protected, so a failure leaves the
        # broker in charge rather than two exits racing.
        surviving = [oid for oid in
                     (meta.get("protective_order_ids") or []) if oid in resting]
        cancel = getattr(client, "cancel_order", None)
        unconfirmed = []
        for oid in surviving:
            try:
                if callable(cancel) and cancel(str(oid)):
                    continue
            except Exception as e:  # noqa: BLE001
                logger.error("[%s_bot] %s: cancelling the surviving leg %s "
                             "failed: %s", self.asset_class, trade.symbol,
                             oid, e)
            unconfirmed.append(str(oid))
        if unconfirmed:
            logger.error("[%s_bot] %s: leg(s) %s still rest at the broker — "
                         "leaving the row PROTECTED rather than running "
                         "bot-side exits beside them",
                         self.asset_class, trade.symbol,
                         ", ".join(unconfirmed))
            meta = dict(meta)
            meta["protective_legs_unconfirmed"] = True
            trade.metadata = meta
            trade.save(update_fields=["metadata"])
            self._notify_protection_vanished(
                trade, f"the stop leg is gone but leg(s) "
                       f"{', '.join(unconfirmed)} could not be cancelled — "
                       f"cancel them at the broker before this position is "
                       f"managed here")
            return False

        meta = dict(meta)
        meta["protected"] = False
        meta["protection_vanished_at"] = timezone.now().isoformat()
        meta["protection_vanished_reason"] = reason
        if surviving:
            meta["protection_legs_cancelled"] = surviving
        # The ids stay on the row: the close path cancels whatever is
        # listed, and a leg this session could not see must still be tried.
        trade.metadata = meta
        trade.save(update_fields=["metadata"])
        self._notify_protection_vanished(trade, reason)
        return True

    def _notify_protection_vanished(self, trade, reason: str) -> None:
        """Tell the operator once per position that its broker stop is gone."""
        meta = dict(trade.metadata or {})
        if meta.get("protection_vanished_notified"):
            return
        try:
            from bot_program.notifications import notify_protection_vanished
            notify_protection_vanished(
                self.user, asset_class=self.asset_class, symbol=trade.symbol,
                side=trade.side, qty=trade.qty, stop_loss=trade.stop_loss,
                reason=reason, trade_id=trade.id)
            meta["protection_vanished_notified"] = True
            trade.metadata = meta
            trade.save(update_fields=["metadata"])
        except Exception as e:  # noqa: BLE001 — never let an alert block exits
            logger.warning("[%s_bot] protection-vanished notification failed: "
                           "%s", self.asset_class, e)

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
            # BOTH rules are asked, every tick. The first version asked the
            # trail only `if candidate is None`, which reads like "break-even
            # takes precedence" but meant something far worse:
            # `breakeven_candidate` returns a PRICE whenever R has passed the
            # trigger and `breakeven_armed` is unset, and that flag is stamped
            # only on a move the venue ACCEPTED (see below). So on a config
            # carrying both knobs, once the trail had lifted the stop past
            # entry+buffer the break-even price stopped being an improvement,
            # the trail was never reached, and the broker stop never moved
            # again — silently, for the life of the position, with no
            # `stop_rules_inert` stamp and no warning. The bot-side path never
            # had this: it runs both rules unconditionally.
            options = []
            if breakeven_at_r > 0:
                options.append(("breakeven", breakeven_candidate(
                    trade, price, breakeven_at_r,
                    self._extras_float("breakeven_buffer_r"))))
            if trail_pct > 0:
                options.append(("trail", trail_candidate(
                    trade, price, trail_pct,
                    self._extras_float("trail_start_r"))))
            # Asked BEFORE anything reaches a broker: a leg modified and
            # then refused by our own tighten-only rule would be a round
            # trip that changed the venue and not the row.
            viable = [(w, c) for w, c in options
                      if c is not None and is_improvement(trade, c, price)]
            if not viable:
                return False
            # The TIGHTER of the two, not the first one to answer. One broker
            # round trip per tick, and a break-even price that sits below an
            # already-trailed stop can never drag it back toward entry.
            why, candidate = (max(viable, key=lambda wc: wc[1])
                              if trade.side == "BUY"
                              else min(viable, key=lambda wc: wc[1]))
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
        # EVERY handle is tried, in the order most likely to be right — not
        # the first one that happens to be set, which is the defect this
        # replaces. The three keys state three different things and only the
        # venue knows which one its bracket answers to:
        #
        #   protective_trade_id — the position/trade handle. On OANDA the stop
        #     is not a standalone order at all and this is the only thing that
        #     can move it. On Saxo it is the PositionId, which resolves the
        #     legs under FifoEndOfDay and resolves NOTHING under the real-time
        #     netting profiles, where the brackets are free-standing orders.
        #   protective_stop_id — the NAMED leg, where the venue said which
        #     order is the stop.
        #   protective_order_ids LAST, because it does not say which is which:
        #     on an Alpaca or IBKR long bracket its first entry is the
        #     TAKE-PROFIT.
        #
        # Stopping at the first handle meant a Saxo real-time-netting row,
        # which carries both a PositionId and a stop OrderId, only ever
        # offered the PositionId: no leg resolved, and break-even and trailing
        # never moved that stop again for the life of the position.
        #
        # THE SAFETY PROPERTY IS THE VENUE'S REFUSAL, not this ordering.
        # Alpaca, IBKR and Saxo read the RESTING order's own type before they
        # write, so a stop request can never land on a target. OANDA and eToro
        # do not type-check at all — their movers write a field on the TRADE —
        # and they are safe here only because both report protectiveOrders as
        # empty, so their rows carry the trade handle and nothing else. If
        # either ever records child order ids, that refusal must be added
        # first.
        flat = meta_now.get("protective_order_ids") or []
        if isinstance(flat, (str, bytes)):
            # One id, not a sequence of characters: splatting a string would
            # ask the venue to move legs named "7" and "7".
            flat = [flat]
        ids, seen = [], set()
        for cand in (meta_now.get("protective_trade_id"),
                     meta_now.get("protective_stop_id"), *flat):
            key = str(cand) if cand else ""
            if not key or key in seen:
                continue
            seen.add(key)
            ids.append(key)
        if not ids:
            self._note_stop_rules_inert(trade)
            return False

        # WHAT EACH HANDLE SAID, not only the last one: with three handles,
        # "leg T1 is a take-profit" from the flat list would otherwise be the
        # only thing recorded about a stop leg that is actually gone.
        #
        # And a WALL-CLOCK ceiling on one walk. Saxo's client timeout is 20s
        # and its leg resolution costs two GETs per handle, so a transport
        # stall turns a three-handle walk into a minute for ONE position —
        # while manage_positions runs every row in one task, delaying the EXIT
        # checks of every position behind it. Three handles are cheap when the
        # venue answers; they must not be able to triple an outage. The FIRST
        # handle is always asked: a slow but working venue still gets its move.
        walk_started = timezone.now()
        moved, notes, accepted = False, [], None
        for oid in ids:
            if notes and ((timezone.now() - walk_started).total_seconds()
                          > self.STOP_MOVE_WALK_BUDGET_S):
                notes.append("remaining handles not asked: the venue did not "
                             "answer within the walk budget")
                break
            try:
                res = mover(str(oid), float(candidate))
            except Exception as e:  # noqa: BLE001
                notes.append(f"{oid}: {e}")
                continue
            if res and res.get("ok"):
                moved = True
                accepted = res.get("price")
                break
            notes.append(
                f"{oid}: {(res or {}).get('reason') or 'no leg matched'}")

        if not moved:
            note = "; ".join(notes) or "no leg matched"
            logger.warning(
                "[%s_bot] %s: %s wanted the stop at %s but the broker leg "
                "could not be moved (%s) — the position is still protected "
                "at its old level",
                self.asset_class, trade.symbol, why, candidate, note)
            # EVERY handle the row carries was refused, and that used to be
            # completely silent: _note_stop_rules_inert is not reached from
            # here (a mover EXISTS), so the row carried no stamp and every
            # surface kept reading "protected, managed" while the stop rules
            # had stopped reaching the venue. Nothing is sent here — this only
            # writes down what already happened.
            self._note_stop_move_failed(trade, note)
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
        # A leg that MOVED is proof the rules are not inert after all — and
        # the run of failures that led to the stamp is over, so the count and
        # the venue's last words go with it. Leaving the count would make the
        # next single failure look like the fourth and stamp the row on a
        # blip; leaving the detail would print a stale reason on the page.
        meta.pop("stop_rules_inert", None)
        meta.pop("stop_rules_inert_detail", None)
        meta.pop("stop_move_failures", None)
        meta.pop("stop_move_last_error", None)
        meta.pop("stop_move_last_at", None)
        trade.stop_loss = resting
        trade.metadata = meta
        trade.save(update_fields=["stop_loss", "metadata"])
        logger.info("[%s_bot] %s %s moved the BROKER stop to %s (asked %s) "
                    "at mark %s", self.asset_class, trade.symbol, why,
                    resting, candidate, price)
        return True

    #: Consecutive attempted moves — ticks on which a candidate existed AND
    #: was an improvement — where EVERY recorded handle was refused, before
    #: the row is stamped inert. A tick that wanted no move neither counts nor
    #: clears. One failure is a blip: an expired session, a 202 the venue
    #: never confirmed, a leg momentarily unroutable. Three are a fact about
    #: the ROW rather than about the network. THREE STATES, deliberately: no
    #: count means nothing has failed, a count below this means it failed and
    #: we are not yet calling it dead, the stamp means dead until a leg moves.
    STOP_MOVE_FAILURES_BEFORE_INERT = 3

    #: A wall-clock ceiling on ONE walk of the handles, in seconds. See the
    #: comment at the walk: three handles must not be able to triple a
    #: transport outage for every position behind this one.
    STOP_MOVE_WALK_BUDGET_S = 25.0

    def _note_stop_move_failed(self, trade, note: str) -> None:
        """Record an attempted move where every handle refused.

        The old code logged one warning per tick and wrote nothing at all, so
        the position card, the forensics timeline and the operator all kept
        reading a managed position while break-even and trailing had stopped
        reaching the venue for good.
        """
        try:
            meta = dict(trade.metadata or {})
            fails = int(meta.get("stop_move_failures") or 0) + 1
            meta["stop_move_failures"] = fails
            # The venue's OWN words, not our summary of them: "leg 3 is not
            # among the open orders" and "no session" call for opposite
            # actions from the operator.
            meta["stop_move_last_error"] = str(note)[:300]
            meta["stop_move_last_at"] = timezone.now().isoformat()
            trade.metadata = meta
            trade.save(update_fields=["metadata"])
        except Exception as e:  # pragma: no cover — never block the tick
            logger.warning("[%s_bot] could not record a failed stop move on "
                           "%s: %s", self.asset_class, trade.symbol, e)
            return
        if fails >= self.STOP_MOVE_FAILURES_BEFORE_INERT:
            self._note_stop_rules_inert(trade, reason="legs_unmovable",
                                        detail=str(note)[:200])

    def _note_stop_rules_inert(self, trade, reason: str = "broker_protected",
                               detail: str = "") -> None:
        """Warn once per trade, PER REASON, that its stop rules cannot run.

        Only for positions whose config actually asked for one: a config
        with no stop rules configured is not owed a warning about them.

        The two reasons are not the same fact. "broker_protected" means no
        client here can move a resting order at all — nothing to do at the
        venue. "legs_unmovable" means the client CAN and every handle this row
        carries was refused — a leg to go and look at. Collapsing them would
        leave the operator unable to tell a missing capability from protection
        that has come adrift.
        """
        if not (self._extras_float("breakeven_at_r") > 0
                or self._extras_float("trail_pct") > 0):
            return
        meta = trade.metadata or {}
        if meta.get("stop_rules_inert") == reason:
            return
        if reason == "broker_protected":
            logger.warning(
                "[%s_bot] %s: break-even/trailing are configured but this "
                "position's stop RESTS AT THE BROKER, which no client can "
                "modify yet - the stop stays where the bracket put it",
                self.asset_class, trade.symbol)
        else:
            logger.warning(
                "[%s_bot] %s: break-even/trailing are configured and this "
                "position's stop RESTS AT THE BROKER, but EVERY recorded leg "
                "handle was refused (%s) - the stop rules are inert for this "
                "position until a leg moves again",
                self.asset_class, trade.symbol, detail or "no leg matched")
        try:
            meta = dict(meta)
            meta["stop_rules_inert"] = reason
            if detail:
                meta["stop_rules_inert_detail"] = str(detail)[:200]
            else:
                # Re-stamped with a DIFFERENT reason and no detail of its own:
                # the detail on the row belongs to the reason being replaced,
                # and leaving it prints legs_unmovable's venue words beside a
                # broker_protected stamp.
                meta.pop("stop_rules_inert_detail", None)
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
        # A VENUE WHERE AN OPPOSITE ORDER DOES NOT FLATTEN — Saxo under the
        # FifoEndOfDay netting profile, and eToro ALWAYS, whose market_order
        # has no close branch at all and answers a SELL with `sellShort`. The
        # decision is in engine/venue_close.py rather than here because the
        # retry drain and the kill switch send closes too, and for the
        # platform's whole life all three sent an opening order on those
        # venues: the row booked CLOSED at that fill while the account held
        # DOUBLE, hedged, paying both spreads.
        #
        # It RAISES rather than send an opening order when the venue needs a
        # position id and the row has none. The refusal is the point: the row
        # goes CLOSE_PENDING, where the drain reads the broker's own book.
        from bot_program.engine.venue_close import close_or_refuse

        close_side = "SELL" if trade.side == "BUY" else "BUY"
        return close_or_refuse(trade, client, float(trade.qty),
                               close_side=close_side,
                               client_order_id=client_order_id)

    #: What each adapter's own `env` string means in the two words the
    #: platform's money side uses. Unlisted is UNKNOWN, never "live":
    #: entry_meta carries no world at all rather than a guessed one.
    VENUE_WORLDS = {"live": "live", "paper": "paper", "sim": "paper",
                    "demo": "paper", "practice": "paper", "testnet": "paper"}

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
            # A CLOSE NOBODY CONFIRMED. An adapter that says inDoubt has
            # placed an order it cannot vouch for; booking the row CLOSED on
            # that is how a live position ends up with no owner, and
            # re-sending it is how a closed long becomes a short. Marked so
            # the in-doubt branch in _close_trade owns it.
            if res.get("inDoubt") and filled <= 0:
                err = RuntimeError(
                    "the broker did not confirm the close"
                    + (f" (reference {res.get('reference')})"
                       if res.get("reference") else ""))
                err.in_doubt = True
                err.reference = str(res.get("reference") or "")
                raise err
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
                # The RETURN VALUE counts, not just the absence of an
                # exception. IBKR answers False (no raise) when the id is
                # not among the orders this session can see — which covers
                # both "already gone" and "still resting, placed by another
                # session". Since the legs became GTC they no longer expire
                # at the session close, so a leaked stop rests for days and
                # fires against a flat book, opening a reverse position.
                # "We could not tell" must therefore be recorded as not
                # done; the caller stamps the row.
                if cancel(oid) is False:
                    ok = False
                    logger.error(
                        "[%s_bot] %s: the broker did not confirm cancelling "
                        "leg %s — it may still be resting (GTC), and a "
                        "resting exit against a flat book OPENS a position",
                        self.asset_class, trade.symbol, oid)
            except Exception as e:
                ok = False
                logger.error("[%s_bot] cancel protective order %s failed: "
                             "%s — it may still be resting at the broker",
                             self.asset_class, oid, e)
        return ok

    #: How often an unresolvable in-doubt close repeats itself. Once is
    #: not enough — nothing else resolves such a row and it holds a live
    #: position — and every tick is noise nobody reads.
    CLOSE_DOUBT_REALERT_HOURS = 1.0

    def _warn_close_in_doubt_unresolved(self, trade, doubt) -> None:
        """Say — and keep saying — that a close may be live and cannot be
        proved either way. The row is NOT closed and no order is sent."""
        meta = dict(trade.metadata or {})
        last = meta.get("close_doubt_alerted_at")
        if last:
            try:
                from datetime import datetime as _dt
                age_h = ((timezone.now() - _dt.fromisoformat(last))
                         .total_seconds() / 3600.0)
                if age_h < self.CLOSE_DOUBT_REALERT_HOURS:
                    return
            except (TypeError, ValueError):
                pass
        ref = (doubt or {}).get("reference") or "(none)"
        logger.error("[%s_bot] %s: a close MAY be live under reference %s and "
                     "the broker cannot be read — nothing is sent and the row "
                     "stays OPEN", self.asset_class, trade.symbol, ref)
        try:
            from bot_program.notifications import notify_staff
            notify_staff(
                title=f"⚠ {trade.symbol}: a close may be live and cannot be "
                      f"resolved",
                body=(f"{self.asset_class.upper()} {trade.symbol}: the close "
                      f"under reference {ref} did not come back, and the "
                      f"broker's positions cannot be read — so the platform "
                      f"cannot tell whether it filled. NOTHING is being sent "
                      f"(a second close would reverse the position) and the "
                      f"row stays OPEN. Check the broker by hand."),
                url="/positions/")
        except Exception as e:  # noqa: BLE001
            logger.warning("[%s_bot] in-doubt close alert failed: %s",
                           self.asset_class, e)
        meta["close_doubt_alerted_at"] = timezone.now().isoformat()
        trade.metadata = meta
        trade.save(update_fields=["metadata"])

    def _flag_unconfirmed_legs(self, trade, why: str) -> None:
        """Record and ANNOUNCE a protective leg that may still rest.

        protective_legs_unconfirmed was written at six places in this file and
        read by no view, template, alert or task, while the identical event on
        the entry-withdrawal path pages a human. A resting exit against a flat
        book OPENS a position when it fires, and nothing in the platform
        describes that position — so this is not a log line, it is an
        incident.

        Every line is fenced: this runs inside _close_trade's try, whose
        handler marks the row CLOSE_PENDING, so an alert that raised would
        turn a completed close into a pending one.
        """
        legs = []
        try:
            meta = dict(trade.metadata or {})
            legs = [str(x) for x in (meta.get("protective_order_ids") or [])]
            meta["protective_legs_unconfirmed"] = True
            # WHICH legs, and when. The bare boolean sent the operator to the
            # log to find out, and by then the log had rolled.
            meta["protective_legs_unconfirmed_ids"] = legs
            meta["protective_legs_unconfirmed_at"] = timezone.now().isoformat()
            trade.metadata = meta
            trade.save(update_fields=["metadata"])
        except Exception as e:  # noqa: BLE001 — never fail the close
            logger.critical("[%s_bot] %s: could not record an unconfirmed "
                            "protective leg (%s) — the leg may be resting",
                            self.asset_class, trade.symbol, e)
        logger.critical("[%s_bot] %s: a protective leg could not be confirmed "
                        "cancelled %s — check the broker for a resting order "
                        "(%s)", self.asset_class, trade.symbol, why,
                        ", ".join(legs) or "no ids recorded")
        try:
            from bot_program.notifications import notify_staff
            notify_staff(
                title=f"⚠ {trade.symbol}: a protective order may still rest "
                      f"at the broker",
                body=(f"{self.asset_class.upper()} {trade.symbol}: {why}, and "
                      f"leg(s) {', '.join(legs) or '(none recorded)'} could "
                      f"not be confirmed cancelled. They are GOOD-TILL-"
                      f"CANCELLED: if one fires against a flat book it OPENS "
                      f"a position the other way, at full size, and no row "
                      f"here describes it. Cancel them at the broker."),
                url="/treasury/")
        except Exception as e:  # noqa: BLE001 — never fail the close
            logger.critical("[%s_bot] %s: the loose-leg alert failed (%s) — "
                            "the leg may be resting and nobody has been told",
                            self.asset_class, trade.symbol, e)

    def _close_trade(self, trade, price, client, *, reason: str) -> bool:
        """Close a trade — pnl is realised in the config's base_currency.

        `price` is the FALLBACK exit price, never the order: the broker order
        is a MARKET order and a live exit books at the fill the broker
        reports. It is None when nothing could price the position — the clock
        exit fires on those, because it reads the clock — and resolve_exit_fill
        then books the entry price and records that it had to. A PAPER close
        must still be handed a number: its modelled fill does float(price).

        The broker order is attempted FIRST; the row is finalised CLOSED only
        when that succeeded (or the trade is paper). On broker failure the row
        moves to CLOSE_PENDING — the position is still live at the broker —
        and the retry_pending_closes beat task drains it. Returns True when
        the trade ended CLOSED.
        """
        # A CLOSE THAT MAY ALREADY BE LIVE IS RESOLVED BEFORE ANOTHER IS
        # SENT. The row carries close_in_doubt when its close request never
        # came back, and a second close turns a closed long into a full-size
        # short — while the clock exit above would fire on every pass. So ask
        # the broker what it holds, and act on the answer rather than on hope.
        doubt = (trade.metadata or {}).get("close_in_doubt")
        if doubt and not trade.paper:
            held = None
            try:
                positions = self._broker_snapshot(client, "positions")
                held = (None if positions is None
                        else self._broker_still_holds(trade, positions))
            except Exception as e:  # noqa: BLE001 — cannot say stays None
                logger.warning("[%s_bot] %s: could not resolve the in-doubt "
                               "close (%s)", self.asset_class, trade.symbol, e)
            if held is False:
                # The in-doubt close LANDED. Sending another would open a
                # position. Nothing is sent: the row is flat at the broker,
                # and reconciliation finalises it from the broker's own fill
                # — which is a measured exit, not the mark we would book here.
                logger.error("[%s_bot] %s: the in-doubt close (reference %s) "
                             "DID land — the broker is flat and nothing is "
                             "sent. Reconciliation books the exit from its "
                             "own fill.", self.asset_class, trade.symbol,
                             (doubt or {}).get("reference") or "(none)")
                return False
            if held is True:
                # It did NOT land. The marker goes, and the close proceeds
                # exactly as any other — this is the only branch that may.
                meta = dict(trade.metadata or {})
                meta.pop("close_in_doubt", None)
                meta["close_in_doubt_resolved"] = "the broker still held it"
                trade.metadata = meta
                trade.save(update_fields=["metadata"])
                logger.warning("[%s_bot] %s: the in-doubt close did NOT land "
                               "— the broker still holds the position, so the "
                               "close is sent once more",
                               self.asset_class, trade.symbol)
            else:
                # COULD NOT ASK. Not proof of either, so nothing is sent: an
                # unresolvable doubt that sends anyway is the double-close
                # this marker exists to prevent. Said out loud once an hour,
                # because a row nobody can resolve needs a human, and an
                # alert every tick is an alert nobody reads.
                self._warn_close_in_doubt_unresolved(trade, doubt)
                return False

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
                except Exception as _e:
                    # IN DOUBT IS NOT REFUSED. Cancelling the legs and
                    # re-sending a close that may already be live turns a
                    # closed long into a full-size short. The row keeps its
                    # legs, carries the reference, and is left for a human
                    # and for the retry loop's own position read.
                    if getattr(_e, "in_doubt", False):
                        ref = str(getattr(_e, "reference", "") or "")
                        meta = dict(trade.metadata or {})
                        meta["close_in_doubt"] = {
                            "reference": ref,
                            "at": timezone.now().isoformat(),
                        }
                        trade.metadata = meta
                        trade.save(update_fields=["metadata"])
                        logger.error(
                            "[%s_bot] %s: the CLOSE request did not come back "
                            "— it MAY be live at the broker under reference "
                            "%s. The protective legs are untouched and "
                            "nothing is re-sent.",
                            self.asset_class, trade.symbol, ref or "(none)")
                        try:
                            from bot_program.notifications import notify_staff
                            notify_staff(
                                title=f"⚠ {trade.symbol}: a close may be live",
                                body=(f"The close of {trade.symbol} did not "
                                      f"come back. Reference {ref or '(none)'}. "
                                      f"If it filled, the position is flat at "
                                      f"the broker and this row still says "
                                      f"OPEN; if it did not, the position is "
                                      f"live with its brackets intact. Check "
                                      f"before closing it by hand — a second "
                                      f"close reverses the position."),
                                url="/positions/")
                        except Exception as e2:  # noqa: BLE001
                            logger.warning("[%s_bot] in-doubt close alert "
                                           "failed: %s", self.asset_class, e2)
                        return False
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
                        self._flag_unconfirmed_legs(
                            trade, "while clearing the way for a close retry")
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
                        # The row goes CLOSED — the exit really happened — so
                        # reaching somebody is the only thing left to do.
                        self._flag_unconfirmed_legs(
                            trade, "after the position was closed")
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

        # A pool that follows the broker's account must not open on a
        # stale reading of it. The operator asked for "the available
        # funds" — funds nobody has read for an hour are not available,
        # they are remembered. Exits and management are untouched.
        if self.cfg.mode == "live":
            from bot_program.capital_truth import tracking_freeze_reason
            frozen = tracking_freeze_reason(self.user, self.cfg)
            if frozen:
                return (False, frozen)

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
        """Propose, then execute: the bot's own entry path, unchanged.

        Split on 2026-09-12 into `propose_entry` (steps A-O: every gate and
        the bot's own final size) and `execute_entry` (steps P-T: shadow,
        order, row, notify) so the capital desk can rank a whole fleet's
        candidates BETWEEN the two. A symbol ticking through here still does
        exactly what it did before the split - the candidate is executed at
        its default size, and every skip is recorded where it always was.
        """
        cand = self.propose_entry(symbol)
        if cand is None:
            return None
        return self.execute_entry(cand)

    def propose_entry(self, symbol: str, *, pricing: str = "trade",
                      signal_stats: dict | None = None):
        """Steps A-O of the entry path: decide, price, level, size, gate.

        Returns an `EntryCandidate` - the entry this bot WOULD take, at the
        size it would take it - or None after recording the skip, exactly as
        scan_symbol always has. Nothing here submits an order or writes a
        row. The two exits that used to be a bare `return None` (the brain
        pause and the live-order exception) are recorded as BRAIN_PAUSED and
        ORDER_ERROR now, so the skip distribution stops having two blind
        spots.

        `pricing="data"` reads the ticker through the router's DATA session
        instead of the exclusive trade session. The desk's proposal pass
        walks every config's symbols before anything is executed; holding
        the one clientId that can place an order across that whole pass
        would starve the pending-close drain and the kill switch for
        minutes (see runner.run_all_asset_bots). `execute_entry` acquires
        the trade client itself, whatever this pass priced through.

        `signal_stats` is the tick-wide `calculate_signal_stats` aggregate,
        threaded to `decide` so a fleet pass computes six months of signal
        history once rather than once per symbol. None means "compute it
        yourself", which is what a single-config tick still does.
        """
        from bot_program.models import AssetBotTrade
        from bot_program.engine.broker_router import client_for_symbol
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.candidates import EntryCandidate

        # Skip if a trade for this symbol is already open (or awaiting a
        # retried close — the broker position is still live) under this config.
        if AssetBotTrade.objects.filter(
                config=self.cfg, symbol=symbol,
                status__in=("OPEN", "CLOSE_PENDING")).exists():
            return self._skip(symbol, skips.ALREADY_OPEN,
                              "a position is already on")

        # AND SKIP IF AN ORDER FOR IT MAY ALREADY BE LIVE. There is no row to
        # find — that is the whole problem — so the note lives on the config.
        # Without this the next tick sends a SECOND order: the idempotency key
        # buckets by the minute, so the broker's duplicate guard does not see
        # the first one either.
        doubt = self._in_doubt_note(symbol)
        if doubt:
            return self._skip(
                symbol, skips.ORDER_IN_DOUBT,
                f"an order under reference "
                f"{doubt.get('reference') or '(none)'} may already be live "
                f"(since {doubt.get('at')})")

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

        # Called exactly as before when no tick-wide stats were handed in,
        # so a `decide` patched or overridden with the one-argument
        # signature keeps working.
        if signal_stats is None:
            decision = self.decide(symbol)
        else:
            decision = self.decide(symbol, signal_stats=signal_stats)
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
                # Recorded, not silent: this exit was one of the two bare
                # `return None`s left on the path, so a rule the brain had
                # parked read from outside exactly like a quiet market.
                return self._skip(
                    symbol, skips.BRAIN_PAUSED,
                    f"brain pause_recommended for "
                    f"{decision.rule_name or '?'}: {why}")
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

        # The client this pass PRICES through. On the bot's own tick that is
        # the trade session, as it always was; the desk's proposal pass asks
        # for the data session so the exclusive clientId is not held across
        # a fleet-wide walk. The trade session is acquired again, by
        # execute_entry, right before an order.
        if pricing == "data":
            client = client_for_symbol(self.user, symbol, self.cfg,
                                       purpose="data")
            # THE DATA SESSION IS NOT THE MONEY GUARD, AND MUST NOT COST AN
            # ENTRY. The router hands back a PaperTrader whenever the IBKR
            # clientId for a purpose is unavailable, and the DATA id is the
            # busy one — the bar writer takes it every 600 s. Left alone,
            # the live-config guard below would read that stand-in as a
            # credential failure and refuse an entry this same config takes
            # today through its trade session: the desk's SHADOW pass would
            # quietly stop the live fleet trading, which is the one thing
            # shadow may never do. So a live config with no data session
            # prices through the client this step always used. Nothing is
            # sent from here either way, and `execute_entry` runs the real
            # guard on the client an order actually goes through
            # (2026-09-12).
            if self.cfg.mode == "live" and self._is_paper_client(client):
                logger.info("[%s_bot] %s: no live DATA session — pricing "
                            "through the trade session, as before",
                            self.asset_class, symbol)
                client = client_for_symbol(self.user, symbol, self.cfg)
        else:
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
            from bot_program.engine.broker_router import session_busy
            busy = session_busy(client)
            self._notify_paper_fallback(symbol, busy=busy)
            return self._skip(symbol, skips.PAPER_FALLBACK,
                              "the IBKR trading session is held by another "
                              "process — nothing was sent" if busy else
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
        # ── WHAT THE ROUND TRIP COSTS, MEASURED WHERE POSSIBLE ───────
        # DEFAULT_COST_BPS is an asset-class ASSUMPTION and `tk` is already in
        # hand: the venue's own quoted spread was three lines up and unread.
        # `cost_to_charge` charges the WIDER of the assumption and the
        # measurement and says which. Computed from the RAW tick and BEFORE
        # `paper_fill_price` rewrites `price`, so the spread is never divided
        # by a price that already contains half of it, and so ONE number feeds
        # the paper fill, the gate and the row — three copies of one cost is
        # how they start disagreeing.
        #
        # AND IT HAS A SECOND-ORDER EFFECT ON THE PAPER PATH, stated rather
        # than denied: the adversely-adjusted `price` below is the argument to
        # both `stop_and_target` and `_size_for_entry`, so a wider measured
        # cost moves the paper stop and the paper size. That is correct and it
        # is why the haircut sits above the levels at all (see the comment
        # below) — a paper fill charged the table's half-spread where the
        # venue quotes four times that flatters precisely the expectancy the
        # promotion ladder reads to decide whether a rule may touch real
        # money. Nothing on the LIVE path is resized: there the fill is the
        # broker's own.
        from bot_program.asset_engine.risk_levels import cost_to_charge
        charge = cost_to_charge(self.cfg, symbol, tk)

        market_price = price
        paper_now = (self.cfg.mode == "paper")
        if paper_now:
            from bot_program.asset_engine.risk_levels import paper_fill_price
            price = paper_fill_price(self.cfg, symbol, price,
                                     decision.direction,
                                     cost_fraction=charge["fraction"])

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
                                             stop=sl,
                                             cost_fraction=charge["fraction"])
        if not ok:
            # The provenance travels with the refusal. /signal-surface/ has no
            # venue client and still shows the assumed table cost, so when it
            # says a setup clears its costs and the bot refuses it, the
            # refusal has to say the venue quoted wider than the table.
            logger.info("[%s_bot] skipping %s — %s (%s)",
                        self.asset_class, symbol, cost_reason, charge["note"])
            return self._skip(symbol, skips.COST_FILTER,
                              f"{cost_reason} — {charge['note']}")

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
        inst = None
        try:
            from instruments.models import Instrument
            from portfolio.risk_gate import correlation_state
            inst = Instrument.objects.filter(symbol=symbol).first()
            corr = correlation_state(self.user, inst)
        except Exception as e:  # noqa: BLE001 — see above
            logger.warning("[%s_bot] correlation taper unavailable for %s: "
                           "%s — sizing untapered", self.asset_class, symbol, e)
            corr = {"scale": 1.0, "reason": ""}
        if corr["scale"] < 1.0:
            qty *= float(corr["scale"])
            logger.info("[%s_bot] %s correlation taper: %s",
                        self.asset_class, symbol, corr["reason"])

        qty = self._round_qty(qty, price)

        # Steps M-O: the ceiling, the single-position cap, the duplicate and
        # theme gates - on the bot's own final size. execute_entry runs the
        # same judgement again on the size actually sent.
        if not self._judge_final_size(symbol, qty=qty, price=price, sl=sl,
                                      decision=decision, sizing=sizing):
            return None

        # ── The candidate: everything decided, nothing sent ──────────────
        # The horizon the desk grades a displaced candidate over. The
        # config's time stop is the honest bound; 0.0 means "off" and a
        # counterfactual with no bound would never resolve.
        try:
            from bot_program.asset_engine.candidates import (
                DEFAULT_HORIZON_HOURS,
            )
            horizon = (float(self.cfg.time_stop_setting()["hours"] or 0.0)
                       or DEFAULT_HORIZON_HOURS)
        except Exception:  # noqa: BLE001 — a horizon must never cost an entry
            horizon = 168.0
        # The same value_per_unit the sizer used and the ceiling above
        # re-derived, so risk_dollars_default is the number the ceiling
        # judged, not a second opinion of it.
        vpu = float(sizing.get("value_per_unit", 1.0))
        per_unit_risk = abs(float(price) - float(sl)) * vpu
        return EntryCandidate(
            bot=self, cfg_id=self.cfg.id, user_id=self.user.id,
            symbol=symbol, instrument_id=getattr(inst, "id", None),
            asset_class=self.asset_class,
            # The venue the row would be filed under - the same rule
            # execute_entry applies to AssetBotTrade.paper.
            venue=("paper" if (self.cfg.mode == "paper"
                               or bool(stage["force_paper"])) else "live"),
            decision=decision, price=float(price),
            market_price=float(market_price),
            stop=float(sl), target=float(tp), level_meta=dict(level_meta),
            cost_reason=cost_reason, cost=dict(charge),
            stage=dict(stage), sizing=dict(sizing),
            qty_default=float(qty), per_unit_risk=per_unit_risk,
            risk_dollars_default=float(qty) * per_unit_risk,
            notional_default=float(qty) * float(price) * vpu,
            value_per_unit=vpu, corr_scale=float(corr.get("scale", 1.0)),
            horizon_hours=horizon,
        )

    def _judge_final_size(self, symbol: str, *, qty: float, price: float,
                          sl: float, decision, sizing: dict) -> bool:
        """Steps M-O on a FINAL quantity: True when it may go to the book.

        Records the skip and returns False otherwise. Shared by
        propose_entry (on the bot's own size) and execute_entry (on that
        size times the desk's multiplier), because every size multiplier
        that exists must sit BEFORE these checks: anything applied after
        them is a quantity nothing judged, and a multiplier past
        MAX_RISK_FRACTION is refused here rather than clamped.
        """
        from bot_program.asset_engine import skips

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
            self._skip(symbol, skips.ERROR, f"risk ceiling: {e}")
            return False
        # The 1e-9 slack is for float noise at exactly the cap, not
        # tolerance — the same slack the manual path uses.
        if (risk_ceiling > 0 and per_unit_risk > 0
                and realised_risk > risk_ceiling + 1e-9):
            logger.warning(
                "[%s_bot] %s REFUSED: %.4f units risk $%.2f, past the $%.2f "
                "ceiling (%.1f%% of the pool)", self.asset_class, symbol,
                qty, realised_risk, risk_ceiling, MAX_RISK_FRACTION * 100)
            self._skip(
                symbol, skips.GATE_BLOCKED,
                f"sized to ${realised_risk:,.2f} of risk, past the "
                f"${risk_ceiling:,.2f} ceiling "
                f"({MAX_RISK_FRACTION * 100:.1f}% of the bot pool) — the "
                f"allocator lane scaled past the cap")
            return False

        if qty <= 0:
            logger.info("[%s_bot] %s sized to zero (risk budget %.2f%% of "
                        "%s, stop %.3f%% away) — skipping", self.asset_class,
                        symbol, sizing["risk_fraction"] * 100, self.cfg.capital,
                        abs(price - sl) / price * 100 if price else 0)
            self._skip(
                symbol, skips.SIZED_TO_ZERO,
                f"risk budget {sizing['risk_fraction'] * 100:.2f}% of "
                f"{self.cfg.capital} is below one tradeable unit")
            return False

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
            self._skip(symbol, skips.GATE_BLOCKED, cap["reason"])
            return False

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
            self._skip(symbol, skips.GATE_BLOCKED, dup["reason"])
            return False
        theme = theme_state(self.user, symbol=symbol,
                            side=decision.direction,
                            asset_class=self.asset_class)
        if not theme["ok"]:
            logger.info("[%s_bot] %s refused by the theme-leg cap: %s",
                        self.asset_class, symbol, theme["reason"])
            self._skip(symbol, skips.GATE_BLOCKED, theme["reason"])
            return False
        return True

    def execute_entry(self, cand, *, size_mult: float = 1.0) -> Optional[dict]:
        """Steps P-T: re-judge the size, then shadow / order / row / notify.

        `cand` is what propose_entry returned. `size_mult` is the desk's
        multiplier, never above 1.0 by doctrine (caps only ever tighten),
        applied to the bot's own final size and then judged AGAIN by the
        MAX_RISK_FRACTION arithmetic, the single-position cap and the
        duplicate/theme gates. Again, because the book may have moved since
        the proposal - duplicate_state and theme_state read the live rows at
        call time and see this tick's earlier fills - and because a size
        nothing judged must never reach a broker. A multiplier that pushes
        past the ceiling is refused there exactly as the allocator lane is,
        not clamped.

        Acquires the trade client itself: an order goes through the
        exclusive session whatever session the proposal priced through, and
        the money-safety guard against a PaperTrader fallback runs on THIS
        client, which is the one that matters.
        """
        from bot_program.engine.broker_router import client_for_symbol
        from bot_program.asset_engine import skips

        symbol = cand.symbol
        decision = cand.decision
        price = float(cand.price)
        market_price = float(cand.market_price)
        paper_now = (self.cfg.mode == "paper")
        sl, tp = float(cand.stop), float(cand.target)
        level_meta, cost_reason = cand.level_meta, cand.cost_reason
        stage, sizing = cand.stage, cand.sizing

        # The multiplier lands BEFORE rounding and BEFORE the judgement, so
        # the quantity judged is the quantity sent. At 1.0 this is the
        # bot's own size rounded a second time, which every _round_qty is
        # idempotent under (round-to-6, floor-to-whole, snap-to-100).
        qty = self._round_qty(float(cand.qty_default) * float(size_mult),
                              price)
        if not self._judge_final_size(symbol, qty=qty, price=price, sl=sl,
                                      decision=decision, sizing=sizing):
            return None

        # Shadow mode: everything is computed, nothing is submitted and no
        # row is written. The way to validate a change against live data
        # for 24-48h without risking money.
        from bot_program.asset_engine.safety import is_shadow, log_shadow_entry
        if is_shadow(self.cfg):
            log_shadow_entry(self.cfg, symbol, decision, price, qty)
            return self._skip(symbol, skips.SHADOW,
                              "shadow mode — computed, not submitted")

        # The TRADE client, acquired by the step that sends. On the bot's
        # own tick propose_entry already held it and this is the pooled
        # session handed straight back; on the desk's pass the proposal
        # priced through the data session and this is the first time the
        # exclusive id is asked for - after every refusal above, so a
        # candidate the book no longer has room for never takes the lease.
        client = client_for_symbol(self.user, symbol, self.cfg)

        # Money-safety, on the client an order would actually go through:
        # a live-mode config whose broker creds are missing or broken gets a
        # PaperTrader back from the router. Refuse to trade — recording a
        # paper fill as paper=False fabricates live history.
        if self.cfg.mode == "live" and self._is_paper_client(client):
            logger.error(
                "[%s_bot] LIVE config %s fell back to PaperTrader for %s "
                "(missing/invalid broker credentials?) — refusing to trade",
                self.asset_class, self.cfg.id, symbol)
            from bot_program.engine.broker_router import session_busy
            busy = session_busy(client)
            self._notify_paper_fallback(symbol, busy=busy)
            return self._skip(symbol, skips.PAPER_FALLBACK,
                              "the IBKR trading session is held by another "
                              "process — nothing was sent" if busy else
                              "live config fell back to PaperTrader")

        # A paper-STAGE rule trades on the paper venue even in a live config:
        # that is the whole point of the stage, and it is how the evidence to
        # promote it gets produced.
        paper = (self.cfg.mode == "paper") or bool(stage["force_paper"])
        order_id = ""
        entry_meta = dict(level_meta)
        entry_meta["cost_check"] = cost_reason
        # WHAT WAS CHARGED AND WHO MEASURED IT, on every entry and not only
        # the paper ones — `paper_fill_price`'s docstring gives the reason
        # ("the fraction applied is recorded on the trade, so it can be
        # retuned against real fills later") and it holds on the live path
        # too. THREE STATES a later retune must be able to tell apart: a cost
        # the venue QUOTED, a cost the table ASSUMED, and an entry that never
        # came through this path — which is the ABSENCE of these keys, not a
        # zero and not "assumed". A candidate built by hand (the desk tests do
        # it) carries no charge and writes none.
        charge = getattr(cand, "cost", None) or {}
        if charge:
            entry_meta["cost_fraction_charged"] = round(charge["fraction"], 8)
            entry_meta["cost_source"] = charge["source"]
            entry_meta["cost_note"] = charge["note"]
            if charge["spread"] is not None:
                # Written even where the measurement LOST to the table, so the
                # retune can see the venue's real spread on those rows too.
                # Absent means nothing was measured; 0.0 means a locked market.
                entry_meta["cost_spread_fraction"] = round(charge["spread"], 8)
        # Frozen at entry so a trailing stop cannot rewrite the risk
        # denominator that realized_r (and therefore sizing) depends on. This
        # is the POST-floor stop — the one actually placed.
        entry_meta["initial_stop_loss"] = round(float(sl), 8)
        if paper or paper_now:
            entry_meta["paper_fill"] = True
            entry_meta["market_price"] = round(float(market_price), 8)
        # `cost_applied_fraction` means APPLIED, so it is written only where
        # `paper_fill_price` actually ran — `paper_now` alone. On a LIVE config
        # whose rule's promotion stage forces paper, `paper` is True and no
        # haircut was taken, and the first draft of this wrote the key anyway.
        # `cost_fraction_charged` above carries the gate's number on every row,
        # so nothing is lost by being strict here. A hand-built candidate
        # carrying no charge keeps the behaviour this line always had: the
        # table, halved.
        if paper_now:
            from bot_program.asset_engine.risk_levels import (
                round_trip_cost_fraction,
            )
            applied = (charge["fraction"] if charge
                       else round_trip_cost_fraction(self.cfg, symbol))
            entry_meta["cost_applied_fraction"] = round(applied / 2.0, 8)
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
            # THE VENUE'S OWN FLOOR, BEFORE THE ORDER. `qty` above is the
            # risk the operator chose, rounded by a `_round_qty` that knows
            # the asset class and nothing about the venue. Saxo already
            # refuses a size under its MinimumTradeSize rather than upsizing
            # it — correctly, and on every tick, as an ORDER_ERROR whose
            # advice is "check the gateway". Asking here turns that into ONE
            # recorded decision carrying both numbers.
            #
            # An UNMEASURED floor refuses nothing, and the log line does not
            # claim the adapter will catch it either — that is true when the
            # instrument publishes no floor and FALSE when the reference
            # read failed, because `_details` caches the empty payload and
            # `_amount` then has nothing left to check. What arrives in that
            # case is Saxo's own rejection. Refusing here on an unmeasured
            # floor would stop a venue trading for want of a lookup.
            # qty > 0 is guaranteed: _judge_final_size above refuses a
            # non-positive size with SIZED_TO_ZERO and returns first.
            _floor, _why = self._venue_size_floor(client, symbol)
            if _floor is None:
                logger.info("[%s_bot] %s: no venue size floor measured (%s) "
                            "— an under-minimum order, if this venue has "
                            "one, will be refused at the order instead",
                            self.asset_class, symbol, _why)
            elif float(qty) < _floor - 1e-9:
                # NOT resized. Raising it to the floor is a different trade
                # and lowering it sends nothing; the house answer is to
                # refuse loudly and name both numbers.
                logger.error(
                    "[%s_bot] %s REFUSED: sized %g units from the stop, the "
                    "venue minimum here is %g (%.1fx the intended risk). "
                    "Nothing sent, nothing resized.",
                    self.asset_class, symbol, float(qty), _floor,
                    _floor / float(qty))
                self._notify_venue_min_size(symbol, qty=float(qty),
                                            floor=_floor)
                return self._skip(
                    symbol, skips.VENUE_MIN_SIZE,
                    f"sized {float(qty):g} units from the stop distance; "
                    f"this venue's minimum is {_floor:g}. Refused rather "
                    f"than traded at {_floor:g}, which is "
                    f"{_floor / float(qty):.1f}x the chosen risk")
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

                # WHICH BROKER carried this. Recorded from the client
                # that actually placed the order, because the alternative
                # — inferring it from the routing rule when the row is
                # read — is wrong for every row opened before an operator
                # moved a primary-for flag, and /treasury/ compares these
                # rows against that broker's holdings.
                # Plus the world it traded in and the handle a close needs —
                # ONE rule, shared with the TAKE TRADE lane: venue_stamps.
                entry_meta.update(self.venue_stamps(client, res))

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
                # WHAT WE ASKED FOR, before the broker's answer replaces
                # it: a partial that is still working needs both numbers.
                requested_qty = float(qty)
                if fill_qty > 0:
                    qty = fill_qty

                # Broker-side protection bookkeeping. "protected" trades are
                # skipped by bot-side SL/TP management (no double-close).
                protective_ids = [str(x) for x in
                                  (res.get("protectiveOrders") or [])]
                if protective_ids:
                    entry_meta["protective_order_ids"] = protective_ids
                # PROTECTED MEANS A STOP IS RESTING. The flag switches
                # bot-side SL/TP off completely, so stamping it on any
                # protective id let a bracket whose STOP was refused and
                # whose LIMIT was accepted claim protection it did not have —
                # and run with no stop anywhere, unmanaged. A venue that
                # names its legs must name the stop; one that reports
                # protection on the TRADE (OANDA) gives the trade handle;
                # protectedOnFill is the venue asserting it outright.
                # THE HANDLE A CLOSE MAY NEED, whatever the protection
                # turned out to be. `broker_position_id` is read by
                # _submit_close_order and by SaxoTrader.closing_fill and was
                # written NOWHERE in this repo — so on a venue where an
                # opposite order does not flatten (eToro always, Saxo under
                # FifoEndOfDay) a row whose bracket was refused had nothing
                # to close by, and the close fell through to an order that
                # OPENS a second position.
                # (`broker_position_id` is stamped above, by venue_stamps.)
                if (res.get("protectiveStopId") or res.get("protectiveTradeId")
                        or res.get("protectedOnFill")):
                    entry_meta["protected"] = True
                if protective_ids or res.get("protectedOnFill"):
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
                # What the broker did to the protection, when it did
                # something — a preset that rewrote the legs' time-in-
                # force, a refused leg, a partial fill. The row explains
                # itself instead of the operator reading it off a log.
                note = res.get("protectionNote")
                if note:
                    entry_meta["protection_note"] = str(note)[:300]
                # WORKING: the broker accepted the order and has not filled
                # it (a market order held outside regular hours, most
                # often). That is not a position. The row is booked so the
                # order has an owner — the duplicate guard sees it, the
                # kill switch can withdraw it — but it says WORKING, claims
                # no protection, and manage_positions polls the broker
                # until it fills, dies or is cancelled. Booking it as OPEN
                # at the pre-order ticker is what let reconcile strip its
                # bracket and let it fill naked.
                if res.get("working"):
                    entry_meta["entry_working"] = True
                    entry_meta["entry_working_since"] = timezone.now().isoformat()
                    entry_meta["qty_requested"] = requested_qty
                    entry_meta["protected"] = False
                    entry_meta["protected_on_fill_expected"] = bool(protective_ids)
                    if fill_qty > 0:
                        # A PARTIAL THAT IS STILL WORKING. The remainder is
                        # live at the broker, both legs were sized for the
                        # whole order, and the poll is the only thing that
                        # withdraws a remainder — booking this as a finished
                        # position left those units with no owner and a stop
                        # that would close what printed and OPEN the rest.
                        entry_meta["entry_working_partial"] = float(fill_qty)
                    else:
                        entry_meta["fill_source"] = "pending"
            except Exception as e:
                # IN DOUBT IS NOT REFUSED. The adapter marks a placement
                # whose request never came back (`in_doubt`) and carries the
                # reference the operator searches on; the engine reads the
                # marker duck-typed, exactly as it reads every other adapter
                # promise, rather than importing one venue's exception.
                if getattr(e, "in_doubt", False):
                    ref = str(getattr(e, "reference", "") or "")
                    self._remember_in_doubt(symbol, ref)
                    logger.error("[%s_bot] %s: the order request did not come "
                                 "back — it MAY be live at the broker under "
                                 "reference %s. NOT retried.",
                                 self.asset_class, symbol, ref or "(none)")
                    try:
                        from bot_program.notifications import notify_staff
                        notify_staff(
                            title=f"⚠ {symbol}: an order may be live with no row",
                            body=(f"{self.asset_class.upper()} placement for "
                                  f"{symbol} did not come back. Search the "
                                  f"broker for reference {ref or '(none)'}: if "
                                  f"that order exists, this platform has no "
                                  f"row for it and nothing is managing it. "
                                  f"{symbol} is not retried for "
                                  f"{self.IN_DOUBT_QUIET_HOURS}h."),
                            url="/positions/")
                    except Exception as e2:  # noqa: BLE001
                        logger.warning("[%s_bot] in-doubt alert failed: %s",
                                       self.asset_class, e2)
                    return self._skip(symbol, skips.ORDER_IN_DOUBT,
                                      f"reference {ref or '(none)'} may be "
                                      f"live at the broker")
                logger.error("[%s_bot] live order failed for %s: %s",
                             self.asset_class, symbol, e)
                # The other bare `return None`: an order the broker threw
                # on used to leave the same trace as no order at all.
                return self._skip(symbol, skips.ORDER_ERROR,
                                  f"live order failed: {e}")

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

        # Phase-20: notify on open — unless the entry is still WORKING at
        # the broker. "Opened" is then a claim about the future; the poll
        # announces the fill when the broker reports it.
        if entry_meta.get("entry_working"):
            logger.info("[%s_bot] %s entry is WORKING at the broker (order "
                        "%s) — booked as pending, polling for the fill",
                        self.asset_class, symbol, order_id)
        else:
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

        # Phase-27: open a tax lot for long entries — but NOT for an order
        # that has not filled. A lot is a cost basis for units the account
        # owns, and close_lots_for consumes open lots FIFO by (user, symbol,
        # class, venue) rather than by source trade: a lot minted for a
        # queued order at the pre-order ticker would be consumed by the next
        # real close, reporting a gain against shares nobody bought. The
        # lot is opened when the fill is booked (_finish_working_entry).
        if not entry_meta.get("entry_working"):
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

    # ── the venue stamps a LIVE row carries ─────────────────────────────

    @classmethod
    def venue_stamps(cls, client, res) -> dict:
        """The three marks a LIVE row carries about the venue that filled
        it — read from the CLIENT that placed the order and the FILL it
        answered, never from today's routing rule, which is wrong for every
        row opened before an operator moved a primary-for flag.

          broker              capabilities.adapter_key(client). An adapter
                              the map does not know answers "" and the key
                              is left ABSENT: a wrong carrier is worse than
                              none, because reconcile_asset.unattributable
                              would then compare the row against the wrong
                              book. A MagicMock or a subclass answers "".
          broker_env          VENUE_WORLDS[client.env]. Saxo and eToro serve
                              SIM and live from one row, so the name alone
                              cannot tell a rehearsal fill from a real one.
                              An adapter that does not say leaves the key
                              ABSENT: an unknown world is not a live one.
          broker_position_id  the handle a close may need on a venue where
                              an opposite order OPENS a second position:
                              `positionId` (eToro, on every fill) or
                              `protectiveTradeId` (OANDA, Saxo). ABSENT when
                              the fill offered neither — venue_close
                              .position_id_for then answers "" and
                              close_or_refuse refuses rather than opens.

        ONE rule for both lanes. execute_entry has written these since
        1da56db / d3c735f; the TAKE TRADE lane (manual_trade._execute)
        wrote none of them, so a hand-taken eToro row recorded no carrier,
        no handle and no world. Absent is a state: nothing here invents a
        value the client or the fill did not give. For a non-dict `res`
        nothing is stamped — the inline code used to stamp str(obj) for
        any object answering .get; no test depends on that reading.
        """
        from bot_program.engine.capabilities import adapter_key
        stamps: dict = {}
        carried_by = adapter_key(client)
        if carried_by:
            stamps["broker"] = carried_by
        world = cls.VENUE_WORLDS.get(
            str(getattr(client, "env", "") or "").lower())
        if world:
            stamps["broker_env"] = world
        fill = res if isinstance(res, dict) else {}
        pos_id = fill.get("positionId") or fill.get("protectiveTradeId")
        if pos_id:
            stamps["broker_position_id"] = str(pos_id)
        return stamps

    # ── live-mode paper-fallback guard ───────────────────────────────────

    @staticmethod
    def _is_paper_client(client) -> bool:
        from bot_program.engine.paper_trader import PaperTrader
        return isinstance(client, PaperTrader)

    # ── the venue's own size floor ──────────────────────────────────────
    #
    # `_round_qty` knows the ASSET CLASS and nothing about the venue: the
    # forex bot's 100-unit boundary is OANDA/IBKR granularity and its own
    # comment calls it tidiness, not any venue's rule. The venue is known
    # only through broker_router, and the one step holding the client an
    # order actually goes through is `execute_entry`. So the question is
    # asked there, on that client, and answered in three states.
    #
    # NOT gated by any PlatformComponent key: this rides the entry path, so
    # there is no row whose absence turns it off. And it is never the
    # enforcer — SaxoTrader._amount still raises on a too-small order at the
    # client. This only moves the refusal one step earlier so it can be
    # recorded as a DECISION with both numbers in it.
    #
    # It covers the AssetBotConfig lane only. runner.py:166-170, the legacy
    # BotConfig loop, reaches the same clients through the same
    # client_for_symbol and swallows the adapter's refusal in a bare log
    # line — no skip code, no counter, no alert. Left alone, named here.

    @staticmethod
    def _venue_size_floor(client, symbol: str) -> tuple:
        """(floor, unmeasured_reason) — the smallest size this venue takes.

        THREE STATES, and a 0 would be a fourth this must never give:

          (1000.0, "")   the venue was asked and said 1000
          (None, "...")  this adapter cannot be asked at all: it declares no
                         `size_floor` capability, because nothing it already
                         reads from the venue carries a minimum size. eToro
                         is the standing example — its search payload is
                         read for `instrumentId` and the spelling, and
                         inventing an eToro minimum here would be a number
                         with no anchor anywhere.
          (None, "...")  the venue could be asked and did not answer: no
                         session, an unknown spelling, or a payload without
                         the field.

        The last two are both None on purpose — from the entry path's point
        of view unmeasured is ONE state, and the reason string is what tells
        them apart in the log. What must never happen is either being read
        as "any size is fine", which is why this returns None and not 0.0.
        """
        from bot_program.engine.capabilities import has_capability
        if not has_capability(client, "size_floor"):
            return None, (f"{type(client).__name__} declares no size_floor "
                          f"capability: this venue publishes no minimum "
                          f"trade size that the adapter already reads")
        try:
            floor = client.min_tradable(symbol)
        except Exception as e:  # noqa: BLE001 — could not ask IS an answer
            return None, (f"min_tradable({symbol}) raised "
                          f"{type(e).__name__}: {e}")
        if floor is None:
            return None, (f"{type(client).__name__} could not state a "
                          f"minimum trade size for {symbol}")
        try:
            floor = float(floor)
        except (TypeError, ValueError):
            return None, (f"min_tradable({symbol}) answered {floor!r}, "
                          f"which is not a number")
        if floor <= 0:
            return None, (f"min_tradable({symbol}) answered {floor}: a "
                          f"floor of zero or less is not a measurement")
        return floor, ""

    def _notify_venue_min_size(self, symbol: str, *, qty: float,
                               floor: float) -> None:
        """Say it ONCE, not once per tick.

        The floor is a property of the instrument at the venue, so it will
        refuse this size on every tick until the operator changes something.
        Deduped per CONFIG per symbol per day: notify_staff and this table
        de-dupe on the title, so a title carrying only the symbol would
        silence a second pool refused on the same symbol for a day and the
        operator would fund the wrong one. Two symbols with two floors are
        two facts, and two pools with two sizes are two more. The skip
        counter keeps counting either way — the alert is the once, the
        counter is the frequency.
        """
        try:
            from datetime import timedelta as _td

            from alerts.models import Notification as _N
            title = (f"✕ {self.cfg.name} · {symbol}: the venue will not "
                     f"take this size")[:200]
            recent = _N.objects.filter(
                user=self.user, notification_type="bot", title=title,
                created_at__gte=timezone.now() - _td(hours=24),
            ).exists()
            if recent:
                return
            times = (floor / qty) if qty > 0 else 0.0
            _N.objects.create(
                user=self.user, notification_type="bot", title=title,
                body=(f"{self.asset_class} config '{self.cfg.name}' sized "
                      f"{qty:g} units of {symbol} from its stop distance. "
                      f"The venue's minimum there is {floor:g}, so nothing "
                      f"was sent — and nothing was resized: trading "
                      f"{floor:g} would be {times:.1f}x the risk this entry "
                      f"was sized for, which is a different trade. What "
                      f"raises the unit count is more capital, a higher "
                      f"extras['risk_per_trade_pct'], or a TIGHTER stop — "
                      f"widening the stop buys FEWER units and makes this "
                      f"worse. Moving the whole asset class off this venue "
                      f"on /brokers/ also works, but it moves every symbol "
                      f"in the class and an open position there would have "
                      f"its exit routed to a venue that does not hold it, "
                      f"so close those first. Said once per pool per symbol "
                      f"per day; the skip counter keeps counting."),
                url="/asset-bots/",
            )
        except Exception as e:  # noqa: BLE001 — an alert must not cost a tick
            logger.warning("[%s_bot] venue-minimum notification failed: %s",
                           self.asset_class, e)

    def _notify_paper_fallback(self, symbol: str, *, busy: bool = False):
        """Best-effort alert, deduped to at most one per config per hour.

        `busy` distinguishes the two reasons the router hands back a
        PaperTrader. A held IBKR trading session means nothing was asked of
        the broker and nothing is wrong with it; saying "missing or invalid
        credentials" there sends the operator to the HQ disconnect, which
        really would put every live path on paper.
        """
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
                        f"{self.asset_class} config '{self.cfg.name}' is in "
                        f"LIVE mode but the exclusive IBKR trading session is "
                        f"held by another process. NOTHING was sent and the "
                        f"broker is fine; the entry on {symbol} was refused "
                        f"and the next tick will try again."
                        if busy else
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

    def _notify_unmanaged_live_position(self, trade, *, busy: bool = False):
        """A REAL position is open and its manager is switched off.

        Strictly worse than the refused entry `_notify_paper_fallback`
        reports: a refused entry costs an opportunity, this carries risk with
        the thing that watches it turned off. And until now the only trace was
        a `logger.error` — the code did the right thing (refuse to manage,
        rather than stamp a row CLOSED off a PaperTrader's synthetic fill
        while the real position is still open at the broker) and told nobody
        who could act on it.

        WHAT SURVIVES AND WHAT DOES NOT is the whole content of this alert,
        because the honest answer is neither "you are fine" nor "you are
        naked". The broker-side bracket survives: protective legs have been
        GTC since 9e2bc10, so the stop and the target are still working
        orders at IBKR and they outlive the session that placed them. What
        stops is everything this platform adds on top — the time stop, the
        trailing stop, the break-even move, and the check that notices a
        protective leg has vanished. A missed 2FA push overnight is enough to
        get here, and the operator needs it within the hour rather than at
        the next morning's briefing.

        Deduped per SYMBOL, not per config: two unmanaged positions are two
        facts, and collapsing them would repeat the mistake the breaker alert
        made by keying on the config name alone.
        """
        try:
            from datetime import timedelta as _td
            from alerts.models import Notification as _N
            title = f"⚠ LIVE position unmanaged: {trade.symbol}"[:200]
            recent = _N.objects.filter(
                user=self.user, notification_type="bot", title=title,
                created_at__gte=timezone.now() - _td(hours=1),
            ).exists()
            if recent:
                return
            why = ("the exclusive IBKR trading session is held by another "
                   "process" if busy else
                   "its broker is unreachable (is the Gateway logged in? a "
                   "live account re-authenticates with 2FA most days)")
            _N.objects.create(
                user=self.user, notification_type="bot", title=title,
                body=(
                    f"A REAL {trade.symbol} position on '{self.cfg.name}' is "
                    f"OPEN and is not being managed: {why}. Its broker-side "
                    f"stop and target are GTC and still working at the "
                    f"broker. What is NOT running: the time stop, the "
                    f"trailing stop, the break-even move, and the check that "
                    f"notices a protective leg has disappeared. Nothing was "
                    f"closed and nothing was faked — the row is left OPEN on "
                    f"purpose."
                ),
                url="/asset-bots/",
            )
        except Exception as e:  # noqa: BLE001 — an alert must not break a tick
            logger.warning("[%s_bot] unmanaged-position notification failed: "
                           "%s", self.asset_class, e)

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

    def decide(self, symbol: str, *,
               signal_stats: dict | None = None) -> BotDecision:
        """Default decision: weighted vote over recent active Signal rows.

        Subclasses can override for asset-specific logic. Returns a BotDecision
        with rule_name=<top contributing rule> so Phase 5/7/8 multipliers apply.

        `signal_stats` is the output of `aggregation.signal_stats_for_tick()`,
        handed through to `weighted_consensus` so a fleet pass aggregates six
        months of signal history once. None leaves the vote exactly as it was:
        the consensus computes the aggregate itself, lazily, when a vote needs
        weighing.
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
                venue=venue, signal_stats=signal_stats)
            if verdict["direction"] == "HOLD":
                return BotDecision("HOLD", 0, [verdict["detail"]])
            side = bullish if verdict["direction"] == "BUY" else bearish
            return BotDecision(
                verdict["direction"],
                self._conviction_score(verdict, side, venue=venue,
                                       signal_stats=signal_stats),
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
                          venue: str,
                          signal_stats: dict | None = None) -> float:
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
            venue=venue, signal_stats=signal_stats)
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
