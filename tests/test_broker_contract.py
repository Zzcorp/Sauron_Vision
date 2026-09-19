"""The seam Saxo and eToro plug into had no guard on it (2026-09-15).

A broker client is duck-typed across roughly two dozen methods. The only
thing the suite checked was:

    self.assertEqual(wall_facts()["broker_adapters"], len(BROKER_ADAPTERS))

It COUNTED them. Nothing anywhere asserted that an adapter implements the
interface the engine calls. An adapter missing `modify_protective` would pass
every test in this repository and fail at runtime, on a live position, at the
moment a trailing stop is moved — which is the worst possible time and the
hardest possible place to see it.

Two more brokers are about to be added. This is the guard that makes that
safe, and it had to exist first.

WHY TIERS AND NOT ONE FLAT LIST

Measured across the six adapters, only FIVE methods are implemented by all of
them: ping, ticker, klines, order_book, market_order. The rest genuinely
varies — `net_liquidation` is IBKR-only, which is exactly why
`sync_broker_account` reads IBKR accounts and no others; `modify_protective`
is absent from both Binance clients. A contract demanding everything of
everyone would have been red on the day it was written, and a red test
nobody can fix is a test somebody deletes.

WHAT THESE TESTS CONFRONT

`ADAPTER_CAPABILITIES` is what the platform BELIEVES. `capabilities_of()`
reads the class and reports what is THERE. Neither can be edited into
agreement with a bug without editing the other — a method quietly lost fails
here, a capability claimed and not implemented fails here, and a new adapter
that fills a tier only halfway fails here naming the method it lacks.
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from bot_program.engine import capabilities as cap

#: adapter name -> (module path, class name). The names come from
#: core/wall_facts.py::BROKER_ADAPTERS, which is the list this platform
#: publishes as "brokers we support".
ADAPTERS = {
    "alpaca": ("bot_program.engine.alpaca_client", "AlpacaTrader"),
    "binance": ("bot_program.engine.binance_client", "BinanceClient"),
    "binance_futures": ("bot_program.engine.binance_futures_client",
                        "BinanceFuturesClient"),
    "etoro": ("bot_program.engine.etoro_client", "EtoroTrader"),
    "ibkr": ("bot_program.engine.ibkr_client", "IBKRTrader"),
    "oanda": ("bot_program.engine.oanda_client", "OANDATrader"),
    "paper": ("bot_program.engine.paper_trader", "PaperTrader"),
    "saxo": ("bot_program.engine.saxo_client", "SaxoTrader"),
}


def _klass(name):
    import importlib
    module, cls = ADAPTERS[name]
    return getattr(importlib.import_module(module), cls)


class TheListAndTheTableAgreeTests(SimpleTestCase):
    """Three lists name the adapters. They must name the same set —
    six on 2026-09-16, eight since Saxo joined on 2026-09-18."""

    def test_every_published_adapter_has_a_capability_row(self):
        from core.wall_facts import BROKER_ADAPTERS
        missing = set(BROKER_ADAPTERS) - set(cap.ADAPTER_CAPABILITIES)
        self.assertEqual(
            missing, set(),
            f"{sorted(missing)} is published as a broker this platform "
            f"supports and declares no capabilities — the engine would have "
            f"to guess what it can be asked for")

    def test_every_capability_row_is_a_published_adapter(self):
        from core.wall_facts import BROKER_ADAPTERS
        extra = set(cap.ADAPTER_CAPABILITIES) - set(BROKER_ADAPTERS)
        self.assertEqual(
            extra, set(),
            f"{sorted(extra)} declares capabilities and is not in "
            f"BROKER_ADAPTERS — either it is a broker and should be "
            f"published, or it is not and should not be here")

    def test_this_test_file_knows_every_adapter(self):
        from core.wall_facts import BROKER_ADAPTERS
        self.assertEqual(set(ADAPTERS), set(BROKER_ADAPTERS),
                         "a broker was added and this guard does not walk it")

    def test_every_adapter_has_a_broker_key(self):
        """A live row records WHICH broker carried it, from the client that
        placed the order (capabilities.adapter_key). An adapter missing from
        that table records nothing, and /tresor/ then compares the row
        against the wrong broker's holdings — or against none."""
        missing = {n for n in ADAPTERS
                   if cap.adapter_key(_klass(n)) != n}
        self.assertEqual(
            missing, set(),
            f"{sorted(missing)}: capabilities.ADAPTER_CLASS_KEYS does not map "
            f"this adapter's class to its broker key, so a position it "
            f"carries cannot say so")

    def test_no_capability_is_declared_that_does_not_exist(self):
        for adapter, tiers in cap.ADAPTER_CAPABILITIES.items():
            for tier in tiers:
                self.assertIn(
                    tier, cap.CAPABILITIES,
                    f"{adapter} declares {tier!r}, which is not a capability")


class WhatIsDeclaredIsWhatIsThereTests(SimpleTestCase):
    """The confrontation. The table says; the class shows."""

    def test_each_adapter_provides_exactly_what_it_declares(self):
        for name in sorted(ADAPTERS):
            with self.subTest(adapter=name):
                found = set(cap.capabilities_of(_klass(name)))
                said = set(cap.declared(name))
                lost = said - found
                gained = found - said
                detail = ""
                for tier in sorted(lost):
                    detail += (f"\n  {tier}: missing "
                               f"{list(cap.missing_methods(_klass(name), tier))}")
                self.assertEqual(
                    lost, set(),
                    f"{name} is declared to provide {sorted(lost)} and does "
                    f"not.{detail}\nThis is the failure that used to surface "
                    f"on a live position instead of here.")
                self.assertEqual(
                    gained, set(),
                    f"{name} now provides {sorted(gained)} and the table does "
                    f"not say so. Add it — an undeclared capability is one "
                    f"the engine will never use.")

    def test_a_tier_needs_all_of_its_methods(self):
        """Half a bracket is not half a capability: a stop that can be set
        and never moved is a stop that will not trail."""
        class _Half:
            def modify_protective(self):
                pass

        self.assertNotIn("brackets", cap.capabilities_of(_Half))
        self.assertEqual(cap.missing_methods(_Half, "brackets"),
                         ("modify_target",))

    def test_has_capability_asks_the_instance(self):
        """The table is what the suite checks; this is what the engine calls,
        so a client the router built in an unusual way answers for itself."""
        self.assertTrue(cap.has_capability(_klass("ibkr"), "account"))
        self.assertFalse(cap.has_capability(_klass("binance"), "brackets"))


class TheFactsBehindTheTableTests(SimpleTestCase):
    """Four measured facts, pinned because each one explains a behaviour an
    operator will otherwise find surprising."""

    def test_which_adapters_can_be_asked_for_the_account(self):
        """Until 2026-09-17 only IBKR could answer net_liquidation, which is
        why `sync_broker_account` walked IBKRAccount and nothing else.
        eToro joined that day and `sync_etoro_accounts` walks it since
        eaa68da. Saxo joined with its adapter — and the sync does NOT walk
        SaxoAccount yet, the router does not route to it, and the book
        cannot be a Saxo row. That gap is recorded here on purpose, as the
        eToro one was: a Saxo account's equity will not reach the pages,
        the drawdown governor or the preflight until the wiring commit.
        The next adapter that joins this set should make the same note,
        or fix the sync."""
        able = {n for n in ADAPTERS
                if cap.has_capability(_klass(n), "account")}
        self.assertEqual(
            able, {"ibkr", "etoro", "saxo"},
            "the set of adapters that can read an account changed; decide "
            "here whether the broker sync walks the newcomer, rather than "
            "letting its equity go unread in silence")

    def test_the_simulator_claims_nothing_it_cannot_simulate(self):
        """PaperTrader is what a live config falls back to when credentials
        are missing, and asset_engine REFUSES to trade when it gets one. A
        simulator claiming `brackets` would make that refusal harder to see."""
        self.assertEqual(set(cap.declared("paper")),
                         {"market_data", "execution"})

    def test_every_adapter_can_at_least_read_a_market_and_place_an_order(self):
        for name in sorted(ADAPTERS):
            with self.subTest(adapter=name):
                found = cap.capabilities_of(_klass(name))
                self.assertIn("market_data", found)
                self.assertIn("execution", found)

    def test_no_broker_holds_a_time_stop(self):
        """The standing exception, and the reason `asset_engine` must keep
        running one itself forever: a bracket holds the stop and the target,
        and nothing at any venue releases capital from a thesis that simply
        never moved."""
        self.assertNotIn("time_stop", cap.CAPABILITIES)
        src = (Path(settings.BASE_DIR) / "bot_program" / "engine"
               / "capabilities.py").read_text(encoding="utf-8")
        self.assertIn("time stop", src.lower())


class TheGuardIsWiredBeforeTheBrokersArriveTests(SimpleTestCase):
    """Written on purpose before Saxo and eToro, and this says so."""

    def test_the_count_test_is_not_the_only_guard_any_more(self):
        wall = (Path(settings.BASE_DIR) / "tests"
                / "test_wall_facts.py").read_text(encoding="utf-8")
        self.assertIn("len(BROKER_ADAPTERS)", wall,
                      "the count guard was removed; it is still the thing "
                      "that stops a helper module becoming a 'broker'")
        # ...and this file is the one that checks they DO anything.
        self.assertTrue(cap.CAPABILITIES)
        self.assertTrue(cap.ADAPTER_CAPABILITIES)
