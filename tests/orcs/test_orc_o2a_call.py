"""T6, ONE ORC WAKE READ IN SHADOW: THE CALL (the O2 spec A.20-A.29, N3, N4,
N6, §1.1.7 T6 and its extras; 2026-11-05). Every request goes to the real
provider on the fake client (tests/orcs/helpers_o2.py): nothing reaches a
network, and every request is proven sent from inside mind_gateway.call
after the Orcs line answered allowed.

- the request: S and the shared turn byte-identical for two Orcs on one
  model; the schema the same object; the breakpoints; the effort rule
  (turn_effort only with a recorded smoke PASS); A.23's keywords,
  max_attempts=1 included; the ledger row on the Orcs line
- one send: an overloaded event mid-stream gets exactly one request and
  ends `failed` with its bound held
- the four gates, the authority and the callers' rungs: each closed gate a
  pair (one request with every gate ON, then none, with its code)
- the money: booked <= the bound at the worst usage; the ledger lookup and
  the `ledger_gap` hold; the `unbilled` hold; a row closed inside the call
  books and journals late, nothing else
- the send-back: a pending wake of the same Orc goes back to the render,
  whose PS5 holds the decision that just landed, up to journal_as_of
- measure_tokens: one count, never a messages request
- S: under its cap, byte-stable, stored as a block
- K-B10: no account figure reaches any request

Run with:  python manage.py test tests.orcs.test_orc_o2a_call
"""
import json
import re
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from tests.orcs.helpers import (_bars, _config, _inst, _on, _row, _switch,
                                _user, _wave, born)
from tests.orcs.helpers_o2 import (KB10_BALANCE, KB10_QTY, KB10_R_MONEY,
                                   MindTestCase, PreStream, fake_answer,
                                   fake_usage, mid_stream_error, minds_on)

UTC = dt_tz.utc
#: Trading day 2026-10-22: Asia and London closed, New York AM running.
NOW = datetime(2026, 10, 22, 13, 30, tzinfo=UTC)
W1 = {"code": "W1", "key": "W1", "t": "birth", "urgent": True}


def answer(**over) -> dict:
    """A complete answer of SCHEMA_V1: a hold by default."""
    out = {"action": "hold", "candidate": "none", "level_id": "none",
           "risk_share": "none", "facts_cited": [], "event_id": "none",
           "plan_clauses": [], "expectation": {"kind": "none",
                                               "level_id": "none"},
           "next_wake_min": 0, "note": "Holding: the 4h structure intact."}
    out.update(over)
    return out


class MindFixture(MindTestCase):
    """One Orc on a paper BTCUSD row, its venue's 1h and 4h bars fresh at
    NOW, a fresh quote, the day's MK built, the K-B10 figures on the
    account, the row and the Orc, and the four gates ON. A wake is
    recorded and rendered as of NOW (`rendered`), claimed by hand (the
    queue is a later commit) and read (`think`)."""

    symbol = "BTCUSD"

    def setUp(self):
        from market_data.models import LiveQuote

        from bot_program.orcs import dossier_market
        from bot_program.orcs.models import Orc
        from bot_program.orcs.sessions import trading_day
        _switch("aragorn")
        _on()
        self.user = _user(f"o2a_{type(self).__name__.lower()[:20]}")
        for sym, cls in (("EURUSD", "forex"), ("XAUUSD", "commodity"),
                         ("SPX500", "index"), ("DXY", "index")):
            _inst(sym, cls)
        inst = _inst(self.symbol, "crypto")
        _bars(self.symbol, "1h", _wave(200), start=NOW - timedelta(hours=200))
        _bars(self.symbol, "4h", _wave(200), start=NOW - timedelta(hours=800))
        q = LiveQuote.objects.create(instrument=inst, last=Decimal("100.5"),
                                     bid=Decimal("100.45"),
                                     ask=Decimal("100.55"), source="etoro")
        LiveQuote.objects.filter(pk=q.pk).update(
            updated_at=NOW - timedelta(seconds=20))
        self.cfg = _config(self.user, capital=KB10_BALANCE)
        self.row = _row(self.cfg, qty=str(KB10_QTY), symbol=self.symbol)
        self.orc = born(self, self.row, at=NOW - timedelta(hours=2))
        Orc.objects.filter(pk=self.orc.pk).update(r_money=KB10_R_MONEY)
        self.orc.refresh_from_db()
        self.row.refresh_from_db()
        dossier_market.build_day(trading_day(NOW), self._model(), now=NOW)
        minds_on(self)

    @staticmethod
    def _model():
        from bot_program.orcs import mind_gateway
        return mind_gateway.rung("r0")["model"]

    # ── the wake's life, by hand where the queue will do it ──────────────

    def rendered(self, reasons=None, *, at=NOW, orc=None):
        """record() then the render alone (the render pass's step 2, A.7),
        as of `at`: the tests that drive the merge and the admission call
        scheduler.absorb and scheduler.admit themselves (2026-11-05: the
        render pass admits since O2a's last commit)."""
        from bot_program.orcs import wake
        from bot_program.orcs.models import OrcWake
        orc = orc or self.orc
        orc.refresh_from_db()
        w = wake.record(orc, orc.root_trade, list(reasons or [W1]), now=at,
                        price="100.5")
        w = (OrcWake.objects.select_related("orc", "orc__root_trade",
                                            "orc__user").get(pk=w.pk))
        with patch("django.utils.timezone.now", return_value=at):
            wake.render_wake(w)
        return OrcWake.objects.get(pk=w.pk)

    def claim(self, w):
        """What the claim (O2a's queue) will write: running, its bound
        reserved, the rung's model, started now."""
        from bot_program.orcs import mind_gateway
        bound = mind_gateway.bound("r0", (w.components or {}).get("tokens"))
        w.status = "running"
        w.started_at = timezone.now()
        w.est_usd = Decimal(str(round(bound, 6)))
        w.model = self._model()
        w.components = {**(w.components or {}), "rung": "r0",
                        "bound": round(bound, 6)}
        w.save()
        return w

    def copy_of(self, w):
        """Another claimed wake on the same stored dossier (no new render)."""
        from bot_program.orcs.models import OrcWake
        twin = OrcWake.objects.create(
            orc_id=w.orc_id, reasons=w.reasons, dedupe_key=f"twin{w.pk}"
            f"{OrcWake.objects.count()}", kind=w.kind, status="skipped",
            components=dict(w.components or {}),
            block_hashes=list(w.block_hashes or []), score=w.score,
            band=w.band, day_class=w.day_class)
        return self.claim(twin)

    def think(self, w, *script):
        from bot_program.orcs import mind
        if script:
            self.use_fake(*script)
        return mind.think(w)

    def entries(self, **filters):
        from bot_program.orcs.models import OrcJournal
        return list(OrcJournal.objects.filter(orc=self.orc, **filters)
                    .order_by("at", "id"))

    def holds(self):
        from bot_program.orcs.models import OrcSetting
        return OrcSetting.get("minds_inflight") or {}


# ── the request ──────────────────────────────────────────────────────────

class TheRequestTests(MindFixture):

    def test_a23s_keywords_and_one_send(self):
        """A.23: the stored blocks, the schema, the rung's limits, the
        agent and the line, the source_ref, no client re-run, ONE send."""
        from ai_agents.providers.claude_provider import ClaudeProvider

        from bot_program.orcs import doctrine, validator
        w = self.claim(self.rendered())
        seen = []
        real = ClaudeProvider.complete

        def spy(provider, *args, **kwargs):
            seen.append(kwargs)
            return real(provider, *args, **kwargs)
        with patch.object(ClaudeProvider, "complete", spy):
            out = self.think(w, fake_answer(answer()))
        self.assertEqual(out["status"], "done")
        self.assertEqual(len(self.requests), 1)
        kw = seen[0]
        self.assertEqual(
            {k: kw[k] for k in ("agent_name", "record", "line",
                                "client_refusal_rerun", "max_attempts",
                                "max_tokens", "timeout_s")},
            {"agent_name": "orc", "record": True, "line": "orcs",
             "client_refusal_rerun": False, "max_attempts": 1,
             "max_tokens": 8000, "timeout_s": 120.0})
        self.assertEqual(kw["source_ref"], f"Orc:{self.orc.pk}:Wake:{w.pk}:r0")
        self.assertIs(kw["output_schema"], validator.SCHEMA_V1)
        self.assertIsNone(kw.get("fallbacks"))
        self.assertEqual(kw["system_blocks"],
                         [{"text": doctrine.S, "cache_ttl": "1h"}])
        sent = self.requests[0].kwargs
        self.assertEqual(sent["max_tokens"], 8000)
        self.assertEqual(sent["output_config"]["format"]["schema"],
                         validator.SCHEMA_V1)
        self.assertNotIn("max_attempts", sent, "never sent to the API")
        users = [m for m in sent["messages"] if m["role"] == "user"]
        self.assertEqual(len(users), 2, "the shared turn, the private turn")
        shared = int(w.components["shared"])
        self.assertEqual(len(users[0]["content"]), shared)
        self.assertEqual(len(users[1]["content"]),
                         len(w.block_hashes) - shared)

    def test_s_and_the_shared_turn_are_byte_identical_for_two_orcs(self):
        from bot_program.orcs import mind, validator
        other = born(self, _row(self.cfg, symbol=self.symbol),
                     at=NOW - timedelta(hours=1))
        a, b = self.rendered(), self.rendered(orc=other)
        ra, rb = mind.build_request(a, "r0"), mind.build_request(b, "r0")
        self.assertEqual(ra["system_blocks"], rb["system_blocks"])
        self.assertEqual(ra["shared_user_blocks"], rb["shared_user_blocks"])
        self.assertNotEqual(ra["private_user_blocks"],
                            rb["private_user_blocks"])
        self.assertIs(ra["output_schema"], validator.SCHEMA_V1)
        self.assertIs(rb["output_schema"], ra["output_schema"])
        self.assertEqual(a.components["s"], b.components["s"])

    def test_the_breakpoints(self):
        """S 1h; in the shared turn the last CLOSED session (MK0 when none
        closed) and MK-E 1h; IN-slow none: three of the four allowed."""
        from bot_program.orcs import mind
        from bot_program.orcs.models import OrcDossierBlock
        w = self.rendered()
        req = mind.build_request(w, "r0")
        self.assertEqual([b["cache_ttl"] for b in req["system_blocks"]],
                         ["1h"])
        shared = list(w.block_hashes[:int(w.components["shared"])])
        kinds = [OrcDossierBlock.objects.get(hash=h).kind for h in shared]
        self.assertIn("mk_session", kinds)
        ttls = {k: [] for k in set(kinds)}
        for kind, block in zip(kinds, req["shared_user_blocks"]):
            ttls[kind].append(block["cache_ttl"])
        last_session = max(i for i, k in enumerate(kinds)
                           if k == "mk_session")
        want = ["1h" if i == last_session or k == "mk_e" else None
                for i, k in enumerate(kinds)]
        self.assertEqual([b["cache_ttl"] for b in req["shared_user_blocks"]],
                         want)
        self.assertEqual(ttls["in_slow"], [None])
        self.assertEqual(sum(1 for b in req["system_blocks"]
                             + req["shared_user_blocks"]
                             + req["private_user_blocks"]
                             if b["cache_ttl"]), 3)

    def test_turn_effort_only_with_a_recorded_pass(self):
        """A.23's effort rule: the effort-only message only for a model
        that takes it AND whose family the smoke passed, the top-level
        effort pinned at the model's default then; the rung's own effort
        on top otherwise, and after a FAIL of the effort check."""
        from ai_agents.catalog import default_effort

        from bot_program.orcs import mind
        from bot_program.orcs.models import OrcSetting
        model = self._model()
        self.assertEqual(mind.efforts("r0"), {"effort": "low"})
        OrcSetting.objects.create(key="smoke_verdict", value={
            "sonnet": {"verdict": "pass", "reasons": [], "at": "x"}})
        self.assertEqual(mind.efforts("r0"),
                         {"turn_effort": "low",
                          "effort": default_effort(model)})
        w = self.claim(self.rendered())
        self.think(w, fake_answer(answer()))
        sent = self.requests[-1].kwargs
        self.assertEqual(self.requests[-1].path, "beta")
        self.assertEqual([m["role"] for m in sent["messages"]],
                         ["user", "system", "user"])
        self.assertEqual(sent["messages"][1]["output_config"],
                         {"effort": "low"})
        self.assertEqual(sent["output_config"]["effort"],
                         default_effort(model))
        OrcSetting.objects.filter(key="smoke_verdict").update(value={
            "sonnet": {"verdict": "fail", "reasons": ["effort"],
                       "at": "x"}})
        self.assertEqual(mind.efforts("r0"), {"effort": "low"})

    def test_the_ledger_row_lands_on_the_orcs_line(self):
        from ai_agents import spend
        from ai_agents.models import AgentTask
        w = self.claim(self.rendered())
        usage = fake_usage(input_tokens=9000, output_tokens=600,
                           cache_write_1h=5000)
        self.think(w, fake_answer(answer(), usage=usage))
        row_ = AgentTask.objects.get()
        self.assertEqual(row_.agent, "orc")
        self.assertEqual(row_.structured_output["source_ref"],
                         f"Orc:{self.orc.pk}:Wake:{w.pk}:r0")
        cost = float(row_.cost_usd)
        self.assertGreater(cost, 0)
        self.assertAlmostEqual(spend.spent_today("orcs"), cost, places=6)
        decision = self.entries(kind="decision")[-1]
        self.assertAlmostEqual(float(decision.cost_usd), cost, places=6)
        self.assertEqual((decision.tokens_in, decision.tokens_out,
                          decision.cache_write), (9000, 600, 5000))
        self.orc.refresh_from_db()
        self.assertAlmostEqual(float(self.orc.spend_today_usd), cost,
                               places=6)
        w.refresh_from_db()
        self.assertEqual(w.est_usd, Decimal(0), "released after the lookup")
        self.assertEqual(self.holds(), {})

    def test_the_gateway_is_listed_and_no_model_id_lives_in_the_package(self):
        from tests.test_llm_ledger_truth import BYPASS_SITES
        self.assertEqual(BYPASS_SITES["bot_program/orcs/mind_gateway.py"],
                         "ORC_AGENT")
        from bot_program.orcs import mind_gateway
        self.assertEqual(mind_gateway.ORC_AGENT, "orc")
        pkg = Path(settings.BASE_DIR) / "bot_program" / "orcs"
        hits = [p.name for p in pkg.glob("*.py")
                if re.search(r"claude-(?:sonnet|opus|haiku|fable)",
                             p.read_text(encoding="utf-8"))]
        self.assertEqual(hits, [])

    def test_no_text_block_carries_an_account_figure(self):
        """K-B10 (N6): the fixture's balance, r_money and size appear in
        no text block of any request, in any format."""
        self.orc.refresh_from_db()
        self.assertEqual(self.orc.r_money, KB10_R_MONEY)
        self.assertEqual(self.row.qty, KB10_QTY)
        w = self.claim(self.rendered())
        self.think(w, fake_answer(answer()))
        self.assertEqual(len(self.requests), 1)
        self.assert_no_account_figure()


# ── one send, and the money ──────────────────────────────────────────────

class TheMoneyOfOneCallTests(MindFixture):

    def test_an_overloaded_event_mid_stream_sends_once_and_holds_the_bound(
            self):
        """A.21: max_attempts=1, so the provider never re-sends a whole
        request after an error mid-stream; the wake is failed and its
        bound stays held until 00:00 UTC (unbilled), its HIGH counted on
        the Orc."""
        from ai_agents import spend

        from bot_program.orcs.constants import HIGH
        from bot_program.orcs.scheduler import next_midnight
        w = self.claim(self.rendered())
        bound = float(w.est_usd)
        out = self.think(w, mid_stream_error())
        self.assertEqual(len(self.requests), 1, "sent once")
        self.assertEqual((out["status"], out["code"]),
                         ("failed", "unbilled"))
        hold = self.holds()[f"w{w.pk}"]
        self.assertEqual((hold["kind"], hold["usd"]), ("unbilled", bound))
        self.assertEqual(hold["until"],
                         next_midnight(timezone.now()).isoformat())
        self.orc.refresh_from_db()
        self.assertAlmostEqual(self.orc.seen["unbilled_usd"], HIGH["r0"])
        self.assertEqual(spend.spent_today("orcs"), 0.0)
        from bot_program.orcs import mind_gateway
        self.assertAlmostEqual(mind_gateway.inflight_usd(), bound)
        error = self.entries(kind="error")[-1]
        self.assertTrue(error.body["held"])

    def test_a_timeout_holds_the_bound_unbilled(self):
        w = self.claim(self.rendered())
        out = self.think(w, PreStream(TimeoutError("read timed out")))
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(out["code"], "unbilled")
        self.assertEqual(self.holds()[f"w{w.pk}"]["kind"], "unbilled")
        w.refresh_from_db()
        self.assertEqual((w.status, w.est_usd), ("failed", Decimal(0)))

    def test_booked_never_passes_the_bound_at_the_worst_usage(self):
        """N4: every prompt token written at 1h on 1.35 x the estimate,
        and the whole max_tokens of output, books at most the bound."""
        w = self.claim(self.rendered())
        est = int(w.components["tokens"])
        worst = fake_usage(input_tokens=0, output_tokens=8000,
                           cache_write_1h=-(-est * 135 // 100))
        self.think(w, fake_answer(answer(), usage=worst))
        booked = float(self.entries(kind="decision")[-1].cost_usd)
        self.assertGreater(booked, 0.1)
        self.assertLessEqual(booked, float(w.est_usd) + 1e-6)

    def test_a_missing_ledger_row_holds_the_booked_cost(self):
        """A.24: the reservation is released only after the provider's
        own ledger row is found; a fenced ledger write leaves the line
        undercounting, so the cost is held as a ledger_gap instead."""
        from ai_agents import spend
        from ai_agents.models import AgentTask
        w = self.claim(self.rendered())
        with patch.object(AgentTask.objects, "create",
                          side_effect=RuntimeError("the ledger is down")):
            self.think(w, fake_answer(answer()))
        self.assertEqual(AgentTask.objects.count(), 0)
        self.assertEqual(spend.spent_today("orcs"), 0.0, "unbooked")
        cost = float(self.entries(kind="decision")[-1].cost_usd)
        hold = self.holds()[f"w{w.pk}"]
        self.assertEqual((hold["kind"], hold["usd"]),
                         ("ledger_gap", round(cost, 6)))
        self.orc.refresh_from_db()
        self.assertAlmostEqual(float(self.orc.spend_today_usd), cost)
        self.assertNotIn("unbilled_usd", {k for k, v in self.orc.seen.items()
                                          if v})
        from bot_program.orcs import mind_gateway
        self.assertAlmostEqual(mind_gateway.inflight_usd(), cost)

    def test_a_row_closed_inside_the_call_books_and_journals_late_only(self):
        """A.26 (P16): the row is read again under the lock; closed during
        the call, the answer is booked and journaled late, and nothing else
        is written: no plan, no intent, no note, no good-wake time, no
        facts hash."""
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.models import OrcIntent
        w = self.claim(self.rendered())
        self.orc.refresh_from_db()
        before = (self.orc.latest_note, self.orc.last_good_wake_at,
                  self.orc.last_facts_hash, self.orc.plan_version)
        real_send = self.fake._send
        table = AssetBotTrade._meta.db_table

        def send(path, kwargs):
            out = real_send(path, kwargs)
            # another process closes the row while the model reads: a
            # write of the care's, never the Orcs' (raw SQL, so the
            # behavioural guard, which watches the Orcs' own writes, does
            # not take it for theirs)
            from django.db import connection
            with connection.cursor() as cur:
                cur.execute(f"UPDATE {table} SET status = %s WHERE id = %s",
                            ["CLOSED", self.row.pk])
            return out
        self.fake._send = send
        out = self.think(w, fake_answer(answer(
            action="revise_plan", note="A plan that must not land.")))
        self.assertEqual((out["status"], out["code"], out["late"]),
                         ("late", "row_closed", True))
        decision = self.entries(kind="decision")[-1]
        self.assertTrue(decision.body["late"])
        self.assertGreater(decision.cost_usd, 0, "booked")
        self.assertEqual(self.entries(kind="plan"), [])
        self.assertEqual(self.entries(kind="intent"), [])
        self.assertFalse(OrcIntent.objects.exists())
        self.orc.refresh_from_db()
        self.assertEqual((self.orc.latest_note, self.orc.last_good_wake_at,
                          self.orc.last_facts_hash, self.orc.plan_version),
                         before)
        self.assertAlmostEqual(float(self.orc.spend_today_usd),
                               float(decision.cost_usd))

    def test_the_settle_sends_a_waiting_wake_back_with_its_journal_bound(
            self):
        """A.24 step 6: a pending wake of the same Orc goes back to the
        render (recorded, queued, journal_as_of = the settle), its
        queued_at kept; rendered again, still as of its own moment, its
        PS5 holds the decision that just landed and nothing written after
        journal_as_of."""
        from bot_program.orcs import journal, wake
        from bot_program.orcs.models import OrcDossierBlock, OrcWake
        first = self.claim(self.rendered())
        waiting = self.rendered(at=NOW + timedelta(minutes=5),
                                reasons=[{"code": "W11", "key": "W11:x",
                                          "t": "the metronome",
                                          "urgent": False}])
        queued_at = NOW + timedelta(minutes=5)
        OrcWake.objects.filter(pk=waiting.pk).update(status="pending",
                                                     queued_at=queued_at)
        out = self.think(first, fake_answer(answer(
            note="Holding: the first decision.")))
        self.assertEqual(out["sent_back"], 1)
        waiting.refresh_from_db()
        self.assertEqual(waiting.status, "recorded")
        self.assertEqual(waiting.components["render"], "queued")
        upto = waiting.components["journal_as_of"]
        self.assertEqual(waiting.queued_at, queued_at, "kept")
        self.assertEqual(waiting.components["as_of"],
                         (NOW + timedelta(minutes=5)).isoformat(),
                         "its own moment never moves")
        later = timezone.now() + timedelta(minutes=30)
        journal.append(self.orc, "decision", "Decision in shadow: hold.",
                       author="orc", at=later,
                       body={"answer": {"action": "hold",
                                        "note": "Written after the bound."}})
        with patch("django.utils.timezone.now",
                   return_value=NOW + timedelta(minutes=5)):
            self.assertEqual(wake.render_queued(), (1, 0))
        waiting.refresh_from_db()
        ps = OrcDossierBlock.objects.get(hash=waiting.block_hashes[
            int(waiting.components["shared"])])
        body = json.loads(ps.text.partition("\n")[2])
        notes = " ".join(body["ps5"]["notes"])
        self.assertIn("Holding: the first decision.", notes)
        self.assertNotIn("Written after the bound.", notes)
        self.assertEqual(waiting.components["journal_as_of"], upto)


# ── the gates, the authority and the rungs (each a pair) ────────────────

class TheGatesTests(MindFixture):

    def test_each_closed_gate_makes_no_call_and_names_its_code(self):
        """A.2: the four gates are read again in the gateway just before
        the send. Every gate ON: one request; then ONE gate OFF: none,
        with that gate's code, and a code answer."""
        gates = (("platform_master", "platform_off"),
                 ("orcs", "orcs_off"), ("orcs_minds", "minds_off"),
                 ("line", "line_off"))
        for gate, code in gates:
            with self.subTest(gate):
                on, off = self.rendered(), self.rendered()
                self.think(self.claim(on), fake_answer(answer()))
                self.assert_one_call()
                closed = self.claim(off)
                if gate == "line":
                    with override_settings(AI_CONFIG={
                            **settings.AI_CONFIG,
                            "orc_daily_budget_usd": 0.0}):
                        out = self.think(closed)
                else:
                    _switch(gate, False)
                    out = self.think(closed)
                    _switch(gate, True)
                self.assert_no_call(code=code, got=out["code"])
                closed.refresh_from_db()
                self.assertEqual((closed.status, closed.skipped_reason),
                                 ("skipped", code))
                self.assertEqual(closed.est_usd, Decimal(0), "released")
                budget = self.entries(kind="budget", wake=closed)
                self.assertEqual(len(budget), 0 if code == "minds_off"
                                 else 1)

    def test_a_seat_above_l0_refuses_with_authority_and_no_call(self):
        """A.29: S says nothing binds; the gateway keeps it true."""
        from bot_program.orcs.models import OrcSeat
        on, off = self.rendered(), self.rendered()
        self.think(self.claim(on), fake_answer(answer()))
        self.assert_one_call()
        OrcSeat.objects.filter(pk=self.orc.seat_id).update(level=1)
        out = self.think(self.claim(off))
        self.assert_no_call(code="authority", got=out["code"])

    def test_a_rung_outside_the_callers_list_raises_with_no_request(self):
        """N4, P35: CALLER_RUNGS = wake r0, smoke r0 and h0; any other
        rung raises before anything is sent."""
        from bot_program.orcs import mind, mind_gateway
        w = self.rendered()
        request = mind.build_request(w, "r0")
        ref = mind.source_ref(w, "r0")
        mind_gateway.call(caller="wake", rung_name="r0", request=request,
                          source_ref=ref, bound_usd=0.2)
        self.assert_one_call()
        self.assertEqual(mind_gateway.CALLER_RUNGS,
                         {"wake": ("r0",), "smoke": ("r0", "h0")})
        refused = [("wake", r) for r in ("h0", "r1", "r2", "r3", "r4", "r5")]
        refused += [("smoke", r) for r in ("r1", "r2", "r3", "r4", "r5")]
        refused += [("captain", "r0"), ("", "r0")]
        for caller, rung in refused:
            with self.subTest(caller=caller, rung=rung), \
                    self.assertRaises(ValueError):
                mind_gateway.call(caller=caller, rung_name=rung,
                                  request=request, source_ref=ref,
                                  bound_usd=0.2)
        self.assert_no_call()


# ── the line asked with the money in flight ─────────────────────────────

class TheLineTests(MindFixture):

    def test_the_line_is_asked_for_the_bound_and_the_others_money(self):
        """A.20: can_spend gets this call's bound plus the OTHER calls'
        reservations and holds, never its own twice, never the default
        estimate, never total_only, on the Orcs line."""
        from bot_program.orcs.scheduler import hold
        w = self.claim(self.rendered())
        other = self.copy_of(w)            # a second call in flight
        held = self.rendered()
        hold(kind="unbilled", usd=0.5, wake=held, rung="r0",
             now=timezone.now())
        self.think(w, fake_answer(answer()))
        asked = [c for c in self.spend_calls if c.gateway is not None]
        self.assertEqual(len(asked), 1)
        kw = asked[0].kwargs
        self.assertEqual(kw["line"], "orcs")
        self.assertNotIn("total_only", kw)
        self.assertEqual(kw["tier"], "balanced")
        want = float(w.est_usd) + float(other.est_usd) + 0.5
        self.assertAlmostEqual(kw["estimated_usd"], want, places=6)

    def test_the_line_off_and_the_total_spent_are_their_own_codes(self):
        from bot_program.orcs import mind_gateway
        with override_settings(AI_CONFIG={**settings.AI_CONFIG,
                                          "orc_daily_budget_usd": 0.0}):
            self.assertEqual(mind_gateway.ask_line(
                rung_name="r0", bound_usd=0.2)[1], "line_off")
        from ai_agents.models import AgentTask
        AgentTask.objects.create(agent="critic", provider="claude",
                                 model="m", prompt_summary="x",
                                 cost_usd=Decimal("30"))
        self.assertEqual(mind_gateway.ask_line(rung_name="r0",
                                               bound_usd=0.2)[1], "total")


# ── the tick's import path ───────────────────────────────────────────────

class TheTickNeverLoadsTheMindTests(MindTestCase):

    def test_the_ticks_modules_load_no_gateway_mind_or_scheduler(self):
        """A.7: the tick's import path (observe, wake, journal) never
        loads the gateway, the mind or the scheduler; the gateway imports
        the provider inside its functions. The modules exist (else the
        proof would hold of nothing)."""
        import subprocess
        import sys
        code = ("import importlib.util, os, sys, django\n"
                "os.environ.setdefault('DJANGO_SETTINGS_MODULE', "
                "'config.settings')\n"
                "django.setup()\n"
                "names = ('bot_program.orcs.mind_gateway', "
                "'bot_program.orcs.mind', 'bot_program.orcs.scheduler', "
                "'bot_program.orcs.validator', 'bot_program.orcs.doctrine')\n"
                "print('MISSING', [m for m in names "
                "if importlib.util.find_spec(m) is None])\n"
                "import bot_program.orcs.observe, bot_program.orcs.wake\n"
                "import bot_program.orcs.switches\n"
                "print('LOADED', [m for m in names if m in sys.modules])\n")
        out = subprocess.run([sys.executable, "-c", code],
                             cwd=settings.BASE_DIR, capture_output=True,
                             text=True, timeout=120)
        self.assertIn("MISSING []", out.stdout, out.stderr[-2000:])
        self.assertIn("LOADED []", out.stdout, out.stderr[-2000:])


# ── counting tokens, and S ───────────────────────────────────────────────

class TheCountAndTheDoctrineTests(MindFixture):

    def test_measure_tokens_counts_once_and_sends_nothing_else(self):
        """N3's one exception: the free count, with the line at 0, records
        one count request and never a messages request."""
        from bot_program.orcs import doctrine, mind_gateway
        self.think(self.claim(self.rendered()), fake_answer(answer()))
        self.assert_one_call()
        with override_settings(AI_CONFIG={**settings.AI_CONFIG,
                                          "orc_daily_budget_usd": 0.0}):
            n = mind_gateway.measure_tokens(system_blocks=[
                {"text": doctrine.S, "cache_ttl": None}],
                user_message="S alone")
        self.assertEqual(n, self.fake.count_answer)
        self.assertEqual(len(self.count_requests), 1)
        self.assert_no_call()

    def test_s_is_under_its_cap_byte_stable_and_stored(self):
        """A.28-A.29: S fits 12,000 characters and the reserve on the
        estimator, names no time, Orc, type or model, carries the
        authority sentence, and is stored as a block whose hash the wake
        keeps."""
        from bot_program.orcs import doctrine, dossier
        from bot_program.orcs.constants import (S_MAX_CHARS,
                                                S_TOKENS_RESERVE, S_VERSION)
        from bot_program.orcs.models import OrcDossierBlock
        self.assertLessEqual(len(doctrine.S), S_MAX_CHARS)
        self.assertLessEqual(dossier.estimate_tokens(doctrine.S),
                             S_TOKENS_RESERVE)
        self.assertIn(doctrine.S_AUTHORITY_L0, doctrine.S)
        self.assertEqual(doctrine.S_AUTHORITY_L0,
                         "Nothing you decide is applied: every seat is L0, "
                         "shadow only, and your proposals are graded against "
                         "what the care alone does.")
        for word in ("sonnet", "opus", "haiku", "fable", "claude", "Line Orcs",
                     "Mercenaries", "Olog-hai", "UTC", "2026"):
            self.assertNotIn(word, doctrine.S.lower() if word.islower()
                             else doctrine.S, word)
        w = self.rendered()
        s = w.components["s"]
        self.assertEqual(s["version"], S_VERSION)
        block = OrcDossierBlock.objects.get(hash=s["hash"])
        self.assertEqual((block.kind, block.key, block.text),
                         ("s", f"s|{S_VERSION}|sonnet", doctrine.S))
        self.assertEqual(dossier.text_of([s["hash"]]), doctrine.S)
        self.assertEqual(self.rendered().components["s"], s, "byte-stable")
