"""Model catalog + runtime model selection.

Run with:  python manage.py test tests.test_model_catalog
"""
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase


class CatalogTests(TestCase):
    def test_tier_defaults_are_all_in_the_catalog(self):
        """A tier pointing at an id not in the catalog means an unpriced (and
        possibly retired) model in production."""
        from ai_agents.catalog import MODELS, TIER_DEFAULTS
        for tier, model_id in TIER_DEFAULTS.items():
            self.assertIn(model_id, MODELS, f"{tier} default missing from catalog")

    def test_no_retired_model_ids_in_catalog(self):
        from ai_agents.catalog import MODELS
        retired = {"claude-sonnet-4-20250514", "claude-3-opus-20240229",
                   "claude-3-5-sonnet-20241022", "claude-3-7-sonnet-20250219"}
        self.assertEqual(set(MODELS) & retired, set())

    def test_every_catalog_model_has_pricing(self):
        from ai_agents.catalog import MODELS, pricing_for
        for model_id in MODELS:
            p = pricing_for(model_id)
            self.assertGreater(p["input"], 0)
            self.assertGreater(p["output"], 0)

    def test_unknown_model_prices_at_fallback_not_zero(self):
        from ai_agents.catalog import pricing_for
        p = pricing_for("some-unreleased-model")
        self.assertGreater(p["input"], 0)

    def test_effort_only_offered_for_supporting_models(self):
        from ai_agents.catalog import supports_effort
        self.assertTrue(supports_effort("claude-opus-5"))
        self.assertFalse(supports_effort("claude-haiku-4-5"))


class ResolutionTests(TestCase):
    def test_tier_resolves_to_a_catalog_model_without_override(self):
        from ai_agents.catalog import MODELS, resolve_tier
        self.assertIn(resolve_tier("deep"), MODELS)

    def test_db_tier_override_wins(self):
        from ai_agents.catalog import resolve_tier
        from ai_agents.models import AIModelSetting
        AIModelSetting.objects.create(scope="tier", key="fast",
                                       model_id="claude-sonnet-5")
        self.assertEqual(resolve_tier("fast"), "claude-sonnet-5")

    def test_agent_override_beats_tier(self):
        from ai_agents.catalog import resolve_agent
        from ai_agents.models import AIModelSetting
        AIModelSetting.objects.create(scope="tier", key="fast",
                                       model_id="claude-haiku-4-5")
        AIModelSetting.objects.create(scope="agent", key="news_analyst",
                                       model_id="claude-opus-5")
        self.assertEqual(resolve_agent("news_analyst", "fast"), "claude-opus-5")
        self.assertEqual(resolve_agent("other_agent", "fast"), "claude-haiku-4-5")

    def test_effort_falls_back_to_tier_default(self):
        from ai_agents.catalog import resolve_effort, TIER_EFFORT_DEFAULTS
        self.assertEqual(resolve_effort("claude-opus-5", "deep"),
                         TIER_EFFORT_DEFAULTS["deep"])

    def test_effort_is_none_for_models_without_support(self):
        from ai_agents.catalog import resolve_effort
        self.assertIsNone(resolve_effort("claude-haiku-4-5", "fast"))

    def test_agent_picks_up_override_at_construction(self):
        from ai_agents.models import AIModelSetting
        from ai_agents.agents.news_analyst import NewsAnalystAgent
        AIModelSetting.objects.create(scope="agent", key="news_analyst",
                                       model_id="claude-opus-5", effort="max")
        agent = NewsAnalystAgent()
        self.assertEqual(agent.model, "claude-opus-5")
        self.assertEqual(agent.effort, "max")


class ProviderTests(TestCase):
    @staticmethod
    def _client_returning(text="ok", input_tokens=10, output_tokens=5):
        block = MagicMock()
        block.type = "text"
        block.text = text
        client = MagicMock()
        # The provider streams (the SDK's ten-minute guard rejects big
        # non-streaming requests), so the mock mirrors the context-manager
        # shape: stream(...) -> __enter__ -> get_final_message().
        response = MagicMock(
            content=[block],
            usage=MagicMock(input_tokens=input_tokens,
                            output_tokens=output_tokens),
        )
        (client.messages.stream.return_value.__enter__
         .return_value.get_final_message.return_value) = response
        return client

    def test_effort_is_sent_only_for_supporting_models(self):
        from ai_agents.providers.claude_provider import ClaudeProvider

        provider = ClaudeProvider()
        client = self._client_returning()
        with patch.object(provider, "_get_client", return_value=client):
            provider.complete("sys", "msg", model="claude-opus-5", effort="high")
            self.assertEqual(
                client.messages.stream.call_args.kwargs["output_config"],
                {"effort": "high"})

            client.messages.stream.reset_mock()
            provider.complete("sys", "msg", model="claude-haiku-4-5", effort="high")
            self.assertNotIn("output_config",
                             client.messages.stream.call_args.kwargs)

    def test_cost_uses_catalog_pricing(self):
        from ai_agents.providers.claude_provider import ClaudeProvider

        provider = ClaudeProvider()
        client = self._client_returning(input_tokens=1_000_000, output_tokens=0)
        with patch.object(provider, "_get_client", return_value=client):
            _, usage = provider.complete("s", "m", model="claude-opus-5")
        self.assertEqual(usage["cost_usd"], 5.0)

    def test_overloaded_is_retried_then_succeeds(self):
        """529 Overloaded arrives as an error EVENT mid-stream, which the
        SDK does not retry — a live 'Generate now' click showed the raw
        payload to the operator. The provider now retries transients."""
        from ai_agents.providers.claude_provider import ClaudeProvider

        provider = ClaudeProvider()
        good = self._client_returning(text="recovered")
        boom = Exception("{'type': 'error', 'error': {'type': "
                         "'overloaded_error', 'message': 'Overloaded'}}")
        good.messages.stream.return_value.__enter__.side_effect = [
            boom, good.messages.stream.return_value.__enter__.return_value]
        with patch.object(provider, "_get_client", return_value=good), \
             patch("ai_agents.providers.claude_provider.time.sleep") as slept:
            text, _ = provider.complete("s", "m", model="claude-opus-5")
        self.assertEqual(text, "recovered")
        slept.assert_called_once_with(2)

    def test_overloaded_exhaustion_raises_a_human_message(self):
        from ai_agents.providers.claude_provider import ClaudeProvider

        provider = ClaudeProvider()
        client = self._client_returning()
        client.messages.stream.return_value.__enter__.side_effect = \
            Exception("{'type': 'overloaded_error', 'message': 'Overloaded'}")
        with patch.object(provider, "_get_client", return_value=client), \
             patch("ai_agents.providers.claude_provider.time.sleep"):
            with self.assertRaises(RuntimeError) as ctx:
                provider.complete("s", "m", model="claude-opus-5")
        self.assertIn("overloaded", str(ctx.exception).lower())
        self.assertNotIn("request_id", str(ctx.exception),
                         "the raw payload must not reach the operator")

    def test_a_non_transient_error_is_not_retried(self):
        from ai_agents.providers.claude_provider import ClaudeProvider

        provider = ClaudeProvider()
        client = self._client_returning()
        client.messages.stream.return_value.__enter__.side_effect = \
            Exception("invalid_request_error: max_tokens too large")
        with patch.object(provider, "_get_client", return_value=client), \
             patch("ai_agents.providers.claude_provider.time.sleep") as slept:
            with self.assertRaises(Exception):
                provider.complete("s", "m", model="claude-opus-5")
        slept.assert_not_called()
        self.assertEqual(client.messages.stream.call_count, 1)


class DashboardTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(
            username="mstaff", password="x", is_staff=True, is_superuser=True)

    def test_page_renders_for_staff(self):
        self.client.force_login(self.staff)
        r = self.client.get("/ai-models/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "AI MODEL SELECTION")

    def test_non_staff_is_redirected(self):
        User.objects.create_user(username="plain", password="x")
        self.client.login(username="plain", password="x")
        r = self.client.get("/ai-models/")
        self.assertIn(r.status_code, (302, 403))

    def test_post_sets_and_clears_an_override(self):
        from ai_agents.models import AIModelSetting
        self.client.force_login(self.staff)

        self.client.post("/ai-models/", {
            "scope": "tier", "key": "fast", "model_id": "claude-sonnet-5",
            "effort": "medium"})
        row = AIModelSetting.objects.get(scope="tier", key="fast")
        self.assertEqual(row.model_id, "claude-sonnet-5")
        self.assertEqual(row.updated_by, self.staff)

        self.client.post("/ai-models/", {
            "scope": "tier", "key": "fast", "model_id": "", "effort": ""})
        self.assertFalse(
            AIModelSetting.objects.filter(scope="tier", key="fast").exists())

    def test_unknown_model_is_rejected(self):
        from ai_agents.models import AIModelSetting
        self.client.force_login(self.staff)
        self.client.post("/ai-models/", {
            "scope": "tier", "key": "deep", "model_id": "gpt-9", "effort": ""})
        self.assertFalse(
            AIModelSetting.objects.filter(scope="tier", key="deep").exists())


# ── PR O0a: the cache prices, the two new models, the sourced card ──────────

class CachePricesAndNewModelsTests(TestCase):
    """The catalog prices every model's cache and knows Sonnet 5.5 and
    Haiku 5.5 (spec §7.5.8). Every number below was read on the pricing
    and prompt-caching pages on 2026-10-15 (the catalog names both)."""

    def test_prices_name_their_source_and_date(self):
        from ai_agents import catalog
        self.assertEqual(catalog.PRICING_SOURCE,
                         "https://platform.claude.com/docs/en/about-claude/pricing")
        self.assertEqual(
            catalog.CACHE_SOURCE,
            "https://platform.claude.com/docs/en/build-with-claude/prompt-caching")
        self.assertEqual(catalog.PRICES_READ_ON, "2026-10-15")
        self.assertEqual(catalog.CACHE_WRITE_5M_X, 1.25)
        self.assertEqual(catalog.CACHE_WRITE_1H_X, 2.0)

    def test_the_two_new_models(self):
        from ai_agents.catalog import MODELS, known_model, pricing_for
        self.assertTrue(known_model("claude-sonnet-5-5"))
        self.assertTrue(known_model("claude-haiku-5-5"))
        self.assertEqual(pricing_for("claude-sonnet-5-5"),
                         {"input": 2.0, "output": 10.0})
        self.assertEqual(pricing_for("claude-haiku-5-5"),
                         {"input": 0.10, "output": 0.50})
        s, h = MODELS["claude-sonnet-5-5"], MODELS["claude-haiku-5-5"]
        self.assertEqual((s["tier_hint"], s["context"], s["thinking"],
                          s["effort"], s["default_effort"]),
                         ("balanced", 1_000_000, True, True, "high"))
        self.assertEqual((h["tier_hint"], h["context"], h["thinking"],
                          h["effort"], h["default_effort"]),
                         ("fast", 1_000_000, True, True, "medium"))
        self.assertEqual(s["server_fallback"], "default")
        self.assertIsNone(h["server_fallback"])

    def test_every_model_carries_the_pages_cache_read_price(self):
        """Sonnet 5.5 is $0.10, not the $0.20 the spec's estimates used:
        the pricing page's footnote prices Opus 5.5 and Sonnet 5.5 cache
        hits at 0.05x their base input price."""
        from ai_agents.catalog import MODELS
        self.assertEqual({m: MODELS[m]["cache_read"] for m in MODELS}, {
            "claude-fable-5-1": 0.25,
            "claude-opus-5-5": 0.20,
            "claude-opus-5": 0.50,
            "claude-opus-4-8": 0.50,
            "claude-opus-4-7": 0.50,
            "claude-opus-4-6": 0.50,
            "claude-sonnet-5-5": 0.10,
            "claude-sonnet-5": 0.20,
            "claude-sonnet-4-6": 0.30,
            "claude-sonnet-4-5": 0.30,
            "claude-haiku-5-5": 0.01,
            "claude-haiku-4-5": 0.10,
            "claude-haiku-4-5-20251001": 0.10,
        })

    def test_minimum_cacheable_prefix_per_model(self):
        from ai_agents.catalog import MODELS, min_cache_tokens
        self.assertEqual({m: min_cache_tokens(m) for m in MODELS}, {
            "claude-fable-5-1": 512, "claude-opus-5-5": 512,
            "claude-opus-5": 512, "claude-opus-4-8": 1024,
            "claude-opus-4-7": 2048, "claude-opus-4-6": 4096,
            "claude-sonnet-5-5": 512, "claude-sonnet-5": 1024,
            "claude-sonnet-4-6": 1024, "claude-sonnet-4-5": 1024,
            "claude-haiku-5-5": 512, "claude-haiku-4-5": 4096,
            "claude-haiku-4-5-20251001": 4096,
        })

    def test_pricing_for_still_returns_exactly_input_and_output(self):
        """Four suites compare pricing_for's dict whole; the cache prices
        live beside it, never inside it."""
        from ai_agents.catalog import MODELS, pricing_for
        for m in list(MODELS) + ["some-unreleased-model"]:
            self.assertEqual(set(pricing_for(m)), {"input", "output"}, m)

    def test_cache_pricing_derives_the_writes_from_the_multipliers(self):
        from ai_agents.catalog import cache_pricing_for
        cases = {
            "claude-fable-5-1": (0.25, 12.50, 20.0),
            "claude-opus-5-5": (0.20, 5.0, 8.0),
            "claude-opus-5": (0.50, 6.25, 10.0),
            "claude-sonnet-5-5": (0.10, 2.50, 4.0),
            "claude-sonnet-5": (0.20, 2.50, 4.0),
            "claude-haiku-5-5": (0.01, 0.125, 0.20),
            "claude-haiku-4-5": (0.10, 1.25, 2.0),
            # Unknown: 0.1x / 1.25x / 2x of the $3 fallback.
            "some-unreleased-model": (0.30, 3.75, 6.0),
        }
        for m, (read, w5, w1h) in cases.items():
            p = cache_pricing_for(m)
            self.assertEqual(set(p), {"read", "write_5m", "write_1h"}, m)
            self.assertAlmostEqual(p["read"], read, places=9, msg=m)
            self.assertAlmostEqual(p["write_5m"], w5, places=9, msg=m)
            self.assertAlmostEqual(p["write_1h"], w1h, places=9, msg=m)

    def test_cost_at_zero_cache_is_bit_equal_to_todays_formula(self):
        """The provider priced (input x p_in + output x p_out) / 1e6; with
        no cache token the new function must return the SAME float, not a
        nearby one, for every model and for the unknown fallback."""
        from ai_agents.catalog import MODELS, cost_usd, pricing_for
        pairs = [(0, 0), (1, 1), (1000, 500), (12_345, 6_789),
                 (99_999, 31_999), (1_000_000, 0), (0, 1_000_000),
                 (150_000, 8_192)]
        for m in list(MODELS) + ["some-unreleased-model"]:
            p = pricing_for(m)
            for i, o in pairs:
                if m == "claude-haiku-5-5" and i > 100_000:
                    continue  # its long-context card, pinned below
                self.assertEqual(
                    cost_usd(m, input_tokens=i, output_tokens=o),
                    (i * p["input"] + o * p["output"]) / 1_000_000,
                    f"{m} {i}/{o}")

    def test_cache_terms_are_priced(self):
        from ai_agents.catalog import cost_usd
        got = cost_usd("claude-opus-5-5", input_tokens=1000,
                       output_tokens=100, cache_read=10_000,
                       cache_write_5m=2000, cache_write_1h=3000)
        want = (1000 * 4.0 + 100 * 20.0 + 10_000 * 0.20 + 2000 * 5.0
                + 3000 * 8.0) / 1e6
        self.assertAlmostEqual(got, want, places=12)

    def test_haiku_5_5_long_context_card(self):
        """Above 100,000 prompt tokens (input + cache reads + cache
        writes) Haiku 5.5 prices the whole request at $0.50/$2.50, reads
        $0.05, writes $0.625/$1.00."""
        from ai_agents.catalog import cost_usd
        at = cost_usd("claude-haiku-5-5", input_tokens=100_000,
                      output_tokens=1000)
        self.assertAlmostEqual(at, (100_000 * 0.10 + 1000 * 0.50) / 1e6)
        over = cost_usd("claude-haiku-5-5", input_tokens=100_001,
                        output_tokens=1000)
        self.assertAlmostEqual(over, (100_001 * 0.50 + 1000 * 2.50) / 1e6)
        mixed = cost_usd("claude-haiku-5-5", input_tokens=40_000,
                         output_tokens=1000, cache_read=50_000,
                         cache_write_5m=6_000, cache_write_1h=5_000)
        self.assertAlmostEqual(mixed, (40_000 * 0.50 + 1000 * 2.50
                                       + 50_000 * 0.05 + 6_000 * 0.625
                                       + 5_000 * 1.00) / 1e6)

    def test_fast_mode_pricing(self):
        from ai_agents.catalog import cost_usd, fast_pricing_for
        self.assertEqual(fast_pricing_for("claude-opus-5-5"),
                         {"input": 8.0, "output": 40.0})
        self.assertEqual(fast_pricing_for("claude-opus-5"),
                         {"input": 10.0, "output": 50.0})
        self.assertEqual(fast_pricing_for("claude-opus-4-8"),
                         {"input": 10.0, "output": 50.0})
        self.assertIsNone(fast_pricing_for("claude-opus-4-7"))
        self.assertIsNone(fast_pricing_for("claude-sonnet-5-5"))
        self.assertAlmostEqual(
            cost_usd("claude-opus-5-5", input_tokens=1_000_000,
                     output_tokens=1_000_000, speed="fast"), 48.0)
        # The caching multipliers apply on top of the fast price.
        self.assertAlmostEqual(
            cost_usd("claude-opus-5-5", input_tokens=0, output_tokens=0,
                     cache_read=1_000_000, cache_write_1h=1_000_000,
                     speed="fast"), 8.0 * 0.05 + 8.0 * 2.0)

    def test_capabilities_the_provider_validates_against(self):
        from ai_agents.catalog import (default_effort, server_fallback,
                                       supports_per_message_effort,
                                       supports_task_budget)
        for m in ("claude-fable-5-1", "claude-opus-5-5", "claude-opus-5",
                  "claude-sonnet-5-5", "claude-haiku-5-5"):
            self.assertTrue(supports_per_message_effort(m), m)
        for m in ("claude-sonnet-5", "claude-opus-4-8", "claude-haiku-4-5",
                  "some-unreleased-model"):
            self.assertFalse(supports_per_message_effort(m), m)
        self.assertTrue(supports_task_budget("claude-opus-5-5"))
        self.assertTrue(supports_task_budget("claude-sonnet-5-5"))
        self.assertFalse(supports_task_budget("claude-sonnet-5"))
        self.assertEqual(server_fallback("claude-opus-5-5"), "both")
        self.assertEqual(server_fallback("claude-fable-5-1"), "both")
        self.assertEqual(server_fallback("claude-sonnet-5-5"), "default")
        self.assertIsNone(server_fallback("claude-haiku-5-5"))
        self.assertIsNone(server_fallback("some-unreleased-model"))
        self.assertEqual(default_effort("claude-opus-5-5"), "medium")
        self.assertEqual(default_effort("claude-haiku-5-5"), "medium")
        self.assertEqual(default_effort("claude-sonnet-5-5"), "high")
        self.assertIsNone(default_effort("claude-haiku-4-5"))

    def test_the_tier_defaults_did_not_move(self):
        """O0a adds models; it moves no tier (the router reads its own
        pinned ladder from O2, never the resolver)."""
        from ai_agents.catalog import TIER_DEFAULTS, TIER_EFFORT_DEFAULTS
        self.assertEqual(TIER_DEFAULTS, {
            "fast": "claude-haiku-4-5", "balanced": "claude-sonnet-5",
            "deep": "claude-opus-5", "frontier": "claude-fable-5-1"})
        self.assertEqual(TIER_EFFORT_DEFAULTS, {
            "fast": "low", "balanced": "medium", "deep": "high",
            "frontier": "high"})

    def test_the_smoke_models_and_the_orc_ladder_are_catalog_ids(self):
        from ai_agents.catalog import (EFFORT_LEVELS, ORC_LADDER_V1, MODELS,
                                       SMOKE_MODELS, SMOKE_OPTIONAL)
        self.assertEqual(SMOKE_MODELS, ("claude-sonnet-5-5",
                                        "claude-opus-5-5",
                                        "claude-haiku-5-5"))
        self.assertEqual(SMOKE_OPTIONAL, ("claude-fable-5-1",))
        self.assertEqual([(r["rung"], r["model"], r["effort"])
                          for r in ORC_LADDER_V1], [
            ("h0", "claude-haiku-5-5", "low"),
            ("r0", "claude-sonnet-5-5", "low"),
            ("r1", "claude-sonnet-5-5", "high"),
            ("r2", "claude-opus-5-5", "medium"),
            ("r3", "claude-opus-5-5", "high"),
            ("r4", "claude-opus-5-5", "xhigh"),
            ("r5", "claude-fable-5-1", "max")])
        for r in ORC_LADDER_V1:
            self.assertIn(r["model"], MODELS)
            self.assertIn(r["effort"], EFFORT_LEVELS)


class NoModelIdOutsideTheCatalogTests(SimpleTestCase):
    """Hard rule of PR O0: a model id lives in ai_agents/catalog.py (and
    the AI_CONFIG env defaults in config/settings.py). The seven quoted
    ids that predate the rule are allowlisted by file and count, so a new
    one fails here."""

    ALLOWED = {
        ("ai_agents/agents/trade_debate.py", "claude-opus-5-5"): 1,
        ("ai_agents/consensus.py", "claude-haiku-4-5-20251001"): 2,
        ("ai_agents/providers/claude_provider.py", "claude-opus-5"): 1,
        ("ai_agents/providers/claude_provider.py", "claude-sonnet-5"): 1,
        ("dashboard/views.py", "claude-haiku-4-5-20251001"): 2,
    }

    # Not the platform's code: the tests, a virtualenv by any of the names
    # .gitignore gives one (the anthropic SDK itself quotes model ids),
    # any installed package, and the worktrees Claude Code keeps.
    SKIPPED_PREFIXES = ("tests/", "venv/", ".venv/", "env/", ".claude/",
                        "node_modules/")

    @classmethod
    def _scan(cls, repo):
        import re
        from collections import Counter
        pat = re.compile(r"""["'](claude-[a-z0-9][a-z0-9.\-]*)["']""")
        found = Counter()
        for p in repo.glob("**/*.py"):
            rel = p.relative_to(repo).as_posix()
            if (rel.startswith(cls.SKIPPED_PREFIXES)
                    or "site-packages/" in rel
                    or "/migrations/" in rel
                    or rel in ("ai_agents/catalog.py", "config/settings.py")):
                continue
            for m in pat.finditer(p.read_text(encoding="utf-8",
                                              errors="replace")):
                found[(rel, m.group(1))] += 1
        return found

    def test_no_model_id_literal_outside_the_catalog(self):
        from pathlib import Path
        repo = Path(__file__).resolve().parent.parent
        self.assertEqual(dict(self._scan(repo)), self.ALLOWED)

    def test_the_scan_skips_virtualenvs_and_installed_packages(self):
        """A checkout with an in-repo .venv/ or env/ (uv, python -m venv)
        holds the anthropic SDK, whose types quote model ids; the scan
        reads the platform's code only, and still sees a new literal."""
        import tempfile
        from pathlib import Path
        sdk = "anthropic/types/model.py"
        literal = 'MODEL = "claude-opus-5-5"\n'
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            for where in (".venv/lib/python3.11/site-packages/",
                          "env/lib/python3.11/site-packages/",
                          "venv/lib/python3.11/site-packages/",
                          "deploy/vendor/site-packages/"):
                f = repo / where / sdk
                f.parent.mkdir(parents=True)
                f.write_text(literal)
            # A virtualenv's own scripts, outside site-packages.
            for where in (".venv/bin/activate_this.py", "env/bin/tool.py"):
                f = repo / where
                f.parent.mkdir(parents=True)
                f.write_text(literal)
            app = repo / "ai_agents" / "agents" / "new_agent.py"
            app.parent.mkdir(parents=True)
            app.write_text(literal)
            self.assertEqual(dict(self._scan(repo)), {
                ("ai_agents/agents/new_agent.py", "claude-opus-5-5"): 1})
