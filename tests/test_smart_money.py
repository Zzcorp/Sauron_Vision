"""THE SMART MONEY'S FOOTPRINTS (2026-10-02).

The operator: study the smart money and the big flows of funds, avoid the
spoofing and the moves made on purpose to break the other side's
positions. These tests pin what bot_program/smart_money.py does with what
can be seen from here: a stop moved out of the crowd's hunt zone within
the plan's reward:risk, smaller real-money entries against a fresh sweep
or a crowded COT positioning, the VIX curve in the stress score, and the
switch that keeps all of it OFF until the operator turns it on.

Run with:  python manage.py test tests.test_smart_money
"""
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _switch(on=True):
    from core.platform_control import PlatformComponent
    PlatformComponent.objects.update_or_create(
        key="smart_money", defaults={"name": "sm", "category": "system",
                                     "is_enabled": on})


def _df(rows):
    """rows: [(open, high, low, close)] oldest first."""
    idx = pd.date_range("2026-09-01", periods=len(rows), freq="4h")
    return pd.DataFrame([{"open": o, "high": h, "low": lo, "close": c,
                          "volume": 0} for o, h, lo, c in rows], index=idx)


def _flat(n, close=100.0, half=1.0):
    return [(close, close + half, close - half, close)] * n


# ── 1. the crowd's stops ──────────────────────────────────────────────────

class TheStopTests(SimpleTestCase):

    def test_a_stop_just_past_a_swing_low_moves_beyond_the_hunt(self):
        from bot_program.smart_money import HUNT_DEPTH_ATR, stop_beyond_the_crowd
        r = stop_beyond_the_crowd("BUY", 100.0, 97.0, 2.0,
                                  [(97.4, "swing low")])
        self.assertTrue(r["moved"])
        self.assertAlmostEqual(r["stop"], 97.4 - HUNT_DEPTH_ATR * 2.0)
        self.assertIn("swing low", r["why"])

    def test_a_stop_just_short_of_a_level_is_taken_on_the_way(self):
        from bot_program.smart_money import stop_beyond_the_crowd
        r = stop_beyond_the_crowd("BUY", 100.0, 97.3, 2.0,
                                  [(97.0, "round number")])
        self.assertTrue(r["moved"])
        self.assertAlmostEqual(r["stop"], 96.0)

    def test_a_stop_clear_of_every_level_stays(self):
        from bot_program.smart_money import stop_beyond_the_crowd
        r = stop_beyond_the_crowd("BUY", 100.0, 97.0, 2.0,
                                  [(99.0, "swing low"), (94.0, "swing low"),
                                   (101.0, "swing low")])
        self.assertFalse(r["moved"])
        self.assertEqual(r["stop"], 97.0)
        self.assertFalse(r["crowded"])

    def test_a_chain_of_levels_settles_in_one_pass(self):
        from bot_program.smart_money import stop_beyond_the_crowd
        r = stop_beyond_the_crowd("BUY", 100.0, 97.0, 2.0,
                                  [(96.4, "swing low"), (97.2, "swing low")])
        # 97.2 -> 96.2 lands in 96.4's zone -> 95.4
        self.assertAlmostEqual(r["stop"], 95.4)
        self.assertEqual([lv["price"] for lv in r["levels"]], [97.2, 96.4])

    def test_a_zone_past_the_cap_leaves_the_stop_and_says_crowded(self):
        from bot_program.smart_money import stop_beyond_the_crowd
        r = stop_beyond_the_crowd("BUY", 100.0, 97.0, 2.0,
                                  [(97.2, "swing low"), (96.4, "swing low"),
                                   (95.6, "swing low")])
        # 97.0 -> 96.2 -> 95.4 -> 94.6: 5.4 from the entry, cap 3 + 2 = 5
        self.assertFalse(r["moved"])
        self.assertTrue(r["crowded"])
        self.assertEqual(r["stop"], 97.0)

    def test_the_plan_s_reward_risk_caps_the_move(self):
        from bot_program.smart_money import stop_beyond_the_crowd
        free = stop_beyond_the_crowd("BUY", 100.0, 97.0, 2.0,
                                     [(97.4, "swing low")])
        self.assertTrue(free["moved"])
        tight = stop_beyond_the_crowd("BUY", 100.0, 97.0, 2.0,
                                      [(97.4, "swing low")], max_distance=3.2)
        self.assertFalse(tight["moved"])
        self.assertTrue(tight["crowded"])
        # the widening in ATRs (0.30), and the room the plan allows (0.10)
        self.assertIn("widening it 0.30 ATR and the plan allows 0.10",
                      tight["why"])

    def test_a_sell_mirrors(self):
        from bot_program.smart_money import stop_beyond_the_crowd
        r = stop_beyond_the_crowd("SELL", 100.0, 103.0, 2.0,
                                  [(102.6, "swing high"), (99.0, "swing high")])
        self.assertAlmostEqual(r["stop"], 103.6)
        self.assertTrue(r["moved"])

    def test_no_atr_moves_nothing(self):
        from bot_program.smart_money import stop_beyond_the_crowd
        r = stop_beyond_the_crowd("BUY", 100.0, 97.0, None,
                                  [(97.4, "swing low")])
        self.assertEqual((r["stop"], r["moved"]), (97.0, False))

    def test_the_round_numbers_follow_the_instrument_s_scale(self):
        from bot_program.smart_money import round_levels, round_step
        self.assertAlmostEqual(round_step(0.0025), 0.01)       # EURUSD figures
        self.assertAlmostEqual(round_step(30.0), 100.0)        # SPX hundreds
        self.assertAlmostEqual(round_step(3.0), 10.0)          # a $230 stock
        self.assertIsNone(round_step(0))
        self.assertEqual(round_levels(1.081, 1.096, 0.01), [1.085, 1.09, 1.095])

    def test_the_crowd_s_levels_for_a_buy(self):
        from bot_program.smart_money import crowd_levels
        rows = _flat(20, 100.0)
        rows[-2] = (100.0, 101.0, 98.2, 100.0)
        df = _df(rows)
        swings = [{"idx": 5, "type": "L", "price": 97.5},
                  {"idx": 6, "type": "H", "price": 103.0},
                  {"idx": 7, "type": "L", "price": 104.0}]
        kinds = dict((k, p) for p, k in crowd_levels(
            "BUY", 100.0, 97.0, 2.0, df, swings))
        self.assertEqual(kinds["swing low"], 97.5, "only lows below the entry")
        self.assertEqual(kinds["recent low"], 98.2)
        self.assertIn("round number", kinds)


class TheRoomTests(SimpleTestCase):

    def test_the_widest_stop_is_exactly_where_the_cost_filter_stops(self):
        from bot_program.asset_engine.risk_levels import (
            max_stop_distance, passes_cost_filter,
        )
        cfg = SimpleNamespace(asset_class="stock", extras={})
        room = max_stop_distance(cfg, "X", 100.0, 106.0)
        self.assertTrue(passes_cost_filter(cfg, "X", 100.0, 106.0,
                                           stop=100.0 - room * 0.999)[0])
        self.assertFalse(passes_cost_filter(cfg, "X", 100.0, 106.0,
                                            stop=100.0 - room * 1.01)[0])

    def test_with_the_filter_off_the_gross_reward_risk_bounds_it(self):
        from bot_program.asset_engine.risk_levels import max_stop_distance
        cfg = SimpleNamespace(asset_class="stock",
                              extras={"use_cost_filter": False})
        self.assertAlmostEqual(max_stop_distance(cfg, "X", 100.0, 106.0), 4.0)


# ── 2. the sweep ──────────────────────────────────────────────────────────

class TheSweepTests(SimpleTestCase):

    def _swept_highs(self):
        rows = _flat(30, 100.0)
        rows[-1] = (100.0, 104.0, 99.5, 100.2)    # wick through 102, back in
        return _df(rows), [{"idx": 10, "type": "H", "price": 102.0}]

    def test_a_buy_right_after_a_sweep_of_the_highs_takes_half(self):
        from bot_program.smart_money import AGAINST_SWEEP_SCALE, sweep_read
        df, swings = self._swept_highs()
        r = sweep_read(df, swings, "BUY", 2.0)
        self.assertEqual(r["scale"], AGAINST_SWEEP_SCALE)
        self.assertIn("sweep of the highs", r["why"])
        s = sweep_read(df, swings, "SELL", 2.0)
        self.assertEqual(s["scale"], 1.0, "a short rides the grab")
        self.assertTrue(s["with"])

    def test_a_swing_not_yet_confirmed_is_not_swept(self):
        from bot_program.smart_money import sweep_read
        df, _ = self._swept_highs()
        r = sweep_read(df, [{"idx": 28, "type": "H", "price": 102.0}],
                       "BUY", 2.0)
        self.assertEqual(r["scale"], 1.0)

    def test_a_breakout_only_the_latest_bar_took_is_not_yet_held(self):
        from bot_program.smart_money import (UNCONFIRMED_BREAKOUT_SCALE,
                                             sweep_read)
        rows = _flat(30, 100.0)
        rows[-1] = (100.0, 102.6, 99.8, 102.3)
        df = _df(rows)
        swings = [{"idx": 10, "type": "H", "price": 102.0}]
        r = sweep_read(df, swings, "BUY", 2.0, entry=102.3)
        self.assertEqual(r["scale"], UNCONFIRMED_BREAKOUT_SCALE)
        self.assertEqual(sweep_read(df, swings, "BUY", 2.0,
                                    entry=103.0)["scale"], 1.0,
                         "past a quarter ATR the breakout is not a wick")

    def test_a_quiet_tape_says_nothing(self):
        from bot_program.smart_money import sweep_read
        df = _df(_flat(30, 100.0))
        r = sweep_read(df, [{"idx": 10, "type": "H", "price": 102.0},
                            {"idx": 12, "type": "L", "price": 98.0}],
                       "BUY", 2.0)
        self.assertEqual((r["scale"], r["against"], r["with"]),
                         (1.0, None, None))


# ── 3. the crowded trade ──────────────────────────────────────────────────

class TheCotScaleTests(SimpleTestCase):

    def test_the_index_and_the_scales(self):
        from bot_program.smart_money import cot_index, cot_scale
        self.assertEqual(cot_index([10, 0, 5, 10]), 100.0)
        self.assertEqual(cot_index([0, 0, 10]), 0.0)
        self.assertIsNone(cot_index([3, 3, 3]))
        self.assertEqual(cot_scale("BUY", 95, 50)[0], 0.5)
        self.assertEqual(cot_scale("BUY", 85, 50)[0], 0.75)
        self.assertEqual(cot_scale("SELL", 95, 50)[0], 1.0)
        self.assertEqual(cot_scale("SELL", 5, 50)[0], 0.5)
        self.assertEqual(cot_scale("BUY", 50, 5)[0], 0.5,
                         "against the hedgers at an extreme short")
        self.assertEqual(cot_scale("BUY", 50, 95)[0], 1.0,
                         "with the hedgers: no cut, and never a boost")


class TheCotReadTests(TestCase):

    def _reports(self, symbol, weeks, *, latest_age_days=3, top=True):
        from instruments.models import Instrument
        from scraping.models import COTReport
        inst = Instrument.objects.create(symbol=symbol, name=symbol,
                                         asset_class="forex")
        today = timezone.now().date()
        for w in range(weeks):
            net = 1000 * (w % 7) if w else (9000 if top else -9000)
            COTReport.objects.create(
                instrument=inst,
                report_date=today - timedelta(days=latest_age_days + 7 * w),
                commercial_long=10000, commercial_short=10000 + net,
                non_commercial_long=10000 + net, non_commercial_short=10000,
                open_interest=100000, net_speculative=net)
        return inst

    def test_speculators_at_a_3_year_high_cut_a_buy(self):
        from bot_program.smart_money import cot_read
        self._reports("EURUSD", 60)
        r = cot_read("EURUSD", "BUY")
        self.assertEqual(r["spec_index"], 100.0)
        self.assertEqual(r["comm_index"], 0.0)
        self.assertEqual(r["scale"], 0.5)
        self.assertEqual(cot_read("EURUSD", "SELL")["scale"], 1.0)

    def test_a_usd_base_pair_reads_the_future_the_other_way(self):
        from bot_program.smart_money import cot_read
        self._reports("USDJPY", 60)
        self.assertEqual(cot_read("USDJPY", "BUY")["scale"], 1.0)
        r = cot_read("USDJPY", "SELL")
        self.assertEqual((r["spec_index"], r["scale"]), (0.0, 0.5))

    def test_thin_or_stale_history_is_neutral_and_said(self):
        from bot_program.smart_money import cot_read
        self._reports("EURUSD", 20)
        r = cot_read("EURUSD", "BUY")
        self.assertEqual(r["scale"], 1.0)
        self.assertIn("cot-backfill", r["why"])
        self._reports("GBPUSD", 60, latest_age_days=40)
        r = cot_read("GBPUSD", "BUY")
        self.assertEqual(r["scale"], 1.0)
        self.assertIn("stale", r["why"])
        self.assertIn("no instrument", cot_read("NOPE", "BUY")["why"])

    def test_the_backfill_stores_the_yearly_archives(self):
        from instruments.models import Instrument
        from scraping.models import COTReport
        from scraping.scrapers.cot_reports import backfill_cot_history
        Instrument.objects.create(symbol="XAUUSD", name="gold",
                                  asset_class="commodity")
        header = ("Market and Exchange Names,As of Date in Form YYYY-MM-DD,"
                  "Open Interest (All),Noncommercial Positions-Long (All),"
                  "Noncommercial Positions-Short (All),"
                  "Commercial Positions-Long (All),"
                  "Commercial Positions-Short (All)\n")

        def fake(url):
            year = int(url.rsplit("deacot", 1)[1][:4])
            return header + "".join(
                f'"GOLD - COMMODITY EXCHANGE INC.",{year}-0{m}-05,'
                f"500000,200000,50000,100000,250000\n" for m in (1, 2))

        with patch("scraping.scrapers.cot_reports._fetch_zip",
                   side_effect=fake):
            out = backfill_cot_history(2, now=date(2026, 10, 2))
        self.assertEqual(out["years"], [2024, 2025, 2026])
        self.assertEqual(COTReport.objects.count(), 6)
        with patch("scraping.scrapers.cot_reports._fetch_zip",
                   side_effect=fake):
            again = backfill_cot_history(2, now=date(2026, 10, 2))
        self.assertEqual((again["created"], COTReport.objects.count()), (0, 6))


# ── 4. the VIX curve ──────────────────────────────────────────────────────

class TheVixCurveTests(TestCase):

    def _series(self, sid, values):
        from market_data.models import MacroIndicator, MacroObservation
        ind = MacroIndicator.objects.create(series_id=sid, name=sid,
                                            category="macro",
                                            frequency="daily")
        today = timezone.now().date()
        for days_ago, v in values:
            MacroObservation.objects.create(
                indicator=ind, date=today - timedelta(days=days_ago), value=v)

    def test_an_upside_down_curve_scores_as_panic(self):
        from bot_program.market_stress import read_components, score
        self._series("VIXCLS", [(1, 33.0), (0, 36.0)])
        self._series("VXVCLS", [(1, 30.0)])
        _switch()
        comps, _ = read_components()
        self.assertEqual(comps["vix_term"], 1.1, "the newest day both have")
        _sc, subs = score(comps)
        self.assertEqual(subs["vix_term"], 85.0)

    def test_off_the_crisis_score_is_what_it_was(self):
        """Review, 2026-10-02: crisis_mode is ON in production; the curve
        must not move its score until the operator turns smart_money on."""
        from bot_program.market_stress import read_components
        self._series("VIXCLS", [(1, 33.0)])
        self._series("VXVCLS", [(1, 30.0)])
        comps, reasons = read_components()
        self.assertNotIn("vix_term", comps)
        self.assertFalse(any("VXVCLS" in r for r in reasons))

    def test_without_the_3_month_twin_the_curve_is_left_out_and_said(self):
        from bot_program.market_stress import read_components
        self._series("VIXCLS", [(0, 18.0)])
        _switch()
        comps, reasons = read_components()
        self.assertNotIn("vix_term", comps)
        self.assertTrue(any("VXVCLS" in r for r in reasons))

    def test_fred_fetches_the_twin(self):
        from core.constants import FRED_SERIES
        self.assertIn("VXVCLS", FRED_SERIES)


# ── 5. the entry ──────────────────────────────────────────────────────────

ROUTER = "bot_program.engine.broker_router.client_for_symbol"


class TheEntryTests(TestCase):
    """A paper stock bot proposes an entry on bars where the ATR stop
    lands just past a swing low."""

    def setUp(self):
        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument
        from market_data.models import PriceData
        from signals.models import Signal
        self.user = User.objects.create_user("sm_u", password="x")
        self.inst = Instrument.objects.create(symbol="SMX", name="SMX",
                                              asset_class="stock")
        closes = [152.0] * 60
        for i, c in zip(range(36, 45), (151, 150, 149, 148.2, 148.2, 149,
                                        150, 151, 152)):
            closes[i] = c
        closes[-1] = 150.0
        start = timezone.now() - timedelta(hours=4 * len(closes))
        PriceData.objects.bulk_create([PriceData(
            instrument=self.inst, timeframe="4h",
            timestamp=start + timedelta(hours=4 * i), open=c, high=c + 1,
            low=c - 1, close=c, source="t") for i, c in enumerate(closes)])
        self.cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="SM", enabled=True,
            mode="paper", symbols=["SMX"], capital=Decimal("10000"),
            base_currency="USD", position_size_pct=2.0,
            max_concurrent_positions=5, max_daily_loss_pct=2.0,
            stop_loss_pct=1.5, take_profit_pct=3.0, entry_score_min=0.6,
            min_signals_for_entry=1, cool_down_minutes=0)
        Signal.objects.create(
            instrument=self.inst, signal_type="composite", direction="bullish",
            urgency="medium", title="SMX", description="t", rule_name="sm_rule",
            score=0.85, sub_scores={}, price_at_signal=Decimal("150"),
            suggested_entry=Decimal("150"), suggested_stop=Decimal("145"),
            suggested_target=Decimal("160"))

    def _propose(self):
        from unittest.mock import MagicMock

        from bot_program.asset_engine import StockBot
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": "150.00"}
        client.get_positions.return_value = []
        with patch(ROUTER, return_value=client):
            return StockBot(self.cfg).propose_entry("SMX")

    def test_off_the_stop_is_the_atr_stop(self):
        cand = self._propose()
        self.assertIsNotNone(cand)
        self.assertNotIn("smart_money", cand.level_meta)
        self.assertAlmostEqual(cand.price - cand.stop,
                               1.5 * cand.level_meta["atr"], places=4)

    def test_on_the_stop_leaves_the_swing_low_s_hunt_zone(self):
        _switch()
        cand = self._propose()
        self.assertIsNotNone(cand)
        sm = cand.level_meta["smart_money"]
        self.assertTrue(sm["stop_moved"], sm)
        self.assertLess(cand.stop, sm["original_stop"])
        atr = cand.level_meta["atr"]
        self.assertLessEqual(cand.price - cand.stop,
                             cand.price - sm["original_stop"] + atr + 1e-9)
        self.assertEqual(sm["scale"], 1.0, "a paper entry is never cut")

    def test_the_scale_binds_real_money_only(self):
        base = self._propose()
        _switch()
        read = {"stop": None, "moved": False, "scale": 0.5,
                "why": ["size x0.5: test"], "stop_read": {}, "sweep": {},
                "cot": {}}

        def fake(symbol, direction, entry, stop, **kw):
            return dict(read, stop=stop)

        with patch("bot_program.smart_money.entry_read", side_effect=fake):
            paper = self._propose()
        self.assertEqual(paper.stage["live_size_factor"],
                         base.stage["live_size_factor"])
        self.assertEqual(paper.qty_default, base.qty_default)

    def test_the_hooks_sit_where_they_must(self):
        import inspect

        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.propose_entry)
        self.assertLess(src.index("stop_and_target("),
                        src.index("self._smart_money("))
        self.assertLess(src.index("self._smart_money("),
                        src.index("passes_cost_filter("))
        self.assertLess(src.index("self._aragorn_and_posture("),
                        src.index("self._smart_money_scale(stage, sm_read)"))
        self.assertLess(src.index("self._smart_money_scale(stage, sm_read)"),
                        src.index("self._size_for_entry("))

    def test_the_scale_cuts_a_live_entry_and_nothing_else(self):
        from bot_program.asset_engine import StockBot
        bot = StockBot(self.cfg)
        stage = {"force_paper": False, "live_size_factor": 0.5}
        read = {"scale": 0.75}
        self.assertEqual(bot._smart_money_scale(stage, read), stage,
                         "a paper config")
        bot.cfg.mode = "live"
        self.assertEqual(bot._smart_money_scale(stage, read)
                         ["live_size_factor"], 0.375)
        self.assertEqual(stage["live_size_factor"], 0.5, "a copy, not a write")
        sent = dict(stage, force_paper=True)
        self.assertEqual(bot._smart_money_scale(sent, read), sent)
        self.assertEqual(bot._smart_money_scale(stage, None), stage)
        self.assertEqual(bot._smart_money_scale(stage, {"scale": 1.0}), stage)

    def test_a_failed_read_changes_nothing(self):
        _switch()
        with patch("bot_program.smart_money.entry_read",
                   side_effect=RuntimeError("boom")):
            cand = self._propose()
        self.assertIsNotNone(cand)
        self.assertNotIn("smart_money", cand.level_meta)


# ── 6. the operator ───────────────────────────────────────────────────────

class TheControlsTests(TestCase):

    def test_the_switch_is_live_money_and_off_by_default(self):
        from core.platform_control import (BULK_ENABLE_EXEMPT,
                                           DEFAULT_COMPONENTS,
                                           LIVE_MONEY_SWITCHES,
                                           is_component_enabled,
                                           seed_components)
        self.assertIn("smart_money", LIVE_MONEY_SWITCHES)
        self.assertIn("smart_money", BULK_ENABLE_EXEMPT)
        row = {c["key"]: c for c in DEFAULT_COMPONENTS}["smart_money"]
        self.assertLess(len(row["description"]), 300)
        seed_components()
        self.assertFalse(is_component_enabled("smart_money"))
        from bot_program.smart_money import is_on
        self.assertFalse(is_on())

    def test_the_command_reads_an_entry_and_plans_the_backfill(self):
        from instruments.models import Instrument
        from market_data.models import PriceData
        inst = Instrument.objects.create(symbol="SMC", name="SMC",
                                         asset_class="stock")
        start = timezone.now() - timedelta(hours=4 * 40)
        PriceData.objects.bulk_create([PriceData(
            instrument=inst, timeframe="4h",
            timestamp=start + timedelta(hours=4 * i), open=100, high=101,
            low=99, close=100, source="t") for i in range(40)])
        out = StringIO()
        call_command("smart_money", "read", "SMC", "BUY", stdout=out)
        text = out.getvalue()
        self.assertIn("SMC BUY at 100", text)
        self.assertIn("switch OFF", text)
        out = StringIO()
        call_command("smart_money", "cot-backfill", stdout=out)
        self.assertIn("PLAN", out.getvalue())
        with patch("scraping.scrapers.cot_reports.backfill_cot_history",
                   return_value={"years": [2025, 2026], "parsed": 10,
                                 "stored": 8, "created": 8, "failed": [],
                                 "missing_instruments": []}) as bf:
            out = StringIO()
            call_command("smart_money", "cot-backfill", "--yes",
                         "--years", "1", stdout=out)
        bf.assert_called_once_with(1)
        self.assertIn("stored 8", out.getvalue())
        out = StringIO()
        call_command("smart_money", stdout=out)
        self.assertIn("Smart money: OFF", out.getvalue())

    def test_aragorn_s_report_carries_it_when_on(self):
        from bot_program.aragorn import report_lines
        self.assertFalse(any("Smart money" in ln for ln in report_lines()))
        _switch()
        self.assertTrue(any("Smart money: ON" in ln for ln in report_lines()))


# ── 7. the held position ──────────────────────────────────────────────────

def _held(side="BUY", entry=100.0, stop=98.0, peak=104.0):
    return SimpleNamespace(
        side=side, entry_price=Decimal(str(entry)),
        stop_loss=Decimal(str(stop)),
        metadata={"initial_stop_loss": stop, "care": {"peak": peak}},
        asset_class="crypto", paper=True,
        opened_at=timezone.now() - timedelta(hours=2))


class TheCareTests(SimpleTestCase):

    def test_a_trail_in_the_hunt_zone_is_placed_beyond_it(self):
        from bot_program.position_care import plan
        plain = plan(_held(), 104.0)
        self.assertEqual(plain["care"]["soft_stop"], 102.0)
        crowd = {"atr": 2.0, "levels": [(102.2, "swing low")]}
        moved = plan(_held(), 104.0, crowd=crowd)
        self.assertEqual(moved["care"]["soft_stop"], 101.2)
        self.assertEqual(moved["care"]["soft_why"], "trail (beyond the crowd)")
        self.assertEqual(moved["action"], "hold")

    def test_a_lock_never_goes_below_the_entry(self):
        from bot_program.position_care import plan
        p = _held(peak=102.4)                    # mfe 1.2R: break-even only
        crowd = {"atr": 2.0, "levels": [(100.4, "round number")]}
        r = plan(p, 102.4, crowd=crowd)
        self.assertEqual(r["care"]["soft_stop"], 100.2)
        self.assertEqual(r["care"]["soft_why"], "breakeven")

    def test_a_short_mirrors(self):
        from bot_program.position_care import plan
        p = _held(side="SELL", entry=100.0, stop=102.0, peak=96.0)
        crowd = {"atr": 2.0, "levels": [(97.8, "swing high")]}
        r = plan(p, 96.0, crowd=crowd)
        self.assertEqual(r["care"]["soft_stop"], 98.8)

    def test_the_manual_lane_and_the_posture_floor_never_move(self):
        from bot_program.position_care import plan
        crowd = {"atr": 2.0, "levels": [(102.2, "swing low")]}
        r = plan(_held(), 104.0, crowd=crowd, manual=True)
        self.assertEqual(r["care"]["soft_stop"], 102.0)
        losing = _held(peak=100.0)
        losing.paper = False
        crowd = {"atr": 2.0, "levels": [(98.6, "swing low")]}
        r = plan(losing, 99.5, crowd=crowd, live=True, kind="risk_on_long",
                 posture_level="crisis")
        self.assertEqual(r["care"]["soft_stop"], 99.0, "the -0.5R floor")


class TheCareWiringTests(TestCase):

    def test_care_reads_the_crowd_only_with_the_switch_on(self):
        from bot_program import position_care
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.update_or_create(
            key="aragorn", defaults={"name": "a", "category": "system",
                                     "is_enabled": True})
        bot = SimpleNamespace(cfg=SimpleNamespace(),
                              _instrument_class=lambda s: "crypto")
        trade = _held()
        trade.symbol, trade.id, trade.pk, trade.rule_name = "BTCUSD", 1, 1, "r"
        crowd = {"atr": 2.0, "levels": [(102.2, "swing low")]}
        with patch("bot_program.smart_money.care_levels",
                   return_value=crowd) as lv, \
                patch("bot_program.position_care._save_care") as save:
            position_care.care(bot, trade, 104.0, None)
            lv.assert_not_called()
            self.assertEqual(save.call_args.args[1]["soft_stop"], 102.0)
            _switch()
            position_care.care(bot, trade, 104.0, None)
            lv.assert_called_once_with("BTCUSD", "BUY", 104.0)
            self.assertEqual(save.call_args.args[1]["soft_stop"], 101.2)

    def test_the_care_levels_come_from_the_bars(self):
        from bot_program.smart_money import care_levels
        from instruments.models import Instrument
        from market_data.models import PriceData
        inst = Instrument.objects.create(symbol="CLV", name="CLV",
                                         asset_class="crypto")
        closes = [100.0] * 40
        closes[20] = 97.0
        start = timezone.now() - timedelta(hours=4 * 40)
        PriceData.objects.bulk_create([PriceData(
            instrument=inst, timeframe="4h",
            timestamp=start + timedelta(hours=4 * i), open=c, high=c + 1,
            low=c - 1, close=c, source="t") for i, c in enumerate(closes)])
        out = care_levels("CLV", "BUY", 100.0)
        self.assertGreater(out["atr"], 0)
        self.assertIn((96.0, "swing low"), out["levels"])
        self.assertIsNone(care_levels("NOBARS", "BUY", 100.0))


# ── 8. ICT, the volume and the pools ──────────────────────────────────────

def _vdf(rows):
    """rows: [(open, high, low, close, volume)] oldest first."""
    idx = pd.date_range("2026-09-01", periods=len(rows), freq="4h")
    return pd.DataFrame([{"open": o, "high": h, "low": lo, "close": c,
                          "volume": v} for o, h, lo, c, v in rows], index=idx)


class TheIctTests(SimpleTestCase):

    def test_the_ict_scale(self):
        from bot_program.smart_money import ict_scale
        self.assertEqual(ict_scale("BUY", bias="short", confidence=0.7)[0], 0.5)
        self.assertEqual(ict_scale("BUY", bias="short", confidence=0.3)[0], 0.75)
        self.assertEqual(ict_scale("BUY", bias="long", confidence=0.9,
                                   zone="premium"), (0.75, "buying the premium "
                                                     "of the dealing range: "
                                                     "chasing"))
        self.assertEqual(ict_scale("SELL", bias="short", zone="premium")[0], 1.0)
        self.assertEqual(ict_scale("SELL", zone="discount")[0], 0.75)
        self.assertEqual(ict_scale("BUY", opposing="a wall")[0], 0.75)
        self.assertEqual(ict_scale("BUY", draw_room_atr=0.4)[0], 0.75)
        self.assertEqual(ict_scale("BUY", draw_room_atr=2.0), (1.0, ""))
        self.assertEqual(ict_scale("BUY", bias="short", confidence=0.8,
                                   opposing="a wall")[0], 0.5,
                         "the strongest warning wins, never a product")

    def test_an_unfilled_bearish_fvg_overhead_is_a_wall(self):
        from bot_program.smart_money import ict_read
        rows = [(110, 111, 109, 110, 0)] * 30
        rows += [(110, 110.5, 107, 107.5, 0),    # i-1: low 107
                 (107.5, 107.6, 104, 104.2, 0),  # i: the displacement
                 (104.2, 105.5, 103.5, 105, 0)]  # i+1: high 105.5 < 107
        rows += [(105, 105.8, 104.5, 105.2, 0)] * 5
        df = _vdf(rows)
        swings = [{"idx": 10, "type": "H", "price": 111.0},
                  {"idx": 33, "type": "L", "price": 103.5}]
        r = ict_read(df, swings, "BUY", 2.0, 105.2)
        self.assertEqual(r["opposing"],
                         "an unfilled bearish FVG 105.5-107 on the way up")
        self.assertEqual((r["bias"], r["zone"]), (None, "discount"))
        self.assertEqual(r["scale"], 0.75)
        self.assertEqual(r["draw"], {"price": 111.0, "touches": 1})
        self.assertEqual(r["draw_room_atr"], 2.9)
        s = ict_read(df, swings, "SELL", 2.0, 105.2)
        self.assertIsNone(s["opposing"], "a short runs away from it")

    def test_too_few_bars_read_nothing(self):
        from bot_program.smart_money import ict_read
        r = ict_read(_vdf([(1, 2, 0.5, 1, 0)] * 5), [], "BUY", 1.0, 1.0)
        self.assertEqual(r["scale"], 1.0)
        self.assertIn("too few bars", r["why"])


class TheVolumeTests(SimpleTestCase):

    def test_volume_leaning_against_a_buy(self):
        from bot_program.smart_money import PRESSURE_SCALE, volume_read
        rows = []
        for i in range(30):
            up = i % 2 == 0
            rows.append((100, 101, 99, 100.5 if up else 99.5,
                         100 if up else 300))
        df = _vdf(rows)
        r = volume_read(df, "BUY")
        self.assertEqual(r["pressure"], 3.0)
        self.assertEqual(r["scale"], PRESSURE_SCALE)
        self.assertEqual(volume_read(df, "SELL")["scale"], 1.0)

    def test_a_feed_without_volume_reads_nothing(self):
        from bot_program.smart_money import volume_read
        r = volume_read(_vdf([(100, 101, 99, 100, 0)] * 30), "BUY")
        self.assertEqual((r["scale"], r["pressure"]), (1.0, None))
        self.assertIn("no volume", r["why"])

    def test_a_thin_sweep_is_a_weaker_grab(self):
        from bot_program.smart_money import (AGAINST_SWEEP_SCALE,
                                             THIN_SWEEP_SCALE, sweep_read)
        rows = [(100, 101, 99, 100, 1000)] * 30
        last = (100, 100.5, 99.5, 100, 1000)
        heavy = rows[:-2] + [(100, 104, 99.5, 100.2, 3000), last]
        thin = rows[:-2] + [(100, 104, 99.5, 100.2, 300), last]
        swings = [{"idx": 10, "type": "H", "price": 102.0}]
        self.assertEqual(sweep_read(_vdf(heavy), swings, "BUY", 2.0)["scale"],
                         AGAINST_SWEEP_SCALE)
        r = sweep_read(_vdf(thin), swings, "BUY", 2.0)
        self.assertEqual(r["scale"], THIN_SWEEP_SCALE)
        self.assertIn("thin volume", r["why"])
        # the bar still forming: its volume is partial, never "thin"
        forming = rows[:-1] + [(100, 104, 99.5, 100.2, 300)]
        self.assertEqual(sweep_read(_vdf(forming), swings, "BUY",
                                    2.0)["scale"], AGAINST_SWEEP_SCALE)


class ThePoolTests(SimpleTestCase):

    def test_equal_lows_are_a_crowd_level(self):
        from bot_program.smart_money import crowd_levels
        df = _df(_flat(40, 100.0))
        swings = [{"idx": 10, "type": "L", "price": 97.40},
                  {"idx": 20, "type": "L", "price": 97.42}]
        kinds = [k for _p, k in crowd_levels("BUY", 100.0, 97.0, 2.0, df,
                                             swings)]
        self.assertIn("equal lows (2 touches)", kinds)



# ── 9. the review, 2026-10-02 ─────────────────────────────────────────────

class TheReviewTests(SimpleTestCase):

    def test_a_level_already_traded_through_is_neither_swept_nor_crowded(self):
        from bot_program.smart_money import crowd_levels, sweep_read
        rows = _flat(30, 100.0)
        rows[15] = (100, 110.0, 99, 100)          # trades through 102 early
        rows[-1] = (100.0, 104.0, 99.5, 100.2)
        swings = [{"idx": 10, "type": "H", "price": 102.0}]
        self.assertEqual(sweep_read(_df(rows), swings, "BUY", 2.0)["scale"],
                         1.0, "the stops at 102 were gone at bar 15")
        lows = _flat(30, 100.0)
        lows[15] = (100, 101, 90.0, 100)          # takes the 97.4 low
        kinds = [k for _p, k in crowd_levels(
            "BUY", 100.0, 97.0, 2.0, _df(lows),
            [{"idx": 10, "type": "L", "price": 97.4}])]
        self.assertNotIn("swing low", kinds)

    def test_an_entry_inside_an_opposing_fvg_is_flagged(self):
        from bot_program.smart_money import ict_read
        rows = [(110, 111, 109, 110, 0)] * 30
        rows += [(110, 110.5, 107, 107.5, 0),
                 (107.5, 107.6, 104, 104.2, 0),
                 (104.2, 105.5, 103.5, 105, 0)]
        rows += [(105, 105.8, 104.5, 105.2, 0)] * 5
        df = _vdf(rows)
        swings = [{"idx": 10, "type": "H", "price": 111.0},
                  {"idx": 33, "type": "L", "price": 103.5}]
        r = ict_read(df, swings, "BUY", 2.0, 106.0)
        self.assertIn("bearish FVG", r["opposing"])

    def test_a_draw_already_reached_leaves_no_room(self):
        from bot_program.smart_money import ict_read
        rows = [(100, 101, 99, 100, 0)] * 40
        rows[20] = (100, 104.0, 99, 100, 0)       # an untaken high at 104
        df = _vdf(rows)
        swings = [{"idx": 20, "type": "H", "price": 104.0}]
        r = ict_read(df, swings, "BUY", 2.0, 104.5)
        self.assertEqual(r["draw_room_atr"], 0.0)
        self.assertEqual(r["scale"], 0.75)

    def test_a_far_percentage_stop_still_sees_its_round_number(self):
        from bot_program.smart_money import crowd_levels
        levels = crowd_levels("BUY", 150.0, 147.0, 0.029)
        self.assertIn((147.0, "round number"), levels)

    def test_the_bars_come_labelled(self):
        from bot_program.smart_money import _bars
        df = _df(_flat(10, 100.0))
        with patch("signals.smc.dataframe.load_ohlcv", return_value=df), \
                patch("signals.smc.pivots.get_swings",
                      return_value=[{"idx": 2, "type": "H", "price": 1.0},
                                    {"idx": 5, "type": "H", "price": 2.0}]):
            _df_, swings = _bars("X", "4h")
        self.assertEqual([s["label"] for s in swings], ["H", "HH"])


class TheCotOpenInterestTests(TestCase):

    def test_a_newest_report_without_open_interest_is_unread(self):
        from bot_program.smart_money import cot_read
        TheCotReadTests._reports(self, "EURUSD", 60)
        from scraping.models import COTReport
        newest = COTReport.objects.order_by("-report_date").first()
        newest.open_interest = 0
        newest.save()
        r = cot_read("EURUSD", "BUY")
        self.assertEqual(r["scale"], 1.0)
        self.assertIn("no open interest", r["why"])



class TheCareReviewTests(SimpleTestCase):

    def test_the_read_is_paid_for_only_when_a_lock_could_move(self):
        from bot_program.position_care import plan
        calls = []

        def crowd():
            calls.append(1)
            return {"atr": 2.0, "levels": [(102.2, "swing low")]}

        plan(_held(peak=100.5), 100.5, crowd=crowd)       # mfe 0.25R
        self.assertEqual(calls, [])
        r = plan(_held(), 104.0, crowd=crowd)
        self.assertEqual(calls, [1])
        self.assertEqual(r["care"]["soft_stop"], 101.2)

    def test_a_lock_keeps_the_round_trip_paid(self):
        from bot_program.position_care import plan
        p = _held(peak=102.4)
        p.metadata["cost_fraction_charged"] = 0.002          # 0.2 on 100
        crowd = {"atr": 2.0, "levels": [(101.0, "round number")]}
        r = plan(p, 102.4, crowd=crowd)
        self.assertGreaterEqual(r["care"]["soft_stop"], 100.2)

    def test_the_weekend_lock_guards_a_gap_and_does_not_move(self):
        from bot_program.position_care import CROWD_MOVABLE
        self.assertNotIn("weekend lock", CROWD_MOVABLE)


class TheCareOptionsTests(TestCase):

    def test_an_options_row_gets_no_crowd_read(self):
        from bot_program import position_care
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.update_or_create(
            key="aragorn", defaults={"name": "a", "category": "system",
                                     "is_enabled": True})
        _switch()
        bot = SimpleNamespace(cfg=SimpleNamespace(), asset_class="options",
                              _instrument_class=lambda s: "options")
        trade = _held(entry=20.0, stop=10.0, peak=35.5)
        trade.symbol, trade.id, trade.pk, trade.rule_name = "AAPL", 1, 1, "r"
        trade.asset_class = "options"
        with patch("bot_program.smart_money.care_levels") as lv, \
                patch("bot_program.position_care._save_care") as save:
            position_care.care(bot, trade, 33.0, None)
        lv.assert_not_called()
        self.assertEqual(save.call_args.args[1]["soft_stop"], 25.5)


class TheFeeCheckTests(TestCase):
    """Review, 2026-10-02: a moved stop that the venue's flat fee refuses at
    the final size goes back to the computed stop, resized."""

    def test_the_stop_goes_back_when_the_fee_refuses_it(self):
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotConfig
        user = User.objects.create_user("sm_fee", password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="F", enabled=True,
            mode="live", symbols=["X"], capital=Decimal("10000"))
        bot = StockBot(cfg)
        sizing = {"qty": 10.0, "stop": 97.0}
        meta = {"smart_money": {"original_stop": 98.0, "stop_moved": True,
                                "scale": 1.0}}
        dec = SimpleNamespace(direction="BUY", rule_name="r")
        stage = {"force_paper": False, "live_size_factor": 1.0}
        with patch.object(bot, "_venue_fee_refusal",
                          return_value=(0.01, "reward:risk falls")), \
                patch.object(bot, "_size_for_entry",
                             return_value={"qty": 15.0, "stop": 98.0}):
            qty, sl, sz, lm = bot._smart_money_fee_check(
                None, "X", dec, stage, {"scale": 1.0}, qty=5.0, price=100.0,
                tp=106.0, sl=97.0, sizing=sizing, level_meta=meta, charge={})
        self.assertEqual(sl, 98.0)
        self.assertAlmostEqual(qty, 15.0 * 0.5 * 0.75,
                               msg="same multipliers, and the crowded scale")
        self.assertFalse(lm["smart_money"]["stop_moved"])
        self.assertIn("venue fee", lm["smart_money"]["reverted"])
        with patch.object(bot, "_venue_fee_refusal", return_value=(0.0, "")):
            kept = bot._smart_money_fee_check(
                None, "X", dec, stage, {"scale": 1.0}, qty=5.0, price=100.0,
                tp=106.0, sl=97.0, sizing=sizing, level_meta=meta, charge={})
        self.assertEqual(kept[:2], (5.0, 97.0))

    def test_no_room_means_no_move(self):
        from bot_program.smart_money import stop_beyond_the_crowd
        r = stop_beyond_the_crowd("BUY", 100.0, 97.0, 2.0,
                                  [(97.4, "swing low")], max_distance=0.0)
        self.assertFalse(r["moved"])
        self.assertTrue(r["crowded"], "left in the zone, and said")
        self.assertEqual(r["stop"], 97.0)
        self.assertIn("the plan has no room to widen it", r["why"])
        tiny = stop_beyond_the_crowd("BUY", 1e-5, 0.97e-5, 2e-7,
                                     [(0.974e-5, "swing low")],
                                     max_distance=0.03e-5)
        self.assertFalse(tiny["moved"], "a relative tolerance at micro prices")



class TheWordsTests(SimpleTestCase):

    def test_the_strongest_reason_is_said_once_with_its_size(self):
        from bot_program.smart_money import entry_read
        rows = _flat(30, 100.0)
        rows[-1] = (100.0, 104.0, 99.5, 100.2)
        df = _df(rows)
        swings = [{"idx": 10, "type": "H", "price": 102.0}]
        with patch("bot_program.smart_money.cot_read",
                   return_value={"scale": 1.0, "why": ""}):
            r = entry_read("X", "BUY", 100.2, 97.2, atr=2.0,
                           bars=(df, swings))
        self.assertEqual(r["scale"], 0.5)
        self.assertTrue(r["why"][0].startswith("size x0.5: a fresh sweep"))
        self.assertEqual(sum(1 for w in r["why"] if "sweep of the highs" in w),
                         1)
