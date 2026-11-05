"""T11, WHAT A WAKE CARRIES INTO THE QUEUE (the O2 spec A.9, A.10, A.28,
A.29, A.47-A.50; §1.1.7 T11 and A.9's case; P23, P25-P29; 2026-11-05).

- S (P29) is O2a's mind's, proven where it was built
  (tests/orcs/test_orc_o2a_call.py: S under its cap and the reserve,
  byte-stable, stored as a block a replay prints; the gateway's
  `authority` pair while a seat reads above L0)
- the facts hash, version 2 (A.10): the plan's version, the watched
  levels by stored reference (never by id), the next print in bands; the
  same facts with plan v1 then v2 are not quiet (P27)
- F6's reference (A.9): while the minds switch is on, a wake answered by
  code never makes the next metronome quiet; a validated answer does;
  with the switch off O1's proxy stays
- the plan's watches (A.48, P28): near the mark, recorded non-urgent from
  the plan, routine, spaced, counted toward the day caps; on a real Orc
  with 4 clauses near the mark the wake ranks 2 and stops at the count
  cap and the spacing
- the asked wake (A.49, P23): a validated next_wake_min of 40 fires at
  +40 minutes, is consumed, and moves next_wake_due
- the metronome (A.50): from any recorded wake, at the army type's period
- a refusal at wake N, a wake answered by code by admission at N+1, and
  N+2's PS5 still lists N's refusal (P26 through the queue). PS3's last
  expectation (P25), PS12's watch column and BE's cost, PS1's events are
  proven where they are built (tests/orcs/test_orc_o2a_validator.py,
  test_orc_o2a_officer.py)

Run with:  python manage.py test tests.orcs.test_orc_o2a_dossier
"""
import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.utils import timezone

from tests.orcs.helpers import _switch
from tests.orcs.helpers_o2 import MindTestCase, fake_answer
from tests.orcs.test_orc_o2a_admission import W2, W4, QueueFixture
from tests.orcs.test_orc_o2a_call import NOW, answer

W11 = {"code": "W11", "key": "W11:metronome", "t": "metronome",
       "urgent": False}
WATCH = {"level_id": "S4h-L1", "kind": "swing", "tf": "4h", "price": 99.0,
         "stop": 98.5, "side": "below", "clause": "trim"}


class _Dossier(QueueFixture):

    def facts_of(self, w):
        w.refresh_from_db()
        return w.components.get("facts_hash")

    def detect(self, at, *, price="100.5"):
        """wake.detect as the tick runs it at `at` (its own memory as the
        tick leaves it), with no render; the decision bar's W2 left out,
        so the reason under test is alone."""
        from bot_program.orcs import wake
        self.orc.refresh_from_db()
        bot = SimpleNamespace(_tick_broker_cache={}, cfg=self.cfg,
                              _last_ticks={})
        self.row.refresh_from_db()
        self.row._care_tick = {"now": at}
        with patch("django.utils.timezone.now", return_value=at), \
                patch.object(wake, "_w2", return_value=None):
            return wake.detect(bot, self.row, price, "", self.orc)

    def seen(self, **keys):
        from bot_program.orcs.models import Orc
        self.orc.refresh_from_db()
        Orc.objects.filter(pk=self.orc.pk).update(
            seen={**(self.orc.seen or {}), **keys})
        self.orc.refresh_from_db()


# ── the facts hash, version 2 (A.10) ─────────────────────────────────────

class TheFactsHashTests(MindTestCase):

    BASE = {"r_now": 0.30, "menu": ["S4h-L1", "BE"], "po3": "manipulation",
            "calendar_min": 400, "thesis": "hold",
            "predicates": {"a": "unmet"}, "plan_v": 1,
            "watches": [{"kind": "swing", "tf": "4h", "price": 99.0}]}

    def test_the_print_counts_in_bands_not_hours(self):
        from bot_program.orcs.wake import facts_hash
        h = facts_hash(self.BASE)
        for minutes in (180, 400, 1000, 1440):
            self.assertEqual(facts_hash({**self.BASE,
                                         "calendar_min": minutes}), h,
                             minutes)
        for minutes in (179, 1441, None):
            self.assertNotEqual(facts_hash({**self.BASE,
                                            "calendar_min": minutes}), h,
                                minutes)
        self.assertEqual(facts_hash({**self.BASE, "calendar_min": 10}),
                         facts_hash({**self.BASE, "calendar_min": 170}))

    def test_the_plans_version_and_its_watches_by_stored_reference(self):
        from bot_program.orcs.wake import facts_hash
        h = facts_hash(self.BASE)
        self.assertNotEqual(facts_hash({**self.BASE, "plan_v": 2}), h)
        renamed = [{"kind": "swing", "tf": "4h", "price": 99.0,
                    "level_id": "S4h-L7"}]
        self.assertEqual(facts_hash({**self.BASE, "watches": renamed}), h,
                         "an id names nothing: the stored reference does")
        moved = [{"kind": "swing", "tf": "4h", "price": 99.5}]
        self.assertNotEqual(facts_hash({**self.BASE, "watches": moved}), h)
        self.assertNotEqual(facts_hash({**self.BASE, "watches": []}), h)

    def test_its_version_is_part_of_the_hashed_input(self):
        from bot_program.orcs import wake
        from bot_program.orcs.constants import FACTS_HASH_VERSION
        self.assertEqual(FACTS_HASH_VERSION, 2)
        h = wake.facts_hash(self.BASE)
        with patch.object(wake, "FACTS_HASH_VERSION", 3):
            self.assertNotEqual(wake.facts_hash(self.BASE), h)


# ── quiet wakes (A.9, P27) ───────────────────────────────────────────────

class TheQuietWakeTests(_Dossier):

    def test_the_same_facts_with_plan_v1_then_v2_are_not_quiet(self):
        """P27: with the last validated answer's hash as the reference,
        the same market facts are quiet until the plan moves."""
        from bot_program.orcs.models import Orc
        first = self.rendered([W11])
        Orc.objects.filter(pk=self.orc.pk).update(
            last_facts_hash=self.facts_of(first), plan_version=1)
        again = self.rendered([{**W11, "key": "W11:b"}])
        self.assertNotEqual(again.status, "quiet", "v0 -> v1 moved it")
        Orc.objects.filter(pk=self.orc.pk).update(
            last_facts_hash=self.facts_of(again))
        same = self.rendered([{**W11, "key": "W11:c"}])
        self.assertEqual(same.status, "quiet")
        Orc.objects.filter(pk=self.orc.pk).update(plan_version=2)
        moved = self.rendered([{**W11, "key": "W11:d"}])
        self.assertNotEqual(moved.status, "quiet")
        self.assertNotEqual(self.facts_of(moved), self.facts_of(same))

    def test_a_code_answered_wake_never_makes_the_next_metronome_quiet(
            self):
        """A.9: while the minds switch is on, F6 compares with the last
        VALIDATED answer's hash: a wake answered by code (here the day's
        cap) writes none, so the next metronome on the same facts is a
        full wake; once a model answered, it is quiet. With the switch
        off, O1's proxy keeps making it quiet, as in O1."""
        from bot_program.orcs.models import Orc, OrcSetting
        OrcSetting.objects.create(key="wakes_per_day", value={"paper": 0})
        coded = self.rendered([W11])
        self.assertEqual(self.admit(coded)["code"], "day_cap")
        self.orc.refresh_from_db()
        self.assertEqual(self.orc.last_facts_hash, "")
        nxt = self.rendered([{**W11, "key": "W11:b"}])
        self.assertNotEqual(nxt.status, "quiet")
        OrcSetting.objects.filter(key="wakes_per_day").delete()
        self.assertEqual(self.admit(self.twin(nxt, reasons=[W4]))["status"],
                         "pending")
        got = self.serve(script=fake_answer(answer()))
        self.assert_one_call()
        self.orc.refresh_from_db()
        self.assertEqual(self.orc.last_facts_hash, self.facts_of(nxt),
                         "a validated answer writes it")
        self.assertEqual(self.rendered([{**W11, "key": "W11:c"}]).status,
                         "quiet")
        self.assertEqual(got["settle"]["status"], "done")
        # the switch off: O1's proxy (the last non-quiet render's hash),
        # never the column, which is blanked here
        _switch("orcs_minds", False)
        Orc.objects.filter(pk=self.orc.pk).update(last_facts_hash="")
        self.assertEqual(self.rendered([{**W11, "key": "W11:d"}]).status,
                         "quiet", "O1's proxy, the switch off")


# ── the plan's watches (A.48, P28) ───────────────────────────────────────

class ThePlanWatchTests(_Dossier):

    def _watching(self, orc, watches):
        from bot_program.orcs.models import Orc
        Orc.objects.filter(pk=orc.pk).update(watches=watches)
        orc.refresh_from_db()

    def test_a_watch_near_the_mark_wakes_non_urgent_routine_and_spaced(
            self):
        """W3 reads Orc.watches beside the thesis: the mark within 0.1 x
        ATR(1h) of a watched level gives a W3 from the plan, never urgent,
        keyed W3:plan:<id>:<stamp>, remembered by its stored reference;
        it waits for the spacing at detection and at admission, and it
        counts toward the routine cap."""
        from bot_program.orcs import scheduler
        self._watching(self.orc, [WATCH])
        at = NOW + timedelta(minutes=30)
        self.seen(w1=True, last_recorded=(at - timedelta(minutes=5))
                  .isoformat(), w11_at=at.isoformat(), w2_bar="x")
        self.assertIsNone(self.detect(at, price="99.0"),
                          "non-urgent: it waits for the spacing")
        self.orc.refresh_from_db()
        pend = self.orc.seen["wake_pending"]["reasons"]
        self.assertEqual(len(pend), 1)
        r = pend[0]
        self.assertEqual((r["code"], r["urgent"], r["source"]),
                         ("W3", False, "plan"))
        self.assertTrue(r["key"].startswith("W3:plan:S4h-L1:"))
        self.assertEqual(r["level"], "plan:swing:4h:99")
        self.seen(last_recorded=(at - timedelta(minutes=20)).isoformat())
        w = self.detect(at + timedelta(minutes=1), price="99.0")
        self.assertIsNotNone(w)
        self.assertEqual([x["code"] for x in w.reasons], ["W3"])
        self.orc.refresh_from_db()
        self.assertIn("plan:swing:4h:99", self.orc.seen["w3_at"])
        self.assertTrue(scheduler.is_routine(w.reasons))
        self.assertFalse(scheduler.is_urgent(w.reasons))
        self.assertIsNone(self.detect(at + timedelta(minutes=40),
                                      price="99.0"),
                          "once per level per W3_ONCE_H")

    def test_four_clauses_near_the_mark_on_a_real_orc_stay_spaced_and_capped(
            self):
        """P28: an urgent watch would skip the spacing and pass the real
        count cap; the plan's clauses never do: rank 2, `spacing`, and
        `day_cap` at the real cap."""
        live = self.live()
        watches = [{**WATCH, "level_id": f"S4h-L{i}",
                    "price": 99.0 + 0.01 * i} for i in range(4)]
        self._watching(live, watches)
        base = self.rendered([W4], orc=live)
        reasons = [{"code": "W3", "key": f"W3:plan:S4h-L{i}:x",
                    "t": "the plan's watch", "urgent": False,
                    "source": "plan", "level": f"plan:swing:4h:{99 + i}"}
                   for i in range(4)]
        from bot_program.orcs.models import Orc
        Orc.objects.filter(pk=live.pk).update(
            last_wake_at=timezone.now() - timedelta(minutes=5))
        spaced = self.admit(self.twin(base, reasons=reasons, orc=live))
        self.assertEqual(spaced["code"], "spacing")
        Orc.objects.filter(pk=live.pk).update(
            last_wake_at=timezone.now() - timedelta(minutes=30))
        self.counters(live, llm_wakes_today=12)
        self.assertEqual(self.admit(self.twin(base, reasons=reasons,
                                              orc=live))["code"], "day_cap")
        self.counters(live, llm_wakes_today=2)
        ok = self.twin(base, reasons=reasons, orc=live)
        out = self.admit(ok)
        self.assertEqual((out["status"], out["priority"]), ("pending", 2.0))


# ── the asked wake (A.49, P23) and the metronome (A.50) ──────────────────

class TheAskedWakeTests(_Dossier):

    def test_the_asked_wake_fires_at_plus_forty_minutes(self):
        """A next_wake_min of 40 that passed V9: seen["w11_ask"] at the
        answer's time + 40 min, next_wake_due the earlier of the
        metronome and the ask; W11 fires at +40, not before, and the
        recorded wake consumes it."""
        from bot_program.orcs.constants import W11_ASK_WORDS
        w = self.rendered()
        self.assertEqual(self.admit(w)["status"], "pending")
        # read 10 minutes after the wake's moment, well inside its
        # metronome (NOW + 4 h): the ask is the earlier
        self.serve(now=NOW + timedelta(minutes=10),
                   script=fake_answer(answer(next_wake_min=40)))
        self.assert_one_call()
        self.orc.refresh_from_db()
        ask = self.orc.seen["w11_ask"]
        answered = type(w).objects.get(pk=w.pk).finished_at
        self.assertEqual(ask, (answered + timedelta(minutes=40)).isoformat())
        self.assertEqual(self.orc.next_wake_due,
                         answered + timedelta(minutes=40))
        at = answered + timedelta(minutes=39)
        self.seen(last_recorded=(at - timedelta(minutes=30)).isoformat(),
                  w11_at=(at - timedelta(minutes=30)).isoformat())
        self.assertIsNone(self.detect(at))
        fired = self.detect(answered + timedelta(minutes=40))
        self.assertIsNotNone(fired)
        self.assertEqual([(r["code"], r["t"]) for r in fired.reasons],
                         [("W11", W11_ASK_WORDS)])
        self.assertTrue(fired.reasons[0]["key"].startswith("W11:ask:"))
        self.orc.refresh_from_db()
        self.assertIsNone(self.orc.seen["w11_ask"], "consumed")
        self.assertEqual(self.orc.next_wake_due, answered + timedelta(
            minutes=40) + timedelta(hours=4), "the metronome again")

    def test_a_dropped_next_wake_asks_nothing(self):
        """V9: 5 minutes is under the spacing: the request is dropped, no
        ask is kept."""
        w = self.rendered()
        self.admit(w)
        self.serve(script=fake_answer(answer(next_wake_min=5)))
        self.assert_one_call()
        self.orc.refresh_from_db()
        self.assertNotIn("w11_ask", self.orc.seen)


class TheMetronomeTests(_Dossier):

    def test_w11_counts_from_any_recorded_wake_at_the_armys_cadence(self):
        """A.50: every recorded wake restarts the metronome (O1 counted
        from the last W11 only); its period is the army type's: Line 4 h,
        Mercenaries 1 h, Olog-hai 24 h; next_wake_due follows it."""
        from bot_program.orcs import wake
        from bot_program.orcs.models import Orc
        t0 = NOW + timedelta(minutes=10)
        self.seen(w1=True, w11_at=(t0 - timedelta(hours=3)).isoformat(),
                  last_recorded=(t0 - timedelta(hours=3)).isoformat(),
                  w2_bar="x")
        with patch("django.utils.timezone.now", return_value=t0):
            w = wake.record(self.orc, self.row, [W4], now=t0)
        self.assertIsNotNone(w)
        self.orc.refresh_from_db()
        self.assertEqual(self.orc.seen["w11_at"], t0.isoformat())
        self.assertEqual(self.orc.next_wake_due, t0 + timedelta(hours=4))
        self.assertIsNone(self.detect(t0 + timedelta(hours=3, minutes=59)),
                          "4 h from the last recorded wake, not the W11")
        fired = self.detect(t0 + timedelta(hours=4))
        self.assertEqual([r["code"] for r in fired.reasons], ["W11"])
        for army, hours in (("mercenaries", 1), ("olog_hai", 24)):
            with self.subTest(army):
                Orc.objects.filter(pk=self.orc.pk).update(army_type=army)
                self.orc.refresh_from_db()
                self.assertEqual(wake.metronome_h(self.orc), float(hours))
                last = t0 + timedelta(hours=5)
                self.seen(w11_at=last.isoformat(),
                          last_recorded=last.isoformat())
                early = last + timedelta(hours=hours) - timedelta(minutes=1)
                self.assertIsNone(self.detect(early))
                got = self.detect(last + timedelta(hours=hours))
                self.assertEqual([r["code"] for r in got.reasons], ["W11"])


# ── P26 through the queue ────────────────────────────────────────────────

class TheRefusalAcrossACodeAnswerTests(_Dossier):

    def test_a_refusal_survives_a_wake_answered_by_code(self):
        """P26: a refusal at wake N; wake N+1 answered by code at admission
        (the day's cap): it writes no decision, so N+2's PS5 still lists
        N's refusal with its rule."""
        from bot_program.orcs.models import OrcDossierBlock, OrcSetting
        w = self.rendered()
        self.admit(w)
        self.serve(script=fake_answer(answer(action="tighten",
                                             level_id="XX-1")))
        self.assert_one_call()
        OrcSetting.objects.create(key="wakes_per_day", value={"paper": 1})
        coded = self.rendered([{**W4, "key": "W4:b"}])
        self.assertEqual(self.admit(coded)["code"], "day_cap")
        later = self.rendered([{**W2, "key": "W2:c"}],
                              at=NOW + timedelta(minutes=20))
        ps = OrcDossierBlock.objects.get(hash=later.block_hashes[
            int(later.components["shared"])])
        notes = " ".join(json.loads(ps.text.partition("\n")[2])["ps5"][
            "notes"])
        self.assertIn("refused (V5)", notes)
