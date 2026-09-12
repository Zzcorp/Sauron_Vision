"""Every gated task must have a switch that exists (2026-09-13).

`core.task_gate.guarded_task(key)` asks `is_component_enabled(key)`, and
that function returns **False for a key with no row** — a deliberate,
correct fail-closed default. The consequence nobody had guarded: a task
decorated with a key that was never seeded is not "on by default", it is
OFF FOREVER, and it says so once per run at INFO:

    [GATE] Component pipeline_alerts disabled — skipping

On the live box on 2026-09-13 the registry held 51 components and three
guarded keys had no row among them: `pipeline_alerts`, `pipeline_digest`
and `agent_commentator`. Price alerts had never been checked. The 07:00
and 17:00 UTC digests had never been sent. The daily commentary had never
been written. Every one of them had a beat entry firing on schedule into
a gate that dropped it, and the platform reported nothing wrong because
nothing WAS wrong by its own lights — the switch was off, as the switch
for a missing row always is.

The old comment on RETIRED_COMPONENT_KEYS described those three as
"admin-created by hand". A key whose existence depends on somebody
remembering to create it is a key that will be missing, and this test is
the cheaper answer: the registry is now the single list, and a new
`@guarded_task("...")` whose key is not in it fails here rather than in
production silence months later.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import TestCase

from core.platform_control import (DEFAULT_COMPONENTS, PlatformComponent,
                                   is_component_enabled, seed_components)

#: Directories that are not this project's source.
SKIP = {".git", ".venv", "venv", "__pycache__", "staticfiles", "static",
        "node_modules", ".pytest_cache", "test_backups", "migrations"}

GUARD_RE = re.compile(r"""guarded_task\(\s*["']([A-Za-z0-9_]+)["']""")


def _python_files():
    root = Path(settings.BASE_DIR)
    for path in root.rglob("*.py"):
        if any(part in SKIP for part in path.relative_to(root).parts):
            continue
        yield path


def _guard_keys():
    """Every key passed to guarded_task anywhere in the project."""
    found = {}
    for path in _python_files():
        text = path.read_text(encoding="utf-8", errors="replace")
        for key in GUARD_RE.findall(text):
            found.setdefault(key, []).append(str(path.relative_to(settings.BASE_DIR)))
    return found


class GuardedTaskKeysAreRegisteredTests(TestCase):

    def test_every_guarded_task_key_has_a_row_in_the_registry(self):
        """The one that would have caught it. A guarded key with no row is
        a task that never runs, and the only symptom is an INFO line."""
        declared = {c["key"] for c in DEFAULT_COMPONENTS}
        used = _guard_keys()
        self.assertTrue(used, "no guarded_task calls found — the regex or "
                              "the skip list is wrong, not the codebase")
        missing = {k: v for k, v in used.items() if k not in declared}
        self.assertEqual(
            missing, {},
            "these guarded_task keys have no row in DEFAULT_COMPONENTS, so "
            "is_component_enabled returns False and the task is skipped on "
            "every run, forever. Add a row (is_enabled defaults to False, "
            "so it arrives OFF) rather than deleting this assertion.")

    def test_a_missing_row_reads_as_disabled_not_as_enabled(self):
        """The behaviour the test above exists because of. Fail-closed is
        right; it is the SILENCE that was wrong."""
        self.assertFalse(PlatformComponent.objects.filter(
            key="definitely_not_a_component").exists())
        self.assertFalse(is_component_enabled("definitely_not_a_component"))

    def test_the_three_that_were_missing_now_seed_and_arrive_off(self):
        """pipeline_digest turning itself on during a deploy would start
        SENDING messages outward on a schedule nobody chose. Every newly
        seeded component must arrive OFF and wait for an operator."""
        seed_components()
        for key in ("pipeline_alerts", "pipeline_digest", "agent_commentator"):
            row = PlatformComponent.objects.filter(key=key).first()
            self.assertIsNotNone(row, f"{key} is not seeded")
            self.assertFalse(
                row.is_enabled,
                f"{key} seeded ON — a deploy must never start a component "
                f"that sends messages or spends on models")
            self.assertFalse(is_component_enabled(key))

    def test_seeding_twice_changes_nothing(self):
        """seed_components runs on every deploy. It must not resurrect a
        switch the operator turned off."""
        seed_components()
        row = PlatformComponent.objects.get(key="pipeline_alerts")
        row.is_enabled = True
        row.save(update_fields=["is_enabled"])

        seed_components()
        self.assertTrue(
            PlatformComponent.objects.get(key="pipeline_alerts").is_enabled,
            "a re-seed reset an operator's choice — get_or_create must not "
            "write defaults over an existing row")

    def test_the_registry_has_no_duplicate_keys(self):
        keys = [c["key"] for c in DEFAULT_COMPONENTS]
        self.assertEqual(len(keys), len(set(keys)),
                         "a duplicated key makes the second row unreachable")

    def test_every_declared_component_has_a_valid_category(self):
        valid = {c[0] for c in PlatformComponent.CATEGORY_CHOICES}
        for comp in DEFAULT_COMPONENTS:
            self.assertIn(comp["category"], valid,
                          f"{comp['key']} has category {comp['category']!r}, "
                          f"which the model does not accept")

    def test_descriptions_fit_the_column(self):
        """A 300-char CharField on Postgres refuses a longer string; SQLite
        does not, so the suite would pass and the deploy would fail."""
        limit = PlatformComponent._meta.get_field("description").max_length
        for comp in DEFAULT_COMPONENTS:
            self.assertLessEqual(
                len(comp.get("description", "")), limit,
                f"{comp['key']}'s description is longer than {limit} chars")
