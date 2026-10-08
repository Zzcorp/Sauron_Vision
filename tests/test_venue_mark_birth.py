"""THE BIRTH GAP: a real row is never valued against another instrument's
quote (2026-10-08).

The operator opened Gold Spot (XAUUSD) at eToro by TAKE TRADE and the
portfolio read about +18 while eToro read about -0.25. The new row carried
no venue mark yet — only the manage tick wrote one, a beat later at best
and never for a config nothing ticks — so the book fell back to the
platform's LiveQuote, which for XAUUSD is Yahoo's GC=F, the gold FUTURE,
above spot, and the basis rendered as P&L.

What is pinned here:
  * the case: a real XAUUSD row, entry at a spot fill, the quote a future
    ~18 above it — no stamp: no P&L at all ("awaiting_venue", the cells say
    they wait for the venue's price); the fill's stamp: about zero; a stale
    stamp: valued at it, with its age; a stamp past the bound: no P&L; a
    paper row and a real forex row: their quote, as before;
  * the stand-in symbols come from public_feed.YF_SYMBOL_MAP, not a list;
  * the fill is stamped by both lanes (TAKE TRADE, a bot entry, a working
    entry's fill), a working ticket is not;
  * the bar refresh stamps the venue's own candle close on the open real
    rows of that symbol (a row nothing ticks included), never from the
    public feed, never over a newer stamp;
  * every reader of a real row's price goes through venue_mark.resolve:
    the pages, the book value, the position summary, the digest, the
    reconcile's orphan close, the kill switch, the close dialog;
  * nothing that decides reads the stamp.

Run with:  python manage.py test tests.test_venue_mark_birth
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

SPOT_FILL = Decimal("2650.00")       # eToro's fill, the CFD on spot
FUTURE = Decimal("2668.00")          # Yahoo's GC=F, about 18 above
ROUTER = "bot_program.engine.broker_router.client_for_symbol"


def _instrument(symbol, asset_class, name=None):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": name or symbol,
                                 "asset_class": asset_class})
    return inst


def _quote(symbol, last, *, asset_class, source="yfinance", age_s=0):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    q, _ = LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": source})
    if age_s:
        LiveQuote.objects.filter(pk=q.pk).update(
            updated_at=timezone.now() - timedelta(seconds=age_s))
        q.refresh_from_db()
    return q


def _cfg(user, asset_class="commodity", name="manual", **kw):
    from bot_program.models import AssetBotConfig
    defaults = {"enabled": True, "mode": "live", "symbols": [],
                "capital": Decimal("10000")}
    defaults.update(kw)
    return AssetBotConfig.objects.create(user=user, asset_class=asset_class,
                                         name=name, **defaults)


def _gold(cfg, *, paper=False, meta=None, entry=SPOT_FILL, qty="1",
          status="OPEN"):
    from bot_program.models import AssetBotTrade
    m = {"initial_stop_loss": 2630.0, "broker": "etoro"}
    if paper:
        m.pop("broker")
    m.update(meta or {})
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="commodity", symbol="XAUUSD", side="BUY",
        qty=Decimal(qty), entry_price=Decimal(str(entry)),
        stop_loss=Decimal("2630"), take_profit=Decimal("2700"),
        status=status, paper=paper, rule_name="manual_take", metadata=m)


def _stamp(price, *, age_s=0, via="tick", source="etoro"):
    at = timezone.now() - timedelta(seconds=age_s)
    return {"venue_mark": {"price": float(price), "at": at.isoformat(),
                           "source": source, "via": via}}


def _row(user, trade):
    from portfolio.services import unified_open_positions
    rows = [r for r in unified_open_positions(user)
            if getattr(r, "trade_id", None) == trade.id]
    assert len(rows) == 1, rows
    return rows[0]


class TheStandInSymbolsTests(SimpleTestCase):
    """The basis symbols are read off the one map of what Yahoo quotes."""

    def test_every_future_and_cash_index_spelling_is_a_stand_in(self):
        from bot_program.venue_mark import quote_stand_in
        from market_data.public_feed import YF_SYMBOL_MAP, yf_stand_in
        self.assertEqual(yf_stand_in("XAUUSD"), "future")
        self.assertEqual(yf_stand_in("xagusd"), "future")
        self.assertEqual(yf_stand_in("NGUSD"), "future")
        self.assertEqual(yf_stand_in("SPX500"), "cash index")
        self.assertEqual(yf_stand_in("NSDQ100"), "cash index")
        for same in ("EURUSD", "USDJPY", "BTCUSD", "AAPL", "BRK.B", "SQ"):
            self.assertEqual(yf_stand_in(same), "", same)
        for sym, ysym in YF_SYMBOL_MAP.items():
            want = ("future" if ysym.endswith("=F") else
                    "cash index" if ysym.startswith("^")
                    or ysym.endswith(".NYB") else "")
            self.assertEqual(quote_stand_in(sym), want, sym)

    def test_a_quote_the_rows_own_venue_wrote_is_its_venues_rate(self):
        from types import SimpleNamespace

        from bot_program.venue_mark import quote_stand_in
        own = SimpleNamespace(source="etoro", last=Decimal("2650"))
        yahoo = SimpleNamespace(source="yfinance", last=Decimal("2668"))
        self.assertEqual(quote_stand_in("XAUUSD", own, carrier="etoro"), "")
        self.assertEqual(quote_stand_in("XAUUSD", yahoo, carrier="etoro"),
                         "future")


class TheGoldCaseTests(TestCase):
    """The operator's case on the book: entry at eToro's spot fill, the
    platform's quote the gold future about 18 above it."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmb_g",
                                                         password="x")
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD", "commodity", "Gold Spot")
        _quote("XAUUSD", FUTURE, asset_class="commodity")

    def test_no_stamp_is_no_pnl_never_the_basis(self):
        t = _gold(self.cfg)
        row = _row(self.user, t)
        self.assertIsNone(row.current_price)
        self.assertIsNone(row.unrealized_pnl, "the +18 basis is not P&L")
        self.assertIsNone(row.unrealized_pnl_pct)
        self.assertEqual(row.mark_source, "awaiting_venue")

    def test_the_fill_stamp_reads_about_zero(self):
        from bot_program import venue_mark
        t = _gold(self.cfg, meta={"venue_mark": venue_mark.at_fill(
            SPOT_FILL, source="etoro")})
        row = _row(self.user, t)
        self.assertEqual(row.mark_source, "venue")
        self.assertEqual(row.mark_via, "fill")
        self.assertAlmostEqual(row.unrealized_pnl, 0.0, places=6)
        # eToro moves a quarter down: the page follows eToro, not GC=F
        venue_mark.stamp(t, SPOT_FILL - Decimal("0.25"), source="etoro",
                         via="tick")
        row = _row(self.user, t)
        self.assertAlmostEqual(row.unrealized_pnl, -0.25, places=6)
        self.assertEqual(row.current_price, Decimal("2649.75"))

    def test_a_stale_stamp_values_the_row_and_says_its_age(self):
        from bot_program.venue_mark import MAX_AGE_S
        t = _gold(self.cfg, meta=_stamp("2649.75", age_s=2 * 3600))
        row = _row(self.user, t)
        self.assertEqual(row.mark_source, "venue_stale")
        self.assertGreater(row.mark_age_s, MAX_AGE_S)
        self.assertAlmostEqual(row.mark_age_s, 7200, delta=30)
        self.assertAlmostEqual(row.unrealized_pnl, -0.25, places=6)
        self.assertEqual(row.current_price, Decimal("2649.75"))

    def test_a_stamp_past_the_bound_is_no_price_at_all(self):
        from bot_program.venue_mark import STALE_MAX_AGE_S
        t = _gold(self.cfg, meta=_stamp("2649.75",
                                        age_s=STALE_MAX_AGE_S + 60))
        row = _row(self.user, t)
        self.assertIsNone(row.unrealized_pnl)
        self.assertEqual(row.mark_source, "awaiting_venue")
        self.assertGreater(row.mark_age_s, STALE_MAX_AGE_S)

    def test_a_paper_gold_row_reads_its_quote_as_before(self):
        paper_cfg = _cfg(self.user, name="paper gold", mode="paper")
        t = _gold(paper_cfg, paper=True)
        row = _row(self.user, t)
        self.assertEqual(row.mark_source, "quote")
        self.assertEqual(row.current_price, FUTURE)
        self.assertAlmostEqual(row.unrealized_pnl, 18.0, places=6)

    def test_the_book_value_leaves_the_unpriced_real_row_out(self):
        from portfolio.services import live_book_value
        _gold(self.cfg)
        book = live_book_value(self.user)
        self.assertEqual(book.n_unpriced, 1)
        self.assertIsNone(book.unrealized,
                          "the basis is not booked as open P&L")


class TheSameInstrumentTests(TestCase):
    """Where the platform's quote IS the venue's instrument, the PR40
    fallback stays."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmb_fx",
                                                         password="x")
        self.cfg = _cfg(self.user, asset_class="forex", name="fx")

    def _fx(self, meta=None):
        from bot_program.models import AssetBotTrade
        m = {"broker": "etoro", "value_per_unit": 1.0}
        m.update(meta or {})
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class="forex", symbol="EURUSD",
            side="BUY", qty=Decimal("1000"), entry_price=Decimal("1.1000"),
            stop_loss=Decimal("1.09"), take_profit=Decimal("1.12"),
            status="OPEN", paper=False, rule_name="r", metadata=m)

    def test_a_real_forex_row_with_no_stamp_reads_its_quote(self):
        _quote("EURUSD", "1.1010", asset_class="forex",
               source="oanda_stream")
        row = _row(self.user, self._fx())
        self.assertEqual(row.mark_source, "quote")
        self.assertEqual(row.current_price, Decimal("1.1010"))
        self.assertAlmostEqual(row.unrealized_pnl, 1.0, places=6)

    def test_a_stale_stamp_gives_way_to_a_same_instrument_quote(self):
        _quote("EURUSD", "1.1010", asset_class="forex",
               source="oanda_stream")
        row = _row(self.user, self._fx(_stamp("1.1005", age_s=3600)))
        self.assertEqual(row.mark_source, "quote")

    def test_a_stale_stamp_beats_no_quote_at_all(self):
        _instrument("EURUSD", "forex")
        row = _row(self.user, self._fx(_stamp("1.1005", age_s=3600)))
        self.assertEqual(row.mark_source, "venue_stale")
        self.assertAlmostEqual(row.unrealized_pnl, 0.5, places=6)


class ThePagesSayWhichMarkTests(TestCase):
    """The positions page and the portfolio page: the words for each state,
    and never the basis."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("vmb_pg",
                                                         password="x")
        self.client.force_login(self.user)
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD", "commodity", "Gold Spot")
        _quote("XAUUSD", FUTURE, asset_class="commodity")

    def _bodies(self):
        return [self.client.get(u, HTTP_HOST="127.0.0.1").content.decode()
                for u in ("/positions/", "/portfolio/")]

    def test_a_row_with_no_venue_price_waits_on_both_pages(self):
        _gold(self.cfg)
        for body in self._bodies():
            self.assertIn("waiting for the venue&#x27;s price", body)
            self.assertIn('data-mark-source="awaiting_venue"', body)
            self.assertNotIn("+18.00", body)

    def test_a_stale_stamp_says_its_age_on_both_pages(self):
        _gold(self.cfg, meta=_stamp("2649.75", age_s=2 * 3600))
        for body in self._bodies():
            self.assertIn('data-mark-source="venue_stale"', body)
            self.assertIn("venue · 2 h old", body)
            self.assertNotIn("+18.00", body)

    def test_a_fresh_stamp_says_venue_on_the_portfolio_page_too(self):
        _gold(self.cfg, meta=_stamp("2649.75", age_s=60))
        pf = self._bodies()[1]
        self.assertIn('data-mark-source="venue"', pf)

    def test_the_words(self):
        from types import SimpleNamespace

        from dashboard.views import _mark_words
        w = _mark_words(SimpleNamespace(mark_source="venue", mark_age_s=120,
                                        mark_via="fill", paper=False))
        self.assertEqual(w["mark_word"], "venue")
        self.assertIn("read 2 min ago at the fill", w["mark_title"])
        w = _mark_words(SimpleNamespace(mark_source="awaiting_venue",
                                        mark_age_s=None, mark_via="",
                                        paper=False))
        self.assertEqual(w["mark_wait"], "waiting for the venue's price")
        self.assertIn("different instrument", w["mark_title"])
        w = _mark_words(SimpleNamespace(mark_source="venue_stale",
                                        mark_age_s=3 * 86400,
                                        mark_via="candle", paper=False))
        self.assertEqual(w["mark_word"], "venue · 3 days old")
        self.assertIn("from the venue's latest candle", w["mark_title"])


class TheSummaryAndTheDigestTests(TestCase):
    """The position summary and the digest read the row's own mark."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmb_sd",
                                                         password="x")
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD", "commodity", "Gold Spot")
        _quote("XAUUSD", FUTURE, asset_class="commodity")

    def test_the_summary_waits_and_never_shows_the_basis(self):
        from dashboard.position_summary import DASH, build_summary
        t = _gold(self.cfg)
        s = build_summary(t)
        self.assertEqual(s["big_value"], DASH)
        self.assertIn("Waiting for the venue's price", s["big_sub"])
        price_now = [f for f in s["facts"] if f["label"] == "Price now"][0]
        self.assertIn("waiting for the venue's price", str(price_now))
        self.assertTrue(any("different instrument" in n["text"]
                            for n in s["notes"]))

    def test_the_summary_dates_a_venue_price_by_the_venue(self):
        from dashboard.position_summary import build_summary, utc_clock
        t = _gold(self.cfg, meta=_stamp("2649.75", age_s=2 * 3600))
        s = build_summary(t)
        price_now = [f for f in s["facts"] if f["label"] == "Price now"][0]
        at = t.metadata["venue_mark"]["at"]
        from django.utils.dateparse import parse_datetime
        self.assertIn(utc_clock(parse_datetime(at)), str(price_now))
        self.assertIn("venue's own rate", str(price_now))
        self.assertTrue(any("came in 2 hours ago" in n["text"]
                            or "2 hours" in n["text"] for n in s["notes"]),
                        s["notes"])

    def test_the_digest_line_waits_for_the_venue(self):
        from alerts.digest_book import position_item
        t = _gold(self.cfg)
        item = position_item(_row(self.user, t), t)
        self.assertIsNone(item["pnl"])
        self.assertIn("waiting for the venue's price", item["line"])
        t2 = _gold(self.cfg, meta=_stamp("2649.75", age_s=2 * 3600))
        item = position_item(_row(self.user, t2), t2)
        self.assertIn("venue price 2 h old", item["line"])


class TheFillIsStampedTests(TestCase):
    """Both lanes book a real row with its fill as its venue mark."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("vmb_tt",
                                                         password="x")

    def test_a_live_take_trade_is_born_marked_at_its_fill(self):
        from bot_program.models import AssetBotTrade
        from tests.test_take_trade_live import (_arm_live, _components_on,
                                                _fake_live_client, _quote as q,
                                                _signal)
        inst = q("BTCUSD", 60000)          # the platform's quote
        _components_on()
        _arm_live(self.user)
        from bot_program.manual_trade import execute_take_trade
        with mock.patch(ROUTER, return_value=_fake_live_client()):
            out = execute_take_trade(self.user, _signal(inst), pin_ok=True)
        self.assertTrue(out.get("ok"), out)
        t = AssetBotTrade.objects.get(pk=out["trade_id"])
        vm = t.metadata["venue_mark"]
        self.assertEqual((vm["price"], vm["via"]), (60012.5, "fill"))
        row = _row(self.user, t)
        self.assertEqual(row.mark_source, "venue")
        self.assertAlmostEqual(row.unrealized_pnl, 0.0, places=6)

    def test_a_working_take_trade_carries_no_stamp(self):
        from bot_program.models import AssetBotTrade
        from tests.test_take_trade_live import (_arm_live, _components_on,
                                                _fake_live_client, _quote as q,
                                                _signal)
        inst = q("BTCUSD", 60000)
        _components_on()
        _arm_live(self.user)
        held = {"orderId": "7", "symbol": "BTCUSD", "side": "BUY",
                "executedQty": "0.0", "avgPrice": "0.0",
                "status": "PENDING", "working": True, "raw": {}}
        from bot_program.manual_trade import execute_take_trade
        with mock.patch(ROUTER, return_value=_fake_live_client(held)):
            out = execute_take_trade(self.user, _signal(inst), pin_ok=True)
        self.assertTrue(out.get("working"), out)
        t = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertNotIn("venue_mark", t.metadata)

    def test_a_working_entrys_fill_stamps_the_venues_fill(self):
        from instruments.models import Instrument
        from tests.test_working_entries import (_cfg as wcfg,
                                                _client as wclient,
                                                _working_trade)
        Instrument.objects.get_or_create(
            symbol="NVDA", defaults={"name": "NVDA", "asset_class": "stock"})
        cfg = wcfg(self.user)
        trade = _working_trade(cfg)
        from bot_program.asset_engine.stock_bot import StockBot
        with mock.patch(ROUTER, return_value=wclient(
                {"state": "filled", "filled": 10.0, "avgPrice": 99.75,
                 "status": "Filled"})):
            StockBot(cfg).manage_positions()
        trade.refresh_from_db()
        self.assertNotIn("entry_working", trade.metadata)
        vm = trade.metadata["venue_mark"]
        self.assertEqual((vm["price"], vm["via"]), (99.75, "fill"))


class TheBotEntryIsStampedTests(TestCase):
    """execute_entry on a LIVE stock config carried by the real EtoroTrader
    over a fake wire (tests.test_entry_quote's last-look fixture)."""

    def setUp(self):
        from tests.test_entry_quote import (_account, _book,
                                            _clear_eligibility, _instrument,
                                            _live_cfg, _signal, _user)
        self.user = _user("vmb_bot")
        self.cfg = _live_cfg(self.user, name="VMB")
        self.cfg.base_currency = "USD"
        self.cfg.extras = {}
        self.cfg.save(update_fields=["base_currency", "extras"])
        _signal(_instrument(), rule="vmb_rule")
        _book(self.user)
        _account(self.user, cash=100000)
        p = mock.patch("bot_program.asset_engine.base.ETORO_PROVEN",
                       frozenset({"stock"}))
        p.start()
        self.addCleanup(p.stop)
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def test_a_bot_entry_is_born_marked_at_the_venues_fill(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotTrade
        from tests.test_entry_quote import _etoro, _mock_client
        bot = StockBot(self.cfg)
        with mock.patch(ROUTER, return_value=_mock_client("100.00")):
            cand = bot.propose_entry("AAPL")
        self.assertIsNotNone(cand)
        t, _fake = _etoro()
        with mock.patch(ROUTER, return_value=t), mock.patch("time.sleep"):
            res = bot.execute_entry(cand)
        self.assertIsNotNone(res)
        trade = AssetBotTrade.objects.get(id=res["trade_id"])
        vm = trade.metadata["venue_mark"]
        self.assertEqual((vm["price"], vm["source"], vm["via"]),
                         (float(trade.entry_price), "etoro", "fill"))


class TheCandleStampTests(TestCase):
    """The bar refresh stamps the venue's own candle close on the open real
    rows of the symbol it just read — a row nothing ticks included."""

    def setUp(self):
        cache.clear()
        from bot_program import venue_health
        from bot_program.engine import etoro_client as ec
        venue_health.reset()
        self.addCleanup(venue_health.reset)
        self.addCleanup(cache.clear)
        for memo in (ec._SEARCH_IDS, ec._SEARCH_NO, ec._RATE_PAUSE):
            memo.clear()
            self.addCleanup(memo.clear)
        from tests.test_bars_etoro_quota import _Clock, _Feed, _Wire
        self.user = get_user_model().objects.create_user("vmb_bars",
                                                         password="x")
        _instrument("XAUUSD", "commodity", "Gold Spot")
        _quote("XAUUSD", FUTURE, asset_class="commodity")
        # XAUUSD is pinned to eToro's id 18: no /search.
        self.wire = _Wire({"XAUUSD": 18})
        self.feed = _Feed()
        self.clock = _Clock()

    def _client(self, *_a, **_k):
        from bot_program.engine.etoro_client import EtoroTrader
        t = EtoroTrader("k", "u", env="live")
        t._session = self.wire
        return t

    def _run(self, client_for=None):
        from market_data import bot_bars
        with mock.patch.object(bot_bars, "_client_for",
                               side_effect=client_for or self._client), \
                mock.patch.object(bot_bars, "_public_market_data_client",
                                  return_value=self.feed), \
                mock.patch.object(bot_bars, "_mono", self.clock.mono), \
                mock.patch.object(bot_bars, "_candle_sleep",
                                  self.clock.sleep), \
                mock.patch.object(bot_bars, "refresh_watchlist_bars",
                                  return_value={}):
            return bot_bars.refresh_bot_bars()

    def test_a_row_on_a_config_switched_off_is_stamped_from_the_candles(self):
        cfg = _cfg(self.user, enabled=False)      # nothing ticks it
        t = _gold(cfg)
        paper = _gold(_cfg(self.user, name="paper", mode="paper",
                           enabled=False), paper=True)
        self._run()
        t.refresh_from_db()
        vm = t.metadata["venue_mark"]
        self.assertEqual((vm["price"], vm["source"], vm["via"]),
                         (1.15, "etoro", "candle"))
        paper.refresh_from_db()
        self.assertNotIn("venue_mark", paper.metadata)
        row = _row(self.user, t)
        self.assertEqual(row.mark_source, "venue")

    def test_a_newer_stamp_is_kept(self):
        cfg = _cfg(self.user, enabled=False)
        t = _gold(cfg, meta=_stamp("2649.75", age_s=0))
        # the candle grid ends now: the tick's stamp a second in the future
        # of the candle's is the newer print
        from bot_program import venue_mark
        later = timezone.now() + timedelta(seconds=5)
        venue_mark.stamp(t, "2649.80", source="etoro", now=later, via="tick")
        self._run()
        t.refresh_from_db()
        self.assertEqual(t.metadata["venue_mark"]["price"], 2649.80)

    def test_the_public_feed_never_stamps(self):
        from market_data import bot_bars
        cfg = _cfg(self.user, enabled=False)
        t = _gold(cfg)

        class _Yahoo:
            _sv_public_feed = True

            def klines(self, *a, **k):
                return [[1, "1", "1", "1", "2668", "1"]]

        self.assertEqual(bot_bars._stamp_venue_rows(
            _Yahoo(), "XAUUSD", "1h", [[1, "1", "1", "1", "2668", "1"]]), 0)
        self.assertEqual(bot_bars._stamp_venue_rows(
            mock.MagicMock(), "XAUUSD", "1h",
            [[1, "1", "1", "1", "2668", "1"]]), 0, "no carrier, no stamp")
        t.refresh_from_db()
        self.assertNotIn("venue_mark", t.metadata)


class TheExitPathsTests(TestCase):
    """The two exit paths that fell back to the LiveQuote go through the
    one answer: never the future's price on a real gold row."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmb_ex",
                                                         password="x")
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD", "commodity", "Gold Spot")
        _quote("XAUUSD", FUTURE, asset_class="commodity")

    def _dead_ticker(self):
        c = mock.MagicMock(spec=["ticker"])
        c.ticker.side_effect = RuntimeError("eToro unreachable")
        return c

    def test_the_orphan_close_books_the_venue_mark_not_the_future(self):
        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import _close_as_orphan
        t = _gold(self.cfg, meta=_stamp("2649.75", age_s=600))
        with mock.patch(ROUTER, return_value=self._dead_ticker()):
            _close_as_orphan(t)
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertEqual(t.status, "CLOSED")
        self.assertEqual(t.exit_price, Decimal("2649.75"))
        self.assertAlmostEqual(float(t.pnl), -0.25, places=6)

    def test_the_orphan_close_with_no_venue_price_is_unpriced(self):
        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import (UNPRICED_EXIT_KEY,
                                                 _close_as_orphan)
        t = _gold(self.cfg)
        with mock.patch(ROUTER, return_value=self._dead_ticker()):
            _close_as_orphan(t)
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertIsNone(t.pnl, "the +18 basis is not realized P&L")
        self.assertTrue(t.metadata.get(UNPRICED_EXIT_KEY))

    def test_the_kill_switch_never_books_the_future(self):
        from bot_program.engine.kill_switch import _market_exit_price
        dead = self._dead_ticker()
        t = _gold(self.cfg)
        self.assertEqual(_market_exit_price("XAUUSD", t.entry_price,
                                            client=dead, trade=t),
                         float(SPOT_FILL))
        t2 = _gold(self.cfg, meta=_stamp("2649.75", age_s=60))
        self.assertEqual(_market_exit_price("XAUUSD", t2.entry_price,
                                            client=dead, trade=t2), 2649.75)
        # a paper row, and a call with no trade: as before
        paper = _gold(_cfg(self.user, name="p", mode="paper"), paper=True)
        self.assertEqual(_market_exit_price("XAUUSD", paper.entry_price,
                                            client=dead, trade=paper),
                         float(FUTURE))
        self.assertEqual(_market_exit_price("XAUUSD", SPOT_FILL,
                                            client=dead), float(FUTURE))

    def test_the_close_dialog_stamps_the_venue_rate_it_read(self):
        from bot_program.manual_close import preview_close
        from bot_program.models import AssetBotTrade
        from tests.test_manual_close import _live_trade, _quote as mq
        inst = mq("BTCUSD", 60000)
        t = _live_trade(self.user, inst)
        live = mock.MagicMock(name="live_client")
        live.ticker.return_value = {"lastPrice": "60100"}
        with mock.patch(ROUTER, return_value=live):
            p = preview_close(self.user, t)
        self.assertNotIn("error", p)
        t = AssetBotTrade.objects.get(pk=t.pk)
        vm = t.metadata["venue_mark"]
        self.assertEqual((vm["price"], vm["via"]), (60100.0, "close dialog"))
        self.assertAlmostEqual(_row(self.user, t).unrealized_pnl,
                               float(p["pnl"]), places=2)


class TheOneFunctionTests(SimpleTestCase):
    """Every reader of a real row's price goes through venue_mark.resolve,
    and nothing that decides reads the stamp."""

    def test_the_readers_go_through_resolve(self):
        import inspect

        from bot_program import reconcile_asset
        from bot_program.engine import kill_switch
        from portfolio import services
        self.assertIn("_venue_resolve(trade, quote)",
                      inspect.getsource(services._trade_to_position))
        self.assertIn("venue_mark.resolve(trade, lq)",
                      inspect.getsource(reconcile_asset._close_as_orphan))
        self.assertIn("venue_mark.resolve(trade, quote)",
                      inspect.getsource(kill_switch._market_exit_price))
        self.assertIn("client=client, trade=trade)",
                      inspect.getsource(kill_switch._close_asset_trade))

    def test_nothing_that_decides_reads_the_stamp(self):
        import inspect

        from bot_program import mark_sanity, position_care
        for mod in (mark_sanity, position_care):
            self.assertNotIn("venue_mark", inspect.getsource(mod),
                             mod.__name__)

    def test_the_review_reads_the_venue_only_for_a_real_bot_row(self):
        """The position review measures a REAL bot row where its stop
        lives — at the venue's price (review, 2026-10-08: "+0.90R, take
        part off" on a real gold row eToro showed at a small loss). One
        door, `_venue_mark_for`; `usable_mark` itself never reads it."""
        import inspect

        from brain import position_review
        self.assertNotIn("venue_mark", inspect.getsource(
            position_review.usable_mark))
        self.assertIn("_venue_mark_for(pos)", inspect.getsource(
            position_review.measure))


class TheClosingSideTests(TestCase):
    """eToro shows an open long at its bid and a short at its ask: a new
    row reads minus the spread, as eToro reads it (review, 2026-10-08)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmb_cs",
                                                         password="x")
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD", "commodity", "Gold Spot")
        _quote("XAUUSD", FUTURE, asset_class="commodity")

    def test_a_fill_with_its_spread_reads_minus_the_spread(self):
        from bot_program import venue_mark
        vm = venue_mark.at_fill(SPOT_FILL, source="etoro",
                                bid=2649.75, ask=2650.00)
        long_ = _gold(self.cfg, meta={"venue_mark": vm})
        self.assertAlmostEqual(_row(self.user, long_).unrealized_pnl, -0.25,
                               places=6)
        short = _gold(self.cfg, meta={"venue_mark": venue_mark.at_fill(
            2649.75, source="etoro", bid=2649.75, ask=2650.00)},
            entry="2649.75")
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(pk=short.pk).update(side="SELL")
        short.refresh_from_db()
        self.assertAlmostEqual(_row(self.user, short).unrealized_pnl, -0.25,
                               places=6)

    def test_a_crossed_or_missing_pair_falls_back_to_the_price(self):
        from bot_program import venue_mark
        self.assertNotIn("bid", venue_mark.at_fill(SPOT_FILL, bid=2651,
                                                   ask=2650))
        self.assertNotIn("bid", venue_mark.at_fill(SPOT_FILL, bid=None,
                                                   ask=2650))
        t = _gold(self.cfg, meta={"venue_mark": venue_mark.at_fill(
            SPOT_FILL, source="etoro")})
        self.assertAlmostEqual(_row(self.user, t).unrealized_pnl, 0.0,
                               places=6)

    def test_the_tick_stamps_the_tickers_two_sides(self):
        from bot_program import venue_mark
        t = _gold(self.cfg)
        self.assertTrue(venue_mark.stamp(t, "2650.10", source="etoro",
                                         via="tick", bid="2649.95",
                                         ask="2650.25"))
        t.refresh_from_db()
        vm = t.metadata["venue_mark"]
        self.assertEqual((vm["bid"], vm["ask"]), (2649.95, 2650.25))
        self.assertAlmostEqual(_row(self.user, t).unrealized_pnl, -0.05,
                               places=6)

    def test_the_manage_tick_hands_its_ticker_sides_to_the_stamp(self):
        import inspect

        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot._mark_price)
        self.assertIn("_last_ticks", src)
        self.assertIn('bid=_tk.get("bid")', inspect.getsource(
            AssetBot.manage_positions))


class TheNewerPrintTests(TestCase):
    """A same-instrument quote never outranks a NEWER venue print."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmb_np",
                                                         password="x")
        self.cfg = _cfg(self.user, asset_class="forex")
        _instrument("EURUSD", "forex")

    def _eur(self, meta):
        from bot_program.models import AssetBotTrade
        m = {"initial_stop_loss": 1.09, "broker": "etoro"}
        m.update(meta)
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class="forex", symbol="EURUSD", side="BUY",
            qty=Decimal("10000"), entry_price=Decimal("1.1000"),
            stop_loss=Decimal("1.09"), status="OPEN", paper=False,
            rule_name="manual_take", metadata=m)

    def test_a_dead_feeds_old_quote_loses_to_a_newer_venue_print(self):
        from bot_program import venue_mark
        _quote("EURUSD", "1.1000", asset_class="forex",
               source="oanda_stream", age_s=3 * 3600)
        t = self._eur(_stamp("1.1050", age_s=20 * 60))
        from market_data.models import LiveQuote
        mk = venue_mark.resolve(t, LiveQuote.objects.get(
            instrument__symbol="EURUSD"))
        self.assertEqual((mk.source, mk.price), (venue_mark.VENUE_STALE,
                                                 1.105))

    def test_a_newer_quote_still_wins_over_an_old_print(self):
        from bot_program import venue_mark
        _quote("EURUSD", "1.1010", asset_class="forex",
               source="oanda_stream")
        t = self._eur(_stamp("1.1050", age_s=20 * 60))
        from market_data.models import LiveQuote
        mk = venue_mark.resolve(t, LiveQuote.objects.get(
            instrument__symbol="EURUSD"))
        self.assertEqual((mk.source, mk.price), (venue_mark.QUOTE, 1.101))


class TheBookingRuleTests(TestCase):
    """Showing a stale venue price with its age is honest; BOOKING a close
    at it is not, unless the market is shut or the print is under an hour
    (review, 2026-10-08)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmb_bk",
                                                         password="x")
        self.cfg = _cfg(self.user)
        _instrument("XAUUSD", "commodity", "Gold Spot")
        _quote("XAUUSD", FUTURE, asset_class="commodity")
        self.open = mock.patch(
            "bot_program.engine.paper_trader.paper_market_shut",
            return_value="")
        self.shut = mock.patch(
            "bot_program.engine.paper_trader.paper_market_shut",
            return_value="the market is shut")

    def _dead(self):
        c = mock.MagicMock(spec=["ticker"])
        c.ticker.side_effect = RuntimeError("eToro unreachable")
        return c

    def test_the_rule(self):
        from bot_program import venue_mark
        from market_data.models import LiveQuote
        q = LiveQuote.objects.get(instrument__symbol="XAUUSD")
        fresh = _gold(self.cfg, meta=_stamp("2649.75", age_s=60))
        hour = _gold(self.cfg, meta=_stamp("2649.75", age_s=40 * 60))
        old = _gold(self.cfg, meta=_stamp("2649.75", age_s=3 * 3600))
        none = _gold(self.cfg)
        with self.open:
            self.assertTrue(venue_mark.bookable(venue_mark.resolve(fresh, q),
                                                fresh))
            self.assertTrue(venue_mark.bookable(venue_mark.resolve(hour, q),
                                                hour))
            self.assertFalse(venue_mark.bookable(venue_mark.resolve(old, q),
                                                 old))
            self.assertFalse(venue_mark.bookable(venue_mark.resolve(none, q),
                                                 none))
        with self.shut:
            self.assertTrue(venue_mark.bookable(venue_mark.resolve(old, q),
                                                old))

    def test_an_open_market_orphan_with_a_three_hour_print_is_unpriced(self):
        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import (UNPRICED_EXIT_KEY,
                                                 _close_as_orphan)
        t = _gold(self.cfg, meta=_stamp("2649.75", age_s=3 * 3600))
        with self.open, mock.patch(ROUTER, return_value=self._dead()):
            _close_as_orphan(t)
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertIsNone(t.pnl)
        self.assertTrue(t.metadata.get(UNPRICED_EXIT_KEY))

    def test_a_shut_market_orphan_books_the_last_print_with_its_age(self):
        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import _close_as_orphan
        t = _gold(self.cfg, meta=_stamp("2649.75", age_s=3 * 3600))
        with self.shut, mock.patch(ROUTER, return_value=self._dead()):
            _close_as_orphan(t)
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertEqual(t.exit_price, Decimal("2649.75"))
        self.assertAlmostEqual(t.metadata["exit_mark_age_s"], 3 * 3600,
                               delta=60)

    def test_the_kill_switch_books_a_recent_print_and_flags_none(self):
        from bot_program.engine.kill_switch import _market_exit_price
        from bot_program.reconcile_asset import UNPRICED_EXIT_KEY
        t = _gold(self.cfg, meta=_stamp("2610", age_s=16 * 60))
        with self.open:
            self.assertEqual(_market_exit_price("XAUUSD", t.entry_price,
                                                client=self._dead(),
                                                trade=t), 2610.0)
        self.assertAlmostEqual(t.metadata["exit_mark_age_s"], 960, delta=30)
        self.assertNotIn(UNPRICED_EXIT_KEY, t.metadata)
        bare = _gold(self.cfg)
        with self.open:
            self.assertEqual(_market_exit_price("XAUUSD", bare.entry_price,
                                                client=self._dead(),
                                                trade=bare),
                             float(SPOT_FILL))
        self.assertTrue(bare.metadata.get(UNPRICED_EXIT_KEY),
                        "an entry-price stand-in is flagged unpriced")


class TheOtherSurfacesTests(TestCase):
    """Every other surface that showed the +18 now reads the row's own
    mark: the instrument page, the close card and the review, the signal
    rail, the level editor, the summary note, the open_trades command."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmb_os",
                                                         password="x")
        self.cfg = _cfg(self.user)
        self.inst = _instrument("XAUUSD", "commodity", "Gold Spot")
        _quote("XAUUSD", FUTURE, asset_class="commodity")
        self.inst.refresh_from_db()

    def test_the_gold_spot_page_panel(self):
        from dashboard.views import _chart_positions
        t = _gold(self.cfg, meta=_stamp("2649.75", age_s=30))
        bare = _gold(self.cfg)
        rows = {r["id"]: r for r in _chart_positions(self.user, self.inst)}
        got = rows[f"bot-{t.pk}"]
        self.assertAlmostEqual(got["pnl"], -0.25, places=6)
        self.assertEqual((got["mark"], got["mark_source"]),
                         (2649.75, "venue"))
        waiting = rows[f"bot-{bare.pk}"]
        self.assertIsNone(waiting["pnl"])
        self.assertIsNone(waiting["r_now"])
        self.assertIn("waiting", waiting["mark_wait"])

    def test_the_close_card_and_the_review(self):
        from brain.close_advice import advise
        t = _gold(self.cfg, meta=_stamp("2649.75", age_s=30))
        bare = _gold(self.cfg)
        out = {p["id"] if "id" in p else p.get("trade_id"): p
               for p in advise(self.user, [t.id, bare.id])["positions"]}
        nums = [p for p in advise(self.user, [t.id])["positions"]][0]["numbers"]
        self.assertAlmostEqual(nums["pnl"], -0.25, places=6)
        self.assertNotEqual(nums.get("pnl"), 18.0)
        nums2 = [p for p in advise(self.user, [bare.id])["positions"]][0]["numbers"]
        self.assertIsNone(nums2["pnl"], "the basis is not P&L on the card")
        self.assertTrue(out)

    def test_the_signal_rail_pnl(self):
        from signals.models import Signal
        t = _gold(self.cfg, meta=_stamp("2649.75", age_s=30))
        bare = _gold(self.cfg)
        sig = Signal(instrument=self.inst)
        self.assertAlmostEqual(sig._acted_pnl(t), -0.25, places=6)
        self.assertIsNone(sig._acted_pnl(bare))

    def test_the_level_editor_judges_at_the_venue(self):
        from bot_program.adjust_levels import validate_levels
        long_ = _gold(self.cfg, meta=_stamp("2650.00", age_s=30))
        self.assertTrue(validate_levels(long_, Decimal("2655"), None),
                        "a long stop above eToro's market is refused")
        from bot_program.models import AssetBotTrade
        short = _gold(self.cfg, meta=_stamp("2650.00", age_s=30))
        AssetBotTrade.objects.filter(pk=short.pk).update(
            side="SELL", stop_loss=Decimal("2670"), take_profit=Decimal("2600"))
        short.refresh_from_db()
        self.assertEqual(validate_levels(short, Decimal("2660"), None), [],
                         "a short stop 10 above eToro's market is valid")

    def test_the_summary_note_follows_the_mark_not_the_quote_row(self):
        from dashboard.position_summary import build_summary
        from market_data.models import LiveQuote
        LiveQuote.objects.filter(instrument__symbol="XAUUSD").delete()
        t = _gold(self.cfg, meta=_stamp("2649", age_s=30))
        s = build_summary(t)
        self.assertFalse(any("cannot be shown" in n["text"]
                             for n in s["notes"]), s["notes"])

    def test_the_open_trades_command(self):
        from bot_program.management.commands.open_trades import _open_mark
        t = _gold(self.cfg, meta=_stamp("2649.75", age_s=30))
        self.assertEqual(_open_mark(t, False), 2649.75)
        self.assertIsNone(_open_mark(_gold(self.cfg), False))


class TheCandleStampEdgesTests(TestCase):
    """The candle stamp's two filters and the zero-quote guard (review:
    each could be dropped with every other test still green)."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("vmb_ce",
                                                         password="x")
        self.cfg = _cfg(self.user, enabled=False)
        _instrument("XAUUSD", "commodity", "Gold Spot")

    def test_a_close_pending_row_is_stamped(self):
        from bot_program import venue_mark
        t = _gold(self.cfg, status="CLOSE_PENDING")
        self.assertEqual(venue_mark.stamp_rows("XAUUSD", 2649.5,
                                               carrier="etoro"), 1)
        t.refresh_from_db()
        self.assertEqual(t.metadata["venue_mark"]["price"], 2649.5)

    def test_a_row_another_broker_carries_is_not(self):
        from bot_program import venue_mark
        t = _gold(self.cfg, meta={"broker": "oanda"})
        self.assertEqual(venue_mark.stamp_rows("XAUUSD", 2649.5,
                                               carrier="etoro"), 0)
        t.refresh_from_db()
        self.assertNotIn("venue_mark", t.metadata)

    def test_a_zero_quote_is_no_price_not_a_total_loss(self):
        paper = _gold(_cfg(self.user, name="p", mode="paper"), paper=True)
        _quote("XAUUSD", "0", asset_class="commodity")
        row = _row(self.user, paper)
        self.assertIsNone(row.current_price)
        self.assertIsNone(row.unrealized_pnl)
