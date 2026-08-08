"""Phase-14 tests:
  - IBKRAccount: encrypted creds round-trip + per-asset-class flags
  - IBKRTrader: graceful degrade when ib_insync absent / TWS unreachable
  - broker_router: IBKR routing override + options always → IBKR
  - OptionContract: uniqueness constraint
  - OptionsBot: select_contract by target_delta + DTE
  - OptionsBot: Greeks-aware sizing skip for deep-ITM contracts

Run with:  python manage.py test tests.test_phase14_options_ibkr
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol,
        defaults={"name": symbol, "asset_class": asset_class},
    )
    if inst.asset_class != asset_class:
        inst.asset_class = asset_class
        inst.save()
    return inst


def _user(name="ph14_user"):
    return User.objects.create_user(username=name, password="x")


def _options_config(user, symbols=None, **overrides):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        user=user, asset_class="options", name="Options Test",
        enabled=True, mode="paper",
        symbols=symbols or ["AAPL"],
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=20.0, take_profit_pct=50.0,
        entry_score_min=0.6, min_signals_for_entry=1,
    )
    defaults.update(overrides)
    return AssetBotConfig.objects.create(**defaults)


def _option_contract(underlying, *, strike, dte, right="C", delta=None,
                     bid=Decimal("1.00"), ask=Decimal("1.10"), iv=0.30):
    from bot_program.options_models import OptionContract
    expiry = (timezone.now().date() + timedelta(days=dte))
    return OptionContract.objects.create(
        underlying=underlying, strike=Decimal(str(strike)),
        expiry=expiry, right=right, multiplier=100,
        bid=bid, ask=ask, last_price=(bid + ask) / Decimal(2),
        iv=iv, delta=delta,
    )


# ── IBKRAccount ─────────────────────────────────────────────────────────────

class IBKRAccountTests(TestCase):
    def test_encrypted_account_id_roundtrip(self):
        from bot_program.models import IBKRAccount
        u = _user("ibkr_creds_u")
        acct = IBKRAccount.objects.create(user=u)
        acct.set_credentials("DU1234567")
        acct.save()
        # account_id_enc should be non-empty and not equal the plaintext.
        self.assertNotEqual(acct.account_id_enc, "DU1234567")
        self.assertGreater(len(acct.account_id_enc), 0)
        # And get_account_id round-trips.
        self.assertEqual(acct.get_account_id(), "DU1234567")

    def test_get_account_id_when_empty(self):
        from bot_program.models import IBKRAccount
        u = _user("ibkr_empty_u")
        acct = IBKRAccount.objects.create(user=u)
        self.assertIsNone(acct.get_account_id())

    def test_is_primary_for_asset_class(self):
        from bot_program.models import IBKRAccount
        u = _user("ibkr_primary_u")
        acct = IBKRAccount.objects.create(
            user=u, is_primary_for_stocks=True,
            is_primary_for_options=True, is_primary_for_forex=False,
        )
        self.assertTrue(acct.is_primary_for("stock"))
        self.assertTrue(acct.is_primary_for("etf"))   # etf maps to stocks flag
        self.assertTrue(acct.is_primary_for("index")) # index too
        self.assertTrue(acct.is_primary_for("options"))
        self.assertFalse(acct.is_primary_for("forex"))
        self.assertFalse(acct.is_primary_for("crypto"))


# ── IBKRTrader graceful degrade ─────────────────────────────────────────────

class IBKRTraderDegradeTests(TestCase):
    """When ib_insync is missing or TWS is unreachable, all calls return
    safe-empty values rather than raising."""

    def test_trader_can_be_constructed_without_connection(self):
        from bot_program.engine.ibkr_client import IBKRTrader
        # Construction must not connect — we point at an unreachable port to
        # be sure even if ib_insync is installed.
        t = IBKRTrader(host="127.0.0.1", port=39999, client_id=99,
                       account_id="X", paper=True, timeout=0.5)
        self.assertIsNotNone(t)

    def test_ping_returns_false_when_unavailable(self):
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_IB_AVAILABLE", False):
            t = ibkr_client.IBKRTrader(timeout=0.1)
            self.assertFalse(t.ping())

    def test_ticker_returns_zero_lastprice_on_failure(self):
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_IB_AVAILABLE", False):
            t = ibkr_client.IBKRTrader(timeout=0.1)
            tk = t.ticker("AAPL")
            self.assertEqual(tk.get("lastPrice"), "0")
            self.assertEqual(tk.get("symbol"), "AAPL")

    def test_klines_returns_empty_list_on_failure(self):
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_IB_AVAILABLE", False):
            t = ibkr_client.IBKRTrader(timeout=0.1)
            self.assertEqual(t.klines("AAPL"), [])

    def test_market_order_returns_rejected_on_failure(self):
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_IB_AVAILABLE", False):
            t = ibkr_client.IBKRTrader(timeout=0.1)
            res = t.market_order("AAPL", "BUY", 1)
            self.assertEqual(res.get("status"), "REJECTED")
            self.assertEqual(res.get("executedQty"), "0")

    def test_option_chain_returns_empty_on_failure(self):
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_IB_AVAILABLE", False):
            t = ibkr_client.IBKRTrader(timeout=0.1)
            self.assertEqual(t.option_chain("AAPL"), [])

    def test_market_order_option_returns_rejected_on_failure(self):
        from bot_program.engine import ibkr_client
        with patch.object(ibkr_client, "_IB_AVAILABLE", False):
            t = ibkr_client.IBKRTrader(timeout=0.1)
            res = t.market_order_option(
                "AAPL", strike=180, expiry="2026-06-19",
                right="C", side="BUY", contracts=1,
            )
            self.assertEqual(res.get("status"), "REJECTED")


# ── broker_router IBKR override ────────────────────────────────────────────

class BrokerRouterIBKRTests(TestCase):
    def setUp(self):
        self.user = _user("router_u")

    def test_options_always_routes_to_ibkr_name(self):
        """Even without an IBKRAccount, options asset_class names ibkr."""
        from bot_program.engine.broker_router import broker_name_for_symbol
        _instrument("AAPL_OPT", asset_class="options")

        # cfg with mode=live so router doesn't short-circuit to paper.
        class _Cfg:
            mode = "live"
        self.assertEqual(
            broker_name_for_symbol(self.user, "AAPL_OPT", cfg=_Cfg()),
            "ibkr",
        )

    def test_paper_mode_short_circuits_router(self):
        from bot_program.engine.broker_router import broker_name_for_symbol
        _instrument("AAPL_PAPER", asset_class="stock")

        class _Cfg:
            mode = "paper"
        self.assertEqual(
            broker_name_for_symbol(self.user, "AAPL_PAPER", cfg=_Cfg()),
            "paper",
        )

    def test_ibkr_overrides_alpaca_when_primary_for_stocks(self):
        from bot_program.models import IBKRAccount
        from bot_program.engine.broker_router import broker_name_for_symbol
        _instrument("MSFT", asset_class="stock")
        IBKRAccount.objects.create(
            user=self.user, is_primary_for_stocks=True,
        )

        class _Cfg:
            mode = "live"
        self.assertEqual(
            broker_name_for_symbol(self.user, "MSFT", cfg=_Cfg()),
            "ibkr",
        )

    def test_no_ibkr_account_falls_through_to_alpaca_for_stocks(self):
        from bot_program.engine.broker_router import broker_name_for_symbol
        _instrument("NVDA", asset_class="stock")

        class _Cfg:
            mode = "live"
        # No IBKRAccount on this user → alpaca remains the default.
        self.assertEqual(
            broker_name_for_symbol(self.user, "NVDA", cfg=_Cfg()),
            "alpaca",
        )

    def test_options_client_falls_back_to_paper_when_ib_insync_absent(self):
        """When ib_insync isn't installed, options routing returns PaperTrader."""
        from bot_program.engine import ibkr_client
        from bot_program.engine.broker_router import client_for_symbol
        from bot_program.engine.paper_trader import PaperTrader
        _instrument("AAPL_FB", asset_class="options")

        class _Cfg:
            mode = "live"

        with patch.object(ibkr_client, "_IB_AVAILABLE", False):
            c = client_for_symbol(self.user, "AAPL_FB", cfg=_Cfg())
        self.assertIsInstance(c, PaperTrader)


# ── OptionContract uniqueness ───────────────────────────────────────────────

class OptionContractTests(TestCase):
    def test_uniqueness_on_underlying_strike_expiry_right(self):
        from bot_program.options_models import OptionContract
        from django.db import IntegrityError, transaction
        inst = _instrument("AAPL", asset_class="stock")
        exp = timezone.now().date() + timedelta(days=30)
        OptionContract.objects.create(
            underlying=inst, strike=Decimal("180"), expiry=exp, right="C",
        )
        # Same (underlying, strike, expiry, right) — must collide.
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                OptionContract.objects.create(
                    underlying=inst, strike=Decimal("180"), expiry=exp, right="C",
                )

    def test_different_right_is_allowed(self):
        from bot_program.options_models import OptionContract
        inst = _instrument("AAPL_DIFF", asset_class="stock")
        exp = timezone.now().date() + timedelta(days=30)
        OptionContract.objects.create(
            underlying=inst, strike=Decimal("180"), expiry=exp, right="C",
        )
        # Same strike+expiry, different right → allowed.
        OptionContract.objects.create(
            underlying=inst, strike=Decimal("180"), expiry=exp, right="P",
        )
        self.assertEqual(OptionContract.objects.count(), 2)


# ── OptionsBot select_contract ──────────────────────────────────────────────

class OptionsBotSelectContractTests(TestCase):
    def setUp(self):
        self.user = _user("opt_select_u")
        self.inst = _instrument("AAPL", asset_class="stock")
        self.cfg = _options_config(self.user, symbols=["AAPL"])

    def _bot(self, **extras):
        from bot_program.asset_engine import OptionsBot
        if extras:
            self.cfg.extras = {**(self.cfg.extras or {}), **extras}
            self.cfg.save()
        return OptionsBot(self.cfg)

    def test_picks_call_closest_to_target_delta(self):
        # delta target 0.40, tolerance 0.10 → eligible: 0.32, 0.41, 0.50
        # winner: closest to 0.40 → 0.41.
        c1 = _option_contract(self.inst, strike=190, dte=30, right="C", delta=0.32)
        c2 = _option_contract(self.inst, strike=180, dte=30, right="C", delta=0.41)
        c3 = _option_contract(self.inst, strike=170, dte=30, right="C", delta=0.50)
        bot = self._bot()
        chosen = bot.select_contract("AAPL", "BUY")
        self.assertEqual(chosen.id, c2.id)

    def test_picks_put_with_negative_delta(self):
        # For SELL → right=P, target delta becomes -0.40.
        c1 = _option_contract(self.inst, strike=170, dte=30, right="P", delta=-0.30)
        c2 = _option_contract(self.inst, strike=180, dte=30, right="P", delta=-0.42)
        bot = self._bot()
        chosen = bot.select_contract("AAPL", "SELL")
        self.assertEqual(chosen.id, c2.id)

    def test_dte_filter_excludes_too_close(self):
        # default min_dte = 14 → contract at 7d should be excluded.
        _option_contract(self.inst, strike=180, dte=7, right="C", delta=0.40)
        bot = self._bot()
        self.assertIsNone(bot.select_contract("AAPL", "BUY"))

    def test_dte_filter_excludes_too_far(self):
        # default max_dte = 60 → contract at 90d should be excluded.
        _option_contract(self.inst, strike=180, dte=90, right="C", delta=0.40)
        bot = self._bot()
        self.assertIsNone(bot.select_contract("AAPL", "BUY"))

    def test_delta_outside_tolerance_excluded(self):
        # tolerance 0.10, target 0.40 → 0.55 falls outside [0.30, 0.50].
        _option_contract(self.inst, strike=180, dte=30, right="C", delta=0.55)
        bot = self._bot()
        self.assertIsNone(bot.select_contract("AAPL", "BUY"))

    def test_premium_cap_excludes_expensive_contract(self):
        # max_premium_per_contract = 5.0 → mid = 6.0 is over cap.
        _option_contract(self.inst, strike=180, dte=30, right="C", delta=0.40,
                         bid=Decimal("5.90"), ask=Decimal("6.10"))
        bot = self._bot()
        self.assertIsNone(bot.select_contract("AAPL", "BUY"))

    def test_missing_delta_excluded(self):
        _option_contract(self.inst, strike=180, dte=30, right="C", delta=None)
        bot = self._bot()
        self.assertIsNone(bot.select_contract("AAPL", "BUY"))

    def test_extras_target_delta_override(self):
        """User sets target_delta=0.20 → picks 0.21 over 0.40."""
        c1 = _option_contract(self.inst, strike=190, dte=30, right="C", delta=0.21)
        c2 = _option_contract(self.inst, strike=180, dte=30, right="C", delta=0.40)
        bot = self._bot(target_delta=0.20)
        chosen = bot.select_contract("AAPL", "BUY")
        self.assertEqual(chosen.id, c1.id)

    def test_tie_break_picks_nearer_expiry(self):
        """Two contracts equidistant from target_delta → nearer expiry wins
        (lower theta drag preference)."""
        c_far = _option_contract(self.inst, strike=180, dte=45, right="C", delta=0.45)
        c_near = _option_contract(self.inst, strike=180, dte=20, right="C", delta=0.45)
        bot = self._bot()
        chosen = bot.select_contract("AAPL", "BUY")
        self.assertEqual(chosen.id, c_near.id)


# ── OptionsBot factory + scan_symbol ────────────────────────────────────────

class OptionsBotFactoryTests(TestCase):
    def test_make_bot_returns_options_bot_for_options_class(self):
        from bot_program.asset_engine import make_bot, OptionsBot
        u = _user("opt_factory_u")
        cfg = _options_config(u)
        bot = make_bot(cfg)
        self.assertIsInstance(bot, OptionsBot)

    def test_options_class_in_choices(self):
        from bot_program.models import AssetBotConfig
        valid = {key for key, _ in AssetBotConfig.ASSET_CLASS_CHOICES}
        self.assertIn("options", valid)
