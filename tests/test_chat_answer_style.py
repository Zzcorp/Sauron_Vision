"""Ask Sauron's answer: how it is built, and what it is allowed to build.

The floating panel paints model output into the operator's page. Two things
have to hold at once and neither is visible from a screenshot:

  * SAFETY. The answer is text an LLM wrote. It used to be escaped and
    assigned to innerHTML, which works right up until the escaping has a
    gap. The renderer now builds DOM nodes instead — createElement for the
    structure, textContent for every leaf — so markup in the answer arrives
    as the characters the model typed and is never handed to the parser.
    The only attribute taken from that text is a link's href, and it is
    matched against a whitelist BEFORE it is set. This file pins that:
    no innerHTML on the path, no attribute but the four the renderer is
    allowed to set, and a whitelist that still rejects the schemes.

  * THE CITATIONS STILL WORK. brain/research_renderer turns the agent's
    <<KIND:id>> markers into markdown links pointing at a fixed table of
    same-origin paths. A whitelist tightened past those paths would silently
    stop rendering every citation the platform produces, so the test asks
    the renderer itself for its URLs and puts each one through the guard.

One hole is closed on the way through: the old pattern allowed any run of
path characters after the leading slash, and `/` was one of them — so
`//host/x` read as a path and was a jump off the platform. The second
character may no longer be a slash.

The rest is the type: a wall of undifferentiated text was the failure state
this replaced, so the classes the renderer emits must all be styled, the
figures must be mono and tabular, wide things must scroll inside themselves,
and both themes must be addressed.

Static analysis only — nothing here renders a page.

Run with:  python manage.py test tests.test_chat_answer_style
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

BASE_HTML = Path(settings.BASE_DIR) / "templates" / "base.html"
CSS_PATH = Path(settings.BASE_DIR) / "static" / "css" / "sauron.css"

#: Where the renderer starts and ends inside base.html's chat script.
RENDERER_START = "Sauron's answer, rendered"
RENDERER_END = "function toolsHtml(role, msgId)"

#: The delimited CSS section this slice owns.
CSS_SECTION_MARK = "ASK SAURON — THE ANSWER"


def _template():
    return BASE_HTML.read_text(encoding="utf-8")


def _css():
    return CSS_PATH.read_text(encoding="utf-8")


def _renderer():
    """The renderer's source, on its own.

    Starts at the opening `/*` of its banner rather than at the marker text
    inside it, so the comment is whole and _renderer_code can strip it.
    """
    src = _template()
    at = src.index(RENDERER_START)
    return src[src.rindex("/*", 0, at):src.index(RENDERER_END)]


def _renderer_code():
    """The renderer with its comments removed.

    The sink scan below has to run on code rather than on prose: the block
    comment at the top of the renderer names innerHTML precisely in order to
    say that nothing there uses it, and a scan that cannot tell the two
    apart would forbid explaining the rule it is enforcing.
    """
    return re.sub(r"/\*.*?\*/", "", _renderer(), flags=re.S)


def _chat_script():
    """The whole Ask-Sauron script block, renderer and panel wiring both."""
    src = _template()
    anchor = src.index("var fab = document.getElementById('seEyeFab');")
    return src[src.rindex("<script>", 0, anchor):src.index("</script>", anchor)]


def _css_section():
    css = _css()
    return css[css.index(CSS_SECTION_MARK):]


def _strip_css_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _js_regex(name):
    """Lift a named JS regex literal out of the template as a Python pattern.

    JS `$` matches only at the end of input; Python's also matches before a
    trailing newline, which would make every rejection test here weaker than
    the browser it is standing in for.
    """
    src = _renderer()
    found = re.search(r"var %s\s*=\s*/(.+?)/;" % name, src)
    assert found, "%s is no longer declared as a regex literal" % name
    pattern = found.group(1)
    if pattern.endswith("$"):
        pattern = pattern[:-1] + r"\Z"
    return re.compile(pattern)


class NoModelTextReachesTheParserTests(SimpleTestCase):
    """The answer is built, not injected."""

    def test_the_renderer_never_touches_inner_html(self):
        src = _renderer_code()
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML",
                     "document.write", "createContextualFragment"):
            self.assertNotIn(
                sink, src,
                "%s on the answer path is how a chat panel becomes an XSS "
                "hole — the whole point of this renderer is that model text "
                "is never parsed as markup" % sink)

    def test_it_builds_nodes_and_carries_text_as_text(self):
        src = _renderer_code()
        self.assertIn("document.createElement", src)
        self.assertIn("document.createTextNode", src)
        self.assertIn("textContent", src)

    def test_the_only_attributes_it_sets_are_the_four_it_may(self):
        """href is the one value read out of model text, and it is checked
        first; the other three are the renderer's own."""
        names = set(re.findall(r"setAttribute\(\s*'([^']+)'", _renderer()))
        self.assertEqual(
            names, {"href", "target", "rel", "start"},
            "an attribute is being set from the answer that this file has "
            "never reasoned about: %r" % sorted(names))

    def test_the_answer_goes_through_the_renderer(self):
        script = _chat_script()
        self.assertIn("renderAnswer(body, m.text)", script)
        self.assertNotIn(
            "body.innerHTML = linkify", script,
            "the escape-then-innerHTML path is back")
        self.assertNotIn(
            "function linkify", script,
            "linkify is superseded by renderAnswer; two paths means one of "
            "them is the one nobody remembers to harden")

    def test_the_operators_own_question_is_never_re_parsed(self):
        """A user bubble is what they typed, shown as they typed it."""
        script = _chat_script()
        self.assertIn("body.textContent = m.text || '';", script)


class HrefWhitelistTests(SimpleTestCase):
    """What a link in the answer is allowed to point at."""

    def setUp(self):
        self.path = _js_regex("SAFE_PATH")
        self.url = _js_regex("SAFE_URL")

    def _rejected(self, candidate):
        return not (self.path.match(candidate) or self.url.match(candidate))

    def test_no_scheme_can_be_spelled(self):
        for hostile in ("javascript:alert(1)",
                        "JavaScript:alert(1)",
                        " javascript:alert(1)",
                        "data:text/html,<svg onload=alert(1)>",
                        "vbscript:msgbox(1)",
                        "jav\tascript:alert(1)",
                        "file:///etc/passwd"):
            with self.subTest(href=hostile):
                self.assertTrue(
                    self._rejected(hostile),
                    "%r passes the href guard, so the renderer would put it "
                    "on a link the operator can click" % hostile)

    def test_a_protocol_relative_url_is_not_a_path(self):
        """`//host/x` looks like a path and is a jump off the platform — the
        hole the old pattern left open."""
        for hostile in ("//evil.example/x", "///evil.example", "//"):
            with self.subTest(href=hostile):
                self.assertTrue(self._rejected(hostile), hostile)

    def test_a_quote_or_bracket_can_never_ride_along(self):
        """Belt and braces: the href is set with setAttribute, so quoting is
        not what protects it — but a value carrying markup is a smell."""
        for hostile in ('/ok" onmouseover="alert(1)',
                        "/ok'><img src=x onerror=alert(1)>",
                        "https://x.example/a\"onload=alert(1)"):
            with self.subTest(href=hostile):
                self.assertTrue(self._rejected(hostile), hostile)

    def test_the_shapes_that_must_keep_working(self):
        for good in ("/generated/", "/audit/", "/hypotheses/#top",
                     "/brain/?tab=regime", "/knowledge/", "/"):
            with self.subTest(href=good):
                self.assertTrue(self.path.match(good),
                                "%r no longer renders as a link" % good)
        for good in ("https://example.com/a/b?c=1",
                     "http://example.com/x"):
            with self.subTest(href=good):
                self.assertTrue(self.url.match(good), good)

    def test_every_citation_the_platform_emits_survives_the_guard(self):
        """The agent's markers become links from a fixed server-side table.
        Tighten the guard past that table and every citation on the platform
        silently stops being clickable."""
        from brain.research_renderer import _url_for_marker
        kinds = ("RULE", "HYP", "REPORT", "AUDIT", "BRIEFING", "EARNINGS",
                 "KNOWLEDGE")
        seen = 0
        for kind in kinds:
            url = _url_for_marker(kind, "42")
            self.assertIsNotNone(
                url, "%s no longer maps to a URL — if the marker was "
                     "retired, drop it from this list" % kind)
            seen += 1
            self.assertTrue(
                self.path.match(url),
                "the citation target %r for <<%s:...>> is rejected by "
                "SAFE_PATH, so that citation renders as raw markdown"
                % (url, kind))
        self.assertEqual(seen, len(kinds))

    def test_an_off_platform_link_cannot_reach_back(self):
        src = _renderer()
        self.assertIn("noopener noreferrer", src)
        self.assertIn("'_blank'", src)

    def test_a_rejected_href_degrades_to_text_rather_than_vanishing(self):
        """Dropping the link silently would lose what the model said."""
        self.assertIn("createTextNode(m[0])", _renderer())


class StructureIsRenderedTests(SimpleTestCase):
    """A trader reads this mid-decision; undifferentiated text is failure."""

    def test_each_block_the_model_emits_has_a_reader(self):
        src = _renderer()
        for fn in ("takeFence", "takeHeading", "takeQuote", "takeTable",
                   "takeList", "takeParagraph"):
            self.assertIn("function %s(" % fn, src,
                          "%s is gone, so that structure renders as the raw "
                          "characters the model typed" % fn)

    def test_inline_marks_are_covered(self):
        kinds = set(re.findall(r"kind:\s*'([a-z]+)'", _renderer()))
        self.assertEqual(
            kinds, {"code", "link", "strong", "em", "url"},
            "the inline rule set changed: %r" % sorted(kinds))

    def test_underscore_emphasis_stays_out(self):
        """Rule names on this platform are snake_case. An `_italic_` rule
        would open on the first underscore of golden_cross_v2 and close on
        the second, italicising the middle of a name."""
        rules = re.search(r"var INLINE = \[(.*?)\n    \];", _renderer(),
                          flags=re.S)
        self.assertIsNotNone(rules, "the inline rule table moved")
        self.assertNotIn(
            "_", rules.group(1),
            "an inline rule now carries an underscore, which is how "
            "snake_case rule names start being eaten as emphasis")

    def test_a_numeric_column_is_right_aligned(self):
        src = _renderer()
        self.assertIn("CELL_NUM_RE", src)
        self.assertIn("se-md-num", src)

    def test_an_unmeasured_cell_stays_in_the_numeric_column(self):
        """An em-dash means NOT MEASURED. It belongs lined up with the
        readings it stands in for, not adrift in the text column."""
        found = re.search(r"var CELL_NUM_RE\s*=\s*/(.+?)/;", _renderer())
        self.assertIsNotNone(found)
        self.assertIn("—", found.group(1),
                      "the em-dash no longer counts as a figure, so one "
                      "unmeasured reading un-aligns its whole column")

    def test_the_list_depth_is_bounded_by_a_named_constant(self):
        src = _renderer()
        found = re.search(r"var MAX_LIST_DEPTH\s*=\s*(\d+);", src)
        self.assertIsNotNone(found, "the nesting cap is now a bare number")
        self.assertEqual(
            found.group(1), "3",
            "three levels is as deep as a readable answer goes; changing it "
            "means changing the reasoning in the comment above it")


class AnswerTypeTests(SimpleTestCase):
    """The type has to look like the platform, not like a chat widget."""

    def _emitted_classes(self):
        """Every class the renderer actually puts on a node."""
        out = set()
        for expr in re.findall(r"className\s*=\s*([^;]+);", _chat_script(),
                               flags=re.S):
            for token in re.findall(r"se-(?:md-[a-z0-9-]+|fig(?:--[a-z]+)?"
                                    r"|answer)\b", expr):
                out.add(token)
        return out

    def test_the_section_is_delimited_and_present(self):
        self.assertIn(CSS_SECTION_MARK, _css())

    def test_every_class_the_renderer_emits_is_styled(self):
        css = _css()
        emitted = self._emitted_classes()
        self.assertIn("se-answer", emitted)
        missing = sorted(c for c in emitted if ("." + c) not in css)
        self.assertEqual(
            missing, [],
            "the renderer puts these classes on nodes that no rule paints, "
            "so that structure renders as unstyled text: %r" % missing)

    def test_the_three_heading_tiers_all_exist(self):
        """The class is built by concatenation, so the scan above cannot
        see the tiers themselves."""
        css = _css()
        for tier in ("se-md-h1", "se-md-h2", "se-md-h3"):
            self.assertIn("." + tier, css,
                          "%s has no rule, so that heading level is "
                          "indistinguishable from body text" % tier)

    def test_figures_are_mono_and_tabular(self):
        """Proportional digits make a column of R multiples jitter; tabular
        ones fix the advance width, which is the only reason two numbers on
        separate lines can be compared by eye."""
        css = _strip_css_comments(_css())
        body = re.search(r"\.se-answer \.se-fig\s*\{([^}]*)\}", css)
        self.assertIsNotNone(body, ".se-fig is not styled")
        self.assertIn("var(--font-mono)", body.group(1))
        self.assertRegex(body.group(1),
                         r"font-variant-numeric\s*:\s*tabular-nums")

    def test_a_figure_inherits_its_colour_so_it_survives_a_link(self):
        """A hard colour on .se-fig would repaint the digits inside a
        citation and break the link's own ink."""
        css = _strip_css_comments(_css())
        body = re.search(r"\.se-answer \.se-fig\s*\{([^}]*)\}", css).group(1)
        self.assertIn("currentColor", body)

    def test_wide_content_scrolls_inside_its_own_container(self):
        css = _strip_css_comments(_css())
        for selector in (r"\.se-answer \.se-md-scroll",
                         r"\.se-answer \.se-md-pre"):
            self.assertRegex(
                css, selector + r"\s*\{[^}]*overflow-x\s*:\s*auto",
                "%s does not scroll, so a wide table or a long code line "
                "pushes the bubble past the panel" % selector)

    def test_the_panel_itself_never_scrolls_sideways(self):
        css = _strip_css_comments(_css())
        section = _strip_css_comments(_css_section())
        self.assertRegex(
            section, r"\.se-chat-messages\s*\{[^}]*overflow-x\s*:\s*hidden",
            "nothing pins the horizontal axis at the container, so any "
            "child that overflows hands the whole panel a scrollbar")
        self.assertIn(".se-chat-messages", css)

    def test_long_tokens_break_only_where_they_should(self):
        """`anywhere` counts its break points in min-content sizing: on a
        cell it lets a wide table compress instead of scrolling, and splits
        a price mid-digit. It is right on a rule name and a URL only."""
        section = _strip_css_comments(_css_section())
        for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", section):
            if not re.search(r"overflow-wrap\s*:\s*anywhere", body):
                continue
            self.assertRegex(
                selector.strip(), r"\.se-md-(code|a)\b",
                "%s takes overflow-wrap:anywhere, which it should not"
                % selector.strip()[:60])

    def test_the_arrival_yields_to_reduced_motion(self):
        section = _strip_css_comments(_css_section())
        block = re.search(
            r"@media \(prefers-reduced-motion: reduce\)\s*\{(.*?)\n\}",
            section, flags=re.S)
        self.assertIsNotNone(
            block, "the answer animates in with nothing to turn it off")
        self.assertIn(".se-answer", block.group(1))

    def test_both_themes_are_addressed(self):
        section = _css_section()
        self.assertIn(
            "body.light-mode .se-answer", section,
            "every surface here was mixed against a near-black card; with "
            "no light-mode restatement the answer is unreadable on white")

    def test_the_section_paints_from_tokens_only(self):
        """A raw colour cannot follow body.light-mode."""
        section = _strip_css_comments(_css_section())
        literals = re.findall(r"#[0-9a-fA-F]{3,8}\b", section)
        self.assertEqual(literals, [], "raw colours: %r" % literals)

    def test_the_section_declares_no_raw_stacking_order(self):
        section = _strip_css_comments(_css_section())
        raw = re.findall(r"z-index\s*:\s*\d+", section)
        self.assertEqual(raw, [], "raw z-index: %r" % raw)
