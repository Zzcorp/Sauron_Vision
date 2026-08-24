"""Tests for the Phase-3 AI operational layer.

Mocks the Claude provider so no real API calls are made.

Covers:
  - PreTradeSanityAgent — JSON parsing, malformed-input fallback
  - SignalJournalAgent — auto-journal on close, threshold gate
  - DecayInvestigatorAgent — only fires when decay_flag actually flagged
  - Risk gate use_ai_check=True wires the AI agent through

Run with:  python manage.py test tests.test_phase3_ai
"""
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone


def _mock_claude(response_dict, input_tokens=120, output_tokens=80):
    """Build a callable suitable for patching ClaudeProvider.complete."""
    text = json.dumps(response_dict)
    usage = {"input_tokens": input_tokens, "output_tokens": output_tokens, "cost_usd": 0.001}

    def fake_complete(self, system_prompt, user_message,
                       model="claude-sonnet-5", effort=None,
                       agent_name="unattributed", record=True,
                       source_ref=""):
        # Mirrors the real contract, ledger kwargs included — a stub
        # frozen on the old shape TypeErrors every caller it stands in
        # for (the live_session stub caught the same change twice).
        return text, usage
    return fake_complete


def _instrument(symbol, asset_class="forex"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _signal(rule_name="rule_a", **overrides):
    from signals.models import Signal
    inst = _instrument(overrides.pop("symbol", "SIG_TEST"))
    defaults = dict(
        instrument=inst, signal_type="composite",
        direction="bullish", urgency="medium",
        title="t", description="t", rule_name=rule_name,
        score=0.7, sub_scores={},
        price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
        suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
        risk_reward_ratio=2.0,
    )
    defaults.update(overrides)
    return Signal.objects.create(**defaults)


# ── PreTradeSanityAgent ─────────────────────────────────────────────────────

class PreTradeSanityAgentTests(TestCase):
    @patch("ai_agents.providers.claude_provider.ClaudeProvider.complete",
           _mock_claude({"verdict": "go", "scale": 1.0,
                         "concerns": [], "rationale": "looks fine"}))
    def test_clean_go_verdict(self):
        from ai_agents.agents.pretrade_sanity import check_proposed_trade
        result = check_proposed_trade(
            symbol="EURUSD", direction="long",
            entry=1.085, stop=1.080, target=1.095,
            rule_name="rule_a",
        )
        self.assertEqual(result["verdict"], "go")
        self.assertEqual(result["scale"], 1.0)
        self.assertEqual(result["concerns"], [])

    @patch("ai_agents.providers.claude_provider.ClaudeProvider.complete",
           _mock_claude({"verdict": "scale_down", "scale": 0.5,
                         "concerns": ["news risk", "macro contradiction"],
                         "rationale": "two moderate concerns"}))
    def test_scale_down_verdict_clamped(self):
        from ai_agents.agents.pretrade_sanity import check_proposed_trade
        result = check_proposed_trade(symbol="EURUSD", direction="long",
                                      entry=1, stop=1, target=1)
        self.assertEqual(result["verdict"], "scale_down")
        self.assertEqual(result["scale"], 0.5)
        self.assertEqual(len(result["concerns"]), 2)

    @patch("ai_agents.providers.claude_provider.ClaudeProvider.complete",
           lambda self, system_prompt, user_message, model="x", effort=None,
                  agent_name="unattributed", record=True, source_ref="":
               ("not json at all",
                {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0}))
    def test_malformed_response_fails_closed(self):
        from ai_agents.agents.pretrade_sanity import check_proposed_trade
        result = check_proposed_trade(symbol="X", direction="long",
                                      entry=1, stop=1, target=1)
        # Malformed JSON must not crash and must fail CLOSED: an unparseable
        # sanity check gives no assurance, so abort with scale 0.0.
        self.assertEqual(result["verdict"], "abort")
        self.assertEqual(result["scale"], 0.0)
        self.assertTrue(result["concerns"])


# ── SignalJournalAgent ──────────────────────────────────────────────────────

class SignalJournalAgentTests(TestCase):
    JOURNAL_RESPONSE = {
        "summary": "Solid breakout setup, executed cleanly.",
        "key_takeaway": "Stick to the trigger criteria.",
        "grade": "B",
        "lessons": ["Confirm volume on breakout", "Don't chase late"],
        "tags": ["breakout", "momentum"],
        "emotional_state": "disciplined",
    }

    def _close(self, sig, r):
        sig.is_active = False
        sig.outcome = "hit_target" if r > 0 else "stopped_out"
        sig.realized_r = r
        sig.expired_at = timezone.now()
        sig.time_to_outcome_seconds = 3600
        sig.save()
        return sig

    @patch("ai_agents.providers.claude_provider.ClaudeProvider.complete",
           _mock_claude(JOURNAL_RESPONSE))
    def test_journal_created_when_above_threshold(self):
        from ai_agents.agents.signal_journal import journal_closed_signal
        from ai_agents.models import TradeJournalEntry
        sig = self._close(_signal(), 2.0)  # |R| = 2.0 > 0.5 threshold
        entry = journal_closed_signal(sig)
        self.assertIsNotNone(entry)
        self.assertEqual(entry.grade, "B")
        self.assertEqual(entry.signal, sig)
        self.assertEqual(entry.tags, ["breakout", "momentum"])
        self.assertEqual(TradeJournalEntry.objects.count(), 1)

    def test_skipped_when_below_threshold(self):
        """Default threshold = 0.5R, so a 0.3R outcome should not trigger."""
        from ai_agents.agents.signal_journal import journal_closed_signal
        sig = self._close(_signal(), 0.3)
        entry = journal_closed_signal(sig)
        self.assertIsNone(entry)

    def test_skipped_when_signal_active(self):
        from ai_agents.agents.signal_journal import journal_closed_signal
        sig = _signal()
        # Don't close it
        entry = journal_closed_signal(sig)
        self.assertIsNone(entry)

    @patch("ai_agents.providers.claude_provider.ClaudeProvider.complete",
           _mock_claude(JOURNAL_RESPONSE))
    def test_force_bypasses_threshold(self):
        from ai_agents.agents.signal_journal import journal_closed_signal
        sig = self._close(_signal(), 0.1)
        entry = journal_closed_signal(sig, force=True)
        self.assertIsNotNone(entry)


# ── DecayInvestigatorAgent ──────────────────────────────────────────────────

class DecayInvestigatorAgentTests(TestCase):
    DECAY_RESPONSE = {
        "hypothesis": "The rule was tuned for trending regimes; "
                      "the last two weeks show a range-bound regime.",
        "contributing_factors": ["regime shift", "volatility compression"],
        "recommended_action": "reduce_size",
    }

    def _close(self, sig, r, days_ago):
        sig.is_active = False
        sig.outcome = "hit_target" if r > 0 else "stopped_out"
        sig.realized_r = r
        sig.expired_at = timezone.now() - timedelta(days=days_ago)
        sig.time_to_outcome_seconds = 3600
        sig.save()

    def test_skipped_when_rule_not_decaying(self):
        from ai_agents.agents.decay_investigator import investigate_decaying_rule
        # 10 hits at +2R — not decaying
        for i in range(10):
            self._close(_signal(rule_name="solid"), 2.0, days_ago=i + 1)
        result = investigate_decaying_rule("solid")
        self.assertIsNone(result)

    @patch("ai_agents.providers.claude_provider.ClaudeProvider.complete",
           _mock_claude(DECAY_RESPONSE))
    def test_creates_investigation_when_decaying(self):
        from ai_agents.agents.decay_investigator import investigate_decaying_rule
        from ai_agents.models import DecayInvestigation
        # Baseline winners (50–80d ago) + recent stops (last 14d) → decay pattern
        for i in range(5):
            self._close(_signal(rule_name="decay_x", symbol=f"BASE{i}"), 2.0, days_ago=50 + i * 5)
        for i in range(5):
            self._close(_signal(rule_name="decay_x", symbol=f"REC{i}"), -1.0, days_ago=i + 1)

        inv = investigate_decaying_rule("decay_x")
        self.assertIsNotNone(inv)
        self.assertEqual(inv.recommended_action, "reduce_size")
        self.assertIn("regime", inv.hypothesis.lower())
        self.assertEqual(DecayInvestigation.objects.count(), 1)


# ── Risk gate AI hook ───────────────────────────────────────────────────────

class RiskGateAICheckTests(TestCase):
    @patch("ai_agents.providers.claude_provider.ClaudeProvider.complete",
           _mock_claude({"verdict": "scale_down", "scale": 0.4,
                         "concerns": ["macro contradiction"],
                         "rationale": "Fed hawkish pivot contradicts long thesis"}))
    def test_use_ai_check_scales_down_when_agent_returns_scale_down(self):
        from portfolio.risk_gate import evaluate_proposed_trade
        from portfolio.services import get_or_create_default_portfolio
        portfolio = get_or_create_default_portfolio()
        inst = _instrument("GATE_AI")
        result = evaluate_proposed_trade(
            portfolio, inst, intended_size_usd=500,
            use_ai_check=True,
            ai_context={"regime_summary": "Hawkish Fed", "news_summary": "soft data"},
        )
        self.assertIn("ai_sanity", result["checks"])
        self.assertEqual(result["checks"]["ai_sanity"]["verdict"], "scale_down")
        # Scale should be ≤ 0.4 (the AI's scale, possibly compounded with correlation=1.0)
        self.assertLessEqual(result["scale"], 0.4)

    def test_use_ai_check_false_skips_ai_call(self):
        from portfolio.risk_gate import evaluate_proposed_trade
        from portfolio.services import get_or_create_default_portfolio
        portfolio = get_or_create_default_portfolio()
        inst = _instrument("GATE_NO_AI")
        result = evaluate_proposed_trade(portfolio, inst, intended_size_usd=500)
        self.assertNotIn("ai_sanity", result["checks"])
