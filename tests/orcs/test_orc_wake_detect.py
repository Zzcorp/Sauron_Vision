"""WAKE DETECTION IN O1 (bot_program/orcs/wake.py, spec §1.3, §7.5, §5.2a):
the tick detects every W-code once per key, records urgent reasons at
once and spaces the others by 15 minutes, merges what the census left
pending, and RECORDS each detected wake; the slow queue then renders it
(wake.render_queued) with its complexity score, band, the day's weather
and its dossier's block hashes. No model is asked: the wake is `skipped`
("no model before O2"), or `quiet` with a code reading when the facts did
not move. Nothing here sends, moves or calls anything.

Run with:  python manage.py test tests.orcs.test_orc_wake_detect
"""
from contextlib import ExitStack
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from tests.orcs.helpers import _config, _on, _row, _switch, _user, born

T0 = datetime(2026, 10, 21, 15, 0, tzinfo=dt_tz.utc)


class _Detect(TestCase):

    def setUp(self):
        _switch("aragorn")
        _on()
        self.user = _user("orc_wake")
        self.cfg = _config(self.user)
        self.row = _row(self.cfg)
        self.orc = born(self, self.row, at=T0 - timedelta(minutes=1))
        self.row.refresh_from_db()

    def _care(self, **care):
        meta = dict(self.row.metadata or {})
        meta["care"] = {**(meta.get("care") or {}), **care}
        self.row.metadata = meta
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(pk=self.row.pk).update(metadata=meta)

    def tick(self, at, *, price="100.5", cared="", ticks=None,
             render=True):
        """The hook after the care, as the tick runs it, at `at`; then the
        slow queue's render of what it recorded (`render`)."""
        from bot_program.orcs import wake
        from bot_program.orcs.observe import after_care
        bot = SimpleNamespace(_tick_broker_cache={}, cfg=self.cfg,
                              _last_ticks=dict(ticks or {}))
        self.row._care_tick = {"now": at}
        with ExitStack() as stack:
            stack.enter_context(patch("django.utils.timezone.now",
                                      return_value=at))
            stack.enter_context(self.captureOnCommitCallbacks(execute=True))
            after_care(bot, self.row, price, cared)
            if render:
                wake.render_queued()
        self.orc.refresh_from_db()

    def wakes(self):
        from bot_program.orcs.models import OrcWake
        return list(OrcWake.objects.filter(orc=self.orc).order_by("id"))

    def codes(self, wake):
        return [r["code"] for r in wake.reasons]


class TheRecordTests(_Detect):

    def test_the_first_tick_records_the_birth_wake(self):
        from ai_agents.models import AgentTask
        from bot_program.orcs.models import OrcDossierBlock, OrcJournal
        card_before = list((self.orc.card or {}).get("journal") or [])
        self.tick(T0)
        wakes = self.wakes()
        self.assertEqual(len(wakes), 1)
        w = wakes[0]
        self.assertEqual(self.codes(w), ["W1"])
        self.assertEqual((w.status, w.skipped_reason, w.kind),
                         ("skipped", "no model before O2", "birth"))
        self.assertIsNotNone(w.score)
        self.assertIn(w.band, ("routine", "material", "complex", "extreme"))
        self.assertIn(w.day_class, ("calm", "eventful", "stormy"))
        self.assertTrue(w.block_hashes)
        self.assertEqual(OrcDossierBlock.objects.filter(
            hash__in=w.block_hashes).count(), len(set(w.block_hashes)))
        self.assertIn("vol", w.components)
        entry = OrcJournal.objects.get(orc=self.orc, kind="wake")
        self.assertEqual(entry.wake_id, w.pk)
        self.assertEqual(entry.block_hashes, w.block_hashes)
        self.assertTrue(entry.facts_hash)
        self.assertIsInstance(entry.snapshot, dict)
        self.assertTrue(entry.headline.startswith("Wake detected: birth. "
                                                  "Complexity "))
        self.assertTrue(entry.headline.endswith(
            "Recorded only: no model is asked yet."))
        card = self.orc.card
        self.assertNotIn("wake", [j["kind"] for j in card["journal"]],
                         "the wake entry is kept off the card's journal")
        self.assertTrue(set(map(str, card_before)) <= set(map(
            str, card["journal"])) or len(card["journal"]) == 3)
        self.assertEqual(card["intellect"]["rung_t"],
                         "no model (O1: code only)")
        self.assertTrue(card["intellect"]["score_t"].startswith("score "))
        self.assertIn(card["integrity"]["flag"], ("ok", "stale", "critical",
                                                  "contradiction"))
        self.assertIsNotNone(self.orc.next_wake_due)
        self.assertEqual(AgentTask.objects.count(), 0)

    def test_a_quiet_tick_records_nothing(self):
        self.tick(T0)
        self.tick(T0 + timedelta(minutes=5))
        self.tick(T0 + timedelta(minutes=30))
        self.assertEqual(len(self.wakes()), 1)

    def test_no_wake_is_ever_pending(self):
        from bot_program.orcs.models import OrcWake
        self.tick(T0)
        self._care(mfe_r=-0.6, r_now=-0.6, mae_r=-0.6)
        self.tick(T0 + timedelta(minutes=1))
        self.assertFalse(OrcWake.objects.filter(status="pending").exists())


class TheReasonTests(_Detect):

    def test_urgent_records_at_once_others_wait_fifteen_minutes(self):
        self.tick(T0)
        # +1R: not urgent, inside the spacing: kept pending in memory
        self._care(mfe_r=1.05, r_now=1.05)
        self.tick(T0 + timedelta(minutes=5))
        self.assertEqual(len(self.wakes()), 1)
        pending = self.orc.seen["wake_pending"]
        self.assertEqual([r["code"] for r in pending["reasons"]], ["W4"])
        # -0.5R... is not reached; the drawdown step is urgent
        self._care(mfe_r=1.05, r_now=-0.55, mae_r=-0.55)
        self.tick(T0 + timedelta(minutes=7))
        wakes = self.wakes()
        self.assertEqual(len(wakes), 2)
        self.assertEqual(self.codes(wakes[-1]), ["W4", "W4", "W4"],
                         "the pending +1R rides with the urgent step")
        words = [r["t"] for r in wakes[-1].reasons]
        self.assertEqual(words, ["+1R reached", "-0.5R reached",
                                 "give-back to half the best"])
        self.assertFalse((self.orc.seen or {}).get("wake_pending"))

    def test_a_spaced_reason_records_after_fifteen_minutes(self):
        self.tick(T0)
        self._care(mfe_r=1.05, r_now=1.05)
        self.tick(T0 + timedelta(minutes=5))
        self.tick(T0 + timedelta(minutes=16))
        wakes = self.wakes()
        self.assertEqual(len(wakes), 2)
        self.assertEqual(self.codes(wakes[-1]), ["W4"])
        self.assertEqual(wakes[-1].kind, "material")

    def test_each_code_once_per_key(self):
        self.tick(T0)
        self._care(mfe_r=1.05, r_now=1.05)
        self.tick(T0 + timedelta(minutes=16))
        self.tick(T0 + timedelta(minutes=40))
        self._care(mfe_r=2.1, r_now=2.1)
        self.tick(T0 + timedelta(minutes=60))
        codes = [self.codes(w) for w in self.wakes()]
        self.assertEqual(codes, [["W1"], ["W4"], ["W4"]])
        self.assertIn("+2R reached", self.wakes()[-1].reasons[0]["t"])

    def test_the_give_back(self):
        self.tick(T0)
        self._care(mfe_r=1.6, r_now=1.6)
        self.tick(T0 + timedelta(minutes=16))
        self._care(mfe_r=1.6, r_now=0.7)
        self.tick(T0 + timedelta(minutes=40))
        self.assertIn("give-back to half the best",
                      [r["t"] for r in self.wakes()[-1].reasons])

    def test_the_care_closed_is_urgent(self):
        self.tick(T0)
        self.tick(T0 + timedelta(minutes=1), cared="closed")
        w = self.wakes()[-1]
        self.assertIn("the care closed the position",
                      [r["t"] for r in w.reasons])
        self.assertTrue(any(r["urgent"] for r in w.reasons))

    def test_the_care_moved_its_stop(self):
        self.tick(T0)
        self._care(soft_stop=100.2, soft_why="breakeven", mfe_r=0.6,
                   r_now=0.6)
        self.tick(T0 + timedelta(minutes=16))
        self.assertIn("the care moved its stop",
                      [r["t"] for r in self.wakes()[-1].reasons])

    def test_predicate_met_urgent_thesis_exit_not_hand_edit(self):
        from bot_program.orcs import wake
        self.tick(T0)
        orc = self.orc
        orc._seen_before = dict(orc.seen)
        orc.seen = {**orc.seen,
                    "predicates": {"close_beyond:4h:S4h-L1": {
                        "state": "met", "why": "a 4h close below"}},
                    "thesis": ["exit", None], "hand_at": "x"}
        bot = SimpleNamespace(_tick_broker_cache={}, cfg=self.cfg,
                              _last_ticks={})
        with patch("django.utils.timezone.now",
                   return_value=T0 + timedelta(minutes=2)):
            w = wake.detect(bot, self.row, "100.5", "", orc)
        self.assertIsNotNone(w, "the met predicate is urgent")
        texts = {r["t"]: r["urgent"] for r in w.reasons}
        self.assertTrue(texts["invalidation met (close_beyond)"])
        self.assertFalse(texts["the thesis check reads exit"])
        self.assertFalse(texts["a hand edit of the levels"])

    def test_the_metronome_and_a_quiet_wake(self):
        from bot_program.orcs.models import Orc, OrcJournal
        self.tick(T0)
        self.tick(T0 + timedelta(hours=4, minutes=1))
        w = self.wakes()[-1]
        self.assertEqual(self.codes(w), ["W11"])
        self.assertEqual(w.status, "quiet", "W11 on unchanged facts")
        reading = OrcJournal.objects.filter(orc=self.orc,
                                            kind="reading").last()
        self.assertTrue(reading.headline.startswith("Nothing new: "))
        self.assertIn("structure unchanged", reading.headline)
        self.assertEqual(Orc.objects.get(pk=self.orc.pk).latest_note,
                         reading.headline[:140])

    def test_w3_near_an_invalidation_level_is_urgent_once_per_4h(self):
        """The mark within 0.1 x ATR(1h) of an invalidation level the
        thesis wrote: urgent (it records inside the spacing), once per
        level per 4 hours."""
        from bot_program.orcs.models import Orc
        from tests.orcs.helpers import _bars, _wave
        _bars("BTCUSD", "1h", _wave(200), start=T0 - timedelta(hours=200))
        th = dict(self.orc.thesis or {})
        th["invalidation"] = list(th.get("invalidation") or []) + [
            {"kind": "close_beyond", "tf": "4h", "level": 99.0,
             "level_id": "S4h-L1"}]
        Orc.objects.filter(pk=self.orc.pk).update(thesis=th)
        self.tick(T0)
        self.tick(T0 + timedelta(minutes=2), price="99.0")
        wakes = self.wakes()
        self.assertEqual(len(wakes), 2)
        self.assertIn("W3", self.codes(wakes[-1]))
        w3 = [r for r in wakes[-1].reasons if r["code"] == "W3"][0]
        self.assertTrue(w3["urgent"])
        self.assertTrue(w3["t"].startswith("the mark near S4h-L1 ("),
                        w3["t"])
        self.tick(T0 + timedelta(minutes=20), price="99.0")
        self.assertEqual(sum("W3" in self.codes(w) for w in self.wakes()), 1,
                         "once per level per 4 hours")
        self.tick(T0 + timedelta(hours=4, minutes=5), price="99.0")
        self.assertEqual(sum("W3" in self.codes(w) for w in self.wakes()), 2)

    def test_w10_a_venue_fault_is_urgent_once(self):
        """A close in doubt, the stop rules inert, an entry in doubt on the
        symbol: each recorded at once, inside the spacing, and once."""
        from bot_program.models import AssetBotTrade
        self.tick(T0)
        meta = dict(self.row.metadata)
        meta["close_in_doubt"] = {"at": "2026-10-21T15:01:00+00:00"}
        meta["stop_rules_inert"] = "the venue holds no stop rule"
        AssetBotTrade.objects.filter(pk=self.row.pk).update(metadata=meta)
        self.row.metadata = meta
        extras = dict(self.cfg.extras or {})
        extras["entry_in_doubt"] = {"BTCUSD": {
            "reference": "r", "at": "2026-10-21T15:01:30+00:00"}}
        self.cfg.extras = extras
        self.cfg.save(update_fields=["extras"])
        self.tick(T0 + timedelta(minutes=2))
        wakes = self.wakes()
        self.assertEqual(len(wakes), 2)
        self.assertEqual(sorted(r["t"] for r in wakes[-1].reasons),
                         ["a close in doubt",
                          "an entry in doubt on this symbol",
                          "the stop rules are inert"])
        self.assertTrue(all(r["urgent"] for r in wakes[-1].reasons))
        self.tick(T0 + timedelta(minutes=4))
        self.tick(T0 + timedelta(minutes=30))
        self.assertEqual(sum("W10" in self.codes(w) for w in self.wakes()),
                         1)

    def test_census_pending_merges_into_the_next_tick(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import wake
        self.tick(T0)
        AssetBotTrade.objects.filter(pk=self.row.pk).update(
            status="CLOSE_PENDING")
        self.assertEqual(wake.census_pending(T0 + timedelta(minutes=1)), 1)
        self.assertEqual(wake.census_pending(T0 + timedelta(minutes=2)), 0,
                         "once per key")
        self.row.refresh_from_db()
        self.tick(T0 + timedelta(minutes=3))
        w = self.wakes()[-1]
        self.assertIn("a close pending at the venue",
                      [r["t"] for r in w.reasons])

    def test_census_clock_before_and_after_a_print(self):
        from bot_program.orcs import wake
        from market_data.models import EconomicEvent
        self.tick(T0)
        EconomicEvent.objects.create(
            title="Non-Farm Employment Change", country="US",
            datetime=T0 + timedelta(minutes=170), impact="High",
            currency_affected="USD", source="forexfactory")
        self.assertEqual(wake.census_clock(T0 + timedelta(minutes=5)), 1)
        self.assertEqual(wake.census_clock(T0 + timedelta(minutes=10)), 0)
        self.tick(T0 + timedelta(minutes=11))
        w = self.wakes()[-1]
        self.assertEqual(self.codes(w), ["W5"])
        self.assertTrue(w.reasons[0]["urgent"])
        # code words only: the currency, the calendar row's id, the minutes
        self.assertRegex(w.reasons[0]["t"],
                         r"^a high-impact USD print \(C\d+\) in \d+ min$")
        self.assertNotIn("Non-Farm", w.reasons[0]["t"])

    def test_a_pending_reason_is_merged_into_the_next_tick(self):
        from bot_program.orcs import journal
        self.tick(T0)
        journal.remember(self.orc, wake_pending={
            "reasons": [{"code": "W12", "key": "W12:w1", "urgent": True,
                         "t": "a war drum (stop_hit, same symbol)"}],
            "since": T0.isoformat()})
        self.tick(T0 + timedelta(minutes=1))
        self.assertEqual(self.codes(self.wakes()[-1]), ["W12"])


class TheFactsHashTests(TestCase):

    def test_quarter_r_buckets_and_the_parts(self):
        from bot_program.orcs.wake import facts_hash
        base = {"r_now": 0.30, "menu": ["S4h-L1", "BE"], "po3": "manipulation",
                "calendar_min": 400, "thesis": "hold",
                "predicates": {"a": "unmet"}}
        h = facts_hash(base)
        self.assertEqual(h, facts_hash({**base, "r_now": 0.45}))
        self.assertNotEqual(h, facts_hash({**base, "r_now": 0.55}))
        self.assertEqual(h, facts_hash({**base, "menu": ["BE", "S4h-L1"]}))
        self.assertNotEqual(h, facts_hash({**base, "po3": "distribution"}))
        self.assertNotEqual(h, facts_hash({**base, "predicates":
                                           {"a": "met"}}))
        self.assertEqual(len(h), 64)
