"""O2c's DRUM WAKES, BEHIND `orcs_drum_wakes`, OFF: WAVES, THE SETTLE AND THE
BREAKER (the O2 spec C.14-C.17, C.19 and N2 for `orcs_drum_wakes`; §1.3.5
P14's twin and P15; §1.3.6 "Drums", "Every new switch" and "The Book";
§1.3.8 W12; §0 N1.2, N1 test item h, N2, N7, N8; §4 Q21; 2026-11-15).

- THE PAIR: with `orcs_drums` ON from before O2c, the minds ON and the
  line set, `orcs_drum_wakes` ON queues exactly one W12 for a delivery,
  recorded once its wave settled, claimed and sent once (the K-B10 walk on
  its request); then OFF, a delivery journals its drum and no call is sent
- OFF: the DR headline and body, the Orc's memory, route's return and the
  OrcDrum rows are O1's, and no OrcWave row is written, in each world the
  gate reads OFF (the drum wakes' switch, the drums' switch, a gate of the
  minds); turned OFF after a W12 was queued, a drum wake not yet sent ends
  drum_wakes_off at its admission or at its claim (frictionless off)
- urgency: a stop_hit on the Orc's own symbol is urgent; a drum whose
  receiver's stop sits 0.2 x ATR(1h) from the mark is urgent, at 0.5 not;
  the render reads it again as of the wake's moment (P15)
- the settle: no W12 is recorded before DRUM_SETTLE_MIN after its wave's
  first drum, then it is; the drums that join within DRUM_JOIN_MIN wake the
  Orc once; an unsettled W12 survives a wake recorded for another reason
- the breaker at its numbers: the 7th drum wake of a wave and the 13th of a
  user within a rolling hour end drum_breaker, the wave records {open, why}
  and its next delivery is journaled only; the 3rd urgent W12 of an Orc in
  a UTC day waits in seen["w12_carry"], its delivery journaled, and joins
  the next recorded wake; 20 own-symbol stop_hit waves on one real Orc make
  2 urgent drum wakes that reach a model, the claim's guard holding the one
  that slipped past its delivery (drum_carry); drum wakes stop at 25% of the
  line (drum_share, urgent included; their money in flight counted once);
  past 60% of the line a W12 ends
  drum_line, while an urgent own-stakes W12 still runs inside its triage
  ceiling (a real one is claimed, a paper one ends triage)
- the wave stamp: an intent from a W12 wake carries wave_id and the O arm
  carries {wave, hop}; other intents carry neither key; no real stop carries
  a wave, and a would-stop hit publishes no drum
- drum_bus.on_close, comments stripped, has the AST of its frozen source
- N2 for `orcs_drum_wakes`; `orcs_drums` outside both tuples, its name kept,
  C.19's description; the RUNBOOK's section

Run with:  python manage.py test tests.orcs.test_orc_o2c_drums
"""
import ast
import inspect
import json
import textwrap
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import CommandError, call_command

from tests.orcs.helpers import _paper_cap, _row, _switch, born
from tests.orcs.helpers_o2 import (KB10_QTY, KB10_R_MONEY, MindTestCase,
                                   fake_answer)
from tests.orcs.test_orc_o2a_admission import QueueFixture
from tests.orcs.test_orc_o2a_arm import S1H, ArmFixture
from tests.orcs.test_orc_o2a_call import NOW, answer
from tests.orcs.test_orc_o2b_routed import TEST_PIN, WRONG_PIN, _row_of

BASE = Path(settings.BASE_DIR)
RUNBOOK = BASE / "deploy" / "RUNBOOK.md"
KEY = "orcs_drum_wakes"
NAME = "Orc Drum Wakes (models in shadow)"
DESCRIPTION = ("Off (default). On, with Orc War Drums and the minds on: a "
               "drum also wakes the Orcs it reaches, in shadow, once its wave "
               "settles, within a breaker (2 urgent drum wakes an Orc a day, "
               "25% of the Orcs line). It sends no order. Turning it on takes "
               "the PIN.")
DRUMS = "orcs_drums"
DRUMS_NAME = "Orc War Drums (wakes from O2)"
#: C.19's words, word for word.
DRUMS_DESCRIPTION = ("Off (default). With orcs on, the war drums (a stop hit, "
                     "a lock, a level break...) are always journaled on the "
                     "Orcs they reach within one user's book. On, with Orc "
                     "Drum Wakes on, a drum also wakes the Orcs it reaches, "
                     "in shadow.")
#: drum_bus.on_close as O2a froze it (FROZEN_SOURCES, N1 test item h): O2c
#: changes its comment only (the seam re-marked "# O3:", C.17).
FROZEN_ON_CLOSE = '''
def on_close(orc, trade):
    """A stop_hit drum when the leg's stop closed it (the venue's stop, the
    engine's, the care's soft stop; never a cut or a clock): once per
    leg."""
    from bot_program.orcs import ghost
    from bot_program.orcs.models import OrcDrum
    rx = ghost.real_exit_of(orc, trade)
    if rx is None or rx.kind not in STOP_HIT_KINDS:
        return None
    if rx.kind == "care" and not _care_stop_hit(trade, rx):
        return None
    if OrcDrum.objects.filter(kind="stop_hit", orc=orc,
                              payload__leg=trade.pk).exists():
        return None
    level = _f(rx.level) if rx.level is not None else _f(trade.exit_price)
    at = rx.at or trade.closed_at or _now()
    mark, atr = _last(trade.symbol), _atr1h(trade.symbol, trade.asset_class,
                                            at)
    beyond = None
    if level is not None and mark is not None and atr:
        sign = 1 if str(trade.side).upper() == "BUY" else -1
        beyond = round(max(0.0, sign * (level - mark)) / atr, 2)
    payload = drums.payload_stop_hit(stop=_px(trade, level), at=at,
                                     beyond_atr=beyond)
    payload["leg"] = trade.pk
    return publish("stop_hit", user=orc.user, symbol=trade.symbol,
                   asset_class=trade.asset_class, payload=payload,
                   origin=f"orc:{orc.pk}", orc=orc, at=at)
'''
#: The keys of a DR entry's body, as O1 writes it.
O1_BODY = ("fk", "drum", "drum_kind", "symbol", "relation", "hop", "wave")


def _fold(text) -> str:
    return " ".join(str(text or "").split())


def _w12(wave, *, urgent=True, first_at=None, hop=0, own=True,
         carried=False):
    """A W12 reason as drum_bus.route queues one (C.14)."""
    out = {"code": "W12", "key": f"W12:{wave}",
           "t": f"a drum: a stop hit on BTCUSD (same symbol, hop {hop})",
           "urgent": bool(urgent), "wave": wave, "hop": hop,
           "first_at": (first_at or NOW - timedelta(minutes=30)).isoformat(),
           "drum": "stop_hit", "own": own}
    if carried:
        out["carried"] = True
    return out


class _Drums(QueueFixture):
    """MindFixture's paper BTCUSD Orc, the ORIGIN of the drums here (its
    stops are the ones hit); receivers born on the same symbol in the same
    book (`receiver`), each quiet: its birth wake behind it. `orcs_drums` ON,
    as it may already be at the site; the four gates ON, the line at $6."""

    def setUp(self):
        super().setUp()
        _switch(DRUMS, True)
        _paper_cap()

    # ── the world ────────────────────────────────────────────────────────

    def receiver(self, *, real=False, stop="98", at=NOW):
        """A new Orc on BTCUSD in the user's book, its memory quiet at
        `at`; `real`: on a live row (scheduler.is_real)."""
        from bot_program.orcs import scheduler
        from bot_program.orcs.models import Orc
        row = _row(self.cfg, paper=not real, qty=str(KB10_QTY),
                   symbol=self.symbol, stop=stop)
        orc = born(self, row, at=NOW - timedelta(hours=2))
        Orc.objects.filter(pk=orc.pk).update(r_money=KB10_R_MONEY)
        orc.refresh_from_db()
        self.assertEqual(scheduler.is_real(orc), real)
        self.quiet(orc, at)
        return orc

    def quiet(self, orc, at):
        """The memory a tick that recorded the birth wake an hour before
        `at` leaves: no W1, W2 or W11 due at `at`."""
        from bot_program.orcs import bars
        from bot_program.orcs.models import Orc
        orc.refresh_from_db()
        f = bars.frame(self.symbol, "4h", asset_class="crypto", now=at)
        end = bars.final_end(f, at) if f is not None else None
        seen = dict(orc.seen or {})
        seen.update({"w1": True, "w2_bar": end.isoformat() if end else None,
                     "w11_at": (at - timedelta(hours=1)).isoformat(),
                     "last_recorded": (at - timedelta(hours=1)).isoformat()})
        Orc.objects.filter(pk=orc.pk).update(seen=seen)
        orc.refresh_from_db()

    def atr(self, at=NOW):
        from bot_program.orcs import drum_bus
        return drum_bus._atr1h(self.symbol, "crypto", at)

    def stop_at(self, share):
        """The stop `share` x ATR(1h) under the quote's last (100.5)."""
        return f"{100.5 - share * self.atr():.6f}"

    # ── the drums ────────────────────────────────────────────────────────

    def drum(self, at, *, kind="stop_hit", origin=None, wave_id=None, hop=0):
        """One drum of the origin Orc, as its close or its tick publishes
        it (drum_bus.publish)."""
        from bot_program.orcs import drum_bus, drums
        origin = origin or self.orc
        payload = (drums.payload_stop_hit(stop="98.00", at=at,
                                          beyond_atr=0.5)
                   if kind == "stop_hit" else
                   drums.payload_lock(what="break-even armed",
                                      price="100.10"))
        return drum_bus.publish(kind, user=self.user, symbol=self.symbol,
                                asset_class="crypto", payload=payload,
                                origin=f"orc:{origin.pk}", orc=origin,
                                at=at, wave_id=wave_id, hop=hop)

    def route(self, at):
        from bot_program.orcs import drum_bus
        with patch("django.utils.timezone.now", return_value=at):
            return drum_bus.route(at)

    def deliver(self, at, **kw):
        """One drum published and routed at `at`; the OrcDrum."""
        d = self.drum(at, **kw)
        self.route(at)
        d.refresh_from_db()
        return d

    # ── the receiver's tick, the render pass, the claim ──────────────────

    def detect(self, orc, at):
        """The tick's detection for `orc` at `at`, the care as it is; W2
        and W11 kept quiet (this module tests W12)."""
        from bot_program.orcs import bars, wake
        from bot_program.orcs.models import Orc
        orc.refresh_from_db()
        f = bars.frame(self.symbol, "4h", asset_class="crypto", now=at)
        end = bars.final_end(f, at) if f is not None else None
        seen = dict(orc.seen or {})
        seen["w2_bar"] = end.isoformat() if end else None
        seen["w11_at"] = (at - timedelta(hours=1)).isoformat()
        Orc.objects.filter(pk=orc.pk).update(seen=seen)
        orc.refresh_from_db()
        row = orc.root_trade
        row._care_tick = {"now": at}
        orc._seen_before = dict(orc.seen or {})
        bot = SimpleNamespace(_tick_broker_cache={}, cfg=self.cfg,
                              _last_ticks={})
        with patch("django.utils.timezone.now", return_value=at):
            return wake.detect(bot, row, "100.5", "", orc)

    def fresh(self, at):
        """The quote 20 s old at `at`: the render's mark is fresh."""
        from market_data.models import LiveQuote
        LiveQuote.objects.filter(instrument__symbol=self.symbol).update(
            updated_at=at - timedelta(seconds=20))

    def render(self, at):
        from bot_program.orcs import wake
        self.fresh(at)
        with patch("django.utils.timezone.now", return_value=at):
            return wake.render_queued()

    def pending_w12(self, orc):
        from bot_program.orcs.models import Orc
        seen = Orc.objects.get(pk=orc.pk).seen or {}
        return [r for r in (seen.get("wake_pending") or {}).get("reasons")
                or [] if r.get("code") == "W12"]

    def carry(self, orc):
        from bot_program.orcs.models import Orc
        return list((Orc.objects.get(pk=orc.pk).seen or {})
                    .get("w12_carry") or [])

    def wave(self, d):
        from bot_program.orcs.models import OrcWave
        return OrcWave.objects.get(user=self.user, wave_id=d.wave_id)

    def dr_entries(self, orc):
        from bot_program.orcs.models import OrcJournal
        return list(OrcJournal.objects.filter(orc=orc, kind="drum")
                    .order_by("at", "id"))

    def drum_wake(self, orc, at, *, first=None):
        """The W12 recorded at `at` once it settled (a drum delivered at
        `first` before, when given), then rendered: the wake, as admission
        left it."""
        if first is not None:
            self.deliver(first)
        w = self.detect(orc, at)
        self.assertIsNotNone(w, "the settled W12 is recorded")
        self.render(at)
        w.refresh_from_db()
        return w

    def urgent_today(self, orc, n, at=NOW):
        """The Orc's urgent drum wakes today, as `n` claims counted them."""
        from bot_program.orcs.models import Orc
        from bot_program.orcs.scheduler import utc_day
        orc.refresh_from_db()
        seen = {**(orc.seen or {}),
                "w12_urgent": {"day": utc_day(at), "n": n}}
        Orc.objects.filter(pk=orc.pk).update(seen=seen)
        orc.refresh_from_db()


# ── THE PAIR (N2, N7, P37) ───────────────────────────────────────────────

class ThePairTests(_Drums):

    def test_drum_wakes_off_journal_the_drum_and_make_no_call(self):
        """With orcs_drums ON as at the site, the minds ON and the line
        set: orcs_drum_wakes ON queues exactly one W12 for one delivery,
        recorded once its wave settled, claimed and sent once (K-B10 on its
        request), its cost booked on its wave; OFF, the next delivery
        journals its drum and no call is sent."""
        from bot_program.orcs.models import OrcWave
        recv = self.receiver()
        _switch(KEY, True)
        t0 = NOW
        d0 = self.deliver(t0)
        [r] = self.pending_w12(recv)
        self.assertEqual((r["key"], r["wave"], r["hop"]),
                         (f"W12:{d0.wave_id}", d0.wave_id, 0))
        self.assertTrue(r["urgent"], "a stop_hit on its own symbol")
        self.assertEqual(len(self.dr_entries(recv)), 1)
        w = self.drum_wake(recv, t0 + timedelta(minutes=16))
        self.assertEqual([x["code"] for x in w.reasons], ["W12"])
        self.assertEqual(w.status, "pending")
        got = self.serve(now=t0 + timedelta(minutes=16),
                         script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w.pk)
        self.assert_one_call()
        self.assert_no_account_figure()
        self.assertEqual(self.wave(d0).w12_answered, 1)
        from bot_program.orcs.models import OrcJournal
        decision = OrcJournal.objects.filter(orc=recv,
                                             kind="decision").latest("id")
        self.assertGreater(decision.cost_usd, 0)
        self.assertAlmostEqual(float(self.wave(d0).cost_usd),
                               float(decision.cost_usd), places=6,
                               msg="the settle books its spend on its wave")
        # OFF: the same fixture, the next wave journaled, nothing sent
        _switch(KEY, False)
        t1 = t0 + timedelta(minutes=60)
        d1 = self.deliver(t1)
        self.assertEqual([e.body["wave"] for e in self.dr_entries(recv)],
                         [d0.wave_id, d1.wave_id])
        self.assertEqual(self.pending_w12(recv), [])
        self.assertFalse(OrcWave.objects.filter(wave_id=d1.wave_id).exists())
        self.assertIsNone(self.detect(recv, t1 + timedelta(minutes=16)))
        self.render(t1 + timedelta(minutes=16))
        self.assertIsNone(self.serve(now=t1 + timedelta(minutes=16))["wake"])
        self.assert_no_call()


# ── OFF: O1's delivery, byte for byte ────────────────────────────────────

class TheOffWorldsTests(_Drums):

    def _off_world(self, recv, at):
        """One delivery routed with the gate OFF: O1's DR entry, memory,
        return and drum, and no OrcWave row."""
        from bot_program.orcs import drums
        from bot_program.orcs.models import Orc, OrcWave
        before = dict(Orc.objects.get(pk=recv.pk).seen or {})
        d = self.drum(at)
        self.assertEqual(self.route(at), 1, "route's return: one delivery")
        d.refresh_from_db()
        e = self.dr_entries(recv)[-1]
        self.assertEqual(sorted(e.body), sorted(O1_BODY))
        self.assertEqual(e.body, {"fk": "drum", "drum": d.pk,
                                  "drum_kind": "stop_hit", "symbol": "BTCUSD",
                                  "relation": "same symbol", "hop": 0,
                                  "wave": d.wave_id})
        self.assertEqual(e.headline, drums.line(
            {"kind": d.kind, "symbol": d.symbol, "hop": d.hop,
             "payload": d.payload}, "same symbol", e.fact_id))
        after = dict(Orc.objects.get(pk=recv.pk).seen or {})
        changed = {k for k in set(before) | set(after)
                   if before.get(k) != after.get(k)}
        self.assertEqual(changed, {"drum_waves", "drum_seq"},
                         "the delivery remembers its wave and its DR id only")
        self.assertEqual(after["drum_waves"][-1], d.wave_id)
        self.assertNotIn("wake_pending", after)
        self.assertNotIn("w12_carry", after)
        self.assertEqual(d.reach, [{"orc": recv.pk,
                                    "relation": "same symbol"}])
        self.assertEqual(d.routed_at, at)
        self.assertFalse(OrcWave.objects.exists())

    def test_every_world_the_gate_reads_off_delivers_as_o1(self):
        recv = self.receiver()
        # the drum wakes' switch absent, as it ships
        self._off_world(recv, NOW)
        # the drum wakes ON, the drums' switch OFF
        _switch(KEY, True)
        _switch(DRUMS, False)
        self._off_world(recv, NOW + timedelta(minutes=20))
        # both ON, a gate of the minds OFF (the minds switch)
        _switch(DRUMS, True)
        _switch("orcs_minds", False)
        self._off_world(recv, NOW + timedelta(minutes=40))
        # both ON, the Orcs line at 0
        _switch("orcs_minds", True)
        with self.settings(AI_CONFIG={**settings.AI_CONFIG,
                                      "orc_daily_budget_usd": 0}):
            self._off_world(recv, NOW + timedelta(minutes=60))

    def test_turned_off_a_queued_drum_wake_ends_by_code_and_no_call(self):
        """Frictionless off (N2): a W12 queued while the switch was ON is
        answered by code once it is OFF, at its admission or at its claim
        (drum_wakes_off), its drum journaled as it was; one read before
        the switch went OFF is the pair's positive control."""
        from bot_program.orcs.models import OrcJournal
        _switch(KEY, True)
        a, b, c = self.receiver(), self.receiver(), self.receiver()
        d = self.deliver(NOW)
        at = NOW + timedelta(minutes=16)
        wa = self.drum_wake(a, at)
        got = self.serve(now=at, script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, wa.pk)
        self.assert_one_call()
        wb = self.drum_wake(b, at)
        self.assertEqual(wb.status, "pending", "admitted while ON")
        _switch(KEY, False)
        wc = self.drum_wake(c, at)
        self.assertEqual((wc.status, wc.skipped_reason),
                         ("skipped", "drum_wakes_off"), "at its admission")
        self.assertIsNone(self.serve(now=at)["wake"])
        wb.refresh_from_db()
        self.assertEqual((wb.status, wb.skipped_reason),
                         ("skipped", "drum_wakes_off"), "at its claim")
        self.assert_no_call()
        for orc, w in ((b, wb), (c, wc)):
            body = OrcJournal.objects.get(orc=orc, kind="budget", wake=w).body
            self.assertEqual((body["code"], body["wave"]),
                             ("drum_wakes_off", d.wave_id))
            self.assertEqual(len(self.dr_entries(orc)), 1)
        self.assertEqual(self.wave(d).breaker, {}, "no breaker opens")
        self.assertEqual(self.wave(d).w12_answered, 1)

    def test_the_gate_reads_the_drums_switch_first(self):
        """drums_on() has its first reader, once a pass: OFF, the drum
        wakes' switch and the minds' gates are not even read."""
        from bot_program.orcs import drum_bus, switches
        recv = self.receiver()
        _switch(KEY, True)
        self.drum(NOW)
        with patch.object(drum_bus, "drums_on",
                          return_value=False) as drums_on, \
                patch.object(switches, "drum_wakes_on") as wakes, \
                patch.object(switches, "gate_code") as gate:
            self.route(NOW)
        drums_on.assert_called_once_with()
        wakes.assert_not_called()
        gate.assert_not_called()
        self.assertEqual(len(self.dr_entries(recv)), 1)
        self.assertEqual(self.pending_w12(recv), [])


# ── urgency (C.14, P15) ──────────────────────────────────────────────────

class TheUrgencyTests(_Drums):

    def test_a_stop_hit_on_its_own_symbol_is_urgent_wherever_its_stop(self):
        _switch(KEY, True)
        far = self.receiver(stop=self.stop_at(3.0))
        self.deliver(NOW)
        [r] = self.pending_w12(far)
        self.assertTrue(r["urgent"])
        self.assertTrue(r["own"])
        self.assertEqual(r["drum"], "stop_hit")

    def test_its_stop_within_a_quarter_atr_is_urgent_half_an_atr_is_not(self):
        _switch(KEY, True)
        near = self.receiver(stop=self.stop_at(0.2))
        half = self.receiver(stop=self.stop_at(0.5))
        d = self.deliver(NOW, kind="lock")
        [rn] = self.pending_w12(near)
        [rh] = self.pending_w12(half)
        self.assertEqual((rn["urgent"], rn["own"]), (True, False))
        self.assertEqual((rh["urgent"], rh["own"]), (False, False))
        # O1's own rule (1 x ATR(1h)) would call both urgent: W12 narrows it
        from bot_program.orcs import drum_bus
        half.refresh_from_db()
        self.assertTrue(drum_bus._urgent_for(half, d, NOW))

    def test_the_render_reads_the_urgency_again_as_of_the_wakes_moment(self):
        """P15: a W12 queued routine (its stop 0.5 ATR away) whose stop
        moved within 0.25 ATR before the wake's moment is urgent in the
        survivor the render leaves to admission, and ranks so."""
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import bars
        _switch(KEY, True)
        recv = self.receiver(stop=self.stop_at(0.5))
        self.deliver(NOW, kind="lock")
        [r] = self.pending_w12(recv)
        self.assertFalse(r["urgent"])
        AssetBotTrade.objects.filter(pk=recv.root_trade_id).update(
            stop_loss=Decimal(self.stop_at(0.2)))
        at = NOW + timedelta(minutes=16)
        w = self.drum_wake(recv, at)
        [got] = w.reasons
        vctx = w.components["vctx"]
        atr = bars.frame(self.symbol, "1h", asset_class="crypto", now=at).atr
        self.assertLessEqual(abs(vctx["m"] - vctx["effective"]), 0.25 * atr)
        self.assertTrue(got["urgent"], "read again at the render")
        self.assertTrue(vctx["urgent"])
        self.assertEqual((w.status, w.priority), ("pending", 1.0),
                         "a paper urgent wake's rank")
        # and back: a stop moved away reads routine again
        AssetBotTrade.objects.filter(pk=recv.root_trade_id).update(
            stop_loss=Decimal(self.stop_at(0.5)))
        from bot_program.orcs import wake
        again = wake._w12_again([got], {"m": vctx["m"],
                                        "effective": float(self.stop_at(0.5)),
                                        "atr1h": atr})
        self.assertFalse(again[0]["urgent"])
        kept = wake._w12_again([{**got, "urgent": False, "carried": True}],
                               {"m": vctx["m"], "effective": vctx["m"],
                                "atr1h": atr})
        self.assertFalse(kept[0]["urgent"], "a carried W12 stays routine")


# ── the settle (C.15) ────────────────────────────────────────────────────

class TheSettleTests(_Drums):

    def test_no_w12_is_recorded_before_its_wave_settled_then_it_is(self):
        from bot_program.orcs.constants import DRUM_SETTLE_MIN
        self.assertEqual(DRUM_SETTLE_MIN, 15)
        _switch(KEY, True)
        recv = self.receiver()
        d = self.deliver(NOW)
        for minutes in (0, 5, 14):
            with self.subTest(minutes=minutes):
                self.assertIsNone(self.detect(recv, NOW + timedelta(
                    minutes=minutes)))
                self.assertEqual(len(self.pending_w12(recv)), 1,
                                 "not recorded, not consumed")
        w = self.detect(recv, NOW + timedelta(minutes=15))
        self.assertEqual([r["key"] for r in w.reasons], [f"W12:{d.wave_id}"])
        self.assertEqual(self.pending_w12(recv), [])

    def test_the_drums_that_join_within_fifteen_minutes_wake_it_once(self):
        from bot_program.orcs.models import OrcWake
        _switch(KEY, True)
        recv = self.receiver()
        first = self.deliver(NOW)
        for minutes in (5, 10):
            d = self.deliver(NOW + timedelta(minutes=minutes))
            self.assertEqual(d.wave_id, first.wave_id, "it joined the wave")
        self.assertEqual(len(self.dr_entries(recv)), 1, "one per wave")
        self.assertEqual(len(self.pending_w12(recv)), 1)
        wave = self.wave(first)
        self.assertEqual((wave.drums, wave.first_at, wave.last_at),
                         (3, NOW, NOW + timedelta(minutes=10)))
        self.assertIsNotNone(self.detect(recv, NOW + timedelta(minutes=16)))
        for minutes in (20, 35, 50):
            self.assertIsNone(self.detect(recv, NOW + timedelta(
                minutes=minutes)))
        self.assertEqual(OrcWake.objects.filter(orc=recv).count(), 1)

    def test_an_unsettled_w12_survives_a_wake_recorded_for_another_reason(
            self):
        from bot_program.models import AssetBotTrade
        _switch(KEY, True)
        recv = self.receiver()
        d = self.deliver(NOW)
        row = recv.root_trade
        meta = dict(row.metadata or {})
        meta["care"] = {"mfe_r": 0.2, "r_now": -0.6, "mae_r": -0.6}
        AssetBotTrade.objects.filter(pk=row.pk).update(metadata=meta)
        w = self.detect(recv, NOW + timedelta(minutes=5))
        self.assertEqual([r["code"] for r in w.reasons], ["W4"])
        self.assertEqual([r["key"] for r in self.pending_w12(recv)],
                         [f"W12:{d.wave_id}"], "it waits for its wave")
        later = self.detect(recv, NOW + timedelta(minutes=16))
        self.assertEqual([r["code"] for r in later.reasons], ["W12"])


# ── the breaker (C.16) ───────────────────────────────────────────────────

class TheWaveBreakerTests(_Drums):

    def test_the_seventh_drum_wake_of_a_wave_ends_drum_breaker(self):
        """A wave's sixth drum wake reaches a model; the seventh ends
        drum_breaker at its claim, the wave records {open, why}, and its
        next delivery is journaled only."""
        from bot_program.orcs.constants import DRUM_WAVE_WAKES
        from bot_program.orcs.models import OrcJournal, OrcWave
        self.assertEqual(DRUM_WAVE_WAKES, 6)
        _switch(KEY, True)
        a, b = self.receiver(), self.receiver()
        d = self.deliver(NOW)
        OrcWave.objects.filter(pk=self.wave(d).pk).update(w12_answered=5)
        at = NOW + timedelta(minutes=16)
        wa = self.drum_wake(a, at)
        wb = self.drum_wake(b, at)
        self.assertEqual((wa.status, wb.status), ("pending", "pending"))
        got = self.serve(now=at, script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, wa.pk)
        self.assert_one_call()
        self.assertEqual(self.wave(d).w12_answered, 6, "the claim counts")
        got = self.serve(now=at)
        self.assertIsNone(got["wake"])
        wb.refresh_from_db()
        self.assertEqual((wb.status, wb.skipped_reason),
                         ("skipped", "drum_breaker"))
        self.assert_no_call()
        breaker = self.wave(d).breaker
        self.assertEqual(breaker["state"], "open")
        self.assertIn("6", breaker["why"])
        budget = OrcJournal.objects.get(orc=b, kind="budget", wake=wb)
        self.assertEqual((budget.body["code"], budget.body["wave"]),
                         ("drum_breaker", d.wave_id))
        # the wave's next delivery is journaled only, as in O1
        c = self.receiver(at=at)
        self.deliver(at, wave_id=d.wave_id)
        [e] = self.dr_entries(c)
        self.assertEqual(e.body["w12"], "breaker")
        self.assertEqual(self.pending_w12(c), [])
        self.assertEqual(self.carry(c), [])

    def test_the_thirteenth_drum_wake_of_a_user_in_an_hour_ends_drum_breaker(
            self):
        from bot_program.orcs.constants import DRUM_USER_HOUR_WAKES
        from bot_program.orcs.models import OrcWake
        self.assertEqual(DRUM_USER_HOUR_WAKES, 12)
        _switch(KEY, True)
        a, b = self.receiver(), self.receiver()
        at = NOW + timedelta(minutes=16)
        # eleven drum wakes of the user reached a model within the hour,
        # one more before the hour (it no longer counts)
        for i, ago in enumerate([5] * 11 + [61]):
            OrcWake.objects.create(
                orc=self.orc, reasons=[_w12(f"old{i}")],
                dedupe_key=f"old{i}", kind="material", status="done",
                started_at=at - timedelta(minutes=ago),
                components={"drum": {"wave": f"old{i}", "hop": 0}})
        wa = self.drum_wake(a, at, first=NOW)
        got = self.serve(now=at, script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, wa.pk, "the twelfth runs")
        self.assert_one_call()
        d2 = self.deliver(NOW + timedelta(minutes=17))
        wb = self.drum_wake(b, NOW + timedelta(minutes=33))
        wb.refresh_from_db()
        self.assertEqual((wb.status, wb.skipped_reason),
                         ("skipped", "drum_breaker"))
        self.assert_no_call()
        self.assertEqual(self.wave(d2).breaker["state"], "open")


class TheUrgentCarryTests(_Drums):

    def test_the_third_urgent_w12_of_a_day_waits_and_joins_the_next_wake(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.constants import DRUM_URGENT_PER_ORC_DAY
        self.assertEqual(DRUM_URGENT_PER_ORC_DAY, 2)
        _switch(KEY, True)
        recv = self.receiver()
        self.urgent_today(recv, 2)
        d = self.deliver(NOW)
        self.assertEqual(self.pending_w12(recv), [])
        [c] = self.carry(recv)
        self.assertEqual((c["key"], c["urgent"], c["carried"]),
                         (f"W12:{d.wave_id}", False, True))
        [e] = self.dr_entries(recv)
        self.assertEqual(e.body["w12"], "carried", "the delivery journaled")
        self.assertEqual(self.wave(d).w12_queued, 1)
        self.assertIsNone(self.detect(recv, NOW + timedelta(minutes=16)),
                          "no wake of its own")
        # the next recorded wake carries it, routine, and consumes it
        row = recv.root_trade
        meta = dict(row.metadata or {})
        meta["care"] = {"mfe_r": 0.2, "r_now": -0.6, "mae_r": -0.6}
        AssetBotTrade.objects.filter(pk=row.pk).update(metadata=meta)
        w = self.detect(recv, NOW + timedelta(minutes=20))
        self.assertEqual([(r["code"], r["urgent"]) for r in w.reasons],
                         [("W4", True), ("W12", False)])
        self.assertTrue(w.reasons[1]["carried"])
        self.assertEqual(self.carry(recv), [])
        # a day later the count starts again
        self.urgent_today(recv, 2, at=NOW - timedelta(days=1))
        d2 = self.deliver(NOW + timedelta(minutes=40))
        [r] = self.pending_w12(recv)
        self.assertEqual((r["key"], r["urgent"]), (f"W12:{d2.wave_id}", True))

    def test_twenty_own_symbol_waves_make_two_urgent_drum_wakes(self):
        """One real Orc, twenty waves of stop hits on its own symbol, each
        delivered 20 minutes after the last: two urgent drum wakes reach a
        model; the third, delivered while the second still waited for its
        claim, is held by the claim's guard (drum_carry) and its W12 waits
        in the carry with the seventeen carried at their delivery."""
        from bot_program.orcs.constants import MODEL_ANSWERED
        from bot_program.orcs.models import OrcWake
        from bot_program.orcs.scheduler import utc_day
        _switch(KEY, True)
        real = self.receiver(real=True)
        step = timedelta(minutes=20)
        t = [NOW + i * step for i in range(20)]
        settle = timedelta(minutes=16)
        # wave 1: delivered, recorded, rendered, claimed and read
        self.drum_wake(real, t[0] + settle, first=t[0])
        got = self.serve(now=t[0] + settle, script=fake_answer(answer()))
        self.assertIsNotNone(got["wake"])
        self.assert_one_call()
        # wave 2: recorded and admitted, its claim not yet made
        w2 = self.drum_wake(real, t[1] + settle, first=t[1])
        self.assertEqual(w2.status, "pending")
        # wave 3, delivered while the second waits: one claimed so far
        self.deliver(t[2])
        self.assertEqual(len(self.pending_w12(real)), 1)
        got = self.serve(now=t[2], script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, w2.pk)
        self.assert_one_call()
        w3 = self.drum_wake(real, t[2] + settle)
        self.assertEqual((w3.status, w3.skipped_reason),
                         ("skipped", "drum_carry"))
        self.assertEqual(len(self.carry(real)), 1)
        # waves 4 to 20: carried at their delivery, no wake of their own
        for at in t[3:]:
            self.deliver(at)
            self.assertIsNone(self.detect(real, at + settle))
        self.render(t[-1] + settle)
        self.assertIsNone(self.serve(now=t[-1] + settle)["wake"])
        self.assert_no_call()
        drum = [w for w in OrcWake.objects.filter(
                orc=real, status__in=MODEL_ANSWERED)
                if (w.components or {}).get("drum")
                and (w.components or {}).get("urgent")]
        self.assertEqual(len(drum), 2)
        real.refresh_from_db()
        self.assertEqual(real.seen["w12_urgent"],
                         {"day": utc_day(NOW), "n": 2})
        self.assertEqual(len(self.carry(real)), 18)
        self.assertTrue(all(not c["urgent"] and c["carried"]
                            for c in self.carry(real)))


class TheShareAndTheLineTests(_Drums):

    def _book_drums(self, usd):
        """W12 spend booked today on another wave of the user's."""
        from bot_program.orcs.models import OrcWave
        OrcWave.objects.update_or_create(
            user=self.user, wave_id="booked", defaults={
                "kind": "stop_hit", "first_at": NOW - timedelta(hours=1),
                "last_at": NOW - timedelta(hours=1),
                "cost_usd": Decimal(str(usd))})

    def test_drum_wakes_stop_at_a_quarter_of_the_line_urgent_included(self):
        from bot_program.orcs.constants import DRUM_SHARE
        from bot_program.orcs.models import OrcJournal
        self.assertEqual(DRUM_SHARE, 0.25)
        _switch(KEY, True)
        a, b = self.receiver(), self.receiver()
        self._book_drums(1.0)
        at = NOW + timedelta(minutes=16)
        wa = self.drum_wake(a, at, first=NOW)
        self.assertEqual(wa.status, "pending", "1.00 + its bound fits 1.50")
        self.assertTrue(wa.components["urgent"])
        self.serve(now=at, script=fake_answer(answer()))
        self.assert_one_call()
        self._book_drums(1.45)
        wb = self.drum_wake(b, NOW + timedelta(minutes=40),
                            first=NOW + timedelta(minutes=24))
        self.assertEqual((wb.status, wb.skipped_reason),
                         ("skipped", "drum_share"))
        self.assertTrue(any(r["urgent"] for r in wb.reasons),
                        "urgent included")
        self.assertIsNone(self.serve(now=NOW + timedelta(minutes=40))["wake"])
        self.assert_no_call()
        body = OrcJournal.objects.get(orc=b, kind="budget", wake=wb).body
        self.assertEqual(body["code"], "drum_share")
        self.assertGreater(body["bound_usd"], 0)
        self.assertEqual(body["line"]["cap"], 6.0)

    def test_the_share_counts_drum_money_in_flight_once(self):
        """drum_inflight: a running drum wake's bound and a drum wake's
        unbilled hold; never a drum wake's ledger-gap hold (the settle
        booked its cost on its wave, drum_booked), nor any other wake's
        bound or hold."""
        from bot_program.orcs import scheduler
        from bot_program.orcs.constants import (HOLD_LEDGER_GAP,
                                                HOLD_UNBILLED)
        from bot_program.orcs.models import OrcWake

        def wake(key, status, drum, est="0"):
            return OrcWake.objects.create(
                orc=self.orc, reasons=[_w12(key)], dedupe_key=key,
                kind="material", status=status, est_usd=Decimal(est),
                components={"drum": {"wave": key, "hop": 0}} if drum else {})
        wake("running", "running", True, "0.25")
        wake("plain", "running", False, "0.5")
        for key, drum, kind, usd in (("unbilled", True, HOLD_UNBILLED, 0.1),
                                     ("gap", True, HOLD_LEDGER_GAP, 0.2),
                                     ("other", False, HOLD_UNBILLED, 0.4)):
            scheduler.hold(kind=kind, usd=usd, wake=wake(key, "done", drum),
                           rung="r0", now=NOW)
        self.assertAlmostEqual(scheduler.drum_inflight(NOW), 0.35, places=6)

    def test_past_sixty_percent_only_an_urgent_own_stakes_w12_runs(self):
        from bot_program.orcs.constants import DRUM_LINE_SHARE
        self.assertEqual(DRUM_LINE_SHARE, 0.60)
        _switch(KEY, True)
        real = self.receiver(real=True)
        paper_urgent = self.receiver()
        self.book(3.60)
        at = NOW + timedelta(minutes=16)
        # a stop hit on their own symbol: urgent, on their own stakes
        self.deliver(NOW)
        # a real one runs inside its triage ceiling (C)
        wr = self.drum_wake(real, at)
        self.assertEqual(wr.status, "pending")
        got = self.serve(now=at, script=fake_answer(answer()))
        self.assertEqual(got["wake"].pk, wr.pk)
        self.assert_one_call()
        # a paper one passes the 60% rule and meets its own ceiling (60%)
        wu = self.drum_wake(paper_urgent, at)
        self.assertTrue(all(r["urgent"] for r in wu.reasons))
        self.assertEqual((wu.status, wu.skipped_reason),
                         ("skipped", "triage"))
        # a routine W12 (its stop 0.5 ATR away) ends drum_line
        later = NOW + timedelta(minutes=20)
        paper = self.receiver(stop=self.stop_at(0.5), at=later)
        self.deliver(later, kind="lock")
        wp = self.drum_wake(paper, later + timedelta(minutes=16))
        self.assertFalse(any(r["urgent"] for r in wp.reasons))
        self.assertEqual((wp.status, wp.skipped_reason),
                         ("skipped", "drum_line"))
        self.assertIsNone(self.serve(now=later + timedelta(
            minutes=16))["wake"])
        self.assert_no_call()


# ── the wave stamp (C.17) ────────────────────────────────────────────────

class TheIntentStampTests(QueueFixture):

    def _tighten(self, reasons, *, done=False):
        """A wake of `reasons` rendered, claimed and answered with a tighten
        to a level of its own menu; its OrcIntent (validated or refused,
        an intent is written either way)."""
        from bot_program.orcs import validator
        from bot_program.orcs.models import OrcIntent
        w = self.claim(self.rendered(reasons))
        vctx = w.components["vctx"]
        lid = next(lv["id"] for lv in vctx["menu"]
                   if lv.get("kind") in ("swing", "pool", "round")
                   and lv.get("stop") is not None
                   and not validator._v7(lv, vctx, "BUY")[1])
        cites = [k for k, v in validator.facts_index(self.orc, as_of=NOW)
                 .items() if v["kind"] in ("structure", "bar", "care")][:1]
        out = self.think(w, fake_answer(answer(action="tighten", level_id=lid,
                                               facts_cited=cites)))
        if done:
            self.assertEqual(out["status"], "done")
        return OrcIntent.objects.get(wake=w)

    def test_an_intent_from_a_w12_wake_carries_its_wave_others_none(self):
        """One documented rule: the newest wave of the wake's W12 reasons
        (the latest first_at)."""
        older = _w12("stop_hit:BTCUSD:20261022120000", urgent=False,
                     first_at=NOW - timedelta(hours=1))
        newer = _w12("stop_hit:BTCUSD:20261022125000", urgent=False, hop=1,
                     first_at=NOW - timedelta(minutes=40))
        W1 = {"code": "W1", "key": "W1", "t": "birth", "urgent": True}
        it = self._tighten([W1, older, newer], done=True)
        self.assertEqual(it.wave_id, "stop_hit:BTCUSD:20261022125000")
        self.assert_one_call()
        from bot_program.orcs.models import OrcIntent
        plain = self._tighten([{"code": "W4", "key": "W4:-0.5",
                                "t": "-0.5R reached", "urgent": True}])
        self.assertEqual(plain.wave_id, "")
        self.assert_one_call()
        self.assertEqual(OrcIntent.objects.filter(wave_id="").count(), 1)


class TheArmStampTests(ArmFixture):
    """The O arm's would-stop carries the wave and its hop; nothing else
    does (C.17)."""

    WAVE = "stop_hit:BTCUSD:20261014101500"

    def _w12_wake(self):
        from bot_program.orcs.models import OrcWake
        from tests.orcs.test_orc_o2a_arm import VCTX
        n = OrcWake.objects.count()
        return OrcWake.objects.create(
            orc=self.orc, reasons=[_w12(self.WAVE, hop=1)],
            dedupe_key=f"w12:{self.orc.pk}:{n}", kind="material",
            status="done", components={"vctx": dict(VCTX)})

    def test_a_w12_tighten_stamps_the_arm_and_nothing_else(self):
        from bot_program.orcs.models import OrcIntent
        self.tick("102.2", 30)
        it = self.queue("tighten", 31, level=S1H, would_stop=101.0,
                        wake=self._w12_wake())
        OrcIntent.objects.filter(pk=it.pk).update(wave_id=self.WAVE)
        self.tick("102.4", 32)
        state = self.arm().state
        self.assertEqual(state["orc_stop"], 101.0)
        self.assertEqual(state["orc_stop_wave"], {"wave": self.WAVE,
                                                  "hop": 1})
        # a tighten from a wake with no W12 moves the stop and drops it
        P = dict(S1H, level_id="S1h-L2", price=101.6, stop=101.4)
        self.queue("tighten", 33, level=P, would_stop=101.4)
        self.tick("102.6", 34)
        state = self.arm().state
        self.assertEqual(state["orc_stop"], 101.4)
        self.assertNotIn("orc_stop_wave", state)

    def test_other_intents_carry_neither_key(self):
        from bot_program.orcs.models import OrcIntent
        self.tick("102.2", 30)
        it = self.queue("tighten", 31, level=S1H, would_stop=101.0)
        self.tick("102.4", 32)
        it.refresh_from_db()
        self.assertEqual((it.status, it.wave_id), ("simulated", ""))
        self.assertNotIn("orc_stop_wave", self.arm().state)
        self.queue("trim", 33, share=0.5)
        self.tick("102.5", 34)
        self.assertNotIn("orc_stop_wave", self.arm().state)
        self.assertFalse(OrcIntent.objects.exclude(wave_id="").exists())

    def test_a_would_stop_hit_publishes_no_drum_and_no_real_stop_a_wave(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import drum_bus
        from bot_program.orcs.ghost import RealExit
        from bot_program.orcs.models import OrcDrum, OrcIntent
        self.tick("102.2", 30)
        it = self.queue("tighten", 31, level=S1H, would_stop=101.0,
                        wake=self._w12_wake())
        OrcIntent.objects.filter(pk=it.pk).update(wave_id=self.WAVE)
        self.tick("102.4", 32)
        self.assertEqual(self.arm().state["orc_stop_wave"]["wave"], self.WAVE)
        # the would-stop is hit: the O arm exits, no drum is published
        drums = OrcDrum.objects.count()
        self.tick("100.9", 33)
        arm = self.arm()
        self.assertFalse(arm.open)
        self.assertEqual(arm.state["exit"]["kind"], "orc")
        self.assertEqual(OrcDrum.objects.count(), drums)
        self.assertFalse(OrcDrum.objects.filter(kind="stop_hit").exists())
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, "OPEN", "the care holds the row")
        self.assertNotIn(self.WAVE, json.dumps(self.row.metadata))
        # the real stop: its drum is hop 0, on a wave of its own
        AssetBotTrade.objects.filter(pk=self.row.pk).update(
            status="CLOSED", exit_price=Decimal("98"),
            closed_at=self.at(40))
        self.row.refresh_from_db()
        with patch("bot_program.orcs.ghost.real_exit_of",
                   return_value=RealExit("venue_stop", level=98.0,
                                         at=self.at(40))):
            d = drum_bus.on_close(self.orc, self.row)
        self.assertEqual(d.hop, 0)
        self.assertNotEqual(d.wave_id, self.WAVE)
        self.assertNotIn("wave", d.payload)
        self.assertNotIn(self.WAVE, json.dumps(self.row.metadata))


# ── the frozen close (N1.2, N1 test item h) ──────────────────────────────

class TheFrozenCloseTests(MindTestCase):

    def test_on_close_comments_stripped_has_its_frozen_ast(self):
        from bot_program.orcs import drum_bus
        src = textwrap.dedent(inspect.getsource(drum_bus.on_close))
        self.assertEqual(ast.dump(ast.parse(src)),
                         ast.dump(ast.parse(FROZEN_ON_CLOSE)))
        self.assertIn("# O3:", src, "the seam is re-marked for O3")
        self.assertNotIn("# O2:", src)


# ── N2: the switches ─────────────────────────────────────────────────────

class TheDrumWakesSwitchShipsOffTests(MindTestCase):

    def setUp(self):
        from core.platform_control import seed_components
        cache.clear()
        seed_components()

    def test_it_is_seeded_off_beside_the_drums(self):
        from core.platform_control import DEFAULT_COMPONENTS

        from bot_program.orcs import switches
        from bot_program.orcs.constants import DRUM_WAKES_SWITCH
        self.assertEqual(DRUM_WAKES_SWITCH, KEY)
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
        self.assertEqual(keys.index(KEY), keys.index(DRUMS) + 1)
        self.assertFalse(switches.drum_wakes_on())
        _switch(KEY, True)
        self.assertTrue(switches.drum_wakes_on())
        with patch("core.platform_control.is_component_enabled",
                   side_effect=RuntimeError("the table is gone")):
            self.assertFalse(switches.drum_wakes_on())

    def test_it_is_exempt_held_back_and_never_live(self):
        from core import switch_pin
        from core.platform_control import (BULK_ENABLE_EXEMPT,
                                           LIVE_MONEY_SWITCHES,
                                           ORC_MIND_SWITCHES, PIN_SWITCHES)
        self.assertIn(KEY, ORC_MIND_SWITCHES)
        self.assertIn(KEY, BULK_ENABLE_EXEMPT)
        self.assertIn(KEY, PIN_SWITCHES)
        self.assertNotIn(KEY, LIVE_MONEY_SWITCHES)
        switch_pin.set_category("system", True, via=switch_pin.VIA_ALL_ON)
        self.assertFalse(_row_of(KEY).is_enabled,
                         '"all on" never reaches it')

    def test_the_drums_switch_keeps_its_name_and_says_c19(self):
        """orcs_drums keeps its O1 meaning (drums journaled), outside both
        tuples: "all on" may turn it on, and its ON alone wakes nobody."""
        from core import switch_pin
        from core.platform_control import (BULK_ENABLE_EXEMPT,
                                           DEFAULT_COMPONENTS,
                                           ORC_MIND_SWITCHES, PIN_SWITCHES)
        [entry] = [c for c in DEFAULT_COMPONENTS if c["key"] == DRUMS]
        self.assertEqual(entry["name"], DRUMS_NAME)
        self.assertEqual(entry["description"], DRUMS_DESCRIPTION)
        self.assertLess(len(entry["description"]), 300)
        self.assertNotIn(DRUMS, ORC_MIND_SWITCHES)
        self.assertNotIn(DRUMS, BULK_ENABLE_EXEMPT)
        self.assertNotIn(DRUMS, PIN_SWITCHES)
        self.assertFalse(switch_pin.needs_pin(DRUMS, was_on=False,
                                              want_on=True))


class OnlyThePinTurnsTheDrumWakesOnTests(MindTestCase):

    def setUp(self):
        from core.platform_control import seed_components
        from portfolio.trader_profile import get_or_create_profile
        cache.clear()
        seed_components()
        self.admin = get_user_model().objects.create_superuser(
            "o2c_drums_admin", "o2c_drums@example.test", "x")
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
        from core import switch_pin
        self.assertFalse(switch_pin.set_switch(
            KEY, True, via=switch_pin.VIA_SHELL).ok)
        self.assertFalse(_row_of(KEY).is_enabled, "no door armed it")

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


# ── the words ────────────────────────────────────────────────────────────

class TheDrumWordsTests(MindTestCase):

    def test_the_codes_have_their_words(self):
        from bot_program.orcs import notes, scheduler
        from bot_program.orcs.constants import WAKE_CODE_WORDS, WAKE_CODES
        for code in ("drum_breaker", "drum_carry", "drum_line",
                     "drum_share", "drum_wakes_off"):
            with self.subTest(code):
                self.assertIn(code, WAKE_CODES)
                self.assertTrue(notes.wake_status_t("skipped", code)
                                .startswith("answered by code: "))
                self.assertNotIn("$", WAKE_CODE_WORDS[code])
        self.assertIn("drum_share", scheduler.BUDGET_CODES)
        self.assertIn("drum_line", scheduler.BUDGET_CODES)
        self.assertNotIn("drum_breaker", scheduler.BUDGET_CODES)
        self.assertNotIn("drum_carry", scheduler.BUDGET_CODES)
        self.assertNotIn("drum_wakes_off", scheduler.BUDGET_CODES)

    def test_the_runbook_says_the_pin_step_and_the_breaker(self):
        text = RUNBOOK.read_text(encoding="utf-8")
        head = "### The Orcs' drum wakes (O2c)"
        self.assertIn(head, text)
        section = text.split(head, 1)[1].split("\n## ", 1)[0] \
            .split("\n### ", 1)[0]
        flat = _fold(section)
        for words in (NAME, KEY, DRUMS, "/ops/", "trading PIN",
                      "takes no PIN", "15 minutes", "2 urgent", "25%",
                      "60%", "6 drum wakes", "12 drum wakes",
                      "drum_wakes_off"):
            with self.subTest(words):
                self.assertIn(words, flat)
        o1c = _fold(text.split("**The war drums**", 1)[1].split("\n####",
                                                               1)[0])
        self.assertNotIn("In O1 a drum wakes nobody", o1c)
        self.assertIn(KEY, o1c)
