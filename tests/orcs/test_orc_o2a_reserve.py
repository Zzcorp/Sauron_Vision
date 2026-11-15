"""T5, THE RESERVATION (the O2 spec N3, N4, A.18, A.20, A.21, A.24, A.25,
A.55; §1.1.7 T5; P2, P8; 2026-11-05). A claimed call holds its bound in
est_usd until its settle; every check of the line counts the OTHER
calls' money in flight and held, never a call's own twice; money is never
released before its cost is known.

- inside the fake client's first call (no lock held), a claim for a
  second wake whose bound no longer fits ends `triage`, with no second
  request; on PostgreSQL two concurrent claims where only one fits make
  one call and neither thread raises, and a claim skips an Orc whose row
  another transaction holds, never waiting for it
  (TheConcurrentClaimsTests)
- a missing ledger row holds the booked cost (ledger_gap) and the next
  claim counts it; a timeout holds the bound until 00:00 UTC and the
  next claim counts it until then
- a call past its wall time is closed `failed` and its bound held as an
  orphan, never free in between: a claim that fits only without it is
  refused; its late settle books the real cost once, and keeps or drops
  the hold by what came back (2026-11-05, completing O2a): a bill with
  its ledger row drops it; a bill with no ledger row holds the booked
  cost as `ledger_gap`; no bill keeps the bound and its HIGH until 00:00
  UTC; a call never sent drops it
- booked <= the bound; can_spend gets the bound plus the others' money,
  never its own twice, never the default estimate
- one call in flight per Orc: the second wake is claimed only after the
  first settles, with the first decision in its PS5
- the lock row's get_or_create survives a race

Run with:  python manage.py test tests.orcs.test_orc_o2a_reserve
(PostgreSQL: DB_ENGINE=postgresql and the DB_* variables of a scratch
cluster.)
"""
import json
import threading
from datetime import timedelta
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.db import IntegrityError, connection
from django.test import override_settings
from django.utils import timezone

from tests.orcs.helpers import _config, _row, _switch, _user
from tests.orcs.helpers_o2 import (MidStream, MindTransactionTestCase,
                                   PreStream, fake_answer, fake_usage,
                                   minds_on)
from tests.orcs.test_orc_o2a_admission import W4, QueueFixture
from tests.orcs.test_orc_o2a_call import NOW, answer

PG = connection.vendor == "postgresql"
NOT_PG = "two concurrent claims need PostgreSQL's row locks"


class _Reserve(QueueFixture):

    #: The hour the class's clock starts at, on the real UTC day.
    CLOCK_HOUR = 12

    def setUp(self):
        # NOON, TODAY (2026-11-13). A wall-timed call's watchdog runs at its
        # started_at + WALL_S, minutes ahead of the clock, and the late
        # settle after it runs on the clock itself. Within WALL_S of 00:00
        # UTC the watchdog books the unbilled HIGH under tomorrow, and the
        # settle, still today, sees another day and resets the day
        # counters: CI ran this class at 23:5x UTC on 2026-11-12 and
        # test_a_late_settle_with_no_bill_keeps_the_orphan_hold read 0.0
        # for 0.0594. Production's clock only moves forward; here the class
        # runs from noon of the real UTC day, its clock still moving (the
        # date and the weekday stay the real ones), set before the fixture
        # writes its rows, so no scenario crosses midnight.
        real_now = timezone.now
        start = real_now()
        base = start.replace(hour=self.CLOCK_HOUR, minute=0, second=0,
                             microsecond=0)
        clock = patch("django.utils.timezone.now",
                      side_effect=lambda: base + (real_now() - start))
        clock.start()
        self.addCleanup(clock.stop)
        super().setUp()

    def line(self, usd):
        """The Orcs line at `usd` for the rest of the test."""
        self.enterContext(override_settings(AI_CONFIG={
            **settings.AI_CONFIG, "orc_daily_budget_usd": usd}))

    def one_bound_line(self, w):
        """The Orcs line at 2.5 bounds of `w`'s dossier: a paper urgent
        ceiling (60%) of 1.5 bounds holds one call in flight, not two."""
        from bot_program.orcs import mind
        bound = mind.price(w, "r0")["bound"]
        self.line(round(2.5 * bound, 6))
        return bound

    def inside_the_call(self, fn):
        """Run `fn()` inside the fake client's next call, after the request
        is recorded and before the answer comes back (no lock held)."""
        real_send = self.fake._send
        out = {}

        def send(path, kwargs):
            reply = real_send(path, kwargs)
            out["value"] = fn()
            return reply
        self.fake._send = send
        return out

    def inflight(self, **kw):
        from bot_program.orcs import mind
        return mind.purse(**kw)["inflight"]

    def wall_timed(self, script):
        """A claimed call that the watchdog closes for its wall time while
        it is still out (inside the fake client's call, no lock held),
        then comes back with `script`: (wake, its bound, the settle, the
        watchdog's result, the money held inside the call)."""
        from bot_program.orcs import mind, scheduler
        from bot_program.orcs.constants import WALL_S
        base = self.rendered()
        self.one_bound_line(base)
        self.pending(base, timezone.now() - timedelta(minutes=1))
        w = scheduler.claim()["wake"]
        bound = float(w.est_usd)
        past = w.started_at + timedelta(seconds=WALL_S["r0"] + 1)
        inner = self.inside_the_call(
            lambda: (scheduler.watch(now=past), self.inflight()))
        self.use_fake(script)
        out = mind.think(w)
        watch, held_inside = inner["value"]
        return w, bound, out, watch, held_inside

    def late_entry(self, w):
        """The late settle's error entry of `w` (the wall time's own is
        written at the watchdog's moment, after it in time)."""
        found = [e for e in self.entries(kind="error", wake=w)
                 if (e.body or {}).get("late_settle")]
        self.assertEqual(len(found), 1)
        return found[0]


class TheReservationTests(_Reserve):

    def test_a_claim_inside_a_call_counts_its_reservation(self):
        """N3, A.18: while the first call streams, its bound is in flight;
        a claim of a second wake whose bound fits only without it ends
        `triage`, with no second request (the line at 2.5 bounds: a paper
        urgent ceiling of 1.5 bounds holds one call in flight, not two)."""
        from bot_program.orcs import mind, scheduler
        base = self.rendered()
        self.one_bound_line(base)
        other = self.orcs(1)[0]
        first = self.pending(base, timezone.now() - timedelta(minutes=1))
        second = self.pending(base, timezone.now(), orc=other)
        got = scheduler.claim()
        self.assertEqual(got["wake"].pk, first.pk)
        bound = float(got["wake"].est_usd)
        inner = self.inside_the_call(lambda: (self.inflight(),
                                              scheduler.claim()))
        self.use_fake(fake_answer(answer()))
        mind.think(got["wake"])
        held, claimed = inner["value"]
        self.assertAlmostEqual(held, bound, places=6)
        self.assertIsNone(claimed["wake"])
        self.assert_one_call()
        second.refresh_from_db()
        self.assert_no_call(code="triage", got=second.skipped_reason)
        self.assertAlmostEqual(self.inflight(), 0.0, places=6,
                               msg="released at the settle")

    def test_a_missing_ledger_row_holds_the_cost_for_the_next_claim(self):
        """A.24: released only once the provider's ledger row is found; a
        fenced ledger write leaves the line undercounting, so the booked
        cost is held (ledger_gap) and the next claim's in-flight sum holds
        it, while spent_today("orcs") is unchanged."""
        from ai_agents import spend
        from ai_agents.models import AgentTask
        from bot_program.orcs import mind_gateway
        w = self.rendered()
        self.admit(w)
        with patch.object(AgentTask.objects, "create",
                          side_effect=RuntimeError("the ledger is down")):
            got = self.serve(script=fake_answer(answer()))
        self.assert_one_call()
        self.assertEqual(spend.spent_today("orcs"), 0.0)
        cost = float(self.entries(kind="decision")[-1].cost_usd)
        self.assertGreater(cost, 0)
        self.assertEqual(got["settle"]["held"], f"w{w.pk}")
        self.assertAlmostEqual(self.inflight(), cost, places=6)
        allowed, code, _why = mind_gateway.ask_line(rung_name="r0",
                                                    bound_usd=0.10)
        asked = self.spend_calls[-1].kwargs["estimated_usd"]
        self.assertAlmostEqual(asked, 0.10 + cost, places=6)

    def test_a_timeout_holds_the_bound_until_midnight(self):
        """A.25: a call that failed with no bill keeps its bound held until
        00:00 UTC (Anthropic may bill a cut call): the next claim counts
        it until then and not after, and the line booked nothing."""
        from ai_agents import spend
        from bot_program.orcs.scheduler import next_midnight
        w = self.rendered()
        self.admit(w)
        got = self.serve(script=PreStream(TimeoutError("read timed out")))
        self.assert_one_call()
        bound = float(type(w).objects.get(pk=w.pk).components["bound"])
        self.assertEqual(spend.spent_today("orcs"), 0.0)
        self.assertEqual(got["settle"]["status"], "failed")
        self.assertAlmostEqual(self.inflight(), bound, places=6)
        midnight = next_midnight(timezone.now())
        with patch("django.utils.timezone.now",
                   return_value=midnight - timedelta(minutes=1)):
            self.assertAlmostEqual(self.inflight(), bound, places=6)
        with patch("django.utils.timezone.now",
                   return_value=midnight + timedelta(minutes=1)):
            self.assertAlmostEqual(self.inflight(), 0.0, places=6)

    def test_a_wall_timed_call_is_held_then_booked_once(self):
        """A.55 (P8): a call still streaming past WALL_S is closed failed
        (wall_time) and its bound held as an orphan: never free, so a claim
        that fits only without it is refused; when it comes back late its
        real cost is booked once on an error entry and the hold dropped."""
        from ai_agents import spend
        from bot_program.orcs import mind, scheduler
        from bot_program.orcs.constants import WALL_S
        base = self.rendered()
        self.one_bound_line(base)
        other = self.orcs(1)[0]
        self.pending(base, timezone.now() - timedelta(minutes=1))
        late = self.pending(base, timezone.now(), orc=other)
        got = scheduler.claim()
        w = got["wake"]
        bound = float(w.est_usd)
        past = w.started_at + timedelta(seconds=WALL_S["r0"] + 1)

        def watchdog_then_claim():
            out = scheduler.watch(now=past)
            return out, self.inflight(), scheduler.claim(now=past)
        inner = self.inside_the_call(watchdog_then_claim)
        usage = fake_usage(input_tokens=9000, output_tokens=900)
        self.use_fake(fake_answer(answer(), usage=usage))
        out = mind.think(w)
        watch, held, claimed = inner["value"]
        self.assertEqual(watch["minds_wall_time"], 1)
        self.assertAlmostEqual(held, bound, places=6, msg="never free")
        self.assertIsNone(claimed["wake"])
        late.refresh_from_db()
        self.assertEqual(late.skipped_reason, "triage")
        self.assertTrue(out["late"])
        w.refresh_from_db()
        self.assertEqual((w.status, w.skipped_reason),
                         ("failed", "wall_time"))
        errors = self.entries(kind="error", wake=w)
        self.assertEqual(len(errors), 2, "the wall time, then the late "
                                         "settle")
        booked = sum(float(e.cost_usd) for e in errors)
        self.assertGreater(booked, 0)
        self.assertAlmostEqual(booked, spend.spent_today("orcs"), places=6,
                               msg="booked once")
        self.orc.refresh_from_db()
        self.assertAlmostEqual(float(self.orc.spend_today_usd), booked,
                               places=6)
        self.assertAlmostEqual(self.orc.seen["unbilled_usd"], 0.0,
                               places=6)
        self.assertAlmostEqual(self.inflight(), 0.0, places=6,
                               msg="the hold dropped")

    def test_a_late_settle_with_no_bill_keeps_the_orphan_hold(self):
        """A.25, N3, N4 (2026-11-05, completing O2a): a wall-timed call
        that comes back with no bill (a timeout mid-stream) may still be
        billed for its cut stream: its whole bound stays held until 00:00
        UTC, and its HIGH stays on the Orc's unbilled dollars."""
        from ai_agents import spend
        from bot_program.orcs import scheduler
        from bot_program.orcs.scheduler import next_midnight
        w, bound, out, watch, held_inside = self.wall_timed(
            MidStream(TimeoutError("read timed out")))
        self.assertEqual(watch["minds_wall_time"], 1)
        self.assertAlmostEqual(held_inside, bound, places=6)
        self.assertTrue(out["late"])
        self.assertEqual(out["held"], f"w{w.pk}")
        self.assert_one_call()
        self.assertAlmostEqual(self.inflight(), bound, places=6,
                               msg="the orphan hold is kept")
        self.assertEqual(self.holds()[f"w{w.pk}"]["kind"], "orphan")
        self.assertEqual(spend.spent_today("orcs"), 0.0)
        self.orc.refresh_from_db()
        self.assertAlmostEqual(self.orc.seen["unbilled_usd"],
                               scheduler.high("r0"), places=6)
        self.assertEqual(float(self.orc.spend_today_usd), 0.0)
        late = self.late_entry(w)
        self.assertEqual(late.headline, "A call that ran past its wall "
                         "time came back with no bill: its bound stays held "
                         "until 00:00 UTC, nothing applied.")
        self.assertEqual(late.body["held"], "orphan")
        midnight = next_midnight(timezone.now())
        with patch("django.utils.timezone.now",
                   return_value=midnight + timedelta(minutes=1)):
            self.assertAlmostEqual(self.inflight(), 0.0, places=6,
                                   msg="it expires at 00:00 UTC")

    def test_a_late_settle_with_no_ledger_row_holds_the_booked_cost(self):
        """A.24 (2026-11-05, completing O2a): a wall-timed call that comes
        back billed while the provider's fenced ledger write failed is
        booked on the Orc, and its cost is held as `ledger_gap` until
        00:00 UTC, so the line and the core's floor still count it; its
        HIGH leaves the unbilled dollars (the cost is in the Orc's day
        dollars now) and the watchdog raises the gap."""
        from ai_agents import spend
        from ai_agents.models import AgentTask
        usage = fake_usage(input_tokens=9000, output_tokens=900)
        with patch.object(AgentTask.objects, "create",
                          side_effect=RuntimeError("the ledger is down")):
            w, bound, out, watch, held_inside = self.wall_timed(
                fake_answer(answer(), usage=usage))
        self.assertEqual(watch["minds_wall_time"], 1)
        self.assertTrue(out["late"])
        self.assertEqual(out["held"], f"w{w.pk}")
        self.assert_one_call()
        self.assertEqual(spend.spent_today("orcs"), 0.0)
        late = self.late_entry(w)
        cost = float(late.cost_usd)
        self.assertGreater(cost, 0)
        self.assertAlmostEqual(self.inflight(), cost, places=6,
                               msg="the line still counts the cost")
        entry = self.holds()[f"w{w.pk}"]
        self.assertEqual(entry["kind"], "ledger_gap")
        self.assertAlmostEqual(entry["usd"], cost, places=6)
        self.orc.refresh_from_db()
        self.assertAlmostEqual(float(self.orc.spend_today_usd), cost,
                               places=6)
        self.assertAlmostEqual(self.orc.seen["unbilled_usd"], 0.0,
                               places=6)
        self.assertEqual(late.headline, "A call that ran past its wall "
                         "time came back: its cost is booked and held until "
                         "00:00 UTC (the provider wrote no ledger row), "
                         "nothing applied.")
        self.assertEqual(self.watch(timezone.now())["minds_ledger_gap"], 1)

    def test_a_late_settle_with_no_bill_after_midnight_holds_no_more(self):
        """A.25: the orphan hold ends at 00:00 UTC, never earlier; a call
        with no bill that comes back after it holds nothing more, and its
        words say the hold had ended."""
        from bot_program.orcs import mind, scheduler
        from bot_program.orcs.constants import WALL_S
        from bot_program.orcs.scheduler import next_midnight
        base = self.rendered()
        self.one_bound_line(base)
        self.pending(base, timezone.now() - timedelta(minutes=1))
        w = scheduler.claim()["wake"]
        past = w.started_at + timedelta(seconds=WALL_S["r0"] + 1)
        after = next_midnight(past) + timedelta(minutes=1)
        inner = self.inside_the_call(lambda: scheduler.watch(now=past))
        self.use_fake(MidStream(TimeoutError("read timed out")))
        out = mind.think(w, now=after)
        self.assertEqual(inner["value"]["minds_wall_time"], 1)
        self.assert_one_call()
        self.assertEqual((out["late"], out["held"]), (True, ""))
        self.assertNotIn(f"w{w.pk}", scheduler._pruned(self.holds(), after),
                         "no hold of its own runs past 00:00 UTC")
        self.assertEqual(self.late_entry(w).headline,
                         "A call that ran past its wall time came back with "
                         "no bill after its hold ended at 00:00 UTC, nothing "
                         "applied.")

    def test_a_wall_timed_call_never_sent_frees_its_hold(self):
        """A.25 (2026-11-05, completing O2a): a wall-timed wake whose call
        the gateway never sent (a gate closed before the send) can never
        be billed: its late settle drops the orphan hold and the HIGH.
        Its pair: a wall-timed call that was sent, billed and ledgered
        drops its hold too, after one request."""
        from bot_program.orcs import mind, scheduler
        from bot_program.orcs.constants import WALL_S
        w, bound, out, watch, held_inside = self.wall_timed(
            fake_answer(answer()))
        self.assertTrue(out["late"])
        self.assert_one_call()
        self.assertAlmostEqual(self.inflight(), 0.0, places=6)
        base = self.rendered()
        self.pending(base, timezone.now() - timedelta(minutes=1))
        second = scheduler.claim()["wake"]
        self.assertIsNotNone(second)
        past = second.started_at + timedelta(seconds=WALL_S["r0"] + 1)
        self.assertEqual(scheduler.watch(now=past)["minds_wall_time"], 1)
        self.assertGreater(self.inflight(), 0.0, "held while it is out")
        _switch("orcs_minds", False)
        out = mind.think(second)
        self.assertEqual((out["late"], out["held"]), (True, ""))
        late = self.late_entry(second)
        self.assert_no_call(code="minds_off", got=late.body["code"])
        self.assertAlmostEqual(self.inflight(), 0.0, places=6,
                               msg="nothing was sent: nothing is held")
        self.assertNotIn(f"w{second.pk}", self.holds())
        self.orc.refresh_from_db()
        self.assertAlmostEqual(self.orc.seen["unbilled_usd"], 0.0,
                               places=6)
        self.assertEqual(late.headline, "A call that ran past its wall "
                         "time was never sent: its bound is released, "
                         "nothing applied.")

    def test_booked_never_passes_the_claims_bound(self):
        """N4 through the claim: the worst usage (every prompt token
        written at 1h on 1.35 x the estimate, max_tokens out) books at
        most the est_usd the claim reserved."""
        w = self.rendered()
        self.admit(w)
        w.refresh_from_db()
        est = int(w.components["tokens"])
        worst = fake_usage(input_tokens=0, output_tokens=8000,
                           cache_write_1h=-(-est * 135 // 100))
        got = self.serve(script=fake_answer(answer(), usage=worst))
        self.assert_one_call()
        booked = float(self.entries(kind="decision")[-1].cost_usd)
        self.assertGreater(booked, 0.1)
        self.assertLessEqual(booked, float(got["wake"].est_usd) + 1e-6)

    def test_can_spend_gets_the_bound_and_the_others_money_once(self):
        """A.20: the claim and the gateway each ask the Orcs line for this
        bound plus the OTHER calls' money in flight and held: never the
        call's own twice, never the default 0.05, never total_only."""
        from bot_program.orcs import mind, scheduler
        base = self.rendered()
        a_orc, b_orc = self.orcs(2)
        self.pending(base, timezone.now() - timedelta(minutes=2), orc=a_orc)
        self.pending(base, timezone.now(), orc=b_orc)
        running = scheduler.claim()["wake"]
        held = 0.40
        self.hold_usd(held)
        del self.spend_calls[:]
        w = scheduler.claim()["wake"]
        bound = float(w.est_usd)
        self.use_fake(fake_answer(answer()))
        mind.think(w)
        self.assert_one_call()
        asks = [c.kwargs for c in self.spend_calls
                if c.kwargs.get("line") == "orcs"]
        self.assertEqual(len(asks), 2, "the claim's and the gateway's")
        others = float(running.est_usd) + held
        for kw in asks:
            self.assertAlmostEqual(kw["estimated_usd"], bound + others,
                                   places=6)
            self.assertNotIn("total_only", kw)
            self.assertNotAlmostEqual(kw["estimated_usd"], 0.05, places=3)
            self.assertEqual(kw["tier"], "balanced")

    def test_one_call_in_flight_per_orc_and_the_second_reads_the_first(
            self):
        """A.18, A.24: two urgent wakes of one Orc and two workers: the
        second worker's claim leaves the second wake pending while the
        first call runs; the first settle sends it back to the render; it
        is rendered again as of its own moment, reading the journal up to
        the settle, admitted, claimed, and its PS5 holds the first
        decision."""
        from bot_program.orcs import mind, scheduler, wake
        from bot_program.orcs.models import OrcDossierBlock
        first = self.rendered([W4])
        self.admit(first)
        got = scheduler.claim()
        self.assertEqual(got["wake"].pk, first.pk)
        second = self.rendered([{**W4, "key": "W4:b"}],
                               at=NOW + timedelta(minutes=3))
        self.assertEqual(self.admit(second)["status"], "pending")
        inner = self.inside_the_call(scheduler.claim)
        self.use_fake(fake_answer(answer(
            note="Holding: the first decision.")))
        out = mind.think(got["wake"])
        self.assert_one_call()
        self.assertIsNone(inner["value"]["wake"], "one call per Orc")
        self.assertEqual(inner["value"]["waiting"], 1)
        self.assertEqual(out["sent_back"], 1)
        second.refresh_from_db()
        self.assertEqual((second.status, second.components["render"]),
                         ("recorded", "queued"))
        with patch("django.utils.timezone.now",
                   return_value=NOW + timedelta(minutes=3)):
            self.assertEqual(wake.render_queued(), (1, 0))
        second.refresh_from_db()
        self.assertEqual(self.admit(second)["status"], "pending")
        got = scheduler.claim()
        self.assertEqual(got["wake"].pk, second.pk)
        ps = OrcDossierBlock.objects.get(hash=second.block_hashes[
            int(second.components["shared"])])
        notes = " ".join(json.loads(ps.text.partition("\n")[2])["ps5"][
            "notes"])
        self.assertIn("Holding: the first decision.", notes)
        mind.think(got["wake"])
        self.assert_one_call()

    def test_the_lock_rows_get_or_create_survives_a_race(self):
        from bot_program.orcs import scheduler
        from bot_program.orcs.models import OrcSetting
        self.admit(self.rendered())
        real = OrcSetting.objects.get_or_create
        calls = []

        def racing(*args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                OrcSetting.objects.create(key="minds_lock", value={})
                raise IntegrityError("a twin made it in the same instant")
            return real(*args, **kwargs)
        with patch.object(OrcSetting.objects, "get_or_create", racing):
            got = scheduler.claim()
        self.assertIsNotNone(got["wake"])
        self.assertEqual(OrcSetting.objects.filter(key="minds_lock").count(),
                         1)


# ── PostgreSQL: two workers at once ──────────────────────────────────────

@skipUnless(PG, NOT_PG)
class TheConcurrentClaimsTests(MindTransactionTestCase):
    """Two threads claim at once where only one bound fits (two real-money
    urgent wakes, the line at $0.30): the line lock makes them take turns,
    so exactly one call is made, the other wake is answered `triage`, and
    neither thread raises (N3). And a claim never waits for an Orc's row
    another transaction holds (A.18, N8)."""

    def _orc(self, user, cfg, seat, n):
        from bot_program.orcs.models import Orc, OrcWake
        row = _row(cfg, paper=False, symbol="BTCUSD")
        orc = Orc.objects.create(seat=seat, user=user, config=cfg,
                                 root_trade=row, symbol="BTCUSD", side="BUY",
                                 asset_class="crypto", paper=False)
        return OrcWake.objects.create(
            orc=orc, reasons=[W4], dedupe_key=f"pg{n}", status="skipped",
            day_class="calm", block_hashes=list(self.hashes),
            components={"render": "done", "tokens": 20000, "shared": 1,
                        "s": {"hash": self.s_hash, "version": "s1"},
                        "as_of": timezone.now().isoformat(),
                        "vctx": {"allowed": ["hold"], "menu": [],
                                 "candidates": [], "events": {}}})

    def setUp(self):
        from bot_program.orcs import doctrine
        from bot_program.orcs.models import OrcDossierBlock, OrcSeat
        _switch("aragorn")
        minds_on(self, line_usd=0.30)
        user = _user("o2a_pg_claims")
        cfg = _config(user)
        seat = OrcSeat.objects.create(venue="live", asset_class="crypto")
        blocks = {"s": doctrine.S, "mk0": "the market's day",
                  "ps": "the position", "tail": "the tail"}
        made = {}
        for kind, text in blocks.items():
            made[kind] = OrcDossierBlock.objects.create(
                hash=f"pg-{kind}", kind=kind, text=text).hash
        self.s_hash = made["s"]
        self.hashes = [made["mk0"], made["ps"], made["tail"]]
        self.wakes = [self._orc(user, cfg, seat, n) for n in (1, 2)]

    def test_two_concurrent_claims_where_one_fits_make_one_call(self):
        """The call in flight is held inside the fake client (no lock
        held) until neither wake is pending (2026-11-06, O2b's routed
        rung): the other claim has then answered its wake by code, or,
        were the line lock broken, claimed it and sent a second request.
        An answer that came back at once let the first call's settle take
        the line lock before the second claim did; the second bound then
        fitted beside the first call's booked cost, inside the line, and
        two calls were made one after the other (on PostgreSQL about one
        run in six on O2a's tip)."""
        import time as clock

        from django.db import connection as conn

        from bot_program.orcs import scheduler
        from bot_program.orcs.models import OrcWake
        for w in self.wakes:
            self.assertEqual(scheduler.admit(w)["status"], "pending")
        self.use_fake(fake_answer(answer()))
        ids, real_send = [w.pk for w in self.wakes], self.fake._send

        def held_send(path, kwargs):
            deadline = clock.monotonic() + 20
            while clock.monotonic() < deadline and OrcWake.objects.filter(
                    pk__in=ids, status="pending").exists():
                clock.sleep(0.02)
            return real_send(path, kwargs)
        self.fake._send = held_send
        errors, results, go = [], [], threading.Barrier(2)

        def worker():
            try:
                go.wait(10)
                results.append(scheduler.run())
            except Exception as e:  # noqa: BLE001 — told to the test
                errors.append(e)
            finally:
                conn.close()
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual(errors, [])
        self.assert_one_call()
        self.assertEqual(sorted(r["thought"] for r in results), [0, 1])
        ends = sorted(OrcWake.objects.filter(
            pk__in=[w.pk for w in self.wakes]).values_list(
            "status", "skipped_reason"))
        self.assertEqual(ends, [("done", ""), ("skipped", "triage")])

    def test_a_claim_skips_an_orc_row_another_transaction_holds(self):
        """A.18, N8: the claim takes the Orc's row with skip_locked. While
        another transaction holds it (the tick's lock, journal.orc_lock),
        the claim neither waits for it nor answers its wake by code: the
        wake stays pending and no request is sent; once the row is free
        the next claim takes it. The line at $2.00, so no money refuses."""
        import time as clock

        from django.db import connection as conn
        from django.db import transaction

        from bot_program.orcs import journal, mind, scheduler
        from bot_program.orcs.models import OrcWake
        minds_on(self, line_usd=2.0)
        free, busy = self.wakes
        for w in (free, busy):
            self.assertEqual(scheduler.admit(w)["status"], "pending")
        self.use_fake(fake_answer(answer()))
        held, release, errors = threading.Event(), threading.Event(), []

        def tick():
            try:
                with transaction.atomic():
                    journal.orc_lock(busy.orc_id)
                    held.set()
                    release.wait(30)
            except Exception as e:  # noqa: BLE001 — told to the test
                errors.append(e)
            finally:
                conn.close()
        holder = threading.Thread(target=tick)
        holder.start()
        try:
            self.assertTrue(held.wait(10), "the tick holds the Orc's row")
            # the positive control: the free Orc's wake is read
            out = scheduler.run()
            self.assertEqual((out["thought"], out["waiting"]), (1, 1))
            self.assert_one_call()
            started = clock.monotonic()
            got = scheduler.claim()
            took = clock.monotonic() - started
            self.assertIsNone(got["wake"])
            self.assertEqual((got["by_code"], got["waiting"]), (0, 1))
            self.assertLess(took, 1.0, "skip_locked never waits for the row")
            self.assert_no_call()
            busy.refresh_from_db()
            self.assertEqual((busy.status, busy.skipped_reason),
                             ("pending", ""))
        finally:
            release.set()
            holder.join(30)
        self.assertEqual(errors, [])
        got = scheduler.claim()
        self.assertEqual(got["wake"].pk, busy.pk)
        mind.think(got["wake"])
        self.assert_one_call()
        self.assertEqual(sorted(OrcWake.objects.filter(
            pk__in=[w.pk for w in self.wakes]).values_list(
            "status", flat=True)), ["done", "done"])
