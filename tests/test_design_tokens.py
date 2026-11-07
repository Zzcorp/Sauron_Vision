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

Display only. Nothing here reaches an order, a stop, a size, a gate, a
switch or a broker; no network, no model.

The measured classes render pages through the test client from synthetic
rows and lay them out in a headless Chromium with every network URL
blocked (tests/test_close_advice.py's _Chrome); they skip, not fail, where
the machine has none. The node class runs the ambient scripts of base.html
under node with a stubbed page; it skips where node is missing.

Run with:  python manage.py test tests.test_design_tokens
"""
import json
import pathlib
import re
import subprocess
import tempfile
import unittest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase

from tests.test_close_advice import CHROME, HOST, NODE, _quote
from tests.test_ui_s0_fixes import _get, _measure

ROOT = pathlib.Path(settings.BASE_DIR)
TOKENS = "static/css/sv-tokens.css"
KIT = "static/css/sv-kit.css"
SAURON = "static/css/sauron.css"
BASE = "templates/base.html"

#: §4.1, checked live: the words and numbers faces, and the wordmark's
#: subset. Nothing else is fetched for type.
FONT_LINKS = (
    "https://fonts.googleapis.com/css2?family=Inter:opsz,wght@14..32,400..700"
    "&family=JetBrains+Mono:wght@400..700&display=swap",
    "https://fonts.googleapis.com/css2?family=Orbitron:wght@700"
    "&text=SAURON%20VISION&display=swap",
)

#: §3: the approved palette (the preview of 2026-11-06).
PALETTE = {
    "--sv-bg-0": "#070A09", "--sv-bg-1": "#0C1110", "--sv-bg-2": "#121918",
    "--sv-bg-3": "#182120", "--sv-bg-4": "#1F2A28",
    "--sv-line-1": "#1B2422", "--sv-line-2": "#26322F", "--sv-line-3": "#36443F",
    "--sv-ink-1": "#E9EFED", "--sv-ink-2": "#B4C0BC", "--sv-ink-3": "#8A9894",
    "--sv-ink-4": "#59655F",
    "--sv-eye": "#00E868",
    "--sv-up": "#24B582", "--sv-down": "#FF6B6E",
    "--sv-up-fill": "#1FA374", "--sv-down-fill": "#E5484D",
    "--sv-real": "#CC3A40", "--sv-real-ink": "#FFFFFF", "--sv-demo": "#D6BC5E",
    "--sv-warn": "#F29B38", "--sv-ai": "#A48BFF",
    "--sv-cat-1": "#3987E5", "--sv-cat-2": "#D95926", "--sv-cat-3": "#9085E9",
    "--sv-cat-4": "#C98500", "--sv-cat-5": "#D55181",
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

#: The ambient layers of base.html, none displayed on a work page.
AMBIENT = (".grid-bg", ".eye-glow-shadow", ".globe-eye-bg",
           ".globe-circuits-bg", "#particles-canvas", "#caustics-canvas",
           ".se-cs-paragraph")

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
        for gone in ("Rajdhani", "Share+Tech+Mono",
                     "Orbitron:wght@400;500;600;700;800;900"):
            self.assertNotIn(gone, base)

    def test_no_other_font_host_in_the_shell(self):
        """base.html and every sheet it links: type comes from Google Fonts
        only, through the two links above (no @import, no @font-face with a
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

    def test_a_page_that_names_a_retired_face_loads_it_itself(self):
        """The shell stopped loading Rajdhani, Share Tech Mono and the full
        Orbitron (§4.1). A page under base.html that names one in its own
        styles (not as a var() fallback) loads it itself, from Google Fonts:
        /passation/'s letter fell back to the system faces, and "TO
        GANDALF" mixed the wordmark subset's eight Orbitron letters with
        fallback ones (review, 2026-11-07)."""
        retired = {"Rajdhani": "Rajdhani", "Share Tech Mono": "Share+Tech+Mono",
                   "Orbitron": "Orbitron"}
        offenders, named = [], 0
        for path in sorted((ROOT / "templates").rglob("*.html")):
            text = path.read_text(encoding="utf-8")
            if '{% extends "base.html" %}' not in text:
                continue
            links = re.findall(r'href="https://fonts\.googleapis\.com/css2\?([^"]+)"', text)
            for face, family in retired.items():
                if not re.search(r"""font-family:\s*['"]%s['"]""" % face, text):
                    continue
                named += 1
                if not any(re.search(r"(^|&|amp;)family=%s(:|&|$)" % re.escape(family), l)
                           for l in links):
                    offenders.append("%s names %s" % (path.relative_to(ROOT), face))
        self.assertGreater(named, 0)
        self.assertEqual(offenders, [])

    def test_the_faces_are_tokens_with_their_fallbacks(self):
        root = block(read(TOKENS), ":root")
        self.assertEqual(root["--sv-font-sans"],
                         '"Inter", system-ui, -apple-system, "Segoe UI", Roboto, sans-serif')
        self.assertEqual(root["--sv-font-mono"],
                         '"JetBrains Mono", ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace')
        self.assertTrue(root["--sv-font-brand"].startswith('"Orbitron"'))

    def test_the_old_names_read_the_new_tokens(self):
        root = block(read(SAURON), ":root")
        for old, (new, was) in REPOINTED.items():
            with self.subTest(token=old):
                self.assertEqual(root.get(old), "var(%s, %s)" % (new, was))

    def test_the_wordmark_keeps_orbitron(self):
        """Orbitron stays on the wordmark only: the subset carries SAURON
        VISION and nothing else, so the brand rule names --sv-font-brand."""
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


class AmbientSourceTests(SimpleTestCase):

    def test_the_ambient_layers_are_not_displayed_on_work_pages(self):
        found = [b for p, b, c in rules(read(SAURON))
                 if all(a in p for a in AMBIENT)]
        self.assertTrue(found, "no rule hides the ambient layers")
        self.assertIn(("display", "none !important"), decls(found[0]))

    def test_the_particles_carry_no_tickers_and_no_prices(self):
        script = _script_with("getElementById('particles-canvas')")
        for gone in ("TICKERS", "tickerPrice", "fillText", "EUR/USD", "base:67500"):
            self.assertNotIn(gone, script)


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
        last_variant = max(i for i, p in enumerate(order) if ".btn.btn-buy" in p or ".btn.btn-stop" in p)
        disabled = [i for i, p in enumerate(order) if "[disabled]" in p and ".btn-buy" in p]
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
# The ambient loops, run under node with a stubbed page
# ══════════════════════════════════════════════════════════════════════════

NODE_HARNESS = r"""
const vm = require('vm');
const fs = require('fs');
const [particles, caustics] = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = {};
for (const [hidden, reduced] of [[false, false], [true, false], [false, true]]) {
  let raf = 0, intervals = 0, clockText = null;
  const el = () => ({ style: {}, width: 0, height: 0,
                      getContext: () => new Proxy({}, { get: (t, k) => (k in t ? t[k] : () => ({ addColorStop() {} })), set: (t, k, v) => { t[k] = v; return true; } }),
                      getAttribute: () => 'UTC', set textContent(v) { clockText = v; } });
  const nodes = { 'particles-canvas': el(), 'caustics-canvas': el(), clock: el() };
  const ctx = {
    window: null, Math, Intl, Date, JSON, console,
    performance: { now: () => 1000 },
    document: {
      getElementById: id => nodes[id] || null,
      querySelector: () => el(),
      addEventListener: () => {},
    },
    getComputedStyle: () => ({ display: hidden ? 'none' : 'block' }),
    matchMedia: q => ({ matches: reduced && /reduce/.test(q) }),
    requestAnimationFrame: () => { raf++; return raf; },
    setInterval: () => { intervals++; return 1; },
    setTimeout: () => 1,
  };
  ctx.window = ctx;
  ctx.window.innerWidth = 1440; ctx.window.innerHeight = 900;
  ctx.window.addEventListener = () => {};
  vm.createContext(ctx);
  vm.runInContext(particles, ctx);
  const afterParticles = raf;
  vm.runInContext(caustics, ctx);
  out[(hidden ? 'hidden' : 'shown') + (reduced ? '+reduced' : '')] =
    { particlesRaf: afterParticles, causticsRaf: raf - afterParticles, intervals, clock: clockText };
}
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "node is not on this machine")
class AmbientGuardNodeTests(SimpleTestCase):
    """The particle, parallax and caustics loops of base.html, run as they
    ship: they start where their layer is displayed and no reduced motion is
    asked, and return before scheduling a single frame otherwise. The clock
    in the same script runs either way."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        scripts = [_script_with("getElementById('particles-canvas')"),
                   _script_with("getElementById('caustics-canvas')")]
        with tempfile.TemporaryDirectory() as tmp:
            data = pathlib.Path(tmp) / "scripts.json"
            data.write_text(json.dumps(scripts), encoding="utf-8")
            harness = pathlib.Path(tmp) / "harness.js"
            harness.write_text(NODE_HARNESS, encoding="utf-8")
            done = subprocess.run([NODE, str(harness), str(data)], capture_output=True,
                                  text=True, timeout=60)
        if done.returncode:
            raise AssertionError(done.stderr)
        cls.got = json.loads(done.stdout)

    def test_the_loops_run_where_the_layer_shows(self):
        shown = self.got["shown"]
        self.assertGreater(shown["particlesRaf"], 0, shown)
        self.assertGreater(shown["causticsRaf"], 0, shown)

    def test_no_frame_is_scheduled_for_a_hidden_layer(self):
        hidden = self.got["hidden"]
        self.assertEqual((hidden["particlesRaf"], hidden["causticsRaf"]), (0, 0), hidden)

    def test_no_frame_is_scheduled_under_reduced_motion(self):
        reduced = self.got["shown+reduced"]
        self.assertEqual((reduced["particlesRaf"], reduced["causticsRaf"]), (0, 0), reduced)

    def test_the_clock_still_ticks(self):
        for state, got in self.got.items():
            with self.subTest(state=state):
                self.assertEqual(got["intervals"], 1)
                self.assertRegex(got["clock"] or "", r"^\d\d:\d\d:\d\d UTC$")


#: The code-stream's block of base.html (Ask Sauron's script), from its
#: comment to its two loops, run alone with a stubbed page.
CODE_STREAM_HARNESS = r"""
const vm = require('vm');
const fs = require('fs');
const block = fs.readFileSync(process.argv[2], 'utf8');
const out = {};
for (const [hidden, reduced] of [[false, false], [true, false], [false, true]]) {
  let timers = 0;
  const para = () => ({ childNodes: [], appendChild(n) { this.childNodes.push(n); return n; },
                        removeChild() {}, get firstChild() { return this.childNodes[0]; } });
  const nodes = { seCsParaLeft: para(), seCsParaRight: para() };
  const ctx = {
    Math, Date, Promise, console,
    window: { matchMedia: q => ({ matches: reduced && /reduce/.test(q) }) },
    document: { getElementById: id => nodes[id] || null,
                createElement: () => ({ appendChild() {}, set className(v) {}, textContent: '' }) },
    getComputedStyle: () => ({ display: hidden ? 'none' : 'block' }),
    setTimeout: () => { timers++; return timers; },
  };
  vm.createContext(ctx);
  vm.runInContext('(function () {' + block + '})();', ctx);
  out[(hidden ? 'hidden' : 'shown') + (reduced ? '+reduced' : '')] = { timers };
}
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "node is not on this machine")
class CodeStreamGuardNodeTests(SimpleTestCase):
    """The two code-stream paragraphs type fake log lines (fake R values,
    fake prices) letter by letter, on timers. S1a hides them on work pages,
    and they went on typing into the hidden nodes: 167 timer callbacks in
    6 s on /command/ (review, 2026-11-07). Like the other ambient loops,
    they start only where their layer is displayed and no reduced motion
    is asked."""

    START = "// ── Ambient code-stream"
    END = "loop(streamRight, 1100);\n    }"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = read(BASE)
        i = base.index(cls.START)
        cls.block = base[i:base.index(cls.END, i) + len(cls.END)]
        with tempfile.TemporaryDirectory() as tmp:
            data = pathlib.Path(tmp) / "block.js"
            data.write_text(cls.block, encoding="utf-8")
            harness = pathlib.Path(tmp) / "harness.js"
            harness.write_text(CODE_STREAM_HARNESS, encoding="utf-8")
            done = subprocess.run([NODE, str(harness), str(data)], capture_output=True,
                                  text=True, timeout=60)
        if done.returncode:
            raise AssertionError(done.stderr)
        cls.got = json.loads(done.stdout)

    def test_the_stream_types_where_it_shows(self):
        self.assertEqual(self.got["shown"]["timers"], 2, self.got)

    def test_no_timer_for_a_hidden_stream(self):
        self.assertEqual(self.got["hidden"]["timers"], 0, self.got)

    def test_no_timer_under_reduced_motion(self):
        self.assertEqual(self.got["shown+reduced"]["timers"], 0, self.got)

    def test_the_guard_reads_the_layer_s_display(self):
        self.assertIn("getComputedStyle(streamLeft).display !== 'none'", self.block)


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
    out.ambient = {};
    %(ambient)s.forEach(function (s) {
        var e = document.querySelector(s);
        out.ambient[s] = e ? getComputedStyle(e).display : 'absent';
    });
    out.anims = document.getAnimations().filter(function (a) {
        var t = a.effect && a.effect.getComputedTiming();
        return a.playState === 'running' && t && t.iterations === Infinity;
    }).map(function (a) { return a.animationName + '@' + (a.effect.target.className && a.effect.target.className.baseVal !== undefined ? a.effect.target.className.baseVal : a.effect.target.className); });
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
    var AMB = '.grid-bg, .eye-glow-shadow, .globe-eye-bg, .globe-circuits-bg, #particles-canvas, #caustics-canvas, .se-cs-paragraph';
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
        for (url, width), got in sorted(self.got.items()):
            with self.subTest(url=url, width=width):
                self.assertEqual(set(got["ambient"].values()) - {"absent"}, {"none"},
                                 got["ambient"])
                self.assertNotIn("absent", [got["ambient"][s] for s in AMBIENT[:6]])

    def test_at_most_two_infinite_animations_and_only_the_meaningful_ones(self):
        """Nothing moves on a work page unless a value moved or he acted: the
        live heartbeat and the armed pill's beat may run, nothing else."""
        for (url, width), got in sorted(self.got.items()):
            with self.subTest(url=url, width=width):
                self.assertLessEqual(len(got["anims"]), 2, got["anims"])
                for a in got["anims"]:
                    self.assertRegex(a, r"^(sv-heartbeat|sv-armed-beat)@", got["anims"])

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
