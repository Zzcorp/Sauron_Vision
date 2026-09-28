"""Main bot loop. Call `run_bot_tick(user_id)` from Celery / cron.

Phase-4 update: per-symbol broker routing. Crypto symbols route to Binance,
forex to OANDA, stocks to Alpaca. Paper mode (or missing credentials) routes
to PaperTrader. See `bot_program.engine.broker_router`.
"""
from __future__ import annotations
import logging
import re
from decimal import Decimal
from django.utils import timezone
from ..models import BotConfig, BotTrade, BinanceAccount
from .binance_client import BinanceClient
from .binance_futures_client import BinanceFuturesClient
from .paper_trader import PaperTrader
from .strategy import decide
from .risk import RiskManager
from .broker_router import client_for_symbol, broker_name_for_symbol

log = logging.getLogger(__name__)

def _client_for(user, cfg=None):
    """Legacy account-wide client selector — used for the position-management
    pass that touches existing BotTrades (which are still crypto-only today)."""
    if cfg is not None and getattr(cfg, "mode", "paper") == "paper":
        log.info("[PAPER] Paper trading mode active for %s", user.username)
        return PaperTrader(cfg)

    try:
        acct: BinanceAccount = user.binance_account
        k, s = acct.get_credentials()
        testnet = acct.testnet
        if testnet:
            log.info("[PAPER] Testnet mode — using PaperTrader for %s", user.username)
            return PaperTrader(cfg)
    except BinanceAccount.DoesNotExist:
        log.warning("[PAPER] No BinanceAccount for %s — using PaperTrader", user.username)
        return PaperTrader(cfg)

    if cfg is not None and getattr(cfg, "market_type", "spot") == "futures":
        return BinanceFuturesClient(k, s, testnet=False)
    return BinanceClient(k, s, testnet=False)

def _parse_klines(raw: list[list]) -> list[list]:
    # [openTime, open, high, low, close, volume, closeTime, ...]
    return [[float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in raw]


def _apply_risk_gate(user, symbol: str, qty: float, price: float) -> tuple[float, str]:
    """Apply the Phase-2 risk gate (correlation + decay) on top of the bot's qty.

    Phase-3: when the `feature_ai_pretrade_gate` PlatformComponent is enabled,
    the gate also calls Claude's PreTradeSanityAgent. Off by default — admin
    toggles it from the dashboard. Costs Claude tokens and adds 1–3s latency.

    Best-effort: if anything goes wrong (instrument missing, portfolio init,
    etc.) we keep the original qty and log a warning. The gate must never
    halt trading on its own malfunction — the in-place RiskManager already
    enforces hard limits.

    Returns (new_qty, reason).
    """
    try:
        from instruments.models import Instrument
        from portfolio.services import get_or_create_default_portfolio
        from portfolio.risk_gate import evaluate_proposed_trade
        from core.platform_control import is_component_enabled

        instrument = Instrument.objects.filter(symbol=symbol).first()
        if instrument is None:
            return qty, "no Instrument record for symbol — gate skipped"

        portfolio = get_or_create_default_portfolio(user=user)
        use_ai = is_component_enabled("feature_ai_pretrade_gate")
        gate = evaluate_proposed_trade(
            portfolio, instrument,
            intended_size_usd=qty * price,
            use_ai_check=use_ai,
            ai_context=None,  # admin-supplied context could plug in here
        )
        scale = float(gate.get("scale", 1.0))
        ai_tag = " ai=on" if use_ai else ""
        if scale >= 0.999:
            return qty, f"gate ok (scale=1.0{ai_tag})"
        return qty * scale, f"gate scale={scale:.2f}{ai_tag}: {' / '.join(gate.get('reasons', []))}"
    except Exception as e:
        log.warning("[risk_gate] evaluation failed for %s: %s — keeping intended qty", symbol, e)
        return qty, f"gate error: {e}"

def run_bot_tick(user_id: int):
    from django.contrib.auth.models import User
    try:
        user = User.objects.get(id=user_id)
        cfg = user.bot_config
    except Exception as e:
        log.warning("no config for user %s: %s", user_id, e); return

    if not cfg.enabled:
        log.info("bot disabled for %s", user.username); return

    rm = RiskManager(cfg)
    weights = cfg.normalized_weights()

    # 1. Manage existing positions (SL/TP) — Phase-4: route per-symbol so a
    #    forex BotTrade's SL/TP check uses OANDA, a stock BotTrade uses Alpaca.
    for t in BotTrade.objects.filter(config=cfg, status="OPEN"):
        try:
            # A PAPER row waits while its market is shut (2026-09-26): the
            # only price then is the last one before it shut. OPEN it stays.
            if t.paper:
                from .paper_trader import paper_market_shut
                shut = paper_market_shut(t.symbol)
                if shut:
                    log.info("legacy paper #%s %s: %s — no paper exit; the "
                             "row stays OPEN", t.id, t.symbol, shut)
                    continue
            sym_client = client_for_symbol(user, t.symbol, cfg)
            # A close an earlier tick left resting at the venue is looked
            # up before the row is managed again (2026-09-28): a fill
            # books the row off it, and nothing is sent over it.
            if not t.paper and _settle_working_close(t, sym_client):
                continue
            tk = sym_client.ticker(t.symbol)
            price = Decimal(tk["lastPrice"])
            if t.paper and price <= 0:
                # No usable paper price — a stale quote, or a market that
                # only just reopened: nothing to compare and nothing to
                # book. A BUY's "stop" at 0 was an exit at 0 (2026-09-26).
                log.info("legacy paper #%s %s: no usable price — no paper "
                         "exit this tick; the row stays OPEN", t.id, t.symbol)
                continue
            hit_sl = (t.side == "BUY" and price <= t.stop_loss) or (t.side == "SELL" and price >= t.stop_loss)
            hit_tp = (t.side == "BUY" and price >= t.take_profit) or (t.side == "SELL" and price <= t.take_profit)
            if hit_sl or hit_tp:
                _close(t, price, sym_client, "TP" if hit_tp else "SL")
        except Exception as e:
            log.warning("manage fail %s: %s", t.symbol, e)

    # 2. Scan universe for new entries
    ok, reason = rm.can_open_new()
    if not ok:
        log.info("no new entries: %s", reason); return

    for symbol in cfg.symbols:
        try:
            # Phase-4: route per-symbol so forex symbols hit OANDA, stocks hit
            # Alpaca, etc. Falls back to PaperTrader when creds are missing.
            sym_client = client_for_symbol(user, symbol, cfg)
            broker_name = broker_name_for_symbol(user, symbol, cfg)
            raw = sym_client.klines(symbol, interval=cfg.timeframe, limit=200)
            ohlcv = _parse_klines(raw)
            ob = sym_client.order_book(symbol, limit=50)
            d = decide(symbol, ohlcv, ob, weights,
                       entry_min=cfg.entry_score_min, exit_max=cfg.exit_score_max)
            log.info("[%s] %s broker=%s score=%.2f dir=%s",
                     user.username, symbol, broker_name, d.score, d.direction)

            if d.direction == "HOLD": continue
            # Skip duplicates
            if BotTrade.objects.filter(config=cfg, symbol=symbol, status="OPEN").exists():
                continue

            price = float(ohlcv[-1][3])
            qty = rm.position_size(price)
            if qty <= 0: continue

            qty, gate_reason = _apply_risk_gate(user, symbol, qty, price)
            log.info("[%s] %s gate: %s", user.username, symbol, gate_reason)
            if qty <= 0: continue

            sl = price * (1 - d.sl_pct/100) if d.direction == "BUY" else price * (1 + d.sl_pct/100)
            tp = price * (1 + d.tp_pct/100) if d.direction == "BUY" else price * (1 - d.tp_pct/100)

            paper = (cfg.mode == "paper")
            if paper:
                # No paper fill while the market is shut (2026-09-26).
                from .paper_trader import paper_market_shut
                shut = paper_market_shut(symbol)
                if shut:
                    log.info("legacy paper %s: %s — no paper fill",
                             symbol, shut)
                    continue
            order_id = ""
            if not paper:
                # Money-safety: live mode + router fell back to PaperTrader
                # (dead/missing creds) — refuse rather than record a paper
                # fill as a live trade.
                if isinstance(sym_client, PaperTrader):
                    log.error("LIVE bot for %s fell back to PaperTrader on %s "
                              "(missing/invalid broker credentials?) — skipping",
                              user.username, symbol)
                    continue
                # THE eToro PROOF GATE, the bots' own rule (AssetBot.
                # _etoro_entry_refusal, 2026-09-24). This loop reaches the
                # same clients through the same client_for_symbol as the
                # asset bots and the TAKE TRADE lane, so an eToro-carried
                # symbol whose class — or short — has no fill-and-close
                # proof pinned (demo or real) sends nothing from here
                # either. Keyed on the
                # router's own class (the Instrument row; no row routes as
                # crypto); a non-eToro carrier passes at the first line.
                from bot_program.asset_engine.base import AssetBot
                from bot_program.engine.broker_router import _instrument_for
                _inst = _instrument_for(symbol)
                _gate, _gate_why = AssetBot._etoro_entry_refusal(
                    sym_client, symbol, d.direction, float(qty), float(price),
                    str(_inst.asset_class) if _inst is not None else "crypto")
                if _gate:
                    log.error("legacy tick %s REFUSED (%s): %s — nothing was "
                              "sent", symbol, _gate, _gate_why)
                    continue
                # THE ACCOUNT'S HEADROOM (2026-09-26). Every eToro entry
                # needs the sync's cells — stored, fresh, read in the
                # row's world, in the pool's currency — because at 1x the
                # venue locks the FULL notional (MEASURED 2026-09-23: used
                # margin 84.8 on 84.8 of exposure). The bots' own
                # _leverage_headroom answers that for the asset bots and
                # the TAKE TRADE lane; this loop cannot ask it honestly (a
                # BotConfig names no pool currency, and the BotTrade rows
                # it books are not what _pledged_since counts), so an
                # eToro-carried order that clears the proof gate is
                # REFUSED here, never sent unchecked — reached since
                # 2026-09-26 by crypto (ETORO_PROVEN); the asset bots carry
                # eToro.
                from .capabilities import adapter_key as _ak
                if _ak(sym_client) == "etoro":
                    log.error("legacy tick %s REFUSED (leverage_refused): "
                              "this loop cannot check the eToro account's "
                              "headroom (no pool currency; its BotTrade rows "
                              "are not counted) — nothing was sent; an "
                              "asset bot carries eToro", symbol)
                    continue
                try:
                    if cfg.market_type == "futures" and hasattr(sym_client, "ensure_config"):
                        sym_client.ensure_config(symbol, cfg.leverage, cfg.margin_mode)
                    res = sym_client.market_order(symbol, d.direction, qty)
                    order_id = str(res.get("orderId", ""))
                except Exception as e:
                    log.error("live order failed %s (%s): %s", symbol, broker_name, e)
                    continue

            BotTrade.objects.create(
                config=cfg, symbol=symbol, side=d.direction,
                qty=Decimal(str(qty)), entry_price=Decimal(str(price)),
                stop_loss=Decimal(str(sl)), take_profit=Decimal(str(tp)),
                composite_score=d.score, reason=" · ".join(d.reasons),
                paper=paper, binance_order_id=order_id,
            )

            ok, reason = rm.can_open_new()
            if not ok: break
        except Exception as e:
            log.exception("scan fail %s: %s", symbol, e)

#: A `reason` column grows on every retry, and a row an operator leaves
#: alone for a week must not grow it without bound. The tail is what matters.
_REASON_MAX = 2000


#: The note `_close` leaves on `reason` for a close the venue accepted and
#: has not printed, and the notes that retire it. BotTrade carries no
#: metadata column and no CLOSE_PENDING state (9eb827f declined both: OPEN
#: already means "still managed"), so the resting order's id lives in the
#: one column this schema keeps provenance in, in a shape that can be read
#: back. The last such note is in force until a later note says the order
#: was withdrawn, died, or the row closed.
_WORKING_CLOSE_RE = re.compile(
    r"close working:(\S+) \(order (\S+) resting at (\S+)\)")
_WORKING_CLOSE_RETIRED = ("close withdrawn:", "close cancelled:", "closed:")


def _resting_note(text: str) -> str:
    """The `close working:` note still in force in `text`, or ""."""
    found = ""
    for note in (text or "").split(" | "):
        # A row whose reason started empty carries a leading "| ".
        note = note.strip().lstrip("|").strip()
        if _WORKING_CLOSE_RE.match(note):
            found = note
        elif note.startswith(_WORKING_CLOSE_RETIRED):
            found = ""
    return found


def _working_close(trade):
    """(intent, order id) of the close still resting at the venue, or None.

    The id is "" when the venue reported none — resting, but neither
    pollable nor withdrawable from here.
    """
    m = _WORKING_CLOSE_RE.match(_resting_note(trade.reason))
    if not m:
        return None
    oid = m.group(2)
    return (m.group(1), "" if oid == "?" else oid)


def _append_reason(trade, note: str) -> None:
    """Append to the one column this schema can carry provenance on.

    BotTrade has no `metadata`, so `reason` is where "was this exit measured
    or assumed" lives — the same place kill_switch._close_legacy_trade puts
    it, with the same two words.
    """
    joined = ((trade.reason or "") + f" | {note}").strip()
    if len(joined) > _REASON_MAX:
        # The cut lands on a note boundary, and the resting close's note
        # survives it: half a note cannot be read back, and a resting note
        # cut away is a retry that resends beside a live order.
        keep = _resting_note(joined)
        room = _REASON_MAX - (len(keep) + 3 if keep else 0)
        tail = joined[-room:]
        sep = tail.find(" | ")
        if sep >= 0:
            tail = tail[sep + 3:]
        joined = f"{keep} | {tail}" if keep and keep not in tail else tail
    trade.reason = joined


def _venue_name(client) -> str:
    from bot_program.engine.capabilities import adapter_key
    return adapter_key(client) or type(client).__name__


def _warn_legacy_close_failed(trade, note: str) -> None:
    """One alert per trade per day. The title IS the dedup key.

    `notify_staff` de-dupes on the exact title, truncated at 200 chars, over
    its cooldown window — so the trade id has to be in the title and early,
    or one stuck row would silence every other. The body names the kill
    switch because this schema has no per-trade close button: the operator's
    only lever on a legacy row is the emergency flatten.

    It used to promise that the retry's deterministic id makes the venue
    refuse a duplicate. IBKR refuses nothing by name (its adapter says so:
    orderRef buys traceability, not idempotency), so that sentence invited
    the operator to press the tick that doubled the position. What the
    retry actually guarantees is said instead: a close the venue is still
    working is withdrawn, and the withdrawal proved, before another is sent.
    """
    try:
        from bot_program.notifications import notify_staff
        notify_staff(
            title=(f"⚠ BotTrade #{trade.id} {trade.symbol}: close FAILED, the "
                   f"position may still be open at the broker")[:200],
            body=(f"{note} The row was left OPEN because that is the truth — "
                  f"this legacy schema has no CLOSE_PENDING state, and "
                  f"booking it CLOSED would hide a live position. There is no "
                  f"per-trade close button for a legacy row: use the "
                  f"EMERGENCY FLATTEN on /command/ (after cancelling any "
                  f"order named above at the venue — the flatten does not "
                  f"withdraw it), or close it by hand at the venue. The next "
                  f"hand-triggered tick will retry; a close the venue is "
                  f"still working is withdrawn first, and the withdrawal "
                  f"proved, before another is sent — nothing here relies on "
                  f"the venue refusing a duplicate by name, because IBKR "
                  f"does not."),
            url="/command/", cooldown_hours=24)
    except Exception as e:  # noqa: BLE001 — an alert must never cost a close
        log.warning("legacy close alert failed for #%s: %s", trade.id, e)


def _leave_open(trade, reason: str, tag: str, note: str) -> bool:
    """The row stays OPEN: said on the row, in the log and to staff.

    Returns False, for the caller to hand back.
    """
    log.error("legacy close #%s %s: %s — row left OPEN",
              trade.id, trade.symbol, note)
    _append_reason(trade, f"close {tag}:{reason} ({note})")
    trade.save(update_fields=["reason"])
    _warn_legacy_close_failed(trade, note[:1].upper() + note[1:] + ".")
    return False


def _book_closed(trade, exit_price: Decimal, note: str, reason: str) -> bool:
    """Write the exit: the only writer of CLOSED on this lane. True."""
    pnl = ((exit_price - trade.entry_price) * trade.qty
           if trade.side == "BUY"
           else (trade.entry_price - exit_price) * trade.qty)
    _append_reason(trade, f"closed:{reason}")
    _append_reason(trade, note)
    trade.exit_price = exit_price
    trade.pnl_usdt = pnl
    trade.status = "CLOSED"
    trade.closed_at = timezone.now()
    trade.save()
    return True


def _read_order(st: dict, trade) -> tuple:
    """(state, filled, done) from an adapter's order_status answer."""
    from bot_program.pending_closes import dust_qty
    state = str(st.get("state") or "unknown")
    filled = Decimal(str(st.get("filled") or 0))
    qty = Decimal(str(trade.qty))
    done = state == "filled" or (filled > 0
                                 and (qty - filled) <= dust_qty("crypto"))
    return state, filled, done


def _book_off_order(trade, client, st: dict, intent: str, oid: str) -> bool:
    """Book the row CLOSED off the resting close's own fill. True."""
    px = Decimal(str(st.get("avgPrice") or 0))
    if px > 0:
        exit_price, note = px, "exit:broker"
    else:
        # A fill with no price reported books the mark and says so, as
        # `_close` does for a response with no price.
        try:
            exit_price = Decimal(str(client.ticker(trade.symbol)["lastPrice"]))
        except Exception:  # noqa: BLE001 — the entry price is certainly real
            exit_price = Decimal(0)
        if exit_price <= 0:
            exit_price = Decimal(str(trade.entry_price))
        note = "exit:mark"
    log.warning("legacy close #%s %s: the close resting as order %s FILLED "
                "— booked off it (%s); nothing sent",
                trade.id, trade.symbol, oid, note)
    return _book_closed(trade, exit_price, note, intent)


def _settle_working_close(trade, client) -> bool:
    """Look up a close an earlier tick left resting, before the row is
    managed again. True when the row was booked CLOSED off that order's
    fill and nothing else should happen to it this tick.

    The asset engine's drain does this every five minutes for a
    CLOSE_PENDING row; this lane has no drain, so the hand-triggered tick
    is the poll. An order that died with nothing filled retires the note,
    so the SL/TP test may send afresh; one still working is left to
    `_close`, which withdraws it — proved — before sending another. A row
    whose client cannot read an order is left to `_close` too, which says
    why nothing can be done.
    """
    found = _working_close(trade)
    if found is None:
        return False
    intent, oid = found
    status_fn = getattr(client, "order_status", None)
    if not oid or not callable(status_fn):
        return False
    try:
        st = status_fn(oid)
    except Exception as e:  # noqa: BLE001 — could not look is not an answer
        log.warning("legacy close #%s %s: resting order %s could not be "
                    "read (%s)", trade.id, trade.symbol, oid, e)
        return False
    if not isinstance(st, dict):
        return False
    state, filled, done = _read_order(st, trade)
    if done:
        return _book_off_order(trade, client, st, intent, oid)
    if state == "dead" and filled <= 0:
        log.warning("legacy close #%s %s: the close resting as order %s "
                    "died with nothing filled — the row is managed again",
                    trade.id, trade.symbol, oid)
        _append_reason(trade, f"close cancelled:{intent} (order {oid} died "
                              f"at {_venue_name(client)} with nothing "
                              f"filled)")
        trade.save(update_fields=["reason"])
    return False


def _withdraw_working_close(trade, client, reason: str):
    """Take the close an earlier tick left resting off the book — and PROVE
    it off — before another is sent, exactly as the retry drain does for
    an AssetBotTrade (pending_closes._cancel_working_close). Two closes
    resting for one position is how a flatten becomes a reverse position,
    and IBKR refuses nothing by name.

    Returns True when the resting close had filled and the row was booked
    CLOSED off that fill; None when it was withdrawn with nothing printed
    and a fresh close may be sent; False when nothing may be sent — the
    withdrawal could not be sent, read or proved, or part of it printed and
    this schema has nowhere to hold the residual.
    """
    intent, oid = _working_close(trade)
    venue = _venue_name(client)
    by_hand = (f"cancel order {oid or '(no id)'} at {venue} by hand before "
               f"the EMERGENCY FLATTEN, which does not withdraw it")
    if not oid:
        return _leave_open(
            trade, reason, "blocked",
            f"a close is still resting at {venue} and the venue reported no "
            f"order id for it, so it can be neither withdrawn nor polled "
            f"from here — NOTHING was sent; close it by hand at {venue}")
    cancel = getattr(client, "cancel_order", None)
    status_fn = getattr(client, "order_status", None)
    if not callable(cancel) or not callable(status_fn):
        return _leave_open(
            trade, reason, "blocked",
            f"a close is still resting at {venue} as order {oid} and "
            f"{type(client).__name__} cannot withdraw and read an order, so "
            f"NOTHING was sent; {by_hand}")
    try:
        cancel(oid)
    except Exception as e:  # noqa: BLE001 — unreachable is not withdrawn
        return _leave_open(
            trade, reason, "blocked",
            f"withdrawing the close resting at {venue} as order {oid} "
            f"failed ({e}), so NOTHING was sent; {by_hand}")
    # The READ is the proof, not the cancel's bool: what printed during
    # the withdrawal is what decides whether anything may be sent.
    try:
        st = status_fn(oid)
    except Exception as e:  # noqa: BLE001
        log.warning("legacy close #%s %s: post-withdrawal read of order %s "
                    "failed: %s", trade.id, trade.symbol, oid, e)
        st = None
    if not isinstance(st, dict):
        return _leave_open(
            trade, reason, "blocked",
            f"order {oid} could not be read at {venue} after the "
            f"withdrawal, so NOTHING was sent; {by_hand}")
    state, filled, done = _read_order(st, trade)
    if done:
        return _book_off_order(trade, client, st, intent, oid)
    if filled > 0:
        return _leave_open(
            trade, reason, "partial",
            f"order {oid} filled only {filled} of {trade.qty} before it was "
            f"withdrawn, and the remainder has nowhere to live on this "
            f"schema — NOTHING was sent; close the remainder by hand at "
            f"{venue}")
    if state == "dead":
        log.warning("legacy close #%s %s: the close resting as order %s is "
                    "withdrawn with nothing filled — sending again",
                    trade.id, trade.symbol, oid)
        _append_reason(trade, f"close withdrawn:{reason} (order {oid} taken "
                              f"off the book at {venue}, nothing filled)")
        trade.save(update_fields=["reason"])
        return None
    return _leave_open(
        trade, reason, "blocked",
        f"order {oid} still reads {state} at {venue} after the withdrawal, "
        f"so NOTHING was sent; {by_hand}")


def _submit_legacy_close(trade: BotTrade, client, reason: str):
    """Send the close THIS venue understands, with a name it can refuse twice.

    Raises on anything that is not a sent order, so the caller writes nothing.

    `close_or_refuse` is the guard the kill switch already uses on this model:
    on eToro `market_order` only ever OPENS (a SELL is sellShort) and under
    Saxo's FifoEndOfDay an opposite order leaves both lots live — and the
    router checks the Saxo/eToro/IBKR overrides BEFORE asset-class routing, so
    a legacy BotTrade really can be handed one of those clients.

    The id is deterministic and intent-scoped. `split_intent` already admits
    "TP" and "SL", which is what `reason` carries, so a retried TP close
    reuses its own id and a venue that refuses a duplicate by name refuses
    the copy — while a kill-switch flatten on the same row carries "KILL"
    and is correctly NOT refused. IBKR refuses nothing by name, which is why
    `_close` withdraws a resting close, proved, before it retries.
    """
    from bot_program.engine.idempotency import (make_client_order_id,
                                                split_intent)
    from bot_program.engine.venue_close import close_or_refuse

    if not hasattr(client, "market_order"):
        raise RuntimeError(f"{type(client).__name__} cannot place an order")
    close_side = "SELL" if trade.side == "BUY" else "BUY"
    order_id = make_client_order_id(
        config_id=int(getattr(trade, "config_id", 0) or 0),
        symbol=str(trade.symbol), signal_id=str(trade.id),
        intent=split_intent(reason))
    extra = {}
    if (trade.config.market_type == "futures"
            and hasattr(client, "ensure_config")):
        # `reduce_only` is a Binance-Futures-only kwarg, and it must survive
        # the move to close_or_refuse: without it a close into an already-flat
        # futures account opens the reverse position.
        extra["reduce_only"] = True
    return close_or_refuse(trade, client, float(trade.qty),
                           close_side=close_side, client_order_id=order_id,
                           extra=extra or None)


def _close(trade: BotTrade, price: Decimal, client, reason: str):
    """Close a BotTrade — ASKING THE VENUE FIRST, and writing only after.

    The `client` is the broker that owns the symbol: crypto uses
    Binance(Futures)Client, forex OANDATrader, stocks AlpacaTrader.

    This used to set status CLOSED, write an exit price off the MARK and
    compute the P&L BEFORE sending anything; then it sent the order inside a
    try whose except only logged, and saved CLOSED regardless. A live trade
    whose close failed was booked CLOSED at a price nobody filled, while the
    position stayed open at the venue. Nothing is written now until the order
    has been answered.

    A close the venue accepted and has not printed is neither: the row stays
    OPEN with the order's id on it, the next tick polls it, and a retry
    withdraws it — proved — before sending another (2026-09-28).

    Returns True when the row was booked CLOSED, False when it was left OPEN.
    The only caller today discards it and relies on the log and the alert;
    the value is here for callers that want to count.
    """
    from bot_program.pending_closes import (broker_exit_price,
                                            broker_filled_qty, dust_qty,
                                            is_paper_client,
                                            order_still_working)

    result = None
    if not trade.paper:
        # A LIVE ROW ROUTED TO THE SIMULATOR IS NOT A CLOSE. The router hands
        # back a PaperTrader on missing credentials, on testnet and on any
        # exception, and PaperTrader.market_order does NOT raise — it answers
        # status FILLED with an avgPrice, in exactly the shape a real fill
        # has. Booking that would stamp a simulated price on a real position
        # and mark the row CLOSED over it. The entry path in this same file
        # already refuses this on the way in.
        if is_paper_client(client):
            from bot_program.engine.broker_router import session_busy
            busy = session_busy(client)
            note = ("the broker session was held by another process, so "
                    "NOTHING was sent" if busy else
                    "the broker was unavailable (PaperTrader fallback), so "
                    "NOTHING was sent")
            log.error("legacy close #%s %s: %s", trade.id, trade.symbol, note)
            _append_reason(trade, f"close refused:{reason} ({note})")
            trade.save(update_fields=["reason"])
            _warn_legacy_close_failed(trade, note.capitalize() + ".")
            return False
        # A CLOSE LEFT RESTING BY AN EARLIER TICK IS WITHDRAWN FIRST, AND
        # THE WITHDRAWAL PROVED — what the retry drain does for an
        # AssetBotTrade — because two closes resting for one position is
        # how a flatten becomes a reverse position, and IBKR refuses
        # nothing by name.
        if _working_close(trade) is not None:
            settled = _withdraw_working_close(trade, client, reason)
            if settled is not None:
                return settled
        try:
            result = _submit_legacy_close(trade, client, reason)
        except Exception as e:  # noqa: BLE001 — a refusal is not a close
            note = f"the venue did not accept the close ({e})"
            log.error("legacy close #%s %s FAILED: %s",
                      trade.id, trade.symbol, e)
            _append_reason(trade, f"close failed:{reason} ({e})")
            trade.save(update_fields=["reason"])
            _warn_legacy_close_failed(trade, note.capitalize() + ".")
            return False

    # PREFER THE FILL THE BROKER REPORTS over the mark read a moment ago, and
    # say which was used. `broker_exit_price` is the ONE place the response
    # keys are spelled — Binance spot reports no average at all, only the
    # quote total and the base quantity whose ratio IS the average, and it
    # refuses a non-positive price, which PaperTrader answers for a symbol
    # with no Instrument row.
    exit_price = Decimal(str(price))
    note = "exit:mark"
    booked = broker_exit_price(result)
    if booked is not None and booked > 0:
        exit_price, note = booked, "exit:broker"

    # A CLOSE THE VENUE ACCEPTED AND HAS NOT PRINTED is neither a close nor
    # a partial. IBKRTrader.market_order answers status WORKING with
    # executedQty 0 and an orderId whenever nothing printed inside its
    # one-second wait — a market close held outside regular hours, on a
    # halted symbol, or simply not acked in time — and Alpaca answers
    # `accepted` the same way, as does a Binance FUTURES accept (NEW). Read
    # as "filled only 0 of N", that dropped the order id, and the alert
    # invited a retry that sent a SECOND full-size close beside the first,
    # which IBKR accepts: orderRef buys traceability, not idempotency. The
    # id goes on the row, the next tick polls it (`_settle_working_close`),
    # and a retry withdraws it — proved — before sending again.
    if order_still_working(result):
        oid = str(result.get("orderId") or "")
        venue = _venue_name(client)
        _append_reason(trade, f"close working:{reason} (order {oid or '?'} "
                              f"resting at {venue})")
        trade.save(update_fields=["reason"])
        if oid:
            told = (f"The venue accepted the close and has not filled it: it "
                    f"is resting at {venue} as order {oid}. A retry would "
                    f"send a second full-size close beside it, so the next "
                    f"hand-triggered tick withdraws that order first and "
                    f"sends nothing unless the withdrawal is proved; if it "
                    f"prints before then, the next tick books the fill. "
                    f"Cancel order {oid} at {venue} by hand before the "
                    f"EMERGENCY FLATTEN, which does not withdraw it.")
        else:
            told = (f"The venue accepted the close and has not filled it, "
                    f"and reported NO order id, so nothing here can withdraw "
                    f"or poll it: the next tick sends nothing over it. Close "
                    f"it by hand at {venue}.")
        log.error("legacy close #%s %s: %s — row left OPEN",
                  trade.id, trade.symbol, told)
        _warn_legacy_close_failed(trade, told)
        return False

    # A PARTIAL FILL HAS NOWHERE TO LIVE ON THIS SCHEMA. No CLOSE_PENDING
    # state, no residual field — so booking CLOSED would hide a live
    # remainder. The row stays OPEN and the operator is told.
    filled = broker_filled_qty(result)
    qty = Decimal(str(trade.qty))
    if filled is not None and (qty - filled) > dust_qty("crypto"):
        left = f"the broker filled only {filled} of {qty}"
        log.error("legacy close #%s %s: %s — row left OPEN",
                  trade.id, trade.symbol, left)
        _append_reason(trade, f"close partial:{reason} ({left})")
        trade.save(update_fields=["reason"])
        _warn_legacy_close_failed(trade, left.capitalize() + ".")
        return False

    return _book_closed(trade, exit_price, note, reason)
