"""Tests for Phase 47 — trust-weighted brain context injection.

Covers:
  - brain_trust_band: maps score → high/medium/low/unknown
  - context_for_prompt: low-trust outputs a heavily softened block with warning
  - context_for_prompt: medium-trust shows "preliminary read" header
  - context_for_prompt: high-trust shows full authoritative block
  - context_for_prompt: unknown (None score) shows full block (bootstrap)
  - brain_rule_advisory: low-trust downgrades pause_recommended → watch
  - brain_rule_advisory: KnowledgeNode-sourced advisories are NOT softened
  - brain_theme_pressure_multiplier: trust factor scales squeeze
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _make_brain_report(**overrides):
    from brain.models import BrainReport
    defaults = dict(
        regime_label="trending", regime_confidence=0.7,
        portfolio_health_score=0.6,
        top_concerns=[{"kind": "decay", "severity": 0.7, "text": "x"}],
        theme_pressures={"usd": 0.6},
        rule_status_overlay={"r1": "pause_recommended", "r2": "watch"},
        valid_until=timezone.now() + timedelta(minutes=30),
    )
    defaults.update(overrides)
    return BrainReport.objects.create(**defaults)


# ── brain_trust_band ──────────────────────────────────────────────────────

class BrainTrustBandTests(TestCase):
    def test_high_band(self):
        from brain.context import brain_trust_band
        self.assertEqual(brain_trust_band(0.7), "high")
        self.assertEqual(brain_trust_band(0.6), "high")
        self.assertEqual(brain_trust_band(1.0), "high")

    def test_medium_band(self):
        from brain.context import brain_trust_band
        self.assertEqual(brain_trust_band(0.5), "medium")
        self.assertEqual(brain_trust_band(0.4), "medium")

    def test_low_band(self):
        from brain.context import brain_trust_band
        self.assertEqual(brain_trust_band(0.39), "low")
        self.assertEqual(brain_trust_band(0.0), "low")

    def test_none_returns_unknown(self):
        from brain.context import brain_trust_band
        with patch("brain.context._brain_trust_score", return_value=None):
            self.assertEqual(brain_trust_band(), "unknown")


# ── context_for_prompt — branches by trust band ───────────────────────────

class ContextForPromptByTrustTests(TestCase):
    def test_low_trust_outputs_softened_block(self):
        from brain.context import context_for_prompt
        _make_brain_report()
        with patch("brain.context._brain_trust_score", return_value=0.2):
            block = context_for_prompt()
        self.assertIn("LOW-TRUST", block)
        # Theme pressures + rule overlay should NOT be in the low-trust block.
        self.assertNotIn("Theme pressures", block)
        self.assertNotIn("Rule overlay", block)
        # Should contain explicit warning verbiage.
        self.assertIn("weak prior", block)

    def test_medium_trust_shows_preliminary_header(self):
        from brain.context import context_for_prompt
        _make_brain_report()
        with patch("brain.context._brain_trust_score", return_value=0.5):
            block = context_for_prompt()
        self.assertIn("preliminary read", block)
        # Full block content present.
        self.assertIn("Theme pressures", block)
        self.assertIn("Rule overlay", block)

    def test_high_trust_full_block(self):
        from brain.context import context_for_prompt
        _make_brain_report()
        with patch("brain.context._brain_trust_score", return_value=0.85):
            block = context_for_prompt()
        # No softening header markers.
        self.assertNotIn("LOW-TRUST", block)
        self.assertNotIn("preliminary read", block)
        self.assertIn("latest synthesis", block)
        self.assertIn("Theme pressures", block)
        self.assertIn("Rule overlay", block)
        self.assertIn("Top concerns", block)

    def test_unknown_trust_uses_full_block(self):
        from brain.context import context_for_prompt
        _make_brain_report()
        with patch("brain.context._brain_trust_score", return_value=None):
            block = context_for_prompt()
        # Calibration bootstrap = treat as full strength.
        self.assertNotIn("LOW-TRUST", block)
        self.assertNotIn("preliminary read", block)
        self.assertIn("Theme pressures", block)


# ── brain_rule_advisory — softening rules ────────────────────────────────

class BrainRuleAdvisorySofteningTests(TestCase):
    def test_low_trust_downgrades_pause_to_watch_for_report_only(self):
        """When the advisory comes from BrainReport (not KG) AND brain trust is
        low, pause_recommended → watch."""
        from brain.context import brain_rule_advisory
        _make_brain_report(rule_status_overlay={"some_rule": "pause_recommended"})
        with patch("brain.context._brain_trust_score", return_value=0.2):
            status, why = brain_rule_advisory("some_rule")
        self.assertEqual(status, "watch")
        self.assertIn("softened", why)
        self.assertIn("trust=low", why)

    def test_high_trust_keeps_pause(self):
        from brain.context import brain_rule_advisory
        _make_brain_report(rule_status_overlay={"keep_pause": "pause_recommended"})
        with patch("brain.context._brain_trust_score", return_value=0.85):
            status, why = brain_rule_advisory("keep_pause")
        self.assertEqual(status, "pause_recommended")
        self.assertNotIn("softened", why)

    def test_knowledge_graph_sourced_advisory_NOT_softened(self):
        """KnowledgeNode-sourced advisories come from consolidation (multi-source)
        and should NOT be softened by brain trust."""
        from brain.context import brain_rule_advisory
        from brain.knowledge_models import KnowledgeNode
        KnowledgeNode.upsert(
            kind="rule_state", key="kg_rule",
            payload={"status": "pause_recommended"},
            confidence=0.8, source="consolidation",
        )
        # Even with low brain trust, the KG-sourced advisory holds.
        with patch("brain.context._brain_trust_score", return_value=0.2):
            status, why = brain_rule_advisory("kg_rule")
        self.assertEqual(status, "pause_recommended")
        self.assertIn("knowledge_graph", why)
        self.assertNotIn("softened", why)

    def test_watch_unchanged_at_low_trust(self):
        """A watch advisory at low trust stays watch (no further softening
        below watch — that's the floor for non-allow signals)."""
        from brain.context import brain_rule_advisory
        _make_brain_report(rule_status_overlay={"w_rule": "watch"})
        with patch("brain.context._brain_trust_score", return_value=0.2):
            status, _ = brain_rule_advisory("w_rule")
        self.assertEqual(status, "watch")


# ── brain_theme_pressure_multiplier — trust factor ───────────────────────

class BrainThemePressureMultiplierTrustTests(TestCase):
    def test_high_trust_full_squeeze(self):
        from brain.context import brain_theme_pressure_multiplier
        _make_brain_report(theme_pressures={"usd": 1.0})
        with patch("brain.context._brain_trust_score", return_value=0.8):
            mult = brain_theme_pressure_multiplier("usd", max_squeeze=0.5)
        # trust_factor=1.0 → 1.0 - 1.0*0.5*1.0 = 0.5
        self.assertAlmostEqual(mult, 0.5)

    def test_medium_trust_partial_squeeze(self):
        from brain.context import brain_theme_pressure_multiplier
        _make_brain_report(theme_pressures={"usd": 1.0})
        with patch("brain.context._brain_trust_score", return_value=0.5):
            mult = brain_theme_pressure_multiplier("usd", max_squeeze=0.5)
        # trust_factor=0.6 → 1.0 - 1.0*0.5*0.6 = 0.7
        self.assertAlmostEqual(mult, 0.7)

    def test_low_trust_minimal_squeeze(self):
        from brain.context import brain_theme_pressure_multiplier
        _make_brain_report(theme_pressures={"usd": 1.0})
        with patch("brain.context._brain_trust_score", return_value=0.2):
            mult = brain_theme_pressure_multiplier("usd", max_squeeze=0.5)
        # trust_factor=0.2 → 1.0 - 1.0*0.5*0.2 = 0.9
        self.assertAlmostEqual(mult, 0.9)

    def test_unknown_trust_full_strength(self):
        from brain.context import brain_theme_pressure_multiplier
        _make_brain_report(theme_pressures={"usd": 1.0})
        with patch("brain.context._brain_trust_score", return_value=None):
            mult = brain_theme_pressure_multiplier("usd", max_squeeze=0.5)
        # Bootstrap = full strength → 0.5
        self.assertAlmostEqual(mult, 0.5)
