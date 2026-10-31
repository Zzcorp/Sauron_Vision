"""The Lore, part 5: the fences (2026-10-14).

Who imports the library, and who never may; where a reviewed entry's words
must never appear. The completeness idiom of tests/test_llm_ledger_truth.py:
a new reader fails the suite until it is listed here and in POLICY.

Run with:  python manage.py test tests.test_lore_fences
"""
import re
import shutil
import subprocess
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase

from tests.test_lore_library import make_entry, review, staff

REPO = Path(__file__).resolve().parent.parent

#: The readers, agent name to the one file that imports the library for it.
READERS = {
    "research": "brain/research_agent.py",
    "strategist": "brain/strategist.py",
}

#: Never readers: a size, a gate or a binding vote sits one hop away.
#: (ai_agents/consensus.py left the list with the module, removed unused
#: on 2026-10-31.)
NEVER = ("bot_program", "portfolio", "brain/synthesizer.py", "brain/horizon.py",
         "ai_agents/agents/trade_debate.py", "ai_agents/agents/weekly_reviewer.py",
         "ai_agents/tasks.py", "ai_agents/next_steps.py")

SCAN_DIRS = ("ai_agents", "brain", "dashboard", "bot_program", "core", "signals",
             "portfolio", "market_data", "scraping", "alerts", "strategies",
             "backtester", "instruments", "indicators", "config")

IMPORT_RE = re.compile(r"^\s*(?:from\s+lore(?:\.|\s)|import\s+lore\b)", re.M)

#: The canary, in the idiom of tests/test_the_book.py: a title no page may
#: carry but the library's own.
CANARY_TITLE = "Canary private phrase of the library"


def _sources():
    for d in SCAN_DIRS:
        for p in (REPO / d).glob("**/*.py"):
            rel = p.relative_to(REPO).as_posix()
            if "/migrations/" in rel:
                continue
            yield rel, p.read_text(encoding="utf-8", errors="replace")


class ImportFenceTests(TestCase):

    def test_only_the_two_readers_import_the_library(self):
        importers = sorted(rel for rel, src in _sources() if IMPORT_RE.search(src))
        self.assertEqual(importers, sorted(READERS.values()))

    def test_the_allowlist_matches_the_policy(self):
        from lore.policy import POLICY
        self.assertEqual(set(POLICY), set(READERS))
        for agent, rel in READERS.items():
            src = (REPO / rel).read_text(encoding="utf-8")
            self.assertIn(f'block_for("{agent}"', src, rel)

    def test_never_readers_do_not_import_the_library(self):
        for rel, src in _sources():
            for never in NEVER:
                if rel == never or rel.startswith(never + "/"):
                    self.assertFalse(IMPORT_RE.search(src), f"{rel} imports lore")

    def test_no_lore_text_reaches_a_prompt_outside_the_read_api(self):
        """Only lore/read.py renders a block; nobody else calls the renderer
        or the search on an agent's behalf."""
        for rel, src in _sources():
            self.assertNotIn("lore.render", src, rel)
            self.assertNotIn("lore.search", src, rel)
            self.assertNotIn("from lore.models", src, rel)

    def test_private_stays_out_of_git(self):
        gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("/private/", gitignore)
        # git itself must ignore the seed's path (exit 0), whether or not
        # the file is there: the library's words never reach the tree.
        if shutil.which("git") is None or not (REPO / ".git").exists():
            self.skipTest("no git checkout here")
        for rel in ("private/lore/seed.json", "private/lore/seed_overlay.json",
                    "private/lore/private_terms.txt"):
            out = subprocess.run(["git", "check-ignore", "-q", "--no-index", rel],
                                 cwd=REPO, capture_output=True)
            self.assertEqual(out.returncode, 0, f"{rel} is not ignored by git")
        # No seed text in the tree: the library's words live outside git.
        for d in ("lore", "templates/lore"):
            for p in (REPO / d).rglob("*"):
                if p.is_file() and p.suffix in (".py", ".html", ".json"):
                    self.assertNotIn("Moskowitz", p.read_text(encoding="utf-8",
                                                               errors="replace"), p)


class CanaryTests(TestCase):

    def setUp(self):
        e = make_entry(slug="example-canary", title=CANARY_TITLE,
                       tags=["canary"])
        review(e)
        self.staff = staff("canary_staff")
        self.plain = User.objects.create_user("canary_plain", "c@x.io", "x")

    def _walk(self, label):
        for url in ("/wall/", "/book/", "/"):
            r = self.client.get(url, follow=True)
            body = r.content.decode(errors="replace")
            self.assertNotIn(CANARY_TITLE, body, f"{label} {url}")
            self.assertNotIn("example-canary", body, f"{label} {url}")
        js = (REPO / "static" / "js" / "sv-gollum.js").read_text(encoding="utf-8")
        self.assertNotIn(CANARY_TITLE, js)
        self.assertNotIn("/lore/", js)

    def test_the_canary_is_absent_for_anonymous_visitors(self):
        self._walk("anonymous")

    def test_the_canary_is_absent_for_staff_too(self):
        self.client.force_login(self.staff)
        self._walk("staff")
        self.client.force_login(self.plain)
        self._walk("plain")

    def test_the_canary_is_on_its_own_page_for_staff(self):
        self.client.force_login(self.staff)
        self.assertIn(CANARY_TITLE,
                      self.client.get("/lore/example-canary/").content.decode())
