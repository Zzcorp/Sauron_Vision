"""One active Signal per (instrument, setup) — the vote the scanner doubled.

The rule engine has always deduped: `signals/tasks.py` skips a rule whose
instrument already carries an active Signal for it. The opportunity scanner
never did. `_emit_match` called `Signal.objects.create` unconditionally, so a
setup that still matched on a later pass — the 09:00 beat, then an admin's
Run Now inside the same 24h window — left two identical active rows.

That is not a cosmetic duplicate. `aggregation.side_weight` sums evidence
PER ROW (`total += contribution`) while `rules` is a SET of names, so one
setup's 0.80 counted twice for a net weight of 1.60 against a rule count of
one — enough to clear `min_net_weight` and, with the default
`min_signals=1`, to carry a direction on its own against a genuine opposing
rule. `AssetBot.decide`'s top-32 cut states the same invariant in as many
words: "per-rule dedupe keeps the real row count near the rule count".

The row-count test is the cheap one; the test that matters is the WEIGHT.

Run with:  python manage.py test tests.test_scanner_dedupe
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol,
        defaults={"name": symbol, "asset_class": asset_class})
    return inst


class ScannerDedupeTests(TestCase):

    def setUp(self):
        from market_data.models import PriceData
        from signals.models import OpportunitySetup

        self.inst = _instrument("DUPE1", "stock")
        PriceData.objects.create(
            instrument=self.inst, timeframe="1d",
            timestamp=timezone.now() - timedelta(hours=1),
            open=Decimal("100"), high=Decimal("100"), low=Decimal("100"),
            close=Decimal("100"), volume=0, source="test")
        self.setup = OpportunitySetup.objects.create(
            name="dupe_setup", direction="bullish", conditions=[],
            min_match_score=0.0, suggested_horizon_days=5, asset_classes=[],
            sizing={"stop_pct": 2.0, "target_rr": 2.0}, is_active=True)

    def _scan(self):
        from signals.opportunity_scanner import scan_setup
        return scan_setup(self.setup, self.inst, as_of=False)

    def _active(self):
        from signals.models import Signal
        return Signal.objects.filter(instrument=self.inst,
                                     rule_name="dupe_setup", is_active=True)

    # ── the row count ───────────────────────────────────────────────────

    def test_a_setup_that_matches_twice_leaves_one_active_signal(self):
        first = self._scan()
        second = self._scan()

        self.assertTrue(first["matched"])
        self.assertTrue(second["matched"])
        self.assertEqual(self._active().count(), 1)
        self.assertEqual(first["signal_id"], second["signal_id"])

    def test_the_second_match_still_records_its_own_flag(self):
        """Deduping the vote must not cost the scanner its history — a flag
        is a MOMENT, and `resolve_pending_flags` grades flags, not signals."""
        from signals.models import OpportunityFlag
        self._scan()
        self._scan()
        self.assertEqual(
            OpportunityFlag.objects.filter(setup=self.setup,
                                           instrument=self.inst).count(), 2)

    def test_a_closed_signal_does_not_block_the_next_one(self):
        from signals.models import Signal
        self._scan()
        Signal.objects.filter(instrument=self.inst).update(
            is_active=False, outcome="expired", expired_at=timezone.now())

        self._scan()

        self.assertEqual(
            Signal.objects.filter(instrument=self.inst,
                                  rule_name="dupe_setup").count(), 2)

    def test_the_reused_row_keeps_its_original_basis(self):
        """Grading measures R against `price_at_signal` and the levels. A
        refresh mid-life would re-anchor an outcome already in flight."""
        self._scan()
        row = self._active().first()
        before = (row.price_at_signal, row.suggested_entry,
                  row.suggested_stop, row.suggested_target)

        self._scan()

        row.refresh_from_db()
        self.assertEqual(
            (row.price_at_signal, row.suggested_entry,
             row.suggested_stop, row.suggested_target), before)

    # ── the weight, which is the part that reaches an order ─────────────

    def test_two_rows_for_one_rule_would_double_the_vote(self):
        """WHY the row count is a money question, not bookkeeping.

        Characterises `side_weight`: it sums `score * weight_for(rule)` per
        ROW while `rules` is a set of names. Two rows for one rule therefore
        carry twice the conviction the rule earned, and the reason string
        still reports one rule. This is the harm the dedupe above prevents —
        asserted here against explicit scores, because a scanned setup with
        no conditions composites to 0.0 and doubling zero proves nothing.

        If aggregation ever dedupes internally this test fails, and that is
        worth knowing: the scanner fix would then be belt-and-braces.
        """
        from bot_program.asset_engine.aggregation import weighted_consensus

        class _Row:
            def __init__(self, rule, score):
                self.rule_name, self.score = rule, score

        one = weighted_consensus([_Row("dupe_setup", 0.8)], [])
        two = weighted_consensus(
            [_Row("dupe_setup", 0.8), _Row("dupe_setup", 0.8)], [])

        self.assertNotEqual(one["net_weight"], two["net_weight"])
        self.assertAlmostEqual(two["net_weight"], one["net_weight"] * 2,
                               places=4)

    def test_and_the_scanner_never_produces_that_shape(self):
        """The link between the characterisation above and the fix."""
        self._scan()
        self._scan()
        rows = list(self._active().filter(signal_type="composite"))
        self.assertEqual(len(rows), 1)

    def test_and_the_rule_count_still_agrees_with_the_row_count(self):
        """The invariant decide()'s top-32 cut is written against."""
        self._scan()
        self._scan()
        rows = list(self._active())
        self.assertEqual(len(rows), len({r.rule_name for r in rows}))

    # ── the correction to the parked patch ──────────────────────────────

    def test_a_rule_engine_signal_of_the_same_name_is_not_adopted(self):
        """Setup names and rule names share the `rule_name` column.

        The parked patch filtered on (instrument, rule_name, is_active)
        alone, so a setup colliding with a rule-engine rule would adopt that
        rule's Signal and hang its OpportunityFlag on a row it did not
        write — a new cross-lane coupling introduced by the fix itself.
        `signal_type` is part of the lookup for that reason.
        """
        from signals.models import Signal

        foreign = Signal.objects.create(
            instrument=self.inst, signal_type="rule", direction="bullish",
            urgency="medium", title="rule engine got here first",
            rule_name="dupe_setup", score=0.9,
            price_at_signal=Decimal("100"))

        res = self._scan()

        self.assertNotEqual(res["signal_id"], foreign.id)
        self.assertEqual(
            Signal.objects.get(pk=res["signal_id"]).signal_type, "composite")
        # Exactly one COMPOSITE row — the foreign one is still there and
        # still the rule engine's, which is why the unfiltered count is 2.
        self.assertEqual(self._active().filter(
            signal_type="composite").count(), 1)
        self.assertEqual(self._active().count(), 2)
        foreign.refresh_from_db()
        self.assertTrue(foreign.is_active)

    def test_and_a_second_pass_still_dedupes_alongside_it(self):
        """The collision guard must not cost the scanner its own dedupe."""
        from signals.models import Signal

        Signal.objects.create(
            instrument=self.inst, signal_type="rule", direction="bullish",
            urgency="medium", title="rule engine got here first",
            rule_name="dupe_setup", score=0.9,
            price_at_signal=Decimal("100"))

        first = self._scan()
        second = self._scan()

        self.assertEqual(first["signal_id"], second["signal_id"])
        self.assertEqual(self._active().filter(
            signal_type="composite").count(), 1)
