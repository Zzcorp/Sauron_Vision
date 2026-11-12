"""The market clock behind a signal's announcement (2026-11-12).

The operator, 2026-11-11: signals were announced while their market was
shut ("please fix it"). Nothing that wrote, announced or showed a signal
asked the market clock; the bots, the paper venue, Morgul and the ticket
already did.

signals/market_hold.py is the one place a signal's announcement and its
card ask "can this instrument trade now": market_state(instrument), on
core.exchange_status.market_clock, with the classes on which the bots
already refuse a shut market (entry_timing.SHUT_CLASSES) and the bots'
own settling quarter hour (entry_timing.OPEN_SETTLE_MINUTES). It adds no
clock of its own.

Pinned here, at fixed instants (November for winter hours, July for
summer), with no database:
  * crypto and an unmodelled class never read shut; a clock that cannot
    be read holds nothing and says so at WARNING;
  * forex, a US share (a holiday and an early close among them), gold on
    COMEX and an index: shut, settling and open, with the hour the market
    opens and the hour it can be traded;
  * an index is shut only while its cash session AND the CME futures week
    are both shut;
  * the class set and the settle are the bots' own;
  * the label a shut market is announced with: "market shut · opens Sun
    22:00 UTC", "market shut" alone when the clock does not know the hour,
    nothing while the market is open (its first quarter hour included);
  * GATE off (the suite's default, tests/__init__.py): nothing reads shut.

Run with:  python manage.py test tests.test_signal_market_hold
"""
from contextlib import contextmanager
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

UTC = dt_timezone.utc


def _t(*parts):
    return datetime(*parts, tzinfo=UTC)


#: Winter hours (the US clocks changed on 2026-11-01).
SAT_0005 = _t(2026, 11, 7, 0, 5)
SAT_NOON = _t(2026, 11, 7, 12, 0)
SUN_2130 = _t(2026, 11, 8, 21, 30)
SUN_2205 = _t(2026, 11, 8, 22, 5)
SUN_2220 = _t(2026, 11, 8, 22, 20)
SUN_OPEN = _t(2026, 11, 8, 22, 0)
MON_0900 = _t(2026, 11, 9, 9, 0)
MON_1000 = _t(2026, 11, 9, 10, 0)
MON_BELL = _t(2026, 11, 9, 14, 30)
TUE_0300 = _t(2026, 11, 10, 3, 0)
TUE_2230 = _t(2026, 11, 10, 22, 30)
THANKSGIVING = _t(2026, 11, 26, 15, 0)
EARLY_CLOSE = _t(2026, 11, 27, 18, 30)
#: Summer hours.
JUL_SAT = _t(2026, 7, 11, 0, 5)
JUL_SUN_2030 = _t(2026, 7, 12, 20, 30)
JUL_SUN_2105 = _t(2026, 7, 12, 21, 5)
JUL_SUN_2120 = _t(2026, 7, 12, 21, 20)
JUL_OPEN = _t(2026, 7, 12, 21, 0)

QUARTER = timedelta(minutes=15)


def _inst(symbol, asset_class, exchange=""):
    """An instrument as market_state reads it: three attributes."""
    return SimpleNamespace(symbol=symbol, asset_class=asset_class,
                           exchange=exchange)


EURUSD = _inst("EURUSD", "forex")
AAPL = _inst("AAPL", "stock", "NASDAQ")
SPY = _inst("SPY", "etf", "NYSE")
XAUUSD = _inst("XAUUSD", "commodity", "COMEX")
SPX500 = _inst("SPX500", "index")
BTCUSD = _inst("BTCUSD", "crypto")


@contextmanager
def _at(when, gate=True):
    """The wall clock fixed at `when`, and the gate ON (the suite runs
    with it off, tests/__init__.py)."""
    from signals import market_hold
    with patch("django.utils.timezone.now", return_value=when), \
            patch.object(market_hold, "GATE", gate):
        yield


def _state(inst, when, gate=True):
    from signals.market_hold import market_state
    with _at(when, gate):
        return market_state(inst)


class TheClockTests(SimpleTestCase):
    def test_1_crypto_on_a_saturday_is_never_held(self):
        st = _state(BTCUSD, SAT_NOON)
        self.assertEqual((st["state"], st["tradeable"]), ("always", True))
        self.assertEqual((st["label"], st["words"]), ("", ""))

    def test_2_forex_over_the_weekend_in_winter(self):
        st = _state(EURUSD, SAT_0005)
        self.assertEqual((st["state"], st["tradeable"]), ("shut", False))
        self.assertEqual(st["reopens"], SUN_OPEN)
        self.assertEqual(st["tradeable_at"], SUN_OPEN + QUARTER)
        self.assertEqual(st["session"], "FOREX")
        self.assertIn("opens Sunday 22:00 UTC", st["words"])
        # Sunday 21:30: the UTC row reads open, the New York week does not
        st = _state(EURUSD, SUN_2130)
        self.assertEqual((st["state"], st["reopens"]), ("shut", SUN_OPEN))
        st = _state(EURUSD, SUN_2205)
        self.assertEqual((st["state"], st["tradeable"]), ("settling", False))
        self.assertEqual(st["opened"], SUN_OPEN)
        self.assertEqual(st["tradeable_at"], SUN_OPEN + QUARTER)
        self.assertIsNone(st["reopens"])
        st = _state(EURUSD, SUN_2220)
        self.assertEqual((st["state"], st["tradeable"]), ("open", True))
        self.assertEqual(st["opened"], SUN_OPEN)
        self.assertEqual(st["words"], "")

    def test_2_forex_over_the_weekend_in_summer(self):
        st = _state(EURUSD, JUL_SAT)
        self.assertEqual((st["state"], st["reopens"]), ("shut", JUL_OPEN))
        self.assertEqual(st["tradeable_at"], JUL_OPEN + QUARTER)
        self.assertEqual(_state(EURUSD, JUL_SUN_2030)["state"], "shut")
        self.assertEqual(_state(EURUSD, JUL_SUN_2105)["state"], "settling")
        self.assertEqual(_state(EURUSD, JUL_SUN_2120)["state"], "open")

    def test_3_a_us_share_before_the_bell_on_a_holiday_and_after_an_early_close(
            self):
        st = _state(AAPL, MON_0900)
        self.assertEqual((st["state"], st["reopens"]), ("shut", MON_BELL))
        self.assertEqual(st["tradeable_at"], MON_BELL + QUARTER)
        self.assertEqual(_state(AAPL, MON_BELL + timedelta(minutes=5))["state"],
                         "settling")
        self.assertEqual(_state(AAPL, MON_BELL + timedelta(minutes=20))["state"],
                         "open")
        # Thanksgiving: shut all day, until Friday's bell
        st = _state(AAPL, THANKSGIVING)
        self.assertEqual((st["state"], st["reopens"]),
                         ("shut", _t(2026, 11, 27, 14, 30)))
        # the Friday after: the 13:00 New York close has passed
        st = _state(AAPL, EARLY_CLOSE)
        self.assertEqual((st["state"], st["reopens"]),
                         ("shut", _t(2026, 11, 30, 14, 30)))
        # an ETF reads its venue the same way
        self.assertEqual(_state(SPY, MON_0900)["reopens"], MON_BELL)

    def test_4_gold_in_the_daily_break(self):
        st = _state(XAUUSD, TUE_2230)
        self.assertEqual((st["state"], st["reopens"]),
                         ("shut", _t(2026, 11, 10, 23, 0)))
        self.assertEqual(st["session"], "CME")

    def test_5_an_index_is_shut_only_when_cash_and_futures_both_are(self):
        # Tuesday 03:00 UTC: New York's cash session is shut, the futures
        # week is open, and the broker's index CFD trades
        st = _state(SPX500, TUE_0300)
        self.assertEqual((st["state"], st["tradeable"]), ("open", True))
        self.assertEqual(st["label"], "")
        # Saturday: both shut; the futures week opens first
        st = _state(SPX500, SAT_NOON)
        self.assertEqual((st["state"], st["tradeable"]), ("shut", False))
        self.assertEqual(st["reopens"], _t(2026, 11, 8, 23, 0))
        self.assertIn("opens Sunday 23:00 UTC", st["words"])
        # the futures' daily break, the cash session shut as well
        st = _state(SPX500, TUE_2230)
        self.assertEqual((st["state"], st["reopens"]),
                         ("shut", _t(2026, 11, 10, 23, 0)))
        # an index that is not American: said as an approximation
        st = _state(_inst("DAX40", "index"), SAT_NOON)
        self.assertEqual(st["state"], "shut")
        self.assertIn("approximation", st["words"])
        self.assertNotIn("approximation", _state(SPX500, SAT_NOON)["words"])

    def test_6_an_unmodelled_class_and_an_unread_clock_hold_nothing(self):
        for cls in ("cfd", "bond", "options", "", "something_new"):
            with self.subTest(asset_class=cls):
                st = _state(_inst("ANY", cls), SAT_NOON)
                self.assertEqual((st["state"], st["tradeable"]),
                                 ("unmodelled", True))
                self.assertEqual(st["label"], "")
        with patch("signals.market_hold.market_clock",
                   side_effect=RuntimeError("no calendar")), \
                self.assertLogs("signals.market_hold", "WARNING") as logs:
            st = _state(EURUSD, SAT_NOON)
        self.assertEqual((st["state"], st["tradeable"]), ("unmodelled", True))
        self.assertEqual(st["label"], "")
        self.assertIn("EURUSD", logs.output[0])
        # an instrument that carries nothing at all
        self.assertTrue(_state(SimpleNamespace(), SAT_NOON)["tradeable"])
        self.assertTrue(_state(None, SAT_NOON)["tradeable"])

    def test_7_the_classes_and_the_settle_are_the_bots_own(self):
        from bot_program import entry_timing
        from signals import market_hold
        self.assertEqual(market_hold.HOLD_CLASSES, entry_timing.SHUT_CLASSES)
        self.assertEqual(market_hold.SETTLE_MINUTES,
                         entry_timing.OPEN_SETTLE_MINUTES)
        self.assertEqual(market_hold.SETTLE,
                         timedelta(minutes=entry_timing.OPEN_SETTLE_MINUTES))

    def test_8_the_gate_off_holds_nothing(self):
        for inst in (EURUSD, AAPL, XAUUSD, SPX500, BTCUSD):
            with self.subTest(symbol=inst.symbol):
                st = _state(inst, SAT_NOON, gate=False)
                self.assertEqual((st["state"], st["tradeable"]), ("off", True))
                self.assertEqual((st["label"], st["words"]), ("", ""))

    def test_the_suite_runs_with_the_gate_off(self):
        """tests/__init__.py: without it a test that announces a signal
        would read the hour it runs at."""
        from signals import market_hold
        self.assertIs(market_hold.GATE, False)

    def test_an_explicit_moment_is_read_instead_of_the_wall_clock(self):
        from signals.market_hold import market_state
        with _at(MON_1000):
            self.assertEqual(market_state(EURUSD)["state"], "open")
            self.assertEqual(market_state(EURUSD, now=SAT_NOON)["state"],
                             "shut")


class TheLabelTests(SimpleTestCase):
    """What a shut market is announced with, on every channel and card."""

    def _label(self, inst, when, gate=True):
        from signals.market_hold import shut_label
        with _at(when, gate):
            return shut_label(inst)

    def test_a_shut_market_says_so_with_the_hour_it_opens(self):
        self.assertEqual(self._label(EURUSD, SAT_NOON),
                         "market shut · opens Sun 22:00 UTC")
        self.assertEqual(self._label(AAPL, MON_0900),
                         "market shut · opens Mon 14:30 UTC")
        self.assertEqual(self._label(AAPL, THANKSGIVING),
                         "market shut · opens Fri 14:30 UTC")
        self.assertEqual(self._label(XAUUSD, TUE_2230),
                         "market shut · opens Tue 23:00 UTC")
        self.assertEqual(self._label(SPX500, SAT_NOON),
                         "market shut · opens Sun 23:00 UTC")
        self.assertEqual(self._label(EURUSD, JUL_SAT),
                         "market shut · opens Sun 21:00 UTC")

    def test_the_state_carries_the_two_halves_of_the_label(self):
        st = _state(EURUSD, SAT_NOON)
        self.assertEqual(st["label"], "market shut · opens Sun 22:00 UTC")
        self.assertEqual(st["opens"], "opens Sun 22:00 UTC")

    def test_an_open_market_says_nothing(self):
        for inst, when in ((EURUSD, MON_1000), (BTCUSD, SAT_NOON),
                           (SPX500, TUE_0300),
                           (AAPL, MON_BELL + timedelta(minutes=20))):
            with self.subTest(symbol=inst.symbol):
                self.assertEqual(self._label(inst, when), "")

    def test_the_first_quarter_hour_is_an_open_market(self):
        """Settling is the hold's word (the announcement may wait for a
        market price); the market is open, so nothing says shut."""
        self.assertEqual(_state(EURUSD, SUN_2205)["state"], "settling")
        self.assertEqual(self._label(EURUSD, SUN_2205), "")
        self.assertEqual(_state(EURUSD, SUN_2205)["label"], "")

    def test_an_unknown_reopening_says_only_market_shut(self):
        clock = {"is_open": False, "session": "FOREX", "modelled": True,
                 "reopens": None, "reopens_words": "", "opened": None,
                 "closed": None}
        with patch("signals.market_hold.market_clock", return_value=clock):
            self.assertEqual(self._label(EURUSD, SAT_NOON), "market shut")
            st = _state(EURUSD, SAT_NOON)
        self.assertEqual((st["state"], st["opens"]), ("shut", ""))
        self.assertIsNone(st["tradeable_at"])

    def test_a_label_never_raises(self):
        from signals.market_hold import shut_label
        with patch("signals.market_hold.market_state",
                   side_effect=RuntimeError("boom")), \
                self.assertLogs("signals.market_hold", "WARNING"):
            with _at(SAT_NOON):
                self.assertEqual(shut_label(EURUSD), "")

    def test_the_gate_off_says_nothing(self):
        self.assertEqual(self._label(EURUSD, SAT_NOON, gate=False), "")

    def test_the_weekday_is_from_a_fixed_table(self):
        """No locale can change the words (core.exchange_status.utc_words
        does the same with the long names)."""
        from signals.market_hold import opens_words
        days = [opens_words(_t(2026, 11, 9 + i, 7, 5)) for i in range(7)]
        self.assertEqual(days, [
            "Mon 07:05 UTC", "Tue 07:05 UTC", "Wed 07:05 UTC",
            "Thu 07:05 UTC", "Fri 07:05 UTC", "Sat 07:05 UTC",
            "Sun 07:05 UTC"])
        # another zone's instant is said in UTC
        paris = dt_timezone(timedelta(hours=1))
        self.assertEqual(opens_words(datetime(2026, 11, 9, 0, 30, tzinfo=paris)),
                         "Sun 23:30 UTC")
