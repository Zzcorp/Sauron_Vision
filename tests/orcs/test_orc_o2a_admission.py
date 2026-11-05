"""T3, ADMISSION AND THE MERGE (the O2 spec A.7 step 1, A.11-A.16 and the
claim's re-checks of A.18; §1.1.7 T3, with T4's merge; P1, P5, P6, P7,
P9, P12, P15; 2026-11-05). The render does not admit yet: these tests
drive scheduler.absorb and scheduler.admit as the render pass will call
them, then scheduler.claim and mind.think on the fake model (N7).

- every code of A.11 is a pair inside one test (ZERO_CALL_CODES): one
  request with every gate ON, then only the one condition flipped, the
  wake answered by code and no request, with its code
- the pending wake: one per Orc at the database ("orc<pk>:pending"), the
  tick's key kept, its first send set once (a send-back keeps it), its
  rank, the rung r0 and A.21's bound
- the day caps per Orc (A.12): 12 urgent wakes then a routine one gives
  `day_cap` (P5); a real-money urgent wake passes the count cap, never
  the dollars; the dollars counted with HIGH (a paper Orc at $0.45 is
  refused an r1 call, at $0.20 an r3 call passes); the routine sub-caps
- the triage (A.13) at R = min($1.00, 0.2 x C): paper urgent wakes cannot
  push the line past 60%, a real urgent wake still runs at 95% (P6); the
  ceilings never invert at caps $1-$50; `inflight` when the money in
  flight and held would pass the core's $3.00 floor
- the rank (A.14): in one pass a real routine wake is claimed before a
  paper urgent one; a demo row and a row that states no world are
  budgeted as paper (P7)
- the merge (P15): a newer routine wake absorbs an older urgent one, and
  the survivor is urgent, skips the spacing and keeps the older first
  send; a plan's watch never makes it urgent

Run with:  python manage.py test tests.orcs.test_orc_o2a_admission
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.conf import settings
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone

from tests.orcs.helpers import _row, born
from tests.orcs.helpers_o2 import MindTestCase, fake_answer
from tests.orcs.test_orc_o2a_call import MindFixture, answer

#: Each code of A.11 and the test that proves it with its pair (T16 reads
#: this table from the source).
ZERO_CALL_CODES = {
    "quiet": "TheCodesTests.test_quiet",
    "minds_off": "TheCodesTests.test_minds_off",
    "line_off": "TheCodesTests.test_line_off",
    "dead": "TheCodesTests.test_dead",
    "row_closed": "TheCodesTests.test_row_closed",
    "over_budget": "TheCodesTests.test_over_budget",
    "breaker": "TheCodesTests.test_breaker",
    "day_cap": "TheCodesTests.test_day_cap",
    "routine_cap": "TheCodesTests.test_routine_cap",
    "dollar_cap": "TheCodesTests.test_dollar_cap",
    "triage": "TheCodesTests.test_triage",
    "inflight": "TheCodesTests.test_inflight",
    "spacing": "TheCodesTests.test_spacing",
    "merged": "TheCodesTests.test_merged",
}

#: A routine reason (a final decision bar), an urgent material one, a
#: plan's own watch (never urgent, A.48).
W2 = {"code": "W2", "key": "W2:4h:x", "t": "4h bar closed", "urgent": False}
W4 = {"code": "W4", "key": "W4:-0.5", "t": "-0.5R reached", "urgent": True}
PLAN = {"code": "W3", "key": "W3:plan:S4h-L1:x", "t": "the plan's watch",
        "urgent": False, "source": "plan", "level": "plan:swing:4h:99"}


class QueueFixture(MindFixture):
    """MindFixture's Orc, its dossiers and the four gates ON; the queue
    driven by hand: `twin` makes another rendered wake on a stored
    dossier, as the render leaves one; `serve` claims the best pending
    wake and reads it."""

    def twin(self, w, *, reasons=None, orc=None, **comps):
        """A rendered wake on `w`'s stored dossier, with its own reasons and
        tick key, its status as O1's render leaves it."""
        from bot_program.orcs.models import OrcWake
        orc = orc or self.orc
        n = OrcWake.objects.count()
        return OrcWake.objects.create(
            orc_id=orc.pk, reasons=list(reasons or w.reasons),
            dedupe_key=f"orc{orc.pk}:twin{n}:{w.pk}", kind=w.kind,
            status="skipped", skipped_reason="no model before O2",
            components={**dict(w.components or {}), **comps},
            block_hashes=list(w.block_hashes or []), score=w.score,
            band=w.band, day_class=w.day_class)

    def admit(self, w, **kw):
        from bot_program.orcs import scheduler
        return scheduler.admit(w, **kw)

    def serve(self, *, now=None, script=None):
        """One claim, and the claimed wake read on the fake model."""
        from bot_program.orcs import mind, scheduler
        if script is not None:
            self.use_fake(script)
        got = scheduler.claim(now=now)
        if got["wake"] is not None:
            got["settle"] = mind.think(got["wake"], now=now)
        return got

    def control(self, reasons=None):
        """The positive control's run: a wake rendered, admitted, claimed
        and read. The test asserts its one request itself (T16 reads the
        pair in the test's own source)."""
        w = self.rendered(reasons)
        self.assertEqual(self.admit(w)["status"], "pending")
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        return w

    def book(self, usd):
        """Money booked today on the Orcs line (the provider's ledger)."""
        from ai_agents.models import AgentTask
        AgentTask.objects.create(agent="orc", provider="claude", model="m",
                                 prompt_summary="booked by the test",
                                 cost_usd=Decimal(str(usd)))

    def counters(self, orc=None, *, unbilled=None, **values):
        """The Orc's day counters, today's (and its unbilled HIGH)."""
        from bot_program.orcs.models import Orc
        from bot_program.orcs.scheduler import utc_day
        orc = orc or self.orc
        orc.refresh_from_db()
        seen = {**(orc.seen or {}), "counters_day": utc_day(timezone.now())}
        if unbilled is not None:
            seen["unbilled_usd"] = unbilled
        Orc.objects.filter(pk=orc.pk).update(seen=seen, **values)
        orc.refresh_from_db()

    def live(self):
        """A real-money Orc on its own live row, its dossier rendered."""
        from bot_program.orcs.models import Orc
        row = _row(self.cfg, paper=False, symbol=self.symbol)
        orc = born(self, row, at=self.orc.born_at)
        Orc.objects.filter(pk=orc.pk).update(r_money=self.orc.r_money)
        orc.refresh_from_db()
        self.assertEqual(orc.seat.venue, "live")
        return orc

    def hold_usd(self, usd):
        from bot_program.orcs.models import OrcSetting
        from bot_program.orcs.scheduler import next_midnight
        now = timezone.now()
        OrcSetting.objects.update_or_create(key="minds_inflight", defaults={
            "value": {"w0": {"kind": "unbilled", "usd": usd, "high": 0.0,
                             "orc": 0, "wake": 0, "rung": "r0",
                             "at": now.isoformat(),
                             "until": next_midnight(now).isoformat()}}})

    def watch(self, at, *, last=None):
        """One watchdog pass at `at`; `last`: its previous pass (5 min
        before by default: not paused)."""
        from bot_program.orcs import scheduler
        from bot_program.orcs.models import OrcSetting
        last = at - timedelta(minutes=5) if last is None else last
        OrcSetting.objects.update_or_create(
            key="minds_watch_last_at", defaults={"value": {
                "at": last.isoformat()}})
        return scheduler.watch(now=at)

    def pending(self, w, at, *, orc=None, reasons=None):
        """A twin of `w` admitted at `at`."""
        t = self.twin(w, orc=orc, reasons=reasons)
        self.assertEqual(self.admit(t, now=at)["status"], "pending")
        t.refresh_from_db()
        return t

    def orcs(self, n):
        """`n` more paper Orcs on their own rows (the paper cap raised)."""
        from bot_program.orcs.models import OrcSetting
        OrcSetting.objects.update_or_create(key="max_paper_orcs",
                                            defaults={"value": 100})
        return [born(self, _row(self.cfg, symbol=self.symbol),
                     at=self.orc.born_at) for _ in range(n)]

    def took(self, orc):
        from bot_program.orcs.models import OrcJournal
        return list(OrcJournal.objects.filter(orc=orc, kind="takeover"))


# ── every code of A.11, each a pair ─────────────────────────────────────

class TheCodesTests(QueueFixture):
    """A.11: the first check that fails decides, with a code and no call
    (P1). Each test: the positive control, then the one condition."""

    def _closed(self, w, code):
        """The wake answered by code, and still nothing to claim."""
        w.refresh_from_db()
        self.assertEqual((w.status, w.skipped_reason), ("skipped", code))
        self.assertIsNone(self.serve()["wake"], "nothing left to claim")
        self.assert_no_call()

    def test_quiet(self):
        """A quiet wake (F6, the render's) stays quiet: no call."""
        w = self.control()
        self.assert_one_call()
        q = self.twin(w)
        type(q).objects.filter(pk=q.pk).update(status="quiet",
                                                skipped_reason="")
        out = self.admit(q)
        self.assert_no_call(code="quiet", got=out["code"])
        q.refresh_from_db()
        self.assertEqual(q.status, "quiet")

    def test_minds_off(self):
        from tests.orcs.helpers import _switch
        w = self.control()
        self.assert_one_call()
        _switch("orcs_minds", False)
        off = self.twin(w)
        out = self.admit(off)
        self.assert_no_call(code="minds_off", got=out["code"])
        self._closed(off, "minds_off")
        self.assertEqual(self.entries(kind="budget", wake=off), [],
                         "no budget entry while the switch is off (A.5)")

    def test_line_off(self):
        w = self.control()
        self.assert_one_call()
        off = self.twin(w)
        with override_settings(AI_CONFIG={**settings.AI_CONFIG,
                                          "orc_daily_budget_usd": 0.0}):
            out = self.admit(off)
            self.assert_no_call(code="line_off", got=out["code"])
            self._closed(off, "line_off")
        budget = self.entries(kind="budget", wake=off)
        self.assertEqual([e.headline for e in budget], [
            "Answered by code: the Orcs budget line is off "
            "(ORC_DAILY_BUDGET_USD=0)."])
        self.assertFalse(budget[0].fact_id)

    def test_dead(self):
        from bot_program.orcs.models import Orc
        w = self.control()
        self.assert_one_call()
        Orc.objects.filter(pk=self.orc.pk).update(state="dead")
        off = self.twin(w)
        out = self.admit(off)
        self.assert_no_call(code="dead", got=out["code"])
        self._closed(off, "dead")

    def test_row_closed(self):
        from bot_program.models import AssetBotTrade
        w = self.control()
        self.assert_one_call()
        AssetBotTrade.objects.filter(pk=self.row.pk).update(status="CLOSED")
        off = self.twin(w)
        out = self.admit(off)
        self.assert_no_call(code="row_closed", got=out["code"])
        self._closed(off, "row_closed")

    def test_over_budget(self):
        w = self.control()
        self.assert_one_call()
        off = self.twin(w)
        out = self.admit(off, rendered={"over_budget": True})
        self.assert_no_call(code="over_budget", got=out["code"])
        self._closed(off, "over_budget")
        self.assertTrue(off.components["over_budget"],
                        "kept for the claim's re-check")

    def test_breaker(self):
        from bot_program.orcs.models import OrcSetting
        w = self.control()
        self.assert_one_call()
        OrcSetting.objects.create(key="minds_breaker", value={
            "until": (timezone.now() + timedelta(minutes=15)).isoformat(),
            "why": "5 model calls failed within 10 minutes"})
        off = self.twin(w)
        out = self.admit(off)
        self.assert_no_call(code="breaker", got=out["code"])
        self._closed(off, "breaker")

    def test_day_cap(self):
        """The count cap binds the whole day: once used (here by one
        urgent claim, its cap set to 1), a routine wake is answered by
        code (P5)."""
        from bot_program.orcs.models import OrcSetting
        w = self.control()
        self.assert_one_call()
        OrcSetting.objects.create(key="wakes_per_day", value={"paper": 1})
        off = self.twin(w, reasons=[W2])
        out = self.admit(off)
        self.assert_no_call(code="day_cap", got=out["code"])
        self._closed(off, "day_cap")

    def test_routine_cap(self):
        """A paper Orc's routine wakes may use 75% of its 6: four."""
        w = self.control()
        self.assert_one_call()
        self.counters(routine_wakes_today=4)
        off = self.twin(w, reasons=[W2])
        self.orc.refresh_from_db()
        out = self.admit(off)
        self.assert_no_call(code="routine_cap", got=out["code"])
        self._closed(off, "routine_cap")

    def test_dollar_cap(self):
        """$0.45 spent, and HIGH(r0) would pass a paper Orc's $0.50."""
        w = self.control()
        self.assert_one_call()
        self.counters(spend_today_usd=Decimal("0.45"))
        off = self.twin(w)
        out = self.admit(off)
        self.assert_no_call(code="dollar_cap", got=out["code"])
        self._closed(off, "dollar_cap")

    def test_triage(self):
        """A paper urgent wake stops at 60% of the line: $3.50 booked of
        $6, plus its bound, passes $3.60. The dollars stay in the body."""
        w = self.control()
        self.assert_one_call()
        self.book(3.50)
        off = self.twin(w, reasons=[W4])
        out = self.admit(off)
        self.assert_no_call(code="triage", got=out["code"])
        self._closed(off, "triage")
        entry = self.entries(kind="budget", wake=off)[0]
        self.assertEqual(entry.headline, "Answered by code: its class's "
                         "share of the Orcs line is used.")
        self.assertNotIn("$", entry.headline)
        self.assertEqual(entry.body["line"]["cap"], 6.0)

    def test_inflight(self):
        """$2.90 held for calls without a bill, plus this bound, would pass
        the core's $3.00 floor (A.18), while the triage still has room."""
        w = self.control()
        self.assert_one_call()
        self.hold_usd(2.95)
        off = self.twin(w, reasons=[W4])
        out = self.admit(off)
        self.assert_no_call(code="inflight", got=out["code"])
        self._closed(off, "inflight")

    def test_spacing(self):
        """A non-urgent wake 5 minutes after the last claimed model wake."""
        w = self.control()
        self.assert_one_call()
        off = self.twin(w, reasons=[W2])
        out = self.admit(off, now=timezone.now() + timedelta(minutes=5))
        self.assert_no_call(code="spacing", got=out["code"])
        self._closed(off, "spacing")

    def test_merged(self):
        """A wake merged into a newer one is never called: its reasons
        ride on the survivor (P1, P15)."""
        from bot_program.orcs import scheduler
        w = self.control()
        self.assert_one_call()
        older = self.twin(w, reasons=[W4])
        self.assertEqual(self.admit(older)["status"], "pending")
        newer = self.twin(w, reasons=[W2])
        self.assertEqual(scheduler.absorb(newer), 1)
        older.refresh_from_db()
        self.assertIsNone(self.serve()["wake"])
        self.assert_no_call(code="merged", got=older.status)
        self.assertEqual(older.components["merged_into"], newer.pk)


# ── the pending wake ─────────────────────────────────────────────────────

class ThePendingWakeTests(QueueFixture):

    def test_pending_is_one_per_orc_its_first_send_set_once(self):
        """A.11 step 9 (P9): the key "orc<pk>:pending" (the database holds
        one pending wake per Orc), the tick's key kept, queued_at set
        once and kept across a send-back and a second admission, the
        priority its rank, the rung r0 and A.21's bound."""
        from bot_program.orcs import mind, scheduler
        from bot_program.orcs.models import OrcWake
        w = self.rendered()
        tick_key = w.dedupe_key
        at = timezone.now()
        out = self.admit(w, now=at)
        w.refresh_from_db()
        self.assertEqual((out["status"], out["code"]), ("pending", ""))
        self.assertEqual(w.dedupe_key, f"orc{self.orc.pk}:pending")
        self.assertEqual(w.components["record_key"], tick_key)
        self.assertEqual(w.queued_at, at)
        self.assertEqual(w.priority, 1.0, "paper urgent")
        self.assertEqual(w.components["rung"], "r0")
        self.assertAlmostEqual(w.components["bound"],
                               mind.price(w, "r0")["bound"], places=6)
        self.assertEqual(w.est_usd, Decimal(0), "nothing reserved yet")
        # the database refuses a second pending wake of the same Orc
        other = self.twin(w)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.admit(other)
        # sent back to the render (the settle of another call), admitted
        # again later: its first send never moves
        OrcWake.objects.filter(pk=w.pk).update(status="skipped")
        self.assertEqual(self.admit(w, now=at + timedelta(minutes=9))[
            "status"], "pending")
        w.refresh_from_db()
        self.assertEqual(w.queued_at, at)
        self.assertEqual(w.components["record_key"], tick_key)
        self.assertEqual(scheduler.claim()["wake"].pk, w.pk)


# ── the day caps (A.12) ──────────────────────────────────────────────────

class TheDayCapsTests(QueueFixture):

    def _wake(self, orc, reasons, day_class="calm"):
        from bot_program.orcs.models import OrcWake
        n = OrcWake.objects.count()
        return OrcWake.objects.create(
            orc_id=orc.pk, reasons=list(reasons), dedupe_key=f"cap{n}",
            status="skipped", day_class=day_class,
            components={"render": "done", "tokens": 20000})

    def test_twelve_urgent_wakes_then_a_routine_one_gives_day_cap(self):
        """P5: the whole day's count binds a routine wake even when urgent
        wakes used it; a real-money urgent wake may pass the count cap,
        never the dollars; a paper urgent wake stops at both."""
        live = self.live()
        self.counters(live, llm_wakes_today=12, routine_wakes_today=0)
        routine = self.admit(self._wake(live, [W2]))
        self.assertEqual(routine["code"], "day_cap")
        urgent = self._wake(live, [W4])
        self.assertEqual(self.admit(urgent)["status"], "pending",
                         "a real urgent wake passes the count cap")
        self.counters(live, spend_today_usd=Decimal("1.95"))
        from bot_program.orcs.models import OrcWake
        OrcWake.objects.filter(pk=urgent.pk).update(status="skipped",
                                                    dedupe_key="u")
        self.assertEqual(self.admit(urgent)["code"], "dollar_cap",
                         "never the dollars")
        self.counters(self.orc, llm_wakes_today=6)
        self.assertEqual(self.admit(self._wake(self.orc, [W4]))["code"],
                         "day_cap", "a paper urgent wake stops at its 6")
        # the cap follows the day's class, per Orc, for real money
        self.counters(live, llm_wakes_today=12, spend_today_usd=0)
        self.assertEqual(self.admit(self._wake(live, [W2], "stormy"))[
            "status"], "pending", "a stormy day's 16")

    def test_the_dollar_cap_counts_high(self):
        """A.12: spend + unbilled + HIGH in flight + HIGH(this rung) within
        the Orc's dollars: a paper Orc at $0.45 is refused an r1 call, at
        $0.20 an r3 call passes; its unbilled and in-flight HIGH count."""
        from bot_program.orcs.scheduler import cap_code
        now = timezone.now()
        kw = dict(real=False, urgent=False, routine=False, day_class="calm",
                  now=now)
        self.counters(spend_today_usd=Decimal("0.45"))
        self.assertEqual(cap_code(self.orc, rung="r1", **kw), "dollar_cap")
        self.counters(spend_today_usd=Decimal("0.20"))
        self.assertEqual(cap_code(self.orc, rung="r3", **kw), "")
        self.assertEqual(cap_code(self.orc, rung="r3", inflight_high=0.0594,
                                  **kw), "dollar_cap")
        self.counters(spend_today_usd=Decimal("0.20"), unbilled=0.0594)
        self.assertEqual(cap_code(self.orc, rung="r3", **kw), "dollar_cap")
        # an earlier day's counters are reset before use
        from bot_program.orcs.models import Orc
        Orc.objects.filter(pk=self.orc.pk).update(seen={
            **self.orc.seen, "counters_day": "2026-01-01"})
        self.orc.refresh_from_db()
        self.assertEqual(cap_code(self.orc, rung="r3", **kw), "")

    def test_the_routine_sub_caps(self):
        """A.12: routine wakes may use 75% of each cap, as well as the
        whole day: a real Orc's 9 of 12 wakes and $1.50 of $2.00."""
        from bot_program.orcs.scheduler import cap_code
        live = self.live()
        now = timezone.now()
        kw = dict(real=True, urgent=False, rung="r0", day_class="calm",
                  now=now)
        self.counters(live, llm_wakes_today=9, routine_wakes_today=9)
        self.assertEqual(cap_code(live, routine=True, **kw), "routine_cap")
        self.assertEqual(cap_code(live, routine=False, **kw), "",
                         "a material wake is not routine")
        self.counters(live, llm_wakes_today=2, routine_wakes_today=2,
                      routine_spend_today_usd=Decimal("1.45"),
                      spend_today_usd=Decimal("1.45"))
        self.assertEqual(cap_code(live, routine=True, **kw), "routine_cap")
        self.assertEqual(cap_code(live, routine=False, **kw), "")


# ── the triage (A.13) and the rank (A.14) ────────────────────────────────

class TheTriageTests(QueueFixture):

    def test_the_ceilings_never_invert_from_one_to_fifty_dollars(self):
        from bot_program.orcs.scheduler import ceilings
        for cap in range(1, 51):
            c = ceilings(float(cap))
            with self.subTest(cap=cap):
                self.assertAlmostEqual(c["reserve"],
                                       min(1.0, 0.2 * cap), places=9)
                self.assertGreaterEqual(c["real_urgent"], c["real"])
                self.assertGreaterEqual(c["real"], c["paper_urgent"])
                self.assertGreaterEqual(c["paper_urgent"], c["paper"])
                self.assertGreaterEqual(c["paper"], c["tickets"])
                self.assertGreaterEqual(c["real"], 0.8 * cap - 1e-9)
        six = ceilings(6.0)
        self.assertEqual([round(six[k], 2) for k in (
            "real_urgent", "real", "paper_urgent", "paper", "tickets")],
            [6.00, 5.00, 3.60, 2.70, 1.80])
        from bot_program.orcs.models import OrcSetting
        OrcSetting.objects.create(key="triage", value={"reserve_share": 0.9,
                                                       "reserve_cap": 50})
        odd = ceilings(6.0)
        self.assertGreaterEqual(odd["real"], odd["paper_urgent"],
                                "an override cannot invert them either")

    def test_paper_urgent_stops_at_60_and_a_real_urgent_runs_at_95(self):
        """P6 at C = $6 and R = $1: $3.50 booked stops a paper urgent wake
        (3.60), a paper routine one (2.70), but not a real routine one
        (5.00); at $5.70 (95%) a real urgent wake is still claimed and
        read, and a real routine one stops."""
        from bot_program.orcs import scheduler
        live = self.live()
        lw = self.rendered([W4], orc=live)
        self.book(3.50)
        self.assertEqual(self.admit(self.twin(lw, reasons=[W4]))["code"],
                         "triage", "paper urgent past 60%")
        self.assertEqual(self.admit(self.twin(lw, reasons=[W2]))["code"],
                         "triage", "paper routine past 45%")
        real_routine = self.twin(lw, reasons=[W2], orc=live)
        self.assertEqual(self.admit(real_routine)["status"], "pending")
        type(real_routine).objects.filter(pk=real_routine.pk).update(
            status="skipped", dedupe_key="rr")
        self.book(2.20)                             # $5.70 of $6.00
        self.assertEqual(self.admit(real_routine)["code"], "triage",
                         "real non-urgent past C - R")
        self.assertEqual(self.admit(lw)["status"], "pending")
        got = scheduler.claim()
        self.assertEqual(got["wake"].pk, lw.pk, "real urgent at 95%")
        from bot_program.orcs import mind
        self.use_fake(fake_answer(answer()))
        mind.think(got["wake"])
        self.assert_one_call()

    def test_a_real_routine_wake_is_claimed_before_a_paper_urgent_one(
            self):
        """A.14: the rank, 3 real urgent, 2 real routine, 1 paper urgent,
        0 paper routine; the claim takes -priority, queued_at, id."""
        from bot_program.orcs import scheduler
        live = self.live()
        paper_urgent = self.rendered([W4])
        real_routine = self.twin(paper_urgent, reasons=[W2], orc=live)
        early = timezone.now() - timedelta(minutes=5)
        self.assertEqual(self.admit(paper_urgent, now=early)["priority"],
                         1.0)
        self.assertEqual(self.admit(real_routine)["priority"], 2.0)
        self.assertEqual(scheduler.claim()["wake"].pk, real_routine.pk)

    def test_demo_and_no_world_rows_are_budgeted_as_paper(self):
        """P7, §4 Q6: real means the seat AND the row's own world live; a
        demo row and a row that states no world are paper (birth.world
        would read no world as live)."""
        from bot_program.orcs import scheduler
        live = self.live()
        self.assertTrue(scheduler.is_real(live))
        demo_row = _row(self.cfg, paper=False, symbol=self.symbol,
                        meta={"broker_env": "paper"})
        demo = born(self, demo_row, at=self.orc.born_at)
        self.assertEqual(demo.seat.venue, "demo")
        self.assertFalse(scheduler.is_real(demo))
        self.assertFalse(scheduler.is_real(self.orc), "paper")
        with patch("dashboard.position_summary.world_of", return_value=""):
            self.assertFalse(scheduler.is_real(live), "no world: paper")
        from bot_program.orcs.birth import world
        with patch("dashboard.position_summary.world_of", return_value=""):
            self.assertEqual(world(live.root_trade), "live",
                             "the trap A.14 avoids")
        self.assertEqual(scheduler.rank(False, True), 1)
        self.assertEqual(scheduler.rank(True, False), 2)


# ── the merge (A.7 step 1, P15) ──────────────────────────────────────────

class TheMergeTests(QueueFixture):

    def test_a_newer_routine_wake_absorbs_an_older_urgent_one(self):
        """The survivor takes the union of the reasons, each keeping its
        urgency; it is urgent, skips the spacing and keeps the older
        first send; the older wake is merged."""
        from bot_program.orcs import scheduler
        base = self.rendered()
        older = self.twin(base, reasons=[W4])
        first = timezone.now() - timedelta(minutes=12)
        self.assertEqual(self.admit(older, now=first)["status"], "pending")
        from bot_program.orcs.models import Orc
        Orc.objects.filter(pk=self.orc.pk).update(
            last_wake_at=timezone.now() - timedelta(minutes=3))
        newer = self.twin(base, reasons=[W2])
        self.assertEqual(scheduler.absorb(newer), 1)
        newer.refresh_from_db()
        self.assertEqual([r["key"] for r in newer.reasons],
                         [W2["key"], W4["key"]])
        self.assertEqual([r["urgent"] for r in newer.reasons],
                         [False, True])
        self.assertEqual(newer.components["queued_at_inherited"],
                         first.isoformat())
        out = self.admit(newer)
        newer.refresh_from_db()
        self.assertEqual((out["status"], newer.priority), ("pending", 1.0),
                         "urgent, so no spacing; paper urgent's rank")
        self.assertEqual(newer.queued_at, first, "the older first send")
        older.refresh_from_db()
        self.assertEqual((older.status, older.components["merged_into"]),
                         ("merged", newer.pk))
        self.assertIsNotNone(older.finished_at)

    def test_a_plan_watch_never_makes_the_survivor_urgent(self):
        from bot_program.orcs import scheduler
        base = self.rendered()
        older = self.twin(base, reasons=[PLAN])
        self.assertEqual(self.admit(older)["status"], "pending")
        newer = self.twin(base, reasons=[W2])
        scheduler.absorb(newer)
        newer.refresh_from_db()
        self.assertFalse(scheduler.is_urgent(newer.reasons))
        self.assertTrue(scheduler.is_routine(newer.reasons),
                        "a plan watch is routine")
        self.assertEqual(self.admit(newer)["priority"], 0.0)


class TheAdmissionIsPureEnoughTests(MindTestCase):
    """The pieces with no fixture: urgency and routine-ness."""

    def test_urgency_ignores_the_plans_watches(self):
        from bot_program.orcs.scheduler import is_routine, is_urgent
        self.assertTrue(is_urgent([W2, W4]))
        self.assertFalse(is_urgent([PLAN, {**PLAN, "urgent": True}]))
        self.assertTrue(is_routine([W2, PLAN]))
        self.assertFalse(is_routine([W2, W4]))
        self.assertFalse(is_routine([]))
