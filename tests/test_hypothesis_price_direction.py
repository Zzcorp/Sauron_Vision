"""The hypothesis market's `price_direction` kind (2026-10-08): THE
THEORIST's market theories are graded confirmed or refuted like every
other agent's, on the calibration resolver's own rules (the first bar at
or after the deadline, a flat move is a miss, a grace counted in the
market's open hours), imported from ai_agents.calibration, never copied.

Run with:  python manage.py test tests.test_hypothesis_price_direction
"""
from datetime import timedelta
from decimal import Decimal

from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _inst(symbol="BTCUSD", asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _bar(at, close, symbol="BTCUSD"):
    from market_data.models import PriceData
    PriceData.objects.create(
        instrument=_inst(symbol), timeframe="1h", timestamp=at,
        open=Decimal(str(close)), high=Decimal(str(close)),
        low=Decimal(str(close)), close=Decimal(str(close)), volume=0,
        source="test")


def _criteria(**over):
    c = {"kind": "price_direction", "symbol": "BTCUSD", "direction": "up",
         "reference_price": 100.0}
    c.update(over)
    return c


class TheGateTests(TestCase):

    def test_an_unmeasurable_direction_is_refused_at_birth(self):
        from brain.hypotheses import UnmeasurableClaim, post_hypothesis
        _inst()
        for crit, words in ((_criteria(symbol="NOPE"), "catalogue"),
                            (_criteria(symbol=""), "catalogue"),
                            (_criteria(direction="sideways"), "up or down"),
                            (_criteria(reference_price=0), "reference price"),
                            (_criteria(reference_price="x"), "reference price"),
                            (_criteria(reference_price=float("nan")),
                             "reference price"),
                            (_criteria(reference_price=None),
                             "reference price")):
            with self.subTest(crit=crit):
                with self.assertRaises(UnmeasurableClaim) as ctx:
                    post_hypothesis(claim_text="t", source_agent="council_theorist",
                                    resolution_criteria=crit)
                self.assertIn(words, str(ctx.exception))
        h = post_hypothesis(claim_text="t", source_agent="council_theorist",
                            resolution_criteria=_criteria(), horizon_hours=48)
        self.assertEqual(h.outcome, "pending")


class TheResolverTests(TestCase):

    def _due(self, **over):
        from brain.hypotheses import post_hypothesis
        from brain.knowledge_models import Hypothesis
        _inst()
        h = post_hypothesis(claim_text="t", source_agent="council_theorist",
                            resolution_criteria=_criteria(**over),
                            horizon_hours=6)
        deadline = timezone.now() - timedelta(hours=10)
        Hypothesis.objects.filter(id=h.id).update(
            resolution_deadline=deadline)
        return h.id, deadline

    def _resolve(self, hid):
        from brain.hypotheses import resolve_due
        from brain.knowledge_models import Hypothesis
        resolve_due()
        return Hypothesis.objects.get(id=hid)

    def test_up_is_confirmed_down_refuted_and_flat_a_miss(self):
        up, at = self._due()
        _bar(at + timedelta(hours=1), 103)
        h = self._resolve(up)
        self.assertEqual(h.outcome, "confirmed")
        self.assertIn("BTCUSD 100 -> 103 (+3.00%)", h.resolution_notes)

    def test_a_down_call_on_a_rise_is_refuted(self):
        down, at = self._due(direction="down")
        _bar(at + timedelta(hours=1), 103)
        self.assertEqual(self._resolve(down).outcome, "refuted")

    def test_a_flat_move_is_a_miss(self):
        flat, at = self._due()
        _bar(at + timedelta(hours=1), 100.05)
        h = self._resolve(flat)
        self.assertEqual(h.outcome, "refuted")
        self.assertIn("flat", h.resolution_notes)

    def test_no_bar_defers_inside_the_grace_and_is_unresolvable_after(self):
        from brain.knowledge_models import Hypothesis
        hid, _at = self._due()
        self.assertEqual(self._resolve(hid).outcome, "pending")
        Hypothesis.objects.filter(id=hid).update(
            resolution_deadline=timezone.now() - timedelta(days=5))
        h = self._resolve(hid)
        self.assertEqual(h.outcome, "unresolvable")
        self.assertIn("no bar within 48 market hours", h.resolution_notes)


class TheRegistryTests(SimpleTestCase):

    def test_the_kind_is_registered_and_the_critic_is_unchanged(self):
        from brain.critic import ALLOW_RESOLVERS
        from brain.hypotheses import RESOLVERS, _resolve_price_direction
        self.assertIs(RESOLVERS["price_direction"], _resolve_price_direction)
        self.assertEqual(ALLOW_RESOLVERS,
                         {"regime_holds", "rule_avg_r", "anomaly_persists"})

    def test_the_resolver_imports_the_calibration_rules(self):
        import inspect

        from brain import hypotheses
        src = inspect.getsource(hypotheses._resolve_price_direction)
        for name in ("DIRECTION_FLAT_BAND", "DIRECTION_GRACE_HOURS",
                     "market_hours_between"):
            self.assertIn(name, src)
        self.assertIn("from ai_agents.calibration import", src)
