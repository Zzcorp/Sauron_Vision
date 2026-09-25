"""ETORO_PROVEN — the proof gate as the tree ships it (C0, 2026-09-24).

An eToro entry on a class — or a short — whose demo fill-and-close proof is
not pinned as `test_proof_<token>` in tests/test_etoro_client.py is refused
by AssetBot._etoro_entry_refusal in EVERY lane that reaches market_order
(the asset bots' execute_entry, the TAKE TRADE lane and the legacy
BotConfig tick in engine/runner.py), before the venue floor, the
idempotency id, the multiplier and the POST. The set ships EMPTY; a token
joins only in the commit that pins its proof (deploy/ETORO_DEPARTURE.md
§7, bullet 0; §10). Every carrier the adapter map does not call "etoro"
passes the gate at its first line, untouched.

The eToro client here is the REAL EtoroTrader over a fake wire
(tests.test_etoro_client._client): capabilities.adapter_key reads the
class name, so a subclass or a MagicMock would never meet the gate.

Run with:  python manage.py test tests.test_etoro_proofs
"""
import inspect
import re
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase

from tests.test_desk_seam import _client as _mock_client
from tests.test_etoro_client import _client as _etoro_client
from tests.test_etoro_leverage import _book
from tests.test_execution_trust import _cfg as _live_cfg
from tests.test_execution_trust import _instrument, _signal, _user

ROUTER = "bot_program.engine.broker_router.client_for_symbol"
PROVEN = "bot_program.asset_engine.base.ETORO_PROVEN"


def _gate(client, symbol="AAPL", side="BUY", icls="stock", **kw):
    from bot_program.asset_engine.base import AssetBot
    return AssetBot._etoro_entry_refusal(client, symbol, side, 1.0, 100.0,
                                         icls, **kw)


class TheSetShipsEmptyTests(SimpleTestCase):
    """What the tree says on 2026-09-24: no class is proven."""

    def test_no_token_is_in_the_set_at_this_commit(self):
        from bot_program.asset_engine.base import ETORO_PROVEN
        self.assertIsInstance(ETORO_PROVEN, frozenset)
        self.assertEqual(ETORO_PROVEN, frozenset())

    def test_every_token_present_has_its_pinned_proof(self):
        """A token without `def test_proof_<token>` in
        tests/test_etoro_client.py is a claim, not a measurement. Vacuous
        while the set is empty — that is the point: the first token that
        lands without its proof fails here, in the same commit."""
        from bot_program.asset_engine.base import ETORO_PROVEN
        src = (Path(settings.BASE_DIR) / "tests"
               / "test_etoro_client.py").read_text(encoding="utf-8")
        pinned = set(re.findall(r"^\s+def test_proof_([a-z0-9_]+)\(", src,
                                re.M))
        for token in ETORO_PROVEN:
            self.assertIn(token, pinned,
                          f"ETORO_PROVEN names {token!r}; tests/"
                          f"test_etoro_client.py pins no test_proof_{token}")

    def test_no_switch_can_flip_it(self):
        """Not a PlatformComponent on purpose: nothing on /health/ can
        state a proof that was never measured."""
        from core import platform_control
        text = inspect.getsource(platform_control)
        self.assertNotIn("ETORO_PROVEN", text)
        self.assertNotIn("etoro_proven", text)


class TheGateTests(SimpleTestCase):
    """AssetBot._etoro_entry_refusal, step 1, on its own. With a token
    patched in, step 2 (C1) runs on the same real adapter: its wire
    answers no /search here, so the row reads "error" and a 1x stock
    passes with the log line — the cache is cleared around every test."""

    def setUp(self):
        from tests.test_etoro_client import _clear_eligibility
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def test_a_carrier_that_is_not_etoro_answers_nothing_at_the_first_line(self):
        """MagicMock (the desk seam), and a class carrying every OTHER
        adapter name the map knows (Saxo, IBKR, paper, OANDA, Alpaca,
        Binance): ("", "") whatever the class or side."""
        from bot_program.engine.capabilities import ADAPTER_CLASS_KEYS
        self.assertEqual(_gate(_mock_client("100.00")), ("", ""))
        self.assertEqual(_gate(_mock_client("100.00"), side="SELL",
                               icls="commodity"), ("", ""))
        others = [n for n, k in ADAPTER_CLASS_KEYS.items() if k != "etoro"]
        self.assertGreaterEqual(len(others), 7, others)
        for name in others:
            client = type(name, (), {})()
            self.assertEqual(_gate(client, side="SELL", icls="forex"),
                             ("", ""), name)

    def test_an_etoro_carrier_is_refused_naming_the_class_and_touches_no_wire(self):
        from bot_program.asset_engine import skips
        t, fake = _etoro_client([])
        code, why = _gate(t)
        self.assertEqual(code, skips.GATE_BLOCKED)
        self.assertTrue(why.startswith("eToro AAPL (stock, BUY): "), why)
        self.assertIn("no demo fill-and-close proof pinned for ['stock']",
                      why)
        self.assertIn("test_proof_<token>", why)
        self.assertEqual(fake.calls, [], "the gate asked the wire something")

    def test_a_sell_needs_the_short_token_too(self):
        from bot_program.asset_engine import skips
        t, _ = _etoro_client([])
        code, why = _gate(t, side="SELL")
        self.assertEqual(code, skips.GATE_BLOCKED)
        self.assertIn("(stock, SELL)", why)
        self.assertIn("['short', 'stock']", why)
        with mock.patch(PROVEN, frozenset({"stock"})):
            self.assertEqual(_gate(t), ("", ""))
            code, why = _gate(t, side="SELL")
            self.assertEqual(code, skips.GATE_BLOCKED)
            self.assertIn("['short']", why)
        with mock.patch(PROVEN, frozenset({"stock", "short"})):
            self.assertEqual(_gate(t, side="SELL"), ("", ""))

    def test_the_instrument_class_is_the_key_not_the_config_class(self):
        """An ETF in a stock config is gated on "etf": the token the proof
        for GLDM will carry, never the config's "stock"."""
        from bot_program.asset_engine import skips
        t, _ = _etoro_client([])
        with mock.patch(PROVEN, frozenset({"stock"})):
            code, why = _gate(t, symbol="GLDM", icls="etf")
        self.assertEqual(code, skips.GATE_BLOCKED)
        self.assertIn("GLDM (etf, BUY)", why)
        self.assertIn("['etf']", why)

    def test_the_set_is_read_at_call_time(self):
        """A patched module global is what the gate sees — the rule every
        test that pushes a real EtoroTrader through a lane relies on
        (tests/test_etoro_leverage.py _proven)."""
        t, _ = _etoro_client([])
        self.assertNotEqual(_gate(t), ("", ""))
        with mock.patch(PROVEN, frozenset({"stock"})):
            self.assertEqual(_gate(t), ("", ""))
        self.assertNotEqual(_gate(t), ("", ""))

    def test_the_words_fit_the_skip_record_and_start_with_the_verdict(self):
        """skips.record keeps 200 characters; the verdict and both names
        come first so nothing that matters is cut on a long key."""
        t, _ = _etoro_client([])
        _code, why = _gate(t, symbol="RUSSELL2000", side="SELL",
                           icls="commodity")
        self.assertLessEqual(len(why), 200, len(why))
        self.assertTrue(why.startswith("eToro RUSSELL2000 (commodity, SELL)"),
                        why)


class TheInstrumentClassTests(TestCase):
    """_instrument_class: the router's own key (the Instrument row); the
    config's class only when no row exists."""

    def setUp(self):
        self.user = _user("proof_icls")
        self.cfg = _live_cfg(self.user, name="ICLS")

    def _bot(self):
        from bot_program.asset_engine.stock_bot import StockBot
        return StockBot(self.cfg)

    def test_an_index_or_etf_row_under_a_stock_config_answers_its_own_class(self):
        _instrument("AAPL", "stock")
        _instrument("SPX500", "index")
        _instrument("GLDM", "etf")
        bot = self._bot()
        self.assertEqual(bot._instrument_class("AAPL"), "stock")
        self.assertEqual(bot._instrument_class("SPX500"), "index")
        self.assertEqual(bot._instrument_class("GLDM"), "etf")

    def test_no_row_answers_the_configs_class(self):
        from instruments.models import Instrument
        self.assertFalse(Instrument.objects.filter(symbol="NOROW").exists())
        self.assertEqual(self._bot()._instrument_class("NOROW"), "stock")


class TheLeverageHintTests(TestCase):
    """_extras_leverage_hint: the whole number the operator typed (>= 1),
    else None. A hint for the gate's later steps, never a judgement —
    judge_order_leverage still refuses an unreadable value."""

    def test_a_whole_number_at_least_one_is_the_hint_else_none(self):
        from bot_program.asset_engine.stock_bot import StockBot
        cfg = _live_cfg(_user("proof_hint"), name="HINT")
        bot = StockBot(cfg)
        for raw, want in ((2, 2), ("2", 2), (1, 1), (" 5 ", 5), (0, None),
                          (-1, None), (2.5, None), ("x", None),
                          (None, None), (True, None), ("", None)):
            cfg.extras = {"leverage": raw}
            self.assertEqual(bot._extras_leverage_hint(), want, repr(raw))
        cfg.extras = {}
        self.assertIsNone(bot._extras_leverage_hint())
        cfg.extras = None
        self.assertIsNone(bot._extras_leverage_hint())

    def test_the_take_trade_lane_reads_the_hint_with_the_same_rule(self):
        """ONE reading for every lane: the staticmethod the bot helper
        delegates to is what manual_trade calls off cfg.extras, so "0" is
        None on both (isdigit alone would hand the lane a 0)."""
        from bot_program.asset_engine.base import AssetBot
        for raw, want in (("0", None), (0, None), ("3", 3), (3, 3),
                          ("x", None), (None, None)):
            self.assertEqual(AssetBot._leverage_hint_of({"leverage": raw}),
                             want, repr(raw))
        self.assertIsNone(AssetBot._leverage_hint_of(None))
        self.assertIsNone(AssetBot._leverage_hint_of({}))
        manual = (Path(settings.BASE_DIR) / "bot_program"
                  / "manual_trade.py").read_text(encoding="utf-8")
        self.assertEqual(
            manual.count("leverage_hint=AssetBot._leverage_hint_of(cfg.extras)"),
            1)


class TheEntryLaneTests(TestCase):
    """execute_entry on a LIVE stock config: the candidate is priced through
    the desk-seam MagicMock (propose); the order would go through the REAL
    EtoroTrader over a fake wire (execute) — and with the shipped set it
    never does. Mirrors tests/test_etoro_leverage.py's entry class, without
    a leverage key and without its _proven("stock")."""

    def setUp(self):
        self.user = _user("proof_entry")
        self.cfg = _live_cfg(self.user, name="PROOF")
        self.cfg.base_currency = "USD"
        self.cfg.save(update_fields=["base_currency"])
        _signal(_instrument(), rule="proof_rule")
        _book(self.user)

    def _cand(self):
        from bot_program.asset_engine.stock_bot import StockBot
        self.bot = StockBot(self.cfg)
        with mock.patch(ROUTER, return_value=_mock_client("100.00")):
            cand = self.bot.propose_entry("AAPL")
        self.assertIsNotNone(cand)
        self.assertGreater(cand.qty_default, 0)
        return cand

    def _skip_note(self):
        from bot_program.asset_engine import skips
        self.cfg.refresh_from_db()
        return skips.last_by_symbol(self.cfg)["AAPL"]

    def _execute(self, cand, client):
        with mock.patch(ROUTER, return_value=client), \
                mock.patch("time.sleep"), \
                mock.patch("bot_program.asset_engine.base.AssetBot"
                           "._notify_venue_min_size") as floor_note:
            res = self.bot.execute_entry(cand)
        return res, floor_note

    def _declare_a_floor(self):
        """EtoroTrader declares no size_floor, so on its own the floor
        answers (None, ...) and _notify_venue_min_size is unreachable —
        a pin on it would pass with the gate placed AFTER the floor.
        Declaring extras['venue_min_notional'] far above the order makes
        the floor reachable (operator-declared, 1e7 units at 100), so the
        floor pins bite: a late gate would record venue_min_size."""
        self.cfg.extras = {"venue_min_notional": 1e9}
        self.cfg.save(update_fields=["extras"])

    def test_an_etoro_carried_stock_buy_is_gate_blocked_before_the_floor(self):
        from bot_program.asset_engine import skips
        from bot_program.models import AssetBotTrade
        self._declare_a_floor()
        cand = self._cand()
        t, fake = _etoro_client([])
        res, floor_note = self._execute(cand, t)
        self.assertIsNone(res)
        self.assertEqual(fake.calls, [], "the wire was asked something")
        floor_note.assert_not_called()
        self.assertEqual(AssetBotTrade.objects.count(), 0)
        note = self._skip_note()
        self.assertEqual(note["code"], skips.GATE_BLOCKED)
        self.assertTrue(note["detail"].startswith("eToro AAPL (stock, BUY): "),
                        note)
        self.assertIn("['stock']", note["detail"])
        self.assertIn("ETORO_DEPARTURE §7", note["detail"])

    def test_an_etoro_carried_sell_names_short_as_well(self):
        """The candidate's direction is flipped by hand: propose votes off
        a bullish signal, and nothing between propose and the gate reads
        the direction — the gate does."""
        from bot_program.asset_engine import skips
        self._declare_a_floor()
        cand = self._cand()
        cand.decision.direction = "SELL"
        t, fake = _etoro_client([])
        res, floor_note = self._execute(cand, t)
        self.assertIsNone(res)
        self.assertEqual(fake.calls, [])
        floor_note.assert_not_called()
        note = self._skip_note()
        self.assertEqual(note["code"], skips.GATE_BLOCKED)
        self.assertIn("(stock, SELL)", note["detail"])
        self.assertIn("['short', 'stock']", note["detail"])

    def test_a_carrier_that_is_not_etoro_passes_the_gate_untouched(self):
        """The desk-seam MagicMock carries extras['leverage']=2 here so the
        refusal that DOES fire is the multiplier's — a judgement that sits
        AFTER the gate — which is how this proves the gate let it through.
        Nothing is sent either way."""
        from bot_program.asset_engine import skips
        self.cfg.extras = {"leverage": 2}
        self.cfg.save(update_fields=["extras"])
        cand = self._cand()
        other = _mock_client("100.00")
        res, _floor_note = self._execute(cand, other)
        self.assertIsNone(res)
        other.market_order.assert_not_called()
        self.assertEqual(self._skip_note()["code"], skips.LEVERAGE_REFUSED)

    def test_the_gate_sits_before_the_floor_the_id_and_the_multiplier(self):
        """Source order in execute_entry, measured: the ONE call to
        _etoro_entry_refusal precedes _venue_size_floor,
        make_client_order_id and _order_leverage; the TAKE TRADE lane calls
        the same classmethod once, before its own leverage judgement; the
        legacy tick calls it once, before its market_order."""
        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.execute_entry)
        self.assertEqual(src.count("_etoro_entry_refusal("), 1)
        order = [src.index(n) for n in ("_etoro_entry_refusal(",
                                        "_venue_size_floor(",
                                        "make_client_order_id(",
                                        "_order_leverage(")]
        self.assertEqual(order, sorted(order), order)
        manual = (Path(settings.BASE_DIR) / "bot_program"
                  / "manual_trade.py").read_text(encoding="utf-8")
        self.assertEqual(manual.count("AssetBot._etoro_entry_refusal("), 1)
        self.assertLess(
            manual.index("AssetBot._etoro_entry_refusal("),
            manual.index("judge_order_leverage(cfg, cls, adapter_key(client))"))
        legacy = (Path(settings.BASE_DIR) / "bot_program" / "engine"
                  / "runner.py").read_text(encoding="utf-8")
        self.assertEqual(legacy.count("AssetBot._etoro_entry_refusal("), 1)
        self.assertLess(
            legacy.index("AssetBot._etoro_entry_refusal("),
            legacy.index("sym_client.market_order(symbol, d.direction, qty)"))


class TheLegacyTickMeetsTheGateTests(TestCase):
    """engine/runner.run_bot_tick — the legacy BotConfig loop — reaches the
    same clients through the same client_for_symbol and sends at its own
    market_order with no floor and no stop attached (a third path the C0
    review found). Since 2026-09-24 it meets the same gate: an eToro-carried
    symbol of an unproven class sends nothing from here either; a carrier
    the adapter map does not call "etoro" is untouched (the existing
    behaviour, pinned). The strategy is patched to vote BUY so the loop
    reaches the send; the Phase-2 risk gate is patched to pass the size."""

    def setUp(self):
        from bot_program.models import BotConfig
        self.user = _user("proof_legacy")
        self.cfg = BotConfig.objects.create(
            user=self.user, enabled=True, mode="live", symbols=["AAPL"],
            capital_usdt=Decimal("1000"))
        _instrument("AAPL", "stock")

    def _tick(self, client, direction="BUY"):
        from bot_program.engine import runner
        from bot_program.engine.strategy import Decision
        d = Decision(symbol="AAPL", score=0.9, confidence=0.9,
                     direction=direction, reasons=["t"], sl_pct=1.5,
                     tp_pct=3.0)
        with mock.patch.object(runner, "client_for_symbol",
                               return_value=client), \
                mock.patch.object(runner, "broker_name_for_symbol",
                                  return_value="etoro"), \
                mock.patch.object(runner, "decide", return_value=d), \
                mock.patch.object(runner, "_apply_risk_gate",
                                  side_effect=lambda u, s, q, p: (q, "ok")):
            runner.run_bot_tick(self.user.id)

    _BARS = [[0, "100", "101", "99", "100", "1"]] * 60

    def _etoro(self):
        """The real adapter over a fake wire that answers nothing; the
        scan it is asked for (klines, order_book) is patched on the
        instance so the only thing that could touch the wire is an order."""
        t, fake = _etoro_client([])
        for name, value in (("klines", self._BARS),
                            ("order_book", {"bids": [], "asks": []})):
            p = mock.patch.object(t, name, return_value=value)
            p.start()
            self.addCleanup(p.stop)
        return t, fake

    def test_an_etoro_carried_unproven_class_sends_nothing_and_books_no_row(self):
        from bot_program.models import BotTrade
        t, fake = self._etoro()
        with mock.patch.object(t, "market_order", wraps=t.market_order) as spy, \
                self.assertLogs("bot_program.engine.runner",
                                level="ERROR") as cm:
            self._tick(t)
        spy.assert_not_called()
        self.assertEqual(fake.calls, [], "the wire was asked something")
        self.assertEqual(BotTrade.objects.count(), 0)
        line = [ln for ln in cm.output if "gate_blocked" in ln]
        self.assertEqual(len(line), 1, cm.output)
        self.assertIn("eToro AAPL (stock, BUY)", line[0])
        self.assertIn("['stock']", line[0])
        self.assertIn("nothing was sent", line[0])

    def test_a_sell_names_short_too(self):
        from bot_program.models import BotTrade
        t, fake = self._etoro()
        with mock.patch(PROVEN, frozenset({"stock"})), \
                mock.patch.object(t, "market_order", wraps=t.market_order) as spy, \
                self.assertLogs("bot_program.engine.runner",
                                level="ERROR") as cm:
            self._tick(t, direction="SELL")
        spy.assert_not_called()
        self.assertEqual(fake.calls, [])
        self.assertEqual(BotTrade.objects.count(), 0)
        self.assertTrue(any("(stock, SELL)" in ln and "['short']" in ln
                            for ln in cm.output), cm.output)

    def test_a_carrier_that_is_not_etoro_is_untouched(self):
        """The existing behaviour, pinned: the loop sends through a carrier
        the adapter map does not know and books the row off its answer."""
        from bot_program.models import BotTrade
        client = mock.MagicMock()
        client.klines.return_value = self._BARS
        client.order_book.return_value = {}
        client.market_order.return_value = {"orderId": "o1"}
        self._tick(client)
        client.market_order.assert_called_once()
        self.assertEqual(client.market_order.call_args.args[:2],
                         ("AAPL", "BUY"))
        row = BotTrade.objects.get()
        self.assertEqual((row.symbol, row.side, row.paper,
                          row.binance_order_id, row.status),
                         ("AAPL", "BUY", False, "o1", "OPEN"))
