"""Nothing stays unseen — the sidebar dots and the live instrument page.

Two operator asks, one principle: a change the platform knows about must
not depend on the operator happening to look. The sidebar wears a dot on
every section with activity newer than THIS user's last visit (server
truth on the profile, so a phone read clears the desktop's dot), and the
instrument page's price and chart move with the market instead of
freezing at first paint under a live market badge — the worst
combination, a frozen number dressed as current.

Run with:  python manage.py test tests.test_nothing_unseen
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase

NAV_SECTIONS = {"signals", "positions", "news", "briefing", "hypotheses",
                "opportunities", "generated"}


def _signal():
    from instruments.models import Instrument
    from signals.models import Signal
    inst, _ = Instrument.objects.get_or_create(
        symbol="BTCUSD", defaults={"name": "b", "asset_class": "crypto"})
    return Signal.objects.create(
        instrument=inst, signal_type="technical", direction="bullish",
        urgency="high", title="t", description="d", rule_name="r",
        score=0.5, price_at_signal=Decimal("1"), is_active=True)


class NavActivityTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("dots_u",
                                                         password="x")
        self.client.force_login(self.user)

    def test_login_is_required(self):
        self.client.logout()
        self.assertEqual(self.client.get("/api/nav-activity/").status_code,
                         302)

    def test_the_payload_covers_every_wired_section(self):
        """The probe table and the sidebar's data-nav-id set must be the
        same seven names — a section wired on one side only is a dot that
        can never light or never die."""
        pages = self.client.get("/api/nav-activity/").json()["pages"]
        self.assertEqual(set(pages), NAV_SECTIONS)

    def test_activity_on_a_never_visited_page_lights_the_dot(self):
        """A dot that waited for a first visit would never light for the
        page most worth discovering."""
        _signal()
        pages = self.client.get("/api/nav-activity/").json()["pages"]
        self.assertTrue(pages["signals"])

    def test_stamping_a_page_seen_clears_it_until_new_activity(self):
        _signal()
        self.client.post("/api/nav-activity/", {"page_id": "signals"},
                         content_type="application/json")
        pages = self.client.get("/api/nav-activity/").json()["pages"]
        self.assertFalse(pages["signals"])

        _signal()  # something new happened after the visit
        pages = self.client.get("/api/nav-activity/").json()["pages"]
        self.assertTrue(pages["signals"])

    def test_seen_is_per_operator_not_per_platform(self):
        """One user reading the signals page must not silence another
        user's dot — seen is a fact about a person."""
        _signal()
        self.client.post("/api/nav-activity/", {"page_id": "signals"},
                         content_type="application/json")

        other = get_user_model().objects.create_user("dots_v", password="x")
        self.client.force_login(other)
        pages = self.client.get("/api/nav-activity/").json()["pages"]
        self.assertTrue(pages["signals"])

    def test_an_opportunity_flag_lights_its_dot(self):
        """The probe once aggregated a field the model does not have; the
        FieldError died inside the fence and the dot was PERMANENTLY dark
        with every test green — this row is the one that would have
        caught it."""
        from instruments.models import Instrument
        from signals.models import OpportunityFlag, OpportunitySetup
        inst, _ = Instrument.objects.get_or_create(
            symbol="ETHUSD", defaults={"name": "e", "asset_class": "crypto"})
        setup = OpportunitySetup.objects.create(
            name="probe_setup", conditions=[], min_match_score=0.5)
        OpportunityFlag.objects.create(
            setup=setup, instrument=inst, score=0.9,
            conditions_evaluated=[])
        pages = self.client.get("/api/nav-activity/").json()["pages"]
        self.assertTrue(pages["opportunities"])

    def test_a_legacy_book_position_lights_the_positions_dot(self):
        """The positions page renders BOTH books; a probe watching one of
        them is the platform's own documented past bug, re-made."""
        from decimal import Decimal as D

        from django.utils import timezone

        from instruments.models import Instrument
        from portfolio.models import Position
        from portfolio.services import get_or_create_default_portfolio
        inst, _ = Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "a", "asset_class": "stock"})
        Position.objects.create(
            portfolio=get_or_create_default_portfolio(user=self.user),
            instrument=inst, direction="long", quantity=D("1"),
            entry_price=D("200"), current_price=D("200"),
            opened_at=timezone.now())
        pages = self.client.get("/api/nav-activity/").json()["pages"]
        self.assertTrue(pages["positions"])

    def test_a_non_dict_json_body_answers_calmly(self):
        """The beacon fires on every page load; "null" is a shrug, not a
        500."""
        resp = self.client.post("/api/nav-activity/", "null",
                                content_type="application/json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["ok"])

    def test_an_unknown_page_id_is_refused_and_the_map_stays_bounded(self):
        from portfolio.trader_profile import TraderProfile
        resp = self.client.post("/api/nav-activity/",
                                {"page_id": "not_a_section"},
                                content_type="application/json")
        self.assertFalse(resp.json()["ok"])
        self.client.post("/api/nav-activity/", {"page_id": "signals"},
                         content_type="application/json")
        prof = TraderProfile.objects.get(user=self.user)
        self.assertEqual(set(prof.pages_seen), {"signals"})

    def test_a_quiet_section_shows_no_dot(self):
        pages = self.client.get("/api/nav-activity/").json()["pages"]
        self.assertFalse(pages["news"], "no articles, no dot")


class SidebarWiringTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("dots_w",
                                                         password="x")
        self.client.force_login(self.user)

    def test_the_sidebar_and_the_payload_agree_exactly(self):
        """Parity in BOTH directions, read off the rendered page — a
        section wired on one side only is a dot that can never light or
        never die, and a constant here would bless the drift."""
        import re as _re
        body = self.client.get("/instruments/").content.decode()
        wired = set(_re.findall(r'data-nav-id="([^"]+)"', body))
        payload = set(self.client.get("/api/nav-activity/")
                      .json()["pages"])
        self.assertEqual(wired, payload)
        self.assertEqual(wired, NAV_SECTIONS)
        self.assertIn("data-nav-page-id", body)
        self.assertIn("js/sv-nav-activity.js", body)


class LiveInstrumentPageTests(TestCase):
    def setUp(self):
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        self.user = get_user_model().objects.create_user("live_i",
                                                         password="x")
        self.client.force_login(self.user)
        inst, _ = Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "Apple",
                                     "asset_class": "stock"})
        LiveQuote.objects.update_or_create(
            instrument=inst, defaults={"last": Decimal("200"),
                                       "source": "test"})

    def test_the_price_hero_is_marked_live_and_the_poller_ships(self):
        resp = self.client.get("/instruments/AAPL/")
        self.assertContains(resp, 'data-instrument-live="AAPL"')
        self.assertContains(resp, "js/sv-instrument-live.js")

    def test_the_chart_widget_registers_its_live_handle(self):
        """The page pollers keep the chart honest through
        window.svCharts[id].refresh/tick — a widget that stops
        registering goes back to load-once-and-freeze silently."""
        resp = self.client.get("/instruments/AAPL/")
        self.assertContains(resp, "window.svCharts")
        self.assertContains(resp, "refresh: function")
        self.assertContains(resp, "tick: function")
