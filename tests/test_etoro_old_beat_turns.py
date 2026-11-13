"""THE OLD BEATS' TURNS, KEPT WHERE THE FASTER BEATS RUN (2026-11-13).

The operator, 2026-11-13: "aussi le refresh etoro par minute est toujours
trop long, je suggère 20-30 secondes non?" The account sync went to 30 s
and eToro's own quotes for the held instruments to 15 s; what the old
beats decided on their own is kept at their pace, by one turn per window
of the old beat and account (venue_health.old_beat_turn): the pass that
holds it notes the venue's health, the passes between read, write and
note nothing. The final check of the branch (2026-11-13) found two things
a faster beat still did more often than the old one:

  * F2, THE QUOTES' OWN LOCK. A quotes pass can outlive 30 s (a slow
    answer, then a read that opens and stalls). The old 30 s beat behind
    it found the lock held and was gone: its turn was lost. At 15 s the
    beat the lock held left the turn free, and the next pass took it, 15 s
    later: a pass outliving 30 s noted every 45 s (the old beat: every
    60 s), and eToro could be sick sooner than before. A beat that finds
    the lock held now spends its own window's turn when the running pass
    holds the turn it took as the first beat of its own window (the old
    beat's place on the grid), as the old beat's skipped pass lost its
    own; behind a quiet pass, or one that took its turn after its window's
    first beat found the lock held, it spends nothing and the window's
    next pass takes the turn, as before.
  * F4, THE SHOCK TRIGGER. The sync asked it on every pass, so at 30 s it
    read the equity twice as often, and a dip shorter than a minute was
    caught up to twice as often. A shock plan is an automated money path
    (share_allocator_auto_derisk and the LIVE mode on: applied with no
    human), and it must not change sensitivity as a side effect of a
    display refresh; the operator decides any change to it. The sync now
    asks it from the pass that holds the account's turn only: once per
    minute window, a pass that holds the turn and reads nothing spending
    it, as the old beat's did. The pools are still resized from every
    pass.

THE THIRD ROUND, A FIXED GRID (the recheck, 2026-11-13). The turns were
taken once the old beat's interval less 5 s (55 s, 25 s) had gone by since
the LAST one. On time that is one turn per old beat; but a turn taken by a
pass more than 5 s late, or a pass that outlived its beat, moved every
turn after it: with sync passes 0 to 24 s late the shock trigger was asked
15 % less often than at 60 s, a late quotes beat could make eToro sick up
to 57 s sooner, and after a timeout incident the notes stayed off the old
beats. Each turn is now the FIRST pass of its window of the old beat's
length on the clock (floor(epoch / 60) for the sync and the shock
trigger, floor(epoch / 30) for the quotes), keyed on the instant the beat
SENT the run (tasks._beat_sent_at: the run's `expires` less the entry's
expiry), or on its start when the run carries none (called directly, as
most tests here do): never two in one window, one in every window a run
reaches, late or not, and nothing to drift. A beat the lock holds spends
its window's quotes turn only behind a pass that took its own as its
window's first beat (where the old beat stood).

Fakes only: no network, broker or model call.

Run with:  python manage.py test tests.test_etoro_old_beat_turns
"""
import random
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
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
#: An instant on the minute (and so on the half minute): the grid's
#: windows start there, every 60 s for the sync, every 30 s for the quotes.
ON_THE_MINUTE = 1_900_000_020.0


def _firsts(instants, window_s):
    """The first of `instants` (seconds after an instant on the minute) in
    each window of `window_s` seconds, in order."""
    first = {}
    for t in sorted(instants):
        first.setdefault(int(t // window_s), t)
    return [first[w] for w in sorted(first)]


# ── The grid itself ───────────────────────────────────────────────────────

class TheOldBeatTurnTests(SimpleTestCase):
    """venue_health.old_beat_turn: the first pass keyed in each window of
    the old beat's length on the clock (here on its start, `at`) holds
    that window's turn; every other pass of the window reads only."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def test_the_first_pass_of_each_window_holds_its_turn(self):
        t = ON_THE_MINUTE
        turns = [vh.old_beat_turn("obt:a", 60, at=t + s)
                 for s in (0, 30, 59.9, 60, 61, 119.9, 150, 179)]
        self.assertEqual(turns, [True, False, False, True, False, False,
                                 True, False])

    def test_a_window_whose_first_pass_is_late_still_has_one_turn(self):
        """The window's turn waits for its first pass, however late in the
        window it starts; the next window's first pass holds the next turn,
        here one second later: never two in one window, but two windows'
        turns can sit close at their edge."""
        t = ON_THE_MINUTE
        self.assertTrue(vh.old_beat_turn("obt:b", 60, at=t + 59))
        self.assertFalse(vh.old_beat_turn("obt:b", 60, at=t + 59.5))
        self.assertTrue(vh.old_beat_turn("obt:b", 60, at=t + 60))

    def test_never_two_turns_in_one_window_whatever_the_instants(self):
        rng = random.Random(109)
        for beat in (60, 30):
            key = f"obt:c:{beat}"
            t, seen = 0.0, []
            for _ in range(400):
                t += rng.uniform(0.0, 0.9 * beat)
                seen.append((t, vh.old_beat_turn(key, beat,
                                                  at=ON_THE_MINUTE + t)))
            held = [s for s, turn in seen if turn]
            self.assertEqual(held, _firsts([s for s, _turn in seen], beat),
                             beat)

    def test_each_account_and_each_beat_its_own(self):
        t = ON_THE_MINUTE
        self.assertTrue(vh.old_beat_turn("etoro_sync:noting:1", 60, at=t))
        self.assertTrue(vh.old_beat_turn("etoro_sync:noting:2", 60, at=t))
        self.assertTrue(vh.old_beat_turn("etoro_quotes:noting:1", 30, at=t))
        self.assertFalse(vh.old_beat_turn("etoro_sync:noting:1", 60,
                                          at=t + 1))

    def test_an_unreadable_cache_notes_as_before_the_turns(self):
        with mock.patch.object(cache, "add",
                               side_effect=RuntimeError("down")):
            self.assertTrue(vh.old_beat_turn("obt:d", 60, at=ON_THE_MINUTE))
            self.assertTrue(vh.old_beat_turn("obt:d", 60,
                                              at=ON_THE_MINUTE + 1))
        self.assertTrue(vh.old_beat_turn("obt:e", 60, at="not an instant"))


# ── F2: a quotes beat the lock holds spends the old beat's turn ──────────

class AQuotesBeatTheLockHoldsSpendsTheOldBeatsTurnTests(_QuotesCase):
    """eToro's own quotes for one held instrument. From `down` on, every
    rates GET waits `stall` seconds and then answers 503 (the read and its
    one bounded retry: a pass of twice `stall`). A beat that comes while a
    pass runs is served INSIDE that wait, as the worker would serve it
    beside the running pass: refresh() then meets the running pass's own
    lock, with the value that pass left in it. The beats sit 10 s past
    each half minute of the clock: the first of each 30 s window is the
    old beat's (0, 30, 60, ...)."""

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
        Now the beat the lock holds at 30 spends its window's turn (the
        running pass took its own as its window's first beat), as the old
        beat's did: the pass at 45 reads and notes nothing, the one at 90
        notes. With the
        beats on time and the old beat's instants first in their windows,
        as here: never closer than the old 60 s; fewer (there is no pass
        at 60 to note): later or not at all, never sooner."""
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
        15 s later, never sooner). The beat at 60 marks its window: the
        pass at 75 takes that window's turn second, not where the old beat
        ran, so the beats at 90 and 120, behind such passes, spend
        nothing. Spending it would have left every pass of the outage
        quiet: each one runs over the next old beat."""
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
        nothing, sends nothing and spends nothing: the next pass of its
        window, on a wire answering 503, holds the turn and notes."""
        clock = _Clock(ON_THE_MINUTE)
        cache.add(eq.LOCK_KEY, "a running pass", eq.LOCK_S)
        with mock.patch.object(eq, "_now", clock):
            with mock.patch.object(eq, "_accounts",
                                   side_effect=RuntimeError("the database")) \
                    as accounts:
                out = eq.refresh()
            self.assertEqual(accounts.call_count, 1)
            self.assertEqual(out["skipped"], "a pass is running")
            self.assertEqual(self.wire.rates(), [])
            cache.delete(eq.LOCK_KEY)
            self.wire.status = [503]
            clock.t += 1
            out = eq.refresh()
        self.assertIn("stopped", out)
        self.assertEqual([f["where"] for f in _failures()], ["ticker"])


# ── The quotes' turns on the grid ─────────────────────────────────────────

def _quotes_beats(case, beats, *, base, trouble=None):
    """eq.refresh() at each of `beats` (seconds after `base`, ascending) on
    a clock the test moves. `trouble(t)` gives (wait_s, status) for a
    rates GET sent t seconds after `base`, or None (answered at once,
    200): the GET waits `wait_s` and answers `status`, and a beat that
    comes during the wait is served inside it, as the worker serves it
    beside the running pass (refresh() then meets that pass's own lock).
    Returns ({beat: out}, [seconds after `base` of each noted failure],
    [seconds after `base` of each pass that held its account's turn])."""
    clock = _Clock(base)
    t0 = datetime.fromtimestamp(base, tz=UTC)
    outs, held = {}, []
    wire_get = case.wire.get
    quiet = eq._quiet_between_noting_passes

    def serve(until):
        for b in beats:
            if b not in outs and clock.t < base + b <= until:
                clock.t = base + b
                outs[b] = eq.refresh()
        clock.t = until

    def get(url, **kw):
        if "/instruments/rates" in url:
            wait, status = (trouble(clock.t - base) if trouble else None) \
                or (0.0, 200)
            if wait:
                serve(clock.t + wait)
            case.wire.status = [status]
        return wire_get(url, **kw)

    def spy(*args, **kwargs):
        holds = quiet(*args, **kwargs)
        if holds:
            held.append(round(clock.t - base, 3))
        return holds
    case.wire.get = get
    with mock.patch.object(eq, "_now", clock), \
            mock.patch.object(eq, "_quiet_between_noting_passes",
                              side_effect=spy), \
            mock.patch("django.utils.timezone.now",
                       side_effect=lambda: datetime.fromtimestamp(
                           clock.t, tz=UTC)):
        for b in beats:
            if b in outs:
                continue
            clock.t = base + b
            outs[b] = eq.refresh()
    noted = [(parse_datetime(f["at"]) - t0).total_seconds()
             for f in _failures()]
    return outs, noted, held


class TheQuotesTurnsSitOnTheGridTests(_QuotesCase):
    """eToro's own quotes for one held instrument, each account's turn the
    first pass of its 30 s window of the clock (called directly, so keyed
    on its start; the windows start on the minute and the half minute
    here)."""

    def setUp(self):
        super().setUp()
        p = mock.patch("bot_program.notifications.notify_staff")
        p.start()
        self.addCleanup(p.stop)
        _held(self.cfg, "AAA")

    def test_a_late_beat_never_notes_twice_in_one_window(self):
        """The 15 s beat at 10 s past each half minute (10, 25, 40, 55, 70,
        85), on a wire answering 503; the beat of 55 runs 5 s late, at 60,
        inside its 10 s expiry. Passes at 25, 40, 60, 70 and 85: the first
        of each window holds its turn and notes, at 25, 40 and 60, and
        eToro is sick at 60 (three in 180 s): the passes at 70 and 85 skip.
        At ae83e10 a turn came 25 s after the last: notes at 25, 60 and 85,
        two in the window from 60 to 90."""
        outs, noted, _held_by = _quotes_beats(
            self, [25, 40, 60, 70, 85], base=ON_THE_MINUTE,
            trouble=lambda t: (0.0, 503))
        self.assertEqual(noted, [25.0, 40.0, 60.0])
        self.assertEqual(len({int(n // 30) for n in noted}), len(noted))
        for s in (70, 85):
            self.assertIn("eToro is sick", outs[s].get("skipped", ""), s)

    def test_beats_up_to_10_s_late_hold_one_turn_in_every_window(self):
        """Eighty beats 15 s apart, each late by up to 9.9 s (inside the
        10 s expiry; drawn with a fixed seed), on a healthy wire: in every
        30 s window the first pass to start holds the turn, and no other
        does: one turn per window of the old 30 s beat, never more, never
        none. At ae83e10 the turns slid behind the late ones."""
        rng = random.Random(15)
        beats = [15 * k + 5 + rng.uniform(0.0, 9.9) for k in range(80)]
        _outs, noted, held = _quotes_beats(self, beats, base=ON_THE_MINUTE)
        self.assertEqual(noted, [])
        self.assertEqual(held, [round(b, 3) for b in _firsts(beats, 30)])

    def test_after_a_timeout_incident_the_turns_come_back_to_the_grid(self):
        """A read-timeout outage from 44 s to 140 s: every rates read sent
        then waits 10.5 s and answers 503, so a pass is 21 s and the
        passes the lock leaves run between the old beats (45, 75, 105,
        135): the turns go to the first of them in each window, as before
        (noted at 96 and 126; the pass at 135 is answered on its retry).
        Once it is over, the first pass of each window holds the turn
        again: 150, 180, 210, 240, the instants the old 30 s beat ran, and
        a 5xx hiccup at 240 is noted at 240. At ae83e10 the turns stayed
        15 s off the old beat (165, 195, 225, 255) and the pass at 240,
        quiet, noted nothing."""
        def trouble(t):
            if 44 <= t < 140:
                return (10.5, 503)
            if 239 <= t < 241:
                return (0.0, 503)
            return None
        _outs, noted, held = _quotes_beats(
            self, [15 * k for k in range(18)], base=ON_THE_MINUTE,
            trouble=trouble)
        self.assertEqual(held[:5], [0.0, 30.0, 75.0, 105.0, 135.0])
        self.assertEqual(held[5:], [150.0, 180.0, 210.0, 240.0])
        self.assertEqual(noted, [96.0, 126.0, 240.0])

    def test_a_late_long_pass_spends_the_old_beats_next_turn(self):
        """A price-read stall: every rates read waits 16.85 s and answers
        503 (a pass of 33.7 s). The beat at 10 s past the half minute runs
        9.4 s late, at 19.4, first in its half minute, and holds the turn;
        the beats at 27 and 41 find it running. The one at 41 stands where
        the old beat's next one stood (first in the next half minute): it
        spends that half minute's turn, so the pass at 58.1 reads and
        notes nothing; the one at 92.4 notes. Noted at 53.1 and 126.1: not
        sick. The old 30 s beat, run at this phase with the same lateness,
        lost its beat at 41 too and noted at 53.1 and 105.7. At ae83e10,
        and with a beat spending the turn only 25 s or more after it was
        taken (the turn here taken 21.6 s before), the pass at 58.1 noted
        too: 53.1, 91.8, 126.1, and eToro sick at 126.1 (the recheck's
        late-beat stall: up to 57.3 s sooner than the old beat)."""
        _outs, noted, held = _quotes_beats(
            self, [19.4, 27.0, 41.0, 58.1, 72.0, 92.4], base=ON_THE_MINUTE,
            trouble=lambda t: (16.85, 503))
        self.assertEqual([round(n, 1) for n in noted], [53.1, 126.1])
        self.assertEqual(held, [19.4, 92.4])
        self.assertIsNone(vh.sick("etoro", "live", now=datetime.fromtimestamp(
            ON_THE_MINUTE + 126.2, tz=UTC)))

    def test_a_pass_etoro_being_sick_skips_still_spends_its_window(self):
        """The pass at 0 finds eToro sick and reads nothing: it spends its
        window's turn, as the old beat's skipped pass did. The pass at 15,
        on a wire answering 503, reads and notes nothing; the one at 30,
        the next window's first, notes. (Green at ae83e10 too: what the
        grid must keep.)"""
        real = vh.sick
        calls = {"n": 0}

        def sick_first(venue, world, now=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return {"words": "the test's"}
            return real(venue, world, now=now)
        with mock.patch.object(vh, "sick", side_effect=sick_first):
            outs, noted, _held_by = _quotes_beats(
                self, [0, 15, 30], base=ON_THE_MINUTE,
                trouble=lambda t: (0.0, 503))
        self.assertIn("eToro is sick", outs[0]["skipped"])
        self.assertIn("stopped", outs[15])
        self.assertEqual(noted, [30.0])

    def test_a_pass_with_nothing_to_ask_still_spends_its_window(self):
        """The pass at 0 has nothing to ask (another reader's answer is
        fresh): it spends its window's turn. The pass at 15 (503) notes
        nothing; the one at 30 notes. (Green at ae83e10 too.)"""
        real = eq._wanted
        calls = {"n": 0}

        def nothing_first(client, rows):
            calls["n"] += 1
            if calls["n"] == 1:
                return [], {"AAA": "answered in the last seconds"}
            return real(client, rows)
        with mock.patch.object(eq, "_wanted", side_effect=nothing_first):
            outs, noted, _held_by = _quotes_beats(
                self, [0, 15, 30], base=ON_THE_MINUTE,
                trouble=lambda t: (0.0, 503))
        self.assertEqual(outs[0]["asked"], 0)
        self.assertEqual(noted, [30.0])

    def test_an_unreadable_turn_notes_as_before_the_turns(self):
        """The cache refuses the turn's key: every pass notes, as before
        the turns existed, and nothing raises. (Green at ae83e10 too.)"""
        real_add = cache.add

        def add(key, *args, **kwargs):
            if "noting" in str(key):
                raise RuntimeError("the cache is down")
            return real_add(key, *args, **kwargs)
        with mock.patch.object(cache, "add", side_effect=add):
            _outs, noted, _held_by = _quotes_beats(
                self, [0, 15], base=ON_THE_MINUTE,
                trouble=lambda t: (0.0, 503))
        self.assertEqual(noted, [0.0, 15.0])


# ── F4: the shock trigger at the old 60 s beat ───────────────────────────

class TheShockTriggerKeepsTheOldBeatTests(TestCase):
    """The eToro book (keyed, flagged primary) on a fake wire: each pass
    reads the aggregate (equity 1000 USD) and the book. The old 60 s beat
    asked the shock trigger once a minute; the 30 s passes ask it from the
    pass that holds the account's turn: the first to start in each minute
    of the clock. The passes here start on the minute (t0)."""

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
        # ON THE MINUTE (the third round): the turns are the clock's
        # minutes, so the passes' instants are counted from one.
        self.t0 = timezone.now().replace(second=0, microsecond=0)

    def _at(self, s):
        return self.t0 + timedelta(seconds=s)

    def _pass_at(self, s):
        with mock.patch("django.utils.timezone.now",
                        return_value=self._at(s)):
            return _pass()

    def _asked_at(self, shock):
        return [round((c.args[1] - self.t0).total_seconds(), 3)
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
        starts 15 s late, at 75, and holds its minute's turn; the pass at
        90 comes inside that minute and asks nothing; the one at 120, the
        next minute's first, asks, as the old 60 s beat's next pass did.
        At 6446516 every pass that read asked: 0, 75, 90, 120, 150. At
        ae83e10 (a turn 55 s after the last) the ask moved to 150, and
        every ask after it 30 s off the old beat."""
        with mock.patch.object(tasks, "_shock_trigger") as shock:
            self.assertEqual(self._pass_at(0)["stored"], 1)
            cache.add(tasks.ETORO_SYNC_LOCK_KEY, "a running pass",
                      tasks.ETORO_SYNC_LOCK_S)
            self.assertIn("still running", self._pass_at(30)["idle"])
            cache.delete(tasks.ETORO_SYNC_LOCK_KEY)
            for s in (75, 90, 120, 150):
                self.assertEqual(self._pass_at(s)["stored"], 1, s)
        asked = self._asked_at(shock)
        self.assertEqual(asked, [0, 75, 120])
        self.assertEqual(len({a // 60 for a in asked}), len(asked),
                         "one ask a minute of the clock, never two")

    def test_passes_late_by_up_to_24_s_ask_once_in_every_minute(self):
        """Forty beats 30 s apart, each late by up to 24 s (inside the
        25 s expiry; drawn with a fixed seed). The first pass of each
        minute asks, and no other: twenty asks in twenty minutes, at the
        very instants the old 60 s beat's passes, late by the same, asked
        (the even beats). At ae83e10 a turn came 55 s after the last, so a
        claiming pass more than 5 s late on its beat cost the next one
        (the recheck: 15 % fewer asks over such passes)."""
        rng = random.Random(24)
        starts = [30 * k + rng.uniform(0.0, 24.0) for k in range(40)]
        with mock.patch.object(tasks, "_shock_trigger") as shock:
            for s in starts:
                self.assertEqual(self._pass_at(s)["stored"], 1, s)
        self.assertEqual(self._asked_at(shock),
                         [round(s, 3) for s in starts[0::2]])

    def test_late_passes_keep_their_minutes_turn(self):
        """The beats at 0, 30, ..., 180 run 20, 10, 0, 20, 10, 0 and 20 s
        late: passes at 20, 40, 60, 110, 130, 150, 200. Each minute's first
        asks: 20, 60, 130, 200, as the old 60 s beat (its passes at 20, 60,
        130, 200). At ae83e10: 20, 110, 200, no ask in the minute from 120
        to 180."""
        with mock.patch.object(tasks, "_shock_trigger") as shock:
            for s in (20, 40, 60, 110, 130, 150, 200):
                self.assertEqual(self._pass_at(s)["stored"], 1, s)
        self.assertEqual(self._asked_at(shock), [20, 60, 130, 200])

    def test_a_quiet_pass_outliving_its_beat_leaves_the_asks_on_the_grid(
            self):
        """The pass at 30, between two old beats, outlives its beat: the
        beat at 60 finds it running (the lock) and reads nothing. The
        minute from 60 is asked by its next pass, at 90 (the old 60 s beat,
        with no lock, read and asked at 60), and the next minutes by their
        first passes, 120 and 180, the old beat's instants. At ae83e10 the
        turn went 55 s after the last ask: 90, then 150, 210, ... 30 s off
        the old beat for good."""
        with mock.patch.object(tasks, "_shock_trigger") as shock:
            for s in (0, 30):
                self.assertEqual(self._pass_at(s)["stored"], 1, s)
            cache.add(tasks.ETORO_SYNC_LOCK_KEY, "the pass of 30",
                      tasks.ETORO_SYNC_LOCK_S)
            self.assertIn("still running", self._pass_at(60)["idle"])
            cache.delete(tasks.ETORO_SYNC_LOCK_KEY)
            for s in (90, 120, 150, 180, 210):
                self.assertEqual(self._pass_at(s)["stored"], 1, s)
        self.assertEqual(self._asked_at(shock), [0, 90, 120, 180])

    def test_after_a_long_pass_a_5xx_is_noted_where_the_old_beat_noted_it(
            self):
        """A timeout incident: the pass at 60 outlives two beats (90 and
        120 find it running). Then a 5xx hiccup meets the pass at 300
        alone. The minute from 120 is held by its next pass, 150; the next
        minutes by their first passes, 180, 240, 300: the hiccup is noted
        at 300 (both reads), where the old 60 s beat noted it. At ae83e10
        the turns had moved to 150, 210, 270, 330: the pass at 300, quiet,
        noted nothing."""
        with mock.patch.object(tasks, "_shock_trigger") as shock:
            for s in (0, 30, 60):
                self.assertEqual(self._pass_at(s)["stored"], 1, s)
            cache.add(tasks.ETORO_SYNC_LOCK_KEY, "the pass of 60",
                      tasks.ETORO_SYNC_LOCK_S)
            for s in (90, 120):
                self.assertIn("still running", self._pass_at(s)["idle"])
            cache.delete(tasks.ETORO_SYNC_LOCK_KEY)
            for s in (150, 180, 210, 240, 270):
                self.assertEqual(self._pass_at(s)["stored"], 1, s)
            self.wire.status = 503
            with self.assertLogs("bot_program.tasks", level="WARNING"):
                self.assertEqual(self._pass_at(300)["unreachable"], 1)
            self.wire.status = 200
            self.assertEqual(self._pass_at(330)["stored"], 1)
        self.assertEqual(
            [(round((parse_datetime(f["at"]) - self.t0).total_seconds()),
              f["where"]) for f in _failures()],
            [(300, "account"), (300, "portfolio")])
        self.assertEqual(self._asked_at(shock), [0, 60, 150, 180, 240])

    def test_an_unreadable_turn_notes_and_asks_as_before_the_turns(self):
        """The cache refuses the turn's key: every pass holds the turn, as
        before the turns existed (the trigger asked from each pass), and
        nothing raises. (Green at ae83e10 too.)"""
        real_add = cache.add

        def add(key, *args, **kwargs):
            if "noting" in str(key):
                raise RuntimeError("the cache is down")
            return real_add(key, *args, **kwargs)
        with mock.patch.object(tasks, "_shock_trigger") as shock, \
                mock.patch.object(cache, "add", side_effect=add):
            for s in (0, 30):
                self.assertEqual(self._pass_at(s)["stored"], 1, s)
        self.assertEqual(self._asked_at(shock), [0, 30])

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


# ── The instant the beat sent the run: a late run keeps its window ───────

def _expires(sent, expiry):
    """The `expires` header Celery stamps on a run the beat sent at `sent`
    (epoch seconds) with the entry's expiry (amqp.as_task_v2)."""
    return datetime.fromtimestamp(sent + expiry, tz=UTC).isoformat()


class TheBeatsSendInstantTests(TestCase):
    """THE THIRD ROUND (2026-11-13): the turns are keyed on the instant the
    beat SENT each run (tasks._beat_sent_at), so a run the worker starts
    late keeps its own window: a window's second beat that runs late into
    the next window no longer takes that window's turn ahead of its first
    beat. On the installed Celery (5.6.3) and django_celery_beat (2.9.0):
    the database scheduler gives each run the entry's expiry, Celery stamps
    it as the send instant plus that expiry in the run's `expires` header,
    and the worker's tracer makes the headers the run's request."""

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
        self.user = User.objects.create_user("obt_sent", password="x")
        self.acct = _account(self.user)
        self.wire = _AccountWire()
        p = mock.patch(TRADER, side_effect=_over(self.wire))
        p.start()
        self.addCleanup(p.stop)
        self.t0 = timezone.now().replace(second=0, microsecond=0)

    def _at(self, s):
        return self.t0 + timedelta(seconds=s)

    def _pass_at(self, s):
        with mock.patch("django.utils.timezone.now",
                        return_value=self._at(s)):
            return _pass()

    def test_each_run_carries_the_instant_its_beat_sent_it(self):
        """The beats as the database scheduler stores and sends them: each
        entry's expiry (25 s, 10 s) is the run's `expires`, the send
        instant plus the expiry; less the expiry, the send instant."""
        from django_celery_beat.schedulers import DatabaseScheduler

        from config.celery import app
        from tests.test_faster_refresh import _beat
        sent = self._at(50)
        for name, task, expiry in (
                ("sync-etoro-accounts", tasks.sync_etoro_accounts, 25),
                ("refresh-etoro-quotes", tasks.refresh_etoro_quotes, 10)):
            entry = DatabaseScheduler.Entry.from_entry(name, app=app,
                                                       **_beat(name))
            self.assertEqual(entry.options.get("expires"), expiry, name)
            message = app.amqp.as_task_v2(
                "obt-sent-1", entry.task, (), {},
                expires=entry.options["expires"], now=sent)
            self.assertEqual(
                message.headers["expires"],
                (sent + timedelta(seconds=expiry)).isoformat(), name)
            task.push_request(expires=message.headers["expires"])
            try:
                self.assertEqual(
                    tasks._beat_sent_at(task, name,
                                        sent.timestamp() + expiry - 1),
                    sent.timestamp(), name)
            finally:
                task.pop_request()

    def test_a_late_run_through_the_worker_keeps_its_minute(self):
        """The pass at 20 holds its minute's turn and asks the shock
        trigger. The beat sends the next run at 50 (the minute's second);
        the worker starts it 12 s late, at 62, through Celery's own tracer
        with the run's headers. It reads, and asks nothing: it was sent in
        the minute the pass at 20 holds. The next minute's first run, at
        80, holds that minute's turn and asks. Keyed on the start, the run
        at 62 took the next minute's turn ahead of its first beat and asked
        at 62 (the pass at 80 then asking nothing)."""
        from celery.app.trace import trace_task

        from config.celery import app
        with mock.patch.object(tasks, "_shock_trigger") as shock:
            self.assertEqual(self._pass_at(20)["stored"], 1)
            message = app.amqp.as_task_v2(
                "obt-sent-2", "bot_program.tasks.sync_etoro_accounts", (),
                {}, expires=25, now=self._at(50))
            with mock.patch("django.utils.timezone.now",
                            return_value=self._at(62)):
                trace_task(tasks.sync_etoro_accounts, "obt-sent-2", (), {},
                           request=dict(message.headers), app=app)
            self.assertEqual(len(self.wire.calls), 4,
                             "the late run read the account")
            self.assertEqual(self._pass_at(80)["stored"], 1)
        self.assertEqual(
            [round((c.args[1] - self.t0).total_seconds())
             for c in shock.call_args_list], [20, 80])

    def test_a_late_second_beat_keeps_its_half_minutes_quotes_turn(self):
        """The held quotes on a wire answering 503. The beat at 10 past the
        half minute notes; the half minute's second beat, sent at 25, runs
        9 s late at 34, inside the next half minute: it notes nothing (it
        was sent in the half minute the first holds). The next half
        minute's first beat, at 40, notes. Keyed on the start, the run at
        34 took that half minute's turn and the one at 40 noted nothing."""
        from tests.test_etoro_rates_batch import _cfg, _instrument

        _instrument("AAA", "stock")
        _held(_cfg(self.user, "live", ["AAA"]), "AAA")
        quotes_wire = _quotes_wire_503()
        base = ON_THE_MINUTE
        clock = _Clock(base)
        noted = []

        def note_at():
            return [round((parse_datetime(f["at"])
                           - datetime.fromtimestamp(base, tz=UTC))
                          .total_seconds(), 1) for f in _failures()]
        with mock.patch("bot_program.etoro_quotes._client_for",
                        return_value=quotes_wire), \
                mock.patch.object(eq, "_now", clock), \
                mock.patch("django.utils.timezone.now",
                           side_effect=lambda: datetime.fromtimestamp(
                               clock.t, tz=UTC)):
            for sent, start in ((10, 10), (25, 34), (40, 40)):
                clock.t = base + start
                tasks.refresh_etoro_quotes.push_request(
                    expires=_expires(base + sent, 10))
                try:
                    out = tasks.refresh_etoro_quotes.run()
                finally:
                    tasks.refresh_etoro_quotes.pop_request()
                self.assertIn("stopped", out, start)
                noted.append(note_at())
        self.assertEqual(noted[-1], [10.0, 40.0])

    def test_no_expiry_or_one_that_does_not_fit_is_the_wall_clock(self):
        """A run with no expiry, called directly (tests, the shell), keyed
        on its start; so is one whose expiry is no instant, has no zone, or
        does not fit its start (sent after it, or more than the expiry and
        5 s before it). Never raises."""
        task, name, now = (tasks.sync_etoro_accounts, "sync-etoro-accounts",
                           ON_THE_MINUTE + 100)
        self.assertEqual(tasks._beat_sent_at(task, name, now), now)
        for expires in ("not an instant", "2026-11-13T10:00:00",
                        _expires(now + 2, 25), _expires(now - 31, 25), 12):
            task.push_request(expires=expires)
            try:
                self.assertEqual(tasks._beat_sent_at(task, name, now), now,
                                 expires)
            finally:
                task.pop_request()
        task.push_request(expires=_expires(now - 24, 25))
        try:
            self.assertEqual(tasks._beat_sent_at(task, name, now), now - 24)
            self.assertEqual(tasks._beat_sent_at(task, "no such beat", now),
                             now)
        finally:
            task.pop_request()


def _quotes_wire_503():
    """The real adapter over a rates wire answering 503 to every read."""
    from tests.test_etoro_rates_batch import _trader, _Wire
    return _trader(_Wire({11: 10.0}, status=[503]))
