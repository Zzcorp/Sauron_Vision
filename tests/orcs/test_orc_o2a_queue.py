"""T10, THE QUEUE, ITS WORKER AND ITS WATCHDOG (the O2 spec A.16-A.19,
A.51-A.56; §1.1.7 T10 and its extras; P4, P8-P14, P16, P17; 2026-11-05).
Wakes are admitted and claimed by hand (the render does not admit yet),
read by mind.think on the fake model (N7), watched by scheduler.watch at
chosen moments.

- the stall alarm fires 20 minutes after the FIRST send, whatever
  happened since (P9)
- a pending wake 30 minutes old closes `stale` with `worker_silent` when
  the worker was silent, and its Orc goes to the care (P10); behind a busy
  worker it closes `backlog`, a code answer, and no Orc changes state
  (P11, P14); a gate OFF or a paused watchdog close it by code with no
  care; a pending wake 25 minutes old is still served (P14)
- silence and the care count only failed and silent-stale wakes: a day of
  code answers leaves the Orc active; two failed calls or two refused
  answers in a row send it to the care; a valid answer without the
  takeover leaves it there, one citing it returns it (P11, P13, P17)
- the claim: the spacing again (P12); the cold-burst rule (A.16); a row
  closed inside the call writes the booking and the late entry only (P16)
- the breaker after five failed calls (P8); one run stops at THINK_RUN_S
  and reads the four gates at every claim (A.19, A.2)
- the tasks: orc_think on `orcs` and its worker in the compose file,
  orc_minds_watch on `slow` (P4, N8); the minds switch off closes the
  pending wakes; neither result names skipped, parsed or attempted; a
  render pass that admitted a wake sends one orc_think ticket

Run with:  python manage.py test tests.orcs.test_orc_o2a_queue
"""
from datetime import timedelta
from unittest.mock import patch

from django.utils import timezone

from tests.orcs.helpers import _switch
from tests.orcs.helpers_o2 import PreStream, fake_answer
from tests.orcs.test_orc_o2a_admission import W2, W4, QueueFixture
from tests.orcs.test_orc_o2a_call import answer

#: Each code a queue path answers by, and the test that proves it with
#: its pair (T16 reads this table from the source).
ZERO_CALL_CODES = {
    "stale": "TheWatchdogTests.test_a_silent_workers_stale_wake_gives_the_care",
    "spacing": "TheClaimTests.test_the_spacing_again_at_the_claim",
    "breaker": "TheBreakerTests.test_five_failed_calls_open_the_breaker",
    "platform_off": "TheRunTests.test_the_platform_master_off_between_claims",
    "minds_off": "TheTaskTests.test_the_minds_switch_off_closes_the_queue",
    "paused": "TheWatchdogTests.test_a_paused_watchdog_answers_by_code",
}
#: The task gate reads these result keys as a health verdict.
GATE_KEYS = ("skipped", "parsed", "attempted")
#: A worker's fake answer: no call, the pace of a settle (P11, P14).
SETTLED = {"kind": "closed", "code": "line", "why": "the test's worker",
           "rung": "r0"}


class _Queue(QueueFixture):
    """QueueFixture's helpers (tests/orcs/test_orc_o2a_admission.py)."""


# ── the watchdog (A.54, A.55) ────────────────────────────────────────────

class TheWatchdogTests(_Queue):

    def test_the_stall_fires_at_twenty_minutes_from_the_first_send(self):
        """P9: queued_at is set once; a send-back and a second admission
        never re-stamp it, and the stall counts from it."""
        from bot_program.orcs.models import OrcWake
        t0 = timezone.now() - timedelta(minutes=19)
        w = self.pending(self.rendered(), t0)
        self.assertEqual(self.watch(t0 + timedelta(minutes=19))[
            "minds_stalled"], 0)
        OrcWake.objects.filter(pk=w.pk).update(status="skipped")
        self.assertEqual(self.admit(w, now=t0 + timedelta(minutes=12))[
            "status"], "pending")
        out = self.watch(t0 + timedelta(minutes=21))
        self.assertEqual((out["status"], out["minds_stalled"]),
                         ("warning", 1))
        self.assertIn("1 wake(s) waited over 20 minutes", out["reason"])
        for key in GATE_KEYS:
            self.assertNotIn(key, out)

    def test_a_silent_workers_stale_wake_gives_the_care(self):
        """P10, A.52: no claim and no settle in the last 30 minutes: the
        wake closes `stale`, `worker_silent`, with no call, and the care
        takes the idea: a takeover FACT in fixed words, the state, its
        reason and its moment."""
        w = self.control()
        self.assert_one_call()
        late = timezone.now() + timedelta(minutes=31)
        waiting = self.pending(w, late - timedelta(minutes=31),
                               reasons=[W4])
        out = self.watch(late)
        waiting.refresh_from_db()
        self.assert_no_call(code="stale", got=waiting.status)
        self.assertEqual(waiting.skipped_reason, "worker_silent")
        self.assertEqual(out["minds_stale"], 1)
        self.orc.refresh_from_db()
        self.assertEqual(self.orc.state, "care_owned")
        self.assertEqual(self.orc.care_owned_reason,
                         "a wake waited 30 minutes for a silent worker")
        took = self.took(self.orc)
        self.assertEqual(len(took), 1)
        self.assertTrue(took[0].fact_id.startswith("F"))
        self.assertEqual(took[0].body["fk"], "care")
        self.assertEqual(took[0].headline, "The care holds this position: a "
                         "wake waited 30 minutes for a silent worker.")

    def test_a_busy_worker_closes_its_backlog_and_no_orc_changes_state(
            self):
        """P11, P14: 40 pending wakes, a worker settling one every 2
        minutes, the watchdog every 5: the wakes past 30 minutes close
        `backlog` (a code answer), none `stale`, and no Orc goes to the
        care."""
        from bot_program.orcs import scheduler
        from bot_program.orcs.models import Orc, OrcWake
        base = self.rendered([W2])
        t0 = timezone.now() - timedelta(hours=1)
        orcs = self.orcs(39) + [self.orc]
        for orc in orcs:
            self.pending(base, t0, orc=orc, reasons=[W2])
        served, reports = 0, []
        for minute in range(0, 40):
            at = t0 + timedelta(minutes=minute)
            if minute % 2 == 0:
                got = scheduler.claim(now=at)
                if got["wake"] is not None:
                    scheduler.settle(got["wake"], dict(SETTLED), now=at)
                    served += 1
            if minute % 5 == 0 and minute:
                reports.append(self.watch(at))
        # claims at minutes 0, 2, ..., 34; the pass at 35 closes the rest
        self.assertEqual(served, 18)
        statuses = list(OrcWake.objects.filter(orc__in=orcs).exclude(
            pk=base.pk).values_list("status", "skipped_reason"))
        backlog = [s for s in statuses if s == ("skipped", "backlog")]
        self.assertEqual(len(backlog), 40 - served)
        self.assertFalse([s for s in statuses if s[0] in ("stale",
                                                          "pending")])
        self.assertEqual(sum(r["minds_backlog"] for r in reports),
                         40 - served)
        self.assertEqual(sum(r["minds_stale"] for r in reports), 0)
        self.assertEqual(reports[-1]["status"], "warning")
        self.assertIn("busy worker", reports[-1]["reason"])
        self.assertFalse(Orc.objects.filter(state="care_owned").exists())
        self.assertEqual(self.took(self.orc), [])

    def test_a_paused_watchdog_answers_by_code(self):
        """A.55: the watchdog did not run for over 10 minutes before this
        pass: a stale wake is answered by code, `paused`, with no care."""
        w = self.control()
        self.assert_one_call()
        at = timezone.now() + timedelta(minutes=45)
        waiting = self.pending(w, at - timedelta(minutes=35), reasons=[W4])
        out = self.watch(at, last=at - timedelta(minutes=25))
        waiting.refresh_from_db()
        self.assert_no_call(code="paused", got=waiting.skipped_reason)
        self.assertEqual(waiting.status, "skipped")
        self.assertEqual(out["minds_stale"], 0)
        self.orc.refresh_from_db()
        self.assertNotEqual(self.orc.state, "care_owned")

    def test_a_gate_off_closes_by_code_with_no_care(self):
        """A.55: platform_off and minds_off are code answers, never
        silence."""
        base = self.rendered([W4])
        for gate, code in (("platform_master", "platform_off"),
                           ("orcs_minds", "minds_off")):
            with self.subTest(gate):
                at = timezone.now() + timedelta(minutes=40)
                w = self.pending(base, at - timedelta(minutes=31))
                _switch(gate, False)
                self.watch(at)
                _switch(gate, True)
                w.refresh_from_db()
                self.assertEqual((w.status, w.skipped_reason),
                                 ("skipped", code))
                self.orc.refresh_from_db()
                self.assertNotEqual(self.orc.state, "care_owned")

    def test_a_pending_wake_25_minutes_old_is_still_served(self):
        """P14: the stale clock is 30 minutes; at 25 the watchdog leaves
        it, and the claim serves it."""
        at = timezone.now()
        w = self.pending(self.rendered(), at - timedelta(minutes=25))
        out = self.watch(at)
        self.assertEqual((out["minds_stale"], out["minds_backlog"]), (0, 0))
        got = self.serve(now=at, script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()


# ── the care's causes (A.51-A.53) ────────────────────────────────────────

class TheCareTests(_Queue):

    def _read(self, reasons=None, *script):
        w = self.rendered(reasons or [W4])
        self.assertEqual(self.admit(w)["status"], "pending")
        return self.serve(script=script[0])["wake"]

    def test_a_day_of_code_answers_leaves_the_orc_active(self):
        """P11, P17: born -> active on the first done wake; then wakes
        answered by code (the day's cap, the spacing) move neither counter
        and the Orc stays active."""
        from bot_program.orcs.models import OrcSetting
        self._read([W4], fake_answer(answer()))
        self.orc.refresh_from_db()
        self.assertEqual(self.orc.state, "active", "A.51")
        OrcSetting.objects.create(key="wakes_per_day", value={"paper": 1})
        base = self.rendered([W2])
        for i in range(12):
            t = self.twin(base, reasons=[{**W2, "key": f"W2:{i}"}])
            self.assertIn(self.admit(t)["code"], ("day_cap", "spacing"))
        self.orc.refresh_from_db()
        self.assertEqual(self.orc.state, "active")
        self.assertEqual((self.orc.seen.get("refused_in_row"),
                          self.orc.seen.get("failed_in_row")), (0, 0))

    def test_two_failed_calls_in_a_row_send_the_orc_to_the_care(self):
        self._read([W4], PreStream(TimeoutError("read timed out")))
        self.orc.refresh_from_db()
        self.assertEqual((self.orc.state, self.orc.seen["failed_in_row"]),
                         ("born", 1))
        self._read([{**W4, "key": "W4:b"}],
                   PreStream(TimeoutError("read timed out")))
        self.orc.refresh_from_db()
        self.assertEqual((self.orc.state, self.orc.care_owned_reason),
                         ("care_owned", "two model calls in a row failed"))
        self.assertEqual(self.orc.seen["failed_in_row"], 0, "reset")

    def test_two_refused_answers_in_a_row_send_the_orc_to_the_care(self):
        bad = fake_answer(answer(action="tighten", level_id="XX-1"))
        self._read([W4], bad)
        self.orc.refresh_from_db()
        self.assertEqual(self.orc.seen["refused_in_row"], 1)
        self._read([{**W4, "key": "W4:b"}], fake_answer(answer()))
        self.orc.refresh_from_db()
        self.assertEqual(self.orc.seen["refused_in_row"], 0,
                         "a done wake resets both")
        self._read([{**W4, "key": "W4:c"}], bad)
        self._read([{**W4, "key": "W4:d"}], bad)
        self.orc.refresh_from_db()
        self.assertEqual((self.orc.state, self.orc.care_owned_reason),
                         ("care_owned", "two answers in a row were refused"))

    def test_only_an_answer_citing_the_takeover_returns_the_orc(self):
        """P13, A.53: after the takeover, a valid answer that omits the
        fact leaves the Orc care_owned; one whose dossier carried it and
        that cites it returns the Orc (a `return` entry)."""
        from bot_program.orcs import scheduler
        from bot_program.orcs.models import OrcJournal
        scheduler.takeover(self.orc, "answers_refused", now=timezone.now())
        self.orc.refresh_from_db()
        took = self.took(self.orc)[0]
        self._read([W4], fake_answer(answer()))
        self.orc.refresh_from_db()
        self.assertEqual(self.orc.state, "care_owned")
        self._read([{**W4, "key": "W4:b"}], fake_answer(answer(
            facts_cited=[took.fact_id], note="Holding; the care took it.")))
        self.orc.refresh_from_db()
        self.assertEqual((self.orc.state, self.orc.care_owned_reason),
                         ("active", ""))
        back = OrcJournal.objects.get(orc=self.orc, kind="return")
        self.assertEqual(back.headline, "The Orc reads its position again: "
                         "it cited the takeover.")
        self.assertEqual(back.body["takeover"], took.fact_id)


# ── the claim (A.15, A.16, A.18, A.26) ───────────────────────────────────

class TheClaimTests(_Queue):

    def test_the_spacing_again_at_the_claim(self):
        """P12: a routine wake admitted while spaced is answered by code
        at the claim when the Orc's last claimed model wake is now 5
        minutes old (another worker claimed one of its wakes meanwhile)."""
        from bot_program.orcs import scheduler
        from bot_program.orcs.models import Orc
        w = self.control()
        self.assert_one_call()
        at = timezone.now() + timedelta(minutes=16)
        routine = self.pending(w, at, reasons=[W2])
        Orc.objects.filter(pk=self.orc.pk).update(last_wake_at=at)
        got = scheduler.claim(now=at + timedelta(minutes=5))
        self.assertIsNone(got["wake"])
        routine.refresh_from_db()
        self.assert_no_call(code="spacing", got=routine.skipped_reason)
        self.assertEqual(got["by_code"], 1)

    def test_the_cold_burst_rule(self):
        """A.16: the first call on a cold model runs alone; the second
        worker's non-urgent wake waits, pending; an urgent wake never
        waits; once the cold call returns, the held wake is claimed."""
        from bot_program.orcs import scheduler
        base = self.rendered([W2])
        a_orc, b_orc, c_orc = self.orcs(3)
        at = timezone.now()
        a = self.pending(base, at - timedelta(minutes=3), orc=a_orc)
        b = self.pending(base, at - timedelta(minutes=2), orc=b_orc)
        first = scheduler.claim(now=at)["wake"]
        self.assertEqual(first.pk, a.pk)
        self.assertTrue(first.components["cold"])
        second = scheduler.claim(now=at)
        self.assertIsNone(second["wake"])
        self.assertEqual(second["waiting"], 1)
        b.refresh_from_db()
        self.assertEqual(b.status, "pending")
        c = self.pending(base, at, orc=c_orc, reasons=[W4])
        urgent = scheduler.claim(now=at)["wake"]
        self.assertEqual(urgent.pk, c.pk, "an urgent wake never waits")
        self.assertFalse(urgent.components["cold"], "the model is warm")
        scheduler.settle(first, dict(SETTLED), now=at)
        self.assertEqual(scheduler.claim(now=at)["wake"].pk, b.pk)

    def test_a_row_closed_inside_the_call_writes_the_booking_only(self):
        """P16 through the queue: the claimed wake's row closes while the
        model reads; the answer is booked and journaled late, nothing
        else."""
        from bot_program.models import AssetBotTrade
        w = self.rendered()
        self.admit(w)
        real_send = self.fake._send
        table = AssetBotTrade._meta.db_table

        def send(path, kwargs):
            out = real_send(path, kwargs)
            from django.db import connection
            with connection.cursor() as cur:
                cur.execute(f"UPDATE {table} SET status = %s WHERE id = %s",
                            ["CLOSED", self.row.pk])
            return out
        self.fake._send = send
        got = self.serve(script=fake_answer(answer(action="revise_plan")))
        self.assertEqual((got["settle"]["status"], got["settle"]["code"]),
                         ("late", "row_closed"))
        self.assertEqual(self.entries(kind="plan"), [])
        self.orc.refresh_from_db()
        self.assertEqual(self.orc.state, "born", "no state change")
        self.assertGreater(float(self.orc.spend_today_usd), 0, "booked")


# ── the breaker (A.56) ───────────────────────────────────────────────────

class TheBreakerTests(_Queue):

    def test_five_failed_calls_open_the_breaker(self):
        """P8: five calls of any Orcs failed within ten minutes open it for
        fifteen; a claim in the pause is answered `breaker`, never
        silence, with no call; the watchdog shows it."""
        from bot_program.orcs import mind, scheduler
        base = self.rendered()
        # admitted before the failures, ranked after them (non-urgent)
        w = self.pending(base, timezone.now(), reasons=[W2])
        for orc in self.orcs(5):
            self.pending(base, timezone.now(), orc=orc)
            got = scheduler.claim()
            self.assertNotEqual(got["wake"].pk, w.pk)
            self.use_fake(PreStream(TimeoutError("read timed out")))
            mind.think(got["wake"])
            self.assert_one_call()
        state = scheduler.breaker_state(timezone.now())
        self.assertIn("5 model calls failed within 10 minutes", state["why"])
        got = scheduler.claim()
        w.refresh_from_db()
        self.assert_no_call(code="breaker", got=w.skipped_reason)
        self.assertIsNone(got["wake"])
        self.assertEqual(self.admit(self.twin(base))["code"], "breaker",
                         "admission reads it too (A.11 step 5)")
        out = self.watch(timezone.now())
        self.assertEqual(out["minds_breaker"], 1)
        self.assertIn("the breaker pauses the claims", out["reason"])
        later = timezone.now() + timedelta(minutes=16)
        self.assertEqual(scheduler.breaker_state(later), {})


# ── one run (A.19) ───────────────────────────────────────────────────────

class TheRunTests(_Queue):

    def test_one_run_stops_at_think_run_s(self):
        """A.19: a run claims and reads one wake at a time and stops once
        THINK_RUN_S (100 s) passed since it started."""
        from bot_program.orcs import scheduler
        from bot_program.orcs.constants import THINK_RUN_S
        self.assertEqual(THINK_RUN_S, 100)
        base = self.rendered()
        for orc in self.orcs(3):
            self.pending(base, timezone.now(), orc=orc)
        ticks = iter([0.0, 30.0, 60.0, 101.0, 130.0])
        self.use_fake(fake_answer(answer()))
        out = scheduler.run(clock=lambda: next(ticks))
        self.assertEqual(out["thought"], 2)
        self.assertEqual(len(self.requests), 2)
        from bot_program.orcs.models import OrcWake
        self.assertEqual(OrcWake.objects.filter(status="pending").count(), 1)

    def test_the_platform_master_off_between_claims(self):
        """A.2: guarded_task reads the platform master when a task starts;
        each claim reads it again, so a run that began before a global
        stop makes no further call."""
        from bot_program.orcs import mind, scheduler
        base = self.rendered()
        a_orc, b_orc = self.orcs(2)
        self.pending(base, timezone.now() - timedelta(minutes=1), orc=a_orc)
        second = self.pending(base, timezone.now(), orc=b_orc)
        real_think = mind.think

        def think(w, **kw):
            out = real_think(w, **kw)
            _switch("platform_master", False)   # the operator's stop
            return out
        self.use_fake(fake_answer(answer()))
        with patch.object(mind, "think", think):
            out = scheduler.run()
        self.assertEqual((out["thought"], out["by_code"]), (1, 1))
        self.assert_one_call()
        second.refresh_from_db()
        self.assert_no_call(code="platform_off", got=second.skipped_reason)
        self.assertEqual(second.status, "skipped")


# ── the tasks (A.17) ─────────────────────────────────────────────────────

class TheTaskTests(_Queue):

    def test_the_routes_the_beats_and_the_consumers(self):
        """P4, N8: orc_think on `orcs`, consumed by worker-orc alone (two
        slots, worker-fast's healthcheck, after the migrations);
        orc_minds_watch on `slow`; every routed queue has a consumer; the
        beats; both behind the orcs switch; still no orcs glob."""
        import yaml
        from celery.app.routes import MapRoute
        from django.conf import settings

        from config.celery import app
        from core import day_of_sauron as day
        routes = dict(app.conf.task_routes)
        route = MapRoute(routes)
        self.assertEqual(route("bot_program.orcs.tasks.orc_think"),
                         {"queue": "orcs"})
        self.assertEqual(route("bot_program.orcs.tasks.orc_minds_watch"),
                         {"queue": "slow"})
        self.assertFalse([k for k in routes if k.startswith(
            "bot_program.orcs") and "*" in k])
        compose = yaml.safe_load(open(f"{settings.BASE_DIR}/deploy/"
                                      f"docker-compose.yml").read())
        services = compose["services"]
        consumers = {}
        for name, svc in services.items():
            cmd = svc.get("command") or ""
            if "celery" in cmd and "worker" in cmd and "-Q" in cmd:
                for q in cmd.split("-Q")[1].split()[0].split(","):
                    consumers.setdefault(q, []).append(name)
        for queue in {r["queue"] for r in routes.values()} | {
                app.conf.task_default_queue}:
            self.assertIn(queue, consumers, queue)
        self.assertEqual(consumers["orcs"], ["worker-orc"])
        orc = services["worker-orc"]
        self.assertIn("-Q orcs -c 2 ", orc["command"])
        self.assertEqual(orc["healthcheck"],
                         services["worker-fast"]["healthcheck"])
        self.assertEqual(orc["depends_on"]["migrate"]["condition"],
                         "service_completed_successfully")
        beat = app.conf.beat_schedule
        self.assertEqual(beat["orc-think"], {
            "task": "bot_program.orcs.tasks.orc_think", "schedule": 60.0,
            "options": {"expires": 55, "expire_seconds": 55}})
        self.assertEqual(beat["orc-minds-watch"], {
            "task": "bot_program.orcs.tasks.orc_minds_watch",
            "schedule": 300.0,
            "options": {"expires": 280, "expire_seconds": 280}})
        self.assertEqual(day.STAGE_OF["orc-think"][0], "think")
        self.assertEqual(day.STAGE_OF["orc-minds-watch"][0], "watch")
        from bot_program.orcs import tasks
        for task in (tasks.orc_think, tasks.orc_minds_watch):
            self.assertEqual(task.run.component_key, "orcs")
        _switch("orcs", False)
        for task in (tasks.orc_think, tasks.orc_minds_watch):
            self.assertEqual(task()["status"], "skipped")

    def test_the_minds_switch_off_closes_the_queue(self):
        """A.17: with the minds switch off, orc_think answers every pending
        wake by code (`minds_off`) and is idle: no call."""
        from bot_program.orcs import tasks
        w = self.control()
        self.assert_one_call()
        waiting = self.pending(w, timezone.now(), reasons=[W4])
        _switch("orcs_minds", False)
        out = tasks.orc_think()
        waiting.refresh_from_db()
        self.assert_no_call(code="minds_off", got=waiting.skipped_reason)
        self.assertEqual(out, {"idle": "the minds switch is off; 1 waiting "
                                       "wake(s) answered by code"})

    def test_the_results_never_name_the_gates_health_keys(self):
        """census.py's rule: a result never names skipped, parsed or
        attempted; an idle pass is idle."""
        from bot_program.orcs import tasks
        self.assertIn("idle", tasks.orc_think())
        self.assertIn("idle", tasks.orc_minds_watch())
        self.pending(self.rendered(), timezone.now())
        self.use_fake(fake_answer(answer()))
        out = tasks.orc_think()
        self.assertEqual(out, {"status": "success", "thought": 1,
                               "by_code": 0})
        self.assert_one_call()
        watch = tasks.orc_minds_watch()
        for result in (out, watch):
            for key in GATE_KEYS:
                self.assertNotIn(key, result)
        for key in ("minds_stalled", "minds_stale", "minds_backlog",
                    "minds_wall_time", "minds_holds", "minds_ledger_gap",
                    "minds_breaker", "answered_by_code"):
            self.assertIn(key, watch)

    def test_a_render_pass_that_admitted_sends_one_ticket(self):
        """A.17: one orc_think ticket after a render pass that admitted any
        wake, none otherwise; render_queued reports its admitted count
        (0 until the render admits)."""
        from bot_program.orcs import tasks, wake
        from bot_program.orcs.wake import RenderPass
        out = RenderPass(3, 1, admitted=2)
        self.assertEqual((tuple(out), out.admitted), ((3, 1), 2))
        self.assertEqual(wake.render_queued().admitted, 0)
        with patch.object(wake, "render_queued",
                          return_value=RenderPass(3, 0, admitted=2)), \
                patch.object(tasks.orc_think, "delay") as ticket:
            result = tasks.orc_render_wakes()
        self.assertEqual(ticket.call_count, 1)
        self.assertEqual(result["admitted"], 2)
        with patch.object(wake, "render_queued",
                          return_value=RenderPass(3, 0)), \
                patch.object(tasks.orc_think, "delay") as ticket:
            tasks.orc_render_wakes()
        self.assertEqual(ticket.call_count, 0)
