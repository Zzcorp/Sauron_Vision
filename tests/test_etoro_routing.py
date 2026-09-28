"""eToro as an opt-in primary broker (2026-09-17).

The router decides which client a symbol's order goes to. Adding a broker
there is the one change that can move real money to a new venue, so the
rule is: NOTHING changes until an operator flips a flag, and when both
IBKR and eToro are flagged for a class, eToro carries it — retiring IBKR is
the stated direction, and the router is where a direction becomes a fact.

WHAT THESE TESTS CONFRONT

  * `client_for_symbol` and `broker_name_for_symbol` must agree. The first
    is what trades; the second is what the dashboard and logs say traded.
    A router that trades on eToro while the page says IBKR is the worst
    shape a wrong answer can take.
  * The flag is read through `EtoroAccount.is_primary_for()` — the same
    method the page reads — never through a second table.
  * Missing credentials fall to PaperTrader, which `asset_engine` refuses to
    trade live against. A paper-mode config never reaches eToro at all.
  * options / cfd stay forced to IBKR: EtoroAccount has no flag for them,
    so the eToro check cannot fire, and the old rule holds unchanged.
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from bot_program.engine.broker_router import (broker_name_for_symbol,
                                              client_for_symbol)
from bot_program.models import AssetBotConfig, EtoroAccount, IBKRAccount


def _instrument(symbol, asset_class):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _cfg(user, mode="live", asset_class="stock", symbols=("AAPL",)):
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=f"{mode}_{asset_class}",
        mode=mode, symbols=list(symbols), capital=Decimal("1000"),
        base_currency="EUR", enabled=True)


def _etoro(user, *, creds=True, demo=True, **flags):
    acct = EtoroAccount.objects.create(user=user, demo=demo, **flags)
    if creds:
        acct.set_credentials("k", "u")
    acct.save()
    return acct


def _kind(client) -> str:
    return type(client).__name__


class NothingChangesUntilAFlagIsFlippedTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("rt_u", password="x")
        _instrument("AAPL", "stock")
        self.live = _cfg(self.user)

    def test_keys_alone_route_nowhere_new(self):
        _etoro(self.user)                       # creds, no flags
        client = client_for_symbol(self.user, "AAPL", self.live)
        self.assertNotEqual(_kind(client), "EtoroTrader")
        self.assertNotEqual(broker_name_for_symbol(self.user, "AAPL",
                                                   self.live), "etoro")

    def test_the_flag_routes_a_live_config_to_etoro(self):
        _etoro(self.user, is_primary_for_stocks=True)
        client = client_for_symbol(self.user, "AAPL", self.live)
        self.assertEqual(_kind(client), "EtoroTrader")
        self.assertEqual(broker_name_for_symbol(self.user, "AAPL", self.live),
                         "etoro")

    def test_the_demo_flag_decides_the_world_not_the_config(self):
        """A row flagged Demo goes to eToro's demo even for a live-mode
        config — OANDA practice's rule in shape. Not the keys' rule: one
        pair opens both worlds (measured 2026-09-23), so the flag alone
        picks the world, and unticking it sends the same pair live."""
        _etoro(self.user, is_primary_for_stocks=True, demo=True)
        self.assertEqual(client_for_symbol(self.user, "AAPL", self.live).env,
                         "demo")
        EtoroAccount.objects.filter(user=self.user).update(demo=False)
        self.user = User.objects.get(pk=self.user.pk)   # drop the cached row
        self.assertEqual(client_for_symbol(self.user, "AAPL", self.live).env,
                         "live")

    def test_a_paper_config_never_reaches_etoro(self):
        _etoro(self.user, is_primary_for_stocks=True)
        paper = _cfg(self.user, mode="paper")
        self.assertEqual(_kind(client_for_symbol(self.user, "AAPL", paper)),
                         "PaperTrader")
        self.assertEqual(broker_name_for_symbol(self.user, "AAPL", paper),
                         "paper")


class TheFlagWinsOverIbkrTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("rt_both", password="x")
        _instrument("AAPL", "stock")
        self.live = _cfg(self.user)
        ib = IBKRAccount.objects.create(user=self.user, port=4003,
                                        is_primary_for_stocks=True)
        ib.set_credentials("U1")
        ib.save()

    def test_etoro_beats_ibkr_when_both_are_flagged(self):
        _etoro(self.user, is_primary_for_stocks=True)
        client = client_for_symbol(self.user, "AAPL", self.live)
        self.assertEqual(_kind(client), "EtoroTrader")
        self.assertEqual(broker_name_for_symbol(self.user, "AAPL", self.live),
                         "etoro")

    def test_without_the_etoro_flag_ibkr_still_carries_it(self):
        """The old behaviour, byte for byte: the IBKR override is untouched
        for anyone who has not flipped an eToro flag."""
        _etoro(self.user)                       # creds, no flags
        self.assertEqual(broker_name_for_symbol(self.user, "AAPL", self.live),
                         "ibkr")


class TheSafetyFallbacksHoldTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("rt_safe", password="x")
        _instrument("AAPL", "stock")
        self.live = _cfg(self.user)

    def test_a_flag_without_keys_is_paper_which_the_engine_refuses(self):
        """The flag says 'eToro carries stocks'; the row has no keys. The
        router hands back PaperTrader, and asset_engine refuses to trade a
        live config against a PaperTrader — loudly, as a skip. Money does
        not move on a half-configured broker."""
        _etoro(self.user, creds=False, is_primary_for_stocks=True)
        self.assertEqual(_kind(client_for_symbol(self.user, "AAPL",
                                                 self.live)), "PaperTrader")

    def test_options_and_cfd_still_go_to_ibkr(self):
        """No eToro flag exists for either, so the eToro check cannot fire
        and the forced-IBKR rule stands unchanged."""
        _instrument("SPY_OPT", "options")
        _etoro(self.user, is_primary_for_stocks=True,
               is_primary_for_forex=True, is_primary_for_commodity=True,
               is_primary_for_crypto=True)
        self.assertEqual(broker_name_for_symbol(
            self.user, "SPY_OPT", _cfg(self.user, asset_class="options",
                                       symbols=("SPY_OPT",))), "ibkr")

    def test_is_primary_for_maps_etf_and_index_to_stocks(self):
        acct = _etoro(self.user, is_primary_for_stocks=True)
        for cls in ("stock", "etf", "index"):
            self.assertTrue(acct.is_primary_for(cls), cls)
        for cls in ("forex", "commodity", "crypto", "options", "cfd"):
            self.assertFalse(acct.is_primary_for(cls), cls)


class ThePageShowsWhoCarriesWhatTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("rt_page", password="x")
        self.admin = User.objects.create_superuser("rt_admin", "a@x", "x")

    def test_the_column_reads_the_router_s_own_method(self):
        _etoro(self.user, is_primary_for_stocks=True,
               is_primary_for_crypto=True)
        self.client.force_login(self.user)
        body = self.client.get(reverse("brokers_page")).content.decode()
        self.assertIn("Primary for", body)
        row = body[body.index("eToro"):body.index("Saxo Bank")]
        self.assertIn("stock", row)
        self.assertIn("crypto", row)
        self.assertNotIn(">forex<", row)

    def test_saving_reads_the_four_checkboxes(self):
        from unittest import mock
        self.client.force_login(self.admin)
        with mock.patch("dashboard.views_brokers.etoro_probe",
                        return_value=("ok", "200")):
            self.client.post(reverse("hq_save_etoro"), {
                "target_username": "rt_page", "etoro_api_key": "k",
                "etoro_user_key": "u", "demo": "on",
                "primary_stocks": "on", "primary_crypto": "on"})
        acct = EtoroAccount.objects.get(user=self.user)
        self.assertTrue(acct.is_primary_for_stocks)
        self.assertTrue(acct.is_primary_for_crypto)
        self.assertFalse(acct.is_primary_for_forex)
        self.assertFalse(acct.is_primary_for_commodity)

    def test_an_omitted_checkbox_turns_the_flag_off(self):
        """Unchecked = absent = off. A re-save that omits a flag must clear
        it, or a flag flipped once would be impossible to un-flip from the
        page."""
        from unittest import mock
        _etoro(self.user, is_primary_for_stocks=True)
        self.client.force_login(self.admin)
        with mock.patch("dashboard.views_brokers.etoro_probe",
                        return_value=("ok", "200")):
            self.client.post(reverse("hq_save_etoro"), {
                "target_username": "rt_page", "etoro_api_key": "k",
                "etoro_user_key": "u", "demo": "on"})
        self.assertFalse(EtoroAccount.objects.get(user=self.user)
                         .is_primary_for_stocks)


class CommoditiesAndSymbolsWithoutARowTests(TestCase):
    """E3.3 + E3.4 (2026-09-26). The commodities box routes a commodity to
    eToro (eToro lists WHEAT.FUT 97 and PLATINUM 40 as CFDs, measured
    2026-09-23; the platform spells them WHEATUSD and XPTUSD); without a
    box a live commodity config meets a PaperTrader, which execute_entry
    refuses. And the NAME agrees with the CLIENT for a symbol with no
    Instrument row: both route it as crypto (client_for_symbol's default)
    — the name used to say "paper" while the client went to eToro."""

    def setUp(self):
        self.user = User.objects.create_user("rt_cmd", password="x")

    def test_the_commodity_box_routes_wheat_to_etoro(self):
        _instrument("WHEATUSD", "commodity")
        cfg = _cfg(self.user, asset_class="commodity",
                   symbols=("WHEATUSD",))
        _etoro(self.user, is_primary_for_commodity=True)
        self.assertEqual(_kind(client_for_symbol(self.user, "WHEATUSD", cfg)),
                         "EtoroTrader")
        self.assertEqual(broker_name_for_symbol(self.user, "WHEATUSD", cfg),
                         "etoro")

    def test_without_the_box_a_live_commodity_meets_paper(self):
        _instrument("WHEATUSD", "commodity")
        cfg = _cfg(self.user, asset_class="commodity",
                   symbols=("WHEATUSD",))
        _etoro(self.user, is_primary_for_stocks=True)
        self.assertEqual(_kind(client_for_symbol(self.user, "WHEATUSD", cfg)),
                         "PaperTrader")
        self.assertEqual(broker_name_for_symbol(self.user, "WHEATUSD", cfg),
                         "paper")

    def test_a_symbol_with_no_row_is_named_where_the_client_goes(self):
        cfg = _cfg(self.user, asset_class="crypto", symbols=("NOROW1",))
        _etoro(self.user, is_primary_for_crypto=True)
        self.assertEqual(_kind(client_for_symbol(self.user, "NOROW1", cfg)),
                         "EtoroTrader")
        self.assertEqual(broker_name_for_symbol(self.user, "NOROW1", cfg),
                         "etoro")

    def test_with_no_row_and_no_box_it_is_named_like_any_crypto(self):
        """No box, no Binance keys: the router would pick Binance and hands
        back paper, for a row-less symbol exactly as for BTCUSD — and a
        live config refuses to trade against paper."""
        _instrument("BTCUSD", "crypto")
        cfg = _cfg(self.user, asset_class="crypto",
                   symbols=("NOROW1", "BTCUSD"))
        self.assertEqual(broker_name_for_symbol(self.user, "NOROW1", cfg),
                         broker_name_for_symbol(self.user, "BTCUSD", cfg))
        self.assertEqual(broker_name_for_symbol(self.user, "NOROW1", cfg),
                         "binance")
        self.assertEqual(_kind(client_for_symbol(self.user, "NOROW1", cfg)),
                         "PaperTrader")


class TheEntryGateKeepsCommoditiesOnEtoroAndUnreadQuotesOutTests(TestCase):
    """The entry gate's two refusals of the fixer round (2026-09-26),
    AssetBot._etoro_entry_refusal: one rule for the bots and TAKE TRADE.
    Step 0: E3.3 woke the IBKR and Saxo commodity flags (IBKR's reads True
    until deploy/ETORO_DEPARTURE.md §2a), so a live commodity order carried
    by either is refused; every other class on those carriers, and the desk
    seam's MagicMock, pass untouched. Step 1b: the five index CFDs the map
    resolves with their quote currency unread are refused whatever
    ETORO_PROVEN holds; SPX500, quoted as spelled, is not. Neither refusal
    asks any wire anything."""

    PROVEN = "bot_program.asset_engine.base.ETORO_PROVEN"

    def setUp(self):
        from tests.test_etoro_client import _clear_eligibility
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    @staticmethod
    def _gate(client, symbol, icls, side="BUY"):
        from bot_program.asset_engine.base import AssetBot
        return AssetBot._etoro_entry_refusal(client, symbol, side, 1.0, 100.0,
                                             icls)

    def test_a_live_commodity_order_on_ibkr_or_saxo_is_refused(self):
        from unittest.mock import MagicMock
        from bot_program.asset_engine import skips
        for name, key in (("IBKRTrader", "ibkr"), ("SaxoTrader", "saxo")):
            client = type(name, (), {})()
            code, why = self._gate(client, "WHEATUSD", "commodity")
            self.assertEqual(code, skips.GATE_BLOCKED, name)
            self.assertEqual(why, f"WHEATUSD (commodity, BUY): a live "
                                  f"commodity order goes to eToro only — "
                                  f"this one routes to {key}, which has no "
                                  f"commodity proof")
            code, _why = self._gate(client, "XPTUSD", "commodity", "SELL")
            self.assertEqual(code, skips.GATE_BLOCKED, name)
            self.assertEqual(self._gate(client, "AAPL", "stock"), ("", ""))
            self.assertEqual(self._gate(client, "EURUSD", "forex", "SELL"),
                             ("", ""))
        self.assertEqual(self._gate(MagicMock(), "WHEATUSD", "commodity"),
                         ("", ""))

    def test_an_etoro_commodity_order_meets_the_proof_gate_not_step_0(self):
        from bot_program.asset_engine import skips
        from tests.test_etoro_client import _client
        t, fake = _client([])
        code, why = self._gate(t, "WHEATUSD", "commodity")
        self.assertEqual(code, skips.GATE_BLOCKED)
        self.assertIn("no demo fill-and-close proof pinned for ['commodity']",
                      why)
        self.assertNotIn("eToro only", why)
        self.assertEqual(fake.calls, [])

    def test_an_index_with_its_quote_currency_unread_is_refused_when_proven(self):
        from unittest import mock
        from bot_program.asset_engine import skips
        from tests.test_etoro_client import _client
        t, fake = _client([])
        with mock.patch(self.PROVEN, frozenset({"index", "short"})):
            for sym in ("FTSE100", "CAC40", "DAX40", "NIKKEI225", "STOXX50"):
                for side in ("BUY", "SELL"):
                    code, why = self._gate(t, sym, "index", side)
                    self.assertEqual(code, skips.GATE_BLOCKED, sym)
                    self.assertTrue(why.startswith(
                        f"eToro {sym} (index, {side}): quote currency "
                        f"unread"), why)
                    self.assertLessEqual(len(why), 200)
            self.assertEqual(fake.calls, [], "the wire was asked something")
            # SPX500 passes step 1b; what refuses it here is step 2's
            # unread row (this fake answers no /search)
            code, why = self._gate(t, "SPX500", "index")
        self.assertNotEqual(code, skips.GATE_BLOCKED, why)
        self.assertNotIn("quote currency", why)
