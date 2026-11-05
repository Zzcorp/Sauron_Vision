"""T13, A QUEUED PROPOSAL STEPS ONLY THE SHADOW ARM (the O2 spec A.41-A.45b,
P32, P33; §1.1.7 T13; 2026-11-05).

The settle queues a proposal in shadow (an OrcIntent `queued`, its id in
seen["intents_queued"]); the next tick takes it (intents.take, called from
ghost._step_orc) and steps the Orc's own arm, the O arm, in would mode.
Every tick here is the real care() then the Orcs' hook, on a paper BTCUSD
long (entry 100, stop 98: 1R is 2), the clock pinned, and each intent is
queued as the settle queues one.

- applied at the first tick after validation and priced by pricing.py:
  the status, the price and the R, the queue left under the Orc's lock
  (an id the settle added meanwhile stays), the card's intents
- P33: the Orc and T-STRUCT naming S1h-L1 hold the same stop; an Orc that
  follows P-LOCK puts orc_stop at BE
- P32: an exit validated at Friday's close waits through the shut and
  expires at the reopen, never filled at the gap
- `moved` at the tick: no room left on the tick's price, or no longer
  tighter than the arm's effective stop
- would mode: entered from `real` as _to_shadow enters shadow, with no
  hand; first_divergence; the faith block kept; a would-stop exit labelled
  `orc`
- after the close: step_bars expires the queued intents with `row_closed`
  and walks the would arm on its orc_stop; an intent after the arm closed
  expires `arm_closed`
- a lock waiver: the arm's care reads a copy of the context without the
  event, and the tick's own context keeps it
- an add never moves the arm; a care_owned Orc's proposals are `recorded`,
  and one queued before the takeover is never applied: it expires `ttl`
- the query budget: a tick with nothing queued reads no intent; a write
  that fails leaves the arm and the queue as they were

Run with:  python manage.py test tests.orcs.test_orc_o2a_arm
"""
import ast
import copy
import inspect
import json
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test.utils import CaptureQueriesContext

from tests.orcs.helpers import (_bars, _config, _on, _row, _switch, _user,
                                born, care_tick, tracks_of)
from tests.orcs.helpers_o2 import MindTestCase

UTC = dt_tz.utc
WED = datetime(2026, 10, 14, 10, 0, tzinfo=UTC)
#: Friday's close and Sunday's reopen of the forex week (21:00 UTC while
#: New York keeps summer time).
FRI_CLOSE = datetime(2026, 10, 16, 21, 0, tzinfo=UTC)
SUN_OPEN = datetime(2026, 10, 18, 21, 0, tzinfo=UTC)
#: The validation context the wake keeps (A.8): what the tick reads of it.
VCTX = {"atr": {"1h": 1.0, "4h": 2.0}, "events": {}}
#: Stored level references (A.30), as the validator copies them.
S1H = {"level_id": "S1h-L1", "kind": "swing", "tf": "1h", "price": 101.2,
       "stop": 101.0}
P1H = {"level_id": "P1h-H1", "kind": "pool", "tf": "1h", "price": 103.0,
       "stop": 103.2}


def _open_at(row, at):
    from bot_program.models import AssetBotTrade
    AssetBotTrade.objects.filter(pk=row.pk).update(opened_at=at)
    row.refresh_from_db()


def _seen(orc):
    from bot_program.orcs.models import Orc
    return Orc.objects.get(pk=orc.pk).seen or {}


def _intent_entries(orc):
    from bot_program.orcs.models import OrcJournal
    return list(OrcJournal.objects.filter(orc=orc, kind="intent",
                                          author="code").order_by("at", "id"))


class ArmFixture(MindTestCase):
    """One Orc on a paper BTCUSD long, born at WED, its wake's validation
    context kept; `tick` runs the real care then the hook at WED + n
    minutes; `queue` writes an intent as the settle writes one."""

    def setUp(self):
        from bot_program.asset_engine.base import make_bot
        _on()
        _switch("aragorn")
        self.user = _user(f"o2a_arm_{type(self).__name__.lower()[:20]}")
        self.cfg = _config(self.user)
        self.row = _row(self.cfg)
        _open_at(self.row, WED)
        self.orc = born(self, self.row, at=WED)
        self.bot = make_bot(self.cfg)
        self.client = MagicMock()
        self.client.get_positions.return_value = []
        self.wake = self.wake_of(self.orc)

    def wake_of(self, orc, vctx=None):
        from bot_program.orcs.models import OrcWake
        n = OrcWake.objects.count()
        return OrcWake.objects.create(
            orc=orc, reasons=[{"code": "W2", "key": f"W2:{n}", "t": "a bar",
                               "urgent": False}],
            dedupe_key=f"t13:{orc.pk}:{n}", kind="routine", status="done",
            components={"vctx": copy.deepcopy(vctx or VCTX)})

    def at(self, minutes):
        return WED + timedelta(minutes=minutes)

    def tick(self, price, minutes=None, *, at=None, bot=None, row=None,
             **kw):
        return care_tick(self, bot or self.bot, row or self.row, str(price),
                         self.client, at or self.at(minutes), **kw)

    def queue(self, kind, minutes=None, *, at=None, level=None,
              would_stop=None, share=None, event_id="", orc=None, wake=None,
              status="queued"):
        """An OrcIntent as the settle writes one (mind._write_intent): in
        shadow, `expires_at` its validation plus INTENT_TTL_S, and a queued
        one's id joining seen["intents_queued"] under the Orc's lock."""
        from bot_program.orcs import journal
        from bot_program.orcs.constants import INTENT_TTL_S
        from bot_program.orcs.models import OrcIntent
        orc = orc or self.orc
        at = at or self.at(minutes)
        level = dict(level or {})
        it = OrcIntent.objects.create(
            orc=orc, wake=wake or self.wake, kind=kind, level=level,
            level_id=str(level.get("level_id") or ""),
            would_stop=(None if would_stop is None
                        else Decimal(str(would_stop))),
            share=share, event_id=event_id, mode="shadow", status=status,
            why="queued for the shadow arm",
            expires_at=at + timedelta(seconds=INTENT_TTL_S), rung="r0",
            s_version="s1", schema_version="d1")
        OrcIntent.objects.filter(pk=it.pk).update(created_at=at)
        if status == "queued":
            journal.remember(orc, intents_queued=(
                lambda cur, pk=it.pk: [x for x in (cur or [])
                                       if isinstance(x, int)] + [pk]))
        it.refresh_from_db()
        return it

    def arm(self, orc=None):
        return tracks_of(orc or self.orc)["orc_shadow"]


# ── applied at the first tick, priced by pricing.py ──────────────────────

class TheFirstTickTests(ArmFixture):

    def test_an_exit_is_applied_at_the_next_tick_and_priced_by_pricing(self):
        """A.42: the first tick after validation applies it on its own
        price; simulated with its time, price and R; the id leaves the
        queue; the card says so; the position is untouched."""
        from bot_program.orcs import pricing
        from bot_program.orcs.models import Orc
        self.tick("101.0", 30)
        it = self.queue("exit", 31)
        self.assertEqual(_seen(self.orc).get("intents_queued"), [it.pk])
        self.tick("101.2", 32)
        it.refresh_from_db()
        arm = self.arm()
        cf = arm.state["cf"]
        px = pricing.market_exit_px(pricing.Tick(at=self.at(32), p=101.2),
                                    "BUY", cf)
        self.assertEqual(it.status, "simulated")
        self.assertEqual(it.applied_at, self.at(32))
        self.assertAlmostEqual(float(it.applied_price), px, places=6)
        self.assertAlmostEqual(it.applied_r, (px - 100.0) / 2.0, places=6)
        self.assertEqual(it.rule, "")
        self.assertFalse(arm.open)
        self.assertEqual(arm.state["mode"], "would")
        self.assertEqual(arm.state["exit"]["kind"], "orc")
        self.assertEqual(arm.state["exit"]["why"], "the Orc's exit (shadow)")
        self.assertAlmostEqual(arm.state["exit"]["px"], px, places=8)
        orc = Orc.objects.get(pk=self.orc.pk)
        self.assertEqual(orc.seen.get("intents_queued"), [])
        self.assertEqual(orc.card["intents"][-1]["status_t"],
                         "applied to the shadow arm")
        self.assertTrue(orc.card["intents"][-1]["kind_t"].startswith(
            "proposed in shadow: exit"))
        entry = _intent_entries(self.orc)[-1]
        self.assertTrue(entry.headline.startswith("Applied in shadow: exit"),
                        entry.headline)
        self.assertEqual(entry.body["intent"], it.pk)
        self.assertEqual(entry.body["status"], "simulated")
        self.row.refresh_from_db()
        self.assertEqual((self.row.status, self.row.stop_loss),
                         ("OPEN", Decimal("98")), "the position is the care's")
        others = tracks_of(self.orc)
        self.assertTrue(others["care"].open and others["playbook"].open)

    def test_an_id_the_settle_queues_meanwhile_stays_queued(self):
        """The removal is a callable merged on the LOCKED memory: an id
        another writer queued after the tick read its Orc is kept for the
        next tick."""
        from bot_program.orcs import ghost
        self.tick("101.0", 30)
        first = self.queue("lock_waive", 31, event_id="C1")
        later = {}
        real = ghost.step_tick

        def step(orc, trade, **kw):
            # the settle, in another process, queues one more while this
            # tick holds its own copy of the Orc
            later["it"] = self.queue("exit", 31)
            return real(orc, trade, **kw)
        with patch.object(ghost, "step_tick", step):
            self.tick("101.2", 32)
        first.refresh_from_db()
        self.assertEqual(first.status, "simulated")
        self.assertEqual(_seen(self.orc).get("intents_queued"),
                         [later["it"].pk])
        later["it"].refresh_from_db()
        self.assertEqual(later["it"].status, "queued")
        self.tick("101.3", 33)
        later["it"].refresh_from_db()
        self.assertEqual(later["it"].status, "simulated", "the next tick")

    def test_a_tick_with_nothing_queued_reads_no_intent(self):
        """The query budget (A.42, observe.py): the queue is read from the
        Orc already in hand."""
        self.tick("101.0", 30)
        with CaptureQueriesContext(connection) as q:
            self.tick("101.1", 31)
        self.assertEqual([x["sql"] for x in q.captured_queries
                          if "orcintent" in x["sql"].lower()], [])
        self.queue("lock_waive", 31, event_id="C1")
        with CaptureQueriesContext(connection) as q:
            self.tick("101.2", 32)
        reads = [x["sql"] for x in q.captured_queries
                 if "orcintent" in x["sql"].lower()
                 and x["sql"].lstrip().upper().startswith("SELECT")]
        self.assertEqual(len(reads), 2, "the queue, and the card's newest")

    def test_a_write_that_fails_leaves_the_arm_and_the_queue(self):
        """The arm moves only once the intent's write committed: a write
        refused (a held Orc lock past the tick's budget: on PostgreSQL,
        tests/orcs/test_orc_o2a_locks.py) applies nothing, and the next
        tick takes it."""
        from bot_program.orcs import intents
        self.tick("101.0", 30)
        it = self.queue("exit", 31)
        before = copy.deepcopy(self.arm().state)

        def refused(*args, **kwargs):
            raise RuntimeError("the Orc's lock was held past the budget")
        with patch.object(intents, "_write", refused):
            self.tick("101.2", 32)
        it.refresh_from_db()
        self.assertEqual(it.status, "queued")
        arm = self.arm()
        self.assertTrue(arm.open)
        self.assertEqual(arm.state["mode"], "real")
        self.assertEqual(arm.state["last"]["p"], 101.2, "the tick recorded")
        self.assertEqual(before["mode"], "real")
        self.assertEqual(_seen(self.orc).get("intents_queued"), [it.pk])
        self.tick("101.3", 33)
        it.refresh_from_db()
        self.assertEqual(it.status, "simulated")


# ── the stop beyond the crowd (P33) ──────────────────────────────────────

class TheMenusStopTests(ArmFixture):

    ROWS = [{"id": "S1h-L1", "kind": "swing", "tf": "1h", "side": "below",
             "price": 101.2, "stop": 101.0, "origin": 1, "watchable": True},
            {"id": "BE", "kind": "breakeven_plus_cost", "tf": "4h",
             "side": "", "price": 100.2, "stop": None, "watchable": False}]

    def _validated(self, action, level_id, candidate):
        from tests.orcs.test_orc_o2a_call import answer
        from tests.orcs.test_orc_o2a_validator import check, with_vctx
        vctx = with_vctx(
            menu=[{k: v for k, v in r.items() if k != "origin"}
                  for r in self.ROWS],
            candidates=[{"id": "T-STRUCT", "action": "tighten",
                         "level_ids": ["S1h-L1"]},
                        {"id": "P-LOCK", "action": "tighten",
                         "level_ids": ["BE"]}],
            p=102.4, m=102.3, effective=98.0)
        verdict = check(answer(action=action, level_id=level_id,
                               candidate=candidate, facts_cited=["F1"]),
                        vctx=vctx)
        self.assertEqual(verdict["status"], "done", verdict["refusals"])
        return verdict

    def test_the_orc_and_t_struct_naming_s1h_l1_hold_the_same_stop(self):
        """P33: T-STRUCT and an Orc's tighten naming S1h-L1 both stand on
        the level's own stop beyond the crowd, never its price."""
        from bot_program.orcs import playbook
        ts = playbook.t_struct(self.ROWS, side="BUY", mfe_r=1.2, p=102.4,
                               m=102.3, effective=98.0,
                               atr={"1h": 1.0, "4h": 2.0})
        self.assertEqual((ts["level_id"], ts["stop"]), ("S1h-L1", 101.0))
        verdict = self._validated("tighten", "S1h-L1", "T-STRUCT")
        self.assertEqual(verdict["would_stop"], ts["stop"])
        self.assertNotEqual(verdict["would_stop"], verdict["level"]["price"])
        self.tick("101.0", 30)
        self.queue("tighten", 31, level=verdict["level"],
                   would_stop=verdict["would_stop"])
        self.tick("102.4", 32)
        state = self.arm().state
        self.assertEqual(state["mode"], "would")
        self.assertEqual(state["orc_stop"], ts["stop"])
        self.assertEqual(state["orc_why"], "the Orc's proposal S1h-L1")

    def test_an_orc_that_follows_p_lock_puts_its_stop_at_be(self):
        verdict = self._validated("tighten", "BE", "P-LOCK")
        self.assertEqual(verdict["would_stop"], 100.2, "the BE row's price")
        self.tick("101.0", 30)
        self.queue("tighten", 31, level=verdict["level"],
                   would_stop=verdict["would_stop"])
        self.tick("102.4", 32)
        state = self.arm().state
        self.assertEqual((state["mode"], state["orc_stop"]), ("would", 100.2))


# ── the time to live (P32) ───────────────────────────────────────────────

class TheTimeToLiveTests(ArmFixture):

    def test_an_exit_validated_at_fridays_close_expires_at_the_reopen(self):
        """P32: through the shut no tick has a fresh price, so it waits;
        the reopen's first tick finds its time gone and expires it, never
        filling it at the gap."""
        from bot_program.asset_engine.base import make_bot
        cfg = _config(self.user, "forex", name="fx")
        row = _row(cfg, symbol="EURUSD", cls="forex", entry="1.1000",
                   stop="1.0950", target="1.1100")
        _open_at(row, FRI_CLOSE - timedelta(hours=3))
        orc = born(self, row, at=FRI_CLOSE - timedelta(hours=3))
        wake = self.wake_of(orc, {"atr": {"1h": 0.001, "4h": 0.002},
                                  "events": {}})
        bot = make_bot(cfg)
        self.tick("1.1040", at=FRI_CLOSE - timedelta(minutes=5), bot=bot,
                  row=row)
        it = self.queue("exit", at=FRI_CLOSE - timedelta(minutes=4), orc=orc,
                        wake=wake)
        self.tick("1.1041", at=FRI_CLOSE + timedelta(minutes=2), bot=bot,
                  row=row)
        it.refresh_from_db()
        self.assertEqual(it.status, "queued", "the shut has no fresh price")
        self.assertEqual(_seen(orc).get("intents_queued"), [it.pk])
        self.tick("1.1020", at=SUN_OPEN + timedelta(minutes=5), bot=bot,
                  row=row)
        it.refresh_from_db()
        self.assertEqual((it.status, it.rule), ("expired", "ttl"))
        self.assertIsNone(it.applied_price)
        self.assertIsNone(it.applied_at)
        arm = self.arm(orc)
        self.assertTrue(arm.open, "never filled at the gap")
        self.assertEqual(arm.state["mode"], "real")
        self.assertEqual(_seen(orc).get("intents_queued"), [])
        entry = _intent_entries(orc)[-1]
        self.assertTrue(entry.headline.startswith("Expired in shadow: exit"),
                        entry.headline)
        self.assertIn("10 minutes", entry.headline)


# ── moved at the tick ────────────────────────────────────────────────────

class TheMovedTests(ArmFixture):

    def test_no_room_left_on_the_ticks_price(self):
        """A.42: 0.5 ATR(1h) of room from the tick's price and closing
        mark, measured at the tick, never at the dossier."""
        self.tick("102.2", 30)
        it = self.queue("tighten", 31,
                        level={**S1H, "price": 101.6, "stop": 101.5},
                        would_stop=101.5)
        self.tick("101.8", 32)
        it.refresh_from_db()
        self.assertEqual((it.status, it.rule), ("expired", "moved"))
        self.assertIn("room", it.why)
        state = self.arm().state
        self.assertEqual(state["mode"], "real")
        self.assertIsNone(state.get("orc_stop"))
        self.assertIsNone(state.get("first_divergence"))

    def test_no_longer_tighter_than_the_arms_stop(self):
        """The care locked break-even (100.2) after the dossier: a would-
        stop at 100.0 is no longer the tighter."""
        self.tick("102.2", 30)
        self.assertEqual(self.arm().state["last_care"]["soft_stop"], 100.2)
        it = self.queue("tighten", 31,
                        level={**S1H, "tf": "4h", "price": 100.3,
                               "stop": 100.0}, would_stop=100.0)
        self.tick("102.4", 32)
        it.refresh_from_db()
        self.assertEqual((it.status, it.rule), ("expired", "moved"))
        self.assertIn("tighter", it.why)
        self.assertEqual(self.arm().state["mode"], "real")


# ── would mode ───────────────────────────────────────────────────────────

class TheWouldModeTests(ArmFixture):

    def test_entering_would_mode_seeds_as_to_shadow_does_with_no_hand(self):
        """A.43: from `real` the arm takes the previous tick's record
        exactly as a hand act's shadow does, and never sets `hand`."""
        from bot_program.orcs import ghost
        from bot_program.orcs.constants import DIVERGE_REDUCE
        self.tick("101.0", 30)
        self.tick("102.2", 60)
        state = self.arm().state
        self.assertEqual(state["mode"], "real")
        replay = self.row.metadata.get("paper_replay")
        would, shadow = copy.deepcopy(state), copy.deepcopy(state)
        ghost._to_would(would, kind="tighten", intent=7, at=self.at(61),
                        replay=replay)
        ghost._to_shadow(shadow, "edit", self.at(61), replay=replay)
        self.assertEqual(would["mode"], "would")
        self.assertIsNone(would.get("hand"))
        self.assertEqual(shadow["hand"]["how"], "edit")
        self.assertEqual(would["first_divergence"],
                         {"kind": DIVERGE_REDUCE,
                          "at": self.at(61).isoformat(), "intent": 7})
        keys = (set(would) | set(shadow)) - {"mode", "hand",
                                             "first_divergence"}
        for key in sorted(keys):
            with self.subTest(key=key):
                self.assertEqual(would.get(key), shadow.get(key))
        self.assertEqual(would["soft_stop"], 100.2, "the record's care")
        self.assertEqual(would["venue_stop"], 98.0)
        self.assertEqual(would["target"], 110.0)

    def test_a_would_stop_exit_is_labelled_orc(self):
        """A.43: the arm's own care step, its would-stop an `orc` exit with
        the proposal's words, never `playbook`; the position is held."""
        from bot_program.orcs import pricing
        self.tick("102.2", 30)
        it = self.queue("tighten", 31, level=S1H, would_stop=101.0)
        self.tick("102.4", 32)
        it.refresh_from_db()
        self.assertEqual(it.status, "simulated")
        self.assertAlmostEqual(float(it.applied_price), 101.0)
        self.assertAlmostEqual(it.applied_r, 0.5)
        state = self.arm().state
        self.assertEqual((state["mode"], state["orc_stop"]), ("would", 101.0))
        self.assertIsNone(state.get("hand"))
        self.assertEqual(state["first_divergence"]["kind"], "reduce")
        self.assertEqual(state["first_divergence"]["intent"], it.pk)
        self.tick("100.9", 33)
        arm = self.arm()
        self.assertFalse(arm.open)
        out = arm.state["exit"]
        self.assertEqual(out["kind"], "orc")
        self.assertEqual(out["why"], "the Orc's proposal S1h-L1")
        self.assertEqual(arm.exit_why, "the Orc's proposal S1h-L1")
        self.assertAlmostEqual(out["px"], pricing.market_exit_px(
            pricing.Tick(at=self.at(33), p=100.9), "BUY", arm.state["cf"]))
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, "OPEN", "the care holds the row")
        self.assertTrue(tracks_of(self.orc)["care"].open)

    def test_would_mode_keeps_the_faith_block(self):
        """A.43: the real row is still the care's, so the faith block
        against the care ghost counts every tick of the would arm."""
        self.tick("101.0", 30)
        self.queue("lock_waive", 31, event_id="C1")
        self.tick("101.2", 32)
        faith = self.arm().state["faith"]
        self.assertEqual(self.arm().state["mode"], "would")
        self.tick("101.4", 33)
        self.tick("101.6", 34)
        after = self.arm().state["faith"]
        self.assertEqual(after["ticks"], faith["ticks"] + 2)
        self.assertEqual(after.get("differ", 0), 0, "the ghost is faithful")
        self.assertEqual(self.arm().state["last"]["p"], 101.6,
                         "the tick's record")

    def test_a_hand_edit_in_would_mode_is_journaled_and_moves_nothing(self):
        """The hand-edit fact sets hand_touched and never moves the would
        arm (A.43)."""
        from bot_program.models import AssetBotTrade
        from bot_program.orcs.models import Orc
        self.tick("102.2", 30)
        self.queue("tighten", 31, level=S1H, would_stop=101.0)
        self.tick("102.4", 32)
        meta = dict(self.row.metadata)
        meta["level_edits"] = [{"at": self.at(33).isoformat(),
                                "stop": "99"}]
        AssetBotTrade.objects.filter(pk=self.row.pk).update(metadata=meta)
        self.row.refresh_from_db()
        self.tick("102.5", 34)
        state = self.arm().state
        self.assertEqual((state["mode"], state["orc_stop"]), ("would", 101.0))
        self.assertIsNone(state.get("hand"))
        self.assertTrue(Orc.objects.get(pk=self.orc.pk).hand_touched)


# ── after the close ──────────────────────────────────────────────────────

class TheCloseTests(ArmFixture):

    def test_the_walk_after_the_close_applies_orc_stop_and_expires(self):
        """A.44: step_bars expires what is still queued with `row_closed`
        and walks the would arm on its orc_stop; the would arm never takes
        the real exit."""
        from bot_program.orcs import ghost, pricing
        from bot_program.scorecard import HAND_CLOSE_TAG
        self.tick("102.2", 30)
        self.queue("tighten", 31, level=S1H, would_stop=101.0)
        self.tick("102.4", 32)
        left = self.queue("trim", 33, level=P1H, share=0.5)
        self.row.status, self.row.outcome = "CLOSED", "manual_close"
        self.row.exit_price = Decimal("102.3")
        self.row.closed_at = self.at(40)
        self.row.reason = f"{self.row.reason or ''} | {HAND_CLOSE_TAG}"
        with self.captureOnCommitCallbacks(execute=True):
            self.row.save()
        _bars("BTCUSD", "1h", [(102.3, 102.6, 100.7, 101.5),
                               (101.5, 101.8, 101.2, 101.6)],
              start=WED + timedelta(hours=1))
        self.orc.refresh_from_db()
        ghost.step_bars(self.orc, now=WED + timedelta(hours=4))
        left.refresh_from_db()
        self.assertEqual((left.status, left.rule), ("expired", "row_closed"))
        self.assertEqual(_seen(self.orc).get("intents_queued"), [])
        arm = self.arm()
        self.assertFalse(arm.open)
        self.assertEqual(arm.state["exit"]["kind"], "stop")
        self.assertAlmostEqual(arm.state["exit"]["px"], pricing.level_exit_px(
            101.0, "BUY", arm.state["cf"]))
        self.assertEqual(arm.state["mode"], "would", "never the real exit")
        ghost.step_bars(self.orc, now=WED + timedelta(hours=5))
        left.refresh_from_db()
        self.assertEqual(left.status, "expired", "once")

    def test_an_intent_after_the_arm_closed_expires_arm_closed(self):
        self.tick("102.2", 30)
        self.queue("tighten", 31, level=S1H, would_stop=101.0)
        self.tick("102.4", 32)
        self.tick("100.9", 33)
        self.assertFalse(self.arm().open)
        it = self.queue("trim", 34, level=P1H, share=0.5)
        self.tick("101.0", 35)
        it.refresh_from_db()
        self.assertEqual((it.status, it.rule), ("expired", "arm_closed"))
        self.assertEqual(_seen(self.orc).get("intents_queued"), [])
        self.row.refresh_from_db()
        self.assertEqual(self.row.status, "OPEN")

    def test_an_exit_closes_the_arm_and_what_follows_expires(self):
        self.tick("101.0", 30)
        first = self.queue("exit", 31)
        then = self.queue("trim", 31, level=P1H, share=0.5)
        self.tick("101.2", 32)
        first.refresh_from_db()
        then.refresh_from_db()
        self.assertEqual(first.status, "simulated")
        self.assertEqual((then.status, then.rule), ("expired", "arm_closed"))


# ── the lock waiver, the trim, the add, the care ─────────────────────────

class TheKindsTests(ArmFixture):

    def test_a_lock_waiver_drops_the_event_lock_on_a_copy(self):
        """A.43, A.45b: the would arm's care reads dict(env.ctx) without the
        waived event; the care, its ghost and the tick's own context keep
        it."""
        from market_data.models import EconomicEvent
        ev = EconomicEvent.objects.create(
            title="US CPI", country="US", datetime=self.at(80),
            impact="high", currency_affected="USD", source="forexfactory")
        wake = self.wake_of(self.orc, {
            "atr": {"1h": 1.0, "4h": 2.0},
            "events": {f"C{ev.pk}": {"at": ev.datetime.isoformat(),
                                     "ccy": "USD", "kind": "print",
                                     "minutes": 60}}})
        self.tick("100.6", 20)
        it = self.queue("lock_waive", 21, event_id=f"C{ev.pk}", wake=wake)
        self.tick("101.4", 30)
        it.refresh_from_db()
        self.assertEqual(it.status, "simulated")
        self.assertEqual(self.row.metadata["care"]["soft_why"], "event lock")
        self.assertEqual(self.row._care_tick["event"]["title"], "US CPI",
                         "the tick's own context keeps its event")
        ghost_ = tracks_of(self.orc)["care"].state
        self.assertEqual(ghost_["soft_why"], "event lock")
        state = self.arm().state
        self.assertEqual(state["mode"], "would")
        self.assertEqual(state["waived"], f"C{ev.pk}")
        self.assertIsNone(state.get("soft_stop"), "no event lock in shadow")
        self.assertEqual(state["first_divergence"]["kind"], "hold")

    def test_a_trim_banks_its_share_at_the_ticks_price(self):
        from bot_program.orcs import pricing
        self.tick("102.2", 30)
        it = self.queue("trim", 31, level=P1H, share=0.5)
        self.tick("102.4", 32)
        it.refresh_from_db()
        state = self.arm().state
        px = pricing.market_exit_px(pricing.Tick(at=self.at(32), p=102.4),
                                    "BUY", state["cf"])
        self.assertEqual(it.status, "simulated")
        self.assertAlmostEqual(float(it.applied_price), px, places=6)
        self.assertEqual(state["qty_open"], 0.5)
        trim = state["banked"][-1]
        self.assertEqual((trim["qty"], trim["why"]),
                         (0.5, "the Orc's trim (shadow)"))
        self.assertAlmostEqual(trim["px"], px)
        self.row.refresh_from_db()
        self.assertEqual(self.row.qty, Decimal("1"), "the position is whole")

    def test_an_add_never_moves_the_arm(self):
        """An add is judged and recorded, never applied: even an add's id
        in the queue is dropped from it and steps nothing."""
        from bot_program.orcs import journal
        self.tick("101.0", 30)
        add = self.queue("add", 31, level=S1H, share=0.5, status="recorded")
        journal.remember(self.orc, intents_queued=lambda cur: [add.pk])
        self.tick("101.2", 32)
        add.refresh_from_db()
        self.assertEqual(add.status, "recorded")
        state = self.arm().state
        self.assertEqual(state["mode"], "real")
        self.assertIsNone(state.get("orc_stop"))
        self.assertIsNone(state.get("first_divergence"))
        self.assertEqual(_seen(self.orc).get("intents_queued"), [])

    def test_a_care_owned_orcs_proposals_are_recorded(self):
        """A.41, A.53: while the care holds the idea the officer still
        judges a proposal, which is recorded, never queued for the arm; and
        one queued before the takeover is never applied while the care
        holds the would-world too: it waits, then expires `ttl`."""
        from bot_program.orcs import mind
        from bot_program.orcs.models import Orc
        from tests.orcs.test_orc_o2a_call import answer
        from tests.orcs.test_orc_o2a_validator import FACTS, VCTX as V7
        wake = self.wake_of(self.orc, V7)
        reply = {"kind": "answer", "text": json.dumps(answer(
            action="tighten", level_id="S1h-L1", candidate="T-STRUCT",
            facts_cited=["F1"])), "stop_reason": "end_turn",
            "usage": None, "rung": "r0", "model": "", "code": "",
            "error": "", "latency": 0.1, "why": ""}

        def judged():
            with patch("bot_program.orcs.validator.facts_index",
                       return_value=FACTS):
                return mind.judge(wake, reply, now=self.at(30))
        out = judged()
        self.assertEqual(out["intent"]["status"], "queued")
        Orc.objects.filter(pk=self.orc.pk).update(state="care_owned")
        out = judged()
        self.assertEqual(out["intent"]["status"], "recorded")
        self.assertEqual(out["intent"]["mode"], "shadow")
        self.assertIsNone(out["intent"]["expires_at"])
        self.assertEqual(out["intent"]["why"],
                         "the care holds the position: recorded")
        # an exit the settle queued just before the takeover
        self.tick("101.0", 30)
        it = self.queue("exit", 31)
        self.tick("101.2", 32)
        it.refresh_from_db()
        self.assertEqual(it.status, "queued", "never applied while care_owned")
        self.assertEqual(self.arm().state["mode"], "real")
        self.tick("101.3", 42)
        it.refresh_from_db()
        self.assertEqual((it.status, it.rule), ("expired", "ttl"))
        self.assertTrue(self.arm().open)
        self.assertEqual(_seen(self.orc).get("intents_queued"), [])


# ── the tick's two judgements, and the savepoint ─────────────────────────

class TheTickJudgementsTests(ArmFixture):

    def test_a_fresh_price_and_a_readable_row(self):
        """P32's second clause: the mark (the tick's own price in an open
        market) and the row (its state readable); the bars stay as the
        dossier judged them."""
        from bot_program.orcs import intents, pricing
        env = SimpleNamespace(row=self.row, now=self.at(30))
        tick = pricing.Tick(at=self.at(30), p=101.0)
        self.assertTrue(intents.fresh(env, tick))
        self.assertTrue(intents.readable(env))
        self.assertFalse(intents.fresh(env, pricing.Tick(at=self.at(30),
                                                         p=0.0)))
        shut = SimpleNamespace(row=SimpleNamespace(asset_class="forex",
                                                   symbol="EURUSD"),
                               now=FRI_CLOSE + timedelta(hours=2))
        self.assertFalse(intents.fresh(shut, tick))
        for bad in (dict(side=""), dict(entry_price=None),
                    dict(metadata=None), dict(status="CLOSED")):
            row = SimpleNamespace(**{"side": "BUY", "entry_price": "100",
                                     "metadata": {}, "status": "OPEN",
                                     **bad})
            with self.subTest(bad):
                self.assertFalse(intents.readable(SimpleNamespace(row=row)))

    def test_the_savepoint_prices_nothing(self):
        """N8 item 1: the Orc's lock is taken inside intents' savepoint,
        which reads and writes the Orc tables only; every price is drawn
        before it opens."""
        from bot_program.orcs import intents
        from tests.orcs.test_orc_o2a_locks import HOLDER_FORBIDDEN
        from tests.orcs.test_orc_o2a_shadow_pins import identifiers
        tree = ast.parse(inspect.getsource(intents))
        savepoints = []
        for fn in (n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)):
            if any(isinstance(n, ast.With) and "atomic" in ast.unparse(n)
                   for n in ast.walk(fn)):
                savepoints.append(fn.name)
                names = {name for name, _n in identifiers(fn)}
                with self.subTest(fn.name):
                    self.assertFalse(names & HOLDER_FORBIDDEN)
                    self.assertIn("merge_seen", names, "the Orc's lock first")
        self.assertEqual(savepoints, ["_write"])
