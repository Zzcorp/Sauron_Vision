"""/ai-models/ shows what each agent runs (2026-10-31).

The page resolved each row with a tier written beside it by hand, and four
of those had drifted from the agent's own default_tier: it showed the Mind,
the research chat and the earnings reviewer on Sonnet 5 at medium (they run
on Opus 5 at high) and the strategy generator on Opus 5 (it runs on Fable
5.1). Five agents that read the same override table were not listed at
all, so the operator could neither see nor set them.

This file drives every agent through the page's resolver and through the
agent's own constructor, under each kind of setting the page can hold,
and asserts they agree. It also fails when an agent class exists that the
page does not list and nothing below excuses.

Run with:  python manage.py test tests.test_ai_models_truth
"""
import importlib
import inspect
import pkgutil

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings

#: Every agent on the page: its name, and the class it runs as.
AGENTS = {
    "news_analyst": ("ai_agents.agents.news_analyst", "NewsAnalystAgent"),
    "anomaly_detector": ("ai_agents.agents.anomaly_detector",
                         "AnomalyDetectorAgent"),
    "market_commentator": ("ai_agents.agents.market_commentator",
                           "MarketCommentatorAgent"),
    "speech_analyst": ("ai_agents.agents.speech_analyst",
                       "SpeechAnalystAgent"),
    "macro_interpreter": ("ai_agents.agents.macro_interpreter",
                          "MacroInterpreterAgent"),
    "earnings_analyst": ("ai_agents.agents.earnings_analyst",
                         "EarningsAnalystAgent"),
    "pretrade_sanity": ("ai_agents.agents.pretrade_sanity",
                        "PreTradeSanityAgent"),
    "debate_executioner": ("ai_agents.agents.trade_debate",
                           "ExecutionerAgent"),
    "debate_champion": ("ai_agents.agents.trade_debate", "ChampionAgent"),
    "signal_journal": ("ai_agents.agents.signal_journal",
                       "SignalJournalAgent"),
    "trade_journal": ("ai_agents.trade_journal", "TradeJournalAgent"),
    "position_reviewer": ("brain.position_review_agent",
                          "PositionReviewerAgent"),
    "close_advisor": ("brain.close_advice", "CloseAdvisorAgent"),
    "decay_investigator": ("ai_agents.agents.decay_investigator",
                           "DecayInvestigatorAgent"),
    "strategy_advisor": ("ai_agents.agents.strategy_advisor",
                         "StrategyAdvisorAgent"),
    "strategy_mutator": ("ai_agents.agents.strategy_mutator",
                         "StrategyMutatorAgent"),
    "weekly_reviewer": ("ai_agents.agents.weekly_reviewer",
                        "WeeklyReviewerAgent"),
    "council_opportunist": ("ai_agents.agents.council", "OpportunistAgent"),
    "council_striker": ("ai_agents.agents.council", "StrikerAgent"),
    "council_fixer": ("ai_agents.agents.council", "FixerAgent"),
    "council_gambler": ("ai_agents.agents.council", "GamblerAgent"),
    "council_emperor": ("ai_agents.agents.council", "EmperorAgent"),
    "council_skeptic": ("ai_agents.agents.council", "SkepticAgent"),
    "council_awakened": ("ai_agents.agents.council", "AwakenedAgent"),
    "council_theorist": ("ai_agents.agents.council", "TheoristAgent"),
    "daily_briefing": ("ai_agents.tasks", "DailyBriefingAgent"),
    "monday_plan": ("ai_agents.tasks", "MondayPlanAgent"),
    "next_steps": ("ai_agents.next_steps", "NextStepsAgent"),
    # Defined lazily inside a factory class; calling it builds the agent.
    "newsletter_writer": ("alerts.newsletter_service",
                          "_NewsletterWriterAgent"),
    "sauron_mind": ("brain.synthesizer", "SauronMindAgent"),
    "critic": ("brain.critic", "CriticAgent"),
    "strategist": ("brain.strategist", "StrategistAgent"),
    "strategy_generator": ("brain.strategy_generator",
                           "StrategyGeneratorAgent"),
    "earnings_reviewer": ("brain.earnings_reviewer", "EarningsReviewerAgent"),
    "research": ("brain.research_agent", "ResearchAgent"),
    "horizon": ("brain.horizon", "HorizonAgent"),
}

#: Agent classes the page does not list, and why.
NOT_LISTED = {
    "council_executioner": "the council's Executioner reads the "
                           "debate_executioner row",
    "council_champion": "the council's Champion reads the debate_champion "
                        "row",
}

#: Where agent classes live; the scan below reads every module in these.
AGENT_PACKAGES = ("ai_agents", "ai_agents.agents", "brain", "alerts")
#: Modules the scan cannot import, and why none of them holds an agent.
UNIMPORTABLE = {
    "ai_agents.memory": "a second AIMemory model beside ai_agents.models' "
                        "own; importing it raises, so nothing runs it",
}

#: AI_MODEL_* blank, as .env.production.example ships them: every tier
#: falls through to catalog.TIER_DEFAULTS, what production resolves.
PROD_LIKE = {**settings.AI_CONFIG,
             "models": {t: "" for t in ("fast", "balanced", "deep",
                                        "frontier")}}


def build(name):
    module, cls = AGENTS[name]
    return getattr(importlib.import_module(module), cls)()


def run_time(agent) -> tuple:
    """(model, effort) the agent hands the provider when it calls."""
    if hasattr(agent, "_model"):    # the two inline agents of ai_agents/tasks.py
        return agent._model, agent._effort
    return agent.model, agent.effort


def page_rows():
    from dashboard.views_ai_models import AGENT_GROUPS
    return [row for _, rows in AGENT_GROUPS for row in rows]


@override_settings(AI_CONFIG=PROD_LIKE)
class ThePageListsEveryAgentTests(TestCase):

    def test_the_five_that_were_missing_are_listed(self):
        names = {name for name, _, _ in page_rows()}
        for name in ("position_reviewer", "daily_briefing", "monday_plan",
                     "next_steps", "newsletter_writer"):
            self.assertIn(name, names)

    def test_every_row_is_an_agent_here_with_its_classes_own_tier(self):
        rows = page_rows()
        self.assertEqual(len(rows), len({name for name, _, _ in rows}),
                         "an agent listed twice")
        self.assertEqual({name for name, _, _ in rows}, set(AGENTS))
        for name, _, tier in rows:
            with self.subTest(agent=name):
                self.assertEqual(build(name).default_tier, tier)

    def test_every_agent_class_on_the_platform_is_listed_or_excused(self):
        found = set()
        for pkg in AGENT_PACKAGES:
            package = importlib.import_module(pkg)
            for info in pkgutil.iter_modules(package.__path__):
                dotted = f"{pkg}.{info.name}"
                if info.ispkg or dotted in UNIMPORTABLE:
                    continue
                module = importlib.import_module(dotted)
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if obj.__module__ != module.__name__:
                        continue
                    name = getattr(obj, "agent_name", None)
                    if name and name != "base" and getattr(
                            obj, "default_tier", None):
                        found.add(name)
        found.add(build("newsletter_writer").agent_name)
        self.assertEqual(found, set(AGENTS) | set(NOT_LISTED))

    def test_an_override_for_a_newly_listed_agent_is_accepted(self):
        from ai_agents.models import AIModelSetting
        boss = User.objects.create_user("models_boss", password="x",
                                        is_staff=True, is_superuser=True)
        self.client.force_login(boss)
        self.client.post("/ai-models/", {
            "scope": "agent", "key": "position_reviewer",
            "model_id": "claude-opus-5", "effort": "xhigh"})
        row = AIModelSetting.objects.get(scope="agent",
                                         key="position_reviewer")
        self.assertEqual((row.model_id, row.effort),
                         ("claude-opus-5", "xhigh"))


@override_settings(AI_CONFIG=PROD_LIKE)
class ThePageAgreesWithTheRunTimeTests(TestCase):
    """Each agent through dashboard.views_ai_models.agent_choice and
    through its own constructor: the same model, the same effort."""

    def _assert_agree(self):
        from dashboard.views_ai_models import agent_choice
        for name, _, tier in page_rows():
            with self.subTest(agent=name):
                self.assertEqual(agent_choice(name, tier),
                                 run_time(build(name)))

    def test_with_nothing_set(self):
        self._assert_agree()

    def test_with_a_model_and_an_effort_on_every_tier(self):
        from ai_agents.models import AIModelSetting
        for tier, model, effort in (
                ("fast", "claude-haiku-5-5", "medium"),
                ("balanced", "claude-sonnet-5-5", "low"),
                ("deep", "claude-opus-5-5", "max"),
                ("frontier", "claude-opus-5-5", "xhigh")):
            AIModelSetting.objects.create(scope="tier", key=tier,
                                          model_id=model, effort=effort)
        self._assert_agree()

    def test_with_a_model_only_on_every_tier(self):
        from ai_agents.models import AIModelSetting
        for tier, model in (("fast", "claude-haiku-5-5"),
                            ("balanced", "claude-sonnet-5-5"),
                            ("deep", "claude-opus-5-5"),
                            ("frontier", "claude-fable-5-1")):
            AIModelSetting.objects.create(scope="tier", key=tier,
                                          model_id=model)
        self._assert_agree()

    def test_with_a_row_for_every_agent(self):
        from ai_agents.models import AIModelSetting
        for name in AGENTS:
            AIModelSetting.objects.create(scope="agent", key=name,
                                          model_id="claude-sonnet-5-5",
                                          effort="xhigh")
        self._assert_agree()

    def test_with_a_model_only_row_for_every_agent(self):
        from ai_agents.models import AIModelSetting
        for name in AGENTS:
            AIModelSetting.objects.create(scope="agent", key=name,
                                          model_id="claude-opus-5-5")
        self._assert_agree()

    def test_with_the_models_set_in_the_environment(self):
        env = {**settings.AI_CONFIG, "models": {
            "fast": "claude-haiku-4-5-20251001",
            "balanced": "claude-sonnet-5-5", "deep": "claude-opus-5-5",
            "frontier": "claude-fable-5-1"}}
        with override_settings(AI_CONFIG=env):
            self._assert_agree()


@override_settings(AI_CONFIG=PROD_LIKE)
class ThePageShowsWhatRunsTests(TestCase):

    def setUp(self):
        boss = User.objects.create_user("models_viewer", password="x",
                                        is_staff=True, is_superuser=True)
        self.client.force_login(boss)

    def _rows(self):
        r = self.client.get("/ai-models/")
        self.assertEqual(r.status_code, 200)
        return {row["name"]: row for group in r.context["agent_groups"]
                for row in group["rows"]}

    def test_the_four_that_drifted_show_their_real_tier_and_model(self):
        rows = self._rows()
        for name, tier, model, effort in (
                ("sauron_mind", "deep", "claude-opus-5", "high"),
                ("research", "deep", "claude-opus-5", "high"),
                ("earnings_reviewer", "deep", "claude-opus-5", "high"),
                ("strategy_generator", "frontier", "claude-fable-5-1",
                 "high")):
            with self.subTest(agent=name):
                self.assertEqual((rows[name]["tier"], rows[name]["resolved"],
                                  rows[name]["effort"]),
                                 (tier, model, effort))

    def test_the_five_that_were_missing_show_their_model_and_effort(self):
        rows = self._rows()
        for name, model, effort in (
                ("position_reviewer", "claude-sonnet-5", "high"),
                ("daily_briefing", "claude-sonnet-5", "high"),
                ("monday_plan", "claude-sonnet-5", "high"),
                ("next_steps", "claude-haiku-4-5", "—"),
                ("newsletter_writer", "claude-haiku-4-5", "—")):
            with self.subTest(agent=name):
                self.assertEqual((rows[name]["resolved"],
                                  rows[name]["effort"]), (model, effort))

    def test_the_page_states_the_effort_order_it_resolves_by(self):
        r = self.client.get("/ai-models/")
        self.assertContains(
            r, "Effort: agent override → the agent's own default → tier "
               "setting → the tier's default.", html=False)
        self.assertContains(
            r, "a tier's effort does not move them; their own override "
               "does.", html=False)

    def test_a_tier_effort_shows_on_its_agents_but_not_on_the_direct_callers(
            self):
        from ai_agents.models import AIModelSetting
        AIModelSetting.objects.create(scope="tier", key="balanced",
                                      effort="low")
        AIModelSetting.objects.create(scope="tier", key="deep",
                                      effort="medium")
        rows = self._rows()
        for name, effort in (("macro_interpreter", "low"),
                             ("weekly_reviewer", "medium"),
                             ("close_advisor", "high"),
                             ("position_reviewer", "high"),
                             ("sauron_mind", "high"),
                             ("critic", "high")):
            with self.subTest(agent=name):
                self.assertEqual(rows[name]["effort"], effort)
