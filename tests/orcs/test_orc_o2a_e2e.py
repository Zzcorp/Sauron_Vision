"""T12, ONE WAKE FROM THE TICK TO THE GRADE, IN EVERY WORLD (the O2 spec
§1.1.4, §1.1.7 T12, P38; 2026-11-05).

The wiring O2a's last commit adds, run whole on the fake model (N7), for a
real-money bot row, a manual row, an eToro demo row and a paper row, each
once with a menu under F5 (the mark is stale: the integrity verdict is
critical) and once without:

  the tick (care, then the Orcs' hook) records the birth wake `recorded`;
  the render pass (wake.render_queued) merges, renders as of the wake's
  moment and admits it `pending`, one ticket's worth;
  the claim (scheduler.claim) reserves its bound and runs it;
  the fake model answers a tighten to a level of the wake's own menu;
  the validator and the officer judge it: without F5 it is `done` and its
  proposal is queued in shadow; under F5 the menu holds no tighten on a
  stale mark, so the answer is `refused`, journaled with its rule, and
  nothing is queued;
  the next tick takes the queued proposal into the O arm only (`simulated`,
  the arm in would mode), never the row;
  the idea dies and is graded: n_llm, n_actions, n_refused, the
  invalid-output tag, the versions and the AI cost booked on the Orcs line;
  the day counters, the booking on the Orcs line and the card's rung.

And a render that fails is answered by code (`render_failed`), never
pending and never silence: the care keeps the idea's Orc where it was.

Run with:  python manage.py test tests.orcs.test_orc_o2a_e2e
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from tests.orcs.helpers import (_config, _manual_config, _manual_row, _row,
                                born, care_tick)
from tests.orcs.helpers_o2 import fake_answer
from tests.orcs.test_orc_o2a_admission import QueueFixture
from tests.orcs.test_orc_o2a_call import NOW, answer

WORLDS = ("real", "manual", "demo", "paper")
#: The venue's fresh and stale mark ages (integrity: over 120 s is
#: critical, so F5).
FRESH_S, STALE_S = 20, 600


class _E2E(QueueFixture):
    """MindFixture's world (BTCUSD's venue bars at NOW, the day built, the
    four gates ON, the Orcs line at $6), and one Orc per world born on its
    own row."""

    def setUp(self):
        super().setUp()
        from bot_program.orcs.models import OrcSetting
        OrcSetting.objects.update_or_create(key="max_paper_orcs",
                                            defaults={"value": 100})
        self.client_mock = MagicMock()
        self.client_mock.get_positions.return_value = []
        self.client_mock.modify_protective.return_value = {"ok": True,
                                                           "price": None}

    # ── the worlds ───────────────────────────────────────────────────────

    def world(self, world, *, f5):
        """(config, row, Orc) of `world`, its mark fresh or stale."""
        from bot_program.models import AssetBotTrade
        from market_data.models import LiveQuote
        tag = f"{world}{'_f5' if f5 else ''}"
        if world == "manual":
            cfg = _manual_config(self.user)
            row = _manual_row(cfg, paper=False, symbol=self.symbol,
                              meta={"broker": "etoro", "manual": True})
        elif world == "real":
            cfg = _config(self.user, mode="live", name=f"e2e_{tag}")
            row = _row(cfg, paper=False, symbol=self.symbol,
                       meta={"broker": "etoro"})
        elif world == "demo":
            cfg = _config(self.user, name=f"e2e_{tag}")
            row = _row(cfg, paper=False, symbol=self.symbol,
                       meta={"broker": "etoro", "broker_env": "paper"})
        else:
            cfg = _config(self.user, name=f"e2e_{tag}")
            row = _row(cfg, symbol=self.symbol)
        age = STALE_S if f5 else FRESH_S
        at = NOW - timedelta(seconds=age)
        if not row.paper:
            meta = dict(row.metadata)
            meta["venue_mark"] = {"price": "100.5", "at": at.isoformat(),
                                  "source": "etoro", "via": "position"}
            AssetBotTrade.objects.filter(pk=row.pk).update(
                metadata=meta, opened_at=NOW - timedelta(hours=2))
        else:
            AssetBotTrade.objects.filter(pk=row.pk).update(
                opened_at=NOW - timedelta(hours=2))
        LiveQuote.objects.filter(instrument__symbol=self.symbol).update(
            updated_at=at)
        row.refresh_from_db()
        orc = born(self, row, at=NOW - timedelta(hours=2))
        row.refresh_from_db()
        return cfg, row, orc

    def tick(self, cfg, row, at):
        from bot_program.asset_engine.base import make_bot
        return care_tick(self, make_bot(cfg), row, "100.5", self.client_mock,
                         at)

    def tighten_of(self, w):
        """A level of the wake's own menu a tighten may name (V7)."""
        from bot_program.orcs import validator
        vctx = w.components["vctx"]
        for lv in vctx["menu"]:
            if lv.get("kind") in ("swing", "pool", "round") and \
                    lv.get("stop") is not None and \
                    not validator._v7(lv, vctx, "BUY")[1]:
                return lv["id"]
        self.fail("no level of this menu leaves the stop room")

    def cites(self, orc):
        from bot_program.orcs.validator import facts_index
        return [k for k, v in facts_index(orc, as_of=NOW).items()
                if v["kind"] in ("structure", "bar", "care")][:1]

    # ── one wake, whole ─────────────────────────────────────────────────

    def run_world(self, world, *, f5):
        from ai_agents import spend
        from ai_agents.models import AgentTask
        from bot_program.orcs import grading, mind, scheduler, wake
        from bot_program.orcs.models import (Orc, OrcIntent, OrcJournal,
                                             OrcTrack, OrcWake)
        cfg, row, orc = self.world(world, f5=f5)
        real = world in ("real", "manual")
        self.assertEqual(orc.seat.venue, {"real": "live", "manual": "live",
                                          "demo": "demo",
                                          "paper": "paper"}[world])
        booked_before = spend.spent_today("orcs")
        # 1. the tick records the birth wake
        self.tick(cfg, row, NOW)
        [w] = OrcWake.objects.filter(orc=orc)
        self.assertEqual((w.status, w.skipped_reason), ("recorded", ""))
        self.assertEqual(w.components["render"], "queued")
        # 2. the render pass: merge, render, admit
        with patch("django.utils.timezone.now", return_value=NOW):
            out = wake.render_queued()
        self.assertEqual((tuple(out), out.admitted), ((1, 0), 1))
        w.refresh_from_db()
        self.assertEqual(w.status, "pending")
        self.assertEqual(bool(w.components["f5"]), f5,
                         "F5 follows the mark's age")
        self.assertEqual(w.priority, 3.0 if real else 1.0,
                         "the rank of an urgent wake in its world")
        self.assertEqual(w.components["real"], real)
        allowed = w.components["vctx"]["allowed"]
        self.assertEqual("tighten" in allowed, not f5)
        lid = self.tighten_of(w) if not f5 else next(
            lv["id"] for lv in w.components["vctx"]["menu"]
            if lv.get("kind") in ("swing", "pool", "round"))
        # 3. the claim and the fake model
        got = scheduler.claim(now=NOW)
        self.assertEqual(got["wake"].pk, w.pk)
        self.use_fake(fake_answer(answer(
            action="tighten", level_id=lid, facts_cited=self.cites(orc),
            note="Tightening under the swing.")))
        settled = mind.think(got["wake"], now=NOW)
        self.assert_one_call()
        w.refresh_from_db()
        # 4. the validator and the officer
        intents = list(OrcIntent.objects.filter(orc=orc))
        if f5:
            self.assertEqual(settled["status"], "refused")
            self.assertEqual(w.status, "refused")
            self.assertTrue(OrcJournal.objects.filter(
                orc=orc, kind="refusal", wake=w).exists())
            self.assertFalse([i for i in intents if i.status == "queued"])
        else:
            self.assertEqual(settled["status"], "done")
            self.assertEqual(w.status, "done")
            [it] = intents
            self.assertEqual((it.kind, it.mode, it.status, it.level_id),
                             ("tighten", "shadow", "queued", lid))
        # 5. the booking lands on the Orcs line
        ledger = AgentTask.objects.get(
            agent="orc", structured_output__source_ref=f"Orc:{orc.pk}:"
                                                       f"Wake:{w.pk}:r0")
        self.assertGreater(ledger.cost_usd, 0)
        self.assertAlmostEqual(spend.spent_today("orcs") - booked_before,
                               float(ledger.cost_usd), places=6)
        decision = OrcJournal.objects.get(orc=orc, kind="decision", wake=w)
        self.assertEqual(decision.cost_usd, ledger.cost_usd)
        self.assertEqual(w.est_usd, Decimal(0), "the reservation released")
        # 6. the day counters and the card
        orc = Orc.objects.get(pk=orc.pk)
        self.assertEqual(orc.llm_wakes_today, 1)
        self.assertEqual(orc.spend_today_usd, ledger.cost_usd)
        self.assertEqual(orc.card["intellect"]["rung_t"],
                         "r0 · balanced tier, low effort")
        self.assertEqual(orc.card["intellect"]["status_t"],
                         "answered in shadow" if not f5 else
                         f"the answer was refused by the validator "
                         f"({w.skipped_reason})")
        # 7. the next tick steps the O arm only
        stop_before = row.stop_loss
        self.tick(cfg, row, NOW + timedelta(minutes=5))
        row.refresh_from_db()
        self.assertEqual(row.stop_loss, stop_before, "the row never moves")
        o_arm = OrcTrack.objects.get(orc=orc, arm="orc_shadow")
        if f5:
            self.assertNotEqual((o_arm.state or {}).get("mode"), "would")
        else:
            it.refresh_from_db()
            self.assertEqual(it.status, "simulated")
            self.assertEqual((o_arm.state or {}).get("mode"), "would")
        # 8. the idea dies and is graded
        from bot_program.models import AssetBotTrade
        later = NOW + timedelta(hours=1)
        for t in OrcTrack.objects.filter(orc=orc):
            OrcTrack.objects.filter(pk=t.pk).update(
                open=False, exit_r=t.exit_r if not t.open else 0.25,
                exit_price=t.exit_price or Decimal("100.5"),
                exit_at=t.exit_at or later, exit_why=t.exit_why or "e2e")
        AssetBotTrade.objects.filter(pk=row.pk).update(
            status="CLOSED", exit_price=Decimal("100.5"), closed_at=later)
        Orc.objects.filter(pk=orc.pk).update(state="dead", died_at=later)
        orc = Orc.objects.get(pk=orc.pk)
        g = grading.grade(orc, now=later + timedelta(minutes=10))
        self.assertIsNotNone(g)
        self.assertEqual(g.n_llm, 1)
        self.assertEqual(g.n_actions, 0 if f5 else 1)
        self.assertEqual(g.n_refused > 0, f5)
        self.assertIn("invalid:1.00" if f5 else "invalid:0.00", g.tags)
        for tag in ("rung:r0", "s:s1", "schema:d1"):
            self.assertIn(tag, g.tags)
        self.assertEqual(g.ai_cost_usd, ledger.cost_usd)
        self.assertEqual(g.venue, orc.seat.venue)
        return orc


class EveryWorldWithoutF5Tests(_E2E):

    def test_real_money_bot_row(self):
        self.run_world("real", f5=False)

    def test_manual_row(self):
        self.run_world("manual", f5=False)

    def test_etoro_demo_row(self):
        self.run_world("demo", f5=False)

    def test_paper_row(self):
        self.run_world("paper", f5=False)


class EveryWorldUnderF5Tests(_E2E):

    def test_real_money_bot_row(self):
        self.run_world("real", f5=True)

    def test_manual_row(self):
        self.run_world("manual", f5=True)

    def test_etoro_demo_row(self):
        self.run_world("demo", f5=True)

    def test_paper_row(self):
        self.run_world("paper", f5=True)


class ARenderThatFailsIsNeverSilenceTests(_E2E):

    def test_render_failed_answers_by_code_and_never_counts_as_silence(self):
        """A.7, P11: two renders that fail in a row are answered by code
        (`render_failed`): never pending, never claimed, never a failed
        call; the watchdog finds nothing stale and the care takes nothing,
        while a served wake still runs."""
        from bot_program.orcs import scheduler, wake
        from bot_program.orcs.models import Orc, OrcJournal, OrcWake
        cfg, row, orc = self.world("paper", f5=False)
        # the first through the tick, the second recorded as the tick
        # records a later reason
        self.tick(cfg, row, NOW)
        for minutes in (0, 20):
            at = NOW + timedelta(minutes=minutes)
            if minutes:
                orc.refresh_from_db()
                wake.record(orc, row, [{"code": "W4", "key": "W4:-0.5",
                                        "t": "-0.5R reached",
                                        "urgent": True}], now=at,
                            price="100.5")
            with patch("bot_program.orcs.dossier.render",
                       side_effect=RuntimeError("the dossier broke")), \
                    patch("django.utils.timezone.now", return_value=at):
                out = wake.render_queued()
            self.assertEqual((tuple(out), out.admitted), ((0, 1), 0))
        failed = list(OrcWake.objects.filter(orc=orc))
        self.assertEqual(len(failed), 2)
        for w in failed:
            self.assertEqual((w.status, w.skipped_reason),
                             ("skipped", "render_failed"))
            self.assertEqual(w.components["render"], "failed")
        out = self.watch(NOW + timedelta(minutes=45))
        self.assertEqual((out["minds_stale"], out["minds_backlog"]), (0, 0))
        orc = Orc.objects.get(pk=orc.pk)
        self.assertNotEqual(orc.state, "care_owned")
        self.assertEqual(int((orc.seen or {}).get("failed_in_row") or 0), 0)
        self.assertFalse(OrcJournal.objects.filter(orc=orc,
                                                   kind="takeover").exists())
        self.assertIsNone(scheduler.claim(now=NOW)["wake"])
        # the queue still serves the next wake that renders
        later = NOW + timedelta(minutes=40)
        orc.refresh_from_db()
        wake.record(orc, row, [{"code": "W4", "key": "W4:-0.75",
                                "t": "-0.75R reached", "urgent": True}],
                    now=later, price="100.5")
        with patch("django.utils.timezone.now", return_value=later):
            out = wake.render_queued()
        self.assertEqual(out.admitted, 1)
        got = self.serve(now=later, script=fake_answer(answer()))
        self.assertIsNotNone(got["wake"])
        self.assert_one_call()
        self.assertEqual(got["settle"]["status"], "done")
