"""The guided platform tour — shown once per user (existing users
included: the flag is a nullable timestamp that starts null for
everyone), skippable, replayable from the user menu forever.

Run with:  python manage.py test tests.test_tour
"""
from django.contrib.auth.models import User
from django.template import Context, Template
from django.test import RequestFactory, TestCase


class TourFlagTests(TestCase):
    def test_new_profile_defaults_to_pending(self):
        from portfolio.trader_profile import get_or_create_profile
        u = User.objects.create_user("tour_u1")
        profile = get_or_create_profile(u)
        self.assertIsNone(profile.tour_completed_at,
                          "every user must see the tour once")

    def test_tour_pending_tag_is_false_for_anonymous(self):
        from django.contrib.auth.models import AnonymousUser
        req = RequestFactory().get("/")
        req.user = AnonymousUser()
        out = Template(
            "{% load sauron_tags %}{% tour_pending as t %}{{ t }}"
        ).render(Context({"request": req}))
        self.assertEqual(out.strip(), "False")

    def test_tour_pending_true_without_a_profile_row(self):
        """Profiles are created lazily — a brand new user has no row, and
        is exactly who the tour is for."""
        u = User.objects.create_user("tour_u2")
        req = RequestFactory().get("/")
        req.user = u
        out = Template(
            "{% load sauron_tags %}{% tour_pending as t %}{{ t }}"
        ).render(Context({"request": req}))
        self.assertEqual(out.strip(), "True")


class TourEndpointTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("tour_ep")

    def test_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get("/tour/complete/").status_code, 405)

    def test_requires_login(self):
        resp = self.client.post("/tour/complete/")
        self.assertEqual(resp.status_code, 302)

    def test_post_marks_complete_and_creates_the_profile(self):
        from portfolio.trader_profile import TraderProfile
        self.client.force_login(self.user)
        resp = self.client.post("/tour/complete/")
        self.assertEqual(resp.status_code, 200)
        profile = TraderProfile.objects.get(user=self.user)
        self.assertIsNotNone(profile.tour_completed_at)

    def test_post_is_idempotent(self):
        self.client.force_login(self.user)
        self.client.post("/tour/complete/")
        resp = self.client.post("/tour/complete/")
        self.assertEqual(resp.status_code, 200)


class TourPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("tour_pg")

    def setUp(self):
        self.client.force_login(self.user)

    def test_pending_user_gets_autostart(self):
        resp = self.client.get("/getting-started/")
        self.assertContains(resp, "autostart: true")
        self.assertContains(resp, 'id="svTourCard"')

    def test_completed_user_keeps_replay_but_not_autostart(self):
        from portfolio.trader_profile import get_or_create_profile
        from django.utils import timezone
        p = get_or_create_profile(self.user)
        p.tour_completed_at = timezone.now()
        p.save(update_fields=["tour_completed_at"])
        resp = self.client.get("/getting-started/")
        self.assertContains(resp, "autostart: false")
        self.assertContains(resp, "Platform Tour",
                            msg_prefix="the replay entry must stay forever")

    def test_step_anchor_targets_exist_in_the_chrome(self):
        """A chrome refactor that renames a tour anchor must fail CI, not
        silently skip half the walk."""
        resp = self.client.get("/getting-started/")
        for anchor in ('id="mainSidebar"', 'id="tickerBar"',
                       'id="infoPanelWrap"', 'id="signalsRail"',
                       'id="notifBell"', 'id="userMenuTrigger"',
                       'id="seEyeFab"', 'class="theme-toggle-btn"'):
            self.assertContains(resp, anchor)


class TourWalksToRealPagesTests(TestCase):
    """The tour used to point at a menu item and describe what lay behind
    it — teaching nothing the sidebar label did not already say, on a page
    the reader could not click. Steps that name a page now walk there, and
    the spotlight is live."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("tour_walk")

    def setUp(self):
        self.client.force_login(self.user)

    def test_page_steps_carry_the_page_they_describe(self):
        """The five stops that are pages — Operations Center, Signals,
        Strategies, the Bot Program, Portfolio — each declare their url, so
        the walk arrives there instead of pointing at the menu entry."""
        import re

        from django.urls import reverse
        body = self.client.get("/getting-started/").content.decode(
            "utf-8", "replace")
        declared = set(re.findall(r'url: "([^"]+)"', body))
        for name in ("command_center", "signals_list", "strategies_list",
                     "bot_home", "portfolio_overview"):
            with self.subTest(page=name):
                self.assertIn(reverse(name), declared)

    def test_every_declared_step_url_resolves(self):
        """A tour that walks you to a 404 is worse than one that points."""
        import re

        from django.urls import Resolver404, resolve
        body = self.client.get("/getting-started/").content.decode(
            "utf-8", "replace")
        urls = re.findall(r'url: "([^"]+)"', body)
        self.assertGreaterEqual(len(urls), 5)
        for u in urls:
            with self.subTest(url=u):
                try:
                    resolve(u)
                except Resolver404:  # pragma: no cover - the assertion reports
                    self.fail(f"tour step points at {u}, which does not resolve")

    def test_the_engine_can_resume_after_navigation(self):
        with open("static/js/sv-tour.js", encoding="utf-8") as fh:
            src = fh.read()
        # Hand-off across a page load, or the walk vanishes the moment it
        # does its job.
        self.assertIn("sv:tour:resume", src)
        self.assertIn("function saveResume", src)
        # Resume must outrank a fresh autostart, or every navigation
        # restarts the tour at step one.
        self.assertIn("if (resume || cfg.autostart)", src)

    def test_what_the_cutout_opens_rides_above_the_scrim(self):
        """A live cutout is half a gift if the bell dropdown it opens paints
        under the scrim and ignores every click — which is exactly what the
        ladder produced: menus at 1600 and panels at 2000 beneath a tour
        layer at 3000."""
        with open("static/css/sv-tour.css", encoding="utf-8") as fh:
            css = fh.read()
        self.assertIn("body.sv-tour-on", css)
        for surface in (".user-menu-dropdown", ".se-chat-panel",
                        ".sr-popup", ".ticker-popup", "[data-sv-overlay]"):
            with self.subTest(surface=surface):
                self.assertIn(surface, css)
        # Raised above the panes, still below the step card, and via the
        # ladder token — never a raw number.
        self.assertIn("calc(var(--z-backdrop, 3000) + 20)", css)
        with open("static/js/sv-tour.js", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn('classList.add("sv-tour-on")', src)
        self.assertIn('classList.remove("sv-tour-on")', src)
        # Escape must close that surface rather than ending the tour.
        self.assertIn(".se-chat-panel.open", src)

    def test_a_click_in_the_cutout_does_not_claim_an_arrival(self):
        """The operator clicked where THEY wanted. Recording it as "the
        tour navigated for step N+1" made that step skip its own walk and
        describe its page from whatever page the click landed on."""
        with open("static/js/sv-tour.js", encoding="utf-8") as fh:
            src = fh.read()
        click_fn = src.split("function onSpotlightClick")[1].split(
            "\n    }")[0]
        self.assertIn("saveResume(Math.min(idx + 1, cfg.steps.length - 1), false, 1)",
                      click_fn)
        # A modified click opens a new tab; this page is not going anywhere.
        self.assertIn("e.ctrlKey || e.metaKey || e.shiftKey || e.altKey",
                      click_fn)
        # And a handler that cancelled the navigation must not leave a
        # hand-off behind either.
        self.assertIn("e.defaultPrevented", click_fn)

    def test_a_step_skipped_into_still_walks_to_its_own_page(self):
        """The skip loop used to jump straight to rendering, so a step
        skipped INTO never checked whether it lived on another page."""
        with open("static/js/sv-tour.js", encoding="utf-8") as fh:
            src = fh.read()
        render_fn = src.split("function render(direction)")[1][:1400]
        nav = render_fn.find("w.location.assign(step.url)")
        skip = render_fn.find("idx += direction")
        self.assertGreater(nav, 0)
        self.assertGreater(skip, nav,
                           "the navigation check must sit INSIDE the skip "
                           "loop, before it advances")

    def test_direction_of_travel_survives_the_page_load(self):
        """BACK across a step that navigates must keep walking back."""
        with open("static/js/sv-tour.js", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("dir: dir === -1 ? -1 : 1", src)
        self.assertIn("render(opts.dir === -1 ? -1 : 1)", src)

    def test_the_spotlight_is_clickable_and_the_rest_is_not(self):
        with open("static/css/sv-tour.css", encoding="utf-8") as fh:
            css = fh.read()
        # The scrim paints; the panes fenced around the cutout carry the
        # hit area, so the highlighted control keeps its own interactions.
        self.assertIn(".sv-tour-pane", css)
        self.assertIn("pointer-events: auto", css)
        with open("static/js/sv-tour.js", encoding="utf-8") as fh:
            src = fh.read()
        self.assertIn("function fencePanes", src)
        self.assertIn("onSpotlightClick", src)


class StrategiesStepIsGroundedTests(TestCase):
    """The tour NAVIGATES to /strategies/ and then describes it.

    That page was rewritten to lead with the promotion ladder — one card per
    RuleControl row the engine runs, grouped by venue — while this step still
    described the old page, where the wizard's trade plans led and the
    automated stable was somewhere else entirely. So the walk arrived at one
    page and narrated another, to the one audience that cannot tell: a
    first-run operator. The file's own header makes that a defect by its own
    standard — "if a claim here stops being true, fix the claim".

    Each test below pins one claim in the step to the thing that makes it
    true, so the claim cannot rot again without failing here.
    """

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("tour_strat")

    def setUp(self):
        self.client.force_login(self.user)

    def _step(self):
        """The one step object, from the page that really renders the tour."""
        body = self.client.get("/getting-started/").content.decode(
            "utf-8", "replace")
        start = body.index('title: "Strategies & Opportunities"')
        return body[start:body.index("{ sel:", start)]

    def _strategies_page(self):
        from django.urls import reverse
        return self.client.get(reverse("strategies_list"),
                               HTTP_HOST="127.0.0.1").content.decode(
                                   "utf-8", "replace")

    def test_the_step_no_longer_leads_with_the_plans_nothing_executes(self):
        """The stale sentence was not a lie in isolation — it was a false
        EXCLUSIVE: it gave "the automated stable" to Opportunities while the
        page it walks to now leads with a section headed "Automated setups"
        and puts the plans four sections down."""
        step = self._step()
        self.assertNotIn("Strategies hold your multi-leg trade plans", step)
        self.assertIn("promotion ladder", step)

    def test_what_the_step_says_leads_the_page_really_leads_it(self):
        page = self._strategies_page()
        lead = page.index("Automated setups")
        plans = page.index("Hand-built trade plans")
        self.assertLess(lead, plans,
                        "the tour says the engine's rules lead and the plans "
                        "sit further down")
        self.assertIn("Nothing executes these", page)

    def test_the_venues_the_step_names_are_the_venues_the_page_prints(self):
        """research / paper / quarter / full — the step describes each one, so
        each has to still be what `_STAGE_VENUE` says it is."""
        step, page = self._step(), self._strategies_page()
        for phrase in ("research", "paper", "quarter"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, step)
        for venue in ("no order is ever placed", "full nominal size",
                      "quarter size", "full size"):
            with self.subTest(venue=venue):
                self.assertIn(venue, page)

    def test_the_step_still_promises_a_gate_and_a_record_per_card(self):
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="tour_rule",
                                   promotion_stage="research")
        step, page = self._step(), self._strategies_page()
        self.assertIn("next gate", step)
        self.assertIn("record", step)
        # Both really are ON the card, not only in the prose about it.
        self.assertIn('class="sc-gate"', page)
        self.assertIn('class="sc-record"', page)

    def test_the_paused_claim_is_what_the_seeders_actually_do(self):
        """"seeded setups start PAUSED until you arm them" survived the wave;
        this is the assertion that says so out loud."""
        from signals.management.commands.seed_strategies import seed_setups
        from signals.models_opportunity import OpportunitySetup
        seed_setups(activate=False)
        self.assertTrue(OpportunitySetup.objects.exists())
        self.assertFalse(
            OpportunitySetup.objects.filter(is_active=True).exists(),
            "the tour tells a first-run user nothing is armed yet")
        self.assertIn("PAUSED", self._step())

    def test_the_step_does_not_promise_a_viewer_the_decide_buttons(self):
        """/evolution/ shows every user the evidence and only an admin the
        fork/reject controls, so the step no longer says "before you fork or
        reject" to a reader who will not see a button."""
        step = self._step()
        self.assertNotIn("before you fork or reject", step)
        self.assertIn("admin", step)

    def test_the_step_still_walks_where_it_claims_to(self):
        from django.urls import reverse
        self.assertIn('url: "{}"'.format(reverse("strategies_list")),
                      self._step())
