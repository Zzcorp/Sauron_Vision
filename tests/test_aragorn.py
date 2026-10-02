"""ARAGORN, THE CRISIS MODE AND THE POSITION CARE (2026-10-02).

The operator: "we are getting plundered ... remove the strategies not
working, promote new proven ones, make it pretty autonomous but still
maintainable by Gandalf or me", "more resilience in dark waters", "a
crash is coming ... make the most out of crisis". He chose the balanced
thresholds, Aragorn that acts on its own, and a "smart mix" leverage.

Run with:  python manage.py test tests.test_aragorn
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
        from bot_program.aragorn import stats
        s = stats([(-1.0, -10), (-1.0, -10), (2.0, 20), (1.0, None)])
        self.assertEqual(s["n"], 4)
        self.assertEqual(s["expectancy"], 0.25)
        self.assertEqual(s["streak"], 2, "the newest two lost")
        self.assertEqual(s["money"], 0.0, "an unmeasured pnl is left out")
        self.assertEqual(s["profit_factor"], 1.5)
        self.assertLess(s["lower"], s["expectancy"])

    def test_the_balanced_bench_and_proof(self):
        from bot_program.aragorn import bench_reason, proven_reason, stats
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
        _switch("aragorn")

    def test_a_losing_live_pair_is_benched_and_journaled(self):
        from bot_program.aragorn import evaluate, pair_policy
        from bot_program.aragorn_models import PairVerdict, AragornAction
        for _ in range(8):
            _closed(self.cfg, -0.4)
        moves = evaluate(apply=False)
        self.assertEqual([(m["kind"], m["rule"]) for m in moves],
                         [("bench", "golden_cross")])
        self.assertFalse(PairVerdict.objects.exists(), "a plan writes nothing")
        evaluate(apply=True)
        v = PairVerdict.objects.get()
        self.assertEqual((v.state, v.asset_class), ("bench", "crypto"))
        self.assertTrue(AragornAction.objects.filter(kind="bench").exists())
        pol = pair_policy("golden_cross", "crypto")
        self.assertTrue(pol["force_paper"])
        self.assertIn("bench", pol["reason"])

    def test_a_pinned_pair_is_never_moved(self):
        from bot_program.aragorn import evaluate, set_by_operator
        set_by_operator("golden_cross", "crypto", "live", by="gandalf",
                        pin=True)
        for _ in range(8):
            _closed(self.cfg, -0.4)
        self.assertEqual(evaluate(apply=True), [])

    def test_probation_graduates_or_goes_back_to_the_bench(self):
        from bot_program.aragorn import evaluate, set_by_operator
        from bot_program.aragorn_models import PairVerdict
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
        from bot_program.aragorn import evaluate, set_by_operator
        from bot_program.aragorn_models import PairVerdict
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
        from bot_program.aragorn import evaluate, pair_policy
        from bot_program.aragorn_models import PairVerdict
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
        from bot_program.aragorn import evaluate
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

    def test_the_switch_off_stops_the_moves_but_the_verdicts_still_bind(self):
        """OFF must not hand every benched loser back to full-size real
        money (review, 2026-10-02): the verdicts bind; only the moves and
        the care stop."""
        from bot_program.aragorn import evaluate, pair_policy, set_by_operator
        set_by_operator("golden_cross", "crypto", "bench", by="t")
        _switch("aragorn", on=False)
        self.assertTrue(pair_policy("golden_cross", "crypto")["force_paper"])
        self.assertEqual(pair_policy("other_rule", "crypto")["state"], "live")
        set_by_operator("golden_cross", "crypto", "live", by="t")
        self.assertFalse(pair_policy("golden_cross", "crypto")["force_paper"])

    def test_a_graduated_pair_is_judged_on_what_it_did_since(self):
        from bot_program.aragorn import evaluate, set_by_operator
        from bot_program.aragorn_models import PairVerdict
        for _ in range(8):
            _closed(self.cfg, -0.3, days_ago=10)       # the old losses
        set_by_operator("golden_cross", "crypto", "live", by="aragorn")
        PairVerdict.objects.update(since=timezone.now() - timedelta(days=5))
        for _ in range(10):
            _closed(self.cfg, 0.05, days_ago=1)
        self.assertEqual(evaluate(apply=False), [],
                         "the losses before graduation are history")

    def test_a_class_under_the_star_bench_comes_back_on_its_own_proof(self):
        from bot_program.aragorn import evaluate, pair_policy
        from bot_program.aragorn_models import PairVerdict
        PairVerdict.objects.create(
            rule_name="vol_squeeze", asset_class="*", state="bench",
            since=timezone.now() - timedelta(days=9))
        for i in range(21):
            _closed(self.cfg, [1.0, -1.0, 1.5][i % 3], paper=True,
                    rule="vol_squeeze", days_ago=2)
        evaluate(apply=True)
        self.assertEqual(pair_policy("vol_squeeze", "crypto")["state"],
                         "probation")
        self.assertTrue(pair_policy("vol_squeeze", "forex")["force_paper"])

    def test_options_and_the_manual_lane_are_never_judged(self):
        """Every pass, the paper-record one included: on 2026-10-02 the
        first plan on the VPS proposed benching manual_take/forex on its
        paper record (the manual lane's RuleControl row is live_full)."""
        from bot_program.aragorn import evaluate
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="manual_take",
                                   promotion_stage="live_full")
        for _ in range(8):
            _closed(self.cfg, -0.5, rule="manual_take")
            _closed(self.cfg, -0.5, cls="options")
        for _ in range(22):
            _closed(self.cfg, -0.4, rule="manual_take", paper=True)
        self.assertEqual(evaluate(apply=False), [])


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

    def test_calm_returns_on_the_real_fifteen_minute_cadence(self):
        """The review's latch: with readings every 15 min, 4 h of calm
        readings stand a stressed market down; 2 h do not."""
        from bot_program.market_stress import next_level
        now = timezone.now()
        calm = lambda h: [SimpleNamespace(level="stressed", raw_level="calm",  # noqa: E731
                                          score=10, at=now - timedelta(minutes=15 * i))
                          for i in range(1, int(h * 4) + 1)]
        self.assertEqual(next_level("stressed", 10, "calm", {}, calm(2), now)[0],
                         "stressed")
        self.assertEqual(next_level("stressed", 10, "calm", {}, calm(4.25), now)[0],
                         "calm")

    def test_a_recovery_ends_and_a_crisis_eases_without_an_index(self):
        from bot_program.market_stress import next_level
        now = timezone.now()
        self.assertEqual(next_level("recovery", 35, "stressed", {}, [], now,
                                    recovery_started=now - timedelta(days=11))[0],
                         "stressed", "ten days of recovery is enough")
        low = [SimpleNamespace(level="crisis", raw_level="stressed", score=40,
                               at=now - timedelta(minutes=15 * i))
               for i in range(1, 30)]                    # 7 h under 45
        self.assertEqual(next_level("crisis", 40, "stressed", {}, low, now)[0],
                         "recovery", "no index return: the score alone eases it")

    def test_no_crash_is_called_on_the_vix_and_a_label_alone(self):
        from bot_program.market_stress import raw_level, score
        comps = {"vix": 26.0, "brain": {"label": "blow_off",
                                        "confidence": 0.9}}
        sc, _ = score(comps)
        self.assertGreaterEqual(sc, 55)
        self.assertEqual(raw_level(sc, comps), "stressed")
        comps["vix"] = 45.0
        self.assertEqual(raw_level(score(comps)[0], comps), "crisis")


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
            from bot_program.aragorn_models import MarketStressReading
            MarketStressReading.objects.create(level="calm", raw_level="calm",
                                               score=5)
            r = evaluate()
        self.assertEqual(r.level, "crisis", r.reasons)
        self.assertGreaterEqual(r.components["raw"]["index_drawdown"], 0.14)
        alarm.assert_called_once()
        self.assertIn("CRISIS", alarm.call_args.args[0])
        self.assertEqual(current()["level"], "crisis")

    def test_stale_bars_are_not_the_market(self):
        from bot_program.market_stress import read_components
        from instruments.models import Instrument
        from market_data.models import PriceData
        inst = Instrument.objects.create(symbol="SPX500", name="s",
                                         asset_class="index")
        old = timezone.now() - timedelta(days=30)
        PriceData.objects.bulk_create([PriceData(
            instrument=inst, timeframe="1d",
            timestamp=old - timedelta(days=i), open=100, high=100, low=100,
            close=100, source="t") for i in range(100)])
        comps, reasons = read_components()
        self.assertNotIn("index_drawdown", comps)
        self.assertTrue(any("SPX500" in r for r in reasons))

    def test_an_override_is_never_the_state_machine_s_past(self):
        from bot_program.market_stress import evaluate, set_override
        from bot_program.aragorn_models import MarketStressReading
        set_override("crisis", hours=1, by="drill")
        r = evaluate()
        self.assertNotEqual(r.level, "crisis", "unmeasured: the measured "
                            "level is stored, not the drill")
        self.assertEqual(r.override, "crisis")
        self.assertEqual(MarketStressReading.objects.get().level, "calm")

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
        from bot_program.aragorn import set_by_operator
        _switch("aragorn")
        set_by_operator("golden_cross", "crypto", "bench", by="t")
        stage, meta = self.bot._aragorn_and_posture("BTCUSD", self.dec,
                                                     self.stage)
        self.assertTrue(stage["force_paper"])
        self.assertEqual(meta["aragorn"]["state"], "bench")
        set_by_operator("golden_cross", "crypto", "probation", by="t")
        stage, _ = self.bot._aragorn_and_posture("BTCUSD", self.dec,
                                                  self.stage)
        self.assertEqual((stage["force_paper"], stage["live_size_factor"]),
                         (False, 0.25))

    def test_a_crisis_sends_a_risk_on_long_to_paper_and_keeps_a_short(self):
        from bot_program.market_stress import set_override
        _switch("crisis_mode")
        set_override("crisis", by="t")
        stage, meta = self.bot._aragorn_and_posture("BTCUSD", self.dec,
                                                     self.stage)
        self.assertTrue(stage["force_paper"])
        self.assertIn("crisis mode", stage["reason"])
        short = SimpleNamespace(rule_name="golden_cross", direction="SELL")
        stage, meta = self.bot._aragorn_and_posture("BTCUSD", short,
                                                     self.stage)
        self.assertFalse(stage["force_paper"])
        self.assertEqual(meta["posture"]["kind"], "risk_on_short")

    def test_both_switches_off_change_nothing(self):
        from bot_program.market_stress import set_override
        set_override("crisis", by="t")
        stage, meta = self.bot._aragorn_and_posture("BTCUSD", self.dec,
                                                     self.stage)
        self.assertEqual((stage, meta), (self.stage, {}))

    def test_a_paper_config_is_never_touched(self):
        from bot_program.market_stress import set_override
        _switch("crisis_mode")
        set_override("crisis", by="t")
        self.bot.cfg.mode = "paper"
        stage, meta = self.bot._aragorn_and_posture("BTCUSD", self.dec,
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

    def test_paper_rows_on_a_live_config_take_no_real_slot(self):
        """Review, 2026-10-02: three crisis-paper longs must not refuse the
        shorts the posture keeps trading."""
        from bot_program.models import AssetBotTrade
        self.bot.cfg.max_concurrent_positions = 1
        self.bot.cfg.save(update_fields=["max_concurrent_positions"])
        AssetBotTrade.objects.create(
            config=self.bot.cfg, asset_class="crypto", symbol="ETHUSD",
            side="BUY", qty=Decimal("1"), entry_price=Decimal("100"),
            status="OPEN", paper=True)
        ok, why = self.bot.can_open_new()
        self.assertNotIn("concurrent positions reached", why)
        AssetBotTrade.objects.create(
            config=self.bot.cfg, asset_class="crypto", symbol="SOLUSD",
            side="BUY", qty=Decimal("1"), entry_price=Decimal("100"),
            status="OPEN", paper=False)
        ok, why = self.bot.can_open_new()
        self.assertFalse(ok)
        self.assertIn("concurrent positions reached", why)

    def test_the_price_is_read_again_after_the_debate(self):
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": "99.4"}
        why = self.bot._drift_since_proposal(client, "BTCUSD", "BUY",
                                             100.0, 99.0, 102.0)
        self.assertIn("of the way to the stop", why)
        client.ticker.return_value = {"lastPrice": "101.2"}
        self.assertIn("planned reward is gone", self.bot._drift_since_proposal(
            client, "BTCUSD", "BUY", 100.0, 99.0, 102.0))
        client.ticker.return_value = {"lastPrice": "100.2"}
        self.assertEqual(self.bot._drift_since_proposal(
            client, "BTCUSD", "BUY", 100.0, 99.0, 102.0), "")
        client.ticker.side_effect = RuntimeError("down")
        self.assertEqual(self.bot._drift_since_proposal(
            client, "BTCUSD", "SELL", 100.0, 101.0, 98.0), "",
            "an unread ticker refuses nothing")

    def test_the_hooks_sit_where_they_must(self):
        import inspect

        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.propose_entry)
        self.assertLess(src.index("stage_policy(decision.rule_name)"),
                        src.index("self._aragorn_and_posture("))
        self.assertLess(src.index("self._aragorn_and_posture("),
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
        # cared for 130 h (on a Thursday, no weekend inside): no progress
        thursday = datetime(2026, 10, 8, 12, 0, tzinfo=dt_tz.utc)
        watched = (thursday - timedelta(hours=130)).isoformat()
        stale = _row(hours=200, cls="crypto",
                     care={"since": watched, "peak": 100.2})
        stale.opened_at = thursday - timedelta(hours=200)
        p = plan(stale, 100.2, now=thursday)
        self.assertEqual((p["action"], p["reason"]), ("close", "TIME"))

    def test_switching_care_on_closes_nothing_old_on_its_first_tick(self):
        """The review's mass-close: a row care never saw has no history it
        can judge — its no-progress clock starts the first tick care sees
        it."""
        from bot_program.position_care import plan
        p = plan(_row(hours=500, cls="stock"), 100.2)
        self.assertEqual(p["action"], "hold")
        self.assertIn("since", p["care"])

    def test_the_weekend_lock_never_closes_a_loser_and_follows_new_york(self):
        from bot_program.position_care import is_weekend_window, plan
        friday = datetime(2026, 10, 2, 20, 0, tzinfo=dt_tz.utc)  # 16:00 NY
        p = plan(_row(cls="forex", care={"peak": 101.0}), 98.4,
                 now=friday)                                       # -0.8R
        self.assertEqual(p["action"], "hold", "a past peak locks nothing")
        p = plan(_row(cls="forex"), 101.2, now=friday)             # +0.6R
        self.assertEqual(p["care"]["soft_why"], "weekend lock")
        self.assertTrue(is_weekend_window(friday, "forex"))
        self.assertFalse(is_weekend_window(friday, "stock"),
                         "US stocks shut at 16:00 New York")
        winter = datetime(2026, 12, 4, 20, 30, tzinfo=dt_tz.utc)  # 15:30 NY
        self.assertTrue(is_weekend_window(winter, "stock"))

    def test_market_hours_skip_the_weekend_except_crypto(self):
        from bot_program.position_care import market_hours
        fri = datetime(2026, 10, 2, 12, 0, tzinfo=dt_tz.utc)
        mon = datetime(2026, 10, 5, 12, 0, tzinfo=dt_tz.utc)
        self.assertEqual(market_hours(fri, mon, "forex"), 24.0)
        self.assertEqual(market_hours(fri, mon, "crypto"), 72.0)


class TheCareTests(TestCase):

    def test_care_never_closes_what_the_venue_no_longer_shows(self):
        from bot_program.models import AssetBotTrade
        from bot_program.position_care import care
        user = get_user_model().objects.create_user("stw_v", password="x")
        cfg = _config(user, symbols=["BTCUSD"], mode="live")
        t = AssetBotTrade.objects.create(
            config=cfg, asset_class="crypto", symbol="BTCUSD", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"),
            stop_loss=Decimal("98"), status="OPEN", paper=False,
            metadata={"initial_stop_loss": 98.0, "protected": True,
                      "protective_trade_id": "777",
                      "care": {"peak": 104.0, "soft_stop": 102.0,
                               "soft_why": "trail",
                               "since": timezone.now().isoformat()}})
        _switch("aragorn")
        bot = MagicMock()
        bot._instrument_class.return_value = "crypto"
        bot._broker_snapshot.return_value = [{"position_id": "999"}]
        client = MagicMock()
        client.close_needs_position_id.return_value = True
        self.assertEqual(care(bot, t, Decimal("101.5"), client), "")
        bot._close_trade.assert_not_called()
        bot._broker_snapshot.return_value = [{"position_id": "777"}]
        bot._close_trade.return_value = False
        self.assertEqual(care(bot, t, Decimal("101.5"), client), "attempted",
                         "a close in flight still ends the row's tick")

    def test_care_is_off_with_the_aragorn_and_closes_through_the_bot(self):
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
                               "soft_why": "trail"},
                      "adjusted_by": "operator"})
        bot = MagicMock()
        bot._close_trade.return_value = True
        bot._instrument_class.return_value = "crypto"
        self.assertEqual(care(bot, t, Decimal("101.5"), None), "")
        bot._close_trade.assert_not_called()
        _switch("aragorn")
        self.assertEqual(care(bot, t, Decimal("101.5"), None), "closed")
        bot._close_trade.assert_called_once()
        self.assertEqual(bot._close_trade.call_args.kwargs["reason"], "SL")
        t.refresh_from_db()
        self.assertEqual(t.metadata["care_exit"], "trail")
        self.assertEqual(t.metadata["adjusted_by"], "operator",
                         "care merges its keys, never clobbers the rest")
        from bot_program.aragorn_models import AragornAction
        self.assertIn("REAL MONEY", AragornAction.objects.get(
            kind="care_close").detail)


# ── the switches, the beat, the command ──────────────────────────────────

class TheControlsTests(TestCase):

    def test_one_fleet_pass_at_a_time(self):
        from django.core.cache import cache

        from bot_program.tasks import TICK_LOCK_KEY, tick_all_asset_bots
        _switch("platform_master")
        _switch("pipeline_asset_bots")
        cache.set(TICK_LOCK_KEY, "x", 60)
        with patch("bot_program.asset_engine.runner.run_all_asset_bots") as run:
            out = tick_all_asset_bots()
        run.assert_not_called()
        self.assertEqual(out["status"], "skipped")
        cache.delete(TICK_LOCK_KEY)
        with patch("bot_program.asset_engine.runner.run_all_asset_bots",
                   return_value={"ticked": 1}) as run:
            tick_all_asset_bots()
        run.assert_called_once()
        self.assertIsNone(cache.get(TICK_LOCK_KEY), "released after a pass")

    def test_two_live_money_switches_seeded_off_and_never_bulk_armed(self):
        from core.platform_control import (BULK_ENABLE_EXEMPT,
                                           DEFAULT_COMPONENTS,
                                           LIVE_MONEY_SWITCHES)
        rows = {c["key"]: c for c in DEFAULT_COMPONENTS}
        for key in ("aragorn", "crisis_mode"):
            self.assertIn(key, rows)
            self.assertLess(len(rows[key]["description"]), 300)
            self.assertIn(key, LIVE_MONEY_SWITCHES)
            self.assertIn(key, BULK_ENABLE_EXEMPT)

    def test_the_beat_runs_the_three_tasks(self):
        from config.celery import app
        tasks = {v["task"] for v in app.conf.beat_schedule.values()}
        for name in ("read_market_stress", "run_aragorn",
                     "aragorn_daily_report"):
            self.assertIn(f"bot_program.tasks.{name}", tasks)

    def test_the_command_shows_plans_and_overrides(self):
        out = StringIO()
        call_command("aragorn", stdout=out)
        self.assertIn("Aragorn: OFF", out.getvalue())
        out = StringIO()
        call_command("aragorn", "bench", "golden_cross", "forex", "--pin",
                     "--by", "gandalf", stdout=out)
        self.assertIn("golden_cross/forex: bench (pinned)", out.getvalue())
        out = StringIO()
        call_command("aragorn", "posture", "stressed", "--hours", "3",
                     stdout=out)
        self.assertIn("stressed", out.getvalue())
        out = StringIO()
        call_command("aragorn", "journal", stdout=out)
        self.assertIn("operator_bench", out.getvalue())
        out = StringIO()
        call_command("aragorn", "run", stdout=out)
        self.assertIn("Nothing to move.", out.getvalue())
