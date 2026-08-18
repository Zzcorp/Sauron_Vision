"""Phase 2 — make the first evidence honest before collecting weeks of it.

Three defects that would each have corrupted the track record the promotion
ladder reads:

  1. Paper fills booked zero cost. The AssetBot paper path never reaches
     PaperTrader — the order block sits inside `if not paper:` — so a paper
     entry was recorded at the raw ticker and a paper exit at the raw mark.
     Free on both sides. Paper expectancy was therefore inflated by exactly
     the round trip that `passes_cost_filter` rejects trades for being
     unable to cover.

  2. Nothing recorded WHY a symbol did not trade. Fourteen `return None`
     exits, several silent, so "the market was quiet" and "this bot has
     been structurally incapable of trading since it was created" produced
     the identical observation.

  3. Reconciliation never graded what it closed. Its own docstring claimed
     it did. Every bracket-protected exit — all stock and forex trades,
     because their stops rest at the broker — finalised with a hardcoded
     "manual_close" and a NULL realized_r, so those asset classes could
     contribute nothing to the learning loop however long they ran.

Run with:  python manage.py test tests.test_evidence_honesty
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="eh_u"):
    return User.objects.create_user(username=name, password="x")


def _instrument(symbol="BTCUSD", asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _cfg(user, **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(user=user, asset_class="crypto", name="EH", mode="paper",
                    symbols=["BTCUSD"], capital=Decimal("100000"), enabled=True,
                    entry_score_min=0.6, min_signals_for_entry=1,
                    cool_down_minutes=0)
    defaults.update(kw)
    return AssetBotConfig.objects.create(**defaults)


def _signal(inst, rule="r_chain", direction="bullish", score=0.9):
    from signals.models import Signal
    return Signal.objects.create(
        instrument=inst, signal_type="technical", direction=direction,
        urgency="high", title="t", description="d", rule_name=rule,
        score=score, sub_scores={}, price_at_signal=Decimal("100"),
        suggested_entry=Decimal("100"), is_active=True)


class PaperFillCostTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.inst = _instrument()

    def test_a_buyer_pays_up_and_a_seller_sells_down(self):
        from bot_program.asset_engine.risk_levels import paper_fill_price
        cfg = _cfg(self.user)
        buy = paper_fill_price(cfg, "BTCUSD", 100.0, "BUY")
        sell = paper_fill_price(cfg, "BTCUSD", 100.0, "SELL")
        self.assertGreater(buy, 100.0)
        self.assertLess(sell, 100.0)
        # crypto is 10bps round trip, so 5bps a side
        self.assertAlmostEqual(buy, 100.05, places=6)
        self.assertAlmostEqual(sell, 99.95, places=6)

    def test_the_two_sides_together_cost_one_round_trip(self):
        from bot_program.asset_engine.risk_levels import (
            paper_fill_price, round_trip_cost_fraction,
        )
        cfg = _cfg(self.user)
        rt = round_trip_cost_fraction(cfg, "BTCUSD")
        buy = paper_fill_price(cfg, "BTCUSD", 100.0, "BUY")
        sell = paper_fill_price(cfg, "BTCUSD", 100.0, "SELL")
        self.assertAlmostEqual((buy - sell) / 100.0, rt, places=8)

    def test_a_paper_entry_is_recorded_at_the_filled_price(self):
        from bot_program.asset_engine import make_bot
        from bot_program.models import AssetBotTrade
        _signal(self.inst)
        cfg = _cfg(self.user, name="EH2")
        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "100"})
        client.get_positions = MagicMock(return_value=[])
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            make_bot(cfg).scan_symbol("BTCUSD")
        t = AssetBotTrade.objects.filter(config=cfg).first()
        self.assertIsNotNone(t)
        self.assertGreater(float(t.entry_price), 100.0,
                           "a paper buy still fills at the raw ticker")
        self.assertTrue(t.metadata.get("paper_fill"))
        self.assertAlmostEqual(float(t.metadata["market_price"]), 100.0, places=6)

    def test_a_round_trip_at_an_unchanged_price_loses_money(self):
        """The property that matters. Buy and sell at the same market price
        and a real account is down the spread; before this, paper booked
        exactly zero and the ladder read that as break-even."""
        from bot_program.asset_engine import make_bot
        from bot_program.models import AssetBotTrade
        _signal(self.inst)
        cfg = _cfg(self.user, name="EH3")
        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "100"})
        client.get_positions = MagicMock(return_value=[])
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            bot = make_bot(cfg)
            bot.scan_symbol("BTCUSD")
            t = AssetBotTrade.objects.get(config=cfg)
            bot._close_trade(t, Decimal("100"), client, reason="MANUAL")
        t.refresh_from_db()
        self.assertLess(float(t.pnl), 0.0,
                        "a flat round trip still books no cost")


class SkipReasonTests(TestCase):
    def setUp(self):
        self.user = _user("skip_u")
        self.inst = _instrument()

    def _run(self, cfg, price="100"):
        from bot_program.asset_engine import make_bot
        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": price})
        client.get_positions = MagicMock(return_value=[])
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            return make_bot(cfg).scan_symbol("BTCUSD")

    def test_no_signals_is_recorded_rather_than_silent(self):
        from bot_program.asset_engine import skips
        cfg = _cfg(self.user, name="SK1")
        self._run(cfg)
        cfg.refresh_from_db()
        self.assertEqual(skips.last_by_symbol(cfg)["BTCUSD"]["code"],
                         skips.NO_SIGNALS)

    def test_a_stale_signal_reads_differently_from_no_signal(self):
        """The distinction the operator needs: nothing to trade, versus a
        lifecycle pass that has stopped clearing signals."""
        from bot_program.asset_engine import skips
        from signals.models import Signal
        from datetime import timedelta
        s = _signal(self.inst)
        Signal.objects.filter(pk=s.pk).update(
            created_at=timezone.now() - timedelta(days=90))
        cfg = _cfg(self.user, name="SK2")
        self._run(cfg)
        cfg.refresh_from_db()
        self.assertEqual(skips.last_by_symbol(cfg)["BTCUSD"]["code"],
                         skips.STALE_SIGNALS)

    def test_an_already_open_position_is_recorded(self):
        from bot_program.asset_engine import skips
        _signal(self.inst)
        cfg = _cfg(self.user, name="SK3")
        self._run(cfg)          # opens
        self._run(cfg)          # already open
        cfg.refresh_from_db()
        self.assertEqual(skips.last_by_symbol(cfg)["BTCUSD"]["code"],
                         skips.ALREADY_OPEN)

    def test_a_stage_blocked_rule_is_recorded(self):
        """The stage gate moved upstream: a research rule's signals no
        longer vote at all (they used to reach entry and be stopped
        there), and the recorded reason says exactly why the bot held."""
        from bot_program.asset_engine import skips
        from signals.models_control import RuleControl
        RuleControl.objects.create(rule_name="r_chain",
                                   promotion_stage="research")
        _signal(self.inst)
        cfg = _cfg(self.user, name="SK4")
        self._run(cfg)
        cfg.refresh_from_db()
        note = skips.last_by_symbol(cfg)["BTCUSD"]
        self.assertEqual(note["code"], skips.HOLD)
        self.assertIn("research", note["detail"])

    def test_counters_accumulate_and_diagnose(self):
        from bot_program.asset_engine import skips
        cfg = _cfg(self.user, name="SK5")
        for _ in range(3):
            self._run(cfg)
        cfg.refresh_from_db()
        self.assertEqual(skips.summary(cfg)[skips.NO_SIGNALS], 3)
        self.assertIn("no rule is producing signals", skips.diagnose(cfg))

    def test_a_successful_entry_clears_the_note(self):
        from bot_program.asset_engine import skips
        cfg = _cfg(self.user, name="SK6")
        self._run(cfg)                       # records no_signals
        _signal(self.inst)
        self._run(cfg)                       # trades
        cfg.refresh_from_db()
        self.assertNotIn("BTCUSD", skips.last_by_symbol(cfg))

    def test_recording_never_breaks_a_tick(self):
        from bot_program.asset_engine import skips
        cfg = _cfg(self.user, name="SK7")
        with patch("bot_program.asset_engine.safety._save_extras",
                   side_effect=RuntimeError("db down")):
            skips.record(cfg, "BTCUSD", skips.NO_SIGNALS, "x")  # must not raise


class ReconciliationGradingTests(TestCase):
    """Every bracket-protected exit goes through reconciliation, so a
    reconciliation that does not grade means stock and forex contribute
    nothing to the learning loop, forever."""

    def setUp(self):
        self.user = _user("rec_u")
        self.inst = _instrument("AAPL", "stock")

    def _open_trade(self, cfg):
        from bot_program.models import AssetBotTrade
        return AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            stop_loss=Decimal("98"), take_profit=Decimal("110"),
            status="OPEN", paper=False, rule_name="r1",
            metadata={"initial_stop_loss": 98.0})

    def test_a_reconciled_close_gets_a_real_r_multiple(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        from bot_program.reconcile_asset import _close_as_orphan
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="RC", mode="live",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
        t = self._open_trade(cfg)

        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "104"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            _close_as_orphan(t)

        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertEqual(t.status, "CLOSED")
        self.assertIsNotNone(t.realized_r,
                             "reconciliation still leaves realized_r NULL")
        # entry 100, stop 98 -> 1R = $20 on 10 shares; exit 104 -> +$40 = 2R
        self.assertAlmostEqual(float(t.realized_r), 2.0, places=2)

    def test_the_inferred_exit_price_is_flagged(self):
        """It is a current ticker, not the fill the broker got. A large part
        of the track record would otherwise be estimates presented as
        measurements."""
        from bot_program.models import AssetBotConfig, AssetBotTrade
        from bot_program.reconcile_asset import _close_as_orphan
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="RC2", mode="live",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
        t = self._open_trade(cfg)
        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "104"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            _close_as_orphan(t)
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertTrue(t.metadata.get("exit_price_inferred"))

    def test_the_outcome_is_classified_not_hardcoded(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        from bot_program.reconcile_asset import _close_as_orphan
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="RC3", mode="live",
            symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
        t = self._open_trade(cfg)
        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "111"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            _close_as_orphan(t)
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertEqual(t.outcome, "hit_target")
