"""Risk-denominated sizing, and the promotion stage as a venue.

Two defects are pinned here.

The first: sizing was `capital * pct / price` and never read the stop. With
$10k at 2% and AAPL at $200 you bought one share whether the stop was 0.3%
away or 3% away — 10x the risk from the same config. Because
`realized_r = pnl / (|entry - stop| * qty)`, those two trades wrote "1R"
values worth $0.60 and $6.00 into the same column, so the mean of
`realized_r` was never an expectancy and no amount of trading would make it
one. Every sophisticated method downstream reads that number.

The second: the promotion stage was applied as a size multiplier, and
SIZE_FACTORS maps both `research` and `paper` to 0.0. `qty *= 0` exits the
entry path, so a rule at PAPER stage could not take the paper trade the
ladder was asking it for, and the evidence needed to leave paper could never
be produced. The ladder was closed on itself.

Run with:  python manage.py test tests.test_risk_sizing
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase


def _user(name="rs_u"):
    return User.objects.create_user(username=name, password="x")


def _cfg(user, **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(user=user, asset_class="stock", name="RS", mode="paper",
                    symbols=["AAA"], capital=Decimal("10000"), enabled=True,
                    position_size_pct=2.0, stop_loss_pct=1.5,
                    take_profit_pct=3.0, entry_score_min=0.6,
                    min_signals_for_entry=1)
    defaults.update(kw)
    return AssetBotConfig.objects.create(**defaults)


class RiskDenominatedSizingTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.cfg = _cfg(self.user)

    def test_a_tight_stop_and_a_wide_stop_risk_the_same_money(self):
        """The whole point. Under notional sizing these differed by 10x."""
        from bot_program.asset_engine.sizing import size_position
        tight = size_position(self.cfg, asset_class="stock", entry=200.0,
                              stop=199.4, direction="BUY")          # 0.3%
        wide = size_position(self.cfg, asset_class="stock", entry=200.0,
                             stop=194.0, direction="BUY")           # 3.0%
        risk_tight = abs(200.0 - tight["stop"]) * tight["qty"]
        risk_wide = abs(200.0 - wide["stop"]) * wide["qty"]
        self.assertAlmostEqual(risk_tight, risk_wide, places=6)
        self.assertAlmostEqual(risk_tight, 10000 * 0.0025, places=6)

    def test_the_tighter_stop_buys_more_units(self):
        from bot_program.asset_engine.sizing import size_position
        tight = size_position(self.cfg, asset_class="stock", entry=200.0,
                              stop=196.0, direction="BUY")
        wide = size_position(self.cfg, asset_class="stock", entry=200.0,
                             stop=180.0, direction="BUY")
        self.assertGreater(tight["qty"], wide["qty"])

    def test_risk_is_the_configured_fraction_of_equity(self):
        from bot_program.asset_engine.sizing import size_position
        cfg = _cfg(self.user, name="RS2", capital=Decimal("25000"),
                   extras={"risk_per_trade_pct": 0.5})
        s = size_position(cfg, asset_class="stock", entry=100.0, stop=98.0,
                          direction="BUY")
        self.assertAlmostEqual(abs(100.0 - s["stop"]) * s["qty"],
                               25000 * 0.005, places=6)

    def test_the_hard_ceiling_cannot_be_exceeded_by_config(self):
        """A fat-fingered extras value must not be able to bet the account."""
        from bot_program.asset_engine.sizing import MAX_RISK_FRACTION, risk_fraction
        cfg = _cfg(self.user, name="RS3", extras={"risk_per_trade_pct": 90})
        self.assertEqual(risk_fraction(cfg), MAX_RISK_FRACTION)

    def test_a_malformed_risk_value_falls_back_rather_than_raising(self):
        from bot_program.asset_engine.sizing import risk_fraction, DEFAULT_RISK_FRACTION
        cfg = _cfg(self.user, name="RS4", extras={"risk_per_trade_pct": "half"})
        self.assertEqual(risk_fraction(cfg), DEFAULT_RISK_FRACTION)


class LeverageBoundTests(TestCase):
    """Risk sizing fixes the denominator and unbounds the numerator:
    notional = equity * f / stop_fraction. At the 0.2% stop floor that is
    125% of equity in one position — something notional sizing could never
    produce. This is the standard way a risk-sizing rewrite loses more money
    than the rule it replaced."""

    def setUp(self):
        self.user = _user("lb_u")
        self.cfg = _cfg(self.user)

    def test_an_extremely_tight_stop_does_not_produce_absurd_leverage(self):
        from bot_program.asset_engine.sizing import size_position
        s = size_position(self.cfg, asset_class="stock", entry=100.0,
                          stop=99.8, direction="BUY")   # 0.2%
        self.assertLessEqual(s["notional_fraction"], 0.20 + 1e-9)
        self.assertTrue(s["stop_widened"])

    def test_widening_the_stop_keeps_risk_exactly_on_budget(self):
        """The alternative — clamping qty — would make realised risk
        stop-dependent again, and biased toward binding on the quietest
        instruments. Risk must stay flat; the stop moves instead."""
        from bot_program.asset_engine.sizing import size_position
        s = size_position(self.cfg, asset_class="stock", entry=100.0,
                          stop=99.8, direction="BUY")
        self.assertAlmostEqual(abs(100.0 - s["stop"]) * s["qty"],
                               10000 * 0.0025, places=6)

    def test_a_normal_stop_is_left_alone(self):
        from bot_program.asset_engine.sizing import size_position
        s = size_position(self.cfg, asset_class="stock", entry=100.0,
                          stop=98.0, direction="BUY")
        self.assertFalse(s["stop_widened"])
        self.assertEqual(s["stop"], 98.0)

    def test_a_short_widens_the_stop_upward(self):
        from bot_program.asset_engine.sizing import size_position
        s = size_position(self.cfg, asset_class="stock", entry=100.0,
                          stop=100.2, direction="SELL")
        self.assertTrue(s["stop_widened"])
        self.assertGreater(s["stop"], 100.2)

    def test_forex_is_not_constrained_like_equities(self):
        """20% notional on an FX major is an economically meaningless cap."""
        from bot_program.asset_engine.sizing import size_position
        cfg = _cfg(self.user, asset_class="forex", name="FX")
        s = size_position(cfg, asset_class="forex", entry=1.1000,
                          stop=1.0989, direction="BUY")   # 0.1%
        self.assertFalse(s["stop_widened"])


class PromotionStageIsAVenueTests(TestCase):
    def setUp(self):
        self.user = _user("ps_u")

    def _ctrl(self, rule_name, stage):
        from signals.models_control import RuleControl
        return RuleControl.objects.create(rule_name=rule_name,
                                          promotion_stage=stage)

    def test_a_paper_stage_rule_can_actually_trade(self):
        """It could not before: SIZE_FACTORS['paper'] is 0.0, and qty *= 0
        exits the entry path — so the stage that exists to generate paper
        evidence generated none."""
        from signals.rule_actuator import stage_policy
        self._ctrl("r_paper", "paper")
        p = stage_policy("r_paper")
        self.assertTrue(p["may_trade"])
        self.assertTrue(p["force_paper"])

    def test_a_research_rule_places_no_orders(self):
        from signals.rule_actuator import stage_policy
        self._ctrl("r_research", "research")
        self.assertFalse(stage_policy("r_research")["may_trade"])

    def test_an_unknown_rule_can_trade_but_only_on_paper(self):
        """Fail SAFE, not fail closed. The old default was 1.0 — an
        unregistered rule placed a live order at full size on its first ever
        firing. Failing all the way closed would be safe too, but it walls
        off the paper evidence the ladder needs to promote anything."""
        from signals.rule_actuator import stage_policy
        p = stage_policy("never_registered")
        self.assertTrue(p["may_trade"])
        self.assertTrue(p["force_paper"])
        self.assertEqual(p["live_size_factor"], 0.0)

    def test_no_unregistered_rule_can_reach_real_money(self):
        """The property that must hold however the default is tuned."""
        from signals.rule_actuator import stage_policy
        for name in ("never_registered", "typo_rule", ""):
            p = stage_policy(name)
            self.assertTrue(p["force_paper"] or not p["may_trade"],
                            msg=f"{name!r} could place a live order")

    def test_live_stages_carry_their_size_factors(self):
        from signals.rule_actuator import stage_policy
        self._ctrl("r_small", "live_small")
        self._ctrl("r_full", "live_full")
        small, full = stage_policy("r_small"), stage_policy("r_full")
        self.assertEqual((small["force_paper"], small["live_size_factor"]),
                         (False, 0.25))
        self.assertEqual((full["force_paper"], full["live_size_factor"]),
                         (False, 1.0))

    def test_the_admin_lane_no_longer_carries_the_stage(self):
        """admin_allocator_multiplier must not zero a paper-stage rule, or
        the venue decision is undone by the multiplier it replaced."""
        from signals.rule_actuator import admin_allocator_multiplier
        self._ctrl("r_paper2", "paper")
        self.assertEqual(admin_allocator_multiplier("r_paper2"), 1.0)


class EndToEndEntryTests(TestCase):
    def setUp(self):
        self.user = _user("e2e_u")

    def _signal(self, symbol="AAA", rule="r_live"):
        from instruments.models import Instrument
        from signals.models import Signal
        inst, _ = Instrument.objects.get_or_create(
            symbol=symbol, defaults={"name": symbol, "asset_class": "stock"})
        Signal.objects.create(
            instrument=inst, signal_type="composite", direction="bullish",
            urgency="medium", title="t", description="t", rule_name=rule,
            score=0.9, sub_scores={}, price_at_signal=Decimal("100"),
            suggested_entry=Decimal("100"), is_active=True)
        return inst

    def _run(self, cfg, price="100"):
        from bot_program.asset_engine import StockBot
        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": price})
        client.get_positions = MagicMock(return_value=[])
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            return StockBot(cfg).scan_symbol("AAA")

    def test_an_entry_risks_the_budget_not_the_notional(self):
        from signals.models_control import RuleControl
        from bot_program.models import AssetBotTrade
        RuleControl.objects.create(rule_name="r_live", promotion_stage="live_full")
        self._signal()
        cfg = _cfg(self.user, name="E1")
        self._run(cfg)
        t = AssetBotTrade.objects.filter(config=cfg).first()
        self.assertIsNotNone(t, "no trade was opened")
        risk = abs(float(t.entry_price) - float(t.stop_loss)) * float(t.qty)
        self.assertAlmostEqual(risk, 10000 * 0.0025, places=2)

    def test_the_recorded_initial_stop_is_the_one_that_was_placed(self):
        """If the widened stop is not what lands in metadata, realized_r is
        denominated against a stop that was never live."""
        from signals.models_control import RuleControl
        from bot_program.models import AssetBotTrade
        RuleControl.objects.create(rule_name="r_live", promotion_stage="live_full")
        self._signal()
        cfg = _cfg(self.user, name="E2")
        self._run(cfg)
        t = AssetBotTrade.objects.filter(config=cfg).first()
        self.assertAlmostEqual(float(t.metadata["initial_stop_loss"]),
                               float(t.stop_loss), places=6)

    def test_a_research_stage_rule_opens_nothing(self):
        from signals.models_control import RuleControl
        from bot_program.models import AssetBotTrade
        RuleControl.objects.create(rule_name="r_live", promotion_stage="research")
        self._signal()
        cfg = _cfg(self.user, name="E3")
        self._run(cfg)
        self.assertEqual(AssetBotTrade.objects.filter(config=cfg).count(), 0)

    def test_a_paper_stage_rule_opens_a_paper_trade_in_a_live_config(self):
        """The ladder asks for paper evidence; this is what produces it."""
        from signals.models_control import RuleControl
        from bot_program.models import AssetBotTrade
        RuleControl.objects.create(rule_name="r_live", promotion_stage="paper")
        self._signal()
        cfg = _cfg(self.user, name="E4", mode="live")
        self._run(cfg)
        t = AssetBotTrade.objects.filter(config=cfg).first()
        self.assertIsNotNone(t, "paper-stage rule still cannot trade")
        self.assertTrue(t.paper)

    def test_an_expensive_share_no_longer_silently_sizes_to_zero(self):
        """A live $10k config at 2% notional could not buy a $201 stock:
        int(200/201) == 0 with no log. Risk sizing buys ~$1,667 of notional
        at a 1.5% stop, so a $201 share is reachable."""
        from signals.models_control import RuleControl
        from bot_program.models import AssetBotTrade
        RuleControl.objects.create(rule_name="r_live", promotion_stage="live_full")
        self._signal()
        cfg = _cfg(self.user, name="E5", mode="live")
        self._run(cfg, price="201")
        t = AssetBotTrade.objects.filter(config=cfg).first()
        self.assertIsNotNone(t, "still cannot buy a $201 share")
        self.assertGreaterEqual(float(t.qty), 1.0)
