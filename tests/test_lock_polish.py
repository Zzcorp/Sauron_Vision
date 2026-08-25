"""The lock screens learn choreography — and the overlay learns to listen.

The functional heart: the overlay's digit router listened on the
overlay ELEMENT, but keys land on <body> when nothing inside has focus
— the PIN could not be typed until a box was clicked. It routes from
the document now, exactly like /locked/. The rest is paint with
contracts: filled boxes answer, wrong PINs shake, controls cascade in,
the departure reads as a gate opening — all behind reduced-motion
guards, all without touching the opaque-veil invariant.

Run with:  python manage.py test tests.test_lock_polish
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase


def _src(*parts):
    return Path(settings.BASE_DIR).joinpath(*parts).read_text(
        encoding="utf-8")


class OverlayTypesAnywhereTests(TestCase):
    def test_the_router_listens_on_the_document_while_locked(self):
        js = _src("static", "js", "idle-lock.js")
        i = js.index('d.addEventListener("keydown", function (e) {\n'
                     '            if (!isLocked) return;')
        self.assertGreater(i, 0)
        router = js[i:i + 700]
        self.assertIn('/^[0-9]$/.test(e.key)', router)
        self.assertIn('pinInsert(e.key)', router)
        self.assertIn('e.key === "Backspace"', router)
        self.assertIn("submitPin()", router)

    def test_the_router_yields_to_buttons_and_focused_boxes(self):
        """Enter on Disconnect must still submit the logout form, and a
        focused box's own keystroke must not insert twice."""
        js = _src("static", "js", "idle-lock.js")
        i = js.index('if (!isLocked) return;')
        router = js[i:i + 700]
        self.assertIn('t.closest("a, button")', router)
        self.assertIn('t.hasAttribute("data-il-pin")) return;', router)

    def test_filled_boxes_and_misses_speak_on_both_surfaces(self):
        js = _src("static", "js", "idle-lock.js")
        self.assertIn("paintFill", js)
        self.assertIn('classList.add("pin-shake")', js)
        page = _src("templates", "dashboard", "locked.html")
        self.assertIn("paintFill", page)
        self.assertIn('classList.add("pin-shake")', page)


class ChoreographyTests(TestCase):
    def _css(self):
        return _src("static", "css", "sauron.css")

    def test_the_fill_and_shake_have_one_shared_vocabulary(self):
        css = self._css()
        self.assertIn(".lk-row input.has-val, .il-card input.has-val", css)
        self.assertIn("@keyframes pinFill", css)
        self.assertIn("@keyframes pinShake", css)

    def test_the_locked_room_breathes_but_the_card_stays_on_top(self):
        css = self._css()
        self.assertIn(".lk-page::before", css)
        self.assertIn(".lk-page::after", css)
        self.assertIn("@keyframes lkGridDrift", css)
        self.assertIn("@keyframes lkAmbient", css)
        self.assertIn(".lk-card { position: relative; z-index: 1; }", css)

    def test_the_veil_stays_opaque_texture_rides_above_it(self):
        """The overlay's background is the lock's whole job — the new
        grid is a LAYER on ::before, never a change to the veil."""
        css = self._css()
        self.assertIn("background: var(--bg-dark, #030806);", css)
        self.assertIn(".il-overlay::before", css)
        self.assertIn(".il-overlay.il-in::before { opacity: 1; }", css)

    def test_both_gates_cascade_awake_in_the_same_rhythm(self):
        css = self._css()
        self.assertIn(".lk-reveal .lk-row { transition:", css)
        self.assertIn(".lk-reveal .lk-unlock { transition:", css)
        self.assertIn(".il-overlay.is-awake .il-card.il-wake", css)

    def test_every_new_animation_bows_to_reduced_motion(self):
        css = self._css()
        block = css.split("@media (prefers-reduced-motion: reduce)")
        joined = "".join(b[:600] for b in block[1:])
        for token in (".lk-page::before", ".lk-card .lk-eye",
                      ".pin-shake", ".il-overlay::before",
                      ".il-card.il-wake"):
            self.assertIn(token, joined, token)

    def test_the_departure_is_a_gate_opening_not_a_jump_cut(self):
        page = _src("templates", "dashboard", "locked.html")
        self.assertIn("lkLeave .4s", page)
        self.assertIn("}, 420);", page)
        self.assertIn(".lk-page.lk-leave::before", page)


class GateStillStandsTests(TestCase):
    """The polish must not loosen anything the lock tests pin."""

    def test_the_locked_page_still_types_without_a_click(self):
        page = _src("templates", "dashboard", "locked.html")
        self.assertIn('document.addEventListener("keydown"', page)
        self.assertIn("focusFirstEmpty();", page)

    def test_the_page_still_renders_for_a_locked_session(self):
        user = get_user_model().objects.create_user("lockp_u",
                                                    password="x")
        self.client.force_login(user)
        session = self.client.session
        session["pin_locked"] = True
        session.save()
        body = self.client.get("/locked/").content.decode()
        self.assertIn("lk-card fade-in-up", body)
        self.assertIn("SECOND GATE", body)
