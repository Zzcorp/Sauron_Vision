"""The three tier defaults move to the current generation (2026-11-01).

The operator approved it on 2026-10-31:
  fast      claude-haiku-4-5  -> claude-haiku-5-5
  balanced  claude-sonnet-5   -> claude-sonnet-5-5
  deep      claude-opus-5     -> claude-opus-5-5
The frontier tier (claude-fable-5-1), the debate and the council (their
own claude-opus-5-5) and the Orcs' ladder do not move, and the
provider's refusal re-run stays on claude-opus-5.

The three new models think by default and put their thinking blocks
BEFORE the text (with display omitted, the default, a block's `thinking`
is an empty string). Thinking counts toward max_tokens and is billed as
output. They refuse `thinking: disabled` (Sonnet 5.5, Opus 5.5),
`budget_tokens`, non-default sampling parameters, forced tool_choice and
a prefill, and they can decline a request (stop_reason "refusal").

For EVERY agent that resolves to one of the three tiers, this file
proves, offline:
  1. it runs on the tier's new model, with an explicit effort no lower
     than the one it ran at on the old model: Haiku 4.5 took no effort
     and ran without thinking; BaseAgent.run sent its tier's effort; a
     direct caller ran at Sonnet 5's or Opus 5's API default, high, and
     sends it since 2026-10-31 (tests/test_agent_effort.py);
  2. its max_tokens is its longest expected answer plus the thinking
     room, and never below the bound it had;
  3. driven through its own entry point, against a real SDK client over a
     recording transport that answers thinking first, its request carries
     exactly that model, effort and max_tokens and none of the fields
     these models refuse, and what it reads is the text block, never the
     thinking block in front of it.
And, for the provider on each of the three models: the text is read from
the text blocks only; a refusal re-runs once on claude-opus-5 (a fast or
balanced decline only when the deep reserve allows it); a max_tokens stop
with no text is a logged, billed failure, never an empty answer.

And what the declines, new on the fast tier and newly re-run on the deep
one, leave behind: the declined call's row names the agent that made it,
for every one of the 24, and a news article the model declines is marked
and never sent again by the five-minute queue.

No request leaves the process.

Run with:  python manage.py test tests.test_tier_models
"""
import json
import os
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from tests.test_ai_models_truth import AGENTS, PROD_LIKE, build, run_time
from tests.test_claude_provider_bytes import httpx

REPO = Path(__file__).resolve().parent.parent

OLD = {"fast": "claude-haiku-4-5", "balanced": "claude-sonnet-5",
       "deep": "claude-opus-5"}
NEW = {"fast": "claude-haiku-5-5", "balanced": "claude-sonnet-5-5",
       "deep": "claude-opus-5-5"}

#: Every agent on the three tiers: its tier, and the effort it ran at
#: before 2026-11-01 on the tier's old model (None: Haiku 4.5, which took
#: no effort and ran without thinking).
BEFORE = {
    # fast, Haiku 4.5, through BaseAgent.run
    "news_analyst": ("fast", None),
    "anomaly_detector": ("fast", None),
    "market_commentator": ("fast", None),
    "speech_analyst": ("fast", None),
    "pretrade_sanity": ("fast", None),
    "signal_journal": ("fast", None),
    "trade_journal": ("fast", None),
    "next_steps": ("fast", None),
    "newsletter_writer": ("fast", None),
    # balanced, Sonnet 5, through BaseAgent.run: the tier's medium
    "macro_interpreter": ("balanced", "medium"),
    "earnings_analyst": ("balanced", "medium"),
    "decay_investigator": ("balanced", "medium"),
    "strategy_advisor": ("balanced", "medium"),
    "strategy_mutator": ("balanced", "medium"),
    # balanced, Sonnet 5, direct callers: its API default, high
    "position_reviewer": ("balanced", "high"),
    "close_advisor": ("balanced", "high"),
    "daily_briefing": ("balanced", "high"),
    "monday_plan": ("balanced", "high"),
    # deep, Opus 5: high, sent by BaseAgent.run or its API default
    "weekly_reviewer": ("deep", "high"),
    "sauron_mind": ("deep", "high"),
    "critic": ("deep", "high"),
    "strategist": ("deep", "high"),
    "earnings_reviewer": ("deep", "high"),
    "research": ("deep", "high"),
}

#: What each sends from 2026-11-01. The fast tier's own effort, low, now
#: reaches the wire (Haiku 5.5 takes effort); nothing else moves.
AFTER_EFFORT = {name: ("low" if tier == "fast" else effort)
                for name, (tier, effort) in BEFORE.items()}

#: The bound each request had before: 8,192 on Haiku 4.5 (no thinking),
#: 32,000 on Sonnet 5 and Opus 5 (claude_provider.build_request).
BOUND_BEFORE = {"fast": 8192, "balanced": 32000, "deep": 32000}

#: Fields the new models refuse with a 400, or that would change their
#: behaviour; none may be on a tier agent's request.
REFUSED = ("thinking", "temperature", "top_p", "top_k", "tool_choice",
           "tools", "stop_sequences", "fallbacks")
#: The whole body of a tier agent's request.
BODY_KEYS = {"max_tokens", "messages", "model", "output_config", "system",
             "stream"}

ANSWER = "The answer, in the text block after the thinking block."


def _longest_answer(name):
    """The longest answer `name` is expected to write, in tokens, from its
    own code. Every one but two writes under the 8,192 tokens every call's
    answer had before thinking: the fast tier's whole bound was 8,192 with
    no thinking, and the others' parsers keep at most 8,000 characters of
    prose (the Mind's narrative, the strategist's outlook, the earnings
    reviewer's summary, the research answer) or a few sentences of JSON.
    The two: the close advisor, which answers for up to MAX_POSITIONS
    positions at once (its own cost estimate), and the weekly reviewer,
    ten sections whose tables run to WEEK_MAX_ROWS rows a book."""
    from ai_agents.providers.claude_provider import ANSWER_TOKENS
    if name == "close_advisor":
        from brain.close_advice import MAX_POSITIONS, answer_tokens_for
        return answer_tokens_for(MAX_POSITIONS)
    if name == "weekly_reviewer":
        from ai_agents.agents.weekly_reviewer import WeeklyReviewerAgent
        return WeeklyReviewerAgent.answer_tokens
    return ANSWER_TOKENS


# ── the recording transport ─────────────────────────────────────────────

def _stream(*, model, texts=(ANSWER,), thinking="", stop_reason="end_turn",
            category=None, input_tokens=1000, output_tokens=600):
    """A server-sent-event stream as the new models send it: ONE thinking
    block first (its `thinking` empty, as display "omitted" leaves it, or
    a summary when `thinking` is given), then the text blocks, if any."""
    events = [("message_start", {"type": "message_start", "message": {
        "id": "msg_tier", "type": "message", "role": "assistant",
        "model": model, "content": [], "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": input_tokens, "output_tokens": 1}}})]
    events += [
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "thinking",
                                                   "thinking": "",
                                                   "signature": ""}})]
    if thinking:
        events.append(("content_block_delta", {
            "type": "content_block_delta", "index": 0,
            "delta": {"type": "thinking_delta", "thinking": thinking}}))
    events += [
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "signature_delta",
                                           "signature": "c2lnbmF0dXJl"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0})]
    for i, text in enumerate(texts, start=1):
        events += [
            ("content_block_start", {"type": "content_block_start",
                                     "index": i, "content_block": {
                                         "type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta",
                                     "index": i, "delta": {
                                         "type": "text_delta",
                                         "text": text}}),
            ("content_block_stop", {"type": "content_block_stop",
                                    "index": i})]
    details = ({"type": "refusal", "category": category,
                "explanation": "declined"}
               if stop_reason == "refusal" else None)
    events += [
        ("message_delta", {"type": "message_delta",
                           "delta": {"stop_reason": stop_reason,
                                     "stop_sequence": None,
                                     "stop_details": details},
                           "usage": {"output_tokens": output_tokens}}),
        ("message_stop", {"type": "message_stop"})]
    return "".join(f"event: {n}\ndata: {json.dumps(d)}\n\n"
                   for n, d in events).encode()


class _Recorder:
    """A real anthropic.Anthropic client whose transport records every
    request and answers each with the next canned stream, the last one
    over and over (an entry point that calls twice gets two answers)."""

    def __init__(self, *answers):
        import anthropic
        self.answers = list(answers)
        self.requests = []
        self.client = anthropic.Anthropic(
            api_key="test-key-not-real", max_retries=0,
            base_url="https://api.anthropic.com",
            http_client=httpx.Client(
                transport=httpx.MockTransport(self._handle)))

    def _handle(self, request):
        self.requests.append(request)
        body = self.answers.pop(0) if len(self.answers) > 1 \
            else self.answers[0]
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=body)

    def body(self, i=0):
        return json.loads(self.requests[i].content)

    def provider(self):
        from ai_agents.providers.claude_provider import ClaudeProvider
        p = ClaudeProvider()
        p.client = self.client
        return p

    def patched(self):
        """Every ClaudeProvider built while active talks to this client."""
        from ai_agents.providers.claude_provider import ClaudeProvider
        return patch.object(ClaudeProvider, "_get_client",
                            return_value=self.client)


# ── each agent through its own entry point ──────────────────────────────

def _run_quietly(fn):
    """Drive an entry point; whatever it does with the canned answer after
    the call (a JSON parser refusing prose, say) is not under test."""
    try:
        fn()
    except Exception:  # noqa: BLE001 — the request is what is measured
        pass


def _drive(name):
    """Call `name` the way the platform calls it, up to the model call."""
    allow = patch("ai_agents.spend.can_spend", return_value=(True, "ok"))
    if name == "sauron_mind":
        from brain.synthesizer import synthesize_now
        return _run_quietly(synthesize_now)
    if name == "critic":
        from brain.critic import review_hypothesis
        from brain.hypotheses import post_hypothesis
        h = post_hypothesis(
            resolution_criteria={"kind": "regime_holds",
                                 "regime": "trending"},
            claim_text="x", source_agent="A", confidence=0.5,
            horizon_hours=24)
        return _run_quietly(lambda: review_hypothesis(h))
    if name == "strategist":
        from brain.strategist import run_strategist_now
        return _run_quietly(run_strategist_now)
    if name == "earnings_reviewer":
        from brain.earnings_reviewer import review_one_event
        from tests.test_brain_phase49_earnings_reviewer import (
            _earnings_event, _instrument)
        inst = _instrument("TIERE")
        ev = _earnings_event(title="TIERE Earnings")
        return _run_quietly(lambda: review_one_event(inst, ev))
    if name == "research":
        from brain.research_agent import (begin_ask, complete_ask,
                                          get_or_create_active_conversation)
        user = get_user_model().objects.create_user("tier_r", password="x")
        _, pending = begin_ask(get_or_create_active_conversation(user),
                               "What now?")
        with patch("brain.research_agent.can_spend",
                   return_value=(True, "ok")):
            return _run_quietly(lambda: complete_ask(pending.pk))
    if name == "position_reviewer":
        from brain.position_review_agent import review_open_positions_now
        from tests.test_position_review import _quote, _trade
        _quote("TIERP", 99.2)
        _trade("TIERP", entry="100", initial_stop="99", stop="99",
               target="103")
        with allow:
            return _run_quietly(review_open_positions_now)
    if name == "close_advisor":
        from brain.close_advice import advise
        from tests.test_close_advice import KEY, _quote, _trade
        user = get_user_model().objects.create_user("tier_c", password="x")
        _quote("BTCUSD", 58000)
        trade = _trade(user)
        with patch.dict(os.environ, KEY), allow:
            return _run_quietly(
                lambda: advise(user, [trade.id], use_model=True))
    if name == "daily_briefing":
        from ai_agents.tasks import DailyBriefingAgent
        return _run_quietly(lambda: DailyBriefingAgent().run("the day"))
    if name == "monday_plan":
        from ai_agents.tasks import MondayPlanAgent
        return _run_quietly(lambda: MondayPlanAgent().run("the week"))
    if name == "newsletter_writer":
        # Its context is the prompt generate_newsletter_with_ai writes.
        return _run_quietly(lambda: build(name).run(prompt="This week."))
    # Every other one is a BaseAgent: BaseAgent.run builds its request.
    return _run_quietly(lambda: build(name).run())


# ── 1. the defaults ─────────────────────────────────────────────────────

class TheTierDefaultsTests(TestCase):

    def test_the_three_tiers_are_on_the_current_generation(self):
        from ai_agents.catalog import TIER_DEFAULTS
        self.assertEqual(TIER_DEFAULTS, {**NEW,
                                         "frontier": "claude-fable-5-1"})

    def test_settings_env_defaults_name_the_same_models(self):
        """config/settings.py's defaults, used when AI_MODEL_* is unset
        (blank falls through to the catalog): the same three ids."""
        src = (REPO / "config" / "settings.py").read_text(encoding="utf-8")
        for tier, var in (("fast", "AI_MODEL_FAST"),
                          ("balanced", "AI_MODEL_BALANCED"),
                          ("deep", "AI_MODEL_DEEP")):
            with self.subTest(tier=tier):
                self.assertRegex(
                    src, rf'"{tier}": os\.getenv\("{var}", '
                         rf'"{re.escape(NEW[tier])}"\)')
        self.assertRegex(src, r'"frontier": os\.getenv\("AI_MODEL_FRONTIER"'
                              r', "claude-fable-5-1"\)')

    def test_what_does_not_move(self):
        from ai_agents.agents.trade_debate import DEBATE_MODEL
        from ai_agents.catalog import TIER_EFFORT_DEFAULTS
        from ai_agents.providers.claude_provider import REFUSAL_FALLBACK_MODEL
        self.assertEqual(DEBATE_MODEL, "claude-opus-5-5")
        self.assertEqual(REFUSAL_FALLBACK_MODEL, "claude-opus-5")
        self.assertEqual(TIER_EFFORT_DEFAULTS, {
            "fast": "low", "balanced": "medium", "deep": "high",
            "frontier": "high"})

    def test_the_old_three_stay_pinnable(self):
        """A saved override or an AI_MODEL_* value naming one of them is
        still a served, priced model, not a 'retired' fallback."""
        from ai_agents.catalog import MODELS
        for model in (*OLD.values(), "claude-haiku-4-5-20251001"):
            self.assertIn(model, MODELS)

    def test_the_providers_default_model_is_the_balanced_default(self):
        import inspect
        from ai_agents.catalog import TIER_DEFAULTS
        from ai_agents.providers.claude_provider import ClaudeProvider
        default = inspect.signature(
            ClaudeProvider.complete).parameters["model"].default
        self.assertEqual(default, TIER_DEFAULTS["balanced"])

    def test_no_catalog_note_calls_a_previous_model_current(self):
        """The notes the /ai-models/ catalog table shows."""
        from ai_agents.catalog import MODELS
        for model in NEW.values():
            with self.subTest(model=model):
                self.assertNotIn("no tier points at it",
                                 MODELS[model]["notes"])
                self.assertIn("tier's default since 2026-11-01",
                              MODELS[model]["notes"])
        for model in (*OLD.values(), "claude-haiku-4-5-20251001"):
            with self.subTest(model=model):
                notes = MODELS[model]["notes"]
                self.assertIn("Previous-generation", notes)
                self.assertIn("until 2026-11-01", notes)
                for stale in ("Strongest", "Good default workhorse",
                              "Cheapest"):
                    self.assertNotIn(stale, notes)
        self.assertNotIn("twice the Opus price",
                         MODELS["claude-fable-5-1"]["notes"])


# ── 2. every tier agent: model, effort, max_tokens ──────────────────────

@override_settings(AI_CONFIG=PROD_LIKE)
class EveryTierAgentResolvesTests(TestCase):

    def test_the_table_is_every_agent_on_the_three_tiers(self):
        from ai_agents.agents.council import COUNCIL_AGENT_NAMES
        from ai_agents.agents.trade_debate import DEBATE_AGENT_NAMES
        on_tiers = {name for name in AGENTS
                    if build(name).default_tier in NEW
                    and name not in DEBATE_AGENT_NAMES + COUNCIL_AGENT_NAMES}
        self.assertEqual(set(BEFORE), on_tiers)

    def test_each_runs_on_its_tiers_new_model(self):
        for name, (tier, _) in BEFORE.items():
            with self.subTest(agent=name):
                self.assertEqual(run_time(build(name))[0], NEW[tier])

    def test_each_sends_an_explicit_effort_no_lower_than_before(self):
        from ai_agents.catalog import EFFORT_LEVELS
        for name, (tier, before) in BEFORE.items():
            with self.subTest(agent=name):
                effort = run_time(build(name))[1]
                self.assertIn(effort, EFFORT_LEVELS, "an explicit effort")
                self.assertEqual(effort, AFTER_EFFORT[name])
                if before is not None:
                    self.assertGreaterEqual(EFFORT_LEVELS.index(effort),
                                            EFFORT_LEVELS.index(before))

    def test_the_deep_agents_do_not_fall_to_opus_5_5s_medium(self):
        """Opus 5.5's API default is medium, a level below Opus 5's high:
        an agent that sent nothing would drop a level unseen."""
        from ai_agents.catalog import default_effort
        self.assertEqual(default_effort(NEW["deep"]), "medium")
        for name, (tier, _) in BEFORE.items():
            if tier == "deep":
                with self.subTest(agent=name):
                    self.assertEqual(run_time(build(name))[1], "high")


class TheMaxTokensRuleTests(TestCase):
    """max_tokens = the answer's room + the thinking room, on a model that
    thinks by default; the answer's room alone on one that does not."""

    def test_the_default_is_the_bound_of_before(self):
        from ai_agents.providers.claude_provider import (
            ANSWER_TOKENS, THINKING_TOKENS, build_request, max_tokens_for)
        self.assertEqual((ANSWER_TOKENS, THINKING_TOKENS), (8192, 23808))
        for model, want in (("claude-haiku-5-5", 32000),
                            ("claude-sonnet-5-5", 32000),
                            ("claude-opus-5-5", 32000),
                            ("claude-haiku-4-5", 8192)):
            with self.subTest(model=model):
                self.assertEqual(max_tokens_for(model), want)
                self.assertEqual(build_request(
                    model=model, user_message="q")["kwargs"]["max_tokens"],
                    want)

    def test_a_longer_answer_adds_its_length_and_never_lowers(self):
        from ai_agents.providers.claude_provider import (THINKING_TOKENS,
                                                         max_tokens_for)
        self.assertEqual(max_tokens_for("claude-opus-5-5", 20000),
                         20000 + THINKING_TOKENS)
        self.assertEqual(max_tokens_for("claude-haiku-4-5", 20000), 20000)
        for short in (1, 2400, 8192):
            self.assertEqual(max_tokens_for("claude-sonnet-5-5", short),
                             32000)

    def test_answer_tokens_reaches_the_request(self):
        from ai_agents.providers.claude_provider import build_request
        kw = build_request(model="claude-sonnet-5-5", user_message="q",
                           answer_tokens=10000)["kwargs"]
        self.assertEqual(kw["max_tokens"], 33808)

    def test_answer_tokens_is_checked_before_anything_is_sent(self):
        from ai_agents.providers.claude_provider import build_request
        for bad in (0, -5, True, "9000", 1.5):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                build_request(model="claude-opus-5-5", user_message="q",
                              answer_tokens=bad)
        with self.assertRaises(ValueError):
            build_request(model="claude-opus-5-5", user_message="q",
                          answer_tokens=9000, max_tokens=40000)

    def test_a_refusal_re_run_sizes_the_answer_for_the_fallback(self):
        """An answer bound is resized for the model that re-runs it: a
        pin to a model without thinking gets the answer's room alone, and
        its re-run on Opus 5, which thinks, gets the thinking room too."""
        wire = _Recorder(
            _stream(model="claude-haiku-4-5", texts=(),
                    stop_reason="refusal", output_tokens=0),
            _stream(model="claude-opus-5", texts=("rescued",)))
        with patch("ai_agents.spend.can_spend", return_value=(True, "ok")), \
                self.assertLogs("ai_agents.providers.claude_provider",
                                level="WARNING"):
            text, _ = wire.provider().complete(
                "sys", "q", model="claude-haiku-4-5", answer_tokens=20000,
                agent_name="t")
        self.assertEqual(text, "rescued")
        self.assertEqual(wire.body(0)["max_tokens"], 20000)
        self.assertEqual(wire.body(1)["model"], "claude-opus-5")
        self.assertEqual(wire.body(1)["max_tokens"], 43808)


@override_settings(AI_CONFIG=PROD_LIKE)
class EveryTierAgentsMaxTokensTests(TestCase):

    def test_each_leaves_the_thinking_room_on_its_longest_answer(self):
        from ai_agents.providers.claude_provider import (THINKING_TOKENS,
                                                         max_tokens_for)
        for name, (tier, _) in BEFORE.items():
            with self.subTest(agent=name):
                longest = _longest_answer(name)
                bound = max_tokens_for(NEW[tier], longest)
                self.assertGreaterEqual(bound, longest + THINKING_TOKENS)
                self.assertGreaterEqual(bound, BOUND_BEFORE[tier],
                                        "a bound never goes down")

    def test_the_two_long_answers_are_raised(self):
        """The close advisor answers for up to fifty positions at once,
        and the weekly reviewer writes ten sections with tables: on the
        32,000 they had, at high effort, their thinking would share what
        is left after the answer. Both now get the thinking room on top
        of their longest answer."""
        from ai_agents.agents.weekly_reviewer import WeeklyReviewerAgent
        from ai_agents.providers.claude_provider import max_tokens_for
        from ai_agents.tasks import WEEK_MAX_ROWS
        from brain.close_advice import (MAX_POSITIONS, OUTPUT_TOKENS_BASE,
                                        OUTPUT_TOKENS_PER_POSITION,
                                        answer_tokens_for)
        self.assertEqual(answer_tokens_for(MAX_POSITIONS),
                         OUTPUT_TOKENS_BASE
                         + OUTPUT_TOKENS_PER_POSITION * MAX_POSITIONS)
        self.assertEqual(max_tokens_for(NEW["balanced"],
                                        answer_tokens_for(MAX_POSITIONS)),
                         45808)
        # Three books' rules in two tables, the skips, the findings and
        # the brakes, WEEK_MAX_ROWS rows each, at ~40 tokens a row.
        self.assertGreaterEqual(WeeklyReviewerAgent.answer_tokens,
                                9 * WEEK_MAX_ROWS * 40)
        self.assertEqual(max_tokens_for(NEW["deep"],
                                        WeeklyReviewerAgent.answer_tokens),
                         40192)

    def test_the_close_advisor_sizes_its_answer_by_the_selection(self):
        """advise() hands the provider the answer bound of the positions
        it asks about, the same arithmetic as its cost estimate."""
        from brain.close_advice import advise, answer_tokens_for
        from tests.test_close_advice import KEY, _quote, _trade
        user = get_user_model().objects.create_user("tier_n", password="x")
        _quote("BTCUSD", 58000)
        trades = [_trade(user) for _ in range(3)]
        complete = MagicMock(side_effect=RuntimeError("stopped"))
        with patch.dict(os.environ, KEY), \
                patch("ai_agents.spend.can_spend", return_value=(True, "ok")), \
                patch("ai_agents.providers.claude_provider.ClaudeProvider"
                      ".complete", complete):
            advise(user, [t.id for t in trades], use_model=True)
        self.assertEqual(complete.call_count, 1)
        self.assertEqual(complete.call_args.kwargs["answer_tokens"],
                         answer_tokens_for(3))


# ── 3. every tier agent, on the wire ────────────────────────────────────

@override_settings(AI_CONFIG=PROD_LIKE)
class EveryTierAgentOnTheWireTests(TestCase):
    """Each of the 24, through its own entry point, against a real SDK
    client over a recording transport that answers thinking first."""

    def _on_the_wire(self, name):
        from ai_agents.models import AgentTask
        tier = BEFORE[name][0]
        wire = _Recorder(_stream(model=NEW[tier]))
        with wire.patched():
            _drive(name)
        self.assertGreaterEqual(len(wire.requests), 1, "no request was sent")
        body = wire.body(0)
        req = wire.requests[0]
        self.assertEqual(req.url.path, "/v1/messages")
        self.assertNotIn("anthropic-beta", req.headers)
        self.assertEqual(body["model"], NEW[tier])
        self.assertEqual(body["output_config"],
                         {"effort": AFTER_EFFORT[name]})
        from ai_agents.providers.claude_provider import max_tokens_for
        want = max_tokens_for(NEW[tier], None if name != "weekly_reviewer"
                              else _longest_answer(name))
        self.assertEqual(body["max_tokens"], want)
        self.assertGreaterEqual(body["max_tokens"], BOUND_BEFORE[tier])
        self.assertLessEqual(set(body), BODY_KEYS)
        for key in REFUSED:
            self.assertNotIn(key, body)
        self.assertEqual(body["messages"][-1]["role"], "user",
                         "no prefill: the last turn is the user's")
        # What the agent read is the text block, never the empty thinking
        # block in front of it: the ledger row keeps what it read.
        rows = AgentTask.objects.filter(agent=name)
        self.assertTrue(rows.exists(), "no ledger row")
        for row in rows:
            self.assertEqual(row.model, NEW[tier])
            if row.response_summary:
                self.assertEqual(row.response_summary, ANSWER)
        self.assertTrue(any(r.response_summary == ANSWER for r in rows),
                        [r.error for r in rows])


def _wire_test(name):
    def test(self):
        self._on_the_wire(name)
    test.__name__ = f"test_{name}"
    test.__doc__ = f"{name}: model, effort, max_tokens, the text it reads."
    return test


for _name in BEFORE:
    setattr(EveryTierAgentOnTheWireTests, f"test_{_name}", _wire_test(_name))
del _name


# ── 4. the provider on the three new models ─────────────────────────────

_BUDGET = {**settings.AI_CONFIG, "daily_budget_usd": 27.0,
           "orc_daily_budget_usd": 0.0}


@override_settings(AI_CONFIG=_BUDGET)
class TheProviderOnTheNewModelsTests(TestCase):

    def test_the_text_is_read_from_the_text_blocks_only(self):
        """A summarised thinking block (display "summarized") never leaks
        into the answer, and every text block is kept, in order."""
        for model in NEW.values():
            with self.subTest(model=model):
                wire = _Recorder(_stream(
                    model=model, thinking="a summary of the reasoning",
                    texts=("Part one. ", "Part two.")))
                text, usage = wire.provider().complete(
                    "sys", "q", model=model, effort="high", agent_name="t")
                self.assertEqual(text, "Part one. Part two.")
                self.assertEqual(usage["output_tokens"], 600,
                                 "thinking is billed as output")

    def test_an_omitted_thinking_block_is_skipped(self):
        for model in NEW.values():
            with self.subTest(model=model):
                wire = _Recorder(_stream(model=model))
                text, _ = wire.provider().complete(
                    "sys", "q", model=model, effort="low", agent_name="t")
                self.assertEqual(text, ANSWER)

    def test_a_refusal_re_runs_once_on_opus_5(self):
        """The client-side fallback stays on claude-opus-5. A fast or
        balanced decline asks the deep reserve first (Opus money); a deep
        one was cleared by its caller. The re-run carries the same effort,
        sized again for Opus 5, and the decline is booked as billed."""
        from ai_agents.models import AgentTask
        for model, asks_reserve in ((NEW["fast"], True),
                                    (NEW["balanced"], True),
                                    (NEW["deep"], False)):
            with self.subTest(model=model):
                AgentTask.objects.all().delete()
                wire = _Recorder(
                    _stream(model=model, texts=(), stop_reason="refusal",
                            category="cyber", output_tokens=40),
                    _stream(model="claude-opus-5", texts=("rescued",)))
                with patch("ai_agents.spend.can_spend",
                           return_value=(True, "ok")) as can_spend, \
                        self.assertLogs("ai_agents.providers.claude_provider",
                                        level="WARNING") as logs:
                    text, usage = wire.provider().complete(
                        "sys", "q", model=model, effort="high",
                        agent_name="t")
                self.assertEqual(text, "rescued")
                self.assertEqual(usage["model"], "claude-opus-5")
                self.assertEqual(len(wire.requests), 2)
                self.assertEqual(wire.body(0)["model"], model)
                self.assertEqual(wire.body(1)["model"], "claude-opus-5")
                self.assertEqual(wire.body(1)["output_config"],
                                 {"effort": "high"})
                self.assertEqual(wire.body(1)["max_tokens"], 32000)
                self.assertEqual(can_spend.called, asks_reserve)
                if asks_reserve:
                    self.assertEqual(can_spend.call_args.kwargs["tier"],
                                     "deep")
                self.assertIn("cyber", "\n".join(logs.output))
                declined, answered = AgentTask.objects.order_by("pk")
                self.assertEqual((declined.model, declined.success),
                                 (model, False))
                self.assertIn("declined", declined.error)
                self.assertGreater(float(declined.cost_usd), 0)
                self.assertEqual((answered.model, answered.success),
                                 ("claude-opus-5", True))

    def test_a_refusal_the_deep_reserve_holds_is_a_billed_failure(self):
        from ai_agents.models import AgentTask
        for model in (NEW["fast"], NEW["balanced"]):
            with self.subTest(model=model):
                AgentTask.objects.all().delete()
                wire = _Recorder(_stream(model=model, texts=(),
                                         stop_reason="refusal",
                                         output_tokens=40))
                with patch("ai_agents.spend.can_spend",
                           return_value=(False, "deep reserve spent")):
                    with self.assertRaises(RuntimeError) as caught:
                        wire.provider().complete(
                            "sys", "q", model=model, effort="low",
                            agent_name="t")
                self.assertIn("deep reserve spent", str(caught.exception))
                self.assertGreater(caught.exception.usage["cost_usd"], 0)
                self.assertEqual(len(wire.requests), 1)
                row = AgentTask.objects.get()
                self.assertFalse(row.success)

    def test_a_max_tokens_stop_with_no_text_is_a_logged_billed_failure(self):
        """Thinking counts toward max_tokens: a call can spend the whole
        bound thinking and write no text. That is a failed call, logged
        and booked at its cost, never an empty answer."""
        from ai_agents.catalog import cost_usd
        from ai_agents.models import AgentTask
        for model in NEW.values():
            with self.subTest(model=model):
                AgentTask.objects.all().delete()
                wire = _Recorder(_stream(model=model, texts=(),
                                         stop_reason="max_tokens",
                                         input_tokens=900,
                                         output_tokens=32000))
                with self.assertLogs("ai_agents.providers.claude_provider",
                                     level="WARNING") as logs:
                    with self.assertRaises(RuntimeError) as caught:
                        wire.provider().complete(
                            "sys", "q", model=model, effort="high",
                            agent_name="t")
                said = str(caught.exception)
                self.assertIn("max_tokens", said)
                self.assertIn("32000", said)
                self.assertIn("before any text", said)
                self.assertIn("before any text", "\n".join(logs.output))
                want = round(cost_usd(model, input_tokens=900,
                                      output_tokens=32000), 6)
                self.assertEqual(caught.exception.usage["cost_usd"], want)
                self.assertEqual(caught.exception.usage["stop_reason"],
                                 "max_tokens")
                row = AgentTask.objects.get()
                self.assertFalse(row.success)
                self.assertEqual(float(row.cost_usd), want)
                self.assertIn("max_tokens", row.error)

    @override_settings(AI_CONFIG=PROD_LIKE)
    def test_through_base_agent_a_max_tokens_stop_is_a_failure_row(self):
        """The fast tier's agents go through BaseAgent.run: the stop
        raises, the failure row carries the billed cost, and no success
        row is written with an empty answer."""
        from ai_agents.models import AgentTask
        wire = _Recorder(_stream(model=NEW["fast"], texts=(),
                                 stop_reason="max_tokens",
                                 output_tokens=32000))
        with wire.patched(), self.assertLogs(
                "ai_agents.providers.claude_provider", level="WARNING"):
            with self.assertRaises(RuntimeError):
                build("news_analyst").run()
        row = AgentTask.objects.get(agent="news_analyst")
        self.assertFalse(row.success)
        self.assertIn("max_tokens", row.error)
        self.assertGreater(float(row.cost_usd), 0)
        self.assertFalse(AgentTask.objects.filter(success=True).exists())

    def test_a_max_tokens_stop_after_some_text_still_says_truncated(self):
        """Unchanged: text cut at max_tokens is returned and warned."""
        wire = _Recorder(_stream(model=NEW["deep"], texts=('{"a": "b',),
                                 stop_reason="max_tokens"))
        with self.assertLogs("ai_agents.providers.claude_provider",
                             level="WARNING") as logs:
            text, usage = wire.provider().complete(
                "sys", "q", model=NEW["deep"], effort="high",
                agent_name="t")
        self.assertEqual(text, '{"a": "b')
        self.assertEqual(usage["stop_reason"], "max_tokens")
        self.assertIn("truncated", "\n".join(logs.output))


# ── 5. /ai-models/ ──────────────────────────────────────────────────────

@override_settings(AI_CONFIG=PROD_LIKE)
class ThePageShowsTheNewDefaultsTests(TestCase):

    def test_the_tier_strip_and_the_code_defaults(self):
        from django.contrib.auth.models import User
        boss = User.objects.create_user("tier_viewer", password="x",
                                        is_staff=True, is_superuser=True)
        self.client.force_login(boss)
        r = self.client.get("/ai-models/")
        self.assertEqual(r.status_code, 200)
        rows = {row["tier"]: row for row in r.context["tier_rows"]}
        for tier, label, effort in (("fast", "Claude Haiku 5.5", "low"),
                                    ("balanced", "Claude Sonnet 5.5",
                                     "medium"),
                                    ("deep", "Claude Opus 5.5", "high")):
            with self.subTest(tier=tier):
                self.assertEqual((rows[tier]["resolved"],
                                  rows[tier]["code_default"],
                                  rows[tier]["label"], rows[tier]["effort"]),
                                 (NEW[tier], NEW[tier], label, effort))
        agents = {row["name"]: row for group in r.context["agent_groups"]
                  for row in group["rows"]}
        for name, (tier, _) in BEFORE.items():
            with self.subTest(agent=name):
                self.assertEqual((agents[name]["resolved"],
                                  agents[name]["effort"]),
                                 (NEW[tier], AFTER_EFFORT[name]))


# ── 6. a declined call is booked under the agent that made it ──────────

def _refusal(model, category="cyber"):
    return _stream(model=model, texts=(), stop_reason="refusal",
                   category=category, output_tokens=40)


@override_settings(AI_CONFIG=PROD_LIKE)
class TheDeclinedCallNamesItsAgentTests(TestCase):
    """A decline the provider re-runs on claude-opus-5 leaves two billed
    calls. The re-run's row is written by whoever writes the call's rows;
    the declined call's row by the provider itself, even for a
    record=False caller (BaseAgent.run, the morning briefing, the Monday
    plan), under the agent_name it is handed. Those three handed none, so
    that row read "unattributed": the agent's decline and its cost were
    missing from its own line on /ai/. Both are new with the move: Haiku
    5.5 declines, Haiku 4.5 did not, and a deep decline on Opus 5.5 now
    re-runs, where one on Opus 5, the re-run's own model, did not."""

    def _declined_then_rescued(self, name):
        from ai_agents.models import AgentTask
        tier = BEFORE[name][0]
        wire = _Recorder(_refusal(NEW[tier]),
                         _stream(model="claude-opus-5"))
        with wire.patched(), patch("ai_agents.spend.can_spend",
                                   return_value=(True, "ok")):
            _drive(name)
        self.assertGreaterEqual(len(wire.requests), 2, "no re-run")
        self.assertEqual([wire.body(i)["model"] for i in range(2)],
                         [NEW[tier], "claude-opus-5"])
        declined = AgentTask.objects.get(model=NEW[tier])
        self.assertFalse(declined.success)
        self.assertIn("declined", declined.error)
        self.assertGreater(float(declined.cost_usd), 0)
        self.assertEqual(declined.agent, name)
        rescued = AgentTask.objects.filter(model="claude-opus-5")
        self.assertTrue(rescued.exists(), "no row for the re-run")
        self.assertEqual({row.agent for row in rescued}, {name})
        self.assertFalse(
            AgentTask.objects.filter(agent="unattributed").exists())

    def test_through_base_agent_a_decline_nobody_rescues(self):
        """Both declines are the agent's own failures: the provider's row
        for the first, and BaseAgent.run's for the re-run's, raised."""
        from ai_agents.models import AgentTask
        wire = _Recorder(_refusal(NEW["fast"]), _refusal("claude-opus-5"))
        with wire.patched(), patch("ai_agents.spend.can_spend",
                                   return_value=(True, "ok")):
            with self.assertRaises(RuntimeError) as caught:
                build("news_analyst").run(article={"title": "t"})
        self.assertEqual(caught.exception.usage["stop_reason"], "refusal")
        self.assertEqual(
            list(AgentTask.objects.order_by("pk").values_list(
                "agent", "model", "success")),
            [("news_analyst", NEW["fast"], False),
             ("news_analyst", "claude-opus-5", False)])

    def test_a_deep_decline_on_opus_5_5_now_re_runs(self):
        """The deep default was the re-run's own model: a decline there
        was a failure, never a re-run. On Opus 5.5 it re-runs, and the
        weekly reviewer, a BaseAgent, now leaves a row of its own for it."""
        from ai_agents.models import AgentTask
        wire = _Recorder(_refusal(NEW["deep"], category="bio"),
                         _stream(model="claude-opus-5",
                                 texts=("the review",)))
        with wire.patched():
            build("weekly_reviewer").run()
        self.assertEqual(
            list(AgentTask.objects.order_by("pk").values_list(
                "agent", "model", "success")),
            [("weekly_reviewer", NEW["deep"], False),
             ("weekly_reviewer", "claude-opus-5", True)])


def _declined_row_test(name):
    def test(self):
        self._declined_then_rescued(name)
    test.__name__ = f"test_{name}"
    test.__doc__ = f"{name}: its declined call's row carries its name."
    return test


for _name in BEFORE:
    setattr(TheDeclinedCallNamesItsAgentTests, f"test_{_name}",
            _declined_row_test(_name))
del _name


# ── 7. the news queue: a declined article is not sent again ─────────────

NEWS_JSON = ('{"sentiment_score": 0.4, "urgency": "normal", '
             '"affected_symbols": [], "summary": "s", '
             '"market_impact": "m"}')


@override_settings(AI_CONFIG=PROD_LIKE)
class ADeclinedArticleIsNotSentAgainTests(TestCase):
    """process_unanalyzed_news takes the ten newest articles without an
    ai_processed_at, every five minutes, and stamps one only on a success.
    A decline of the same text does not go away on a retry, and declines
    are new on this tier: an article Haiku 5.5 and its re-run on Opus 5
    both declined went out again on every beat, two billed calls a beat,
    with no end. A decline is final for the queue now. The article is
    marked ai_declined_at and keeps ai_processed_at empty: it was never
    analysed, so no reader of the analyst's work (the sentiment index,
    news_risk, the briefing, the RAG) counts it."""

    def _article(self, n=1, minutes_ago=0):
        from datetime import timedelta

        from django.utils import timezone
        from scraping.models import NewsArticle
        return NewsArticle.objects.create(
            title=f"Exploit drains a DeFi protocol ({n})", source="coindesk",
            url=f"https://example.invalid/tier/{n}",
            published_at=timezone.now() - timedelta(minutes=minutes_ago),
            content_summary="An attacker used a reentrancy bug ...")

    def _beats(self, wire, n=3, reserve=True):
        """`n` passes of the five-minute task, through its gate. The day's
        total always allows; the deep reserve as `reserve` says."""
        from ai_agents.tasks import process_unanalyzed_news

        def can_spend(*args, **kwargs):
            if kwargs.get("total_only") or reserve:
                return True, "ok"
            return False, "deep reserve spent"
        with wire.patched(), \
                patch("ai_agents.spend.can_spend", side_effect=can_spend), \
                patch("core.task_gate.is_component_enabled",
                      return_value=True):
            return [process_unanalyzed_news() for _ in range(n)]

    def _models(self, wire):
        return [wire.body(i)["model"] for i in range(len(wire.requests))]

    def test_an_article_both_models_decline_costs_one_pair_in_three_beats(
            self):
        from ai_agents.models import AgentTask
        art = self._article()
        wire = _Recorder(_refusal(NEW["fast"]), _refusal("claude-opus-5"))
        outs = self._beats(wire)
        self.assertEqual(self._models(wire), [NEW["fast"], "claude-opus-5"])
        self.assertEqual(outs[0], {"status": "success", "processed": 0,
                                   "attempted": 1, "stored": 0,
                                   "declined": 1})
        self.assertEqual(outs[1:], [{"status": "no_unprocessed_news"}] * 2)
        art.refresh_from_db()
        self.assertIsNotNone(art.ai_declined_at)
        self.assertIsNone(art.ai_processed_at)
        self.assertIsNone(art.ai_sentiment_score)
        self.assertEqual(
            list(AgentTask.objects.order_by("pk").values_list(
                "agent", "model", "success")),
            [("news_analyst", NEW["fast"], False),
             ("news_analyst", "claude-opus-5", False)])

    def test_a_decline_the_deep_reserve_holds_is_final_too(self):
        """No re-run (the reserve holds the Opus money): the one Haiku
        call, and the article is not sent again."""
        art = self._article()
        wire = _Recorder(_refusal(NEW["fast"]))
        outs = self._beats(wire, reserve=False)
        self.assertEqual(self._models(wire), [NEW["fast"]])
        self.assertEqual(outs[0]["declined"], 1)
        self.assertEqual(outs[1:], [{"status": "no_unprocessed_news"}] * 2)
        art.refresh_from_db()
        self.assertIsNotNone(art.ai_declined_at)
        self.assertIsNone(art.ai_processed_at)

    def test_a_rescued_decline_is_an_analysed_article(self):
        art = self._article()
        wire = _Recorder(_refusal(NEW["fast"]),
                         _stream(model="claude-opus-5", texts=(NEWS_JSON,)))
        outs = self._beats(wire, n=2)
        self.assertEqual(self._models(wire), [NEW["fast"], "claude-opus-5"])
        self.assertEqual(outs, [{"status": "success", "processed": 1,
                                 "attempted": 1, "stored": 1,
                                 "declined": 0},
                                {"status": "no_unprocessed_news"}])
        art.refresh_from_db()
        self.assertIsNone(art.ai_declined_at)
        self.assertIsNotNone(art.ai_processed_at)
        self.assertEqual(art.ai_sentiment_score, 0.4)

    def test_a_failure_that_is_not_a_decline_is_tried_again(self):
        """Unchanged for every other failure (an outage, a missing key, a
        call that spent its bound thinking): the article stays queued."""
        art = self._article()
        wire = _Recorder(_stream(model=NEW["fast"], texts=(),
                                 stop_reason="max_tokens",
                                 output_tokens=32000))
        outs = self._beats(wire, n=2)
        self.assertEqual(self._models(wire), [NEW["fast"]] * 2)
        self.assertEqual([o["declined"] for o in outs], [0, 0])
        art.refresh_from_db()
        self.assertIsNone(art.ai_declined_at)
        self.assertIsNone(art.ai_processed_at)

    def test_a_declined_article_takes_no_slot_in_the_queue(self):
        """The queue is the ten newest unprocessed articles: a declined
        one, however new, is not among them."""
        from django.utils import timezone
        declined = self._article(1)
        declined.ai_declined_at = timezone.now()
        declined.save()
        fresh = self._article(2, minutes_ago=30)
        wire = _Recorder(_stream(model=NEW["fast"], texts=(NEWS_JSON,)))
        outs = self._beats(wire, n=1)
        self.assertEqual(len(wire.requests), 1)
        self.assertIn(fresh.title, wire.body(0)["messages"][0]["content"])
        self.assertNotIn(declined.title,
                         wire.body(0)["messages"][0]["content"])
        self.assertEqual(outs[0]["attempted"], 1)

    def test_the_model_matches_its_migrations(self):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        call_command("makemigrations", "scraping", "--check", "--dry-run",
                     stdout=out)
        self.assertIn("No changes detected", out.getvalue())
