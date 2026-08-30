"""EXPAND made the chart disappear.

The report: "when we click expand the graph of an instrument at the moment
the graph just disappears".

The expand state pins the card with `position: fixed` and four insets
measured against the VIEWPORT. That is correct — and it only works if the
viewport is actually the containing block.

FIXED ONCE, WRONGLY, AND THIS FILE IS WHY IT STAYED BROKEN. The first
diagnosis blamed the final keyframe:

    @keyframes fadeInUp { ... to { opacity:1; transform: translateY(0); } }

...and "fixed" it by ending on `transform: none` instead, with tests
asserting exactly that string. Those tests passed. The chart kept
vanishing, and was reported a second time in the same words.

The keyframe was never the problem. The FILL MODE is:

    .fade-in-up { animation: fadeInUp 0.5s ease forwards; }

An animation that is FILLING keeps its element under animation control for
the property it animates. A filling TRANSFORM animation therefore keeps the
element composited and acting as a containing block for every
`position: fixed` descendant — whatever value the final keyframe holds.
`transform: none` under `forwards` is still a filling transform animation.

`.page-content > *` carries the same shape, and it matches every direct
child of every authed page, so this made a containing block out of
essentially every card on the platform. The chart card also carries an
inline `overflow: hidden`, which is what turned "pinned to the wrong box"
into "gone".

The fix is `backwards` — fill only the BEFORE phase, which is all the
staggered `.delay-N` classes need — plus a portal in the widget so the
pinned card is a child of <body> and has no ancestor left to capture it.

LESSON FOR THIS FILE ESPECIALLY: every assertion below used to be a
source-string grep. A grep cannot tell a filling animation from a settled
one, so the suite reported a pass it had not earned, twice. What is
asserted now is the property that actually governs the behaviour.

Run with:  python manage.py test tests.test_expand_does_not_vanish
"""
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import TestCase


def css():
    return (Path(settings.BASE_DIR) / "static" / "css" / "sauron.css"
            ).read_text(encoding="utf-8")


def widget():
    return render_to_string("_partials/chart_widget.html", {
        "chart_id": "t", "symbol": "EURUSD", "height": "420",
        "timeframe": "1d"})


class NoEntryAnimationTrapsPositionFixedTests(TestCase):
    """The two card-wrapping entry animations must not FILL FORWARDS.

    These are the only two selectors on the platform that animate a
    transform on an element which wraps content — every other `forwards`
    animation here runs on an ephemeral thing (a banner clock, the gate
    ripple) that holds no fixed children.
    """

    #: The rules that wrap cards. A filling transform on either of these
    #: captures `position: fixed` for everything inside it.
    WRAPPERS = (".fade-in-up", ".page-content > *")

    def _rule(self, selector):
        """The declaration block for `selector`, or fail."""
        body = css()
        i = body.find(selector + " {")
        if i < 0:
            i = body.find(selector + "{")
        self.assertGreater(i, 0, f"{selector} not found in sauron.css")
        return body[i:body.index("}", i) + 1]

    def test_the_card_wrappers_do_not_fill_forwards(self):
        """THE REAL INVARIANT. `forwards` is what makes the element a
        containing block; the final keyframe never mattered."""
        for sel in self.WRAPPERS:
            rule = self._rule(sel)
            self.assertNotIn("forwards", rule,
                             f"{sel} fills forwards — a filling transform "
                             f"animation is a containing block for fixed "
                             f"descendants whatever its last keyframe says")

    def test_they_fill_backwards_instead(self):
        """`backwards` is required, not merely 'not forwards': the
        `.delay-N` classes stagger these, and without a before-phase fill
        the cards flash at full opacity during their delay."""
        for sel in self.WRAPPERS:
            self.assertIn("backwards", self._rule(sel), sel)

    def test_neither_settles_back_to_invisible(self):
        """With `backwards` the element returns to its OWN style once the
        run ends. A base `opacity: 0` — which is what these carried while
        they filled forwards — would leave every card permanently
        invisible. This is the regression that pairs with the fix."""
        for sel in self.WRAPPERS:
            rule = self._rule(sel)
            self.assertNotIn("opacity: 0", rule, sel)
            self.assertNotIn("opacity:0", rule, sel)

    def test_no_base_transform_is_left_behind_either(self):
        """Same reason, and the one that would re-create the containing
        block directly rather than through an animation."""
        for sel in self.WRAPPERS:
            rule = self._rule(sel)
            decls = [d.strip() for d in rule.split(";")]
            for d in decls:
                self.assertFalse(
                    d.startswith("transform:"),
                    f"{sel} carries a base {d!r} — it settles onto that "
                    f"once the animation stops filling")


class TheChartIsPortalledOutOfItsAncestryTests(TestCase):
    """Belt and braces, and the part that keeps this fixed.

    The CSS fix removes today's containing block. The portal removes the
    CLASS of bug: while pinned, the card is a child of <body>, so no
    ancestor exists to capture it. A `contain: paint` added to some
    wrapper next year cannot silently break the chart again.
    """

    def test_the_widget_portals_while_it_pins(self):
        html = widget()
        self.assertIn("function portalOut", html)
        self.assertIn("document.body.appendChild(container)", html)

    def test_and_puts_it_back(self):
        html = widget()
        self.assertIn("function portalBack", html)
        self.assertIn("portalHome.insertBefore(container, portalGap)", html)

    def test_the_decision_is_made_where_the_pin_is_written(self):
        """One place decides both, or they drift apart — a portal without
        a pin is a chart loose in the page."""
        html = widget()
        self.assertIn("if (weArePinning) portalOut(); else portalBack();",
                      html)

    def test_real_fullscreen_is_not_portalled(self):
        """The top layer is above every containing block, so fullscreen
        needs no portal — but the .sv-chart-fs FALLBACK is an ordinary
        fixed element and does."""
        html = widget()
        self.assertIn("document.fullscreenElement !== container", html)

    def test_a_placeholder_holds_the_gap(self):
        """Otherwise the card collapses and the page jumps the moment the
        chart leaves the flow."""
        html = widget()
        self.assertIn("data-sv-chart-gap", html)


class TheExpandBoxCannotCollapseTests(TestCase):
    """Defence in depth. The transform fix removes the cause; these stop
    any future mis-measurement from producing an empty rectangle instead
    of a bigger chart."""

    def test_every_inset_is_guarded_by_where_its_furniture_sits(self):
        """The top inset always checked that its element was near the top.
        Bottom, left and right did not — so a `.info-panel-wrap` anywhere
        on the page could eat the whole viewport height."""
        html = widget()
        self.assertIn("panel.top > vh * 0.5", html)
        self.assertIn("side.right < vw * 0.5", html)
        self.assertIn("rail.left > vw * 0.5", html)

    def test_a_collapsed_box_falls_back_to_the_viewport(self):
        html = widget()
        self.assertIn("MIN_TALL_H", html)
        self.assertIn("MIN_TALL_W", html)
        self.assertIn("return { top: pad, right: pad, bottom: pad, left: pad };",
                      html)

    def test_a_dead_measurement_never_reaches_the_chart(self):
        """The last line of defence: whatever the box says, the operator
        keeps the chart they already had rather than an empty card."""
        self.assertIn("if (!(total > MIN_TALL_H)) total = CHART_HEIGHT;",
                      widget())

    def test_the_body_still_has_a_floor(self):
        """The toolbar height is now MEASURED (`tbH`), but the floor
        under the body is the same guarantee it always was."""
        self.assertIn("Math.max(120, total - tbH - panesH)", widget())


class TheToolbarIsMeasuredNotAssumedTests(TestCase):
    """`TOOLBAR_H = 36` describes ONE row of a toolbar that wraps to two.

    `.sv-chart-toolbar` is `flex-wrap: wrap` and carries forty-odd
    controls, which need roughly 1200px. The instrument page offers about
    1080 at a 1440-wide window and ~850 with the signals rail open, so it
    wraps — and every pixel of the difference was handed to
    lightweight-charts as canvas height the box did not have. The
    container is `overflow: hidden`, so what got clipped was the bottom of
    the chart, which is where the TIME AXIS lives.

    It also produced a symptom that reads as an expand bug and is not: the
    tall state is nearly viewport-wide, so the toolbar UN-wraps there and
    the axis comes back. The state that was wrong was the normal one.
    """

    def test_the_body_height_uses_the_measured_toolbar(self):
        html = widget()
        self.assertIn("tbEl.offsetHeight", html)
        self.assertIn("total - tbH - panesH", html)

    def test_the_constant_survives_only_as_the_fallback(self):
        """Before the first measurement there is nothing to measure."""
        html = widget()
        self.assertIn("|| TOOLBAR_H", html)

    def test_the_overlays_follow_the_toolbar_instead_of_copying_it(self):
        """The measure readout, legend and countdown each carried their own
        literal 44px. A wrapped toolbar landed on top of all three."""
        html = widget()
        self.assertIn("--sv-toolbar-h", html)
        self.assertIn("calc(var(--sv-toolbar-h, 36px) + 8px)", html)

    def test_no_overlay_still_hardcodes_the_old_offset(self):
        html = widget()
        for dead in ("top: 44px;", "top: 36px; /* below toolbar */"):
            self.assertNotIn(dead, html, dead)


class CollapsedFurnitureStopsChargingItsInsetTests(TestCase):
    """Neither headband hides with `display` or `visibility`.

    Both use `transform: translateX(110%); opacity: 0; pointer-events:
    none`, which leaves the box its full height and its original top — so
    `visibleRect` believed a collapsed band and charged its whole inset.
    Collapsing both bands to win more chart won exactly nothing, which is
    the precise case tallBox()'s measured approach exists to handle.
    """

    def test_zero_opacity_counts_as_hidden(self):
        self.assertIn("parseFloat(cs.opacity) === 0", widget())

    def test_and_so_does_a_box_shoved_off_screen(self):
        """translateX(110%) keeps the height and moves it out of view."""
        html = widget()
        self.assertIn("r.left >= window.innerWidth", html)


class ThePinnedBoxKeepsUpWithTheFurnitureTests(TestCase):
    """A pinned, portalled card never resizes with the page.

    The ResizeObserver watches `container`, whose box while tall is four
    inline insets on a child of <body>. The margin change that opens the
    signals rail, the sidebar minifying, a headband collapsing and the info
    panel sliding away are all invisible to it — so the tall box kept the
    geometry it was born with while the page moved underneath, and at
    z-index 1200 the stale box wins the overlap.
    """

    def test_a_furniture_transition_relayouts_while_tall(self):
        html = widget()
        self.assertIn("transitionend", html)
        self.assertIn("if (viewState !== 'tall') return;", html)

    def test_the_chart_does_not_relayout_on_its_own_transitions(self):
        """Otherwise it feeds itself."""
        self.assertIn(
            "if (ev.target === container || container.contains(ev.target)) return;",
            widget())


class ExpandingKeepsTheZoomTests(TestCase):
    """`fitContent()` on every state change threw away the operator's zoom.

    Expanding to look more closely at a few days refit the whole series —
    the act of expanding destroyed the reason for it.
    """

    def test_the_range_is_captured_before_the_box_changes(self):
        html = widget()
        i = html.find("function setViewState")
        self.assertGreater(i, 0)
        block = html[i:i + 1200]
        self.assertLess(block.find("getVisibleLogicalRange"),
                        block.find("layout();"),
                        "the range must be read before the resize")

    def test_and_restored_after(self):
        html = widget()
        block = html[html.find("function setViewState"):][:1200]
        self.assertIn("setVisibleLogicalRange(keepRange)", block)

    def test_fit_content_remains_the_fallback(self):
        """A chart with no range yet — first paint — still needs fitting."""
        block = widget()[widget().find("function setViewState"):][:1200]
        self.assertIn("fitContent()", block)


class TheChartPaintsFromTokensInBothThemesTests(TestCase):
    """Three colours in the widget ignored the light palette."""

    def test_the_measure_plate_is_not_an_undefined_token(self):
        """`--bg-elevated` is defined nowhere on the platform, so its
        hardcoded near-black fallback always won — and light mode paints
        --text-primary #1a2a1a on it. Black on black."""
        html = widget()
        self.assertNotIn("var(--bg-elevated", html)

    def test_the_active_tint_is_mixed_from_the_live_accent(self):
        """rgba(0,232,104,0.08) is the DARK accent frozen into a literal;
        light mode sets --accent #00994d."""
        html = widget()
        self.assertNotIn("rgba(0, 232, 104, 0.08)", html)
        self.assertIn("color-mix(in srgb, var(--accent) 12%, transparent)",
                      html)

    def test_the_measure_r_uses_the_gold_that_prints(self):
        """--accent-gold fails contrast on white at this size; the ink
        token is defined in both themes, and this widget's own JS already
        prefers it when picking a marker colour."""
        html = widget()
        self.assertIn(
            ".sv-chart-measure .sv-m-r { color: var(--accent-gold-ink,",
            html)
