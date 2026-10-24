"""NO ACCOUNT FIGURE REACHES A NON-STAFF READER THROUGH THE AI (2026-10-24).

The platform's rule: no account money figure (a book's value, its cash, a
P&L in money) reaches a reader who is not staff. The AI outputs below go
to every login, or did through the API:

  * the morning briefing: its text goes to the bell of every active user,
    and the AI was handed the lowest-id book's value and cash and the
    strategies' P&L in money;
  * the Monday plan: the bell of every active user and /briefing/; it was
    handed the same, plus the snapshot's total and its exposure in money;
  * the weekly review, which becomes the newsletter: every snapshot's
    total, cash, daily P&L and exposure in money, and a sizing note that
    quoted the pools and the book;
  * the strategy advisor (the hourly review and the Saturday optimization),
    whose answer /ai/ and /api/ai/briefing/ show every login: the book's
    value and cash and each open position's size and P&L in money;
  * the trade journal: a closed position's P&L in money, its answer kept
    on the AI ledger;
  * the next steps read of the end-of-day digest, whose steps any login
    sees on /briefing/: the book sections of the digest, in money;
  * the same read from the shell (`next_steps read eod_digest`);
  * the Monday plan also read the newest weekly review of any age, so a
    review written from money before this fix came back every week;
  * the brain's snapshot sent a legacy position's P&L in money, labelled
    R; its narrative reaches the strategist briefing and /brain/;
  * /api/ai/tasks/ served every login the whole AI ledger (prompt, answer,
    structured output) of every agent, the staff-only ones included, and
    /api/ai/briefing/ the strategy advisor's whole answer; the page
    /ai/tasks/ showed every agent's answer in its Summary column.

Each prompt now carries percentages and R where it needs the account at
all, both API views are staff-only, and /ai/tasks/ shows the answers to
staff only.

Run with:  python manage.py test tests.test_no_account_figures_broadcast
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

#: Every account figure seeded below, as a prompt could print it.
FIGURES = ("98765", "98,765", "12345", "12,345", "4321", "4,321",
           "87654", "87,654", "23456", "23,456", "3456", "3,456",
           "6543", "6,543", "6542", "6,542", "55555", "55,555", "44444",
           "44,444")


class _Provider:
    def __init__(self, text):
        self.text = text
        self.seen = []

    def complete(self, **kw):
        self.seen.append(kw)
        return self.text, {"input_tokens": 100, "output_tokens": 200,
                           "cost_usd": 0.01}


def _ok():
    return mock.MagicMock(ok=True, status_code=200, text='{"ok":true}')


def _book():
    """The lowest-id book (Portfolio.objects.first()) with figures that
    must never reach a prompt, an open position and a strategy."""
    from instruments.models import Instrument
    from portfolio.models import Portfolio, PortfolioSnapshot, Position
    from strategies.models import Strategy
    book = Portfolio.objects.create(
        name="Main", initial_capital=Decimal("90000"),
        current_value=Decimal("98765.43"),
        cash_available=Decimal("12345.67"), currency="EUR")
    Portfolio.objects.update(current_value=Decimal("98765.43"),
                             cash_available=Decimal("12345.67"))
    first = Portfolio.objects.first()
    strategy = Strategy.objects.create(
        name="Momentum", description="d", time_horizon="swing",
        status="active", pnl=Decimal("4321.09"), pnl_pct=4.2,
        max_drawdown=-2.5)
    inst = Instrument.objects.create(symbol="ACF1", name="ACF1",
                                     asset_class="stock")
    Position.objects.create(
        portfolio=first, instrument=inst, strategy=strategy,
        direction="long", quantity=Decimal("777"),
        entry_price=Decimal("10"), current_price=Decimal("18.42"),
        unrealized_pnl=Decimal("6543.21"), unrealized_pnl_pct=84.2,
        opened_at=timezone.now() - timedelta(days=2))
    PortfolioSnapshot.objects.create(
        portfolio=first, date=timezone.now().date() - timedelta(days=1),
        total_value=Decimal("87654.32"), cash=Decimal("23456.78"),
        daily_pnl=Decimal("3456.12"), daily_pnl_pct=1.2,
        cumulative_pnl_pct=9.7, max_drawdown=-3.1,
        exposure_by_asset_class={"stock": 55555.55, "forex": 44444.45},
        exposure_by_sector={"tech": 55555.55, "unknown": 44444.45})
    return book, strategy, inst


def _eod_digest():
    """An end-of-day digest whose book sections carry FIGURES."""
    return {
        "type": "end_of_day",
        "summary": ["Open positions: 2 (1 simulated · 1 real money)"],
        "sections": {
            "real_money": {"lines": ["Equity: 98,765.43 EUR",
                                     "Cash: 12,345.67 EUR"]},
            "simulated": {"lines": ["Book value: 87,654.32 EUR, cash "
                                    "23,456.78 EUR"]},
            "daily_pnl": {"pnl": 3456.12,
                          "lines": ["P&L: +3,456.12 EUR (+1.20%)"]},
            "trades": {"lines": ["• Closed ACF1 Buy · +6,543.21 USD · "
                                 "+1.50R · Real money"]},
            "strategies": [{"name": "Momentum", "pnl_pct": 4.2,
                            "status": "active"}]}}


class _Case(TestCase):

    def assertNoFigure(self, text):
        for figure in FIGURES:
            self.assertNotIn(figure, text, f"{figure!r} in {text[:3000]!r}")


class TheBroadcastPromptsCarryNoAccountMoneyTests(_Case):

    def setUp(self):
        self.book, self.strategy, self.inst = _book()

    def test_the_morning_briefing_carries_no_value_cash_or_pnl(self):
        from ai_agents.models import AgentTask
        from ai_agents.tasks import DailyBriefingAgent, generate_daily_briefing
        provider = _Provider("Market Overview: quiet.")
        with mock.patch.object(DailyBriefingAgent, "_get_provider",
                               lambda self, name: provider):
            generate_daily_briefing.__wrapped__.__wrapped__()
        prompt = provider.seen[0]["user_message"]
        self.assertNoFigure(prompt)
        self.assertNotIn("current_value", prompt)
        self.assertNotIn("cash_available", prompt)
        # The strategies stay, in percent.
        self.assertIn('"name": "Momentum"', prompt)
        self.assertIn('"pnl_pct": 4.2', prompt)
        self.assertNoFigure(AgentTask.objects.get(
            agent="daily_briefing").prompt_summary)

    def test_the_monday_plan_carries_percentages_only(self):
        from ai_agents.tasks import MondayPlanAgent, generate_monday_plan
        provider = _Provider("## Plan\nHold.")
        with mock.patch.object(MondayPlanAgent, "_get_provider",
                               lambda self, name: provider), \
                mock.patch("requests.post", return_value=_ok()):
            generate_monday_plan.__wrapped__.__wrapped__()
        prompt = provider.seen[0]["user_message"]
        self.assertNoFigure(prompt)
        self.assertIn('"cumulative_pnl_pct": 9.7', prompt)
        self.assertIn('"max_daily_loss_pct"', prompt)
        # The exposure as shares of the whole, in percent.
        self.assertIn('"stock": 55.6', prompt)
        self.assertIn('"forex": 44.4', prompt)

    def test_the_weekly_review_that_becomes_the_newsletter(self):
        from ai_agents.agents.weekly_reviewer import WeeklyReviewerAgent
        from ai_agents.tasks import generate_weekly_review
        from alerts.models import Newsletter
        provider = _Provider("# Market Overview\nQuiet week.")
        with mock.patch.object(WeeklyReviewerAgent, "_get_provider",
                               lambda self: provider), \
                mock.patch("requests.post", return_value=_ok()):
            result = generate_weekly_review.__wrapped__.__wrapped__()
        prompt = provider.seen[0]["user_message"]
        self.assertNoFigure(prompt)
        self.assertIn('"daily_pnl_pct": 1.2', prompt)
        self.assertIn('"stock": 55.6', prompt)
        self.assertNoFigure(Newsletter.objects.get(
            pk=result["newsletter_id"]).ai_prompt)

    def test_the_sizing_note_is_a_ratio_never_the_money(self):
        from ai_agents.tasks import _sizing_notes
        from bot_program.models import AssetBotConfig
        from portfolio.services import get_or_create_default_portfolio
        user = User.objects.create(username="acf_note")
        own = get_or_create_default_portfolio(user=user)
        own.current_value = Decimal("273.07")
        own.cash_available = Decimal("500")
        own.save()
        AssetBotConfig.objects.create(
            user=user, name="manual", asset_class="stock", mode="paper",
            enabled=True, symbols=[], capital=Decimal("10000"))
        note = _sizing_notes({own.name})[own.name]
        self.assertIn("Sized by 1 paper pool totalling 20.0 times the book",
                      note)
        for figure in ("10,000", "10000", "500", "273"):
            self.assertNotIn(figure, note)

    def test_the_strategy_advisor_sees_no_value_cash_size_or_pnl(self):
        from ai_agents.agents.strategy_advisor import StrategyAdvisorAgent
        from ai_agents.tasks import optimize_strategies, review_active_strategies
        for task in (review_active_strategies, optimize_strategies):
            provider = _Provider('{"strategies": []}')
            with self.subTest(task.name), \
                    mock.patch.object(StrategyAdvisorAgent, "_get_provider",
                                      lambda self: provider):
                task.__wrapped__.__wrapped__()
            prompt = provider.seen[0]["user_message"]
            self.assertNoFigure(prompt)
            self.assertNotIn('"quantity"', prompt)
            self.assertIn('"unrealized_pnl_pct": 84.2', prompt)

    def test_the_trade_journal_reads_the_pnl_in_percent(self):
        from ai_agents.trade_journal import TradeJournalAgent, generate_journal_entry
        from portfolio.models import Position
        pos = Position.objects.get(instrument=self.inst)
        pos.closed_at = timezone.now().replace(microsecond=0)
        pos.opened_at = pos.closed_at - timedelta(days=2)
        pos.save()
        provider = _Provider('{"grade": "B"}')
        with mock.patch.object(TradeJournalAgent, "_get_provider",
                               lambda self: provider):
            generate_journal_entry(pos)
        prompt = provider.seen[0]["user_message"]
        self.assertNoFigure(prompt)
        self.assertIn("P&L: 84.20%", prompt)

    def test_the_end_of_day_next_steps_read_no_book_section(self):
        from alerts.tasks import send_eod_digest
        User.objects.all().delete()
        with mock.patch("alerts.scheduled_digests.generate_eod_digest",
                        return_value=_eod_digest()), \
                mock.patch("ai_agents.next_steps.extract") as extract:
            send_eod_digest.__wrapped__.__wrapped__()
        report_kind, text = extract.call_args.args
        self.assertEqual(report_kind, "eod_digest")
        self.assertNoFigure(text)
        self.assertIn("Momentum", text)
        self.assertIn("Open positions: 2", text)

    def test_the_manual_next_steps_read_has_no_book_section_either(self):
        """`next_steps read eod_digest` (the shell) reads the digest as the
        Celery path does: its steps reach the same page."""
        from django.core.management import call_command
        with mock.patch("alerts.scheduled_digests.generate_eod_digest",
                        return_value=_eod_digest()), \
                mock.patch("ai_agents.next_steps.extract",
                           return_value=[]) as extract:
            call_command("next_steps", "read", "eod_digest",
                         stdout=mock.MagicMock())
        report_kind, text = extract.call_args.args
        self.assertEqual(report_kind, "eod_digest")
        self.assertNoFigure(text)
        self.assertIn("Momentum", text)
        self.assertIn("Open positions: 2", text)

    def test_the_monday_plan_never_reads_a_stale_review(self):
        """A review written from money before this fix is not fed back to
        the plan (every user's bell) week after week; a review of the last
        eight days still is."""
        from alerts.models import Newsletter
        from ai_agents.tasks import MondayPlanAgent, generate_monday_plan
        stale = Newsletter.objects.create(
            title="Old review", frequency="weekly", status="sent",
            origin="weekly_review",
            content_markdown="The book ended the week at 98,765.43 EUR "
                             "with 12,345.67 cash.")
        Newsletter.objects.filter(pk=stale.pk).update(
            created_at=timezone.now() - timedelta(days=9))

        def plan_prompt():
            provider = _Provider("## Plan\nHold.")
            with mock.patch.object(MondayPlanAgent, "_get_provider",
                                   lambda self, name: provider), \
                    mock.patch("requests.post", return_value=_ok()):
                generate_monday_plan.__wrapped__.__wrapped__()
            return provider.seen[0]["user_message"]

        prompt = plan_prompt()
        self.assertNoFigure(prompt)
        self.assertIn("No previous weekly review available.", prompt)
        Newsletter.objects.create(
            title="This week", frequency="weekly", status="ai_generated",
            origin="weekly_review", content_markdown="RECENT REVIEW: +1.5R.")
        self.assertIn("RECENT REVIEW: +1.5R.", plan_prompt())

    def test_the_brain_reads_a_legacy_position_in_percent(self):
        """The legacy row's unrealized_pnl is money; it rode the snapshot
        as "unrealized_r" into the brain, whose narrative the strategist
        briefing and /brain/ show."""
        import json

        from brain.synthesizer import SauronMindAgent, _build_world_snapshot
        snap = _build_world_snapshot()
        (row,) = [p for p in snap["open_positions"]
                  if p["book"] == "portfolio"]
        self.assertNotIn("unrealized_r", row)
        self.assertEqual(row["unrealized_pnl_pct"], 84.2)
        self.assertNoFigure(json.dumps(snap, default=str))
        self.assertNoFigure(SauronMindAgent().build_context(snapshot=snap))


class TheAILedgerAPIIsStaffOnlyTests(_Case):

    def setUp(self):
        from ai_agents.models import AgentTask
        AgentTask.objects.create(
            agent="position_review", provider="claude", model="m",
            prompt_summary="Equity 98765.43 EUR, cash 12345.67 EUR",
            response_summary="Hold: the book is 98765.43 EUR.",
            structured_output={"note": "equity 98765.43"})
        AgentTask.objects.create(
            agent="strategy_advisor", provider="claude", model="m",
            prompt_summary="CURRENT PORTFOLIO: 98765.43",
            response_summary="{}",
            structured_output={"portfolio_notes": "cash 12345.67"})
        # The staff-only agents that answer from money: the close advisor
        # (P&L, committed and freed capital) and the trade debate (risk
        # at the stop).
        AgentTask.objects.create(
            agent="close_advisor", provider="claude", model="m",
            response_summary="Closing frees 98765.43 EUR of capital.")
        AgentTask.objects.create(
            agent="debate_executioner", provider="claude", model="m",
            response_summary="VETO: risking 6,543.21 of real money on this")
        self.reader = User.objects.create(username="acf_reader")
        self.staff = User.objects.create(username="acf_staff", is_staff=True)

    def test_a_non_staff_login_reads_no_ledger_row(self):
        self.client.force_login(self.reader)
        for path in ("/api/ai/tasks/", "/api/ai/briefing/"):
            with self.subTest(path):
                resp = self.client.get(path)
                self.assertEqual(resp.status_code, 403)
                self.assertNoFigure(resp.content.decode())

    def test_staff_still_read_the_ledger(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/api/ai/tasks/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("98765.43", resp.content.decode())
        resp = self.client.get("/api/ai/briefing/")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"portfolio_notes": "cash 12345.67"})

    def test_the_ledger_page_shows_no_answer_to_a_non_staff_login(self):
        """/ai/tasks/ (the page) shows the same rows as /api/ai/tasks/:
        a login that is not staff reads the counts, costs and times, never
        an answer."""
        self.client.force_login(self.reader)
        resp = self.client.get("/ai/tasks/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # The figures these rows carry (the page's own script holds
        # "0123456789abcdef", so FIGURES' "12345" cannot be looked for).
        for figure in ("98765", "98,765", "6543", "6,543"):
            self.assertNotIn(figure, body)
        self.assertNotIn("Closing frees", body)
        self.assertNotIn("VETO", body)
        self.assertIn("close_advisor", body)
        self.assertIn("debate_executioner", body)

    def test_staff_read_the_answers_on_the_ledger_page(self):
        self.client.force_login(self.staff)
        body = self.client.get("/ai/tasks/").content.decode()
        self.assertIn("Closing frees 98765.43 EUR of capital.", body)
        self.assertIn("6,543.21", body)
