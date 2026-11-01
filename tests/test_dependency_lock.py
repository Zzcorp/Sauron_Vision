"""The dependency lock: the direct requirements CI tests are the ones the
next image installs.

requirements.txt carried ranged pins (anthropic>=0.40, openai>=1.50 and
most of the others). The production image's pip layer is cached on that
file's content, so a box kept whatever release was newest the first time
it built the layer: the anthropic SDK could be 0.x, 1.x or 2.x, and with
it the API version the platform sends. And editing any one line, for an
unrelated package, rebuilt the layer and moved every unpinned package to
that day's newest at once.

Every requirement is pinned exactly now (2026-10-31), to what CI resolved
that day. These tests keep it so: a ranged or unbounded pin fails here,
the anthropic pin must be the 2.x line the provider's suites pass on, and
no image or CI step installs a package outside the lock.

The packages those requirements pull in (86 of the 132 installed on
Python 3.12, httpx2 and httpcore2 under the anthropic SDK among them) are
not pinned: a rebuild of the pip layer resolves them again that day.

Run with:  python manage.py test tests.test_dependency_lock
"""
import re
from importlib import metadata
from pathlib import Path

from django.test import SimpleTestCase

REPO = Path(__file__).resolve().parent.parent

#: name[extras]==version, with an optional environment marker. Nothing
#: else: no >=, no ~=, no <, no wildcard, no bare name.
EXACT = re.compile(
    r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)"
    r"(?:\[[A-Za-z0-9_.,-]+\])?"
    r"==(?P<version>[0-9][0-9A-Za-z.+!-]*)"
    r"(?:\s*;\s*(?P<marker>.+))?$")

#: The anthropic line the provider's suites (118 tests) were run on, and
#: the API version and auth header that SDK sends.
ANTHROPIC_MAJOR = 2
ANTHROPIC_API_VERSION = "2026-10-21"


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_lines(text: str) -> list:
    """The requirement lines of a requirements file, comments stripped."""
    out = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def loose_lines(lines) -> list:
    """The lines that are not an exact pin."""
    return [line for line in lines if not EXACT.match(line)]


def pins(text: str) -> dict:
    """{normalized name: [(version, marker or "")]} of the exact lines."""
    out = {}
    for line in requirement_lines(text):
        m = EXACT.match(line)
        if m:
            out.setdefault(_norm(m["name"]), []).append(
                (m["version"], (m["marker"] or "").strip()))
    return out


#: pip options that take the next token as their value.
_VALUE_FLAGS = {"-r", "--requirement", "-c", "--constraint", "-w",
                "--wheel-dir", "-f", "--find-links", "-i", "--index-url"}


def pip_targets(text: str) -> list:
    """What each `pip install` / `pip wheel` in `text` names on its own
    command line, beside the files it reads: [(command, [targets])]."""
    text = text.replace("\\\n", " ")
    found = []
    for segment in re.split(r"&&|\|\||;|\n", text):
        tokens = segment.split()
        for i, tok in enumerate(tokens[:-1]):
            if tok == "pip" and tokens[i + 1] in ("install", "wheel"):
                rest = iter(tokens[i + 2:])
                targets = []
                for t in rest:
                    if t in _VALUE_FLAGS:
                        next(rest, None)
                    elif t.startswith("-") or t[:1].isdigit() and ">" in t:
                        continue        # an option, or a 2>/dev/null
                    else:
                        targets.append(t)
                found.append((" ".join(tokens[i:]), targets))
                break
    return found


class RequirementsAreExactTests(SimpleTestCase):

    def setUp(self):
        self.text = (REPO / "requirements.txt").read_text(encoding="utf-8")
        self.lines = requirement_lines(self.text)

    def test_the_checker_refuses_every_shape_of_a_loose_pin(self):
        """The guard itself: each of these would let a rebuild move."""
        self.assertEqual(loose_lines([
            "anthropic>=0.40", "anthropic>=2.3.0,<3", "anthropic~=2.3",
            "anthropic", "anthropic==2.*", "anthropic<3",
            "Django>=5.1,<6.0", "uvicorn[standard]>=0.30",
            "anthropic==2.3.0", "uvicorn[standard]==0.54.0",
            'numpy==2.5.4; python_version >= "3.12"',
        ]), ["anthropic>=0.40", "anthropic>=2.3.0,<3", "anthropic~=2.3",
             "anthropic", "anthropic==2.*", "anthropic<3",
             "Django>=5.1,<6.0", "uvicorn[standard]>=0.30"])

    def test_the_file_it_replaced_fails_the_guard(self):
        """The requirements.txt of 6bf2f06..dbfe0a9, as it was: unbounded."""
        before = ["anthropic>=0.40", "openai>=1.50", "ollama>=0.4",
                  "numpy>=1.26,<3.0", "celery>=5.4,<6"]
        self.assertEqual(loose_lines(before), before)

    def test_every_requirement_is_pinned_exactly(self):
        self.assertGreater(len(self.lines), 40)
        self.assertEqual(
            loose_lines(self.lines), [],
            "a ranged or unbounded pin lets the next rebuild install "
            "whatever is newest that day: pin it with ==")

    def test_no_package_is_named_twice_except_under_a_marker(self):
        for name, versions in pins(self.text).items():
            if len(versions) > 1:
                self.assertTrue(all(marker for _, marker in versions), name)
                self.assertEqual(len({m for _, m in versions}),
                                 len(versions), name)

    def test_the_file_reads_no_other_file(self):
        """No -r/-c line: the image copies requirements.txt alone, so a
        constraints file next to it would be missing at build time."""
        self.assertEqual([line for line in self.lines
                          if line.startswith("-")], [])

    def test_anthropic_is_pinned_exactly_on_the_2x_line(self):
        found = pins(self.text).get("anthropic")
        self.assertIsNotNone(found, "requirements.txt must name anthropic")
        self.assertEqual(len(found), 1)
        version, marker = found[0]
        self.assertEqual(marker, "")
        self.assertEqual(int(version.split(".")[0]), ANTHROPIC_MAJOR)


class TheSuiteRunsOnTheLockedSdkTests(SimpleTestCase):
    """CI installs requirements.txt, so the SDK under the suite is the
    pinned one; a hand-installed other version fails here instead of
    passing the provider's suites on a wire they do not describe."""

    def test_the_installed_sdk_is_the_pinned_one(self):
        text = (REPO / "requirements.txt").read_text(encoding="utf-8")
        (version, _), = pins(text)["anthropic"]
        self.assertEqual(metadata.version("anthropic"), version)

    def test_the_sdk_sends_the_api_version_the_lock_was_verified_on(self):
        import anthropic
        headers = anthropic.Anthropic(api_key="not-a-key").default_headers
        self.assertEqual(int(anthropic.__version__.split(".")[0]),
                         ANTHROPIC_MAJOR)
        self.assertEqual(headers["anthropic-version"], ANTHROPIC_API_VERSION)
        self.assertIn("Authorization", headers)
        self.assertNotIn("X-Api-Key", headers)


class NothingInstallsOutsideTheLockTests(SimpleTestCase):
    """A package named on a pip command line is resolved to that day's
    newest, beside the lock. Dockerfile.prod wheeled gunicorn and
    uvicorn[standard] a second time that way; with both pinned in
    requirements.txt, the next release would have put two versions of
    each in /wheels, and the runtime stage installs /wheels/*.whl."""

    FILES = ("Dockerfile", "Dockerfile.prod", ".github/workflows/tests.yml")

    def test_the_parser_sees_a_bare_package(self):
        self.assertEqual(pip_targets(
            "RUN pip wheel --no-cache-dir --wheel-dir=/build/wheels "
            "-r requirements.txt \\\n"
            "    && pip wheel --no-cache-dir --wheel-dir=/build/wheels "
            "gunicorn uvicorn[standard]\n"),
            [("pip wheel --no-cache-dir --wheel-dir=/build/wheels "
              "-r requirements.txt", []),
             ("pip wheel --no-cache-dir --wheel-dir=/build/wheels "
              "gunicorn uvicorn[standard]", ["gunicorn", "uvicorn[standard]"])])

    def test_every_pip_command_reads_the_lock_or_its_wheels(self):
        seen = 0
        for rel in self.FILES:
            text = (REPO / rel).read_text(encoding="utf-8")
            for command, targets in pip_targets(text):
                seen += 1
                self.assertEqual(
                    [t for t in targets if not t.startswith("/wheels/")], [],
                    f"{rel}: `{command}` installs a package outside "
                    "requirements.txt")
        self.assertGreaterEqual(seen, 4)

    def test_the_production_image_still_wheels_the_lock(self):
        text = (REPO / "Dockerfile.prod").read_text(encoding="utf-8")
        self.assertIn("COPY requirements.txt ./", text)
        self.assertIn("--wheel-dir=/build/wheels -r requirements.txt", text)
