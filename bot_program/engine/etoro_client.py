"""eToro public API trading client (2026-09-17).

Conforms to the duck-typed adapter contract in `engine/capabilities.py`,
declaring: market_data, execution, orders, brackets, account, fractional_units,
money_floor, order_caps, leverage_values — nine tiers (capabilities.py TIERS,
pinned by tests/test_etoro_client.py). The last four read the eligibility
row, MEASURED 2026-09-23 (deploy/ETORO_DEPARTURE.md §4 D2c-0): one POST per
instrument per UTC day once read; an unread row is asked again on every ask.

    ping, ticker, klines, order_book            market_data
    market_order                                execution
    modify_protective, modify_target            brackets
    net_liquidation, broker_portfolio           account
    takes_fractional_units                      fractional_units (MEASURED off the
                                                 row's unitsQuantityType: True /
                                                 False / None unread; the engine
                                                 asks only while the switch is on)
    min_notional                                money_floor (minPositionExposure,
                                                 USD; another currency raises)
    max_units_per_order, allow_open_position,   order_caps (step 2 of the entry
    eligibility_state                           gate, base._etoro_entry_refusal)
    leverage_values, max_stop_loss_pct,         leverage_values (read; the engine
    settlement_for                              judges against the LIVE list in
                                                 a later stage)
    eligibility, unit_type, requires_w8ben,     (read, not a tier on their own)
    min_stop_loss_pct, min_amount
    cancel_order, get_positions                 orders (MEASURED 2026-09-23 20:29 UTC,
                                                 demo; order_status is in no tier)
    order_status, account, balance_usdt         (used, not a tier on their own)

NOT declared, on purpose — see "What it refuses to claim" below.

WHY THIS BROKER

eToro authenticates with two LONG-LIVED keys sent as headers. No OAuth, no
token to refresh, no daily human at a phone. That is the property IBKR's
retail API withholds, and the reason the operator is moving live capital
here. It also holds the stop, the target AND a trailing stop at the broker,
so a position stays protected while this platform is down — which today's
engine only gets from OANDA and Alpaca.

THREE FACTS ABOUT THE API THAT SHAPE EVERYTHING BELOW

1. ORDERS ARE ASYNCHRONOUS. A 200 on POST /orders means "accepted for
   processing", not "filled". The fill is read by a second call,
   orders:lookup, keyed by the INTEGER orderId the acceptance carries
   ({token, orderId, referenceId} — MEASURED 2026-09-23, demo segment).
   NOT by the x-request-id this client sends: eToro echoes it as
   referenceId and keeps no copy (the v1 order read shows referenceID all
   zeros; `?referenceId=` answers 404 every time), which is how every order
   of the first demo night read PENDING/pollFailed although each filled in
   200 ms. `status` on the lookup is an OBJECT {id, name, errorCode}; only
   ids 3, 11 and 7 (D2b-i, 2026-09-23) and 4 with errorCode 720 (the floor
   refusal, BTC, same night) have met a key — the twelve-value table
   (3 and 5 fills, 4/7/8/9/10 refusals) is the public reference. This
   client polls — bounded, best-effort, the way `AlpacaTrader._await_fill`
   does — and NEVER reports an acceptance as a fill. OANDA's own history
   here is the warning: "a completely unfilled order was booked as a
   complete fill on both sides".

2. THE ENVIRONMENT SEGMENT IS NOT A RULE, IT IS A TABLE. v2 omits it for
   the real account:
       /api/v2/trading/execution/demo/orders   vs   /api/v2/trading/execution/orders
   v1 omits it for portfolio, aggregate-portfolio and the close — and WRITES
   it for pnl:
       /api/v1/trading/info/demo/portfolio     vs   /api/v1/trading/info/portfolio
       /api/v1/trading/info/demo/pnl           vs   /api/v1/trading/info/real/pnl
   This header used to claim v1 always wrote "real", and called that "encoded
   in two helpers rather than discovered in production on a real key". It was
   discovered in production on a real key: the operator's first live save
   probed a 404 on 2026-09-22, and every real-account read AND the close were
   wrong while order placement (v2) was right — a venue that would take an
   order and refuse every exit. Each entry in `_V1_INFO_REAL_SEG` and
   `_V1_EXEC_REAL_SEG` now carries the status code that measured it, and an
   unattested tail raises. Everything under /market-data/ carries no
   environment at all.

3. EVERYTHING IS KEYED ON AN INTEGER instrumentId — candles, rates,
   closing. Only order creation accepts a ticker. Ids are immutable
   (the docs: "they never change, even if a company rebrands"), so they
   are resolved once through /market-data/search and cached for the life
   of the client. An unresolvable symbol RAISES: asking for bars on a
   wrong id answers an empty list, which is indistinguishable from "no
   history" and is exactly how `market_data/bot_bars.py` documents a bot
   going blind one spelling at a time.

WHAT IT REFUSES TO CLAIM

  * `orders` — CLAIMED since D3b (2026-09-24). MEASURED 2026-09-23 20:29 UTC
    on the demo segment: an order sent off hours reads status 11
    WaitingForMarket, `DELETE /api/v3/trading/execution/demo/orders/<id>`
    answers 202 {orderId, referenceId ""}, and the lookup then reads 7
    Canceled with the margin released. `cancel_order` is LOOKUP-FIRST: it
    answers False, nothing sent, for any id the lookup cannot read (a close
    order id is findable on no read path — read once, never DELETEd), True
    only when a lookup reads 7/8/9, False on any other read after the
    DELETE, None only when a DELETE went out and no lookup answered. The
    live spelling is refused by `_seg` until measured.
  * `fills` — no closed-position history is documented anywhere. The
    close-confirmation SHAPE met a real key on 2026-09-23 (`close_position`:
    orderForClose{orderID, orderType 19, statusID 1}) and so did the close
    PROOF (`position_state`: the OPEN order's positionExecutions[0].state
    turning "closed") — but neither carries a closing price, and the close
    order id is findable on no read path. So `closing_fill` stays absent:
    the engine books the exit at its mark (exit_fill_source "mark") or,
    from reconcile, at a ticker read flagged `exit_price_inferred`. Adding
    it would also create the "fills" tier (capabilities.py) on a method
    that cannot price an exit.
  * `options` — none.
  * `leverage` as a TIER — no. The capabilities tier of that name means
    set_leverage/set_margin_type: Binance futures' per-SYMBOL venue state,
    set once before a plain order (binance_futures_client.ensure_config).
    eToro's leverage is a FIELD OF EACH ORDER BODY. This client sends 1
    unless the caller passes `leverage=`: a whole number in
    [1, LEVERAGE_MAX] rides the body as-is, anything else is refused
    before the POST (`_leverage`), and above 1 a missing stop_loss is
    refused too — from the public reference (unmeasured): "a stopLossRate
    is required when leverage is greater than 1". The fill result carries
    what the venue ECHOES (`venueStopLoss`/`venueTakeProfit` off
    positionExecutions[0], absent when the wire lacks them) and says when
    NO lookup could be read at all (`pollFailed`: every GET failed, never
    one of them). This client READS eToro's per-instrument
    `leverageValues` (`eligibility` and the accessors beside it, MEASURED
    2026-09-23, deploy/ETORO_DEPARTURE.md §4 D2c-0: once read, one POST per
    instrument per UTC day through a module cache — an unread row costs one
    POST per ask — and the LIVE list readable from a demo instance); the
    engine judges a multiplier against the LIVE list of the entry that
    carries it in a later stage, and no leveraged order has met the live
    world. One leveraged order HAS met eToro — demo, 2x, GLDM, 1 unit,
    order 383458277, FILLED 2026-09-23: asset.leverage 2, requestedAmount
    42.4 = notional / 2, marginAccountCurrency 42.39, units 1.0 untouched,
    fees 0.13 as at 1x, stop held exactly as sent.
  * an UNPROTECTED order nobody asked for — a stop_loss or take_profit that
    is present and not a price is refused before the POST (`_level`), never
    dropped; and a rates payload without a `rates` list, or a rate row
    spelled with none of bid/ask/lastExecution, raises rather than reading
    as a quiet market (`ticker`), because neither shape has met a real key.

Symbol convention: the platform's spelling is passed to /search as
`internalSymbolFull`. No renaming table exists yet because none has been
measured; the first symbol eToro spells differently will fail loudly here
rather than silently elsewhere, and that is where the table starts.
"""
from __future__ import annotations

import logging
import math
import uuid
from datetime import datetime, timezone
from typing import Optional

import requests

log = logging.getLogger(__name__)

BASE = "https://public-api.etoro.com"

#: Platform timeframe -> eToro candle interval enum.
INTERVAL_MAP = {
    "1m": "OneMinute", "5m": "FiveMinutes", "10m": "TenMinutes",
    "15m": "FifteenMinutes", "30m": "ThirtyMinutes",
    "1h": "OneHour", "4h": "FourHours", "1d": "OneDay", "1w": "OneWeek",
}
#: Seconds per interval, for the close-time column of a kline row.
INTERVAL_SECONDS = {
    "1m": 60, "5m": 300, "10m": 600, "15m": 900, "30m": 1800,
    "1h": 3600, "4h": 14400, "1d": 86400, "1w": 604800,
}
CANDLES_MAX = 1000

#: ELIGIBILITY rows (deploy/ETORO_DEPARTURE.md §4 D2c-0, MEASURED
#: 2026-09-23), one per (world, instrumentId), kept for the UTC day they
#: were read. MODULE-level on purpose: the router builds a fresh
#: EtoroTrader per call (broker_router.client_for_symbol), so an instance
#: cache would POST on every tick; config/settings.py defines no CACHES,
#: so Django's cache is the same per-process memo with more machinery.
#: Per day is a design choice — intraday drift is unmeasured. THREE
#: STATES in the value: a row dict (read), the literal ELIGIBILITY_ABSENT
#: (a 200 that listed no row for this id — not re-asked today), nothing
#: (an error — a non-200, 429 included, is asked again on EVERY ask: the
#: proposal's fractional read with the switch ON, the gate's state read
#: and the floor's min_notional read are up to three POSTs on one tick;
#: a memo or a back-off for an unread row is a later stage's).
#: (world, iid) -> (utc_date, value). Forgotten on restart. Tests clear
#: it in setUp AND tearDown (tests/test_etoro_client.py
#: _clear_eligibility, and every module where a real EtoroTrader reaches
#: it: SEARCH_AAPL hands every test the same id 1001).
_ELIGIBILITY: dict = {}
ELIGIBILITY_ABSENT = "absent"

#: Met on the wire: 3, 11, 7 (2026-09-23 D2b-i) and 4 with errorCode 720
#: (the floor refusal); the rest is the public table (5 and 9 never seen).
#: eToro order status ids (orders:lookup). Two fills, five refusals, the
#: rest pending. Mapped onto the vocabulary `asset_engine` already refuses
#: on: REJECTED / CANCELLED / EXPIRED with no fill is a skipped entry.
STATUS_FILLED = {3, 5}
STATUS_REFUSED = {4: "REJECTED", 7: "CANCELLED", 8: "EXPIRED",
                  9: "CANCELLED", 10: "REJECTED"}
STATUS_NAMES = {1: "Received", 2: "Placed", 3: "Filled", 4: "Rejected",
                5: "PartiallyFilled", 6: "PendingCancel", 7: "Canceled",
                8: "Expired", 9: "CanceledPartiallyFilled",
                10: "RejectedPartiallyFilled", 11: "WaitingForMarket",
                12: "PendingTriggeredRate"}

#: Polling for the async fill — bounded and best-effort, matching
#: AlpacaTrader._await_fill. A still-pending order is reported PENDING with
#: no quantity, never as a fill.
FILL_ATTEMPTS = 5
FILL_DELAY_S = 0.6

#: THE CLOSE PROOF, and its budget. MEASURED 2026-09-23 (demo, the 2x close,
#: order 383458277): the close order (orderType 19) is findable on no read
#: path; the proof is the OPEN order's positionExecutions[0].state turning
#: "closed", read by the OPEN orderId. During that close the lookup answered
#: HTTP 500 three times over ~6 s, then 200 "closed" at ~8 s — a 500 there
#: is transient. 5 × 2 s covers 8 s with a margin and, beside one order's
#: FILL_ATTEMPTS, stays inside the public 20/60 s lookup quota (unmeasured;
#: not hit at ≤ 18/min).
CLOSE_PROOF_ATTEMPTS = 5
CLOSE_PROOF_DELAY_S = 2.0

#: /portfolio LAGS BOTH WAYS. MEASURED 2026-09-23 (demo): the row was
#: ABSENT ~2 s after a fill (accountTotalUsedMargin already showed it) and
#: STILL PRESENT 3 s after the close (used margin already 0); present ~60 s
#: after the fill, absent ~60 s after the close. One get_positions() read
#: inside this window proves neither presence nor absence. Carried on the
#: class so the engine reads it duck-typed off the client it holds
#: (reconcile_asset.venue_lag_window); an adapter without it lags for nobody.
PORTFOLIO_LAG_S = 60

#: THE MOST THIS ADAPTER WILL EVER PUT IN AN ORDER BODY, whatever the caller
#: asks. EQUAL to asset_engine/base.MAX_ORDER_LEVERAGE and pinned equal by
#: tests/test_etoro_leverage.py — restated rather than imported because
#: engine/ does not import asset_engine/ (base.py imports this package).
#: A ceiling on what LEAVES the box, not a claim about what eToro accepts:
#: the allowed multipliers are per instrument, settlementType and direction
#: (`leverageValues`, MEASURED 2026-09-23 and read off the eligibility row
#: by `leverage_values` since 2026-09-25; the engine judges against the
#: LIVE list in a later stage). A shell caller on the
#: live key cannot send more than the engine could ever ask for.
LEVERAGE_MAX = 5


def _iso_to_ms(ts: str) -> int:
    """'2026-09-17T08:00:00Z' -> epoch ms; 0 when unreadable."""
    s = (ts or "").rstrip("Z")
    if "." in s:
        whole, frac = s.split(".", 1)
        s = whole + "." + frac[:6].ljust(6, "0")
    try:
        return int(datetime.fromisoformat(s).replace(
            tzinfo=timezone.utc).timestamp() * 1000)
    except ValueError:
        return 0


def _level(value, name: str, symbol: str, side: str):
    """A protective level for the order body, or None when the caller sent
    none — and a RAISE, before any POST, for a level that is not a price.

    `market_order` used to attach the legs under `if stop_loss:`, so a stop
    the engine computed at 0.0 was dropped SILENTLY and the order went out
    unprotected at leverage 1 — while a NEGATIVE stop, being truthy, was
    sent as stopLossRate. The routes to such a stop, most open first: the
    Take Trade lane, where an engine-derived BUY stop of 0 passes the
    wrong-side check `stop < price < target` and the cost filter is
    information, never a refusal (manual_trade); the bot lane's
    sizing.apply_stop_floor, which widens a BUY stop to entry * (1 - f/cap)
    AFTER the cost filter and before the order when an extras
    max_notional_fraction sits below the risk fraction; and stop_and_target's
    pct fallback with stop_loss_pct >= 100 (asset_models.AssetBotConfig, no
    validator, no form clean), which the bot lane's cost filter refuses
    unless extras use_cost_filter is False. None stays None: a caller that
    sent no level asked for no leg, and that is its choice.

    ValueError is what both callers already catch: asset_engine/base.py
    execute_entry's `except Exception` books it as skips.ORDER_ERROR
    ("live order failed: ..."); manual_trade returns it in the error dict.
    The message LEADS with the fact because skips.record keeps 200
    characters and why_no_trade prints 88.

    KNOWN, 2026-09-23: the Take Trade lane wraps that dict in "The order
    MAY have reached the broker" (manual_trade, the except after
    client.market_order), which is false for this refusal — nothing was
    sent. Until that except reads the refusal apart from a transport
    error, the operator is told to check the broker for an order that
    never left the box.
    """
    if value is None:
        return None
    try:
        if isinstance(value, bool):
            raise ValueError
        level = float(value)
    except (TypeError, ValueError):
        raise ValueError(
            f"eToro NOT SENT: {name} {value!r} is not a number "
            f"({symbol} {side}). The caller asked for a broker-held leg; "
            f"an order without it would be unprotected at leverage 1."
        ) from None
    if not math.isfinite(level) or level <= 0:
        raise ValueError(
            f"eToro NOT SENT: {name} {level!r} is not a price "
            f"({symbol} {side}). The caller asked for a broker-held leg; "
            f"an order without it would be unprotected at leverage 1."
        )
    return level


def _leverage(value, symbol: str, side: str) -> int:
    """The `leverage` field of the order body: 1 when the caller sent none,
    else a whole number in [1, LEVERAGE_MAX] — and a RAISE, before any
    POST, for anything else. A string, a bool, a fraction, a NaN, a zero
    or a negative is refused rather than rounded or defaulted: a multiplier
    this adapter silently replaced with 1 is a default nobody asked for.
    ValueError, as `_level` raises it, so both callers book it the same
    way (execute_entry: skips.ORDER_ERROR; manual_trade: the error dict);
    the message LEADS with the fact (skips.record keeps 200 chars,
    why_no_trade prints 88).
    """
    if value is None:
        return 1
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"eToro NOT SENT: leverage {value!r} is not a number "
            f"({symbol} {side}). Nothing here sends 1 in its place."
        )
    lev = float(value)
    if not math.isfinite(lev) or lev < 1 or lev != int(lev):
        raise ValueError(
            f"eToro NOT SENT: leverage {value!r} is not a whole number >= 1 "
            f"({symbol} {side}). eToro's multiplier is an integer and "
            f"nothing here rounds one."
        )
    if lev > LEVERAGE_MAX:
        raise ValueError(
            f"eToro NOT SENT: leverage {int(lev)} is past this adapter's "
            f"{LEVERAGE_MAX} ceiling ({symbol} {side}). The cap is on what "
            f"leaves the box; the venue refuses at the order what it will "
            f"not take."
        )
    return int(lev)


def _status_of(polled) -> tuple:
    """(status id, refusal words) off an orders:lookup payload.

    `status` is an OBJECT {id, name, errorCode} on the wire — MEASURED
    2026-09-23: {"id": 3, "name": "Filled", "errorCode": 0}, then 11
    WaitingForMarket and 7 Canceled (D2b-i), then 4 Rejected with
    errorCode 720 and an errorMessage naming the amount and the minimum
    (the floor refusal, BTC) — carried WHOLE since 2026-09-24: the amount
    and the minimum sit at the END of that message and a 120-char cut
    lost exactly them; the skip record and the row bound it (skips.record
    200, trade.reason 1000); entry_withdrawn_reason, the alert body and
    the TAKE TRADE error carry it whole. Since D3b
    the working-entry poller writes the words into
    entry_withdrawn_reason. The INT form is the suite's
    older fixture and is still read. The wire's `name` is not promoted
    over STATUS_NAMES: the only name measured agrees with the table, and a
    differing one would be a shape nobody has seen. Anything else is 0 —
    PENDING, which
    the engine books WORKING (loud, never CLOSED) — because this runs
    AFTER an accepted POST: a raise here lands in execute_entry as
    ORDER_ERROR with NO ROW for an order eToro may have filled, the worse
    of the two wrongs. The words ride `refusal` on the result, a key
    base.py reads into the ORDER_REJECTED detail. D2 writes the wire
    shape down (deploy/ETORO_DEPARTURE.md §4).
    """
    raw = (polled or {}).get("status")
    if raw is None:
        raw = (polled or {}).get("statusId")
    words = ""
    if isinstance(raw, dict):
        code, msg = raw.get("errorCode"), raw.get("errorMessage")
        if code or msg:
            words = f"errorCode {code}: {msg or ''}"
        raw = raw.get("id")
    try:
        sid = int(raw or 0)
    except (TypeError, ValueError):
        sid = 0
    return sid, words


class EtoroTrader:
    """eToro REST trading client."""

    def __init__(self, api_key: str, user_key: str, env: str = "demo",
                 timeout: float = 10.0):
        self.api_key = api_key
        self.user_key = user_key
        self.env = (env or "demo").lower()
        self.demo = self.env != "live"
        self.timeout = timeout
        self._session: Optional[requests.Session] = None
        # symbol -> instrumentId, and the reverse for reading positions back.
        self._ids: dict = {}
        self._symbols: dict = {}
        # instrumentId -> the spelling eToro itself answered on /search.
        # Kept because instrument_id accepts a LONE result of any
        # spelling; a reader (etoro_smoke) shows the mismatch instead
        # of painting the id green. No consumer reads it.
        self._venue_spelling: dict = {}

    # ── plumbing ───────────────────────────────────────────────────────────

    def _sess(self) -> requests.Session:
        if self._session is None:
            s = requests.Session()
            s.headers.update({"x-api-key": self.api_key,
                              "x-user-key": self.user_key,
                              "Content-Type": "application/json"})
            self._session = s
        return self._session

    @staticmethod
    def _rid(client_order_id: Optional[str] = None) -> str:
        """x-request-id: required on every call, and the idempotency key of
        an order. A caller's client_order_id is used when it is a UUID;
        anything else gets a fresh one and the caller's id is recorded in
        the raw payload instead."""
        if client_order_id:
            try:
                return str(uuid.UUID(str(client_order_id)))
            except ValueError:
                pass
        return str(uuid.uuid4())

    def _headers(self, rid: Optional[str] = None) -> dict:
        return {"x-request-id": rid or self._rid()}

    #: Read off the client by reconcile_asset.venue_lag_window (and through
    #: it by pending_closes.retry_trade_close); the module constant above
    #: carries the measurement. A client that declares no NUMBER here has no
    #: window — a MagicMock's attribute is not a number.
    PORTFOLIO_LAG_S = PORTFOLIO_LAG_S

    #: WHAT THE REAL ACCOUNT DOES WITH THE ENVIRONMENT SEGMENT, PER TAIL.
    #:
    #: Not a rule — a TABLE, because eToro is not consistent and a rule would
    #: be wrong for `pnl`. Every entry was MEASURED on 2026-09-22 with a live
    #: real key, read-only, each beside a known-200 control:
    #:
    #:   /info/aggregate-portfolio        200   /info/real/aggregate-portfolio  404
    #:   /info/portfolio                  200   /info/real/portfolio            404
    #:   /info/pnl                        404   /info/real/pnl                  200
    #:   /execution/market-close-orders/  405   /execution/real/market-close-*  404
    #:
    #: The 405 attests the close WITHOUT sending one: the close is a POST, so a
    #: GET cannot close anything, and Method Not Allowed proves the path exists
    #: where 404 proves it does not.
    #:
    #: DEMO writes "demo/" for every tail measured. An unlisted tail RAISES
    #: rather than composing a URL nobody has ever seen answer: this adapter's
    #: previous header called its paths "encoded ... rather than discovered in
    #: production on a real key", and they were discovered in production on a
    #: real key. A tail nobody measured is "could not ask", not "probably".
    _V1_INFO_REAL_SEG = {
        "aggregate-portfolio": "",
        "portfolio": "",
        "pnl": "real/",
    }
    _V1_EXEC_REAL_SEG = {
        "market-close-orders": "",
    }
    #: v3 execution, the order DELETE. DEMO measured 2026-09-23 20:29 UTC
    #: (/api/v3/trading/execution/demo/orders/<id> -> 202). The real
    #: spelling the public reference documents, /api/v3/trading/execution/
    #: orders/<id>, has met no key: the table is EMPTY so `_seg` raises on
    #: the real segment until it is measured and "orders": "" is added.
    _V3_EXEC_REAL_SEG: dict = {}

    def _seg(self, table: dict, key: str, tail: str) -> str:
        """The environment segment for `key`, or a raise naming the tail.

        Demo writes "demo/" for everything measured. Real reads the table,
        and an unattested tail is refused — loudly, at the call, rather than
        as a 404 nobody connects to a guess made months earlier.
        """
        if self.demo:
            return "demo/"
        try:
            return table[key]
        except KeyError:
            raise LookupError(
                f"eToro path not attested: {tail!r}. Nobody has measured "
                f"whether the real account writes the environment segment "
                f"for this endpoint, and eToro is not consistent — "
                f"/info/pnl writes it while /info/portfolio omits it. Check "
                f"api-portal.etoro.com for your tail and add it to the "
                f"table, with the status codes you measured."
            ) from None

    def _v1_info(self, tail: str) -> str:
        seg = self._seg(self._V1_INFO_REAL_SEG, tail.split("/")[0], tail)
        return f"{BASE}/api/v1/trading/info/{seg}{tail}"

    def _v1_exec(self, tail: str) -> str:
        seg = self._seg(self._V1_EXEC_REAL_SEG, tail.split("/")[0], tail)
        return f"{BASE}/api/v1/trading/execution/{seg}{tail}"

    def _v2(self, tail: str) -> str:
        seg = "demo/" if self.demo else ""
        return f"{BASE}/api/v2/trading/{seg}{tail}"

    def _v2_exec_orders(self) -> str:
        seg = "demo/" if self.demo else ""
        return f"{BASE}/api/v2/trading/execution/{seg}orders"

    def _v3_exec_order(self, order_id: str) -> str:
        """The DELETE of one order. Demo = the measured spelling; real raises
        through `_seg` (LookupError) until the real spelling is measured."""
        seg = self._seg(self._V3_EXEC_REAL_SEG, "orders", f"orders/{order_id}")
        return f"{BASE}/api/v3/trading/execution/{seg}orders/{order_id}"

    def _v2_lookup(self) -> str:
        seg = "demo/" if self.demo else ""
        return f"{BASE}/api/v2/trading/info/{seg}orders:lookup"

    def _v2_info(self, tail: str, world: str = "") -> str:
        """/api/v2/trading/info/{demo/}{tail} — the segment sits AFTER
        `info/`, as orders:lookup writes it (_v2_lookup). MEASURED
        2026-09-23 (deploy/ETORO_DEPARTURE.md §4 D2c-0): info/eligibility
        200 live, info/demo/eligibility 200 demo, and
        trading/demo/info/eligibility 404 — which is what _v2() composes,
        so _v2 is the WRONG shape for an info tail. `world` "live" /
        "demo" overrides this instance's world: the same key pair
        answers both (both worlds were measured with the operator's one
        pair) and only the LIVE lists prove anything; "" is this
        instance's own."""
        demo = self.demo if not world else (str(world).lower() == "demo")
        return f"{BASE}/api/v2/trading/info/{'demo/' if demo else ''}{tail}"

    # ── instruments (fact 3) ───────────────────────────────────────────────

    def instrument_id(self, symbol: str) -> int:
        """The immutable integer id for `symbol`, resolved once and cached.

        Raises LookupError when eToro does not know the spelling. Silently
        returning 0 would make every later call answer "nothing here",
        which reads as a quiet market and is a blind bot.
        """
        key = str(symbol).upper()
        if key in self._ids:
            return self._ids[key]
        r = self._sess().get(f"{BASE}/api/v1/market-data/search",
                             params={"internalSymbolFull": key},
                             headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        items = data if isinstance(data, list) else (
            data.get("items") or data.get("instruments") or data.get("data")
            or ([data] if data.get("instrumentId") else []))
        for it in items:
            sym = str(it.get("internalSymbolFull") or it.get("symbol")
                      or "").upper()
            iid = it.get("instrumentId") or it.get("instrumentID")
            if iid and (sym == key or len(items) == 1):
                iid = int(iid)
                self._ids[key] = iid
                self._symbols[iid] = key
                self._venue_spelling[iid] = sym
                return iid
        raise LookupError(f"eToro knows no instrument spelled {key!r}")

    def _symbol_for(self, instrument_id) -> str:
        """Reverse lookup for positions read back. Warm for every symbol
        this client resolved; a cold id is reported as its number rather
        than guessed at, and says so."""
        try:
            iid = int(instrument_id)
        except (TypeError, ValueError):
            return str(instrument_id)
        return self._symbols.get(iid, f"ETORO:{iid}")

    def _named(self, instrument_id) -> bool:
        """Can THIS client put a platform symbol on that instrument id?

        The reverse map is warm only for the symbols this instance itself
        resolved, and the router builds a fresh client for every call
        (broker_router.py:229) — so a reader that placed no order sees a
        book it cannot name. `get_positions` says so beside the name
        instead of letting `ETORO:1001` travel as though it were a symbol:
        every consumer compares that name against the platform's spelling
        and reads a miss as "the position is gone", which books a live row
        CLOSED.
        """
        try:
            return int(instrument_id) in self._symbols
        except (TypeError, ValueError):
            return False

    # ── market data ────────────────────────────────────────────────────────

    def ping(self) -> bool:
        try:
            r = self._sess().get(self._v1_info("aggregate-portfolio"),
                                 headers=self._headers(),
                                 timeout=self.timeout)
            return r.status_code == 200
        except Exception as e:  # noqa: BLE001
            log.warning("eToro ping failed: %s", e)
            return False

    def ticker(self, symbol: str) -> dict:
        """{lastPrice, symbol[, bid, ask]} — THREE STATES, never two.

          raise           could not ask: a transport/HTTP error, an unknown
                          spelling (instrument_id), a 200 whose body has no
                          `rates` list, or a rate row spelled with none of
                          bid/ask/lastExecution — shapes this adapter has
                          never seen answer, which is unmeasured, not empty.
          lastPrice "0"   the venue ANSWERED and had no rate: an empty list,
                          or a row whose believed keys are all 0/None. The
                          platform's own no-price sentinel — ibkr_client,
                          oanda_client, paper_trader and public_feed return
                          this literal and every reader tests `> 0` and
                          skips. One spelling, "0", from both branches.
          lastPrice > 0   a price, with bid/ask beside it.

        The keys `rates` and bid/ask/lastExecution are a BELIEF from the
        public reference; this GET was not among the reads measured on
        2026-09-22. Record the measured keys here the day it meets a real
        key, as _V1_INFO_REAL_SEG records its status codes.
        """
        iid = self.instrument_id(symbol)
        r = self._sess().get(f"{BASE}/api/v1/market-data/instruments/rates",
                             params={"instrumentIds": str(iid)},
                             headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data, dict) or "rates" not in data:
            # THREE STATES. A 200 whose body does not carry `rates` is not
            # "no rates" — it is a shape this adapter has never seen answer.
            # The rates endpoint was NOT among the reads measured on
            # 2026-09-22 (search, aggregate-portfolio, portfolio, real/pnl,
            # the close's 405), so the key is still a belief; read as an
            # empty list it would make every symbol a quiet market forever,
            # which is how the nested totals block hid for four commands.
            # Raise, naming what came back, as `_seg` does for an unattested
            # tail and instrument_id for an unknown spelling. Every reader
            # catches it: base.py's manage tick logs it and still runs the
            # clock exit; propose_entry skips NO_PRICE "ticker failed".
            keys = (sorted(data) if isinstance(data, dict)
                    else type(data).__name__)
            raise LookupError(
                f"eToro rates payload for {symbol!r} (id {iid}) carries no "
                f"'rates' key — got {keys}. The shape has not met a real "
                f"key; measure the GET beside a known-200 control and fix "
                f"the key before trusting a 0 here."
            )
        rates = data.get("rates")
        if rates is not None and not isinstance(rates, list):
            raise LookupError(
                f"eToro rates payload for {symbol!r} (id {iid}) carries "
                f"'rates' as {type(rates).__name__}, not a list — an "
                f"unmeasured shape; measure the GET before trusting a 0 here."
            )
        rates = rates or []
        p = rates[0] if rates else {}
        if rates and (not isinstance(p, dict)
                      or not ({"bid", "ask", "lastExecution"} & set(p))):
            # THE SAME RULE ONE LEVEL DOWN. The per-rate keys are as
            # unmeasured as the top-level one: a row spelled any other way
            # used to read `.get(...) or 0` as a quiet market with no line
            # at all — the failure the raise above exists to end.
            row = sorted(p) if isinstance(p, dict) else type(p).__name__
            raise LookupError(
                f"eToro rate row for {symbol!r} (id {iid}) carries none of "
                f"bid/ask/lastExecution — got {row}. Measure the row's keys "
                f"before trusting a 0 here."
            )
        bid = float(p.get("bid") or 0)
        ask = float(p.get("ask") or 0)
        last = float(p.get("lastExecution") or 0)
        if not last:
            last = (bid + ask) / 2 if bid and ask else (bid or ask)
        if not last:
            # THE VENUE ANSWERED: nothing — an empty list, or a row whose
            # believed keys are all 0/None. lastPrice "0" is the platform's
            # no-price sentinel: ibkr_client, oanda_client, paper_trader and
            # public_feed return this same literal, and every reader
            # (base._mark_price, propose_entry, manual_trade._mark_for,
            # pending_closes, reconcile_asset, kill_switch) tests `> 0` and
            # skips. ONE spelling from both empty branches — "0", never the
            # "0.0" str(0.0) used to give the row branch. Not None: the
            # readers call .get on the dict. Not a raise: a shut market is an
            # answer, not a failure to ask. Said with the id, because the
            # engine's own line ("no usable mark from the broker") carries
            # only the name; INFO rather than WARNING because base.py already
            # WARNs per position per tick and US stocks are shut two thirds
            # of the day.
            log.info("eToro ticker(%s): instrument %s answered 200 with no "
                     "price (%s) — reporting the platform's 0 sentinel, "
                     "which every reader skips on", symbol, iid,
                     "empty rates list" if not rates
                     else "bid/ask/lastExecution all empty")
            return {"lastPrice": "0", "symbol": symbol}
        return {"lastPrice": str(last), "symbol": symbol,
                "bid": str(bid), "ask": str(ask)}

    def klines(self, symbol: str, interval: str = "15m",
               limit: int = 200) -> list[list]:
        """Binance-style 12-element rows: [openTime, o, h, l, c, v,
        closeTime, quoteVol, trades, takerBase, takerQuote, ignore].
        Oldest first, like every other adapter. The runner reads only
        o/h/l/c/v; the tail is parity padding."""
        iid = self.instrument_id(symbol)
        enum = INTERVAL_MAP.get(interval, "FifteenMinutes")
        span_ms = INTERVAL_SECONDS.get(interval, 900) * 1000
        n = max(1, min(int(limit), CANDLES_MAX))
        r = self._sess().get(
            f"{BASE}/api/v1/market-data/instruments/{iid}/history/candles"
            f"/asc/{enum}/{n}",
            headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        data = r.json() or {}
        # MEASURED 2026-09-23 on the real key (GLDM, FourHours, 5):
        #   {"candles": [{"instrumentId": 3190,
        #                 "candles": [{close, fromDate, high, instrumentID,
        #                              low, open, volume}, ... x5],
        #                 "rangeOpen", "rangeHigh", "rangeLow", "rangeClose",
        #                 "volume"}],
        #    "interval": ...}
        # One GROUP per instrument, the bars one level down. This method
        # used to read the group as a bar: one row, close "0", for every
        # symbol — which bot_bars refused (close <= 0) WITHOUT falling back
        # to the public feed, because the venue had "answered" a row. A
        # config on eToro would have had no 4h bars at all. THREE STATES: a
        # group's inner list is the bars; a flat list of bars (the shape
        # this adapter believed before it met a key) is still read; a
        # group that carries neither is an unmeasured shape and RAISES —
        # bot_bars logs "klines failed" and then does fall back.
        groups = (data.get("candles") if isinstance(data, dict) else data) or []
        candles = []
        for g in groups:
            if isinstance(g, dict) and isinstance(g.get("candles"), list):
                candles.extend(c for c in g["candles"] if isinstance(c, dict))
            elif isinstance(g, dict) and "close" in g:
                candles.append(g)
            else:
                shape = sorted(g) if isinstance(g, dict) else type(g).__name__
                raise LookupError(
                    f"eToro candles payload for {symbol!r} (id {iid}) carries "
                    f"a row with neither a 'candles' list nor a 'close' — "
                    f"got {shape}. An unmeasured shape; measure the GET "
                    f"before trusting a bar here.")
        rows = []
        for c in candles:
            ts = _iso_to_ms(str(c.get("fromDate") or c.get("date") or ""))
            rows.append([
                ts,
                str(c.get("open", "0")), str(c.get("high", "0")),
                str(c.get("low", "0")), str(c.get("close", "0")),
                str(c.get("volume", 0)),
                ts + span_ms,
                "0", 0, "0", "0", "0",
            ])
        return rows

    def order_book(self, symbol: str, limit: int = 50) -> dict:
        """Synthetic single-level book from bid/ask — eToro exposes no
        depth on the public API. Same posture as OANDA."""
        tk = self.ticker(symbol)
        bid = float(tk.get("bid", "0") or 0)
        ask = float(tk.get("ask", "0") or 0)
        if not (bid and ask):
            return {"bids": [], "asks": []}
        n = min(limit, 20)
        return {
            "bids": [[str(round(bid * (1 - i * 0.0001), 6)), "1000000"]
                     for i in range(n)],
            "asks": [[str(round(ask * (1 + i * 0.0001), 6)), "1000000"]
                     for i in range(n)],
        }

    # ── account ────────────────────────────────────────────────────────────

    def account(self) -> dict:
        r = self._sess().get(self._v1_info("aggregate-portfolio"),
                             headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        return r.json() or {}

    #: WHERE THE MONEY IS IN THE AGGREGATE PAYLOAD. Measured 2026-09-22
    #: against a live real account: `account()` returns accountCurrency at
    #: the TOP level and every figure one level down, under `accountTotals`
    #: — accountTotalValue, accountAvailableCash, accountBalance,
    #: accountCurrentPnl, accountFrozenCash, accountTotalUsedMargin, all
    #: numeric. This adapter read the first two at the top level and found
    #: neither: the URLs were corrected in ea0bb54 and the field names were
    #: still wrong, so the sync ran clean and wrote no equity at all.
    @staticmethod
    def _totals(info: dict) -> dict:
        """The nested totals block, or {} when the payload has no such shape.

        {} rather than a raise: a caller reading a missing figure gets None
        from `.get`, which is already every caller's unmeasured answer.
        """
        if not isinstance(info, dict):
            return {}
        block = info.get("accountTotals")
        return block if isinstance(block, dict) else {}

    def margin_cells(self) -> "dict | None":
        """{"available_cash", "used_margin", "currency"} from ONE aggregate
        read, or None when the read failed. Each figure is None when the
        payload lacks its key — three states; a 0 is a measurement. The
        KEY NAMES were measured 2026-09-22 (accountAvailableCash,
        accountTotalUsedMargin under accountTotals, see the comment above
        `_totals`); their arithmetic (available + used + pnl = total) is
        the public reference's claim, unmeasured. One more GET per sync;
        nothing on an entry path calls this — the gate reads the cells."""
        try:
            info = self.account()
        except Exception as e:  # noqa: BLE001
            log.warning("eToro margin_cells failed: %s", e)
            return None
        totals = self._totals(info)

        def _num(key):
            raw = totals.get(key)
            try:
                return None if raw is None else float(raw)
            except (TypeError, ValueError):
                return None

        return {"available_cash": _num("accountAvailableCash"),
                "used_margin": _num("accountTotalUsedMargin"),
                "currency": str(info.get("accountCurrency") or "")}

    def balance_usdt(self) -> float:
        """Available cash in the ACCOUNT currency, not USDT — the name is the
        contract's, the unit is eToro's. Caller converts if it must.

        A FAILED READ ANSWERS 0.0, which cannot be told from an empty
        account. That is not a choice made here: six adapters return a bare
        float on this method and `capital_truth` reads it duck-typed, so one
        of them answering None would break the contract the other five keep.
        The consumer is honest about it — capital_truth treats a zero from a
        live broker as unmeasured, "this module cannot tell which" — so the
        gap is contained rather than corrected, and it is named here so the
        next reader meets it before they trust the number.
        """
        try:
            return float(self._totals(self.account())
                         .get("accountAvailableCash") or 0)
        except Exception as e:  # noqa: BLE001
            log.warning("eToro balance fetch failed: %s", e)
            return 0.0

    def net_liquidation(self) -> "tuple[float, str] | None":
        """(total value, currency) or None when unreadable — the same
        contract as IBKRTrader, so sync_broker_account can read it.

        The value comes from the nested totals block; the CURRENCY does not
        — eToro puts accountCurrency at the top level, and that read was
        always right.

        A zero answers None, deliberately and in step with SaxoTrader's
        identical rule: capital_truth states the reasoning, that a zero from
        a live broker cannot be told from an API answering badly. It means an
        empty account reads as unmeasured, which is this platform's
        convention and not eToro's peculiarity; changing it belongs in a
        change that moves every adapter at once.
        """
        try:
            info = self.account()
        except Exception as e:  # noqa: BLE001
            log.warning("eToro net_liquidation failed: %s", e)
            return None
        try:
            value = float(self._totals(info).get("accountTotalValue"))
        except (TypeError, ValueError):
            return None
        if value <= 0:
            return None
        return value, str(info.get("accountCurrency") or "")

    def _open_positions(self) -> list:
        r = self._sess().get(self._v1_info("portfolio"),
                             headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        data = r.json() or {}
        return (data.get("positions")
                or (data.get("clientPortfolio") or {}).get("positions")
                or [])

    def get_positions(self) -> list[dict]:
        """Open positions — Phase-33 reconciliation shape. Raises on
        transport errors so reconcile counts the broker unavailable rather
        than assuming flat (the same rule as OANDA and IBKR).

        /portfolio LAGS (MEASURED 2026-09-23, `PORTFOLIO_LAG_S`): a filled
        position is ABSENT here ~2 s after the fill and a closed one STILL
        LISTED 3 s after the close, both settled by ~60 s, while the margin
        cells (`margin_cells`) move within the same second. One read inside
        that window is not a measurement of presence or absence; the
        readers (reconcile_asset, pending_closes) hold off on it. The row
        keys are positionID / instrumentID / orderID (capital ID, measured);
        the camel spellings are read as a courtesy and have not been seen.
        """
        out = []
        for p in self._open_positions():
            qty = float(p.get("units") or 0)
            if qty == 0:
                continue
            iid = p.get("instrumentID") or p.get("instrumentId")
            row = {
                "symbol": self._symbol_for(iid),
                "qty": abs(qty),
                "side": "BUY" if p.get("isBuy", True) else "SELL",
                "position_id": str(p.get("positionID") or p.get("positionId")
                                   or ""),
            }
            if not self._named(iid):
                # THREE STATES. eToro holds this; what it is called HERE is
                # unmeasured. Not a symbol, and above all not an absence —
                # the readers that compare this name book a row CLOSED on a
                # miss.
                row["symbol_unresolved"] = True
            out.append(row)
        return out

    def broker_portfolio(self) -> "list[dict] | None":
        """Holdings as the broker values them, or None when unreadable —
        IBKRTrader's contract, for the portfolio views. Marks are not on
        the position row on eToro, so market_price is left 0 rather than
        invented; the aggregate endpoint has exposure per instrument if a
        caller needs it."""
        try:
            positions = self._open_positions()
        except Exception as e:  # noqa: BLE001
            log.warning("eToro broker_portfolio failed: %s", e)
            return None
        out = []
        for p in positions:
            qty = float(p.get("units") or 0)
            if qty == 0:
                continue
            row = {
                "symbol": self._symbol_for(p.get("instrumentID")
                                           or p.get("instrumentId")),
                "sec_type": "CFD",
                "qty": abs(qty),
                "side": "BUY" if p.get("isBuy", True) else "SELL",
                "avg_cost": float(p.get("openRate") or 0),
                "market_price": 0.0,
                "market_value": 0.0,
                "unrealized_pnl": 0.0,
                "currency": "",
            }
            # THE VENUE'S OWN MULTIPLIER, when the row carries one. MEASURED
            # 2026-09-23: the /portfolio row of the 1x order carried
            # `leverage: 1`, `units: 1.0`, `amount: 84.8` (units × openRate
            # at 1x). Absent on the wire -> absent here, never 1: /treasury/
            # prints the em dash for a row that did not say. `units` stay
            # units at any leverage (measured on the 2x ORDER: requestedUnits
            # 1.0, openingData.units 1.0; the 2x /portfolio row itself was
            # not captured — it closed before the lagging list showed it).
            lev = p.get("leverage")
            if lev is not None and not isinstance(lev, bool):
                try:
                    if float(lev) >= 1 and float(lev) == int(float(lev)):
                        row["leverage"] = int(float(lev))
                except (TypeError, ValueError):
                    pass
            out.append(row)
        return out

    # ── execution (fact 1) ─────────────────────────────────────────────────

    # ── eligibility (MEASURED 2026-09-23, deploy/ETORO_DEPARTURE.md §4 D2c-0) ──

    def _elig_key(self, symbol: str, world: str = "") -> tuple:
        """((world, instrumentId), today's UTC date) — the cache key of one
        eligibility row. `world` "" is this instance's own; an unknown
        spelling raises from instrument_id (never a 0 id)."""
        iid = self.instrument_id(symbol)
        world_name = str(world or ("demo" if self.demo else "live")).lower()
        return (world_name, iid), datetime.now(timezone.utc).date()

    def eligibility(self, symbol: str, world: str = "") -> "dict | None":
        """eToro's ELIGIBILITY row for `symbol` — the per-instrument facts
        an order is judged against (minPositionExposure, maxUnitsPerOrder,
        allowOpenPosition, unitsQuantityType, requiresW8Ben and the
        leverageConfigs list) — or None.

        MEASURED 2026-09-23 (deploy/ETORO_DEPARTURE.md §4 D2c-0), both
        worlds, the operator's one pair: POST /api/v2/trading/info/
        {demo/}eligibility, body {"instrumentIds": [id]}, 200 in both
        worlds, answer {"currency": "usd", "eligibilities": [row, ...]}
        with the row keyed on `instrumentId`. ONCE READ (or absent), ONE
        POST per (world, instrument) per UTC day through the module cache
        _ELIGIBILITY (the router builds a fresh client per call, so the
        memo cannot live on the instance); while UNREAD every ask is a
        POST — up to three on one tick (the proposal's fractional read
        with the switch ON, the gate's state read, the floor's
        min_notional read), no back-off: a memo for an unread row is a
        later stage's.

        THREE STATES behind the None: a same-day row (returned, the same
        dict each time); a 200 that listed no row for this id
        (ELIGIBILITY_ABSENT, cached for the day, None — the venue's own
        answer); an error — a non-200 (429 included) is logged, NOT
        cached and asked again on the next ask, None. A transport
        failure (requests raising from the POST) RAISES, nothing caught
        here — as every read on this client — and the engine reads the
        raise as an error (base._etoro_entry_refusal step 2,
        _venue_size_floor, _venue_fractional_units). A 200 whose body
        carries no `eligibilities` list RAISES LookupError naming its
        keys (the ticker() rule: a shape never seen answer is
        unmeasured, not empty) and caches nothing; an unknown spelling
        raises from instrument_id before any POST. `world` "live"/"demo"
        reads that world's row on any instance — the same pair answers
        both and only the LIVE lists prove anything; "" is this
        instance's own. On a hit the row's `symbol` is written to
        _venue_spelling (the NAME confirmation a lone /search result
        lacks — WHEAT -> WHEAT.FUT 97) and the body's currency rides the
        row as `_currency` (min_notional refuses any but usd), the world
        as `_world`."""
        key, today = self._elig_key(symbol, world)
        hit = _ELIGIBILITY.get(key)
        if hit is not None and hit[0] == today:
            return None if hit[1] == ELIGIBILITY_ABSENT else hit[1]
        world_name, iid = key
        r = self._sess().post(self._v2_info("eligibility", world_name),
                              json={"instrumentIds": [iid]},
                              headers=self._headers(), timeout=self.timeout)
        status = int(getattr(r, "status_code", 0) or 0)
        if status != 200:
            log.warning("eToro eligibility for %s (id %s, %s) answered %s — "
                        "not cached, asked again next tick", symbol, iid,
                        world_name, status)
            return None
        body = r.json()
        rows = body.get("eligibilities") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            keys = (sorted(body) if isinstance(body, dict)
                    else type(body).__name__)
            raise LookupError(
                f"eToro eligibility payload for {symbol!r} (id {iid}, "
                f"{world_name}) carries no 'eligibilities' list — got {keys}. "
                f"MEASURED 2026-09-23 as {{currency, eligibilities: [...]}}; "
                f"a body spelled otherwise is unmeasured, not empty, and "
                f"nothing is cached.")
        row = None
        for it in rows:
            try:
                if isinstance(it, dict) and int(it.get("instrumentId")) == iid:
                    row = dict(it)
                    break
            except (TypeError, ValueError):
                continue
        if row is None:
            log.warning("eToro eligibility (%s) lists no row for %s (id %s) "
                        "— ABSENT for the rest of the UTC day", world_name,
                        symbol, iid)
            _ELIGIBILITY[key] = (today, ELIGIBILITY_ABSENT)
            return None
        row["_currency"] = body.get("currency")
        row["_world"] = world_name
        spelling = str(row.get("symbol") or "")
        if spelling:
            self._venue_spelling[iid] = spelling
        _ELIGIBILITY[key] = (today, row)
        return row

    def eligibility_state(self, symbol: str, world: str = "") -> str:
        """"read" | "absent" | "error" — the row's own THREE-STATE after one
        attempt (a same-day hit costs nothing). "absent" is the venue
        saying it holds no row for this id — a stronger statement than
        "error", could not ask (a non-200) — and the engine gates the two
        apart (base._etoro_entry_refusal, step 2). An unknown spelling,
        an unmeasured body shape or a transport failure (requests raising
        from the POST) RAISES through eligibility(), nothing caught here;
        the engine reads a raise as "error"."""
        self.eligibility(symbol, world)
        key, today = self._elig_key(symbol, world)
        hit = _ELIGIBILITY.get(key)
        if hit is None or hit[0] != today:
            return "error"
        return "absent" if hit[1] == ELIGIBILITY_ABSENT else "read"

    def _elig(self, symbol: str, key: str, world: str = ""):
        """One key off the row; None when the row or the key is absent."""
        row = self.eligibility(symbol, world)
        return None if row is None else row.get(key)

    @staticmethod
    def _num(value) -> "float | None":
        """A number off the wire as float; None for anything else (a
        bool, a word, nothing) — unmeasured, never 0."""
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def unit_type(self, symbol: str, world: str = "") -> "str | None":
        """`unitsQuantityType` ("fractional" | "whole"), None unread."""
        v = self._elig(symbol, "unitsQuantityType", world)
        return None if v is None else str(v)

    def min_notional(self, symbol: str, world: str = "") -> "float | None":
        """`minPositionExposure` — the MONEY floor of one order in USD
        (MEASURED 2026-09-23: 10 on stocks, ETFs and crypto; 1000 on
        forex, indices and commodities; the body's `currency` read "usd"
        in both worlds), the `money_floor` tier base._venue_size_floor
        turns into units at a USD entry price. None unread. A body typed
        in anything but usd — or naming no currency — RAISES LookupError
        naming it (2026-09-25): the floor would otherwise be divided by
        a USD price and refuse or pass on a number nobody measured; the
        engine reads the raise as unmeasured with the currency in its
        reason, and the currency-free accessors on the same row still
        answer. NOT `minPositionAmount`, the per-entry margin floor
        (min_amount)."""
        row = self.eligibility(symbol, world)
        if row is None:
            return None
        currency = str(row.get("_currency") or "").lower()
        if currency != "usd":
            raise LookupError(
                f"eToro eligibility for {symbol!r} ({row.get('_world')}) is "
                f"typed in {currency or 'no currency'}, not usd — MEASURED "
                f"usd in both worlds 2026-09-23; a floor in another "
                f"currency is unmeasured, never scaled")
        return self._num(row.get("minPositionExposure"))

    def max_units_per_order(self, symbol: str,
                            world: str = "") -> "float | None":
        """`maxUnitsPerOrder` (AAPL 6151, BTC 41, SPX500 2300 ...); None
        unread or unprinted (ETFs, commodities). Refused past it by the
        entry gate, never clamped."""
        return self._num(self._elig(symbol, "maxUnitsPerOrder", world))

    def allow_open_position(self, symbol: str,
                            world: str = "") -> "bool | None":
        """`allowOpenPosition` as the wire's own bool; None unread or
        spelled as anything but a bool."""
        v = self._elig(symbol, "allowOpenPosition", world)
        return v if isinstance(v, bool) else None

    def requires_w8ben(self, symbol: str, world: str = "") -> "bool | None":
        """`requiresW8Ben` (True on US stocks and ETFs, False on forex,
        crypto, CPER). The platform cannot read the account's W8 state;
        the first live stock order is that measurement."""
        v = self._elig(symbol, "requiresW8Ben", world)
        return v if isinstance(v, bool) else None

    # leverageConfigs, keyed on (settlementType, direction, LEVERAGE).
    # MEASURED 2026-09-23 [FIX 1]: ONE (settlementType, direction) pair
    # maps to TWO entries on ETFs, forex, indices and commodities —
    # cfd/long [1] maxSL 100 AND cfd/long [2,5] — so a single-entry pick
    # would answer [1] or [2,5] by response order. The list is the UNION
    # across the pair's entries; a band is read off the entry that CARRIES
    # the multiplier. The levered bands were not printed: None, three-state.

    def _lev_configs(self, symbol: str, side: str, settlement: str,
                     world: str = "") -> list:
        """ALL leverageConfigs entries of `settlement` ("real" | "cfd")
        and the direction `side` maps to (BUY -> long, SELL -> short —
        the body's own words; the order body says buy/sellShort)."""
        row = self.eligibility(symbol, world)
        if row is None:
            return []
        direction = "long" if str(side).upper() == "BUY" else "short"
        want = str(settlement or "").lower()
        out = []
        for c in row.get("leverageConfigs") or []:
            if not isinstance(c, dict):
                continue
            if str(c.get("direction") or "").lower() != direction:
                continue
            if str(c.get("settlementType") or "").lower() != want:
                continue
            out.append(c)
        return out

    @staticmethod
    def _lev_values(config: dict) -> list:
        """The whole numbers >= 1 of one entry's `leverageValues`."""
        vals = []
        for v in config.get("leverageValues") or []:
            try:
                f = float(v)
            except (TypeError, ValueError):
                continue
            if f >= 1 and f == int(f):
                vals.append(int(f))
        return vals

    def leverage_values(self, symbol: str, side: str, settlement: str,
                        world: str = "live") -> "list | None":
        """The sorted UNION of `leverageValues` across the pair's entries
        — a membership check — or None when the row or the pair is
        absent. Defaults to the LIVE world: demo is more permissive
        (stocks 20 vs 5, forex 400 vs 30) and a demo list proves nothing
        for the real account."""
        configs = self._lev_configs(symbol, side, settlement, world)
        if not configs:
            return None
        return sorted({v for c in configs for v in self._lev_values(c)})

    def _lev_config_for(self, symbol: str, side: str, settlement: str,
                        leverage, world: str = "live") -> "dict | None":
        """The entry whose `leverageValues` carries `leverage`, else
        None (an off-list multiplier has no band to read)."""
        want = self._num(leverage)
        if want is None or want != int(want):
            return None
        for c in self._lev_configs(symbol, side, settlement, world):
            if int(want) in self._lev_values(c):
                return c
        return None

    def max_stop_loss_pct(self, symbol: str, side: str, settlement: str,
                          leverage, world: str = "live") -> "float | None":
        """`maxStopLossPercentage` of the entry that carries `leverage`
        (100 on every 1x entry read; 50 on stock CFDs); None when the
        entry or the key is absent — the levered ETF/forex/index bands
        were not printed on 2026-09-23. Its semantics (of the margin? of
        the price?) are unmeasured; a later stage judges a stop by it."""
        c = self._lev_config_for(symbol, side, settlement, leverage, world)
        return None if c is None else self._num(c.get("maxStopLossPercentage"))

    def min_stop_loss_pct(self, symbol: str, side: str, settlement: str,
                          leverage, world: str = "live") -> "float | None":
        """`minStopLossPercentage` of the entry that carries `leverage`;
        None absent (unprinted on every entry read)."""
        c = self._lev_config_for(symbol, side, settlement, leverage, world)
        return None if c is None else self._num(c.get("minStopLossPercentage"))

    def min_amount(self, symbol: str, side: str, settlement: str,
                   leverage, world: str = "live") -> "float | None":
        """`minPositionAmount` of the entry that carries `leverage` — the
        smallest MARGIN of one position (10 stocks/crypto, 25 forex and
        commodities, 50 indices); printed by a later stage, not enforced
        (under the platform cap it never binds before minPositionExposure)."""
        c = self._lev_config_for(symbol, side, settlement, leverage, world)
        return None if c is None else self._num(c.get("minPositionAmount"))

    def settlement_for(self, symbol: str, side: str, leverage,
                       world: str = "") -> "str | None":
        """The settlement an order of `side` at `leverage` lands on, read
        off the row's entries: "real" iff side is BUY, leverage is None
        or 1 and a real/long entry exists; "cfd" iff any cfd entry exists
        for the direction; else None — and None when the row itself is
        None (unread or absent): unknown, never free, which the carry
        step of a later stage reads as a refusal at >= 24 h [GAP 6].
        Every ETF, every short and every multiplier above 1 is a CFD with
        an overnight fee (doc §9). B: eToro's OWN assignment when the
        order body omits settlementType was measured once only (GLDM 1x
        -> CFD, D2 2026-09-23), consistent with this reading."""
        row = self.eligibility(symbol, world)
        if row is None:
            return None
        buy = str(side).upper() == "BUY"
        at_one = leverage is None or self._num(leverage) == 1.0
        if buy and at_one and self._lev_configs(symbol, side, "real", world):
            return "real"
        if self._lev_configs(symbol, side, "cfd", world):
            return "cfd"
        return None

    # ── fractional units (the `fractional_units` tier, MEASURED 2026-09-23) ──

    def takes_fractional_units(self, symbol: str) -> "bool | None":
        """Does eToro take a non-whole `units` for `symbol`? MEASURED per
        instrument off `unitsQuantityType` on the eligibility row (deploy/
        ETORO_DEPARTURE.md §4 D2c-0, 2026-09-23: "fractional" on all 20
        instruments read, both worlds; D2c pinned a fractional fill the
        same night). THREE STATES: True ("fractional"), False ("whole"),
        None for an instrument whose row is not read today (a non-200,
        an absent row, the key missing — unmeasured, never "whole" and
        never "fractional"); an unknown spelling raises from
        instrument_id, as every read here does. Once read, ONE POST per
        instrument per UTC day (the module cache); an unread row costs
        one POST per ask. The ENGINE asks
        only while the `fractional_units_live` switch is ON
        (base._venue_fractional_units) and holds stocks at whole shares
        otherwise — with the switch OFF this is never called. Until
        2026-09-25 this answered True as a labelled belief from the
        public reference, with no HTTP call."""
        ut = self.unit_type(symbol)
        return True if ut == "fractional" else (False if ut == "whole" else None)

    def _lookup_once(self, params: dict) -> "tuple[Optional[dict], int]":
        """ONE GET of orders:lookup -> (payload, http status). The payload is
        None when the GET could not be read (4xx/5xx, transport, non-JSON);
        the status is 0 when nothing answered. The bounded loops below
        decide what a None means across their attempts; nothing here does.

        MEASURED 2026-09-23: `orderId=<int from the acceptance>` -> 200;
        `referenceId=<our x-request-id>` -> 404 "No external operation was
        found for referenceId ..." (eToro keeps no client reference: the v1
        order read shows referenceID all zeros); `token=` -> 400. During a
        close in flight the same lookup answered 500 three times (~6 s),
        then 200 — a 500 is transient. Never raises.
        """
        r = None
        try:
            r = self._sess().get(self._v2_lookup(), params=params,
                                 headers=self._headers(),
                                 timeout=self.timeout)
            r.raise_for_status()
            return (r.json() or {}), int(getattr(r, "status_code", 0) or 0)
        except Exception as e:  # noqa: BLE001
            code = getattr(r, "status_code", 0)
            log.warning("eToro orders:lookup %s failed (%s): %s",
                        params, code, e)
            return None, (code if isinstance(code, int) else 0)

    def _await_fill(self, order_id: str, *, reference_id: str = "",
                    attempts: int = FILL_ATTEMPTS,
                    delay: float = FILL_DELAY_S) -> Optional[dict]:
        """Poll orders:lookup by the acceptance's orderId until a terminal
        status or attempts run out. Returns the last payload READ, or None
        when no attempt could be read at all — three states: a terminal
        payload, a non-terminal one, nothing.

        BY orderId (DEFECT 1 of the first demo orders, MEASURED
        2026-09-23): the acceptance's INTEGER orderId is the only key eToro
        answers 200 to; polling by the echoed referenceId answered 404 for
        ever and read every filled order as PENDING/pollFailed.
        `reference_id` is the documented fallback for an acceptance that
        names no orderId — a shape nobody has seen — and today it means
        404 -> None -> pollFailed: loud, never a fill.

        A FAILED GET IS ONE FAILED GET. Until 2026-09-23 this loop returned
        on the first exception, so one 404 (or one transient 500) ended the
        poll and `pollFailed` meant "one lookup failed". It now spends the
        attempt and goes on; None means EVERY attempt failed.
        """
        import time
        if order_id:
            params = {"orderId": str(order_id)}
        elif reference_id:
            params = {"referenceId": str(reference_id)}
        else:
            return None
        last = None
        for _ in range(attempts):
            time.sleep(delay)
            read, _code = self._lookup_once(params)
            if read is None:
                continue
            last = read
            status, _ = _status_of(last)
            if status in STATUS_FILLED or status in STATUS_REFUSED:
                return last
        return last

    def order_status(self, order_id: str) -> Optional[dict]:
        """The engine's working-entry vocabulary off ONE orders:lookup GET.

        MEASURED 2026-09-23 (demo): 11 WaitingForMarket -> working (the held
        order, positionExecutions []); 3 Filled -> filled with the units and
        price off positionExecutions[0].openingData; 7 Canceled -> dead;
        4 Rejected with errorCode 720 -> dead + `refusal` (the floor). The
        rest of the table is the public reference (5 -> working with units,
        8/9/10 -> dead, 1/2/6/12 -> working; 5 and 9 have met no key).
        THREE STATES: a dict is a reading; {"state": "unknown"} is an id eToro
        does not know (404 - a close order id, or an entry not yet indexed
        ~0.6 s after the POST); None is could-not-ask (5xx, 429, transport,
        non-JSON). Never raises, never sleeps. `positionId` and
        `venueStopLoss`/`venueTakeProfit` ride positionExecutions[0] exactly as
        market_order reports them - the HELD stop lives there, never on the
        top-level openStopLossRate (which stays the SENT level, measured on
        BTC 2026-09-23: 33758.56 sent, 63304.47 held).
        """
        oid = str(order_id or "")
        empty = {"state": "unknown", "status": "", "statusId": 0,
                 "filled": 0.0, "avgPrice": 0.0, "raw": {}}
        if not oid:
            return {**empty, "reason": "no order id"}
        read, code = self._lookup_once({"orderId": oid})
        if read is None:
            if code == 404:
                return {**empty,
                        "reason": f"eToro does not know order {oid} (404)"}
            return None
        sid, refusal = _status_of(read)
        executions = read.get("positionExecutions") or []
        first = (executions[0]
                 if executions and isinstance(executions[0], dict) else {})
        opening = first.get("openingData") or {}
        try:
            filled = float(opening.get("units")
                           or first.get("remainingUnits") or 0)
        except (TypeError, ValueError):
            filled = 0.0
        try:
            avg = float(opening.get("avgPrice") or 0)
        except (TypeError, ValueError):
            avg = 0.0
        out = {"state": "working", "status": STATUS_NAMES.get(sid, str(sid)),
               "statusId": sid, "filled": 0.0, "avgPrice": 0.0, "raw": read}
        if sid == 3:
            if not first:
                out["state"] = "unknown"
                out["reason"] = ("status Filled with no positionExecutions "
                                 "- a shape nobody has seen")
                return out
            out.update(state="filled", filled=filled, avgPrice=avg)
        elif sid == 5:
            out.update(state="working", filled=filled, avgPrice=avg)
        elif sid in STATUS_REFUSED:
            out.update(state="dead", filled=filled, avgPrice=avg)
        if refusal:
            out["refusal"] = refusal
        pid = first.get("positionId") or first.get("positionID")
        if pid:
            out["positionId"] = str(pid)
        for key, wire in (("venueStopLoss", "stopLossRate"),
                          ("venueTakeProfit", "takeProfitRate")):
            raw_level = first.get(wire)
            if raw_level is None:
                continue
            try:
                out[key] = float(raw_level)
            except (TypeError, ValueError):
                pass
        return out

    def position_state(self, order_id: str, *, until: Optional[str] = None,
                       attempts: int = CLOSE_PROOF_ATTEMPTS,
                       delay: float = CLOSE_PROOF_DELAY_S) -> Optional[str]:
        """"open" / "closed" — the venue's own word on the position an OPEN
        order created, read by that order's id — or None: could not ask.

        THE CLOSE PROOF (MEASURED 2026-09-23). The close order this venue
        answers with (orderType 19) is findable on no read path:
        orders:lookup 404 "Order category for <id> not found", the v1 order
        read 404. What changes is the OPEN order's
        positionExecutions[0].state: "open" after the fill, "closed" after
        the close — reached ~8 s after the close POST, behind three 500s
        (measured on the 2x close; the 1x close's lookup timing was not
        printed). The lookup's own `status` stays {id 3, Filled} across the
        close and is NOT the proof; `remainingUnits` stays at the opened
        units and is not a residual; no closing price rides anywhere here.

        `until="closed"` keeps polling, `delay` apart (sleeping BEFORE each
        read, so a caller straight after the close POST does not spend its
        first read on a body that cannot have moved), until that word or
        the budget; the last word READ is returned then — "open" is a
        reading, not a proof. `until=None` returns the first word read; the
        drain calls it with attempts=1, delay=0.0 — one GET, no sleep.
        THREE STATES: a word is a reading; None is could-not-ask — every
        read failed, or no body carried an execution (a 404 by orderId for
        an order that exists is UNMEASURED and reads as could-not-ask,
        never as closed).
        """
        import time
        oid = str(order_id or "")
        if not oid:
            return None
        last = None
        for _ in range(attempts):
            if delay:
                time.sleep(delay)
            read, _code = self._lookup_once({"orderId": oid})
            if read is None:
                continue
            execs = read.get("positionExecutions") or []
            first = execs[0] if execs and isinstance(execs[0], dict) else {}
            state = str(first.get("state") or "").strip().lower()
            if not state:
                continue
            last = state
            if until is None or state == until:
                return last
        return last

    def market_order(self, symbol: str, side: str, quantity: float,
                     **kwargs) -> dict:
        """Open a position. side BUY -> `buy`, SELL -> `sellShort`.

        stop_loss / take_profit kwargs become stopLossRate / takeProfitRate,
        absolute prices held AT THE BROKER on fill. The fill itself is read
        back by polling; an order still pending when polling stops is
        reported PENDING with executedQty 0, never as a fill.

        A stop_loss / take_profit that is PRESENT and not a price (0, a
        negative, NaN, a non-number) RAISES ValueError before any POST: the
        caller asked for a broker-held leg, and an order sent without it is
        unprotected at leverage 1. None means no leg was asked for.

        `leverage` (kwarg, default absent) rides the body as an integer in
        [1, LEVERAGE_MAX] or RAISES before the POST (`_leverage`); above 1
        a None stop_loss raises too (public reference, unmeasured: eToro
        requires a stopLossRate there). Units are untouched by it: leverage
        changes the margin eToro locks for the same units and nothing else
        this adapter sends. No settlementType is sent; eToro assigned
        `asset.settlementType "CFD"` at 1x and at 2x (measured 2026-09-23,
        GLDM — an ETF, which eToro lists with no real settlement).
        `venueStopLoss`/`venueTakeProfit` echo what the lookup says the
        venue holds; `pollFailed` says NO lookup could be read (every GET
        failed), never that one of them did.

        THE RESULT, on the wire measured 2026-09-23: the acceptance is
        {token, orderId (int), referenceId}; `orderId` rides out as a
        string (the row column). FILLED carries executedQty
        (openingData.units), avgPrice (openingData.avgPrice), positionId
        (positionExecutions[0].positionId, camel), venueStopLoss /
        venueTakeProfit, and protectedOnFill + protectiveTradeId when both
        legs were sent; raw.lookup is the whole lookup body (state, margin,
        fees, markup, marketSpread ride there for the record — no consumer
        reads them, so they are not promoted to keys). PENDING with
        `working` is a real non-filled status, or every lookup failing —
        then `pollFailed` too.
        """
        rid = self._rid(kwargs.get("client_order_id"))
        # THE MULTIPLIER, validated before anything else is built: 1 when
        # the caller sent none (the literal this body carried until
        # 2026-09-23), the caller's whole number otherwise, a raise for
        # anything that is neither. It scales the margin eToro locks, not
        # `units` — the same units at any leverage lose the same money at
        # the stop, which is the invariant asset_engine/sizing.py keeps.
        leverage = _leverage(kwargs.get("leverage"), symbol, side)
        body = {
            "action": "open",
            "transaction": "buy" if side == "BUY" else "sellShort",
            "symbol": str(symbol),
            "units": float(quantity),
            "leverage": leverage,
        }
        # REFUSED BEFORE THE POST when a level is present and not a price.
        # `if stop_loss:` dropped a 0.0 leg silently and SENT a negative
        # one; `_level` raises for both, and None stays "no leg asked for".
        stop_loss = _level(kwargs.get("stop_loss"), "stop_loss", symbol, side)
        take_profit = _level(kwargs.get("take_profit"), "take_profit",
                             symbol, side)
        protected = False
        if stop_loss is not None:
            body["stopLossRate"] = stop_loss
            body["stopLossType"] = "fixed"
        if take_profit is not None:
            body["takeProfitRate"] = take_profit
        if stop_loss is not None and take_profit is not None:
            protected = True
        if leverage > 1 and stop_loss is None:
            # From the public reference (unmeasured): "a stopLossRate is
            # required when leverage is greater than 1". Refused here, in
            # `_level`'s voice, rather than sent for eToro to refuse — and
            # never sent at 1 instead. The bot lane always passes both legs
            # (asset_engine/base.py execute_entry); this protects every
            # other caller and the D2b shell snippet.
            raise ValueError(
                f"eToro NOT SENT: leverage {leverage} with no stop_loss "
                f"({symbol} {side}). eToro requires a stop above leverage 1; "
                f"an order without one is refused here, before the POST."
            )

        r = self._sess().post(self._v2_exec_orders(), json=body,
                              headers=self._headers(rid),
                              timeout=self.timeout)
        try:
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            # THE VENUE'S WORDS ride the raise: skips.record keeps 200 chars
            # and why_no_trade prints 88, and a bare HTTPError read as
            # "check the gateway" for a size eToro refused (the
            # _patch_position idiom below).
            log.error("eToro order failed: %s", r.text)
            raise RuntimeError(f"eToro refused ({r.status_code}): "
                               f"{str(r.text)[:160]}") from e
        accepted = r.json() or {}
        order_id = str(accepted.get("orderId") or "")
        reference = str(accepted.get("referenceId") or rid)

        # BY THE ORDER ID, never by the reference (MEASURED 2026-09-23, see
        # _await_fill): `order_id` is the handle, and it is what both lanes
        # persist as AssetBotTrade.broker_order_id — the same id proves the
        # close later (position_state). The reference rides only as the
        # documented fallback for an acceptance with no orderId.
        polled = self._await_fill(order_id, reference_id=reference)
        # THREE STATES for the lookup: a payload (read), None (NO poll could
        # be read — every GET failed: transport, 5xx, or the shared 20/60 s
        # quota, public reference, unmeasured). `poll_failed` travels out as
        # `pollFailed` so a WORKING row can say "the lookup failed" instead
        # of "eToro is holding it"; {} is never invented as a reading, and
        # one failed GET beside a later 200 is not a failed poll.
        poll_failed = polled is None
        polled = polled or {}
        status_id, refusal = _status_of(polled)
        executions = polled.get("positionExecutions") or []
        first = executions[0] if executions else {}
        opening = first.get("openingData") or {}

        filled_units = 0.0
        avg_price = 0.0
        if status_id in STATUS_FILLED:
            try:
                filled_units = float(opening.get("units")
                                     or first.get("remainingUnits") or 0)
                avg_price = float(opening.get("avgPrice") or 0)
            except (TypeError, ValueError):
                filled_units, avg_price = 0.0, 0.0

        if status_id in STATUS_FILLED:
            status = "FILLED" if status_id == 3 else "PARTIALLY_FILLED"
        elif status_id in STATUS_REFUSED:
            status = STATUS_REFUSED[status_id]
        else:
            status = "PENDING"

        out = {
            "orderId": order_id,
            "symbol": symbol,
            "side": side,
            "executedQty": str(filled_units),
            "avgPrice": str(avg_price),
            "status": status,
            "raw": {"accepted": accepted, "lookup": polled,
                    "requestId": rid,
                    "clientOrderId": kwargs.get("client_order_id"),
                    "statusName": STATUS_NAMES.get(status_id, str(status_id))},
        }
        if status_id in STATUS_REFUSED and refusal:
            # Read by base.py into the ORDER_REJECTED detail (consumer key).
            out["refusal"] = refusal
        position_id = first.get("positionId") or first.get("positionID")
        # WHAT THE VENUE HOLDS, when the lookup says. MEASURED 2026-09-23:
        # positionExecutions[0].stopLossRate 82.22 / takeProfitRate 87.3,
        # exactly the levels SENT (no rewrite at 1x or 2x), and a PATCH of
        # the stop to 83.06 echoed there on the next lookup. Absent on the
        # wire -> absent here. base.py
        # compares them with what was SENT; eToro's 0.0001 "no stop"
        # sentinel (public reference, unmeasured) then reads as a rewrite,
        # which is the truth: the venue holds no stop.
        for key, wire in (("venueStopLoss", "stopLossRate"),
                          ("venueTakeProfit", "takeProfitRate")):
            raw_level = first.get(wire)
            if raw_level is not None and not isinstance(raw_level, bool):
                try:
                    out[key] = float(raw_level)
                except (TypeError, ValueError):
                    pass
        if position_id:
            # THE HANDLE THE CLOSE NEEDS, on every fill. It used to be
            # reported only beside an accepted bracket (below), so exactly
            # the rows whose bracket eToro refused had nothing to close BY —
            # and at this venue a close without a position id cannot be sent
            # at all. Reported under its own key rather than as
            # protectiveTradeId, because it is not a claim about protection.
            out["positionId"] = str(position_id)
        if protected and filled_units > 0 and position_id:
            # Protection rides the POSITION, as on OANDA: nothing to cancel,
            # and the position id is the handle for moving the legs later.
            out["protectedOnFill"] = True
            out["protectiveOrders"] = []
            out["protectiveTradeId"] = str(position_id)
        if status == "PENDING":
            if poll_failed:
                # NOT "eToro is holding it": nobody could read the lookup.
                # Filled, refused and waiting are all possible; the row
                # books WORKING either way and the alert says which.
                out["pollFailed"] = True
            # AN ACCEPTANCE IS NOT A POSITION. Every non-terminal lookup
            # status (Received, Placed, WaitingForMarket, PendingTriggered
            # Rate) — and a poll that could not be read at all, which also
            # lands here — has nothing filled. base.py and manual_trade book
            # a WORKING row on this flag, the contract IBKR (ibkr_client
            # .market_order) and Saxo (saxo_client.market_order) already
            # keep; without it both lanes booked a full-size OPEN position
            # at the pre-order ticker for an order eToro was merely holding,
            # and the pre-open reconcile (13:00/13:15 UTC) then orphan-
            # closed the row at a mark while the order filled at 13:30 with
            # a bracket the platform never saw.
            #
            # WHAT HAPPENS NEXT (D3b, 2026-09-24): the row is WATCHED by
            # base._poll_working_entry through order_status (one lookup by
            # the orderId both lanes persist as broker_order_id) and
            # WITHDRAWN by cancel_working_entry through cancel_order (DELETE
            # v3 -> 202 -> lookup 7) after ENTRY_WORKING_MAX_HOURS on the
            # demo segment; on the real segment the DELETE spelling is
            # unmeasured, `_v3_exec_order` raises, and the tick alerts daily
            # instead. A held order refused at the open (status 4) is booked
            # CANCELED with its errorCode words. Since the fix in
            # _await_fill this branch is reached only by a real non-filled
            # status (11 measured) or by EVERY lookup failing.
            out["working"] = True
        return out

    # ── brackets ───────────────────────────────────────────────────────────

    def _patch_position(self, position_id: str, body: dict,
                        what: str) -> dict:
        try:
            r = self._sess().patch(self._v2(f"positions/{position_id}"),
                                   json=body, headers=self._headers(),
                                   timeout=self.timeout)
            if r.status_code in (200, 202):
                return {"ok": True, "reason": ""}
            return {"ok": False,
                    "reason": f"eToro refused ({r.status_code}): "
                              f"{r.text[:160]}"}
        except Exception as e:  # noqa: BLE001
            log.error("eToro %s(%s) failed: %s", what, position_id, e)
            return {"ok": False, "reason": str(e)}

    def modify_protective(self, trade_id: str, new_price: float) -> dict:
        """Move the stop on position `trade_id`. One field, so the target is
        untouched — a mover that sent both would be the bug it exists to
        prevent. 200 or 202 both mean accepted; which one answered the
        first PATCH ever (2026-09-23, demo, position 3603285267, 82.22 ->
        83.06) was not recorded — the adapter answered ok and the next
        lookup showed stopLossRate 83.06 on positionExecutions[0]. TIGHTER
        only; a widening PATCH has not been sent."""
        res = self._patch_position(str(trade_id),
                                   {"stopLossRate": float(new_price)},
                                   "modify_protective")
        res["price"] = float(new_price) if res["ok"] else None
        return res

    def modify_target(self, trade_id: str, new_price: float) -> dict:
        """Move the take-profit on position `trade_id`. The sibling of
        modify_protective, deliberately separate."""
        res = self._patch_position(str(trade_id),
                                   {"takeProfitRate": float(new_price)},
                                   "modify_target")
        res["price"] = float(new_price) if res["ok"] else None
        return res

    # ── closing ────────────────────────────────────────────────────────────

    # ── orders (D3b) ───────────────────────────────────────────────────────────────

    def cancel_order(self, order_id: str) -> Optional[bool]:
        """Withdraw a held ENTRY order - LOOKUP FIRST, DELETE, PROVE.

        MEASURED 2026-09-23 20:29 UTC (demo, order 383459788, WaitingForMarket):
        DELETE /api/v3/trading/execution/demo/orders/<id> -> 202
        {orderId, referenceId ""}; the lookup then read {7, Canceled} and the
        pledged margin and frozen cash returned to 0.

        THREE ANSWERS. True = a lookup read Canceled (7, 8 or 9; 7 measured,
        8/9 the public table). False = nothing was cancelled: nothing sent
        (an id the lookup cannot read - a CLOSE order id is findable on no
        read path and is read once, never DELETEd; an order already filled
        or refused), refused (a DELETE answering anything but 200/202/204;
        the refusal body is unmeasured), or not proven (a DELETE accepted
        and the lookup reading anything else afterwards, including a body
        the adapter cannot read). None = a DELETE went out and no lookup
        answered at all. Status 5 (PartiallyFilled) is OPEN: the DELETE is
        sent and a 9 read proves it (belief - neither has met a key). The
        real segment's spelling is unmeasured: `_v3_exec_order` raises there
        and every consumer books "not confirmed".
        """
        oid = str(order_id or "")
        if not oid:
            return False
        read, code = self._lookup_once({"orderId": oid})
        if read is None:
            log.error("eToro cancel_order NOT SENT: eToro cannot read %s as an "
                      "order (HTTP %s) - a close order id is findable on no "
                      "read path", oid, code)
            return False
        sid, _ = _status_of(read)
        if sid in (7, 8, 9):
            return True
        if sid in (3, 4, 10):
            log.info("eToro cancel_order: order %s reads %s - nothing to "
                     "cancel", oid, STATUS_NAMES.get(sid, sid))
            return False
        url = self._v3_exec_order(oid)          # raises on the real segment
        try:
            r = self._sess().delete(url, headers=self._headers(),
                                    timeout=self.timeout)
            code2 = int(getattr(r, "status_code", 0) or 0)
            if code2 not in (200, 202, 204):
                log.error("eToro cancel_order refused (%s): %s", code2,
                          str(getattr(r, "text", "") or "")[:160])
                return False
        except Exception as e:  # noqa: BLE001 - the DELETE may have landed
            log.warning("eToro cancel_order: DELETE %s raised (%s) - reading "
                        "the lookup anyway", oid, e)
        proof = self._await_fill(oid)
        if proof is None:
            return None
        sid2, _ = _status_of(proof)
        if sid2 in (7, 8, 9):
            return True
        log.error("eToro cancel_order: DELETE accepted, lookup reads %s - not "
                  "proven", STATUS_NAMES.get(sid2, f"id {sid2}"))
        return False

    def close_needs_position_id(self) -> bool:
        """ALWAYS true here, and it is not a netting profile.

        market_order sends {"action": "open", ...} and has no close branch —
        eToro's API separates the two — so an "opposite market order", which
        is what the engine's default close is, OPENS a position instead of
        closing one: a SELL becomes `sellShort` beside the long. The row then
        books CLOSED at that fill while the account holds DOUBLE, hedged,
        paying both spreads.

        The engine asks this before every close and closes by PositionId when
        the answer is yes, through close_position below — the market-close
        endpoint, which is the only thing at eToro that reduces a position.
        """
        return True

    def close_position(self, position_id: str, symbol: str,
                       units: Optional[float] = None, *,
                       open_order_id: str = "") -> dict:
        """Submit a market close and, given the OPEN order's id, PROVE it.

        MEASURED 2026-09-23 (demo): the POST answers {orderForClose:
        {positionID, instrumentID, orderID (orderType 19), statusID 1, CID,
        openDateTime, lastUpdate}, token} — never an executedQty, never a
        price — and that orderID is findable nowhere afterwards, so it rides
        out as a RECORD (`orderId`), never a handle. The proof is
        `position_state(open_order_id, until="closed")`: the OPEN order's
        execution state, ~8 s behind three transient 500s (measured on the
        2x close). venue_close hands the id in from the row's own
        AssetBotTrade.broker_order_id.

        THREE ANSWERS, in the vocabulary pending_closes.resolve_exit_fill
        reads:
          proven      status FILLED, executedQty = the units asked, NO
                      avgPrice — the exit books at the engine's mark
                      (exit_fill_source "mark"); positionState "closed".
                      With no `units` asked (the D2 shell) executedQty is
                      left absent and the caller's size stands, flagged
                      close_qty_assumed by resolve_exit_fill.
          unproven    status PENDING, executedQty "0.0", positionState
                      "open" / None -> the row books CLOSE_PENDING (the
                      bot lane through _book_partial_close, the kill switch
                      through its own incomplete branch) and the drain
                      re-proves by the same open id. NEVER an absent
                      executedQty here: resolve_exit_fill assumes the whole
                      size for that, which is how an acceptance booked
                      CLOSED on the first demo night.
          no open id  (a row with no broker_order_id): status PENDING,
                      executedQty "0.0", no lookup asked; the drain proves
                      it off the book past PORTFOLIO_LAG_S.
        MEASURED 2026-09-23 17:43-17:58 UTC: a body carrying `UnitsToDeduct`
        is accepted and NEVER executes; InstrumentID alone executes. So the
        field is never sent and a close is always the whole position.
        UNMEASURED and said so: a close below the position (no way to ask
        for one now), a second close on an already-closed positionId.
        """
        # NEVER UnitsToDeduct. MEASURED 2026-09-23 (demo, 17:43-17:58 UTC):
        # two closes carrying {InstrumentID, UnitsToDeduct 1.0} were
        # ACCEPTED (orderForClose echoed unitsToDeduct 1.0) and NEVER
        # executed - the position stayed open, margin held, for fifteen
        # minutes; the same close with InstrumentID alone executed in ~6 s
        # (two transient 500s on the way). Every engine caller passes the
        # row's units; on eToro a close is the whole position, so `units`
        # is accepted, reported back, and not sent.
        body = {"InstrumentID": self.instrument_id(symbol)}
        r = self._sess().post(
            self._v1_exec(f"market-close-orders/positions/{position_id}"),
            json=body, headers=self._headers(), timeout=self.timeout)
        r.raise_for_status()
        data = r.json() or {}
        ofc = data.get("orderForClose") or {}
        out = {"orderId": str(ofc.get("orderID") or ofc.get("orderId")
                              or ""),
               "positionId": str(position_id), "status": "PENDING",
               "executedQty": "0.0", "raw": data}
        oid = str(open_order_id or "")
        if not oid:
            return out
        out["openOrderId"] = oid
        out["positionState"] = self.position_state(oid, until="closed")
        if out["positionState"] != "closed":
            return out
        out["status"] = "FILLED"
        if units:
            out["executedQty"] = str(float(units))
        else:
            out.pop("executedQty")
        return out
