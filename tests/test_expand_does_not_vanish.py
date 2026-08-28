"""EXPAND made the chart disappear.

The report: "when we click expand the graph of an instrument at the moment
the graph just disappears".

The expand state pins the card with `position: fixed` and four insets
measured against the VIEWPORT. That is correct — and it only works if the
viewport is actually the containing block.

    .fade-in-up { transform: translateY(12px);
                  animation: fadeInUp 0.5s ease forwards; }
    @keyframes fadeInUp { ... to { opacity:1; transform: translateY(0); } }

`forwards` makes the final keyframe persist, and ANY transform other than
`none` makes that element the containing block for every `position: fixed`
descendant — and clips them to its own overflow. The chart card carries
both `fade-in-up` and an inline `overflow: hidden`, so the expanded chart
pinned itself inside a 460px card and was clipped away.

`translateY(0)` and `none` render identically, which is why this survived:
nothing about the page looked wrong until something inside a card tried to
pin itself to the screen.

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

    def test_fade_in_up_settles_on_no_transform(self):
        self.assertIn("to{opacity:1;transform:none;}", css())

    def test_page_enter_settles_on_no_transform(self):
        body = css()
        i = body.find("@keyframes pageEnterUp")
        self.assertGreater(i, 0)
        self.assertIn("transform: none;", body[i:i + 260])

    def test_neither_ends_on_translate_zero(self):
        """Visually identical, and not equivalent: one is a containing
        block for fixed descendants and the other is not."""
        body = css()
        for name in ("@keyframes fadeInUp", "@keyframes pageEnterUp"):
            i = body.find(name)
            self.assertGreater(i, 0, name)
            block = body[i:i + 260]
            tail = block[block.find("to"):]
            self.assertNotIn("translateY(0)", tail, name)


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
        self.assertIn("Math.max(120, total - TOOLBAR_H - panesH)", widget())
