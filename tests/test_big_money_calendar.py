"""The Big Money Board's calendar: business days and the forced flows,
with frozen dates (spec bigmoney/spec.md §2.4 R2, §2.13).

Every date pinned here was computed by hand on 2026-10-09 from the rule the
spec names, and the announced ones carry the URL they were read from.

Run with:  python manage.py test tests.test_big_money_calendar
"""
from datetime import date, datetime
from datetime import timezone as dt_tz

from django.test import SimpleTestCase, TestCase

from bigmoney import calendar as bmcal
from bigmoney import words as W

UTC = dt_tz.utc


def table_cal():
    """No tape: the NYSE table (2026-2027), weekdays past it."""
    return bmcal.BusinessCalendar(())


class ExpiryTests(SimpleTestCase):

    def test_third_fridays(self):
        cal = table_cal()
        self.assertEqual([bmcal.monthly_expiry(2026, m, cal) for m in (10, 11, 12)],
                         [date(2026, 10, 16), date(2026, 11, 20), date(2026, 12, 18)])

    def test_vix_expiries_are_30_days_before_the_next_third_friday(self):
        cal = table_cal()
        self.assertEqual([bmcal.vix_expiry(2026, m, cal) for m in (10, 11, 12)],
                         [date(2026, 10, 21), date(2026, 11, 18), date(2026, 12, 16)])
        for m in (10, 11, 12):
            self.assertEqual(bmcal.vix_expiry(2026, m, cal).weekday(), 2)

    def test_a_holiday_expiry_moves_to_the_business_day_before(self):
        cal = bmcal.BusinessCalendar(())
        # 2027-03-26 is Good Friday in the NYSE table; March's third
        # Friday is the 19th, so a synthetic check on a holiday Friday:
        self.assertFalse(cal.is_business_day(date(2027, 3, 26)))
        self.assertEqual(bmcal._on_or_before(date(2027, 3, 26), cal),
                         date(2027, 3, 25))


class WindowTests(SimpleTestCase):

    def test_the_month_end_rebalancing_windows(self):
        cal = table_cal()
        self.assertEqual(cal.window(2026, 10, "rebalance"),
                         [date(2026, 10, d) for d in (26, 27, 28, 29, 30)])
        # Thanksgiving (Thu 26 Nov) skipped:
        self.assertEqual(cal.window(2026, 11, "rebalance"),
                         [date(2026, 11, d) for d in (23, 24, 25, 27, 30)])
        self.assertEqual(cal.window(2026, 12, "rebalance"),
                         [date(2026, 12, d) for d in (24, 28, 29, 30, 31)])

    def test_the_reversal_windows(self):
        cal = table_cal()
        self.assertEqual(cal.window(2026, 11, "reversal"),
                         [date(2026, 11, d) for d in (2, 3, 4, 5, 6)])
        self.assertEqual(cal.window(2026, 12, "reversal"),
                         [date(2026, 12, d) for d in (1, 2, 3, 4, 7)])
        self.assertEqual(cal.window(2027, 1, "reversal"),
                         [date(2027, 1, d) for d in (4, 5, 6, 7, 8)])

    def test_the_fx_fix_windows(self):
        cal = table_cal()
        self.assertEqual(cal.window(2026, 10, "fx_fix"),
                         [date(2026, 10, 29), date(2026, 10, 30)])
        self.assertEqual(cal.window(2026, 11, "fx_fix"),
                         [date(2026, 11, 27), date(2026, 11, 30)])
        self.assertEqual(cal.window(2026, 12, "fx_fix"),
                         [date(2026, 12, 30), date(2026, 12, 31)])

    def test_month_ends(self):
        cal = table_cal()
        self.assertEqual([cal.last_business_day(2026, m) for m in (10, 11, 12)],
                         [date(2026, 10, 30), date(2026, 11, 30), date(2026, 12, 31)])


class DeadlineTests(SimpleTestCase):

    def test_the_13f_deadline_rolls_to_monday(self):
        self.assertEqual(bmcal.thirteen_f_deadline(date(2026, 9, 30), table_cal()),
                         date(2026, 11, 16))

    def test_financing_estimates_the_monday_before_the_refunding(self):
        self.assertEqual(bmcal.financing_estimates(date(2026, 11, 4)),
                         date(2026, 11, 2))

    def test_the_cot_bound_and_the_delayed_releases(self):
        self.assertEqual(bmcal.cot_bound(date(2026, 9, 29)), 10)
        self.assertEqual(bmcal.cot_bound(date(2026, 11, 3)), 14)    # Nov 16
        self.assertEqual(bmcal.cot_bound(date(2026, 11, 17)), 14)   # Nov 30
        self.assertEqual(bmcal.cot_bound(date(2026, 12, 15)), 14)   # Dec 28
        self.assertEqual(bmcal.cot_release(date(2026, 11, 10)), date(2026, 11, 16))
        self.assertEqual(bmcal.cot_release(date(2026, 10, 6)), date(2026, 10, 9))


class EventsTests(SimpleTestCase):

    def _events(self, start=date(2026, 10, 9), days=90):
        evs, reasons = bmcal.events(start, days, table_cal())
        return evs, reasons

    def _on(self, evs, event):
        return [e["date"] for e in evs if e["event"] == event]

    def test_the_computed_rows(self):
        evs, _ = self._events()
        self.assertEqual(self._on(evs, W.EV_MONTH_END),
                         ["2026-10-30", "2026-11-30", "2026-12-31"])
        self.assertEqual(self._on(evs, W.EV_QUARTER_END), ["2026-12-31"])
        self.assertEqual(self._on(evs, W.EV_OPEX), ["2026-10-16", "2026-11-20"])
        self.assertEqual(self._on(evs, W.EV_QUARTERLY_OPEX), ["2026-12-18"])
        self.assertEqual(self._on(evs, W.EV_NDX_RECON), ["2026-12-18"])
        self.assertEqual(self._on(evs, W.EV_SP500_REBALANCE), ["2026-12-18"])
        self.assertEqual(self._on(evs, W.EV_VIX_EXPIRY),
                         ["2026-10-21", "2026-11-18", "2026-12-16"])
        self.assertEqual(self._on(evs, W.EV_13F), ["2026-11-16"])
        self.assertEqual(self._on(evs, W.EV_TAX_DATE), ["2026-12-15"])
        self.assertEqual(self._on(evs, W.EV_FINANCING), ["2026-11-02"])
        self.assertEqual(self._on(evs, W.EV_REBALANCE_OPENS)[:2],
                         ["2026-10-26", "2026-11-23"])
        self.assertEqual(self._on(evs, W.EV_REVERSAL_OPENS)[:2],
                         ["2026-11-02", "2026-12-01"])

    def test_the_tax_dates_are_the_corporate_estimates(self):
        """Calendar-year corporations pay on the 15th of April, June,
        September and December (26 U.S.C. 6655(c)(2)); mid-March is the
        S-corporation return date and moves little cash."""
        evs, _ = self._events(start=date(2027, 3, 1), days=200)
        self.assertEqual(self._on(evs, W.EV_TAX_DATE),
                         ["2027-04-15", "2027-06-15", "2027-09-15"])
        self.assertNotIn("2027-03-15", self._on(evs, W.EV_TAX_DATE))
        # The 13F deadline still follows the quarter's end.
        self.assertIn("2027-05-17", self._on(evs, W.EV_13F))

    def test_cot_fridays_give_way_to_the_delayed_mondays(self):
        evs, _ = self._events()
        fridays = self._on(evs, W.EV_COT)
        self.assertIn("2026-10-09", fridays)
        self.assertNotIn("2026-11-13", fridays)
        self.assertNotIn("2026-11-27", fridays)
        self.assertEqual(self._on(evs, W.EV_COT_DELAYED),
                         ["2026-11-16", "2026-11-30", "2026-12-28"])

    def test_only_the_forced_flows_carry_a_direction(self):
        evs, _ = self._events()
        directional = {e["event"] for e in evs if e["directional"]}
        self.assertEqual(directional, {W.EV_REBALANCE_OPENS, W.EV_REVERSAL_OPENS,
                                       W.EV_FX_FIX_OPENS})
        plays = {e["event"]: e["play"] for e in evs}
        self.assertEqual(plays[W.EV_FOMC], W.PLAY_EVENT_RISK)
        self.assertEqual(plays[W.EV_REFUNDING], W.PLAY_EVENT_RISK)
        self.assertEqual(plays[W.EV_RUSSELL_RANK], W.PLAY_INDEX)
        self.assertEqual(plays[W.EV_REBALANCE_OPENS], W.PLAY_REBALANCE)
        self.assertEqual(plays[W.EV_FX_FIX_OPENS], W.PLAY_FX_FIX)

    def test_a_trend_trigger_is_an_estimate(self):
        evs, _ = bmcal.events(date(2026, 10, 9), 30, table_cal(),
                              triggers=[(date(2026, 10, 12), "gold", "Gold")])
        trig = [e for e in evs if e["kind"] == "estimate"]
        self.assertEqual(trig[0]["event"], "Trend followers' trigger on Gold")
        self.assertEqual(trig[0]["play"], W.PLAY_TREND)
        self.assertTrue(trig[0]["directional"])

    def test_the_window_is_bounded(self):
        evs, _ = bmcal.events(date(2026, 10, 9), 30, table_cal())
        self.assertTrue(all("2026-10-09" <= e["date"] <= "2026-11-08" for e in evs))
        self.assertEqual(evs, sorted(evs, key=lambda e: (e["date"], e["event"])))

    def test_every_announced_row_carries_a_url_and_a_check_date(self):
        for a in bmcal.ANNOUNCED:
            self.assertTrue(a["source_url"].startswith("https://"), a)
            self.assertIn(a["checked"], ("2026-10-08", "2026-10-09"), a)
            self.assertTrue(a["rows"], a)
        evs, _ = self._events()
        for e in evs:
            if e["kind"] == "announced":
                self.assertTrue(e["source_url"] and e["checked"], e)

    def test_the_runway_warning(self):
        _, reasons = bmcal.events(date(2026, 10, 9), 30, table_cal())
        self.assertEqual(reasons, [])
        _, reasons = bmcal.events(date(2026, 12, 1), 30, table_cal())
        self.assertEqual(reasons, ["calendar: announced dates end on 2026-12-28; "
                                   "computed dates only after it"])


class BusinessDayTests(SimpleTestCase):

    def test_past_business_days_come_from_the_tape(self):
        tape = [date(2025, 7, 2), date(2025, 7, 3), date(2025, 7, 7),
                date(2025, 7, 9)]                       # no 4 Jul, no 8 Jul
        cal = bmcal.BusinessCalendar(tape)
        self.assertFalse(cal.is_business_day(date(2025, 7, 4)))
        self.assertFalse(cal.is_business_day(date(2025, 7, 8)))  # a hole
        self.assertEqual(cal.prev_business_day(date(2025, 7, 9)), date(2025, 7, 7))
        self.assertEqual(cal.next_business_day(date(2025, 7, 3)), date(2025, 7, 7))
        self.assertEqual(cal.business_days_between(date(2025, 7, 2),
                                                   date(2025, 7, 9)), 3)
        self.assertEqual(cal.gaps(), [])
        # After the tape: the NYSE table (Thanksgiving 2026 is shut).
        self.assertFalse(cal.is_business_day(date(2026, 11, 26)))
        self.assertTrue(cal.is_business_day(date(2026, 11, 27)))

    def test_a_long_hole_in_the_tape_is_named(self):
        cal = bmcal.BusinessCalendar([date(2026, 3, 2), date(2026, 3, 10)])
        self.assertEqual(cal.gaps(), [(date(2026, 3, 2), date(2026, 3, 10), 8)])

    def test_past_2027_weekdays_count_and_it_is_said(self):
        cal = table_cal()
        self.assertTrue(cal.is_business_day(date(2028, 1, 3)))
        self.assertIn(W.R_HOLIDAYS_END, cal.reasons)

    def test_the_h_th_business_day_across_thanksgiving(self):
        cal = table_cal()
        self.assertEqual(cal.add_business_days(date(2026, 11, 25), 1),
                         date(2026, 11, 27))
        self.assertEqual(cal.add_business_days(date(2026, 11, 24), 3),
                         date(2026, 11, 30))

    def test_as_of_is_the_last_close_that_has_passed(self):
        cal = table_cal()
        self.assertEqual(bmcal.as_of_for(datetime(2026, 10, 9, 5, 20, tzinfo=UTC), cal),
                         date(2026, 10, 8))
        self.assertEqual(bmcal.as_of_for(datetime(2026, 10, 9, 23, 20, tzinfo=UTC), cal),
                         date(2026, 10, 9))
        self.assertEqual(bmcal.as_of_for(datetime(2026, 10, 12, 5, 20, tzinfo=UTC), cal),
                         date(2026, 10, 9))
        self.assertEqual(bmcal.as_of_for(datetime(2026, 11, 27, 5, 20, tzinfo=UTC), cal),
                         date(2026, 11, 25))


class TapeFromTheDatabaseTests(TestCase):

    def test_the_tape_reads_spx500_daily_bars_on_their_own_days(self):
        from tests.test_big_money_board import seed_closes, weekdays
        days = weekdays(date(2026, 9, 1), date(2026, 9, 30),
                        skip=(date(2026, 9, 7),))
        seed_closes("SPX500", {d: 100.0 for d in days})
        cal = bmcal.BusinessCalendar.from_db()
        self.assertEqual(cal.tape_first, date(2026, 9, 1))
        self.assertEqual(cal.tape_last, date(2026, 9, 30))
        self.assertFalse(cal.is_business_day(date(2026, 9, 7)))   # Labor Day
        self.assertEqual(cal.next_business_day(date(2026, 9, 4)),
                         date(2026, 9, 8))
        self.assertEqual(cal.next_business_day(date(2026, 9, 30)),
                         date(2026, 10, 1))
        self.assertEqual(cal.add_business_days(date(2026, 9, 29), 3),
                         date(2026, 10, 2))
        self.assertTrue(all(cal.is_business_day(d) for d in days))
        self.assertEqual(len(cal.month_days(2026, 9)), len(days))
        self.assertEqual(cal.prev_business_day(date(2026, 9, 1)),
                         date(2026, 8, 31))
