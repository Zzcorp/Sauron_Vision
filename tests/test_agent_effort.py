"""Every agent sends the effort the catalog gives it (2026-10-31).

Ten callers, in brain/ and ai_agents/tasks.py, call provider.complete()
themselves instead of going through BaseAgent.run, and none of them passed
`effort`: each ran at its model's API default, and an effort saved for
them on /ai-models/ was stored and never sent. Horizon was the one direct
caller that already passed it. All ten pass their agent's effort now.

No agent's effort drops. The six on the deep and frontier tiers ran at
Opus 5's and Fable 5.1's API default, high, and their tiers' effort is
high. The four on the balanced tier (the position reviewer, the close
advisor, the morning briefing, the Monday plan) ran at Sonnet 5's default,
high, while the balanced tier's effort is medium: sending the tier's
effort would have cut them silently. All ten carry their own default,
high, in catalog.AGENT_EFFORT_DEFAULTS, read before the tier's row: a tier
effort saved on /ai-models/ for the BaseAgent agents never reached these
ten, and it does not move them now, down or up. Only a row saved for
that very agent does. The table at the end pins every agent's effort as
it runs today, and the class after it pins that no saved tier row puts a
direct caller below the effort it ran at.

The tiers moved on 2026-11-01 (Haiku 5.5, Sonnet 5.5, Opus 5.5;
tests/test_tier_models.py) and no effort moved with them: the ten keep
high on Sonnet 5.5 and Opus 5.5 (whose API default is medium), the
BaseAgent agents keep their tier's effort, and the fast tier's low now
reaches the wire, Haiku 5.5 taking effort where Haiku 4.5 took none.

Run with:  python manage.py test tests.test_agent_effort
"""
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from tests.test_ai_models_truth import AGENTS, PROD_LIKE, build, run_time

REPO = Path(__file__).resolve().parent.parent

#: The four balanced agents that call the provider directly.
BALANCED_DIRECT = ("position_reviewer", "close_advisor", "daily_briefing",
                   "monday_plan")
#: All ten direct callers and their tier. Horizon, the eleventh direct
#: call, sent its tier's effort before 2026-10-31 and is not among them.
DIRECT = {
    **{name: "balanced" for name in BALANCED_DIRECT},
    **{name: "deep" for name in ("sauron_mind", "critic", "strategist",
                                 "earnings_reviewer", "research")},
    "strategy_generator": "frontier",
}


class _Stop(Exception):
    """What the patched provider raises once it has seen the call."""


def _stopping_complete():
    return patch("ai_agents.providers.claude_provider.ClaudeProvider.complete",
                 MagicMock(side_effect=_Stop("stopped after the call")))


class TheCatalogsPerAgentDefaultTests(TestCase):

    def test_the_ten_direct_callers_default_to_high(self):
        from ai_agents.catalog import (AGENT_EFFORT_DEFAULTS, TIER_DEFAULTS,
                                       resolve_effort)
        self.assertEqual(AGENT_EFFORT_DEFAULTS,
                         {name: "high" for name in DIRECT})
        for name, tier in DIRECT.items():
            with self.subTest(agent=name):
                self.assertEqual(
                    resolve_effort(TIER_DEFAULTS[tier], tier, name), "high")

    def test_every_other_balanced_agent_keeps_the_tiers_medium(self):
        from ai_agents.catalog import resolve_effort
        for name in ("macro_interpreter", "earnings_analyst",
                     "decay_investigator", "strategy_advisor",
                     "strategy_mutator", ""):
            self.assertEqual(
                resolve_effort("claude-sonnet-5", "balanced", name), "medium")

    def test_the_operators_agent_row_wins(self):
        from ai_agents.catalog import resolve_effort
        from ai_agents.models import AIModelSetting
        AIModelSetting.objects.create(scope="agent", key="position_reviewer",
                                      effort="low")
        self.assertEqual(resolve_effort("claude-sonnet-5", "balanced",
                                        "position_reviewer"), "low")

    def test_a_tier_rows_effort_does_not_move_a_direct_caller(self):
        """Until 2026-10-31 the ten sent no effort, so a tier's effort row
        never reached them. An effort the operator saved there, for the
        BaseAgent agents on the tier, must not move them the day they
        start sending one: not down (a balanced 'low' would cut the close
        advisor) and not up (a deep 'max' would multiply the hourly Mind's
        and the half-hourly critic's cost)."""
        from ai_agents.catalog import (EFFORT_LEVELS, TIER_DEFAULTS,
                                       resolve_effort)
        from ai_agents.models import AIModelSetting
        for tier_effort in EFFORT_LEVELS:
            for tier in ("balanced", "deep", "frontier"):
                AIModelSetting.objects.update_or_create(
                    scope="tier", key=tier, defaults={"effort": tier_effort})
            for name, tier in DIRECT.items():
                with self.subTest(agent=name, tier_effort=tier_effort):
                    self.assertEqual(
                        resolve_effort(TIER_DEFAULTS[tier], tier, name),
                        "high")

    def test_a_tier_rows_effort_still_sets_every_other_agent_on_it(self):
        from ai_agents.catalog import resolve_effort
        from ai_agents.models import AIModelSetting
        for tier, effort in (("balanced", "low"), ("deep", "medium"),
                             ("frontier", "xhigh")):
            AIModelSetting.objects.create(scope="tier", key=tier,
                                          effort=effort)
        self.assertEqual(resolve_effort("claude-sonnet-5", "balanced",
                                        "macro_interpreter"), "low")
        self.assertEqual(resolve_effort("claude-sonnet-5", "balanced"),
                         "low")
        self.assertEqual(resolve_effort("claude-opus-5", "deep",
                                        "weekly_reviewer"), "medium")
        self.assertEqual(resolve_effort("claude-fable-5-1", "frontier",
                                        "horizon"), "xhigh")

    def test_the_agents_own_row_moves_it_and_beats_its_default(self):
        """The one row that moves a direct caller is the one the operator
        saves for that very agent, in either direction."""
        from ai_agents.catalog import resolve_effort
        from ai_agents.models import AIModelSetting
        AIModelSetting.objects.create(scope="tier", key="deep",
                                      effort="max")
        AIModelSetting.objects.create(scope="agent", key="critic",
                                      effort="low")
        AIModelSetting.objects.create(scope="agent", key="sauron_mind",
                                      effort="xhigh")
        self.assertEqual(resolve_effort("claude-opus-5", "deep", "critic"),
                         "low")
        self.assertEqual(resolve_effort("claude-opus-5", "deep",
                                        "sauron_mind"), "xhigh")
        self.assertEqual(resolve_effort("claude-opus-5", "deep",
                                        "strategist"), "high")

    def test_a_model_without_effort_still_takes_none(self):
        from ai_agents.catalog import resolve_effort
        self.assertIsNone(resolve_effort("claude-haiku-4-5", "balanced",
                                         "daily_briefing"))


@override_settings(AI_CONFIG=PROD_LIKE)
class EveryDirectCallerSendsItsAgentsEffortTests(TestCase):
    """Each of the ten, driven through its own entry point with the
    provider stopped at the call: the model and the effort it hands over.
    """

    def _sent(self, drive):
        with _stopping_complete() as complete:
            drive()
        self.assertEqual(complete.call_count, 1)
        kw = complete.call_args.kwargs
        return kw["model"], kw.get("effort")

    def _deep(self, drive):
        self.assertEqual(self._sent(drive), ("claude-opus-5-5", "high"))

    def _balanced(self, drive):
        self.assertEqual(self._sent(drive), ("claude-sonnet-5-5", "high"))

    # ── the deep tier: Opus 5.5 at high, the high they ran at on Opus 5 ─
    def test_the_mind(self):
        from brain.synthesizer import synthesize_now
        self._deep(synthesize_now)

    def test_the_critic(self):
        from brain.critic import review_hypothesis
        from brain.hypotheses import post_hypothesis
        h = post_hypothesis(
            resolution_criteria={"kind": "regime_holds",
                                 "regime": "trending"},
            claim_text="x", source_agent="A", confidence=0.5,
            horizon_hours=24)
        self._deep(lambda: review_hypothesis(h))

    def test_the_strategist(self):
        from brain.strategist import run_strategist_now
        self._deep(run_strategist_now)

    def test_the_earnings_reviewer(self):
        from brain.earnings_reviewer import review_one_event
        from tests.test_brain_phase49_earnings_reviewer import (
            _earnings_event, _instrument)
        inst, ev = _instrument("EFFRT"), _earnings_event(title="EFFRT Earnings")
        self._deep(lambda: review_one_event(inst, ev))

    def test_the_research_chat(self):
        from brain.research_agent import (begin_ask, complete_ask,
                                          get_or_create_active_conversation)
        user = get_user_model().objects.create_user("effort_r", password="x")
        _, pending = begin_ask(get_or_create_active_conversation(user),
                               "What now?")
        with patch("brain.research_agent.can_spend",
                   return_value=(True, "ok")):
            self._deep(lambda: complete_ask(pending.pk))

    # ── the frontier tier: Fable 5.1 at high, as before, now sent ──────
    def test_the_strategy_generator(self):
        from brain.strategy_generator import generate_strategies_now
        self.assertEqual(self._sent(generate_strategies_now),
                         ("claude-fable-5-1", "high"))

    # ── the balanced four: Sonnet 5.5 at high, NOT the tier's medium ───
    def test_the_position_reviewer(self):
        from brain.position_review_agent import review_open_positions_now
        from tests.test_position_review import _quote, _trade
        _quote("EFFRP", 99.2)
        _trade("EFFRP", entry="100", initial_stop="99", stop="99",
               target="103")
        with patch("ai_agents.spend.can_spend", return_value=(True, "ok")):
            self._balanced(review_open_positions_now)

    def test_the_close_advisor(self):
        import os
        from brain.close_advice import advise
        from tests.test_close_advice import KEY, _quote, _trade
        user = get_user_model().objects.create_user("effort_c", password="x")
        _quote("BTCUSD", 58000)
        trade = _trade(user)
        with patch.dict(os.environ, KEY), \
                patch("ai_agents.spend.can_spend", return_value=(True, "ok")):
            self._balanced(lambda: advise(user, [trade.id], use_model=True))

    def test_the_morning_briefing(self):
        from ai_agents.tasks import DailyBriefingAgent

        def drive():
            with self.assertRaises(_Stop):
                DailyBriefingAgent().run("the day")
        self._balanced(drive)

    def test_the_monday_plan(self):
        from ai_agents.tasks import MondayPlanAgent

        def drive():
            with self.assertRaises(_Stop):
                MondayPlanAgent().run("the week")
        self._balanced(drive)

    # ── an effort saved on /ai-models/ is now sent ──────────────────────
    def test_an_agent_row_effort_reaches_the_call(self):
        from ai_agents.models import AIModelSetting
        from ai_agents.tasks import DailyBriefingAgent
        from brain.synthesizer import synthesize_now
        AIModelSetting.objects.create(scope="agent", key="sauron_mind",
                                      effort="max")
        AIModelSetting.objects.create(scope="agent", key="daily_briefing",
                                      effort="xhigh")
        self.assertEqual(self._sent(synthesize_now),
                         ("claude-opus-5-5", "max"))

        def drive():
            with self.assertRaises(_Stop):
                DailyBriefingAgent().run("the day")
        self.assertEqual(self._sent(drive), ("claude-sonnet-5-5", "xhigh"))


@override_settings(AI_CONFIG=PROD_LIKE)
class TheBalancedCallOnTheWireTests(TestCase):
    """One of the four through a real SDK client: the body carries
    output_config.effort = high (it carried no output_config before)."""

    def test_the_morning_briefing_sends_high(self):
        from ai_agents.providers.claude_provider import ClaudeProvider
        from ai_agents.tasks import DailyBriefingAgent
        from tests.test_claude_provider_bytes import _sse, _Wire
        wire = _Wire(_sse(model="claude-sonnet-5-5", text="The briefing."))
        with patch.object(ClaudeProvider, "_get_client",
                          return_value=wire.client):
            DailyBriefingAgent().run("the day")
        body = wire.body()
        self.assertEqual(body["model"], "claude-sonnet-5-5")
        self.assertEqual(body["output_config"], {"effort": "high"})


class EveryDirectCallSiteNamesTheEffortTests(TestCase):
    """Source-pinned, like the attribution in test_llm_ledger_truth: a new
    direct caller in brain/ or ai_agents/tasks.py that forgets `effort`
    fails here, before it runs at a model's default unseen."""

    @staticmethod
    def _calls(src):
        for m in re.finditer(r"provider\.complete\(", src):
            depth, i = 1, m.end()
            while depth and i < len(src):
                depth += {"(": 1, ")": -1}.get(src[i], 0)
                i += 1
            yield src[m.end():i - 1]

    def test_every_direct_call_passes_the_agents_effort(self):
        files = sorted((REPO / "brain").glob("*.py")) + [
            REPO / "ai_agents" / "tasks.py"]
        seen = 0
        for path in files:
            src = path.read_text(encoding="utf-8")
            for args in self._calls(src):
                seen += 1
                rel = path.relative_to(REPO).as_posix()
                self.assertRegex(
                    args, r"\beffort=",
                    f"{rel}: a provider.complete call without effort")
        self.assertEqual(seen, 11, "the ten callers and Horizon")


@override_settings(AI_CONFIG=PROD_LIKE)
class NoAgentsEffortDropsTests(TestCase):
    """Every agent's (model, effort) with nothing overridden, as it runs
    from 2026-11-01. Each effort is the one the agent ran at before:
    BaseAgent.run sent the tier's effort, a direct caller ran at the
    model's API default (high on Opus 5, Fable 5.1 and Sonnet 5). The
    one change is the fast tier: Haiku 4.5 took no effort and ran without
    thinking; Haiku 5.5 takes the tier's low."""

    EXPECTED = {
        # fast tier, Haiku 5.5: the tier's low (Haiku 4.5 took none)
        "news_analyst": ("claude-haiku-5-5", "low"),
        "anomaly_detector": ("claude-haiku-5-5", "low"),
        "market_commentator": ("claude-haiku-5-5", "low"),
        "speech_analyst": ("claude-haiku-5-5", "low"),
        "pretrade_sanity": ("claude-haiku-5-5", "low"),
        "signal_journal": ("claude-haiku-5-5", "low"),
        "trade_journal": ("claude-haiku-5-5", "low"),
        "next_steps": ("claude-haiku-5-5", "low"),
        "newsletter_writer": ("claude-haiku-5-5", "low"),
        # the debate and the council: their own model, the fast tier's low
        "debate_executioner": ("claude-opus-5-5", "low"),
        "debate_champion": ("claude-opus-5-5", "low"),
        "council_opportunist": ("claude-opus-5-5", "low"),
        "council_striker": ("claude-opus-5-5", "low"),
        "council_fixer": ("claude-opus-5-5", "low"),
        "council_gambler": ("claude-opus-5-5", "low"),
        "council_emperor": ("claude-opus-5-5", "low"),
        "council_skeptic": ("claude-opus-5-5", "low"),
        "council_awakened": ("claude-opus-5-5", "low"),
        "council_theorist": ("claude-opus-5-5", "low"),
        # balanced, through BaseAgent.run: the tier's medium, as sent before
        "macro_interpreter": ("claude-sonnet-5-5", "medium"),
        "earnings_analyst": ("claude-sonnet-5-5", "medium"),
        "decay_investigator": ("claude-sonnet-5-5", "medium"),
        "strategy_advisor": ("claude-sonnet-5-5", "medium"),
        "strategy_mutator": ("claude-sonnet-5-5", "medium"),
        # balanced, direct: Sonnet 5's API default, sent
        "position_reviewer": ("claude-sonnet-5-5", "high"),
        "close_advisor": ("claude-sonnet-5-5", "high"),
        "daily_briefing": ("claude-sonnet-5-5", "high"),
        "monday_plan": ("claude-sonnet-5-5", "high"),
        # deep: high, as on Opus 5 (Opus 5.5's API default is medium)
        "weekly_reviewer": ("claude-opus-5-5", "high"),
        "sauron_mind": ("claude-opus-5-5", "high"),
        "critic": ("claude-opus-5-5", "high"),
        "strategist": ("claude-opus-5-5", "high"),
        "earnings_reviewer": ("claude-opus-5-5", "high"),
        "research": ("claude-opus-5-5", "high"),
        # frontier: high, sent before (Horizon) or now
        "strategy_generator": ("claude-fable-5-1", "high"),
        "horizon": ("claude-fable-5-1", "high"),
    }

    def test_every_agent_runs_at_the_effort_it_ran_at(self):
        self.assertEqual(set(self.EXPECTED), set(AGENTS))
        for name, want in self.EXPECTED.items():
            with self.subTest(agent=name):
                self.assertEqual(run_time(build(name)), want)

    def test_no_direct_caller_is_below_its_models_api_default(self):
        from ai_agents.catalog import EFFORT_LEVELS, default_effort
        for name in BALANCED_DIRECT + ("sauron_mind", "critic", "strategist",
                                       "earnings_reviewer", "research",
                                       "strategy_generator", "horizon"):
            with self.subTest(agent=name):
                model, effort = run_time(build(name))
                self.assertGreaterEqual(
                    EFFORT_LEVELS.index(effort),
                    EFFORT_LEVELS.index(default_effort(model)))


@override_settings(AI_CONFIG=PROD_LIKE)
class NoSavedTierRowLowersADirectCallerTests(TestCase):
    """The deploy against whatever /ai-models/ already holds, which nobody
    has read (plan check F). Until 2026-10-31 the ten sent no effort, so
    each ran at its resolved model's API default (catalog default_effort)
    whatever rows were saved. Under any tier row, with or without a model
    and with any effort, and under a model-only pin on the agent itself,
    each of the ten now sends at least that. Only an effort saved on the
    agent's own row moves it below."""

    MODELS = ("claude-sonnet-5", "claude-sonnet-5-5", "claude-opus-5",
              "claude-opus-5-5", "claude-haiku-5-5", "claude-fable-5-1",
              "claude-haiku-4-5")

    def _assert_none_below_what_it_ran_at(self):
        from ai_agents.catalog import EFFORT_LEVELS, default_effort
        for name in DIRECT:
            model, effort = run_time(build(name))
            ran_at = default_effort(model)    # no effort was sent before
            with self.subTest(agent=name, model=model):
                if ran_at is None:            # a model without effort
                    self.assertIsNone(effort)
                else:
                    self.assertGreaterEqual(EFFORT_LEVELS.index(effort),
                                            EFFORT_LEVELS.index(ran_at))

    def _tier_rows(self, model_id, effort):
        from ai_agents.models import AIModelSetting
        for tier in ("balanced", "deep", "frontier"):
            AIModelSetting.objects.update_or_create(
                scope="tier", key=tier,
                defaults={"model_id": model_id, "effort": effort})

    def test_under_a_tier_row_with_an_effort_and_no_model(self):
        from ai_agents.catalog import EFFORT_LEVELS
        for effort in EFFORT_LEVELS:
            self._tier_rows("", effort)
            with self.subTest(tier_effort=effort):
                self._assert_none_below_what_it_ran_at()
                for name in DIRECT:
                    self.assertEqual(run_time(build(name))[1], "high")

    def test_under_a_tier_row_that_pins_a_model(self):
        from ai_agents.catalog import EFFORT_LEVELS
        for model in self.MODELS:
            for effort in ("",) + EFFORT_LEVELS:
                self._tier_rows(model, effort)
                with self.subTest(tier_model=model, tier_effort=effort):
                    self._assert_none_below_what_it_ran_at()

    def test_under_a_model_only_pin_on_the_agent(self):
        from ai_agents.models import AIModelSetting
        for model in self.MODELS:
            for name in DIRECT:
                AIModelSetting.objects.update_or_create(
                    scope="agent", key=name,
                    defaults={"model_id": model, "effort": ""})
            with self.subTest(agent_model=model):
                self._assert_none_below_what_it_ran_at()

    def test_a_pin_to_a_model_whose_default_is_medium_now_runs_at_high(self):
        """The one direction a saved row with no effort moves them: up.
        A pin to claude-opus-5-5 (API default medium), on the agent or on
        its tier, ran at medium; it now sends the agent's own high, and
        costs more. The commit names it, and check F lists such a row."""
        from ai_agents.catalog import default_effort
        from ai_agents.models import AIModelSetting
        self.assertEqual(default_effort("claude-opus-5-5"), "medium")
        AIModelSetting.objects.create(scope="agent", key="close_advisor",
                                      model_id="claude-opus-5-5")
        AIModelSetting.objects.create(scope="tier", key="deep",
                                      model_id="claude-opus-5-5")
        self.assertEqual(run_time(build("close_advisor")),
                         ("claude-opus-5-5", "high"))
        self.assertEqual(run_time(build("sauron_mind")),
                         ("claude-opus-5-5", "high"))
