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


class TheProductionSettingsDoNotBlindIt(TestCase):
    """On the live box DEBUG is off, so SECURE_SSL_REDIRECT is on and
    SecurityMiddleware answers every plain-http request with a 301 to its
    https twin before any view runs — and 301 was a pass. The first cut of
    this command therefore reported ~270 "ok"s on the VPS that measured
    nothing (2026-09-28); the suite never saw it because .env.example says
    DEBUG=True and the redirect is decided at settings import. The probe
    now asks the way Caddy forwards — over https, X-Forwarded-Proto set —
    and a redirect to the https twin of the same path is a failure named
    for what it is, never an ok."""

    PROD = dict(DEBUG=False, SECURE_SSL_REDIRECT=True,
                SECURE_REDIRECT_EXEMPT=[r"^healthz/?$"],
                SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
                ALLOWED_HOSTS=["testserver"])

    def setUp(self):
        cache.delete("forge:route_probe")
        User.objects.create_superuser("probe_su3", "p@x", "x")

    def test_with_ssl_redirect_on_a_missing_page_is_still_found(self):
        from core.management.commands import probe_routes as pr
        routes = pr.free_routes() + [
            ("a_page_nobody_wired", "this-route-answers-nothing/", True)]
        with override_settings(**self.PROD), \
                mock.patch.object(pr, "free_routes", return_value=routes):
            body = _run()
        stored = cache.get("forge:route_probe")
        self.assertEqual(stored["state"], "ran")
        self.assertEqual(stored["missing"], ["a_page_nobody_wired"])
        self.assertEqual(stored["counts"]["broken"], 0,
                         "broken: " + ", ".join(stored["broken"]))
        self.assertGreater(stored["counts"]["ok"], 100, stored["counts"])
        self.assertIn("1 answer 404", body)

    def test_a_redirect_to_the_https_twin_is_a_failure_not_an_ok(self):
        from django.http import HttpResponsePermanentRedirect
        from core.management.commands import probe_routes as pr

        class Bounced:
            def get(self, path, **kw):
                return HttpResponsePermanentRedirect(
                    f"https://testserver{path}")

        with mock.patch.object(pr, "free_routes",
                               return_value=[("ops_dashboard", "ops/", True)]):
            tally = pr.probe(Bounced(), "testserver")
        self.assertEqual(tally["ok"], [])
        self.assertEqual(len(tally["broken"]), 1, tally)
        self.assertIn("ops_dashboard", tally["broken"][0])
        self.assertIn("redirected before the view ran", tally["broken"][0])

    def test_the_request_looks_like_the_one_caddy_forwards(self):
        from django.http import HttpResponse
        from core.management.commands import probe_routes as pr
        seen = []

        class Recorder:
            def get(self, path, **kw):
                seen.append(kw)
                return HttpResponse("")

        with mock.patch.object(pr, "free_routes",
                               return_value=[("ops_dashboard", "ops/", True)]):
            tally = pr.probe(Recorder(), "testserver")
        self.assertEqual(tally["ok"], ["ops_dashboard"])
        self.assertEqual(seen[0]["HTTP_HOST"], "testserver")
        self.assertTrue(seen[0]["secure"])
        self.assertEqual(seen[0]["HTTP_X_FORWARDED_PROTO"], "https")


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


class TheEndpointsTheProbeFirstFoundAreGone(TestCase):
    """dashboard.views.ai_chat_stream was the probe's first find
    (2026-09-23): it imported StreamingHttpResponse and not JsonResponse,
    so its two refusals raised NameError and answered 500, and nothing
    else had ever visited it. The two tests that pinned those refusals
    went with it on 2026-10-31, when it and ai_chat_api were removed: no
    page reached either (ai_chat_page redirects to /research/, and the
    template that called them was rendered by no view), and both posted to
    the Messages API by hand, outside the ledger and the daily budget, on
    a hardcoded Haiku 4.5 and anthropic-version 2023-06-01. The old chat
    page's URL still redirects, so a bookmark lands somewhere."""

    def setUp(self):
        self.u = User.objects.create_user("chat", "c@x", "x")
        self.client.force_login(self.u)

    def test_neither_endpoint_answers_any_more(self):
        import os
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test"}), \
                mock.patch("requests.post") as post:
            for url in ("/api/ai-chat/", "/api/ai-chat/stream/"):
                self.assertEqual(
                    self.client.get(url, {"message": "hi"}).status_code, 404,
                    url)
                self.assertEqual(self.client.post(
                    url, data='{"message": "hi"}',
                    content_type="application/json").status_code, 404, url)
        post.assert_not_called()

    def test_their_route_names_are_gone(self):
        from django.urls import NoReverseMatch, reverse
        for name in ("ai_chat_api", "ai_chat_stream"):
            with self.assertRaises(NoReverseMatch):
                reverse(name)

    def test_the_old_chat_page_still_redirects_to_research(self):
        from django.urls import reverse
        r = self.client.get("/ai/chat/")
        self.assertRedirects(r, reverse("research_view"),
                             fetch_redirect_response=False)
