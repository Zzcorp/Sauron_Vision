"""THE ENTRY TIMING (2026-10-06, the operator asked for more resilience and
smartness in taking positions): no new entry in the minutes when the price
is not a market price, and no attack into a scheduled print.

  ROLLOVER      forex, commodities, indices: ROLLOVER_NY, New York time.
  SHUT          (2026-10-07) an exchange that is shut, on Morgul G1's own
                clock and classes (SHUT_CLASSES; the options lane's live
                branch on its underlying's key, OPTIONS_SHUT_CLASSES):
                the hour it opens and the hour entries resume, recorded as
                skips.MARKET_SHUT — after config 26's PG short filled 22
                minutes before the NYSE open on 2026-10-06.
  OPEN SETTLE   the first OPEN_SETTLE_MINUTES after any modelled open —
                for forex, the first quarter hour of the week.
  CLOSE GUARD   a stock or ETF in the last CLOSE_GUARD_MINUTES before its
                exchange closes (early closes kept); every class that shuts,
                in Friday's last hour before the weekend.
  THE PRINT     position_care.event_for's window at entry.
  THE ATTACK    a print within EVENT_ATTACK_HOURS caps the tier at STANDARD.

The bot lane refuses (skips.BAD_TIMING) at the proposal and again before
the order; the TAKE TRADE ticket warns and stays pressable. The suite runs
with the gate OFF (tests/__init__.py); these tests turn it on at a fixed
clock.

Run with:  python manage.py test tests.test_entry_timing
"""
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from bot_program import entry_timing as et

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _ny(y, m, d, hh, mm):
    """An aware instant from New York wall time (DST follows)."""
    return datetime(y, m, d, hh, mm, tzinfo=NY).astimezone(UTC)


def _ev(now, minutes, title="CPI", currency="USD", earnings=False):
    return {"at": now + timedelta(minutes=minutes), "title": title,
            "currency": currency, "earnings": earnings}


def _on():
    return mock.patch.object(et, "GATE", True)


# a Tuesday in winter (New York = UTC-5) and one in summer (UTC-4)
WINTER_TUE = (2026, 1, 13)
SUMMER_TUE = (2026, 7, 14)
WINTER_FRI = (2026, 1, 16)
SUMMER_FRI = (2026, 7, 17)


class TheConstantsTests(SimpleTestCase):

    def test_the_windows(self):
        from datetime import time as dtime
        self.assertEqual(et.ROLLOVER_NY, (dtime(16, 50), dtime(17, 10)))
        self.assertEqual(et.ROLLOVER_CLASSES,
                         frozenset({"forex", "commodity", "index"}))
        self.assertEqual((et.OPEN_SETTLE_MINUTES, et.CLOSE_GUARD_MINUTES),
                         (15, 10))
        self.assertEqual(et.CLOSE_GUARD_CLASSES, frozenset({"stock", "etf"}))
        self.assertEqual((et.EVENT_ATTACK_HOURS, et.EVENT_ATTACK_CAP),
                         (3, "STANDARD"))

    def test_the_suite_runs_with_the_gate_off_and_off_is_open(self):
        self.assertFalse(et.GATE)
        v = et.verdict("EURUSD", "forex", now=_ny(*WINTER_TUE, 16, 55),
                       events=[_ev(_ny(*WINTER_TUE, 16, 55), 10)])
        self.assertEqual(v, {"ok": True, "code": "", "why": "", "until": None,
                             "attack": None})


class TheRolloverTests(SimpleTestCase):

    def test_forex_commodities_and_indices_in_the_window_winter_and_summer(self):
        with _on():
            for day in (WINTER_TUE, SUMMER_TUE):
                for cls, sym in (("forex", "EURUSD"), ("commodity", "XAUUSD"),
                                 ("index", "SPX500")):
                    with self.subTest(day=day, cls=cls):
                        v = et.verdict(sym, cls, now=_ny(*day, 16, 55),
                                       events=[])
                        self.assertFalse(v["ok"])
                        self.assertEqual(v["code"], et.ROLLOVER)
                        self.assertIn("rolls over at 17:00 New York", v["why"])
                        # a commodity clears when CME reopens from its
                        # 16:00-17:00 CT break (18:00 New York) and settles
                        from datetime import time as dtime
                        want = (dtime(18, 15) if cls == "commodity"
                                else et.ROLLOVER_NY[1])
                        self.assertEqual(v["until"].astimezone(NY).time(),
                                         want)

    def test_the_edges_and_the_classes_that_do_not_roll(self):
        with _on():
            self.assertTrue(et.verdict("EURUSD", "forex",
                                       now=_ny(*WINTER_TUE, 16, 49),
                                       events=[])["ok"])
            self.assertTrue(et.verdict("EURUSD", "forex",
                                       now=_ny(*WINTER_TUE, 17, 10),
                                       events=[])["ok"])
            self.assertEqual(et.verdict("EURUSD", "forex",
                                        now=_ny(*WINTER_TUE, 17, 9),
                                        events=[])["code"], et.ROLLOVER)
            # crypto never rolls; a stock does not roll either, and at
            # 16:55 New York its exchange is shut: since 2026-10-07 that is
            # SHUT, with the hour NASDAQ opens again and the hour entries
            # resume (a fill Morgul G1 would flag: shut since 16:00)
            self.assertTrue(et.verdict("BTCUSD", "crypto",
                                       now=_ny(*WINTER_TUE, 16, 55),
                                       events=[])["ok"])
            v = et.verdict("AAPL", "stock", exchange="NASDAQ",
                           now=_ny(*WINTER_TUE, 16, 55), events=[])
            self.assertEqual(v["code"], et.SHUT)
            self.assertEqual(v["until"],
                             datetime(2026, 1, 14, 14, 45, tzinfo=UTC))
            self.assertIn("shut until Wednesday 14:30 UTC", v["why"])


class TheRolloverOnAShutVenueTests(SimpleTestCase):
    """Review 2026-10-06: the rollover answers while the venue is in its
    own break, so the hour it clears is the venue's reopening plus its
    settling quarter hour, never the window's end inside a shut venue."""

    def test_cme_metals_clear_after_the_daily_break_and_its_settle(self):
        # Tuesday 17:05 New York: CME is in its 16:00-17:00 CT break and
        # reopens at 17:00 CT = 18:00 New York = 23:00 UTC in winter
        with _on():
            v = et.verdict("XAUUSD", "commodity", exchange="COMEX",
                           now=_ny(*WINTER_TUE, 17, 5), events=[])
        self.assertEqual(v["code"], et.ROLLOVER)
        self.assertEqual(v["until"],
                         datetime(2026, 1, 13, 23, 15, tzinfo=UTC))
        self.assertIn("resume Tuesday 23:15 UTC, once the venue reopens "
                      "and settles", v["why"])

    def test_a_venue_open_at_the_windows_end_keeps_it(self):
        with _on():
            v = et.verdict("EURUSD", "forex", exchange="FOREX",
                           now=_ny(*WINTER_TUE, 16, 55), events=[])
        self.assertEqual(v["until"], _ny(*WINTER_TUE, 17, 10))
        self.assertNotIn("once the venue reopens", v["why"])

    def test_the_hour_comes_first_in_the_words(self):
        """why_no_trade prints 88 characters of a skip's detail."""
        with _on():
            roll = et.verdict("EURUSD", "forex", exchange="FOREX",
                              now=_ny(*WINTER_TUE, 16, 55), events=[])
            settle = et.verdict("AAPL", "stock", exchange="NASDAQ",
                                now=_ny(*WINTER_TUE, 9, 40), events=[])
        self.assertIn("resume Tuesday 22:10 UTC", roll["why"][:88])
        self.assertIn("resume Tuesday 14:45 UTC", settle["why"][:88])

    def test_an_unreadable_advisory_is_logged(self):
        with mock.patch.object(et, "verdict", side_effect=RuntimeError("x")), \
                self.assertLogs("bot_program.entry_timing", level="WARNING"):
            self.assertTrue(et.advisory("EURUSD", "forex")["ok"])


class TheOpenSettleTests(SimpleTestCase):

    def test_the_first_quarter_hour_of_a_stock_session(self):
        with _on():
            v = et.verdict("AAPL", "stock", exchange="NASDAQ",
                           now=_ny(*WINTER_TUE, 9, 40), events=[])
            self.assertFalse(v["ok"])
            self.assertEqual(v["code"], et.OPEN_SETTLE)
            self.assertIn("opened at Tuesday 14:30 UTC", v["why"])
            self.assertIn("resume Tuesday 14:45 UTC", v["why"])
            self.assertEqual(v["until"], _ny(*WINTER_TUE, 9, 45))
            self.assertTrue(et.verdict("AAPL", "stock", exchange="NASDAQ",
                                       now=_ny(*WINTER_TUE, 9, 45),
                                       events=[])["ok"])

    def test_the_first_quarter_hour_of_the_forex_week(self):
        # Sunday 2026-01-18: the week opens at 17:00 New York = 22:00 UTC
        with _on():
            v = et.verdict("EURUSD", "forex", exchange="FOREX",
                           now=datetime(2026, 1, 18, 22, 5, tzinfo=UTC),
                           events=[])
            self.assertEqual(v["code"], et.OPEN_SETTLE)
            self.assertIn("Sunday 22:00 UTC", v["why"])
            self.assertTrue(et.verdict("EURUSD", "forex", exchange="FOREX",
                                       now=datetime(2026, 1, 18, 22, 20,
                                                    tzinfo=UTC),
                                       events=[])["ok"])

    def test_a_shut_market_is_refused_with_its_opening_hour(self):
        """2026-10-07: a shut market was nobody's business here; it is now
        SHUT, with the hour it opens (Morgul G1's own clock)."""
        with _on():
            # Saturday forex, a stock at 03:00 New York
            v = et.verdict("EURUSD", "forex", exchange="FOREX",
                           now=datetime(2026, 1, 17, 12, 0, tzinfo=UTC),
                           events=[])
            self.assertEqual(v["code"], et.SHUT)
            self.assertIn("until Sunday 22:00 UTC", v["why"])
            v = et.verdict("AAPL", "stock", exchange="NASDAQ",
                           now=_ny(*WINTER_TUE, 3, 0), events=[])
            self.assertEqual(v["code"], et.SHUT)
            self.assertIn("until Tuesday 14:30 UTC", v["why"])


class TheCloseGuardTests(SimpleTestCase):

    def test_the_last_ten_minutes_of_a_stock_session(self):
        with _on():
            v = et.verdict("AAPL", "stock", exchange="NASDAQ",
                           now=_ny(*WINTER_TUE, 15, 55), events=[])
            self.assertFalse(v["ok"])
            self.assertEqual(v["code"], et.CLOSE_GUARD)
            self.assertIn("closes at Tuesday 21:00 UTC", v["why"])
            self.assertEqual(v["until"], _ny(*WINTER_TUE, 16, 0))
            self.assertTrue(et.verdict("AAPL", "stock", exchange="NASDAQ",
                                       now=_ny(*WINTER_TUE, 15, 45),
                                       events=[])["ok"])
            # an ETF on the NYSE, same rule; a forex pair has no daily close
            self.assertEqual(et.verdict("SPY", "etf", exchange="NYSE",
                                        now=_ny(*WINTER_TUE, 15, 55),
                                        events=[])["code"], et.CLOSE_GUARD)
            self.assertTrue(et.verdict("EURUSD", "forex", exchange="FOREX",
                                       now=_ny(*WINTER_TUE, 15, 55),
                                       events=[])["ok"])

    def test_an_early_close_is_kept(self):
        # Friday 2026-11-27, the 13:00 New York early close
        with _on():
            v = et.verdict("AAPL", "stock", exchange="NASDAQ",
                           now=_ny(2026, 11, 27, 12, 55), events=[])
            self.assertEqual(v["code"], et.CLOSE_GUARD)
            self.assertIn("closes at Friday 18:00 UTC", v["why"])
            # after it the market is shut: SHUT since 2026-10-07, with the
            # next session's opening (Monday, past the weekend)
            v = et.verdict("AAPL", "stock", exchange="NASDAQ",
                           now=_ny(2026, 11, 27, 13, 5), events=[])
            self.assertEqual(v["code"], et.SHUT)
            self.assertIn("until Monday 14:30 UTC", v["why"])

    def test_fridays_last_hour_before_the_weekend(self):
        # 2026-10-07: on a WINTER Friday the forex clock (the FOREX row's
        # Friday 21:00 UTC, morgul._shut's own) has already shut the
        # market at 16:00 New York, so SHUT answers there first, with the
        # week's opening hour; the forex weekend window is pinned on a
        # SUMMER Friday, when 16:00 New York is 20:00 UTC and the market is
        # still open.
        with _on():
            v = et.verdict("EURUSD", "forex", exchange="FOREX",
                           now=_ny(*SUMMER_FRI, 16, 0), events=[])
            self.assertEqual(v["code"], et.WEEKEND)
            self.assertIn("Friday's last hour before the weekend", v["why"])
            # Friday 16:50-17:00 is the weekend window's, never a rollover
            # that would name a resume hour inside the shut weekend
            v = et.verdict("EURUSD", "forex", exchange="FOREX",
                           now=_ny(*SUMMER_FRI, 16, 55), events=[])
            self.assertEqual(v["code"], et.WEEKEND)
            self.assertNotIn("resume Friday", v["why"])
            v = et.verdict("EURUSD", "forex", exchange="FOREX",
                           now=_ny(*WINTER_FRI, 16, 55), events=[])
            self.assertEqual(v["code"], et.SHUT)
            self.assertNotIn("resume Friday", v["why"])
            self.assertIsNone(et.rollover(_ny(*WINTER_FRI, 16, 55), "forex"))
            self.assertIsNone(et.rollover(_ny(2026, 7, 17, 16, 55), "index"))
            # a stock: 15:00-16:00 New York on Friday
            self.assertEqual(et.verdict("AAPL", "stock", exchange="NASDAQ",
                                        now=_ny(*WINTER_FRI, 15, 10),
                                        events=[])["code"], et.WEEKEND)
            self.assertTrue(et.verdict("AAPL", "stock", exchange="NASDAQ",
                                       now=_ny(*WINTER_FRI, 14, 50),
                                       events=[])["ok"])
            # Thursday at the same hour: nothing
            self.assertTrue(et.verdict("EURUSD", "forex", exchange="FOREX",
                                       now=_ny(2026, 1, 15, 16, 0),
                                       events=[])["ok"])


class ThePrintTests(SimpleTestCase):

    def setUp(self):
        self.now = _ny(*WINTER_TUE, 10, 0)

    def test_a_print_in_the_window_refuses_with_the_cares_matching(self):
        with _on():
            v = et.verdict("EURUSD", "forex", now=self.now,
                           events=[_ev(self.now, 30)])
            self.assertFalse(v["ok"])
            self.assertEqual(v["code"], et.EVENT)
            self.assertIn("high-impact print CPI in 30 min", v["why"])
            self.assertIn("60 min before to 15 min after", v["why"])
            self.assertEqual(v["until"], self.now + timedelta(minutes=45))
            # the minutes after, too
            self.assertEqual(et.verdict("EURUSD", "forex", now=self.now,
                                        events=[_ev(self.now, -10)])["code"],
                             et.EVENT)
            # a currency the pair does not carry: nothing
            self.assertTrue(et.verdict("GBPJPY", "forex", now=self.now,
                                       events=[_ev(self.now, 30)])["ok"])
            # the home currency reaches a stock and a crypto row
            self.assertEqual(et.verdict("AAPL", "stock", exchange="NASDAQ",
                                        now=self.now,
                                        events=[_ev(self.now, 30)])["code"],
                             et.EVENT)
            self.assertEqual(et.verdict("BTCUSD", "crypto", now=self.now,
                                        events=[_ev(self.now, 30)])["code"],
                             et.EVENT)

    def test_a_print_within_three_hours_caps_the_attack(self):
        with _on():
            v = et.verdict("EURUSD", "forex", now=self.now,
                           events=[_ev(self.now, 120)])
            self.assertTrue(v["ok"])
            self.assertEqual(v["attack"]["cap"], "STANDARD")
            self.assertIn("attack capped at STANDARD: CPI in 120 min",
                          v["attack"]["why"])
            # past three hours: no cap; another currency: no cap
            self.assertIsNone(et.verdict("EURUSD", "forex", now=self.now,
                                         events=[_ev(self.now, 200)])["attack"])
            self.assertIsNone(et.verdict("GBPJPY", "forex", now=self.now,
                                         events=[_ev(self.now, 120)])["attack"])
            self.assertIn("in 2.5 h", et.verdict(
                "AAPL", "stock", exchange="NASDAQ", now=self.now,
                events=[_ev(self.now, 150)])["attack"]["why"])

    def test_a_stocks_own_earnings_refuse(self):
        with _on():
            v = et.verdict("AAPL", "stock", exchange="NASDAQ", now=self.now,
                           events=[_ev(self.now, 20 * 60, title="AAPL earnings",
                                       currency="AAPL", earnings=True)])
            self.assertEqual(v["code"], et.EVENT)
            self.assertIn("AAPL earnings in 20 h", v["why"])
            self.assertIn("own earnings within 24 h", v["why"])
            # another stock's earnings: nothing
            self.assertTrue(et.verdict("MSFT", "stock", exchange="NASDAQ",
                                       now=self.now,
                                       events=[_ev(self.now, 20 * 60,
                                                   title="AAPL earnings",
                                                   currency="AAPL",
                                                   earnings=True)])["ok"])

    def test_options_are_never_judged(self):
        with _on():
            self.assertTrue(et.verdict("AAPL", "options", now=self.now,
                                       events=[_ev(self.now, 30)])["ok"])

    def test_the_clock_comes_before_the_calendar(self):
        with _on():
            v = et.verdict("EURUSD", "forex", now=_ny(*WINTER_TUE, 16, 55),
                           events=[_ev(_ny(*WINTER_TUE, 16, 55), 30)])
            self.assertEqual(v["code"], et.ROLLOVER)


class NothingUnreadableRefusesTests(SimpleTestCase):

    def test_an_unreadable_clock_or_calendar_refuses_nothing(self):
        with _on(), \
                mock.patch("core.exchange_status.market_clock",
                           side_effect=RuntimeError("no clock")), \
                self.assertLogs("bot_program.entry_timing", level="WARNING"):
            v = et.verdict("AAPL", "stock", exchange="NASDAQ",
                           now=_ny(*WINTER_TUE, 9, 40), events=[])
        self.assertTrue(v["ok"])
        with _on(), \
                mock.patch("bot_program.position_care.event_for",
                           side_effect=RuntimeError("no calendar")), \
                self.assertLogs("bot_program.entry_timing", level="WARNING"):
            v = et.verdict("EURUSD", "forex", now=_ny(*WINTER_TUE, 10, 0),
                           events=[_ev(_ny(*WINTER_TUE, 10, 0), 30)])
        self.assertTrue(v["ok"])

    def test_the_advisory_shape(self):
        with _on():
            adv = et.advisory("EURUSD", "forex", now=_ny(*WINTER_TUE, 16, 55))
            self.assertFalse(adv["ok"])
            self.assertIn("rolls over", adv["reason"])
            self.assertEqual(adv["attack"], "")
            self.assertEqual(adv["code"], et.ROLLOVER)
        with mock.patch.object(et, "verdict", side_effect=RuntimeError("x")):
            self.assertEqual(et.advisory("EURUSD", "forex"),
                             {"ok": True, "reason": "", "attack": "",
                              "code": ""})


# ── the shut exchange (2026-10-07) ────────────────────────────────────────

class TheShutExchangeTests(SimpleTestCase):
    """THE SHUT EXCHANGE (2026-10-07): on 2026-10-06 research_stock_5
    (config 26) shorted PG at 13:08 UTC, 22 minutes before the NYSE open;
    eToro filled it at once and Morgul G1 braked the config at 13:12. The
    bot lane now refuses a live entry while the instrument's exchange is
    shut, on Morgul G1's own clock and for G1's classes at a broker."""

    def test_the_pg_short_of_2026_10_06_is_refused_with_the_hour_nyse_opens(self):
        from bot_program import morgul
        at = datetime(2026, 10, 6, 13, 8, tzinfo=UTC)
        with _on():
            v = et.verdict("PG", "stock", exchange="NYSE", now=at, events=[])
            self.assertFalse(v["ok"])
            self.assertEqual(v["code"], et.SHUT)
            self.assertEqual(v["until"],
                             datetime(2026, 10, 6, 13, 45, tzinfo=UTC))
            # the hours come first: why_no_trade prints 88 characters; the
            # resume instant on the reopening's own date is its hour alone
            self.assertIn("shut until Tuesday 13:30 UTC", v["why"][:88])
            self.assertIn("resume 13:45 UTC", v["why"][:88])
            # shut at 13:08 and a grace before: a fill G1 would flag (it
            # runs only while morgul_guards is ON, and brakes only while
            # morgul_brake is ON, so "would", and never "brakes")
            self.assertIn("(NYSE hours: out of session, a fill Morgul G1 "
                          "would flag)", v["why"])
            self.assertNotIn("brakes", v["why"])
            # the clock G1 judged the booking on, at the booking and at
            # the noticed-fill grace before it
            self.assertTrue(morgul._shut("stock", "NYSE", "PG", at))
            self.assertTrue(morgul._shut(
                "stock", "NYSE", "PG",
                at - timedelta(seconds=morgul.NOTICED_GRACE_S)))
            # inside the first quarter hour: OPEN_SETTLE; then an entry
            self.assertEqual(et.verdict(
                "PG", "stock", exchange="NYSE",
                now=datetime(2026, 10, 6, 13, 35, tzinfo=UTC),
                events=[])["code"], et.OPEN_SETTLE)
            self.assertTrue(et.verdict(
                "PG", "stock", exchange="NYSE",
                now=datetime(2026, 10, 6, 13, 45, tzinfo=UTC),
                events=[])["ok"])

    def test_every_class_morgul_g1_judges_is_refused_while_its_exchange_is_shut(self):
        from bot_program import morgul
        chicago = ZoneInfo("America/Chicago")
        cases = (
            ("EURUSD", "forex", "FOREX",
             datetime(2026, 1, 17, 12, 0, tzinfo=UTC),
             ("until Sunday 22:00 UTC",), None),
            ("XAUUSD", "commodity", "COMEX", _ny(*WINTER_TUE, 17, 30),
             ("until Tuesday 23:00 UTC",),
             datetime(2026, 1, 13, 23, 15, tzinfo=UTC)),
            ("CORNUSD", "commodity", "CBOT",
             datetime(*WINTER_TUE, 14, 0, tzinfo=chicago).astimezone(UTC),
             ("until Wednesday 01:00 UTC", "CBOT GRAINS hours"), None),
            ("SPY", "etf", "NYSE", _ny(*WINTER_TUE, 3, 0),
             ("until Tuesday 14:30 UTC",), None),
            ("VOD", "stock", "LSE", datetime(*WINTER_TUE, 3, 0, tzinfo=UTC),
             ("until Tuesday 08:00 UTC",), None),
        )
        with _on():
            for sym, cls, ex, at, words, until in cases:
                with self.subTest(sym=sym):
                    v = et.verdict(sym, cls, exchange=ex, now=at, events=[])
                    self.assertEqual(v["code"], et.SHUT)
                    for w in words:
                        self.assertIn(w, v["why"])
                    self.assertNotIn("_", v["why"])
                    if until is not None:
                        self.assertEqual(v["until"], until)
                    self.assertTrue(morgul._shut(cls, ex, sym, at))

    def test_holidays_and_early_closes_name_the_next_session(self):
        with _on():
            v = et.verdict("PG", "stock", exchange="NYSE",
                           now=_ny(2026, 11, 26, 10, 0), events=[])
            self.assertEqual(v["code"], et.SHUT)
            self.assertIn("until Friday 14:30 UTC", v["why"])
            v = et.verdict("PG", "stock", exchange="NYSE",
                           now=_ny(2026, 11, 27, 13, 5), events=[])
            self.assertEqual(v["code"], et.SHUT)
            self.assertIn("until Monday 14:30 UTC", v["why"])

    def test_shut_comes_after_the_rollover_and_before_the_weekend_window(self):
        from bot_program.position_care import is_weekend_window
        with _on():
            # CME's daily break at 17:05 New York keeps PR47's words
            self.assertEqual(et.verdict(
                "XAUUSD", "commodity", exchange="COMEX",
                now=_ny(*WINTER_TUE, 17, 5), events=[])["code"], et.ROLLOVER)
            # the grains shut at 13:20 Chicago: on a Friday at 15:45 New
            # York they are inside the weekend window AND shut, and the
            # opening hour wins over the window's words, which name none
            corn_at = _ny(*WINTER_FRI, 15, 45)
            self.assertTrue(is_weekend_window(corn_at, "commodity"))
            v = et.verdict("CORNUSD", "commodity", exchange="CBOT",
                           now=corn_at, events=[])
            self.assertEqual(v["code"], et.SHUT)
            self.assertIn("until Monday 01:00 UTC", v["why"])
            self.assertNotEqual(v["code"], et.WEEKEND)
            # an open market in its weekend window stays WEEKEND: forex on
            # a summer Friday at 16:00 New York (20:00 UTC, still open)
            self.assertEqual(et.verdict(
                "EURUSD", "forex", exchange="FOREX",
                now=_ny(*SUMMER_FRI, 16, 0), events=[])["code"], et.WEEKEND)
            # on a winter Friday 16:00 New York is 21:00 UTC: the forex
            # clock (the FOREX row, morgul._shut's) is already shut, so it
            # is SHUT with the week's opening hour
            v = et.verdict("EURUSD", "forex", exchange="FOREX",
                           now=_ny(*WINTER_FRI, 16, 0), events=[])
            self.assertEqual(v["code"], et.SHUT)
            self.assertIn("until Sunday 22:00 UTC", v["why"])

    def test_what_g1_does_not_judge_is_never_refused_for_being_shut(self):
        with _on():
            for at in (_ny(*WINTER_TUE, 3, 0),
                       datetime(2026, 1, 17, 12, 0, tzinfo=UTC)):
                for sym, cls in (("SPX500", "index"), ("BTCUSD", "crypto"),
                                 ("XCFD", "cfd"), ("AAPL", "options")):
                    with self.subTest(sym=sym, at=at):
                        self.assertTrue(et.verdict(sym, cls, now=at,
                                                   events=[])["ok"])

    def test_the_shut_classes_are_morguls_clock_classes_less_index_and_options(self):
        from bot_program import morgul
        self.assertEqual(et.SHUT_CLASSES,
                         frozenset(morgul.CLOCK_CLASSES) - {"index", "options"})
        self.assertEqual(et.OPTIONS_SHUT_CLASSES,
                         frozenset(morgul.CLOCK_CLASSES) - {"index"})
        self.assertEqual(et.SHUT, "SHUT")

    def test_the_gate_and_morgul_g1_never_disagree_over_a_week(self):
        """Thanksgiving week 2026, every 20 minutes: a SHUT_CLASSES
        instrument G1 calls shut is never let through, SHUT is never said
        of a market G1 calls open, and never of an index or crypto."""
        from bot_program import morgul
        book = (("PG", "stock", "NYSE"), ("VOD", "stock", "LSE"),
                ("SPY", "etf", "NYSE"), ("EURUSD", "forex", "FOREX"),
                ("XAUUSD", "commodity", "COMEX"),
                ("CORNUSD", "commodity", "CBOT"),
                ("LEANHOGS", "commodity", ""), ("SPX500", "index", ""),
                ("BTCUSD", "crypto", ""))
        start = datetime(2026, 11, 22, 0, 0, tzinfo=UTC)
        end = datetime(2026, 11, 30, 0, 0, tzinfo=UTC)
        wrong, said = [], 0
        with _on():
            at = start
            while at < end:
                for sym, cls, ex in book:
                    v = et.verdict(sym, cls, exchange=ex, now=at, events=[])
                    if v["code"] == et.SHUT:
                        said += 1
                        if cls in ("index", "crypto"):
                            wrong.append(f"SHUT on {cls} {sym} at {at}")
                    if cls in et.SHUT_CLASSES:
                        shut = morgul._shut(cls, ex, sym, at)
                        if shut and v["ok"]:
                            wrong.append(f"{sym} let through at {at}, "
                                         f"G1 calls it shut")
                        if v["code"] == et.SHUT and not shut:
                            wrong.append(f"{sym} SHUT at {at}, G1 calls "
                                         f"it open")
                at += timedelta(minutes=20)
        self.assertEqual(wrong, [])
        self.assertGreater(said, 1000)

    def test_the_minutes_after_a_close_name_no_morgul(self):
        """Review 2026-10-07: G1 flags a booking only when the market is
        shut at it AND CLOSE_GRACE_S before it. PG at 20:03 UTC, three
        minutes after the NYSE close: SHUT, and the words promise no flag
        G1 would not raise."""
        from bot_program import morgul
        at = datetime(2026, 10, 7, 20, 3, tzinfo=UTC)
        with _on():
            v = et.verdict("PG", "stock", exchange="NYSE", now=at, events=[])
        self.assertEqual(v["code"], et.SHUT)
        self.assertNotIn("Morgul", v["why"])
        self.assertTrue(v["why"].endswith("(NYSE hours: out of session)"),
                        v["why"])
        self.assertIn("shut until Thursday 13:30 UTC — new entries resume "
                      "13:45 UTC", v["why"][:88])
        # G1's own condition: shut now, open a grace before
        self.assertTrue(morgul._shut("stock", "NYSE", "PG", at))
        self.assertFalse(morgul._shut(
            "stock", "NYSE", "PG",
            at - timedelta(seconds=morgul.CLOSE_GRACE_S)))

    def test_past_the_grace_the_words_say_g1_would_flag(self):
        from bot_program import morgul
        at = datetime(2026, 10, 7, 20, 20, tzinfo=UTC)
        with _on():
            v = et.verdict("PG", "stock", exchange="NYSE", now=at, events=[])
        self.assertEqual(v["code"], et.SHUT)
        self.assertTrue(v["why"].endswith(
            "(NYSE hours: out of session, a fill Morgul G1 would flag)"),
            v["why"])
        self.assertTrue(morgul._shut(
            "stock", "NYSE", "PG",
            at - timedelta(seconds=morgul.CLOSE_GRACE_S)))
        # a second read that fails promises no flag; the refusal stands
        with _on(), mock.patch.object(et, "_g1_would_flag",
                                      return_value=False):
            v = et.verdict("PG", "stock", exchange="NYSE", now=at, events=[])
        self.assertEqual(v["code"], et.SHUT)
        self.assertNotIn("Morgul", v["why"])
        with _on(), mock.patch("bot_program.morgul.CLOSE_GRACE_S", None), \
                self.assertLogs("bot_program.entry_timing", level="WARNING"):
            self.assertFalse(et._g1_would_flag("stock", "NYSE", "PG", at))

    def test_the_resume_hour_survives_the_88_characters_every_weekday(self):
        """SPLIT (review 2026-10-07): why_no_trade prints 88 characters of
        a skip's detail. Every SHUT_CLASSES instrument, every weekday of
        2026-10-05..10-11, every 20 minutes: whenever the verdict is SHUT
        with a reopening, the "resume ... HH:MM UTC" token is inside the
        88, and "would flag" is said exactly when G1's own condition
        holds (shut now and CLOSE_GRACE_S before)."""
        import re
        from bot_program import morgul
        book = (("PG", "stock", "NYSE"), ("SPY", "etf", "NYSE"),
                ("EURUSD", "forex", "FOREX"),
                ("XAUUSD", "commodity", "COMEX"),
                ("CORNUSD", "commodity", "CBOT"))
        start = datetime(2026, 10, 5, 0, 0, tzinfo=UTC)
        end = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)
        token = re.compile(r"new entries resume (?:[A-Z][a-z]+day )?"
                           r"(\d\d:\d\d) UTC")
        wrong, checked, days = [], 0, set()
        with _on():
            at = start
            while at < end:
                for sym, cls, ex in book:
                    v = et.verdict(sym, cls, exchange=ex, now=at, events=[])
                    if v["code"] != et.SHUT or v["until"] is None:
                        continue
                    checked += 1
                    days.add(at.weekday())
                    got = token.search(v["why"][:88])
                    if got is None or got.group(1) != (
                            f"{v['until'].astimezone(UTC):%H:%M}"):
                        wrong.append(f"{sym} at {at}: {v['why'][:88]!r}")
                    g1 = (morgul._shut(cls, ex, sym, at) and morgul._shut(
                        cls, ex, sym,
                        at - timedelta(seconds=morgul.CLOSE_GRACE_S)))
                    if ("Morgul G1 would flag" in v["why"]) != g1:
                        wrong.append(f"{sym} at {at}: G1 {g1}, words "
                                     f"{v['why']!r}")
                at += timedelta(minutes=20)
        self.assertEqual(wrong, [])
        self.assertEqual(days, set(range(7)))
        self.assertGreater(checked, 500)

    def test_a_resume_on_another_date_keeps_its_day(self):
        reopens = datetime(2026, 1, 13, 23, 50, tzinfo=UTC)
        v = et._shut_verdict("commodity", {"reopens": reopens,
                                           "session": "CME"})
        self.assertIn("resume Wednesday 00:05 UTC (CME hours: out of "
                      "session)", v["why"])
        v = et._shut_verdict("commodity", {"reopens": reopens - timedelta(
            hours=1), "session": ""}, flagged=True)
        self.assertTrue(v["why"].endswith(
            "resume 23:05 UTC (out of session, a fill Morgul G1 would "
            "flag)"), v["why"])

    def test_a_shut_exchange_with_no_known_reopening_still_refuses(self):
        clock = {"is_open": False, "modelled": True, "reopens": None,
                 "session": "NYSE", "reopens_words": "", "opened": None}
        with _on(), mock.patch("core.exchange_status.market_clock",
                               return_value=clock):
            v = et.verdict("PG", "stock", exchange="NYSE",
                           now=_ny(*WINTER_TUE, 10, 0), events=[])
        self.assertEqual(v["code"], et.SHUT)
        self.assertIsNone(v["until"])
        self.assertIn("resume once it opens and settles", v["why"])
        # the mocked clock is shut a grace before too: G1 would flag it
        self.assertIn("(NYSE hours: out of session, a fill Morgul G1 would "
                      "flag)", v["why"])

    def test_the_suite_switch_turns_shut_off_too(self):
        sat = datetime(2026, 1, 17, 12, 0, tzinfo=UTC)
        with mock.patch.object(et, "GATE", False):
            self.assertEqual(et.verdict("EURUSD", "forex", exchange="FOREX",
                                        now=sat, events=[]), et._open())
            self.assertIsNone(et.shut_verdict("EURUSD", "forex",
                                              exchange="FOREX", now=sat))
            self.assertIsNone(et.shut_verdict(
                "AAPL", "options", now=sat,
                classes=et.OPTIONS_SHUT_CLASSES))

    def test_skip_code_maps_shut_to_market_shut_and_every_other_window_to_bad_timing(self):
        from bot_program.asset_engine import skips
        self.assertEqual(et.skip_code({"code": et.SHUT}), skips.MARKET_SHUT)
        for code in (et.ROLLOVER, et.OPEN_SETTLE, et.CLOSE_GUARD,
                     et.WEEKEND, et.EVENT, ""):
            with self.subTest(code=code):
                self.assertEqual(et.skip_code({"code": code}),
                                 skips.BAD_TIMING)
        self.assertEqual(et.skip_code({}), skips.BAD_TIMING)
        self.assertEqual(et.skip_code(None), skips.BAD_TIMING)
        with _on():
            v = et.verdict("EURUSD", "forex", exchange="FOREX",
                           now=datetime(2026, 1, 17, 12, 0, tzinfo=UTC),
                           events=[])
        self.assertEqual(et.skip_code(v), skips.MARKET_SHUT)

    def test_the_options_key_is_judged_on_g1s_broker_classes(self):
        at = _ny(*WINTER_TUE, 3, 0)
        with _on():
            v = et.shut_verdict("AAPL", "options", now=at,
                                classes=et.OPTIONS_SHUT_CLASSES)
            self.assertEqual(v["code"], et.SHUT)
            self.assertIn("until Tuesday 14:30 UTC", v["why"])
            self.assertIsNone(et.shut_verdict("AAPL", "options", now=at,
                                              classes=et.SHUT_CLASSES))
            self.assertIsNone(et.shut_verdict(
                "SPX500", "index", now=at, classes=et.OPTIONS_SHUT_CLASSES))


# ── the calendar read, three hours deep ───────────────────────────────────

class TheCalendarHorizonTests(TestCase):

    def setUp(self):
        from market_data.models import EconomicEvent
        self.now = timezone.now()
        for minutes, title in ((30, "CPI"), (120, "FOMC"), (400, "Far")):
            EconomicEvent.objects.create(
                title=title, country="US", datetime=self.now + timedelta(
                    minutes=minutes), impact="high", currency_affected="USD",
                source="forexfactory")

    def test_the_default_window_and_the_deep_read_cache_apart(self):
        from bot_program import position_care as pc
        cache = {}
        near = pc.upcoming_events(self.now, cache=cache)
        self.assertEqual([e["title"] for e in near], ["CPI"])
        deep = pc.upcoming_events(self.now, cache=cache, horizon_minutes=180)
        self.assertEqual([e["title"] for e in deep], ["CPI", "FOMC"])
        self.assertEqual(set(cache), {pc.EVENT_CACHE_KEY,
                                      f"{pc.EVENT_CACHE_KEY}:180"})
        row = SimpleNamespace(symbol="EURUSD", asset_class="forex")
        self.assertEqual(pc.event_for(row, self.now, deep)["title"], "CPI")
        self.assertEqual(pc.event_for(row, self.now, deep[1:],
                                      before_minutes=180)["title"], "FOMC")
        self.assertIsNone(pc.event_for(row, self.now, deep[1:]))

    def test_the_verdict_reads_the_calendar_itself_when_given_none(self):
        # The wall clock: on a weekend EURUSD would answer SHUT (and in
        # the rollover, weekend and settle minutes the clock's own window)
        # before the calendar is read, so the clock is held open here
        # (2026-10-07): this test is about the calendar.
        with _on(), mock.patch.object(et, "clock_verdict",
                                      return_value=None):
            v = et.verdict("EURUSD", "forex", now=self.now, cache={})
            self.assertEqual(v["code"], et.EVENT)
            self.assertIn("CPI in 30 min", v["why"])


# ── the bot lane ──────────────────────────────────────────────────────────

REFUSED = {"ok": False, "code": "ROLLOVER", "why": "the forex market rolls "
           "over at 17:00 New York — new entries resume Tuesday 22:10 UTC",
           "until": None, "attack": None}
CAPPED = {"ok": True, "code": "", "why": "", "until": None,
          "attack": {"cap": "STANDARD",
                     "why": "attack capped at STANDARD: CPI in 120 min, "
                            "inside 3 h of a print"}}


class TheProposalIsRefusedOnTheClockTests(TestCase):

    def setUp(self):
        from tests.test_entry_quote import _book, _instrument, _live_cfg, _signal, _user
        from instruments.models import Instrument
        self.user = _user("tm_prop")
        self.cfg = _live_cfg(self.user, name="TM")
        inst = _instrument()
        # the venue travels with the symbol: the gate is asked on the
        # INSTRUMENT's class and exchange, the router's own key
        Instrument.objects.filter(pk=inst.pk).update(exchange="NASDAQ")
        _signal(inst, rule="tm_rule")
        _book(self.user)

    def _propose(self, verdict):
        from tests.test_entry_quote import ROUTER, _mock_client
        from bot_program.asset_engine.stock_bot import StockBot
        self.bot = StockBot(self.cfg)
        client = _mock_client("100.00")
        client.ticker.return_value = {"lastPrice": "100.00", "bid": "99.98",
                                      "ask": "100.02", "symbol": "AAPL"}
        with mock.patch(ROUTER, return_value=client), \
                mock.patch("bot_program.entry_timing.verdict",
                           return_value=verdict) as v:
            cand = self.bot.propose_entry("AAPL")
        return cand, v

    def test_a_refusal_is_a_bad_timing_skip_before_the_levels(self):
        from bot_program.asset_engine import skips
        with mock.patch("bot_program.asset_engine.risk_levels.stop_and_target"
                        ) as levels, \
                self.assertLogs("bot_program.asset_engine.base",
                                level="WARNING") as caught:
            cand, v = self._propose(REFUSED)
        self.assertIsNone(cand)
        levels.assert_not_called()
        self.assertIn("entry refused on the clock", "\n".join(caught.output))
        self.assertEqual(v.call_args.args[:2], ("AAPL", "stock"))
        self.assertEqual(v.call_args.kwargs["exchange"], "NASDAQ")
        self.cfg.refresh_from_db()
        note = skips.last_by_symbol(self.cfg)["AAPL"]
        self.assertEqual(note["code"], skips.BAD_TIMING)
        self.assertIn("rolls over at 17:00 New York", note["detail"])
        self.assertEqual(self.bot._timing_verdict["AAPL"], REFUSED)

    def test_an_open_verdict_proposes(self):
        cand, _v = self._propose({"ok": True, "code": "", "why": "",
                                  "until": None, "attack": None})
        self.assertIsNotNone(cand)


SHUT_VERDICT = {"ok": False, "code": "SHUT",
                "why": "the stock market is shut until Monday 13:30 UTC — new "
                       "entries resume 13:45 UTC (NYSE hours: out of "
                       "session, a fill Morgul G1 would flag)",
                "until": None, "attack": None}
OPEN_VERDICT = {"ok": True, "code": "", "why": "", "until": None,
                "attack": None}


class TheLiveEntryOnAShutExchangeTests(TestCase):
    """THE SHUT EXCHANGE in the bot lane and on the options lane's live
    branch (2026-10-07), at tests/test_paper_market_hours.py's Saturday
    with the clock gate ON: no live order leaves while the exchange is
    shut, and the skip is the one word for a shut market, market_shut."""

    def setUp(self):
        from tests.test_paper_market_hours import _user
        patcher = mock.patch.object(et, "GATE", True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.user = _user("tm_shut")

    def _last_skip(self, cfg, symbol):
        cfg.refresh_from_db()
        return ((cfg.extras or {}).get("skips") or {}).get(symbol) or {}

    def _live_seam(self):
        from signals.models import RuleControl
        from tests.test_paper_market_hours import _seam_cfg, _seam_signal
        RuleControl.objects.create(
            rule_name="mh_live_rule", status="active",
            promotion_stage="live_full", stage_entered_at=timezone.now())
        cfg = _seam_cfg(self.user, mode="live")
        _seam_signal("MHSEAM", rule="mh_live_rule")
        return cfg

    def test_a_live_stock_bot_sends_nothing_before_the_open(self):
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        from tests.test_paper_market_hours import ROUTER, SAT, _at, _client
        with _at(SAT):
            cfg = self._live_seam()
            client = _client()
            client.market_order.side_effect = RuntimeError("socket closed")
            with mock.patch(ROUTER, return_value=client):
                self.assertIsNone(StockBot(cfg).scan_symbol("MHSEAM"))
        client.market_order.assert_not_called()
        self.assertEqual(AssetBotTrade.objects.count(), 0)
        skip = self._last_skip(cfg, "MHSEAM")
        self.assertEqual(skip.get("code"), "market_shut")
        self.assertTrue(skip.get("detail", "").startswith(
            "the stock market is shut until Monday 13:30 UTC — new entries "
            "resume 13:45 UTC"), skip)

    def test_the_send_is_refused_when_the_exchange_shuts_after_the_proposal(self):
        from bot_program.asset_engine import StockBot, skips
        from bot_program.models import AssetBotTrade
        from tests.test_paper_market_hours import ROUTER, SAT, _at, _client
        with _at(SAT):
            cfg = self._live_seam()
            client = _client()
            client.market_order.side_effect = RuntimeError("socket closed")
            bot = StockBot(cfg)
            with mock.patch(ROUTER, return_value=client):
                with mock.patch("bot_program.entry_timing.verdict",
                                return_value=OPEN_VERDICT):
                    cand = bot.propose_entry("MHSEAM")
                self.assertIsNotNone(cand)
                # the read before the debate, then the one after the last
                # look: the exchange shut in between
                with mock.patch("bot_program.entry_timing.verdict",
                                side_effect=[OPEN_VERDICT, SHUT_VERDICT]) as v:
                    self.assertIsNone(bot.execute_entry(cand))
        self.assertEqual(v.call_count, 2)
        client.market_order.assert_not_called()
        self.assertEqual(AssetBotTrade.objects.count(), 0)
        skip = self._last_skip(cfg, "MHSEAM")
        self.assertEqual(skip.get("code"), skips.MARKET_SHUT)
        self.assertIn("shut until Monday 13:30 UTC", skip.get("detail", ""))

    def test_a_paper_config_still_hears_the_paper_venue_first(self):
        from bot_program.asset_engine import StockBot
        from tests.test_paper_market_hours import (
            SAT, _at, _quote, _seam_cfg, _seam_signal,
        )
        with _at(SAT):
            cfg = _seam_cfg(self.user)
            _quote(_seam_signal("MHSEAM").instrument, "150",
                   source="yfinance")
            StockBot(cfg).scan_symbol("MHSEAM")
        skip = self._last_skip(cfg, "MHSEAM")
        self.assertEqual(skip.get("code"), "market_shut")
        self.assertTrue(skip.get("detail", "").endswith(" — no paper fill"),
                        skip)
        self.assertIn("the stock market is shut (reopens Monday 13:30 UTC)",
                      skip.get("detail", ""))
        self.assertNotIn("new entries resume", skip.get("detail", ""))

    def _scan_options(self, when, name, client):
        from bot_program.asset_engine.base import BotDecision
        from bot_program.asset_engine.options_bot import OptionsBot
        from bot_program.models import AssetBotConfig
        from bot_program.options_models import OptionContract
        from portfolio.risk_gate import limits_book
        from tests.test_paper_market_hours import ROUTER, _at, _inst
        with _at(when):
            pf = limits_book()
            pf.current_value = Decimal("10000")
            pf.max_single_position_pct = 100.0
            pf.save()
            inst = _inst("AAPL", "stock")
            cfg = AssetBotConfig.objects.create(
                user=self.user, asset_class="options", name=name,
                enabled=True, mode="live", symbols=["AAPL"],
                capital=Decimal("1000000"), stop_loss_pct=20.0,
                take_profit_pct=50.0)
            OptionContract.objects.get_or_create(
                underlying=inst, strike=Decimal("180"),
                expiry=timezone.now().date() + timedelta(days=30), right="C",
                defaults=dict(multiplier=100, bid=Decimal("1.00"),
                              ask=Decimal("1.02"), last_price=Decimal("1.01"),
                              iv=0.30, delta=0.41))
            bot = OptionsBot(cfg)
            corr = {"scale": 1.0, "max_corr": 0.0, "peer": "",
                    "threshold": 0.7, "measured": True, "reason": ""}
            with mock.patch.object(bot, "decide", return_value=BotDecision(
                    "BUY", 0.9, ["signal"])), \
                    mock.patch(ROUTER, return_value=client), \
                    mock.patch("portfolio.risk_gate.correlation_state",
                               return_value=corr):
                return cfg, bot.scan_symbol("AAPL")

    def test_a_live_options_entry_sends_nothing_while_the_underlying_is_shut(self):
        from unittest.mock import MagicMock
        from bot_program.models import AssetBotTrade
        from tests.test_paper_market_hours import MON_NYSE, SAT
        client = MagicMock(name="fake_live_options_client")
        client.market_order_option.side_effect = RuntimeError("socket closed")
        cfg, out = self._scan_options(SAT, "tm_opt_sat", client)
        self.assertIsNone(out)
        client.market_order_option.assert_not_called()
        client.market_order.assert_not_called()
        self.assertFalse(AssetBotTrade.objects.exists())
        skip = self._last_skip(cfg, "AAPL")
        self.assertEqual(skip.get("code"), "market_shut")
        self.assertIn("the stock market is shut until Monday 13:30 UTC",
                      skip.get("detail", ""))
        # in session the clock lets it through to the venue (which raises
        # here, so nothing is booked either way)
        _cfg, out = self._scan_options(MON_NYSE, "tm_opt_mon", client)
        self.assertIsNone(out)
        client.market_order_option.assert_called_once()
        self.assertFalse(AssetBotTrade.objects.exists())


class TheAttackIsCappedBeforeAPrintTests(TestCase):

    def setUp(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from tests.test_attack_mode import _instrument, _live_cfg, _user
        self.user = _user("tm_cap")
        _instrument("AAPL", "stock")
        self.cfg = _live_cfg(self.user, name="TMC")
        self.cfg.extras = {"leverage": "auto", "risk_per_trade_pct": 7}
        self.cfg.save(update_fields=["extras"])
        self.bot = StockBot(self.cfg)

    def _tier(self, score, verdict):
        from tests.test_attack_mode import DETAIL, _decision, _record
        self.bot._timing_verdict = {"AAPL": verdict}
        with mock.patch(DETAIL, return_value=_record(40, 0.60, 0.35)):
            return self.bot._attack_tier("AAPL", _decision(score))

    def test_a_strong_or_high_score_is_held_at_standard(self):
        for score in (0.80, 0.95):
            with self.subTest(score=score):
                out = self._tier(score, CAPPED)
                self.assertEqual((out["tier"], out["capped"]),
                                 ("STANDARD", True))
                self.assertAlmostEqual(out["risk_fraction"], 0.035)
                self.assertIn("attack capped at STANDARD: CPI in 120 min",
                              out["why"])

    def test_nothing_changes_without_a_cap_or_on_a_standard_score(self):
        out = self._tier(0.95, {"ok": True, "attack": None})
        self.assertEqual((out["tier"], out["capped"]), ("HIGH", False))
        out = self._tier(0.70, CAPPED)
        self.assertEqual((out["tier"], out["capped"]), ("STANDARD", False))
        self.bot._timing_verdict = {}
        self.assertEqual(self._tier(0.95, None)["tier"], "HIGH")


class TheWiringTests(SimpleTestCase):

    def test_the_gate_sits_after_the_quote_and_before_the_cost(self):
        import inspect
        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.propose_entry)
        quote = src.index("self._entry_quote_gate(symbol, tk, client)")
        gate = src.index("self._entry_timing_gate(symbol)")
        cost = src.index("charge = cost_to_charge(self.cfg, symbol, tk)")
        self.assertLess(quote, gate)
        self.assertLess(gate, cost)
        src = inspect.getsource(AssetBot.execute_entry)
        # before the billed debate (review 2026-10-06), and again on the
        # fresh clock after the last look, just before the order
        first = src.index("self._entry_timing_gate(symbol)")
        debate = src.index("debate_candidate(self, cand, qty)")
        look = src.index("self._last_look(client, symbol, decision.direction,")
        again = src.rindex("self._entry_timing_gate(symbol)")
        order = src.index("order_kwargs = {")
        self.assertLess(first, debate)
        self.assertLess(look, again)
        self.assertLess(again, order)
        self.assertNotEqual(first, again)

    def test_the_skip_code_has_its_advice_and_its_words(self):
        import inspect
        from bot_program.asset_engine import skips
        from bot_program.telegram_eye import SKIP_WORDS
        self.assertEqual(skips.BAD_TIMING, "bad_timing")
        self.assertIn("BAD_TIMING:", inspect.getsource(skips.diagnose))
        self.assertIn("bad_timing", SKIP_WORDS)
        self.assertIn("clock said no", SKIP_WORDS["bad_timing"])

    def test_the_suite_switch_is_declared_beside_the_paper_gates(self):
        from pathlib import Path
        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "tests" / "__init__.py").read_text(
            encoding="utf-8")
        self.assertIn("_entry_timing.GATE = False", src)

    def test_market_shut_words_cover_a_live_entry(self):
        """2026-10-07: a live entry refused on a shut exchange is recorded
        as market_shut, so its advice and its Telegram words name the live
        lane too; every refusal on the clock goes through skip_code, and
        the options lane asks the clock before it is re-armed and sends."""
        import inspect
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.base import AssetBot
        from bot_program.asset_engine.options_bot import OptionsBot
        from bot_program.telegram_eye import SKIP_WORDS
        advice = inspect.getsource(skips.diagnose)
        self.assertIn("no live entry", advice)
        self.assertIn("nothing is wrong with the feed", advice)
        self.assertIn("no live entry", SKIP_WORDS["market_shut"])
        src = (inspect.getsource(AssetBot.propose_entry)
               + inspect.getsource(AssetBot.execute_entry))
        self.assertEqual(src.count("entry_timing.skip_code(_timing)"), 3)
        self.assertNotIn("skips.BAD_TIMING, _timing", src)
        # Review 2026-10-07: the order is read off the CALLS (ast), never
        # the first textual match, which a comment satisfies: the
        # shut_verdict call, asked with OPTIONS_SHUT_CLASSES, comes before
        # the re-arm check and before the order.
        import ast
        import textwrap
        tree = ast.parse(textwrap.dedent(
            inspect.getsource(OptionsBot.scan_symbol)))
        calls = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func,
                                                         ast.Attribute):
                calls.setdefault(node.func.attr, []).append(node)
        self.assertEqual(len(calls.get("shut_verdict", [])), 1)
        shut = calls["shut_verdict"][0]
        kw = {k.arg: k.value for k in shut.keywords}
        self.assertIsInstance(kw.get("classes"), ast.Attribute)
        self.assertEqual(kw["classes"].attr, "OPTIONS_SHUT_CLASSES")
        armed = [c for c in calls.get("_still_armed", [])
                 if isinstance(c.func.value, ast.Name)
                 and c.func.value.id == "self"]
        self.assertTrue(armed)
        self.assertLess(shut.lineno, min(c.lineno for c in armed))
        self.assertLess(shut.lineno, min(
            c.lineno for c in calls.get("market_order_option", [])))


# ── the manual lane ───────────────────────────────────────────────────────

class TheManualLaneTests(SimpleTestCase):

    def test_the_advisory_warns_and_never_refuses(self):
        from bot_program.manual_trade import timing_advisory
        inst = SimpleNamespace(symbol="EURUSD", asset_class="forex",
                               exchange="FOREX")
        with mock.patch("bot_program.entry_timing.verdict",
                        return_value=REFUSED) as v:
            adv = timing_advisory(inst)
        self.assertEqual(adv, {"ok": False, "reason": REFUSED["why"],
                               "attack": "", "code": "ROLLOVER"})
        self.assertEqual(v.call_args.args, ("EURUSD", "forex"))
        self.assertEqual(v.call_args.kwargs["exchange"], "FOREX")
        with mock.patch("bot_program.entry_timing.verdict",
                        side_effect=RuntimeError("x")):
            self.assertTrue(timing_advisory(inst)["ok"])

    def test_the_preview_the_booking_and_the_popup_carry_it_without_blocking(self):
        from pathlib import Path
        from django.conf import settings
        base = Path(settings.BASE_DIR)
        manual = (base / "bot_program" / "manual_trade.py").read_text(
            encoding="utf-8")
        self.assertIn('"timing_advisory": timing_advisory(inst),', manual)
        self.assertIn('extra["timing_advisory_at_entry"]', manual)
        html = (base / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertIn("p.timing_advisory", html)
        self.assertIn("BAD TIMING FOR AN ENTRY", html)
        self.assertIn("A warning, not a block: the bots refuse an entry at",
                      html)
        expr = html.split("okBtn.disabled = ", 1)[1].split(";", 1)[0]
        self.assertNotIn("timingAdv", expr)
        self.assertNotIn("timing_advisory", expr)

    def test_the_ticket_warns_on_a_shut_exchange_and_stays_pressable(self):
        """2026-10-07: a live ticket on a shut exchange is warned with its
        own heading, never refused. Review 2026-10-07: the footer says only
        what is always true (G1 flags a booking only past its grace, and
        only while morgul_guards is ON)."""
        from pathlib import Path
        from django.conf import settings
        from bot_program.manual_trade import timing_advisory
        from tests.test_paper_market_hours import SAT
        inst = SimpleNamespace(symbol="PG", asset_class="stock",
                               exchange="NYSE")
        with _on(), mock.patch("django.utils.timezone.now",
                               return_value=SAT):
            adv = timing_advisory(inst)
        self.assertFalse(adv["ok"])
        self.assertEqual(adv["code"], "SHUT")
        self.assertIn("shut until Monday 13:30 UTC", adv["reason"])
        base = Path(settings.BASE_DIR)
        html = (base / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertIn("THE MARKET IS SHUT", html)
        import re
        joined = re.sub(r"'\s*\+\s*'", "", html)    # the JS literals, joined
        self.assertIn("A warning, not a block: the bots send no entry while "
                      "its exchange is shut; this ticket is yours to send.",
                      joined)
        self.assertNotIn("Morgul flags a", joined)
        expr = html.split("okBtn.disabled = ", 1)[1].split(";", 1)[0]
        self.assertNotIn("timingAdv", expr)
        manual = (base / "bot_program" / "manual_trade.py").read_text(
            encoding="utf-8")
        self.assertIn('"code": str(_ta.get("code") or "")', manual)
