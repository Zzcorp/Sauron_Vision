"""The default request, byte for byte (PR O0a's guarantee).

PR O0a gives `ClaudeProvider.complete()` keyword arguments for the Orcs:
cache blocks, a schema, a bound on max_tokens, server-side fallbacks, a
budget line. The spec's promise for that PR is that no caller of today
sees a difference: "default request bytes and behaviour identical (test);
ledger cost identical when cache tokens are 0" (spec §11, row O0a).

This file is that test. It was written first and run green against the
provider as it stood at 6d57b6e, before the keywords existed, so it pins
the old bytes rather than describing the new code. It drives a REAL
`anthropic.Anthropic` client over a mock HTTP transport, so what is
compared is the JSON body the SDK would put on the wire, the path and
the headers, not a MagicMock's recollection of keyword arguments. No
request ever leaves the process.

Run with:  python manage.py test tests.test_claude_provider_bytes
"""
import json
import os
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import TestCase, override_settings

# The SDK's own HTTP library, chosen by the SDK's major: 1.x and 2.x are
# built on httpx2, 0.x on httpx. Not by whether httpx2 imports: a 0.x
# install with httpx2 also present mis-picked it, and the client refused
# the mock transport (requirements.txt pins 2.x, tests.test_dependency_lock).
import anthropic as _anthropic

if int(_anthropic.__version__.split(".")[0]) >= 1:
    import httpx2 as httpx
else:  # pragma: no cover — depends on the installed SDK
    import httpx


def _sse(*, model, text="ok", stop_reason="end_turn", input_tokens=1000,
         output_tokens=500, usage_extra=None):
    """A canned server-sent-event stream of one assistant message."""
    usage = {"input_tokens": input_tokens, "output_tokens": 1}
    usage.update(usage_extra or {})
    events = [("message_start", {"type": "message_start", "message": {
        "id": "msg_test", "type": "message", "role": "assistant",
        "model": model, "content": [], "stop_reason": None,
        "stop_sequence": None, "usage": usage}})]
    if text:
        events += [
            ("content_block_start", {"type": "content_block_start",
                                     "index": 0, "content_block": {
                                         "type": "text", "text": ""}}),
            ("content_block_delta", {"type": "content_block_delta",
                                     "index": 0, "delta": {
                                         "type": "text_delta",
                                         "text": text}}),
            ("content_block_stop", {"type": "content_block_stop",
                                    "index": 0}),
        ]
    events += [
        ("message_delta", {"type": "message_delta",
                           "delta": {"stop_reason": stop_reason,
                                     "stop_sequence": None},
                           "usage": {"output_tokens": output_tokens}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n"
                   for name, data in events).encode()


class _Wire:
    """A real SDK client whose transport records each request and answers
    from a queue of canned streams."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.requests = []
        import anthropic
        # The API's own address, written here: left out, the SDK reads
        # ANTHROPIC_BASE_URL from the environment, and a proxy or gateway
        # setting would move the path this file pins.
        self.client = anthropic.Anthropic(
            api_key="test-key-not-real", max_retries=0,
            base_url="https://api.anthropic.com",
            http_client=httpx.Client(
                transport=httpx.MockTransport(self._handle)))

    def _handle(self, request):
        self.requests.append(request)
        body = self.answers.pop(0)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=body)

    def body(self, i=0):
        return json.loads(self.requests[i].content)

    def provider(self):
        from ai_agents.providers.claude_provider import ClaudeProvider
        p = ClaudeProvider()
        p.client = self.client
        return p


# The budget the refusal re-runs ask (_fallback_held), written here: never
# the AI_DAILY_BUDGET_USD / ORC_DAILY_BUDGET_USD of this process's
# environment (a box's .env), which could hold a re-run this file pins.
_BUDGET = {**settings.AI_CONFIG, "daily_budget_usd": 27.0,
           "orc_daily_budget_usd": 0.0}


@override_settings(AI_CONFIG=_BUDGET)
class DefaultRequestBytesTests(TestCase):
    """The bodies below are what the provider sent at 6d57b6e."""

    def _one(self, model, effort, answer_model=None):
        wire = _Wire(_sse(model=answer_model or model))
        text, usage = wire.provider().complete(
            "sys", "q", model=model, effort=effort, agent_name="golden")
        self.assertEqual(text, "ok")
        self.assertEqual(len(wire.requests), 1)
        return wire, usage

    def _plain_wire(self, wire, i=0):
        req = wire.requests[i]
        self.assertEqual(req.method, "POST")
        self.assertEqual(req.url.path, "/v1/messages")
        self.assertNotIn("beta", str(req.url.query),
                         "the default request never takes the beta path")
        self.assertNotIn("anthropic-beta", req.headers,
                         "the default request carries no beta header")

    def test_a_thinking_model_with_effort(self):
        wire, _ = self._one("claude-sonnet-5", "medium")
        self._plain_wire(wire)
        self.assertEqual(wire.body(), {
            "max_tokens": 32000,
            "messages": [{"role": "user", "content": "q"}],
            "model": "claude-sonnet-5",
            "output_config": {"effort": "medium"},
            "system": "sys",
            "stream": True,
        })

    def test_a_gateway_in_the_environment_does_not_move_the_golden(self):
        with patch.dict(os.environ, {
                "ANTHROPIC_BASE_URL": "https://gateway.example/anthropic"}):
            wire, _ = self._one("claude-sonnet-5", "medium")
        self._plain_wire(wire)
        self.assertEqual(wire.requests[0].url.host, "api.anthropic.com")

    def test_a_model_without_effort_or_thinking(self):
        wire, _ = self._one("claude-haiku-4-5", "medium")
        self._plain_wire(wire)
        self.assertEqual(wire.body(), {
            "max_tokens": 8192,
            "messages": [{"role": "user", "content": "q"}],
            "model": "claude-haiku-4-5",
            "system": "sys",
            "stream": True,
        })

    def test_the_deep_tier_default_with_high_effort(self):
        wire, _ = self._one("claude-opus-5", "high")
        self._plain_wire(wire)
        self.assertEqual(wire.body(), {
            "max_tokens": 32000,
            "messages": [{"role": "user", "content": "q"}],
            "model": "claude-opus-5",
            "output_config": {"effort": "high"},
            "system": "sys",
            "stream": True,
        })

    def test_no_effort_sends_no_output_config(self):
        wire, _ = self._one("claude-opus-5-5", None)
        self._plain_wire(wire)
        self.assertEqual(wire.body(), {
            "max_tokens": 32000,
            "messages": [{"role": "user", "content": "q"}],
            "model": "claude-opus-5-5",
            "system": "sys",
            "stream": True,
        })

    def test_the_refusal_re_run_sends_todays_opus_5_request(self):
        """A balanced-tier refusal asks the deep reserve, then re-runs once
        on claude-opus-5 with max_tokens recomputed for THAT model: the
        second body is exactly today's Opus 5 request."""
        wire = _Wire(_sse(model="claude-sonnet-5", text="",
                          stop_reason="refusal", output_tokens=0),
                     _sse(model="claude-opus-5", text="answered"))
        with self.assertLogs("ai_agents.providers.claude_provider",
                             level="WARNING"):
            text, usage = wire.provider().complete(
                "sys", "q", model="claude-sonnet-5", effort="medium",
                agent_name="golden")
        self.assertEqual(text, "answered")
        self.assertEqual(len(wire.requests), 2)
        for i in (0, 1):
            self._plain_wire(wire, i)
        self.assertEqual(wire.body(0)["model"], "claude-sonnet-5")
        self.assertEqual(wire.body(1), {
            "max_tokens": 32000,
            "messages": [{"role": "user", "content": "q"}],
            "model": "claude-opus-5",
            "output_config": {"effort": "medium"},
            "system": "sys",
            "stream": True,
        })
        self.assertEqual(usage["model"], "claude-opus-5")

    def test_a_non_thinking_refusal_re_runs_with_the_fallbacks_own_bound(self):
        """Haiku 4.5 sends 8,192 and no effort; its re-run on Opus 5 is
        sized for Opus 5 (32,000) and carries the effort the caller asked
        for, exactly as before."""
        wire = _Wire(_sse(model="claude-haiku-4-5", text="",
                          stop_reason="refusal", output_tokens=0),
                     _sse(model="claude-opus-5", text="answered"))
        with self.assertLogs("ai_agents.providers.claude_provider",
                             level="WARNING"):
            wire.provider().complete("sys", "q", model="claude-haiku-4-5",
                                     effort="low", agent_name="golden")
        self.assertEqual(wire.body(0)["max_tokens"], 8192)
        self.assertNotIn("output_config", wire.body(0))
        self.assertEqual(wire.body(1), {
            "max_tokens": 32000,
            "messages": [{"role": "user", "content": "q"}],
            "model": "claude-opus-5",
            "output_config": {"effort": "low"},
            "system": "sys",
            "stream": True,
        })


class DefaultLedgerTests(TestCase):
    """What a default call books: the same cost, model and columns."""

    def test_cost_and_row_are_todays_arithmetic(self):
        from ai_agents.catalog import pricing_for
        from ai_agents.models import AgentTask
        wire = _Wire(_sse(model="claude-opus-5", input_tokens=1234,
                          output_tokens=567))
        text, usage = wire.provider().complete(
            "sys", "the question", model="claude-opus-5", effort="high",
            agent_name="sauron_mind", source_ref="BrainReport:7")
        p = pricing_for("claude-opus-5")
        expected = round((1234 * p["input"] + 567 * p["output"]) / 1e6, 6)
        self.assertEqual(usage["input_tokens"], 1234)
        self.assertEqual(usage["output_tokens"], 567)
        self.assertEqual(usage["cost_usd"], expected)
        self.assertEqual(usage["model"], "claude-opus-5")
        row = AgentTask.objects.get()
        self.assertEqual(row.agent, "sauron_mind")
        self.assertEqual(row.provider, "claude")
        self.assertEqual(row.model, "claude-opus-5")
        self.assertEqual(row.prompt_summary, "the question")
        self.assertEqual(row.response_summary, "ok")
        self.assertEqual((row.input_tokens, row.output_tokens), (1234, 567))
        self.assertEqual(float(row.cost_usd), expected)
        self.assertEqual(row.structured_output,
                         {"source_ref": "BrainReport:7"})
        self.assertTrue(row.success)
        self.assertEqual(row.error, "")

    def test_a_dated_echo_of_an_alias_does_not_move_the_model_column(self):
        """The API may answer an alias with a dated snapshot id. A default
        call books the model it ASKED for, as it always has: recording the
        echo would split one model's spend across two ledger names."""
        from ai_agents.models import AgentTask
        wire = _Wire(_sse(model="claude-haiku-4-5-20251001"))
        _, usage = wire.provider().complete(
            "sys", "q", model="claude-haiku-4-5", agent_name="news_analyst")
        self.assertEqual(usage["model"], "claude-haiku-4-5")
        self.assertEqual(AgentTask.objects.get().model, "claude-haiku-4-5")

    def test_the_sdks_absent_cache_fields_cost_nothing(self):
        """The real SDK reports absent cache counters as None. A default
        call that reads them must price exactly the old two terms."""
        from ai_agents.catalog import pricing_for
        wire = _Wire(_sse(model="claude-sonnet-5", input_tokens=2000,
                          output_tokens=300))
        _, usage = wire.provider().complete("sys", "q",
                                            model="claude-sonnet-5")
        p = pricing_for("claude-sonnet-5")
        self.assertEqual(usage["cost_usd"],
                         round((2000 * p["input"] + 300 * p["output"]) / 1e6,
                               6))


class DefaultCallShapeTests(TestCase):
    """The MagicMock style the older tests use: the keyword arguments the
    provider hands the SDK on a default call are exactly today's set."""

    def test_the_sdk_receives_exactly_todays_keywords(self):
        from ai_agents.providers.claude_provider import ClaudeProvider
        block = MagicMock()
        block.type = "text"
        block.text = "ok"
        response = MagicMock(content=[block], usage=MagicMock(
            input_tokens=10, output_tokens=5))
        response.stop_reason = "end_turn"
        client = MagicMock()
        (client.messages.stream.return_value.__enter__
         .return_value.get_final_message.return_value) = response
        provider = ClaudeProvider()
        with patch.object(provider, "_get_client", return_value=client):
            provider.complete("sys", "msg", model="claude-opus-5",
                              effort="high")
        self.assertEqual(client.messages.stream.call_args.args, ())
        self.assertEqual(client.messages.stream.call_args.kwargs, {
            "model": "claude-opus-5",
            "max_tokens": 32000,
            "system": "sys",
            "messages": [{"role": "user", "content": "msg"}],
            "output_config": {"effort": "high"},
        })
        client.beta.messages.stream.assert_not_called()
