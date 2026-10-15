"""The provider's new keyword arguments (PR O0a; spec §7.3, §7.5.8, §5.2a).

`ClaudeProvider.complete()` learns what the Orcs will need: cache blocks,
two user turns with the effort-only system message between them, a JSON
schema, a bound on max_tokens, server-side fallbacks, a budget line, a
timeout, a task budget and fast mode. No caller passes any of them in
O0a; tests/test_claude_provider_bytes.py pins that the default request
did not move. This file pins what each keyword sends, what it refuses
before any call is made, how the refusal re-run carries them, and what
the ledger books (cache-aware cost, the answering model, the latency).

A fake client only: nothing here reaches the network.

Run with:  python manage.py test tests.test_claude_provider_keywords
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase, override_settings

SCHEMA = {"type": "object",
          "properties": {"action": {"type": "string"}},
          "required": ["action"], "additionalProperties": False}


def _usage(input_tokens=1000, output_tokens=200, **extra):
    base = dict(input_tokens=input_tokens, output_tokens=output_tokens,
                cache_read_input_tokens=None,
                cache_creation_input_tokens=None, cache_creation=None)
    base.update(extra)
    return SimpleNamespace(**base)


def _response(text='{"action": "hold"}', stop_reason="end_turn",
              usage=None, model=None):
    content = [SimpleNamespace(type="text", text=text)] if text else []
    return SimpleNamespace(content=content, stop_reason=stop_reason,
                           stop_details=None, usage=usage or _usage(),
                           model=model or "claude-test", id="msg_test")


class _Stream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.response


class _Client:
    """Records every stream() call on the plain and the beta path and
    answers from a list (or one response for every call)."""

    def __init__(self, *responses):
        self.responses = list(responses) or [_response()]
        self.calls = []
        self.messages = MagicMock()
        self.beta = MagicMock()
        self.messages.stream.side_effect = lambda **kw: self._answer(
            "plain", kw)
        self.beta.messages.stream.side_effect = lambda **kw: self._answer(
            "beta", kw)
        self.messages.count_tokens.return_value = SimpleNamespace(
            input_tokens=4321)

    def _answer(self, path, kw):
        self.calls.append((path, kw))
        r = (self.responses.pop(0) if len(self.responses) > 1
             else self.responses[0])
        return _Stream(r)


def _provider(client):
    from ai_agents.providers.claude_provider import ClaudeProvider
    p = ClaudeProvider()
    p.client = client
    return p


def _blocks(*items):
    return [{"text": t, "cache_ttl": ttl} for t, ttl in items]


def _budget(total, orcs=0.0):
    """The budget these tests read, written whole: never the
    AI_DAILY_BUDGET_USD / ORC_DAILY_BUDGET_USD of this process's
    environment (a box's .env), so the answers do not depend on where the
    suite runs."""
    return override_settings(AI_CONFIG={
        **settings.AI_CONFIG, "daily_budget_usd": total,
        "orc_daily_budget_usd": orcs})


class RequestShapeTests(TestCase):

    def test_system_blocks_become_cached_content_blocks(self):
        client = _Client()
        _provider(client).complete(
            "", "q", model="claude-sonnet-5-5", effort="low",
            system_blocks=_blocks(("doctrine", "1h"), ("rules", "5m"),
                                  ("plain", None)))
        path, kw = client.calls[0]
        self.assertEqual(path, "plain")
        self.assertEqual(kw["system"], [
            {"type": "text", "text": "doctrine",
             "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            {"type": "text", "text": "rules",
             "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "plain"},
        ])
        self.assertEqual(kw["messages"], [{"role": "user", "content": "q"}])

    def test_user_blocks_make_one_user_turn(self):
        client = _Client()
        _provider(client).complete(
            "sys", "", model="claude-sonnet-5-5",
            user_blocks=_blocks(("day", "1h"), ("now", None)))
        _, kw = client.calls[0]
        self.assertEqual(kw["system"], "sys")
        self.assertEqual(kw["messages"], [{"role": "user", "content": [
            {"type": "text", "text": "day",
             "cache_control": {"type": "ephemeral", "ttl": "1h"}},
            {"type": "text", "text": "now"}]}])

    def test_two_turns_with_the_effort_only_message_between(self):
        """§5.2a: the shared, cached turn; then the effort-only system
        message; then the private turn it governs. The per-message effort
        is a beta, so the request goes through client.beta.messages."""
        client = _Client()
        _provider(client).complete(
            "", "", model="claude-opus-5-5", effort="medium",
            system_blocks=_blocks(("S", "1h")),
            shared_user_blocks=_blocks(("MK", "1h"), ("IN", "5m")),
            private_user_blocks=_blocks(("PS", None), ("tail", None)),
            turn_effort="xhigh", output_schema=SCHEMA, max_tokens=4000)
        path, kw = client.calls[0]
        self.assertEqual(path, "beta")
        client.messages.stream.assert_not_called()
        self.assertEqual(kw["betas"],
                         ["mid-conversation-output-config-2026-07-01"])
        self.assertEqual([m["role"] for m in kw["messages"]],
                         ["user", "system", "user"])
        self.assertEqual(kw["messages"][1], {
            "role": "system", "content": [],
            "output_config": {"effort": "xhigh"}})
        self.assertEqual([b["text"] for b in kw["messages"][0]["content"]],
                         ["MK", "IN"])
        self.assertEqual([b["text"] for b in kw["messages"][2]["content"]],
                         ["PS", "tail"])
        self.assertTrue(all("cache_control" not in b
                            for b in kw["messages"][2]["content"]))
        self.assertEqual(kw["output_config"], {
            "effort": "medium",
            "format": {"type": "json_schema", "schema": SCHEMA}})
        self.assertEqual(kw["max_tokens"], 4000)

    def test_two_turns_without_a_turn_effort_stay_on_the_plain_client(self):
        client = _Client()
        _provider(client).complete(
            "sys", "", model="claude-sonnet-5-5",
            shared_user_blocks=_blocks(("MK", "1h")),
            private_user_blocks=_blocks(("PS", None)))
        path, kw = client.calls[0]
        self.assertEqual(path, "plain")
        self.assertNotIn("betas", kw)
        self.assertEqual([m["role"] for m in kw["messages"]],
                         ["user", "user"])

    def test_output_schema_merges_with_effort(self):
        client = _Client()
        _provider(client).complete("s", "q", model="claude-sonnet-5-5",
                                   effort="low", output_schema=SCHEMA)
        path, kw = client.calls[0]
        self.assertEqual(path, "plain")
        self.assertEqual(kw["output_config"], {
            "effort": "low",
            "format": {"type": "json_schema", "schema": SCHEMA}})

    def test_max_tokens_is_a_caller_bound(self):
        client = _Client()
        _provider(client).complete("s", "q", model="claude-opus-5-5",
                                   max_tokens=1234)
        self.assertEqual(client.calls[0][1]["max_tokens"], 1234)

    def test_fallbacks_default_form(self):
        client = _Client()
        _provider(client).complete("s", "q", model="claude-sonnet-5-5",
                                   fallbacks="default")
        path, kw = client.calls[0]
        self.assertEqual(path, "beta")
        self.assertEqual(kw["fallbacks"], "default")
        self.assertEqual(kw["betas"], ["server-side-fallback-2026-07-01"])

    def test_fallbacks_list_form_has_its_own_header(self):
        client = _Client()
        _provider(client).complete(
            "s", "q", model="claude-opus-5-5",
            fallbacks=[{"model": "claude-opus-5"}])
        _, kw = client.calls[0]
        self.assertEqual(kw["fallbacks"], [{"model": "claude-opus-5"}])
        self.assertEqual(kw["betas"], ["server-side-fallback-2026-06-01"])

    def test_task_budget(self):
        client = _Client()
        _provider(client).complete("s", "q", model="claude-opus-5-5",
                                   effort="xhigh", task_budget=25_600)
        path, kw = client.calls[0]
        self.assertEqual(path, "beta")
        self.assertEqual(kw["output_config"], {
            "effort": "xhigh",
            "task_budget": {"type": "tokens", "total": 25_600}})
        self.assertEqual(kw["betas"], ["task-budgets-2026-03-13"])

    def test_fast_mode(self):
        client = _Client()
        _provider(client).complete("s", "q", model="claude-opus-5-5",
                                   speed="fast")
        path, kw = client.calls[0]
        self.assertEqual(path, "beta")
        self.assertEqual(kw["speed"], "fast")
        self.assertEqual(kw["betas"], ["fast-mode-2026-02-01"])

    def test_timeout_only_when_set(self):
        client = _Client()
        p = _provider(client)
        p.complete("s", "q", model="claude-opus-5-5", timeout_s=42)
        self.assertEqual(client.calls[0][1]["timeout"], 42.0)
        p.complete("s", "q", model="claude-opus-5-5")
        self.assertNotIn("timeout", client.calls[1][1])

    def test_every_beta_at_once_in_a_fixed_order(self):
        client = _Client()
        _provider(client).complete(
            "", "", model="claude-opus-5-5", effort="medium",
            system_blocks=_blocks(("S", "1h")),
            shared_user_blocks=_blocks(("MK", "1h")),
            private_user_blocks=_blocks(("PS", None)),
            turn_effort="low", fallbacks="default", task_budget=20_000,
            speed="fast")
        self.assertEqual(client.calls[0][1]["betas"], [
            "mid-conversation-output-config-2026-07-01",
            "server-side-fallback-2026-07-01",
            "task-budgets-2026-03-13",
            "fast-mode-2026-02-01"])


class ValidationTests(TestCase):
    """Each misuse is a ValueError before any request leaves."""

    def _refused(self, model="claude-opus-5-5", system_prompt="",
                 user_message="", **kw):
        client = _Client()
        with self.assertRaises(ValueError):
            _provider(client).complete(system_prompt, user_message,
                                       model=model, **kw)
        self.assertEqual(client.calls, [])
        client.messages.stream.assert_not_called()
        client.beta.messages.stream.assert_not_called()

    def test_a_system_prompt_and_system_blocks(self):
        self._refused(system_prompt="s", user_message="q",
                      system_blocks=_blocks(("S", None)))

    def test_a_user_message_and_user_blocks(self):
        self._refused(user_message="q", user_blocks=_blocks(("U", None)))

    def test_user_blocks_and_shared_blocks(self):
        self._refused(user_blocks=_blocks(("U", None)),
                      shared_user_blocks=_blocks(("MK", None)))

    def test_private_blocks_without_shared_ones(self):
        self._refused(private_user_blocks=_blocks(("PS", None)))

    def test_a_turn_effort_without_a_private_turn(self):
        self._refused(shared_user_blocks=_blocks(("MK", None)),
                      turn_effort="low")

    def test_an_unknown_turn_effort(self):
        self._refused(shared_user_blocks=_blocks(("MK", None)),
                      private_user_blocks=_blocks(("PS", None)),
                      turn_effort="extreme")

    def test_a_turn_effort_on_a_model_without_it(self):
        self._refused(model="claude-sonnet-5",
                      shared_user_blocks=_blocks(("MK", None)),
                      private_user_blocks=_blocks(("PS", None)),
                      turn_effort="low")

    def test_five_breakpoints(self):
        self._refused(system_blocks=_blocks(("a", "1h"), ("b", "1h")),
                      shared_user_blocks=_blocks(("c", "1h"), ("d", "5m")),
                      private_user_blocks=_blocks(("e", "5m")))

    def test_a_1h_breakpoint_after_a_5m_one(self):
        """The caching page: a longer TTL must come before a shorter one."""
        self._refused(system_blocks=_blocks(("S", "5m")),
                      shared_user_blocks=_blocks(("MK", "1h")),
                      private_user_blocks=_blocks(("PS", None)))

    def test_a_malformed_block(self):
        self._refused(system_blocks=[{"cache_ttl": "1h"}], user_message="q")
        self._refused(system_blocks=[{"text": "S", "cache_ttl": "2h"}],
                      user_message="q")
        self._refused(system_blocks=[{"text": "", "cache_ttl": None}],
                      user_message="q")

    def test_a_task_budget_under_the_minimum_or_unsupported(self):
        self._refused(user_message="q", task_budget=19_999)
        self._refused(model="claude-sonnet-5", user_message="q",
                      task_budget=20_000)

    def test_speed_other_than_fast_or_without_fast_pricing(self):
        self._refused(user_message="q", speed="slow")
        self._refused(model="claude-sonnet-5-5", user_message="q",
                      speed="fast")

    def test_fallbacks_where_the_model_has_none(self):
        self._refused(model="claude-haiku-5-5", user_message="q",
                      fallbacks="default")

    def test_the_list_form_on_a_default_only_model(self):
        self._refused(model="claude-sonnet-5-5", user_message="q",
                      fallbacks=[{"model": "claude-sonnet-5"}])

    def test_a_fallbacks_value_that_is_neither_form(self):
        self._refused(user_message="q", fallbacks="opus")

    def test_an_unknown_budget_line(self):
        self._refused(user_message="q", line="treasury")

    def test_a_schema_that_is_not_an_object(self):
        self._refused(user_message="q", output_schema="json")

    def test_a_max_tokens_that_is_not_a_positive_int(self):
        for bad in (0, -1, True, "4000", 4000.0):
            self._refused(user_message="q", max_tokens=bad)

    def test_a_timeout_that_is_not_positive(self):
        for bad in (0, -5, "90"):
            self._refused(user_message="q", timeout_s=bad)

    def test_a_malformed_fallbacks_list(self):
        self._refused(user_message="q", fallbacks=[])
        self._refused(user_message="q", fallbacks=[{"name": "claude-opus-5"}])
        self._refused(user_message="q", fallbacks=["claude-opus-5"])
        self._refused(user_message="q", fallbacks=[{"model": 5}])


class RefusalReRunTests(TestCase):

    def test_the_re_run_carries_every_keyword(self):
        from ai_agents.providers.claude_provider import REFUSAL_FALLBACK_MODEL
        client = _Client(_response(text="", stop_reason="refusal",
                                   model="claude-sonnet-5-5"),
                         _response(model="claude-opus-5"))
        kw = dict(
            system_blocks=_blocks(("S", "1h")),
            shared_user_blocks=_blocks(("MK", "1h"), ("IN", "5m")),
            private_user_blocks=_blocks(("PS", None)),
            turn_effort="high", output_schema=SCHEMA, max_tokens=5000,
            fallbacks="default", timeout_s=90, task_budget=20_000)
        with patch("ai_agents.spend.can_spend", return_value=(True, "ok")), \
                self.assertLogs("ai_agents.providers.claude_provider",
                                level="WARNING"):
            _, usage = _provider(client).complete(
                "", "", model="claude-sonnet-5-5", effort="high",
                agent_name="probe", **kw)
        self.assertEqual(len(client.calls), 2)
        (_, first), (_, second) = client.calls
        self.assertEqual(second["model"], REFUSAL_FALLBACK_MODEL)
        for key in ("system", "messages", "output_config", "max_tokens",
                    "fallbacks", "timeout", "betas"):
            self.assertEqual(second[key], first[key], key)
        self.assertEqual(usage["model"], REFUSAL_FALLBACK_MODEL)

    def test_no_client_re_run_books_a_billed_failure(self):
        from ai_agents.models import AgentTask
        client = _Client(_response(text="", stop_reason="refusal"))
        with patch("ai_agents.spend.can_spend",
                   return_value=(True, "ok")) as asked:
            with self.assertRaises(RuntimeError) as ctx:
                _provider(client).complete(
                    "s", "q", model="claude-sonnet-5-5",
                    agent_name="orc", client_refusal_rerun=False)
        self.assertEqual(len(client.calls), 1)
        asked.assert_not_called()
        self.assertIn("declined", str(ctx.exception))
        self.assertGreater(ctx.exception.usage["cost_usd"], 0)
        row = AgentTask.objects.get()
        self.assertFalse(row.success)
        self.assertIn("declined", row.error)
        self.assertGreater(float(row.cost_usd), 0)

    @_budget(27.0)
    def test_the_fallback_gate_asks_the_callers_line(self):
        """_fallback_held(line=): a refusal on a balanced-tier model asks
        the deep tier's question on the caller's own line. The Orcs line
        is off in O0a, so an Orc-line re-run is held."""
        client = _Client(_response(text="", stop_reason="refusal"),
                         _response())
        from ai_agents import spend
        with patch.object(spend, "can_spend",
                          wraps=spend.can_spend) as asked:
            with self.assertRaises(RuntimeError) as ctx:
                _provider(client).complete(
                    "s", "q", model="claude-sonnet-5-5", agent_name="orc",
                    line="orcs")
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(asked.call_args.kwargs["line"], "orcs")
        self.assertEqual(asked.call_args.kwargs["tier"], "deep")
        self.assertIn("Orcs line is off", str(ctx.exception))

    def test_fallback_held_defaults_to_the_core_line(self):
        from ai_agents.providers.claude_provider import _fallback_held
        with patch("ai_agents.spend.can_spend",
                   return_value=(True, "ok")) as asked:
            self.assertEqual(_fallback_held("claude-sonnet-5",
                                            {"input_tokens": 100}), "")
        self.assertEqual(asked.call_args.kwargs["line"], "core")

    def test_without_cache_the_re_run_estimate_is_todays_to_the_bit(self):
        from ai_agents.catalog import pricing_for
        from ai_agents.providers.claude_provider import (
            REFUSAL_FALLBACK_MODEL, _fallback_held)
        with patch("ai_agents.spend.can_spend",
                   return_value=(True, "ok")) as asked:
            _fallback_held("claude-sonnet-5", {"input_tokens": 1234})
        self.assertEqual(
            asked.call_args.kwargs["estimated_usd"],
            1234 * pricing_for(REFUSAL_FALLBACK_MODEL)["input"] / 1_000_000)

    def test_the_re_run_estimate_prices_the_whole_prompt_as_fresh_writes(self):
        """input_tokens is only the uncached share. The fallback cannot
        read another model's cache, so the re-run pays the cached share
        again, as writes at the dearest TTL the request used."""
        from ai_agents.providers.claude_provider import _fallback_held
        usage = {"input_tokens": 1000, "cache_read_input_tokens": 20_000,
                 "cache_creation_input_tokens": 500}
        with patch("ai_agents.spend.can_spend",
                   return_value=(True, "ok")) as asked:
            _fallback_held("claude-sonnet-5-5", usage, write_x=2.0)
        # 21,500 tokens x $5/M (Opus 5's input) x 2 (1-hour writes).
        self.assertAlmostEqual(asked.call_args.kwargs["estimated_usd"],
                               0.215)

    def test_complete_passes_the_dearest_write_multiplier(self):
        """The TTLs of the request decide the multiplier: 2x with a 1-hour
        breakpoint, 1.25x with only 5-minute ones, 1x with none."""
        cases = (
            (dict(system_blocks=_blocks(("S", "1h")),
                  user_blocks=_blocks(("U", "5m"))), 2.0),
            (dict(system_blocks=_blocks(("S", "5m")), user_message="q"),
             1.25),
            (dict(system_prompt="s", user_message="q"), 1.0),
        )
        for layout, mult in cases:
            client = _Client(_response(
                text="", stop_reason="refusal",
                usage=_usage(input_tokens=1000, output_tokens=0,
                             cache_read_input_tokens=3000)))
            kw = {"system_prompt": "", "user_message": "", **layout}
            with patch("ai_agents.spend.can_spend",
                       return_value=(False, "held")) as asked:
                with self.assertRaises(RuntimeError):
                    _provider(client).complete(
                        kw.pop("system_prompt"), kw.pop("user_message"),
                        model="claude-sonnet-5-5", agent_name="probe", **kw)
            self.assertAlmostEqual(asked.call_args.kwargs["estimated_usd"],
                                   4000 * 5.0 * mult / 1e6, msg=mult)
            self.assertEqual(len(client.calls), 1)

    @_budget(0.10)
    def test_a_cached_refusal_is_not_re_run_on_a_line_it_would_overdraw(self):
        """Sonnet 5.5, a 20,000-token cached prefix (1-hour TTL) and a
        1,000-token private turn, declined, with $0.10 left on the line.
        The re-run costs about 21,000 x $5/M x 2 = $0.21, so it is held;
        priced on input_tokens alone ($0.005) it would have been sent."""
        from ai_agents.providers.claude_provider import REFUSAL_FALLBACK_MODEL
        client = _Client(
            _response(text="", stop_reason="refusal",
                      usage=_usage(input_tokens=1000, output_tokens=0,
                                   cache_read_input_tokens=20_000)),
            _response())
        with self.assertRaises(RuntimeError) as ctx:
            _provider(client).complete(
                "", "", model="claude-sonnet-5-5", agent_name="probe",
                system_blocks=_blocks(("S", "1h")),
                shared_user_blocks=_blocks(("MK", "1h")),
                private_user_blocks=_blocks(("PS", None)))
        self.assertEqual(len(client.calls), 1)
        self.assertIn(f"not re-run on {REFUSAL_FALLBACK_MODEL}",
                      str(ctx.exception))
        self.assertIn("($0.10 left)", str(ctx.exception))


class CostAndLedgerTests(TestCase):

    def _one(self, usage, model="claude-opus-5-5", **kw):
        client = _Client(_response(usage=usage, model=kw.pop(
            "served", None)))
        return _provider(client).complete("s", "q", model=model,
                                          agent_name="probe", **kw)

    def test_cache_aware_cost_from_the_ttl_split(self):
        from ai_agents.catalog import cost_usd
        _, usage = self._one(_usage(
            input_tokens=1000, output_tokens=300,
            cache_read_input_tokens=9000, cache_creation_input_tokens=5000,
            cache_creation=SimpleNamespace(ephemeral_5m_input_tokens=2000,
                                           ephemeral_1h_input_tokens=3000)))
        self.assertEqual(usage["cost_usd"], round(cost_usd(
            "claude-opus-5-5", input_tokens=1000, output_tokens=300,
            cache_read=9000, cache_write_5m=2000, cache_write_1h=3000), 6))
        self.assertEqual(usage["cache_read_input_tokens"], 9000)
        self.assertEqual(usage["cache_creation_input_tokens"], 5000)
        self.assertEqual(usage["cache_write_5m_tokens"], 2000)
        self.assertEqual(usage["cache_write_1h_tokens"], 3000)

    def test_without_the_split_the_dearest_ttl_used_is_billed(self):
        from ai_agents.catalog import cost_usd
        bare = dict(input_tokens=1000, output_tokens=300,
                    cache_creation_input_tokens=4000)
        client = _Client(_response(usage=_usage(**bare)))
        _, one_hour = _provider(client).complete(
            "", "q", model="claude-opus-5-5",
            system_blocks=_blocks(("S", "1h"), ("T", "5m")))
        self.assertEqual(one_hour["cache_write_1h_tokens"], 4000)
        self.assertEqual(one_hour["cost_usd"], round(cost_usd(
            "claude-opus-5-5", input_tokens=1000, output_tokens=300,
            cache_write_1h=4000), 6))
        client = _Client(_response(usage=_usage(**bare)))
        _, five_min = _provider(client).complete(
            "", "q", model="claude-opus-5-5",
            system_blocks=_blocks(("S", "5m")))
        self.assertEqual(five_min["cache_write_5m_tokens"], 4000)
        self.assertEqual(five_min["cache_write_1h_tokens"], 0)

    def test_a_magicmock_usage_is_zero_cache_and_todays_cost(self):
        from ai_agents.catalog import pricing_for
        _, usage = self._one(MagicMock(input_tokens=1000, output_tokens=500),
                             model="claude-opus-5")
        p = pricing_for("claude-opus-5")
        self.assertEqual(usage["cost_usd"],
                         round((1000 * p["input"] + 500 * p["output"]) / 1e6,
                               6))
        self.assertEqual(usage["cache_read_input_tokens"], 0)
        self.assertEqual(usage["cache_creation_input_tokens"], 0)

    def _iteration(self, kind, model, input_tokens, output_tokens):
        return SimpleNamespace(type=kind, model=model,
                               input_tokens=input_tokens,
                               output_tokens=output_tokens,
                               cache_read_input_tokens=0,
                               cache_creation_input_tokens=0,
                               cache_creation=None)

    def test_iterations_are_summed_at_each_models_price(self):
        """With fallbacks, usage.iterations is the per-attempt bill: the
        declined attempt at its model's price, the fallback at its own.
        The two cards differ (Opus 5.5 $4/$20, Opus 5 $5/$25), so pricing
        both at the asked model's card would give 0.0148, not 0.0173."""
        from ai_agents.models import AgentTask
        its = [self._iteration("message", "claude-opus-5-5", 1000, 40),
               self._iteration("fallback_message", "claude-opus-5", 1000,
                               300)]
        _, usage = self._one(_usage(input_tokens=1000, output_tokens=300,
                                    iterations=its),
                             model="claude-opus-5-5",
                             fallbacks=[{"model": "claude-opus-5"}],
                             served="claude-opus-5")
        want = (1000 * 4 + 40 * 20 + 1000 * 5 + 300 * 25) / 1e6
        self.assertAlmostEqual(want, 0.0173)
        self.assertEqual(usage["cost_usd"], round(want, 6))
        self.assertEqual((usage["input_tokens"], usage["output_tokens"]),
                         (2000, 340))
        row = AgentTask.objects.get()
        self.assertEqual(row.model, "claude-opus-5")
        self.assertEqual(row.structured_output,
                         {"asked_model": "claude-opus-5-5"})
        self.assertAlmostEqual(float(row.cost_usd), want)

    def test_an_uncatalogued_iteration_is_never_booked_below_a_card(self):
        """An attempt by a model the catalog does not price is booked at
        the dearer of the asked model's card and the unknown-model card
        ($3/$15), and said."""
        cases = (
            # Opus 5.5 ($4/$20) is dearer than $3/$15.
            ("claude-opus-5-5", (1000 * 4 + 300 * 20) / 1e6),
            # Sonnet 5.5 ($2/$10) is cheaper than $3/$15.
            ("claude-sonnet-5-5", (1000 * 3 + 300 * 15) / 1e6),
        )
        for asked, want in cases:
            its = [self._iteration("fallback_message",
                                   "claude-unlisted-9-20270101", 1000, 300)]
            with self.assertLogs("ai_agents.providers.claude_provider",
                                 level="WARNING") as logs:
                _, usage = self._one(_usage(input_tokens=1000,
                                            output_tokens=300,
                                            iterations=its),
                                     model=asked, fallbacks="default",
                                     served="claude-unlisted-9-20270101")
            self.assertEqual(usage["cost_usd"], round(want, 6), asked)
            self.assertIn("not in the catalog", "\n".join(logs.output))

    def test_a_dated_echo_with_fallbacks_and_no_iterations(self):
        """With fallbacks the echoed id is recorded, but a dated id the
        catalog does not list is priced at the asked model's card (Opus
        5.5, $4/$20: 0.008), never at the $3/$15 fallback (0.006)."""
        _, usage = self._one(_usage(input_tokens=1000, output_tokens=200),
                             model="claude-opus-5-5", fallbacks="default",
                             served="claude-opus-5-5-20261101")
        self.assertEqual(usage["cost_usd"], 0.008)
        self.assertEqual(usage["model"], "claude-opus-5-5-20261101")

    def test_the_served_model_is_recorded_only_with_fallbacks(self):
        from ai_agents.models import AgentTask
        _, usage = self._one(_usage(), model="claude-opus-5-5",
                             served="claude-opus-5-5-20261001")
        self.assertEqual(usage["model"], "claude-opus-5-5")
        self.assertEqual(AgentTask.objects.get().model, "claude-opus-5-5")
        AgentTask.objects.all().delete()
        _, usage = self._one(_usage(), model="claude-opus-5-5",
                             served="claude-opus-5", fallbacks="default",
                             source_ref="Orc:1:Wake:2")
        self.assertEqual(usage["model"], "claude-opus-5")
        row = AgentTask.objects.get()
        self.assertEqual(row.model, "claude-opus-5")
        self.assertEqual(row.structured_output,
                         {"source_ref": "Orc:1:Wake:2",
                          "asked_model": "claude-opus-5-5"})

    def test_the_duration_and_stop_reason_ride_in_the_usage(self):
        from ai_agents.models import AgentTask
        with patch("ai_agents.providers.claude_provider._monotonic",
                   side_effect=[10.0, 13.5]):
            _, usage = self._one(_usage())
        self.assertEqual(usage["duration_seconds"], 3.5)
        self.assertEqual(usage["stop_reason"], "end_turn")
        self.assertEqual(AgentTask.objects.get().duration_seconds, 3.5)

    def test_a_max_tokens_stop_is_returned_and_said(self):
        client = _Client(_response(text='{"action": "ho',
                                   stop_reason="max_tokens"))
        with self.assertLogs("ai_agents.providers.claude_provider",
                             level="WARNING"):
            _, usage = _provider(client).complete(
                "s", "q", model="claude-opus-5-5", max_tokens=1024)
        self.assertEqual(usage["stop_reason"], "max_tokens")

    def test_fast_mode_is_billed_at_the_fast_card(self):
        from ai_agents.catalog import cost_usd
        _, usage = self._one(_usage(input_tokens=1000, output_tokens=100),
                             speed="fast")
        self.assertEqual(usage["cost_usd"], round(cost_usd(
            "claude-opus-5-5", input_tokens=1000, output_tokens=100,
            speed="fast"), 6))

    def test_the_prompt_summary_reads_the_private_turn(self):
        from ai_agents.models import AgentTask
        client = _Client()
        _provider(client).complete(
            "", "", model="claude-opus-5-5",
            shared_user_blocks=_blocks(("the market day", "1h")),
            private_user_blocks=_blocks(("the position", None)))
        self.assertEqual(AgentTask.objects.get().prompt_summary,
                         "the position")


class CountTokensTests(TestCase):

    def test_count_tokens_sends_the_request_without_the_effort_message(self):
        client = _Client()
        n = _provider(client).count_tokens(
            model="claude-sonnet-5-5", system_blocks=_blocks(("S", "1h")),
            shared_user_blocks=_blocks(("MK", "1h")),
            private_user_blocks=_blocks(("PS", None)))
        self.assertEqual(n, 4321)
        kw = client.messages.count_tokens.call_args.kwargs
        self.assertEqual(kw["model"], "claude-sonnet-5-5")
        self.assertEqual([b["text"] for b in kw["system"]], ["S"])
        self.assertEqual([m["role"] for m in kw["messages"]],
                         ["user", "user"])
        client.messages.stream.assert_not_called()

    def test_count_tokens_of_a_plain_message(self):
        client = _Client()
        _provider(client).count_tokens(model="claude-haiku-5-5",
                                       user_message="hello")
        kw = client.messages.count_tokens.call_args.kwargs
        self.assertEqual(kw["messages"],
                         [{"role": "user", "content": "hello"}])
        self.assertNotIn("system", kw)

    def test_count_tokens_is_never_ledgered(self):
        from ai_agents.models import AgentTask
        _provider(_Client()).count_tokens(model="claude-haiku-5-5",
                                          user_message="hello")
        self.assertFalse(AgentTask.objects.exists())
