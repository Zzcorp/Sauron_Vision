"""The attack mode (2026-09-26): extras["leverage"] = "auto".

The operator, 2026-09-26: "je veux surtout que ce mode d'attaque de
leverage soit vraiment smart, qu'il soit ballsy si proba très high" — and
the ceilings the same day: forex 20, index 20, commodity 10.

Under house rule 5 the multiplier changes ONLY the cash eToro locks
(notional / L), never the loss at the stop and never the gain per R. So
the mode has two halves, tested apart:

  RISK  the conviction tier (AssetBot._attack_tier, applied in
        _size_for_entry): STANDARD 0.50x / STRONG 0.75x / HIGH 1.00x of
        the config's own risk fraction, HIGH only with a MEASURED edge
        (n >= 20 graded trades, win rate >= 55%, average R >= +0.20).
  CASH  the chooser (AssetBot._choose_auto_leverage, in _order_leverage):
        the highest multiplier on the instrument's LIVE list inside the
        class ceiling, the PROVEN multiplier (ETORO_PROVEN_LEVERAGE, empty
        on arrival) and the stop band — then every gate a typed number
        meets.

Every test asserts a measured value, a decided number, or a refusal that
sends nothing. The eToro client is the REAL EtoroTrader (adapter_key reads
the class name); its eligibility answers measured rows (doc 2026-09-23
§9-§10, §15) without a wire, so every accessor is the adapter's own reading.

Run with:  python manage.py test tests.test_attack_mode
"""
import re
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_desk_seam import _client as _mock_client
from tests.test_etoro_client import (ROW_AAPL_LIVE, ROW_EURUSD_LIVE,
                                     SEARCH_AAPL, _clear_eligibility,
                                     _elig_route, _elig_row, _lev)
from tests.test_etoro_leverage import (RATES, ROUTER, _account, _book,
                                       _etoro, _order_posts, _switch)
from tests.test_execution_trust import _cfg as _live_cfg
from tests.test_execution_trust import _instrument, _signal, _user

PROVEN = "bot_program.asset_engine.base.ETORO_PROVEN"
PROVEN_LEV = "bot_program.asset_engine.base.ETORO_PROVEN_LEVERAGE"
DETAIL = "bot_program.bot_grading.bot_track_record_detail"

# SPX500 (index, id 27) — MEASURED 2026-09-23 (doc §10) and 2026-09-25
# (§15): CFD only; LIVE cfd/long [1] maxSL 100 AND [2,5,10,20] (the levered
# band unprinted); cfd/short [1,2,5,10,20]; minPositionExposure 1,000 USD.
ROW_SPX500_LIVE = _elig_row(27, "SPX500", [
    _lev("cfd", "long", [1], max_sl=100, min_amount=50),
    _lev("cfd", "long", [2, 5, 10, 20], min_amount=50),
    _lev("cfd", "short", [1, 2, 5, 10, 20], min_amount=50)],
    min_exposure=1000, w8=False)
# A commodity row WIDER than any LIVE list read (WHEAT.FUT's LIVE long is
# [1] / [2,5,10]; its DEMO list runs to 100): the class ceiling, not the
# list, is what stops the chooser at 10.
ROW_WHEAT_WIDE = _elig_row(97, "WHEAT", [
    _lev("cfd", "long", [1], max_sl=100, min_amount=25),
    _lev("cfd", "long", [2, 5, 10, 20, 50], min_amount=25),
    _lev("cfd", "short", [1, 2, 5, 10, 20, 50], min_amount=25)],
    min_exposure=1000, w8=False)
# A long side that lists no 1 at all: a stock row without its real entry,
# only the LIVE cfd/long [2, 5] (maxSL 50).
ROW_NO_ONE = _elig_row(1001, "AAPL", [
    _lev("cfd", "long", [2, 5], max_sl=50)], max_units=6151)


def _wire(rows):
    """The REAL adapter whose eligibility answers `rows` by symbol in both
    worlds, no HTTP: leverage_values, settlement_for and the band readers
    are the adapter's own reading of the row."""
    from bot_program.engine.etoro_client import EtoroTrader
    t = EtoroTrader("api-k", "user-k", env="demo")
    t.eligibility = lambda symbol, world="": rows.get(symbol)
    return t


def _decision(score, rule="atk_rule", direction="BUY"):
    return SimpleNamespace(score=score, rule_name=rule, direction=direction)


def _record(n, win_rate, avg_r, venue="live"):
    """bot_grading.bot_track_record_detail's shape; `expectancy` IS the
    average realized R there (bot_performance_summary)."""
    return {"multiplier": 1.0, "venue": venue, "n": n,
            "win_rate": win_rate, "expectancy": avg_r, "measured": n >= 20,
            "reason": "test"}


class TheThresholdsTests(SimpleTestCase):

    def test_at_sixty_the_thresholds_are_the_thirds_of_the_band(self):
        from bot_program.asset_engine.base import attack_thresholds
        strong, high = attack_thresholds(0.60)
        self.assertAlmostEqual(strong, 0.7333, places=4)
        self.assertAlmostEqual(high, 0.8667, places=4)

    def test_an_unreadable_bar_reads_zero_and_a_wild_one_is_clamped(self):
        from bot_program.asset_engine.base import attack_thresholds
        strong, high = attack_thresholds("x")
        self.assertAlmostEqual(strong, 1 / 3)
        self.assertAlmostEqual(high, 2 / 3)
        self.assertEqual(attack_thresholds(1.5), (1.0, 1.0))


class TheTierTests(TestCase):
    """The RISK half on a stock config at the operator's 7% cap: STANDARD
    3.5%, STRONG 5.25%, HIGH 7% of the pool."""

    def setUp(self):
        from bot_program.asset_engine.stock_bot import StockBot
        self.user = _user("atk_tier")
        _instrument("AAPL", "stock")
        self.cfg = _live_cfg(self.user, name="ATKT")
        self.cfg.extras = {"leverage": "auto", "risk_per_trade_pct": 7}
        self.cfg.save(update_fields=["extras"])
        self.bot = StockBot(self.cfg)

    def _tier(self, score, *, rule="atk_rule", symbol="AAPL", **patch_kw):
        with mock.patch(DETAIL, **patch_kw) as detail:
            out = self.bot._attack_tier(symbol, _decision(score, rule))
        return out, detail

    def test_the_three_tiers_and_the_risk_each_puts_on(self):
        good = _record(40, 0.60, 0.35)
        cases = ((0.7332, "STANDARD", 0.035), (0.7334, "STRONG", 0.0525),
                 (0.8666, "STRONG", 0.0525), (0.8668, "HIGH", 0.07))
        for score, tier, risk in cases:
            with self.subTest(score=score):
                out, _ = self._tier(score, return_value=good)
                self.assertEqual(out["tier"], tier)
                self.assertAlmostEqual(out["risk_fraction"], risk)
                self.assertAlmostEqual(out["config_risk_fraction"], 0.07)
                self.assertEqual(out["strong_from"], 0.7333)
                self.assertEqual(out["high_from"], 0.8667)

    def test_high_needs_the_measured_record(self):
        """n 19, win 54%, avg R +0.19 — each one short keeps a HIGH score
        at STRONG; 20 / 55% / +0.20 is HIGH."""
        for n, wr, avg, words in ((19, 0.60, 0.35, "edge not yet measured"),
                                  (20, 0.54, 0.35, "edge not proven"),
                                  (20, 0.60, 0.19, "edge not proven")):
            with self.subTest(n=n, wr=wr, avg=avg):
                out, _ = self._tier(0.95, return_value=_record(n, wr, avg))
                self.assertEqual(out["tier"], "STRONG")
                self.assertAlmostEqual(out["risk_fraction"], 0.0525)
                self.assertIn(words, out["why"])
        out, _ = self._tier(0.95, return_value=_record(20, 0.55, 0.20))
        self.assertEqual(out["tier"], "HIGH")
        self.assertAlmostEqual(out["risk_fraction"], 0.07)
        self.assertIn("edge measured — atk_rule on stock, live: n 20, win "
                      "55%, avg R +0.20", out["why"])

    def test_the_own_venue_first_then_the_pooled_record_named(self):
        def _by_venue(rule, icls, *, min_n, venue):
            return (_record(5, 0.9, 0.9, venue) if venue == "live"
                    else _record(30, 0.60, 0.30, venue))
        out, detail = self._tier(0.95, side_effect=_by_venue)
        self.assertEqual(out["tier"], "HIGH")
        self.assertIn("pooled (paper and live): n 30", out["why"])
        self.assertEqual([c.kwargs["venue"] for c in detail.call_args_list],
                         ["live", "all"])
        self.assertEqual({c.args for c in detail.call_args_list},
                         {("atk_rule", "stock")})
        self.assertEqual({c.kwargs["min_n"] for c in detail.call_args_list},
                         {20})
        out, detail = self._tier(0.95, return_value=_record(25, 0.6, 0.3))
        self.assertEqual(out["tier"], "HIGH")
        self.assertIn("live: n 25", out["why"])
        self.assertEqual(detail.call_count, 1, "own venue had the record")

    def test_a_losing_own_record_is_never_lifted_by_the_pooled_one(self):
        """Live n 15, avg R -0.80: the pooled 200 trades (mostly paper) at
        +0.30 are never asked — STRONG, not HIGH (bot_grading: simulated
        fills must not size a real order). A thin record that is not
        losing (n 0, nothing measured) still reads the pooled one."""
        def _losing(rule, icls, *, min_n, venue):
            return (_record(15, 0.20, -0.80, venue) if venue == "live"
                    else _record(200, 0.60, 0.30, venue))
        out, detail = self._tier(0.95, side_effect=_losing)
        self.assertEqual(out["tier"], "STRONG")
        self.assertAlmostEqual(out["risk_fraction"], 0.0525)
        self.assertIn("atk_rule on stock, live: n 15, avg R -0.80, a losing "
                      "record on the venue this order goes to, which the "
                      "pooled record may not lift to HIGH", out["why"])
        self.assertEqual([c.kwargs["venue"] for c in detail.call_args_list],
                         ["live"])

        def _cold(rule, icls, *, min_n, venue):
            if venue == "live":
                return {"multiplier": 1.0, "venue": venue, "n": 0,
                        "win_rate": None, "expectancy": None,
                        "measured": False, "reason": "none"}
            return _record(200, 0.60, 0.30, venue)
        out, detail = self._tier(0.95, side_effect=_cold)
        self.assertEqual(out["tier"], "HIGH")
        self.assertIn("pooled (paper and live): n 200", out["why"])
        self.assertEqual([c.kwargs["venue"] for c in detail.call_args_list],
                         ["live", "all"])

    def test_a_paper_config_asks_its_own_venue_first(self):
        self.cfg.mode = "paper"
        self.cfg.save(update_fields=["mode"])
        _, detail = self._tier(0.95, return_value=_record(25, 0.6, 0.3))
        self.assertEqual(detail.call_args.kwargs["venue"], "paper")

    def test_a_raising_lookup_is_standard_never_high(self):
        with self.assertLogs("bot_program.asset_engine.base",
                             level="WARNING") as cm:
            out, _ = self._tier(0.95, side_effect=RuntimeError("db down"))
        self.assertEqual(out["tier"], "STANDARD")
        self.assertAlmostEqual(out["risk_fraction"], 0.035)
        self.assertTrue(any("could not be read" in ln for ln in cm.output),
                        cm.output)

    def test_a_lookup_that_answers_nothing_is_standard(self):
        with self.assertLogs("bot_program.asset_engine.base",
                             level="WARNING"):
            out, _ = self._tier(0.95, return_value=None)
        self.assertEqual(out["tier"], "STANDARD")
        self.assertAlmostEqual(out["risk_fraction"], 0.035)

    def test_a_decision_without_a_rule_cannot_be_high(self):
        out, detail = self._tier(0.95, rule="", return_value=_record(
            40, 0.9, 0.9))
        self.assertEqual(out["tier"], "STRONG")
        self.assertIn("names no rule", out["why"])
        detail.assert_not_called()

    def test_the_record_is_the_instruments_class(self):
        """SPX500 in this STOCK config: its record is read on "index", and
        the words say this config's own SPX500 trades are filed as stock
        (AssetBotTrade.asset_class is the config's), outside that record.
        AAPL, a stock, reads "stock" and carries no such clause."""
        _instrument("SPX500", "index")
        out, detail = self._tier(0.95, symbol="SPX500",
                                 return_value=_record(25, 0.6, 0.3))
        self.assertEqual(detail.call_args.args, ("atk_rule", "index"))
        self.assertIn("atk_rule on index, live: n 25, win 60%, avg R +0.30; "
                      "this stock config files its own index trades as "
                      "stock, outside this record", out["why"])
        out, detail = self._tier(0.95, return_value=_record(25, 0.6, 0.3))
        self.assertEqual(detail.call_args.args, ("atk_rule", "stock"))
        self.assertNotIn("files its own", out["why"])


class TheTierOverrideTests(TestCase):

    def test_junk_keeps_each_default_and_never_raises(self):
        from bot_program.asset_engine.base import attack_tier_scales
        for junk in ("x", "0.3", True, 0, -1, None, [], float("nan")):
            with self.subTest(junk=junk):
                scales = attack_tier_scales(SimpleNamespace(
                    extras={"attack_tiers": {"standard": junk}}))
                self.assertEqual(scales, {"standard": 0.50, "strong": 0.75,
                                          "high": 1.00})
        self.assertEqual(attack_tier_scales(SimpleNamespace(
            extras={"attack_tiers": "fast"}))["high"], 1.00)

    def test_above_one_is_one_and_a_valid_value_stands(self):
        from bot_program.asset_engine.base import attack_tier_scales
        scales = attack_tier_scales(SimpleNamespace(extras={
            "attack_tiers": {"standard": 0.3, "strong": 1.5, "high": 9}}))
        self.assertEqual(scales, {"standard": 0.3, "strong": 1.0,
                                  "high": 1.0})

    def test_risk_is_never_above_the_configs_fraction_nor_the_cap(self):
        """A config typing 40% is clamped to the 7% cap by risk_fraction;
        tiers asking 5x and 2x of it cannot lift it past 7%."""
        from bot_program.asset_engine.sizing import (MAX_RISK_FRACTION,
                                                     risk_fraction)
        from bot_program.asset_engine.stock_bot import StockBot
        self.assertEqual(MAX_RISK_FRACTION, 0.070)
        user = _user("atk_cap")
        _instrument("AAPL", "stock")
        cfg = _live_cfg(user, name="ATKC")
        cfg.extras = {"leverage": "auto", "risk_per_trade_pct": 40,
                      "attack_tiers": {"standard": 2.0, "strong": "x",
                                       "high": 5}}
        cfg.save(update_fields=["extras"])
        self.assertEqual(risk_fraction(cfg), 0.07)
        bot = StockBot(cfg)
        good = _record(40, 0.9, 0.9)
        for score in (0.61, 0.80, 0.95):
            with self.subTest(score=score), mock.patch(DETAIL,
                                                       return_value=good):
                out = bot._attack_tier("AAPL", _decision(score))
                self.assertLessEqual(out["risk_fraction"], 0.07 + 1e-12)
                self.assertLessEqual(out["risk_fraction"],
                                     risk_fraction(cfg) + 1e-12)


class TheSizingSeesTheTierTests(TestCase):
    """The tier lands at the ONE place risk enters the bot lane's sizing:
    the stop floor, the notional cap and the size all read the tiered
    fraction. AAPL at 100, pool 10,000, the 7% cap typed."""

    def setUp(self):
        from bot_program.asset_engine.stock_bot import StockBot
        self.user = _user("atk_size")
        _instrument("AAPL", "stock")
        self.cfg = _live_cfg(self.user, name="ATKS")
        self.cfg.extras = {"leverage": "auto", "risk_per_trade_pct": 7}
        self.cfg.save(update_fields=["extras"])
        self.bot = StockBot(self.cfg)

    def test_standard_halves_the_risk_the_size_and_the_floor(self):
        s = self.bot._size_for_entry("AAPL", 100.0, 50.0, _decision(0.70))
        self.assertEqual(s["attack"]["tier"], "STANDARD")
        self.assertAlmostEqual(s["risk_fraction"], 0.035)
        self.assertAlmostEqual(s["attack"]["risk_fraction"], 0.035)
        self.assertAlmostEqual(s["risk_dollars"], 350.0)
        self.assertAlmostEqual(s["qty"], 7.0)            # 350 / 50
        self.assertFalse(s["stop_widened"])
        # the floor reads the tiered fraction: 3.5% / the 20% cap = 17.5%
        s = self.bot._size_for_entry("AAPL", 100.0, 99.0, _decision(0.70))
        self.assertTrue(s["stop_widened"])
        self.assertAlmostEqual(s["stop"], 82.5)
        self.assertAlmostEqual(s["qty"], 20.0)           # 350 / 17.5

    def test_a_typed_config_sizes_at_its_own_fraction_as_before(self):
        self.cfg.extras = {"leverage": 2, "risk_per_trade_pct": 7}
        self.cfg.save(update_fields=["extras"])
        s = self.bot._size_for_entry("AAPL", 100.0, 50.0, _decision(0.70))
        self.assertNotIn("attack", s)
        self.assertAlmostEqual(s["risk_fraction"], 0.07)
        self.assertAlmostEqual(s["qty"], 14.0)           # 700 / 50

    def test_without_auto_the_sizer_is_called_exactly_as_before(self):
        from bot_program.asset_engine import sizing
        for extras in ({}, {"leverage": 2}, {"leverage": 1}):
            with self.subTest(extras=extras):
                self.cfg.extras = extras
                self.cfg.save(update_fields=["extras"])
                with mock.patch.object(sizing, "size_position",
                                       wraps=sizing.size_position) as spy:
                    s = self.bot._size_for_entry("AAPL", 100.0, 98.0,
                                                 _decision(0.95))
                self.assertEqual(set(spy.call_args.kwargs),
                                 {"asset_class", "entry", "stop",
                                  "direction", "value_per_unit",
                                  "cap_class"})
                self.assertNotIn("attack", s)

    def test_sizing_reads_neither_the_switch_nor_the_proven_table(self):
        """A guard, not the house-rule-5 pin: _size_for_entry never runs the
        chooser, and this keeps it that way — the switch and the proven
        table, which bound the multiplier, change nothing it returns. The
        pin that units never see the multiplier sent is end to end:
        TheEntryLaneTests.test_the_same_units_at_one_and_at_five."""
        _switch(False)
        with mock.patch(PROVEN_LEV, {}):
            one = self.bot._size_for_entry("AAPL", 100.0, 98.0,
                                           _decision(0.80))
        _switch(True)
        with mock.patch(PROVEN_LEV, {"stock": 5}):
            five = self.bot._size_for_entry("AAPL", 100.0, 98.0,
                                            _decision(0.80))
        self.assertEqual(one["attack"]["tier"], five["attack"]["tier"])
        for key in ("qty", "stop", "risk_fraction", "risk_dollars",
                    "notional_fraction"):
            self.assertEqual(one[key], five[key], key)

    def test_the_sizer_clamps_a_scale_to_one_and_ignores_junk(self):
        from bot_program.asset_engine.sizing import size_position
        base = size_position(self.cfg, asset_class="stock", entry=100.0,
                             stop=50.0, direction="BUY")
        for junk in (5, "x", 0, -1, float("nan"), float("inf")):
            with self.subTest(junk=junk):
                s = size_position(self.cfg, asset_class="stock", entry=100.0,
                                  stop=50.0, direction="BUY",
                                  risk_scale=junk)
                self.assertEqual(s["risk_fraction"], base["risk_fraction"])
                self.assertEqual(s["qty"], base["qty"])


class TheChooserTests(TestCase):
    """The CASH half: the highest multiplier on the LIVE list inside the
    ceiling, the proven multiplier and the stop band. At the 7% cap the
    stop floor is 1.75% of price on forex (7% / 4.0) and 3.5% on an index
    or a commodity (7% / 2.0)."""

    ROWS = {"EURUSD": ROW_EURUSD_LIVE, "SPX500": ROW_SPX500_LIVE,
            "WHEAT": ROW_WHEAT_WIDE, "AAPL": ROW_AAPL_LIVE}

    def setUp(self):
        from bot_program.asset_engine.stock_bot import StockBot
        self.user = _user("atk_pick")
        for sym, cls in (("EURUSD", "forex"), ("SPX500", "index"),
                         ("WHEAT", "commodity"), ("AAPL", "stock")):
            _instrument(sym, cls)
        self.cfg = _live_cfg(self.user, name="ATKP")
        self.cfg.extras = {"leverage": "auto"}
        self.cfg.save(update_fields=["extras"])
        self.bot = StockBot(self.cfg)
        _switch(True)

    def _choose(self, symbol, *, price, stop, proven, rows=None,
                side="BUY"):
        with mock.patch(PROVEN_LEV, dict(proven)):
            return self.bot._choose_auto_leverage(
                _wire(self.ROWS if rows is None else rows), symbol, side,
                price, stop)

    def test_forex_at_the_seven_percent_floor_picks_twenty(self):
        """1.75% x 20 = 35% of the margin, inside the one measured band
        (50%, assumed: the levered forex band is unprinted); 30 is on the
        LIVE list and past the ceiling."""
        lev, why = self._choose("EURUSD", price=1.0, stop=0.9825,
                                proven={"forex": 20})
        self.assertEqual(lev, 20)
        self.assertIn("35.0% of the margin", why)
        self.assertIn("assumed from the one measured band", why)

    def test_an_index_at_a_three_and_a_half_percent_stop_picks_ten(self):
        """3.5% x 20 = 70% > 50%: 20 is passed over, 10 (35%) is picked."""
        lev, why = self._choose("SPX500", price=100.0, stop=96.5,
                                proven={"index": 20})
        self.assertEqual(lev, 10)
        self.assertIn("auto: 10x", why)
        self.assertIn("passed over: 20x puts the stop at 70.0% of the "
                      "margin, past the 50% band (assumed)", why)

    def test_a_commodity_never_goes_above_ten(self):
        lev, _ = self._choose("WHEAT", price=100.0, stop=99.9,
                              proven={"commodity": 50})
        self.assertEqual(lev, 10)

    def test_nothing_proven_is_one(self):
        lev, why = self._choose("EURUSD", price=1.0, stop=0.9825, proven={})
        self.assertEqual(lev, 1)
        self.assertIn("no multiplier is proven for forex yet", why)

    def test_the_switch_off_is_one_and_the_words_name_it(self):
        _switch(False)
        lev, why = self._choose("EURUSD", price=1.0, stop=0.9825,
                                proven={"forex": 20})
        self.assertEqual(lev, 1)
        self.assertIn("etoro_leverage_live is OFF", why)

    def test_a_printed_band_wins_over_the_assumed_one(self):
        """AAPL's LIVE CFD band is printed (50): a 12% stop is 60% at 5x,
        24% at 2x."""
        lev, why = self._choose("AAPL", price=100.0, stop=88.0,
                                proven={"stock": 5})
        self.assertEqual(lev, 2)
        self.assertIn("(printed)", why)

    def test_a_side_with_no_one_and_no_fitting_multiplier_is_refused(self):
        lev, why = self._choose("AAPL", price=100.0, stop=98.0, proven={},
                                rows={"AAPL": ROW_NO_ONE})
        self.assertIsNone(lev)
        self.assertIn("auto: no multiplier fits AAPL long", why)
        self.assertIn("1 is not on its LIVE list (cfd: [2, 5])", why)
        self.assertIn("nothing sent", why)
        with mock.patch(PROVEN_LEV, {}):
            lev, why2 = self.bot._order_leverage(
                _wire({"AAPL": ROW_NO_ONE}), "AAPL", side="BUY",
                price=100.0, stop=98.0)
        self.assertIsNone(lev)
        self.assertEqual(why2, why)

    def test_an_unread_row_a_foreign_client_and_no_stop_are_one(self):
        lev, why = self._choose("EURUSD", price=1.0, stop=0.9825,
                                proven={"forex": 20}, rows={})
        self.assertEqual((lev, "unread today" in why), (1, True))
        with mock.patch(PROVEN_LEV, {"forex": 20}):
            lev, why = self.bot._choose_auto_leverage(
                _mock_client("1.0"), "EURUSD", "BUY", 1.0, 0.9825)
        self.assertEqual((lev, "no per-order multiplier" in why), (1, True))
        lev, why = self._choose("EURUSD", price=1.0, stop=None,
                                proven={"forex": 20})
        self.assertEqual((lev, "no stop was handed in" in why), (1, True))

    def test_a_short_reads_the_short_list(self):
        lev, _ = self._choose("SPX500", price=100.0, stop=103.5,
                              proven={"index": 20}, side="SELL")
        self.assertEqual(lev, 10)

    def test_a_margin_under_the_venue_minimum_is_passed_over(self):
        """AAPL's LIVE cfd entries print minPositionAmount 10 (the smallest
        MARGIN eToro takes). 0.4 units at 100 with a 5% stop: 5x fits the
        band (25%) but pledges 8.00 — passed over, never sent to be
        refused; 2x pledges 20.00. 4 units pledge 80.00 at 5x. No qty
        handed in: the minimum is not judged."""
        with mock.patch(PROVEN_LEV, {"stock": 5}):
            lev, why = self.bot._choose_auto_leverage(
                _wire(self.ROWS), "AAPL", "BUY", 100.0, 95.0, qty=0.4)
            self.assertEqual(lev, 2)
            self.assertIn("passed over: 5x pledges 8.00, under eToro's "
                          "minimum margin of 10", why)
            lev, _ = self.bot._choose_auto_leverage(
                _wire(self.ROWS), "AAPL", "BUY", 100.0, 95.0, qty=4)
            self.assertEqual(lev, 5)
            lev, _ = self.bot._choose_auto_leverage(
                _wire(self.ROWS), "AAPL", "BUY", 100.0, 95.0)
            self.assertEqual(lev, 5)

    def test_an_unread_live_list_is_said_and_goes_at_one_as_a_typed_one(self):
        """The own-world row is read, the LIVE row is not: the words say
        "unread today", never "carries nothing", and the order goes at 1x
        exactly as a typed 1 would (_instrument_leverage_check at 1 on an
        unread LIVE list: the class ceiling is the only ceiling). A LIVE
        row read WITHOUT the levered entry says "absent"."""
        from bot_program.engine.etoro_client import EtoroTrader
        t = EtoroTrader("api-k", "user-k", env="demo")
        t.eligibility = (lambda symbol, world="":
                         None if world == "live" else ROW_AAPL_LIVE)
        with mock.patch(PROVEN_LEV, {"stock": 5}):
            lev, why = self.bot._choose_auto_leverage(t, "AAPL", "BUY",
                                                      100.0, 95.0)
            self.assertEqual(lev, 1)
            self.assertIn("eToro's LIVE long/cfd list for AAPL is unread "
                          "today", why)
            self.assertIn("the LIVE long/real list is unread today, and at "
                          "1x the class ceiling is the only ceiling, as for "
                          "a typed 1", why)
            self.assertNotIn("carries nothing", why)
            self.assertEqual(self.bot._order_leverage(
                t, "AAPL", side="BUY", price=100.0, stop=95.0), (1, ""))
        real_only = _elig_row(1001, "AAPL", [
            _lev("real", "long", [1], max_sl=100)], max_units=6151)
        t2 = EtoroTrader("api-k", "user-k", env="demo")
        t2.eligibility = (lambda symbol, world="":
                          real_only if world == "live" else ROW_AAPL_LIVE)
        with mock.patch(PROVEN_LEV, {"stock": 5}):
            lev, why = self.bot._choose_auto_leverage(t2, "AAPL", "BUY",
                                                      100.0, 95.0)
        self.assertEqual(lev, 1)
        self.assertIn("eToro's LIVE long/cfd list for AAPL is absent from "
                      "its LIVE row", why)


class ThePickMeetsEveryGateTests(TestCase):

    def setUp(self):
        from bot_program.asset_engine.stock_bot import StockBot
        self.user = _user("atk_gate")
        _instrument("EURUSD", "forex")
        _instrument("AAPL", "stock")
        self.cfg = _live_cfg(self.user, name="ATKG")
        self.cfg.extras = {"leverage": "auto"}
        self.cfg.save(update_fields=["extras"])
        self.bot = StockBot(self.cfg)
        _switch(True)

    def test_the_pick_is_judged_like_a_typed_number(self):
        """No own book on /setup/: the pick of 20 is refused by the same
        sentence a typed 20 meets — the chooser never bypasses a gate."""
        wire = _wire({"EURUSD": ROW_EURUSD_LIVE})
        with mock.patch(PROVEN_LEV, {"forex": 20}):
            lev, why = self.bot._order_leverage(wire, "EURUSD", side="BUY",
                                                price=1.0, stop=0.9825)
        self.assertIsNone(lev)
        self.assertIn("at 20x: MAX TOTAL EXPOSURE has no book", why)
        self.assertEqual(self.bot._auto_pick["EURUSD"]["leverage"], 20)
        _book(self.user)
        with mock.patch(PROVEN_LEV, {"forex": 20}):
            self.assertEqual(self.bot._order_leverage(
                wire, "EURUSD", side="BUY", price=1.0, stop=0.9825),
                (20, ""))

    def test_the_rule_reads_auto_only_through_a_pick(self):
        from bot_program.asset_engine.base import judge_order_leverage
        _book(self.user)
        for spelled in ("auto", "AUTO", " Auto "):
            with self.subTest(spelled=spelled):
                self.cfg.extras = {"leverage": spelled}
                self.assertEqual(judge_order_leverage(self.cfg, "forex",
                                                      "etoro"), (None, ""))
                self.assertEqual(judge_order_leverage(
                    self.cfg, "forex", "etoro", pick=1), (1, ""))
                self.assertEqual(judge_order_leverage(
                    self.cfg, "forex", "etoro", pick=20), (20, ""))
                lev, why = judge_order_leverage(self.cfg, "forex", "etoro",
                                                pick=21)
                self.assertIsNone(lev)
                self.assertIn("platform cap of 20x", why)
        self.cfg.extras = {"leverage": "autox"}
        lev, why = judge_order_leverage(self.cfg, "forex", "etoro", pick=5)
        self.assertIsNone(lev)
        self.assertIn("not a number", why)
        self.cfg.extras = {"leverage": 2}
        self.assertEqual(judge_order_leverage(self.cfg, "forex", "etoro",
                                              pick=20), (2, ""),
                         "a pick is read only under auto")

    def test_the_proposal_counts_the_most_the_chooser_could_pick(self):
        """MAX SINGLE POSITION before the order (_margin_leverage_hint):
        under auto, the most the chooser could pick for the INSTRUMENT —
        1 while the switch is OFF, else the lowest of the platform cap, the
        class ceiling and the proven multiplier; a typed config keeps its
        typed hint, and no key keeps None (the adapter's 1)."""
        with mock.patch(PROVEN_LEV, {"forex": 20, "stock": 5}):
            self.assertEqual(self.bot._margin_leverage_hint("EURUSD"), 20)
            self.assertEqual(self.bot._margin_leverage_hint("AAPL"), 5)
        with mock.patch(PROVEN_LEV, {"forex": 50}):
            self.assertEqual(self.bot._margin_leverage_hint("EURUSD"), 20)
        with mock.patch(PROVEN_LEV, {}):
            self.assertEqual(self.bot._margin_leverage_hint("EURUSD"), 1)
        _switch(False)
        with mock.patch(PROVEN_LEV, {"forex": 20}):
            self.assertEqual(self.bot._margin_leverage_hint("EURUSD"), 1)
        self.cfg.extras = {"leverage": 2}
        self.assertEqual(self.bot._margin_leverage_hint("EURUSD"), 2)
        self.cfg.extras = {}
        self.assertIsNone(self.bot._margin_leverage_hint("EURUSD"))

    def test_a_config_without_auto_never_reaches_the_chooser(self):
        from bot_program.asset_engine.stock_bot import StockBot
        _book(self.user)
        self.cfg.extras = {"leverage": 2}
        self.cfg.save(update_fields=["extras"])
        with mock.patch.object(StockBot, "_choose_auto_leverage") as chooser:
            out = StockBot(self.cfg)._order_leverage(
                _wire({"AAPL": ROW_AAPL_LIVE}), "AAPL", side="BUY",
                price=100.0, stop=97.0)
        chooser.assert_not_called()
        self.assertEqual(out, (2, ""))


class TheEntryLaneTests(TestCase):
    """execute_entry end to end on the measured AAPL rows: the candidate
    priced through the desk-seam MagicMock, the order through the REAL
    EtoroTrader over a fake wire (tests/test_etoro_leverage.py's harness).
    "stock" is stated proven HERE only. One user per run: the duplicate
    and theme gates are per user, and a second entry on one book would be
    refused as the same bet."""

    def setUp(self):
        _signal(_instrument(), rule="atk_rule")
        _switch(True)
        p = mock.patch(PROVEN, frozenset({"stock"}))
        p.start()
        self.addCleanup(p.stop)
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def _cfg(self, name, extras=None):
        user = _user(name)
        cfg = _live_cfg(user, name=name.upper())
        cfg.base_currency = "USD"
        cfg.extras = dict(extras or {"leverage": "auto"})
        cfg.save(update_fields=["base_currency", "extras"])
        _book(user)
        _account(user, cash=100000)
        return cfg

    def _run(self, cfg, proven, t=None):
        from bot_program.asset_engine.stock_bot import StockBot
        _clear_eligibility()
        bot = StockBot(cfg)
        with mock.patch(PROVEN_LEV, dict(proven)):
            with mock.patch(ROUTER, return_value=_mock_client("100.00")):
                cand = bot.propose_entry("AAPL")
            self.assertIsNotNone(cand)
            t, fake = _etoro() if t is None else t
            with mock.patch(ROUTER, return_value=t), \
                    mock.patch("time.sleep"), \
                    mock.patch("bot_program.notifications."
                               "notify_bot_fill_open") as note:
                res = bot.execute_entry(cand)
        return cand, res, fake, note

    def test_the_same_units_at_one_and_at_five(self):
        from bot_program.models import AssetBotTrade
        cand1, res1, fake1, _ = self._run(self._cfg("atk_one"), {})
        self.assertIsNotNone(res1)
        body1 = _order_posts(fake1)[0][2]["json"]
        row1 = AssetBotTrade.objects.get(id=res1["trade_id"])
        self.assertEqual(body1["leverage"], 1)
        self.assertEqual(row1.metadata["leverage"], 1)
        self.assertEqual(row1.metadata["attack"]["leverage"], 1)
        self.assertIn("no multiplier is proven for stock yet",
                      row1.metadata["attack"]["leverage_why"])
        cand5, res5, fake5, _ = self._run(self._cfg("atk_five"),
                                          {"stock": 5})
        self.assertIsNotNone(res5)
        body5 = _order_posts(fake5)[0][2]["json"]
        row5 = AssetBotTrade.objects.get(id=res5["trade_id"])
        self.assertEqual(body5["leverage"], 5)
        self.assertEqual(row5.metadata["leverage"], 5)
        self.assertEqual(row5.metadata["attack"]["leverage"], 5)
        self.assertIn("auto: 5x", row5.metadata["attack"]["leverage_why"])
        # house rule 5: the multiplier never touches units
        self.assertEqual(cand1.qty_default, cand5.qty_default)
        self.assertAlmostEqual(body1["units"], body5["units"], places=9)
        self.assertEqual(row1.metadata["attack"]["tier"],
                         row5.metadata["attack"]["tier"])
        self.assertAlmostEqual(row5.metadata["risk_fraction"],
                               row5.metadata["attack"]["risk_fraction"])

    def test_the_fill_line_names_tier_risk_multiplier_and_margin(self):
        """HIGH (a measured record), the config's 1%: the stop floor is 5%
        (1% / the stock cap 0.20), so 20 units go at 5x (25% of the
        margin, inside the printed 50). The fake venue fills 3 of the 20
        at 100.00, and the line reports the risk the ROW carries at its
        stop — 3 x 5.00 / 10,000 = 0.15% — not the sizer's 1%, and the
        margin 3 x 100.00 / 5."""
        from bot_program.models import AssetBotTrade
        cfg = self._cfg("atk_line", {"leverage": "auto",
                                     "risk_per_trade_pct": 1})
        with mock.patch(DETAIL, return_value=_record(40, 0.60, 0.35)):
            _, res, fake, note = self._run(cfg, {"stock": 5})
        row = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertEqual(_order_posts(fake)[0][2]["json"]["units"], 20.0)
        self.assertEqual(float(row.qty), 3.0)
        self.assertEqual(row.metadata["attack"]["risk_fraction"], 0.01)
        self.assertEqual(
            note.call_args.kwargs["rule_name"],
            "atk_rule\nAttack: HIGH · risk 0.15% of pool · 5x · "
            "margin 60.00 USD")

    def test_a_typed_config_is_todays_path(self):
        from bot_program.models import AssetBotTrade
        _, res, _, note = self._run(self._cfg("atk_typed", {"leverage": 2}),
                                    {"stock": 5})
        row = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertNotIn("attack", row.metadata)
        self.assertEqual(row.metadata["leverage"], 2)
        self.assertEqual(note.call_args.kwargs["rule_name"], "atk_rule")

    def test_a_refused_pick_sends_nothing_and_names_the_tier(self):
        from bot_program.asset_engine import skips
        from bot_program.models import AssetBotTrade
        cfg = self._cfg("atk_refused")
        wire = _etoro([SEARCH_AAPL, RATES, _elig_route([ROW_NO_ONE]),
                       _elig_route([ROW_NO_ONE], world="live")])
        with mock.patch(DETAIL, return_value=_record(40, 0.60, 0.35)):
            _, res, fake, note = self._run(cfg, {}, t=wire)
        self.assertIsNone(res)
        self.assertEqual(_order_posts(fake), [])
        self.assertEqual(AssetBotTrade.objects.count(), 0)
        note.assert_not_called()
        cfg.refresh_from_db()
        rec = skips.last_by_symbol(cfg)["AAPL"]
        self.assertEqual(rec["code"], skips.LEVERAGE_REFUSED)
        self.assertTrue(rec["detail"].startswith(
            "attack HIGH: auto: no multiplier fits AAPL long — "), rec)

    def test_a_pick_past_the_single_position_cap_sends_nothing(self):
        """The proposal counts the MOST the chooser could pick (5 on a
        stock proven at 5); the pick is 1 (a 35% stop is 70% of the margin
        at 2x, past the printed 50), and MAX SINGLE POSITION, judged again
        at the pick, refuses: 19 units at 100.00 tie up 1,900.00 at 1x,
        past 10% of the 10,000.00 pool — 380.00 at 5x had passed. Nothing
        sent, no row, no notification, and the skip names the tier and
        the multiplier."""
        from bot_program.asset_engine import skips
        from bot_program.models import AssetBotTrade
        from portfolio.risk_gate import limits_book
        book = limits_book()
        book.max_single_position_pct = Decimal("10")
        book.save(update_fields=["max_single_position_pct"])
        cfg = self._cfg("atk_cap", {"leverage": "auto",
                                    "risk_per_trade_pct": 7})
        with mock.patch(DETAIL, return_value=_record(40, 0.60, 0.35)):
            cand, res, fake, note = self._run(cfg, {"stock": 5})
        self.assertEqual(cand.qty_default, 19.0)
        self.assertIsNone(res)
        self.assertEqual(_order_posts(fake), [])
        self.assertEqual(AssetBotTrade.objects.count(), 0)
        note.assert_not_called()
        rec = skips.last_by_symbol(cfg)["AAPL"]
        self.assertEqual(rec["code"], skips.GATE_BLOCKED)
        self.assertTrue(rec["detail"].startswith(
            "attack HIGH: at 1x: this position ties up 1,900.00 — past the "
            "1,000.00 a single position may hold (10% of the 10,000.00 bot "
            "pool)"), rec)


class TheFillWordsTests(TestCase):
    """The Attack line on the OTHER notifier call site — a WORKING entry
    filling later (_finish_working_entry) — and on the rows that cannot
    name a multiplier. The risk is the one the row carries at its stop."""

    def setUp(self):
        from bot_program.asset_engine.stock_bot import StockBot
        self.user = _user("atk_words")
        _instrument("AAPL", "stock")
        self.cfg = _live_cfg(self.user, name="ATKW")
        self.cfg.base_currency = "USD"
        self.cfg.extras = {"leverage": "auto"}
        self.cfg.save(update_fields=["base_currency", "extras"])
        self.bot = StockBot(self.cfg)

    def _row(self, *, rule="atk_rule", paper=False, attack=None, stop="95",
             **meta):
        from tests.test_execution_trust import _trade
        metadata = {"value_per_unit": 1.0, "leverage": 5,
                    "attack": dict(attack or {"tier": "HIGH",
                                              "risk_fraction": 0.01,
                                              "leverage": 5})}
        if stop is not None:
            metadata["initial_stop_loss"] = float(stop)
        metadata.update(meta)
        return _trade(self.cfg, rule_name=rule, paper=paper,
                      qty=Decimal("20"), entry_price=Decimal("100"),
                      stop_loss=None if stop is None else Decimal(stop),
                      metadata=metadata)

    def test_a_working_entry_fill_carries_the_attack_line(self):
        """20 units fill at 100.50 against the 95.00 stop sent: 20 x 5.50
        / 10,000 = 1.1% of the pool; margin 20 x 100.50 / 5 = 402.00."""
        from unittest.mock import MagicMock
        trade = self._row(entry_working=True)
        with mock.patch("bot_program.notifications."
                        "notify_bot_fill_open") as note:
            self.bot._finish_working_entry(trade, MagicMock(), qty=20.0,
                                           price=100.5, source="broker")
        self.assertEqual(
            note.call_args.kwargs["rule_name"],
            "atk_rule\nAttack: HIGH · risk 1.1% of pool · 5x · "
            "margin 402.00 USD")

    def test_a_paper_row_says_so_and_a_row_without_a_rule_shows_a_dash(self):
        trade = self._row(rule="", paper=True,
                          attack={"tier": "STRONG", "risk_fraction": 0.0075})
        self.assertEqual(self.bot._fill_rule_words(trade),
                         "—\nAttack: STRONG · risk 1.0% of pool · paper, "
                         "no multiplier")

    def test_a_row_with_no_stop_falls_back_to_the_sizers_fraction(self):
        trade = self._row(stop=None,
                          attack={"tier": "STANDARD", "risk_fraction": 0.0035,
                                  "leverage": 2})
        self.assertEqual(self.bot._fill_rule_words(trade),
                         "atk_rule\nAttack: STANDARD · risk 0.35% of pool · "
                         "2x · margin 1,000.00 USD")


class ThePreflightTests(TestCase):
    """Section 4 for an auto config: the tier table for its
    entry_score_min and, per instrument class, the ceiling, the proven
    multiplier and the most the chooser may pick — that most judged by
    the engine's own rule."""

    def _armed(self, *, book=True):
        from bot_program.models import EtoroAccount
        from tests.test_preflight_live import _bars, _cfg, _pin
        from tests.test_preflight_live import _user as _pf_user
        u = _pf_user()
        acct = EtoroAccount.objects.create(user=u, demo=False, label="Main",
                                           is_primary_for_stocks=True)
        acct.set_credentials("k", "u")
        acct.last_equity = Decimal("100000")
        acct.last_equity_currency = "USD"
        acct.last_equity_at = timezone.now()
        acct.save()
        if book:
            _book(u)
        _pin(u)
        cfg = _cfg(u, capital="5000", base_currency="USD")
        cfg.extras = {"leverage": "auto", "risk_per_trade_pct": 7}
        cfg.save(update_fields=["extras"])
        _instrument("AAPL", "stock")
        _bars("AAPL", age_hours=1.0)
        return cfg

    def test_the_tier_table_and_the_proven_multiplier_print(self):
        from tests.test_preflight_live import _blockers, _run
        self._armed()
        out = _run()
        self.assertIn("leverage auto (extras) — the attack mode", out)
        self.assertIn("tiers at entry_score_min 0.60: STANDARD below 0.7333 "
                      "— 0.50x, risk 3.50% of the pool", out)
        self.assertIn("STRONG from 0.7333 — 0.75x, risk 5.25%", out)
        self.assertIn("HIGH from 0.8667 with a measured edge (n >= 20, win "
                      ">= 55%, avg R >= +0.20) — 1.00x, risk 7.00%", out)
        self.assertIn("stock: ceiling 5x, proven 1x — the chooser picks at "
                      "most 1x (etoro_leverage_live is OFF: every order goes "
                      "at 1x)", out)
        self.assertNotIn("attack mode", _blockers(out))

    def test_a_proven_multiplier_meets_the_engine_rule(self):
        from tests.test_preflight_live import _blockers, _run
        self._armed(book=False)
        _switch(True)
        with mock.patch(PROVEN_LEV, {"stock": 5}):
            out = _run()
        self.assertIn("stock: ceiling 5x, proven 5x — the chooser picks at "
                      "most 5x", out)
        self.assertIn("in attack mode, stock at 5x: at 5x: MAX TOTAL "
                      "EXPOSURE has no book", _blockers(out))

    def test_a_typed_multiplier_above_the_proven_one_is_worth_reading(self):
        """B4 binds the chooser only: a TYPED 5 on a stock proven at 1x is
        judged as before (inside the ceiling, the switch ON, the own book)
        and preflight says, under WORTH READING, that no 5x proof is
        pinned — never a blocker. Proven at 5, the line goes."""
        from tests.test_preflight_live import _blockers, _run, _worth
        cfg = self._armed()
        cfg.extras = {"leverage": 5}
        cfg.save(update_fields=["extras"])
        _switch(True)
        out = _run()
        self.assertIn("leverage 5x (extras)", out)
        line = (f"config {cfg.id} ({cfg.name}) at 5x: stock is proven at 1x "
                f"only — no demo fill-and-close at 5x is pinned; a typed "
                f"multiplier is not held to the proven multipliers (the "
                f"attack mode is)")
        self.assertIn(line, _worth(out))
        self.assertNotIn("is proven at", _blockers(out))
        with mock.patch(PROVEN_LEV, {"stock": 5}):
            out = _run()
        self.assertNotIn("is proven at", _worth(out))


class TheTakeTradeLaneTests(TestCase):
    """"auto" is a BOT decision: the hand-taken ticket goes at 1x at the
    pool's own risk fraction, and the preview says so."""

    def test_the_ticket_goes_at_one_and_the_preview_says_why(self):
        from django.contrib.auth import get_user_model
        from django.core.cache import cache

        from bot_program.manual_trade import (execute_take_trade,
                                              preview_take_trade)
        from tests.test_take_trade_live import ROUTER as TT_ROUTER
        from tests.test_take_trade_live import (_arm_live, _components_on,
                                                _fake_live_client, _quote)
        from tests.test_take_trade_live import _signal as _tt_signal
        cache.clear()
        user = get_user_model().objects.create_user("atk_tt", password="x")
        inst = _quote("BTCUSD", 60000)
        _components_on()
        cfg = _arm_live(user)
        cfg.extras = dict(cfg.extras or {}, leverage="auto")
        cfg.save(update_fields=["extras"])
        with mock.patch(TT_ROUTER, return_value=_fake_live_client()):
            p = preview_take_trade(user, _tt_signal(inst))
        self.assertNotIn("error", p)
        self.assertIn("Attack mode (extras['leverage'] = \"auto\") is a bot "
                      "decision: this hand-taken ticket goes at 1x",
                      p["leverage"]["note"])
        fake = _fake_live_client()
        with mock.patch(TT_ROUTER, return_value=fake):
            out = execute_take_trade(user, _tt_signal(inst), pin_ok=True)
        self.assertTrue(out.get("ok"), out)
        self.assertNotIn("leverage", fake.market_order.call_args.kwargs)


class TheProvenMultipliersTests(SimpleTestCase):
    """ETORO_PROVEN_LEVERAGE — C0's mechanism (tests/test_etoro_proofs.py)
    for multipliers: class -> the highest multiplier whose demo
    fill-and-close is pinned as test_proof_<class>_at_<L>x."""

    def test_the_table_ships_empty_and_every_class_reads_one(self):
        from bot_program.asset_engine.base import (ETORO_PROVEN_LEVERAGE,
                                                   ORDER_LEVERAGE_CEILING,
                                                   proven_leverage)
        self.assertEqual(ETORO_PROVEN_LEVERAGE, {})
        for cls in ORDER_LEVERAGE_CEILING:
            self.assertEqual(proven_leverage(cls), 1, cls)

    @staticmethod
    def _unpinned(table, src):
        """The (class, multiplier) entries of `table` with no
        `def test_proof_<class>_at_<L>x(` in `src`."""
        pinned = set(re.findall(r"^\s+def test_proof_([a-z]+)_at_(\d+)x\(",
                                src, re.M))
        return sorted((cls, lev) for cls, lev in table.items()
                      if (cls, str(lev)) not in pinned)

    def test_every_entry_has_its_pinned_proof_under_its_ceiling(self):
        """Empty today, so nothing is unpinned — the point: the first
        value that lands without its proof fails here, in the same
        commit."""
        from bot_program.asset_engine.base import (ETORO_PROVEN_LEVERAGE,
                                                   ORDER_LEVERAGE_CEILING)
        src = (Path(settings.BASE_DIR) / "tests"
               / "test_etoro_client.py").read_text(encoding="utf-8")
        self.assertEqual(self._unpinned(ETORO_PROVEN_LEVERAGE, src), [],
                         "ETORO_PROVEN_LEVERAGE names a multiplier whose "
                         "test_proof_<class>_at_<L>x is not pinned")
        for cls, lev in ETORO_PROVEN_LEVERAGE.items():
            self.assertLessEqual(lev, ORDER_LEVERAGE_CEILING[cls], cls)

    def test_the_pin_check_bites(self):
        """The check on a stated source: forex 20 with only an index proof
        pinned is caught; with its own proof it is not."""
        self.assertEqual(self._unpinned(
            {"forex": 20}, "    def test_proof_index_at_20x(self):\n"),
            [("forex", 20)])
        self.assertEqual(self._unpinned(
            {"forex": 20}, "    def test_proof_forex_at_20x(self):\n"), [])
        self.assertEqual(self._unpinned(
            {"forex": 20}, "    def test_proof_forex_at_10x(self):\n"),
            [("forex", 20)])

    def test_it_is_read_at_call_time_and_junk_reads_one(self):
        from bot_program.asset_engine.base import proven_leverage
        with mock.patch(PROVEN_LEV, {"forex": 20}):
            self.assertEqual(proven_leverage("forex"), 20)
            self.assertEqual(proven_leverage("index"), 1)
        for junk in ("20", 2.5, True, 0, -5, float("nan")):
            with self.subTest(junk=junk), mock.patch(PROVEN_LEV,
                                                     {"forex": junk}):
                self.assertEqual(proven_leverage("forex"), 1)

    def test_no_switch_can_name_it(self):
        import inspect

        from core import platform_control
        self.assertNotIn("ETORO_PROVEN_LEVERAGE",
                         inspect.getsource(platform_control))
