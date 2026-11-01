"""AN ORDER WHOSE ANSWER DID NOT COME BACK IS NEVER FORGOTTEN, ON EITHER
LANE (2026-11-01).

The operator reported that Sauron counts less used capital than eToro
shows. The investigation found two booking paths that leave nothing
behind when eToro may have taken an order, and a settle that forgets the
order while eToro still holds it:

  * THE TICKET. On TAKE TRADE (manual_trade._execute) a POST that raised
    after the send booked no row, wrote no note and told nobody: the ticket
    said "MAY have reached the broker", and a second ticket on the same
    symbol sent a second order. The ticket now does what the bot lane does
    (AssetBot._order_in_doubt): the note on the lane's config, the staff
    alert, and eToro's cells read again a few seconds from now. The live
    ticket refuses the symbol while the note stands, in propose_entry's
    words: in its preview and under its lock, beside the double-click
    guard. A paper ticket sends nothing to a broker and is not held.
  * THE VENUE. A 5xx answer to the order POST was read as a refusal on both
    lanes ("eToro refused (502)"): an order eToro may have taken left no
    trace, and the next tick sent it again. EtoroTrader.market_order now
    raises EtoroOrderInDoubt for it, with the request id, the symbol,
    "HTTP <code>" and the client order id; the venue's health is noted as
    before. A 429 and every 4xx stay refusals.
  * THE SETTLE. AssetBot._settle_in_doubt read /portfolio only, and an
    order eToro HOLDS (WaitingForMarket) is in no /portfolio row: two flat
    reads cleared the note while eToro held it. A flat read now counts only
    when eToro's frozen cash (C3's last_frozen_cash) was read after the
    note, in the account's world, and is no more than Sauron's own WORKING
    eToro rows explain (base.frozen_explained). Otherwise the note stands,
    and says so when the cash is unexplained. A cell never stored, or
    another venue, keeps the old rule.
  * THE SPLIT (bot_program.etoro_used, display only). "Held at eToro, no
    Sauron row" is carved out of "outside Sauron" with its age: eToro's
    frozen cash less what Sauron's WORKING rows explain, which "opened by
    Sauron" already counts and which is never counted twice. An outside
    position, or the held part, on a symbol with a fresh in-doubt note on
    any of the user's configs says "may be Sauron's order of <time> that
    did not come back"; no number moves between the split's parts.

The review of the first draft (2026-11-01) closed five more gaps, each
pinned below by a test written first:

  * ONE FROZEN READ BACKED TWO FLAT READS. The frozen read behind a flat
    read now obeys the position read's rule: past the venue's lag since
    the note, and newer than the previous flat read. The re-read the
    in-doubt call itself queues, 3 s after the note, backs none.
  * THE NOTE HELD ONLY ITS OWN LANE. Both lanes now refuse the symbol
    while any config of the user holds a fresh note on it (the bot lane in
    its proposal and again before the order leaves); the settle stays the
    owner's.
  * SAURON'S OWN POSITION KEPT THE NOTE. eToro opens each order as its own
    position, so one whose id a Sauron row records is not the order; the
    refusal now says why the note stands and when it lifts at the latest.
  * THE LABEL NAMED WHAT WAS READ BEFORE THE ORDER. It now names only a
    read that could carry the order, and never a position eToro opened
    before it.
  * THE "HELD" WORDS OUTLIVED THEIR READ. They are dropped by the first
    read that does not show them, and lead with their read's time.

Over a fake eToro wire: the REAL router, adapter and both lanes; only the
HTTP session is fake, and no socket may open. Ported from the
investigation's red tests (R1, R2, R3, R3b, R8) and the review's probes.
Illustrative round numbers only; no account figures.

Run with:  python manage.py test tests.test_order_in_doubt_lanes
"""
import copy
import json
import socket
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import StringIO
from unittest import mock

import requests
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

LOCMEM = {"default": {"BACKEND":
                      "django.core.cache.backends.locmem.LocMemCache"}}
BASE = "bot_program.asset_engine.base.AssetBot"
REREAD = "bot_program.etoro_cells.refresh_for_client"


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
    aggregate-portfolio, eligibility and the order POST. Every call is
    recorded; a POST follows the next plan queued for its spelling."""

    def __init__(self):
        self.headers = {}
        self.calls = []
        self.by_wire, self.by_iid = {}, {}
        self.lookups = {}
        self.plans = {}
        self.portfolio = []
        self.totals = None
        self.orders = []
        self._oid, self._pid = 990000000, 880000000

    def add(self, symbol, wire, iid, price, row):
        inst = {"symbol": symbol, "wire": wire, "iid": iid,
                "price": float(price), "row": row}
        self.by_wire[wire] = inst
        self.by_iid[iid] = inst

    def plan(self, wire, **plan):
        self.plans.setdefault(wire, []).append(plan)

    def get(self, url, params=None, **kw):
        self.calls.append(("GET", url, dict(params or {})))
        return self._get(url, params or {})

    def post(self, url, json=None, **kw):
        self.calls.append(("POST", url, copy.deepcopy(json)))
        return self._post(url, json or {})

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
        return _Resp(404, {"message": f"test wire: no route {url}"})

    def _order(self, body):
        wire = str(body.get("symbol") or "")
        inst = self.by_wire.get(wire)
        seq = self.plans.get(wire) or []
        plan = seq.pop(0) if seq else {}
        if "raise" in plan:
            raise plan["raise"]
        if "resp" in plan:
            return plan["resp"]
        self._oid += 1
        self._pid += 1
        oid, pid = self._oid, self._pid
        lk = _lookup(oid, pid, inst, body, **plan.get("fill", {}))
        self.lookups[str(oid)] = [lk]
        self.orders.append({"oid": oid, "pid": pid, "body": copy.deepcopy(body),
                            "lookup": lk})
        ex = lk.get("positionExecutions") or []
        if ex and inst is not None:
            od = ex[0]["openingData"]
            self.portfolio.append(_portfolio_row(
                pid, inst["iid"], od["units"], od["avgPrice"],
                int(lk["asset"]["leverage"]),
                amount=ex[0]["marginAccountCurrency"], order_id=oid))
        return _Resp(200, {"token": "<test>", "orderId": oid,
                           "referenceId": "<test>"})


def _lookup(order_id, position_id, inst, body, *, status=(3, "Filled"),
            fees=0.0):
    """orders:lookup in the measured shape (tests/test_etoro_client.py),
    composed from the POST: filled at the instrument's price, margin =
    units x price / the multiplier sent; held (11, WaitingForMarket) with
    no execution."""
    units = float(body.get("units") or 0)
    lev = int(body.get("leverage") or 1)
    avg = inst["price"]
    margin = round(units * avg / lev, 2)
    sid, sname = status
    filled = sid in (3, 5)
    out = {
        "orderId": order_id, "action": "open",
        "transaction": "buy" if body.get("transaction") == "buy" else "sell",
        "type": "mkt", "status": {"id": sid, "name": sname, "errorCode": 0},
        "asset": {"symbol": inst["wire"], "instrumentId": inst["iid"],
                  "currency": "USD", "settlementType": "CFD",
                  "leverage": lev,
                  "side": ("long" if body.get("transaction") == "buy"
                           else "short")},
        "requestedAmount": margin, "requestedUnits": units,
        "frozenAmount": round(margin + fees, 2),
        "openStopLossRate": body.get("stopLossRate") if filled else 0.0,
        "openTakeProfitRate": body.get("takeProfitRate") if filled else 0.0,
        "totalCosts": fees, "positionExecutions": []}
    if filled:
        out["positionExecutions"] = [{
            "positionId": position_id, "state": "open",
            "marginAccountCurrency": margin, "remainingUnits": units,
            "stopLossRate": body.get("stopLossRate"),
            "takeProfitRate": body.get("takeProfitRate"),
            "openingData": {"units": units, "avgPrice": avg, "fees": fees}}]
    return out


def _portfolio_row(position_id, iid, units, open_rate, leverage, *,
                   amount=None, order_id=0, opened=None):
    """One /portfolio row on the measured GLDM row's keys, opened at
    `opened` (now when None: the wire's own fill)."""
    from tests.test_etoro_client import PORTFOLIO_ROW
    amt = (round(units * open_rate / max(int(leverage), 1), 2)
           if amount is None else float(amount))
    opened = (opened or timezone.now()).astimezone(dt_timezone.utc)
    return dict(PORTFOLIO_ROW, positionID=int(position_id),
                instrumentID=int(iid), isBuy=True, units=float(units),
                initialUnits=float(units), openRate=float(open_rate),
                amount=amt, initialAmountInDollars=amt,
                unitsBaseValueDollars=round(units * open_rate, 2),
                leverage=int(leverage), orderID=int(order_id or 0),
                takeProfitRate=0.0, stopLossRate=0.0,
                openDateTime=opened.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
                + "Z")


def _totals(used, frozen):
    """aggregate-portfolio as the sync and the re-read read it."""
    return {"accountCurrency": "USD", "accountTotals": {
        "accountTotalValue": 100000.0,
        "accountAvailableCash": 100000.0 - used,
        "accountTotalUsedMargin": used, "accountFrozenCash": frozen,
        "accountCurrentPnl": 0.0, "accountBalance": 100000.0}}


def _utc_minute(at) -> str:
    return at.astimezone(dt_timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _until(note) -> str:
    """When a note lifts by itself: its time + IN_DOUBT_QUIET_HOURS."""
    return _utc_minute(datetime.fromisoformat(note["at"])
                       + timedelta(hours=12))


#: The two instruments these tests trade: the catalogue symbol, eToro's
#: spelling and id, the price, a ticket size and its stop and target.
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


def _manual_lane(user, *, mode="live"):
    from bot_program.manual_trade import manual_config_for
    cfg = manual_config_for(user, "commodity")
    cfg.mode = mode
    cfg.capital = Decimal("100000")
    cfg.base_currency = "USD"
    cfg.save(update_fields=["mode", "capital", "base_currency"])
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


def _wire_of():
    from bot_program.engine.etoro_client import EtoroTrader
    return EtoroTrader("k", "u", env="live")._sess()


def _book_bot(user, cfg, key, *, plan=None):
    """One entry through AssetBot.execute_entry on a hand-built candidate,
    the order through the real router and adapter onto the wire. (row or
    None, result)."""
    from bot_program.asset_engine.base import BotDecision, make_bot
    from bot_program.asset_engine.candidates import EntryCandidate
    from bot_program.models import AssetBotTrade
    from instruments.models import Instrument
    c = CASES[key]
    if plan is not None:
        _wire_of().plan(c["wire"], **plan)
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
    row = (AssetBotTrade.objects.get(pk=res["trade_id"])
           if res and res.get("trade_id") else None)
    return row, res


def _book_manual(user, key, *, plan=None):
    """One TAKE TRADE through manual_trade.execute_asset_trade (the
    instrument page's LONG), PIN confirmed. (row or None, result)."""
    from bot_program.manual_trade import execute_asset_trade
    from bot_program.models import AssetBotTrade
    from instruments.models import Instrument
    c = CASES[key]
    if plan is not None:
        _wire_of().plan(c["wire"], **plan)
    out = execute_asset_trade(user, Instrument.objects.get(symbol=c["symbol"]),
                              "BUY", qty=str(c["units"]), pin_ok=True)
    row = (AssetBotTrade.objects.get(pk=out["trade_id"])
           if out.get("ok") and out.get("trade_id") else None)
    return row, out


def _note_of(cfg, symbol):
    cfg.refresh_from_db()
    return ((cfg.extras or {}).get("entry_in_doubt") or {}).get(symbol)


def _age_note(cfg, symbol, seconds, **more):
    """The stored note, its time moved `seconds` back (and `more` set)."""
    cfg.refresh_from_db()
    extras = dict(cfg.extras or {})
    book = dict(extras["entry_in_doubt"])
    note = dict(book[symbol])
    note["at"] = (timezone.now() - timedelta(seconds=seconds)).isoformat()
    note.update(more)
    book[symbol] = note
    extras["entry_in_doubt"] = book
    cfg.extras = extras
    cfg.save(update_fields=["extras"])
    return note


def _preview(user, key):
    """The instrument page's LONG popup (preview_asset_trade)."""
    from bot_program.manual_trade import preview_asset_trade
    from instruments.models import Instrument
    return preview_asset_trade(
        user, Instrument.objects.get(symbol=CASES[key]["symbol"]), "BUY")


class _Clock:
    """timezone.now() in the test's hand: T0 when made, moved by at()."""

    def __init__(self):
        self.t0 = timezone.now()
        self.t = self.t0

    def __call__(self):
        return self.t

    def at(self, seconds):
        self.t = self.t0 + timedelta(seconds=seconds)


@override_settings(CACHES=LOCMEM)
class _WireBase(TestCase):

    username = "doubt_op"

    def setUp(self):
        self.user, self.acct, self.wire, self.guard = _world(self,
                                                             self.username)
        _gates_pass(self)

    def tearDown(self):
        self.assertEqual(self.guard.attempts, [], "a socket was opened")

    def _posts(self):
        return [c for c in self.wire.calls if c[0] == "POST"
                and c[1].endswith("/execution/orders")]

    def _alerts(self, words):
        from alerts.models import Notification
        return Notification.objects.filter(title__icontains=words)

    def _cells(self, *, frozen, read_ago_s=10, world="live", used=None):
        """eToro's cells as the sync stores them: read `read_ago_s` ago in
        `world`, `frozen` the frozen cash (None: the read did not carry
        it)."""
        self.acct.last_frozen_cash = (None if frozen is None
                                      else Decimal(str(frozen)))
        self.acct.last_used_margin = Decimal(str(
            used if used is not None else (frozen or 0)))
        self.acct.last_margin_at = (timezone.now()
                                    - timedelta(seconds=read_ago_s))
        self.acct.last_margin_world = world
        self.acct.save(update_fields=["last_frozen_cash", "last_used_margin",
                                      "last_margin_at", "last_margin_world"])

    def _settle_twice(self, cfg, symbol, note_age_s=130):
        """Two settles a lag apart, as two ticks would ask them: the first
        on a note `note_age_s` old, the second with its flat read moved a
        lag back. True when the note was cleared."""
        from bot_program.asset_engine.base import make_bot
        _age_note(cfg, symbol, note_age_s)
        make_bot(cfg)._settle_in_doubt(symbol, _note_of(cfg, symbol))
        note = _note_of(cfg, symbol)
        if note is None:
            return True
        note = _age_note(cfg, symbol, note_age_s, flat_read_at=(
            timezone.now() - timedelta(seconds=61)).isoformat())
        make_bot(cfg)._settle_in_doubt(symbol, note)
        return _note_of(cfg, symbol) is None

    def _working_row(self, cfg, key, *, opened_ago_s=3600, **meta):
        """A WORKING eToro row of the real world: an order eToro holds."""
        from bot_program.models import AssetBotTrade
        c = CASES[key]
        m = {"broker": "etoro", "broker_env": "live", "entry_working": True,
             "qty_requested": c["units"]}
        m.update(meta)
        t = AssetBotTrade.objects.create(
            config=cfg, asset_class="commodity", symbol=c["symbol"],
            side="BUY", qty=Decimal(str(c["units"])),
            entry_price=Decimal(str(c["price"])), status="OPEN", paper=False,
            stop_loss=Decimal(str(c["legs"][0])),
            take_profit=Decimal(str(c["legs"][1])), metadata=m)
        AssetBotTrade.objects.filter(pk=t.pk).update(
            opened_at=timezone.now() - timedelta(seconds=opened_ago_s))
        t.refresh_from_db()
        return t


# ── 1. the ticket remembers, tells and refuses ───────────────────────────

class TheTicketRemembersTests(_WireBase):

    def test_R1_take_trade_in_doubt_writes_the_note_and_one_alert(self):
        """The ticket's ReadTimeout left no note and no alert: the bot
        lane's own memory, title and body now."""
        mcfg = _manual_lane(self.user)
        row, out = _book_manual(self.user, "gold", plan={
            "raise": requests.exceptions.ReadTimeout("test: no answer")})
        note = _note_of(mcfg, "XAUUSD")
        self.assertIsNone(row)
        self.assertIn("MAY have reached the broker", out.get("error", ""))
        self.assertTrue(note, "the manual config carries no in-doubt note")
        self.assertTrue(note.get("reference"))
        alerts = self._alerts("may be live")
        self.assertEqual(alerts.count(), 1)
        alert = alerts.first()
        self.assertEqual(alert.title,
                         "⚠ XAUUSD: an order may be live with no row")
        self.assertIn("COMMODITY placement for XAUUSD did not come back. "
                      "Search the broker for reference "
                      f"{note['reference']}", alert.body)
        self.assertIn("XAUUSD is not retried for 12h.", alert.body)
        self.assertEqual(len(self._posts()), 1)

    def test_R2_take_trade_in_doubt_refuses_a_second_send(self):
        """A second ticket on the symbol sent a second order and booked a
        second row; it is refused in propose_entry's words."""
        _manual_lane(self.user)
        _book_manual(self.user, "gold", plan={
            "raise": requests.exceptions.ReadTimeout("test: no answer")})
        row2, out2 = _book_manual(self.user, "gold")
        self.assertEqual(len(self._posts()), 1,
                         "the second ticket sent another order while the "
                         "first may be live")
        self.assertIsNone(row2)
        err = out2.get("error", "")
        self.assertTrue(err.startswith("XAUUSD: an order under reference "),
                        err)
        self.assertIn("may already be live (since ", err)
        self.assertTrue(err.endswith("nothing was sent"), err)

    def test_R3b_take_trade_5xx_on_the_order_post_is_in_doubt(self):
        mcfg = _manual_lane(self.user)
        row, out = _book_manual(self.user, "gold", plan={
            "resp": _Resp(504, {"message": "test: gateway timeout"})})
        self.assertIsNone(row)
        self.assertTrue(_note_of(mcfg, "XAUUSD"))
        self.assertNotIn("refused", out.get("error", "").lower())
        self.assertIn("MAY have reached the broker", out.get("error", ""))
        self.assertIn("HTTP 504", out.get("error", ""))
        self.assertEqual(self._alerts("may be live").count(), 1)

    def test_the_ticket_asks_etoros_cells_again(self):
        """The C2 re-read: the pledge gate sees what eToro holds for the
        order within seconds instead of at the next sync."""
        _manual_lane(self.user)
        with mock.patch(REREAD) as asked:
            _book_manual(self.user, "gold", plan={
                "raise": requests.exceptions.ReadTimeout("test")})
        whys = [c.kwargs.get("why") for c in asked.call_args_list]
        self.assertEqual(whys, ["order in doubt"])
        self.assertEqual(asked.call_args.args[0], self.user)

    def test_a_note_written_after_the_lock_still_stops_the_order(self):
        """Another ticket's order on the symbol did not come back after
        this ticket's preview under the lock: the order does not leave."""
        from bot_program import manual_trade
        from bot_program.asset_engine.base import make_bot
        mcfg = _manual_lane(self.user)
        real = manual_trade._preview

        def _preview(*a, **kw):
            out = real(*a, **kw)
            if kw.get("ask_reread") is False:            # under the lock
                make_bot(type(mcfg).objects.get(pk=mcfg.pk)) \
                    ._remember_in_doubt("XAUUSD", "REF-OTHER")
            return out
        with mock.patch.object(manual_trade, "_preview", _preview):
            row, out = _book_manual(self.user, "gold")
        self.assertIsNone(row)
        self.assertEqual(len(self._posts()), 0)
        self.assertIn("an order under reference REF-OTHER may already be "
                      "live", out.get("error", ""))

    def test_the_preview_refuses_the_symbol_and_not_another(self):
        from bot_program.manual_trade import preview_asset_trade
        from instruments.models import Instrument
        _manual_lane(self.user)
        _book_manual(self.user, "gold", plan={
            "raise": requests.exceptions.ReadTimeout("test")})
        gold = preview_asset_trade(
            self.user, Instrument.objects.get(symbol="XAUUSD"), "BUY")
        self.assertIn("may already be live (since ", gold.get("error", ""))
        oil = preview_asset_trade(
            self.user, Instrument.objects.get(symbol="WTIUSD"), "BUY")
        self.assertNotIn("may already be live", oil.get("error", ""))
        self.assertEqual(len(self._posts()), 1)

    def test_an_expired_note_lets_the_ticket_send_again(self):
        """The hold is IN_DOUBT_QUIET_HOURS at most: a note that never
        expired would retire the symbol."""
        mcfg = _manual_lane(self.user)
        _book_manual(self.user, "gold", plan={
            "raise": requests.exceptions.ReadTimeout("test")})
        _age_note(mcfg, "XAUUSD", 12 * 3600 + 60)
        row, out = _book_manual(self.user, "gold")
        self.assertIsNotNone(row, out)
        self.assertEqual(len(self._posts()), 2)

    def test_a_paper_ticket_is_not_held_by_the_note(self):
        """The note holds what goes to the broker; a paper ticket sends
        nothing there."""
        mcfg = _manual_lane(self.user)
        _book_manual(self.user, "gold", plan={
            "raise": requests.exceptions.ReadTimeout("test")})
        mcfg.mode = "paper"
        mcfg.save(update_fields=["mode"])
        with mock.patch("bot_program.engine.paper_trader.paper_market_shut",
                        return_value=""):
            row, out = _book_manual(self.user, "gold")
        self.assertIsNotNone(row, out)
        self.assertTrue(row.paper)
        self.assertEqual(len(self._posts()), 1)
        self.assertTrue(_note_of(mcfg, "XAUUSD"))


# ── 2. the bot lane: a 5xx is in doubt too ───────────────────────────────

class TheBotLaneTests(_WireBase):

    def test_R3_bot_lane_5xx_on_the_order_post_is_in_doubt(self):
        from bot_program.asset_engine import skips
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        row, _res = _book_bot(self.user, cfg, "gold", plan={
            "resp": _Resp(502, {"message": "test: bad gateway"})})
        self.assertIsNone(row)
        self.assertTrue(_note_of(cfg, "XAUUSD"),
                        "a 5xx on the POST left no in-doubt note")
        self.assertEqual(self._alerts("may be live").count(), 1)
        skip = skips.last_by_symbol(cfg).get("XAUUSD")
        self.assertEqual(skip["code"], skips.ORDER_IN_DOUBT, skip)
        self.assertEqual(len(self._posts()), 1)

    def test_the_bot_lane_asks_etoros_cells_again_too(self):
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        with mock.patch(REREAD) as asked:
            _book_bot(self.user, cfg, "gold", plan={
                "raise": requests.exceptions.ReadTimeout("test")})
        self.assertEqual([c.kwargs.get("why") for c in asked.call_args_list],
                         ["order in doubt"])

    def test_the_next_tick_does_not_send_it_again(self):
        """propose_entry refuses the symbol on the note the 5xx left."""
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.base import make_bot
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        _book_bot(self.user, cfg, "gold", plan={
            "resp": _Resp(503, {"message": "test: unavailable"})})
        cfg.refresh_from_db()
        self.assertIsNone(make_bot(cfg).propose_entry("XAUUSD"))
        cfg.refresh_from_db()
        last = skips.last_by_symbol(cfg)["XAUUSD"]
        self.assertEqual(last["code"], skips.ORDER_IN_DOUBT)
        self.assertIn("may already be live", last["detail"])


# ── 2b. one note holds both lanes ────────────────────────────────────────

class TheNoteHoldsBothLanesTests(_WireBase):
    """The note lives on the config that sent the order, and each lane read
    its own only: after a TAKE TRADE in doubt a gold bot sent the same bet
    once venue health's quiet ended, and after a bot's order in doubt the
    ticket sent at once. Both lanes now refuse the symbol while any config
    of the user holds a fresh note on it — the bot lane in its proposal and
    again before the order leaves. The settle stays the owner's."""

    def _ticket_in_doubt(self):
        mcfg = _manual_lane(self.user)
        with mock.patch(REREAD):
            row, _out = _book_manual(self.user, "gold", plan={
                "raise": requests.exceptions.ReadTimeout("test: no answer")})
        self.assertIsNone(row)
        note = _note_of(mcfg, "XAUUSD")
        self.assertTrue(note)
        return mcfg, note

    def _bot_in_doubt(self):
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        with mock.patch(REREAD):
            row, _res = _book_bot(self.user, cfg, "gold", plan={
                "raise": requests.exceptions.ReadTimeout("test: no answer")})
        self.assertIsNone(row)
        note = _note_of(cfg, "XAUUSD")
        self.assertTrue(note)
        return cfg, note

    def _quiet_over(self):
        """As if venue health's quiet after the failed POST had passed."""
        from bot_program import venue_health as vh
        vh.reset()

    def _propose(self, cfg, symbol):
        """propose_entry with decide() answering HOLD: whether decide was
        reached (it is only past the in-doubt gates), and the skip."""
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.base import BotDecision, make_bot
        bot = make_bot(type(cfg).objects.get(pk=cfg.pk))
        hold = BotDecision(direction="HOLD", score=0.0, reasons=["test"],
                           rule_name="")
        with mock.patch.object(type(bot), "decide",
                               return_value=hold) as dec:
            self.assertIsNone(bot.propose_entry(symbol))
        cfg.refresh_from_db()
        return dec.called, skips.last_by_symbol(cfg).get(symbol)

    def test_a_tickets_note_holds_the_bot_lanes_proposal(self):
        from bot_program.asset_engine import skips
        mcfg, note = self._ticket_in_doubt()
        bcfg = _config(self.user, "gold bot", ["XAUUSD", "WTIUSD"])
        decided, skip = self._propose(bcfg, "XAUUSD")
        self.assertFalse(decided, "the bot lane decided past the ticket's "
                                  "note")
        self.assertEqual(skip["code"], skips.ORDER_IN_DOUBT, skip)
        self.assertTrue(skip["detail"].startswith(
            f"an order the TAKE TRADE ticket sent under reference "
            f"{note['reference']} may already be live (since "),
            skip["detail"])
        decided, _skip = self._propose(bcfg, "WTIUSD")
        self.assertTrue(decided, "another symbol is not held")
        self.assertTrue(_note_of(mcfg, "XAUUSD"))

    def test_a_tickets_note_holds_the_bot_lanes_send(self):
        """Asked again before the order leaves (execute_entry): a candidate
        proposed before the ticket's note, or built by hand, sends nothing
        either, after venue health's quiet as inside it."""
        from bot_program.asset_engine import skips
        mcfg, _note = self._ticket_in_doubt()
        bcfg = _config(self.user, "gold bot", ["XAUUSD"])
        self._quiet_over()
        with mock.patch(REREAD):
            row, _res = _book_bot(self.user, bcfg, "gold")
        self.assertIsNone(row)
        self.assertEqual(len(self._posts()), 1,
                         "the bot lane sent the bet the ticket's order may "
                         "already hold")
        bcfg.refresh_from_db()
        self.assertEqual(skips.last_by_symbol(bcfg)["XAUUSD"]["code"],
                         skips.ORDER_IN_DOUBT)
        self.assertTrue(_note_of(mcfg, "XAUUSD"))

    def test_a_bot_lanes_note_holds_the_ticket(self):
        bcfg, note = self._bot_in_doubt()
        _manual_lane(self.user)
        for quiet_over in (False, True):
            with self.subTest(quiet_over=quiet_over):
                if quiet_over:
                    self._quiet_over()
                err = _preview(self.user, "gold").get("error", "")
                self.assertTrue(err.startswith(
                    f"XAUUSD: an order the bot 'gold bot' sent under "
                    f"reference {note['reference']} may already be live "
                    f"(since "), err)
                self.assertIn(f"until {_until(note)} at the latest", err)
                self.assertTrue(err.endswith("nothing was sent"), err)
                row, out = _book_manual(self.user, "gold")
                self.assertIsNone(row)
                self.assertEqual(out.get("error"), err)
                self.assertEqual(len(self._posts()), 1)
        self.assertTrue(_note_of(bcfg, "XAUUSD"))

    def test_the_other_lanes_note_is_read_never_settled_there(self):
        """The ticket refuses on the bot's note and leaves its settle to
        the bot: eToro reads flat, and the bot's note is not touched."""
        bcfg, note = self._bot_in_doubt()
        _manual_lane(self.user)
        _age_note(bcfg, "XAUUSD", 130)
        self._cells(frozen=0)
        for _ in range(2):
            self.assertIn("may already be live",
                          _preview(self.user, "gold").get("error", ""))
        left = _note_of(bcfg, "XAUUSD")
        self.assertEqual(left["reference"], note["reference"])
        self.assertNotIn("flat_reads", left)

    def test_the_owners_settle_lifts_the_other_lane(self):
        bcfg, _note = self._bot_in_doubt()
        _manual_lane(self.user)
        self._cells(frozen=0)
        self.assertTrue(self._settle_twice(bcfg, "XAUUSD"))
        row, out = _book_manual(self.user, "gold")
        self.assertIsNotNone(row, out)
        self.assertEqual(len(self._posts()), 2)

    def test_a_paper_bot_is_not_held_by_another_lanes_note(self):
        """The hold is for what goes to a broker; a paper bot sends
        nothing there."""
        self._ticket_in_doubt()
        pcfg = _config(self.user, "paper gold bot", ["XAUUSD"], mode="paper")
        decided, _skip = self._propose(pcfg, "XAUUSD")
        self.assertTrue(decided)

    def test_an_expired_note_on_another_lane_holds_nothing(self):
        mcfg, _note = self._ticket_in_doubt()
        _age_note(mcfg, "XAUUSD", 12 * 3600 + 60)
        bcfg = _config(self.user, "gold bot", ["XAUUSD"])
        decided, _skip = self._propose(bcfg, "XAUUSD")
        self.assertTrue(decided)


# ── 3. the venue: a 5xx answer to the order POST ─────────────────────────

class TheVenueTests(SimpleTestCase):

    ORDERS = "/execution/demo/orders"

    def setUp(self):
        from tests.test_etoro_client import _clear_eligibility
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def _order(self, status, **kw):
        from tests.test_etoro_client import SEARCH_AAPL, _client
        t, fake = _client([SEARCH_AAPL,
                           ("POST", self.ORDERS, status, {"m": "x"})])
        with mock.patch("time.sleep"):
            t.market_order("AAPL", "BUY", 1.0, stop_loss=180.0,
                           take_profit=210.0, **kw)
        return fake

    def test_a_5xx_on_the_order_post_is_in_doubt_with_its_reference(self):
        import uuid

        from bot_program import venue_health as vh
        from bot_program.engine.etoro_client import EtoroOrderInDoubt
        for status in (500, 502, 503, 504):
            with self.subTest(status=status):
                vh.reset()
                coid = str(uuid.uuid4())
                with self.assertRaises(EtoroOrderInDoubt) as cm, \
                        self.assertLogs("bot_program.engine.etoro_client",
                                        level="ERROR") as logs:
                    self._order(status, client_order_id=coid)
                e = cm.exception
                self.assertTrue(getattr(e, "in_doubt", False))
                self.assertIsInstance(e, RuntimeError)
                self.assertEqual(e.reference, coid)
                self.assertEqual(e.client_order_id, coid)
                self.assertEqual(e.symbol, "AAPL")
                self.assertIn(f"(HTTP {status}", str(e))
                self.assertIn("MAY be live at eToro", str(e))
                self.assertNotIn("refused", str(e).lower())
                self.assertTrue(any("IN DOUBT" in m and "NOT retried" in m
                                    for m in logs.output))
                s = vh.sick("etoro", "demo")
                self.assertIsNotNone(s, "the venue's health note stays")
                self.assertEqual(s["failures"][-1]["code"], status)

    def test_the_post_is_sent_once_and_nothing_is_polled(self):
        from bot_program.engine.etoro_client import EtoroOrderInDoubt
        from tests.test_etoro_client import SEARCH_AAPL, _client
        t, fake = _client([SEARCH_AAPL, ("POST", self.ORDERS, 502, {})])
        with self.assertRaises(EtoroOrderInDoubt), mock.patch("time.sleep"):
            t.market_order("AAPL", "BUY", 1.0, stop_loss=180.0,
                           take_profit=210.0)
        self.assertEqual(len([c for c in fake.calls if c[0] == "POST"
                              and self.ORDERS in c[1]]), 1)
        self.assertEqual([c for c in fake.calls if "orders:lookup" in c[1]],
                         [])

    def test_a_429_and_every_4xx_stay_refusals(self):
        from bot_program import venue_health as vh
        for status in (429, 400, 401, 403, 404, 409, 422):
            with self.subTest(status=status):
                vh.reset()
                with self.assertRaises(RuntimeError) as cm:
                    self._order(status)
                self.assertFalse(getattr(cm.exception, "in_doubt", False))
                self.assertIn(f"eToro refused ({status})", str(cm.exception))


# ── 4. the settle reads eToro's frozen cash ──────────────────────────────

class TheSettleReadsTheFrozenCashTests(_WireBase):

    def test_R8_in_doubt_note_stands_while_frozen_cash_is_unexplained(self):
        """eToro took the order and holds it (WaitingForMarket, the measured
        D2b-i shape): used = frozen = its frozenAmount, /portfolio []. Two
        flat reads cleared the note."""
        from bot_program.asset_engine.base import make_bot
        from bot_program.tasks import sync_etoro_accounts
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        _book_bot(self.user, cfg, "gold", plan={
            "raise": requests.exceptions.ReadTimeout("test")})
        self.wire.totals = {"accountCurrency": "USD", "accountTotals": {
            "accountTotalValue": 100000.0, "accountAvailableCash": 98000.0,
            "accountTotalUsedMargin": 2000.0, "accountFrozenCash": 2000.0,
            "accountCurrentPnl": 0.0, "accountBalance": 100000.0}}
        sync_etoro_accounts()
        cfg.refresh_from_db()
        note = dict(cfg.extras["entry_in_doubt"]["XAUUSD"])
        note["at"] = (timezone.now() - timedelta(minutes=4)).isoformat()
        make_bot(cfg)._settle_in_doubt("XAUUSD", note)
        cfg.refresh_from_db()
        n2 = dict(cfg.extras["entry_in_doubt"].get("XAUUSD") or note)
        n2["flat_read_at"] = (timezone.now()
                              - timedelta(minutes=2)).isoformat()
        make_bot(cfg)._settle_in_doubt("XAUUSD", n2)
        left = _note_of(cfg, "XAUUSD")
        self.assertTrue(left, "the note cleared while eToro holds an order "
                              "no Sauron row explains")
        self.assertNotIn("flat_reads", left)
        self.assertIn("eToro holds 2,000.00 USD of frozen cash no Sauron "
                      "order explains", left["held"]["words"])
        self.assertEqual((left["held"]["frozen"], left["held"]["explained"]),
                         (2000.0, 0.0))

    def test_the_skip_and_the_ticket_say_why_the_note_stands(self):
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.base import make_bot
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        _book_bot(self.user, cfg, "gold", plan={
            "raise": requests.exceptions.ReadTimeout("test")})
        _age_note(cfg, "XAUUSD", 130)
        self._cells(frozen=2000)
        self.assertIsNone(make_bot(cfg).propose_entry("XAUUSD"))
        cfg.refresh_from_db()
        last = skips.last_by_symbol(cfg)["XAUUSD"]
        self.assertEqual(last["code"], skips.ORDER_IN_DOUBT)
        self.assertIn("may already be live", last["detail"])
        self.assertIn("eToro holds 2,000.00 USD of frozen cash",
                      last["detail"])

    def test_frozen_cash_a_working_row_explains_lets_two_flat_reads_clear(self):
        """A gold order Sauron booked WORKING (2,000 at 1x) and its fee:
        2,001 frozen is explained, and the oil note clears as before."""
        cfg = _config(self.user, "oil bot", ["WTIUSD"])
        _book_bot(self.user, cfg, "oil", plan={
            "raise": requests.exceptions.ReadTimeout("test")})
        self._working_row(_config(self.user, "gold bot", ["XAUUSD"]), "gold")
        self._cells(frozen=2001)
        self.assertTrue(self._settle_twice(cfg, "WTIUSD"))

    def test_frozen_cash_past_the_working_rows_keeps_the_note(self):
        cfg = _config(self.user, "oil bot", ["WTIUSD"])
        _book_bot(self.user, cfg, "oil", plan={
            "raise": requests.exceptions.ReadTimeout("test")})
        self._working_row(_config(self.user, "gold bot", ["XAUUSD"]), "gold")
        self._cells(frozen=3800)
        self.assertFalse(self._settle_twice(cfg, "WTIUSD"))
        held = _note_of(cfg, "WTIUSD")["held"]
        self.assertEqual((held["frozen"], held["explained"]), (3800.0, 2000.0))
        self.assertIn("eToro holds 1,800.00 USD of frozen cash no Sauron "
                      "order explains", held["words"])

    def test_a_working_row_booked_after_the_read_explains_nothing(self):
        cfg = _config(self.user, "oil bot", ["WTIUSD"])
        _book_bot(self.user, cfg, "oil", plan={
            "raise": requests.exceptions.ReadTimeout("test")})
        self._working_row(_config(self.user, "gold bot", ["XAUUSD"]), "gold",
                          opened_ago_s=2)
        self._cells(frozen=2000, read_ago_s=10)
        self.assertFalse(self._settle_twice(cfg, "WTIUSD"))

    def test_a_cell_read_before_the_note_cannot_clear_it(self):
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        _book_bot(self.user, cfg, "gold", plan={
            "raise": requests.exceptions.ReadTimeout("test")})
        self._cells(frozen=0, read_ago_s=600)
        self.assertFalse(self._settle_twice(cfg, "XAUUSD"))
        self.assertNotIn("flat_reads", _note_of(cfg, "XAUUSD"))

    def test_a_cell_read_in_the_other_world_cannot_clear_it(self):
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        _book_bot(self.user, cfg, "gold", plan={
            "raise": requests.exceptions.ReadTimeout("test")})
        self._cells(frozen=0, world="demo")
        self.assertFalse(self._settle_twice(cfg, "XAUUSD"))
        self.assertNotIn("flat_reads", _note_of(cfg, "XAUUSD"))

    def test_nothing_frozen_and_two_flat_reads_clear_the_note(self):
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        _book_bot(self.user, cfg, "gold", plan={
            "raise": requests.exceptions.ReadTimeout("test")})
        self._cells(frozen=0)
        self.assertTrue(self._settle_twice(cfg, "XAUUSD"))

    def test_a_cell_never_stored_keeps_the_old_rule(self):
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        _book_bot(self.user, cfg, "gold", plan={
            "raise": requests.exceptions.ReadTimeout("test")})
        self._cells(frozen=None, read_ago_s=600)
        self.assertTrue(self._settle_twice(cfg, "XAUUSD"))

    def test_a_position_at_etoro_keeps_the_note_whatever_the_cash(self):
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        _book_bot(self.user, cfg, "gold", plan={
            "raise": requests.exceptions.ReadTimeout("test")})
        self.wire.portfolio.append(_portfolio_row(7001, 18, 0.5, 4000.0, 1))
        self._cells(frozen=0)
        self.assertFalse(self._settle_twice(cfg, "XAUUSD"))


class TheFrozenReadBehindAFlatReadTests(_WireBase):
    """A flat read counted once eToro's frozen cash was read after the
    note, and the likeliest such read is the one the in-doubt call itself
    queues, SETTLE_S (3 s) after it. eToro, slow or failing enough to lose
    the answer, may register and hold the order after that read: one read
    backed both flat reads, the note cleared while eToro held the order,
    and the next ticket sent a second one. The frozen read behind a flat
    read now obeys the position read's rule: past the venue's lag since the
    note, and newer than the previous flat read."""

    username = "doubt_floor"

    def _ticket_in_doubt(self):
        mcfg = _manual_lane(self.user)
        with mock.patch(REREAD):
            row, _out = _book_manual(self.user, "gold", plan={
                "raise": requests.exceptions.ReadTimeout("test")})
        self.assertIsNone(row)
        self.assertTrue(_note_of(mcfg, "XAUUSD"))
        return mcfg

    def test_a_cell_read_3s_after_the_note_backs_no_flat_read(self):
        from bot_program.tasks import sync_etoro_accounts
        mcfg = self._ticket_in_doubt()
        # the in-doubt re-read, 3 s after the note (aged to 130 s by
        # _settle_twice): eToro had frozen nothing yet
        self._cells(frozen=0, read_ago_s=127)
        self.assertFalse(self._settle_twice(mcfg, "XAUUSD"),
                         "one frozen read taken 3 s after the note backed "
                         "both flat reads")
        self.assertNotIn("flat_reads", _note_of(mcfg, "XAUUSD"))
        # eToro took the order and holds it; the next sync reads it
        self.wire.totals = _totals(2000.0, 2000.0)
        sync_etoro_accounts()
        row, out = _book_manual(self.user, "gold")
        self.assertIsNone(row)
        self.assertEqual(len(self._posts()), 1)
        self.assertIn("eToro holds 2,000.00 USD of frozen cash no Sauron "
                      "order explains", out.get("error", ""))

    def test_each_flat_read_needs_a_frozen_read_newer_than_the_last(self):
        from bot_program.asset_engine.base import make_bot

        def settle():
            make_bot(type(mcfg).objects.get(pk=mcfg.pk))._settle_in_doubt(
                "XAUUSD", _note_of(mcfg, "XAUUSD"))
        mcfg = self._ticket_in_doubt()
        _age_note(mcfg, "XAUUSD", 130)
        self._cells(frozen=0, read_ago_s=65)          # past the lag: counts
        settle()
        self.assertEqual(_note_of(mcfg, "XAUUSD").get("flat_reads"), 1)
        # a lag later, on the same cell: it backed the first flat read
        _age_note(mcfg, "XAUUSD", 130, flat_read_at=(
            timezone.now() - timedelta(seconds=61)).isoformat())
        settle()
        left = _note_of(mcfg, "XAUUSD")
        self.assertTrue(left, "the read behind the first flat read backed "
                              "the second")
        self.assertEqual(left.get("flat_reads"), 1)
        # a newer read: the second flat read counts, and the note clears
        self._cells(frozen=0, read_ago_s=5)
        settle()
        self.assertIsNone(_note_of(mcfg, "XAUUSD"))

    def test_an_early_read_that_shows_the_cash_still_keeps_the_note(self):
        """The rule is for a flat read: a read after the note that shows
        frozen cash no row explains keeps the note and says so, early or
        not."""
        mcfg = self._ticket_in_doubt()
        self._cells(frozen=2000, read_ago_s=127)
        self.assertFalse(self._settle_twice(mcfg, "XAUUSD"))
        self.assertIn("eToro holds 2,000.00 USD of frozen cash",
                      _note_of(mcfg, "XAUUSD")["held"]["words"])


class TheFrozenReadTimelineTests(_WireBase):
    """The review's timeline, on one clock, through the real re-read, the
    real previews, the real ticket and the real sync."""

    username = "doubt_clock"

    def setUp(self):
        super().setUp()
        self.clock = _Clock()
        p = mock.patch("django.utils.timezone.now", self.clock)
        p.start()
        self.addCleanup(p.stop)

    def test_the_reread_before_etoro_registers_the_order_clears_nothing(self):
        from bot_program.tasks import refresh_etoro_cells, sync_etoro_accounts
        _manual_lane(self.user)
        self.wire.totals = _totals(0.0, 0.0)
        with mock.patch(REREAD):                                  # T0
            row, _out = _book_manual(self.user, "gold", plan={
                "raise": requests.exceptions.ReadTimeout("test")})
        self.assertIsNone(row)
        self.clock.at(3)               # the re-read the in-doubt call asks
        self.assertTrue(refresh_etoro_cells(self.acct.pk,
                                            why="order in doubt")["read"])
        # eToro registers the order and HOLDS it: used = frozen, no row
        self.wire.totals = _totals(2000.0, 2000.0)
        for t in (70, 131):            # the operator opens the ticket again
            self.clock.at(t)
            self.assertIn("may already be live",
                          _preview(self.user, "gold").get("error", ""),
                          f"T0+{t}")
        self.clock.at(140)
        row2, out2 = _book_manual(self.user, "gold")
        self.assertIsNone(row2, out2)
        self.assertEqual(len(self._posts()), 1)
        self.clock.at(300)             # the sync's beat reads what eToro holds
        sync_etoro_accounts()
        self.clock.at(310)
        self.assertIn("eToro holds 2,000.00 USD of frozen cash no Sauron "
                      "order explains",
                      _preview(self.user, "gold").get("error", ""))


class SauronsOwnPositionIsNotTheOrderTests(_WireBase):
    """eToro opens each order as its own position, so one whose id a
    Sauron row records cannot be the order whose answer did not come back.
    The settle kept the note for ANY position on the symbol: adding to a
    symbol the ticket's lane already holds — sizing, for the ticket — was
    refused for the note's whole 12 h after one timeout, with /portfolio
    listing only the lane's own position and nothing frozen."""

    username = "doubt_ownrow"

    def _hold_then_doubt(self):
        """The first ticket fills (a row with eToro's position id); an hour
        later a second ticket on the symbol times out after the POST and
        eToro takes nothing."""
        mcfg = _manual_lane(self.user)
        row1, out1 = _book_manual(self.user, "gold")
        self.assertIsNotNone(row1, out1)
        pid = str((row1.metadata or {}).get("broker_position_id") or "")
        self.assertTrue(pid)
        type(row1).objects.filter(pk=row1.pk).update(
            opened_at=timezone.now() - timedelta(hours=1))
        with mock.patch(REREAD):
            row2, _out2 = _book_manual(self.user, "gold", plan={
                "raise": requests.exceptions.ReadTimeout("test")})
        self.assertIsNone(row2)
        self.assertTrue(_note_of(mcfg, "XAUUSD"))
        self.assertEqual([str(p["positionID"]) for p in self.wire.portfolio],
                         [pid])
        return mcfg, pid

    def test_the_lanes_own_position_lets_the_note_settle(self):
        mcfg, _pid = self._hold_then_doubt()
        self._cells(frozen=0)
        self.assertTrue(self._settle_twice(mcfg, "XAUUSD"))
        row3, out3 = _book_manual(self.user, "gold")
        self.assertIsNotNone(row3, out3)
        self.assertEqual(len(self._posts()), 3)

    def test_a_position_under_a_new_id_keeps_the_note(self):
        """eToro did take the second order: its own id, no Sauron row."""
        mcfg, _pid = self._hold_then_doubt()
        self.wire.portfolio.append(_portfolio_row(880000777, 18, 0.5, 4000.0,
                                                  1))
        self._cells(frozen=0)
        self.assertFalse(self._settle_twice(mcfg, "XAUUSD"))

    def test_a_held_order_beside_the_lanes_position_keeps_the_note(self):
        mcfg, _pid = self._hold_then_doubt()
        self._cells(frozen=2000)
        self.assertFalse(self._settle_twice(mcfg, "XAUUSD"))
        self.assertIn("frozen cash no Sauron order explains",
                      _note_of(mcfg, "XAUUSD")["held"]["words"])

    def test_the_refusal_says_why_the_note_stands_and_until_when(self):
        mcfg, _pid = self._hold_then_doubt()
        self.wire.portfolio.append(_portfolio_row(7001, 18, 0.5, 4000.0, 1))
        self._cells(frozen=0)
        note = _age_note(mcfg, "XAUUSD", 130)
        row3, out3 = _book_manual(self.user, "gold")
        err = out3.get("error", "")
        self.assertIsNone(row3)
        self.assertIn("the broker lists a position on XAUUSD that no Sauron "
                      "row owns (position 7001), which may be this order", err)
        self.assertIn(f"until {_until(note)} at the latest", err)
        self.assertEqual(len(self._posts()), 2)

    def test_an_unnamed_position_no_row_owns_keeps_the_note_and_says_so(self):
        mcfg, _pid = self._hold_then_doubt()
        self.wire.portfolio.append(_portfolio_row(880000778, 4242, 1.0, 10.0,
                                                  1))
        self._cells(frozen=0)
        self.assertFalse(self._settle_twice(mcfg, "XAUUSD"))
        err = _preview(self.user, "gold").get("error", "")
        self.assertIn("the broker lists a position it cannot name (position "
                      "880000778), which may be this order", err)


class TheHeldWordsFollowTheLatestReadTests(_WireBase):
    """A "held" verdict wrote the note's held words and only a counted
    flat read removed them: once the held order filled (eToro lists the
    position, nothing frozen) the skip and the ticket still said "eToro
    holds 2,000.00 USD of frozen cash" as present fact. The first read that
    does not show it drops them, and they lead with their read's time,
    which the skip's 200 characters cut off."""

    username = "doubt_words"

    def _held_first(self, cfg):
        """The note 130 s old; eToro's cells read 10 s ago hold 2,000."""
        from bot_program.asset_engine.base import make_bot
        _age_note(cfg, "XAUUSD", 130)
        self._cells(frozen=2000, read_ago_s=10)
        make_bot(cfg)._settle_in_doubt("XAUUSD", _note_of(cfg, "XAUUSD"))
        self.assertIn("held", _note_of(cfg, "XAUUSD"))

    def _it_fills(self, **cells):
        """The held order fills at the open: eToro lists the position and
        freezes nothing, read just now."""
        self.wire.portfolio.append(_portfolio_row(7001, 18, 0.5, 4000.0, 1))
        cells.setdefault("frozen", 0)
        cells.setdefault("used", 2000)
        self._cells(read_ago_s=1, **cells)

    def _bot_lane(self):
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        _book_bot(self.user, cfg, "gold", plan={
            "raise": requests.exceptions.ReadTimeout("test")})
        return cfg

    def _ticket_lane(self):
        cfg = _manual_lane(self.user)
        with mock.patch(REREAD):
            _book_manual(self.user, "gold", plan={
                "raise": requests.exceptions.ReadTimeout("test")})
        return cfg

    def test_the_skip_says_what_the_latest_read_shows(self):
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.base import make_bot
        cfg = self._bot_lane()
        self._held_first(cfg)
        self._it_fills()
        self.assertIsNone(make_bot(cfg).propose_entry("XAUUSD"))
        cfg.refresh_from_db()
        last = skips.last_by_symbol(cfg)["XAUUSD"]
        self.assertEqual(last["code"], skips.ORDER_IN_DOUBT)
        self.assertNotIn("eToro holds", last["detail"])
        self.assertNotIn("held", _note_of(cfg, "XAUUSD"))

    def test_the_ticket_says_what_the_latest_read_shows(self):
        cfg = self._ticket_lane()
        self._held_first(cfg)
        self._it_fills()
        row, out = _book_manual(self.user, "gold")
        err = out.get("error", "")
        self.assertIsNone(row)
        self.assertNotIn("eToro holds", err)
        self.assertIn("the broker lists a position on XAUUSD that no Sauron "
                      "row owns (position 7001)", err)
        self.assertEqual(len(self._posts()), 1)

    def test_an_unreadable_list_or_the_other_world_drops_the_words(self):
        from bot_program.asset_engine.base import make_bot
        from bot_program.manual_trade import _in_doubt_refusal
        cfg = self._ticket_lane()
        real_get = self.wire._get

        def _down(url, params):
            if url.rstrip("/").endswith("/info/portfolio"):
                return _Resp(503, {"message": "test: down"})
            return real_get(url, params)
        for case in ("list unreadable", "other world"):
            with self.subTest(case=case):
                self._held_first(cfg)
                if case == "list unreadable":
                    self._cells(frozen=0, used=0, read_ago_s=1)
                    with mock.patch.object(self.wire, "_get", _down):
                        words = _in_doubt_refusal(make_bot(cfg), "XAUUSD")
                else:
                    self._cells(frozen=0, used=0, read_ago_s=1, world="demo")
                    words = _in_doubt_refusal(make_bot(cfg), "XAUUSD")
                self.assertIn("may already be live", words)
                self.assertNotIn("eToro holds", words)
                self.assertNotIn("held", _note_of(cfg, "XAUUSD"))

    def test_the_skip_dates_the_held_words_inside_its_200_characters(self):
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.base import make_bot
        cfg = self._bot_lane()
        self._held_first(cfg)
        self.assertIsNone(make_bot(cfg).propose_entry("XAUUSD"))
        cfg.refresh_from_db()
        detail = skips.last_by_symbol(cfg)["XAUUSD"]["detail"]
        self.acct.refresh_from_db()
        hm = self.acct.last_margin_at.astimezone(dt_timezone.utc)
        self.assertIn(f"read {hm:%H:%M} UTC: eToro holds 2,000.00", detail)


class AnotherVenueKeepsTheOldRuleTests(TestCase):

    ROUTER = "bot_program.engine.broker_router.client_for_symbol"

    def test_frozen_cash_on_the_users_etoro_row_is_not_read_for_it(self):
        from bot_program.models import EtoroAccount
        from tests.test_order_lifecycle import _bot
        from tests.test_venue_health import _FlatVenue
        user = User.objects.create_user("doubt_other", password="x")
        bot, cfg = _bot(user)
        EtoroAccount.objects.create(
            user=user, demo=False, label="Main", last_margin_world="live",
            last_frozen_cash=Decimal("2000"), last_used_margin=Decimal("2000"),
            last_margin_at=timezone.now())
        bot._remember_in_doubt("AAPL", "REF-1")
        venue = _FlatVenue()
        cfg.refresh_from_db()
        note = _age_note(cfg, "AAPL", 130)
        bot.cfg.refresh_from_db()
        with mock.patch(self.ROUTER, return_value=venue):
            self.assertFalse(bot._settle_in_doubt("AAPL", note))
        bot._tick_broker_cache = {}
        note = _age_note(cfg, "AAPL", 130, flat_reads=1, flat_read_at=(
            timezone.now() - timedelta(seconds=61)).isoformat())
        bot.cfg.refresh_from_db()
        with mock.patch(self.ROUTER, return_value=venue):
            self.assertTrue(bot._settle_in_doubt("AAPL", note))
        self.assertIsNone(_note_of(cfg, "AAPL"))

    def test_a_position_a_row_owns_is_never_skipped_off_etoro(self):
        """eToro alone is known to hold every position apart: on a venue
        that nets, the one position a row owns can carry the in-doubt
        order's fill too, so its id proves nothing there."""
        from tests.test_order_lifecycle import _bot, _open_trade
        from tests.test_venue_health import _FlatVenue
        user = User.objects.create_user("doubt_net", password="x")
        bot, cfg = _bot(user)
        _open_trade(cfg, broker="ibkr", broker_position_id="9")
        bot._remember_in_doubt("AAPL", "REF-1")
        venue = _FlatVenue([{"symbol": "AAPL", "qty": 20.0, "side": "BUY",
                             "position_id": "9"}])
        for flat_reads in (0, 1):
            note = _age_note(cfg, "AAPL", 130, **({} if not flat_reads else {
                "flat_reads": 1, "flat_read_at": (
                    timezone.now() - timedelta(seconds=61)).isoformat()}))
            bot.cfg.refresh_from_db()
            bot._tick_broker_cache = {}
            with mock.patch(self.ROUTER, return_value=venue):
                self.assertFalse(bot._settle_in_doubt("AAPL", note))
        self.assertTrue(_note_of(cfg, "AAPL"))


class TwoNotesOnOneLaneTests(TestCase):

    ROUTER = "bot_program.engine.broker_router.client_for_symbol"

    def _bot(self, name):
        from tests.test_order_lifecycle import _bot
        return _bot(User.objects.create_user(name, password="x"))

    def test_a_settle_never_writes_back_a_note_cleared_since(self):
        """Another reader (the ticket's preview, the next tick) cleared the
        note after this one read it: its flat read writes nothing back."""
        from tests.test_venue_health import _FlatVenue
        bot, cfg = self._bot("doubt_gone")
        bot._remember_in_doubt("AAPL", "REF-A")
        note = _age_note(cfg, "AAPL", 130)
        bot.cfg.refresh_from_db()
        type(cfg).objects.filter(pk=cfg.pk).update(
            extras={"entry_in_doubt": {}})
        with mock.patch(self.ROUTER, return_value=_FlatVenue()):
            self.assertFalse(bot._settle_in_doubt("AAPL", note))
        self.assertIsNone(_note_of(cfg, "AAPL"))

    def test_a_settle_leaves_a_newer_orders_note_as_it_is(self):
        """A second order on the symbol did not come back either while
        the first note was being settled: the clear is the first note's,
        and the second note stands."""
        from bot_program.asset_engine.base import make_bot
        from tests.test_venue_health import _FlatVenue
        bot, cfg = self._bot("doubt_newer")
        bot._remember_in_doubt("AAPL", "REF-A")
        note = _age_note(cfg, "AAPL", 130, flat_reads=1, flat_read_at=(
            timezone.now() - timedelta(seconds=61)).isoformat())
        bot.cfg.refresh_from_db()
        make_bot(type(cfg).objects.get(pk=cfg.pk))._remember_in_doubt(
            "AAPL", "REF-B")
        with mock.patch(self.ROUTER, return_value=_FlatVenue()):
            self.assertFalse(bot._settle_in_doubt("AAPL", note))
        self.assertEqual(_note_of(cfg, "AAPL")["reference"], "REF-B")

    def test_a_note_written_from_an_old_read_keeps_the_other(self):
        """The TAKE TRADE lane is one config for every symbol of its class:
        a ticket whose extras were read before another ticket's note was
        written must not erase that note."""
        from bot_program.asset_engine.base import make_bot
        from tests.test_order_lifecycle import _bot
        user = User.objects.create_user("doubt_two", password="x")
        first, cfg = _bot(user)
        second = make_bot(type(cfg).objects.get(pk=cfg.pk))
        first._remember_in_doubt("AAPL", "REF-A")
        second._remember_in_doubt("MSFT", "REF-B")
        cfg.refresh_from_db()
        self.assertEqual(sorted(cfg.extras["entry_in_doubt"]),
                         ["AAPL", "MSFT"])
        self.assertEqual(sorted(second.cfg.extras["entry_in_doubt"]),
                         ["AAPL", "MSFT"])


class WhatTheWorkingRowsExplainTests(TestCase):
    """base.frozen_explained: the margin of the orders eToro held for
    Sauron's own WORKING eToro rows of the world, at the cells' read."""

    def setUp(self):
        from tests.test_used_is_etoros import _cfg, _user
        self.user = _user("doubt_fx")
        self.cfg = _cfg(self.user, cls="commodity")
        self.at = timezone.now() - timedelta(seconds=60)

    def _row(self, symbol, qty, entry, **kw):
        from tests.test_used_is_etoros import _row
        return _row(self.cfg, symbol, qty, entry, **kw)

    def _meta(self, row, **meta):
        m = dict(row.metadata or {})
        m.update(meta)
        type(row).objects.filter(pk=row.pk).update(metadata=m)

    def _fx(self, world="live"):
        from bot_program.asset_engine.base import frozen_explained
        return frozen_explained(User.objects.get(pk=self.user.pk), world,
                                self.at)

    def test_working_rows_of_the_world_at_the_read_only(self):
        self._row("XAUUSD", 0.5, 4000, working=True)               # 2,000
        self._row("XAGUSD", 4, 50, working=True, lev=2)             # 100
        self._row("WTIUSD", 30, 60)                    # a position: not it
        self._row("XPTUSD", 1, 1000, working=True, opened_ago_s=5)  # since
        self._row("XPDUSD", 1, 1000, working=True, env="paper")     # demo
        self._row("NGUSD", 100, 3, working=True, broker="saxo")     # saxo
        fx = self._fx()
        self.assertEqual((fx["margin"], fx["n"]), (2100.0, 2))
        # a stock's 1.00 fee, a short's 1.98, BTC's 1 %: each row explains
        # its margin and the larger of 2.00 and 1 % of it more (20.00 on
        # the gold, 2.00 on the silver)
        self.assertEqual(fx["tolerance"], 22.0)
        self.assertEqual(self._fx("demo")["margin"], 1000.0)

    def test_a_row_filled_or_withdrawn_since_the_read_was_held_at_it(self):
        later = (timezone.now() - timedelta(seconds=30)).isoformat()
        earlier = (timezone.now() - timedelta(seconds=90)).isoformat()
        filled = self._row("XAUUSD", 0.5, 4000)
        self._meta(filled, qty_requested=0.5, entry_filled_at=later)
        gone = self._row("XAGUSD", 10, 50, status="CANCELED",
                         closed_ago_s=30)
        self._meta(gone, qty_requested=10.0, entry_withdrawn_at=later)
        old = self._row("WTIUSD", 30, 60)
        self._meta(old, qty_requested=30.0, entry_filled_at=earlier)
        self.assertEqual(self._fx()["margin"], 2500.0)

    def test_a_partial_explains_only_what_is_still_held(self):
        row = self._row("XAUUSD", 0.2, 4000, working=True)
        self._meta(row, qty_requested=0.5, entry_working_partial=0.2)
        self.assertEqual(self._fx()["margin"], 1200.0)

    def test_no_working_row_explains_nothing(self):
        self.assertEqual(self._fx(), {"margin": 0.0, "n": 0,
                                      "tolerance": 0.0})


# ── 5. the split names what eToro holds with no Sauron row ───────────────

def _fresh_note(cfg, symbol, *, minutes_ago=20, reference="REF-1"):
    at = timezone.now() - timedelta(minutes=minutes_ago)
    extras = dict(cfg.extras or {})
    book = dict(extras.get("entry_in_doubt") or {})
    book[symbol] = {"reference": reference, "at": at.isoformat()}
    extras["entry_in_doubt"] = book
    cfg.extras = extras
    cfg.save(update_fields=["extras"])
    return at.astimezone(dt_timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


class TheSplitNamesTheHeldPartTests(TestCase):

    def setUp(self):
        from tests.test_used_is_etoros import _cfg, _user
        self.user = _user("doubt_split")
        self.cfg = _cfg(self.user, cls="commodity")

    def _etoro(self, **kw):
        from tests.test_used_is_etoros import _etoro
        kw.setdefault("cash", "98000.00")
        kw.setdefault("pnl", "0.00")
        kw.setdefault("total", "100000.00")
        kw.setdefault("balance", "100000.00")
        return _etoro(self.user, **kw)

    def _used(self, **kw):
        from tests.test_used_is_etoros import _used
        return _used(self.user, **kw)

    def test_frozen_2000_and_no_working_row_is_a_held_part_of_2000(self):
        self._etoro(used="2000.00", frozen="2000.00")
        u = self._used()
        self.assertEqual((u["sauron"], u["outside"]), (0.0, 2000.0))
        self.assertEqual((u["held"], u["positions_part"]), (2000.0, 0.0))
        self.assertEqual((u["held_t"], u["positions_part_t"]),
                         ("2,000.00", "0.00"))
        self.assertEqual(u["split_t"], (
            "At that read: opened by Sauron 0.00 · outside Sauron 2,000.00 "
            "(held at eToro, no Sauron row 2,000.00, read 4 min ago; "
            "positions 0.00) · P&L +0.00"))

    def test_a_working_row_is_never_counted_twice(self):
        """Sauron's WORKING gold is under "opened by Sauron" already; its
        2,000 and the 1.00 fee eToro freezes with it are not "held with no
        Sauron row"."""
        from tests.test_used_is_etoros import _row
        _row(self.cfg, "XAUUSD", 0.5, 4000, working=True)
        self._etoro(used="2001.00", frozen="2001.00")
        u = self._used()
        self.assertEqual((u["sauron"], u["outside"]), (2000.0, 1.0))
        self.assertEqual((u["held"], u["positions_part"]), (0.0, 1.0))
        self.assertNotIn("held at eToro", u["split_t"])
        self.assertIn("· outside Sauron 1.00 · ", u["split_t"])

    def test_a_working_row_and_an_order_with_no_row(self):
        from tests.test_used_is_etoros import _row
        _row(self.cfg, "XAUUSD", 0.5, 4000, working=True)
        self._etoro(used="5000.00", frozen="3800.00")
        u = self._used()
        self.assertEqual((u["sauron"], u["outside"]), (2000.0, 3000.0))
        self.assertEqual((u["held"], u["positions_part"]), (1800.0, 1200.0))
        self.assertIn("· outside Sauron 3,000.00 (held at eToro, no Sauron "
                      "row 1,800.00, read 4 min ago; positions 1,200.00) · ",
                      u["split_t"])

    def test_a_rest_below_zero_is_said_the_other_way_round(self):
        """Sauron counts a position eToro no longer holds: the rest of the
        outside part reads below zero and is said as the split says its
        own excess (2026-10-31)."""
        from bot_program.models import EtoroAccount
        from tests.test_used_is_etoros import _row
        _row(self.cfg, "WTIUSD", 10, 100)                     # 1,000 counted
        self._etoro(used="2500.00", frozen="2500.00")
        u = self._used()
        self.assertEqual((u["outside"], u["held"], u["positions_part"]),
                         (1500.0, 2500.0, -1000.0))
        self.assertIn("· outside Sauron 1,500.00 (held at eToro, no Sauron "
                      "row 2,500.00, read 4 min ago; Sauron's rows count "
                      "1,000.00 more than eToro's positions) · ",
                      u["split_t"])
        EtoroAccount.objects.filter(user=self.user).update(
            last_used_margin=Decimal("800.00"),
            last_frozen_cash=Decimal("800.00"))
        u = self._used()
        self.assertEqual((u["outside"], u["held"]), (-200.0, 800.0))
        self.assertIn("· Sauron's rows count 200.00 more than eToro's used "
                      "(a row eToro no longer holds, or an unconverted "
                      "currency); held at eToro, no Sauron row 800.00, read "
                      "4 min ago · ", u["split_t"])

    def test_nothing_frozen_leaves_the_split_as_it_was(self):
        self._etoro(used="2000.00", frozen="0.00")
        u = self._used()
        self.assertEqual((u["held"], u["positions_part"]), (0.0, 2000.0))
        self.assertEqual(u["split_t"], (
            "At that read: opened by Sauron 0.00 · outside Sauron 2,000.00 "
            "· P&L +0.00"))

    def test_a_frozen_cell_never_stored_carves_nothing(self):
        """Unread is not zero: neither part is claimed."""
        self._etoro(used="2000.00", frozen=None)
        u = self._used()
        self.assertEqual(u["outside"], 2000.0)
        self.assertIsNone(u["held"])
        self.assertIsNone(u["positions_part"])
        self.assertEqual((u["held_t"], u["positions_part_t"]), ("—", "—"))
        self.assertNotIn("held at eToro", u["split_t"])

    def test_the_in_doubt_label_names_the_held_part_and_moves_no_number(self):
        self._etoro(used="2000.00", frozen="2000.00")
        before = self._used()
        when = _fresh_note(self.cfg, "XAUUSD")
        u = self._used()
        for key in ("used", "sauron", "stopped", "outside", "held",
                    "positions_part"):
            self.assertEqual(u[key], before[key], key)
        self.assertIn("(held at eToro, no Sauron row 2,000.00, read 4 min "
                      f"ago; XAUUSD: may be Sauron's order of {when} that "
                      "did not come back; positions 0.00)", u["split_t"])

    def test_a_note_on_any_of_the_users_configs_counts(self):
        from tests.test_used_is_etoros import _cfg
        self._etoro(used="2000.00", frozen="2000.00")
        lane = _cfg(self.user, cls="commodity", name="manual")
        when = _fresh_note(lane, "WTIUSD")
        self.assertIn(f"WTIUSD: may be Sauron's order of {when} that did not "
                      "come back", self._used()["split_t"])

    def test_an_expired_note_says_nothing(self):
        self._etoro(used="2000.00", frozen="2000.00")
        _fresh_note(self.cfg, "XAUUSD", minutes_ago=13 * 60)
        self.assertNotIn("may be Sauron's order", self._used()["split_t"])

    def test_an_outside_position_on_an_in_doubt_symbol_says_so(self):
        from tests.test_used_is_etoros import _held
        self._etoro(used="2600.00", held=[
            _held("XAUUSD", 0.5, 4000, pid=7, amount=2000.0),
            _held("WTIUSD", 10, 60, pid=8, amount=600.0)])
        before = self._used(positions=True)["positions"]
        when = _fresh_note(self.cfg, "XAUUSD")
        out = self._used(positions=True)["positions"]
        by = {r["symbol"]: r for r in out["rows"]}
        self.assertEqual(by["XAUUSD"]["in_doubt_t"],
                         f"may be Sauron's order of {when} that did not come "
                         f"back")
        self.assertEqual(by["WTIUSD"]["in_doubt_t"], "")
        self.assertEqual([r["margin"] for r in out["rows"]],
                         [r["margin"] for r in before["rows"]])
        self.assertEqual(out["margin"], before["margin"])

    def test_the_treasury_page_and_command_print_it(self):
        from tests.test_used_is_etoros import _held
        self._etoro(used="4000.00", frozen="2000.00", held=[
            _held("XAUUSD", 0.5, 4000, pid=7, amount=2000.0)])
        when = _fresh_note(self.cfg, "XAUUSD")
        self.client.force_login(self.user)
        page = self.client.get(reverse("treasury_page")).content.decode()
        out = StringIO()
        call_command("treasury", user="doubt_split", stdout=out)
        label = f"may be Sauron&#x27;s order of {when} that did not come back"
        self.assertIn(label, page)
        self.assertIn("held at eToro, no Sauron row 2,000.00", page)
        body = out.getvalue()
        self.assertIn(label.replace("&#x27;", "'"), body)
        self.assertIn("held at eToro, no Sauron row 2,000.00", body)

    def test_the_title_says_what_the_held_part_is(self):
        self._etoro(used="2000.00", frozen="2000.00")
        self.assertIn("Held at eToro, no Sauron row", self._used()["title"])


class TheLabelNamesOnlyWhatCouldCarryTheOrderTests(TestCase):
    """The label was chosen by symbol and the note's freshness alone: a
    holdings list or a frozen-cash read taken before Sauron's order left
    cannot carry it, and a position eToro opened before then cannot be it,
    yet for up to a sync after the alert the Treasury and the treasury
    command named an earlier position on the symbol (one opened in the
    eToro app) "may be Sauron's order". It now names only a read stamped no
    earlier than LIST_LAG_S before the note, and never a position whose
    own open time (eToro's openDateTime) is earlier than that."""

    def setUp(self):
        from tests.test_used_is_etoros import _cfg, _user
        self.user = _user("doubt_reads")
        self.cfg = _cfg(self.user, cls="commodity")

    def _etoro(self, **kw):
        from tests.test_used_is_etoros import _etoro
        for k, v in (("cash", "98000.00"), ("pnl", "0.00"),
                     ("total", "100000.00"), ("balance", "100000.00")):
            kw.setdefault(k, v)
        return _etoro(self.user, **kw)

    def _used(self, **kw):
        from tests.test_used_is_etoros import _used
        return _used(self.user, **kw)

    def _held(self, pid, *, opened_ago_s=None):
        from tests.test_used_is_etoros import _held
        row = _held("XAUUSD", 0.5, 4000, pid=pid, amount=2000.0)
        if opened_ago_s is not None:
            row["opened_at"] = (timezone.now() - timedelta(
                seconds=opened_ago_s)).isoformat()
        return row

    def _labels(self):
        return {r["position_id"]: r["in_doubt_t"]
                for r in self._used(positions=True)["positions"]["rows"]}

    def test_a_position_listed_before_the_order_is_not_labelled(self):
        self._etoro(used="2000.00", frozen="0.00", held=[self._held(7)])
        _fresh_note(self.cfg, "XAUUSD", minutes_ago=1)       # list: 4 min
        self.assertEqual(self._labels(), {"7": ""})

    def test_a_list_read_inside_the_slack_before_the_note_is_labelled(self):
        """The sync stamps the list before its reads, and the order left up
        to its timeout before the note: a list stamped within LIST_LAG_S
        before the note may carry it."""
        self._etoro(used="2000.00", frozen="0.00", held=[self._held(7)],
                    held_age_s=120)
        when = _fresh_note(self.cfg, "XAUUSD", minutes_ago=1.5)
        self.assertEqual(self._labels(), {
            "7": f"may be Sauron's order of {when} that did not come back"})

    def test_a_position_eToro_opened_before_the_order_is_never_labelled(self):
        """After the next sync the list carries the earlier position and
        the order's fill: only the fill can be the order."""
        self._etoro(used="4000.00", frozen="0.00", held_age_s=10, held=[
            self._held(7001, opened_ago_s=3 * 3600),
            self._held(7002, opened_ago_s=100)])
        when = _fresh_note(self.cfg, "XAUUSD", minutes_ago=2)
        self.assertEqual(self._labels(), {
            "7001": "",
            "7002": f"may be Sauron's order of {when} that did not come "
                    f"back"})

    def test_the_held_part_read_before_the_order_is_not_labelled(self):
        self._etoro(used="2000.00", frozen="2000.00")        # cells: 4 min
        before = self._used()
        _fresh_note(self.cfg, "XAUUSD", minutes_ago=1)
        u = self._used()
        for key in ("used", "sauron", "outside", "held", "positions_part"):
            self.assertEqual(u[key], before[key], key)
        self.assertEqual(u["held_doubt_t"], "")
        self.assertNotIn("may be Sauron's order", u["split_t"])
        self.assertIn("held at eToro, no Sauron row 2,000.00, read 4 min ago",
                      u["split_t"])

    def test_of_two_notes_the_label_names_the_one_the_read_can_carry(self):
        """Two orders on the symbol in doubt on two lanes: the cells read
        between them can carry the older one only."""
        from tests.test_used_is_etoros import _cfg
        self._etoro(used="2000.00", frozen="2000.00")        # cells: 4 min
        older = _fresh_note(self.cfg, "XAUUSD", minutes_ago=20)
        _fresh_note(_cfg(self.user, cls="commodity", name="manual"),
                    "XAUUSD", minutes_ago=1)
        self.assertEqual(self._used()["held_doubt_t"],
                         f"XAUUSD: may be Sauron's order of {older} that did "
                         f"not come back")


class TheHoldingsCarryEtorosOpenTimeTests(SimpleTestCase):
    """EtoroTrader.broker_portfolio keeps eToro's own open time of each
    position (openDateTime, MEASURED on the /portfolio row), as an ISO
    time, or None when the row does not carry a readable one."""

    def setUp(self):
        from tests.test_etoro_client import _clear_eligibility
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def test_the_open_time_rides_each_holding(self):
        from tests.test_etoro_client import PORTFOLIO_ROW, SEARCH_AAPL, _client
        t, _ = _client([SEARCH_AAPL, ("GET", "/portfolio", 200, {
            "clientPortfolio": {"positions": [
                dict(PORTFOLIO_ROW, instrumentID=1001),
                dict(PORTFOLIO_ROW, instrumentID=1001, positionID=2,
                     openDateTime=None),
                dict(PORTFOLIO_ROW, instrumentID=1001, positionID=3,
                     openDateTime="not a time"),
                dict(PORTFOLIO_ROW, instrumentID=1001, positionID=4,
                     openDateTime="2026-09-23T14:06:31")]}})])
        t.instrument_id("AAPL")
        rows = t.broker_portfolio()
        self.assertEqual([r["opened_at"] for r in rows],
                         ["2026-09-23T14:06:31.463000+00:00", None, None,
                          None])


class TheLabelOverTheWireTests(_WireBase):
    """The skeptic's timeline over the wire: an app position listed by the
    sync, Sauron's order in doubt, then the next beat listing its fill."""

    username = "doubt_label_wire"

    def _labels(self):
        from bot_program.etoro_used import account_used
        return {r["position_id"]: r["in_doubt_t"] for r in account_used(
            User.objects.get(pk=self.user.pk),
            positions=True)["positions"]["rows"]}

    def test_an_app_position_older_than_the_order_is_never_labelled(self):
        from bot_program.models import EtoroAccount
        from bot_program.tasks import sync_etoro_accounts
        self.wire.portfolio.append(_portfolio_row(
            7001, 18, 0.5, 4000.0, 1,
            opened=timezone.now() - timedelta(hours=3)))
        self.wire.totals = _totals(2000.0, 0.0)
        sync_etoro_accounts()
        then = timezone.now() - timedelta(seconds=240)    # that beat: 4 min
        EtoroAccount.objects.filter(pk=self.acct.pk).update(
            broker_positions_at=then, last_margin_at=then,
            last_equity_at=then, last_sync=then)
        cfg = _config(self.user, "gold bot", ["XAUUSD"])
        with mock.patch(REREAD):
            row, _res = _book_bot(self.user, cfg, "gold", plan={
                "raise": requests.exceptions.ReadTimeout("test")})
        self.assertIsNone(row)
        self.assertEqual(self._labels(), {"7001": ""})
        # eToro took it: the next beat lists its fill beside the app's
        self.wire.portfolio.append(_portfolio_row(7002, 18, 0.5, 4000.0, 1))
        self.wire.totals = _totals(4000.0, 0.0)
        sync_etoro_accounts()
        labels = self._labels()
        self.assertEqual(labels["7001"], "")
        self.assertTrue(labels["7002"].startswith("may be Sauron's order of "),
                        labels)


# ── 6. what moves no money ───────────────────────────────────────────────

class NoGateReadsTheHeldPartTests(SimpleTestCase):
    """The held part and the label are display: nothing on an order path
    reads etoro_used (C3's promise), and the gate's pledge still reads
    eToro's own used margin, which carries a held order."""

    def test_the_order_paths_do_not_import_the_display(self):
        import re
        from pathlib import Path

        from django.conf import settings
        base = Path(settings.BASE_DIR)
        pat = re.compile(r"^\s*(from\s+\S*etoro_used\s+import|"
                         r"import\s+\S*etoro_used|"
                         r"from\s+\S+\s+import\s+[^\n#]*\betoro_used\b)",
                         re.M)
        for rel in ("bot_program/asset_engine/base.py",
                    "bot_program/engine/etoro_client.py",
                    "portfolio/risk_gate.py"):
            src = (base / rel).read_text(encoding="utf-8")
            self.assertIsNone(pat.search(src), rel)
