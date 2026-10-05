"""THE EVENT WINDOW: a high-impact calendar event is the weekend's gap in
miniature (2026-10-05, the operator asked for more resilience on open
positions).

From EVENT_BEFORE_MINUTES before to EVENT_AFTER_MINUTES after a high-impact
macro event on the row's currency — either leg of a pair, the home currency
for every other class — and within EARNINGS_BEFORE_HOURS of a held stock's
own earnings, the care does what it does before the weekend shut: a winner
of EVENT_LOCK_AT_R locks break-even ("event lock"), a REAL loser carrying
EVENT_CUT_LEVERAGE or more is closed ("event cut"). The manual lane gets the
lock only. Options are never read. The calendar is read once per tick.

Run with:  python manage.py test tests.test_event_window
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_aragorn import _switch
from tests.test_risk_limits_bind import _config
from tests.test_scale_out import _trade


def _row(symbol="USDJPY", cls="forex", side="BUY", entry=150.0, stop=149.0,
         care=None, lev=None, paper=False):
    meta = {"initial_stop_loss": stop}
    if care:
        meta["care"] = care
    if lev:
        meta["leverage"] = lev
    return SimpleNamespace(symbol=symbol, side=side,
                           entry_price=Decimal(str(entry)),
                           stop_loss=Decimal(str(stop)), metadata=meta,
                           asset_class=cls, paper=paper,
                           opened_at=timezone.now() - timedelta(hours=1))


def _ev(minutes, title="BOJ Policy Rate", currency="JPY", earnings=False,
        now=None):
    now = now or timezone.now()
    return {"at": now + timedelta(minutes=minutes), "title": title,
            "currency": currency, "earnings": earnings}


class TheConstantsTests(SimpleTestCase):

    def test_the_window_and_the_weekends_rules(self):
        from bot_program import position_care as pc
        from bot_program.news_risk import MACRO_SOURCES
        self.assertEqual((pc.EVENT_BEFORE_MINUTES, pc.EVENT_AFTER_MINUTES,
                          pc.EARNINGS_BEFORE_HOURS), (60, 15, 24))
        self.assertEqual(pc.EVENT_LOCK_AT_R, pc.WEEKEND_LOCK_AT_R)
        self.assertEqual(pc.EVENT_CUT_LEVERAGE, pc.WEEKEND_CUT_LEVERAGE)
        self.assertEqual((pc.EVENT_LOCK_AT_R, pc.EVENT_CUT_LEVERAGE), (0.5, 5))
        self.assertEqual(pc.EVENT_HOME_CURRENCY, "USD")
        self.assertEqual(pc.EVENT_IMPACT, "high")
        self.assertEqual(tuple(pc.EVENT_SOURCES), tuple(MACRO_SOURCES))
        self.assertNotIn("event lock", pc.CROWD_MOVABLE,
                         "a gap, not a hunt: the crowd never moves it")


class TheEventForTests(SimpleTestCase):

    def setUp(self):
        self.now = timezone.now()

    def test_a_pair_is_exposed_through_either_leg_inside_the_window(self):
        from bot_program.position_care import event_for
        ev = _ev(30, now=self.now)
        e = event_for(_row("USDJPY"), self.now, [ev])
        self.assertIsNotNone(e)
        self.assertEqual((e["title"], e["minutes"]), ("BOJ Policy Rate", 30.0))
        self.assertEqual(e["why"], "BOJ Policy Rate in 30 min")
        self.assertFalse(e["earnings"])
        self.assertIsNotNone(event_for(_row("EURJPY"), self.now, [ev]))
        self.assertIsNone(event_for(_row("EURUSD"), self.now, [ev]), "no yen leg")
        self.assertIsNone(event_for(_row("USDJPY"), self.now,
                                    [_ev(90, now=self.now)]), "too far")
        past = event_for(_row("USDJPY"), self.now, [_ev(-10, now=self.now)])
        self.assertIsNotNone(past)
        self.assertEqual(past["why"], "BOJ Policy Rate 10 min ago")
        self.assertIsNone(event_for(_row("USDJPY"), self.now,
                                    [_ev(-20, now=self.now)]), "the print is done")

    def test_every_other_class_reads_the_home_currency(self):
        from bot_program.position_care import event_for
        usd = _ev(20, title="FOMC Minutes", currency="USD", now=self.now)
        jpy = _ev(20, now=self.now)
        for cls, sym in (("index", "SPX500"), ("commodity", "WTIUSD"),
                         ("crypto", "BTCUSD"), ("stock", "AAPL"), ("etf", "SPY")):
            self.assertIsNotNone(event_for(_row(sym, cls), self.now, [usd]), cls)
            self.assertIsNone(event_for(_row(sym, cls), self.now, [jpy]), cls)
        self.assertIsNone(event_for(_row("AAPL", "options"), self.now, [usd]))
        self.assertIsNone(event_for(_row("SPX500", "index"), self.now,
                                    [_ev(20, title="?", currency="", now=self.now)]))

    def test_a_held_stocks_own_earnings_count_from_a_day_out(self):
        from bot_program.position_care import event_for
        earn = _ev(10 * 60, title="AAPL Earnings", currency="AAPL",
                   earnings=True, now=self.now)
        e = event_for(_row("AAPL", "stock"), self.now, [earn])
        self.assertIsNotNone(e)
        self.assertTrue(e["earnings"])
        self.assertEqual(e["why"], "AAPL Earnings in 10 h")
        self.assertIsNone(event_for(_row("MSFT", "stock"), self.now, [earn]))
        self.assertIsNone(event_for(_row("AAPL", "stock"), self.now,
                                    [_ev(30 * 60, title="AAPL Earnings",
                                         currency="AAPL", earnings=True,
                                         now=self.now)]), "beyond a day")
        word = _ev(5 * 60, title="Q3 Earnings: AAPL", currency="",
                   earnings=True, now=self.now)
        self.assertIsNotNone(event_for(_row("AAPL", "stock"), self.now, [word]))
        other = _ev(5 * 60, title="Q3 Earnings: AAPLX", currency="",
                    earnings=True, now=self.now)
        self.assertIsNone(event_for(_row("AAPL", "stock"), self.now, [other]),
                          "a word of the title, not a substring")
        self.assertIsNotNone(event_for(_row("SPY", "etf"), self.now,
                                       [_ev(60, title="SPY Earnings",
                                            currency="SPY", earnings=True,
                                            now=self.now)]))
        self.assertIsNone(event_for(_row("USDJPY"), self.now, [earn]),
                          "a pair never reads earnings")

    def test_the_nearest_event_wins_and_an_empty_calendar_is_no_window(self):
        from bot_program.position_care import event_for
        evs = [_ev(50, title="far", now=self.now), _ev(5, title="near", now=self.now)]
        self.assertEqual(event_for(_row("USDJPY"), self.now, evs)["title"], "near")
        self.assertIsNone(event_for(_row("USDJPY"), self.now, []))
        self.assertIsNone(event_for(_row("USDJPY"), self.now, [{"title": "x"}]))


class TheCalendarTests(TestCase):

    def _event(self, minutes, *, title="BOJ Policy Rate", currency="JPY",
               impact="high", source="forexfactory"):
        from market_data.models import EconomicEvent
        return EconomicEvent.objects.create(
            title=title, country="JP", impact=impact,
            datetime=timezone.now() + timedelta(minutes=minutes),
            source=source, currency_affected=currency)

    def test_high_impact_macro_rows_in_the_window_and_earnings_a_day_out(self):
        from bot_program.position_care import upcoming_events
        self._event(30)                                           # in
        self._event(20, impact="medium", title="medium")          # out: impact
        self._event(180, currency="USD", title="CPI")             # out: too far
        self._event(-10, currency="USD", title="NFP")             # in: just past
        self._event(-30, currency="USD", title="old")             # out: done
        self._event(40, source="test", currency="USD",
                    title="unknown source")                       # out: source
        self._event(10 * 60, title="AAPL Earnings", currency="AAPL",
                    source="fmp", impact="")                      # in: earnings
        self._event(30 * 60, title="MSFT Earnings", currency="MSFT",
                    source="fmp", impact="")                      # out: a day+
        rows = upcoming_events()
        self.assertEqual(sorted(r["title"] for r in rows),
                         ["AAPL Earnings", "BOJ Policy Rate", "NFP"])
        earn = next(r for r in rows if r["earnings"])
        self.assertEqual(earn["currency"], "AAPL")
        boj = next(r for r in rows if r["title"] == "BOJ Policy Rate")
        self.assertEqual((boj["currency"], boj["earnings"]), ("JPY", False))

    def test_the_tick_cache_reads_the_calendar_once(self):
        from bot_program.position_care import EVENT_CACHE_KEY, upcoming_events
        cache = {}
        self.assertEqual(upcoming_events(cache=cache), [])
        self._event(30)
        self.assertEqual(upcoming_events(cache=cache), [], "the tick's read stands")
        self.assertIn(EVENT_CACHE_KEY, cache)
        self.assertEqual(len(upcoming_events()), 1)

    def test_an_unreadable_calendar_is_no_window(self):
        from bot_program.position_care import upcoming_events
        with mock.patch("market_data.models.EconomicEvent.objects.filter",
                        side_effect=RuntimeError("db gone")):
            self.assertEqual(upcoming_events(), [])


class ThePlanTests(SimpleTestCase):
    """Entry 150, stop 149 (risk 1): 150.6 is +0.6R, 149.5 is -0.5R."""

    def setUp(self):
        self.now = timezone.now()
        self.event = {"title": "BOJ Policy Rate",
                      "at": (self.now + timedelta(minutes=30)).isoformat(),
                      "minutes": 30.0, "earnings": False,
                      "why": "BOJ Policy Rate in 30 min"}

    def test_a_winner_locks_break_even_in_the_window(self):
        from bot_program.position_care import plan
        p = plan(_row(), 150.6, now=self.now, live=True, event=self.event)
        self.assertEqual(p["action"], "hold")
        self.assertEqual(p["care"]["soft_why"], "event lock")
        self.assertAlmostEqual(p["care"]["soft_stop"], 150.1)
        self.assertEqual(p["care"]["event"],
                         {"title": "BOJ Policy Rate", "at": self.event["at"]})
        self.assertTrue(p["changed"])
        # under the lock bar: no lock, the event still written on the care
        p2 = plan(_row(), 150.3, now=self.now, live=True, event=self.event)
        self.assertNotIn("soft_stop", p2["care"])
        self.assertIn("event", p2["care"])
        # no event: nothing, and a stale event on the care is forgotten
        p3 = plan(_row(care={"event": {"title": "old", "at": "x"}}), 150.6,
                  now=self.now, live=True)
        self.assertNotIn("event", p3["care"])
        self.assertNotIn("soft_stop", p3["care"])
        self.assertTrue(p3["changed"])
        # the same event twice: nothing changed the second time
        p4 = plan(_row(care=p["care"]), 150.6, now=self.now, live=True,
                  event=self.event)
        self.assertFalse(p4["changed"])

    def test_a_levered_real_loser_is_cut_the_others_are_not(self):
        from bot_program.position_care import plan
        p = plan(_row(lev=5), 149.5, now=self.now, live=True, event=self.event)
        self.assertEqual((p["action"], p["reason"]), ("close", "SL"))
        self.assertIn("BOJ Policy Rate in 30 min", p["why"])
        self.assertIn("5x loser", p["why"])
        self.assertEqual(p["care"]["exit"], "event cut")
        self.assertEqual(plan(_row(lev=2), 149.5, now=self.now, live=True,
                              event=self.event)["action"], "hold")
        self.assertEqual(plan(_row(lev=5, paper=True), 149.5, now=self.now,
                              live=False, event=self.event)["action"], "hold")
        self.assertEqual(plan(_row(lev=5), 149.5, now=self.now,
                              live=True)["action"], "hold")
        self.assertEqual(plan(_row(lev=5), 150.6, now=self.now, live=True,
                              event=self.event)["action"], "hold",
                         "a winner is never cut")
        # the manual lane: the lock, never the cut
        m = plan(_row(lev=5), 149.5, now=self.now, live=True, manual=True,
                 event=self.event)
        self.assertEqual(m["action"], "hold")
        m2 = plan(_row(lev=5), 150.6, now=self.now, live=True, manual=True,
                  event=self.event)
        self.assertEqual(m2["care"]["soft_why"], "event lock")


class TheCareTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user("ev_u", password="x")
        self.cfg = _config(self.user, asset_class="forex", name="fx",
                           symbols=["USDJPY"])
        _switch("aragorn")
        from bot_program.asset_engine.base import make_bot
        self.bot = make_bot(self.cfg)

    def _event(self, minutes=30, currency="JPY", title="BOJ Policy Rate"):
        from market_data.models import EconomicEvent
        return EconomicEvent.objects.create(
            title=title, country="JP", impact="high",
            datetime=timezone.now() + timedelta(minutes=minutes),
            source="forexfactory", currency_affected=currency)

    def _real(self, **meta):
        return _trade(self.cfg, paper=False, symbol="USDJPY", cls="forex",
                      qty="1000", entry="150", stop="149", meta=meta)

    def _care(self, trade, price):
        from bot_program.position_care import care
        return care(self.bot, trade, price, None)

    def test_a_real_winner_locks_break_even_before_the_print(self):
        self._event()
        t = self._real()
        self.assertEqual(self._care(t, 150.6), "")
        t.refresh_from_db()
        care = t.metadata["care"]
        self.assertEqual(care["soft_why"], "event lock")
        self.assertAlmostEqual(care["soft_stop"], 150.1)
        self.assertEqual(care["event"]["title"], "BOJ Policy Rate")
        # an unrelated currency's event: nothing
        from market_data.models import EconomicEvent
        EconomicEvent.objects.all().delete()
        self._event(currency="GBP", title="BoE Rate")
        t2 = self._real()
        self._care(t2, 150.6)
        t2.refresh_from_db()
        self.assertNotIn("soft_stop", t2.metadata["care"])
        self.assertNotIn("event", t2.metadata["care"])

    def test_a_levered_real_loser_is_cut_and_journaled(self):
        from bot_program.aragorn_models import AragornAction
        self._event()
        t = self._real(leverage=10)
        with mock.patch.object(type(self.bot), "_close_trade",
                               return_value=True) as closed:
            self.assertEqual(self._care(t, 149.5), "closed")
        closed.assert_called_once()
        self.assertEqual(closed.call_args.kwargs.get("reason"), "SL")
        act = AragornAction.objects.get(kind="care_close")
        self.assertIn("REAL MONEY", act.detail)
        self.assertIn("BOJ Policy Rate in 30 min", act.detail)
        self.assertEqual(act.stats["exit"], "event cut")

    def test_the_calendar_is_read_once_per_tick(self):
        from bot_program.position_care import EVENT_CACHE_KEY
        self._event()
        self.bot._tick_broker_cache = {}
        t = self._real()
        self._care(t, 150.6)
        self.assertIn(EVENT_CACHE_KEY, self.bot._tick_broker_cache)
        self.assertEqual(len(self.bot._tick_broker_cache[EVENT_CACHE_KEY]), 1)
        with mock.patch("market_data.models.EconomicEvent.objects.filter",
                        side_effect=RuntimeError("not asked twice")):
            self._care(t, 150.7)
        t.refresh_from_db()
        self.assertEqual(t.metadata["care"]["soft_why"], "event lock")


class TheWiringTests(SimpleTestCase):

    def test_the_care_passes_the_rows_event_to_the_plan(self):
        import inspect

        from bot_program import position_care
        self.assertIn("event=None", inspect.getsource(position_care.plan)
                      .split('"""')[0])
        src = inspect.getsource(position_care.care)
        self.assertIn("upcoming_events(", src)
        self.assertIn("_tick_broker_cache", src)
        self.assertIn("scale=scale, event=event)", src)
