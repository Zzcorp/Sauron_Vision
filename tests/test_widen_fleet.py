"""The widened fleet: a catalogue-complete symbol map, keyless forex and
index marks, and the seed_bots starter fleet.

The bot code was never the blocker to trading more than crypto — the data
was. Three gaps closed here: the Yahoo symbol map now speaks the
catalogue's spelling for every index and soft (a wrong mapping returns an
empty frame, indistinguishable from "no history"), forex and index marks
arrive keylessly, and seed_bots creates the paper fleet that consumes them.

Run with:  python manage.py test tests.test_widen_fleet
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase


def _fake_yf(price=100.0):
    fake = MagicMock()
    fake.Ticker.return_value.info = {
        "regularMarketPrice": price,
        "regularMarketChangePercent": 0.5,
        "volume": 1234,
    }
    return fake


def _instrument(symbol, asset_class):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


# ── The symbol map speaks the catalogue's language ──────────────────────

class SymbolMapCompletenessTests(SimpleTestCase):
    """The map used exchange shorthand (SPX, ZCUSD, KCUSD) while the
    catalogue says SPX500, CORNUSD, COFFEEUSD — so an index bot would have
    resolved SPX500 -> Yahoo 'SPX500' -> zero rows, forever, silently."""

    def test_every_catalogue_index_symbol_is_mapped_off_identity(self):
        from instruments.services import INSTRUMENTS_DATA
        from market_data.public_feed import yf_symbol
        for sym in INSTRUMENTS_DATA["index"]:
            self.assertNotEqual(
                yf_symbol(sym, "index"), sym,
                f"{sym} falls through the map unchanged — Yahoo will return "
                f"an empty frame and it will read as 'no history available'")

    def test_every_catalogue_commodity_is_mapped_or_declared_unavailable(self):
        from instruments.services import INSTRUMENTS_DATA
        from market_data.public_feed import YF_UNAVAILABLE, yf_symbol
        for sym in INSTRUMENTS_DATA["commodity"]:
            if sym in YF_UNAVAILABLE:
                continue
            self.assertNotEqual(
                yf_symbol(sym, "commodity"), sym,
                f"{sym} is neither mapped nor declared unavailable — it "
                f"will warn about its symbol mapping on every poll")

    def test_the_unavailable_set_names_only_real_catalogue_symbols(self):
        """A typo in the skip-set would quietly re-expose the symbol it
        meant to cover."""
        from instruments.services import INSTRUMENTS_DATA
        from market_data.public_feed import YF_UNAVAILABLE
        self.assertLessEqual(
            YF_UNAVAILABLE, set(INSTRUMENTS_DATA["commodity"]))

    def test_forex_pairs_resolve_to_yahoo_x_spelling(self):
        from market_data.public_feed import yf_symbol
        self.assertEqual(yf_symbol("EURUSD", "forex"), "EURUSD=X")
        # The rule must hold for the exotics too, not just the majors.
        self.assertEqual(yf_symbol("USDRON", "forex"), "USDRON=X")


# ── Keyless index marks ─────────────────────────────────────────────────

class IndexQuoteTaskTests(TestCase):
    """SPX500 and friends had Instrument rows and no task that ever wrote
    their LiveQuote, so the headband's index strip rendered em-dashes
    forever."""

    def test_index_levels_go_out_in_yahoo_spelling_and_through_the_writer(self):
        inst = _instrument("SPX500", "index")
        fake = _fake_yf(price=7785.76)
        with patch("core.market_calendar.is_any_market_open",
                   return_value=True), \
             patch.dict("sys.modules", {"yfinance": fake}):
            from market_data.tasks import fetch_index_quotes
            result = fetch_index_quotes.__wrapped__.__wrapped__()
        fake.Ticker.assert_any_call("^GSPC")
        self.assertGreaterEqual(result["fetched"], 1)
        from market_data.models import LiveQuote
        quote = LiveQuote.objects.get(instrument=inst)
        self.assertEqual(quote.source, "yfinance")
        self.assertEqual(quote.last, Decimal("7785.76"))

    def test_closed_markets_are_an_intentional_skip(self):
        with patch("core.market_calendar.is_any_market_open",
                   return_value=False):
            from market_data.tasks import fetch_index_quotes
            result = fetch_index_quotes.__wrapped__.__wrapped__()
        self.assertEqual(result["status"], "skipped")

    def test_the_task_is_scheduled_and_its_component_registered(self):
        """A gated task whose component row nobody seeds silently no-ops
        forever — registration is part of the task, not an ops afterthought."""
        from config.celery import app
        entry = app.conf.beat_schedule["fetch-index-live"]
        self.assertEqual(entry["task"], "market_data.tasks.fetch_index_quotes")
        from core.platform_control import DEFAULT_COMPONENTS
        self.assertIn("scraper_indices",
                      {c["key"] for c in DEFAULT_COMPONENTS})


# ── The commodity poller reads the catalogue ────────────────────────────

class CommodityCatalogueTests(TestCase):
    """The old poller hardcoded six symbols, so 26 of the 32 seeded
    commodities could never have a mark."""

    def test_softs_resolve_through_the_shared_map(self):
        inst = _instrument("CORNUSD", "commodity")
        fake = _fake_yf(price=459.0)
        with patch.dict("sys.modules", {"yfinance": fake}):
            from market_data.tasks import fetch_commodity_quotes
            result = fetch_commodity_quotes.__wrapped__.__wrapped__()
        fake.Ticker.assert_any_call("ZC=F")
        self.assertGreaterEqual(result["fetched"], 1)
        from market_data.models import LiveQuote
        self.assertEqual(LiveQuote.objects.get(instrument=inst).source,
                         "yfinance")

    def test_symbols_with_no_free_source_never_generate_a_request(self):
        """ZINC.L looks plausible on Yahoo and returns an LSE equity with
        NaN closes — confident garbage, worse than no data."""
        _instrument("ZINCUSD", "commodity")
        fake = _fake_yf()
        with patch.dict("sys.modules", {"yfinance": fake}):
            from market_data.tasks import fetch_commodity_quotes
            fetch_commodity_quotes.__wrapped__.__wrapped__()
        fake.Ticker.assert_not_called()


# ── NaN is a known Yahoo behaviour, not an edge case ────────────────────

class NaNQuoteResilienceTests(TestCase):
    """Yahoo serves NaN closes for real: an in-progress FX candle keeps a
    null Close that survives yfinance's row cleanup. NaN is truthy, parses
    cleanly into Decimal, and raises InvalidOperation on the first
    comparison — so an unguarded NaN costs the whole task run, not one
    symbol."""

    def test_write_quote_refuses_a_nan_price(self):
        _instrument("EURUSD", "forex")
        from market_data.quotes import write_quote
        self.assertFalse(
            write_quote("EURUSD", last=float("nan"), source="yfinance"))

    def test_a_nan_change_pct_is_not_stored_beside_a_valid_price(self):
        inst = _instrument("EURUSD", "forex")
        from market_data.quotes import write_quote
        self.assertTrue(write_quote("EURUSD", last=1.09,
                                    change_pct=float("nan"),
                                    source="yfinance"))
        from market_data.models import LiveQuote
        self.assertTrue(
            LiveQuote.objects.get(instrument=inst).change_pct.is_finite())

    def test_one_nan_pair_costs_that_pair_not_the_run(self):
        _instrument("AUDUSD", "forex")
        _instrument("EURUSD", "forex")

        def ticker_for(ysym):
            t = MagicMock()
            if ysym == "AUDUSD=X":
                t.info = {"regularMarketPrice": float("nan")}
                t.history.return_value = MagicMock(empty=True)
            else:
                t.info = {"regularMarketPrice": 1.0912,
                          "regularMarketChangePercent": 0.1}
            return t

        fake = MagicMock()
        fake.Ticker.side_effect = ticker_for
        with patch("market_data.adapters.alpha_vantage.API_KEY", ""), \
             patch("core.market_calendar.is_forex_open", return_value=True), \
             patch.dict("sys.modules", {"yfinance": fake}):
            from market_data.tasks import fetch_forex_quotes
            result = fetch_forex_quotes.__wrapped__.__wrapped__()
        self.assertEqual(result["status"], "success")
        self.assertGreaterEqual(result["fetched"], 1)
        from market_data.models import LiveQuote
        self.assertTrue(LiveQuote.objects.filter(
            instrument__symbol="EURUSD").exists())
        self.assertFalse(LiveQuote.objects.filter(
            instrument__symbol="AUDUSD").exists())


# ── Precedence-aware polling ────────────────────────────────────────────

class SourcePrecedencePollingTests(TestCase):
    """A symbol a fresher, higher-priority feed holds must not be polled at
    all: the call is wasted, the write refused, and the run then scores
    'handled N rows and stored none' — a warning earned for having BETTER
    data than the poller provides."""

    def test_an_all_held_universe_is_a_skip_not_a_silent_warning(self):
        inst = _instrument("EURUSD", "forex")
        from market_data.models import LiveQuote
        LiveQuote.objects.create(
            instrument=inst, last=Decimal("1.0910"), source="oanda")
        fake = _fake_yf()
        with patch("market_data.adapters.alpha_vantage.API_KEY", ""), \
             patch("core.market_calendar.is_forex_open", return_value=True), \
             patch.dict("sys.modules", {"yfinance": fake}):
            from market_data.tasks import fetch_forex_quotes
            result = fetch_forex_quotes.__wrapped__.__wrapped__()
        self.assertEqual(result["status"], "skipped")
        fake.Ticker.assert_not_called()
        self.assertEqual(LiveQuote.objects.get(instrument=inst).source,
                         "oanda")


# ── Forex marks stay inside the paper trader's freshness window ─────────

class ForexMarkFreshnessTests(SimpleTestCase):
    def test_the_cadence_beats_the_staleness_cutoff(self):
        """PaperTrader rejects quotes older than 900s; at the old 1800s
        cadence a forex mark was stale for half its life and stop checks
        silently fell back to bar closes."""
        from bot_program.engine.paper_trader import PaperTrader
        from config.celery import app
        self.assertLessEqual(
            app.conf.beat_schedule["fetch-forex-live"]["schedule"],
            PaperTrader.MAX_QUOTE_AGE_SECONDS)


# ── seed_bots: the starter fleet ────────────────────────────────────────

class SeedBotsFleetDefinitionTests(SimpleTestCase):
    def test_every_fleet_symbol_exists_in_the_catalogue(self):
        """An unknown spelling gets zero bars forever AND routes to Binance
        as crypto — a typo here is a bot that can never trade."""
        from bot_program.management.commands.seed_bots import FLEET
        from instruments.services import INSTRUMENTS_DATA
        for asset_class, name, symbols in FLEET:
            for sym in symbols:
                self.assertIn(
                    sym, INSTRUMENTS_DATA[asset_class],
                    f"{name}: {sym} is not a seeded {asset_class} symbol")

    def test_no_fleet_symbol_is_declared_unavailable(self):
        from bot_program.management.commands.seed_bots import FLEET
        from market_data.public_feed import YF_UNAVAILABLE
        for _, name, symbols in FLEET:
            self.assertFalse(
                set(symbols) & YF_UNAVAILABLE,
                f"{name} trades a symbol with no free data source")

    def test_no_jpy_quoted_pair_ships_until_the_sizing_gap_closes(self):
        """ForexBot's risk sizing divides dollar risk by the stop distance
        in quote-currency terms without converting; on a JPY-quoted pair the
        default-risk quantity computes ~10 units, rounds to the nearest 100,
        and sizes to zero — a bot that ticks forever and never trades."""
        from bot_program.management.commands.seed_bots import FLEET
        for _, name, symbols in FLEET:
            for sym in symbols:
                self.assertFalse(
                    sym.endswith("JPY"),
                    f"{name}: {sym} is JPY-quoted and sizes to zero under "
                    f"default risk sizing")


class SeedBotsCommandTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from django.core.management import call_command
        cls.owner = get_user_model().objects.create_superuser(
            username="sb_admin", password="x", email="sb@x.test")
        call_command("seed_instruments", verbosity=0)

    def _run(self, *flags):
        from io import StringIO
        from django.core.management import call_command
        out, err = StringIO(), StringIO()
        call_command("seed_bots", *flags, stdout=out, stderr=err)
        return out.getvalue(), err.getvalue()

    def test_seeds_are_paper_disabled_and_idempotent(self):
        from bot_program.models import AssetBotConfig
        self._run()
        first = AssetBotConfig.objects.count()
        self.assertEqual(first, 6)
        for cfg in AssetBotConfig.objects.all():
            self.assertEqual(cfg.mode, "paper")
            self.assertFalse(cfg.enabled)
            self.assertTrue(cfg.name.startswith("starter_"))
        self._run()
        self.assertEqual(AssetBotConfig.objects.count(), first)

    def test_activate_enables_the_fleet(self):
        from bot_program.models import AssetBotConfig
        self._run("--activate")
        self.assertFalse(
            AssetBotConfig.objects.filter(enabled=False).exists())

    def test_rerun_never_reasserts_enabled_or_extras(self):
        """`enabled` belongs to the operator and `extras` carries the safety
        engine's persisted circuit-breaker state — a seed that re-asserted
        either would disarm a bot or erase a tripped breaker."""
        from bot_program.models import AssetBotConfig
        self._run()
        cfg = AssetBotConfig.objects.get(name="starter_fx_majors")
        cfg.enabled = True
        cfg.extras = {"circuit_tripped_at": "2026-08-15T00:00:00Z"}
        cfg.save()
        self._run()
        cfg.refresh_from_db()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.extras,
                         {"circuit_tripped_at": "2026-08-15T00:00:00Z"})

    def test_reset_spares_any_config_that_has_traded_but_disables_it(self):
        """AssetBotTrade cascades from its config, so deleting a traded
        config would erase the history the grading layer reads. But the
        keep-guard fires precisely when the bot is enabled and ticking —
        keeping it ARMED after the operator asked for the fleet to go would
        mean 'reset' keeps opening positions."""
        from bot_program.models import AssetBotConfig, AssetBotTrade
        self._run()
        traded = AssetBotConfig.objects.get(name="starter_fx_majors")
        traded.enabled = True
        traded.save(update_fields=["enabled"])
        AssetBotTrade.objects.create(
            config=traded, asset_class="forex", symbol="EURUSD", side="BUY",
            qty=Decimal("1000"), entry_price=Decimal("1.09"),
            stop_loss=Decimal("1.08"), take_profit=Decimal("1.11"),
            status="CLOSED", paper=True, rule_name="starter",
            composite_score=0.7, reason="test")
        _, err = self._run("--reset")
        self.assertIn("starter_fx_majors", err)
        traded.refresh_from_db()
        self.assertFalse(traded.enabled,
                         "a kept config must be decommissioned, not armed")
        self.assertEqual(AssetBotConfig.objects.count(), 1)

    def test_reset_never_touches_a_config_a_human_named(self):
        from bot_program.models import AssetBotConfig
        AssetBotConfig.objects.create(
            user=self.owner, asset_class="forex", name="My FX bot",
            mode="paper", symbols=["EURUSD"])
        self._run()
        self._run("--reset")
        self.assertTrue(
            AssetBotConfig.objects.filter(name="My FX bot").exists())

    def test_unknown_symbols_are_left_out_with_a_warning(self):
        from bot_program.models import AssetBotConfig
        from instruments.models import Instrument
        Instrument.objects.filter(symbol="TSLA").delete()
        _, err = self._run()
        self.assertIn("TSLA", err)
        cfg = AssetBotConfig.objects.get(name="starter_megacaps")
        self.assertNotIn("TSLA", cfg.symbols)

    def test_without_a_superuser_the_command_refuses_plainly(self):
        from django.contrib.auth import get_user_model
        from django.core.management import call_command
        from django.core.management.base import CommandError
        get_user_model().objects.filter(is_superuser=True).delete()
        with self.assertRaises(CommandError):
            call_command("seed_bots", verbosity=0)


# ── The map keeps telling the truth ─────────────────────────────────────

class MapWiringTests(SimpleTestCase):
    """The System Map's wiring table is traced, not guessed — so when the
    tracing changes, the table must change in the same commit."""

    def test_the_index_scraper_is_on_the_map(self):
        from dashboard.views_topology import WIRING
        node = WIRING["scraper_indices"]
        self.assertEqual(node["layer"], "ingest")
        self.assertEqual(node["writes"], ["LiveQuote"])

    def test_the_forex_node_no_longer_claims_an_unreachable_write(self):
        from dashboard.views_topology import WIRING
        self.assertEqual(WIRING["scraper_forex"]["writes"], ["LiveQuote"])
        self.assertNotIn("unreachable",
                         WIRING["scraper_forex"].get("note", ""))

    def test_every_headband_symbol_exists_in_the_catalogue(self):
        """A tracked symbol no seeder creates renders the em-dash forever
        and its click 404s — the old list carried exchange shorthand, six
        bond tickers and BNBUSD, none of which have an Instrument row."""
        from core.context_ui import HEADBAND_SYMBOLS
        from instruments.services import INSTRUMENTS_DATA
        catalogue = set()
        for symbols in INSTRUMENTS_DATA.values():
            catalogue.update(symbols)
        for sym in HEADBAND_SYMBOLS:
            self.assertIn(
                sym, catalogue,
                f"the headband tracks {sym}, which no seeder creates")
