"""The deal ticket says which venue it trades at, before the click.

The manual lane is armed PER ASSET CLASS. On this deployment the stock lane
was live while forex, commodity and crypto stayed in paper — so a LONG on
GLDM moved real money while the byte-identical button on GBPJPY was a
simulation, and the ticket said nothing either way. The venue appeared only
in the preview payload, i.e. AFTER the click, and the operator took a forex
position believing it was live.

This file already argues the principle about prices, in its own comment:

    The price rides the button that trades at it. LONG lifts the ASK and
    SHORT hits the BID, so pairing them by eye was work the operator was
    doing that the markup should have been doing.

Which fact governs the button matters more than which price is on it. A wrong
price costs a few basis points; a wrong venue is the difference between a
simulation and the account.

Run with:  python manage.py test tests.test_deal_ticket_venue
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase


def _instrument(symbol="GLDM", asset_class="etf"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol,
        defaults={"name": symbol, "asset_class": asset_class,
                  "currency": "USD", "is_active": True})
    if inst.asset_class != asset_class:
        inst.asset_class = asset_class
        inst.save(update_fields=["asset_class"])
    return inst


def _lane(user, cls, mode):
    from bot_program.manual_trade import manual_config_for
    cfg = manual_config_for(user, cls)
    cfg.mode = mode
    cfg.capital = Decimal("500")
    cfg.save(update_fields=["mode", "capital"])
    return cfg


class TheTicketNamesItsVenueTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("ticket_u", password="x")
        self.client = Client()
        self.client.force_login(self.user)

    def _page(self, symbol):
        return self.client.get(f"/instruments/{symbol}/").content.decode()

    def test_an_armed_class_shows_LIVE_on_the_ticket(self):
        _instrument("GLDM", "etf")
        _lane(self.user, "stock", "live")     # etf executes as stock
        html = self._page("GLDM")
        self.assertIn("tk-venue--live", html)
        self.assertIn("● LIVE", html)

    def test_a_paper_class_shows_paper(self):
        _instrument("GBPJPY", "forex")
        _lane(self.user, "forex", "paper")
        html = self._page("GBPJPY")
        self.assertIn("tk-venue--paper", html)
        self.assertNotIn("tk-venue--live", html)

    def test_the_two_classes_disagree_on_the_same_deployment(self):
        """The exact state that produced the mistake: one lane armed, another
        not, and the operator on the wrong page."""
        _instrument("GLDM", "etf")
        _instrument("GBPJPY", "forex")
        _lane(self.user, "stock", "live")
        _lane(self.user, "forex", "paper")
        self.assertIn("tk-venue--live", self._page("GLDM"))
        self.assertIn("tk-venue--paper", self._page("GBPJPY"))

    def test_an_etf_follows_the_stock_lane(self):
        """EXECUTABLE_CLASS maps etf -> stock, so a commodity ETF is armed by
        arming stocks. That is not obvious from the page and is exactly why
        the badge has to be computed, not assumed."""
        _instrument("SLV", "etf")
        _lane(self.user, "stock", "live")
        self.assertIn("● LIVE", self._page("SLV"))

    def test_the_badge_explains_itself_on_hover(self):
        _instrument("GLDM", "etf")
        _lane(self.user, "stock", "live")
        self.assertIn("places REAL orders", self._page("GLDM"))


class TheBadgeNeverBreaksThePageTests(TestCase):
    """It is decoration on a page an operator reaches from a list. A missing
    lane, an unknown asset class or a broken import must cost the badge, never
    the instrument."""

    def setUp(self):
        self.user = User.objects.create_user("ticket_safe", password="x")
        self.client = Client()
        self.client.force_login(self.user)

    def test_an_unmapped_asset_class_still_renders(self):
        _instrument("SOMEBOND", "bond")     # no EXECUTABLE_CLASS entry
        r = self.client.get("/instruments/SOMEBOND/")
        self.assertEqual(r.status_code, 200)
        self.assertNotIn("tk-venue--live", r.content.decode())

    def test_a_failure_inside_the_lookup_degrades_to_paper(self):
        from unittest.mock import patch

        _instrument("GLDM", "etf")
        _lane(self.user, "stock", "live")
        with patch("bot_program.manual_trade.manual_config_for",
                   side_effect=RuntimeError("boom")):
            r = self.client.get("/instruments/GLDM/")
        self.assertEqual(r.status_code, 200)
        # Degrades to the SAFE side: never claims live it could not confirm.
        self.assertNotIn("tk-venue--live", r.content.decode())


class TheOtherIncludesAreUntouchedTests(SimpleTestCase):
    """The ticket is included from several pages. Only the caller that passes
    `lane_mode` renders a badge, so nothing else changes shape."""

    def test_the_badge_is_conditional_on_the_caller(self):
        from pathlib import Path

        from django.conf import settings
        html = (Path(settings.BASE_DIR) / "templates" / "_partials"
                / "deal_ticket.html").read_text(encoding="utf-8")
        self.assertIn("{% if lane_mode %}", html)

    def test_the_instrument_page_passes_it(self):
        from pathlib import Path

        from django.conf import settings
        html = (Path(settings.BASE_DIR) / "templates" / "dashboard"
                / "instrument_detail.html").read_text(encoding="utf-8")
        self.assertIn("lane_mode=lane_mode", html)
