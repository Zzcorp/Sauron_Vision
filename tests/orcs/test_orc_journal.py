"""THE DETERMINISTIC JOURNAL (spec §1.4, O1a): facts written by code, each
with an id the model may later cite, only when something changed — the
care's stop by the quarter R, the mirror held or refused, a hand edit, an
event window, a scale-out, the care's close, the thesis check, a review,
a pending close. R and prices only; never money, never a reviewer's prose.

Run with:  python manage.py test tests.orcs.test_orc_journal
"""
import json
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from tests.orcs.helpers import (_config, _manual_config, _manual_row, _on,
                                _row, _user, born, headlines)


def _bot():
    """What after_care reads of the bot: its per-pass cache."""
    return SimpleNamespace(_tick_broker_cache={}, asset_class="crypto")


def _care(row, **care):
    """The care wrote these keys on the row (as _save_care would)."""
    from bot_program.models import AssetBotTrade
    meta = dict(row.metadata or {})
    meta["care"] = {**(meta.get("care") or {}), **care}
    row.metadata = meta
    AssetBotTrade.objects.filter(pk=row.pk).update(metadata=meta)


class TheJournalTests(TestCase):

    def setUp(self):
        _on()
        self.user = _user("orc_journal")
        self.cfg = _config(self.user)
        self.row = _row(self.cfg)
        self.orc = born(self, self.row)
        self.bot = _bot()
        # the birth's own facts: the army type, and the Corsair overlay
        # when the expected hold holds a crypto weekend
        self.n0 = len(headlines(self.orc, kind="fact"))

    def _tick(self, price="101", cared="", bot=None):
        from bot_program.orcs.observe import after_care
        after_care(bot or self.bot, self.row, price, cared)

    def _facts(self):
        return headlines(self.orc, kind="fact")[self.n0:]

    def test_a_care_stop_move_is_one_fact(self):
        _care(self.row, soft_stop=100.2, soft_why="breakeven", peak=102.2)
        self._tick("102.2")
        self._tick("102.3")
        self.assertEqual(self._facts(), [
            "The care moved its stop to 100.20 (breakeven), +0.10R."])

    def test_a_trail_grind_writes_one_fact_per_quarter_r(self):
        for level in (101.0, 101.1, 101.2, 101.4, 101.5, 101.6):
            _care(self.row, soft_stop=level, soft_why="trail")
            self._tick(str(level + 2))
        self.assertEqual(self._facts(), [
            "The care moved its stop to 101.00 (trail), +0.50R.",
            "The care moved its stop to 101.50 (trail), +0.75R."])

    def test_mirror_held_and_refused_are_facts_once(self):
        _care(self.row, venue_stop=100.2)
        self._tick()
        self._tick()
        _care(self.row, venue_stop_refusal="refused: rate too close",
              venue_asked_for=101.0)
        self._tick()
        self._tick()
        self.assertEqual(self._facts(), [
            "The venue now holds the stop at 100.20, +0.10R.",
            "The venue refused the stop at 101.00; the care keeps it on the "
            "platform."])
        self.assertNotIn("rate too close", json.dumps(
            [e.body for e in self.orc.journal.all()]),
            "the venue's own words are not copied")

    def test_a_hand_edit_is_a_fact_and_marks_hand_touched(self):
        _care(self.row, venue_stop_hand={"level": 99.0,
                                         "at": "2026-10-14T15:00:00+00:00"})
        self._tick()
        self._tick()
        self.assertEqual(self._facts(), [
            "A hand edit set the venue's stop at 99.00, -0.50R. The grade "
            "counts it as a hand act."])
        self.orc.refresh_from_db()
        self.assertTrue(self.orc.hand_touched)

    def test_event_window_scale_out_and_the_care_close_are_facts(self):
        from bot_program.models import AssetBotTrade
        _care(self.row, event={"title": "Non-Farm Payrolls",
                               "at": "2026-10-16T12:30:00+00:00"})
        self._tick()
        _care(self.row, scaled_out=True)
        meta = dict(self.row.metadata)
        meta["scale_out"] = {"qty": "0.5", "price": 102.2, "r": 1.1,
                             "original_qty": "1"}
        self.row.metadata = meta
        AssetBotTrade.objects.filter(pk=self.row.pk).update(metadata=meta)
        self._tick()
        meta = dict(self.row.metadata, care_exit="trail")
        self.row.metadata = meta
        self._tick("101.9", cared="attempted")
        self._tick("101.9", cared="attempted")
        self.assertEqual(self._facts(), [
            "An event window opened: a high-impact print at 12:30 UTC.",
            "The care banked half the position at +1.10R (paper).",
            "The care decided to close (trail) at 101.90, +0.95R."])
        event = self.orc.journal.get(headline__startswith="An event window")
        self.assertEqual(event.body["title"], "Non-Farm Payrolls",
                         "the title rides in the body only")

    def test_a_thesis_verdict_change_is_one_fact(self):
        from bot_program.models import AssetBotTrade
        for th in ({"verdict": "hold", "stop": None, "at": "t1"},
                   {"verdict": "hold", "stop": None, "at": "t2"},
                   {"verdict": "adjust", "stop": 99.5, "at": "t3"}):
            meta = dict(self.row.metadata, thesis=th)
            self.row.metadata = meta
            AssetBotTrade.objects.filter(pk=self.row.pk).update(metadata=meta)
            self._tick()
        self.assertEqual(self._facts(), [
            "The thesis check reads hold.",
            "The thesis check reads adjust: a structure stop at 99.50."])

    def test_a_review_is_one_fact_without_its_reasoning(self):
        from brain.position_review_models import PositionReview
        from bot_program.orcs import facts
        PositionReview.objects.create(
            book="bot", position_id=self.row.pk, symbol="BTCUSD", side="BUY",
            verdict="none", mark=101, unrealized_r=0.5)
        PositionReview.objects.create(
            book="bot", position_id=self.row.pk, symbol="BTCUSD", side="BUY",
            verdict="tighten", mark=101, unrealized_r=0.5,
            reasoning_md="SECRET reasoning about the account")
        self.assertEqual(facts.observe_reviews(), 1)
        self.assertEqual(facts.observe_reviews(), 0)
        self.assertEqual(self._facts(), [
            "The reviewer reads tighten at 101.00, +0.50R."])
        blob = json.dumps([[e.headline, e.body]
                           for e in self.orc.journal.all()])
        self.assertNotIn("SECRET", blob)

    def test_a_pending_close_is_a_fact_once(self):
        from bot_program.orcs import facts
        self.row.status = "CLOSE_PENDING"
        self.row.save(update_fields=["status"])
        self.assertEqual(facts.observe_pending(), 1)
        self.assertEqual(facts.observe_pending(), 0)
        self.assertEqual(self._facts(), [
            "A close is pending at the venue for this position."])

    def test_fact_ids_run_in_order_per_orc(self):
        other = born(self, _row(self.cfg, symbol="ETHUSD"))
        _care(self.row, soft_stop=100.2, soft_why="breakeven")
        self._tick()
        _care(self.row, venue_stop=100.2)
        self._tick()
        ids = [e.fact_id for e in self.orc.journal.filter(kind="fact")
               .order_by("at", "id")]
        self.assertEqual(len(ids), self.n0 + 2)
        self.assertEqual(ids, [f"F{i}" for i in range(1, len(ids) + 1)])
        theirs = [e.fact_id for e in other.journal.filter(kind="fact")
                  .order_by("at", "id")]
        self.assertEqual(theirs[0], "F1", "each Orc counts its own")
        self.assertEqual(self.orc.journal.filter(kind="birth").get().fact_id,
                         "", "a birth line is no fact")

    def test_every_text_carries_r_and_prices_only(self):
        from bot_program.orcs.lifecycle import kill_all
        _care(self.row, soft_stop=100.2, soft_why="breakeven",
              venue_stop=100.2,
              venue_stop_hand={"level": 99.0, "at": "x"},
              event={"title": "CPI", "at": "2026-10-16T12:30:00+00:00"})
        self._tick()
        kill_all(self.user, reason="t")
        texts = [e.headline for e in self.orc.journal.all()]
        self.assertGreater(len(texts), 5)
        for text in texts:
            with self.subTest(text):
                self.assertFalse(set(text) & set("$€£¥"))
                low = text.lower()
                for word in ("balance", "equity", "account", "pnl", "usd"):
                    self.assertNotIn(word, low)
        blob = json.dumps([e.body for e in self.orc.journal.all()]).lower()
        for word in ("risk_dollars", "pnl", "balance", "equity"):
            self.assertNotIn(word, blob)

    def test_the_card_keeps_the_last_three_entries(self):
        for level in (100.2, 100.6, 101.0, 101.5):
            _care(self.row, soft_stop=level, soft_why="trail")
            self._tick()
        self.orc.refresh_from_db()
        card = self.orc.card
        self.assertEqual(card["v"], 1)
        self.assertEqual(len(card["journal"]), 3)
        last = self.orc.journal.order_by("-at", "-id").first()
        self.assertEqual(card["journal"][-1]["t"], last.headline)
        self.assertEqual(set(card["journal"][-1]), {"at", "kind", "author",
                                                    "t"})

    def test_a_quiet_tick_writes_nothing(self):
        _care(self.row, soft_stop=100.2, soft_why="breakeven")
        self._tick()
        n = self.orc.journal.count()
        with self.assertNumQueries(1):          # the Orc, by the stamp
            self._tick()
        self.assertEqual(self.orc.journal.count(), n)

    def test_the_switch_is_read_once_per_pass(self):
        from bot_program.orcs.observe import after_care
        second = _row(self.cfg, symbol="ETHUSD")
        born(self, second)
        bot = _bot()
        with patch("core.platform_control.is_component_enabled",
                   return_value=True) as read:
            after_care(bot, self.row, "101", "")
            after_care(bot, second, "101", "")
            after_care(bot, self.row, "101", "")
        self.assertEqual(read.call_count, 1)
        with patch("core.platform_control.is_component_enabled",
                   return_value=True) as again:
            after_care(_bot(), self.row, "101", "")
        self.assertEqual(again.call_count, 1, "a new pass reads it again")

    def test_a_dead_orc_hears_nothing_more(self):
        from bot_program.orcs.lifecycle import kill_all
        kill_all(self.user)
        n = self.orc.journal.count()
        _care(self.row, soft_stop=100.6, soft_why="trail")
        self._tick()
        self.assertEqual(self.orc.journal.count(), n)

    def test_journal_entries_are_never_updated(self):
        from bot_program.orcs import journal
        self.assertFalse(hasattr(journal, "update"))
        self.assertFalse(hasattr(journal, "edit"))
        entry = journal.append(self.orc, "fact", "x", fact=True,
                               at=timezone.now())
        self.assertEqual(entry.fact_id, f"F{self.n0 + 1}")


class TheAdoptedHistoryTests(TestCase):
    """facts.baseline: what an adopted row already says is not news. The
    row's history is in its reconstructed thesis, never journaled again as
    new facts, and a hand edit made before the adoption is not this idea's
    hand act."""

    def test_an_adopted_rows_care_history_is_not_journaled_again(self):
        from brain.position_review_models import PositionReview
        from bot_program.orcs import facts
        from bot_program.orcs.observe import after_care
        _on()
        user = _user("orc_adopted_history")
        lane = _manual_config(user, "commodity", mode="live")
        care = {"peak": 2680.0, "worst": 2640.0, "soft_stop": 2650.0,
                "soft_why": "breakeven", "venue_stop": 2650.0,
                "venue_stop_hand": {"level": 2645.0,
                                    "at": "2026-10-10T09:00:00+00:00"},
                "event": {"title": "CPI", "at": "2026-10-15T12:30:00+00:00"},
                "venue_stop_refusal": "refused", "venue_asked_for": 2655.0,
                "since": "2026-10-09T10:00:00+00:00"}
        row = _manual_row(lane, paper=False, symbol="XAUUSD", cls="commodity",
                          entry="2650", stop="2630", target="2700",
                          meta={"care": care,
                                "thesis": {"verdict": "hold", "stop": None}})
        PositionReview.objects.create(
            book="bot", position_id=row.pk, symbol="XAUUSD", side="BUY",
            verdict="tighten", mark=2660, unrealized_r=0.5)
        with patch("bot_program.notifications.dispatch_notification"):
            orc = born(self, row, adopted=True)
        row.refresh_from_db()
        n = len(headlines(orc, kind="fact"))
        after_care(SimpleNamespace(_tick_broker_cache={}), row, "2660", "")
        self.assertEqual(facts.observe_reviews(), 0,
                         "a review read before the adoption is history")
        orc.refresh_from_db()
        self.assertEqual(headlines(orc, kind="fact")[n:], [])
        self.assertFalse(orc.hand_touched,
                         "a hand edit before the adoption is not this idea's")
        # ...and what changes after it is news again
        _care(row, soft_stop=2660.0, soft_why="trail")
        after_care(SimpleNamespace(_tick_broker_cache={}), row, "2670", "")
        self.assertEqual(headlines(orc, kind="fact")[n:], [
            "The care moved its stop to 2660.00 (trail), +0.50R."])
