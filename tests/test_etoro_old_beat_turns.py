"""THE OLD BEATS' TURNS, KEPT WHERE THE FASTER BEATS RUN (2026-11-13).

The operator, 2026-11-13: "aussi le refresh etoro par minute est toujours
trop long, je suggère 20-30 secondes non?" The account sync went to 30 s
and eToro's own quotes for the held instruments to 15 s; what the old
beats decided on their own is kept at their pace, by one turn per old beat
and account (venue_health.noting_slot): the pass that holds it notes the
venue's health, the passes between read, write and note nothing. The
final check of the branch (2026-11-13) found two things a faster beat
still did more often than the old one:

  * F2, THE QUOTES' OWN LOCK. A quotes pass can outlive 30 s (a slow
    answer, then a read that opens and stalls). The old 30 s beat behind
    it found the lock held and was gone: its turn was lost. At 15 s the
    beat the lock held left the turn free, and the next pass took it, 15 s
    later: a pass outliving 30 s noted every 45 s (the old beat: every
    60 s), and eToro could be sick sooner than before. A beat that finds
    the lock held now spends the turn of each account whose turn the
    running pass holds, as the old beat's skipped pass lost its own; a
    quiet pass running over an old beat leaves that beat's turn to the
    next pass, as before.
  * F4, THE SHOCK TRIGGER. The sync asked it on every pass, so at 30 s it
    read the equity twice as often, and a dip shorter than a minute was
    caught up to twice as often. A shock plan is an automated money path
    (share_allocator_auto_derisk and the LIVE mode on: applied with no
    human), and it must not change sensitivity as a side effect of a
    display refresh; the operator decides any change to it. The sync now
    asks it from the pass that holds the account's turn only: at most once
    per old 60 s beat, a pass that holds the turn and reads nothing
    spending it, as the old beat's did. The pools are still resized from
    every pass.

Fakes only: no network, broker or model call.

Run with:  python manage.py test tests.test_etoro_old_beat_turns
"""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from bot_program import etoro_quotes as eq
from bot_program import tasks
from bot_program import venue_health as vh
from bot_program.engine import etoro_client as ec
from tests.test_etoro_rates_batch import _Clock, _held
from tests.test_etoro_sync_30s import (TRADER, _AccountWire, _failures,
                                       _over, _pass)
from tests.test_faster_refresh import _account, _components, _QuotesCase

UTC = dt_tz.utc


# ── F2: a quotes beat the lock holds spends the old beat's turn ──────────

class AQuotesBeatTheLockHoldsSpendsTheOldBeatsTurnTests(_QuotesCase):
    """eToro's own quotes for one held instrument. From `down` on, every
    rates GET waits `stall` seconds and then answers 503 (the read and its
    one bounded retry: a pass of twice `stall`). A beat that comes while a
    pass runs is served INSIDE that wait, as the worker would serve it
    beside the running pass: refresh() then meets the running pass's own
    lock, with the value that pass left in it."""

    BASE = 1_900_000_000.0

    def setUp(self):
        super().setUp()
        p = mock.patch("bot_program.notifications.notify_staff")
        p.start()
        self.addCleanup(p.stop)
        _held(self.cfg, "AAA")

    def _beats(self, *, n, stall, down):
        clock = _Clock(self.BASE)
        t0 = datetime.fromtimestamp(self.BASE, tz=UTC)
        beats = [15 * k for k in range(n)]
        outs = {}
        wire_get = self.wire.get

        def serve(until):
            for b in beats:
                if b not in outs and clock.t < self.BASE + b <= until:
                    clock.t = self.BASE + b
                    outs[b] = eq.refresh()
            clock.t = until

        def stalling(url, **kw):
            if "/instruments/rates" in url and clock.t >= self.BASE + down:
                self.wire.status = [503]
                serve(clock.t + stall)
            return wire_get(url, **kw)
        self.wire.get = stalling
        with mock.patch.object(eq, "_now", clock), \
                mock.patch("django.utils.timezone.now",
                           side_effect=lambda: datetime.fromtimestamp(
                               clock.t, tz=UTC)):
            for b in beats:
                if b in outs:
                    continue
                clock.t = self.BASE + b
                outs[b] = eq.refresh()
        noted = [(parse_datetime(f["at"]) - t0).total_seconds()
                 for f in _failures()]
        return outs, noted

    def test_a_pass_outliving_30_s_notes_no_closer_than_the_old_beat(self):
        """Every failing pass is 34 s (two 17 s waits). The old 30 s beat
        ran passes at 0, 60, 120, 180 (the beats at 30, 90, 150 found the
        lock held and were gone: their turns lost) and noted at 34, 94,
        154, 214. The 15 s beat runs passes at 0, 45, 90, 135, 180 (the
        lock holds 15, 30, 60, 75, ...): at 6446516 every one of them took
        the turn the lock-held beat had left free, and noted every 45 s
        (34, 79, 124: eToro sick at 124, 30 s sooner than the old beat).
        Now the beat the lock holds at 30 spends the turn the running pass
        holds, as the old beat's did: the pass at 45 reads and notes
        nothing, the one at 90 notes. Never closer than the old 60 s;
        fewer here (there is no pass at 60 to note): later, never
        sooner."""
        outs, noted = self._beats(n=15, stall=17.0, down=0)
        self.assertEqual(noted, [34.0, 124.0, 214.0])
        self.assertTrue(all(b - a >= 60 for a, b in zip(noted, noted[1:])))
        for s in (15, 30, 60, 75, 105, 120, 150, 165):
            self.assertEqual(outs[s].get("skipped"), "a pass is running", s)
        for s in (0, 45, 90, 135, 180):
            self.assertIn("stopped", outs[s], s)
        self.assertEqual(len(self.wire.rates()), 10,
                         "the passes asked eToro; the beats the lock held "
                         "sent nothing")

    def test_a_quiet_pass_over_an_old_beat_leaves_its_turn_to_the_next(
            self):
        """WHAT THE FIX MUST NOT TAKE AWAY (green at 6446516 by design).
        Healthy passes at 0, 15, 30 (the turns at 0 and 30), then from
        44 s every read stalls 10.5 s and fails, its retry the same (21 s a
        pass, as under read timeouts). The pass at 45
        is a quiet one, between two old beats; it runs over the old beat
        at 60, which finds the lock held. That beat's turn is NOT the
        running pass's, so it is left to the next pass: the pass at 75
        notes, and so does every pass after it, 30 s apart (noted at 96,
        126, 156: sick at 156; the old 30 s beat noted at 81, 111, 141:
        15 s later, never sooner). Spending it would have left every pass
        of the outage quiet: each one runs over the next old beat."""
        outs, noted = self._beats(n=12, stall=10.5, down=44)
        self.assertEqual(noted, [96.0, 126.0, 156.0])
        self.assertEqual(outs[60].get("skipped"), "a pass is running")
        self.assertIsNotNone(vh.sick(
            "etoro", "live", now=datetime.fromtimestamp(self.BASE + 156,
                                                        tz=UTC)))

    def test_a_beat_the_lock_holds_never_fails_on_its_accounts(self):
        """A beat the lock holds looks for the turns to spend over the
        accounts a pass reads (at 6446516 it looked at nothing). They
        cannot be read here: it still says the pass is running, raises
        nothing, sends nothing and spends nothing."""
        cache.add(eq.LOCK_KEY, "a running pass", eq.LOCK_S)
        with mock.patch.object(eq, "_accounts",
                               side_effect=RuntimeError("the database")) \
                as accounts:
            out = eq.refresh()
        self.assertEqual(accounts.call_count, 1)
        self.assertEqual(out["skipped"], "a pass is running")
        self.assertEqual(self.wire.rates(), [])
        self.assertIsNone(cache.get(eq.NOTE_KEY.format(pk=self.acct.pk)))


# ── F4: the shock trigger at the old 60 s beat ───────────────────────────

class TheShockTriggerKeepsTheOldBeatTests(TestCase):
    """The eToro book (keyed, flagged primary) on a fake wire: each pass
    reads the aggregate (equity 1000 USD) and the book. The old 60 s beat
    asked the shock trigger once a minute; the 30 s passes ask it from the
    pass that holds the account's turn, the old beat's."""

    def setUp(self):
        cache.clear()
        vh.reset()
        self.addCleanup(cache.clear)
        self.addCleanup(vh.reset)
        _components()
        for p in (mock.patch.object(ec, "READ_RETRY_DELAY_S", 0.0),
                  mock.patch("bot_program.notifications.notify_staff")):
            p.start()
            self.addCleanup(p.stop)
        self.user = User.objects.create_user("obt_shock", password="x")
        self.acct = _account(self.user)
        self.wire = _AccountWire()
        p = mock.patch(TRADER, side_effect=_over(self.wire))
        p.start()
        self.addCleanup(p.stop)
        self.t0 = timezone.now().replace(microsecond=0)

    def _at(self, s):
        return self.t0 + timedelta(seconds=s)

    def _pass_at(self, s):
        with mock.patch("django.utils.timezone.now",
                        return_value=self._at(s)):
            return _pass()

    def _asked_at(self, shock):
        return [round((c.args[1] - self.t0).total_seconds())
                for c in shock.call_args_list]

    def test_30_s_passes_ask_it_on_every_other_pass(self):
        """Six passes 30 s apart: the trigger at 0, 60 and 120, as the old
        beat's three passes; the pools resized from all six."""
        with mock.patch.object(tasks, "_shock_trigger") as shock, \
                mock.patch.object(tasks, "_follow_the_account") as follow:
            for s in (0, 30, 60, 90, 120, 150):
                out = self._pass_at(s)
                self.assertEqual(out["stored"], 1, (s, out))
        self.assertEqual(self._asked_at(shock), [0, 60, 120])
        self.assertTrue(all(c.args[0] == self.user
                            for c in shock.call_args_list))
        self.assertEqual(follow.call_count, 6)

    def test_a_pass_that_holds_the_turn_and_reads_nothing_spends_it(self):
        """A miss at 0 (503 on both reads) holds the turn: it notes the
        venue's health and has no reading to ask about. The pass at 30
        reads the equity but holds no turn: no trigger, as no old beat
        ran there. The pass at 60 holds it and asks. One turn, two uses:
        the pass that noted is the pass that would have asked."""
        self.wire.status = 503
        with mock.patch.object(tasks, "_shock_trigger") as shock:
            with self.assertLogs("bot_program.tasks", level="WARNING"):
                self.assertEqual(self._pass_at(0)["unreachable"], 1)
            self.assertEqual([f["where"] for f in _failures()],
                             ["account", "portfolio"])
            self.wire.status = 200
            for s in (30, 60):
                self.assertEqual(self._pass_at(s)["stored"], 1, s)
        self.assertEqual(self._asked_at(shock), [60])
        self.assertEqual(len(_failures()), 2, "nothing failed after 0")

    def test_a_pass_the_budget_deferred_spends_its_turn_too(self):
        """The request budget did not send the aggregate at 0: a deferral,
        never a miss, and the turn it held is spent (as the old beat's
        deferred pass asked nothing). The pass at 30 asks nothing; the one
        at 60 asks."""
        refused = RuntimeError("the account minute keeps its floor")
        refused.budget_refused = True
        real_read = tasks._read_etoro_aggregate
        calls = {"n": 0}

        def first_refused(client):
            calls["n"] += 1
            if calls["n"] == 1:
                raise refused
            return real_read(client)
        with mock.patch.object(tasks, "_shock_trigger") as shock, \
                mock.patch.object(tasks, "_read_etoro_aggregate",
                                  side_effect=first_refused):
            self.assertEqual(self._pass_at(0).get("deferred"), 1)
            for s in (30, 60):
                self.assertEqual(self._pass_at(s)["stored"], 1, s)
        self.assertEqual(self._asked_at(shock), [60])

    def test_a_beat_the_lock_holds_and_a_late_run_never_ask_twice_a_minute(
            self):
        """The pass at 0 asks. The beat at 30 finds a pass running (the
        lock held): idle, nothing read, nothing asked. The 60 s beat's run
        starts 15 s late, at 75, and holds the turn; the passes at 90 and
        120 come inside its minute and ask nothing; the one at 150 asks.
        At 6446516 every pass that read asked: 0, 75, 90, 120, 150."""
        with mock.patch.object(tasks, "_shock_trigger") as shock:
            self.assertEqual(self._pass_at(0)["stored"], 1)
            cache.add(tasks.ETORO_SYNC_LOCK_KEY, "a running pass",
                      tasks.ETORO_SYNC_LOCK_S)
            self.assertIn("still running", self._pass_at(30)["idle"])
            cache.delete(tasks.ETORO_SYNC_LOCK_KEY)
            for s in (75, 90, 120, 150):
                self.assertEqual(self._pass_at(s)["stored"], 1, s)
        self.assertEqual(self._asked_at(shock), [0, 75, 150])
        asked = self._asked_at(shock)
        self.assertTrue(all(b - a >= tasks.ETORO_SYNC_NOTE_EVERY_S
                            for a, b in zip(asked, asked[1:])))

    def test_the_pass_that_holds_the_turn_proposes_the_shock_plan_as_before(
            self):
        """The book's equity was 1100 twelve hours ago and the pass reads
        1000: 9.1 % under, a shock. The pass that holds the turn proposes
        the shock plan and tells the staff, as the old beat's pass did
        (tests.test_share_allocator, tests.test_shock_plan_once); the pass
        30 s later does not even look; the one at 60 looks, and the plan
        still unanswered holds the door."""
        from bot_program.equity_models import BrokerEquityReading
        from bot_program.share_allocator import shock_detected
        from bot_program.share_models import SharePlan
        from tests.test_share_allocator import _cfg, _enable
        _enable("pipeline_share_allocator", "broker_account_sync")
        BrokerEquityReading.objects.create(
            broker="etoro", account_pk=self.acct.pk, value=Decimal("1100"),
            currency="USD", env="live", at=self.t0 - timedelta(hours=12))
        _cfg(self.user, name="a", tracks=True, share=50, capital="1000")
        _cfg(self.user, name="b", tracks=True, share=50, capital="1000")
        looked = []

        def spy(user, *, now=None):
            looked.append(round((now - self.t0).total_seconds()))
            return shock_detected(user, now=now)
        with mock.patch("bot_program.share_allocator.shock_detected",
                        side_effect=spy), \
                mock.patch("bot_program.notifications.notify_staff") as told:
            for s in (0, 30, 60):
                self.assertEqual(self._pass_at(s)["stored"], 1, s)
        self.assertEqual(looked, [0, 60])
        plans = list(SharePlan.objects.filter(user=self.user))
        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].mode, "shock")
        self.assertEqual(plans[0].state, SharePlan.STATE_PROPOSED)
        self.assertIn("equity −9.1% in 24h", plans[0].mode_reasons)
        shock_told = [c for c in told.call_args_list
                      if c.kwargs.get("title") == "⚠ Shock plan proposed"]
        self.assertEqual(len(shock_told), 1)
        self.assertEqual(shock_told[0].kwargs["url"], "/shares/")
