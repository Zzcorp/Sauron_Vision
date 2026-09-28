"""The research fleet: paper bots across the whole keyless catalogue.

The learning engine grades what the fleet does, and by 2026-09-11 the
fleet was six starter configs on 35 symbols plus three live pools on a
500 EUR account: fourteen trades a week for a ladder whose first rung
wants thirty graded signals per rule. The catalogue held 179 instruments
with keyless bars for most of them. This command puts them to work in
paper, chunked so the fill rate scales with the universe, within a budget
the bar refresh can afford.

Run with:  python manage.py test tests.test_research_fleet
"""
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase


def _instruments(spec):
    """spec: {asset_class: [symbols]} -> rows, all active."""
    from instruments.models import Instrument
    for asset_class, symbols in spec.items():
        for s in symbols:
            Instrument.objects.get_or_create(
                symbol=s, defaults={"name": s, "asset_class": asset_class,
                                    "is_active": True})


def _run(*args):
    out = StringIO()
    call_command("seed_research_fleet", *args, stdout=out)
    return out.getvalue()


class TheUniverseTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("rf", password="x",
                                             is_superuser=True)

    def test_etfs_trade_under_the_stock_bot_and_indices_do_not(self):
        from bot_program.management.commands.seed_research_fleet import (
            research_universe)
        _instruments({"stock": ["AAPL"], "etf": ["GLDM"], "index": ["SPX"],
                      "options": ["SPY-OPT"], "forex": ["EURUSD"]})
        u = research_universe(self.user)
        self.assertEqual(u["stock"], ["AAPL", "GLDM"])
        self.assertEqual(u["forex"], ["EURUSD"])
        self.assertNotIn("index", u)
        self.assertNotIn("options", u)

    def test_symbols_the_keyless_feed_cannot_serve_are_skipped_by_name(self):
        from bot_program.management.commands.seed_research_fleet import (
            research_universe)
        _instruments({"commodity": ["XAUUSD", "ZINCUSD", "XAUEUR"]})
        self.assertEqual(research_universe(self.user)["commodity"],
                         ["XAUUSD"])

    def test_a_symbol_another_enabled_config_trades_is_not_doubled(self):
        from bot_program.management.commands.seed_research_fleet import (
            research_universe)
        from bot_program.models import AssetBotConfig
        _instruments({"stock": ["AAPL", "MSFT"]})
        AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="starter_megacaps",
            mode="live", symbols=["AAPL"], capital=Decimal("150"),
            enabled=True)
        AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="old_paper",
            mode="paper", symbols=["MSFT"], capital=Decimal("1"),
            enabled=False)                     # disabled: not covering
        self.assertEqual(research_universe(self.user)["stock"], ["MSFT"])

    def test_the_budget_binds_round_robin_across_classes(self):
        from bot_program.management.commands.seed_research_fleet import (
            research_universe)
        _instruments({"stock": [f"S{i}" for i in range(10)],
                      "forex": ["EURUSD", "GBPUSD"],
                      "crypto": ["BTCUSD"]})
        u = research_universe(self.user, budget=6)
        self.assertEqual(sum(len(v) for v in u.values()), 6)
        self.assertEqual(u["crypto"], ["BTCUSD"])
        self.assertEqual(u["forex"], ["EURUSD", "GBPUSD"])
        self.assertEqual(len(u["stock"]), 3)


class TheFleetIsSeededTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("rf2", password="x",
                                             is_superuser=True)
        _instruments({"stock": [f"S{i:02d}" for i in range(23)],
                      "forex": ["EURUSD", "GBPUSD", "USDJPY"]})

    def _configs(self):
        from bot_program.models import AssetBotConfig
        return {c.name: c for c in AssetBotConfig.objects.filter(
            user=self.user, name__startswith="research_")}

    def test_it_chunks_enables_and_marks_what_it_made(self):
        out = _run("--chunk", "10")
        cfgs = self._configs()
        self.assertEqual(sorted(cfgs), ["research_forex_1", "research_stock_1",
                                        "research_stock_2", "research_stock_3"])
        s1 = cfgs["research_stock_1"]
        self.assertEqual(len(s1.symbols), 10)
        self.assertEqual(len(cfgs["research_stock_3"].symbols), 3)
        self.assertEqual(s1.mode, "paper")
        self.assertTrue(s1.enabled)
        self.assertEqual(float(s1.capital), 100000.0)
        self.assertTrue(s1.extras.get("research_fleet"))
        self.assertIn("4 config(s), 26 symbols", out)
        self.assertIn("~26 keyless downloads", out)

    def test_dry_run_writes_nothing_and_disabled_seeds_off(self):
        out = _run("--dry-run")
        self.assertEqual(self._configs(), {})
        self.assertIn("would seed", out)
        _run("--disabled")
        self.assertFalse(any(c.enabled for c in self._configs().values()))

    def test_a_rerun_refreshes_symbols_and_nothing_else(self):
        _run("--chunk", "10")
        cfg = self._configs()["research_stock_1"]
        cfg.enabled = False
        cfg.capital = Decimal("5")
        cfg.extras = {"research_fleet": True, "circuit": "tripped"}
        cfg.save()
        _instruments({"stock": ["ZZZZ"]})           # the universe grew
        _run("--chunk", "10")
        cfg.refresh_from_db()
        self.assertFalse(cfg.enabled)               # the operator's
        self.assertEqual(float(cfg.capital), 5.0)   # tuned by hand
        self.assertEqual(cfg.extras.get("circuit"), "tripped")
        names = self._configs()
        self.assertIn("ZZZZ", names["research_stock_3"].symbols)

    def test_a_promoted_research_config_is_left_alone(self):
        _run("--chunk", "10")
        cfg = self._configs()["research_stock_1"]
        cfg.mode = "live"
        cfg.symbols = ["S00"]
        cfg.save()
        out = _run("--chunk", "10")
        cfg.refresh_from_db()
        self.assertEqual(cfg.symbols, ["S00"])
        self.assertIn("promoted to live", out)

    def test_a_config_wearing_the_name_without_the_mark_is_never_touched(self):
        from bot_program.models import AssetBotConfig
        mine = AssetBotConfig.objects.create(
            user=self.user, asset_class="forex", name="research_forex_1",
            mode="paper", symbols=["USDCHF"], capital=Decimal("1"),
            enabled=True)
        out = _run()
        mine.refresh_from_db()
        self.assertEqual(mine.symbols, ["USDCHF"])
        self.assertIn("not seeded by this command", out)

    def test_reset_removes_what_it_seeded_and_only_that(self):
        from bot_program.models import AssetBotConfig
        _run()
        AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="starter_megacaps",
            mode="paper", symbols=["AAPL"], capital=Decimal("1"))
        _run("--reset")
        self.assertEqual(self._configs(), {})
        self.assertTrue(AssetBotConfig.objects.filter(
            name="starter_megacaps").exists())

    def test_a_stale_research_config_stands_down_when_the_plan_shrinks(self):
        _run("--chunk", "10")
        self.assertIn("research_stock_3", self._configs())
        _run("--chunk", "10", "--budget", "12")
        cfgs = self._configs()
        self.assertNotIn("research_stock_3", cfgs)
        self.assertIn("research_stock_1", cfgs)
