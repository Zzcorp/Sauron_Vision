"""A symbol with no bars is not a losing trade (2026-09-14).

`_simulate_exit` returned `(None, 0.0, "expired")` when the bar feed carried
nothing after a signal, and `run_backtest` priced that 0.0 as a fill:

    r = (0.0 - 100) / |100 - 98| = -50

booked as a completed, *expired* trade. `exit_time` was None, so neither the
one-position-per-symbol guard nor the cooldown was ever armed for that
symbol — every later signal on it booked another -50. One symbol the feed had
never carried could bury an entire run.

This platform carries 159 symbols and a bar feed that has gone dark for
fourteen hours at a stretch. It has also just been established that not one
symbol's bars come from IBKR. So the input that triggers this is not exotic;
it is the normal state of several symbols on any given day.

WHY THE OLD TEST DID NOT CATCH IT

`test_no_bars_returns_expired` asserted `outcome == "expired"` and
`exit_time is None`. Both were true. The test was written from the
implementation, so it described the bug accurately and held it in place —
the fourth time that shape has turned up in this repository.

WHAT THIS FILE DOES INSTEAD

It never asserts a number the engine chose. The central test runs the SAME
backtest twice, once with a ghost symbol added, and demands that every
statistic come back byte-identical. An input carrying no information may not
change a single output. That invariant cannot be satisfied by a bug, and it
cannot be written into agreement with one, because both sides of the
comparison are produced by the engine itself.
"""
import re
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase

ENGINE = Path(settings.BASE_DIR) / "bot_program" / "backtest_asset.py"
DETAIL = (Path(settings.BASE_DIR) / "templates" / "dashboard"
          / "bot_backtest_detail.html")

START = datetime(2026, 4, 1, 0, 0, tzinfo=dt_tz.utc)
END = datetime(2026, 4, 30, 23, 0, tzinfo=dt_tz.utc)


def _instrument(symbol):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": "stock"})
    return inst


#: (user, asset_class, name) is unique on AssetBotConfig, and several tests
#: below build two configs to compare one run against another.
_seq = iter(range(1, 10_000))


def _config(user, symbols, **kw):
    from bot_program.models import AssetBotConfig
    fields = dict(
        name=f"T{next(_seq)}",
        enabled=True, mode="paper", symbols=symbols,
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=2.0, take_profit_pct=4.0,
        entry_score_min=0.6, min_signals_for_entry=1,
        timeframe="1h", cool_down_minutes=0,
    )
    fields.update(kw)
    return AssetBotConfig.objects.create(
        user=user, asset_class="stock", **fields)


def _signal(instrument, ts, price=100, score=0.85):
    from signals.models import Signal
    sig = Signal.objects.create(
        instrument=instrument, signal_type="composite", direction="bullish",
        urgency="medium", title="t", description="t", rule_name="r1",
        score=score, sub_scores={},
        price_at_signal=Decimal(str(price)),
        suggested_entry=Decimal(str(price)))
    Signal.objects.filter(pk=sig.pk).update(created_at=ts)
    return sig


def _bar(instrument, ts, o, h, low, c):
    from market_data.models import PriceData
    return PriceData.objects.create(
        instrument=instrument, timeframe="1h", timestamp=ts,
        open=Decimal(str(o)), high=Decimal(str(h)), low=Decimal(str(low)),
        close=Decimal(str(c)), volume=0, source="test")


def _run(config, **kw):
    from bot_program.backtest_asset import BacktestParams, run_backtest
    return run_backtest(BacktestParams(
        config_id=config.id, start=START, end=END, **kw))


class AGhostSymbolMayNotMoveASingleNumberTests(TestCase):
    """The central invariant. Nothing here hard-codes an expected statistic."""

    def setUp(self):
        self.user = User.objects.create_user("ghost_u", password="x")
        self.real = _instrument("AAPL")
        self.ghost = _instrument("GHOSTUSD")

        # One measurable trade: signal at +1h, target hit at +2h.
        sig_at = START + timedelta(hours=1)
        _signal(self.real, sig_at)
        _bar(self.real, sig_at + timedelta(hours=1), 100, 104.5, 99.5, 104)

        # Three signals on a symbol the feed has never carried. No bars.
        for hours in (3, 10, 20):
            _signal(self.ghost, START + timedelta(hours=hours))

    def test_the_statistics_are_identical_with_and_without_it(self):
        with_ghost = _run(_config(self.user, ["AAPL", "GHOSTUSD"]))
        without = _run(_config(self.user, ["AAPL"]))
        self.assertEqual(
            with_ghost.stats, without.stats,
            "adding a symbol whose bars do not exist changed the measured "
            "statistics; an input that carries no information may not move "
            "a single output")

    def test_it_produces_no_trade(self):
        result = _run(_config(self.user, ["AAPL", "GHOSTUSD"]))
        self.assertEqual([t.symbol for t in result.trades], ["AAPL"])

    def test_the_dropped_signals_are_counted_not_discarded(self):
        """Silently dropping them would be the quieter version of the same
        lie: a run that measured one signal out of four, reported as though
        it had measured everything."""
        result = _run(_config(self.user, ["AAPL", "GHOSTUSD"]))
        self.assertEqual(result.unmeasured["signals_without_bars"], 3)
        self.assertEqual(result.unmeasured["by_symbol"], {"GHOSTUSD": 3})

    def test_the_count_matches_an_independent_query(self):
        """Counted from the database rather than from the engine's own
        bookkeeping, so the two sides cannot drift into agreement."""
        from market_data.models import PriceData
        from signals.models import Signal
        cfg = _config(self.user, ["AAPL", "GHOSTUSD"])
        expected = 0
        for sig in Signal.objects.filter(score__gte=cfg.entry_score_min):
            if not PriceData.objects.filter(
                    instrument=sig.instrument, timeframe=cfg.timeframe,
                    timestamp__gt=sig.created_at).exists():
                expected += 1
        self.assertEqual(_run(cfg).unmeasured["signals_without_bars"],
                         expected)

    def test_the_old_defect_by_its_magnitude(self):
        """Pinned by the number it produced, because that number is what
        anyone reading a backtest would have had to explain away. A 2% stop
        turned a missing bar into -50 R; three of them into -150."""
        result = _run(_config(self.user, ["AAPL", "GHOSTUSD"]))
        self.assertGreater(result.stats["total_r"], 0,
                           "a run with one winning trade and three unmeasured "
                           "signals came back negative")
        for trade in result.trades:
            self.assertGreater(
                trade.realized_r, -2.0,
                f"{trade.symbol} booked {trade.realized_r} R — a loss larger "
                f"than the stop it was given, which only happens when an "
                f"absent price was treated as a fill")

    def test_a_run_where_everything_is_unmeasured_says_so(self):
        from bot_program.backtest_asset import _empty_stats
        result = _run(_config(self.user, ["GHOSTUSD"]))
        self.assertEqual(result.trades, [])
        self.assertEqual(result.stats, _empty_stats())
        self.assertEqual(result.unmeasured["signals_without_bars"], 3)

    def test_zero_dropped_is_still_reported(self):
        """An absent key and a measured zero are different answers, and the
        page renders them identically unless the key is always there."""
        result = _run(_config(self.user, ["AAPL"]))
        self.assertEqual(result.unmeasured["signals_without_bars"], 0)
        self.assertEqual(result.unmeasured["by_symbol"], {})

    def test_slippage_does_not_resurrect_the_absent_price(self):
        """The bug lived in the arithmetic that followed the simulation, not
        in the simulation. With slippage on, a None price multiplied by a
        factor raises — or, as it did before, becomes a plausible number."""
        result = _run(_config(self.user, ["AAPL", "GHOSTUSD"]),
                      slippage_pct=0.5, transaction_cost_pct=0.10)
        self.assertEqual(len(result.trades), 1)
        self.assertEqual(result.unmeasured["signals_without_bars"], 3)


class TheGuardSitsBeforeTheArithmeticTests(SimpleTestCase):
    """Read out of the source, because the ordering IS the fix."""

    def setUp(self):
        self.src = ENGINE.read_text(encoding="utf-8")

    def test_the_no_data_branch_precedes_the_exit_pricing(self):
        guard = "if outcome == NO_DATA or raw_exit_price is None:"
        pricing = "exit_price = raw_exit_price * (1 - slip)"
        self.assertIn(guard, self.src)
        self.assertIn(pricing, self.src)
        self.assertLess(
            self.src.index(guard), self.src.index(pricing),
            "the absent-price guard moved below the arithmetic that prices "
            "an exit; a None or a 0.0 will be multiplied by a slippage "
            "factor and booked as a fill again")

    def test_the_simulator_never_returns_a_zero_price(self):
        """`return None, 0.0, ...` is the exact shape of the defect: a
        sentinel that is also a valid number."""
        self.assertNotIn("return None, 0.0", self.src)

    def test_no_data_is_absent_from_the_outcomes_that_are_trades(self):
        from bot_program.backtest_asset import NO_DATA, OUTCOMES
        self.assertNotIn(NO_DATA, OUTCOMES)


class TheStatsCarryEveryOutcomeTests(SimpleTestCase):
    """A bucket the engine can fill and `stats` cannot name renders as a
    blank on the detail page, which reads as zero."""

    def test_compute_stats_seeds_all_of_them(self):
        from bot_program.backtest_asset import OUTCOMES, compute_stats

        class _T:
            outcome = "hit_target"
            realized_r = 1.0

        self.assertEqual(set(compute_stats([_T()])["by_outcome"]),
                         set(OUTCOMES))

    def test_empty_stats_seeds_all_of_them(self):
        from bot_program.backtest_asset import OUTCOMES, _empty_stats
        self.assertEqual(set(_empty_stats()["by_outcome"]), set(OUTCOMES))

    def test_both_shapes_agree(self):
        """The two dicts are written in two places and read as one."""
        from bot_program.backtest_asset import _empty_stats, compute_stats

        class _T:
            outcome = "expired"
            realized_r = 0.0

        self.assertEqual(set(compute_stats([_T()])), set(_empty_stats()))


class TheDetailPageNamesEveryOutcomeTests(SimpleTestCase):
    """Same posture as tests/test_backtest_stat_keys.py: the page and the
    engine are read separately and compared, rather than either being
    trusted."""

    def test_every_outcome_the_engine_can_produce_appears_on_the_page(self):
        from bot_program.backtest_asset import OUTCOMES
        page = DETAIL.read_text(encoding="utf-8")
        named = set(re.findall(r"by_outcome\.([a-z_]+)", page))
        missing = set(OUTCOMES) - named
        self.assertEqual(
            missing, set(),
            f"the engine can report {sorted(missing)} and the page has no row "
            f"for it — the count would simply not be displayed, which reads "
            f"as zero")

    def test_the_page_shows_what_it_could_not_measure(self):
        page = DETAIL.read_text(encoding="utf-8")
        self.assertIn("unmeasured.signals_without_bars", page)
        self.assertIn("unmeasured.by_symbol", page)


class TheRunPersistsWhatItCouldNotMeasureTests(TestCase):
    """A count that lives only in memory is a count nobody reads."""

    def setUp(self):
        self.user = User.objects.create_user("ghost_v", password="x")
        self.client = Client()
        self.client.force_login(self.user)

    def test_the_view_writes_it_into_the_stats_json(self):
        from bot_program.models import BotBacktestRun
        _instrument("AAPL")
        ghost = _instrument("GHOSTUSD")
        cfg = _config(self.user, ["AAPL", "GHOSTUSD"])
        _signal(ghost, datetime(2026, 4, 5, 10, 0, tzinfo=dt_tz.utc))

        response = self.client.post("/bot-backtest/run/", {
            "config_id": cfg.id, "start": "2026-04-01", "end": "2026-04-30",
        }, follow=True)
        self.assertEqual(response.status_code, 200)

        run = BotBacktestRun.objects.filter(user=self.user).first()
        self.assertIsNotNone(run)
        self.assertEqual(run.status, "complete", run.error)
        self.assertEqual(run.stats["unmeasured"]["signals_without_bars"], 1)
        self.assertEqual(run.stats["unmeasured"]["by_symbol"],
                         {"GHOSTUSD": 1})

    def test_the_oculus_separates_the_runs_that_predate_the_fix(self):
        """A run stored by the old engine may carry a -50 R phantom and knows
        nothing of the time stop. Displayed beside the new ones without a
        word, it reads as a comparable measurement. The absence of the
        `unmeasured` key is the marker, and it is reliable because the key is
        written unconditionally — zero included."""
        from bot_program.models import BotBacktestRun
        from dashboard.oculus import oculus

        BotBacktestRun.objects.create(
            user=self.user, config_name_snapshot="old",
            asset_class_snapshot="stock", status="complete", trades_json=[],
            stats={"n": 3, "total_r": -148.0})          # no `unmeasured` key
        BotBacktestRun.objects.create(
            user=self.user, config_name_snapshot="new",
            asset_class_snapshot="stock", status="complete", trades_json=[],
            stats={"n": 1, "total_r": 2.0,
                   "unmeasured": {"signals_without_bars": 4,
                                  "by_symbol": {"GHOSTUSD": 4}}})

        cycle = next(c for c in oculus()["cycles"] if c["key"] == "backtests")
        facts = {f["label"]: f["value"] for f in cycle["facts"]}
        stale = next(v for k, v in facts.items() if "before the 09-14 fix" in k)
        dropped = next(v for k, v in facts.items() if "could not simulate" in k)
        self.assertEqual(stale, 1)
        self.assertEqual(dropped, 4)

    def test_the_detail_page_renders_the_symbol_it_could_not_price(self):
        from bot_program.models import BotBacktestRun
        run = BotBacktestRun.objects.create(
            user=self.user, config_name_snapshot="X",
            asset_class_snapshot="stock", status="complete", trades_json=[],
            stats={"n": 0, "by_outcome": {},
                   "unmeasured": {"signals_without_bars": 7,
                                  "by_symbol": {"GHOSTUSD": 7}}})
        body = self.client.get(f"/bot-backtest/{run.id}/").content.decode()
        self.assertIn("GHOSTUSD", body)
        self.assertIn("7", body)
