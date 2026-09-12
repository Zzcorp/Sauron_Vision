"""The capital-desk seam (Stage 1, 2026-09-12).

`AssetBot.scan_symbol` was one inline function from "already open" to "push
the fill". It is now `execute_entry(propose_entry(symbol))`: the proposal is
every gate and the bot's own final size, packaged as an EntryCandidate; the
execution re-judges the size (times the desk's multiplier), then runs the
shadow branch, the order and the row. These tests pin what the split must
keep true:

  - scan_symbol on a paper config writes the same row, with the same
    metadata keys, as propose followed by execute;
  - the two exits that were a bare `return None` are recorded skips now
    (BRAIN_PAUSED, ORDER_ERROR);
  - pricing="data" reads the ticker through the router's data session;
  - execute_entry re-judges the MAX_RISK_FRACTION ceiling on qty x
    size_mult — 0.5 halves the size, 2.0 is refused exactly as the
    allocator lane is, never clamped;
  - a tick-wide signal_stats aggregate threads through decide() and
    changes no decision;
  - the options lane is not desked and says so.

Run with:  python manage.py test tests.test_desk_seam
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _user(name="seam_user"):
    return User.objects.create_user(username=name, password="x")


def _config(user, asset_class="stock", **overrides):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        user=user, asset_class=asset_class, name="Seam Bot",
        enabled=True, mode="paper",
        symbols=[],
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
        entry_score_min=0.6, min_signals_for_entry=1, cool_down_minutes=0,
    )
    defaults.update(overrides)
    return AssetBotConfig.objects.create(**defaults)


def _signal(symbol, direction, score, rule="rule_a", asset_class="stock"):
    from signals.models import Signal
    inst = _instrument(symbol, asset_class)
    return Signal.objects.create(
        instrument=inst, signal_type="composite", direction=direction,
        urgency="medium", title=f"{symbol} {direction}", description="t",
        rule_name=rule, score=score, sub_scores={},
        price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
        suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
    )


def _client(price="150.00"):
    client = MagicMock()
    client.ticker.return_value = {"lastPrice": price}
    client.get_positions.return_value = []
    return client


ROUTER = "bot_program.engine.broker_router.client_for_symbol"


# ── scan_symbol == execute(propose) ─────────────────────────────────────────

class SplitIsBehaviourPreservingTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.cfg = _config(self.user, symbols=["SEAM1"])
        _signal("SEAM1", "bullish", 0.85, rule="seam_rule")

    def test_scan_symbol_equals_execute_of_propose(self):
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        bot = StockBot(self.cfg)

        with patch(ROUTER, return_value=_client()):
            res1 = bot.scan_symbol("SEAM1")
        self.assertIsNotNone(res1)
        t1 = AssetBotTrade.objects.get(id=res1["trade_id"])
        keys1 = set((t1.metadata or {}).keys())
        # The book must not hold the first row, or the duplicate gate — one
        # expression per bet — refuses the second, correctly.
        t1.delete()

        with patch(ROUTER, return_value=_client()):
            cand = bot.propose_entry("SEAM1")
            self.assertIsNotNone(cand)
            self.assertEqual(cand.symbol, "SEAM1")
            self.assertEqual(cand.venue, "paper")
            self.assertEqual(cand.direction, "BUY")
            self.assertEqual(cand.rule_name, "seam_rule")
            self.assertEqual(cand.cfg_id, self.cfg.id)
            self.assertEqual(cand.user_id, self.user.id)
            self.assertAlmostEqual(cand.qty_default, res1["qty"], places=6)
            self.assertAlmostEqual(cand.price, res1["entry"], places=6)
            self.assertAlmostEqual(
                cand.risk_dollars_default,
                cand.qty_default * abs(cand.price - cand.stop), places=6)
            self.assertAlmostEqual(cand.per_unit_risk,
                                   abs(cand.price - cand.stop), places=8)
            self.assertEqual(AssetBotTrade.objects.count(), 0,
                             "propose_entry must write nothing")
            res2 = bot.execute_entry(cand)

        self.assertIsNotNone(res2)
        t2 = AssetBotTrade.objects.get(id=res2["trade_id"])
        self.assertEqual(set((t2.metadata or {}).keys()), keys1)
        self.assertEqual(t2.qty, t1.qty)
        self.assertEqual(t2.entry_price, t1.entry_price)
        self.assertEqual(t2.stop_loss, t1.stop_loss)
        self.assertEqual(t2.take_profit, t1.take_profit)
        self.assertEqual(t2.side, t1.side)
        self.assertEqual(t2.rule_name, "seam_rule")
        self.assertTrue(t2.paper)
        self.assertEqual(t2.metadata["initial_stop_loss"],
                         round(cand.stop, 8))

    def test_scan_symbol_is_nothing_but_the_two_halves(self):
        """A HOLD proposes nothing and executes nothing."""
        from bot_program.asset_engine import StockBot
        from bot_program.models import AssetBotTrade
        _instrument("SEAM1H")
        cfg = _config(self.user, name="H", symbols=["SEAM1H"])
        bot = StockBot(cfg)
        with patch.object(bot, "execute_entry") as ex, \
                patch(ROUTER, return_value=_client()) as router:
            self.assertIsNone(bot.scan_symbol("SEAM1H"))
        ex.assert_not_called()
        router.assert_not_called()
        self.assertEqual(AssetBotTrade.objects.count(), 0)

    def test_candidate_horizon_follows_the_time_stop(self):
        from bot_program.asset_engine import StockBot
        from bot_program.asset_engine.candidates import DEFAULT_HORIZON_HOURS
        bounded = _config(self.user, name="TS", symbols=["SEAM1"],
                          max_hold_hours=48)
        with patch(ROUTER, return_value=_client()):
            cand = StockBot(bounded).propose_entry("SEAM1")
        self.assertIsNotNone(cand)
        self.assertEqual(cand.horizon_hours, 48.0)

        off = _config(self.user, name="TS0", symbols=["SEAM1"],
                      extras={"max_hold_hours": 0})
        with patch(ROUTER, return_value=_client()):
            cand = StockBot(off).propose_entry("SEAM1")
        self.assertIsNotNone(cand)
        self.assertEqual(cand.horizon_hours, DEFAULT_HORIZON_HOURS)
        self.assertEqual(DEFAULT_HORIZON_HOURS, 168.0)


# ── the two bare exits are recorded now ─────────────────────────────────────

class NewSkipCodesTests(TestCase):
    def setUp(self):
        self.user = _user("seam_skips")

    def test_brain_pause_is_recorded(self):
        from bot_program.asset_engine import StockBot, skips
        from bot_program.models import AssetBotTrade
        cfg = _config(self.user, symbols=["SEAM2"])
        _signal("SEAM2", "bullish", 0.85, rule="parked_rule")
        bot = StockBot(cfg)
        with patch("brain.context.brain_rule_advisory",
                   return_value=("pause_recommended", "latest BrainReport")), \
                patch("brain.observations.record_observation"), \
                patch("bot_program.audit.record_brain_soft_block"), \
                patch(ROUTER, return_value=_client()) as router:
            self.assertIsNone(bot.scan_symbol("SEAM2"))
        router.assert_not_called()
        cfg.refresh_from_db()
        note = skips.last_by_symbol(cfg)["SEAM2"]
        self.assertEqual(note["code"], skips.BRAIN_PAUSED)
        self.assertIn("parked_rule", note["detail"])
        self.assertEqual(AssetBotTrade.objects.count(), 0)

    def test_live_order_exception_is_recorded(self):
        from bot_program.asset_engine import StockBot, skips
        from bot_program.models import AssetBotTrade
        from signals.models import RuleControl
        RuleControl.objects.create(
            rule_name="seam_live_rule", status="active",
            promotion_stage="live_full", stage_entered_at=timezone.now())
        cfg = _config(self.user, symbols=["SEAM3"], mode="live")
        _signal("SEAM3", "bullish", 0.85, rule="seam_live_rule")
        client = _client()
        client.market_order.side_effect = RuntimeError("socket closed")
        bot = StockBot(cfg)
        with patch(ROUTER, return_value=client):
            self.assertIsNone(bot.scan_symbol("SEAM3"))
        client.market_order.assert_called_once()
        cfg.refresh_from_db()
        note = skips.last_by_symbol(cfg)["SEAM3"]
        self.assertEqual(note["code"], skips.ORDER_ERROR)
        self.assertIn("socket closed", note["detail"])
        self.assertEqual(AssetBotTrade.objects.count(), 0,
                         "an order that raised must not book a row")

    def test_the_vocabulary_and_diagnose_know_the_codes(self):
        from bot_program.asset_engine import skips
        self.assertEqual(skips.BRAIN_PAUSED, "brain_paused")
        self.assertEqual(skips.ORDER_ERROR, "order_error")
        cfg = _config(self.user, symbols=["SEAMD"])
        skips.record(cfg, "SEAMD", skips.ORDER_ERROR, "x")
        cfg.refresh_from_db()
        self.assertIn("broker", skips.diagnose(cfg))
        skips.record(cfg, "SEAMD", skips.BRAIN_PAUSED, "x")
        skips.record(cfg, "SEAMD", skips.BRAIN_PAUSED, "x")
        cfg.refresh_from_db()
        self.assertIn("pause_recommended", skips.diagnose(cfg))


# ── pricing='data' ───────────────────────────────────────────────────────────

class PricingSessionTests(TestCase):
    def setUp(self):
        self.user = _user("seam_pricing")
        self.cfg = _config(self.user, symbols=["SEAM4"])
        _signal("SEAM4", "bullish", 0.85, rule="seam_rule")

    def test_data_pricing_asks_for_the_data_session(self):
        from bot_program.asset_engine import StockBot
        bot = StockBot(self.cfg)
        with patch(ROUTER, return_value=_client()) as router:
            cand = bot.propose_entry("SEAM4", pricing="data")
        self.assertIsNotNone(cand)
        router.assert_called_once_with(self.user, "SEAM4", self.cfg,
                                       purpose="data")

    def test_trade_pricing_is_the_call_it_always_was(self):
        from bot_program.asset_engine import StockBot
        bot = StockBot(self.cfg)
        with patch(ROUTER, return_value=_client()) as router:
            cand = bot.propose_entry("SEAM4")
        self.assertIsNotNone(cand)
        router.assert_called_once_with(self.user, "SEAM4", self.cfg)

    def test_a_busy_data_session_does_not_cost_a_live_entry(self):
        """REGRESSION (adversarial review, 2026-09-12): SHADOW may not stop
        the live fleet trading.

        The router hands back a PaperTrader whenever the IBKR clientId for a
        purpose is unavailable, and the DATA id is the busy one — the bar
        writer takes it every 600 s. Read by the live-config money guard as
        a credential failure, that stand-in refused an entry this same
        config takes today through its trade session: the desk's proposal
        pass would have switched the live lane off while the plan beside it
        claimed to change nothing. A live config with no data session prices
        through the client this step always used; nothing is sent from here
        either way.
        """
        from bot_program.asset_engine import StockBot, skips
        from bot_program.engine.paper_trader import PaperTrader

        live = _config(self.user, name="Live Bot", mode="live",
                       symbols=["SEAM4"])
        trade_client = _client()
        stand_in = PaperTrader(live)

        def route(user, symbol, cfg, purpose="trade"):
            return stand_in if purpose == "data" else trade_client

        with patch(ROUTER, side_effect=route), \
                patch.object(StockBot, "_notify_paper_fallback") as notify:
            cand = StockBot(live).propose_entry("SEAM4", pricing="data")

        self.assertIsNotNone(cand, "a busy data session must not lose the entry")
        notify.assert_not_called()
        self.assertEqual(skips.last_by_symbol(live).get("SEAM4"), None)
        trade_client.ticker.assert_called_with("SEAM4")

    def test_no_trade_session_either_is_still_refused(self):
        """The money guard itself is untouched: when the client an order
        would go through is a stand-in, a live config is refused exactly as
        before, with PAPER_FALLBACK and the operator told."""
        from bot_program.asset_engine import StockBot, skips
        from bot_program.engine.paper_trader import PaperTrader

        live = _config(self.user, name="Dead Bot", mode="live",
                       symbols=["SEAM4"])
        with patch(ROUTER, side_effect=lambda *a, **k: PaperTrader(live)), \
                patch.object(StockBot, "_notify_paper_fallback") as notify:
            cand = StockBot(live).propose_entry("SEAM4", pricing="data")

        self.assertIsNone(cand)
        notify.assert_called_once()
        self.assertEqual(skips.last_by_symbol(live)["SEAM4"]["code"],
                         skips.PAPER_FALLBACK)

    def test_execute_acquires_the_trade_session_itself(self):
        from bot_program.asset_engine import StockBot
        bot = StockBot(self.cfg)
        with patch(ROUTER, return_value=_client()) as router:
            cand = bot.propose_entry("SEAM4", pricing="data")
            router.reset_mock()
            res = bot.execute_entry(cand)
        self.assertIsNotNone(res)
        router.assert_called_once_with(self.user, "SEAM4", self.cfg)


# ── execute re-judges the ceiling ────────────────────────────────────────────

class SizeMultCeilingTests(TestCase):
    """3% risk per trade on a 5% ceiling: 1.0 fits, 0.5 halves, 2.0 (6%) is
    refused by the MAX_RISK_FRACTION arithmetic exactly as the allocator
    lane would be. A 30% stop keeps the notional (~$1,000 of a $10,000 pool)
    well inside the single-position cap, so the ceiling is the only gate
    that can bind here."""

    def setUp(self):
        self.user = _user("seam_mult")
        self.cfg = _config(self.user, symbols=["SEAM5"],
                           stop_loss_pct=30.0, take_profit_pct=60.0,
                           extras={"risk_per_trade_pct": 3.0})
        _signal("SEAM5", "bullish", 0.85, rule="seam_rule")

    def _cand(self):
        from bot_program.asset_engine import StockBot
        self.bot = StockBot(self.cfg)
        with patch(ROUTER, return_value=_client()):
            cand = self.bot.propose_entry("SEAM5")
        self.assertIsNotNone(cand)
        return cand

    def test_half_halves_the_quantity(self):
        from bot_program.models import AssetBotTrade
        cand = self._cand()
        with patch(ROUTER, return_value=_client()):
            res = self.bot.execute_entry(cand, size_mult=0.5)
        self.assertIsNotNone(res)
        t = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertAlmostEqual(float(t.qty), cand.qty_default * 0.5, places=5)
        # entry_meta risk_dollars is the sizer's PRE-multiplier number, as
        # before; the actual risk is qty x per_unit_risk.
        self.assertAlmostEqual(float(t.metadata["risk_dollars"]),
                               cand.sizing["risk_dollars"], places=6)

    def test_one_is_the_default_size(self):
        from bot_program.models import AssetBotTrade
        cand = self._cand()
        with patch(ROUTER, return_value=_client()):
            res = self.bot.execute_entry(cand)
        t = AssetBotTrade.objects.get(id=res["trade_id"])
        self.assertAlmostEqual(float(t.qty), cand.qty_default, places=6)

    def test_two_is_refused_at_the_ceiling_not_clamped(self):
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.sizing import MAX_RISK_FRACTION
        from bot_program.models import AssetBotTrade
        cand = self._cand()
        # The default size is inside the ceiling; twice it is not.
        ceiling = float(self.cfg.capital) * MAX_RISK_FRACTION
        self.assertLessEqual(cand.risk_dollars_default, ceiling + 1e-9)
        self.assertGreater(cand.risk_dollars_default * 2.0, ceiling)
        with patch(ROUTER, return_value=_client()) as router:
            res = self.bot.execute_entry(cand, size_mult=2.0)
        self.assertIsNone(res)
        router.assert_not_called()
        self.assertEqual(AssetBotTrade.objects.count(), 0,
                         "refused, never clamped to the ceiling")
        self.cfg.refresh_from_db()
        note = skips.last_by_symbol(self.cfg)["SEAM5"]
        self.assertEqual(note["code"], skips.GATE_BLOCKED)
        self.assertIn("ceiling", note["detail"])

    def test_execute_rejudges_the_book_not_just_the_ceiling(self):
        """The duplicate gate reads the live rows at call time: a row the
        proposal did not see refuses the execution."""
        from bot_program.asset_engine import skips
        from bot_program.models import AssetBotTrade
        cand = self._cand()
        other = _config(self.user, name="Other", symbols=["SEAM5"])
        AssetBotTrade.objects.create(
            config=other, asset_class="stock", symbol="SEAM5", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("150"), status="OPEN",
            paper=True)
        with patch(ROUTER, return_value=_client()):
            res = self.bot.execute_entry(cand)
        self.assertIsNone(res)
        self.assertEqual(AssetBotTrade.objects.filter(config=self.cfg).count(), 0)
        self.cfg.refresh_from_db()
        self.assertEqual(skips.last_by_symbol(self.cfg)["SEAM5"]["code"],
                         skips.GATE_BLOCKED)


# ── signal_stats threading ───────────────────────────────────────────────────

class SignalStatsThreadingTests(TestCase):
    def setUp(self):
        self.user = _user("seam_stats")
        self.cfg = _config(self.user, symbols=["SEAM6"])
        _signal("SEAM6", "bullish", 0.85, rule="rule_a")
        _signal("SEAM6", "bullish", 0.75, rule="rule_b")

    def test_a_tick_wide_aggregate_changes_no_decision(self):
        from bot_program.asset_engine import StockBot
        from bot_program.asset_engine.aggregation import signal_stats_for_tick
        bot = StockBot(self.cfg)
        stats = signal_stats_for_tick()
        self.assertIsInstance(stats, dict)
        lazy = bot.decide("SEAM6")
        threaded = bot.decide("SEAM6", signal_stats=stats)
        self.assertEqual(lazy.direction, "BUY")
        self.assertEqual(threaded.direction, lazy.direction)
        self.assertEqual(threaded.rule_name, lazy.rule_name)
        self.assertAlmostEqual(threaded.score, lazy.score, places=6)
        self.assertEqual(threaded.reasons, lazy.reasons)

    def test_a_supplied_aggregate_is_not_recomputed(self):
        from bot_program.asset_engine import StockBot, aggregation
        bot = StockBot(self.cfg)
        calls = []
        with patch.object(aggregation, "_signal_stats",
                          side_effect=lambda: (calls.append(1), {})[1]):
            bot.decide("SEAM6", signal_stats={})
        self.assertEqual(calls, [], "supplied stats must seed the cache")
        with patch.object(aggregation, "_signal_stats",
                          side_effect=lambda: (calls.append(1), {})[1]):
            bot.decide("SEAM6")
        self.assertEqual(len(calls), 1, "None keeps the lazy aggregation")

    def test_propose_entry_threads_it_to_decide(self):
        from bot_program.asset_engine import StockBot
        bot = StockBot(self.cfg)
        seen = []
        real = bot.decide

        def spy(symbol, **kw):
            seen.append(kw)
            return real(symbol, **kw)

        with patch.object(bot, "decide", side_effect=spy), \
                patch(ROUTER, return_value=_client()):
            self.assertIsNotNone(bot.propose_entry("SEAM6"))
            self.assertIsNotNone(bot.propose_entry("SEAM6", signal_stats={}))
        self.assertEqual(seen, [{}, {"signal_stats": {}}])

    def test_subclass_overrides_accept_the_kwarg(self):
        from bot_program.asset_engine import ForexBot, OptionsBot, StockBot
        for cls, ac in ((StockBot, "stock"), (ForexBot, "forex"),
                        (OptionsBot, "options")):
            cfg = _config(self.user, ac, name=f"K-{ac}", symbols=[])
            _instrument(f"SEAMK{ac}", ac)
            d = cls(cfg).decide(f"SEAMK{ac}", signal_stats={})
            self.assertEqual(d.direction, "HOLD")


# ── options: not desked ──────────────────────────────────────────────────────

class OptionsLaneNotDeskedTests(TestCase):
    def test_flag_and_loud_refusal(self):
        from bot_program.asset_engine import AssetBot, OptionsBot, StockBot
        self.assertTrue(AssetBot.DESKED)
        self.assertTrue(StockBot.DESKED)
        self.assertFalse(OptionsBot.DESKED)
        u = _user("seam_opt")
        bot = OptionsBot(_config(u, "options", symbols=["SPY"]))
        with self.assertRaises(NotImplementedError):
            bot.propose_entry("SPY", pricing="data")
        with self.assertRaises(NotImplementedError):
            bot.execute_entry(None)
