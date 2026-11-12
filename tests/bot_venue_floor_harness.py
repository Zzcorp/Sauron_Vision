"""The harness of the venue floor's tests (tests/test_bot_venue_floor*.py).

Synthetic fixtures only: EURUSD, XAUUSD, NAS100, AAPL and BTCUSD at invented
prices, round invented pools, invented users. No broker, no model, no HTTP:
the venue is the REAL eToro adapter with its eligibility rows, its quote
and its order answer stated by the test, on a wire that answers nothing.

Not a test module (the suite discovers test*.py): the scenarios, the venue
and the snapshot the tests and the golden recording share.
"""
import json
import re
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.utils import timezone

from tests.test_desk_seam import _client as _mock_client
from tests.test_etoro_client import (_FakeSession, _clear_eligibility,
                                     _elig_row, _lev)
from tests.test_execution_trust import _cfg as _live_cfg
from tests.test_execution_trust import _instrument

ROUTER = "bot_program.engine.broker_router.client_for_symbol"
#: The floor's switch, spelled here by hand: a rename of the key is a
#: change to a live-money switch and must fail a test.
SWITCH = "bots_venue_floor_live"
FRACTIONS = "fractional_units_live"
LEVERAGE = "etoro_leverage_live"

RULE = "floor_rule"                 # live_full
RULE_SMALL = "floor_rule_small"     # live_small: a quarter size
RULE_PAPER = "floor_rule_paper"     # paper stage: a live config books paper


def _row(iid, symbol, configs, *, min_exposure, max_units=None,
         currency="usd"):
    """One eligibility row as the adapter keeps it: the wire's row with the
    body's currency and world beside it."""
    row = _elig_row(iid, symbol, configs, min_exposure=min_exposure,
                    max_units=max_units, w8=False)
    row["_currency"] = currency
    row["_world"] = "demo"
    return row


def rows(**overrides):
    """The five instruments' rows, as measured for their classes (forex,
    index and commodity: a 1,000 USD minimum exposure; stock and crypto:
    10 USD), on invented ids. `overrides` replaces a symbol's row (None
    removes it: unread)."""
    table = {
        "EURUSD": _row(1002, "EURUSD", [
            _lev("cfd", "long", [1], max_sl=100, min_amount=25),
            _lev("cfd", "long", [2, 5, 10, 20, 30], min_amount=25),
            _lev("cfd", "short", [1, 2, 5, 10, 20, 30], min_amount=25)],
            min_exposure=1000, max_units=3805935),
        "XAUUSD": _row(18, "GOLD", [
            _lev("cfd", "long", [1], max_sl=100, min_amount=25),
            _lev("cfd", "long", [2, 5, 10], min_amount=25),
            _lev("cfd", "short", [1, 2, 5, 10], min_amount=25)],
            min_exposure=1000),
        "NAS100": _row(28, "NSDQ100", [
            _lev("cfd", "long", [1], max_sl=100, min_amount=25),
            _lev("cfd", "long", [2, 5, 10, 20], min_amount=25),
            _lev("cfd", "short", [1, 2, 5, 10, 20], min_amount=25)],
            min_exposure=1000),
        "AAPL": _row(1001, "AAPL", [
            _lev("real", "long", [1], max_sl=100),
            _lev("cfd", "long", [2, 5], max_sl=50),
            _lev("cfd", "short", [1, 2, 5], max_sl=50)],
            min_exposure=10, max_units=6151),
        "BTCUSD": _row(100000, "BTC", [
            _lev("real", "long", [1], max_sl=100),
            _lev("cfd", "long", [2]),
            _lev("cfd", "short", [1, 2])],
            min_exposure=10, max_units=41),
    }
    for symbol, row in overrides.items():
        if row is None:
            table.pop(symbol, None)
        else:
            table[symbol] = row
    return table


def venue(price, table=None, *, fill=None, raises=None):
    """The real eToro adapter, demo world, with what it would read stated:
    the eligibility rows (`table`), one quote (`price`) and the order's
    answer (a fill of the size asked at that price; `fill` states another
    answer, `raises` an exception). Every row read is noted on `.asked`;
    anything sent on the wire lands on `.wire.calls`, and nothing should."""
    from bot_program.engine.etoro_client import EtoroTrader
    table = rows() if table is None else table
    t = EtoroTrader("api-k", "user-k", env="demo")
    t.wire = t._session = _FakeSession([])
    t.asked = []

    def eligibility(symbol, world=""):
        t.asked.append(symbol)
        return table.get(symbol)

    def order(symbol, side, qty, **kw):
        if raises is not None:
            raise raises
        if fill is not None:
            return dict(fill)
        return {"orderId": "o-1", "status": "FILLED", "avgPrice": str(price),
                "executedQty": str(qty), "positionId": "p-1"}

    t.eligibility = eligibility
    t.eligibility_state = (
        lambda symbol, world="": "read" if table.get(symbol) else "error")
    t.ticker = mock.MagicMock(return_value={"lastPrice": str(price)})
    t.market_order = mock.MagicMock(side_effect=order)
    t.get_positions = mock.MagicMock(return_value=[])
    return t


def switch(key, on):
    """A PlatformComponent row in the state named; None deletes the row."""
    from core.platform_control import PlatformComponent
    if on is None:
        PlatformComponent.objects.filter(key=key).delete()
        return
    PlatformComponent.objects.update_or_create(
        key=key, defaults={"name": key, "category": "system",
                           "is_enabled": bool(on)})


def ceiling(pct):
    """MAX BOT FLOOR RISK as the /setup/ card stores it."""
    from portfolio.risk_gate import limits_book
    book = limits_book()
    book.max_bot_floor_risk_pct = pct
    book.save(update_fields=["max_bot_floor_risk_pct", "updated_at"])
    return book


def limit(**fields):
    """Other limits of the book, as the card stores them."""
    from portfolio.risk_gate import limits_book
    book = limits_book()
    for name, value in fields.items():
        setattr(book, name, value)
    book.save(update_fields=[*fields, "updated_at"])
    return book


def signal(symbol, icls, *, rule=RULE, stage="live_full",
           direction="bullish"):
    """An active signal of `rule` on the instrument, the rule at `stage`."""
    from signals.models import Signal
    from signals.models_control import RuleControl
    inst = _instrument(symbol, icls)
    # one voice per entry: an earlier scenario's signal on this instrument
    # would vote too, under its own rule and stage
    Signal.objects.filter(instrument=inst).update(is_active=False)
    RuleControl.objects.update_or_create(
        rule_name=rule, defaults={"promotion_stage": stage})
    return Signal.objects.create(
        instrument=inst, signal_type="composite", direction=direction,
        urgency="medium", title="t", description="d", rule_name=rule,
        score=0.9, sub_scores={}, price_at_signal=Decimal("100"),
        suggested_entry=Decimal("100"), is_active=True)


def account(user, *, money="1000", cash=None, used="0", currency="USD"):
    """The user's eToro row, demo, every class routed to it, with fresh
    cells: equity `money`, free cash `cash` (the equity when not stated)."""
    from bot_program.models import EtoroAccount
    acct = EtoroAccount.objects.create(
        user=user, demo=True, label="Main", is_primary_for_stocks=True,
        is_primary_for_forex=True, is_primary_for_commodity=True,
        is_primary_for_crypto=True)
    acct.set_credentials("k", "u")
    now = timezone.now()
    acct.last_equity = Decimal(str(money))
    acct.last_equity_currency = currency
    acct.last_equity_at = now
    acct.last_available_cash = Decimal(str(money if cash is None else cash))
    acct.last_used_margin = Decimal(str(used))
    acct.last_margin_at = now
    acct.last_margin_world = "demo"
    acct.save()
    return acct


def own_book(user, value="1000"):
    """The operator's own book on /setup/, which a levered order needs."""
    from portfolio.models import Portfolio
    return Portfolio.objects.create(
        name=f"{user.username}_main", initial_capital=Decimal(str(value)),
        current_value=Decimal(str(value)),
        cash_available=Decimal(str(value)), currency="USD")


#: The synthetic entries, across the five classes. `cls` is the config's
#: class (an index sits in a stock config), `icls` the instrument's.
#: Stops and targets are the config's own percentages (no bars, so no ATR).
SCENARIOS = {
    # under eToro's 1,000 USD minimum exposure
    "forex_under_min": dict(
        cls="forex", symbol="EURUSD", icls="forex", price="1.0800",
        pool="2000", extras={"session_filter_disabled": True}),
    "forex_typed_leverage": dict(
        cls="forex", symbol="EURUSD", icls="forex", price="1.0800",
        pool="2000", extras={"session_filter_disabled": True,
                             "leverage": 10}),
    "forex_auto_leverage": dict(
        cls="forex", symbol="EURUSD", icls="forex", price="1.0800",
        pool="2000", extras={"session_filter_disabled": True,
                             "leverage": "auto"}),
    "commodity_under_min": dict(
        cls="commodity", symbol="XAUUSD", icls="commodity",
        price="2000.00", pool="1000"),
    "index_under_min": dict(
        cls="stock", symbol="NAS100", icls="index", price="20000.00",
        pool="1000", fractions=True),
    # sized to zero by the whole-unit rounding of a live stock config
    "index_whole_units": dict(
        cls="stock", symbol="NAS100", icls="index", price="20000.00",
        pool="1000"),
    "stock_under_one_share": dict(
        cls="stock", symbol="AAPL", icls="stock", price="100.00",
        pool="1000", sl=5.0, tp=15.0),
    # crypto under eToro's 10 USD minimum (a very small risk setting)
    "crypto_under_min": dict(
        cls="crypto", symbol="BTCUSD", icls="crypto", price="50000.00",
        pool="1000", sl=5.0, tp=15.0, extras={"risk_per_trade_pct": 0.02}),
    # sizes the venue takes: nothing to raise
    "crypto_clear": dict(
        cls="crypto", symbol="BTCUSD", icls="crypto", price="50000.00",
        pool="1000", sl=5.0, tp=15.0),
    "stock_clear": dict(
        cls="stock", symbol="AAPL", icls="stock", price="100.00",
        pool="10000", sl=5.0, tp=15.0),
    # the stages
    "forex_probation": dict(
        cls="forex", symbol="EURUSD", icls="forex", price="1.0800",
        pool="2000", extras={"session_filter_disabled": True},
        rule=RULE_SMALL, stage="live_small"),
    "forex_paper_stage": dict(
        cls="forex", symbol="EURUSD", icls="forex", price="1.0800",
        pool="2000", extras={"session_filter_disabled": True},
        rule=RULE_PAPER, stage="paper"),
    # a paper config: the platform's own venue
    "forex_paper_config": dict(
        cls="forex", symbol="EURUSD", icls="forex", price="1.0800",
        pool="2000", extras={"session_filter_disabled": True},
        mode="paper"),
    # a minimum the venue does not state
    "forex_unmeasured": dict(
        cls="forex", symbol="EURUSD", icls="forex", price="1.0800",
        pool="2000", extras={"session_filter_disabled": True},
        unmeasured=True),
    "stock_unread_row": dict(
        cls="stock", symbol="AAPL", icls="stock", price="100.00",
        pool="1000", sl=5.0, tp=15.0, unread=True),
}


def arm(name, tag, **changes):
    """Build one scenario's world: a user, its eToro row and book, the
    instrument, the rule and its signal, the config. `tag` keeps users
    apart (the duplicate and theme gates are per user). Returns the spec
    with `cfg`, `user`, `table` added; `changes` override the spec."""
    from django.contrib.auth import get_user_model
    spec = dict(SCENARIOS[name], **changes)
    user = get_user_model().objects.create_user(
        f"floor_{name}_{tag}"[:150], password="x")
    pool = spec["pool"]
    account(user, money=spec.get("money", pool), cash=spec.get("cash"),
            used=spec.get("used", "0"),
            currency=spec.get("account_currency", "USD"))
    own_book(user, pool)
    signal(spec["symbol"], spec["icls"], rule=spec.get("rule", RULE),
           stage=spec.get("stage", "live_full"))
    cfg = _live_cfg(user, spec["cls"], mode=spec.get("mode", "live"),
                    name=f"F {name}"[:80])
    cfg.symbols = [spec["symbol"]]
    cfg.capital = Decimal(pool)
    cfg.base_currency = spec.get("currency", "USD")
    cfg.stop_loss_pct = spec.get("sl", 1.5)
    cfg.take_profit_pct = spec.get("tp", 3.0)
    cfg.extras = dict(spec.get("extras") or {})
    cfg.save()
    table = rows()
    if spec.get("unmeasured"):
        # typed in another currency: the adapter raises, the engine reads
        # the minimum as unmeasured
        table[spec["symbol"]] = dict(table[spec["symbol"]], _currency="eur")
    if spec.get("unread"):
        table.pop(spec["symbol"], None)
    if "table" in spec:
        table = spec["table"]
    switch(FRACTIONS, True if spec.get("fractions") else None)
    return dict(spec, cfg=cfg, user=user, table=table)


def run(world, *, the_venue=None, size_mult=1.0, between=None,
        prepare=None):
    """Propose, then execute, as scan_symbol does (the two steps apart so a
    test can act between them). `prepare(bot)` runs on the bot before the
    proposal (the state can_open_new leaves on it); `between()` runs
    between the proposal and the order."""
    from bot_program.asset_engine.base import make_bot
    cfg, symbol = world["cfg"], world["symbol"]
    _clear_eligibility()
    if the_venue is None:
        the_venue = (_mock_client(world["price"]) if cfg.mode == "paper"
                     else venue(world["price"], world["table"]))
        if cfg.mode == "paper":
            the_venue.asked = []
    bot = make_bot(cfg)
    if prepare is not None:
        prepare(bot)
    with mock.patch(ROUTER, return_value=the_venue), \
            mock.patch("time.sleep"), \
            mock.patch("bot_program.notifications."
                       "notify_bot_fill_open") as note:
        cand = bot.propose_entry(symbol)
        res = None
        if cand is not None:
            if between is not None:
                between()
            res = bot.execute_entry(cand, size_mult=size_mult)
    cfg.refresh_from_db()
    return SimpleNamespace(bot=bot, cand=cand, res=res, venue=the_venue,
                           note=note, cfg=cfg, world=world)


def skip_of(out, symbol=None):
    """The last skip recorded for the symbol: {"code", "detail"} or {}."""
    rec = (out.cfg.extras.get("skips") or {}).get(
        symbol or out.world["symbol"]) or {}
    return {k: rec.get(k) for k in ("code", "detail")} if rec else {}


def orders(out):
    """The orders sent: [symbol, side, qty, kwargs without the order id]."""
    return [[c.args[0], c.args[1], c.args[2],
             {k: v for k, v in sorted(c.kwargs.items())
              if k != "client_order_id"}]
            for c in out.venue.market_order.call_args_list]


def trade_rows(out):
    from bot_program.models import AssetBotTrade
    return list(AssetBotTrade.objects.filter(config=out.cfg).order_by("id"))


_TIME = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?"
                   r"(\+\d{2}:\d{2}|Z)?")
#: Keys whose value is a clock or an id of this run, never a decision.
_VOLATILE = {"trade_id", "age_s", "id"}


def scrub(value):
    """A stored value with this run's clock and ids taken out: timestamps
    read "<time>", the keys of _VOLATILE "<run>". Everything else is kept
    as it is stored."""
    if isinstance(value, dict):
        return {str(k): ("<run>" if k in _VOLATILE else scrub(v))
                for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [scrub(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, str):
        return _TIME.sub("<time>", value)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _TIME.sub("<time>", str(value))


def snapshot(out) -> dict:
    """Everything one entry decided, sent and stored: the candidate, the
    result, the orders, the rows the venue was asked for, the skip and the
    counters, the trade rows with their metadata, the audit rows, the fill
    message's own words and the bell. JSON-safe, with this run's clock and
    ids scrubbed, so two runs of one decision compare equal."""
    from alerts.models import Notification
    from bot_program.audit_models import AuditLogEntry
    cand = out.cand
    snap = {
        "candidate": None if cand is None else {
            "venue": cand.venue, "qty_default": cand.qty_default,
            "price": cand.price, "stop": cand.stop, "target": cand.target,
            "per_unit_risk": cand.per_unit_risk,
            "risk_dollars_default": cand.risk_dollars_default,
            "notional_default": cand.notional_default,
            "fractional_units": cand.fractional_units,
            "stage": cand.stage, "sizing": cand.sizing,
            "level_meta": cand.level_meta},
        "result": (None if out.res is None else
                   {k: out.res.get(k) for k in ("symbol", "side", "qty",
                                                "entry", "score")}),
        "orders": orders(out),
        "rows_asked": list(getattr(out.venue, "asked", [])),
        "quotes_asked": out.venue.ticker.call_count,
        "wire": len(getattr(getattr(out.venue, "wire", None), "calls", [])),
        "skip": skip_of(out),
        "skip_counts": out.cfg.extras.get("skip_counts") or {},
        "config_notes": sorted(k for k in out.cfg.extras
                               if k not in (out.world.get("extras") or {})),
        "trades": [{
            "symbol": t.symbol, "side": t.side, "qty": t.qty,
            "entry_price": t.entry_price, "stop_loss": t.stop_loss,
            "take_profit": t.take_profit, "paper": t.paper,
            "status": t.status, "rule_name": t.rule_name,
            "broker_order_id": t.broker_order_id, "reason": t.reason,
            "metadata": t.metadata} for t in trade_rows(out)],
        "audit": [e.data for e in AuditLogEntry.objects.filter(
            user=out.cfg.user, kind="trade_open").order_by("id")],
        "fill_words": [{k: v for k, v in sorted(c.kwargs.items())
                        if isinstance(v, str)}
                       for c in out.note.call_args_list],
        "fill_arguments": [sorted(c.kwargs) for c in out.note.call_args_list],
        "bell": [[n.title, n.body] for n in Notification.objects.filter(
            user=out.cfg.user).order_by("id")],
    }
    return json.loads(json.dumps(scrub(snap), sort_keys=True))
