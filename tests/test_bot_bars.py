"""Bot bar feed + staleness guards.

The bars matter more than they look: every technical rule and the SMC
composite rule read 4h bars. Before this feed existed nothing wrote them,
so load_ohlcv returned None, every rule returned None, and the bots could
only ever HOLD.

Run with:  python manage.py test tests.test_bot_bars
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="bars_u"):
    return User.objects.create_user(username=name, password="x")


def _instrument(symbol="AAPL", asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _cfg(user, *, asset_class="stock", mode="live", enabled=True,
         symbols=("AAPL",), name="BARS"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode=mode,
        symbols=list(symbols), capital=Decimal("10000"), enabled=enabled)


def _klines(n=3, start_ms=1_700_000_000_000, step_ms=14_400_000):
    """Binance-style rows: [openTime, o, h, l, c, v, ...]."""
    return [
        [start_ms + i * step_ms, "100.0", "101.0", "99.0",
         str(100 + i), "1000", start_ms + (i + 1) * step_ms,
         "0", 0, "0", "0", "0"]
        for i in range(n)
    ]


class BarWriterTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.inst = _instrument()
        self.cfg = _cfg(self.user)

    def test_writes_both_timeframes_the_rules_read(self):
        from market_data.bot_bars import refresh_bot_bars
        from market_data.models import PriceData

        client = MagicMock()
        client.klines = MagicMock(return_value=_klines(3))
        with patch("market_data.bot_bars._client_for", return_value=client):
            out = refresh_bot_bars()

        self.assertEqual(out["configs"], 1)
        self.assertEqual(out["bars"], 6)  # 3 bars x 2 intervals
        self.assertEqual(
            PriceData.objects.filter(instrument=self.inst, timeframe="4h").count(), 3)
        self.assertEqual(
            PriceData.objects.filter(instrument=self.inst, timeframe="1h").count(), 3)

    def test_bars_make_ohlcv_loadable_for_the_rule_layer(self):
        """The whole point: signals.smc.dataframe.load_ohlcv must return
        data for 4h after a refresh."""
        from market_data.bot_bars import refresh_bot_bars
        from signals.smc.dataframe import load_ohlcv

        client = MagicMock()
        client.klines = MagicMock(return_value=_klines(60))
        with patch("market_data.bot_bars._client_for", return_value=client):
            refresh_bot_bars()

        df = load_ohlcv("AAPL", "4h", bars=60)
        self.assertIsNotNone(df)
        self.assertGreater(len(df), 0)

    def test_upsert_is_idempotent(self):
        from market_data.bot_bars import refresh_bot_bars
        from market_data.models import PriceData

        client = MagicMock()
        client.klines = MagicMock(return_value=_klines(3))
        with patch("market_data.bot_bars._client_for", return_value=client):
            refresh_bot_bars()
            refresh_bot_bars()

        self.assertEqual(
            PriceData.objects.filter(instrument=self.inst).count(), 6)

    def test_disabled_configs_are_skipped(self):
        from market_data.bot_bars import refresh_bot_bars
        self.cfg.enabled = False
        self.cfg.save()
        client = MagicMock()
        client.klines = MagicMock(return_value=_klines(3))
        with patch("market_data.bot_bars._client_for", return_value=client):
            out = refresh_bot_bars()
        self.assertEqual(out["configs"], 0)
        self.assertEqual(out["bars"], 0)

    def test_bad_rows_are_skipped_not_written(self):
        from market_data.bot_bars import refresh_bot_bars
        from market_data.models import PriceData

        rows = _klines(2)
        rows.append([0, "1", "1", "1", "0", "0", 0, "0", 0, "0", "0", "0"])  # zero close
        rows.append(["junk"])  # too short
        client = MagicMock()
        client.klines = MagicMock(return_value=rows)
        with patch("market_data.bot_bars._client_for", return_value=client):
            out = refresh_bot_bars()

        self.assertEqual(out["skipped"], 4)  # 2 bad rows x 2 intervals
        self.assertEqual(PriceData.objects.filter(instrument=self.inst).count(), 4)

    def test_broker_error_on_one_interval_does_not_lose_the_other(self):
        from market_data.bot_bars import refresh_bot_bars
        from market_data.models import PriceData

        def flaky(symbol, interval="1h", limit=200):
            if interval == "1h":
                raise RuntimeError("rate limited")
            return _klines(2)

        client = MagicMock()
        client.klines = MagicMock(side_effect=flaky)
        with patch("market_data.bot_bars._client_for", return_value=client):
            out = refresh_bot_bars()

        self.assertEqual(out["errors"], 1)
        self.assertEqual(
            PriceData.objects.filter(instrument=self.inst, timeframe="4h").count(), 2)

    def test_missing_instrument_is_reported_not_crashed(self):
        from market_data.bot_bars import refresh_bot_bars
        self.cfg.symbols = ["NOSUCH"]
        self.cfg.save()
        out = refresh_bot_bars()
        self.assertEqual(out["errors"], 1)
        self.assertEqual(out["bars"], 0)

    def test_beat_schedule_runs_the_bar_feed(self):
        from config.celery import app
        entry = app.conf.beat_schedule.get("refresh-bot-bars")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["task"], "market_data.tasks.refresh_bot_bars_task")


# ── Staleness + paper-fallback guards ───────────────────────────────────

class StaleQuoteGuardTests(TestCase):
    def setUp(self):
        self.user = _user("stale_u")
        self.inst = _instrument("MSFT")
        self.cfg = _cfg(self.user, symbols=("MSFT",), name="STALE")

    def _quote(self, last, age_seconds):
        from market_data.models import LiveQuote
        q = LiveQuote.objects.create(instrument=self.inst, last=Decimal(str(last)),
                                      source="test")
        LiveQuote.objects.filter(pk=q.pk).update(
            updated_at=timezone.now() - timedelta(seconds=age_seconds))
        return q

    def test_fresh_quote_is_returned(self):
        from bot_program.engine.paper_trader import PaperTrader
        self._quote(101, age_seconds=30)
        tk = PaperTrader(self.cfg).ticker("MSFT")
        self.assertEqual(tk["lastPrice"], "101.00000000")

    def test_stale_quote_reports_no_price(self):
        from bot_program.engine.paper_trader import PaperTrader
        self._quote(101, age_seconds=PaperTrader.MAX_QUOTE_AGE_SECONDS + 60)
        tk = PaperTrader(self.cfg).ticker("MSFT")
        self.assertEqual(tk["lastPrice"], "0")
        self.assertTrue(tk.get("stale"))


class LiveManageGuardTests(TestCase):
    def setUp(self):
        self.user = _user("mg_u")
        self.inst = _instrument("NVDA")
        self.cfg = _cfg(self.user, symbols=("NVDA",), name="MG")

    def test_live_trade_is_not_managed_through_paper_fallback(self):
        """A live row managed via PaperTrader would get a synthetic FILLED
        order and be stamped CLOSED while the broker position stays open."""
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.engine.paper_trader import PaperTrader
        from bot_program.models import AssetBotTrade

        trade = AssetBotTrade.objects.create(
            config=self.cfg, asset_class="stock", symbol="NVDA", side="BUY",
            qty=Decimal("5"), entry_price=Decimal("100"),
            stop_loss=Decimal("98"), take_profit=Decimal("104"),
            status="OPEN", paper=False)

        paper = PaperTrader(self.cfg)
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=paper):
            closed = StockBot(self.cfg).manage_positions()

        self.assertEqual(closed, 0)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
