"""THE eTORO SYNC EVERY 30 s, THE HELD QUOTES EVERY 15 s (2026-11-13).

The operator, 2026-11-13: "aussi le refresh etoro par minute est toujours
trop long, je suggère 20-30 secondes non?" On 2026-11-06 he had asked
"augmenter au maximum le taux de refresh des valeurs et de eToro surtout",
and the account sync went to 60 s, eToro's own quotes for the held
instruments to 30 s.

  * THE ACCOUNT SYNC EVERY 30 s (config/celery.py "sync-etoro-accounts",
    tasks.ETORO_SYNC_BEAT_S), inside his 20-30 s: a run not started within
    25 s is dropped, and one pass runs at a time (tasks.ETORO_SYNC_LOCK_KEY:
    a beat that finds a pass running is idle, sends nothing, counts no
    miss and writes no component row). NOT 20 s: one eToro key pair opens
    both worlds (etoro_budget's header, MEASURED 2026-09-23), so REAL and
    DEMO spend ONE budget. At 30 s the sync alone holds 12 account reads in
    a rolling minute and the worst burst beside it 25 of P2's 28; at 20 s
    the sync alone holds 16, past the 15 the demo short proofs stand aside
    at (etoro_budget.busy(kh, P5)), and the same burst needs 29: a refused
    sync holds that account's eToro entries until the next read.
  * eToro's OWN QUOTES for the held instruments EVERY 15 s
    (etoro_quotes.BEAT_S): three requests a pass, so the cap stays twelve a
    rolling minute; a run not started within 10 s is dropped; a pass
    starts no read past PASS_BUDGET_S (5 s). The beat skips only an answer
    younger than half its beat (OWN_FRESH_S, 7 s): at 15 s, skipping what
    the shared rates cache answered within 15 s skipped its OWN last
    answer, and every instrument was read every 30 s.
  * WHAT WAS TUNED TO THE 60 s PASS IS KEPT IN WALL-CLOCK TERMS:
      - the stall alert and the alarm after thirty missed beats, fifteen
        minutes; a pass that outlived its beat (its reads timing out) held
        the beats behind it under the lock, and its miss counts them;
      - the equity history one row in five minutes (the slack is half a
        beat, 15 s);
      - the venue's health noted from ONE pass a minute per account for the
        sync, and from one pass per 30 s for the quotes: the passes the old
        beats would have run. The others read, write and count their miss
        as every pass does, and note nothing (EtoroTrader.health_quiet), so
        a brief eToro hiccup makes eToro sick no sooner and no more often
        than before; an order's failure is always noted.
  * MONEY: the order gates read eToro's cash, used margin and equity at
    most about 30 s old instead of 60 s, from the same cells by the same
    rules; no limit, threshold, ratio or formula moves (TheMoneyWindows
    DoNotMoveTests).

THE REVIEW (2026-11-13, on 6be0d77): a quiet pass that meets a 429 grants
no shared pause (the pause skipped the next noting pass, and a 429 storm
made eToro sick later than before, or not at all); its 429 is still kept
for the readers that step aside for one (venue_health.note_refusal),
never toward SICK; the pass lock is given back only by the pass that
holds it, and REAL is read before DEMO; the held quotes' cap judges a
pass by the instant it started, so a steady pass is never blank; the
digest says "every 30 s"; the operator's live check reads the database.

Fakes only: no network, broker or model call.

Run with:  python manage.py test tests.test_etoro_sync_30s
"""
import contextlib
from datetime import datetime, timedelta, timezone as dt_tz
from io import StringIO
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from bot_program import etoro_quotes as eq
from bot_program import tasks
from bot_program import venue_health as vh
from bot_program.engine import etoro_budget as eb
from bot_program.engine import etoro_client as ec
from bot_program.engine import etoro_rates as er
from tests.test_etoro_cheaper_reads import AGG
from tests.test_etoro_client import _Resp
from tests.test_etoro_rates_batch import (KH, USER_KEY, _Clock, _held,
                                          _instrument)
from tests.test_faster_refresh import (_QuotesCase, _account, _beat,
                                       _components, _refresh)

UTC = dt_tz.utc
#: The adapter itself, named before any test patches its name.
REAL = ec.EtoroTrader
TRADER = "bot_program.engine.etoro_client.EtoroTrader"
#: The operator's read-only check after the deploy (the sheet's line), run
#: here by Django's own shell command against the stored rows.
CHECK = ("from django_celery_beat.models import PeriodicTask as T; "
         "[print(t.name, '|', t.interval, '|', 'expires', t.expire_seconds, "
         "'|', 'on' if t.enabled else 'OFF') for t in T.objects.filter("
         "name__in=['sync-etoro-accounts', 'refresh-etoro-quotes'])"
         ".order_by('name')]")
#: The operator's LIVE check (review M1, 2026-11-13): each keyed account's
#: last sync, read from the database. The beat's own "Sending due task"
#: lines are INFO, and production writes the celery loggers at WARNING
#: (core/logging_config, DEBUG False): a grep of the beat's log reads 0.
LIVE = ("from django.utils import timezone as tz; "
        "from bot_program.models import EtoroAccount as E; "
        "[print(a.pk, 'DEMO' if a.demo else 'REAL', 'last sync', "
        "(str(int((tz.now()-a.last_sync).total_seconds()))+' s ago') "
        "if a.last_sync else 'never') "
        "for a in E.objects.exclude(api_key_enc='').order_by('pk')]")


def _pass():
    """One sync pass, the gate's switches not read (as the suite's other
    sync tests run it)."""
    return tasks.sync_etoro_accounts.__wrapped__.__wrapped__()


def _over(wire):
    """EtoroTrader as the sync builds it, its transport the fake `wire`."""
    def make(k, u, env="demo", timeout=10.0):
        t = REAL(k, u, env=env, timeout=timeout)
        t._session = wire
        return t
    return make


class _AccountWire:
    """The account sync's two reads on a fake wire: aggregate-portfolio
    answers AGG and /portfolio an empty book; with `status` other than 200
    every GET answers it (a 503 is a failure the venue's health notes,
    after the read's one retry). Every request is logged."""

    def __init__(self, status=200):
        self.status = status
        self.calls = []
        self.headers = {}

    def get(self, url, **kw):
        self.calls.append(("GET", url))
        if self.status != 200:
            return _Resp(self.status, {})
        if "aggregate-portfolio" in url:
            return _Resp(200, AGG)
        if "portfolio" in url:
            return _Resp(200, {"positions": []})
        return _Resp(200, {})


def _failures(world="live"):
    return vh._load(vh._key("etoro", world)).get("failures") or []


# ── 1. the beats ──────────────────────────────────────────────────────────

class TheBeatsTests(SimpleTestCase):
    """The operator's 20-30 s for the sync, and the held quotes as fast as
    the budget allows; a run not started within its expiry is dropped
    (expire_seconds: the database scheduler's spelling, django_celery_beat
    ModelEntry._unpack_options)."""

    def test_the_sync_every_30_s_a_run_late_by_25_s_dropped(self):
        entry = _beat("sync-etoro-accounts")
        self.assertEqual(entry["task"],
                         "bot_program.tasks.sync_etoro_accounts")
        self.assertEqual(entry["schedule"], 30.0)
        self.assertEqual(entry["schedule"], tasks.ETORO_SYNC_BEAT_S)
        self.assertEqual(entry["options"],
                         {"expires": 25, "expire_seconds": 25})
        self.assertLess(entry["options"]["expire_seconds"], entry["schedule"])

    def test_inside_the_operators_20_to_30_s(self):
        self.assertGreaterEqual(_beat("sync-etoro-accounts")["schedule"], 20)
        self.assertLessEqual(_beat("sync-etoro-accounts")["schedule"], 30)

    def test_the_quotes_every_15_s_a_run_late_by_10_s_dropped(self):
        from config.celery import app
        entry = _beat("refresh-etoro-quotes")
        self.assertEqual(entry["schedule"], 15.0)
        self.assertEqual(entry["schedule"], eq.BEAT_S)
        self.assertEqual(entry["options"],
                         {"expires": 10, "expire_seconds": 10})
        self.assertEqual(
            app.conf.task_routes["bot_program.tasks.refresh_etoro_quotes"],
            {"queue": "fast"})


class TheDatabaseSchedulerMovesTheStoredBeatsTests(TestCase):
    """The beat runs django_celery_beat's DatabaseScheduler (2.9.0). At its
    start, setup_schedule -> update_from_dict(app.conf.beat_schedule) ->
    DatabaseScheduler.Entry.from_entry(name, app=app, **entry) for every
    entry: PeriodicTask.update_or_create BY NAME, the interval and
    expire_seconds from the code. enabled, last_run_at and total_run_count
    are not in its defaults, so they are kept. Only a beat restarted on the
    new code moves them (the rebuild)."""

    def _rows_as_1b94a50_stored_them(self, last):
        from django_celery_beat.models import IntervalSchedule, PeriodicTask
        for name, task, every, expire, runs in (
                ("sync-etoro-accounts",
                 "bot_program.tasks.sync_etoro_accounts", 60, None, 1234),
                ("refresh-etoro-quotes",
                 "bot_program.tasks.refresh_etoro_quotes", 30, 25, 4321)):
            interval, _ = IntervalSchedule.objects.get_or_create(
                every=every, period="seconds")
            PeriodicTask.objects.create(
                name=name, task=task, interval=interval,
                expire_seconds=expire, last_run_at=last,
                total_run_count=runs, enabled=True)

    def _the_check_line(self):
        out = StringIO()
        with contextlib.redirect_stdout(out):
            call_command("shell", command=CHECK, verbosity=0)
        return out.getvalue().splitlines()

    def test_each_beat_is_stored_as_its_interval(self):
        from django_celery_beat.schedulers import ModelEntry
        for key, every in (("sync-etoro-accounts", 30),
                           ("refresh-etoro-quotes", 15)):
            model, field = ModelEntry.to_model_schedule(
                _beat(key)["schedule"])
            self.assertEqual(field, "interval", key)
            self.assertEqual((model.every, model.period), (every, "seconds"),
                             key)

    def test_the_stored_rows_move_at_beat_start_and_keep_their_history(self):
        from django_celery_beat.models import PeriodicTask
        from django_celery_beat.schedulers import DatabaseScheduler

        from config.celery import app
        last = timezone.now() - timedelta(seconds=40)
        self._rows_as_1b94a50_stored_them(last)
        self.assertEqual(self._the_check_line(), [
            "refresh-etoro-quotes | every 30 seconds | expires 25 | on",
            "sync-etoro-accounts | every 60 seconds | expires None | on"])
        for name in ("sync-etoro-accounts", "refresh-etoro-quotes"):
            DatabaseScheduler.Entry.from_entry(name, app=app, **_beat(name))
        # the operator's check after the deploy, and its exact answer
        self.assertEqual(self._the_check_line(), [
            "refresh-etoro-quotes | every 15 seconds | expires 10 | on",
            "sync-etoro-accounts | every 30 seconds | expires 25 | on"])
        for name, runs in (("sync-etoro-accounts", 1234),
                           ("refresh-etoro-quotes", 4321)):
            row = PeriodicTask.objects.get(name=name)
            self.assertEqual(row.last_run_at, last, name)
            self.assertEqual(row.total_run_count, runs, name)
            self.assertTrue(row.enabled, name)

    def test_a_row_disabled_in_the_admin_stays_off(self):
        """The beat never re-enables a row the operator turned off: the
        check line then says OFF."""
        from django_celery_beat.models import PeriodicTask
        from django_celery_beat.schedulers import DatabaseScheduler

        from config.celery import app
        self._rows_as_1b94a50_stored_them(timezone.now())
        PeriodicTask.objects.filter(name="sync-etoro-accounts").update(
            enabled=False)
        DatabaseScheduler.Entry.from_entry(
            "sync-etoro-accounts", app=app, **_beat("sync-etoro-accounts"))
        self.assertIn(
            "sync-etoro-accounts | every 30 seconds | expires 25 | OFF",
            self._the_check_line())

    def test_the_live_check_reads_each_keyed_accounts_last_sync(self):
        """The operator's second check after the deploy (review M1): the
        age of each keyed account's last sync, from the database, run a
        few times. Under about 35 s on a healthy 30 s sync; "never" for an
        account no pass has read; an account without keys is not listed."""
        real = _account(User.objects.create_user("e30_live_r", password="x"))
        demo = _account(User.objects.create_user("e30_live_d", password="x"),
                        demo=True)
        unkeyed = _account(User.objects.create_user("e30_live_u",
                                                    password="x"))
        type(unkeyed).objects.filter(pk=unkeyed.pk).update(api_key_enc="")
        type(real).objects.filter(pk=real.pk).update(
            last_sync=timezone.now() - timedelta(seconds=12))
        out = StringIO()
        with contextlib.redirect_stdout(out):
            call_command("shell", command=LIVE, verbosity=0)
        self.assertEqual(out.getvalue().splitlines(), [
            f"{real.pk} REAL last sync 12 s ago",
            f"{demo.pk} DEMO last sync never"])


# ── 2. the stall alert keeps its fifteen minutes ─────────────────────────

class TheStallAlertKeepsItsFifteenMinutesTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user("e30_stall", password="x")
        self.acct = _account(self.user)
        self.t0 = timezone.now().replace(microsecond=0)

    def _miss(self, at_s, acct=None, **kw):
        with mock.patch("django.utils.timezone.now",
                        return_value=self.t0 + timedelta(seconds=at_s)):
            tasks._note_broker_miss(acct or self.acct, self.user, **kw)

    def _count(self, kind="etoro", acct=None):
        return int(cache.get(
            f"broker_sync:miss:{kind}:{(acct or self.acct).pk}") or 0)

    def test_thirty_beats_of_30_s_are_the_fifteen_minutes(self):
        self.assertEqual(tasks.broker_miss_alert_after("etoro"), 30)
        self.assertEqual(tasks.broker_miss_alert_after("etoro")
                         * tasks.ETORO_SYNC_BEAT_S, 900)
        self.assertEqual(tasks.broker_miss_alert_after("etoro")
                         * _beat("sync-etoro-accounts")["schedule"], 900)
        for kind in ("ibkr", "saxo"):
            self.assertEqual(tasks.broker_miss_alert_after(kind),
                             tasks.BROKER_MISS_ALERT_AFTER, kind)

    def test_29_failing_passes_30_s_apart_say_nothing_the_30th_says_it(self):
        with mock.patch("bot_program.notifications.notify_broker_unreachable",
                        return_value=True) as said, \
                self.assertLogs("bot_program.tasks", level="WARNING"):
            for k in range(29):
                self._miss(30 * k)
            said.assert_not_called()
            self.assertEqual(self._count(), 29)
            self._miss(30 * 29)
        said.assert_called_once()
        self.assertEqual(said.call_args.kwargs["misses"], 30)
        self.assertEqual(said.call_args.kwargs["broker"], "etoro")

    def test_a_pass_that_held_two_beats_counts_three(self):
        """A failing pass that outlives its beat (four reads timing out: up
        to ~83 s, ~163 s with read timeouts) holds the beats behind it under
        the pass lock. Its miss counts the beats since the last counted
        one, so the alert still comes about fifteen minutes after the
        first miss, never 45 to 90."""
        with mock.patch("bot_program.notifications.notify_broker_unreachable",
                        return_value=True) as said, \
                self.assertLogs("bot_program.tasks", level="WARNING") as logs:
            self._miss(0)
            self.assertEqual(self._count(), 1, "the first miss of a run")
            self._miss(90)
            self.assertEqual(self._count(), 4)
            for k in range(2, 10):
                self._miss(90 * k)
            self.assertEqual(self._count(), 28)
            said.assert_not_called()
            self._miss(900)
        said.assert_called_once()
        self.assertEqual(said.call_args.kwargs["misses"], 31)
        self.assertTrue(any("consecutive miss 4" in line
                            and "3 beats" in line for line in logs.output),
                        logs.output)

    def test_a_late_pass_then_an_on_time_one_count_one_each(self):
        """The beat at 0 ran 25 s late (inside its expiry), the one at 30 on
        time: two beats, two misses, never more."""
        with self.assertLogs("bot_program.tasks", level="WARNING"):
            self._miss(25)
            self._miss(30)
            self.assertEqual(self._count(), 2)
            self._miss(60)
        self.assertEqual(self._count(), 3)

    def test_after_a_long_silence_a_miss_counts_what_a_pass_can_hold(self):
        """A worker down an hour sent no pass: its beats were not eToro's
        misses. One miss counts at most the beats the lock can hold behind
        a pass, and its own."""
        self.assertEqual(tasks.BROKER_MISS_MAX_BEATS,
                         tasks.ETORO_SYNC_LOCK_S // tasks.ETORO_SYNC_BEAT_S
                         + 1)
        with self.assertLogs("bot_program.tasks", level="WARNING"):
            self._miss(0)
            self._miss(3600)
        self.assertEqual(self._count(), 1 + tasks.BROKER_MISS_MAX_BEATS)

    def test_a_good_pass_starts_the_run_again(self):
        with self.assertLogs("bot_program.tasks", level="WARNING"):
            self._miss(0)
            self._miss(90)
            self.assertEqual(self._count(), 4)
            tasks._clear_broker_miss(self.acct)
            self._miss(180)
        self.assertEqual(self._count(), 1)

    def test_a_deferred_pass_is_never_a_missed_beat(self):
        """A pass the request budget deferred sent nothing and is never a
        miss (2026-11-01): the next miss counts from it, not across it."""
        from unittest.mock import MagicMock

        from tests.test_sync_walks_etoro import _sync_etoro
        silent = MagicMock(spec=["account_snapshot", "broker_portfolio",
                                 "demo"])
        silent.demo = False
        silent.account_snapshot.return_value = None
        silent.broker_portfolio.return_value = None
        refused = MagicMock(spec=["account_snapshot", "broker_portfolio",
                                  "demo"])
        refused.demo = False
        refused.account_snapshot.side_effect = eb.Refused(
            eb.ACCOUNT, eb.P2, eb.FLOOR, "eToro budget: account 28/30")

        def at(s, client):
            with mock.patch("django.utils.timezone.now",
                            return_value=self.t0 + timedelta(seconds=s)):
                return _sync_etoro(client)
        with self.assertLogs("bot_program.tasks", level="WARNING"):
            at(0, silent)
            self.assertEqual(at(30, refused)["deferred"], 1)
            self.assertEqual(self._count(), 1, "a deferral counts nothing")
            at(60, silent)
        self.assertEqual(self._count(), 2)

    def test_ibkr_and_saxo_count_one_a_miss(self):
        """Their walks hold no pass lock and keep their own rule: three
        passes of 900 s."""
        from bot_program.models import IBKRAccount
        ib = IBKRAccount.objects.create(user=self.user, port=4003, label="IB")
        ib.set_credentials("U1")
        ib.save()
        with self.assertLogs("bot_program.tasks", level="WARNING"):
            self._miss(0, acct=ib)
            self._miss(900, acct=ib)
        self.assertEqual(self._count("ibkr", ib), 2)

    def test_the_alerts_say_fifteen_minutes(self):
        from bot_program import notifications
        after = 30
        with mock.patch.object(notifications, "dispatch_notification",
                               return_value=True) as d:
            notifications.notify_broker_unreachable(
                self.user, label="Main", host="api", port=0, misses=after,
                broker="etoro")
        kw = d.call_args.kwargs
        self.assertIn("since 15 minutes ago", kw["body"])
        self.assertIn("Silent for 30 syncs running (about 15 minutes)",
                      kw["row_data"]["items"])
        with mock.patch.object(notifications, "dispatch_notification",
                               return_value=True) as d:
            notifications.notify_broker_cells_unanswered(
                self.user, label="Main", misses=after, broker="etoro")
        kw = d.call_args.kwargs
        self.assertIn("For about 15 minutes the account sync", kw["body"])
        self.assertIn("Cash and used margin: not answered for 30 syncs "
                      "running (about 15 minutes)", kw["row_data"]["items"])
        # IBKR's three passes of 900 s stay forty-five minutes
        with mock.patch.object(notifications, "dispatch_notification",
                               return_value=True) as d:
            notifications.notify_broker_unreachable(
                self.user, label="ISA", host="ibgateway", port=4001,
                misses=3, broker="ibkr")
        self.assertIn("since 45 minutes ago", d.call_args.kwargs["body"])

    def test_the_alarm_says_it_at_30_not_29(self):
        from bot_program import alarm
        _components()
        key = f"broker_sync:miss:etoro:{self.acct.pk}"
        cache.set(key, 29, 3600)
        self.assertEqual(alarm.read_brokers(timezone.now()), [])
        cache.set(key, 30, 3600)
        said = alarm.read_brokers(timezone.now())
        self.assertEqual(len(said), 1)
        self.assertIn(f"eToro account #{self.acct.pk} has not answered 30 "
                      f"syncs in a row", said[0].words)


# ── 3. the history keeps its five minutes ────────────────────────────────

class TheHistoryKeepsItsFiveMinutesTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user("e30_hist", password="x")
        self.acct = _account(self.user)
        self.t0 = timezone.now().replace(microsecond=0)

    def _sync(self, at_s):
        from tests.test_sync_walks_etoro import _client, _sync_etoro
        with mock.patch("django.utils.timezone.now",
                        return_value=self.t0 + timedelta(seconds=at_s)):
            return _sync_etoro(_client())

    def _gaps(self):
        from bot_program.equity_models import BrokerEquityReading
        ats = list(BrokerEquityReading.objects
                   .filter(broker="etoro", account_pk=self.acct.pk)
                   .order_by("at").values_list("at", flat=True))
        return ats, [(b - a).total_seconds() for a, b in zip(ats, ats[1:])]

    def test_the_slack_is_half_a_beat(self):
        self.assertEqual(tasks.ETORO_HISTORY_EVERY_S, 300)
        self.assertEqual(tasks.ETORO_HISTORY_SLACK_S,
                         tasks.ETORO_SYNC_BEAT_S // 2)
        self.assertLess(tasks.ETORO_HISTORY_SLACK_S, tasks.ETORO_SYNC_BEAT_S)

    def test_an_hour_of_passes_30_s_apart_writes_a_row_every_five_minutes(
            self):
        for k in range(121):                    # 0 .. 3600 s
            out = self._sync(30 * k)
            self.assertEqual(out["stored"], 1, k)
        ats, gaps = self._gaps()
        self.assertEqual(len(ats), 13)
        self.assertEqual(set(gaps), {300.0})

    def test_a_late_pass_never_writes_closer_than_285_s(self):
        starts = [30 * k for k in range(9)] + [295] \
            + [30 * k for k in range(10, 21)]   # the beat at 270 ran at 295
        for s in starts:
            self._sync(s)
        ats, gaps = self._gaps()
        self.assertEqual(gaps, [295.0, 305.0])
        self.assertTrue(all(g >= 300 - tasks.ETORO_HISTORY_SLACK_S
                            for g in gaps))


# ── 4. the venue's health: no sooner and no more often than before ───────

class TheSyncNotesTheVenueOnceAMinuteTests(TestCase):
    """REAL on a wire answering 503: each failing pass is two failed reads
    (the aggregate and /portfolio, each after its one retry). Today's 60 s
    beat noted two at 0 and two at 60, and eToro was sick at 60 (three
    inside 180 s). At 30 s the pass at 30 notes nothing: sick at 60, the
    same instant."""

    def setUp(self):
        cache.clear()
        vh.reset()
        self.addCleanup(cache.clear)
        self.addCleanup(vh.reset)
        for p in (mock.patch.object(ec, "READ_RETRY_DELAY_S", 0.0),
                  mock.patch("bot_program.notifications.notify_staff")):
            p.start()
            self.addCleanup(p.stop)
        self.user = User.objects.create_user("e30_vh", password="x")
        self.real = _account(self.user)
        self.wire = _AccountWire(status=503)
        p = mock.patch(TRADER, side_effect=_over(self.wire))
        p.start()
        self.addCleanup(p.stop)
        self.t0 = timezone.now().replace(microsecond=0)

    def _at(self, s):
        return self.t0 + timedelta(seconds=s)

    def _pass_at(self, s):
        with mock.patch("django.utils.timezone.now",
                        return_value=self._at(s)), \
                self.assertLogs("bot_program.tasks", level="WARNING"):
            return _pass()

    def test_noted_once_a_minute_and_sick_at_the_same_instant_as_before(self):
        self._pass_at(0)
        self.assertEqual([f["where"] for f in _failures()],
                         ["account", "portfolio"])
        self.assertIsNone(vh.sick("etoro", "live", now=self._at(0)))
        self._pass_at(30)
        self.assertEqual(len(_failures()), 2,
                         "the pass between two noting passes notes nothing")
        self.assertIsNone(vh.sick("etoro", "live", now=self._at(30)))
        self._pass_at(60)
        self.assertEqual(len(_failures()), 4)
        sick = vh.sick("etoro", "live", now=self._at(60))
        self.assertIsNotNone(sick)
        self.assertEqual(sick["since"], self._at(60).isoformat())
        # every pass asked eToro: two reads and their retries each
        self.assertEqual(len(self.wire.calls), 12)

    def test_a_quiet_pass_counts_its_miss_and_says_why_it_noted_nothing(self):
        self._pass_at(0)
        with mock.patch("django.utils.timezone.now",
                        return_value=self._at(30)), \
                self.assertLogs("bot_program.tasks", level="WARNING"), \
                self.assertLogs("bot_program.engine.etoro_client",
                                level="INFO") as said:
            out = _pass()
        self.assertEqual(out["unreachable"], 1)
        self.assertEqual(int(cache.get(
            f"broker_sync:miss:etoro:{self.real.pk}")), 2)
        quiet = [line for line in said.output
                 if "not noted on the venue's health" in line]
        self.assertEqual(len(quiet), 2, said.output)

    def test_real_and_demo_each_hold_their_own_slot(self):
        """One key, two worlds, two memories of the venue's health: each
        account notes from its own pass a minute."""
        other = User.objects.create_user("e30_vh_demo", password="x")
        _account(other, demo=True)
        self._pass_at(0)
        self.assertEqual((len(_failures("live")), len(_failures("demo"))),
                         (2, 2))
        self._pass_at(30)
        self.assertEqual((len(_failures("live")), len(_failures("demo"))),
                         (2, 2))
        self._pass_at(60)
        self.assertEqual((len(_failures("live")), len(_failures("demo"))),
                         (4, 4))

    def test_a_quiet_client_still_notes_an_order_failure(self):
        """The quiet is the READS' only: an order that failed for the
        venue's reason makes it sick at once, whatever pass sent it."""
        t = REAL("api-k", USER_KEY, env="live")
        t.health_quiet = "a quiet pass of the account sync"
        t._note_health("account", code=503, detail="unavailable")
        t._note_health("portfolio", code=503, detail="unavailable")
        self.assertEqual(_failures(), [])
        t._note_health("order", code=503, detail="the POST failed")
        self.assertEqual([f["where"] for f in _failures()], ["order"])
        self.assertIsNotNone(vh.sick("etoro", "live"))

    def test_a_client_notes_as_before_by_default(self):
        t = REAL("api-k", USER_KEY, env="live")
        self.assertFalse(t.health_quiet)
        t._note_health("account", code=503, detail="unavailable")
        self.assertEqual([f["where"] for f in _failures()], ["account"])


class TheNotingSlotTests(SimpleTestCase):
    """venue_health.noting_slot: the pass that claims it notes; it is free
    again `hold_s` after the pass that claimed it, on the caller's clock."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_claimed_held_then_free_again(self):
        key = "e30:slot:1"
        self.assertTrue(vh.noting_slot(key, 55, now=1000.0))
        self.assertFalse(vh.noting_slot(key, 55, now=1030.0))
        self.assertTrue(vh.noting_slot(key, 55, now=1060.0))
        self.assertFalse(vh.noting_slot(key, 55, now=1090.0))
        self.assertTrue(vh.noting_slot("e30:slot:2", 55, now=1090.0),
                        "each account its own")

    def test_a_cache_that_cannot_be_read_notes_as_before(self):
        with mock.patch.object(cache, "add", side_effect=RuntimeError("down")):
            self.assertTrue(vh.noting_slot("e30:slot:3", 55, now=1.0))


class TheQuotesNoteAsTheirOldBeatDidTests(_QuotesCase):
    """eToro's own quotes on a wire answering 503: a pass stops at its
    first failure. Today's 30 s beat noted at 0, 30 and 60 (sick at 60);
    passes every 15 s note at 0, 30 and 60 still, and the ones between
    ask eToro and note nothing."""

    def test_passes_every_15_s_note_at_0_30_and_60(self):
        _held(self.cfg, "AAA")
        self.wire.status = [503]
        base = 1_900_000_000.0
        t0 = datetime.fromtimestamp(base, tz=UTC)
        clock = _Clock(base)
        with mock.patch.object(eq, "_now", clock):
            for s in (0, 15, 30, 45, 60):
                clock.t = base + s
                with mock.patch("django.utils.timezone.now",
                                return_value=t0 + timedelta(seconds=s)):
                    out = _refresh()
                self.assertIn("stopped", out, s)
        self.assertEqual([(parse_datetime(f["at"]) - t0).total_seconds()
                          for f in _failures()], [0.0, 30.0, 60.0])
        self.assertIsNotNone(vh.sick("etoro", "live",
                                     now=t0 + timedelta(seconds=60)))
        self.assertEqual(len(self.wire.rates()), 10,
                         "every pass asked: one read and its retry each")


class AQuietPassGrantsNoPauseTests(_QuotesCase):
    """THE REVIEW, V1 (2026-11-13). At 6be0d77 a QUIET pass that met a 429
    still granted the shared 429 pause, and the pause then skipped the next
    NOTING pass, the one the old 30 s beat ran: in a 429 storm eToro went
    sick later than at the old beats, or not at all, so the ten-minute
    hold on new real entries came later. A quiet pass now grants no pause
    either: the noting pass after it meets the 429, notes it and grants
    the pause, as the old beat's pass did (passes at 0 and 30: the 429
    noted at 30, the pause from 30)."""

    def test_the_noting_pass_after_a_quiet_429_notes_it_and_pauses(self):
        _held(self.cfg, "AAA")
        self.wire.status = [200, 429]
        base = 1_900_000_000.0
        t0 = datetime.fromtimestamp(base, tz=UTC)
        clock = _Clock(base)
        outs = {}
        with mock.patch.object(eq, "_now", clock), \
                mock.patch.object(eb, "_now", clock), \
                mock.patch.object(ec, "RATE_PAUSE", True), \
                self.assertLogs("bot_program.engine.etoro_client",
                                level="INFO") as said:
            for s in (0, 15, 30):
                clock.t = base + s
                with mock.patch("django.utils.timezone.now",
                                return_value=t0 + timedelta(seconds=s)):
                    outs[s] = _refresh()
                if s == 15:
                    self.assertIn("stopped", outs[15])
                    self.assertEqual(eb.pause_left(KH, "live"), 0.0,
                                     "a quiet pass grants no pause")
                    self.assertEqual(_failures(), [])
            self.assertGreater(eb.pause_left(KH, "live"), 0.0,
                               "the noting pass granted it")
        self.assertNotIn("skipped", outs[30])
        self.assertIn("stopped", outs[30])
        self.assertEqual(
            [(f["where"], f["code"],
              (parse_datetime(f["at"]) - t0).total_seconds())
             for f in _failures()], [("ticker", 429, 30.0)])
        self.assertEqual(len(self.wire.rates()), 3)
        self.assertTrue(any("not noted on the venue's health" in line
                            and "429" in line for line in said.output),
                        said.output)

    def test_a_noting_turn_the_pause_skips_is_spent_as_the_old_beats_was(
            self):
        """The review's harness, re-run on the fix: the old 30 s beat's
        pass that the pause skipped was gone, and its next came 30 s later.
        Here the noting pass the pause skipped left its turn free, the
        quiet pass 15 s later took it and noted the 429 15 s sooner than
        the old beat could (sick up to 0.2 s sooner in 12 of the 432
        phases of a 60 or 90 s 429 storm, beside the sync's notes). A
        pass the pause skips now spends the turn it would have held:
        noted at 0 (paused 40 s) and at 60, as the old beat's passes at 0,
        30 (skipped) and 60."""
        _held(self.cfg, "AAA")
        self.wire.status = [429]
        self.wire.answer_headers = {"Retry-After": "40"}
        base = 1_900_000_000.0
        t0 = datetime.fromtimestamp(base, tz=UTC)
        clock = _Clock(base)
        outs = {}
        with mock.patch.object(eq, "_now", clock), \
                mock.patch.object(eb, "_now", clock), \
                mock.patch.object(ec, "RATE_PAUSE", True), \
                self.assertLogs("bot_program.engine.etoro_client",
                                level="INFO"):
            for s in (0, 15, 30, 45, 60):
                clock.t = base + s
                with mock.patch("django.utils.timezone.now",
                                return_value=t0 + timedelta(seconds=s)):
                    outs[s] = _refresh()
        for s in (15, 30):
            self.assertIn("429 pause holds", outs[s].get("skipped", ""), s)
        self.assertEqual(
            [(parse_datetime(f["at"]) - t0).total_seconds()
             for f in _failures()], [0.0, 60.0])
        self.assertEqual(len(self.wire.rates()), 3, "asked at 0, 45, 60")


class TheQuiet429sAreKeptForTheReadersThatStepAsideTests(TestCase):
    """THE REVIEW, M3 (2026-11-13). A 429 a QUIET pass met was a log line
    only: the readers that step aside after a 429 (the demo short proofs
    for ten minutes, the bar refresh for two) read the noted ones
    (venue_health.recent_refusals), and the sync's account reads grant no
    pause. It is now kept where they read it (venue_health.note_refusal),
    and never counted toward SICK: the operator's "no sooner sick" stays
    whole. A quiet 5xx or timeout stays a log line."""

    def setUp(self):
        cache.clear()
        vh.reset()
        self.addCleanup(cache.clear)
        self.addCleanup(vh.reset)
        self.t = REAL("api-k", USER_KEY, env="live")
        self.t.health_quiet = "a quiet pass of the account sync"
        self.t0 = timezone.now().replace(microsecond=0)

    def _note(self, s, where, code=None, client=None, detail=""):
        with mock.patch("django.utils.timezone.now",
                        return_value=self.t0 + timedelta(seconds=s)):
            (client or self.t)._note_health(where, code=code, detail=detail)

    def _refusals(self, world="live", s=0):
        return vh.recent_refusals("etoro", world, within_s=600,
                                  now=self.t0 + timedelta(seconds=s))

    def test_a_quiet_429_is_kept_and_never_counted_toward_sick(self):
        with self.assertLogs("bot_program.engine.etoro_client", level="INFO"):
            for s in (0, 1, 2):
                self._note(s, "account", 429, detail="no Retry-After")
        self.assertEqual(_failures(), [])
        self.assertIsNone(vh.sick("etoro", "live",
                                  now=self.t0 + timedelta(seconds=2)))
        self.assertEqual([(f["where"], f["code"]) for f in self._refusals()],
                         [("account", 429)] * 3)
        self.assertEqual(self._refusals("demo"), [])

    def test_a_quiet_5xx_or_timeout_stays_a_log_line(self):
        with self.assertLogs("bot_program.engine.etoro_client", level="INFO"):
            self._note(0, "portfolio", 503, detail="unavailable")
            self._note(1, "account", detail="ConnectTimeout: no answer")
        self.assertEqual(self._refusals(), [])
        self.assertEqual(_failures(), [])

    def test_merged_oldest_first_with_the_noted_ones_and_aged_out(self):
        noting = REAL("api-k", USER_KEY, env="live")
        with self.assertLogs("bot_program.engine.etoro_client", level="INFO"):
            self._note(5, "account", 429)
        self._note(0, "ticker", 429, client=noting)
        self.assertEqual([f["where"] for f in self._refusals(s=5)],
                         ["ticker", "account"])
        self.assertEqual([f["where"] for f in self._refusals(s=604)],
                         ["account"])
        self.assertEqual(self._refusals(s=606), [])

    def test_the_demo_proofs_and_the_bars_step_aside_for_it(self):
        from bot_program import short_proofs
        from market_data import bot_bars
        self.assertEqual(short_proofs.refusing(), "")
        self.assertEqual(bot_bars._etoro_refusing("live"), "")
        with self.assertLogs("bot_program.engine.etoro_client", level="INFO"):
            self.t._note_health("portfolio", code=429, detail="")
        self.assertIn("answered HTTP 429", short_proofs.refusing())
        self.assertIn("HTTP 429 (portfolio)", bot_bars._etoro_refusing("live"))

    def test_forgotten_with_the_venues_memory(self):
        with self.assertLogs("bot_program.engine.etoro_client", level="INFO"):
            self._note(0, "account", 429)
        vh.reset()
        self.assertEqual(self._refusals(), [])


# ── 5. the budget: both worlds on one key ────────────────────────────────

class TheBudgetHoldsBothWorldsOnOneKeyTests(TestCase):
    """REAL and DEMO keyed with ONE user key: one key pair opens both
    worlds (MEASURED 2026-09-23, etoro_budget's header), so the two
    accounts spend ONE budget. The account family's start rate is 30 a
    minute, of which P2 (every account read) may take 28; the demo short
    proofs stand aside while a P5 take would be refused, at 15
    (short_proofs.refusing, etoro_budget.busy)."""

    BASE = 1_900_000_000.0

    def setUp(self):
        cache.clear()
        eb.forget_all()
        vh.reset()
        for fn in (cache.clear, eb.forget_all, vh.reset):
            self.addCleanup(fn)
        _components()
        self.clock = _Clock(self.BASE)
        self.wire = _AccountWire()
        for p in (mock.patch.object(eb, "BUDGET", True),
                  mock.patch.object(eb, "_now", self.clock),
                  mock.patch(TRADER, side_effect=_over(self.wire))):
            p.start()
            self.addCleanup(p.stop)
        self.real = _account(User.objects.create_user("e30_real",
                                                      password="x"))
        self.demo = _account(User.objects.create_user("e30_demo",
                                                      password="x"),
                             demo=True)

    def test_the_sync_alone_holds_twelve_reads_a_minute_never_the_proofs_line(
            self):
        entry = _beat("sync-etoro-accounts")
        beat = int(entry["schedule"])
        late = int(entry["options"]["expire_seconds"])
        # ten minutes of passes, the sixth started as late as its expiry
        starts = {beat * k + (late if k == 5 else 0)
                  for k in range(600 // beat)}
        peak, busy = 0, []
        for t in range(600):
            self.clock.t = self.BASE + t
            if t in starts:
                out = _pass()
                self.assertEqual((out["attempted"], out["stored"]), (2, 2),
                                 out)
                self.assertNotIn("deferred", out)
                self.assertNotIn("book_deferred", out)
            if t >= 120:
                peak = max(peak, eb.rolling(KH, eb.ACCOUNT))
                if eb.busy(KH, eb.P5):
                    busy.append(t)
        self.assertEqual(peak, 12)
        self.assertLess(peak, eb.limit(eb.ACCOUNT, eb.P5))
        self.assertEqual(busy, [], "the demo short proofs never stand aside "
                                   "for the sync alone")
        self.assertEqual(len(self.wire.calls), 2 * 2 * len(starts))

    def _burst_minute(self, beat):
        """The worst minute named for the account family, all of it at P2
        on the one key: the sync every `beat` s, both accounts re-read
        after the platform's orders every COALESCE_S (the most it paces
        them to), the reconcile's book for each world, a Telegram /status
        (two reads) and a key probe. (syncs, re-reads, refused direct
        takes, the rolling minute at its end)."""
        from bot_program import etoro_cells
        events = sorted(
            [(t, 0, "reread") for t in range(0, 61, etoro_cells.COALESCE_S)]
            + [(10, 1, "reconcile"), (50, 1, "status")]
            + [(t, 2, "sync") for t in range(0, 61, beat)])
        syncs, rereads, refused = [], [], []
        for t, _order, what in events:
            self.clock.t = self.BASE + t
            if what == "sync":
                syncs.append(_pass())
            elif what == "reread":
                for acct in (self.real, self.demo):
                    rereads.append(tasks.refresh_etoro_cells(acct.pk,
                                                             "an order"))
            else:
                n, where = ((2, "portfolio") if what == "reconcile"
                            else (3, "account"))
                for i in range(n):
                    try:
                        eb.take(KH, eb.ACCOUNT, eb.P2,
                                world=("live", "demo")[i % 2], where=where,
                                why=what)
                    except eb.Refused as e:
                        refused.append((t, what, str(e)))
        return syncs, rereads, refused, eb.rolling(KH, eb.ACCOUNT)

    def test_the_worst_minute_beside_three_passes_is_every_take_granted(self):
        syncs, rereads, refused, n = self._burst_minute(
            int(_beat("sync-etoro-accounts")["schedule"]))
        self.assertEqual(len(syncs), 3)
        for out in syncs:
            self.assertNotIn("deferred", out)
            self.assertNotIn("book_deferred", out)
        self.assertEqual([r["read"] for r in rereads], [True] * 8)
        self.assertEqual(refused, [])
        self.assertEqual(n, 25)
        self.assertLessEqual(n, eb.limit(eb.ACCOUNT, eb.P2))

    def test_why_not_20_s_the_same_minute_refuses_a_sync_read(self):
        """At 20 s four passes fit the rolling minute: 16 reads, and the
        same burst needs 29 of P2's 28. The refused read is a deferral that
        holds that account's eToro entries until the next read
        (AssetBot._cash_gate, etoro_cells.note_sync_deferred)."""
        syncs, _rereads, _refused, n = self._burst_minute(20)
        self.assertEqual(len(syncs), 4)
        self.assertEqual(n, eb.limit(eb.ACCOUNT, eb.P2))
        self.assertTrue(any(out.get("deferred") or out.get("book_deferred")
                            for out in syncs), syncs)

    def _with_p1_reads(self, k):
        """The same worst minute at the 30 s beat with `k` P1 account reads
        of the orders themselves (their eligibility, the drain's book), at
        5 s: never refused, but counted in the same rolling minute the P2
        limit is judged on. (the sync passes, the accounts whose aggregate
        a pass deferred: their pks)"""
        from bot_program import etoro_cells
        self.clock.t = self.BASE + 5
        for _ in range(k):
            eb.spend(KH, eb.ACCOUNT, eb.P1, where="eligibility",
                     why="the order's eligibility")
        eb.flush()
        syncs, _rereads, _refused, _n = self._burst_minute(
            int(_beat("sync-etoro-accounts")["schedule"]))
        held = {a.pk for a in (self.real, self.demo)
                if etoro_cells.sync_deferred_at(a.pk) is not None}
        return syncs, held

    def test_the_margin_beside_the_orders_own_reads_real_held_last(self):
        """THE REVIEW, V3 (2026-11-13): "25 of P2's 28" counts the P2 reads
        alone. The orders' own P1 reads in that minute leave three: the
        fourth refuses a sync read (a holdings read, its cells still
        written), the fifth defers DEMO's aggregate (its entries wait a
        pass), the seventh REAL's. REAL is read first, so the budget defers
        DEMO first, whatever the accounts' order in the database (DEMO
        first, REAL's was deferred from the fifth). (a sync read refused,
        DEMO's aggregate deferred, REAL's) for k = 0 to 7."""
        from bot_program.models import EtoroAccount
        EtoroAccount.objects.filter(pk=self.real.pk).delete()
        self.real = _account(User.objects.create_user("e30_real_2",
                                                      password="x"))
        self.assertLess(self.demo.pk, self.real.pk, "DEMO first in the base")
        outcomes = {}
        for k in range(0, 8):
            cache.clear()
            eb.forget_all()
            _components()
            syncs, held = self._with_p1_reads(k)
            outcomes[k] = (
                any(out.get("book_deferred") or out.get("deferred")
                    for out in syncs),
                self.demo.pk in held, self.real.pk in held)
        self.assertEqual(outcomes, {
            0: (False, False, False), 1: (False, False, False),
            2: (False, False, False), 3: (False, False, False),
            4: (True, False, False), 5: (True, True, False),
            6: (True, True, False), 7: (True, True, True)})


class RealIsReadFirstTests(TestCase):
    """THE REVIEW, V3 (2026-11-13): the walk read the keyed accounts in no
    stated order; REAL now comes first (demo, then pk), so the request
    budget, a slow pass or a lock that runs out reaches DEMO first."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        _components()
        self.demo = _account(User.objects.create_user("e30_first_d",
                                                      password="x"),
                             demo=True)
        self.real = _account(User.objects.create_user("e30_first_r",
                                                      password="x"))
        self.wire = _AccountWire()
        p = mock.patch(TRADER, side_effect=_over(self.wire))
        p.start()
        self.addCleanup(p.stop)

    def test_real_is_read_before_demo_whatever_their_order_in_the_base(self):
        self.assertLess(self.demo.pk, self.real.pk)
        out = _pass()
        self.assertEqual((out["attempted"], out["stored"]), (2, 2), out)
        self.assertEqual(["demo" if "demo/" in url else "real"
                          for _method, url in self.wire.calls],
                         ["real", "real", "demo", "demo"])


class TheQuotesKeepTwelveARollingMinuteTests(_QuotesCase):
    """Three requests a pass at 15 s: twelve a minute, the feed spec's
    P-c.3 cap, whatever the passes (a run late by its 10 s expiry beside
    the next beat's)."""

    def test_passes_late_and_on_time_never_send_more_than_twelve(self):
        self.assertEqual(eq.SINGLE_READS_PER_PASS, 3)
        self.assertEqual(eq.READS_PER_MINUTE, 12)
        for i in range(1, 9):
            s = f"S{i}"
            _instrument(s, "stock")
            self.client._ids[s] = 100 + i
            self.wire.prices[100 + i] = float(i)
            _held(self.cfg, s)
        clock = _Clock(1_000_000.0)
        sent, at, outs = [], [], []
        with mock.patch.object(eq, "_now", clock):
            for step in (0, 10, 5, 15, 15, 16):
                clock.t += step
                before = len(self.wire.rates())
                outs.append(_refresh())
                n = len(self.wire.rates()) - before
                sent.append(n)
                at += [clock.t] * n
        self.assertEqual(sent, [3, 3, 3, 3, 0, 3])
        self.assertIn("12 reads a minute", outs[4]["stopped"])
        for t in at:
            self.assertLessEqual(sum(1 for u in at if t - 60 < u <= t), 12)


class TheQuotesCapNeverBlanksASteadyPassTests(_QuotesCase):
    """THE REVIEW, M2 (2026-11-13). The cap stamped each read when it
    ENDED and judged a pass's room when it STARTED: with three reads every
    15 s, the fifth pass starts exactly 60 s after the first, whose reads
    ended a little after it started, still inside the minute: the room
    read 0 and every fifth pass sent nothing (four held instruments then
    waited up to 45 s, 30 s at the old beat). A pass's reads are now
    stamped at the instant the pass judged its room: twelve in any minute
    of passes, and a steady pass never blank. Here each read takes 0.25 s
    and the passes are exactly 15 s apart."""

    BASE = 1_900_000_000.0

    def _passes(self, symbols, n=20, read_s=0.25):
        for s in symbols:
            _held(self.cfg, s)
        clock = _Clock(self.BASE)
        wire_get = self.wire.get

        def slow(url, **kw):
            if "/instruments/rates" in url:
                clock.t += read_s
            return wire_get(url, **kw)
        self.wire.get = slow
        sent, reads = [], []
        with mock.patch.object(eq, "_now", clock):
            for k in range(n):
                clock.t = self.BASE + 15 * k
                before = len(self.wire.rates())
                _refresh()
                asked = self.wire.rates()[before:]
                sent.append(len(asked))
                reads += [(15 * k, i) for i in asked]
        return sent, reads

    def _worst_gap(self, reads):
        worst = 0
        for i in {i for _t, i in reads}:
            ats = [t for t, j in reads if j == i]
            worst = max([worst] + [b - a for a, b in zip(ats, ats[1:])])
        return worst

    def _twelve_a_minute(self, sent):
        for k in range(len(sent)):
            self.assertLessEqual(sum(sent[max(0, k - 3):k + 1]), 12, k)

    def test_three_held_instruments_every_pass(self):
        sent, reads = self._passes(["AAA", "BBB", "CCC"])
        self.assertEqual(sent, [3] * 20)
        self.assertEqual(self._worst_gap(reads), 15)
        self._twelve_a_minute(sent)

    def test_four_held_instruments_never_wait_more_than_the_old_30_s(self):
        sent, reads = self._passes(["AAA", "BBB", "CCC", "DDD"])
        self.assertEqual(sent, [3] * 20)
        self.assertEqual(self._worst_gap(reads), 30)
        self._twelve_a_minute(sent)

    def test_a_run_late_by_its_expiry_still_leaves_the_fifth_blank(self):
        """The cap's own case, kept: the beat at 0 ran 10 s late (its
        expiry), so five passes fall inside one minute of starts and the
        fifth sends nothing."""
        for s in ("AAA", "BBB", "CCC", "DDD"):
            _held(self.cfg, s)
        clock = _Clock(self.BASE)
        sent, outs = [], []
        with mock.patch.object(eq, "_now", clock):
            for start in (10, 15, 30, 45, 60, 75):
                clock.t = self.BASE + start
                before = len(self.wire.rates())
                outs.append(_refresh())
                sent.append(len(self.wire.rates()) - before)
        self.assertEqual(sent, [3, 3, 3, 3, 0, 3])
        self.assertIn("12 reads a minute", outs[4]["stopped"])


# ── 6. no pile-up ─────────────────────────────────────────────────────────

class OnePassAtATimeTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        _components()
        self.user = User.objects.create_user("e30_lock", password="x")
        self.acct = _account(self.user)

    def test_a_beat_that_finds_a_pass_running_is_idle(self):
        """No request, no miss, no component row (core.task_gate's idle)."""
        from core.platform_control import PlatformComponent
        cache.add(tasks.ETORO_SYNC_LOCK_KEY, "held", tasks.ETORO_SYNC_LOCK_S)
        before = PlatformComponent.objects.get(key="broker_account_sync")
        with mock.patch(TRADER) as made:
            out = tasks.sync_etoro_accounts.__wrapped__()    # through the gate
        self.assertIn("still running", out["idle"])
        made.assert_not_called()
        self.assertIsNone(cache.get(f"broker_sync:miss:etoro:{self.acct.pk}"))
        after = PlatformComponent.objects.get(key="broker_account_sync")
        self.assertEqual(
            (after.last_run_at, after.last_status, after.run_count),
            (before.last_run_at, before.last_status, before.run_count))
        self.assertEqual(cache.get(tasks.ETORO_SYNC_LOCK_KEY), "held",
                         "a beat never frees another pass's lock")

    def test_the_lock_is_given_back_after_a_pass_and_after_one_that_raised(
            self):
        from bot_program.models import EtoroAccount
        from tests.test_sync_walks_etoro import _client, _sync_etoro
        self.assertEqual(_sync_etoro(_client())["attempted"], 1)
        self.assertIsNone(cache.get(tasks.ETORO_SYNC_LOCK_KEY))
        with mock.patch.object(EtoroAccount.objects, "exclude",
                               side_effect=RuntimeError("the database")), \
                self.assertRaises(RuntimeError):
            _pass()
        self.assertIsNone(cache.get(tasks.ETORO_SYNC_LOCK_KEY))
        self.assertEqual(_sync_etoro(_client())["attempted"], 1)

    def test_a_pass_that_outlived_its_lock_never_frees_the_next_passes(self):
        """THE REVIEW, V2 and N1 (2026-11-13): a pass can outlive the lock's
        180 s (an API host whose several addresses each eat a 10 s connect,
        a DNS stall, a third keyed account); the next beat's pass then
        takes the lock. The first pass, ending, gave the lock back without
        asking whose it was: it freed the second pass's, and the beat after
        started a third beside it. It now gives back only its own."""
        from tests.test_sync_walks_etoro import _client, _sync_etoro

        def the_next_pass_takes_it(*_a, **_kw):
            # mid-pass: the lock ran out and the next beat's pass took it
            cache.set(tasks.ETORO_SYNC_LOCK_KEY, "the next pass",
                      tasks.ETORO_SYNC_LOCK_S)
        with mock.patch.object(tasks, "_warm_etoro_names",
                               side_effect=the_next_pass_takes_it):
            self.assertEqual(_sync_etoro(_client())["attempted"], 1)
        self.assertEqual(cache.get(tasks.ETORO_SYNC_LOCK_KEY),
                         "the next pass")
        with mock.patch(TRADER) as made:
            out = _pass()
        self.assertIn("still running", out["idle"])
        made.assert_not_called()

    def test_the_lock_outlives_the_longest_failing_pass(self):
        """Two accounts, two reads each, each read and its one retry
        timing out on connect AND on read (requests' timeout bounds each),
        the retry's pause between: 163.2 s. The lock holds longer, so a
        slow pass never meets a second; a pass killed mid-way blocks the
        sync three minutes at most."""
        timeout = REAL("k", "u").timeout
        per_read = ((1 + ec.READ_RETRIES) * 2 * timeout
                    + ec.READ_RETRIES * ec.READ_RETRY_DELAY_S)
        self.assertGreaterEqual(tasks.ETORO_SYNC_LOCK_S, 2 * 2 * per_read)
        self.assertLessEqual(tasks.ETORO_SYNC_LOCK_S, 180)

    def test_the_quotes_pass_starts_no_read_it_cannot_end_inside_its_beat(
            self):
        """ON A CONNECTION THAT NEVER OPENS (review N3: the bound is that
        case's alone): a P3 read gives up after its 4 s connect, the
        retry's pause and the retry's 4 s, and a pass starts no read past
        PASS_BUDGET_S, so such a pass ends inside its beat. One pass at a
        time (LOCK_KEY) and a run not started within its expiry dropped:
        no pile-up."""
        give_up = 2 * ec.READ_CONNECT_TIMEOUT_S + ec.READ_RETRY_DELAY_S
        self.assertLessEqual(eq.PASS_BUDGET_S + give_up, eq.BEAT_S)
        self.assertLess(
            _beat("refresh-etoro-quotes")["options"]["expire_seconds"],
            eq.BEAT_S)
        self.assertGreaterEqual(eq.LOCK_S, eq.BEAT_S)

    def test_a_quotes_pass_that_outlives_its_beat_never_meets_another(self):
        """THE REVIEW, V5 and N3 (2026-11-13): a P3 read whose connection
        opens and then never answers waits its 10 s read timeout on each
        attempt: up to 2 x (4 + 10) + 0.8 s, so a pass that starts one at
        PASS_BUDGET_S outlives its 15 s beat. The lock outlives that pass:
        the beats behind it find it held and send nothing, and a run not
        started within its 10 s expiry is dropped. Never two at once."""
        t = REAL("k", "u", env="live")
        self.assertEqual(t._read_timeout(eb.P3), (ec.READ_CONNECT_TIMEOUT_S,
                                                  ec.READ_TIMEOUT_S))
        stalled = (2 * (ec.READ_CONNECT_TIMEOUT_S + ec.READ_TIMEOUT_S)
                   + ec.READ_RETRY_DELAY_S)
        self.assertGreater(eq.PASS_BUDGET_S + stalled, eq.BEAT_S,
                           "said as it is: such a pass outlives its beat")
        self.assertGreaterEqual(eq.LOCK_S, eq.PASS_BUDGET_S + stalled)
        cache.add(eq.LOCK_KEY, 1, eq.LOCK_S)
        self.assertEqual(eq.refresh()["skipped"], "a pass is running")


# ── 7. the quotes' own answer ─────────────────────────────────────────────

class TheQuotesReadTheirOwnAnswerAgainTests(_QuotesCase):
    """The shared rates cache keeps every answer, the beat's own included.
    Skipping what it answered within PREFETCH_FRESH_S (15 s) made a 15 s
    beat skip its own last answer: one read every 30 s (measured at
    1b94a50: 1, 0, 1, 0). The beat skips only an answer younger than half
    its beat."""

    def setUp(self):
        super().setUp()
        self.clock = _Clock(1_900_000_000.0)
        for p in (mock.patch.object(er, "CACHE", True),
                  mock.patch.object(er, "_now", self.clock),
                  mock.patch.object(eq, "_now", self.clock)):
            p.start()
            self.addCleanup(p.stop)
        _held(self.cfg, "AAA")

    def test_own_fresh_is_half_the_beat(self):
        self.assertEqual(eq.OWN_FRESH_S, eq.BEAT_S // 2)
        self.assertEqual(eq.OWN_FRESH_S, 7)

    def test_a_pass_15_s_after_the_last_asks_its_instrument_again(self):
        asked = []
        for _ in range(4):
            before = len(self.wire.rates())
            _refresh()
            asked.append(len(self.wire.rates()) - before)
            self.clock.t += 15
        self.assertEqual(asked, [1, 1, 1, 1])

    def test_an_answer_another_reader_gave_7_s_ago_is_still_skipped(self):
        self.client.ticker("AAA")              # the manage tick's mark
        first = len(self.wire.rates())
        self.clock.t += 7
        out = _refresh()
        self.assertEqual(len(self.wire.rates()), first)
        self.assertEqual(out["left"], {"AAA": "answered in the last seconds"})
        self.clock.t += 1
        _refresh()
        self.assertEqual(len(self.wire.rates()), first + 1)


# ── 8. the words ──────────────────────────────────────────────────────────

class TheWordsTests(TestCase):

    def _read(self, *parts):
        return (Path(settings.BASE_DIR).joinpath(*parts)
                .read_text(encoding="utf-8"))

    def test_the_switch_says_30_s_and_15_s_inside_its_300_characters(self):
        from core.platform_control import DEFAULT_COMPONENTS
        row = next(c for c in DEFAULT_COMPONENTS
                   if c["key"] == "broker_account_sync")
        self.assertIn("eToro every 30 s", row["description"])
        self.assertIn("eToro's own quotes for the open real positions "
                      "every 15 s", row["description"])
        self.assertNotIn("every minute", row["description"])
        self.assertLessEqual(len(row["description"]), 300)

    def test_the_broker_card_says_30_s(self):
        card = self._read("templates", "_partials", "broker_account.html")
        self.assertIn("eToro every 30 s", card)
        self.assertNotIn("eToro every minute", card)

    def test_day_says_30_s_and_15_s(self):
        from core import day_of_sauron as day
        scheme = day.day_scheme()
        whens = {t["key"]: t["when"] for s in scheme["stages"]
                 for t in s["tasks"]}
        self.assertEqual(whens["sync-etoro-accounts"], "30 s")
        self.assertEqual(whens["refresh-etoro-quotes"], "15 s")

    def test_the_treasury_says_the_sync_runs_every_30_s(self):
        from bot_program.broker_vision import sync_every, sync_seconds, vision
        from tests.test_reread_after_orders import _account as _aged
        self.assertEqual(sync_seconds("etoro"), 30.0)
        self.assertEqual(sync_every("etoro"), "30 s")
        self.assertEqual(sync_every("ibkr"), "15 min")
        user = User.objects.create_user("e30_words", password="x")
        _aged(user, age_s=3 * 3600)
        notes = " ".join(vision(user)["notes"])
        self.assertIn("minutes old; the sync runs every 30 s.", notes)

    def test_the_budget_command_says_every_15_s(self):
        cache.clear()
        out = StringIO()
        call_command("etoro_budget", stdout=out)
        self.assertIn("eToro's own quotes (every 15 s)", out.getvalue())

    def test_the_digest_says_every_30_s_not_every_minute(self):
        """THE REVIEW, N2 (2026-11-13): the digest's "stopped" line named
        the 30 s beat "every minute" (whole minutes rounded it to one)."""
        from core.component_digest import _cadence_words
        self.assertEqual(_cadence_words(30 / 3600), "every 30 s")
        self.assertEqual(_cadence_words(15 / 3600), "every 15 s")
        self.assertEqual(_cadence_words(60 / 3600), "every minute")
        self.assertEqual(_cadence_words(300 / 3600), "every 5 minutes")
        self.assertEqual(_cadence_words(0.5), "every 30 minutes")


# ── 9. the money windows do not move ─────────────────────────────────────

class TheMoneyWindowsDoNotMoveTests(SimpleTestCase):
    """Wall-clock windows the money paths read, unchanged by the beats: the
    gates read the sync's cells by the same rules, only fresher."""

    def test_the_windows(self):
        from bot_program import capital_truth, etoro_cells
        from portfolio import services
        self.assertEqual(capital_truth.TRACKING_FRESH_SECONDS, 3600)
        self.assertEqual(capital_truth.CACHE_SECONDS, 900)
        self.assertEqual(etoro_cells.TICKET_FRESH_S, 60)
        self.assertEqual(etoro_cells.COALESCE_S, 20)
        self.assertEqual(etoro_cells.SETTLE_S, 3)
        self.assertEqual(services.ETORO_PNL_MAX_AGE_S, 900)
        self.assertEqual(er.MARK_MAX_AGE_S, 30)
        self.assertEqual(er.PREFETCH_FRESH_S, 15, "the batch's, untouched")

    def test_the_venue_health_rule(self):
        self.assertEqual((vh.SICK_BURST, vh.BURST_WINDOW_S,
                          vh.VENUE_QUIET_MINUTES), (3, 180, 10))
        self.assertEqual(vh.WRITE_SITES, frozenset({"order"}))

    def test_the_budget(self):
        self.assertEqual(eb.rate(eb.ACCOUNT), 30)
        self.assertEqual(eb.limit(eb.ACCOUNT, eb.P2), 28)
        self.assertEqual(eb.limit(eb.ACCOUNT, eb.P5), 15)
        self.assertEqual(eb.rate(eb.MARKET), 60)
        self.assertEqual(eb.limit(eb.MARKET, eb.P3), 54)
