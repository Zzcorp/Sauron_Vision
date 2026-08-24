"""The lock screen, and the two ways into it.

An idle lock already existed and was server-authoritative — the flag is
the lock, the overlay is paint. What it lacked was a way to lock ON
PURPOSE, a state that reads as asleep rather than as a dialog, and a
screen that actually hides what it is locking.

That last one was the real defect: the overlay painted rgba(3, 8, 6, 0.78)
over a backdrop blur, so positions and P&L stayed legible through 22%
transparency — and `backdrop-filter` is ignored outright in some engines
and under forced-colors, leaving the account plainly readable behind a
screen that says LOCKED. A lock that shows the data it is locking is a
screensaver.

Run with:  python manage.py test tests.test_lock_screen
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

HOST = "127.0.0.1"


def _css():
    return (Path(settings.BASE_DIR) / "static" / "css"
            / "sauron.css").read_text(encoding="utf-8")


def _declarations(block):
    """A CSS block with its comments stripped.

    The first version of this guard scanned the raw block and tripped on
    the comment EXPLAINING why rgba and backdrop-filter had been removed.
    A guard that reads prose measures the wrong thing — and this project
    has now been bitten by exactly that four times.
    """
    return re.sub(r"/\*.*?\*/", "", block, flags=re.S)


def _js():
    return (Path(settings.BASE_DIR) / "static" / "js"
            / "idle-lock.js").read_text(encoding="utf-8")


class TheScreenHidesWhatItLocksTests(SimpleTestCase):
    def test_the_overlay_is_opaque(self):
        """The defect, in one assertion: a translucent lock screen shows
        the book it is locking."""
        block = _declarations(
            _css().split(".il-overlay {", 1)[1].split("}", 1)[0])
        self.assertNotIn("rgba", block,
                         "a translucent lock screen leaks the account")
        self.assertIn("background: var(--bg-dark", block)

    def test_it_does_not_rely_on_backdrop_filter_to_hide_anything(self):
        """backdrop-filter is ignored in some engines and under
        forced-colors. If it were load-bearing, those users would see the
        whole account through the lock."""
        block = _declarations(
            _css().split(".il-overlay {", 1)[1].split("}", 1)[0])
        self.assertNotIn("backdrop-filter", block)

    def test_the_light_theme_is_opaque_too(self):
        css = _css()
        line = [l for l in css.splitlines()
                if "body.light-mode .il-overlay" in l and "background" in l]
        self.assertTrue(line)
        self.assertNotIn("rgba", line[0])


class TheSleepingStateTests(SimpleTestCase):
    def test_the_controls_are_hidden_until_the_screen_is_woken(self):
        """A PIN pad glowing at an empty desk is an invitation. A locked
        screen is usually locked BECAUSE somebody walked away from it."""
        css = _css()
        block = css.split(".il-wake {", 1)[1].split("}", 1)[0]
        self.assertIn("visibility: hidden", block)
        self.assertIn("opacity: 0", block)
        self.assertIn(".il-overlay.is-awake .il-wake", css)

    def test_a_move_a_key_or_a_touch_wakes_it(self):
        js = _js()
        for ev in ("mousemove", "keydown", "touchstart"):
            self.assertIn(ev, js, ev)
        self.assertIn("wake()", js)

    def test_it_goes_back_to_sleep_and_clears_the_pad(self):
        """Waking on a passing cursor must not leave the pad lit, and
        half-typed digits must not sit on the screen."""
        js = _js()
        block = js.split("wakeTimer = setTimeout", 1)[1][:300]
        self.assertIn("sleep()", block)
        self.assertIn("pinClear()", block)

    def test_it_locks_asleep_rather_than_awake(self):
        js = _js()
        engage = js.split("function engage(", 1)[1][:900]
        self.assertIn("sleep()", engage)


class TheStandalonePageSleepsTooTests(SimpleTestCase):
    """The /locked/ page keeps the same sleeping contract as the in-app
    overlay above: the PIN gate shows only when the operator reaches for
    it — hover on the card, or any move/key/touch — and 45s of stillness
    puts it back to sleep with the pad cleared. Two lock surfaces with
    two behaviours would teach the operator the wrong reflex on one of
    them."""

    @staticmethod
    def _page():
        from django.conf import settings as _s
        from pathlib import Path as _P
        return (_P(_s.BASE_DIR) / "templates" / "dashboard"
                / "locked.html").read_text(encoding="utf-8")

    def test_the_gate_is_hidden_until_woken(self):
        page = self._page()
        block = page.split(".lk-reveal {", 1)[1].split("}", 1)[0]
        self.assertIn("opacity: 0", block)
        self.assertIn("visibility: hidden", block,
                      "opacity alone leaves an invisible UNLOCK clickable")
        self.assertIn(".lk-card:hover .lk-reveal", page)
        self.assertIn(".lk-page.lk-awake .lk-reveal", page)

    def test_a_move_a_key_or_a_touch_wakes_it(self):
        page = self._page()
        for ev in ("mousemove", "keydown", "touchstart"):
            self.assertIn(ev, page, ev)
        self.assertIn("wake", page)

    def test_it_goes_back_to_sleep_and_clears_the_pad(self):
        page = self._page()
        block = page.split("wakeTimer = setTimeout", 1)[1][:300]
        self.assertIn('classList.remove("lk-awake")', block)
        self.assertIn("clear()", block)

    def test_the_pin_gate_is_inside_the_reveal(self):
        """A box left outside the wrapper would glow on the sleeping
        face — the exact invitation this exists to remove."""
        page = self._page()
        reveal = page.split('<div class="lk-reveal">', 1)[1]
        # Everything the gate is made of must appear BEFORE the wrapper
        # could have closed around the following <style> block.
        gate_zone = reveal.split("<style>", 1)[0]
        for needle in ('id="lkPinRow"', 'id="lkError"', 'id="lkUnlock"',
                       'id="lkLogoutForm"'):
            self.assertIn(needle, gate_zone, needle)


class TheGateMovesLikeAGateTests(SimpleTestCase):
    """Engage and release are choreographed, not jump cuts — and the page
    comes back to LIFE on release, not just back into view: every poller
    listens for sv:pin-unlocked and repaints immediately instead of
    waiting out its sweep."""

    def test_the_veil_is_opaque_from_frame_one_and_only_the_eye_arrives(self):
        """The first cut animated the OVERLAY's opacity — which showed
        the book through a fading sheet that says LOCKED, and a JS hiccup
        could have left the veil open and invisible. The sheet must be
        opaque the frame it exists; the eye alone makes the entrance."""
        css = _css()
        base = _declarations(
            css.split(".il-overlay {", 1)[1].split("}", 1)[0])
        self.assertNotIn("opacity", base,
                         "the veil itself must never fade IN")
        self.assertIn(".il-overlay .il-eye", css)
        self.assertIn(".il-overlay.il-in .il-eye", css)
        self.assertIn(".il-overlay.il-out", css)

    def test_reduced_motion_stills_the_choreography(self):
        css = _css()
        guard = css.split(".il-overlay.il-out, .il-overlay .il-eye", 1)
        self.assertEqual(len(guard), 2,
                         "the reduced-motion guard must cover the exit "
                         "fade and the eye's entrance")

    def test_engage_adds_the_class_a_frame_late_and_release_waits(self):
        js = _js()
        self.assertIn('classList.add("il-in")', js)
        self.assertIn("requestAnimationFrame", js,
                      "same-frame class add skips the transition entirely")
        self.assertIn('classList.remove("il-in")', js)

    def test_the_standalone_page_arrives_and_leaves_gracefully(self):
        from django.conf import settings as _s
        from pathlib import Path as _P
        page = (_P(_s.BASE_DIR) / "templates" / "dashboard"
                / "locked.html").read_text(encoding="utf-8")
        self.assertIn('class="lk-card fade-in-up"', page)
        self.assertIn(".lk-page.lk-leave .lk-card", page)
        self.assertIn('classList.add("lk-leave")', page)

    def test_every_poller_comes_back_to_life_on_release(self):
        """A lifted gate over a frozen page is half an unlock. The event
        already existed (sv:pin-unlocked); what is pinned here is that
        the pollers actually use it."""
        from django.conf import settings as _s
        from pathlib import Path as _P
        base = _P(_s.BASE_DIR)
        for rel in ("static/js/sv-market-status.js",
                    "static/js/sv-nav-activity.js",
                    "static/js/sv-instrument-live.js",
                    "templates/_partials/live_region.html"):
            src = (base / rel).read_text(encoding="utf-8")
            self.assertIn("sv:pin-unlocked", src, rel)


class TheLockButtonTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("lock_u", password="x")
        self.client.force_login(self.user)

    def _body(self):
        resp = self.client.get("/positions/", HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode("utf-8", "replace")

    def _set_pin(self, pin="1234"):
        from django.contrib.auth.hashers import make_password
        from portfolio.trader_profile import TraderProfile
        prof, _ = TraderProfile.objects.get_or_create(user=self.user)
        prof.access_pin_hash = make_password(pin)
        prof.save(update_fields=["access_pin_hash"])

    def test_the_button_is_offered(self):
        self.assertIn('id="lockNowBtn"', self._body())

    def test_it_reports_that_no_pin_is_set(self):
        self.assertEqual(
            re.search(r'data-has-pin="(\d)"', self._body()).group(1), "0")

    def test_it_reports_a_pin_once_there_is_one(self):
        self._set_pin()
        self.assertEqual(
            re.search(r'data-has-pin="(\d)"', self._body()).group(1), "1")

    def test_without_a_pin_it_offers_to_set_one_rather_than_locking(self):
        """Locking with no PIN would trap the operator behind a screen only
        a logout escapes."""
        js = _js()
        block = js.split('getElementById("lockNowBtn")', 1)[1][:1600]
        self.assertIn('data-has-pin") === "1"', block)
        self.assertIn("modal=pin", block)

    def test_the_lock_endpoint_it_posts_to_exists(self):
        resp = self.client.post("/api/session/lock/", HTTP_HOST=HOST,
                                HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertIn(resp.status_code, (200, 204))


class TheScreenIsSauronTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("lock_s", password="x")
        self.client.force_login(self.user)

    def test_it_carries_the_eye_and_the_hour(self):
        body = self.client.get("/positions/", HTTP_HOST=HOST).content.decode(
            "utf-8", "replace")
        self.assertIn("il-eye", body)
        self.assertIn("sauron_eye.svg", body)
        self.assertIn('id="ilClock"', body)

    def test_it_says_how_to_wake_it(self):
        body = self.client.get("/positions/", HTTP_HOST=HOST).content.decode(
            "utf-8", "replace")
        self.assertIn("move to wake", body)

    def test_unlock_and_disconnect_are_both_behind_the_wake(self):
        body = self.client.get("/positions/", HTTP_HOST=HOST).content.decode(
            "utf-8", "replace")
        self.assertIn("il-wake", body)
        self.assertIn("ilUnlockBtn", body)
        self.assertIn("il-disconnect", body)
