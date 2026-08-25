"""Notification detail card + mark-on-view.

Two things the operator asked for and this module pins:

A. A notification row is a headline — the bell truncates the body at 110
   characters, states the kind as a chip, rounds the age to the minute,
   and can link to exactly one page even when the alert names seven
   instruments. A 2s dwell has to raise the rest of it, including one
   link per `data["items"]` entry, and a notification with no payload
   (which is nearly all of them) must render exactly as before.

B. Opening the bell means the rows it showed have been seen. That is a
   write, so it goes through the server: POST /notifications/read-all/
   with the ids the panel displayed, scoped to request.user, idempotent,
   and followed by a badge REFETCH rather than a client-side subtraction.

Run with:  python manage.py test tests.test_notification_detail
"""
import pathlib

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

READ_ALL = "/notifications/read-all/"


def _static(*parts):
    return (pathlib.Path(settings.BASE_DIR).joinpath("static", *parts)
            .read_text(encoding="utf-8"))


class MarkOnViewEndpointTests(TestCase):
    """The endpoint the bell posts to when it opens."""

    def setUp(self):
        from alerts.models import Notification
        self.user = User.objects.create_user("nd_owner", password="x")
        self.other = User.objects.create_user("nd_other", password="x")
        self.mine = [Notification.objects.create(
            user=self.user, notification_type="system", title=f"mine {i}")
            for i in range(3)]
        self.theirs = Notification.objects.create(
            user=self.other, notification_type="system", title="theirs")
        self.client.force_login(self.user)

    def _post(self, **kwargs):
        return self.client.post(READ_ALL, kwargs,
                                HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_it_marks_only_the_ids_the_panel_showed(self):
        """The bell shows ten of possibly hundreds. "I opened the bell" is
        evidence about those ten and nothing else — the older rows the
        operator never scrolled to must stay unread."""
        from alerts.models import Notification
        resp = self._post(ids=[self.mine[0].pk, self.mine[1].pk])
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["marked"], 2)
        self.assertTrue(Notification.objects.get(pk=self.mine[0].pk).read)
        self.assertTrue(Notification.objects.get(pk=self.mine[1].pk).read)
        self.assertFalse(Notification.objects.get(pk=self.mine[2].pk).read)

    def test_it_never_touches_another_users_rows(self):
        """Ids travel from the browser, so they are an operator-supplied
        value: the queryset filters on request.user before it writes."""
        from alerts.models import Notification
        resp = self._post(ids=[self.theirs.pk])
        self.assertEqual(resp.json()["marked"], 0)
        self.assertFalse(Notification.objects.get(pk=self.theirs.pk).read)

    def test_it_is_idempotent(self):
        """The panel opens as often as the operator likes, and a second
        open must be a no-op rather than a second write."""
        ids = [n.pk for n in self.mine]
        self.assertEqual(self._post(ids=ids).json()["marked"], 3)
        again = self._post(ids=ids)
        self.assertEqual(again.json()["marked"], 0)
        self.assertEqual(again.json()["unread"], 0)

    def test_junk_ids_mark_nothing_rather_than_everything(self):
        """An all-junk list must not fall through to the no-ids branch —
        that branch clears the whole inbox."""
        from alerts.models import Notification
        self.assertEqual(self._post(ids=["", "abc"]).json()["marked"], 0)
        self.assertEqual(
            Notification.objects.filter(user=self.user, read=False).count(), 3)

    def test_no_ids_still_marks_everything(self):
        """The explicit "Mark all read" control posts the same endpoint with
        no ids and must keep working exactly as it did."""
        from alerts.models import Notification
        self.assertEqual(self._post().json()["marked"], 3)
        self.assertEqual(Notification.unread_count(self.user), 0)

    def test_get_is_refused(self):
        """A state change on GET let prefetching proxies clear the inbox."""
        self.assertEqual(self.client.get(READ_ALL).status_code, 405)

    def test_anonymous_is_bounced(self):
        self.client.logout()
        resp = self.client.post(READ_ALL, {"ids": [self.mine[0].pk]})
        self.assertIn(resp.status_code, (302, 403))
        from alerts.models import Notification
        self.assertFalse(Notification.objects.get(pk=self.mine[0].pk).read)

    def test_the_badge_count_drops_after_the_panel_marks_read(self):
        """The badge is refetched from /partials/panel-counts/, so the drop
        has to be visible in the SERVER's answer, not only in the DOM."""
        before = self.client.get("/partials/panel-counts/").json()
        self.assertEqual(before["notifications"], 3)
        self._post(ids=[n.pk for n in self.mine])
        after = self.client.get("/partials/panel-counts/").json()
        self.assertEqual(after["notifications"], 0)

    def test_marking_mine_leaves_the_other_users_badge_alone(self):
        self._post()
        self.client.force_login(self.other)
        counts = self.client.get("/partials/panel-counts/").json()
        self.assertEqual(counts["notifications"], 1)


class DetailCardMarkupTests(TestCase):
    """What the templates and the engine have to carry for the card to
    exist at all. These are contract assertions: the interaction lives in
    JS, and nothing else would notice if a data attribute went missing."""

    @classmethod
    def setUpTestData(cls):
        from alerts.models import Notification
        cls.user = User.objects.create_user("nd_markup", password="x")
        cls.rich = Notification.objects.create(
            user=cls.user, notification_type="portfolio",
            title="Market anomaly across 2 instruments",
            body="Unusual volume on two names.\nSecond line survives.",
            url="/quotes/",
            data={"items": [
                {"label": "BTC-USD", "detail": "+8.4% on 6x volume",
                 "url": "/instruments/btc-usd/"},
                {"label": "ETH-USD", "detail": "+5.1% on 4x volume",
                 "url": "/instruments/eth-usd/"},
            ]})
        cls.plain = Notification.objects.create(
            user=cls.user, notification_type="system",
            title="Nightly job finished", body="No payload on this one.")

    def setUp(self):
        self.client.force_login(self.user)

    def _inbox(self):
        return self.client.get("/notifications/").content.decode("utf-8", "replace")

    def test_the_bell_rows_carry_the_card_payload(self):
        """The bell row shows a stub; the card needs the whole thing plus
        the exact timestamp the row rounds away."""
        html = self._inbox()
        self.assertIn("data-nc-row", html)
        self.assertIn('data-nc-title="Market anomaly across 2 instruments"', html)
        self.assertIn("data-nc-kind=", html)
        self.assertIn("data-nc-at=", html)
        self.assertIn("Second line survives.", html)

    def test_data_items_reach_the_page_as_escaped_json(self):
        """json_script, not a hand-built attribute: the labels come from a
        producer and must never be able to close a tag."""
        html = self._inbox()
        self.assertIn('type="application/json"', html)
        self.assertIn('"label": "BTC-USD"', html)
        self.assertIn('"url": "/instruments/eth-usd/"', html)

    def test_a_notification_with_no_data_still_renders(self):
        """Nearly every notification has an empty payload. It must render
        as it always did — and never as Python's dict_items repr, which is
        what `n.data.items` resolves to on a dict with no "items" key."""
        from alerts.models import Notification
        Notification.objects.create(
            user=self.user, notification_type="system",
            title="Payload with no items", data={"origin": "scheduler"})
        html = self._inbox()
        self.assertIn("Nightly job finished", html)
        self.assertIn("Payload with no items", html)
        self.assertNotIn("dict_items", html)

    def test_the_inbox_rows_carry_the_card_payload_too(self):
        """Same card on both surfaces — the inbox is where an operator goes
        to actually work through them."""
        html = self._inbox()
        self.assertIn("inbox-row", html)
        self.assertGreaterEqual(html.count("data-nc-row"), 2)

    def test_the_engine_ships_the_dwell_contract(self):
        """The fixes the news feed and the briefing already paid for: a
        dwell on the platform's one hover beat, a body-portalled card, the relatedTarget guard on the way to
        it, the selection check before navigating, and a touch branch."""
        js = _static("js", "sv-notif-card.js")
        self.assertIn("HOVER_DELAY_MS = (w.SV_HOVER_BEAT_MS || 450)", js)
        self.assertIn("d.body.appendChild(pop)", js)
        self.assertIn("pop.contains(to)", js)
        self.assertIn("pointerleave", js)
        self.assertIn("isCollapsed", js)
        self.assertIn("(hover: hover)", js)
        # Delegated from document, so a live-swapped row keeps working.
        self.assertIn('d.addEventListener("pointerover"', js)

    def test_the_card_is_placed_beside_a_portalled_panel(self):
        """--z-hovercard sits below --z-menu: a card laid under a bell row
        the way the news feed lays its own would paint behind the panel."""
        js = _static("js", "sv-notif-card.js")
        self.assertIn('row.closest("[data-sv-overlay]")', js)

    def test_the_card_chrome_exists_in_both_themes(self):
        """It reuses .nf-pop, whose colours are the --pop-* tokens, and the
        item rows must stay on tokens too or light mode loses them."""
        css = _static("css", "sauron.css")
        self.assertIn(".nf-pop-items", css)
        self.assertIn(".nf-pop-item .nfi-label", css)
        self.assertIn(".notif-item.just-read", css)
        self.assertNotIn("nfi-label { color: #", css)

    def test_the_page_ships_the_engine(self):
        self.assertIn("js/sv-notif-card.js", self._inbox())

    def test_the_payload_rides_inside_its_own_row(self):
        """The card reads the json_script relative to the row it is
        building, so a payload parked outside the row would silently
        attach to whichever notification happened to be first."""
        import re
        rows = [m.group(0) for m in
                re.finditer(r'<a class="notif-item.*?</a>', self._inbox(), re.S)]
        carriers = [r for r in rows if "application/json" in r]
        self.assertEqual(len(carriers), 1)
        self.assertIn("Market anomaly across 2 instruments", carriers[0])


class MarkOnViewClientTests(TestCase):
    """The browser half of B, pinned where it lives: base.html."""

    @classmethod
    def setUpTestData(cls):
        from alerts.models import Notification
        cls.user = User.objects.create_user("nd_client", password="x")
        # An unread row, or the bell renders neither the panel rows nor the
        # "Mark all read" control this class is checking.
        Notification.objects.create(
            user=cls.user, notification_type="bot", title="Fill on BTC-USD")

    def setUp(self):
        self.client.force_login(self.user)
        self.html = self.client.get("/notifications/").content.decode(
            "utf-8", "replace")

    def test_it_fires_on_the_panels_open_event(self):
        """sv:open on the portalled panel — a hover must not clear an
        inbox, and a listener bound to the topbar subtree would miss the
        menu entirely once the controller moves it to <body>."""
        self.assertIn("addEventListener('sv:open'", self.html)
        self.assertIn(".notif-item.unread[data-notif-id]", self.html)

    def test_it_posts_the_shown_ids_with_csrf(self):
        self.assertIn("/notifications/read-all/", self.html)
        self.assertIn("'X-CSRFToken': csrf", self.html)
        self.assertIn("form.append('ids'", self.html)

    def test_the_badge_is_refetched_never_decremented(self):
        """One missed message and a client-side delta drifts forever."""
        self.assertIn("window.refreshNotifBadge()", self.html)
        self.assertNotIn("count - 1", self.html)

    def test_a_refused_write_leaves_the_rows_unread(self):
        """The idle PIN lock answers 423 to XHR. Dimming the rows anyway
        would tell the operator they had read what the server still holds
        as unread."""
        self.assertIn("if (!r.ok) return;", self.html)
        self.assertIn("just-read", self.html)

    def test_the_explicit_mark_all_control_still_posts(self):
        self.assertIn("markAllReadForm", self.html)
        self.assertIn("MARK ALL READ", self.html)
