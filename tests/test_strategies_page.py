"""The Strategies page answers "what is running, at what stage, how is it doing".

The failure these guard: the operator asked "why still 0 strategies?" while
twelve rules were running. `/strategies/` led with `strategies.Strategy` — a
multi-leg trade plan the wizard writes and nothing executes — while the public
landing page counted `signals.RuleControl` (core/wall_facts._count_strategies).
The platform gave two different answers to one question, one on each side of
the login boundary, and the four pages that explain a rule's life were in no
menu at all.

Covered here:
  - the seeded rules appear, grouped by promotion stage
  - the card's numbers are the ones the ladder judges on (_stats_since)
  - the gate shows the GAP ("18 of 30 closed trades"), not a verdict
  - a setup's GATE condition renders as a precondition, not as a weighted leg,
    and the card states the denominator the scanner really divides by
  - a stage is described as a VENUE, not a size
  - an empty install says how to seed instead of showing an empty table
  - hand-built plans stay visible, labelled as plans nothing executes
  - the four ladder pages resolve and are linked from nav and cards
  - the query budget is fixed as the rule count grows (no N+1 on rule_name)

Run with:  python manage.py test tests.test_strategies_page
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone


def _instrument(symbol="SPTEST"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": "stock"})
    return inst


def _rule(name, stage="research", *, status="active", entered_days_ago=0,
          baseline=None, paused_until=None):
    from signals.models_control import RuleControl
    ctrl = RuleControl.objects.create(
        rule_name=name, status=status, promotion_stage=stage,
        stage_entered_at=timezone.now() - timedelta(days=entered_days_ago),
        stage_baseline_expectancy=baseline, paused_until=paused_until)
    return ctrl


def _setup(name, *, active=True, conditions=None, min_match_score=None):
    """An OpportunitySetup with NO companion RuleControl row.

    Nothing creates one automatically — not a post_save, not the admin form,
    not the pattern miner's activate path — so this is the shape a hand-armed
    setup actually has on disk.
    """
    from signals.models_opportunity import OpportunitySetup
    kwargs = {}
    if min_match_score is not None:
        kwargs["min_match_score"] = min_match_score
    return OpportunitySetup.objects.create(
        name=name, direction="bullish", asset_classes=["stock"],
        is_active=active,
        conditions=(conditions if conditions is not None else
                    [{"kind": "price_pattern", "params": {"ma_period": 50}}]),
        **kwargs)


def _closed_signals(rule_name, rs, *, days_ago=1):
    """Closed, graded signals — the only rows `_stats_since` counts."""
    from signals.models import Signal
    inst = _instrument("SP_" + rule_name[:20])
    for r in rs:
        Signal.objects.create(
            instrument=inst, signal_type="technical", direction="bullish",
            urgency="medium", title="t", description="t", rule_name=rule_name,
            score=0.7, sub_scores={},
            price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
            suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
            risk_reward_ratio=2.0, is_active=False,
            outcome="hit_target" if r > 0 else "stopped_out",
            realized_r=r,
            expired_at=timezone.now() - timedelta(days=days_ago))


class StrategiesLadderPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("ladder_u", password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def _get(self):
        return self.client.get(reverse("strategies_list"), HTTP_HOST="127.0.0.1")

    # ── The real estate leads ──────────────────────────────────────────

    def test_seeded_rules_appear_grouped_by_stage(self):
        """The seeder's rules ARE the strategies. They used to be a footnote
        under an empty trade-plan table."""
        from signals.management.commands.seed_strategies import seed_setups
        seed_setups(activate=False)
        from signals.models_control import RuleControl
        n_seeded = RuleControl.objects.count()
        self.assertGreater(n_seeded, 0, "the seeder registered no rule")

        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8", "replace")

        self.assertIn("Automated setups", body)
        for name in RuleControl.objects.values_list("rule_name", flat=True):
            self.assertIn(name, body, f"{name} is running but is not on the page")
        # One section per stage, in the ladder's own order.
        for stage in ("research", "paper", "live_small", "live_full"):
            self.assertIn(f'id="stage-{stage}"', body)
        self.assertIn('data-stage="research"', body)

    def test_a_rule_sits_in_the_section_for_its_own_stage(self):
        _rule("in_research", "research")
        _rule("in_paper", "paper")
        _rule("at_full_size", "live_full")
        body = self._get().content.decode("utf-8", "replace")

        def section(stage):
            start = body.index(f'id="stage-{stage}"')
            nxt = body.find('<section class="sc-stage"', start + 1)
            return body[start:nxt if nxt != -1 else len(body)]

        self.assertIn("in_research", section("research"))
        self.assertNotIn("in_paper", section("research"))
        self.assertIn("in_paper", section("paper"))
        self.assertIn("at_full_size", section("live_full"))

    def test_the_page_counts_strategies_the_way_the_landing_page_does(self):
        """The contradiction across the login boundary is the whole bug."""
        from core.wall_facts import _count_strategies
        _rule("agreement_a")
        _rule("agreement_b")
        from dashboard.views import _promotion_ladder
        self.assertEqual(_promotion_ladder()["n_rules"], _count_strategies())

    # ── The numbers are the ladder's numbers ───────────────────────────

    def test_the_card_shows_what_the_ladder_computes(self):
        """A card whose numbers differ from the ones the pipeline judges on is
        worse than a card with no numbers."""
        from dashboard.views import _promotion_ladder
        from signals.promotion_pipeline import _stats_since
        _rule("measured_rule", "research")
        _closed_signals("measured_rule", [1.0, 2.0, -1.0, -1.0, 0.5])

        card = _promotion_ladder()["stage_groups"][0]["cards"][0]
        truth = _stats_since("measured_rule")
        self.assertEqual(card["record"]["n"], truth["n"])
        self.assertEqual(card["record"]["hit_rate"], truth["hit_rate"])
        self.assertAlmostEqual(card["record"]["expectancy"], truth["expectancy"],
                               places=6)

    def test_an_open_signal_is_not_counted_as_a_result(self):
        """`_stats_since` counts closed, graded signals only."""
        from dashboard.views import _promotion_ladder
        from signals.models import Signal
        _rule("half_open", "research")
        _closed_signals("half_open", [1.0, 1.0])
        Signal.objects.create(
            instrument=_instrument("SP_open"), signal_type="technical",
            direction="bullish", urgency="medium", title="t", description="t",
            rule_name="half_open", score=0.7, sub_scores={},
            price_at_signal=Decimal("100"), risk_reward_ratio=2.0,
            is_active=True)
        card = _promotion_ladder()["stage_groups"][0]["cards"][0]
        self.assertEqual(card["record"]["n"], 2)
        self.assertEqual(card["n_live_signals"], 1)

    def test_an_unmeasured_rate_renders_as_a_dash_never_as_zero(self):
        """A dash means "not measured". A 0% hit rate is a claim about
        evidence that does not exist."""
        from dashboard.views import _promotion_ladder
        _rule("never_traded", "research")
        card = _promotion_ladder()["stage_groups"][0]["cards"][0]
        self.assertEqual(card["record"]["n"], 0)
        self.assertIsNone(card["record"]["hit_rate"])
        self.assertIsNone(card["hit_rate_display"])
        self.assertIsNone(card["expectancy_display"])

        body = self._get().content.decode("utf-8", "replace")
        self.assertIn("sv-unknown", body)

    # ── The gate shows the gap ─────────────────────────────────────────

    def test_the_gate_states_the_distance_to_the_next_venue(self):
        """"18 of 30 closed trades" — a number the operator can act on, not
        a red cross."""
        from dashboard.views import _promotion_ladder
        from signals.promotion_pipeline import PROMO_RESEARCH_TO_PAPER_MIN_N
        _rule("nearly_there", "research")
        _closed_signals("nearly_there", [1.0] * 18)

        card = _promotion_ladder()["stage_groups"][0]["cards"][0]
        self.assertEqual(card["gate"]["target"], "paper")
        self.assertIn(f"18 of {PROMO_RESEARCH_TO_PAPER_MIN_N} closed trades",
                      card["gate"]["summary"])
        # 18/30 is the binding constraint, so that is what the bar fills to.
        self.assertEqual(card["gate"]["progress"], 60)

        body = self._get().content.decode("utf-8", "replace")
        self.assertIn("--sc-fill: 60%", body)

    def test_a_losing_rule_is_not_most_of_the_way_to_live_money(self):
        """"expectancy >= 0R" does not part-fill: a rule handing money back is
        at zero progress, whatever its sample size."""
        from dashboard.views import _promotion_ladder
        _rule("bleeding", "research")
        _closed_signals("bleeding", [-1.0] * 40)
        card = _promotion_ladder()["stage_groups"][0]["cards"][0]
        self.assertEqual(card["gate"]["progress"], 0)

    def test_a_rule_at_the_top_of_the_ladder_has_no_next_gate(self):
        from dashboard.views import _promotion_ladder
        _rule("topped_out", "live_full")
        cards = {c["rule"]: c for g in _promotion_ladder()["stage_groups"]
                 for c in g["cards"]}
        gate = cards["topped_out"]["gate"]
        self.assertIsNone(gate["target"])
        self.assertIsNone(gate["progress"])
        self.assertIn("top of the ladder", gate["summary"])

    def test_meeting_the_criteria_for_a_live_stage_is_not_called_ready(self):
        """promotion_evidence gates every LIVE stage on out-of-sample
        evidence, so the page must not promise a promotion the pipeline has
        not agreed to."""
        from dashboard.views import _promotion_ladder
        _rule("paper_veteran", "paper", entered_days_ago=60)
        _closed_signals("paper_veteran", [1.0] * 25)
        cards = {c["rule"]: c for g in _promotion_ladder()["stage_groups"]
                 for c in g["cards"]}
        summary = cards["paper_veteran"]["gate"]["summary"]
        self.assertEqual(cards["paper_veteran"]["gate"]["progress"], 100)
        self.assertIn("walk-forward", summary)

    # ── A stage is a venue ─────────────────────────────────────────────

    def test_the_page_says_a_stage_is_a_venue_not_a_size(self):
        """Reading the stage as a size is what once let a PAPER rule size to
        zero, take no paper trade, and never earn its way out of paper."""
        _rule("venue_demo", "research")
        body = self._get().content.decode("utf-8", "replace")
        self.assertIn("venue", body)
        self.assertIn("signals only", body)
        self.assertIn("no order is ever placed", body)
        self.assertIn("paper venue", body)

    # ── Forks ──────────────────────────────────────────────────────────

    def test_a_fork_borrows_the_definition_it_was_forked_from(self):
        """Evolution forks the RuleControl only — `{parent}_evolved_v{N}` — so
        a fork with no OpportunitySetup of its own has to walk up the name."""
        from dashboard.views import _promotion_ladder
        from signals.models_opportunity import OpportunitySetup
        OpportunitySetup.objects.create(
            name="golden_cross", direction="bullish", asset_classes=["stock"],
            conditions=[{"kind": "price_pattern", "params": {"ma_period": 50}}])
        _rule("golden_cross", "live_full")
        _rule("golden_cross_evolved_v2", "research")

        cards = {c["rule"]: c for g in _promotion_ladder()["stage_groups"]
                 for c in g["cards"]}
        fork = cards["golden_cross_evolved_v2"]
        self.assertEqual(fork["parent"], "golden_cross")
        self.assertIsNotNone(fork["setup"])
        self.assertTrue(fork["setup"]["inherited"])
        self.assertEqual(fork["setup"]["name"], "golden_cross")
        self.assertFalse(cards["golden_cross"]["setup"]["inherited"])

    def test_an_open_mutation_is_shown_on_the_parent_card(self):
        from dashboard.views import _promotion_ladder
        from signals.models_control import RuleMutation
        _rule("mutable", "live_small")
        RuleMutation.objects.create(
            parent_rule="mutable", parent_params={"fast": 20},
            mutated_params={"fast": 30}, parameters_changed=["fast"],
            proposed_score=0.42, score_method="walk_forward")
        cards = {c["rule"]: c for g in _promotion_ladder()["stage_groups"]
                 for c in g["cards"]}
        self.assertEqual(len(cards["mutable"]["forks_open"]), 1)
        self.assertIn("fast", cards["mutable"]["forks_open"][0]["changed"])

    # ── The honest empty state ─────────────────────────────────────────

    def test_an_empty_install_says_how_to_seed_instead_of_showing_nothing(self):
        from signals.models_control import RuleControl
        self.assertEqual(RuleControl.objects.count(), 0)
        body = self._get().content.decode("utf-8", "replace")
        self.assertIn("seed_strategies", body)
        self.assertIn("research", body)
        self.assertIn(reverse("promotions_dashboard"), body)
        # And it must not be the trade-plan table doing the talking.
        self.assertIn("NO RULE IS REGISTERED", body)

    def test_a_populated_install_never_shows_the_empty_state(self):
        _rule("something_runs", "paper")
        body = self._get().content.decode("utf-8", "replace")
        self.assertNotIn("NO RULE IS REGISTERED", body)

    # ── Hand-built plans keep their own, labelled, section ──────────────

    def test_hand_built_plans_stay_visible_and_are_labelled_as_plans(self):
        from strategies.models import Strategy
        Strategy.objects.create(name="My iron condor", description="d",
                                time_horizon="swing", status="proposed")
        body = self._get().content.decode("utf-8", "replace")
        self.assertIn("Hand-built trade plans", body)
        self.assertIn("My iron condor", body)
        self.assertIn("Nothing executes these", body)
        self.assertIn(reverse("strategy_wizard"), body)

    def test_the_plan_filter_still_works(self):
        from strategies.models import Strategy
        Strategy.objects.create(name="Plan active", description="d",
                                time_horizon="swing", status="active")
        Strategy.objects.create(name="Plan proposed", description="d",
                                time_horizon="swing", status="proposed")
        resp = self.client.get(reverse("strategies_list") + "?status=active",
                               HTTP_HOST="127.0.0.1")
        # Asserted on the page's own list, not the rendered body: the bottom
        # headband legitimately shows platform-wide activity and would match
        # a plan this filter excluded.
        names = [p.name for p in resp.context["plans"]]
        self.assertEqual(names, ["Plan active"])

    def test_zero_plans_does_not_read_as_zero_strategies(self):
        """The exact sentence the operator hit: rules running, plans empty."""
        _rule("running_rule", "paper")
        body = self._get().content.decode("utf-8", "replace")
        self.assertIn("running_rule", body)
        self.assertIn("none is needed for the engine to run", body)


class LadderNavigationTests(TestCase):
    """The four pages that explain a rule's life were orphaned: zero
    occurrences in base.html, reachable only from the admin dashboard."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("nav_u", password="x")

    def setUp(self):
        self.client.force_login(self.user)

    LADDER_PAGES = ("promotions_dashboard", "rule_control_dashboard",
                    "allocator_dashboard", "discoveries_dashboard")

    def test_every_ladder_page_is_in_the_sidebar(self):
        body = self.client.get(reverse("strategies_list"),
                               HTTP_HOST="127.0.0.1").content.decode(
                                   "utf-8", "replace")
        # Prefix match, not the full opening tag: the nav element carries
        # attributes now (data-nav-page-id for the unseen dots), and a
        # navigation test should not break when the tag grows one.
        nav = body[body.index('<nav class="sidebar-nav"'):
                   body.index("</nav>")]
        for name in self.LADDER_PAGES:
            self.assertIn(reverse(name), nav,
                          f"{name} is still orphaned from the menu")

    def test_every_ladder_page_actually_resolves(self):
        """A nav link to a 500 is worse than no nav link."""
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="nav_probe",
                                   promotion_stage="research")
        for name in self.LADDER_PAGES:
            with self.subTest(page=name):
                resp = self.client.get(reverse(name), HTTP_HOST="127.0.0.1")
                self.assertEqual(resp.status_code, 200)

    def test_a_card_deep_links_to_the_pages_that_explain_it(self):
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="linked_rule",
                                   promotion_stage="research")
        body = self.client.get(reverse("strategies_list"),
                               HTTP_HOST="127.0.0.1").content.decode(
                                   "utf-8", "replace")
        card = body[body.index('<article class="card sc-card"'):]
        card = card[:card.index("</article>")]
        for name in ("promotions_dashboard", "rule_control_dashboard",
                     "allocator_dashboard"):
            self.assertIn(reverse(name), card)


class LadderQueryBudgetTests(TestCase):
    """Signal / RuleControl / OpportunitySetup / AssetBotTrade are joined by a
    STRING (`rule_name`), so there is no select_related to lean on and the
    naive card loop is one query per card — plus one more for every per-rule
    call into `promotion_pipeline`."""

    # rules · setups · all-time stats · in-stage stats · signal recency ·
    # bot trades · mutations. Nothing in the card loop touches the database.
    LADDER_QUERIES = 7

    def _rules(self, n, stage="research", prefix="budget_rule"):
        from signals.models_control import RuleControl
        RuleControl.objects.bulk_create([
            RuleControl(rule_name=f"{prefix}_{i}", promotion_stage=stage,
                        stage_entered_at=timezone.now())
            for i in range(n)])

    def test_the_budget_is_fixed_at_three_rules(self):
        from dashboard.views import _promotion_ladder
        self._rules(3)
        with self.assertNumQueries(self.LADDER_QUERIES):
            _promotion_ladder()

    def test_the_budget_does_not_move_at_forty_rules(self):
        from dashboard.views import _promotion_ladder
        self._rules(40)
        with self.assertNumQueries(self.LADDER_QUERIES):
            _promotion_ladder()

    def test_an_empty_install_costs_two_queries(self):
        """No rules means no lookups to batch — it must not fan out anyway.

        Two, not one: the setup query runs before the no-rules return, because
        an armed OpportunitySetup scans whether or not anything registered it
        as a rule, and an install with no ladder row at all is exactly where
        that setup would otherwise be invisible.
        """
        from dashboard.views import _promotion_ladder
        with self.assertNumQueries(2):
            _promotion_ladder()

    def test_graded_signals_do_not_add_queries_per_rule(self):
        from dashboard.views import _promotion_ladder
        self._rules(12)
        for i in range(12):
            _closed_signals(f"budget_rule_{i}", [1.0, -1.0])
        with self.assertNumQueries(self.LADDER_QUERIES):
            _promotion_ladder()

    def test_the_whole_page_does_not_grow_with_the_rule_count(self):
        """Belt and braces: context processors make the absolute number
        uninteresting, but it must not MOVE when rules are added."""
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        user = User.objects.create_user("budget_u", password="x")
        self.client.force_login(user)
        url = reverse("strategies_list")
        self.client.get(url, HTTP_HOST="127.0.0.1")  # warm any per-process cache

        self._rules(3)
        with CaptureQueriesContext(connection) as small:
            self.client.get(url, HTTP_HOST="127.0.0.1")
        self._rules(40, stage="paper", prefix="budget_extra")
        with CaptureQueriesContext(connection) as large:
            self.client.get(url, HTTP_HOST="127.0.0.1")
        self.assertEqual(len(large), len(small),
                         "the page fans out one query per rule")


class GateMeterTests(TestCase):
    """The one piece of motion on the page painted nothing.

    `.sv-meter-fill` is a <span> inside `.sv-meter-track`. The track is the
    flex item, so blockification stops there and never reaches the child; no
    stylesheet gave the fill a display, and `width`/`height` do not apply to a
    non-replaced inline box. Every gate meter drew an empty groove at every
    stage and every percentage — while the view computed the number correctly
    and the JS sweep animated a property the box was ignoring.
    """

    def _css(self):
        from pathlib import Path
        from django.conf import settings
        return Path(settings.BASE_DIR).joinpath(
            "static", "css", "sauron.css").read_text(encoding="utf-8")

    def _rule_body(self, css, selector):
        start = css.index(selector + " {")
        return css[start:css.index("}", start)]

    def test_the_gate_fill_is_a_block_box(self):
        body = self._rule_body(self._css(), ".sv-meter-fill.sc-gate-fill")
        self.assertIn("display: block", body,
                      "the fill is inline again — width does not apply to a "
                      "non-replaced inline box, so the meter paints nothing")
        self.assertIn("width: var(--sc-fill", body)

    def test_the_markup_still_uses_the_component_the_rule_targets(self):
        """A renamed class would take the display with it, silently."""
        from pathlib import Path
        from django.conf import settings
        html = Path(settings.BASE_DIR).joinpath(
            "templates", "dashboard", "strategies_list.html").read_text(
            encoding="utf-8")
        self.assertIn("sv-meter-fill sc-gate-fill", html)
        self.assertIn("--sc-fill:", html)

    def test_a_half_measured_rule_emits_a_half_width_fill(self):
        from signals.promotion_pipeline import PROMO_RESEARCH_TO_PAPER_MIN_N
        user = User.objects.create_user("meter_u", password="x")
        self.client.force_login(user)
        _rule("half_way", "research")
        _closed_signals("half_way", [1.0] * (PROMO_RESEARCH_TO_PAPER_MIN_N // 2))
        body = self.client.get(reverse("strategies_list"),
                               HTTP_HOST="127.0.0.1").content.decode(
                                   "utf-8", "replace")
        self.assertIn("--sc-fill: 50%", body)


class RunningPopulationTests(TestCase):
    """What the headband cell means by "STRATEGIES n active".

    `status="active"` is not that population. `reduced` is a running state —
    `rule_size_multiplier` reads weight_multiplier only when status is
    "reduced", i.e. the field exists to size a rule that is still trading —
    and a `paused` rule whose paused_until has elapsed is running again,
    because `is_effectively_active()` computes expiry on the fly while nothing
    anywhere writes the column back to "active".
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("running_u", password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def _get(self):
        return self.client.get(reverse("strategies_list"), HTTP_HOST="127.0.0.1")

    def test_the_filter_and_the_model_method_name_the_same_population(self):
        """`is_effectively_active()` is a Python method and cannot be used in
        a queryset, so the predicate is restated once as a Q. This is the
        assertion that keeps the two from drifting apart."""
        from core.context_processors import running_rules_q
        from signals.models_control import RuleControl
        now = timezone.now()
        past, future = now - timedelta(days=1), now + timedelta(days=1)
        for name, status, until in (
                ("plain_active", "active", None),
                ("active_stale_pause", "active", past),
                ("reduced_plain", "reduced", None),
                ("reduced_with_pause", "reduced", future),
                ("paused_no_deadline", "paused", None),
                ("paused_until_tomorrow", "paused", future),
                ("pause_expired", "paused", past)):
            _rule(name, status=status, paused_until=until)

        by_filter = set(RuleControl.objects.filter(running_rules_q(now))
                        .values_list("rule_name", flat=True))
        by_method = {r.rule_name for r in RuleControl.objects.all()
                     if r.is_effectively_active(now)}
        self.assertEqual(by_filter, by_method)
        # Spelled out too, so a "fix" that makes both wrong still fails.
        self.assertIn("reduced_plain", by_filter)
        self.assertIn("pause_expired", by_filter)
        self.assertNotIn("paused_until_tomorrow", by_filter)
        self.assertNotIn("paused_no_deadline", by_filter)

    def test_the_headband_counts_a_reduced_rule_and_an_expired_pause(self):
        _rule("hb_active", status="active")
        _rule("hb_reduced", status="reduced")
        _rule("hb_pause_expired", status="paused",
              paused_until=timezone.now() - timedelta(days=1))
        _rule("hb_paused", status="paused",
              paused_until=timezone.now() + timedelta(days=30))
        self.assertEqual(self._get().context["panel_strategies"], 3)

    def test_the_ladder_count_is_every_row_including_the_paused_one(self):
        """The two numbers measure different things on purpose: the headband
        says "active", the ladder says "in the ladder". A paused rule is on
        the ladder and is not running."""
        from core.wall_facts import _count_strategies
        from signals.models_control import RuleControl
        _rule("both_active")
        _rule("only_ladder", status="paused",
              paused_until=timezone.now() + timedelta(days=30))
        ctx = self._get().context
        self.assertEqual(ctx["n_rules"], RuleControl.objects.count())
        self.assertEqual(ctx["n_rules"], _count_strategies())
        self.assertEqual(ctx["n_running"], 1)

    def test_the_page_prints_the_headband_number_beside_the_ladder_number(self):
        """The cell deep-links here. If the two numbers never appear together,
        the operator has no way to see them reconcile."""
        _rule("visible_a")
        _rule("visible_b", status="paused",
              paused_until=timezone.now() + timedelta(days=30))
        resp = self._get()
        self.assertEqual(resp.context["n_running"],
                         resp.context["panel_strategies"])
        self.assertIn("1 running", resp.content.decode("utf-8", "replace"))

    def test_a_reduced_rule_is_not_dropped_from_the_dropdown_either(self):
        _rule("dd_reduced", status="reduced")
        names = [d["name"]
                 for d in self._get().context["panel_recent_strategies"]]
        self.assertIn("dd_reduced", names)


class HeadbandDropdownOrderTests(TestCase):
    """`stage_entered_at` is nullable and neither seeder writes it, so all
    twelve shipped rules carry NULL. A bare `-stage_entered_at` lets the
    backend decide where NULLs land: PostgreSQL (production) sorts them
    largest, so DESC put every never-promoted rule ahead of every rule that
    had actually earned its stage. SQLite (dev, CI) does the opposite, which
    is why nothing local ever showed it.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("dropdown_u", password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def _panel(self):
        resp = self.client.get(reverse("strategies_list"), HTTP_HOST="127.0.0.1")
        return [d["name"] for d in resp.context["panel_recent_strategies"]]

    def _created(self, ctrl, days_ago):
        """created_at is auto_now_add; .update() is the only way past it."""
        from signals.models_control import RuleControl
        RuleControl.objects.filter(pk=ctrl.pk).update(
            created_at=timezone.now() - timedelta(days=days_ago))

    def test_a_promoted_rule_is_not_buried_behind_six_that_never_moved(self):
        from signals.models_control import RuleControl
        for i in range(6):
            self._created(RuleControl.objects.create(
                rule_name=f"aaa_never_moved_{i}", promotion_stage="research"), 2)
        RuleControl.objects.create(
            rule_name="zzz_promoted", promotion_stage="paper",
            stage_entered_at=timezone.now())
        self.assertEqual(self._panel()[0], "zzz_promoted")

    def test_never_moved_rules_rank_by_creation_recency_not_the_alphabet(self):
        """Coalescing onto created_at, rather than merely parking NULLs at the
        back, is what gives a never-moved rule a real recency — the idiom
        dashboard.views and promotion_pipeline already read this field with."""
        from signals.models_control import RuleControl
        old = RuleControl.objects.create(rule_name="aaa_seeded_first")
        new = RuleControl.objects.create(rule_name="zzz_seeded_last")
        self._created(old, 30)
        self._created(new, 1)
        self.assertEqual(self._panel(), ["zzz_seeded_last", "aaa_seeded_first"])

    def test_the_dropdown_is_capped_at_five(self):
        from signals.models_control import RuleControl
        for i in range(9):
            RuleControl.objects.create(rule_name=f"cap_rule_{i}")
        self.assertEqual(len(self._panel()), 5)


class DeadContextQueryTests(TestCase):
    """`sauron_context` is a global context processor: every line in it runs
    once per authenticated page render, forever."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("dead_u", password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def test_nothing_renders_panel_proposed_so_nothing_computes_it(self):
        from pathlib import Path
        from django.conf import settings
        readers = [str(p) for p in Path(settings.BASE_DIR).rglob("*.html")
                   if "panel_proposed" in p.read_text(encoding="utf-8",
                                                      errors="replace")]
        self.assertEqual(readers, [],
                         "a template reads panel_proposed — surface it in the "
                         "context processor instead of deleting the query")
        resp = self.client.get(reverse("strategies_list"), HTTP_HOST="127.0.0.1")
        self.assertNotIn("panel_proposed", resp.context)


class UnbackedSetupTests(TestCase):
    """`scan_all_setups` iterates OpportunitySetup.objects.filter(is_active=
    True) and never consults RuleControl; `stage_policy` reads a missing
    RuleControl row as PAPER with may_trade=True. So a setup nobody registered
    scans every pass, writes signals, and may place paper orders at full
    nominal size — while the page that claims to show what is running showed
    nothing for it, and its own "n of m setups armed" counter left it out.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("unbacked_u", password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def _get(self):
        return self.client.get(reverse("strategies_list"), HTTP_HOST="127.0.0.1")

    def test_an_armed_setup_with_no_rule_row_is_on_the_page(self):
        _rule("registered_rule", "research")
        _setup("registered_rule")
        _setup("hand_armed_orphan")
        resp = self._get()
        self.assertEqual([s["name"] for s in resp.context["unbacked_setups"]],
                         ["hand_armed_orphan"])
        body = resp.content.decode("utf-8", "replace")
        self.assertIn("hand_armed_orphan", body)
        self.assertIn("Scanning without a ladder row", body)

    def test_it_is_counted_in_the_setups_armed_line(self):
        _rule("counted_rule", "research")
        _setup("counted_rule")
        _setup("orphan_one")
        _setup("orphan_two")
        ctx = self._get().context
        self.assertEqual(ctx["n_setups"], 3)
        self.assertEqual(ctx["n_armed"], 3)

    def test_a_setup_nobody_armed_is_not_advertised_as_running(self):
        """Mined candidates awaiting review live in /discoveries/. They do not
        scan, so this section must not claim they do."""
        _rule("quiet_rule", "research")
        _setup("mined_candidate", active=False)
        resp = self._get()
        self.assertEqual(resp.context["unbacked_setups"], [])
        self.assertNotIn("Scanning without a ladder row",
                         resp.content.decode("utf-8", "replace"))

    def test_it_is_visible_even_when_the_ladder_is_completely_empty(self):
        """The worst case: the empty state used to say nothing scans, on an
        install where something was scanning."""
        _setup("orphan_on_a_bare_install")
        resp = self._get()
        body = resp.content.decode("utf-8", "replace")
        self.assertEqual(resp.context["n_armed"], 1)
        self.assertIn("orphan_on_a_bare_install", body)
        self.assertIn("NO RULE IS REGISTERED", body)
        # Whitespace-normalised: the sentence wraps across template lines, and
        # asserting on the raw body makes the test a hostage to indentation.
        self.assertIn("nothing it governs scans", " ".join(body.split()))

    def test_a_forks_inherited_setup_does_not_count_as_unbacked(self):
        """A fork borrows its parent's definition, so the parent's setup backs
        a rule on this page even though no rule carries its name."""
        _setup("golden_cross")
        _rule("golden_cross_evolved_v2", "research")
        resp = self._get()
        self.assertEqual(resp.context["unbacked_setups"], [])
        self.assertEqual(resp.context["n_setups"], 1)

    def test_the_query_budget_does_not_move_when_orphans_exist(self):
        from dashboard.views import _promotion_ladder
        _rule("budget_backed", "research")
        _setup("budget_backed")
        for i in range(6):
            _setup(f"budget_orphan_{i}")
        with self.assertNumQueries(LadderQueryBudgetTests.LADDER_QUERIES):
            _promotion_ladder()


class GateIsNotAWeightedLegTests(TestCase):
    """A gate is a precondition. The card used to draw it as a vote.

    `scan_setup` reads `cond["gate"]` and returns {"skipped": True, "reason":
    "gate_failed"} BEFORE it touches `weighted_score_sum` or `weight_sum`, so a
    gate contributes no score, no denominator, and cannot be outvoted by any
    amount of evidence. Printing "×1.0" beside it said the opposite twice over:
    that the universe check was roughly a third of a vote, and that the seeded
    `starter_usd_weakness_macro` composites over 3.5 of weight. The scanner
    divides by 2.5 — the difference between a setup that fires at 0.76 and one
    the operator concludes can never reach its own 0.70 bar.
    """

    # The shape of the only gated setup the platform ships
    # (seed_strategies.starter_usd_weakness_macro).
    GATED = [
        {"kind": "quote_currency", "params": {"currency": "USD"}, "gate": True},
        {"kind": "macro_trend", "params": {"series": "DXY"}, "weight": 1.5},
        {"kind": "cot_report", "params": {"lookback_weeks": 4}, "weight": 1.0},
    ]

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("gate_u", password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def _get(self):
        return self.client.get(reverse("strategies_list"), HTTP_HOST="127.0.0.1")

    def _gated_card(self):
        """The rendered response plus the one card's setup context."""
        _rule("usd_weakness", "research")
        _setup("usd_weakness", conditions=self.GATED, min_match_score=0.70)
        resp = self._get()
        cards = {c["rule"]: c for g in resp.context["stage_groups"]
                 for c in g["cards"]}
        return resp, cards["usd_weakness"]["setup"]

    @staticmethod
    def _cond_block(body):
        """Just the condition list, so a dash elsewhere on the card cannot
        stand in for the one this test is about."""
        start = body.index('class="sc-cond"')
        return body[start:body.index("</ul>", start)]

    @staticmethod
    def _setup_block(body):
        """The whole `<details>` — condition list plus the foot that states
        the threshold. Scoped, because the chrome around it is full of
        unrelated numbers."""
        start = body.index('class="sc-setup"')
        return " ".join(body[start:body.index("</details>", start)].split())

    # ── The gate is marked as a gate ───────────────────────────────────

    def test_the_gate_carries_no_weight_and_says_what_it_is(self):
        resp, setup = self._gated_card()
        kinds = {c["kind"]: c for c in setup["conditions"]}
        self.assertTrue(kinds["quote_currency"]["gate"])
        self.assertFalse(kinds["macro_trend"]["gate"])

        block = self._cond_block(resp.content.decode("utf-8", "replace"))
        self.assertIn('data-gate="1"', block)
        self.assertIn("GATE", block)
        self.assertIn("required", block)
        # The scoring legs keep their weights; only the gate loses one, so
        # three conditions carry exactly two weights.
        self.assertIn("&times;1.5", block)
        self.assertEqual(block.count("&times;"), 2)

    def test_the_gate_is_not_counted_as_a_scoring_condition(self):
        """"3 conditions" over two legs and a gate describes a setup that does
        not exist."""
        resp, setup = self._gated_card()
        self.assertEqual(setup["n_scoring"], 2)
        self.assertEqual(setup["n_gates"], 1)
        block = self._setup_block(resp.content.decode("utf-8", "replace"))
        self.assertIn("2 scoring conditions · 1 gate", block)
        self.assertNotIn("3 conditions", block)

    def test_the_card_states_the_denominator_the_scanner_divides_by(self):
        resp, setup = self._gated_card()
        self.assertEqual(setup["weight_sum"], 2.5)
        self.assertEqual(setup["weight_sum_display"], "2.5")
        block = self._setup_block(resp.content.decode("utf-8", "replace"))
        self.assertIn("match &ge; 0.7 of 2.5 total weight", block)
        # The total an operator would add up from the old card.
        self.assertNotIn("3.5", block)

    def test_the_card_says_a_gate_cannot_be_outvoted(self):
        """The number alone does not teach the mechanism; the operator has to
        be told the setup is SKIPPED, not merely marked down."""
        resp, _ = self._gated_card()
        block = self._setup_block(resp.content.decode("utf-8", "replace"))
        self.assertIn("precondition, not a leg", block)
        self.assertIn("skipped before anything is scored", block)

    # ── The arithmetic on the card is the scanner's arithmetic ─────────

    def test_the_cards_numbers_reproduce_the_scanners_verdict(self):
        """With macro_trend at 1.0 and cot_report at 0.4, the scanner fires and
        an operator reading the old card concluded it could not."""
        _resp, setup = self._gated_card()
        scored = 1.0 * 1.5 + 0.4 * 1.0
        composite = scored / setup["weight_sum"]
        self.assertAlmostEqual(composite, 0.76, places=6)
        self.assertGreaterEqual(composite, setup["min_match_score"])
        # What the page used to imply: three legs, 3.5 of weight, no match.
        self.assertLess(scored / 3.5, setup["min_match_score"])

    def test_the_engine_short_circuits_on_the_key_the_page_reads(self):
        """The page's `gate` and the scanner's `gate` have to be the same key.

        An unknown kind is the cheapest gate failure to provoke: `scan_setup`
        returns before any evaluator, price lookup or write.
        """
        from signals.opportunity_scanner import scan_setup
        from signals.models_opportunity import OpportunitySetup
        setup = OpportunitySetup.objects.create(
            name="gate_contract", direction="bullish", asset_classes=["stock"],
            is_active=True,
            conditions=[{"kind": "no_such_kind", "gate": True},
                        {"kind": "no_such_kind_either", "weight": 1.0}])
        res = scan_setup(setup, _instrument("SP_GATE"))
        self.assertTrue(res["skipped"])
        self.assertEqual(res["reason"], "gate_failed")
        self.assertFalse(res["matched"])

    # ── Edges ──────────────────────────────────────────────────────────

    def test_an_ungated_setup_is_described_exactly_as_before(self):
        _rule("plain_rule", "research")
        _setup("plain_rule", conditions=[
            {"kind": "price_pattern", "params": {"ma_period": 50}},
            {"kind": "volume_spike", "weight": 2.0}])
        resp = self._get()
        cards = {c["rule"]: c for g in resp.context["stage_groups"]
                 for c in g["cards"]}
        setup = cards["plain_rule"]["setup"]
        self.assertEqual(setup["n_gates"], 0)
        self.assertEqual(setup["n_scoring"], 2)
        self.assertEqual(setup["weight_sum"], 3.0)
        body = resp.content.decode("utf-8", "replace")
        self.assertNotIn('data-gate="1"', body)
        self.assertNotIn("precondition, not a leg", body)

    def test_a_weight_the_scanner_cannot_read_is_a_dash_not_a_one(self):
        """`float(cond.get("weight", 1.0))` RAISES in scan_setup on "1,5" — so
        the weight is unknown, and the total it belongs to is unknown too."""
        _rule("bad_weight", "research")
        _setup("bad_weight", conditions=[
            {"kind": "macro_trend", "weight": "1,5"},
            {"kind": "cot_report", "weight": 1.0}])
        resp = self._get()
        cards = {c["rule"]: c for g in resp.context["stage_groups"]
                 for c in g["cards"]}
        setup = cards["bad_weight"]["setup"]
        self.assertIsNone(setup["conditions"][0]["weight"])
        self.assertIsNone(setup["weight_sum"])
        self.assertEqual(setup["weight_sum_display"], "—")
        block = self._cond_block(resp.content.decode("utf-8", "replace"))
        self.assertIn("sv-unknown", block)
        self.assertNotIn("1,5", block)

    def test_a_setup_that_is_all_gate_does_not_claim_a_threshold(self):
        """Every condition a gate means `weight_sum` is 0 in the scanner, so
        the composite is 0 whatever the evidence says."""
        _rule("all_gate", "research")
        _setup("all_gate", conditions=[
            {"kind": "quote_currency", "params": {"currency": "USD"},
             "gate": True}])
        resp = self._get()
        cards = {c["rule"]: c for g in resp.context["stage_groups"]
                 for c in g["cards"]}
        self.assertEqual(cards["all_gate"]["setup"]["n_scoring"], 0)
        body = " ".join(resp.content.decode("utf-8", "replace").split())
        self.assertIn("no scoring condition", body)

    def test_an_unbacked_setups_gate_is_split_out_too(self):
        """The orphan list draws from the same conditions and made the same
        claim about them."""
        _setup("orphan_with_a_gate", conditions=self.GATED)
        resp = self._get()
        row = resp.context["unbacked_setups"][0]
        self.assertEqual(row["n_scoring"], 2)
        self.assertEqual(row["n_gates"], 1)
        body = " ".join(resp.content.decode("utf-8", "replace").split())
        self.assertIn("2 scoring conditions · 1 gate", body)


class PlanAnalyticsLabelTests(TestCase):
    """/htmx/metrics/strategies/ reads `strategies.Strategy` only — the
    wizard's plans. Its partial prints "Strategy overview / Total / Active",
    which on this page is the exact confusion the rewrite exists to end: an
    install with twelve rules running and no plan written read "Active 0"
    under an unqualified "Strategy Analytics" heading.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("analytics_u", password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def test_the_analytics_card_says_it_is_about_plans(self):
        _rule("engine_rule", "live_full")
        body = self.client.get(reverse("strategies_list"),
                               HTTP_HOST="127.0.0.1").content.decode(
                                   "utf-8", "replace")
        card = body[body.index('class="card sc-analytics"'):]
        card = card[:card.index("sv-metrics-wrapper")]
        self.assertIn("Trade-plan analytics", card)
        self.assertNotIn("Strategy Analytics", body)
        # The partial is shared and untouched, so its "Active" tile is named
        # and disowned by the card that frames it.
        self.assertIn("never a rule the engine runs", card)
        # Still wired: relabelling must not silently drop the panel.
        self.assertIn("/htmx/metrics/strategies/",
                      body[body.index('class="card sc-analytics"'):])
