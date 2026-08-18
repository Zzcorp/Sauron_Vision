"""Model catalog + runtime model selection.

Run with:  python manage.py test tests.test_model_catalog
"""
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase


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
