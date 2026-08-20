"""A long setup and its short twin are not the same rule.

The signature this audit compares is the set of evaluator KINDS and drops
every param, `direction` included — so a setup and its directional mirror,
which by construction run the same evaluators pointed the other way, scored
a perfect 1.0. `advanced_smc_long` and `advanced_smc_short` did exactly
that, and the strategist relayed it to the operator eleven times in one day:
that the arsenal was narrower than the rule count suggested, and that the
pair "will fail together".

A long and a short are the one pair that cannot fail together. Acting on
that advice would delete half the book's ability to express a direction, so
this is not a noisy finding — it is a backwards one, which costs more than
silence.

Run with:  python manage.py test tests.test_mirror_pairs_are_not_duplicates
"""
from django.test import SimpleTestCase, TestCase


class OpposedDirectionTests(SimpleTestCase):
    def test_the_two_vocabularies_this_codebase_uses(self):
        from brain.correlation_audit import _opposed
        self.assertTrue(_opposed("bullish", "bearish"))
        self.assertTrue(_opposed("bearish", "bullish"))
        self.assertTrue(_opposed("long", "short"))

    def test_case_and_padding_do_not_defeat_it(self):
        from brain.correlation_audit import _opposed
        self.assertTrue(_opposed("  BULLISH ", "Bearish"))

    def test_the_same_direction_is_not_opposition(self):
        from brain.correlation_audit import _opposed
        self.assertFalse(_opposed("bullish", "bullish"))
        self.assertFalse(_opposed("short", "short"))

    def test_an_unknown_direction_falls_through_to_the_audit(self):
        """An unrecognised value must NOT excuse a pair. Silently exempting
        whatever it cannot classify is how a detector stops detecting."""
        from brain.correlation_audit import _opposed
        self.assertFalse(_opposed("", "bearish"))
        self.assertFalse(_opposed(None, None))
        self.assertFalse(_opposed("sideways", "bearish"))
        self.assertFalse(_opposed("neutral", "neutral"))


class SignatureOverlapTests(TestCase):
    def _setup(self, name, direction, kinds):
        from signals.models_opportunity import OpportunitySetup
        return OpportunitySetup.objects.create(
            name=name, description="d", direction=direction,
            conditions=[{"kind": k, "params": {}, "weight": 1.0}
                        for k in kinds],
            min_match_score=0.5, is_active=True,
            asset_classes=["stock"], suggested_horizon_days=5)

    def _pairs(self):
        from brain.correlation_audit import detect_evaluator_signature_overlap
        return {f["key"] for f in detect_evaluator_signature_overlap()}

    def test_a_directional_mirror_is_not_reported(self):
        kinds = ["fair_value_gap", "relative_volume", "market_structure_break"]
        self._setup("mirror_long", "bullish", kinds)
        self._setup("mirror_short", "bearish", kinds)
        self.assertEqual(self._pairs(), set())

    def test_two_setups_pointing_the_same_way_are_still_reported(self):
        """The diversification illusion this detector exists to find is
        untouched — only the opposed case is excused."""
        kinds = ["fair_value_gap", "relative_volume", "market_structure_break"]
        self._setup("clone_a", "bullish", kinds)
        self._setup("clone_b", "bullish", kinds)
        self.assertEqual(self._pairs(), {"clone_a__VS__clone_b"})

    def test_the_real_pair_the_briefing_named_still_reports(self):
        """starter_commodity_vol_compression and starter_stock_mean_reversion
        are both bullish, so that finding was correct and must survive."""
        kinds = ["fair_value_gap", "relative_volume"]
        self._setup("starter_commodity_vol_compression", "bullish", kinds)
        self._setup("starter_stock_mean_reversion", "bullish", kinds)
        self.assertIn(
            "starter_commodity_vol_compression__VS__starter_stock_mean_reversion",
            self._pairs())

    def test_an_unknown_direction_is_still_audited(self):
        kinds = ["fair_value_gap", "relative_volume", "market_structure_break"]
        self._setup("odd_a", "bullish", kinds)
        self._setup("odd_b", "sideways", kinds)
        self.assertEqual(self._pairs(), {"odd_a__VS__odd_b"})

    def test_the_shipped_smc_pair_stops_being_flagged(self):
        """End to end on the real seeded rows, which is where this was found."""
        from django.core.management import call_command
        call_command("seed_advanced_strategies", verbosity=0)
        from signals.models_opportunity import OpportunitySetup
        OpportunitySetup.objects.filter(
            name__in=["advanced_smc_long", "advanced_smc_short"]
        ).update(is_active=True)
        flagged = self._pairs()
        self.assertNotIn("advanced_smc_long__VS__advanced_smc_short", flagged)
