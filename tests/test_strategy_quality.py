"""Decision chain + strategy-quality changes.

Covers the two things that decide whether this system can be profitable
at all: that a bot's symbols actually reach the scan (bars -> rules ->
signals -> decision), and that entries/exits are volatility-normalised and
cost-aware rather than fixed-percentage guesses.

Run with:  python manage.py test tests.test_strategy_quality
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="sq_u"):
    return User.objects.create_user(username=name, password="x")


def _instrument(symbol="AAPL", asset_class="stock", watchlist=False):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol,
        defaults={"name": symbol, "asset_class": asset_class,
                  "is_watchlist": watchlist})
    if inst.is_watchlist != watchlist:
        inst.is_watchlist = watchlist
        inst.save(update_fields=["is_watchlist"])
    return inst


def _cfg(user, **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(user=user, asset_class="stock", name="SQ", mode="paper",
                    symbols=["BOTONLY"], capital=Decimal("10000"), enabled=True)
    defaults.update(kw)
    return AssetBotConfig.objects.create(**defaults)


def _bars(inst, n=60, timeframe="4h", start=100.0, step=0.5, spread=2.0):
    from market_data.models import PriceData
    now = timezone.now()
    for i in range(n):
        close = start + i * step
        PriceData.objects.create(
            instrument=inst, timeframe=timeframe,
            timestamp=now - timedelta(hours=4 * (n - i)),
            open=Decimal(str(close - step)),
            high=Decimal(str(close + spread)),
            low=Decimal(str(close - spread)),
            close=Decimal(str(close)), volume=1000, source="test")


def _signal(inst, direction="bullish", score=0.85, rule="r1"):
    from signals.models import Signal
    return Signal.objects.create(
        instrument=inst, signal_type="composite", direction=direction,
        urgency="medium", title=f"{rule} fired", description="d",
        rule_name=rule, score=score, sub_scores={},
        price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
        is_active=True)


# ── the scan universe ───────────────────────────────────────────────────

class ScanUniverseTests(TestCase):
    def setUp(self):
        self.user = _user()

    def test_bot_symbols_are_scanned_even_when_not_watchlisted(self):
        """The bug: the scan only covered the watchlist, so a bot symbol got
        bars but never a Signal — decide() could only ever return HOLD."""
        from signals.universe import scan_universe
        _instrument("BOTONLY", watchlist=False)
        _cfg(self.user, symbols=["BOTONLY"])
        self.assertIn("BOTONLY",
                      set(scan_universe().values_list("symbol", flat=True)))

    def test_watchlist_is_still_included(self):
        from signals.universe import scan_universe
        _instrument("WATCHED", watchlist=True)
        self.assertIn("WATCHED",
                      set(scan_universe().values_list("symbol", flat=True)))

    def test_disabled_bots_do_not_widen_the_universe(self):
        from signals.universe import scan_universe
        _instrument("OFFBOT", watchlist=False)
        _cfg(self.user, symbols=["OFFBOT"], enabled=False, name="OFF")
        self.assertNotIn("OFFBOT",
                         set(scan_universe().values_list("symbol", flat=True)))

    def test_no_duplicates_when_a_bot_symbol_is_also_watchlisted(self):
        from signals.universe import scan_universe
        _instrument("BOTH", watchlist=True)
        _cfg(self.user, symbols=["BOTH"], name="BOTHCFG")
        symbols = list(scan_universe().values_list("symbol", flat=True))
        self.assertEqual(symbols.count("BOTH"), 1)


# ── indicators actually get written ─────────────────────────────────────

class IndicatorTaskTests(TestCase):
    def test_indicators_are_computed_and_persisted(self):
        """Both tasks were stubs returning pending_implementation while beat
        ran them every 15 minutes."""
        from indicators.models import TechnicalIndicator
        from indicators.tasks import recalculate_for_instruments
        inst = _instrument("INDI")
        _bars(inst, n=60)
        _bars(inst, n=60, timeframe="1d")

        out = recalculate_for_instruments([inst])

        self.assertEqual(out["written"], 2)
        row = TechnicalIndicator.objects.get(instrument=inst, timeframe="4h")
        self.assertIsNotNone(row.rsi_14)
        self.assertIsNotNone(row.atr_14)
        self.assertGreater(float(row.atr_14), 0)

    def test_rerun_updates_in_place(self):
        from indicators.models import TechnicalIndicator
        from indicators.tasks import recalculate_for_instruments
        inst = _instrument("INDI2")
        _bars(inst, n=60)
        recalculate_for_instruments([inst], timeframes=("4h",))
        recalculate_for_instruments([inst], timeframes=("4h",))
        self.assertEqual(
            TechnicalIndicator.objects.filter(instrument=inst).count(), 1)

    def test_thin_history_is_skipped_not_crashed(self):
        from indicators.tasks import recalculate_for_instruments
        inst = _instrument("THIN")
        _bars(inst, n=5)
        out = recalculate_for_instruments([inst], timeframes=("4h",))
        self.assertEqual(out["written"], 0)
        self.assertEqual(out["skipped_no_data"], 1)
        self.assertEqual(out["errors"], 0)


# ── ATR-normalised levels ───────────────────────────────────────────────

class AtrLevelTests(TestCase):
    def setUp(self):
        self.user = _user("atr_u")
        self.cfg = _cfg(self.user, symbols=["ATRSYM"])
        self.inst = _instrument("ATRSYM")

    def test_levels_scale_with_volatility_not_a_fixed_percent(self):
        from bot_program.asset_engine.risk_levels import stop_and_target
        _bars(self.inst, n=60, spread=2.0)
        sl, tp, meta = stop_and_target(self.cfg, "ATRSYM", 130.0, "BUY")
        self.assertEqual(meta["levels_source"], "atr")
        # Planned reward:risk follows the ATR multiples (3.0 / 1.5 = 2:1).
        self.assertAlmostEqual((tp - 130.0) / (130.0 - sl), 2.0, places=4)

    def test_short_side_is_mirrored(self):
        from bot_program.asset_engine.risk_levels import stop_and_target
        _bars(self.inst, n=60, spread=2.0)
        sl, tp, _ = stop_and_target(self.cfg, "ATRSYM", 130.0, "SELL")
        self.assertGreater(sl, 130.0)
        self.assertLess(tp, 130.0)

    def test_falls_back_to_config_percentages_without_bars(self):
        from bot_program.asset_engine.risk_levels import stop_and_target
        sl, tp, meta = stop_and_target(self.cfg, "NOBARS", 100.0, "BUY")
        self.assertEqual(meta["levels_source"], "pct")
        self.assertAlmostEqual(sl, 100.0 * (1 - self.cfg.stop_loss_pct / 100))

    def test_absurd_atr_is_rejected_in_favour_of_percentages(self):
        """A spike bar must not produce a 90%-wide stop."""
        from bot_program.asset_engine.risk_levels import stop_and_target
        with patch("bot_program.asset_engine.risk_levels.atr_for",
                    return_value=9999.0):
            _, _, meta = stop_and_target(self.cfg, "ATRSYM", 100.0, "BUY")
        self.assertEqual(meta["levels_source"], "pct")
        self.assertEqual(meta["levels_fallback_reason"], "atr_out_of_band")


# ── cost-aware entry filter ─────────────────────────────────────────────

class CostFilterTests(TestCase):
    def setUp(self):
        self.user = _user("cost_u")

    def test_trade_smaller_than_the_round_trip_is_rejected(self):
        from bot_program.asset_engine.risk_levels import passes_cost_filter
        cfg = _cfg(self.user, asset_class="crypto", name="C1")  # 10bps each way
        ok, reason = passes_cost_filter(cfg, "BTCUSD", 100.0, 100.1)  # 0.1%
        self.assertFalse(ok)
        self.assertIn("round-trip cost", reason)

    def test_trade_with_real_edge_passes(self):
        from bot_program.asset_engine.risk_levels import passes_cost_filter
        cfg = _cfg(self.user, asset_class="stock", name="C2")
        ok, _ = passes_cost_filter(cfg, "AAPL", 100.0, 103.0)
        self.assertTrue(ok)

    def test_filter_can_be_disabled_per_config(self):
        from bot_program.asset_engine.risk_levels import passes_cost_filter
        cfg = _cfg(self.user, asset_class="crypto", name="C3",
                   extras={"use_cost_filter": False})
        ok, _ = passes_cost_filter(cfg, "BTCUSD", 100.0, 100.01)
        self.assertTrue(ok)

    def test_entry_is_skipped_end_to_end_when_cost_dominates(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotTrade
        inst = _instrument("TINY")
        _signal(inst)
        cfg = _cfg(self.user, symbols=["TINY"], name="C4",
                   extras={"use_atr_levels": False})
        cfg.take_profit_pct = 0.02  # 0.02% target vs 5bps round trip
        cfg.save()
        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "100"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            self.assertIsNone(StockBot(cfg).scan_symbol("TINY"))
        self.assertEqual(AssetBotTrade.objects.filter(config=cfg).count(), 0)


# ── evidence-weighted aggregation ───────────────────────────────────────

class WeightedConsensusTests(TestCase):
    def setUp(self):
        self.user = _user("wc_u")
        self.inst = _instrument("WSYM")

    def test_unproven_rules_are_neutral(self):
        from bot_program.asset_engine.aggregation import rule_weight
        self.assertEqual(rule_weight("brand_new_rule", "stock"), 1.0)

    def test_a_proven_rule_outweighs_an_unproven_opponent(self):
        from bot_program.asset_engine.aggregation import weighted_consensus
        bull = [_signal(self.inst, "bullish", 0.7, "good_rule")]
        bear = [_signal(self.inst, "bearish", 0.7, "unproven")]
        with patch("bot_program.asset_engine.aggregation.rule_weight",
                    side_effect=lambda r, a="", **kw: 1.8 if r == "good_rule" else 1.0):
            verdict = weighted_consensus(bull, bear, asset_class="stock",
                                          min_net_weight=0.5)
        self.assertEqual(verdict["direction"], "BUY")
        self.assertEqual(verdict["rule_name"], "good_rule")

    def test_balanced_evidence_holds(self):
        from bot_program.asset_engine.aggregation import weighted_consensus
        bull = [_signal(self.inst, "bullish", 0.8, "a")]
        bear = [_signal(self.inst, "bearish", 0.8, "b")]
        verdict = weighted_consensus(bull, bear, min_net_weight=0.6)
        self.assertEqual(verdict["direction"], "HOLD")

    def test_a_single_strong_signal_still_trades(self):
        """The weighted path must not be stricter than the headcount rule it
        replaces: min_signals_for_entry=1 at entry_score_min=0.6 means one
        0.85 signal is enough."""
        from bot_program.asset_engine.base import AssetBot
        from bot_program.asset_engine.stock_bot import StockBot
        cfg = _cfg(self.user, symbols=["WSYM"], name="W1")
        _signal(self.inst, "bullish", 0.85, "solo")
        decision = StockBot(cfg).decide("WSYM")
        self.assertEqual(decision.direction, "BUY")

    def test_opt_out_restores_headcount_behaviour(self):
        from bot_program.asset_engine.stock_bot import StockBot
        cfg = _cfg(self.user, symbols=["WSYM"], name="W2",
                   extras={"use_weighted_consensus": False})
        _signal(self.inst, "bullish", 0.85, "solo")
        self.assertEqual(StockBot(cfg).decide("WSYM").direction, "BUY")


# ── exit management ─────────────────────────────────────────────────────

class ExitManagementTests(TestCase):
    def setUp(self):
        self.user = _user("ex_u")
        self.inst = _instrument("EXSYM")

    def _trade(self, cfg, **kw):
        from bot_program.models import AssetBotTrade
        defaults = dict(
            config=cfg, asset_class="stock", symbol="EXSYM", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            stop_loss=Decimal("98"), take_profit=Decimal("110"),
            status="OPEN", paper=True)
        defaults.update(kw)
        return AssetBotTrade.objects.create(**defaults)

    def test_trailing_stop_ratchets_up_in_profit(self):
        from bot_program.asset_engine.stock_bot import StockBot
        cfg = _cfg(self.user, symbols=["EXSYM"], name="T1",
                   extras={"trail_pct": 2.0})
        trade = self._trade(cfg)
        StockBot(cfg)._update_trailing_stop(trade, Decimal("106"))
        trade.refresh_from_db()
        self.assertGreater(trade.stop_loss, Decimal("98"))

    def test_trailing_stop_does_not_move_on_a_losing_trade(self):
        from bot_program.asset_engine.stock_bot import StockBot
        cfg = _cfg(self.user, symbols=["EXSYM"], name="T2",
                   extras={"trail_pct": 2.0})
        trade = self._trade(cfg)
        StockBot(cfg)._update_trailing_stop(trade, Decimal("97"))
        trade.refresh_from_db()
        self.assertEqual(trade.stop_loss, Decimal("98"))

    def test_trailing_is_skipped_for_broker_protected_trades(self):
        """Moving only our copy would desynchronise it from the resting
        broker-side stop."""
        from bot_program.asset_engine.stock_bot import StockBot
        cfg = _cfg(self.user, symbols=["EXSYM"], name="T3",
                   extras={"trail_pct": 2.0})
        trade = self._trade(cfg, metadata={"protected": True})
        self.assertFalse(
            StockBot(cfg)._update_trailing_stop(trade, Decimal("106")))

    def test_time_stop_closes_a_stale_position(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotTrade
        cfg = _cfg(self.user, symbols=["EXSYM"], name="T4",
                   extras={"max_hold_hours": 24})
        trade = self._trade(cfg)
        AssetBotTrade.objects.filter(pk=trade.pk).update(
            opened_at=timezone.now() - timedelta(hours=48))
        trade.refresh_from_db()

        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "101"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                    return_value=client):
            closed = StockBot(cfg).manage_positions()

        self.assertEqual(closed, 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertIn("TIME", trade.reason)

    def test_time_stop_leaves_a_fresh_position_alone(self):
        from bot_program.asset_engine.stock_bot import StockBot
        cfg = _cfg(self.user, symbols=["EXSYM"], name="T5",
                   extras={"max_hold_hours": 24})
        trade = self._trade(cfg)
        self.assertFalse(StockBot(cfg)._time_stop_hit(trade))
