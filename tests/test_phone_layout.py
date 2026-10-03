"""THE PHONE TIER, FIRST SLICE (2026-09-28).

The operator, 2026-09-27: "Sauron needs a lifting on the responsive side,
please... it's not adaptive at all now". The father runs Sauron from his
phone from Monday 2026-09-28. Measured on 3994ffc at 360x780 in a
phone-emulating headless Chrome: the topbar's right cluster ran to x=685,
so the bell and the account menu were off the screen; the ticker and the
info panel were 56px stubs; a saved open signals rail could not be closed;
pinch-zoom was off; and on /positions/ the stacked rows were labelled by
position on a table that had grown to fourteen columns: the target price
read "P&L", and Strategy, Opened and Action had no label.

A test has no viewport. What it holds is the set of rules and the markup
that make the phone layout, so a later edit cannot quietly undo them:

  A. static/css/sv-responsive.css, the phone tier. base.html links it
     once, last of the shell sheets, before a page's extra_css. Outside
     its 768px query it holds three rules, and those touch phone-only
     markup; no px width over 320, no hex colour, every z-index a rung of
     the ladder. Inside: the rail, the ticker and the info panel off, the
     topbar at 44px, 44px taps, 48px CLOSE, 16px inputs (and sauron.css's
     global form rule lifted to 16px at its own weight, which a zero-weight
     floor could not reach). The floating buttons' selector weighs 0,2,2:
     over sauron.css's info-panel pair (0,2,1), under the position page's
     own lift (1,1,2). The viewport lets a phone zoom.
  B. The stacked tables. One tier, 768px. The pos-tabs argument stays in
     the :is() lists because its weight, 0,3,2, is what lifts the stack
     over the 34rem runway (also 0,3,2, declared earlier). The eleven
     positional labels are gone. Every refinement in the phone sheet uses
     the stack block's exact prefix. Every CLOSE on /positions/ sits in an
     action cell, and the broker table names its cells.
  C. The rendered pages. /positions/ and its live refresh label each cell
     by its own column, in the thead's order and words; the bottom nav
     links Home, Positions, Portfolio and Briefing and marks the current
     one only; the account menu carries the lock and the theme.
  D. The info panel reads "minimized" on a phone and nothing is saved:
     base.html's real IIFE runs under node against a stub page.

Later stages of the same plan (home, portfolio, briefing, the other pages,
the standalone pages, phone performance) widen B's template sets.

Run with:  python manage.py test tests.test_phone_layout
"""
import html
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

NODE = shutil.which("node")
BASE = Path(settings.BASE_DIR)
HOST = "127.0.0.1"

#: The stack block's exact prefix (sauron.css, STACKED TABLES). The
#: weight argument was `.pos-tabs ~ .card table:has(th:nth-child(11))`
#: until the 2026-09-28 merge with the close-advice branch, whose
#: `.table-wrapper table.sv-stack:has(th:nth-child(1))` holds the same
#: (0,3,2) and matches nothing .sv-stack does not already match.
P = (":is(.sv-stack, .table-wrapper table.sv-stack:has(th:nth-child(1)), "
     ".positions-metrics table)")

#: This slice's stacked templates; later stages add theirs.
STACKED = {"positions_list.html"}


# ── helpers ──────────────────────────────────────────────────────────────

def _read(*parts):
    return BASE.joinpath(*parts).read_text(encoding="utf-8")


def _norm(text):
    return " ".join(text.split())


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _blocks(css):
    """[(prelude, body)] of every top-level block of a comment-free sheet:
    a brace walker, so an @media block comes back whole."""
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
    """A selector list split on its top-level commas (an :is() keeps its
    own)."""
    parts, depth, cur = [], 0, ""
    for ch in selector:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    parts.append(cur.strip())
    return [p for p in parts if p]


def _ident_end(sel, i):
    while i < len(sel) and (sel[i].isalnum() or sel[i] in "-_"):
        i += 1
    return i


def _weight(sel):
    """(ids, classes, types) of ONE complex selector. :is(), :not() and
    :has() weigh their heaviest argument, :where() nothing; attributes and
    other pseudo-classes weigh a class, pseudo-elements a type."""
    a = b = c = 0
    i = 0
    while i < len(sel):
        ch = sel[i]
        if ch == "#":
            a += 1
            i = _ident_end(sel, i + 1)
        elif ch == ".":
            b += 1
            i = _ident_end(sel, i + 1)
        elif ch == "[":
            b += 1
            i = sel.index("]", i) + 1
        elif ch == ":":
            if sel.startswith("::", i):
                c += 1
                i = _ident_end(sel, i + 2)
                continue
            start = i + 1
            i = _ident_end(sel, start)
            name = sel[start:i]
            if i < len(sel) and sel[i] == "(":
                depth, j = 0, i
                while True:
                    if sel[j] == "(":
                        depth += 1
                    elif sel[j] == ")":
                        depth -= 1
                        if depth == 0:
                            break
                    j += 1
                inner, i = sel[i + 1:j], j + 1
                if name in ("is", "not", "has"):
                    best = max((_weight(p.lstrip("> +~"))
                                for p in _split_top(inner)), default=(0, 0, 0))
                    a, b, c = a + best[0], b + best[1], c + best[2]
                elif name != "where":
                    b += 1
            else:
                b += 1
        elif ch.isalpha():
            c += 1
            i = _ident_end(sel, i)
        else:
            i += 1
    return (a, b, c)


def _sheet():
    return _strip_comments(_read("static", "css", "sv-responsive.css"))


def _phone():
    """The body of the sheet's one @media (max-width: 768px) block."""
    bodies = [body for prelude, body in _blocks(_sheet())
              if prelude == "@media (max-width: 768px)"]
    assert len(bodies) == 1, len(bodies)
    return bodies[0]


def _phone_rules():
    return _rules(_phone())


def _body(selector):
    """The declarations of the phone rule whose whole selector is this."""
    found = [b for s, b in _phone_rules() if s == _norm(selector)]
    assert found, "no phone rule %r" % selector
    return " ".join(found)


def _hidden():
    """Every selector the phone block sets to display: none !important."""
    out = set()
    for sel, body in _phone_rules():
        if re.search(r"(^|;)\s*display: none !important", body):
            out.update(_split_top(sel))
    return out


def _text(markup):
    return _norm(html.unescape(re.sub(r"<[^>]+>", " ", markup)))


class _Cells(HTMLParser):
    """The attributes of every <td> (and <th>) in a fragment, in order."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tds, self.ths = [], []

    def handle_starttag(self, tag, attrs):
        if tag == "td":
            self.tds.append(dict(attrs))
        elif tag == "th":
            self.ths.append(dict(attrs))


def _cells(fragment):
    parser = _Cells()
    parser.feed(fragment)
    return parser


def _region(body, name):
    start = body.index('data-sv-live="%s"' % name)
    end = body.find('data-sv-live="', start + 12)
    return body[start:end if end != -1 else len(body)]


def _open_table(body):
    region = _region(body, "pos-open")
    m = re.search(r'<table class="([^"]*)">(.*?)</table>', region, re.S)
    assert m, "no table in the pos-open region"
    return m.group(1).split(), m.group(2)


# ── A. the phone sheet ───────────────────────────────────────────────────

class PhoneSheetTests(SimpleTestCase):

    def test_base_links_it_once_last_of_the_shell_before_the_page(self):
        base = _read("templates", "base.html")
        # The link itself; a comment may name the file.
        self.assertEqual(base.count("'css/sv-responsive.css'"), 1)
        at = base.index("'css/sv-responsive.css'")
        for sheet in ("'css/sauron.css'", "'css/sv-overlay.css'",
                      "'css/sv-tour.css'"):
            self.assertGreater(at, base.index(sheet), sheet)
        self.assertLess(at, base.index("{% block extra_css %}"))
        self.assertLess(at, base.index("</head>"))
        self.assertIn('<link rel="stylesheet" href="{% static '
                      "'css/sv-responsive.css' %}\">", base)

    def test_the_viewport_lets_a_phone_zoom(self):
        base = _read("templates", "base.html")
        metas = re.findall(r'<meta name="viewport" content="([^"]+)">', base)
        self.assertEqual(
            metas, ["width=device-width, initial-scale=1, viewport-fit=cover"])
        self.assertNotIn("maximum-scale", metas[0])
        self.assertNotIn("user-scalable", metas[0])

    def test_outside_the_phone_query_only_three_rules(self):
        blocks = _blocks(_sheet())
        top = [(p, _norm(b)) for p, b in blocks if not p.startswith("@")]
        self.assertEqual(top, [
            (":root", "--sv-bottom-chrome: 0px;"),
            (".sv-phone-nav, .sv-phone-only", "display: none !important;"),
            (".sv-actions",
             "display: flex; gap: 6px; flex-wrap: wrap; align-items: center;"),
        ])
        media = [p for p, _b in blocks if p.startswith("@")]
        self.assertEqual(media.count("@media (max-width: 768px)"), 1)
        # The one other block the plan allows: phone performance (Stage 6).
        self.assertEqual(
            set(media) - {"@media (max-width: 768px)",
                          "@media (max-width: 768px), (pointer: coarse)"},
            set(), media)

    def test_no_px_width_over_320(self):
        # Declarations only: the media query's own (max-width: 768px) is
        # the tier, not a width.
        decls = " ".join(body for _sel, body in _rules(_sheet()))
        found = re.findall(
            r"(?<![-\w])((?:min-|max-)?width)\s*:\s*(\d+(?:\.\d+)?)px", decls)
        self.assertTrue(found)
        for prop, px in found:
            self.assertLessEqual(float(px), 320, prop)

    def test_every_z_index_is_a_rung_of_the_ladder(self):
        zs = re.findall(r"z-index\s*:\s*([^;]+);", _sheet())
        self.assertTrue(zs)
        for z in zs:
            self.assertRegex(z.strip(), r"^(calc\()?var\(--z-", z)

    def test_no_hex_colour(self):
        for _sel, body in _rules(_sheet()):
            self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", body), [],
                             body)

    def test_the_rail_the_ticker_and_the_info_panel_are_off(self):
        hidden = _hidden()
        for sel in (".signals-rail", ".rail-toggle-btn", ".sidebar-toggle-btn",
                    ".mobile-toggle", ".ticker-bar", ".hb-restore-tab.ticker",
                    ".info-panel-wrap", "#ipRestorePill"):
            self.assertIn(sel, hidden)
        self.assertEqual(_body(".main-content"), "margin-right: 0 !important;")
        body = _body("body")
        self.assertIn("--hb-ticker-h: 0px !important", body)
        self.assertIn("--se-left-chrome: 0px !important", body)
        self.assertIn("--se-fab-size: 48px !important", body)
        # Loaded after sauron.css, whose rail is display:flex !important at
        # the same weight: the order is what makes it lose.
        base = _read("templates", "base.html")
        self.assertGreater(base.index("'css/sv-responsive.css'"),
                           base.index("'css/sauron.css'"))

    def test_the_topbar_fits_and_its_controls_are_44px(self):
        hidden = _hidden()
        for sel in ("#clock", ".topbar .exchange-indicator",
                    ".topbar .theme-toggle-btn", ".topbar .lock-now",
                    ".um-name-text", ".um-caret", ".lsp-label"):
            self.assertIn(sel, hidden)
        body = _body(".mobile-menu-btn, .notif-bell, .user-menu-trigger")
        self.assertIn("min-height: 44px", body)
        self.assertIn("min-width: 44px", body)
        title = _body(".topbar-title")
        self.assertIn("white-space: nowrap", title)
        self.assertIn("text-overflow: ellipsis", title)
        self.assertIn("min-width: 0", _body(".topbar > :first-child"))
        menus = _body(".user-menu-dropdown, .notif-dropdown")
        self.assertIn("max-width: calc(100vw - 16px)", menus)
        # vh first: dvh needs Chrome 108 or later.
        self.assertLess(menus.index("100vh"), menus.index("100dvh"))
        self.assertIn("display: flex !important", _body(".sv-phone-only"))

    def test_the_tap_and_type_floor(self):
        self.assertIn("min-height: 44px", _body(".btn, .btn-sm"))
        close = _body("[data-sv-close-trade], #svCloseAll")
        self.assertIn("min-height: 48px", close)
        where = [b for s, b in _phone_rules() if s.startswith(":where(input")]
        self.assertEqual(len(where), 1)
        self.assertIn("font-size: 16px", where[0])
        self.assertIn("min-height: 44px", where[0])
        # sauron.css's global form rule sets 13px at 0,1,1, which a
        # zero-weight floor never beats: its own selectors, straight after
        # it and inside the phone query, lift it to 16px.
        css = _strip_comments(_read("static", "css", "sauron.css"))
        rule = (".form-input, .input, input[type=text], input[type=password], "
                "input[type=email], input[type=number], input[type=search], "
                "textarea, select")
        blocks = _blocks(css)
        at = [i for i, (p, b) in enumerate(blocks)
              if p == rule and "font-size: 13px" in b]
        self.assertEqual(len(at), 1)
        prelude, body = blocks[at[0] + 1]
        self.assertEqual(prelude, "@media (max-width: 768px)")
        self.assertEqual(_rules(body), [(rule, "font-size: 16px;")])

    def test_the_stop_and_target_buttons_meet_the_tap_floor(self):
        """The one control on /positions/ that moves a stop. sauron.css
        sizes .lvl-edit to its text, about 24px for a price with no
        distance under it, and the (i) floor names .btn, CLOSE, the
        dialog's X and the inputs, not it: a thumb that missed landed on
        the cell, which is a tap on the row (sv-position-card.js) and
        opened the trade page. Page-scoped like the detail link beside
        it; a column, so the price and its distance keep their two lines;
        and the text follows the stacked cell, which the stack sets left
        (sauron.css) where the button's own rule says right."""
        markup = _read("templates", "dashboard", "positions_list.html")
        for label in ("Stop", "Target"):
            cell = markup.split('data-label="%s"' % label, 1)[1].split("</td>", 1)[0]
            self.assertIn('class="lvl-edit"', cell, label)
        lvl = _body(".page-content .lvl-edit")
        for decl in ("min-height: 44px", "display: flex", "flex-direction: column",
                     "justify-content: center", "text-align: inherit"):
            self.assertIn(decl, lvl)
        self.assertGreater(_weight(".page-content .lvl-edit"), _weight(".lvl-edit"))

    def test_the_floating_buttons_clear_the_bottom_nav_on_the_ladder(self):
        """0,2,1 < 0,2,2 < 1,1,2: over the shell's info-panel pair whatever
        the order, under the position page's lift over its close bar."""
        fab = [s for s, b in _phone_rules() if "--se-bottom-edge" in b]
        self.assertEqual(fab, ["html body:has(.sv-phone-nav .sv-pn-item)"])
        self.assertIn("calc(var(--sv-bottom-chrome) + 12px)",
                      _body(fab[0]))
        sauron = _strip_comments(_read("static", "css", "sauron.css"))
        for sel in ("body:has(.info-panel-wrap):not(.page-dashboard)",
                    "body:has(.info-panel-wrap.minimized)"):
            self.assertIn(sel + " {", sauron)
            self.assertEqual(_weight(sel), (0, 2, 1), sel)
        self.assertEqual(_weight(fab[0]), (0, 2, 2))
        pd = _read("templates", "dashboard", "forensics_detail.html")
        self.assertIn("html.pd-js body:has(#pdCloseBtn) {", pd)
        self.assertEqual(_weight("html.pd-js body:has(#pdCloseBtn)"), (1, 1, 2))
        self.assertIn("--sv-bottom-chrome: 0px", _body("body:has(#pdCloseBtn)"))
        self.assertIn("display: none !important",
                      _body("body:has(#pdCloseBtn) .sv-phone-nav"))

    def test_the_bottom_nav_is_a_fixed_five_column_bar_on_the_ladder(self):
        nav = _body(".sv-phone-nav")
        for decl in ("display: grid !important",
                     "grid-template-columns: repeat(5, minmax(0, 1fr))",
                     "position: fixed", "bottom: 0",
                     "height: calc(56px + env(safe-area-inset-bottom, 0px))",
                     "z-index: var(--z-chrome)"):
            self.assertIn(decl, nav)
        self.assertIn("min-height: 56px", _body(".sv-pn-item"))
        self.assertIn("color: var(--accent)",
                      _body('.sv-pn-item[aria-current="page"]'))
        self.assertIn("calc(var(--sv-bottom-chrome) + var(--se-fab-size) + 28px)",
                      _body(".page-content, body.page-dashboard .page-content"))

    def test_gollum_is_off_on_a_phone_and_left_as_he_was_above(self):
        for sel in (".gollum-fab", ".gollum-bubble", ".gollum-dialog"):
            self.assertIn(sel, _hidden())
        # Above 768px nothing changes in this slice: his 900px rule stands.
        self.assertIn(
            "@media (max-width: 900px) { .gollum-dialog { width: calc(100vw - "
            "24px); left: 12px; } .gollum-fab, .gollum-bubble { left: 12px; } }",
            _read("static", "css", "sauron.css"))


# ── B. the stacked tables ────────────────────────────────────────────────

class StackTierTests(SimpleTestCase):

    def _css(self):
        return _strip_comments(_read("static", "css", "sauron.css"))

    def test_one_tier_768px(self):
        css = self._css()
        self.assertRegex(css, r"@media \(max-width: 768px\) \{\s*:is\(\.sv-stack,")
        self.assertNotRegex(css, r"@media \(max-width: 640px\) \{\s*:is\(\.sv-stack,")

    def test_the_weight_argument_keeps_the_stack_over_the_runway(self):
        """Its weight is the point: the stack's display:block and
        min-width:0 tie the 34rem runway at 0,3,2 and win by coming later.
        Without the weight argument the :is() would weigh 0,1,0 and every
        wide stacked table would keep its 34rem floor. The argument is
        `.table-wrapper table.sv-stack:has(th:nth-child(1))` since the
        2026-09-28 merge (test_card_responsiveness pins that the old
        `.pos-tabs ~ .card table` is gone); what is pinned here is that it
        is in every list, weighs 0,3,2, and comes after the runway."""
        css = self._css()
        lists = re.findall(
            r":is\(\.sv-stack,\s*\.table-wrapper table\.sv-stack:has\(th:"
            r"nth-child\(1\)\),\s*\.positions-metrics table\)", css)
        self.assertEqual(len(lists), 9)
        runway = ".table-wrapper .sv-perf-table:has(thead th:nth-child(6))"
        self.assertIn(runway + " { min-width: 34rem; }", css)
        self.assertEqual(_weight(P), (0, 3, 2))
        self.assertEqual(_weight(runway), (0, 3, 2))
        self.assertLess(css.index(runway), css.index(":is(.sv-stack,"))

    def test_the_positional_labels_are_gone(self):
        css = self._css()
        self.assertNotIn("td:nth-child(11)::before", css)
        self.assertNotIn('content: "Opened"', css)
        self.assertNotIn("td:nth-child(n+12)", css)
        # The analytics partial's six keep theirs.
        self.assertIn('.positions-metrics table td:nth-child(6)::before '
                      '{ content: "%"; }', css)
        self.assertRegex(css, r"\.sv-stack[^{]*td::before[^{]*\{[^}]*content"
                              r"\s*:\s*attr\(data-label\)")

    def test_this_slices_tables_stack(self):
        stacked = set()
        for path in (BASE / "templates").rglob("*.html"):
            if re.search(r"<table[^>]*\bclass=\"[^\"]*\bsv-stack\b",
                         path.read_text(encoding="utf-8")):
                stacked.add(path.name)
        self.assertEqual(STACKED - stacked, set())

    def test_every_close_on_positions_sits_in_an_action_cell(self):
        for name in STACKED:
            markup = _read("templates", "dashboard", name)
            closes = [m.start() for m in re.finditer("data-sv-close-trade", markup)]
            self.assertTrue(closes, name)
            for at in closes:
                td = markup.rfind("<td", 0, at)
                tag = markup[td:markup.index(">", td)]
                self.assertIn("sv-cell-action", tag, name)
                self.assertIn('data-label="Action"', tag, name)

    def test_every_stacked_rule_uses_the_stack_blocks_exact_prefix(self):
        stacked = [s for s, _b in _phone_rules() if "tbody" in s]
        self.assertGreaterEqual(len(stacked), 8)
        for sel in stacked:
            for part in _split_top(sel):
                self.assertTrue(part.startswith(P), part)

    def test_open_positions_are_two_column_cards_with_a_full_width_close(self):
        pairs = _body(P + ".sv-stack--pairs tbody tr")
        self.assertIn("display: grid", pairs)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr))", pairs)
        wide = _body(P + ".sv-stack--pairs tbody td:is(.sv-cell-wide, "
                     ".sv-cell-action, [colspan]), " + P
                     + ".sv-stack--pairs tbody th[colspan]")
        self.assertIn("grid-column: 1 / -1", wide)
        self.assertIn("content: none", _body(P + " tbody td.sv-cell-action::before"))
        self.assertIn("width: 100%",
                      _body(P + " tbody td.sv-cell-action :is(.btn, button)"))

    def test_the_broker_table_names_its_cells(self):
        markup = _read("templates", "dashboard", "positions_list.html")
        m = re.search(r'<table class="bkp-table sv-stack">(.*?)</table>',
                      markup, re.S)
        self.assertIsNotNone(m)
        cells = _cells(m.group(1))
        heads = [_text(h) for h in re.findall(r"<th>(.*?)</th>", m.group(1))]
        labels = [td.get("data-label") for td in cells.tds]
        self.assertEqual(len(labels), 10)
        # The header's words; the last header is empty on a wide screen.
        self.assertEqual([x.lower() for x in labels[:9]],
                         [x.lower() for x in heads[:9]])
        self.assertEqual((heads[9], labels[9]), ("", "Claim"))


# ── C. the rendered pages ────────────────────────────────────────────────

class RenderedPhoneMarkupTests(TestCase):

    def setUp(self):
        from tests.test_position_page import _instrument, _quote, _trade
        self.user = get_user_model().objects.create_user(
            "phone_layout", password="x")
        self.client.force_login(self.user)
        _quote(_instrument(), "1.61030")
        self.trade = _trade(self.user)

    def _get(self, url):
        resp = self.client.get(url, HTTP_HOST=HOST)
        self.assertEqual(resp.status_code, 200, url)
        return resp.content.decode("utf-8")

    def _assert_labels(self, body):
        classes, table = _open_table(body)
        self.assertIn("sv-stack", classes)
        self.assertIn("sv-stack--pairs", classes)
        thead = re.search(r"<thead>(.*?)</thead>", table, re.S).group(1)
        heads = [_text(h) for h in re.findall(r"<th\b[^>]*>(.*?)</th>", thead)]
        # Fifteen since the 2026-09-28 merge: the tick column ("Should I
        # close?", tests/test_close_advice.py) comes first. Its header is
        # the select-all box and has no words, so its cells carry the one
        # label the header cannot: "Select". Sixteen since 2026-10-03: the
        # leverage column (tests/test_leverage_column.py) after Capital.
        self.assertEqual(len(heads), 16)
        self.assertEqual(heads[0], "")
        row = re.search(r"<tr data-sv-position-row.*?</tr>", table, re.S)
        self.assertIsNotNone(row, "no open row rendered")
        tds = _cells(row.group(0)).tds
        self.assertEqual([td.get("data-label") for td in tds],
                         ["Select"] + heads[1:])
        self.assertIn("sv-cell-wide", tds[1].get("class", "").split())
        self.assertIn("sv-cell-action", tds[-1].get("class", "").split())
        self.assertEqual(
            [i for i, td in enumerate(tds)
             if "sv-cell-action" in td.get("class", "").split()], [15])
        self.assertIn('data-sv-close-trade="%d"' % self.trade.id,
                      row.group(0).split('data-label="Action"', 1)[1])

    def test_each_open_cell_is_labelled_by_its_own_column(self):
        self._assert_labels(self._get(reverse("positions_list")))

    def test_the_live_refresh_carries_the_same_labels(self):
        self._assert_labels(self._get(reverse("positions_live")))

    def test_the_page_carries_the_sheet_and_the_viewport(self):
        body = self._get(reverse("positions_list"))
        self.assertIn('content="width=device-width, initial-scale=1, '
                      'viewport-fit=cover"', body)
        self.assertGreater(body.index("css/sv-responsive.css"),
                           body.index("css/sv-tour.css"))

    def _nav(self, body):
        m = re.search(r'<nav class="sv-phone-nav" id="svPhoneNav" '
                      r'aria-label="Main">(.*?)</nav>', body, re.S)
        self.assertIsNotNone(m, "no bottom nav")
        return m.group(1)

    def test_the_bottom_nav_links_the_four_pages_and_the_menu(self):
        nav = self._nav(self._get(reverse("positions_list")))
        self.assertEqual(
            re.findall(r'<a class="sv-pn-item" href="([^"]+)"', nav),
            [reverse(n) for n in ("command_center", "positions_list",
                                  "portfolio_overview", "briefing_dashboard")])
        self.assertEqual(
            [_text(x) for x in re.findall(
                r'<span class="sv-pn-label">(.*?)</span>', nav)],
            ["Home", "Positions", "Portfolio", "Briefing", "Menu"])
        self.assertIn('<button type="button" class="sv-pn-item" '
                      'onclick="toggleMobileSidebar()" aria-controls='
                      '"mainSidebar">', nav)
        self.assertEqual(nav.count('aria-hidden="true"'), 5)

    def test_the_current_page_and_only_it_is_marked(self):
        for url, current in ((reverse("positions_list"), "positions_list"),
                             (reverse("command_center"), "command_center")):
            nav = self._nav(self._get(url))
            self.assertEqual(nav.count('aria-current="page"'), 1, url)
            self.assertEqual(
                re.findall(r'<a class="sv-pn-item" href="([^"]+)" '
                           r'aria-current="page">', nav),
                [reverse(current)], url)
        self.assertNotIn('aria-current="page"',
                         self._nav(self._get(reverse("notifications_inbox"))))

    def test_the_account_menu_carries_the_lock_and_the_theme(self):
        body = self._get(reverse("positions_list"))
        menu = body.split('<div class="user-menu-dropdown" role="menu">', 1)[1]
        menu = menu.split('class="um-logout-form"', 1)[0]
        lock = re.search(r'<button type="button" class="um-link sv-phone-only"'
                         r'[^>]*onclick="([^"]+)"', menu)
        self.assertIsNotNone(lock)
        self.assertIn("getElementById('lockNowBtn')", lock.group(1))
        self.assertIn(".click()", lock.group(1))
        self.assertIn('<a class="um-link sv-phone-only" href="%s" '
                      'role="menuitem">' % reverse("toggle_theme"), menu)
        # The real controls stay in the topbar for a wide screen.
        self.assertIn('id="lockNowBtn"', body)
        self.assertIn('class="theme-toggle-btn"', body)


# ── D. the info panel on a phone ─────────────────────────────────────────

def _info_panel_iife():
    base = _read("templates", "base.html")
    start = base.index("(function(){", base.index("// Info panel minimize / restore toggle"))
    end = base.index("\n  })();", start) + len("\n  })();")
    return base[start:end]


HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[2], 'utf8');
function classList() {
  const s = new Set();
  return {
    add(c) { s.add(c); }, remove(c) { s.delete(c); },
    contains(c) { return s.has(c); },
    toggle(c, f) { const on = (f === undefined) ? !s.has(c) : !!f;
                   if (on) s.add(c); else s.delete(c); return on; }
  };
}
function el() {
  const l = {};
  return { classList: classList(),
           addEventListener(t, f) { (l[t] = l[t] || []).push(f); },
           fire(t) { (l[t] || []).forEach(function (f) { f({}); }); } };
}
function run(o) {
  const wrap = el(), tab = el(), pill = el();
  const store = Object.assign({}, o.store), sets = [], queries = [], changes = [];
  const mq = { matches: o.phone,
               addEventListener(t, f) { if (t === 'change') changes.push(f); } };
  vm.runInNewContext(src, {
    window: { matchMedia(q) { queries.push(q); return mq; } },
    document: { getElementById(id) {
      return ({ infoPanelWrap: wrap, ipMinTab: tab, ipRestorePill: pill })[id] || null; } },
    localStorage: {
      getItem(k) { return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
      setItem(k, v) { sets.push([k, String(v)]); store[k] = String(v); } }
  });
  const snap = () => ({ min: wrap.classList.contains('minimized'),
                        pill: pill.classList.contains('visible') });
  const out = { queries: queries, load: snap() };
  if (o.flip !== undefined) {
    mq.matches = o.flip;
    changes.forEach(function (f) { f({ matches: o.flip }); });
    out.after = snap();
  }
  if (o.click) { tab.fire('click'); out.clicked = snap(); }
  out.sets = sets;
  return out;
}
process.stdout.write(JSON.stringify({
  phone_fresh: run({ phone: true, store: {}, flip: false }),
  phone_kept: run({ phone: true, store: { ipMinimized: '1' }, flip: false }),
  desk_fresh: run({ phone: false, store: {}, click: true }),
  desk_kept: run({ phone: false, store: { ipMinimized: '1' } })
}));
"""


class InfoPanelPhoneTests(SimpleTestCase):

    def test_the_phone_fit_reads_the_768px_query_and_saves_nothing(self):
        iife = _info_panel_iife()
        self.assertIn("window.matchMedia('(max-width: 768px)')", iife)
        fit = re.search(r"function fitPhone\(\)\{(.*?)\n    \}", iife, re.S)
        self.assertIsNotNone(fit)
        self.assertNotIn("setItem", fit.group(1))
        self.assertIn("fitPhone();", iife)

    @unittest.skipUnless(NODE, "node is not installed")
    def test_the_real_iife_on_a_stub_page(self):
        tmp = Path(tempfile.mkdtemp(prefix="sv-phone-"))
        try:
            (tmp / "iife.js").write_text(_info_panel_iife(), encoding="utf-8")
            (tmp / "run.js").write_text(HARNESS, encoding="utf-8")
            proc = subprocess.run([NODE, str(tmp / "run.js"), str(tmp / "iife.js")],
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            got = json.loads(proc.stdout)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        # A phone: minimized, no pill, nothing saved; back on a wide
        # window the operator's own choice returns.
        self.assertEqual(got["phone_fresh"]["load"], {"min": True, "pill": False})
        self.assertEqual(got["phone_fresh"]["after"], {"min": False, "pill": False})
        self.assertEqual(got["phone_fresh"]["sets"], [])
        self.assertIn("(max-width: 768px)", got["phone_fresh"]["queries"])
        self.assertEqual(got["phone_kept"]["load"], {"min": True, "pill": False})
        self.assertEqual(got["phone_kept"]["after"], {"min": True, "pill": True})
        self.assertEqual(got["phone_kept"]["sets"], [])
        # A wide screen reads as it always did, and the tab still saves.
        self.assertEqual(got["desk_fresh"]["load"], {"min": False, "pill": False})
        self.assertEqual(got["desk_fresh"]["clicked"], {"min": True, "pill": True})
        self.assertEqual(got["desk_fresh"]["sets"], [["ipMinimized", "1"]])
        self.assertEqual(got["desk_kept"]["load"], {"min": True, "pill": True})
        self.assertEqual(got["desk_kept"]["sets"], [])
