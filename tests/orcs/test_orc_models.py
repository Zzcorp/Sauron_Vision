"""THE ORCS' TABLES (spec §10.1, §10.7): one migration, reversible, only
the tables O1 writes, and the constraints that make an idea one idea.

O2a (2026-11-05, the O2 spec §1.1.2): its own migration, right after the
tree's latest, adds the proposals' table (OrcIntent, moved out of the O2
set on purpose), OrcWake.queued_at and the claim's index; still no
`choices`, and no money column on the new table.

O2b (2026-11-06, the O2 spec §1.2.2): its own migration, right after
O2a's, adds the probe pairs' table (OrcTierGrade, moved out of the O2 set
on purpose), one CreateModel, reversible; its allowed values are tuples
in constants.py, never `choices`.

O2c (2026-11-07, the O2 spec §1.3.2): its own migration, right after
O2b's, adds the Captain, its orders in shadow, the drums' waves and the
temperaments' grade (moved out of the O2 set on purpose), and
Orc.temperament: four CreateModel and one AddField, each reversible; its
allowed values are tuples in constants.py, never `choices`; no money
column but a wave's AI spend (USD, staff pages only). Nothing reads the
tables yet.

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
#: O2b's own table (the O2 spec §1.2.2, 2026-11-06): one row per probe
#: pair, moved out of O2_TABLES on purpose.
O2B_TABLES = {"OrcTierGrade"}
#: O2c's own tables (the O2 spec §1.3.2, 2026-11-07): the Captain per
#: (user, class), its orders in shadow, the drums' waves per user and the
#: temperaments' grade, moved out of O2_TABLES on purpose.
O2C_TABLES = {"Captain", "CaptainOrder", "OrcWave", "OrcTemperamentGrade"}
#: The tables only later O2 commits write ship in their own migrations.
O2_TABLES = {"OrcActionGrade", "OrcBattle", "OrcLesson", "OrcWeapon"}
#: Every table the package defines today.
DEFINED = O1_TABLES | O2A_TABLES | O2B_TABLES | O2C_TABLES


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

    def test_o2b_ships_its_own_migration_right_after_o2as(self):
        """O2b (2026-11-06, the O2 spec §1.0 item 4, §1.2.2): one migration
        right after O2a's (0049), one CreateModel, reversible: the probe
        pairs' table, OrcTierGrade."""
        from importlib import import_module

        from django.db import migrations
        mig = import_module("bot_program.migrations.0050_orcs_o2b").Migration
        others = [d for d in mig.dependencies if d[0] == "bot_program"]
        self.assertEqual(others, [("bot_program", "0049_orcs_o2a")],
                         "one migration, right after O2a's")
        for op in mig.operations:
            self.assertIsInstance(op, migrations.CreateModel,
                                  type(op).__name__)
            self.assertTrue(op.reversible, type(op).__name__)
        self.assertEqual({op.name for op in mig.operations}, O2B_TABLES)

    def test_o2c_ships_its_own_migration_right_after_o2bs(self):
        """O2c (2026-11-07, the O2 spec §1.0 item 4, §1.3.2): one migration
        right after O2b's (0050), its only bot_program dependency, with
        four CreateModel (its tables) and one AddField (Orc.temperament),
        each reversible; the field a column of default '' (on PostgreSQL a
        change of the catalogue only, no table rewrite)."""
        from importlib import import_module

        from django.db import migrations
        mig = import_module("bot_program.migrations.0051_orcs_o2c").Migration
        others = [d for d in mig.dependencies if d[0] == "bot_program"]
        self.assertEqual(others, [("bot_program", "0050_orcs_o2b")],
                         "one migration, right after O2b's")
        for op in mig.operations:
            self.assertIsInstance(op, (migrations.CreateModel,
                                       migrations.AddField),
                                  type(op).__name__)
            self.assertTrue(op.reversible, type(op).__name__)
        created = {op.name for op in mig.operations
                   if isinstance(op, migrations.CreateModel)}
        self.assertEqual(created, O2C_TABLES)
        added = {(op.model_name, op.name) for op in mig.operations
                 if isinstance(op, migrations.AddField)}
        self.assertEqual(added, {("orc", "temperament")})
        [field] = [op.field for op in mig.operations
                   if isinstance(op, migrations.AddField)]
        self.assertEqual((field.default, field.null, field.blank,
                          field.max_length), ("", False, True, 16))

    def test_makemigrations_finds_nothing_left(self):
        out = StringIO()
        try:
            call_command("makemigrations", "bot_program", "--check",
                         "--dry-run", stdout=out, verbosity=0)
        except SystemExit as e:  # --check exits 1 when a migration is missing
            self.fail(f"makemigrations --check found changes: "
                      f"{out.getvalue()} (exit {e.code})")


class TheTablesTests(SimpleTestCase):

    def test_the_tables_are_the_ones_o1_o2a_o2b_and_o2c_write(self):
        """O1's tables, O2a's OrcIntent (changed on purpose on 2026-11-05:
        OrcIntent left the O2 set with O2a's migration), O2b's
        OrcTierGrade (changed on purpose on 2026-11-06: it left the O2 set
        with O2b's migration) and O2c's four (changed on purpose on
        2026-11-07: Captain, CaptainOrder, OrcWave and OrcTemperamentGrade
        left the O2 set with O2c's migration)."""
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


class TheTierGradeTableTests(SimpleTestCase):
    """OrcTierGrade (the O2 spec §1.2.2, B.12; O2b, 2026-11-06): one row
    per probe pair, every column of the spec at its type, the costs the
    only money (AI spend in USD, shown on staff pages only), one pair per
    (wake, kind), and its allowed values tuples in constants.py (A.6)."""

    #: name -> (internal type, max_length, null)
    COLUMNS = {
        "wake": ("ForeignKey", None, True),
        "orc": ("ForeignKey", None, False),
        "kind": ("CharField", 8, False),
        "boundary": ("SmallIntegerField", None, True),
        "world": ("CharField", 8, False),
        "routed_rung": ("CharField", 4, False),
        "probe_rung": ("CharField", 4, False),
        "would_rung": ("CharField", 4, False),
        "routed": ("JSONField", None, False),
        "probe": ("JSONField", None, False),
        "agree_action": ("BooleanField", None, False),
        "agree_level": ("BooleanField", None, False),
        "routed_cost_usd": ("DecimalField", None, False),
        "probe_cost_usd": ("DecimalField", None, False),
        "fwd_routed_r": ("FloatField", None, True),
        "fwd_probe_r": ("FloatField", None, True),
        "fwd_at": ("DateTimeField", None, True),
        "block": ("IntegerField", None, False),
        "created_at": ("DateTimeField", None, False),
    }

    def _model(self):
        from django.apps import apps
        return apps.get_model("bot_program", "OrcTierGrade")

    def test_every_column_of_the_spec_at_its_type(self):
        from django.db import models
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
                self.assertFalse(f.choices)
        for name in ("routed_cost_usd", "probe_cost_usd"):
            self.assertEqual((fields[name].max_digits,
                              fields[name].decimal_places), (10, 6))
        rel = {f.name: (f.related_model.__name__, f.remote_field.on_delete)
               for f in fields.values() if f.is_relation}
        self.assertEqual(rel, {"wake": ("OrcWake", models.SET_NULL),
                               "orc": ("Orc", models.CASCADE)})
        self.assertTrue(fields["created_at"].auto_now_add)
        self.assertEqual(fields["routed"].default, dict)
        self.assertEqual(fields["probe"].default, dict)
        money = {f.name for f in fields.values()
                 if any(w in f.name for w in ("usd", "cost", "money"))}
        self.assertEqual(money, {"routed_cost_usd", "probe_cost_usd"},
                         "the AI spend of each side, and nothing else")

    def test_one_pair_per_wake_and_kind_and_its_indexes(self):
        model = self._model()
        uniques = {tuple(c.fields) for c in model._meta.constraints}
        self.assertIn(("wake", "kind"), uniques)
        indexed = {tuple(i.fields) for i in model._meta.indexes}
        self.assertIn(("kind", "boundary", "world", "block"), indexed)
        self.assertIn(("fwd_at",), indexed)

    def test_the_allowed_values_are_tuples(self):
        from bot_program.orcs import constants as C
        self.assertEqual(C.TIER_GRADE_KINDS, ("h0", "boundary", "twin"))
        self.assertEqual(C.PROBE_KINDS, ("h0", "boundary"))
        self.assertEqual(C.PROBE_BOUNDARIES, (30, 55, 75))
        self.assertEqual(C.PROBE_BOUNDARIES, (C.BAND_ROUTINE_MAX,
                                              C.BAND_MATERIAL_MAX,
                                              C.BAND_COMPLEX_MAX))
        model = self._model()
        self.assertLessEqual(max(map(len, C.TIER_GRADE_KINDS)),
                             model._meta.get_field("kind").max_length)
        self.assertLessEqual(max(map(len, C.VENUES)),
                             model._meta.get_field("world").max_length)
        self.assertLessEqual(max(map(len, C.RUNG_LIMITS)),
                             model._meta.get_field("probe_rung").max_length)


def _columns_problems(test, model, columns):
    """Every concrete column of `model` but its key at the spec's type,
    size and nullability, none with `choices` (the TheIntentTableTests
    pattern)."""
    fields = {f.name: f for f in model._meta.concrete_fields
              if not f.primary_key}
    test.assertEqual(set(fields), set(columns))
    for name, (kind, size, null) in columns.items():
        f = fields[name]
        with test.subTest(model=model.__name__, field=name):
            test.assertEqual(f.get_internal_type(), kind)
            test.assertEqual(f.null, null)
            if size is not None:
                test.assertEqual(f.max_length, size)
            test.assertFalse(f.choices)
    return fields


class TheO2cTablesTests(SimpleTestCase):
    """O2c's tables (the O2 spec §1.3.2; O2c, 2026-11-07): every column of
    the spec at its type, one Captain per (user, class), one wave per
    (user, wave id), one temperament grade per (temperament, version,
    venue, class, bar source), no money column but a wave's AI spend, and
    their allowed values tuples in constants.py (§1.0 item 5). Nothing
    reads them in this commit."""

    #: name -> (internal type, max_length, null)
    CAPTAIN = {
        "user": ("ForeignKey", None, False),
        "asset_class": ("CharField", 12, False),
        "seated_at": ("DateTimeField", None, False),
        "label": ("CharField", 60, False),
        "state": ("CharField", 12, False),
        "last_wake_at": ("DateTimeField", None, True),
        "wakes_today": ("SmallIntegerField", None, False),
        "counters_day": ("DateField", None, True),
        "pending": ("JSONField", None, False),
    }
    ORDER = {
        "captain": ("ForeignKey", None, False),
        "kind": ("CharField", 12, False),
        "scope": ("JSONField", None, False),
        "level_id": ("CharField", 24, False),
        "level": ("JSONField", None, False),
        "words": ("CharField", 300, False),
        "mode": ("CharField", 10, False),
        "issued_at": ("DateTimeField", None, False),
        "expires_at": ("DateTimeField", None, True),
        "cause": ("JSONField", None, False),
        "skeptic": ("JSONField", None, False),
        "grade": ("JSONField", None, False),
        "s_version": ("CharField", 8, False),
    }
    WAVE = {
        "wave_id": ("CharField", 40, False),
        "user": ("ForeignKey", None, False),
        "kind": ("CharField", 16, False),
        "symbols": ("JSONField", None, False),
        "origin": ("CharField", 40, False),
        "first_at": ("DateTimeField", None, False),
        "last_at": ("DateTimeField", None, False),
        "max_hop": ("SmallIntegerField", None, False),
        "drums": ("IntegerField", None, False),
        "reach": ("JSONField", None, False),
        "w12_queued": ("IntegerField", None, False),
        "w12_answered": ("IntegerField", None, False),
        "cost_usd": ("DecimalField", None, False),
        "breaker": ("JSONField", None, False),
    }
    TEMPERAMENT_GRADE = {
        "temperament": ("CharField", 16, False),
        "version": ("CharField", 8, False),
        "venue": ("CharField", 8, False),
        "asset_class": ("CharField", 12, False),
        "bar_source": ("CharField", 12, False),
        "n": ("IntegerField", None, False),
        "mean": ("FloatField", None, True),
        "se": ("FloatField", None, True),
        "lb80": ("FloatField", None, True),
        "ub80": ("FloatField", None, True),
        "vs_control_mean": ("FloatField", None, True),
        "block": ("IntegerField", None, False),
        "at": ("DateTimeField", None, False),
    }
    #: the words a money column is spelled with
    MONEY = ("usd", "money", "pnl", "cost", "balance", "amount", "equity",
             "notional", "qty")

    def _model(self, name):
        from django.apps import apps
        return apps.get_model("bot_program", name)

    def _money(self, fields):
        return {n for n in fields if any(w in n for w in self.MONEY)}

    def test_the_captain_one_per_user_and_class(self):
        from django.conf import settings
        from django.db import models
        model = self._model("Captain")
        fields = _columns_problems(self, model, self.CAPTAIN)
        self.assertEqual(fields["user"].related_model._meta.label,
                         settings.AUTH_USER_MODEL)
        self.assertEqual(fields["user"].remote_field.on_delete,
                         models.CASCADE)
        uniques = {tuple(c.fields) for c in model._meta.constraints}
        self.assertIn(("user", "asset_class"), uniques)
        self.assertEqual(fields["pending"].default, dict)
        self.assertEqual(fields["state"].default, "seated")
        self.assertEqual(self._money(fields), set(), "no money column")

    def test_an_order_in_shadow_keeps_its_level_by_reference(self):
        """CaptainOrder (§1.3.2, C.8, C.9): its level kept as the stored
        reference {level_id, kind, tf, price, stop}, which C.9 grades and
        PS11 shows (§1.3.2 lists only the id: A.30's rule, as OrcIntent's
        level); its words capped as FENCE_CAPS["captain"] allows; mode
        shadow; R and prices only."""
        from django.db import models

        from bot_program.orcs import constants as C
        model = self._model("CaptainOrder")
        fields = _columns_problems(self, model, self.ORDER)
        self.assertEqual((fields["captain"].related_model.__name__,
                          fields["captain"].remote_field.on_delete),
                         ("Captain", models.CASCADE))
        for name in ("scope", "level", "cause", "skeptic", "grade"):
            self.assertEqual(fields[name].default, dict, name)
        self.assertEqual(fields["mode"].default, C.MODE_SHADOW)
        self.assertGreaterEqual(fields["words"].max_length,
                                C.FENCE_CAPS["captain"])
        self.assertEqual(self._money(fields), set(), "no money column")

    def test_a_wave_is_one_per_user_and_wave_id(self):
        """drums.wave_of names a wave by its kind, symbol and second with
        no user, so the id alone is never unique: (user, wave_id) is. The
        wave's AI spend is its only money, in USD (staff pages only)."""
        from django.conf import settings
        from django.db import models
        model = self._model("OrcWave")
        fields = _columns_problems(self, model, self.WAVE)
        self.assertEqual((fields["user"].related_model._meta.label,
                          fields["user"].remote_field.on_delete),
                         (settings.AUTH_USER_MODEL, models.CASCADE))
        self.assertFalse(fields["wave_id"].unique, "never unique alone")
        uniques = {tuple(c.fields) for c in model._meta.constraints}
        self.assertIn(("user", "wave_id"), uniques)
        self.assertEqual((fields["cost_usd"].max_digits,
                          fields["cost_usd"].decimal_places), (10, 6))
        self.assertEqual(self._money(fields), {"cost_usd"})
        self.assertEqual(fields["breaker"].default, dict)
        self.assertEqual(fields["symbols"].default, list)
        self.assertEqual(fields["reach"].default, list)

    def test_one_temperament_grade_per_key(self):
        model = self._model("OrcTemperamentGrade")
        fields = _columns_problems(self, model, self.TEMPERAMENT_GRADE)
        uniques = {tuple(c.fields) for c in model._meta.constraints}
        self.assertIn(("temperament", "version", "venue", "asset_class",
                       "bar_source"), uniques)
        self.assertEqual(self._money(fields), set(), "R only")

    def test_the_orc_carries_its_temperament(self):
        """Orc.temperament (§1.3.2): a CharField of 16, blank, '' for
        every Orc born before O2c or with its switch OFF (C.4)."""
        from bot_program.orcs.models import Orc
        f = Orc._meta.get_field("temperament")
        self.assertEqual((f.get_internal_type(), f.max_length, f.blank,
                          f.null, f.default), ("CharField", 16, True, False,
                                               ""))
        self.assertFalse(f.choices)

    def test_the_reverse_accessors_are_named_apart(self):
        """No new table is reached from a platform row through `.orc`,
        `.orc_leg` or `.orcs` (N1.6, test item g): a Captain through
        user.orc_captains, its orders through captain.orders, a wave
        through user.orc_waves."""
        names = {(m, f): self._model(m)._meta.get_field(f)
                 .remote_field.related_name
                 for m, f in (("Captain", "user"),
                              ("CaptainOrder", "captain"),
                              ("OrcWave", "user"))}
        self.assertEqual(names, {("Captain", "user"): "orc_captains",
                                 ("CaptainOrder", "captain"): "orders",
                                 ("OrcWave", "user"): "orc_waves"})
        self.assertFalse(set(names.values()) & {"orc", "orc_leg", "orcs"})

    def test_the_allowed_values_are_tuples(self):
        """§1.0 item 5: the orders' kinds and mode, the Captain's states and
        the wave breaker's, tuples in constants.py; each fits its
        column."""
        from bot_program.orcs import constants as C
        self.assertEqual(C.CAPTAIN_ORDER_KINDS, ("hold_fire", "tighten",
                                                 "cut", "theme"))
        self.assertEqual(C.ORDER_MODES, (C.MODE_SHADOW,))
        self.assertTrue(set(C.ORDER_MODES) <= set(C.MODES))
        self.assertEqual(C.CAPTAIN_STATES, ("seated", "idle"))
        self.assertEqual(C.WAVE_BREAKER_STATES, ("closed", "open"))
        for model, field, values in (
                ("CaptainOrder", "kind", C.CAPTAIN_ORDER_KINDS),
                ("CaptainOrder", "mode", C.ORDER_MODES),
                ("Captain", "state", C.CAPTAIN_STATES),
                ("OrcWave", "kind", C.DRUM_KINDS),
                ("OrcTemperamentGrade", "venue", C.VENUES)):
            with self.subTest(f"{model}.{field}"):
                self.assertLessEqual(max(map(len, values)), self._model(
                    model)._meta.get_field(field).max_length)

    def test_the_journal_words_and_the_fence_caps(self):
        """§1.3.2: JOURNAL_KINDS gains `skeptic` (the Skeptic's co-sign),
        AUTHORS gains `emperor`; FACT_AUTHORS stays code's alone (the
        Emperor's words are a model's, never a fact, N5); FENCE_CAPS gains
        the temperament's lane texts, a Captain's, the Emperor's and the
        Skeptic's words."""
        from bot_program.orcs import constants as C
        self.assertIn("skeptic", C.JOURNAL_KINDS)
        self.assertEqual(len(C.JOURNAL_KINDS), len(set(C.JOURNAL_KINDS)))
        self.assertIn("emperor", C.AUTHORS)
        self.assertEqual(C.FACT_AUTHORS, ("code", "care", "reconcile",
                                          "morgul"))
        self.assertNotIn("emperor", C.FACT_AUTHORS)
        for kind, cap in (("temperament", 600), ("captain", 280),
                          ("emperor", 600), ("skeptic", 280)):
            self.assertEqual(C.FENCE_CAPS[kind], cap, kind)
        from bot_program.orcs.models import OrcJournal
        self.assertLessEqual(max(map(len, C.JOURNAL_KINDS)),
                             OrcJournal._meta.get_field("kind").max_length)
        self.assertLessEqual(max(map(len, C.AUTHORS)),
                             OrcJournal._meta.get_field("author").max_length)


class TheO2cConstraintTests(TestCase):
    """The database holds the uniques (O2c, 2026-11-07)."""

    def setUp(self):
        self.user = _user("orc_o2c_models")
        self.other = _user("orc_o2c_models_b")

    def test_one_captain_per_user_and_class(self):
        from bot_program.orcs.models import Captain, CaptainOrder
        cap = Captain.objects.create(user=self.user, asset_class="crypto")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Captain.objects.create(user=self.user, asset_class="crypto")
        Captain.objects.create(user=self.user, asset_class="forex")
        Captain.objects.create(user=self.other, asset_class="crypto")
        order = CaptainOrder.objects.create(captain=cap, kind="hold_fire",
                                            scope={"class": "crypto"})
        self.assertEqual((order.mode, list(cap.orders.all())),
                         ("shadow", [order]))
        self.assertEqual((cap.state, cap.pending, cap.wakes_today),
                         ("seated", {}, 0))

    def test_one_wave_per_user_and_wave_id(self):
        from bot_program.orcs.models import OrcWave
        wave = "stop_hit:BTCUSD:20261022132700"
        OrcWave.objects.create(user=self.user, wave_id=wave, kind="stop_hit")
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrcWave.objects.create(user=self.user, wave_id=wave,
                                   kind="stop_hit")
        OrcWave.objects.create(user=self.other, wave_id=wave,
                               kind="stop_hit")
        self.assertEqual(OrcWave.objects.filter(wave_id=wave).count(), 2)

    def test_one_temperament_grade_per_key(self):
        from bot_program.orcs.models import OrcTemperamentGrade
        key = {"temperament": "striker", "version": "t1", "venue": "paper",
               "asset_class": "crypto", "bar_source": "etoro"}
        OrcTemperamentGrade.objects.create(**key)
        with self.assertRaises(IntegrityError), transaction.atomic():
            OrcTemperamentGrade.objects.create(**key)
        OrcTemperamentGrade.objects.create(**{**key, "venue": "live"})
