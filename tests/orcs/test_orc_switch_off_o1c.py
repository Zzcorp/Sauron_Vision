"""HARD RULE 1 FOR O1c (spec §11): with `orcs` OFF the tick, the census, the
beats and the bar refresh are byte-identical to before and no O1c table
is written; ON, a row with no Orc is managed exactly as before; the care's
plan() is unchanged; wake detection never raises and a failure leaves the
tick intact; a quiet tick stays inside the O1b query budget.

Run with:  python manage.py test tests.orcs.test_orc_switch_off_o1c
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from unittest.mock import patch

from django.test import TestCase

from tests.orcs.helpers import _config, _on, _row, born
from tests.orcs.test_orc_tick_off import FIXED, _Tick

O1C_TABLES = ("OrcWake", "OrcDossierBlock", "OrcDrum", "OrcDayBaseline")


def _o1c_counts():
    from bot_program.orcs import models
    return {name: getattr(models, name).objects.count()
            for name in O1C_TABLES}


class TheOffTests(_Tick):

    def test_tick_byte_identical_off_with_orc_rows(self):
        _on()
        (a, ra), (b, rb) = self._pair()
        born(self, ra)
        born(self, rb)
        ra.refresh_from_db()
        rb.refresh_from_db()
        _on(False)
        before = _o1c_counts()
        out = self._run(a, ra, hooked=False)
        real = self._run(b, rb, hooked=True)
        for run in (out, real):
            run["row"]["metadata"].pop("orc")
            run.pop("sql")
        self.assertEqual(real["orc_sql"], [])
        self.assertLessEqual(real.pop("queries") - out.pop("queries"), 1)
        self.assertEqual(out, real)
        self.assertEqual(_o1c_counts(), before)

    def test_no_o1c_table_written_while_off(self):
        from bot_program.orcs import census, tasks
        from bot_program.orcs.models import OrcJournal
        _on()
        (a, ra), _b = self._pair()
        born(self, ra)
        ra.refresh_from_db()
        _on(False)
        kinds = set(OrcJournal.objects.values_list("kind", flat=True))
        n = OrcJournal.objects.count()
        self._run(a, ra)
        self.assertEqual(census.run(FIXED)["status"], "skipped")
        for task in (tasks.orc_day_roll, tasks.orc_session_close,
                     tasks.orc_hourly, tasks.orc_census):
            self.assertEqual(task()["status"], "skipped")
        self.assertEqual(_o1c_counts(), dict.fromkeys(O1C_TABLES, 0))
        self.assertEqual(OrcJournal.objects.count(), n)
        self.assertEqual(set(OrcJournal.objects.values_list("kind",
                                                            flat=True)),
                         kinds)

    def test_on_a_row_with_no_orc_is_byte_identical(self):
        _on()
        (a, ra), (b, rb) = self._pair()
        out = self._run(a, ra, hooked=False)
        real = self._run(b, rb, hooked=True)
        out.pop("sql")
        real.pop("sql")
        self.assertEqual(out, real)
        self.assertEqual(_o1c_counts(), dict.fromkeys(O1C_TABLES, 0))


class TheFenceTests(_Tick):

    def test_detect_never_raises(self):
        from types import SimpleNamespace

        from bot_program.orcs import wake
        _on()
        (a, ra), _b = self._pair()
        orc = born(self, ra)
        ra.refresh_from_db()
        bot = SimpleNamespace(_tick_broker_cache={}, cfg=a, _last_ticks={})
        with patch("bot_program.orcs.dossier.render",
                   side_effect=RuntimeError("the dossier broke")):
            self.assertIsNone(wake.detect(bot, ra, "102.2", "", orc))
        with patch("bot_program.orcs.complexity.score",
                   side_effect=RuntimeError("the score broke")):
            self.assertIsNone(wake.detect(bot, ra, "102.2", "", orc))
        self.assertIsNone(wake.detect(None, None, None, "", None))

    def test_detect_failure_leaves_the_tick_intact(self):
        _on()
        (a, ra), (b, rb) = self._pair()
        born(self, ra)
        born(self, rb)
        ra.refresh_from_db()
        rb.refresh_from_db()
        with patch("bot_program.orcs.wake.detect",
                   side_effect=RuntimeError("detection broke")), \
                patch("bot_program.orcs.drum_bus.on_tick",
                      side_effect=RuntimeError("the drums broke")):
            real = self._run(b, rb, hooked=True)
        out = self._run(a, ra, hooked=False)
        for run in (out, real):
            run["row"]["metadata"].pop("orc")
        self.assertEqual(out["row"], real["row"])
        self.assertEqual(out["calls"], real["calls"])
        self.assertEqual(out["actions"], real["actions"])

    def test_quiet_tick_query_budget(self):
        """The O1b budget (tests/orcs/test_orc_tick_off.py): a quiet tick
        of a row with an Orc costs at most 12 queries more than a row
        without; detection adds none on a quiet tick."""
        _on()
        (a, ra), _b = self._pair()
        born(self, ra)
        ra.refresh_from_db()
        self._run(a, ra)                    # the birth wake is recorded
        quiet = self._run(a, ra)
        plain_cfg = _config(self.user, name="plain")
        plain = _row(plain_cfg)
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(pk=plain.pk).update(
            opened_at=FIXED - timedelta(hours=1))
        plain.refresh_from_db()
        self._run(plain_cfg, plain)
        base = self._run(plain_cfg, plain)
        self.assertLessEqual(quiet["queries"] - base["queries"], 12,
                             quiet["sql"])
        from bot_program.orcs.models import OrcWake
        self.assertEqual(OrcWake.objects.count(), 1)


class TheQuietTickTests(TestCase):
    """A quiet tick with O1c's steps costs exactly the queries of O1b's
    steps alone: detection reads the frames the tick already read and the
    memory in hand, and opens no savepoint unless it writes."""

    def test_detection_adds_no_query_on_a_quiet_tick(self):
        from contextlib import ExitStack
        from types import SimpleNamespace

        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from bot_program.orcs import observe
        from tests.orcs.helpers import _bars, _switch, _user, _wave
        _switch("aragorn")
        _on()
        user = _user("quiet_o1c")
        cfg = _config(user)
        _bars("BTCUSD", "1h", _wave(200), start=FIXED - timedelta(hours=200))
        _bars("BTCUSD", "4h", _wave(200), start=FIXED - timedelta(hours=800))
        row = _row(cfg)
        born(self, row, at=FIXED - timedelta(minutes=1))
        row.refresh_from_db()

        def tick(at, steps=None):
            bot = SimpleNamespace(_tick_broker_cache={}, cfg=cfg,
                                  _last_ticks={})
            row._care_tick = {"now": at}
            with ExitStack() as st:
                st.enter_context(patch("django.utils.timezone.now",
                                       return_value=at))
                if steps is not None:
                    st.enter_context(patch.object(observe, "TICK_STEPS",
                                                  steps))
                q = st.enter_context(CaptureQueriesContext(connection))
                st.enter_context(self.captureOnCommitCallbacks(execute=True))
                observe.after_care(bot, row, "100.5", "")
            return len(q.captured_queries)
        tick(FIXED)                                   # the birth wake
        o1c = tick(FIXED + timedelta(minutes=5))
        o1b = tick(FIXED + timedelta(minutes=6),
                   (observe._observe_tick, observe._check_predicates,
                    observe._step_ghosts))
        self.assertEqual(o1c, o1b)


class TheCloseHookTests(TestCase):
    """The death receiver (bot_program/orcs/lifecycle.py): an unstamped
    row's closing save costs no query and queues nothing, whatever the
    switch; a stamped one queues ONE callback, inside which the close is
    journaled and its stop drum published (no second on_commit)."""

    def test_close_save_unstamped_no_query(self):
        from django.utils import timezone

        from bot_program.orcs import lifecycle
        from bot_program.orcs.models import OrcDrum
        from tests.orcs.helpers import _switch, _user
        _switch("aragorn")
        _on()
        cfg = _config(_user("close_hook"))
        plain = _row(cfg)
        plain.status, plain.outcome = "CLOSED", "stopped_out"
        with self.assertNumQueries(0), \
                self.captureOnCommitCallbacks() as cbs:
            lifecycle._leg_saved(type(plain), plain)
        self.assertEqual(cbs, [])
        stamped = _row(cfg, symbol="ETHUSD")
        born(self, stamped)
        stamped.refresh_from_db()
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(pk=stamped.pk).update(
            status="CLOSED", outcome="stopped_out", reason="closed:SL",
            exit_price=97.5, closed_at=timezone.now())
        stamped.refresh_from_db()
        with self.captureOnCommitCallbacks() as cbs:
            lifecycle._leg_saved(type(stamped), stamped)
        self.assertEqual(len(cbs), 1)
        with self.captureOnCommitCallbacks(execute=True) as inner:
            cbs[0]()
        self.assertEqual(inner, [], "the drum rides the same callback")
        self.assertEqual(OrcDrum.objects.filter(kind="stop_hit").count(), 1)


class TheCarePlanTests(TestCase):

    def test_plan_unchanged_for_a_row_with_no_orc_and_for_an_orc_row(self):
        from bot_program.position_care import plan
        from tests.test_aragorn import _row as _care_row
        friday = datetime(2026, 10, 2, 20, 0, tzinfo=dt_tz.utc)
        cases = [(dict(), 102.2, {}), (dict(side="SELL", stop=102.0), 96.0,
                                       {}),
                 (dict(cls="forex"), 101.2, dict(now=friday))]
        for kw, price, extra in cases:
            extra = {"now": FIXED, **extra}
            row = _care_row(**kw)
            golden = plan(row, price, **extra)
            stamped = _care_row(**kw)
            stamped.metadata = {**(stamped.metadata or {}),
                                "orc": {"idea": 1, "leg": 1, "kind": "root"}}
            with self.subTest(kw=kw):
                self.assertEqual(plan(stamped, price, **extra), golden)
