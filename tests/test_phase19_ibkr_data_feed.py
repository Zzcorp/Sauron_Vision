"""Phase-19 IBKR data feed tests:
  - graceful degrade: no IBKRAccount, no primary classes, no symbols
  - klines upserts PriceData with source='ibkr' and dedupes by unique_together
  - ticker upserts LiveQuote
  - per-user filter: walk only enabled configs whose asset_class matches IBKR primary
  - mocked client (no live TWS connection needed)
  - aggregate walker iterates connected accounts only
  - beat schedule entry registered

Run with:  python manage.py test tests.test_phase19_ibkr_data_feed
"""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from unittest.mock import MagicMock

from django.contrib.auth.models import User
from django.test import TestCase


def _user(name="ibd_u"):
    return User.objects.create_user(username=name, password="x")


def _ibkr(user, *, connected=True, paper=True, **kw):
    from bot_program.models import IBKRAccount
    defaults = dict(
        host="127.0.0.1", port=7497, client_id=1,
        connected=connected, paper=paper,
        is_primary_for_stocks=False, is_primary_for_forex=False,
        is_primary_for_options=False, is_primary_for_commodity=False,
        is_primary_for_cfd=False,
    )
    defaults.update(kw)
    return IBKRAccount.objects.create(user=user, **defaults)


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _abc(user, asset_class, **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        enabled=True, mode="paper", symbols=[],
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
        entry_score_min=0.6, min_signals_for_entry=1,
    )
    defaults.update(kw)
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=defaults.pop("name", "T"),
        **defaults,
    )


def _fake_kline(ts_ms, *, o=100, h=101, low=99, c=100.5, v=1000):
    """Binance-style 11-element row, matching what IBKRTrader.klines returns."""
    return [ts_ms, str(o), str(h), str(low), str(c), str(v),
             ts_ms + 60_000, "0", 0, "0", "0", "0"]


def _make_client(*, klines_rows=None, ticker_resp=None):
    client = MagicMock()
    client.klines = MagicMock(return_value=klines_rows or [])
    client.ticker = MagicMock(return_value=ticker_resp or {})
    return client


# ── Per-user feed: graceful degrade ──────────────────────────────────────

class FeedDegradeTests(TestCase):
    def setUp(self):
        self.user = _user()

    def test_no_account_skipped(self):
        from bot_program.ibkr_data_feed import refresh_ibkr_data_for_user
        r = refresh_ibkr_data_for_user(self.user.id)
        self.assertEqual(r["skipped"], "no_ibkr_account")

    def test_no_primary_classes_skipped(self):
        from bot_program.ibkr_data_feed import refresh_ibkr_data_for_user
        _ibkr(self.user)  # all primary flags False
        r = refresh_ibkr_data_for_user(self.user.id)
        self.assertEqual(r["skipped"], "no_primary_classes")

    def test_no_symbols_skipped(self):
        """User has IBKR primary for stocks but no enabled stock configs."""
        from bot_program.ibkr_data_feed import refresh_ibkr_data_for_user
        _ibkr(self.user, is_primary_for_stocks=True)
        # Forex config doesn't match stocks primary.
        _abc(self.user, "forex", name="FX", symbols=["EURUSD"])
        r = refresh_ibkr_data_for_user(self.user.id, _client=_make_client())
        self.assertEqual(r["skipped"], "no_symbols")

    def test_unknown_user_returns_error(self):
        from bot_program.ibkr_data_feed import refresh_ibkr_data_for_user
        r = refresh_ibkr_data_for_user(9999999)
        self.assertIn("error", r)


# ── Klines upsert ────────────────────────────────────────────────────────

class KlinesUpsertTests(TestCase):
    def setUp(self):
        self.user = _user("kl_u")
        _ibkr(self.user, is_primary_for_stocks=True)
        _instrument("AAPL", asset_class="stock")
        _abc(self.user, "stock", name="ST", symbols=["AAPL"])

    def test_klines_upserts_pricedata(self):
        from bot_program.ibkr_data_feed import refresh_ibkr_data_for_user
        from market_data.models import PriceData
        ts = int(datetime(2026, 4, 30, 13, 0, tzinfo=dt_tz.utc).timestamp() * 1000)
        client = _make_client(klines_rows=[
            _fake_kline(ts, o=180, h=182, low=179, c=181, v=1_000_000),
        ])
        r = refresh_ibkr_data_for_user(self.user.id, _client=client)
        self.assertEqual(r["bars_upserted"], 1)
        bar = PriceData.objects.get(timeframe="1h")
        self.assertEqual(bar.source, "ibkr")
        self.assertEqual(bar.open, Decimal("180"))
        self.assertEqual(bar.close, Decimal("181"))

    def test_klines_dedupe_on_repeat_call(self):
        """Same kline pulled twice → one row (unique on instrument/tf/ts)."""
        from bot_program.ibkr_data_feed import refresh_ibkr_data_for_user
        from market_data.models import PriceData
        ts = int(datetime(2026, 4, 30, 13, 0, tzinfo=dt_tz.utc).timestamp() * 1000)
        client = _make_client(klines_rows=[_fake_kline(ts)])
        refresh_ibkr_data_for_user(self.user.id, _client=client)
        refresh_ibkr_data_for_user(self.user.id, _client=client)
        self.assertEqual(PriceData.objects.count(), 1)

    def test_klines_failure_continues(self):
        """If klines() raises, the feed continues and counts an error."""
        from bot_program.ibkr_data_feed import refresh_ibkr_data_for_user
        client = MagicMock()
        client.klines = MagicMock(side_effect=Exception("network"))
        client.ticker = MagicMock(return_value={"lastPrice": "0"})
        r = refresh_ibkr_data_for_user(self.user.id, _client=client)
        self.assertEqual(r["bars_upserted"], 0)
        self.assertGreater(r["errors"], 0)


# ── Ticker upsert ────────────────────────────────────────────────────────

class TickerUpsertTests(TestCase):
    def setUp(self):
        self.user = _user("tk_u")
        _ibkr(self.user, is_primary_for_stocks=True)
        _instrument("AAPL", asset_class="stock")
        _abc(self.user, "stock", name="ST", symbols=["AAPL"])

    def test_ticker_upserts_livequote(self):
        from bot_program.ibkr_data_feed import refresh_ibkr_data_for_user
        from market_data.models import LiveQuote
        client = _make_client(ticker_resp={
            "lastPrice": "181.50", "bid": "181.45", "ask": "181.55",
            "symbol": "AAPL",
        })
        r = refresh_ibkr_data_for_user(self.user.id, _client=client)
        self.assertEqual(r["quotes_updated"], 1)
        lq = LiveQuote.objects.get(instrument__symbol="AAPL")
        self.assertEqual(lq.last, Decimal("181.50"))
        self.assertEqual(lq.bid, Decimal("181.45"))
        self.assertEqual(lq.source, "ibkr")

    def test_ticker_zero_price_skipped(self):
        from bot_program.ibkr_data_feed import refresh_ibkr_data_for_user
        from market_data.models import LiveQuote
        client = _make_client(ticker_resp={"lastPrice": "0"})
        r = refresh_ibkr_data_for_user(self.user.id, _client=client)
        self.assertEqual(r["quotes_updated"], 0)
        self.assertEqual(LiveQuote.objects.count(), 0)


# ── Asset-class filter ───────────────────────────────────────────────────

class AssetClassFilterTests(TestCase):
    def test_only_primary_classes_pulled(self):
        """User primary-flagged for stocks only — forex configs ignored."""
        from bot_program.ibkr_data_feed import refresh_ibkr_data_for_user
        u = _user("ac_u")
        _ibkr(u, is_primary_for_stocks=True)  # forex flag False
        _instrument("AAPL", asset_class="stock")
        _instrument("EURUSD", asset_class="forex")
        _abc(u, "stock", name="ST", symbols=["AAPL"])
        _abc(u, "forex", name="FX", symbols=["EURUSD"])

        ts = int(datetime.now(tz=dt_tz.utc).timestamp() * 1000)
        client = _make_client(klines_rows=[_fake_kline(ts)],
                               ticker_resp={"lastPrice": "100"})
        r = refresh_ibkr_data_for_user(u.id, _client=client)
        # Only AAPL pulled. Each call to klines / ticker once per symbol.
        self.assertEqual(r["symbols"], 1)
        self.assertEqual(client.klines.call_count, 1)
        self.assertEqual(client.ticker.call_count, 1)
        client.klines.assert_called_with("AAPL", interval="1h", limit=100)


# ── All-users walker ─────────────────────────────────────────────────────

class AllUsersWalkerTests(TestCase):
    def test_walks_only_connected_accounts(self):
        """Disconnected IBKRAccount is skipped."""
        from bot_program.ibkr_data_feed import refresh_ibkr_data_all_users
        from unittest.mock import patch
        u_on = _user("walk_on")
        u_off = _user("walk_off")
        _ibkr(u_on, connected=True, is_primary_for_stocks=True)
        _ibkr(u_off, connected=False, is_primary_for_stocks=True)
        # Patch the per-user function so we don't need a real client.
        with patch("bot_program.ibkr_data_feed.refresh_ibkr_data_for_user",
                    return_value={"bars_upserted": 0, "quotes_updated": 0,
                                   "errors": 0}) as m:
            r = refresh_ibkr_data_all_users()
        # Only u_on should have been visited.
        self.assertEqual(r["users"], 1)
        self.assertEqual(m.call_count, 1)
        m.assert_called_with(u_on.id, intervals=("1h",), limit=100)


# ── Beat schedule ────────────────────────────────────────────────────────

class BeatScheduleTests(TestCase):
    def test_ibkr_data_feed_in_beat_schedule(self):
        from config.celery import app
        schedule = app.conf.beat_schedule
        self.assertIn("ibkr-data-feed", schedule)
        entry = schedule["ibkr-data-feed"]
        self.assertEqual(entry["task"],
                          "bot_program.tasks.refresh_all_ibkr_market_data")
