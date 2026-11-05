"""THE ORCS' TABLES (spec §10.1, §10.7): one migration, reversible, only
the tables O1 writes, and the constraints that make an idea one idea.

O2a (2026-11-05, the O2 spec §1.1.2): its own migration, right after the
tree's latest, adds the proposals' table (OrcIntent, moved out of the O2
set on purpose), OrcWake.queued_at and the claim's index; still no
`choices`, and no money column on the new table.

Run with:  python manage.py test tests.orcs.test_orc_models
"""
from io import StringIO

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from tests.orcs.helpers import _config, _row, _user

O1_TABLES = {"OrcSeat", "Orc", "OrcLeg", "OrcJournal", "OrcWake", "OrcTrack",
             "OrcGrade", "OrcSetting", "OrcDossierBlock", "OrcDayBaseline",
             "OrcDrum"}
#: O2a's own table (the O2 spec §1.1.2): one row per proposal.
O2A_TABLES = {"OrcIntent"}
#: The tables only later O2 commits write ship in their own migrations.
O2_TABLES = {"OrcActionGrade", "Captain", "CaptainOrder", "OrcWave",
             "OrcBattle", "OrcLesson", "OrcWeapon", "OrcTierGrade",
             "OrcTemperamentGrade"}
#: Every table the package defines today.
DEFINED = O1_TABLES | O2A_TABLES


class TheMigrationTests(TestCase):

    def test_the_migration_is_present_reversible_and_clean(self):
        from importlib import import_module

        from django.db import migrations
        mod = import_module("bot_program.migrations.0044_orcs")
        mig = mod.Migration
        self.assertIn(("bot_program", "0043_venue_split"), mig.dependencies)
        others = [d for d in mig.dependencies if d[0] == "bot_program"]
        self.assertEqual(others, [("bot_program", "0043_venue_split")],
                         "one migration, right after the tree's latest")
        allowed = (migrations.CreateModel, migrations.AddIndex,
                   migrations.AddConstraint, migrations.AlterUniqueTogether,
                   migrations.AddField)
        for op in mig.operations:
            self.assertIsInstance(op, allowed, type(op).__name__)
            self.assertTrue(op.reversible, type(op).__name__)
        created = {op.name for op in mig.operations
                   if isinstance(op, migrations.CreateModel)}
        self.assertEqual(created, O1_TABLES)

    def test_o2a_ships_its_own_migration_right_after_the_trees_latest(self):
        """O2a (2026-11-05): one migration right after the tree's latest
        at build time (0048), four kinds of operation only, each
        reversible: OrcIntent, OrcWake.queued_at and the claim's index."""
        from importlib import import_module

        from django.db import migrations
        mig = import_module("bot_program.migrations.0049_orcs_o2a").Migration
        others = [d for d in mig.dependencies if d[0] == "bot_program"]
        self.assertEqual(others, [("bot_program", "0048_short_proofs_demo")],
                         "one migration, right after the tree's latest")
        allowed = (migrations.CreateModel, migrations.AddField,
                   migrations.AddIndex, migrations.AddConstraint)
        for op in mig.operations:
            self.assertIsInstance(op, allowed, type(op).__name__)
            self.assertTrue(op.reversible, type(op).__name__)
        created = {op.name for op in mig.operations
                   if isinstance(op, migrations.CreateModel)}
        self.assertEqual(created, O2A_TABLES)
        added = {(op.model_name, op.name) for op in mig.operations
                 if isinstance(op, migrations.AddField)}
        self.assertEqual(added, {("orcwake", "queued_at")})
        indexed = {(op.model_name, tuple(op.index.fields))
                   for op in mig.operations
                   if isinstance(op, migrations.AddIndex)}
        self.assertIn(("orcwake", ("status", "-priority", "queued_at")),
                      indexed, "the claim's order (A.14, A.18)")

    def test_makemigrations_finds_nothing_left(self):
        out = StringIO()
        try:
            call_command("makemigrations", "bot_program", "--check",
                         "--dry-run", stdout=out, verbosity=0)
        except SystemExit as e:  # --check exits 1 when a migration is missing
            self.fail(f"makemigrations --check found changes: "
                      f"{out.getvalue()} (exit {e.code})")


class TheTablesTests(SimpleTestCase):

    def test_the_tables_are_the_ones_o1_and_o2a_write(self):
        """O1's tables and O2a's OrcIntent (changed on purpose on
        2026-11-05: OrcIntent left the O2 set with O2a's migration)."""
        from bot_program.orcs import models as m
        defined = {name for name in dir(m)
                   if isinstance(getattr(m, name), type)
                   and getattr(getattr(m, name), "_meta", None) is not None
                   and getattr(m, name).__module__ == m.__name__}
        self.assertEqual(defined, DEFINED)
        self.assertFalse(defined & O2_TABLES)

    def test_app_label_is_bot_program(self):
        from django.apps import apps
        for name in DEFINED:
            with self.subTest(name):
                model = apps.get_model("bot_program", name)
                self.assertEqual(model._meta.app_label, "bot_program")
                self.assertEqual(model.__module__, "bot_program.orcs.models")

    def test_no_status_or_kind_column_carries_choices(self):
        from django.apps import apps
        for name in DEFINED:
            for f in apps.get_model("bot_program", name)._meta.concrete_fields:
                with self.subTest(model=name, field=f.name):
                    self.assertFalse(f.choices)


class TheConstraintTests(TestCase):

    def setUp(self):
        from bot_program.orcs.models import OrcSeat
        self.user = _user("orc_models")
        self.cfg = _config(self.user)
        self.seat = OrcSeat.objects.create(venue="paper",
                                           asset_class="crypto")

    def _orc(self, row):
        from bot_program.orcs.models import Orc
        return Orc.objects.create(seat=self.seat, user=self.user,
                                  config=self.cfg, root_trade=row,
                                  symbol=row.symbol, side=row.side,
                                  asset_class=row.asset_class)

    def test_one_orc_per_root_and_one_idea_per_leg(self):
        from bot_program.orcs.models import OrcLeg
        row = _row(self.cfg)
        orc = self._orc(row)
        OrcLeg.objects.create(orc=orc, trade=row, kind="root", seq=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self._orc(row)
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrcLeg.objects.create(orc=orc, trade=row, kind="add", seq=2)
        other = _row(self.cfg, symbol="ETHUSD")
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrcLeg.objects.create(orc=orc, trade=other, kind="add", seq=1)
        from bot_program.models import AssetBotTrade
        fresh = AssetBotTrade.objects.get(pk=row.pk)
        self.assertEqual(fresh.orc, orc)
        self.assertEqual(fresh.orc_leg.orc, orc)

    def test_one_pending_wake_per_dedupe_key(self):
        from bot_program.orcs.models import OrcWake
        orc = self._orc(_row(self.cfg))
        OrcWake.objects.create(orc=orc, dedupe_key="orc1:w2", status="pending")
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrcWake.objects.create(orc=orc, dedupe_key="orc1:w2",
                                   status="pending")
        OrcWake.objects.create(orc=orc, dedupe_key="orc1:w2", status="done")
        OrcWake.objects.create(orc=orc, dedupe_key="orc1:w2", status="quiet")
        self.assertEqual(OrcWake.objects.filter(dedupe_key="orc1:w2").count(),
                         3)

    def test_one_seat_per_venue_class_and_rule_key(self):
        from bot_program.orcs.models import OrcSeat
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrcSeat.objects.create(venue="paper", asset_class="crypto")
        OrcSeat.objects.create(venue="live", asset_class="crypto")
        OrcSeat.objects.create(venue="paper", asset_class="crypto",
                               rule_key="manual_take")

    def test_the_setting_reads_its_default(self):
        from bot_program.orcs.models import OrcSetting
        self.assertEqual(OrcSetting.get("max_paper_orcs", 10), 10)
        OrcSetting.objects.create(key="max_paper_orcs", value=3)
        self.assertEqual(OrcSetting.get("max_paper_orcs", 10), 3)


class TheIntentTableTests(SimpleTestCase):
    """OrcIntent (the O2 spec §1.1.2 item 1, 2026-11-05): one row per
    proposal that is not a hold, every column of the spec at its type and
    size, its two indexes, and no money column: R and prices only. Its
    allowed values are tuples in constants.py (A.6)."""

    #: name -> (internal type, max_length, null)
    COLUMNS = {
        "orc": ("ForeignKey", None, False),
        "wake": ("ForeignKey", None, True),
        "decision": ("ForeignKey", None, True),
        "kind": ("CharField", 16, False),
        "candidate": ("CharField", 16, False),
        "level_id": ("CharField", 24, False),
        "level": ("JSONField", None, False),
        "would_stop": ("DecimalField", None, True),
        "event_id": ("CharField", 16, False),
        "share": ("FloatField", None, True),
        "facts_cited": ("JSONField", None, False),
        "mode": ("CharField", 10, False),
        "rule": ("CharField", 16, False),
        "officer": ("JSONField", None, False),
        "status": ("CharField", 12, False),
        "why": ("CharField", 200, False),
        "created_at": ("DateTimeField", None, False),
        "expires_at": ("DateTimeField", None, True),
        "applied_at": ("DateTimeField", None, True),
        "applied_price": ("DecimalField", None, True),
        "applied_r": ("FloatField", None, True),
        "wave_id": ("CharField", 40, False),
        "rung": ("CharField", 4, False),
        "s_version": ("CharField", 8, False),
        "schema_version": ("CharField", 8, False),
    }

    def _model(self):
        from django.apps import apps
        return apps.get_model("bot_program", "OrcIntent")

    def test_every_column_of_the_spec_at_its_type(self):
        fields = {f.name: f for f in self._model()._meta.concrete_fields
                  if not f.primary_key}
        self.assertEqual(set(fields), set(self.COLUMNS))
        for name, (kind, size, null) in self.COLUMNS.items():
            f = fields[name]
            with self.subTest(name):
                self.assertEqual(f.get_internal_type(), kind)
                self.assertEqual(f.null, null)
                if size is not None:
                    self.assertEqual(f.max_length, size)
                if kind == "DecimalField":
                    self.assertEqual((f.max_digits, f.decimal_places), (18, 8))
        from django.db import models
        rel = {f.name: (f.related_model.__name__, f.remote_field.on_delete)
               for f in fields.values() if f.is_relation}
        self.assertEqual(rel, {"orc": ("Orc", models.CASCADE),
                               "wake": ("OrcWake", models.SET_NULL),
                               "decision": ("OrcJournal", models.SET_NULL)})
        self.assertTrue(fields["created_at"].auto_now_add)
        self.assertEqual(fields["level"].default, dict)
        self.assertEqual(fields["officer"].default, dict)
        self.assertEqual(fields["facts_cited"].default, list)

    def test_no_money_column_r_and_prices_only(self):
        fields = self._model()._meta.concrete_fields
        for f in fields:
            with self.subTest(f.name):
                for word in ("usd", "money", "pnl", "cost", "balance",
                             "amount", "equity", "notional", "qty"):
                    self.assertNotIn(word, f.name)
        self.assertEqual({f.name for f in fields
                          if f.get_internal_type() == "DecimalField"},
                         {"would_stop", "applied_price"},
                         "the would-be stop and the applied price: prices")

    def test_the_two_indexes(self):
        got = {tuple(i.fields) for i in self._model()._meta.indexes}
        self.assertEqual(got, {("orc", "-created_at"), ("status",)})

    def test_the_wake_keeps_its_first_send(self):
        """OrcWake.queued_at (§1.1.2 item 2): null until admission, set
        once [P9]; the claim's index orders by it (item 3)."""
        from bot_program.orcs.models import OrcWake
        f = OrcWake._meta.get_field("queued_at")
        self.assertEqual((f.get_internal_type(), f.null),
                         ("DateTimeField", True))
        self.assertIn(("status", "-priority", "queued_at"),
                      {tuple(i.fields) for i in OrcWake._meta.indexes})

    def test_the_allowed_values_are_tuples(self):
        """A.6: the intent's kinds, statuses, expiry codes and modes live
        in constants.py, never as `choices`."""
        from bot_program.orcs import constants as C
        self.assertEqual(C.INTENT_KINDS, ("tighten", "trim", "exit",
                                          "lock_waive", "add"))
        self.assertEqual(C.INTENT_STATUSES, ("queued", "simulated",
                                             "expired", "recorded",
                                             "refused"))
        self.assertEqual(C.INTENT_EXPIRY_CODES, ("ttl", "moved",
                                                 "row_closed", "arm_closed"))
        self.assertEqual(C.INTENT_MODES, (C.MODE_SHADOW, C.MODE_REFUSED))
        self.assertTrue(set(C.INTENT_MODES) <= set(C.MODES))
        model = self._model()
        for name, values in (("kind", C.INTENT_KINDS),
                             ("status", C.INTENT_STATUSES),
                             ("mode", C.INTENT_MODES),
                             ("rule", C.INTENT_EXPIRY_CODES)):
            with self.subTest(name):
                self.assertLessEqual(max(map(len, values)),
                                     model._meta.get_field(name).max_length)
