"""Regressions for the strategy-arc review findings.

Each test here pins a defect that was live in the strategy arc and that
no existing test caught. They share a theme: the code did the right thing
in the case anyone would try by hand, and the wrong thing in the case that
actually runs in production.

Run with:  python manage.py test tests.test_strategy_review_fixes
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="srf_u"):
    return User.objects.create_user(username=name, password="x")


def _instrument(symbol, asset_class="stock", watchlist=False):
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
    defaults = dict(user=user, asset_class="stock", name="SRF", mode="paper",
                    symbols=["AAA"], capital=Decimal("10000"), enabled=True,
                    entry_score_min=0.6, min_signals_for_entry=1)
    defaults.update(kw)
    return AssetBotConfig.objects.create(**defaults)


def _trade(cfg, **kw):
    from bot_program.models import AssetBotTrade
    defaults = dict(config=cfg, asset_class=cfg.asset_class, symbol="AAA",
                    side="BUY", qty=Decimal("10"), entry_price=Decimal("100"),
                    stop_loss=Decimal("98"), take_profit=Decimal("110"),
                    status="OPEN", paper=True, rule_name="r1")
    # opened_at is auto_now_add, so create() silently ignores it — an age
    # has to be written back through the queryset or every trade in these
    # tests is two seconds old and no time stop can ever fire.
    opened_at = kw.pop("opened_at", None)
    defaults.update(kw)
    t = AssetBotTrade.objects.create(**defaults)
    if opened_at is not None:
        AssetBotTrade.objects.filter(pk=t.pk).update(opened_at=opened_at)
        t.refresh_from_db()
    return t


def _signal(inst, direction="bullish", score=0.85, rule="r1"):
    from signals.models import Signal
    return Signal.objects.create(
        instrument=inst, signal_type="composite", direction=direction,
        urgency="medium", title="t", description="t", rule_name=rule,
        score=score, sub_scores={}, price_at_signal=Decimal("100"),
        suggested_entry=Decimal("100"), is_active=True)


# ── 1. R-multiples must be measured against the stop we actually took ────

class RiskDenominatorTests(TestCase):
    """A trailing stop rewrites trade.stop_loss. Grading read that mutated
    value as the *initial* risk, so pnl and risk became the same quantity
    and every trailing exit graded ~1.0R regardless of the real multiple.

    That number is not cosmetic: bot_trade_track_record feeds it back into
    the entry weight and the meta-allocator's sizing, so a system that
    trailed its winners would teach itself that every rule returns exactly
    1R and lose the ability to tell a good rule from a bad one."""

    def setUp(self):
        self.user = _user()
        self.cfg = _cfg(self.user)

    def _closed(self, *, initial_stop, final_stop, exit_price):
        from bot_program.models import AssetBotTrade
        t = _trade(self.cfg, status="CLOSED",
                   stop_loss=Decimal(str(final_stop)),
                   exit_price=Decimal(str(exit_price)),
                   pnl=Decimal(str((exit_price - 100) * 10)),
                   closed_at=timezone.now(),
                   opened_at=timezone.now() - timedelta(hours=3))
        if initial_stop is not None:
            t.metadata = {"initial_stop_loss": initial_stop}
            t.save(update_fields=["metadata"])
        return AssetBotTrade.objects.get(pk=t.pk)

    def test_trailed_exit_grades_against_the_initial_stop(self):
        from bot_program.bot_grading import grade_bot_trade
        # entry 100, stop 98 (risk 2/unit), trailed to 106.8, exit 106.8.
        t = self._closed(initial_stop=98.0, final_stop=106.8, exit_price=106.8)
        grade_bot_trade(t)
        # True R = 6.8 / 2 = 3.4. Reading the trailed stop gives ~1.0.
        self.assertAlmostEqual(float(t.realized_r), 3.4, places=2)

    def test_untrailed_trade_is_unaffected(self):
        from bot_program.bot_grading import grade_bot_trade
        t = self._closed(initial_stop=98.0, final_stop=98.0, exit_price=104.0)
        grade_bot_trade(t)
        self.assertAlmostEqual(float(t.realized_r), 2.0, places=2)

    def test_legacy_trade_without_the_field_still_grades(self):
        """Rows written before the field existed must not start returning
        None — they fall back to the stop they have."""
        from bot_program.bot_grading import grade_bot_trade
        t = self._closed(initial_stop=None, final_stop=98.0, exit_price=104.0)
        grade_bot_trade(t)
        self.assertAlmostEqual(float(t.realized_r), 2.0, places=2)

    def test_corrupt_field_falls_back_rather_than_raising(self):
        from bot_program.bot_grading import grade_bot_trade
        t = self._closed(initial_stop="not-a-number", final_stop=98.0,
                         exit_price=104.0)
        self.assertTrue(grade_bot_trade(t))
        self.assertAlmostEqual(float(t.realized_r), 2.0, places=2)

    def test_entry_records_the_stop_it_opened_with(self):
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        inst = _instrument("AAA")
        _signal(inst, score=0.9)
        cfg = _cfg(self.user, name="ENTRY")
        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "100"})
        client.get_positions = MagicMock(return_value=[])
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            StockBot(cfg).scan_symbol("AAA")
        t = AssetBotTrade.objects.filter(config=cfg).first()
        self.assertIsNotNone(t)
        self.assertIn("initial_stop_loss", t.metadata or {})
        self.assertAlmostEqual(float(t.metadata["initial_stop_loss"]),
                               float(t.stop_loss), places=4)


class OptionsRiskDenominatorTests(TestCase):
    """The options bot builds its own metadata dict rather than reusing the
    base entry_meta, so the initial-stop fix skipped it entirely — and
    options are where the fix matters most, because a 30% premium stop with
    a trail attached is exactly the shape that grades every winner as 1R."""

    def setUp(self):
        self.user = _user("oi_u")

    def _contract(self, inst):
        from bot_program.options_models import OptionContract
        return OptionContract.objects.create(
            underlying=inst, symbol="SPY  C00500000",
            strike=Decimal("500"),
            expiry=(timezone.now() + timedelta(days=30)).date(),
            right="C", multiplier=100, delta=0.40, iv=0.25,
            bid=Decimal("1.95"), ask=Decimal("2.05"),
            last_price=Decimal("2.00"))

    def test_options_entry_records_the_stop_it_opened_with(self):
        from bot_program.asset_engine.options_bot import OptionsBot
        from bot_program.asset_engine.base import BotDecision
        from bot_program.models import AssetBotTrade
        inst = _instrument("SPY")
        contract = self._contract(inst)
        # One contract risks |2.00 - 1.30| x 100 = $70. At the default 0.25%
        # risk budget that needs $28,000 of equity before a single contract
        # is affordable — arithmetic, not a defect. Fund it so the test
        # exercises the metadata, not the affordability floor.
        cfg = _cfg(self.user, asset_class="options", name="OPT",
                   symbols=["SPY"], stop_loss_pct=30.0, take_profit_pct=90.0,
                   cool_down_minutes=0, capital=Decimal("50000"))
        bot = OptionsBot(cfg)
        client = MagicMock()
        with patch.object(OptionsBot, "decide",
                          return_value=BotDecision("BUY", 0.9, [], "r1")),              patch.object(OptionsBot, "select_contract", return_value=contract),              patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            bot.scan_symbol("SPY")
        t = AssetBotTrade.objects.filter(config=cfg).first()
        self.assertIsNotNone(t, "options entry did not open a trade")
        self.assertIn("initial_stop_loss", t.metadata or {})
        # Premium-denominated, same scale as entry_price — not the underlying.
        self.assertAlmostEqual(float(t.metadata["initial_stop_loss"]),
                               float(t.stop_loss), places=4)
        self.assertLess(float(t.metadata["initial_stop_loss"]),
                        float(t.entry_price))


class QuietTickQueryBudgetTests(TestCase):
    """Hoisting the stats aggregation to the top of weighted_consensus made
    every tick pay for six months of history — including the overwhelming
    majority where nothing clears entry_score_min and there is not a single
    vote to weigh. Fixing a query bomb by moving it earlier is not fixing
    it."""

    def setUp(self):
        self.user = _user("qt_u")
        self.inst = _instrument("QTSYM")

    def test_no_votes_means_no_aggregation(self):
        from bot_program.asset_engine import aggregation
        calls = []
        with patch.object(aggregation, "_signal_stats",
                          side_effect=lambda: (calls.append(1), {})[1]):
            verdict = aggregation.weighted_consensus([], [],
                                                     asset_class="stock")
        self.assertEqual(verdict["direction"], "HOLD")
        self.assertEqual(calls, [])

    def test_one_vote_still_aggregates_exactly_once(self):
        from bot_program.asset_engine import aggregation
        calls = []
        with patch.object(aggregation, "_signal_stats",
                          side_effect=lambda: (calls.append(1), {})[1]):
            aggregation.weighted_consensus(
                [_signal(self.inst, "bullish", 0.8, f"r{i}") for i in range(5)],
                [], asset_class="stock")
        self.assertEqual(len(calls), 1)


# ── 2. The headcount the config promises must be the headcount enforced ──

class HeadcountFloorTests(TestCase):
    def setUp(self):
        self.user = _user("hc_u")
        self.inst = _instrument("HSYM")

    def test_one_heavily_weighted_rule_cannot_stand_in_for_two(self):
        """A rule that has earned a 2.0 weight clears a threshold meant to
        represent two independent confirmations. The config would read
        'min_signals_for_entry: 2' while the bot traded on one opinion."""
        from bot_program.asset_engine.aggregation import weighted_consensus
        bull = [_signal(self.inst, "bullish", 0.9, "proven")]
        with patch("bot_program.asset_engine.aggregation.rule_weight",
                   side_effect=lambda r, a="", **kw: 2.0):
            verdict = weighted_consensus(bull, [], min_net_weight=1.2,
                                         min_signals=2)
        self.assertEqual(verdict["direction"], "HOLD")
        self.assertIn("need 2", verdict["detail"])

    def test_two_agreeing_rules_pass_the_same_floor(self):
        from bot_program.asset_engine.aggregation import weighted_consensus
        bull = [_signal(self.inst, "bullish", 0.9, "a"),
                _signal(self.inst, "bullish", 0.9, "b")]
        with patch("bot_program.asset_engine.aggregation.rule_weight",
                   side_effect=lambda r, a="", **kw: 1.0):
            verdict = weighted_consensus(bull, [], min_net_weight=1.2,
                                         min_signals=2)
        self.assertEqual(verdict["direction"], "BUY")

    def test_two_signals_from_the_same_rule_are_one_opinion(self):
        """Two firings of one rule are correlated by construction — counting
        them as two confirmations is how a single indicator gets to vote
        twice."""
        from bot_program.asset_engine.aggregation import weighted_consensus
        bull = [_signal(self.inst, "bullish", 0.9, "same"),
                _signal(self.inst, "bullish", 0.9, "same")]
        with patch("bot_program.asset_engine.aggregation.rule_weight",
                   side_effect=lambda r, a="", **kw: 1.0):
            verdict = weighted_consensus(bull, [], min_net_weight=1.2,
                                         min_signals=2)
        self.assertEqual(verdict["direction"], "HOLD")

    def test_decide_passes_the_configured_floor_through(self):
        """The floor has to be what rejects this, not the weight threshold.
        extras pins min_net_weight low enough that one signal clears it
        comfortably, so a HOLD can only come from the headcount — and the
        control below proves the same setup enters at a floor of 1."""
        from bot_program.asset_engine import StockBot
        inst = _instrument("AAA")
        _signal(inst, "bullish", 0.95, "solo")
        cfg = _cfg(self.user, name="FLOOR", min_signals_for_entry=2,
                   extras={"min_net_weight": 0.5})
        d = StockBot(cfg).decide("AAA")
        self.assertEqual(d.direction, "HOLD")
        self.assertIn("need 2", d.reasons[0])

    def test_the_same_setup_enters_when_the_floor_is_one(self):
        """Control for the test above: identical signal and threshold, only
        min_signals_for_entry differs. Without this pair, a HOLD for any
        unrelated reason would look like the floor working."""
        from bot_program.asset_engine import StockBot
        inst = _instrument("AAA")
        _signal(inst, "bullish", 0.95, "solo")
        cfg = _cfg(self.user, name="FLOOR1", min_signals_for_entry=1,
                   extras={"min_net_weight": 0.5})
        self.assertEqual(StockBot(cfg).decide("AAA").direction, "BUY")


class WeightQueryBudgetTests(TestCase):
    """rule_weight aggregated six months of signals per call, inside a loop
    over every signal on both sides. One decision on a busy symbol turned
    into thousands of queries — enough to make the tick loop the heaviest
    thing on the box."""

    def setUp(self):
        self.user = _user("wq_u")
        self.inst = _instrument("QSYM")

    def test_stats_are_aggregated_once_per_decision(self):
        from bot_program.asset_engine import aggregation
        calls = []
        real = aggregation._signal_stats

        def counted():
            calls.append(1)
            return real()

        bull = [_signal(self.inst, "bullish", 0.5, f"r{i}") for i in range(8)]
        bear = [_signal(self.inst, "bearish", 0.5, f"b{i}") for i in range(8)]
        with patch.object(aggregation, "_signal_stats", counted):
            aggregation.weighted_consensus(bull, bear, asset_class="stock")
        self.assertEqual(sum(calls), 1)

    def test_a_repeated_rule_is_weighed_once(self):
        from bot_program.asset_engine import aggregation
        seen = []
        with patch.object(aggregation, "rule_weight",
                          side_effect=lambda r, a="", **kw: (seen.append(r), 1.0)[1]):
            aggregation.weighted_consensus(
                [_signal(self.inst, "bullish", 0.5, "dup") for _ in range(6)],
                [], asset_class="stock")
        self.assertEqual(seen, ["dup"])


# ── 3. A typo in extras must not silently disable risk management ────────

class ExtrasParsingTests(TestCase):
    def setUp(self):
        self.user = _user("ex_u")

    def test_a_non_numeric_knob_does_not_take_sl_tp_down_with_it(self):
        """extras is hand-edited JSON. `"trail_pct": "2%"` used to raise out
        of the exit block, skipping the stop-loss check for that trade — the
        position then ran unmanaged until reconciliation noticed."""
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        cfg = _cfg(self.user, name="BADEXTRAS", extras={"trail_pct": "2%"})
        t = _trade(cfg, stop_loss=Decimal("98"))
        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "95"})  # below SL
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            closed = StockBot(cfg).manage_positions()
        self.assertEqual(closed, 1)
        self.assertEqual(AssetBotTrade.objects.get(pk=t.pk).status, "CLOSED")

    def test_a_non_numeric_hold_window_does_not_raise(self):
        from bot_program.asset_engine import StockBot
        cfg = _cfg(self.user, name="BADHOLD", extras={"max_hold_hours": "two"})
        t = _trade(cfg, opened_at=timezone.now() - timedelta(days=9))
        self.assertFalse(StockBot(cfg)._time_stop_hit(t))


# ── 4. Live trades need the one exit the broker doesn't know about ───────

class LiveExitManagementTests(TestCase):
    def setUp(self):
        self.user = _user("lx_u")

    def test_time_stop_fires_on_a_broker_protected_trade(self):
        """A bracket holds SL and TP, so protected trades skipped our exit
        block entirely — correct for SL/TP, wrong for the time stop, which
        nothing at the broker will ever fire. Capital sat in a thesis that
        never moved, for as long as the market let it."""
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        cfg = _cfg(self.user, name="PROT", extras={"max_hold_hours": 24})
        t = _trade(cfg, metadata={"protected": True},
                   opened_at=timezone.now() - timedelta(hours=48))
        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "101"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            closed = StockBot(cfg).manage_positions()
        self.assertEqual(closed, 1)
        t = AssetBotTrade.objects.get(pk=t.pk)
        self.assertEqual(t.status, "CLOSED")
        self.assertIn("TIME", t.reason)

    def test_protected_trade_is_still_left_alone_at_its_stop(self):
        """The double-close guard has to survive the change: our market
        order flattens, then the broker's resting stop fires against a flat
        book and opens a brand-new reverse position."""
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        cfg = _cfg(self.user, name="PROT2")
        t = _trade(cfg, metadata={"protected": True}, stop_loss=Decimal("98"))
        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "90"})
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            StockBot(cfg).manage_positions()
        self.assertEqual(AssetBotTrade.objects.get(pk=t.pk).status, "OPEN")


class OrphanedBracketLegTests(TestCase):
    """Closing a bracketed position does not retire the bracket. The legs
    stay resting at the broker, and the stop eventually fires against a
    flat book — opening a brand-new position in the opposite direction that
    no row in our database describes, so nothing manages or closes it.

    Cancelling was only attempted when the close was REJECTED. Routing the
    time stop through protected trades made the successful-close path the
    common one, so the gap had to be shut."""

    def setUp(self):
        self.user = _user("ob_u")

    def _live_close(self, **trade_kw):
        from bot_program.asset_engine import StockBot
        cfg = _cfg(self.user, name="OB", mode="live")
        t = _trade(cfg, paper=False,
                   metadata={"protected": True,
                             "protective_order_ids": ["leg-sl", "leg-tp"]},
                   **trade_kw)
        client = MagicMock()
        client.ticker = MagicMock(return_value={"lastPrice": "101"})
        StockBot(cfg)._close_trade(t, Decimal("101"), client, reason="TIME")
        return client

    def test_legs_are_cancelled_after_a_successful_close(self):
        client = self._live_close()
        cancelled = {c.args[0] for c in client.cancel_order.call_args_list}
        self.assertEqual(cancelled, {"leg-sl", "leg-tp"})

    def test_a_broker_that_cannot_cancel_does_not_break_the_close(self):
        """cancel_order is best-effort — a broker that rejects it must not
        leave the row OPEN while the position is actually flat."""
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        cfg = _cfg(self.user, name="OB2", mode="live")
        t = _trade(cfg, paper=False,
                   metadata={"protected": True,
                             "protective_order_ids": ["leg-sl"]})
        client = MagicMock()
        client.cancel_order = MagicMock(side_effect=RuntimeError("nope"))
        self.assertTrue(
            StockBot(cfg)._close_trade(t, Decimal("101"), client, reason="TIME"))
        self.assertEqual(AssetBotTrade.objects.get(pk=t.pk).status, "CLOSED")

    def test_a_rejected_close_still_cancels_then_retries(self):
        """The original path has to survive: legs are stripped only after
        the close is refused, never speculatively — cancelling up front
        would leave a live, unprotected position whenever the close then
        fails."""
        from bot_program.asset_engine import StockBot
        cfg = _cfg(self.user, name="OB3", mode="live")
        t = _trade(cfg, paper=False,
                   metadata={"protected": True,
                             "protective_order_ids": ["leg-sl"]})
        client = MagicMock()
        client.market_order = MagicMock(
            side_effect=[RuntimeError("held by bracket"), {"status": "FILLED"}])
        self.assertTrue(
            StockBot(cfg)._close_trade(t, Decimal("101"), client, reason="TIME"))
        client.cancel_order.assert_called_once_with("leg-sl")
        self.assertEqual(client.market_order.call_count, 2)


# ── 5. The cost filter has to be able to reject something ────────────────

class CostFilterBiteTests(TestCase):
    def setUp(self):
        self.user = _user("cf_u")

    def test_the_gross_check_alone_cannot_reject_the_tightest_atr_setup(self):
        """Runs the real filter, not arithmetic on constants. At the very
        tightest stop the ATR path can produce (MIN_STOP_FRACTION, target
        2x that), the gross check passes for every non-options class — so
        on its own it could never reject an ATR setup, however marginal.
        Options are excluded deliberately: their 60bps makes the gross
        check bite there, which is exactly why it looked like it worked."""
        from bot_program.asset_engine.risk_levels import (
            MIN_STOP_FRACTION, passes_cost_filter,
        )
        # Rejected once costs are netted; forex is absent on purpose — at
        # 2bps a 0.2% stop really is 100x the round trip, and a filter that
        # rejected it would be wrong rather than strict.
        NET_REJECTS = {"stock", "crypto", "commodity"}
        for asset_class in ("stock", "forex", "crypto", "commodity"):
            cfg = _cfg(self.user, asset_class=asset_class,
                       name=f"GROSS-{asset_class}")
            price = 100.0
            stop = price * (1 - MIN_STOP_FRACTION)
            target = price * (1 + MIN_STOP_FRACTION * 2)
            ok, _ = passes_cost_filter(cfg, "SYM", price, target)
            self.assertTrue(ok, msg=f"{asset_class} rejected by gross check")
            ok_net, reason = passes_cost_filter(cfg, "SYM", price, target,
                                                stop=stop)
            self.assertEqual(ok_net, asset_class not in NET_REJECTS,
                             msg=f"{asset_class}: {reason}")

    def test_a_tight_stop_on_a_wide_spread_is_rejected(self):
        from bot_program.asset_engine.risk_levels import passes_cost_filter
        cfg = _cfg(self.user, asset_class="crypto", name="CF1")
        # 0.6% target, 0.3% stop — a gross 2:1 that the 0.1% round trip
        # drags to 1.25:1.
        ok, reason = passes_cost_filter(cfg, "BTCUSD", 100.0, 100.6, stop=99.7)
        self.assertFalse(ok)
        self.assertIn("reward:risk", reason)

    def test_a_wide_setup_still_passes(self):
        from bot_program.asset_engine.risk_levels import passes_cost_filter
        cfg = _cfg(self.user, asset_class="crypto", name="CF2")
        ok, _ = passes_cost_filter(cfg, "BTCUSD", 100.0, 104.5, stop=97.75)
        self.assertTrue(ok)

    def test_a_measured_spread_overrides_the_asset_class_average(self):
        from bot_program.asset_engine.risk_levels import passes_cost_filter
        cfg = _cfg(self.user, asset_class="options", name="CF3")
        # 1.00 mid with a 0.20 spread: 20% of the position, round trip.
        ok, reason = passes_cost_filter(cfg, "SPY", 1.00, 1.50, stop=0.70,
                                        cost_fraction=0.20)
        self.assertFalse(ok)

    def test_the_filter_is_still_opt_out(self):
        from bot_program.asset_engine.risk_levels import passes_cost_filter
        cfg = _cfg(self.user, asset_class="crypto", name="CF4",
                   extras={"use_cost_filter": False})
        ok, _ = passes_cost_filter(cfg, "BTCUSD", 100.0, 100.01, stop=99.99)
        self.assertTrue(ok)


# ── 6. Quotes must reach every symbol with money behind it ───────────────

class QuoteUniverseTests(TestCase):
    """The pollers read the watchlist alone. A bot trading a symbol nobody
    had starred got bars and signals but no LiveQuote — and LiveQuote is
    what the mark and the paper fill path read, so the bot formed decisions
    it could never act on."""

    def setUp(self):
        self.user = _user("qu_u")

    def test_a_bot_only_symbol_is_polled(self):
        from signals.universe import quote_targets
        _instrument("BOTONLY", watchlist=False)
        _cfg(self.user, name="QU", symbols=["BOTONLY"])
        self.assertIn("BOTONLY", [i.symbol for i in quote_targets("stock")])

    def test_watchlist_symbols_are_still_polled(self):
        from signals.universe import quote_targets
        _instrument("STARRED", watchlist=True)
        self.assertIn("STARRED", [i.symbol for i in quote_targets("stock")])

    def test_traded_symbols_survive_the_provider_budget(self):
        """Free tiers cap symbols per run. When the list is truncated the
        ones with real money behind them must be what's left."""
        from signals.universe import quote_targets
        for i in range(5):
            _instrument(f"WATCH{i}", watchlist=True)
        _instrument("ZTRADED", watchlist=False)
        _cfg(self.user, name="QU2", symbols=["ZTRADED"])
        picked = [i.symbol for i in quote_targets("stock", limit=1)]
        self.assertEqual(picked, ["ZTRADED"])

    def test_other_asset_classes_are_not_polled_by_the_stock_task(self):
        from signals.universe import quote_targets
        _instrument("EURUSD", asset_class="forex", watchlist=True)
        self.assertNotIn("EURUSD", [i.symbol for i in quote_targets("stock")])
