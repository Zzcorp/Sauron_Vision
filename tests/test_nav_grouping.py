"""The rail is grouped by the question, and stays that way (2026-09-13).

The sidebar had drifted into seven sections over ~52 rows where two were
dumping grounds: "Intelligence" held sixteen links and "AI Agents"
fifteen, each mixing what may ACT with where MONEY goes with what is
MEASURED with what is being INVENTED. A rail like that is browsed, not
navigated — you have to already know which drawer a page lives in, which
is the "too many pages, not enough global eye" the regrouping answers.

Drift is the normal failure here, not a bad initial design: every new
page needs a home TODAY and the nearest plausible section always wins.
Nothing pushed back. These tests are the push-back, and they are shaped
to catch the drift rather than to freeze a layout — a section may be
renamed and rows may move, but no section may swell past the point where
its name stops predicting its contents, and no two rows may carry the
same name.

THE DUPLICATE THAT WAS ALREADY THERE. Two different rows both read "Bot
Performance": the per-rule expectancy table and the equity-curve page.
Two pages under one name is one page nobody finds, and nothing in the
suite objected.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import NoReverseMatch, reverse

#: Past this, a section's name has stopped predicting what is inside it.
#: Set from the largest honest section rather than from a round number —
#: raise it only with a section name that still earns the rows.
MAX_ROWS_PER_SECTION = 15


def _rail() -> str:
    t = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
        encoding="utf-8")
    return t[t.index("sidebar-nav"):t.index("sidebar-footer")]


def _sections():
    """[(section title, [row labels])] in rail order."""
    rail = _rail()
    out, current = [], None
    token = re.compile(
        r'nav-section">(?P<sec>[^<]*)<'
        r'|label-text">(?P<row>[^<]*)<')
    for m in token.finditer(rail):
        if m.group("sec") is not None:
            current = (m.group("sec").strip(), [])
            out.append(current)
        elif current is not None:
            current[1].append(m.group("row").strip())
    return out


def _url_names():
    return re.findall(r"\{%\s*url '([a-z_]+)'\s*%\}", _rail())


def _rows_with_glyphs():
    """[(url name, glyph)] for every row, entity-encoded ones decoded.

    Two rows wrote their glyph as `&#x25C9;` rather than as the character,
    which is why four rows sharing one circle was not obvious from reading
    the file.
    """
    import html
    rows = re.findall(
        r'<a\b[^>]*href="\{%\s*url\s+\'([a-z0-9_]+)\'[^}]*%\}"[^>]*>'
        r'.*?<span class="icon">(.*?)</span>',
        _rail(), re.S)
    return [(name, html.unescape(glyph).strip()) for name, glyph in rows]


class TheRailIsNavigableTests(SimpleTestCase):

    def test_every_row_sits_under_a_section(self):
        """A row above the first section header is unreachable by scanning:
        the eye looks for the header first."""
        rail = _rail()
        first_section = rail.index('nav-section">')
        before = re.findall(r'label-text">([^<]*)<', rail[:first_section])
        self.assertEqual(before, [],
                         f"rows sit above the first section header: {before}")

    def test_no_section_has_swollen_into_a_dumping_ground(self):
        oversize = {sec: len(rows) for sec, rows in _sections()
                    if len(rows) > MAX_ROWS_PER_SECTION}
        self.assertEqual(
            oversize, {},
            f"a section outgrew its own name (limit {MAX_ROWS_PER_SECTION}): "
            f"{oversize}. Split it by the QUESTION its pages answer — that is "
            f"how 'Intelligence' came to hold sixteen unrelated rows.")

    def test_no_section_is_empty(self):
        empty = [sec for sec, rows in _sections() if not rows]
        self.assertEqual(empty, [], f"section header with no rows: {empty}")

    def test_no_two_rows_carry_the_same_label(self):
        """The defect this regrouping found already in place. Two pages under
        one name is one page nobody finds."""
        labels = [row for _sec, rows in _sections() for row in rows]
        dupes = sorted({l for l in labels if labels.count(l) > 1})
        self.assertEqual(
            dupes, [],
            f"two rail rows share a label: {dupes}. Name each row for what "
            f"its page answers, not for the subsystem it belongs to.")

    def test_every_row_points_somewhere_real(self):
        """A rail is the one place a dead url name is invisible until a user
        clicks it — the template would raise at render, on every page."""
        for name in _url_names():
            try:
                reverse(name)
            except NoReverseMatch:  # pragma: no cover - the failure message is the point
                self.fail(f"the rail links to {name!r}, which reverses to "
                          f"nothing; every page extending base.html would 500")

    def test_the_entry_is_first(self):
        """Amon Hen is the page that answers 'is the machine turning'. It is
        the entry, so it is the first row under the first header — a global
        view you have to scroll to is not a global view."""
        sections = _sections()
        self.assertTrue(sections, "the rail has no sections at all")
        first_title, first_rows = sections[0]
        self.assertEqual(first_title, "Amon Hen")
        self.assertEqual(first_rows[0], "Oculus")

    def test_the_sections_are_named_for_questions_not_subsystems(self):
        """The two names that became dumping grounds were both subsystem
        names. That is the tell: a section named after a part of the system
        accepts anything built in that part."""
        titles = [sec for sec, _rows in _sections()]
        for banned in ("Intelligence", "AI Agents", "Automation"):
            self.assertNotIn(
                banned, titles,
                f"{banned!r} is a subsystem, not a question — it is how this "
                f"rail collected sixteen unrelated rows under one header")


class TheRailIsReadableByShapeTests(SimpleTestCase):
    """A 55-row rail is scanned by glyph before it is read by word.

    Six glyphs carried fifteen rows between them: Operations Center,
    Sauron's Mind, Profile and Notifications were the same filled circle,
    Strategies / Strategy Evolution / Knowledge Graph the same hexagon.
    A repeated shape costs exactly what a repeated label costs — the eye
    stops distinguishing rows and starts reading every word instead, which
    is the browsing the regrouping exists to end.
    """

    def test_every_row_carries_a_glyph(self):
        rows = _rows_with_glyphs()
        self.assertEqual(
            len(rows), len(_url_names()),
            "a rail row has no <span class=\"icon\"> — it will sit in the "
            "column of shapes as a hole")
        blank = [name for name, glyph in rows if not glyph]
        self.assertEqual(blank, [], f"rows with an empty glyph: {blank}")

    def test_no_two_rows_carry_the_same_glyph(self):
        rows = _rows_with_glyphs()
        seen = {}
        for name, glyph in rows:
            seen.setdefault(glyph, []).append(name)
        clashes = {glyph: names for glyph, names in seen.items()
                   if len(names) > 1}
        self.assertEqual(
            clashes, {},
            f"rail rows share a glyph: "
            f"{ {g: n for g, n in clashes.items()} }. Pick an unused shape "
            f"for the newer row; there are three geometric blocks of them "
            f"and the rail is what a duplicate makes unreadable.")

    def test_the_glyphs_are_text_not_pictures(self):
        """An emoji renders in colour, at a different size, on some platforms
        and not others. The rail is a monospace column of shapes; one picture
        in it breaks the column on the machines where it renders."""
        for name, glyph in _rows_with_glyphs():
            for ch in glyph:
                self.assertLess(
                    ord(ch), 0x1F000,
                    f"{name} uses {ch!r} (U+{ord(ch):04X}), which is an "
                    f"emoji codepoint and will not render as a text glyph "
                    f"everywhere")

    def test_the_glyphs_come_from_blocks_the_font_stack_already_renders(self):
        """`--font-heading` is Rajdhani, which contains none of these. Every
        one of them arrives by font fallback, and fallback is per-BLOCK on
        the platforms this runs on: a glyph from a block no other row uses
        is a glyph that may render as a tofu box on the operator's machine
        and as a shape on mine.

        So a new glyph must come from a block already proven by a row that
        renders today. That is a real constraint and the cheapest possible
        check — it is satisfied by picking a neighbour of an existing shape,
        which is also what keeps the column visually coherent.
        """
        allowed = {
            (0x2190, 0x21FF): "Arrows",
            (0x2200, 0x22FF): "Mathematical Operators",
            (0x2300, 0x23FF): "Miscellaneous Technical",
            (0x25A0, 0x25FF): "Geometric Shapes",
            (0x2600, 0x26FF): "Miscellaneous Symbols",
            (0x2700, 0x27BF): "Dingbats",
            (0x27C0, 0x27FF): "Misc Mathematical Symbols-A",
            (0x2900, 0x29FF): "Supplemental Mathematical Operators",
            (0x2B00, 0x2BFF): "Misc Symbols and Arrows",
        }
        for name, glyph in _rows_with_glyphs():
            for ch in glyph:
                point = ord(ch)
                if point < 0x80:      # '$' on Earnings, '?' on Ask Sauron
                    continue
                block = next((label for (lo, hi), label in allowed.items()
                              if lo <= point <= hi), None)
                self.assertIsNotNone(
                    block,
                    f"{name} uses {ch!r} (U+{point:04X}), which is outside "
                    f"every Unicode block the rail already renders. Pick a "
                    f"neighbour of a shape that is already there.")
