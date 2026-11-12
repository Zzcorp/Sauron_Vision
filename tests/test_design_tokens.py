"""S1a of the UI plan: the foundation (2026-11-06).

The operator approved the preview of the new look on 2026-11-06: a blend
of Bloomberg's discipline and TradingView's calm, in Sauron's identity,
dark, desktop first. S1a lays its foundation under every page at once:

  * THE TOKENS (plan §3-§5, §8): one sheet, static/css/sv-tokens.css, holds
    the palette (opaque surfaces, ink by brightness, the Eye, market
    polarity, whose money, status), the faces, the type scale with its
    desktop tiers, spacing, shape and motion. Every text role meets 4.5:1
    on every surface it can sit on, computed here.
  * THE OLD NAMES RE-POINTED (§3.10): sauron.css's tokens (--bg-void,
    --text-muted, --accent-red, --font-mono…) now read the new ones, so
    every page changes at once. Each keeps its old value as the var()
    fallback, so a page that loads sauron.css without the token sheet
    (the lock screen, the investor panel: standalone until S2.7) keeps
    today's look. Light mode restates the old values: it computes the
    colours it computes today; only the faces change.
  * THE FACES (§4.1): Inter for words, JetBrains Mono for numbers, Orbitron
    for the wordmark only (a subset), from Google Fonts only.
  * THE RESET: a form control takes the page's face and colour.
  * A CALM BACKGROUND (§8): on a work page the grid, the globe-eye, the
    circuits, the particles, the caustics and the code-stream are not
    displayed; their animation loops do not start when their layer is not
    displayed or when the browser asks for reduced motion; and the
    particles no longer carry ticker labels and prices anywhere (fake
    prices have no place on a trading screen, even behind glass).
  * REAL IS THE ONLY SOLID RED: the world-marker family paints in --sv-real
    (#CC3A40, white on it 4.94:1; today's #E83030 gave 4.29), and nothing
    else paints a solid fill in it.

THE MAGIC KEPT (2026-11-12). The operator approved this look and asked to
keep Sauron's own theme, "the magic, the prestige". What that changed here,
each a look, updated deliberately, with its reason at the test:
  * the twelve neutrals of the palette take the Eye's hue at the very
    lightness they had (S1A_LADDER keeps the values they replace);
  * the shell loads three faces' links: Orbitron comes back for the frame's
    titles, without digits, and Rajdhani for the nav rows;
  * the embers come back on the pages that opt in, calm, from
    static/js/sv-embers.js, which the node class below runs as it ships;
    the caustics and the fake log lines are gone for good;
  * one more loop may run, under Ambience Magic: the Eye's breath; under
    reduced motion none runs at all.
What a look may never do stays as it was: 4.5:1, REAL the only solid red,
nothing under 11 px, light mode frozen. tests/test_magic_layer.py holds
the layer's own rules.

Display only. Nothing here reaches an order, a stop, a size, a gate, a
switch or a broker; no network, no model.

The measured classes render pages through the test client from synthetic
rows and lay them out in a headless Chromium with every network URL
blocked (tests/test_close_advice.py's _Chrome); they skip, not fail, where
the machine has none. The node class runs the ember script and base.html's
clock under node with a stubbed page; it skips where node is missing.

Run with:  python manage.py test tests.test_design_tokens
"""
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase

from tests.test_close_advice import CHROME, HOST, NODE, _Chrome, _quote
from tests.test_ui_s0_fixes import _get, _measure, _offline

ROOT = pathlib.Path(settings.BASE_DIR)
TOKENS = "static/css/sv-tokens.css"
KIT = "static/css/sv-kit.css"
SAURON = "static/css/sauron.css"
BASE = "templates/base.html"
EMBERS = "static/js/sv-embers.js"

#: §4.1, checked live: the words and numbers faces; Orbitron for the frame's
#: titles, as a subset of the capitals, the Latin-1 capitals and the title
#: punctuation, with no digit in it; Rajdhani 600 for the nav rows. A look,
#: updated (the magic kept, 2026-11-12): S1a's second link carried the
#: wordmark's own letters at 700 and nothing else. text= applies to a whole
#: request, so Orbitron and Rajdhani each have their link. Nothing else is
#: fetched for type.
FONT_LINKS = (
    "https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400..700"
    "&family=JetBrains+Mono:wght@400..700&display=swap",
    "https://fonts.googleapis.com/css2?family=Orbitron:wght@400..900"
    "&text=ABCDEFGHIJKLMNOPQRSTUVWXYZ%C3%80%C3%81%C3%82%C3%84%C3%87%C3%88%C3%89%C3%8A%C3%8B%C3%8E%C3%8F"
    "%C3%94%C3%96%C3%99%C3%9B%C3%9C%20%C2%B7%E2%80%94%E2%80%93-%26%27%E2%80%99()%2F%3A.%2C!%3F%23%2B%25"
    "&display=swap",
    "https://fonts.googleapis.com/css2?family=Rajdhani:wght@600&display=swap",
)

#: §3: the approved palette (the preview of 2026-11-06), its twelve neutrals
#: Eye-lit (the magic kept, 2026-11-12). A look, updated: each neutral keeps
#: the OKLab lightness S1a gave it and takes the Eye's hue family, so every
#: contrast below is computed on the new values and none moved by more than
#: 0.1 (the minimum is ink-3 on bg-4, 4.92:1; it was 4.93).
PALETTE = {
    "--sv-bg-0": "#040B07", "--sv-bg-1": "#07130C", "--sv-bg-2": "#0D1B14",
    "--sv-bg-3": "#14231B", "--sv-bg-4": "#1B2C23",
    "--sv-line-1": "#14261D", "--sv-line-2": "#1D3528", "--sv-line-3": "#2C4739",
    "--sv-ink-1": "#E6F1EA", "--sv-ink-2": "#ACC4B6", "--sv-ink-3": "#839B8D",
    "--sv-ink-4": "#55665D",
    "--sv-eye": "#00E868",
    "--sv-up": "#24B582", "--sv-down": "#FF6B6E",
    "--sv-up-fill": "#1FA374", "--sv-down-fill": "#E5484D",
    "--sv-real": "#CC3A40", "--sv-real-ink": "#FFFFFF", "--sv-demo": "#D6BC5E",
    "--sv-warn": "#F29B38", "--sv-ai": "#A48BFF",
    "--sv-cat-1": "#3987E5", "--sv-cat-2": "#D95926", "--sv-cat-3": "#9085E9",
    "--sv-cat-4": "#C98500", "--sv-cat-5": "#D55181",
}
#: S1a's neutrals, which the Eye-lit ones replace at the same lightness
#: (tests/test_magic_layer.py measures each against its own).
S1A_LADDER = {
    "--sv-bg-0": "#070A09", "--sv-bg-1": "#0C1110", "--sv-bg-2": "#121918",
    "--sv-bg-3": "#182120", "--sv-bg-4": "#1F2A28",
    "--sv-line-1": "#1B2422", "--sv-line-2": "#26322F", "--sv-line-3": "#36443F",
    "--sv-ink-1": "#E9EFED", "--sv-ink-2": "#B4C0BC", "--sv-ink-3": "#8A9894",
    "--sv-ink-4": "#59655F",
}
SURFACES = ("--sv-bg-0", "--sv-bg-1", "--sv-bg-2", "--sv-bg-3", "--sv-bg-4")
#: Everything that prints words or numbers on a surface (§3.2-§3.6). ink-4
#: is for disabled and placeholder text only, never information; --sv-real
#: is a fill, never text (white sits on it).
TEXT_ROLES = ("--sv-ink-1", "--sv-ink-2", "--sv-ink-3", "--sv-eye", "--sv-up",
              "--sv-down", "--sv-demo", "--sv-warn", "--sv-ai")

#: §4.3: the type scale at 1280-1679, 1680-2199, 2200 and up, and phones.
SCALE = {
    "--sv-fs-micro": (11, 11, 12, 11), "--sv-fs-small": (12, 12, 13, 12),
    "--sv-fs-base": (13, 14, 15, 14), "--sv-fs-lead": (15, 16, 17, 15),
    "--sv-fs-title": (18, 19, 20, 17), "--sv-fs-figure": (20, 22, 24, 20),
    "--sv-fs-hero": (28, 32, 36, 26),
}

#: §3.10: sauron.css's old names, what each now reads, and its old value
#: (the fallback, and what light mode restates where it did not set its own).
REPOINTED = {
    "--bg-void": ("--sv-bg-0", "#030806"),
    "--bg-primary": ("--sv-bg-0", "#060e0a"),
    "--bg-secondary": ("--sv-bg-1", "#081410"),
    "--bg-card": ("--sv-bg-1", "#0a1a14"),
    "--bg-card-hover": ("--sv-bg-3", "#0e2218"),
    "--border": ("--sv-line-2", "#133020"),
    "--border-glow": ("--sv-line-3", "#1a4030"),
    "--text-primary": ("--sv-ink-1", "#daf0e6"),
    "--text-secondary": ("--sv-ink-2", "#7aaa8a"),
    "--text-muted": ("--sv-ink-3", "#3a6850"),
    "--accent": ("--sv-eye", "#00e868"),
    "--accent-red": ("--sv-down", "#e83030"),
    "--accent-gold": ("--sv-demo", "#d8b020"),
    "--accent-blue": ("--sv-cat-1", "#30a0e8"),
    "--accent-purple": ("--sv-ai", "#8840d0"),
    "--danger": ("--sv-down", "#d03030"),
    "--success": ("--sv-up", "#00e868"),
    "--warning": ("--sv-warn", "#d89020"),
    "--font-display": ("--sv-font-sans", "'Orbitron', sans-serif"),
    "--font-heading": ("--sv-font-sans", "'Rajdhani', sans-serif"),
    "--font-mono": ("--sv-font-mono", "'Share Tech Mono', monospace"),
    "--font-body": ("--sv-font-sans", "'Rajdhani', sans-serif"),
}
#: Light mode as it computes today (the S0 tip, 328d924): its own values
#: where it set them, the dark root's where it did not. The faces are not
#: colours; they change in light mode too (plan §15, decision 3).
LIGHT_TODAY = {
    "--bg-void": "#f0f2f0", "--bg-primary": "#e8ece8",
    "--bg-secondary": "#dfe5df", "--bg-card": "#ffffff",
    "--bg-card-hover": "#f5f8f5", "--border": "#c0d0c0",
    "--border-glow": "#a0c0a0", "--text-primary": "#1a2a1a",
    "--text-secondary": "#4a6a4a", "--text-muted": "#8aaa8a",
    "--accent": "#00994d", "--accent-red": "#e83030",
    "--accent-gold": "#d8b020", "--accent-blue": "#30a0e8",
    "--accent-purple": "#8840d0", "--danger": "#d03030",
    "--success": "#00e868", "--warning": "#d89020",
}

#: The shorthand aliases (sauron.css, the 294 call sites' vocabulary) and
#: the overlay's surfaces, as light mode computes them on origin/main
#: ede54d0 (2026-11-07). They are custom properties computed on :root from
#: the dark root, and inherited as values: light mode never redefined them,
#: so it computed the dark root's colours for them. Frozen means those, not
#: the new dark tokens (review, 2026-11-07).
LIGHT_ALIASES_TODAY = {
    "--text": "#daf0e6", "--text2": "#7aaa8a", "--text3": "#3a6850",
    "--bg": "#060e0a", "--bg2": "#081410", "--bg3": "#0a1a14",
    "--bg-alt": "#081410", "--bg-elev": "#0e2218", "--bg-darker": "#030806",
    "--accent-green": "#00e868", "--down": "#d03030", "--purple": "#8840d0",
    "--gold": "#d8b020", "--blue": "#30a0e8",
}
LIGHT_OVERLAY_TODAY = {"--pop-bg": "#0a1a14", "--pop-bg-2": "#0e2218", "--pop-border": "#133020"}
#: The kit's own derived tokens: computed on :root from the dark palette,
#: so light mode must derive them again from its own.
DERIVED = ("--sv-up-wash", "--sv-down-wash", "--sv-paper", "--sv-danger", "--sv-grid")

#: The ambient layers of base.html. The first four are displayed on no work
#: page. The ember canvas is displayed on the pages that opt in, under
#: Ambience Magic, in the dark theme, and nowhere else (the magic kept,
#: 2026-11-12); the caustics canvas and the two code-stream paragraphs of
#: fake log lines are no longer in the page at all.
STILL_LAYERS = (".grid-bg", ".eye-glow-shadow", ".globe-eye-bg", ".globe-circuits-bg")
AMBIENT = STILL_LAYERS + ("#particles-canvas",)

#: The world-marker family (§3.5): the only selectors that may paint a
#: solid fill in --sv-real, the only solid red on the platform. The LIVE /
#: REAL labels of the close advice, the position card's fallback, the
#: accounts grid and the broker env chips joined on 2026-11-07 (review):
#: they read --accent-red, the loss coral since S1a, and plan §3.10 moves
#: the REAL family to --sv-real by name.
WORLD_MARKERS = (".sv-world--live", ".sv-armed-pill", ".tk-venue--live",
                 ".sv-row--live", ".sv-venue--live",
                 ".sv-adv-world.is-live", ".pos-pop-venue.is-live", ".hq-tag--live",
                 ".hq-brk--live", ".ib-env--live", ".bk-env--live", ".hq-acct--live")
#: The dialogs that take the trading PIN (real money) carry the REAL edge;
#: the edge sat on .sv-dialog--danger, every "danger" confirm, until the
#: review of 2026-11-07.
REAL_DIALOGS = (".sv-dialog:has(.sz-pin)", '.sv-dialog:has([data-role="secret-wrap"])')


# ── reading the sheets ───────────────────────────────────────────────────

def read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def rules(css):
    """Every rule as (prelude, body, at-rule context), nested @media and
    @supports flattened; @keyframes and @font-face come back whole."""
    css = strip_comments(css)
    out = []

    def walk(s, ctx):
        i = 0
        while True:
            j = s.find("{", i)
            if j < 0:
                return
            depth, k = 1, j + 1
            while k < len(s) and depth:
                if s[k] == "{":
                    depth += 1
                elif s[k] == "}":
                    depth -= 1
                k += 1
            prelude = s[i:j].split(";")[-1].strip()
            body = s[j + 1:k - 1]
            if re.match(r"@(media|supports|layer|container)\b", prelude):
                walk(body, ctx + (prelude,))
            else:
                out.append((prelude, body, ctx))
            i = k

    walk(css, ())
    return out


def decls(body):
    """[(property, value)] of a declaration block, split outside brackets."""
    out, depth, cur = [], 0, []
    for ch in body:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == ";" and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    pairs = []
    for d in out:
        if ":" in d:
            p, v = d.split(":", 1)
            if p.strip():
                pairs.append((p.strip().lower(), v.strip()))
    return pairs


def block(css, selector, ctx=(), nth=0):
    """The declarations of the nth rule whose prelude is exactly
    `selector` in the at-rule context `ctx`."""
    found = [b for p, b, c in rules(css)
             if p == selector and c == tuple(ctx)]
    if len(found) <= nth:
        raise AssertionError("no rule %r in %r" % (selector, ctx))
    return dict(decls(found[nth]))


def hex_rgb(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def luminance(h):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = hex_rgb(h)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a, b):
    x, y = luminance(a), luminance(b)
    return (max(x, y) + 0.05) / (min(x, y) + 0.05)


def oklab(h):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in hex_rgb(h))
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
            1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
            0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)


def delta_e(a, b):
    return 100 * sum((x - y) ** 2 for x, y in zip(oklab(a), oklab(b))) ** 0.5


def px(value):
    m = re.fullmatch(r"\s*([0-9.]+)px\s*", value)
    return float(m.group(1)) if m else None


# ══════════════════════════════════════════════════════════════════════════
# The palette
# ══════════════════════════════════════════════════════════════════════════

class PaletteTests(SimpleTestCase):

    def setUp(self):
        self.root = block(read(TOKENS), ":root")

    def test_the_palette_is_the_approved_one(self):
        for name, hexv in PALETTE.items():
            with self.subTest(token=name):
                self.assertEqual(self.root.get(name, "").upper(), hexv)

    def test_every_text_role_meets_4_5_to_1_on_every_surface(self):
        low = []
        for role in TEXT_ROLES:
            for surface in SURFACES:
                r = contrast(PALETTE[role], PALETTE[surface])
                if r < 4.5:
                    low.append("%s on %s: %.2f" % (role, surface, r))
        self.assertEqual(low, [])

    def test_white_on_real_meets_4_5_to_1_and_today_s_red_did_not(self):
        self.assertGreaterEqual(contrast(PALETTE["--sv-real-ink"],
                                         PALETTE["--sv-real"]), 4.9)
        self.assertLess(contrast("#FFFFFF", "#E83030"), 4.5)

    def test_what_is_not_a_text_role_says_so(self):
        """ink-4 (disabled, placeholder) and the REAL red are under 4.5:1 on
        the cards: neither may carry information as text."""
        self.assertLess(contrast(PALETTE["--sv-ink-4"], PALETTE["--sv-bg-1"]), 4.5)
        self.assertLess(contrast(PALETTE["--sv-real"], PALETTE["--sv-bg-1"]), 4.5)

    def test_labels_are_readable_now(self):
        """Today's labels (--text-muted, #3a6850) were 3.1:1; ink-3 is 6.3."""
        self.assertLess(contrast("#3a6850", "#060e0a"), 3.1)
        self.assertGreater(contrast(PALETTE["--sv-ink-3"], PALETTE["--sv-bg-1"]), 6.3)

    def test_up_is_not_the_eye(self):
        """The Eye's green marks what is live and selected; gains move to
        jade, far enough from it to read apart (OKLab ΔE x100 15.9)."""
        self.assertGreater(delta_e(PALETTE["--sv-up"], PALETTE["--sv-eye"]), 15)

    def test_the_derived_tokens(self):
        r = self.root
        self.assertEqual(r["--sv-paper"], "var(--sv-ink-3)")
        self.assertEqual(r["--sv-danger"], "var(--sv-down)")
        self.assertIn("var(--sv-up) 14%", r["--sv-up-wash"])
        self.assertIn("var(--sv-down) 14%", r["--sv-down-wash"])

    def test_surfaces_and_ink_are_opaque(self):
        for name in PALETTE:
            with self.subTest(token=name):
                self.assertRegex(self.root[name], r"^#[0-9A-Fa-f]{6}$")


# ══════════════════════════════════════════════════════════════════════════
# The faces and the scale
# ══════════════════════════════════════════════════════════════════════════

class FaceTests(SimpleTestCase):

    def test_the_font_links_are_exactly_section_4_1(self):
        base = read(BASE)
        links = re.findall(r'href="(https://fonts\.googleapis\.com/[^"]+)"', base)
        self.assertEqual([l.replace("&amp;", "&") for l in links], list(FONT_LINKS))
        # Updated deliberately (the magic kept, 2026-11-12): Rajdhani is
        # back in the shell, as the 600 link alone (the nav rows' face).
        # Share Tech Mono and the full Orbitron, digits included, stay out.
        self.assertEqual(base.count("Rajdhani"), 1)
        self.assertIn("family=Rajdhani:wght@600&amp;display=swap", base)
        for gone in ("Share+Tech+Mono", "Orbitron:wght@400;500;600;700;800;900",
                     "Orbitron:wght@700&amp;text=SAURON"):
            self.assertNotIn(gone, base)

    def test_orbitron_is_loaded_without_digits(self):
        """A digit must never be drawn in Orbitron: its 5, 6, 8 and 9 are
        the least distinct of the four faces. The link asks for a subset by
        its text= and that text holds no digit, so the browser draws a
        title's digits in the next face of the stack, JetBrains Mono."""
        import urllib.parse
        link = [l for l in FONT_LINKS if "Orbitron" in l]
        self.assertEqual(len(link), 1)
        query = urllib.parse.parse_qs(urllib.parse.urlparse(link[0]).query)
        self.assertEqual(query["family"], ["Orbitron:wght@400..900"])
        text = query["text"][0]
        self.assertEqual(re.findall(r"\d", text), [])
        for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ ·—#":
            self.assertIn(ch, text)
        root = block(read(TOKENS), ":root")
        self.assertEqual(root["--sv-font-display"].split(",")[1].strip(), '"JetBrains Mono"')

    def test_no_other_font_host_in_the_shell(self):
        """base.html and every sheet it links: type comes from Google Fonts
        only, through the three links above (no @import, no @font-face with a
        remote source, no other host)."""
        base = read(BASE)
        sheets = re.findall(r"""\{% static 'css/([\w.-]+\.css)' %\}""", base)
        self.assertIn("sv-tokens.css", sheets)
        for rel in [BASE] + ["static/css/" + s for s in sheets]:
            text = read(rel)
            with self.subTest(file=rel):
                self.assertNotRegex(text, r"@import")
                self.assertNotRegex(text, r"@font-face\s*\{[^}]*url\(\s*['\"]?https?:")
                for host in ("fonts.bunny.net", "use.typekit.net", "fonts.cdnfonts",
                             "fonts.gstatic.com", "fontawesome", "rsms.me"):
                    self.assertNotIn(host, text)

    def test_no_page_under_the_shell_names_a_face_or_loads_one_of_its_own(self):
        """Updated deliberately (the magic kept, 2026-11-12). S1a's shell
        loaded neither Rajdhani nor the full Orbitron, so a page that named
        one loaded it itself (/passation/). The shell loads both again:
        named literally, the letter's sentences would now be drawn in the
        nav rows' Rajdhani, and a page's own full Orbitron would draw
        digits in it on that page. So no page under base.html names
        Orbitron, Rajdhani or Share Tech Mono in its own styles (a var()
        fallback aside) or links a face of its own: the tokens carry them
        (tests/test_magic_layer.py reads which selectors may)."""
        offenders, read_pages = [], 0
        for path in sorted((ROOT / "templates").rglob("*.html")):
            text = path.read_text(encoding="utf-8")
            if not re.search(r'\{% extends (base_template\|default:)?"base\.html" %\}', text):
                continue
            read_pages += 1
            if "fonts.googleapis.com" in text:
                offenders.append("%s links a face of its own" % path.relative_to(ROOT))
            for face in ("Orbitron", "Rajdhani", "Share Tech Mono"):
                if re.search(r"""font-family:\s*['"]%s['"]""" % face, text):
                    offenders.append("%s names %s" % (path.relative_to(ROOT), face))
        self.assertGreater(read_pages, 80)
        self.assertEqual(offenders, [])

    def test_the_faces_are_tokens_with_their_fallbacks(self):
        root = block(read(TOKENS), ":root")
        self.assertEqual(root["--sv-font-sans"],
                         '"Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif')
        self.assertEqual(root["--sv-font-mono"],
                         '"JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace')
        # The wordmark's face is the display face now (2026-11-12): one
        # Orbitron for the frame, its digits falling to JetBrains Mono.
        self.assertEqual(root["--sv-font-brand"], "var(--sv-font-display)")
        self.assertTrue(root["--sv-font-display"].startswith('"Orbitron", "JetBrains Mono"'))

    def test_the_old_names_read_the_new_tokens(self):
        root = block(read(SAURON), ":root")
        for old, (new, was) in REPOINTED.items():
            with self.subTest(token=old):
                self.assertEqual(root.get(old), "var(%s, %s)" % (new, was))

    def test_the_wordmark_keeps_orbitron(self):
        """The brand rule names --sv-font-brand, which reads the display
        face: Orbitron, on the wordmark and the frame's titles (the magic
        kept, 2026-11-12; S1a's subset carried SAURON VISION alone)."""
        brand = block(read(SAURON), ".sidebar-brand h1")
        self.assertTrue(brand["font-family"].startswith("var(--sv-font-brand"),
                        brand["font-family"])

    def test_chart_js_takes_the_number_face(self):
        assets = read("templates/_chart_assets.html")
        self.assertIn('token("--sv-font-mono", token("--font-mono", "\'Share Tech Mono\', monospace"))',
                      assets)
        self.assertNotIn('font.family = "\'Share Tech Mono\', monospace"', assets)

    def test_the_scale_and_its_desktop_tiers(self):
        css = read(TOKENS)
        tiers = (block(css, ":root"),
                 block(css, ":root", ("@media (min-width: 1680px)",)),
                 block(css, ":root", ("@media (min-width: 2200px)",)),
                 block(css, ":root", ("@media (max-width: 768px)",)))
        for name, sizes in SCALE.items():
            for i, (tier, want) in enumerate(zip(tiers, sizes)):
                with self.subTest(token=name, tier=("1280", "1680", "2200", "phone")[i]):
                    self.assertEqual(px(tier.get(name, "")), want)

    def test_no_font_size_under_11px_in_the_tokens_or_the_kit(self):
        small = []
        for rel in (TOKENS, KIT):
            for prelude, body, ctx in rules(read(rel)):
                for prop, value in decls(body):
                    sizes = []
                    if prop == "font-size" or prop.startswith("--sv-fs-"):
                        sizes = [value]
                    elif prop == "font":
                        sizes = re.findall(r"(?<![\w.-])([0-9.]+px)", value.split("/")[0])
                    for s in sizes:
                        v = px(s)
                        if v is not None and v < 11:
                            small.append("%s %s { %s: %s }" % (rel, prelude, prop, value))
                        elif v is None and re.search(r"\d(em|rem|%)", s):
                            m = re.match(r"([0-9.]+)", s)
                            if m and float(m.group(1)) < 1 and "em" in s:
                                small.append("%s %s { %s: %s } (relative)"
                                             % (rel, prelude, prop, value))
        self.assertEqual(small, [])


class ResetAndBodyTests(SimpleTestCase):

    def test_the_input_reset_exists(self):
        css = strip_comments(read(SAURON))
        self.assertRegex(css, r"button,\s*input,\s*select,\s*textarea\s*\{\s*"
                              r"font:\s*inherit;\s*color:\s*inherit;\s*\}")

    def test_the_body_is_inter_13_on_1_45(self):
        body = block(read(SAURON), "body")
        self.assertEqual(body["font-family"], "var(--font-body)")
        self.assertEqual(body["font-size"], "var(--sv-fs-base, 15px)")
        self.assertEqual(body["font-weight"], "var(--sv-body-weight, 500)")
        self.assertEqual(body["line-height"], "var(--sv-lh-text, 1.6)")
        root = block(read(TOKENS), ":root")
        self.assertEqual(root["--sv-body-weight"], "400")
        self.assertEqual(root["--sv-lh-text"], "1.45")


class LightModeFrozenTests(SimpleTestCase):

    def test_light_mode_restates_every_re_pointed_token(self):
        """Every old name S1a re-points keeps, under body.light-mode, the
        colour light mode computes today."""
        light = block(read(SAURON), "body.light-mode")
        for name, want in LIGHT_TODAY.items():
            with self.subTest(token=name):
                self.assertEqual(light.get(name, "").lower(), want)
        colours = {k for k, (new, _) in REPOINTED.items()
                   if not new.startswith("--sv-font")}
        self.assertEqual(colours, set(LIGHT_TODAY))

    def test_light_mode_maps_every_colour_token_of_the_kit(self):
        """A kit component under light mode draws from today's light palette,
        not from the dark one."""
        light = block(read(TOKENS), "body.light-mode")
        for name in PALETTE:
            with self.subTest(token=name):
                self.assertIn(name, light)
        self.assertEqual(light["--sv-up"].lower(), "#00994d")   # .up in light, today
        self.assertEqual(light["--sv-down"].lower(), "#e83030")
        self.assertEqual(light["--sv-real"].lower(), "#e83030")
        self.assertEqual(light["--sv-ink-1"].lower(), "#1a2a1a")
        self.assertEqual(light["--sv-bg-1"].lower(), "#ffffff")

    def test_light_mode_derives_the_kit_s_washes_from_its_own_palette(self):
        """--sv-up-wash, --sv-paper and the rest are computed where they are
        declared: on :root, from the dark palette. Light mode declares them
        again, the same expressions, so they read its own colours (a light
        .sv-world--paper was the dark ink-3; review, 2026-11-07)."""
        root, light = block(read(TOKENS), ":root"), block(read(TOKENS), "body.light-mode")
        for name in DERIVED:
            with self.subTest(token=name):
                self.assertEqual(light.get(name), root[name])

    def test_light_mode_restates_the_shorthand_aliases_and_the_overlay(self):
        """The aliases (--text, --down, --bg3…) and the overlay's surfaces
        (--pop-bg…) are computed on :root and inherited as values: light
        mode computed the old dark root's colours for them, and S1a's dark
        root would have changed them (--down #d03030 to the coral: 5.06:1 on
        a white card to 2.77). Restated at today's values (2026-11-07)."""
        light = {}
        for prelude, body, ctx in rules(read(SAURON)):
            if prelude == "body.light-mode" and not ctx:
                light.update(decls(body))
        for name, want in LIGHT_ALIASES_TODAY.items():
            with self.subTest(token=name):
                self.assertEqual(light.get(name, "").lower(), want)
        kit = block(read(KIT), "body.light-mode")
        for name, want in LIGHT_OVERLAY_TODAY.items():
            with self.subTest(token=name):
                self.assertEqual(kit.get(name, "").lower(), want)

    def test_the_kit_s_light_exceptions_are_scoped_to_the_dark_theme(self):
        """Rules that would recolour light mode wear the dark scope: the
        unknown dash at full strength, the LIVE label as a chip, the band's
        counts in ink, a bullish chip on its wash (2026-11-07)."""
        kit = strip_comments(read(KIT))
        for sel in (".sv-unknown", ".badge-bullish"):
            with self.subTest(selector=sel):
                self.assertRegex(kit, r"body:not\(\.light-mode\)\)?\s+%s\s*\{" % re.escape(sel))
                self.assertNotRegex(kit, r"(^|\}|,)\s*%s\s*\{" % re.escape(sel))
        css = read(SAURON)
        self.assertEqual(block(css, ".badge-bullish")["background"], "var(--accent-dim)")
        self.assertEqual(block(css, ":where(body.light-mode) .ip-cat .ip-count")["color"],
                         "var(--accent)")
        self.assertEqual(block(read(KIT), ":where(body.light-mode) .sv-venue--live"),
                         {"color": "var(--accent-red)", "background": "transparent"})


class RealIsTheOnlySolidRedTests(SimpleTestCase):

    def test_sv_real_paints_only_the_world_markers(self):
        offenders = []
        for rel in (TOKENS, KIT, SAURON):
            for prelude, body, ctx in rules(read(rel)):
                if prelude.startswith("@") or prelude.startswith(":root") \
                        or prelude.startswith("body.light-mode"):
                    continue
                for prop, value in decls(body):
                    if not re.search(r"--sv-real(?![\w-])", value):
                        continue
                    if prop not in ("background", "background-color", "background-image",
                                    "box-shadow", "border-top", "border-top-color",
                                    "border-color", "border", "outline-color",
                                    "border-left", "border-left-color"):
                        continue
                    sels = [s.strip() for s in prelude.split(",")]
                    for s in sels:
                        # Updated deliberately (2026-11-07, review): the REAL
                        # edge's exception is the PIN-taking dialogs, no
                        # longer every .sv-dialog--danger (a delete, a pause,
                        # a paper close); the guard is the same: nothing
                        # outside the REAL family paints --sv-real.
                        if not any(m in s for m in WORLD_MARKERS + REAL_DIALOGS):
                            offenders.append("%s: %s { %s: %s }" % (rel, s, prop, value))
        self.assertEqual(offenders, [])

    def test_the_world_family_reads_sv_real(self):
        """The chip, the armed pill, the ticket's chip and the LIVE label
        fill in --sv-real with --sv-real-ink on it; the row's edge is
        --sv-real. The fallbacks are the old look, for a page without the
        token sheet."""
        css = read(SAURON)
        for sel in (".sv-world--live", ".sv-armed-pill", ".tk-venue--live",
                    ".sv-venue--live"):
            with self.subTest(selector=sel):
                rule = block(css, sel)
                self.assertTrue(rule["background"].startswith("var(--sv-real,"), rule)
                self.assertTrue(rule["color"].startswith("var(--sv-real-ink,"), rule)
                self.assertNotIn("0 0 ", rule.get("box-shadow", "none"))   # no glow
        edge = [b for p, b, c in rules(css) if p.startswith("tr.sv-row--live > td:first-child")]
        self.assertIn("inset 3px 0 0 var(--sv-real, var(--accent-red))", edge[0])


class PolarityTests(SimpleTestCase):
    """Gains and losses in jade and coral; the Eye keeps live and selected."""

    def test_up_and_down_read_the_polarity_tokens(self):
        css = read(SAURON)
        self.assertEqual(block(css, ".up")["color"], "var(--sv-up, var(--accent))")
        self.assertEqual(block(css, ".down")["color"], "var(--sv-down, var(--accent-red))")
        self.assertEqual(block(css, ".sign-up")["color"], "var(--sv-up, var(--accent))")
        self.assertEqual(block(css, ".sign-down")["color"], "var(--sv-down, var(--accent-red))")
        # sign_class's third output is a number nobody measured: the
        # unknown's colour, ink-3, as its em-dash.
        self.assertEqual(block(css, ".sign-flat")["color"], "var(--text-muted)")

    def test_no_rule_paints_a_gain_in_the_eye(self):
        """A selector naming up, bullish, long or BUY never takes --accent
        for its text colour in sauron.css any more."""
        offenders = []
        for prelude, body, ctx in rules(read(SAURON)):
            for sel in prelude.split(","):
                if not re.search(r"\.(up|bullish|tk-long|BUY|ipr-side--long|ipr-side--bullish)\b(?![\w-])", sel):
                    continue
                for prop, value in decls(body):
                    if prop == "color" and re.fullmatch(r"var\(--accent\)", value):
                        offenders.append("%s { color: %s }" % (sel.strip(), value))
        self.assertEqual(offenders, [])

    def test_no_shell_sheet_paints_a_gain_in_the_eye(self):
        """The same rule across every sheet base.html links and the close
        advice's own (review, 2026-11-07: the Horde's strip printed +5.78R
        in the Eye beside the band's jade). A sheet the kit does not own
        keeps its rule; the kit names that selector, in the dark theme, and
        paints it jade."""
        base = read(BASE)
        sheets = ["static/css/" + s for s in
                  re.findall(r"""\{% static 'css/([\w.-]+\.css)' %\}""", base)
                  if s not in ("sv-tokens.css", "sv-kit.css", "sauron.css")]
        sheets.append("static/css/sv-close-advice.css")
        gain = re.compile(r"[.-](up|bullish|long|BUY)(?![\w-])")
        kit = {}
        for prelude, body, ctx in rules(read(KIT)):
            for sel in prelude.split(","):
                for prop, value in decls(body):
                    if prop == "color":
                        kit[sel.strip()] = value
        offenders = []
        for rel in sheets:
            for prelude, body, ctx in rules(read(rel)):
                if prelude.startswith("@") or "light-mode" in prelude:
                    continue
                for sel in prelude.split(","):
                    sel = sel.strip()
                    if not gain.search(sel.split(":")[0]):
                        continue
                    for prop, value in decls(body):
                        if prop == "color" and value == "var(--accent)":
                            fixed = "var(--sv-up)" in (kit.get("body:not(.light-mode) " + sel),
                                                       kit.get(":where(body:not(.light-mode)) " + sel))
                            if not fixed:
                                offenders.append("%s: %s { color: %s }" % (rel, sel, value))
        self.assertEqual(offenders, [])


class RailFiltersOnTheKitTests(SimpleTestCase):
    """The signal rail's filters, LEFT THE RAIL and its click-to-open cards
    (railfilters, #90) on the kit, from the merge of origin/main into this
    branch (2026-11-07): sv-rail.css loads before the kit, so every size it
    sets under 11 px meets the micro size at its own selector here; a gain
    is jade, never the Eye; a pressed filter is selected (bg-3, ink-1, the
    Eye's edge); and a card pinned open keeps that edge under the kit's
    popover border, its sticky head and foot on the card's own surface."""

    RAIL = "static/css/sv-rail.css"
    DARK = "body:not(.light-mode) "
    WHERE = ":where(body:not(.light-mode)) "

    @staticmethod
    def value(css, selector, prop):
        """What the last top-level rule naming `selector` (alone or in a
        list) gives `prop`: the cascade's answer for rules of one weight."""
        got = None
        for prelude, body, ctx in rules(css):
            if ctx or selector not in [s.strip() for s in prelude.split(",")]:
                continue
            for p, v in decls(body):
                if p == prop:
                    got = v
        return got

    def test_the_kit_loads_after_the_rail_sheet_and_before_the_phone_tier(self):
        base = read(BASE)
        self.assertLess(base.index("'css/sv-rail.css'"), base.index("'css/sv-kit.css'"))
        self.assertLess(base.index("'css/sv-kit.css'"), base.index("'css/sv-responsive.css'"))

    def test_every_rail_size_under_11px_meets_the_micro_size(self):
        small = set()
        for prelude, body, ctx in rules(read(self.RAIL)):
            for prop, value in decls(body):
                v = px(value) if prop == "font-size" else None
                if v is not None and v < 11:
                    small.update(s.strip() for s in prelude.split(","))
        floored = set()
        for prelude, body, ctx in rules(read(KIT)):
            if not ctx and ("font-size", "var(--sv-fs-micro)") in decls(body):
                floored.update(s.strip() for s in prelude.split(","))
        self.assertGreater(len(small), 20)
        self.assertEqual(sorted(small - floored), [])

    def test_a_gain_on_the_rail_is_jade_never_the_eye(self):
        css = read(KIT)
        for sel, want in ((".sr-gone-l1 .sr-badge-bullish", "var(--sv-up)"),
                          (".sr-gone-tag-target_reached", "var(--sv-up)"),
                          (".sr-gone-tag-closed_target", "var(--sv-up)"),
                          (".sr-gone-l1 .sr-badge-bearish", "var(--sv-down)"),
                          (".sr-gone-tag-stop_crossed", "var(--sv-down)")):
            with self.subTest(selector=sel):
                self.assertEqual(self.value(css, self.WHERE + sel, "color"), want)

    def test_a_pressed_filter_is_selected_with_the_eye_s_edge(self):
        css = read(KIT)
        for sel in ('button.rf-chip[aria-pressed="true"]', '.rf-opt[aria-pressed="true"]'):
            with self.subTest(selector=sel):
                self.assertEqual(self.value(css, self.WHERE + sel, "border-color"), "var(--sv-eye)")
                self.assertEqual(self.value(css, self.WHERE + sel, "background"), "var(--sv-bg-3)")
                self.assertEqual(self.value(css, self.WHERE + sel, "color"), "var(--sv-ink-1)")

    def test_a_pinned_card_keeps_the_eye_s_edge_and_its_ends_their_surface(self):
        css = read(KIT)
        # The popover border it must outweigh, and the edge that does.
        self.assertEqual(self.value(css, self.DARK + ".sr-popup", "border"),
                         "1px solid var(--sv-line-2)")
        self.assertEqual(self.value(css, self.DARK + ".sr-popup.sv-pinned", "border-color"),
                         "var(--sv-eye)")
        for sel in (".sr-popup .sr-pop-head", ".sr-pop-foot", ".ip-dropdown .ip-dd-head"):
            with self.subTest(selector=sel):
                self.assertEqual(self.value(css, self.DARK + sel, "background"), "var(--sv-bg-2)")

    def test_the_stage_chips_take_no_meaning_the_palette_forbids(self):
        """The rail's stage chip (2026-11-07, review of the merge): its tone
        "bearish" is TRADEABLE, "real money can move on this"
        (dashboard/signal_surface.py), drawn in the loss coral; "high" is
        PAUSED or REDUCED, drawn as DEMO's gold outline. TRADEABLE is the
        strong neutral outline (ink-1 on a line-3 border: brightness, not a
        hue); PAUSED and REDUCED the warning amber (plan §3.9)."""
        css = read(KIT)
        self.assertEqual(self.value(css, self.WHERE + ".sr-stage-bearish", "color"), "var(--sv-ink-1)")
        self.assertEqual(self.value(css, self.WHERE + ".sr-stage-bearish", "border-color"),
                         "var(--sv-line-3)")
        self.assertEqual(self.value(css, self.WHERE + ".sr-stage-high", "color"), "var(--sv-warn)")
        self.assertIn("var(--sv-warn)", self.value(css, self.WHERE + ".sr-stage-high", "border-color"))
        for sel in (".sr-stage-bearish", ".sr-stage-high"):
            for prelude, body, ctx in rules(css):
                if any(s.strip().endswith(sel) for s in prelude.split(",")):
                    with self.subTest(selector=prelude):
                        for bad in ("--sv-down", "--accent-red", "--accent-gold", "--sv-demo"):
                            self.assertNotIn(bad, body)


class MarketShutOnTheKitTests(SimpleTestCase):
    """MARKET SHUT on the kit (main's #99, #100 and #101, merged into this
    branch on 2026-11-12). A signal whose market is shut says so on its
    rail card, on its headband row and on /signals/; a SHUT chip shows or
    hides those cards; with the optional hold on (the switch
    signal_market_hold) they wait in a MARKET SHUT section. Main drew them
    on the old look: sizes from 7.5 to 10 px, a colour that is DEMO's gold
    in the dark theme since S1a (--accent-gold-ink reads --accent-gold
    there), a line the hour is clipped by, and a see-through ground under
    the section. On the kit: every size meets the
    micro size; what says MARKET SHUT is the warning amber, an outline and
    never a fill (REAL is the only solid red), never the Eye's green (a
    shut market is not live), never DEMO's gold; the hour a market opens is
    a figure, in the number face, unlit and never cut; the section sits on
    an opaque ground. The SHUT chip is a filter chip like the others, on
    the kit already. Light mode keeps main's own colours (frozen)."""

    RAIL = "static/css/sv-rail.css"
    WHERE = ":where(body:not(.light-mode)) "
    DARK = "body:not(.light-mode) "
    HALF = "color-mix(in srgb, var(--sv-warn) 50%, transparent)"
    #: Main's sizes under 11 px, each at its own selector.
    SMALL = (".sr-shut", ".sr-shut-tag", ".ipr-shut", ".sig-shut-opens", ".sig-hold", ".sr-wait-rule")
    #: What says MARKET SHUT.
    SAYS = (".sr-shut", ".sr-shut-tag", ".sr-pop-fact-shut", ".ipr-shut",
            ".sr-gone-tag-market_shut", ".sr-gone-tag-market_settling", ".sig-shut")
    #: The classes main added: a kit rule that names one is read below.
    MARK = re.compile(r"\.(sr-shut(-tag|-opens|-sec)?|sr-pop-fact-shut|ipr-shut|sig-shut(-opens)?|sig-hold"
                      r"|sr-wait-(row|rule)|rf-shut|sr-gone-tag-market_(shut|settling))(?![\w-])")
    #: What a rule may set on them in both themes: a size, a face, a shape.
    BOTH_THEMES = ("font-size", "font-family", "font-weight", "font-variant-numeric", "letter-spacing",
                   "border-radius", "white-space", "flex-wrap", "row-gap")

    value = staticmethod(RailFiltersOnTheKitTests.value)

    def named(self):
        """(selector, declarations) of every kit rule naming one of main's
        MARKET SHUT classes. The section's ▶ TICKET is a money control,
        which wears its signal's side: tests/test_money_controls_look.py
        and tests/test_magic_layer.py hold it, not this class."""
        out = []
        for prelude, body, ctx in rules(read(KIT)):
            for sel in prelude.split(","):
                if self.MARK.search(sel) and "sr-gone-btn" not in sel:
                    out.append((sel.strip(), decls(body)))
        return out

    def test_main_s_sizes_under_11px_meet_the_micro_size(self):
        rail = read(self.RAIL)
        floored = set()
        for prelude, body, ctx in rules(read(KIT)):
            if not ctx and ("font-size", "var(--sv-fs-micro)") in decls(body):
                floored.update(s.strip() for s in prelude.split(","))
        for sel in self.SMALL:
            with self.subTest(selector=sel):
                self.assertLess(px(block(rail, sel)["font-size"]), 11)      # main's own, on the old look
                self.assertIn(sel, floored)

    def test_what_says_market_shut_is_the_warning_amber(self):
        css = read(KIT)
        for sel in self.SAYS:
            with self.subTest(selector=sel):
                self.assertEqual(self.value(css, self.WHERE + sel, "color"), "var(--sv-warn)")
        for sel in (".sr-shut-tag", ".sr-gone-tag-market_shut", ".sr-gone-tag-market_settling"):
            with self.subTest(outline=sel):
                self.assertEqual(self.value(css, self.WHERE + sel, "border-color"), self.HALF)
        # /signals/' badge is main's .badge-high, DEMO's gold on its wash:
        # the amber outline here, its ring drawn inside so no badge grows.
        self.assertEqual(block(css, self.WHERE + ".sig-shut"),
                         {"color": "var(--sv-warn)", "background": "transparent",
                          "box-shadow": "inset 0 0 0 1px " + self.HALF})
        # Main's own colour: --accent-gold-ink, which the dark theme reads
        # from --accent-gold, DEMO's gold since S1a. Gold says DEMO.
        self.assertEqual(block(read(self.RAIL), ".sr-shut")["color"], "var(--accent-gold-ink, #e8a33d)")
        sauron = read(SAURON)
        self.assertIn("--accent-gold-ink: var(--accent-gold);", sauron)
        self.assertIn("--accent-gold: var(--sv-demo, #d8b020);", sauron)

    def test_no_rule_gives_it_a_fill_a_red_the_eye_s_green_or_gold(self):
        named = self.named()
        self.assertGreater(len(named), 12)
        for sel, pairs in named:
            for prop, value in pairs:
                with self.subTest(selector=sel, prop=prop):
                    for bad in ("--sv-real", "--sv-down", "--sv-danger", "--accent", "--sv-eye", "--sv-up",
                                "--sv-demo", "#", "rgb(", "rgba(", "gradient"):
                        self.assertNotIn(bad, value)
                    if prop in ("background", "background-color", "background-image"):
                        self.assertIn(value, ("transparent", "var(--sv-bg-0)"))
        # The chip takes no rule of its own: it is the kit's filter chip.
        self.assertEqual([sel for sel, _ in named if "rf-shut" in sel], [])

    def test_the_hour_is_a_figure_in_the_number_face_and_nothing_lights_it(self):
        css = read(KIT)
        for sel in (".sr-shut-opens", ".sig-shut-opens"):
            with self.subTest(selector=sel):
                self.assertEqual(self.value(css, sel, "font-family"), "var(--sv-font-mono)")
                self.assertEqual(self.value(css, sel, "font-variant-numeric"), "tabular-nums")
                self.assertEqual(self.value(css, sel, "letter-spacing"), "0")
        # On a card the hour is never cut: it takes the line under the
        # badge, whole, when the two cannot sit side by side.
        self.assertEqual(self.value(css, ".sr-shut", "flex-wrap"), "wrap")
        self.assertEqual(self.value(css, ".sr-shut-opens", "white-space"), "nowrap")
        for sel, pairs in self.named():
            for prop, value in pairs:
                with self.subTest(selector=sel, prop=prop):
                    self.assertNotIn(prop, ("text-shadow", "filter", "animation", "animation-name",
                                            "background-image"))
                    self.assertNotIn("--sv-glow", value)
                    self.assertNotIn("data-sv-ambience", sel)       # the magic adds nothing to it
                    if prop == "box-shadow":                        # a ring with no blur is no light
                        self.assertEqual(value, "inset 0 0 0 1px " + self.HALF)

    def test_the_section_sits_on_an_opaque_ground(self):
        css = read(KIT)
        self.assertEqual(self.value(css, self.DARK + ".sr-shut-sec", "background"), "var(--sv-bg-0)")
        self.assertEqual(self.value(css, self.DARK + ".sr-wait-row", "border-top-color"), "var(--sv-line-1)")
        # Main's own ground is see-through: its counts would sit on glass.
        self.assertEqual(block(read(self.RAIL), ".sr-shut-sec")["background"], "rgba(0, 0, 0, 0.18)")

    def test_light_mode_keeps_main_s_colours(self):
        """Every colour the kit gives a MARKET SHUT class wears the dark
        scope; what reaches both themes is a size, a face or a shape."""
        seen = 0
        for sel, pairs in self.named():
            if sel.startswith((self.WHERE, self.DARK)):
                continue
            seen += 1
            self.assertNotIn("light-mode", sel)
            for prop, value in pairs:
                with self.subTest(selector=sel, prop=prop):
                    self.assertIn(prop, self.BOTH_THEMES)
                    self.assertNotIn("--sv-warn", value)
        self.assertGreater(seen, 6)


class AmbientSourceTests(SimpleTestCase):

    def test_the_ambient_layers_are_not_displayed_on_work_pages(self):
        """Updated deliberately (the magic kept, 2026-11-12): the grid, the
        globe-eye, its glow and the circuits stay hidden everywhere; the
        ember canvas left that list for a rule of its own, which hides it
        off the pages that opted in, outside Ambience Magic and in light
        mode."""
        css = read(SAURON)
        still = block(css, ", ".join(STILL_LAYERS))
        self.assertEqual(still, {"display": "none !important"})
        for prelude, body, ctx in rules(css):
            if any(a in prelude for a in STILL_LAYERS) and "display" in dict(decls(body)) \
                    and dict(decls(body))["display"].startswith("none"):
                self.assertNotIn("#particles-canvas", prelude)
        embers = block(css, "body:not([data-sv-embers]) #particles-canvas,\n"
                            "        body:not([data-sv-ambience=\"magic\"]) #particles-canvas,\n"
                            "        body.light-mode #particles-canvas")
        self.assertEqual(embers, {"display": "none !important"})

    def test_the_particles_carry_no_tickers_and_no_prices(self):
        """The embers draw no text, ever: no label, no symbol, no figure
        (S1a took the fake tickers and prices out of main's script; the
        calm field never had any). At most 56 embers and 12 flakes of ash."""
        script = read(EMBERS)
        for gone in ("TICKERS", "tickerPrice", "fillText", "strokeText", "EUR/USD", "base:67500"):
            self.assertNotIn(gone, script)
        self.assertNotRegex(script, r"\.font\s*=")
        caps = re.search(r"NMAX = CFG\.embers \|\| (\d+), NAMAX = CFG\.ash \|\| (\d+)", script)
        self.assertTrue(caps, "the caps are not where the test reads them")
        self.assertLessEqual(int(caps.group(1)), 56)
        self.assertLessEqual(int(caps.group(2)), 12)
        self.assertRegex(script, r"Math\.min\(NMAX,")
        self.assertRegex(script, r"Math\.min\(NAMAX,")

    def test_the_caustics_and_the_fake_log_lines_are_gone(self):
        """Fabricated activity never ships: the two code-stream paragraphs
        typed invented log lines (fake R values, fake prices), hidden since
        S1a and still in the page; the caustics layer never showed on a
        work page and was the heaviest loop. Both are out of base.html and
        of the sheet, with the pupil and parallax loops of the hidden
        globe."""
        base = read(BASE)
        for gone in ("se-cs-paragraph", "seCsPara", "TEMPLATES", "caustics-canvas",
                     "Ambient code-stream", "globePupilGroup').style", "pupil.style.transform",
                     "Embers & Ash", "Mouse parallax"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, base)
        css = read(SAURON)
        for gone in ("se-cs-paragraph", "se-cs-line", "seCursorBlink", "#caustics-canvas"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, css)
        self.assertEqual(base.count('<canvas id="particles-canvas"></canvas>'), 1)


def mix(a, b, share):
    """color-mix(in srgb, a share, b) as a hex string."""
    x, y = hex_rgb(a), hex_rgb(b)
    return "#%02x%02x%02x" % tuple(round(x[i] * share + y[i] * (1 - share)) for i in range(3))


class ReviewFixesTests(SimpleTestCase):
    """The review of S1a (2026-11-07), on the sheets."""

    def test_a_taken_card_s_hover_keeps_every_word_at_4_5_to_1(self):
        """The rail's TAKEN card took 14 % of the taken gold over bg-3 on
        hover: its ages and rule fell to 4.1:1, its BULL badge to 3.9. The
        dark theme's hover is a breath of the gold, every text on it at
        4.5:1 or more, computed here as the browser mixes it."""
        rule = block(read(KIT), "body:not(.light-mode) .sr-signal-wrap.sr-acted .sr-signal:hover")
        m = re.fullmatch(r"color-mix\(in srgb, var\(--sr-taken\) (\d+)%, var\(--sv-bg-3\)\)",
                         rule["background"])
        self.assertTrue(m, rule)
        ground = mix(PALETTE["--sv-demo"], PALETTE["--sv-bg-3"], int(m.group(1)) / 100)
        texts = {"ink-3 (age, rule, venue)": (PALETTE["--sv-ink-3"], ground),
                 "ink-2 (who)": (PALETTE["--sv-ink-2"], ground),
                 "BULL badge": (PALETTE["--sv-up"], mix(PALETTE["--sv-up"], ground, .12)),
                 "BEAR badge": (PALETTE["--sv-down"], mix(PALETTE["--sv-down"], ground, .12)),
                 "TAKEN tag": (PALETTE["--sv-demo"], mix(PALETTE["--sv-demo"], ground, .18))}
        for name, (fg, bg) in texts.items():
            with self.subTest(text=name):
                self.assertGreaterEqual(contrast(fg, bg), 4.5)

    def test_the_band_s_apart_groups_print_at_full_strength(self):
        """At 85 % the PAPER label on a hovered PORTFOLIO cell was 4.35:1."""
        self.assertEqual(block(read(KIT), "body:not(.light-mode) .ip-cat .ip-pnl-apart"),
                         {"opacity": "1"})
        self.assertLess(contrast(mix(PALETTE["--sv-ink-3"], PALETTE["--sv-bg-3"], .85),
                                 PALETTE["--sv-bg-3"]), 4.5)

    def test_the_blue_chips_are_neutral_ink(self):
        """--accent-blue is the chart's first slot now (#3987E5): on its own
        12 % wash over a card it is 4.49:1. A severity or an asset class is
        not a series: the chips print in ink-2 (plan §3.6, §7)."""
        kit = read(KIT)
        for sel in (".badge-medium", ".badge-stock"):
            with self.subTest(selector=sel):
                self.assertEqual(RailFiltersOnTheKitTests.value(
                    kit, "body:not(.light-mode) " + sel, "color"), "var(--sv-ink-2)")
        wash = mix("#30a0e8", PALETTE["--sv-bg-1"], .12)
        self.assertLess(contrast(PALETTE["--sv-cat-1"], wash), 4.5)
        self.assertGreater(contrast(PALETTE["--sv-ink-2"], wash), 4.5)

    def test_the_band_s_cells_fit_more_at_the_11px_floor(self):
        """The band's words rose to 11 px and their cells grew by a third:
        at 1920 px two cells hid behind the arrow, where main showed all 14
        (review, 2026-11-07). A cell's sub-line is words, so Inter (plan
        rule 5; JetBrains Mono's 0.6 em is wider), and its sides take the
        spacing scale's 8, as the shared table's cells do."""
        kit = read(KIT)
        sub = RailFiltersOnTheKitTests.value(kit, ".ip-cat .ip-sub", "font-family")
        self.assertEqual(sub, "var(--sv-font-sans)")
        for side in ("padding-left", "padding-right"):
            self.assertEqual(RailFiltersOnTheKitTests.value(kit, ".ip-cat", side), "var(--sv-sp-3)")

    def test_a_kit_field_keeps_16px_on_a_phone(self):
        """iOS zooms the page on focus under 16 px (sv-responsive.css):
        .sv-input takes the base size, 14 px on a phone, so it is named."""
        self.assertEqual(block(read(KIT), ".sv-input", ("@media (max-width: 768px)",)),
                         {"font-size": "16px"})

    def test_a_disabled_variant_reads_disabled(self):
        """The variants (BUY, SELL, stop, secondary) come after sauron.css's
        disabled look at its weight, so a disabled BUY kept its jade: the
        disabled look is restated after them."""
        kit = read(KIT)
        order = [p for p, b, c in rules(kit) if not c]
        # Updated deliberately (the magic kept, 2026-11-12): the side's own
        # light on hover names a BUY that is :not([disabled]); it is neither
        # a variant's look nor the disabled look, so neither list takes it.
        lit = ":is(:hover, :focus-visible)"
        last_variant = max(i for i, p in enumerate(order)
                           if (".btn.btn-buy" in p or ".btn.btn-stop" in p) and lit not in p)
        disabled = [i for i, p in enumerate(order)
                    if "[disabled]" in p and ".btn-buy" in p and lit not in p]
        self.assertTrue(disabled)
        self.assertGreater(disabled[-1], last_variant)
        rule = dict(decls([b for p, b, c in rules(kit) if not c][disabled[-1]]))
        self.assertEqual((rule["background"], rule["color"], rule["border-color"]),
                         ("var(--sv-bg-2)", "var(--sv-ink-4)", "var(--sv-line-1)"))

    def test_the_dark_field_rule_yields_to_a_component_s_state(self):
        """The field rule's weight (0,2,2) outweighed every component's own
        state: the idle lock's filled PIN boxes lost their edge. At a
        field's weight (:where), a component's state wins again."""
        kit = strip_comments(read(KIT))
        self.assertIn(":where(body:not(.light-mode)) :is(.form-input, .input, input[type=text]", kit)
        self.assertNotRegex(kit, r"(^|\})\s*body:not\(\.light-mode\) :is\(\.form-input")


def _script_with(marker):
    base = read(BASE)
    for m in re.finditer(r"<script>(.*?)</script>", base, flags=re.S):
        if marker in m.group(1):
            return m.group(1)
    raise AssertionError("no inline script with %r" % marker)


# ══════════════════════════════════════════════════════════════════════════
# The embers and the clock, run under node with a stubbed page
# ══════════════════════════════════════════════════════════════════════════

NODE_HARNESS = r"""
const vm = require('vm');
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const clockSrc = fs.readFileSync(process.argv[3], 'utf8');

function world(o) {
  o = Object.assign({ ambience: 'magic', embers: true, hidden: false, reduced: false, light: false,
                      cssHides: false, cover: () => false, hitCost: 0, drawCost: 0, words: [],
                      cardBox: null, kbd: false }, o);
  let now = 1000, rafQ = [], rafAsked = 0, idleQ = [], timers = [], hits = 0, fontSet = 0;
  const calls = {}, observers = [], listeners = {}, wlisteners = {};
  const context = main => new Proxy({}, {
    get: (t, k) => {
      if (k in t) return t[k];
      if (k === 'createRadialGradient') return () => ({ addColorStop() {} });
      return () => { if (main) { calls[k] = (calls[k] || 0) + 1; if (k === 'clearRect') now += o.drawCost; } };
    },
    set: (t, k, v) => { if (main && k === 'font') fontSet++; t[k] = v; return true; } });
  const mainCtx = context(true);
  const canvas = { id: 'particles-canvas', width: 0, height: 0, getContext: () => mainCtx };
  const classes = new Set(o.light ? ['light-mode'] : []);
  const attrs = { 'data-sv-ambience': o.ambience };
  if (o.embers) attrs['data-sv-embers'] = '';
  const mutate = () => observers.forEach(f => f([]));
  const body = {
    classList: { contains: c => classes.has(c), add: c => { classes.add(c); mutate(); },
                 remove: c => { classes.delete(c); mutate(); } },
    getAttribute: k => (k in attrs ? attrs[k] : null), hasAttribute: k => k in attrs,
    setAttribute: (k, v) => { attrs[k] = v; mutate(); }, removeAttribute: k => { delete attrs[k]; mutate(); } };
  const root = { scrollHeight: 912 };
  const rect = b => (b ? { left: b[0], top: b[1], right: b[2], bottom: b[3], width: b[2] - b[0], height: b[3] - b[1] }
                       : { left: 0, top: 0, right: 0, bottom: 0, width: 0, height: 0 });
  const card = { parentElement: body, isCard: true, getBoundingClientRect: () => rect(o.cardBox) };
  // base.html's "?" sheet (#kbdModalOverlay), its class watched as <body>'s is
  const kclasses = new Set();
  const kbd = o.kbd ? { id: 'kbdModalOverlay', classList: { contains: c => kclasses.has(c),
    add: c => { kclasses.add(c); mutate(); }, remove: c => { kclasses.delete(c); mutate(); } } } : null;
  const doc = {
    body, documentElement: root, hidden: o.hidden, fonts: null,
    getElementById: id => (id === 'particles-canvas' ? canvas : (id === 'kbdModalOverlay' ? kbd : null)),
    createElement: () => ({ width: 0, height: 0, getContext: () => context(false) }),
    querySelectorAll: () => o.words.map(b => ({ getBoundingClientRect: () => (
      { left: b[0], top: b[1], right: b[2], bottom: b[3], width: b[2] - b[0], height: b[3] - b[1] }) })),
    elementFromPoint: (x, y) => { hits++; now += o.hitCost; return o.cover(x, y) ? card : body; },
    addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); } };
  const win = {
    document: doc, innerWidth: 1440, innerHeight: 912, scrollY: 0,
    matchMedia: () => ({ matches: o.reduced, addEventListener() {} }),
    getComputedStyle: el => (el === canvas ? { display: o.cssHides ? 'none' : 'block' }
      : { backgroundImage: 'none', backgroundColor: el && el.isCard ? 'rgb(7, 19, 12)' : 'rgba(0, 0, 0, 0)' }),
    performance: { now: () => now },
    requestAnimationFrame: f => { rafAsked++; rafQ.push(f); return rafAsked; },
    cancelAnimationFrame: () => { rafQ = []; },
    requestIdleCallback: f => { idleQ.push(f); return idleQ.length; },
    setTimeout: (f, ms) => { timers.push({ at: now + (ms || 0), f }); return timers.length; },
    clearTimeout: id => { if (timers[id - 1]) timers[id - 1].f = null; },
    addEventListener: (t, f) => { (wlisteners[t] = wlisteners[t] || []).push(f); },
    MutationObserver: function (f) { this.observe = () => observers.push(f); },
    Math, Float32Array, Map, console };
  win.window = win;
  vm.runInContext(src, vm.createContext(win));
  return {
    o, body, doc, root, calls, win, kbd,
    stats: () => win.__svEmberStats,
    idle: () => { let n = 0; while (idleQ.length && n < 2000) { idleQ.shift()({ timeRemaining: () => 4 }); n++; } return n; },
    tick: dt => { now += dt; const q = rafQ; rafQ = []; q.forEach(f => f(now)); return q.length; },
    advance: ms => { now += ms; timers.forEach(t => { if (t.f && t.at <= now) { const f = t.f; t.f = null; f(); } }); },
    fire: t => (listeners[t] || []).forEach(f => f({ type: t })),
    wfire: (t, ev) => (wlisteners[t] || []).forEach(f => f(Object.assign({ type: t, target: doc }, ev || {}))),
    asked: () => rafAsked, pending: () => rafQ.length, hits: () => hits, fontSet: () => fontSet };
}
function settle(w, ticks) { let n = 0; for (let i = 0; i < ticks; i++) n += w.tick(16.7); return n; }
// the field starts once the page's own entrance is over (900 ms), then maps in idle slices
function start(w) { w.advance(1000); return w.idle(); }

const out = {};
// opted in, under Magic, with a void: frames are scheduled, the caps hold
{ const w = world(); const slices = start(w); const s = w.stats();
  out.running = { asked: w.asked(), embers: s.embers, ash: s.ash, hits: w.hits(), slices, maps: s.maps };
  settle(w, 20);
  out.running.frames = s.frames; out.running.perFrame = (w.calls.drawImage || 0) / s.frames;
  out.running.text = (w.calls.fillText || 0) + (w.calls.strokeText || 0) + w.fontSet(); }
// the tab hidden
{ const w = world({ hidden: true }); start(w); settle(w, 5); out.hidden = w.asked();
  w.doc.hidden = false; w.fire('visibilitychange'); w.idle(); out.shownAgain = w.asked() > 0;
  const a = w.asked(); w.doc.hidden = true; w.fire('visibilitychange'); settle(w, 5); out.hiddenAgain = [w.asked() - a, w.pending()]; }
// the PIN lock, until it lifts
{ const w = world(); start(w); settle(w, 4); const a = w.asked();
  w.fire('sv:pin-locked'); settle(w, 5); out.locked = [w.asked() - a, w.pending()];
  w.fire('sv:pin-unlocked'); out.unlocked = w.asked() - a; }
// a dialog holds the page (sv-overlay.js: body.sv-scroll-locked), until it closes
{ const w = world(); start(w); settle(w, 4); const a = w.asked();
  w.body.classList.add('sv-scroll-locked'); settle(w, 5); out.dialog = [w.asked() - a, w.pending()];
  w.body.classList.remove('sv-scroll-locked'); out.dialogClosed = w.asked() - a; }
// Calm and Off: nothing mapped, nothing scheduled; switched to from Magic, the canvas is cleared
['calm', 'off'].forEach(m => {
  const w = world({ ambience: m }); start(w); settle(w, 5);
  const v = world(); start(v); settle(v, 4);
  const a = v.asked(), c = v.calls.clearRect || 0, d = v.calls.drawImage || 0;
  v.body.setAttribute('data-sv-ambience', m); settle(v, 5);
  const off = { asked: v.asked() - a, cleared: (v.calls.clearRect || 0) - c, drawn: (v.calls.drawImage || 0) - d };
  v.body.setAttribute('data-sv-ambience', 'magic');
  out[m] = { asked: w.asked(), hits: w.hits(), switched: off, back: v.asked() - a };
});
// not opted in; the sheet hides the canvas; light mode
{ const w = world({ embers: false }); start(w); settle(w, 5); out.notOptedIn = [w.asked(), w.hits()];
  w.body.setAttribute('data-sv-embers', ''); w.idle(); out.optedInLater = w.asked() > 0; }
{ const w = world({ cssHides: true }); start(w); settle(w, 5); out.cssHidden = [w.asked(), w.hits()]; }
{ const w = world({ light: true }); start(w); settle(w, 5); out.lightMode = [w.asked(), w.hits()]; }
// a page with no void
{ const w = world({ cover: () => true }); start(w); settle(w, 5);
  out.noVoid = { asked: w.asked(), embers: w.stats().embers, ash: w.stats().ash, drawn: w.calls.drawImage || 0 }; }
// reduced motion: one still frame, no frame asked, and none again when the page changes
{ const w = world({ reduced: true }); start(w); settle(w, 5);
  out.reduced = { asked: w.asked(), draws: w.calls.clearRect || 0, sprites: w.calls.drawImage || 0,
                  field: w.stats().embers + w.stats().ash };
  w.body.classList.add('sv-scroll-locked'); w.body.classList.remove('sv-scroll-locked');
  out.reduced.drawsAfter = w.calls.clearRect || 0; }
// the cap: ten ticks 16.7 ms apart give five draws
{ const w = world(); start(w); const f = w.stats().frames; settle(w, 10); out.cap = w.stats().frames - f; }
// the void map: a card over the top half; no ember is born there, at the start or when
// one that left the screen is born again (its x falls back to the left edge)
{ const w = world({ cover: (x, y) => y < 456 }); start(w);
  const born = w.stats().field().map(e => e[1]), reborn = [];
  let prev = w.stats().field();
  for (let i = 0; i < 4000; i++) {
    w.tick(100);
    const cur = w.stats().field();
    cur.forEach((e, k) => { if (e[0] < prev[k][0]) reborn.push(e[1]); });
    prev = cur;
  }
  out.map = { embers: w.stats().embers, minBorn: Math.min.apply(null, born), reborn: reborn.length,
              minReborn: Math.min.apply(null, reborn), voidArea: w.stats().voidArea }; }
// the slices: a hit test costs 0.1 ms on this clock, so a row costs 2.4
{ const w = world({ hitCost: 0.1 }); const n = start(w);
  out.slices = { max: w.stats().sliceMax, count: w.stats().mapSlices, ran: n, maps: w.stats().maps }; }
// a live swap that leaves the page's shape alone costs no map; one that moves it costs one
{ const w = world(); start(w); const h = w.hits();
  w.fire('sv:live-swapped'); w.advance(400); w.idle(); const same = w.hits() - h;
  w.root.scrollHeight = 1400; w.fire('sv:live-swapped'); w.advance(400); w.idle();
  out.swap = [same, w.hits() - h]; }
// near words on the void: held to .18 inside their box, the ember's own alpha from 18 px
{ const w = world({ words: [[400, 300, 700, 314]] }); start(w); const s = w.stats();
  out.near = { inside: s.alphaAt(500, 305, 0.55), edge: s.alphaAt(500, 300, 0.55), half: s.alphaAt(500, 291, 0.55),
               at18: s.alphaAt(500, 282, 0.55), far: s.alphaAt(100, 100, 0.55), dim: s.alphaAt(500, 305, 0.1),
               words: s.words }; }
// review 2026-11-12: a resize while a dialog's scrim holds the page; the map waits for the
// hold to end (through the scrim it would find no void and empty the field), then maps
{ let scrim = false; const w = world({ cover: () => scrim }); start(w); settle(w, 4);
  const h = w.hits(), e = w.stats().embers;
  scrim = true; w.body.classList.add('sv-scroll-locked'); w.wfire('resize'); w.advance(400); w.idle(); settle(w, 3);
  const during = { hits: w.hits() - h, embers: w.stats().embers };
  scrim = false; w.body.classList.remove('sv-scroll-locked'); const a = w.asked(); w.advance(400); w.idle(); settle(w, 3);
  out.heldRemap = { before: e, during, after: { hits: w.hits() - h, embers: w.stats().embers, asked: w.asked() - a } }; }
// the "?" shortcut sheet, base.html's own modal outside SV.overlay: open, no frame
{ const w = world({ kbd: true }); start(w); settle(w, 4); const a = w.asked();
  w.kbd.classList.add('open'); settle(w, 5); out.kbd = [w.asked() - a, w.pending()];
  w.kbd.classList.remove('open'); out.kbdClosed = w.asked() - a; }
// a panel scrolling inside itself (the nav, the rail) leaves the void as it was: no map;
// the page's own scroll that moves it maps once
{ const w = world(); start(w); const h = w.hits();
  w.wfire('scroll', { target: { nodeType: 1 } }); w.advance(400); w.idle(); const inner = w.hits() - h;
  w.win.scrollY = 120; w.wfire('scroll'); w.advance(400); w.idle();
  out.innerScroll = [inner, w.hits() - h]; }
// a 10 px gutter between two cards stacked one above the other is no void: no ember is
// born to run along it (a point counts only where the void runs a row above and below too)
{ const w = world({ cover: (x, y) => !(y >= 296 && y < 306) }); start(w); settle(w, 3);
  out.seam = { voidArea: w.stats().voidArea, embers: w.stats().embers, asked: w.asked() }; }
// near a card's edge an ember fades out: gone within 12 px, whole again at 24 px, so none
// is ever cut flat by a card or seen in a gutter under 24 px
{ const w = world({ cover: (x, y) => x >= 400 && x < 700 && y >= 300 && y < 400, cardBox: [400, 300, 700, 400] });
  start(w); const s = w.stats();
  out.ground = { grounds: s.grounds, inside: s.groundAt(500, 350, 0.55), at6: s.groundAt(500, 294, 0.55),
                 at12: s.groundAt(500, 288, 0.55), at18: s.groundAt(500, 282, 0.55), at24: s.groundAt(500, 276, 0.55),
                 side18: s.groundAt(718, 350, 0.55), far: s.groundAt(100, 100, 0.55),
                 words: s.alphaAt(500, 282, 0.55) }; }
// the stats ring: the last 240 draws, so a late read still sees the latest
{ const w = world(); start(w); const s = w.stats(); let n = 0;
  while (s.n < 300) { w.o.drawCost = (s.n + 1) / 100; w.tick(40); if (++n > 2000) break; }
  const r = s.recent();
  out.ring = { n: s.n, kept: r.length, first: r[0], last: r[r.length - 1] }; }
// the clock in base.html: its own small script
{ let intervals = 0, text = null;
  const el = { getAttribute: () => 'UTC', set textContent(v) { text = v; } };
  const ctx = { Intl, Date, document: { getElementById: id => (id === 'clock' ? el : null) },
                setInterval: () => { intervals++; return 1; } };
  vm.runInContext(clockSrc, vm.createContext(ctx));
  out.clock = { intervals, text, lines: clockSrc.split('\n').length }; }
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "node is not on this machine")
class AmbientGuardNodeTests(SimpleTestCase):
    """static/js/sv-embers.js, run as it ships with a stubbed page (rewritten
    for it, the magic kept, 2026-11-12; S1a's class ran main's ember,
    parallax and caustics loops, which are gone). The field runs on a page
    that opted in, under Ambience Magic, where the page shows a void; it
    asks for no frame while the tab is hidden, the PIN lock is up or a
    dialog holds the page, under Calm and Off, on a page that has not
    opted in, or where the page shows no void; under reduced motion it
    draws one still frame. The clock is its own small script in base.html
    and ticks either way."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with tempfile.TemporaryDirectory() as tmp:
            clock = pathlib.Path(tmp) / "clock.js"
            clock.write_text(_script_with("getElementById('clock')"), encoding="utf-8")
            harness = pathlib.Path(tmp) / "harness.js"
            harness.write_text(NODE_HARNESS, encoding="utf-8")
            done = subprocess.run([NODE, str(harness), str(ROOT / EMBERS), str(clock)],
                                  capture_output=True, text=True, timeout=120)
        if done.returncode:
            raise AssertionError(done.stderr)
        cls.got = json.loads(done.stdout)

    def test_the_field_runs_where_it_shows(self):
        """Opted in, Magic, a void: frames are asked for; one ember per
        6,000 px² of void up to 56, ash up to 12; one drawImage each."""
        r = self.got["running"]
        self.assertGreater(r["asked"], 0, r)
        self.assertEqual((r["embers"], r["ash"]), (56, 12))
        self.assertEqual(r["hits"], 38 * 24)             # 24 columns, a row every 24 px
        self.assertEqual(r["maps"], 1)
        self.assertGreater(r["frames"], 0)
        self.assertEqual(r["perFrame"], 68)
        self.assertEqual(r["text"], 0)

    def test_no_frame_is_scheduled_for_a_hidden_tab(self):
        self.assertEqual(self.got["hidden"], 0)
        self.assertTrue(self.got["shownAgain"])
        self.assertEqual(self.got["hiddenAgain"], [0, 0])

    def test_no_frame_is_scheduled_while_the_pin_lock_is_up(self):
        self.assertEqual(self.got["locked"], [0, 0])
        self.assertGreater(self.got["unlocked"], 0)

    def test_no_frame_is_scheduled_while_a_dialog_holds_the_page(self):
        self.assertEqual(self.got["dialog"], [0, 0])
        self.assertGreater(self.got["dialogClosed"], 0)

    def test_no_frame_is_scheduled_under_calm_or_off(self):
        for mode in ("calm", "off"):
            got = self.got[mode]
            with self.subTest(mode=mode):
                self.assertEqual((got["asked"], got["hits"]), (0, 0), got)
                self.assertEqual(got["switched"]["asked"], 0, got)
                self.assertGreaterEqual(got["switched"]["cleared"], 1, got)     # the canvas cleared
                self.assertEqual(got["switched"]["drawn"], 0, got)
                self.assertGreater(got["back"], 0, got)                         # back on Magic, no reload

    def test_no_frame_is_scheduled_on_a_page_that_has_not_opted_in(self):
        self.assertEqual(self.got["notOptedIn"], [0, 0])
        self.assertTrue(self.got["optedInLater"])
        self.assertEqual(self.got["cssHidden"], [0, 0])
        self.assertEqual(self.got["lightMode"], [0, 0])

    def test_a_page_with_no_void_has_no_embers_and_asks_for_no_frame(self):
        self.assertEqual(self.got["noVoid"], {"asked": 0, "embers": 0, "ash": 0, "drawn": 0})

    def test_no_frame_is_scheduled_under_reduced_motion(self):
        """One still frame, drawn once: the field is simply there."""
        r = self.got["reduced"]
        self.assertEqual(r["asked"], 0, r)
        self.assertEqual((r["draws"], r["drawsAfter"]), (1, 1), r)
        self.assertEqual(r["sprites"], r["field"])
        self.assertGreater(r["field"], 0)

    def test_at_most_30_frames_a_second(self):
        self.assertEqual(self.got["cap"], 5)

    def test_embers_are_born_in_the_void_only(self):
        """Updated deliberately (review 2026-11-12): a point counts as void
        where the void runs a row above and below it too, so the row that
        touches the card's edge (y 456 to 480) is held off as well."""
        m = self.got["map"]
        self.assertEqual(m["embers"], 56)
        self.assertEqual(m["voidArea"], 1440 * 432)
        self.assertGreaterEqual(m["minBorn"], 480)
        self.assertGreater(m["reborn"], 56)
        self.assertGreaterEqual(m["minReborn"], 480)

    def test_the_map_never_holds_the_main_thread(self):
        """Built in slices: none works for more than 4 ms plus one row."""
        s = self.got["slices"]
        self.assertLessEqual(s["max"], 4 + 24 * 0.1 + 1e-6, s)
        self.assertGreater(s["count"], 10, s)
        self.assertEqual(s["count"], s["ran"])
        self.assertEqual(s["maps"], 1)

    def test_a_swap_that_leaves_the_page_s_shape_alone_costs_no_map(self):
        self.assertEqual(self.got["swap"], [0, 38 * 24])

    def test_an_ember_dims_near_words_on_the_void(self):
        n = self.got["near"]
        self.assertEqual(n["words"], 1)
        self.assertAlmostEqual(n["inside"], 0.18, places=6)
        self.assertAlmostEqual(n["edge"], 0.18, places=6)
        self.assertAlmostEqual(n["half"], 0.365, places=6)
        self.assertAlmostEqual(n["at18"], 0.55, places=6)
        self.assertAlmostEqual(n["far"], 0.55, places=6)
        self.assertAlmostEqual(n["dim"], 0.1, places=6)       # never raised: a cap, not a floor

    def test_a_map_waits_for_a_dialog_to_close(self):
        """Review 2026-11-12: a resize under a dialog's scrim mapped the
        scrim, found no void, emptied the field and drew nothing until the
        next scroll. The map now waits for the hold to end, then maps the
        page as it is."""
        g = self.got["heldRemap"]
        self.assertEqual(g["before"], 56)
        self.assertEqual(g["during"], {"hits": 0, "embers": 56})
        self.assertEqual((g["after"]["hits"], g["after"]["embers"]), (38 * 24, 56))
        self.assertGreater(g["after"]["asked"], 0)

    def test_no_frame_is_scheduled_under_the_shortcut_sheet(self):
        """Review 2026-11-12: base.html's "?" sheet is a modal outside
        SV.overlay (no scroll lock): open, the field asks for no frame;
        closed, it runs again."""
        self.assertEqual(self.got["kbd"], [0, 0])
        self.assertGreater(self.got["kbdClosed"], 0)

    def test_a_panel_scrolling_inside_itself_costs_no_map(self):
        """Review 2026-11-12: the nav and the rail paint their own ground;
        their scroll leaves the void as it was. The page's scroll maps."""
        self.assertEqual(self.got["innerScroll"], [0, 38 * 24])

    def test_a_gutter_between_stacked_cards_is_no_void(self):
        """Review 2026-11-12 (the brief: the magic around the numbers,
        never among them): embers glinted in the 10 and 16 px gutters
        between the KPI tiles."""
        self.assertEqual(self.got["seam"], {"voidArea": 0, "embers": 0, "asked": 0})

    def test_an_ember_fades_out_near_a_card_s_edge(self):
        g = self.got["ground"]
        self.assertEqual(g["grounds"], 1)
        for k in ("inside", "at6", "at12"):
            with self.subTest(at=k):
                self.assertEqual(g[k], 0)
        self.assertAlmostEqual(g["at18"], 0.275, places=6)
        self.assertAlmostEqual(g["side18"], 0.275, places=6)
        self.assertAlmostEqual(g["at24"], 0.55, places=6)
        self.assertAlmostEqual(g["far"], 0.55, places=6)
        self.assertAlmostEqual(g["words"], 0.55, places=6)     # alphaAt stays the words' cap (C5)

    def test_the_stats_ring_keeps_the_last_240_draws(self):
        r = self.got["ring"]
        self.assertEqual((r["n"], r["kept"]), (300, 240))
        self.assertAlmostEqual(r["first"], 0.61, places=4)
        self.assertAlmostEqual(r["last"], 3.0, places=4)

    def test_the_clock_still_ticks(self):
        got = self.got["clock"]
        self.assertEqual(got["intervals"], 1)
        self.assertRegex(got["text"] or "", r"^\d\d:\d\d:\d\d UTC$")
        self.assertLess(got["lines"], 25)        # the clock alone: no loop rides in its script


# ══════════════════════════════════════════════════════════════════════════
# Measured: the shell as the browser computes it
# ══════════════════════════════════════════════════════════════════════════

SHELL_PROBE = r"""(async function () {
    function frame() { return new Promise(function (r) { requestAnimationFrame(function () { requestAnimationFrame(r); }); }); }
    await frame();
    var b = document.body, cs = getComputedStyle(b);
    var out = { width: innerWidth,
        body: { family: cs.fontFamily, size: cs.fontSize, weight: cs.fontWeight, line: cs.lineHeight },
        docOverflowX: document.documentElement.scrollWidth - document.documentElement.clientWidth };
    var probe = document.createElement('div');
    probe.innerHTML = '<button>b</button><input type="text" value="i"><select><option>s</option></select><textarea>t</textarea>'
        + '<span class="up">+1</span><span class="down">-1</span><span class="sign-flat">0</span>'
        + '<span class="sv-world sv-world--live">REAL</span>';
    b.appendChild(probe);
    // What the review of 2026-11-07 found, on chips and states the shell
    // carries: put inside the page's content, like the pages print them.
    var rv = document.createElement('div');
    rv.innerHTML = '<span class="hd-tab-r up">+5.78R</span><span class="hd-tone-up">+1.0</span>'
        + '<div class="sv-adv-card"><span class="up">+12.00</span></div>'
        + '<span class="badge badge-medium">MEDIUM</span><span class="badge badge-stock">STOCK</span>'
        + '<button type="button" class="btn btn-buy" disabled>Buy</button>'
        + '<button type="button" class="btn btn-sell" disabled>Sell</button>'
        + '<div class="il-card"><input type="password" class="has-val" value="1"></div>'
        + '<div class="ip-cat"><span class="ip-pnl"><span class="ip-pnl-apart">PAPER</span></span></div>'
        + '<span class="badge badge-bullish">BULL</span><span class="sv-venue sv-venue--live">LIVE</span>'
        + '<span class="sv-unknown">—</span><span class="sv-world sv-world--paper">PAPER</span>'
        + '<div class="ip-cat"><span class="ip-count">3</span></div>'
        + '<span class="dh-chg up">+0.42%%</span><span class="sr-pop-dir sr-pop-dir-bullish">BULLISH</span>';
    (document.querySelector('.page-content') || b).appendChild(rv);
    function q(s) { return rv.querySelector(s); }
    function look(s) { var c = getComputedStyle(q(s)); return { color: c.color, bg: c.backgroundColor, border: c.borderTopColor, opacity: c.opacity }; }
    out.review = { hordeUp: look('.hd-tab-r.up').color, toneUp: look('.hd-tone-up').color,
                   adviceUp: look('.sv-adv-card .up').color, medium: look('.badge-medium'),
                   stock: look('.badge-stock'), buyOff: look('.btn-buy'), sellOff: look('.btn-sell'),
                   pinFilled: look('.il-card input').border, apart: look('.ip-pnl-apart').opacity };
    out.controls = Array.prototype.map.call(probe.querySelectorAll('button, input, select, textarea'), function (e) {
        var c = getComputedStyle(e); return { tag: e.tagName, family: c.fontFamily, size: c.fontSize, color: c.color };
    });
    out.ink1 = (function () { var s = document.createElement('span'); s.style.color = 'var(--sv-ink-1)'; b.appendChild(s);
        var c = getComputedStyle(s).color; s.remove(); return c; })();
    out.bodyColor = cs.color;
    out.up = getComputedStyle(probe.querySelector('.up')).color;
    out.down = getComputedStyle(probe.querySelector('.down')).color;
    out.flat = getComputedStyle(probe.querySelector('.sign-flat')).color;
    var real = getComputedStyle(probe.querySelector('.sv-world--live'));
    out.real = { bg: real.backgroundColor, color: real.color, size: real.fontSize };
    // The ambient layers and the endless animations, per Ambience (the
    // body's attribute, as the operator's choice sets it).
    function ambientNow() {
        var got = {};
        %(ambient)s.forEach(function (s) {
            var e = document.querySelector(s);
            got[s] = e ? getComputedStyle(e).display : 'absent';
        });
        return got;
    }
    function animsNow() {
        return document.getAnimations().filter(function (a) {
            var t = a.effect && a.effect.getComputedTiming();
            return a.playState === 'running' && t && t.iterations === Infinity;
        }).map(function (a) { return a.animationName + '@' + (a.effect.target.className && a.effect.target.className.baseVal !== undefined ? a.effect.target.className.baseVal : a.effect.target.className); });
    }
    out.embers = b.hasAttribute('data-sv-embers');
    out.ambient = {}; out.anims = {};
    var modes = ['calm', 'off', 'magic'];
    for (var mi = 0; mi < modes.length; mi++) {
        b.setAttribute('data-sv-ambience', modes[mi]);
        await frame();
        out.ambient[modes[mi]] = ambientNow();
        out.anims[modes[mi]] = animsNow();
    }
    // The shell's own text: everything outside the page content, visible or
    // not (a dropdown waiting for its hover counts), the ambient layers aside.
    function own(el) {
        for (var i = 0; i < el.childNodes.length; i++) {
            var n = el.childNodes[i];
            if (n.nodeType === 3 && n.nodeValue.trim()) return true;
        }
        return false;
    }
    function rgba(c) {
        var m = /rgba?\(([^)]+)\)/.exec(c || '');
        if (!m) return null;
        var p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number);
        return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
    }
    function over(t, u) { return { r: t.r * t.a + u.r * (1 - t.a), g: t.g * t.a + u.g * (1 - t.a), b: t.b * t.a + u.b * (1 - t.a), a: 1 }; }
    function lum(c) {
        function f(v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }
        return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
    }
    function ground(el) {
        var layers = [];
        for (var n = el; n && n.nodeType === 1; n = n.parentElement) {
            var c = rgba(getComputedStyle(n).backgroundColor);
            if (c && c.a > 0) { layers.push(c); if (c.a >= 0.999) break; }
        }
        var g = layers.length && layers[layers.length - 1].a >= 0.999 ? layers.pop() : { r: 0, g: 0, b: 0, a: 1 };
        while (layers.length) g = over(layers.pop(), g);
        return g;
    }
    var AMB = '.grid-bg, .eye-glow-shadow, .globe-eye-bg, .globe-circuits-bg, #particles-canvas';
    out.shellSmall = []; out.shellLow = []; out.redFills = []; out.shellText = 0;
    Array.prototype.forEach.call(b.querySelectorAll('*'), function (el) {
        if (el === probe || probe.contains(el)) return;
        if (el.closest('script, style, noscript, template') || el.closest(AMB)) return;
        if (!own(el)) return;
        var c = getComputedStyle(el);
        var name = el.tagName.toLowerCase() + (typeof el.className === 'string' && el.className ? '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.') : '');
        var bg = rgba(c.backgroundColor);
        if (bg && bg.a >= 0.5 && bg.r >= 150 && bg.g < 130 && bg.b < 140
                && !el.closest('.sv-world--live, .sv-armed-pill, .tk-venue--live, .sv-venue--live')) {
            out.redFills.push(name + ' ' + c.backgroundColor);
        }
        if (el.closest('.page-content')) return;
        out.shellText++;
        if (parseFloat(c.fontSize) < 11) out.shellSmall.push(name + '@' + c.fontSize);
        var r = el.getBoundingClientRect();
        if (c.display === 'none' || c.visibility === 'hidden' || r.width === 0 || r.height === 0) return;
        for (var a = el; a; a = a.parentElement) {
            var ac = getComputedStyle(a);
            if (ac.display === 'none' || ac.visibility === 'hidden' || parseFloat(ac.opacity) === 0) return;
        }
        var fg = rgba(c.color), g = ground(el);
        if (fg.a < 1) fg = over(fg, g);
        var x = lum(fg), y = lum(g);
        var ratio = (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
        var large = parseFloat(c.fontSize) >= 24 || (parseFloat(c.fontSize) >= 18.66 && parseInt(c.fontWeight, 10) >= 700);
        if (ratio < (large ? 3 : 4.5)) out.shellLow.push(name + ' ' + ratio.toFixed(2) + ' ' + c.color);
    });
    b.classList.add('light-mode');
    var lcs = getComputedStyle(b);
    out.ambient.light = ambientNow();
    out.light = {};
    %(light)s.forEach(function (n) { out.light[n] = lcs.getPropertyValue(n).trim(); });
    out.lightUp = getComputedStyle(probe.querySelector('.up')).color;
    out.lightReal = getComputedStyle(probe.querySelector('.sv-world--live')).backgroundColor;
    out.lightAliases = {};
    %(aliases)s.forEach(function (n) { out.lightAliases[n] = lcs.getPropertyValue(n).trim(); });
    out.lightEls = { bull: look('.badge-bullish'), live: look('.sv-venue--live'), unknown: look('.sv-unknown'),
                     paper: look('.sv-world--paper'), count: look('.ip-count'),
                     chg: look('.dh-chg.up'), dir: look('.sr-pop-dir-bullish') };
    b.classList.remove('light-mode');
    probe.remove();
    rv.remove();
    return JSON.stringify(out);
})()""" % {"ambient": json.dumps(list(AMBIENT)), "light": json.dumps(sorted(LIGHT_TODAY)),
           "aliases": json.dumps(sorted(set(LIGHT_ALIASES_TODAY) | set(LIGHT_OVERLAY_TODAY)))}


#: The endless animations per Ambience, for the pass that asks for reduced
#: motion.
REDUCED_PROBE = r"""(async function () {
    function frame() { return new Promise(function (r) { requestAnimationFrame(function () { requestAnimationFrame(r); }); }); }
    var out = {}, modes = ['magic', 'calm', 'off'];
    for (var i = 0; i < modes.length; i++) {
        document.body.setAttribute('data-sv-ambience', modes[i]);
        await frame();
        out[modes[i]] = document.getAnimations().filter(function (a) {
            var t = a.effect && a.effect.getComputedTiming();
            return a.playState === 'running' && t && t.iterations === Infinity;
        }).map(function (a) { return a.animationName; });
    }
    return JSON.stringify(out);
})()"""


def _measure_reduced(pages, viewports, probe, tmp_prefix):
    """tests.test_ui_s0_fixes._measure, with the browser asked for reduced
    motion: {(url, width): the probe's answer}."""
    tmp = tempfile.mkdtemp(prefix=tmp_prefix)
    try:
        files = {}
        for i, (url, markup) in enumerate(sorted(pages.items())):
            path = pathlib.Path(tmp) / ("page%d.html" % i)
            path.write_text(_offline(markup), encoding="utf-8")
            files[url] = path.as_uri()
        chrome = _Chrome(CHROME)
        try:
            got = {}
            for width, height in viewports:
                sid = chrome.page(width, height, False)
                chrome.call("Emulation.setEmulatedMedia", {"features": [
                    {"name": "prefers-reduced-motion", "value": "reduce"}]}, session=sid)
                for url, uri in files.items():
                    chrome.open(sid, uri)
                    got[(url, width)] = json.loads(chrome.eval(sid, probe))
            return got
        finally:
            chrome.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def rgb(h):
    return "rgb(%d, %d, %d)" % hex_rgb(h)


def rgba_of(css_colour):
    """(r, g, b, a) of a computed colour, rgb()/rgba() or the color(srgb …)
    a color-mix() computes to, so two spellings of one colour compare
    equal."""
    m = re.fullmatch(r"color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: / ([\d.]+))?\)", css_colour)
    if m:
        r, g, b = (round(float(x) * 255) for x in m.group(1, 2, 3))
        return (r, g, b, round(float(m.group(4) or 1), 3))
    m = re.fullmatch(r"rgba?\((\d+), (\d+), (\d+)(?:, ([\d.]+))?\)", css_colour)
    if not m:
        raise AssertionError("not a colour: %r" % css_colour)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), round(float(m.group(4) or 1), 3))


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class ShellMeasuredTests(TestCase):
    """/command/ and /positions/ as the browser lays them out, offline, at the
    four desk widths."""

    VIEWPORTS = ((1280, 800), (1440, 900), (1920, 1080), (2560, 1440))

    @classmethod
    def setUpTestData(cls):
        user = get_user_model().objects.create_user("s1a_shell", password="x",
                                                    is_staff=True)
        _quote("BTCUSD", 60600)
        client = Client()
        client.force_login(user)
        pages = {url: _get(client, url) for url in ("/command/", "/positions/")}
        cls.got = _measure(pages, cls.VIEWPORTS, SHELL_PROBE, "sv-s1a-shell-")
        cls.reduced = _measure_reduced(pages, cls.VIEWPORTS, REDUCED_PROBE, "sv-s1a-reduced-")

    def test_the_body_is_inter_13_on_1_45_at_400(self):
        for (url, width), got in sorted(self.got.items()):
            with self.subTest(url=url, width=width):
                body = got["body"]
                self.assertTrue(body["family"].startswith("Inter"), body)
                want = {1280: 13, 1440: 13, 1920: 14, 2560: 15}[width]
                self.assertEqual(body["size"], "%dpx" % want)
                self.assertEqual(body["weight"], "400")
                self.assertAlmostEqual(float(body["line"][:-2]), want * 1.45, delta=0.05)

    def test_form_controls_take_the_page_s_face_and_colour(self):
        """A button no class dresses printed in the browser's Arial, in
        black: it takes the page's face, size and colour now. The fields
        keep the field rule's number face, which is JetBrains Mono now."""
        for (url, width), got in sorted(self.got.items()):
            for c in got["controls"]:
                with self.subTest(url=url, width=width, tag=c["tag"]):
                    if c["tag"] == "BUTTON":
                        self.assertEqual(c["family"], got["body"]["family"])
                        self.assertEqual(c["size"], got["body"]["size"])
                        self.assertEqual(c["color"], got["bodyColor"])
                    else:
                        self.assertTrue(c["family"].startswith('"JetBrains Mono"'), c)
                        self.assertEqual(c["color"], got["ink1"])

    def test_gains_jade_losses_coral_unknown_grey(self):
        got = self.got[("/command/", 1440)]
        self.assertEqual(got["up"], rgb(PALETTE["--sv-up"]))
        self.assertEqual(got["down"], rgb(PALETTE["--sv-down"]))
        self.assertEqual(got["flat"], rgb(PALETTE["--sv-ink-3"]))

    def test_real_is_white_on_the_real_red_at_11px(self):
        got = self.got[("/command/", 1440)]["real"]
        self.assertEqual(got["bg"], rgb(PALETTE["--sv-real"]))
        self.assertEqual(got["color"], "rgb(255, 255, 255)")
        self.assertGreaterEqual(float(got["size"][:-2]), 11)

    def test_no_ambient_layer_is_displayed(self):
        """Updated deliberately (the magic kept, 2026-11-12). /command/ and
        /positions/ opted into the embers: under Ambience Magic, in the dark
        theme, their canvas is displayed, and no other ambient layer is;
        under Calm and Off, and in light mode, none is. (A page that has
        not opted in: tests/test_magic_layer.py.)"""
        for (url, width), got in sorted(self.got.items()):
            with self.subTest(url=url, width=width):
                self.assertTrue(got["embers"])
                magic = dict(got["ambient"]["magic"])
                self.assertEqual(magic.pop("#particles-canvas"), "block")
                self.assertEqual(set(magic.values()), {"none"}, magic)
                for mode in ("calm", "off", "light"):
                    self.assertEqual(set(got["ambient"][mode].values()), {"none"},
                                     (mode, got["ambient"][mode]))

    def test_at_most_two_infinite_animations_and_only_the_meaningful_ones(self):
        """Nothing moves on a work page unless a value moved or he acted: the
        live heartbeat and the armed pill's beat may run, nothing else.
        Updated deliberately (the magic kept, 2026-11-12): under Ambience
        Magic one more may, the Eye's breath on the sidebar's mark (opacity
        and transform on one small layer); Calm and Off keep S1a's two; and
        under reduced motion nothing loops at all, in any Ambience."""
        beats = r"^(sv-heartbeat|sv-armed-beat)@"
        for (url, width), got in sorted(self.got.items()):
            with self.subTest(url=url, width=width):
                magic = got["anims"]["magic"]
                self.assertLessEqual(len(magic), 3, magic)
                breath = [a for a in magic if a.startswith("sv-eye-breath@")]
                self.assertEqual(len(breath), 1, magic)
                for a in magic:
                    if a not in breath:
                        self.assertRegex(a, beats, magic)
                for mode in ("calm", "off"):
                    self.assertLessEqual(len(got["anims"][mode]), 2, got["anims"][mode])
                    for a in got["anims"][mode]:
                        self.assertRegex(a, beats, got["anims"][mode])
        for (url, width), got in sorted(self.reduced.items()):
            with self.subTest(url=url, width=width, motion="reduced"):
                self.assertEqual(got, {"magic": [], "calm": [], "off": []})

    def test_light_mode_computes_today_s_colours(self):
        got = self.got[("/command/", 1440)]
        for name, want in LIGHT_TODAY.items():
            with self.subTest(token=name):
                self.assertEqual(got["light"][name].lower(), want)
        self.assertEqual(got["lightUp"], rgb("#00994d"))
        self.assertEqual(got["lightReal"], rgb("#e83030"))

    def test_light_mode_keeps_today_s_aliases_overlay_and_chips(self):
        """Light mode as origin/main computes it (2026-11-07): the aliases
        and the overlay's surfaces at their inherited values, a bullish chip
        on its light wash, the band's counts in the light accent, LIVE as
        a red word, the unknown dash at 65 %, PAPER in the light ink."""
        for (url, width), got in sorted(self.got.items()):
            if width != 1440:
                continue
            for name, want in sorted({**LIGHT_ALIASES_TODAY, **LIGHT_OVERLAY_TODAY}.items()):
                with self.subTest(url=url, token=name):
                    self.assertEqual(got["lightAliases"][name].lower(), want)
            els = got["lightEls"]
            with self.subTest(url=url, element="chips"):
                self.assertEqual((els["bull"]["color"], els["bull"]["bg"]),
                                 (rgb("#00994d"), rgb("#d0f0d8")))
                self.assertEqual((els["live"]["color"], els["live"]["bg"]),
                                 (rgb("#e83030"), "rgba(0, 0, 0, 0)"))
                self.assertEqual(els["unknown"]["opacity"], "0.65")
                self.assertEqual(els["paper"]["color"], rgb("#8aaa8a"))
                self.assertEqual(els["count"]["color"], rgb("#00994d"))
                # The washes behind a gain: the old Eye's green, as today.
                self.assertEqual(rgba_of(els["chg"]["bg"]), (0, 232, 104, 0.08))
                self.assertEqual(rgba_of(els["dir"]["bg"]), (0, 232, 104, 0.18))

    def test_the_review_s_states_in_the_dark_theme(self):
        """What the review of 2026-11-07 measured: a gain in the Horde's
        strip and in the close advice is jade, never the Eye; the blue chips
        are neutral ink (4.4:1 in the chart blue); a disabled BUY or SELL
        reads disabled; an idle-lock box that holds a digit keeps its Eye
        edge; the band's apart groups print at full strength."""
        for (url, width), got in sorted(self.got.items()):
            r = got["review"]
            with self.subTest(url=url, width=width):
                self.assertEqual(r["hordeUp"], rgb(PALETTE["--sv-up"]))
                self.assertEqual(r["toneUp"], rgb(PALETTE["--sv-up"]))
                self.assertEqual(r["adviceUp"], rgb(PALETTE["--sv-up"]))
                for chip in ("medium", "stock"):
                    self.assertEqual(r[chip]["color"], rgb(PALETTE["--sv-ink-2"]), chip)
                for btn in ("buyOff", "sellOff"):
                    self.assertEqual((r[btn]["color"], r[btn]["bg"], r[btn]["border"]),
                                     (rgb(PALETTE["--sv-ink-4"]), rgb(PALETTE["--sv-bg-2"]),
                                      rgb(PALETTE["--sv-line-1"])), btn)
                self.assertEqual(r["pinFilled"], rgb(PALETTE["--sv-eye"]))
                self.assertEqual(r["apart"], "1")

    def test_nothing_in_the_shell_is_under_11px(self):
        """The sidebar, the bars, the rail, the bottom band and every
        dropdown and card the shell carries (shown or waiting): 39-56 % of
        all text at 1280 px was under 11 px."""
        for (url, width), got in sorted(self.got.items()):
            with self.subTest(url=url, width=width):
                self.assertGreater(got["shellText"], 80)
                self.assertEqual(got["shellSmall"], [])

    def test_shell_text_meets_4_5_to_1_on_its_ground(self):
        for (url, width), got in sorted(self.got.items()):
            with self.subTest(url=url, width=width):
                self.assertEqual(got["shellLow"], [])

    def test_real_is_the_only_solid_red_behind_text(self):
        """No element that carries words or figures sits on a solid red, on
        the page or in the shell, but the REAL markers."""
        for (url, width), got in sorted(self.got.items()):
            with self.subTest(url=url, width=width):
                self.assertEqual(got["redFills"], [])

    def test_no_page_scrolls_sideways(self):
        for (url, width), got in sorted(self.got.items()):
            with self.subTest(url=url, width=width):
                self.assertEqual(got["docOverflowX"], 0)
