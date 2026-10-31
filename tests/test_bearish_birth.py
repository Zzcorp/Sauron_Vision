"""BORN AT RESEARCH (2026-10-31, signals/rule_birth): the bearish pack's
eleven names are watched and graded, never traded, until the ladder
promotes them.

What the file pins:
  * with no RuleControl row a born name reads research (may_trade False);
    any other name with no row still reads paper;
  * decide() leaves a born name's signals out of the window BEFORE the
    32-slot slice, so they neither vote nor crowd a votable row out, and
    on a LIVE config a born name at paper does not vote either (its vote
    would push or cancel a live-stage rule's real order);
  * the first stored signal of a born name writes its row at research, a
    second leaves the row as it is;
  * every other row creator (the actuator's pause and rollback, the
    allocator's apply, `rule_scope set`) creates a born name's row at
    research, never at the model's live_full default;
  * a born name still at research reaches the banner and the bell, not
    Telegram; close advice and the legacy crypto blend do not read it;
  * nor do the readers that lean on money (2026-11-01): its row takes no
    slot in the realized-return audit's window (the quorum keeps today's
    correlated pairs), and its signals are no opportunity for a share
    plan, no backing for an instrument-view ticket, no trade in the config
    backtest and no budget in the meta-allocator's proposal.

Run with:  python manage.py test tests.test_bearish_birth
"""
from datetime import date, timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from tests.test_evidence_honesty import _cfg, _instrument, _signal


def _row(rule, stage, **kw):
    from signals.models import RuleControl
    return RuleControl.objects.create(rule_name=rule, promotion_stage=stage,
                                      **kw)


class TheBirthTests(TestCase):

    def test_every_born_name_with_no_row_reads_research(self):
        from signals.rule_actuator import stage_policy
        from signals.rule_birth import BORN_AT_RESEARCH
        self.assertEqual(len(BORN_AT_RESEARCH), 11)
        for name in sorted(BORN_AT_RESEARCH):
            p = stage_policy(name)
            self.assertEqual(p["stage"], "research", name)
            self.assertFalse(p["may_trade"], name)
            self.assertIn("born at research", p["reason"])

    def test_a_fork_of_a_born_name_is_born_with_it(self):
        from signals.rule_actuator import stage_policy
        from signals.rule_birth import born_at_research
        self.assertTrue(born_at_research("death_cross_evolved_v2"))
        self.assertTrue(born_at_research("death_cross_evolved_v2_evolved_v1"))
        self.assertFalse(born_at_research("golden_cross_evolved_v2"))
        self.assertFalse(stage_policy("death_cross_evolved_v3")["may_trade"])

    def test_any_other_name_with_no_row_still_reads_paper(self):
        from signals.rule_actuator import stage_policy
        p = stage_policy("golden_cross")
        self.assertEqual(p["stage"], "paper")
        self.assertTrue(p["may_trade"])

    def test_a_row_decides_once_it_exists(self):
        from signals.rule_actuator import stage_policy
        _row("death_cross", "paper")
        self.assertEqual(stage_policy("death_cross")["stage"], "paper")

    def test_birth_defaults_change_nothing_for_an_existing_name(self):
        from signals.rule_birth import birth_defaults
        self.assertEqual(birth_defaults("golden_cross"), {})
        self.assertEqual(birth_defaults("bull_trap_swing_high")
                         ["promotion_stage"], "research")


class TheVoteTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("born_u", password="x")
        self.inst = _instrument("BORNX", asset_class="stock")

    def _decide(self, mode="paper", **kw):
        from bot_program.asset_engine import StockBot
        cfg = _cfg(self.user, asset_class="stock", name=f"Born {mode}",
                   mode=mode, symbols=["BORNX"], capital=Decimal("10000"),
                   **kw)
        return StockBot(cfg).decide("BORNX")

    def test_a_born_bearish_signal_does_not_cancel_a_paper_long(self):
        _signal(self.inst, rule="golden_cross", score=0.62)
        _signal(self.inst, rule="bull_trap_swing_high", direction="bearish",
                score=0.75)
        d = self._decide()
        self.assertEqual(d.direction, "BUY", d.reasons)
        self.assertNotIn("bull_trap_swing_high", " ".join(d.reasons))

    def test_forty_research_signals_do_not_crowd_the_window(self):
        from signals.rule_birth import BORN_AT_RESEARCH
        for name in sorted(BORN_AT_RESEARCH):
            for _ in range(4):
                _signal(self.inst, rule=name, direction="bearish", score=0.75)
        _signal(self.inst, rule="golden_cross", score=0.61)
        d = self._decide()
        self.assertEqual(d.direction, "BUY", d.reasons)
        self.assertEqual(d.rule_name, "golden_cross")

    def test_only_born_research_signals_say_so(self):
        _signal(self.inst, rule="death_cross", direction="bearish", score=0.8)
        d = self._decide()
        self.assertEqual(d.direction, "HOLD")
        self.assertIn("only research-stage or paused signals", d.reasons[0])

    def test_on_a_live_config_a_paper_born_short_is_no_second_vote(self):
        _row("bollinger_squeeze_breakout", "live_full")
        _row("range_breakdown_short", "paper")
        _signal(self.inst, rule="bollinger_squeeze_breakout",
                direction="bearish", score=0.62)
        _signal(self.inst, rule="range_breakdown_short", direction="bearish",
                score=0.75)
        d = self._decide(mode="live", min_signals_for_entry=2)
        self.assertEqual(d.direction, "HOLD", d.reasons)

    def test_on_a_live_config_a_paper_born_short_cancels_no_live_long(self):
        _row("golden_cross", "live_full")
        _row("range_breakdown_short", "paper")
        _signal(self.inst, rule="golden_cross", score=0.62)
        _signal(self.inst, rule="range_breakdown_short", direction="bearish",
                score=0.75)
        d = self._decide(mode="live")
        self.assertEqual(d.direction, "BUY", d.reasons)

    def test_on_a_paper_config_a_paper_born_short_votes(self):
        _row("range_breakdown_short", "paper")
        _signal(self.inst, rule="range_breakdown_short", direction="bearish",
                score=0.75)
        d = self._decide(mode="paper")
        self.assertEqual(d.direction, "SELL", d.reasons)
        self.assertEqual(d.rule_name, "range_breakdown_short")

    def test_a_live_stage_born_rule_votes_on_a_live_config(self):
        _row("range_breakdown_short", "live_small")
        _signal(self.inst, rule="range_breakdown_short", direction="bearish",
                score=0.75)
        self.assertEqual(self._decide(mode="live").direction, "SELL")


def _raw(symbol, rule="bull_trap_swing_high"):
    return {"symbol": symbol, "rule": rule, "direction": "SHORT",
            "score": 0.7, "headline": f"{symbol} SHORT · test",
            "thesis": "test", "entry": 100.0, "stop": 103.0, "target": 94.0}


class TheFirstSignalTests(TestCase):

    def test_the_first_stored_signal_writes_the_row_at_research(self):
        from signals.models import RuleControl, Signal
        from signals.tasks import _create_signals_and_notify
        _instrument("FIRSTA", asset_class="stock")
        _instrument("FIRSTB", asset_class="stock")
        with patch("signals.announce.announce_new_signal"):
            self.assertEqual(_create_signals_and_notify([_raw("FIRSTA")]), 1)
        row = RuleControl.objects.get(rule_name="bull_trap_swing_high")
        self.assertEqual(row.promotion_stage, "research")
        self.assertIsNotNone(row.stage_entered_at)
        entered = row.stage_entered_at
        with patch("signals.announce.announce_new_signal"):
            self.assertEqual(_create_signals_and_notify([_raw("FIRSTB")]), 1)
        row.refresh_from_db()
        self.assertEqual(row.stage_entered_at, entered)
        self.assertEqual(RuleControl.objects.count(), 1)
        self.assertEqual(Signal.objects.filter(
            rule_name="bull_trap_swing_high").count(), 2)

    def test_an_existing_row_is_never_rewritten(self):
        from signals.models import RuleControl
        from signals.tasks import _create_signals_and_notify
        _instrument("FIRSTC", asset_class="stock")
        _row("bull_trap_swing_high", "paper")
        with patch("signals.announce.announce_new_signal"):
            _create_signals_and_notify([_raw("FIRSTC")])
        self.assertEqual(RuleControl.objects.get(
            rule_name="bull_trap_swing_high").promotion_stage, "paper")

    def test_an_existing_rule_writes_no_row(self):
        from signals.models import RuleControl
        from signals.tasks import _create_signals_and_notify
        _instrument("FIRSTD", asset_class="stock")
        with patch("signals.announce.announce_new_signal"):
            _create_signals_and_notify([_raw("FIRSTD", rule="golden_cross")])
        self.assertFalse(RuleControl.objects.exists())


class TheOtherCreatorsTests(TestCase):

    def test_an_actuator_pause_creates_a_research_row(self):
        from signals.models import RuleAction, RuleControl
        from signals.rule_actuator import apply_action, rollback_action
        from tests.test_rule_actuator import _seed_components, _set_live_mode
        _seed_components()
        _set_live_mode(True)
        user = User.objects.create_user("born_act", is_superuser=True)
        action = RuleAction.objects.create(
            rule_name="death_cross", action=RuleAction.ACTION_PAUSE,
            state=RuleAction.STATE_PROPOSED, rationale="test")
        apply_action(action.id, user)
        ctrl = RuleControl.objects.get(rule_name="death_cross")
        self.assertEqual(ctrl.promotion_stage, "research")
        self.assertEqual(ctrl.status, "paused")
        ctrl.delete()
        rollback_action(action.id, user)
        self.assertEqual(RuleControl.objects.get(
            rule_name="death_cross").promotion_stage, "research")

    def test_an_allocator_apply_creates_a_research_row(self):
        from signals.meta_allocator import apply_allocation
        from signals.models import MetaAllocation, RuleControl
        from tests.test_meta_allocator import _set_live
        _set_live(True)
        user = User.objects.create_user("born_alloc", is_superuser=True)
        alloc = MetaAllocation.objects.create(
            state=MetaAllocation.STATE_SHADOW,
            target_weights={"multipliers": {"vix_inversion_index_short": 1.2,
                                            "golden_cross": 1.1}})
        apply_allocation(alloc.id, user)
        self.assertEqual(RuleControl.objects.get(
            rule_name="vix_inversion_index_short").promotion_stage, "research")
        # an existing name keeps the creator's own default
        self.assertEqual(RuleControl.objects.get(
            rule_name="golden_cross").promotion_stage, "live_full")

    def test_rule_scope_set_creates_a_research_row(self):
        from signals.models import RuleControl
        out = StringIO()
        call_command("rule_scope", "show", "death_cross", stdout=out)
        self.assertIn("at the research stage", out.getvalue())
        call_command("rule_scope", "set", "death_cross",
                     "--exclude-class", "commodity", stdout=StringIO())
        self.assertEqual(RuleControl.objects.get(
            rule_name="death_cross").promotion_stage, "research")
        call_command("rule_scope", "set", "golden_cross",
                     "--exclude-class", "commodity", stdout=StringIO())
        self.assertEqual(RuleControl.objects.get(
            rule_name="golden_cross").promotion_stage, "paper")


class TheQuietTests(TestCase):

    def test_a_born_research_signal_is_not_sent_to_the_phone(self):
        from signals.announce import announce_new_signal
        inst = _instrument("QUIETX", asset_class="stock")
        sig = _signal(inst, rule="crowded_long_reversal_short",
                      direction="bearish", score=0.7)
        with patch("alerts.dispatch.dispatch_signal_alert") as send, \
                patch("alerts.notify.notify_new_signal") as bell:
            out = announce_new_signal(sig)
        send.assert_not_called()
        bell.assert_called_once()
        self.assertIn("born at research", out["channels"])

    def test_a_promoted_born_rule_and_any_other_rule_are_sent(self):
        from signals.announce import announce_new_signal
        inst = _instrument("LOUDX", asset_class="stock")
        _row("crowded_long_reversal_short", "paper")
        for rule in ("crowded_long_reversal_short", "golden_cross"):
            sig = _signal(inst, rule=rule, direction="bearish", score=0.7)
            with patch("alerts.dispatch.dispatch_signal_alert",
                       return_value={"telegram": 1}) as send, \
                    patch("alerts.notify.notify_new_signal"):
                announce_new_signal(sig)
            send.assert_called_once()

    def test_close_advice_reads_no_born_research_signal(self):
        from brain.close_advice import fresh_signals
        inst = _instrument("ADVX", asset_class="stock")
        _signal(inst, rule="death_cross", direction="bearish", score=0.9)
        _signal(inst, rule="golden_cross", direction="bullish", score=0.6)
        out = fresh_signals("ADVX", "BUY")
        self.assertEqual((out["agree"], out["oppose"]), (1, 0))
        self.assertFalse(out["opposing_dominates"])

    def test_the_legacy_crypto_blend_reads_no_born_research_signal(self):
        from bot_program.engine.strategy import _score_sauron_signals
        inst = _instrument("BTCUSD", asset_class="crypto")
        _signal(inst, rule="death_cross", direction="bearish", score=0.9)
        with patch("signals.bot_bridge.smc_score_for_symbol",
                   return_value=(0, [])):
            self.assertEqual(_score_sauron_signals("BTCUSDT"), (0, []))
        _signal(inst, rule="golden_cross", direction="bullish", score=0.6)
        with patch("signals.bot_bridge.smc_score_for_symbol",
                   return_value=(0, [])):
            score, _why = _score_sauron_signals("BTCUSDT")
        self.assertGreater(score, 0)


class TheCorrelationWindowTests(TestCase):
    """detect_realized_return_correlation audits the first 30 active rows
    by name, before it reads a trade; eight born names sort ahead of
    rsi_bull_divergence."""

    PAIR = ("rsi_bull_divergence", "starter_stock_momentum")

    def setUp(self):
        from bot_program.asset_engine import rule_clusters
        from signals.models import RuleControl
        # cluster_map caches for a day: put back what the process had, so
        # this pair is not one source in a later test's quorum
        self.addCleanup(rule_clusters._CACHE.update,
                        dict(rule_clusters._CACHE))
        for d in range(1, 29):
            RuleControl.objects.create(rule_name=f"generated_202610{d:02d}_idea",
                                       status="active",
                                       promotion_stage="live_full")
        for name in self.PAIR:
            RuleControl.objects.create(rule_name=name, status="active",
                                       promotion_stage="live_full")
        days = [date(2026, 10, d) for d in range(1, 13)]
        self.series = {
            self.PAIR[0]: {d: float(i % 3) for i, d in enumerate(days)},
            self.PAIR[1]: {d: float(i % 3) + 0.1 for i, d in enumerate(days)}}

    def _audit(self):
        from bot_program.asset_engine import rule_clusters
        from brain import correlation_audit as ca
        with patch.object(ca, "_daily_realized_r_series",
                          side_effect=lambda r, lookback_days:
                          self.series.get(r, {})) as read:
            pairs = ca.detect_realized_return_correlation(threshold=0.8)
            mapping, stale = rule_clusters.cluster_map(force=True)
        audited = {c.args[0] for c in read.call_args_list}
        return ([(p["rule_a"], p["rule_b"]) for p in pairs], audited,
                rule_clusters.independent_sources(self.PAIR, mapping=mapping,
                                                  stale=stale))

    def test_born_research_rows_take_no_slot(self):
        from signals.rule_birth import BORN_AT_RESEARCH, ensure_research_row
        before = self._audit()
        self.assertEqual(before[0], [self.PAIR])
        self.assertEqual(before[2], 1)
        for name in sorted(BORN_AT_RESEARCH):
            ensure_research_row(name)
        pairs, audited, sources = self._audit()
        self.assertEqual(pairs, [self.PAIR])
        self.assertEqual(sources, 1)
        self.assertEqual(audited, before[1])
        self.assertFalse(audited & BORN_AT_RESEARCH)

    def test_a_born_rule_off_research_takes_its_slot(self):
        from signals.models import RuleControl
        from signals.rule_birth import ensure_research_row
        ensure_research_row("bull_trap_swing_high")
        RuleControl.objects.filter(rule_name="bull_trap_swing_high").update(
            promotion_stage="paper")
        _pairs, audited, _sources = self._audit()
        self.assertIn("bull_trap_swing_high", audited)
        self.assertNotIn(self.PAIR[1], audited)


def _scanner_on():
    from core.platform_control import PlatformComponent
    c, _ = PlatformComponent.objects.get_or_create(
        key="pipeline_opportunity_scanner",
        defaults={"name": "Opportunity Scanner", "category": "pipeline"})
    c.is_enabled = True
    c.save()


class TheMoneyReadersTests(TestCase):
    """Signals of a born rule still at research: no opportunity for a
    share plan, no backing for a ticket, no trade in the config backtest."""

    def setUp(self):
        self.user = User.objects.create_user("born_readers", password="x")
        self.a = _instrument("BRNA", asset_class="stock")
        for symbol in ("BRNB", "BRNC", "BRND"):
            _instrument(symbol, asset_class="stock")

    def test_the_density_counts_no_born_research_signal(self):
        from signals.opportunity_density import opportunity_density
        _scanner_on()
        _signal(self.a, rule="death_cross", direction="bearish", score=0.6)
        stock = opportunity_density()["stock"]
        self.assertEqual((stock["n_signals"], stock["share"]), (0, 0.0))
        _signal(_instrument("BRNB", asset_class="stock"),
                rule="bollinger_squeeze_breakout", direction="bearish",
                score=0.6)
        stock = opportunity_density()["stock"]
        self.assertEqual((stock["n_signals"], stock["share"]), (1, 0.25))
        _row("death_cross", "paper")
        self.assertEqual(opportunity_density()["stock"]["n_signals"], 2)

    def test_a_born_research_short_backs_no_ticket(self):
        from bot_program.manual_trade import signal_backing_advisory
        _signal(self.a, rule="crowded_long_reversal_short",
                direction="bearish", score=0.7)
        adv = signal_backing_advisory(self.user, self.a, "SELL")
        self.assertFalse(adv["ok"])
        self.assertIn("No Sauron signal backs this ticket", adv["reason"])
        _signal(self.a, rule="bollinger_squeeze_breakout",
                direction="bearish", score=0.6)
        adv = signal_backing_advisory(self.user, self.a, "SELL")
        self.assertEqual((adv["ok"], adv["signals"]),
                         (True, ["bollinger_squeeze_breakout"]))

    def _backtest(self, rule, mode="paper"):
        from django.utils import timezone

        from bot_program.backtest_asset import BacktestParams, run_backtest
        from market_data.models import PriceData
        from signals.models import Signal
        t0 = timezone.now() - timedelta(hours=10)
        sig = _signal(self.a, rule=rule, direction="bearish", score=0.6)
        Signal.objects.filter(pk=sig.pk).update(created_at=t0)
        if not PriceData.objects.filter(instrument=self.a).exists():
            for i in range(1, 6):
                PriceData.objects.create(
                    instrument=self.a, timeframe="1h",
                    timestamp=t0 + timedelta(hours=i), open=Decimal("100"),
                    high=Decimal("100.5"), low=Decimal(str(100 - i)),
                    close=Decimal(str(100 - i)), volume=0, source="test")
        self.runs = getattr(self, "runs", 0) + 1
        cfg = _cfg(self.user, asset_class="stock", name=f"BT {self.runs}",
                   mode=mode, symbols=["BRNA"], capital=Decimal("10000"),
                   stop_loss_pct=2.0, take_profit_pct=4.0, timeframe="1h")
        res = run_backtest(BacktestParams(config_id=cfg.id,
                                          start=t0 - timedelta(hours=1),
                                          end=timezone.now()))
        Signal.objects.filter(pk=sig.pk).delete()
        return [t.rule_name for t in res.trades]

    def test_the_config_backtest_replays_what_decide_lets_vote(self):
        self.assertEqual(self._backtest("death_cross"), [])
        self.assertEqual(self._backtest("bollinger_squeeze_breakout"),
                         ["bollinger_squeeze_breakout"])
        # at paper a born rule votes on a paper config, not on a live one
        _row("death_cross", "paper")
        self.assertEqual(self._backtest("death_cross"), ["death_cross"])
        self.assertEqual(self._backtest("death_cross", mode="live"), [])

    def test_the_meta_allocator_budgets_no_born_research_rule(self):
        from signals.meta_allocator import _collect_rule_stats
        from signals.rule_birth import ensure_research_row
        from tests.test_meta_allocator import _seed_signals
        _seed_signals("golden_cross", [1.0, -0.5, 2.0])
        _seed_signals("death_cross", [-1.0, -1.0])
        ensure_research_row("death_cross")
        self.assertEqual(set(_collect_rule_stats(180)), {"golden_cross"})
        _row("bull_trap_swing_high", "paper")
        _seed_signals("bull_trap_swing_high", [0.5])
        self.assertEqual(set(_collect_rule_stats(180)),
                         {"golden_cross", "bull_trap_swing_high"})
