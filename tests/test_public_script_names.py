"""The two public pages' scripts are written in whole words.

The Book (templates/landing/the_book.html) and the Wall
(templates/landing/the_wall.html) are read by anyone who opens the page
source. Their inline scripts once leaned on two- and three-letter names
for elements, events, offsets and callbacks; each one cost the reader a
guess. This holds every declared name in those scripts (var, let and
const names, function names, parameters, catch parameters) and every
object-literal key to one rule: a name of two or three characters must be
an ordinary English word from the short list below. Single letters (loop
counters, coordinates) stay. The comments beside the code do not bring
the common shorthand back either.

The scan tokenizes the JavaScript itself, so a two-letter run inside a
string ("px" in a transform) is never mistaken for a name.

Run with:  python manage.py test tests.test_public_script_names
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

REPO = Path(settings.BASE_DIR)
PAGES = (
    REPO / "templates" / "landing" / "the_book.html",
    REPO / "templates" / "landing" / "the_wall.html",
)

# Short names in public scripts are spelled out so a reader never has to guess them.
ENGLISH_SHORT_NAMES = frozenset({
    "aim", "all", "at", "bar", "box", "dot", "fit", "go", "id", "low",
    "now", "on", "pen", "row", "sky", "top",
})
# Keys a payload or a server reply really carries: a status flag, a tag
# name and a currency code.
DATA_KEYS = frozenset({"ok", "tag", "usd"})
# Common code shorthand that a comment should spell out as well.
COMMENT_SHORTHAND = frozenset({
    "btn", "cb", "cfg", "ctx", "doc", "dx", "dy", "el", "elm", "err", "ev",
    "evt", "exp", "fd", "fn", "hx", "idx", "img", "inp", "io", "msg", "mx",
    "nb", "obj", "op", "opt", "pw", "px", "py", "req", "res", "str", "t0",
    "ti", "tmp", "val", "vh", "vw",
})
COMMENT_WORD_RE = re.compile(r"(?<![\w.$-])[A-Za-z_$][\w$]*(?![\w$-])")

SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
DJANGO_RE = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
IDENT_START = re.compile(r"[A-Za-z_$]")
IDENT_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
# After one of these, a slash opens a regular expression, not a division.
REGEX_AFTER = set("(,=:[!&|?{};+-*%<>~^") | {"return", "typeof", "case", ""}


def tokens(source, comments=None):
    """The script as a list of identifier and punctuation tokens.

    Strings, comments and regular-expression literals are dropped whole;
    when a list is given as comments, each comment's text is added to it."""
    out = []
    i, n = 0, len(source)
    while i < n:
        ch = source[i]
        if ch.isspace():
            i += 1
        elif source.startswith("//", i):
            end = source.find("\n", i)
            end = n if end < 0 else end
            if comments is not None:
                comments.append(source[i + 2:end])
            i = end
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            end = n if end < 0 else end
            if comments is not None:
                comments.append(source[i + 2:end])
            i = min(n, end + 2)
        elif ch in "'\"`":
            i += 1
            while i < n and source[i] != ch:
                i += 2 if source[i] == "\\" else 1
            i += 1
        elif ch == "/" and (out[-1] if out else "") in REGEX_AFTER:
            i += 1
            in_class = False
            while i < n:
                c = source[i]
                if c == "\\":
                    i += 2
                    continue
                if c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    break
                i += 1
            i += 1
            while i < n and source[i].isalpha():
                i += 1
            out.append("/regex/")
        elif IDENT_START.match(ch):
            word = IDENT_RE.match(source, i).group(0)
            out.append(word)
            i += len(word)
        elif ch.isdigit():
            match = re.compile(r"[0-9.]+(?:[eE][-+]?\d+)?").match(source, i)
            out.append("0")
            i += len(match.group(0))
        else:
            if source.startswith("=>", i):
                out.append("=>")
                i += 2
            else:
                out.append(ch)
                i += 1
    return out


def declared_names(source):
    """Every name the script declares: var/let/const, function, parameter, catch."""
    toks = tokens(source)
    names = []

    def params_from(start):
        # toks[start] is "(": the names right after "(" or a top-level ",".
        depth, j = 0, start
        while j < len(toks):
            tok = toks[j]
            if tok in "([{":
                depth += 1
            elif tok in ")]}":
                depth -= 1
                if depth == 0:
                    return j
            elif depth == 1 and toks[j - 1] in ("(", ",") and IDENT_RE.fullmatch(tok):
                names.append(tok)
            j += 1
        return j

    for k, tok in enumerate(toks):
        if tok in ("var", "let", "const"):
            depth, j, expect = 0, k + 1, True
            while j < len(toks):
                t = toks[j]
                if expect and depth == 0 and IDENT_RE.fullmatch(t):
                    names.append(t)
                    expect = False
                elif t in "([{":
                    depth += 1
                elif t in ")]}":
                    depth -= 1
                    if depth < 0:
                        break
                elif depth == 0 and t == ",":
                    expect = True
                elif depth == 0 and t == ";":
                    break
                j += 1
        elif tok == "function":
            j = k + 1
            if j < len(toks) and IDENT_RE.fullmatch(toks[j]):
                names.append(toks[j])
                j += 1
            if j < len(toks) and toks[j] == "(":
                params_from(j)
        elif tok == "catch" and k + 1 < len(toks) and toks[k + 1] == "(":
            params_from(k + 1)
        elif tok == "=>":
            if toks[k - 1] == ")":
                depth, j = 0, k - 1
                while j > 0:
                    if toks[j] == ")":
                        depth += 1
                    elif toks[j] == "(":
                        depth -= 1
                        if depth == 0:
                            break
                    j -= 1
                params_from(j)
            elif IDENT_RE.fullmatch(toks[k - 1]):
                names.append(toks[k - 1])
    return names


def object_keys(source):
    """Every key written in an object literal: a name after "{" or "," and before ":"."""
    toks = tokens(source)
    return [toks[k] for k in range(1, len(toks) - 1)
            if toks[k - 1] in ("{", ",") and toks[k + 1] == ":" and IDENT_RE.fullmatch(toks[k])]


def comment_words(source):
    """Every word in the script's // and /* */ comments."""
    comments = []
    tokens(source, comments)
    return [word for text in comments for word in COMMENT_WORD_RE.findall(text)]


def inline_scripts(path):
    text = HTML_COMMENT_RE.sub("", path.read_text(encoding="utf-8"))
    # A template value stands where a number will be printed.
    return [DJANGO_RE.sub("0", block) for block in SCRIPT_RE.findall(text)]


class PublicScriptNameTests(SimpleTestCase):
    def test_the_scanner_reads_declarations(self):
        """A scan that finds nothing proves nothing: it must see each kind."""
        found = declared_names(
            "var alpha = 1, beta = f(x, y); let gamma; const delta = 2;\n"
            "function epsilon(zeta, eta) { try {} catch (theta) {} }\n"
            "var s = 'var hidden = 1'; // var gone\n"
            "var r = /\\d{3}/g; [1].map((iota, kappa) => iota); lambda => 1;")
        self.assertEqual(found, ["alpha", "beta", "gamma", "delta", "epsilon",
                                 "zeta", "eta", "theta", "s", "r",
                                 "iota", "kappa", "lambda"])

    def test_every_page_has_scripts_to_read(self):
        for page in PAGES:
            scripts = inline_scripts(page)
            self.assertGreaterEqual(len(scripts), 2, page.name)
            self.assertGreater(sum(len(declared_names(s)) for s in scripts), 50,
                               page.name)

    def test_short_declared_names_are_english_words(self):
        for page in PAGES:
            short = sorted({
                name
                for script in inline_scripts(page)
                for name in declared_names(script)
                if 2 <= len(name) <= 3 and name not in ENGLISH_SHORT_NAMES
            })
            with self.subTest(page=page.name):
                self.assertEqual(short, [], f"{page.name} declares short names "
                                 f"a reader has to guess: {', '.join(short)}")

    def test_the_scanner_reads_keys_and_comments(self):
        source = ("var a = { alpha: 1, beta: { gamma: 2 } }, b = c ? d : e;\n"
                  "// the delta is here\nvar s = '// not a comment'; /* epsilon, zeta */")
        self.assertEqual(object_keys(source), ["alpha", "beta", "gamma"])
        self.assertEqual(comment_words(source), ["the", "delta", "is", "here", "epsilon", "zeta"])

    def test_short_object_keys_are_english_words(self):
        for page in PAGES:
            short = sorted({
                key
                for script in inline_scripts(page)
                for key in object_keys(script)
                if 2 <= len(key) <= 3 and key not in ENGLISH_SHORT_NAMES | DATA_KEYS
            })
            with self.subTest(page=page.name):
                self.assertEqual(short, [], f"{page.name} writes short object keys "
                                 f"a reader has to guess: {', '.join(short)}")

    def test_comments_spell_out_the_names_they_mention(self):
        for page in PAGES:
            shorthand = sorted({
                word
                for script in inline_scripts(page)
                for word in comment_words(script)
                if word in COMMENT_SHORTHAND
            })
            with self.subTest(page=page.name):
                self.assertEqual(shorthand, [], f"{page.name} comments use shorthand: "
                                 f"{', '.join(shorthand)}")
