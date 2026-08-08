"""Tests for Phase-12 real-time event-driven engine.

Covers:
  - register_fast_rule: rejects non-FastRule, validates rule_name/event_types
  - dispatch_event: routes only to rules with matching event_type
  - dispatch_event creates Signal with correct rule_name + price levels
  - dispatch_event records FastEvent audit row with timing + fired rules
  - cooldown: same (rule, symbol) doesn't fire twice within window
  - Phase-5 integration: paused rule_name skipped by dispatcher
  - BreakoutOnTickRule: fires on bullish breakout, not on inside-range
  - NewsShockRule: fires on extreme sentiment, not on neutral

Run with:  python manage.py test tests.test_fast_rules
"""
import time
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _seed_prices(instrument, closes, timeframe="5m", end=None):
    """Seed PriceData. Each close also becomes high+low for simplicity."""
    from market_data.models import PriceData
    end = end or timezone.now()
    rows = []
    for i, c in enumerate(closes):
        ts = end - timedelta(minutes=(len(closes) - i) * 5)
        rows.append(PriceData(
            instrument=instrument, timeframe=timeframe, timestamp=ts,
            open=Decimal(str(c)), high=Decimal(str(c)), low=Decimal(str(c)),
            close=Decimal(str(c)), volume=0, source="test",
        ))
    PriceData.objects.bulk_create(rows)


def _isolate_registry():
    """Test setUp/tearDown helper: clear registry + cooldowns + re-register defaults."""
    from signals.fast_rules import reset_fast_rules, register_default_rules
    reset_fast_rules()
    register_default_rules()


# ── Registry ───────────────────────────────────────────────────────────────

class RegistryTests(TestCase):
    def setUp(self):
        from signals.fast_rules import reset_fast_rules
        reset_fast_rules()

    def test_register_rejects_non_FastRule(self):
        from signals.fast_rules import register_fast_rule
        with self.assertRaises(TypeError):
            register_fast_rule("not a rule")

    def test_register_rejects_empty_rule_name(self):
        from signals.fast_rules import register_fast_rule, FastRule
        class Bad(FastRule):
            rule_name = ""
            event_types = ["x"]
            def evaluate(self, *args, **kw): return None
        with self.assertRaises(ValueError):
            register_fast_rule(Bad())

    def test_register_rejects_empty_event_types(self):
        from signals.fast_rules import register_fast_rule, FastRule
        class Bad(FastRule):
            rule_name = "bad"
            event_types = []
            def evaluate(self, *args, **kw): return None
        with self.assertRaises(ValueError):
            register_fast_rule(Bad())

    def test_register_default_rules_idempotent(self):
        from signals.fast_rules import (
            register_default_rules, FAST_RULE_REGISTRY,
        )
        register_default_rules()
        n1 = len(FAST_RULE_REGISTRY)
        register_default_rules()
        n2 = len(FAST_RULE_REGISTRY)
        self.assertEqual(n1, n2)


# ── Dispatch routing ───────────────────────────────────────────────────────

class DispatchRoutingTests(TestCase):
    def setUp(self):
        from signals.fast_rules import (
            reset_fast_rules, register_fast_rule, FastRule, SignalSpec,
        )
        reset_fast_rules()

        class TickRule(FastRule):
            rule_name = "test_tick"
            event_types = ["price_tick"]
            cooldown_seconds = 0
            def evaluate(self, event_type, payload):
                from instruments.models import Instrument
                inst = Instrument.objects.filter(symbol=payload["symbol"]).first()
                if not inst:
                    return None
                return SignalSpec(
                    instrument=inst, direction="bullish", score=0.9,
                    title="tick fired", price=100.0, stop=99.0, target=102.0,
                )

        class NewsRule(FastRule):
            rule_name = "test_news"
            event_types = ["news"]
            cooldown_seconds = 0
            def evaluate(self, event_type, payload):
                return None  # never fires

        register_fast_rule(TickRule())
        register_fast_rule(NewsRule())

    def test_dispatch_only_evaluates_matching_event_type(self):
        from signals.fast_rules import dispatch_event
        _instrument("ROUT1")
        result = dispatch_event("price_tick", {"symbol": "ROUT1", "last": 100})
        self.assertEqual(result["rules_evaluated"], 1)  # only TickRule
        self.assertEqual(result["rules_fired"], 1)

    def test_dispatch_no_matching_rules_zero_evaluated(self):
        from signals.fast_rules import dispatch_event
        result = dispatch_event("nonexistent_event", {})
        self.assertEqual(result["rules_evaluated"], 0)
        self.assertEqual(result["rules_fired"], 0)

    def test_dispatch_creates_signal_with_correct_rule_name(self):
        from signals.fast_rules import dispatch_event
        from signals.models import Signal
        _instrument("ROUT2")
        result = dispatch_event("price_tick", {"symbol": "ROUT2", "last": 100})
        self.assertEqual(len(result["signal_ids"]), 1)
        sig = Signal.objects.get(id=result["signal_ids"][0])
        self.assertEqual(sig.rule_name, "test_tick")
        self.assertEqual(sig.direction, "bullish")
        self.assertEqual(float(sig.suggested_target), 102.0)

    def test_dispatch_records_fastevent_audit(self):
        from signals.fast_rules import dispatch_event
        from signals.models import FastEvent
        _instrument("ROUT3")
        dispatch_event("price_tick", {"symbol": "ROUT3", "last": 100})
        fe = FastEvent.objects.last()
        self.assertEqual(fe.event_type, "price_tick")
        self.assertEqual(fe.symbol, "ROUT3")
        self.assertEqual(fe.rules_fired, 1)
        self.assertIn("test_tick", fe.fired_rule_names)
        self.assertGreater(fe.dispatch_ms, 0)


# ── Cooldown ───────────────────────────────────────────────────────────────

class CooldownTests(TestCase):
    def setUp(self):
        from signals.fast_rules import (
            reset_fast_rules, register_fast_rule, FastRule, SignalSpec,
        )
        reset_fast_rules()
        class CooledRule(FastRule):
            rule_name = "cooled_rule"
            event_types = ["price_tick"]
            cooldown_seconds = 60
            def evaluate(self, event_type, payload):
                from instruments.models import Instrument
                inst = Instrument.objects.filter(symbol=payload["symbol"]).first()
                if not inst:
                    return None
                return SignalSpec(
                    instrument=inst, direction="bullish", score=0.9,
                    title="cooled", price=100.0,
                )
        register_fast_rule(CooledRule())

    def test_second_dispatch_within_cooldown_skips(self):
        from signals.fast_rules import dispatch_event
        from signals.models import Signal
        _instrument("CL1")
        r1 = dispatch_event("price_tick", {"symbol": "CL1", "last": 100})
        r2 = dispatch_event("price_tick", {"symbol": "CL1", "last": 101})
        self.assertEqual(r1["rules_fired"], 1)
        self.assertEqual(r2["rules_fired"], 0)
        self.assertEqual(Signal.objects.filter(rule_name="cooled_rule").count(), 1)

    def test_different_symbol_independent_cooldown(self):
        from signals.fast_rules import dispatch_event
        _instrument("CL2A")
        _instrument("CL2B")
        r1 = dispatch_event("price_tick", {"symbol": "CL2A", "last": 100})
        r2 = dispatch_event("price_tick", {"symbol": "CL2B", "last": 100})
        self.assertEqual(r1["rules_fired"], 1)
        self.assertEqual(r2["rules_fired"], 1)


# ── Phase-5 actuator integration ───────────────────────────────────────────

class ActuatorIntegrationTests(TestCase):
    def setUp(self):
        from signals.fast_rules import (
            reset_fast_rules, register_fast_rule, FastRule, SignalSpec,
        )
        reset_fast_rules()
        class PauseableRule(FastRule):
            rule_name = "pauseable_rule"
            event_types = ["price_tick"]
            cooldown_seconds = 0
            def evaluate(self, event_type, payload):
                from instruments.models import Instrument
                inst = Instrument.objects.filter(symbol=payload["symbol"]).first()
                return SignalSpec(
                    instrument=inst, direction="bullish", score=0.9,
                    title="x", price=100.0,
                ) if inst else None
        register_fast_rule(PauseableRule())

    def test_paused_rule_skipped_by_dispatcher(self):
        from signals.fast_rules import dispatch_event
        from signals.models import RuleControl, Signal
        _instrument("PAUSED1")
        # Pause the rule via Phase-5 RuleControl.
        RuleControl.objects.create(
            rule_name="pauseable_rule", status="paused",
            weight_multiplier=0.0,
            paused_until=timezone.now() + timedelta(days=1),
        )
        r = dispatch_event("price_tick", {"symbol": "PAUSED1", "last": 100})
        self.assertEqual(r["rules_fired"], 0)
        self.assertEqual(Signal.objects.filter(rule_name="pauseable_rule").count(), 0)


# ── BreakoutOnTickRule ─────────────────────────────────────────────────────

class BreakoutRuleTests(TestCase):
    def setUp(self):
        _isolate_registry()

    def test_fires_on_bullish_breakout(self):
        from signals.fast_rules import dispatch_event
        from signals.models import Signal
        inst = _instrument("BR1")
        # 25 closes around 100, last tick well above prior 20-bar high.
        _seed_prices(inst, [100.0] * 25)
        r = dispatch_event("price_tick", {"symbol": "BR1", "last": 105.0})
        self.assertGreaterEqual(r["rules_fired"], 1)
        sigs = Signal.objects.filter(rule_name="fast_breakout_on_tick", direction="bullish")
        self.assertEqual(sigs.count(), 1)

    def test_no_fire_when_inside_range(self):
        from signals.fast_rules import dispatch_event
        from signals.models import Signal
        inst = _instrument("BR2")
        _seed_prices(inst, [100.0] * 25)
        r = dispatch_event("price_tick", {"symbol": "BR2", "last": 100.1})
        self.assertEqual(r["rules_fired"], 0)
        self.assertEqual(Signal.objects.filter(rule_name="fast_breakout_on_tick").count(), 0)

    def test_fires_on_bearish_breakdown(self):
        from signals.fast_rules import dispatch_event
        from signals.models import Signal
        inst = _instrument("BR3")
        _seed_prices(inst, [100.0] * 25)
        r = dispatch_event("price_tick", {"symbol": "BR3", "last": 95.0})
        self.assertGreaterEqual(r["rules_fired"], 1)
        sigs = Signal.objects.filter(rule_name="fast_breakout_on_tick", direction="bearish")
        self.assertEqual(sigs.count(), 1)


# ── NewsShockRule ──────────────────────────────────────────────────────────

class NewsShockRuleTests(TestCase):
    def setUp(self):
        _isolate_registry()

    def test_fires_on_extreme_positive_sentiment(self):
        from signals.fast_rules import dispatch_event
        from signals.models import Signal
        _instrument("NS1")
        r = dispatch_event("news", {
            "symbol": "NS1", "sentiment": 0.85,
            "headline": "huge upgrade", "source": "bloomberg",
            "last_price": 200.0,
        })
        self.assertGreaterEqual(r["rules_fired"], 1)
        sig = Signal.objects.filter(rule_name="fast_news_shock").first()
        self.assertIsNotNone(sig)
        self.assertEqual(sig.direction, "bullish")
        self.assertEqual(sig.urgency, "critical")

    def test_no_fire_on_moderate_sentiment(self):
        from signals.fast_rules import dispatch_event
        from signals.models import Signal
        _instrument("NS2")
        r = dispatch_event("news", {
            "symbol": "NS2", "sentiment": 0.3,
            "headline": "neutral", "source": "x", "last_price": 200.0,
        })
        self.assertEqual(r["rules_fired"], 0)
        self.assertEqual(Signal.objects.filter(rule_name="fast_news_shock").count(), 0)

    def test_fires_bearish_on_extreme_negative(self):
        from signals.fast_rules import dispatch_event
        from signals.models import Signal
        _instrument("NS3")
        r = dispatch_event("news", {
            "symbol": "NS3", "sentiment": -0.9,
            "headline": "huge downgrade", "source": "x", "last_price": 200.0,
        })
        sig = Signal.objects.filter(rule_name="fast_news_shock").first()
        self.assertIsNotNone(sig)
        self.assertEqual(sig.direction, "bearish")

    def test_no_fire_when_no_price_available(self):
        from signals.fast_rules import dispatch_event
        from signals.models import Signal
        # Instrument exists but no LiveQuote and payload has no last_price.
        _instrument("NS4")
        r = dispatch_event("news", {
            "symbol": "NS4", "sentiment": 0.9, "headline": "x", "source": "x",
        })
        self.assertEqual(r["rules_fired"], 0)
