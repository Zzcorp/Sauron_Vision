"""Which commit is running? (2026-09-13)

`.dockerignore` excludes `.git` — correctly. The consequence nobody had
accounted for is that the running application could not answer the
simplest question about itself, and it cost a day: the box served the
previous commit, `/personas/` and `/setups/` answered 404, the operator
reported "il manque beaucoup de choses", and the only way to find out was
probing the public site route by route from OUTSIDE. Nothing on the
platform could say "I am stale".

`deploy/dc` now reads the sha from the checkout, compose passes it as a
build arg, the Dockerfile turns it into an env var, and
`core/build_stamp.py` reads it back. These tests hold every link of that
chain, because a chain that breaks anywhere reports "unknown" — which is
honest, and useless.

THE RULE THAT MATTERS MOST. An unstamped build reports None and the page
renders an em dash. It must never report the literal string "unknown",
which reads like data, and it must never invent a plausible sha, which is
the exact species of fabrication core/wall_facts.py exists to abolish: a
number nobody can check, presented as measured.
"""
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core import build_stamp


def _read(*parts):
    return (Path(settings.BASE_DIR).joinpath(*parts)).read_text(
        encoding="utf-8")


class TheStampNeverGuessesTests(SimpleTestCase):

    def test_an_unstamped_build_reports_none_not_a_word(self):
        for value in ("", "unknown", "UNKNOWN", "none", "null", "  "):
            with self.subTest(value=value):
                with mock.patch.dict("os.environ",
                                     {"SAURON_GIT_SHA": value}, clear=False):
                    self.assertIsNone(
                        build_stamp.git_sha(),
                        f"{value!r} came back as data; the page would print "
                        f"it as though it were a commit")

    def test_a_real_sha_survives_unchanged(self):
        with mock.patch.dict("os.environ",
                             {"SAURON_GIT_SHA": "65055ec"}, clear=False):
            self.assertEqual(build_stamp.git_sha(), "65055ec")

    def test_a_missing_variable_is_none(self):
        env = {k: v for k, v in __import__("os").environ.items()
               if k not in ("SAURON_GIT_SHA", "SAURON_BUILT_AT")}
        with mock.patch.dict("os.environ", env, clear=True):
            self.assertIsNone(build_stamp.git_sha())
            self.assertIsNone(build_stamp.built_at())
            self.assertIsNone(build_stamp.build_age_hours())
            self.assertFalse(build_stamp.stamp()["stamped"])

    def test_the_age_is_computed_from_the_stamp(self):
        from datetime import datetime, timedelta, timezone as dt_tz
        when = datetime.now(dt_tz.utc) - timedelta(hours=31)
        with mock.patch.dict(
                "os.environ",
                {"SAURON_BUILT_AT": when.strftime("%Y-%m-%dT%H:%M:%SZ")},
                clear=False):
            self.assertAlmostEqual(build_stamp.build_age_hours(), 31.0,
                                   delta=0.2)

    def test_an_unreadable_timestamp_is_none_and_not_a_crash(self):
        """A bad stamp must cost the age, never the page."""
        with mock.patch.dict("os.environ",
                             {"SAURON_BUILT_AT": "yesterday-ish"},
                             clear=False):
            self.assertIsNone(build_stamp.build_age_hours())

    def test_stamp_never_raises(self):
        with mock.patch.dict("os.environ",
                             {"SAURON_GIT_SHA": "x", "SAURON_BUILT_AT": "!!"},
                             clear=False):
            out = build_stamp.stamp()
        self.assertEqual(set(out), {"sha", "built_at", "age_hours", "stamped"})


class TheChainThatCarriesItTests(SimpleTestCase):
    """Four files have to agree or the stamp silently reads 'unknown'."""

    def test_the_wrapper_reads_the_sha_from_the_checkout(self):
        dc = _read("deploy", "dc")
        self.assertIn("git rev-parse --short HEAD", dc)
        self.assertIn("export GIT_SHA=", dc)
        self.assertIn("export BUILT_AT=", dc)

    def test_the_wrapper_still_starts_without_git(self):
        """A tarball deploy, or a checkout with no .git, must still bring the
        platform up — it simply ships an unstamped image."""
        dc = _read("deploy", "dc")
        self.assertIn("|| true", dc)
        self.assertIn(':-unknown}"', dc)

    def test_compose_passes_both_args(self):
        compose = _read("deploy", "docker-compose.yml")
        self.assertIn("GIT_SHA: ${GIT_SHA:-unknown}", compose)
        self.assertIn("BUILT_AT: ${BUILT_AT:-unknown}", compose)

    def test_the_dockerfile_declares_and_exports_them(self):
        df = _read("Dockerfile.prod")
        self.assertIn("ARG GIT_SHA=unknown", df)
        self.assertIn("ARG BUILT_AT=unknown", df)
        self.assertIn("ENV SAURON_GIT_SHA=$GIT_SHA", df)
        self.assertIn("SAURON_BUILT_AT=$BUILT_AT", df)

    def test_the_args_sit_after_every_expensive_layer(self):
        """They change on EVERY build by definition. Placed above the wheel
        install or collectstatic they would bust both caches each time,
        turning a four-second rebuild into a four-minute one — which is how
        a build stamp gets removed again six months later."""
        df = _read("Dockerfile.prod")
        arg_at = df.index("ARG GIT_SHA=unknown")
        for expensive in ("pip install", "collectstatic", "COPY --chown"):
            self.assertLess(
                df.index(expensive), arg_at,
                f"ARG GIT_SHA sits above {expensive!r} and will invalidate it "
                f"on every single build")


class TheForgeReportsItTests(TestCase):

    def test_the_forge_is_a_cycle(self):
        from dashboard.oculus import oculus
        keys = [c["key"] for c in oculus()["cycles"]]
        self.assertIn("forge", keys)

    def test_the_sha_is_a_text_fact_not_a_count(self):
        """Rounding an identifier to an integer is not a category error
        anyone catches later."""
        from dashboard.oculus import oculus
        with mock.patch.dict("os.environ",
                             {"SAURON_GIT_SHA": "65055ec"}, clear=False):
            forge = next(c for c in oculus()["cycles"] if c["key"] == "forge")
        sha = next(f for f in forge["facts"] if "commit" in f["label"])
        self.assertTrue(sha.get("text"))
        self.assertEqual(sha["value"], "65055ec")

    def test_an_unstamped_image_dashes_on_the_page(self):
        import html as _html
        from dashboard.oculus import oculus
        env = {k: v for k, v in __import__("os").environ.items()
               if k != "SAURON_GIT_SHA"}
        with mock.patch.dict("os.environ", env, clear=True):
            forge = next(c for c in oculus()["cycles"] if c["key"] == "forge")
        sha = next(f for f in forge["facts"] if "commit" in f["label"])
        self.assertIsNone(sha["value"])

        user = User.objects.create_user("forge_u", password="x")
        self.client.force_login(user)
        body = _html.unescape(
            self.client.get(reverse("oculus_dashboard")).content.decode())
        self.assertIn("La forge", body)
        # As TEXT, not as an attribute: `.ocu-gate.unknown` is a legitimate
        # CSS class for a component with no row, and a blanket search for
        # the word matches it. What must never appear is the word rendered
        # where a value belongs.
        import re as _re
        rendered = _re.findall(r">\s*unknown\s*<", body, _re.I)
        self.assertEqual(rendered, [],
                         "the literal 'unknown' was rendered as a value; it "
                         "reads like data, and an em dash does not")

    def test_it_says_it_cannot_know_whether_the_commit_is_current(self):
        """The image has no git and no guaranteed network. It knows what it
        was built FROM and nothing else — and the caveat has to say so, or
        a fresh-looking sha reads as 'up to date'."""
        from dashboard.oculus import oculus
        forge = next(c for c in oculus()["cycles"] if c["key"] == "forge")
        self.assertIn("ne peut pas savoir", forge["caveat"])
