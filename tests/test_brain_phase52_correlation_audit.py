"""Tests for Phase 52 — cross-rule correlation audit.

Covers:
  - _evaluator_signature: extracts kind set from conditions list
  - _jaccard: standard set similarity, empty-vs-empty edge case
  - detect_position_overlap: emits when 2+ rules hold same (symbol, side);
    no overlap → empty; ignores blank rule_name; respects min_overlap
  - detect_evaluator_signature_overlap: pairs above threshold emit;
    below threshold skipped; single-evaluator rules ignored
  - Integration: both detectors registered in anomaly_scanner.DETECTORS
  - Integration: scan_anomalies_now picks them up + persists observations
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="corr_t"):
    return User.objects.create_user(username=name, password="x")


def _bot_config(user, name="cfg"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="stock", name=name,
        enabled=True, mode="paper", symbols=["X"],
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
        entry_score_min=0.6, min_signals_for_entry=1,
    )


def _open_trade(cfg, symbol, side, rule_name):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol=symbol, side=side,
        qty=Decimal("1"), entry_price=Decimal("100"),
        stop_loss=Decimal("99"), take_profit=Decimal("103"),
        rule_name=rule_name, paper=True, status="OPEN",
    )


def _setup(name, conditions, *, direction="bullish", asset_classes=None):
    from signals.models_opportunity import OpportunitySetup
    return OpportunitySetup.objects.create(
        name=name, description="t", direction=direction,
        asset_classes=(["stock"] if asset_classes is None else asset_classes),
        conditions=conditions,
        min_match_score=0.6, suggested_horizon_days=5, sizing={},
        is_active=True,
    )


# ── Helpers ───────────────────────────────────────────────────────────────

class HelpersTests(TestCase):
    def test_evaluator_signature_extracts_kinds(self):
        from brain.correlation_audit import _evaluator_signature
        sig = _evaluator_signature([
            {"kind": "rvol", "weight": 1.0},
            {"kind": "macd", "weight": 0.5},
            {"kind": "rvol", "weight": 0.7},  # duplicate kind
        ])
        self.assertEqual(sig, frozenset({"rvol", "macd"}))

    def test_evaluator_signature_handles_garbage(self):
        from brain.correlation_audit import _evaluator_signature
        self.assertEqual(_evaluator_signature(None), frozenset())
        self.assertEqual(_evaluator_signature([{"weight": 1.0}]),
                          frozenset())

    def test_jaccard_basic(self):
        from brain.correlation_audit import _jaccard
        a = frozenset({"x", "y", "z"})
        b = frozenset({"x", "y"})
        self.assertAlmostEqual(_jaccard(a, b), 2 / 3)

    def test_jaccard_disjoint(self):
        from brain.correlation_audit import _jaccard
        self.assertEqual(_jaccard(frozenset({"a"}), frozenset({"b"})), 0.0)

    def test_jaccard_empty_returns_zero(self):
        from brain.correlation_audit import _jaccard
        self.assertEqual(_jaccard(frozenset(), frozenset()), 0.0)


# ── detect_position_overlap ──────────────────────────────────────────────

class DetectPositionOverlapTests(TestCase):
    def test_two_rules_same_symbol_side_emits_anomaly(self):
        from brain.correlation_audit import detect_position_overlap
        u = _user()
        cfg = _bot_config(u)
        _open_trade(cfg, "AAPL", "BUY", "momentum_a")
        _open_trade(cfg, "AAPL", "BUY", "momentum_b")
        anoms = detect_position_overlap(min_overlap=2)
        self.assertEqual(len(anoms), 1)
        a = anoms[0]
        self.assertEqual(a["symbol"], "AAPL")
        self.assertEqual(a["side"], "BUY")
        self.assertEqual(set(a["rules"]), {"momentum_a", "momentum_b"})

    def test_same_rule_twice_no_overlap(self):
        from brain.correlation_audit import detect_position_overlap
        u = _user()
        cfg = _bot_config(u)
        _open_trade(cfg, "AAPL", "BUY", "the_rule")
        _open_trade(cfg, "AAPL", "BUY", "the_rule")
        # Same rule_name → only one rule in the group → no overlap.
        self.assertEqual(detect_position_overlap(), [])

    def test_different_sides_no_overlap(self):
        from brain.correlation_audit import detect_position_overlap
        u = _user()
        cfg = _bot_config(u)
        _open_trade(cfg, "AAPL", "BUY", "long_rule")
        _open_trade(cfg, "AAPL", "SELL", "short_rule")
        self.assertEqual(detect_position_overlap(), [])

    def test_blank_rule_name_excluded(self):
        from brain.correlation_audit import detect_position_overlap
        u = _user()
        cfg = _bot_config(u)
        _open_trade(cfg, "AAPL", "BUY", "real_rule")
        _open_trade(cfg, "AAPL", "BUY", "")  # blank — excluded
        self.assertEqual(detect_position_overlap(), [])

    def test_three_rules_same_symbol_side(self):
        from brain.correlation_audit import detect_position_overlap
        u = _user()
        cfg = _bot_config(u)
        for r in ("a", "b", "c"):
            _open_trade(cfg, "MSFT", "BUY", r)
        anoms = detect_position_overlap()
        self.assertEqual(len(anoms), 1)
        self.assertEqual(anoms[0]["rule_count"], 3)


# ── detect_evaluator_signature_overlap ───────────────────────────────────

class DetectSignatureOverlapTests(TestCase):
    def test_high_overlap_emits(self):
        from brain.correlation_audit import detect_evaluator_signature_overlap
        # Both rules share 3 of 4 kinds = Jaccard 3/5 = 0.6 — below default 0.8
        # Use exact-match for high overlap.
        _setup("rule_a", [
            {"kind": "rvol", "weight": 1.0},
            {"kind": "macd", "weight": 1.0},
            {"kind": "rsi", "weight": 1.0},
        ])
        _setup("rule_b", [
            {"kind": "rvol", "weight": 0.5},
            {"kind": "macd", "weight": 0.5},
            {"kind": "rsi", "weight": 0.5},
        ])
        anoms = detect_evaluator_signature_overlap()
        self.assertEqual(len(anoms), 1)
        self.assertEqual(set([anoms[0]["rule_a"], anoms[0]["rule_b"]]),
                          {"rule_a", "rule_b"})
        self.assertGreaterEqual(anoms[0]["jaccard"], 0.8)

    def test_low_overlap_skipped(self):
        from brain.correlation_audit import detect_evaluator_signature_overlap
        _setup("rule_lo_a", [
            {"kind": "rvol", "weight": 1.0},
            {"kind": "macd", "weight": 1.0},
        ])
        _setup("rule_lo_b", [
            {"kind": "rsi", "weight": 1.0},
            {"kind": "atr", "weight": 1.0},
        ])
        # Disjoint sets → Jaccard 0.0
        self.assertEqual(detect_evaluator_signature_overlap(), [])

    def test_single_evaluator_rules_skipped(self):
        from brain.correlation_audit import detect_evaluator_signature_overlap
        # Single-evaluator setups are too noisy — skip.
        _setup("rule_solo_a", [{"kind": "rvol", "weight": 1.0}])
        _setup("rule_solo_b", [{"kind": "rvol", "weight": 1.0}])
        self.assertEqual(detect_evaluator_signature_overlap(), [])

    def test_threshold_param_respected(self):
        from brain.correlation_audit import detect_evaluator_signature_overlap
        _setup("rule_p_a", [
            {"kind": "rvol", "weight": 1.0},
            {"kind": "macd", "weight": 1.0},
        ])
        _setup("rule_p_b", [
            {"kind": "rvol", "weight": 1.0},
            {"kind": "rsi", "weight": 1.0},
        ])
        # Jaccard = 1/3 ≈ 0.33. Below 0.8, above 0.3.
        self.assertEqual(
            detect_evaluator_signature_overlap(threshold=0.8), [])
        anoms = detect_evaluator_signature_overlap(threshold=0.3)
        self.assertEqual(len(anoms), 1)


# ── Integration: registered in DETECTORS + observations persisted ────────

class IntegrationTests(TestCase):
    def test_phase52_detectors_in_DETECTORS(self):
        from brain.anomaly_scanner import DETECTORS
        from brain.correlation_audit import (
            detect_position_overlap,
            detect_evaluator_signature_overlap,
        )
        self.assertIn(detect_position_overlap, DETECTORS)
        self.assertIn(detect_evaluator_signature_overlap, DETECTORS)

    def test_scan_anomalies_now_picks_up_position_overlap(self):
        from brain.anomaly_scanner import scan_anomalies_now
        from brain.models import BrainObservation
        u = _user()
        cfg = _bot_config(u)
        _open_trade(cfg, "MSFT", "BUY", "rule_x")
        _open_trade(cfg, "MSFT", "BUY", "rule_y")
        result = scan_anomalies_now()
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(result["n_emitted"], 1)
        # The detector_summary picked it up.
        self.assertIn("detect_position_overlap", result["by_detector"])
        self.assertGreaterEqual(
            result["by_detector"]["detect_position_overlap"], 1)
        # Observation row persisted with the right detector field.
        anoms = BrainObservation.objects.filter(kind="anomaly_detected")
        self.assertTrue(anoms.exists())
        self.assertTrue(any(
            (obs.payload or {}).get("detector") == "position_overlap"
            for obs in anoms))


class RulesThatCannotMeetAreNotDuplicatesTests(TestCase):
    """The other half of the mirror-pair mistake.

    The signature is a set of evaluator KINDS and discards every param, so
    two rules reading the same INDICATORS on entirely different markets score
    a perfect 1.0. The platform's own shipped starters did it —
    starter_commodity_vol_compression (commodity) and
    starter_stock_mean_reversion (stock, etf) — and the strategist relayed it
    to the operator as evidence that the arsenal was narrower than the rule
    count suggested.

    Two rules that can never be scored against the same instrument cannot
    misfire together, however much their conditions rhyme.
    """

    CONDITIONS = [
        {"kind": "rsi", "op": "lt", "value": 30, "weight": 1},
        {"kind": "bollinger", "op": "lt", "value": 0.1, "weight": 1},
        {"kind": "volume", "op": "gt", "value": 1.5, "weight": 1},
    ]

    def _pair(self, classes_a, classes_b):
        """Exactly two setups in the world, so the count is the answer.

        The detector scores every ACTIVE setup against every other, so a
        test that builds a second pair without clearing the first also
        measures the four cross-pairs between them.
        """
        from brain.correlation_audit import detect_evaluator_signature_overlap
        from signals.models_opportunity import OpportunitySetup
        OpportunitySetup.objects.all().delete()
        _setup("rule_a", self.CONDITIONS, asset_classes=classes_a)
        _setup("rule_b", self.CONDITIONS, asset_classes=classes_b)
        return detect_evaluator_signature_overlap()

    def test_disjoint_universes_are_not_reported(self):
        self.assertEqual(self._pair(["commodity"], ["stock", "etf"]), [])

    def test_an_overlapping_universe_is_still_reported(self):
        """The detector must still do its job: same evaluators, same market,
        same direction is the diversification illusion it exists to find."""
        found = self._pair(["stock", "etf"], ["stock"])
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0]["jaccard"], 1.0)

    def test_an_identical_universe_is_still_reported(self):
        self.assertEqual(len(self._pair(["stock"], ["stock"])), 1)

    def test_an_empty_universe_means_everything_and_never_excuses_a_pair(self):
        """A value nobody set must not silently exempt a real duplicate —
        the same care `_opposed` takes with an unrecognised direction."""
        self.assertEqual(len(self._pair([], ["stock"])), 1)
        self.assertEqual(len(self._pair(["stock"], [])), 1)

    def test_a_non_list_universe_never_excuses_a_pair(self):
        self.assertEqual(len(self._pair(None, ["stock"])), 1)

    def test_case_and_whitespace_do_not_create_a_false_disjunction(self):
        """"Stock" and "stock " are the same market; treating them as
        disjoint would hide a genuine duplicate."""
        self.assertEqual(len(self._pair([" STOCK "], ["stock"])), 1)


class TheShippedStartersAreNotFlaggedTests(TestCase):
    """End to end on the real rules, because both false pairs the operator
    was shown came from the seeders rather than from a synthetic fixture."""

    def test_the_platforms_own_seeded_rules_produce_no_false_pair(self):
        from django.core.management import call_command
        from brain.correlation_audit import detect_evaluator_signature_overlap
        call_command("seed_strategies", "--activate", verbosity=0)
        call_command("seed_advanced_strategies", "--activate", verbosity=0)
        found = detect_evaluator_signature_overlap()
        names = {tuple(sorted((f["rule_a"], f["rule_b"]))) for f in found}
        self.assertNotIn(
            ("starter_commodity_vol_compression", "starter_stock_mean_reversion"),
            names, "disjoint markets reported as duplicated coverage")
        self.assertNotIn(
            ("advanced_smc_long", "advanced_smc_short"),
            names, "a long and its short mirror reported as duplicates")
