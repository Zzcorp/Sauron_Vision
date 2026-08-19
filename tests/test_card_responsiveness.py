"""A card must never scroll sideways, and never bleed past its own border.

Layout is the one part of this platform a test cannot see: there is no
viewport here, no font metrics, no reflow. What IS checkable is the set of
conventions that produce a card which contains its content — and every one
of them has already been broken once by a later edit that looked harmless
in isolation. That is what this file pins:

  * `overflow-wrap: anywhere` must never be set on a blanket table-cell
    selector. `anywhere` counts its break opportunities in min-content
    sizing, so it lets a table compress to fit instead of overflowing into
    its .table-wrapper scroll — and it wraps prices mid-digit while doing
    it. It is correct only as a named opt-in (.sv-ident) on a column that
    genuinely holds one long identifier.
  * every .grid-N track ends up as minmax(0, ...) — a bare fr track takes
    its automatic minimum from its content and refuses to shrink.
  * the responsive restatements come AFTER the plain declarations they
    have to beat. Media queries add no specificity, so a later unqualified
    rule silently wins over an earlier breakpoint — this is exactly how the
    laptop reflow was lost once already.
  * a card grid never declares a fixed px track.
  * a table marked .sv-stack has actually named its columns. A stacked row
    with no labels is a column of bare values, which is worse than the
    scroll it replaced.

Static analysis only: nothing here renders a page.

Run with:  python manage.py test tests.test_card_responsiveness
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

CSS_PATH = Path(settings.BASE_DIR) / "static" / "css" / "sauron.css"
TEMPLATE_ROOTS = [
    Path(settings.BASE_DIR) / "templates",
    Path(settings.BASE_DIR) / "bot_program" / "templates",
]

#: Card-grid selectors whose tracks must stay fluid.
CARD_GRID_SELECTORS = (".grid", ".oc-strip", ".sc-grid", ".ph-detail-grid")


def _css():
    return CSS_PATH.read_text(encoding="utf-8")


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _rules(css):
    """Yield (selector, body) for every rule in the sheet."""
    for _start, selector, body in _positioned_rules(css):
        yield selector, body


def _positioned_rules(css):
    """Yield (offset, selector, body) for every innermost rule.

    Deliberately crude: because the pattern forbids braces inside both
    halves, an @media prelude can never match as a selector — the engine
    skips past it and picks up the rules nested inside, which is exactly
    what the ordering checks need.
    """
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", _strip_comments(css)):
        yield match.start(), match.group(1).strip(), match.group(2).strip()


def _strip_django_tags(markup):
    """Remove {% %} and {{ }} before scanning HTML tags.

    A condition like `{% if pnl > 0 %}` inside a class attribute carries a
    bare `>`, which ends an HTML tag as far as any regex is concerned — so
    a scan that skips this reads half a tag and misses its attributes.
    """
    markup = re.sub(r"\{%.*?%\}", "", markup, flags=re.S)
    return re.sub(r"\{\{.*?\}\}", "", markup, flags=re.S)


def _templates():
    for root in TEMPLATE_ROOTS:
        if root.exists():
            yield from sorted(root.rglob("*.html"))


class BlanketWrapTests(SimpleTestCase):
    """`anywhere` on every cell is what made wide tables collapse instead of
    scrolling, and split prices across lines mid-digit."""

    #: Selectors that reach EVERY cell rather than an opted-in column.
    BLANKET_CELL_SELECTORS = ("td", "tbody td", "table td", "tr td",
                              ".sv-perf-table td", "thead th", "th")

    def test_no_blanket_cell_selector_uses_overflow_wrap_anywhere(self):
        offenders = []
        for selector, body in _rules(_css()):
            if "overflow-wrap" not in body:
                continue
            if not re.search(r"overflow-wrap\s*:\s*anywhere", body):
                continue
            for part in (p.strip() for p in selector.split(",")):
                if part in self.BLANKET_CELL_SELECTORS:
                    offenders.append(part)
        self.assertEqual(
            offenders, [],
            "overflow-wrap:anywhere on a blanket cell selector collapses "
            "every table's min-content width — wide tables stop scrolling "
            "and start compressing, and numbers break mid-digit. Use the "
            ".sv-ident opt-in on the one column that needs it: %r" % offenders)

    def test_the_sanctioned_opt_in_exists(self):
        """.sv-ident is the escape hatch the rule above assumes."""
        bodies = [b for s, b in _rules(_css()) if ".sv-ident" in s]
        self.assertTrue(bodies, ".sv-ident is not defined")
        self.assertTrue(
            any(re.search(r"overflow-wrap\s*:\s*anywhere", b) for b in bodies),
            ".sv-ident exists but does not break long identifiers, so a "
            "33-character rule name still sets its table's minimum width")

    def test_blanket_cells_still_wrap_with_break_word(self):
        """Removing `anywhere` must not mean removing wrapping."""
        css = _strip_comments(_css())
        self.assertRegex(
            css, r"tbody td\s*\{[^}]*overflow-wrap\s*:\s*break-word",
            "tbody td no longer wraps long prose at all, so text will "
            "lean out over the card border")


class GridTrackTests(SimpleTestCase):
    """A bare fr track takes its automatic minimum from its content."""

    NUMBERED_GRIDS = (".grid-2", ".grid-3", ".grid-4", ".grid-5", ".grid-6",
                      ".grid-sidebar")

    def _last_track_declaration(self, css, selector):
        """The winning grid-template-columns for `selector`, source-order."""
        winner = None
        for sel, body in _rules(css):
            parts = [p.strip() for p in sel.split(",")]
            if selector not in parts:
                continue
            found = re.search(r"grid-template-columns\s*:([^;]+)", body)
            if found:
                winner = found.group(1).strip()
        return winner

    def test_every_numbered_grid_resolves_to_minmax_zero(self):
        css = _css()
        for selector in self.NUMBERED_GRIDS:
            with self.subTest(selector=selector):
                track = self._last_track_declaration(css, selector)
                self.assertIsNotNone(track, "%s declares no tracks" % selector)
                self.assertIn(
                    "minmax(0", track,
                    "%s ends up on %r — a bare fr track never shrinks below "
                    "its content, so one long string widens the whole row"
                    % (selector, track))

    def test_no_card_grid_declares_a_fixed_px_track(self):
        """A px floor inside minmax() is fine; a px TRACK is not."""
        offenders = []
        for selector, body in _rules(_css()):
            if not any(g in selector for g in CARD_GRID_SELECTORS):
                continue
            found = re.search(r"grid-template-columns\s*:([^;]+)", body)
            if not found:
                continue
            value = found.group(1)
            # Drop every function call, floors and all, then look at what
            # is left standing as a track of its own.
            bare = re.sub(r"[a-z-]+\([^()]*(?:\([^()]*\)[^()]*)*\)", " ", value)
            if re.search(r"\b\d+(\.\d+)?px\b", bare):
                offenders.append((selector, value.strip()))
        self.assertEqual(
            offenders, [],
            "a fixed px track cannot reflow, so the grid sets its card's "
            "width instead of the other way round: %r" % offenders)

    def test_inline_grids_inside_cards_are_told_to_shrink(self):
        """~40 templates declare their tracks inline, out of this sheet's
        reach. min-width:0 on the children is the same fix, applied once."""
        css = _strip_comments(_css())
        self.assertRegex(
            css,
            r'\.card \[style\*="grid-template-columns"\] > \*[^{]*\{[^}]*'
            r'min-width\s*:\s*0',
            "inline grid tracks in card templates have no honest minimum, "
            "so they push their card wider than its column")


class BreakpointOrderTests(SimpleTestCase):
    """Media queries add no specificity — a later plain rule beats them."""

    def _last_index(self, css, needle):
        idx = css.rfind(needle)
        self.assertNotEqual(idx, -1, "%r is not in the stylesheet" % needle)
        return idx

    def _last_unqualified_grid_rule(self, css):
        """Offset of the last rule whose ENTIRE selector is one .grid-N.

        Matching the selector exactly matters: the breakpoint blocks say
        `.grid-5, .grid-6`, and a substring search for `.grid-6 {` finds
        the tail of that pair rather than the standalone rule it is meant
        to be ordered against.
        """
        latest = -1
        for start, selector, body in _positioned_rules(css):
            if selector in (".grid-5", ".grid-6") and "grid-template-columns" in body:
                latest = max(latest, start)
        self.assertNotEqual(latest, -1, "no standalone .grid-5/.grid-6 rule")
        return latest

    def test_the_laptop_reflow_is_restated_after_the_plain_tracks(self):
        css = _strip_comments(_css())
        last_plain = self._last_unqualified_grid_rule(_css())
        for breakpoint in ("@media (max-width: 1400px)",
                           "@media (max-width: 1200px)",
                           "@media (min-width: 769px) and (max-width: 1024px)"):
            with self.subTest(breakpoint=breakpoint):
                self.assertGreater(
                    css.rfind(breakpoint), last_plain,
                    "%s sits before the last unqualified .grid-N rule, so "
                    "the reflow it declares is silently overwritten on "
                    "every laptop" % breakpoint)

    def test_the_laptop_shim_keeps_its_769px_floor(self):
        """Below 769px the Phase-29 rule collapses inline grids to one
        column; the shim must not out-cascade it."""
        css = _strip_comments(_css())
        self.assertIn("@media (min-width: 769px) and (max-width: 1280px)", css)

    def test_stacking_is_declared_after_the_mobile_table_runway(self):
        """Both land on .sv-perf-table at the same specificity, so the one
        that wins is whichever is written last."""
        css = _strip_comments(_css())
        runway = self._last_index(css, "min-width: 34rem")
        stack = self._last_index(css, ".sv-stack")
        self.assertGreater(
            stack, runway,
            "the 34rem runway is declared after the stacked layout, so a "
            "stacked table still demands 34rem and still scrolls")


class MobileTableTests(SimpleTestCase):
    """The blanket 600px minimum put a scrollbar under two-column tables."""

    def test_the_blanket_600px_runway_is_superseded(self):
        css = _strip_comments(_css())
        blanket = css.rfind("min-width: 600px")
        if blanket == -1:
            return  # already deleted outright, which is also correct
        reset = css.rfind("min-width: 0")
        self.assertGreater(
            reset, blanket,
            "every .sv-perf-table still inherits a 600px floor on phones, "
            "including the two- and three-column breakdown tables that fit "
            "a 360px screen with room to spare")

    def test_a_runway_survives_for_tables_that_genuinely_need_one(self):
        css = _strip_comments(_css())
        self.assertRegex(
            css, r"th:nth-child\(6\)",
            "no column-count test remains, so either every table scrolls "
            "again or none of the wide ones can")

    def test_the_wrapper_is_the_only_thing_that_scrolls(self):
        css = _strip_comments(_css())
        self.assertRegex(css, r"\.table-wrapper[^{]*\{[^}]*overflow-x\s*:\s*auto")
        # The card itself was set to overflow:visible by the honesty pass
        # and must stay that way — a card with its own scrollbar is the bug.
        self.assertRegex(
            css, r"\.card[^{]*\{[^}]*overflow\s*:\s*visible",
            "the card no longer declares overflow:visible; if it has gone "
            "back to hidden, content is being amputated again")


class StackedTableLabelTests(SimpleTestCase):
    """A stacked row without labels is a column of anonymous values."""

    #: `<td` tags exempt from carrying a label.
    EXEMPT = ("colspan", "data-label")

    def _stacked_tables(self, markup):
        """Yield the tbody markup of each table carrying the sv-stack class.

        Matches the class attribute only — `--sv-stack` is the overlay
        z-ladder variable and appears in unrelated templates.
        """
        for table in re.finditer(
                r"<table[^>]*\bclass=[\"'][^\"']*\bsv-stack\b[^\"']*[\"'][^>]*>"
                r"(.*?)</table>", markup, flags=re.S):
            body = re.search(r"<tbody>(.*?)</tbody>", table.group(1), flags=re.S)
            if body:
                yield body.group(1)

    def test_every_stacked_cell_names_its_column(self):
        offenders = []
        for path in _templates():
            markup = _strip_django_tags(path.read_text(encoding="utf-8"))
            if "sv-stack" not in markup:
                continue
            for body in self._stacked_tables(markup):
                for tag in re.finditer(r"<td\b[^>]*>", body):
                    if not any(token in tag.group(0) for token in self.EXEMPT):
                        offenders.append((path.name, tag.group(0)[:90]))
        self.assertEqual(
            offenders, [],
            "a cell in a stacked table has no data-label, so on a phone it "
            "renders as a value with nothing saying what it is: %r"
            % offenders)

    def test_at_least_the_widest_pages_actually_stack(self):
        """The convention is worth nothing unless it is applied where the
        operator meets it — these are the platform's widest tables."""
        expected = {"signals_list.html", "eye_fills.html", "backtest_list.html",
                    "tax_lots.html", "promotions.html", "calibration.html",
                    "asset_bots.html", "bot_performance.html", "audit_log.html",
                    "rule_control.html", "ai_tasks_list.html"}
        stacked = {
            p.name for p in _templates()
            if re.search(r"class=[\"'][^\"']*\bsv-stack\b", p.read_text(encoding="utf-8"))
        }
        self.assertEqual(
            expected - stacked, set(),
            "these wide tables lost their stacked phone layout: %r"
            % sorted(expected - stacked))

    def test_the_stacked_layout_is_defined_and_scoped_to_phone_width(self):
        css = _strip_comments(_css())
        self.assertIn("@media (max-width: 640px)", css)
        self.assertRegex(
            css, r"\.sv-stack[^{]*td::before[^{]*\{[^}]*content\s*:\s*attr\(data-label\)",
            "nothing reads data-label back out, so the labels in the "
            "templates are dead weight")


class FixedWidthColumnTests(SimpleTestCase):
    """A px width on a <th> is a floor the table cannot go under."""

    #: Below this a fixed column is a glyph or a checkbox, not a cause of
    #: horizontal scroll.
    TOLERATED_PX = 120

    def test_no_wide_column_is_pinned_in_pixels(self):
        offenders = []
        for path in _templates():
            markup = path.read_text(encoding="utf-8")
            for tag in re.finditer(r"<th\b[^>]*>", markup):
                for width in re.finditer(r"width\s*:\s*(\d+)px", tag.group(0)):
                    if int(width.group(1)) >= self.TOLERATED_PX:
                        offenders.append((path.name, tag.group(0)[:80]))
        self.assertEqual(
            offenders, [],
            "a px column width is a minimum, not a preference: three of "
            "them and the table cannot fit a phone at any font size. Use "
            "ch, which tracks the type: %r" % offenders)


class VisualLanguageTests(SimpleTestCase):
    """Refinement inside the existing language, not a new one."""

    def _containment_section(self):
        css = _css()
        start = css.index("CARD CONTAINMENT")
        return css[start:]

    def test_the_containment_pass_introduces_no_new_colour(self):
        section = _strip_comments(self._containment_section())
        literals = re.findall(r"#[0-9a-fA-F]{3,8}\b", section)
        self.assertEqual(
            literals, [],
            "a raw colour bypasses the token set, so it cannot follow "
            "body.light-mode: %r" % literals)

    def test_the_containment_pass_introduces_no_raw_z_index(self):
        section = _strip_comments(self._containment_section())
        raw = re.findall(r"z-index\s*:\s*\d+", section)
        self.assertEqual(
            raw, [],
            "floating elements ride the sv-overlay ladder tokens "
            "(--z-hovercard/--z-menu/--z-panel/--z-dialog): %r" % raw)

    def test_one_radius_across_the_card_family(self):
        """.card, .stat-box, .metric and .signal-item share every grid on
        the platform, so they cannot round their corners differently."""
        css = _css()
        winner = {}
        for selector, body in _rules(css):
            parts = [p.strip() for p in selector.split(",")]
            found = re.search(r"border-radius\s*:([^;]+)", body)
            if not found:
                continue
            for part in parts:
                if part in (".card", ".stat-box", ".metric", ".signal-item"):
                    winner[part] = found.group(1).strip()
        self.assertEqual(len(set(winner.values())), 1,
                         "the card family renders more than one corner "
                         "radius in the same grid: %r" % winner)

    def test_one_hover_tempo_across_the_card_family(self):
        css = _css()
        winner = {}
        for selector, body in _rules(css):
            parts = [p.strip() for p in selector.split(",")]
            found = re.search(r"transition\s*:([^;]+)", body)
            if not found:
                continue
            for part in parts:
                if part in (".card", ".stat-box", ".metric", ".signal-item"):
                    winner[part] = found.group(1).strip()
        self.assertEqual(
            len(set(winner.values())), 1,
            "two tiles under the same pointer lift at different speeds, "
            "which reads as one of them lagging: %r" % winner)

    def test_motion_still_yields_to_prefers_reduced_motion(self):
        css = _strip_comments(_css())
        self.assertIn("@media (prefers-reduced-motion: reduce)", css)

    def test_numbers_are_tabular_so_columns_line_up(self):
        css = _strip_comments(_css())
        self.assertRegex(
            css,
            r"\.sv-perf-table[^{]*\{[^}]*font-variant-numeric\s*:\s*tabular-nums",
            "proportional figures do not line their decimal points up, "
            "which is the only reason to put numbers in a column")
        self.assertRegex(
            css, r"td\.num[^{]*\{[^}]*text-align\s*:\s*right",
            ".num no longer right-aligns, so magnitude is not comparable "
            "down the column")
