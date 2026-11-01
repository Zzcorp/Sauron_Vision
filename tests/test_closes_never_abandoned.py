"""A REAL POSITION IS NEVER ABANDONED WHILE eTORO STILL HOLDS IT
(2026-11-01).

The operator reported that Sauron counts less used capital than eToro
shows. The investigation found three ways a real row left every Sauron sum
while eToro still held its position:

  * A QUEUED CLOSE SPENT ITS BUDGET ON FAILED READS. While eToro holds a
    close (a shut market), every drain pass whose order lookup failed fell
    through to the cancel gate; eToro cannot cancel a close order, so the
    pass was booked as a failed attempt although nothing was sent. Twelve
    such passes gave ERROR. A pass now notes the close blocked and spends
    nothing (pending_closes.retry_trade_close, EtoroTrader
    .CANCELS_CLOSE_ORDERS).
  * A LANE STOOD DOWN TO PAPER, OR AN UNTICKED CLASS BOX, HANDED THE ROW
    THE SIMULATOR. Today's routing answered PaperTrader, and the drain spent
    an attempt per pass: ERROR in about an hour. The kill switch, the CLOSE
    button and the manage tick refused the row, the braked pass skipped its
    working order, and the reconcile could not read its venue. A live eToro
    row now goes to its own carrier, in its own world
    (broker_router.client_for_row): closes, withdrawals and protective moves
    only, never an entry. With the keys gone, or the account trading the
    other world, the drain notes the close blocked instead of spending an
    attempt.
  * A CLOSE SAURON GAVE UP ON LEFT EVERY SUM. A row eToro refused to close
    twelve times went to ERROR and out of used, the exposure gate, the
    open-risk gate and the TAKE TRADE lane's pool. It now stays counted
    while the carrier's stored holdings list it, or cannot say
    (portfolio.services.abandoned_still_held); the split's "Sauron stopped
    closing" reads the same predicate.

Over a fake eToro wire: the REAL router, adapter, lanes, drain, kill
switch, CLOSE button, reconcile and manage tick; only the HTTP session is
fake, and no socket may open. Ported from the investigation's red tests
(R4, R5, R6, R7) and guards (G1, G2, G3), and from its skeptics' (the
healthy queued close, the refused close that still reaches ERROR).
CONSTRUCTED marks an eToro answer nobody measured. Illustrative round
numbers only; no account figures.

Run with:  python manage.py test tests.test_closes_never_abandoned
"""
import ast
import copy
import json
import socket
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import requests
from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

LOCMEM = {"default": {"BACKEND":
                      "django.core.cache.backends.locmem.LocMemCache"}}
BASE = "bot_program.asset_engine.base.AssetBot"
BEAT_S = 300                 # config/celery.py retry-pending-closes cadence
REFUSE = {"status": 400, "payload": {"message": "CONSTRUCTED: refused"}}


# ── the wire ─────────────────────────────────────────────────────────────

class _Guard:
    """Every connect raises and is recorded: no test may open a socket."""

    def __init__(self):
        self.attempts = []

    def start(self, testcase):
        guard = self
        real_connect = socket.socket.connect

        def _connect(sock, address, *a, **k):
            if getattr(sock, "family", None) == getattr(socket, "AF_UNIX",
                                                        object()):
                return real_connect(sock, address, *a, **k)
            guard.attempts.append(repr(address))
            raise ConnectionRefusedError(f"test: no network ({address!r})")

        def _create_connection(address, *a, **k):
            guard.attempts.append(repr(address))
            raise ConnectionRefusedError(f"test: no network ({address!r})")

        for p in (mock.patch.object(socket.socket, "connect", _connect),
                  mock.patch("socket.create_connection", _create_connection)):
            p.start()
            testcase.addCleanup(p.stop)
        return self


class _Resp:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = {} if payload is None else payload
        self.text = json.dumps(self._payload, default=str)[:400]
        self.headers = {}

    def json(self):
        return copy.deepcopy(self._payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}: "
                                     f"{self.text[:120]}")


class _Wire:
    """eToro's answers: /search, /rates, orders:lookup, /portfolio,
    aggregate-portfolio, eligibility, the order POST, the market close POST,
    the position PATCH and the order DELETE. Every call is recorded.

    `close_plans` answers the close POSTs in turn, the last one repeating:
    "queue" (eToro takes the close and holds it, the shut market: the
    position stays listed and its open order reads "open"), a dict
    {"status", "payload"} (an answer, a refusal for 4xx), or anything else
    (closed at once). `fail_lookup` makes every orders:lookup answer a
    CONSTRUCTED 500."""

    def __init__(self):
        self.headers = {}
        self.calls = []
        self.by_wire, self.by_iid = {}, {}
        self.lookups = {}
        self.portfolio = []
        self.totals = None
        self.orders = []
        self.close_plans = []
        self.fail_lookup = False
        self._oid, self._pid = 990000000, 880000000

    def add(self, symbol, wire, iid, price, row):
        inst = {"symbol": symbol, "wire": wire, "iid": iid,
                "price": float(price), "row": row}
        self.by_wire[wire] = inst
        self.by_iid[iid] = inst

    def get(self, url, params=None, **kw):
        self.calls.append(("GET", url, dict(params or {})))
        return self._get(url, params or {})

    def post(self, url, json=None, **kw):
        self.calls.append(("POST", url, copy.deepcopy(json)))
        return self._post(url, json or {})

    def patch(self, url, json=None, **kw):
        self.calls.append(("PATCH", url, copy.deepcopy(json)))
        return _Resp(200, {})

    def put(self, url, json=None, **kw):
        self.calls.append(("PUT", url, copy.deepcopy(json)))
        return _Resp(200, {})

    def delete(self, url, **kw):
        self.calls.append(("DELETE", url, None))
        oid = url.rstrip("/").rsplit("/", 1)[-1]
        seq = self.lookups.get(oid)
        if seq:
            lk = copy.deepcopy(seq[0])
            lk["status"] = {"id": 7, "name": "Canceled", "errorCode": 0}
            self.lookups[oid] = [lk]
        return _Resp(202, {"orderId": oid, "referenceId": ""})

    def _get(self, url, params):
        if "/market-data/search" in url:
            inst = self.by_wire.get(str(params.get("internalSymbolFull") or ""))
            return _Resp(200, [] if inst is None else [
                {"instrumentId": inst["iid"],
                 "internalSymbolFull": inst["wire"]}])
        if "/market-data/instruments/rates" in url:
            try:
                iid = int(str(params.get("instrumentIds") or "0"))
            except ValueError:
                iid = 0
            inst = self.by_iid.get(iid)
            if inst is None:
                return _Resp(200, {"rates": []})
            return _Resp(200, {"rates": [{
                "instrumentID": iid, "bid": inst["price"],
                "ask": inst["price"], "lastExecution": inst["price"]}]})
        if "orders:lookup" in url:
            if self.fail_lookup:
                return _Resp(500, {"message": "CONSTRUCTED: transient"})
            seq = self.lookups.get(str(params.get("orderId") or ""))
            if not seq:
                return _Resp(404, {"message": "no such order"})
            return _Resp(200, seq[0])
        if url.rstrip("/").endswith("/info/portfolio") or \
                url.rstrip("/").endswith("/info/demo/portfolio"):
            return _Resp(200, {"clientPortfolio": {
                "positions": copy.deepcopy(self.portfolio)}})
        if "aggregate-portfolio" in url:
            return (_Resp(404, {}) if self.totals is None
                    else _Resp(200, self.totals))
        return _Resp(404, {"message": f"test wire: no route {url}"})

    def _post(self, url, body):
        if url.endswith("/execution/orders") or \
                url.endswith("/execution/demo/orders"):
            return self._order(body)
        if url.endswith("/info/eligibility") or \
                url.endswith("/info/demo/eligibility"):
            rows = [copy.deepcopy(self.by_iid[i]["row"])
                    for i in body.get("instrumentIds") or []
                    if i in self.by_iid]
            return _Resp(200, {"currency": "usd", "eligibilities": rows})
        if "market-close-orders/positions/" in url:
            return self._close(url)
        return _Resp(404, {"message": f"test wire: no route {url}"})

    def _order(self, body):
        inst = self.by_wire.get(str(body.get("symbol") or ""))
        self._oid += 1
        self._pid += 1
        oid, pid = self._oid, self._pid
        lk = _lookup(oid, pid, inst, body)
        self.lookups[str(oid)] = [lk]
        self.orders.append({"oid": oid, "pid": pid, "lookup": lk})
        ex = lk["positionExecutions"][0]
        self.portfolio.append(_portfolio_row(
            pid, inst["iid"], ex["openingData"]["units"],
            ex["openingData"]["avgPrice"], int(lk["asset"]["leverage"]),
            amount=ex["marginAccountCurrency"], order_id=oid))
        return _Resp(200, {"token": "<test>", "orderId": oid,
                           "referenceId": "<test>"})

    def _close(self, url):
        pid = url.rstrip("/").rsplit("/", 1)[-1]
        plan = None
        if self.close_plans:
            plan = (self.close_plans.pop(0) if len(self.close_plans) > 1
                    else self.close_plans[0])
        if isinstance(plan, dict):
            return _Resp(plan["status"], plan["payload"])
        if plan == "queue":
            return _Resp(200, {"orderForClose": {
                "positionID": int(pid), "orderID": 770000001,
                "orderType": 19, "statusID": 1}, "token": "<test>"})
        self.close_at_once(pid)
        return _Resp(200, {"orderForClose": {
            "positionID": int(pid), "orderID": 770000002, "orderType": 19,
            "statusID": 1}, "token": "<test>"})

    def close_at_once(self, pid):
        """eToro closes the position: delisted, its open order "closed"."""
        pid = str(pid)
        self.portfolio = [p for p in self.portfolio
                          if str(p.get("positionID")) != pid]
        for o in self.orders:
            if str(o["pid"]) == pid:
                lk = copy.deepcopy(o["lookup"])
                for ex in lk.get("positionExecutions") or []:
                    ex["state"] = "closed"
                self.lookups[str(o["oid"])] = [lk]


def _lookup(order_id, position_id, inst, body):
    """orders:lookup in the measured shape (tests/test_etoro_client.py),
    composed from the POST: filled at the instrument's price, margin =
    units x price / the multiplier sent."""
    units = float(body.get("units") or 0)
    lev = int(body.get("leverage") or 1)
    avg = inst["price"]
    margin = round(units * avg / lev, 2)
    return {
        "orderId": order_id, "action": "open",
        "transaction": "buy" if body.get("transaction") == "buy" else "sell",
        "type": "mkt", "status": {"id": 3, "name": "Filled", "errorCode": 0},
        "asset": {"symbol": inst["wire"], "instrumentId": inst["iid"],
                  "currency": "USD", "settlementType": "CFD",
                  "leverage": lev,
                  "side": ("long" if body.get("transaction") == "buy"
                           else "short")},
        "requestedAmount": margin, "requestedUnits": units,
        "frozenAmount": margin,
        "openStopLossRate": body.get("stopLossRate"),
        "openTakeProfitRate": body.get("takeProfitRate"),
        "totalCosts": 0.0,
        "positionExecutions": [{
            "positionId": position_id, "state": "open",
            "marginAccountCurrency": margin, "remainingUnits": units,
            "stopLossRate": body.get("stopLossRate"),
            "takeProfitRate": body.get("takeProfitRate"),
            "openingData": {"units": units, "avgPrice": avg, "fees": 0.0}}]}


def _portfolio_row(position_id, iid, units, open_rate, leverage, *,
                   amount=None, order_id=0):
    """One /portfolio row on the measured GLDM row's keys."""
    from tests.test_etoro_client import PORTFOLIO_ROW
    amt = (round(units * open_rate / max(int(leverage), 1), 2)
           if amount is None else float(amount))
    return dict(PORTFOLIO_ROW, positionID=int(position_id),
                instrumentID=int(iid), isBuy=True, units=float(units),
                initialUnits=float(units), openRate=float(open_rate),
                amount=amt, initialAmountInDollars=amt,
                unitsBaseValueDollars=round(units * open_rate, 2),
                leverage=int(leverage), orderID=int(order_id or 0),
                takeProfitRate=0.0, stopLossRate=0.0)


#: The two instruments these tests trade: the catalogue symbol, eToro's
#: spelling and id, the price, a size and its stop and target.
CASES = {
    "gold": dict(symbol="XAUUSD", wire="GOLD", iid=18, price=4000.0,
                 units=0.5, legs=(3880.0, 4240.0)),
    "oil": dict(symbol="WTIUSD", wire="OIL", iid=17, price=60.0,
                units=30.0, legs=(58.2, 63.6)),
}


def _commodity_row(iid, sym):
    """A commodity eligibility row (WHEAT.FUT's printed LIVE lists)."""
    from tests.test_etoro_client import _elig_row, _lev
    return _elig_row(iid, sym, [
        _lev("cfd", "long", [1], max_sl=100, min_amount=25),
        _lev("cfd", "long", [2, 5, 10], min_amount=25),
        _lev("cfd", "short", [1, 2, 5, 10], min_amount=25)],
        min_exposure=1000, w8=False)


def _world(testcase, username):
    """A staff user, a keyed LIVE eToro account flagged for every class
    with fresh cells, the platform switches on, both instruments quoted,
    and the wire under every EtoroTrader. (user, account, wire, guard)."""
    from django.core.cache import cache

    from bot_program.engine.etoro_client import EtoroTrader
    from bot_program.models import EtoroAccount
    from core.platform_control import PlatformComponent
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    from portfolio.models import Portfolio
    from tests.test_etoro_client import _clear_eligibility
    cache.clear()
    testcase.addCleanup(cache.clear)
    _clear_eligibility()
    testcase.addCleanup(_clear_eligibility)
    guard = _Guard().start(testcase)
    user = User.objects.create_user(username, password="x", is_staff=True)
    for key, on in (("platform_master", True), ("pipeline_asset_bots", True),
                    ("broker_account_sync", True),
                    ("etoro_leverage_live", False)):
        PlatformComponent.objects.update_or_create(
            key=key, defaults={"name": key, "category": "system",
                               "is_enabled": on})
    now = timezone.now()
    acct = EtoroAccount.objects.create(
        user=user, demo=False, label="Main", is_primary_for_stocks=True,
        is_primary_for_forex=True, is_primary_for_commodity=True,
        is_primary_for_crypto=True, connected=True)
    acct.set_credentials("test-api-key", "test-user-key")
    acct.last_equity = Decimal("100000")
    acct.last_equity_currency = "USD"
    acct.last_equity_at = now
    acct.last_available_cash = Decimal("100000")
    acct.last_used_margin = Decimal("0")
    acct.last_margin_at = now
    acct.last_margin_world = "live"
    acct.save()
    Portfolio.objects.get_or_create(
        name=f"{user.username}_main",
        defaults={"initial_capital": Decimal("100000"),
                  "current_value": Decimal("100000"),
                  "cash_available": Decimal("100000"), "currency": "USD"})
    wire = _Wire()
    for c in CASES.values():
        wire.add(c["symbol"], c["wire"], c["iid"], c["price"],
                 _commodity_row(c["iid"], c["wire"]))
        inst, _ = Instrument.objects.get_or_create(
            symbol=c["symbol"], defaults={"name": c["symbol"],
                                          "asset_class": "commodity",
                                          "is_active": True})
        LiveQuote.objects.update_or_create(
            instrument=inst, defaults={"last": Decimal(str(c["price"])),
                                       "source": "yfinance"})
    p = mock.patch.object(EtoroTrader, "_sess", lambda self: wire)
    p.start()
    testcase.addCleanup(p.stop)
    ps = mock.patch("time.sleep")
    ps.start()
    testcase.addCleanup(ps.stop)
    return user, acct, wire, guard


def _config(user, name, symbols, *, mode="live"):
    from bot_program.models import AssetBotConfig
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class="commodity", name=name,
        defaults={"mode": mode, "symbols": list(symbols),
                  "capital": Decimal("100000"), "enabled": True,
                  "base_currency": "USD", "extras": {}})
    return cfg


def _gates_pass(testcase):
    """The four pre-send judgements that are not the booking, answered
    'pass': the size judge, the venue fee, the last look and the AI."""
    for p in (mock.patch(f"{BASE}._judge_final_size", return_value=True),
              mock.patch(f"{BASE}._venue_fee_refusal", return_value=(0.0, "")),
              mock.patch(f"{BASE}._last_look", return_value={}),
              mock.patch("ai_agents.agents.trade_debate.debate_candidate",
                         return_value={}),
              mock.patch("ai_agents.agents.council.after_send",
                         return_value=None)):
        p.start()
        testcase.addCleanup(p.stop)


def _book_bot(user, cfg, key):
    """One entry through AssetBot.execute_entry on a hand-built candidate,
    the order through the real router and adapter onto the wire."""
    from bot_program.asset_engine.base import BotDecision, make_bot
    from bot_program.asset_engine.candidates import EntryCandidate
    from bot_program.models import AssetBotTrade
    from instruments.models import Instrument
    c = CASES[key]
    bot = make_bot(cfg)
    vpu = float(bot._value_per_unit(c["symbol"]))
    stop, target = c["legs"]
    pur = abs(c["price"] - stop) * vpu
    cand = EntryCandidate(
        bot=bot, cfg_id=cfg.id, user_id=user.id, symbol=c["symbol"],
        instrument_id=Instrument.objects.get(symbol=c["symbol"]).id,
        asset_class=bot.asset_class, venue="live",
        decision=BotDecision(direction="BUY", score=0.9, reasons=["test"],
                             rule_name="test_rule"),
        price=c["price"], market_price=c["price"], stop=stop, target=target,
        level_meta={}, cost_reason="",
        stage={"force_paper": False, "stage": "live_full"},
        sizing={"risk_fraction": 0.01, "risk_dollars": pur * c["units"],
                "notional_fraction": (c["price"] * c["units"] * vpu
                                      / float(cfg.capital)),
                "value_per_unit": vpu, "stop_widened": False},
        qty_default=c["units"], per_unit_risk=pur,
        risk_dollars_default=pur * c["units"],
        notional_default=c["price"] * c["units"] * vpu, value_per_unit=vpu)
    cand.fractional_units = None
    res = bot.execute_entry(cand)
    return (AssetBotTrade.objects.get(pk=res["trade_id"])
            if res and res.get("trade_id") else None)


@override_settings(CACHES=LOCMEM)
class _Base(TestCase):

    username = "abandon_op"

    def setUp(self):
        self.user, self.acct, self.wire, self.guard = _world(self,
                                                             self.username)
        _gates_pass(self)

    def tearDown(self):
        self.assertEqual(self.guard.attempts, [], "a socket was opened")

    # the figures
    def _used(self):
        from portfolio.services import capital_summary
        return capital_summary(User.objects.get(pk=self.user.pk))["used_live"]

    def _gate(self):
        from portfolio.risk_gate import limits_book, open_capital_at_work
        return open_capital_at_work(self.user, limits_book())["live_total"]

    def _open_risk(self):
        from portfolio.risk_gate import limits_book, open_risk_state
        book = limits_book()
        book.max_open_risk_pct = Decimal("50")
        book.save(update_fields=["max_open_risk_pct"])
        return open_risk_state(self.user, portfolio=book,
                               venue="live")["open_risk"]

    # the rows
    def _gold_row(self, name="gold bot"):
        cfg = _config(self.user, name, ["XAUUSD"])
        row = _book_bot(self.user, cfg, "gold")
        self.assertIsNotNone(row)
        self.assertEqual(row.metadata.get("broker"), "etoro")
        return cfg, row

    def _close_now(self, row):
        """The bot's own close, routed as the lane routes it today (live,
        box ticked)."""
        from bot_program.asset_engine.base import make_bot
        from bot_program.engine.broker_router import client_for_symbol
        client = client_for_symbol(self.user, row.symbol, row.config)
        return make_bot(row.config)._close_trade(row, Decimal("3990"),
                                                 client, reason="SL")

    def _drain_at(self, when):
        from bot_program.pending_closes import retry_all_pending_closes
        with mock.patch("django.utils.timezone.now", return_value=when):
            return retry_all_pending_closes()

    def _passes(self, row, n, *, start=None, stop_early=True):
        t0 = start or timezone.now()
        for i in range(n):
            self._drain_at(t0 + timedelta(seconds=BEAT_S * (i + 1)))
            row.refresh_from_db()
            if stop_early and row.status != "CLOSE_PENDING":
                break
        return row

    def _stand_down(self, cfg):
        """The lane set to paper, as /brokers/ and the lane switch do."""
        cfg.mode = "paper"
        cfg.save(update_fields=["mode"])

    def _untick_commodity(self):
        self.acct.is_primary_for_commodity = False
        self.acct.save(update_fields=["is_primary_for_commodity"])

    # the wire
    def _held(self, iid=18):
        return [p["amount"] for p in self.wire.portfolio
                if p["instrumentID"] == iid]

    def _order_posts(self):
        return [c for c in self.wire.calls if c[0] == "POST"
                and (c[1].endswith("/execution/orders")
                     or c[1].endswith("/execution/demo/orders"))]

    def _close_posts(self):
        return [c for c in self.wire.calls if c[0] == "POST"
                and "market-close-orders" in c[1]]

    def _lookups(self):
        return sum(1 for c in self.wire.calls
                   if c[0] == "GET" and "orders:lookup" in c[1])

    def _alerts(self, words):
        from alerts.models import Notification
        return Notification.objects.filter(title__icontains=words).count()

    def _abandon(self, row):
        """The route that stays valid after every fix: eToro refuses the
        close POST at every beat (CONSTRUCTED 400) -> twelve failed attempts
        -> pending_closes._give_up -> ERROR, closed_at None."""
        self.wire.close_plans = [REFUSE]
        self._close_now(row)
        self._passes(row, 20)
        self.assertEqual(row.status, "ERROR")
        self.assertIsNone(row.closed_at)
        # twelve passes take an hour: the position opened before any
        # holdings read the tests store below
        type(row).objects.filter(pk=row.pk).update(
            opened_at=timezone.now() - timedelta(hours=3))
        row.refresh_from_db()
        return row

    def _snapshot(self, positions, *, age_s=60):
        """The holdings snapshot as the sync stores it (broker_portfolio
        keeps the position id and eToro's amount), read `age_s` ago."""
        self.acct.broker_positions = positions
        self.acct.broker_positions_at = (timezone.now()
                                         - timedelta(seconds=age_s))
        self.acct.save(update_fields=["broker_positions",
                                      "broker_positions_at"])

    def _gold_held(self, pid):
        return {"symbol": "XAUUSD", "sec_type": "CFD", "qty": 0.5,
                "side": "BUY", "avg_cost": 4000.0, "leverage": 1,
                "position_id": str(pid), "amount": 2000.0}

    def _hold_as_working(self, row):
        """The row's order held by eToro (WaitingForMarket, nothing filled)
        and the row WORKING, as a held entry is booked."""
        oid = str(row.broker_order_id)
        held = copy.deepcopy(self.wire.lookups[oid][0])
        held["status"] = {"id": 11, "name": "WaitingForMarket",
                          "errorCode": 0}
        held["positionExecutions"] = []
        self.wire.lookups[oid] = [held]
        self.wire.portfolio = []
        meta = dict(row.metadata)
        meta.update({"entry_working": True, "qty_requested": float(row.qty)})
        type(row).objects.filter(pk=row.pk).update(metadata=meta)
        row.refresh_from_db()
        return row

    def _deletes(self):
        return [c for c in self.wire.calls if c[0] == "DELETE"]


# ── fix 3: a queued close spends no attempt while nothing is sent ─────────

class TheQueuedCloseSpendsNothingTests(_Base):

    def test_failed_lookups_beside_a_queued_close_spend_no_attempt(self):
        """R4. 240 passes (20 h) with one lookup in twenty failing: twelve
        failed reads used to spend twelve attempts ("could not be cancelled,
        refusing to stack") and give ERROR while eToro held the position."""
        from bot_program import pending_closes as pc
        _cfg, row = self._gold_row()
        self.wire.close_plans = ["queue"]
        self._close_now(row)
        row.refresh_from_db()
        self.assertEqual(row.status, "CLOSE_PENDING")
        self.assertTrue(row.metadata.get(pc.CLOSE_ORDER_WORKING_KEY))
        t0 = timezone.now()
        fails = 0
        for i in range(240):
            self.wire.fail_lookup = (i % 20 == 19)
            fails += int(self.wire.fail_lookup)
            self._drain_at(t0 + timedelta(seconds=BEAT_S * (i + 1)))
        self.wire.fail_lookup = False
        row.refresh_from_db()
        self.assertEqual(fails, 12)
        self.assertEqual(row.status, "CLOSE_PENDING")
        self.assertFalse(row.metadata.get("close_retry_attempts"))
        self.assertIn("nothing sent", row.metadata.get("close_blocked_why", ""))
        self.assertEqual(self._used(), 2000.0)
        self.assertEqual(self._gate(), 2000.0)
        self.assertEqual(self._held(), [2000.0])
        # nothing was stacked on the queued close
        self.assertEqual(len(self._close_posts()), 1)

    def test_a_failed_lookup_pass_says_what_it_could_not_read(self):
        """The words are the venue-proved block's, and true for this pass:
        the order read did not answer, the list still shows the position."""
        _cfg, row = self._gold_row()
        self.wire.close_plans = ["queue"]
        self._close_now(row)
        self.wire.fail_lookup = True
        self._passes(row, 1)
        why = row.metadata.get("close_blocked_why", "")
        self.assertIn("a close order is queued there that this adapter can "
                      "neither list nor cancel", why)
        self.assertIn("did not answer", why)
        self.assertNotIn("still shows the position OPEN", why)
        self.assertFalse(row.metadata.get("close_retry_attempts"))

    def test_healthy_lookups_over_a_queued_close_spend_nothing(self):
        """The skeptics' control: 100 healthy passes, 0 attempts."""
        _cfg, row = self._gold_row()
        self.wire.close_plans = ["queue"]
        self._close_now(row)
        self._passes(row, 100)
        self.assertEqual(row.status, "CLOSE_PENDING")
        self.assertIsNone(row.metadata.get("close_retry_attempts"))
        self.assertEqual(self._used(), 2000.0)

    def test_a_refused_close_still_reaches_error_in_twelve_passes(self):
        """The skeptics' k1b: a close eToro REFUSES at every beat is a real
        failure, and the budget still ends it."""
        _cfg, row = self._gold_row()
        self.wire.close_plans = [REFUSE]
        self._close_now(row)
        t0 = timezone.now()
        passes = 0
        while row.status == "CLOSE_PENDING" and passes < 20:
            self._drain_at(t0 + timedelta(seconds=BEAT_S * (passes + 1)))
            row.refresh_from_db()
            passes += 1
        self.assertEqual(row.status, "ERROR")
        self.assertEqual(passes, 12)
        self.assertEqual(row.metadata.get("close_retry_attempts"), 12)

    def test_the_book_reading_flat_still_books_the_close(self):
        """The flat path above the new gate is unchanged: eToro executes the
        queued close at the reopen while its order read is failing, the list
        no longer shows the position, and an hour of unanswered asks books
        the row (venue_exit.after_no_answer), spending nothing."""
        _cfg, row = self._gold_row()
        self.wire.close_plans = ["queue"]
        self._close_now(row)
        self.wire.portfolio = []
        self.wire.fail_lookup = True
        self._passes(row, 20)
        self.assertEqual(row.status, "CLOSED")
        self.assertFalse(row.metadata.get("close_retry_attempts"))

    def test_the_venue_declares_it_cannot_cancel_a_close_order(self):
        from bot_program.engine.etoro_client import EtoroTrader
        from bot_program.engine.paper_trader import PaperTrader
        self.assertIs(EtoroTrader.CANCELS_CLOSE_ORDERS, False)
        self.assertFalse(hasattr(PaperTrader, "CANCELS_CLOSE_ORDERS"))


# ── fix 4: the row's own carrier ──────────────────────────────────────────

class TheDrainAsksTheRowsOwnCarrierTests(_Base):

    def test_lane_stood_down_to_paper_the_drain_still_asks_etoro(self):
        """R5. The router used to hand the drain PaperTrader: an attempt per
        pass, ERROR in twelve, and no lookup ever asked of eToro."""
        cfg, row = self._gold_row()
        self.wire.close_plans = ["queue"]
        self._close_now(row)
        self._stand_down(cfg)
        n0 = self._lookups()
        self._passes(row, 20)
        self.assertEqual(row.status, "CLOSE_PENDING")
        self.assertFalse(row.metadata.get("close_retry_attempts"))
        self.assertGreater(self._lookups() - n0, 0)
        self.assertEqual(self._used(), 2000.0)
        self.assertEqual(len(self._close_posts()), 1)

    def test_commodity_box_unticked_the_drain_still_asks_etoro(self):
        """R6. Commodity has no default venue, so unticked it routed to
        paper."""
        _cfg, row = self._gold_row()
        self.wire.close_plans = ["queue"]
        self._close_now(row)
        self._untick_commodity()
        n0 = self._lookups()
        self._passes(row, 20)
        self.assertEqual(row.status, "CLOSE_PENDING")
        self.assertFalse(row.metadata.get("close_retry_attempts"))
        self.assertGreater(self._lookups() - n0, 0)

    def test_on_a_stood_down_lane_a_refused_close_is_sent_to_etoro(self):
        """The one order-path change: a pending close nothing holds at
        eToro (the first close was refused) is SENT to eToro on a lane
        stood down to paper, by position id, and booked; before, nothing
        was sent and the row was abandoned after about an hour."""
        cfg, row = self._gold_row()
        self.wire.close_plans = [REFUSE, "close"]
        self._close_now(row)
        row.refresh_from_db()
        self.assertEqual(row.status, "CLOSE_PENDING")
        self._stand_down(cfg)
        n_orders = len(self._order_posts())
        self._passes(row, 3)
        self.assertEqual(row.status, "CLOSED")
        self.assertEqual(self._held(), [])
        self.assertEqual(len(self._close_posts()), 2)
        self.assertEqual(len(self._order_posts()), n_orders,
                         "a close opened something")

    def test_keys_gone_the_drain_notes_the_close_blocked(self):
        """The keys removed: the row's carrier cannot be reached. Nothing
        was sent and nothing was refused, so no attempt is spent (it used to
        be, and the row went to ERROR in an hour)."""
        from bot_program.models import EtoroAccount
        _cfg, row = self._gold_row()
        self.wire.close_plans = ["queue"]
        self._close_now(row)
        EtoroAccount.objects.filter(pk=self.acct.pk).update(api_key_enc="",
                                                             user_key_enc="")
        self._passes(row, 20)
        self.assertEqual(row.status, "CLOSE_PENDING")
        self.assertFalse(row.metadata.get("close_retry_attempts"))
        self.assertIn("nothing", row.metadata.get("close_blocked_why", ""))
        self.assertEqual(len(self._close_posts()), 1)

    def test_the_account_now_trades_the_other_world_nothing_is_sent(self):
        """Demo ticked with a real close pending (a guarded save refuses it
        on the page; set here by hand): nothing goes to either world."""
        from bot_program.models import EtoroAccount
        _cfg, row = self._gold_row()
        self.wire.close_plans = [REFUSE, "close"]
        self._close_now(row)
        EtoroAccount.objects.filter(pk=self.acct.pk).update(demo=True)
        self._passes(row, 20)
        self.assertEqual(row.status, "CLOSE_PENDING")
        self.assertFalse(row.metadata.get("close_retry_attempts"))
        self.assertEqual(len(self._close_posts()), 1)
        self.assertEqual(self._held(), [2000.0])


class ClientForRowTests(_Base):

    def _row(self, **meta):
        from bot_program.models import AssetBotTrade
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        m = {"broker": "etoro", "broker_env": "live"}
        m.update(meta)
        return AssetBotTrade.objects.create(
            config=cfg, asset_class="commodity", symbol="XAUUSD", side="BUY",
            qty=Decimal("0.5"), entry_price=Decimal("4000"), status="OPEN",
            paper=False, metadata={k: v for k, v in m.items()
                                   if v is not None})

    def _client(self, row):
        """client_for_row over the row as a pass loads it: its config and
        owner read fresh (the drain's claim select_related's both)."""
        from bot_program.engine.broker_router import client_for_row
        from bot_program.models import AssetBotTrade
        return client_for_row(AssetBotTrade.objects.select_related(
            "config", "config__user").get(pk=row.pk))

    def test_a_live_etoro_row_gets_etoro_whatever_the_lane_and_the_box(self):
        from bot_program.engine.etoro_client import EtoroTrader
        row = self._row()
        self._stand_down(row.config)
        row.refresh_from_db()
        client = self._client(row)
        self.assertIsInstance(client, EtoroTrader)
        self.assertEqual(client.env, "live")
        self._untick_commodity()
        self.assertIsInstance(self._client(row), EtoroTrader)

    def test_keys_gone_or_the_other_world_is_the_simulator(self):
        from bot_program.engine.paper_trader import PaperTrader
        from bot_program.models import EtoroAccount
        row = self._row()
        EtoroAccount.objects.filter(pk=self.acct.pk).update(demo=True)
        self.assertIsInstance(self._client(row), PaperTrader)
        EtoroAccount.objects.filter(pk=self.acct.pk).update(
            demo=False, api_key_enc="", user_key_enc="")
        self.assertIsInstance(self._client(row), PaperTrader)

    def test_a_demo_row_gets_the_demo_world(self):
        from bot_program.engine.etoro_client import EtoroTrader
        from bot_program.models import EtoroAccount
        EtoroAccount.objects.filter(pk=self.acct.pk).update(demo=True)
        row = self._row(broker_env="paper")
        self._stand_down(row.config)
        row.refresh_from_db()
        client = self._client(row)
        self.assertIsInstance(client, EtoroTrader)
        self.assertEqual(client.env, "demo")

    def test_every_other_row_goes_through_todays_routing(self):
        from bot_program.engine import broker_router
        sentinel = object()
        for row in (self._row(broker="saxo"), self._row(broker=None)):
            with mock.patch.object(broker_router, "client_for_symbol",
                                   return_value=sentinel) as routed:
                self.assertIs(self._client(row), sentinel)
            routed.assert_called_once()
        paper = self._row()
        type(paper).objects.filter(pk=paper.pk).update(paper=True)
        paper.refresh_from_db()
        with mock.patch.object(broker_router, "client_for_symbol",
                               return_value=sentinel):
            self.assertIs(self._client(paper), sentinel)


class TheKillSwitchClosesARealRowTests(_Base):

    def _kill(self):
        from bot_program.engine.kill_switch import execute_kill_switch
        return execute_kill_switch(user=self.user, reason="test")

    def test_on_a_lane_stood_down_to_paper(self):
        cfg, row = self._gold_row()
        self._stand_down(cfg)
        n_orders = len(self._order_posts())
        res = self._kill()
        row.refresh_from_db()
        self.assertEqual(res["errors"], [])
        self.assertEqual(res["asset_positions_closed"], 1)
        self.assertEqual(row.status, "CLOSED")
        self.assertEqual(self._held(), [])
        self.assertEqual(len(self._close_posts()), 1)
        self.assertEqual(len(self._order_posts()), n_orders)

    def test_on_an_unticked_class_box(self):
        _cfg, row = self._gold_row()
        self._untick_commodity()
        res = self._kill()
        row.refresh_from_db()
        self.assertEqual(res["errors"], [])
        self.assertEqual(row.status, "CLOSED")
        self.assertEqual(self._held(), [])


class TheCloseButtonClosesARealRowTests(_Base):

    def test_the_preview_on_a_lane_stood_down_to_paper(self):
        from bot_program.manual_close import preview_close
        cfg, row = self._gold_row()
        self._stand_down(cfg)
        row.refresh_from_db()
        out = preview_close(self.user, row)
        self.assertNotIn("error", out)
        self.assertEqual(out["action"], "close")
        self.assertEqual(out["venue"], "live")
        self.assertEqual(out["mark"], 4000.0)

    def test_close_on_a_lane_stood_down_to_paper(self):
        from bot_program.manual_close import execute_close
        cfg, row = self._gold_row()
        self._stand_down(cfg)
        row.refresh_from_db()
        n_orders = len(self._order_posts())
        out = execute_close(self.user, row, pin_ok=True)
        row.refresh_from_db()
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(row.status, "CLOSED")
        self.assertEqual(self._held(), [])
        self.assertEqual(len(self._order_posts()), n_orders)
        self.assertEqual(self._alerts("refused"), 0)

    def test_close_on_an_unticked_class_box(self):
        from bot_program.manual_close import execute_close
        _cfg, row = self._gold_row()
        self._untick_commodity()
        out = execute_close(self.user, row, pin_ok=True)
        row.refresh_from_db()
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(row.status, "CLOSED")

    def test_retry_close_on_a_lane_stood_down_to_paper(self):
        """A CLOSE_PENDING row: the button's RETRY CLOSE is the drain's own
        pass, and it reaches eToro."""
        from bot_program.manual_close import execute_close
        cfg, row = self._gold_row()
        self.wire.close_plans = [REFUSE, "close"]
        self._close_now(row)
        row.refresh_from_db()
        self.assertEqual(row.status, "CLOSE_PENDING")
        self._stand_down(cfg)
        with mock.patch("django.utils.timezone.now",
                        return_value=timezone.now() + timedelta(minutes=5)):
            out = execute_close(self.user, row, pin_ok=True)
        row.refresh_from_db()
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(row.status, "CLOSED")

    def test_withdraw_a_working_entry_on_a_lane_stood_down_to_paper(self):
        """An entry eToro holds as an order: WITHDRAW ORDER cancels it at
        eToro (a DELETE), and opens nothing."""
        from bot_program.manual_close import execute_close
        cfg, row = self._gold_row()
        self._hold_as_working(row)
        self._stand_down(cfg)
        row.refresh_from_db()
        n_orders = len(self._order_posts())
        out = execute_close(self.user, row, pin_ok=True)
        row.refresh_from_db()
        self.assertTrue(out.get("withdrawn"), out)
        self.assertEqual(row.status, "CANCELED")
        self.assertEqual(len(self._deletes()), 1)
        self.assertEqual(len(self._order_posts()), n_orders)


class TheReconcileReadsTheRowsOwnVenueTests(_Base):

    def _reconcile_at(self, when):
        from bot_program.reconcile_asset import reconcile_user
        with mock.patch("django.utils.timezone.now", return_value=when):
            return reconcile_user(self.user)

    def test_a_row_etoro_still_holds_is_never_booked_against_a_paper_book(self):
        """Proven first: on a lane stood down to paper, the reconcile never
        books a real row CLOSED because the simulator holds nothing."""
        cfg, row = self._gold_row()
        self._stand_down(cfg)
        out = self._reconcile_at(timezone.now() + timedelta(minutes=10))
        row.refresh_from_db()
        self.assertEqual(row.status, "OPEN")
        self.assertEqual(out["closed_as_orphan"], 0)

    def test_on_a_stood_down_lane_it_reads_etoros_book(self):
        """The row is judged at eToro: its position listed by id, the row
        checked and open (it used to read nothing, broker unavailable)."""
        cfg, row = self._gold_row()
        self._stand_down(cfg)
        n0 = sum(1 for c in self.wire.calls if c[0] == "GET"
                 and c[1].rstrip("/").endswith("/info/portfolio"))
        out = self._reconcile_at(timezone.now() + timedelta(minutes=10))
        row.refresh_from_db()
        self.assertEqual(row.status, "OPEN")
        self.assertEqual(out["broker_unavailable"], 0)
        self.assertGreater(sum(1 for c in self.wire.calls if c[0] == "GET"
                               and c[1].rstrip("/").endswith(
                                   "/info/portfolio")), n0)

    def test_on_a_stood_down_lane_a_close_etoro_made_is_booked(self):
        """eToro closed the position (its stop, or a hand in its app): its
        order read says closed, and the row is booked from eToro's word and
        eToro's rate; nothing is sent."""
        cfg, row = self._gold_row()
        self._stand_down(cfg)
        self.wire.close_at_once(row.metadata["broker_position_id"])
        # eToro's own rate now; the platform's quote stays at 4000, which
        # sits a whole R from the stop and would be booked AT it (nearest)
        self.wire.by_wire["GOLD"]["price"] = 4100.0
        posts = sum(1 for c in self.wire.calls if c[0] == "POST")
        out = self._reconcile_at(timezone.now() + timedelta(minutes=10))
        row.refresh_from_db()
        self.assertEqual(out["closed_as_orphan"], 1)
        self.assertEqual(row.status, "CLOSED")
        self.assertEqual(row.exit_price, Decimal("4100"))
        self.assertEqual(sum(1 for c in self.wire.calls if c[0] == "POST"),
                         posts)

    def test_on_an_unticked_class_box_it_reads_etoros_book(self):
        _cfg, row = self._gold_row()
        self._untick_commodity()
        out = self._reconcile_at(timezone.now() + timedelta(minutes=10))
        row.refresh_from_db()
        self.assertEqual(row.status, "OPEN")
        self.assertEqual(out["broker_unavailable"], 0)

    def test_keys_gone_a_miss_is_never_booked_against_the_simulator(self):
        """The fallback stays harmless: with the keys gone the row's own
        carrier cannot be asked, the simulator's book holds no AssetBot row
        (its read raises for one), and a position eToro no longer lists is
        booked by nobody; nothing is sent."""
        from bot_program.models import EtoroAccount
        cfg, row = self._gold_row()
        self._stand_down(cfg)
        self.wire.close_at_once(row.metadata["broker_position_id"])
        EtoroAccount.objects.filter(pk=self.acct.pk).update(api_key_enc="",
                                                             user_key_enc="")
        posts = sum(1 for c in self.wire.calls if c[0] == "POST")
        out = self._reconcile_at(timezone.now() + timedelta(minutes=10))
        row.refresh_from_db()
        self.assertEqual(row.status, "OPEN")
        self.assertEqual(out["closed_as_orphan"], 0)
        self.assertEqual(out["broker_unavailable"], 1)
        self.assertEqual(sum(1 for c in self.wire.calls if c[0] == "POST"),
                         posts)


class TheManageTickKeepsCaringForRealRowsTests(_Base):

    def _due(self, cfg, row):
        """The time stop due: a one-hour ceiling, opened three hours ago."""
        cfg.max_hold_hours = 1.0
        cfg.save(update_fields=["max_hold_hours"])
        type(row).objects.filter(pk=row.pk).update(
            opened_at=timezone.now() - timedelta(hours=3))

    def _manage(self, cfg):
        from bot_program.asset_engine.base import make_bot
        cfg.refresh_from_db()
        return make_bot(cfg).manage_positions()

    def test_on_a_lane_stood_down_to_paper_the_time_stop_closes_it(self):
        cfg, row = self._gold_row()
        self._due(cfg, row)
        self._stand_down(cfg)
        n_orders = len(self._order_posts())
        closed = self._manage(cfg)
        row.refresh_from_db()
        self.assertEqual(closed, 1)
        self.assertEqual(row.status, "CLOSED")
        self.assertEqual(self._held(), [])
        self.assertEqual(len(self._close_posts()), 1)
        self.assertEqual(len(self._order_posts()), n_orders,
                         "the manage tick opened something")
        self.assertEqual(self._alerts("LIVE position unmanaged"), 0)

    def test_on_an_unticked_class_box_the_time_stop_closes_it(self):
        cfg, row = self._gold_row()
        self._due(cfg, row)
        self._untick_commodity()
        closed = self._manage(cfg)
        row.refresh_from_db()
        self.assertEqual(closed, 1)
        self.assertEqual(row.status, "CLOSED")
        self.assertEqual(self._alerts("LIVE position unmanaged"), 0)

    def test_on_a_lane_stood_down_to_paper_the_stop_moves_at_etoro(self):
        """A protective move: the trail lifts eToro's stop (a PATCH on the
        position), and nothing opens."""
        cfg, row = self._gold_row()
        cfg.extras = {"trail_pct": 1.0}
        cfg.save(update_fields=["extras"])
        meta = dict(row.metadata)
        meta["protected"] = True
        type(row).objects.filter(pk=row.pk).update(metadata=meta)
        self.wire.by_wire["GOLD"]["price"] = 4100.0
        from market_data.models import LiveQuote
        LiveQuote.objects.filter(instrument__symbol="XAUUSD").update(
            last=Decimal("4100"))
        self._stand_down(cfg)
        n_orders = len(self._order_posts())
        self._manage(cfg)
        row.refresh_from_db()
        patches = [c for c in self.wire.calls if c[0] == "PATCH"]
        self.assertEqual(len(patches), 1, self.wire.calls[-6:])
        self.assertIn("stopLossRate", patches[0][2])
        self.assertGreater(float(row.stop_loss), 3880.0)
        self.assertEqual(row.status, "OPEN")
        self.assertEqual(len(self._order_posts()), n_orders)

    def test_on_a_lane_stood_down_to_paper_a_filled_order_is_booked(self):
        """A real entry eToro held as an order and filled after the lane
        was stood down: the tick reads the order at eToro and books the
        position that already exists, so it is managed. Nothing is sent:
        no order, no cancel (the simulator was asked before, and the row
        stayed WORKING over a real position nothing managed)."""
        cfg, row = self._gold_row()
        oid = str(row.broker_order_id)
        filled = copy.deepcopy(self.wire.lookups[oid][0])
        held_list = copy.deepcopy(self.wire.portfolio)
        self._hold_as_working(row)
        self._stand_down(cfg)
        self.wire.lookups[oid] = [filled]          # eToro filled it since
        self.wire.portfolio = held_list
        n_orders = len(self._order_posts())
        self._manage(cfg)
        row.refresh_from_db()
        self.assertEqual(row.status, "OPEN")
        self.assertFalse(row.metadata.get("entry_working"))
        self.assertTrue(row.metadata.get("entry_filled_at"))
        self.assertEqual(len(self._order_posts()), n_orders)
        self.assertEqual(self._deletes(), [])
        self.assertEqual(self._alerts("LIVE position unmanaged"), 0)

    def test_a_braked_lane_stood_down_withdraws_its_real_working_order(self):
        """The braked pass (manage_only) withdraws a bot's working order at
        eToro, where its poll now reads it; today's routing skipped it as
        the simulator and the order could still fill."""
        from bot_program.asset_engine.base import make_bot
        cfg, row = self._gold_row()
        self._hold_as_working(row)
        self._stand_down(cfg)
        cfg.refresh_from_db()
        n_orders = len(self._order_posts())
        out = make_bot(cfg)._withdraw_working_while_braked("morgul")
        row.refresh_from_db()
        self.assertEqual(out, [row.pk])
        self.assertEqual(row.status, "CANCELED")
        self.assertEqual(len(self._deletes()), 1)
        self.assertEqual(len(self._order_posts()), n_orders)

    def test_the_paper_only_pass_still_never_reads_a_real_row(self):
        """manage_paper_only (a config stopped by hand) is unchanged: a
        real row is never routed there."""
        from bot_program.engine import broker_router
        cfg, row = self._gold_row()
        self._due(cfg, row)
        from bot_program.asset_engine.base import make_bot
        with mock.patch.object(broker_router, "client_for_row") as by_row, \
                mock.patch.object(broker_router, "client_for_symbol") as by_sym:
            make_bot(cfg).manage_positions(paper_only=True)
        by_row.assert_not_called()
        by_sym.assert_not_called()
        row.refresh_from_db()
        self.assertEqual(row.status, "OPEN")


# ── fix 5: an abandoned close that eToro still holds stays counted ────────

class TheAbandonedRowStaysCountedTests(_Base):

    def test_an_abandoned_row_etoro_still_lists_is_counted(self):
        """R7. ERROR, still listed by its position id: used_live, the
        exposure gate and the open-risk gate keep it (all three read 0)."""
        _cfg, row = self._gold_row()
        pid = row.metadata["broker_position_id"]
        self._abandon(row)
        self.assertEqual(self._held(), [2000.0])
        self._snapshot([self._gold_held(pid)])
        self.assertEqual(self._used(), 2000.0)
        self.assertEqual(self._gate(), 2000.0)
        self.assertAlmostEqual(
            self._open_risk(),
            float(row.qty) * (float(row.entry_price) - float(row.stop_loss)),
            2)

    def test_an_abandoned_row_etoro_no_longer_lists_is_not_counted(self):
        """G2. The operator closed it in the eToro app, as the alert asks."""
        _cfg, row = self._gold_row()
        self._abandon(row)
        self._snapshot([])
        self.assertEqual(self._used(), 0.0)
        self.assertEqual(self._gate(), 0.0)
        self.assertEqual(self._open_risk(), 0.0)

    def test_a_missing_or_stale_snapshot_cannot_say_so_it_counts(self):
        from bot_program.capital_truth import TRACKING_FRESH_SECONDS
        _cfg, row = self._gold_row()
        self._abandon(row)
        self.acct.broker_positions = []
        self.acct.broker_positions_at = None          # never read
        self.acct.save(update_fields=["broker_positions",
                                      "broker_positions_at"])
        self.assertEqual(self._gate(), 2000.0)
        self._snapshot([], age_s=TRACKING_FRESH_SECONDS + 60)
        self.assertEqual(self._used(), 2000.0)
        self.assertEqual(self._gate(), 2000.0)

    def test_a_snapshot_of_the_other_world_cannot_say_so_it_counts(self):
        from bot_program.models import EtoroAccount
        _cfg, row = self._gold_row()
        self._abandon(row)
        self._snapshot([])
        EtoroAccount.objects.filter(pk=self.acct.pk).update(demo=True)
        self.assertEqual(self._gate(), 2000.0)

    def test_a_demo_row_given_up_is_not_real_money_while_the_account_is_live(
            self):
        """Review (2026-11-01). A row filled in eToro's DEMO world (paper
        False, broker_env "paper") while the account now trades LIVE is no
        real money, and a live account never stores a demo list that could
        drop it: it was counted in the LIVE exposure and open-risk gates for
        ever, and the refusal told the operator to close at the broker what
        the live account cannot close. Not counted, whatever the list."""
        from portfolio.services import abandoned_still_held
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        self._given_up(cfg, 880000104, env="paper")
        self.assertIsNone(self.acct.broker_positions_at)      # never read
        self.assertEqual(abandoned_still_held(self.user), [])
        self.assertEqual(self._gate(), 0.0)
        self.assertEqual(self._open_risk(), 0.0)
        for held in ([], [self._gold_held(880000999)]):       # a fresh list
            self._snapshot(held)
            self.assertEqual(abandoned_still_held(self.user), [])
            self.assertEqual(self._gate(), 0.0)
            self.assertEqual(self._open_risk(), 0.0)

    def test_a_live_row_given_up_still_counts_while_the_account_is_in_demo(
            self):
        """The other direction stays: a LIVE row while the account is in
        Demo. A demo list cannot say the real position is gone, so it is
        counted (review, 2026-11-01)."""
        from bot_program.models import EtoroAccount
        from portfolio.services import abandoned_still_held
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        row = self._given_up(cfg, 880000105)
        EtoroAccount.objects.filter(pk=self.acct.pk).update(demo=True)
        self._snapshot([])
        self.assertEqual([t.pk for t in abandoned_still_held(self.user)],
                         [row.pk])
        self.assertEqual(self._gate(), 2000.0)
        self.assertAlmostEqual(self._open_risk(), 60.0, 2)

    def test_a_row_with_no_position_id_is_matched_by_symbol_and_side(self):
        _cfg, row = self._gold_row()
        self._abandon(row)
        meta = dict(row.metadata)
        meta.pop("broker_position_id", None)
        type(row).objects.filter(pk=row.pk).update(metadata=meta)
        held = self._gold_held("")
        held["position_id"] = None
        self._snapshot([held])
        self.assertEqual(self._gate(), 2000.0)
        self._snapshot([dict(held, side="SELL")])
        self.assertEqual(self._gate(), 0.0)

    def test_a_snapshot_read_before_the_position_could_be_listed(self):
        """A fresh list read before the position opened (a stalled sync)
        cannot say it is gone; one read after its open and the list's lag
        can."""
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        row = self._given_up(cfg, 880000103)
        type(row).objects.filter(pk=row.pk).update(
            opened_at=timezone.now() - timedelta(minutes=10))
        self._snapshot([], age_s=20 * 60)
        self.assertEqual(self._gate(), 2000.0)
        self._snapshot([], age_s=5 * 60)
        self.assertEqual(self._gate(), 0.0)

    def test_the_exposure_refusal_names_the_abandoned_share(self):
        """A ceiling held by a position no open list shows is said."""
        from portfolio.risk_gate import exposure_state, limits_book
        _cfg, row = self._gold_row()
        pid = row.metadata["broker_position_id"]
        self._abandon(row)
        self._snapshot([self._gold_held(pid)])
        book = limits_book()
        book.max_total_exposure_pct = Decimal("1")
        book.save(update_fields=["max_total_exposure_pct"])
        st = exposure_state(self.user, portfolio=book, venue="live")
        self.assertFalse(st["ok"])
        self.assertEqual(st["committed"], 2000.0)
        self.assertIn("1 of those are closes Sauron gave up on that the "
                      "broker may still hold (2,000.00)", st["reason"])

    def test_an_abandoned_row_never_hides_a_legacy_row_at_risk(self):
        """A legacy portfolio row on the same symbol keeps its own risk: an
        abandoned row is added on top, never in its place."""
        from instruments.models import Instrument
        from portfolio.models import Position
        from portfolio.risk_gate import limits_book
        _cfg, row = self._gold_row()
        pid = row.metadata["broker_position_id"]
        self._abandon(row)
        self._snapshot([self._gold_held(pid)])
        Position.objects.create(
            portfolio=limits_book(),
            instrument=Instrument.objects.get(symbol="XAUUSD"),
            direction="long", quantity=Decimal("1"),
            entry_price=Decimal("4000"), current_price=Decimal("4000"),
            stop_loss=Decimal("3900"), opened_at=timezone.now())
        self.assertAlmostEqual(self._open_risk(), 100.0 + 60.0, 2)

    def test_no_stop_counts_the_whole_notional_at_risk(self):
        _cfg, row = self._gold_row()
        pid = row.metadata["broker_position_id"]
        self._abandon(row)
        type(row).objects.filter(pk=row.pk).update(stop_loss=None)
        self._snapshot([self._gold_held(pid)])
        self.assertAlmostEqual(self._open_risk(), 2000.0, 2)

    def _given_up(self, cfg, pid, env="live"):
        """A close given up on, as pending_closes._give_up leaves it: a real
        eToro gold row, ERROR, no close time, filled in the `env` world."""
        from bot_program.models import AssetBotTrade
        t = AssetBotTrade.objects.create(
            config=cfg, asset_class="commodity", symbol="XAUUSD", side="BUY",
            qty=Decimal("0.5"), entry_price=Decimal("4000"),
            stop_loss=Decimal("3880"), take_profit=Decimal("4240"),
            status="ERROR", paper=False,
            metadata={"broker": "etoro", "broker_env": env,
                      "broker_position_id": str(pid)})
        AssetBotTrade.objects.filter(pk=t.pk).update(
            opened_at=timezone.now() - timedelta(hours=3))
        return t

    def test_the_take_trade_lane_counts_its_own_abandoned_rows(self):
        """The TAKE TRADE pool's committed sum: plus its own abandoned rows,
        never another lane's."""
        from bot_program.manual_trade import (manual_config_for,
                                              preview_asset_trade)
        from instruments.models import Instrument
        lane = manual_config_for(self.user, "commodity")
        lane.mode, lane.capital, lane.base_currency = (
            "live", Decimal("100000"), "USD")
        lane.save(update_fields=["mode", "capital", "base_currency"])
        self._given_up(lane, 880000101)
        self._given_up(_config(self.user, "another lane", ["XAUUSD"]),
                       880000102)
        self._snapshot([self._gold_held(880000101),
                        self._gold_held(880000102)])
        out = preview_asset_trade(
            self.user, Instrument.objects.get(symbol="WTIUSD"), "BUY")
        self.assertNotIn("error", out)
        self.assertEqual(out.get("committed"), 2000.0)
        self.assertEqual(self._gate(), 4000.0)

    def test_the_pledge_gate_reads_etoros_cells_and_charges_no_old_row(self):
        """G1. The order gate's used is eToro's own cell, and nothing
        pledged since the read: an abandoned row is never charged twice."""
        from bot_program.asset_engine.base import AssetBot, make_bot
        from bot_program.engine.broker_router import client_for_symbol
        _cfg, row = self._gold_row()
        pid = row.metadata["broker_position_id"]
        self._abandon(row)
        self._snapshot([self._gold_held(pid)])
        acct = self.acct
        acct.last_used_margin = Decimal("2000")
        acct.last_available_cash = Decimal("98000")
        acct.last_margin_at = timezone.now()
        acct.save(update_fields=["last_used_margin", "last_available_cash",
                                 "last_margin_at"])
        cfg2 = _config(self.user, "oil bot", ["WTIUSD"])
        bot = make_bot(cfg2)
        client = client_for_symbol(self.user, "WTIUSD", cfg2)
        g = bot._cash_gate(client, "WTIUSD", qty=10.0, price=60.0, leverage=1)
        since = AssetBot._pledged_since(SimpleNamespace(user=self.user),
                                        acct.last_margin_at, "etoro")
        self.assertEqual(g["used"], 2000.0)
        self.assertEqual(g["pledged"], 0.0)
        self.assertEqual(since, 0.0)

    def test_nothing_is_sent_for_an_abandoned_row(self):
        """G3. 24 drain passes and a reconcile after ERROR send nothing,
        whatever the predicate counts."""
        from bot_program.reconcile_asset import reconcile_user
        _cfg, row = self._gold_row()
        pid = row.metadata["broker_position_id"]
        self._abandon(row)
        self._snapshot([self._gold_held(pid)])
        n0 = sum(1 for c in self.wire.calls if c[0] in ("POST", "PATCH",
                                                         "DELETE"))
        t0 = timezone.now()
        for i in range(24):
            self._drain_at(t0 + timedelta(hours=2, seconds=BEAT_S * i))
        reconcile_user(self.user)
        row.refresh_from_db()
        self.assertEqual(sum(1 for c in self.wire.calls
                             if c[0] in ("POST", "PATCH", "DELETE")), n0)
        self.assertEqual(row.status, "ERROR")


class TheSplitReadsTheSamePredicateTests(_Base):

    def _split(self):
        from bot_program.etoro_used import account_used
        return account_used(User.objects.get(pk=self.user.pk))

    def _cells(self, used):
        """eToro's cells, read now: after every row here was booked."""
        self.acct.last_used_margin = Decimal(str(used))
        self.acct.last_margin_at = timezone.now()
        self.acct.save(update_fields=["last_used_margin", "last_margin_at"])

    def test_listed_it_is_stopped_closing_and_counted_once(self):
        """Opened by Sauron is the open rows' own walk; the abandoned row is
        in "Sauron stopped closing" only, never in both."""
        _cfg, row = self._gold_row()
        pid = row.metadata["broker_position_id"]
        self._abandon(row)
        oil = _book_bot(self.user, _config(self.user, "oil bot", ["WTIUSD"]),
                        "oil")
        self.assertIsNotNone(oil)
        self._snapshot([self._gold_held(pid)])
        self._cells(3800)
        u = self._split()
        self.assertEqual((u["sauron"], u["sauron_n"]), (1800.0, 1))
        self.assertEqual((u["stopped"], u["stopped_n"]), (2000.0, 1))
        self.assertEqual(u["outside"], 0.0)
        self.assertEqual(self._used(), 3800.0)

    def test_a_stale_snapshot_is_said_may_still_be_open_and_counted(self):
        """The gates count it (a stale list cannot say), so the split says
        "may still be open" and subtracts it, instead of "no longer listed"
        off a list an hour old."""
        from bot_program.capital_truth import TRACKING_FRESH_SECONDS
        _cfg, row = self._gold_row()
        self._abandon(row)
        self._snapshot([], age_s=TRACKING_FRESH_SECONDS + 60)
        self._cells(2000)
        u = self._split()
        self.assertEqual((u["stopped"], u["stopped_n"]), (2000.0, 1))
        self.assertEqual(u["stopped_gone_n"], 0)
        self.assertIn("Sauron stopped closing, may still be open at eToro "
                      "2,000.00", u["split_t"])
        self.assertEqual(self._gate(), 2000.0)

    def test_gone_from_a_fresh_snapshot_it_leaves_both(self):
        _cfg, row = self._gold_row()
        self._abandon(row)
        self._snapshot([])
        self._cells(0)
        u = self._split()
        self.assertEqual((u["stopped"], u["stopped_n"]), (0.0, 0))
        self.assertEqual(u["stopped_gone_n"], 1)
        self.assertEqual(self._gate(), 0.0)


# ── review (2026-11-01): a paper ticket never closes a real row ──────────

def _paper_open(testcase):
    """The paper venue open: the suite may run on a weekend, and a paper
    ticket fills nothing while its market is shut."""
    for p in (mock.patch("bot_program.engine.paper_trader.paper_market_shut",
                         return_value=""),
              mock.patch("bot_program.engine.paper_trader."
                         "paper_awaits_first_price", return_value="")):
        p.start()
        testcase.addCleanup(p.stop)


class ThePaperTicketNeverClosesARealRowTests(_Base):
    """A TAKE TRADE lane stood down to paper still holds the real row its
    live ticket opened. Its paper ticket offered that row as a funding
    close, pre-ticked, and a ticket naming it sent the close through
    today's routing: the simulator was refused, the row went CLOSE_PENDING
    and the ticket said "Closing XAUUSD failed". The drain, which now asks
    the row's own carrier, then sent the real close at the next beat, with
    no PIN. A real row is closed only from the positions page, with the
    PIN (manual_close.execute_close)."""

    def setUp(self):
        super().setUp()
        _paper_open(self)

    def _stood_down_lane(self, capital=2050):
        """The commodity TAKE TRADE lane armed LIVE with the PIN, a LIVE gold
        ticket through the real adapter, then stood down to paper with a
        retyped pool (arm_manual_lane: standing down is never gated)."""
        from bot_program.manual_trade import (arm_manual_lane,
                                              execute_asset_trade,
                                              manual_config_for)
        from bot_program.models import AssetBotTrade
        from instruments.models import Instrument
        lane = manual_config_for(self.user, "commodity")
        lane.base_currency = "USD"
        lane.save(update_fields=["base_currency"])
        armed = arm_manual_lane(self.user, asset_class="commodity",
                                mode="live", capital=20000, pin_ok=True)
        self.assertNotIn("error", armed, armed)
        out = execute_asset_trade(self.user,
                                  Instrument.objects.get(symbol="XAUUSD"),
                                  "BUY", None, qty=0.5, pin_ok=True,
                                  dup_seen=[])
        self.assertTrue(out.get("ok"), out)
        real = AssetBotTrade.objects.get(config=lane, paper=False,
                                         status="OPEN")
        down = arm_manual_lane(self.user, asset_class="commodity",
                               mode="paper", capital=capital)
        self.assertNotIn("error", down, down)
        AssetBotTrade.objects.filter(pk=real.pk).update(
            opened_at=timezone.now() - timedelta(hours=3))
        real.refresh_from_db()
        lane.refresh_from_db()
        self.assertEqual(lane.mode, "paper")
        self.assertEqual(self._held(), [2000.0])
        return lane, real

    def _oil(self):
        from instruments.models import Instrument
        return Instrument.objects.get(symbol="WTIUSD")

    def _named(self, real):
        """A paper oil ticket naming the real row as its funding close, then
        three drain beats: (the ticket's answer, close POSTs sent)."""
        from bot_program.manual_trade import execute_asset_trade
        from bot_program.models import AssetBotTrade
        n_rows = AssetBotTrade.objects.count()
        posts = len(self._close_posts())
        out = execute_asset_trade(self.user, self._oil(), "BUY", [real.pk],
                                  pin_ok=False, dup_seen=[])
        real.refresh_from_db()
        self.assertEqual(real.status, "OPEN", out)
        self.assertEqual(AssetBotTrade.objects.count(), n_rows,
                         "a paper ticket booked something")
        self._passes(real, 3, stop_early=False)
        return out, len(self._close_posts()) - posts

    def test_the_paper_ticket_never_offers_the_real_row(self):
        """The preview's funding list and its proposal hold only the lane's
        paper rows. Short with nothing a paper ticket may close, it says
        where the real row is closed."""
        from bot_program.manual_trade import preview_asset_trade
        _lane, real = self._stood_down_lane()
        p = preview_asset_trade(self.user, self._oil(), "BUY")
        offered = ({c["trade_id"] for c in p.get("closable") or []}
                   | {c["trade_id"] for c in p.get("close_proposal") or []})
        self.assertNotIn(real.pk, offered, p)
        self.assertIn("error", p, p)
        for words in ("REAL", "XAUUSD", "positions page", "with the PIN"):
            self.assertIn(words, p["error"])

    def test_a_paper_ticket_naming_the_real_row_sends_nothing(self):
        """Refused before anything is liquidated; the row stays OPEN, and
        no drain beat after it sends anything to eToro."""
        _lane, real = self._stood_down_lane()
        out, posts = self._named(real)
        self.assertIn("REAL", out.get("error", ""), out)
        self.assertIn("with the PIN", out["error"])
        self.assertFalse(out.get("closed"))
        self.assertEqual(posts, 0)
        real.refresh_from_db()
        self.assertEqual(real.status, "OPEN")
        self.assertEqual(self._held(), [2000.0])

    def test_named_by_hand_with_room_to_spare_it_is_refused_too(self):
        """No shortfall, so the dialog shows no list: a request naming the
        real row by hand is refused all the same."""
        _lane, real = self._stood_down_lane(capital=100000)
        out, posts = self._named(real)
        self.assertIn("REAL", out.get("error", ""), out)
        self.assertEqual(posts, 0)
        self.assertEqual(self._held(), [2000.0])

    def test_a_paper_row_still_funds_the_paper_ticket(self):
        """The control: the lane's paper rows are offered and closed as
        before, and the real row is never among them."""
        from bot_program.manual_trade import (_trade_capital_use,
                                              execute_asset_trade,
                                              preview_asset_trade)
        from bot_program.models import AssetBotTrade
        from instruments.models import Instrument
        lane, real = self._stood_down_lane(capital=100000)
        first = execute_asset_trade(self.user,
                                    Instrument.objects.get(symbol="XAUUSD"),
                                    "BUY", None, pin_ok=False, dup_seen=[])
        self.assertTrue(first.get("ok"), first)
        paper = AssetBotTrade.objects.get(pk=first["trade_id"])
        self.assertTrue(paper.paper)
        lane.capital = Decimal(str(round(
            _trade_capital_use(real) + _trade_capital_use(paper) + 1, 2)))
        lane.save(update_fields=["capital"])
        p = preview_asset_trade(self.user, self._oil(), "BUY")
        self.assertNotIn("error", p, p)
        self.assertFalse(p["sufficient"])
        self.assertEqual([c["trade_id"] for c in p["closable"]], [paper.pk])
        self.assertEqual([c["trade_id"] for c in p["close_proposal"]],
                         [paper.pk])
        posts = len(self._close_posts())
        out = execute_asset_trade(self.user, self._oil(), "BUY", [paper.pk],
                                  pin_ok=False, dup_seen=[])
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out.get("closed"), ["XAUUSD"])
        paper.refresh_from_db()
        real.refresh_from_db()
        self.assertEqual(paper.status, "CLOSED")
        self.assertEqual(real.status, "OPEN")
        self.assertEqual(len(self._close_posts()), posts)


# ── review (2026-11-01): the sweep names a close given up on truly ───────

class TheSweepNamesAGivenUpCloseTests(_Base):
    """reconcile_unknown_positions claimed with OPEN and CLOSE_PENDING rows
    only, so the position of a close Sauron gave up on was said, every
    three hours, to be "invisible to every exposure and daily-loss gate"
    while those gates count it (portfolio.services.abandoned_still_held).
    The given-up row claims its own position now, as the split and the
    positions panel claim it, and the reminder says what is true."""

    def _sweep(self, when=None):
        from bot_program.reconcile_asset import reconcile_unknown_positions
        user = User.objects.get(pk=self.user.pk)
        if when is None:
            return reconcile_unknown_positions(user)
        with mock.patch("django.utils.timezone.now", return_value=when):
            return reconcile_unknown_positions(user)

    def _bells(self, words):
        from alerts.models import Notification
        return list(Notification.objects.filter(
            user=self.user, title__contains=words).order_by("pk"))

    def _given_up_held(self):
        _cfg, row = self._gold_row()
        pid = row.metadata["broker_position_id"]
        self._abandon(row)
        self.assertEqual(self._held(), [2000.0])
        self._snapshot([self._gold_held(pid)])
        self.assertEqual(self._gate(), 2000.0)
        return row

    def test_a_given_up_close_is_never_said_invisible_to_the_gates(self):
        self._given_up_held()
        out = self._sweep()
        self.assertEqual(out["unclaimed"], 0)
        self.assertEqual(out["given_up"], 1)
        self.assertEqual(self._bells("no row claims"), [])
        [bell] = self._bells("gave up on")
        self.assertIn("XAUUSD", bell.body)
        for words in ("no longer manages", "exposure and open-risk gates "
                      "count it", "Close it at the broker"):
            self.assertIn(words, bell.body)
        self.assertNotIn("invisible", bell.body)

    def test_the_reminder_rings_again_after_the_window_only(self):
        from bot_program.notifications import UNCLAIMED_REMIND_S
        self._given_up_held()
        self._sweep()
        self._sweep()
        self.assertEqual(len(self._bells("gave up on")), 1)
        self._sweep(timezone.now()
                    + timedelta(seconds=UNCLAIMED_REMIND_S + 60))
        self.assertEqual(len(self._bells("gave up on")), 2)

    def test_a_position_opened_by_hand_beside_it_is_still_unclaimed(self):
        """The given-up row claims its own position, by its id: a second
        gold position opened in the eToro app is said unclaimed, in the
        unclaimed words."""
        self._given_up_held()
        self.wire.portfolio.append(_portfolio_row(880009999, 18, 0.25,
                                                  4010.0, 1))
        out = self._sweep()
        self.assertEqual(out["unclaimed"], 1)
        self.assertEqual(out["symbols"], ["XAUUSD"])
        self.assertEqual(out["given_up"], 1)
        self.assertEqual(len(self._bells("no row claims")), 1)
        self.assertEqual(len(self._bells("gave up on")), 1)

    def test_the_reminder_reaches_the_phone_in_the_house_style(self):
        """The unclaimed alert's channel and mark: one Telegram message,
        its first line the mark and the title, its lines the true words."""
        import os

        from alerts.models import UserNotificationPrefs
        from bot_program.notifications import (NOTIFY_MARKS,
                                               notify_given_up_held)
        from portfolio.trader_profile import TraderProfile
        prefs, _ = UserNotificationPrefs.objects.get_or_create(user=self.user)
        prefs.telegram_chat_id = "123"
        prefs.save()
        profile, _ = TraderProfile.objects.get_or_create(user=self.user)
        profile.notify_channel = "telegram"
        profile.save()
        sent = mock.MagicMock(ok=True, status_code=200, text='{"ok":true}')
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "1:<test>",
                                          "TELEGRAM_CHAT_ID": "", "DOMAIN": ""}), \
                mock.patch("requests.post", return_value=sent) as post:
            self.assertTrue(notify_given_up_held(self.user,
                                                 symbols=["XAUUSD"],
                                                 venue="eToro Main"))
        [text] = [c.kwargs["json"]["text"] for c in post.call_args_list]
        first, *rest = text.split("\n")
        self.assertTrue(first.startswith(
            f"<b>{NOTIFY_MARKS['unclaimed_position']} "), first)
        self.assertIn("1 close Sauron gave up on, still held at eToro Main",
                      first)
        body = "\n".join(rest)
        for words in ("Counted by the exposure and open-risk gates while "
                      "the broker holds it", "Close it at the broker"):
            self.assertIn(words, body)
        self.assertNotIn("invisible", text)

    def test_a_given_up_row_without_an_id_is_matched_as_the_gates_match_it(
            self):
        """A row that records no position id claims a position on its
        symbol and side, as abandoned_still_held counts it: the gates count
        it, so the sweep never says it is invisible to them."""
        row = self._given_up_held()
        meta = dict(row.metadata)
        meta.pop("broker_position_id", None)
        type(row).objects.filter(pk=row.pk).update(metadata=meta)
        self.assertEqual(self._gate(), 2000.0)
        out = self._sweep()
        self.assertEqual((out["unclaimed"], out["given_up"]), (0, 1))
        self.assertEqual(self._bells("no row claims"), [])


# ── review (2026-11-01): the Horde names a close given up on ─────────────

class TheHordeNamesAGivenUpCloseTests(_Base):
    """The Horde's head said the open-risk gate's rows beyond the real
    seats were "open rows of the shared Main book". A close Sauron gave up
    on is counted by that gate since this change and is never a seat, so
    it was called a Main-book row the book may not hold. It is said apart,
    in the exposure refusal's words."""

    def _live_head(self):
        from dashboard import horde
        from portfolio.risk_gate import limits_book
        book = limits_book()
        book.max_open_risk_pct = Decimal("50")
        book.save(update_fields=["max_open_risk_pct"])
        board = horde.board(User.objects.get(pk=self.user.pk))
        return board["head"]["sides"]["live"]

    def _abandoned_held(self):
        _cfg, row = self._gold_row()
        pid = row.metadata["broker_position_id"]
        self._abandon(row)
        self._snapshot([self._gold_held(pid)])
        return row

    def test_the_gate_carries_its_given_up_rows_apart(self):
        from portfolio.risk_gate import limits_book, open_risk_state
        self._abandoned_held()
        book = limits_book()
        book.max_open_risk_pct = Decimal("50")
        book.save(update_fields=["max_open_risk_pct"])
        st = open_risk_state(self.user, portfolio=book, venue="live")
        self.assertEqual((st["rows"], st["abandoned"]), (1, 1))
        paper = open_risk_state(self.user, portfolio=book, venue="paper")
        self.assertEqual(paper["abandoned"], 0)

    def test_a_given_up_close_is_not_called_a_main_book_row(self):
        self._abandoned_held()
        live = self._live_head()
        self.assertEqual(live["open_risk"]["rows"], 1)
        self.assertEqual(live["gate_extra_rows"], 0)
        self.assertEqual(live["extra_t"], "")
        self.assertEqual(live["gate_abandoned_rows"], 1)
        self.assertIn("1 close(s) Sauron gave up on that the broker may "
                      "still hold", live["abandoned_t"])
        self.assertNotIn("Main book", live["abandoned_t"])

    def test_beside_a_main_book_row_each_is_named_for_what_it_is(self):
        from instruments.models import Instrument
        from portfolio.models import Position
        from portfolio.risk_gate import limits_book
        self._abandoned_held()
        Position.objects.create(
            portfolio=limits_book(),
            instrument=Instrument.objects.get(symbol="WTIUSD"),
            direction="long", quantity=Decimal("10"),
            entry_price=Decimal("60"), current_price=Decimal("60"),
            stop_loss=Decimal("58"), opened_at=timezone.now())
        live = self._live_head()
        self.assertEqual(live["open_risk"]["rows"], 2)
        self.assertEqual(live["gate_extra_rows"], 1)
        self.assertIn("The gate counts 1 more row(s): open rows of the shared "
                      "Main book", live["extra_t"])
        self.assertEqual(live["gate_abandoned_rows"], 1)


# ── review (2026-11-01): the level dialog moves a real row's legs ────────

class TheLevelDialogMovesARealRowsLegsTests(_Base):
    """On a lane stood down to paper, or with its class box unticked, the
    manage tick moves a real eToro row's stop at eToro (client_for_row),
    and the operator's own stop and target dialog was refused with "this
    broker cannot modify a resting order yet — close and re-open": a false
    reason, and advice that costs a real round trip. The dialog asks the
    row's own carrier too, behind the PIN the view asks for a real row."""

    def _protected_gold(self):
        cfg, row = self._gold_row()
        meta = dict(row.metadata)
        meta["protected"] = True
        type(row).objects.filter(pk=row.pk).update(metadata=meta)
        row.refresh_from_db()
        return cfg, row

    def _writes(self):
        return [c for c in self.wire.calls if c[0] in ("PATCH", "PUT")]

    def _move(self, row, **kw):
        from bot_program.adjust_levels import adjust_levels
        from bot_program.models import AssetBotTrade
        return adjust_levels(self.user, AssetBotTrade.objects.get(pk=row.pk),
                             **kw)

    def test_on_a_lane_stood_down_to_paper_the_stop_moves_at_etoro(self):
        cfg, row = self._protected_gold()
        self._stand_down(cfg)
        n_orders, n = len(self._order_posts()), len(self._writes())
        out = self._move(row, stop=Decimal("3950"))
        row.refresh_from_db()
        self.assertTrue(out.get("ok"), out)
        sent = self._writes()[n:]
        self.assertEqual(len(sent), 1, sent)
        self.assertIn("stopLossRate", sent[0][2])
        self.assertEqual(row.stop_loss, Decimal("3950"))
        self.assertEqual(len(self._order_posts()), n_orders)

    def test_on_an_unticked_class_box_the_stop_moves_at_etoro(self):
        _cfg, row = self._protected_gold()
        self._untick_commodity()
        n = len(self._writes())
        out = self._move(row, stop=Decimal("3950"))
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(len(self._writes()) - n, 1)

    def test_the_view_as_the_dialog_posts_it_behind_the_pin(self):
        """The dialog posts the stop, the stored target and the PIN; the
        view asks the PIN for a real row whatever its lane's mode."""
        from django.test import Client
        from django.urls import reverse
        cfg, row = self._protected_gold()
        self._stand_down(cfg)
        c = Client()
        c.force_login(self.user)
        body = {"stop": "3950", "target": str(row.take_profit),
                "clear_target": False, "pin": "<test>"}
        url = reverse("position_levels", args=[row.pk])
        with mock.patch("dashboard.views_close._pin_ok",
                        return_value=False) as pin:
            r = c.post(url, data=json.dumps(body),
                       content_type="application/json")
        self.assertEqual(r.status_code, 403)
        pin.assert_called_once()
        n = len(self._writes())
        with mock.patch("dashboard.views_close._pin_ok", return_value=True):
            r = c.post(url, data=json.dumps(body),
                       content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertGreater(len(self._writes()), n)
        row.refresh_from_db()
        self.assertEqual(row.stop_loss, Decimal("3950"))

    def test_keys_gone_the_dialog_says_why_and_sends_nothing(self):
        """The row's own venue cannot be asked: said so, never "this broker
        cannot modify a resting order"."""
        from bot_program.models import EtoroAccount
        cfg, row = self._protected_gold()
        self._stand_down(cfg)
        EtoroAccount.objects.filter(pk=self.acct.pk).update(api_key_enc="",
                                                             user_key_enc="")
        n = len(self._writes())
        out = self._move(row, stop=Decimal("3950"))
        row.refresh_from_db()
        self.assertFalse(out.get("ok"))
        self.assertIn("cannot be asked from here", out["error"])
        self.assertNotIn("cannot modify a resting order", out["error"])
        self.assertEqual(len(self._writes()), n)
        self.assertEqual(row.stop_loss, Decimal("3880"))

    def test_a_live_row_of_another_venue_on_a_paper_lane_is_told_why(self):
        """client_for_row reroutes eToro rows only: a live row of another
        venue on a lane stood down to paper is still handed the simulator,
        and the dialog says its own venue cannot be asked and why, never
        that the broker cannot modify a resting order."""
        from bot_program.models import AssetBotTrade
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        self._stand_down(cfg)
        row = AssetBotTrade.objects.create(
            config=cfg, asset_class="commodity", symbol="XAUUSD",
            side="BUY", qty=Decimal("0.5"), entry_price=Decimal("4000"),
            stop_loss=Decimal("3880"), take_profit=Decimal("4240"),
            status="OPEN", paper=False,
            metadata={"broker": "saxo", "broker_env": "live",
                      "protected": True, "protective_trade_id": "<test>"})
        n = len(self._writes())
        out = self._move(row, stop=Decimal("3950"))
        row.refresh_from_db()
        self.assertFalse(out.get("ok"))
        self.assertIn("cannot be asked from here", out["error"])
        self.assertIn("a lane on paper for a venue other than eToro",
                      out["error"])
        self.assertNotIn("cannot modify a resting order", out["error"])
        self.assertEqual(len(self._writes()), n)
        self.assertEqual(row.stop_loss, Decimal("3880"))


# ── the source: who may call the two new names ───────────────────────────

#: Top-level folders that are not the project's own code: a build, a
#: virtualenv, the front end. A folder whose name starts with a dot (a
#: worktree Claude Code keeps under .claude/, .git) is skipped too.
_NOT_THE_PROJECT = {"tests", "staticfiles", "static", "templates", "venv",
                    "node_modules", "frontend", "test_backups"}


def _project_sources():
    """(relative path, source) of every .py file of the project's own
    packages, migrations left out: never a virtualenv, a build, or another
    worktree that may sit inside the checkout."""
    base = Path(settings.BASE_DIR)
    roots = [p for p in sorted(base.iterdir()) if p.is_dir()
             and not p.name.startswith(".") and p.name not in _NOT_THE_PROJECT]
    paths = [p for root in roots for p in sorted(root.rglob("*.py"))]
    paths += sorted(base.glob("*.py"))
    for path in paths:
        rel = path.relative_to(base).as_posix()
        if "/migrations/" in rel:
            continue
        try:
            yield rel, path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue


class _Calls(ast.NodeVisitor):
    """{(path, the innermost function around the call)} for every call of
    `name`, spelled bare or as an attribute."""

    def __init__(self, rel, name):
        self.rel, self.name, self.stack, self.found = rel, name, [], set()

    def _function(self, node):
        self.stack.append(node.name)
        self.generic_visit(node)
        self.stack.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = _function

    def visit_Call(self, node):
        called = (getattr(node.func, "id", None)
                  or getattr(node.func, "attr", None))
        if called == self.name:
            self.found.add((self.rel, self.stack[-1] if self.stack
                            else "<module>"))
        self.generic_visit(node)


def _callers_of(name) -> set:
    found = set()
    for rel, src in _project_sources():
        if name not in src:
            continue
        visitor = _Calls(rel, name)
        visitor.visit(ast.parse(src))
        found |= visitor.found
    return found


class NoEntryPathCallsClientForRowTests(SimpleTestCase):

    #: Where client_for_row may be called: closes, the reads that book a
    #: close, the manage tick's closes, withdrawals and stop moves, and the
    #: operator's stop and target dialog (review, 2026-11-01: it moves a
    #: resting leg of a position that exists, behind the PIN).
    ALLOWED = {
        ("bot_program/pending_closes.py", "retry_trade_close"),
        ("bot_program/engine/kill_switch.py", "_close_asset_trade"),
        ("bot_program/manual_close.py", "preview_close"),
        ("bot_program/manual_close.py", "execute_close"),
        ("bot_program/reconcile_asset.py", "reconcile_user"),
        ("bot_program/reconcile_asset.py", "_close_as_orphan"),
        ("bot_program/asset_engine/base.py", "manage_positions"),
        ("bot_program/asset_engine/base.py",
         "_withdraw_working_while_braked"),
        ("bot_program/adjust_levels.py", "_move_broker_leg"),
    }
    #: The entry paths: none of them may ask for it.
    ENTRY = {
        "bot_program/asset_engine/base.py": (
            "execute_entry", "propose_entry", "scan_symbol", "tick",
            "_settle_in_doubt", "_cash_gate", "_order_in_doubt"),
        "bot_program/manual_trade.py": (
            "_execute", "execute_asset_trade", "preview_asset_trade",
            "_preview"),
    }

    def test_only_the_close_paths_call_it(self):
        self.assertEqual(_callers_of("client_for_row"), self.ALLOWED)

    def test_no_entry_function_names_it(self):
        base = Path(settings.BASE_DIR)
        for rel, names in self.ENTRY.items():
            tree = ast.parse((base / rel).read_text(encoding="utf-8"))
            seen = {fn.name for fn in ast.walk(tree)
                    if isinstance(fn, ast.FunctionDef) and fn.name in names}
            # every entry path named here exists, or the check checks nothing
            self.assertEqual(seen, set(names), rel)
            for fn in ast.walk(tree):
                if isinstance(fn, ast.FunctionDef) and fn.name in names:
                    self.assertNotIn("client_for_row", ast.unparse(fn),
                                     f"{rel}:{fn.name}")


class ThePredicatesReadersTests(SimpleTestCase):
    """abandoned_still_held is read by the pages' used, the exposure and
    open-risk gates, the TAKE TRADE pool and the split, and never by
    AssetBot._pledged_since (eToro's own cells count the position), the
    drain, the reconcile or the manage tick: nothing is sent for such a
    row."""

    READERS = {
        ("portfolio/services.py", "capital_summary"),
        ("portfolio/risk_gate.py", "open_capital_at_work"),
        ("portfolio/risk_gate.py", "open_risk_state"),
        ("bot_program/manual_trade.py", "_preview"),
        ("bot_program/etoro_used.py", "_still_held"),
    }

    def test_only_the_money_readers_read_it(self):
        self.assertEqual(_callers_of("abandoned_still_held"), self.READERS)

    def test_the_split_imports_it_from_the_gates_module(self):
        """The split reads the gates' predicate; no gate module ever reads
        bot_program.etoro_used (tests.test_used_is_etoros)."""
        base = Path(settings.BASE_DIR)
        src = (base / "bot_program/etoro_used.py").read_text(encoding="utf-8")
        self.assertIn("from portfolio.services import abandoned_still_held",
                      src)
        self.assertNotIn("def abandoned_still_held", src)
