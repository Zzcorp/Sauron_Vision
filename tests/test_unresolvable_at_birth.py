"""A forecast about a rule that cannot trade is unresolvable at birth.

The 2026-08-30 briefing: sauron_mind trust 0.00, thirty-plus hypotheses
resolved UNRESOLVABLE, "a self-inflicted blind spot". Checked against
production the same morning: golden_cross emitted 0 signals and 0 trades
in three days while the brain kept posting decay forecasts about it.

`_validate_criteria` refused a rule_avg_r claim for a missing rule_name,
an unknown comparator, a non-finite threshold and a non-integer window —
every one of them a question about whether the resolver could PARSE the
claim. None of them asked whether the rule could produce a trade to grade
it against.

WHAT THIS DOES AND DOES NOT COST. It does not cost trust:
`agent_trust_score` excludes UNRESOLVABLE deliberately, because those are
the platform's blind spots and not the agent's misses. It costs the
agent's entire forecasting budget — every horizon spent on a claim that
can never grade is one not spent on a claim that could, which is how an
agent forecasts for a fortnight and ends with no record at all.

THE GATE READS ENFORCEMENT STATE, NOT THE MARKET. A quiet rule may fire
tomorrow and a forecast about it is perfectly legitimate. A rule the
platform has switched off cannot, and that is a fact we already hold.

Run with:  python manage.py test tests.test_unresolvable_at_birth
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone


def _criteria(**over):
    base = {"kind": "rule_avg_r", "rule_name": "golden_cross",
            "comparator": "<", "threshold": 0.0,
            "window_days": 7, "min_n": 3}
    base.update(over)
    return base


def _control(rule="golden_cross", **fields):
    from signals.models_control import RuleControl
    defaults = {"status": RuleControl.STATUS_ACTIVE,
                "promotion_stage": RuleControl.STAGE_PAPER}
    defaults.update(fields)
    rc, _ = RuleControl.objects.update_or_create(
        rule_name=rule, defaults=defaults)
    return rc


class AResearchStageRuleIsStillForecastableTests(TestCase):
    """The refusal I nearly shipped, and the test that stopped it.

    `stage_policy` defines research as "no orders at all", so a research
    rule genuinely cannot produce a trade — which makes refusing its
    rule_avg_r claims look obviously right. It is not.

    Research is the ENTRY RUNG OF A LADDER, not a decision to stop.
    `promotion_pipeline` creates every RuleControl at that stage, and the
    generator posts a BIRTH HYPOTHESIS for each new rule immediately
    afterwards. `demoter` kills generated rules whose birth hypothesis is
    REFUTED — so refusing research-stage claims would have left every new
    rule without a birth hypothesis and quietly disabled the only thing
    that culls bad generated rules.

    A pause is a decision. A stage is a position on a ladder.
    """

    def test_a_research_stage_birth_hypothesis_is_allowed(self):
        from brain.hypotheses import post_hypothesis
        from signals.models_control import RuleControl
        _control(promotion_stage=RuleControl.STAGE_RESEARCH)
        h = post_hypothesis(claim_text="golden_cross decays",
                            source_agent="strategy_generator",
                            resolution_criteria=_criteria(),
                            horizon_hours=168)
        self.assertIsNotNone(h.pk)

    def test_a_paper_stage_rule_is_forecastable(self):
        """Paper trades at full nominal size on the paper venue — those
        are real closed trades and they grade the claim."""
        from brain.hypotheses import post_hypothesis
        from signals.models_control import RuleControl
        _control(promotion_stage=RuleControl.STAGE_PAPER)
        h = post_hypothesis(claim_text="golden_cross decays",
                            source_agent="sauron_mind",
                            resolution_criteria=_criteria(),
                            horizon_hours=168)
        self.assertIsNotNone(h.pk)

    def test_and_so_is_a_live_one(self):
        from brain.hypotheses import post_hypothesis
        from signals.models_control import RuleControl
        _control(promotion_stage=RuleControl.STAGE_LIVE_SMALL)
        self.assertIsNotNone(
            post_hypothesis(claim_text="c", source_agent="a",
                            resolution_criteria=_criteria(),
                            horizon_hours=24).pk)


class APausedRuleIsJudgedAgainstTheDeadlineTests(TestCase):
    """Paused is not automatically unmeasurable — it depends on whether
    the rule comes back inside the claim's own horizon."""

    def test_paused_with_no_scheduled_return_is_refused(self):
        from brain.hypotheses import UnmeasurableClaim, post_hypothesis
        from signals.models_control import RuleControl
        _control(status=RuleControl.STATUS_PAUSED, paused_until=None)
        with self.assertRaises(UnmeasurableClaim) as ctx:
            post_hypothesis(claim_text="c", source_agent="a",
                            resolution_criteria=_criteria(),
                            horizon_hours=24)
        self.assertIn("PAUSED", str(ctx.exception))

    def test_paused_past_the_deadline_is_refused(self):
        from brain.hypotheses import UnmeasurableClaim, post_hypothesis
        from signals.models_control import RuleControl
        _control(status=RuleControl.STATUS_PAUSED,
                 paused_until=timezone.now() + timedelta(days=30))
        with self.assertRaises(UnmeasurableClaim):
            post_hypothesis(claim_text="c", source_agent="a",
                            resolution_criteria=_criteria(),
                            horizon_hours=24)

    def test_but_a_rule_that_returns_inside_the_window_is_allowed(self):
        """THE ASSERTION THAT KEEPS THIS GATE HONEST. It resumes in six
        hours against a 24h horizon, so it has eighteen hours in which to
        produce the trades that grade the claim. Refusing here would be
        the gate overreaching."""
        from brain.hypotheses import post_hypothesis
        from signals.models_control import RuleControl
        _control(status=RuleControl.STATUS_PAUSED,
                 paused_until=timezone.now() + timedelta(hours=6))
        h = post_hypothesis(claim_text="c", source_agent="a",
                            resolution_criteria=_criteria(),
                            horizon_hours=24)
        self.assertIsNotNone(h.pk)

    def test_an_expired_pause_is_not_a_pause(self):
        """`is_effectively_active` auto-reactivates on a lapsed
        `paused_until`, and the raw `status` column still reads paused —
        the model's own docstring warns that querying `status` subtracts
        rules that are live."""
        from brain.hypotheses import post_hypothesis
        from signals.models_control import RuleControl
        _control(status=RuleControl.STATUS_PAUSED,
                 paused_until=timezone.now() - timedelta(hours=1))
        self.assertIsNotNone(
            post_hypothesis(claim_text="c", source_agent="a",
                            resolution_criteria=_criteria(),
                            horizon_hours=24).pk)

    def test_reduced_is_not_silenced(self):
        """REDUCED trades at smaller size. It still produces evidence."""
        from brain.hypotheses import post_hypothesis
        from signals.models_control import RuleControl
        _control(status=RuleControl.STATUS_REDUCED)
        self.assertIsNotNone(
            post_hypothesis(claim_text="c", source_agent="a",
                            resolution_criteria=_criteria(),
                            horizon_hours=24).pk)


class TheGateFailsOpenTests(TestCase):
    """The risky half. Blocking an agent's forecast on OUR outage is the
    same mistake as grading it on our blind spot, pointed the other way."""

    def test_a_rule_with_no_control_row_is_allowed(self):
        """Unknown to the control layer is not known-and-silenced.
        Refusing here would reject every claim about a new rule."""
        from brain.hypotheses import post_hypothesis
        from signals.models_control import RuleControl
        RuleControl.objects.filter(rule_name="golden_cross").delete()
        self.assertIsNotNone(
            post_hypothesis(claim_text="c", source_agent="a",
                            resolution_criteria=_criteria(),
                            horizon_hours=24).pk)

    def test_an_unreadable_control_layer_is_allowed(self):
        from brain.hypotheses import post_hypothesis
        with patch("signals.models_control.RuleControl.objects") as mgr:
            mgr.filter.side_effect = RuntimeError("db down")
            self.assertIsNotNone(
                post_hypothesis(claim_text="c", source_agent="a",
                                resolution_criteria=_criteria(),
                                horizon_hours=24).pk)

    def test_other_claim_kinds_are_untouched(self):
        """regime_holds and anomaly_persists name no rule and must not be
        dragged through a rule check."""
        from brain.hypotheses import post_hypothesis
        from signals.models_control import RuleControl
        _control(promotion_stage=RuleControl.STAGE_RESEARCH)
        self.assertIsNotNone(
            post_hypothesis(claim_text="c", source_agent="a",
                            resolution_criteria={"kind": "regime_holds",
                                                 "regime": "mean_reverting"},
                            horizon_hours=24).pk)


class TheShapeChecksStillFireTests(TestCase):
    """The new gate is additional, not a replacement — a claim can be
    unmeasurable for its shape before the rule is ever looked up."""

    def test_a_missing_rule_name_is_still_refused(self):
        from brain.hypotheses import UnmeasurableClaim, post_hypothesis
        with self.assertRaises(UnmeasurableClaim):
            post_hypothesis(claim_text="c", source_agent="a",
                            resolution_criteria=_criteria(rule_name=""),
                            horizon_hours=24)

    def test_a_non_finite_threshold_is_still_refused(self):
        from brain.hypotheses import UnmeasurableClaim, post_hypothesis
        _control()
        with self.assertRaises(UnmeasurableClaim):
            post_hypothesis(claim_text="c", source_agent="a",
                            resolution_criteria=_criteria(
                                threshold=float("inf")),
                            horizon_hours=24)


class APausedRuleHoldingAPositionIsGradeableTests(TestCase):
    """The counterexample that broke the second version of this gate.

    A PAUSE STOPS ENTRIES, NOT EXITS. `test_position_review` creates a
    paused rule, opens a position on it, and asserts a rule_avg_r claim
    IS posted — because that open trade will close, and the resolver
    counts trades closed since the claim was posted.

    The position reviewer posts precisely into this case: it flags
    `rule_decayed` on an open position and bets on that rule's forward R.
    Refusing it would have deleted the reviewer's only gradeable output.

    So the gate needs BOTH halves to be impossible — no entry can open
    AND nothing is open to close. Either alone is a guess; together they
    are an impossibility proof.
    """

    def _open_trade(self, rule="golden_cross", status="OPEN"):
        from decimal import Decimal
        from django.contrib.auth.models import User
        from bot_program.models import AssetBotConfig, AssetBotTrade
        u = User.objects.create_user(f"pr_{rule}_{status}", password="x")
        cfg = AssetBotConfig.objects.create(
            user=u, asset_class="stock", name="C", mode="paper",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
        return AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"),
            stop_loss=Decimal("99"), status=status, paper=True,
            rule_name=rule, opened_at=timezone.now())

    def test_a_paused_rule_with_an_open_position_is_allowed(self):
        from brain.hypotheses import post_hypothesis
        from signals.models_control import RuleControl
        _control(status=RuleControl.STATUS_PAUSED, paused_until=None)
        self._open_trade()
        self.assertIsNotNone(
            post_hypothesis(claim_text="c", source_agent="position_reviewer",
                            resolution_criteria=_criteria(),
                            horizon_hours=24).pk)

    def test_a_close_pending_position_counts_too(self):
        """It is still capital at the broker and it still books a close."""
        from brain.hypotheses import post_hypothesis
        from signals.models_control import RuleControl
        _control(status=RuleControl.STATUS_PAUSED, paused_until=None)
        self._open_trade(status="CLOSE_PENDING")
        self.assertIsNotNone(
            post_hypothesis(claim_text="c", source_agent="a",
                            resolution_criteria=_criteria(),
                            horizon_hours=24).pk)

    def test_a_closed_position_does_not_rescue_the_claim(self):
        """Already closed is evidence that exists BEFORE the claim, and the
        resolver only counts trades closed since it was posted."""
        from brain.hypotheses import UnmeasurableClaim, post_hypothesis
        from signals.models_control import RuleControl
        _control(status=RuleControl.STATUS_PAUSED, paused_until=None)
        self._open_trade(status="CLOSED")
        with self.assertRaises(UnmeasurableClaim):
            post_hypothesis(claim_text="c", source_agent="a",
                            resolution_criteria=_criteria(),
                            horizon_hours=24)

    def test_an_open_position_on_a_DIFFERENT_rule_does_not_count(self):
        from brain.hypotheses import UnmeasurableClaim, post_hypothesis
        from signals.models_control import RuleControl
        _control(status=RuleControl.STATUS_PAUSED, paused_until=None)
        self._open_trade(rule="some_other_rule")
        with self.assertRaises(UnmeasurableClaim):
            post_hypothesis(claim_text="c", source_agent="a",
                            resolution_criteria=_criteria(),
                            horizon_hours=24)

    def test_the_refusal_names_both_halves(self):
        """So the next person reads why, not just that."""
        from brain.hypotheses import UnmeasurableClaim, post_hypothesis
        from signals.models_control import RuleControl
        _control(status=RuleControl.STATUS_PAUSED, paused_until=None)
        with self.assertRaises(UnmeasurableClaim) as ctx:
            post_hypothesis(claim_text="c", source_agent="a",
                            resolution_criteria=_criteria(),
                            horizon_hours=24)
        msg = str(ctx.exception)
        self.assertIn("PAUSED", msg)
        self.assertIn("no open position", msg)
