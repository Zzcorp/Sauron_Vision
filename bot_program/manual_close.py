"""Manual close — the CLOSE button's engine.

TAKE TRADE gave the operator a way in. There was no way out: a position
left the book only when the 5-minute tick hit its stop or target, or when
the kill switch flattened EVERYTHING. Wanting out of ONE position — the
thesis broke, the news landed, the spread went stupid — had no path.

This closes exactly one trade, through the SAME machinery an engine close
runs. It deliberately does not reimplement the close: it routes the same
client, marks with the same per-class hook, and hands the trade to
``AssetBot._close_trade``, which is what fires grading, the notification,
the audit entry, the tax-lot consumption, the Eye push, the paper exit
cost, and the forex/option multipliers (via each subclass's ``_trade_pnl``
override). A close path that re-derived any of those would grade the trade
differently from a stop-out on the same row — and the R-multiples of the
two would stop being comparable, which is the whole point of the ledger.

Two states this module refuses rather than papers over:

  * A LIVE trade whose broker is unreachable. ``client_for_symbol`` never
    returns None — it falls back to PaperTrader — so calling the close
    anyway gets a synthetic FILLED order back and stamps the row CLOSED
    while the position is still live at the broker. That exact defect is
    documented at asset_engine/base.py:100-110, where manage_positions
    skips the trade for the same reason. Refusing is the only honest
    answer: the operator must be told the position is still on.

  * A trade already in CLOSE_PENDING. The broker close failed and the
    retry beat task owns that row. Manual pressure there means "retry
    now", not "start a second close" — so it goes through
    ``pending_closes.retry_trade_close``, the same machinery, which asks
    the broker whether it still holds the position before sending another
    order. A second close path would send a market order into a book that
    may already be flat, i.e. open a brand-new reverse position.

  * A PAPER trade whose market is shut (2026-09-26). On Saturday
    2026-09-26 13:53 UTC this button closed #108 EURCAD and #109 GBPCAD at
    Friday's last OANDA price, re-stamped by a reconnecting stream. The
    only price a shut market has is the last one before it shut, so the
    row stays OPEN and nothing is booked until it reopens (the preview
    says so first). A LIVE trade is never asked: its venue decides.

Serialization: the row is claimed under ``select_for_update`` before any
broker call, so a double-click cannot close twice. The close itself runs
OUTSIDE that transaction for the same reason manual_trade's funding closes
do — ``_close_trade`` sends Telegram/Eye messages the moment it closes, and
holding a write lock across external HTTP is how a rollback announces a
close that never happened.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from django.utils import timezone

logger = logging.getLogger(__name__)

CLOSE_REASON = "MANUAL"

# The claim marker written into trade.metadata while a close is in flight.
# A double-click, a second tab and a retry-happy operator all arrive here.
CLAIM_KEY = "manual_close_claim"
# A claim older than this is stale — the worker that took it died between
# the claim and the broker call. Without a TTL a crashed close would make
# the position permanently unclosable from the UI, which is a worse
# failure than the double-close the claim exists to prevent.
CLAIM_TTL_SECONDS = 120


def _stale(iso: str) -> bool:
    """Whether a claim timestamp is old enough to be re-taken."""
    from django.utils.dateparse import parse_datetime
    try:
        at = parse_datetime(iso)
    except (TypeError, ValueError):
        return True
    if at is None:
        return True
    return (timezone.now() - at).total_seconds() >= CLAIM_TTL_SECONDS


def _live_broker_missing(trade, client) -> bool:
    """True when a non-paper trade routed to PaperTrader.

    The one check that separates "closed" from "believed closed". Same
    rule the tick applies in manage_positions — see the module docstring.
    """
    from bot_program.asset_engine.base import AssetBot
    return (not trade.paper) and AssetBot._is_paper_client(client)


def _bot_for(trade):
    """The AssetBot subclass that owns this trade's close hooks, or None.

    ``make_bot`` raises for an asset class with no implementation (cfd is
    selectable in the admin and has none). A trade on one of those cannot
    be marked or closed by anything, so naming the gap beats a traceback.
    """
    from bot_program.asset_engine.base import make_bot
    try:
        return make_bot(trade.config)
    except Exception as e:  # noqa: BLE001
        logger.warning("[manual-close] no engine for trade #%s: %s", trade.id, e)
        return None


def _initial_stop(trade):
    """The stop the trade OPENED with — the risk it was actually taken
    with, and therefore the only correct denominator for R.

    trade.stop_loss is the CURRENT stop and a trailing stop rewrites it;
    grading against that makes pnl and risk the same quantity and every
    trailed exit scores ~1.0R. bot_grading applies exactly this rule, so
    the number the confirm dialog promises is the number that gets booked.
    """
    raw = (trade.metadata or {}).get("initial_stop_loss")
    if raw is not None:
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    return float(trade.stop_loss) if trade.stop_loss is not None else None


def _risk_dollars(trade) -> float:
    """Initial risk in the config's base currency, scaled the same way
    bot_grading scales it — or 0 when it cannot be computed.

    The multipliers are not optional decoration: an options R is inflated
    ~100x without the contract multiplier, and a JPY stop-out grades at
    -0.0067 instead of -1.0 without the entry-time rate.
    """
    stop = _initial_stop(trade)
    entry = float(trade.entry_price or 0)
    qty = float(trade.qty or 0)
    if not stop or entry <= 0 or qty <= 0:
        return 0.0
    risk = abs(entry - stop) * qty
    if risk <= 0:
        return 0.0
    if trade.asset_class == "options":
        try:
            from bot_program.asset_engine.options_bot import option_pnl_multiplier
            risk *= float(option_pnl_multiplier(trade))
        except Exception:  # noqa: BLE001
            pass
    elif trade.asset_class == "forex":
        try:
            from bot_program.asset_engine.forex_bot import forex_usd_multiplier
            risk *= float(forex_usd_multiplier(trade))
        except Exception:  # noqa: BLE001
            pass
    return risk


#: The window and the minimum sample behind the lane's payoff sentence.
EARLY_CLOSE_LOOKBACK_DAYS = 90
EARLY_CLOSE_MIN_SAMPLE = 10
#: How long one lane's payoff is reused: a close-all previews every row.
EARLY_CLOSE_STATS_TTL = 300


def _lane_payoff(trade):
    """(lane, scorecard summary) of this trade's lane — the operator's own
    hand-taken trades or the bots — over EARLY_CLOSE_LOOKBACK_DAYS, for its
    owner, cached EARLY_CLOSE_STATS_TTL so a close-all reads it once."""
    from django.core.cache import cache

    from bot_program import scorecard
    from bot_program.manual_trade import MANUAL_RULE
    lane = "manual" if trade.rule_name == MANUAL_RULE else "bots"
    user = getattr(trade.config, "user", None)
    key = (f"scorecard:lane:{getattr(user, 'pk', 0)}:{lane}:"
           f"{EARLY_CLOSE_LOOKBACK_DAYS}")
    summary = cache.get(key)
    if summary is None:
        summary = scorecard.summarize(
            [r for r in scorecard.rows(days=EARLY_CLOSE_LOOKBACK_DAYS,
                                       user=user) if r["lane"] == lane])
        cache.set(key, summary, EARLY_CLOSE_STATS_TTL)
    return lane, summary


def early_close_advisory(trade, r_now) -> dict:
    """{warn, r, target_r, mfe, reason} — whether this close cuts a winner
    short of its own target (2026-10-02).

    The week's book: 12 of 15 winners closed by hand at +0.28R on average,
    several in one minute, against losers that ran their full -1R. A
    WARNING, never a refusal: the operator asked for the last word to stay
    theirs. It says what the position is worth now against what it was
    planned for, what it has already seen, whether it is protected, and —
    with enough closed trades behind it — what this lane's winners must
    average to pay for its losers."""
    out = {"warn": False, "r": r_now, "target_r": None, "mfe": None,
           "reason": ""}
    if r_now is None or r_now <= 0 or trade.take_profit is None:
        return out
    entry = float(trade.entry_price or 0)
    init = _initial_stop(trade)
    if not init or entry <= 0 or abs(entry - init) <= 0:
        return out
    d = 1.0 if str(trade.side).upper() == "BUY" else -1.0
    target_r = d * (float(trade.take_profit) - entry) / abs(entry - init)
    out["target_r"] = round(target_r, 2)
    care = (trade.metadata or {}).get("care") or {}
    try:
        mfe = float(care["mfe_r"]) if care.get("mfe_r") is not None else None
    except (TypeError, ValueError):
        mfe = None
    out["mfe"] = mfe
    if target_r <= r_now:
        return out
    parts = [f"Closing a winner early: {r_now:+.2f}R now, its target is "
             f"{target_r:+.2f}R."]
    if mfe is not None and mfe > r_now + 0.05:
        parts.append(f"It has already been {mfe:+.2f}R.")
    if care.get("soft_why"):
        parts.append(f"It is already protected: the platform's stop sits at "
                     f"its {care['soft_why']} level.")
    elif r_now < 1.0:
        parts.append("Position care moves its stop to break-even once it "
                     "reaches +1R.")
    try:
        lane, s = _lane_payoff(trade)
    except Exception as e:  # noqa: BLE001 — the warning must not cost the close
        logger.debug("[manual-close] no lane payoff for #%s: %s", trade.pk, e)
        lane, s = None, None
    if (s and s.get("n", 0) >= EARLY_CLOSE_MIN_SAMPLE
            and s.get("avg_win") is not None
            and s.get("needed_avg_win") is not None):
        who = "your hand-taken" if lane == "manual" else "the bots'"
        parts.append(
            f"Over {EARLY_CLOSE_LOOKBACK_DAYS} days {who} winners averaged "
            f"{s['avg_win']:+.2f}R; at a {s['win_rate'] * 100:.0f}% win rate "
            f"they must average {s['needed_avg_win']:+.2f}R to pay for the "
            f"losers.")
    parts.append("A warning, not a block: the choice is yours.")
    out.update(warn=True, reason=" ".join(parts))
    return out


def _exit_fill(trade, price: float) -> float:
    """The price the close will actually book at.

    Paper exits are charged half the round trip adversely by _close_trade;
    quoting the raw mark in the dialog and booking a worse one would make
    the promised R a number the operator never receives.
    """
    if not trade.paper:
        return price
    from bot_program.asset_engine.risk_levels import paper_fill_price
    exit_side = "SELL" if trade.side == "BUY" else "BUY"
    return float(paper_fill_price(trade.config, trade.symbol, price, exit_side))


def _market_shut_error(trade) -> str:
    """For a PAPER row whose market is shut, the refusal both the preview
    and the close say; "" otherwise (2026-09-26). A LIVE row is never
    asked: the venue decides whether its close fills."""
    if not trade.paper:
        return ""
    from bot_program.engine.paper_trader import paper_market_shut
    shut = paper_market_shut(trade.symbol, trade.asset_class)
    if not shut:
        return ""
    return (f"{trade.symbol}: {shut} — no paper exit. The position stays "
            f"OPEN and nothing was booked")


def requires_pin(trade) -> bool:
    """Whether closing THIS trade needs the trading PIN.

    Live only, and the asymmetry is deliberate. The PIN exists to stop a
    stray cursor from doing something irreversible with real money — arming
    a bot live, flattening the book. Closing REDUCES exposure, so gating
    every close would put the platform's heaviest friction on the safest
    action and, in a fast market, the seconds spent typing a PIN are what
    turns a 1R loss into a 3R one. A paper close costs a row in the
    evidence ledger; the confirm dialog with the facts is proportionate.

    A LIVE close is a different animal. It is irreversible at the broker,
    it cannot be re-entered at the same price, and the round trip is paid
    twice — so it meets the same bar the kill switch does: real money,
    no undo. Same gate, same reason.
    """
    return not bool(trade.paper)


def preview_close(user, trade) -> dict:
    """Everything the confirm popup needs, or {"error": ...}.

    Nothing is executed and nothing is claimed here — a preview that
    mutated the row would make hovering the button a trading action.
    """
    from bot_program.engine.broker_router import client_for_symbol

    from bot_program.asset_engine.base import is_entry_working
    if is_entry_working(trade):
        # Not an error: the button becomes WITHDRAW ORDER. There is no
        # position yet, so there is no mark, no P&L and no R to show — and
        # rendering an exit price for one would invent a trade.
        return {
            "trade_id": trade.id, "symbol": trade.symbol, "side": trade.side,
            "qty": float(trade.qty), "asset_class": trade.asset_class,
            "entry": float(trade.entry_price), "mark": None, "pnl": None,
            "r": None, "venue": "live" if not trade.paper else "paper",
            "pending": False, "working": True,
            "requires_pin": requires_pin(trade),
            "action": "withdraw",
            "note": (f"The entry order for {trade.symbol} is still WORKING "
                     f"at the broker — nothing has filled. Withdrawing "
                     f"cancels the order and its protective legs; no "
                     f"position is opened and nothing is graded."),
        }

    if trade.status == "CLOSE_PENDING":
        # Not an error: the button becomes RETRY CLOSE. The operator needs
        # to see that the position is still live at the broker.
        attempts = int((trade.metadata or {}).get("close_retry_attempts") or 0)
        return {
            "trade_id": trade.id, "symbol": trade.symbol, "side": trade.side,
            "qty": float(trade.qty), "asset_class": trade.asset_class,
            "entry": float(trade.entry_price), "mark": None, "pnl": None,
            "r": None, "venue": "live" if not trade.paper else "paper",
            "pending": True, "attempts": attempts,
            "requires_pin": requires_pin(trade),
            "action": "retry",
            "note": (f"This close already failed {attempts} time(s) — the "
                     f"position is STILL OPEN at the broker. Retrying asks "
                     f"the broker whether it still holds it before sending "
                     f"another order."),
        }
    if trade.status != "OPEN":
        return {"error": f"Trade #{trade.id} is {trade.status}, not open — "
                         f"nothing to close"}

    bot = _bot_for(trade)
    if bot is None:
        return {"error": f"No execution engine exists for "
                         f"{trade.asset_class} — this position cannot be "
                         f"closed from here; close it at the broker"}

    client = client_for_symbol(user, trade.symbol, trade.config)
    if _live_broker_missing(trade, client):
        return {"error": f"{trade.symbol} is a LIVE position and its broker "
                         f"is unreachable (missing or invalid credentials). "
                         f"Closing here would mark the row closed while the "
                         f"position is still open at the broker — fix the "
                         f"connection, or close it at the broker directly"}

    shut = _market_shut_error(trade)
    if shut:
        return {"error": shut, "market_shut": True}

    try:
        mark = bot._mark_price(trade, client)
    except Exception as e:  # noqa: BLE001
        logger.warning("[manual-close] mark failed for #%s: %s", trade.id, e)
        mark = None
    if mark is None or float(mark) <= 0:
        return {"error": f"No usable price mark for {trade.symbol} — closing "
                         f"now would book the exit at a price nobody quoted"}

    fill = _exit_fill(trade, float(mark))
    # the remainder at this fill plus what a scale-out banked (2026-10-04)
    pnl = float(bot._realised_pnl(trade, Decimal(str(fill))))
    risk = _risk_dollars(trade)
    r_now = round(pnl / risk, 2) if risk > 0 else None
    return {
        "trade_id": trade.id, "symbol": trade.symbol, "side": trade.side,
        "qty": float(trade.qty), "asset_class": trade.asset_class,
        "entry": float(trade.entry_price),
        "mark": round(float(mark), 8),
        "exit": round(fill, 8),
        "stop": float(trade.stop_loss) if trade.stop_loss is not None else None,
        "initial_stop": _initial_stop(trade),
        "pnl": round(pnl, 2),
        # An unmeasurable R renders as an em-dash upstream, never as 0.0 —
        # a legacy row with no initial stop has no risk denominator, and
        # "0.0R" would read as a scratch trade.
        "r": r_now,
        "venue": "paper" if trade.paper else "live",
        "requires_pin": requires_pin(trade),
        "pending": False,
        "action": "close",
        # Whether this cuts a winner short of its target — a warning the
        # dialog shows above the button, never a refusal.
        "early_close": early_close_advisory(trade, r_now),
    }


def _claim(user, trade_pk):
    """Take the close claim on one closeable row, or say why not.

    Returns (trade, None) or (None, error). Everything that decides
    whether a close may start is re-read INSIDE the lock: the cheap
    preview above is a courtesy for the dialog, not a gate.
    """
    from django.db import transaction
    from bot_program.models import AssetBotTrade

    with transaction.atomic():
        try:
            trade = (AssetBotTrade.objects
                     .select_for_update()
                     .select_related("config", "config__user")
                     .get(pk=trade_pk, config__user=user))
        except AssetBotTrade.DoesNotExist:
            return None, "not_found"
        if trade.status not in ("OPEN", "CLOSE_PENDING"):
            return None, (f"Trade #{trade.id} is {trade.status}, not open — "
                          f"nothing was closed")
        meta = dict(trade.metadata or {})
        held = meta.get(CLAIM_KEY)
        if held and not _stale(str(held)):
            return None, (f"A close for {trade.symbol} is already in "
                          f"flight — nothing was closed twice")
        meta[CLAIM_KEY] = timezone.now().isoformat()
        trade.metadata = meta
        trade.save(update_fields=["metadata"])
    return trade, None


def _release(trade_pk) -> None:
    """Drop the claim, whatever the close did.

    Re-read under the lock rather than saving the in-memory row: the close
    may have written status/reason/metadata (CLOSE_PENDING records retry
    bookkeeping), and clobbering that with a pre-close snapshot would lose
    the one field the retry task steers on.
    """
    from django.db import transaction
    from bot_program.models import AssetBotTrade
    try:
        with transaction.atomic():
            row = AssetBotTrade.objects.select_for_update().get(pk=trade_pk)
            meta = dict(row.metadata or {})
            if meta.pop(CLAIM_KEY, None) is not None:
                row.metadata = meta
                row.save(update_fields=["metadata"])
    except Exception as e:  # noqa: BLE001 — a stuck claim expires on its own
        logger.warning("[manual-close] claim release failed for #%s: %s",
                       trade_pk, e)


def execute_close(user, trade, *, pin_ok: bool = False) -> dict:
    """Close one position now. Returns {"ok": True, ...} or {"error": ...}.

    `pin_ok` is the caller's verdict on the trading PIN — the view owns
    checking it, this owns REQUIRING it, so a future caller (a bot console,
    an API) cannot forget the gate exists.
    """
    from bot_program.engine.broker_router import client_for_symbol

    def _no_pin(t):
        return {"error": f"{t.symbol} is a LIVE position — the trading PIN "
                         f"is required to close it. Nothing was closed"}

    # Checked before the claim so a forgotten PIN costs no write, and again
    # under the lock below: everything that decides whether a close may
    # start belongs on the row that was actually locked.
    if requires_pin(trade) and not pin_ok:
        return _no_pin(trade)

    trade, err = _claim(user, trade.pk)
    if err == "not_found":
        return {"error": "not_found", "not_found": True}
    if err:
        return {"error": err}

    try:
        if requires_pin(trade) and not pin_ok:
            return _no_pin(trade)

        # A failed live close already left the row here; the retry task owns
        # it and knows how to ask the broker whether the position is still on.
        if trade.status == "CLOSE_PENDING":
            return _retry_pending(user, trade)

        # An unfilled entry is withdrawn, not sold: there is no position to
        # close, and a market order here would open the reverse one.
        from bot_program.asset_engine.base import (cancel_working_entry,
                                                   is_entry_working)
        if is_entry_working(trade):
            client = client_for_symbol(user, trade.symbol, trade.config)
            if _live_broker_missing(trade, client):
                return {"error": f"{trade.symbol}'s entry order is still "
                                 f"working at the broker and the broker is "
                                 f"unreachable — nothing was withdrawn; "
                                 f"cancel the order at the broker",
                        "still_open": True}
            if cancel_working_entry(trade, client,
                                    reason=f"withdrawn by {user.username}"):
                return {"ok": True, "trade_id": trade.id,
                        "symbol": trade.symbol, "side": trade.side,
                        "qty": float(trade.qty), "exit": None, "pnl": 0.0,
                        "r": None, "outcome": "", "withdrawn": True}
            return {"error": f"{trade.symbol}'s entry order could not be "
                             f"withdrawn — it may still fill. Cancel it at "
                             f"the broker",
                    "still_open": True}

        bot = _bot_for(trade)
        if bot is None:
            return {"error": f"No execution engine exists for "
                             f"{trade.asset_class} — close this position at "
                             f"the broker"}

        client = client_for_symbol(user, trade.symbol, trade.config)
        if _live_broker_missing(trade, client):
            # The row stays OPEN. It has to: the position IS open, and a
            # CLOSED row here is the single most expensive lie the system
            # can tell — the operator stops watching a live position.
            logger.error("[manual-close] refusing LIVE close of #%s (%s): "
                         "broker unavailable (PaperTrader fallback)",
                         trade.id, trade.symbol)
            _notify_refused(user, trade)
            return {"error": f"{trade.symbol} is a LIVE position and its "
                             f"broker is unreachable — the position is still "
                             f"OPEN and was NOT closed. Fix the broker "
                             f"connection or close it at the broker",
                    "still_open": True}

        shut = _market_shut_error(trade)
        if shut:
            logger.warning("[manual-close] refusing paper close of #%s: %s",
                           trade.id, shut)
            return {"error": shut, "still_open": True, "market_shut": True}

        try:
            mark = bot._mark_price(trade, client)
        except Exception as e:  # noqa: BLE001
            logger.warning("[manual-close] mark failed for #%s: %s", trade.id, e)
            mark = None
        if mark is None or Decimal(str(mark)) <= 0:
            return {"error": f"No usable price mark for {trade.symbol} — the "
                             f"position is still OPEN rather than booked at a "
                             f"price nobody quoted",
                    "still_open": True}

        # Everything past here is the engine's own close: grading, the
        # notification, the audit entry, the tax lots, the Eye push, the
        # paper exit cost and the per-class P&L multiplier all live in
        # _close_trade, and a live failure lands in CLOSE_PENDING for the
        # retry task exactly as a bot-tick close would.
        closed = bot._close_trade(trade, Decimal(str(mark)), client,
                                  reason=CLOSE_REASON)
    finally:
        _release(trade.pk)

    trade.refresh_from_db()
    if not closed and trade.paper and trade.status == "OPEN":
        # A PAPER close the engine declined booked nothing and left the row
        # OPEN: there is no broker, no CLOSE_PENDING and no retry task for
        # it, so the live words below would be false. The one way here is
        # the market shutting (or opening) between the gate above and
        # _close_trade's own belt — a click at Friday 20:59:59 (2026-09-26).
        shut = _market_shut_error(trade)
        return {"error": shut or (f"{trade.symbol}: the paper close booked "
                                  f"nothing — the position stays OPEN"),
                "still_open": True, "market_shut": bool(shut),
                "trade_id": trade.id}
    if not closed:
        return {"error": f"The broker rejected the close for {trade.symbol}. "
                         f"The position is STILL OPEN at the broker; the row "
                         f"is CLOSE_PENDING and the retry task will keep "
                         f"trying every 5 minutes",
                "pending": True, "trade_id": trade.id}

    logger.info("[manual-close] %s closed #%s %s %s at %s (%sR)",
                user.username, trade.id, trade.side, trade.symbol,
                trade.exit_price, trade.realized_r)
    return {
        "ok": True, "trade_id": trade.id, "symbol": trade.symbol,
        "side": trade.side, "qty": float(trade.qty),
        "exit": float(trade.exit_price) if trade.exit_price is not None else None,
        "pnl": float(trade.pnl) if trade.pnl is not None else None,
        "r": trade.realized_r,
        "outcome": trade.outcome or "",
    }


def _retry_pending(user, trade) -> dict:
    """Push a CLOSE_PENDING row through the existing retry machinery.

    Not a second close path — the same function the beat task calls, so
    the broker-still-holds check, the attempt counter, the stranded-position
    alert and the give-up threshold all apply identically. Closing a
    CLOSE_PENDING row with a fresh market order instead is how a retry
    turns into a NEW naked position in the opposite direction.
    """
    from bot_program.pending_closes import retry_trade_close

    # what THIS click's pass counts is stamped at or after this moment
    asked_from = timezone.now()
    try:
        ok = retry_trade_close(trade)
    except Exception as e:  # noqa: BLE001
        logger.exception("[manual-close] retry crashed for #%s: %s", trade.id, e)
        return {"error": f"The close retry for {trade.symbol} failed: {e}. "
                         f"The position may still be open at the broker",
                "pending": True}
    trade.refresh_from_db()
    if not ok and _waiting_on_the_venues_word(trade, since=asked_from):
        # 2026-10-07 (venue_exit): nothing was refused — eToro's list no
        # longer shows the position and its order read has not answered.
        return {"error": f"eToro's position list no longer shows "
                         f"{trade.symbol} and its order read has not "
                         f"answered. Nothing was sent and nothing was "
                         f"booked; the platform asks again every 5 minutes "
                         f"and books it once eToro answers, or after an "
                         f"hour without an answer",
                "pending": True, "trade_id": trade.id}
    if not ok:
        return {"error": f"The broker still refuses to close {trade.symbol}. "
                         f"The position is STILL OPEN there; the retry task "
                         f"keeps trying every 5 minutes",
                "pending": True, "trade_id": trade.id}
    return {
        "ok": True, "trade_id": trade.id, "symbol": trade.symbol,
        "side": trade.side, "qty": float(trade.qty),
        "exit": float(trade.exit_price) if trade.exit_price is not None else None,
        "pnl": float(trade.pnl) if trade.pnl is not None else None,
        "r": trade.realized_r, "outcome": trade.outcome or "",
        "retried": True,
    }


def _waiting_on_the_venues_word(trade, *, since) -> bool:
    """THIS click's drain pass counted an unanswered ask (venue_exit.
    after_no_answer wrote venue_miss.last_at at or after `since`, taken
    just before the pass). A naive or unreadable stamp is no such ask.

    (2026-10-07, review) Not "within the last two minutes": an ask the beat
    counted on a flat list 60 s earlier made a click whose close was SENT
    and refused (the list showed the position again), or whose order read
    answered "closed", say "Nothing was sent" and "has not answered"."""
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime
    miss = (trade.metadata or {}).get("venue_miss")
    if trade.status != "CLOSE_PENDING" or not isinstance(miss, dict):
        return False
    try:
        at = parse_datetime(str(miss.get("last_at") or ""))
    except (TypeError, ValueError):
        return False
    if at is None or timezone.is_naive(at):
        return False
    return at >= since


def _notify_refused(user, trade) -> None:
    """Tell the operator out-of-band that a live close was refused.

    The dialog says it too, but a dialog is dismissed and forgotten while
    the position stays on. This is the same posture as the paper-fallback
    alert on the entry side.
    """
    try:
        from bot_program.notifications import notify_manual_close_refused
        notify_manual_close_refused(
            user, asset_class=trade.asset_class, symbol=trade.symbol,
            trade_id=trade.id)
    except Exception as e:  # noqa: BLE001
        logger.warning("[manual-close] refusal notification failed: %s", e)
