"""The setup memory (backtester/proving/memory.py, 2026-10-03): what
followed, the last times this rule fired on this class in this tape.

The operator: "Sauron should truly understand the chart, its history...
so that he can predict more". The honest version is a conditional
expectancy from the proving ground's own simulated trades, kept with each
saved verdict (ProvingTrade). It is information on the ticket, never a
gate, and it says "no memory" for a rule nobody replayed.

Run with:  python manage.py test tests.test_setup_memory
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from backtester.proving import memory as M
from tests.test_proving_ground import synth


def _seed(symbol="MEMUSD", n=4000, seed=5, drift=0.0008):
    from instruments.models import Instrument
    from market_data.models import PriceData
    inst = Instrument.objects.create(symbol=symbol, name=symbol,
                                     asset_class="crypto")
    df = synth(n, seed=seed, drift=drift)
    PriceData.objects.bulk_create([
        PriceData(instrument=inst, timeframe="4h", timestamp=ts,
                  open=Decimal(str(round(r.open, 4))),
                  high=Decimal(str(round(r.high, 4))),
                  low=Decimal(str(round(r.low, 4))),
                  close=Decimal(str(round(r.close, 4))),
                  volume=1, source="test")
        for ts, r in df.iterrows()], batch_size=1000)
    return inst


class TheCaseTests(SimpleTestCase):

    def test_the_live_rules_map_to_their_families(self):
        fam, d = M.rule_case("golden_cross")
        self.assertEqual((fam.key, d), ("ma_cross", "long"))
        fam, d = M.rule_case("macd_bullish_crossover")
        self.assertEqual((fam.key, d), ("macd_cross", "long"))
        self.assertIsNone(M.rule_case("smc_composite"))
        self.assertIsNone(M.rule_case(""))

    def test_an_unreplayed_rule_has_no_memory_never_a_number(self):
        mem = M.memory_for("smc_composite", "BTCUSD", "crypto")
        self.assertFalse(mem["ok"])
        self.assertEqual(mem["words"], "")
        self.assertIn("no family", mem["reason"])


class TheMemoryTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        _seed()

    def test_before_any_saved_run_it_says_so(self):
        mem = M.memory_for("macd_bullish_crossover", "MEMUSD", "crypto")
        self.assertFalse(mem["ok"])
        self.assertIn("no saved verdict", mem["reason"])

    def test_the_run_keeps_its_trades_and_the_memory_reads_them(self):
        from backtester.models_proving import ProvingTrade, ProvingVerdict
        call_command("prove", "rules", "--class", "crypto", "--save",
                     stdout=StringIO())
        v = ProvingVerdict.objects.get(live_rule="macd_bullish_crossover")
        self.assertGreater(ProvingTrade.objects.filter(verdict=v).count(), 10)
        t = ProvingTrade.objects.filter(verdict=v).first()
        self.assertIn(t.regime.split("+")[0], ("trend", "range"))
        self.assertIn(M.regime_now("MEMUSD").split("+")[0], ("trend", "range"))

        mem = M.memory_for("macd_bullish_crossover", "MEMUSD", "crypto")
        self.assertTrue(mem["ok"], mem)
        self.assertGreaterEqual(mem["n"], M.MIN_ANALOGS)
        self.assertLessEqual(mem["n"], M.ANALOGS_N)
        self.assertIn(f"The last {mem['n']} times macd_bullish_crossover "
                      f"fired on crypto", mem["words"])
        self.assertIn("% won", mem["words"])
        self.assertIn("R a trade", mem["words"])
        self.assertIn(f"Verdict {mem['verdict']}", mem["words"])
        # the newest run is the one read
        self.assertEqual(mem["run_id"], v.run_id)

        out = StringIO()
        call_command("prove", "memory", "macd_bullish_crossover", "--class",
                     "crypto", "--symbols", "MEMUSD", stdout=out)
        self.assertIn("macd_bullish_crossover fired on crypto", out.getvalue())

    def test_only_the_newest_runs_keep_their_trades(self):
        from backtester.models_proving import ProvingTrade, ProvingVerdict
        from backtester.proving.run import RUNS_KEPT
        for _ in range(RUNS_KEPT + 2):
            call_command("prove", "rules", "--class", "crypto", "--save",
                         stdout=StringIO())
        runs_with_trades = set(ProvingTrade.objects.values_list(
            "verdict__run_id", flat=True).distinct())
        self.assertEqual(len(runs_with_trades), RUNS_KEPT)
        newest = (ProvingVerdict.objects.order_by("-created_at")
                  .values_list("run_id", flat=True).first())
        self.assertIn(newest, runs_with_trades)

    def test_a_thin_regime_falls_back_to_every_tape_and_says_so(self):
        from backtester.models_proving import ProvingTrade, ProvingVerdict
        call_command("prove", "rules", "--class", "crypto", "--save",
                     stdout=StringIO())
        v = ProvingVerdict.objects.get(live_rule="macd_bullish_crossover")
        # pretend every analog sat in one tape the market is not in now
        ProvingTrade.objects.filter(verdict=v).update(regime="range+hi_vol")
        mem = M.analogs("macd_cross", "long", "crypto", regime="trend")
        self.assertTrue(mem["fell_back"])
        self.assertGreater(mem["n"], 0)


class TheTicketTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("mem_u", password="x")
        _seed()
        call_command("prove", "rules", "--class", "crypto", "--save",
                     stdout=StringIO())

    def test_the_ticket_quotes_the_memory_of_its_signal_s_rule(self):
        from decimal import Decimal as D

        from bot_program.manual_trade import _preview
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        from signals.models import Signal
        inst, _ = Instrument.objects.get_or_create(
            symbol="BTCUSD", defaults={"name": "BTCUSD",
                                       "asset_class": "crypto"})
        LiveQuote.objects.update_or_create(
            instrument=inst, defaults={"last": D("60000"),
                                       "source": "binance_public"})
        sig = Signal.objects.create(
            instrument=inst, signal_type="technical", direction="bullish",
            urgency="high", title="t", description="d",
            rule_name="macd_bullish_crossover", score=0.6, sub_scores={},
            price_at_signal=D("60000"), suggested_entry=D("60000"),
            suggested_stop=D("59100"), suggested_target=D("61800"),
            is_active=True)
        p = _preview(self.user, inst, "BUY", signal=sig)
        self.assertNotIn("error", p)
        mem = p["setup_memory"]
        self.assertTrue(mem["ok"], mem)
        self.assertIn("macd_bullish_crossover fired on crypto", mem["words"])

    def test_an_instrument_view_ticket_has_no_rule_and_no_memory(self):
        from bot_program.manual_trade import _setup_memory
        mem = _setup_memory(None, "BTCUSD", "crypto")
        self.assertFalse(mem["ok"])
        self.assertEqual(mem["words"], "")

    def test_the_popup_renders_it(self):
        from pathlib import Path
        from django.conf import settings
        html = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")
        self.assertIn("p.setup_memory", html)
        self.assertIn("SETUP MEMORY", html)
