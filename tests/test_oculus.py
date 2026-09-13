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


class TheBookIsPerViewerAndNeverPooledTests(TestCase):
    """THE BOOK — the one panel on this page that is not platform-wide.

    Every other cycle counts the whole platform, which is the right grain
    for a machine. Capital is not: it belongs to a user, and a book pooled
    across users is a number nobody can act on. So the panel appears only
    when a viewer is known, and the page says so in its caveat — a reader
    who takes it for a fleet total misreads every figure in it.

    Live and paper stand in two columns and are never added. That rule is
    not this page's invention: persona_mix._venue_ok RAISES rather than
    accept a pooled venue, capital_desk.budget_for applies the drawdown
    governor to the live venue only, and portfolio.services.capital_summary
    says why at the dict that produces the split.
    """

    def setUp(self):
        from decimal import Decimal

        from bot_program.models import AssetBotConfig
        self.user = User.objects.create_user("book_u", password="x")
        for name, mode, capital in (("live-pool", "live", "1000"),
                                    ("paper-pool", "paper", "4000")):
            AssetBotConfig.objects.create(
                user=self.user, asset_class="crypto", name=name, enabled=True,
                mode=mode, symbols=[], capital=Decimal(capital),
                base_currency="USD")

    def _book(self, data):
        return next((c for c in data["cycles"] if c["key"] == "book"), None)

    def test_a_viewer_gets_the_book(self):
        self.assertIsNotNone(self._book(oculus(user=self.user)))

    def test_no_viewer_means_no_book_rather_than_a_pooled_one(self):
        """A system or anonymous caller must not be handed someone's money,
        and must not be handed everyone's money added together either."""
        self.assertIsNone(self._book(oculus()))
        self.assertIsNone(self._book(oculus(user=None)))

    def test_it_carries_two_venues_and_keeps_them_apart(self):
        book = self._book(oculus(user=self.user))
        venues = [v["venue"] for v in book["venues"]]
        self.assertEqual(venues, ["live", "paper"])
        # No fact on the panel is a sum of the two columns.
        self.assertEqual(book["facts"], [],
                         "a flat fact on the book panel would sit outside "
                         "both columns and read as a total")

    def test_the_drawdown_governor_is_a_live_only_fact(self):
        """A drawdown brake on a simulation would throttle a book that
        cannot lose anything. capital_desk says so: 'paper venue — no
        drawdown governor'."""
        book = self._book(oculus(user=self.user))
        by_venue = {v["venue"]: [f["label"] for f in v["facts"]]
                    for v in book["venues"]}
        self.assertTrue(any("gouverneur" in l for l in by_venue["live"]))
        self.assertFalse(any("gouverneur" in l for l in by_venue["paper"]))

    def test_the_governor_says_that_100_is_ambiguous(self):
        """1.00 means EITHER no drawdown OR no equity reading at all, and an
        operator acts differently on each."""
        book = self._book(oculus(user=self.user))
        live = next(v for v in book["venues"] if v["venue"] == "live")
        gov = next(f for f in live["facts"] if "gouverneur" in f["label"])
        self.assertIn("DEUX", gov["qualifier"])

    def test_the_caveat_says_the_panel_is_yours_and_not_the_fleet(self):
        book = self._book(oculus(user=self.user))
        self.assertIn("VOUS", book["caveat"])
        self.assertIn("jamais additionnés", book["caveat"])

    def test_a_venue_that_cannot_be_read_costs_only_itself(self):
        """One unreadable column must not take the other, nor the page."""
        from dashboard import oculus as mod

        original = mod._venue_facts

        def _half(user, venue):
            if venue == "live":
                raise RuntimeError("broker table mid-migration")
            return original(user, venue)

        mod._venue_facts = _half
        try:
            book = self._book(oculus(user=self.user))
        finally:
            mod._venue_facts = original

        by_venue = {v["venue"]: v["facts"] for v in book["venues"]}
        self.assertEqual(by_venue["live"], [])
        self.assertTrue(by_venue["paper"])


class TheExpectancyGapIsRenderedHonestlyTests(TestCase):
    """`bot_grading.paper_live_expectancy_gap` ends its docstring with
    "Nothing in the decision path consumes this yet — exposed so a
    dashboard or the promotion ladder can pick it up". This is that
    dashboard.

    Its contract is the interesting part: `gap` is None whenever EITHER
    venue has no closed trade, "because a gap against an unmeasured venue
    is not a small gap, it is no measurement at all". The page must render
    that None as an em dash and never as 0.00, which would read as "live
    matched paper exactly" — the most flattering possible lie.
    """

    def setUp(self):
        self.user = User.objects.create_user("gap_u", password="x")

    def test_the_page_renders_a_none_gap_as_a_dash(self):
        import html as _html

        from dashboard import oculus as mod
        original = mod._cycle_book

        def _seeded(user):
            cycle = original(user)
            cycle["gaps"] = [{
                "rule": "only_ever_paper", "asset_class": "crypto",
                "n_paper": 12, "n_live": 0,
                "paper": 0.42, "live": None, "gap": None,
            }]
            return cycle

        mod._cycle_book = _seeded
        try:
            self.client.force_login(self.user)
            body = _html.unescape(
                self.client.get(reverse("oculus_dashboard")).content.decode())
        finally:
            mod._cycle_book = original

        self.assertIn("only_ever_paper", body)
        row = body[body.index("only_ever_paper"):]
        row = row[:row.index("</tr>")]
        self.assertIn("—", row)
        self.assertNotIn("0.00", row,
                         "a None gap rendered as 0.00 reads as 'live matched "
                         "paper exactly', which is the most flattering lie "
                         "this table could tell")

    def test_the_page_explains_which_direction_is_normal(self):
        """A negative gap is the NORMAL direction — the simulated fill never
        suffers a queue, a gap through the stop or a partial. Without that
        sentence an operator reads every red number as a broken rule.

        The explanation lives WITH the table and not above it, so a book
        with nothing to compare shows neither. That is deliberate: a legend
        for an absent table is noise, and this test seeds a row rather than
        asserting the sentence is always on the page."""
        import html as _html

        from dashboard import oculus as mod
        original = mod._cycle_book

        def _seeded(user):
            cycle = original(user)
            cycle["gaps"] = [{
                "rule": "ate_its_edge", "asset_class": "forex",
                "n_paper": 30, "n_live": 14,
                "paper": 0.31, "live": -0.05, "gap": -0.36,
            }]
            return cycle

        mod._cycle_book = _seeded
        try:
            self.client.force_login(self.user)
            body = _html.unescape(
                self.client.get(reverse("oculus_dashboard")).content.decode())
        finally:
            mod._cycle_book = original

        self.assertIn("Négatif est la direction normale", body)
        # And the distinction that decides what the operator does about it.
        self.assertIn("plus petit que ses coûts", body)


class EveryCycleOffersAWayIntoItTests(TestCase):
    """LA MACHINE — the panels became doors (2026-09-13).

    A panel that reports a count and offers no way into it is a report,
    not a command post: the operator reads "12 setups blind", nods, and
    still has to remember which of thirty pages explains why. That was
    the Oculus's own limit from the day it shipped.

    The drill-downs are the EXISTING pages, unchanged. The Oculus
    summarises; they answer. Several per cycle on purpose — the ladder is
    answered by three pages at three zooms, and allocation by three that
    size three different things. Collapsing them would repeat the defect
    the rail already fixed once, where one row named "allocator" hid a
    second page sizing something else entirely.
    """

    def test_every_cycle_carries_at_least_one_way_out(self):
        for cycle in oculus()["cycles"]:
            self.assertTrue(
                cycle.get("pages"),
                f"cycle {cycle['key']!r} is a dead end — it reports a count "
                f"and names no page that explains it")

    def test_every_destination_reverses(self):
        """Names, never paths: a hard-coded '/setups/' survives a route
        rename and 404s in silence."""
        from django.urls import NoReverseMatch, reverse

        from dashboard.oculus import CYCLE_PAGES
        for key, pages in CYCLE_PAGES.items():
            for name, label in pages:
                with self.subTest(cycle=key, page=name):
                    self.assertTrue(label, "a link with no label is a dot")
                    try:
                        reverse(name)
                    except NoReverseMatch:  # pragma: no cover
                        self.fail(f"cycle {key!r} links to {name!r}, which "
                                  f"reverses to nothing")

    def test_a_renamed_route_costs_one_link_and_not_the_page(self):
        """The page must survive a route it can no longer resolve. Losing a
        link is a smaller failure than losing the ten panels."""
        from dashboard import oculus as mod

        original = dict(mod.CYCLE_PAGES)
        mod.CYCLE_PAGES = {**original,
                           "gates": original["gates"] + [("gone_away", "Gone")]}
        try:
            data = oculus()
        finally:
            mod.CYCLE_PAGES = original

        gates = next(c for c in data["cycles"] if c["key"] == "gates")
        names = [p["name"] for p in gates["pages"]]
        self.assertNotIn("gone_away", names)
        self.assertIn("ops_dashboard", names)

    def test_the_links_reach_the_page(self):
        import html as _html
        user = User.objects.create_user("out_u", password="x")
        self.client.force_login(user)
        body = _html.unescape(
            self.client.get(reverse("oculus_dashboard")).content.decode())
        for href in ("/setups/", "/promotions/", "/evidence/", "/ops/"):
            self.assertIn(f'href="{href}"', body,
                          f"{href} is in the map and not on the page")

    def test_no_cycle_points_at_itself(self):
        """/oculus/ among its own drill-downs would be a loop, and a loop
        reads as 'there is nowhere further to go'."""
        from dashboard.oculus import CYCLE_PAGES
        for key, pages in CYCLE_PAGES.items():
            self.assertNotIn("oculus_dashboard", [n for n, _l in pages],
                             f"cycle {key!r} links back to the Oculus")
