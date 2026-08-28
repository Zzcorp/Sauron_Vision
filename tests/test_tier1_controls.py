"""Four controls that returned the shape of success while doing nothing.

Each of these sits between a live position and a real loss, and each one
reported a pass it had not earned:

  the drawdown breaker   netted SIMULATED profit into a live equity curve,
                         so paper wins raised the peak a live drawdown was
                         measured from — and while one rule is promoted
                         platform-wide the actuator forces most entries to
                         paper, so that curve was mostly invented.

  the kill switch        could not stop the tick already in flight.
                         can_open_new never re-read `enabled`, so a tick
                         holding a stale config kept opening at the broker
                         AFTER the flatten pass had walked past those
                         symbols — and nothing manages what it opened,
                         because the runner refuses a disabled config.

  the 5% risk cap        was clamped in `risk_fraction()` and then scaled
                         past by the allocator multiplier, which the
                         meta-allocator writes anywhere in [0.10, 3.00].
                         Dormant only while every multiplier is <= 1.0.

  a broker-held target   was written to the row and nowhere else, with
                         ok=true and an audit entry claiming an "in-place"
                         broker modification that never happened.

Run with:  python manage.py test tests.test_tier1_controls
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _cfg(user, **kw):
    from bot_program.models import AssetBotConfig
    opts = dict(user=user, asset_class="stock", name="T1", mode="live",
                symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
    opts.update(kw)
    return AssetBotConfig.objects.create(**opts)


def _closed(cfg, pnl, paper=False, hours_ago=1):
    from bot_program.models import AssetBotTrade
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
        qty=Decimal("10"), entry_price=Decimal("100"),
        exit_price=Decimal("99") if pnl is not None else None,
        pnl=pnl, status="CLOSED", paper=paper,
        opened_at=timezone.now() - timedelta(hours=hours_ago + 1))
    t.closed_at = timezone.now() - timedelta(hours=hours_ago)
    t.save(update_fields=["closed_at"])
    return t


class TheDrawdownCurveIsNotNettedTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("t1_dd", password="x")
        self.cfg = _cfg(self.user, extras={"max_drawdown_pct": 20.0})

    def _check(self):
        from bot_program.asset_engine.safety import CircuitBreakers
        return CircuitBreakers(self.cfg).check_drawdown_from_peak()

    def test_paper_profit_cannot_mask_a_live_drawdown(self):
        """The whole bug. Six paper winners lift the blended peak so the
        live losses beneath them never read as a drawdown."""
        for i in range(6):
            _closed(self.cfg, Decimal("400"), paper=True, hours_ago=20 - i)
        for i in range(6):
            _closed(self.cfg, Decimal("-400"), paper=False, hours_ago=10 - i)
        ok, reason = self._check()
        self.assertFalse(ok, "the live curve drew down 24% and was masked")
        self.assertIn("live", reason)

    def test_a_paper_drawdown_can_still_halt(self):
        """Separating the curves must not weaken the breaker: a strategy
        bleeding on paper is still bleeding."""
        for i in range(6):
            _closed(self.cfg, Decimal("-400"), paper=True, hours_ago=10 - i)
        ok, reason = self._check()
        self.assertFalse(ok)
        self.assertIn("paper", reason)

    def test_a_healthy_book_still_passes(self):
        for i in range(6):
            _closed(self.cfg, Decimal("50"), paper=False, hours_ago=10 - i)
        self.assertTrue(self._check()[0])

    def test_an_unmeasured_close_is_excluded_not_scored_as_flat(self):
        """`float(pnl or 0)` scored a close nobody could price as a
        break-even — the fabrication the nullable column exists to stop."""
        for i in range(6):
            _closed(self.cfg, Decimal("-400"), paper=False, hours_ago=20 - i)
        _closed(self.cfg, None, paper=False, hours_ago=2)
        ok, reason = self._check()
        self.assertFalse(ok)
        self.assertIn("unmeasured", reason)


class TheKillSwitchStopsThisTickTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("t1_ks", password="x")
        self.cfg = _cfg(self.user)

    def test_a_disarm_between_ticks_is_seen(self):
        """The config in memory still says enabled; the database does not,
        and the database is the one the operator just wrote to."""
        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotConfig
        bot = StockBot(self.cfg)
        AssetBotConfig.objects.filter(pk=self.cfg.pk).update(enabled=False)
        self.assertTrue(bot.cfg.enabled, "the in-memory copy is stale — "
                                        "which is the whole point")
        ok, reason = bot.can_open_new()
        self.assertFalse(ok)
        self.assertIn("disarmed", reason)

    def test_an_armed_config_is_unaffected(self):
        from bot_program.asset_engine.stock_bot import StockBot
        ok, reason = StockBot(self.cfg).can_open_new()
        self.assertNotIn("disarmed", reason)

    def test_a_database_error_fails_open_loudly(self):
        """Halting the whole fleet on a transient hiccup is the worse
        failure — the posture preflight already takes. A disarm will still
        be true next tick; a dropped connection will not."""
        from bot_program.asset_engine.stock_bot import StockBot
        bot = StockBot(self.cfg)
        with patch("bot_program.models.AssetBotConfig.objects.filter",
                   side_effect=RuntimeError("connection lost")):
            self.assertTrue(bot._still_armed())


class TheRiskCeilingBindsOnTheFinalSizeTests(TestCase):
    """`risk_fraction()` clamps to 5%, and then the allocator multiplies
    the QUANTITY. Driven through scan_symbol, because the arithmetic is
    not the claim — the claim is that this entry path refuses."""

    def setUp(self):
        from instruments.models import Instrument
        from signals.models import Signal
        self.user = User.objects.create_user("t1_cap", password="x")
        # A WIDE stop on purpose. With a tight one the notional cap binds
        # first and this class would pass without the risk ceiling ever
        # running — which is how a test comes to prove someone else's gate.
        # At 30%%, one unit risks 30 and the 5%% budget buys ~16 units:
        # 1,600 of notional, comfortably inside the single-position limit,
        # so the ceiling is the gate under test.
        self.cfg = _cfg(self.user, mode="paper", symbols=["CAP1"],
                        entry_score_min=0.6, min_signals_for_entry=1,
                        stop_loss_pct=30.0, take_profit_pct=60.0,
                        # Sized AT the cap, so the only thing that can carry
                        # this entry past it is the allocator multiplier —
                        # which is precisely the hole being closed. The
                        # default risk fraction is far below the cap, and a
                        # 3x lane on top of it still clears, so a test left
                        # on the default would pass with the gate deleted.
                        extras={"risk_per_trade_pct": 5.0})
        inst, _ = Instrument.objects.get_or_create(
            symbol="CAP1", defaults={"name": "Cap One",
                                     "asset_class": "stock"})
        Signal.objects.create(
            instrument=inst, signal_type="composite", direction="bullish",
            urgency="medium", title="CAP1 bullish", description="t",
            rule_name="cap_rule", score=0.85, sub_scores={},
            price_at_signal=Decimal("100"),
            suggested_entry=Decimal("100"), suggested_stop=Decimal("95"),
            suggested_target=Decimal("110"))

    def _scan(self, multiplier):
        from bot_program.asset_engine.stock_bot import StockBot
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": "100.00"}
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client), \
             patch("signals.rule_actuator.admin_allocator_multiplier",
                   return_value=multiplier):
            return StockBot(self.cfg).scan_symbol("CAP1")

    def test_an_allocator_lane_cannot_size_past_the_ceiling(self):
        """3x is inside the meta-allocator's own [0.10, 3.00] range, so
        this is the size the platform would really send."""
        from bot_program.models import AssetBotTrade
        self._scan(3.0)
        self.assertEqual(AssetBotTrade.objects.count(), 0,
                         "an entry risking 3x the 5% cap was written")

    def test_an_unscaled_entry_is_still_taken(self):
        """The ceiling must refuse the oversized trade, not all trades."""
        from bot_program.models import AssetBotTrade
        self._scan(1.0)
        self.assertEqual(AssetBotTrade.objects.count(), 1)

    def test_the_refusal_names_the_ceiling_and_the_lane(self):
        """scan_symbol returns None for every skip; the reason lands in
        cfg.extras["skips"], which is what the operator actually reads."""
        self._scan(3.0)
        self.cfg.refresh_from_db()
        skip = (self.cfg.extras or {}).get("skips", {}).get("CAP1", {})
        self.assertEqual(skip.get("code"), "gate_blocked")
        self.assertIn("ceiling", skip.get("detail", "").lower())
        self.assertIn("allocator", skip.get("detail", "").lower())


class ABrokerHeldTargetIsRefusedTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("t1_lv", password="x")
        self.cfg = _cfg(self.user)

    def _trade(self, protected=True):
        from bot_program.models import AssetBotTrade
        return AssetBotTrade.objects.create(
            config=self.cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"),
            stop_loss=Decimal("95"), take_profit=Decimal("110"),
            status="OPEN", paper=False, opened_at=timezone.now(),
            metadata={"protected": protected,
                      "protective_order_ids": ["1"]})

    def test_raising_a_target_on_a_protected_row_is_refused(self):
        from bot_program.adjust_levels import adjust_levels
        t = self._trade()
        res = adjust_levels(self.user, t, target=Decimal("120"))
        self.assertFalse(res["ok"])
        self.assertIn("rests at the broker", res["error"])

    def test_the_row_is_not_changed_by_the_refusal(self):
        """The old path returned ok=true with the row updated and the
        broker's limit still resting at the old number."""
        from bot_program.adjust_levels import adjust_levels
        from bot_program.models import AssetBotTrade
        t = self._trade()
        adjust_levels(self.user, t, target=Decimal("120"))
        self.assertEqual(AssetBotTrade.objects.get(pk=t.pk).take_profit,
                         Decimal("110"))

    def test_clearing_a_target_on_a_protected_row_is_refused(self):
        """Worse than raising it: the row would show no target while the
        broker's still fills."""
        from bot_program.adjust_levels import adjust_levels
        from bot_program.models import AssetBotTrade
        t = self._trade()
        res = adjust_levels(self.user, t, clear_target=True)
        self.assertFalse(res["ok"])
        self.assertEqual(AssetBotTrade.objects.get(pk=t.pk).take_profit,
                         Decimal("110"))

    def test_an_unprotected_row_still_accepts_a_target(self):
        """The refusal is about the broker holding the leg, not about
        targets."""
        from bot_program.adjust_levels import adjust_levels
        from bot_program.models import AssetBotTrade
        t = self._trade(protected=False)
        res = adjust_levels(self.user, t, target=Decimal("120"))
        self.assertTrue(res["ok"], res.get("error"))
        self.assertEqual(AssetBotTrade.objects.get(pk=t.pk).take_profit,
                         Decimal("120"))

    def test_the_audit_no_longer_claims_an_in_place_broker_move(self):
        """`broker: "in-place"` on a row-only edit recorded a modification
        that never happened."""
        from bot_program.adjust_levels import adjust_levels
        from bot_program.models import AssetBotTrade
        t = self._trade(protected=False)
        adjust_levels(self.user, t, target=Decimal("120"))
        edits = (AssetBotTrade.objects.get(pk=t.pk).metadata or {}
                 ).get("level_edits") or []
        self.assertTrue(edits)
        self.assertNotEqual(edits[-1]["broker"], "in-place")
