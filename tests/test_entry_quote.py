"""THE ENTRY QUOTE and THE SLIPPAGE BUDGET (2026-10-05, the operator asked
for more resilience and smartness in taking positions).

  1. The quote an entry is sized, stopped and ordered on is JUDGED before
     anything reads it (mark_sanity.entry_quote): crossed, a last print
     outside the live bid/ask, far from the platform's own quote, or frozen
     for FROZEN_MINUTES in an open market is a skip (SUSPECT_MARK), never
     an entry. The TAKE TRADE ticket warns on the same read.
  2. THE LAST LOOK before every live order (AssetBot._last_look): one fresh
     read of the venue's quote — the drift since the proposal (the trade
     debate's rule, every order's now), the quote's sanity, and the
     slippage budget (a half-spread past ENTRY_SLIPPAGE_MAX_R of the stop
     distance is WIDE_SPREAD: the sized risk would be understated).
  3. THE FILL AGAINST THE QUOTE (AssetBot.reanchor_stop_to_fill): the slip
     is recorded on every real fill; an ADVERSE one moves eToro's stop by
     the slip — tighter only, one PATCH — so the risk held is the risk
     sized; past ENTRY_SLIPPAGE_ALERT_R the staff are told. The fill
     message says it (slippage_words).

Run with:  python manage.py test tests.test_entry_quote
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from bot_program import mark_sanity as ms
from tests.test_desk_seam import _client as _mock_client
from tests.test_etoro_client import (SEARCH_AAPL, _clear_eligibility, _client,
                                     _lookup)
from tests.test_etoro_leverage import (POSTED, RATES, _account, _book, _etoro,
                                       _order_posts)
from tests.test_execution_trust import _cfg as _live_cfg
from tests.test_execution_trust import _instrument, _signal, _user

ROUTER = "bot_program.engine.broker_router.client_for_symbol"


def _tick(last, bid=None, ask=None):
    t = {"lastPrice": str(last), "symbol": "BTCUSD"}
    if bid is not None:
        t["bid"] = str(bid)
    if ask is not None:
        t["ask"] = str(ask)
    return t


# ── 1. the pure read ──────────────────────────────────────────────────────

class TheEntryQuoteTests(SimpleTestCase):

    def test_the_constants(self):
        self.assertEqual(ms.ENTRY_SLIPPAGE_MAX_R, 0.15)
        self.assertEqual(ms.ENTRY_SLIPPAGE_ALERT_R, 0.25)
        self.assertEqual(ms.ENTRY_MARKS_MAX, 200)

    def test_an_ordinary_quote_is_ok_and_carries_its_numbers(self):
        v = ms.entry_quote(_tick(100, 99.9, 100.1), "crypto", "BTCUSD",
                           stop=98.0)
        self.assertTrue(v["ok"])
        self.assertEqual((v["bid"], v["ask"], v["last_price"], v["mid"]),
                         (99.9, 100.1, 100.0, 100.0))
        self.assertAlmostEqual(v["spread"], 0.002, places=6)
        self.assertAlmostEqual(v["half_spread"], 0.1, places=6)
        self.assertAlmostEqual(v["half_spread_r"], 0.05, places=6)
        self.assertEqual(v["mark"]["mid"], 100.0)
        self.assertEqual(ms.slippage_budget_words(v), "")

    def test_a_crossed_quote_is_refused(self):
        v = ms.entry_quote(_tick(100, 100.2, 99.8), "crypto", "BTCUSD")
        self.assertFalse(v["ok"])
        self.assertEqual(v["why"], "crossed quote: bid 100.2 over ask 99.8")

    def test_a_last_print_outside_the_quote_is_a_stale_print(self):
        v = ms.entry_quote(_tick(101, 99.9, 100.1), "crypto", "BTCUSD")
        self.assertFalse(v["ok"])
        self.assertIn("sits outside the quote (bid 99.9 / ask 100.1)", v["why"])
        self.assertIn("a stale print", v["why"])
        # a tick outside is the venue's rounding, not a stale print
        self.assertTrue(ms.entry_quote(_tick(100.11, 99.9, 100.1), "crypto",
                                       "BTCUSD")["ok"])
        # forex: five decimals
        self.assertTrue(ms.entry_quote(_tick(1.10011, 1.10000, 1.10010),
                                       "forex", "EURUSD")["ok"])
        self.assertFalse(ms.entry_quote(_tick(1.1004, 1.10000, 1.10010),
                                        "forex", "EURUSD")["ok"])

    def test_a_venue_quote_far_from_the_platforms_is_refused(self):
        v = ms.entry_quote(_tick(100, 99.9, 100.1), "crypto", "BTCUSD",
                           reference=104.0)
        self.assertFalse(v["ok"])
        self.assertIn("3.8% from the platform's 104 (bar 3.0%)", v["why"])
        self.assertTrue(ms.entry_quote(_tick(100, 99.9, 100.1), "crypto",
                                       "BTCUSD", reference=102.0)["ok"])
        # no opinion refuses nothing; no bid/ask still reads the reference
        self.assertTrue(ms.entry_quote(_tick(100), "crypto", "BTCUSD")["ok"])
        self.assertFalse(ms.entry_quote(_tick(100), "crypto", "BTCUSD",
                                        reference=104.0)["ok"])

    def test_a_frozen_quote_in_an_open_market_is_refused_and_not_in_a_shut_one(self):
        now = timezone.now()
        since = (now - timedelta(minutes=50)).isoformat()
        last = {"mid": 100.0, "at": since, "same_since": since}
        v = ms.entry_quote(_tick(100, 99.9, 100.1), "crypto", "BTCUSD",
                           last=last, now=now, market_open=True)
        self.assertFalse(v["ok"])
        self.assertIn("frozen quote: 100 unchanged for 50 minutes", v["why"])
        self.assertEqual(v["mark"]["same_since"], since, "the clock keeps")
        v2 = ms.entry_quote(_tick(100, 99.9, 100.1), "crypto", "BTCUSD",
                            last=last, now=now, market_open=False)
        self.assertTrue(v2["ok"])
        # a different mid resets the clock
        v3 = ms.entry_quote(_tick(100.5, 100.4, 100.6), "crypto", "BTCUSD",
                            last=last, now=now)
        self.assertTrue(v3["ok"])
        self.assertEqual(v3["mark"]["same_since"], now.isoformat())
        # under FROZEN_MINUTES: still ok
        young = {"mid": 100.0, "at": (now - timedelta(minutes=10)).isoformat(),
                 "same_since": (now - timedelta(minutes=10)).isoformat()}
        self.assertTrue(ms.entry_quote(_tick(100, 99.9, 100.1), "crypto",
                                       "BTCUSD", last=young, now=now)["ok"])

    def test_options_and_no_price_are_never_judged(self):
        self.assertTrue(ms.entry_quote(_tick(5, 6, 4), "options", "AAPL")["ok"])
        v = ms.entry_quote(_tick(0), "crypto", "BTCUSD", reference=50.0)
        self.assertTrue(v["ok"])
        self.assertIsNone(v["mark"])
        self.assertTrue(ms.entry_quote("not a tick", "crypto", "BTCUSD")["ok"])

    def test_the_budget_words(self):
        v = ms.entry_quote(_tick(100, 99, 101), "crypto", "BTCUSD", stop=98.0)
        self.assertTrue(v["ok"], "a wide quote is not a suspect one")
        self.assertAlmostEqual(v["half_spread_r"], 0.5)
        words = ms.slippage_budget_words(v)
        self.assertEqual(words, "the quoted half-spread 1 is 50% of the stop "
                                "distance (max 15%) — the sized risk would be "
                                "understated; nothing sent")
        self.assertEqual(ms.slippage_budget_words({}), "")
        self.assertEqual(ms.slippage_budget_words({"half_spread_r": 0.15}), "")


# ── the engine's reads ────────────────────────────────────────────────────

class TheProposalGateTests(TestCase):
    """propose_entry on a LIVE stock config priced through a client that
    answers bid/ask: the quote is judged right after the no-price gate,
    before the cost, the levels and the size."""

    def setUp(self):
        self.user = _user("eq_prop")
        self.cfg = _live_cfg(self.user, name="EQ")
        _signal(_instrument(), rule="eq_rule")
        _book(self.user)

    def _propose(self, tick):
        from bot_program.asset_engine.stock_bot import StockBot
        self.bot = StockBot(self.cfg)
        client = _mock_client("100.00")
        client.ticker.return_value = tick
        with mock.patch(ROUTER, return_value=client):
            return self.bot.propose_entry("AAPL")

    def _skip_note(self):
        from bot_program.asset_engine import skips
        self.cfg.refresh_from_db()
        return skips.last_by_symbol(self.cfg)["AAPL"]

    def test_a_crossed_quote_is_refused_before_the_levels_and_the_size(self):
        from bot_program.asset_engine import skips
        with mock.patch("bot_program.asset_engine.risk_levels.stop_and_target"
                        ) as levels, \
                self.assertLogs("bot_program.asset_engine.base",
                                level="WARNING") as logs:
            cand = self._propose({"lastPrice": "100.00", "bid": "100.2",
                                  "ask": "99.8"})
        self.assertIsNone(cand)
        levels.assert_not_called()
        note = self._skip_note()
        self.assertEqual(note["code"], skips.SUSPECT_MARK)
        self.assertIn("crossed quote", note["detail"])
        self.assertTrue(any("entry refused on the quote" in m
                            for m in logs.output))

    def test_an_ordinary_quote_passes_and_the_mark_is_remembered(self):
        cand = self._propose({"lastPrice": "100.00", "bid": "99.9",
                              "ask": "100.1"})
        self.assertIsNotNone(cand)
        self.cfg.refresh_from_db()
        mark = self.cfg.extras["entry_marks"]["AAPL"]
        self.assertEqual(mark["mid"], 100.0)
        self.assertIn("same_since", mark)

    def test_a_quote_frozen_across_ticks_is_refused_in_an_open_market(self):
        from bot_program.asset_engine import skips
        since = (timezone.now() - timedelta(minutes=50)).isoformat()
        self.cfg.extras = {"entry_marks": {"AAPL": {
            "mid": 100.0, "at": since, "same_since": since}}}
        self.cfg.save(update_fields=["extras"])
        with mock.patch("bot_program.engine.paper_trader.paper_market_shut",
                        return_value=""):
            cand = self._propose({"lastPrice": "100.00", "bid": "99.9",
                                  "ask": "100.1"})
        self.assertIsNone(cand)
        self.assertEqual(self._skip_note()["code"], skips.SUSPECT_MARK)
        self.assertIn("frozen quote", self._skip_note()["detail"])
        # the same quote in a shut market is the clock, not the feed
        with mock.patch("bot_program.engine.paper_trader.paper_market_shut",
                        return_value="the market is shut"):
            self.assertIsNotNone(self._propose(
                {"lastPrice": "100.00", "bid": "99.9", "ask": "100.1"}))

    def test_a_read_that_fails_lets_the_entry_run(self):
        with mock.patch("bot_program.mark_sanity.entry_quote",
                        side_effect=RuntimeError("boom")):
            self.assertIsNotNone(self._propose(
                {"lastPrice": "100.00", "bid": "100.2", "ask": "99.8"}))


class TheLastLookTests(TestCase):
    """execute_entry on a LIVE stock config carried by the REAL EtoroTrader
    over a fake wire (tests.test_etoro_leverage's fixture, no leverage
    key): the fresh rates read before the POST refuse the drift, a
    suspect quote and a wide spread — and nothing is POSTed."""

    def setUp(self):
        self.user = _user("eq_look")
        self.cfg = _live_cfg(self.user, name="LOOK")
        self.cfg.base_currency = "USD"
        self.cfg.extras = {}
        self.cfg.save(update_fields=["base_currency", "extras"])
        _signal(_instrument(), rule="look_rule")
        _book(self.user)
        _account(self.user, cash=100000)
        p = mock.patch("bot_program.asset_engine.base.ETORO_PROVEN",
                       frozenset({"stock"}))
        p.start()
        self.addCleanup(p.stop)
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def _cand(self):
        from bot_program.asset_engine.stock_bot import StockBot
        self.bot = StockBot(self.cfg)
        with mock.patch(ROUTER, return_value=_mock_client("100.00")):
            cand = self.bot.propose_entry("AAPL")
        self.assertIsNotNone(cand)
        return cand

    def _execute(self, cand, t):
        with mock.patch(ROUTER, return_value=t), mock.patch("time.sleep"):
            return self.bot.execute_entry(cand)

    def _skip_note(self):
        from bot_program.asset_engine import skips
        self.cfg.refresh_from_db()
        return skips.last_by_symbol(self.cfg)["AAPL"]

    @staticmethod
    def _rates(last, bid, ask):
        return ("GET", "/rates", 200, {"rates": [
            {"bid": bid, "ask": ask, "lastExecution": last}]})

    def test_the_drift_since_the_proposal_refuses_without_the_debate(self):
        from bot_program.asset_engine import skips
        cand = self._cand()
        dist = float(cand.price) - float(cand.stop)
        fresh = round(float(cand.price) - 0.6 * dist, 2)
        t, fake = _etoro([SEARCH_AAPL, self._rates(fresh, fresh - 0.1,
                                                   fresh + 0.1), POSTED])
        self.assertIsNone(self._execute(cand, t))
        self.assertEqual(_order_posts(fake), [])
        note = self._skip_note()
        self.assertEqual(note["code"], skips.GATE_BLOCKED)
        self.assertIn("of the way to the stop since the proposal (", note["detail"])
        self.assertIn("s ago)", note["detail"])

    def test_a_crossed_fresh_quote_is_suspect_at_the_send(self):
        from bot_program.asset_engine import skips
        cand = self._cand()
        t, fake = _etoro([SEARCH_AAPL, self._rates(100.0, 100.2, 99.8), POSTED])
        self.assertIsNone(self._execute(cand, t))
        self.assertEqual(_order_posts(fake), [])
        note = self._skip_note()
        self.assertEqual(note["code"], skips.SUSPECT_MARK)
        self.assertTrue(note["detail"].startswith("at the send: crossed quote"),
                        note)

    def test_a_wide_spread_against_the_stop_is_refused_with_both_numbers(self):
        from bot_program.asset_engine import skips
        cand = self._cand()
        dist = float(cand.price) - float(cand.stop)
        half = round(0.5 * dist, 4)
        t, fake = _etoro([SEARCH_AAPL, self._rates(100.0, 100.0 - half,
                                                   100.0 + half), POSTED])
        self.assertIsNone(self._execute(cand, t))
        self.assertEqual(_order_posts(fake), [])
        note = self._skip_note()
        self.assertEqual(note["code"], skips.WIDE_SPREAD)
        self.assertIn("50% of the stop distance (max 15%)", note["detail"])
        self.assertIn("nothing sent", note["detail"])

    def test_an_ordinary_fresh_quote_sends_and_records_the_read(self):
        from bot_program.models import AssetBotTrade
        cand = self._cand()
        t, fake = _etoro()
        res = self._execute(cand, t)
        self.assertIsNotNone(res)
        self.assertEqual(len(_order_posts(fake)), 1)
        trade = AssetBotTrade.objects.get(id=res["trade_id"])
        q = trade.metadata["entry_quote"]
        self.assertEqual((q["bid"], q["ask"], q["mid"]), (99.9, 100.1, 100.0))
        self.assertEqual(q["proposal_price"], float(cand.price))
        self.assertGreaterEqual(q["age_s"], 0)
        self.assertAlmostEqual(q["half_spread_r"],
                               0.1 / (float(cand.price) - float(cand.stop)),
                               places=5)

    def test_an_unreadable_fresh_quote_refuses_nothing(self):
        cand = self._cand()
        t, fake = _etoro([SEARCH_AAPL, ("GET", "/rates", 500, {}), POSTED])
        with mock.patch.object(type(t), "ticker", side_effect=RuntimeError("x")):
            res = self._execute(cand, t)
        self.assertIsNotNone(res, "the order goes on the proposal's price")
        self.assertEqual(len(_order_posts(fake)), 1)

    def test_the_drift_words(self):
        from unittest.mock import MagicMock
        from bot_program.asset_engine.stock_bot import StockBot
        bot = StockBot(self.cfg)
        client = MagicMock()
        why = bot._drift_since_proposal(client, "AAPL", "BUY", 100.0, 99.0,
                                        102.0, tick={"lastPrice": "99.4"},
                                        age_s=12.6)
        self.assertEqual(why, "the price moved 60% of the way to the stop "
                              "since the proposal (12 s ago) (100 -> 99.4) — "
                              "nothing sent")
        client.ticker.assert_not_called()
        self.assertEqual(bot._drift_since_proposal(
            client, "AAPL", "BUY", 100.0, 99.0, 102.0,
            tick={"lastPrice": "100.2"}), "")


class TheReanchorTests(SimpleTestCase):
    """reanchor_stop_to_fill on the real adapter over a fake wire: BUY
    sized on 100 with the stop at 98 (a 2.0 distance)."""

    FILL = {"protectiveTradeId": "555", "positionId": "555"}

    def _re(self, fill, *, side="BUY", stop=98.0, proposal=100.0,
            patch=("PATCH", "positions/555", 200, {}), **kw):
        t, fake = _client([SEARCH_AAPL] + ([patch] if patch else []))
        out = t.__class__.__name__ and __import__(
            "bot_program.asset_engine.base", fromlist=["AssetBot"]
        ).AssetBot.reanchor_stop_to_fill(
            t, self.FILL, side=side, proposal=proposal, fill=fill, stop=stop,
            asset_class="stock", symbol="AAPL", **kw)
        patches = [c for c in fake.calls if c[0] == "PATCH"]
        return out, patches

    def test_an_adverse_fill_moves_the_stop_by_the_slip_once(self):
        out, patches = self._re(100.5)
        self.assertEqual(out["slippage"], {"proposal": 100.0, "fill": 100.5,
                                           "points": 0.5, "r_fraction": 0.25})
        self.assertTrue(out["sent"])
        self.assertTrue(out["ok"])
        self.assertEqual(out["new_stop"], 98.5)
        self.assertEqual(len(patches), 1)
        self.assertIn("positions/555", patches[0][1])
        self.assertEqual(patches[0][2]["json"], {"stopLossRate": 98.5})
        self.assertFalse(out["alert"], "0.25 is the line, not past it")
        out2, _ = self._re(100.6)
        self.assertTrue(out2["alert"])
        # a SELL: sized on 100, stop 102, filled 99.5 -> stop 101.5
        out3, patches3 = self._re(99.5, side="SELL", stop=102.0)
        self.assertEqual(out3["new_stop"], 101.5)
        self.assertEqual(patches3[0][2]["json"], {"stopLossRate": 101.5})

    def test_a_favourable_fill_moves_nothing_and_is_still_recorded(self):
        out, patches = self._re(99.5)
        self.assertEqual(out["slippage"]["r_fraction"], -0.25)
        self.assertFalse(out["sent"])
        self.assertEqual(patches, [])

    def test_the_venue_refusal_is_recorded_never_retried(self):
        out, patches = self._re(100.5, patch=("PATCH", "positions/555", 400,
                                              {"m": "no"}))
        self.assertTrue(out["sent"])
        self.assertFalse(out["ok"])
        self.assertIn("eToro refused (400)", out["reason"])
        self.assertEqual(len(patches), 1)

    def test_nothing_is_sent_where_it_must_not_be(self):
        # the venue already holds a tighter stop
        out, patches = self._re(100.5, held=98.7)
        self.assertFalse(out["sent"])
        self.assertIn("already holds a tighter stop (98.7)", out["reason"])
        self.assertEqual(patches, [])
        # the venue holds a wider one: re-anchor past it
        out, patches = self._re(100.5, held=97.0)
        self.assertTrue(out["ok"])
        # a working order
        out, patches = self._re(100.5, working=True)
        self.assertFalse(out["sent"])
        self.assertEqual(patches, [])
        # under a tick
        out, patches = self._re(100.004)
        self.assertFalse(out["sent"])
        self.assertIn("under a tick", out["reason"])
        # a slip larger than the stop distance still lands the stop one
        # distance under the fill, by construction
        out, patches = self._re(102.5)
        self.assertTrue(out["ok"])
        self.assertEqual(out["new_stop"], 100.5)
        # no handle on the fill
        from bot_program.asset_engine.base import AssetBot
        t, fake = _client([SEARCH_AAPL])
        out = AssetBot.reanchor_stop_to_fill(t, {}, side="BUY", proposal=100.0,
                                             fill=100.5, stop=98.0)
        self.assertFalse(out["sent"])
        self.assertIn("no position handle", out["reason"])
        # another carrier
        other = mock.MagicMock()
        out = AssetBot.reanchor_stop_to_fill(other, self.FILL, side="BUY",
                                             proposal=100.0, fill=100.5,
                                             stop=98.0)
        self.assertFalse(out["sent"])
        other.modify_protective.assert_not_called()
        self.assertIn("only eToro", out["reason"])
        # bad numbers
        self.assertIsNone(AssetBot.reanchor_stop_to_fill(
            other, self.FILL, side="BUY", proposal="x", fill=1, stop=1)["slippage"])


class TheFillBooksItTests(TestCase):
    """The whole lane: a FILLED answer above the proposal on a BUY — the
    row's stop and initial_stop_loss carry the re-anchored stop, the slip
    is on the row, the fill message names it; a favourable fill leaves the
    stop; a refused PATCH is recorded."""

    def setUp(self):
        self.user = _user("eq_fill")
        self.cfg = _live_cfg(self.user, name="FILL")
        self.cfg.base_currency = "USD"
        self.cfg.extras = {}
        self.cfg.save(update_fields=["base_currency", "extras"])
        _signal(_instrument(), rule="fill_rule")
        _book(self.user)
        _account(self.user, cash=100000)
        p = mock.patch("bot_program.asset_engine.base.ETORO_PROVEN",
                       frozenset({"stock"}))
        p.start()
        self.addCleanup(p.stop)
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def _cand(self):
        from bot_program.asset_engine.stock_bot import StockBot
        self.bot = StockBot(self.cfg)
        with mock.patch(ROUTER, return_value=_mock_client("100.00")):
            cand = self.bot.propose_entry("AAPL")
        self.assertIsNotNone(cand)
        return cand

    def _wire(self, avg, patch_status=200):
        lk = _lookup(3, units=3.0, avg=avg)
        ex = lk["positionExecutions"][0]
        ex.pop("stopLossRate", None)
        ex.pop("takeProfitRate", None)
        return _etoro([SEARCH_AAPL, RATES, POSTED,
                       ("GET", "orders:lookup", 200, lk),
                       ("PATCH", "positions/555", patch_status, {"m": "x"})])

    def _execute(self, cand, t):
        with mock.patch(ROUTER, return_value=t), mock.patch("time.sleep"):
            return self.bot.execute_entry(cand)

    def test_an_adverse_fill_reanchors_the_stop_and_says_so(self):
        from bot_program.models import AssetBotTrade
        cand = self._cand()
        sent_stop = float(cand.stop)
        t, fake = self._wire(100.5)
        res = self._execute(cand, t)
        self.assertIsNotNone(res)
        patches = [c for c in fake.calls if c[0] == "PATCH"]
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0][2]["json"], {"stopLossRate": round(sent_stop + 0.5, 2)})
        trade = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertEqual(float(trade.entry_price), 100.5)
        self.assertEqual(float(trade.stop_loss), round(sent_stop + 0.5, 2))
        self.assertEqual(trade.metadata["initial_stop_loss"],
                         round(sent_stop + 0.5, 2))
        self.assertEqual(trade.metadata["stop_reanchored_to_fill"]["sent"],
                         sent_stop)
        slip = trade.metadata["slippage"]
        self.assertEqual((slip["proposal"], slip["fill"]), (100.0, 100.5))
        self.assertAlmostEqual(slip["r_fraction"], 0.5 / (100.0 - sent_stop),
                               places=5)
        words = self.bot._fill_words(trade)["slippage"]
        self.assertTrue(words.startswith("Filled 100.50, sized on 100.00 — "),
                        words)
        self.assertIn("of a stop distance against; stop re-anchored to", words)

    def test_a_favourable_fill_keeps_the_sent_stop(self):
        from bot_program.models import AssetBotTrade
        cand = self._cand()
        sent_stop = float(cand.stop)
        t, fake = self._wire(99.5)
        res = self._execute(cand, t)
        self.assertEqual([c for c in fake.calls if c[0] == "PATCH"], [])
        trade = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertEqual(float(trade.stop_loss), sent_stop)
        self.assertEqual(trade.metadata["initial_stop_loss"], sent_stop)
        self.assertNotIn("stop_reanchored_to_fill", trade.metadata)
        self.assertLess(trade.metadata["slippage"]["r_fraction"], 0)
        self.assertIn("in favour", self.bot._fill_words(trade)["slippage"])

    def test_a_refused_patch_is_recorded_and_the_staff_hear_a_big_slip(self):
        from bot_program.models import AssetBotTrade
        cand = self._cand()
        sent_stop = float(cand.stop)
        dist = 100.0 - sent_stop
        t, fake = self._wire(round(100.0 + 0.4 * dist, 2), patch_status=400)
        with mock.patch("bot_program.notifications.notify_staff") as told:
            res = self._execute(cand, t)
        trade = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertEqual(float(trade.stop_loss), sent_stop)
        self.assertIn("eToro refused (400)", trade.metadata["stop_reanchor_refused"])
        self.assertTrue(any("of a stop distance past the quote"
                            in c.kwargs["title"] for c in told.call_args_list))
        body = [c.kwargs["body"] for c in told.call_args_list
                if "stop distance past" in c.kwargs["title"]][0]
        self.assertIn("The stop stays at", body)
        self.assertNotIn("$", body)
        self.assertIn("the stop stays:", self.bot._fill_words(trade)["slippage"])


class TheWordsTests(SimpleTestCase):

    def test_slippage_words(self):
        from bot_program.asset_engine.base import slippage_words
        self.assertEqual(slippage_words({}), "")
        self.assertEqual(slippage_words({"slippage": {"proposal": 100, "fill": 100.005,
                                                      "r_fraction": 0.0025}}), "")
        meta = {"slippage": {"proposal": 100.0, "fill": 100.5, "points": 0.5,
                             "r_fraction": 0.25},
                "stop_reanchored_to_fill": {"sent": 98.0, "held": 98.5}}
        self.assertEqual(slippage_words(meta, "stock", "AAPL"),
                         "Filled 100.50, sized on 100.00 — 25% of a stop "
                         "distance against; stop re-anchored to 98.50")
        self.assertEqual(slippage_words({"slippage": {"proposal": 100.0,
                                                      "fill": 99.5,
                                                      "r_fraction": -0.25}},
                                        "stock", "AAPL"),
                         "Filled 99.50, sized on 100.00 — 25% of a stop "
                         "distance in favour")

    def test_the_fill_message_carries_the_line(self):
        from bot_program.notifications import fill_open_message
        msg = fill_open_message(asset_class="stock", symbol="AAPL", side="BUY",
                                qty=3, entry_price=100.5, rule_name="r",
                                slippage="Filled 100.50, sized on 100.00 — "
                                         "25% of a stop distance against")
        self.assertIn("Filled 100.50, sized on 100.00 — 25% of a stop "
                      "distance against", msg["lines"])

    def test_the_skip_codes_have_their_words(self):
        import inspect
        from bot_program import telegram_eye as eye
        from bot_program.asset_engine import skips
        self.assertEqual(skips.WIDE_SPREAD, "wide_spread")
        self.assertIn("wide_spread", eye.SKIP_WORDS)
        src = inspect.getsource(skips.diagnose)
        self.assertIn("WIDE_SPREAD:", src)
        self.assertIn("entry was refused", src)


class TheWiringTests(SimpleTestCase):

    def test_the_gates_sit_where_they_must(self):
        import inspect
        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.propose_entry)
        no_price = src.index('skips.NO_PRICE, "ticker returned 0"')
        gate = src.index("self._entry_quote_gate(symbol, tk, client)")
        cost = src.index("charge = cost_to_charge(self.cfg, symbol, tk)")
        self.assertLess(no_price, gate)
        self.assertLess(gate, cost)
        src = inspect.getsource(AssetBot.execute_entry)
        look = src.index("self._last_look(client, symbol, decision.direction")
        order = src.index("order_kwargs = {")
        reanchor = src.index("self.reanchor_stop_to_fill(")
        create = src.index("trade = AssetBotTrade.objects.create(")
        self.assertLess(look, order)
        self.assertLess(order, reanchor)
        self.assertLess(reanchor, create)
        self.assertNotIn('if debate.get("on"):\n                _drift', src,
                         "the last look runs on every live order")


# ── the manual lane ───────────────────────────────────────────────────────

class TheManualLaneTests(SimpleTestCase):

    def test_the_quote_advisory_warns_and_never_refuses(self):
        from bot_program.manual_trade import quote_advisory
        ok = quote_advisory(_tick(100, 99.9, 100.1), "crypto", "BTCUSD",
                            stop=98.0)
        self.assertTrue(ok["ok"])
        self.assertTrue(ok["budget_ok"])
        self.assertEqual((ok["bid"], ok["ask"]), (99.9, 100.1))
        self.assertAlmostEqual(ok["spread_pct"], 0.2, places=3)
        self.assertAlmostEqual(ok["half_spread_r"], 0.05, places=3)
        bad = quote_advisory(_tick(100, 100.2, 99.8), "crypto", "BTCUSD")
        self.assertFalse(bad["ok"])
        self.assertIn("crossed quote", bad["reason"])
        wide = quote_advisory(_tick(100, 99, 101), "crypto", "BTCUSD",
                              stop=98.0)
        self.assertTrue(wide["ok"])
        self.assertFalse(wide["budget_ok"])
        self.assertIn("50% of the stop distance", wide["budget_reason"])
        # a paper ticket, or no tick: always ok
        self.assertTrue(quote_advisory(_tick(100, 100.2, 99.8), "crypto",
                                       "BTCUSD", live=False)["ok"])
        self.assertTrue(quote_advisory({}, "crypto", "BTCUSD")["ok"])

    def test_the_mark_read_hands_the_tick_over(self):
        from bot_program.manual_trade import _mark_for_detail, _mark_for
        client = mock.MagicMock()
        client.ticker.return_value = _tick(100, 99.9, 100.1)
        with mock.patch(ROUTER, return_value=client):
            out = _mark_for_detail(mock.MagicMock(), mock.MagicMock(), "BTCUSD")
            self.assertEqual(len(out), 5)
            self.assertEqual(out[0], 100.0)
            self.assertEqual(out[4]["bid"], "99.9")
            self.assertEqual(len(_mark_for(mock.MagicMock(), mock.MagicMock(),
                                           "BTCUSD")), 3)
        client.ticker.side_effect = RuntimeError("down")
        with mock.patch(ROUTER, return_value=client):
            out = _mark_for_detail(mock.MagicMock(), mock.MagicMock(), "BTCUSD")
        self.assertIsNone(out[0])
        self.assertEqual(out[4], {})

    def test_the_preview_the_booking_and_the_popup_carry_it_without_blocking(self):
        from pathlib import Path
        from django.conf import settings
        base = Path(settings.BASE_DIR)
        manual = (base / "bot_program" / "manual_trade.py").read_text(
            encoding="utf-8")
        self.assertIn('"quote_advisory": quote_advisory(_tick, cls, inst.symbol,',
                      manual)
        self.assertIn("AssetBot.reanchor_stop_to_fill(", manual)
        self.assertIn('extra["initial_stop_loss"] = stop', manual)
        self.assertIn('extra["quote_advisory_at_entry"]', manual)
        html = (base / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertIn("p.quote_advisory", html)
        self.assertIn("QUOTE LOOKS OFF", html)
        self.assertIn("WIDE SPREAD FOR THIS STOP", html)
        expr = html.split("okBtn.disabled = ", 1)[1].split(";", 1)[0]
        self.assertNotIn("quoteAdv", expr)
        self.assertNotIn("quote_advisory", expr)
