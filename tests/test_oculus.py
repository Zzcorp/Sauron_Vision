"""THE OCULUS — the page above the other thirty (2026-09-13).

What is guarded here is not arithmetic. The Oculus does no arithmetic of
its own: it reads counts the subsystems already record. What can go
wrong is the READING, and this codebase has a documented history of it —
`core/wall_facts.py` exists because a public page published "667 tests
green" for roughly 1,250 tests, and `tests/test_the_wall.py` took fifteen
overclaims back out of one commit.

An overview multiplies that risk by ten, because putting ten cycles side
by side invites exactly the three mistakes these tests pin:

* rendering an unmeasured counter as 0, which reads as "measured, and
  nothing happened" when the truth is "nobody measured";
* printing a count without the switch behind it, so a number produced by
  a task nobody turned on reads as a fact about the market;
* printing a count without its qualifier, so "6 rules in research" reads
  as coverage when a research-stage rule can neither trade nor vote.

Run with:  python manage.py test tests.test_oculus
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from dashboard.oculus import UNMEASURED, oculus


def _base_html() -> str:
    return (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
        encoding="utf-8")


class OculusShapeTests(TestCase):

    def test_it_returns_every_cycle_and_never_raises(self):
        data = oculus()
        keys = [c["key"] for c in data["cycles"]]
        for expected in ("gates", "scan", "ladder", "signals", "evolution",
                         "personas", "allocation", "horizon", "backtests",
                         "trust"):
            self.assertIn(expected, keys)

    def test_a_broken_cycle_is_reported_dead_not_dropped(self):
        """A panel that vanishes reads as 'there is no such cycle' — a lie
        of omission the operator cannot see. A broken one must say so."""
        from dashboard import oculus as mod

        def _explode():
            raise RuntimeError("table is mid-migration")

        _explode.__name__ = "_cycle_boom"
        original = mod.BUILDERS
        mod.BUILDERS = original + (_explode,)
        try:
            data = oculus()
        finally:
            mod.BUILDERS = original

        dead = [c for c in data["cycles"] if c.get("dead")]
        self.assertEqual(len(dead), 1)
        self.assertIn("n'est pas un zéro", dead[0]["caveat"])
        self.assertIn("_cycle_boom", data["degraded"])

    def test_an_unreadable_counter_is_none_and_never_zero(self):
        """The whole point of the page. 0 means measured-and-nothing-
        happened; None means nobody could measure. An operator acts
        differently on each, so they must never collapse."""
        from dashboard.oculus import _fact

        def _boom():
            raise RuntimeError("no such table")

        self.assertIs(_fact("x", _boom)["value"], UNMEASURED)
        self.assertIsNone(UNMEASURED, "UNMEASURED must stay None — the "
                                      "template tests `value is None`")
        self.assertEqual(_fact("x", lambda: 0)["value"], 0)

    def test_every_fact_carries_a_label_and_a_tone(self):
        for cycle in oculus()["cycles"]:
            for fact in cycle["facts"]:
                self.assertTrue(fact["label"])
                self.assertIn(fact["tone"], ("plain", "caution", "inert"))

    def test_the_counts_that_read_backwards_carry_their_qualifier(self):
        """Three counts in this platform mean close to the opposite of
        what they look like. None of them may appear bare."""
        cycles = {c["key"]: c for c in oculus()["cycles"]}

        research = next(f for f in cycles["ladder"]["facts"]
                        if "recherche" in f["label"])
        self.assertTrue(research["qualifier"])
        self.assertIn("vote", research["qualifier"])
        self.assertEqual(research["tone"], "inert")

        shadow = next(f for f in cycles["allocation"]["facts"]
                      if "ombre" in f["label"])
        self.assertTrue(shadow["qualifier"])
        self.assertEqual(shadow["tone"], "inert")

        worn = [f for f in cycles["personas"]["facts"]
                if "dont réellement activées" in f["label"]]
        self.assertTrue(worn, "the enabled qualifier row is gone")
        for fact in worn:
            self.assertTrue(fact["qualifier"])

    def test_every_cycle_states_its_caveat(self):
        for cycle in oculus()["cycles"]:
            self.assertTrue(cycle["caveat"],
                            f"{cycle['key']} has no caveat — every cycle on "
                            f"this page has at least one way of misreading")

    def test_a_gate_with_no_row_is_reported_absent_not_on(self):
        """`is_component_enabled` returns False for a missing row, and on
        2026-09-13 three components turned out never to have had one. The
        page must distinguish off from absent, because the fix differs."""
        from dashboard.oculus import _gate

        gates = {g["key"]: g for g in _gate("definitely_not_a_component")}
        gate = gates["definitely_not_a_component"]
        self.assertFalse(gate["on"])
        self.assertFalse(gate["known"])

    def test_the_series_are_bucketed_on_creation_not_on_settlement(self):
        """completed_at / resolved_at / evaluated_at are NULL on exactly
        the rows a stalled cycle would show, so bucketing on them hides
        the stall — the one thing an evolution strip exists to reveal."""
        src = (Path(settings.BASE_DIR) / "dashboard" / "oculus.py").read_text(
            encoding="utf-8")
        for banned in ("_series(", ):
            self.assertIn(banned, src)
        for stamp in ('"completed_at"', '"resolved_at"', '"evaluated_at"',
                      '"applied_at"', '"graded_at"'):
            self.assertNotIn(f"_series({stamp}", src)
        # And every series call names a creation-shaped field.
        import re
        fields = re.findall(r"_series\([A-Za-z_]+,\s*\"([a-z_]+)\"", src)
        self.assertTrue(fields)
        for field in fields:
            self.assertIn(field, ("created_at", "scanned_at"),
                          f"_series buckets on {field!r}, which can be NULL "
                          f"on the rows that matter")

    def test_each_spark_is_scaled_to_itself(self):
        for cycle in oculus()["cycles"]:
            series = cycle.get("series") or []
            self.assertEqual(cycle["max_n"],
                             max((p["n"] for p in series), default=0))


class OculusPageTests(TestCase):

    def setUp(self):
        self.url = reverse("oculus_dashboard")
        self.user = User.objects.create_user("ocu_u", password="x")

    def test_it_needs_a_login(self):
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_it_renders(self):
        import html as _html
        self.client.force_login(self.user)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        # Django escapes the apostrophe to &#x27;, so compare unescaped —
        # four of these ten titles start with "L'".
        body = _html.unescape(resp.content.decode())
        for title in ("Les interrupteurs", "Le scan", "L'échelle de promotion",
                      "Les signaux", "L'évolution", "Les personnalités",
                      "L'allocation", "L'horizon", "Les backtests",
                      "La confiance"):
            self.assertIn(title, body)

    def test_the_page_explains_the_em_dash_rule_in_words(self):
        """A convention the reader cannot see is a convention that does not
        exist. The page states it rather than hoping it is inferred."""
        import html as _html
        self.client.force_login(self.user)
        body = _html.unescape(self.client.get(self.url).content.decode())
        self.assertIn("un tiret n'est pas un zéro", body)
        self.assertIn("non mesurable", body)

    def test_it_writes_nothing(self):
        """Read-only, like /shares/ and /personas/. A GET on an overview
        must never place an order, flip a switch or stamp a row."""
        from core.platform_control import PlatformComponent
        self.client.force_login(self.user)
        before = list(PlatformComponent.objects.values_list(
            "key", "is_enabled", "run_count"))
        self.client.get(self.url)
        after = list(PlatformComponent.objects.values_list(
            "key", "is_enabled", "run_count"))
        self.assertEqual(before, after)

    def test_the_view_module_holds_no_query_of_its_own(self):
        """The view assembles nothing: all counting lives in oculus.py
        behind its fences, so a new panel cannot bypass them."""
        src = (Path(settings.BASE_DIR) / "dashboard" / "views_oculus.py"
               ).read_text(encoding="utf-8")
        for orm in (".objects.", "annotate(", "aggregate("):
            self.assertNotIn(orm, src)


class OculusMarkTests(SimpleTestCase):

    def test_the_sidebar_row_exists_and_points_at_the_page(self):
        base = _base_html()
        self.assertIn("url 'oculus_dashboard'", base)
        self.assertIn("page_id == 'oculus'", base)

    def test_its_mark_is_used_nowhere_else(self):
        """The sidebar's convention: one glyph, one row. U+25CE was the
        obvious pick for an eye and Trade Forensics already holds it."""
        import re
        base = _base_html()
        icons = re.findall(r'<span class="icon">(.+?)</span>', base)
        self.assertEqual(icons.count("⦿"), 1,
                         "the Oculus mark U+29BF is not unique in the sidebar")
        self.assertGreater(icons.count("◎"), 0,
                           "U+25CE moved — recheck which glyph is free")
