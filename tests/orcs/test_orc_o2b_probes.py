"""O2b's THIRD COMMIT, THE PROBES (the O2 spec B.8a, B.11, B.12, B.15b's
probe row, B.16a, B.16b and N2 for `orcs_probes`; §1.2.5 P1, P5's twin,
P6's twin, P22, P36-P39; §1.2.6 "Probes", the PIN, "Fallbacks" (a probe
sends none) and K-B10 on the probe requests; §1.2.7 "orcs_probes ON";
2026-11-06).

Behind a new switch, `orcs_probes` (OFF on arrival, the trading PIN to turn
it on), a paper or demo wake a model read (done or refused) is read once
more, blind to that answer, by a neighbouring rung on the wake's own stored
dossier: h0 on calm and eventful days, and the rung across a band boundary
when the score sits within 5 of 30, 55 or 75 (the route's probes). A probe
is a ticket on its own allowance (15% of the Orcs line by default) inside
C - R, never a wake: it is stored in OrcTierGrade and the ledger only, and
graded forward over the next final decision-frame bar. Real money gets
none. Nothing here turns a switch on for the operator.

- N2: the switch ships OFF beside the router, exempt from "all on", in
  ORC_MIND_SWITCHES and never a live-money switch; only the PIN turns it
  on; its pair: ON a paper wake records exactly one probe request, OFF
  none (read again at the reservation and at the gateway)
- which: a paper wake on a calm day at score 27 calls h0 and r1 (Sonnet's
  PASS recorded); the same wake on a stormy day calls neither; a
  real-money wake calls none; the weather's `probes` binds (B.8a)
- nowhere but OrcTierGrade and the ledger: no slot key, no PS block of the
  next wake, no journal entry, plan, intent, note, card line or counter
- the caps: the 7th boundary probe of a user in a day is refused, h0's cap
  is 40, both binding at once from OrcSetting "probes_per_day"
- the allowance: an r3 probe late in the UTC day still fits its own
  allowance; one past probes_usd_per_day is refused; probes stay inside
  C - R; the Orc's caps never move
- a refused probe is stored invalid; a probe sends no fallback and holds
  the primary's bound alone, on the Orcs line
- when: last of all (a waiting real-money wake stops them), within 15
  minutes of the routed answer, one billed attempt per item
- the rungs: h0, r0, r1, r3, r4, and r2 only as B.5's map of r3 and r4
- OrcTierGrade: kind, boundary, world, the answering rungs with would_rung,
  agreement, costs, blocks of 20 per (boundary, kind, world); the forward
  grade per action on fake bars, taken by the watchdog's task
- the surfaces: /ai-models/ per rung today's probes and each boundary's
  validation state ("validated" after two completed blocks); the staff
  ladder table on /orcs/seats/
- K-B10 over every probe request; the RUNBOOK's probes section
- PostgreSQL: two reservations racing for a user's last boundary probe of
  the day get one ticket between them

Run with:  python manage.py test tests.orcs.test_orc_o2b_probes
"""
import json
import re
import threading
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.db import connection
from django.utils import timezone

from tests.orcs.helpers import _bars, _config, _row, _switch, _user, born
from tests.orcs.helpers_o2 import (MindTestCase, MindTransactionTestCase,
                                   fake_answer, minds_on)
from tests.orcs.test_orc_o2a_call import NOW, answer
from tests.orcs.test_orc_o2b_routed import (TEST_PIN, W7, WRONG_PIN,
                                           _gateway_asks, _Routed, _row_of,
                                           _urgent)
from tests.orcs.test_orc_o2b_router import _verdicts

BASE = Path(settings.BASE_DIR)
RUNBOOK = BASE / "deploy" / "RUNBOOK.md"
KEY = "orcs_probes"
NAME = "Orc Probes (neighbouring rungs in shadow)"
DESCRIPTION = ("Off (default). On, with the minds on: beside a paper or demo "
               "wake a model read, a neighbouring rung reads the same "
               "dossier again, blind, on its own allowance (15% of the Orcs "
               "line); graded in shadow, never applied. Real money gets "
               "none. Turning it on takes the PIN.")
#: Patched scores: far from every boundary (h0 alone is due); 3 under 30
#: (h0 and r1 across it); 3 under 55 (h0 and r3 across it).
FAR, NEAR_30, NEAR_55 = 12.0, 27.0, 52.0
#: The Orcs line minds_on() sets (helpers_o2.MINDS_LINE_USD) and its parts.
LINE = 6.0
ALLOWANCE = 0.15 * LINE
C_MINUS_R = LINE - 1.0
#: The card's sentences on /ai-models/, by the probes' switch.
SAID_OFF = "The probes' switch (orcs_probes) is off: no rung is probed."
SAID_ON = ("The probes' switch (orcs_probes) is on: beside a paper or demo "
           "wake a model read, a neighbouring rung reads the same dossier "
           "again, blind, on the probes' own allowance.")
PG = connection.vendor == "postgresql"
NOT_PG = "two reservations racing need PostgreSQL's row locks"


def _probes_mod():
    from bot_program.orcs import probes
    return probes


# ── N2: the switch itself ────────────────────────────────────────────────

class TheProbesSwitchShipsOffTests(MindTestCase):

    def setUp(self):
        from core.platform_control import seed_components
        cache.clear()
        seed_components()

    def test_it_is_seeded_off_beside_the_router(self):
        from core.platform_control import DEFAULT_COMPONENTS

        from bot_program.orcs import switches
        row = _row_of(KEY)
        self.assertFalse(row.is_enabled)
        self.assertEqual((row.name, row.category), (NAME, "system"))
        self.assertEqual(row.description, DESCRIPTION)
        self.assertLess(len(row.description), 300)
        entry = [c for c in DEFAULT_COMPONENTS if c["key"] == KEY]
        self.assertEqual(len(entry), 1)
        self.assertNotIn("is_enabled", entry[0], "it arrives OFF")
        self.assertNotIn("enabled", entry[0])
        keys = [c["key"] for c in DEFAULT_COMPONENTS]
        self.assertEqual(keys.index(KEY), keys.index("orcs_router") + 1)
        self.assertFalse(switches.probes_on())
        self.assertEqual(switches.caller_code("probe"), "probes_off")
        _switch(KEY, True)
        self.assertTrue(switches.probes_on())
        self.assertEqual(switches.caller_code("probe"), "")
        for caller in ("wake", "smoke"):
            with self.subTest(caller=caller):
                self.assertEqual(switches.caller_code(caller), "",
                                 "no switch of its own beyond the gates")
        # an unreadable switch reads OFF
        with patch("core.platform_control.is_component_enabled",
                   side_effect=RuntimeError("the table is gone")):
            self.assertFalse(switches.probes_on())
            self.assertEqual(switches.caller_code("probe"), "probes_off")

    def test_it_is_exempt_held_back_and_never_live(self):
        from core import switch_pin
        from core.platform_control import (BULK_ENABLE_EXEMPT,
                                           LIVE_MONEY_SWITCHES,
                                           ORC_MIND_SWITCHES, PIN_SWITCHES)
        self.assertIn(KEY, ORC_MIND_SWITCHES)
        self.assertIn(KEY, BULK_ENABLE_EXEMPT)
        self.assertIn(KEY, PIN_SWITCHES)
        self.assertNotIn(KEY, LIVE_MONEY_SWITCHES)
        self.assertEqual(switch_pin._does(KEY), "lets a model spend AI money")
        switch_pin.set_category("system", True, via=switch_pin.VIA_ALL_ON)
        self.assertFalse(_row_of(KEY).is_enabled,
                         '"all on" never reaches it')


class OnlyThePinTurnsTheProbesOnTests(MindTestCase):

    def setUp(self):
        from core.platform_control import seed_components
        from portfolio.trader_profile import get_or_create_profile
        cache.clear()
        seed_components()
        self.admin = get_user_model().objects.create_superuser(
            "o2b_probes_admin", "o2b_probes@example.test", "x")
        prof = get_or_create_profile(self.admin)
        prof.set_pin(TEST_PIN)
        prof.save()
        self.client.force_login(self.admin)

    def ops(self, **extra):
        return self.client.post("/admin-dashboard/toggle/",
                                {"key": KEY, "next": "ops", **extra})

    def test_every_door_refuses_on_without_the_pin(self):
        self.ops()
        self.ops(want="on")
        self.ops(want="on", pin="")
        self.ops(want="on", pin=WRONG_PIN)
        self.client.post("/admin-dashboard/system-map/toggle/",
                         {"kind": "component", "key": KEY})
        with self.assertRaises(CommandError) as ctx:
            call_command("component", "on", KEY, stdout=StringIO())
        self.assertIn("/ops/", str(ctx.exception))
        row = _row_of(KEY)
        data = {"form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1",
                "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
                "form-0-id": str(row.pk), "form-0-is_enabled": "on",
                "_save": "Save"}
        self.client.post("/admin/core/platformcomponent/", data)
        self.assertFalse(_row_of(KEY).is_enabled, "no door armed it")
        from core import switch_pin
        self.assertFalse(switch_pin.set_switch(
            KEY, True, via=switch_pin.VIA_SHELL).ok)
        self.assertFalse(_row_of(KEY).is_enabled)

    def test_the_right_pin_turns_it_on_and_off_takes_none(self):
        from bot_program.audit_models import AuditLogEntry
        self.ops(want="on", pin=TEST_PIN)
        self.assertTrue(_row_of(KEY).is_enabled)
        armed = [e for e in AuditLogEntry.objects.filter(kind="switch_armed")
                 if (e.data or {}).get("key") == KEY]
        self.assertEqual(len(armed), 1)
        out = StringIO()
        call_command("component", "off", KEY, stdout=out)
        self.assertIn(f"{KEY}: ON → OFF", out.getvalue())
        self.assertFalse(_row_of(KEY).is_enabled)


# ── the probed wake (the render pass, the queue, the fake model) ─────────

class _Probed(_Routed):
    """_Routed's paper Orc and gates (the four ON, the Orcs line at $6),
    the router's switch OFF as it ships (r0 answers every wake), the
    probes' switch as each test sets it."""

    def probes_switch(self, on=True):
        _switch(KEY, on)

    def due(self, w=None):
        """The probes due now, as (kind, rung, boundary), of wake `w`."""
        out = []
        for x, p in _probes_mod().due(timezone.now()):
            if w is None or x.pk == w.pk:
                out.append((p["kind"], p["rung"], p["boundary"]))
        return out

    def send(self, w, kind):
        """The one due probe of `kind` beside wake `w`, sent."""
        probes = _probes_mod()
        got = [(x, p) for x, p in probes.due(timezone.now())
               if x.pk == w.pk and p["kind"] == kind]
        self.assertEqual(len(got), 1, f"the {kind} probe of wake {w.pk} is "
                                      f"due")
        return probes.send(*got[0])

    def probe_of(self, w, kind):
        """A due probe of `kind` beside wake `w` (its dict), unsent."""
        got = [p for x, p in _probes_mod().due(timezone.now())
               if x.pk == w.pk and p["kind"] == kind]
        self.assertEqual(len(got), 1)
        return got[0]

    def stormy(self):
        """Today's weather of the fixture's class raised to stormy (an
        upward re-run never lowers it)."""
        from bot_program.orcs import weather
        from bot_program.orcs.models import OrcDayBaseline
        row = weather.current(self.user, self.orc.asset_class,
                              timezone.now())
        OrcDayBaseline.objects.filter(pk=row.pk).update(day_class="stormy",
                                                        score=99.0)

    def seed_counts(self, **by_kind):
        """The tickets' book of today with the user's probe counts."""
        from bot_program.orcs import scheduler
        from bot_program.orcs.models import OrcSetting
        counts = {}
        for kind, n in by_kind.items():
            key, _cap = scheduler.ticket_cap("probe", {
                "kind": kind, "user": self.user.pk})
            counts[key] = n
        OrcSetting.objects.update_or_create(key="minds_tickets", defaults={
            "value": {"day": scheduler.utc_day(timezone.now()),
                      "counts": counts, "items": {}}})

    def book_probes(self, usd):
        """Probe spend booked today on the Orcs line (its ledger)."""
        from ai_agents.models import AgentTask
        AgentTask.objects.create(
            agent="orc", provider="claude", model="m",
            prompt_summary="a probe booked by the test",
            cost_usd=Decimal(str(round(usd, 6))),
            structured_output={"source_ref": "Orc:1:Wake:1:probe:r1"})

    def counters_of(self, orc):
        orc.refresh_from_db()
        return {k: getattr(orc, k) for k in (
            "llm_wakes_today", "routine_wakes_today", "spend_today_usd",
            "routine_spend_today_usd", "last_wake_at", "last_good_wake_at",
            "last_facts_hash", "latest_note", "latest_note_at", "plan",
            "plan_version", "plan_changes_24h", "watches", "state")} | {
            "seen": json.dumps(orc.seen, sort_keys=True, default=str),
            "card": json.dumps(orc.card, sort_keys=True, default=str)}


class TheSwitchPairTests(_Probed):
    """N2, N7's pair: the probes' own switch, read before each probe, at
    its reservation and again at the gateway (frictionless off)."""

    def test_on_a_paper_wake_records_one_probe_request_off_none(self):
        """ON: a paper wake far from every boundary (h0 alone is due)
        records exactly one probe request, on h0's model. OFF: the next
        paper wake records none, with the switch's code, and a probe
        handed straight to the sender is refused at its reservation."""
        probes = _probes_mod()
        self.probes_switch()
        w = self.routed([_urgent(1)], score=FAR)
        self.assertEqual(self.fresh(w).components["route"]["probes"],
                         [{"kind": "h0", "rung": "h0", "would_rung": "h0",
                           "boundary": None}])
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertEqual(self.due(w), [("h0", "h0", None)])
        out = probes.run()
        self.assertEqual((out["probed"], out["code"]), (1, ""))
        self.assert_one_call()
        self.assertEqual(self.requests[-1].kwargs["model"], self.model("h0"))
        self.probes_switch(False)
        v = self.routed([_urgent(2)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, v.pk)
        self.assert_one_call()
        out = probes.run()
        self.assert_no_call(code="probes_off", got=out["code"])
        self.assertEqual(out["probed"], 0)
        sent = probes.send(*[(x, p) for x, p in probes.due(timezone.now())
                             if x.pk == v.pk][0])
        self.assert_no_call(code="probes_off", got=sent["code"])
        self.assertFalse(sent["sent"])
        self.assertEqual(self.tickets(), {}, "nothing held")


class WhichProbesTests(_Probed):
    """B.11 with the route's probes (C1's probes[]): paper and demo only, h0
    on calm and eventful days, the boundary rung within 5 of 30, 55 or
    75, mapped by B.5, never the wake's own answering rung."""

    def test_a_paper_wake_on_a_calm_day_at_27_calls_h0_and_r1(self):
        """With Sonnet's PASS: the wake answers on r0 (the router OFF);
        its two probes, h0 and r1 across 30, each record one request on
        its rung's model, the wake's own stored blocks, no fallback."""
        _verdicts(sonnet="pass")
        self.probes_switch()
        w = self.routed([_urgent(1)], score=NEAR_30)
        self.assertEqual((w.day_class, w.band, w.components["rung"]),
                         ("calm", "routine", "r0"))
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        wake_req = self.requests[-1].kwargs

        def users(kwargs):
            return [m for m in kwargs["messages"] if m.get("role") == "user"]
        self.assertEqual(self.due(w), [("h0", "h0", None),
                                       ("boundary", "r1", 30)])
        for kind, rung in (("h0", "h0"), ("boundary", "r1")):
            with self.subTest(kind=kind):
                got = self.send(w, kind)
                self.assertTrue(got["sent"])
                self.assert_one_call()
                sent = self.requests[-1].kwargs
                self.assertEqual(sent["model"], self.model(rung))
                self.assertNotIn("fallbacks", sent)
                self.assertEqual(sent["system"], wake_req["system"],
                                 "S, as the wake sent it")
                self.assertEqual(users(sent), users(wake_req),
                                 "the wake's own stored blocks, both turns")
        self.assertEqual(self.due(w), [], "each probe once")

    def test_never_on_the_wakes_own_answering_rung(self):
        """With Sonnet's PASS and the router OFF, a paper wake at 33
        routes r1 (material) and lists the rung across 30, r0; but r0 is
        the rung that answered it (the router's switch OFF), so only h0 is
        due, and only h0 is sent."""
        _verdicts(sonnet="pass")
        self.probes_switch()
        w = self.routed([_urgent(1)], score=33.0)
        self.assertEqual((w.band, w.components["rung"]), ("material", "r0"))
        self.assertEqual([(p["kind"], p["rung"]) for p in
                          w.components["route"]["probes"]],
                         [("h0", "h0"), ("boundary", "r0")])
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertEqual(self.due(w), [("h0", "h0", None)])
        self.assertEqual(_probes_mod().run()["probed"], 1)
        self.assert_one_call()
        self.assertEqual(self.requests[-1].kwargs["model"], self.model("h0"))

    def test_the_same_wake_on_a_stormy_day_calls_neither(self):
        """The control: the calm day's wake at 27 and its two probes, each
        one request. On a stormy day the same wake lists no probe and
        none is sent."""
        _verdicts(sonnet="pass")
        self.probes_switch()
        w = self.routed([_urgent(1)], score=NEAR_30)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        for kind in ("h0", "boundary"):
            self.send(w, kind)
            self.assert_one_call()
        self.stormy()
        v = self.routed([_urgent(2)], score=NEAR_30)
        self.assertEqual(v.day_class, "stormy")
        self.assertEqual(v.components["route"]["probes"], [])
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, v.pk)
        self.assert_one_call()
        out = _probes_mod().run()
        self.assert_no_call()
        self.assertEqual((out["probed"], self.due(v)), (0, []))

    def test_a_real_money_wake_calls_none(self):
        """The control: a paper wake at 27 and its two probes. A real-money
        wake at 27 lists none and none is sent; a probe handed straight to
        the sender for it is refused (scheduler.is_real) before any
        ticket."""
        probes = _probes_mod()
        _verdicts(sonnet="pass")
        self.probes_switch()
        w = self.routed([_urgent(1)], score=NEAR_30)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        for kind in ("h0", "boundary"):
            self.send(w, kind)
            self.assert_one_call()
        v = self.routed([_urgent(2)], orc=self.live(), score=NEAR_30)
        self.assertEqual(v.components["route"]["probes"], [])
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, v.pk)
        self.assert_one_call()
        self.assertTrue(self.fresh(v).components["real"])
        out = probes.run()
        self.assert_no_call()
        self.assertEqual((out["probed"], self.due(v)), (0, []))
        sent = probes.send(self.fresh(v), {"kind": "h0", "rung": "h0",
                                           "would_rung": "h0",
                                           "boundary": None})
        self.assert_no_call(code="real_money", got=sent["code"])
        self.assertEqual(self.tickets(), {})

    def test_the_weathers_probes_bind(self):
        """B.8a: caps_for's `probes` binds (BINDING gains it): the control
        sends one h0 probe; with caps_for saying no probe for the day, a
        due-looking wake sends none."""
        from bot_program.orcs import weather
        self.assertEqual(weather.BINDING, ("wakes_per_day", "probes"))
        self.assertEqual(weather.caps_for("calm", False)["binding"],
                         ["wakes_per_day", "probes"])
        self.probes_switch()
        w = self.routed([_urgent(1)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertEqual(_probes_mod().run()["probed"], 1)
        self.assert_one_call()
        v = self.routed([_urgent(2)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, v.pk)
        self.assert_one_call()
        real = weather.caps_for
        with patch.object(weather, "caps_for", side_effect=lambda d, r: {
                **real(d, r), "probes": False}):
            out = _probes_mod().run()
            self.assertEqual(self.due(v), [])
        self.assert_no_call()
        self.assertEqual(out["probed"], 0)
        self.assertEqual(self.due(v), [("h0", "h0", None)],
                         "the day's own caps let it run again")


class TheProbeIsSeenNowhereTests(_Probed):
    """B.11, P22, P5's twin: a probe is stored only in OrcTierGrade and the
    ledger; never a plan, an intent, a note, a card line, a PS5 note or a
    journal entry, and never counted in the Orc's caps."""

    SENTINEL = "quartz zebra"

    def test_the_answer_reaches_no_slot_key_and_no_ps_block_of_the_next_wake(
            self):
        from bot_program.orcs import dossier_position, notes
        from bot_program.orcs.models import OrcDossierBlock, OrcJournal
        self.probes_switch()
        w = self.routed([_urgent(1)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.use_fake(fake_answer(answer(
            action="exit", facts_cited=["F987"],
            note=f"Probe {self.SENTINEL} exits.")))
        got = self.send(w, "h0")
        self.assert_one_call()
        self.assertEqual(got["grade"].probe["action"], "exit")
        nxt = self.routed([_urgent(2)], score=FAR)
        texts = list(OrcDossierBlock.objects.filter(
            hash__in=nxt.block_hashes).values_list("text", flat=True))
        self.assertTrue(any("Holding: the 4h structure intact." in t
                            for t in texts),
                        "the wake's own note reaches the next wake's PS5")
        for text in texts:
            self.assertNotIn(self.SENTINEL, text)
            self.assertNotIn("F987", text)
        self.orc.refresh_from_db()
        decisions = dossier_position.ps5_notes(self.orc)
        self.assertEqual(len(decisions), 1,
                         "PS5 lists the wake's own decision alone")
        self.assertIn("Holding: the 4h structure intact.", decisions[0])
        self.assertNotIn(self.SENTINEL, decisions[0])
        sl = notes.slot(self.orc, trade=self.orc.root_trade, minds=True)
        text = json.dumps(sl, ensure_ascii=False, default=str)
        self.assertIn("Holding: the 4h structure intact.", text,
                      "the wake's own note reaches the slot")
        self.assertNotIn(self.SENTINEL, text)
        self.assertNotEqual(self.orc.latest_note, f"Probe {self.SENTINEL} "
                                                  f"exits.")
        for e in OrcJournal.objects.filter(orc=self.orc):
            blob = e.headline + json.dumps(e.body, default=str)
            self.assertNotIn(self.SENTINEL, blob)

    def test_a_probe_writes_no_entry_plan_intent_note_card_line_or_counter(
            self):
        """What would write a refused intent, its refusal and a decision
        for a wake (an exit that names no reached level) writes nothing
        for a probe but its OrcTierGrade row and the ledger; the Orc's
        counters, plan, note, card and memory stay as they were (the
        behavioural guard runs too)."""
        from ai_agents.models import AgentTask

        from bot_program.orcs.models import (OrcIntent, OrcJournal,
                                             OrcTierGrade)
        self.probes_switch()
        w = self.routed([_urgent(1)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        before = self.counters_of(self.orc)
        rows = (OrcJournal.objects.count(), OrcIntent.objects.count(),
                OrcTierGrade.objects.count(), AgentTask.objects.count())
        self.use_fake(fake_answer(answer(action="exit", level_id="none")))
        got = self.send(w, "h0")
        self.assert_one_call()
        self.assertEqual(got["grade"].probe["action"], "exit")
        self.assertEqual((OrcJournal.objects.count(),
                          OrcIntent.objects.count(),
                          OrcTierGrade.objects.count(),
                          AgentTask.objects.count()),
                         (rows[0], rows[1], rows[2] + 1, rows[3] + 1))
        self.assertEqual(self.counters_of(self.orc), before)


class TheCapsTests(_Probed):
    """B.11, P1: probes are capped measurements: a user's boundary probes
    6 a UTC day, h0 40, counted in the tickets' book by (caller, kind,
    user) under the line lock, OrcSetting "probes_per_day" binding at
    once."""

    def test_the_7th_boundary_probe_of_a_user_is_refused_with_an_empty_call_list(
            self):
        """Five boundary probes reserved today: the 6th is sent (the
        control), the 7th is answered `day_cap` and nothing is sent."""
        from bot_program.orcs import scheduler
        from bot_program.orcs.models import OrcSetting
        _verdicts(sonnet="pass")
        self.probes_switch()
        self.seed_counts(boundary=5)
        a = self.routed([_urgent(1)], score=NEAR_30)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, a.pk)
        self.assert_one_call()
        self.assertTrue(self.send(a, "boundary")["sent"])
        self.assert_one_call()
        b = self.routed([_urgent(2)], score=NEAR_30)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, b.pk)
        self.assert_one_call()
        got = self.send(b, "boundary")
        self.assert_no_call(code="day_cap", got=got["code"])
        key, cap = scheduler.ticket_cap("probe", {"kind": "boundary",
                                                  "user": self.user.pk})
        self.assertEqual((key, cap), (f"probe:boundary:{self.user.pk}", 6))
        book = OrcSetting.get("minds_tickets")
        self.assertEqual(book["counts"][key], 6)
        self.assertEqual(self.tickets(), {})
        # h0 has its own count: b's h0 probe is still sent
        self.assertTrue(self.send(b, "h0")["sent"])
        self.assert_one_call()

    def test_h0s_cap_is_40_a_user_a_day_and_the_setting_binds_at_once(self):
        """At the reservation (no model asked): 39 h0 probes reserved
        today let a 40th through and refuse a 41st; another user's count
        is its own; OrcSetting "probes_per_day" moves the cap at once, 0
        refusing every probe of its kind."""
        from bot_program.orcs import scheduler
        from bot_program.orcs.constants import PROBES_PER_DAY
        from bot_program.orcs.models import OrcSetting
        self.probes_switch()
        self.assertEqual(PROBES_PER_DAY, {"boundary": 6, "h0": 40})
        self.seed_counts(h0=39)
        other = _user("o2b_probes_other")

        def reserve(item, user=None):
            return scheduler.reserve_ticket("probe", {
                "rung": "h0", "tokens": 1000, "item": item,
                "orc": self.orc.pk, "kind": "h0",
                "user": (user or self.user).pk, "would_rung": "h0",
                "ref": f"Orc:{self.orc.pk}:Wake:0:probe:h0"})
        fortieth = reserve("probe:t:a")
        self.assertTrue(fortieth["ok"])
        self.assertEqual(reserve("probe:t:b")["code"], "day_cap")
        self.assertTrue(reserve("probe:t:c", user=other)["ok"],
                        "a user a day")
        OrcSetting.objects.update_or_create(key="probes_per_day", defaults={
            "value": {"h0": 41}})
        self.assertEqual(scheduler.ticket_cap("probe", {
            "kind": "h0", "user": self.user.pk})[1], 41)
        self.assertTrue(reserve("probe:t:d")["ok"])
        OrcSetting.objects.update_or_create(key="probes_per_day", defaults={
            "value": {"h0": 0}})
        self.assertEqual(reserve("probe:t:e", user=other)["code"],
                         "day_cap")
        for key in list(self.tickets()):
            scheduler.settle_ticket(key, {"kind": "closed", "sent": False,
                                          "code": "", "usage": None})
        self.assertEqual(self.tickets(), {})
        for caller, req in (("probe", {"kind": "twin", "user": 1}),
                            ("probe", {"kind": "h0", "user": None}),
                            ("probe", {"kind": "", "user": 1})):
            with self.subTest(req=req), self.assertRaises(ValueError):
                scheduler.ticket_cap(caller, req)


class TheAllowanceTests(_Probed):
    """B.11, P6's twin: the probes' booked spend today (the ledger's
    ':probe:' rows), their tickets and holds in flight and this bound stay
    within OrcSetting "probes_usd_per_day" (15% of the line's cap by
    default, read at once; an explicit value is dollars); AND the line's
    booked spend, everything in flight and held and this bound stay within
    C - R; B.13 and A.18's floor too."""

    def test_an_r3_probe_late_in_the_utc_day_still_fits_its_own_allowance(
            self):
        """The line booked under 70% less the probe's bound (the day's
        late hours): the r3 probe of a paper wake at 52, Opus's PASS
        recorded, is sent, one request, its bound the primary's alone."""
        from bot_program.orcs import mind, mind_gateway
        _verdicts(sonnet="pass", opus="pass")
        self.probes_switch()
        w = self.routed([_urgent(1)], score=NEAR_55)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertIn(("boundary", "r3", 55), self.due(w))
        bound = mind_gateway.bound("r3", mind.ticket_tokens(w, "r3"))
        self.assertLessEqual(bound, ALLOWANCE)
        self.booked_to(0.7 * LINE - bound - 0.01)
        got = self.send(w, "boundary")
        self.assertTrue(got["sent"])
        self.assert_one_call()
        sent = self.requests[-1].kwargs
        self.assertEqual(sent["model"], self.model("r3"))
        self.assertNotIn("fallbacks", sent)
        asked = _gateway_asks(self)[-1].kwargs
        self.assertEqual(asked["tier"], "deep")
        self.assertAlmostEqual(asked["estimated_usd"], bound, places=6)

    def test_a_probe_past_probes_usd_per_day_is_refused_with_an_empty_call_list(
            self):
        """The control: an h0 probe inside the allowance. Then the probes'
        booked spend brought within half a bound of 15% of the line: the
        next probe is refused `probe_allowance`, nothing sent, nothing
        held. An explicit OrcSetting value is dollars, read at once: at
        $2.00 the same probe (its item waited) is sent."""
        from bot_program.orcs import mind, mind_gateway
        from bot_program.orcs.models import OrcSetting
        self.probes_switch()
        w = self.routed([_urgent(1)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertTrue(self.send(w, "h0")["sent"])
        self.assert_one_call()
        v = self.routed([_urgent(2)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, v.pk)
        self.assert_one_call()
        bound = mind_gateway.bound("h0", mind.ticket_tokens(v, "h0"))
        spent = mind.probes_spent()
        self.assertGreater(spent, 0, "the control's probe is booked")
        self.book_probes(ALLOWANCE - spent - bound / 2)
        self.assertAlmostEqual(mind.probes_spent(), ALLOWANCE - bound / 2,
                               places=5)
        got = self.send(v, "h0")
        self.assert_no_call(code="probe_allowance", got=got["code"])
        self.assertEqual(self.tickets(), {})
        OrcSetting.objects.update_or_create(key="probes_usd_per_day",
                                            defaults={"value": 2.0})
        self.assertTrue(self.send(v, "h0")["sent"])
        self.assert_one_call()

    def test_probes_stay_inside_c_minus_r_and_the_orcs_caps_never_move(self):
        """A probe is a ticket of the real non-urgent class: past C - R on
        the line's whole booked spend it is refused `triage`; a probe sent
        moves none of the Orc's day counters or dollars."""
        from bot_program.orcs import mind, mind_gateway
        self.probes_switch()
        w = self.routed([_urgent(1)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        before = self.counters_of(self.orc)
        self.assertTrue(self.send(w, "h0")["sent"])
        self.assert_one_call()
        self.assertEqual(self.counters_of(self.orc), before,
                         "the Orc's caps never move")
        v = self.routed([_urgent(2)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, v.pk)
        self.assert_one_call()
        bound = mind_gateway.bound("h0", mind.ticket_tokens(v, "h0"))
        self.booked_to(C_MINUS_R - bound / 2)
        self.assertLess(mind.probes_spent() + bound, ALLOWANCE,
                        "the allowance alone would let it through")
        got = self.send(v, "h0")
        self.assert_no_call(code="triage", got=got["code"])
        self.assertEqual(self.tickets(), {})

    def test_the_allowance_and_the_class_are_the_tables(self):
        from bot_program.orcs import scheduler
        from bot_program.orcs.constants import (DOSSIER_MAX_TOKENS,
                                                PROBES_USD_SHARE,
                                                TICKET_CLASS,
                                                TICKET_MAX_TOKENS)
        from bot_program.orcs.models import OrcSetting
        self.assertEqual(PROBES_USD_SHARE, 0.15)
        self.assertEqual(TICKET_CLASS["probe"], "real")
        self.assertEqual(TICKET_MAX_TOKENS["probe"], DOSSIER_MAX_TOKENS)
        self.assertAlmostEqual(scheduler.probes_usd_per_day(10.0), 1.50)
        self.assertAlmostEqual(scheduler.probes_usd_per_day(6.0), 0.90)
        OrcSetting.objects.update_or_create(key="probes_usd_per_day",
                                            defaults={"value": 0.5})
        self.assertAlmostEqual(scheduler.probes_usd_per_day(10.0), 0.5,
                               msg="an explicit value is dollars")
        OrcSetting.objects.update_or_create(key="probes_usd_per_day",
                                            defaults={"value": "x"})
        self.assertAlmostEqual(scheduler.probes_usd_per_day(10.0), 1.50,
                               msg="an unreadable value is the default")
        got = scheduler.reserve_ticket("probe", {
            "rung": "h0", "tokens": DOSSIER_MAX_TOKENS + 1, "kind": "h0",
            "user": self.user.pk, "item": "probe:t:big", "orc": self.orc.pk,
            "would_rung": "h0", "ref": f"Orc:{self.orc.pk}:Wake:0:probe:h0"})
        self.assertEqual((got["ok"], got["code"]), (False, "over_budget"))
        self.assertEqual(self.tickets(), {})


class TheRefusedProbeTests(_Probed):
    """B.11, B.14: the same validator, with no lock held; a refused probe
    is stored invalid; a probe names no fallback, its bound the primary's
    alone, billed on the Orcs line under agent orc and its own
    source_ref."""

    def test_a_refused_probe_is_stored_invalid(self):
        """An answer the validator refuses (V1), and a billed failure (an
        empty answer): each stored invalid, its cost booked."""
        self.probes_switch()
        w = self.routed([_urgent(1)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.use_fake(fake_answer(text="not an answer"))
        g = self.send(w, "h0")["grade"]
        self.assert_one_call()
        self.assertEqual({k: g.probe[k] for k in ("action", "level_id",
                                                   "valid", "rule")},
                         {"action": "", "level_id": "", "valid": False,
                          "rule": "V1"})
        self.assertEqual((g.routed["action"], g.routed["valid"]),
                         ("hold", True))
        self.assertEqual((g.agree_action, g.agree_level), (False, False))
        self.assertGreater(g.probe_cost_usd, 0)
        v = self.routed([_urgent(2)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, v.pk)
        self.assert_one_call()
        self.use_fake(fake_answer(text=""))
        g = self.send(v, "h0")["grade"]
        self.assert_one_call()
        self.assertEqual((g.probe["valid"], g.probe["rule"]), (False, "V1"))
        self.assertGreater(g.probe_cost_usd, 0, "a billed failure is booked")

    def test_a_probe_sends_no_fallback_and_holds_the_primarys_bound(self):
        """A paper r3 probe (Opus's PASS): no `fallbacks` sent; the line
        asked for the primary's bound alone (no fallback's), the ticket
        released once the ledger row is found, the item billed; the row on
        the Orcs line under agent orc, source_ref
        Orc:<pk>:Wake:<w>:probe:r3."""
        from ai_agents import spend
        from ai_agents.models import AgentTask

        from bot_program.orcs import mind, mind_gateway
        from bot_program.orcs.models import OrcSetting
        _verdicts(sonnet="pass", opus="pass")
        self.probes_switch()
        w = self.routed([_urgent(1)], score=NEAR_55)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        line_before = spend.spent_today("orcs")
        got = self.send(w, "boundary")
        self.assert_one_call()
        self.assertNotIn("fallbacks", self.requests[-1].kwargs)
        tokens = mind.ticket_tokens(w, "r3")
        asked = _gateway_asks(self)[-1].kwargs
        self.assertAlmostEqual(asked["estimated_usd"],
                               mind_gateway.bound("r3", tokens), places=6)
        self.assertLess(mind_gateway.bound("r3", tokens),
                        mind_gateway.bound("r3", tokens, fallback=True))
        ref = f"Orc:{self.orc.pk}:Wake:{w.pk}:probe:r3"
        task = AgentTask.objects.get(structured_output__source_ref=ref)
        self.assertEqual(task.agent, "orc")
        self.assertAlmostEqual(spend.spent_today("orcs") - line_before,
                               float(task.cost_usd), places=6)
        self.assertEqual(Decimal(str(got["grade"].probe_cost_usd)),
                         task.cost_usd)
        self.assertEqual(self.tickets(), {}, "released")
        items = OrcSetting.get("minds_tickets")["items"]
        self.assertEqual(items[f"probe:{w.pk}:boundary"]["state"], "billed")


class TheBlindProbeTests(_Probed):
    """B.11: the probe is blind to the routed answer, in its request (the
    wake's own stored blocks) and in its judging: the validator reads the
    Orc's plan as the wake's context read it, so the plan changes the
    routed answer made at its settle never refuse the probe (V2)."""

    def test_the_routed_answers_plan_changes_never_judge_the_probe(self):
        from bot_program.orcs import mind
        from bot_program.orcs.models import Orc, OrcWake
        now = timezone.now()
        claimed = now - timedelta(minutes=5)

        def changes(*minutes):
            return [{"at": (claimed + timedelta(minutes=m)).isoformat(),
                     "urgent": False} for m in minutes]
        w = OrcWake.objects.create(
            orc=self.orc, reasons=[W7], dedupe_key="blind", status="done",
            kind="material", started_at=claimed, finished_at=now,
            components={"as_of": claimed.isoformat(), "vctx": {
                "allowed": ["hold", "revise_plan"], "menu": [],
                "candidates": [], "events": {}, "plan_version": 1,
                "plan_at": None}})
        reply = {"kind": "answer", "stop_reason": "end_turn",
                 "text": json.dumps(answer(action="revise_plan"))}
        # two changes since the claim: the routed answer's own
        Orc.objects.filter(pk=self.orc.pk).update(plan_version=2,
                                                  plan_changes_24h=changes(
                                                      1, 2))
        side = mind.judge_probe(w, reply, now=now)
        self.assertEqual(side["action"], "revise_plan")
        self.assertNotEqual(side["rule"], "V2")
        # the same two changes before the claim: V2 refuses it, as it
        # would have refused the routed answer
        Orc.objects.filter(pk=self.orc.pk).update(plan_changes_24h=changes(
            -60, -30))
        side = mind.judge_probe(w, reply, now=now)
        self.assertEqual((side["action"], side["valid"], side["rule"]),
                         ("revise_plan", False, "V2"))


class WhenProbesRunTests(_Probed):
    """B.11 as built (decided here): from the worker, after its claims,
    with no lock held; last of all, only while no real-money wake waits;
    within 15 minutes of the routed answer, else dropped by code; one
    billed attempt per item, 'probe:<wake>:<kind>'."""

    def test_probes_go_last_while_a_real_money_wake_waits(self):
        probes = _probes_mod()
        self.probes_switch()
        w = self.routed([_urgent(1)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertEqual(probes.run()["probed"], 1)
        self.assert_one_call()
        v = self.routed([_urgent(2)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, v.pk)
        self.assert_one_call()
        waiting = self.routed([_urgent(3)], orc=self.live(), score=FAR)
        self.assertEqual(waiting.status, "pending")
        self.assertTrue(probes.real_waits())
        out = probes.run()
        self.assert_no_call(code="real_waits", got=out["code"])
        self.assertEqual(self.due(v), [("h0", "h0", None)], "it waits")

    def test_a_probe_past_its_freshness_window_is_dropped(self):
        from bot_program.orcs.constants import PROBE_FRESH_MIN
        from bot_program.orcs.models import OrcWake
        probes = _probes_mod()
        self.assertEqual(PROBE_FRESH_MIN, 15)
        self.probes_switch()
        w = self.routed([_urgent(1)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertEqual(probes.run()["probed"], 1)
        self.assert_one_call()
        v = self.routed([_urgent(2)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, v.pk)
        self.assert_one_call()
        OrcWake.objects.filter(pk=v.pk).update(
            finished_at=timezone.now() - timedelta(minutes=16))
        out = probes.run()
        self.assert_no_call()
        self.assertEqual((out["probed"], self.due(v)), (0, []))

    def test_one_billed_attempt_per_item(self):
        """A billed probe closes its item: nothing is due for it again, and
        a reservation of the same item is refused `item_closed`."""
        from bot_program.orcs import scheduler
        probes = _probes_mod()
        self.probes_switch()
        w = self.routed([_urgent(1)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertEqual(probes.item_key(w, "h0"), f"probe:{w.pk}:h0")
        self.assertTrue(self.send(w, "h0")["sent"])
        self.assert_one_call()
        out = probes.run()
        self.assert_no_call()
        self.assertEqual((out["probed"], self.due(w)), (0, []))
        again = scheduler.reserve_ticket("probe", {
            "rung": "h0", "tokens": 1000, "item": f"probe:{w.pk}:h0",
            "orc": self.orc.pk, "kind": "h0", "user": self.user.pk,
            "would_rung": "h0", "ref": f"Orc:{self.orc.pk}:Wake:{w.pk}:"
                                       f"probe:h0"})
        self.assertEqual((again["ok"], again["code"]), (False,
                                                        "item_closed"))

    def test_the_worker_sends_them_after_its_claims(self):
        """tasks.orc_think: the claims first (the wake read), then the
        probes in what is left of the run; its result names them, never a
        gate's health key."""
        from bot_program.orcs import tasks
        self.probes_switch()
        w = self.routed([_urgent(1)], score=FAR)
        self.assertEqual(w.status, "pending")
        self.use_fake(fake_answer(answer()))
        out = tasks.orc_think()
        self.assertEqual(out, {"status": "success", "thought": 1,
                               "by_code": 0, "probed": 1})
        self.assertEqual([r.kwargs["model"] for r in self.requests],
                         [self.model("r0"), self.model("h0")],
                         "the wake first, its probe last")
        for key in ("skipped", "parsed", "attempted"):
            self.assertNotIn(key, out)


class TheProbeRungsTests(_Probed):
    """B.15b, N4: CALLER_RUNGS["probe"] = h0, r0, r1, r3, r4, with r2
    admitted only as B.5's map of r3 and r4 (§1.0.9 "mapped"); any other
    rung raises before anything is sent."""

    def test_the_probes_rungs_and_r2_only_as_a_map(self):
        from bot_program.orcs import mind, mind_gateway
        self.assertEqual(mind_gateway.CALLER_RUNGS["probe"],
                         ("h0", "r0", "r1", "r3", "r4"))
        self.assertEqual(mind_gateway.MAPPED_RUNGS,
                         {"probe": {"r2": ("r3", "r4")}})
        for rung in ("h0", "r0", "r1", "r3", "r4"):
            mind_gateway.check_rung("probe", rung)
        for would in ("r3", "r4"):
            mind_gateway.check_rung("probe", "r2", would=would)
        for rung, would in (("r2", None), ("r2", "r1"), ("r2", "r2"),
                            ("r5", None), ("r5", "r4"), ("x9", None)):
            with self.subTest(rung=rung, would=would), \
                    self.assertRaises(ValueError):
                mind_gateway.check_rung("probe", rung, would=would)
        self.probes_switch()
        w = self.routed([_urgent(1)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        request = mind.build_request(w, "h0")
        ref = mind.source_ref(w, "h0", caller="probe")
        self.assertEqual(ref, f"Orc:{self.orc.pk}:Wake:{w.pk}:probe:h0")
        mind_gateway.call(caller="probe", rung_name="h0", request=request,
                          source_ref=ref, bound_usd=0.01)
        self.assert_one_call()
        for rung in ("r2", "r5"):
            with self.subTest(rung=rung), self.assertRaises(ValueError):
                mind_gateway.call(caller="probe", rung_name=rung,
                                  request=request, source_ref=ref,
                                  bound_usd=0.5)
        self.assert_no_call()

    def test_without_opuss_pass_an_r3_probe_answers_as_r2(self):
        """B.5: Sonnet's PASS only; a paper wake at 52 probes across 55:
        r3 by the table, answered as r2 (Opus at its one effort), on r2's
        model at medium effort; its row keeps the answering rung."""
        _verdicts(sonnet="pass")
        self.probes_switch()
        w = self.routed([_urgent(1)], score=NEAR_55)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        probe = self.probe_of(w, "boundary")
        self.assertEqual((probe["rung"], probe["would_rung"]), ("r2", "r3"))
        got = self.send(w, "boundary")
        self.assert_one_call()
        sent = self.requests[-1].kwargs
        self.assertEqual((sent["model"], sent["output_config"]["effort"]),
                         (self.model("r2"), "medium"))
        self.assertEqual(got["grade"].probe_rung, "r2")


# ── OrcTierGrade (B.12) ──────────────────────────────────────────────────

class TheTierGradeRowsTests(_Probed):
    """One row per probe pair: kind, boundary, world, the ANSWERING rungs
    with would_rung, each side {action, level_id, valid}, the agreement,
    both costs (AI spend, staff pages only) and the block index (blocks
    of SEAT_WINDOW pairs per (boundary, kind, world))."""

    def test_a_row_carries_kind_boundary_world_rungs_agreement_costs_block(
            self):
        from ai_agents.models import AgentTask

        from bot_program.orcs.models import OrcJournal
        _verdicts(sonnet="pass")
        self.probes_switch()
        w = self.routed([_urgent(1)], score=NEAR_30)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        w = self.fresh(w)
        decision = OrcJournal.objects.get(kind="decision", wake=w)
        for kind, rung, boundary in (("h0", "h0", None),
                                     ("boundary", "r1", 30)):
            with self.subTest(kind=kind):
                g = self.send(w, kind)["grade"]
                self.assert_one_call()
                self.assertEqual(
                    (g.wake_id, g.orc_id, g.kind, g.boundary, g.world,
                     g.routed_rung, g.probe_rung, g.would_rung),
                    (w.pk, self.orc.pk, kind, boundary, "paper", "r0", rung,
                     "r0"))
                self.assertEqual({k: g.routed[k] for k in (
                    "action", "level_id", "valid", "rule", "stop")},
                    {"action": "hold", "level_id": "none", "valid": True,
                     "rule": "", "stop": None})
                self.assertEqual((g.probe["action"], g.probe["level_id"],
                                  g.probe["valid"]), ("hold", "none", True))
                self.assertEqual((g.agree_action, g.agree_level),
                                 (True, True))
                self.assertEqual(g.routed_cost_usd, decision.cost_usd)
                task = AgentTask.objects.get(
                    structured_output__source_ref=f"Orc:{self.orc.pk}:Wake:"
                                                  f"{w.pk}:probe:{rung}")
                self.assertEqual(g.probe_cost_usd, task.cost_usd)
                self.assertEqual(g.block, 0)
                self.assertIsNone(g.fwd_at)
                self.assertEqual(g.routed["at"], w.finished_at.isoformat())

    def test_blocks_hold_twenty_pairs_per_boundary_kind_and_world(self):
        """Twenty paper h0 pairs make block 0 full: the next paper h0
        pair is block 1; a demo wake's pair starts its own world's block
        0 (paper and demo never pooled)."""
        from bot_program.orcs.models import OrcSetting, OrcTierGrade
        for n in range(20):
            OrcTierGrade.objects.create(orc=self.orc, kind="h0",
                                        boundary=None, world="paper",
                                        routed_rung="r0", probe_rung="h0",
                                        block=0)
        self.probes_switch()
        w = self.routed([_urgent(1)], score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        g = self.send(w, "h0")["grade"]
        self.assert_one_call()
        self.assertEqual((g.world, g.block), ("paper", 1))
        OrcSetting.objects.update_or_create(key="max_paper_orcs",
                                            defaults={"value": 100})
        demo_row = _row(self.cfg, paper=False, symbol=self.symbol,
                        meta={"broker_env": "paper"})
        demo = born(self, demo_row, at=self.orc.born_at)
        self.assertEqual(demo.seat.venue, "demo")
        v = self.routed([_urgent(2)], orc=demo, score=FAR)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, v.pk)
        self.assert_one_call()
        g = self.send(v, "h0")["grade"]
        self.assert_one_call()
        self.assertEqual((g.world, g.block), ("demo", 0))


class TheForwardGradeTests(_Probed):
    """B.12: each pair priced by pricing.py over the next final
    decision-frame bar after the LATER answer, from stored bars: exit at
    its first price (the bar's open), trim half there and half at the
    close, tighten at the close or its would-stop when the bar traded
    through it (the open when it gapped through), the rest at the close;
    an invalid answer as a hold. Every priced point less the one-way
    cost."""

    BAR = {"open": 101.0, "high": 103.0, "low": 99.0, "close": 102.0}

    def r(self, action, *, valid=True, stop=None, side="BUY", cf=0.0,
          bar=None):
        return _probes_mod().forward_r(
            {"action": action, "valid": valid, "stop": stop},
            bar or self.BAR, entry=100.0, rpu=2.0, direction=side, cf=cf)

    def test_each_action_is_priced_over_the_bar(self):
        cases = (("exit", {}, 0.5), ("trim", {}, 0.75),
                 ("tighten", {"stop": 99.5}, -0.25),
                 ("tighten", {"stop": 98.0}, 1.0),
                 ("tighten", {"stop": 101.5}, 0.5),
                 ("tighten", {"stop": None}, 1.0),
                 ("hold", {}, 1.0), ("revise_plan", {}, 1.0),
                 ("lock_waive", {}, 1.0), ("add", {}, 1.0),
                 ("exit", {"valid": False}, 1.0), ("", {"valid": False}, 1.0))
        for action, extra, want in cases:
            with self.subTest(action=action, **extra):
                self.assertAlmostEqual(self.r(action, **extra), want,
                                       places=9)
        # a short, mirrored: up is against it
        self.assertAlmostEqual(self.r("exit", side="SELL"), -0.5, places=9)
        self.assertAlmostEqual(self.r("hold", side="SELL"), -1.0, places=9)
        self.assertAlmostEqual(self.r("tighten", side="SELL", stop=102.5),
                               -1.25, places=9)
        # the one-way cost on the priced point: 1% round trip
        self.assertAlmostEqual(self.r("exit", cf=0.01),
                               (101.0 * (1 - 0.005) - 100.0) / 2.0, places=9)
        self.assertIsNone(_probes_mod().forward_r(
            {"action": "exit", "valid": True}, self.BAR, entry=None, rpu=2.0,
            direction="BUY", cf=0.0), "no entry: unmeasured")

    def test_grade_forward_prices_both_sides_after_the_later_answer(self):
        """Stored 4h bars after NOW: the later answer at NOW + 5h; the
        next bar opening after it (NOW + 8h) is graded once it is final,
        never before: neither while it forms nor while it is the newest
        snapshot the refresh may still rewrite. The routed exit at its
        open, the probe's hold at its close; fwd_at is that bar's end."""
        from bot_program.orcs.models import OrcTierGrade, OrcWake
        probes = _probes_mod()
        w = OrcWake.objects.create(
            orc=self.orc, reasons=[], dedupe_key="fwd1", status="done",
            kind="material", day_class="calm", finished_at=NOW,
            components={"vctx": {"decision_tf": "4h", "symbol": self.symbol,
                                 "side": "BUY", "entry": 100.0, "rpu": 2.0,
                                 "cf": 0.0}})
        g = OrcTierGrade.objects.create(
            orc=self.orc, wake=w, kind="h0", world="paper",
            routed_rung="r0", probe_rung="h0",
            routed={"action": "exit", "level_id": "none", "valid": True,
                    "at": (NOW + timedelta(hours=1)).isoformat()},
            probe={"action": "hold", "level_id": "none", "valid": True,
                   "at": (NOW + timedelta(hours=5)).isoformat()})
        _bars(self.symbol, "4h", [(100, 100.5, 99.5, 100.2),
                                  (100.2, 100.8, 99.9, 100.6),
                                  (101.0, 104.0, 100.5, 103.0)],
              start=NOW)
        self.assertEqual(probes.grade_forward(now=NOW + timedelta(hours=9)),
                         0, "the bar after the later answer still forms")
        self.assertEqual(probes.grade_forward(
            now=NOW + timedelta(hours=12, minutes=5)), 0,
            "ended, but a snapshot the refresh may rewrite: not final")
        g.refresh_from_db()
        self.assertIsNone(g.fwd_at)
        _bars(self.symbol, "4h", [(103.0, 103.5, 102.0, 102.5)],
              start=NOW + timedelta(hours=12))
        self.assertEqual(probes.grade_forward(now=NOW + timedelta(hours=13)),
                         1)
        g.refresh_from_db()
        self.assertAlmostEqual(g.fwd_routed_r, 0.5, places=9)
        self.assertAlmostEqual(g.fwd_probe_r, 1.5, places=9)
        self.assertEqual(g.fwd_at, NOW + timedelta(hours=12))
        self.assertEqual(probes.grade_forward(now=NOW + timedelta(hours=20)),
                         0, "graded once")
        # a pair whose wake keeps no entry is closed unmeasured
        bare = OrcWake.objects.create(orc=self.orc, reasons=[],
                                      dedupe_key="fwd2", status="done",
                                      kind="material", components={})
        h = OrcTierGrade.objects.create(orc=self.orc, wake=bare, kind="h0",
                                        world="paper", routed_rung="r0",
                                        probe_rung="h0")
        self.assertEqual(probes.grade_forward(now=NOW + timedelta(hours=20)),
                         1)
        h.refresh_from_db()
        self.assertIsNotNone(h.fwd_at)
        self.assertEqual((h.fwd_routed_r, h.fwd_probe_r), (None, None))

    def test_the_watchdogs_task_grades_after_its_pass_with_no_lock(self):
        """tasks.orc_minds_watch calls probes.grade_forward after
        scheduler.watch (T17 bars the scheduler from naming pricing), and
        a pass that graded pairs says so."""
        from bot_program.orcs import scheduler, tasks
        probes = _probes_mod()
        order = []
        real_watch = scheduler.watch

        def watch(**kw):
            order.append("watch")
            return real_watch(**kw)

        def grade(**kw):
            order.append("grade")
            return 2
        with patch.object(scheduler, "watch", watch), \
                patch.object(probes, "grade_forward", grade):
            out = tasks.orc_minds_watch()
        self.assertEqual(order, ["watch", "grade"])
        self.assertEqual(out["probes_graded"], 2)
        self.assertNotIn("idle", out)
        for key in ("skipped", "parsed", "attempted"):
            self.assertNotIn(key, out)
        with patch.object(probes, "grade_forward",
                          side_effect=RuntimeError("bars gone")):
            out = tasks.orc_minds_watch()
        self.assertNotIn("probes_graded", out, "fenced, logged")


# ── the surfaces (B.16a, B.16b) ──────────────────────────────────────────

class TheSurfacesTests(_Probed):

    def setUp(self):
        super().setUp()
        self.staff = get_user_model().objects.create_user(
            "o2b_probes_staff", password="x", is_staff=True)

    def card(self) -> str:
        from html import unescape
        self.client.force_login(self.staff)
        html = unescape(self.client.get("/ai-models/").content.decode())
        return html.split("The Orcs (read-only)", 1)[1].split(
            "Catalog</span>", 1)[0]

    @staticmethod
    def pairs(n, *, boundary, world="paper", orc, **kw):
        from bot_program.orcs.models import OrcTierGrade
        for i in range(n):
            OrcTierGrade.objects.create(
                orc=orc, kind="boundary" if boundary else "h0",
                boundary=boundary, world=world, routed_rung="r0",
                probe_rung="r1", block=i // 20, **kw)

    def test_two_completed_blocks_read_validated_on_ai_models(self):
        self.pairs(40, boundary=55, orc=self.orc)
        self.pairs(25, boundary=30, orc=self.orc)
        self.pairs(40, boundary=75, world="demo", orc=self.orc)
        text = " ".join(self.card().split())
        rows = {(int(b), w): (int(p), int(k), s) for b, w, p, k, s in
                re.findall(r'<tr data-boundary="(\d+)" data-world="(\w+)">'
                           r'.*?<td data-label="Pairs">(\d+)</td>\s*'
                           r'<td data-label="Completed blocks">(\d+)</td>\s*'
                           r'<td data-label="State">(\w+)</td>', text)}
        self.assertEqual(rows[(55, "paper")], (40, 2, "validated"))
        self.assertEqual(rows[(30, "paper")], (25, 1, "unvalidated"))
        self.assertEqual(rows[(75, "paper")], (0, 0, "unvalidated"))
        self.assertEqual(rows[(75, "demo")], (40, 2, "validated"),
                         "a world's blocks are its own")
        self.assertEqual(len(rows), 6)
        self.assertIn("shown only: no router reads it", text)

    def test_each_rung_shows_todays_probes_and_the_cards_sentence(self):
        from ai_agents.models import AgentTask
        yesterday = timezone.now() - timedelta(days=1, hours=1)
        for ref in ("Orc:1:Wake:2:probe:h0", "Orc:1:Wake:2:probe:r1",
                    "Orc:1:Wake:3:probe:r1", "Orc:1:Wake:3:r0",
                    "Orc:1:Wake:4:probe:r3"):
            AgentTask.objects.create(
                agent="orc", provider="claude", model="m",
                prompt_summary="x", cost_usd=Decimal("0.01"),
                structured_output={"source_ref": ref})
        old = AgentTask.objects.get(structured_output__source_ref=(
            "Orc:1:Wake:4:probe:r3"))
        AgentTask.objects.filter(pk=old.pk).update(created_at=yesterday)
        cells = {}
        for rung, calls, probes in re.findall(
                r'<tr data-rung="([a-z]\d)">.*?'
                r'<td data-label="Calls today">(\d+)</td>\s*'
                r'<td data-label="Would route today">\d+</td>\s*'
                r'<td data-label="Probes today">(\d+)</td>',
                self.card(), re.S):
            cells[rung] = (int(calls), int(probes))
        self.assertEqual(cells, {"h0": (1, 1), "r0": (1, 0), "r1": (2, 2),
                                 "r2": (0, 0), "r3": (0, 0), "r4": (0, 0),
                                 "r5": (0, 0)})
        text = " ".join(self.card().split())
        self.assertIn(SAID_OFF, text)
        self.assertNotIn(SAID_ON, text)
        self.probes_switch()
        text = " ".join(self.card().split())
        self.assertIn(SAID_ON, text)
        self.assertNotIn(SAID_OFF, text)

    def test_the_seats_ladder_table_is_staff_only(self):
        """/orcs/seats/ (staff): one row per (kind, boundary, world): the
        rungs, the pairs, the completed blocks, the valid shares, the
        agreement, the forward R per side over the graded pairs and the
        cost per pair of each side."""
        from django.urls import reverse

        from bot_program.orcs.models import OrcTierGrade
        self.client.force_login(self.user)
        r = self.client.get(reverse("orcs_seats"))
        self.assertEqual(r.status_code, 302, "staff only")
        now = timezone.now()
        for i in range(22):
            OrcTierGrade.objects.create(
                orc=self.orc, kind="boundary", boundary=30, world="paper",
                routed_rung="r0", probe_rung="r1", block=i // 20,
                routed={"action": "hold", "valid": True},
                probe={"action": "hold" if i % 2 else "exit",
                       "valid": i != 0},
                agree_action=bool(i % 2), agree_level=bool(i % 2),
                routed_cost_usd=Decimal("0.04"),
                probe_cost_usd=Decimal("0.08"),
                fwd_routed_r=0.5 if i < 10 else None,
                fwd_probe_r=0.7 if i < 10 else None,
                fwd_at=now if i < 10 else None)
        self.client.force_login(self.staff)
        html = self.client.get(reverse("orcs_seats")).content.decode()
        block = html.split('id="orc-ladder"', 1)[1].split("</table>", 1)[0]
        cells = re.findall(r'<td data-label="([^"]+)"[^>]*>([^<]*)</td>',
                           block)
        got = dict(cells)
        self.assertEqual(got["Kind"], "boundary")
        self.assertEqual(got["Boundary"], "30")
        self.assertEqual(got["World"], "paper")
        self.assertEqual(got["Rungs"], "r0 vs r1")
        self.assertEqual(got["Pairs"], "22")
        self.assertEqual(got["Completed blocks"], "1")
        self.assertEqual(got["State"], "unvalidated")
        self.assertEqual(got["Valid"], "100% / 95%")
        self.assertEqual(got["Agree"], "50% / 50%")
        self.assertEqual(got["Forward R"], "+0.50R / +0.70R (10)")
        self.assertEqual(got["Cost per pair"], "$0.0400 / $0.0800")
        self.assertIn("A block is 20 pairs", html)


class NoAccountFigureInAProbeRequestTests(_Probed):
    """K-B10 (N6): the walk over every request the probes send."""

    def test_no_account_figure_in_any_probe_request(self):
        _verdicts(sonnet="pass", opus="pass")
        self.probes_switch()
        for n, score, kinds in ((1, NEAR_30, ("h0", "boundary")),
                                (2, NEAR_55, ("boundary",))):
            w = self.routed([_urgent(n)], score=score)
            got = self.serve(script=fake_answer(answer()))
            self.assertEqual(got["wake"].pk, w.pk)
            self.assert_one_call()
            for kind in kinds:
                self.assertTrue(self.send(w, kind)["sent"])
                self.assert_one_call()
        self.assertEqual(len(self.requests), 5)
        self.assert_no_account_figure()


class TheProbesRunbookTests(MindTestCase):

    def test_the_runbook_says_how_probes_run_spend_and_stop(self):
        text = RUNBOOK.read_text(encoding="utf-8")
        head = "### The Orcs' probes (O2b)"
        self.assertIn(head, text)
        start = text.index(head)
        self.assertGreater(start, text.index("### The Orcs' router (O2b)"))
        section = " ".join(text[start:text.index("## Operating notes",
                                                 start)].split())
        for words in ("`orcs_probes`", NAME, "/ops/", "trading PIN",
                      "takes no PIN", "paper and demo", "real money",
                      "`probes_usd_per_day`", "15% of the line", "$1.50",
                      "in dollars", "`probes_per_day`", "6 boundary probes",
                      "40 h0 probes", "C − R", "no fallback", "15 minutes",
                      "/orcs/seats/", "/ai-models/", "validated",
                      "two completed blocks", "about $0.48 a day",
                      "nothing it decides is applied"):
            self.assertIn(words, section)
        self.assertNotIn("component on orcs_probes", text)


# ── PostgreSQL: the per-key day cap under the line lock ──────────────────

@skipUnless(PG, NOT_PG)
class TheProbesCapRaceTests(MindTransactionTestCase):
    """Two reservations racing for a user's 6th boundary probe of the day
    take the line lock in turn: one ticket, the other `day_cap`, neither
    thread raises."""

    def test_two_racing_reservations_get_one_ticket(self):
        from django.db import connection as conn

        from bot_program.orcs import scheduler
        from bot_program.orcs.models import OrcSetting
        _switch("aragorn")
        minds_on(self)
        _switch(KEY, True)
        user = _user("o2b_probes_race")
        cfg = _config(user)
        key, _cap = scheduler.ticket_cap("probe", {"kind": "boundary",
                                                   "user": user.pk})
        OrcSetting.objects.update_or_create(key="minds_tickets", defaults={
            "value": {"day": scheduler.utc_day(timezone.now()),
                      "counts": {key: 5}, "items": {}}})
        self.assertTrue(cfg.pk)
        go, results, errors = threading.Barrier(2), [], []

        def worker(n):
            try:
                go.wait(10)
                results.append(scheduler.reserve_ticket("probe", {
                    "rung": "r1", "tokens": 1000, "item": f"probe:race:{n}",
                    "orc": 0, "kind": "boundary", "user": user.pk,
                    "would_rung": "r1",
                    "ref": f"Orc:0:Wake:{n}:probe:r1"}))
            except Exception as e:  # noqa: BLE001 — told to the test
                errors.append(e)
            finally:
                conn.close()
        threads = [threading.Thread(target=worker, args=(n,))
                   for n in (1, 2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(errors, [])
        self.assertEqual(sorted((r["ok"], r["code"]) for r in results),
                         [(False, "day_cap"), (True, "")])
        book = OrcSetting.get("minds_tickets")
        self.assertEqual(book["counts"][key], 6)
