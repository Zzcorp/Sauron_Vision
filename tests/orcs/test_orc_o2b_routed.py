"""O2b's SECOND COMMIT, THE ROUTED RUNG ANSWERS (the O2 spec B.2b, B.4,
B.5, B.7, B.13, B.14, B.15a, B.16a and N2 for `orcs_router`; §1.2.5 P34,
P36-P39; §1.2.6 "The switch", "One render", "The answering rung", "Effort
without a PASS", "The deep share", "Fallbacks" (the wake and the smoke),
"The card", K-B10 and "Unchanged"; 2026-11-06).

Behind a new switch, `orcs_router` (OFF on arrival, the trading PIN to
turn it on), the rung the router chose answers a wake a model reads, on a
dossier rendered once for that rung's model family. OFF, as it ships, r0
answers every wake and the router's choice is only recorded. Nothing here
turns a switch on for the operator: every gate answers as it ships.

- N2: the switch ships OFF beside the minds, exempt from "all on", in
  ORC_MIND_SWITCHES and never a live-money switch; no PIN, a wrong one,
  the shell and the Django admin turn nothing on; the right PIN does; OFF
  takes none; its description is under 300 characters; unreadable, OFF
- the switch's pair: OFF, a real complex wake (the Opus PASS recorded)
  records route r3 and its one request is on r0's model; ON, its one
  request is on r3's model; switched OFF between the render and the claim,
  its one request is on r0's model, re-priced
- one render, for the routed family; components.tokens is that render's
- the answering rung: RUNG_LIMITS, the bound, the tier, the source_ref and
  the grade's tag are r2's while would_rung keeps r3; so are the HIGH in
  flight and the wall time
- a long call keeps the worker busy (A.55, §4 Q8; 2026-11-06, completing
  O2b): behind another Orc's r3 call, a real-money Orc's own r4 call, an
  r5 pair or an r3 probe, each still inside its wall time past the
  30-minute stale clock, the wake that waited closes `backlog` and no Orc
  goes to the care; past the wall, or behind a smoke sent from the shell,
  the worker is silent
- effort without a PASS: r1 is sent as r0 and r3 as r2; with the PASS the
  effort-only message carries the rung's effort and the top-level effort
  is the model's default
- the deep share (B.13): past 70% of the line (booked, in flight and held,
  and the bound) an r2 wake ends `deep_share` at admission and at the
  claim, after its positive control; a real-money urgent wake still calls
  once (D30); a ticket is held to it too
- fallbacks (B.14): the id from the catalog; the bound with its own; a
  real-money r2 wake sends the list form, a paper r3 wake and the smoke
  none; a served fallback's model lands on the wake and the decision
- the card (B.7, U-R31): rung_t in tier words, no model id, no cost
- K-B10: no account figure in any routed request
- the smoke (B.15a, P34, P35): a rung above r0 needs the router's switch,
  r1 answers as r0 without the PASS (both rungs printed), r5 is refused,
  and it is dry by default
- /ai-models/ (B.16a): the card's sentence reads the switch; per rung,
  today's calls and would-counts; the ladder's notes kept (K/D-A4)
- the RUNBOOK's router steps (K-R8, U-R6, U-R31)

Run with:  python manage.py test tests.orcs.test_orc_o2b_routed
"""
import json
import re
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

from tests.orcs.helpers import _switch
from tests.orcs.helpers_o2 import MindTestCase, fake_answer
from tests.orcs.test_orc_o2a_admission import W4
from tests.orcs.test_orc_o2a_call import answer
from tests.orcs.test_orc_o2b_router import (MONEY_KEYS, _keys, _model_words,
                                            _Route, _verdicts)

BASE = Path(settings.BASE_DIR)
RUNBOOK = BASE / "deploy" / "RUNBOOK.md"
KEY = "orcs_router"
NAME = "Orc Router (routed rungs in shadow)"
DESCRIPTION = ("Off (default). While off, every Orc wake a model reads is "
               "answered on r0 and the router's choice is only recorded. On, "
               "with the minds on, the rung the router chose answers, one "
               "effort per model until the smoke's PASS. Nothing it decides "
               "sends an order. Turning it on takes the PIN.")
#: Test-only values, never the operator's.
TEST_PIN = "583920"
WRONG_PIN = "104729"
#: A patched score in each band, far from every boundary (30, 55, 75).
ROUTINE, MATERIAL, COMPLEX = 12.0, 42.0, 65.0
#: A reason neither urgent nor routine: F6 never quiets it.
W7 = {"code": "W7", "key": "W7:risk:x", "t": "open risk at 80% of its limit",
      "urgent": False}
#: The card's sentence on /ai-models/, by the router's switch.
SAID_OFF = ("Once the minds switch and the Orcs line are on, every wake a "
            "model reads is answered on r0: the router's switch "
            "(orcs_router) is off, and its choice is only recorded.")
SAID_ON = ("Once the minds switch and the Orcs line are on, every wake a "
           "model reads is answered on the rung the router chose: its "
           "switch (orcs_router) is on, one effort per model until the "
           "smoke's PASS for the model's family.")


def _urgent(n) -> dict:
    """An urgent reason of its own key: F6 never quiets it, the spacing
    never holds it."""
    return {**W4, "key": f"W4:routed:{n}", "t": f"-0.{n}R reached"}


def _row_of(key=KEY):
    from core.platform_control import PlatformComponent
    return PlatformComponent.objects.get(key=key)


def _gateway_asks(test):
    """The can_spend calls made inside mind_gateway.call."""
    return [c for c in test.spend_calls if c.gateway is not None]


# ── N2: the switch itself ────────────────────────────────────────────────

class TheRouterSwitchShipsOffTests(MindTestCase):

    def setUp(self):
        from core.platform_control import seed_components
        cache.clear()
        seed_components()

    def test_it_is_seeded_off_beside_the_minds(self):
        from core.platform_control import DEFAULT_COMPONENTS

        from bot_program.orcs import switches
        row = _row_of()
        self.assertFalse(row.is_enabled)
        self.assertEqual((row.name, row.category), (NAME, "system"))
        self.assertEqual(row.description, DESCRIPTION)
        self.assertLess(len(row.description), 300)
        entry = [c for c in DEFAULT_COMPONENTS if c["key"] == KEY]
        self.assertEqual(len(entry), 1)
        self.assertNotIn("is_enabled", entry[0], "it arrives OFF")
        self.assertNotIn("enabled", entry[0])
        keys = [c["key"] for c in DEFAULT_COMPONENTS]
        self.assertEqual(keys.index(KEY), keys.index("orcs_minds") + 1)
        self.assertFalse(switches.router_on())
        _switch(KEY, True)
        self.assertTrue(switches.router_on())
        # an unreadable switch reads OFF
        with patch("core.platform_control.is_component_enabled",
                   side_effect=RuntimeError("the table is gone")):
            self.assertFalse(switches.router_on())

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
        self.assertFalse(_row_of().is_enabled, '"all on" never reaches it')


class OnlyThePinTurnsTheRouterOnTests(MindTestCase):

    def setUp(self):
        from core.platform_control import seed_components
        from portfolio.trader_profile import get_or_create_profile
        cache.clear()
        seed_components()
        self.admin = get_user_model().objects.create_superuser(
            "o2b_router_admin", "o2b_router@example.test", "x")
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
        row = _row_of()
        data = {"form-TOTAL_FORMS": "1", "form-INITIAL_FORMS": "1",
                "form-MIN_NUM_FORMS": "0", "form-MAX_NUM_FORMS": "1000",
                "form-0-id": str(row.pk), "form-0-is_enabled": "on",
                "_save": "Save"}
        self.client.post("/admin/core/platformcomponent/", data)
        self.assertFalse(_row_of().is_enabled, "no door armed it")
        from core import switch_pin
        self.assertFalse(switch_pin.set_switch(
            KEY, True, via=switch_pin.VIA_SHELL).ok)
        self.assertFalse(_row_of().is_enabled)

    def test_the_right_pin_turns_it_on_and_off_takes_none(self):
        from bot_program.audit_models import AuditLogEntry
        self.ops(want="on", pin=TEST_PIN)
        self.assertTrue(_row_of().is_enabled)
        armed = [e for e in AuditLogEntry.objects.filter(kind="switch_armed")
                 if (e.data or {}).get("key") == KEY]
        self.assertEqual(len(armed), 1)
        out = StringIO()
        call_command("component", "off", KEY, stdout=out)
        self.assertIn(f"{KEY}: ON → OFF", out.getvalue())
        self.assertFalse(_row_of().is_enabled)


# ── the routed wake (the render pass, the queue, the fake model) ─────────

class _Routed(_Route):
    """_Route's Orc and gates (the four ON, the Orcs line at $6), the
    router's switch as each test sets it."""

    def router(self, on=True):
        _switch(KEY, on)

    @staticmethod
    def model(rung):
        from bot_program.orcs import mind_gateway
        return mind_gateway.rung(rung)["model"]

    def routed(self, reasons, *, orc=None, score=COMPLEX):
        """A wake the tick recorded and the render pass rendered and
        admitted, its score patched into a band (the route's input)."""
        w = self.record(reasons, orc=orc)
        with patch("bot_program.orcs.complexity.score", return_value=score):
            self.render_pass()
        return self.fresh(w)

    def smoke(self, orc, *args) -> str:
        out = StringIO()
        call_command("orcs", "smoke", "--row", str(orc.root_trade_id), *args,
                     stdout=out)
        return out.getvalue()

    def tickets(self) -> dict:
        from bot_program.orcs.models import OrcSetting
        return {k: v for k, v in (OrcSetting.get("minds_inflight") or {})
                .items() if isinstance(v, dict) and v.get("kind") == "ticket"}

    def booked_to(self, total):
        """Book on the Orcs line what brings its booked spend today to
        `total`."""
        from ai_agents import spend
        self.book(round(total - spend.spent_today("orcs"), 6))


class TheSwitchPairTests(_Routed):
    """§1.2.6 "The switch" (N7's pairs): OFF the router's choice is only
    recorded and r0 answers; ON the routed rung answers; switched OFF
    between the render and the claim, r0 answers, re-priced."""

    def test_off_records_r3_and_r0_answers_on_one_request(self):
        _verdicts(sonnet="pass", opus="pass")
        live = self.live()
        w = self.routed([W4], orc=live)
        route = self.assert_route(w)
        self.assertEqual((route["would_rung"], route["rung"]), ("r3", "r3"))
        self.assertEqual((w.status, w.components["rung"]), ("pending", "r0"))
        self.assertEqual(w.components["family"], "sonnet",
                         "rendered for the reference family")
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertEqual(self.requests[-1].kwargs["model"], self.model("r0"))
        w = self.fresh(w)
        self.assertEqual((w.status, w.model, w.components["rung"]),
                         ("done", self.model("r0"), "r0"))

    def test_on_the_routed_model_answers_on_one_request(self):
        _verdicts(sonnet="pass", opus="pass")
        self.router()
        live = self.live()
        w = self.routed([W4], orc=live)
        route = self.assert_route(w)
        self.assertEqual((route["would_rung"], route["rung"]), ("r3", "r3"))
        self.assertEqual((w.status, w.components["rung"],
                          w.components["family"]), ("pending", "r3", "opus"))
        got = self.serve(script=fake_answer(answer(),
                                            model=self.model("r3")))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertEqual(self.requests[-1].kwargs["model"], self.model("r3"))
        w = self.fresh(w)
        self.assertEqual((w.status, w.model, w.components["rung"]),
                         ("done", self.model("r3"), "r3"))

    def test_switched_off_between_the_render_and_admission_r0_waits(self):
        """Admission reads the switch too: a wake rendered for Opus while
        the switch was ON and admitted once it is OFF (one render pass)
        waits on r0, with r0's bound and no fallback, and its one request
        is on r0's model."""
        from bot_program.orcs import mind_gateway, switches
        _verdicts(sonnet="pass", opus="pass")
        live = self.live()
        w = self.record([W4], orc=live)
        with patch.object(switches, "router_on", side_effect=[True, False]), \
                patch("bot_program.orcs.complexity.score",
                      return_value=COMPLEX):
            self.render_pass()
        w = self.fresh(w)
        self.assertEqual((w.components["family"],
                          w.components["route"]["rung"]), ("opus", "r3"))
        self.assertEqual((w.status, w.components["rung"]), ("pending", "r0"))
        self.assertAlmostEqual(w.components["bound"], mind_gateway.bound(
            "r0", w.components["tokens"]), places=6)
        self.assertIs(w.components["fallback"], False)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertEqual(self.requests[-1].kwargs["model"], self.model("r0"))

    def test_switched_off_between_the_render_and_the_claim_r0_answers(self):
        """Frictionless off: the claim reads the switch again. A wake
        admitted on r3 is re-priced and answered on r0 from its stored
        dossier (the Opus and Sonnet texts are one size at factor 1.0): its
        bound is r0's, with no fallback, on the balanced tier."""
        from bot_program.orcs import mind_gateway
        _verdicts(sonnet="pass", opus="pass")
        self.router()
        live = self.live()
        w = self.routed([W4], orc=live)
        self.assertEqual(w.components["rung"], "r3")
        self.router(False)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        sent = self.requests[-1].kwargs
        self.assertEqual(sent["model"], self.model("r0"))
        self.assertNotIn("fallbacks", sent)
        asked = _gateway_asks(self)[-1].kwargs
        self.assertEqual(asked["tier"], "balanced")
        self.assertAlmostEqual(asked["estimated_usd"], mind_gateway.bound(
            "r0", w.components["tokens"]), places=6)
        w = self.fresh(w)
        self.assertEqual((w.status, w.model, w.components["rung"]),
                         ("done", self.model("r0"), "r0"))
        self.assertEqual((w.components["route"]["would_rung"],
                          w.components["route"]["rung"]), ("r3", "r3"),
                         "the router's choice is kept")


class OneRenderForTheRoutedFamilyTests(_Routed):
    """B.4: with the router's switch ON, ONE render, for the family of the
    answering rung's model; components.tokens is that render's, and so is
    the stored S. OFF, the reference family, as O2a."""

    def test_one_render_for_the_routed_family_its_tokens_kept(self):
        from bot_program.orcs import dossier
        from bot_program.orcs.models import OrcDossierBlock
        real_render = dossier.render
        for on, family, rung in ((True, "opus", "r2"),
                                 (False, "sonnet", "r0")):
            with self.subTest(router=on):
                seen = []

                def render(*a, **k):
                    out = real_render(*a, **k)
                    seen.append((k.get("model"), out["tokens"],
                                 out["model"]))
                    return out
                self.router(on)
                live = self.live()
                with patch.object(dossier, "render", render):
                    w = self.routed([W4], orc=live)
                self.assertEqual(len(seen), 1, "one render")
                self.assertEqual(seen[0][0], family if on else None)
                self.assertEqual(seen[0][2], family)
                self.assertEqual(w.components["tokens"], seen[0][1])
                self.assertEqual((w.components["family"],
                                  w.components["rung"]), (family, rung))
                s = OrcDossierBlock.objects.get(hash=w.components["s"][
                    "hash"])
                self.assertEqual(s.key, f"s|s1|{family}")


class TheAnsweringRungTests(_Routed):
    """B.2b, N4: the answering rung governs: RUNG_LIMITS, the bound, the
    tier, CALLER_RUNGS, the source_ref and the grade's tag are its own;
    the routed rung is kept only as components["route"]["would_rung"]."""

    def test_limits_bound_tier_ref_and_tag_are_the_answering_rungs(self):
        """A real complex wake with no Opus PASS: would r3, answered as
        r2."""
        from ai_agents.models import AgentTask

        from bot_program.orcs import grading, mind_gateway, scheduler
        from bot_program.orcs.constants import HIGH, RUNG_LIMITS
        from bot_program.orcs.models import OrcJournal
        self.router()
        live = self.live()
        w = self.routed([W4], orc=live)
        route = self.assert_route(w)
        self.assertEqual((route["would_rung"], route["rung"]), ("r3", "r2"))
        bound = mind_gateway.bound("r2", w.components["tokens"],
                                   fallback=True)
        self.assertEqual(w.components["rung"], "r2")
        self.assertAlmostEqual(w.components["bound"], bound, places=6)
        self.assertIs(w.components["fallback"], True)
        got = scheduler.claim()
        self.assertEqual(got["wake"].pk, w.pk)
        running = self.fresh(w)
        self.assertEqual(running.est_usd, Decimal(str(round(bound, 6))))
        self.assertEqual(running.model, self.model("r2"))
        self.assertEqual(scheduler._running_high(live.pk), HIGH["r2"],
                         "the HIGH in flight is r2's")
        from bot_program.orcs import mind
        self.use_fake(fake_answer(answer(), model=self.model("r2")))
        mind.think(got["wake"])
        self.assert_one_call()
        sent = self.requests[-1].kwargs
        self.assertEqual((sent["model"], sent["max_tokens"], sent["timeout"]),
                         (self.model("r2"), RUNG_LIMITS["r2"]["max_tokens"],
                          float(RUNG_LIMITS["r2"]["timeout_s"])))
        asked = _gateway_asks(self)[-1].kwargs
        self.assertEqual(asked["tier"], "deep")
        self.assertAlmostEqual(asked["estimated_usd"], bound, places=6)
        ref = f"Orc:{live.pk}:Wake:{w.pk}:r2"
        self.assertTrue(AgentTask.objects.filter(
            structured_output__source_ref=ref).exists())
        decision = OrcJournal.objects.get(kind="decision", wake=w)
        self.assertEqual(decision.body["rung"], "r2")
        self.assertIn("rung:r2", grading.mind_tags(grading.mind_counts(live)))
        w = self.fresh(w)
        self.assertEqual((w.components["route"]["would_rung"],
                          w.components["rung"]), ("r3", "r2"))

    def test_the_wall_time_is_the_answering_rungs(self):
        """A.55 on the wake's own rung: an r2 call running past r0's wall
        time is still running; past r2's it is closed."""
        from bot_program.orcs import scheduler
        from bot_program.orcs.constants import WALL_S
        from bot_program.orcs.models import OrcWake
        now = timezone.now()
        mid = OrcWake.objects.create(
            orc=self.orc, reasons=[], dedupe_key="r2a", kind="material",
            status="running", est_usd=Decimal("0.5"),
            started_at=now - timedelta(seconds=WALL_S["r0"] + 60),
            components={"rung": "r2"})
        self.assertEqual(scheduler._wall_time(now), 0)
        self.assertEqual(OrcWake.objects.get(pk=mid.pk).status, "running")
        OrcWake.objects.filter(pk=mid.pk).update(
            started_at=now - timedelta(seconds=WALL_S["r2"] + 60))
        self.assertEqual(scheduler._wall_time(now), 1)
        self.assertEqual(OrcWake.objects.get(pk=mid.pk).skipped_reason,
                         "wall_time")

    def test_a_rung_the_wake_may_not_use_is_never_sent(self):
        """N4: a claimed wake on a rung outside CALLER_RUNGS["wake"] (r5,
        Fable's, whose gate is C4's) ends `failed` before any send, its
        bound released at once, after its positive control."""
        from bot_program.orcs import mind
        from bot_program.orcs.models import OrcWake
        w = self.claim(self.rendered())
        out = self.think(w, fake_answer(answer()))
        self.assertEqual(out["status"], "done")
        self.assert_one_call()
        twin = self.copy_of(w)
        OrcWake.objects.filter(pk=twin.pk).update(components={
            **twin.components, "rung": "r5"})
        out = mind.think(OrcWake.objects.get(pk=twin.pk))
        twin = OrcWake.objects.get(pk=twin.pk)
        self.assert_no_call(code="unsent", got=twin.skipped_reason)
        self.assertEqual((out["status"], twin.status, twin.est_usd),
                         ("failed", "failed", Decimal(0)))
        self.assertNotIn(f"w{twin.pk}", self.holds())


class TheLongCallsKeepTheWorkerBusyTests(_Routed):
    """A.55, §4 Q8 (2026-11-06, completing O2b): from O2b a call may run
    past STALE_MIN inside its wall time (A.21: r3's 2,160 s, r4's and r5's
    3,460 s, an r5 pair's both), a routed wake's or a probe's ticket. While
    one does, the worker is busy, never silent: a wake that waited 31
    minutes behind it closes `backlog`, a code answer, and no Orc goes to
    the care. Each with its pair: past its wall time the same call keeps
    nothing busy, and a smoke's ticket (sent from the shell, never by the
    worker) never does."""

    def running(self, orc, *, started, rung="r3", **comps):
        """A wake of `orc` claimed at `started` on `rung`, still running."""
        from bot_program.orcs.models import OrcWake
        n = OrcWake.objects.count()
        return OrcWake.objects.create(
            orc=orc, reasons=[], dedupe_key=f"long{n}", kind="material",
            status="running", est_usd=Decimal("0.71"), started_at=started,
            components={"rung": rung, **comps})

    def ticket(self, caller, rung, at, **extra):
        """A ticket of `caller` on `rung` reserved at `at`, as the probes
        (probes.send) and the smoke (orcs smoke --row) reserve theirs."""
        from bot_program.orcs import scheduler
        got = scheduler.reserve_ticket(caller, {
            "rung": rung, "tokens": 1000, "orc": self.orc.pk,
            "ref": f"Orc:{self.orc.pk}:Wake:0:{caller}:{rung}", **extra},
            now=at)
        self.assertTrue(got["ok"], got["code"])
        return got["key"]

    def assert_busy(self, out, waiting):
        """The waiting wake closed behind a busy worker: `backlog`, and its
        Orc kept from the care."""
        from bot_program.orcs.models import Orc
        waiting.refresh_from_db()
        self.assertEqual((waiting.status, waiting.skipped_reason),
                         ("skipped", "backlog"))
        self.assertEqual((out["minds_backlog"], out["minds_stale"]), (1, 0))
        orc = Orc.objects.get(pk=waiting.orc_id)
        self.assertNotEqual(orc.state, "care_owned")
        self.assertEqual(self.took(orc), [])

    def assert_silent(self, out, waiting):
        """The waiting wake closed for a silent worker: `stale`,
        `worker_silent`, and its Orc to the care (A.52)."""
        from bot_program.orcs.models import Orc
        waiting.refresh_from_db()
        self.assertEqual((waiting.status, waiting.skipped_reason),
                         ("stale", "worker_silent"))
        self.assertEqual(out["minds_stale"], 1)
        orc = Orc.objects.get(pk=waiting.orc_id)
        self.assertEqual(orc.state, "care_owned")
        self.assertEqual(len(self.took(orc)), 1)

    def test_another_orcs_r3_call_inside_its_wall_is_a_busy_worker(self):
        """Another Orc's r3 call claimed 31 minutes ago (r3's wall is 36):
        the wake that waited 31 minutes closes `backlog` and the call runs
        on. The pair: once that call is past its wall, a wake that waited
        31 minutes reads a silent worker, and the call is closed for its
        wall time in the same pass."""
        from bot_program.orcs.constants import STALE_MIN, WALL_S
        base = self.rendered([W4])
        now = timezone.now()
        started = now - timedelta(minutes=31)
        self.assertLess(STALE_MIN * 60, 31 * 60)
        self.assertLess(31 * 60, WALL_S["r3"])
        other = self.orcs(1)[0]
        run = self.running(other, started=started)
        waiting = self.pending(base, now - timedelta(minutes=31),
                               reasons=[W4])
        self.assert_busy(self.watch(now), waiting)
        self.assertEqual(self.fresh(run).status, "running")
        later = started + timedelta(seconds=WALL_S["r3"] + 60)
        again = self.pending(base, later - timedelta(minutes=31),
                             reasons=[W4])
        self.assert_silent(self.watch(later), again)
        run = self.fresh(run)
        self.assertEqual((run.status, run.skipped_reason),
                         ("failed", "wall_time"))

    def test_its_own_orcs_r4_call_inside_its_wall_is_a_busy_worker(self):
        """A.18: one call in flight per Orc, so a real-money Orc's next
        wake waits behind its own r4 call, claimed 40 minutes ago (r4's
        wall is 58): it closes `backlog` after 31 minutes, never
        `worker_silent`, and the care never takes that Orc. The pair: past
        r4's wall, the same wait reads a silent worker."""
        from bot_program.orcs.constants import WALL_S
        live = self.live()
        base = self.rendered([W4], orc=live)
        now = timezone.now()
        started = now - timedelta(minutes=40)
        self.assertLess(40 * 60, WALL_S["r4"])
        run = self.running(live, started=started, rung="r4")
        waiting = self.pending(base, now - timedelta(minutes=31), orc=live,
                               reasons=[W4])
        self.assert_busy(self.watch(now), waiting)
        self.assertEqual(self.fresh(run).status, "running")
        later = started + timedelta(seconds=WALL_S["r4"] + 60)
        again = self.pending(base, later - timedelta(minutes=31), orc=live,
                             reasons=[W4])
        self.assert_silent(self.watch(later), again)
        self.assertEqual(self.fresh(run).skipped_reason, "wall_time")

    def test_an_r5_pairs_wall_is_the_wall_times_own(self):
        """An r5 wake's pair (O2b's frontier) is sent within one wall time,
        r5's and its twin's: claimed 70 minutes ago, past r5's 58 minutes
        alone, it still keeps the worker busy, as _wall_time keeps it
        running. The pair: past both walls, a silent worker."""
        from bot_program.orcs.constants import WALL_S
        base = self.rendered([W4])
        now = timezone.now()
        started = now - timedelta(minutes=70)
        self.assertLess(WALL_S["r5"], 70 * 60)
        self.assertLess(70 * 60, WALL_S["r5"] + WALL_S["r4"])
        run = self.running(self.orcs(1)[0], started=started, rung="r5",
                           twin={"key": "tpair", "rung": "r4", "bound": 0.87,
                                 "ref": "x"})
        waiting = self.pending(base, now - timedelta(minutes=31),
                               reasons=[W4])
        self.assert_busy(self.watch(now), waiting)
        self.assertEqual(self.fresh(run).status, "running")
        later = started + timedelta(seconds=WALL_S["r5"] + WALL_S["r4"]
                                    + 60)
        again = self.pending(base, later - timedelta(minutes=31),
                             reasons=[W4])
        self.assert_silent(self.watch(later), again)
        self.assertEqual(self.fresh(run).skipped_reason, "wall_time")

    def test_a_probe_inside_its_wall_is_a_busy_worker_a_smoke_never(self):
        """The worker sends the probes (tasks.orc_think, after its claims):
        an r3 probe reserved 31 minutes ago, inside r3's wall, keeps it
        busy, and the wake that waited 31 minutes closes `backlog`. The
        pair: once that probe is past its wall, a smoke's r4 ticket
        reserved 31 minutes ago (the shell's call, inside its own wall)
        keeps nothing busy: a silent worker."""
        from bot_program.orcs.constants import WALL_S
        _verdicts(sonnet="pass", opus="pass")
        _switch("orcs_probes", True)
        base = self.rendered([W4])
        now = timezone.now()
        at = now - timedelta(minutes=31)
        probe = self.ticket("probe", "r3", at, kind="boundary",
                            user=self.user.pk, would_rung="r3",
                            item="probe:0:boundary")
        self.assertEqual(self.tickets()[probe]["wall_s"], WALL_S["r3"])
        waiting = self.pending(base, at, reasons=[W4])
        self.assert_busy(self.watch(now), waiting)
        self.assertEqual(self.tickets()[probe]["kind"], "ticket",
                         "still in flight")
        later = at + timedelta(seconds=WALL_S["r3"] + 60)
        smoke = self.ticket("smoke", "r4", later - timedelta(minutes=31))
        self.assertLess(31 * 60, self.tickets()[smoke]["wall_s"])
        again = self.pending(base, later - timedelta(minutes=31),
                             reasons=[W4])
        self.assert_silent(self.watch(later), again)


class EffortWithoutAPassTests(_Routed):
    """B.5: one effort per model until the smoke's PASS for its family
    (the fake sees the effort)."""

    def test_r1_is_sent_as_r0_and_r3_as_r2_without_a_pass(self):
        self.router()
        for score, would, rung, effort in ((MATERIAL, "r1", "r0", "low"),
                                           (COMPLEX, "r3", "r2", "medium")):
            with self.subTest(would=would):
                orc = self.orcs(1)[0]
                w = self.routed([W4], orc=orc, score=score)
                route = self.assert_route(w)
                self.assertEqual((route["would_rung"], route["rung"]),
                                 (would, rung))
                self.assertEqual(w.components["rung"], rung)
                got = self.serve(script=fake_answer(answer()))
                self.assertEqual(got["wake"].pk, w.pk)
                self.assert_one_call()
                sent = self.requests[-1].kwargs
                self.assertEqual(sent["model"], self.model(rung))
                self.assertEqual(sent["output_config"]["effort"], effort)
                self.assertEqual([m for m in sent["messages"]
                                  if m.get("role") == "system"], [],
                                 "no effort-only message without the PASS")

    def test_with_the_pass_the_effort_only_message_carries_the_rungs(self):
        """With Opus's PASS a paper complex wake answers on r3: the
        effort-only message says r3's effort (high), and the top-level
        effort is Opus's default (medium), so the cache key never
        moves."""
        from ai_agents.catalog import default_effort
        _verdicts(sonnet="pass", opus="pass")
        self.router()
        w = self.routed([W4], orc=self.orcs(1)[0], score=COMPLEX)
        self.assertEqual(w.components["rung"], "r3")
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        sent = self.requests[-1].kwargs
        self.assertEqual(sent["model"], self.model("r3"))
        turn = [m for m in sent["messages"] if m.get("role") == "system"]
        self.assertEqual([m["output_config"]["effort"] for m in turn],
                         ["high"])
        self.assertEqual(sent["output_config"]["effort"],
                         default_effort(self.model("r3")))
        self.assertEqual(default_effort(self.model("r3")), "medium")

    def test_a_verdict_recorded_after_the_render_binds_at_the_claim(self):
        """The claim maps the admitted rung again: a FAIL recorded after
        an r3 wake was admitted sends it as r2 (one effort per model)."""
        _verdicts(sonnet="pass", opus="pass")
        self.router()
        w = self.routed([W4], orc=self.orcs(1)[0], score=COMPLEX)
        self.assertEqual(w.components["rung"], "r3")
        _verdicts(sonnet="pass", opus="fail")
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        sent = self.requests[-1].kwargs
        self.assertEqual((sent["model"], sent["output_config"]["effort"]),
                         (self.model("r2"), "medium"))
        self.assertEqual(self.fresh(w).components["rung"], "r2")


class TheDeepShareTests(_Routed):
    """B.13: for r2-r5 the line's booked spend, plus the OTHER calls in
    flight and the holds, plus this bound, stays within 70% of the cap,
    else `deep_share`. spend.can_spend weighs the booked spend alone
    (spend.py), so the scheduler's money code mirrors it. A real-money
    urgent wake is exempt (D30); a ticket never is."""

    def test_an_r2_wake_past_70_percent_is_deep_share_with_no_call(self):
        """The positive control: a real non-urgent r2 wake well under 70%
        is read, one request. Then the booked spend under 70% alone, with
        a hold and the bound passing it: a pending r2 wake is answered
        `deep_share` at the claim and a new one at admission, with no
        request; a real-money urgent r2 wake still calls once."""
        from bot_program.orcs import scheduler
        from bot_program.orcs.models import OrcJournal
        self.router()
        a = self.routed([W7], orc=self.live(), score=MATERIAL)
        self.assertEqual((a.status, a.components["rung"]), ("pending", "r2"))
        got = self.serve(script=fake_answer(answer(),
                                            model=self.model("r2")))
        self.assertEqual(got["wake"].pk, a.pk)
        self.assert_one_call()
        b = self.routed([W7], orc=self.live(), score=MATERIAL)
        self.assertEqual((b.status, b.components["rung"]), ("pending", "r2"))
        bound = float(b.components["bound"])
        cap = 6.0
        # booked + held + bound = 70% of the line + half the bound, the
        # booked spend alone under it (can_spend would pass it)
        self.hold_usd(0.30)
        self.booked_to(0.7 * cap - 0.30 - bound / 2)
        self.assertLess(0.7 * cap - 0.30 - bound / 2, 0.7 * cap)
        self.assertLessEqual(0.7 * cap + bound / 2, cap - 1.0,
                             "inside the real non-urgent class's C - R")
        got = self.serve()
        self.assertIsNone(got["wake"])
        b = self.fresh(b)
        self.assert_no_call(code="deep_share", got=b.skipped_reason)
        self.assertEqual(b.status, "skipped")
        c = self.routed([W7], orc=self.live(), score=MATERIAL)
        self.assertEqual((c.status, c.skipped_reason),
                         ("skipped", "deep_share"), "admission holds it too")
        self.assert_no_call()
        entry = list(OrcJournal.objects.filter(orc_id=c.orc_id,
                                               kind="budget", wake=c))
        self.assertEqual([e.headline for e in entry], [
            "Answered by code: the deep-tier share of the Orcs line is "
            "used."])
        self.assertNotIn("$", entry[0].headline)
        self.assertEqual(entry[0].body["rung"], "r2")
        # a real-money urgent wake is exempt (D30): read, one request
        d = self.routed([W4], orc=self.live(), score=MATERIAL)
        self.assertEqual((d.status, d.components["rung"]), ("pending", "r2"))
        got = self.serve(script=fake_answer(answer(),
                                            model=self.model("r2")))
        self.assertEqual(got["wake"].pk, d.pk)
        self.assert_one_call()
        self.assertEqual(self.fresh(d).status, "done")
        self.assertEqual(scheduler.money_code(
            real=True, urgent=False, bound=bound, tier="deep",
            purse={"cap": cap, "spent": 0.7 * cap - 0.30 - bound / 2,
                   "inflight": 0.30, "floor": 3.0, "deep_share": 0.7}),
            "deep_share")

    def test_the_balanced_tier_and_an_urgent_real_wake_pass_the_share(self):
        """The mirror holds the deep tiers only (deep, frontier), and
        exempts a real-money urgent wake only: the same purse refuses a
        real non-urgent wake on the deep or frontier tier and a ticket
        with `deep_share`, stops a paper one at its triage first, and
        passes the balanced and fast tiers and a real-money urgent wake."""
        from bot_program.orcs import scheduler
        purse = {"cap": 10.0, "spent": 6.5, "inflight": 0.2, "floor": 3.0,
                 "deep_share": 0.7}
        for tier, real, urgent, code in (
                ("deep", True, False, "deep_share"),
                ("frontier", True, False, "deep_share"),
                ("deep", True, True, ""),
                ("balanced", True, False, ""),
                ("fast", True, False, "")):
            with self.subTest(tier=tier, urgent=urgent):
                self.assertEqual(scheduler.money_code(
                    real=real, urgent=urgent, bound=0.5, tier=tier,
                    purse=purse), code)
        # paper's ceilings sit below 70%: the triage answers first
        self.assertEqual(scheduler.money_code(
            real=False, urgent=True, bound=0.5, tier="deep", purse=purse),
            "triage")
        # a ticket of the smoke's class is never exempt
        self.assertEqual(scheduler.class_money_code(
            "real", bound=0.5, purse=purse, tier="deep"), "deep_share")

    def test_a_smoke_ticket_on_r2_is_held_to_the_deep_share(self):
        """A.57 with B.13: reserve_ticket weighs the deep share for an r2
        ticket (no fallback, never exempt): refused by code with nothing
        held; the same line reserves an r0 ticket."""
        from bot_program.orcs import mind, scheduler
        tokens = 10000
        bound = mind.ticket_price("r2", tokens)["bound"]
        self.booked_to(0.7 * 6.0 - bound / 2)
        got = scheduler.reserve_ticket("smoke", {
            "rung": "r2", "tokens": tokens, "orc": self.orc.pk,
            "ref": f"Orc:{self.orc.pk}:Smoke:0:r2"})
        self.assertEqual((got["ok"], got["code"], got["tier"]),
                         (False, "deep_share", "deep"))
        self.assertEqual(self.tickets(), {})
        ok = scheduler.reserve_ticket("smoke", {
            "rung": "r0", "tokens": tokens, "orc": self.orc.pk,
            "ref": f"Orc:{self.orc.pk}:Smoke:0:r0"})
        self.assertTrue(ok["ok"])
        self.assertEqual(list(self.tickets()), [ok["key"]])


class TheFallbackTests(_Routed):
    """B.14: only a real-money wake on r2-r5 sends the list form, the
    fallback's id read from the catalog; its bound adds the fallback's
    own. Paper and demo wakes and every ticket (the smoke) send none."""

    def test_the_id_comes_from_the_catalog_and_the_bound_adds_its_own(self):
        from ai_agents import catalog

        from bot_program.orcs import mind_gateway
        fb = catalog.ORC_FALLBACK_V1
        self.assertIn(fb, catalog.MODELS)
        self.assertEqual(catalog.MODELS[fb]["tier_hint"], "deep")
        self.assertTrue(catalog.supports_per_message_effort(fb))
        for rung in ("r2", "r3", "r4"):
            self.assertEqual(catalog.server_fallback(
                mind_gateway.rung(rung)["model"]), "both",
                "the list form is a valid request on the rung's model")
        self.assertEqual(mind_gateway.fallback_list("wake", "r2", True),
                         [{"model": fb, "max_tokens": 8000}])
        for caller, rung, real in (
                ("wake", "r0", True), ("wake", "r1", True),
                ("wake", "h0", True), ("wake", "r2", False),
                ("wake", "r3", False), ("smoke", "r2", True),
                ("smoke", "r4", True)):
            with self.subTest(caller=caller, rung=rung, real=real):
                self.assertIsNone(mind_gateway.fallback_list(caller, rung,
                                                             real))
        # §2.2 at O1's end-of-day estimate: r2 $1.05, r3 $1.21, r4 $1.37
        # (ceil(21,640 x 1.35) is 29,214 exactly: integers, never a float)
        est = 21640
        written = -(-est * 135 // 100)
        self.assertEqual(written, 29214)
        own = catalog.cost_usd(fb, input_tokens=0, output_tokens=8000,
                               cache_write_1h=written)
        self.assertAlmostEqual(own, 0.4921, places=4)
        for rung, total in (("r2", 1.05), ("r3", 1.21), ("r4", 1.37)):
            with self.subTest(rung=rung):
                plain = mind_gateway.bound(rung, est)
                both = mind_gateway.bound(rung, est, fallback=True)
                self.assertAlmostEqual(both, plain + own, places=9)
                self.assertEqual(round(both, 2), total)
        self.assertEqual(mind_gateway.bound("r0", est, fallback=False),
                         mind_gateway.bound("r0", est))

    def test_a_real_r2_wake_sends_the_list_form(self):
        from ai_agents.catalog import ORC_FALLBACK_V1

        from bot_program.orcs import mind_gateway
        self.router()
        w = self.routed([W4], orc=self.live(), score=MATERIAL)
        self.assertEqual((w.components["rung"], w.components["fallback"]),
                         ("r2", True))
        got = self.serve(script=fake_answer(answer(),
                                            model=self.model("r2")))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        sent = self.requests[-1]
        self.assertEqual(sent.path, "beta")
        self.assertEqual(sent.kwargs["fallbacks"],
                         [{"model": ORC_FALLBACK_V1, "max_tokens": 8000}])
        self.assertAlmostEqual(
            _gateway_asks(self)[-1].kwargs["estimated_usd"],
            mind_gateway.bound("r2", w.components["tokens"], fallback=True),
            places=6)

    def test_a_paper_r3_wake_and_the_smoke_send_none(self):
        from bot_program.orcs import mind_gateway
        _verdicts(sonnet="pass", opus="pass")
        self.router()
        w = self.routed([W4], orc=self.orcs(1)[0], score=COMPLEX)
        self.assertEqual((w.components["rung"], w.components["fallback"]),
                         ("r3", False))
        self.assertAlmostEqual(w.components["bound"], mind_gateway.bound(
            "r3", w.components["tokens"]), places=6)
        got = self.serve(script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assertNotIn("fallbacks", self.requests[-1].kwargs)
        # the smoke of a real-money Orc's stored dossier, on r2: none
        live = self.live()
        self.routed([W4], orc=live, score=MATERIAL)
        self.use_fake(fake_answer(answer()))
        self.smoke(live, "--rung", "r2", "--yes")
        self.assert_one_call()
        self.assertEqual(self.requests[-1].kwargs["model"], self.model("r2"))
        self.assertNotIn("fallbacks", self.requests[-1].kwargs)

    def test_a_served_fallbacks_model_lands_on_the_wake_and_the_decision(
            self):
        from ai_agents.catalog import ORC_FALLBACK_V1
        from ai_agents.models import AgentTask

        from bot_program.orcs.models import OrcJournal
        self.router()
        live = self.live()
        w = self.routed([W4], orc=live, score=MATERIAL)
        got = self.serve(script=fake_answer(answer(), model=ORC_FALLBACK_V1))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        w = self.fresh(w)
        self.assertEqual((w.status, w.model), ("done", ORC_FALLBACK_V1))
        decision = OrcJournal.objects.get(kind="decision", wake=w)
        self.assertEqual((decision.model, decision.body["rung"]),
                         (ORC_FALLBACK_V1, "r2"))
        task = AgentTask.objects.get(
            structured_output__source_ref=f"Orc:{live.pk}:Wake:{w.pk}:r2")
        self.assertEqual((task.model, task.structured_output["asked_model"]),
                         (ORC_FALLBACK_V1, self.model("r2")))
        live.refresh_from_db()
        self.assertEqual(live.card["intellect"]["rung_t"],
                         "r2 · deep tier, medium effort")


class TheRoutedCardTests(_Routed):
    """B.7, U-R31: the card's rung is the answering rung in tier words,
    never a model id or a cost."""

    def test_rung_t_is_the_answering_rung_in_tier_words(self):
        from bot_program.orcs import notes
        self.router()
        live = self.live()
        w = self.routed([W4], orc=live)
        self.assertEqual(w.components["rung"], "r2")
        got = self.serve(script=fake_answer(answer(),
                                            model=self.model("r2")))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        live.refresh_from_db()
        self.assertEqual(live.card["intellect"]["rung_t"],
                         "r2 · deep tier, medium effort")
        for minds in (True, False):
            sl = notes.slot(live, trade=live.root_trade, minds=minds)
            self.assertEqual(sl["intellect"]["rung_t"],
                             "r2 · deep tier, medium effort")
            self.assertFalse(_keys(sl) & MONEY_KEYS, _keys(sl) & MONEY_KEYS)
            text = json.dumps(sl, ensure_ascii=False, default=str).lower()
            for word in _model_words() + ["sonnet", "opus", "haiku",
                                          "fable"]:
                self.assertNotIn(word, text)
            self.assertNotIn("$", text)


class NoAccountFigureInARoutedRequestTests(_Routed):
    """K-B10 (N6): the walk over every request a routed wake sends."""

    def test_no_account_figure_in_any_routed_request(self):
        """The fixture's Orc carries the distinctive figures; with both
        PASSes and the router ON its wakes answer on r0, r1 and r3, a real
        one on r2 with its fallback named."""
        _verdicts(sonnet="pass", opus="pass")
        self.router()
        rungs = []
        for n, (orc, score) in enumerate(((self.orc, ROUTINE),
                                          (self.orc, MATERIAL),
                                          (self.orc, COMPLEX),
                                          (self.live(), MATERIAL))):
            w = self.routed([_urgent(n + 1)], orc=orc, score=score)
            rungs.append(w.components["rung"])
            got = self.serve(script=fake_answer(answer()))
            self.assertEqual(got["wake"].pk, w.pk)
            self.assert_one_call()
        self.assertEqual(rungs, ["r0", "r1", "r3", "r2"])
        self.assertEqual(len(self.requests), 4)
        self.assert_no_account_figure()


# ── the smoke (B.15a, A.60, P34, P35) ────────────────────────────────────

class TheRoutedSmokeTests(_Routed):
    """`orcs smoke --rung` takes the wake's rungs under a wake's gates: the
    four, and the router's switch for a rung above r0; B.5's map; no
    fallback; never r5."""

    def test_a_routed_rung_is_refused_with_the_router_off_no_call(self):
        """ON: one call on r2's model, its whole bound reserved and
        released, no fallback; OFF: refused before anything is reserved,
        no request."""
        from bot_program.orcs import mind, mind_gateway
        w = self.rendered()
        self.router()
        self.use_fake(fake_answer(answer()))
        out = self.smoke(self.orc, "--rung", "r2", "--yes")
        self.assert_one_call()
        sent = self.requests[-1].kwargs
        self.assertEqual(sent["model"], self.model("r2"))
        self.assertNotIn("fallbacks", sent)
        self.assertIn(f"Orc:{self.orc.pk}:Smoke:{w.pk}:r2", out)
        self.assertAlmostEqual(
            _gateway_asks(self)[-1].kwargs["estimated_usd"],
            mind_gateway.bound("r2", mind.ticket_tokens(w, "r2")), places=6)
        self.assertEqual(self.tickets(), {})
        self.router(False)
        with self.assertRaises(CommandError) as cm:
            self.smoke(self.orc, "--rung", "r2", "--yes")
        self.assertIn("(orcs_router)", str(cm.exception))
        self.assertIn("Nothing was reserved or sent", str(cm.exception))
        self.assert_no_call()
        self.assertEqual(self.tickets(), {})
        # r0 and h0 need no router
        self.smoke(self.orc, "--yes")
        self.assert_one_call()

    def test_r1_answers_as_r0_without_the_pass_both_rungs_printed(self):
        from bot_program.orcs.models import OrcSetting
        w = self.rendered()
        self.router()
        dry = self.smoke(self.orc, "--rung", "r1")
        self.assertIn("rung r1, answered as r0 (one effort per model until "
                      "the smoke's PASS for the sonnet family)", dry)
        self.assertIn("DRY RUN", dry)
        self.assertEqual(self.tickets(), {})
        self.use_fake(fake_answer(answer()))
        out = self.smoke(self.orc, "--rung", "r1", "--yes")
        self.assert_one_call()
        sent = self.requests[-1].kwargs
        self.assertEqual((sent["model"], sent["output_config"]["effort"]),
                         (self.model("r0"), "low"))
        self.assertIn(f"Orc:{self.orc.pk}:Smoke:{w.pk}:r0", out)
        _verdicts(sonnet="pass")
        out = self.smoke(self.orc, "--rung", "r1", "--yes")
        self.assert_one_call()
        sent = self.requests[-1].kwargs
        turn = [m for m in sent["messages"] if m.get("role") == "system"]
        self.assertEqual([m["output_config"]["effort"] for m in turn],
                         ["high"], "r1 at its own effort after the PASS")
        self.assertIn(f"Orc:{self.orc.pk}:Smoke:{w.pk}:r1", out)
        self.assertIn("The call: rung r1, the sonnet family", out)
        self.assertIsNotNone(OrcSetting.get("smoke_verdict"))

    def test_r5_is_refused_and_the_smoke_stays_dry_by_default(self):
        self.rendered()
        self.router()
        self.use_fake(fake_answer(answer()))
        self.smoke(self.orc, "--yes")
        self.assert_one_call()
        for rung in ("r5", "x9"):
            with self.subTest(rung=rung), \
                    self.assertRaises(CommandError) as cm:
                self.smoke(self.orc, "--rung", rung, "--yes")
            self.assertIn(f"rung {rung!r}", str(cm.exception))
        dry = self.smoke(self.orc, "--rung", "r4")
        self.assertIn("DRY RUN", dry)
        self.assertIn("rung r4, answered as r2", dry)
        self.assert_no_call()
        self.assertEqual(self.tickets(), {})


# ── /ai-models/ (B.16a, U-R6, K/D-A4) ────────────────────────────────────

class TheAiModelsCardTests(_Routed):

    def setUp(self):
        super().setUp()
        staff = get_user_model().objects.create_user(
            "o2b_routed_staff", password="x", is_staff=True)
        self.client.force_login(staff)

    def card(self) -> str:
        from html import unescape
        html = unescape(self.client.get("/ai-models/").content.decode())
        return html.split("The Orcs (read-only)", 1)[1].split(
            "Catalog</span>", 1)[0]

    @staticmethod
    def cells(card) -> dict:
        """{rung: (calls today, would route today)} from the ladder."""
        out = {}
        for rung, calls, would in re.findall(
                r'<tr data-rung="([a-z]\d)">.*?'
                r'<td data-label="Calls today">(\d+)</td>\s*'
                r'<td data-label="Would route today">(\d+)</td>',
                card, re.S):
            out[rung] = (int(calls), int(would))
        return out

    def test_the_cards_sentence_reads_the_router_switch(self):
        from ai_agents.catalog import ORC_LADDER_V1
        text = " ".join(self.card().split())
        self.assertIn(SAID_OFF, text)
        self.assertNotIn(SAID_ON, text)
        self.assertIn("an unvalidated prior", text)
        for stale in ("a router comes with O2b", "O2a answers every wake",
                      "will pin"):
            self.assertNotIn(stale, text)
        for step in ORC_LADDER_V1:
            self.assertIn(step["note"], text, "the ladder's notes (K/D-A4)")
        self.router()
        text = " ".join(self.card().split())
        self.assertIn(SAID_ON, text)
        self.assertNotIn(SAID_OFF, text)
        self.assertIn("an unvalidated prior", text)

    def test_each_rung_shows_todays_calls_and_would_counts(self):
        """Calls: the Orcs line's ledger rows since 00:00 UTC, by the rung
        in their source_ref (a core row and yesterday's aside). Would: the
        wakes rendered since 00:00 UTC by the router's choice (a quiet or
        merged wake aside, and yesterday's)."""
        from ai_agents.models import AgentTask

        from bot_program.orcs.models import OrcWake
        yesterday = timezone.now() - timedelta(days=1, hours=1)
        for ref, agent in (("Orc:1:Wake:2:r2", "orc"),
                           ("Orc:1:Wake:3:r2", "orc"),
                           ("Orc:1:Wake:4:r0", "orc"),
                           ("Orc:1:Smoke:5:h0", "orc"),
                           ("Orc:1:Wake:6:r3", "orc"),
                           ("", "research")):
            AgentTask.objects.create(
                agent=agent, provider="claude", model="m",
                prompt_summary="x", cost_usd=Decimal("0.01"),
                structured_output={"source_ref": ref} if ref else {})
        old = AgentTask.objects.get(structured_output__source_ref=(
            "Orc:1:Wake:6:r3"))
        AgentTask.objects.filter(pk=old.pk).update(created_at=yesterday)

        def wake(n, would, status="skipped"):
            return OrcWake.objects.create(
                orc=self.orc, reasons=[], dedupe_key=f"would{n}",
                status=status, kind="material", components={"route": {
                    "rung": would, "would_rung": would, "why": [],
                    "version": "table-v1"}})
        wake(1, "r3")
        wake(2, "r3")
        wake(3, "r1", status="done")
        wake(4, "r4", status="quiet")
        wake(5, "r4", status="merged")
        stale = wake(6, "r2")
        OrcWake.objects.filter(pk=stale.pk).update(created_at=yesterday)
        cells = self.cells(self.card())
        self.assertEqual(sorted(cells), ["h0", "r0", "r1", "r2", "r3", "r4",
                                         "r5"])
        self.assertEqual(cells, {"h0": (1, 0), "r0": (1, 0), "r1": (0, 1),
                                 "r2": (2, 0), "r3": (0, 2), "r4": (0, 0),
                                 "r5": (0, 0)})


# ── the RUNBOOK (K-R8, U-R6, U-R31) ─────────────────────────────────────

class TheRouterRunbookTests(MindTestCase):

    def test_the_runbook_says_how_to_turn_the_router_on_and_off(self):
        text = RUNBOOK.read_text(encoding="utf-8")
        head = "### The Orcs' router (O2b)"
        self.assertIn(head, text)
        start = text.index(head)
        section = " ".join(text[start:text.index("## Operating notes",
                                                 start)].split())
        for words in ("`orcs_router`", NAME, "/ops/", "trading PIN",
                      "orcs smoke-verdict --family opus --pass",
                      "ORC_DAILY_BUDGET_USD=10", "`AI_DAILY_BUDGET_USD` to 28",
                      "one effort per model until the smoke's PASS",
                      "r2 · deep tier, medium effort",
                      "at the next claim", "takes no PIN",
                      "$5.88 to $11.48", "$1.37", "70%"):
            self.assertIn(words, section)
        self.assertLess(section.index("1. Record the smoke's PASS"),
                        section.index("3. On /ops/"),
                        "the PASS is recorded first")
        # A.55, §4 Q8 (2026-11-06, completing O2b): a long Opus call is a
        # busy worker, never a silent one
        self.assertIn("An Opus call may run past 30 minutes inside its "
                      "wall time (about 36 minutes on r3, 58 on r4): a "
                      "wake that waits behind it, its own Orc's next wake "
                      "included, is answered by code as a backlog after 30 "
                      "minutes, and no Orc goes to the care for that wait.",
                      section)
        self.assertNotIn("component on orcs_router", text)
        # K-R8: the verdict the router assumes until one is recorded
        smoke = " ".join(text.split("**The provider smoke.**", 1)[1].split(
            "---", 1)[0].split())
        self.assertIn("The Orcs' router assumes a FAIL until a PASS is "
                      "recorded for the family", smoke)
        # U-R31: the Horde names the rung that answered in tier words
        self.assertIn('"r2 · deep tier, medium effort"', " ".join(
            text.split("**The Horde.**", 1)[1].split("\n- **", 1)[0]
            .split()))
