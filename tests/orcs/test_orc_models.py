"""THE ORCS' TABLES (spec §10.1, §10.7): one migration, reversible, only
the tables O1 writes, and the constraints that make an idea one idea.

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
#: The tables only O2 writes ship in O2's own migration (§10.7).
O2_TABLES = {"OrcIntent", "OrcActionGrade", "Captain", "CaptainOrder",
             "OrcWave", "OrcBattle", "OrcLesson", "OrcWeapon",
             "OrcTierGrade", "OrcTemperamentGrade"}


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

    def test_makemigrations_finds_nothing_left(self):
        out = StringIO()
        try:
            call_command("makemigrations", "bot_program", "--check",
                         "--dry-run", stdout=out, verbosity=0)
        except SystemExit as e:  # --check exits 1 when a migration is missing
            self.fail(f"makemigrations --check found changes: "
                      f"{out.getvalue()} (exit {e.code})")


class TheTablesTests(SimpleTestCase):

    def test_the_tables_are_the_ones_o1_writes(self):
        from bot_program.orcs import models as m
        defined = {name for name in dir(m)
                   if isinstance(getattr(m, name), type)
                   and getattr(getattr(m, name), "_meta", None) is not None
                   and getattr(m, name).__module__ == m.__name__}
        self.assertEqual(defined, O1_TABLES)
        self.assertFalse(defined & O2_TABLES)

    def test_app_label_is_bot_program(self):
        from django.apps import apps
        for name in O1_TABLES:
            with self.subTest(name):
                model = apps.get_model("bot_program", name)
                self.assertEqual(model._meta.app_label, "bot_program")
                self.assertEqual(model.__module__, "bot_program.orcs.models")

    def test_no_status_or_kind_column_carries_choices(self):
        from django.apps import apps
        for name in O1_TABLES:
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
