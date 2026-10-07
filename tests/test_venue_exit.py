"""THE VENUE'S OWN WORD BEFORE A MISS IS BOOKED, AND THE PRICE OF A CLOSE
NOBODY SAW (2026-10-07, PR50; bot_program/venue_exit.py).

The four real cases of 2026-10-07, all live eToro rows the 15-minute
reconcile found missing from /portfolio and booked "priced from the last
mark":
  - NVDA #131 (BUY 6 @ 237.60, venue stop 238.03 after care's break-even,
    initial 233.40): the tick saw 237.9 cross the stop at 11:07:59 and no
    position in the list; booked at 238.16. Now: 238.03, `crossed`, the
    window [11:00:0x, 11:07:59];
  - AMZN #140 (braked, unmanaged; BUY 1 @ 257.39, stop 254.18): booked at
    254.48, -0.91R. Now: the stop, `nearest`, -1.00R, said an estimate;
  - PG #138 (a short, SELL @ 147.95, stop 149.779125): booked at 148.41,
    about -0.25R. Now: the stop, `nearest` (0.75R away), -1.00R;
  - XAGUSD #134 (BUY @ 61.29, stop 59.43): the 59.21 mark was already
    beyond the stop. Now: the stop, `mark_beyond`.

Pinned here:
  A. the guard, through reconcile_user: "closed" books, "open" books
     nothing and tells staff once (no money figure), no answer counts the
     ask and books only after the hour AND four asks in one unbroken run;
     a listing by the row's own id stamps the read and forgets the miss;
     no order id, a non-eToro adapter, a MagicMock: today's rule;
  B. the price: the crossing, care's last mark, the 1h bars, the mark
     beyond, the nearest level; never for a close of ours, a stale
     crossing, a moved level or an unproven booking;
  C. the drain and the kill switch;
  D. the stamps never fire on a row they do not concern and never raise;
  E. the words; F. the wiring and the constants.

Tests 36, 39 and 41 of the build spec (the tick's crossing hook, the stop
move's "when") live in tests/test_venue_exit_hooks.py beside base.py.

Run with:  python manage.py test tests.test_venue_exit
"""
import inspect
import re
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from tests.test_exit_truth import _cfg, _trade, _user

ROUTER = "bot_program.engine.broker_router.client_for_symbol"
STAFF = "bot_program.notifications.notify_staff"
NVDA_OID = "1601464870"


class EtoroTrader:
    """Named like the adapter: adapter_key and _state_key read the class
    name. One live book; `held` is [(symbol, position_id or None)]."""
    PORTFOLIO_LAG_S = 60

    def __init__(self, held=(), state="closed", last="238.16"):
        self.held = list(held)
        self.state = state
        self.last = last
        self.proofs, self.closes, self.read_times = [], [], []

    def _world(self):
        return "live"

    def instrument_id(self, symbol):
        return 1001

    def get_positions(self):
        self.read_times.append(timezone.now())
        out = []
        for symbol, pid in self.held:
            p = {"symbol": symbol, "qty": "6", "side": "BUY"}
            if pid:
                p["position_id"] = pid
            out.append(p)
        return out

    def ticker(self, symbol):
        return {"lastPrice": self.last}

    def close_needs_position_id(self):
        return True

    def position_state(self, order_id, **kw):
        self.proofs.append((order_id, kw))
        if isinstance(self.state, Exception):
            raise self.state
        return self.state

    def close_position(self, position_id, symbol, units=None, *,
                       open_order_id=""):
        self.closes.append((position_id, symbol, units, open_order_id))
        return {"orderId": "c1", "positionId": position_id,
                "status": "PENDING", "executedQty": "0.0",
                "openOrderId": open_order_id, "positionState": None}

    def market_order(self, *a, **k):
        raise AssertionError("never on an eToro close")

    def cancel_order(self, oid):
        return False


class OANDATrader:
    """Another venue (adapter_key "oanda"): never asked for the word."""

    def __init__(self, last="99.5"):
        self.last = last
        self.proofs = []

    def get_positions(self):
        return []

    def ticker(self, symbol):
        return {"lastPrice": self.last}

    def position_state(self, order_id, **kw):
        self.proofs.append(order_id)
        return "closed"


def _iso(dt):
    return dt.isoformat()


class Base(TestCase):
    def setUp(self):
        self.user = _user("ve_u")
        self.cfg = _cfg(self.user)
        self.now = timezone.now()

    def _aged(self, t, age=timedelta(days=1)):
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(pk=t.pk).update(opened_at=self.now - age)
        t.refresh_from_db()
        return t

    def _nvda(self, age=timedelta(days=1), **meta):
        m = {"broker": "etoro", "broker_env": "live", "protected": True,
             "protective_trade_id": "P131", "initial_stop_loss": 233.40,
             "care": {"soft_stop": 238.02671429, "venue_stop": 238.03}}
        m.update(meta)
        t = _trade(self.cfg, symbol="NVDA", qty=Decimal("6"),
                   entry_price=Decimal("237.60"), stop_loss=Decimal("238.03"),
                   take_profit=Decimal("245.50"),
                   broker_order_id=NVDA_OID, metadata=m)
        return self._aged(t, age)

    def _row(self, symbol, side, qty, entry, stop, tp, oid, cfg=None,
             **meta):
        m = {"broker": "etoro", "broker_env": "live", "protected": True,
             "protective_trade_id": "P" + oid,
             "initial_stop_loss": float(stop)}
        m.update(meta)
        t = _trade(cfg or self.cfg, symbol=symbol, side=side,
                   qty=Decimal(qty), entry_price=Decimal(entry),
                   stop_loss=Decimal(stop), take_profit=Decimal(tp),
                   broker_order_id=oid, metadata=m)
        return self._aged(t)

    def _amzn(self, **meta):
        return self._row("AMZN", "BUY", "1", "257.39", "254.18", "263.81",
                         "1605558483", **meta)

    def _listed(self, minutes=15):
        return _iso(self.now - timedelta(minutes=minutes))

    def _run(self, venue):
        from bot_program.reconcile_asset import reconcile_user
        with mock.patch(ROUTER, return_value=venue), \
                mock.patch(STAFF) as staff:
            out = reconcile_user(self.user)
        return out, staff

    def _bar(self, symbol, at, low, high):
        from instruments.models import Instrument
        from market_data.models import PriceData
        inst, _ = Instrument.objects.get_or_create(
            symbol=symbol, defaults={"name": symbol, "asset_class": "stock"})
        PriceData.objects.create(instrument=inst, timeframe="1h",
                                 timestamp=at, open=256, high=high, low=low,
                                 close=255, source="etoro")


# ── A. the guard, through reconcile_user ────────────────────────────────

class TheGuardTests(Base):

    def test_closed_is_booked_and_priced_at_the_crossed_stop_with_its_window(self):
        listed = self.now - timedelta(minutes=15)
        crossed_at = self.now - timedelta(minutes=7)
        t = self._nvda(venue_listed_at=_iso(listed),
                       venue_level_crossed={"level": "stop", "price": 238.03,
                                            "mark": 237.9,
                                            "at": _iso(crossed_at)},
                       venue_missing_at=_iso(crossed_at))
        venue = EtoroTrader(state="closed")
        out, staff = self._run(venue)
        t.refresh_from_db()
        self.assertEqual(out["closed_as_orphan"], 1, out)
        self.assertEqual(t.status, "CLOSED")
        self.assertEqual(t.exit_price, Decimal("238.03"))
        self.assertEqual(t.pnl, Decimal("2.58"))
        self.assertEqual(t.outcome, "stopped_out")
        self.assertIn("reconciled-orphan", t.reason)
        self.assertEqual(t.metadata["exit_fill_source"], "venue_stop")
        self.assertTrue(t.metadata["exit_price_inferred"])
        basis = t.metadata["exit_priced_at"]
        self.assertEqual((basis["level"], basis["evidence"], basis["seen"]),
                         ("stop", "crossed", 237.9))
        self.assertEqual(t.metadata["venue_closed_between"],
                         [_iso(listed), _iso(crossed_at)])
        self.assertEqual(venue.proofs,
                         [(NVDA_OID, {"attempts": 1, "delay": 0.0})])
        self.assertEqual(venue.closes, [])
        staff.assert_not_called()

    def test_open_books_nothing_and_alerts_once(self):
        from bot_program.manual_close import CLAIM_KEY
        t = self._nvda()
        venue = EtoroTrader(state="open")
        out, staff = self._run(venue)
        out2, staff2 = self._run(venue)
        t.refresh_from_db()
        self.assertEqual(t.status, "OPEN")
        self.assertIsNone(t.exit_price)
        self.assertEqual(out["broker_unavailable"], 1)
        self.assertEqual(out["venue_says_open"], 1)
        self.assertEqual(out["closed_as_orphan"], 0)
        self.assertEqual(out2["venue_says_open"], 1)
        self.assertEqual(staff.call_count, 1)
        self.assertEqual(staff2.call_count, 0)
        self.assertNotIn(CLAIM_KEY, t.metadata)
        self.assertIn("venue_said_open_at", t.metadata)
        self.assertIn("venue_listing_missed_alerted_at", t.metadata)
        self.assertEqual(len(venue.proofs), 2)

    def test_the_open_alert_carries_no_money_figure(self):
        self._nvda()
        _out, staff = self._run(EtoroTrader(state="open"))
        kw = staff.call_args.kwargs
        text = kw["title"] + " " + kw["body"]
        for money in ("USD", "$", "237.6", "238.03", "238.16", "233.4",
                      "245.5"):
            self.assertNotIn(money, text)
        self.assertIsNone(re.search(r"\d+\.\d+", text), text)
        self.assertIn("NVDA", kw["title"])
        self.assertIn("OPEN", kw["body"])

    def test_no_answer_waits_without_an_error_and_counts(self):
        t = self._nvda()
        out, staff = self._run(EtoroTrader(state=None))
        t.refresh_from_db()
        self.assertEqual(t.status, "OPEN")
        self.assertEqual(out["errors"], 0, out)
        self.assertEqual(out["venue_unanswered"], 1)
        self.assertEqual(out["broker_unavailable"], 1)
        self.assertEqual(t.metadata["venue_miss"]["asks"], 1)
        out, _ = self._run(EtoroTrader(state=RuntimeError("429")))
        t.refresh_from_db()
        self.assertEqual(t.status, "OPEN")
        self.assertEqual(out["errors"], 0, out)
        self.assertEqual(t.metadata["venue_miss"]["asks"], 2)
        staff.assert_not_called()

    def test_after_the_hour_it_books_as_before_and_says_so(self):
        t = self._nvda(venue_miss={
            "since": _iso(self.now - timedelta(minutes=56)), "asks": 4,
            "last_at": _iso(self.now - timedelta(minutes=14))})
        out, _ = self._run(EtoroTrader(state=None))
        t.refresh_from_db()
        self.assertEqual(out["closed_as_orphan"], 1, out)
        self.assertEqual(t.status, "CLOSED")
        self.assertIn("reconciled-orphan | venue-unanswered", t.reason)
        self.assertIn("did not answer 5 asks over 56 minutes",
                      t.metadata["venue_unproven_close"])
        self.assertEqual(t.exit_price, Decimal("238.16"))
        self.assertEqual(t.metadata["exit_fill_source"], "mark")
        self.assertNotIn("venue_closed_between", t.metadata)

    def test_the_hour_needs_both_the_time_and_the_asks(self):
        from bot_program.models import AssetBotTrade
        t = self._nvda()
        for since, asks in ((56, 2), (10, 9)):
            meta = dict(t.metadata)
            meta["venue_miss"] = {
                "since": _iso(self.now - timedelta(minutes=since)),
                "asks": asks,
                "last_at": _iso(self.now - timedelta(minutes=5))}
            AssetBotTrade.objects.filter(pk=t.pk).update(metadata=meta)
            out, _ = self._run(EtoroTrader(state=None))
            t.refresh_from_db()
            self.assertEqual(t.status, "OPEN", (since, asks))
            self.assertEqual(out["venue_unanswered"], 1)
            self.assertEqual(t.metadata["venue_miss"]["asks"], asks + 1)

    def test_a_stale_counter_restarts_instead_of_booking(self):
        t = self._nvda(venue_miss={
            "since": _iso(self.now - timedelta(hours=5)), "asks": 3,
            "last_at": _iso(self.now - timedelta(hours=4))})
        self._run(EtoroTrader(state=None))
        t.refresh_from_db()
        self.assertEqual(t.status, "OPEN")
        self.assertEqual(t.metadata["venue_miss"]["asks"], 1)
        self.assertGreater(t.metadata["venue_miss"]["since"],
                           _iso(self.now - timedelta(minutes=1)))

    def test_an_open_answer_restarts_the_hour(self):
        from bot_program.models import AssetBotTrade
        t = self._nvda(venue_miss={
            "since": _iso(self.now - timedelta(minutes=50)), "asks": 3,
            "last_at": _iso(self.now - timedelta(minutes=5))})
        self._run(EtoroTrader(state="open"))
        t.refresh_from_db()
        self.assertNotIn("venue_miss", t.metadata)
        self.assertIn("venue_said_open_at", t.metadata)
        # an "open" answer that came after the run began also ends it
        meta = dict(t.metadata)
        meta["venue_miss"] = {
            "since": _iso(self.now - timedelta(minutes=58)), "asks": 4,
            "last_at": _iso(self.now - timedelta(minutes=5))}
        meta["venue_said_open_at"] = _iso(self.now - timedelta(minutes=20))
        AssetBotTrade.objects.filter(pk=t.pk).update(metadata=meta)
        self._run(EtoroTrader(state=None))
        t.refresh_from_db()
        self.assertEqual(t.status, "OPEN")
        self.assertEqual(t.metadata["venue_miss"]["asks"], 1)

    def test_a_listed_row_is_stamped_at_the_read_and_its_miss_forgotten(self):
        from bot_program.venue_exit import OPEN_ALERTED_KEY
        t = self._nvda(venue_miss={"since": _iso(self.now), "asks": 2,
                                   "last_at": _iso(self.now)},
                       venue_missing_at=_iso(self.now),
                       **{OPEN_ALERTED_KEY: _iso(self.now)})
        before = timezone.now()
        venue = EtoroTrader(held=[("NVDA", "P131")])
        out, staff = self._run(venue)
        t.refresh_from_db()
        self.assertEqual(t.status, "OPEN")
        self.assertEqual(out["closed_as_orphan"], 0)
        listed = datetime.fromisoformat(t.metadata["venue_listed_at"])
        # the moment the book was READ (before get_positions answered),
        # not the moment the stamp was written
        self.assertTrue(before <= listed <= venue.read_times[0],
                        (before, listed, venue.read_times))
        for key in ("venue_miss", "venue_missing_at", OPEN_ALERTED_KEY):
            self.assertNotIn(key, t.metadata)
        self.assertEqual(venue.proofs, [])
        staff.assert_not_called()

    def test_a_row_listed_only_by_symbol_is_not_stamped(self):
        t = self._nvda()
        venue = EtoroTrader(held=[("NVDA", None)])
        self._run(venue)
        t.refresh_from_db()
        self.assertEqual(t.status, "OPEN")
        self.assertNotIn("venue_listed_at", t.metadata)
        self.assertEqual(venue.proofs, [])

    def _todays_rule(self, t, venue, last="238.16"):
        self._run(venue)
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        self.assertEqual(t.exit_price, Decimal(last))
        self.assertEqual(t.metadata["exit_fill_source"], "mark")
        for key in ("venue_closed_between", "exit_priced_at", "venue_miss",
                    "venue_unproven_close"):
            self.assertNotIn(key, t.metadata)
        self.assertNotIn("venue-unanswered", t.reason)

    def test_no_order_id_magicmock_and_cannot_ask_keep_todays_rule(self):
        from tests.test_reconcile_all_day import EtoroTrader as NoProofEtoro
        # no order id: the word cannot be asked
        t = self._nvda(venue_listed_at=self._listed())
        t.broker_order_id = ""
        t.save(update_fields=["broker_order_id"])
        venue = EtoroTrader(state="open")
        self._todays_rule(t, venue)
        self.assertEqual(venue.proofs, [])
        # an eToro-named client without position_state
        t = self._nvda(venue_listed_at=self._listed())
        self._todays_rule(t, NoProofEtoro(), last="101")
        # a MagicMock answers "" for the adapter and is never asked
        t = self._nvda(venue_listed_at=self._listed())
        client = mock.MagicMock()
        client.get_positions.return_value = []
        client.ticker.return_value = {"lastPrice": "238.16"}
        client.closing_fill = None
        self._todays_rule(t, client)
        client.position_state.assert_not_called()

    def test_the_real_adapter_is_asked_by_the_open_order_id(self):
        from bot_program import venue_exit
        from tests.test_etoro_client import _client, _measured_lookup
        t = self._nvda()
        client, fake = _client(
            [("GET", "orders:lookup", 200,
              _measured_lookup("closed", order_id=int(NVDA_OID)))],
            env="live")
        self.assertTrue(venue_exit.can_ask(t, client))
        self.assertEqual(venue_exit.word_on_miss(t, client), ("closed", ""))
        lookups = [c for c in fake.calls if "orders:lookup" in c[1]]
        self.assertEqual(len(lookups), 1)
        self.assertEqual(lookups[0][0], "GET")
        self.assertEqual(lookups[0][2]["params"], {"orderId": NVDA_OID})

    def test_the_new_counters_reach_reconcile_all_users(self):
        from bot_program.reconcile_asset import reconcile_all_users
        self._nvda()

        def run(venue):
            with mock.patch(ROUTER, return_value=venue), \
                    mock.patch(STAFF), \
                    mock.patch("bot_program.reconcile_asset."
                               "reconcile_unknown_positions",
                               return_value={}):
                return reconcile_all_users()
        totals = run(EtoroTrader(state=None))
        self.assertEqual(totals["venue_unanswered"], 1, totals)
        self.assertNotIn("venue_says_open", totals)
        totals = run(EtoroTrader(state="open"))
        self.assertEqual(totals["venue_says_open"], 1, totals)
        self.assertNotIn("venue_unanswered", totals)
        totals = run(EtoroTrader(held=[("NVDA", "P131")]))
        self.assertNotIn("venue_says_open", totals)
        self.assertNotIn("venue_unanswered", totals)


# ── B. the price ────────────────────────────────────────────────────────

class ThePriceTests(Base):

    def test_amzn_140_nearest_stop_is_an_estimate(self):
        from dashboard.position_summary import ending_words
        t = self._amzn(venue_listed_at=self._listed())
        self._run(EtoroTrader(state="closed", last="254.48"))
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        self.assertEqual(t.exit_price, Decimal("254.18"))
        self.assertEqual(t.pnl, Decimal("-3.21"))
        self.assertEqual(t.metadata["exit_priced_at"]["evidence"], "nearest")
        self.assertEqual(t.metadata["exit_priced_at"]["seen"], 254.48)
        self.assertEqual(t.metadata["exit_fill_source"], "venue_stop")
        self.assertTrue(t.metadata["exit_price_inferred"])
        self.assertAlmostEqual(t.realized_r, -1.0, places=6)
        self.assertEqual(ending_words(t), "Closed at the broker, most likely "
                                          "by its stop (an estimate)")

    def test_pg_138_short_nearest_stop_at_three_quarters_of_r(self):
        t = self._row("PG", "SELL", "1", "147.95", "149.779125", "144.29",
                      "1604803372", venue_listed_at=self._listed())
        self._run(EtoroTrader(state="closed", last="148.41"))
        t.refresh_from_db()
        self.assertEqual(t.exit_price, Decimal("149.779125"))
        self.assertEqual(t.metadata["exit_priced_at"]["evidence"], "nearest")
        self.assertEqual(t.outcome, "stopped_out")
        self.assertAlmostEqual(t.realized_r, -1.0, places=6)

    def test_xagusd_134_mark_beyond_the_stop(self):
        commodity = _cfg(self.user, asset_class="commodity", name="CMD")
        t = self._row("XAGUSD", "BUY", "16.3109", "61.29", "59.43", "65.0",
                      "1600000134", cfg=commodity,
                      venue_listed_at=self._listed())
        self._run(EtoroTrader(state="closed", last="59.21"))
        t.refresh_from_db()
        self.assertEqual(t.exit_price, Decimal("59.43"))
        self.assertEqual(t.metadata["exit_priced_at"]["evidence"],
                         "mark_beyond")
        self.assertEqual(t.metadata["exit_priced_at"]["seen"], 59.21)
        self.assertEqual(t.outcome, "stopped_out")
        self.assertAlmostEqual(t.realized_r, -1.0, places=6)

    def test_a_mark_far_from_both_levels_keeps_the_mark(self):
        t = self._amzn(venue_listed_at=self._listed())
        self._run(EtoroTrader(state="closed", last="259.0"))
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        self.assertEqual(t.exit_price, Decimal("259.0"))
        self.assertEqual(t.metadata["exit_fill_source"], "mark")
        self.assertNotIn("exit_priced_at", t.metadata)
        # the venue said closed: the window is written all the same
        self.assertIn("venue_closed_between", t.metadata)

    def test_a_mark_near_the_target_within_half_r_prices_it_at_the_target(self):
        from dashboard.position_summary import ending_words
        # R = 3.21; the target 263.81 is 1.31 (0.41R) from 262.5
        t = self._amzn(venue_listed_at=self._listed())
        self._run(EtoroTrader(state="closed", last="262.5"))
        t.refresh_from_db()
        self.assertEqual(t.exit_price, Decimal("263.81"))
        self.assertEqual(t.metadata["exit_priced_at"]["level"], "target")
        self.assertEqual(t.metadata["exit_priced_at"]["evidence"], "nearest")
        self.assertEqual(t.metadata["exit_fill_source"], "venue_target")
        self.assertEqual(t.outcome, "hit_target")
        self.assertEqual(ending_words(t), "Closed at the broker, most likely "
                                          "at its target (an estimate)")
        # 0.6R from the target: the mark stands
        t = self._amzn(venue_listed_at=self._listed())
        self._run(EtoroTrader(state="closed", last="261.88"))
        t.refresh_from_db()
        self.assertEqual(t.exit_price, Decimal("261.88"))
        self.assertEqual(t.metadata["exit_fill_source"], "mark")

    def test_an_hour_aligned_bar_through_the_stop_prices_it(self):
        hour = self.now.replace(minute=0, second=0, microsecond=0)
        t = self._amzn(venue_listed_at=_iso(hour + timedelta(seconds=3)))
        self._bar("AMZN", hour, low=254.0, high=256.5)
        self._run(EtoroTrader(state="closed", last="258.9"))
        t.refresh_from_db()
        self.assertEqual(t.exit_price, Decimal("254.18"))
        self.assertEqual(t.metadata["exit_priced_at"]["evidence"], "bars")
        self.assertEqual(t.metadata["exit_priced_at"]["seen"], 254.0)

    def test_a_bar_that_opened_before_the_listing_is_not_evidence(self):
        hour = self.now.replace(minute=0, second=0, microsecond=0)
        t = self._amzn(venue_listed_at=_iso(hour + timedelta(minutes=30)))
        self._bar("AMZN", hour, low=254.0, high=256.5)
        self._run(EtoroTrader(state="closed", last="258.9"))
        t.refresh_from_db()
        self.assertEqual(t.exit_price, Decimal("258.9"))
        self.assertEqual(t.metadata["exit_fill_source"], "mark")
        self.assertNotIn("exit_priced_at", t.metadata)

    def test_one_bar_through_both_levels_is_priced_at_the_stop(self):
        hour = self.now.replace(minute=0, second=0, microsecond=0)
        t = self._amzn(venue_listed_at=_iso(hour + timedelta(seconds=3)))
        self._bar("AMZN", hour, low=254.0, high=264.0)
        self._run(EtoroTrader(state="closed", last="258.9"))
        t.refresh_from_db()
        self.assertEqual(t.exit_price, Decimal("254.18"))
        self.assertEqual(t.metadata["exit_priced_at"]["level"], "stop")
        self.assertEqual(t.metadata["exit_priced_at"]["evidence"], "bars")

    def test_a_close_of_ours_is_never_priced_at_a_level(self):
        from bot_program.pending_closes import (CLOSE_FILLS_KEY,
                                                CLOSE_IN_DOUBT_KEY,
                                                CLOSE_SENT_AT_KEY)
        from bot_program.venue_exit import estimate
        crossing = {"level": "stop", "price": 254.18, "mark": 254.0,
                    "at": self._listed(5)}
        for key, val in ((CLOSE_SENT_AT_KEY, _iso(self.now)),
                         (CLOSE_FILLS_KEY, [{"qty": "1"}]),
                         (CLOSE_IN_DOUBT_KEY, {"at": "x"})):
            t = self._amzn(venue_listed_at=self._listed(),
                           venue_level_crossed=crossing, **{key: val})
            self.assertIsNone(estimate(t, mark=254.3), key)
        # the control: the same row without a close of ours is priced
        t = self._amzn(venue_listed_at=self._listed(),
                       venue_level_crossed=crossing)
        self.assertEqual(estimate(t, mark=254.3)["evidence"], "crossed")

    def test_a_crossing_before_the_last_listing_is_not_evidence(self):
        from bot_program.venue_exit import estimate
        t = self._nvda(venue_listed_at=self._listed(10),
                       venue_level_crossed={"level": "stop", "price": 238.03,
                                            "mark": 237.9,
                                            "at": self._listed(20)})
        self.assertIsNone(estimate(t, mark=None))
        # the mark 238.16 is 0.03R from the stop: priced, but as nearest
        self.assertEqual(estimate(t, mark=238.16)["evidence"], "nearest")

    def test_a_crossing_at_a_level_since_moved_is_not_evidence(self):
        from bot_program.venue_exit import estimate
        crossing = {"level": "stop", "price": 238.03, "mark": 237.9,
                    "at": self._listed(20)}
        t = self._nvda(venue_listed_at=self._listed(30),
                       venue_level_crossed=crossing,
                       stop_moves=[{"to": "238.03", "asked": "238.03",
                                    "at": "241.73",
                                    "why": "breakeven:broker",
                                    "when": self._listed(10)}])
        self.assertIsNone(estimate(t, mark=None))
        # a crossing of the OLD level is not one of the level held now
        t = self._nvda(venue_listed_at=self._listed(30),
                       venue_level_crossed=dict(crossing, price=236.0,
                                                at=self._listed(5)))
        self.assertIsNone(estimate(t, mark=None))
        # the control: the same crossing, level unmoved, is evidence
        t = self._nvda(venue_listed_at=self._listed(30),
                       venue_level_crossed=crossing)
        self.assertEqual(estimate(t, mark=None)["evidence"], "crossed")

    def test_the_stop_eToro_rewrote_at_the_fill_is_the_level(self):
        from bot_program.venue_exit import venue_levels
        t = self._nvda(stop_rewritten_by_venue={"sent": 238.03, "held": 237.0})
        self.assertEqual(venue_levels(t), {"stop": 237.0, "target": 245.5})
        t = self._nvda(stop_rewritten_by_venue={"held": 237.0},
                       stop_moves=[{"to": "238.03", "when": self._listed(5)}])
        self.assertEqual(venue_levels(t)["stop"], 238.03)
        t = self._nvda(stop_rewritten_by_venue={"held": 0.0001})
        self.assertEqual(venue_levels(t), {"target": 245.5})
        t = self._nvda(venue_stop_unread=True)
        self.assertNotIn("stop", venue_levels(t))
        t = self._nvda(protected=False)
        self.assertEqual(venue_levels(t), {})

    def test_an_unproven_booking_is_never_priced_at_a_level(self):
        t = self._nvda(venue_listed_at=self._listed(70),
                       venue_level_crossed={"level": "stop", "price": 238.03,
                                            "mark": 237.9,
                                            "at": self._listed(65)},
                       venue_miss={
                           "since": self._listed(56), "asks": 4,
                           "last_at": self._listed(14)})
        self._run(EtoroTrader(state=None))
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        self.assertEqual(t.exit_price, Decimal("238.16"))
        self.assertEqual(t.metadata["exit_fill_source"], "mark")
        self.assertNotIn("exit_priced_at", t.metadata)
        self.assertNotIn("venue_closed_between", t.metadata)
        self.assertTrue(t.metadata["venue_unproven_close"])

    def test_resolve_exit_fill_keeps_its_default_source(self):
        from bot_program.pending_closes import (EXIT_SOURCE_MARK,
                                                resolve_exit_fill)
        sig = inspect.signature(resolve_exit_fill)
        self.assertEqual(sig.parameters["mark_source"].default,
                         EXIT_SOURCE_MARK)
        t = _trade(self.cfg)
        fill = resolve_exit_fill(t, None, mark=Decimal("99"))
        self.assertEqual(fill["source"], "mark")
        self.assertEqual(fill["metadata"]["exit_fill_source"], "mark")
        self.assertEqual(fill["price"], Decimal("99"))
        fill = resolve_exit_fill(t, None, mark=Decimal("98"),
                                 mark_source="venue_stop")
        self.assertEqual(fill["source"], "venue_stop")
        # one slice booked at a mark makes the blend a mark
        t.metadata = dict(t.metadata, close_fills=[
            {"qty": "4", "price": "99", "source": "mark"}])
        fill = resolve_exit_fill(t, None, mark=Decimal("98"),
                                 mark_source="venue_stop")
        self.assertEqual(fill["source"], "mark")

    def test_a_stop_move_on_another_venue_changes_no_words(self):
        from bot_program.notifications import fill_close_message
        t = _trade(self.cfg, broker_order_id="OANDA-7", metadata={
            "initial_stop_loss": 98.0, "protected": True, "broker": "oanda",
            "protective_trade_id": "T7",
            "stop_moves": [{"to": "99", "at": "101", "why": "trail:broker",
                            "when": self._listed(5)}]})
        self._aged(t)
        venue = OANDATrader()
        self._run(venue)
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        self.assertEqual(venue.proofs, [])
        self.assertEqual(t.exit_price, Decimal("99.5"))
        self.assertEqual(t.metadata["exit_fill_source"], "mark")
        self.assertNotIn("venue_closed_between", t.metadata)
        self.assertNotIn("exit_priced_at", t.metadata)
        msg = fill_close_message(asset_class="stock", symbol="AAPL",
                                 side="BUY", qty=t.qty,
                                 exit_price=t.exit_price, pnl=t.pnl, trade=t)
        self.assertIn("Priced from the last mark, not from a broker fill.",
                      msg["lines"])
        self.assertTrue(msg["details"][-1].endswith(
            "— the broker had closed it before; the exact moment is not "
            "readable"), msg["details"])


# ── C. the drain and the kill switch ────────────────────────────────────

class TheDrainAndSwitchTests(Base):

    def _pending(self, **meta):
        t = self._nvda(**meta)
        t.status = "CLOSE_PENDING"
        t.save(update_fields=["status"])
        return t

    def test_the_drain_waits_on_an_unanswered_flat_book(self):
        from bot_program.pending_closes import retry_trade_close
        t = self._pending()
        venue = EtoroTrader(state=None)
        with mock.patch(ROUTER, return_value=venue):
            self.assertFalse(retry_trade_close(t))
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSE_PENDING")
        self.assertIsNone(t.exit_price)
        self.assertEqual(t.metadata["venue_miss"]["asks"], 1)
        self.assertFalse(t.metadata.get("close_retry_attempts"))
        self.assertEqual(venue.closes, [])

    def test_the_drain_books_after_the_hour_and_says_recorded(self):
        from bot_program.notifications import fill_close_message
        from bot_program.pending_closes import retry_trade_close
        t = self._pending(venue_miss={
            "since": self._listed(56), "asks": 9,
            "last_at": self._listed(5)})
        venue = EtoroTrader(state=None)
        with mock.patch(ROUTER, return_value=venue):
            self.assertTrue(retry_trade_close(t))
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        self.assertIn("RETRY_ALREADY_FLAT", t.reason)
        self.assertTrue(t.metadata["venue_unproven_close"])
        self.assertEqual(venue.closes, [])
        msg = fill_close_message(asset_class="stock", symbol="NVDA",
                                 side="BUY", qty=t.qty, exit_price=t.exit_price,
                                 pnl=t.pnl, trade=t)
        self.assertTrue(any(d.startswith("Recorded closed:")
                            for d in msg["details"]), msg["details"])
        self.assertNotIn(" after ", msg["summary"])
        self.assertTrue(any(line.startswith("eToro never confirmed")
                            for line in msg["lines"]), msg["lines"])
        # (2026-10-07, review) the drain's hour-late booking is a mark read
        # an hour after the list went flat: flagged inferred like the
        # reconcile's unproven twin, so the money and the R say "about"
        self.assertTrue(t.metadata["exit_price_inferred"])
        self.assertEqual(t.metadata["exit_fill_source"], "mark")
        self.assertIn("about", msg["title"])
        self.assertIn("Priced from the last mark, not from a broker fill.",
                      msg["lines"])

    def test_the_drain_tells_staff_once_when_the_venue_says_open_beside_a_flat_list(self):
        from bot_program.pending_closes import retry_trade_close
        t = self._pending()
        self._aged(t, timedelta(seconds=600))
        venue = EtoroTrader(state="open")
        with mock.patch(ROUTER, return_value=venue), \
                mock.patch(STAFF) as staff:
            self.assertFalse(retry_trade_close(t))
            t.refresh_from_db()
            self.assertFalse(retry_trade_close(t))
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSE_PENDING")
        self.assertEqual(staff.call_count, 1)
        self.assertEqual(venue.closes, [])
        # inside the venue's own lag: a list that has not caught up, never
        # an alert
        t2 = self._pending()
        self._aged(t2, timedelta(seconds=2))
        with mock.patch(ROUTER, return_value=venue), \
                mock.patch(STAFF) as staff:
            self.assertFalse(retry_trade_close(t2))
        staff.assert_not_called()
        t2.refresh_from_db()
        self.assertNotIn("venue_said_open_at", t2.metadata)

    def test_the_drain_prices_a_proved_close_at_the_stop(self):
        from bot_program.pending_closes import retry_trade_close
        t = self._pending(
            venue_listed_at=self._listed(15),
            venue_level_crossed={"level": "stop", "price": 238.03,
                                 "mark": 237.9, "at": self._listed(7)})
        venue = EtoroTrader(state="closed")
        with mock.patch(ROUTER, return_value=venue):
            self.assertTrue(retry_trade_close(t))
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        self.assertIn("RETRY_VENUE_PROVED_CLOSED", t.reason)
        self.assertEqual(t.exit_price, Decimal("238.03"))
        self.assertEqual(t.metadata["exit_fill_source"], "venue_stop")
        self.assertTrue(t.metadata["exit_price_inferred"])
        self.assertEqual(t.metadata["exit_priced_at"]["evidence"], "crossed")
        self.assertEqual(venue.closes, [])

    def test_the_kill_switch_sends_the_close_on_an_unproven_flat_list(self):
        from bot_program.engine.kill_switch import _close_asset_trade
        t = self._nvda()
        venue = EtoroTrader(state=None)
        with mock.patch(ROUTER, return_value=venue), \
                self.assertRaises(RuntimeError):
            _close_asset_trade(t, timezone.now())
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSE_PENDING")
        self.assertEqual(len(venue.closes), 1)
        self.assertEqual(venue.closes[0][0], "P131")
        self.assertIsNone(t.exit_price)

    def test_the_kill_switch_still_books_a_flat_list_the_venue_proved(self):
        from bot_program.engine.kill_switch import _close_asset_trade
        t = self._nvda()
        venue = EtoroTrader(state="closed")
        with mock.patch(ROUTER, return_value=venue):
            _close_asset_trade(t, timezone.now())
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        self.assertEqual(venue.closes, [])

    def test_a_close_pressed_while_eToro_is_silent_says_so(self):
        from bot_program.manual_close import _retry_pending
        t = self._pending()
        with mock.patch(ROUTER, return_value=EtoroTrader(state=None)):
            out = _retry_pending(self.user, t)
        self.assertTrue(out["pending"])
        self.assertIn("order read has not answered", out["error"])
        self.assertIn("Nothing was sent and nothing was booked", out["error"])
        self.assertNotIn("refuses", out["error"])
        self.assertIsNone(re.search(r"\d+\.\d+", out["error"]))

    def test_a_close_pressed_after_the_beat_counted_an_ask_says_what_this_click_did(self):
        """(2026-10-07, review) The words follow THIS click's pass, not an
        unanswered ask the beat counted up to two minutes earlier."""
        from bot_program.manual_close import _retry_pending

        class Refusing(EtoroTrader):
            def close_position(self, position_id, symbol, units=None, *,
                               open_order_id=""):
                self.closes.append((position_id, symbol, units,
                                    open_order_id))
                raise RuntimeError("eToro refused the close")

        # (a) the beat counted an ask 60 s ago on a flat list; at the click
        # the list shows NVDA again and the close is SENT and refused
        t = self._pending(venue_miss={
            "since": self._listed(10), "asks": 2,
            "last_at": _iso(timezone.now() - timedelta(seconds=60))})
        venue = Refusing(held=[("NVDA", "P131")], state=None)
        with mock.patch(ROUTER, return_value=venue), mock.patch(STAFF):
            out = _retry_pending(self.user, t)
        self.assertEqual([c[0] for c in venue.closes], ["P131"])
        self.assertTrue(out["pending"])
        self.assertNotIn("Nothing was sent", out["error"])
        self.assertNotIn("has not answered", out["error"])
        self.assertIn("STILL OPEN there", out["error"])
        # (b) the beat counted an ask 90 s ago; at the click the order read
        # ANSWERS "closed" but nothing prices the row: no "has not answered"
        t = self._pending(venue_miss={
            "since": self._listed(10), "asks": 2,
            "last_at": _iso(timezone.now() - timedelta(seconds=90))})
        venue = EtoroTrader(state="closed", last=None)
        with mock.patch(ROUTER, return_value=venue), mock.patch(STAFF):
            out = _retry_pending(self.user, t)
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSE_PENDING")
        self.assertEqual(len(venue.proofs), 1)
        self.assertEqual(venue.closes, [])
        self.assertNotIn("has not answered", out["error"])
        # the control: an ask this click itself counted keeps the words
        t = self._pending(venue_miss={
            "since": self._listed(10), "asks": 2,
            "last_at": _iso(timezone.now() - timedelta(seconds=90))})
        with mock.patch(ROUTER, return_value=EtoroTrader(state=None)):
            out = _retry_pending(self.user, t)
        self.assertIn("order read has not answered", out["error"])
        self.assertIn("Nothing was sent and nothing was booked", out["error"])


# ── D. the stamps ───────────────────────────────────────────────────────

class TheStampTests(Base):

    def test_a_paper_unprotected_or_non_etoro_row_is_never_stamped(self):
        from bot_program import venue_exit
        paper = self._nvda()
        paper.paper = True
        paper.save(update_fields=["paper"])
        bare = self._nvda(protected=False)
        oanda = self._nvda(broker="oanda")
        no_oid = self._nvda()
        no_oid.broker_order_id = ""
        no_oid.save(update_fields=["broker_order_id"])
        for t in (paper, bare, oanda, no_oid):
            self.assertFalse(venue_exit.note_crossing(t, 237.0))
            t.refresh_from_db()
            self.assertNotIn(venue_exit.CROSSED_KEY, t.metadata)
        # the listing and the miss: only an eToro client asks
        self.assertFalse(venue_exit.note_listed(paper, EtoroTrader()))
        live = self._nvda()
        for client in (OANDATrader(), mock.MagicMock()):
            self.assertFalse(venue_exit.note_listed(live, client))
            self.assertFalse(venue_exit.note_missing(live, client))
        live.refresh_from_db()
        for key in (venue_exit.LISTED_AT_KEY, venue_exit.MISSING_AT_KEY):
            self.assertNotIn(key, live.metadata)
        # a mark short of every level stamps nothing either
        self.assertFalse(venue_exit.note_crossing(live, 240.0))
        live.refresh_from_db()
        self.assertNotIn(venue_exit.CROSSED_KEY, live.metadata)
        # the control: the live eToro row's first crossing is kept, a
        # second one of the same level is not a new episode
        self.assertTrue(venue_exit.note_crossing(live, 237.9))
        first = dict(live.metadata[venue_exit.CROSSED_KEY])
        self.assertEqual((first["level"], first["price"], first["mark"]),
                         ("stop", 238.03, 237.9))
        self.assertFalse(venue_exit.note_crossing(live, 237.5))
        live.refresh_from_db()
        self.assertEqual(live.metadata[venue_exit.CROSSED_KEY], first)

    def test_a_crossing_of_the_other_level_keeps_the_first(self):
        """(2026-10-07, review) The row stays OPEN here up to the reconcile
        after eToro closed it, and the tick keeps marking it: the FIRST
        crossing since eToro last showed it open is kept, whichever level a
        later tick crosses."""
        from bot_program import venue_exit
        # NVDA: the stop at T-30m, then the target at T-5m
        t = self._nvda(venue_listed_at=self._listed(40))
        self.assertTrue(venue_exit.note_crossing(
            t, 237.9, now=self.now - timedelta(minutes=30)))
        first = dict(t.metadata[venue_exit.CROSSED_KEY])
        self.assertFalse(venue_exit.note_crossing(
            t, 245.6, now=self.now - timedelta(minutes=5)))
        t.refresh_from_db()
        self.assertEqual(t.metadata[venue_exit.CROSSED_KEY], first)
        self._run(EtoroTrader(state="closed", last="245.6"))
        t.refresh_from_db()
        self.assertEqual(t.status, "CLOSED")
        self.assertEqual(t.exit_price, Decimal("238.03"))
        self.assertEqual(t.pnl, Decimal("2.58"))
        self.assertEqual(t.outcome, "stopped_out")
        self.assertEqual(t.metadata["exit_priced_at"]["evidence"], "crossed")
        # AMZN, the mirror: the target at T-10m, then the stop at T-5m
        a = self._amzn(venue_listed_at=self._listed(15))
        self.assertTrue(venue_exit.note_crossing(
            a, 264.0, now=self.now - timedelta(minutes=10)))
        self.assertFalse(venue_exit.note_crossing(
            a, 254.0, now=self.now - timedelta(minutes=5)))
        self._run(EtoroTrader(state="closed", last="254.0"))
        a.refresh_from_db()
        self.assertEqual(a.exit_price, Decimal("263.81"))
        self.assertEqual(a.pnl, Decimal("6.42"))
        self.assertEqual(a.outcome, "hit_target")
        self.assertEqual(a.metadata["exit_fill_source"], "venue_target")
        # the control: a stamp from before the last listing is no evidence,
        # so a crossing of the other level replaces it
        s = self._amzn(venue_listed_at=self._listed(15),
                       venue_level_crossed={"level": "stop", "price": 254.18,
                                            "mark": 254.0,
                                            "at": self._listed(20)})
        self.assertTrue(venue_exit.note_crossing(s, 264.0, now=self.now))
        self.assertEqual(s.metadata[venue_exit.CROSSED_KEY]["level"], "target")

    def test_a_crossing_seen_after_a_level_change_is_stamped_again(self):
        """(2026-10-07, review) The tick stamps BEFORE the same tick's care
        and stop moves, so a target crossing can be older than the stop move
        that followed it: dead evidence for estimate(). The next tick still
        beyond the target writes it again."""
        from bot_program import venue_exit
        from bot_program.asset_engine.base import make_bot
        from django.utils.dateparse import parse_datetime
        t = self._nvda(venue_listed_at=self._listed(60))
        self.assertTrue(venue_exit.note_crossing(
            t, 246.0, now=self.now - timedelta(seconds=5)))
        client = mock.MagicMock(spec=["modify_protective", "ticker"])
        client.modify_protective.side_effect = (
            lambda oid, price: {"ok": True, "price": price})
        self.assertTrue(make_bot(self.cfg)._move_broker_stop(
            t, 246.0, client, Decimal("241.00"), "trail"))
        t.refresh_from_db()
        moved = venue_exit._level_changed_at(t)
        self.assertIsNotNone(moved)
        later = moved + timedelta(minutes=5)
        self.assertTrue(venue_exit.note_crossing(t, 246.2, now=later))
        t.refresh_from_db()
        stamp = t.metadata[venue_exit.CROSSED_KEY]
        self.assertGreater(parse_datetime(stamp["at"]), moved)
        self.assertEqual((stamp["level"], stamp["price"], stamp["mark"]),
                         ("target", 245.5, 246.2))
        got = venue_exit.estimate(t, mark=240.0,
                                  now=later + timedelta(minutes=1))
        self.assertEqual((got["level"], got["evidence"], got["price"]),
                         ("target", "crossed", 245.5))
        # a further tick of the same episode keeps it
        self.assertFalse(venue_exit.note_crossing(
            t, 246.5, now=later + timedelta(minutes=5)))
        t.refresh_from_db()
        self.assertEqual(t.metadata[venue_exit.CROSSED_KEY], stamp)

    def test_the_crossing_stamp_never_raises(self):
        from bot_program import venue_exit
        t = self._nvda()
        with mock.patch.object(venue_exit, "merge_meta",
                               side_effect=RuntimeError("db down")), \
                mock.patch(STAFF) as staff:
            self.assertFalse(venue_exit.note_crossing(t, 237.9))
            self.assertFalse(venue_exit.note_listed(t, EtoroTrader()))
            self.assertFalse(venue_exit.note_missing(t, EtoroTrader()))
            venue_exit.said_open(t, EtoroTrader(), where="test")
        self.assertEqual(staff.call_count, 1)
        # a row with unreadable fields is no crossing and no raise
        broken = mock.MagicMock(paper=False, metadata={"broker": "etoro"},
                                side="BUY", stop_loss="x", take_profit=None)
        self.assertFalse(venue_exit.note_crossing(broken, "nan"))

    def test_care_stamps_the_first_list_without_the_position(self):
        from bot_program.position_care import _venue_still_holds
        t = self._nvda()
        bot = mock.MagicMock()
        venue = EtoroTrader()
        bot._broker_snapshot.return_value = [{"position_id": "P131"}]
        self.assertTrue(_venue_still_holds(bot, t, venue))
        t.refresh_from_db()
        self.assertNotIn("venue_missing_at", t.metadata)
        bot._broker_snapshot.return_value = []
        self.assertFalse(_venue_still_holds(bot, t, venue))
        t.refresh_from_db()
        first = t.metadata["venue_missing_at"]
        self.assertFalse(_venue_still_holds(bot, t, venue))
        t.refresh_from_db()
        self.assertEqual(t.metadata["venue_missing_at"], first)
        # an unreadable snapshot is no miss
        t2 = self._nvda()
        bot._broker_snapshot.return_value = None
        self.assertFalse(_venue_still_holds(bot, t2, venue))
        t2.refresh_from_db()
        self.assertNotIn("venue_missing_at", t2.metadata)
        # under the venue's 60 s lag the list has not caught up
        t3 = self._nvda(age=timedelta(seconds=20))
        bot._broker_snapshot.return_value = []
        self.assertFalse(_venue_still_holds(bot, t3, venue))
        t3.refresh_from_db()
        self.assertNotIn("venue_missing_at", t3.metadata)


# ── E. the words ────────────────────────────────────────────────────────

class TheWordsTests(Base):

    def _msg(self, **meta):
        from bot_program.notifications import fill_close_message
        t = self._nvda(**meta)
        t.status, t.reason = "CLOSED", "manual | reconciled-orphan"
        t.exit_price, t.pnl = Decimal("238.03"), Decimal("2.58")
        t.closed_at = datetime(2026, 10, 7, 11, 15, 0, 634564, tzinfo=dt_tz.utc)
        t.metadata["exit_price_inferred"] = True
        t.outcome = "stopped_out"
        t.save()
        return fill_close_message(asset_class="stock", symbol="NVDA",
                                  side="BUY", qty=t.qty, exit_price=t.exit_price,
                                  pnl=t.pnl, trade=t)

    def test_the_stop_and_the_window(self):
        msg = self._msg(
            exit_priced_at={"level": "stop", "price": 238.03,
                            "evidence": "crossed"},
            venue_closed_between=["2026-10-07T11:00:03+00:00",
                                  "2026-10-07T11:07:59+00:00"])
        self.assertIn("Priced at the stop the venue held (238.03): the "
                      "venue's own fill price is not readable.", msg["lines"])
        self.assertIn("How it ended: stop loss hit", msg["lines"])
        self.assertEqual(msg["details"][-1],
                         "Recorded closed: 2026-10-07 11:15 UTC — eToro last "
                         "showed it open at 11:00 UTC and no longer at 11:08 "
                         "UTC; the exact moment of the close is not readable")
        self.assertNotIn(" after ", msg["summary"])

    def test_a_nearest_estimate_never_says_stop_loss_hit(self):
        msg = self._msg(exit_priced_at={"level": "stop", "price": 238.03,
                                        "evidence": "nearest"})
        self.assertIn("How it ended: closed at the broker, most likely by its "
                      "stop (an estimate)", msg["lines"])
        self.assertNotIn("How it ended: stop loss hit", msg["lines"])
        self.assertIn("Priced at the stop the venue held (238.03), the level "
                      "nearest the price when the close was found: an "
                      "estimate; the venue's own fill price is not readable.",
                      msg["lines"])

    def test_midnight_carries_both_dates(self):
        from bot_program.venue_exit import between_words
        lo = datetime(2026, 10, 6, 23, 59, 30, tzinfo=dt_tz.utc)
        hi = datetime(2026, 10, 7, 0, 7, 59, tzinfo=dt_tz.utc)
        self.assertEqual(between_words(lo, hi),
                         "eToro last showed it open at 2026-10-06 23:59 UTC "
                         "and no longer at 2026-10-07 00:08 UTC")
        # a whole-minute upper bound is not rounded up
        self.assertEqual(between_words(lo, hi.replace(second=0)),
                         "eToro last showed it open at 2026-10-06 23:59 UTC "
                         "and no longer at 2026-10-07 00:07 UTC")

    def test_an_unproven_close_says_eToro_never_confirmed_it(self):
        msg = self._msg(venue_unproven_close="eToro's order read did not "
                                             "answer 5 asks over 56 minutes")
        line = ("eToro never confirmed this close: its order read did not "
                "answer for an hour, so the row was booked from its position "
                "list.")
        self.assertIn(line, msg["lines"])
        self.assertIsNone(re.search(r"\d", line))
        self.assertIn("Priced from the last mark, not from a broker fill.",
                      msg["lines"])
        self.assertTrue(msg["details"][-1].endswith(
            "the broker had closed it before; the exact moment is not "
            "readable"))


# ── F. the wiring and the constants ─────────────────────────────────────

class TheWiringTests(TestCase):

    def test_every_path_that_books_a_miss_asks_the_venue_first(self):
        from bot_program import pending_closes, reconcile_asset
        src = inspect.getsource(reconcile_asset.reconcile_user)
        self.assertLess(src.index("venue_exit.word_on_miss("),
                        src.index("_close_as_orphan("))
        self.assertLess(src.index("venue_exit.note_listed("),
                        src.index("venue_exit.word_on_miss("))
        src = inspect.getsource(pending_closes.retry_trade_close)
        first = src.index("venue_exit.after_no_answer(")
        self.assertLess(first, src.index('reason="RETRY_ALREADY_FLAT"'))
        second = src.index("venue_exit.after_no_answer(", first + 1)
        self.assertLess(second, src.index('reason="RETRY_WORKING_CLOSE_FILLED"'))
        self.assertLess(src.index("venue_position_state(trade, client)"),
                        src.index('reason="RETRY_VENUE_PROVED_CLOSED"'))
        src = inspect.getsource(pending_closes._reconcile_filled_against_broker)
        self.assertLess(src.index("venue_position_state(trade, client)"),
                        src.index("implied_filled ="))
        # the window and the price are written by the reconcile only on
        # the venue's "closed"
        src = inspect.getsource(reconcile_asset._close_as_orphan)
        self.assertIn('if venue_said == "closed" and not measured', src)
        self.assertIn('if venue_said == "closed" else None', src)

    def test_the_constants(self):
        from bot_program import morgul, venue_exit
        self.assertEqual(venue_exit.UNPROVEN_WAIT_S, 3300)
        self.assertEqual(venue_exit.UNPROVEN_MIN_ASKS, 4)
        self.assertEqual(venue_exit.MISS_RESTART_AFTER_S, 2100)
        self.assertEqual(venue_exit.NEAREST_STOP_MAX_R, 1.0)
        self.assertEqual(venue_exit.NEAREST_TARGET_MAX_R, 0.5)
        self.assertEqual(venue_exit.BARS_TIMEFRAME, "1h")
        self.assertEqual(venue_exit.BARS_START_SLACK_S, 300)
        self.assertEqual(venue_exit.NO_STOP_SENTINEL, morgul.NO_STOP_SENTINEL)
        self.assertEqual(morgul.VENUE_SESSION_CLASSES, ("stock", "etf"))
