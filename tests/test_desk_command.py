"""`python manage.py desk` — the /desk/ page as a command (2026-09-12).

An operator at a terminal must be able to ask the same four questions the
page answers, and one the page cannot: what would the desk say about THIS
config and THIS symbol right now. That last verb is the reason this file
pins more than exit codes:

  - `desk explain` is READ-ONLY BY CONSTRUCTION. It calls propose_entry with
    pricing='data' — the market-data session, never the exclusive trading
    client — and stops at the candidate. Nothing it does can send an order,
    and this suite proves the pricing argument rather than trusting it.
  - An unmeasured rule prints an em dash for its expected R, never 0.000.
    The command is where an operator checks a rule before promoting it, so
    a fabricated expectancy costs more here than anywhere else.
  - `desk grade` is the nightly pass on demand, and it says what it did.

Run with:  python manage.py test tests.test_desk_command
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone


def _config(user, **overrides):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        user=user, asset_class="stock", name="Desk Bot", enabled=True,
        mode="paper", symbols=["AAPL"], capital=Decimal("10000"),
        base_currency="USD", position_size_pct=2.0,
        max_concurrent_positions=5, max_daily_loss_pct=2.0,
        stop_loss_pct=1.5, take_profit_pct=3.0, entry_score_min=0.6,
        min_signals_for_entry=1, cool_down_minutes=0,
    )
    defaults.update(overrides)
    return AssetBotConfig.objects.create(**defaults)


def _candidate(bot, *, rule="desk_rule", score=0.8):
    from bot_program.asset_engine.candidates import EntryCandidate
    decision = SimpleNamespace(direction="BUY", score=score, reasons=[],
                               rule_name=rule)
    return EntryCandidate(
        bot=bot, cfg_id=bot.cfg.id, user_id=bot.cfg.user_id, symbol="AAPL",
        instrument_id=None, asset_class="stock", venue="paper",
        decision=decision, price=100.0, market_price=100.0, stop=95.0,
        target=115.0, level_meta={}, cost_reason="",
        stage={"force_paper": True, "stage": ""},
        sizing={"risk_fraction": 0.02, "risk_dollars": 50.0,
                "notional_fraction": 0.1, "stop_widened": False,
                "value_per_unit": 1.0},
        qty_default=10.0, per_unit_risk=5.0, risk_dollars_default=50.0,
        notional_default=1000.0, value_per_unit=1.0, horizon_hours=168.0)


def _run(*args, **opts):
    out = StringIO()
    call_command("desk", *args, stdout=out, **opts)
    return out.getvalue()


class DeskListAndShowTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("cmd_u", password="x")
        self.cfg = _config(self.user)

    def test_list_with_nothing_says_so_and_names_the_mode(self):
        text = _run("list")
        self.assertIn("no plans", text)
        self.assertIn("pipeline_capital_desk is off", text)

    def test_list_prints_a_row_per_plan_and_an_em_dash_for_an_ungraded_one(self):
        from bot_program.models import DeskPlan
        DeskPlan.objects.create(
            user=self.user, venue="paper", mode="shadow",
            budget=Decimal("100"), book_risk=Decimal("0"),
            new_risk_chosen=Decimal("40"), new_risk_marginal=Decimal("31"),
            n_candidates=3, n_chosen=2)
        text = _run("list")
        self.assertIn("EDGE R", text)
        self.assertIn("cmd_u", text)
        # The column carries the MARGINAL total, the unit the budget was
        # spent in; the raw risk-at-stop (40) belongs to `desk show`, which
        # has room to name both (2026-09-12).
        self.assertIn("MARGINAL", text)
        self.assertIn("31.00", text)
        self.assertIn("—", text)
        self.assertNotIn("0.000", text)

    def test_a_plan_from_before_the_marginal_column_prints_a_dash_not_a_zero(self):
        """new_risk_marginal is NULL on every plan written before the
        column existed. A 0.00 there would claim the desk committed
        nothing, which nobody measured (2026-09-12)."""
        from bot_program.models import DeskPlan
        DeskPlan.objects.create(
            user=self.user, venue="paper", mode="shadow",
            budget=Decimal("100"), book_risk=Decimal("0"),
            new_risk_chosen=Decimal("40"), n_candidates=3, n_chosen=2)
        text = _run("list")
        self.assertIn("—", text)
        self.assertNotIn("0.00 ", text)

    def test_show_prints_the_decisions_with_their_reasons(self):
        from bot_program.models import DeskDecision, DeskPlan
        plan = DeskPlan.objects.create(
            user=self.user, venue="paper", mode="shadow",
            budget=Decimal("72"), book_risk=Decimal("6"),
            new_risk_chosen=Decimal("41"), n_candidates=2, n_chosen=1,
            n_displaced=1)
        DeskDecision.objects.create(
            plan=plan, config=self.cfg, symbol="AAPL", direction="BUY",
            rule_name="desk_rule", lane="config_live", n=14, e_r=0.31,
            rank_key=0.31, measured=True, marginal_risk=Decimal("12"),
            rank=1, outcome="chosen", reason="taken at full size",
            price=Decimal("100"), stop=Decimal("95"), target=Decimal("115"))
        DeskDecision.objects.create(
            plan=plan, config=self.cfg, symbol="MSFT", direction="BUY",
            rule_name="desk_rule", lane="unmeasured", n=0, rank_key=0.4,
            measured=False, marginal_risk=Decimal("16"), rank=2,
            outcome="displaced", reason="rule_share — over the cap",
            price=Decimal("100"), stop=Decimal("95"), target=Decimal("115"))
        text = _run("show", str(plan.pk))
        self.assertIn(f"plan #{plan.pk}", text)
        self.assertIn("taken at full size", text)
        self.assertIn("rule_share — over the cap", text)
        self.assertIn("+0.310", text)
        # The unmeasured decision must print an em dash for E[R], not 0.000.
        row = [ln for ln in text.splitlines() if "MSFT" in ln][0]
        self.assertIn("—", row)
        self.assertNotIn("0.000", row)

    def test_show_without_a_plan_is_an_error_not_a_traceback(self):
        with self.assertRaises(CommandError):
            _run("show")

    def test_grade_runs_both_passes_and_says_what_it_did(self):
        with patch("bot_program.capital_desk.resolve_counterfactuals",
                   return_value=4) as res, \
                patch("bot_program.capital_desk.grade_plans",
                      return_value=1) as grade:
            text = _run("grade")
        self.assertTrue(res.called and grade.called)
        self.assertIn("resolved 4", text)
        self.assertIn("graded 1", text)


class DeskExplainTests(TestCase):
    """The one verb that touches the entry path — read-only by construction."""

    def setUp(self):
        self.user = User.objects.create_user("cmd_e", password="x")
        self.cfg = _config(self.user)

    def test_explain_reads_through_the_data_session_and_sends_nothing(self):
        from bot_program.asset_engine import StockBot
        bot = StockBot(self.cfg)
        cand = _candidate(bot)
        with patch("bot_program.asset_engine.base.make_bot", return_value=bot), \
                patch.object(bot, "propose_entry",
                             return_value=cand) as propose, \
                patch.object(bot, "execute_entry") as execute:
            text = _run("explain", str(self.cfg.pk), "aapl")
        propose.assert_called_once()
        self.assertEqual(propose.call_args.kwargs.get("pricing"), "data",
                         "explain must read the ticker through the market-"
                         "data session, never the exclusive trade client")
        self.assertFalse(execute.called, "explain must never send an order")
        self.assertIn("Nothing was sent", text)
        self.assertIn("AAPL BUY", text)
        self.assertIn("desk_rule", text)

    def test_an_unmeasured_rule_prints_an_em_dash_for_its_expected_r(self):
        from bot_program.asset_engine import StockBot
        bot = StockBot(self.cfg)
        cand = _candidate(bot, rule="a_brand_new_rule")
        with patch("bot_program.asset_engine.base.make_bot", return_value=bot), \
                patch.object(bot, "propose_entry", return_value=cand):
            text = _run("explain", str(self.cfg.pk), "AAPL")
        self.assertIn("expected R  — (unmeasured)", text)
        self.assertIn("under the", text)      # the floor is named in the why
        self.assertNotIn("expected R  +0.000", text)

    def test_a_measured_rule_states_its_lane_and_its_n(self):
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        for _ in range(12):
            AssetBotTrade.objects.create(
                config=self.cfg, asset_class="stock", symbol="HIST",
                side="BUY", qty=Decimal("1"), entry_price=Decimal("100"),
                status="CLOSED", outcome="hit_target", realized_r=0.5,
                rule_name="desk_rule", paper=False,
                closed_at=timezone.now() - timedelta(days=2))
        bot = StockBot(self.cfg)
        cand = _candidate(bot)
        with patch("bot_program.asset_engine.base.make_bot", return_value=bot), \
                patch.object(bot, "propose_entry", return_value=cand):
            text = _run("explain", str(self.cfg.pk), "AAPL")
        self.assertIn("config_live", text)
        self.assertIn("n=12", text)
        self.assertIn("+0.500", text)

    def test_nothing_to_propose_prints_the_skip_that_explains_it(self):
        from bot_program.asset_engine import StockBot
        from bot_program.asset_engine import skips
        bot = StockBot(self.cfg)
        skips.record(self.cfg, "AAPL", skips.NO_SIGNALS, "nothing fresh")
        with patch("bot_program.asset_engine.base.make_bot", return_value=bot), \
                patch.object(bot, "propose_entry", return_value=None):
            text = _run("explain", str(self.cfg.pk), "AAPL")
        self.assertIn("would propose nothing", text)
        self.assertIn("no_signals", text)

    def test_the_options_lane_says_it_is_not_desked(self):
        from bot_program.asset_engine import StockBot
        bot = StockBot(self.cfg)
        bot.DESKED = False
        with patch("bot_program.asset_engine.base.make_bot", return_value=bot):
            text = _run("explain", str(self.cfg.pk), "AAPL")
        self.assertIn("never", text)
        self.assertIn("options", text)

    def test_a_missing_config_is_an_error_not_a_traceback(self):
        with self.assertRaises(CommandError):
            _run("explain", "999999", "AAPL")

    def test_explain_needs_both_arguments(self):
        with self.assertRaises(CommandError):
            _run("explain", str(self.cfg.pk))


class TheCatalogueTests(TestCase):
    """core.ops_commands is the one place the catalogue lives; /ops/ and
    `manage.py ops` both render it, so a command missing from it is a
    command nobody can discover."""

    def test_the_desk_command_is_registered_and_mirrors_its_page(self):
        from core import ops_commands
        entry = ops_commands.get("desk")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["mirrors"], "/desk/")
        self.assertEqual(entry["category"], "decide")
        # `desk grade` writes the counterfactuals and the plan scores, so it
        # is not a read-only entry and the page's Run lane may not fire it.
        self.assertFalse(entry["read_only"])
        self.assertNotIn("desk", ops_commands.runnable_names())

    def test_every_usage_line_is_the_command_s_own_docstring(self):
        import ast
        import os

        from django.conf import settings
        from core import ops_commands
        path = os.path.join(settings.BASE_DIR, "bot_program", "management",
                            "commands", "desk.py")
        doc = ast.get_docstring(ast.parse(
            open(path, encoding="utf-8").read())) or ""
        for line in ops_commands.get("desk")["usage"]:
            self.assertIn(line, doc)


class TheRunbookTests(TestCase):

    def test_the_runbook_section_names_the_bar_for_going_live(self):
        import os

        from django.conf import settings
        path = os.path.join(os.path.dirname(settings.BASE_DIR), "deploy",
                            "RUNBOOK.md")
        if not os.path.exists(path):
            path = os.path.join(settings.BASE_DIR, "deploy", "RUNBOOK.md")
        text = open(path, encoding="utf-8").read()
        self.assertIn("The capital desk", text)
        self.assertIn("pipeline_capital_desk", text)
        self.assertIn("capital_desk_mode_live", text)
        # The four things an operator must know before touching the switch.
        self.assertIn("marginal risk", text.lower())
        self.assertIn("fails open", text.lower())
        self.assertIn("enabled", text)
        self.assertIn("shadow", text.lower())
