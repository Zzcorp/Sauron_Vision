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
    """[(section title, [row labels])] in rail order. Updated deliberately
    (the desk v2 board, approved 2026-11-13: "amazing work, bravo, I need it
    fast!!"): a section head is a button that folds its rows, its name in
    .nav-fold-name."""
    rail = _rail()
    out, current = [], None
    token = re.compile(
        r'nav-fold-name">(?P<sec>[^<]*)<'
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


def _rows_with_icons():
    """[(url name, the icon span's content)] for every row. Updated
    deliberately (UI plan §9, redo B2, the desk v2 board approved
    2026-11-13): a row's mark is a symbol of the one sprite
    (templates/_partials/sv_icons.html), named by <use href="#svi-…">,
    never a glyph."""
    rows = re.findall(
        r'<a\b[^>]*href="\{%\s*url\s+\'([a-z0-9_]+)\'[^}]*%\}"[^>]*>'
        r'.*?<span class="icon">(.*?)</span>',
        _rail(), re.S)
    return [(name, icon) for name, icon in rows]


def _sprite_ids():
    sprite = (Path(settings.BASE_DIR) / "templates" / "_partials" / "sv_icons.html").read_text(encoding="utf-8")
    return set(re.findall(r'<symbol id="(svi-[\w-]+)"', sprite))


class TheRailIsNavigableTests(SimpleTestCase):

    def test_every_row_sits_under_a_section(self):
        """A row above the first section header is unreachable by scanning:
        the eye looks for the header first."""
        rail = _rail()
        first_section = rail.index('class="nav-section"')
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
    """A 55-row rail is scanned by shape before it is read by word.

    Six glyphs carried fifteen rows between them: Operations Center,
    Sauron's Mind, Profile and Notifications were the same filled circle,
    Strategies / Strategy Evolution / Knowledge Graph the same hexagon.
    A repeated shape costs exactly what a repeated label costs — the eye
    stops distinguishing rows and starts reading every word instead, which
    is the browsing the regrouping exists to end.

    Updated deliberately (UI plan §9, redo B2; the desk v2 board, approved
    2026-11-13: "amazing work, bravo, I need it fast!!"): the shapes are the
    one icon family's symbols now, not Unicode glyphs, so a glyph rule
    becomes "every row names an icon that exists in the sprite". The
    meanings stay: every row has its mark, no two rows share one, and no
    row draws a picture a font may or may not have.
    """

    def test_every_row_names_an_icon_the_sprite_has(self):
        rows = _rows_with_icons()
        self.assertEqual(
            len(rows), len(_url_names()),
            "a rail row has no <span class=\"icon\"> — it will sit in the "
            "column of shapes as a hole")
        ids = _sprite_ids()
        for name, icon in rows:
            used = re.findall(r'<use href="#(svi-[\w-]+)"', icon)
            with self.subTest(row=name):
                self.assertEqual(len(used), 1, f"{name} names no icon: {icon!r}")
                self.assertIn(used[0], ids, f"{name} names {used[0]}, which the sprite does not have")

    def test_no_two_rows_carry_the_same_icon(self):
        seen = {}
        for name, icon in _rows_with_icons():
            for ref in re.findall(r'<use href="#(svi-[\w-]+)"', icon):
                seen.setdefault(ref, []).append(name)
        clashes = {ref: names for ref, names in seen.items() if len(names) > 1}
        self.assertEqual(
            clashes, {},
            f"rail rows share an icon: {clashes}. Draw the newer row its own "
            f"symbol in the sprite; the rail is what a duplicate makes "
            f"unreadable.")

    def test_no_row_draws_a_glyph(self):
        """An emoji or a Unicode glyph renders in colour, at another size or
        not at all depending on the machine; the sprite renders the same
        everywhere. The icon span holds the symbol and nothing else."""
        for name, icon in _rows_with_icons():
            with self.subTest(row=name):
                self.assertEqual(re.sub(r"<[^>]+>", "", icon).strip(), "",
                                 f"{name} draws text in its icon: {icon!r}")
