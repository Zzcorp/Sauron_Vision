"""fill_open says whether the order filled, and a held order's fill is
announced (2026-11-07).

`fill_open` on the user's Eye socket (/ws/eye/) was pushed for every row
TAKE TRADE (manual_trade._execute) or the bot lane (AssetBot.execute_entry)
booked: an order the broker HOLDS unfilled (a WORKING entry, most often a
market order sent outside regular hours) included, with the same payload
as a fill. When that order filled later, the tick booked the fill
(AssetBot._finish_working_entry) and pushed nothing, and its bell row is
banner-silent because the push is what draws a fill. So a page could not
tell a fill from a held order, and a held order's fill went unannounced.

Now both pushes say `working` (the row's own entry_working: true for a held
order, false for a fill), and the tick pushes one fill_open with working
false once the fill is booked. Display only: each push comes after its
booking, inside its own try/except. The tests below book each case twice,
with the push answering and with it raising, and find the same orders sent,
the same rows booked, the same writes made and the same hooks registered.

Run with:  python manage.py test tests.test_fill_open_working
"""
import re
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection, transaction
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests.test_take_trade_live import (ROUTER, _arm_live, _components_on,
                                        _fake_live_client, _filled_response,
                                        _quote, _signal)
from tests.test_working_entries import _cfg, _client, _working_trade

PUSH = "dashboard.consumers.push_eye_event"

#: an order eToro holds unfilled, as the adapter answers it (TAKE TRADE)
HELD_TICKET = {"orderId": "7", "symbol": "BTCUSD", "side": "BUY",
               "executedQty": "0.0", "avgPrice": "0.0", "status": "PENDING",
               "working": True, "raw": {}}

#: the bot lane's two answers: held, and filled with its bracket resting
HELD_ENTRY = {"orderId": "101", "status": "WORKING", "working": True,
              "executedQty": "0", "avgPrice": "0",
              "protectiveOrders": ["12", "13"], "protectiveStopId": "13"}
FILLED_ENTRY = {"orderId": "102", "status": "FILLED", "executedQty": "5",
                "avgPrice": "100.25", "protectedOnFill": True,
                "protectiveOrders": ["12", "13"], "protectiveStopId": "13"}

#: the tick's reading of a held order that has filled whole
FILLED_10 = {"state": "filled", "filled": 10.0, "avgPrice": 99.75,
             "status": "Filled"}


def _answering(user, kind, data=None):
    return True


def _raising(user, kind, data=None):
    """The fill_open push raises (a channel layer gone mid-call, an import
    that failed); every other kind still answers."""
    if kind == "fill_open":
        raise RuntimeError("the socket is down")
    return True


def _fill_opens(pushed):
    """The payloads a patched push_eye_event was handed for fill_open, in
    order (a call whose push raised included)."""
    return [c.args[2] for c in pushed.call_args_list
            if len(c.args) > 2 and c.args[1] == "fill_open"]


class _Undo(Exception):
    """Ends a run's savepoint once its snapshot is taken."""


def _undone(run):
    """`run()` in a savepoint rolled back after it: what it returned, and
    the database as it was, so the next run books the very same case."""
    box = {}
    try:
        with transaction.atomic():
            box["seen"] = run()
            raise _Undo
    except _Undo:
        pass
    return box["seen"]


_WRITE = re.compile(r'^\s*(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+"?(\w+)"?',
                    re.IGNORECASE)


def _writes(queries):
    """Each write a run made, as (verb, table), in order."""
    out = []
    for q in queries:
        m = _WRITE.match(q["sql"])
        if m:
            out.append((" ".join(m.group(1).upper().split()), m.group(2)))
    return out


def _row(pk):
    """Every column of the booked row but its id, read back."""
    from bot_program.models import AssetBotTrade
    row = AssetBotTrade.objects.get(pk=pk)
    return {f.attname: getattr(row, f.attname)
            for f in AssetBotTrade._meta.concrete_fields if f.name != "id"}


def _orders(client):
    """Every call the broker client was handed, its own name first: what
    went to the venue, and what was asked of it."""
    return [(name, args, kwargs) for name, args, kwargs in client.mock_calls]


class _BookedTwice:
    """One booking, run twice under one clock: the push answering, then the
    push raising. Each run is rolled back after its snapshot."""

    LOGGER = ""

    def _twice(self, book):
        now = timezone.now()
        runs = []
        for push in (_answering, _raising):
            def run(push=push):
                cache.clear()
                with patch("django.utils.timezone.now", return_value=now), \
                        patch(PUSH, side_effect=push) as pushed, \
                        CaptureQueriesContext(connection) as queries, \
                        self.captureOnCommitCallbacks() as hooks:
                    if push is _raising:
                        # said, never raised: the push's own except logs it
                        with self.assertLogs(self.LOGGER, "WARNING") as logs:
                            seen = book()
                        self.assertTrue(
                            any("WS push" in line for line in logs.output),
                            logs.output)
                    else:
                        seen = book()
                seen["writes"] = _writes(queries.captured_queries)
                seen["hooks"] = [getattr(h, "__qualname__", repr(type(h)))
                                 for h in hooks]
                seen["fill_open"] = _fill_opens(pushed)
                return seen
            runs.append(_undone(run))
        return runs

    def _same(self, answered, raised, keys):
        for key in keys:
            self.assertEqual(answered[key], raised[key],
                             f"{key} differs when the push raises")


# ── TAKE TRADE (bot_program/manual_trade.py) ────────────────────────────────

class TheTicketSaysWhetherItFilledTests(_BookedTwice, TestCase):
    """The ticket's one push says whether the broker filled the order."""

    LOGGER = "bot_program.manual_trade"

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("fow_t", password="x")

    def setUp(self):
        cache.clear()
        self.inst = _quote("BTCUSD", 60000)
        _components_on()
        self.cfg = _arm_live(self.user)
        self.signal = _signal(self.inst)

    def _ticket(self, response):
        from bot_program.manual_trade import execute_take_trade
        fake = _fake_live_client(response)
        with patch(ROUTER, return_value=fake), patch(PUSH) as pushed:
            out = execute_take_trade(self.user, self.signal, pin_ok=True)
        self.assertTrue(out.get("ok"), out)
        return out, _fill_opens(pushed)

    def test_a_filled_ticket_says_it_filled(self):
        out, pushed = self._ticket(_filled_response())
        self.assertEqual(pushed, [{
            "trade_id": out["trade_id"], "asset_class": "crypto",
            "symbol": "BTCUSD", "side": "BUY", "working": False}])
        self.assertIs(pushed[0]["working"], False)

    def test_a_held_ticket_says_it_is_held(self):
        from bot_program.models import AssetBotTrade
        out, pushed = self._ticket(HELD_TICKET)
        self.assertTrue(out.get("working"), out)
        self.assertTrue(AssetBotTrade.objects.get(
            pk=out["trade_id"]).metadata["entry_working"])
        self.assertEqual(pushed, [{
            "trade_id": out["trade_id"], "asset_class": "crypto",
            "symbol": "BTCUSD", "side": "BUY", "working": True}])
        self.assertIs(pushed[0]["working"], True)

    def test_a_push_that_raises_changes_nothing_on_the_ticket(self):
        from bot_program.manual_trade import execute_take_trade
        from signals.models import Signal
        for response, working in ((_filled_response(), False),
                                  (HELD_TICKET, True)):
            with self.subTest(working=working):
                def book(response=response):
                    # read afresh: a rolled-back run leaves its writes on
                    # the objects it held (the instrument's watchlist star)
                    user = get_user_model().objects.get(pk=self.user.pk)
                    signal = Signal.objects.get(pk=self.signal.pk)
                    fake = _fake_live_client(dict(response))
                    with patch(ROUTER, return_value=fake):
                        out = execute_take_trade(user, signal, pin_ok=True)
                    self.assertTrue(out.get("ok"), out)
                    tid = out.pop("trade_id")
                    return {"tid": tid, "out": out, "row": _row(tid),
                            "orders": _orders(fake)}

                answered, raised = self._twice(book)
                self._same(answered, raised,
                           ("out", "row", "orders", "writes", "hooks"))
                for run in (answered, raised):
                    self.assertEqual([p["working"] for p in run["fill_open"]],
                                     [working])
                    self.assertEqual(run["fill_open"][0]["trade_id"],
                                     run["tid"])

    def test_a_paper_ticket_says_it_filled(self):
        from bot_program.manual_trade import execute_take_trade
        user = get_user_model().objects.create_user("fow_tp", password="x")
        with patch(PUSH) as pushed:
            out = execute_take_trade(user, _signal(self.inst))
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out["venue"], "paper")
        self.assertEqual(_fill_opens(pushed), [{
            "trade_id": out["trade_id"], "asset_class": "crypto",
            "symbol": "BTCUSD", "side": "BUY", "working": False}])


# ── the bot lane (AssetBot.execute_entry) ───────────────────────────────────

class TheBotEntrySaysWhetherItFilledTests(_BookedTwice, TestCase):
    """The engine's one push at the entry says whether it filled."""

    LOGGER = "bot_program.asset_engine.base"

    def setUp(self):
        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument
        from signals.models import Signal
        from signals.models_control import RuleControl
        cache.clear()
        self.user = get_user_model().objects.create_user("fow_b",
                                                         password="x")
        self.inst, _ = Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "AAPL", "asset_class": "stock"})
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="FOW", mode="live",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
        # a live entry needs a promoted rule: an unregistered one is
        # confined to paper whatever the config says
        RuleControl.objects.get_or_create(
            rule_name="r1", defaults={"promotion_stage": "live_full"})
        Signal.objects.create(
            instrument=self.inst, signal_type="composite",
            direction="bullish", urgency="medium", title="t",
            description="d", rule_name="r1", score=0.9, sub_scores={},
            price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
            is_active=True)

    def _client(self, order):
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": "100"}
        client.market_order.return_value = dict(order)
        return client

    def _scan(self, order):
        from bot_program.asset_engine.stock_bot import StockBot
        with patch(ROUTER, return_value=self._client(order)), \
                patch(PUSH) as pushed:
            res = StockBot(self.cfg).scan_symbol("AAPL")
        self.assertIsNotNone(res)
        return res, _fill_opens(pushed)

    def test_a_filled_entry_says_it_filled(self):
        res, pushed = self._scan(FILLED_ENTRY)
        self.assertEqual(pushed, [{
            "trade_id": res["trade_id"], "asset_class": "stock",
            "symbol": "AAPL", "side": "BUY", "working": False}])
        self.assertIs(pushed[0]["working"], False)

    def test_a_held_entry_says_it_is_held(self):
        from bot_program.models import AssetBotTrade
        res, pushed = self._scan(HELD_ENTRY)
        self.assertTrue(AssetBotTrade.objects.get(
            pk=res["trade_id"]).metadata["entry_working"])
        self.assertEqual(pushed, [{
            "trade_id": res["trade_id"], "asset_class": "stock",
            "symbol": "AAPL", "side": "BUY", "working": True}])
        self.assertIs(pushed[0]["working"], True)

    def test_a_push_that_raises_changes_nothing_on_the_entry(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotConfig
        for order, working in ((FILLED_ENTRY, False), (HELD_ENTRY, True)):
            with self.subTest(working=working):
                def book(order=order):
                    # read afresh: a rolled-back run leaves its writes on
                    # the objects it held
                    cfg = AssetBotConfig.objects.get(pk=self.cfg.pk)
                    client = self._client(order)
                    with patch(ROUTER, return_value=client):
                        res = StockBot(cfg).scan_symbol("AAPL")
                    self.assertIsNotNone(res)
                    res = dict(res)
                    tid = res.pop("trade_id")
                    return {"tid": tid, "out": res, "row": _row(tid),
                            "orders": _orders(client)}

                answered, raised = self._twice(book)
                self._same(answered, raised,
                           ("out", "row", "orders", "writes", "hooks"))
                for run in (answered, raised):
                    self.assertEqual([p["working"] for p in run["fill_open"]],
                                     [working])
                    self.assertEqual(run["fill_open"][0]["trade_id"],
                                     run["tid"])

    def test_a_paper_entry_says_it_filled(self):
        """The paper venue fills at once: never held."""
        from bot_program.asset_engine import StockBot
        from market_data.models import LiveQuote
        self.cfg.mode = "paper"
        self.cfg.save(update_fields=["mode"])
        LiveQuote.objects.update_or_create(
            instrument=self.inst, defaults={"last": Decimal("100")})
        with patch(PUSH) as pushed:
            res = StockBot(self.cfg).scan_symbol("AAPL")
        self.assertIsNotNone(res)
        self.assertEqual(_fill_opens(pushed), [{
            "trade_id": res["trade_id"], "asset_class": "stock",
            "symbol": "AAPL", "side": "BUY", "working": False}])


# ── the held order's fill (AssetBot._finish_working_entry) ──────────────────

class AHeldOrdersFillIsAnnouncedTests(_BookedTwice, TestCase):
    """The tick that books a held order's fill announces it, once."""

    LOGGER = "bot_program.asset_engine.base"

    def setUp(self):
        from instruments.models import Instrument
        cache.clear()
        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "NVDA", "asset_class": "stock"})
        self.user = get_user_model().objects.create_user("fow_f",
                                                         password="x")
        self.cfg = _cfg(self.user, name="FOWFILL")

    def _tick(self, client):
        from bot_program.asset_engine.stock_bot import StockBot
        with patch(ROUTER, return_value=client), patch(PUSH) as pushed:
            StockBot(self.cfg).manage_positions()
        return _fill_opens(pushed)

    def test_the_fill_is_announced_once_and_says_it_filled(self):
        trade = _working_trade(self.cfg)
        client = _client(dict(FILLED_10))
        pushed = self._tick(client)
        trade.refresh_from_db()
        self.assertNotIn("entry_working", trade.metadata)   # booked
        self.assertEqual(pushed, [{
            "trade_id": trade.id, "asset_class": "stock", "symbol": "NVDA",
            "side": "BUY", "working": False}])
        self.assertIs(pushed[0]["working"], False)
        # the next tick manages a position: its fill is not told again
        self.assertEqual(self._tick(client), [])

    def test_an_order_still_held_or_withdrawn_announces_no_fill(self):
        trade = _working_trade(
            self.cfg, entry_working_since=timezone.now().isoformat())
        held = _client({"state": "working", "filled": 0.0, "avgPrice": 0,
                        "status": "PreSubmitted"})
        self.assertEqual(self._tick(held), [])
        trade.refresh_from_db()
        self.assertTrue(trade.metadata["entry_working"])
        dead = _client({"state": "dead", "filled": 0.0, "avgPrice": 0,
                        "status": "Cancelled"})
        self.assertEqual(self._tick(dead), [])
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CANCELED")

    def test_a_partial_fill_is_announced_once(self):
        """Part printed, the rest withdrawn: what printed is the fill."""
        trade = _working_trade(self.cfg)
        client = _client({})
        client.order_status.side_effect = [
            {"state": "working", "filled": 4.0, "avgPrice": 99.5,
             "status": "Submitted"},
            {"state": "filled", "filled": 4.0, "avgPrice": 99.5,
             "status": "Cancelled"},
        ]
        pushed = self._tick(client)
        trade.refresh_from_db()
        self.assertEqual(float(trade.qty), 4.0)
        self.assertEqual(pushed, [{
            "trade_id": trade.id, "asset_class": "stock", "symbol": "NVDA",
            "side": "BUY", "working": False}])

    def test_a_push_that_raises_changes_nothing_on_the_fill(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotConfig

        def book():
            cfg = AssetBotConfig.objects.get(pk=self.cfg.pk)
            trade = _working_trade(cfg)
            client = _client(dict(FILLED_10))
            with patch(ROUTER, return_value=client):
                StockBot(cfg).manage_positions()
            return {"tid": trade.pk, "row": _row(trade.pk),
                    "orders": _orders(client)}

        answered, raised = self._twice(book)
        self._same(answered, raised, ("row", "orders", "writes", "hooks"))
        self.assertNotIn("entry_working", raised["row"]["metadata"])
        self.assertEqual(raised["row"]["entry_price"], Decimal("99.75"))
        for run in (answered, raised):
            self.assertEqual(run["fill_open"], [{
                "trade_id": run["tid"], "asset_class": "stock",
                "symbol": "NVDA", "side": "BUY", "working": False}])

    def test_a_push_that_raises_never_escapes_the_fill(self):
        """Called as the poll calls it: the fill is booked, the hooks after
        the push still run, and nothing is raised to the tick."""
        from bot_program.asset_engine.base import make_bot
        from bot_program.tax_lot_models import TaxLot
        trade = _working_trade(self.cfg)
        client = _client(dict(FILLED_10))
        with patch(PUSH, side_effect=_raising) as pushed, \
                self.assertLogs(self.LOGGER, "WARNING"), \
                self.captureOnCommitCallbacks() as hooks:
            make_bot(self.cfg)._finish_working_entry(
                trade, client, qty=10.0, price=99.75, source="broker",
                venue=dict(FILLED_10))
        self.assertEqual(len(_fill_opens(pushed)), 1)
        trade.refresh_from_db()
        self.assertNotIn("entry_working", trade.metadata)
        self.assertEqual(trade.entry_price, Decimal("99.75"))
        self.assertTrue(TaxLot.objects.filter(source_trade=trade).exists())
        self.assertTrue(hooks, "the Orc's birth is registered after it")


# ── end to end: a held ticket, then its fill ────────────────────────────────

class AHeldTicketThenItsFillTests(TestCase):
    """What the Eye hears for one hand-taken order eToro held: one
    fill_open saying it is held, then one saying it filled."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("fow_e", password="x")

    def setUp(self):
        cache.clear()
        self.inst = _quote("BTCUSD", 60000)
        _components_on()
        self.cfg = _arm_live(self.user)

    def test_held_then_filled(self):
        from bot_program.asset_engine.base import make_bot
        from bot_program.manual_trade import MANUAL_RULE, execute_take_trade
        from bot_program.models import AssetBotTrade
        fake = _fake_live_client(dict(HELD_TICKET))
        with patch(ROUTER, return_value=fake), patch(PUSH) as pushed:
            out = execute_take_trade(self.user, _signal(self.inst),
                                     pin_ok=True)
            self.assertTrue(out.get("working"), out)
            fake.order_status.return_value = {
                "state": "filled", "filled": 0.0004, "avgPrice": 60010.0,
                "status": "Filled"}
            make_bot(self.cfg).manage_positions()
        row = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertEqual(row.rule_name, MANUAL_RULE)
        self.assertNotIn("entry_working", row.metadata)
        self.assertEqual(row.entry_price, Decimal("60010"))
        told = {"trade_id": row.id, "asset_class": "crypto",
                "symbol": "BTCUSD", "side": "BUY"}
        self.assertEqual(_fill_opens(pushed), [dict(told, working=True),
                                               dict(told, working=False)])
