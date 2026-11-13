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
    tightens; lower_budgets() below writes it, never upwards). A file
    absent from the budget must be at zero, so a new template starts
    clean. A failure prints file:line, the marker and the text.
  * THE MEASURED HALF (Chromium over its DevTools pipe; skipped where the
    machine has none): every routed page and the shell's states, as the
    browser computes them (tests/old_design_census.js, the sweep's
    collector ported), each scene's count of each marker held to its
    budget. Its notes are below, with its classes. It is tagged
    "old_design_measured" and runs as its own CI job, in four shards.

THE META-TEST (SourceGuardBitesTests, MeasuredGuardBitesTests): one old
marker added to a temp copy fails with its file and line (its page,
selector, property and value); removed, the copy passes.

THE MARKERS (the plan's "final guard", and the critic's hole 4):

  eye_literal     the Eye's literal green (#00E868, rgb(0, 232, 104))
                  outside the tokens and the magic's light sources;
  old_literal     its old companions and the old palette's literals
                  (#40FF90, #0A5028, #030806, #3A6850, #E83030, #D8B020,
                  #FFB000, #FF5E5E);
  old_token       var(--accent-dim), var(--accent-bright), var(--accent-glow);
  accent_role     var(--accent) as a text, border or outline colour outside
                  the roles the Eye keeps (focus, selection, the brand, the
                  active row, the empty-state mark);
  sub11           a font-size under 11 px (px, rem, the font shorthand, an
                  SVG attribute, a script's size);
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
                  (el.style.color = ..., cssText, setProperty);
  infinite        an endless animation outside the allowed three
                  (sv-heartbeat, sv-armed-beat, sv-eye-breath), an endless
                  SMIL animation;
  glass           a backdrop-filter;
  gradient        a gradient outside the void, the hero card's edge and the
                  active row's spill (and the magic's own light);
  glow            a coloured shadow with a blur (box-shadow, text-shadow,
                  drop-shadow), outside the magic's light sources;
  glyph_icon      a Unicode glyph or an emoji alone in a button, a link, an
                  icon slot or a pseudo-element's content: an icon that is
                  not the sprite's;
  scrollbar       a ::-webkit-scrollbar rule (or scrollbar-color) painting
                  a colour that is not a token: computed styles cannot see
                  scrollbars, so the source holds them;
  off_token_hex   in the emails and the Python that paints (the email
                  palette in sauron_tags.py, the PDF's in reports.py), a
                  hex colour that is not a token's value.

What is never counted: sv-tokens.css (it defines the palette, the light
mode it freezes and the magic's light), and in sv-kit.css the rules the
magic scopes to its ambience (data-sv-ambience: the wordmark, the Eye, the
active row, live dots, the selected tab, a live hero card's edge, a side's
inset light, the moments). A var() fallback behind a token is inert and is
not counted either.

THE FILE:LINE -> BATCH MAP (the critic's hole 5): OWNERS below names, for
every scanned file (and for the stretches of the shared files: base.html,
sauron.css, sv-overlay.css), the batch of batches.md that empties it.
Every counted marker has an owner, so none is left for B24 by default;
`batch_map()` prints the map, and the totals by batch.

Tests only. Synthetic data; no network, no broker, no model.

Run with:  python manage.py test tests.test_zero_old_design
"""
import base64
import collections
import contextlib
import copy
import html.parser
import io
import json
import mimetypes
import os
import pathlib
import re
import select
import subprocess
import time
import tokenize
import unicodedata
import unittest
import urllib.parse
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, tag

from tests.test_close_advice import CHROME, HOST, _Chrome

ROOT = pathlib.Path(settings.BASE_DIR)
BUDGET = ROOT / "tests" / "old_design_budget.json"

#: What the source half scans (the plan's list, with the bot program's
#: templates and the emails, which live under templates/).
SOURCES = ("templates/**/*.html", "bot_program/templates/**/*.html", "static/css/*.css",
           "static/js/*.js", "core/templatetags/*.py", "dashboard/views_bot_charts.py",
           "dashboard/reports.py")

MARKERS = ("eye_literal", "old_literal", "old_token", "accent_role", "sub11", "share_tech",
           "mono_generic", "old_face_load", "badge_side", "inline_visual", "js_style",
           "infinite", "glass", "gradient", "glow", "glyph_icon", "scrollbar", "off_token_hex")

#: The palette's definition: never counted.
TOKENS_SHEET = "static/css/sv-tokens.css"
KIT_SHEET = "static/css/sv-kit.css"
#: The magic's own scripts (2026-11-12, merged in #106): the embers' canvas
#: and the moments draw the Eye's light, which is theirs to draw.
MAGIC_SCRIPTS = ("static/js/sv-embers.js", "static/js/sv-moments.js")
#: The files whose hex colours must be token values (emails, PDF, tags).
PALETTE_FILES = re.compile(r"^(templates/email/|templates/newsletter/|core/templatetags/|"
                           r"dashboard/reports\.py$|dashboard/views_bot_charts\.py$)")

Hit = collections.namedtuple("Hit", "file line marker text")


# ── colours ─────────────────────────────────────────────────────────────

def _rgb(r, g, b):
    return r"rgba?\(\s*%s\s*[, ]\s*%s\s*[, ]\s*%s\b" % (r, g, b)


EYE_LITERAL = re.compile(r"#00e868\b|" + _rgb(0, 232, 104), re.I)
OLD_LITERAL = re.compile("|".join([
    r"#40ff90\b", _rgb(64, 255, 144), r"#0a5028\b", _rgb(10, 80, 40), r"#030806\b", _rgb(3, 8, 6),
    r"#3a6850\b", _rgb(58, 104, 80), r"#e83030\b", _rgb(232, 48, 48), r"#d8b020\b", _rgb(216, 176, 32),
    r"#ffb000\b", _rgb(255, 176, 0), r"#ff5e5e\b", _rgb(255, 94, 94)]), re.I)
OLD_TOKEN = re.compile(r"var\(\s*--accent-(?:dim|bright|glow)\s*[,)]")
ACCENT = re.compile(r"var\(\s*--accent\s*[,)]")
HEX = re.compile(r"(?<![\w&])#(?:[0-9a-f]{6}|[0-9a-f]{3})(?![0-9a-z])", re.I)

#: Properties that paint text, a border or an outline (accent_role).
TEXT_OR_BORDER = re.compile(r"^(color|-webkit-text-fill-color|caret-color|text-decoration(-color)?|"
                            r"border(-(top|right|bottom|left|block|inline)(-(start|end))?)?(-color)?|"
                            r"outline(-color)?|column-rule(-color)?)$")
#: Where the Eye may draw text or a border (plan §3.3): focus, selection,
#: the brand, the active nav row, the empty-state mark.
EYE_ROLE = re.compile(r":focus|:checked|\[aria-(selected|pressed|current|checked)|\.is-(active|selected|on)\b|"
                      r"\.active\b|\.selected\b|\.sidebar-brand|\.brand|empty-state|::selection")
VISUAL = re.compile(r"^(color|background(-[a-z]+)?|border(-[a-z]+)*|outline(-[a-z]+)?|font(-[a-z]+)?|"
                    r"letter-spacing|text-transform|text-shadow|box-shadow|filter|-webkit-text-fill-color|"
                    r"fill|stroke|text-decoration(-color)?)$")
ALLOWED_LOOPS = ("sv-heartbeat", "sv-armed-beat", "sv-eye-breath")
#: Where a gradient is the new look's own: the void, the hero card's edge,
#: the active row's spill (the measured half's GRAD_OK, the same list).
GRADIENT_OK = re.compile(r"(^|[\s,>+~(])(html|body)(?=$|[\s,:.\[#)>+~])|\.nav-link\.active|"
                         r"\.day-scheme-wrap|\.sv-panel--hero")
DARK = re.compile(r"^(transparent|black|#000(000)?|var\(\s*--(sv-bg-\d|bg-void|bg-primary|bg-secondary|"
                  r"sv-shadow-[a-z-]+)\s*\)|none|0)$", re.I)


def strip_var_fallbacks(value):
    """var(--x, fallback) -> var(--x): a literal that only stands behind a
    token is inert (nested var() read through)."""
    out, i, n = [], 0, len(value)
    while i < n:
        if value.startswith("var(", i):
            depth, j = 0, i
            while j < n:
                if value[j] == "(":
                    depth += 1
                elif value[j] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                j += 1
            inner = value[i + 4:j]
            name, depth = inner, 0
            for k, ch in enumerate(inner):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                elif ch == "," and depth == 0:
                    name = inner[:k]
                    break
            out.append("var(" + name.strip() + ")")
            i = j + 1
            continue
        out.append(value[i])
        i += 1
    return "".join(out)


def split_top(value, sep=","):
    out, depth, cur = [], 0, []
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [p.strip() for p in out if p.strip()]


def _coloured(colour):
    """Whether a shadow's colour lights: a colour with some light in it at
    some opacity, a token of the palette's hues, or currentColor."""
    c = colour.strip()
    if not c or DARK.match(c):
        return False
    if re.match(r"currentcolor$", c, re.I):
        return True
    m = re.match(r"rgba?\(\s*([\d.]+)\s*[, ]\s*([\d.]+)\s*[, ]\s*([\d.]+)(?:\s*[,/]\s*([\d.]+)(%?))?", c, re.I)
    if m:
        a = 1.0 if m.group(4) is None else float(m.group(4)) / (100 if m.group(5) else 1)
        return a > 0.04 and max(float(m.group(i)) for i in (1, 2, 3)) > 40
    m = re.match(r"#([0-9a-f]{3}|[0-9a-f]{6})([0-9a-f]{2})?$", c, re.I)
    if m:
        h = m.group(1)
        h = "".join(ch * 2 for ch in h) if len(h) == 3 else h
        a = int(m.group(2), 16) / 255 if m.group(2) else 1
        return a > 0.04 and max(int(h[i:i + 2], 16) for i in (0, 2, 4)) > 40
    m = re.match(r"var\(\s*--([\w-]+)\s*\)$", c)
    if m:
        return not re.match(r"(sv-)?(bg|line|shadow)", m.group(1))
    if c.startswith("color-mix("):
        return bool(re.search(r"--(sv-)?(eye|accent|up|down|real|demo|warn|ai|cat|gold|red|green|blue|purple|glow)", c))
    return bool(re.match(r"[a-z]+$", c, re.I))   # a named colour (white, gold…)


def glows(prop, value):
    """The coloured, blurred shadows of a declaration."""
    out = []
    if prop in ("box-shadow", "text-shadow", "-webkit-box-shadow"):
        for layer in split_top(value):
            colour = re.search(r"rgba?\([^)]*\)|hsla?\([^)]*\)|color-mix\((?:[^()]|\([^)]*\))*\)|"
                               r"var\(--[\w-]+\)|#[0-9a-f]{3,8}\b|currentcolor|\b[a-z]+\b\s*$", layer, re.I)
            if not colour:
                continue
            rest = layer.replace(colour.group(0), " ")
            lengths = re.findall(r"(-?[\d.]+)(px|em|rem)?(?![\w%])", rest.replace("inset", " "))
            nums = [float(v) for v, _u in lengths]
            if len(nums) >= 3 and nums[2] > 0 and _coloured(colour.group(0)):
                out.append(layer)
            elif re.fullmatch(r"\s*var\(--[\w-]+\)\s*", layer) and re.search(r"glow|halo", layer):
                out.append(layer)        # a glow token (sv-tokens.css names them --sv-glow-*)
    if prop in ("filter", "-webkit-filter"):
        for m in re.finditer(r"drop-shadow\(((?:[^()]|\([^)]*\))*)\)", value):
            inner = m.group(1)
            colour = re.search(r"rgba?\([^)]*\)|var\(--[\w-]+\)|#[0-9a-f]{3,8}\b|currentcolor|[a-z]+\s*$", inner, re.I)
            rest = inner.replace(colour.group(0), " ") if colour else inner
            nums = [float(v) for v in re.findall(r"(-?\d*\.?\d+)(?:px|em|rem)?(?![\w%(.])", rest)]
            if colour and len(nums) >= 3 and nums[2] > 0 and _coloured(colour.group(0)):
                out.append(m.group(0))
    return out


def font_px(value):
    v = value.replace("!important", "").strip()
    m = re.fullmatch(r"(\d*\.?\d+)px", v)
    if m:
        return float(m.group(1))
    m = re.fullmatch(r"(\d*\.?\d+)rem", v)
    if m:
        return float(m.group(1)) * 16
    return None


def font_shorthand_px(value):
    m = re.search(r"(?:^|\s)(\d*\.?\d+)(px|rem)(?:\s*/\s*[\d.]+[a-z%]*)?\s+[\"'a-zA-Z(]", value)
    if m:
        return float(m.group(1)) * (16 if m.group(2) == "rem" else 1)
    return None


def first_face(value):
    return split_top(value)[0].strip().strip("\"'").lower() if value.strip() else ""


# ── one declaration ─────────────────────────────────────────────────────

def declaration_markers(prop, raw, selector="", rule_decls=(), where=""):
    """[(marker, text)] for one CSS declaration. `selector` is the rule's
    (empty for a style attribute); `rule_decls` the rule's other
    (property, value) pairs; `where` the file."""
    prop = prop.strip().lower()
    value = strip_var_fallbacks(raw.strip())
    out = []
    magic = where == KIT_SHEET and "data-sv-ambience" in selector
    if not magic:
        if EYE_LITERAL.search(value):
            out.append(("eye_literal", value))
        if OLD_LITERAL.search(value):
            out.append(("old_literal", value))
    if OLD_TOKEN.search(value):
        out.append(("old_token", value))
    if TEXT_OR_BORDER.match(prop) and ACCENT.search(value) and not EYE_ROLE.search(selector):
        out.append(("accent_role", "%s: %s" % (prop, value)))
    if prop == "font-size":
        px = font_px(value)
        if px is not None and px < 11:
            out.append(("sub11", "%s: %s" % (prop, value)))
    if prop == "font":
        px = font_shorthand_px(value)
        if px is not None and px < 11:
            out.append(("sub11", "%s: %s" % (prop, value)))
    if prop in ("font-family", "font"):
        if re.search(r"share\s*tech\s*mono", value, re.I):
            out.append(("share_tech", value))
        family = value if prop == "font-family" else re.sub(r"^.*?\d[\w.%/]*\s+", "", value)
        if first_face(family) == "monospace":
            out.append(("mono_generic", value))
    if prop in ("animation", "animation-iteration-count") and re.search(r"\binfinite\b", value):
        names = value if prop == "animation" else dict(rule_decls).get("animation-name", "")
        if not any(n in names for n in ALLOWED_LOOPS):
            out.append(("infinite", "%s: %s" % (prop, value)))
    if prop in ("backdrop-filter", "-webkit-backdrop-filter") and value.lower() not in ("none", "initial", "unset"):
        out.append(("glass", "%s: %s" % (prop, value)))
    if (prop in ("background", "background-image", "border-image", "border-image-source")
            and re.search(r"(linear|radial|conic)-gradient\(", value)
            and not GRADIENT_OK.search(selector) and not magic):
        out.append(("gradient", "%s: %s" % (prop, value[:120])))
    if not magic:
        for g in glows(prop, value):
            out.append(("glow", "%s: %s" % (prop, g[:120])))
    if "::-webkit-scrollbar" in selector or prop == "scrollbar-color":
        if prop in ("background", "background-color", "border-color", "border", "color", "box-shadow",
                    "scrollbar-color", "outline", "border-left", "border-right", "border-top", "border-bottom"):
            colours = re.findall(r"#[0-9a-f]{3,8}\b|rgba?\([^)]*\)|var\(--[\w-]+\)|\b[a-z]+\b", value, re.I)
            off = [c for c in colours if not re.match(r"var\(--sv-|transparent$|none$|solid$|inset$|auto$", c, re.I)]
            if off:
                out.append(("scrollbar", "%s: %s" % (prop, value)))
    if prop == "content" and ICON_SELECTOR.search(selector) and not STOP_MARK.search(selector):
        text = value.strip()
        if len(text) >= 2 and text[0] in "\"'" and text[-1] == text[0]:
            if is_glyph_icon(_css_unescape(text[1:-1])):
                out.append(("glyph_icon", "content: " + text))
    return out


#: A pseudo-element's glyph counts as an icon where the plan says icons are
#: the sprite's (the final guard: the nav, the topbar, a button).
ICON_SELECTOR = re.compile(r"(^|[\s,>+~(])(button|a|summary|nav)(?=$|[\s,:.\[#)>+~])|\.btn\b|-btn\b|btn-|"
                           r"\.nav-|\.sidebar|\.topbar|\.um-|\.mobile-|\[role=.?button")
#: §10's stop variant: CLOSE ALL, all off and PAUSE wear ■ (the kit's mark).
STOP_MARK = re.compile(r"\.btn-stop\b")


def _css_unescape(s):
    return re.sub(r"\\([0-9a-f]{1,6})\s?", lambda m: chr(int(m.group(1), 16)), s, flags=re.I)


GLYPH_RANGES = ((0x2190, 0x21FF), (0x2300, 0x23FF), (0x2460, 0x24FF), (0x25A0, 0x25FF), (0x2600, 0x26FF),
                (0x2700, 0x27BF), (0x27C0, 0x27EF), (0x2900, 0x297F), (0x2B00, 0x2BFF), (0x2A00, 0x2AFF),
                (0x2200, 0x22FF), (0x1F000, 0x1FAFF), (0x2100, 0x214F), (0x29B0, 0x29FF))
NOT_ICONS = set("·—–…×±%+−-=<>/|.,:;!?'\"()[]{}&#*$€£¥@°")


def is_glyph_icon(text):
    """1 to 3 characters, every one a pictographic glyph or symbol (never
    letters, figures or the typographic marks words use)."""
    chars = [ch for ch in text if not ch.isspace() and ch not in "\ufe0f\ufe0e\u200d"]
    if not 1 <= len(chars) <= 3:
        return False
    for ch in chars:
        cp = ord(ch)
        if ch in NOT_ICONS or ch.isalnum():
            return False
        if not (any(a <= cp <= b for a, b in GLYPH_RANGES) or unicodedata.category(ch) == "So"):
            return False
    return True


# ── CSS ─────────────────────────────────────────────────────────────────

def _blank_comments(text, opener="/*", closer="*/"):
    """Comments replaced by spaces, newlines kept (line numbers hold);
    strings kept."""
    out, i, n, quote = [], 0, len(text), None
    while i < n:
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote or ch == "\n":
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if text.startswith(opener, i):
            j = text.find(closer, i + len(opener))
            j = n if j < 0 else j + len(closer)
            out.append("".join("\n" if c == "\n" else " " for c in text[i:j]))
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def css_rules(text, first_line=1):
    """[(selector, line, [(prop, value, line)])] of a style sheet. A rule
    inside @media or @supports keeps its own selector; a frame of
    @keyframes x is the selector "@keyframes x 50%"; @font-face is
    skipped."""
    t = _blank_comments(text)
    line_of, ln = [], first_line
    for ch in t:
        line_of.append(ln)
        if ch == "\n":
            ln += 1
    line_of.append(ln)
    rules, stack, i, n, start, quote = [], [], 0, len(t), 0, None

    def close_of(j):
        depth = 1
        while j < n and depth:
            if t[j] == "{":
                depth += 1
            elif t[j] == "}":
                depth -= 1
            j += 1
        return j

    while i < n:
        ch = t[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "{":
            prelude = t[start:i].strip()
            sel_line = line_of[start + len(t[start:i]) - len(t[start:i].lstrip())]
            if prelude.lower().startswith("@font-face"):
                i = start = close_of(i + 1)
                continue
            if prelude.startswith("@"):
                stack.append(prelude)
                i += 1
                start = i
                continue
            end = close_of(i + 1)
            frames = [p for p in stack if re.match(r"@(-webkit-)?keyframes", p, re.I)]
            selector = (frames[-1] + " " + prelude) if frames else prelude
            rules.append((selector, sel_line, _decls(t[i + 1:end - 1], i + 1, line_of)))
            i = start = end
            continue
        elif ch == "}":
            if stack:
                stack.pop()
            start = i + 1
        elif ch == ";":
            start = i + 1
        i += 1
    return rules


def _decls(body, offset, line_of):
    out, start, depth, quote = [], 0, 0, None
    for k, ch in enumerate(body + ";"):
        if quote:
            if ch == quote:
                quote = None
            continue
        if ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == ";" and depth <= 0:
            part = body[start:k]
            if ":" in part:
                prop, val = part.split(":", 1)
                lead = len(part) - len(part.lstrip())
                if prop.strip() and not prop.strip().startswith("{"):
                    out.append((prop.strip(), val.strip(), line_of[min(offset + start + lead, len(line_of) - 1)]))
            start = k + 1
    return out


def css_hits(text, rel, first_line=1):
    hits = []
    for selector, _line, decls in css_rules(text, first_line):
        pairs = tuple((p.lower(), v) for p, v, _l in decls)
        for prop, value, line in decls:
            for marker, detail in declaration_markers(prop, value, selector, pairs, rel):
                hits.append(Hit(rel, line, marker, "%s { %s }" % (selector[:80], detail[:140])))
    return hits


def style_attr_hits(style, rel, line):
    """The markers of one style attribute: inline_visual once if it carries
    a visual property, and each declaration's own markers."""
    hits, visual = [], []
    for part in split_top(style, ";"):
        if ":" not in part:
            continue
        prop, value = part.split(":", 1)
        prop = prop.strip().lower()
        if "{{" in prop or "{%" in prop:
            continue
        # A token the data picks (the kit page's specimens: var({{ token }}))
        # is data, as a bar's width is.
        if VISUAL.match(prop) and not re.fullmatch(r"\s*var\(\s*{{[^}]*}}\s*\)\s*", value):
            visual.append(prop)
        for marker, detail in declaration_markers(prop, value, "", (), rel):
            if marker != "accent_role" or TEXT_OR_BORDER.match(prop):
                hits.append(Hit(rel, line, marker, 'style="%s"' % style[:120]))
    if visual:
        hits.append(Hit(rel, line, "inline_visual", 'style="%s" (%s)' % (style[:110], ", ".join(visual[:4]))))
    return hits


# ── scripts ─────────────────────────────────────────────────────────────

JS_STYLE = re.compile(r"\.style\.(color|background|backgroundColor|backgroundImage|borderColor|"
                      r"border(?:Top|Right|Bottom|Left)?(?:Color)?|outline(?:Color)?|fontFamily|fontSize|"
                      r"fontWeight|boxShadow|textShadow|filter|cssText|webkitTextFillColor)\s*(\+?=)(?!=)|"
                      r"\.style\.setProperty\(\s*['\"](color|background(?:-color)?|border(?:-[a-z]+)?|"
                      r"font-[a-z]+|box-shadow|text-shadow|filter)['\"]")
JS_STYLE_ATTR = re.compile(r"""style=\\?(["'])(.*?)\\?\1""")


def _blank_js_comments(text):
    """// and /* */ comments blanked, strings and template literals kept,
    newlines kept."""
    out, i, n, quote = [], 0, len(text), None
    while i < n:
        ch = text[i]
        if quote:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == quote or (ch == "\n" and quote != "`"):
                quote = None
            i += 1
            continue
        if ch in "\"'`":
            quote = ch
            out.append(ch)
            i += 1
            continue
        if text.startswith("/*", i):
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            out.append("".join("\n" if c == "\n" else " " for c in text[i:j]))
            i = j
            continue
        if text.startswith("//", i) and (i == 0 or text[i - 1] not in ":\\"):
            j = text.find("\n", i)
            j = n if j < 0 else j
            out.append(" " * (j - i))
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def js_hits(text, rel, first_line=1):
    hits = []
    code = _blank_js_comments(text)
    lines = code.split("\n")
    for k, line_text in enumerate(lines):
        line = first_line + k
        if EYE_LITERAL.search(line_text):
            hits.append(Hit(rel, line, "eye_literal", line_text.strip()[:140]))
        if OLD_LITERAL.search(line_text):
            hits.append(Hit(rel, line, "old_literal", line_text.strip()[:140]))
        for _m in OLD_TOKEN.finditer(line_text):
            hits.append(Hit(rel, line, "old_token", line_text.strip()[:140]))
        if re.search(r"share\s*tech\s*mono", line_text, re.I):
            hits.append(Hit(rel, line, "share_tech", line_text.strip()[:140]))
        for m in re.finditer(r"font-size\s*:\s*(\d*\.?\d+)(px|rem)\b|fontSize\s*=\s*['\"](\d*\.?\d+)px|"
                             r"\bfont\s*=\s*['\"`][^'\"`]*?(?<![\w.])(\d*\.?\d+)px", line_text):
            raw = m.group(1) or m.group(3) or m.group(4)
            px = float(raw) * (16 if m.group(2) == "rem" else 1)
            if px < 11:
                hits.append(Hit(rel, line, "sub11", line_text.strip()[:140]))
        for m in JS_STYLE.finditer(line_text):
            hits.append(Hit(rel, line, "js_style", line_text.strip()[:140]))
        for m in re.finditer(r"(linear|radial|conic)-gradient\(", line_text):
            hits.append(Hit(rel, line, "gradient", line_text.strip()[:140]))
        if re.search(r"backdrop-filter\s*:\s*(?!none)|backdropFilter\s*=", line_text):
            hits.append(Hit(rel, line, "glass", line_text.strip()[:140]))
        for m in re.finditer(r"(box-shadow|text-shadow)\s*:\s*([^;'\"`]+)", line_text):
            for g in glows(m.group(1), strip_var_fallbacks(m.group(2))):
                hits.append(Hit(rel, line, "glow", line_text.strip()[:140]))
        for m in re.finditer(r"(?<![\w-])color\s*:\s*var\(--accent\)", line_text):
            hits.append(Hit(rel, line, "accent_role", line_text.strip()[:140]))
    # Style attributes a script builds into markup.
    for m in JS_STYLE_ATTR.finditer(code):
        line = first_line + code.count("\n", 0, m.start())
        for hit in style_attr_hits(m.group(2), rel, line):
            if hit.marker == "inline_visual":
                hits.append(hit)
    return hits


# ── templates ───────────────────────────────────────────────────────────

SIDE_WORD = re.compile(r"^(LONG|SHORT|BUY|SELL|BULL|BEAR|BULLISH|BEARISH|UP|DOWN|▲|▼|[▲▼]\s*\w+)$", re.I)
SIDE_EXPR = re.compile(r"\b(direction|side|dir|bias|is_long|is_short|long|short)\b", re.I)
#: Where a glyph is an icon the sprite owes (the final guard: the nav, the
#: topbar, a button): inside a button, a link, a disclosure, the nav or the
#: topbar, or anything dressed as a button.
ICON_HOST = re.compile(r"(^|\s)(topbar|sidebar|sidebar-nav|btn|[\w-]+-btn|btn-[\w-]+|nav-link|sv-phone-nav)(\s|$)")
DJ_TAG = re.compile(r"{%.*?%}|{{.*?}}|{#.*?#}", re.S)


class _Markup(html.parser.HTMLParser):
    """The markup facts of a template: style attributes, colour and size
    attributes, endless SMIL, side badges, glyph icons, font links. Its
    <style> and <script> bodies arrive blanked: they are read as a sheet
    and as a script."""

    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr",
            "param", "path", "circle", "rect", "line", "polyline", "polygon", "ellipse", "stop", "use"}

    def __init__(self, rel):
        super().__init__(convert_charrefs=True)
        self.rel, self.hits, self.stack = rel, [], []

    def _line(self):
        return self.getpos()[0]

    def handle_starttag(self, tag, attrs):
        a = dict((k.lower(), v or "") for k, v in attrs)
        line = self._line()
        if "style" in a and a["style"].strip():
            self.hits += style_attr_hits(a["style"], self.rel, line)
        for name in ("fill", "stroke", "stop-color", "color", "flood-color", "lighting-color", "bgcolor"):
            v = a.get(name, "")
            if v and EYE_LITERAL.search(v):
                self.hits.append(Hit(self.rel, line, "eye_literal", '%s="%s"' % (name, v)))
            if v and OLD_LITERAL.search(v):
                self.hits.append(Hit(self.rel, line, "old_literal", '%s="%s"' % (name, v)))
            if v and OLD_TOKEN.search(v):
                self.hits.append(Hit(self.rel, line, "old_token", '%s="%s"' % (name, v)))
        fs = a.get("font-size", "")
        m = re.fullmatch(r"\s*(\d*\.?\d+)(px)?\s*", fs)
        if m and float(m.group(1)) < 11:
            self.hits.append(Hit(self.rel, line, "sub11", 'font-size="%s"' % fs))
        if a.get("repeatcount", "").strip() == "indefinite":
            self.hits.append(Hit(self.rel, line, "infinite", '<%s repeatCount="indefinite">' % tag))
        if tag == "link" and "fonts.googleapis.com" in a.get("href", ""):
            href = a["href"].replace("&amp;", "&")
            if re.search(r"Share\+Tech\+Mono", href):
                self.hits.append(Hit(self.rel, line, "share_tech", href[:140]))
            if re.search(r"family=Orbitron", href) and "text=" not in href:
                self.hits.append(Hit(self.rel, line, "old_face_load", href[:140]))
            for wghts in re.findall(r"family=Rajdhani(?::wght@([\d;.]+))?", href):
                if wghts != "600":
                    self.hits.append(Hit(self.rel, line, "old_face_load", href[:140]))
        cls = a.get("class", "")
        self.stack.append({"tag": tag, "cls": cls, "line": line, "text": [],
                           "badge": re.search(r"(?<![\w-])badge-(bullish|bearish)(?![\w-])", cls)})
        if tag in self.VOID:
            self.handle_endtag(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for k in range(len(self.stack) - 1, -1, -1):
            if self.stack[k]["tag"] == tag:
                el = self.stack[k]
                del self.stack[k:]
                if el["badge"]:
                    text = "".join(el["text"])
                    exprs = " ".join(m.group(0) for m in DJ_TAG.finditer(text) if m.group(0).startswith("{{"))
                    plain = DJ_TAG.sub(" ", text).split()
                    side = (all(SIDE_WORD.match(w) for w in plain) if plain
                            else bool(exprs) and bool(SIDE_EXPR.search(exprs)))
                    if not side:
                        self.hits.append(Hit(self.rel, el["line"], "badge_side",
                                             'class="%s" around %r' % (el["cls"][:60], " ".join(text.split())[:60])))
                return

    def handle_data(self, data):
        for el in self.stack:
            if el["badge"]:
                el["text"].append(data)
        text = DJ_TAG.sub(" ", data)
        if not text.strip() or not is_glyph_icon(text):
            return
        if any(h["tag"] in ("button", "a", "summary", "nav") or ICON_HOST.search(h["cls"]) for h in self.stack):
            self.hits.append(Hit(self.rel, self._line(), "glyph_icon",
                                 "<%s class=%r>%s" % (self.stack[-1]["tag"], self.stack[-1]["cls"][:50], text.strip())))


def _raw_blocks(text, tag):
    """(first line, body) of each <style> or <script> body, JSON islands
    excluded."""
    out = []
    for m in re.finditer(r"<%s\b([^>]*)>(.*?)</%s>" % (tag, tag), text, re.S | re.I):
        if tag == "script" and re.search(r"type=[\"']?application/(ld\+)?json", m.group(1)):
            continue
        if tag == "script" and re.search(r"\bsrc=", m.group(1)):
            continue
        out.append((text.count("\n", 0, m.start(2)) + 1, m.group(2)))
    return out


def template_hits(text, rel):
    hits = []
    # Django comments blanked (lines kept): a note is not a look.
    clean = re.sub(r"{#.*?#}", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)
    clean = re.sub(r"{%\s*comment\s*%}.*?{%\s*endcomment\s*%}",
                   lambda m: re.sub(r"[^\n]", " ", m.group(0)), clean, flags=re.S)
    clean = re.sub(r"<!--.*?-->", lambda m: re.sub(r"[^\n]", " ", m.group(0)), clean, flags=re.S)
    for first, body in _raw_blocks(clean, "style"):
        hits += css_hits(body, rel, first)
    for first, body in _raw_blocks(clean, "script"):
        hits += js_hits(body, rel, first)
    # The markup, with the raw blocks blanked so the parser never reads them.
    markup = re.sub(r"(<(style|script)\b[^>]*>)(.*?)(</\2>)",
                    lambda m: m.group(1) + re.sub(r"[^\n]", " ", m.group(3)) + m.group(4),
                    clean, flags=re.S | re.I)
    parser = _Markup(rel)
    parser.feed(markup)
    parser.close()
    hits += parser.hits
    if PALETTE_FILES.match(rel):
        hits += palette_hits(clean, rel)
    return hits


# ── the Python that paints ──────────────────────────────────────────────

_TOKEN_HEX = None


def token_hexes():
    """Every hex value the tokens sheet defines, dark and light: what an
    email or the PDF may inline (email clients ignore CSS variables)."""
    global _TOKEN_HEX
    if _TOKEN_HEX is None:
        text = (ROOT / TOKENS_SHEET).read_text(encoding="utf-8")
        found = {h.lower() for h in re.findall(r"--[\w-]+\s*:\s*(#[0-9a-fA-F]{3,6})\b", text)}
        found |= {"#ffffff", "#fff", "#000000", "#000"}
        _TOKEN_HEX = found
    return _TOKEN_HEX


def palette_hits(text, rel, first_line=1):
    hits = []
    for k, line_text in enumerate(text.split("\n")):
        for m in HEX.finditer(line_text):
            h = m.group(0).lower()
            if len(h) == 4:
                h = "#" + "".join(ch * 2 for ch in h[1:])
            if h not in token_hexes() and m.group(0).lower() not in token_hexes():
                hits.append(Hit(rel, first_line + k, "off_token_hex", line_text.strip()[:140]))
    return hits


def python_hits(text, rel):
    """In the Python that emits markup or a PDF: the strings only (never a
    comment), read for the same colour and size markers, and, being a
    painter, for a hex colour that is not a token's value."""
    hits = []
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return hits
    for tok in toks:
        if tok.type != tokenize.STRING:
            continue
        body, line = tok.string, tok.start[0]
        if re.match(r'^[rbuf]*("""|\'\'\')', body, re.I) and not re.search(r"[<{;:]\s*(color|background|style)", body):
            continue        # a docstring or a long note, not markup
        for k, part in enumerate(body.split("\n")):
            ln = line + k
            if EYE_LITERAL.search(part):
                hits.append(Hit(rel, ln, "eye_literal", part.strip()[:140]))
            if OLD_LITERAL.search(part):
                hits.append(Hit(rel, ln, "old_literal", part.strip()[:140]))
            for m in re.finditer(r"font-size\s*:\s*(\d*\.?\d+)px", part):
                if float(m.group(1)) < 11:
                    hits.append(Hit(rel, ln, "sub11", part.strip()[:140]))
            if re.search(r"share\s*tech\s*mono", part, re.I):
                hits.append(Hit(rel, ln, "share_tech", part.strip()[:140]))
            for m in JS_STYLE_ATTR.finditer(part):
                for hit in style_attr_hits(m.group(2), rel, ln):
                    if hit.marker == "inline_visual":
                        hits.append(hit)
            hits += palette_hits(part, rel, ln)
    return hits


# ── the census ──────────────────────────────────────────────────────────

def source_files():
    seen = []
    for pattern in SOURCES:
        for path in sorted(ROOT.glob(pattern)):
            if path.is_file():
                seen.append(path)
    return seen


def file_hits(path, rel=None):
    """The hits of one file; `rel` names it when it is a copy outside the
    tree (the meta-test reads a temp copy as the file it copies)."""
    rel = rel or path.relative_to(ROOT).as_posix()
    if rel == TOKENS_SHEET:
        return []
    text = path.read_text(encoding="utf-8")
    if rel.endswith(".css"):
        return css_hits(text, rel)
    if rel.endswith(".js"):
        hits = js_hits(text, rel)
        if rel in MAGIC_SCRIPTS:
            hits = [h for h in hits if h.marker not in ("eye_literal", "glow", "gradient")]
        return hits
    if rel.endswith(".py"):
        return python_hits(text, rel)
    return template_hits(text, rel)


def census(paths=None):
    """[Hit] for every scanned file (or the given ones)."""
    hits = []
    for path in (paths if paths is not None else source_files()):
        hits += file_hits(path)
    return hits


def counts(hits):
    """{file: {marker: n}}"""
    out = {}
    for h in hits:
        out.setdefault(h.file, collections.Counter())[h.marker] += 1
    return {f: dict(sorted(c.items())) for f, c in sorted(out.items())}


# ══════════════════════════════════════════════════════════════════════════
# Who empties what: the file:line -> batch map (the critic's hole 5)
# ══════════════════════════════════════════════════════════════════════════
#
# The batch of batches.md that removes a file's old markers. A shared file
# is cut into stretches (first line, last line, batch[, marker]): a marker
# named on a stretch is that batch's on those lines (the shell's glyph
# icons are B2's wherever they sit, the rest of a stretch its own batch's).
# Lines are main's at 1b94a50. A batch that moves lines moves its stretch
# with them, in the same change. "exception" is a recorded exception of the
# final guard (the intro, kept exactly; the Django admin); "B24a" is light
# mode, its §10 meanings whatever he decides about its palette.

BATCHES = ("B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10", "B11", "B12", "B13", "B14",
           "B15", "B16", "B17", "B18", "B19", "B20", "B21", "B22", "B23", "B24", "B24a", "exception")

#: One owner per template or script: the page batch that redoes it.
FILE_OWNER = {
    # The frame (B1) and the shell's own pieces.
    "templates/_partials/activity_drawer.html": "B4", "templates/_partials/council_band.html": "B4",
    "templates/_partials/the_horde.html": "B4", "templates/_tour.html": "B4",
    "templates/_partials/dh_item.html": "B3", "templates/_partials/ticker_item.html": "B3",
    "templates/_partials/ticker_items.html": "B3", "templates/_partials/signal_rail_items.html": "B3",
    "templates/_partials/signal_rows_compact.html": "B3", "templates/_partials/notif_items.html": "B3",
    "templates/_partials/rail_sig_chips.html": "B3", "templates/_partials/rail_watch_chips.html": "B3",
    "templates/_partials/rail_host_attrs.html": "B3", "templates/_partials/passation_card.html": "B3",
    "templates/_partials/live_region.html": "B3", "templates/_partials/deep_link_note.html": "B3",
    "templates/_partials/sv_venue.html": "B3",
    # The shared pieces (B5) and the kit's own page.
    "templates/dashboard/design_kit.html": "B5",
    # B6: the ticket and the instrument page.
    "templates/_partials/deal_ticket.html": "B6", "templates/dashboard/instrument_detail.html": "B6",
    # B7: positions.
    "templates/dashboard/positions_list.html": "B7", "templates/dashboard/_positions_metrics.html": "B7",
    "templates/dashboard/_position_summary.html": "B7", "templates/_partials/capital_card.html": "B7",
    "templates/_partials/position_filter.html": "B7", "templates/_partials/close_selection_bar.html": "B7",
    "templates/_partials/position_group_row.html": "B7", "templates/_partials/position_view_note.html": "B7",
    "templates/dashboard/forensics_detail.html": "B7", "templates/dashboard/_council_card.html": "B7",
    "templates/dashboard/_live_shell.html": "B7",
    # B8: home, /command/ (OC1).
    "templates/dashboard/command.html": "B8", "templates/dashboard/_command_bots.html": "B8",
    "templates/dashboard/_command_history.html": "B8", "templates/dashboard/_command_live.html": "B8",
    "templates/dashboard/_command_portfolio.html": "B8",
    # B9: signals, portfolio, the small charts, the broker's own reading.
    "templates/dashboard/signals_list.html": "B9", "templates/dashboard/_signals_metrics.html": "B9",
    "templates/dashboard/portfolio_overview.html": "B9", "templates/dashboard/_portfolio_metrics.html": "B9",
    "templates/_chart_assets.html": "B9", "templates/_partials/chart_line.html": "B9",
    "templates/_partials/chart_bars.html": "B9", "templates/_partials/chart_donut.html": "B9",
    "templates/_partials/broker_account.html": "B9", "dashboard/views_bot_charts.py": "B9",
    # B10: the instrument chart.
    "templates/_partials/chart_widget.html": "B10",
    # B11: the cockpits.
    "templates/dashboard/ops.html": "B11", "templates/dashboard/orcs_list.html": "B11",
    "templates/dashboard/orcs_seats.html": "B11", "templates/dashboard/orc_detail.html": "B11",
    "templates/dashboard/ai_models.html": "B11",
    # B12: /oculus/.
    "templates/dashboard/oculus.html": "B12",
    # B13: money settings.
    "templates/dashboard/setup.html": "B13", "templates/dashboard/brokers.html": "B13",
    "templates/dashboard/withdrawals.html": "B13", "templates/dashboard/treasury.html": "B13",
    # B14: bots and pools.
    "templates/dashboard/asset_bots.html": "B14", "templates/dashboard/shares.html": "B14",
    "templates/dashboard/desk.html": "B14", "templates/dashboard/allocator.html": "B14",
    "templates/dashboard/risk_depth.html": "B14", "bot_program/templates/bot_program/home.html": "B14",
    "templates/dashboard/bot_console.html": "B14",
    # B15: login, PIN, lock, pop-out (and the Wall's sign-in, below).
    "templates/registration/login.html": "B15", "templates/registration/login_pin.html": "B15",
    "templates/registration/_key_eye.html": "B15", "templates/dashboard/locked.html": "B15",
    "templates/dashboard/_popout.html": "B15", "static/js/idle-lock.js": "B15",
    # B16: the markets.
    "templates/dashboard/instruments_list.html": "B16", "templates/dashboard/economic_calendar.html": "B16",
    "templates/dashboard/news_feed.html": "B16", "templates/dashboard/news_detail.html": "B16",
    "templates/dashboard/_news_metrics.html": "B16", "templates/bigmoney/board.html": "B16",
    "templates/dashboard/liquidations.html": "B16",
    # B17: what can act.
    "templates/dashboard/strategies_list.html": "B17", "templates/dashboard/strategy_detail.html": "B17",
    "templates/dashboard/_strategy_wizard.html": "B17", "templates/dashboard/_strategies_metrics.html": "B17",
    "templates/dashboard/setups.html": "B17", "templates/dashboard/opportunities.html": "B17",
    "templates/dashboard/rule_control.html": "B17", "templates/dashboard/promotions.html": "B17",
    "templates/dashboard/personas.html": "B17", "templates/dashboard/events.html": "B17",
    # B18: what is measured.
    "templates/dashboard/evidence.html": "B18", "templates/dashboard/performance.html": "B18",
    "templates/dashboard/bot_performance.html": "B18", "templates/dashboard/forensics_list.html": "B18",
    "templates/dashboard/backtest_list.html": "B18", "templates/dashboard/_backtest_metrics.html": "B18",
    "templates/dashboard/bot_backtest.html": "B18", "templates/dashboard/bot_backtest_detail.html": "B18",
    "templates/dashboard/calibration.html": "B18", "templates/dashboard/council.html": "B18",
    # B19: what is invented.
    "templates/dashboard/evolution.html": "B19", "templates/dashboard/discoveries.html": "B19",
    "templates/dashboard/generated.html": "B19", "templates/dashboard/hypotheses.html": "B19",
    "templates/dashboard/brain.html": "B19", "templates/dashboard/_brain_rule_lever.html": "B19",
    "templates/dashboard/knowledge.html": "B19", "templates/dashboard/knowledge_history.html": "B19",
    "templates/lore/index.html": "B19", "templates/lore/entry.html": "B19",
    "templates/dashboard/consolidation.html": "B19", "templates/dashboard/horizon.html": "B19",
    "templates/dashboard/intelligence.html": "B19", "templates/dashboard/briefing.html": "B19",
    "templates/dashboard/_monday_plan.html": "B19", "templates/dashboard/_next_steps.html": "B19",
    "templates/dashboard/earnings_reviews.html": "B19", "templates/dashboard/research.html": "B19",
    "templates/dashboard/ai_journal.html": "B19", "templates/dashboard/ai_insights.html": "B19",
    # B20: the machine.
    "templates/dashboard/admin_dashboard.html": "B20", "templates/dashboard/_admin_bots.html": "B20",
    "templates/dashboard/system_map.html": "B20", "templates/dashboard/admin_eye.html": "B20",
    "templates/dashboard/hq_books.html": "B20", "templates/dashboard/_hq_divisions.html": "B20",
    "templates/dashboard/admin_newsletters.html": "B20", "templates/dashboard/eye.html": "B20",
    "templates/dashboard/_eye_body.html": "B20", "templates/dashboard/eye_gate_events.html": "B20",
    "templates/dashboard/eye_fills.html": "B20", "templates/dashboard/eye_exposure.html": "B20",
    "templates/dashboard/system_health.html": "B20", "templates/dashboard/ai_tasks_list.html": "B20",
    "templates/dashboard/audit_log.html": "B20",
    # B21: you, off-nav, the book's tail.
    "templates/dashboard/profile.html": "B21", "templates/dashboard/_profile_credentials.html": "B21",
    "templates/dashboard/_profile_password_modal.html": "B21",
    "templates/dashboard/_profile_pin_modal.html": "B21", "templates/dashboard/notifications_inbox.html": "B21",
    "templates/dashboard/user_notifications.html": "B21", "templates/dashboard/newsletter_archive.html": "B21",
    "templates/dashboard/newsletter_detail.html": "B21", "templates/dashboard/getting_started.html": "B21",
    "templates/dashboard/passation.html": "B21", "templates/dashboard/short_proofs.html": "B21",
    "bot_program/templates/bot_program/link.html": "B21", "bot_program/templates/bot_program/configure.html": "B21",
    "bot_program/templates/bot_program/scenarios.html": "B21",
    "bot_program/templates/bot_program/scenario_new.html": "B21",
    "bot_program/templates/bot_program/scenario_detail.html": "B21",
    "templates/dashboard/tax_lots.html": "B21", "templates/dashboard/bot_charts.html": "B21",
    # B23: the public pages, the report and the emails (the Wall's sign-in is B15's, below).
    "templates/landing/the_wall.html": "B23", "templates/landing/the_book.html": "B23",
    "templates/landing/withheld.html": "B23", "templates/investor/panel.html": "B23",
    "templates/investor/_panel_body.html": "B23", "templates/email/newsletter.html": "B23",
    "templates/email/briefing.html": "B23", "templates/newsletter/unsubscribe.html": "B23",
    "dashboard/reports.py": "B23",
    # B24: dead, deleted rather than restyled.
    "templates/dashboard/dashboard.html": "B24", "templates/dashboard/market_quotes.html": "B24",
    "templates/dashboard/_signal_cards.html": "B24", "templates/dashboard/_signal_performance.html": "B24",
    "templates/_modal.html": "B24", "templates/dashboard/report.html": "B24",
    # Recorded exceptions of the final guard.
    "templates/dashboard/intro.html": "exception", "templates/admin/base_site.html": "exception",
    # The sheets and the scripts.
    "static/css/sv-rail.css": "B3", "static/css/sv-venue.css": "B3", "static/css/sv-overlay.css": "B3",
    "static/css/sv-horde.css": "B4", "static/css/sv-council-band.css": "B4", "static/css/sv-activity.css": "B4",
    "static/css/sv-tour.css": "B4", "static/css/sv-motion.css": "B5", "static/css/sv-kit.css": "B5",
    "static/css/sv-close-advice.css": "B7", "static/css/sv-day-scheme.css": "B8",
    "static/css/sv-responsive.css": "B22",
    "static/js/sv-overlay.js": "B3", "static/js/sv-flash.js": "B3", "static/js/sv-notif-card.js": "B3",
    "static/js/sv-news-dwell.js": "B3", "static/js/sv-rail-filters.js": "B3", "static/js/sv-position-card.js": "B3",
    "static/js/sv-venue.js": "B3", "static/js/sv-market-status.js": "B3",
    "static/js/sv-horde.js": "B4", "static/js/sv-council-band.js": "B4", "static/js/sv-activity.js": "B4",
    "static/js/sv-tour.js": "B4", "static/js/sv-gollum.js": "B4", "static/js/sv-motion.js": "B5",
    "static/js/sv-council.js": "B6", "static/js/sv-instrument-live.js": "B6", "static/js/sv-level-edit.js": "B7",
    "static/js/sv-close-advice.js": "B7", "static/js/sv-day-scheme.js": "B8", "static/js/sv-day-live.js": "B8",
    "static/js/sv-nav-activity.js": "B2", "static/js/sv-gate.js": "B15", "static/js/sv-run.js": "B5",
    "static/js/sv-embers.js": "B1", "static/js/sv-moments.js": "B1", "static/js/sv-ambience.js": "B1",
    "core/templatetags/sauron_tags.py": "B5", "core/templatetags/quote_tags.py": "B3",
}

#: The two big shared files, cut where their own sections begin. A stretch
#: starts on the first line, after the previous stretch's start, that holds
#: its anchor, and runs to the next one (the first from line 1, the last to
#: the end of the file). Anchored on the files' own section notes, so lines
#: added above move nothing; a batch that rewrites a section re-anchors its
#: stretch in the same change (a lost anchor fails a test below).
ANCHORED = {
    "templates/base.html": [
        (None, "B1"),                                                   # the head: the faces, the sheets
        ("<!-- Animated grid background -->", "B24"),                   # the hidden ambient layers (#103)
        ('<div id="navMiniTip"', "B2"),                                 # the brand, the nav, its 62 marks
        ("<!-- Mobile sidebar overlay -->", "B1"),                      # the topbar row (#7)
        ('class="theme-toggle-btn"', "B2"),                             # the theme toggle's ☀ ☾
        ('<span id="clock"', "B1"),
        ('<div class="exchange-indicator">', "B3"),                     # the sessions menu (#40)
        ('class="sv-armed-pill"', "B1"),                                # REAL ARMED (#41)
        ("<!-- UPGRADE-8: Live status pill -->", "B3"),                 # the live-status list, the bell (#39, #40)
        ("{# Lock now, rather than waiting out the idle window", "B2"),  # lock now (#113)
        ('<div class="user-menu" id="userMenu">', "B3"),                # the user menu (#40)
        ("<!-- Ticker Bar (fixed, always visible) -->", "B1"),          # the strips, restore tabs, the bottom strip (#1, #10, #11)
        ('<div class="ip-dropdown">', "B3"),                            # the bottom strip's dropdowns (#38)
        ("{# A Telegram button's page (2026-10-24): what the link opens. #}", "B3"),  # (#112)
        ("<!-- UPGRADE-6: Top-level rail toggle", "B1"),
        ("{# THE PHONE'S BOTTOM NAV", "B2"),
        ("<!-- Signals Rail (right sidebar)", "B1"),                    # the rail's frame (#6)
        ('id="railWatchPanel"', "B3"),                                  # the watchlist, its quote card (#35, #37)
        ("{# The activity drawer (2026-09-29)", "B1"),
        ("/* Phase 62 — render sparkline paths", "B3"),                 # sparks, the rail card, pass and star (#36)
        ("/* ── TAKE TRADE — a signal proposes", "B6"),                  # TAKE TRADE and its outcome (#25, #109)
        ("/* ── CLOSE POSITION — the way out", "B7"),                    # the close (#30)
        ("/* ── A TELEGRAM BUTTON'S PAGE (2026-10-24)", "B3"),           # (#112)
        ("<!-- UPGRADE-9: Sidebar edge toggle", "B1"),                  # the edge toggle, the embers, the clock
        ("// Instrument preview on hover", "B3"),                       # the instrument preview (#39)
        ("function toggleSidebar()", "B2"),                             # the sidebar's collapse
        ("// Ticker mouse wheel scroll", "B1"),                         # the strips' wheel (the marquee's)
        ("/* UPGRADE-3: WebSocket live ticks.", "B3"),                  # live ticks, the flash's fallback, the popups (#13, #39)
        ("<!-- ── Keyboard Shortcuts Modal", "B4"),                     # the "?" sheet, the toast (#88)
        ("<!-- ── Mobile Sidebar Toggle", "B22"),
        ("<!-- ── Pop-Out Panel System", "B15"),                        # the pop-out (#96)
        ("<!-- ── PWA: Service Worker Registration", "B1"),             # Gollum's button (#2)
        ('<div class="gollum-dialog" id="gollumDialog"', "B4"),         # Gollum's dialog (#74)
        ('<button type="button" class="se-eye-fab" id="seEyeFab"', "B1"),  # Ask Sauron's Eye (#3)
        ('<div class="se-chat-panel" id="seChatPanel"', "B4"),          # Ask Sauron's panel (#73)
        ("/* ── Resume scroll position across navigation", "B1"),
        ("{# Idle PIN lock gate.", "B15"),                              # the idle lock (#69)
        ("/* Live event banners.", "B3"),                               # the trading-event banners (#75)
    ],
    "static/css/sauron.css": [
        (None, "B24"),                                   # the old token names, re-pointed (dropped once unread)
        ("/* The browser's own parts follow the theme", "B5"),   # form controls, body, links
        ("/* ── Globe-Eye: static eye, rotating globe", "B24"),  # the ambient keyframes (#103)
        ("/* The embers (the magic kept, 2026-11-12)", "B1"),
        ("/* ── Sidebar ──", "B2"),                       # the sidebar, the brand, the logout
        ("/* ── Main ──", "B1"),                          # the main frame
        ("/* ── Cards (base — overridden", "B5"),          # the cards' base (#14)
        ("Smart 2-row reflow when BOTH rails are open", "B22"),  # reflow, phone 29, the hamburger
        ("/* stat-box — handled by unified card system", "B5"),  # stat-box, signal-item (#14, #45)
        ("/* ── Account cards ──", "B13"),                # the account cards
        ("/* The line under an empty state that says WHY", "B5"),  # notes, the entry motion (#15, #83)
        ("::-webkit-scrollbar{width:6px}", "B1"),        # the page's scrollbar (#113)
        (".detail-header { display: flex;", "B5"),       # details, section dividers (#45)
        ("/* ── Light Mode ──", "B24a"),                  # light mode (#100, #116)
        ("/* ── Theme Toggle ──", "B1"),
        ("/* ── Keyboard Shortcuts Modal ──", "B4"),      # (#88)
        ("/* ── Sidebar Collapse ──", "B2"),              # the collapsed sidebar, its tooltip (#8)
        ("/* ── Exchange Dropdown (fixed) ──", "B3"),     # the sessions menu (#40)
        ("/* ── Buttons ──", "B24"),                      # the old buttons, folded into the kit (#16)
        ("/* ── Instrument Preview Popup ──", "B3"),      # (#39)
        ("/* ── Admin User Popup ──", "B20"),
        ("/* ── Mobile Responsive ──", "B22"),
        ("/* ── Form Styles (global) ──", "B5"),          # form labels (#45)
        ("/* ── Headband collapse system: dynamic offsets ── */", "B1"),  # strips, bottom strip, cells (#1, #11)
        ("/* ── Notification Bell ──", "B3"),             # the bell (#40, #113)
        ("/* ── Sidebar expand arrow (when mini) ──", "B2"),
        ("/* ── Signals Sidebar (right) ──", "B1"),        # the rail's frame (#6)
        ("/* Rich row layout */", "B3"),                  # the rail's rows
        ("/* ── Hover popup for each signal ──", "B3"),   # the rail card (#36)
        ("/* Adjust main content when signals rail is visible */", "B1"),  # toggles, hide/restore tabs (#5, #10)
        ("UPGRADE-2: Design system — buttons, inputs, metrics", "B24"),    # the second .btn (#16)
        (".input-label { font-family: var(--font-mono); font-size: 10px;", "B5"),  # labels (#45)
        ("UPGRADE-2: Signals rail split (Signals + Watchlist)", "B3"),     # the watchlist (#37)
        ("UPGRADE-9: Data headband (escape-clip popups + RTL scroll)", "B1"),  # the price band (#1)
        ("/* Popup — fixed position, anchored by JS to escape the scroll container */", "B3"),  # cards (#35, #39)
        ("/* ── THE VENUE CONVENTION, NAMED ONCE", "B5"),  # the world chips' convention (#21)
        ("/* THE ARMED PILL: on every page", "B1"),       # (#41)
        ("/* Gold, and therefore --accent-gold-ink", "B3"),  # the position card's insides (#39)
        ("/* Fresh headline in the marquee", "B1"),
        ("/* Push page content down for headbands", "B3"),   # the news popup, the live-status pill
        ("UNIFIED PREMIUM CARD SYSTEM", "B5"),             # the card recipe (#14)
        ("/* ── Top-right user menu (clickable username dropdown) ── */", "B3"),  # (#40)
        ("/* ── Enhanced Form Styles ──", "B5"),           # forms, checkbox, radio, range, file (#77)
        ("/* ── Switch (toggle) — for any element with class .sv-switch", "B24"),  # (#104)
        ("/* Django form.as_p styling */", "B5"),          # form.as_p, search, the KPI strip (#44)
        ("/* ── Layout-aware anchoring ──", "B1"),         # Ask Sauron's floating Eye (#3)
        ("/* ── In-panel SEND button — circular palantír-mini", "B4"),  # the send orb (hole 5)
        ("/* Background circuits overlay", "B24"),         # the circuits (#103)
        ("/* (FAB no longer uses the old SVG pupil-look", "B4"),  # Ask Sauron's panel (#73)
        ("REFINEMENT LAYER", "B5"),                       # numbers, the strip, cards (#14, #44)
        ("/* ── 3c. Strategy ladder cards", "B17"),        # (#90)
        ("/* ── 4. Tables ──", "B5"),                     # tables, empty states (#83, #114)
        ("TOKEN ALIASES", "B24"),
        ("/* ── The lead metric ──", "B5"),               # (#44)
        ("TICKER POPUPS", "B3"),                         # (#39)
        ("EVENT BANNERS", "B3"),                         # (#75)
        ("LIGHT MODE — remove the dark inset shadows", "B24a"),
        ("OVERFLOW HONESTY (2026-08-19)", "B22"),
        ("IDLE PIN LOCK (il-)", "B15"),                  # (#69)
        ("CARD CONTAINMENT (2026-08-19)", "B5"),         # identifiers (#82)
        ("STACKED TABLES (.sv-stack)", "B22"),
        ("/* ── Positions: the closed-trade cards", "B7"),
        ("SIGNAL ALREADY ACTED ON (sr-acted / sr-taken)", "B3"),
        ("TAKE TRADE — the pre-trade control panel (sz-)", "B6"),  # (#25, #109)
        ("CHART SURFACES", "B9"),                        # (#49)
        ("ASK SAURON — THE ANSWER", "B4"),               # (#73)
        ("INTERACTIVE BROKERS CONNECTION CARD", "B13"),
        ("/* ── Signal symbol cell ──", "B9"),            # (#47)
        ("/* ── Lock-now button ──", "B2"),               # (#113)
        ("/* ── Capital truth (pools/used/free card", "B7"),
        ("/* The oversubscribed note inside a dropdown body", "B3"),
        ("/* Sidebar unseen-activity dot", "B2"),        # (#113)
        ("/* ── Lock engage/release choreography", "B15"),
        ("/* ── Briefing depth — the strategist's report", "B19"),
        ("/* ── Gollum — the guide at the bottom-left", "B1"),   # his button and bubble (#2)
        ("/* The dialog — above the stone, in the card idiom. */", "B4"),  # his dialog (#74)
        ("/* ── The second gate — shared by /locked/ and the idle overlay", "B15"),
        ("/* ── News cell: a day of sentiment above the headlines", "B16"),
        ("/* -- Editing a stop where it is read", "B7"),   # the level editor (#32)
        ("/* ── DEAL TICKET ──", "B6"),                   # (#26)
        ("/* ── BROKER TRUTH ──", "B9"),                  # (#110)
        ("/* ── A Telegram button's page (2026-10-24)", "B3"),  # (#112)
    ],
}

_ANCHOR_CACHE = {}


def anchored_stretches(rel):
    """[(first, last, batch)] of an anchored file, end to end, and the
    anchors not found (in order)."""
    st = (ROOT / rel).stat()
    key = (rel, st.st_mtime_ns, st.st_size)
    if key not in _ANCHOR_CACHE:
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        starts, lost, at = [], [], 0
        for anchor, batch in ANCHORED[rel]:
            if anchor is None:
                starts.append((1, batch))
                continue
            for i in range(at, len(lines)):
                if anchor in lines[i]:
                    starts.append((i + 1, batch))
                    at = i + 1
                    break
            else:
                lost.append(anchor)
        out = [(first, (starts[k + 1][0] - 1) if k + 1 < len(starts) else max(len(lines), first), batch)
               for k, (first, batch) in enumerate(starts)]
        _ANCHOR_CACHE[key] = (out, lost)
    return _ANCHOR_CACHE[key]


#: The other shared files, cut by line (first, last, batch[, marker]): a
#: marker named on a stretch is that batch's on those lines.
STRETCHES = {
    "templates/base.html": [(1, 10 ** 6, "B2", "glyph_icon")],   # every glyph icon of the shell: the sprite
    "static/css/sv-overlay.css": [
        (448, 476, "B3"),          # the bottom strip's dropdowns (#38)
        (854, 977, "B1"),          # Ask Sauron's floating Eye (#3)
        (1022, 1048, "B4"),        # Ask Sauron's panel (#73)
    ],
    "static/css/sv-horde.css": [(150, 230, "B1")],          # the Horde's strip (#4)
    "static/css/sv-council-band.css": [(117, 144, "B1")],   # COUNCIL's edge tab (#5)
    "static/css/sv-activity.css": [(46, 72, "B1")],         # ACTIVITY's edge tab (#5)
    "static/js/sv-venue.js": [(725, 735, "B9")],            # the eToro "now" line's colour (#49)
    "static/js/sv-motion.js": [(198, 282, "B8")],           # count-ups on /command/ (#42)
    "templates/landing/the_wall.html": [
        (630, 790, "B15"), (4586, 4670, "B15"), (5040, 5260, "B15"),   # his sign-in (#105)
    ],
    "core/templatetags/sauron_tags.py": [(300, 470, "B23")],   # the emails' palette (#99)
    "templates/_partials/council_band.html": [(1, 9999, "B2", "glyph_icon")],
    "templates/_partials/the_horde.html": [(1, 9999, "B2", "glyph_icon")],
}


def owner(path, line, marker=None):
    """The batch that empties `path` at `line` (of `marker`), or None."""
    stretches = list(STRETCHES.get(path, ()))
    for first, last, batch, *only in stretches:
        if only and only[0] == marker and first <= line <= last:
            return batch
    if path in ANCHORED:
        stretches += anchored_stretches(path)[0]
    found = None
    for first, last, batch, *only in stretches:
        if not only and first <= line <= last:
            found = batch
    return found or FILE_OWNER.get(path)


def batch_map(hits=None):
    """{batch: {file: [(line, marker)]}} and the orphans (no owner)."""
    hits = census() if hits is None else hits
    out, orphans = {}, []
    for h in hits:
        b = owner(h.file, h.line, h.marker)
        if b is None:
            orphans.append(h)
            continue
        out.setdefault(b, {}).setdefault(h.file, []).append((h.line, h.marker))
    return out, orphans


def print_batch_map(stream=None, hits=None):
    """The file:line -> batch map, batch by batch, with the totals."""
    import sys
    stream = stream or sys.stdout
    by_batch, orphans = batch_map(hits)
    order = {b: i for i, b in enumerate(BATCHES)}
    for b in sorted(by_batch, key=lambda x: order.get(x, 99)):
        files = by_batch[b]
        total = sum(len(v) for v in files.values())
        stream.write("%s  %d markers in %d files\n" % (b, total, len(files)))
        for f, items in sorted(files.items()):
            marks = collections.Counter(m for _l, m in items)
            lines = sorted({l for l, _m in items})
            spans, start, prev = [], None, None
            for l in lines:
                if start is None:
                    start = prev = l
                elif l <= prev + 3:
                    prev = l
                else:
                    spans.append((start, prev))
                    start = prev = l
            if start is not None:
                spans.append((start, prev))
            stream.write("    %s:%s  %s\n" % (f, ",".join("%d" % a if a == z else "%d-%d" % (a, z) for a, z in spans[:12])
                                             + (",…" if len(spans) > 12 else ""),
                                             " ".join("%s=%d" % kv for kv in sorted(marks.items()))))
    for h in orphans:
        stream.write("ORPHAN %s:%d %s\n" % (h.file, h.line, h.marker))
    return by_batch, orphans


# ══════════════════════════════════════════════════════════════════════════
# The budget: today's counts, a ratchet that only goes down
# ══════════════════════════════════════════════════════════════════════════

def load_budget():
    return json.loads(BUDGET.read_text(encoding="utf-8"))


def write_budget(budget):
    BUDGET.write_text(json.dumps(budget, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def compare_source(now, budget, hits):
    """(over, under): one message per file and marker above its budget
    (with every line of that marker in that file), and one per budget the
    count has gone under (the ratchet must follow it down)."""
    over, under = [], []
    by_key = collections.defaultdict(list)
    for h in hits:
        by_key[(h.file, h.marker)].append(h)
    for f in sorted(set(now) | set(budget)):
        for marker in sorted(set(now.get(f, {})) | set(budget.get(f, {}))):
            got, allowed = now.get(f, {}).get(marker, 0), budget.get(f, {}).get(marker, 0)
            if got > allowed:
                head = ("%s: %s %d, budget %d (%s)" %
                        (f, marker, got, allowed,
                         "a file absent from the budget must be at zero" if f not in budget
                         else "old design added"))
                lines = ["    %s:%d %s [%s]  %s" % (h.file, h.line, h.marker, owner(h.file, h.line, h.marker) or "no batch",
                                                   h.text[:150])
                         for h in sorted(by_key[(f, marker)], key=lambda x: x.line)[:40]]
                over.append("\n".join([head] + lines))
            elif got < allowed:
                under.append("%s: %s %d, budget %d: lower the budget to %d (the ratchet follows the count down;"
                             " tests.test_zero_old_design.lower_budgets() writes it)" % (f, marker, got, allowed, got))
    return over, under


def lower_budgets(write=True):
    """Every source budget lowered to today's count where the count went
    down: never raised. Returns the changes. A batch that removes old
    markers runs it and commits the file with its change."""
    budget = load_budget()
    now = counts(census())
    changes = []
    src = budget.setdefault("source", {})
    for f in sorted(src):
        for marker in sorted(src[f]):
            got = now.get(f, {}).get(marker, 0)
            if got < src[f][marker]:
                changes.append("%s %s %d -> %d" % (f, marker, src[f][marker], got))
                if got:
                    src[f][marker] = got
                else:
                    del src[f][marker]
        if not src[f]:
            del src[f]
    if write and changes:
        write_budget(budget)
    return changes


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
        """STRICT: the files a batch has emptied, held at zero for good (none
        at B0)."""
        for f in self.budget["strict"]["source"]:
            with self.subTest(file=f):
                self.assertNotIn(f, self.budget["source"])
                self.assertEqual(self.now.get(f, {}), {})

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
        # Every scanned file has an owner, so a marker added anywhere names
        # the batch it falls to.
        for p in source_files():
            rel = p.relative_to(ROOT).as_posix()
            if rel in (TOKENS_SHEET,) or rel.endswith("__init__.py"):
                continue
            with self.subTest(file=rel):
                self.assertTrue(rel in FILE_OWNER or rel in STRETCHES or rel in ANCHORED,
                                "%s has no batch in OWNERS" % rel)

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
        exempt by their scope, and the tokens sheet is never read."""
        self.assertEqual([h for h in self.hits if h.file in (KIT_SHEET, TOKENS_SHEET)], [])
        self.assertEqual(file_hits(ROOT / TOKENS_SHEET), [])


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
        self.assertEqual(self.css(".x { color: var(--sv-eye, #00e868); }"), [])
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


# ══════════════════════════════════════════════════════════════════════════
# THE MEASURED HALF: every routed page and the shell's states, in Chromium
# ══════════════════════════════════════════════════════════════════════════
#
# Chromium over its DevTools pipe (tests/test_close_advice._Chrome), on a
# synthetic book, at one frozen instant (the one-price fixture's T, a
# Thursday evening, every market open): the server's clock, the market
# hours' and the page's own Date all read T, so a page measured on a
# Saturday is the page measured on a Thursday.
#
# THE CRITIC'S HOLE 1 (pages opened as files load nothing after the HTML):
# every request the page makes is answered from the test client through the
# DevTools Fetch domain, before it can leave the machine (no host resolves
# either): the document, its sheets and scripts from static/, its fetch()
# and XHR calls (the rail, the bell, the live regions, /eye/'s body, the
# chart's data, the instrument preview) from the views themselves. A POST
# is never sent to a view that could move anything: the previews the
# states need are synthetic or read-only, every other POST is answered 204.
# The regions htmx fills on load (the KPI strips, the bot panel, /command/'s
# tabs, /eye/'s body) are filled the way htmx fills them, from their own
# routes, before the page is served: the CDN libraries (htmx, Chart.js,
# lightweight-charts) are not fetched, so the chart's canvas stays empty
# (B10 brings its pixel census with a copy of the library).
#
# THE CRITIC'S HOLE 2 (rest state only): a forced pass puts :hover,
# :focus-visible and :active on every button, link, row and checkbox of the
# shell and of the §10 money controls, and measures again.
# THE CRITIC'S HOLE 3 (1440 only): the shell and the §10 controls at 390 x 844
# too: money targets under 44 px, sideways scroll, red fills outside REAL.
# THE CRITIC'S HOLE 4: accent-color, caret-color, ::placeholder, ::marker,
# and the states the lists missed (below, STATES).
#
# THE SAME COUNT IN EVERY RUN. Each page is read at the same instant of its
# life: the page's timers of a second or more run on a held clock the run
# moves by fixed steps (2.6 s after the load, 1.6 s after an act; INIT), so
# the live pill's first poll, the nav dots', Gollum's whisper, the Horde's
# first tab, the Wall's labels have all happened, and nothing later has;
# what the motion layer hid below the fold is shown, finite animations end
# where they end, endless ones are stopped at their start (the census), and
# each scene's writes to the book and the cache are undone after it
# (_scene_apart), so a scene reads the same page whichever came before it.
# Two runs on a loaded machine and an idle one counted alike, scene by scene.
#
# Per page and per state, each marker's count is held to its budget in
# tests/old_design_budget.json ("measured"): a count above it fails, naming
# the page, the state, the selector, the property and the value. A measured
# count may differ a little from one machine to another (fonts, wrapping),
# so a count below its budget never fails here; lower_measured_budgets()
# takes the budgets down after a batch.

CENSUS_JS = ROOT / "tests" / "old_design_census.js"
ORIGIN_HOST = "sv.census"
ORIGIN = "http://" + ORIGIN_HOST
#: The measured markers (old_design_census.js).
MEASURED = ("font_share_tech", "font_orbitron", "font_rajdhani", "font_other", "tiny", "figs", "prose_mono",
            "eye_text", "color_off", "contrast", "eye_fill", "eye_wash", "bg_off", "see_through", "red_fill",
            "glass", "gradient", "eye_border", "border_off", "glow", "shadow", "text_glow", "accent_color",
            "radius", "anim_loop", "inline_visual", "glyph_face", "first_line_low",
            "chrome_over_content", "sideways", "target_small")
#: The §10 money controls: the forced pass hovers them, the phone pass
#: measures them.
MONEY = (".tk-side, .tk-long, .tk-short, [data-sv-close-trade], #svCloseAll, .sr-pop-btn, .sr-gone-btn-ticket, "
         ".btn-buy, .btn-sell, .btn-stop, .sz-confirm, .sz-dialog .sv-dialog-btn, input[type=\"password\"], "
         "form[action*=\"toggle\"] button, form[action*=\"component\"] button, .sv-armed-pill, .ip-pos-close")
#: The shell's interactive parts (the forced pass).
SHELL_INTERACTIVE = (".sidebar a, .sidebar button, .topbar a, .topbar button, .info-panel-wrap a, "
                     ".info-panel-wrap button, .signals-rail a, .signals-rail button, .data-headband a, "
                     ".ticker-bar a, input[type=\"checkbox\"], tr")
#: The faces a glyph may be drawn in (the four; Orbitron and Rajdhani are
#: not installed anywhere these tests run, and fall to the next face).
FACES = ("Inter", "JetBrains Mono", "Orbitron", "Rajdhani")


def _frozen_instant():
    from tests.one_quote_fixture import T
    return T


class _Frozen:
    """datetime and date stand-ins whose now() and today() read T, for the
    modules that ask the clock without django.utils.timezone (the market
    hours, the market calendar, the charts' and bars' ages)."""

    @staticmethod
    def make():
        import datetime as _dt
        T = _frozen_instant()

        class FrozenDatetime(_dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return T.astimezone(tz) if tz is not None else T.replace(tzinfo=None)

            @classmethod
            def utcnow(cls):
                return T.replace(tzinfo=None)

        class FrozenDate(_dt.date):
            @classmethod
            def today(cls):
                return T.date()

        return FrozenDatetime, FrozenDate


def freeze_patches():
    """The patches that hold the server at T (started by the caller)."""
    T = _frozen_instant()
    dt, d = _Frozen.make()
    out = [mock.patch("django.utils.timezone.now", return_value=T),
           mock.patch("market_data.one_quote.now", return_value=T)]
    for mod, names in (("core.exchange_status", ("datetime", "date")), ("core.market_calendar", ("datetime",)),
                       ("dashboard.chart_source", ("datetime",)), ("market_data.bot_bars", ("datetime",))):
        try:
            m = __import__(mod, fromlist=["x"])
        except ImportError:
            continue
        for name in names:
            if hasattr(m, name):
                out.append(mock.patch.object(m, name, dt if name == "datetime" else d))
    return out


def token_rgbs():
    """{name: [r, g, b]} of every colour token of sv-tokens.css's :root (the
    dark palette the census holds colours to)."""
    text = (ROOT / TOKENS_SHEET).read_text(encoding="utf-8")
    root = text[text.index(":root"):]
    root = root[:root.index("}")]
    out = {}
    for name, hexv in re.findall(r"--sv-([\w-]+)\s*:\s*#([0-9a-fA-F]{6})\b", root):
        out[name] = [int(hexv[i:i + 2], 16) for i in (0, 2, 4)]
    return out


def token_radii():
    text = (ROOT / TOKENS_SHEET).read_text(encoding="utf-8")
    return sorted({0.0} | {float(v) for v in re.findall(r"--sv-radius-[\w-]+\s*:\s*([\d.]+)px", text) if float(v) < 99})


class _Driver(_Chrome):
    """_Chrome with every request answered here (the DevTools Fetch domain)
    and no host that resolves: nothing the page asks for leaves the
    machine."""

    ARGS = _Chrome.ARGS + ("--host-resolver-rules=MAP * ~NOTFOUND", "--disable-background-networking",
                           "--disable-component-update", "--disable-default-apps", "--disable-sync",
                           "--no-pings", "--lang=en-US", "--force-color-profile=srgb")

    def __init__(self, binary, answer):
        self.answer = answer
        self.ignored = set()
        self.served, self.last_served = 0, time.monotonic()
        super().__init__(binary)

    def _write(self, data):
        view = memoryview(data)
        while view:
            ready_r, ready_w, _x = select.select([self.out_r], [self.cmd_w], [], 60)
            if ready_r:
                chunk = os.read(self.out_r, 1 << 16)
                if not chunk:
                    raise RuntimeError("Chromium closed its pipe")
                self.buf += chunk
            if ready_w:
                n = os.write(self.cmd_w, view[:1 << 16])
                view = view[n:]

    def _send(self, method, params, session, keep):
        self.n += 1
        msg = {"id": self.n, "method": method, "params": params or {}}
        if session:
            msg["sessionId"] = session
        if not keep:
            self.ignored.add(self.n)
        self._write(json.dumps(msg).encode("utf-8") + b"\0")
        return self.n

    def _handled(self, got):
        if got.get("method") == "Fetch.requestPaused":
            self._fulfil(got["params"], got.get("sessionId"))
            return True
        if got.get("id") in self.ignored:
            self.ignored.discard(got["id"])
            return True
        return False

    def call(self, method, params=None, session=None, timeout=90):
        mine = self._send(method, params, session, keep=True)
        while True:
            got = self._recv(timeout)
            if self._handled(got):
                continue
            if got.get("id") == mine:
                if "error" in got:
                    raise RuntimeError("%s: %r" % (method, got["error"]))
                return got.get("result", {})
            self.events.append(got)

    def call_many(self, calls, session, timeout=90):
        """Many commands sent at once, their answers collected in order: a
        forced pass on a thousand nodes costs one round trip, not a
        thousand."""
        ids = [self._send(m, p, session, keep=True) for m, p in calls]
        want, got_by_id = set(ids), {}
        while want:
            got = self._recv(timeout)
            if self._handled(got):
                continue
            if got.get("id") in want:
                want.discard(got["id"])
                got_by_id[got["id"]] = got.get("result", {}) if "error" not in got else {"__error__": got["error"]}
                continue
            self.events.append(got)
        return [got_by_id[i] for i in ids]

    def wait(self, event, session, timeout=45):
        deadline = time.monotonic() + timeout
        while True:
            for i, got in enumerate(self.events):
                if got.get("method") == event and got.get("sessionId") == session:
                    del self.events[i]
                    return got.get("params", {})
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError("no %s in %ss" % (event, timeout))
            got = self._recv(left)
            if not self._handled(got):
                self.events.append(got)

    def _fulfil(self, p, session):
        self.served += 1
        self.last_served = time.monotonic()
        try:
            got = self.answer(p["request"], p.get("resourceType", ""))
        except Exception as exc:     # a view that raised: a 500, as the server would say
            got = (500, {"Content-Type": "text/plain"}, ("census: %r" % exc).encode("utf-8"))
        if got is None:
            self._send("Fetch.failRequest", {"requestId": p["requestId"], "errorReason": "BlockedByClient"},
                       session, keep=False)
            return
        status, headers, body = got
        self._send("Fetch.fulfillRequest", {
            "requestId": p["requestId"], "responseCode": int(status),
            "responseHeaders": [{"name": k, "value": str(v)} for k, v in headers.items()],
            "body": base64.b64encode(body).decode("ascii")}, session, keep=False)

    def tab(self, width, height, mobile=False, init=""):
        tid = self.call("Target.createTarget", {"url": "about:blank"})["targetId"]
        sid = self.call("Target.attachToTarget", {"targetId": tid, "flatten": True})["sessionId"]
        for method in ("Page.enable", "Runtime.enable", "DOM.enable", "CSS.enable"):
            self.call(method, session=sid)
        self.call("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]}, session=sid)
        self.call("Emulation.setDeviceMetricsOverride", {"width": width, "height": height, "deviceScaleFactor": 1,
                                                         "mobile": mobile}, session=sid)
        if mobile:
            self.call("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5}, session=sid)
        if init:
            self.call("Page.addScriptToEvaluateOnNewDocument", {"source": init}, session=sid)
        return tid, sid

    def quiet(self, sid, still=0.4, cap=6.0):
        """Wait until the page has asked for nothing for `still` seconds
        (or `cap` has passed): what a script fetches after the load, the
        rail's cards, a drawer's rows, a panel's thread, is in the page
        before it is read, on a fast machine as on a slow one."""
        start = time.monotonic()
        while time.monotonic() - start < cap:
            before = self.served
            self.js(sid, "new Promise(function (r) { setTimeout(r, 120); })")
            if self.served == before and time.monotonic() - self.last_served >= still:
                return round(time.monotonic() - start, 2)
        return None

    def close_tab(self, tid):
        try:
            self.call("Target.closeTarget", {"targetId": tid})
        except RuntimeError:
            pass

    def go(self, sid, url, timeout=45):
        self.call("Page.navigate", {"url": url}, session=sid)
        self.wait("Page.loadEventFired", sid, timeout)

    def js(self, sid, expression, timeout=90):
        got = self.call("Runtime.evaluate", {"expression": expression, "awaitPromise": True,
                                             "returnByValue": True}, session=sid, timeout=timeout)
        if got.get("exceptionDetails"):
            d = got["exceptionDetails"]
            raise RuntimeError((d.get("exception") or {}).get("description") or d.get("text") or repr(d))
        return got["result"].get("value")

    def nodes(self, sid, selector):
        doc = self.call("DOM.getDocument", {"depth": 0}, session=sid)["root"]["nodeId"]
        return self.call("DOM.querySelectorAll", {"nodeId": doc, "selector": selector}, session=sid)["nodeIds"]

    def force(self, sid, selector, states):
        ids = self.nodes(sid, selector)
        self.call_many([("CSS.forcePseudoState", {"nodeId": nid, "forcedPseudoClasses": list(states)})
                        for nid in ids], sid)
        return len(ids)

    def faces(self, sid, index):
        ids = self.nodes(sid, '[data-svc="%d"]' % index)
        if not ids:
            return []
        got = self.call("CSS.getPlatformFontsForNode", {"nodeId": ids[0]}, session=sid)
        return [(f["familyName"], f.get("isCustomFont", False), f["glyphCount"]) for f in got["fonts"]]


# ── the book ────────────────────────────────────────────────────────────

def census_book():
    """The synthetic book the pages are measured on (round, invented
    instruments, sizes and ages; nobody's data): real-money eToro longs and
    a paper lane, signals on each side, switches on and off, a legacy row,
    notifications, a news item, a strategy, a letter, a backtest, a
    scenario, an answer from Ask Sauron. Returns the staff user."""
    from tests.one_quote_fixture import T, daily_bar, quote, seed_measured
    from tests.test_close_advice import _legacy, _pin, _quote, _trade
    from tests.test_ops_cockpit import _component
    from tests.test_signal_acted_and_sizing import _signal
    user = get_user_model().objects.create_user("census", password="x", is_staff=True, is_superuser=True)
    _pin(user)
    held = seed_measured(user)
    quote("GBPUSD", "1.29410", "yfinance", 240, chg="-0.21")
    for days, close in ((3, "1.08120"), (2, "1.08300"), (1, "1.08480")):
        daily_bar("EURUSD", T - timedelta(days=days), close)
    _quote("BTCUSD", 64200)
    _quote("ETHUSD", 2600)
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    LiveQuote.objects.filter(instrument__symbol__in=("BTCUSD", "ETHUSD")).update(updated_at=T - timedelta(seconds=20))
    Instrument.objects.filter(symbol__in=("EURUSD", "GBPUSD", "XAUUSD", "AAPL", "BTCUSD")).update(is_watchlist=True)
    paper = _trade(user, symbol="BTCUSD", qty="0.05", entry=63800, stop=62500, target=66500)
    _trade(user, symbol="ETHUSD", side="SELL", qty="1", entry=2650, stop=2720, target=2500)
    _trade(user, symbol="BTCUSD", status="CLOSED", entry=61000, stop=60000, target=63000)
    btc = Instrument.objects.get(symbol="BTCUSD")
    eth = Instrument.objects.get(symbol="ETHUSD")
    _signal(btc, direction="bullish", entry=64200, stop=62400, target=67800, rule="census_up")
    _signal(eth, direction="bearish", entry=2600, stop=2690, target=2420, rule="census_down")
    _component("census_on_switch", is_enabled=True)
    _component("census_off_switch", is_enabled=False)
    _component("orcs", is_enabled=True)          # the Orcs' pages exist while their switch is ON
    _legacy(user)
    from alerts.models import Notification
    for title, kind in (("BTCUSD opened 0.05 at 63,800", "trade"), ("New signal: ETHUSD bearish", "signal"),
                        ("Daily summary ready", "system")):
        Notification.objects.create(user=user, notification_type=kind, title=title, body="synthetic", url="/positions/")
    from scraping.models import NewsArticle
    NewsArticle.objects.create(title="Synthetic: central bank holds rates", source="Census wire",
                               url="https://example.com/census-rates", published_at=T - timedelta(hours=2),
                               ai_urgency="high")
    from strategies.models import Strategy
    Strategy.objects.create(name="Census momentum", description="A synthetic strategy.", time_horizon="swing",
                            status="active", pnl=Decimal("120.50"), pnl_pct=1.2, max_drawdown=-2.5)
    from alerts.models import Newsletter
    Newsletter.objects.create(title="Census weekly letter", frequency="weekly", status="sent",
                              content_markdown="## The week\n\nA synthetic letter.")
    from lore.models import LoreEntry
    LoreEntry.objects.create(slug="census-lesson", kind="lesson", title="Census lesson",
                             summary="A synthetic lesson.", mechanism="m", works_when="w", evidence_grade="none",
                             origin="sauron", status="reviewed", regimes_works_flat="|risk_off|", tags_flat="|trend|")
    from bot_program.models import BotBacktestRun, BotScenario
    BotBacktestRun.objects.create(user=user, config_name_snapshot="Crypto", asset_class_snapshot="crypto",
                                  status="complete", stats={"n": 12, "win_rate": 0.5, "total_r": 3.4})
    BotScenario.objects.create(user=user, name="Census scenario", symbols=["BTCUSD"],
                               start_date=(T - timedelta(days=30)).date(), end_date=T.date())
    from bot_program.orcs.models import Orc, OrcLeg, OrcSeat, OrcTrack
    seat, _ = OrcSeat.objects.get_or_create(venue="paper", asset_class=paper.asset_class, rule_key="*")
    orc = Orc.objects.create(seat=seat, user=user, config=paper.config, root_trade=paper, symbol=paper.symbol,
                             side=paper.side, asset_class=paper.asset_class, paper=True, army_type="line", state="born")
    OrcLeg.objects.create(orc=orc, trade=paper, kind="root", seq=1)
    OrcTrack.objects.create(orc=orc, arm="care", state={}, open=True)
    from brain.research_models import ResearchConversation, ResearchMessage
    conv = ResearchConversation.objects.create(user=user, title="Census question")
    ResearchMessage.objects.create(conversation=conv, role="user", content="How is the book doing?")
    ResearchMessage.objects.create(conversation=conv, role="assistant", content=(
        "## The book\n\nTwo **paper** positions and three held at eToro.\n\n"
        "| Symbol | Side |\n|---|---|\n| BTCUSD | LONG |\n| ETHUSD | SHORT |\n\n- a synthetic answer\n- for the census"))
    return user, held, paper


# ── serving the page from the test client ──────────────────────────────

def _static(path):
    from django.contrib.staticfiles import finders
    rel = urllib.parse.unquote(path[len(settings.STATIC_URL):])
    found = finders.find(rel)
    if not found and settings.STATIC_ROOT:
        p = pathlib.Path(settings.STATIC_ROOT) / rel
        found = str(p) if p.is_file() else None
    if not found:
        return 404, {"Content-Type": "text/plain"}, b"not found"
    ctype = mimetypes.guess_type(found)[0] or "application/octet-stream"
    if ctype.startswith("text/") or ctype in ("application/javascript",):
        ctype += "; charset=utf-8"
    return 200, {"Content-Type": ctype, "Cache-Control": "max-age=3600"}, pathlib.Path(found).read_bytes()


_HX = re.compile(r"<(?P<tag>[a-z]+)\b(?P<attrs>[^>]*\bhx-get=\"(?P<url>[^\"]+)\"[^>]*)>", re.I)


def _fill_htmx(markup, get):
    """The regions htmx fills by itself (hx-trigger load or every), filled
    from their own routes as htmx would: innerHTML, or the hx-target's."""
    out, pos = [], 0
    for m in _HX.finditer(markup):
        attrs = m.group("attrs")
        trig = re.search(r'hx-trigger="([^"]*)"', attrs)
        if not trig or not re.search(r"\b(load|every)\b", trig.group(1)):
            continue
        if re.search(r'hx-target="', attrs):
            continue
        tag = m.group("tag").lower()
        # the element's own end: count its kind open and shut
        depth, i = 1, m.end()
        opener, closer = re.compile(r"<%s\b" % tag, re.I), re.compile(r"</%s\s*>" % tag, re.I)
        while depth and i < len(markup):
            a, b = opener.search(markup, i), closer.search(markup, i)
            if not b:
                break
            if a and a.start() < b.start():
                depth += 1
                i = a.end()
            else:
                depth -= 1
                i = b.end() if depth else b.start()
        body = get(m.group("url").replace("&amp;", "&"))
        if body is None:
            continue
        out.append(markup[pos:m.end()])
        out.append(body)
        pos = i
    out.append(markup[pos:])
    return "".join(out)


class _Server:
    """Answers Chromium's requests for one scene: the census origin from the
    test client (or static/), Google's font sheet with nothing (the faces
    of the machine draw), every other host refused."""

    def __init__(self, client):
        self.client = client
        self.post = {}          # path regex -> (status, JSON) for a synthetic preview
        self.seen = []

    def get_body(self, path):
        resp = self.client.get(path, HTTP_HOST=HOST, HTTP_HX_REQUEST="true")
        if resp.status_code != 200 or getattr(resp, "streaming", False):
            return None
        return resp.content.decode("utf-8")

    def __call__(self, request, rtype):
        url = urllib.parse.urlsplit(request["url"])
        method = request.get("method", "GET")
        if url.scheme in ("data", "blob"):
            return None
        if url.hostname == "fonts.googleapis.com":
            return 200, {"Content-Type": "text/css; charset=utf-8"}, b""
        if url.hostname != ORIGIN_HOST:
            self.seen.append("refused " + request["url"][:80])
            return None
        path = url.path + ("?" + url.query if url.query else "")
        if url.path.startswith(settings.STATIC_URL):
            return _static(url.path)
        if url.path.startswith("/ws/"):
            return None
        if method not in ("GET", "HEAD"):
            for pattern, (status, payload) in self.post.items():
                if re.search(pattern, url.path):
                    self.seen.append("synthetic %s %s" % (method, url.path))
                    return status, {"Content-Type": "application/json"}, json.dumps(payload).encode("utf-8")
            self.seen.append("withheld %s %s" % (method, url.path))
            return 204, {"Content-Type": "text/plain"}, b""
        headers = {"HTTP_HOST": HOST}
        for k, v in (request.get("headers") or {}).items():
            if k.lower() in ("accept", "x-requested-with", "hx-request", "hx-target", "hx-current-url"):
                headers["HTTP_" + k.upper().replace("-", "_")] = v
        resp = self.client.get(path, **headers)
        if getattr(resp, "streaming", False):
            return None
        body = resp.content
        out = {"Content-Type": resp.get("Content-Type", "text/html; charset=utf-8")}
        if resp.status_code in (301, 302, 303, 307, 308):
            loc = urllib.parse.urlsplit(resp["Location"])
            out["Location"] = ORIGIN + loc.path + ("?" + loc.query if loc.query else "")
        if rtype == "Document" and resp.status_code == 200 and out["Content-Type"].startswith("text/html"):
            body = _fill_htmx(body.decode("utf-8"), self.get_body).encode("utf-8")
        return resp.status_code, out, body


# ── the scenes: every routed page, and the states ──────────────────────

#: The routes measured as pages: every page route but the ones that end
#: the session or are not a page. Parameters come from the book: each
#: detail route is reached by the first link its list page prints.
DETAIL_LINKS = {
    "/bot-backtest/<int:run_id>/": ("/bot-backtest/", r'href="(/bot-backtest/\d+/)"'),
    "/bot/scenarios/<int:pk>/": ("/bot/scenarios/", r'(?:href="|location=\')(/bot/scenarios/\d+/)'),
    "/knowledge/<str:kind>/<path:key>/": ("/knowledge/", r'href="(/knowledge/[a-z_]+/[^"/]+/)"'),
    "/lore/<slug:slug>/": ("/lore/", r'href="(/lore/[\w-]+/)"'),
    "/news/<int:pk>/": ("/news/", r'href="(/news/\d+/)"'),
    "/newsletters/<int:pk>/": ("/newsletters/", r'href="(/newsletters/\d+/)"'),
    "/orcs/<int:trade_id>/": ("/orcs/", r'href="(/orcs/\d+/)"'),
    "/strategies/<int:pk>/": ("/strategies/", r'href="(/strategies/\d+/)"'),
}
#: Anonymous pages, and the pages a session in a given state opens.
ANON = ("/login/", "/wall/", "/book/")
SESSION_STATE = {"/login/pin/": "pending", "/login/pin/forgot/": "pending", "/locked/": "locked", "/intro/": "intro",
                 "/investor/": "investor"}
#: A detail route whose list page prints no link for it: the path asked.
DETAIL_FALLBACK = {"/knowledge/<str:kind>/<path:key>/": "/knowledge/rule/census_up/"}


#: Every routed page: the 105 routes of the old-design sweep (94 under
#: base.html, 11 standalone; read from the URL conf at 349b1ca), but
#: /logout/, which ends the session.
PAGES = (
    "/admin-dashboard/", "/admin-dashboard/books/", "/admin-dashboard/eye/", "/admin-dashboard/newsletters/",
    "/admin-dashboard/system-map/", "/ai-journal/", "/ai-models/", "/ai/", "/ai/tasks/", "/allocator/",
    "/asset-bots/", "/audit/", "/backtest/", "/big-money/", "/book/", "/bot-backtest/",
    "/bot-backtest/<int:run_id>/", "/bot-charts/", "/bot-performance/", "/bot/", "/bot/configure/",
    "/bot/console/", "/bot/link/", "/bot/scenarios/", "/bot/scenarios/<int:pk>/", "/bot/scenarios/new/",
    "/brain/", "/briefing/", "/brokers/", "/calendar/", "/calibration/", "/command/", "/consolidation/",
    "/council/", "/design/kit/", "/desk/", "/discoveries/", "/earnings-reviews/", "/events/", "/evidence/",
    "/evolution/", "/eye/", "/eye/exposure/", "/eye/fills/", "/eye/gate-events/", "/forensics/",
    "/forensics/<int:trade_id>/", "/generated/", "/getting-started/", "/health/", "/horizon/", "/hypotheses/",
    "/instruments/", "/instruments/<str:symbol>/", "/intelligence/", "/intro/", "/investor/",
    "/investor/live/", "/knowledge/", "/knowledge/<str:kind>/<path:key>/", "/liquidations/", "/locked/",
    "/login/", "/login/pin/", "/login/pin/forgot/", "/lore/", "/lore/<slug:slug>/", "/news/",
    "/news/<int:pk>/", "/newsletter/unsubscribe/<str:token>/", "/newsletters/", "/newsletters/<int:pk>/",
    "/notifications/", "/notifications/settings/", "/oculus/", "/opportunities/", "/ops/", "/orcs/",
    "/orcs/<int:trade_id>/", "/orcs/seats/", "/passation/", "/performance/", "/personas/", "/portfolio/",
    "/portfolio/live/", "/positions/", "/positions/live/", "/profile/", "/promotions/", "/research/", "/risk/",
    "/risk/live/", "/rule-control/", "/setup/", "/setups/", "/shares/", "/short-proofs/", "/signals/",
    "/strategies/", "/strategies/<int:pk>/", "/tax-lots/", "/treasury/", "/wall/", "/withdrawals/",
)

#: The live shells: the same view and template as their page, without the
#: shell (dashboard/_live_shell.html), refreshed into the page's live
#: regions. Their markup is the page's own, measured with it.
IN_HOST = {"/positions/live/": "/positions/", "/portfolio/live/": "/portfolio/", "/risk/live/": "/risk/",
           "/investor/live/": "/investor/"}

#: The partial routes, measured in the page that loads them (the critic's
#: hole 1): /command/'s four tabs (live is the page itself), the KPI strips
#: and the bot panel (filled with their pages), /eye/'s body (with /eye/).
PARTIAL_SCENES = (("/command/?tab=portfolio", "/command/tab/portfolio/"),
                  ("/command/?tab=history", "/command/tab/history/"),
                  ("/command/?tab=bots", "/command/tab/bots/"))

#: A browser's start: the clock at T, the saved choices this scene wants,
#: and (unless the scene measures the bell offline) a socket that opens and
#: stays quiet, as the live pipe does between pushes.
#:
#: And the page's slow timers held. Every timer of a second or more (the
#: live pill's first poll at 1.5 s, the nav dots' and Gollum's at 2 s, the
#: Horde's first tab, the Wall's labels every 1.1 s, a whisper hidden after
#: 6 s, every poll) waits on a clock of its own that only the run moves
#: (__svClock.advance), firing them in their order and letting each one's
#: fetches come back before the next. A census read on either side of the
#: 1.5 s poll counted the pill's glow in one run and not in the next, and
#: the Gollum whisper on 34 pages; on the held clock every run reads every
#: page at the same instant of its life, on a fast machine as on a slow
#: one. Timers under a second (a hover's delay, a fade's end) run as they
#: are.
INIT = r"""(function () {
  var nST = window.setTimeout, nCT = window.clearTimeout, nSI = window.setInterval, nCI = window.clearInterval;
  var nFetch = window.fetch, SLOW = 1000, vnow = 0, seq = 0, held = {}, flying = 0;
  function hold(fn, ms, args, every) {
    seq += 1;
    var id = 1000000000 + seq;
    held[id] = {due: vnow + ms, fn: fn, args: args, every: every ? ms : 0, seq: seq};
    return id;
  }
  window.setTimeout = function (fn, ms) {
    ms = +ms || 0;
    if (ms < SLOW) return nST.apply(window, arguments);
    return hold(fn, ms, Array.prototype.slice.call(arguments, 2), false);
  };
  window.setInterval = function (fn, ms) {
    ms = +ms || 0;
    if (ms < SLOW) return nSI.apply(window, arguments);
    return hold(fn, ms, Array.prototype.slice.call(arguments, 2), true);
  };
  window.clearTimeout = function (id) { if (held[id]) delete held[id]; else nCT.call(window, id); };
  window.clearInterval = function (id) { if (held[id]) delete held[id]; else nCI.call(window, id); };
  if (nFetch) {
    window.fetch = function () {
      flying += 1;
      var p = nFetch.apply(this, arguments);
      var done = function () { flying -= 1; };
      p.then(done, done);
      return p;
    };
  }
  var nSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function () {
    flying += 1;
    this.addEventListener('loadend', function () { flying -= 1; });
    return nSend.apply(this, arguments);
  };
  function landed() {
    return new Promise(function (r) {
      var t0 = performance.now();
      (function poll() {
        if (flying <= 0 || performance.now() - t0 > 4000) { nST.call(window, r, 40); return; }
        nST.call(window, poll, 10);
      })();
    });
  }
  window.__svClock = {
    native: function (fn, ms) { return nST.call(window, fn, ms); },
    now: function () { return vnow; },
    advance: async function (ms) {
      var to = vnow + ms, fired = 0;
      await landed();
      for (var guard = 0; guard < 400; guard++) {
        var next = null, nid = null;
        for (var k in held) {
          var h = held[k];
          if (h.due <= to && (!next || h.due < next.due || (h.due === next.due && h.seq < next.seq))) { next = h; nid = k; }
        }
        if (!next) break;
        vnow = next.due;
        if (next.every) next.due += next.every; else delete held[nid];
        try { if (typeof next.fn === 'function') next.fn.apply(window, next.args); }
        catch (e) { (window.__svClockErrors = window.__svClockErrors || []).push(String(e).slice(0, 200)); }
        fired += 1;
        await landed();
      }
      vnow = to;
      return fired;
    }
  };
  var shift = %(t)d - Date.now(), D = Date;
  function SvDate(a, b, c, d, e, f, g) {
    if (!(this instanceof SvDate)) return new D(D.now() + shift).toString();
    var x = arguments.length === 0 ? new D(D.now() + shift)
          : arguments.length === 1 ? new D(a) : new D(a, b, c === undefined ? 1 : c, d || 0, e || 0, f || 0, g || 0);
    return x;
  }
  SvDate.prototype = D.prototype;
  SvDate.now = function () { return D.now() + shift; };
  SvDate.parse = D.parse; SvDate.UTC = D.UTC;
  window.Date = SvDate;
  try {
    localStorage.clear(); sessionStorage.clear();
    var prefs = %(prefs)s;
    for (var k in prefs) localStorage.setItem(k, prefs[k]);
  } catch (e) {}
  if (%(ws)s) {
    window.WebSocket = function (url) {
      var self = this; this.url = url; this.readyState = 0;
      setTimeout(function () { self.readyState = 1; if (self.onopen) self.onopen({}); }, 30);
    };
    window.WebSocket.prototype.send = function () {};
    window.WebSocket.prototype.close = function () { this.readyState = 3; };
    window.WebSocket.prototype.addEventListener = function () {};
    window.WebSocket.OPEN = 1; window.WebSocket.CONNECTING = 0; window.WebSocket.CLOSED = 3;
  }
})();"""

#: The held clock moved on by this many ms, its timers fired in order.
ADVANCE = "(window.__svClock ? window.__svClock.advance(%d) : 0)"
LOAD_MS, ACT_MS = 2600, 1600

#: The page at rest, whatever the clock did. A card the motion layer
#: (sv-motion.js) hid below the fold until it scrolls in, or until its
#: safety timer 2.5 s after the load, is shown now, as the operator sees
#: it once there: the census measured it in one run and not in the next
#: when it ran either side of that timer. A count-up the scroll of an
#: act started is let finish. Finite animations end where they end; a
#: loop is left running, it is what anim_loop counts.
SETTLE = r"""(async function (ms) {
  try { await document.fonts.ready; } catch (e) {}
  var frame = function () { return new Promise(function (r) { requestAnimationFrame(function () { requestAnimationFrame(r); }); }); };
  var sleep = function (t) { return new Promise(function (r) { setTimeout(r, t); }); };
  await frame();
  await sleep(ms);
  document.querySelectorAll('.sv-rv').forEach(function (el) {
    el.classList.remove('sv-rv', 'in'); el.style.removeProperty('--sv-i');
  });
  if (document.body) document.body.classList.remove('sv-leaving');
  var counting = function () {
    return Array.prototype.filter.call(document.querySelectorAll('[data-sv-count]'), function (e) { return e.__svCounted; })
      .map(function (e) { return e.textContent; }).join('|');
  };
  var was = counting();
  for (var tick = 0; was && tick < 15; tick++) {
    await sleep(120);
    var now = counting();
    if (now === was) break;
    was = now;
  }
  for (var round = 0; round < 6; round++) {
    var moving = 0;
    document.getAnimations().forEach(function (a) {
      var t = a.effect && a.effect.getComputedTiming();
      if (t && t.iterations !== Infinity && a.playState !== 'finished') { moving++; try { a.finish(); } catch (e) {} }
    });
    await frame();
    if (!moving) break;
  }
  return 1;
})(%d)"""


#: What the critic's hole 1 is about, read after the census: regions htmx
#: or a script fills, and whether they were filled.
PROBE = r"""(function () {
  function n(sel) { return document.querySelectorAll(sel).length; }
  return {metricsEmpty: n('.sv-metrics-wrapper:empty'), metricsFilled: n('.sv-metrics-wrapper > *'),
          ocLoading: n('#ocTabBody .oc-loading, .oc-loading'), ocBody: n('#ocTabBody > *'),
          adminBots: n('.admin-bots'), eyeBody: n('#eyeBody > *, [hx-get*="/eye/partial/"] > *'),
          railCards: n('.signals-rail .sr-signal'), dialogs: n('.sv-dialog'), popups: n('.sr-popup.show, .sr-popup.sv-pinned'),
          width: innerWidth};
})()"""


def _click(sel, nth=0, text=None):
    return ("(function () { var all = Array.prototype.filter.call(document.querySelectorAll(%s), function (e) {"
            " return e.checkVisibility() && (!%s || (e.innerText || '').toUpperCase().indexOf(%s) >= 0); });"
            " var e = all[%d]; if (!e) throw new Error('nothing to click: ' + %s);"
            " e.scrollIntoView({block: 'center'}); e.click(); return all.length; })()"
            % (json.dumps(sel), json.dumps(text), json.dumps(text or ""), nth, json.dumps(sel)))


def _hover(sel):
    return ("(function () { var e = document.querySelector(%s); if (!e) throw new Error('nothing to hover: ' + %s);"
            " e.scrollIntoView({block: 'center'}); ['pointerover', 'pointerenter', 'mouseover', 'mouseenter', 'mousemove']"
            ".forEach(function (k) { e.dispatchEvent(new MouseEvent(k, {bubbles: k.indexOf('enter') < 0, cancelable: true,"
            " view: window})); }); return 1; })()" % (json.dumps(sel), json.dumps(sel)))


def _then(*steps, wait=500):
    """Steps run in order, each followed by `wait` ms."""
    body = "".join("await Promise.resolve(%s); await new Promise(function (r) { setTimeout(r, %d); });" % (s, wait)
                   for s in steps)
    return "(async function () { %s return 1; })()" % body


class Scene(dict):
    """One measurement: a path, the client that asks it, the saved choices,
    what is done on the page, and how it is read (rest, forced, phone,
    light)."""

    def __init__(self, key, path, **kw):
        super().__init__(key=key, path=path, client=kw.pop("client", "main"), rail=kw.pop("rail", "closed"),
                         sidebar=kw.pop("sidebar", "full"), bands=kw.pop("bands", False), ws=kw.pop("ws", True),
                         act=kw.pop("act", None), post=kw.pop("post", {}), real_post=kw.pop("real_post", ()),
                         mode=kw.pop("mode", "rest"), width=kw.pop("width", 1440), height=kw.pop("height", 900),
                         mobile=kw.pop("mobile", False), cookie=kw.pop("cookie", None), need=kw.pop("need", None))
        assert not kw, kw


FORCED_PAGES = ("/positions/", "/ops/", "/instruments/EURUSD/", "/brokers/", "/setup/", "/withdrawals/",
                "/asset-bots/", "/command/", "/admin-dashboard/")
PHONE_PAGES = ("/positions/", "/ops/", "/instruments/EURUSD/", "/brokers/", "/setup/", "/withdrawals/",
               "/asset-bots/", "/command/")
LIGHT_PAGES = ("/positions/", "/ops/", "/command/")
#: What the phone and light passes read (holes 3 and 4, §10).
PHONE_MARKERS = ("target_small", "sideways", "red_fill")
LIGHT_MARKERS = ("red_fill",)

#: Synthetic close previews (the shape base.html's closeFlow reads; never
#: sent to the server): a live EURUSD row and a paper BTCUSD row.
CLOSE_PREVIEW = {
    "live": {"ok": True, "side": "BUY", "qty": "10,000", "symbol": "EURUSD", "entry": "1.08210", "mark": 1.08452,
             "exit": "1.08447", "pnl": "+23.70", "r": "0.76", "venue": "live", "asset_class": "forex"},
    "paper": {"ok": True, "side": "BUY", "qty": "0.05", "symbol": "BTCUSD", "entry": "63,800.00", "mark": 64200.0,
              "exit": "64,190.00", "pnl": "+19.50", "r": "0.30", "venue": "paper", "asset_class": "crypto"},
}


def build_scenes(details, live_id, paper_id):
    """Every scene of a run: the pages, the partial routes, the states, the
    forced, phone and light passes, the error pages."""
    out = []
    for route in PAGES:
        if route in IN_HOST:
            continue
        if route == "/instruments/<str:symbol>/":
            out += [Scene("/instruments/EURUSD/", "/instruments/EURUSD/"), Scene("/instruments/BTCUSD/", "/instruments/BTCUSD/")]
        elif route == "/forensics/<int:trade_id>/":
            out += [Scene("/forensics/<live>/", "/forensics/%d/" % live_id),
                    Scene("/forensics/<paper>/", "/forensics/%d/" % paper_id)]
        elif route == "/newsletter/unsubscribe/<str:token>/":
            out.append(Scene(route, details.get(route) or "/newsletter/unsubscribe/census/", client="anon"))
        elif route in DETAIL_LINKS:
            out.append(Scene(route, details.get(route), need=route))
        elif route in ANON:
            out.append(Scene(route, route, client="anon"))
        elif route in SESSION_STATE:
            out.append(Scene(route, route, client=SESSION_STATE[route]))
        else:
            out.append(Scene(route, route))
    for path, partial in PARTIAL_SCENES:
        out.append(Scene(partial, path))
    S = lambda key, path="/command/", **kw: out.append(Scene("state:" + key, path, **kw))
    S("rail_bullish", "/positions/", rail="open",
      act=_click(".signals-rail .sr-signal-wrap:not(:has(.sr-badge-bearish)) .sr-signal"))
    S("rail_bearish", "/positions/", rail="open", act=_click(".signals-rail .sr-signal-wrap:has(.sr-badge-bearish) .sr-signal"))
    S("rail_dock", "/command/", rail="closed")
    S("quote_card", act=_then(_hover(".data-headband .dh-item"), _click(".data-headband .dh-item")))
    S("news_card", act=_hover(".ticker-bar .ticker-item"))
    for name in ("PORTFOLIO", "POSITIONS", "SIGNALS"):
        S("bar_" + name.lower(), act=_click(".info-panel-wrap .ip-cat", text=name))
    S("bell", act=_click("#notifBell"))
    S("bell_offline", ws=False, act=_click("#notifBell"))
    S("user_menu", act=_click("#userMenuTrigger"))
    S("sessions_menu", act=_then(_hover(".exchange-indicator"), _click(".exchange-trigger")))
    S("live_status", act=_click("#liveStatusPill"))
    S("instrument_preview", "/instruments/", act=_hover("[data-instrument]"))
    S("fill_banner", act="window.svBanner('fill_open', {symbol: 'BTCUSD', side: 'BUY', qty: '0.05', entry: '64,200.00',"
                         " asset_class: 'crypto', rule_name: 'census_up', paper: true}) || 1")
    S("horde", "/positions/", act=_click("#svHordeTab"))
    S("council", act=_click("#svCouncilBandTab"))
    S("activity", act=_click("#svActivityTab"))
    S("ask_sauron", act=_click("#seEyeFab"))
    S("gollum", act=_click("#gollumFab"))
    S("tour", act="(window.SV && SV.tour && SV.tour.start(), 1)")
    S("kbd_help", act="document.dispatchEvent(new KeyboardEvent('keydown', {key: '?', shiftKey: true, bubbles: true})) && 1")
    S("idle_lock", act="(window.svIdleLock && window.svIdleLock.engage(false), 1)")
    S("sidebar_mini", sidebar="mini", act=_hover(".sidebar .nav-link:not(.active)"))
    S("bands_hidden", bands=True)
    S("bar_minimised", act=_click("#ipMinTab"))
    S("take_trade_paper", "/instruments/BTCUSD/", act=_click(".tk-side.tk-long"),
      real_post=(r"^/instruments/BTCUSD/take-trade/preview/$",))
    # Made from the paper preview at run time ("@live", "@short").
    S("take_trade_live", "/instruments/EURUSD/", act=_click(".tk-side.tk-long"),
      post={r"/take-trade/preview/$": (200, "@live")})
    S("take_trade_short", "/instruments/BTCUSD/", act=_click(".tk-side.tk-long"),
      post={r"/take-trade/preview/$": (200, "@short")})
    S("close_live", "/positions/", act=_click('[data-sv-close-trade="%d"]' % live_id),
      post={r"/positions/\d+/close/preview/$": (200, CLOSE_PREVIEW["live"])})
    S("close_paper", "/positions/", act=_click('[data-sv-close-trade="%d"]' % paper_id),
      post={r"/positions/\d+/close/preview/$": (200, CLOSE_PREVIEW["paper"])})
    S("close_all_preview", "/positions/", act=_click("#svCloseAll"), real_post=(r"^/positions/close-all/preview/$",))
    S("close_selected_preview", "/positions/",
      act=_then(_click("[data-sv-select-trade]"), _click("[data-sv-select-bar] button", text="CLOSE")),
      real_post=(r"^/positions/close-selected/preview/$", r"^/positions/close-advice/$"))
    S("level_editor", "/positions/", act=_click(".lvl-edit"))
    S("deep_link", "/positions/%d/close-dialog/" % live_id)
    S("messages", "/withdrawals/", cookie="messages")
    S("wall_signin", "/wall/?next=/positions/", client="anon")
    S("wall_pin", "/wall/?next=/positions/", client="anon", act="document.body.classList.add('pin-mode') || 1")
    S("empty_positions", "/positions/", client="empty")
    S("empty_command", "/command/", client="empty")
    for page in FORCED_PAGES:
        out.append(Scene("hover:" + page, page, mode="forced"))
    out.append(Scene("hover:state:take_trade_paper", "/instruments/BTCUSD/", mode="forced", act=_click(".tk-side.tk-long"),
                     real_post=(r"^/instruments/BTCUSD/take-trade/preview/$",)))
    out.append(Scene("hover:state:close_live", "/positions/", mode="forced", act=_click('[data-sv-close-trade="%d"]' % live_id),
                     post={r"/positions/\d+/close/preview/$": (200, CLOSE_PREVIEW["live"])}))
    for page in PHONE_PAGES:
        out.append(Scene("390:" + page, page, mode="phone", width=390, height=844, mobile=True))
    for page in LIGHT_PAGES:
        out.append(Scene("light:" + page, page, mode="light"))
    for code in ("404", "403", "403_csrf", "500"):
        out.append(Scene("error:" + code, "/__census__/error/%s/" % code, client="anon"))
    return out


# ── the run ─────────────────────────────────────────────────────────────

def faces_present():
    """Whether the machine draws Inter and JetBrains Mono itself (the glyph
    census reads which face drew each glyph; on a machine without them
    every glyph would fall to another face). The CI job installs both."""
    try:
        out = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return "Inter" in out and "JetBrains Mono" in out


def _error_page(code):
    from django.core.exceptions import PermissionDenied
    from django.http import Http404
    from django.views import defaults
    from django.views.csrf import csrf_failure
    req = RequestFactory().get("/signals/999999/ticket/")
    if code == "404":
        return defaults.page_not_found(req, Http404("census"))
    if code == "403":
        return defaults.permission_denied(req, PermissionDenied("census"))
    if code == "403_csrf":
        return csrf_failure(req, reason="CSRF token from POST incorrect.")
    return defaults.server_error(req)


def _messages_cookie():
    from django.contrib.messages import constants
    from django.contrib.messages.storage.base import Message
    from django.contrib.messages.storage.cookie import CookieStorage
    st = CookieStorage(RequestFactory().get("/"))
    return st.cookie_name, st._encode([Message(constants.SUCCESS, "Saved: the synthetic reservation."),
                                       Message(constants.ERROR, "Refused: a synthetic error, nothing was changed.")])


class _SceneOver(Exception):
    pass


@contextlib.contextmanager
def _scene_apart():
    """One scene's writes undone after it: the database (a transaction
    rolled back) and the in-memory cache (put back as it was). A page writes
    as it loads (the nav dots stamp it seen, which changes the dots and
    Gollum's whisper on every page after it; a preview leaves its row), and
    a scene read after another must read the same book as one read first,
    whatever shard the order of the scenes puts it in."""
    from django.core.cache import caches
    from django.core.cache.backends.locmem import LocMemCache
    from django.db import transaction
    kept = [(c, collections.OrderedDict(c._cache), dict(c._expire_info))
            for c in caches.all() if isinstance(c, LocMemCache)]
    box = {}
    try:
        with transaction.atomic():
            yield box
            raise _SceneOver
    except _SceneOver:
        pass
    finally:
        for c, data, expiry in kept:
            with c._lock:
                c._cache.clear()
                c._cache.update(data)
                c._expire_info.clear()
                c._expire_info.update(expiry)


class CensusRun:
    """One Chromium, every scene in turn, each apart from the others
    (_scene_apart). results[key] = {counts, examples, geo, status, seen,
    error}."""

    def __init__(self, clients, scenes, glyphs=True, previews=None):
        self.clients, self.scenes, self.glyphs = clients, scenes, glyphs
        self.made = previews or {}
        self.results, self.previews, self.timing = {}, {}, {}
        self.source = CENSUS_JS.read_text(encoding="utf-8")
        self.opts = {"tokens": token_rgbs(), "radii": token_radii(), "money": MONEY, "examples": 40}

    def answer_for(self, scene, server):
        status = {}

        def answer(request, rtype):
            url = urllib.parse.urlsplit(request["url"])
            if url.hostname == ORIGIN_HOST and url.path.startswith("/__census__/error/"):
                resp = _error_page(url.path.strip("/").rsplit("/", 1)[-1])
                status["doc"] = resp.status_code
                return resp.status_code, {"Content-Type": resp.get("Content-Type", "text/html")}, resp.content
            if url.hostname == ORIGIN_HOST and request.get("method") == "POST" and any(
                    re.search(p, url.path) for p in scene["real_post"]):
                body = (request.get("postData") or "").encode("utf-8")
                ctype = (request.get("headers") or {}).get("Content-Type", "application/x-www-form-urlencoded")
                resp = server.client.generic("POST", url.path, data=body, content_type=ctype, HTTP_HOST=HOST,
                                             HTTP_X_REQUESTED_WITH="XMLHttpRequest")
                try:
                    self.previews[url.path] = json.loads(resp.content)
                except ValueError:
                    pass
                server.seen.append("previewed POST %s %s" % (url.path, resp.status_code))
                return resp.status_code, {"Content-Type": resp.get("Content-Type", "application/json")}, resp.content
            got = server(request, rtype)
            if rtype == "Document" and got is not None and "doc" not in status:
                status["doc"] = got[0]
            return got
        return answer, status

    def run(self):
        driver = _Driver(CHROME, answer=lambda r, t: None)
        t0 = time.monotonic()
        try:
            for scene in self.scenes:
                t1 = time.monotonic()
                # The clients' cookies too: a session a scene turned over
                # would point at a row the rollback took away.
                jars = {name: copy.deepcopy(c.cookies) for name, c in self.clients.items()}
                try:
                    with _scene_apart() as box:
                        box["res"] = self.one(driver, scene)
                finally:
                    for name, jar in jars.items():
                        self.clients[name].cookies = jar
                self.results[scene["key"]] = box["res"]
                self.timing[scene["key"]] = round(time.monotonic() - t1, 2)
        finally:
            driver.close()
        self.timing["__total__"] = round(time.monotonic() - t0, 1)
        return self.results

    def one(self, driver, scene):
        res = {"counts": {}, "examples": {}, "geo": {}, "status": None, "seen": [], "error": None}
        if scene["path"] is None:
            res["error"] = "no %s in the book" % scene["need"]
            return res
        client = self.clients[scene["client"]]
        if scene["cookie"] == "messages":
            name, value = _messages_cookie()
            client.cookies[name] = value
        server = _Server(client)
        for pattern, (code, payload) in scene["post"].items():
            if isinstance(payload, str) and payload.startswith("@"):
                if payload[1:] not in self.made:
                    res["error"] = "no paper preview to make the %s one from" % payload[1:]
                    return res
                payload = self.made[payload[1:]]
            server.post[pattern] = (code, payload)
        answer, status = self.answer_for(scene, server)
        driver.answer = answer
        prefs = {"sauron_signals_rail": scene["rail"], "sauron_sidebar": scene["sidebar"]}
        if scene["bands"]:
            prefs.update({"sauron_hb_ticker": "1", "sauron_hb_data": "1"})
        init = INIT % {"t": int(_frozen_instant().timestamp() * 1000), "prefs": json.dumps(prefs),
                       "ws": "true" if scene["ws"] else "false"}
        tid, sid = driver.tab(scene["width"], scene["height"], scene["mobile"], init)
        try:
            driver.go(sid, ORIGIN + scene["path"])
            # The page read 2.6 s into its life on the held clock (INIT):
            # its first polls answered, the motion layer's safety passed.
            driver.js(sid, ADVANCE % LOAD_MS)
            driver.quiet(sid)
            driver.js(sid, SETTLE % 100)
            if scene["act"]:
                try:
                    driver.js(sid, scene["act"])
                except RuntimeError as exc:
                    res["error"] = "the state was not reached: %s" % str(exc)[:200]
                # A state read 1.6 s into its life: what it starts a second
                # later is in (the Horde's first tab), what it ends after
                # 1.8 s and more (a toast, a banner's ttl) is not yet over.
                driver.js(sid, ADVANCE % ACT_MS)
                driver.quiet(sid)
                driver.js(sid, SETTLE % 300)
            if scene["mode"] == "forced":
                res["forced"] = driver.force(sid, SHELL_INTERACTIVE + ", " + MONEY, ["hover", "focus-visible", "active"])
                driver.quiet(sid)
                driver.js(sid, SETTLE % 100)
            if scene["mode"] == "light":
                driver.js(sid, "document.body.classList.add('light-mode') || 1")
                driver.js(sid, SETTLE % 100)
            opts = dict(self.opts, phone=scene["mode"] == "phone")
            got = driver.js(sid, self.source + "\n;census(%s)" % json.dumps(opts))
            counts = got["counts"]
            if self.glyphs and scene["mode"] == "rest" and got["glyphs"]:
                doc = driver.call("DOM.getDocument", {"depth": 0}, session=sid)["root"]["nodeId"]
                found = driver.call_many([("DOM.querySelector", {"nodeId": doc, "selector": '[data-svc="%d"]' % g[0]})
                                          for g in got["glyphs"]], sid)
                held = [(g, f.get("nodeId")) for g, f in zip(got["glyphs"], found) if f.get("nodeId")]
                faces = driver.call_many([("CSS.getPlatformFontsForNode", {"nodeId": nid}) for _g, nid in held], sid)
                for (g, _nid), answer in zip(held, faces):
                    # One per text holder some glyph of which no face of the
                    # four drew (the colour emoji included): which face of the
                    # machine stood in differs from one machine to another, that
                    # the four could not draw it does not.
                    index, signature, key, text = g
                    fonts = answer.get("fonts", [])
                    other = [f for f in fonts if not any(f["familyName"].startswith(face) for face in FACES)]
                    if other:
                        counts["glyph_face"] = counts.get("glyph_face", 0) + 1
                        ex = got["examples"].setdefault("glyph_face", [])
                        if len(ex) < 40:
                            ex.append([1, key, "drawn by", ", ".join("%s (%d)" % (f["familyName"], f["glyphCount"])
                                                                   for f in other), text])
            if scene["mode"] == "phone":
                counts = {k: v for k, v in counts.items() if k in PHONE_MARKERS}
            elif scene["mode"] == "light":
                counts = {k: v for k, v in counts.items() if k in LIGHT_MARKERS}
            res.update(counts=dict(sorted(counts.items())), examples=got["examples"], geo=got["geo"],
                       n=got["n"], url=got["url"], probe=driver.js(sid, PROBE))
        except (RuntimeError, TimeoutError) as exc:
            res["error"] = str(exc)[:300]
        finally:
            driver.close_tab(tid)
        res["status"] = status.get("doc")
        res["seen"] = server.seen[:30]
        return res


def census_clients(user):
    """The test clients a run asks with: the operator, a stranger, a
    session at the PIN step, a locked session, one before the intro, and a
    reader with an empty book."""
    from dashboard.auth_views import PENDING_KEY
    main = Client()
    main.force_login(user)
    anon = Client()
    pending = Client()
    s = pending.session
    s[PENDING_KEY] = user.id
    s.save()
    locked = Client()
    locked.force_login(user)
    s = locked.session
    s["pin_locked"] = True
    s.save()
    intro = Client()
    intro.force_login(user)
    empty_user = get_user_model().objects.create_user("census_empty", password="x", is_staff=True)
    empty = Client()
    empty.force_login(empty_user)
    from portfolio.investor_models import InvestorAccess
    lp = get_user_model().objects.create_user("census_lp", password="x")
    InvestorAccess.objects.create(investor=lp, owner=user, label="Census fund")
    investor = Client()
    investor.force_login(lp)
    return {"main": main, "anon": anon, "pending": pending, "locked": locked, "intro": intro, "empty": empty,
            "investor": investor}


def resolve_details(client, user):
    """Each detail route's path, from the first link its list page prints
    (None where the book gives the list page no row)."""
    from alerts.models import Newsletter
    fallback = dict(DETAIL_FALLBACK)
    letter = Newsletter.objects.order_by("pk").first()
    if letter:      # the archive lists what was mailed to a reader; staff open any edition
        fallback["/newsletters/<int:pk>/"] = "/newsletters/%d/" % letter.pk
    out = {}
    for route, (listing, pattern) in DETAIL_LINKS.items():
        resp = client.get(listing, HTTP_HOST=HOST)
        m = re.search(pattern, resp.content.decode("utf-8")) if resp.status_code == 200 else None
        out[route] = m.group(1) if m else fallback.get(route)
    try:
        from alerts.newsletter_service import unsubscribe_path
        out["/newsletter/unsubscribe/<str:token>/"] = unsubscribe_path(user)
    except Exception:       # the letter's signer needs a setting this machine lacks: a token that does not verify
        out["/newsletter/unsubscribe/<str:token>/"] = None
    return out


def live_previews(paper):
    """A TAKE TRADE preview on a live world, and a paper one short of
    capital, made from the paper preview the view answered (never sent to
    a broker: the browser receives them from here)."""
    if not isinstance(paper, dict):
        return {}
    live = json.loads(json.dumps(paper))
    for k in ("venue", "world", "mode"):
        if k in live:
            live[k] = "live"
    for k in ("paper", "is_paper"):
        if k in live:
            live[k] = False
    for k in ("live", "is_live", "requires_pin"):
        if k in live:
            live[k] = True
    short = json.loads(json.dumps(paper))
    short["sufficient"] = False
    short.setdefault("closable", [])
    return {"live": live, "short": short}


_RUN = {}


def measured_run():
    """The run every measured class reads (one per test process)."""
    return _RUN


#: The measured half runs in four shards (one Chromium and one book each),
#: so a parallel run spreads it over the machine's workers: scene k falls
#: to shard k mod 4, every group (pages, states, passes) across all four.
SHARDS = 4


def shard_of(scenes, i, n=SHARDS):
    return [s for k, s in enumerate(scenes) if k % n == i]


class _MeasuredShard:
    """The measured half, one shard: every routed page, the partial routes
    in their pages, the shell's states, the forced pass, the phone pass and
    light mode's §10 check, each held to its budget. Set SV_OLD_DESIGN_ONLY
    to a comma list of scene keys (or their beginnings) to measure only
    those while a batch works; SV_OLD_DESIGN_DUMP=<path> writes the run."""

    SHARD = 0
    maxDiff = None

    @classmethod
    def setUpTestData(cls):
        from django.core.cache import cache
        cls._patches = freeze_patches()
        for p in cls._patches:
            p.start()
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
            previews = live_previews(next(iter(first.previews.values()), None))
        cls.glyphs = faces_present()
        run = CensusRun(clients, scenes, glyphs=cls.glyphs, previews=previews)
        run.run()
        cls.scene_keys = [s["key"] for s in scenes]
        cls.results, cls.timing = run.results, run.timing
        _RUN.setdefault("results", {}).update(run.results)
        _RUN.setdefault("timing", {})["shard %d" % cls.SHARD] = run.timing.get("__total__")
        dump = os.environ.get("SV_OLD_DESIGN_DUMP")
        if dump:
            path = pathlib.Path(dump.replace(".json", "") + "_shard%d.json" % cls.SHARD)
            path.write_text(json.dumps({"results": run.results, "timing": run.timing, "details": details,
                                        "glyphs": cls.glyphs, "previews": previews}, indent=1, default=str))

    @classmethod
    def tearDownClass(cls):
        for p in getattr(cls, "_patches", ()):
            try:
                p.stop()
            except RuntimeError:
                pass
        super().tearDownClass()

    def test_every_scene_was_measured(self):
        """Every page answered and was read, every state was reached; what
        the book cannot reach is recorded in the budget ("unreached"), and
        still unreached (so a fixture that reaches it updates the record)."""
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
        the page or state, then the elements grouped by selector, with the
        property and the value."""
        over = compare_measured(self.results, load_budget()["measured"], glyphs=self.glyphs)
        if os.environ.get("SV_OLD_DESIGN_LOWER") and not over and not self.only:
            lower_measured_budgets(self.results)
        self.assertEqual(over, [], "old design above its measured budget:\n" + "\n".join(over))

    def test_a_strict_page_is_at_zero(self):
        """STRICT (none at B0): a page or state a batch has emptied stays
        empty, its budget gone."""
        budget = load_budget()
        for key in budget["strict"]["measured"]:
            with self.subTest(scene=key):
                self.assertNotIn(key, budget["measured"])
                if key in self.results:
                    self.assertEqual(self.results[key]["counts"], {})

    def test_the_critic_s_holes_are_measured(self):
        """Hole 1: the regions htmx and scripts fill are filled (the KPI
        strips, /command/'s tab bodies, the bot panel, /eye/'s body, the
        rail's cards); hole 2: the forced pass reached the shell and the
        money controls; hole 3: the phone pass ran at 390 px."""
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
        if not self.only:
            self.assertGreater(checks, 3)


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
@tag("old_design_measured")
class MeasuredShard1Tests(_MeasuredShard, TestCase):
    SHARD = 0


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
@tag("old_design_measured")
class MeasuredShard2Tests(_MeasuredShard, TestCase):
    SHARD = 1


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
@tag("old_design_measured")
class MeasuredShard3Tests(_MeasuredShard, TestCase):
    SHARD = 2


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
@tag("old_design_measured")
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

    def test_every_page_route_is_a_scene(self):
        """The 104 routes (the sweep's 105 but /logout/) and about forty
        states: the plan's "every routed page and about 25 states", and
        the critic's."""
        keys = {s["key"] for s in self.scenes()}
        for route in PAGES:
            if route in IN_HOST:
                continue
            with self.subTest(route=route):
                self.assertTrue(route in keys or any(k.startswith(route.split("<")[0]) for k in keys))
        self.assertGreaterEqual(len([k for k in keys if k.startswith("state:")]), 25)


# ── the measured budget ─────────────────────────────────────────────────

GLYPH_MARKERS = ("glyph_face",)


def why_unread(key, r):
    """Why a scene was not read as itself: the state was not reached, or the
    page did not answer 200 (an error page's own code is its point). Such a
    scene is recorded in "unreached", and never compared with a budget: a
    page sent elsewhere was read as the page it was sent to."""
    if r.get("error"):
        return r["error"]
    if r.get("status") not in (200, None) and not key.startswith("error:"):
        return "status %s" % r["status"]
    return None


def compare_measured(results, budget, glyphs=True):
    """One message per scene and marker above its budget, naming the page
    or state, and for each element the selector, the property and the
    value (a scene absent from the budget must be at zero)."""
    over = []
    for key in sorted(results):
        r = results[key]
        if why_unread(key, r):
            continue
        allowed = budget.get(key, {})
        for marker, n in sorted(r["counts"].items()):
            if not glyphs and marker in GLYPH_MARKERS:
                continue
            if n > allowed.get(marker, 0):
                head = "%s: %s %d, budget %d%s" % (key, marker, n, allowed.get(marker, 0),
                                                   "" if key in budget else " (a page absent from the budget is at zero)")
                lines = ["      x%d  %s  %s: %s  %r" % (k, sel, prop, value, text[:40])
                         for k, sel, prop, value, text in r["examples"].get(marker, [])]
                over.append("\n".join([head] + lines))
    return over


def measured_budget_from(results, glyphs=True):
    out = {}
    for key, r in sorted(results.items()):
        if why_unread(key, r):
            continue
        counts = {m: n for m, n in r["counts"].items() if n and (glyphs or m not in GLYPH_MARKERS)}
        if counts:
            out[key] = dict(sorted(counts.items()))
    return out


def lower_measured_budgets(results=None, write=True):
    """Every measured budget lowered to the run's count where the count went
    down (never raised): after a batch, run the measured half with
    SV_OLD_DESIGN_LOWER=1."""
    results = results or measured_run().get("results") or {}
    budget = load_budget()
    meas = budget.setdefault("measured", {})
    changes = []
    for key, r in results.items():
        if why_unread(key, r) or key not in meas:
            continue
        for marker in list(meas[key]):
            got = r["counts"].get(marker, 0)
            if got < meas[key][marker]:
                changes.append("%s %s %d -> %d" % (key, marker, meas[key][marker], got))
                if got:
                    meas[key][marker] = got
                else:
                    del meas[key][marker]
        if not meas[key]:
            del meas[key]
    if write and changes:
        write_budget(budget)
    return changes


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


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
@tag("old_design_measured")
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
        opts = {"tokens": token_rgbs(), "radii": token_radii(), "money": MONEY, "examples": 40}
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
        self.assertEqual(compare_measured(self.result("clean"), budget, glyphs=False), [])
        over = compare_measured(self.result("marked"), budget, glyphs=False)
        joined = "\n".join(over)
        self.assertIn("/design/kit/: glow", joined)
        self.assertIn("x1  div.card.sv-meta-card  box-shadow: rgba(0, 232, 104, 0.6) 18px", joined)
        self.assertIn("/design/kit/: color_off 1, budget 0", joined)
        self.assertIn("x1  span.sv-meta-fig.mono  color: rgb(18, 52, 86)  '1,234.50'", joined)
        self.assertIn("/design/kit/: inline_visual", joined)
        # the copy without them passes again
        self.assertEqual(compare_measured(self.result("again"), budget, glyphs=False), [])
