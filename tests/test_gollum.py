"""Gollum — the guide who knows the way to Mordor.

A creature at the bottom-left corner, opposite the Palantír: one orb
SEES (Ask Sauron), the other POINTS. He searches every page and section
from the sidebar's own links plus his lore, learns what changed from
the nav-activity poll the dots already run, fidgets and whispers once
per change — never nags — and never acts.

Run with:  python manage.py test tests.test_gollum
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase


def _src(*parts):
    return Path(settings.BASE_DIR).joinpath(*parts).read_text(
        encoding="utf-8")


class GollumStandsAtTheCornerTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("gollum_u",
                                                         password="x")
        self.client.force_login(self.user)

    def test_he_stands_on_every_app_page(self):
        body = self.client.get("/instruments/").content.decode()
        self.assertIn('id="gollumFab"', body)
        self.assertIn('id="gollumDialog"', body)
        self.assertIn("data-gollum-input", body)
        self.assertIn("js/sv-gollum.js", body)

    def test_he_stays_off_the_dataless_screens(self):
        """The locked page is standalone by design — no shell, no guide."""
        session = self.client.session
        session["pin_locked"] = True
        session.save()
        body = self.client.get("/locked/").content.decode()
        self.assertNotIn("gollumFab", body)

    def test_he_is_a_real_button_with_a_dialog_contract(self):
        body = self.client.get("/instruments/").content.decode()
        head = body.split('id="gollumFab"')[0][-400:]
        self.assertIn('<button type="button" class="gollum-fab"', head)
        self.assertIn('aria-controls="gollumDialog"', body)
        self.assertIn('role="dialog"', body)


class GollumKnowsTheRoadsTests(TestCase):
    def _js(self):
        return _src("static", "js", "sv-gollum.js")

    def test_he_reads_the_sidebar_and_his_lore(self):
        js = self._js()
        self.assertIn('".sidebar-nav .nav-link"', js)
        self.assertIn("GOLLUM_LORE", js)
        for word in ("briefing", "positions", "brain", "headband", "news"):
            self.assertIn(word, js)

    def test_every_token_must_land_or_the_road_is_not_shown(self):
        """Fuzzy but honest: a query token the entry does not contain
        drops the entry — no word salad of near-misses."""
        js = self._js()
        self.assertIn("if (at < 0) return -1;", js)

    def test_he_answers_the_keys(self):
        js = self._js()
        # Ctrl+K belongs to the Palantír (base.html routes it to Ask
        # Sauron); two owners on one chord means neither works.
        self.assertNotIn('e.key.toLowerCase() === "k"', js)
        self.assertIn('e.key === "/"', js)
        self.assertIn('e.key === "Escape"', js)
        self.assertIn('"ArrowDown"', js)

    def test_the_page_you_are_on_is_never_unseen(self):
        """One filtered map for the dots and the guide — a guide that
        counts the page under your nose as unseen is not believed."""
        nav = _src("static", "js", "sv-nav-activity.js")
        self.assertIn("k !== here", nav)
        self.assertIn("detail: { pages: pages }", nav)

    def test_the_cursor_row_scrolls_into_view(self):
        js = self._js()
        self.assertIn("scrollIntoView", js)

    def test_he_learns_from_the_dots_without_a_second_poll(self):
        nav = _src("static", "js", "sv-nav-activity.js")
        self.assertIn("sv:nav-activity", nav)
        js = self._js()
        self.assertIn('"sv:nav-activity"', js)
        self.assertNotIn("fetch(", js)

    def test_he_whispers_once_per_change_never_nags(self):
        js = self._js()
        self.assertIn("if (n > nudged)", js)
        self.assertIn("nudged = n;", js)

    def test_he_points_but_never_acts(self):
        """Anchored roads glow or engage the lock — nothing here trades,
        closes, or posts."""
        js = self._js()
        self.assertIn('e.href === "#headband"', js)
        self.assertIn("gl-pointed", js)
        self.assertNotIn("method: \"POST\"", js)
        self.assertNotIn("/take-trade/", js)

    def test_the_lock_sends_him_away(self):
        js = self._js()
        self.assertIn('"sv:pin-locked", close', js)


class GollumWearsTheOrbCraftTests(TestCase):
    def _css(self):
        return _src("static", "css", "sauron.css")

    def test_he_anchors_like_the_palantir_but_on_the_left(self):
        css = self._css()
        block = css.split(".gollum-fab {")[1].split("}")[0]
        self.assertIn("left: calc(var(--se-left-chrome) + 18px)", block)
        self.assertIn("bottom: var(--se-bottom-edge)", block)
        # The overlay ladder, not a hand-picked number — the idle veil
        # (--z-dialog) must outrank him or a locked screen keeps a
        # working search box.
        self.assertIn("z-index: var(--z-fab", block)
        ladder = _src("static", "css", "sv-overlay.css")
        fab = int(ladder.split("--z-fab:")[1].split(";")[0].strip())
        dialog = int(ladder.split("--z-dialog:")[1].split(";")[0].strip())
        self.assertLess(fab + 1, dialog)

    def test_his_eyes_look_blink_and_widen(self):
        css = self._css()
        for kf in ("@keyframes glLook", "@keyframes glBlink",
                   "@keyframes glFidget", "@keyframes glRing"):
            self.assertIn(kf, css)
        self.assertIn(".gollum-fab.has-unseen .gl-eye", css)
        self.assertIn(".gollum-fab.is-open .gl-lid", css)

    def test_the_whisper_and_dialog_sit_above_him(self):
        css = self._css()
        for sel in (".gollum-bubble {", ".gollum-dialog {"):
            block = css.split(sel)[1].split("}")[0]
            self.assertIn("bottom: calc(var(--se-bottom-edge) + var(--se-fab-size) + 12px)",
                          block)

    def test_reduced_motion_stills_him_after_his_base_rules(self):
        css = self._css()
        base_at = css.index(".gollum-fab {")
        guard_at = css.rindex("@media (prefers-reduced-motion: reduce)")
        self.assertGreater(guard_at, base_at)
        guard = css[guard_at:guard_at + 700]
        self.assertIn(".gollum-fab", guard)
        self.assertIn(".gollum-dialog .gl-dot", guard)

    def test_light_mode_has_its_own_stone(self):
        self.assertIn("body.light-mode .gollum-fab", self._css())
