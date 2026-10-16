"""PR O0b, hygiene before any Orc (docs/orcs spec §11 row O0b, §3.3).

No Orc exists after this PR. Each item below prepares the ground and keeps
every existing caller byte-identical by default:

  1. The broker-stop mover (AssetBot._move_broker_stop) and its two notes
     (_note_stop_move_failed, _note_stop_rules_inert) MERGE their keys into
     the row's metadata read fresh under a row lock, like
     position_care._save_care. A key another writer added after this tick
     loaded the row (a fresh care, a close-in-doubt marker) is no longer
     clobbered by the tick's stale copy. The mirror's in-memory
     initial_stop_loss stamp still reaches the row.
  2. A hand stop edit on a protected live row records the level the venue
     took in the care (care["venue_stop_hand"] = {level, at}, read by
     nothing until O3), tighter or wider, and never touches the mirror's
     own state (care["venue_stop"], care["venue_stop_refusal"]). The mirror
     drops the record when the venue no longer holds that level. The mirror
     sends exactly what it sends today, for one edit and for sequences of
     edits and ticks; the differential tests below prove it, and two tests
     show that a venue_stop write (literal, or tighten-only) would not.
  3. load_ohlcv(source=None): None is today's query, byte for byte.
  4. _last_look(fail_closed=False): the default returns today's dicts; True
     turns each "refuses nothing" path into a refusal.
  5. grade_bot_trade: an explicit closed:ORC branch grades manual_close.
  6. Morgul's docstring says "the guards".

Run with:  python manage.py test tests.test_o0b_hygiene
"""
import inspect
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import requests
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests.test_aragorn import _switch
from tests.test_care_mirror import _client as _mirror_client
from tests.test_risk_limits_bind import _config
from tests.test_scale_out import _trade

FIXED = datetime(2026, 10, 15, 12, 0, tzinfo=dt_tz.utc)


def _row(trade):
    from bot_program.asset_models import AssetBotTrade
    return AssetBotTrade.objects.get(pk=trade.pk)


def _other_writer(trade, **keys):
    """Another writer (the care, a manual close, a hand edit) adds keys to
    the ROW after this tick loaded `trade`: the in-memory copy is stale."""
    from bot_program.asset_models import AssetBotTrade
    fresh = AssetBotTrade.objects.get(pk=trade.pk)
    AssetBotTrade.objects.filter(pk=trade.pk).update(
        metadata={**(fresh.metadata or {}), **keys})


# ── 1. The mover merges under the row lock ──────────────────────────────

class TheMoverMergesUnderTheRowLockTests(TestCase):
    """Entry 100, sent stop 98 (tests.test_scale_out._trade)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("o0b_mv", password="x")
        self.cfg = _config(self.user, symbols=["BTCUSD"],
                           extras={"trail_pct": 5.0})
        from bot_program.asset_engine.base import make_bot
        self.bot = make_bot(self.cfg)

    def _real(self, **meta):
        return _trade(self.cfg, paper=False,
                      meta={"protected": True, "protective_trade_id": "P1",
                            **meta})

    def _move(self, trade, client, candidate="100.2", why="breakeven",
              price=102.2):
        with mock.patch("django.utils.timezone.now", return_value=FIXED):
            return self.bot._move_broker_stop(trade, price, client,
                                              Decimal(candidate), why)

    # -- with no other writer: exactly today's dict ------------------------

    def test_success_alone_persists_todays_dict(self):
        t = self._real(stop_move_failures=2, stop_move_last_error="x",
                       stop_move_last_at="y", stop_rules_inert="legs_unmovable",
                       stop_rules_inert_detail="d",
                       stop_moves=[{"to": "99", "why": "old"}])
        self.assertTrue(self._move(t, _mirror_client()))
        row = _row(t)
        self.assertEqual(row.stop_loss, Decimal("100.2"))
        self.assertEqual(row.metadata, {
            "protected": True, "protective_trade_id": "P1",
            "initial_stop_loss": 98.0,
            "stop_moves": [{"to": "99", "why": "old"},
                           {"to": "100.2", "asked": "100.2", "at": "102.2",
                            "why": "breakeven:broker",
                            "when": FIXED.isoformat()}],
            "breakeven_armed": True})
        self.assertEqual(t.metadata, row.metadata, "the tick reads the row")
        self.assertEqual(t.stop_loss, Decimal("100.2"))

    def test_a_trail_move_does_not_arm_break_even(self):
        t = self._real()
        self.assertTrue(self._move(t, _mirror_client(), "101", "trail"))
        self.assertNotIn("breakeven_armed", _row(t).metadata)

    def test_failure_alone_persists_todays_dict(self):
        t = self._real()
        self.assertFalse(self._move(t, _mirror_client(ok=False)))
        row = _row(t)
        self.assertEqual(row.stop_loss, Decimal("98"))
        self.assertEqual(row.metadata, {
            "protected": True, "protective_trade_id": "P1",
            "initial_stop_loss": 98.0, "stop_move_failures": 1,
            "stop_move_last_error": ("P1: eToro refused (400): stop too "
                                     "close to the rate"),
            "stop_move_last_at": FIXED.isoformat()})

    def test_the_third_failure_stamps_inert_as_today(self):
        t = self._real(stop_move_failures=2)
        self.assertFalse(self._move(t, _mirror_client(ok=False)))
        meta = _row(t).metadata
        self.assertEqual(meta["stop_move_failures"], 3)
        self.assertEqual(meta["stop_rules_inert"], "legs_unmovable")
        self.assertIn("stop too close", meta["stop_rules_inert_detail"])

    def test_inert_alone_persists_todays_dict(self):
        t = _trade(self.cfg, paper=False, meta={"protected": True,
                                                "stop_rules_inert_detail": "z"})
        self.assertFalse(self._move(t, _mirror_client()))     # no handle
        self.assertEqual(_row(t).metadata, {
            "protected": True, "initial_stop_loss": 98.0,
            "stop_rules_inert": "broker_protected"})

    def test_inert_twice_for_the_same_reason_writes_once(self):
        t = _trade(self.cfg, paper=False, meta={"protected": True})
        self._move(t, _mirror_client())
        with mock.patch("django.db.models.query.QuerySet.select_for_update"
                        ) as lock:
            self._move(t, _mirror_client())
        lock.assert_not_called()

    # -- another writer's keys survive -------------------------------------

    def test_success_keeps_a_care_and_a_key_written_after_load(self):
        t = self._real(stop_moves=[{"to": "99", "why": "old"}])
        care = {"soft_stop": 100.2, "venue_stop": 99.0, "peak": 102.2}
        _other_writer(t, care=care, close_in_doubt={"at": "now"},
                      stop_moves=[{"to": "99", "why": "old"},
                                  {"to": "99.5", "why": "hand"}])
        self.assertTrue(self._move(t, _mirror_client()))
        meta = _row(t).metadata
        self.assertEqual(meta["care"], care, "the fresh care is not clobbered")
        self.assertEqual(meta["close_in_doubt"], {"at": "now"})
        self.assertEqual([m["to"] for m in meta["stop_moves"]],
                         ["99", "99.5", "100.2"],
                         "the move appends to the FRESH list")
        self.assertEqual(t.metadata, meta)

    def test_failure_keeps_a_key_written_after_load_and_counts_on_the_row(self):
        t = self._real()
        _other_writer(t, care={"soft_stop": 100.2}, stop_move_failures=2)
        self.assertFalse(self._move(t, _mirror_client(ok=False)))
        meta = _row(t).metadata
        self.assertEqual(meta["care"], {"soft_stop": 100.2})
        self.assertEqual(meta["stop_move_failures"], 3,
                         "the count is read from the row, not the stale copy")
        self.assertEqual(meta["stop_rules_inert"], "legs_unmovable")

    def test_inert_keeps_a_key_written_after_load(self):
        t = _trade(self.cfg, paper=False, meta={"protected": True})
        _other_writer(t, care={"soft_stop": 100.2})
        self._move(t, _mirror_client())
        meta = _row(t).metadata
        self.assertEqual(meta["care"], {"soft_stop": 100.2})
        self.assertEqual(meta["stop_rules_inert"], "broker_protected")

    # -- the mirror's initial_stop_loss stamp ------------------------------

    def test_an_in_memory_initial_stop_loss_reaches_the_row(self):
        for ok in (True, False):
            t = self._real()
            meta = dict(t.metadata)
            meta.pop("initial_stop_loss")
            t.metadata = meta
            t.save(update_fields=["metadata"])
            t.metadata = {**meta, "initial_stop_loss": 98.0}  # the mirror's
            self._move(t, _mirror_client(ok=ok))
            self.assertEqual(_row(t).metadata["initial_stop_loss"], 98.0, ok)

    def test_the_rows_own_initial_stop_loss_wins(self):
        t = self._real()
        _other_writer(t, initial_stop_loss=97.5)
        t.metadata = {**t.metadata, "initial_stop_loss": 98.0}
        self._move(t, _mirror_client())
        self.assertEqual(_row(t).metadata["initial_stop_loss"], 97.5)

    def test_the_mirror_stamp_is_persisted_on_a_refusal(self):
        """position_care._mirror_to_venue stamps initial_stop_loss in memory
        only and relies on the mover's save (position_care.py:756-760)."""
        _switch("aragorn")
        t = self._real()
        meta = dict(t.metadata)
        meta.pop("initial_stop_loss")
        t.metadata = meta
        t.save(update_fields=["metadata"])
        from bot_program.position_care import care
        care(self.bot, t, 102.2, _mirror_client(ok=False))
        row = _row(t)
        self.assertEqual(row.metadata["initial_stop_loss"], 98.0)
        self.assertIn("stop too close",
                      row.metadata["care"]["venue_stop_refusal"])

    # -- the lock, and no lock across the venue call -----------------------

    def test_the_row_is_locked_after_the_venue_answered_never_across_it(self):
        """("lock", True) means the merge OPENED its own transaction: the
        test case already runs inside atomic blocks, so in_atomic_block
        would be True without one; the depth of the stack would not.
        Outside any transaction (a tick on Postgres in autocommit),
        select_for_update() raises TransactionManagementError."""
        from django.db.models.query import QuerySet
        real = QuerySet.select_for_update
        for ok in (True, False):
            events = []
            base = len(connection.atomic_blocks)

            def spy(qs, *a, _events=events, _base=base, **k):
                _events.append(("lock", len(connection.atomic_blocks) > _base))
                return real(qs, *a, **k)
            client = _mirror_client(ok=ok)
            answer = client.modify_protective.side_effect

            def move(oid, price, _answer=answer, _events=events):
                _events.append(("venue", None))
                return _answer(oid, price)
            client.modify_protective.side_effect = move
            t = self._real()
            with mock.patch.object(QuerySet, "select_for_update", spy):
                self._move(t, client)
            self.assertEqual(events, [("venue", None), ("lock", True)], ok)

    # -- a row with no pk: today's write ------------------------------------

    def test_a_trade_without_a_pk_writes_in_memory_and_saves_as_today(self):
        saves = []
        t = SimpleNamespace(pk=None, id=None, symbol="BTCUSD", side="BUY",
                            stop_loss=Decimal("98"), paper=False,
                            metadata={"protected": True,
                                      "protective_trade_id": "P1"},
                            save=lambda **k: saves.append(k))
        self.assertTrue(self._move(t, _mirror_client()))
        self.assertEqual(saves, [{"update_fields": ["stop_loss", "metadata"]}])
        self.assertEqual(t.stop_loss, Decimal("100.2"))
        self.assertTrue(t.metadata["breakeven_armed"])
        saves.clear()
        self.assertFalse(self._move(t, _mirror_client(ok=False)))
        self.assertEqual(saves, [{"update_fields": ["metadata"]}])
        self.assertEqual(t.metadata["stop_move_failures"], 1)

    def test_an_unsaved_model_row_raises_as_today(self):
        from bot_program.asset_models import AssetBotTrade
        t = AssetBotTrade(config=self.cfg, asset_class="crypto",
                          symbol="BTCUSD", side="BUY", qty=Decimal("1"),
                          entry_price=Decimal("100"), stop_loss=Decimal("98"),
                          status="OPEN", paper=False,
                          metadata={"protected": True,
                                    "protective_trade_id": "P1"})
        with self.assertRaises(ValueError):
            self._move(t, _mirror_client())
        self.assertEqual(t.stop_loss, Decimal("100.2"))

    def test_a_row_deleted_under_the_tick_raises_as_today(self):
        from django.db import DatabaseError
        t = self._real()
        type(t).objects.filter(pk=t.pk).delete()
        with self.assertRaises(DatabaseError):
            self._move(t, _mirror_client())


class TheMoverSourcePinsTests(SimpleTestCase):

    def test_the_three_writers_use_the_locked_merge(self):
        from bot_program.asset_engine.base import AssetBot
        for fn in (AssetBot._move_broker_stop, AssetBot._note_stop_move_failed,
                   AssetBot._note_stop_rules_inert):
            src = inspect.getsource(fn)
            self.assertIn("_merge_row_metadata(", src, fn.__name__)
            self.assertNotIn("trade.save(", src, fn.__name__)
        src = inspect.getsource(AssetBot._merge_row_metadata)
        self.assertIn("select_for_update()", src)
        self.assertIn("transaction.atomic()", src)
        self.assertIn('"initial_stop_loss"', src)

    def test_the_venue_is_asked_before_the_row_is_locked(self):
        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot._move_broker_stop)
        self.assertLess(src.index("res = mover(str(oid), float(candidate))"),
                        src.index("self._merge_row_metadata("))


# ── 2. A hand stop edit records the venue's stop for the care ───────────

class TheHandEditTellsTheCareTests(TestCase):
    """Entry 100, sent stop 98, risk 2: break-even lock 100.2 from +1R
    (mark 102), the trail at +2R (mark 104) is 102.

    Each scenario runs TWICE on fresh rows: with this PR's record, and with
    it switched off (which is HEAD's adjust_levels exactly). The mirror's
    modify_protective calls must be equal: the record changes no real-money
    send, for one hand edit and for SEQUENCES of hand edits and ticks."""

    MARK = Decimal("102")

    def setUp(self):
        self.user = get_user_model().objects.create_user("o0b_hand",
                                                         password="x")
        self.cfg = _config(self.user, symbols=["BTCUSD"])
        _switch("aragorn")
        from bot_program.asset_engine.base import make_bot
        self.bot = make_bot(self.cfg)

    def _old(self, minutes=120):
        return (timezone.now() - timedelta(minutes=minutes)).isoformat()

    def _row_with(self, *, stop="98", paper=False, protected=True, care=None,
                  side="BUY", initial=98.0):
        meta = {"initial_stop_loss": initial}    # the stop sent at entry
        if protected:
            meta.update(protected=True, protective_trade_id="P1")
        if care is not None:
            meta["care"] = care
        return _trade(self.cfg, paper=paper, stop=stop, side=side, meta=meta)

    def _hand(self, t, stop, *, mark=None, head=False):
        from bot_program.adjust_levels import adjust_levels
        hand = mock.MagicMock()
        hand.modify_protective.return_value = {"ok": True, "price": float(stop)}
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=hand), \
                mock.patch("bot_program.adjust_levels._mark_for",
                           return_value=mark or self.MARK):
            if head:
                with mock.patch("bot_program.adjust_levels._tell_the_care",
                                lambda *a, **k: None):
                    r = adjust_levels(self.user, t, stop=stop)
            else:
                r = adjust_levels(self.user, t, stop=stop)
        self.assertTrue(r["ok"], r)
        return r

    def _sequence(self, care, stop, steps, *, head=False, **row):
        """`steps`: ("hand", level[, mark]) or ("tick", price), in order, on
        one row and one venue. (the mirror's sends, the care after each
        hand edit, the care at the end)."""
        from bot_program.position_care import care as tick
        t = self._row_with(stop=stop, care=dict(care) if care else care,
                           **row)
        client = _mirror_client()
        after_hands = []
        for step in steps:
            if step[0] == "hand":
                mark = Decimal(step[2]) if len(step) > 2 else None
                self._hand(t, step[1], mark=mark, head=head)
                t.refresh_from_db()
                after_hands.append(dict((t.metadata or {}).get("care") or {}))
            else:
                t.refresh_from_db()
                tick(self.bot, t, step[1], client)
        t.refresh_from_db()
        sent = [(c.args[0], float(c.args[1]))
                for c in client.modify_protective.call_args_list]
        return sent, after_hands, dict((t.metadata or {}).get("care") or {})

    def _same_sequence(self, care, stop, steps, expected, **row):
        sent, hands, end = self._sequence(care, stop, steps, **row)
        sent_head, hands_head, end_head = self._sequence(
            care, stop, steps, head=True, **row)
        self.assertEqual(sent, sent_head, "the mirror sends what it sends "
                         "at HEAD")
        self.assertEqual(sent, expected)
        clocks = ("since", "venue_asked_at")     # each run reads its clock
        for new, old in zip(hands + [end], hands_head + [end_head]):
            # the care, the mirror's own state included, is HEAD's after
            # every hand edit and at the end; only the record differs
            self.assertNotIn("venue_stop_hand", old)
            self.assertEqual(
                {k: v for k, v in new.items()
                 if k not in clocks and k != "venue_stop_hand"},
                {k: v for k, v in old.items() if k not in clocks})
        return hands, end

    def _same_sends(self, care, stop, hand, prices, expected, **row):
        steps = [("hand", hand)] + [("tick", p) for p in prices]
        hands, _ = self._same_sequence(care, stop, steps, expected, **row)
        return hands[0]

    def _mirrored(self, **extra):
        return {"peak": 102.2, "soft_stop": 100.2, "soft_why": "breakeven",
                "venue_stop": 100.2, "venue_asked_for": 100.2,
                "venue_asked_at": self._old(), **extra}

    def _recorded(self, after, level, care):
        """`after` is `care` plus the record of `level`, nothing else."""
        self.assertEqual(after["venue_stop_hand"]["level"], level)
        self.assertTrue(after["venue_stop_hand"]["at"])
        self.assertEqual({k: v for k, v in after.items()
                          if k != "venue_stop_hand"}, care)

    # -- one hand edit ------------------------------------------------------

    def test_a_hand_widen_is_recorded_and_the_mirror_state_untouched(self):
        care = self._mirrored()
        after = self._same_sends(care, "100.2", "99", [102.1, 104.0],
                                 [("P1", 102.0)])
        self._recorded(after, 99.0, care)

    def test_the_spec_literal_write_would_re_tighten_a_hand_widen(self):
        """Why the record: writing the widened level as venue_stop makes the
        mirror re-send the soft stop on the next tick, undoing the
        operator's widen on real money (position_care.py:724-737)."""
        from bot_program import adjust_levels as al

        def literal(meta, stop, *, at):
            meta["care"] = {**meta["care"], "venue_stop": float(stop)}
        with mock.patch.object(al, "_tell_the_care", literal):
            sent, _, _ = self._sequence(self._mirrored(), "100.2",
                                        [("hand", "99"), ("tick", 102.1),
                                         ("tick", 104.0)])
        self.assertEqual(sent, [("P1", 100.2), ("P1", 102.0)])

    def test_a_tighten_only_write_would_skip_a_later_care_lock(self):
        """Why not even a tighten-only write (the review of O0b): the
        tightened level stays recorded after a later hand widen, and the
        mirror skips the care lock between the two (position_care.py:
        724-726) where today it copies it to the venue."""
        from bot_program import adjust_levels as al

        def tighten_only(meta, stop, *, at):
            care, level = dict(meta["care"]), float(stop)
            if care.get("venue_stop") is None or level >= care["venue_stop"]:
                care["venue_stop"] = level
            meta["care"] = care
        steps = [("hand", "101"), ("hand", "99"), ("tick", 102.1)]
        care = {"peak": 100.5, "worst": 99.5, "since": self._old()}
        with mock.patch.object(al, "_tell_the_care", tighten_only):
            sent, _, _ = self._sequence(care, "98", steps)
        self.assertEqual(sent, [])
        self._same_sequence(care, "98", steps, [("P1", 100.2)])

    def test_a_hand_tighten_above_the_soft_stop(self):
        care = self._mirrored()
        after = self._same_sends(care, "100.2", "101",
                                 [102.1, 103.0, 104.0], [("P1", 102.0)])
        self._recorded(after, 101.0, care)

    def test_a_hand_tighten_between_the_venue_and_the_soft_stop(self):
        care = self._mirrored(venue_stop=99.0,
                              venue_stop_refusal="stop too close")
        after = self._same_sends(care, "99", "99.5", [102.1, 104.0],
                                 [("P1", 100.2), ("P1", 102.0)])
        self._recorded(after, 99.5, care)

    def test_no_recorded_venue_stop(self):
        care = {"peak": 102.2, "soft_stop": 100.2, "soft_why": "breakeven"}
        after = self._same_sends(care, "98", "99", [102.1, 104.0],
                                 [("P1", 100.2), ("P1", 102.0)])
        self._recorded(after, 99.0, care)
        after = self._same_sends(care, "98", "101", [102.1, 104.0],
                                 [("P1", 102.0)])
        self._recorded(after, 101.0, care)

    def test_a_refusal_pending(self):
        care = {"peak": 102.2, "soft_stop": 100.2, "soft_why": "breakeven",
                "venue_stop": 98.5, "venue_stop_refusal": "stop too close",
                "venue_asked_for": 100.2, "venue_asked_at": self._old(5)}
        after = self._same_sends(care, "98.5", "98", [102.1, 104.0],
                                 [("P1", 102.0)])
        self._recorded(after, 98.0, care)
        after = self._same_sends(care, "98.5", "101", [102.1, 104.0],
                                 [("P1", 102.0)])
        self._recorded(after, 101.0, care)
        # the pacing passes: the same answer both ways
        care["venue_asked_at"] = self._old()
        self._same_sends(care, "98.5", "99", [102.1, 104.0],
                         [("P1", 100.2), ("P1", 102.0)])

    def test_a_paper_row_is_never_told(self):
        after = self._same_sends(self._mirrored(), "100.2", "101",
                                 [102.1, 104.0], [], paper=True)
        self.assertEqual(after, self._mirrored(
            venue_asked_at=after["venue_asked_at"]))

    def test_an_unprotected_row_is_never_told(self):
        after = self._same_sends(self._mirrored(), "100.2", "101",
                                 [102.1, 104.0], [], protected=False)
        self.assertEqual(after, self._mirrored(
            venue_asked_at=after["venue_asked_at"]))

    def test_no_care_dict_is_created(self):
        t = self._row_with(stop="98")
        self._hand(t, "99")
        t.refresh_from_db()
        self.assertNotIn("care", t.metadata)
        self.assertEqual(t.metadata["level_edits"][-1]["stop"], "99")

    def test_a_target_only_edit_leaves_the_care(self):
        from bot_program.adjust_levels import adjust_levels
        t = self._row_with(stop="100.2", care=self._mirrored())
        hand = mock.MagicMock()
        hand.modify_target.return_value = {"ok": True, "price": 112.0}
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=hand), \
                mock.patch("bot_program.adjust_levels._mark_for",
                           return_value=self.MARK):
            self.assertTrue(adjust_levels(self.user, t, target="112")["ok"])
        t.refresh_from_db()
        self.assertEqual(t.metadata["care"], self._mirrored(
            venue_asked_at=t.metadata["care"]["venue_asked_at"]))

    def test_the_record_names_the_last_edit_either_way(self):
        from bot_program.adjust_levels import _tell_the_care
        meta = {"care": {"venue_stop": 99.8, "venue_stop_refusal": "x"}}
        _tell_the_care(meta, Decimal("99.5"), at="t1")
        self.assertEqual(meta["care"], {
            "venue_stop": 99.8, "venue_stop_refusal": "x",
            "venue_stop_hand": {"level": 99.5, "at": "t1"}})
        _tell_the_care(meta, Decimal("101"), at="t2")
        self.assertEqual(meta["care"], {
            "venue_stop": 99.8, "venue_stop_refusal": "x",
            "venue_stop_hand": {"level": 101.0, "at": "t2"}})
        meta = {"care": "not a dict"}
        _tell_the_care(meta, Decimal("101"), at="t3")
        self.assertEqual(meta, {"care": "not a dict"})

    def test_the_write_rides_the_locked_save(self):
        from bot_program import adjust_levels as al
        src = inspect.getsource(al.adjust_levels)
        lock = src.index("select_for_update()")
        tell = src.index("_tell_the_care(meta, stop, at=edit_at)")
        save = src.index("fresh.save(update_fields=fields)")
        self.assertLess(lock, tell)
        self.assertLess(tell, save)

    # -- a short through adjust_levels and the mirror ----------------------

    def test_a_short_hand_widen_sends_what_head_sends(self):
        """Every scenario above is a BUY: a short's widen is UPWARD, and a
        side read wrong would undo it on real money."""
        care = {"peak": 97.8, "soft_stop": 99.8, "soft_why": "breakeven",
                "venue_stop": 99.8, "venue_asked_for": 99.8,
                "venue_asked_at": self._old()}
        hands, end = self._same_sequence(
            care, "99.8", [("hand", "101", "98"), ("tick", 97.9),
                           ("tick", 96.0)],
            [("P1", 98.0)], side="SELL", initial=102.0)
        self._recorded(hands[0], 101.0, care)
        self.assertNotIn("venue_stop_hand", end, "the mirror moved the venue")

    def test_a_short_hand_tighten_sends_what_head_sends(self):
        care = {"peak": 97.8, "soft_stop": 99.8, "soft_why": "breakeven",
                "venue_stop": 99.8, "venue_asked_for": 99.8,
                "venue_asked_at": self._old()}
        self._same_sequence(
            care, "99.8", [("hand", "99", "98"), ("tick", 97.9),
                           ("tick", 96.0)],
            [("P1", 98.0)], side="SELL", initial=102.0)

    # -- sequences of hand edits (the review of O0b) -----------------------

    def test_tighten_then_widen_then_the_break_even_lock(self):
        """No soft stop yet: a hand tighten to 101, a hand widen to 99, then
        the break-even lock 100.2 arrives and is copied to the venue."""
        care = {"peak": 100.5, "worst": 99.5, "since": self._old()}
        self._same_sequence(care, "98", [("hand", "101"), ("hand", "99"),
                                         ("tick", 102.1)], [("P1", 100.2)])

    def test_tighten_then_widen_under_a_mirrored_level(self):
        care = self._mirrored(since=self._old())
        self._same_sequence(care, "100.2",
                            [("hand", "101.5"), ("hand", "99"),
                             ("tick", 103.3), ("tick", 103.6)],
                            [("P1", 101.3), ("P1", 101.6)])

    def test_tighten_far_then_widen_then_the_trail(self):
        self._same_sequence(self._mirrored(), "100.2",
                            [("hand", "103", "103.5"), ("hand", "101", "103.5"),
                             ("tick", 104.0)], [("P1", 102.0)])

    def test_tighten_then_widen_with_a_refusal_pending(self):
        care = self._mirrored(venue_stop=99.0,
                              venue_stop_refusal="stop too close")
        self._same_sequence(care, "99", [("hand", "101"), ("hand", "99.5"),
                                         ("tick", 102.1)], [("P1", 100.2)])

    def test_tighten_tick_widen_tick(self):
        """The mirror's held branch records the hand's 103 between the two
        edits (position_care.py:744-750), at HEAD and here alike."""
        hands, end = self._same_sequence(
            self._mirrored(), "100.2",
            [("hand", "103", "103.5"), ("tick", 104.0),
             ("hand", "101", "104"), ("tick", 105.0)], [])
        self.assertEqual(end["venue_stop"], 103.0)
        self.assertEqual(end["venue_stop_hand"]["level"], 101.0)

    # -- the mirror drops a record the venue no longer holds ---------------

    def test_the_mirrors_move_drops_the_hand_record(self):
        hands, end = self._same_sequence(
            self._mirrored(), "100.2", [("hand", "99"), ("tick", 104.0)],
            [("P1", 102.0)])
        self.assertEqual(hands[0]["venue_stop_hand"]["level"], 99.0)
        self.assertEqual(end["venue_stop"], 102.0)
        self.assertNotIn("venue_stop_hand", end)

    def test_the_held_branch_keeps_a_record_the_venue_still_holds(self):
        care = self._mirrored(venue_stop=99.0,
                              venue_stop_refusal="stop too close")
        hands, end = self._same_sequence(
            care, "99", [("hand", "101"), ("tick", 102.1)], [])
        self.assertEqual(end["venue_stop"], 101.0)
        self.assertNotIn("venue_stop_refusal", end)
        self.assertEqual(end["venue_stop_hand"], hands[0]["venue_stop_hand"])

    def test_the_held_branch_drops_a_record_of_another_level(self):
        """The row's stop moved past the hand's level since the edit (the
        engine's own rules): the record no longer names the venue's stop."""
        from bot_program.position_care import care as tick
        care = self._mirrored(venue_stop=99.0,
                              venue_stop_refusal="stop too close",
                              venue_stop_hand={"level": 101.0, "at": "t"})
        t = self._row_with(stop="101.5", care=care)
        tick(self.bot, t, 102.1, _mirror_client())
        t.refresh_from_db()
        self.assertEqual(t.metadata["care"]["venue_stop"], 101.5)
        self.assertNotIn("venue_stop_hand", t.metadata["care"])


# ── 3. load_ohlcv(source=None) ──────────────────────────────────────────

class LoadOhlcvBySourceTests(TestCase):

    def setUp(self):
        from instruments.models import Instrument
        from market_data.models import PriceData
        self.inst = Instrument.objects.create(symbol="O0BX", name="X",
                                              asset_class="commodity",
                                              is_active=True)
        t0 = datetime(2026, 10, 1, tzinfo=dt_tz.utc)
        for i in range(6):
            PriceData.objects.create(
                instrument=self.inst, timeframe="4h",
                timestamp=t0 + timedelta(hours=4 * i),
                open=Decimal("10"), high=Decimal("11"), low=Decimal("9"),
                close=Decimal(str(10 + i)), volume=100 + i,
                source="etoro" if i % 2 else "yahoo")
        PriceData.objects.create(
            instrument=self.inst, timeframe="1h", timestamp=t0,
            open=1, high=1, low=1, close=1, volume=1, source="etoro")

    def test_the_default_query_is_todays(self):
        from market_data.models import PriceData
        from signals.smc.dataframe import load_ohlcv
        with CaptureQueriesContext(connection) as plain:
            a = load_ohlcv("O0BX")
        self.assertEqual(list(a["close"]), [10.0, 11.0, 12.0, 13.0, 14.0,
                                            15.0])
        # today's bar query, built by hand: instrument, then timeframe
        with CaptureQueriesContext(connection) as hand:
            list(PriceData.objects.filter(instrument=self.inst)
                 .filter(timeframe="4h").order_by("-timestamp")[:500])
        self.assertEqual(plain.captured_queries[-1]["sql"],
                         hand.captured_queries[-1]["sql"])

    def test_source_none_is_the_default_query(self):
        import pandas as pd

        from signals.smc.dataframe import load_ohlcv
        for args in ((), ("1h",), ("4h", 3)):
            with CaptureQueriesContext(connection) as plain:
                a = load_ohlcv("O0BX", *args)
            with CaptureQueriesContext(connection) as none:
                b = load_ohlcv("O0BX", *args, source=None)
            self.assertEqual([q["sql"] for q in plain.captured_queries],
                             [q["sql"] for q in none.captured_queries], args)
            pd.testing.assert_frame_equal(a, b)
        self.assertIsNone(load_ohlcv("NOPE", source=None))

    def test_a_source_reads_only_its_bars(self):
        from signals.smc.dataframe import load_ohlcv
        df = load_ohlcv("O0BX", source="etoro")
        self.assertEqual(list(df["close"]), [11.0, 13.0, 15.0])
        df = load_ohlcv("O0BX", "4h", 2, source="yahoo")
        self.assertEqual(list(df["close"]), [12.0, 14.0])
        for many in (["etoro", "yahoo"], ("etoro", "yahoo"),
                     {"etoro", "yahoo"}, frozenset({"etoro", "yahoo"})):
            self.assertEqual(len(load_ohlcv("O0BX", source=many)), 6, many)
        self.assertIsNone(load_ohlcv("O0BX", source="oanda"))
        self.assertEqual(len(load_ohlcv("O0BX", "1h", source="etoro")), 1)

    def test_the_signature(self):
        from signals.smc.dataframe import load_ohlcv
        params = inspect.signature(load_ohlcv).parameters
        self.assertEqual([(n, p.default) for n, p in params.items()],
                         [("symbol", inspect.Parameter.empty),
                          ("timeframe", "4h"), ("bars", 500),
                          ("source", None)])


# ── 4. _last_look(fail_closed=False) ────────────────────────────────────

class _Resp:
    def __init__(self, code):
        self.status_code = code


def _named(name):
    cls = type(name, (mock.MagicMock,), {})
    return cls()


class TheLastLookFailClosedTests(SimpleTestCase):
    """The harness of tests/test_entry_holds.py:301-305."""

    TICK = {"lastPrice": "1.1", "bid": "1.0999", "ask": "1.1001"}
    VERDICT = {"mid": 1.1, "bid": 1.0999, "ask": 1.1001, "last_price": 1.1,
               "half_spread_r": 0.01}
    EMPTY = {"skip": "", "why": "", "quote": None}

    # what _entry_quote_gate returns when its read failed (base.py's except)
    GATE_UNREAD = {"ok": True, "why": "", "verdict": {}, "unread": True}

    def _bot(self, drift=None, gate=None):
        bot = mock.Mock(asset_class="forex")
        if isinstance(drift, Exception):
            bot._drift_since_proposal.side_effect = drift
        else:
            bot._drift_since_proposal.return_value = drift or ""
        bot._entry_quote_gate.return_value = gate or {
            "ok": True, "why": "", "verdict": dict(self.VERDICT)}
        return bot

    def _look(self, client, *, bot=None, **kw):
        from bot_program.asset_engine.base import AssetBot
        return AssetBot._last_look(bot or self._bot(), client, "EURUSD",
                                   "BUY", 1.1, 1.09, 1.12, **kw)

    def _client(self, *, tick=None, raises=None):
        client = mock.MagicMock()
        if raises is not None:
            client.ticker.side_effect = raises
        else:
            client.ticker.return_value = tick
        return client

    def _branches(self):
        return {
            "unreadable": (self._client(raises=RuntimeError("socket")), None),
            "not a dict": (self._client(tick=["1.1"]), None),
            "no price": (self._client(tick={"lastPrice": 0}), None),
            "drift unread": (self._client(tick=dict(self.TICK)),
                             self._bot(drift=RuntimeError("no proposal"))),
            "gate unread": (self._client(tick=dict(self.TICK)),
                            self._bot(gate=dict(self.GATE_UNREAD))),
            # the gate's only empty verdict is its except branch
            # (mark_sanity.entry_quote always returns its keys)
            "gate verdict empty": (self._client(tick=dict(self.TICK)),
                                   self._bot(gate={"ok": True, "why": "",
                                                   "verdict": {}})),
        }

    QUOTED = {"skip": "", "why": "", "quote": {
        "mid": 1.1, "bid": 1.0999, "ask": 1.1001, "last_price": 1.1,
        "age_s": None, "half_spread_r": 0.01, "proposal_price": 1.1}}
    # today's answer when the gate could not judge the quote: the order goes
    UNJUDGED = {"skip": "", "why": "", "quote": {
        "mid": None, "bid": None, "ask": None, "last_price": None,
        "age_s": None, "half_spread_r": None, "proposal_price": 1.1}}

    def _want(self):
        return {"unreadable": self.EMPTY, "not a dict": self.EMPTY,
                "no price": self.EMPTY, "drift unread": self.QUOTED,
                "gate unread": self.UNJUDGED,
                "gate verdict empty": self.UNJUDGED}

    def test_the_default_returns_todays_dicts(self):
        for name, (client, bot) in self._branches().items():
            self.assertEqual(self._look(client, bot=bot), self._want()[name],
                             name)

    def test_an_explicit_false_is_the_default(self):
        for name, (client, bot) in self._branches().items():
            self.assertEqual(self._look(client, bot=bot, fail_closed=False),
                             self._want()[name], name)

    def test_fail_closed_refuses_each_branch_in_words(self):
        words = {"unreadable": "could not read the quote (socket)",
                 "not a dict": "got no quote back",
                 "no price": "read a quote with no price",
                 "drift unread": "could not read the drift since the "
                                 "proposal (no proposal)",
                 "gate unread": "could not read the entry quote's sanity",
                 "gate verdict empty": "could not read the entry quote's "
                                       "sanity"}
        for name, (client, bot) in self._branches().items():
            out = self._look(client, bot=bot, fail_closed=True)
            self.assertEqual(out["skip"], "", name)
            self.assertIn("EURUSD: the last look ", out["refused"], name)
            self.assertIn(words[name], out["refused"], name)
            self.assertIn("nothing sent: this look fails closed",
                          out["refused"], name)

    def test_a_readable_look_is_the_same_either_way(self):
        for drift in ("", "the price ran half-way to the stop"):
            a = self._look(self._client(tick=dict(self.TICK)),
                           bot=self._bot(drift))
            b = self._look(self._client(tick=dict(self.TICK)),
                           bot=self._bot(drift), fail_closed=True)
            self.assertEqual(a, b, drift)
            self.assertNotIn("refused", b)

    # -- the real entry quote gate: a lost verdict says it is unread -------

    BAD = {"ok": False, "why": "the quote is crossed", "mid": 1.1,
           "mark": {"mid": 1.1, "same_since": "t0"}}

    def _gate(self, *, verdict=None, save_raises=None, read_raises=None):
        """AssetBot._entry_quote_gate on a stand-in bot, the sanity read and
        the entry_marks save replaced."""
        from bot_program.asset_engine.base import AssetBot
        bot = mock.Mock(asset_class="forex")
        quote = mock.Mock(side_effect=read_raises,
                          return_value=dict(verdict or self.BAD))
        with mock.patch("bot_program.mark_sanity.entry_quote", quote), \
                mock.patch("bot_program.asset_engine.safety._extras",
                           return_value={}), \
                mock.patch("bot_program.asset_engine.safety._save_extras",
                           side_effect=save_raises):
            return AssetBot._entry_quote_gate(bot, "EURUSD", dict(self.TICK),
                                              mock.MagicMock(), stop=1.09)

    def test_a_judged_quote_carries_no_unread_flag(self):
        self.assertEqual(self._gate(), {"ok": False,
                                        "why": "the quote is crossed",
                                        "verdict": self.BAD})

    def test_a_failed_save_is_unread_and_lets_the_entry_go_as_today(self):
        from django.db import DatabaseError
        for kw in ({"save_raises": DatabaseError("locked")},
                   {"read_raises": RuntimeError("no class")}):
            self.assertEqual(self._gate(**kw), self.GATE_UNREAD, kw)

    def test_a_failed_save_after_a_bad_verdict_refuses_when_failing_closed(self):
        """The review's case: entry_quote judged the quote BAD, then the
        entry_marks save raised; the except discards the verdict. The
        default lets the order go, as today; fail_closed refuses."""
        from django.db import DatabaseError
        gate = self._gate(save_raises=DatabaseError("locked"))
        client = self._client(tick=dict(self.TICK))
        self.assertEqual(self._look(client, bot=self._bot(gate=dict(gate))),
                         self.UNJUDGED)
        out = self._look(client, bot=self._bot(gate=dict(gate)),
                         fail_closed=True)
        self.assertIn("could not read the entry quote's sanity",
                      out["refused"])
        self.assertIsNone(out["quote"])

    def test_the_proposal_reads_ok_and_why_only(self):
        """The proposal's own gate call (AssetBot.propose_entry) reads ok
        and why, so the unread flag changes nothing there."""
        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.propose_entry)
        self.assertEqual(src.count("self._entry_quote_gate("), 1)
        self.assertNotIn('_quote.get(', src)
        self.assertEqual(set(__import__("re").findall(r'_quote\["(\w+)"\]',
                                                     src)), {"ok", "why"})

    def _429_and_pause(self, **kw):
        err = requests.HTTPError("429 Client Error", response=_Resp(429))
        client = _named("EtoroTrader")
        client.ticker.side_effect = err
        self.assertEqual(self._look(client, **kw),
                         {"skip": "", "why": "", "quote": None,
                          "refused": "EURUSD: the last look met eToro's 429 — "
                                     "nothing sent on the proposal's price"},
                         kw)
        client = _named("EtoroTrader")
        client.ticker.side_effect = RuntimeError("500")
        with mock.patch("bot_program.venue_health.pause_s", return_value=20):
            self.assertEqual(
                self._look(client, **kw)["refused"],
                "EURUSD: the last look could not read the quote inside "
                "eToro's 429 pause (20s left) — nothing sent on the "
                "proposal's price", kw)

    def test_the_429_and_the_pause_at_the_default(self):
        self._429_and_pause()

    def test_the_429_and_the_pause_are_unchanged_when_failing_closed(self):
        self._429_and_pause(fail_closed=False)
        self._429_and_pause(fail_closed=True)

    def test_the_only_caller_keeps_the_default(self):
        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.execute_entry)
        self.assertEqual(src.count("self._last_look("), 1)
        self.assertNotIn("fail_closed", src)
        params = inspect.signature(AssetBot._last_look).parameters
        self.assertEqual(params["fail_closed"].default, False)
        self.assertEqual(params["fail_closed"].kind,
                         inspect.Parameter.KEYWORD_ONLY)


# ── 5. closed:ORC grades as a hand close ────────────────────────────────

class ClosedOrcGradesAsAHandCloseTests(TestCase):

    def setUp(self):
        from tests.test_phase17_bot_grading import _abc, _user
        self.cfg = _abc(_user("o0b_grade"), "stock", name="O0B")

    def _grade(self, reason, *, side="BUY", exit_=94, sl=95, tp=110):
        from bot_program.bot_grading import grade_bot_trade
        from tests.test_phase17_bot_grading import _closed_trade
        entry = 100
        if side == "SELL":
            sl, tp = 2 * entry - sl, 2 * entry - tp
            exit_ = 2 * entry - exit_
        t = _closed_trade(self.cfg, symbol="AAPL", side=side, entry=entry,
                          exit=exit_, sl=sl, tp=tp, qty=10, reason=reason)
        self.assertTrue(grade_bot_trade(t))
        t.refresh_from_db()
        return t.outcome

    def test_an_orc_exit_at_or_past_the_stop_or_the_target(self):
        for side in ("BUY", "SELL"):
            self.assertEqual(self._grade("x | closed:ORC", side=side),
                             "manual_close", side)
            self.assertEqual(self._grade("x | closed:ORC", side=side,
                                         exit_=95), "manual_close", side)
            self.assertEqual(self._grade("closed:ORC", side=side, exit_=111),
                             "manual_close", side)
            self.assertEqual(self._grade("x | closed:ORC:trim", side=side),
                             "manual_close", side)

    def test_today_the_same_exits_grade_by_price(self):
        """What the branch changes: without it these grade by price."""
        for side in ("BUY", "SELL"):
            self.assertEqual(self._grade("x | closed:MANUAL", side=side),
                             "stopped_out", side)
            self.assertEqual(self._grade("x | closed:MANUAL", side=side,
                                         exit_=111), "hit_target", side)

    def test_a_longer_word_falls_through(self):
        for reason in ("x | closed:ORCA", "x | closed:ORC_EXIT",
                       "x | closed:ORC9"):
            self.assertEqual(self._grade(reason), "stopped_out", reason)

    def test_the_venues_and_the_engines_words_still_win(self):
        self.assertEqual(self._grade("closed:ORC | closed:SL"), "stopped_out")
        self.assertEqual(self._grade("closed:ORC | closed:TP", exit_=111),
                         "hit_target")
        self.assertEqual(self._grade("closed:ORC | closed:TIME"), "time_stop")
        self.assertEqual(self._grade("EXPIRY_CLOSE closed:ORC"), "expired")


class NothingWritesClosedOrcYetTests(SimpleTestCase):

    def test_no_reason_in_the_code_says_closed_orc(self):
        import pathlib
        root = pathlib.Path(__file__).resolve().parent.parent
        hits = []
        for path in root.rglob("*.py"):
            rel = path.relative_to(root).as_posix()
            if rel.startswith(("tests/", "venv/", ".venv/", "env/")) \
                    or "site-packages/" in rel or "/." in "/" + rel:
                continue
            if rel == "bot_program/bot_grading.py":
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if 'reason="ORC"' in text or "closed:ORC" in text:
                hits.append(rel)
        self.assertEqual(hits, [], "nothing closes as ORC until O3")


# ── 6. Morgul's guards are guards ───────────────────────────────────────

class MorgulsGuardsAreGuardsTests(SimpleTestCase):

    def test_the_docstring_says_the_guards(self):
        from bot_program import morgul
        first = morgul.__doc__.splitlines()[0]
        self.assertEqual(first, "THE MORGUL GUARDS: the guards that save "
                                "Sauron from itself (2026-09-26).")
        self.assertNotIn("orcs", first.lower())

    def test_the_test_modules_docstring_too(self):
        from tests import test_morgul
        self.assertTrue(test_morgul.__doc__.startswith(
            "The Morgul guards: the guards that save Sauron from itself "
            "(2026-09-26)."))
