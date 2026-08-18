"""The hardening wave: quote-currency sizing, honest marks, verified
credentials, and four components that stopped lying.

Run with:  python manage.py test tests.test_hardening
"""
import inspect
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _instrument(symbol, asset_class="forex"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _quote(symbol, last, *, source="oanda", age_seconds=0, asset_class="forex"):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    lq, _ = LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)), "source": source})
    if age_seconds:
        LiveQuote.objects.filter(pk=lq.pk).update(
            updated_at=timezone.now() - timedelta(seconds=age_seconds))
    return lq


def _bar(symbol, close, *, hours_ago=1, timeframe="1h", asset_class="forex"):
    from market_data.models import PriceData
    inst = _instrument(symbol, asset_class)
    c = Decimal(str(close))
    return PriceData.objects.create(
        instrument=inst, timeframe=timeframe,
        timestamp=timezone.now() - timedelta(hours=hours_ago),
        open=c, high=c, low=c, close=c, volume=0, source="test")


def _forex_bot(user, symbols=("USDJPY",)):
    from bot_program.asset_engine.base import make_bot
    from bot_program.models import AssetBotConfig
    cfg = AssetBotConfig.objects.create(
        user=user, asset_class="forex", name="fx_test", mode="paper",
        symbols=list(symbols), capital=Decimal("10000"), enabled=True)
    return make_bot(cfg)


# ── Quote-currency sizing conversion ────────────────────────────────────

class ForexSizingConversionTests(TestCase):
    """Risk was divided by a stop distance in QUOTE currency: USDJPY's
    2.25-JPY stop was treated as 2.25 USD, computing ~11 units and rounding
    to zero — the bot ticked forever logging SIZED_TO_ZERO."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        cls.user = get_user_model().objects.create_user("fxsz_u", password="x")

    def test_usd_quoted_pairs_convert_at_one(self):
        bot = _forex_bot(self.user)
        self.assertEqual(bot._value_per_unit("EURUSD"), 1.0)

    def test_jpy_pairs_convert_through_the_inverse_major(self):
        _quote("USDJPY", 150)
        bot = _forex_bot(self.user)
        self.assertAlmostEqual(bot._value_per_unit("USDJPY"), 1 / 150, places=6)

    def test_crosses_convert_through_the_direct_major(self):
        _quote("GBPUSD", 1.27)
        bot = _forex_bot(self.user)
        self.assertAlmostEqual(bot._value_per_unit("EURGBP"), 1.27, places=6)

    def test_no_rate_sizes_to_zero_not_to_a_wrong_number(self):
        bot = _forex_bot(self.user)
        self.assertEqual(bot._value_per_unit("USDJPY"), 0.0)

    def test_a_stale_quote_falls_back_to_a_recent_bar(self):
        _quote("USDJPY", 150, age_seconds=3600)
        _bar("USDJPY", 151)
        bot = _forex_bot(self.user)
        self.assertAlmostEqual(bot._value_per_unit("USDJPY"), 1 / 151, places=6)

    def test_usdjpy_sizes_to_the_converted_quantity_end_to_end(self):
        """$25 risk / (2.25 JPY / 150) = 1,666 units — not 25/2.25 = 11."""
        from bot_program.asset_engine import sizing
        _quote("USDJPY", 150)
        bot = _forex_bot(self.user)
        result = sizing.size_position(
            bot.cfg, asset_class="forex", entry=150.0, stop=147.75,
            direction="BUY", value_per_unit=bot._value_per_unit("USDJPY"))
        self.assertAlmostEqual(result["qty"], 1666.67, delta=1.0)
        self.assertEqual(bot._round_qty(result["qty"], 150.0), 1700.0)

    def test_trade_pnl_is_converted_to_account_currency(self):
        from bot_program.models import AssetBotTrade
        _quote("USDJPY", 150)
        bot = _forex_bot(self.user)
        trade = AssetBotTrade(
            config=bot.cfg, asset_class="forex", symbol="USDJPY", side="BUY",
            qty=Decimal("1000"), entry_price=Decimal("150"),
            stop_loss=Decimal("147.75"), take_profit=Decimal("154.5"),
            status="OPEN", paper=True, rule_name="t", composite_score=0.7,
            reason="t")
        pnl = bot._trade_pnl(trade, Decimal("151"))
        # 1,000 JPY of profit is ~$6.67, not $1,000.
        self.assertAlmostEqual(float(pnl), 1000 / 150, places=2)


# ── R-symmetry: pnl and risk convert by the SAME number ─────────────────

class ForexGradingSymmetryTests(TestCase):
    """The first conversion attempt converted only the bot-path P&L, at a
    close-time rate — so a JPY stop-out graded at −0.0067 instead of −1.0
    and the kill switch booked yen into the USD daily-loss column. The fix
    is one entry-time multiplier applied identically everywhere, the way
    option_pnl_multiplier works."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        cls.user = get_user_model().objects.create_user("fxg_u", password="x")

    def _closed_jpy_trade(self, cfg):
        from bot_program.models import AssetBotTrade
        now = timezone.now()
        return AssetBotTrade.objects.create(
            config=cfg, asset_class="forex", symbol="USDJPY", side="BUY",
            qty=Decimal("1700"), entry_price=Decimal("150"),
            stop_loss=Decimal("147.75"), take_profit=Decimal("154.5"),
            status="CLOSED", paper=True, rule_name="t", composite_score=0.7,
            reason="closed:SL", exit_price=Decimal("147.75"),
            pnl=Decimal("-25.50"), opened_at=now - timedelta(hours=4),
            closed_at=now,
            metadata={"initial_stop_loss": 147.75,
                      "value_per_unit": 1 / 150})

    def test_a_jpy_stop_out_grades_at_minus_one_r(self):
        from bot_program.bot_grading import grade_bot_trade
        bot = _forex_bot(self.user)
        trade = self._closed_jpy_trade(bot.cfg)
        grade_bot_trade(trade)
        trade.refresh_from_db()
        self.assertEqual(trade.outcome, "stopped_out")
        self.assertAlmostEqual(trade.realized_r, -1.0, places=2)

    def test_every_close_path_converts_by_the_same_entry_rate(self):
        """The bot close, the pending-close retry and the kill-switch
        formula must all book the same USD figure for the same exit."""
        from bot_program.pending_closes import _pnl
        bot = _forex_bot(self.user)
        trade = self._closed_jpy_trade(bot.cfg)
        expected = Decimal("-3825") * Decimal(str(1 / 150))
        self.assertAlmostEqual(
            float(bot._trade_pnl(trade, Decimal("147.75"))),
            float(expected), places=2)
        self.assertAlmostEqual(
            float(_pnl(trade, Decimal("147.75"))), float(expected), places=2)

    def test_the_multiplier_is_fixed_at_entry_not_at_close(self):
        """A rate move during the trade must not re-denominate its risk:
        metadata wins over whatever LiveQuote says now."""
        from bot_program.asset_engine.forex_bot import forex_usd_multiplier
        bot = _forex_bot(self.user)
        trade = self._closed_jpy_trade(bot.cfg)
        _quote("USDJPY", 120)  # the live rate has moved hard
        self.assertAlmostEqual(
            float(forex_usd_multiplier(trade)), 1 / 150, places=6)

    def test_non_forex_trades_are_untouched(self):
        from bot_program.asset_engine.forex_bot import forex_usd_multiplier
        stub = MagicMock(asset_class="stock")
        self.assertEqual(forex_usd_multiplier(stub), Decimal("1"))


# ── The resolver speaks OANDA's dialect ─────────────────────────────────

class UnderscoreResolutionTests(TestCase):
    """OANDA streams EUR_USD; without stripping the underscore the
    candidate list never contained EURUSD and every streamer tick was
    silently dropped — while the dashboard's own broadcast kept animating."""

    def test_underscore_symbols_resolve_to_catalogue_instruments(self):
        from market_data.quotes import (instrument_symbol_candidates,
                                        resolve_instrument)
        self.assertIn("EURUSD", instrument_symbol_candidates("EUR_USD"))
        _instrument("USDJPY")
        self.assertIsNotNone(resolve_instrument("USD_JPY"))


# ── Retired components stay buried on deployed databases ────────────────

class RetiredComponentTests(TestCase):
    def test_seed_components_deletes_the_finviz_ghost(self):
        """get_or_create never prunes, so a removed component's row survived
        on deployed DBs — its toggle still said 'FinViz Screener started.'
        for a task that no longer exists."""
        from core.platform_control import PlatformComponent, seed_components
        PlatformComponent.objects.create(
            key="scraper_finviz", name="FinViz Screener", category="scraper")
        seed_components()
        self.assertFalse(PlatformComponent.objects.filter(
            key="scraper_finviz").exists())


# ── Broker verification survives threads and hangs up after itself ──────

class BrokerPingHygieneTests(TestCase):
    def test_the_client_is_always_disconnected(self):
        """A successful IBKR ping used to leave a live TWS connection
        holding the client-id slot, so every LATER router connection got
        error 326."""
        from dashboard.views_admin_hq import _broker_ping
        client = MagicMock()
        client.ping.return_value = True
        self.assertTrue(_broker_ping(lambda: client, "test"))
        client.disconnect.assert_called_once()

    def test_disconnect_happens_even_when_ping_blows_up(self):
        from dashboard.views_admin_hq import _broker_ping
        client = MagicMock()
        client.ping.side_effect = RuntimeError("boom")
        self.assertFalse(_broker_ping(lambda: client, "test"))
        client.disconnect.assert_called_once()


# ── Lifecycle grading reads a real price ────────────────────────────────

class LifecyclePriceTests(TestCase):
    """_latest_price queried three fields LiveQuote never had, so the
    branch always raised into its bare except and outcome grading ran on
    bar closes alone — hours stale on the 4h timeframe."""

    def test_a_fresh_livequote_is_finally_used(self):
        from signals.lifecycle import _latest_price
        _quote("EURUSD", 1.0912)
        self.assertAlmostEqual(_latest_price("EURUSD"), 1.0912, places=4)

    def test_a_stale_quote_falls_back_to_bars(self):
        from signals.lifecycle import _latest_price
        _quote("EURUSD", 1.0912, age_seconds=3600)
        _bar("EURUSD", 1.0800)
        self.assertAlmostEqual(_latest_price("EURUSD"), 1.0800, places=4)


# ── Kill switch marks ───────────────────────────────────────────────────

class KillSwitchMarkTests(TestCase):
    """The forced-close price came from LiveQuote with no staleness check
    and never asked the broker — and the kill switch runs precisely when
    things are broken, which is when a fossil is most likely in the table."""

    def test_the_broker_tick_wins_when_available(self):
        from bot_program.engine.kill_switch import _market_exit_price
        _quote("EURUSD", 1.05)
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": "1.0700"}
        self.assertEqual(
            _market_exit_price("EURUSD", 1.0, client=client), 1.07)

    def test_a_stale_quote_is_refused_in_favour_of_the_entry(self):
        from bot_program.engine.kill_switch import _market_exit_price
        _quote("EURUSD", 1.05, age_seconds=1200)
        self.assertEqual(_market_exit_price("EURUSD", 1.0), 1.0)

    def test_a_fresh_quote_is_used_without_a_client(self):
        from bot_program.engine.kill_switch import _market_exit_price
        _quote("EURUSD", 1.05)
        self.assertEqual(_market_exit_price("EURUSD", 1.0), 1.05)


# ── ETFs join the stock quote universe ──────────────────────────────────

class EtfQuoteTests(TestCase):
    def test_etf_symbols_are_quote_targets_beside_stocks(self):
        """SPY is asset_class='etf'; a poller filtering 'stock' alone left
        a StockBot trading ETFs with bars and no mark."""
        from instruments.models import Instrument
        from signals.universe import quote_targets
        for sym, cls in (("AAPL", "stock"), ("SPY", "etf")):
            inst = _instrument(sym, cls)
            Instrument.objects.filter(pk=inst.pk).update(is_watchlist=True)
        got = {i.symbol for i in quote_targets(("stock", "etf"))}
        self.assertIn("AAPL", got)
        self.assertIn("SPY", got)

    def test_the_stock_poller_asks_for_both_classes(self):
        from market_data import tasks
        src = inspect.getsource(tasks.fetch_live_quotes)
        self.assertIn('("stock", "etf")', src)


# ── Position mark-to-market ─────────────────────────────────────────────

class PositionMarkTests(TestCase):
    """Position.unrealized_pnl had no scheduled writer and a default of 0,
    so every dashboard summing it rendered +0.00 forever."""

    def _position(self, symbol="AAPL", *, direction="long", entry=100,
                  qty=5, asset_class="stock"):
        from portfolio.models import Position
        from portfolio.services import get_or_create_default_portfolio
        return Position.objects.create(
            portfolio=get_or_create_default_portfolio(),
            instrument=_instrument(symbol, asset_class),
            direction=direction, quantity=Decimal(str(qty)),
            entry_price=Decimal(str(entry)), current_price=Decimal(str(entry)),
            opened_at=timezone.now())

    def test_a_long_position_is_marked_from_the_live_quote(self):
        from portfolio.tasks import mark_positions_to_market
        pos = self._position()
        _quote("AAPL", 110, asset_class="stock")
        self.assertEqual(mark_positions_to_market([pos]), 1)
        pos.refresh_from_db()
        self.assertEqual(pos.current_price, Decimal("110"))
        self.assertEqual(pos.unrealized_pnl, Decimal("50.00"))
        self.assertAlmostEqual(pos.unrealized_pnl_pct, 10.0, places=2)

    def test_a_short_position_signs_the_loss(self):
        from portfolio.tasks import mark_positions_to_market
        pos = self._position(direction="short")
        _quote("AAPL", 110, asset_class="stock")
        mark_positions_to_market([pos])
        pos.refresh_from_db()
        self.assertEqual(pos.unrealized_pnl, Decimal("-50.00"))
        self.assertAlmostEqual(pos.unrealized_pnl_pct, -10.0, places=2)

    def test_day_old_data_leaves_the_mark_untouched(self):
        from portfolio.tasks import mark_positions_to_market
        pos = self._position()
        _quote("AAPL", 110, asset_class="stock", age_seconds=25 * 3600)
        self.assertEqual(mark_positions_to_market([pos]), 0)
        pos.refresh_from_db()
        self.assertEqual(pos.current_price, Decimal("100"))

    def test_the_exposure_task_marks_before_it_sums(self):
        from portfolio.tasks import recalculate_exposure
        self._position()
        _quote("AAPL", 110, asset_class="stock")
        out = recalculate_exposure.__wrapped__.__wrapped__()
        self.assertEqual(out["marked"], 1)
        self.assertAlmostEqual(
            out["exposure_by_asset_class"]["stock"], 550.0, places=1)

    def test_the_first_run_ever_survives_creating_the_portfolio(self):
        """Settings hand initial_capital over as a FLOAT, and a freshly
        created instance keeps its given types until reloaded — so the run
        that both creates and uses the portfolio crashed on float + Decimal.
        On a fresh deploy that is the very first exposure run; found live,
        nineteen minutes after the platform was switched on."""
        from portfolio.models import Portfolio
        from portfolio.tasks import recalculate_exposure
        self.assertFalse(Portfolio.objects.exists(),
                         "this test must be the portfolio's creator")
        out = recalculate_exposure.__wrapped__.__wrapped__()
        self.assertEqual(out["status"], "ok")


# ── COT: the parser reads the real formats ──────────────────────────────

# A REAL line captured from the live deafut.txt on 2026-08-16 (WHEAT-SRW),
# plus a GOLD line built in the same positional shape.
DEAFUT_SAMPLE = (
    '"WHEAT-SRW - CHICAGO BOARD OF TRADE",260811,2026-08-11,001602,CBT ,00,'
    '001 ,  475566,  114979,  139889,  150164,  171852,  149098,  436995,'
    '  439151,   38571,   36415\n'
    '"GOLD - COMMODITY EXCHANGE INC.",260811,2026-08-11,088691,CMX ,00,001 ,'
    '  500000,  200000,  100000,   50000,  120000,  180000,  400000,  410000,'
    '   30000,   20000\n'
    '"MICRO GOLD - COMMODITY EXCHANGE INC.",260811,2026-08-11,088695,CMX ,00,'
    '001 ,   10000,    5000,    2000,    1000,    2000,    3000,    9000,'
    '    9100,     500,     400\n'
)

DEACOT_SAMPLE = (
    '"Market and Exchange Names","As of Date in Form YYMMDD",'
    '"As of Date in Form YYYY-MM-DD","CFTC Contract Market Code",'
    '"CFTC Market Code in Initials","CFTC Region Code","CFTC Commodity Code",'
    '"Open Interest (All)","Noncommercial Positions-Long (All)",'
    '"Noncommercial Positions-Short (All)",'
    '"Noncommercial Positions-Spreading (All)",'
    '"Commercial Positions-Long (All)","Commercial Positions-Short (All)"\n'
    '"EURO FX - CHICAGO MERCANTILE EXCHANGE",260811,2026-08-11,099741,CME,00,'
    '099,700000,250000,120000,30000,300000,400000\n'
)


class CotParserTests(SimpleTestCase):
    """The old code fetched an Excel archive, decoded the binary as latin-1
    'text', and fed a headerless file to DictReader — zero rows stored for
    the scraper's whole life. Samples here are the real observed formats."""

    def test_the_current_week_file_parses_positionally(self):
        from scraping.scrapers.cot_reports import _parse_fixed_width_txt
        rows = _parse_fixed_width_txt(DEAFUT_SAMPLE)
        wheat = next(r for r in rows if r["market_name"].startswith("WHEAT-SRW"))
        self.assertEqual(wheat["open_interest"], 475566)
        self.assertEqual(wheat["non_commercial_long"], 114979)
        self.assertEqual(wheat["non_commercial_short"], 139889)
        self.assertEqual(wheat["commercial_long"], 171852)
        self.assertEqual(wheat["commercial_short"], 149098)
        self.assertEqual(wheat["report_date"], "2026-08-11")
        self.assertEqual(wheat["instrument_symbol"], "WHEATUSD")

    def test_the_yearly_archive_header_names_are_recognised(self):
        from scraping.scrapers.cot_reports import _parse_cot_csv
        rows = _parse_cot_csv(DEACOT_SAMPLE)
        self.assertEqual(len(rows), 1)
        euro = rows[0]
        self.assertEqual(euro["open_interest"], 700000)
        self.assertEqual(euro["commercial_long"], 300000)
        self.assertEqual(euro["non_commercial_short"], 120000)
        self.assertEqual(euro["instrument_symbol"], "EURUSD")

    def test_micro_contracts_do_not_collide_with_the_flagship(self):
        from scraping.scrapers.cot_reports import _map_market_to_symbol
        self.assertEqual(
            _map_market_to_symbol("GOLD - COMMODITY EXCHANGE INC."), "XAUUSD")
        self.assertIsNone(
            _map_market_to_symbol("MICRO GOLD - COMMODITY EXCHANGE INC."))
        self.assertIsNone(
            _map_market_to_symbol("WHEAT-HRW - CHICAGO BOARD OF TRADE"))

    def test_the_map_speaks_catalogue_spellings_only(self):
        from instruments.services import INSTRUMENTS_DATA
        from scraping.scrapers.cot_reports import MARKET_NAME_MAP
        catalogue = set()
        for symbols in INSTRUMENTS_DATA.values():
            catalogue.update(symbols)
        for market, sym in MARKET_NAME_MAP.items():
            self.assertIn(sym, catalogue,
                          f"{market!r} maps to {sym}, which no seeder creates")


class CotPersistTests(TestCase):
    def test_parsed_rows_reach_the_database(self):
        from scraping.models import COTReport
        from scraping.scrapers.cot_reports import (
            _parse_fixed_width_txt, _persist_cot_reports)
        _instrument("XAUUSD", "commodity")
        _instrument("WHEATUSD", "commodity")
        _persist_cot_reports(_parse_fixed_width_txt(DEAFUT_SAMPLE))
        self.assertEqual(COTReport.objects.count(), 2)
        gold = COTReport.objects.get(instrument__symbol="XAUUSD")
        self.assertEqual(gold.net_speculative, 100000)


# ── SEC: Form-4 issuers resolve to instruments ──────────────────────────

class SecResolutionTests(TestCase):
    def test_an_issuer_title_resolves_through_the_cik_map(self):
        from scraping.scrapers import sec_edgar
        with patch.object(sec_edgar, "_cik_to_ticker_map",
                          return_value={1646188: "ONDS"}):
            self.assertEqual(
                sec_edgar._issuer_symbol_from_title(
                    "4 - Ondas Inc. (0001646188) (Issuer)"), "ONDS")

    def test_reporting_owner_entries_stay_unresolved(self):
        from scraping.scrapers import sec_edgar
        self.assertIsNone(sec_edgar._issuer_symbol_from_title(
            "4 - COHEN RICHARD M (0001075891) (Reporting)"))

    def test_the_cik_map_is_fetched_once_then_cached(self):
        from django.core.cache import cache
        from scraping.scrapers import sec_edgar
        cache.delete(sec_edgar.CIK_CACHE_KEY)
        resp = MagicMock()
        resp.json.return_value = {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}}
        with patch.object(sec_edgar, "_get", return_value=resp) as got:
            first = sec_edgar._cik_to_ticker_map()
            second = sec_edgar._cik_to_ticker_map()
        self.assertEqual(first, {320193: "AAPL"})
        self.assertEqual(second, first)
        got.assert_called_once()
        cache.delete(sec_edgar.CIK_CACHE_KEY)


# ── Event engine: the switch finally gates something ────────────────────

class EventEngineWrapperTests(TestCase):
    def test_the_wrapper_is_gated_like_every_other_pipeline(self):
        from signals.tasks import dispatch_event_task
        out = dispatch_event_task("price_move", {})
        self.assertEqual(out.get("status"), "skipped")
        self.assertEqual(out.get("reason"), "platform_disabled")

    def test_the_wrapper_forwards_to_the_dispatcher_when_open(self):
        from signals.tasks import dispatch_event_task
        fake = {"event_id": 1, "rules_evaluated": 2, "rules_fired": 0,
                "signal_ids": [], "elapsed_ms": 3}
        with patch("core.task_gate.is_component_enabled", return_value=True), \
             patch("core.task_gate.get_component", return_value=None), \
             patch("signals.fast_rules.dispatch_event",
                   return_value=fake) as dispatched:
            out = dispatch_event_task("price_move", {"symbol": "BTCUSD"},
                                      source="test")
        dispatched.assert_called_once_with(
            "price_move", {"symbol": "BTCUSD"}, source="test")
        self.assertEqual(out["rules_evaluated"], 2)
        self.assertEqual(out["status"], "success")


# ── The OANDA streamer goes through the one writer ──────────────────────

class StreamRerouteTests(SimpleTestCase):
    def test_the_streamer_writes_through_write_quote_at_stream_priority(self):
        """Asserted on the source, house-style: the alternative is mocking
        an async websocket loop to prove a negative about a direct write."""
        from market_data.management.commands import stream_oanda
        src = inspect.getsource(stream_oanda.update_live_quote)
        self.assertIn("write_quote", src)
        self.assertIn("oanda_stream", src)
        self.assertNotIn("LiveQuote.objects.update_or_create", src)


# ── FinViz: fully removed, and it stays removed ─────────────────────────

class FinvizRemovalTests(SimpleTestCase):
    """It fetched a screener, took len(), and dropped the list — no model,
    no page, no consumer, permanently green. Removed; these pin the grave."""

    def test_the_scraper_module_is_gone(self):
        from pathlib import Path
        from django.conf import settings
        self.assertFalse(
            (Path(settings.BASE_DIR) / "scraping" / "scrapers"
             / "finviz.py").exists(),
            "finviz.py is back — either give it a model and a consumer, "
            "or let it stay gone")

    def test_no_component_or_beat_entry_remains(self):
        from config.celery import app
        from core.platform_control import DEFAULT_COMPONENTS
        from dashboard.views_topology import WIRING
        self.assertNotIn("scraper_finviz",
                         {c["key"] for c in DEFAULT_COMPONENTS})
        self.assertNotIn("fetch-finviz-screener", app.conf.beat_schedule)
        self.assertNotIn("scraper_finviz", WIRING)


# ── Charts work from day one ────────────────────────────────────────────

class ChartDataFallbackTests(TestCase):
    """Charts draw DAILY candles, but a fresh deployment has intraday bars
    days before its first 1d row (the bot-bar feed writes 1h/4h; the EOD
    scraper runs nightly and was stock-only) — so every chart on a new box
    queried an empty table and rendered blank while the data to draw it
    sat one timeframe over."""

    def _bar(self, inst, tf, when, o, h, l, c, vol=0):
        from market_data.models import PriceData
        return PriceData.objects.create(
            instrument=inst, timeframe=tf, timestamp=when,
            open=Decimal(str(o)), high=Decimal(str(h)), low=Decimal(str(l)),
            close=Decimal(str(c)), volume=vol, source="test")

    def test_daily_candles_are_synthesized_from_4h_bars(self):
        from dashboard.views import _daily_chart_bars
        inst = _instrument("EURUSD")
        base = timezone.now().replace(hour=8, minute=0, second=0,
                                      microsecond=0)
        self._bar(inst, "4h", base, 1.10, 1.12, 1.09, 1.11, vol=10)
        self._bar(inst, "4h", base + timedelta(hours=4),
                  1.11, 1.15, 1.10, 1.14, vol=5)
        bars = _daily_chart_bars(inst)
        self.assertEqual(len(bars), 1)
        day = bars[0]
        self.assertEqual(day["open"], 1.10)
        self.assertEqual(day["high"], 1.15)
        self.assertEqual(day["low"], 1.09)
        self.assertEqual(day["close"], 1.14)
        self.assertEqual(day["volume"], 15)

    def test_real_daily_bars_win_when_present(self):
        from dashboard.views import _daily_chart_bars
        inst = _instrument("EURUSD")
        now = timezone.now()
        self._bar(inst, "1d", now, 1.20, 1.21, 1.19, 1.20)
        self._bar(inst, "4h", now, 9, 9, 9, 9)
        bars = _daily_chart_bars(inst)
        self.assertEqual(bars[-1]["close"], 1.20)

    def test_the_api_serves_the_synthesized_bars(self):
        from django.contrib.auth import get_user_model
        inst = _instrument("EURUSD")
        self._bar(inst, "4h", timezone.now(), 1.10, 1.12, 1.09, 1.11)
        user = get_user_model().objects.create_user("chart_u", password="x")
        self.client.force_login(user)
        resp = self.client.get("/api/chart-data/?symbol=EURUSD&timeframe=1d",
                               HTTP_HOST="127.0.0.1")
        data = resp.json()
        self.assertTrue(data["bars"], "the fallback never reached the API")


class EodUniverseTests(SimpleTestCase):
    def test_the_eod_task_covers_every_mapped_class_not_just_stocks(self):
        """Stock-only EOD was the other half of the blank-charts bug: no
        daily bar was ever written for forex, commodities or indices."""
        import inspect
        from market_data import tasks
        src = inspect.getsource(tasks.fetch_eod_all_instruments)
        self.assertIn("SUPPORTED_ASSET_CLASSES", src)
        self.assertIn("yf_symbol", src)
        self.assertIn("YF_UNAVAILABLE", src)
        self.assertNotIn('asset_class="stock"', src)


# ── The star delivers bars, not just quotes ─────────────────────────────

class WatchlistBarsTests(TestCase):
    """Bars were fetched only for enabled bots' symbols, so a starred
    instrument's chart stayed blank and its rules could never fire —
    quietly contradicting what the star promises. The bar refresh now runs
    a watchlist pass through the keyless public feeds."""

    def _klines(self, n=3):
        base = int(timezone.now().timestamp() * 1000) - n * 3600_000
        return [[base + i * 3600_000, "1.10", "1.12", "1.09", "1.11", "0"]
                for i in range(n)]

    def test_a_starred_instrument_gets_bars_without_a_bot(self):
        from instruments.models import Instrument
        from market_data.bot_bars import refresh_watchlist_bars
        from market_data.models import PriceData
        inst = _instrument("EURUSD")
        Instrument.objects.filter(pk=inst.pk).update(is_watchlist=True)
        client = MagicMock()
        client.klines = MagicMock(return_value=self._klines())
        client._sv_public_feed = True
        with patch("market_data.public_feed.public_feed_for",
                   return_value=client):
            out = refresh_watchlist_bars()
        self.assertEqual(out["symbols"], 1)
        self.assertGreater(out["bars"], 0)
        self.assertTrue(PriceData.objects.filter(instrument=inst).exists())

    def test_fleet_symbols_are_not_fetched_twice(self):
        from instruments.models import Instrument
        from market_data.bot_bars import refresh_watchlist_bars
        inst = _instrument("EURUSD")
        Instrument.objects.filter(pk=inst.pk).update(is_watchlist=True)
        client = MagicMock()
        with patch("market_data.public_feed.public_feed_for",
                   return_value=client):
            out = refresh_watchlist_bars(covered={"EURUSD"})
        client.klines.assert_not_called()
        self.assertEqual(out["symbols"], 0)


# ── The watchlist star ──────────────────────────────────────────────────

class WatchlistToggleTests(TestCase):
    """The star is how an operator widens what the platform watches:
    scan_universe and the quote pollers read is_watchlist, so starring an
    instrument is a data decision, not a bookmark."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        self.user = get_user_model().objects.create_user("wl_u", password="x")
        self.inst = _instrument("EURUSD")
        self.client.force_login(self.user)

    def _toggle(self, **extra):
        return self.client.post("/instruments/EURUSD/watchlist/",
                                extra, HTTP_HOST="127.0.0.1")

    def test_the_star_toggles_both_ways(self):
        self.assertFalse(self.inst.is_watchlist)
        self._toggle()
        self.inst.refresh_from_db()
        self.assertTrue(self.inst.is_watchlist)
        self._toggle()
        self.inst.refresh_from_db()
        self.assertFalse(self.inst.is_watchlist)

    def test_it_returns_where_the_operator_was(self):
        resp = self._toggle(next="/instruments/?filter=forex")
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, "/instruments/?filter=forex")

    def test_a_hostile_next_is_ignored(self):
        resp = self._toggle(next="https://evil.example/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/instruments/EURUSD/", resp.url)

    def test_get_is_refused(self):
        resp = self.client.get("/instruments/EURUSD/watchlist/",
                               HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 405)

    def test_anonymous_users_are_bounced_and_nothing_changes(self):
        self.client.logout()
        resp = self._toggle()
        self.assertEqual(resp.status_code, 302)
        self.assertIn("next=/instruments/EURUSD/watchlist/", resp.url)
        self.inst.refresh_from_db()
        self.assertFalse(self.inst.is_watchlist,
                         "an anonymous POST must not touch the watchlist")


class IntradayChartTests(TestCase):
    """Sub-daily chart resolutions. 1h/4h serve from stored bars; minute
    bars are fetched live from the keyless public feed and cached for a
    minute — persisting minute bars for every instrument would bloat
    PriceData for the sake of a chart click. `time` must be epoch seconds:
    lightweight-charts needs numeric time below daily resolution."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        cls.user = get_user_model().objects.create_user("ic_u", password="x")

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.client.force_login(self.user)
        from instruments.models import Instrument
        self.inst, _ = Instrument.objects.get_or_create(
            symbol="BTCUSD", defaults={"name": "Bitcoin",
                                       "asset_class": "crypto"})

    def test_stored_hourly_bars_serve_the_1h_view(self):
        from datetime import timedelta
        from decimal import Decimal
        from django.utils import timezone
        from market_data.models import PriceData
        now = timezone.now()
        for i in range(3):
            PriceData.objects.create(
                instrument=self.inst, timeframe="1h",
                timestamp=now - timedelta(hours=i),
                open=Decimal("1"), high=Decimal("2"), low=Decimal("0.5"),
                close=Decimal("1.5"), volume=10, source="test")
        resp = self.client.get(
            "/api/chart-data/?symbol=BTCUSD&timeframe=1h",
            HTTP_HOST="127.0.0.1")
        bars = resp.json()["bars"]
        self.assertEqual(len(bars), 3)
        self.assertIsInstance(bars[0]["time"], int)
        self.assertLess(bars[0]["time"], bars[-1]["time"],
                        "bars must be oldest-first")

    def test_minute_bars_are_fetched_live_cached_and_venue_translated(self):
        from unittest.mock import MagicMock, patch
        feed = MagicMock()
        feed.klines.return_value = [
            [1700000000000, "1", "2", "0.5", "1.5", "10"],
            [1700000060000, "1.5", "2.5", "1", "2", "12"],
        ]
        with patch("market_data.public_feed.public_feed_for",
                   return_value=feed):
            r1 = self.client.get(
                "/api/chart-data/?symbol=BTCUSD&timeframe=1min",
                HTTP_HOST="127.0.0.1")
            self.client.get(
                "/api/chart-data/?symbol=BTCUSD&timeframe=1min",
                HTTP_HOST="127.0.0.1")
        bars = r1.json()["bars"]
        self.assertEqual(bars[0]["time"], 1700000000)
        self.assertEqual(bars[1]["close"], 2.0)
        self.assertEqual(feed.klines.call_count, 1,
                         "the second hit inside a minute must be cached")
        # Crypto fetches under the venue spelling (BTCUSD -> BTCUSDT).
        self.assertEqual(feed.klines.call_args.args[0], "BTCUSDT")

    def test_a_feedless_class_reports_instead_of_500ing(self):
        from unittest.mock import patch
        with patch("market_data.public_feed.public_feed_for",
                   return_value=None):
            resp = self.client.get(
                "/api/chart-data/?symbol=BTCUSD&timeframe=5min",
                HTTP_HOST="127.0.0.1")
        data = resp.json()
        self.assertEqual(data["bars"], [])
        self.assertIn("error", data)

    def test_legacy_month_timeframe_still_serves_daily(self):
        """'1m' has always meant ONE MONTH of daily candles on this API —
        the minute views use '1min' so old callers keep working."""
        resp = self.client.get(
            "/api/chart-data/?symbol=BTCUSD&timeframe=1m",
            HTTP_HOST="127.0.0.1")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("error", resp.json())


class WatchlistSentimentTests(TestCase):
    """Trending-only StockTwits coverage sampled THEIR universe — mostly
    off-catalogue small caps, so 'Social Sentiment ran and stored nothing'
    was the normal outcome. The watchlist pass samples OURS: starred
    equities are in the catalogue by definition, so their snapshots land."""

    def test_starred_equities_get_sentiment_snapshots(self):
        from unittest.mock import patch
        from instruments.models import Instrument
        from scraping.models import SentimentSnapshot
        from scraping.scrapers.stocktwits import fetch_watchlist_sentiment
        inst, _ = Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "Apple", "asset_class": "stock"})
        inst.is_watchlist = True
        inst.save(update_fields=["is_watchlist"])
        payload = {
            "response": {"status": 200},
            "symbol": {"symbol": "AAPL", "title": "Apple",
                       "watchlist_count": 5},
            "messages": [
                {"entities": {"sentiment": {"basic": "Bullish"}}},
                {"entities": {"sentiment": {"basic": "Bearish"}}},
                {"entities": {"sentiment": None}},
            ],
        }
        with patch("scraping.scrapers.stocktwits._get",
                   return_value=payload):
            covered = fetch_watchlist_sentiment()
        self.assertEqual(covered, 1)
        snap = SentimentSnapshot.objects.get(instrument=inst,
                                             source="stocktwits")
        self.assertEqual(snap.bullish_count, 1)
        self.assertEqual(snap.bearish_count, 1)

    def test_crypto_and_unstarred_symbols_are_not_queried(self):
        """StockTwits spells crypto BTC.X — the catalogue does not; and an
        unstarred symbol is not the operator's to poll for."""
        from unittest.mock import patch
        from instruments.models import Instrument
        from scraping.scrapers.stocktwits import fetch_watchlist_sentiment
        inst, _ = Instrument.objects.get_or_create(
            symbol="BTCUSD", defaults={"name": "Bitcoin",
                                       "asset_class": "crypto"})
        inst.is_watchlist = True
        inst.save(update_fields=["is_watchlist"])
        with patch("scraping.scrapers.stocktwits._get") as mock_get:
            fetch_watchlist_sentiment()
        mock_get.assert_not_called()
