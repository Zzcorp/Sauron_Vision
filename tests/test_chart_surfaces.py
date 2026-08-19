"""A chart must survive a theme swap, a phone, and an empty series.

This platform draws charts four ways — inline SVG columns, the .oc-donut
family, the .oc-sparkline path renderer, and lightweight-charts for candles —
and every one of them had already broken at least one of the same three rules
before this file existed:

  * A COORDINATE SPACE THE CSS CANNOT MOVE. The cost-trend card sized its
    bars as a percentage of a fixed-height flex column that also held two
    text labels, so the tallest bar pushed the date row out through the
    bottom of the card. Geometry belongs in a viewBox.
  * TOKENS, NOT HEX. Thirteen donuts carried their own '#00e868' palette, so
    in light mode — where --accent is #00994d — every donut painted the dark
    theme's green next to a card that had already changed colour.
  * AN HONEST EMPTY. A day with no reading and a day measured at zero drew
    the same nothing; a flat series was pinned to the floor of its box by a
    `span || 1` fallback; a one-point series rendered an empty frame with no
    explanation.

Mostly static analysis. The render checks use the template loader only — no
database, no client, no viewport.

Run with:  python manage.py test tests.test_chart_surfaces
"""
import re
from pathlib import Path

from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase

CSS_PATH = Path(settings.BASE_DIR) / "static" / "css" / "sauron.css"
TEMPLATE_ROOTS = [
    Path(settings.BASE_DIR) / "templates",
    Path(settings.BASE_DIR) / "bot_program" / "templates",
]

#: The shared chart implementations. Everything else should include one of
#: these rather than hand-rolling a fifth way to draw a series.
CHART_PARTIALS = (
    "_partials/chart_bars.html",
    "_partials/chart_donut.html",
    "_partials/chart_line.html",
)

#: Classes that mark an <svg> as a chart rather than an icon.
CHART_SVG_CLASSES = ("oc-donut", "oc-sparkline", "sv-bars-svg")

#: `.tm-edges` is the system-map wiring overlay. Its paths are computed in JS
#: from measured DOM positions, so it draws in CSS pixels ON PURPOSE — a
#: viewBox there would rescale coordinates that are already correct.
VIEWBOX_EXEMPT = ("tm-edges",)


def _css():
    return CSS_PATH.read_text(encoding="utf-8")


def _strip_css_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _templates():
    for root in TEMPLATE_ROOTS:
        if root.exists():
            yield from sorted(root.rglob("*.html"))


def _strip_django_tags(markup):
    """Remove {% %} and {{ }} before scanning HTML tags.

    A `{% if pnl > 0 %}` inside an attribute carries a bare `>`, which ends
    an HTML tag as far as any regex is concerned.
    """
    markup = re.sub(r"\{%.*?%\}", "", markup, flags=re.S)
    return re.sub(r"\{\{.*?\}\}", "", markup, flags=re.S)


def _strip_comments_and_fallbacks(text):
    """Drop the places a hex literal is legitimate.

    Two of them: a `var(--token, #hex)` fallback, which only paints when the
    token is missing entirely, and the same idea in JS —
    `token('--accent', '#00e868')` — needed because a <canvas> cannot resolve
    a custom property. Both keep the token as the source of truth.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    text = re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "",
                  text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"var\([^()]*\)", "var()", text)
    text = re.sub(r"token\([^()]*\)", "token()", text)
    return text


HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def _bars(values, labels=None):
    """The shape every caller of chart_bars.html hands over."""
    return [
        {
            "label": (labels[i] if labels else "d%d" % i),
            "value": v,
            "display": ("—" if v is None else "$%.4f" % v),
            "note": "2 tasks",
        }
        for i, v in enumerate(values)
    ]


class ViewBoxTests(SimpleTestCase):
    """A chart with no viewBox is a chart whose numbers the CSS can move."""

    def test_every_chart_svg_declares_a_view_box(self):
        offenders = []
        for path in _templates():
            markup = _strip_django_tags(path.read_text(encoding="utf-8"))
            for tag in re.finditer(r"<svg\b[^>]*>", markup, flags=re.S):
                text = tag.group(0)
                if any(x in text for x in VIEWBOX_EXEMPT):
                    continue
                if "viewBox" not in text:
                    offenders.append((path.name, " ".join(text.split())[:90]))
        self.assertEqual(
            offenders, [],
            "an <svg> with no viewBox has no coordinate space of its own, so "
            "its geometry is whatever the CSS box happens to be that render: "
            "%r" % offenders)

    def test_the_chart_partials_also_state_how_they_scale(self):
        """viewBox alone still leaves preserveAspectRatio to the default."""
        for name in CHART_PARTIALS:
            src = self._partial(name)
            svgs = re.findall(r"<svg\b[^>]*>", src, flags=re.S)
            self.assertTrue(svgs, "%s draws no SVG" % name)
            for tag in svgs:
                self.assertIn("viewBox", tag, "%s: %s" % (name, tag[:80]))
                self.assertIn(
                    "preserveAspectRatio", tag,
                    "%s leaves the fit to the default (xMidYMid meet), which "
                    "letterboxes a chart that is meant to fill its card: %s"
                    % (name, tag[:80]))

    def test_no_chart_pins_itself_to_a_pixel_width(self):
        """Fluid width is the whole point; height may be fixed."""
        css = _strip_css_comments(_css())
        for selector in (r"\.sv-bars-svg", r"\.oc-sparkline",
                         r"\.oc-donut-wrap \.oc-donut"):
            for body in re.findall(selector + r"\s*\{([^}]*)\}", css):
                self.assertNotRegex(
                    body, r"(?<!max-)width\s*:\s*\d+px",
                    "%s sets a px width, so it cannot shrink with the card "
                    "it lives in" % selector)

    def _partial(self, name):
        for root in TEMPLATE_ROOTS:
            p = root / name
            if p.exists():
                return p.read_text(encoding="utf-8")
        self.fail("missing chart partial: %s" % name)


class TokenPaletteTests(SimpleTestCase):
    """A hex that survives a theme swap is a chart that lies in light mode."""

    def test_no_chart_partial_carries_a_hardcoded_colour(self):
        offenders = []
        for name in CHART_PARTIALS:
            src = None
            for root in TEMPLATE_ROOTS:
                if (root / name).exists():
                    src = (root / name).read_text(encoding="utf-8")
            self.assertIsNotNone(src, "missing chart partial: %s" % name)
            for hit in HEX.findall(_strip_comments_and_fallbacks(src)):
                offenders.append((name, hit))
        self.assertEqual(
            offenders, [],
            "a colour written as hex does not move when --accent does, so "
            "the chart keeps the dark theme's palette on a white card: %r"
            % offenders)

    def test_no_chart_css_rule_carries_a_hardcoded_colour(self):
        """Scoped to the chart classes — the rest of the sheet is not ours."""
        css = _strip_css_comments(_css())
        offenders = []
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            sel = selector.strip()
            if not re.search(r"\.(sv-bars|sv-bar|sv-line|oc-donut|oc-sparkline|oc-tone)",
                             sel):
                continue
            stripped = re.sub(r"var\([^()]*\)", "var()", body)
            for hit in HEX.findall(stripped):
                offenders.append((sel[:60], hit))
        self.assertEqual(
            offenders, [],
            "chart CSS must paint from the tokens only: %r" % offenders)

    def test_the_donut_tones_are_all_defined(self):
        """The renderer picks a tone class; every one it can pick must exist."""
        css = _strip_css_comments(_css())
        for tone in ("accent", "red", "gold", "blue", "purple", "muted"):
            self.assertRegex(
                css, r"\.oc-tone-%s\s*\{[^}]*stroke\s*:" % tone,
                "the donut renderer can assign oc-tone-%s but no rule "
                "strokes it, so that slice draws in the default colour"
                % tone)
            self.assertRegex(
                css, r"span\.oc-tone-%s\s*\{[^}]*background\s*:" % tone,
                "the legend swatch for oc-tone-%s has no fill, so the key "
                "cannot be matched to its slice" % tone)

    def test_both_themes_are_addressed(self):
        css = _strip_css_comments(_css())
        for selector in (".oc-donut-track", ".sv-bars-base",
                         ".oc-sparkline-ref"):
            self.assertIn(
                "body.light-mode %s" % selector, css,
                "%s was tuned against a dark card and has no light-mode "
                "restatement, so it is invisible or wrong in the other theme"
                % selector)


class OneImplementationTests(SimpleTestCase):
    """Thirteen copies of a renderer is thirteen places to fix a bug."""

    #: system_map builds the wiring overlay between nodes from measured DOM
    #: positions. It is a diagram of the platform, not a plot of a series,
    #: and it has no series to hand to a chart partial.
    SVG_BUILDERS_EXEMPT = {"chart_donut.html", "chart_line.html",
                           "system_map.html"}

    def test_no_template_hand_rolls_the_donut_renderer_any_more(self):
        offenders = [
            p.name for p in _templates()
            if "createElementNS" in p.read_text(encoding="utf-8")
            and p.name not in self.SVG_BUILDERS_EXEMPT
        ]
        self.assertEqual(
            offenders, [],
            "these templates build SVG segments by hand instead of including "
            "a chart partial — the copies drift, and every copy carried its "
            "own hardcoded palette: %r" % offenders)

    def test_each_renderer_is_defined_exactly_once(self):
        for fn in ("svRenderDonuts", "svRenderLines"):
            defs = [p.name for p in _templates()
                    if ("window.%s = function" % fn)
                    in p.read_text(encoding="utf-8")]
            self.assertEqual(
                len(defs), 1,
                "%s is defined in %r — a second definition wins by load "
                "order, which is not a decision anyone made" % (fn, defs))

    def test_no_two_cards_share_a_gradient_id(self):
        """An SVG id is document-global; a duplicate silently rebinds a fill."""
        seen = {}
        for path in _templates():
            src = path.read_text(encoding="utf-8")
            for gid in re.findall(r'<linearGradient[^>]*\bid="([^"{}]+)"', src):
                seen.setdefault(gid, []).append(path.name)
        clashes = {k: v for k, v in seen.items() if len(v) > 1}
        self.assertEqual(
            clashes, {},
            "two cards define the same gradient id, so whichever renders "
            "first owns the fill for both: %r" % clashes)


class AxisHonestyTests(SimpleTestCase):
    """A number with no axis is a number the reader has to guess at."""

    INCLUDE = re.compile(
        r'\{%\s*include\s+"_partials/chart_(bars|line)\.html"(.*?)%\}', re.S)

    def test_every_chart_include_names_both_axes(self):
        offenders = []
        for path in _templates():
            src = path.read_text(encoding="utf-8")
            for kind, args in self.INCLUDE.findall(src):
                if "unit=" not in args:
                    offenders.append((path.name, kind, "unit"))
                if "when=" not in args:
                    offenders.append((path.name, kind, "when"))
        self.assertEqual(
            offenders, [],
            "a chart that does not say what it measures or over what window "
            "is an unlabelled number: %r" % offenders)

    def test_every_chart_include_offers_an_empty_state(self):
        offenders = []
        for path in _templates():
            src = path.read_text(encoding="utf-8")
            for match in self.INCLUDE.finditer(src):
                args = match.group(2)
                if "empty=" in args:
                    continue
                # An outer {% if %} may already carry the empty message.
                head = src[:match.start()].rstrip().splitlines()[-3:]
                if any("{% if" in line for line in head):
                    continue
                offenders.append((path.name, match.group(1)))
        self.assertEqual(
            offenders, [],
            "a chart with no data and no message is a blank box: %r"
            % offenders)

    def test_the_tick_row_is_allowed_to_shrink(self):
        """min-width:0 is what stops seven mono labels from setting a floor
        the card cannot go under — the original cost-trend scroll bug."""
        css = _strip_css_comments(_css())
        body = re.search(r"\.sv-bars-axis span\s*\{([^}]*)\}", css)
        self.assertIsNotNone(body, ".sv-bars-axis span is not styled")
        self.assertRegex(body.group(1), r"min-width\s*:\s*0")
        self.assertRegex(body.group(1), r"text-overflow\s*:\s*ellipsis")


class CostTrendRenderTests(SimpleTestCase):
    """The named defect: /ai/ and /ai-tasks/ cost trend, every series shape.

    Each of these produced a broken frame before: a peak bar that overflowed
    its card, a row of mono labels that would not shrink, and a zero that
    could not be told apart from a day nobody measured.
    """

    BASE = dict(unit="USD of API spend per day", when="last 7 days")

    def _render(self, values, **extra):
        real = [abs(v) for v in values if v is not None]
        ctx = dict(self.BASE, bars=_bars(values),
                   max=(max(real) if real else 0))
        ctx.update(extra)
        return render_to_string("_partials/chart_bars.html", ctx)

    def assert_no_broken_numbers(self, markup, label):
        for token in ("NaN", "Infinity", 'height="-', 'width="-', 'x="-'):
            self.assertNotIn(
                token, markup,
                "%s put %r into the markup — an SVG attribute that is not a "
                "number draws nothing at all" % (label, token))

    def test_a_full_week_draws_one_bar_per_day(self):
        markup = self._render([0.001, 0.02, 0.0, 0.31, 0.05, 0.0, 0.12])
        self.assert_no_broken_numbers(markup, "seven days")
        # Five non-zero readings; the two measured zeros sit on the baseline.
        self.assertEqual(markup.count("<rect"), 5)
        self.assertIn('class="sv-bars-base"', markup)

    def test_one_data_point_still_draws_a_bar(self):
        markup = self._render([0.42])
        self.assert_no_broken_numbers(markup, "one point")
        self.assertEqual(markup.count("<rect"), 1,
                         "a single reading must render as a bar, not as an "
                         "empty frame")

    def test_no_data_points_say_so(self):
        markup = render_to_string(
            "_partials/chart_bars.html",
            dict(self.BASE, bars=[], max=0,
                 empty="No agent calls in the last 7 days."))
        self.assert_no_broken_numbers(markup, "no points")
        self.assertIn("No agent calls in the last 7 days.", markup)
        self.assertNotIn("<rect", markup)

    def test_a_flat_series_does_not_divide_by_zero(self):
        markup = self._render([0.05] * 7)
        self.assert_no_broken_numbers(markup, "flat series")
        self.assertEqual(markup.count("<rect"), 7)

    def test_an_all_zero_series_says_it_measured_zero(self):
        """max is 0 here: the old template divided by it."""
        markup = self._render([0.0] * 7)
        self.assert_no_broken_numbers(markup, "all zero")
        self.assertNotIn("<rect", markup)
        self.assertIn('class="sv-bars-base"', markup,
                      "with no bars the baseline is the only thing saying "
                      "the readings were zero rather than missing")
        self.assertIn("nothing recorded", markup)

    def test_an_unknown_reading_is_marked_rather_than_plotted_as_zero(self):
        markup = self._render([None, 0.0, 0.3, None])
        self.assert_no_broken_numbers(markup, "unknown readings")
        # One real bar, two "not measured" markers, and the measured zero
        # drawing nothing but the baseline.
        self.assertEqual(markup.count("sv-bar--unknown"), 2,
                         "None is unknown: it must be marked as missing, not "
                         "plotted as a zero sitting on the baseline")
        self.assertEqual(markup.count("<rect"), 3)
        self.assertIn("— not measured", markup,
                      "the missing slot has to say so in words on hover")

    def test_a_measured_zero_and_an_unknown_do_not_look_the_same(self):
        zero = self._render([0.0, 0.3])
        unknown = self._render([None, 0.3])
        self.assertNotIn("sv-bar--unknown", zero,
                         "a measured zero is a reading — it sits on the "
                         "baseline and must not be flagged as missing")
        self.assertIn("sv-bar--unknown", unknown)

    def test_a_negative_never_becomes_a_negative_height(self):
        """A signed series belongs in signed mode; a stray negative in an
        unsigned one must degrade to no bar, not to invalid markup."""
        markup = self._render([1.0, -2.0, 3.0])
        self.assert_no_broken_numbers(markup, "negative in unsigned series")
        self.assertEqual(markup.count("<rect"), 2)

    def test_a_signed_series_draws_both_sides_off_one_zero_line(self):
        markup = self._render([1.2, -0.8, 0.0, -2.4, 3.1], signed=1)
        self.assert_no_broken_numbers(markup, "signed series")
        self.assertEqual(markup.count("<rect"), 4)
        self.assertIn("sv-bar--red", markup)
        self.assertIn('class="sv-bars-base"', markup)


class SparklineRenderTests(SimpleTestCase):
    """The .oc-sparkline family, same three series shapes."""

    BASE = dict(unit="account equity", when="last 30 days")

    def test_a_curve_renders_its_own_gradient_id(self):
        markup = render_to_string(
            "_partials/chart_line.html",
            dict(self.BASE, points=[1, 2, 3], min=1, max=3,
                 chart_id="testCurve", fill=1))
        self.assertIn('id="testCurveGrad"', markup,
                      "the gradient must be namespaced per instance — two "
                      "cards sharing one id is how a curve ends up filled "
                      "from another card's gradient")
        self.assertNotIn("oc-spark-grad", markup)

    def test_one_point_and_no_points_are_different_states(self):
        one = render_to_string(
            "_partials/chart_line.html",
            dict(self.BASE, points=[5], chart_id="testOne"))
        none = render_to_string(
            "_partials/chart_line.html",
            dict(self.BASE, points=[], chart_id="testNone",
                 empty="No snapshots yet."))
        self.assertIn("testOneSvg", one)
        self.assertNotIn("<svg", none)
        self.assertIn("No snapshots yet.", none)

    def test_the_renderer_centres_a_flat_series(self):
        """`span || 1` put a flat curve on the floor of its box, which reads
        as 'at the low' for a series that never moved."""
        src = None
        for root in TEMPLATE_ROOTS:
            p = root / "_partials/chart_line.html"
            if p.exists():
                src = p.read_text(encoding="utf-8")
        self.assertIsNotNone(src)
        # Comments first: the partial documents the bug it fixes, and the
        # quoted expression would otherwise match the guard below.
        code = _strip_comments_and_fallbacks(src)
        self.assertNotRegex(
            code, r"\(\s*\w+\s*-\s*\w+\s*\)\s*\|\|\s*1",
            "the zero-span fallback is back: it maps every point of a flat "
            "series to the bottom of the box")
        self.assertIn("H / 2", code)
