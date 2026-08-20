"""Every inline <script> in a template has to parse.

Written the moment it earned its keep: a refactor of the bell panel's
mark-on-open handler left one extra `});` behind. Python never sees it,
Django renders the page happily, the suite stayed green — and every feature
defined in that 200-line script block would have been dead in the browser,
found by the operator rather than by us.

There is no bundler and no linter in this project; the JS lives inline in
templates and in static/js. Node's own parser is the whole tool needed, and
the CI runner already has node.

Blocks containing Django tags are skipped: `{% url %}` and `{{ value }}` are
not JavaScript, and a parser is right to reject them. Those blocks are
deliberately kept small for exactly this reason — logic belongs in a plain
block or a static file, where this guard can reach it.

One node process for the whole sweep, not one per block: at ~50 blocks the
per-spawn cost was over a minute of the suite's wall clock, which is how a
guard becomes the thing somebody deletes.

Run with:  python manage.py test tests.test_inline_js_parses
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

NODE = shutil.which("node")
SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S)
DJANGO_TAG_RE = re.compile(r"\{%|\{\{")
# HTML comments come out FIRST. the_wall.html carries a comment that says
# the words "<script>" while explaining why one must not go there, and a
# naive scan opens a block on it and then swallows everything up to the next
# real closing tag — reporting prose as a syntax error.
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)

# Parses each source as a SCRIPT and reports every failure in one pass.
# `new vm.Script` compiles without executing, which is the only thing wanted
# here — running arbitrary page JS under node would fail on `document`
# rather than on syntax.
CHECKER_JS = r"""
const fs = require('fs'), vm = require('vm');
/* argv is [node, this script, the manifest] — the manifest is argv[2]. */
const jobs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const bad = [];
for (const job of jobs) {
    try { new vm.Script(job.source, { filename: job.label }); }
    catch (e) { bad.push({ label: job.label, error: String(e && e.message) }); }
}
process.stdout.write(JSON.stringify(bad));
"""


def _template_dirs():
    dirs = []
    for engine in settings.TEMPLATES:
        dirs.extend(Path(d) for d in engine.get("DIRS", []))
    return [d for d in dirs if d.exists()]


def _parse_all(jobs):
    """[{label, source}, ...] -> [(label, error), ...] for the ones that fail."""
    tmp = Path(tempfile.mkdtemp(prefix="sv-jscheck-"))
    try:
        manifest = tmp / "jobs.json"
        manifest.write_text(json.dumps(jobs), encoding="utf-8")
        runner = tmp / "check.js"
        runner.write_text(CHECKER_JS, encoding="utf-8")
        proc = subprocess.run([NODE, str(runner), str(manifest)],
                              capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            raise AssertionError(
                f"the JS checker itself failed: {proc.stderr[:500]}")
        return [(row["label"], row["error"])
                for row in json.loads(proc.stdout or "[]")]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipIf(NODE is None, "node is not installed on this machine")
class InlineTemplateScriptsParseTests(SimpleTestCase):
    def test_every_plain_inline_script_parses(self):
        jobs = []
        for root in _template_dirs():
            for tpl in sorted(root.rglob("*.html")):
                text = HTML_COMMENT_RE.sub(
                    "", tpl.read_text(encoding="utf-8", errors="replace"))
                for i, block in enumerate(SCRIPT_RE.findall(text)):
                    if DJANGO_TAG_RE.search(block) or not block.strip():
                        continue
                    jobs.append({"label": f"{tpl.name} inline script #{i}",
                                 "source": block})
        # A guard that silently checks nothing is not a guard. base.html
        # alone carries more than ten plain blocks.
        self.assertGreater(len(jobs), 5,
                           "no inline scripts were checked — the extractor "
                           "has stopped matching the markup")
        failures = _parse_all(jobs)
        self.assertEqual(
            failures, [],
            "\n".join(f"{label}: {err}" for label, err in failures))


class StylesheetStructureTests(SimpleTestCase):
    """A stylesheet has no parser here either, and it shows.

    Written after a comment was inserted INSIDE an existing comment block:
    the first `*/` closed both, five lines of English prose landed in the
    stylesheet as top-level CSS, and that swallowed the very next rule into
    an invalid selector prelude. The rule the comment was explaining — the
    one that paints the headband's alarm cells red — was dropped by the
    browser, so the >=60% volatility alarm rendered in the platform's
    "good" green. Nothing failed; the page just quietly lied.

    CSS is forgiving by design: a browser skips what it cannot parse and
    says nothing, which is exactly why this needs a test rather than a
    stack trace.
    """

    def _sheets(self):
        root = Path(settings.BASE_DIR) / "static" / "css"
        return sorted(root.rglob("*.css")) if root.exists() else []

    def test_there_are_stylesheets_to_check(self):
        self.assertTrue(self._sheets(), "static/css is empty")

    def test_no_comment_opens_inside_another_comment(self):
        """`/*` inside a comment means somebody nested one, and the first
        `*/` will end both."""
        for css in self._sheets():
            text = css.read_text(encoding="utf-8", errors="replace")
            depth, i, line = 0, 0, 1
            while i < len(text) - 1:
                pair = text[i:i + 2]
                if pair == "/*":
                    self.assertEqual(
                        depth, 0,
                        f"{css.name}:{line} opens a comment inside a comment")
                    depth, i = 1, i + 2
                    continue
                if pair == "*/":
                    self.assertEqual(
                        depth, 1,
                        f"{css.name}:{line} closes a comment that never opened")
                    depth, i = 0, i + 2
                    continue
                if text[i] == "\n":
                    line += 1
                i += 1
            self.assertEqual(depth, 0, f"{css.name} ends inside a comment")

    def test_braces_balance(self):
        """An unclosed block silently swallows every rule after it."""
        for css in self._sheets():
            text = re.sub(r"/\*.*?\*/", "", css.read_text(
                encoding="utf-8", errors="replace"), flags=re.S)
            text = re.sub(r"""(['"])(?:\\.|(?!\1).)*\1""", "''", text)
            self.assertEqual(text.count("{"), text.count("}"),
                             f"{css.name} has unbalanced braces")

    def test_no_prose_escaped_into_the_rules(self):
        """The tell of the bug above: a line of English at top level.

        A real declaration or selector never starts with a lowercase word
        followed by a space and another word with no punctuation between
        them — but a sentence always does.
        """
        prose = re.compile(r"^\s{0,20}[A-Z][a-z]+\s+[a-z]+\s+[a-z]+")
        for css in self._sheets():
            stripped = re.sub(r"/\*.*?\*/", "", css.read_text(
                encoding="utf-8", errors="replace"), flags=re.S)
            for n, ln in enumerate(stripped.splitlines(), start=1):
                if prose.match(ln) and not ln.rstrip().endswith((";", "{", "}", ",")):
                    self.fail(f"{css.name}:{n} looks like prose outside a "
                              f"comment: {ln.strip()[:80]!r}")


@unittest.skipIf(NODE is None, "node is not installed on this machine")
class StaticJsParsesTests(SimpleTestCase):
    def test_every_shipped_js_file_parses(self):
        root = Path(settings.BASE_DIR) / "static" / "js"
        if not root.exists():
            self.skipTest("no static/js directory")
        jobs = [{"label": js.name,
                 "source": js.read_text(encoding="utf-8", errors="replace")}
                for js in sorted(root.rglob("*.js"))]
        self.assertGreater(len(jobs), 0, "static/js is empty")
        failures = _parse_all(jobs)
        self.assertEqual(
            failures, [],
            "\n".join(f"{label}: {err}" for label, err in failures))
