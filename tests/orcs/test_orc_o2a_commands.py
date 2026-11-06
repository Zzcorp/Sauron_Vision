"""T14, THE ORCS' COMMANDS FOR THE MINDS (the O2 spec A.59-A.61, P34, P35,
N3's one exception, §1.1.7 T14 and A.59's lines; 2026-11-05).

- `orcs smoke --row ROOT`: dry by default (the rung, the family, the
  tokens, the bound, the line's answer, the gates); `--yes` refused while
  any of the four gates is off; only the smoke's rungs (r0, h0; from O2b
  the wake's r1-r4 too, refused while the router's switch is off); a ticket
  reserved and the whole bound asked of the line; ONE send, billed on the
  Orcs line (agent orc, source_ref Orc:<pk>:Smoke:<wake>:<rung>); the
  answer and its validation printed; nothing written to the Orc
- `orcs smoke-verdict`: {verdict, reasons, at} per family, as the effort
  rule reads it; nothing sent
- `orcs tokens --s`: dry by default; `--yes` counts S at the provider's
  free endpoint through the gateway, with the line at 0 and every switch
  off, and needs the API key; never a messages request
- `orcs` (status): the minds switch, the line, the model calls today, the
  queue, the money held, the stall alarm, the breaker, the ledger gaps
- `orcs dossier ROOT`: S by its stored hash, the answer with each V-rule's
  verdict, the officer's verdicts and the booking
- the tickets (A.57), on the scheduler: a caller outside §1.0.9 or a rung
  outside its list raises before anything is held; a request above its
  cap is refused by code; the class's ceiling and the core's floor refuse
  with no call; one billed attempt per item, a budget refusal waiting at
  most to the next UTC day; the settle releases once the ledger row is
  found, else holds until 00:00 UTC; a ticket past its wall time becomes
  an orphan hold

Every call goes to the real provider on the fake client, proven sent from
inside mind_gateway.call after the Orcs line answered (tests/orcs/
helpers_o2.py).

Run with:  python manage.py test tests.orcs.test_orc_o2a_commands
"""
import json
import os
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from tests.orcs.helpers import _switch
from tests.orcs.test_orc_o2a_call import NOW, MindFixture, answer
from tests.orcs.helpers_o2 import fake_answer, fake_usage

KEY = {"ANTHROPIC_API_KEY": "sk-test-not-a-key"}


def _orcs(*args) -> str:
    out = StringIO()
    call_command("orcs", *args, stdout=out)
    return out.getvalue()


class CommandFixture(MindFixture):

    def smoke(self, *args) -> str:
        return _orcs("smoke", "--row", str(self.row.pk), *args)

    def tickets(self) -> dict:
        from bot_program.orcs.models import OrcSetting
        return {k: v for k, v in (OrcSetting.get("minds_inflight") or {})
                .items() if isinstance(v, dict) and v.get("kind") == "ticket"}


# ── the smoke (A.60) ─────────────────────────────────────────────────────

class TheSmokeTests(CommandFixture):

    def test_the_smoke_is_dry_by_default(self):
        """Without --yes it prints the plan and reserves nothing; the same
        command with --yes is the pair's positive control."""
        from bot_program.orcs import mind, mind_gateway
        w = self.rendered()
        self.use_fake(fake_answer(answer()))
        self.smoke("--yes")
        self.assert_one_call()
        dry = self.smoke()
        self.assert_no_call()
        bound = mind_gateway.bound("r0", mind.ticket_tokens(w, "r0"))
        for words in ("rung r0", "sonnet", f"wake #{w.pk}",
                      f"bound ${bound:.4f}", "The Orcs line", "allowed",
                      "The four gates", "DRY RUN"):
            self.assertIn(words, dry)
        self.assertEqual(self.tickets(), {})

    def test_yes_is_refused_while_any_gate_is_off(self):
        self.rendered()
        self.smoke("--yes")
        self.assert_one_call()
        for key, code in (("platform_master", "platform_off"),
                          ("orcs_minds", "minds_off"), ("orcs", "orcs_off")):
            _switch(key, False)
            with self.subTest(gate=key), \
                    self.assertRaises(CommandError) as cm:
                self.smoke("--yes")
            self.assertIn(f"({code})", str(cm.exception))
            _switch(key, True)
        with override_settings(AI_CONFIG={**settings.AI_CONFIG,
                                          "orc_daily_budget_usd": 0.0}), \
                self.assertRaises(CommandError) as cm:
            self.smoke("--yes")
        self.assertIn("(line_off)", str(cm.exception))
        self.assert_no_call()
        self.assertEqual(self.tickets(), {})

    def test_only_the_smokes_rungs_are_accepted(self):
        """P35: r5 and a rung off the ladder are refused before anything
        is reserved or sent; Fable cannot be reached; h0 is the smoke's
        rung beside r0. Changed on purpose (2026-11-06, O2b B.15a): the
        smoke takes the wake's rungs r1-r4 too, under a wake's gates, so
        with the router's switch (orcs_router) OFF, as it ships, each is
        refused with nothing reserved or sent
        (tests/orcs/test_orc_o2b_routed.py sends one with it ON)."""
        from ai_agents.models import AgentTask

        from bot_program.orcs import mind_gateway
        w = self.rendered()
        self.smoke("--yes")
        self.assert_one_call()
        for rung in ("r5", "x9"):
            with self.subTest(rung=rung), \
                    self.assertRaises(CommandError) as cm:
                self.smoke("--rung", rung, "--yes")
            self.assertIn(f"rung {rung!r}", str(cm.exception))
        for rung in ("r1", "r2", "r3", "r4"):
            with self.subTest(rung=rung), \
                    self.assertRaises(CommandError) as cm:
                self.smoke("--rung", rung, "--yes")
            self.assertIn(f"rung {rung}", str(cm.exception))
            self.assertIn("(orcs_router)", str(cm.exception))
        self.assert_no_call()
        self.assertEqual(self.tickets(), {})
        self.smoke("--rung", "h0", "--yes")
        self.assert_one_call()
        self.assertEqual(self.requests[-1].kwargs["model"],
                         mind_gateway.rung("h0")["model"])
        refs = list(AgentTask.objects.order_by("id").values_list(
            "structured_output__source_ref", flat=True))
        self.assertEqual(refs[-1], f"Orc:{self.orc.pk}:Smoke:{w.pk}:h0")

    def test_the_whole_bound_is_asked_and_the_one_send_bills_the_line(self):
        """A.60, A.57, A.20: a ticket, the line asked for its whole bound
        (its own reservation never counted twice), one send with
        max_attempts=1, agent orc on the Orcs line; the ticket released
        once the ledger row is found."""
        from ai_agents import spend
        from ai_agents.models import AgentTask
        from ai_agents.providers.claude_provider import ClaudeProvider

        from bot_program.orcs import mind, mind_gateway
        w = self.rendered()
        bound = mind_gateway.bound("r0", mind.ticket_tokens(w, "r0"))
        seen = []
        real = ClaudeProvider.complete

        def spy(provider, *args, **kwargs):
            seen.append(kwargs)
            return real(provider, *args, **kwargs)
        self.use_fake(fake_answer(answer(), usage=fake_usage(
            input_tokens=9000, output_tokens=600, cache_write_1h=5000)))
        with patch.object(ClaudeProvider, "complete", spy):
            out = self.smoke("--yes")
        self.assert_one_call()
        asked = [c for c in self.spend_calls if c.gateway is not None]
        self.assertEqual(len(asked), 1)
        self.assertEqual(asked[0].kwargs["line"], "orcs")
        self.assertAlmostEqual(asked[0].kwargs["estimated_usd"], bound,
                               places=9)
        ref = f"Orc:{self.orc.pk}:Smoke:{w.pk}:r0"
        self.assertEqual(
            {k: seen[0][k] for k in ("agent_name", "record", "line",
                                     "client_refusal_rerun", "max_attempts",
                                     "max_tokens", "source_ref")},
            {"agent_name": "orc", "record": True, "line": "orcs",
             "client_refusal_rerun": False, "max_attempts": 1,
             "max_tokens": 8000, "source_ref": ref})
        row_ = AgentTask.objects.get()
        self.assertEqual((row_.agent, row_.structured_output["source_ref"]),
                         ("orc", ref))
        self.assertAlmostEqual(spend.spent_today("orcs"),
                               float(row_.cost_usd), places=6)
        self.assertEqual(self.tickets(), {}, "released after the lookup")
        self.assertIn(ref, out)

    def test_nothing_is_written_to_the_orc(self):
        """A.60: no journal entry, no plan, no intent, no counter, and the
        wake as it was."""
        from bot_program.orcs.models import Orc, OrcIntent, OrcJournal, \
            OrcWake
        w = self.rendered()

        def snap():
            o = Orc.objects.get(pk=self.orc.pk)
            wk = OrcWake.objects.get(pk=w.pk)
            return (json.dumps({f.attname: getattr(o, f.attname)
                                for f in Orc._meta.concrete_fields},
                               default=str, sort_keys=True),
                    json.dumps({f.attname: getattr(wk, f.attname)
                                for f in OrcWake._meta.concrete_fields},
                               default=str, sort_keys=True),
                    OrcJournal.objects.filter(orc=self.orc).count(),
                    OrcIntent.objects.count())
        before = snap()
        self.use_fake(fake_answer(answer(action="revise_plan",
                                         facts_cited=["F1"])))
        self.smoke("--yes")
        self.assert_one_call()
        self.assertEqual(snap(), before)

    def test_the_answer_and_its_validation_are_printed(self):
        self.rendered()
        self.use_fake(fake_answer(answer()))
        out = self.smoke("--yes")
        self.assert_one_call()
        self.assertIn("The answer, as kept:", out)
        self.assertIn('"action": "hold"', out)
        self.assertIn("The validation: done", out)
        self.assertIn("V1 pass", out)
        self.assertIn("Booked:", out)
        self.assertIn("Nothing was written to the Orc", out)

    def test_a_row_with_no_stored_dossier_is_refused(self):
        from bot_program.orcs.models import OrcWake
        with self.assertRaises(CommandError) as cm:
            self.smoke()
        self.assertIn("no wake with a stored dossier", str(cm.exception))
        self.rendered()
        OrcWake.objects.update(components={})
        with self.assertRaises(CommandError):
            self.smoke("--yes")
        with self.assertRaises(CommandError) as cm:
            _orcs("smoke", "--row", "999999")
        self.assertIn("No Orc", str(cm.exception))
        self.assertEqual(self.tickets(), {})


# ── smoke-verdict and tokens (A.61) ──────────────────────────────────────

class TheVerdictAndTokensTests(CommandFixture):

    def test_smoke_verdict_stores_one_verdict_per_family(self):
        from bot_program.orcs import mind
        from bot_program.orcs.models import OrcSetting
        self.think(self.claim(self.rendered()), fake_answer(answer()))
        self.assert_one_call()
        out = _orcs("smoke-verdict", "--family", "sonnet", "--pass")
        _orcs("smoke-verdict", "--family", "opus", "--fail", "effort",
              "cache")
        self.assert_no_call()
        v = OrcSetting.get("smoke_verdict")
        self.assertEqual(set(v), {"sonnet", "opus"})
        self.assertEqual((v["sonnet"]["verdict"], v["sonnet"]["reasons"]),
                         ("pass", []))
        self.assertEqual((v["opus"]["verdict"], v["opus"]["reasons"]),
                         ("fail", ["effort", "cache"]))
        for family in ("sonnet", "opus"):
            self.assertIsNotNone(parse_datetime(v[family]["at"]))
        self.assertIn("sonnet", out)
        self.assertTrue(mind.smoke_pass("sonnet"))
        self.assertFalse(mind.smoke_pass("opus"))
        self.assertIn("turn_effort", mind.efforts("r0"),
                      "the effort rule reads it")
        _orcs("smoke-verdict", "--family", "sonnet", "--fail", "effort")
        self.assertFalse(mind.smoke_pass("sonnet"), "the newest verdict")
        self.assertEqual(mind.efforts("r0"), {"effort": "low"})
        for args in ((), ("--family", "sonnet"),
                     ("--family", "sonnet", "--pass", "--fail", "cache"),
                     ("--family", "gpt", "--pass")):
            with self.subTest(args=args), self.assertRaises(CommandError):
                _orcs("smoke-verdict", *args)
        with self.assertRaises((CommandError, SystemExit)):
            _orcs("smoke-verdict", "--family", "opus", "--fail", "speed")

    def test_tokens_counts_s_once_with_the_line_at_0_and_the_switches_off(
            self):
        """N3's one exception: one count request through the gateway's
        measure_tokens, never complete(), stored in s_tokens; the dry run
        counts nothing."""
        from bot_program.orcs import doctrine
        from bot_program.orcs.models import OrcSetting
        self.think(self.claim(self.rendered()), fake_answer(answer()))
        self.assert_one_call()
        for key in ("platform_master", "orcs", "orcs_minds"):
            _switch(key, False)
        with override_settings(AI_CONFIG={**settings.AI_CONFIG,
                                          "orc_daily_budget_usd": 0.0}), \
                patch.dict(os.environ, KEY):
            dry = _orcs("tokens", "--s")
            out = _orcs("tokens", "--s", "--yes")
        self.assertEqual(len(self.count_requests), 1, "the dry run counts "
                         "nothing")
        self.assert_no_call()
        self.assertIn("DRY RUN", dry)
        self.assertIn(doctrine.S, self.count_requests[0].texts())
        self.assertIn("measure_tokens",
                      [f.name for f in self.count_requests[0].stack])
        s = OrcSetting.get("s_tokens")
        self.assertEqual((s["version"], s["family"], s["tokens"]),
                         ("s1", "sonnet", self.fake.count_answer))
        self.assertEqual(s["chars"], len(doctrine.S))
        self.assertIsNotNone(parse_datetime(s["at"]))
        self.assertIn(str(self.fake.count_answer), out)

    def test_tokens_needs_the_api_key_and_the_s_flag(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}), \
                self.assertRaises(CommandError) as cm:
            _orcs("tokens", "--s", "--yes")
        self.assertIn("API key", str(cm.exception))
        with self.assertRaises(CommandError):
            _orcs("tokens", "--yes")
        with patch.dict(os.environ, KEY):
            _orcs("tokens", "--s", "--yes")
        self.assertEqual(len(self.count_requests), 1, "the refused runs "
                         "counted nothing")


# ── status and dossier (A.59) ────────────────────────────────────────────

class TheStatusAndDossierTests(CommandFixture):

    def test_status_shows_the_minds_the_line_and_the_money_held(self):
        from bot_program.orcs import scheduler
        from bot_program.orcs.models import Orc, OrcSetting, OrcWake
        now = timezone.now()
        out = _orcs()
        for line in ("The orcs switch is ON.",
                     "The minds switch (orcs_minds) is ON.",
                     "The Orcs line: $0.00 of $6.00 today.",
                     "Model calls today: 0.",
                     "Wakes waiting for a model: 0 pending, 0 running; 0 "
                     "answered by code after a backlog today.",
                     "Held for calls without a bill: $0.00.",
                     "Tickets in flight: none.",
                     "The stall alarm is quiet.",
                     "The breaker is closed.", "Ledger gaps: none."):
            self.assertIn(line, out)
        w = self.rendered()
        OrcWake.objects.filter(pk=w.pk).update(
            status="pending", dedupe_key=f"orc{self.orc.pk}:pending",
            queued_at=now - timedelta(minutes=25))
        OrcWake.objects.create(orc=self.orc, dedupe_key="b1",
                               status="skipped", skipped_reason="backlog")
        Orc.objects.filter(pk=self.orc.pk).update(
            llm_wakes_today=3,
            seen={**(self.orc.seen or {}),
                  "counters_day": scheduler.utc_day(now)})
        until = scheduler.next_midnight(now).isoformat()
        OrcSetting.objects.update_or_create(key="minds_inflight", defaults={
            "value": {
                "w1": {"kind": "unbilled", "usd": 0.20, "until": until},
                "w2": {"kind": "orphan", "usd": 0.05, "until": until},
                "w3": {"kind": "ledger_gap", "usd": 0.10, "until": until},
                "t1": {"kind": "ticket", "usd": 0.19, "caller": "smoke",
                       "at": now.isoformat(), "wall_s": 820}}})
        OrcSetting.objects.update_or_create(key="minds_breaker", defaults={
            "value": {"until": (now + timedelta(minutes=9)).isoformat(),
                      "why": "5 model calls failed within 10 minutes",
                      "at": now.isoformat()}})
        out = _orcs()
        for line in ("Model calls today: 3.",
                     "Wakes waiting for a model: 1 pending, 0 running; 1 "
                     "answered by code after a backlog today.",
                     "Held for calls without a bill: $0.25.",
                     "Tickets in flight: 1 ($0.19).",
                     "The stall alarm: 1 wake(s) waited over 20 minutes "
                     "for a model call.",
                     "The breaker is open until",
                     "5 model calls failed within 10 minutes",
                     "Ledger gaps: 1 ($0.10 held until 00:00 UTC)."):
            self.assertIn(line, out)
        for key in ("platform_master", "orcs", "orcs_minds"):
            _switch(key, False)
        with override_settings(AI_CONFIG={**settings.AI_CONFIG,
                                          "orc_daily_budget_usd": 0.0}):
            off = _orcs()
        self.assertIn("The minds switch (orcs_minds) is OFF.", off)
        self.assertIn("The Orcs line is off (ORC_DAILY_BUDGET_USD=0).", off)

    def test_the_dossier_shows_s_the_answer_the_officer_and_the_booking(
            self):
        from bot_program.orcs import doctrine
        from bot_program.orcs.models import OrcDossierBlock, OrcIntent
        w = self.claim(self.rendered())
        self.think(w, fake_answer(answer(), usage=fake_usage(
            input_tokens=9000, output_tokens=600, cache_write_1h=5000)))
        self.assert_one_call()
        OrcIntent.objects.create(
            orc=self.orc, wake=w, kind="tighten",
            level={"level_id": "S1h-L1", "kind": "swing", "tf": "1h",
                   "price": 99.0, "stop": 98.8}, level_id="S1h-L1",
            would_stop=Decimal("98.8"), mode="shadow", status="queued",
            officer={"verdict": "allow", "rule": "", "words": ""},
            why="queued for the shadow arm", rung="r0", s_version="s1",
            schema_version="d1")
        out = _orcs("dossier", str(self.row.pk))
        s = w.components["s"]
        self.assertTrue(OrcDossierBlock.objects.filter(hash=s["hash"])
                        .exists())
        self.assertIn(f"S {s['version']}, stored as {s['hash'][:12]}", out)
        self.assertIn(doctrine.S, out)
        self.assertIn("The answer, as kept:", out)
        self.assertIn('"action": "hold"', out)
        self.assertIn("V1 pass", out)
        self.assertIn("The officer: nothing to judge", out)
        self.assertIn("Proposed in shadow: tighten to S1h-L1", out)
        self.assertIn("the officer: allow", out)
        self.assertIn("The booking:", out)
        self.assertIn("9000 in, 600 out", out)
        bare = self.rendered(at=NOW + timedelta(hours=2))
        out = _orcs("dossier", str(self.row.pk))
        self.assertIn(f"wake of {bare.created_at:%Y-%m-%d %H:%M}", out)
        self.assertIn("No model answer for this wake", out)


# ── the tickets (A.57) ───────────────────────────────────────────────────

USAGE = {"input_tokens": 10, "output_tokens": 5, "cost_usd": 0.0123}


class TheTicketTests(CommandFixture):
    """A.57 on the scheduler, with the smoke as its one caller in O2a: the
    callers of §1.0.9 only, the request's cap, the ceiling and the floor,
    one billed attempt per item, the settle and the wall time."""

    def reserve(self, *, item="", tokens=1000, rung="r0", now=None):
        from bot_program.orcs import scheduler
        return scheduler.reserve_ticket("smoke", {
            "rung": rung, "tokens": tokens, "item": item, "orc": self.orc.pk,
            "ref": f"Orc:{self.orc.pk}:Smoke:0:{rung}"}, now=now)

    @staticmethod
    def settle(key, kind, *, usage=None, ledger=None, now=None):
        from bot_program.orcs import scheduler
        return scheduler.settle_ticket(key, {
            "kind": kind, "sent": kind not in ("closed", "unsent"),
            "code": "", "usage": usage, "ledger": ledger}, now=now)

    @staticmethod
    def items() -> dict:
        from bot_program.orcs.models import OrcSetting
        return (OrcSetting.get("minds_tickets") or {}).get("items") or {}

    def test_a_caller_outside_the_table_raises_before_anything_is_held(self):
        """§1.0.9: the wake is claimed, never ticketed; a caller with no
        row yet (a Captain, a question) and a rung outside the smoke's
        raise before any lock, hold or count. Changed on purpose
        (2026-11-06, O2b B.15a): the smoke's rungs are h0 and r0-r4, so
        an unknown rung stands where r1 stood."""
        from bot_program.orcs import scheduler
        from bot_program.orcs.models import OrcSetting
        for caller, rung in (("wake", "r0"), ("captain", "r0"),
                             ("question", "r0"), ("smoke", "x9"),
                             ("smoke", "r5")):
            with self.subTest(caller=caller, rung=rung), \
                    self.assertRaises(ValueError):
                scheduler.reserve_ticket(caller, {"rung": rung,
                                                  "tokens": 1000})
        self.assertEqual(self.tickets(), {})
        self.assertIsNone(OrcSetting.get("minds_tickets"))
        self.assertTrue(self.reserve()["ok"], "the smoke's own row")

    def test_a_request_above_its_cap_is_refused_by_code(self):
        """Its request comes first: above TICKET_MAX_TOKENS, `over_budget`
        with nothing held; at the cap, the whole bound held (A.21 on the
        estimate, no fallback), counted in the line's money in flight but
        never in its own ask."""
        from bot_program.orcs import mind_gateway
        from bot_program.orcs.constants import TICKET_MAX_TOKENS, WALL_S
        cap = TICKET_MAX_TOKENS["smoke"]
        got = self.reserve(tokens=cap + 1)
        self.assertEqual((got["ok"], got["code"], got["key"]),
                         (False, "over_budget", ""))
        self.assertEqual(self.tickets(), {})
        got = self.reserve(tokens=cap)
        self.assertTrue(got["ok"])
        entry = self.tickets()[got["key"]]
        bound = mind_gateway.bound("r0", cap)
        self.assertAlmostEqual(got["bound"], bound, places=9)
        self.assertAlmostEqual(entry["usd"], bound, places=6)
        self.assertEqual((entry["caller"], entry["rung"], entry["wall_s"]),
                         ("smoke", "r0", WALL_S["r0"]))
        self.assertAlmostEqual(mind_gateway.inflight_usd(), entry["usd"],
                               places=9)
        self.assertEqual(mind_gateway.inflight_usd(exclude_key=got["key"]),
                         0.0)

    def test_the_ceiling_and_the_floor_refuse_with_no_call(self):
        """A ticket refused at its ceiling makes no call: the smoke's class
        (real non-urgent, C - R) and the core's floor, each read with the
        money in flight and held."""
        from bot_program.orcs import scheduler
        from bot_program.orcs.models import OrcSetting
        self.rendered()
        self.smoke("--yes")
        self.assert_one_call()
        until = scheduler.next_midnight(timezone.now()).isoformat()
        for usd, code in ((5.95, "triage"), (2.95, "inflight")):
            OrcSetting.objects.update_or_create(
                key="minds_inflight", defaults={"value": {"h1": {
                    "kind": "unbilled", "usd": usd, "until": until}}})
            with self.subTest(code=code), \
                    self.assertRaises(CommandError) as cm:
                self.smoke("--yes")
            self.assertIn(f"({code})", str(cm.exception))
            self.assertEqual(self.tickets(), {})
        self.assert_no_call()

    def test_one_billed_attempt_per_item(self):
        """A call with usage closes its item, billed or refused alike; a
        failure with no bill leaves one more try, then closes it; a closed
        or busy item reserves nothing."""
        a = self.reserve(item="t14:a")
        self.assertTrue(a["ok"])
        self.assertEqual(self.items()["t14:a"]["state"], "reserved")
        busy = self.reserve(item="t14:a")
        self.assertEqual((busy["ok"], busy["code"]), (False, "item_busy"))
        self.settle(a["key"], "billed", usage=USAGE, ledger=True)
        self.assertEqual(self.items()["t14:a"]["state"], "billed")
        again = self.reserve(item="t14:a")
        self.assertEqual((again["ok"], again["code"]), (False, "item_closed"))
        b = self.reserve(item="t14:b")
        self.settle(b["key"], "unbilled")
        self.assertEqual(self.items()["t14:b"]["state"], "unbilled")
        retry = self.reserve(item="t14:b")
        self.assertTrue(retry["ok"], "one more try, on the next beat")
        self.settle(retry["key"], "unbilled")
        self.assertEqual(self.items()["t14:b"]["state"], "failed")
        self.assertEqual(self.reserve(item="t14:b")["code"], "item_closed")
        self.assertEqual(sorted(e["kind"] for e in self.holds().values()
                                if e.get("item") == "t14:b"),
                         ["unbilled", "unbilled"],
                         "each try's bound held until 00:00 UTC")
        self.assertEqual(self.tickets(), {})

    def test_a_budget_refusal_waits_at_most_to_the_next_utc_day(self):
        """A budget refusal before any send leaves the item waiting: the
        same day it may reserve again; refused again by the gateway, it
        waits again; the next UTC day it closes `expired`, never sent."""
        day1 = timezone.now()
        with override_settings(AI_CONFIG={**settings.AI_CONFIG,
                                          "orc_daily_budget_usd": 0.0}):
            got = self.reserve(item="t14:c", now=day1)
        self.assertEqual((got["ok"], got["code"]), (False, "line_off"))
        self.assertEqual(self.items()["t14:c"]["state"], "waiting")
        got = self.reserve(item="t14:c", now=day1)
        self.assertTrue(got["ok"], "the same day, the line back")
        self.settle(got["key"], "closed", now=day1)
        self.assertEqual(self.items()["t14:c"]["state"], "waiting",
                         "the gateway refused: no call made")
        got = self.reserve(item="t14:c", now=day1 + timedelta(days=1))
        self.assertEqual((got["ok"], got["code"]), (False, "expired"))
        self.assertEqual(self.items()["t14:c"]["state"], "expired")
        self.assertEqual(self.tickets(), {})

    def test_the_settle_releases_once_the_ledger_row_is_found(self):
        """As A.24 releases a wake's: a bill with its ledger row releases;
        a bill without one holds the booked cost as a ledger gap; a call
        with no bill keeps its bound held; nothing sent releases. Every
        hold until 00:00 UTC, never earlier."""
        from bot_program.orcs import scheduler
        now = timezone.now()
        until = scheduler.next_midnight(now).isoformat()
        for kind, usage, ledger, held in (
                ("answer", USAGE, True, ""),
                ("answer", USAGE, False, "ledger_gap"),
                ("billed", USAGE, False, "ledger_gap"),
                ("unbilled", None, None, "unbilled"),
                ("closed", None, None, ""), ("unsent", None, None, "")):
            got = self.reserve(now=now)
            out = self.settle(got["key"], kind, usage=usage, ledger=ledger,
                              now=now)
            entry = self.holds().get(got["key"])
            with self.subTest(kind=kind, ledger=ledger):
                self.assertEqual((out["held"], out["released"]),
                                 (held, not held))
                if held:
                    self.assertEqual((entry["kind"], entry["until"]),
                                     (held, until))
                    self.assertAlmostEqual(
                        entry["usd"], USAGE["cost_usd"] if usage
                        else got["bound"], places=6)
                else:
                    self.assertIsNone(entry)
        self.assertEqual(self.tickets(), {})

    def test_a_ticket_past_its_wall_time_becomes_an_orphan_hold(self):
        """The watchdog makes a ticket past its wall time an orphan hold
        until 00:00 UTC, with its alarm: its call may still bill. Its late
        settle drops it once the bill and its ledger row are found; a late
        one with no bill leaves it held."""
        from bot_program.orcs import scheduler
        from bot_program.orcs.constants import WALL_S
        t0 = timezone.now()
        a, b = self.reserve(now=t0), self.reserve(now=t0)
        early = scheduler.watch(now=t0 + timedelta(seconds=WALL_S["r0"] - 5))
        self.assertEqual(early["minds_ticket_wall_time"], 0)
        later = t0 + timedelta(seconds=WALL_S["r0"] + 5)
        out = scheduler.watch(now=later)
        self.assertEqual(out["minds_ticket_wall_time"], 2)
        self.assertIn("2 ticket(s) ran past their wall time: their bounds "
                      "stay held until 00:00 UTC", out["reason"])
        until = scheduler.next_midnight(later).isoformat()
        for key in (a["key"], b["key"]):
            self.assertEqual((self.holds()[key]["kind"],
                              self.holds()[key]["until"]), ("orphan", until))
        self.assertEqual(self.tickets(), {})
        got = self.settle(a["key"], "answer", usage=USAGE, ledger=True,
                          now=later)
        self.assertEqual((got["late"], got["released"]), (True, True))
        got = self.settle(b["key"], "unbilled", now=later)
        self.assertEqual((got["late"], got["held"]), (True, "orphan"))
        self.assertNotIn(a["key"], self.holds())
        self.assertEqual(self.holds()[b["key"]]["kind"], "orphan")
