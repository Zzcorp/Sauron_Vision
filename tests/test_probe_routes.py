"""probe_routes: the measurement behind "are all the pages operational?"

305 URL patterns, 277 named routes, 34 touched by any test, 243 never. The
suite proves the consistency of what it covers and cannot see a page that
renders 500 — on 2026-09-13 two pages answered 404 for a day and were found
by probing the public site from outside. This command is that probe, from
inside, in three states, with the buckets it does NOT probe counted rather
than hidden.
"""
from io import StringIO
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase, override_settings


def _run(*args):
    out = StringIO()
    call_command("probe_routes", *args, stdout=out)
    return out.getvalue()


class TheWalkIsComplete(TestCase):

    def test_every_pattern_lands_in_exactly_one_of_probeable_or_skipped(self):
        from core.management.commands.probe_routes import free_routes
        rows = free_routes()
        self.assertGreater(len(rows), 250, len(rows))
        probeable = [r for r in rows if r[2]]
        skipped = [r for r in rows if not r[2]]
        self.assertGreater(len(probeable), 200)
        self.assertGreater(len(skipped), 20)
        for _name, route, ok in skipped:
            self.assertTrue("<" in route or "(" in route, route)

    def test_a_mutating_name_is_excluded_and_listed(self):
        from core.management.commands.probe_routes import MUTATING
        for name in ("hq_run_asset_bot", "bot_toggle", "hq_save_etoro",
                     "flatten_all_positions", "kill_switch_api", "logout",
                     "close_position_execute", "asset_trade_preview"):
            self.assertTrue(MUTATING.search(name), name)
        for name in ("brokers_page", "treasury", "oculus", "system_health"):
            self.assertFalse(MUTATING.search(name), name)


class TheThreeStates(TestCase):

    def setUp(self):
        cache.delete("forge:route_probe")

    @override_settings(ALLOWED_HOSTS=[])
    def test_no_host_is_could_not_probe_not_zero(self):
        body = _run()
        self.assertIn("COULD NOT PROBE", body)
        self.assertIn("ALLOWED_HOSTS", body)
        self.assertEqual(cache.get("forge:route_probe")["state"], "could_not")

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_no_superuser_is_could_not_probe(self):
        User.objects.filter(is_superuser=True).delete()
        body = _run()
        self.assertIn("no active superuser", body)
        self.assertEqual(cache.get("forge:route_probe")["state"], "could_not")

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_a_run_stores_counts_the_forge_can_read(self):
        User.objects.create_superuser("probe_su", "p@x", "x")
        body = _run()
        self.assertIn("ROUTE PROBE", body)
        stored = cache.get("forge:route_probe")
        self.assertEqual(stored["state"], "ran")
        self.assertEqual(stored["as"], "probe_su")
        counts = stored["counts"]
        for k in ("ok", "forbidden", "missing", "broken", "skipped",
                  "excluded"):
            self.assertIn(k, counts)
        self.assertGreater(counts["ok"], 100, counts)
        self.assertGreater(counts["excluded"], 50, counts)
        self.assertGreater(counts["skipped"], 20, counts)

    @override_settings(ALLOWED_HOSTS=["testserver"])
    def test_no_probed_page_raises_or_is_missing(self):
        """The assertion this whole command exists to make. If it goes red,
        a page broke, and the output names it."""
        User.objects.create_superuser("probe_su2", "p@x", "x")
        body = _run()
        stored = cache.get("forge:route_probe")
        self.assertEqual(stored["counts"]["broken"], 0,
                         "broken: " + ", ".join(stored["broken"]))
        self.assertEqual(stored["counts"]["missing"], 0,
                         "missing: " + ", ".join(stored["missing"]))
        self.assertIn("answers.", body)


class TheForgeReadsIt(TestCase):

    def setUp(self):
        cache.delete("forge:route_probe")

    def test_never_run_is_a_dash_not_a_zero(self):
        from dashboard.oculus import _cycle_forge
        facts = {f["label"]: f["value"] for f in _cycle_forge()["facts"]}
        self.assertIn("pages that raise, at the last probe", facts)
        self.assertIsNone(facts["pages that raise, at the last probe"])

    def test_a_stored_probe_becomes_counts(self):
        from dashboard.oculus import _cycle_forge
        cache.set("forge:route_probe", {
            "state": "ran", "at": 0, "host": "h", "as": "u",
            "counts": {"ok": 200, "forbidden": 1, "missing": 2, "broken": 3,
                       "skipped": 30, "excluded": 80},
            "missing": ["a", "b"], "broken": ["c", "d", "e"]}, 60)
        facts = {f["label"]: f["value"] for f in _cycle_forge()["facts"]}
        self.assertEqual(facts["pages that raise, at the last probe"], 3)
        self.assertEqual(facts["pages answering 404, at the last probe"], 2)


class TheOpsLaneKnowsIt(TestCase):

    def test_it_is_registered_read_only_and_runnable(self):
        from core import ops_commands
        e = ops_commands.get("probe_routes")
        self.assertIsNotNone(e)
        self.assertTrue(e["read_only"])
        self.assertEqual(e["category"], "read")
        self.assertIn("probe_routes", ops_commands.runnable_names())


class TheFirstThingTheProbeFound(TestCase):
    """dashboard.views.ai_chat_stream imported StreamingHttpResponse and
    not JsonResponse, so its two refusals — empty message, no API key —
    raised NameError and answered 500. probe_routes found it on its first
    run; nothing else had ever visited the page. Both refusals are pinned
    here, and neither reaches the network."""

    def setUp(self):
        self.u = User.objects.create_user("chat", "c@x", "x")
        self.client.force_login(self.u)

    def test_an_empty_message_is_refused_with_json_not_a_raise(self):
        r = self.client.get("/api/ai-chat/stream/")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["error"], "Empty message")

    def test_a_missing_key_is_refused_with_json_not_a_raise(self):
        import os
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
            r = self.client.get("/api/ai-chat/stream/", {"message": "hi"})
        self.assertEqual(r.status_code, 500)
        self.assertEqual(r.json()["error"], "API key not configured")
