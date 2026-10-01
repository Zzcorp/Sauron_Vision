"""THE STEWARD, THE CRISIS MODE AND THE POSITION CARE (2026-10-02).

The operator: "we are getting plundered ... remove the strategies not
working, promote new proven ones, make it pretty autonomous but still
maintainable by Gandalf or me", "more resilience in dark waters", "a
crash is coming ... make the most out of crisis". He chose the balanced
thresholds, a steward that acts on its own, and a "smart mix" leverage.

Run with:  python manage.py test tests.test_steward
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_risk_limits_bind import _config


def _switch(key, on=True):
    from core.platform_control import PlatformComponent
    PlatformComponent.objects.update_or_create(
        key=key, defaults={"name": key, "category": "system",
                           "is_enabled": on})


def _closed(cfg, r, *, paper=False, rule="golden_cross", days_ago=1.0,
            pnl=None, cls=None):
    from bot_program.models import AssetBotTrade
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=cls or cfg.asset_class, symbol="BTCUSD",
        side="BUY", qty=Decimal("1"), entry_price=Decimal("100"),
        stop_loss=Decimal("99"), status="CLOSED", paper=paper,
        pnl=Decimal(str(pnl if pnl is not None else r)), rule_name=rule,
        realized_r=r)
    t.closed_at = timezone.now() - timedelta(days=days_ago)
    t.save(update_fields=["closed_at"])
    return t


# ── the numbers ──────────────────────────────────────────────────────────

class TheStatsTests(SimpleTestCase):

    def test_expectancy_floor_streak_and_profit_factor(self):
        from bot_program.steward import stats
        s = stats([(-1.0, -10), (-1.0, -10), (2.0, 20), (1.0, None)])
        self.assertEqual(s["n"], 4)
        self.assertEqual(s["expectancy"], 0.25)
        self.assertEqual(s["streak"], 2, "the newest two lost")
        self.assertEqual(s["money"], 0.0, "an unmeasured pnl is left out")
        self.assertEqual(s["profit_factor"], 1.5)
        self.assertLess(s["lower"], s["expectancy"])

    def test_the_balanced_bench_and_proof(self):
        from bot_program.steward import bench_reason, proven_reason, stats
        self.assertIn("expectancy", bench_reason(stats([(-0.3, -3)] * 8)))
        self.assertEqual(bench_reason(stats([(0.5, 5)] + [(-0.3, -3)] * 6)),
                         "", "7 closes, the newest a win: too early, no streak")
        self.assertIn("all lost", bench_reason(stats([(-1.0, -1)] * 4)))
        good = [(1.0, 10), (-1.0, -10), (1.5, 15)] * 7       # n 21
        self.assertIn("paper proven", proven_reason(stats(good)))
        self.assertEqual(proven_reason(stats(good[:19])), "", "under 20")
        flat = [(0.5, 5), (-0.4, -4)] * 11
        self.assertEqual(proven_reason(stats(flat)), "",
                         "+0.05R is not the +0.15R the balanced rule asks")


class ThePassTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user("stw_u", password="x")
        self.cfg = _config(self.user, symbols=["BTCUSD"], mode="live")
        _switch("steward")

    def test_a_losing_live_pair_is_benched_and_journaled(self):
        from bot_program.steward import evaluate, pair_policy
        from bot_program.steward_models import PairVerdict, StewardAction
        for _ in range(8):
            _closed(self.cfg, -0.4)
        moves = evaluate(apply=False)
        self.assertEqual([(m["kind"], m["rule"]) for m in moves],
                         [("bench", "golden_cross")])
        self.assertFalse(PairVerdict.objects.exists(), "a plan writes nothing")
        evaluate(apply=True)
        v = PairVerdict.objects.get()
        self.assertEqual((v.state, v.asset_class), ("bench", "crypto"))
        self.assertTrue(StewardAction.objects.filter(kind="bench").exists())
        pol = pair_policy("golden_cross", "crypto")
        self.assertTrue(pol["force_paper"])
        self.assertIn("bench", pol["reason"])

    def test_a_pinned_pair_is_never_moved(self):
        from bot_program.steward import evaluate, set_by_operator
        set_by_operator("golden_cross", "crypto", "live", by="gandalf",
                        pin=True)
        for _ in range(8):
            _closed(self.cfg, -0.4)
        self.assertEqual(evaluate(apply=True), [])

    def test_probation_graduates_or_goes_back_to_the_bench(self):
        from bot_program.steward import evaluate, set_by_operator
        from bot_program.steward_models import PairVerdict
        set_by_operator("golden_cross", "crypto", "probation", by="t")
        PairVerdict.objects.update(since=timezone.now() - timedelta(days=5))
        for _ in range(10):
            _closed(self.cfg, 0.3)
        evaluate(apply=True)
        self.assertEqual(PairVerdict.objects.get().state, "live")
        set_by_operator("golden_cross", "crypto", "probation", by="t")
        PairVerdict.objects.update(since=timezone.now() - timedelta(hours=1))
        for _ in range(3):
            _closed(self.cfg, -1.0, days_ago=0.01)
        evaluate(apply=True)
        self.assertEqual(PairVerdict.objects.get().state, "bench")

    def test_the_bench_returns_on_fresh_paper_proof_after_its_dwell(self):
        from bot_program.steward import evaluate, set_by_operator
        from bot_program.steward_models import PairVerdict
        set_by_operator("golden_cross", "crypto", "bench", by="t")
        PairVerdict.objects.update(since=timezone.now() - timedelta(days=3))
        for i in range(21):
            _closed(self.cfg, [1.0, -1.0, 1.5][i % 3], paper=True,
                    days_ago=1)
        self.assertEqual(evaluate(apply=False), [], "3 days: still dwelling")
        PairVerdict.objects.update(since=timezone.now() - timedelta(days=8))
        evaluate(apply=True)
        self.assertEqual(PairVerdict.objects.get().state, "probation")

    def test_a_proven_pair_takes_its_paper_rule_live_for_its_class_alone(self):
        from bot_program.steward import evaluate, pair_policy
        from bot_program.steward_models import PairVerdict
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="vol_squeeze",
                                   promotion_stage="paper")
        for i in range(21):
            _closed(self.cfg, [1.0, -1.0, 1.5][i % 3], paper=True,
                    rule="vol_squeeze")
        evaluate(apply=True)
        self.assertEqual(RuleControl.objects.get(
            rule_name="vol_squeeze").promotion_stage, "live_full")
        self.assertEqual(PairVerdict.objects.get(
            rule_name="vol_squeeze", asset_class="crypto").state, "probation")
        self.assertEqual(PairVerdict.objects.get(
            rule_name="vol_squeeze", asset_class="*").state, "bench")
        self.assertEqual(pair_policy("vol_squeeze", "crypto")["size"], 0.25)
        self.assertTrue(pair_policy("vol_squeeze", "forex")["force_paper"],
                        "its other classes stay on paper")

    def test_a_live_pair_without_real_evidence_is_benched_on_its_paper_loss(self):
        from bot_program.steward import evaluate
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="golden_cross",
                                   promotion_stage="live_full")
        for i in range(22):
            _closed(self.cfg, [-0.6, -0.4, 0.2][i % 3], paper=True)
        _closed(self.cfg, 0.5)                       # one real close
        moves = evaluate(apply=False)
        self.assertEqual([(m["kind"], m["stats"]["live_n"]) for m in moves],
                         [("bench", 1)])
        self.assertIn("paper record loses", moves[0]["reason"])
        for _ in range(8):
            _closed(self.cfg, 0.5)
        self.assertEqual(evaluate(apply=False), [],
                         "with 8 real closes the real record speaks")

    def test_the_switch_off_reads_live_at_full_size(self):
        from bot_program.steward import pair_policy, set_by_operator
        set_by_operator("golden_cross", "crypto", "bench", by="t")
        _switch("steward", on=False)
        self.assertEqual(pair_policy("golden_cross", "crypto"),
                         {"state": "live", "force_paper": False, "size": 1.0,
                          "reason": ""})


# ── the posture ──────────────────────────────────────────────────────────

class TheClassifierTests(SimpleTestCase):

    def test_what_each_entry_does_in_a_crash(self):
        from bot_program.posture import classify
        cases = [("AAPL", "stock", "BUY", "risk_on_long"),
                 ("SPX500", "index", "SELL", "risk_on_short"),
                 ("XAUUSD", "commodity", "BUY", "haven_long"),
                 ("GLDM", "etf", "SELL", "haven_short"),
                 ("USDJPY", "forex", "SELL", "haven_long"),
                 ("AUDUSD", "forex", "SELL", "haven_long"),
                 ("EURUSD", "forex", "BUY", "risk_on_long"),
                 ("EURGBP", "forex", "BUY", "neutral"),
                 ("BTCUSD", "crypto", "BUY", "risk_on_long")]
        for sym, cls, side, want in cases:
            self.assertEqual(classify(sym, cls, side), want, (sym, side))

    def test_the_smart_mix_leverage(self):
        from bot_program.posture import leverage_cap
        self.assertIsNone(leverage_cap("calm", "risk_on_long", 20))
        self.assertEqual(leverage_cap("stressed", "risk_on_long", 20), 10)
        self.assertEqual(leverage_cap("crisis", "risk_on_short", 20), 10,
                         "riding the crash keeps half the ceiling")
        self.assertEqual(leverage_cap("crisis", "risk_on_long", 20), 1)
        self.assertEqual(leverage_cap("crisis", "neutral", 20), 2)
        self.assertEqual(leverage_cap("recovery", "risk_on_long", 5), 2)

    def test_recovery_brings_risk_on_longs_back_in_steps(self):
        from bot_program.posture import posture_rule
        sizes = [posture_rule("recovery", "risk_on_long",
                              recovery_days=d)["size"] for d in (0, 2.5, 5)]
        self.assertEqual(sizes, [0.33, 0.5, 0.75])
        self.assertFalse(posture_rule("crisis", "risk_on_long")["live"])


# ── the market's stress ──────────────────────────────────────────────────

class TheScoreTests(SimpleTestCase):

    def test_a_crash_scores_a_crisis_and_a_quiet_market_calm(self):
        from bot_program.market_stress import raw_level, score
        crash = {"index_drawdown": 0.14, "index_5d": -0.07,
                 "realized_vol": 2.6, "vix": 41.0, "hy_spread": 6.5}
        sc, subs = score(crash)
        self.assertEqual(raw_level(sc), "crisis")
        quiet = {"index_drawdown": 0.01, "index_5d": 0.01,
                 "realized_vol": 0.9, "vix": 14.0}
        self.assertEqual(raw_level(score(quiet)[0]), "calm")
        self.assertIsNone(score({"hy_spread": 9.0})[0],
                          "no index and no VIX: unmeasured")

    def test_up_at_once_down_slowly_and_a_crisis_ends_in_recovery(self):
        from bot_program.market_stress import next_level
        now = timezone.now()
        R = lambda lvl, raw, h: SimpleNamespace(level=lvl, raw_level=raw,  # noqa: E731
                                                at=now - timedelta(hours=h))
        self.assertEqual(next_level("calm", 60, "crisis", {}, [], now)[0],
                         "crisis")
        self.assertEqual(next_level("crisis", 40, "stressed",
                                    {"index_5d": 0.02}, [], now)[0],
                         "recovery")
        self.assertEqual(next_level("crisis", 40, "stressed",
                                    {"index_5d": -0.01}, [], now)[0],
                         "crisis", "still falling: the crisis holds")
        self.assertEqual(next_level("stressed", 10, "calm", {},
                                    [R("stressed", "calm", 1)], now)[0],
                         "stressed", "one calm hour is not calm")
        self.assertEqual(next_level("stressed", 10, "calm", {},
                                    [R("stressed", "calm", 5)], now)[0],
                         "calm")
        self.assertEqual(next_level("stressed", None, "", {}, [], now)[0],
                         "stressed", "unmeasured holds the level")


class TheReadingTests(TestCase):

    def _bars(self, symbol, closes):
        from instruments.models import Instrument
        from market_data.models import PriceData
        inst = Instrument.objects.create(symbol=symbol, name=symbol,
                                         asset_class="index")
        start = timezone.now() - timedelta(days=len(closes) + 1)
        PriceData.objects.bulk_create([PriceData(
            instrument=inst, timeframe="1d", timestamp=start + timedelta(days=i),
            open=c, high=c, low=c, close=c, source="t")
            for i, c in enumerate(closes)])

    def test_an_index_down_hard_reads_a_crisis_and_tells_the_alarm(self):
        from bot_program.market_stress import current, evaluate
        _switch("crisis_mode")
        closes = [100.0 + (i % 3) * 0.3 for i in range(240)]
        closes += [100 - 1.5 * i for i in range(1, 11)]      # -15% in 10 days
        self._bars("SPX500", closes)
        with patch("bot_program.alarm.send_alarm") as alarm:
            from bot_program.steward_models import MarketStressReading
            MarketStressReading.objects.create(level="calm", raw_level="calm",
                                               score=5)
            r = evaluate()
        self.assertEqual(r.level, "crisis", r.reasons)
        self.assertGreaterEqual(r.components["raw"]["index_drawdown"], 0.14)
        alarm.assert_called_once()
        self.assertIn("CRISIS", alarm.call_args.args[0])
        self.assertEqual(current()["level"], "crisis")

    def test_the_operator_override_wins_until_it_expires(self):
        from bot_program.market_stress import current, set_override
        set_override("crisis", hours=2, by="gandalf")
        self.assertEqual(current()["level"], "crisis")
        set_override("auto", by="gandalf")
        self.assertEqual(current()["level"], "calm")
        with self.assertRaises(ValueError):
            set_override("panic")


# ── the entry path ───────────────────────────────────────────────────────

class TheEntryWiringTests(TestCase):

    def setUp(self):
        from bot_program.asset_engine.base import make_bot
        self.user = get_user_model().objects.create_user("stw_e", password="x")
        self.bot = make_bot(_config(self.user, symbols=["BTCUSD"],
                                    mode="live"))
        self.stage = {"may_trade": True, "force_paper": False,
                      "live_size_factor": 1.0, "stage": "live_full",
                      "reason": ""}
        self.dec = SimpleNamespace(rule_name="golden_cross", direction="BUY")

    def test_a_benched_pair_goes_to_paper_and_probation_trades_a_quarter(self):
        from bot_program.steward import set_by_operator
        _switch("steward")
        set_by_operator("golden_cross", "crypto", "bench", by="t")
        stage, meta = self.bot._steward_and_posture("BTCUSD", self.dec,
                                                     self.stage)
        self.assertTrue(stage["force_paper"])
        self.assertEqual(meta["steward"]["state"], "bench")
        set_by_operator("golden_cross", "crypto", "probation", by="t")
        stage, _ = self.bot._steward_and_posture("BTCUSD", self.dec,
                                                  self.stage)
        self.assertEqual((stage["force_paper"], stage["live_size_factor"]),
                         (False, 0.25))

    def test_a_crisis_sends_a_risk_on_long_to_paper_and_keeps_a_short(self):
        from bot_program.market_stress import set_override
        _switch("crisis_mode")
        set_override("crisis", by="t")
        stage, meta = self.bot._steward_and_posture("BTCUSD", self.dec,
                                                     self.stage)
        self.assertTrue(stage["force_paper"])
        self.assertIn("crisis mode", stage["reason"])
        short = SimpleNamespace(rule_name="golden_cross", direction="SELL")
        stage, meta = self.bot._steward_and_posture("BTCUSD", short,
                                                     self.stage)
        self.assertFalse(stage["force_paper"])
        self.assertEqual(meta["posture"]["kind"], "risk_on_short")

    def test_both_switches_off_change_nothing(self):
        from bot_program.market_stress import set_override
        set_override("crisis", by="t")
        stage, meta = self.bot._steward_and_posture("BTCUSD", self.dec,
                                                     self.stage)
        self.assertEqual((stage, meta), (self.stage, {}))

    def test_a_paper_config_is_never_touched(self):
        from bot_program.market_stress import set_override
        _switch("crisis_mode")
        set_override("crisis", by="t")
        self.bot.cfg.mode = "paper"
        stage, meta = self.bot._steward_and_posture("BTCUSD", self.dec,
                                                     self.stage)
        self.assertEqual(meta, {})
        self.assertFalse(stage["force_paper"])

    def test_the_posture_caps_a_typed_leverage(self):
        from bot_program.market_stress import set_override
        _switch("crisis_mode")
        set_override("stressed", by="t")
        self.assertEqual(self.bot._posture_leverage("BTCUSD", "BUY", 2)[0], 1)
        set_override("calm", by="t")
        self.assertEqual(self.bot._posture_leverage("BTCUSD", "BUY", 2),
                         (2, ""))

    def test_the_hooks_sit_where_they_must(self):
        import inspect

        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.propose_entry)
        self.assertLess(src.index("stage_policy(decision.rule_name)"),
                        src.index("self._steward_and_posture("))
        self.assertLess(src.index("self._steward_and_posture("),
                        src.index("self._size_for_entry("))
        lev = inspect.getsource(AssetBot._order_leverage)
        self.assertLess(lev.index("judge_order_leverage("),
                        lev.index("self._posture_leverage("))
        self.assertLess(lev.index("self._posture_leverage("),
                        lev.index("self._instrument_leverage_check("))
        mp = inspect.getsource(AssetBot.manage_positions)
        self.assertLess(mp.index("_care(self, trade, price, client)"),
                        mp.index("if protected:\n"))


# ── the position care ────────────────────────────────────────────────────

def _row(side="BUY", entry=100.0, stop=98.0, hours=1, cls="crypto",
         care=None, lev=None, paper=False):
    meta = {"initial_stop_loss": stop}
    if care:
        meta["care"] = care
    if lev:
        meta["leverage"] = lev
    return SimpleNamespace(
        side=side, entry_price=Decimal(str(entry)), stop_loss=Decimal(str(stop)),
        metadata=meta, asset_class=cls, paper=paper,
        opened_at=timezone.now() - timedelta(hours=hours))


class TheCarePlanTests(SimpleTestCase):

    def test_breakeven_then_trail_tighten_only(self):
        from bot_program.position_care import plan
        p = plan(_row(), 102.2)                     # +1.1R
        self.assertEqual(p["action"], "hold")
        self.assertAlmostEqual(p["care"]["soft_stop"], 100.2)
        self.assertEqual(p["care"]["soft_why"], "breakeven")
        p2 = plan(_row(care=p["care"]), 104.0)      # +2R: trail 1R behind
        self.assertAlmostEqual(p2["care"]["soft_stop"], 102.0)
        p3 = plan(_row(care=p2["care"]), 103.0)     # back to +1.5R
        self.assertAlmostEqual(p3["care"]["soft_stop"], 102.0, msg="never loosens")
        self.assertEqual(p3["action"], "hold")
        p4 = plan(_row(care=p3["care"]), 101.9)
        self.assertEqual((p4["action"], p4["reason"]), ("close", "SL"))
        self.assertEqual(p4["care"]["exit"], "trail")

    def test_a_short_trails_downward(self):
        from bot_program.position_care import plan
        p = plan(_row(side="SELL", stop=102.0), 96.0)   # +2R
        self.assertAlmostEqual(p["care"]["soft_stop"], 98.0)
        self.assertEqual(plan(_row(side="SELL", stop=102.0, care=p["care"]),
                              98.1)["action"], "close")

    def test_a_crisis_cuts_a_live_risk_on_long_to_half_its_risk(self):
        from bot_program.position_care import plan
        p = plan(_row(), 98.9, posture_level="crisis", kind="risk_on_long",
                 live=True)                          # -0.55R
        self.assertEqual(p["action"], "close")
        self.assertEqual(p["care"]["exit"], "crisis")
        self.assertEqual(plan(_row(), 98.9, posture_level="crisis",
                              kind="risk_on_short", live=True)["action"],
                         "hold", "a position riding the crash is left alone")

    def test_a_manual_position_keeps_its_profit_guards_and_no_cut(self):
        from bot_program.position_care import plan
        p = plan(_row(), 98.9, posture_level="crisis", kind="risk_on_long",
                 live=True, manual=True)
        self.assertEqual(p["action"], "hold", "no crisis cut on a manual row")
        self.assertEqual(plan(_row(hours=500, cls="stock"), 100.1,
                              manual=True)["action"], "hold",
                         "no no-progress exit either")
        p = plan(_row(), 102.2, manual=True)
        self.assertEqual(p["care"]["soft_why"], "breakeven")

    def test_the_weekend_cut_and_no_progress(self):
        from bot_program.position_care import plan
        friday = datetime(2026, 10, 2, 20, 0, tzinfo=dt_tz.utc)
        p = plan(_row(lev=10, cls="forex"), 99.5, now=friday, live=True)
        self.assertEqual((p["action"], p["care"]["exit"]),
                         ("close", "weekend cut"))
        self.assertEqual(plan(_row(lev=10, cls="crypto"), 99.5, now=friday,
                              live=True)["action"], "hold",
                         "crypto never shuts")
        stale = _row(hours=130, cls="stock")
        p = plan(stale, 100.2)
        self.assertEqual((p["action"], p["reason"]), ("close", "TIME"))


class TheCareTests(TestCase):

    def test_care_is_off_with_the_steward_and_closes_through_the_bot(self):
        from bot_program.models import AssetBotTrade
        from bot_program.position_care import care
        user = get_user_model().objects.create_user("stw_c", password="x")
        cfg = _config(user, symbols=["BTCUSD"], mode="live")
        t = AssetBotTrade.objects.create(
            config=cfg, asset_class="crypto", symbol="BTCUSD", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"),
            stop_loss=Decimal("98"), status="OPEN", paper=False,
            metadata={"initial_stop_loss": 98.0,
                      "care": {"peak": 104.0, "soft_stop": 102.0,
                               "soft_why": "trail"}})
        bot = MagicMock()
        bot._close_trade.return_value = True
        self.assertFalse(care(bot, t, Decimal("101.5"), None))
        bot._close_trade.assert_not_called()
        _switch("steward")
        self.assertTrue(care(bot, t, Decimal("101.5"), None))
        bot._close_trade.assert_called_once()
        self.assertEqual(bot._close_trade.call_args.kwargs["reason"], "SL")
        t.refresh_from_db()
        self.assertEqual(t.metadata["care_exit"], "trail")
        from bot_program.steward_models import StewardAction
        self.assertIn("REAL MONEY", StewardAction.objects.get(
            kind="care_close").detail)


# ── the switches, the beat, the command ──────────────────────────────────

class TheControlsTests(TestCase):

    def test_two_live_money_switches_seeded_off_and_never_bulk_armed(self):
        from core.platform_control import (BULK_ENABLE_EXEMPT,
                                           DEFAULT_COMPONENTS,
                                           LIVE_MONEY_SWITCHES)
        rows = {c["key"]: c for c in DEFAULT_COMPONENTS}
        for key in ("steward", "crisis_mode"):
            self.assertIn(key, rows)
            self.assertLess(len(rows[key]["description"]), 300)
            self.assertIn(key, LIVE_MONEY_SWITCHES)
            self.assertIn(key, BULK_ENABLE_EXEMPT)

    def test_the_beat_runs_the_three_tasks(self):
        from config.celery import app
        tasks = {v["task"] for v in app.conf.beat_schedule.values()}
        for name in ("read_market_stress", "run_steward",
                     "steward_daily_report"):
            self.assertIn(f"bot_program.tasks.{name}", tasks)

    def test_the_command_shows_plans_and_overrides(self):
        out = StringIO()
        call_command("steward", stdout=out)
        self.assertIn("Steward: OFF", out.getvalue())
        out = StringIO()
        call_command("steward", "bench", "golden_cross", "forex", "--pin",
                     "--by", "gandalf", stdout=out)
        self.assertIn("golden_cross/forex: bench (pinned)", out.getvalue())
        out = StringIO()
        call_command("steward", "posture", "stressed", "--hours", "3",
                     stdout=out)
        self.assertIn("stressed", out.getvalue())
        out = StringIO()
        call_command("steward", "journal", stdout=out)
        self.assertIn("operator_bench", out.getvalue())
        out = StringIO()
        call_command("steward", "run", stdout=out)
        self.assertIn("Nothing to move.", out.getvalue())
