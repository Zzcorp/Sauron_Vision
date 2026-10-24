"""NO ACCOUNT FIGURE REACHES A NON-STAFF READER THROUGH A PAGE (2026-10-24).

PR72 took account money out of the AI's prompts and made the AI ledger
staff-only (tests/test_no_account_figures_broadcast.py). The prose those
agents had already written, and one prompt, stayed open to every login
that is not an investor:

  * /ai/ printed the newest weekly review or strategy advisor answer;
  * /brain/ printed the Mind's narrative, every concern's text and, on a
    failed synthesis, up to 200 characters of the model's raw answer; the
    concern text again on the /command/ live tab and on /research/;
  * the research chat was handed six narratives and the latest outlook,
    so any login could ask it for what the pages hide;
  * the Mind itself was handed every closed trade's P&L and size, every
    open's size and broker order id, and every shadow entry's size;
  * a sent letter is open to any login, and the letters written before
    PR72 carried money.

Staff see everything as before. Everyone else sees the regime, the health,
the kinds, the severities and the levers, and a dash for the prose.

Run with:  python manage.py test tests.test_no_account_figures_pages
"""
import json
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import Client
from django.utils import timezone

from tests.test_no_account_figures_broadcast import FIGURES, _Case

MONEY = "a P&L of +4,321.09 EUR on 98,765 units"
#: The figures MONEY carries, as a page could print them. A whole page is
#: checked for these, not for every FIGURES token: a page's own markup
#: carries digits a prompt never would.
PAGE_FIGURES = ("4,321.09", "4321.09", "4,321", "98,765", "98765")


class _PageCase(_Case):

    def assertNoMoney(self, body):
        for figure in PAGE_FIGURES:
            self.assertNotIn(figure, body, figure)


def _plain(name="nf_plain"):
    return User.objects.create_user(username=name, password="x")


def _staff(name="nf_staff"):
    return User.objects.create_user(username=name, password="x",
                                    is_staff=True)


def _client_for(user):
    c = Client()
    c.force_login(user)
    return c


def _report(**kw):
    from brain.models import BrainReport
    fields = dict(regime_label="trending", regime_confidence=0.7,
                  portfolio_health_score=0.6,
                  narrative_md=f"The book booked {MONEY}.",
                  top_concerns=[{"kind": "theme_saturation", "severity": 0.8,
                                 "ref": "", "venue": "live",
                                 "text": f"Concentrated: {MONEY}."}])
    fields.update(kw)
    return BrainReport.objects.create(**fields)


class TheAICardTests(_PageCase):

    def test_the_ai_card_shows_the_briefing_to_staff_only(self):
        from ai_agents.models import AgentTask
        AgentTask.objects.create(
            agent="strategy_advisor", provider="anthropic", model="m",
            prompt_summary="p", response_summary=f"Advice: {MONEY}.",
            success=True)
        AgentTask.objects.create(
            agent="weekly_reviewer", provider="anthropic", model="m",
            prompt_summary="p", structured_output={"review": f"Week: {MONEY}."},
            success=True)
        body = _client_for(_plain()).get("/ai/").content.decode()
        self.assertNoMoney(body)
        self.assertIn("Latest AI briefing", body)
        self.assertIn("weekly_reviewer", body)
        self.assertIn("for staff", body)
        staff = _client_for(_staff()).get("/ai/").content.decode()
        self.assertIn("4,321.09", staff)


class TheMindsProseTests(_PageCase):

    def test_the_brain_page_shows_the_minds_prose_to_staff_only(self):
        _report()
        r = _client_for(_plain()).get("/brain/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertNoMoney(body)
        self.assertIn("TRENDING", body)
        self.assertIn("theme_saturation", body)
        staff = _client_for(_staff()).get("/brain/").content.decode()
        self.assertIn("4,321.09", staff)

    def test_a_failed_synthesis_shows_no_raw_answer_to_a_non_staff_login(self):
        """Critique M3(a): the error carries text[:200] of the model's
        answer (brain/synthesizer.py parse_response)."""
        _report(error=f"non-JSON brain output: no object: {MONEY}",
                narrative_md="")
        body = _client_for(_plain()).get("/brain/").content.decode()
        self.assertNoMoney(body)
        self.assertIn("Synthesis error", body)
        staff = _client_for(_staff()).get("/brain/").content.decode()
        self.assertIn("4,321.09", staff)

    def test_the_command_live_tab_and_research_show_concern_text_to_staff_only(self):
        _report()
        plain = _client_for(_plain())
        for path in ("/command/tab/live/", "/research/"):
            r = plain.get(path)
            self.assertEqual(r.status_code, 200, path)
            body = r.content.decode()
            self.assertNoMoney(body)
            self.assertIn("theme_saturation", body.lower().replace(
                "theme saturation", "theme_saturation"), path)
        staff = _client_for(_staff())
        for path in ("/command/tab/live/", "/research/"):
            self.assertIn("4,321.09", staff.get(path).content.decode(), path)


class TheResearchChatTests(_Case):
    """Critique M3(b): hiding the prose on /research/ is cosmetic while
    the chat beside it is handed the same prose."""

    def _ask(self, user):
        from brain.knowledge_models import Hypothesis  # noqa: F401
        from brain.briefing_models import StrategistBriefing
        from brain.research_agent import ask, get_or_create_active_conversation
        _report()
        StrategistBriefing.objects.create(
            posture="neutral", outlook_md=f"Outlook: {MONEY}.")
        seen = []
        usage = {"input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}

        def init(self, *a, **kw):
            self.agent_name = "research"
            self.provider_name = "stub"
            self.model = "stub"
            self.provider = MagicMock()

            def complete(**kw):
                seen.append(kw["user_message"])
                return '{"answer_md": "ok"}', usage
            self.provider.complete = complete
        with patch("brain.research_agent.ResearchAgent.__init__", init):
            ask(get_or_create_active_conversation(user), "What happened?")
        self.assertEqual(len(seen), 1)
        return seen[0]

    def test_a_non_staff_asker_is_handed_no_prose(self):
        context = self._ask(_plain())
        self.assertNoFigure(context)
        self.assertIn("trending", context)

    def test_a_staff_asker_is_handed_the_prose(self):
        """A guard: staff keep what they had."""
        context = self._ask(_staff())
        self.assertIn("4,321.09", context)


def _strategist_prose():
    """The strategist's and the Mind's prose with money in it: a briefing's
    watchlist and idea, the idea's hypothesis, a Mind hypothesis's notes,
    and one other agent's claim (open to every login on /hypotheses/)."""
    from brain.briefing_models import StrategistBriefing
    from brain.knowledge_models import Hypothesis
    StrategistBriefing.objects.create(
        posture="neutral", outlook_md="Steady.",
        watchlist=[{"kind": "rule", "ref": "nf_rule",
                    "what_to_watch": f"Hold {MONEY}."}],
        ideas=[{"summary": f"Trim the book: {MONEY}.", "symbol": "NFA1"}])
    Hypothesis.objects.create(
        claim_text=f"Trim the book: {MONEY}.", source_agent="strategist",
        confidence=0.6)
    Hypothesis.objects.create(
        claim_text="[regime_persistence] risk_off", source_agent="sauron_mind",
        confidence=0.6, outcome="refuted", resolved_at=timezone.now(),
        resolution_notes=f"measured on {MONEY}")
    Hypothesis.objects.create(
        claim_text="the critic doubts the regime call", source_agent="critic",
        confidence=0.5)


class TheResearchChatIsHandedNoStrategistProseTests(_Case):
    """Review F10: the chat's snapshot still carried the briefing's
    watchlist and ideas and the strategist's hypothesis claims, all written
    from the same snapshots as the narratives it already withheld."""

    def _snapshot(self, staff):
        from brain.research_agent import _build_research_snapshot
        _strategist_prose()
        return json.dumps(_build_research_snapshot(staff=staff), default=str)

    def test_a_non_staff_snapshot_carries_none_of_it(self):
        text = self._snapshot(staff=False)
        self.assertNoFigure(text)
        self.assertIn("nf_rule", text)           # the refs and kinds stay
        self.assertIn("NFA1", text)
        self.assertIn("the critic doubts the regime call", text)

    def test_a_staff_snapshot_keeps_it(self):
        """A guard: staff keep what they had."""
        text = self._snapshot(staff=True)
        self.assertIn("4,321.09", text)
        self.assertIn("what_to_watch", text)


class TheTelegramThreadGetsNoProseTests(_Case):
    """Review F17 (M3b as built): a Telegram thread is handed no narrative,
    concern text or outlook, though its owner is staff: its group can hold
    people who are not."""

    def _ask_telegram(self, channel):
        from brain.briefing_models import StrategistBriefing
        from brain.research_agent import (TELEGRAM_THREAD_PREFIX, begin_ask,
                                          complete_ask)
        from brain.research_models import ResearchConversation
        staff = _staff("nf_tg")
        conv = ResearchConversation.objects.create(
            user=staff, title=f"{TELEGRAM_THREAD_PREFIX}4242")
        _report()
        StrategistBriefing.objects.create(posture="neutral",
                                          outlook_md=f"Outlook: {MONEY}.")
        _strategist_prose()
        seen = []
        usage = {"input_tokens": 1, "output_tokens": 1, "cost_usd": 0.0}

        def init(self, *a, **kw):
            self.agent_name = "research"
            self.provider_name = "stub"
            self.model = "stub"
            self.provider = MagicMock()

            def complete(**kw):
                seen.append(kw["user_message"])
                return '{"answer_md": "ok"}', usage
            self.provider.complete = complete
        _u, pending = begin_ask(conv, "What happened?")
        with patch("brain.research_agent.ResearchAgent.__init__", init):
            complete_ask(pending.pk, channel=channel)
        self.assertEqual(len(seen), 1)
        return seen[0]

    def test_the_telegram_channel_is_handed_no_prose(self):
        self.assertNoFigure(self._ask_telegram("telegram"))

    def test_a_telegram_thread_read_on_the_web_is_handed_no_prose(self):
        self.assertNoFigure(self._ask_telegram("web"))


class TheMindIsNeverHandedMoneyTests(_Case):

    def test_the_mind_is_never_handed_money(self):
        from bot_program.audit import record_trade_close, record_trade_open
        from bot_program.models import AssetBotTrade
        from brain.observations import record_observation
        from brain.synthesizer import SauronMindAgent, _build_world_snapshot
        from tests.test_desk_seam import _config, _user
        cfg = _config(_user("nf_book"), symbols=["NFA1"], mode="live")
        shut = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="NFA1", side="BUY",
            qty=Decimal("98765"), entry_price=Decimal("100"),
            exit_price=Decimal("101"), pnl=Decimal("4321.09"),
            outcome="win", realized_r=1.5, status="CLOSED", paper=False,
            rule_name="nf_rule", broker_order_id="BO-12345")
        record_trade_close(cfg.user, trade=shut)
        opened = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="NFA1", side="BUY",
            qty=Decimal("55555"), entry_price=Decimal("100"),
            status="OPEN", paper=False, rule_name="nf_rule",
            broker_order_id="BO-23456")
        record_trade_open(cfg.user, trade=opened)
        record_observation(kind="shadow_entry", payload={
            "config_id": cfg.id, "symbol": "NFA1", "direction": "bullish",
            "qty": 44444.0, "price": 100.0, "score": 0.8,
            "rule_name": "nf_rule"}, source="asset_bot_shadow")
        snap = _build_world_snapshot()
        text = json.dumps(snap, default=str)
        self.assertNoFigure(text)
        self.assertNoFigure(SauronMindAgent().build_context(snapshot=snap))
        closes = [o["payload"] for o in snap["observations"]
                  if o["kind"] == "fill_closed"]
        self.assertEqual(len(closes), 1)
        self.assertEqual(closes[0]["realized_r"], 1.5)
        self.assertEqual(closes[0]["outcome"], "win")
        self.assertEqual(closes[0]["venue"], "live")
        self.assertNotIn("pnl", closes[0])
        self.assertNotIn("qty", closes[0])


class TheOldLettersTests(_PageCase):

    def _edition(self, created_at):
        from alerts.models import Newsletter
        nl = Newsletter.objects.create(
            title="Weekly Market Report", frequency="weekly", status="sent",
            sent_at=created_at + timedelta(hours=1),
            content_markdown=f"## The week\n\nThe book made {MONEY}.")
        Newsletter.objects.filter(pk=nl.pk).update(created_at=created_at)
        return nl

    def test_the_cutoff_is_pr72s_merge(self):
        from alerts.newsletter_service import NO_ACCOUNT_FIGURES_SINCE
        self.assertEqual(NO_ACCOUNT_FIGURES_SINCE,
                         datetime(2026, 10, 24, 13, 8, 25,
                                  tzinfo=dt_timezone.utc))

    def test_an_edition_written_before_the_cutoff_is_kept_for_staff(self):
        from alerts.newsletter_service import NO_ACCOUNT_FIGURES_SINCE
        nl = self._edition(NO_ACCOUNT_FIGURES_SINCE - timedelta(hours=3))
        r = _client_for(_plain()).get(f"/newsletters/{nl.pk}/")
        self.assertEqual(r.status_code, 200)
        body = r.content.decode()
        self.assertIn("Weekly Market Report", body)
        self.assertIn("kept for staff", body)
        self.assertNoMoney(body)
        staff = _client_for(_staff()).get(f"/newsletters/{nl.pk}/")
        self.assertIn("4,321.09", staff.content.decode())

    def test_an_untouched_weekly_draft_from_before_the_cutoff_is_never_sent(self):
        """Review F13: the page withheld what the Sunday send would still
        broadcast by email and Telegram, which cannot be recalled."""
        from alerts.models import Newsletter
        from alerts.newsletter_service import (NO_ACCOUNT_FIGURES_SINCE,
                                               due_newsletter_ids)
        now = NO_ACCOUNT_FIGURES_SINCE + timedelta(days=1)

        def draft(origin, created_at, **kw):
            nl = Newsletter.objects.create(
                title=f"{origin} draft", frequency="weekly",
                status="ai_generated", origin=origin,
                scheduled_for=now - timedelta(minutes=1),
                content_markdown=f"The book made {MONEY}.", **kw)
            Newsletter.objects.filter(pk=nl.pk).update(created_at=created_at)
            return nl
        before = NO_ACCOUNT_FIGURES_SINCE - timedelta(hours=3)
        held = draft("weekly_review", before)
        edited = draft("weekly_review", before,
                       touched_at=NO_ACCOUNT_FIGURES_SINCE + timedelta(hours=2))
        admin = draft("admin", before)
        later = draft("weekly_review",
                      NO_ACCOUNT_FIGURES_SINCE + timedelta(minutes=5))
        due = due_newsletter_ids(now)
        self.assertNotIn(held.pk, due)
        for nl in (edited, admin, later):
            self.assertIn(nl.pk, due, nl.title)
        # a staff edit releases it
        Newsletter.objects.filter(pk=held.pk).update(
            touched_at=NO_ACCOUNT_FIGURES_SINCE + timedelta(hours=4))
        self.assertIn(held.pk, due_newsletter_ids(now))

    def test_an_edition_written_after_the_cutoff_reads_whole(self):
        from alerts.newsletter_service import NO_ACCOUNT_FIGURES_SINCE
        nl = self._edition(NO_ACCOUNT_FIGURES_SINCE + timedelta(hours=1))
        body = _client_for(_plain()).get(
            f"/newsletters/{nl.pk}/").content.decode()
        self.assertNotIn("kept for staff", body)
        self.assertIn("The week", body)
