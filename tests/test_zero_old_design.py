"""ZERO OLD DESIGN: the guard the old-design redo is measured by (B0,
2026-11-13), a ratchet until B24 makes it strict.

The operator, 2026-11-13: "refaites aussi tous les éléments du vieux
design svp, tout". Twenty-four pull requests redo every old element in
the new look (the plan's batches.md; the 116 rows of its inventory.md).
This guard is what makes each of them measurable, and what keeps other
work (money branches keep adding templates) from bringing an old look
back while the redo runs.

TWO HALVES, ONE BUDGET FILE (tests/old_design_budget.json):

  * THE SOURCE HALF (no browser; always runs): a census of old markers in
    every template, sheet and script, the template tags and the Python
    that emits colours. Each file's count of each marker is held to its
    budget: today's count at B0. A count may only go down, and when it
    does the budget follows it down in the same change (the ratchet
    tightens; tests.old_design.budget.lower_budgets() writes it, never
    upwards). A file absent from the budget must be at zero, so a new
    template starts clean. A failure prints file:line, the marker and the
    text. The same counts on every Python (the strings of the Python that
    paints are read through its AST: tokenize splits f-strings from 3.12).
  * THE MEASURED HALF (Chromium over its DevTools pipe; skipped where the
    machine has none): every routed page and the shell's states, as the
    browser computes them (tests/old_design_census.js, the sweep's
    collector ported), each scene's count of each marker held to its
    budget, both ways. Its notes are in tests/old_design/measure.py. It is
    tagged "old_design_measured" and runs as its own CI job, in four
    shards, in the browser and with the faces the budgets were taken with;
    there SV_OLD_DESIGN_REQUIRE=1 turns a missing browser or face into a
    failure, never a skip.

THE CEILING (tests/old_design_ceiling.json, pinned by its hash in
tests/old_design/budget.py): B0's budgets, frozen. No budget may rise
above it, so raising one is a visible change to the code. STRICT entries
name a file, a file's lines of one batch ("<file>@B7", "*@B1"), a scene,
or a shell region of a scene ("*@topbar"): a batch makes its own part
strict while the shared files and pages still hold others'.

THE META-TEST (SourceGuardBitesTests, MeasuredGuardBitesTests): one old
marker added to a temp copy fails with its file and line (its page,
selector, property and value); removed, the copy passes.

THE MARKERS (the plan's "final guard", and the critic's hole 4):

  eye_literal     the Eye's literal green (#00E868, with or without an
                  alpha, rgb(0, 232, 104), hsl()) outside the tokens and
                  the magic's light sources;
  old_literal     its old companions and the old palette's literals
                  (#40FF90, #0A5028, #030806, #3A6850, #E83030, #D8B020,
                  #FFB000, #FF5E5E);
  old_token       var(--accent-dim), var(--accent-bright), var(--accent-glow);
  accent_role     var(--accent) or var(--sv-eye) as a text, border,
                  outline, fill or stroke colour outside the roles the Eye
                  keeps (focus, selection, the brand, the active row, the
                  empty-state mark), read per item of a selector list;
  sub11           a font-size under 11 px (px, pt, rem, keywords, calc(),
                  clamp()'s floor, a size the sheet names itself; em and %
                  under half their parent; the font shorthand, an SVG
                  attribute, a script's size);
  share_tech      "Share Tech Mono", wherever it is named or loaded;
  mono_generic    the browser's generic monospace as a first face;
  old_face_load   a Google Fonts link loading Orbitron with its digits
                  (no text= subset) or Rajdhani in another weight than 600;
  badge_side      .badge-bullish / .badge-bearish on anything that is not
                  a side word (LONG, SHORT, BUY, SELL, BULL, BEAR);
  inline_visual   a style attribute (written in a template, or built by a
                  script) that carries a visual property: colour,
                  background, border, outline, font, shadow, filter;
                  geometry (sizes, offsets, transforms, custom properties
                  for data-driven bars) stays allowed;
  js_style        a script writing a visual style property directly
                  (el.style.color = ..., style['color'], cssText,
                  setProperty, setAttribute('style'), Object.assign on a
                  style);
  infinite        an endless animation (or one of 100 cycles and more)
                  outside the allowed three by their exact names
                  (sv-heartbeat, sv-armed-beat, sv-eye-breath), an endless
                  SMIL animation;
  glass           a backdrop-filter;
  gradient        a gradient (or an SVG one in a data URL) outside the
                  void, the hero card's edge and the active row's spill
                  (and the magic's own light), each item of a selector list
                  on its own subject;
  glow            a coloured shadow with a blur (box-shadow, text-shadow,
                  drop-shadow), outside the magic's light sources;
  glyph_icon      a Unicode glyph or an emoji alone in a button, a link, an
                  icon slot or a pseudo-element's content, or beside words
                  in a button ("⚙ Settings"): an icon that is not the
                  sprite's (a side's ▲ ▼, the stop's ■, a menu's ✓ are the
                  kit's);
  scrollbar       a ::-webkit-scrollbar rule (or scrollbar-color) painting
                  a colour that is not a token: computed styles cannot see
                  scrollbars, so the source holds them;
  off_token_hex   in the emails and the Python that paints (the email
                  palette in sauron_tags.py, the PDF's in reports.py), a
                  colour that is not a token's value (hex, rgb(), Color(),
                  a named colour); and in any template, an SVG painted in a
                  colour of no token.

What is never counted: sv-tokens.css's custom properties (they define the
palette, the light mode it freezes and the magic's light; any other rule
written there is read like any sheet's), the kit page's specimens (a swatch,
the type scale, the wordmark), and in sv-kit.css the rules the magic scopes
to its ambience (data-sv-ambience: the wordmark, the Eye, the
active row, live dots, the selected tab, a live hero card's edge, a side's
inset light, the moments). In the frame's sheet (sv-frame.css, B1, the
desk v2 board), the seven lights the board draws, each named by its
selector, its property and its value (rules.FRAME_LIGHT, FRAME_EMBER): the
Eye's halo, the feed pill's live dot and the docked Eye's glow under Magic
and Calm, the docked Eye's sphere, ring and core in every ambience, the
tower's ember in the menu's foot; nothing else written there (the review
of #115's guard rules, FrameLightHolesTests). A var() fallback behind a
token is inert and is not counted either.

THE FILE:LINE -> BATCH MAP (the critic's hole 5): OWNERS below names, for
every scanned file (and for the stretches of the shared files: base.html,
sauron.css, sv-overlay.css), the batch of batches.md that empties it.
Every counted marker has an owner, so none is left for B24 by default;
print_batch_map() prints the map, and the totals by batch. A file
needs an owner only once it holds a marker: a clean new file is strict.

Tests only. Synthetic data; no network, no broker, no model.

Run with:  python manage.py test tests.test_zero_old_design
"""
import json
import os
import pathlib
import re
import unittest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase, tag

from tests.old_design import routes
from tests.old_design.budget import (CEILING, CEILING_SHA256, above_ceiling, compare_measured, compare_source,
                                     load_budget, lower_measured_budgets, measured_budget_from,
                                     strict_measured_breaches, strict_source_breaches, why_unread)
from tests.old_design.measure import (CENSUS_JS, DETAIL_LINKS, IN_HOST, MEASURED, PAGES, PARTIAL_SCENES,
                                      REGIONS, SETTLE, SHARDS, CensusRun, _RUN, build_scenes, census_book,
                                      census_clients, census_opts, faces_present, freeze_patches, live_previews,
                                      machine, resolve_details, shard_of)
from tests.old_design.owners import ANCHORED, BATCHES, FILE_OWNER, STRETCHES, anchored_stretches, batch_map, owner
from tests.old_design.rules import (FRAME_EMBER, FRAME_LIGHT, FRAME_SHEET, KIT_SHEET, MARKERS, ROOT, TOKENS_SHEET,
                                    census, counts, css_hits, css_rules, file_hits, js_hits, python_hits, source_files,
                                    template_hits)
from tests.test_close_advice import CHROME, HOST, _Chrome

#: Set on the CI job: a measured class that cannot run (no browser, no
#: faces) fails there instead of skipping (the review of B0).
REQUIRE = bool(os.environ.get("SV_OLD_DESIGN_REQUIRE"))
#: The families whose face lays out whole runs of text (machine()).
LAID_OUT = ("sans-serif", "serif", "monospace", "system-ui", "Orbitron", "Rajdhani")

class SourceCensusTests(SimpleTestCase):
    """The source half: every scanned file's old markers against its
    budget, the ratchet, and the map of who empties what."""

    maxDiff = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.hits = census()
        cls.now = counts(cls.hits)
        cls.budget = load_budget()

    def test_no_file_holds_more_old_markers_than_its_budget(self):
        """A count above its budget is old design added (a file absent from
        the budget is at zero): every line of that marker in that file is
        printed, file:line, with its text."""
        over, _under = compare_source(self.now, self.budget["source"], self.hits)
        self.assertEqual(over, [], "old design above its budget:\n" + "\n".join(over))

    def test_the_budget_follows_a_count_down(self):
        """The ratchet: a count that went down takes its budget down with it
        in the same change, so nothing removed can come back unseen."""
        _over, under = compare_source(self.now, self.budget["source"], self.hits)
        self.assertEqual(under, [], "budgets above today's counts:\n" + "\n".join(under))

    def test_the_budget_names_scanned_files_and_known_markers_only(self):
        scanned = {p.relative_to(ROOT).as_posix() for p in source_files()}
        for f, marks in self.budget["source"].items():
            with self.subTest(file=f):
                self.assertIn(f, scanned)
                self.assertTrue(marks)
                for marker, n in marks.items():
                    self.assertIn(marker, MARKERS)
                    self.assertIsInstance(n, int)
                    self.assertGreater(n, 0)

    def test_a_strict_file_has_no_budget_and_no_marker(self):
        """STRICT: what a batch has emptied, held at zero for good (none at
        B0): a whole file, a file's lines of one batch ("<file>@B7"), or
        every line a batch owns ("*@B1")."""
        self.assertEqual(strict_source_breaches(self.budget["strict"]["source"], self.hits, self.now,
                                                self.budget["source"]), [])

    def test_strict_reaches_a_batch_s_lines(self):
        """A STRICT entry by batch sees that batch's lines and no other's: the
        shared files can be strict for one batch while others' remain."""
        base = [h for h in self.hits if h.file == "templates/base.html"]
        b1 = [h for h in base if owner(h.file, h.line, h.marker) == "B1"]
        self.assertTrue(b1 and len(b1) < len(base))
        self.assertEqual(len(strict_source_breaches(["templates/base.html@B1"], base, {}, {})), len(b1))
        self.assertEqual(len(strict_source_breaches(["*@B1"], self.hits, {}, {})),
                         len([h for h in self.hits if owner(h.file, h.line, h.marker) == "B1"]))
        self.assertEqual(strict_source_breaches(["templates/base.html@B1"], [h for h in base if h not in b1], {}, {}), [])

    def test_no_budget_is_above_its_ceiling(self):
        """The review of B0: B0's budgets frozen (tests/old_design_ceiling.json,
        pinned by its hash), so no budget can be raised with the marker it
        lets in, nor a file, a scene or an unreached scene added."""
        import hashlib
        self.assertEqual(hashlib.sha256(CEILING.read_bytes()).hexdigest(), CEILING_SHA256,
                         "the ceiling changed: a raise needs its hash changed in tests/old_design/budget.py, "
                         "with its reason")
        ceiling = json.loads(CEILING.read_text(encoding="utf-8"))
        self.assertEqual(above_ceiling(self.budget, ceiling), [])
        raised = json.loads(json.dumps(self.budget))
        key = sorted(raised["source"])[0]
        marker = sorted(raised["source"][key])[0]
        raised["source"][key][marker] += 1
        raised["measured"]["/new-page/"] = {"tiny": 1}
        raised["unreached"]["state:new"] = "census"
        self.assertEqual(len(above_ceiling(raised, ceiling)), 3)

    def test_every_old_marker_has_a_batch(self):
        """The critic's hole 5: every counted marker falls to a batch of
        batches.md (or a recorded exception), so none is left to B24 by
        default; print_batch_map() prints the map."""
        by_batch, orphans = batch_map(self.hits)
        self.assertEqual(["%s:%d %s" % (h.file, h.line, h.marker) for h in orphans], [])
        self.assertTrue(set(by_batch) <= set(BATCHES), set(by_batch) - set(BATCHES))
        self.assertTrue(set(FILE_OWNER.values()) <= set(BATCHES))
        for f, stretches in STRETCHES.items():
            for first, last, batch, *_only in stretches:
                self.assertIn(batch, BATCHES, f)
                self.assertLessEqual(first, last, f)
        # A file with a marker has an owner (the orphans above); a clean file
        # needs none: a new template, sheet or script built on the kit is
        # strict by the at-zero rule, and never has to name a batch (the
        # review of B0: claude/marquee's sv-marquee.js, every money branch's
        # new template). Every owner named is a file that exists.
        for rel in FILE_OWNER:
            with self.subTest(owner=rel):
                self.assertTrue((ROOT / rel).is_file(), "%s is named in FILE_OWNER and does not exist" % rel)

    def test_the_shared_files_are_cut_without_a_gap(self):
        """base.html and sauron.css are cut end to end on their own section
        notes: every anchor is found, in order, and every line has a batch,
        the critic's 2,845 unowned lines of sauron.css included."""
        for rel in ANCHORED:
            stretches, lost = anchored_stretches(rel)
            n = len((ROOT / rel).read_text(encoding="utf-8").splitlines())
            with self.subTest(file=rel):
                self.assertEqual(lost, [], "anchors no longer in %s: re-anchor their stretches" % rel)
                self.assertEqual(stretches[0][0], 1)
                self.assertEqual(stretches[-1][1], n)
                for (a, b, _x), (c, _d, _y) in zip(stretches, stretches[1:]):
                    self.assertEqual(b + 1, c)
                self.assertTrue(all(owner(rel, line) for line in range(1, n + 1)))

    def test_the_kit_and_the_tokens_flag_nothing(self):
        """No rule flags a kit component (the plan: a rule that does is a
        bug in the rule): sv-kit.css is at zero, its magic's light sources
        exempt by their scope; the tokens sheet is read, and only its
        custom properties (the palette, the magic's light) are its own: a
        rule written there is counted like any sheet's."""
        self.assertEqual([h for h in self.hits if h.file in (KIT_SHEET, TOKENS_SHEET)], [])
        self.assertTrue(any(p.relative_to(ROOT).as_posix() == TOKENS_SHEET for p in source_files()))
        sheet = (ROOT / TOKENS_SHEET).read_text(encoding="utf-8")
        self.assertEqual(css_hits(sheet, TOKENS_SHEET), [])
        planted = sheet + "\n.card { box-shadow: 0 0 18px #00e868; }\n"
        self.assertEqual(sorted(h.marker for h in css_hits(planted, TOKENS_SHEET)), ["eye_literal", "glow"])


class MarkerRuleTests(SimpleTestCase):
    """Each marker is seen where it is old, and not where the new look
    keeps it (the kit, the magic's light, a token, geometry): the census is
    neither blind nor a false alarm on the kit."""

    def markers(self, hits):
        return sorted(h.marker for h in hits)

    def css(self, text, rel="static/css/sauron.css"):
        return self.markers(css_hits(text, rel))

    def page(self, text, rel="templates/dashboard/x.html"):
        return self.markers(template_hits(text, rel))

    def test_colours(self):
        self.assertEqual(self.css(".x { color: #00E868; }"), ["eye_literal"])
        self.assertEqual(self.css(".x { border-color: rgba(0, 232, 104, .4); }"), ["eye_literal"])
        self.assertEqual(self.css(".sv-live-dot { background: var(--sv-eye, #00e868); }"), [])
        self.assertEqual(self.css(".x { background: #0a5028; }"), ["old_literal"])
        self.assertEqual(self.css(".x { background: #E83030; }"), ["old_literal"])
        self.assertEqual(self.css(".x { background: var(--accent-dim); }"), ["old_token"])
        lit = 'body:not(.light-mode)[data-sv-ambience="magic"] .sidebar-brand h1 { text-shadow: 0 0 12px #00e868; }'
        self.assertEqual(self.css(lit, KIT_SHEET), [])
        self.assertEqual(self.css(lit.replace('[data-sv-ambience="magic"]', ""), KIT_SHEET), ["eye_literal", "glow"])

    def test_the_eye_keeps_its_roles(self):
        self.assertEqual(self.css(".x a { color: var(--accent); }"), ["accent_role"])
        self.assertEqual(self.css(".x:hover { border-color: var(--accent); }"), ["accent_role"])
        self.assertEqual(self.css(".x:focus-visible { outline: 2px solid var(--accent); }"), [])
        self.assertEqual(self.css(".oc-tab.active { border-bottom: 2px solid var(--accent); }"), [])
        self.assertEqual(self.css(".sv-live-dot { background: var(--accent); }"), [])

    def test_sizes_and_faces(self):
        self.assertEqual(self.css(".x { font-size: 10px; }"), ["sub11"])
        self.assertEqual(self.css(".x { font-size: .625rem; }"), ["sub11"])
        self.assertEqual(self.css(".x { font: 600 9px/1 var(--sv-font-sans); }"), ["sub11"])
        self.assertEqual(self.css(".x { font-size: 11px; } .y { font-size: var(--sv-fs-micro); }"), [])
        self.assertEqual(self.css(".x { font-family: 'Share Tech Mono', monospace; }"), ["share_tech"])
        self.assertEqual(self.css(".x { font-family: monospace; }"), ["mono_generic"])
        self.assertEqual(self.css(".x { font-family: var(--sv-font-mono); }"), [])
        self.assertEqual(self.page('<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700">'),
                         ["old_face_load"])
        self.assertEqual(self.page('<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400..900&amp;text=ABC">'
                                   '<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@600&amp;display=swap">'), [])
        self.assertEqual(self.page('<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@300;400;600">'),
                         ["old_face_load"])
        self.assertEqual(self.page('<svg><text font-size="9">1</text></svg>'), ["sub11"])

    def test_light_and_motion(self):
        self.assertEqual(self.css(".card { box-shadow: 0 0 18px rgba(0, 232, 104, .35); }"), ["eye_literal", "glow"])
        self.assertEqual(self.css(".card { box-shadow: 0 0 18px var(--accent-glow); }"), ["glow", "old_token"])
        self.assertEqual(self.css(".x { text-shadow: 0 0 8px currentColor; }"), ["glow"])
        self.assertEqual(self.css(".pop { box-shadow: 0 8px 24px rgba(0, 0, 0, .45); }"), [])
        self.assertEqual(self.css(".x { box-shadow: inset 0 0 0 1px var(--sv-line-3); }"), [])
        self.assertEqual(self.css(".x { filter: drop-shadow(0 0 6px var(--accent)); }"), ["glow"])
        self.assertEqual(self.css(".card { background: linear-gradient(180deg, #111, #222); }"), ["gradient"])
        self.assertEqual(self.css(".nav-link.active { background: linear-gradient(90deg, #111, #222); }"), [])
        self.assertEqual(self.css(".x { backdrop-filter: blur(8px); } .y { backdrop-filter: none; }"), ["glass"])
        self.assertEqual(self.css(".x { animation: pulse 2s ease infinite; }"), ["infinite"])
        self.assertEqual(self.css(".x { animation-name: pulse; animation-iteration-count: infinite; }"), ["infinite"])
        self.assertEqual(self.css(".x { animation: sv-heartbeat 2.4s ease-in-out infinite; }"), [])
        self.assertEqual(self.css("@keyframes glowy { 50% { box-shadow: 0 0 12px var(--accent); } }"), ["glow"])
        self.assertEqual(self.page('<svg><circle r="2"><animate attributeName="r" repeatCount="indefinite"/></circle></svg>'),
                         ["infinite"])

    def test_markup(self):
        self.assertEqual(self.page('<span class="badge badge-bullish">ON</span>'), ["badge_side"])
        self.assertEqual(self.page('<span class="badge {% if a %}badge-bullish{% else %}badge-bearish{% endif %}">'
                                   '{% if a %}ARMED{% else %}OFF{% endif %}</span>'), ["badge_side"])
        self.assertEqual(self.page('<span class="badge badge-bearish">SHORT</span>'
                                   '<span class="badge badge-bullish">{{ s.direction|upper }}</span>'), [])
        self.assertEqual(self.page('<div style="color: #fff; width: 40%">x</div>'), ["inline_visual"])
        self.assertEqual(self.page('<div style="width: 40%; --w: {{ pct }}%">x</div>'), [])
        self.assertEqual(self.page('<i style="background: var({{ token }})"></i>'), [])
        self.assertEqual(self.page('<button class="x">✕</button><a class="nav-link"><span class="icon">⛁</span></a>'),
                         ["glyph_icon", "glyph_icon"])
        self.assertEqual(self.page('<span class="chg up">▲ +1.20%</span><div class="empty-icon">◌</div>'), [])
        self.assertEqual(self.css(".x .btn::before { content: '\\2715'; }"), ["glyph_icon"])
        self.assertEqual(self.css(".btn.btn-stop::before { content: '■'; }"), [])
        self.assertEqual(self.page("{# a note: color:#00e868 #}<p>x</p><!-- #00e868 -->"), [])

    def test_scripts(self):
        js = lambda s: sorted(h.marker for h in js_hits(s, "static/js/x.js"))
        self.assertEqual(js("el.style.color = 'red';"), ["js_style"])
        self.assertEqual(js("el.style.width = '4px'; el.style.transform = 'none';"), [])
        self.assertEqual(js("ctx.font = '10px Inter';"), ["sub11"])
        self.assertEqual(js("b.innerHTML = '<i style=\"color:var(--accent)\">x</i>';"), ["accent_role", "inline_visual"])
        self.assertEqual(js("// was #00e868\nvar a = 1; /* rgba(0,232,104,.3) */"), [])
        self.assertEqual(js("var c = 'rgba(0,232,104,.3)';"), ["eye_literal"])

    def test_scrollbars_and_palettes(self):
        self.assertEqual(self.css("::-webkit-scrollbar-thumb:hover { background: var(--accent-dim); }"),
                         ["old_token", "scrollbar"])
        self.assertEqual(self.css("::-webkit-scrollbar-thumb { background: var(--sv-line-2); }"), [])
        self.assertEqual(self.css(".x { scrollbar-color: var(--border) transparent; }"), ["scrollbar"])
        email = "templates/email/x.html"
        self.assertEqual(self.page('<p style="margin:0">x</p><td style="color:#888">y</td>', email),
                         ["inline_visual", "off_token_hex"])
        self.assertEqual(self.page('<td style="color:#24B582">y</td>', email), ["inline_visual"])
        py = lambda s: sorted(h.marker for h in python_hits(s, "dashboard/reports.py"))
        self.assertEqual(py("c = colors.HexColor('#c0392b')  # was #e74c3c\n"), ["off_token_hex"])
        self.assertEqual(py("c = colors.HexColor('#FF6B6E')\n"), [])

    def test_the_python_that_paints_reads_alike_on_every_python(self):
        """The review of B0: from Python 3.12 tokenize splits an f-string, and
        the census of STRING tokens no longer saw sauron_tags.py:410 on CI.
        The strings are read through the AST: an f-string whole, once."""
        py = lambda s: sorted(h.marker for h in python_hits(s, "core/templatetags/sauron_tags.py"))
        self.assertEqual(py("x = f'<a style=\"color:{LINK};text-decoration:underline;\">'\n"), ["inline_visual"])
        self.assertEqual(py("x = f'<a style=\"color:{f\"{c}\"}\">'\n"), ["inline_visual"])
        self.assertEqual(py('def f():\n    """A note on the Eye, #00e868, in a docstring."""\n'), [])
        self.assertEqual(py("x = 'rgba(0,232,104,' + a + ')'\n"), ["eye_literal"])

    def test_the_review_s_evasions_are_seen(self):
        """The looks the review of B0 planted past the source half."""
        self.assertEqual(self.css(".x { color: #00e868cc; }"), ["eye_literal"])
        self.assertEqual(self.css(".x { color: hsl(147 100% 45%); }"), ["eye_literal"])
        self.assertEqual(self.css(".x { color: #020804; }"), [])                  # near, not the old void
        self.assertEqual(self.css(".card .v { color: var(--sv-eye); }"), ["accent_role"])
        self.assertEqual(self.css(".card { outline: 2px solid var(--sv-eye); }"), ["accent_role"])
        self.assertEqual(self.css(".tab.active, .card a { color: var(--accent); }"), ["accent_role"])
        self.assertEqual(self.css(".sv-toggle input:checked + .sv-toggle-track { border-color: var(--sv-eye); }"), [])
        self.assertEqual(self.css(".rh-gear[aria-expanded=\"true\"] { border-color: var(--sv-eye); }"), [])
        for size in ("7pt", "x-small", "calc(9px + 0px)", "clamp(9px, 1vw, 14px)", ".4em", "40%"):
            self.assertEqual(self.css(".x { font-size: %s; }" % size), ["sub11"], size)
        for size in (".6em", "60%", "small", "var(--sv-fs-micro)", "clamp(11px, 1vw, 14px)"):
            self.assertEqual(self.css(".x { font-size: %s; }" % size), [], size)
        self.assertEqual(self.css(".x { --tiny: 9px; font-size: var(--tiny); }"), ["sub11"])
        self.assertEqual(self.css(".x { font: 600 7pt/1 var(--sv-font-sans); }"), ["sub11"])
        self.assertEqual(self.css(".card { box-shadow: 0 0 18px hsla(300, 100%, 50%, .6); }"), ["glow"])
        self.assertEqual(self.css(".card { box-shadow: 0 0 18px oklch(0.85 0.25 150); }"), ["glow"])
        self.assertEqual(self.css("body .card { box-shadow: 0 0 18px #ff00ff; }"), ["glow"])
        self.assertEqual(self.css("body .card { background: linear-gradient(90deg, #111, #333); }"), ["gradient"])
        self.assertEqual(self.css("body, .card { background: linear-gradient(90deg, #111, #333); }"), ["gradient"])
        self.assertEqual(self.css("body.light-mode, html { background: linear-gradient(90deg, #111, #333); }"), [])
        self.assertEqual(self.css(".card { background: url(\"data:image/svg+xml,<svg><linearGradient id='g'/></svg>\"); }"),
                         ["gradient"])
        self.assertEqual(self.css(".card { animation: sv-heartbeat-neon 1s infinite; }"), ["infinite"])
        self.assertEqual(self.css(".card { animation: sv-heartbeat 2s infinite, neon-pulse 1s infinite; }"), ["infinite"])
        self.assertEqual(self.css(".card { animation: neon-pulse 1s 1000000; }"), ["infinite"])
        self.assertEqual(self.css("@import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@700');"),
                         ["old_face_load"])
        js = lambda s: sorted(h.marker for h in js_hits(s, "static/js/x.js"))
        self.assertEqual(js("el.style.webkitBackdropFilter = 'blur(6px)';"), ["glass"])
        self.assertEqual(js("el.setAttribute('style', 'color: #ff00ff');"), ["js_style"])
        self.assertEqual(js("Object.assign(el.style, {color: '#ff00ff'});"), ["js_style"])
        self.assertEqual(js("el.style['color'] = '#ff00ff';"), ["js_style"])
        self.assertEqual(js("dot.style.fill = '#ff00ff';"), ["js_style"])
        self.assertEqual(js("el.classList.add('badge-bullish'); el.textContent = 'ARMED';"), ["badge_side"])
        self.assertEqual(js("ctx.font = '9px \"Share Tech Mono\", monospace';"), ["share_tech", "sub11"])
        self.assertEqual(self.page('<span {% if x %}style="color: #ff00ff"{% endif %}>1</span>'), ["inline_visual"])
        self.assertEqual(self.page('<input type="checkbox" style="accent-color: #ff5e00">'), ["inline_visual"])
        self.assertEqual(self.page('<button class="btn">⚙ Settings</button>'), ["glyph_icon"])
        self.assertEqual(self.page('<a class="nav-link" href="/x">🔥 Hot</a>'), ["glyph_icon"])
        self.assertEqual(self.page('<a href="/x">Full view →</a><button class="sv-menu-item">✓ Newest</button>'), [])
        self.assertEqual(self.page('<button class="btn btn-stop"><span class="sv-stop-mark">■</span> CLOSE ALL</button>'), [])
        self.assertEqual(self.page('<svg><circle r="3" fill="#ff00ff"/></svg>'), ["off_token_hex"])
        self.assertEqual(self.page('<svg class="x"><path d="M0 0" fill="var(--sv-eye)"/></svg>'), ["accent_role"])
        self.assertEqual(self.page('<div class="sidebar-brand"><svg><path fill="var(--accent)"/></svg></div>'), [])
        email = "templates/email/x.html"
        self.assertEqual(self.page('<td style="color: red">y</td>', email), ["inline_visual", "off_token_hex"])
        py = lambda s: sorted(h.marker for h in python_hits(s, "dashboard/reports.py"))
        self.assertEqual(py("c = colors.Color(0.75, 0.22, 0.17)\nd = 'rgb(192, 57, 43)'\n"),
                         ["off_token_hex", "off_token_hex"])

    def test_the_kit_page_s_specimens_are_the_kit_s(self):
        """The review of B0 (G12): the kit page's swatches, type scale and
        wordmark show the tokens and the Eye they document."""
        kit = "templates/dashboard/design_kit.html"
        self.assertEqual(self.page('<style>.dk-icon { color: var(--sv-eye); }</style>'
                                   '<div class="dk-scale-row"><span style="color: var(--sv-eye);">SAURON</span></div>', kit),
                         [])
        self.assertEqual(self.page('<style>.dk-icon { color: var(--sv-eye); }</style>'), ["accent_role"])

    #: The frame's seven lights as sv-frame.css writes them (B1, the desk v2
    #: board): the Eye's halo in the 44 px head and the feed pill's live dot
    #: under Magic and Calm; the docked Eye's sphere, ring and core in every
    #: ambience (Desk2's .orb, and .amb-off .orb); its glow under Magic and
    #: Calm; the tower's ember. Each with the markers it carries in another
    #: sheet.
    LIT = 'html body:not(.light-mode):is([data-sv-ambience="magic"], [data-sv-ambience="calm"])'
    FRAME_LIGHTS = (
        (LIT + " .sidebar .sidebar-brand .brand-eye-wrap::before { background: radial-gradient(circle,"
         " rgba(0,232,104,.34) 0%, rgba(0,232,104,.16) 40%, rgba(0,232,104,0) 70%); }", ["eye_literal", "gradient"]),
        (LIT + " .live-status-pill .lsp-green { box-shadow: var(--sv-glow-dot); }", ["glow"]),
        ("html body .se-eye-fab:not(.open) { background: radial-gradient(circle at 38% 34%, rgba(220,255,235,.55) 0 8%,"
         " rgba(0,232,104,.35) 22%, rgba(4,30,16,.95) 62%, var(--sv-bg-0) 100%); }", ["eye_literal", "gradient"]),
        ("html body .se-eye-fab:not(.open) { box-shadow: inset 0 0 0 1px rgba(0,232,104,.55); }", ["eye_literal"]),
        ("html body .se-eye-fab:not(.open)::after { background: radial-gradient(circle, rgba(0,232,104,.95),"
         " rgba(0,232,104,0) 70%); }", ["eye_literal", "gradient"]),
        (LIT + " .se-eye-fab:not(.open) { box-shadow: inset 0 0 0 1px rgba(0,232,104,.55),"
         " 0 0 10px rgba(0,232,104,.28); }", ["eye_literal", "glow"]),
        (".sv-tower .sv-tower-eye { fill: var(--sv-eye); fill-opacity: .35; }", ["accent_role"]),
    )

    def test_the_frame_s_lights_are_named_one_by_one(self):
        """B1 (the desk v2 board, approved 2026-11-13), as tightened after the
        review of its two guard rules (#115): in the frame's sheet the seven
        lights the board draws pass, each named by its selector, its
        property and its value (rules.FRAME_LIGHT, FRAME_EMBER). The same
        declaration in another sheet is counted, and so it is there with one
        thing changed: its value, its ambience, its property or its
        selector (a list with one more item, another state, the orb's
        other pseudo-element, a descendant)."""
        frame = FRAME_SHEET
        for rule, markers in self.FRAME_LIGHTS:
            with self.subTest(rule=rule[:90]):
                self.assertEqual(self.css(rule, frame), [])
                self.assertEqual(self.css(rule), markers)
        halo, dot, sphere, ring, core, glow, ember = (r for r, _m in self.FRAME_LIGHTS)
        changed = [
            # its value
            (halo.replace(".34) 0%", ".7) 0%"), ["eye_literal", "gradient"]),
            (dot.replace("var(--sv-glow-dot)", "0 0 12px var(--sv-eye)"), ["glow"]),
            (ring.replace(".55)", ".9)"), ["eye_literal"]),
            (glow.replace("0 0 10px", "0 0 40px 12px"), ["eye_literal", "glow"]),
            (ember.replace("fill-opacity: .35", "fill-opacity: 1"), ["accent_role"]),
            (ember.replace(" fill-opacity: .35;", ""), ["accent_role"]),
            # its ambience: Off, or none
            (halo.replace(':is([data-sv-ambience="magic"], [data-sv-ambience="calm"])', '[data-sv-ambience="off"]'),
             ["eye_literal", "gradient"]),
            (dot.replace(':is([data-sv-ambience="magic"], [data-sv-ambience="calm"])', ""), ["glow"]),
            (glow.replace(':is([data-sv-ambience="magic"], [data-sv-ambience="calm"])', ""), ["eye_literal", "glow"]),
            # its property
            (sphere.replace("background:", "border-image:"), ["eye_literal", "gradient"]),
            (dot.replace("box-shadow:", "text-shadow:"), ["glow"]),
            (ember.replace("fill:", "stroke:"), ["accent_role"]),
            # its selector
            (sphere.replace("html body .se-eye-fab:not(.open)", "html body .se-eye-fab:not(.open), html body .card"),
             ["eye_literal", "gradient"]),
            (ring.replace(".se-eye-fab:not(.open)", ".se-eye-fab.working"), ["eye_literal"]),
            (core.replace("::after", "::before"), ["eye_literal", "gradient"]),
            (ring.replace(":not(.open)", ":not(.open) .se-fab-label"), ["eye_literal"]),
            (ember.replace(".sv-tower .sv-tower-eye", ".sidebar .sv-tower .sv-tower-eye"), ["accent_role"]),
        ]
        for rule, markers in changed:
            with self.subTest(changed=rule[:90]):
                self.assertEqual(self.css(rule, frame), markers)
        # The tower is no place of the brand: what sits under it is read like
        # anything in a template.
        self.assertEqual(self.page('<div class="sv-tower"><svg><ellipse fill="var(--sv-eye)"/></svg></div>'),
                         ["accent_role"])
        # A lane's fade painted over its ends is a gradient, even there.
        self.assertEqual(self.css("html body .sv-band .ticker-bar::after { right: 0;"
                                  " background: linear-gradient(270deg, var(--sv-bg-1), transparent); }", frame),
                         ["gradient"])

    def test_the_frame_s_named_lights_are_its_own(self):
        """Every light rules.py names for the frame is a declaration the
        frame's sheet makes, exactly as named (a name the sheet stops using
        goes with it, never left behind for a look to come back under), and
        the sheet, read with them, holds no marker."""
        sheet = (ROOT / FRAME_SHEET).read_text(encoding="utf-8")
        rules = [(" ".join(selector.split()), {p.lower(): " ".join(v.split()) for p, v, _l in decls})
                 for selector, _line, decls in css_rules(sheet)]
        self.assertEqual(len(FRAME_LIGHT), 6)
        for selector, prop, value in FRAME_LIGHT:
            with self.subTest(light="%s { %s }" % (selector, prop)):
                self.assertTrue(any(s == selector and d.get(prop) == value for s, d in rules))
        named, fill, token, (dose_prop, dose) = FRAME_EMBER
        self.assertTrue(any(s == named and d.get(fill) == token and d.get(dose_prop) == dose for s, d in rules))
        self.assertEqual(css_hits(sheet, FRAME_SHEET), [])


class FrameLightHolesTests(SimpleTestCase):
    """The review of B1's two guard rules (#115, on a0a6b7a: a scope lens
    and a mutation lens). B1 had read the frame's sheet like the kit's (a
    rule whose selector named the ambience anywhere, or whose every item's
    subject named the docked Eye's class, was the magic's light), and made
    the tower a place of the brand in every sheet and template. Each hole
    the lenses found is planted here as they planted it, in a temp copy of
    a file at zero, and fails the guard's source half with that file, a
    line of the planted text and its markers: red on 1b51023, where each
    passed the source half (and six of them the whole guard), green once
    the frame's lights are named one by one (rules.FRAME_LIGHT,
    FRAME_EMBER). The lenses' ids are in the names: the mutation lens's a3
    to h1, the scope lens's E1 to E13, T1 to T3 and M1."""

    FRAME = FRAME_SHEET
    #: The mutation lens planted its rules at the end of the frame's 769 px
    #: block, before its tiers note.
    ANCHOR = "/* ── The tiers "
    SCOPE = 'html body:not(.light-mode):is([data-sv-ambience="magic"], [data-sv-ambience="calm"])'
    MAGIC = 'html body:not(.light-mode)[data-sv-ambience="magic"]'
    EYE_GLOW = "0 0 18px rgba(0, 232, 104, .45)"
    TEXT_GLOW = "0 0 8px rgba(0, 232, 104, .6)"
    LANE_FADE = ("content: ''; position: absolute; top: 0; right: 0; bottom: 0; width: 24px; z-index: 1;"
                 " pointer-events: none; background: linear-gradient(270deg, var(--sv-bg-1), transparent);")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.budget = load_budget()["source"]

    def setUp(self):
        import shutil as _shutil
        import tempfile
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="sv-guard-holes-"))
        self.addCleanup(_shutil.rmtree, self.tmp, True)

    def guard(self, plant, rel=FRAME, over=None):
        """The guard's source half on a temp copy of `rel` (a file at zero)
        with `plant` added (in the frame's sheet before its tiers note,
        elsewhere at the end), or with `over` = (old, new) written over one
        of its rules: the markers it finds above the budget, each on a line
        of the planted text."""
        self.assertNotIn(rel, self.budget)
        path = ROOT / rel
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        if over:
            old, new = over
            self.assertEqual(text.count(old), 1, "the reviewed rule is no longer in %s: %r" % (rel, old))
            at = text.index(old)
            text = text.replace(old, new)
            planted = text[at:text.index("}", at)]          # the rule written over, to its end
        else:
            at = text.index(self.ANCHOR) if rel == self.FRAME else len(text)
            planted = plant + "\n"
            text = text[:at] + planted + text[at:]
        first = text.count("\n", 0, at) + 1
        last = first + planted.count("\n")
        copy = self.tmp / pathlib.Path(rel).name
        copy.write_text(text, encoding="utf-8")
        hits = file_hits(copy, rel)
        over_budget, _under = compare_source(counts(hits), {f: m for f, m in self.budget.items() if f == rel}, hits)
        found = re.findall(r"^    (\S+):(\d+) (\w+) \[", "\n".join(over_budget), re.M)
        for f, line, marker in found:
            self.assertEqual(f, rel)
            self.assertTrue(first <= int(line) <= last,
                            "%s:%s %s is off the planted lines %d-%d" % (f, line, marker, first, last))
        return sorted(marker for _f, _line, marker in found)

    # ── The mutation lens: seventeen the source half let through ────────

    def test_a3_a_card_glows_in_the_eye_s_green_under_magic_and_calm(self):
        self.assertEqual(self.guard("%s .page-content .card { box-shadow: %s; }" % (self.SCOPE, self.EYE_GLOW)),
                         ["eye_literal", "glow"])

    def test_a4_a_card_glows_behind_a_not_of_the_docked_eye(self):
        self.assertEqual(self.guard("html body .page-content .card:not(.se-eye-fab) { box-shadow: %s; }"
                                    % self.EYE_GLOW),
                         ["eye_literal", "glow"])

    def test_a5_the_dock_s_buttons_glow_on_a_hover_under_magic(self):
        """One of the six the whole guard let through: the measured half's
        forced pass hovers no dock button."""
        self.assertEqual(self.guard("%s .sv-dock-btn:hover { box-shadow: 0 0 10px rgba(0, 232, 104, .6); }"
                                    % self.MAGIC),
                         ["eye_literal", "glow"])

    def test_b2_a_menu_label_in_the_eye_s_literal_under_magic(self):
        self.assertEqual(self.guard("%s .sidebar .nav-link .label-text { color: #00e868; }" % self.MAGIC),
                         ["eye_literal"])

    def test_b3_a_menu_label_in_the_eye_under_a_has_of_the_tower(self):
        self.assertEqual(self.guard("html body .sidebar:has(.sv-tower) .nav-link .label-text"
                                    " { color: var(--sv-eye); }"),
                         ["accent_role"])

    def test_c2_a_glow_behind_a_bar_figure_under_magic_and_calm(self):
        self.assertEqual(self.guard("%s .info-panel-bar .ip-cat .ip-v { text-shadow: %s; }"
                                    % (self.SCOPE, self.TEXT_GLOW)),
                         ["eye_literal", "glow"])

    def test_c4_a_pool_of_the_eye_s_light_behind_the_real_book_s_figure_under_magic(self):
        """One of the six the whole guard let through: the measured half saw
        one gradient more on /positions/, inside that page's room (17 of
        18)."""
        cell = '%s .info-panel-bar [data-sv-cell="portfolio"] .ip-v' % self.MAGIC
        self.assertEqual(self.guard("%s { position: relative; }\n%s::before { content: ''; position: absolute;"
                                    " inset: -6px -10px; z-index: -1; pointer-events: none;"
                                    " background: radial-gradient(closest-side, rgba(0, 232, 104, .35), transparent); }"
                                    % (cell, cell)),
                         ["eye_literal", "gradient"])

    def test_d2_the_docked_eye_s_before_draws_a_glowing_number(self):
        number = ("html body .se-eye-fab:not(.open)::before { content: '3'; position: absolute; top: -8px; right: -6px;"
                  "%s font: 600 11px/1 var(--sv-font-mono); color: var(--sv-ink-1); text-shadow: %s; }")
        self.assertEqual(self.guard(number % ("", self.TEXT_GLOW)), ["eye_literal", "glow"])
        # Drawn for real (the old tooltip's own paint put back to none).
        shown = " left: auto; transform: none; opacity: 1; padding: 0; border: 0; background: none; box-shadow: none;"
        self.assertEqual(self.guard(number % (shown, self.TEXT_GLOW)), ["eye_literal", "glow"])

    def test_d3_the_docked_eye_s_label_glows_through_an_is(self):
        self.assertEqual(self.guard("html body :is(.se-eye-fab:not(.open) .se-fab-label) { display: inline-block;"
                                    " text-shadow: %s; }" % self.TEXT_GLOW),
                         ["eye_literal", "glow"])

    def test_e1_an_eye_border_on_the_tower(self):
        self.assertEqual(self.guard("html body .sidebar .sv-tower { border-top: 1px solid var(--sv-eye); }"),
                         ["accent_role"])

    def test_e2_an_eye_border_on_the_menu_beside_the_tower(self):
        self.assertEqual(self.guard("html body .sidebar .sidebar-nav:has(~ .sv-tower)"
                                    " { border-bottom: 1px solid var(--sv-eye); }"),
                         ["accent_role"])

    def test_f2_the_docked_eye_s_glow_in_every_ambience(self):
        """One of the six the whole guard let through: no measured scene
        runs Off."""
        scoped = self.SCOPE + " .se-eye-fab:not(.open) {"
        self.assertEqual(self.guard(None, over=(scoped, "html body:not(.light-mode) .se-eye-fab:not(.open) {")),
                         ["eye_literal", "glow"])

    def test_f4_the_eye_s_halo_drawn_again_under_off(self):
        """One of the six the whole guard let through: no measured scene
        runs Off."""
        self.assertEqual(self.guard('html body:not(.light-mode)[data-sv-ambience="off"] .sidebar .sidebar-brand'
                                    " .brand-eye-wrap::before { opacity: .7; width: 38px; height: 38px;"
                                    " background: radial-gradient(circle, rgba(0,232,104,.34) 0%,"
                                    " rgba(0,232,104,.16) 40%, rgba(0,232,104,0) 70%); }"),
                         ["eye_literal", "gradient"])

    def test_g2_both_lanes_painted_fades_back_under_magic(self):
        self.assertEqual(self.guard("%s .sv-band .ticker-bar::after, %s .sv-band .data-headband::after { %s }"
                                    % (self.MAGIC, self.MAGIC, self.LANE_FADE)),
                         ["gradient"])

    def test_g3_the_whole_old_fade_back_under_magic(self):
        left = self.LANE_FADE.replace("right: 0;", "left: 0;").replace("270deg", "90deg")
        self.assertEqual(self.guard("%s .sv-band .ticker-bar::after, %s .sv-band .data-headband::after { %s }\n"
                                    "%s .sv-band .ticker-bar::before, %s .sv-band .data-headband::before { %s }"
                                    % (self.MAGIC, self.MAGIC, self.LANE_FADE, self.MAGIC, self.MAGIC, left)),
                         ["gradient", "gradient"])

    def test_g4_one_lane_end_s_painted_fade_back_under_magic(self):
        """One of the six the whole guard let through: the measured half saw
        one gradient more on the pages at rest, each inside its page's
        room."""
        self.assertEqual(self.guard("%s .sv-band .ticker-bar::after { %s }" % (self.MAGIC, self.LANE_FADE)),
                         ["gradient"])

    def test_h1_an_eye_edge_on_a_card_by_border_image_under_magic_and_calm(self):
        """One of the six the whole guard let through: the measured half
        reads a gradient in a background only."""
        self.assertEqual(self.guard("%s .page-content .card { border-image: linear-gradient(90deg, var(--sv-eye),"
                                    " transparent 60%%) 1; }" % self.SCOPE),
                         ["gradient"])

    # ── The scope lens: the docked Eye's class read as text ─────────────

    def test_E1_eye_text_and_a_glow_on_a_bar_figure_behind_a_not(self):
        self.assertEqual(self.guard("html body .info-panel-bar .ip-cat .ip-v:not(.se-eye-fab) { color: #00E868;"
                                    " text-shadow: 0 0 12px rgba(0,232,104,.8); }"),
                         ["eye_literal", "eye_literal", "glow"])

    def test_E2_neon_on_every_button_through_an_is(self):
        self.assertEqual(self.guard("html body :is(.se-eye-fab, .btn-primary, .tk-long) { box-shadow: 0 0 18px"
                                    " rgba(0,232,104,.6); border: 1px solid #00E868; }"),
                         ["eye_literal", "eye_literal", "glow"])

    def test_E3_the_fill_banners_lit_as_the_docked_eye_s_sibling(self):
        self.assertEqual(self.guard("html body .se-eye-fab ~ #svBannerStack { box-shadow: 0 0 24px #00E868;"
                                    " background: linear-gradient(90deg, rgba(0,232,104,.3), transparent); }"),
                         ["eye_literal", "eye_literal", "glow", "gradient"])

    def test_E4_the_old_palette_on_the_pin_lock_as_the_docked_eye_s_sibling(self):
        self.assertEqual(self.guard("html body .se-eye-fab ~ .il-overlay { background: radial-gradient(circle, #0A5028,"
                                    " #030806); box-shadow: inset 0 0 80px #40FF90; }"),
                         ["glow", "gradient", "old_literal", "old_literal"])

    def test_E5_the_docked_eye_in_the_old_neon(self):
        self.assertEqual(self.guard("html body .se-eye-fab:not(.open) { background: radial-gradient(circle, #40FF90 0%,"
                                    " rgba(0,232,104,.9) 30%, #0A5028 100%); box-shadow: 0 0 40px 12px"
                                    " rgba(64,255,144,.9), 0 0 90px rgba(0,232,104,.8); }"),
                         ["eye_literal", "eye_literal", "glow", "glow", "gradient", "old_literal", "old_literal"])

    def test_E6_the_docked_eye_s_old_hover_label(self):
        self.assertEqual(self.guard('html body .se-eye-fab::before { content: "ASK SAURON"; color: #00E868;'
                                    " border: 1px solid rgba(0,232,104,.4); text-shadow: 0 0 8px #00E868;"
                                    " background: linear-gradient(180deg, rgba(8,22,14,.95), rgba(4,12,8,.95)); }"),
                         ["eye_literal", "eye_literal", "eye_literal", "glow", "gradient"])

    def test_E11_an_old_neon_kept_in_a_property_set_where_the_docked_eye_is(self):
        """The glow it carries through var() is the measured half's to see;
        the source half counts the old literal it is written with."""
        self.assertEqual(self.guard("html body:has(.se-eye-fab) { --x-neon: 0 0 24px #40FF90; }\n"
                                    "html body .info-panel-bar .ip-cat .ip-v { text-shadow: var(--x-neon); }"),
                         ["old_literal"])

    def test_E12_a_gradient_on_every_panel_through_a_where(self):
        self.assertEqual(self.guard("html body :where(.se-eye-fab, .sv-panel) { background: linear-gradient(180deg,"
                                    " rgba(0,232,104,.25), transparent); }"),
                         ["eye_literal", "gradient"])

    def test_E13_the_docked_eye_s_working_state_in_the_old_neon(self):
        self.assertEqual(self.guard("html body .se-eye-fab.working { box-shadow: 0 0 30px #00E868,"
                                    " 0 0 60px #40FF90; }"),
                         ["eye_literal", "glow", "glow", "old_literal"])

    # ── The scope lens: the ambience read as text ───────────────────────

    def test_E7_a_glow_on_a_bar_figure_under_calm_alone(self):
        self.assertEqual(self.guard('html body[data-sv-ambience="calm"] .info-panel-bar .ip-cat .ip-v'
                                    " { text-shadow: 0 0 12px #00E868; }"),
                         ["eye_literal", "glow"])

    def test_E8_real_armed_glowing_under_off(self):
        self.assertEqual(self.guard('html body[data-sv-ambience="off"] .sv-armed-pill { box-shadow: 0 0 14px'
                                    " rgba(232,48,48,.8); background: linear-gradient(#E83030, #8a1010); }"),
                         ["glow", "gradient", "old_literal", "old_literal"])

    def test_E9_a_glow_on_every_band_price_behind_a_not_of_the_ambience(self):
        self.assertEqual(self.guard("html body .sv-band .dh-item .dh-val:not([data-sv-ambience])"
                                    " { text-shadow: 0 0 10px rgba(0,232,104,.7); }"),
                         ["eye_literal", "glow"])

    def test_E10_one_scoped_item_frees_a_card_in_its_list(self):
        self.assertEqual(self.guard('html body[data-sv-ambience="magic"] .sidebar-brand h1, html body .card'
                                    " { box-shadow: 0 0 20px #00E868; }"),
                         ["eye_literal", "glow"])

    # ── The scope lens: the tower, a place in every sheet and template ──

    def test_T1_the_eye_on_a_button_under_a_has_of_the_tower_in_another_sheet(self):
        self.assertEqual(self.guard("body:has(.sv-tower) .btn-primary { color: var(--sv-eye);"
                                    " border-color: var(--sv-eye); }", rel=KIT_SHEET),
                         ["accent_role", "accent_role"])

    def test_T2_an_eye_edge_on_a_card_behind_a_not_of_the_tower_in_another_sheet(self):
        self.assertEqual(self.guard(".card:not(.sv-tower) { border-left: 2px solid var(--sv-eye); }", rel=KIT_SHEET),
                         ["accent_role"])

    def test_T3_the_eye_on_a_link_as_the_tower_s_sibling_in_another_sheet(self):
        self.assertEqual(self.guard(".sv-tower ~ .sidebar-footer a { color: var(--accent); }", rel=KIT_SHEET),
                         ["accent_role"])

    def test_M1_a_chart_in_the_eye_under_a_box_named_tower_in_a_template(self):
        self.assertEqual(self.guard('<div class="sv-panel sv-tower"><svg>'
                                    '<polyline stroke="var(--sv-eye)" points="0,0 9,9"/>'
                                    '<text fill="var(--sv-eye)">1,234.50</text></svg></div>',
                                    rel="templates/dashboard/new_page.html"),
                         ["accent_role", "accent_role"])


class _MeasuredShard:
    """The measured half, one shard: every routed page, the partial routes
    in their pages, the shell's states, the forced pass, the phone pass and
    light mode's §10 check, each held to its budget. Set SV_OLD_DESIGN_ONLY
    to a comma list of scene keys (or their beginnings) to measure only
    those while a batch works; SV_OLD_DESIGN_DUMP=<path> writes the run;
    SV_OLD_DESIGN_LOWER=1 lowers the budgets a full run went under."""

    SHARD = 0
    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        from django.core.cache import cache
        if not CHROME:
            raise AssertionError("no headless Chromium on this machine (SV_OLD_DESIGN_REQUIRE is set)")
        cls.glyphs = faces_present()
        if REQUIRE and not cls.glyphs:
            raise AssertionError("Inter and JetBrains Mono are not installed (SV_OLD_DESIGN_REQUIRE is set)")
        cls._patches = freeze_patches()
        for p in cls._patches:
            p.start()
            # Stopped even when this setup raises (tearDownClass would not run).
            cls.addClassCleanup(p.stop)
        cache.clear()
        user, held, paper = census_book()
        clients = census_clients(user)
        details = resolve_details(clients["main"], user)
        scenes = shard_of(build_scenes(details, held["EURUSD"].id, paper.id), cls.SHARD)
        only = [x for x in os.environ.get("SV_OLD_DESIGN_ONLY", "").split(",") if x]
        if only:
            scenes = [s for s in scenes if any(s["key"].startswith(x) for x in only)]
        cls.only = bool(only)
        previews = {}
        if any(s["key"] in ("state:take_trade_live", "state:take_trade_short") for s in scenes):
            # The paper preview the view answers, from which the live and the
            # short ones are made (never sent to a broker).
            first = CensusRun(clients, [s for s in build_scenes(details, held["EURUSD"].id, paper.id)
                                        if s["key"] == "state:take_trade_paper"], glyphs=False)
            first.run()
            previews = live_previews(next(iter(first.previews.values()), None), paper.id)
        run = CensusRun(clients, scenes, glyphs=cls.glyphs, previews=previews)
        run.run()
        cls.machine = machine(run.browser)
        cls.scene_keys = [s["key"] for s in scenes]
        cls.results, cls.timing = run.results, run.timing
        _RUN.setdefault("results", {}).update(run.results)
        _RUN.setdefault("timing", {})["shard %d" % cls.SHARD] = run.timing.get("__total__")
        dump = os.environ.get("SV_OLD_DESIGN_DUMP")
        if dump:
            path = pathlib.Path(dump.replace(".json", "") + "_shard%d.json" % cls.SHARD)
            path.write_text(json.dumps({"results": run.results, "timing": run.timing, "details": details,
                                        "glyphs": cls.glyphs, "previews": previews, "machine": cls.machine},
                                       indent=1, default=str))

    def test_the_machine_is_the_budget_s(self):
        """The budgets were taken in one browser with one set of faces (the
        review of B0): another counts otherwise, and says so here first,
        before the counts do. Compared: the browser, and the face each
        family a page names resolves to (a whole run of text is laid out
        in it); the faces that stand in for a lone glyph are recorded only
        (which face draws a ▶ the four cannot changes no count)."""
        want = load_budget()["machine"]
        mine = {"browser": self.machine["browser"],
                "faces": {k: v for k, v in self.machine["faces"].items() if k in LAID_OUT}}
        self.assertEqual(mine, {"browser": want["browser"],
                                "faces": {k: v for k, v in want["faces"].items() if k in LAID_OUT}},
                         "this machine is not the one the budgets were measured on: install the browser and "
                         "the faces the CI job installs (.github/workflows/tests.yml, old-design-measured)")

    def test_every_scene_was_measured(self):
        """Every page answered and was read, every state was reached: its act
        changed the page and what it opens is on the screen (the review of
        B0 found nine states that read as their page). What the book cannot
        reach is recorded in the budget ("unreached"), and still unreached
        (so a fixture that reaches it updates the record)."""
        unreached = {k: v for k, v in load_budget().get("unreached", {}).items() if k in self.scene_keys}
        got = {k: why_unread(k, r) for k, r in self.results.items()}
        missing = {k: why for k, why in got.items() if why}
        if self.only:
            missing = {k: v for k, v in missing.items() if k not in unreached}
            unreached = {}
        self.assertEqual(sorted(missing), sorted(unreached), json.dumps(missing, indent=1))

    def test_no_page_or_state_holds_more_old_markers_than_its_budget(self):
        """The ratchet: per page and per state, each marker's count at most
        its budget (a scene absent from the budget at zero). A failure names
        the page or state, then every element group by selector, with the
        property and the value."""
        over, under = compare_measured(self.results, load_budget()["measured"], glyphs=self.glyphs)
        if os.environ.get("SV_OLD_DESIGN_LOWER") and not over and not self.only:
            lower_measured_budgets(self.results, glyphs=self.glyphs)
        self.assertEqual(over, [], "old design above its measured budget:\n" + "\n".join(over))

    def test_the_measured_budget_follows_a_count_down(self):
        """The other way (the review of B0): a count under its budget fails
        until the budget follows it, so nothing a batch removed can come
        back unseen; a layout marker may sit up to its slack under."""
        if os.environ.get("SV_OLD_DESIGN_LOWER"):
            return          # lowered by the test above, in this same run
        _over, under = compare_measured(self.results, load_budget()["measured"], glyphs=self.glyphs)
        self.assertEqual(under, [], "measured budgets above today's counts:\n" + "\n".join(under))

    def test_a_strict_page_is_at_zero(self):
        """STRICT (none at B0): a page or state a batch has emptied stays
        empty, its budget gone; a shell region made strict stays empty on
        every page ("*@topbar") or one ("/positions/@rail")."""
        budget = load_budget()
        self.assertEqual(strict_measured_breaches(budget["strict"]["measured"], self.results, budget["measured"]), [])
        regions = {name for name, _sel in REGIONS} | {"other"}
        for entry in budget["strict"]["measured"]:
            _scene, _at, region = entry.partition("@")
            if region:
                self.assertIn(region, regions)

    def test_every_hit_has_a_region(self):
        """The regions add up to the scene: each counted element sits in
        exactly one shell region (or the page, or other)."""
        for key, r in self.results.items():
            if why_unread(key, r):
                continue
            total = {}
            for rc in r.get("regions", {}).values():
                for marker, n in rc.items():
                    total[marker] = total.get(marker, 0) + n
            with self.subTest(scene=key):
                self.assertEqual(total, {m: n for m, n in r["counts"].items() if n})

    def test_the_critic_s_holes_are_measured(self):
        """Hole 1: the regions htmx and scripts fill are filled (the KPI
        strips, /command/'s tab bodies, the bot panel, /eye/'s body, the
        rail's cards); hole 2: the forced pass reached the shell, the money
        controls and every control of its page; hole 3: the phone pass ran
        at 390 px."""
        r = {k: v for k, v in self.results.items() if not v.get("error")}
        checks = 0
        for key in ("/positions/", "/portfolio/", "/signals/", "/news/", "/backtest/", "/strategies/"):
            if key in r:
                checks += 1
                with self.subTest(region="KPI strip", page=key):
                    self.assertEqual(r[key]["probe"]["metricsEmpty"], 0)
                    self.assertGreater(r[key]["probe"]["metricsFilled"], 0)
        for key in ["/command/"] + [partial for _p, partial in PARTIAL_SCENES]:
            if key in r:
                checks += 1
                with self.subTest(region="command tab", scene=key):
                    self.assertEqual(r[key]["probe"]["ocLoading"], 0)
                    self.assertGreater(r[key]["probe"]["ocBody"], 0)
        for key, probe, least in (("/admin-dashboard/", "adminBots", 1), ("/eye/", "eyeBody", 1),
                                  ("state:rail_bullish", "railCards", 2)):
            if key in r:
                checks += 1
                self.assertGreaterEqual(r[key]["probe"][probe], least, key)
        for key, res in r.items():
            if key.startswith("hover:"):
                checks += 1
                with self.subTest(forced=key):
                    self.assertGreater(res.get("forced", 0), 50)
            if key.startswith("390:"):
                checks += 1
                with self.subTest(phone=key):
                    self.assertEqual(res["probe"]["width"], 390)
                    self.assertTrue(res["probe"]["coarse"])         # a finger
            elif "probe" in res:
                with self.subTest(desk=key):
                    self.assertTrue(res["probe"]["hover"])          # a mouse (the operator's desk)
        if not self.only:
            self.assertGreater(checks, 3)


def _measured(cls):
    """A measured class: tagged for its own CI job; skipped where no
    Chromium is, unless SV_OLD_DESIGN_REQUIRE says it must run."""
    cls = tag("old_design_measured")(cls)
    return unittest.skipUnless(CHROME or REQUIRE, "no headless Chromium on this machine")(cls)


@_measured
class MeasuredShard1Tests(_MeasuredShard, TestCase):
    SHARD = 0


@_measured
class MeasuredShard2Tests(_MeasuredShard, TestCase):
    SHARD = 1


@_measured
class MeasuredShard3Tests(_MeasuredShard, TestCase):
    SHARD = 2


@_measured
class MeasuredShard4Tests(_MeasuredShard, TestCase):
    SHARD = 3


class MeasuredSceneListTests(SimpleTestCase):
    """The measured half's plan, read without a browser: the shards cover
    every scene once, the budget names scenes and markers the census has,
    every scene the budget records as unreached is a scene."""

    def scenes(self):
        return build_scenes({r: "/" for r in DETAIL_LINKS}, 1, 2)

    def test_the_shards_cover_every_scene_once(self):
        keys = [s["key"] for s in self.scenes()]
        self.assertEqual(len(keys), len(set(keys)))
        shards = [[s["key"] for s in shard_of(self.scenes(), i)] for i in range(SHARDS)]
        self.assertEqual(sorted(sum(shards, [])), sorted(keys))

    def test_the_budget_names_scenes_and_markers_the_census_has(self):
        keys = {s["key"] for s in self.scenes()}
        budget = load_budget()
        for key, marks in budget["measured"].items():
            with self.subTest(scene=key):
                self.assertIn(key, keys)
                self.assertTrue(set(marks) <= set(MEASURED), set(marks) - set(MEASURED))
        for key in budget.get("unreached", {}):
            self.assertIn(key, keys)
        self.assertTrue(budget["machine"]["browser"])

    def test_every_page_route_is_a_scene(self):
        """Every route of the URL conf whose view renders a whole page is a
        scene or recorded with its reason (routes.NOT_MEASURED), read from
        the code, so a page added later (Barad-dûr's "/", Anduin, OC1, the
        orders' pages) is measured from its first day, at zero; and every
        page of the list is still routed. About forty states beside them:
        the plan's "every routed page and about 25 states", and the
        critic's."""
        keys = {s["key"] for s in self.scenes()}
        routed = {route for route, _p in routes.url_patterns()}
        documents = routes.page_routes()
        self.assertGreater(len(documents), 90)
        for route in sorted(documents):
            with self.subTest(route=route):
                self.assertTrue(route in PAGES or route in routes.NOT_MEASURED,
                                "%s renders %s and is not measured: add it to PAGES (its budget is zero)"
                                % (route, documents[route]))
        for route in PAGES:
            with self.subTest(listed=route):
                self.assertIn(route, routed, "%s is in PAGES and no longer routed" % route)
                if route not in IN_HOST:
                    self.assertTrue(route in keys or any(k.startswith(route.split("<")[0]) for k in keys))
        for route in routes.NOT_MEASURED:
            self.assertIn(route, routed)
        self.assertGreaterEqual(len([k for k in keys if k.startswith("state:")]), 25)

    def test_the_route_reader_sees_a_new_page(self):
        """The reader is not vacuous: /popout/ and /strategies/new/ (the two
        the sweep's list missed) are pages; a JSON route is not."""
        documents = routes.page_routes()
        self.assertIn("/popout/", documents)
        self.assertIn("/strategies/new/", documents)
        self.assertNotIn("/partials/ticker/", documents)
        self.assertTrue(routes.is_document("base.html"))
        self.assertFalse(routes.is_document("_partials/ticker_items.html"))

    def test_every_state_names_what_it_opens(self):
        """A state with an act says what must be on the screen after it: one
        that never opened fails instead of reading as its page."""
        for s in self.scenes():
            if s["key"].startswith("state:") and s["act"]:
                with self.subTest(state=s["key"]):
                    self.assertTrue(s["shows"] or s["shows_text"])


# ══════════════════════════════════════════════════════════════════════════
# The guard bites: one old marker added to a copy fails, removed it passes
# ══════════════════════════════════════════════════════════════════════════

class SourceGuardBitesTests(SimpleTestCase):
    """B0's meta-test, the source half: in a temp copy of a template under
    budget, one neon glow on a card fails the comparison with that file,
    that line and that marker; the copy without it passes; a new template
    with one marker fails as a file absent from the budget."""

    REL = "templates/dashboard/ops.html"

    def setUp(self):
        import tempfile
        import shutil as _shutil
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="sv-guard-"))
        self.addCleanup(_shutil.rmtree, self.tmp, True)
        self.budget = load_budget()["source"]
        self.text = (ROOT / self.REL).read_text(encoding="utf-8")

    def compare(self, text, rel=None):
        copy = self.tmp / "copy.html"
        copy.write_text(text, encoding="utf-8")
        hits = file_hits(copy, rel or self.REL)
        others = {f: v for f, v in self.budget.items() if f == (rel or self.REL)}
        return compare_source(counts(hits), others, hits)

    def test_a_glow_added_to_a_card_fails_with_its_file_line_and_marker(self):
        clean_over, clean_under = self.compare(self.text)
        self.assertEqual((clean_over, clean_under), ([], []))
        lines = self.text.split("\n")
        at = next(i for i, line in enumerate(lines) if "{% block content %}" in line) + 1
        marked = lines[:at] + ['<div class="card" style="box-shadow: 0 0 18px rgba(0, 232, 104, .5)">census</div>'] + lines[at:]
        over, _under = self.compare("\n".join(marked))
        joined = "\n".join(over)
        self.assertTrue(over, "the census did not see the glow")
        self.assertIn("%s: glow" % self.REL, joined)
        self.assertIn("%s:%d glow [B11]" % (self.REL, at + 1), joined)
        self.assertIn("%s:%d eye_literal" % (self.REL, at + 1), joined)
        self.assertIn("%s:%d inline_visual" % (self.REL, at + 1), joined)
        # removed again: it passes
        self.assertEqual(self.compare("\n".join(lines)), ([], []))

    def test_a_non_token_colour_on_a_figure_in_a_sheet_fails(self):
        rel = "static/css/sv-kit.css"
        kit = (ROOT / rel).read_text(encoding="utf-8")
        self.assertEqual(self.compare(kit, rel), ([], []))
        marked = kit + "\n.sv-kpi-value { color: #3a6850; font-size: 9px; }\n"
        over, _u = self.compare(marked, rel)
        n = marked[:marked.index(".sv-kpi-value { color: #3a6850")].count("\n") + 1
        joined = "\n".join(over)
        self.assertIn("%s:%d old_literal" % (rel, n), joined)
        self.assertIn("%s:%d sub11" % (rel, n), joined)
        self.assertIn("a file absent from the budget must be at zero", joined)

    def test_a_new_template_starts_at_zero(self):
        over, _u = self.compare('<span class="badge badge-bullish">ARMED</span>', "templates/dashboard/new_page.html")
        self.assertEqual(len(over), 1)
        self.assertIn("templates/dashboard/new_page.html:1 badge_side", over[0])
        self.assertIn("a file absent from the budget must be at zero", over[0])


@_measured
class MeasuredGuardBitesTests(TestCase):
    """B0's meta-test, the measured half: the kit's page, rendered and laid
    out in Chromium as a temp copy, measured clean, is its own budget; a
    neon glow on a card and a colour off the tokens on a figure added to the
    copy fail the comparison, naming the page, the selector, the property
    and the value; the clean copy passes again."""

    MARKS = ('<style>.sv-meta-card { box-shadow: 0 0 18px rgba(0, 232, 104, .6); }</style>'
             '<div class="card sv-meta-card">A card that glows</div>'
             '<span class="sv-meta-fig mono" style="color: #123456">1,234.50</span>')

    @classmethod
    def setUpTestData(cls):
        import shutil as _shutil
        import tempfile
        user = get_user_model().objects.create_user("census_bites", password="x", is_staff=True)
        client = Client()
        client.force_login(user)
        page = client.get("/design/kit/", HTTP_HOST=HOST).content.decode("utf-8")
        page = re.sub(r"<script\b.*?</script>", "", page, flags=re.S)
        page = re.sub(r'<link\b[^>]*href="https?://[^>]*>', "", page)
        page = page.replace("/static/", "file://%s/static/" % settings.BASE_DIR)
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="sv-guard-measured-"))
        clean, marked = tmp / "clean.html", tmp / "marked.html"
        clean.write_text(page, encoding="utf-8")
        i = page.index('<div class="page-content')
        i = page.index(">", i) + 1
        marked.write_text(page[:i] + cls.MARKS + page[i:], encoding="utf-8")
        source = CENSUS_JS.read_text(encoding="utf-8")
        opts = census_opts()
        chrome = _Chrome(CHROME)
        try:
            sid = chrome.page(1440, 900, False)
            cls.got = {}
            for name, path in (("clean", clean), ("marked", marked), ("again", clean)):
                chrome.open(sid, path.as_uri())
                chrome.eval(sid, SETTLE % 100)
                cls.got[name] = chrome.eval(sid, source + "\n;census(%s)" % json.dumps(opts))
        finally:
            chrome.close()
            _shutil.rmtree(tmp, ignore_errors=True)

    def result(self, name):
        g = self.got[name]
        return {"/design/kit/": {"counts": g["counts"], "examples": g["examples"], "error": None}}

    def test_a_glow_and_an_off_token_figure_fail_and_their_removal_passes(self):
        budget = measured_budget_from(self.result("clean"), glyphs=False)
        self.assertEqual(compare_measured(self.result("clean"), budget, glyphs=False), ([], []))
        over, _under = compare_measured(self.result("marked"), budget, glyphs=False)
        joined = "\n".join(over)
        self.assertIn("/design/kit/: glow", joined)
        self.assertIn("x1  div.card.sv-meta-card  box-shadow: rgba(0, 232, 104, 0.6) 18px", joined)
        self.assertIn("/design/kit/: color_off 1, budget 0", joined)
        self.assertIn("x1  span.sv-meta-fig.mono  color: rgb(18, 52, 86)  '1,234.50'", joined)
        self.assertIn("/design/kit/: inline_visual", joined)
        # the copy without them passes again
        self.assertEqual(compare_measured(self.result("again"), budget, glyphs=False), ([], []))


@_measured
class MeasuredPipelineBitesTests(TestCase):
    """B0's meta-test through the run itself (the review of B0: the static
    copy above exercises the census and the comparison, not the Fetch
    serving, the held clock, the state check or why_unread): the kit's page
    served by the test client in a CensusRun scene, measured clean, then
    with a neon glow and an off-token figure planted in a temp copy of its
    template (a TEMPLATES dir put first), then clean again."""

    MARKS = ('<style>.sv-meta-card { box-shadow: 0 0 18px rgba(0, 232, 104, .6); }</style>'
             '<div class="card sv-meta-card">A card that glows</div>'
             '<span class="sv-meta-fig mono" style="color: #123456">1,234.50</span>')

    @classmethod
    def setUpTestData(cls):
        import shutil as _shutil
        import tempfile
        from django.test.utils import override_settings
        user = get_user_model().objects.create_user("census_pipe", password="x", is_staff=True)
        from tests.old_design.measure import tour_done
        tour_done(user)
        client = Client()
        client.force_login(user)
        scene = [s for s in build_scenes({}, 1, 2) if s["key"] == "/design/kit/"]
        tmp = pathlib.Path(tempfile.mkdtemp(prefix="sv-guard-pipeline-"))
        try:
            text = (ROOT / "templates/dashboard/design_kit.html").read_text(encoding="utf-8")
            at = text.index("{% block content %}") + len("{% block content %}")
            (tmp / "dashboard").mkdir()
            (tmp / "dashboard" / "design_kit.html").write_text(text[:at] + cls.MARKS + text[at:], encoding="utf-8")
            templates = [dict(settings.TEMPLATES[0], DIRS=[str(tmp)] + list(settings.TEMPLATES[0]["DIRS"]))]
            cls.got = {}
            for name in ("clean", "marked", "again"):
                if name == "marked":
                    with override_settings(TEMPLATES=templates):
                        run = CensusRun({"main": client}, scene, glyphs=False)
                        run.run()
                else:
                    run = CensusRun({"main": client}, scene, glyphs=False)
                    run.run()
                cls.got[name] = run.results
        finally:
            _shutil.rmtree(tmp, ignore_errors=True)

    def test_a_planted_look_fails_through_the_run_and_its_removal_passes(self):
        clean = self.got["clean"]
        self.assertIsNone(why_unread("/design/kit/", clean["/design/kit/"]), clean["/design/kit/"].get("error"))
        budget = measured_budget_from(clean, glyphs=False)
        self.assertEqual(compare_measured(clean, budget, glyphs=False), ([], []))
        marked = self.got["marked"]
        self.assertIsNone(why_unread("/design/kit/", marked["/design/kit/"]))
        over, _under = compare_measured(marked, budget, glyphs=False)
        joined = "\n".join(over)
        self.assertIn("/design/kit/: glow", joined)
        self.assertIn("div.card.sv-meta-card  box-shadow: rgba(0, 232, 104, 0.6) 18px", joined)
        self.assertIn("/design/kit/: color_off", joined)
        self.assertIn("span.sv-meta-fig.mono  color: rgb(18, 52, 86)  '1,234.50'", joined)
        self.assertEqual(compare_measured(self.got["again"], budget, glyphs=False), ([], []))
