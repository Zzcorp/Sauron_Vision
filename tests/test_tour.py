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
