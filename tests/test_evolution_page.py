"""The evolution page has to make the mutation loop legible, and one
distinction on it is worth more than all the others: a mutant that was
NEVER MEASURED must not be able to pass for a mutant that was measured and
lost.

Both land in the table as a number below the parent. Only one of them is a
result. The other is `parent_mean + INSUFFICIENT_DATA_PENALTY` — a flat
-1.0R stamp meaning "fewer than MIN_TRADES_PER_SPLIT trades on one of the
four legs, so no delta was computed at all". Read as a loss, it retires a
mutation that might have been the good one; read as a result, it makes the
scorer look like it measured something it never touched.

Everything here is markup-level on purpose: the honesty has to survive in
what actually reaches the operator's screen, not only in the view's dicts.

Run with:  python manage.py test tests.test_evolution_page
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _leg(n, expectancy):
    """One walk-forward leg as `evolution_backtest.backtest_with_params`
    persists it into score_details."""
    return {"n": n, "expectancy": expectancy,
            "hit_rate": 0.5, "std": 0.4, "realized_r_list": []}


def _mutation(**overrides):
    from signals.models import RuleMutation
    defaults = dict(
        parent_rule="golden_cross",
        parent_params={"fast": 50, "slow": 200, "stop_pct": 0.05},
        mutated_params={"fast": 30, "slow": 200, "stop_pct": 0.05},
        parameters_changed=["fast"],
        parent_expectancy=0.20,
        proposed_score=0.31,
        score_method="walk_forward",
        state=RuleMutation.STATE_PROPOSED,
    )
    defaults.update(overrides)
    proposed_at = defaults.pop("proposed_at", None)
    mut = RuleMutation.objects.create(**defaults)
    if proposed_at is not None:
        # auto_now_add wins at create() — the row has to be aged afterwards.
        RuleMutation.objects.filter(id=mut.id).update(proposed_at=proposed_at)
        mut.refresh_from_db()
    return mut


def _measured_details(train_delta, test_delta):
    """A mutation that really was backtested: four legs above the floor."""
    return {
        "train_parent": _leg(30, 0.10), "train_mutant": _leg(28, 0.10 + train_delta),
        "test_parent": _leg(14, 0.08), "test_mutant": _leg(12, 0.08 + test_delta),
        "train_delta": train_delta, "test_delta": test_delta,
        "worst_delta": min(train_delta, test_delta),
        "sufficient_data": True,
        "notes": f"train Δ={train_delta:+.2f}R · test Δ={test_delta:+.2f}R",
    }


def _thin_details():
    """The shape `score_mutant_walkforward` returns when a leg starves: no
    deltas at all, and a score that is the parent's mean plus the penalty."""
    return {
        "train_parent": _leg(30, 0.10), "train_mutant": _leg(2, 0.90),
        "test_parent": _leg(14, 0.08), "test_mutant": _leg(0, None),
        "train_delta": None, "test_delta": None, "worst_delta": None,
        "sufficient_data": False,
        "notes": "Insufficient data in one or both splits — mutant penalised.",
    }


def _starved_parent_details():
    """The shape the scorer returns when the PARENT's own legs come back
    empty: `score_mutant_walkforward` substitutes 0 for each missing leg, so
    the score lands on a flat penalty with no baseline under it at all."""
    return {
        "train_parent": _leg(0, None), "test_parent": _leg(0, None),
        "train_mutant": _leg(0, None), "test_mutant": _leg(0, None),
        "train_delta": None, "test_delta": None, "worst_delta": None,
        "sufficient_data": False,
        "notes": "Insufficient data in one or both splits — mutant penalised.",
    }


def _card(body, mutation_id):
    """The markup of exactly one mutation card, so an assertion about one
    card cannot be satisfied by a neighbouring card's markup."""
    anchor = body.index(f'id="mut-{mutation_id}"')
    return body[body.rindex("<article", 0, anchor):
                body.index("</article>", anchor)]


def _score_nums(card):
    """Just the `parent → score` line, so an assertion about the arrow cannot
    be satisfied by a number printed elsewhere on the same card."""
    start = card.index('class="ev-score-nums"')
    return card[start:card.index("</div>", start)]


def _ledger_cells(body, mutation_id):
    """The decision-ledger row for one mutation, as a list of cell bodies:
    [#id, parent, outcome, forked rule, proposed, decided, by]."""
    import re
    # The element is `class="card ev-ledger"` — anchor on the modifier, not
    # on a full attribute value that a second class breaks.
    table = body[body.index("ev-ledger"):]
    anchor = table.index(f">#{mutation_id}<")
    row = table[table.rindex("<tr>", 0, anchor):table.index("</tr>", anchor)]
    return re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)


class EvolutionPageBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("evo_page", password="x")
        self.client.force_login(self.user)

    def _control(self, rule_name="golden_cross", stage="live_full", **kw):
        from signals.models import RuleControl
        return RuleControl.objects.create(
            rule_name=rule_name, promotion_stage=stage, **kw)

    def _body(self):
        resp = self.client.get("/evolution/")
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode("utf-8", "replace")


class FourLegEvidenceTests(EvolutionPageBase):
    """The walk-forward breakdown was persisted from day one and shown as two
    deltas. Four legs were measured; four legs get drawn."""

    def test_a_measured_mutation_renders_all_four_legs(self):
        mut = _mutation(score_details=_measured_details(0.22, 0.11),
                        proposed_score=0.35)
        card = _card(self._body(), mut.id)
        self.assertEqual(card.count('class="ev-leg '), 4,
                         "train/test × parent/mutant is four legs, not two")
        for window in ("TRAIN", "TEST"):
            self.assertIn(window, card)
        for side in ("parent", "mutant"):
            self.assertIn(f"<em>{side}</em>", card)

    def test_each_leg_carries_its_own_sample_size(self):
        """An expectancy with no n behind it is a number pretending to be
        evidence, and these legs run on single digits."""
        mut = _mutation(score_details=_measured_details(0.22, 0.11))
        card = _card(self._body(), mut.id)
        for n in ("n=30", "n=28", "n=14", "n=12"):
            self.assertIn(n, card)

    def test_the_leg_expectancies_and_both_deltas_are_shown(self):
        mut = _mutation(score_details=_measured_details(0.22, 0.11))
        card = _card(self._body(), mut.id)
        for value in ("+0.10R", "+0.32R", "+0.08R", "+0.19R"):
            self.assertIn(value, card, "a measured leg must print its expectancy")
        self.assertIn("+0.22R", card)
        self.assertIn("+0.11R", card)

    def test_a_negative_leg_is_drawn_on_the_other_side_of_zero(self):
        """The bars diverge from a centre line, so a losing leg points the
        other way rather than merely being shorter than a winning one."""
        mut = _mutation(score_details=_measured_details(0.42, -0.38))
        card = _card(self._body(), mut.id)
        self.assertIn("ev-leg-fill--neg", card)
        self.assertIn("ev-leg-fill--pos", card)

    def test_a_row_without_leg_detail_says_so_instead_of_drawing_zeroes(self):
        """Older proposals stored only the deltas. Four empty bars would be a
        confident claim that all four legs measured nothing."""
        mut = _mutation(score_details={"train_delta": 0.11, "test_delta": 0.06,
                                       "notes": "ROBUST (both halves improve)"})
        card = _card(self._body(), mut.id)
        self.assertNotIn('class="ev-leg ', card)
        self.assertIn("not recorded", card)
        self.assertIn("ROBUST", card, "the deltas it does have must still show")


class ThinDataIsNotALossTests(EvolutionPageBase):
    """The single most misread number in this system."""

    def _both(self):
        thin = _mutation(score_details=_thin_details(), proposed_score=-0.91)
        lost = _mutation(score_details=_measured_details(-0.32, -0.18),
                         proposed_score=-0.23)
        body = self._body()
        return _card(body, thin.id), _card(body, lost.id)

    def test_the_two_cards_are_marked_differently_in_the_markup(self):
        thin, lost = self._both()
        self.assertIn('data-verdict="thin"', thin)
        self.assertIn('data-measured="0"', thin)
        self.assertIn("ev-mut--thin", thin)

        self.assertIn('data-verdict="worse"', lost)
        self.assertIn('data-measured="1"', lost)
        self.assertNotIn("ev-mut--thin", lost)
        self.assertIn("ev-mut--worse", lost)

    def test_the_unmeasured_card_says_not_measured_in_words(self):
        """Colour alone is not a distinction; the state has to be readable."""
        thin, lost = self._both()
        self.assertIn("NOT MEASURED", thin)
        self.assertNotIn("NOT MEASURED", lost)
        self.assertIn("WORSE THAN PARENT", lost)

    def test_the_unmeasured_card_prints_dashes_where_it_has_no_deltas(self):
        """A dash means not measured. Printing 0.00R there would invent a
        measurement that was never taken."""
        thin, _lost = self._both()
        self.assertIn("Δ train <b>—</b>", thin)
        self.assertIn("Δ test <b>—</b>", thin)
        self.assertNotIn("R</b>", thin.split("ev-deltas")[1].split("</div>")[0])

    def test_the_starved_legs_are_named_not_just_the_verdict(self):
        """'thin data' with no visible cause is a claim, not evidence: the
        legs that fell below the floor are marked where they are drawn."""
        thin, lost = self._both()
        self.assertIn("ev-leg--starved", thin)
        self.assertIn("n-badge--thin", thin)
        self.assertIn("n=2", thin)
        self.assertIn("n=0", thin)
        self.assertNotIn("ev-leg--starved", lost,
                         "every leg of the losing mutant cleared the floor")

    def test_the_score_is_labelled_a_placeholder_not_a_result(self):
        thin, lost = self._both()
        self.assertIn("placeholder", thin)
        self.assertNotIn("placeholder", lost)

    def test_the_page_states_the_real_floor_and_the_real_penalty(self):
        """Both constants are read from the scorer, so a change there cannot
        leave the page explaining a rule it no longer follows."""
        from signals.evolution_backtest import (INSUFFICIENT_DATA_PENALTY,
                                                MIN_TRADES_PER_SPLIT)
        _mutation(score_details=_thin_details(), proposed_score=-0.91)
        body = self._body()
        self.assertIn(f"<b>{MIN_TRADES_PER_SPLIT}</b>", body)
        self.assertIn(f"<b>{INSUFFICIENT_DATA_PENALTY:.2f}R</b>", body)

    def test_an_unbacktested_mutation_is_a_third_thing_again(self):
        """A heuristic score never touched a bar. It is not a loss and it is
        not a thin measurement — it is no measurement."""
        mut = _mutation(score_method="heuristic", score_details={},
                        proposed_score=0.28)
        card = _card(self._body(), mut.id)
        self.assertIn('data-verdict="unbacktested"', card)
        self.assertIn('data-measured="0"', card)
        self.assertIn("NO BACKTEST", card)


class WhyThereIsNoBacktestTests(EvolutionPageBase):
    """"No backtest" has three causes and they send the operator three
    different places. Naming the wrong one is worse than naming none."""

    def setUp(self):
        super().setUp()
        from signals.evolution import _ensure_rules_registered
        # golden_cross is the one family with a registered evaluator; the
        # branch is meaningless without it.
        _ensure_rules_registered()

    def test_a_fallback_score_blames_the_scorer_not_a_missing_registration(self):
        """`score_mutant` catches a scorer exception, logs it and falls back to
        the heuristic. Telling the operator no evaluator is registered sends
        them to the registry while the real cause sits in the worker log."""
        from signals.evolution_backtest import has_evaluator
        self.assertTrue(has_evaluator("golden_cross"))
        mut = _mutation(parent_rule="golden_cross", score_method="heuristic",
                        score_details={}, proposed_score=0.28)
        card = _card(self._body(), mut.id)
        self.assertIn("An evaluator IS registered", card)
        self.assertIn("worker log", card)
        self.assertNotIn("No evaluator is registered", card)

    def test_a_family_with_no_evaluator_is_still_told_so(self):
        from signals.evolution_backtest import has_evaluator
        self.assertFalse(has_evaluator("macd_crossover"))
        mut = _mutation(parent_rule="macd_crossover", score_method="heuristic",
                        score_details={}, proposed_score=0.28)
        card = _card(self._body(), mut.id)
        self.assertIn("No evaluator is registered", card)
        self.assertNotIn("worker log", card)

    def test_a_fork_inherits_its_parents_evaluator(self):
        """`golden_cross_evolved_v2` is the same detector as its parent, so
        the registry lookup has to strip the fork suffix — otherwise every
        fork is reported as an unregistered family."""
        mut = _mutation(parent_rule="golden_cross_evolved_v2",
                        score_method="heuristic", score_details={})
        card = _card(self._body(), mut.id)
        self.assertIn("An evaluator IS registered", card)

    def test_a_non_heuristic_method_is_not_described_as_random_drift(self):
        """score_method is heuristic | walk_forward | manual_backtest. The
        branch is `!= walk_forward`, so a manual backtest fell into it and was
        announced as 'NO BACKTEST … random drift'."""
        mut = _mutation(score_method="manual_backtest", score_details={},
                        proposed_score=0.41)
        card = _card(self._body(), mut.id)
        self.assertIn("UNVERIFIED", card)
        self.assertIn("manual_backtest", card)
        self.assertNotIn("random drift", card)
        self.assertNotIn("NO BACKTEST", card)

    def test_a_parent_with_no_closed_trades_is_not_credited_with_a_mean(self):
        """`score_mutant_heuristic` returns a flat 0.0 when the parent has no
        closed signals — there is no expectancy for the drift to sit on."""
        mut = _mutation(parent_rule="macd_crossover", score_method="heuristic",
                        parent_expectancy=None, score_details={},
                        proposed_score=0.0)
        card = _card(self._body(), mut.id)
        self.assertIn("no closed trades", card)
        self.assertNotIn("random drift", card)


class ParameterMoveTests(EvolutionPageBase):
    """A bare `fast: 30` says nothing. Against the schema's [10, 90] it reads
    at a glance as near the floor, which is the judgement being asked for."""

    def test_a_move_is_drawn_against_its_declared_bounds(self):
        from signals.evolution import _ensure_rules_registered
        _ensure_rules_registered()
        mut = _mutation(score_details=_measured_details(0.22, 0.11))
        card = _card(self._body(), mut.id)
        self.assertIn("--ev-from:", card)
        self.assertIn("--ev-to:", card)
        # golden_cross declares fast in [10, 90]; 50 → 30 is mid → quarter.
        self.assertIn("--ev-from:50.00%", card)
        self.assertIn("--ev-to:25.00%", card)
        self.assertIn(">10<", card)
        self.assertIn(">90<", card)

    def test_the_move_names_the_parameter_and_the_signed_delta(self):
        mut = _mutation(score_details=_measured_details(0.22, 0.11))
        card = _card(self._body(), mut.id)
        self.assertIn("fast", card)
        self.assertIn("-20", card)

    def test_a_parameter_with_no_bounds_degrades_to_a_dash(self):
        """An unregistered parameter has no range to sit in. Drawing it at
        0% would be a position nobody measured."""
        mut = _mutation(parent_rule="macd_crossover",
                        parent_params={"threshold": 4},
                        mutated_params={"threshold": 7},
                        parameters_changed=["threshold"],
                        score_details=_measured_details(0.1, 0.1))
        card = _card(self._body(), mut.id)
        self.assertIn("no declared range", card)
        self.assertNotIn("--ev-from:", card)


class RegistryPanelTests(EvolutionPageBase):
    """"Why is only one family evolvable?" is a question this page should
    answer without being asked."""

    def test_the_panel_states_the_true_number_of_registered_schemas(self):
        from signals.evolution import SCHEMA_REGISTRY, _ensure_rules_registered
        _ensure_rules_registered()
        expected = len(SCHEMA_REGISTRY)
        self.assertGreaterEqual(expected, 1, "the evolution layer is dormant")
        body = self._body()
        self.assertIn(f'data-registered-schemas="{expected}"', body)
        self.assertIn(f"{expected} of ", body)

    def test_golden_cross_is_listed_with_its_bounds(self):
        from signals.evolution import _ensure_rules_registered
        _ensure_rules_registered()
        body = self._body()
        self.assertIn("golden_cross", body)
        self.assertIn("10 … 90", body)
        self.assertIn("120 … 300", body)

    def test_the_dormant_families_are_listed_with_the_honest_reason(self):
        """Listing only the registry would imply the rest do not exist. The
        rest exist and are deliberately left alone."""
        body = self._body()
        self.assertIn("ev-reg--off", body)
        self.assertIn("no parameter schema", body)
        self.assertIn("has_schema gate", body)

    def test_the_registry_never_claims_a_fork_is_its_own_family(self):
        """A fork reuses its parent's schema, so listing `..._evolved_v1` as
        a separate un-evolvable family would inflate the dormant count and
        make the honest ratio a lie."""
        self._control("golden_cross")
        self._control("golden_cross_evolved_v1", stage="research",
                      parameters={"fast": 30})
        body = self._body()
        self.assertNotIn('class="ev-reg-name">golden_cross_evolved_v1<', body)

    def test_the_family_is_resolved_by_the_one_shared_parser(self):
        """This page used to carry its own `_base_family` regex, a third copy
        of the one `promotion_evidence` gates promotions with — and this page
        asserted in its docstring that the two agreed. Now they are the same
        function, so agreeing is not something anyone has to remember.

        The stake: this panel and the evidence gate must name the same parent
        for a fork, or a rule is backtested against one evaluator and drawn on
        screen under another. Full coverage in tests/test_fork_names.py.
        """
        from core import fork_names
        from dashboard import views_evolution
        self.assertIs(views_evolution.base_family, fork_names.base_family)
        self.assertEqual(
            views_evolution.base_family("golden_cross_evolved_v1"),
            "golden_cross")


class EmptyStateTests(EvolutionPageBase):
    """A young install has no mutations. That is a reading, not a fault, and
    the page has to say which of the three gates it is sitting behind."""

    def test_the_empty_state_explains_rather_than_reporting_zero(self):
        body = self._body()
        self.assertIn("No mutations have been proposed yet", body)
        self.assertIn("not a fault", body)
        self.assertIn("registered schema", body)
        self.assertIn("decaying", body)

    def test_the_empty_state_names_the_cadence_that_would_produce_one(self):
        body = self._body()
        self.assertIn("Sundays", body)
        self.assertIn("05:00 UTC", body)
        self.assertIn("02:30 UTC", body)

    def test_the_registry_still_renders_with_no_mutations(self):
        """The empty case is exactly when 'which rules can even evolve?' is
        the question being asked."""
        body = self._body()
        self.assertIn("Parameter registry", body)
        self.assertIn("data-registered-schemas=", body)


class UnknownIsADashTests(EvolutionPageBase):
    def test_a_fork_with_no_closed_signals_reads_as_a_dash(self):
        """A fork that has not closed a trade has no expectancy. Rendering
        0.00R would report a flat result it never produced."""
        self._control("golden_cross")
        mut = _mutation(state="applied", forked_rule="golden_cross_evolved_v1",
                        applied_at=timezone.now())
        self._control("golden_cross_evolved_v1", stage="research")
        body = self._body()
        self.assertIn("golden_cross_evolved_v1", body)
        self.assertIn("n=0", body)
        self.assertNotIn("0.00R", _card(body, mut.id))


class ExpiryTests(EvolutionPageBase):
    """An undecided proposal is on a clock: past the TTL it expires and the
    next sweep asks again with freshly scored candidates. A card that does
    not show the clock is asking for a decision with no deadline attached."""

    def test_an_open_proposal_shows_its_time_to_expiry(self):
        from signals.evolution import PROPOSAL_TTL_DAYS
        # The extra hour keeps the remainder off the day boundary: the view
        # floors days_left, so an exact 4-day gap renders as 3 by the time
        # the request is served.
        mut = _mutation(
            score_details=_measured_details(0.22, 0.11),
            proposed_at=(timezone.now()
                         - timedelta(days=PROPOSAL_TTL_DAYS - 4)
                         + timedelta(hours=1)))
        card = _card(self._body(), mut.id)
        self.assertIn("4d left", card)
        self.assertIn("expires", card)
        self.assertIn("ev-expiry", card)

    def test_a_proposal_close_to_expiry_is_marked_urgent(self):
        from signals.evolution import PROPOSAL_TTL_DAYS
        mut = _mutation(
            score_details=_measured_details(0.22, 0.11),
            proposed_at=timezone.now() - timedelta(days=PROPOSAL_TTL_DAYS - 2))
        self.assertIn("is-urgent", _card(self._body(), mut.id))

    def test_the_strip_reports_the_soonest_expiry(self):
        from signals.evolution import PROPOSAL_TTL_DAYS
        _mutation(score_details=_measured_details(0.22, 0.11),
                  proposed_at=timezone.now() - timedelta(days=2))
        _mutation(score_details=_measured_details(0.22, 0.11),
                  proposed_at=timezone.now() - timedelta(days=PROPOSAL_TTL_DAYS - 1))
        body = self._body()
        self.assertIn("NEXT EXPIRY", body)
        self.assertIn(f"{PROPOSAL_TTL_DAYS}d TTL", body)

    def test_a_decided_mutation_shows_no_countdown(self):
        """A clock on a settled question is invented urgency."""
        mut = _mutation(state="applied", forked_rule="golden_cross_evolved_v1",
                        applied_at=timezone.now(),
                        score_details=_measured_details(0.22, 0.11))
        card = _card(self._body(), mut.id)
        self.assertNotIn("ev-expiry", card)
        self.assertIn("forked into", card)

    def test_an_expired_proposal_says_what_happens_next(self):
        from signals.evolution import PROPOSAL_TTL_DAYS
        mut = _mutation(state="expired",
                        score_details=_measured_details(0.22, 0.11))
        card = _card(self._body(), mut.id)
        self.assertIn(f"expired after {PROPOSAL_TTL_DAYS}d", card)
        self.assertIn("asks again", card)


class LineageTests(EvolutionPageBase):
    """Parent → its mutations → which of them forked, on one surface."""

    def test_a_family_groups_its_mutations_under_the_parent(self):
        self._control("golden_cross")
        a = _mutation(score_details=_measured_details(0.22, 0.11))
        b = _mutation(score_details=_thin_details(), proposed_score=-0.91)
        body = self._body()
        self.assertEqual(body.count('<h2 class="ev-fam-name">'), 1,
                         "both mutations descend from one parent")
        self.assertIn("ev-spine", body)
        for mut in (a, b):
            self.assertIn(f'id="mut-{mut.id}"', body)

    def test_an_applied_mutation_shows_the_fork_beside_its_parent(self):
        self._control("golden_cross", stage="live_full")
        self._control("golden_cross_evolved_v1", stage="research",
                      parameters={"fast": 30})
        _mutation(state="applied", forked_rule="golden_cross_evolved_v1",
                  applied_at=timezone.now(),
                  score_details=_measured_details(0.22, 0.11))
        body = self._body()
        self.assertIn("forks trading beside it", body)
        self.assertIn("ev-forkchip--stage-research", body)
        self.assertIn("LIVE_FULL", body,
                      "the parent keeps running — a fork never overwrites it")

    def test_a_familys_open_question_sorts_to_the_top(self):
        _mutation(parent_rule="quiet_rule", state="rejected",
                  score_details=_measured_details(0.1, 0.1))
        _mutation(parent_rule="golden_cross",
                  score_details=_measured_details(0.22, 0.11))
        body = self._body()
        self.assertLess(body.index("golden_cross"), body.index("quiet_rule"),
                        "the family awaiting a decision comes first")

    def test_the_live_record_beside_a_rule_is_a_real_measurement(self):
        """Signal.Meta.ordering rides into a GROUP BY and splits each rule
        into one row per timestamp — every rule then reports n=1."""
        from instruments.models import Instrument
        from signals.models import Signal
        inst, _ = Instrument.objects.get_or_create(
            symbol="EVOPG", defaults={"name": "EVOPG", "asset_class": "crypto"})
        now = timezone.now()
        for i in range(4):
            Signal.objects.create(
                instrument=inst, signal_type="technical", direction="bullish",
                urgency="high", title="t", description="d",
                rule_name="golden_cross", score=0.7, sub_scores={},
                price_at_signal=Decimal("100"), is_active=False,
                outcome="hit_target", realized_r=1.0,
                expired_at=now - timedelta(days=i + 1))
        self._control("golden_cross")
        _mutation(score_details=_measured_details(0.22, 0.11))
        self.assertIn("n=4", self._body())


class DecisionSurfaceTests(EvolutionPageBase):
    def test_a_viewer_sees_the_evidence_but_no_decide_buttons(self):
        _mutation(score_details=_measured_details(0.22, 0.11))
        body = self._body()
        self.assertIn("ROBUST", body)
        self.assertNotIn(">Fork<", body)
        self.assertNotIn(">Reject<", body)

    def test_an_admin_can_decide_from_the_card(self):
        admin = User.objects.create_superuser("evo_admin", "a@b.co", "x")
        self.client.force_login(admin)
        mut = _mutation(score_details=_measured_details(0.22, 0.11))
        card = _card(self._body(), mut.id)
        self.assertIn(">Fork<", card)
        self.assertIn(">Reject<", card)
        self.assertIn(f'value="{mut.id}"', card)


class ScoreArrowTests(EvolutionPageBase):
    """`parent X → Y` is a claim that Y replaced X on the same measurement.
    Only one baseline on this page satisfies that."""

    def test_the_arrow_starts_at_the_backtest_baseline_not_the_live_record(self):
        """A walk-forward score is mean(train_parent, test_parent) + worst Δ.
        parent_expectancy is an average of live closed Signals over a
        different window, universe, data source and fill convention — pairing
        them drew a 0.31R regression that no measurement produced."""
        mut = _mutation(parent_expectancy=0.40, proposed_score=0.14,
                        score_details=_measured_details(0.06, 0.05))
        nums = _score_nums(_card(self._body(), mut.id))
        self.assertIn("backtest parent", nums)
        # (0.10 + 0.08) / 2 — the two parent legs the score was built on.
        self.assertIn("0.09R", nums)
        self.assertNotIn("0.40R", nums,
                         "the live record is not the arrow's origin")

    def test_the_live_record_is_still_shown_and_labelled_as_its_own_thing(self):
        mut = _mutation(parent_expectancy=0.40,
                        score_details=_measured_details(0.06, 0.05))
        card = _card(self._body(), mut.id)
        aside = card[card.index('class="ev-score-aside"'):]
        self.assertIn("0.40R", aside)
        self.assertIn("live", aside)

    def test_a_heuristic_score_keeps_the_live_record_as_its_baseline(self):
        """The heuristic really is parent_expectancy + drift, so on that card
        the live number IS the origin and must not be duplicated beside it."""
        mut = _mutation(parent_rule="macd_crossover", score_method="heuristic",
                        parent_expectancy=0.40, proposed_score=0.52,
                        score_details={})
        card = _card(self._body(), mut.id)
        self.assertIn("live parent", _score_nums(card))
        self.assertIn("0.40R", _score_nums(card))
        self.assertNotIn("ev-score-aside", card)

    def test_an_unmeasured_parent_leg_reads_as_a_dash_not_a_zero(self):
        """The scorer substitutes 0 for a missing parent leg, which is how a
        card lands on a flat -1.00R. Printing that 0 as the parent's result
        would invent the measurement the penalty exists to flag."""
        mut = _mutation(score_details=_starved_parent_details(),
                        proposed_score=-1.0)
        card = _card(self._body(), mut.id)
        self.assertIn("&mdash;", _score_nums(card))
        self.assertNotIn("0.00R", card)
        self.assertIn("no baseline under it", card)


class ScoreToneTests(EvolutionPageBase):
    """The view computes an up/down tone for the score. The page has to
    actually wear it — and only where it means something."""

    def test_the_tone_rule_is_compound_so_the_utility_class_survives(self):
        """sauron.css's bare `.up`/`.down` carry the same specificity as this
        page's `.ev-score-val`, which is declared later and therefore wins:
        the tone was computed, emitted, and silently discarded."""
        from pathlib import Path
        from django.conf import settings
        css = Path(settings.BASE_DIR).joinpath(
            "templates", "dashboard", "evolution.html").read_text(
            encoding="utf-8")
        self.assertIn(".ev-score-val.up", css)
        self.assertIn(".ev-score-val.down", css)

    def test_a_mutant_that_beat_its_baseline_renders_up(self):
        mut = _mutation(score_details=_measured_details(0.22, 0.11),
                        proposed_score=0.20)
        self.assertIn('class="ev-score-val up"', _card(self._body(), mut.id))

    def test_a_mutant_that_lost_renders_down(self):
        mut = _mutation(score_details=_measured_details(-0.32, -0.18),
                        proposed_score=-0.23)
        self.assertIn('class="ev-score-val down"', _card(self._body(), mut.id))

    def test_a_placeholder_score_is_neither_up_nor_down(self):
        """An untested score is not a direction. Toning it would file it
        exactly where this page exists to stop it being filed."""
        thin = _mutation(score_details=_thin_details(), proposed_score=-0.91)
        card = _card(self._body(), thin.id)
        self.assertNotIn('class="ev-score-val up"', card)
        self.assertNotIn('class="ev-score-val down"', card)


class DecisionLedgerTests(EvolutionPageBase):
    """The ledger answers "what did we do, and when". Only one of those two
    is recorded for a rejection or an expiry."""

    def test_a_rejection_does_not_borrow_the_proposal_time_as_its_decision(self):
        """`applied_at` is written only by apply_evolution(). Coalescing to
        proposed_at dated the decision to the day the question was ASKED,
        under a column header that says otherwise."""
        mut = _mutation(state="rejected",
                        proposed_at=timezone.now() - timedelta(days=9),
                        score_details=_measured_details(0.1, 0.1))
        cells = _ledger_cells(self._body(), mut.id)
        self.assertEqual(len(cells), 7)
        self.assertIn("&mdash;", cells[5], "no decision time was ever stamped")
        self.assertNotIn("&mdash;", cells[4], "the proposal time is real")

    def test_an_expiry_does_not_report_itself_a_fortnight_early(self):
        """expire_stale_mutations() only touches rows older than the TTL, so
        the fabricated time was understated by at least PROPOSAL_TTL_DAYS —
        every time, not occasionally."""
        from signals.evolution import PROPOSAL_TTL_DAYS
        mut = _mutation(state="expired",
                        proposed_at=(timezone.now()
                                     - timedelta(days=PROPOSAL_TTL_DAYS + 6)),
                        score_details=_measured_details(0.1, 0.1))
        cells = _ledger_cells(self._body(), mut.id)
        self.assertIn("&mdash;", cells[5])

    def test_a_fork_reports_the_real_decision_time(self):
        decided = timezone.now() - timedelta(days=1)
        mut = _mutation(state="applied", forked_rule="golden_cross_evolved_v1",
                        applied_at=decided,
                        proposed_at=timezone.now() - timedelta(days=6),
                        score_details=_measured_details(0.1, 0.1))
        cells = _ledger_cells(self._body(), mut.id)
        self.assertNotIn("&mdash;", cells[5])
        self.assertIn(decided.strftime("%b %d"), cells[5])

    def test_the_ledger_says_which_of_the_resolved_rows_it_is_showing(self):
        """`{{ ledger|length }} resolved` reported the slice as the total."""
        from unittest.mock import patch
        for i in range(3):
            _mutation(state="rejected",
                      proposed_at=timezone.now() - timedelta(days=i + 1),
                      score_details=_measured_details(0.1, 0.1))
        with patch("dashboard.views_evolution.LEDGER_ROWS", 2):
            body = self._body()
        self.assertIn("newest 2 of 3 resolved", body)


class FetchWindowHonestyTests(EvolutionPageBase):
    """The per-family counts were the size of an 80-row fetch, printed as
    though the page had counted the table."""

    def _resolved(self, n, parent="golden_cross", day0=1):
        return [_mutation(parent_rule=parent, state="rejected",
                          proposed_at=timezone.now() - timedelta(days=day0 + i),
                          score_details=_measured_details(0.1, 0.1))
                for i in range(n)]

    def test_a_familys_mutation_count_is_the_table_not_the_window(self):
        from unittest.mock import patch
        self._resolved(5)
        with patch("dashboard.views_evolution.MAX_MUTATIONS_TOTAL", 2):
            body = self._body()
        self.assertIn("<em>mutations</em> 5", body)

    def test_the_older_not_shown_count_is_what_is_actually_missing(self):
        from unittest.mock import patch
        self._resolved(5)
        with patch("dashboard.views_evolution.MAX_MUTATIONS_TOTAL", 2):
            body = self._body()
        self.assertIn("3 older mutations not shown", body)

    def test_a_fork_older_than_the_window_still_shows_beside_its_parent(self):
        """The fork line was built from the same windowed list, so an old
        applied mutation dropped its fork off the page while the forked rule
        was still trading — and while the strip's FORKS count still had it."""
        from unittest.mock import patch
        self._control("golden_cross")
        self._control("golden_cross_evolved_v1", stage="research")
        _mutation(state="applied", forked_rule="golden_cross_evolved_v1",
                  applied_at=timezone.now() - timedelta(days=40),
                  proposed_at=timezone.now() - timedelta(days=44),
                  score_details=_measured_details(0.1, 0.1))
        self._resolved(3)
        with patch("dashboard.views_evolution.MAX_MUTATIONS_TOTAL", 2):
            body = self._body()
        self.assertIn("forks trading beside it", body)
        self.assertIn("golden_cross_evolved_v1", body)

    def test_a_family_that_fell_out_of_the_window_is_declared_not_dropped(self):
        """A family with no row inside the window vanished from the lineage
        entirely, leaving the page reading as a complete history."""
        from unittest.mock import patch
        self._resolved(1, parent="quiet_rule", day0=40)
        self._resolved(2, parent="golden_cross")
        with patch("dashboard.views_evolution.MAX_MUTATIONS_TOTAL", 2):
            body = self._body()
        self.assertIn("further famil", body)
        self.assertIn("not shown above", body)


class PagePresentationTests(EvolutionPageBase):
    """House rules the page has to keep whatever it renders."""

    def _template(self):
        from pathlib import Path
        from django.conf import settings
        return Path(settings.BASE_DIR).joinpath(
            "templates", "dashboard", "evolution.html").read_text(
            encoding="utf-8")

    def test_motion_is_switched_off_where_it_is_unwelcome(self):
        self.assertIn("prefers-reduced-motion", self._template())

    def test_no_floating_element_carries_a_raw_z_index(self):
        """The sv-overlay ladder owns stacking order; a raw number on this
        page would sit under or over the rail unpredictably."""
        import re
        self.assertEqual(re.findall(r"z-index\s*:", self._template()), [])

    def test_the_page_local_styles_are_on_tokens_not_raw_colour(self):
        """Both themes follow the tokens. A literal colour renders the same in
        light mode, where it is illegible — and the hex-only form of this
        check let a copied dark-mode `rgba(0,0,0,.45)` hover shadow through,
        which painted a black halo on a white card."""
        import re
        self.assertEqual(
            re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", self._template()),
            [])

    def test_every_shadow_is_a_token_so_light_mode_gets_one_too(self):
        """.ev-mut hand-rolls the card grammar instead of carrying `card`, so
        none of sauron.css's `body.light-mode .card:hover` overrides reach it.
        A literal shadow here is a dark-mode-only shadow, permanently."""
        import re
        shadows = re.findall(r"box-shadow:[^;]+;", self._template())
        self.assertTrue(shadows, "the page draws shadows; this guard needs them")
        for decl in shadows:
            self.assertIn("var(", decl,
                          f"raw shadow with no light-mode counterpart: {decl}")

    def test_no_comment_markup_reaches_the_browser(self):
        """Django's {# #} is single-line; a multi-line one is not a comment
        and renders verbatim onto the page."""
        _mutation(score_details=_measured_details(0.22, 0.11))
        body = self._body()
        self.assertNotIn("{#", body)
        self.assertNotIn("{% comment", body)

    def test_wide_content_scrolls_inside_itself(self):
        _mutation(state="applied", forked_rule="golden_cross_evolved_v1",
                  applied_at=timezone.now(),
                  score_details=_measured_details(0.22, 0.11))
        self.assertIn("table-wrapper", self._body())
