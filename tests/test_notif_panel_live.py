"""The bell's ROWS have to be live, not just its number.

The operator's report: "notification number in red appear and the banner too
but nothing live when clicked". Both live halves worked. The panel behind
the bell did not — it was rendered inline in base.html at page load and
never again, so an alert that arrived afterwards moved the badge, raised a
banner, and then was not in the list the click opened.

Run with:  python manage.py test tests.test_notif_panel_live
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase


def _notify(user, title, **kw):
    from alerts.models import Notification
    return Notification.objects.create(
        user=user, notification_type=kw.pop("notification_type", "bot"),
        title=title, body=kw.pop("body", ""), url=kw.pop("url", ""), **kw)


class NotifItemsPartialTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("bell_u", password="x")
        self.client.force_login(self.user)

    def test_the_partial_serves_the_rows(self):
        _notify(self.user, "Position opened · XAUUSD")
        body = self.client.get("/partials/notif-items/").content.decode()
        self.assertIn("Position opened", body)
        self.assertIn("notif-item", body)

    def test_it_serves_what_arrived_after_the_page_did(self):
        """The whole point: the page is already open, the alert is new."""
        page = self.client.get("/dashboard/").content.decode()
        self.assertNotIn("Landed after the page", page)
        _notify(self.user, "Landed after the page")
        rows = self.client.get("/partials/notif-items/").content.decode()
        self.assertIn("Landed after the page", rows)

    def test_it_is_another_users_business_only(self):
        other = User.objects.create_user("bell_other", password="x")
        _notify(other, "Not yours")
        body = self.client.get("/partials/notif-items/").content.decode()
        self.assertNotIn("Not yours", body)

    def test_it_needs_a_login(self):
        self.client.logout()
        resp = self.client.get("/partials/notif-items/")
        self.assertIn(resp.status_code, (302, 403))

    def test_an_empty_inbox_renders_the_empty_state_not_nothing(self):
        body = self.client.get("/partials/notif-items/").content.decode()
        self.assertIn("Nothing yet", body)

    def test_a_row_carries_what_the_dwell_card_reads(self):
        _notify(self.user, "Close FAILED · EURUSD", body="Broker rejected it.",
                url="/asset-bots/")
        body = self.client.get("/partials/notif-items/").content.decode()
        for attr in ("data-nc-row", "data-nc-title", "data-nc-body",
                     "data-nc-kind", "data-nc-at", "data-nc-href"):
            self.assertIn(attr, body)


class OneTemplateForBothPaintsTests(TestCase):
    """base.html must INCLUDE the partial rather than keep its own copy.

    Two copies of these rows is how the panel came to be stale in the first
    place: the refresh would swap in markup that drifts from the markup it
    replaced, and the drift would only ever show up live.
    """

    def _base(self):
        for d in settings.TEMPLATES[0]["DIRS"]:
            p = Path(d) / "base.html"
            if p.exists():
                return p.read_text(encoding="utf-8")
        self.fail("base.html not found in TEMPLATES DIRS")

    def test_base_includes_the_partial(self):
        self.assertIn('{% include "_partials/notif_items.html" %}', self._base())

    def test_base_does_not_re_inline_the_rows(self):
        """The row markup lives in exactly one file."""
        self.assertNotIn('class="notif-item ni-{{ n.notification_type }}',
                         self._base())

    def test_the_scroll_box_is_addressable(self):
        """The refresh swaps this element's contents — no id, no refresh."""
        self.assertIn('id="notifScroll"', self._base())

    def test_the_socket_refreshes_the_rows_not_only_the_badge(self):
        base = self._base()
        self.assertIn("window.refreshNotifPanel", base)
        # The count and the list move together, from the same event.
        self.assertIn("if (window.refreshNotifPanel) window.refreshNotifPanel();",
                      base)

    def test_opening_the_bell_refreshes_before_it_retires_rows(self):
        """Order matters: marking a STALE list read retires the wrong rows
        and leaves the new one unread under a count that already dropped."""
        base = self._base()
        self.assertIn("refreshed.then(retireVisibleRows, retireVisibleRows)",
                      base)

    def test_the_banner_body_is_a_click_target(self):
        """"Nothing when clicked" was partly literal: only the six characters
        reading "Open" did anything."""
        self.assertIn("sv-banner--clickable", self._base())

    def test_a_row_swap_does_not_close_popups_elsewhere(self):
        """An unqualified htmx:afterSwap closes EVERY open portal popup.

        With the bell rows refreshing on every alert, that would have shut
        whatever popup the operator was reading each time a notification
        landed — reintroducing, from a new direction, the exact complaint
        the popup-persistence work had just fixed. The refreshers name the
        region they replaced; the popup closer keeps a popup whose own
        anchor is outside it.
        """
        base = self._base()
        self.assertIn("detail: { svRegion: box }", base)
        self.assertIn("detail: { svRegion: body }", base)
        self.assertIn("e.detail && e.detail.svRegion", base)
