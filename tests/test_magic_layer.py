"""The magic kept: Sauron's theme inside the approved look (UI plan S1a,
2026-11-12).

The operator approved S1a's look and asked to keep Sauron's own theme: "the
magic, the prestige". This layer brings it back in the frame and never on
the data:

  * THE EYE-LIT LADDER: the twelve neutrals take the Eye's hue at S1a's own
    lightness, so no contrast moves (tests/test_design_tokens computes them).
  * THE FACES: Orbitron on the frame's titles, loaded without digits so a
    digit in a title is always drawn in JetBrains Mono; Rajdhani on the nav
    rows; never a money word (BUY, SELL, REAL, LONG, SHORT) in Orbitron.
  * LIGHT ON WHAT LIVES: the wordmark, the Eye, the active row, live dots,
    the selected tab, a hero card while its figure is live. Never a figure,
    never REAL, never the Eye's green on a control that moves money; a BUY
    or a SELL lights in its own side's colour, inside its own box, on hover
    and focus only. Off is S1a exactly.
  * THE VOID: light from above, a vignette and a grain on two fixed
    composited layers behind opaque cards; no figure on the void or on a
    translucent ground.
  * CALM EMBERS on the pages that opt in (static/js/sv-embers.js; its node
    harness is in tests/test_design_tokens.py), and MOMENTS for proven
    events only (static/js/sv-moments.js): the Eye flares for a fill the
    payload or this tab's own answer proves, a light runs under the new
    row, a new signal's card and the rail's icon light once.

Display only. Nothing here reaches an order, a stop, a size, a gate, a
switch or a broker; no network, no model. Every row is synthetic.

The node classes run the scripts as they ship with a stubbed page; the
measured classes lay synthetic pages out in a headless Chromium with every
network URL blocked. Both skip, not fail, where the machine has no node or
no Chromium.

Run with:  python manage.py test tests.test_magic_layer
"""
import base64
import io
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest
import urllib.parse
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase

from tests.test_close_advice import CHROME, HOST, NODE, _Chrome, _legacy, _quote, _trade
from tests.test_design_tokens import (BASE, KIT, PALETTE, S1A_LADDER, SAURON, TOKENS,
                                      block, contrast, decls, hex_rgb, oklab, read, rules,
                                      strip_comments)
from tests.test_ui_s0_fixes import _get, _offline

ROOT = pathlib.Path(settings.BASE_DIR)
EMBERS = "static/js/sv-embers.js"
MOMENTS = "static/js/sv-moments.js"
KIT_PAGE = "templates/dashboard/design_kit.html"

#: The scopes of the light (C3): the dark theme, under Magic and Calm; and
#: what moves, under Magic alone.
LIT = 'body:not(.light-mode):is([data-sv-ambience="magic"], [data-sv-ambience="calm"])'
MAGIC = 'body:not(.light-mode)[data-sv-ambience="magic"]'

#: The only colours light may take: the Eye and its pale core, jade, coral.
EYE_RGB, PALE_RGB, UP_RGB, DOWN_RGB = (0, 232, 104), (120, 255, 180), (36, 181, 130), (255, 107, 110)

#: What prints a figure, what is a button, what is a chip (C2, C3).
FIGURE_CLASSES = (".sv-num", ".mono", "td.num", ".sv-kpi-value", ".stat-value",
                  ".metric-value", ".dv", ".ip-pnl", ".dh-val", ".dh-chg", ".wl-sym",
                  ".sr-sym", ".pos-pop-sym", ".gate-key", ".tk-px")
BUTTON_CLASSES = (".btn", ".sr-pop-btn", ".sv-dialog-btn")
CHIP_CLASSES = (".sv-chip", ".sv-world", ".sv-side")

#: The frame: the only selectors that take the display face (C2).
DISPLAY_FACE = (".sidebar-brand h1", ".topbar-title", ".card-title", ".sv-panel-title",
                ".sc-heading-title", ".modal-title", ".kbd-modal-title",
                ".gollum-dialog .gl-title", ".nav-section", ".il-title", ".sv-overline")
#: The hand-over letter's own titles, in its own styles: the card every
#: page carries while a hand-over is due, and the letter's page.
DISPLAY_FACE_PAGES = {
    "templates/_partials/passation_card.html": (".sv-passation-kicker",),
    "templates/dashboard/passation.html": (".pass-title", ".pass-body p.first::first-letter",
                                           ".pass-sign", ".pass-h"),
}
FRAME_FACE = (".nav-link", ".sidebar-brand .subtitle")

#: The world family (§3.5): REAL is a fill, never a light.
WORLD_FAMILY = (".sv-world--live", ".sv-armed-pill", ".tk-venue--live", ".sv-venue--live",
                ".sv-row--live", ".sv-adv-world.is-live", ".pos-pop-venue.is-live",
                ".hq-tag--live", ".hq-brk--live", ".ib-env--live", ".bk-env--live",
                ".hq-acct--live")
#: What a hero card may never hold (C3).
HERO_DARK = (".sv-world--live", ".sv-venue--live", ".tk-venue--live", ".sv-armed-pill",
             ".sv-adv-world.is-live", ".pos-pop-venue.is-live", ".hq-tag--live",
             ".hq-brk--live", ".ib-env--live", ".bk-env--live")
HERO_STALE = (".sv-fresh--stale", ".sv-fresh--closed", ".sv-fresh--ref", ".sv-est")

#: A money word is the word alone: "real-time" and "long-term" are not one.
MONEY_WORD = re.compile(r"(?<![\w-])(BUY|SELL|REAL|LONG|SHORT)(?![\w-])", re.I)


def colours(value):
    """Every (r, g, b) a CSS value names as rgb()/rgba()."""
    return [tuple(int(float(x)) for x in m.group(1).split(",")[:3])
            for m in re.finditer(r"rgba?\(([^)]+)\)", value)]


def layers(value):
    """A shadow list, split at the commas outside brackets."""
    out, depth, cur = [], 0, []
    for ch in value:
        depth += ch == "("
        depth -= ch == ")"
        if ch == "," and depth == 0:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur).strip())
    return [l for l in out if l]


def selectors(prelude):
    """A prelude's selectors, split at the commas outside brackets."""
    return layers(prelude)


def kit_rules():
    return rules(read(KIT))


def under_base():
    """The templates rendered under base.html: base.html, every template
    that extends it, and the partials they include (by name, transitively).
    A standalone page (its own <html>) and what only it includes are not."""
    root = ROOT / "templates"
    text = {p: p.read_text(encoding="utf-8") for p in root.rglob("*.html")}
    seen, queue = set(), [p for p, t in text.items()
                          if p == ROOT / BASE or re.search(r'\{% extends (base_template\|default:)?"base\.html" %\}', t)]
    while queue:
        p = queue.pop()
        if p in seen:
            continue
        seen.add(p)
        for name in re.findall(r"""\{% include ["']([^"']+)["']""", text[p]):
            if root / name in text:
                queue.append(root / name)
    return {str(p.relative_to(ROOT)): text[p] for p in sorted(seen)}


def style_rules(markup):
    """The rules of every <style> block of a template."""
    out = []
    for css in re.findall(r"<style\b[^>]*>(.*?)</style>", markup, flags=re.S):
        out.extend(rules(re.sub(r"\{[%#].*?[%#]\}", "", css, flags=re.S)))
    return out


def unfallback(value):
    """A value without what sits in a var()'s fallback: var(--x, 'Orbitron')
    names no face of its own."""
    prev = None
    while prev != value:
        prev = value
        value = re.sub(r"var\(\s*(--[\w-]+)\s*,[^()]*(\([^()]*\)[^()]*)*\)", r"var(\1)", value)
    return value


# ══════════════════════════════════════════════════════════════════════════
# C1. The tokens: the ladder and the light
# ══════════════════════════════════════════════════════════════════════════

class EyeLitTokenTests(SimpleTestCase):

    def setUp(self):
        self.root = block(read(TOKENS), ":root")

    def test_the_eye_lit_ladder_keeps_s1a_lightness(self):
        """Every neutral keeps S1a's OKLab lightness within 0.003, so no
        contrast can drift; its hue is the Eye's family (150-170) and its
        chroma at most 0.045."""
        import math
        for name, was in S1A_LADDER.items():
            with self.subTest(token=name):
                old, new = oklab(was), oklab(PALETTE[name])
                self.assertLess(abs(new[0] - old[0]), 0.003)
                hue = math.degrees(math.atan2(new[2], new[1])) % 360
                self.assertTrue(150 <= hue <= 170, hue)
                self.assertLessEqual(math.hypot(new[1], new[2]), 0.045)

    def test_the_minimum_contrast_is_still_ink_3_on_bg_4(self):
        low = min((contrast(PALETTE[i], PALETTE[s]), i, s)
                  for i in ("--sv-ink-1", "--sv-ink-2", "--sv-ink-3")
                  for s in ("--sv-bg-0", "--sv-bg-1", "--sv-bg-2", "--sv-bg-3", "--sv-bg-4"))
        self.assertEqual(low[1:], ("--sv-ink-3", "--sv-bg-4"))
        self.assertGreaterEqual(low[0], 4.9)

    def test_light_is_the_eye_or_a_side_only(self):
        """Every glow, edge and spill token uses the Eye, its pale core,
        jade or coral, and nothing else: never --sv-real, never another
        red. A side's light is inset only: it stays inside its control."""
        light = {k: v for k, v in self.root.items()
                 if re.match(r"--sv-(glow|edge|spill)-", k)}
        for want in ("--sv-glow-brand-text", "--sv-glow-edge", "--sv-glow-dot", "--sv-glow-up-in",
                     "--sv-glow-down-in", "--sv-glow-up-ring", "--sv-glow-down-ring",
                     "--sv-spill-active", "--sv-edge-hero"):
            self.assertIn(want, light)
        for name, value in light.items():
            with self.subTest(token=name):
                self.assertNotIn("--sv-real", value)
                self.assertNotRegex(value, r"#[0-9a-fA-F]{3,8}\b")
                for c in colours(value):
                    self.assertIn(c, (EYE_RGB, PALE_RGB, UP_RGB, DOWN_RGB))
        for name, colour in (("--sv-glow-up-in", UP_RGB), ("--sv-glow-down-in", DOWN_RGB),
                             ("--sv-glow-up-ring", UP_RGB), ("--sv-glow-down-ring", DOWN_RGB)):
            for layer in layers(light[name]):
                with self.subTest(token=name, layer=layer):
                    self.assertTrue(layer.startswith("inset "), layer)
                    self.assertEqual(colours(layer), [colour])
        # The ring a figure's button takes is the inset light's own first
        # layer, alone: a 1 px line, no blur.
        for ring, light_in in (("--sv-glow-up-ring", "--sv-glow-up-in"), ("--sv-glow-down-ring", "--sv-glow-down-in")):
            with self.subTest(token=ring):
                self.assertEqual(layers(light[ring]), layers(light[light_in])[:1])
                self.assertRegex(light[ring], r"^inset 0 0 0 1px rgba\(")

    def test_no_text_glow_token_but_the_brand(self):
        """One text may glow, the wordmark. The kit sets no other
        text-shadow but none and the dark halo of words on the void, which
        is a shade in bg-0, not a light."""
        self.assertEqual([k for k in self.root if "glow" in k and "text" in k],
                         ["--sv-glow-brand-text"])
        halo = "0 0 3px var(--sv-bg-0), 0 0 8px var(--sv-bg-0), 0 0 14px var(--sv-bg-0)"
        for prelude, body, ctx in kit_rules():
            for prop, value in decls(body):
                if prop != "text-shadow":
                    continue
                with self.subTest(rule=prelude):
                    self.assertIn(value, ("none", "var(--sv-glow-brand-text)", halo))
                    if value == "var(--sv-glow-brand-text)":
                        self.assertEqual(selectors(prelude), [LIT + " .sidebar-brand h1"])
                    if value == halo:
                        self.assertEqual(selectors(prelude), ["body:not(.light-mode) .sv-on-void"])

    def test_no_primary_or_focus_glow_token(self):
        """v1's primary-button glow and focus halo are not built: the
        primary button is also the PIN-guarded TURN ON that arms real money,
        and a halo on a focused money control would be the Eye's green on
        it. The focus light stays S1a's 2 px outline."""
        for gone in ("--sv-glow-primary", "--sv-glow-focus"):
            self.assertNotIn(gone, self.root)
            self.assertNotIn(gone, read(KIT))
        for prelude, body, ctx in kit_rules():
            if ".btn-primary" not in prelude and ".btn-danger" not in prelude \
                    and ".sv-dialog-btn" not in prelude:
                continue
            for prop, value in decls(body):
                with self.subTest(rule=prelude, prop=prop):
                    if prop in ("box-shadow", "text-shadow", "filter"):
                        self.assertEqual(value, "none")
                    self.assertNotIn("--sv-glow", value)
        focus = block(read(KIT), ":is(a, button, [tabindex], summary, .btn):focus-visible")
        self.assertEqual(focus, {"outline": "2px solid var(--sv-eye)", "outline-offset": "2px"})

    def test_the_void_and_the_motion_tokens(self):
        """Two lights from above. Updated deliberately (2026-11-13, the
        check of CR2): the Eye's light that reaches the page (the
        operator's brief, "magique dans l'esprit de Sauron, high end et
        financier", and his decision on the review's CR2: 1000 x 420 px
        centred 150 px down, it lights the empty page just under the chrome
        and is gone by y = 460) is fixed to the window, so it lies under
        whatever a page puts there, at any scroll. On five pages the
        commit never measured, figures on the void took it (+4 to +7
        levels). It is --sv-void-light-reach now, worn only by a page
        proven to put no figure on the void (sv-kit.css, the void); every
        other page keeps C1's light, --sv-void-light again: 900 x 360 px
        centred 110 px above the window, it fades out at y = 156 px, under
        the chrome, and adds nothing to the page (LightFromAboveMeasuredTests
        reads every page of the nav)."""
        r = self.root
        self.assertEqual(r["--sv-void-light"],
                         "radial-gradient(900px 360px at 46% -110px, rgba(0,232,104,.10), "
                         "rgba(0,232,104,.025) 50%, rgba(0,232,104,0) 74%)")
        self.assertEqual(r["--sv-void-light-reach"],
                         "radial-gradient(1000px 420px at 46% 150px, rgba(0,232,104,.06), "
                         "rgba(0,232,104,.02) 50%, rgba(0,232,104,0) 74%)")
        self.assertIn("rgba(0,0,0,.42)", r["--sv-void-vignette"])
        self.assertIn("feTurbulence", r["--sv-void-grain"])
        self.assertEqual(r["--sv-grain-opacity"], ".07")
        self.assertEqual((r["--sv-dur-breath"], r["--sv-dur-moment"], r["--sv-dur-sweep"]),
                         ("6s", "1200ms", "900ms"))

    def test_light_mode_carries_no_light(self):
        """Light mode is frozen: its block names no glow, edge, spill or
        void token, and no rule of the kit lights anything under it."""
        light = block(read(TOKENS), "body.light-mode")
        self.assertEqual([k for k in light if re.match(r"--sv-(glow|edge|spill|void|grain)", k)], [])
        for prelude, body, ctx in kit_rules():
            if "--sv-glow" in body or "--sv-edge-hero" in body or "--sv-spill" in body \
                    or "--sv-void" in body:
                for sel in selectors(prelude):
                    with self.subTest(selector=sel):
                        self.assertTrue(sel.startswith("body:not(.light-mode)"), sel)


# ══════════════════════════════════════════════════════════════════════════
# C2. The faces: Orbitron on the frame only, Rajdhani on the nav
# ══════════════════════════════════════════════════════════════════════════

class FrameFaceTests(SimpleTestCase):

    def faces(self):
        """(where, selector, value) for every font-family or font
        declaration of the two sheets and of every <style> block of the
        templates rendered under base.html; and (where, value) for every
        style="" attribute that names a face."""
        found, inline = [], []
        for rel in (SAURON, KIT):
            for prelude, body, ctx in rules(read(rel)):
                if prelude.startswith(":root"):
                    continue
                for prop, value in decls(body):
                    if prop in ("font-family", "font"):
                        found.extend((rel, s, value) for s in selectors(prelude))
        for rel, markup in under_base().items():
            for prelude, body, ctx in style_rules(markup):
                for prop, value in decls(body):
                    if prop in ("font-family", "font"):
                        found.extend((rel, s, value) for s in selectors(prelude))
            for style in re.findall(r'\bstyle="([^"]*)"', markup):
                if re.search(r"font(-family)?\s*:", style):
                    inline.append((rel, style))
        return found, inline

    def test_the_display_face_is_on_the_frame_only(self):
        """Orbitron reaches a page through the display token alone, and the
        token sits on the frame's titles and nowhere else: never a figure,
        a button or a chip."""
        found, inline = self.faces()
        self.assertGreater(len(found), 200)
        used = set()
        for rel, sel, value in found:
            bare = unfallback(value)
            with self.subTest(file=rel, selector=sel):
                self.assertNotRegex(bare, r"Orbitron")
                if "--sv-font-display" in bare or "--sv-font-brand" in bare:
                    allowed = DISPLAY_FACE + DISPLAY_FACE_PAGES.get(rel, ())
                    self.assertIn(sel, allowed)
                    used.add(sel)
        for rel, style in inline:
            with self.subTest(file=rel, style=style[:60]):
                self.assertNotRegex(unfallback(style), r"Orbitron|--sv-font-(display|brand)")
        self.assertEqual(sorted(set(DISPLAY_FACE) - used), [])
        for sel in DISPLAY_FACE + sum(DISPLAY_FACE_PAGES.values(), ()):
            for cls in FIGURE_CLASSES + BUTTON_CLASSES + CHIP_CLASSES:
                with self.subTest(selector=sel, never=cls):
                    self.assertNotRegex(sel, re.escape(cls) + r"(?![\w-])")

    def test_rajdhani_is_on_the_nav_rows_and_the_subtitle_only(self):
        found, inline = self.faces()
        used = set()
        for rel, sel, value in found:
            bare = unfallback(value)
            with self.subTest(file=rel, selector=sel):
                self.assertNotRegex(bare, r"Rajdhani|Share Tech")
                if "--sv-font-frame" in bare:
                    self.assertIn(sel, FRAME_FACE)
                    used.add(sel)
        for rel, style in inline:
            with self.subTest(file=rel, style=style[:60]):
                self.assertNotRegex(unfallback(style), r"Rajdhani|Share Tech|--sv-font-frame")
        self.assertEqual(sorted(used), sorted(FRAME_FACE))

    def test_the_display_rule(self):
        kit = read(KIT)
        rule = block(kit, ",\n".join(DISPLAY_FACE))
        self.assertEqual(rule, {"font-family": "var(--sv-font-display)", "font-weight": "600",
                                "text-transform": "uppercase",
                                "letter-spacing": "var(--sv-track-display)"})
        root = block(read(TOKENS), ":root")
        self.assertEqual(root["--sv-font-display"], '"Orbitron", "JetBrains Mono", "Inter", sans-serif')
        self.assertEqual(root["--sv-font-frame"], '"Rajdhani", "Inter", sans-serif')
        self.assertEqual(root["--sv-font-brand"], "var(--sv-font-display)")
        self.assertEqual(root["--sv-fs-nav"], "calc(var(--sv-fs-base) + 2px)")
        self.assertEqual(block(kit, ".il-title")["font-weight"], "900")
        nav = block(kit, ".nav-link")
        self.assertEqual((nav["font-family"], nav["font-size"], nav["border-left-width"]),
                         ("var(--sv-font-frame)", "var(--sv-fs-nav)", "2px"))
        plain = block(kit, ".sv-plain,\n.topbar-title .pd-title-long")
        self.assertEqual(plain["font-family"], "var(--sv-font-sans)")

    def test_the_brand_s_subtitle_ends_under_the_wordmark(self):
        """Updated deliberately (2026-11-12): the operator's brief and his
        decision on the review's CR7. Spaced at C2's .3em, "TRADING
        INTELLIGENCE" ran 34 px past SAURON, out of the lockup. At .15em
        it ends under the wordmark's last letter (measured with the
        production faces: 0.1 px apart). The face and the size stay C2's,
        in both themes, as C2 built them: light mode's colours are not
        touched."""
        sub = block(read(KIT), ".sidebar-brand .subtitle")
        self.assertEqual((sub["font-family"], sub["font-weight"], sub["font-size"], sub["letter-spacing"]),
                         ("var(--sv-font-frame)", "600", "12px", ".15em"))

    def test_the_lock_s_clock_is_a_figure_and_its_words_reach_11px(self):
        css = read(SAURON)
        clock = block(css, ".il-clock")
        self.assertTrue(clock["font-family"].startswith("var(--sv-font-mono"), clock)
        self.assertEqual(clock["font-weight"], "400")
        for sel in (".il-sub", ".il-standby"):
            self.assertEqual(block(css, sel)["font-size"], "11px", sel)

    def test_no_money_word_in_orbitron(self):
        """BUY, SELL, REAL, LONG and SHORT never print in the display face:
        in a page title, a card title or a panel title, the word wears the
        word face (.sv-plain). Static, over what the templates spell out;
        the measured class reads what the pages compute."""
        titles = re.compile(r'<(\w+)\b[^>]*class="[^"]*\b(card-title|sv-panel-title|sc-heading-title|'
                            r'modal-title|kbd-modal-title|gl-title|nav-section|il-title|sv-overline)\b'
                            r'[^"]*"[^>]*>')

        def inner(markup, m):
            """What the element holds, its own tag nested or not."""
            depth = 1
            for t in re.finditer(r"<(/?)%s\b" % m.group(1), markup[m.end():]):
                depth += -1 if t.group(1) else 1
                if depth == 0:
                    return markup[m.end():m.end() + t.start()]
            return markup[m.end():m.end() + 400]

        def spelt(markup):
            markup = re.sub(r'<(\w+) class="sv-plain">.*?</\1>', " ", markup, flags=re.S)
            markup = re.sub(r"<[^>]+>", " ", markup)
            return re.sub(r"\{[%{].*?[%}]\}", " ", markup, flags=re.S)

        offenders, read_titles = [], 0
        for rel, markup in under_base().items():
            for m in re.finditer(r"\{% block page_title %\}(.*?)\{% endblock", markup, re.S):
                read_titles += 1
                # A side printed from a variable is a money word too.
                if MONEY_WORD.search(spelt(m.group(1))) or re.search(
                        r"\{\{[^}]*\b(side|direction)\b[^}]*\}\}",
                        re.sub(r'<(\w+) class="(sv-plain|pd-title-long)">.*?</\1>', " ", m.group(1), flags=re.S)):
                    offenders.append("%s page title: %s" % (rel, m.group(1).strip()[:70]))
            for m in titles.finditer(markup):
                read_titles += 1
                held = inner(markup, m)
                if MONEY_WORD.search(spelt(held)):
                    offenders.append("%s .%s: %s" % (rel, m.group(2), held.strip()[:70]))
        self.assertGreater(read_titles, 300)
        self.assertEqual(offenders, [])
        self.assertIn('<span class="sv-plain">{% if orc.side == "BUY" %}LONG{% else %}SHORT{% endif %}</span>',
                      read("templates/dashboard/orc_detail.html"))


# ══════════════════════════════════════════════════════════════════════════
# C3. Light on the frame, never on a figure, never on REAL
# ══════════════════════════════════════════════════════════════════════════

#: Who may wear a glow token (C3's whitelist), by the token.
LIGHT_SOURCES = {
    "--sv-glow-brand-text": (LIT + " .sidebar-brand h1",),
    "--sv-glow-edge": (LIT + " .nav-link.active::after",),
    "--sv-spill-active": (LIT + " .nav-link.active",),
    "--sv-glow-dot": (LIT + " .sv-fresh--live::before", LIT + " .sv-live-dot",
                      LIT + " .status-dot.online"),
    "--sv-edge-hero": (LIT + " .sv-panel--hero::before",),
    "--sv-glow-up-in": tuple(LIT + " " + s + ":not([disabled], .disabled):is(:hover, :focus-visible)" for s in (
        ".sr-pop-btn.sr-pop-btn-act",
        '.sr-gone-row[data-side="long"] .sr-gone-btn.sr-gone-btn-ticket',
        # MARKET SHUT's ▶ TICKET (2026-11-12, the merge of main's #99-#101):
        # LEFT THE RAIL's control in the section beside it, the same light.
        '.sr-wait-row[data-side="long"] .sr-gone-btn.sr-gone-btn-ticket')),
    "--sv-glow-down-in": tuple(LIT + " " + s + ":not([disabled], .disabled):is(:hover, :focus-visible)" for s in (
        ".sr-pop-btn.sr-pop-btn-short",
        ".sr-popup:has(.sr-pop-dir-bearish) .sr-pop-btn.sr-pop-btn-act",
        '.sr-gone-row[data-side="short"] .sr-gone-btn.sr-gone-btn-ticket',
        '.sr-wait-row[data-side="short"] .sr-gone-btn.sr-gone-btn-ticket')),
    # A BUY or a SELL whose label holds a figure (the ticket's live bid and
    # ask, a size): the side's ring alone, no blur (review 2026-11-12).
    "--sv-glow-up-ring": tuple(LIT + " " + s + ":not([disabled], .disabled):is(:hover, :focus-visible)"
                               for s in (".tk-long", ".btn.btn-buy")),
    "--sv-glow-down-ring": tuple(LIT + " " + s + ":not([disabled], .disabled):is(:hover, :focus-visible)"
                                 for s in (".tk-short", ".btn.btn-sell")),
}


class LightOnTheFrameTests(SimpleTestCase):

    def test_light_only_on_light_sources(self):
        """Every rule that uses a glow, edge or spill token is one of the
        named light sources, under the dark theme and Magic or Calm."""
        seen = {k: [] for k in LIGHT_SOURCES}
        for prelude, body, ctx in kit_rules():
            for prop, value in decls(body):
                for token in re.findall(r"var\((--sv-(?:glow|spill)-[\w-]+|--sv-edge-hero)\)", value):
                    seen[token].extend(selectors(prelude))
        for token, want in LIGHT_SOURCES.items():
            with self.subTest(token=token):
                self.assertEqual(sorted(seen[token]), sorted(want))
        for rel in (SAURON, "static/css/sv-overlay.css", "static/css/sv-rail.css"):
            self.assertNotRegex(read(rel), r"--sv-(glow|spill)-|--sv-edge-hero")

    def test_every_light_rule_is_scoped_to_magic_or_calm(self):
        """Off is S1a: a rule the magic adds that sets a shadow, a filter
        or a lit background sits under Magic or Calm (or Magic alone), in
        the dark theme. Read between the kit's two markers."""
        kit = read(KIT)
        start, end = kit.index("THE MAGIC KEPT"), kit.index("END OF THE MAGIC KEPT")
        self.assertLess(start, end)
        checked = 0
        for prelude, body, ctx in rules(kit[start:end]):
            if prelude.startswith("@"):
                continue
            props = dict(decls(body))
            lit = any(p in props and props[p] != "none" for p in ("box-shadow", "text-shadow", "filter")) \
                or any("0,232,104" in v.replace(" ", "") or "--sv-void" in v or "--sv-spill" in v
                       or "--sv-edge-hero" in v for v in props.values())
            if not lit:
                continue
            for sel in selectors(prelude):
                checked += 1
                with self.subTest(selector=sel):
                    if sel == "body:not(.light-mode) .sv-on-void":
                        continue       # a shade in bg-0, not a light
                    self.assertTrue(sel.startswith(LIT) or sel.startswith(MAGIC), sel)
        self.assertGreater(checked, 20)

    def test_no_figure_is_ever_lit(self):
        """No rule whose selector ends on a figure class sets a text-shadow
        (but none), a filter, a box-shadow in the Eye's or a side's colour,
        or a gradient or translucent background. Static, over the kit; the
        measured class reads the pages at rest and at each moment's peak."""
        figure = re.compile("(%s)(?![\\w-])" % "|".join(re.escape(c) for c in FIGURE_CLASSES))
        checked = 0
        for prelude, body, ctx in kit_rules():
            for sel in selectors(prelude):
                last = re.split(r"[\s>+~]+", sel.strip())[-1]
                if not figure.search(last):
                    continue
                checked += 1
                for prop, value in decls(body):
                    flat = value.replace(" ", "")
                    with self.subTest(selector=sel, prop=prop):
                        if prop == "text-shadow":
                            self.assertEqual(value, "none")
                        if prop == "filter":
                            self.assertEqual(value, "none")
                        if prop == "box-shadow":
                            self.assertNotRegex(flat, r"0,232,104|36,181,130|255,107,110|--sv-(eye|up|down|glow)")
                        if prop in ("background", "background-image", "background-color"):
                            self.assertNotRegex(flat, r"gradient|rgba\(|transparent\)|--sv-(spill|void|edge)")
        self.assertGreater(checked, 5)

    def test_real_never_glows(self):
        """The world family is a fill, never a light: no rule of the three
        shell sheets gives one of its selectors a blurred shadow or a
        text-shadow, and none wears a glow token. S1a's focus outline is
        the one ring it may take (the armed pill is a link)."""
        checked = 0
        for rel in (SAURON, KIT, "static/css/sv-overlay.css"):
            for prelude, body, ctx in rules(read(rel)):
                for sel in selectors(prelude):
                    if not any(re.search(re.escape(m) + r"(?![\w-])", sel) for m in WORLD_FAMILY):
                        continue
                    if "light-mode)" not in sel and "light-mode" in sel:
                        continue       # light mode, frozen
                    checked += 1
                    for prop, value in decls(body):
                        with self.subTest(file=rel, selector=sel, prop=prop):
                            self.assertNotIn("--sv-glow", value)
                            if prop == "text-shadow":
                                self.assertEqual(value, "none")
                            if prop == "filter":       # a hover may brighten the fill; never a shadow
                                self.assertNotRegex(value, r"drop-shadow|blur")
                            if prop == "box-shadow":
                                for layer in layers(value):
                                    self.assertNotRegex(layer, r"(^|\s)0 0 [1-9]", layer)
        self.assertGreater(checked, 12)

    def test_a_money_button_lights_in_its_side_inside_its_box_never_disabled(self):
        kit = read(KIT)
        for token in ("--sv-glow-up-in", "--sv-glow-down-in", "--sv-glow-up-ring", "--sv-glow-down-ring"):
            want = LIGHT_SOURCES[token]
            rule = block(kit, ",\n".join(want))
            self.assertEqual(rule, {"box-shadow": "var(%s)" % token})
        # The bearish card's coral comes after the jade it must outweigh.
        order = [p for p, b, c in kit_rules()]
        self.assertLess(order.index(",\n".join(LIGHT_SOURCES["--sv-glow-up-in"])),
                        order.index(",\n".join(LIGHT_SOURCES["--sv-glow-down-in"])))
        # At rest S1a's "box-shadow: none" stays on the card's two sides.
        for sel in (".sr-pop-btn.sr-pop-btn-act", ".sr-pop-btn.sr-pop-btn-short"):
            self.assertEqual(block(kit, sel)["box-shadow"], "none")

    def test_the_hero_card_is_dark_when_stale_and_around_a_world_marker(self):
        kit = read(KIT)
        hero = LIT + " .sv-panel--hero"
        self.assertEqual(block(kit, hero), {"position": "relative", "border-color": "var(--sv-line-3)"})
        edge = block(kit, hero + "::before")
        self.assertEqual((edge["top"], edge["height"], edge["left"], edge["right"], edge["background"]),
                         ("-1px", "1px", "14px", "14px", "var(--sv-edge-hero)"))
        glow = block(kit, hero + "::after")
        self.assertEqual((glow["top"], glow["height"], glow["left"], glow["right"]),
                         ("-14px", "13px", "12%", "12%"))
        for marks in (HERO_STALE, HERO_DARK):
            has = "%s:has(%s)" % (hero, ", ".join(marks))
            self.assertEqual(block(kit, "%s::before,\n%s::after" % (has, has)), {"content": "none"})

    def test_the_hero_s_glow_fades_to_nothing_at_both_ends(self):
        """Updated deliberately (2026-11-12): the operator's brief and his
        decision on the review's CR5. As wide as 60 % of its box, the
        glow's ellipse still held about .05 at the box's two sides: a
        vertical step at 12 % and 88 % of the card. Half the box wide and
        centred, it reaches 0 at both ends, and above them."""
        glow = block(read(KIT), LIT + " .sv-panel--hero::after")
        self.assertEqual(glow["background"],
                         "radial-gradient(50% 100% at 50% 100%, rgba(0,232,104,.30), rgba(0,232,104,0))")
        m = re.match(r"radial-gradient\(([\d.]+)% ([\d.]+)% at ([\d.]+)% 100%,", glow["background"])
        rx, at = float(m.group(1)), float(m.group(3))
        self.assertLessEqual(at + rx, 100)          # the right end, inside the box
        self.assertGreaterEqual(at - rx, 0)         # the left end

    def test_the_active_row_s_icon_takes_the_eye_s_colour_and_no_glow(self):
        """Updated deliberately (2026-11-12): the operator's brief and his
        decision on the review's CR6. Its drop-shadow made the active row's
        glyph a lit green disc on /command/ ("◉"), the sign of "eToro ·
        live" and "Engine healthy". The icon keeps the Eye's colour; the
        2 px edge with its glow and the spill say "chosen"."""
        kit = read(KIT)
        self.assertEqual(block(kit, LIT + " .nav-link.active .icon"), {"color": "var(--sv-eye)"})
        for prelude, body, ctx in kit_rules():
            if not any(re.search(r"\.nav-link\b[^,]*\.icon\b", s) for s in selectors(prelude)):
                continue
            for prop, value in decls(body):
                with self.subTest(rule=prelude, prop=prop):
                    self.assertNotIn(prop, ("filter", "text-shadow", "box-shadow"))

    def test_no_template_makes_a_hero_of_a_card_that_holds_a_world_marker(self):
        """A card that holds REAL is never a hero. The kit's own proof that
        such a card stays dark is the one pairing a template may spell."""
        marker = re.compile(r"sv-world--live|sv-venue--live|tk-venue--live|sv-armed-pill|is-live|"
                            r"hq-tag--live|hq-brk--live|ib-env--live|bk-env--live|money_world \"live\"")
        heroes = 0
        for rel, markup in under_base().items():
            for m in re.finditer(r"<(\w+)\b[^>]*\bsv-panel--hero\b[^>]*>", markup):
                heroes += 1
                if 'data-kit="hero-real"' in m.group(0):
                    continue
                end = markup.find("</%s>" % m.group(1), m.end())
                depth, i = 1, m.end()
                for t in re.finditer(r"<(/?)%s\b" % m.group(1), markup[m.end():]):
                    depth += -1 if t.group(1) else 1
                    if depth == 0:
                        end = m.end() + t.start()
                        break
                with self.subTest(file=rel, hero=m.group(0)[:80]):
                    self.assertNotRegex(markup[m.end():end], marker)
        self.assertGreaterEqual(heroes, 3)


# ══════════════════════════════════════════════════════════════════════════
# C4. The void and opaque cards; C5. the opt-in; C7. the moments' sheet
# ══════════════════════════════════════════════════════════════════════════

class VoidAndEmbersSourceTests(SimpleTestCase):

    def test_the_void_is_two_fixed_composited_layers(self):
        kit = read(KIT)
        light = block(kit, LIT + "::before")
        self.assertEqual((light["position"], light["inset"], light["z-index"], light["pointer-events"],
                          light["will-change"], light["background"]),
                         ("fixed", "0", "-2", "none", "transform",
                          "var(--sv-void-light), var(--sv-void-vignette)"))
        grain = block(kit, LIT + "::after")
        self.assertEqual((grain["position"], grain["inset"], grain["z-index"], grain["pointer-events"],
                          grain["will-change"], grain["background-image"], grain["opacity"]),
                         ("fixed", "0", "-1", "none", "transform", "var(--sv-void-grain)",
                          "var(--sv-grain-opacity)"))

    def test_the_light_that_reaches_the_page_only_where_no_figure_sits_on_the_void(self):
        """2026-11-13, the check of CR2: the light that reaches the page is
        fixed to the window, under whatever scrolls there. A page wears it
        once it has proved no figure of its sits on the void: a page with
        the embers (data-sv-embers), and the kit by its own opt-in
        (data-sv-light). Every other page keeps C1's light, which fades
        out under the chrome. One rule names the token, and only it."""
        kit = read(KIT)
        reach = LIT + ":is([data-sv-embers], [data-sv-light])::before"
        self.assertEqual(block(kit, reach), {"background": "var(--sv-void-light-reach), var(--sv-void-vignette)"})
        named = [sel for prelude, body, _ctx in rules(read(KIT)) + rules(read(SAURON))
                 if "--sv-void-light-reach" in body for sel in selectors(prelude)]
        self.assertEqual(named, [reach])

    def test_nothing_is_attached_to_the_viewport_by_a_background(self):
        """background-attachment: fixed makes the main thread repaint the
        page behind every frame (measured: 2.6 times the cost at rest)."""
        for rel in (TOKENS, KIT, SAURON):
            css = strip_comments(read(rel))
            with self.subTest(file=rel):
                self.assertNotRegex(css, r"background-attachment\s*:\s*fixed")
                self.assertNotRegex(css, r"background\s*:[^;{}]*\bfixed\b")

    def test_the_cards_are_opaque_in_the_dark_theme(self):
        rule = block(read(KIT), "body:not(.light-mode) :is(.card, .stat-box, .metric, .signal-item)")
        self.assertEqual(rule, {"background": "var(--sv-bg-1)"})

    def test_a_lone_figure_on_the_void_takes_a_solid_pill_in_the_dark_theme_only(self):
        """The refresh note under /command/'s and /eye/'s last card holds a
        clock: in the dark theme it sits on bg-1 with a line, like a page
        head's age. No rule names the pill outside the dark theme, so the
        light theme (no void) prints the note as it did."""
        kit = read(KIT)
        named = [sel for sel, _body, _ctx in rules(kit) if ".sv-void-pill" in sel]
        self.assertEqual(named, ["body:not(.light-mode) .sv-void-pill"])
        pill = block(kit, "body:not(.light-mode) .sv-void-pill")
        self.assertEqual((pill["background"], pill["border"]), ("var(--sv-bg-1)", "1px solid var(--sv-line-2)"))
        self.assertEqual(pill["font-size"], "var(--sv-fs-micro)")
        self.assertNotIn("text-shadow", pill)
        note = read("templates/dashboard/_eye_body.html")
        self.assertRegex(note, r'<span class="sv-void-pill">Auto-refresh every 10s · \{\{ now\|date:"Y-m-d H:i:s" \}\}</span>')

    def test_words_on_the_void_wear_the_dark_halo_and_a_figure_sits_on_a_pill(self):
        kit = read(KIT)
        self.assertEqual(block(kit, "body:not(.light-mode) .sv-on-void")["text-shadow"],
                         "0 0 3px var(--sv-bg-0), 0 0 8px var(--sv-bg-0), 0 0 14px var(--sv-bg-0)")
        pill = block(kit, ".sv-pill--solid")
        self.assertEqual((pill["background"], pill["border"], pill["text-shadow"]),
                         ("var(--sv-bg-1)", "1px solid var(--sv-line-2)", "none"))

    def test_the_body_says_the_ambience_and_a_page_opts_into_the_embers(self):
        """Updated deliberately (2026-11-13, the check of CR2): the body
        carries a second opt-in, the light that reaches the page, which the
        kit fills (a page with the embers wears that light already)."""
        base = read(BASE)
        self.assertIn(' data-sv-ambience="{% get_ambience %}"{% block sv_embers %}{% endblock %}'
                      '{% block sv_light %}{% endblock %}>', base)
        opted = sorted(rel for rel, t in under_base().items() if "{% block sv_embers %}" in t and rel != BASE)
        self.assertEqual(opted, ["templates/dashboard/command.html",
                                 "templates/dashboard/positions_list.html"])
        for rel in opted:
            self.assertIn("{% block sv_embers %} data-sv-embers{% endblock %}", read(rel))
        lit = sorted(rel for rel, t in under_base().items() if "{% block sv_light %}" in t and rel != BASE)
        self.assertEqual(lit, [KIT_PAGE])
        self.assertIn("{% block sv_light %} data-sv-light{% endblock %}", read(KIT_PAGE))

    def test_get_ambience_answers_magic(self):
        """With nobody signed in the tag answers "magic". Updated
        deliberately (Ambience Magic, Calm or Off, 2026-11-12): the tag
        now reads the operator's own choice from his profile, as get_theme
        reads his theme; tests/test_ambience_pref.py holds that."""
        from django.template import Context, Template
        out = Template("{% load sauron_tags %}{% get_ambience %}").render(Context({}))
        self.assertEqual(out, "magic")
        src = read("core/templatetags/sauron_tags.py")
        fn = src[src.index("def get_ambience"):]
        fn = fn[:fn.index("\n@register") if "\n@register" in fn else len(fn)]
        self.assertIn("request.user.trader_profile.ambience", fn.split('"""')[-1])

    def test_the_ember_and_moment_scripts_load_once_deferred(self):
        base = read(BASE)
        for name in ("sv-embers.js", "sv-moments.js"):
            self.assertEqual(base.count("<script src=\"{%% static 'js/%s' %%}\" defer></script>" % name), 1)

    def test_the_brand_iris_is_one_group_clipped_to_the_lid(self):
        base = read(BASE)
        lid = "M4.2 12Q12 3.4 19.8 12Q12 20.6 4.2 12Z"
        self.assertIn('<clipPath id="svBrandLid"><path d="%s"/></clipPath>' % lid, base)
        m = re.search(r'<g clip-path="url\(#svBrandLid\)">\s*<g class="sv-brand-iris">(.*?)</g>\s*</g>', base, re.S)
        self.assertTrue(m)
        self.assertEqual(m.group(1).count("<circle"), 2)


class MomentsSheetTests(SimpleTestCase):

    MOMENT_FRAMES = ("sv-light-run", "sv-light-fade", "sv-moment-icon")

    def frames(self):
        return {p.split()[1]: b for p, b, c in kit_rules() if p.startswith("@keyframes")}

    def test_the_moment_keyframes_animate_light_only(self):
        """A moment animates the opacity and the background-position of its
        own light, never a colour, a transform or a size."""
        frames = self.frames()
        for name in self.MOMENT_FRAMES:
            with self.subTest(keyframes=name):
                props = set(re.findall(r"([\w-]+)\s*:", re.sub(r"[\d.%,\s]+(?=\{)|from|to", "", frames[name])))
                self.assertTrue(props, frames[name])
                self.assertLessEqual(props, {"opacity", "background-position"})

    def test_the_flare_s_ring_ends_inside_the_window(self):
        """Review 2026-11-12 (the brief: never a game effect): in the full
        sidebar the mark's centre sits 38 px from the window's top and left
        edges (its 36 px box at 20 px), and the flare is a 70 px circle;
        grown to 1.9 its ring was cut by the window at the top and the left
        from 300 ms on, a sonar ping. It may grow to 2 x 38 / 70 = 1.086 at
        most: a bloom that stays whole. The burst, the timing and the easing
        are C6's.

        2026-11-13, the check of the collapsed mark: in the collapsed
        sidebar (68 px, overflow-x hidden) the mark's centre sits 14 + 15 =
        29 px under the window's top and, inside the sidebar's 1 px edge and
        its 6 px scrollbar, (68 - 1 - 6) / 2 = 30.5 px from either side. The
        70 px circle (its ring 31.5 px from the centre at .9, 37.8 at 1.08;
        Calm's glow 35) was cut there by the window at the top and by the
        sidebar on both sides: the same sonar ping. There the circle is
        50 px, so at its largest scale the ring ends 25 x 1.08 = 27 px from
        the centre and Calm's glow 25 px, a pixel and more inside both
        (CollapsedMarkMeasuredTests measures it)."""
        frames, kit, shell = self.frames(), read(KIT), read(SAURON)
        rule = block(kit, LIT + " .brand-eye-wrap.sv-flare::after")
        self.assertEqual((rule["width"], rule["height"]), ("70px", "70px"))
        # The collapsed sidebar's circle: the flare's own, unless a rule of
        # the collapsed sidebar names its size.
        mini = dict(rule)
        for prelude, body, ctx in kit_rules():
            if prelude == LIT + " .sidebar.mini .brand-eye-wrap.sv-flare::after" and not ctx:
                mini.update(decls(body))
        self.assertEqual(mini["width"], mini["height"])
        # Where the collapsed mark sits (sauron.css).
        self.assertEqual(block(shell, ".sidebar.mini"), {"width": "68px"})
        self.assertEqual(block(shell, ".sidebar.mini .brand-eye-wrap,\n        .sidebar.mini .brand-eye"),
                         {"width": "30px", "height": "30px"})
        self.assertEqual(block(shell, ".sidebar.mini .sidebar-brand")["padding"], "14px 8px")
        self.assertIn("::-webkit-scrollbar{width:6px}", shell)
        self.assertEqual(block(shell, ".sidebar")["border-right"], "1px solid var(--border)")
        top, side = 14 + 30 / 2, (68 - 1 - 6) / 2
        for name in ("sv-eye-flare", "sv-eye-flare-soft", "sv-eye-glow"):
            scales = [float(s) for s in re.findall(r"scale\(([\d.]+)\)", frames[name])]
            with self.subTest(keyframes=name):
                if name != "sv-eye-glow":
                    self.assertEqual(scales[:2], [0.6, 0.9])
                self.assertLessEqual(max(scales) * 70 / 2, 38)
                # collapsed: inside the window's top and the sidebar's sides
                self.assertLessEqual(max(scales) * float(mini["width"][:-2]) / 2, min(top, side) - 1)
        self.assertEqual((mini["width"], mini["height"]), ("50px", "50px"))

    def test_a_moment_never_targets_a_button_or_a_figure(self):
        used = 0
        for prelude, body, ctx in kit_rules():
            if not re.search(r"animation(-name)?\s*:[^;]*sv-(light|moment)-", body):
                continue
            for sel in selectors(prelude):
                used += 1
                with self.subTest(selector=sel):
                    self.assertRegex(sel, r"\.sv-row-light|\.sv-moment-arrive(\.sv-moment--still)?::after|"
                                          r"\.sv-moment-icon::before")
                    for cls in FIGURE_CLASSES + BUTTON_CLASSES + ("button",):
                        self.assertNotRegex(sel, r"(^|[\s>+~])" + re.escape(cls) + r"(?![\w-])")
        self.assertGreaterEqual(used, 3)

    def test_the_fill_s_light_is_a_hairline_with_no_shadow(self):
        kit = read(KIT)
        light = block(kit, ".sv-row-light")
        self.assertEqual((light["position"], light["height"], light["pointer-events"]),
                         ("absolute", "2px", "none"))
        self.assertNotIn("box-shadow", light)
        for sel in (".sv-moment-arrive::after", ".sv-moment-icon::before"):
            self.assertNotIn("box-shadow", block(kit, sel))

    def test_the_eye_s_breath_runs_on_transform_and_opacity(self):
        frames = self.frames()
        for name in ("sv-eye-breath", "sv-eye-flare", "sv-eye-flare-soft", "sv-eye-glow"):
            with self.subTest(keyframes=name):
                props = set(re.findall(r"([\w-]+)\s*:", re.sub(r"[\d.%,\s]+(?=\{)", "", frames[name])))
                self.assertLessEqual(props, {"opacity", "transform"})
        kit = read(KIT)
        breath = block(kit, MAGIC + " .brand-eye-wrap::before",
                       ("@media (prefers-reduced-motion: no-preference)",))
        self.assertEqual(breath["animation"], "sv-eye-breath var(--sv-dur-breath) ease-in-out infinite")
        still = block(kit, LIT + " .brand-eye-wrap::before")
        self.assertEqual((still["opacity"], still["filter"]), (".7", "none"))
        # S1a's rule stays for Off: no halo, nothing moves.
        self.assertEqual(block(kit, ".brand-eye-wrap::before"), {"animation": "none", "opacity": "0"})
        self.assertEqual(block(kit, ".sidebar-brand .brand-eye"), {"animation": "none", "filter": "none"})

    def test_the_eye_s_breath_reads_and_fades_inside_its_own_circle(self):
        """Updated deliberately (2026-11-12): the operator's brief and his
        decision on the review's CR4. The breath barely read: outside the
        36 px mark its halo was a ring 8.5 to 15.5 px wide, +10 to +25
        levels. It now holds .16 to half its radius (it held .12 to 36 %):
        11 to 17.5 px, +20 to +43 (measured, DPR 2).

        Its last stop is 70 %, not the review's 84 %: the halo is a 70 px
        circle (sauron.css: border-radius 50 %) whose gradient runs to the
        box's corner, 35 x sqrt(2) = 49.5 px, so its own circle cuts it at
        70.7 %. At 84 % it still held .0625 there: a hard circular edge,
        a step of 9 to 10 levels under Calm and at the breath's peak
        (measured, DPR 2). At 70 % it fades out inside its circle and,
        grown to the breath's 1.06, inside the window: the mark's centre
        sits 38 px from the window's top and left edges."""
        kit = read(KIT)
        still = block(kit, LIT + " .brand-eye-wrap::before")
        self.assertEqual(still["background"],
                         "radial-gradient(circle, rgba(0,232,104,.34) 0%, rgba(0,232,104,.16) 50%, "
                         "rgba(0,232,104,0) 70%)")
        box = block(read(SAURON), ".brand-eye-wrap::before")
        self.assertEqual((box["width"], box["height"], box["border-radius"]), ("70px", "70px", "50%"))
        radius = 70 / 2
        end = float(re.findall(r"rgba\(0,232,104,0\) ([\d.]+)%\)$", still["background"])[0]) / 100
        fades_at = end * radius * 2 ** 0.5        # circle: its gradient runs to the farthest corner
        self.assertLessEqual(fades_at, radius)
        grown = max(float(s) for s in re.findall(r"scale\(([\d.]+)\)", self.frames()["sv-eye-breath"]))
        self.assertLessEqual(fades_at * grown, 38)

    def test_the_collapsed_mark_s_halo_fades_inside_the_window_and_the_sidebar(self):
        """2026-11-13, the check of CR4: in the collapsed sidebar (68 px,
        overflow-x hidden) the mark is 30 px, its centre 14 + 15 = 29 px
        under the window's top and, with the sidebar's 1 px edge and its
        6 px scrollbar, (68 - 1 - 6) / 2 = 30.5 px from either side. The
        70 px halo fades out 36.7 px from it at the breath's peak: the
        check saw the window cut it at the top (+23.7 levels) and the
        sidebar on its right (a straight +11-level edge). At 52 px it
        fades out at .70 x 26 x sqrt(2) x 1.06 = 27.3 px, inside both. It
        holds .16 to 40 % of its ray, not half: from 50 % its fall to
        nothing ran over 7.8 px and a step between two device pixels
        reached 4 levels at the peak; from 40 % it runs over 11.7 px, 3 at
        most (CollapsedMarkMeasuredTests measures both)."""
        kit, shell = read(KIT), read(SAURON)
        mini = block(kit, LIT + " .sidebar.mini .brand-eye-wrap::before")
        self.assertEqual(mini, {"width": "52px", "height": "52px",
                                "background": "radial-gradient(circle, rgba(0,232,104,.34) 0%, "
                                              "rgba(0,232,104,.16) 40%, rgba(0,232,104,0) 70%)"})
        end = float(re.findall(r"rgba\(0,232,104,0\) ([\d.]+)%\)$", mini["background"])[0]) / 100
        grown = max(float(s) for s in re.findall(r"scale\(([\d.]+)\)", self.frames()["sv-eye-breath"]))
        self.assertEqual(block(shell, ".brand-eye-wrap::before")["border-radius"], "50%")
        fades_at = end * 52 / 2 * 2 ** 0.5 * grown
        self.assertLessEqual(fades_at, 52 / 2 * grown)            # inside its own circle
        # Where the collapsed mark sits (sauron.css).
        self.assertEqual(block(shell, ".sidebar.mini"), {"width": "68px"})
        self.assertEqual(block(shell, ".sidebar.mini .brand-eye-wrap,\n        .sidebar.mini .brand-eye"),
                         {"width": "30px", "height": "30px"})
        self.assertEqual(block(shell, ".sidebar.mini .sidebar-brand")["padding"], "14px 8px")
        self.assertIn("::-webkit-scrollbar{width:6px}", shell)
        self.assertEqual(block(shell, ".sidebar")["border-right"], "1px solid var(--border)")
        top = 14 + 30 / 2
        side = (68 - 1 - 6) / 2
        self.assertLess(fades_at, top - 1)
        self.assertLess(fades_at, side - 1)

    def test_the_only_infinite_animation_the_magic_adds_is_the_breath(self):
        kit = read(KIT)
        start, end = kit.index("THE MAGIC KEPT"), kit.index("END OF THE MAGIC KEPT")
        endless = [p for p, b, c in rules(kit[start:end]) if "infinite" in b]
        self.assertEqual(endless, [MAGIC + " .brand-eye-wrap::before"])


# ══════════════════════════════════════════════════════════════════════════
# C6, C7. The moments' script, run under node with a stubbed page
# ══════════════════════════════════════════════════════════════════════════

MOMENTS_HARNESS = r"""
const vm = require('vm');
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');

function classList(el) {
  const set = new Set();
  return { add: (...c) => { c.forEach(x => { set.add(x); el.log.push('+' + x); }); },
           remove: (...c) => c.forEach(x => set.delete(x)),
           contains: c => set.has(c), toString: () => Array.from(set).join(' '), _set: set };
}
function element(name, attrs) {
  const el = { name, attrs: Object.assign({}, attrs), log: [], listeners: {}, children: [], style: {},
               offsetWidth: 100, parentNode: null, parentElement: null };
  el.classList = classList(el);
  el.getAttribute = k => (k in el.attrs ? el.attrs[k] : null);
  el.setAttribute = (k, v) => { el.attrs[k] = String(v); };
  el.hasAttribute = k => k in el.attrs;
  el.removeAttribute = k => { delete el.attrs[k]; };
  el.addEventListener = (t, f) => { (el.listeners[t] = el.listeners[t] || []).push(f); };
  el.getBoundingClientRect = () => ({ left: 10, top: 20, right: 510, bottom: 52, width: 500, height: 32 });
  el.getClientRects = () => [1];
  el.appendChild = c => { el.children.push(c); c.parentNode = el; c.parentElement = el; return c; };
  el.removeChild = c => { el.children = el.children.filter(x => x !== c); c.parentNode = null; return c; };
  el.closest = () => null;
  el.querySelector = () => null;
  return el;
}

function world(opts) {
  opts = opts || {};
  let now = 1000, timers = [], rafs = [];
  const body = element('body', { 'data-sv-ambience': opts.ambience || 'magic' });
  if (opts.light) body.classList.add('light-mode');
  const wrap = element('brand-eye-wrap'), iris = element('iris'), icon = element('rh-icon');
  let styleWrites = 0;
  iris.style = new Proxy({}, { set: (t, k, v) => { t[k] = v; styleWrites++; return true; } });
  const listeners = {};
  let cards = (opts.cards || []).slice();
  let rows = {};
  const railBody = element('railSignalsBody'); railBody.id = 'railSignalsBody';
  const table = element('table'), host = element('card');
  table.parentElement = host; host.parentElement = body;
  const doc = {
    body, documentElement: element('html'), hidden: false,
    addEventListener: (t, f) => { (listeners[t] = listeners[t] || []).push(f); },
    querySelector: sel => {
      if (sel === '.brand-eye-wrap') return wrap;
      if (sel === '.sv-brand-iris') return iris;
      if (sel === '#railSignals .rail-head .rh-icon') return icon;
      const m = /data-sv-close-trade="([^"]+)"/.exec(sel);
      if (m) return rows[m[1]] ? rows[m[1]].button : null;
      return null;
    },
    querySelectorAll: sel => (sel.indexOf('.sr-signal-wrap') >= 0 ? cards : []),
    createElement: n => element(n),
    getElementById: id => (id === 'railSignalsBody' ? railBody : null),
  };
  const win = {
    document: doc, SV: {},
    matchMedia: q => ({ matches: !!opts.reduced && /reduce/.test(q), addEventListener() {} }),
    performance: { now: () => now },
    setTimeout: (f, ms) => { timers.push({ at: now + (ms || 0), f }); return timers.length; },
    clearTimeout: id => { if (timers[id - 1]) timers[id - 1].f = null; },
    requestAnimationFrame: f => { rafs.push(f); return rafs.length; },
    getComputedStyle: () => ({ position: 'relative', display: 'block' }),
    innerWidth: 1440, innerHeight: 900, scrollX: 0, scrollY: 0,
    addEventListener() {}, MutationObserver: function () { this.observe = () => {}; },
    Date: { parse: Date.parse }, Math, String, Object, Array, isNaN, parseFloat, RegExp, console,
  };
  win.window = win;
  const ctx = vm.createContext(win);
  vm.runInContext(src, ctx);
  const api = {
    body, wrap, iris, icon, host, win,
    fire: (type, detail) => (listeners[type] || []).forEach(f => f({ type, detail, clientX: 700, clientY: 400 })),
    eye: (kind, data) => api.fire('sv:eye-event', { kind, data }),
    answer: detail => api.fire('sv:position-changed', detail),
    advance: ms => { now += ms; timers.forEach(t => { if (t.f && t.at <= now) { const f = t.f; t.f = null; f(); } }); },
    frames: () => { const q = rafs; rafs = []; q.forEach(f => f(now)); return q.length; },
    pendingFrames: () => rafs.length,
    row: id => {
      const tr = element('tr'), td = element('td'), button = element('button', { 'data-sv-close-trade': id });
      button.closest = sel => (/^tr/.test(sel) ? tr : td);
      tr.closest = sel => (sel === 'table' ? table : null);
      tr.querySelector = () => button;
      rows[id] = { tr, button };
      return tr;
    },
    swapPositions: () => api.fire('sv:live-swapped', { region: 'pos-open', node: doc }),
    card: (id, created) => {
      const c = element('card', { 'data-signal-id': String(id), 'data-created': created });
      return c;
    },
    swapRail: list => { cards = list.slice(); api.fire('htmx:afterSwap', { svRegion: railBody }); },
    flares: () => wrap.log.filter(x => x === '+sv-flare').length,
    softs: () => wrap.log.filter(x => x === '+sv-flare--soft').length,
    lights: () => host.children.filter(c => /sv-row-light/.test(c.className || '')),
    arrived: list => [].concat(...list.map(c => c.log.filter(x => x === '+sv-moment-arrive').map(() => c.attrs['data-signal-id']))),
    iconLit: () => icon.log.filter(x => x === '+sv-moment-icon').length,
    styleWrites: () => styleWrites,
  };
  return api;
}

const out = {};
// 1. a fill the payload proves, and one it says is held
{ const w = world(); w.eye('fill_open', { trade_id: 11, working: false }); out.proven = w.flares();
  w.advance(2000); w.eye('fill_open', { trade_id: 12, working: true }); w.advance(6000); out.held = w.flares() - out.proven; }
// 2. no word in the payload: this tab's own answer decides, within 4 s
{ const w = world(); w.eye('fill_open', { trade_id: 21 }); out.waiting = w.flares();
  w.advance(1000); w.answer({ ok: true, trade_id: 21, symbol: 'SYNUSD' }); out.answered = w.flares(); }
{ const w = world(); w.eye('fill_open', { trade_id: 22 }); w.advance(1000);
  w.answer({ ok: true, trade_id: 22, working: true }); w.advance(6000); out.answeredWorking = w.flares(); }
{ const w = world(); w.eye('fill_open', { trade_id: 23 }); w.advance(6000); out.unanswered = w.flares();
  w.answer({ ok: true, trade_id: 23 }); out.answeredLate = w.flares(); }
{ const w = world(); w.eye('fill_open', { trade_id: 24 }); w.advance(500);
  w.answer({ state: 'booked', trade_id: 24 }); out.lookupBooked = w.flares(); }
{ const w = world(); w.eye('fill_open', { trade_id: 25 }); w.advance(500);
  w.answer({ state: 'booked', trade_id: 25, working: true }); w.advance(6000); out.lookupWorking = w.flares(); }
// 3. the other dispatches of sv:position-changed prove nothing, alone or after the event
out.unproven = {};
const shapes = { mayHaveReached: { error: 'The order MAY have reached the broker.' }, lost: {},
                 received: { state: 'received' }, unknown: { state: 'unknown' }, refused: { state: 'refused', trade_id: 31 },
                 closeLost: {}, okNoId: { ok: true }, otherTrade: { ok: true, trade_id: 99 } };
Object.keys(shapes).forEach(k => {
  const w = world(); w.answer(shapes[k]); const alone = w.flares();
  w.eye('fill_open', { trade_id: 31 }); w.advance(500); w.answer(shapes[k]); w.advance(6000);
  out.unproven[k] = [alone, w.flares()];
});
// 4. one answer and one socket event for one trade: one flare, in either order
{ const w = world(); w.answer({ ok: true, trade_id: 41 }); out.answerAlone = w.flares();
  w.advance(300); w.eye('fill_open', { trade_id: 41 }); w.advance(6000); out.answerThenEvent = w.flares(); }
{ const w = world(); w.eye('fill_open', { trade_id: 42 }); w.advance(300); w.answer({ ok: true, trade_id: 42 });
  w.advance(6000); w.eye('fill_open', { trade_id: 42, working: false }); w.advance(6000); out.eventThenAnswer = w.flares(); }
// 5. once per trade id, ever; at most one per 1.5 s
{ const w = world(); w.eye('fill_open', { trade_id: 51, working: false }); w.advance(500);
  w.eye('fill_open', { trade_id: 52, working: false }); out.tooSoon = w.flares();
  w.advance(1600); w.eye('fill_open', { trade_id: 53, working: false }); out.later = w.flares();
  w.advance(5000); w.eye('fill_open', { trade_id: 51, working: false }); w.advance(5000);
  w.eye('fill_open', { trade_id: 51 }); w.answer({ ok: true, trade_id: 51 }); out.twice = w.flares(); }
// 6. a close flares soft; a quote, a notification and a run do not
{ const w = world(); w.eye('fill_close', { trade_id: 61 }); out.close = [w.flares(), w.softs()];
  w.advance(5000); ['quote', 'notification', 'run_complete', 'sauron_answer', 'close_pending'].forEach(k => w.eye(k, { trade_id: 62 }));
  out.others = w.flares(); w.eye('fill_close', { trade_id: 61 }); out.closeTwice = w.flares(); }
// 6b. a close only its own booked trade proves: the kill switch's sweep (a held order it
// withdrew, "Nothing traded", still pushes fill_close with its trade; the portfolio rows it
// only marks closed push one with no trade) and nl_trader's close written in the database
// alone say their source and flare nothing, now or again; the booked close still flares soft
out.closeUnproven = {};
const closeShapes = { killSwitchWithdrawn: { source: 'kill_switch', trade_id: 63, asset_class: 'crypto', symbol: 'SYNUSD' },
                      killSwitchRows: { source: 'kill_switch' },
                      nlTrader: { symbol: 'SYNUSD', source: 'nl_trader' } };
Object.keys(closeShapes).forEach(k => {
  const w = world(); w.eye('fill_close', closeShapes[k]); w.advance(2000); w.eye('fill_close', closeShapes[k]);
  out.closeUnproven[k] = w.flares();
});
{ const w = world(); w.eye('fill_close', { trade_id: 64, asset_class: 'crypto', symbol: 'SYNUSD', side: 'BUY', outcome: 'win', pnl: '' });
  out.closeBooked = [w.flares(), w.softs()]; }
// 7. nothing under reduced motion, Off or light mode; Calm flares
out.quiet = {};
[['reduced', { reduced: true }], ['off', { ambience: 'off' }], ['light', { light: true }], ['calm', { ambience: 'calm' }]].forEach(([k, o]) => {
  const w = world(o); w.eye('fill_open', { trade_id: 71, working: false }); w.row('71'); w.swapPositions();
  const lights = w.lights().map(l => l.className);
  w.advance(2000); const left = w.lights().length; w.eye('fill_close', { trade_id: 72 });
  const c = w.card(1, '2026-01-01T00:00:00+00:00'); w.swapRail([c]);
  out.quiet[k] = { flares: w.flares(), lights: lights.length, arrived: w.arrived([c]).length, icon: w.iconLit(),
                   still: lights, left };
});
// 8. the row's light: the proven trade's row, on the swap that brings it, and only that row
{ const w = world(); w.row('82'); w.swapPositions(); out.swapWithoutFill = w.lights().length;
  w.eye('fill_open', { trade_id: 81, working: false }); w.swapPositions(); out.rowBOnly = w.lights().length;
  w.row('81'); w.swapPositions(); out.rowA = w.lights().length; out.rowClass = w.lights().map(l => l.className);
  out.rowStyle = w.lights().map(l => [l.style.left, l.style.top, l.style.width]);
  w.swapPositions(); out.rowOnce = w.lights().length; }
{ const w = world(); w.eye('fill_open', { trade_id: 83, working: false }); w.advance(61000); w.row('83'); w.swapPositions();
  out.rowExpired = w.lights().length; }
{ const w = world(); w.eye('fill_open', { trade_id: 84, working: true }); w.row('84'); w.swapPositions(); out.rowHeld = w.lights().length; }
// 9. a new signal: not on the rail before AND later than the rail's high-water mark
{ const a = world().card(1, '2026-01-01T10:00:00+00:00'), b = world().card(2, '2026-01-01T11:00:00+00:00');
  const w = world({ cards: [a, b] });
  w.swapRail([b, a]); out.reorder = [w.arrived([a, b]).length, w.iconLit()];
  const old = w.card(3, '2026-01-01T09:00:00+00:00'); w.swapRail([b, a, old]); out.broughtBack = [w.arrived([old]).length, w.iconLit()];
  w.swapRail([b]); w.swapRail([b, a]); out.filterChange = [w.arrived([a]).length, w.iconLit()];
  const fresh = w.card(4, '2026-01-01T12:00:00+00:00'); w.swapRail([fresh, b, a]); out.fresh = [w.arrived([fresh, b, a]), w.iconLit()];
  w.swapRail([fresh, b, a]); out.freshOnce = [w.arrived([fresh]).length, w.iconLit()];
  const many = [5, 6, 7, 8, 9].map(i => w.card(i, '2026-01-01T13:0' + i + ':00+00:00'));
  w.swapRail(many.concat([fresh, b, a])); out.many = [w.arrived(many).length, w.iconLit()];
  const hidden = w.card(10, '2026-01-01T14:00:00+00:00'); hidden.offsetWidth = 0; hidden.getClientRects = () => [];
  w.swapRail([hidden].concat(many)); out.hidden = [w.arrived([hidden]).length, w.iconLit()]; }
// 10. the gaze writes nothing while the pointer is still, one write a frame when it moves
{ const w = world(); out.gazeStill = [w.pendingFrames(), w.styleWrites()];
  w.fire('pointermove'); w.fire('pointermove'); w.fire('pointermove'); out.gazeQueued = w.pendingFrames();
  w.frames(); out.gazeWrites = w.styleWrites(); out.gazeTo = w.iris.style.transform;
  out.gazeAfter = w.pendingFrames(); }
{ const w = world({ ambience: 'calm' }); w.fire('pointermove'); out.gazeCalm = [w.pendingFrames(), w.styleWrites()]; }
{ const w = world({ reduced: true }); w.fire('pointermove'); out.gazeReduced = [w.pendingFrames(), w.styleWrites()]; }
// 11. the kit's play: the same lights, by hand, and never an event
{ const w = world(); const tr = w.row('k1'); const heard = [];
  ['sv:eye-event', 'sv:position-changed', 'sv:live-swapped'].forEach(t => w.win.document.addEventListener(t, () => heard.push(t)));
  w.win.SV.moments.play('fill', tr); out.play = [w.flares(), w.lights().length, heard.length]; }
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipUnless(NODE, "node is not on this machine")
class MomentsNodeTests(SimpleTestCase):
    """static/js/sv-moments.js as it ships, with a stubbed page. The Eye
    flares for a fill only when the fill is proven, once per trade; the
    light runs under the proven trade's row and no other; a signal's card
    lights only when it is new by the server's own clock."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with tempfile.TemporaryDirectory() as tmp:
            harness = pathlib.Path(tmp) / "harness.js"
            harness.write_text(MOMENTS_HARNESS, encoding="utf-8")
            done = subprocess.run([NODE, str(harness), str(ROOT / MOMENTS)], capture_output=True,
                                  text=True, timeout=60)
        if done.returncode:
            raise AssertionError(done.stderr)
        cls.got = json.loads(done.stdout)

    def test_a_fill_the_payload_proves_flares_and_a_held_order_does_not(self):
        self.assertEqual((self.got["proven"], self.got["held"]), (1, 0))

    def test_without_the_word_this_tab_s_own_answer_decides_within_4_s(self):
        g = self.got
        self.assertEqual((g["waiting"], g["answered"]), (0, 1))
        self.assertEqual(g["answeredWorking"], 0)
        self.assertEqual((g["unanswered"], g["answeredLate"]), (0, 0))
        self.assertEqual((g["lookupBooked"], g["lookupWorking"]), (1, 0))

    def test_the_other_dispatches_prove_nothing(self):
        """"MAY have reached the broker", a lost answer, the lookup's
        "received" and "unknown", a refusal, a close whose answer was lost:
        each, alone or after the socket's event, gives no flare."""
        for shape, got in sorted(self.got["unproven"].items()):
            with self.subTest(shape=shape):
                self.assertEqual(got, [0, 0])

    def test_one_answer_and_one_event_give_one_flare_in_either_order(self):
        g = self.got
        self.assertEqual((g["answerAlone"], g["answerThenEvent"]), (0, 1))
        self.assertEqual(g["eventThenAnswer"], 1)

    def test_once_per_trade_and_at_most_one_per_second_and_a_half(self):
        g = self.got
        self.assertEqual((g["tooSoon"], g["later"], g["twice"]), (1, 2, 2))

    def test_a_close_flares_soft_and_nothing_else_flares(self):
        g = self.got
        self.assertEqual(g["close"], [1, 1])
        self.assertEqual((g["others"], g["closeTwice"]), (1, 1))

    def test_a_close_its_own_trade_does_not_prove_flares_nothing(self):
        """Review 2026-11-12: the kill switch pushes fill_close for a held
        order it withdrew (nothing traded) and, with no trade, for the
        portfolio rows it only marks closed; nl_trader for a close written
        in the database alone. Each says its source; none proves a fill, so
        none flares, the first time or again. The engine's, the
        reconcile's and the pending closes' booked close carries its trade
        and no source: it still flares soft."""
        for shape, got in sorted(self.got["closeUnproven"].items()):
            with self.subTest(shape=shape):
                self.assertEqual(got, 0)
        self.assertEqual(self.got["closeBooked"], [1, 1])

    def test_nothing_under_reduced_motion_off_or_light_mode(self):
        for mode in ("reduced", "off", "light"):
            with self.subTest(mode=mode):
                self.assertEqual({k: v for k, v in self.got["quiet"][mode].items() if k != "still"},
                                 {"flares": 0, "lights": 0, "arrived": 0, "icon": 0, "left": 0})
        calm = self.got["quiet"]["calm"]
        self.assertEqual((calm["flares"], calm["lights"], calm["arrived"], calm["icon"]), (2, 1, 1, 1))
        self.assertEqual(calm["still"], ["sv-row-light sv-row-light--still"])
        self.assertEqual(calm["left"], 0)          # the light leaves, with or without an animation

    def test_the_light_runs_under_the_proven_trade_s_row_and_no_other(self):
        g = self.got
        self.assertEqual(g["swapWithoutFill"], 0)
        self.assertEqual(g["rowBOnly"], 0)          # a fill for trade A never lights row B
        self.assertEqual((g["rowA"], g["rowOnce"]), (1, 1))
        self.assertEqual(g["rowClass"], ["sv-row-light"])
        self.assertEqual(g["rowStyle"], [["0px", "30px", "0px"]])
        self.assertEqual((g["rowExpired"], g["rowHeld"]), (0, 0))

    def test_a_signal_is_new_by_the_server_s_clock_only(self):
        g = self.got
        self.assertEqual(g["reorder"], [0, 0])
        self.assertEqual(g["broughtBack"], [0, 0])      # ↺ BRING BACK
        self.assertEqual(g["filterChange"], [0, 0])
        self.assertEqual(g["fresh"], [["4"], 1])
        self.assertEqual(g["freshOnce"], [1, 1])
        self.assertEqual(g["many"], [3, 2])             # at most three cards a swap
        self.assertEqual(g["hidden"], [0, 2])           # a card the filters hide lights nothing
        src = read(MOMENTS)
        self.assertNotRegex(src, r"Date\.now|new Date")

    def test_the_gaze_writes_only_when_the_pointer_moves(self):
        g = self.got
        self.assertEqual(g["gazeStill"], [0, 0])
        self.assertEqual((g["gazeQueued"], g["gazeWrites"], g["gazeAfter"]), (1, 1, 0))
        m = re.fullmatch(r"translate\((-?[\d.]+)px, (-?[\d.]+)px\)", g["gazeTo"])
        self.assertTrue(m, g["gazeTo"])
        self.assertLessEqual(abs(float(m.group(1))), 2.4)
        self.assertLessEqual(abs(float(m.group(2))), 1.0)
        self.assertEqual(g["gazeCalm"], [0, 0])
        self.assertEqual(g["gazeReduced"], [0, 0])

    def test_the_kit_s_play_is_no_event(self):
        self.assertEqual(self.got["play"], [1, 1, 0])

    def test_the_script_listens_for_the_eye_s_events_and_never_dispatches(self):
        src = strip_comments(read(MOMENTS))
        self.assertIn("'sv:eye-event'", src)
        self.assertNotIn("dispatchEvent", src)
        for never in ("fetch(", "XMLHttpRequest", "WebSocket", "localStorage", "htmx.ajax"):
            self.assertNotIn(never, src)


# ══════════════════════════════════════════════════════════════════════════
# Measured: the pages as the browser lays them out, offline
# ══════════════════════════════════════════════════════════════════════════

def _file_page(markup, scripts=(), before=""):
    """A rendered page as a file Chromium opens on its own (_offline: its
    scripts dropped, no network), with the named static scripts put back at
    the end of the body as they ship; `before` runs ahead of them. The
    page's JSON islands stay, for the scripts that draw from them."""
    held = []

    def hold(m):
        held.append(m.group(0))
        return "<!--sv-data-%d-->" % (len(held) - 1)

    # A JSON island (json_script) is data, not a script that wants a server.
    markup = re.sub(r'<script\b[^>]*\btype="application/json"[^>]*>.*?</script>', hold, markup, flags=re.S)
    page = _offline(markup)
    for i, tag in enumerate(held):
        page = page.replace("<!--sv-data-%d-->" % i, tag)
    tags = ("<script>%s</script>" % before if before else "") + "".join(
        '<script src="%s"></script>' % (ROOT / "static/js" / name).as_uri() for name in scripts)
    i = page.rindex("</body>")
    return page[:i] + tags + page[i:]


class _Browser:
    """One Chromium for a test class: pages written as files, a tab per
    viewport, and the DevTools calls the measures need."""

    def __init__(self, pages, prefix):
        self.tmp = tempfile.mkdtemp(prefix=prefix)
        self.uri = {}
        for i, (key, markup) in enumerate(sorted(pages.items())):
            path = pathlib.Path(self.tmp) / ("page%d.html" % i)
            path.write_text(markup, encoding="utf-8")
            self.uri[key] = path.as_uri()
        self.chrome = _Chrome(CHROME)

    def close(self):
        try:
            self.chrome.close()
        finally:
            shutil.rmtree(self.tmp, ignore_errors=True)

    def tab(self, width=1440, height=900, reduced=False):
        sid = self.chrome.page(width, height, False)
        self.chrome.call("DOM.enable", session=sid)
        self.chrome.call("CSS.enable", session=sid)
        if reduced:
            self.chrome.call("Emulation.setEmulatedMedia", {"features": [
                {"name": "prefers-reduced-motion", "value": "reduce"}]}, session=sid)
        return sid

    def open(self, sid, key, define=""):
        self.chrome.open(sid, self.uri[key])
        if define:
            self.chrome.eval(sid, define + "; 0")

    def js(self, sid, expression):
        return self.chrome.eval(sid, expression)

    def nodes(self, sid, selector):
        doc = self.chrome.call("DOM.getDocument", {"depth": 0}, session=sid)["root"]["nodeId"]
        return self.chrome.call("DOM.querySelectorAll", {"nodeId": doc, "selector": selector},
                                session=sid)["nodeIds"]

    def force(self, sid, selector, states):
        """Force :hover, :focus-visible… on every node the selector finds."""
        ids = self.nodes(sid, selector)
        for nid in ids:
            self.chrome.call("CSS.forcePseudoState", {"nodeId": nid, "forcedPseudoClasses": list(states)},
                             session=sid)
        return len(ids)

    def fonts(self, sid, selector):
        """[{family, custom, glyphs}] per node: the faces that drew its text."""
        out = []
        for nid in self.nodes(sid, selector):
            got = self.chrome.call("CSS.getPlatformFontsForNode", {"nodeId": nid}, session=sid)
            out.append([{"family": f["familyName"], "custom": f.get("isCustomFont", False),
                         "glyphs": f["glyphCount"]} for f in got["fonts"]])
        return out

    def shot(self, sid, clip=None):
        """A picture of the viewport as it stands, or of a box of it (x, y,
        width, height in viewport pixels). Never beyond the viewport: that
        lays the fixed layers out again."""
        from PIL import Image
        params = {"format": "png", "captureBeyondViewport": False}
        if clip:
            # The DevTools' clip is in the document's own coordinates.
            sx, sy = self.chrome.eval(sid, "[scrollX, scrollY]")
            params["clip"] = {"x": clip[0] + sx, "y": clip[1] + sy, "width": clip[2], "height": clip[3], "scale": 1}
        data = self.chrome.call("Page.captureScreenshot", params, session=sid)["data"]
        return Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")


def _book(name):
    """A signed-in staff client over a synthetic book: quotes, a paper
    trade, a legacy row, a signal on each side, a switch, and an index whose
    symbol holds digits (its page's title must draw them in the number
    face)."""
    from tests.test_ops_cockpit import _component
    from tests.test_signal_acted_and_sizing import _signal
    user = get_user_model().objects.create_user(name, password="x", is_staff=True, is_superuser=True)
    inst = _quote("BTCUSD", 60600).instrument
    _signal(inst, direction="bullish", rule="magic_up")
    eth = _quote("ETHUSD", 2600).instrument
    _signal(eth, direction="bearish", entry=2600, stop=2700, target=2400, rule="magic_down")
    _quote("SYN100", 100, asset_class="index")
    _trade(user)
    _legacy(user)
    _component("magic_on_switch", is_enabled=True)
    _component("magic_off_switch", is_enabled=False)
    client = Client()
    client.force_login(user)
    return client


COMMAND, POSITIONS, INSTRUMENT, OPS, KIT_URL = ("/command/", "/positions/", "/instruments/SYN100/",
                                               "/ops/", "/design/kit/")
#: /command/ fills its body after it loads: one of four tabs, swapped in.
COMMAND_TABS = ("live", "portfolio", "history", "bots")


def _loaded_command(client, tab="live"):
    """/command/ as the operator has it once it has loaded: the page, with
    the tab's body where htmx swaps it in on load. A page read without it
    is an empty frame: most of /command/'s figures are in that body."""
    page = _get(client, COMMAND)
    body = _get(client, "/command/tab/%s/" % tab)
    page, n = re.subn(r'<p class="oc-loading">.*?</p>', lambda _m: body, page, count=1, flags=re.S)
    if n != 1:
        raise AssertionError("the tab body's place is gone from /command/")
    return page


def _command_page(client, tab="live"):
    """The loaded /command/ as a file, its day scheme drawn by its own
    script from the page's own JSON."""
    return _file_page(_loaded_command(client, tab), scripts=("sv-day-scheme.js",))


#: Shared by the probes: colours as numbers, a node's name, the figures of
#: the page (every rendered text node that holds a digit) with the ground
#: each sits on and whether anything lights it.
PROBES = r"""
window.__sv = (function () {
  var AMB = '.grid-bg, .eye-glow-shadow, .globe-eye-bg, .globe-circuits-bg, #particles-canvas';
  function rgba(c) {
    var m = /rgba?\(([^)]+)\)/.exec(c || '');
    if (m) { var p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; }
    m = /color\(srgb ([\d.]+) ([\d.]+) ([\d.]+)(?: \/ ([\d.]+))?\)/.exec(c || '');
    if (m) return { r: Math.round(m[1] * 255), g: Math.round(m[2] * 255), b: Math.round(m[3] * 255), a: m[4] === undefined ? 1 : Number(m[4]) };
    return null;
  }
  function every(str) { return (str.match(/rgba?\([^)]+\)|color\(srgb [^)]+\)/g) || []).map(rgba); }
  function split(v) {
    var out = [], depth = 0, cur = '';
    for (var i = 0; i < v.length; i++) {
      var ch = v[i];
      if (ch === '(') depth++; if (ch === ')') depth--;
      if (ch === ',' && !depth) { out.push(cur.trim()); cur = ''; } else cur += ch;
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
  }
  function name(n) {
    return n.tagName.toLowerCase() + (typeof n.className === 'string' && n.className.trim()
      ? '.' + n.className.trim().split(/\s+/).slice(0, 3).join('.') : '');
  }
  function cls(n, re) { return typeof n.className === 'string' && re.test(n.className); }
  function light(c) {
    return !!c && ((c.r === 0 && c.g === 232 && c.b === 104) || (c.r === 120 && c.g === 255 && c.b === 180)
      || (c.r === 36 && c.g === 181 && c.b === 130) || (c.r === 255 && c.g === 107 && c.b === 110));
  }
  function token(nameOf) {
    var s = document.createElement('span'); s.style.color = 'var(' + nameOf + ')'; document.body.appendChild(s);
    var c = rgba(getComputedStyle(s).color); s.remove(); return c;
  }
  function figureNodes() {
    var out = [], walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT), t;
    while ((t = walker.nextNode())) {
      var txt = t.nodeValue.trim();
      if (!txt || !/\d/.test(txt)) continue;
      var el = t.parentElement;
      if (!el || el.closest('script, style, noscript, template, title, ' + AMB)) continue;
      if (!el.getClientRects().length) continue;      /* not rendered: a list waiting for its click */
      out.push([t, el, txt]);
    }
    return out;
  }
  /* The figures: on the void (no opaque ground before <body>), on glass (a
     translucent colour or a gradient with a clear stop before the first
     opaque ground; S1a's 600 ms wash, .sv-flash, is the one allowed), or
     lit (a text-shadow that is not the void's halo, a filter, a glow in
     the Eye's or a side's colour on itself or an ancestor up to its cell
     or card; a line or a ring with no blur is no light, nor is the
     selected tab's short glow, which hangs below its own box). */
  function figures() {
    var bg0 = token('--sv-bg-0');
    var out = { figures: 0, onVoid: [], glass: [], lit: [] };
    figureNodes().forEach(function (f) {
      var el = f[1], label = f[2].slice(0, 24) + ' <' + name(el) + '>';
      out.figures++;
      var card = null, glass = null, n, cs;
      for (n = el; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
        cs = getComputedStyle(n);
        var c = rgba(cs.backgroundColor), img = cs.backgroundImage, wash = cls(n, /(^|\s)sv-flash/);
        if (img && img !== 'none' && /gradient/.test(img)) {
          var clear = /transparent/.test(img) || every(img).some(function (s) { return s && s.a < 0.999; });
          if (!clear) { card = n; break; }
          if (!wash && !glass) glass = 'a gradient on ' + name(n);
        }
        if (c && c.a >= 0.999) { card = n; break; }
        if (c && c.a > 0 && !wash && !glass) glass = cs.backgroundColor + ' on ' + name(n);
      }
      if (!card) out.onVoid.push(label);
      else if (glass) out.glass.push(label + ': ' + glass);
      for (n = el; n && n !== document.body; n = n.parentElement) {
        cs = getComputedStyle(n);
        var why = null;
        if (cs.textShadow !== 'none' && !every(cs.textShadow).every(function (k) { return k && k.r === bg0.r && k.g === bg0.g && k.b === bg0.b; })) {
          why = 'text-shadow ' + cs.textShadow;
        } else if (cs.filter !== 'none') {
          why = 'filter ' + cs.filter;
        } else if (cs.boxShadow !== 'none') {
          split(cs.boxShadow).forEach(function (layer) {
            if (!light(rgba(layer))) return;
            var px = (layer.replace(/rgba?\([^)]+\)|color\([^)]+\)/, '').match(/-?[\d.]+px/g) || []).map(parseFloat);
            var inset = /inset/.test(layer);
            if (!px[2]) return;         /* no blur: a line or a ring, not a light */
            if (!inset && cls(n, /(^|\s)sv-(tab|seg-btn)(\s|$)/) && px[0] === 0 && px[1] === 4 && px[2] === 10 && px[3] === -6) return;
            why = 'box-shadow ' + layer;
          });
        }
        if (why) { out.lit.push(label + ': ' + why + ' on ' + name(n)); break; }
        if (n === card || n.tagName === 'TD' || n.tagName === 'TH') break;
      }
    });
    return out;
  }
  function mode(m) { document.body.setAttribute('data-sv-ambience', m); }
  function frame() { return new Promise(function (r) { requestAnimationFrame(function () { requestAnimationFrame(r); }); }); }
  /* A still page for a picture: whatever plays once (a page's entrance, a
     hover's transition) is at its end, whatever loops is held at its
     start. While a page fades in it is see-through, and two pictures of it
     differ by the clock alone. */
  function settle(round) {
    var moving = 0;
    document.getAnimations().forEach(function (a) {
      var t = a.effect && a.effect.getComputedTiming();
      if (t && t.iterations === Infinity) { a.pause(); a.currentTime = 0; }
      else if (a.playState !== 'finished') { moving++; try { a.finish(); } catch (e) {} }
    });
    /* An entrance that ends can start a transition of its own: again,
       until nothing is left in flight. Then the page is laid out afresh
       (a node in, a node out): headless Chromium can keep the last painted
       frame of an animation that was finished by hand. */
    return frame().then(function () {
      if (moving && (round || 0) < 6) return settle((round || 0) + 1);
      token('--sv-bg-0');
      return frame().then(function () { return 0; });
    });
  }
  /* Every element's shadows and filter, its two pseudo-elements included. */
  function shadows() {
    var out = [];
    Array.prototype.forEach.call(document.querySelectorAll('body, body *'), function (el) {
      ['', '::before', '::after'].forEach(function (p) {
        var c = getComputedStyle(el, p || null);
        out.push(name(el) + p + ' ' + c.boxShadow + ' | ' + c.textShadow + ' | ' + c.filter + (p ? ' | ' + c.content : ''));
      });
    });
    return out;
  }
  /* The boxes, in the viewport, of what the selector finds and the eye can
     see: displayed, not hidden, not faded out, inside the viewport. */
  function boxes(sel) {
    return Array.prototype.filter.call(document.querySelectorAll(sel), function (b) {
      return b.checkVisibility({ checkOpacity: true, checkVisibilityCSS: true });
    }).map(function (b) {
      var r = b.getBoundingClientRect();
      return { name: name(b), text: (b.textContent || '').trim().slice(0, 20), x: r.left, y: r.top, w: r.width, h: r.height };
    }).filter(function (b) { return b.w > 0 && b.h > 0 && b.x >= 0 && b.y >= 0 && b.x + b.w <= innerWidth && b.y + b.h <= innerHeight; });
  }
  return { rgba: rgba, every: every, split: split, name: name, light: light, token: token, figureNodes: figureNodes,
           figures: figures, mode: mode, frame: frame, settle: settle, shadows: shadows, boxes: boxes };
})();
"""


def _pages(client, urls):
    """Each page as the server renders it; /command/ with its live tab in."""
    return {url: _loaded_command(client) if url == COMMAND else _get(client, url) for url in urls}


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class FiguresMeasuredTests(TestCase):
    """No figure on the void or on glass, and none lit at rest: every text
    node that holds a digit, on the five harness pages, at 1440 px, under
    Magic (the two pages with embers are among them). /command/ is read
    with each of its four tabs in place and its day scheme drawn; the
    instrument page with a day change on each side, as a quote with a
    change prints it."""

    URLS = (POSITIONS, INSTRUMENT, OPS, KIT_URL)
    TABS = tuple(COMMAND + "#" + tab for tab in COMMAND_TABS)
    #: the controls that open or add to a position (C3's side lights)
    MONEY = ".tk-long, .tk-short, .btn.btn-buy, .btn.btn-sell, .sr-pop-btn, .sr-gone-btn"
    CHIPS = ("(function () { var p = document.querySelector('.dtl-price'); if (!p) return 0;"
             " p.insertAdjacentHTML('beforeend', '<span class=\"dtl-chg up\">\u25B2 +1.85%</span>"
             "<span class=\"dtl-chg down\">\u25BC 0.42%</span>'); return 1; })()")
    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        client = _book("magic_figures")
        # The ticket's BUY and SELL carry the live bid and ask (a quote
        # without them prints a dash, which holds no figure).
        from market_data.models import LiveQuote
        LiveQuote.objects.filter(instrument__symbol="SYN100").update(bid=Decimal("99.9"), ask=Decimal("100.1"))
        pages = {u: _file_page(m) for u, m in _pages(client, cls.URLS).items()}
        for tab in COMMAND_TABS:
            pages[COMMAND + "#" + tab] = _command_page(client, tab)
        b = _Browser(pages, "sv-magic-figures-")
        try:
            sid = b.tab()
            cls.got = {}
            for url in sorted(pages):
                b.open(sid, url, PROBES)
                cls.chips = b.js(sid, cls.CHIPS) if url == INSTRUMENT else getattr(cls, "chips", 0)
                cls.got[url] = b.js(sid, "(async function () { __sv.mode('magic'); await __sv.frame();"
                                         " var f = __sv.figures();"
                                         " f.embers = document.body.hasAttribute('data-sv-embers');"
                                         " f.cards = Array.prototype.map.call(document.querySelectorAll('.card, .stat-box, .metric, .signal-item'),"
                                         "   function (c) { var s = getComputedStyle(c); return s.backgroundColor + ' ' + s.backgroundImage; });"
                                         " f.fixed = Array.prototype.filter.call(document.querySelectorAll('body, body *'),"
                                         "   function (e) { return /fixed/.test(getComputedStyle(e).backgroundAttachment); }).map(__sv.name);"
                                         " f.overflowX = document.documentElement.scrollWidth - document.documentElement.clientWidth;"
                                         " f.dayTexts = Array.prototype.filter.call(document.querySelectorAll('.day-scheme-wrap text'),"
                                         "   function (t) { return /\\d/.test(t.textContent); }).length;"
                                         " f.note = /Auto-refresh every \\d+s/.test(document.body.textContent);"
                                         " f.empties = document.querySelectorAll('.oc-empty').length;"
                                         " f.loading = document.querySelectorAll('.oc-loading').length;"
                                         " return f; })()")
            # Review 2026-11-12: a money button whose label holds a figure
            # (the ticket's BUY and SELL hold the live ask and bid, the
            # kit's samples a size), hovered and focused, under Magic and
            # Calm.
            cls.forced = {}
            for url in (INSTRUMENT, KIT_URL):
                b.open(sid, url, PROBES)
                n = b.force(sid, cls.MONEY, ["hover", "focus-visible", "focus"])
                for mode in ("magic", "calm"):
                    f = b.js(sid, "(async function () { __sv.mode('%s'); await __sv.frame();"
                                  " var f = __sv.figures(); f.prices = Array.prototype.filter.call("
                                  "   document.querySelectorAll('.tk-long .tk-px, .tk-short .tk-px'),"
                                  "   function (p) { return /\\d/.test(p.textContent); }).length;"
                                  " return f; })()" % mode)
                    cls.forced[(url, mode)] = {"forced": n, "figures": f["figures"], "lit": f["lit"],
                                               "prices": f["prices"]}
        finally:
            b.close()

    def test_no_figure_on_the_void_or_glass(self):
        for url, got in sorted(self.got.items()):
            with self.subTest(url=url):
                self.assertGreater(got["figures"], 20)
                self.assertEqual(got["onVoid"], [])
                self.assertEqual(got["glass"], [])

    def test_command_is_read_as_it_stands_once_loaded(self):
        """Each tab's body is in place, the day scheme has drawn its counts,
        and the live tab ends on its refresh note: what the test above
        reads is the page the operator has, not its empty frame."""
        for key in self.TABS:
            with self.subTest(tab=key):
                self.assertEqual(self.got[key]["loading"], 0)
                self.assertGreater(self.got[key]["dayTexts"], 5)
        self.assertTrue(self.got[COMMAND + "#live"]["note"])
        self.assertGreater(self.got[COMMAND + "#live"]["empties"], 0)
        self.assertEqual(self.chips, 1)

    def test_the_pages_with_embers_are_among_them(self):
        self.assertEqual(sorted(u for u, g in self.got.items() if g["embers"]), sorted(self.TABS + (POSITIONS,)))

    def test_no_figure_is_lit_at_rest(self):
        for url, got in sorted(self.got.items()):
            with self.subTest(url=url):
                self.assertEqual(got["lit"], [])

    def test_no_figure_is_lit_while_a_money_button_is_hovered_or_focused(self):
        """Review 2026-11-12: the ticket's BUY and SELL hold the live ask
        and bid, the kit's BUY and SELL samples a size. Hovered or focused
        under Magic or Calm, a side marks its button with a ring of no blur
        inside its box, which lights no figure (C3's measure: a line or a
        ring with no blur is no light); its 12 px inset blur lit both
        prices."""
        for (url, mode), got in sorted(self.forced.items()):
            with self.subTest(url=url, mode=mode):
                self.assertGreater(got["forced"], 1)
                self.assertGreater(got["figures"], 20)
                self.assertEqual(got["lit"], [])
        self.assertGreaterEqual(self.forced[(INSTRUMENT, "magic")]["prices"], 2)

    def test_the_cards_compute_an_opaque_ground(self):
        want = "rgb(%d, %d, %d) none" % hex_rgb(PALETTE["--sv-bg-1"])
        seen = 0
        for url, got in sorted(self.got.items()):
            for card in got["cards"]:
                seen += 1
                with self.subTest(url=url):
                    self.assertRegex(card, r"^rgb\(\d+, \d+, \d+\) ")
                    self.assertNotIn("gradient", card.replace(want, ""))
        self.assertGreater(seen, 10)

    def test_no_background_is_attached_to_the_viewport(self):
        for url, got in sorted(self.got.items()):
            with self.subTest(url=url):
                self.assertEqual(got["fixed"], [])
                self.assertEqual(got["overflowX"], 0)


LIGHT_PROBE = r"""(async function () {
  var out = {};
  function px(el, pseudo, prop) { return el ? getComputedStyle(el, pseudo || null)[prop] : null; }
  /* A mode is read once its transitions have ended: a hover's shadow still
     moving (.se-chat-header-btn's .18 s) read as a difference under load
     (review 2026-11-12). Loops are left as they are. */
  function still() {
    document.getAnimations().forEach(function (a) { if (a instanceof CSSTransition) { try { a.finish(); } catch (e) {} } });
  }
  for (var m of ['magic', 'calm', 'off', 's1a']) {
    __sv.mode(m); await __sv.frame(); still();
    var nav = document.querySelector('.sidebar .nav-link.active'), wrap = document.querySelector('.brand-eye-wrap');
    out[m] = {
      wordmark: px(document.querySelector('.sidebar-brand h1'), null, 'textShadow'),
      navBg: px(nav, null, 'backgroundImage'), navEdge: px(nav, '::after', 'boxShadow'), navEdgeContent: px(nav, '::after', 'content'),
      navIcon: px(nav && nav.querySelector('.icon'), null, 'filter') + ' | ' + px(nav && nav.querySelector('.icon'), null, 'textShadow'),
      halo: px(wrap, '::before', 'opacity'), haloFilter: px(wrap, '::before', 'filter'),
      voidLight: px(document.body, '::before', 'content') + ' ' + px(document.body, '::before', 'backgroundImage') + ' ' + px(document.body, '::before', 'position'),
      grain: px(document.body, '::after', 'content') + ' ' + px(document.body, '::after', 'opacity') + ' ' + px(document.body, '::after', 'position'),
      canvas: px(document.getElementById('particles-canvas'), null, 'display'),
      bodyBg: px(document.body, null, 'backgroundColor') + ' ' + px(document.body, null, 'backgroundImage'),
      shadows: __sv.shadows()
    };
  }
  document.body.classList.add('light-mode'); __sv.mode('magic'); await __sv.frame(); still();
  out.light = { wordmarkLit: /0, 232, 104|0, 153, 77/.test(px(document.querySelector('.sidebar-brand h1'), null, 'textShadow')) && false,
                voidLight: px(document.body, '::before', 'content'), grain: px(document.body, '::after', 'content'),
                canvas: px(document.getElementById('particles-canvas'), null, 'display'),
                navEdgeContent: px(document.querySelector('.sidebar .nav-link.active'), '::after', 'content'),
                halo: px(document.querySelector('.brand-eye-wrap'), '::before', 'opacity') };
  document.body.classList.remove('light-mode');
  return out;
})()"""


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class LightMeasuredTests(TestCase):
    """The light as the browser computes it on /command/, per Ambience, and
    Off against a page no magic rule can match (an ambience no rule names):
    with hover and focus forced on every link and button, the two compute
    the same shadows and filters, element by element."""

    @classmethod
    def setUpTestData(cls):
        pages = {u: _file_page(m) for u, m in _pages(_book("magic_light"), (COMMAND, OPS)).items()}
        b = _Browser(pages, "sv-magic-light-")
        try:
            sid = b.tab()
            b.open(sid, COMMAND, PROBES)
            cls.rest = b.js(sid, LIGHT_PROBE)
            cls.forcedNodes = b.force(sid, "a, button, .btn, input, [tabindex]", ["hover", "focus-visible", "focus"])
            cls.forced = b.js(sid, LIGHT_PROBE)
            b.open(sid, OPS, PROBES)
            cls.ops = b.js(sid, LIGHT_PROBE)
        finally:
            b.close()

    def test_magic_and_calm_light_the_frame(self):
        for mode in ("magic", "calm"):
            got = self.rest[mode]
            with self.subTest(mode=mode):
                self.assertRegex(got["wordmark"], r"rgba\(0, 232, 104, 0\.45\) 0px 0px 12px")
                self.assertIn("linear-gradient", got["navBg"])
                self.assertRegex(got["navEdge"], r"rgba\(0, 232, 104, 0\.75\) 0px 0px 8px")
                # The active row's icon: the Eye's colour, no glow (CR6,
                # his decision of 2026-11-12): a lit disc read as "live".
                self.assertEqual(got["navIcon"], "none | none")
                self.assertEqual(got["haloFilter"], "none")
                self.assertRegex(got["voidLight"], r'^"" radial-gradient\(.*radial-gradient\(.* fixed$')
                self.assertEqual(got["grain"], '"" 0.07 fixed')
                # <body> keeps its flat bg-0: the void's layers are its two pseudo-elements.
                self.assertEqual(got["bodyBg"], "rgb(%d, %d, %d) none" % hex_rgb(PALETTE["--sv-bg-0"]))

    def test_off_is_s1a(self):
        """Off computes what S1a computed: no glow on the wordmark, no
        spill, no edge, no halo, a flat void; and, element by element, the
        shadows and filters of a page no magic rule can match, at rest and
        with hover and focus forced."""
        off = self.rest["off"]
        self.assertEqual((off["wordmark"], off["navBg"], off["navEdgeContent"], off["halo"]),
                         ("none", "none", "none", "0"))
        self.assertTrue(off["voidLight"].startswith("none "), off["voidLight"])
        self.assertTrue(off["grain"].startswith("none "), off["grain"])
        self.assertGreater(self.forcedNodes, 60)
        for name, got in (("rest", self.rest), ("forced", self.forced), ("ops", self.ops)):
            with self.subTest(state=name):
                self.assertGreater(len(got["off"]["shadows"]), 1500)
                diff = [(a, b) for a, b in zip(got["off"]["shadows"], got["s1a"]["shadows"]) if a != b]
                self.assertEqual(diff[:5], [])
        # The forced states are not vacuous: Magic differs from Off somewhere.
        self.assertNotEqual(self.forced["magic"]["shadows"], self.forced["off"]["shadows"])

    def test_the_embers_show_under_magic_on_a_page_that_opted_in_and_nowhere_else(self):
        self.assertEqual([self.rest[m]["canvas"] for m in ("magic", "calm", "off")], ["block", "none", "none"])
        self.assertEqual([self.ops[m]["canvas"] for m in ("magic", "calm", "off")], ["none", "none", "none"])
        self.assertEqual(self.rest["light"]["canvas"], "none")

    def test_light_mode_takes_none_of_it(self):
        light = self.rest["light"]
        self.assertEqual((light["voidLight"], light["grain"], light["navEdgeContent"]), ("none", "none", "none"))

    def test_no_real_marker_glows_in_any_mode(self):
        marks = re.compile(r"^\w+\.[\w.-]*(sv-world--live|sv-armed-pill|tk-venue--live|sv-venue--live)")
        seen = 0
        for mode in ("magic", "calm", "off"):
            for line in self.forced[mode]["shadows"] + self.ops[mode]["shadows"]:
                if not marks.match(line) or "::" in line.split(" ")[0]:
                    continue
                seen += 1
                with self.subTest(mode=mode, mark=line[:60]):
                    shadow, text, filt = [x.strip() for x in line.split(" ", 1)[1].split("|")[:3]]
                    self.assertEqual((text, filt), ("none", "none"))
                    self.assertNotRegex(shadow, r"0, 232, 104|36, 181, 130")
                    self.assertNotRegex(shadow, r"\) 0px 0px [1-9]")
        self.assertGreater(seen, 0)


#: Down the light's column (46 % of the window): the chrome (opaque), the
#: empty page (no opaque ground under the point) and the first opaque box
#: below it; a run of empty page under 8 px is a seam, not the page. And
#: the boxes, in the window, of every figure (a text node with a digit)
#: the eye can see: a closed popup's figures are laid out, unseen.
ABOVE_PROBE = r"""(function () {
  function ground(n) {
    for (; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
      var c = getComputedStyle(n), bg = __sv.rgba(c.backgroundColor), img = c.backgroundImage;
      if (img && img !== 'none' && /gradient/.test(img) && !/transparent/.test(img)
          && __sv.every(img).every(function (s) { return s && s.a >= 0.999; })) return n;
      if (bg && bg.a >= 0.999) return n;
    }
    return null;
  }
  var x = Math.round(innerWidth * 0.46), top = null, bottom = null, run = 0;
  for (var y = 0; y < innerHeight; y++) {
    var el = document.elementFromPoint(x, y), g = el && ground(el);
    if (!g) { if (!run) top = y; run++; }
    else { if (run >= 8) { bottom = y; break; } run = 0; top = null; }
  }
  var boxes = [];
  __sv.figureNodes().forEach(function (f) {
    if (!f[1].checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return;
    var range = document.createRange(); range.selectNodeContents(f[0]);
    Array.prototype.forEach.call(range.getClientRects(), function (q) {
      if (q.width > 0 && q.height > 0 && q.bottom > 0 && q.right > 0 && q.top < innerHeight && q.left < innerWidth)
        boxes.push([Math.max(0, Math.floor(q.left)), Math.max(0, Math.floor(q.top)),
                    Math.min(innerWidth, Math.ceil(q.right)), Math.min(innerHeight, Math.ceil(q.bottom))]);
    });
  });
  var f = __sv.figures();
  return { x: x, top: bottom === null ? null : top, bottom: bottom, boxes: boxes, figures: f.figures, lit: f.lit, onVoid: f.onVoid };
})()"""


#: The light from above off, then on again: both of its tokens, C1's light,
#: which every page wears, and the light that reaches the page, which only
#: a page proven off the void wears (setting a token no sheet names is
#: harmless).
LIGHT_OFF = ("(function () { var s = document.documentElement.style;"
             " s.setProperty('--sv-void-light', 'none'); s.setProperty('--sv-void-light-reach', 'none');"
             " return __sv.settle(); })()")
LIGHT_ON = ("(function () { var s = document.documentElement.style;"
            " s.removeProperty('--sv-void-light'); s.removeProperty('--sv-void-light-reach');"
            " return __sv.settle(); })()")
#: The two floating orbs (Ask Sauron, Gollum) are drawn on layers of their
#: own, which headless Chromium redraws a fraction of a pixel apart from
#: one picture to the next, light or not (as KitMagicMeasuredTests found):
#: held out of the pictures, so a figure near them reads as it is.
ORBS_OUT = ("(function () { Array.prototype.forEach.call(document.querySelectorAll('.gollum-fab, .se-eye-fab'),"
            " function (e) { e.style.visibility = 'hidden'; }); return __sv.settle(); })()")

#: For the sweep: where the window stands, the boxes of every figure the eye
#: can see in it (as ABOVE_PROBE reads them, with their text), the light
#: from above the page computes, and whether the page opted into the light
#: that reaches it.
SWEEP_PROBE = r"""(function () {
  var boxes = [], b = document.body;
  __sv.figureNodes().forEach(function (f) {
    if (!f[1].checkVisibility({ checkOpacity: true, checkVisibilityCSS: true })) return;
    var range = document.createRange(); range.selectNodeContents(f[0]);
    Array.prototype.forEach.call(range.getClientRects(), function (q) {
      if (q.width > 0 && q.height > 0 && q.bottom > 0 && q.right > 0 && q.top < innerHeight && q.left < innerWidth)
        boxes.push([Math.max(0, Math.floor(q.left)), Math.max(0, Math.floor(q.top)),
                    Math.min(innerWidth, Math.ceil(q.right)), Math.min(innerHeight, Math.ceil(q.bottom)),
                    f[2].slice(0, 32)]);
    });
  });
  return { y: Math.round(scrollY), boxes: boxes, light: getComputedStyle(b, '::before').backgroundImage,
           optedIn: b.hasAttribute('data-sv-embers') || b.hasAttribute('data-sv-light') };
})()"""


def _nav_urls(markup):
    """Every page the sidebar's nav links, in its order, as a page renders
    it for a staff session (which sees every row)."""
    nav = markup[markup.index('<nav class="sidebar-nav"'):]
    nav = nav[:nav.index("</nav>")]
    urls = []
    for tag in re.findall(r"<a\b[^>]*>", nav):
        href = re.search(r'\bhref="(/[^"]*)"', tag)
        if href and re.search(r'\bclass="nav-link\b', tag) and href.group(1) not in urls:
            urls.append(href.group(1))
    return urls


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class LightFromAboveMeasuredTests(TestCase):
    """The Eye's light from above reaches the page (2026-11-12, the
    operator's brief and his decision on the review's CR2), and only where
    no figure sits on the void (2026-11-13, the check of CR2).

    On the pages that opted in (/positions/ and /command/, which have the
    embers, and the kit) at 1440 and 1920, each picture is taken twice
    with nothing else moving, the light on, then its tokens set to none:
    what differs is the light alone. On the empty page above the first
    card, at the light's column, it adds at least 2 levels of green at its
    brightest point (C1's light, centred 110 px above the window, adds 0.0
    there); Off has none. No pixel of any figure in the window moves with
    it, while every figure computes no light and none sits on the void.

    And on every page the sidebar's nav reaches, at 1440, under Magic and
    Calm, at scroll 0 and one screen down: the light moves no pixel of any
    figure's box by more than one level. The light that reaches the page is
    fixed to the window, so it lies under whatever a page puts there at any
    scroll; at ae1a803, which gave it to every page, it lit figures on the
    void or on see-through grounds by +4 to +7 levels on /evidence/,
    /asset-bots/, /evolution/, /big-money/ and /treasury/. Only the pages
    that opted in wear it now; every other page computes C1's light, which
    fades out under the chrome."""

    URLS = (POSITIONS, COMMAND, KIT_URL)
    VIEWPORTS = ((1440, 900), (1920, 1080))
    MODES = ("magic", "calm", "off")
    SWEEP_VIEWPORT = (1440, 900)
    SWEEP_MODES = ("magic", "calm")

    @classmethod
    def setUpTestData(cls):
        client = _book("magic_above")
        cls.nav = _nav_urls(_get(client, POSITIONS))
        pages = {u: _file_page(m) for u, m in _pages(client, sorted(set(cls.URLS) | set(cls.nav))).items()}
        b = _Browser(pages, "sv-magic-above-")
        try:
            cls.got = {}
            for width, height in cls.VIEWPORTS:
                sid = b.tab(width, height)
                for url in cls.URLS:
                    b.open(sid, url, PROBES)
                    b.js(sid, ORBS_OUT)
                    for mode in cls.MODES:
                        b.js(sid, "__sv.mode('%s'); __sv.settle()" % mode)
                        got = b.js(sid, ABOVE_PROBE)
                        on = b.shot(sid)
                        b.js(sid, LIGHT_OFF)
                        none = b.shot(sid)
                        b.js(sid, LIGHT_ON)
                        got["brightest"], got["figurePixels"] = cls._light(got, on, none)
                        cls.got[(url, width, mode)] = got
            cls.sweep = {}
            sid = b.tab(*cls.SWEEP_VIEWPORT)
            for url in cls.nav:
                b.open(sid, url, PROBES)
                b.js(sid, ORBS_OUT)
                for mode in cls.SWEEP_MODES:
                    seen = set()
                    for screens in (0, 1):
                        b.js(sid, "(function () { __sv.mode('%s'); scrollTo(0, %d * innerHeight);"
                                  " return __sv.settle(); })()" % (mode, screens))
                        got = b.js(sid, SWEEP_PROBE)
                        if got["y"] in seen:
                            continue        # shorter than two screens: one screen down is the end
                        seen.add(got["y"])
                        on = b.shot(sid)
                        b.js(sid, LIGHT_OFF)
                        none = b.shot(sid)
                        b.js(sid, LIGHT_ON)
                        got["worst"], got["moved"] = cls._moved(got["boxes"], on, none)
                        got["boxes"] = len(got["boxes"])
                        cls.sweep[(url, mode, got["y"])] = got
        finally:
            b.close()

    @staticmethod
    def _light(got, on, none):
        """The light alone (green, on minus none: it only adds) at its
        brightest on the empty page above the first card, as a 5 x 5 mean,
        within 160 px of the light's column; and the most any pixel of any
        figure's box moved with it."""
        from PIL import ImageChops, ImageFilter
        brightest = None
        if got["bottom"] is not None:
            added = ImageChops.subtract(on.split()[1], none.split()[1])
            band = added.crop((max(0, got["x"] - 160), got["top"], got["x"] + 160, got["bottom"]))
            brightest = band.filter(ImageFilter.BoxBlur(2)).getextrema()[1]
        moved = ImageChops.difference(on, none)
        figure = max((max(hi for _lo, hi in moved.crop(tuple(box)).getextrema()) for box in got["boxes"]),
                     default=None)
        return brightest, figure

    @staticmethod
    def _moved(boxes, on, none):
        """The most the light moves a pixel of any figure's box, and the
        boxes it moves by more than one level, the most first."""
        from PIL import ImageChops
        moved = ImageChops.difference(on, none)
        worst, out = 0, []
        for x0, y0, x1, y1, text in boxes:
            if x1 <= x0 or y1 <= y0:
                continue
            hi = max(h for _l, h in moved.crop((x0, y0, x1, y1)).getextrema())
            worst = max(worst, hi)
            if hi > 1:
                out.append((hi, text, x0, y0))
        return worst, sorted(out, reverse=True)

    def test_the_light_from_above_lights_the_empty_page_above_the_first_card(self):
        for (url, width, mode), got in sorted(self.got.items()):
            with self.subTest(url=url, width=width, mode=mode):
                self.assertIsNotNone(got["bottom"], "no empty page above a first card down the light's column")
                if mode == "off":
                    self.assertEqual(got["brightest"], 0)
                else:
                    self.assertGreaterEqual(got["brightest"], 2, (got["top"], got["bottom"]))

    def test_every_figure_stays_unlit(self):
        for (url, width, mode), got in sorted(self.got.items()):
            with self.subTest(url=url, width=width, mode=mode):
                self.assertGreater(got["figures"], 20)
                self.assertGreater(len(got["boxes"]), 20)
                self.assertEqual(got["figurePixels"], 0)
                self.assertEqual(got["lit"], [])
                self.assertEqual(got["onVoid"], [])

    def test_the_light_moves_no_figure_on_any_page_of_the_nav(self):
        """Every page of the nav, under Magic and Calm, at scroll 0 and one
        screen down: no pixel of any figure's box moves with the light by
        more than one level."""
        self.assertGreater(len(self.nav), 55)
        for url in self.nav:
            with self.subTest(url=url):
                self.assertEqual(sorted({m for u, m, _y in self.sweep if u == url}), sorted(self.SWEEP_MODES))
        self.assertGreater(len([k for k in self.sweep if k[2] > 0]), 40)     # read one screen down too
        for (url, mode, y), got in sorted(self.sweep.items()):
            with self.subTest(url=url, mode=mode, scroll=y):
                self.assertGreater(got["boxes"], 0)
                self.assertLessEqual(got["worst"], 1, got["moved"][:4])

    def test_the_light_reaches_only_the_pages_that_opted_in(self):
        """The light that reaches the page on the pages proven off the void
        (in the nav, the two with the embers); C1's light everywhere else."""
        opted = sorted({url for (url, _m, _y), got in self.sweep.items() if got["optedIn"]})
        self.assertEqual(opted, sorted([COMMAND, POSITIONS]))
        for (url, mode, y), got in sorted(self.sweep.items()):
            with self.subTest(url=url, mode=mode, scroll=y):
                self.assertIn("at 46% 150px" if got["optedIn"] else "at 46% -110px", got["light"])


#: The collapsed sidebar's mark: where it stands, the sidebar's clip (its
#: padding box, inside its 1 px edge and its scrollbar), the halo's box and
#: the flare's.
MINI_PROBE = r"""(function () {
  var sb = document.getElementById('mainSidebar'), w = sb.querySelector('.brand-eye-wrap');
  var s = sb.getBoundingClientRect(), r = w.getBoundingClientRect(), h = getComputedStyle(w, '::before');
  var f = getComputedStyle(w, '::after');
  return { mini: sb.classList.contains('mini'), cx: r.left + r.width / 2, cy: r.top + r.height / 2,
           clipLeft: s.left + sb.clientLeft, clipRight: s.left + sb.clientLeft + sb.clientWidth,
           halo: [h.width, h.height, h.opacity, h.transform], flare: [f.width, f.height, f.opacity, f.transform] };
})()"""


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class CollapsedMarkMeasuredTests(TestCase):
    """The Eye's halo in the collapsed sidebar (2026-11-13, the check of
    CR4), at DPR 2, under Magic at the breath's peak (3 s of its 6) and
    under Calm. The halo alone (its picture against the same picture with
    the halo hidden; the mark, the wordmark and the toggle hidden in both)
    adds nothing on the window's top row nor on the first and last columns
    inside the sidebar's clip: it fades out inside the window and the
    sidebar. Its largest step between neighbouring device pixels is 3
    levels. At ae1a803 the 70 px halo, at the breath's peak, still added
    23 levels on the window's top row, 17 and 21 on the sidebar's first and
    last columns (15, 10 and 12 under Calm), and stepped by 5.

    The flare there (2026-11-13, the check of b3421f6), held at its frames
    over the halo: the flare alone (its picture against the same picture
    with the flare hidden) adds nothing on that top row nor on those two
    columns either: its ring blooms whole inside the window and the
    sidebar."""

    CLIP = (0, 0, 120, 100)
    #: The flare's frames (1200 ms): under Magic, sv-eye-flare at its burst
    #: (144 ms: opacity 1, scale .9) and on its way out to 1.08 (420 and
    #: 700 ms); under Calm, sv-eye-glow at its brightest (240 ms: .6).
    FLARES = {"magic": ("sv-eye-flare", (144, 420, 700)), "calm": ("sv-eye-glow", (240,))}

    @classmethod
    def setUpTestData(cls):
        import numpy as np
        pages = {POSITIONS: _file_page(_get(_book("magic_mini"), POSITIONS))}
        b = _Browser(pages, "sv-magic-mini-")
        try:
            sid = b.tab(1440, 900)
            b.chrome.call("Emulation.setDeviceMetricsOverride",
                          {"width": 1440, "height": 900, "deviceScaleFactor": 2, "mobile": False}, session=sid)
            b.open(sid, POSITIONS, PROBES)
            b.js(sid, "(function () { document.getElementById('mainSidebar').classList.add('mini');"
                      " var s = document.createElement('style'); s.textContent ="
                      " '.sidebar-brand > :not(h1), .brand-eye-wrap > *, .brand-text { visibility: hidden !important; }';"
                      " document.head.appendChild(s); return 0; })()")
            cls.got, cls.flares = {}, {}
            for mode in ("magic", "calm"):
                b.js(sid, "(function () { __sv.mode('%s'); return __sv.settle().then(function () {"
                          " document.getAnimations().forEach(function (a) {"
                          "   if (a.animationName === 'sv-eye-breath') { a.pause(); a.currentTime = 3000; } });"
                          " return __sv.frame(); }).then(function () { return 0; }); })()" % mode)
                got = b.js(sid, MINI_PROBE)
                on = np.asarray(b.shot(sid, cls.CLIP), dtype=int)[..., 1]
                b.js(sid, "(function () { var s = document.createElement('style'); s.id = 'svProbeNoHalo';"
                          " s.textContent = '.brand-eye-wrap::before { visibility: hidden !important; }';"
                          " document.head.appendChild(s); return __sv.frame().then(function () { return 0; }); })()")
                off = np.asarray(b.shot(sid, cls.CLIP), dtype=int)[..., 1]
                b.js(sid, "(function () { document.getElementById('svProbeNoHalo').remove();"
                          " return __sv.frame().then(function () { return 0; }); })()")
                got.update(cls._halo(got, on - off, on.shape[1] / cls.CLIP[2]))
                cls.got[mode] = got
                # The flare, as a proven fill sets it (sv-moments.js adds
                # .sv-flare; this page runs no script, so nothing takes it
                # off), held at each of its frames.
                name, frames = cls.FLARES[mode]
                b.js(sid, "(function () { var w = document.querySelector('.brand-eye-wrap');"
                          " w.classList.remove('sv-flare'); void w.offsetWidth; w.classList.add('sv-flare');"
                          " return __sv.frame().then(function () { return 0; }); })()")
                for at in frames:
                    held = b.js(sid, "(function () { var n = 0; document.getAnimations().forEach(function (a) {"
                                     " if (a.animationName === '%s') { a.pause(); a.currentTime = %d; n++; } });"
                                     " return __sv.frame().then(function () { return n; }); })()" % (name, at))
                    flare = b.js(sid, MINI_PROBE)
                    on = np.asarray(b.shot(sid, cls.CLIP), dtype=int)[..., 1]
                    b.js(sid, "(function () { var s = document.createElement('style'); s.id = 'svProbeNoFlare';"
                              " s.textContent = '.brand-eye-wrap::after { visibility: hidden !important; }';"
                              " document.head.appendChild(s); return __sv.frame().then(function () { return 0; }); })()")
                    off = np.asarray(b.shot(sid, cls.CLIP), dtype=int)[..., 1]
                    b.js(sid, "(function () { document.getElementById('svProbeNoFlare').remove();"
                              " return __sv.frame().then(function () { return 0; }); })()")
                    flare.update(cls._halo(flare, on - off, on.shape[1] / cls.CLIP[2]), held=held)
                    cls.flares[(mode, at)] = flare
                b.js(sid, "(function () { document.querySelector('.brand-eye-wrap').classList.remove('sv-flare');"
                          " return __sv.frame().then(function () { return 0; }); })()")
        finally:
            b.close()

    @staticmethod
    def _halo(got, added, scale):
        """The halo (or the flare) alone (G levels, device px): what it
        adds on the window's top row and on the first and last columns
        inside the sidebar's clip, at its brightest and its least, and its
        largest step between neighbouring device px inside the clip."""
        import numpy as np
        inside = added[:, int(round(got["clipLeft"] * scale)):int(round(got["clipRight"] * scale))]
        step = max(int(np.abs(np.diff(inside, axis=1)).max()), int(np.abs(np.diff(inside, axis=0)).max()))
        return {"scale": scale, "top": int(inside[0].max()), "left": int(inside[:, 0].max()),
                "right": int(inside[:, -1].max()), "brightest": int(inside.max()), "least": int(inside.min()),
                "step": step}

    def test_the_sidebar_is_collapsed_and_read_at_dpr_2(self):
        for mode, got in sorted(self.got.items()):
            with self.subTest(mode=mode):
                self.assertTrue(got["mini"])
                self.assertEqual(got["scale"], 2)
                self.assertLess(got["clipRight"] - got["clipLeft"], 68)
        self.assertEqual(self.got["magic"]["halo"][2], "0.95")         # the breath's peak
        self.assertIn("1.06", self.got["magic"]["halo"][3])
        self.assertEqual(self.got["calm"]["halo"][2], "0.7")

    def test_the_halo_fades_out_inside_the_window_and_the_sidebar(self):
        for mode, got in sorted(self.got.items()):
            with self.subTest(mode=mode):
                self.assertGreaterEqual(got["brightest"], 20, got)              # the halo is there
                self.assertGreaterEqual(got["least"], -1, got)                  # it only adds
                self.assertEqual((got["top"], got["left"], got["right"]), (0, 0, 0), got)

    def test_the_halo_s_largest_step_is_3_levels(self):
        for mode, got in sorted(self.got.items()):
            with self.subTest(mode=mode):
                self.assertLessEqual(got["step"], 3, got)

    def test_the_flare_blooms_whole_inside_the_window_and_the_sidebar(self):
        """At b3421f6 the 70 px flare, its ring 31.5 px from the mark's
        centre at its burst, was cut by the window at the top and by the
        sidebar on both sides: at its burst it added 193 levels where the
        ring met the window's top row, 69 at 420 ms and 20 at 700 ms, and
        as much on the sidebar's first and last columns; Calm's glow 28 at
        the top and 18 to 25 at the sides (the check, overlay and classic
        scrollbars). At 50 px it adds nothing on any of them."""
        self.assertEqual(sorted(self.flares), [("calm", 240), ("magic", 144), ("magic", 420), ("magic", 700)])
        for (mode, at), got in sorted(self.flares.items()):
            with self.subTest(mode=mode, at=at):
                self.assertTrue(got["mini"])
                self.assertEqual(got["held"], 1, got)                           # its frame, held
                self.assertGreaterEqual(got["brightest"], 10, got)              # the flare is there
                self.assertGreaterEqual(got["least"], -1, got)                  # it only adds
                self.assertEqual((got["top"], got["left"], got["right"]), (0, 0, 0), got)
        burst = self.flares[("magic", 144)]["flare"]
        self.assertEqual(burst[2], "1")                                         # the burst at its brightest
        self.assertIn("matrix(0.9, 0, 0, 0.9,", burst[3])
        self.assertEqual(self.flares[("calm", 240)]["flare"][2], "0.6")


FACE_PROBE = r"""(function () {
  var out = { title: [], card: [], nav: [], figures: [], money: [], orbDigits: 0, small: [] };
  out.brand = getComputedStyle(document.querySelector('.sidebar-brand .brand-text')).fontFamily.replace(/"/g, '');
  function fam(el) { return getComputedStyle(el).fontFamily.replace(/"/g, ''); }
  function shown(el) { return el.getClientRects().length > 0; }
  Array.prototype.forEach.call(document.querySelectorAll('.topbar-title'), function (e) { out.title.push(fam(e)); });
  Array.prototype.forEach.call(document.querySelectorAll('.card-title, .sv-panel-title'), function (e) { out.card.push(fam(e)); });
  Array.prototype.forEach.call(document.querySelectorAll('.sidebar .nav-link'), function (e) { out.nav.push(fam(e)); });
  var i = 0;
  Array.prototype.forEach.call(document.body.querySelectorAll('*'), function (el) {
    if (el.closest('script, style, noscript, template, .grid-bg, .eye-glow-shadow, .globe-eye-bg, .globe-circuits-bg')) return;
    var own = '';
    for (var k = 0; k < el.childNodes.length; k++) if (el.childNodes[k].nodeType === 3) own += el.childNodes[k].nodeValue;
    own = own.trim();
    if (!own) return;
    var f = fam(el), orb = /^Orbitron/.test(f);
    if (orb && /(^|[^\w-])(BUY|SELL|REAL|LONG|SHORT)(?![\w-])/i.test(own)) out.money.push(__sv.name(el) + ': ' + own.slice(0, 40));
    if (orb && /\d/.test(own) && shown(el)) { el.setAttribute('data-orb-probe', i++); out.orbDigits++; }
    if (shown(el) && /\d/.test(own) && !/[A-Za-z]/.test(own) && !/^(JetBrains Mono|Inter)/.test(f)) out.figures.push(__sv.name(el) + ' ' + own.slice(0, 16) + ' in ' + f.slice(0, 30));
  });
  out.probes = Array.prototype.map.call(document.querySelectorAll('[data-orb-probe]'), function (el) {
    var own = '';
    for (var k = 0; k < el.childNodes.length; k++) if (el.childNodes[k].nodeType === 3) own += el.childNodes[k].nodeValue;
    return { name: __sv.name(el), text: own.trim(), letters: own.replace(/\d/g, '').length };
  });
  return out;
})()"""


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class FacesMeasuredTests(TestCase):
    """The faces as the browser computes them on /command/, /positions/, an
    instrument page whose symbol holds digits, and the kit, at 1280, 1440
    and 1920. No face is fetched here (no network): a face of the machine
    stands in for Orbitron, with the very characters the shell's link asks
    Google for, so a digit in a title falls to the next face exactly as it
    does with the real subset."""

    URLS = (COMMAND, POSITIONS, INSTRUMENT, KIT_URL)
    VIEWPORTS = ((1280, 800), (1440, 900), (1920, 1080))
    #: A serif of the machine: nothing else on these pages is drawn in one.
    STANDINS = ("DejaVu Serif", "Liberation Serif", "Times New Roman")

    @classmethod
    def setUpTestData(cls):
        link = [l for l in re.findall(r'href="(https://fonts\.googleapis\.com/[^"]+)"', read(BASE))
                if "Orbitron" in l][0].replace("&amp;", "&")
        text = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)["text"][0]
        ranges = ", ".join("U+%04X" % ord(ch) for ch in sorted(set(text)))
        standin = ("(function () { var st = document.createElement('style');"
                   " st.textContent = '@font-face { font-family: \"Orbitron\"; font-weight: 400 900;"
                   " src: local(\"DejaVu Serif\"), local(\"Liberation Serif\"), local(\"Times New Roman\");"
                   " unicode-range: %s; }'; document.head.appendChild(st);"
                   " return document.fonts.load('600 12px Orbitron', 'A').then(function (f) { return f.length; }); })()"
                   % ranges)
        pages = {u: _file_page(m) for u, m in _pages(_book("magic_faces"), cls.URLS).items()}
        b = _Browser(pages, "sv-magic-faces-")
        try:
            cls.got, cls.standin = {}, None
            for width, height in cls.VIEWPORTS:
                sid = b.tab(width, height)
                for url in cls.URLS:
                    b.open(sid, url, PROBES)
                    cls.standin = b.js(sid, standin)
                    got = b.js(sid, FACE_PROBE)
                    got["fonts"] = b.fonts(sid, "[data-orb-probe]") if cls.standin else []
                    cls.got[(url, width)] = got
        finally:
            b.close()

    def test_titles_compute_orbitron_and_nav_rows_rajdhani(self):
        for key, got in sorted(self.got.items()):
            with self.subTest(page=key):
                self.assertTrue(got["title"] and got["nav"], key)
                if key[0] != COMMAND:           # the Operations Center has tabs, no card title
                    self.assertTrue(got["card"], key)
                for f in got["title"] + got["card"] + [got["brand"]]:
                    self.assertTrue(f.startswith("Orbitron, JetBrains Mono, Inter"), f)
                for f in got["nav"]:
                    self.assertTrue(f.startswith("Rajdhani, Inter"), f)

    def test_no_digit_is_drawn_in_orbitron(self):
        """For every element that computes Orbitron and holds a digit, the
        stand-in drew no more glyphs than the text has characters other
        than digits; on the kit's probe title it drew the letters and no
        digit."""
        if not self.standin:
            self.skipTest("no local face to stand in for Orbitron on this machine")
        probed = 0
        for key, got in sorted(self.got.items()):
            self.assertEqual(len(got["fonts"]), len(got["probes"]))
            for probe, fonts in zip(got["probes"], got["fonts"]):
                probed += 1
                standin = sum(f["glyphs"] for f in fonts if f["family"] in self.STANDINS)
                digits = len(re.findall(r"\d", probe["text"]))
                with self.subTest(page=key, element=probe["name"], text=probe["text"][:30]):
                    self.assertLessEqual(standin, probe["letters"])
                    self.assertGreaterEqual(sum(f["glyphs"] for f in fonts if f["family"] not in self.STANDINS),
                                            digits)
                    if probe["text"] == "SYN100 · 30D WINDOW #12":
                        self.assertGreaterEqual(standin, 12)
        self.assertGreater(probed, 6)
        titles = [p["text"] for p in self.got[(INSTRUMENT, 1440)]["probes"] if "topbar-title" in p["name"]]
        self.assertEqual(titles, ["SYN100 — SYN100"])

    def test_no_orbitron_text_holds_a_money_word(self):
        for key, got in sorted(self.got.items()):
            with self.subTest(page=key):
                self.assertEqual(got["money"], [])

    def test_every_bare_figure_computes_the_number_face_or_inter(self):
        for key, got in sorted(self.got.items()):
            with self.subTest(page=key):
                self.assertEqual(got["figures"], [])


HERO_PROBE = r"""(async function () {
  var out = {};
  for (var m of ['magic', 'calm', 'off']) {
    __sv.mode(m); await __sv.frame();
    out[m] = {};
    ['hero-live', 'hero-stale', 'hero-real'].forEach(function (k) {
      var el = document.querySelector('[data-kit="' + k + '"]');
      out[m][k] = [getComputedStyle(el, '::before').content, getComputedStyle(el, '::after').content,
                   getComputedStyle(el, '::before').backgroundImage.slice(0, 15)];
    });
  }
  __sv.mode('magic'); await __sv.frame();
  out.band = [];
  Array.prototype.forEach.call(document.querySelectorAll('.sv-panel--hero'), function (h) {
    var r = h.getBoundingClientRect();
    __sv.figureNodes().forEach(function (f) {
      var range = document.createRange(); range.selectNodeContents(f[0]);
      Array.prototype.forEach.call(range.getClientRects(), function (q) {
        if (q.bottom > r.top - 15 && q.top < r.top && q.right > r.left && q.left < r.right) out.band.push(f[2].slice(0, 24));
      });
    });
  });
  out.pill = (function () { var p = document.querySelector('.sv-page-head .sv-pill--solid'), c = getComputedStyle(p);
                            return [c.backgroundColor, c.textShadow, /\d/.test(p.textContent)]; })();
  out.halo = getComputedStyle(document.querySelector('.sv-page-head.sv-on-void')).textShadow;
  return out;
})()"""


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class KitMagicMeasuredTests(TestCase):
    """The kit page's magic specimens at 1440: the hero card lit only while
    its figure is live and never around REAL; the moments at their peak,
    played by hand (SV.moments.play, as the page's play buttons do), with
    static/js/sv-moments.js as it ships."""

    HEIGHTS = ("28", "32", "44")

    @classmethod
    def setUpTestData(cls):
        client = _book("magic_kit")
        pages = {KIT_URL: _file_page(_get(client, KIT_URL), scripts=("sv-moments.js",))}
        b = _Browser(pages, "sv-magic-kit-")
        try:
            sid = b.tab()
            b.open(sid, KIT_URL, PROBES)
            cls.hero = b.js(sid, HERO_PROBE)
            # The moments: the page is settled, then each moment is played
            # and its own animations are held at two instants of their life.
            hold = ("(function (t) { document.getAnimations().forEach(function (a) {"
                    " var n = a.animationName || '';"
                    " if (/^sv-(light|moment|eye-flare|eye-glow|flash)/.test(n)) { a.pause(); a.currentTime = t; } });"
                    " return __sv.frame().then(function () { return 0; }); })")
            b.js(sid, "__sv.mode('magic'); document.querySelector('[data-kit=\"moments\"]').scrollIntoView(); 0")
            # Settled, and read once as each peak will be read, so the first
            # picture and the later ones are of one layout.
            b.js(sid, "__sv.settle().then(function () { __sv.figures(); return __sv.frame(); }).then(function () { return 0; })")
            # The two floating orbs (Ask Sauron, Gollum) are drawn on layers
            # of their own, and headless Chromium redraws them a fraction of
            # a pixel apart from one frame to the next, moment or not: they
            # are held out of the pictures and checked by their boxes.
            cls.orbs = b.js(sid, "__sv.boxes('.gollum-fab, .se-eye-fab')")
            b.js(sid, "(function () { Array.prototype.forEach.call(document.querySelectorAll('.gollum-fab, .se-eye-fab'),"
                      " function (e) { e.style.visibility = 'hidden'; }); return __sv.frame().then(function () { return 0; }); })()")
            cls.buttons = b.js(sid, "__sv.boxes('button, .btn')")
            # Where a moment's light is, at this instant: the row's light,
            # the flare at its widest, the card's edge, the icon's light.
            # Updated deliberately (the desk v2 board, approved 2026-11-13:
            # "amazing work, bravo, I need it fast!!"): the flare's box is
            # its own circle at its largest scale (1.08, the kit's
            # sv-eye-flare) plus 2 px, as it computes on the page, not the
            # 70 px circle at the 1.9 it no longer reaches; in the 44 px
            # head the menu's first fold button sits 6 px under the head.
            lights = ("(function () { var out = []; function box(e, pad) { var r = e.getBoundingClientRect();"
                      " return [r.left - pad, r.top - pad, r.width + 2 * pad, r.height + 2 * pad]; }"
                      " Array.prototype.forEach.call(document.querySelectorAll('.sv-row-light'), function (e) { out.push(box(e, 0)); });"
                      " var w = document.querySelector('.brand-eye-wrap.sv-flare');"
                      " if (w) { var r = w.getBoundingClientRect(), R = (parseFloat(getComputedStyle(w, '::after').width) || 70) * 1.08 / 2 + 2;"
                      " out.push([r.left + r.width / 2 - R, r.top + r.height / 2 - R, 2 * R, 2 * R]); }"
                      " Array.prototype.forEach.call(document.querySelectorAll('.sv-moment-arrive'), function (e) { var q = box(e, 0); out.push([q[0], q[1], q[2], 2]); });"
                      " Array.prototype.forEach.call(document.querySelectorAll('.sv-moment-icon'), function (e) { out.push(box(e, 4)); });"
                      " return out; })()")
            rest = b.shot(sid)
            cls.peaks = {}
            plays = [("fill-" + h, "SV.moments.play('fill', document.querySelector('[data-kit-row=\"%s\"]'))" % h)
                     for h in cls.HEIGHTS]
            plays += [("signal", "SV.moments.play('signal', document.querySelector('[data-kit-card]'), document.querySelector('[data-kit-icon]'))"),
                      ("stop", "SV.moments.play('stop', document.querySelector('[data-kit-stop]'))"),
                      ("close", "SV.moments.play('close')")]
            for name, play in plays:
                b.js(sid, "(function () { %s; return 0; })()" % play)
                for at in (150, 450):
                    running = b.js(sid, "document.getAnimations().map(function (a) { return a.animationName; })")
                    b.js(sid, hold + "(%d)" % at)
                    cls.peaks[(name, at)] = {"figures": b.js(sid, "__sv.figures()"), "shot": b.shot(sid),
                                             "running": running, "where": b.js(sid, lights),
                                             "lights": b.js(sid, "document.querySelectorAll('.sv-row-light').length")}
                # let it end, as animationend would
                b.js(sid, "(function () { document.getAnimations().forEach(function (a) { var n = a.animationName || '';"
                          " if (/^sv-(light|moment|eye-flare|eye-glow|flash)/.test(n)) a.finish(); });"
                          " return new Promise(function (r) { setTimeout(r, 60); }).then(function () { return 0; }); })()")
            cls.rest = rest
            cls.left = b.js(sid, "[document.querySelectorAll('.sv-row-light').length,"
                                 " document.querySelectorAll('.sv-moment-arrive, .sv-moment-icon, .sv-flare').length]")
            # A fill played live: the P&L cell's colour, every 50 ms.
            cls.colours = b.js(sid, "(function () {"
                                    " var cell = document.querySelector('[data-kit-row=\"32\"] [data-kit-pnl]'), seen = {};"
                                    " SV.moments.play('fill', document.querySelector('[data-kit-row=\"32\"]'));"
                                    " return new Promise(function (r) { var n = 0, t = setInterval(function () {"
                                    "   seen[getComputedStyle(cell).color] = 1; if (++n >= 24) { clearInterval(t); r(Object.keys(seen)); } }, 50); }); })()")
        finally:
            b.close()

    def test_a_hero_is_lit_only_while_its_figure_is_live_and_never_around_real(self):
        for mode in ("magic", "calm"):
            with self.subTest(mode=mode):
                self.assertEqual(self.hero[mode]["hero-live"], ['""', '""', "linear-gradient"])
                self.assertEqual(self.hero[mode]["hero-stale"][:2], ["none", "none"])
                self.assertEqual(self.hero[mode]["hero-real"][:2], ["none", "none"])
        for k in ("hero-live", "hero-stale", "hero-real"):
            self.assertEqual(self.hero["off"][k][:2], ["none", "none"], k)

    def test_the_band_above_a_hero_holds_no_figure(self):
        self.assertEqual(self.hero["band"], [])

    def test_a_page_head_s_figure_sits_on_an_opaque_pill_with_no_halo(self):
        bg, shadow, has_digit = self.hero["pill"]
        self.assertEqual(bg, "rgb(%d, %d, %d)" % hex_rgb(PALETTE["--sv-bg-1"]))
        self.assertEqual(shadow, "none")
        self.assertTrue(has_digit)
        self.assertEqual(self.hero["halo"].count("rgb(%d, %d, %d)" % hex_rgb(PALETTE["--sv-bg-0"])), 3)

    def test_each_moment_plays(self):
        for h in self.HEIGHTS:
            self.assertEqual(self.peaks[("fill-" + h, 150)]["lights"], 1, h)
            self.assertIn("sv-light-run", self.peaks[("fill-" + h, 150)]["running"])
            self.assertIn("sv-eye-flare", self.peaks[("fill-" + h, 150)]["running"])
        self.assertIn("sv-moment-icon", self.peaks[("signal", 150)]["running"])
        self.assertIn("sv-eye-flare-soft", self.peaks[("close", 150)]["running"])
        self.assertTrue(any(n.startswith("sv-flash") for n in self.peaks[("stop", 150)]["running"]))
        self.assertEqual(self.left, [0, 0])       # each light leaves when it ends

    def test_no_figure_is_lit_at_a_moment_s_peak(self):
        for key, got in sorted(self.peaks.items()):
            with self.subTest(moment=key):
                self.assertGreater(got["figures"]["figures"], 60)
                self.assertEqual(got["figures"]["lit"], [])
                self.assertEqual(got["figures"]["glass"], [])
                self.assertEqual(got["figures"]["onVoid"], [])

    def test_no_moment_paints_inside_a_button(self):
        """At each moment's peak, at row heights 28, 32 and 44 px, no pixel
        inside any button's box moves by more than 2 levels."""
        from PIL import ImageChops
        self.assertGreater(len(self.buttons), 12)
        self.assertGreaterEqual(len([b for b in self.buttons if b["text"] == "Close"]), 3)
        self.assertEqual(len(self.orbs), 2)
        for key, got in sorted(self.peaks.items()):
            diff = ImageChops.difference(self.rest, got["shot"])
            self.assertIsNotNone(diff.getbbox(), key)        # the moment is on the picture
            # By its box, no light reaches a button, the two orbs included
            # (a stop that moved plays the approved wash and no light).
            self.assertEqual(bool(got["where"]), key[0] != "stop", key)
            for lx, ly, lw, lh in got["where"]:
                for b in self.buttons + self.orbs:
                    apart = (lx + lw <= b["x"] or b["x"] + b["w"] <= lx or ly + lh <= b["y"] or b["y"] + b["h"] <= ly)
                    with self.subTest(moment=key, button=b["text"] or b["name"], light=(round(lx), round(ly))):
                        self.assertTrue(apart)
            for b in self.buttons:
                box = (int(b["x"]), int(b["y"]), int(b["x"] + b["w"] + 0.999), int(b["y"] + b["h"] + 0.999))
                worst = max(hi for lo, hi in diff.crop(box).getextrema())
                with self.subTest(moment=key, button=b["text"] or b["name"]):
                    self.assertLessEqual(worst, 2)

    def test_a_fill_never_changes_the_p_and_l_s_colour(self):
        self.assertEqual(len(self.colours), 1, self.colours)


EMBER_COUNTER = r"""(function () {
  var P = CanvasRenderingContext2D.prototype, n = window.__svCalls = {};
  function ours(ctx) { return ctx.canvas && ctx.canvas.id === 'particles-canvas'; }
  Object.getOwnPropertyNames(P).forEach(function (k) {
    var d = Object.getOwnPropertyDescriptor(P, k);
    if (d && typeof d.value === 'function') {
      P[k] = function () { if (ours(this)) n[k] = (n[k] || 0) + 1; return d.value.apply(this, arguments); };
    } else if (d && d.set && k === 'font') {
      Object.defineProperty(P, k, { get: d.get, set: function (v) { if (ours(this)) n['font='] = (n['font='] || 0) + 1; d.set.call(this, v); } });
    }
  });
})();"""

EMBER_WINDOW = r"""(function (ms) {
  var s = window.__svEmberStats, c = window.__svCalls;
  function total() { var t = 0; for (var k in c) t += c[k]; return t; }
  function text() { return (c.fillText || 0) + (c.strokeText || 0) + (c['font='] || 0); }
  var f0 = s ? s.frames : 0, t0 = total(), x0 = text();
  return new Promise(function (r) { setTimeout(function () {
    var frames = (s ? s.frames : 0) - f0;
    r({ frames: frames, calls: total() - t0, text: text() - x0, embers: s ? s.embers : -1, ash: s ? s.ash : -1,
        maps: s ? s.maps : -1, display: getComputedStyle(document.getElementById('particles-canvas')).display,
        slice: s ? s.sliceMax : 0, draw: s && s.recent().length ? s.recent().reduce(function (a, b) { return a + b; }, 0) / s.recent().length : 0 });
  }, ms); });
})"""


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class EmbersMeasuredTests(TestCase):
    """static/js/sv-embers.js as it ships, on /positions/ and /command/ at
    1440: counts are asserted, times only reported. Under Magic at most 31
    frames a second are drawn, with at most 100 canvas calls a frame and no
    text call; under Calm and Off, and on a page that has not opted in, the
    canvas is not displayed and no frame is drawn in 2 s."""

    #: Updated deliberately (the desk v2 board, approved 2026-11-13: "amazing
    #: work, bravo, I need it fast!!"): its frame keeps 16 px gutters, so at
    #: 1440 x 900 /command/ shows no void of its own any more (no gutter of
    #: 24 px, the field's own rule) and rightly draws nothing. The measure
    #: hides the page's hero, at the top, to give the field a void there:
    #: every count below still runs on that page's shell and the script as
    #: it ships.
    VOID_FOR = {COMMAND: "<style>.oc-hero { visibility: hidden !important; }</style>"}

    @classmethod
    def setUpTestData(cls):
        pages = {u: _file_page(m, scripts=("sv-embers.js",), before=EMBER_COUNTER)
                 for u, m in _pages(_book("magic_embers"), (POSITIONS, COMMAND)).items()}
        for u, style in cls.VOID_FOR.items():
            pages[u] = pages[u].replace("</head>", style + "</head>", 1)
        b = _Browser(pages, "sv-magic-embers-")
        try:
            sid = b.tab()
            cls.got = {}
            for url in (POSITIONS, COMMAND):
                b.open(sid, url, PROBES)
                got = {}
                b.js(sid, "(function () { return new Promise(function (r) { var n = 0, t = setInterval(function () {"
                          " if ((window.__svEmberStats && __svEmberStats.maps) || ++n > 100) { clearInterval(t); r(0); } }, 50); }); })()")
                got["magic"] = b.js(sid, EMBER_WINDOW + "(2000)")
                for mode in ("calm", "off"):
                    b.js(sid, "__sv.mode('%s'); __sv.frame().then(function () { return 0; })" % mode)
                    got[mode] = b.js(sid, EMBER_WINDOW + "(2000)")
                b.js(sid, "__sv.mode('magic'); __sv.frame().then(function () { return 0; })")
                got["back"] = b.js(sid, EMBER_WINDOW + "(1000)")
                b.js(sid, "document.body.classList.add('sv-scroll-locked'); __sv.frame().then(function () { return 0; })")
                got["dialog"] = b.js(sid, EMBER_WINDOW + "(1000)")
                b.js(sid, "document.body.classList.remove('sv-scroll-locked');"
                          " document.dispatchEvent(new CustomEvent('sv:pin-locked')); __sv.frame().then(function () { return 0; })")
                got["locked"] = b.js(sid, EMBER_WINDOW + "(1000)")
                # Review 2026-11-12: the "?" shortcut sheet is base.html's
                # own modal (not SV.overlay's): open, no frame.
                b.js(sid, "document.dispatchEvent(new CustomEvent('sv:pin-unlocked'));"
                          " document.getElementById('kbdModalOverlay').classList.add('open');"
                          " __sv.frame().then(function () { return 0; })")
                got["kbd"] = b.js(sid, EMBER_WINDOW + "(1000)")
                # A resize while a dialog's scrim holds the page: the map
                # waits for it to close, and the field draws again after.
                b.js(sid, "document.getElementById('kbdModalOverlay').classList.remove('open');"
                          " (function () { var s = document.createElement('div'); s.id = 'svProbeScrim';"
                          " s.style.cssText = 'position:fixed;inset:0;z-index:5000;background:rgba(0,0,0,.6)';"
                          " document.body.appendChild(s); document.body.classList.add('sv-scroll-locked');"
                          " window.dispatchEvent(new Event('resize'));"
                          " return new Promise(function (r) { setTimeout(function () { r(0); }, 1200); }); })()")
                b.js(sid, "document.getElementById('svProbeScrim').remove();"
                          " document.body.classList.remove('sv-scroll-locked'); 0")
                got["afterHold"] = b.js(sid, EMBER_WINDOW + "(2000)")
                b.js(sid, "document.body.removeAttribute('data-sv-embers'); __sv.frame().then(function () { return 0; })")
                got["notOptedIn"] = b.js(sid, EMBER_WINDOW + "(2000)")
                cls.got[url] = got
            still = b.tab(reduced=True)
            b.open(still, POSITIONS, PROBES)
            # Each map draws its still frame (the first, then one when the
            # faces are ready): the watch starts once the maps have stopped.
            b.js(still, "(function () { return new Promise(function (r) { var n = 0, last = -1, same = 0, t = setInterval(function () {"
                        " var m = window.__svEmberStats ? __svEmberStats.maps : 0; same = m && m === last ? same + 1 : 0; last = m;"
                        " if (same >= 12 || ++n > 200) { clearInterval(t); r(0); } }, 50); }); })()")
            cls.reducedMaps = b.js(still, "__svEmberStats.maps")
            cls.reduced = b.js(still, EMBER_WINDOW + "(1500)")
            cls.reducedDrawn = b.js(still, "window.__svCalls.drawImage || 0")
        finally:
            b.close()

    def test_magic_draws_at_most_31_frames_a_second_and_100_calls_a_frame(self):
        for url, got in sorted(self.got.items()):
            m = got["magic"]
            with self.subTest(url=url):
                self.assertEqual(m["display"], "block")
                self.assertTrue(0 < m["embers"] <= 56, m)
                self.assertLessEqual(m["ash"], 12)
                self.assertGreater(m["frames"], 0)
                self.assertLessEqual(m["frames"], 62)
                self.assertLessEqual(m["calls"] / m["frames"], 100)
                self.assertEqual(m["text"], 0)

    def test_no_frame_under_calm_or_off_or_without_the_opt_in(self):
        for url, got in sorted(self.got.items()):
            for state in ("calm", "off", "notOptedIn"):
                with self.subTest(url=url, state=state):
                    self.assertEqual(got[state]["display"], "none")
                    self.assertEqual((got[state]["frames"], got[state]["calls"]), (0, 0), got[state])

    def test_no_frame_while_a_dialog_holds_the_page_or_the_lock_is_up(self):
        for url, got in sorted(self.got.items()):
            with self.subTest(url=url):
                self.assertGreater(got["back"]["frames"], 0)     # back on Magic, no reload
                self.assertEqual(got["dialog"]["frames"], 0, got["dialog"])
                self.assertEqual(got["locked"]["frames"], 0, got["locked"])

    def test_the_shortcut_sheet_holds_the_field_and_a_hold_never_empties_it(self):
        """Review 2026-11-12: under the "?" sheet no frame is drawn; and a
        resize while a dialog's scrim holds the page no longer maps the
        scrim (no void, no ember, no frame until the next scroll): the
        field draws again once the hold ends."""
        for url, got in sorted(self.got.items()):
            with self.subTest(url=url):
                self.assertEqual(got["kbd"]["frames"], 0, got["kbd"])
                self.assertGreater(got["afterHold"]["embers"], 0, got["afterHold"])
                self.assertGreaterEqual(got["afterHold"]["frames"], 10, got["afterHold"])

    def test_reduced_motion_draws_one_still_frame(self):
        self.assertEqual(self.reduced["frames"], 0)
        self.assertGreater(self.reducedMaps, 0)
        self.assertGreater(self.reducedDrawn, 0)
        self.assertEqual(self.reduced["calls"], 0)       # nothing after the still frame


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class WordsOnTheVoidMeasuredTests(TestCase):
    """Words on the void keep 4.5:1 with the brightest ember the field
    would draw behind them: the kit's page head, the field's largest sprite
    stamped along each line at the alpha its own cap gives there (6, 12
    and 18 px above and below the line too), against the brightest pixel
    within 2 px of the glyphs."""

    OFFSETS = (0, -6, 6, -12, 12, -18, 18)

    @classmethod
    def setUpTestData(cls):
        from PIL import ImageChops, ImageFilter
        client = _book("magic_void")
        pages = {KIT_URL: _file_page(_get(client, KIT_URL), scripts=("sv-embers.js",))}
        b = _Browser(pages, "sv-magic-void-")
        try:
            sid = b.tab()
            b.open(sid, KIT_URL, PROBES)
            b.js(sid, "(function () { __sv.mode('magic'); document.body.setAttribute('data-sv-embers', '');"
                      " document.querySelector('.sv-page-head').scrollIntoView({ block: 'center' });"
                      " return new Promise(function (r) { var n = 0, t = setInterval(function () {"
                      "   if ((window.__svEmberStats && __svEmberStats.maps && __svEmberStats.words) || ++n > 100) {"
                      "     clearInterval(t); document.body.classList.add('sv-scroll-locked'); setTimeout(function () { r(0); }, 120); } }, 50); }); })()")
            # Settled, the words are read again where they now stand: under
            # load the map can read them while the page's entrance still
            # moves them (review 2026-11-12, a run read 4.42:1 that way).
            b.js(sid, "__sv.settle().then(function () { document.dispatchEvent(new CustomEvent('sv:live-swapped')); return 0; })")
            cls.words = b.js(sid, "Array.prototype.map.call(document.querySelectorAll('.sv-page-head .sv-overline, .sv-page-head .sv-page-head-lead'), function (e) {"
                                  " var r = e.getBoundingClientRect(), c = getComputedStyle(e);"
                                  " return { x: r.left, y: r.top, w: r.width, h: r.height, color: c.color, size: c.fontSize, text: e.textContent.trim().slice(0, 30) }; })")
            cls.stats = b.js(sid, "({ words: __svEmberStats.words, inside: __svEmberStats.alphaAt(%f, %f, 0.55),"
                                  " far: __svEmberStats.alphaAt(%f, %f, 0.55) })"
                             % ((cls.words[0]["x"] + 5, cls.words[0]["y"] + 5, cls.words[0]["x"] + 5, cls.words[0]["y"] - 400)
                                if cls.words else (0, 0, 0, 0)))
            cls.ratios = {}
            for i, wd in enumerate(cls.words):
                clip = (max(0, wd["x"] - 30), max(0, wd["y"] - 30), wd["w"] + 60, wd["h"] + 60)
                worst = None
                for dy in cls.OFFSETS:
                    b.js(sid, "(function () { var c = document.getElementById('particles-canvas'), g = c.getContext('2d');"
                              " g.setTransform(1, 0, 0, 1, 0, 0); g.clearRect(0, 0, c.width, c.height);"
                              " for (var x = %f; x <= %f; x += 56) __svEmberStats.stamp(x, %f);"
                              " return __sv.frame().then(function () { return 0; }); })()"
                         % (wd["x"], wd["x"] + wd["w"], wd["y"] + wd["h"] / 2 + dy))
                    b.js(sid, "__sv.settle()")
                    ink = b.shot(sid, clip)
                    b.js(sid, "document.querySelectorAll('.sv-page-head .sv-overline, .sv-page-head .sv-page-head-lead')[%d].style.color = 'transparent';"
                              " __sv.settle()" % i)
                    bare = b.shot(sid, clip)
                    b.js(sid, "document.querySelectorAll('.sv-page-head .sv-overline, .sv-page-head .sv-page-head-lead')[%d].style.color = '';"
                              " __sv.settle()" % i)
                    glyphs = ImageChops.difference(ink, bare).convert("L").point(lambda v: 255 if v > 24 else 0)
                    near = glyphs.filter(ImageFilter.MaxFilter(5))
                    brightest, px, mask = 0.0, bare.load(), near.load()
                    for yy in range(bare.size[1]):
                        for xx in range(bare.size[0]):
                            if mask[xx, yy]:
                                r, g, bl = px[xx, yy]
                                brightest = max(brightest, _luminance(r, g, bl))
                    m = re.match(r"rgb\((\d+), (\d+), (\d+)\)", wd["color"])
                    fg = _luminance(*(int(v) for v in m.groups()))
                    ratio = (max(fg, brightest) + 0.05) / (min(fg, brightest) + 0.05)
                    worst = ratio if worst is None else min(worst, ratio)
                    cls.glyphs = glyphs.getbbox()
                cls.ratios[wd["text"]] = worst
        finally:
            b.close()

    def test_the_field_dims_near_the_words(self):
        self.assertGreaterEqual(self.stats["words"], 1)
        self.assertLessEqual(self.stats["inside"], 0.18 + 1e-6)
        self.assertAlmostEqual(self.stats["far"], 0.55, places=6)

    def test_every_line_keeps_4_5_to_1_with_the_brightest_ember_behind_it(self):
        self.assertGreaterEqual(len(self.words), 2)
        self.assertIsNotNone(self.glyphs)
        for text, ratio in sorted(self.ratios.items()):
            with self.subTest(line=text):
                self.assertGreaterEqual(ratio, 4.5)


def _luminance(r, g, b):
    def lin(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
