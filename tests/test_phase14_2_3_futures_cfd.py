"""Phase-14.2 / 14.3 tests:
  - Instrument.metadata-driven contract builder (FUT, CFD, IND, CASH, STK)
  - Futures support via FUTURES_DEFAULT_EXCHANGE map
  - CFD routing via IBKRAccount.is_primary_for_cfd
  - Schema: AssetBotConfig accepts asset_class='cfd'
"""
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase


def _instrument(symbol, asset_class="stock", metadata=None):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol,
        defaults={"name": symbol, "asset_class": asset_class,
                  "metadata": metadata or {}},
    )
    if metadata:
        inst.metadata = metadata
        inst.save()
    if inst.asset_class != asset_class:
        inst.asset_class = asset_class
        inst.save()
    return inst


def _user(name="ph14_23_u"):
    return User.objects.create_user(username=name, password="x")


# ── 14.2: contract builder honours metadata ────────────────────────────────

class ContractBuilderMetadataTests(TestCase):
    """The trader uses Instrument.metadata['ibkr'] to pick the IBKR contract
    type. We inject a fake `_ib` module and assert the right factory is
    called with the expected kwargs."""

    def setUp(self):
        from bot_program.engine import ibkr_client
        self.ibkr_client = ibkr_client

        # Build a fake _ib module — just the factories we need.
        self.fake_ib = MagicMock()
        self.fake_ib.Stock = MagicMock(side_effect=lambda *a, **kw: ("STK", a, kw))
        self.fake_ib.Forex = MagicMock(side_effect=lambda pair: ("CASH", pair))
        self.fake_ib.Future = MagicMock(side_effect=lambda *a, **kw: ("FUT", a, kw))
        self.fake_ib.ContFuture = MagicMock(side_effect=lambda *a, **kw: ("CONTFUT", a, kw))
        self.fake_ib.CFD = MagicMock(side_effect=lambda *a, **kw: ("CFD", a, kw))
        self.fake_ib.Index = MagicMock(side_effect=lambda *a, **kw: ("IND", a, kw))

        self._patches = [
            patch.object(ibkr_client, "_ib", self.fake_ib),
            patch.object(ibkr_client, "_IB_AVAILABLE", True),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _trader(self):
        return self.ibkr_client.IBKRTrader(timeout=0.1)

    # ── FUT ────────────────────────────────────────────────────────────

    def test_future_with_explicit_expiry(self):
        _instrument("CL", asset_class="commodity", metadata={
            "ibkr": {"sec_type": "FUT", "expiry": "20260719"},
        })
        c = self._trader()._build_contract("CL")
        self.assertEqual(c[0], "FUT")
        # Future call should pass exchange=NYMEX (CL default)
        kwargs = c[2]
        self.assertEqual(kwargs.get("exchange"), "NYMEX")
        self.assertEqual(kwargs.get("currency"), "USD")
        self.assertEqual(kwargs.get("lastTradeDateOrContractMonth"), "20260719")

    def test_future_for_es_uses_globex(self):
        _instrument("ES", asset_class="commodity", metadata={
            "ibkr": {"sec_type": "FUT", "expiry": "202609"},
        })
        c = self._trader()._build_contract("ES")
        self.assertEqual(c[0], "FUT")
        self.assertEqual(c[2].get("exchange"), "GLOBEX")

    def test_future_with_explicit_exchange_overrides_default(self):
        _instrument("CL", asset_class="commodity", metadata={
            "ibkr": {"sec_type": "FUT", "expiry": "20260719",
                     "exchange": "NYMEX_OVR"},
        })
        c = self._trader()._build_contract("CL")
        self.assertEqual(c[2].get("exchange"), "NYMEX_OVR")

    def test_future_with_no_expiry_falls_back_to_continuous(self):
        _instrument("GC", asset_class="commodity", metadata={
            "ibkr": {"sec_type": "FUT"},
        })
        c = self._trader()._build_contract("GC")
        self.assertEqual(c[0], "CONTFUT")  # ContFuture used

    def test_future_with_multiplier_passed_through(self):
        _instrument("CL", asset_class="commodity", metadata={
            "ibkr": {"sec_type": "FUT", "expiry": "202609", "multiplier": "1000"},
        })
        c = self._trader()._build_contract("CL")
        self.assertEqual(c[2].get("multiplier"), "1000")

    # ── CFD ────────────────────────────────────────────────────────────

    def test_cfd_explicit_metadata(self):
        _instrument("IBUS500", asset_class="cfd", metadata={
            "ibkr": {"sec_type": "CFD", "exchange": "SMART", "currency": "USD"},
        })
        c = self._trader()._build_contract("IBUS500")
        self.assertEqual(c[0], "CFD")

    def test_cfd_with_localsymbol_override(self):
        _instrument("UK100_CFD", asset_class="cfd", metadata={
            "ibkr": {"sec_type": "CFD", "localSymbol": "IBGB100",
                     "currency": "GBP"},
        })
        c = self._trader()._build_contract("UK100_CFD")
        self.assertEqual(c[0], "CFD")
        self.assertEqual(c[1][0], "IBGB100")  # localSymbol used

    # ── IND ────────────────────────────────────────────────────────────

    def test_index_explicit_metadata(self):
        _instrument("SPX", asset_class="index", metadata={
            "ibkr": {"sec_type": "IND", "exchange": "CBOE"},
        })
        c = self._trader()._build_contract("SPX")
        self.assertEqual(c[0], "IND")

    # ── STK + CASH explicit ───────────────────────────────────────────

    def test_stock_explicit_metadata(self):
        _instrument("AAPL", asset_class="stock", metadata={
            "ibkr": {"sec_type": "STK"},
        })
        c = self._trader()._build_contract("AAPL")
        self.assertEqual(c[0], "STK")

    def test_cash_explicit_metadata(self):
        _instrument("EURUSD_C", asset_class="forex", metadata={
            "ibkr": {"sec_type": "CASH", "localSymbol": "EURUSD"},
        })
        c = self._trader()._build_contract("EURUSD_C")
        self.assertEqual(c[0], "CASH")
        self.assertEqual(c[1], "EURUSD")

    # ── Heuristic fallback (no metadata) ──────────────────────────────

    def test_heuristic_forex_for_six_letter_symbol(self):
        # No Instrument record → no metadata → heuristic kicks in.
        c = self._trader()._build_contract("GBPUSD")
        self.assertEqual(c[0], "CASH")
        self.assertEqual(c[1], "GBPUSD")

    def test_heuristic_stock_for_normal_symbol(self):
        c = self._trader()._build_contract("MSFT")
        self.assertEqual(c[0], "STK")


# ── 14.3: CFD routing + flag ───────────────────────────────────────────────

class CFDRoutingTests(TestCase):
    def setUp(self):
        self.user = _user("cfd_route_u")

    def test_cfd_asset_class_always_routes_to_ibkr_name(self):
        from bot_program.engine.broker_router import broker_name_for_symbol
        _instrument("IBUS500", asset_class="cfd")

        class _Cfg:
            mode = "live"
        self.assertEqual(
            broker_name_for_symbol(self.user, "IBUS500", cfg=_Cfg()),
            "ibkr",
        )

    def test_is_primary_for_cfd_flag(self):
        from bot_program.models import IBKRAccount
        acct = IBKRAccount.objects.create(
            user=self.user, is_primary_for_cfd=True,
        )
        self.assertTrue(acct.is_primary_for("cfd"))
        self.assertFalse(acct.is_primary_for("stock"))

    def test_cfd_in_asset_bot_choices(self):
        from bot_program.models import AssetBotConfig
        valid = {key for key, _ in AssetBotConfig.ASSET_CLASS_CHOICES}
        self.assertIn("cfd", valid)


# ── 14.2: futures default-exchange map ─────────────────────────────────────

class FuturesExchangeMapTests(TestCase):
    def test_known_futures_have_exchange(self):
        from bot_program.engine.ibkr_client import FUTURES_DEFAULT_EXCHANGE
        # Spot-check a handful — we want this to be a stable contract.
        self.assertEqual(FUTURES_DEFAULT_EXCHANGE.get("CL"), "NYMEX")
        self.assertEqual(FUTURES_DEFAULT_EXCHANGE.get("GC"), "COMEX")
        self.assertEqual(FUTURES_DEFAULT_EXCHANGE.get("ES"), "GLOBEX")
        self.assertEqual(FUTURES_DEFAULT_EXCHANGE.get("ZB"), "CBOT")

    def test_unknown_future_falls_back_to_globex_in_builder(self):
        from bot_program.engine import ibkr_client
        fake_ib = MagicMock()
        fake_ib.Future = MagicMock(side_effect=lambda *a, **kw: ("FUT", a, kw))
        with patch.object(ibkr_client, "_ib", fake_ib), \
             patch.object(ibkr_client, "_IB_AVAILABLE", True):
            _instrument("ZZZ", asset_class="commodity", metadata={
                "ibkr": {"sec_type": "FUT", "expiry": "202609"},
            })
            t = ibkr_client.IBKRTrader(timeout=0.1)
            c = t._build_contract("ZZZ")
            self.assertEqual(c[2].get("exchange"), "GLOBEX")
