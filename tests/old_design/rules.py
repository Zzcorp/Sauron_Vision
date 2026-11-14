"""The source half's census (tests/test_zero_old_design.py, B0): every
scanned file's old markers, read from its text. No browser, no database.
The markers are listed in the test module's docstring."""
import collections
import html.parser
import pathlib
import re
import unicodedata

from django.conf import settings

ROOT = pathlib.Path(settings.BASE_DIR)

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
#: The kit's own page, and its specimens: a swatch shows a token by
#: painting it, the type scale and the wordmark show the sizes and the Eye
#: they document (the measured half's SPECIMEN, the same list).
KIT_PAGE = "templates/dashboard/design_kit.html"
SPECIMEN_CLASS = re.compile(r"(?<![\w-])(dk-icon|dk-chip-sample|dk-scale-row)(?![\w-])")
#: The magic's own scripts (2026-11-12, merged in #106): the embers' canvas
#: and the moments draw the Eye's light, which is theirs to draw.
MAGIC_SCRIPTS = ("static/js/sv-embers.js", "static/js/sv-moments.js")
#: The frame's sheet (B1, the desk v2 board the operator approved on
#: 2026-11-13) draws the magic's light where the board draws it, and its
#: lights are named here one by one (frame_light()): each by its selector,
#: its property and its value as the sheet writes them (white space aside).
#: Only those are read as the magic's own, their Eye literal, glow and
#: gradient not counted:
#:   under Magic and Calm, the Eye's halo in the 44 px head and the feed
#:   pill's live dot (Desk2's .dot.live);
#:   the docked Eye, Ask Sauron's orb at the bar's end (Desk2's .orb): its
#:   sphere, ring and core in every ambience (.amb-off .orb keeps them),
#:   its glow under Magic and Calm.
#: Anything else written there is read like any sheet's: another selector
#: (one that only names the orb's class or the ambience, in :not(), :is(),
#: :where() or :has(), or before a sibling; a descendant of the orb; a
#: list with one more item), another property, another value, another
#: ambience. The review of #115's guard rules (on a0a6b7a) found the sheet
#: read like the kit's (any rule naming the ambience, any rule whose items'
#: subjects named the orb's class), which let a glow, an Eye literal or a
#: gradient onto any element there. The old floating Eye's rules
#: (sauron.css, sv-overlay.css) are counted under the same class.
FRAME_SHEET = "static/css/sv-frame.css"
_FRAME_LIT = 'html body:not(.light-mode):is([data-sv-ambience="magic"], [data-sv-ambience="calm"])'
FRAME_LIGHT = (
    (_FRAME_LIT + " .sidebar .sidebar-brand .brand-eye-wrap::before", "background",
     "radial-gradient(circle, rgba(0,232,104,.34) 0%, rgba(0,232,104,.16) 40%, rgba(0,232,104,0) 70%)"),
    (_FRAME_LIT + " .live-status-pill .lsp-green", "box-shadow", "var(--sv-glow-dot)"),
    ("html body .se-eye-fab:not(.open)", "background",
     "radial-gradient(circle at 38% 34%, rgba(220,255,235,.55) 0 8%, rgba(0,232,104,.35) 22%, "
     "rgba(4,30,16,.95) 62%, var(--sv-bg-0) 100%)"),
    ("html body .se-eye-fab:not(.open)", "box-shadow", "inset 0 0 0 1px rgba(0,232,104,.55)"),
    ("html body .se-eye-fab:not(.open)::after", "background",
     "radial-gradient(circle, rgba(0,232,104,.95), rgba(0,232,104,0) 70%)"),
    (_FRAME_LIT + " .se-eye-fab:not(.open)", "box-shadow",
     "inset 0 0 0 1px rgba(0,232,104,.55), 0 0 10px rgba(0,232,104,.28)"),
)
#: The tower's Eye (B1, the desk v2 board: Barad-dûr's silhouette in the
#: menu's empty foot, Twist2's "la tour en filigrane"): one fill of the
#: Eye's token, in the frame's sheet, a faint ember at its dose in the same
#: rule (frame_ember()). The tower is no place of the brand: a rule or a
#: template that names it is read like any other.
FRAME_EMBER = (".sv-tower .sv-tower-eye", "fill", "var(--sv-eye)", ("fill-opacity", ".35"))
#: The files whose hex colours must be token values (emails, PDF, tags).
PALETTE_FILES = re.compile(r"^(templates/email/|templates/newsletter/|core/templatetags/|"
                           r"dashboard/reports\.py$|dashboard/views_bot_charts\.py$)")

Hit = collections.namedtuple("Hit", "file line marker text")


# ── colours ─────────────────────────────────────────────────────────────

def _hex_rgb(h):
    """'#rgb', '#rgba', '#rrggbb' or '#rrggbbaa' -> ((r, g, b), alpha)."""
    h = h.lstrip("#")
    if len(h) in (3, 4):
        h = "".join(ch * 2 for ch in h)
    rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    return rgb, (int(h[6:8], 16) / 255 if len(h) == 8 else 1.0)


def _num(v, scale=1.0):
    v = v.strip()
    if v.endswith("%"):
        return float(v[:-1]) / 100 * scale
    return float(v)


def _hsl_rgb(h, s, light):
    h = (h % 360) / 360.0
    if s == 0:
        v = round(light * 255)
        return (v, v, v)
    q = light * (1 + s) if light < 0.5 else light + s - light * s
    p = 2 * light - q

    def hue(t):
        t %= 1
        if t < 1 / 6:
            return p + (q - p) * 6 * t
        if t < 1 / 2:
            return q
        if t < 2 / 3:
            return p + (q - p) * (2 / 3 - t) * 6
        return p
    return tuple(round(hue(h + d) * 255) for d in (1 / 3, 0, -1 / 3))


#: A colour literal: hex in its four lengths, rgb()/rgba() and hsl()/hsla()
#: in both syntaxes (commas, or spaces and a slash).
COLOUR_LITERAL = re.compile(r"(?<![\w&])#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{4}|[0-9a-f]{3})(?![0-9a-z])|"
                            r"\b(?:rgba?|hsla?)\(\s*[^()]*\)", re.I)


def literal_rgb(text):
    """((r, g, b), alpha) of one colour literal COLOUR_LITERAL found, or
    None (a var() inside, a keyword, a percentage form it cannot read)."""
    t = text.strip()
    if t.startswith("#"):
        return _hex_rgb(t)
    m = re.match(r"(rgba?|hsla?)\(\s*(.*?)\s*\)$", t, re.I | re.S)
    if not m or "var(" in m.group(2):
        return None
    parts = [p for p in re.split(r"[\s,/]+", m.group(2)) if p]
    if len(parts) < 3:
        return None
    try:
        alpha = _num(parts[3]) if len(parts) > 3 else 1.0
        if m.group(1).lower().startswith("rgb"):
            rgb = tuple(_num(p, 255) for p in parts[:3])
        else:
            hue = float(re.sub(r"deg$", "", parts[0]))
            rgb = _hsl_rgb(hue, _num(parts[1]), _num(parts[2]))
    except ValueError:
        return None
    return rgb, alpha


def _near(a, b, tol=3):
    return sum((x - y) ** 2 for x, y in zip(a, b)) <= tol * tol


EYE_RGB = (0, 232, 104)
#: The old palette's literals (#40FF90, #0A5028, #030806, #3A6850, #E83030,
#: #D8B020, #FFB000, #FF5E5E).
OLD_RGBS = ((64, 255, 144), (10, 80, 40), (3, 8, 6), (58, 104, 80), (232, 48, 48), (216, 176, 32),
            (255, 176, 0), (255, 94, 94))


#: A colour literal's first three components, closed or not: a script
#: builds 'rgba(0,232,104,' + alpha + ')' from pieces.
_LITERAL_HEAD = re.compile(r"(?<![\w&])#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{4}|[0-9a-f]{3})(?![0-9a-z])|"
                           r"\b(rgba?|hsla?)\(\s*(-?[\d.]+(?:%|deg)?)\s*[,\s]\s*(-?[\d.]+%?)\s*[,\s]\s*(-?[\d.]+%?)",
                           re.I)


def _literals(text):
    """((r, g, b), tolerance) of every colour literal in a text, closed or
    not: a hex or an rgb() is the colour exactly; an hsl() is read to the
    nearest unit, so a spelling of the same colour is within 3."""
    for m in _LITERAL_HEAD.finditer(text):
        if m.group(0).startswith("#"):
            yield _hex_rgb(m.group(0))[0], 0
            continue
        try:
            if m.group(1).lower().startswith("rgb"):
                yield tuple(_num(m.group(i), 255) for i in (2, 3, 4)), 0.5
            else:
                yield _hsl_rgb(float(re.sub(r"deg$", "", m.group(2))), _num(m.group(3)), _num(m.group(4))), 3
        except ValueError:
            continue


def has_eye_literal(text):
    """The Eye's green written as a literal, in any of its spellings (hex
    with or without alpha, rgb(), hsl())."""
    return any(_near(rgb, EYE_RGB, tol) for rgb, tol in _literals(text))


def has_old_literal(text):
    return any(_near(rgb, old, tol) for rgb, tol in _literals(text) for old in OLD_RGBS)


OLD_TOKEN = re.compile(r"var\(\s*--accent-(?:dim|bright|glow)\s*[,)]")
#: The Eye by name: the old alias and the token itself.
ACCENT = re.compile(r"var\(\s*--(?:accent|sv-eye)\s*[,)]")
HEX = re.compile(r"(?<![\w&])#(?:[0-9a-f]{8}|[0-9a-f]{6}|[0-9a-f]{4}|[0-9a-f]{3})(?![0-9a-z])", re.I)

#: Properties that paint text, a border or an outline (accent_role).
TEXT_OR_BORDER = re.compile(r"^(color|-webkit-text-fill-color|caret-color|text-decoration(-color)?|"
                            r"border(-(top|right|bottom|left|block|inline)(-(start|end))?)?(-color)?|"
                            r"outline(-color)?|column-rule(-color)?|fill|stroke)$")
#: Where the Eye may draw text or a border (plan §3.3): focus, selection,
#: the brand, the active nav row, the empty-state mark. Read per item of a
#: selector list: the role is the item's subject's (its last compound), or
#: an ancestor that is one of the named places.
EYE_ROLE = re.compile(r":focus|:checked|\[aria-(selected|pressed|current|checked|expanded)|\.is-(active|selected|on)\b|"
                      r"\.active\b|\.selected\b|\.sv-pinned\b|::selection")
EYE_PLACE = re.compile(r"\.sidebar-brand\b|\.brand\b|empty-state|\.nav-link\.active\b")
VISUAL = re.compile(r"^(color|background(-[a-z]+)?|border(-[a-z]+)*|outline(-[a-z]+)?|font(-[a-z]+)?|"
                    r"letter-spacing|text-transform|text-shadow|box-shadow|filter|-webkit-text-fill-color|"
                    r"fill|stroke|text-decoration(-color)?|accent-color|caret-color|backdrop-filter)$")
ALLOWED_LOOPS = ("sv-heartbeat", "sv-armed-beat", "sv-eye-breath")
#: Where a gradient is the new look's own: the void (html, body), the hero
#: card's edge, the active row's spill (the measured half's GRAD_OK, the
#: same list). Read per item of a selector list, on the item's subject.
GRADIENT_OK = re.compile(r"^(html|body)(?=$|[:.\[#])|\.nav-link\.active\b|\.day-scheme-wrap\b|\.sv-panel--hero\b")
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
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [p.strip() for p in out if p.strip()]


def selector_items(selector):
    """The items of a selector list (a keyframe's selector is one item)."""
    if selector.startswith("@"):
        return [selector]
    return split_top(selector) or [selector]


def subject(item):
    """An item's subject: its last compound selector, with the compounds
    joined to it as siblings (+, ~): `input:checked + .track` is a track
    drawn by its box's state. Descendant and child combinators end it."""
    parts, depth, cur = [], 0, []
    for ch in item:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if depth == 0 and ch in " >+~":
            if cur:
                parts.append("".join(cur))
                cur = []
            if ch != " ":
                parts.append(ch)
            continue
        cur.append(ch)
    if cur:
        parts.append("".join(cur))
    # parts alternate compounds and explicit combinators; a gap between two
    # compounds is a descendant combinator.
    chain, k = [], len(parts) - 1
    while k >= 0:
        chain.insert(0, parts[k])
        if k >= 2 and parts[k - 1] in ("+", "~"):
            chain.insert(0, parts[k - 1])
            k -= 2
            continue
        break
    return " ".join(chain).strip()


def gradient_allowed(selector):
    """Every item of the list has an allowed subject (`body .card` is a
    card's gradient, not the void's)."""
    return all(GRADIENT_OK.search(subject(item)) for item in selector_items(selector))


def eye_role(selector):
    """Every item of the list draws the Eye in one of its roles: on its
    subject (focus, a checked or selected or active state), or inside one
    of the named places (the brand, the active nav row, the empty state)."""
    if not selector:
        return False
    return all(EYE_ROLE.search(subject(item)) or EYE_PLACE.search(item) for item in selector_items(selector))


def _words(text):
    """A selector or a value with its white space run together."""
    return " ".join(text.split())


def frame_light(selector, prop, value, where):
    """Whether a declaration is one of the frame's named lights
    (FRAME_LIGHT): in that sheet, that selector, that property, that
    value."""
    return where == FRAME_SHEET and (_words(selector), prop, _words(value)) in FRAME_LIGHT


def frame_ember(selector, prop, value, rule_decls, where):
    """Whether a declaration is the tower's ember (FRAME_EMBER): in the
    frame's sheet, that selector and that fill, its dose in the same rule."""
    named, fill, token, (dose_prop, dose) = FRAME_EMBER
    return (where == FRAME_SHEET and (_words(selector), prop, _words(value)) == (named, fill, token)
            and _words(dict(rule_decls).get(dose_prop, "")) == dose)


#: Colour functions whose lightness is read directly (oklch, oklab, lab,
#: lch: their first argument), and color(srgb r g b).
_LIGHTNESS_FN = re.compile(r"^(oklch|oklab|lab|lch)\(\s*([\d.]+)(%?)", re.I)


def _coloured(colour):
    """Whether a shadow's colour lights: a colour with some light in it at
    some opacity, a token of the palette's hues, or currentColor."""
    c = colour.strip()
    if not c or DARK.match(c):
        return False
    if re.match(r"currentcolor$", c, re.I):
        return True
    if COLOUR_LITERAL.fullmatch(c):
        got = literal_rgb(c)
        if got is None:
            return True             # a form it cannot read: assume it lights
        rgb, a = got
        return a > 0.04 and max(rgb) > 40
    m = _LIGHTNESS_FN.match(c)
    if m:
        light = float(m.group(2)) / (100 if m.group(3) or m.group(1).lower() in ("lab", "lch") else 1)
        alpha = re.search(r"/\s*([\d.]+)(%?)\s*\)$", c)
        a = 1.0 if not alpha else float(alpha.group(1)) / (100 if alpha.group(2) else 1)
        return a > 0.04 and light > 0.2
    m = re.match(r"color\(\s*srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*/\s*([\d.]+)(%?))?", c, re.I)
    if m:
        a = 1.0 if m.group(4) is None else float(m.group(4)) / (100 if m.group(5) else 1)
        return a > 0.04 and max(float(m.group(i)) for i in (1, 2, 3)) > 40 / 255
    m = re.match(r"var\(\s*--([\w-]+)\s*\)$", c)
    if m:
        return not re.match(r"(sv-)?(bg|line|shadow)", m.group(1))
    if c.startswith("color-mix("):
        return bool(re.search(r"--(sv-)?(eye|accent|up|down|real|demo|warn|ai|cat|gold|red|green|blue|purple|glow)", c))
    return bool(re.match(r"[a-z]+$", c, re.I))   # a named colour (white, gold…)


#: A shadow layer's colour: any colour function, a token, a literal, a name.
_SHADOW_COLOUR = re.compile(r"(?:rgba?|hsla?|oklch|oklab|lab|lch|hwb|color)\((?:[^()]|\([^)]*\))*\)|"
                            r"color-mix\((?:[^()]|\([^)]*\))*\)|var\(--[\w-]+\)|#[0-9a-f]{3,8}\b|currentcolor|"
                            r"\b[a-z]+\b\s*$", re.I)


def glows(prop, value):
    """The coloured, blurred shadows of a declaration."""
    out = []
    if prop in ("box-shadow", "text-shadow", "-webkit-box-shadow"):
        for layer in split_top(value):
            colour = _SHADOW_COLOUR.search(layer)
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
            colour = _SHADOW_COLOUR.search(inner)
            rest = inner.replace(colour.group(0), " ") if colour else inner
            nums = [float(v) for v in re.findall(r"(-?\d*\.?\d+)(?:px|em|rem)?(?![\w%(.])", rest)]
            if colour and len(nums) >= 3 and nums[2] > 0 and _coloured(colour.group(0)):
                out.append(m.group(0))
    return out


#: Sizes in px: the absolute units and rem (the root's 16 px). em and %
#: are their parent's, which the source does not know: they are read
#: against a 22 px parent, the largest text the pages size that way, so
#: only a size under 11 px under any such parent is counted (.4em is,
#: setups.html's 60% inside a KPI figure is not); the measured half reads
#: every text's computed size.
_UNIT_PX = {"px": 1.0, "pt": 4 / 3, "pc": 16.0, "in": 96.0, "cm": 96 / 2.54, "mm": 96 / 25.4, "q": 96 / 101.6,
            "rem": 16.0, "em": 22.0, "%": 0.22}
#: The keyword sizes (CSS Fonts 4 at a 16 px medium).
KEYWORD_PX = {"xx-small": 9.0, "x-small": 10.0, "xxx-small": 9.0, "small": 13.0}
_LENGTH = re.compile(r"(-?\d*\.?\d+)(px|pt|pc|in|cm|mm|q|rem|em|%)(?![\w-])", re.I)


def _length_px(v):
    m = re.fullmatch(r"\s*(-?\d*\.?\d+)(px|pt|pc|in|cm|mm|q|rem|em|%)\s*", v, re.I)
    return float(m.group(1)) * _UNIT_PX[m.group(2).lower()] if m else None


def _calc_px(expr):
    """A calc() of lengths and numbers, in px, or None (a var(), a
    viewport unit, anything it cannot read)."""
    if re.search(r"var\(|v[whib]|vmin|vmax|cq|[a-df-z_]\(", expr, re.I):
        return None
    py = _LENGTH.sub(lambda m: "(%r)" % (float(m.group(1)) * _UNIT_PX[m.group(2).lower()]), expr)
    if not re.fullmatch(r"[\d.\s()+*/-]+", py) or "**" in py:
        return None
    try:
        return float(eval(py, {"__builtins__": {}}, {}))      # digits and + - * / ( ) only
    except Exception:
        return None


def font_px(value):
    """A font-size in px, or None: px, pt, rem, em, % (against 16 px), the
    keyword sizes, calc() of those, and clamp()/min()/max() at the smallest
    size they allow."""
    v = value.replace("!important", "").strip().lower()
    if v in KEYWORD_PX:
        return KEYWORD_PX[v]
    px = _length_px(v)
    if px is not None:
        return px
    m = re.fullmatch(r"(calc|clamp|min|max)\((.*)\)", v, re.S)
    if m:
        if m.group(1) == "calc":
            return _calc_px(m.group(2))
        args = [_arg_px(a) for a in split_top(m.group(2))]
        known = [a for a in args if a is not None]
        if m.group(1) == "clamp" and len(args) == 3:
            return args[0]          # the floor: the size it can render at
        if m.group(1) == "min" and known:
            return min(known)
        if m.group(1) == "max" and known and len(known) == len(args):
            return max(known)
    return None


def _arg_px(a):
    px = font_px(a)
    return px if px is not None else _calc_px(a)


def font_shorthand_px(value):
    m = re.search(r"(?:^|\s)(\d*\.?\d+)(px|pt|rem|em|%)(?:\s*/\s*[\d.]+[a-z%]*)?\s+[\"'a-zA-Z(]", value, re.I)
    if m:
        return float(m.group(1)) * _UNIT_PX[m.group(2).lower()]
    m = re.search(r"(?:^|\s)(xx-small|x-small|xxx-small)(?:\s*/\s*[\d.]+[a-z%]*)?\s+[\"'a-zA-Z(]", value, re.I)
    if m:
        return KEYWORD_PX[m.group(1).lower()]
    return None


def first_face(value):
    return split_top(value)[0].strip().strip("\"'").lower() if value.strip() else ""


#: An iteration count this high is a loop by another name.
ENDLESS = 100
#: The animation keywords and values that are not a name.
_ANIM_WORDS = {"infinite", "linear", "ease", "ease-in", "ease-out", "ease-in-out", "step-start", "step-end",
               "normal", "reverse", "alternate", "alternate-reverse", "forwards", "backwards", "both", "none",
               "running", "paused", "initial", "inherit", "unset", "revert", "auto"}


def animation_layers(prop, value, rule_decls):
    """[(name, endless)] of each layer of an animation (the shorthand's
    comma layers, or animation-iteration-count read against the rule's
    animation-name, cycled as CSS does)."""
    if prop == "animation":
        out = []
        for layer in split_top(value):
            words = [w for w in re.split(r"\s+", re.sub(r"[a-z-]+\([^)]*\)", " ", layer, flags=re.I)) if w]
            names = [w.strip("\"'") for w in words
                     if w.lower() not in _ANIM_WORDS and not re.fullmatch(r"-?[\d.]+m?s|-?[\d.]+", w, re.I)]
            counts = [w for w in words if re.fullmatch(r"[\d.]+", w)]
            endless = bool(re.search(r"\binfinite\b", layer)) or any(float(c) >= ENDLESS for c in counts)
            out.append((names[0] if names else "", endless))
        return out
    if prop == "animation-iteration-count":
        names = split_top(dict(rule_decls).get("animation-name", "")) or [""]
        return [(names[k % len(names)].strip("\"'"),
                 c.strip() == "infinite" or (re.fullmatch(r"[\d.]+", c.strip()) is not None and float(c) >= ENDLESS))
                for k, c in enumerate(split_top(value))]
    return []



# ── one declaration ─────────────────────────────────────────────────────

def declaration_markers(prop, raw, selector="", rule_decls=(), where=""):
    """[(marker, text)] for one CSS declaration. `selector` is the rule's
    (empty for a style attribute); `rule_decls` the rule's other
    (property, value) pairs; `where` the file."""
    prop = prop.strip().lower()
    value = strip_var_fallbacks(raw.strip())
    out = []
    if where == KIT_PAGE and selector and all(SPECIMEN_CLASS.search(i) for i in selector_items(selector)):
        return out          # a specimen of the kit's page
    magic = (where == KIT_SHEET and "data-sv-ambience" in selector) or frame_light(selector, prop, value, where)
    if not magic:
        if has_eye_literal(value):
            out.append(("eye_literal", value))
        if has_old_literal(value):
            out.append(("old_literal", value))
    if OLD_TOKEN.search(value):
        out.append(("old_token", value))
    if (TEXT_OR_BORDER.match(prop) and ACCENT.search(value) and not eye_role(selector)
            and not frame_ember(selector, prop, value, rule_decls, where)):
        out.append(("accent_role", "%s: %s" % (prop, value)))
    if prop == "font-size":
        px = font_px(value)
        if px is None:
            # A size the rule (or the sheet) names itself: --tiny: 9px; font-size: var(--tiny).
            m = re.fullmatch(r"\s*var\(\s*(--[\w-]+)\s*\)\s*", value)
            own = dict(rule_decls).get(m.group(1)) if m else None
            if own is None and m:
                own = _SHEET_VARS.get(where, {}).get(m.group(1))
            px = font_px(own) if own else None
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
    if prop in ("animation", "animation-iteration-count"):
        # Each endless layer by its own name, exactly (sv-heartbeat-neon is
        # not the heartbeat; "sv-heartbeat 2s infinite, neon 1s infinite"
        # holds one loop that is not).
        if any(endless and name not in ALLOWED_LOOPS for name, endless in animation_layers(prop, value, rule_decls)):
            out.append(("infinite", "%s: %s" % (prop, value)))
    if prop in ("backdrop-filter", "-webkit-backdrop-filter") and value.lower() not in ("none", "initial", "unset"):
        out.append(("glass", "%s: %s" % (prop, value)))
    if (prop in ("background", "background-image", "border-image", "border-image-source")
            and re.search(r"(linear|radial|conic)-gradient\(|data:image/svg\+xml[^)]*(?:<|%3C)(?:linear|radial)Gradient",
                          value, re.I)
            and not gradient_allowed(selector) and not magic):
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


#: The kit's own marks beside a word: a side's ▲ ▼, the stop's ■ and a
#: menu's chosen ✓.
SIDE_MARKS = set("▲▼△▽▴▾■✓")


def glyph_beside_words(text):
    """A glyph icon written beside words ("⚙ Settings", "View ▸"): the
    glyph, or None. A side's mark, the stop's ■ and a menu's ✓ are the
    kit's."""
    words = text.split()
    if len(words) < 2 or not any(re.search(r"[^\W\d_]{2,}", w) for w in words):
        return None
    for w in (words[0], words[-1]):
        if w not in SIDE_MARKS and is_glyph_icon(w):
            return w
    return None


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


#: The custom properties each sheet (or template's <style>) defines, by
#: file: a size named there is read through its name.
_SHEET_VARS = {}


def css_hits(text, rel, first_line=1):
    hits = []
    tokens = rel == TOKENS_SHEET
    rules = css_rules(text, first_line)
    own = _SHEET_VARS.setdefault(rel, {})
    for _sel, _line, decls in rules:
        for prop, value, _l in decls:
            if prop.startswith("--"):
                own[prop] = value.strip()
    for selector, _line, decls in rules:
        pairs = tuple((p.lower(), v) for p, v, _l in decls)
        for prop, value, line in decls:
            if tokens and prop.startswith("--"):
                continue        # the palette's own definitions (the magic's light among them)
            for marker, detail in declaration_markers(prop, value, selector, pairs, rel):
                hits.append(Hit(rel, line, marker, "%s { %s }" % (selector[:80], detail[:140])))
    # A face a sheet loads itself (@import of Google's font sheet).
    clean = _blank_comments(text)
    for m in re.finditer(r"@import\s+(?:url\()?\s*['\"]?([^'\")\s;]+)", clean):
        hits += font_link_hits(m.group(1), rel, first_line + clean.count("\n", 0, m.start()))
    return hits


def font_link_hits(href, rel, line):
    """A Google Fonts link (a <link> or an @import) that loads Share Tech
    Mono, Orbitron with its digits, or Rajdhani in another weight than 600."""
    hits = []
    if "fonts.googleapis.com" not in href:
        return hits
    href = href.replace("&amp;", "&")
    if re.search(r"Share\+Tech\+Mono|Share%20Tech%20Mono", href):
        hits.append(Hit(rel, line, "share_tech", href[:140]))
    if re.search(r"family=Orbitron", href) and "text=" not in href:
        hits.append(Hit(rel, line, "old_face_load", href[:140]))
    for wghts in re.findall(r"family=Rajdhani(?::wght@([\d;.]+))?", href):
        if wghts != "600":
            hits.append(Hit(rel, line, "old_face_load", href[:140]))
    return hits


#: CSS's named colours (but white, black and the keywords): in an email or
#: a painter's style, a colour of no token.
NAMED_COLOURS = set("""aliceblue antiquewhite aqua aquamarine azure beige bisque blanchedalmond blue blueviolet brown
burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod
darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon
darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey
dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey
honeydew hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral
lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue
lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine
mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise
mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered
orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple
rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue
slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato turquoise violet wheat whitesmoke
yellow yellowgreen""".split())


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
        if PALETTE_FILES.match(rel) and VISUAL.match(prop):
            for word in re.findall(r"(?<![\w#-])[a-z]+(?![\w-])", re.sub(r"var\([^)]*\)", " ", value.lower())):
                if word in NAMED_COLOURS:
                    hits.append(Hit(rel, line, "off_token_hex", 'style="%s" (%s)' % (style[:110], word)))
    if visual:
        hits.append(Hit(rel, line, "inline_visual", 'style="%s" (%s)' % (style[:110], ", ".join(visual[:4]))))
    return hits


# ── scripts ─────────────────────────────────────────────────────────────

#: The visual style properties a script may not write directly (camelCase
#: and their CSS names): colours, surfaces, borders, faces, light, paint.
_JS_VISUAL = (r"color|background(?:Color|Image)?|border(?:Top|Right|Bottom|Left)?(?:Color)?|borderImage|"
              r"outline(?:Color)?|fontFamily|fontSize|fontWeight|boxShadow|textShadow|filter|cssText|"
              r"webkitTextFillColor|fill|stroke|caretColor|accentColor|textDecorationColor")
_CSS_VISUAL = (r"color|background(?:-color|-image)?|border(?:-[a-z]+)*|outline(?:-color)?|font-[a-z]+|box-shadow|"
               r"text-shadow|filter|fill|stroke|caret-color|accent-color|-webkit-text-fill-color")
JS_STYLE = re.compile(r"\.style\.(?:%s)\s*(\+?=)(?!=)|"                       # el.style.color = ...
                      r"\.style\s*\[\s*['\"`](?:%s|%s)['\"`]\s*\]\s*(\+?=)(?!=)|"  # el.style['color'] = ...
                      r"\.style\.setProperty\(\s*['\"`](?:%s)['\"`]|"           # setProperty('color', ...)
                      r"\.setAttribute\(\s*['\"`]style['\"`]|"                  # setAttribute('style', ...)
                      r"Object\.assign\(\s*[\w$.\[\]'\"]*\.style\s*,"           # Object.assign(el.style, {...})
                      % (_JS_VISUAL, _JS_VISUAL, _CSS_VISUAL, _CSS_VISUAL))
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
        if has_eye_literal(line_text):
            hits.append(Hit(rel, line, "eye_literal", line_text.strip()[:140]))
        if has_old_literal(line_text):
            hits.append(Hit(rel, line, "old_literal", line_text.strip()[:140]))
        for _m in OLD_TOKEN.finditer(line_text):
            hits.append(Hit(rel, line, "old_token", line_text.strip()[:140]))
        if re.search(r"share\s*tech\s*mono", line_text, re.I):
            hits.append(Hit(rel, line, "share_tech", line_text.strip()[:140]))
        for m in re.finditer(r"font-size\s*:\s*([^;'\"`]+)|fontSize\s*=\s*(['\"`])(.*?)\2|"
                             r"\bfont\s*=\s*(['\"`])(.*?)\4", line_text):
            if m.group(1) or m.group(3):
                px = font_px(m.group(1) or m.group(3))
            else:
                px = font_shorthand_px(m.group(5) or "")
            if px is not None and px < 11:
                hits.append(Hit(rel, line, "sub11", line_text.strip()[:140]))
        for m in JS_STYLE.finditer(line_text):
            hits.append(Hit(rel, line, "js_style", line_text.strip()[:140]))
        # The old side badge put on by a script: unless the same line speaks
        # of a side, what it wears cannot be a side word.
        if (re.search(r"(?<![\w-])badge-(bullish|bearish)(?![\w-])", line_text)
                and not re.search(r"\b(LONG|SHORT|BUY|SELL|BULL|BEAR|direction|side|dir|bias)\b", line_text, re.I)
                and not re.search(r"^\s*[.#\w\s,>:-]*\{", line_text)):
            hits.append(Hit(rel, line, "badge_side", line_text.strip()[:140]))
        for m in re.finditer(r"(linear|radial|conic)-gradient\(", line_text):
            hits.append(Hit(rel, line, "gradient", line_text.strip()[:140]))
        if re.search(r"backdrop-filter\s*:\s*(?!none)|[bB]ackdropFilter\s*=(?!=)|"
                     r"setProperty\(\s*['\"`](?:-webkit-)?backdrop-filter['\"`]", line_text):
            hits.append(Hit(rel, line, "glass", line_text.strip()[:140]))
        for m in re.finditer(r"(box-shadow|text-shadow)\s*:\s*([^;'\"`]+)", line_text):
            for g in glows(m.group(1), strip_var_fallbacks(m.group(2))):
                hits.append(Hit(rel, line, "glow", line_text.strip()[:140]))
        for m in re.finditer(r"(?<![\w-])(?:color|fill|stroke|border(?:-[a-z]+)*|outline(?:-color)?)\s*:\s*"
                             r"var\(--(?:accent|sv-eye)\)", line_text):
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

    def _specimen(self, cls=""):
        return self.rel == KIT_PAGE and (bool(SPECIMEN_CLASS.search(cls)) or any(h["specimen"] for h in self.stack))

    def handle_starttag(self, tag, attrs):
        a = dict((k.lower(), v or "") for k, v in attrs)
        line = self._line()
        specimen = self._specimen(a.get("class", ""))
        # Every style attribute (a template's {% if %} can print one of two).
        for k, v in attrs:
            if k.lower() == "style" and (v or "").strip() and not specimen:
                self.hits += style_attr_hits(v, self.rel, line)
        for name in ("fill", "stroke", "stop-color", "color", "flood-color", "lighting-color", "bgcolor"):
            v = a.get(name, "")
            if v and has_eye_literal(v):
                self.hits.append(Hit(self.rel, line, "eye_literal", '%s="%s"' % (name, v)))
            if v and has_old_literal(v):
                self.hits.append(Hit(self.rel, line, "old_literal", '%s="%s"' % (name, v)))
            if v and OLD_TOKEN.search(v):
                self.hits.append(Hit(self.rel, line, "old_token", '%s="%s"' % (name, v)))
            # The Eye by name as an SVG's paint, outside the brand, the active
            # row and the empty state (its roles as a mark).
            if (v and name in ("fill", "stroke") and ACCENT.search(v)
                    and not any(EYE_PLACE.search("." + ".".join(h["cls"].split())) for h in self.stack)
                    and not EYE_PLACE.search("." + ".".join(a.get("class", "").split()))):
                self.hits.append(Hit(self.rel, line, "accent_role", '%s="%s"' % (name, v)))
            # An SVG painted in a colour of no token (the sheet's tokens are
            # what a template may paint with; a literal is a colour off them).
            if v and name in ("fill", "stroke", "stop-color", "flood-color", "lighting-color", "bgcolor"):
                for m in COLOUR_LITERAL.finditer(v):
                    got = literal_rgb(m.group(0))
                    if got and got[1] > 0 and not is_token_rgb(got[0]):
                        self.hits.append(Hit(self.rel, line, "off_token_hex", '%s="%s"' % (name, v)))
                        break
        fs = a.get("font-size", "")
        m = re.fullmatch(r"\s*(\d*\.?\d+)(px)?\s*", fs)
        if m and float(m.group(1)) < 11:
            self.hits.append(Hit(self.rel, line, "sub11", 'font-size="%s"' % fs))
        if a.get("repeatcount", "").strip() == "indefinite":
            self.hits.append(Hit(self.rel, line, "infinite", '<%s repeatCount="indefinite">' % tag))
        if tag == "link":
            self.hits += font_link_hits(a.get("href", ""), self.rel, line)
        cls = a.get("class", "")
        self.stack.append({"tag": tag, "cls": cls, "line": line, "text": [], "specimen": specimen,
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
        if not text.strip():
            return
        alone = is_glyph_icon(text)
        if not (alone or glyph_beside_words(text)) or self._specimen():
            return
        if alone and text.strip() == "■" and any(re.search(r"(?<![\w-])(btn-stop|sv-stop-mark)(?![\w-])", h["cls"])
                                                for h in self.stack):
            return          # §10's stop variant wears ■ (the kit's mark)
        # Alone, a glyph is an icon in a button, a link, a disclosure, the
        # nav or anything dressed as one; beside words, in a button (a text
        # link's trailing arrow is typography).
        hosts = ("button", "a", "summary", "nav") if alone else ("button", "summary")
        if any(h["tag"] in hosts or ICON_HOST.search(h["cls"]) for h in self.stack):
            self.hits.append(Hit(self.rel, self._line(), "glyph_icon",
                                 "<%s class=%r>%s" % (self.stack[-1]["tag"], self.stack[-1]["cls"][:50], text.strip()[:60])))


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
    # And its {% tags %} blanked (lines and columns kept): a tag right
    # before an attribute ({% if x %}style="...") hid the attribute from the
    # parser (ai_journal.html:110, performance.html:145, risk_depth.html:31).
    markup = re.sub(r"{%.*?%}", lambda m: re.sub(r"[^\n]", " ", m.group(0)), markup, flags=re.S)
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
    """Every hex value the tokens sheet defines, dark and light (#rgb also
    spelled #rrggbb): what an email or the PDF may inline (email clients
    ignore CSS variables)."""
    global _TOKEN_HEX
    if _TOKEN_HEX is None:
        text = (ROOT / TOKENS_SHEET).read_text(encoding="utf-8")
        found = {h.lower() for h in re.findall(r"--[\w-]+\s*:\s*(#[0-9a-fA-F]{3,6})\b", text)}
        found |= {"#ffffff", "#fff", "#000000", "#000"}
        found |= {"#" + "".join(ch * 2 for ch in h[1:]) for h in found if len(h) == 4}
        _TOKEN_HEX = found
    return _TOKEN_HEX


def is_token_rgb(rgb):
    """Whether (r, g, b) is the value of a token (dark or light), white or
    black."""
    return "#%02x%02x%02x" % tuple(int(round(c)) for c in rgb) in token_hexes()


#: A colour a painter writes without a hex: rgb(r, g, b) and ReportLab's
#: colors.Color(r, g, b) on 0..1.
_PAINTER_RGB = re.compile(r"\brgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})|"
                          r"\bColor\(\s*([01]?\.?\d*)\s*,\s*([01]?\.?\d*)\s*,\s*([01]?\.?\d*)\s*[,)]")


def palette_hits(text, rel, first_line=1):
    """One hit per colour off the tokens: a hex (any length), an rgb() or
    a ReportLab Color()."""
    hits = []
    for k, line_text in enumerate(text.split("\n")):
        for m in HEX.finditer(line_text):
            if not is_token_rgb(_hex_rgb(m.group(0))[0]):
                hits.append(Hit(rel, first_line + k, "off_token_hex", line_text.strip()[:140]))
        for m in _PAINTER_RGB.finditer(line_text):
            try:
                if m.group(1) is not None:
                    rgb = tuple(int(m.group(i)) for i in (1, 2, 3))
                else:
                    rgb = tuple(float(m.group(i) or 0) * 255 for i in (4, 5, 6))
            except ValueError:
                continue
            if not is_token_rgb(rgb):
                hits.append(Hit(rel, first_line + k, "off_token_hex", line_text.strip()[:140]))
    return hits


def _parse(text):
    import ast
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError):
        return None


def _string_nodes(text, tree=None):
    """(line, source) of every string literal of a Python module, as
    written (an f-string whole, with its {fields}), read through the AST so
    every Python counts alike: from 3.12, tokenize splits an f-string into
    FSTRING_START, _MIDDLE and _END tokens, which a census of STRING tokens
    no longer saw (sauron_tags.py:410 on CI's 3.12, the review of B0). A
    string inside an f-string's field is read with the f-string."""
    import ast
    tree = tree or _parse(text)
    if tree is None:
        return []
    inside = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            for sub in ast.walk(node):
                if sub is not node:
                    inside.add(id(sub))
    out = []
    for node in ast.walk(tree):
        if id(node) in inside:
            continue
        if isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes))):
            seg = ast.get_source_segment(text, node)
            if seg:
                out.append((node.lineno, seg))
    return sorted(out)


def _colour_calls(text, rel, tree):
    """A painter's colour built from numbers (ReportLab's Color(r, g, b) on
    0..1, or on 0..255): off the tokens unless a token's value."""
    import ast
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", "")
        if name != "Color" or len(node.args) < 3:
            continue
        nums = [a.value for a in node.args[:3] if isinstance(a, ast.Constant) and isinstance(a.value, (int, float))]
        if len(nums) < 3:
            continue
        scale = 255 if all(0 <= v <= 1 for v in nums) else 1
        if not is_token_rgb(tuple(v * scale for v in nums)):
            hits.append(Hit(rel, node.lineno, "off_token_hex", (ast.get_source_segment(text, node) or name)[:140]))
    return hits


def python_hits(text, rel):
    """In the Python that emits markup or a PDF: the strings only (never a
    comment), read for the same colour and size markers, and, being a
    painter, for a colour that is not a token's value."""
    hits = []
    tree = _parse(text)
    if tree is None:
        return hits
    if PALETTE_FILES.match(rel):
        hits += _colour_calls(text, rel, tree)
    for line, body in _string_nodes(text, tree):
        if re.match(r'^[rbuf]*("""|\'\'\')', body, re.I) and not re.search(r"[<{;:]\s*(color|background|style)", body):
            continue        # a docstring or a long note, not markup
        for k, part in enumerate(body.split("\n")):
            ln = line + k
            if has_eye_literal(part):
                hits.append(Hit(rel, ln, "eye_literal", part.strip()[:140]))
            if has_old_literal(part):
                hits.append(Hit(rel, ln, "old_literal", part.strip()[:140]))
            for m in re.finditer(r"font-size\s*:\s*([^;'\"]+)", part):
                px = font_px(m.group(1))
                if px is not None and px < 11:
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

