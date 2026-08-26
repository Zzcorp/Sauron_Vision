"""The second gate becomes a gate.

The choreography wave gave both lock surfaces ambience and a cascade,
but the gate itself was still a card with four boxes and a button —
nothing answered the operator except the boxes filling. Now the eye
watches: it brightens per digit, recoils on a refusal, flares as the
iris opens. A ring closes as the PIN completes, and a keypad gives the
hand something to press on a touch screen.

Both surfaces share one stylesheet and one behaviour file, because two
lock screens with two personalities teach the wrong reflex on one.

Run with:  python manage.py test tests.test_gate_feel
"""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase


def _src(*parts):
    return Path(settings.BASE_DIR).joinpath(*parts).read_text(
        encoding="utf-8")


class BothSurfacesWearTheGateTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("gate_u",
                                                         password="x")
        self.client.force_login(self.user)

    def _locked(self):
        session = self.client.session
        session["pin_locked"] = True
        session.save()
        return self.client.get("/locked/").content.decode()

    def test_the_standalone_gate_has_iris_ring_and_keypad(self):
        body = self._locked()
        self.assertIn("data-gate-iris", body)
        self.assertIn("data-gate-ring", body)
        self.assertIn("gate-pad", body)
        for digit in "0123456789":
            self.assertIn('data-gate-key="%s"' % digit, body)
        self.assertIn("data-gate-back", body)
        self.assertIn("js/sv-gate.js", body)

    def test_the_in_app_overlay_wears_the_same_gate(self):
        body = self.client.get("/instruments/").content.decode()
        self.assertIn("data-gate-iris", body)
        self.assertIn("gate-pad", body)
        self.assertIn("js/sv-gate.js", body)

    def test_the_eye_still_sits_inside_the_iris(self):
        """The pinned eye is not replaced — it is framed."""
        # The overlay FIRST: a locked session redirects every app page
        # to /locked/, so asking for one after locking gets the gate
        # rather than the page carrying it.
        overlay = self.client.get("/instruments/").content.decode()
        self.assertIn("sauron_eye.svg",
                      overlay.split("data-gate-iris")[1][:600])
        body = self._locked()
        iris = body.split("data-gate-iris")[1].split("</svg>")[0]
        self.assertIn("gate-ring", iris)


class TheGateAnswersTheHandTests(TestCase):
    def _js(self):
        return _src("static", "js", "sv-gate.js")

    def test_the_keypad_sends_the_keystroke_the_keyboard_would(self):
        """One path for a typed digit and a pressed one, or the two
        inputs drift apart and only one of them is tested."""
        js = self._js()
        self.assertIn("KeyboardEvent", js)
        self.assertIn('press(key.getAttribute("data-gate-key")', js)
        self.assertIn('press("Backspace"', js)

    def test_the_boxes_stay_the_source_of_truth(self):
        """The gate READS the filled boxes; it never writes a digit of
        its own — the PIN has exactly one home."""
        js = self._js()
        self.assertIn("It reads, never writes", js)
        self.assertNotIn(".value =", js)

    def test_the_ring_closes_as_the_pin_builds(self):
        js = self._js()
        self.assertIn("strokeDashoffset", js)
        self.assertIn("data-gate-lit", js)

    def test_a_refusal_is_felt_not_just_read(self):
        js = self._js()
        self.assertIn("is-wrong", js)
        self.assertIn("MutationObserver", js)


class TheGatePaintsFromTokensTests(TestCase):
    def _css(self):
        return _src("static", "css", "sauron.css")

    def test_the_gate_block_introduces_no_new_colour(self):
        """Everything after the containment pass paints from tokens —
        two suites scan this section for hex literals."""
        import re
        css = self._css()
        block = css[css.index("/* ── The second gate"):]
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", block), [])

    def test_the_iris_and_keypad_are_styled(self):
        css = self._css()
        for sel in (".gate-iris", ".gate-ring-fill", ".gate-pad",
                    ".gate-key", "@keyframes gateRecoil",
                    "@keyframes gateFlare", "@keyframes gateRipple"):
            self.assertIn(sel, css, sel)

    def test_the_eye_flares_on_the_way_through(self):
        """NOT a clip-path iris: clip-path has no interpolable start
        here, so none-to-circle is a discrete jump that clips nothing —
        and the veil's own opacity fade already owns the exit."""
        css = self._css()
        self.assertIn(".il-overlay.il-out .gate-iris { animation: gateFlare", css)
        self.assertNotIn("gateIrisOut", css)

    def test_the_keystroke_lands_on_a_box_never_on_a_button(self):
        """Both routers ignore keystrokes from buttons (so Enter on
        Disconnect submits the form, not the PIN) — dispatching on the
        pressed key posted every digit into a listener that drops it."""
        js = _src("static", "js", "sv-gate.js")
        self.assertIn("target.dispatchEvent(ev);", js)
        self.assertNotIn("d.activeElement", js)

    def test_the_lit_eye_stands_down_the_idle_animation(self):
        """An animation outranks a declaration on the same property, so
        every brightness level was a dead letter until the bloom and the
        breathe were stood down."""
        css = self._css()
        self.assertIn('.gate-iris[data-gate-lit]:not([data-gate-lit="0"]) .lk-eye',
                      css)
        # The selector appears twice (one per eye); take the text after
        # the LAST occurrence, which is the declaration block itself.
        block = css.rsplit('data-gate-lit="0"', 1)[1][:120]
        self.assertIn("animation: none", block)

    def test_a_refusal_outranks_the_flare(self):
        """Both animate .gate-iris; the later declaration wins, and a
        refusal must never be swallowed by a completed ring's flare."""
        css = self._css()
        self.assertLess(css.index(".gate-iris.is-open { animation: gateFlare"),
                        css.index(".gate-iris.is-wrong { animation: gateRecoil"))

    def test_a_locked_screen_can_always_reach_its_way_out(self):
        """The gate grew; on a short viewport Disconnect — the only exit
        when the PIN is forgotten — fell off with no way to scroll."""
        css = self._css()
        block = css.split(".il-overlay {")[1].split("}")[0]
        self.assertIn("overflow-y: auto", block)
        self.assertIn("justify-content: safe center", block)

    def test_every_new_motion_bows_to_reduced_motion(self):
        css = self._css()
        guard = css[css.rindex("@media (prefers-reduced-motion: reduce)"):]
        for token in (".gate-ring-fill", ".gate-iris.is-wrong",
                      ".gate-key", ".il-overlay.il-out"):
            self.assertIn(token, guard, token)
