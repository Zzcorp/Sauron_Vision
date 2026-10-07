"""WHICH EXIT CLOSED IT (2026-10-07, PR51a; bot_program/scorecard.py,
`manage.py scorecard --by exit`).

Before any exit is changed (PR51b's be_only drops care's +1.5R trail), the
operator reads which exit closed each live trade. If the seven winners of
the last 30 days were closed by the +0.1R break-even, the weekend or the
event lock rather than the trail, dropping the trail changes none of them.

Pinned here:
  - exit_of: one label per row from what the row recorded, first match
    wins (by hand, care's lock, the time stop, the target, the mirrored
    stop at its lock, the stop, other), on outcomes bot_grading itself
    wrote — never a new spelling; the mirrored stop's lock is the one the
    venue's last accepted stop move names, never care's newest soft_why
    (review, 2026-10-07);
  - the row keys: the exit, the policy (care until PR51b stamps one), the
    shadow (the row's own R until PR51b records care's), inferred (the
    flag, or an exit booked at a mark or at a venue level: every close the
    platform sends to eToro), closed at the venue, and the close window the
    reconcile writes (PR50, venue_exit.CLOSED_BETWEEN_KEY) read as (lo, hi);
  - the two lines under --by exit: inferred exit prices k of n, and live
    stock and ETF venue closes outside 09:30-16:00 New York k of n, the
    window's lo moved back by the list's lag (LIST_LAG_S) — or
    "unmeasured" when no close window is recorded;
  - the command: a block per exit, the two lines only under --by exit,
    and no --by policy before an exit policy exists.

Run with:  python manage.py test tests.test_scorecard_by_exit
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

import tests.test_venue_exit as ve
from bot_program import scorecard as sc

UTC = dt_timezone.utc
UNMEASURED = ("outside regular hours: unmeasured — the venue's close time "
              "is not recorded")


def _at(day, hh, mm=0, ss=0, *, month=10):
    """A UTC instant in 2026 (October: New York is UTC-4)."""
    return datetime(2026, month, day, hh, mm, ss, tzinfo=UTC)


def _window(lo, hi):
    """The close window as the reconcile writes it (reconcile_asset.py:
    `[between[0].isoformat(), between[1].isoformat()]`)."""
    return [lo.isoformat(), hi.isoformat()]


def _move(to, why, when=None):
    """A stop move the venue accepted, as base._move_broker_stop records it:
    `to` the level the venue took, `why` + ":broker"."""
    return {"to": to, "asked": to, "at": "103", "why": why + ":broker",
            "when": (when or _at(6, 15)).isoformat()}


class _Book(TestCase):
    """A live stock book: a long at 100 with a 95 stop and a 110 target,
    10 shares (1R = $50), every row graded by bot_grading itself."""

    @classmethod
    def setUpTestData(cls):
        from bot_program.models import AssetBotConfig
        user = get_user_model().objects.create_user("sc_exit_u", password="x")
        cls.cfg = AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="EXITS", mode="live",
            symbols=["NVDA"], capital=Decimal("10000"), enabled=True)

    def mk(self, *, exit_price="100", reason="bollinger_squeeze_breakout",
           stop="95", meta=None, paper=False, asset_class="stock",
           symbol="NVDA", grade=True):
        from bot_program.bot_grading import grade_bot_trade
        from bot_program.models import AssetBotTrade
        now = timezone.now()
        m = {"initial_stop_loss": 95.0}
        m.update(meta or {})
        exit_p = Decimal(exit_price)
        t = AssetBotTrade.objects.create(
            config=self.cfg, asset_class=asset_class, symbol=symbol,
            side="BUY", qty=Decimal("10"), entry_price=Decimal("100"),
            stop_loss=Decimal(stop), take_profit=Decimal("110"),
            exit_price=exit_p, pnl=(exit_p - Decimal("100")) * 10,
            status="CLOSED", paper=paper, rule_name="bollinger_squeeze_breakout",
            reason=reason, metadata=m)
        AssetBotTrade.objects.filter(pk=t.pk).update(
            opened_at=now - timedelta(days=3), closed_at=now - timedelta(days=1))
        t.refresh_from_db()
        if grade:
            self.assertTrue(grade_bot_trade(t))
            t.refresh_from_db()
        return t


# ── exit_of, on outcomes bot_grading wrote ──────────────────────────────

class TheExitLabelTests(_Book):

    def test_a_hand_close_is_by_hand_before_anything_the_row_recorded(self):
        t = self.mk(exit_price="95", reason="x | closed:MANUAL",
                    meta={"care_exit": "trail",
                          "care": {"venue_stop": 101.0, "soft_why": "trail"}})
        self.assertEqual(sc.exit_of(t), "by hand")

    def test_care_names_its_own_lock_crowd_move_kept(self):
        t = self.mk(exit_price="103.5", reason="x | closed:SL",
                    meta={"care_exit": "trail (beyond the crowd)"})
        self.assertEqual(t.outcome, sc.STOPPED_OUT)
        self.assertEqual(sc.exit_of(t), "care: trail (beyond the crowd)")

    def test_cares_no_progress_is_cares_not_the_time_stop(self):
        t = self.mk(exit_price="100.5", reason="x | closed:TIME",
                    meta={"care_exit": "no progress"})
        self.assertEqual(t.outcome, sc.TIME_STOP)
        self.assertEqual(sc.exit_of(t), "care: no progress")

    def test_the_time_stop(self):
        t = self.mk(exit_price="99", reason="x | closed:TIME")
        self.assertEqual(t.outcome, "time_stop")
        self.assertEqual(sc.exit_of(t), "time stop")

    def test_the_target(self):
        t = self.mk(exit_price="110", reason="x | reconciled-orphan")
        self.assertEqual(t.outcome, "hit_target")
        self.assertEqual(sc.exit_of(t), "target")

    def test_a_mirrored_soft_stop_filled_at_the_venue_names_its_lock(self):
        """NVDA #131's shape: care's break-even copied onto the eToro stop
        (the move base._move_broker_stop records), filled there, booked by
        the reconcile at the level."""
        t = self.mk(exit_price="100.5", stop="100.5",
                    reason="x | reconciled-orphan",
                    meta={"care": {"soft_stop": 100.5, "venue_stop": 100.5,
                                   "soft_why": "breakeven"},
                          "stop_moves": [_move("100.5", "care breakeven")]})
        self.assertEqual(t.outcome, "stopped_out")
        self.assertEqual(sc.exit_of(t), "stop at breakeven")
        # the mirror of a lock with no name (why "care lock") still says it
        # was care's
        t.metadata["stop_moves"] = [_move("100.5", "care lock")]
        self.assertEqual(sc.exit_of(t), "stop at lock")

    def test_the_stop_sent_with_the_order(self):
        t = self.mk(exit_price="95", reason="x | reconciled-orphan",
                    meta={"care": {"soft_stop": 100.1}})
        self.assertEqual(t.outcome, "stopped_out")
        self.assertEqual(sc.exit_of(t), "stop")

    def test_the_lock_is_the_one_the_venue_took_not_cares_newest(self):
        """(2026-10-07, review) care.soft_why names care's newest lock every
        tick; the venue's stop moves only when a mirror is accepted. The
        trail's mirror refused (an eToro 429): the break-even still rests
        there and fills — "stop at breakeven", never "stop at trail"."""
        t = self.mk(exit_price="100.1", stop="100.1",
                    reason="x | reconciled-orphan",
                    meta={"care": {"soft_stop": 103.0, "soft_why": "trail",
                                   "venue_stop": 100.1,
                                   "venue_stop_refusal": "HTTP 429"},
                          "stop_moves": [_move("100.1", "care breakeven")]})
        self.assertEqual(t.outcome, "stopped_out")
        self.assertEqual(sc.exit_of(t), "stop at breakeven")

    def test_a_stop_care_did_not_set_last_is_the_stop(self):
        """(2026-10-07, review) The venue's stop last set by anything but
        care's mirror reads "stop", whatever care.venue_stop says."""
        cases = {
            # the held branch: the engine's trail knob set 101, care's
            # looser break-even was remembered as the venue's, never sent
            "engine trail, held by care": (
                "101", {"care": {"soft_stop": 100.2, "soft_why": "breakeven",
                                 "venue_stop": 101.0},
                        "stop_moves": [_move("101", "trail")]}),
            # the operator's own level on the venue: held, no move recorded
            "operator's level, held by care": (
                "101", {"care": {"soft_stop": 100.2, "soft_why": "breakeven",
                                 "venue_stop": 101.0}}),
            # care mirrored its break-even, then the engine's knob moved on
            "engine knob after care's mirror": (
                "101", {"care": {"soft_stop": 100.2, "soft_why": "breakeven",
                                 "venue_stop": 100.2},
                        "stop_moves": [_move("100.2", "care breakeven"),
                                       _move("101", "breakeven")]}),
            # care's mirror, then the levels edited by hand (no stop move)
            "a hand edit after care's mirror": (
                "99", {"care": {"soft_stop": 100.2, "soft_why": "breakeven",
                                "venue_stop": 100.2},
                       "stop_moves": [_move("100.2", "care breakeven")]}),
        }
        for name, (stop, meta) in cases.items():
            with self.subTest(name):
                t = self.mk(exit_price=stop, stop=stop,
                            reason="x | reconciled-orphan", meta=meta)
                self.assertEqual(t.outcome, "stopped_out")
                self.assertEqual(sc.exit_of(t), "stop")

    def test_the_mirror_refused_end_to_end(self):
        """Through position care itself (make_bot, care, the engine's one
        mover; test_care_mirror's book: entry 100, sent stop 98): the
        break-even mirrored at 102.2, the trail's mirror refused at 104 — the
        venue's break-even fills and reads as the break-even."""
        from bot_program.asset_engine.base import make_bot
        from bot_program.bot_grading import grade_bot_trade
        from bot_program.position_care import care
        from tests.test_aragorn import _switch
        from tests.test_care_mirror import _client
        from tests.test_risk_limits_bind import _config
        from tests.test_scale_out import _trade
        _switch("aragorn")
        cfg = _config(self.cfg.user, symbols=["BTCUSD"])
        bot = make_bot(cfg)
        t = _trade(cfg, paper=False, meta={"protected": True,
                                           "protective_trade_id": "P1"})
        care(bot, t, 102.2, _client())
        care(bot, t, 104.0, _client(ok=False, reason="HTTP 429"))
        t.refresh_from_db()
        c = t.metadata["care"]
        self.assertEqual((c["soft_why"], c["venue_stop"], t.stop_loss),
                         ("trail", 100.2, Decimal("100.2")))
        self.assertIn("429", c["venue_stop_refusal"])
        # the venue fills its break-even; the reconcile books it at the level
        t.status, t.exit_price = "CLOSED", Decimal("100.2")
        t.pnl, t.reason = Decimal("0.2"), "x | reconciled-orphan"
        t.closed_at = timezone.now()
        t.save()
        self.assertTrue(grade_bot_trade(t))
        t.refresh_from_db()
        self.assertEqual(t.outcome, "stopped_out")
        self.assertEqual(sc.exit_of(t), "stop at breakeven")

    def test_anything_else_is_other_with_its_outcome(self):
        t = self.mk(exit_price="102", reason="x | reconciled-orphan")
        self.assertEqual(t.outcome, "manual_close")
        self.assertEqual(sc.exit_of(t), "other: manual_close")
        ungraded = self.mk(exit_price="102", grade=False)
        self.assertEqual(sc.exit_of(ungraded), "other: ungraded")


# ── the row keys ────────────────────────────────────────────────────────

class TheRowKeysTests(_Book):

    def test_policy_shadow_inferred_venue_and_window(self):
        lo, hi = _at(7, 10, 52), _at(7, 11, 7, 59)
        t = self.mk(exit_price="95", reason="x | reconciled-orphan",
                    meta={"exit_price_inferred": True,
                          "venue_closed_between": _window(lo, hi)})
        row = sc.row_of(t)
        self.assertEqual(row["exit"], "stop")
        self.assertEqual(row["policy"], "care")
        self.assertEqual(row["shadow_r"], t.realized_r)
        self.assertEqual(row["shadow_r"], -1.0)
        self.assertIs(row["inferred"], True)
        self.assertIs(row["at_venue"], True)
        self.assertEqual(row["venue_close_at"], (lo, hi))

        care_close = sc.row_of(self.mk(
            exit_price="103", reason="x | closed:SL",
            meta={"care_exit": "trail", "exit_policy": {"key": "be_only"}}))
        self.assertEqual(care_close["policy"], "be_only")
        self.assertIs(care_close["inferred"], False)
        self.assertIs(care_close["at_venue"], False)
        self.assertIsNone(care_close["venue_close_at"])

    def test_a_window_that_is_not_ours_is_not_read(self):
        for bad in (["2026-10-07T11:00:00", "2026-10-07T11:05:00"],   # naive
                    _window(_at(7, 12), _at(7, 11)),                   # reversed
                    ["x", "y"], ["2026-10-07T11:00:00+00:00"], "nope", None):
            with self.subTest(bad=bad):
                self.assertIsNone(sc.close_window({"venue_closed_between": bad}))

    def test_the_key_and_the_classes_are_pr50s(self):
        from bot_program import morgul, venue_exit
        self.assertEqual(sc.CLOSE_WINDOW_KEY, venue_exit.CLOSED_BETWEEN_KEY)
        self.assertEqual(sc.VENUE_SESSION_CLASSES,
                         morgul.VENUE_SESSION_CLASSES)
        # the list's lag the window's lower bound is widened by
        from bot_program.engine.etoro_client import EtoroTrader
        self.assertEqual(sc.LIST_LAG_S, EtoroTrader.PORTFOLIO_LAG_S)
        self.assertEqual(sc.LIST_LAG_S, 60)


class TheReconcileWritesItTests(ve.Base):
    """End to end on PR50's own reconcile: the NVDA #131 booking, read back
    by the scorecard."""

    def test_nvda_131_reads_as_the_mirrored_break_even_with_its_window(self):
        from bot_program.models import AssetBotTrade
        listed = self.now - timedelta(minutes=15)
        crossed_at = self.now - timedelta(minutes=7)
        t = self._nvda(venue_listed_at=ve._iso(listed),
                       venue_level_crossed={"level": "stop", "price": 238.03,
                                            "mark": 237.9,
                                            "at": ve._iso(crossed_at)},
                       venue_missing_at=ve._iso(crossed_at),
                       care={"soft_stop": 238.02671429, "venue_stop": 238.03,
                             "soft_why": "breakeven"},
                       # the mirror's accepted move, an hour before the
                       # listing (base._move_broker_stop's record)
                       stop_moves=[_move("238.03", "care breakeven",
                                         when=listed - timedelta(hours=1))])
        self._run(ve.EtoroTrader(state="closed"))
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        row = sc.row_of(AssetBotTrade.objects.get(pk=t.pk))
        self.assertEqual(row["exit"], "stop at breakeven")
        self.assertIs(row["inferred"], True)
        self.assertIs(row["at_venue"], True)
        self.assertEqual(row["venue_close_at"], (listed, crossed_at))
        self.assertIn(sc.session_side(listed, crossed_at),
                      ("outside", "inside", "spans"))


# ── the two lines ───────────────────────────────────────────────────────

class TheInferredLineTests(_Book):

    def test_the_inferred_count(self):
        self.mk(exit_price="95", reason="x | reconciled-orphan",
                meta={"exit_price_inferred": True})
        self.mk(exit_price="110", reason="x | reconciled-orphan",
                meta={"exit_price_inferred": True})
        self.mk(exit_price="103", reason="x | closed:SL",
                meta={"exit_price_inferred": False, "care_exit": "trail"})
        self.mk(exit_price="99", reason="x | closed:TIME")
        self.assertEqual(
            sc.inferred_line(sc.rows(days=30)),
            "inferred exit price: 2 of 4 (these R are estimates: no broker "
            "fill was read)")

    def test_an_etoro_close_we_sent_is_booked_at_the_mark_and_counted(self):
        """(2026-10-07, review) eToro's proven close answer carries no
        price (EtoroTrader.close_position: FILLED, the units, no avgPrice):
        resolve_exit_fill books the mark, sourced "mark", and sets no
        exit_price_inferred. Every care, hand, stop and time close the
        platform sends to eToro has this shape: its R is an estimate."""
        from types import SimpleNamespace

        from bot_program.pending_closes import resolve_exit_fill
        proven = {"orderId": "c1", "positionId": "P1", "status": "FILLED",
                  "executedQty": "10.0", "positionState": "closed"}
        fill = resolve_exit_fill(
            SimpleNamespace(id=1, pk=1, symbol="NVDA", qty=Decimal("10"),
                            entry_price=Decimal("100"), metadata={}),
            proven, mark=Decimal("103"))
        self.assertEqual(fill["metadata"]["exit_fill_source"], "mark")
        self.assertNotIn("exit_price_inferred", fill["metadata"])
        sent = self.mk(exit_price="103", reason="x | closed:SL",
                       meta={**fill["metadata"], "care_exit": "trail"})
        self.assertIs(sc.row_of(sent)["inferred"], True)
        # a fill the venue reported, and paper's modelled fill: not estimates
        broker = self.mk(exit_price="103", reason="x | closed:SL",
                         meta={"exit_fill_source": "broker",
                               "care_exit": "trail"})
        paper = self.mk(exit_price="103", reason="x | closed:SL", paper=True,
                        meta={"exit_fill_source": "paper",
                              "care_exit": "trail"})
        self.assertIs(sc.row_of(broker)["inferred"], False)
        self.assertIs(sc.row_of(paper)["inferred"], False)
        # the venue-level sources, even without the flag
        for src in ("venue_stop", "venue_target"):
            with self.subTest(src=src):
                t = self.mk(exit_price="95", reason="x | reconciled-orphan",
                            meta={"exit_fill_source": src})
                self.assertIs(sc.row_of(t)["inferred"], True)
        self.assertEqual(
            sc.inferred_line([sc.row_of(x) for x in (sent, broker, paper)]),
            "inferred exit price: 1 of 3 (these R are estimates: no broker "
            "fill was read)")


class TheDrainsMarkIsAnEstimateTests(ve.Base):
    """(2026-10-07, review) The drain's bookings at the mark, through
    pending_closes.retry_trade_close: no fill read, no exit_price_inferred,
    counted inferred all the same."""

    def _pending(self, t):
        t.status = "CLOSE_PENDING"
        t.save(update_fields=["status"])
        return t

    def _drain(self, t, venue):
        from unittest import mock

        from bot_program.pending_closes import retry_trade_close
        with mock.patch(ve.ROUTER, return_value=venue), mock.patch(ve.STAFF):
            self.assertTrue(retry_trade_close(t))
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        self.assertEqual(t.metadata["exit_fill_source"], "mark")
        self.assertNotIn("exit_price_inferred", t.metadata)
        row = sc.row_of(t)
        self.assertIs(row["inferred"], True)
        self.assertEqual(sc.inferred_line([row]),
                         "inferred exit price: 1 of 1 (these R are "
                         "estimates: no broker fill was read)")
        return t

    def test_a_proved_close_with_no_level_to_price_it_at(self):
        """eToro's order read says closed; the row's stop never rested at
        the venue (protected False): booked at the mark."""
        t = self._drain(self._pending(self._nvda(protected=False)),
                        ve.EtoroTrader(state="closed"))
        self.assertIn("RETRY_VENUE_PROVED_CLOSED", t.reason)

    def test_an_already_flat_book(self):
        """A venue that cannot prove a close no longer lists the position:
        RETRY_ALREADY_FLAT at the mark."""

        class _FlatBook:
            def get_positions(self):
                return []

            def ticker(self, symbol):
                return {"lastPrice": "99.5"}

        t = ve._trade(self.cfg, broker_order_id="OANDA-7", metadata={
            "initial_stop_loss": 98.0, "protected": True, "broker": "oanda",
            "protective_trade_id": "T7"})
        t = self._drain(self._pending(self._aged(t)), _FlatBook())
        self.assertIn("RETRY_ALREADY_FLAT", t.reason)
        self.assertEqual(t.exit_price, Decimal("99.5"))


class TheOutsideHoursTests(_Book):

    def _venue_close(self, window=None, **kw):
        meta = {"exit_price_inferred": True}
        if window is not None:
            meta["venue_closed_between"] = _window(*window)
        return self.mk(exit_price="95", reason="x | reconciled-orphan",
                       meta=meta, **kw)

    def test_outside_hours_counted_from_a_recorded_window(self):
        from bot_program import venue_exit

        class _Row:
            metadata = {venue_exit.LISTED_AT_KEY: _at(7, 10, 52).isoformat(),
                        venue_exit.MISSING_AT_KEY: _at(7, 11, 7, 59).isoformat()}
        # NVDA #131: 06:52-07:08 New York, a Wednesday — the extended session.
        # The window comes from PR50's own function, as the reconcile builds it.
        nvda = venue_exit.closed_between(_Row(), now=_at(7, 11, 15))
        self.assertEqual(nvda, (_at(7, 10, 52), _at(7, 11, 7, 59)))
        self._venue_close(nvda)
        self._venue_close((_at(7, 14, 40), _at(7, 14, 55)))   # 10:40 NY: in
        self._venue_close((_at(10, 14), _at(10, 15)))          # a Saturday
        # not counted: a forex venue close, a paper row, care's own close
        self._venue_close((_at(7, 2), _at(7, 3)), asset_class="forex",
                          symbol="EURUSD")
        self._venue_close((_at(7, 2), _at(7, 3)), paper=True)
        self.mk(exit_price="103", reason="x | closed:SL",
                meta={"care_exit": "trail"})
        line = sc.outside_hours_line(sc.rows(days=30))
        self.assertEqual(line, "outside 09:30-16:00 New York: 2 of 3")

    def test_the_list_keeps_a_closed_position_up_to_its_lag(self):
        """(2026-10-07, review) The window's lo is the last list read that
        showed the position, and eToro's list keeps a closed one up to ~60 s
        (LIST_LAG_S): the close may precede lo. A stop filled at 15:59:30
        New York, still listed by the 16:00:20 read, gone at 16:15 — and a
        pre-market close at 09:29:30 still listed at 09:30:05 — both span
        the edge. A window whose lo is past the lag stays outside."""
        self._venue_close((_at(7, 20, 0, 20), _at(7, 20, 15)))
        self._venue_close((_at(7, 13, 30, 5), _at(7, 13, 45)))
        self._venue_close((_at(7, 20, 1, 1), _at(7, 20, 15)))
        self.assertEqual(
            sc.outside_hours_line(sc.rows(days=30)),
            "outside 09:30-16:00 New York: 1 of 3 (2 window(s) span the "
            "session edge: either side)")

    def test_unmeasured_when_no_close_time_is_recorded(self):
        self._venue_close()
        self._venue_close(asset_class="etf", symbol="SPY")
        self.assertEqual(sc.outside_hours_line(sc.rows(days=30)), UNMEASURED)

    def test_a_window_across_the_open_and_a_row_without_one_are_named(self):
        self._venue_close((_at(7, 13), _at(7, 14)))     # 09:00-10:00 New York
        self._venue_close()
        self.assertEqual(
            sc.outside_hours_line(sc.rows(days=30)),
            "outside 09:30-16:00 New York: 0 of 1 (1 window(s) span the "
            "session edge: either side; 1 more unmeasured — the venue's "
            "close time is not recorded)")

    def test_no_live_stock_close_at_the_venue_says_so(self):
        self.mk(exit_price="103", reason="x | closed:SL",
                meta={"care_exit": "trail"})
        self.assertEqual(sc.outside_hours_line(sc.rows(days=30)),
                         "outside 09:30-16:00 New York: 0 of 0 (no live stock "
                         "or ETF row closed at the venue)")


class TheNewYorkClockTests(SimpleTestCase):

    def test_the_session_edges_on_both_sides_of_the_clock_change(self):
        cases = [
            # October, UTC-4: 09:30 New York is 13:30 UTC
            ((_at(7, 13, 29), _at(7, 13, 29, 59)), "outside"),
            ((_at(7, 13, 30), _at(7, 13, 31)), "inside"),
            ((_at(7, 19, 59), _at(7, 20, 0)), "inside"),      # 16:00 is in
            ((_at(7, 20, 0, 1), _at(7, 20, 5)), "outside"),
            ((_at(7, 19, 55), _at(7, 20, 5)), "spans"),
            # December, UTC-5: 09:30 New York is 14:30 UTC
            ((_at(2, 13, 31, month=12), _at(2, 14, 29, month=12)), "outside"),
            ((_at(2, 14, 31, month=12), _at(2, 14, 40, month=12)), "inside"),
            # Friday after the close to Monday before the open
            ((_at(9, 20, 30), _at(12, 13, 0)), "outside"),
            ((_at(9, 20, 30), _at(12, 13, 45)), "spans"),
            ((_at(1, 0), _at(20, 0)), "spans"),
        ]
        for (lo, hi), side in cases:
            with self.subTest(lo=lo, hi=hi):
                self.assertEqual(sc.session_side(lo, hi), side)


# ── the command ─────────────────────────────────────────────────────────

class TheCommandTests(_Book):

    def _out(self, *args):
        out = StringIO()
        call_command("scorecard", *args, stdout=out)
        return out.getvalue()

    def test_by_exit_prints_a_block_per_exit_and_the_two_lines(self):
        self.mk(exit_price="103.5", reason="x | closed:SL",
                meta={"care_exit": "trail"})
        self.mk(exit_price="100.1", reason="x | closed:SL",
                meta={"care_exit": "breakeven"})
        self.mk(exit_price="95", reason="x | reconciled-orphan",
                meta={"exit_price_inferred": True,
                      "venue_closed_between": _window(_at(7, 10, 52),
                                                      _at(7, 11, 7, 59))})
        text = self._out("--venue", "live", "--by", "exit")
        for title in ("── exit care: trail", "── exit care: breakeven",
                      "── exit stop"):
            self.assertIn(title, text)
        self.assertIn("  inferred exit price: 1 of 3 (these R are estimates",
                      text)
        self.assertIn("  outside 09:30-16:00 New York: 1 of 1", text)
        for money in ("$", "USD", "pnl"):
            self.assertNotIn(money, text)

    def test_the_unmeasured_words_reach_the_operator(self):
        self.mk(exit_price="95", reason="x | reconciled-orphan")
        self.assertIn(UNMEASURED, self._out("--by", "exit"))

    def test_the_two_lines_only_under_by_exit(self):
        self.mk(exit_price="95", reason="x | reconciled-orphan")
        text = self._out()
        self.assertNotIn("inferred exit price", text)
        self.assertNotIn("outside regular hours", text)

    def test_no_by_policy_before_an_exit_policy_exists(self):
        with self.assertRaises(CommandError):
            self._out("--by", "policy")
