"""The provider smoke (`manage.py claude_smoke`, PR O0a).

The two facts O1 and O2 lean on cannot be proved without the real API:
how many tokens the dossier is on each model's tokenizer, and whether an
effort-only system message between two user turns keeps the prompt cache
while it changes the effort of the turn after it, with structured outputs
on (spec §5.2a). The smoke is the operator's own measurement, run by hand
on the server, dry by default. These tests drive it with a fake client:
nothing here reaches the network and no key is needed.

Run with:  python manage.py test tests.test_claude_smoke
"""
import json
import os
from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

GOOD = json.dumps({"action": "hold", "level_id": "S4h-3",
                   "confidence": 0.6, "facts_cited": ["F3"],
                   "note": "structure holds above the 4h level"})
KEY = {"ANTHROPIC_API_KEY": "test-key-not-real"}


def _usage(out, read=0, w5=0, w1h=0, inp=6000):
    return SimpleNamespace(
        input_tokens=inp, output_tokens=out, cache_read_input_tokens=read,
        cache_creation_input_tokens=w5 + w1h,
        cache_creation=SimpleNamespace(ephemeral_5m_input_tokens=w5,
                                       ephemeral_1h_input_tokens=w1h))


def _resp(model, out, read=0, w5=0, w1h=0, text=GOOD, stop="end_turn"):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)] if text else [],
        stop_reason=stop, stop_details=None, model=model, id="msg",
        usage=_usage(out, read=read, w5=w5, w1h=w1h))


class _Stream:
    def __init__(self, r):
        self.r = r

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.r


class _Fake:
    """count_tokens answers by length; stream answers A (low) then B
    (xhigh) per model from `plan[model] = (resp_a, resp_b)`."""

    def __init__(self, plan=None):
        self.plan = plan or {}
        self.calls = []
        self.counts = []
        self.messages = MagicMock()
        self.beta = MagicMock()
        self.messages.count_tokens.side_effect = self._count
        self.messages.stream.side_effect = lambda **kw: self._stream(
            "plain", kw)
        self.beta.messages.stream.side_effect = lambda **kw: self._stream(
            "beta", kw)

    def _count(self, **kw):
        self.counts.append(kw)
        chars = len(json.dumps(kw.get("messages"))) + len(
            json.dumps(kw.get("system", "")))
        return SimpleNamespace(input_tokens=chars // 4)

    def _stream(self, path, kw):
        self.calls.append((path, kw))
        effort = kw["messages"][1]["output_config"]["effort"]
        a, b = self.plan.get(kw["model"]) or (
            _resp(kw["model"], 400, w5=2900, w1h=6800),
            _resp(kw["model"], 1600, read=9700))
        return _Stream(a if effort == "low" else b)


def _run(*args, fake=None, env=None):
    """The smoke under a budget written here, $27 and the Orcs' line off:
    never the AI_DAILY_BUDGET_USD / ORC_DAILY_BUDGET_USD of this process's
    environment (a box's .env), which would decide whether --yes runs."""
    out = StringIO()
    fake = fake or _Fake()
    budget = {**settings.AI_CONFIG, "daily_budget_usd": 27.0,
              "orc_daily_budget_usd": 0.0}
    with patch("ai_agents.providers.claude_provider.ClaudeProvider."
               "_get_client", return_value=fake), \
            patch.dict(os.environ, env or {}, clear=False), \
            override_settings(AI_CONFIG=budget):
        if env is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        call_command("claude_smoke", *args, stdout=out)
    return out.getvalue(), fake


class DryRunTests(TestCase):

    def test_dry_by_default_sends_nothing_and_needs_no_key(self):
        from ai_agents.catalog import SMOKE_MODELS
        from ai_agents.models import AgentTask
        text, fake = _run()
        self.assertEqual(fake.calls, [])
        self.assertEqual(fake.counts, [])
        self.assertFalse(AgentTask.objects.exists())
        for m in SMOKE_MODELS:
            self.assertIn(m, text)
        self.assertIn("DRY RUN", text)
        self.assertIn("anthropic SDK", text)
        self.assertIn("cost bound", text)
        self.assertIn("budget now:", text)
        self.assertIn("mid-conversation-output-config-2026-07-01", text)

    def test_with_fable_adds_the_optional_model(self):
        text, _ = _run("--with-fable")
        self.assertIn("claude-fable-5-1", text)

    def test_models_must_be_catalog_ids(self):
        with self.assertRaises(CommandError):
            _run("--models", "claude-sonnet-5-5,gpt-9")
        text, _ = _run("--models", "claude-haiku-5-5")
        self.assertIn("claude-haiku-5-5", text)
        self.assertNotIn("claude-opus-5-5", text)

    def test_the_dossier_is_deterministic_english_without_money(self):
        from ai_agents.management.commands.claude_smoke import build_dossier
        a, b = build_dossier(), build_dossier()
        self.assertEqual(a, b)
        blob = json.dumps(a)
        for banned in ("$", "€", "£", "USD", "EUR", "account"):
            self.assertNotIn(banned, blob)
        sizes = {k: sum(len(t) for t in v) if isinstance(v, list)
                 else len(v) for k, v in a.items()}
        # Sized like §5.2a at about four characters a token.
        for layer, tokens in (("S", 3050), ("MK", 3650), ("IN", 2830),
                              ("PS", 2650), ("tail", 3700)):
            self.assertAlmostEqual(sizes[layer] / 4, tokens,
                                   delta=tokens * 0.1, msg=layer)


class SendTests(TestCase):

    def test_yes_without_a_key_refuses(self):
        with self.assertRaises(CommandError) as ctx:
            _run("--yes")
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))

    def test_yes_refused_by_the_budget_sends_nothing(self):
        fake = _Fake()
        with patch("ai_agents.spend.can_spend",
                   return_value=(False, "daily AI budget spent")):
            with self.assertRaises(CommandError) as ctx:
                _run("--yes", fake=fake, env=KEY)
        self.assertIn("budget", str(ctx.exception))
        self.assertEqual(fake.calls, [])
        self.assertEqual(fake.counts, [])

    def test_the_request_layout(self):
        from ai_agents.catalog import MODELS, default_effort
        text, fake = _run("--yes", fake=_Fake(), env=KEY)
        self.assertIn("PASS", text)
        by_model = {}
        for path, kw in fake.calls:
            self.assertEqual(path, "beta")
            by_model.setdefault(kw["model"], []).append(kw)
        for model, (a, b) in by_model.items():
            self.assertIn("mid-conversation-output-config-2026-07-01",
                          a["betas"])
            self.assertNotIn("fallbacks", a)
            self.assertEqual([m["role"] for m in a["messages"]],
                             ["user", "system", "user"])
            self.assertEqual(a["messages"][1]["output_config"],
                             {"effort": "low"})
            self.assertEqual(b["messages"][1]["output_config"],
                             {"effort": "xhigh"})
            # B is A with only the effort-only message changed.
            self.assertEqual(a["system"], b["system"])
            self.assertEqual(a["messages"][0], b["messages"][0])
            self.assertEqual(a["messages"][2], b["messages"][2])
            self.assertEqual(a["output_config"], b["output_config"])
            self.assertEqual(a["output_config"]["effort"],
                             default_effort(model))
            self.assertEqual(a["output_config"]["format"]["type"],
                             "json_schema")
            self.assertEqual(
                a["max_tokens"],
                16000 if MODELS[model]["tier_hint"] in ("deep", "frontier")
                else 8000)
            ttls = [blk["cache_control"].get("ttl", "5m")
                    for blk in (a["system"] + a["messages"][0]["content"]
                                + a["messages"][2]["content"])
                    if "cache_control" in blk]
            self.assertLessEqual(len(ttls), 4)
            self.assertEqual(ttls, sorted(ttls, key=lambda t: t != "1h"),
                             "1h breakpoints before 5m ones")
            self.assertEqual(a["system"][-1]["cache_control"],
                             {"type": "ephemeral", "ttl": "1h"})
            shared = a["messages"][0]["content"]
            self.assertEqual(shared[-1]["cache_control"],
                             {"type": "ephemeral"})          # IN-slow, 5m
            self.assertEqual(shared[-2]["cache_control"],
                             {"type": "ephemeral", "ttl": "1h"})  # MK's last
            self.assertTrue(all("cache_control" not in blk
                                for blk in a["messages"][2]["content"]))

    def test_rows_are_booked_under_claude_smoke(self):
        from ai_agents.catalog import SMOKE_MODELS
        from ai_agents.models import AgentTask
        _run("--yes", fake=_Fake(), env=KEY)
        rows = AgentTask.objects.filter(agent="claude_smoke")
        self.assertEqual(rows.count(), 2 * len(SMOKE_MODELS))
        refs = sorted(r.structured_output["source_ref"] for r in rows)
        self.assertTrue(all(ref.startswith("Smoke:") for ref in refs))
        self.assertTrue(any(ref.endswith(":claude-opus-5-5:xhigh")
                            for ref in refs))

    def test_the_bound_is_asked_of_the_budget_whole(self):
        """Sonnet 5.5's bound, by hand: the dossier's characters / 4 x 1.35
        tokens, every one written at the 1-hour price (2x $2/M) on BOTH
        calls, plus 8,000 output tokens at $10/M on both."""
        from ai_agents import spend
        from ai_agents.management.commands.claude_smoke import (
            CHARS_PER_TOKEN, TOKENIZER_HEADROOM, _chars, build_dossier)
        chars = sum(_chars(v) for v in build_dossier().values())
        tokens = int(chars / CHARS_PER_TOKEN * TOKENIZER_HEADROOM) + 1
        want = 2 * (8000 * 10.0 + tokens * 2.0 * 2) / 1e6
        self.assertAlmostEqual(want, 0.3322, places=3)
        with patch.object(spend, "can_spend",
                          wraps=spend.can_spend) as asked:
            text, _ = _run("--models", "claude-sonnet-5-5")
        self.assertIn("cost bound $0.33", text)
        self.assertEqual(asked.call_args.kwargs["tier"], "deep")
        self.assertAlmostEqual(asked.call_args.kwargs["estimated_usd"],
                               want, places=6)

    def test_an_sdk_without_the_beta_path_sends_nothing(self):
        from ai_agents.management.commands.claude_smoke import Command
        fake = _Fake()
        with patch.object(Command, "_sdk",
                          return_value=("0.x", "no fallbacks")):
            with self.assertRaises(CommandError) as ctx:
                _run("--yes", fake=fake, env=KEY)
        self.assertIn("no fallbacks", str(ctx.exception))
        self.assertEqual(fake.calls, [])
        self.assertEqual(fake.counts, [])

    def test_the_whole_count_is_the_request_as_sent(self):
        """The sixth count per model is the whole §5.2a request: the
        system block and the two user turns, not the tail alone."""
        from ai_agents.catalog import SMOKE_MODELS
        fake = _Fake()
        _run("--yes", "--count-only", fake=fake, env=KEY)
        for i, model in enumerate(SMOKE_MODELS):
            whole = fake.counts[6 * i + 5]
            self.assertEqual(whole["model"], model)
            self.assertIn("system", whole)
            self.assertEqual(whole["system"][0]["cache_control"],
                             {"type": "ephemeral", "ttl": "1h"})
            self.assertEqual([m["role"] for m in whole["messages"]],
                             ["user", "user"])
            self.assertEqual(len(whole["messages"][0]["content"]), 5)
            self.assertEqual(len(whole["messages"][1]["content"]), 2)
            for layer in fake.counts[6 * i:6 * i + 5]:
                self.assertNotIn("system", layer)
                self.assertEqual(len(layer["messages"]), 1)

    def test_count_only_sends_no_message(self):
        from ai_agents.catalog import SMOKE_MODELS
        fake = _Fake()
        text, _ = _run("--yes", "--count-only", fake=fake, env=KEY)
        self.assertEqual(fake.calls, [])
        self.assertEqual(len(fake.counts), 6 * len(SMOKE_MODELS))
        self.assertIn("count_tokens", text)
        self.assertIn("x1.00 of claude-sonnet-5-5", text)


class VerdictTests(TestCase):
    """PASS needs all four; each failure is named and the command fails."""

    def _verdict(self, a, b, model="claude-sonnet-5-5"):
        fake = _Fake({model: (a, b)})
        return _run("--yes", "--models", model, fake=fake, env=KEY)

    def test_pass(self):
        text, _ = self._verdict(
            _resp("claude-sonnet-5-5", 500, w5=2900, w1h=6800),
            _resp("claude-sonnet-5-5", 1000, read=9700))
        self.assertIn("PASS", text)
        self.assertIn("smoke PASSED", text)

    def _fails(self, a, b, words):
        with self.assertRaises(CommandError) as ctx:
            self._verdict(a, b)
        self.assertIn("smoke FAILED", str(ctx.exception))
        self.assertIn(words, str(ctx.exception))

    def test_no_cache_read_on_b(self):
        self._fails(_resp("claude-sonnet-5-5", 500, w1h=9700),
                    _resp("claude-sonnet-5-5", 2000, w1h=9700),
                    "read no cache")

    def test_effort_did_not_govern(self):
        self._fails(_resp("claude-sonnet-5-5", 500, w1h=9700),
                    _resp("claude-sonnet-5-5", 999, read=9700),
                    "less than 2x")

    def test_a_truncated_answer(self):
        self._fails(_resp("claude-sonnet-5-5", 500, w1h=9700),
                    _resp("claude-sonnet-5-5", 8000, read=9700,
                          stop="max_tokens"),
                    "stop_reason max_tokens")

    def test_an_answer_off_the_schema(self):
        self._fails(_resp("claude-sonnet-5-5", 500, w1h=9700,
                          text='{"action": "buy"}'),
                    _resp("claude-sonnet-5-5", 2000, read=9700),
                    "schema")

    def test_a_refusal_is_a_failure_not_a_re_run(self):
        fake = _Fake({"claude-sonnet-5-5": (
            _resp("claude-sonnet-5-5", 0, text="", stop="refusal"),
            _resp("claude-sonnet-5-5", 2000, read=9700))})
        with self.assertRaises(CommandError) as ctx:
            _run("--yes", "--models", "claude-sonnet-5-5", fake=fake,
                 env=KEY)
        self.assertIn("declined", str(ctx.exception))
        self.assertEqual({kw["model"] for _, kw in fake.calls},
                         {"claude-sonnet-5-5"})
        # A failed call A is not followed by call B: one message sent.
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(
            fake.calls[0][1]["messages"][1]["output_config"],
            {"effort": "low"})
