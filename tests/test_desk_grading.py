"""The capital desk's grade (Stage 3, 2026-09-12).

A desk that ranks is only worth keeping if the ranking beats the fleet it
overruled — and that comparison is impossible unless the entries the desk
REFUSED are priced too. These tests pin the arithmetic that prices them:

  - THE BRACKET WALK: stop first is −1R, target first is the planned reward
    in units of that risk, neither is a mark to market at the horizon, and a
    bar that contains BOTH books the stop — a bar says what was touched,
    never in what order, and assuming the good half printed first is how a
    backtest invents an edge;
  - UNGRADEABLE IS NOT ZERO: no bars after the grace, no stop to measure
    against, or a closed trade whose exit could not be priced, all resolve
    with counterfactual_r NULL and are counted separately;
  - THE TAKEN SIDE: a chosen decision's R is its own trade's realized_r, and
    NULL stays NULL;
  - EDGE R: the desk's set (realized_r × size_mult) minus the default set
    (every desked candidate at size 1.0), with NULLs excluded from both and
    edge_r itself None when nothing on the plan could be priced;
  - THE BEAT: the task exists, is gated on the component, is scheduled, and
    reports counters the task gate will not read as "handled rows and stored
    none";
  - THE REGISTRY: the two components fit their columns, the WIRING entry
    names the task and the page, and the live switch is a MODE_FLAG of the
    pipeline one.

Run with:  python manage.py test tests.test_desk_grading
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _user(name="grade_u"):
    return User.objects.create_user(username=name, password="x")


def _config(user, **overrides):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        user=user, asset_class="stock", name="Desk Bot", enabled=True,
        mode="paper", symbols=[], capital=Decimal("10000"),
        base_currency="USD", position_size_pct=2.0,
        max_concurrent_positions=5, max_daily_loss_pct=2.0,
        stop_loss_pct=1.5, take_profit_pct=3.0, entry_score_min=0.6,
        min_signals_for_entry=1, cool_down_minutes=0,
    )
    defaults.update(overrides)
    return AssetBotConfig.objects.create(**defaults)


def _plan(user, *, created_at=None, **overrides):
    from bot_program.models import DeskPlan
    defaults = dict(user=user, venue="paper", mode="shadow",
                    budget=Decimal("100"), book_risk=Decimal("0"),
                    new_risk_chosen=Decimal("40"), n_candidates=2)
    defaults.update(overrides)
    plan = DeskPlan.objects.create(**defaults)
    if created_at is not None:
        DeskPlan.objects.filter(pk=plan.pk).update(created_at=created_at)
        plan.refresh_from_db()
    return plan


def _decision(plan, cfg, *, created_at=None, **overrides):
    from bot_program.models import DeskDecision
    defaults = dict(plan=plan, config=cfg, symbol="AAPL", direction="BUY",
                    rule_name="desk_rule", lane="config_live", n=12,
                    e_r=0.3, rank_key=0.3, measured=True,
                    risk_dollars_default=Decimal("20"),
                    marginal_risk=Decimal("20"), rank=1, outcome="displaced",
                    reason="budget — nothing free", size_mult=1.0,
                    qty_default=Decimal("1"), price=Decimal("100"),
                    stop=Decimal("95"), target=Decimal("115"),
                    horizon_hours=24.0)
    defaults.update(overrides)
    row = DeskDecision.objects.create(**defaults)
    if created_at is not None:
        DeskDecision.objects.filter(pk=row.pk).update(created_at=created_at)
        row.refresh_from_db()
    return row


def _bar(symbol, ts, *, high, low, close, timeframe="1h", asset_class="stock"):
    from instruments.models import Instrument
    from market_data.models import PriceData
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return PriceData.objects.create(
        instrument=inst, timeframe=timeframe, timestamp=ts,
        open=Decimal(str(close)), high=Decimal(str(high)),
        low=Decimal(str(low)), close=Decimal(str(close)),
        volume=1, source="test")


def _trade(cfg, *, realized_r, status="CLOSED", outcome="hit_target"):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol="AAPL", side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"), status=status,
        outcome=outcome, realized_r=realized_r, rule_name="desk_rule",
        paper=True, closed_at=timezone.now())


# ── the bracket walk ────────────────────────────────────────────────────

class BracketWalkTests(SimpleTestCase):
    """Pure arithmetic — no database, because the walk is the part that must
    be provably right before anything is written down."""

    def _bars(self, rows):
        now = timezone.now()
        return [(now + timedelta(hours=i), h, l, c)
                for i, (h, l, c) in enumerate(rows)]

    def test_stop_first_is_minus_one_r(self):
        from bot_program.capital_desk import CF_STOP, walk_bracket
        r, outcome = walk_bracket(
            direction="BUY", price=100, stop=95, target=115,
            bars=self._bars([(101, 99, 100), (102, 94, 96)]))
        self.assertEqual(outcome, CF_STOP)
        self.assertEqual(r, -1.0)

    def test_target_first_is_the_planned_reward_in_that_risk(self):
        from bot_program.capital_desk import CF_TARGET, walk_bracket
        r, outcome = walk_bracket(
            direction="BUY", price=100, stop=95, target=115,
            bars=self._bars([(101, 99, 100), (116, 110, 115)]))
        self.assertEqual(outcome, CF_TARGET)
        self.assertAlmostEqual(r, 3.0, places=9)   # 15 of reward over 5 of risk

    def test_neither_touched_marks_to_market_at_the_horizon(self):
        from bot_program.capital_desk import CF_OPEN, walk_bracket
        r, outcome = walk_bracket(
            direction="BUY", price=100, stop=95, target=115,
            bars=self._bars([(101, 99, 100), (104, 99, 102.5)]))
        self.assertEqual(outcome, CF_OPEN)
        self.assertAlmostEqual(r, 0.5, places=9)   # +2.5 of a 5-wide risk

    def test_one_bar_holding_both_books_the_stop(self):
        """A bar says WHAT was touched, never in what order. Assuming the
        good half printed first is how a backtest invents an edge — and on a
        displaced decision that assumption flatters the DESK's own score."""
        from bot_program.capital_desk import CF_STOP, walk_bracket
        r, outcome = walk_bracket(
            direction="BUY", price=100, stop=95, target=115,
            bars=self._bars([(120, 90, 110)]))
        self.assertEqual(outcome, CF_STOP)
        self.assertEqual(r, -1.0)

    def test_a_short_reads_its_levels_the_other_way_round(self):
        from bot_program.capital_desk import CF_TARGET, walk_bracket
        r, outcome = walk_bracket(
            direction="SELL", price=100, stop=105, target=90,
            bars=self._bars([(101, 99, 100), (100, 89, 90)]))
        self.assertEqual(outcome, CF_TARGET)
        self.assertAlmostEqual(r, 2.0, places=9)

        r, outcome = walk_bracket(
            direction="SELL", price=100, stop=105, target=90,
            bars=self._bars([(103, 99, 102)]))
        self.assertAlmostEqual(r, -0.4, places=9)   # marked to market, short

    def test_no_risk_to_measure_against_is_ungradeable_not_zero(self):
        from bot_program.capital_desk import CF_UNGRADEABLE, walk_bracket
        r, outcome = walk_bracket(
            direction="BUY", price=100, stop=100, target=115,
            bars=self._bars([(101, 99, 100)]))
        self.assertIsNone(r)
        self.assertEqual(outcome, CF_UNGRADEABLE)


# ── resolving ───────────────────────────────────────────────────────────

class ResolveCounterfactualsTests(TestCase):

    def setUp(self):
        self.user = _user()
        self.cfg = _config(self.user)
        self.now = timezone.now()
        self.start = self.now - timedelta(hours=48)

    def test_a_displaced_decision_is_walked_over_its_own_horizon(self):
        from bot_program.capital_desk import CF_TARGET, resolve_counterfactuals
        plan = _plan(self.user, created_at=self.start)
        d = _decision(plan, self.cfg, created_at=self.start)
        _bar("AAPL", self.start + timedelta(hours=2), high=116, low=110,
             close=115)
        self.assertEqual(resolve_counterfactuals(now=self.now), 1)
        d.refresh_from_db()
        self.assertEqual(d.counterfactual_outcome, CF_TARGET)
        self.assertAlmostEqual(d.counterfactual_r, 3.0, places=6)
        self.assertIsNotNone(d.resolved_at)

    def test_a_bar_after_the_horizon_is_not_in_the_walk(self):
        """The horizon is the bound. A target hit two days after the setup
        expired is not a trade the fleet would have been in."""
        from bot_program.capital_desk import CF_OPEN, resolve_counterfactuals
        plan = _plan(self.user, created_at=self.start)
        d = _decision(plan, self.cfg, created_at=self.start)
        _bar("AAPL", self.start + timedelta(hours=2), high=102, low=99,
             close=101)
        _bar("AAPL", self.start + timedelta(hours=30), high=130, low=120,
             close=125)
        resolve_counterfactuals(now=self.now)
        d.refresh_from_db()
        self.assertEqual(d.counterfactual_outcome, CF_OPEN)
        self.assertAlmostEqual(d.counterfactual_r, 0.2, places=6)

    def test_an_unclosed_horizon_is_left_alone(self):
        from bot_program.capital_desk import resolve_counterfactuals
        plan = _plan(self.user)
        d = _decision(plan, self.cfg, horizon_hours=168.0)
        self.assertEqual(resolve_counterfactuals(now=self.now), 0)
        d.refresh_from_db()
        self.assertIsNone(d.resolved_at)

    def test_no_bars_waits_through_the_grace_then_says_ungradeable(self):
        from bot_program.capital_desk import (COUNTERFACTUAL_GRACE_HOURS,
                                              CF_UNGRADEABLE,
                                              resolve_counterfactuals)
        start = self.now - timedelta(hours=25)
        plan = _plan(self.user, created_at=start)
        d = _decision(plan, self.cfg, created_at=start)   # horizon 24h
        self.assertEqual(resolve_counterfactuals(now=self.now), 0,
                         "inside the grace the desk waits for the feed")
        d.refresh_from_db()
        self.assertIsNone(d.resolved_at)

        later = start + timedelta(hours=24 + COUNTERFACTUAL_GRACE_HOURS + 1)
        self.assertEqual(resolve_counterfactuals(now=later), 1)
        d.refresh_from_db()
        self.assertEqual(d.counterfactual_outcome, CF_UNGRADEABLE)
        self.assertIsNone(d.counterfactual_r,
                          "an unpriceable decision is NULL, never 0.0")
        self.assertIsNotNone(d.resolved_at)

    def test_a_decision_with_no_stop_settles_at_once(self):
        """Waiting cannot supply a risk denominator that was never stored."""
        from bot_program.capital_desk import (CF_UNGRADEABLE,
                                              resolve_counterfactuals)
        plan = _plan(self.user, created_at=self.start)
        d = _decision(plan, self.cfg, created_at=self.start, stop=None)
        self.assertEqual(resolve_counterfactuals(now=self.now), 1)
        d.refresh_from_db()
        self.assertEqual(d.counterfactual_outcome, CF_UNGRADEABLE)
        self.assertIsNone(d.counterfactual_r)

    def test_a_taken_decision_takes_its_r_from_its_trade(self):
        from bot_program.capital_desk import resolve_counterfactuals
        plan = _plan(self.user, created_at=self.start)
        trade = _trade(self.cfg, realized_r=1.7)
        d = _decision(plan, self.cfg, created_at=self.start,
                      outcome="chosen", trade=trade, size_mult=1.0)
        self.assertEqual(resolve_counterfactuals(now=self.now), 1)
        d.refresh_from_db()
        self.assertAlmostEqual(d.counterfactual_r, 1.7, places=6)
        self.assertEqual(d.counterfactual_outcome, "hit_target")

    def test_an_open_trade_is_not_resolved_yet(self):
        from bot_program.capital_desk import resolve_counterfactuals
        plan = _plan(self.user, created_at=self.start)
        trade = _trade(self.cfg, realized_r=None, status="OPEN", outcome="")
        d = _decision(plan, self.cfg, created_at=self.start,
                      outcome="chosen", trade=trade)
        self.assertEqual(resolve_counterfactuals(now=self.now), 0)
        d.refresh_from_db()
        self.assertIsNone(d.resolved_at)

    def test_an_open_trade_never_occupies_the_resolver_batch(self):
        """REGRESSION (adversarial review, 2026-09-12): a chosen decision
        whose trade is still OPEN can never resolve, and it stayed in the
        resolver's queryset forever. Filtered in Python behind a batch
        limit, a fleet's long-held positions would fill that batch — oldest
        first — and a trade that closed last night would never be reached
        again, so the desk would quietly stop grading itself. The
        closed-and-graded test belongs in the ORM filter, so the batch is
        spent on rows that can actually resolve."""
        from unittest.mock import patch

        from bot_program.capital_desk import resolve_counterfactuals
        plan = _plan(self.user, created_at=self.start)
        held = _trade(self.cfg, realized_r=None, status="OPEN", outcome="")
        _decision(plan, self.cfg, created_at=self.start - timedelta(days=5),
                  outcome="chosen", trade=held, symbol="HELD")
        done = _trade(self.cfg, realized_r=0.9)
        fresh = _decision(plan, self.cfg, created_at=self.start,
                          outcome="chosen", trade=done, symbol="DONE")
        # A batch of one: under the old filter the open row took it.
        with patch("bot_program.capital_desk.DESK_RESOLVE_BATCH", 1):
            resolve_counterfactuals(now=self.now)
        fresh.refresh_from_db()
        self.assertIsNotNone(fresh.resolved_at,
                             "a closed trade must not queue behind an open one")
        self.assertAlmostEqual(fresh.counterfactual_r, 0.9, places=6)

    def test_a_closed_trade_with_no_r_resolves_ungradeable(self):
        """AssetBotTrade.realized_r NULL means the exit could not be priced.
        NULL STAYS NULL — folding it in as a break-even would book a trade
        that never happened into the desk's score."""
        from bot_program.capital_desk import (CF_UNGRADEABLE,
                                              resolve_counterfactuals)
        plan = _plan(self.user, created_at=self.start)
        trade = _trade(self.cfg, realized_r=None, outcome="manual_close")
        d = _decision(plan, self.cfg, created_at=self.start,
                      outcome="resized", trade=trade)
        resolve_counterfactuals(now=self.now)
        d.refresh_from_db()
        self.assertIsNone(d.counterfactual_r)
        self.assertEqual(d.counterfactual_outcome, CF_UNGRADEABLE)

    def test_the_finest_timeframe_that_has_bars_wins(self):
        from bot_program.capital_desk import CF_STOP, resolve_counterfactuals
        plan = _plan(self.user, created_at=self.start)
        d = _decision(plan, self.cfg, created_at=self.start)
        # 4h says the day closed flat; 1h says the stop printed inside it.
        _bar("AAPL", self.start + timedelta(hours=1), high=101, low=94,
             close=100, timeframe="1h")
        _bar("AAPL", self.start + timedelta(hours=4), high=101, low=99,
             close=100, timeframe="4h")
        resolve_counterfactuals(now=self.now)
        d.refresh_from_db()
        self.assertEqual(d.counterfactual_outcome, CF_STOP)

    def test_a_not_desked_row_is_never_resolved(self):
        """The options lane trades whole; the desk did not decide it and has
        no claim on its result."""
        from bot_program.capital_desk import resolve_counterfactuals
        plan = _plan(self.user, created_at=self.start)
        d = _decision(plan, self.cfg, created_at=self.start,
                      outcome="not_desked")
        _bar("AAPL", self.start + timedelta(hours=2), high=116, low=110,
             close=115)
        self.assertEqual(resolve_counterfactuals(now=self.now), 0)
        d.refresh_from_db()
        self.assertIsNone(d.resolved_at)


# ── the edge ────────────────────────────────────────────────────────────

class GradePlansTests(TestCase):

    def setUp(self):
        self.user = _user("grade_e")
        self.cfg = _config(self.user)
        self.now = timezone.now()
        self.start = self.now - timedelta(hours=4)

    def _resolved(self, plan, **overrides):
        opts = dict(created_at=self.start, resolved_at=self.now)
        opts.update(overrides)
        return _decision(plan, self.cfg, **opts)

    def test_edge_is_the_desk_set_minus_the_fleets_default_set(self):
        from bot_program.capital_desk import grade_plans
        plan = _plan(self.user, created_at=self.start)
        # taken at half size, paid +2R; the fleet would have taken it whole
        self._resolved(plan, outcome="resized", size_mult=0.5,
                       counterfactual_r=2.0, rank=1)
        # displaced, and it would have lost 1R
        self._resolved(plan, symbol="MSFT", outcome="displaced",
                       counterfactual_r=-1.0, rank=2)
        self.assertEqual(grade_plans(now=self.now), 1)
        plan.refresh_from_db()
        # desk: 2.0 x 0.5 = 1.0 ; default: 2.0 + (-1.0) = 1.0 ; edge 0.0
        self.assertAlmostEqual(plan.edge_r, 0.0, places=6)
        self.assertEqual(plan.edge_detail["n_graded"], 2)
        self.assertAlmostEqual(plan.edge_detail["desk_r"], 1.0, places=6)
        self.assertAlmostEqual(plan.edge_detail["default_r"], 1.0, places=6)
        self.assertIsNotNone(plan.graded_at)

    def test_displacing_a_loser_is_positive_edge(self):
        from bot_program.capital_desk import grade_plans
        plan = _plan(self.user, created_at=self.start)
        self._resolved(plan, outcome="chosen", counterfactual_r=1.0, rank=1)
        self._resolved(plan, symbol="MSFT", outcome="displaced",
                       counterfactual_r=-1.0, rank=2)
        grade_plans(now=self.now)
        plan.refresh_from_db()
        self.assertAlmostEqual(plan.edge_r, 1.0, places=6)

    def test_nulls_are_excluded_from_both_sets_and_counted(self):
        from bot_program.capital_desk import grade_plans
        plan = _plan(self.user, created_at=self.start)
        self._resolved(plan, outcome="chosen", counterfactual_r=0.5, rank=1)
        self._resolved(plan, symbol="MSFT", outcome="displaced",
                       counterfactual_r=None,
                       counterfactual_outcome="ungradeable", rank=2)
        grade_plans(now=self.now)
        plan.refresh_from_db()
        self.assertAlmostEqual(plan.edge_detail["desk_r"], 0.5, places=6)
        self.assertAlmostEqual(plan.edge_detail["default_r"], 0.5, places=6)
        self.assertEqual(plan.edge_detail["n_graded"], 1)
        self.assertEqual(plan.edge_detail["n_ungradeable"], 1)

    def test_nothing_gradeable_leaves_edge_null_not_zero(self):
        """Zero would say the ranking made no difference. What actually
        happened is that nothing was measured."""
        from bot_program.capital_desk import grade_plans
        plan = _plan(self.user, created_at=self.start)
        self._resolved(plan, outcome="displaced", counterfactual_r=None,
                       counterfactual_outcome="ungradeable")
        grade_plans(now=self.now)
        plan.refresh_from_db()
        self.assertIsNone(plan.edge_r)
        self.assertIsNotNone(plan.graded_at)
        self.assertEqual(plan.edge_detail["n_graded"], 0)

    def test_an_unresolved_decision_holds_the_plan_until_the_grace(self):
        from bot_program.capital_desk import (PLAN_GRADE_GRACE_HOURS,
                                              grade_plans)
        plan = _plan(self.user, created_at=self.start)
        self._resolved(plan, outcome="chosen", counterfactual_r=1.0, rank=1)
        _decision(plan, self.cfg, symbol="MSFT", outcome="displaced",
                  created_at=self.start, rank=2)      # unresolved
        self.assertEqual(grade_plans(now=self.now), 0)
        plan.refresh_from_db()
        self.assertIsNone(plan.graded_at)

        later = self.start + timedelta(hours=PLAN_GRADE_GRACE_HOURS + 1)
        self.assertEqual(grade_plans(now=later), 1)
        plan.refresh_from_db()
        # The pending row left BOTH sums, so the chosen one nets to nothing:
        # the desk took what the fleet would have taken. What the plan must
        # carry is how much of itself was still open when the grace ran out.
        self.assertAlmostEqual(plan.edge_r, 0.0, places=6)
        self.assertEqual(plan.edge_detail["n_graded"], 1)
        self.assertEqual(plan.edge_detail["n_pending_at_grade"], 1)

    def test_by_rule_and_by_class_carry_the_split(self):
        from bot_program.capital_desk import grade_plans
        other = _config(self.user, name="FX", asset_class="forex")
        plan = _plan(self.user, created_at=self.start)
        self._resolved(plan, outcome="chosen", counterfactual_r=1.0, rank=1)
        from bot_program.models import DeskDecision
        DeskDecision.objects.create(
            plan=plan, config=other, symbol="EURUSD", direction="BUY",
            rule_name="fx_rule", lane="unmeasured", rank=2,
            outcome="displaced", counterfactual_r=-0.5,
            resolved_at=self.now, price=Decimal("1"), stop=Decimal("0.9"),
            target=Decimal("1.2"), horizon_hours=24.0)
        grade_plans(now=self.now)
        plan.refresh_from_db()
        self.assertIn("desk_rule", plan.edge_detail["by_rule"])
        self.assertIn("fx_rule", plan.edge_detail["by_rule"])
        self.assertEqual(set(plan.edge_detail["by_class"]),
                         {"stock", "forex"})
        self.assertAlmostEqual(
            plan.edge_detail["by_class"]["forex"]["edge_r"], 0.5, places=6)

    def test_a_graded_plan_is_never_graded_twice(self):
        from bot_program.capital_desk import grade_plans
        plan = _plan(self.user, created_at=self.start)
        self._resolved(plan, outcome="chosen", counterfactual_r=1.0)
        self.assertEqual(grade_plans(now=self.now), 1)
        self.assertEqual(grade_plans(now=self.now), 0)

    def test_a_failed_plan_grades_empty_at_the_grace(self):
        """The fail-open row has no decisions at all; it must still close,
        or it holds the graded_at index open forever."""
        from bot_program.capital_desk import (PLAN_GRADE_GRACE_HOURS,
                                              grade_plans)
        plan = _plan(self.user, created_at=self.start, error="matrix blew up")
        later = self.start + timedelta(hours=PLAN_GRADE_GRACE_HOURS + 1)
        self.assertEqual(grade_plans(now=later), 1)
        plan.refresh_from_db()
        self.assertIsNone(plan.edge_r)
        self.assertEqual(plan.edge_detail["n_graded"], 0)


# ── the beat ────────────────────────────────────────────────────────────

class TheNightlyTaskTests(TestCase):

    def test_the_task_runs_both_passes_and_reports_its_counters(self):
        from unittest.mock import patch

        from core.platform_control import PlatformComponent
        # The gate checks the master switch first, then the component.
        for key in ("platform_master", "pipeline_capital_desk"):
            PlatformComponent.objects.create(
                key=key, name="d", description="d", category="pipeline",
                is_enabled=True)
        from bot_program.tasks import grade_capital_desk
        with patch("bot_program.capital_desk.resolve_counterfactuals",
                   return_value=3) as res, \
                patch("bot_program.capital_desk.grade_plans",
                      return_value=2) as grade:
            out = grade_capital_desk()
        self.assertTrue(res.called and grade.called)
        self.assertEqual(out, {"status": "ok", "resolved": 3, "graded": 2})

    def test_the_task_is_gated_on_the_component(self):
        """A guarded task with no component row short-circuits on every beat;
        with the row off it must do nothing at all."""
        from unittest.mock import patch

        from core.platform_control import PlatformComponent
        PlatformComponent.objects.create(
            key="platform_master", name="d", description="d",
            category="system", is_enabled=True)
        from bot_program.tasks import grade_capital_desk
        with patch("bot_program.capital_desk.resolve_counterfactuals") as res:
            out = grade_capital_desk()
        self.assertFalse(res.called)
        self.assertEqual(out["status"], "skipped")

    def test_the_counters_are_not_read_as_handled_and_stored_none(self):
        """core.task_gate.judge_result marks a task WARNING when it reports
        `parsed`/`attempted` rows and no `stored`. A quiet night on the desk
        is patience, not silence."""
        from core.task_gate import judge_result
        status, _msg = judge_result({"status": "ok", "resolved": 0,
                                     "graded": 0})
        self.assertEqual(status, "success")


class TheRegistryTests(SimpleTestCase):

    def test_both_components_are_registered_and_fit_their_columns(self):
        from core.platform_control import (DEFAULT_COMPONENTS,
                                           PlatformComponent)
        by_key = {c["key"]: c for c in DEFAULT_COMPONENTS}
        for key in ("pipeline_capital_desk", "capital_desk_mode_live"):
            self.assertIn(key, by_key)
        limits = {f.name: f.max_length
                  for f in PlatformComponent._meta.get_fields()
                  if getattr(f, "max_length", None)}
        for key in ("pipeline_capital_desk", "capital_desk_mode_live"):
            row = by_key[key]
            for field in ("key", "name", "description", "category"):
                self.assertLessEqual(len(row[field]), limits[field],
                                     f"{key}.{field}")
        self.assertEqual(by_key["pipeline_capital_desk"]["category"],
                         "pipeline")
        self.assertEqual(by_key["capital_desk_mode_live"]["category"],
                         "system")
        # The live switch must say what it does and that shadow is default.
        self.assertIn("shadow", by_key["capital_desk_mode_live"]["description"])

    def test_the_wiring_names_the_task_the_writes_and_the_page(self):
        from dashboard.views_topology import WIRING
        node = WIRING["pipeline_capital_desk"]
        self.assertEqual(node["task"], "bot_program.tasks.grade_capital_desk")
        self.assertEqual(node["cadence"], 86400)
        self.assertEqual(node["layer"], "gate")
        self.assertEqual(node["pages"], ["/desk/"])
        self.assertIn("execute_bots", node["feeds"])
        for written in ("DeskPlan", "DeskDecision",
                        "AssetBotTrade.metadata.desk_*"):
            self.assertIn(written, node["writes"])

    def test_the_live_switch_is_a_mode_flag_of_the_pipeline_one(self):
        from dashboard.views_topology import MODE_FLAGS, WIRING
        self.assertEqual(MODE_FLAGS["capital_desk_mode_live"],
                         "pipeline_capital_desk")
        self.assertIn(MODE_FLAGS["capital_desk_mode_live"], WIRING)
        # A mode flag has no node of its own — four edgeless boxes read as
        # four broken things.
        self.assertNotIn("capital_desk_mode_live", WIRING)

    def test_the_task_is_on_the_beat_with_a_declared_cadence(self):
        from config.celery import app
        from dashboard.views_topology import WIRING
        tasks = {e.get("task") for e in app.conf.beat_schedule.values()}
        self.assertIn("bot_program.tasks.grade_capital_desk", tasks)
        # It runs on a crontab, which states when it next fires and not how
        # often, so the cadence must be declared or the map calls it STALE.
        self.assertTrue(WIRING["pipeline_capital_desk"]["cadence"])

    def test_the_three_skip_codes_are_in_the_closed_vocabulary(self):
        from bot_program.asset_engine import skips
        self.assertEqual(skips.DESK_DISPLACED, "desk_displaced")
        self.assertEqual(skips.BRAIN_PAUSED, "brain_paused")
        self.assertEqual(skips.ORDER_ERROR, "order_error")
        import inspect
        src = inspect.getsource(skips.diagnose)
        for code in ("DESK_DISPLACED", "BRAIN_PAUSED", "ORDER_ERROR"):
            self.assertIn(code, src,
                          f"{code} has no advice line in diagnose()")


class TheAuditHookTests(TestCase):

    def test_a_plan_writes_one_chained_row_and_the_kind_fits(self):
        from bot_program.audit import record_desk_plan
        from bot_program.audit_models import AuditLogEntry
        user = _user("grade_a")
        plan = _plan(user)
        record_desk_plan(plan, {"governor": 1.0})
        row = AuditLogEntry.objects.filter(kind="desk_plan").first()
        self.assertIsNotNone(row)
        self.assertLessEqual(
            len(row.kind),
            AuditLogEntry._meta.get_field("kind").max_length)
        self.assertEqual(row.data["plan_id"], plan.pk)
        self.assertEqual(row.data["governor"], 1.0)

    def test_the_hook_never_raises(self):
        """It is called from the entry path. A desk that cannot write its
        audit line still has a plan worth executing."""
        from bot_program.audit import record_desk_plan
        from bot_program.audit_models import AuditLogEntry
        before = AuditLogEntry.objects.count()
        record_desk_plan(object())        # no attributes at all
        # It swallowed the failure — and wrote NOTHING, rather than a
        # half-built row the chain would have to be trusted on.
        self.assertEqual(AuditLogEntry.objects.count(), before)
