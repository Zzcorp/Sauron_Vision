"""Backfill reaches every asset class, not only crypto.

The signal scanner reads DAILY closes and every evaluator needs a lookback.
The scheduled feeds write one daily bar per day, so the eleven commodity
ETFs created on Monday 2026-09-07 had six daily bars by Thursday: no
evaluator could compute, the one live bot that could afford its symbols sat
on `no_signals`, and the only backfill command on the platform spoke to
Binance. The command now routes by asset class — Binance for crypto, the
keyless Yahoo feed `refresh_bot_bars` already falls back to for the rest —
and `--from-configs` means what its help always said: every enabled bot.

Run with:  python manage.py test tests.test_backfill_bars_every_class
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase


def _instrument(symbol, asset_class):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol,
        defaults={"name": symbol, "asset_class": asset_class,
                  "currency": "USD", "is_active": True})
    if inst.asset_class != asset_class:
        inst.asset_class = asset_class
        inst.save(update_fields=["asset_class"])
    return inst


def _cfg(user, asset_class, symbols, *, enabled=True):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=f"bf_{asset_class}",
        mode="paper", symbols=list(symbols), capital=Decimal("500"),
        enabled=enabled)


def _klines(n, step_ms=86_400_000, start_ms=1_756_000_000_000):
    return [[start_ms + i * step_ms, "100", "101", "99", "100.5", "1000"]
            for i in range(n)]


def _feed(rows=None, raises=None):
    feed = MagicMock(name="YFinanceFeed")
    if raises is not None:
        feed.klines.side_effect = raises
    else:
        feed.klines.return_value = rows if rows is not None else _klines(5)
    return feed


def _run(*args):
    out, err = StringIO(), StringIO()
    call_command("backfill_bars", *args, stdout=out, stderr=err)
    return out.getvalue(), err.getvalue()


class EveryClassTests(TestCase):

    def test_an_etf_is_served_by_the_public_feed_in_one_call(self):
        from market_data.models import PriceData
        inst = _instrument("GLDM", "etf")
        feed = _feed()
        with patch("market_data.public_feed.public_feed_for",
                   return_value=feed) as pf:
            out, _err = _run("--symbols", "GLDM", "--intervals", "1d",
                             "--bars", "300")
        pf.assert_called_once_with("etf")
        feed.klines.assert_called_once_with("GLDM", interval="1d", limit=300)
        self.assertEqual(
            PriceData.objects.filter(instrument=inst, timeframe="1d").count(),
            5)
        self.assertIn("5 bars fetched", out)

    def test_the_bars_say_where_they_came_from(self):
        from market_data.models import PriceData
        inst = _instrument("SLV", "etf")
        with patch("market_data.public_feed.public_feed_for",
                   return_value=_feed()):
            _run("--symbols", "SLV", "--intervals", "1d")
        sources = set(PriceData.objects.filter(instrument=inst)
                      .values_list("source", flat=True))
        self.assertEqual(sources, {"yfinance_public"})

    def test_from_configs_covers_forex_and_stock_bots(self):
        user = User.objects.create_user("bf_u", password="x")
        _instrument("EURUSD", "forex")
        _instrument("AAPL", "stock")
        _instrument("ETHUSD", "crypto")
        _cfg(user, "forex", ["EURUSD"])
        _cfg(user, "stock", ["AAPL"])
        _cfg(user, "crypto", ["ETHUSD"], enabled=False)   # off: not fetched
        feed = _feed()
        with patch("market_data.public_feed.public_feed_for",
                   return_value=feed), \
                patch("bot_program.engine.binance_client.BinanceClient.klines",
                      return_value=[]) as binance:
            _run("--from-configs", "--intervals", "1d")
        fetched = {c.args[0] for c in feed.klines.call_args_list}
        self.assertEqual(fetched, {"EURUSD", "AAPL"})
        binance.assert_not_called()

    def test_crypto_still_pages_binance_and_never_asks_yahoo(self):
        from market_data.models import PriceData
        inst = _instrument("BTCUSD", "crypto")
        with patch("bot_program.engine.binance_client.BinanceClient.klines",
                   side_effect=[_klines(3, step_ms=14_400_000), []]), \
                patch("market_data.public_feed.public_feed_for") as pf:
            _run("--symbols", "BTCUSD", "--intervals", "4h", "--bars", "3")
        pf.assert_not_called()
        self.assertEqual(
            PriceData.objects.filter(instrument=inst, timeframe="4h").count(),
            3)

    def test_a_class_with_no_keyless_source_is_named_and_skipped(self):
        from market_data.models import PriceData
        _instrument("SOMEBOND", "bond")
        with patch("market_data.public_feed.public_feed_for",
                   return_value=None):
            _out, err = _run("--symbols", "SOMEBOND", "--intervals", "1d")
        self.assertIn("no keyless source", err)
        self.assertIn("'bond'", err)
        self.assertEqual(PriceData.objects.count(), 0)

    def test_one_symbols_failure_does_not_end_the_run(self):
        from market_data.models import PriceData
        _instrument("GLDM", "etf")
        slv = _instrument("SLV", "etf")
        feed = _feed()
        feed.klines.side_effect = [RuntimeError("boom"), _klines(4)]
        with patch("market_data.public_feed.public_feed_for",
                   return_value=feed):
            _out, err = _run("--symbols", "GLDM,SLV", "--intervals", "1d")
        self.assertIn("public feed failed: boom", err)
        self.assertEqual(
            PriceData.objects.filter(instrument=slv).count(), 4)

    def test_dry_run_fetches_and_writes_nothing(self):
        from market_data.models import PriceData
        _instrument("GLDM", "etf")
        with patch("market_data.public_feed.public_feed_for",
                   return_value=_feed()):
            out, _err = _run("--symbols", "GLDM", "--intervals", "1d",
                             "--dry-run")
        self.assertEqual(PriceData.objects.count(), 0)
        self.assertIn("would write 5 bars", out)

    def test_the_help_stopped_saying_crypto_only(self):
        from market_data.management.commands.backfill_bars import Command
        self.assertIn("every asset class", Command.help)
        parser = Command().create_parser("manage.py", "backfill_bars")
        from_configs = next(a for a in parser._actions
                            if a.dest == "from_configs")
        self.assertNotIn("crypto", from_configs.help)
