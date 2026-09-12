"""The capital desk's page — /desk/ (Stage 3, 2026-09-12).

The operator asked for this page in these words: "a graphical interface and a
page that illustrates the capital desk, giving perfect understanding and
vision of what Sauron is doing". So what is pinned here is not that the view
returns 200 — it is that the page EXPLAINS:

  - the sentence at the top names the real counts off the real plan, in four
    states (component off, on with no plan, shadow with a plan, live with a
    plan), and never invents one;
  - an unmeasured candidate wears the badge and shows NO expected R, because
    a 0.00 in the same column as a measured edge is the exact lie this
    platform's UI-honesty rule exists to prevent;
  - a non-staff viewer does not receive the platform-wide zone, the rule
    /ops/ and /health/ already follow;
  - no template tag reaches for a JavaScript asset: the bars are div widths
    and the sparkline is inline SVG, both computed in the view, so a page
    about risk still renders when the network is what is broken.

Run with:  python manage.py test tests.test_desk_page
"""
import re
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _component(key, enabled=True):
    from core.platform_control import PlatformComponent
    return PlatformComponent.objects.create(
        key=key, name=key, description="", category="pipeline",
        is_enabled=enabled)


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


def _plan(user, **overrides):
    from bot_program.models import DeskPlan
    defaults = dict(user=user, venue="live", mode="shadow",
                    budget=Decimal("78.00"), book_risk=Decimal("0.00"),
                    new_risk_chosen=Decimal("41.00"),
                    # The MARGINAL total the chooser actually spent — a
                    # different quantity from the raw risk-at-stop above, and
                    # the one the budget was consumed in.
                    new_risk_marginal=Decimal("30.00"), n_candidates=9,
                    n_chosen=3, n_resized=0, n_displaced=6, n_duplicate=0,
                    matrix_pairs_measured=4, matrix_pairs_total=10)
    defaults.update(overrides)
    return DeskPlan.objects.create(**defaults)


def _decision(plan, cfg, **overrides):
    from bot_program.models import DeskDecision
    defaults = dict(plan=plan, config=cfg, symbol="AAPL", direction="BUY",
                    rule_name="desk_rule", lane="config_live", n=14,
                    e_r=0.31, p_win=0.55, rank_key=0.31, measured=True,
                    decaying=False, risk_dollars_default=Decimal("20.00"),
                    marginal_risk=Decimal("12.00"), corr_max=0.2, rank=1,
                    outcome="chosen", reason="taken at full size — adds 12.00",
                    size_mult=1.0, qty_default=Decimal("4"),
                    price=Decimal("100"), stop=Decimal("95"),
                    target=Decimal("115"), horizon_hours=168.0)
    defaults.update(overrides)
    return DeskDecision.objects.create(**defaults)


class DeskPageStatesTests(TestCase):
    """Four states, four honest pages."""

    def setUp(self):
        self.user = User.objects.create_user("desk_page", password="x",
                                             is_staff=True)
        self.cfg = _config(self.user, mode="live")
        self.client.force_login(self.user)

    def test_the_component_being_off_is_a_sentence_naming_the_command(self):
        resp = self.client.get("/desk/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("The desk has not run — pipeline_capital_desk is OFF",
                      html)
        self.assertIn("component on pipeline_capital_desk", html)

    def test_on_with_no_plan_says_nothing_cleared_rather_than_off(self):
        _component("pipeline_capital_desk", True)
        resp = self.client.get("/desk/")
        html = resp.content.decode()
        self.assertIn("No candidate cleared the gates on the last tick", html)
        self.assertNotIn("The desk has not run", html)

    def test_the_top_sentence_names_the_real_counts_from_the_plan(self):
        _component("pipeline_capital_desk", True)
        plan = _plan(self.user)
        _decision(plan, self.cfg)
        _decision(plan, self.cfg, symbol="MSFT", rank=2, outcome="displaced",
                  reason=("rule_share — desk_rule would hold 55% of the "
                          "tick's risk (cap 40%)"))
        html = self.client.get("/desk/").content.decode()
        # The counts are the PLAN's, not the rows' — the plan is what was
        # decided, and a page that recounted would disagree with the audit.
        self.assertIn("saw nine candidates", html)
        self.assertIn("kept three", html)
        self.assertIn("30 of the 78 USD of MARGINAL risk", html)
        self.assertIn("it displaced one", html)
        self.assertIn("one rule already held its share", html)

    def test_the_bar_and_the_sentence_spend_the_marginal_number(self):
        """REGRESSION (adversarial review, 2026-09-12): the chooser spends
        the budget in MARGINAL risk — the correlation-aware increment each
        pick adds — and the page drew `new_risk_chosen`, the raw sum of
        risk-at-stop, against it. Two units under one heading: the bar could
        read 41 of 78 spent on a tick the desk had stopped at the budget's
        edge with 30. Both numbers are on the page now, each labelled so
        neither can be read as the other."""
        _component("pipeline_capital_desk", True)
        plan = _plan(self.user)
        _decision(plan, self.cfg)
        html = self.client.get("/desk/").content.decode()
        # the sentence
        self.assertIn("30 of the 78 USD of MARGINAL risk", html)
        self.assertIn("RAW risk at stop on the same entries is 41 USD", html)
        # the budget bar
        self.assertIn("MARGINAL RISK this plan adds (the unit the budget was "
                      "spent in): 30.00 USD", html)
        self.assertIn("RAW RISK AT STOP on the same entries (what the account "
                      "loses if every one of those stops is hit): 41.00 USD",
                      html)
        # the record table, where the same two quantities get their own
        # columns rather than one "Budget used" heading over the wrong one
        self.assertIn("Marginal used / budget", html)
        self.assertIn("Raw risk at stop", html)

    def test_a_plan_with_no_marginal_total_renders_without_inventing_one(self):
        """A plan written before the column existed has NULL there. The page
        must render, must say the marginal total was never recorded, and must
        NOT put the raw risk-at-stop in its place — the em-dash rule every
        other unmeasured quantity on this page already follows."""
        _component("pipeline_capital_desk", True)
        plan = _plan(self.user, new_risk_marginal=None)
        _decision(plan, self.cfg)
        resp = self.client.get("/desk/")
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn("a MARGINAL total this plan did not record", html)
        self.assertIn("RAW risk at stop on those entries was 41 USD", html)
        self.assertNotIn("41 of the 78 USD of MARGINAL risk", html)
        self.assertNotIn("30 of the 78 USD of MARGINAL risk", html)
        self.assertIn(f"Plan #{plan.pk} recorded no marginal total", html)
        self.assertIn("MARGINAL RISK this plan adds (the unit the budget was "
                      "spent in): —", html)

    def test_shadow_shows_the_counterfactual_and_live_shows_what_applied(self):
        _component("pipeline_capital_desk", True)
        plan = _plan(self.user)
        _decision(plan, self.cfg)
        html = self.client.get("/desk/").content.decode()
        self.assertIn("in shadow nothing was changed", html.lower())
        self.assertIn("THE DESK WOULD HAVE", html)

        _component("capital_desk_mode_live", True)
        from bot_program.models import DeskPlan
        DeskPlan.objects.filter(pk=plan.pk).update(mode="live")
        html = self.client.get("/desk/").content.decode()
        self.assertIn("Applied:", html)
        self.assertIn("0 resized, 6 displaced", html)

    def test_a_failed_plan_says_the_fleet_ran_undesked(self):
        _component("pipeline_capital_desk", True)
        _plan(self.user, error="matrix blew up")
        html = self.client.get("/desk/").content.decode()
        self.assertIn("FAILED", html)
        self.assertIn("ran undesked", html)
        self.assertIn("matrix blew up", html)


class UnmeasuredIsNeverDressedAsMeasuredTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("desk_unm", password="x")
        self.cfg = _config(self.user)
        self.client.force_login(self.user)
        _component("pipeline_capital_desk", True)

    def test_an_unmeasured_candidate_shows_a_badge_and_no_expected_r(self):
        plan = _plan(self.user, venue="paper")
        _decision(plan, self.cfg, lane="unmeasured", measured=False, n=0,
                  e_r=None, p_win=None, rank_key=0.44,
                  reason="taken at full size — adds 12.00")
        html = self.client.get("/desk/").content.decode()
        self.assertIn(">unmeasured<", html)
        self.assertIn("ranked on conviction only", html)
        # The measured label ("+0.31R · n=14 · This config, live") must not
        # appear at all: a fabricated 0.00R beside a real edge is the exact
        # failure tests/test_ui_honesty.py exists to prevent.
        self.assertNotIn("R · n=", html)
        self.assertNotIn("This config, live", html)

    def test_a_measured_candidate_states_its_lane_and_its_n(self):
        plan = _plan(self.user, venue="paper")
        _decision(plan, self.cfg)
        html = self.client.get("/desk/").content.decode()
        self.assertIn("+0.31R over 14 graded fills", html)
        self.assertIn("This config, live", html)

    def test_an_ungraded_plan_renders_an_em_dash_for_its_edge(self):
        plan = _plan(self.user, venue="paper")
        _decision(plan, self.cfg)
        html = self.client.get("/desk/").content.decode()
        self.assertIn("no plan graded yet", html)
        self.assertNotIn("+0.000", html)

    def test_a_graded_plan_shows_its_edge_and_the_sparkline_needs_two(self):
        now = timezone.now()
        for i, edge in enumerate((0.4, -0.2, 0.9)):
            p = _plan(self.user, venue="paper", edge_r=edge, graded_at=now,
                      edge_detail={"n_graded": 2, "n_ungradeable": 0})
            _decision(p, self.cfg, rank=i + 1)
        html = self.client.get("/desk/").content.decode()
        self.assertIn("<polyline", html)
        self.assertIn("edge R across 3 graded plans", html)
        self.assertIn("+1.10", html)      # 0.4 - 0.2 + 0.9 over 7 days


class PlatformZoneIsStaffOnlyTests(TestCase):
    """/ops/'s own rule: the per-user plan is for anyone who owns it, the
    switch states and the beat's error text are staff's."""

    def setUp(self):
        _component("pipeline_capital_desk", True)
        self.viewer = User.objects.create_user("desk_viewer", password="x")
        self.staff = User.objects.create_user("desk_staff", password="x",
                                              is_staff=True)

    def test_a_non_staff_viewer_does_not_receive_the_platform_wide_zone(self):
        self.client.force_login(self.viewer)
        html = self.client.get("/desk/").content.decode()
        self.assertIn("staff only — platform-wide", html)
        self.assertNotIn("component on capital_desk_mode_live", html)

    def test_staff_receive_the_switches(self):
        self.client.force_login(self.staff)
        html = self.client.get("/desk/").content.decode()
        self.assertNotIn("staff only — platform-wide", html)
        self.assertIn("component on capital_desk_mode_live", html)

    def test_login_is_required(self):
        self.assertEqual(self.client.get("/desk/").status_code, 302)


class NoJavascriptTests(TestCase):
    """Server-rendered only: the bars are div widths and the sparkline is
    inline SVG, both computed in the view. A chart library on this page
    would be one more thing that can be missing on the day it matters."""

    def test_the_template_references_no_javascript_asset(self):
        from pathlib import Path

        from django.conf import settings
        tpl = (Path(settings.BASE_DIR) / "templates" / "dashboard"
               / "desk.html").read_text(encoding="utf-8")
        self.assertNotIn("<script", tpl.lower())
        self.assertFalse(re.search(r"\.js\b", tpl),
                         "the desk page must ship no JavaScript asset")
        self.assertNotIn("cdn", tpl.lower())
        self.assertIn("<svg", tpl)
        self.assertIn("<polyline", tpl)

    def test_the_page_is_in_the_rail_with_a_mark_of_its_own(self):
        from pathlib import Path

        from django.conf import settings
        base = (Path(settings.BASE_DIR) / "templates" / "base.html"
                ).read_text(encoding="utf-8")
        self.assertIn("desk_dashboard", base)
        self.assertIn("Capital Desk", base)
        # One mark, one meaning: the desk's glyph is used nowhere else.
        self.assertEqual(base.count("▩"), 1)
        # No data-nav-id: the activity-dot payload and the rail must stay
        # the same seven sections (tests/test_nothing_unseen.py).
        row = base[base.index("desk_dashboard") - 200:
                   base.index("desk_dashboard") + 200]
        self.assertNotIn("data-nav-id", row)
