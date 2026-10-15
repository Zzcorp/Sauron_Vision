"""The Lore, part 1: the library itself (2026-10-14).

Import and export, the validator (one code at a time), the models. Every
entry here is a neutral stand-in built in code; no seed text is in git.

Run with:  python manage.py test tests.test_lore_library
"""
import copy
import json
import os
import tempfile
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import CommandError, call_command
from django.test import SimpleTestCase, TestCase

REPO = Path(__file__).resolve().parent.parent

#: A summary of five plain sentences, in our own words.
SUMMARY = ("A stand-in entry written for the tests. It follows the price "
           "when it has moved one way for a while. It sells when the move "
           "turns against it. It is reference data and nothing more. Five "
           "sentences are enough here.")


def seed_entry(slug="example-trend-rule", kind="strategy", **over):
    """One entry in the catalogue schema, overlay keys inline."""
    d = {
        "slug": slug, "kind": kind, "title": "Example trend rule",
        "summary": SUMMARY,
        "mechanism": "Buy after a run of higher closes and sell after a run "
                     "of lower closes, sized by recent volatility.",
        "works_when": {"regimes": "Long, persistent moves over weeks.",
                       "asset_classes": ["index futures", "FX"]},
        "fails_when": [{"how": "Sharp turns inside the lookback window.",
                        "episode": "A stand-in episode.", "src": [0]}],
        "evidence": [{"title": "A stand-in paper", "by": "Example Author",
                      "url": "https://example.org/paper", "date": "2012-05",
                      "type": "paper", "note": "A note in our words.",
                      "date_kind": "published"}],
        "documented": [{"claim": "The stand-in effect was positive in the "
                                 "sample.", "src": [0]}],
        "reputed": [],
        "evidence_grade": "moderate",
        "related": [],
        "small_account": {"can": "Run it slowly on a few markets.",
                          "cannot": "Cannot diversify across sixty markets."},
        "sauron_code": [],
        "tags": ["trend", "stand-in"],
        "accessed": "2026-10-09",
        "asset_classes": ["index", "forex"],
        "regimes_works": ["trending"],
        "regimes_breaks": ["mean_reverting"],
        "horizons": ["weeks"],
        "families": [],
    }
    d.update(over)
    return d


def import_dicts(*dicts, **kw):
    from lore.importer import import_entries
    return import_entries(list(dicts), {}, **kw)


def make_entry(**over):
    """Import one stand-in and return its row."""
    from lore.models import LoreEntry
    d = seed_entry(**over)
    report = import_dicts(d)
    assert not report.refused, report.refused
    return LoreEntry.objects.get(slug=d["slug"])


def staff(name="lore_staff", *, superuser=True):
    if superuser:
        return User.objects.create_superuser(name, f"{name}@x.io", "x")
    u = User.objects.create_user(name, f"{name}@x.io", "x")
    u.is_staff = True
    u.save()
    return u


def review(entry, user=None):
    from lore import curate
    user = user or staff(f"rev_{entry.slug[:20]}")
    checks = {k: True for k, _ in curate.REVIEW_CHECKS}
    return curate.mark_reviewed(entry, user, checks=checks)


def switch(key, on=True):
    from core.platform_control import PlatformComponent
    row, _ = PlatformComponent.objects.get_or_create(
        key=key, defaults={"name": key, "category": "agent"})
    row.is_enabled = on
    row.save()
    return row


# ── Import and export ─────────────────────────────────────────────────────

class ImportTests(TestCase):

    def test_a_seed_shaped_entry_imports_as_a_draft(self):
        from lore.models import LoreClaim, LoreRevision, LoreSource
        e = make_entry()
        self.assertEqual(e.status, "draft")
        self.assertEqual(e.origin, "world")
        self.assertEqual(e.proposed_by, "seed")
        self.assertEqual(e.version, 1)
        self.assertEqual(e.classes, ["index", "forex"])
        self.assertEqual(e.regimes_works, ["trending"])
        self.assertEqual(e.horizons, ["weeks"])
        self.assertEqual(e.tags_flat, "|trend|stand-in|")
        self.assertEqual(LoreSource.objects.filter(entry=e).count(), 1)
        self.assertEqual(LoreSource.objects.get(entry=e).found_via,
                         "search_summary")
        self.assertEqual(LoreClaim.objects.filter(entry=e, side="documented")
                         .get().sources, [1])
        self.assertEqual(LoreRevision.objects.filter(entry=e, via="import")
                         .count(), 1)
        self.assertTrue(e.content_sha and e.content_sha == e.imported_sha)
        self.assertIn("stand-in paper", e.search_text)

    def test_import_is_idempotent_by_slug(self):
        from lore.models import LoreEntry
        d = seed_entry()
        import_dicts(d)
        report = import_dicts(d)
        self.assertEqual(report.same, ["example-trend-rule"])
        self.assertEqual(LoreEntry.objects.count(), 1)
        self.assertEqual(LoreEntry.objects.get().version, 1)

    def test_an_untouched_entry_updates(self):
        from lore.models import LoreEntry
        d = seed_entry()
        import_dicts(d)
        d2 = dict(d, mechanism="A changed mechanism, still in our words.")
        report = import_dicts(d2)
        self.assertEqual(report.updated, ["example-trend-rule"])
        e = LoreEntry.objects.get()
        self.assertEqual(e.version, 2)
        self.assertEqual(e.mechanism, d2["mechanism"])
        self.assertEqual(e.content_sha, e.imported_sha)
        self.assertEqual(e.revisions.count(), 2)

    def test_a_staff_edit_is_kept(self):
        from lore import curate
        from lore.models import LoreEntry
        d = seed_entry()
        import_dicts(d)
        e = LoreEntry.objects.get()
        e.summary = SUMMARY + " A sixth sentence a staff member added."
        e.save()
        curate.content_changed_in_admin(e)
        self.assertNotEqual(e.content_sha, e.imported_sha)
        report = import_dicts(dict(d, mechanism="The file moved too."))
        self.assertEqual(report.kept, ["example-trend-rule"])
        e.refresh_from_db()
        self.assertIn("sixth sentence", e.summary)
        self.assertNotEqual(e.mechanism, "The file moved too.")
        self.assertIn("kept     example-trend-rule", "\n".join(report.lines()))

    def test_a_reviewed_entry_whose_text_changed_returns_to_draft(self):
        from lore.models import LoreEntry
        d = seed_entry()
        import_dicts(d)
        review(LoreEntry.objects.get())
        self.assertEqual(LoreEntry.objects.get().status, "reviewed")
        import_dicts(dict(d, mechanism="New text under an old review."))
        e = LoreEntry.objects.get()
        self.assertEqual(e.status, "draft")
        self.assertEqual(e.version, 2)

    def test_force_slug_replaces_an_edited_entry(self):
        from lore import curate
        from lore.models import LoreEntry
        d = seed_entry()
        import_dicts(d)
        e = LoreEntry.objects.get()
        e.mechanism = "Edited here."
        e.save()
        curate.content_changed_in_admin(e)
        report = import_dicts(dict(d, mechanism="The file's version."),
                              force_slugs=["example-trend-rule"])
        self.assertEqual(report.updated, ["example-trend-rule"])
        self.assertEqual(LoreEntry.objects.get().mechanism, "The file's version.")

    def test_an_unknown_key_is_refused(self):
        report = import_dicts(seed_entry(stop_pct=2.0))
        self.assertEqual([c for _, c, _ in report.refused], ["V25"])
        self.assertIn('Unknown field "stop_pct"', report.refused[0][2])

    def test_a_source_without_url_or_date_is_refused(self):
        src = {"title": "No link", "by": "Someone", "url": "",
               "date": "", "type": "paper", "note": "", "date_kind": "published"}
        report = import_dicts(seed_entry(evidence=[src]))
        codes = {c for _, c, _ in report.refused}
        self.assertEqual(codes, {"V06"})
        reasons = " ".join(r for _, _, r in report.refused)
        self.assertIn("has no link", reasons)
        self.assertIn("no usable date", reasons)

    def test_a_claim_citing_a_missing_source_is_refused(self):
        report = import_dicts(seed_entry(
            documented=[{"claim": "Cites a source that is not there.",
                         "src": [3]}]))
        self.assertEqual([c for _, c, _ in report.refused], ["V08"])
        self.assertIn("cites S4, which does not exist", report.refused[0][2])

    def test_an_import_cannot_say_a_source_was_opened(self):
        from lore import curate
        from lore.models import LoreEntry, LoreSource
        d = seed_entry()
        d["evidence"] = [dict(d["evidence"][0], found_via="opened")]
        report = import_dicts(d)
        self.assertEqual([c for _, c, _ in report.refused], ["V25"])
        self.assertIn('carries "found_via"', report.refused[0][2])
        self.assertFalse(LoreEntry.objects.exists())
        # Even past the validator, the rows land as search summary only.
        e = make_entry()
        curate.write_rows(e, d)
        src = LoreSource.objects.get(entry=e)
        self.assertEqual(src.found_via, "search_summary")
        self.assertIsNone(src.checked_by)

    def test_an_import_cannot_create_a_sauron_lesson(self):
        report = import_dicts(seed_entry(origin="sauron"))
        self.assertIn("V26", {c for _, c, _ in report.refused})
        from lore.models import LoreEntry
        self.assertFalse(LoreEntry.objects.exists())

    def test_related_links_come_out_two_way(self):
        from lore.models import LoreLink
        a = seed_entry(slug="entry-a", related=["entry-b", "missing-one"])
        b = seed_entry(slug="entry-b", title="Entry b")
        report = import_dicts(a, b)
        self.assertEqual(LoreLink.objects.filter(kind="related").count(), 2)
        self.assertTrue(LoreLink.objects.filter(
            from_entry__slug="entry-a", to_entry__slug="entry-b").exists())
        self.assertTrue(LoreLink.objects.filter(
            from_entry__slug="entry-b", to_entry__slug="entry-a").exists())
        self.assertIn(("entry-a", "related entry missing-one not found"),
                      report.warnings)

    def test_the_overlay_is_applied_and_checked_against_the_registries(self):
        from lore.importer import import_entries
        from lore.models import LoreEntry
        bare = seed_entry()
        for key in ("asset_classes", "regimes_works", "regimes_breaks",
                    "horizons", "families"):
            bare.pop(key)
        overlay = {"example-trend-rule": {
            "asset_classes": ["commodity"], "regimes_works": ["risk_off"],
            "regimes_breaks": [], "horizons": ["months"],
            "families": ["tsmom"]}}
        report = import_entries([bare], overlay)
        self.assertFalse(report.refused)
        e = LoreEntry.objects.get()
        self.assertEqual(e.classes, ["commodity"])
        self.assertEqual(e.regimes_works, ["risk_off"])
        self.assertEqual(e.families, ["tsmom"])
        bad_entry = seed_entry(slug="bad-overlay")
        for key in ("asset_classes", "regimes_works", "regimes_breaks",
                    "horizons", "families"):
            bad_entry.pop(key)
        bad = import_entries([bad_entry],
                             {"bad-overlay": {"families": ["no_such_family"],
                                              "regimes_works": ["sideways"],
                                              "asset_classes": ["tulips"],
                                              "horizons": ["eons"]}})
        self.assertEqual({c for _, c, _ in bad.refused},
                         {"V16", "V17", "V18", "V19"})

    def test_a_dry_run_writes_nothing(self):
        from lore.models import LoreEntry
        report = import_dicts(seed_entry(), dry_run=True)
        self.assertEqual(report.created, ["example-trend-rule"])
        self.assertTrue(report.dry_run)
        self.assertFalse(LoreEntry.objects.exists())
        self.assertIn("Nothing written (dry run).", report.lines())

    def test_export_then_import_round_trips_the_content_sha(self):
        from lore.importer import export_all, import_entries
        from lore.models import LoreEntry
        import_dicts(seed_entry(slug="entry-a", related=["entry-b"]),
                     seed_entry(slug="entry-b", title="Entry b"))
        shas = dict(LoreEntry.objects.values_list("slug", "content_sha"))
        exported = export_all()
        self.assertEqual({d["status"] for d in exported}, {"draft"})
        LoreEntry.objects.all().delete()
        report = import_entries(exported, {})
        self.assertFalse(report.refused, report.refused)
        self.assertEqual(dict(LoreEntry.objects.values_list(
            "slug", "content_sha")), shas)

    def test_the_command_reports_and_exits_non_zero_on_a_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "seed.json"
            path.write_text(json.dumps([seed_entry(),
                                        seed_entry(slug="bad-one",
                                                   evidence_grade="shaky")]))
            out = StringIO()
            with self.assertRaises(CommandError) as ctx:
                call_command("lore", "import", str(tmp), stdout=out)
            text = out.getvalue()
        self.assertIn("created  example-trend-rule (draft)", text)
        self.assertIn("refused  bad-one: V21", text)
        self.assertIn("1 created, 0 updated, 0 kept, 0 unchanged, 1 refused",
                      text)
        self.assertIn("1 entries were refused; the others were imported.",
                      str(ctx.exception))

    def test_the_command_says_when_there_is_no_catalogue(self):
        out = StringIO()
        call_command("lore", "import", "/nonexistent/lore", stdout=out)
        self.assertIn("No catalogue at /nonexistent/lore. Put the files in "
                      "private/lore/ or set LORE_DIR.", out.getvalue())

    def test_export_writes_a_file_the_import_reads(self):
        make_entry()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "export-test.json"
            out = StringIO()
            call_command("lore", "export", str(target), stdout=out)
            self.assertIn(f"Wrote 1 entries to {target}.", out.getvalue())
            data = json.loads(target.read_text())
        self.assertEqual(data[0]["slug"], "example-trend-rule")
        self.assertEqual(data[0]["proposed_by"], "seed")

    def test_check_passes_the_stand_in_and_names_a_drifted_reference(self):
        make_entry(sauron_code=[{"ref": "lore/models.py:1", "note": "the rows"},
                                {"ref": "lore/nowhere.py:3", "note": "gone"}])
        out = StringIO()
        call_command("lore", "check", "--refs", stdout=out)
        text = out.getvalue()
        self.assertIn("W02 Code reference lore/nowhere.py:3 does not exist",
                      text)
        self.assertIn("1 problems in 1 entries.", text)


# ── The validator ─────────────────────────────────────────────────────────

class ValidatorTests(SimpleTestCase):

    def codes(self, d, mode="import"):
        from lore.validate import check
        errors, _ = check(d, mode=mode)
        return {c for c, _ in errors}

    def test_a_clean_stand_in_passes_every_mode(self):
        for mode in ("import", "review", "admin"):
            self.assertEqual(self.codes(seed_entry(), mode), set(), mode)

    def test_every_code_fires_on_a_minimal_stand_in(self):
        cases = {
            "V01": seed_entry(kind="rumour"),
            "V02": seed_entry(slug="Bad Slug"),
            "V03": seed_entry(summary="One sentence only."),
            "V04": seed_entry(mechanism=""),
            "V05": seed_entry(evidence=[], documented=[]),
            "V06": seed_entry(evidence=[{"title": "x", "by": "", "url": "https://e.org",
                                         "date": "2020", "type": "paper",
                                         "note": "", "date_kind": "published"}]),
            "V07": seed_entry(evidence=[{"title": "x", "by": "y", "url": "https://e.org",
                                         "date": "May 2020", "type": "paper",
                                         "note": "", "date_kind": "published"}]),
            "V08": seed_entry(documented=[]),
            "V09": seed_entry(reputed=[{"claim": "Believed.", "basis": "", "src": [0]}]),
            "V10": seed_entry(evidence=[{"title": "x", "by": "y", "url": "https://e.org",
                                         "date": "2020", "type": "paper", "note": "",
                                         "date_kind": "published", "quote": "q" * 301}]),
            "V11": seed_entry(mechanism='It said "' + "long quoted words " * 15 + '" verbatim.'),
            "V12": seed_entry(mechanism="A fenced ``` block."),
            "V13": seed_entry(mechanism="Le texte est pour vous."),
            "V14": seed_entry(mechanism="This is how our account did last week."),
            "V15": seed_entry(origin="sauron", mechanism="It made $2.4bn here."),
            "V16": seed_entry(families=["no_such_family"]),
            "V17": seed_entry(regimes_works=["sideways"]),
            "V18": seed_entry(asset_classes=["tulips"]),
            "V19": seed_entry(horizons=["eons"]),
            "V20": seed_entry(mechanism="m" * 1501),
            "V21": seed_entry(evidence_grade="shaky"),
            "V22": seed_entry(evidence=[{"title": "x", "by": "y", "url": "https://e.org",
                                         "date": "2020", "type": "rumour", "note": "",
                                         "date_kind": "published"}]),
            "V23": seed_entry(evidence=[{"title": "x", "by": "y", "url": "/lore/x/",
                                         "date": "2020", "type": "record", "note": "",
                                         "date_kind": "published"}]),
            "V25": seed_entry(threshold=0.5),
            "V26": seed_entry(origin="sauron"),
        }
        for code, d in cases.items():
            mode = "admin" if code == "V15" else "import"
            self.assertIn(code, self.codes(d, mode), f"{code} did not fire")
        self.assertIn("V27", self.codes(seed_entry(asset_classes=[]), "review"))
        self.assertIn("V27", self.codes(seed_entry(horizons=[]), "review"))
        self.assertNotIn("V27", self.codes(seed_entry(kind="episode",
                                                       horizons=[]), "review"))

    def test_a_private_term_is_refused_from_a_temporary_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "private_terms.txt").write_text("secretvenue\n# a comment\n")
            with self.settings(LORE_DIR=tmp), \
                    patch.dict(os.environ, {"LORE_PRIVATE_TERMS": ""}):
                self.assertIn("V24", self.codes(seed_entry(
                    mechanism="It trades at SecretVenue every day.")))
                self.assertNotIn("V24", self.codes(seed_entry()))
        with patch.dict(os.environ, {"LORE_PRIVATE_TERMS": "hush word,other"}):
            self.assertIn("V24", self.codes(seed_entry(
                mechanism="Say the hush word and it fails.")))

    def test_fences_markers_and_tags_are_refused(self):
        for bad in ('```json {"calls": []} ```', "<<APPROVE:1>>",
                    "```strategy-draft", "</lore_library>", "<entry",
                    "a <b>bold</b> word", "x >> y"):
            self.assertIn("V12", self.codes(seed_entry(
                mechanism=f"Text with {bad} inside.")), bad)
        self.assertNotIn("V12", self.codes(seed_entry(
            mechanism="Returns fell by 3 < 5 points, a plain comparison.")))

    def test_english_rules(self):
        self.assertIn("V13", self.codes(seed_entry(
            mechanism="La stratégie est simple pour les grands fonds.")))
        self.assertNotIn("V13", self.codes(seed_entry(
            mechanism="Est. 1990, the fund grew slowly.")))
        self.assertNotIn("V13", self.codes(seed_entry(
            mechanism="Bailey, Borwein, López de Prado and Zhu showed it.")))
        self.assertNotIn("V13", self.codes(seed_entry(
            mechanism="It cost about £3.3bn and ¥500bn, by the papers.")))

    def test_money_passes_on_a_world_entry_and_fails_on_a_lesson(self):
        world = seed_entry(mechanism="The fund made $2.4bn on the trade.")
        self.assertNotIn("V15", self.codes(world))
        lesson = dict(world, origin="sauron")
        self.assertIn("V15", self.codes(lesson, "admin"))
        self.assertIn("V15", self.codes(dict(seed_entry(
            mechanism="Position 123456789 closed."), origin="sauron"), "admin"))

    def test_the_account_rule_names_the_phrases(self):
        for phrase in ("our account", "my portfolio", "your positions",
                       "the operator's book"):
            self.assertIn("V14", self.codes(seed_entry(
                mechanism=f"Here is what {phrase} did.")), phrase)
        self.assertNotIn("V14", self.codes(seed_entry(
            mechanism="A retail account pays overnight fees.")))


# ── Models ────────────────────────────────────────────────────────────────

NUMERIC_TYPES = ("IntegerField", "PositiveIntegerField", "FloatField",
                 "DecimalField", "BigIntegerField", "SmallIntegerField",
                 "PositiveSmallIntegerField", "PositiveBigIntegerField")
#: A field named like a parameter is a field some code could read as one.
PARAMETER_WORDS = ("stop", "size", "threshold", "leverage", "limit", "param",
                   "target", "weight", "ratio", "pct", "percent", "max_",
                   "min_", "cap_", "qty", "quantity", "amount")


class ModelTests(TestCase):

    def test_no_numeric_field_except_version_and_position(self):
        from lore import models as m
        for model in (m.LoreEntry, m.LoreSource, m.LoreClaim, m.LoreLink,
                      m.LoreRevision):
            for f in model._meta.get_fields():
                kind = f.get_internal_type() if hasattr(f, "get_internal_type") else ""
                if kind in NUMERIC_TYPES and not getattr(f, "primary_key", False):
                    self.assertIn(f.name, ("version", "position"),
                                  f"{model.__name__}.{f.name} is numeric")
                for word in PARAMETER_WORDS:
                    self.assertNotIn(word, f.name,
                                     f"{model.__name__}.{f.name} reads like a parameter")
        for f in m.LoreRead._meta.get_fields():
            for word in PARAMETER_WORDS:
                self.assertNotIn(word, f.name, f"LoreRead.{f.name}")

    def test_the_migration_is_in_step_with_the_models(self):
        out = StringIO()
        call_command("makemigrations", "lore", "--check", "--dry-run",
                     stdout=out)
        self.assertIn("No changes detected", out.getvalue())

    def test_the_migration_holds_no_data_and_no_vendor_sql(self):
        src = (REPO / "lore" / "migrations" / "0001_initial.py").read_text()
        self.assertNotIn("RunPython", src)
        self.assertNotIn("RunSQL", src)

    def test_review_permission_and_choices(self):
        from lore.models import LoreEntry
        perms = {p[0] for p in LoreEntry._meta.permissions}
        self.assertIn("review_loreentry", perms)
        self.assertEqual([k for k, _ in LoreEntry._meta.get_field("audience").choices],
                         ["staff"])

    def test_vocabularies_come_from_the_platform(self):
        from backtester.proving.families import FAMILIES
        from brain.models import BrainReport
        from core.constants import AssetClass
        from lore import constants as C
        self.assertEqual(set(C.regime_keys()),
                         {k for k, _ in BrainReport.REGIME_CHOICES} - {"unknown"})
        self.assertEqual(set(C.ASSET_CLASS_KEYS), {k for k, _ in AssetClass.CHOICES})
        self.assertEqual(set(C.family_keys()), set(FAMILIES))

    def test_the_flat_columns_are_normalised_on_every_save(self):
        """An admin edit types the columns as raw text; search filters on
        `|x|` with a LIKE that is case-sensitive on PostgreSQL."""
        from lore.models import LoreEntry
        from lore.search import base_queryset
        e = make_entry()
        e.classes_flat = "Forex|INDEX"
        e.regimes_works_flat = "trending|mean_reverting"
        e.tags_flat = "|Momentum| Trend |"
        e.save()
        e.refresh_from_db()
        self.assertEqual(e.classes_flat, "|forex|index|")
        self.assertEqual(e.regimes_works_flat, "|trending|mean_reverting|")
        self.assertEqual(e.tags_flat, "|momentum|trend|")
        self.assertEqual([x.slug for x in base_queryset(
            classes=("forex",), statuses=("draft",))], [e.slug])
        self.assertEqual([x.slug for x in base_queryset(
            regimes=("trending",), statuses=("draft",))], [e.slug])
        self.assertEqual([x.slug for x in base_queryset(
            tags=("momentum",), statuses=("draft",))], [e.slug])
        e.horizons_flat = ""
        e.save()
        self.assertEqual(LoreEntry.objects.get(pk=e.pk).horizons_flat, "")

    def test_content_sha_ignores_state_and_links_but_not_text(self):
        from lore import curate
        d = seed_entry()
        base = curate.content_sha(d)
        self.assertEqual(curate.content_sha(dict(d, status="reviewed",
                                                 related=["other"])), base)
        self.assertNotEqual(curate.content_sha(dict(d, title="Other title")),
                            base)
        self.assertEqual(curate.content_sha(copy.deepcopy(d)), base)
