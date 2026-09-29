"""THE MOTION LAYER (2026-09-29).

The operator, 2026-09-28: "add fade in, slide in, fade out, etc, impressive
animations for the users, same for all the platform". The answer is one
sheet, static/css/sv-motion.css, and one script, static/js/sv-motion.js,
linked from base.html so every authed page gets the same scroll reveal,
swap fades, page-leave fade, panel pop-ins and count-ups.

A test has no viewport and no scroll. What it can hold is the set of
promises that make motion safe on this platform, so a later edit cannot
quietly break one of them:

  A. The wiring. base.html links the sheet once, after sv-tour.css and
     before sv-responsive.css (tests/test_phone_layout.py pins that the
     phone tier stays the last shell sheet), and loads the script once,
     deferred, beside the other sv-*.js scripts.
  B. The sheet. Every selector it animates or transitions is named again
     in its prefers-reduced-motion block with the motion off and any
     opacity-0 rest state back at 1 — the Wall's .desk-row lesson. And no
     rule in it is a FILLING transform animation: sauron.css lines
     535-595 record how a `forwards` fill on a transform keyframe made
     every card the containing block for its position:fixed descendants
     and the chart's expand pin vanished into the card.
  C. The script. It only hides anything behind IntersectionObserver and
     matchMedia guards, arms the 2.5s safety timer, listens for pageshow
     so a bfcache return is not blank, and never calls preventDefault on
     a link — the fade rides the navigation, it does not replace it.
  D. The pages. /command/ and /getting-started/ ship both files; the
     Operations Center's tab buttons carry the swap delay the fade-out
     needs, and its tab bodies carry the reveal and count-up hooks.

Run with:  python manage.py test tests.test_motion
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

BASE = Path(settings.BASE_DIR)
HOST = "127.0.0.1"

REDUCED = "@media (prefers-reduced-motion: reduce)"
PHONE = "@media (max-width: 768px)"


# ── helpers ──────────────────────────────────────────────────────────────

def _read(*parts):
    return BASE.joinpath(*parts).read_text(encoding="utf-8")


def _norm(text):
    return " ".join(text.split())


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _blocks(css):
    """[(prelude, body)] of every top-level block of a comment-free sheet:
    a brace walker, so an @media or @keyframes block comes back whole."""
    out, depth, prelude_at, body_at, prelude = [], 0, 0, 0, ""
    for i, ch in enumerate(css):
        if ch == "{":
            if depth == 0:
                prelude = _norm(css[prelude_at:i])
                body_at = i + 1
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                out.append((prelude, css[body_at:i]))
                prelude_at = i + 1
    assert depth == 0, "unbalanced braces"
    return out


def _rules(css):
    """[(selector, body)] of every innermost rule, whitespace normalised."""
    return [(_norm(m.group(1)), _norm(m.group(2)))
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)]


def _split_top(selector):
    """A selector list split on its top-level commas: a :where() or an
    attribute value keeps its own."""
    parts, depth, cur, quote = [], 0, "", None
    for ch in selector:
        if quote:
            cur += ch
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return [p for p in parts if p]


#: A declaration that puts an element in motion. `animation-delay`,
#: `transition-delay` and friends only shape a motion declared elsewhere;
#: `none` is the reduced block switching one off.
MOVES = re.compile(
    r"(?:^|;)\s*(?:animation|animation-name|transition|transition-property)"
    r"\s*:(?!\s*none\b)")


def _sheet():
    return _strip_comments(_read("static", "css", "sv-motion.css"))


def _outer_and_reduced():
    """([(selector, body)] outside the reduced block, [(selector, body)]
    inside it). Keyframes are not rules and are left out of both."""
    outer, reduced = [], []
    for prelude, body in _blocks(_sheet()):
        if prelude.startswith("@keyframes"):
            continue
        if prelude == REDUCED:
            reduced.extend(_rules(body))
        elif prelude.startswith("@"):
            outer.extend(_rules(body))
        else:
            outer.append((prelude, _norm(body)))
    return outer, reduced


def _top():
    """{selector: body} of the rules outside every @-block."""
    return {prelude: _norm(body) for prelude, body in _blocks(_sheet())
            if not prelude.startswith("@")}


def _keyframes():
    """{name: [(frame selector, body)]} for every @keyframes block."""
    out = {}
    for prelude, body in _blocks(_sheet()):
        if prelude.startswith("@keyframes"):
            out[prelude.split()[1]] = _rules(body)
    return out


def _script():
    return _read("static", "js", "sv-motion.js")


def _code(js):
    """The script minus its comments and strings, for the calls it makes."""
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    js = re.sub(r"//[^\n]*", "", js)
    return re.sub(r"""(['"])(?:\\.|(?!\1).)*\1""", "''", js)


# ── A. the wiring ────────────────────────────────────────────────────────

class ShellWiringTests(SimpleTestCase):

    def test_base_links_the_sheet_once_between_the_tour_and_the_phone(self):
        base = _read("templates", "base.html")
        self.assertEqual(base.count("'css/sv-motion.css'"), 1)
        self.assertIn('<link rel="stylesheet" href="{% static '
                      "'css/sv-motion.css' %}\">", base)
        at = base.index("'css/sv-motion.css'")
        for sheet in ("'css/sauron.css'", "'css/sv-overlay.css'",
                      "'css/sv-tour.css'"):
            self.assertGreater(at, base.index(sheet), sheet)
        self.assertLess(at, base.index("'css/sv-responsive.css'"))
        self.assertLess(at, base.index("{% block extra_css %}"))
        self.assertLess(at, base.index("</head>"))

    def test_base_loads_the_script_once_deferred(self):
        base = _read("templates", "base.html")
        self.assertEqual(base.count("'js/sv-motion.js'"), 1)
        self.assertIn('<script src="{% static \'js/sv-motion.js\' %}" defer>'
                      '</script>', base)
        # Beside the other deferred shell scripts, inside <head>.
        self.assertLess(base.index("'js/sv-motion.js'"), base.index("</head>"))
        self.assertGreater(base.index("'js/sv-motion.js'"),
                           base.index("'js/sv-overlay.js'"))

    def test_the_sheet_and_the_script_exist(self):
        self.assertTrue((BASE / "static" / "css" / "sv-motion.css").exists())
        self.assertTrue((BASE / "static" / "js" / "sv-motion.js").exists())


# ── B. the sheet ─────────────────────────────────────────────────────────

class MotionSheetTests(SimpleTestCase):

    def test_the_sheet_animates_something(self):
        outer, _reduced = _outer_and_reduced()
        moving = [s for s, b in outer if MOVES.search(b)]
        self.assertGreaterEqual(len(moving), 8, moving)

    def test_the_reduced_block_names_every_selector_that_moves(self):
        """Every selector with an animation or transition outside the
        reduced block appears inside it, or a wildcard rule there covers
        it. The Wall's lesson: `animation: none` alone is not enough for a
        class whose rest state is opacity 0, so the block is checked below
        for the restorations too."""
        outer, reduced = _outer_and_reduced()
        self.assertTrue(reduced, "the sheet has no %s block" % REDUCED)
        named = set()
        for sel, _body in reduced:
            named.update(_split_top(sel))
        wildcard = "*" in named
        missing = []
        for sel, body in outer:
            if not MOVES.search(body):
                continue
            for part in _split_top(sel):
                if part not in named and not wildcard:
                    missing.append(part)
        self.assertEqual(
            missing, [],
            "these selectors animate or transition but the reduced-motion "
            "block never names them, so a reader who asked for less motion "
            "still gets it: %r" % missing)

    def test_the_reduced_block_switches_the_motion_off(self):
        _outer, reduced = _outer_and_reduced()
        for sel, body in reduced:
            self.assertFalse(
                MOVES.search(body),
                "%s: the reduced block itself declares motion: %s" % (sel, body))
            # Off, or a hidden rest state put back: one of the two.
            self.assertRegex(
                body, r"(animation|transition)\s*:\s*none|opacity\s*:\s*1\b",
                "%s: the reduced block names it but turns nothing off and "
                "restores nothing" % sel)

    def test_the_reduced_block_restores_every_hidden_rest_state(self):
        """A rest state at opacity 0 must come back to 1 under reduced
        motion, or the element is simply gone for that reader."""
        outer, reduced = _outer_and_reduced()
        hidden = [sel for sel, body in outer
                  if re.search(r"(?:^|;)\s*opacity\s*:\s*0\s*(?:;|$)", body)]
        self.assertTrue(hidden, "the sheet hides nothing, which means the "
                                "reveal and the swap fade are gone")
        restored = {sel for sel, body in reduced
                    if re.search(r"(?:^|;)\s*opacity\s*:\s*1\s*(?:;|$)", body)}
        for sel in hidden:
            self.assertIn(sel, restored,
                          "%s rests at opacity 0 and the reduced block does "
                          "not put it back to 1" % sel)

    def test_no_filling_transform_animation(self):
        """sauron.css, lines 535-595: a transform animation that FILLS
        (animation-fill-mode forwards or both) keeps the element under
        animation control after it ends, and a browser treats an element
        under a transform animation as the containing block for every
        position:fixed descendant. The chart's expand pin pinned itself to
        the card instead of the viewport and was clipped away — "the
        graph just disappears". The final keyframe's value is irrelevant;
        the fill mode is the whole problem. So: no `forwards`, no `both`,
        anywhere in this sheet, and no animation-fill-mode declaration at
        all — every keyframe here runs with the default fill of none."""
        css = _sheet()
        self.assertIsNone(
            re.search(r"animation[^;{}]*\b(forwards|both)\b", css),
            "a filling animation in the motion sheet")
        self.assertNotIn("animation-fill-mode", css)
        # And the transforms this sheet does animate all END at none.
        frames = _keyframes()
        self.assertTrue(frames)
        for name, rules in frames.items():
            if not any("transform" in body for _sel, body in rules):
                continue
            last = [body for sel, body in rules if sel in ("to", "100%")]
            self.assertTrue(last, name)
            self.assertRegex(last[-1], r"transform\s*:\s*none",
                             "@keyframes %s moves a transform and does not "
                             "end at none" % name)

    def test_the_reveal_is_a_transition_that_ends_at_none(self):
        rv = _top()
        self.assertIn(".sv-rv", rv)
        self.assertIn(".sv-rv.in", rv)
        self.assertIn("opacity: 0", rv[".sv-rv"])
        self.assertIn("transition:", rv[".sv-rv"])
        self.assertIn("var(--sv-i", rv[".sv-rv"])
        self.assertIn("opacity: 1", rv[".sv-rv.in"])
        self.assertIn("transform: none", rv[".sv-rv.in"])

    def test_the_phone_tier_shortens_the_rise_and_drops_the_leave_fade(self):
        bodies = [body for prelude, body in _blocks(_sheet()) if prelude == PHONE]
        self.assertEqual(len(bodies), 1)
        rules = dict(_rules(bodies[0]))
        self.assertIn("8px", rules[".sv-rv"])
        self.assertIn("transform: none", rules["body.sv-leaving .page-content"])
        self.assertIn("opacity: 1", rules["body.sv-leaving .page-content > *"])

    def test_the_leave_fade_rides_the_children_not_the_wrapper(self):
        """.page-content is born with .fade-in, an opacity animation that
        fills forwards (sauron.css). An animation beats a plain
        declaration, so opacity on the wrapper never takes; and swapping
        the animation out in the same change was measured to snap the
        opacity to 0 with no transition. The fade lives on the children,
        the slide on the wrapper, and no rule here touches `animation`."""
        top = _top()
        wrapper = top["body.sv-leaving .page-content"]
        kids = top["body.sv-leaving .page-content > *"]
        self.assertNotIn("opacity", wrapper)
        self.assertNotIn("animation", wrapper)
        self.assertIn("transform: translateY(-6px)", wrapper)
        self.assertIn("opacity: 0", kids)
        self.assertRegex(kids, r"transition: opacity")

    def test_the_swap_fade_rides_the_htmx_classes_at_zero_weight(self):
        """htmx 1.9 adds .htmx-swapping to the target for the swap delay
        and .htmx-added to each new node until settle. The transition has
        to live on the node and at zero weight, so a node with its own
        transition keeps it instead of losing its hover motion."""
        css = _sheet()
        self.assertIn(".htmx-swapping { opacity: 0; }", _norm(css))
        self.assertIn("> .htmx-added { opacity: 0; }", _norm(css))
        self.assertRegex(css, r":where\(#ocTabBody[^{]*\)\s*\{\s*transition")

    def test_the_sheet_parses(self):
        """No nested comment, balanced braces, no prose escaped into the
        rules: tests/test_inline_js_parses.py sweeps every sheet the same
        way; this is the same check, named here so this module fails on
        its own file."""
        raw = _read("static", "css", "sv-motion.css")
        self.assertNotRegex(raw, r"/\*(?:(?!\*/).)*/\*", "a comment inside a comment")
        css = re.sub(r"""(['"])(?:\\.|(?!\1).)*\1""", "''", _sheet())
        self.assertEqual(css.count("{"), css.count("}"))


# ── C. the script ────────────────────────────────────────────────────────

class MotionScriptTests(SimpleTestCase):

    def test_it_hides_nothing_without_the_observer_and_the_preference(self):
        js = _script()
        self.assertIn("IntersectionObserver", js)
        self.assertRegex(js, r"typeof w\.IntersectionObserver === 'function'")
        self.assertIn("matchMedia", js)
        self.assertIn("(prefers-reduced-motion: reduce)", js)
        self.assertIn("(max-width: 768px)", js)
        # The guard gates the scan, not just the observer.
        self.assertRegex(js, r"if \(!hasIO \|\| reduce\) return;")

    def test_the_safety_timer_is_armed_before_anything_is_hidden(self):
        """2.5s after a scan, whatever that scan hid and the observer never
        reached is shown anyway; the timer is set before the first class
        goes on, so a scan that throws halfway still gets undone."""
        js = _script()
        self.assertIn("SAFETY_MS = 2500", js)
        scan = js[js.index("function scanReveal"):js.index("function fmt")]
        self.assertIn("}, SAFETY_MS);", scan)
        self.assertLess(scan.index("SAFETY_MS);"),
                        scan.index("classList.add('sv-rv')"))
        # And the catch: a scan that threw reveals everything.
        self.assertIn("catch (e) {\n      revealAll();", scan)

    def test_the_leave_fade_rides_the_navigation(self):
        js = _script()
        self.assertIn("'pageshow'", js)
        self.assertIn("e.persisted", js)
        self.assertIn("classList.add('sv-leaving')", js)
        code = _code(js)
        self.assertNotIn("preventDefault", code)
        self.assertNotIn("location.href", code)
        self.assertNotIn("location.assign", code)
        self.assertNotIn("stopPropagation", code)

    def test_the_leave_fade_skips_what_is_not_a_plain_navigation(self):
        js = _script()
        for guard in ("a.target && a.target !== '_self'",
                      "hasAttribute('download')",
                      "href.charAt(0) === '#'",
                      "e.metaKey || e.ctrlKey || e.shiftKey || e.altKey",
                      "[data-no-fade]", "form", "indexOf('hx-') === 0",
                      "sameOrigin(a)", "e.defaultPrevented"):
            self.assertIn(guard, js, guard)

    def test_the_count_up_can_never_print_nan(self):
        js = _script()
        self.assertIn("data-sv-count", js)
        self.assertIn("isFinite(target)", js)
        self.assertIn("toLocaleString('en-US'", js)
        # Under reduced motion the final value is written, not animated.
        self.assertRegex(js, r"if \(reduce \|\| typeof w\.requestAnimationFrame")

    def test_a_live_refresh_does_not_replay_the_reveal(self):
        js = _script()
        self.assertIn("htmx:afterSettle", js)
        self.assertIn("data-sv-motion-seen", js)
        self.assertIn("triggeringEvent", js)
        self.assertIn("sv:live-swapped", js)

    def test_every_swapped_in_node_fades_alike(self):
        """Measured 2026-09-29: with the fade as a transition on the node,
        a swapped-in .card appeared in one step (its own transition list
        has no opacity in it) while the strip beside it faded. So the
        script answers htmx:afterSwap by putting .sv-in, an animation, on
        each .htmx-added node, and the sheet names .sv-in."""
        js = _script()
        self.assertIn("htmx:afterSwap", js)
        self.assertIn("contains('htmx-added')", js)
        self.assertIn("'sv-in'", js)
        self.assertIn(".sv-in { animation:", _norm(_sheet()))


# ── D. the pages ─────────────────────────────────────────────────────────

class RenderedPagesTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user("motion_u", password="x")
        self.client.force_login(self.user)

    def _get(self, url):
        resp = self.client.get(url, HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 200, url)
        return resp.content.decode("utf-8")

    def test_the_command_center_and_getting_started_ship_the_layer(self):
        for name in ("command_center", "getting_started"):
            body = self._get(reverse(name))
            self.assertEqual(body.count("css/sv-motion.css"), 1, name)
            self.assertEqual(body.count("js/sv-motion.js"), 1, name)
            self.assertLess(body.index("css/sv-tour.css"),
                            body.index("css/sv-motion.css"), name)
            self.assertLess(body.index("css/sv-motion.css"),
                            body.index("css/sv-responsive.css"), name)
            self.assertIn('<div class="page-content fade-in">', body, name)

    def test_the_tab_buttons_carry_the_swap_delay_and_nothing_else_does(self):
        body = self._get(reverse("command_center"))
        self.assertEqual(body.count('hx-swap="innerHTML swap:120ms"'), 4)
        # The tab body's own load trigger keeps no delay: a delayed first
        # paint is a delay for nobody.
        self.assertRegex(body, r'id="ocTabBody"[^>]*hx-swap="innerHTML"')

    def test_the_tab_bodies_carry_the_reveal_and_count_hooks(self):
        live = self._get("/command/tab/live/")
        self.assertGreaterEqual(live.count("data-sv-reveal"), 2)
        # A number, or the platform's em-dash for "nothing to count"
        # (views_command.py renders DASH with no bot configured): the
        # script counts the first and leaves the second exactly as it is.
        honest = r"^(-?\d+(\.\d+)?|—)$"
        bots = self._get("/command/tab/bots/")
        self.assertGreaterEqual(bots.count("data-sv-reveal"), 1)
        self.assertGreaterEqual(bots.count("data-sv-count="), 4)
        for m in re.finditer(r'data-sv-count="([^"]*)"', bots):
            self.assertRegex(m.group(1), honest,
                             "a count hook that is neither a number nor the "
                             "unmeasured mark: %r" % m.group(1))
        history = self._get("/command/tab/history/")
        self.assertGreaterEqual(history.count("data-sv-reveal"), 2)
        for m in re.finditer(r'data-sv-count="([^"]*)"', history):
            self.assertRegex(m.group(1), honest)
