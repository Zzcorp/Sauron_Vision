"""The evidence ledger: what each rule proved, and the regret.

The platform graded itself in three places and showed them on three
pages. The operator's question — what did each rule make in paper, what
did it make live, how much proven R sits in paper that nothing has taken
live — was on none of them. Shadow mode, meanwhile, left only log lines:
24 hours of "would have bought" nobody could score. Shadow entries now
register direction calls under the config's own name, graded at the time
stop by the calibration, and the ledger shows them per config.

Run with:  python manage.py test tests.test_evidence_ledger
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.utils import timezone


def _instrument(symbol="AAPL", asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _graded_signal(rule, outcome, r, symbol="AAPL"):
    from signals.models import Signal
    inst = _instrument(symbol)
    return Signal.objects.create(
        instrument=inst, signal_type="composite", direction="bullish",
        urgency="medium", title=f"{symbol} {rule}", description="t",
        rule_name=rule, score=0.7, sub_scores={},
        price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
        suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
        is_active=False, outcome=outcome, realized_r=r,
        expired_at=timezone.now())


def _cfg(user, name="bot", mode="paper", **extras):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="stock", name=name, mode=mode,
        symbols=["AAPL"], capital=Decimal("1000"), enabled=True,
        extras=extras)


def _fill(cfg, rule, r, pnl, *, paper=True):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"),
        exit_price=Decimal("101"), status="CLOSED", pnl=Decimal(str(pnl)),
        rule_name=rule, paper=paper, realized_r=r, outcome="hit_target")


class TheRuleRowsTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("ev_u", password="x")

    def test_signals_and_fills_meet_on_one_row(self):
        from dashboard.views_evidence import rule_rows
        _graded_signal("r1", "hit_target", 2.0)
        _graded_signal("r1", "stopped_out", -1.0)
        _graded_signal("r1", "hit_target", 1.5)
        cfg = _cfg(self.user)
        _fill(cfg, "r1", 1.0, 10)
        _fill(cfg, "r1", -0.5, -5)
        row = next(r for r in rule_rows() if r["rule"] == "r1")
        self.assertEqual(row["sig_n"], 3)
        self.assertAlmostEqual(row["sig_hit"], 2 / 3, places=4)
        self.assertAlmostEqual(row["sig_r"], 2.5)
        self.assertEqual(row["paper_n"], 2)
        self.assertAlmostEqual(row["paper_r"], 0.5)
        self.assertAlmostEqual(row["paper_pnl"], 5.0)
        self.assertEqual(row["live_n"], 0)

    def test_the_regret_is_paper_r_with_no_live_fill(self):
        from dashboard.views_evidence import rule_rows
        cfg = _cfg(self.user)
        live = _cfg(self.user, name="live_bot", mode="live")
        _fill(cfg, "paper_only", 1.2, 12)
        _fill(cfg, "taken_live", 0.8, 8)
        _fill(live, "taken_live", 0.3, 3, paper=False)
        rows = {r["rule"]: r for r in rule_rows()}
        self.assertAlmostEqual(rows["paper_only"]["regret_r"], 1.2)
        self.assertEqual(rows["taken_live"]["regret_r"], 0.0)
        self.assertAlmostEqual(rows["taken_live"]["live_r"], 0.3)

    def test_an_active_signal_and_an_open_trade_are_not_evidence(self):
        from dashboard.views_evidence import rule_rows
        from bot_program.models import AssetBotTrade
        from signals.models import Signal
        s = _graded_signal("r2", "hit_target", 1.0)
        s.is_active = True
        s.save()
        cfg = _cfg(self.user)
        AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN",
            rule_name="r2", paper=True)
        self.assertEqual([r for r in rule_rows() if r["rule"] == "r2"], [])

    def test_a_control_row_without_evidence_still_appears_with_its_stage(self):
        from dashboard.views_evidence import rule_rows
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="quiet_rule")
        row = next(r for r in rule_rows() if r["rule"] == "quiet_rule")
        self.assertEqual(row["sig_n"], 0)
        self.assertIn(row["stage"], ("research", "paper", "live_small",
                                     "live_full"))


class TheShadowIsScoredTests(TestCase):

    def setUp(self):
        from market_data.models import PriceData
        self.user = User.objects.create_user("sh_u", password="x")
        self.inst = _instrument("AAPL")
        PriceData.objects.create(
            instrument=self.inst, timeframe="1h",
            timestamp=timezone.now() - timedelta(hours=1),
            open=100, high=100, low=100, close=Decimal("100"), volume=1,
            source="test")
        until = (timezone.now() + timedelta(hours=24)).isoformat()
        self.cfg = _cfg(self.user, name="SHADOWED", mode="live",
                        shadow_until=until)

    def _decision(self, direction="BUY"):
        return SimpleNamespace(direction=direction, score=0.72,
                               rule_name="r1", reasons=[])

    def test_a_shadow_entry_registers_a_call_under_the_configs_name(self):
        from ai_agents.models import AgentPrediction
        from bot_program.asset_engine.safety import log_shadow_entry
        from dashboard.views_evidence import shadow_agent_for
        log_shadow_entry(self.cfg, "AAPL", self._decision(), 100.0, 3)
        pred = AgentPrediction.objects.get(agent=shadow_agent_for(self.cfg))
        self.assertEqual(pred.predicted_value, "up")
        self.assertEqual(float(pred.reference_price), 100.0)
        self.assertAlmostEqual(pred.confidence, 0.72)
        self.assertGreater(pred.horizon_hours, 0)
        self.assertIn("r1", pred.evaluation_notes)

    def test_a_sell_is_a_down_call_and_a_hold_registers_nothing(self):
        from ai_agents.models import AgentPrediction
        from bot_program.asset_engine.safety import log_shadow_entry
        log_shadow_entry(self.cfg, "AAPL", self._decision("SELL"), 100.0, 3)
        self.assertEqual(AgentPrediction.objects.get().predicted_value,
                         "down")
        AgentPrediction.objects.all().delete()
        log_shadow_entry(self.cfg, "AAPL", self._decision("HOLD"), 100.0, 3)
        self.assertEqual(AgentPrediction.objects.count(), 0)

    def test_the_config_row_counts_the_shadows_graded_calls(self):
        from ai_agents.models import AgentPrediction
        from bot_program.asset_engine.safety import log_shadow_entry
        from dashboard.views_evidence import config_rows
        log_shadow_entry(self.cfg, "AAPL", self._decision(), 100.0, 3)
        pred = AgentPrediction.objects.get()
        pred.was_correct, pred.score = True, 0.02
        pred.evaluated_at = timezone.now()
        pred.save()
        row = next(c for c in config_rows() if c["cfg"].pk == self.cfg.pk)
        self.assertTrue(row["shadow"])
        self.assertEqual(row["calls_n"], 1)
        self.assertEqual(row["calls_graded"], 1)
        self.assertEqual(row["calls_hit"], 1.0)
        self.assertAlmostEqual(row["calls_move"], 0.02)

    def test_a_failure_inside_registration_never_breaks_the_tick(self):
        from unittest.mock import patch

        from bot_program.asset_engine.safety import log_shadow_entry
        with patch("ai_agents.calibration.log_direction_prediction",
                   side_effect=RuntimeError("boom")):
            log_shadow_entry(self.cfg, "AAPL", self._decision(), 100.0, 3)


class ThePageTests(TestCase):

    def test_it_renders_with_the_totals_and_the_link(self):
        user = User.objects.create_user("pg_u", password="x")
        cfg = _cfg(user)
        _fill(cfg, "r1", 1.5, 15)
        client = Client()
        client.force_login(user)
        html = client.get("/evidence/").content.decode()
        self.assertIn("Evidence ledger", html)
        self.assertIn("Regret", html)
        self.assertIn("r1", html)
        self.assertIn("/calibration/", html)
        self.assertIn("Evidence Ledger", html)          # the nav link
