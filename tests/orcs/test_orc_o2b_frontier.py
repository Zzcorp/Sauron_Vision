"""O2b's FOURTH COMMIT, FABLE'S GATE AND ITS BLIND TWIN (the O2 spec B.4b,
B.8b, B.9, B.10, B.15c and N2 for `orcs_frontier`; §1.2.5 P35, P36-P39;
§1.2.6 "The family", "The twin", "The frontier quota", "Fallbacks" (the
twin sends none), the PIN and K-B10 on the r5 and twin requests; §1.2.7
"Fable stays at 0"; §4 Q12; 2026-11-06).

Behind a new switch, `orcs_frontier` (OFF on arrival, the trading PIN to
turn it on), a real-money extreme wake may be answered by r5 (Fable) beside
its r4 blind twin, when every clause of Fable's gate holds, read in order:
real money; the band extreme; a frontier quota left today (OrcSetting
frontier_per_day, 0 by default, less the user's r5 calls today); the switch
ON; the pair, priced at the dossier's size cap, under the wake's class's
ceiling and the money the Orcs may hold in flight; the Fable render within
its cap. The pair's bound (about $3.57) is above the $3.00 the Orcs may hold
in flight, so in O2 the gate cannot open: these tests raise that floor
inside the test to prove the pair, and keep it at $3.00 to prove it stays
shut. Nothing here turns a switch on for the operator.

- N2: the switch ships OFF beside the probes, exempt from "all on", in
  ORC_MIND_SWITCHES and never a live-money switch; only the PIN turns it on;
  its pair: ON, one r5 request beside one twin request for one wake; OFF,
  r4 answers with the switch's clause in the route and the journal; OFF at
  the send, neither goes and both reservations are released
- the twin: r5 never runs without r4; with the quota at 0 neither runs; the
  pair reserves after one money check of its bound, in one transaction; at
  the real $3.00 floor it is refused `inflight` for any dossier; the twin's
  answer is kept only as a `twin` pair
- the quota: a day row at 4 opens nothing (the router never reads it); the
  weather writes the setting's value; the quota left counts the user's r5
  calls today across classes, the ones in flight included
- the family: a Fable route renders x1.35 and falls to r4's family when
  over its cap, the clause journaled, block_hashes the final render's
- fallbacks: r5 sends the list form and its bound includes it; the twin
  sends none
- the gateway: the twin's rungs (r4, r2 as B.5's map); r5 and the twin are
  refused before the send without the pair's reservation
- the smoke: --rung r5 goes through the gate and is refused with its
  clause (P35), after its positive control
- K-B10 over the r5 and twin requests; the words (the RUNBOOK, /ai-models/,
  the weather's and the router's comments)

Run with:  python manage.py test tests.orcs.test_orc_o2b_frontier
"""
import inspect
import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import CommandError, call_command
from django.utils import timezone

from tests.orcs.helpers import _config, _row, _switch, _user, born
from tests.orcs.helpers_o2 import MindTestCase, fake_answer
from tests.orcs.test_orc_o2a_call import answer
from tests.orcs.test_orc_o2b_routed import (TEST_PIN, WRONG_PIN,
                                           _gateway_asks, _Routed, _row_of,
                                           _urgent)
from tests.orcs.test_orc_o2b_router import _verdicts

BASE = Path(settings.BASE_DIR)
RUNBOOK = BASE / "deploy" / "RUNBOOK.md"
KEY = "orcs_frontier"
NAME = "Orc Frontier (Fable and its blind twin in shadow)"
DESCRIPTION = ("Off (default). On, with the router on: a real-money extreme "
               "wake may be answered by r5 beside an r4 blind twin, under a "
               "daily quota (0 by default). In O2 the pair cannot run: its "
               "bound is above what the Orcs may hold in flight. Turning it "
               "on takes the PIN.")
#: A patched score far into the extreme band (above 75 + 5).
EXTREME = 90.0
#: The in-flight floor raised INSIDE a test only, so the pair can run.
RAISED_FLOOR = 10.0
#: Fable's gate in its own words (router.py), as the route keeps them.
NOT_REAL = "Fable answers real money only"
NOT_EXTREME = "the band is not extreme"
NO_QUOTA = "no frontier quota is left today"
FRONTIER_OFF = "the frontier switch (orcs_frontier) is off"
INFLIGHT = "the pair is above the money the Orcs may hold in flight"
OVER_CAP = "its Fable dossier is over the size cap"
#: The card's sentence on /ai-models/ while the gate cannot open.
SAID_CLOSED = "Fable (r5) stays at 0 through O2"


def _ref_rows():
    """The ledger's source_refs, oldest first."""
    from ai_agents.models import AgentTask
    return [str(r or "") for r in AgentTask.objects.order_by("id")
            .values_list("structured_output__source_ref", flat=True)]


# ── N2: the switch itself ────────────────────────────────────────────────

class TheFrontierSwitchShipsOffTests(MindTestCase):

    def setUp(self):
        from core.platform_control import seed_components
        cache.clear()
        seed_components()

    def test_it_is_seeded_off_beside_the_probes(self):
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
        self.assertEqual(keys.index(KEY), keys.index("orcs_probes") + 1)
        self.assertFalse(switches.frontier_on())
        # the twin's own switch, and r5's beside the wake's gates (B.15c)
        self.assertEqual(switches.caller_code("twin"), "frontier_off")
        self.assertEqual(switches.caller_code("wake", "r5"), "frontier_off")
        for caller, rung in (("wake", "r4"), ("wake", None), ("smoke", "r0")):
            with self.subTest(caller=caller, rung=rung):
                self.assertEqual(switches.caller_code(caller, rung), "")
        _switch(KEY, True)
        self.assertTrue(switches.frontier_on())
        self.assertEqual(switches.caller_code("twin"), "")
        self.assertEqual(switches.caller_code("wake", "r5"), "")
        # an unreadable switch reads OFF
        with patch("core.platform_control.is_component_enabled",
                   side_effect=RuntimeError("the table is gone")):
            self.assertFalse(switches.frontier_on())
            self.assertEqual(switches.caller_code("twin"), "frontier_off")

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


class OnlyThePinTurnsTheFrontierOnTests(MindTestCase):

    def setUp(self):
        from core.platform_control import seed_components
        from portfolio.trader_profile import get_or_create_profile
        cache.clear()
        seed_components()
        self.admin = get_user_model().objects.create_superuser(
            "o2b_frontier_admin", "o2b_frontier@example.test", "x")
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


# ── the pair (the render pass, the queue, the fake model) ────────────────

class _Frontier(_Routed):
    """_Routed's Orcs and gates (the four ON, the Orcs line at $6), the
    router's switch ON and both PASSes recorded, so the twin answers on r4
    itself (B.5); the frontier switch, its quota and the in-flight floor
    as each test sets them."""

    def setUp(self):
        super().setUp()
        _verdicts(sonnet="pass", opus="pass")
        self.router()

    def frontier(self, on=True):
        _switch(KEY, on)

    def quota(self, n):
        """OrcSetting "frontier_per_day" (B.8b), binding at once."""
        from bot_program.orcs.models import OrcSetting
        OrcSetting.objects.update_or_create(key="frontier_per_day",
                                            defaults={"value": n})

    def raise_floor(self, usd=RAISED_FLOOR):
        """ORC_LIVE_FLOOR_USD raised for this test only: the one way a pair
        of about $3.57 fits in flight (it ships at $3.00)."""
        from ai_agents import spend
        self.enterContext(patch.object(spend, "ORC_LIVE_FLOOR_USD", usd))

    def open_gate(self, quota=1):
        """Every clause B.9 reads before the render held: the floor raised
        in the test, a quota, the frontier switch ON."""
        self.raise_floor()
        self.quota(quota)
        self.frontier()

    def extreme(self, orc=None, *, n=1):
        """A real-money extreme wake, rendered and admitted."""
        return self.routed([_urgent(n)], orc=orc or self.live(),
                           score=EXTREME)

    @staticmethod
    def cap_bound(rung, *, fallback=False) -> float:
        from bot_program.orcs import mind_gateway
        from bot_program.orcs.constants import DOSSIER_MAX_TOKENS
        return float(mind_gateway.bound(rung, DOSSIER_MAX_TOKENS,
                                        fallback=fallback))

    def pair_bound(self, twin="r4") -> float:
        """r5's bound with its fallback and its twin's, both at the
        dossier's size cap, from the catalog."""
        return (self.cap_bound("r5", fallback=True)
                + self.cap_bound(twin))

    def answers(self, twin_note="Holding: the twin reads the 4h structure.",
                r5_note="Holding: r5 reads the 4h structure."):
        """The fake's two answers, in the order the pair sends them: the
        twin first, then r5."""
        return self.use_fake(fake_answer(answer(note=twin_note),
                                         model=self.model("r4")),
                             fake_answer(answer(note=r5_note),
                                         model=self.model("r5")))

    def assert_pair_call(self):
        """The pair's own positive control: exactly two requests since the
        last control, the twin's on r4's model, then r5's on Fable's."""
        fake = self.fake
        sent = fake.requests[fake.mark:]
        self.assertEqual([r.kwargs["model"] for r in sent],
                         [self.model("r4"), self.model("r5")],
                         "the twin, then r5: two requests")
        fake.mark = len(fake.requests)
        self._one_call_proven = True
        return sent

    def models(self) -> list:
        return [r.kwargs["model"] for r in self.requests]


class TheSwitchPairTests(_Frontier):
    """N2, N7: the frontier switch's pair (B.9's fourth clause), and
    frictionless off at the send (B.15c)."""

    def test_on_r5_answers_beside_its_twin_off_r4_answers_with_the_clause(
            self):
        """ON, the floor raised in the test and a quota of 2: a real-money
        extreme wake records exactly one r5 request and one twin request,
        both for that wake (the ledger's source_refs). OFF: the next
        real-money extreme wake routes r4, the switch's clause in its route
        and its journal entry, and its one request is on r4's model."""
        from bot_program.orcs.models import OrcJournal
        self.open_gate(quota=2)
        live = self.live()
        w = self.extreme(live)
        route = self.assert_route(w)
        self.assertEqual((route["would_rung"], route["rung"], route["twin"],
                          route["fable"]), ("r5", "r5", True, ""))
        self.assertIn("extreme, every clause of the Fable gate holds: r5",
                      route["why"])
        self.assertEqual((w.status, w.components["rung"],
                          w.components["family"]), ("pending", "r5", "fable"))
        self.answers()
        got = self.serve()
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_pair_call()
        self.assertEqual(_ref_rows(), [f"Orc:{live.pk}:Wake:{w.pk}:twin:r4",
                                       f"Orc:{live.pk}:Wake:{w.pk}:r5"])
        w = self.fresh(w)
        self.assertEqual((w.status, w.model, w.components["rung"]),
                         ("done", self.model("r5"), "r5"))
        self.frontier(False)
        v = self.extreme(live, n=2)
        route = self.assert_route(v)
        self.assertEqual((route["would_rung"], route["rung"], route["twin"],
                          route["fable"]), ("r4", "r4", False, FRONTIER_OFF))
        self.assertIn(f"extreme: r4, {FRONTIER_OFF}", route["why"])
        entry = OrcJournal.objects.get(kind="wake", wake=v)
        self.assertEqual(entry.body["route"]["fable"], FRONTIER_OFF)
        got = self.serve(script=fake_answer(answer(), model=self.model("r4")))
        self.assertEqual(got["wake"].pk, v.pk)
        self.assert_one_call()
        self.assertEqual(self.requests[-1].kwargs["model"], self.model("r4"))
        self.assertEqual(self.models().count(self.model("r5")), 1)

    def test_switched_off_at_the_send_neither_goes_both_are_released(self):
        """Frictionless off: the gateway reads the frontier switch again at
        each of the pair's sends. The positive control: with it OFF from
        the start a real-money extreme wake is answered on r4, one request.
        Then a wake claimed with its pair reserved while it was ON, read
        once it is OFF: the twin's call is closed (frontier_off), so r5 is
        not sent either; the wake is answered by code and both
        reservations are released."""
        from bot_program.orcs import mind, scheduler
        self.raise_floor()
        self.quota(1)
        live = self.live()
        w = self.extreme(live)
        self.assertEqual(w.components["route"]["fable"], FRONTIER_OFF)
        got = self.serve(script=fake_answer(answer(), model=self.model("r4")))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.frontier()
        v = self.extreme(live, n=2)
        self.assertEqual(v.components["rung"], "r5")
        claimed = scheduler.claim()["wake"]
        self.assertEqual(claimed.pk, v.pk)
        self.assertEqual(len(self.tickets()), 1, "the twin's ticket")
        self.frontier(False)
        out = mind.think(claimed)
        v = self.fresh(v)
        self.assert_no_call(code="frontier_off", got=v.skipped_reason)
        self.assertEqual((out["status"], v.status, v.est_usd),
                         ("skipped", "skipped", Decimal(0)))
        self.assertEqual(self.tickets(), {}, "the twin's ticket released")
        self.assertNotIn(f"w{v.pk}", self.holds())

    def test_switched_off_before_the_claim_r4_reads_the_fable_dossier(self):
        """The claim reads the frontier switch again: a wake admitted on r5
        while it was ON and claimed once it is OFF is answered on r4 from
        its stored Fable dossier, r4's bound and fallback reserved, no
        twin held, the switch's clause kept beside the rung."""
        from bot_program.orcs import mind_gateway
        self.open_gate()
        w = self.extreme()
        self.assertEqual((w.components["rung"], w.components["family"]),
                         ("r5", "fable"))
        self.frontier(False)
        got = self.serve(script=fake_answer(answer(), model=self.model("r4")))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertEqual(self.requests[-1].kwargs["model"], self.model("r4"))
        self.assertIn("fallbacks", self.requests[-1].kwargs)
        w = self.fresh(w)
        self.assertEqual((w.status, w.components["rung"],
                          w.components["frontier"]), ("done", "r4",
                                                      FRONTIER_OFF))
        self.assertNotIn("twin", w.components)
        self.assertAlmostEqual(w.components["bound"], mind_gateway.bound(
            "r4", w.components["tokens"], fallback=True), places=6)
        self.assertEqual(self.tickets(), {})


class TheTwinTests(_Frontier):
    """B.9, B.10: r5 only beside its r4 blind twin, the pair reserved
    together at the claim; its bound priced at the dossier's size cap."""

    def test_r5_never_runs_without_r4(self):
        """Every request on Fable's model has its twin's request before it,
        for the same wake, on the ledger and at the fake; and the gateway
        refuses, before anything is sent, r5 to a wake call that carries
        no pass and the twin to a call whose ticket is not held."""
        from bot_program.orcs import mind, mind_gateway
        self.open_gate(quota=2)
        for n in (1, 2):
            w = self.extreme(self.live(), n=n)
            self.answers()
            got = self.serve()
            self.assertEqual(got["wake"].pk, w.pk)
            self.assert_pair_call()
        refs = _ref_rows()
        r5 = [i for i, ref in enumerate(refs) if ref.endswith(":r5")]
        self.assertEqual(len(r5), 2)
        for i in r5:
            head = refs[i].rsplit(":", 1)[0]
            self.assertEqual(refs[i - 1], f"{head}:twin:r4",
                             "the twin of the same wake, just before")
        self.assertEqual(self.models(), [self.model("r4"), self.model("r5")]
                         * 2)
        # no pass, no Fable; no held ticket, no twin
        w = self.extreme(self.live(), n=3)
        request = mind.build_request(w, "r5")
        for kwargs in ({"caller": "wake", "rung_name": "r5"},
                       {"caller": "wake", "rung_name": "r5",
                        "frontier_pass": "t0000000000000000"},
                       {"caller": "twin", "rung_name": "r4",
                        "exclude_key": "t0000000000000000"}):
            with self.subTest(**kwargs), self.assertRaises(ValueError):
                mind_gateway.call(request=request, bound_usd=3.0,
                                  source_ref=mind.source_ref(w, "r5"),
                                  **kwargs)
        self.assertEqual(len(self.requests), 4, "nothing more was sent")

    def test_with_the_quota_at_0_neither_runs(self):
        """B.8b, B.10: the quota ships at 0 (no setting): a real-money
        extreme wake routes r4 (no frontier quota is left today) and is
        answered on r4's model alone, one request; with a quota of 1 the
        next one is answered by the pair; set back to 0, the next routes
        r4 again and neither Fable nor its twin is sent."""
        from bot_program.orcs import weather
        self.raise_floor()
        self.frontier()
        self.assertEqual(weather.frontier_per_day(), 0)
        live = self.live()
        w = self.extreme(live)
        self.assertEqual((w.components["route"]["fable"],
                          w.components["rung"]), (NO_QUOTA, "r4"))
        self.assertIn(f"extreme: r4, {NO_QUOTA}", w.components["route"]["why"])
        got = self.serve(script=fake_answer(answer(), model=self.model("r4")))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.quota(1)
        v = self.extreme(live, n=2)
        self.assertEqual(v.components["rung"], "r5")
        self.answers()
        self.assertEqual(self.serve()["wake"].pk, v.pk)
        self.assert_pair_call()
        self.quota(0)
        u = self.extreme(live, n=3)
        self.assertEqual((u.components["route"]["fable"],
                          u.components["rung"]), (NO_QUOTA, "r4"))
        got = self.serve(script=fake_answer(answer(), model=self.model("r4")))
        self.assertEqual(got["wake"].pk, u.pk)
        self.assert_one_call()
        self.assertEqual(self.models().count(self.model("r5")), 1)
        self.assertEqual([r for r in _ref_rows() if ":twin:" in r],
                         [f"Orc:{live.pk}:Wake:{v.pk}:twin:r4"])

    def test_the_claim_counts_the_quota_again_under_the_line_lock(self):
        """Two real-money extreme wakes of one user rendered before either
        was claimed both route r5 on a quota of 1; the claims take the
        line lock in turn, so the first is answered by the pair and the
        second, the quota spent, on r4 alone, the quota's clause kept."""
        self.open_gate()
        a = self.extreme(self.live(), n=1)
        b = self.extreme(self.live(), n=2)
        self.assertEqual((a.components["rung"], b.components["rung"]),
                         ("r5", "r5"))
        self.answers()
        self.assertEqual(self.serve()["wake"].pk, a.pk)
        self.assert_pair_call()
        got = self.serve(script=fake_answer(answer(), model=self.model("r4")))
        self.assertEqual(got["wake"].pk, b.pk)
        self.assert_one_call()
        self.assertEqual(self.requests[-1].kwargs["model"], self.model("r4"))
        b = self.fresh(b)
        self.assertEqual((b.status, b.components["rung"],
                          b.components["frontier"]), ("done", "r4", NO_QUOTA))
        self.assertEqual(self.models().count(self.model("r5")), 1)

    def test_the_pair_reserves_after_one_money_check_of_its_bound(self):
        """With the floor raised: the r5 wake's claim weighs the money once,
        for the whole pair (r5's bound with its fallback and its twin's,
        priced at the dossier's size cap from the catalog: about $3.57),
        then reserves both in its one transaction under the line lock: the
        wake's est_usd is r5's bound, the twin's ticket (caller twin) holds
        its own. A failure inside that transaction leaves neither."""
        from bot_program.orcs import journal, scheduler
        self.open_gate()
        w = self.extreme()
        pair = self.pair_bound()
        self.assertAlmostEqual(pair, 3.56, delta=0.02, msg="about $3.56")
        self.assertAlmostEqual(w.components["pair"], pair, places=6)
        # a failure at the claim's last write rolls the pair back whole
        with patch.object(journal, "remember",
                          side_effect=RuntimeError("the claim fails late")), \
                self.assertRaises(RuntimeError):
            scheduler.claim()
        self.assertEqual(self.fresh(w).status, "pending")
        self.assertEqual(self.tickets(), {})
        weighed = []
        real_code = scheduler.class_money_code

        def spy(klass, **kw):
            weighed.append((klass, kw["bound"], kw.get("tier")))
            return real_code(klass, **kw)
        with patch.object(scheduler, "class_money_code", spy):
            claimed = scheduler.claim()["wake"]
        self.assertEqual(claimed.pk, w.pk)
        self.assertEqual(len(weighed), 1, "one money check of the pair")
        self.assertEqual(weighed[0][0], "real_urgent")
        self.assertAlmostEqual(weighed[0][1], pair, places=6)
        self.assertEqual(weighed[0][2], "frontier")
        line = [c for c in self.spend_calls if c.gateway is None][-1]
        self.assertAlmostEqual(line.kwargs["estimated_usd"], pair, places=6)
        running = self.fresh(w)
        self.assertEqual((running.status, running.components["rung"]),
                         ("running", "r5"))
        self.assertEqual(running.est_usd, Decimal(str(round(
            self.cap_bound("r5", fallback=True), 6))))
        tickets = self.tickets()
        self.assertEqual(len(tickets), 1)
        key, ticket = next(iter(tickets.items()))
        self.assertEqual((ticket["caller"], ticket["rung"], ticket["pair"]),
                         ("twin", "r4", w.pk))
        self.assertAlmostEqual(ticket["usd"], self.cap_bound("r4"), places=6)
        self.assertNotIn("wake", ticket, "r5's own ask never drops it")
        self.assertEqual(running.components["twin"]["key"], key)
        self.assertEqual(running.components["twin"]["ref"],
                         f"Orc:{w.orc_id}:Wake:{w.pk}:twin:r4")

    def test_at_the_real_floor_the_pair_is_refused_inflight(self):
        """§4 Q12: at the $3.00 the Orcs may hold in flight (as it ships),
        with a quota of 1 and both switches ON, a real-money extreme wake
        routes r4 with the `inflight` clause and is answered on r4's model
        alone. Priced at the dossier's size cap the pair passes $3.00 for
        ANY dossier, an estimate of 0 tokens included, with its twin on r4
        or, before Opus's PASS, on r2."""
        from bot_program.orcs import mind, mind_gateway, scheduler
        self.quota(1)
        self.frontier()
        self.assertEqual(mind_gateway.live_floor(), 3.0)
        w = self.extreme()
        self.assertEqual((w.components["route"]["fable"],
                          w.components["rung"]), (INFLIGHT, "r4"))
        self.assertIn(f"extreme: r4, {INFLIGHT}", w.components["route"]["why"])
        got = self.serve(script=fake_answer(answer(), model=self.model("r4")))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertNotIn(self.model("r5"), self.models())
        self.assertEqual(scheduler.fable_money(w.reasons), "inflight")
        empty = self.fresh(w)
        empty.components = {**empty.components, "tokens": 0}
        self.assertAlmostEqual(mind.price(empty, "r5", real=True)["weigh"],
                               self.pair_bound(), places=6)
        self.assertGreater(mind.price(empty, "r5", real=True)["weigh"], 3.0)
        self.assertLess(mind_gateway.bound("r5", 0, fallback=True)
                        + mind_gateway.bound("r4", 0), 3.0,
                        "on its own estimate a tiny dossier would fit")
        _verdicts(sonnet="pass")
        self.assertEqual(mind.pair_price()["twin"]["rung"], "r2")
        self.assertAlmostEqual(mind.pair_price()["weigh"],
                               self.pair_bound("r2"), places=6)
        self.assertGreater(mind.pair_price()["weigh"], 3.0)
        self.assertEqual(scheduler.fable_money(w.reasons), "inflight")

    def test_the_twin_is_kept_only_as_a_twin_pair(self):
        """B.10: r5's answer is the Orc's; the twin's is judged by the same
        validator, blind, and kept only as an OrcTierGrade `twin` pair, in
        real money's world: never a note, a plan, an intent, a journal
        line or a card line."""
        from bot_program.orcs.models import (Orc, OrcIntent, OrcJournal,
                                             OrcTierGrade)
        self.open_gate()
        live = self.live()
        w = self.extreme(live)
        self.answers(twin_note="TWINWORDS: the twin holds too.")
        self.assertEqual(self.serve()["wake"].pk, w.pk)
        self.assert_pair_call()
        live = Orc.objects.get(pk=live.pk)
        self.assertEqual(live.latest_note, "Holding: r5 reads the 4h "
                                           "structure.")
        text = json.dumps([list(OrcJournal.objects.filter(orc=live).values(
            "headline", "body"))], default=str) + json.dumps(
            live.card, default=str) + json.dumps(live.plan, default=str)
        self.assertNotIn("TWINWORDS", text)
        self.assertFalse(OrcIntent.objects.filter(wake=w).exists())
        pair = OrcTierGrade.objects.get(wake=w)
        self.assertEqual((pair.kind, pair.boundary, pair.world,
                          pair.routed_rung, pair.probe_rung,
                          pair.would_rung), ("twin", None, "live", "r5",
                                             "r4", "r5"))
        self.assertEqual((pair.routed["action"], pair.routed["valid"],
                          pair.probe["action"], pair.probe["valid"]),
                         ("hold", True, "hold", True))
        self.assertTrue(pair.agree_action)
        self.assertGreater(pair.probe_cost_usd, 0)
        self.assertGreater(pair.routed_cost_usd, 0)
        self.assertNotIn("TWINWORDS", json.dumps(
            [pair.routed, pair.probe], default=str))


class TheFrontierQuotaTests(_Frontier):
    """B.8b: OrcSetting frontier_per_day (0 by default), per user across
    every class, less the user's r5 calls today; the router never reads
    OrcDayBaseline.frontier_quota, which the weather writes from the
    setting."""

    def test_a_day_row_at_4_opens_nothing_and_the_weather_writes_the_setting(
            self):
        """The floor raised, both switches ON, the setting at its default
        0 and the day row at 4: a real-money extreme wake routes r4 (no
        frontier quota is left today) and its one request is on r4's model,
        never Fable's. The weather writes the setting's value there: 0, and
        2 once the setting says 2."""
        from bot_program.orcs import weather
        from bot_program.orcs.models import OrcDayBaseline
        from bot_program.orcs.sessions import trading_day
        self.raise_floor()
        self.frontier()
        live = self.live()
        day = weather.current(self.user, live.asset_class, timezone.now())
        self.assertEqual(day.frontier_quota, 0, "the setting's 0")
        self.assertNotIn("frontier_quota", day.caps)
        OrcDayBaseline.objects.filter(pk=day.pk).update(frontier_quota=4)
        w = self.extreme(live)
        self.assertEqual(OrcDayBaseline.objects.get(pk=day.pk).frontier_quota,
                         4)
        self.assertEqual((w.components["route"]["fable"],
                          w.components["rung"]), (NO_QUOTA, "r4"))
        got = self.serve(script=fake_answer(answer(), model=self.model("r4")))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertNotIn(self.model("r5"), self.models())
        # the weather writes the setting's value, on a new day row and on
        # an upward re-run alike
        self.quota(2)
        other = _user("o2b_frontier_weather")
        fresh = weather.current(other, "forex", timezone.now())
        self.assertEqual(fresh.frontier_quota, 2)
        OrcDayBaseline.objects.filter(pk=day.pk).update(frontier_quota=4)
        inputs = weather.market_inputs(self.user, live.asset_class,
                                       timezone.now())
        inputs.update(posture_level="crisis", posture_fresh=True)
        up = weather.current(self.user, live.asset_class, timezone.now(),
                             inputs=inputs)
        self.assertEqual((up.pk, up.day_class), (day.pk, "stormy"))
        self.assertEqual(up.frontier_quota, 2)
        self.assertEqual(up.trading_day, trading_day(timezone.now()))

    def test_the_quota_left_counts_the_users_r5_calls_today(self):
        """mind.frontier_left: the setting less the user's r5 calls today,
        across every class: the Orcs line's ledger rows by the source_ref's
        rung and the user's r5 wakes in flight; never another user's, a
        call of yesterday, a twin's or a probe's."""
        from ai_agents.models import AgentTask

        from bot_program.orcs import mind
        from bot_program.orcs.models import OrcSetting, OrcWake
        OrcSetting.objects.update_or_create(key="max_paper_orcs",
                                            defaults={"value": 100})
        live = self.live()
        forex = born(self, _row(self.cfg, cls="forex", symbol="EURUSD"),
                     at=self.orc.born_at)
        self.assertNotEqual(forex.asset_class, live.asset_class)
        stranger = _user("o2b_frontier_stranger")
        theirs = born(self, _row(_config(stranger), symbol=self.symbol),
                      at=self.orc.born_at)
        self.assertEqual(mind.frontier_left(self.user.pk), 0, "it ships at 0")
        OrcSetting.objects.update_or_create(key="frontier_per_day",
                                            defaults={"value": 5})
        self.assertEqual(mind.frontier_left(self.user.pk), 5)
        yesterday = timezone.now() - timedelta(days=1, hours=1)
        for ref in (f"Orc:{live.pk}:Wake:900:r5",
                    f"Orc:{forex.pk}:Wake:901:r5",
                    f"Orc:{live.pk}:Wake:902:twin:r4",
                    f"Orc:{live.pk}:Wake:903:probe:r1",
                    f"Orc:{live.pk}:Wake:904:r4",
                    f"Orc:{theirs.pk}:Wake:905:r5",
                    f"Orc:{live.pk}:Wake:906:r5"):
            AgentTask.objects.create(
                agent="orc", provider="claude", model="m",
                prompt_summary="x", cost_usd=Decimal("0.01"),
                structured_output={"source_ref": ref})
        old = AgentTask.objects.get(
            structured_output__source_ref=f"Orc:{live.pk}:Wake:906:r5")
        AgentTask.objects.filter(pk=old.pk).update(created_at=yesterday)
        self.assertEqual(mind.frontier_left(self.user.pk), 3)
        OrcWake.objects.create(orc=live, reasons=[], dedupe_key="r5run",
                               kind="material", status="running",
                               est_usd=Decimal("2.69"),
                               started_at=timezone.now(),
                               components={"rung": "r5"})
        self.assertEqual(mind.frontier_left(self.user.pk), 2,
                         "a call in flight is counted")
        self.assertEqual(mind.frontier_left(stranger.pk), 4)
        OrcSetting.objects.update_or_create(key="frontier_per_day",
                                            defaults={"value": 1})
        self.assertEqual(mind.frontier_left(self.user.pk), 0, "never below 0")


class TheFamilyTests(_Frontier):
    """B.4b: a Fable route renders for the fable family (x1.35); only an
    over-budget Fable render renders again, for r4's family, the clause
    journaled; block_hashes holds the final render."""

    def renders(self, *, over=False):
        """A spy on dossier.render: (family asked, tokens, hashes) of each
        call; `over` reads the Fable render over its cap."""
        from bot_program.orcs import dossier
        seen, real = [], dossier.render

        def render(*a, **k):
            out = real(*a, **k)
            if over and k.get("model") == "fable":
                out = {**out, "over_budget": True}
            seen.append((k.get("model"), out["tokens"], list(out["hashes"])))
            return out
        return seen, patch.object(dossier, "render", render)

    def test_a_fable_route_renders_x135_and_falls_to_r4s_family_over_cap(
            self):
        from bot_program.orcs.constants import S_TOKENS_RESERVE
        from bot_program.orcs.models import OrcJournal
        self.open_gate()
        live = self.live()
        seen, spy = self.renders(over=True)
        with spy:
            w = self.extreme(live)
        self.assertEqual([s[0] for s in seen], ["fable", "opus"])
        ratio = (seen[0][1] - S_TOKENS_RESERVE) / (seen[1][1]
                                                   - S_TOKENS_RESERVE)
        self.assertAlmostEqual(ratio, 1.35, delta=0.02,
                               msg="the Fable render at the 1.35 factor")
        route = self.assert_route(w)
        self.assertEqual((route["would_rung"], route["rung"], route["twin"],
                          route["fable"]), ("r4", "r4", False, OVER_CAP))
        self.assertIn(f"extreme: r4, {OVER_CAP}", route["why"])
        entry = OrcJournal.objects.get(kind="wake", wake=w)
        self.assertEqual(entry.body["route"]["fable"], OVER_CAP)
        self.assertEqual(w.block_hashes, seen[1][2], "the final render's")
        self.assertEqual((w.components["tokens"], w.components["family"],
                          w.components["rung"], w.status),
                         (seen[1][1], "opus", "r4", "pending"))
        self.assertEqual(entry.block_hashes, seen[1][2])

    def test_a_fable_render_within_its_cap_is_r5s_one_render(self):
        self.open_gate()
        seen, spy = self.renders()
        with spy:
            w = self.extreme()
        self.assertEqual([s[0] for s in seen], ["fable"], "one render")
        self.assertEqual((w.block_hashes, w.components["tokens"],
                          w.components["family"], w.components["rung"]),
                         (seen[0][2], seen[0][1], "fable", "r5"))
        self.assertIs(w.components["over_budget"], False)


class TheFallbackTests(_Frontier):
    """B.14: r5, real money's, sends the list form and its bound includes
    the fallback's own; the twin, a probe, sends none."""

    def test_r5_sends_the_list_form_and_the_twin_none(self):
        from ai_agents.catalog import ORC_FALLBACK_V1
        self.open_gate()
        w = self.extreme()
        self.answers()
        self.assertEqual(self.serve()["wake"].pk, w.pk)
        twin, r5 = self.assert_pair_call()
        self.assertEqual(r5.kwargs["fallbacks"],
                         [{"model": ORC_FALLBACK_V1, "max_tokens": 8000}])
        self.assertNotIn("fallbacks", twin.kwargs)
        self.assertLess(self.cap_bound("r5"), self.cap_bound("r5",
                                                             fallback=True))
        asks = [c.kwargs for c in _gateway_asks(self)][-2:]
        self.assertEqual([a["tier"] for a in asks], ["deep", "frontier"])
        for ask in asks:
            self.assertAlmostEqual(ask["estimated_usd"], self.pair_bound(),
                                   places=6, msg="each send asks the line "
                                                 "for the whole pair")


class TheTwinCallerTests(_Frontier):
    """B.15c and §1.0.9's twin row: CALLER_RUNGS["twin"] = r4, with r2 as
    B.5's map; the twin is never ticketed alone; its source_ref."""

    def test_the_twins_rungs_and_its_source_ref(self):
        from bot_program.orcs import mind, mind_gateway, scheduler
        self.assertEqual(mind_gateway.CALLER_RUNGS["twin"], ("r4",))
        self.assertEqual(mind_gateway.MAPPED_RUNGS["twin"], {"r2": ("r4",)})
        self.assertNotIn("r5", mind_gateway.CALLER_RUNGS["wake"],
                         "r5 only through the Fable gate")
        mind_gateway.check_rung("twin", "r4")
        mind_gateway.check_rung("twin", "r2", would="r4")
        for rung, would in (("r2", None), ("r5", None), ("r3", None),
                            ("r0", None), ("h0", None), ("r2", "r3")):
            with self.subTest(rung=rung, would=would), \
                    self.assertRaises(ValueError):
                mind_gateway.check_rung("twin", rung, would=would)
        with self.assertRaises(ValueError):
            scheduler.reserve_ticket("twin", {"rung": "r4", "tokens": 1000})
        self.assertEqual(self.tickets(), {})
        w = self.extreme()
        self.assertEqual(mind.source_ref(w, "r4", caller="twin"),
                         f"Orc:{w.orc_id}:Wake:{w.pk}:twin:r4")


# ── the smoke (B.15c, P35) ───────────────────────────────────────────────

class TheFrontierSmokeTests(_Frontier):

    def test_r5_is_refused_with_the_gates_clause_after_its_positive_control(
            self):
        """`orcs smoke --rung r5` goes only through Fable's gate: at the
        floor as it ships, with a quota of 1 and both switches ON, the
        Orc's latest wake (real money, extreme) is refused with the clause
        that fails (`inflight`), dry and with --yes, and nothing is
        reserved, after its positive control (the smoke on r0)."""
        self.quota(1)
        self.frontier()
        live = self.live()
        self.extreme(live)
        self.use_fake(fake_answer(answer()))
        self.smoke(live, "--yes")
        self.assert_one_call()
        dry = " ".join(self.smoke(live, "--rung", "r5").split())
        self.assertIn(INFLIGHT, dry)
        self.assertIn("DRY RUN", dry)
        with self.assertRaises(CommandError) as cm:
            self.smoke(live, "--rung", "r5", "--yes")
        said = str(cm.exception)
        self.assertIn("rung 'r5'", said)
        self.assertIn(INFLIGHT, said)
        self.assertIn("Nothing was reserved or sent", said)
        self.assert_no_call()
        self.assertEqual(self.tickets(), {})
        # a paper Orc's: its first clause
        self.rendered()
        with self.assertRaises(CommandError) as cm:
            self.smoke(self.orc, "--rung", "r5", "--yes")
        self.assertIn(NOT_REAL, str(cm.exception))
        self.assert_no_call()


# ── K-B10 (N6) ───────────────────────────────────────────────────────────

class NoAccountFigureInThePairTests(_Frontier):

    def test_no_account_figure_in_the_r5_or_twin_request(self):
        self.open_gate(quota=2)
        for n in (1, 2):
            w = self.extreme(self.live(), n=n)
            self.answers()
            self.assertEqual(self.serve()["wake"].pk, w.pk)
            self.assert_pair_call()
        self.assertEqual(len(self.requests), 4)
        self.assert_no_account_figure()


# ── the words (§1.0 item 7) ──────────────────────────────────────────────

class TheFrontierCardTests(_Frontier):

    def setUp(self):
        super().setUp()
        staff = get_user_model().objects.create_user(
            "o2b_frontier_staff", password="x", is_staff=True)
        self.client.force_login(staff)

    def card(self) -> str:
        from html import unescape
        html = unescape(self.client.get("/ai-models/").content.decode())
        return " ".join(html.split("The Orcs (read-only)", 1)[1].split(
            "Catalog</span>", 1)[0].split())

    def test_the_card_says_fable_stays_at_0_through_o2(self):
        text = self.card()
        self.assertIn(SAID_CLOSED, text)
        self.assertIn(f"${self.pair_bound():.2f}", text)
        self.assertIn("above the $3.00 the Orcs may hold in flight", text)
        self.assertIn("The frontier switch (orcs_frontier) is off", text)
        self.assertIn("its quota (frontier_per_day) is 0 a day", text)
        self.frontier()
        self.quota(1)
        text = self.card()
        self.assertIn(SAID_CLOSED, text)
        self.assertIn("The frontier switch (orcs_frontier) is on", text)
        self.assertIn("its quota (frontier_per_day) is 1 a day", text)


class TheFrontierWordsTests(MindTestCase):

    def test_the_runbook_says_fable_stays_at_0_through_o2(self):
        text = RUNBOOK.read_text(encoding="utf-8")
        head = "### Fable's gate (O2b)"
        self.assertIn(head, text)
        start = text.index(head)
        self.assertGreater(start, text.index("### The Orcs' probes (O2b)"))
        section = " ".join(text[start:text.index("## Operating notes",
                                                 start)].split())
        for words in ("Fable (r5) stays at 0 through O2", "`orcs_frontier`",
                      NAME, "/ops/", "trading PIN", "takes no PIN",
                      "`frontier_per_day`", "0 by default", "blind twin",
                      "the same stored dossier", "no fallback",
                      "about $3.57", "$2.69", "$0.88", "$3.00",
                      "the gate cannot open", "Fable adds $0",
                      "the router never reads", "--rung r5`",
                      "real money", "extreme", "r4"):
            self.assertIn(words, section)
        self.assertNotIn("component on orcs_frontier", text)
        flat = " ".join(text.split())
        smoke = flat.split("Three subcommands prepare the minds",
                           1)[1].split("```", 1)[0]
        self.assertNotIn("never r5", smoke)
        self.assertIn("r5 only through Fable's gate", smoke)

    def test_the_comments_say_the_quota_is_the_settings(self):
        from bot_program.orcs import router, wake, weather
        src = inspect.getsource(weather)
        self.assertNotIn("FRONTIER_PER_DAY = {", src)
        doc = " ".join(weather.__doc__.split())
        self.assertIn("frontier_per_day", doc)
        self.assertNotIn("The frontier quota is shown only", doc)
        for text in (router.__doc__, wake._route.__doc__):
            words = " ".join(text.split())
            self.assertNotIn("B.9 is a later commit's", words)
            self.assertNotIn("closed with no frontier quota", words)
        self.assertIn("frontier_per_day", " ".join(router.__doc__.split()))

    def test_the_gates_clauses_are_read_in_order(self):
        """B.9, pure: the first clause that fails, each read only when
        every clause before it holds."""
        from bot_program.orcs import router
        read = []

        def reader(name, value):
            def f():
                read.append(name)
                return value
            return f
        full = dict(real=True, band="extreme", quota=reader("quota", 1),
                    switch=reader("switch", True), money=reader("money", ""),
                    render=reader("render", ""))
        self.assertEqual(router.fable_gate(**full), "")
        self.assertEqual(read, ["quota", "switch", "money", "render"])
        for over, said, upto in (
                ({"real": False}, NOT_REAL, []),
                ({"band": "complex"}, NOT_EXTREME, []),
                ({"quota": reader("quota", 0)}, NO_QUOTA, ["quota"]),
                ({"switch": reader("switch", False)}, FRONTIER_OFF,
                 ["quota", "switch"]),
                ({"money": reader("money", "triage")},
                 "the pair does not fit under its class's ceiling",
                 ["quota", "switch", "money"]),
                ({"money": reader("money", "deep_share")},
                 "the pair does not fit under the deep tiers' share",
                 ["quota", "switch", "money"]),
                ({"money": reader("money", "inflight")}, INFLIGHT,
                 ["quota", "switch", "money"]),
                ({"render": reader("render", OVER_CAP)}, OVER_CAP,
                 ["quota", "switch", "money", "render"])):
            read.clear()
            with self.subTest(said=said):
                self.assertEqual(router.fable_gate(**{**full, **over}), said)
                self.assertEqual(read, upto)
