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
    browser computes them. Its own docstring is below, with its classes.

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
import collections
import html.parser
import io
import json
import os
import pathlib
import re
import tokenize
import unicodedata

from django.conf import settings
from django.test import SimpleTestCase

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


def file_hits(path):
    rel = path.relative_to(ROOT).as_posix()
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
