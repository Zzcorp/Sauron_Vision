"""NO PAPER FILL AND NO PAPER EXIT WHILE THE MARKET IS SHUT (2026-09-26).

On Saturday 2026-09-26 13:53:54 UTC, forex shut since Friday ~21:00 UTC,
the CLOSE button booked two PAPER forex rows — #108 EURCAD and #109
GBPCAD — at Friday's last OANDA price. stream_oanda wrote every PRICE
message, and OANDA re-sends a snapshot per instrument on each reconnect,
shut market included, flagged "tradeable": false: the LiveQuote kept
Friday's price under a fresh updated_at, PaperTrader.ticker judged only
its age, and nothing on the paper path asked whether the market was open.

What this file pins, at fixed clocks (the rest of the suite runs with the
gate off — tests/__init__.py):
  * the stream writes nothing OANDA calls not tradeable (M1);
  * ONE clock answers "open now, when next, since when" per instrument
    class — the New York forex week in winter, the US equity holidays
    (M2);
  * no paper fill and no paper exit while the market is shut, nor in the
    settling quarter hour after it opens — the CLOSE button and its
    preview, the tick's time stop and SL, the TAKE TRADE and the
    instrument BUY/SELL, the bots' entries (the options lane too), the
    kill switch, the legacy tick, PaperTrader itself — and every one of
    them goes ahead once the market has a price of the new session (M3);
  * a clock exit or a flatten that finds no price in the hours after a
    reopen waits for the first one, never booking the entry price there;
  * LIVE rows are untouched on every path: the venue client is called as
    before (the CLOSE button, the tick's SL, the bot's entry, the manual
    ticket, the kill switch, the position review's mark).

Run with:  python manage.py test tests.test_paper_market_hours
"""
import inspect
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from bot_program.engine import paper_trader

UTC = dt_timezone.utc
#: The incident's instant: Saturday, forex shut since Friday 21:00 UTC.
SAT = datetime(2026, 9, 26, 13, 53, 54, tzinfo=UTC)
#: Half an hour into the next forex week (its settling window long over).
SUN_OPEN = datetime(2026, 9, 27, 21, 30, tzinfo=UTC)
#: Inside the settling quarter hour after the Sunday 21:00 UTC open.
SUN_SETTLING = datetime(2026, 9, 27, 21, 5, tzinfo=UTC)
#: Monday 11:00 New York: the NYSE session is running.
MON_NYSE = datetime(2026, 9, 28, 15, 0, tzinfo=UTC)
FOREX_WORDS = "the forex market is shut (reopens Sunday 21:00 UTC)"
SETTLING_WORDS = ("the forex market reopened at Sunday 21:00 UTC and its "
                  "first quotes may still carry the price from before it "
                  "shut (paper fills resume Sunday 21:15 UTC)")
ROUTER = "bot_program.engine.broker_router.client_for_symbol"


@contextmanager
def _at(when, gate=True):
    """The wall clock fixed at `when`, and the paper venue's gate ON (the
    suite runs with it off)."""
    with patch("django.utils.timezone.now", return_value=when), \
            patch.object(paper_trader, "MARKET_HOURS_GATE", gate):
        yield


def _user(name):
    return get_user_model().objects.create_user(username=name, password="x")


def _inst(symbol, asset_class, exchange=""):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "exchange": exchange, "is_active": True})
    return inst


def _quote(inst, last, age_s=60, source="oanda_stream"):
    """A LiveQuote `age_s` seconds old AT THE FIXED CLOCK — the incident's
    quote was a minute old because the stream had just re-stamped it."""
    from market_data.models import LiveQuote
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": source})
    LiveQuote.objects.filter(instrument=inst).update(
        updated_at=timezone.now() - timedelta(seconds=age_s))


def _quote_written_at(inst, last, when, source="oanda_stream"):
    """A LiveQuote whose updated_at is exactly `when`."""
    from market_data.models import LiveQuote
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": source})
    LiveQuote.objects.filter(instrument=inst).update(updated_at=when)


def _cfg(user, asset_class="forex", mode="paper", **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(user=user, asset_class=asset_class,
                    name=f"{asset_class}_{mode}", enabled=True, mode=mode,
                    symbols=[], capital=Decimal("10000"))
    defaults.update(kw)
    return AssetBotConfig.objects.create(**defaults)


def _row(cfg, symbol="EURCAD", *, qty="7900", entry="1.60725571",
         stop="1.60500000", target="1.63000000", paper=True, vpu=0.73,
         opened_at=None):
    """#108's shape: a BUY on EURCAD, paper, OPEN."""
    from bot_program.models import AssetBotTrade
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side="BUY",
        qty=Decimal(qty), entry_price=Decimal(entry),
        stop_loss=Decimal(stop), take_profit=Decimal(target),
        status="OPEN", paper=paper, rule_name="mh_rule",
        metadata={"initial_stop_loss": float(stop), "value_per_unit": vpu})
    if opened_at is not None:
        AssetBotTrade.objects.filter(pk=t.pk).update(opened_at=opened_at)
        t.refresh_from_db()
    return t


def _untouched(test, trade):
    """OPEN, and nothing booked on it."""
    trade.refresh_from_db()
    test.assertEqual(trade.status, "OPEN")
    test.assertIsNone(trade.exit_price)
    test.assertEqual(trade.pnl or 0, 0)     # the model's default: none realised
    test.assertFalse(trade.outcome)
    test.assertIsNone(trade.closed_at)
    test.assertNotIn("time_stop_unpriced", trade.metadata or {})


def _live_client(fill="97.50", last="97"):
    """A LIVE broker client (not a PaperTrader): quotes `last`, fills a
    close in full at `fill`."""
    c = MagicMock(name="fake_live_client")
    c.market_order = MagicMock(return_value={
        "orderId": "L-1", "avgPrice": fill, "executedQty": "10",
        "status": "FILLED"})
    c.ticker = MagicMock(return_value={"lastPrice": last})
    c.get_positions = MagicMock(return_value=[{"symbol": "AAPL",
                                                "qty": "10"}])
    return c


def _live_aapl(user):
    """A LIVE AAPL long — 10 at 100, stop 98 — on a live stock config."""
    _inst("AAPL", "stock", "NASDAQ")
    cfg = _cfg(user, "stock", mode="live")
    return cfg, _row(cfg, "AAPL", qty="10", entry="100", stop="98",
                     target="104", paper=False, vpu=1.0)


# ── 0. the suite's default, and the production value ─────────────────────────

class TheGateIsOnInProductionTests(SimpleTestCase):
    def test_the_module_ships_with_the_gate_on(self):
        src = inspect.getsource(paper_trader)
        self.assertIn("\nMARKET_HOURS_GATE = True\n", src)
        self.assertIn("\nREOPEN_SETTLE_SECONDS = 900\n", src)
        self.assertIn("\nREOPEN_PRICE_GRACE_SECONDS = 6 * 3600\n", src)

    def test_the_suite_runs_with_it_off(self):
        """tests/__init__.py: every other module's paper trade runs at
        whatever hour the wall clock says."""
        self.assertFalse(paper_trader.MARKET_HOURS_GATE)
        self.assertEqual(paper_trader.market_shut_words("forex", now=SAT), "")
        self.assertEqual(paper_trader.paper_awaits_first_price(
            "EURCAD", "forex", now=SUN_OPEN), "")


# ── 1. M1: the stream ─────────────────────────────────────────────────────────

def _price(tradeable=None, instrument="EUR_CAD", bid="1.61040",
           ask="1.61063"):
    msg = {"type": "PRICE", "instrument": instrument,
           "bids": [{"price": bid, "liquidity": 1000000}],
           "asks": [{"price": ask, "liquidity": 1000000}]}
    if tradeable is not None:
        msg["tradeable"] = tradeable
    return msg


class TheStreamWritesOnlyTradeablePricesTests(SimpleTestCase):
    def _fn(self):
        from market_data.management.commands.stream_oanda import (
            price_to_write)
        return price_to_write

    def test_tradeable_false_is_skipped_and_named_once_per_connection(self):
        fn = self._fn()
        seen = set()
        with self.assertLogs("stream_oanda", level="INFO") as cm:
            self.assertIsNone(fn(_price(False), seen))
            self.assertIsNone(fn(_price(False), seen))
        lines = [r.getMessage() for r in cm.records]
        self.assertEqual(lines,
                         ["EUR_CAD not tradeable — price not written"])
        # a new connection starts a new set: named again
        with self.assertLogs("stream_oanda", level="INFO") as cm2:
            self.assertIsNone(fn(_price(False), set()))
        self.assertEqual(len(cm2.records), 1)

    def test_tradeable_true_is_written(self):
        self.assertEqual(self._fn()(_price(True), set()),
                         ("EUR_CAD", 1.6104, 1.61063))

    def test_a_message_without_the_flag_is_written_as_before(self):
        self.assertEqual(self._fn()(_price(None), set()),
                         ("EUR_CAD", 1.6104, 1.61063))

    def test_a_string_false_is_skipped_too(self):
        self.assertIsNone(self._fn()(_price("false"), {"EUR_CAD"}))

    def test_heartbeats_and_empty_books_are_not_prices(self):
        fn = self._fn()
        self.assertIsNone(fn({"type": "HEARTBEAT"}, set()))
        msg = _price(True)
        msg["bids"] = []
        self.assertIsNone(fn(msg, set()))

    def test_the_loop_writes_and_broadcasts_only_what_passes(self):
        from pathlib import Path

        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "market_data" / "management"
               / "commands" / "stream_oanda.py").read_text(encoding="utf-8")
        loop = src[src.index("async for line in r.content:"):]
        loop = loop[:loop.index("except Exception as e:")]
        self.assertIn("got = price_to_write(msg, not_tradeable)", loop)
        self.assertIn("if got is None: continue", loop)
        self.assertLess(loop.index("if got is None: continue"),
                        loop.index("update_live_quote(sym, bid, ask)"))
        self.assertLess(loop.index("if got is None: continue"),
                        loop.index("await broadcast(sym, mid, None,"))
        # one set per CONNECTION, made before the loop reads a line
        head = src[:src.index("async for line in r.content:")]
        self.assertIn("not_tradeable = set()", head[-400:])


# ── 2. M2: the one clock ──────────────────────────────────────────────────────

def _utc(*args):
    return datetime(*args, tzinfo=UTC)


class TheOneMarketClockTests(SimpleTestCase):
    def _clock(self, cls, when, exchange="", symbol=""):
        from core.exchange_status import market_clock
        return market_clock(cls, exchange, symbol=symbol, now_utc=when)

    def test_forex_is_shut_on_saturday_and_reopens_sunday_2100_utc(self):
        c = self._clock("forex", SAT)
        self.assertFalse(c["is_open"])
        self.assertEqual(c["session"], "FOREX")
        self.assertEqual(c["reopens"], _utc(2026, 9, 27, 21, 0))
        self.assertEqual(c["reopens_words"], "Sunday 21:00 UTC")
        self.assertIsNone(c["opened"])

    def test_forex_shuts_at_friday_2100_utc_and_reopens_on_sunday(self):
        self.assertTrue(self._clock(
            "forex", _utc(2026, 9, 25, 20, 59))["is_open"])
        c = self._clock("forex", _utc(2026, 9, 25, 21, 0))
        self.assertFalse(c["is_open"])
        self.assertEqual(c["reopens_words"], "Sunday 21:00 UTC")
        self.assertFalse(self._clock(
            "forex", _utc(2026, 9, 27, 20, 59))["is_open"])
        c = self._clock("forex", SUN_OPEN)
        self.assertTrue(c["is_open"])
        self.assertEqual(c["opened"], _utc(2026, 9, 27, 21, 0))

    def test_in_winter_the_forex_week_keeps_17_00_new_york(self):
        """From November 17:00 New York is 22:00 UTC: the venues' week —
        and OANDA's tradeable flag — opens an hour after the UTC row."""
        c = self._clock("forex", _utc(2026, 11, 8, 21, 30))
        self.assertFalse(c["is_open"])
        self.assertEqual(c["reopens"], _utc(2026, 11, 8, 22, 0))
        self.assertEqual(c["reopens_words"], "Sunday 22:00 UTC")
        c = self._clock("forex", _utc(2026, 11, 8, 22, 1))
        self.assertTrue(c["is_open"])
        self.assertEqual(c["opened"], _utc(2026, 11, 8, 22, 0))
        # Friday: the UTC row still shuts it at 21:00, the earlier of the two
        c = self._clock("forex", _utc(2026, 11, 6, 21, 30))
        self.assertFalse(c["is_open"])
        self.assertEqual(c["reopens_words"], "Sunday 22:00 UTC")
        self.assertTrue(self._clock(
            "forex", _utc(2026, 11, 6, 20, 59))["is_open"])
        # summer unchanged: the two clocks agree
        self.assertTrue(self._clock(
            "forex", _utc(2026, 9, 27, 21, 5))["is_open"])

    def test_crypto_never_shuts(self):
        c = self._clock("crypto", SAT)
        self.assertTrue(c["is_open"])
        self.assertIsNone(c["reopens"])
        self.assertIsNone(c["opened"])

    def test_a_stock_waits_for_the_new_york_open(self):
        c = self._clock("stock", SAT, exchange="NASDAQ", symbol="AAPL")
        self.assertFalse(c["is_open"])
        self.assertEqual(c["reopens_words"], "Monday 13:30 UTC")
        c = self._clock("stock", _utc(2026, 9, 29, 21, 0), exchange="NYSE")
        self.assertFalse(c["is_open"])
        self.assertEqual(c["reopens_words"], "Wednesday 13:30 UTC")
        c = self._clock("stock", MON_NYSE, exchange="NYSE")
        self.assertTrue(c["is_open"])
        self.assertEqual(c["opened"], _utc(2026, 9, 28, 13, 30))

    def test_the_us_equity_holidays_and_early_closes(self):
        # Thanksgiving: shut all day; Friday opens at 09:30 New York (EST)
        c = self._clock("stock", _utc(2026, 11, 26, 15, 0), exchange="NYSE")
        self.assertFalse(c["is_open"])
        self.assertEqual(c["reopens_words"], "Friday 14:30 UTC")
        # the Wednesday close already skips it
        c = self._clock("stock", _utc(2026, 11, 25, 21, 30),
                        exchange="NASDAQ")
        self.assertEqual(c["reopens_words"], "Friday 14:30 UTC")
        # the day after: open until the 13:00 early close, then Monday
        self.assertTrue(self._clock("etf", _utc(2026, 11, 27, 17, 59),
                                    exchange="NYSE")["is_open"])
        c = self._clock("etf", _utc(2026, 11, 27, 18, 30), exchange="NYSE")
        self.assertFalse(c["is_open"])
        self.assertEqual(c["reopens_words"], "Monday 14:30 UTC")
        # the New York cash index keeps them too; London does not
        self.assertFalse(self._clock("index", _utc(2026, 12, 25, 15, 0),
                                     symbol="SPX500")["is_open"])
        self.assertTrue(self._clock("stock", _utc(2026, 11, 26, 10, 0),
                                    exchange="LSE")["is_open"])

    def test_the_holiday_table_holds_only_weekdays(self):
        from core.exchange_status import (US_EQUITY_EARLY_CLOSES,
                                          US_EQUITY_HOLIDAYS)
        for day in list(US_EQUITY_HOLIDAYS) + list(US_EQUITY_EARLY_CLOSES):
            with self.subTest(day=day):
                self.assertLess(day.weekday(), 5)
        self.assertFalse(set(US_EQUITY_HOLIDAYS) & set(US_EQUITY_EARLY_CLOSES))

    def test_an_index_keeps_its_cash_venue(self):
        c = self._clock("index", SAT, symbol="SPX500")
        self.assertEqual(c["session"], "NYSE")
        self.assertEqual(c["reopens_words"], "Monday 13:30 UTC")

    def test_a_metal_keeps_globex_the_weekend_and_the_daily_break(self):
        fri = _utc(2026, 9, 25, 21, 30)     # 16:30 CT
        c = self._clock("commodity", fri, exchange="COMEX", symbol="GOLD")
        self.assertFalse(c["is_open"])
        self.assertEqual(c["session"], "CME")
        self.assertEqual(c["reopens_words"], "Sunday 22:00 UTC")
        tue = _utc(2026, 9, 29, 21, 30)     # break
        c = self._clock("commodity", tue, exchange="COMEX", symbol="GOLD")
        self.assertFalse(c["is_open"])
        self.assertEqual(c["reopens_words"], "Tuesday 22:00 UTC")
        # Tuesday 10:00 CT runs the session that opened Monday 17:00 CT
        c = self._clock("commodity", _utc(2026, 9, 29, 15, 0),
                        exchange="COMEX", symbol="GOLD")
        self.assertEqual(c["opened"], _utc(2026, 9, 28, 22, 0))

    def test_a_grain_keeps_its_product_session(self):
        c = self._clock("commodity", SAT, exchange="CBOT", symbol="CORNUSD")
        self.assertFalse(c["is_open"])
        self.assertEqual(c["session"], "CBOT_GRAINS")
        # Sunday 19:00 CT is Monday 00:00 UTC
        self.assertEqual(c["reopens_words"], "Monday 00:00 UTC")
        # 09:00 CT Tuesday: the day segment reopened at 08:30 CT
        c = self._clock("commodity", _utc(2026, 9, 29, 14, 0),
                        exchange="CBOT", symbol="CORNUSD")
        self.assertTrue(c["is_open"])
        self.assertEqual(c["opened"], _utc(2026, 9, 29, 13, 30))

    def test_a_class_with_no_modelled_hours_reads_open_and_says_so(self):
        for cls in ("cfd", "", "dogecoin_cfd"):
            with self.subTest(cls=cls):
                c = self._clock(cls, SAT)
                self.assertTrue(c["is_open"])
                self.assertFalse(c["modelled"])
                self.assertIsNone(c["opened"])

    def test_the_words_every_refusal_carries(self):
        with patch.object(paper_trader, "MARKET_HOURS_GATE", True):
            self.assertEqual(paper_trader.market_shut_words("forex", now=SAT),
                             FOREX_WORDS)
            self.assertEqual(
                paper_trader.market_shut_words("etf", "NYSE", now=SAT),
                "the ETF market is shut (reopens Monday 13:30 UTC)")
            self.assertEqual(paper_trader.market_shut_words("crypto",
                                                            now=SAT), "")

    def test_the_settling_quarter_hour_after_an_open(self):
        with patch.object(paper_trader, "MARKET_HOURS_GATE", True):
            self.assertEqual(
                paper_trader.market_shut_words("forex", now=SUN_SETTLING),
                SETTLING_WORDS)
            self.assertEqual(paper_trader.market_shut_words(
                "forex", now=_utc(2026, 9, 27, 21, 15)), "")
            self.assertIn("(paper fills resume Monday 13:45 UTC)",
                          paper_trader.market_shut_words(
                              "stock", "NYSE",
                              now=_utc(2026, 9, 28, 13, 31)))
            self.assertEqual(paper_trader.market_shut_words(
                "stock", "NYSE", now=_utc(2026, 9, 28, 13, 45)), "")


# ── 3. M3: PaperTrader itself ─────────────────────────────────────────────────

class PaperTraderKeepsTheHoursTests(TestCase):
    def test_ticker_on_saturday_reports_no_price_and_the_reason(self):
        with _at(SAT):
            _quote(_inst("EURCAD", "forex"), "1.61051500")
            tk = paper_trader.PaperTrader(None).ticker("EURCAD")
        self.assertEqual(tk["lastPrice"], "0")
        self.assertTrue(tk["market_shut"])
        self.assertEqual(tk["reason"], FOREX_WORDS)

    def test_ticker_prices_again_once_the_market_reopens(self):
        with _at(SUN_OPEN):
            _quote(_inst("EURCAD", "forex"), "1.61051500")
            tk = paper_trader.PaperTrader(None).ticker("EURCAD")
        self.assertEqual(Decimal(tk["lastPrice"]), Decimal("1.610515"))
        self.assertNotIn("market_shut", tk)

    def test_ticker_says_settling_in_the_quarter_hour_after_the_open(self):
        with _at(SUN_SETTLING):
            _quote(_inst("EURCAD", "forex"), "1.61051500", age_s=10)
            tk = paper_trader.PaperTrader(None).ticker("EURCAD")
        self.assertEqual(tk["lastPrice"], "0")
        self.assertTrue(tk["market_shut"])
        self.assertEqual(tk["reason"], SETTLING_WORDS)

    def test_a_quote_written_inside_the_window_is_not_a_price_after_it(self):
        """A 10-minute poll at 21:10 may carry Friday's close under a fresh
        stamp: at 21:20 it is 10 minutes old — young enough for the age
        rule, and still not a price of the new week."""
        inst = _inst("USDNOK", "forex")
        with _at(_utc(2026, 9, 27, 21, 20)):
            _quote_written_at(inst, "9.50437", _utc(2026, 9, 27, 21, 10),
                              source="yfinance")
            tk = paper_trader.PaperTrader(None).ticker("USDNOK")
            self.assertEqual(tk["lastPrice"], "0")
            _quote_written_at(inst, "9.51200", _utc(2026, 9, 27, 21, 16),
                              source="yfinance")
            tk = paper_trader.PaperTrader(None).ticker("USDNOK")
        self.assertEqual(Decimal(tk["lastPrice"]), Decimal("9.512"))

    def test_a_bar_that_ended_before_the_open_is_not_a_price(self):
        """Gold after the daily 16:00-17:00 CT break: the 15:00 CT bar is
        under six hours old and still the price from before the break."""
        from market_data.models import PriceData
        inst = _inst("GOLD", "commodity", "COMEX")
        when = _utc(2026, 9, 29, 22, 20)             # 17:20 CT, settled
        _quote_written_at(inst, "2650", _utc(2026, 9, 29, 20, 55),
                          source="yfinance")
        PriceData.objects.create(
            instrument=inst, timeframe="1h",
            timestamp=_utc(2026, 9, 29, 20, 0), open=Decimal("2649"),
            high=Decimal("2651"), low=Decimal("2648"),
            close=Decimal("2650"), source="t")
        with _at(when):
            tk = paper_trader.PaperTrader(None).ticker("GOLD")
        self.assertEqual(tk["lastPrice"], "0")
        with _at(when, gate=False):
            tk = paper_trader.PaperTrader(None).ticker("GOLD")
        self.assertEqual(Decimal(tk["lastPrice"]), Decimal("2650"))
        PriceData.objects.create(
            instrument=inst, timeframe="1h",
            timestamp=_utc(2026, 9, 29, 22, 0), open=Decimal("2652"),
            high=Decimal("2653"), low=Decimal("2651"),
            close=Decimal("2652.5"), source="t")
        with _at(when):
            tk = paper_trader.PaperTrader(None).ticker("GOLD")
        self.assertEqual(Decimal(tk["lastPrice"]), Decimal("2652.5"))

    def test_ticker_prices_crypto_on_saturday(self):
        with _at(SAT):
            _quote(_inst("BTCUSD", "crypto"), "60000", source="binance")
            tk = paper_trader.PaperTrader(None).ticker("BTCUSD")
        self.assertEqual(Decimal(tk["lastPrice"]), Decimal("60000"))

    def test_a_read_only_caller_reads_the_quote_without_the_clock(self):
        with _at(SAT):
            _quote(_inst("EURCAD", "forex"), "1.61051500")
            tk = paper_trader.PaperTrader(None).ticker(
                "EURCAD", market_hours=False)
        self.assertEqual(Decimal(tk["lastPrice"]), Decimal("1.610515"))

    def test_market_order_refuses_on_saturday_and_fills_crypto(self):
        with _at(SAT):
            _quote(_inst("EURCAD", "forex"), "1.61051500")
            _quote(_inst("BTCUSD", "crypto"), "60000", source="binance")
            pt = paper_trader.PaperTrader(None)
            with self.assertRaises(paper_trader.PaperMarketShut) as cm:
                pt.market_order("EURCAD", "BUY", 7900)
            res = pt.market_order("BTCUSD", "BUY", 0.01)
        self.assertEqual(str(cm.exception),
                         f"EURCAD: {FOREX_WORDS} — no paper fill")
        self.assertEqual(res["status"], "FILLED")


# ── 4. M3: the CLOSE button ───────────────────────────────────────────────────

class TheCloseButtonWaitsForTheMarketTests(TestCase):
    def setUp(self):
        self.user = _user("mh_close")

    def test_saturday_the_paper_forex_close_is_refused_and_nothing_booked(self):
        from bot_program.manual_close import execute_close
        with _at(SAT):
            _quote(_inst("EURCAD", "forex"), "1.61051500")
            trade = _row(_cfg(self.user))
            out = execute_close(self.user, trade)
        self.assertIn(FOREX_WORDS, out.get("error", ""), out)
        self.assertIn("no paper exit", out["error"])
        self.assertTrue(out.get("still_open"))
        _untouched(self, trade)
        # the claim was released: the button works again on Sunday night
        self.assertNotIn("manual_close_claim", trade.metadata or {})

    def test_saturday_the_preview_says_the_same(self):
        from bot_program.manual_close import preview_close
        with _at(SAT):
            _quote(_inst("EURCAD", "forex"), "1.61051500")
            trade = _row(_cfg(self.user))
            p = preview_close(self.user, trade)
        self.assertIn(FOREX_WORDS, p.get("error", ""), p)
        self.assertTrue(p.get("market_shut"))
        self.assertIsNone(p.get("pnl"))

    def test_the_settling_quarter_hour_refuses_too(self):
        from bot_program.manual_close import execute_close
        with _at(SUN_SETTLING):
            _quote(_inst("EURCAD", "forex"), "1.61200000", age_s=20)
            trade = _row(_cfg(self.user))
            out = execute_close(self.user, trade)
        self.assertIn(SETTLING_WORDS, out.get("error", ""), out)
        _untouched(self, trade)

    def test_sunday_2130_utc_the_same_row_closes(self):
        from bot_program.manual_close import execute_close
        inst = _inst("EURCAD", "forex")
        with _at(SAT):
            _quote(inst, "1.61051500")
            trade = _row(_cfg(self.user))
            self.assertIn("error", execute_close(self.user, trade))
        with _at(SUN_OPEN):
            _quote(inst, "1.61200000")
            out = execute_close(self.user, trade)
        self.assertTrue(out.get("ok"), out)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        # the paper exit, charged half the round trip below the 1.612 mark
        self.assertLess(float(trade.exit_price), 1.612)
        self.assertGreater(float(trade.exit_price), 1.60)

    def test_the_winter_hour_before_22_00_utc_is_refused(self):
        """2026-11-08, 21:30 UTC is 16:30 New York: the week has not opened,
        whatever a poller re-stamped a minute ago (the incident's exit)."""
        from bot_program.manual_close import execute_close
        inst = _inst("EURCAD", "forex")
        with _at(_utc(2026, 11, 8, 21, 30)):
            _quote(inst, "1.61051500", source="yfinance")
            trade = _row(_cfg(self.user))
            out = execute_close(self.user, trade)
        self.assertIn("the forex market is shut (reopens Sunday 22:00 UTC)",
                      out.get("error", ""), out)
        _untouched(self, trade)
        with _at(_utc(2026, 11, 8, 22, 20)):
            _quote(inst, "1.61200000")
            out = execute_close(self.user, trade)
        self.assertTrue(out.get("ok"), out)

    def test_a_crypto_paper_row_closes_on_saturday(self):
        from bot_program.manual_close import execute_close
        with _at(SAT):
            _quote(_inst("BTCUSD", "crypto"), "60000", source="binance")
            trade = _row(_cfg(self.user, "crypto"), "BTCUSD", qty="0.01",
                         entry="59000", stop="58000", target="62000",
                         vpu=1.0)
            out = execute_close(self.user, trade)
        self.assertTrue(out.get("ok"), out)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")

    def test_a_stock_paper_row_is_refused_on_saturday(self):
        from bot_program.manual_close import execute_close
        with _at(SAT):
            _quote(_inst("AAPL", "stock", "NASDAQ"), "227.50",
                   source="yfinance")
            trade = _row(_cfg(self.user, "stock"), "AAPL", qty="10",
                         entry="225", stop="220", target="240", vpu=1.0)
            out = execute_close(self.user, trade)
        self.assertIn("the stock market is shut (reopens Monday 13:30 UTC)",
                      out.get("error", ""), out)
        _untouched(self, trade)

    def test_a_close_the_belt_declines_says_so_not_close_pending(self):
        """The market shuts between the button's gate and _close_trade's
        belt (a click at Friday 20:59:59): the row is OPEN and paper, so
        the live CLOSE_PENDING words would be false."""
        from bot_program import manual_close
        real = manual_close._market_shut_error
        calls = []

        def _open_first(trade):
            calls.append(trade.id)
            return "" if len(calls) == 1 else real(trade)

        client = MagicMock()
        client.ticker.return_value = {"lastPrice": "1.61051500"}
        with _at(SAT):
            trade = _row(_cfg(self.user))
            _inst("EURCAD", "forex")
            with patch.object(manual_close, "_market_shut_error",
                              side_effect=_open_first), \
                    patch(ROUTER, return_value=client):
                out = manual_close.execute_close(self.user, trade)
        self.assertIn(FOREX_WORDS, out.get("error", ""), out)
        self.assertTrue(out.get("still_open"))
        self.assertTrue(out.get("market_shut"))
        self.assertNotIn("CLOSE_PENDING", out["error"])
        self.assertNotIn("pending", out)
        _untouched(self, trade)

    def test_a_live_row_close_path_is_unchanged(self):
        """The venue decides whether a LIVE close fills: the client is
        called exactly as before, on a Saturday too."""
        from bot_program.manual_close import execute_close

        class _FakeLive:
            env = "live"

            def __init__(self):
                self.orders = []

            def ticker(self, symbol):
                return {"lastPrice": "1.61051500"}

            def market_order(self, symbol, side, qty, **kw):
                self.orders.append((symbol, side, float(qty)))
                return {"orderId": "L-1", "status": "FILLED",
                        "avgPrice": "1.61040000", "executedQty": str(qty)}

        fake = _FakeLive()
        with _at(SAT):
            _quote(_inst("EURCAD", "forex"), "1.61051500")
            trade = _row(_cfg(self.user, mode="live"), paper=False)
            with patch(ROUTER, return_value=fake):
                out = execute_close(self.user, trade, pin_ok=True)
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(fake.orders, [("EURCAD", "SELL", 7900.0)])
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.exit_price, Decimal("1.61040000"))


# ── 5. M3: the tick — time stop, SL, the belt ─────────────────────────────────

class TheTickWaitsForTheMarketTests(TestCase):
    def setUp(self):
        self.user = _user("mh_tick")

    def _bot(self, cfg):
        from bot_program.asset_engine.forex_bot import ForexBot
        return ForexBot(cfg)

    def test_a_paper_time_stop_waits_and_books_on_the_next_open_tick(self):
        inst = _inst("EURCAD", "forex")
        with _at(SAT):
            _quote(inst, "1.61051500")
            cfg = _cfg(self.user, max_hold_hours=24)
            trade = _row(cfg, opened_at=SAT - timedelta(hours=30))
            self.assertEqual(self._bot(cfg).manage_positions(), 0)
        _untouched(self, trade)     # never at the entry price, never at 1.6105
        with _at(SUN_OPEN):
            _quote(inst, "1.61200000")
            self.assertEqual(self._bot(cfg).manage_positions(), 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertIn("closed:TIME", trade.reason)
        self.assertNotEqual(trade.exit_price, trade.entry_price)
        self.assertNotIn("time_stop_unpriced", trade.metadata or {})

    def test_the_first_ticks_after_the_reopen_never_book_the_entry(self):
        """Only Friday's quote exists. 21:02 is inside the settling window;
        21:20 is past it with nothing that prices the pair yet — the time
        stop waits for the first price instead of booking the entry."""
        from bot_program.asset_engine import skips
        inst = _inst("EURCAD", "forex")
        _quote_written_at(inst, "1.61051500", _utc(2026, 9, 25, 20, 58, 45))
        with _at(SAT):
            cfg = _cfg(self.user, max_hold_hours=24)
            trade = _row(cfg, opened_at=SAT - timedelta(hours=30))
        for when in (_utc(2026, 9, 27, 21, 2), _utc(2026, 9, 27, 21, 20)):
            with self.subTest(when=when), _at(when):
                self.assertEqual(self._bot(cfg).manage_positions(), 0)
                _untouched(self, trade)
        cfg.refresh_from_db()
        note = skips.last_by_symbol(cfg)["EURCAD"]
        self.assertEqual(note["code"], skips.NO_PRICE)
        self.assertIn("the time stop waits", note["detail"])
        with _at(_utc(2026, 9, 27, 21, 30)):
            _quote(inst, "1.61200000")
            self.assertEqual(self._bot(cfg).manage_positions(), 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertLess(float(trade.exit_price), 1.612)
        self.assertGreater(float(trade.exit_price), 1.611)
        self.assertNotIn("time_stop_unpriced", trade.metadata or {})

    def test_a_dead_feed_still_ends_the_position_after_the_grace(self):
        """Six hours after the reopen nothing has priced it: the feed is
        dead, and the entry price stands in as it always did — said."""
        inst = _inst("EURCAD", "forex")
        _quote_written_at(inst, "1.61051500", _utc(2026, 9, 25, 20, 58, 45))
        with _at(SAT):
            cfg = _cfg(self.user, max_hold_hours=24)
            trade = _row(cfg, opened_at=SAT - timedelta(hours=30))
        with _at(_utc(2026, 9, 28, 3, 30)):
            self.assertEqual(self._bot(cfg).manage_positions(), 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertTrue(trade.metadata.get("time_stop_unpriced"))

    def test_a_stock_time_stop_waits_out_the_delayed_open(self):
        """AAPL, a 24h ceiling long past, Friday's 20:00 quote only. 13:30:30
        is the settling window (a 15-minute-delayed feed still shows
        Friday's close); 13:50 has no price of the session yet; the first
        quote written after the window books it."""
        from bot_program.asset_engine.stock_bot import StockBot
        inst = _inst("AAPL", "stock", "NASDAQ")
        _quote_written_at(inst, "225.00", _utc(2026, 9, 25, 20, 0),
                          source="yfinance")
        with _at(SAT):
            cfg = _cfg(self.user, "stock", max_hold_hours=24)
            trade = _row(cfg, "AAPL", qty="10", entry="225", stop="200",
                         target="260", vpu=1.0,
                         opened_at=SAT - timedelta(hours=72))
        for when in (_utc(2026, 9, 28, 13, 30, 30),
                     _utc(2026, 9, 28, 13, 50)):
            with self.subTest(when=when), _at(when):
                self.assertEqual(StockBot(cfg).manage_positions(), 0)
                _untouched(self, trade)
        _quote_written_at(inst, "230.00", _utc(2026, 9, 28, 13, 55),
                          source="yfinance")
        with _at(_utc(2026, 9, 28, 14, 0)):
            self.assertEqual(StockBot(cfg).manage_positions(), 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertLess(float(trade.exit_price), 230.0)
        self.assertGreater(float(trade.exit_price), 229.0)
        self.assertNotIn("time_stop_unpriced", trade.metadata or {})

    def test_a_restamped_friday_close_at_the_reopen_is_not_booked(self):
        """USDNOK is polled, not streamed: at 21:00:10 the poller wrote
        Friday's 9.50437 under a fresh stamp. Neither 21:00:30 (settling)
        nor 21:16 (that quote predates the window) books it; the first
        quote written after the window does."""
        inst = _inst("USDNOK", "forex")
        with _at(SAT):
            cfg = _cfg(self.user, max_hold_hours=24)
            trade = _row(cfg, "USDNOK", qty="10000", entry="9.49000",
                         stop="9.40000", target="9.70000", vpu=0.105,
                         opened_at=SAT - timedelta(hours=30))
        _quote_written_at(inst, "9.50437", _utc(2026, 9, 27, 21, 0, 10),
                          source="yfinance")
        for when in (_utc(2026, 9, 27, 21, 0, 30),
                     _utc(2026, 9, 27, 21, 16)):
            with self.subTest(when=when), _at(when):
                self.assertEqual(self._bot(cfg).manage_positions(), 0)
                _untouched(self, trade)
        _quote_written_at(inst, "9.51000", _utc(2026, 9, 27, 21, 19, 30),
                          source="yfinance")
        with _at(_utc(2026, 9, 27, 21, 20)):
            self.assertEqual(self._bot(cfg).manage_positions(), 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertLess(float(trade.exit_price), 9.51)
        self.assertGreater(float(trade.exit_price), 9.505)

    def test_the_approach_warning_still_runs_while_shut(self):
        """It reads no price: a ceiling that falls due over the weekend is
        announced before the reopen books it."""
        from alerts.models import Notification
        inst = _inst("EURCAD", "forex")
        with _at(SAT):
            _quote(inst, "1.61051500")
            cfg = _cfg(self.user, max_hold_hours=48)
            trade = _row(cfg, opened_at=SAT - timedelta(hours=40))
            self.assertEqual(self._bot(cfg).manage_positions(), 0)
        _untouched(self, trade)
        self.assertTrue(Notification.objects.filter(
            user=self.user, title__startswith="⧗ Time stop nearing").exists())

    def test_a_paper_stop_crossed_on_saturday_is_not_booked(self):
        with _at(SAT):
            _quote(_inst("EURCAD", "forex"), "1.60000000")   # under the stop
            cfg = _cfg(self.user)
            trade = _row(cfg)
            self.assertEqual(self._bot(cfg).manage_positions(), 0)
            _untouched(self, trade)
            # a client that DOES price it (a paper-stage row on a live
            # client's tick) is not asked either: the row waits whole
            client = MagicMock()
            client.ticker.return_value = {"lastPrice": "1.60000000"}
            with patch(ROUTER, return_value=client):
                self.assertEqual(self._bot(cfg).manage_positions(), 0)
            client.ticker.assert_not_called()
        _untouched(self, trade)

    def test_the_same_stop_books_when_the_gate_is_off(self):
        """The control: the gate, and nothing else, held the row above."""
        with _at(SAT, gate=False):
            cfg = _cfg(self.user)
            trade = _row(cfg)
            client = MagicMock()
            client.ticker.return_value = {"lastPrice": "1.60000000"}
            with patch(ROUTER, return_value=client):
                self.assertEqual(self._bot(cfg).manage_positions(), 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")

    def test_a_live_stop_crossed_on_saturday_is_still_sent(self):
        """LIVE rows never meet the paper clock: the venue decides."""
        from bot_program.asset_engine.stock_bot import StockBot
        client = _live_client()
        with _at(SAT):
            cfg, trade = _live_aapl(self.user)
            with patch(ROUTER, return_value=client):
                self.assertEqual(StockBot(cfg).manage_positions(), 1)
        client.market_order.assert_called_once()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.exit_price, Decimal("97.50"))

    def test_close_trade_is_the_belt_under_every_paper_exit(self):
        """The options expiry close and the TAKE TRADE funding closes call
        _close_trade directly: on a shut market it books nothing."""
        with _at(SAT):
            cfg = _cfg(self.user)
            trade = _row(cfg)
            ok = self._bot(cfg)._close_trade(
                trade, Decimal("1.61"), paper_trader.PaperTrader(cfg),
                reason="EXPIRY_CLOSE")
        self.assertIs(ok, False)
        _untouched(self, trade)


# ── 6. M3: the manual lane's paper ticket ─────────────────────────────────────

def _signal(inst, entry="1.61050", stop="1.60400", target="1.62400"):
    from signals.models import Signal
    return Signal.objects.create(
        instrument=inst, signal_type="technical", direction="bullish",
        urgency="high", title=f"{inst.symbol} bullish", description="d",
        rule_name="test_rule", score=0.8, sub_scores={},
        price_at_signal=Decimal(entry), suggested_entry=Decimal(entry),
        suggested_stop=Decimal(stop), suggested_target=Decimal(target),
        is_active=True)


class TheManualTicketWaitsForTheMarketTests(TestCase):
    def setUp(self):
        self.user = _user("mh_ticket")

    def test_a_paper_forex_ticket_on_saturday_is_refused(self):
        from bot_program.manual_trade import (execute_asset_trade,
                                              execute_take_trade,
                                              preview_asset_trade)
        from bot_program.models import AssetBotTrade
        with _at(SAT):
            inst = _inst("EURCAD", "forex")
            _quote(inst, "1.61051500")
            p = preview_asset_trade(self.user, inst, "BUY")
            out = execute_asset_trade(self.user, inst, "BUY")
            out2 = execute_take_trade(self.user, _signal(inst))
        for res in (p, out, out2):
            self.assertIn(f"EURCAD: {FOREX_WORDS} — no paper fill",
                          res.get("error", ""), res)
            self.assertTrue(res.get("market_shut"))
        self.assertEqual(AssetBotTrade.objects.count(), 0)

    def test_a_live_ticket_on_saturday_is_not_asked(self):
        """The venue decides whether a LIVE ticket fills: the preview is
        the live one, never the paper clock's refusal."""
        from core.platform_control import PlatformComponent
        from bot_program.manual_trade import (manual_config_for,
                                              preview_take_trade)
        for key in ("platform_master", "pipeline_asset_bots"):
            PlatformComponent.objects.get_or_create(
                key=key, defaults={"name": key, "category": "system",
                                   "is_enabled": True})
            PlatformComponent.objects.filter(key=key).update(is_enabled=True)
        cfg = manual_config_for(self.user, "stock")
        cfg.mode = "live"
        cfg.save(update_fields=["mode"])
        client = MagicMock(name="fake_live_client")
        client.ticker.return_value = {"lastPrice": "227.50"}
        with _at(SAT):
            inst = _inst("AAPL", "stock", "NASDAQ")
            _quote(inst, "227.50", source="yfinance")
            with patch(ROUTER, return_value=client):
                p = preview_take_trade(self.user, _signal(
                    inst, entry="227.50", stop="222.00", target="240.00"))
        self.assertFalse(p.get("market_shut"), p)
        self.assertNotIn("market is shut", p.get("error", ""))
        self.assertNotIn("error", p)
        self.assertEqual(p["venue"], "live")


# ── 7. M3: the bots' paper entries ────────────────────────────────────────────

def _seam_cfg(user, mode="paper"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="stock", name=f"MH Seam {mode}", enabled=True,
        mode=mode, symbols=["MHSEAM"], capital=Decimal("10000"),
        base_currency="USD", position_size_pct=2.0,
        max_concurrent_positions=5, max_daily_loss_pct=2.0,
        stop_loss_pct=1.5, take_profit_pct=3.0, entry_score_min=0.6,
        min_signals_for_entry=1, cool_down_minutes=0)


def _seam_signal(symbol, rule="mh_seam_rule"):
    from signals.models import Signal
    return Signal.objects.create(
        instrument=_inst(symbol, "stock"), signal_type="composite",
        direction="bullish", urgency="medium", title=f"{symbol} bullish",
        description="t", rule_name=rule, score=0.85, sub_scores={},
        price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
        suggested_stop=Decimal("95"), suggested_target=Decimal("110"))


def _client(price="150.00"):
    client = MagicMock()
    client.ticker.return_value = {"lastPrice": price}
    client.get_positions.return_value = []
    return client


class TheBotsPaperEntriesWaitTests(TestCase):
    def setUp(self):
        self.user = _user("mh_bot")

    def _last_skip(self, cfg, symbol):
        cfg.refresh_from_db()
        return ((cfg.extras or {}).get("skips") or {}).get(symbol) or {}

    def test_saturday_no_paper_row_is_booked_and_the_skip_says_why(self):
        """A client that prices it (a live client's tick on a paper-stage
        rule) meets execute_entry's gate."""
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        with _at(SAT):
            cfg = _seam_cfg(self.user)
            _seam_signal("MHSEAM")
            with patch(ROUTER, return_value=_client()):
                res = StockBot(cfg).scan_symbol("MHSEAM")
        self.assertIsNone(res)
        self.assertEqual(AssetBotTrade.objects.count(), 0)
        skip = self._last_skip(cfg, "MHSEAM")
        self.assertEqual(skip.get("code"), "market_shut")
        self.assertIn("the stock market is shut (reopens Monday 13:30 UTC)"
                      " — no paper fill", skip.get("detail", ""))

    def test_monday_in_session_the_same_entry_books(self):
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        with _at(MON_NYSE):
            cfg = _seam_cfg(self.user)
            _seam_signal("MHSEAM")
            with patch(ROUTER, return_value=_client()):
                res = StockBot(cfg).scan_symbol("MHSEAM")
        self.assertIsNotNone(res)
        self.assertEqual(AssetBotTrade.objects.filter(paper=True).count(), 1)

    def test_a_live_config_on_saturday_still_reaches_the_venue(self):
        """The control on the live side: the order goes to the client (it
        raises here, so nothing is booked either way)."""
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        from signals.models import RuleControl
        with _at(SAT):
            RuleControl.objects.create(
                rule_name="mh_live_rule", status="active",
                promotion_stage="live_full", stage_entered_at=timezone.now())
            cfg = _seam_cfg(self.user, mode="live")
            _seam_signal("MHSEAM", rule="mh_live_rule")
            client = _client()
            client.market_order.side_effect = RuntimeError("socket closed")
            with patch(ROUTER, return_value=client):
                self.assertIsNone(StockBot(cfg).scan_symbol("MHSEAM"))
        client.market_order.assert_called_once()
        self.assertEqual(self._last_skip(cfg, "MHSEAM").get("code"),
                         "order_error")
        self.assertEqual(AssetBotTrade.objects.count(), 0)

    def test_the_paper_venue_says_market_shut_not_no_price(self):
        """Through PaperTrader itself (a paper config, the real router):
        the ticker's own answer is recorded as the clock, not the feed."""
        from bot_program.asset_engine import StockBot
        with _at(SAT):
            cfg = _seam_cfg(self.user)
            _quote(_seam_signal("MHSEAM").instrument, "150", source="yfinance")
            StockBot(cfg).scan_symbol("MHSEAM")
        skip = self._last_skip(cfg, "MHSEAM")
        self.assertEqual(skip.get("code"), "market_shut")
        self.assertIn("the stock market is shut", skip.get("detail", ""))

    def test_market_shut_is_a_closed_vocabulary_word_with_its_words(self):
        from bot_program import telegram_eye
        from bot_program.asset_engine import skips
        self.assertEqual(skips.MARKET_SHUT, "market_shut")
        self.assertIn("market_shut", telegram_eye.SKIP_WORDS)
        cfg = _seam_cfg(self.user)
        skips.record(cfg, "MHSEAM", skips.MARKET_SHUT, "x")
        cfg.refresh_from_db()
        self.assertIn("nothing is wrong with the feed", skips.diagnose(cfg))


class TheOptionsPaperEntryWaitsTests(TestCase):
    """OptionsBot replaces scan_symbol wholesale: its paper contract meets
    the underlying's clock in its own execute path."""

    @classmethod
    def setUpTestData(cls):
        cls.user = _user("mh_opt")

    def _scan(self, when):
        from bot_program.asset_engine.base import BotDecision
        from bot_program.asset_engine.options_bot import OptionsBot
        from bot_program.models import AssetBotConfig
        from bot_program.options_models import OptionContract
        from portfolio.risk_gate import limits_book
        with _at(when):
            pf = limits_book()
            pf.current_value = Decimal("10000")
            pf.max_single_position_pct = 100.0
            pf.save()
            inst = _inst("AAPL", "stock")
            cfg = AssetBotConfig.objects.create(
                user=self.user, asset_class="options", name="mh_opt",
                enabled=True, mode="paper", symbols=["AAPL"],
                capital=Decimal("1000000"), stop_loss_pct=20.0,
                take_profit_pct=50.0)
            OptionContract.objects.create(
                underlying=inst, strike=Decimal("180"),
                expiry=timezone.now().date() + timedelta(days=30), right="C",
                multiplier=100, bid=Decimal("1.00"), ask=Decimal("1.02"),
                last_price=Decimal("1.01"), iv=0.30, delta=0.41)
            bot = OptionsBot(cfg)
            corr = {"scale": 1.0, "max_corr": 0.0, "peer": "",
                    "threshold": 0.7, "measured": True, "reason": ""}
            with patch.object(bot, "decide", return_value=BotDecision(
                    "BUY", 0.9, ["signal"])), \
                    patch(ROUTER), \
                    patch("portfolio.risk_gate.correlation_state",
                          return_value=corr):
                return cfg, bot.scan_symbol("AAPL")

    def test_saturday_no_paper_contract(self):
        from bot_program.models import AssetBotTrade
        cfg, out = self._scan(SAT)
        self.assertIsNone(out)
        self.assertFalse(AssetBotTrade.objects.exists())
        cfg.refresh_from_db()
        skip = ((cfg.extras or {}).get("skips") or {}).get("AAPL") or {}
        self.assertEqual(skip.get("code"), "market_shut")

    def test_monday_in_session_it_opens(self):
        cfg, out = self._scan(MON_NYSE)
        self.assertIsNotNone(out)
        self.assertGreater(out["contracts"], 0)


# ── 8. M3: the kill switch ────────────────────────────────────────────────────

class TheKillSwitchWaitsForPaperBookingTests(TestCase):
    def test_every_bot_is_disabled_paper_crypto_booked_paper_forex_waits(self):
        from alerts.models import Notification
        from bot_program.engine.kill_switch import execute_kill_switch
        user = _user("mh_kill")
        with _at(SAT):
            _quote(_inst("EURCAD", "forex"), "1.61051500")
            _quote(_inst("BTCUSD", "crypto"), "60000", source="binance")
            fx = _cfg(user, "forex")
            cr = _cfg(user, "crypto")
            eurcad = _row(fx)
            btc = _row(cr, "BTCUSD", qty="0.01", entry="59000",
                       stop="58000", target="62000", vpu=1.0)
            results = execute_kill_switch(user=user, reason="mh test")
        fx.refresh_from_db()
        cr.refresh_from_db()
        self.assertFalse(fx.enabled)
        self.assertFalse(cr.enabled)
        self.assertEqual(results["asset_bots_disabled"], 2)
        btc.refresh_from_db()
        self.assertEqual(btc.status, "CLOSED")
        self.assertEqual(results["asset_positions_closed"], 1)
        _untouched(self, eurcad)
        self.assertEqual(results["paper_waiting"],
                         [f"EURCAD #{eurcad.id}: {FOREX_WORDS}"])
        self.assertEqual(results["errors"], [])
        note = Notification.objects.filter(
            user=user, title__startswith="KILL SWITCH").latest("id")
        self.assertIn("1 paper position(s) were NOT booked because their "
                      "market is shut", note.body)
        self.assertIn("EURCAD", note.body)

    def test_a_live_row_on_saturday_is_flattened_as_before(self):
        from bot_program.engine.kill_switch import execute_kill_switch
        user = _user("mh_kill_live")
        client = _live_client()
        with _at(SAT):
            _cfg_, trade = _live_aapl(user)
            with patch(ROUTER, return_value=client):
                results = execute_kill_switch(user=user, reason="mh test")
        client.market_order.assert_called_once()
        self.assertEqual(results["asset_positions_closed"], 1)
        self.assertEqual(results["paper_waiting"], [])
        self.assertEqual(results["errors"], [])
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")

    def test_after_the_reopen_an_unpriced_paper_row_waits(self):
        """21:02 is settling; 21:20 is past it with only Friday's quote.
        Neither books the entry price nor Friday's quote."""
        from bot_program.engine.kill_switch import execute_kill_switch
        user = _user("mh_kill_reopen")
        inst = _inst("EURCAD", "forex")
        _quote_written_at(inst, "1.61051500", _utc(2026, 9, 25, 20, 58, 45))
        with _at(SAT):
            eurcad = _row(_cfg(user, "forex"))
        with _at(_utc(2026, 9, 27, 21, 2)):
            results = execute_kill_switch(user=user, reason="mh test")
        self.assertEqual(len(results["paper_waiting"]), 1)
        self.assertIn("reopened at Sunday 21:00 UTC",
                      results["paper_waiting"][0])
        _untouched(self, eurcad)
        with _at(_utc(2026, 9, 27, 21, 20)):
            results = execute_kill_switch(user=user, reason="mh test")
        self.assertEqual(len(results["paper_waiting"]), 1)
        self.assertIn("nothing has priced EURCAD since",
                      results["paper_waiting"][0])
        _untouched(self, eurcad)
        with _at(_utc(2026, 9, 27, 21, 30)):
            _quote(inst, "1.61200000")
            results = execute_kill_switch(user=user, reason="mh test")
        self.assertEqual(results["paper_waiting"], [])
        eurcad.refresh_from_db()
        self.assertEqual(eurcad.status, "CLOSED")
        self.assertNotEqual(eurcad.exit_price, eurcad.entry_price)


class TheHQFlattenMessageTests(TestCase):
    def test_a_waiting_paper_row_is_a_warning_that_names_it(self):
        from django.contrib import messages
        from django.contrib.messages import get_messages
        from django.test import Client
        from django.urls import reverse
        admin = get_user_model().objects.create_user(
            username="mh_hq", password="x", is_staff=True, is_superuser=True)
        c = Client()
        c.force_login(admin)
        results = {"bots_disabled": 0, "asset_bots_disabled": 2,
                   "positions_closed": 0, "asset_positions_closed": 1,
                   "portfolio_positions_closed": 0, "errors": [],
                   "paper_waiting": [f"EURCAD #108: {FOREX_WORDS}"]}
        with patch("bot_program.engine.kill_switch.execute_kill_switch",
                   return_value=results), \
                patch("dashboard.views_admin_hq._pin_ok", return_value=True):
            resp = c.post(reverse("flatten_all_positions"),
                          {"pin": "1234", "reason": "mh"})
        got = [(m.level, str(m)) for m in get_messages(resp.wsgi_request)]
        self.assertEqual(len(got), 1, got)
        level, text = got[0]
        self.assertEqual(level, messages.WARNING)
        self.assertIn("1 paper position(s) NOT booked", text)
        self.assertIn("EURCAD #108", text)


# ── 9. M3: the legacy tick ────────────────────────────────────────────────────

class TheLegacyTickWaitsTests(TestCase):
    def _row(self):
        from bot_program.models import BotConfig, BotTrade
        user = _user("mh_legacy")
        cfg = BotConfig.objects.create(user=user, enabled=True, mode="paper",
                                       capital_usdt=Decimal("1000"),
                                       symbols=[])
        _inst("EURCAD", "forex")
        return user, BotTrade.objects.create(
            config=cfg, symbol="EURCAD", side="BUY", qty=Decimal("1000"),
            entry_price=Decimal("1.61"), stop_loss=Decimal("1.605"),
            take_profit=Decimal("1.63"), paper=True, status="OPEN")

    def _tick(self, user, gate, price="1.60000000", when=SAT):
        from bot_program.engine.runner import run_bot_tick
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": price}
        with _at(when, gate=gate), \
                patch("bot_program.engine.runner.client_for_symbol",
                      return_value=client):
            run_bot_tick(user.id)
        return client

    def test_a_paper_legacy_stop_crossed_on_saturday_is_not_booked(self):
        user, trade = self._row()
        client = self._tick(user, gate=True)
        client.ticker.assert_not_called()
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIsNone(trade.exit_price)

    def test_the_control_books_it_with_the_gate_off(self):
        user, trade = self._row()
        self._tick(user, gate=False)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")

    def test_a_paper_legacy_row_is_never_closed_at_a_price_of_0(self):
        """No usable price is no exit: a BUY's stop 'crossed' at 0 was an
        exit at 0."""
        user, trade = self._row()
        self._tick(user, gate=False, price="0")
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIsNone(trade.exit_price)


class TheLegacyTickPaperEntryWaitsTests(TestCase):
    _BARS = [[0, "1.61", "1.62", "1.60", "1.61", "1"]] * 60

    def _tick(self, gate):
        from bot_program.engine import runner
        from bot_program.engine.strategy import Decision
        from bot_program.models import BotConfig, BotTrade
        user = _user("mh_legacy_entry")
        BotConfig.objects.create(user=user, enabled=True, mode="paper",
                                 symbols=["EURCAD"],
                                 capital_usdt=Decimal("1000"))
        _inst("EURCAD", "forex")
        client = MagicMock()
        client.klines.return_value = self._BARS
        client.order_book.return_value = {"bids": [], "asks": []}
        d = Decision(symbol="EURCAD", score=0.9, confidence=0.9,
                     direction="BUY", reasons=["t"], sl_pct=1.5, tp_pct=3.0)
        with _at(SAT, gate=gate), \
                patch.object(runner, "client_for_symbol",
                             return_value=client), \
                patch.object(runner, "broker_name_for_symbol",
                             return_value="paper"), \
                patch.object(runner, "decide", return_value=d), \
                patch.object(runner, "_apply_risk_gate",
                             side_effect=lambda u, s, q, p: (q, "ok")):
            runner.run_bot_tick(user.id)
        return BotTrade.objects.filter(symbol="EURCAD").count()

    def test_saturday_no_paper_legacy_row(self):
        self.assertEqual(self._tick(gate=True), 0)

    def test_the_control_books_it_with_the_gate_off(self):
        self.assertEqual(self._tick(gate=False), 1)


# ── 10. the read-only position review ─────────────────────────────────────────

class ThePositionReviewKeepsItsMarkTests(TestCase):
    def test_a_live_position_is_still_marked_on_saturday(self):
        """The review marks every position, LIVE ones included, read-only:
        the paper clock decides what paper may book, never what it sees."""
        from brain.position_review import usable_mark
        with _at(SAT):
            _quote(_inst("AAPL", "stock", "NASDAQ"), "227.50",
                   source="yfinance")
            price, source = usable_mark("AAPL")
        self.assertEqual(price, 227.5)
        self.assertEqual(source, "quote")
