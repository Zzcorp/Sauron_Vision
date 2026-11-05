"""The provider's `max_attempts` (2026-11-05; the Orcs' O2 spec A.21, N4,
test T18).

`ClaudeProvider.complete()` sends the whole request again, once, after an
error whose text names `overloaded`, `internal_server_error` or
`api_error`, mid-stream ones included, and reads only the last attempt's
usage (`_MAX_ATTEMPTS` = 2). A cut attempt may still be billed, so one call
reserved at its bound could bill about twice that bound while the ledger
showed one. The keyword-only `max_attempts=1` sends a call once: an error
mid-stream ends it. `None`, the default, keeps `_MAX_ATTEMPTS`, so no caller
of today sees a difference (tests/test_claude_provider_bytes.py stays
green as it is). No caller passes the keyword in this commit; the Orcs'
gateway will pass 1.

A REAL anthropic client over a mock HTTP transport, as in
tests/test_claude_provider_bytes.py: the error is an `error` event in the
server-sent stream, after the message has started, which the SDK raises on
and never retries itself. No request leaves the process.

Run with:  python manage.py test tests.test_claude_provider_attempts
"""
import json
from unittest.mock import patch

from django.test import TestCase, override_settings

from tests.test_claude_provider_bytes import _BUDGET, _Wire, _sse

SLEEP = "ai_agents.providers.claude_provider.time.sleep"

#: The default's own words when both of its attempts bounce: unchanged.
TWO_BOUNCED = ("Anthropic is overloaded right now — 2 attempts all "
               "bounced. Try again in a minute.")

#: The default, left out and given: every caller of today.
DEFAULTS = ({}, {"max_attempts": None})


def _r0_model():
    """The model the Orcs' wakes are answered on (catalog.ORC_LADDER_V1's
    r0): the call that will pass max_attempts=1."""
    from ai_agents.catalog import ORC_LADDER_V1
    return {r["rung"]: r["model"] for r in ORC_LADDER_V1}["r0"]


def _cut(*, model, kind="overloaded_error", message="Overloaded"):
    """A stream that starts a message, writes a word of it, then carries
    an `error` event: the mid-stream error the SDK raises on (an
    APIStatusError whose text is the event's payload) and never retries."""
    events = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_cut", "type": "message", "role": "assistant",
            "model": model, "content": [], "stop_reason": None,
            "stop_sequence": None,
            "usage": {"input_tokens": 1000, "output_tokens": 1}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0,
                                 "content_block": {"type": "text",
                                                   "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                 "delta": {"type": "text_delta",
                                           "text": "half an ans"}}),
        ("error", {"type": "error", "error": {"type": kind,
                                              "message": message}}),
    ]
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n"
                   for name, data in events).encode()


def _declined(model):
    return _sse(model=model, text="", stop_reason="refusal", output_tokens=0)


def _rows():
    from ai_agents.models import AgentTask
    return list(AgentTask.objects.order_by("id"))


@override_settings(AI_CONFIG=_BUDGET)
class OneSendTests(TestCase):
    """max_attempts=1: the request is sent once, whatever happens to it."""

    def test_one_attempt_sends_once_after_a_mid_stream_overloaded_error(self):
        model = _r0_model()
        wire = _Wire(_cut(model=model), _sse(model=model, text="never read"))
        with patch(SLEEP) as slept:
            with self.assertRaises(RuntimeError) as ctx:
                wire.provider().complete(
                    "sys", "q", model=model, effort="low",
                    agent_name="attempts", max_attempts=1)
        self.assertEqual(len(wire.requests), 1, "the request was sent again")
        self.assertEqual(len(wire.answers), 1, "the second answer was asked")
        slept.assert_not_called()
        said = str(ctx.exception)
        self.assertIn("overloaded", said.lower())
        self.assertNotIn("2 attempts", said)
        self.assertNotIn("'type'", said, "the raw payload reaches no one")
        # The cut stream has no final usage: nothing is booked here, which
        # is why the Orcs hold the call's bound until a bill or 00:00 UTC.
        self.assertEqual(_rows(), [])

    def test_one_attempt_also_ends_on_an_api_error_mid_stream(self):
        model = _r0_model()
        for kind in ("api_error", "internal_server_error"):
            wire = _Wire(_cut(model=model, kind=kind, message="Internal"),
                         _sse(model=model, text="never read"))
            with patch(SLEEP) as slept:
                with self.assertRaises(Exception) as ctx:
                    wire.provider().complete(
                        "sys", "q", model=model, effort="low",
                        agent_name="attempts", max_attempts=1)
            self.assertIn(kind, str(ctx.exception), kind)
            self.assertEqual(len(wire.requests), 1, kind)
            slept.assert_not_called()

    def test_one_attempt_changes_nothing_on_the_wire(self):
        """The keyword never reaches the SDK: on a clean answer the body,
        the path and the headers are the default's, and so is the row."""
        model = _r0_model()
        sent = []
        for extra in ({}, {"max_attempts": 1}):
            wire = _Wire(_sse(model=model, text="ok"))
            text, usage = wire.provider().complete(
                "sys", "q", model=model, effort="low",
                agent_name="attempts", **extra)
            self.assertEqual(text, "ok")
            self.assertEqual(len(wire.requests), 1, extra)
            req = wire.requests[0]
            sent.append((req.url.path, str(req.url.query),
                         req.headers.get("anthropic-beta"), wire.body(),
                         usage["cost_usd"]))
        self.assertEqual(sent[0], sent[1])
        self.assertNotIn("max_attempts", json.dumps(sent[1][3]))
        self.assertEqual(len(_rows()), 2)

    def test_the_refusal_re_run_keeps_one_attempt(self):
        """A declined request re-runs once on the platform's fallback with
        every keyword as the caller gave it: max_attempts included, so the
        re-run is sent once too."""
        from ai_agents.providers.claude_provider import REFUSAL_FALLBACK_MODEL
        model = _r0_model()
        wire = _Wire(_declined(model), _cut(model=REFUSAL_FALLBACK_MODEL),
                     _sse(model=REFUSAL_FALLBACK_MODEL, text="never read"))
        with patch(SLEEP) as slept, \
                self.assertLogs("ai_agents.providers.claude_provider",
                                level="WARNING"):
            with self.assertRaises(RuntimeError):
                wire.provider().complete(
                    "sys", "q", model=model, effort="low",
                    agent_name="attempts", max_attempts=1)
        self.assertEqual(len(wire.requests), 2,
                         "the declined request and one send of its re-run")
        self.assertEqual(wire.body(1)["model"], REFUSAL_FALLBACK_MODEL)
        self.assertEqual(len(wire.answers), 1)
        slept.assert_not_called()
        # The declined generation is booked; the cut re-run has no usage.
        [declined] = _rows()
        self.assertFalse(declined.success)

    def test_attempts_outside_one_to_the_default_are_refused_unsent(self):
        """A caller may lower the attempts, never raise them: every attempt
        can be billed. Refused before anything is sent."""
        model = _r0_model()
        for bad in (0, -1, 3, True, 1.0, "1"):
            wire = _Wire(_sse(model=model))
            with self.assertRaises(ValueError, msg=repr(bad)):
                wire.provider().complete("sys", "q", model=model,
                                         agent_name="attempts",
                                         max_attempts=bad)
            self.assertEqual(wire.requests, [], repr(bad))
        self.assertEqual(_rows(), [])


@override_settings(AI_CONFIG=_BUDGET)
class TheDefaultKeepsTwoAttemptsTests(TestCase):
    """None, given or left out, is _MAX_ATTEMPTS: every caller of today."""

    def test_none_re_sends_the_whole_request_once(self):
        from ai_agents.providers.claude_provider import _MAX_ATTEMPTS
        self.assertEqual(_MAX_ATTEMPTS, 2)
        model = _r0_model()
        for extra in DEFAULTS:
            wire = _Wire(_cut(model=model),
                         _sse(model=model, text="after the retry"))
            with patch(SLEEP) as slept:
                text, _ = wire.provider().complete(
                    "sys", "q", model=model, effort="low",
                    agent_name="attempts", **extra)
            self.assertEqual(text, "after the retry", extra)
            self.assertEqual(len(wire.requests), 2, extra)
            self.assertEqual(wire.body(0), wire.body(1),
                             "the same request, sent whole again")
            slept.assert_called_once_with(2)
        # Only the last attempt's usage is read: one row per call, the
        # cut attempt unbooked (the double bill A.21 removes for the Orcs).
        self.assertEqual(len(_rows()), 2)

    def test_two_bounced_attempts_raise_the_default_words(self):
        model = _r0_model()
        for extra in DEFAULTS:
            wire = _Wire(_cut(model=model), _cut(model=model))
            with patch(SLEEP):
                with self.assertRaises(RuntimeError) as ctx:
                    wire.provider().complete("sys", "q", model=model,
                                             effort="low",
                                             agent_name="attempts", **extra)
            self.assertEqual(str(ctx.exception), TWO_BOUNCED, extra)
            self.assertEqual(len(wire.requests), 2, extra)

    def test_the_refusal_re_run_keeps_the_default_too(self):
        from ai_agents.providers.claude_provider import REFUSAL_FALLBACK_MODEL
        model = _r0_model()
        for extra in DEFAULTS:
            wire = _Wire(_declined(model), _cut(model=REFUSAL_FALLBACK_MODEL),
                         _sse(model=REFUSAL_FALLBACK_MODEL, text="answered"))
            with patch(SLEEP), \
                    self.assertLogs("ai_agents.providers.claude_provider",
                                    level="WARNING"):
                text, usage = wire.provider().complete(
                    "sys", "q", model=model, effort="low",
                    agent_name="attempts", **extra)
            self.assertEqual(text, "answered", extra)
            self.assertEqual(len(wire.requests), 3, extra)
            self.assertEqual(usage["model"], REFUSAL_FALLBACK_MODEL, extra)
