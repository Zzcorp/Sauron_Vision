"""Phase-14.1 tests: live OptionContract chain refresh."""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _user(name="ph14_1_u"):
    return User.objects.create_user(username=name, password="x")


def _options_cfg(user, symbols, **extras):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="options", name="Opts",
        enabled=True, mode="paper", symbols=symbols,
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=20.0, take_profit_pct=50.0,
        entry_score_min=0.6, min_signals_for_entry=1,
        extras=extras or {},
    )


def _fake_chain_entry(strike, dte, right="C", *, delta=0.40, iv=0.30,
                       bid=1.0, ask=1.1):
    exp = (date.today() + timedelta(days=dte)).isoformat()
    return {
        "symbol": f"FAKE{int(strike)}{right}",
        "strike": strike, "expiry": exp, "right": right,
        "bid": bid, "ask": ask, "last": (bid + ask) / 2,
        "iv": iv, "delta": delta, "gamma": 0.01,
        "theta": -0.05, "vega": 0.10,
        "open_interest": 100, "volume": 50,
    }


class ChainRefreshForUserTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.inst = _instrument("AAPL", asset_class="stock")

    def _make_client(self, chain):
        client = MagicMock()
        client.option_chain = MagicMock(return_value=chain)
        return client

    def test_no_options_configs_short_circuits(self):
        from bot_program.tasks import refresh_option_chains_for_user
        result = refresh_option_chains_for_user(self.user.id)
        self.assertEqual(result.get("symbols"), 0)
        self.assertIn("skipped", result)

    def test_user_not_found(self):
        from bot_program.tasks import refresh_option_chains_for_user
        result = refresh_option_chains_for_user(99999999)
        self.assertIn("error", result)

    def test_filters_out_of_dte_window(self):
        """Default min_dte=14, max_dte=60 → 5d and 90d entries skipped."""
        from bot_program.tasks import refresh_option_chains_for_user
        from bot_program.options_models import OptionContract
        _options_cfg(self.user, ["AAPL"])

        chain = [
            _fake_chain_entry(180, dte=5),    # too close
            _fake_chain_entry(180, dte=30),   # in window
            _fake_chain_entry(180, dte=90),   # too far
        ]
        client = self._make_client(chain)
        with patch("bot_program.engine.broker_router.client_for_symbol", return_value=client):
            r = refresh_option_chains_for_user(self.user.id)

        self.assertEqual(r["contracts_upserted"], 1)
        self.assertEqual(OptionContract.objects.count(), 1)

    def test_filters_out_of_strike_band_when_underlying_known(self):
        """With LiveQuote at $100, strikes outside ±20% band are dropped."""
        from bot_program.tasks import refresh_option_chains_for_user
        from bot_program.options_models import OptionContract
        from market_data.models import LiveQuote
        LiveQuote.objects.create(instrument=self.inst, last=Decimal("100"))
        _options_cfg(self.user, ["AAPL"])

        chain = [
            _fake_chain_entry(70, dte=30),     # -30% — out
            _fake_chain_entry(95, dte=30),     # -5%  — in
            _fake_chain_entry(100, dte=30),    # ATM — in
            _fake_chain_entry(110, dte=30),    # +10% — in
            _fake_chain_entry(140, dte=30),    # +40% — out
        ]
        client = self._make_client(chain)
        with patch("bot_program.engine.broker_router.client_for_symbol", return_value=client):
            r = refresh_option_chains_for_user(self.user.id)

        self.assertEqual(r["contracts_upserted"], 3)
        self.assertEqual(OptionContract.objects.count(), 3)
        strikes = sorted(float(c.strike) for c in OptionContract.objects.all())
        self.assertEqual(strikes, [95.0, 100.0, 110.0])

    def test_upsert_overwrites_greeks(self):
        """Calling refresh twice with updated Greeks updates the existing row."""
        from bot_program.tasks import refresh_option_chains_for_user
        from bot_program.options_models import OptionContract
        _options_cfg(self.user, ["AAPL"])

        first = [_fake_chain_entry(180, dte=30, delta=0.40, iv=0.25)]
        second = [_fake_chain_entry(180, dte=30, delta=0.55, iv=0.40)]

        client = self._make_client(first)
        with patch("bot_program.engine.broker_router.client_for_symbol", return_value=client):
            refresh_option_chains_for_user(self.user.id)
        self.assertEqual(OptionContract.objects.count(), 1)

        client = self._make_client(second)
        with patch("bot_program.engine.broker_router.client_for_symbol", return_value=client):
            refresh_option_chains_for_user(self.user.id)
        self.assertEqual(OptionContract.objects.count(), 1)

        c = OptionContract.objects.first()
        self.assertEqual(c.delta, 0.55)
        self.assertEqual(c.iv, 0.40)

    def test_extras_dte_window_widens_filter(self):
        """extras={'min_dte':5,'max_dte':120} → 5d and 90d both upserted."""
        from bot_program.tasks import refresh_option_chains_for_user
        from bot_program.options_models import OptionContract
        _options_cfg(self.user, ["AAPL"], min_dte=5, max_dte=120)

        chain = [
            _fake_chain_entry(180, dte=5),
            _fake_chain_entry(180, dte=30),
            _fake_chain_entry(180, dte=90),
        ]
        client = self._make_client(chain)
        with patch("bot_program.engine.broker_router.client_for_symbol", return_value=client):
            r = refresh_option_chains_for_user(self.user.id)

        self.assertEqual(r["contracts_upserted"], 3)
        self.assertEqual(OptionContract.objects.count(), 3)

    def test_skips_paper_client_without_option_chain(self):
        """PaperTrader has no option_chain method → skip cleanly."""
        from bot_program.tasks import refresh_option_chains_for_user
        from bot_program.engine.paper_trader import PaperTrader
        from bot_program.options_models import OptionContract
        _options_cfg(self.user, ["AAPL"])

        cfg = MagicMock()
        client = PaperTrader(cfg)
        with patch("bot_program.engine.broker_router.client_for_symbol", return_value=client):
            r = refresh_option_chains_for_user(self.user.id)
        self.assertEqual(r["contracts_upserted"], 0)
        self.assertEqual(OptionContract.objects.count(), 0)


class RefreshAllOptionChainsTests(TestCase):
    def test_iterates_distinct_users(self):
        from bot_program.tasks import _refresh_all_option_chains_impl
        u1 = _user("rch_a")
        u2 = _user("rch_b")
        _options_cfg(u1, ["AAPL"])
        _options_cfg(u2, ["MSFT"])
        with patch("bot_program.tasks.refresh_option_chains_for_user",
                   return_value={"contracts_upserted": 3}) as m:
            r = _refresh_all_option_chains_impl()
        self.assertEqual(r["users"], 2)
        self.assertEqual(r["total_upserted"], 6)
        self.assertEqual(m.call_count, 2)


class BeatScheduleTests(TestCase):
    def test_refresh_option_chains_in_beat_schedule(self):
        from config.celery import app
        schedule = app.conf.beat_schedule
        self.assertIn("refresh-option-chains", schedule)
        entry = schedule["refresh-option-chains"]
        self.assertEqual(entry["task"], "bot_program.tasks.refresh_all_option_chains")
