"""The capital desk (Stage 2, 2026-09-12).

The operator asked for "an agent that continuously recomputes, from the
opportunities available and the risk, the best way to place capital to
maximise gains and snuff out risk". These tests pin the four pieces that
agent is made of and the two-phase pass that runs it:

  - EXPECTED R: the lane order (own config live beats the fleet), the
    ten-fill floor, the paper and Signal haircuts, the decay haircut, and
    the rule the whole design rests on — a measured expectancy is NEVER
    multiplied by the decision's conviction, because the size already was;
  - CORRELATION: 4h buckets aligned across feeds, a pair under sixty shared
    bars left UNMEASURED rather than called uncorrelated, the cache, and the
    sign flip that makes an opposite-direction bet a hedge;
  - THE BOOK: risk at stop over open rows, the manual lane counted as the
    exposure it is, a row with no initial stop counted as unmeasured;
  - THE CHOICE: the budget spent in marginal risk, the 0.25 floor under a
    resize, the rule and class share caps, one expression per bet across
    configs, a config out of slots, the governor on live only, and the two
    venues never sharing anything;
  - THE PASS: in SHADOW the fleet does exactly what the legacy loop did and
    the plan beside it is the counterfactual; in LIVE the displaced are
    skipped with DESK_DISPLACED and the chosen carry their multiplier; a
    desk that raises fails OPEN; the component off is the legacy loop and
    writes no rows at all.

Run with:  python manage.py test tests.test_capital_desk
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

ROUTER = "bot_program.engine.broker_router.client_for_symbol"


# ── fixtures ────────────────────────────────────────────────────────────────

def _component(key, enabled=True):
    from core.platform_control import PlatformComponent
    return PlatformComponent.objects.create(
        key=key, name=key, description="", category="pipeline",
        is_enabled=enabled)


def _user(name="desk_user"):
    return User.objects.create_user(username=name, password="x")


def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _config(user, **overrides):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        user=user, asset_class="stock", name="Desk Bot", enabled=True,
        mode="paper", symbols=[], capital=Decimal("10000"),
        base_currency="USD", position_size_pct=2.0,
        max_concurrent_positions=5, max_daily_loss_pct=2.0,
        stop_loss_pct=1.5, take_profit_pct=3.0, entry_score_min=0.6,
        min_signals_for_entry=1, cool_down_minutes=0,
    )
    defaults.update(overrides)
    return AssetBotConfig.objects.create(**defaults)


def _signal(symbol, direction="bullish", score=0.85, rule="desk_rule",
            asset_class="stock"):
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


def _closed(cfg, *, rule, r, paper, asset_class="stock", days_ago=3,
            outcome="hit_target", symbol="HIST"):
    """One graded, closed trade in a lane."""
    from bot_program.models import AssetBotTrade
    from datetime import timedelta
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=asset_class, symbol=symbol, side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"),
        exit_price=Decimal("101"), status="CLOSED", outcome=outcome,
        realized_r=r, rule_name=rule, paper=paper,
        closed_at=timezone.now() - timedelta(days=days_ago),
    )


def _resolved_signal(rule, r, days_ago=3):
    from datetime import timedelta
    from signals.models import Signal
    sig = _signal("SIGHIST", rule=rule)
    Signal.objects.filter(pk=sig.pk).update(
        is_active=False, outcome="target_hit", realized_r=r,
        expired_at=timezone.now() - timedelta(days=days_ago))
    return sig


def _open_row(cfg, symbol, *, side="BUY", qty="10", entry="100",
              stop="95", vpu=1.0, paper=True, status="OPEN"):
    from bot_program.models import AssetBotTrade
    meta = {"value_per_unit": vpu}
    if stop is not None:
        meta["initial_stop_loss"] = float(stop)
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal(qty), entry_price=Decimal(entry), status=status,
        rule_name="open_rule", paper=paper, metadata=meta)


def _cand(bot, symbol="AAA", *, direction="BUY", rule="desk_rule",
          price=100.0, stop=95.0, target=115.0, qty=10.0, score=0.8,
          venue="paper", asset_class=None, horizon=168.0):
    """An EntryCandidate built by hand — the arithmetic under test never
    needs the broker, and building one through propose_entry would tie the
    desk's unit tests to the entry path's fixtures."""
    from bot_program.asset_engine.candidates import EntryCandidate
    per_unit = abs(price - stop)
    decision = SimpleNamespace(direction=direction, score=score,
                               reasons=[], rule_name=rule)
    return EntryCandidate(
        bot=bot, cfg_id=bot.cfg.id, user_id=bot.cfg.user_id, symbol=symbol,
        instrument_id=None, asset_class=asset_class or bot.cfg.asset_class,
        venue=venue, decision=decision, price=price, market_price=price,
        stop=stop, target=target, level_meta={}, cost_reason="",
        stage={"force_paper": venue == "paper", "stage": ""},
        sizing={"risk_fraction": 0.02, "risk_dollars": qty * per_unit,
                "notional_fraction": 0.1, "stop_widened": False,
                "value_per_unit": 1.0},
        qty_default=qty, per_unit_risk=per_unit,
        risk_dollars_default=qty * per_unit, notional_default=qty * price,
        value_per_unit=1.0, horizon_hours=horizon,
    )


def _bot(cfg):
    from bot_program.asset_engine import StockBot
    return StockBot(cfg)


# ── 1. expected R ───────────────────────────────────────────────────────────

class ExpectedRTests(TestCase):
    def setUp(self):
        self.user = _user("desk_ev")
        self.cfg = _config(self.user, mode="live")
        self.other = _config(self.user, name="Other", mode="live")
        self.bot = _bot(self.cfg)
        self.cand = _cand(self.bot, rule="ev_rule", venue="live")

    def test_own_live_lane_wins_over_the_fleet(self):
        from bot_program.capital_desk import expected_r
        for _ in range(12):
            _closed(self.cfg, rule="ev_rule", r=0.5, paper=False)
        for _ in range(40):
            _closed(self.other, rule="ev_rule", r=-0.9, paper=False)
        ev = expected_r(self.cand, user=self.user)
        self.assertEqual(ev["lane"], "config_live")
        self.assertEqual(ev["n"], 12)
        self.assertAlmostEqual(ev["e_r"], 0.5, places=6)
        self.assertTrue(ev["measured"])
        self.assertEqual(ev["window_days"], 180)

    def test_fleet_live_lane_when_the_config_is_thin(self):
        from bot_program.capital_desk import expected_r
        _closed(self.cfg, rule="ev_rule", r=9.0, paper=False)
        for _ in range(11):
            _closed(self.other, rule="ev_rule", r=0.2, paper=False)
        ev = expected_r(self.cand, user=self.user)
        self.assertEqual(ev["lane"], "user_live")
        # The one own-config fill is IN the wider lane's population.
        self.assertEqual(ev["n"], 12)

    def test_paper_lane_is_haircut(self):
        from bot_program.capital_desk import (
            expected_r, DESK_PAPER_HAIRCUT,
        )
        for _ in range(10):
            _closed(self.cfg, rule="ev_rule", r=1.0, paper=True)
        ev = expected_r(self.cand, user=self.user)
        self.assertEqual(ev["lane"], "fleet_paper")
        self.assertAlmostEqual(ev["e_r"], DESK_PAPER_HAIRCUT, places=6)
        self.assertIn("paper", ev["reason"])

    def test_signal_lane_is_the_last_resort_and_haircut(self):
        from bot_program.capital_desk import (
            expected_r, DESK_PAPER_HAIRCUT,
        )
        for _ in range(10):
            _resolved_signal("ev_rule", 2.0)
        ev = expected_r(self.cand, user=self.user)
        self.assertEqual(ev["lane"], "signal")
        self.assertEqual(ev["n"], 10)
        self.assertAlmostEqual(ev["e_r"], 2.0 * DESK_PAPER_HAIRCUT, places=6)

    def test_under_the_floor_is_unmeasured_and_ranked_on_conviction(self):
        from bot_program.capital_desk import expected_r, planned_net_rr
        for _ in range(9):
            _closed(self.cfg, rule="ev_rule", r=3.0, paper=False)
        ev = expected_r(self.cand, user=self.user)
        self.assertFalse(ev["measured"])
        self.assertIsNone(ev["e_r"], "an unmeasured lane has NO expected R")
        self.assertEqual(ev["lane"], "unmeasured")
        self.assertEqual(ev["n"], 0)
        self.assertAlmostEqual(
            ev["rank_key"], 0.8 * planned_net_rr(self.cand), places=9)
        self.assertGreater(ev["rank_key"], 0)

    def test_a_measured_key_is_never_multiplied_by_the_score(self):
        from bot_program.capital_desk import expected_r
        for _ in range(10):
            _closed(self.cfg, rule="ev_rule", r=0.4, paper=False)
        hot = _cand(self.bot, rule="ev_rule", venue="live", score=0.99)
        cold = _cand(self.bot, rule="ev_rule", venue="live", score=0.61)
        self.assertAlmostEqual(expected_r(hot, user=self.user)["rank_key"],
                               expected_r(cold, user=self.user)["rank_key"],
                               places=9)
        self.assertAlmostEqual(expected_r(hot, user=self.user)["rank_key"],
                               0.4, places=6)

    def test_win_rate_and_averages_keep_the_zero_r_rows(self):
        from bot_program.capital_desk import expected_r
        for r in (1.0, 2.0, -1.0, 0.0, 1.0, 0.0, -1.0, 1.0, 0.0, -1.0):
            _closed(self.cfg, rule="ev_rule", r=r, paper=False)
        ev = expected_r(self.cand, user=self.user)
        self.assertEqual(ev["n"], 10)
        self.assertAlmostEqual(ev["p_win"], 0.4, places=6)
        self.assertAlmostEqual(ev["avg_win_r"], 1.25, places=6)
        self.assertAlmostEqual(ev["avg_loss_r"], -1.0, places=6)
        self.assertAlmostEqual(ev["e_r"], 0.2, places=6)

    def test_a_decaying_rule_ranks_at_half(self):
        from bot_program.capital_desk import expected_r, DESK_DECAY_HAIRCUT
        for _ in range(10):
            _closed(self.cfg, rule="ev_rule", r=1.0, paper=False)
        with patch("signals.performance.decay_flag",
                   return_value={"is_decaying": True}):
            ev = expected_r(self.cand, user=self.user)
        self.assertTrue(ev["decaying"])
        self.assertAlmostEqual(ev["e_r"], 1.0, places=6,
                               msg="the expectancy itself is the evidence")
        self.assertAlmostEqual(ev["rank_key"], DESK_DECAY_HAIRCUT, places=6)

    def test_decay_flag_that_raises_is_not_decaying(self):
        from bot_program.capital_desk import expected_r
        with patch("signals.performance.decay_flag",
                   side_effect=RuntimeError("ledger down")):
            ev = expected_r(self.cand, user=self.user)
        self.assertFalse(ev["decaying"])

    def test_the_manual_lane_is_not_evidence_about_a_rule(self):
        from bot_program.capital_desk import expected_r
        for _ in range(30):
            _closed(self.cfg, rule="manual_take", r=2.0, paper=False)
        cand = _cand(self.bot, rule="manual_take", venue="live")
        ev = expected_r(cand, user=self.user)
        self.assertFalse(ev["measured"])
        self.assertEqual(ev["lane"], "unmeasured")


# ── 2. correlation ──────────────────────────────────────────────────────────

class CorrelationMatrixTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.user = _user("desk_corr")
        self.cfg = _config(self.user)

    def _bars(self, symbol, closes, *, minute_offset=0):
        from datetime import timedelta
        from market_data.models import PriceData
        inst = _instrument(symbol)
        start = timezone.now() - timedelta(hours=4 * (len(closes) + 1))
        start = start.replace(minute=0, second=0, microsecond=0)
        start -= timedelta(hours=start.hour % 4)
        for i, close in enumerate(closes):
            PriceData.objects.create(
                instrument=inst, timeframe="4h",
                timestamp=start + timedelta(hours=4 * i,
                                            minutes=minute_offset),
                open=Decimal(str(close)), high=Decimal(str(close)),
                low=Decimal(str(close)), close=Decimal(str(close)),
                volume=1, source="test")

    def test_perfectly_aligned_series_correlate_across_feed_minutes(self):
        from bot_program.capital_desk import correlation_matrix, rho_of
        walk = [100 + (i % 7) * 0.5 + i * 0.1 for i in range(80)]
        self._bars("CORRA", walk)
        # Second feed stamps the same 4h window three minutes late. Without
        # the bucket floor the inner join finds nothing at all.
        self._bars("CORRB", walk, minute_offset=3)
        m = correlation_matrix(self.user, ["CORRA", "CORRB"])
        self.assertIn(("CORRA", "CORRB"), m["measured"])
        self.assertAlmostEqual(rho_of(m, "CORRA", "CORRB"), 1.0, places=6)
        self.assertEqual(m["n_bars"][("CORRA", "CORRB")], 80)
        self.assertEqual(m["pairs_total"], 1)

    def test_under_sixty_shared_bars_is_unmeasured_not_uncorrelated(self):
        from bot_program.capital_desk import correlation_matrix, rho_of
        walk = [100 + i * 0.3 for i in range(40)]
        self._bars("CORRC", walk)
        self._bars("CORRD", walk)
        m = correlation_matrix(self.user, ["CORRC", "CORRD"])
        self.assertNotIn(("CORRC", "CORRD"), m["measured"])
        self.assertEqual(rho_of(m, "CORRC", "CORRD"), 0.0)
        self.assertEqual(m["n_bars"][("CORRC", "CORRD")], 40)
        self.assertEqual(m["matrix_pairs_measured"]
                         if "matrix_pairs_measured" in m else 0, 0)

    def test_the_open_book_joins_the_matrix_uninvited(self):
        from bot_program.capital_desk import correlation_matrix
        walk = [100 + (i % 5) * 0.4 + i * 0.2 for i in range(70)]
        self._bars("CORRE", walk)
        self._bars("CORRF", walk)
        _open_row(self.cfg, "CORRF")
        m = correlation_matrix(self.user, ["CORRE"])
        self.assertEqual(m["symbols"], ["CORRE", "CORRF"])
        self.assertIn(("CORRE", "CORRF"), m["measured"])

    def test_opposite_directions_flip_the_sign(self):
        from bot_program.capital_desk import correlation_matrix, bet_rho
        walk = [100 + (i % 6) * 0.6 + i * 0.15 for i in range(70)]
        self._bars("CORRG", walk)
        self._bars("CORRH", walk)
        m = correlation_matrix(self.user, ["CORRG", "CORRH"])
        same = bet_rho(m, "CORRG", "BUY", "CORRH", "BUY")
        opposed = bet_rho(m, "CORRG", "BUY", "CORRH", "SELL")
        self.assertAlmostEqual(same, 1.0, places=6)
        self.assertAlmostEqual(opposed, -1.0, places=6,
                               msg="an opposite bet on a correlated pair is "
                                   "a hedge, not concentration")

    def test_the_second_call_is_a_cache_hit(self):
        from bot_program.capital_desk import correlation_matrix
        walk = [100 + (i % 4) * 0.7 + i * 0.1 for i in range(70)]
        self._bars("CORRI", walk)
        self._bars("CORRJ", walk)
        first = correlation_matrix(self.user, ["CORRI", "CORRJ"])
        self.assertIn(("CORRI", "CORRJ"), first["measured"])
        # _floor_bucket runs once per bar and ONLY on the compute path, so a
        # second call that never touches it is a cache hit. (The newest-bar
        # query still runs: it is what the cache key is made of.)
        with patch("bot_program.capital_desk._floor_bucket") as bucket:
            bucket.side_effect = AssertionError("re-bucketed a cached matrix")
            second = correlation_matrix(self.user, ["CORRI", "CORRJ"])
        bucket.assert_not_called()
        self.assertEqual(second["measured"], first["measured"])
        self.assertEqual(second["n_bars"], first["n_bars"])


# ── 3. the open book ────────────────────────────────────────────────────────

class BookRiskTests(TestCase):
    def setUp(self):
        self.user = _user("desk_book")
        self.cfg = _config(self.user)

    def test_risk_at_stop_over_open_and_close_pending(self):
        from bot_program.capital_desk import book_risk
        _open_row(self.cfg, "BK1", qty="10", entry="100", stop="95")
        _open_row(self.cfg, "BK2", qty="4", entry="50", stop="45",
                  status="CLOSE_PENDING")
        book = book_risk(self.user, "paper")
        self.assertAlmostEqual(book["risk"], 10 * 5 + 4 * 5, places=6)
        self.assertEqual(book["n_open"], 2)
        self.assertEqual(book["unmeasured_open"], 0)

    def test_a_row_with_no_initial_stop_is_unmeasured_not_zero(self):
        from bot_program.capital_desk import book_risk
        _open_row(self.cfg, "BK3", qty="10", entry="100", stop=None)
        book = book_risk(self.user, "paper")
        self.assertEqual(book["risk"], 0.0)
        self.assertEqual(book["unmeasured_open"], 1)
        self.assertEqual(book["entries"], [])

    def test_the_manual_lane_is_exposure(self):
        from bot_program.capital_desk import book_risk
        manual = _config(self.user, name="manual", symbols=[])
        _open_row(manual, "BK4", qty="2", entry="200", stop="180")
        book = book_risk(self.user, "paper")
        self.assertAlmostEqual(book["risk"], 40.0, places=6)

    def test_value_per_unit_converts(self):
        from bot_program.capital_desk import book_risk
        _open_row(self.cfg, "BK5", qty="10000", entry="1.1000",
                  stop="1.0950", vpu=1.25)
        book = book_risk(self.user, "paper")
        self.assertAlmostEqual(book["risk"], 10000 * 0.005 * 1.25, places=4)

    def test_the_venues_never_mix(self):
        from bot_program.capital_desk import book_risk
        _open_row(self.cfg, "BK6", qty="10", entry="100", stop="95",
                  paper=True)
        _open_row(self.cfg, "BK7", qty="10", entry="100", stop="90",
                  paper=False)
        self.assertAlmostEqual(book_risk(self.user, "paper")["risk"], 50.0)
        self.assertAlmostEqual(book_risk(self.user, "live")["risk"], 100.0)


class VenueCapitalTests(TestCase):
    def setUp(self):
        self.user = _user("desk_cap")

    def test_the_denominator_is_the_enabled_pools_of_that_venue(self):
        from bot_program.capital_desk import venue_capital
        _config(self.user, name="A", mode="live", capital=Decimal("5000"))
        _config(self.user, name="B", mode="live", capital=Decimal("3000"))
        _config(self.user, name="C", mode="paper", capital=Decimal("9000"))
        _config(self.user, name="D", mode="live", capital=Decimal("7000"),
                enabled=False)
        self.assertAlmostEqual(venue_capital(self.user, "live"), 8000.0)
        # The live pools are in the PAPER denominator as well, because a live
        # config's paper-stage rules FILL on the paper venue. The two are
        # never summed with each other — they are two separate books.
        self.assertAlmostEqual(venue_capital(self.user, "paper"), 17000.0)
        # A disabled config is in neither: its capital cannot be spent.
        self.assertNotIn(7000.0, (venue_capital(self.user, "live"),
                                  venue_capital(self.user, "paper")))

    def test_a_live_only_fleet_still_has_a_paper_budget(self):
        """REGRESSION (adversarial review, 2026-09-12): the paper denominator
        summed mode='paper' configs alone, so an operator whose configs are
        ALL mode='live' — the live deployment's own shape — had a paper
        budget of 0.00 and every paper-venue candidate was displaced with
        'budget — 0.00 free'. A live config emits paper candidates:
        propose_entry files venue='paper' when `stage['force_paper']`, and
        stage_policy forces it for every rule with no RuleControl row and
        every rule still at the paper stage, which is nearly all of them.
        SHADOW hid the whole thing because phase 3 executes every candidate
        anyway; the day capital_desk_mode_live was switched on the fleet
        would have silently stopped taking paper-stage entries."""
        from bot_program.capital_desk import budget_for, venue_capital
        _config(self.user, name="LiveOnly1", mode="live",
                capital=Decimal("10000"))
        _config(self.user, name="LiveOnly2", mode="live",
                capital=Decimal("5000"))
        self.assertAlmostEqual(venue_capital(self.user, "paper"), 15000.0)
        paper = budget_for(self.user, "paper")
        self.assertAlmostEqual(paper["capital"], 15000.0, places=6)
        self.assertAlmostEqual(paper["budget"], 300.0, places=6)
        self.assertGreater(paper["budget"], 0.0,
                           "a live-only fleet must still be able to fill on "
                           "the paper venue its rules are forced onto")

    def test_a_paper_config_never_enlarges_the_live_budget(self):
        """The fix widened the PAPER denominator and nothing else. Live is
        still the live-mode configs alone: it is the only budget standing in
        front of real money, and capital that cannot reach the broker may not
        raise it. The live numbers below are exactly the ones this file
        asserted before the paper denominator changed."""
        from bot_program.capital_desk import budget_for, venue_capital
        _config(self.user, name="L3", mode="live", capital=Decimal("10000"))
        _config(self.user, name="P3", mode="paper", capital=Decimal("90000"))
        self.assertAlmostEqual(venue_capital(self.user, "live"), 10000.0)
        with patch("bot_program.capital_truth.equity_drawdown",
                   return_value=None):
            live = budget_for(self.user, "live")
        self.assertAlmostEqual(live["capital"], 10000.0, places=6)
        self.assertAlmostEqual(live["budget"], 200.0, places=6)
        # And the paper book is the whole enabled fleet, live pool included.
        self.assertAlmostEqual(venue_capital(self.user, "paper"), 100000.0)
        self.assertAlmostEqual(budget_for(self.user, "paper")["budget"],
                               2000.0, places=6)

    def test_a_paper_candidate_from_a_live_config_is_not_displaced(self):
        """The symptom the denominator produced: an entry whose risk fits the
        budget many times over, refused for 'budget — 0.00 free' because the
        venue it was forced onto had no capital behind it at all."""
        from bot_program.capital_desk import plan_for
        cfg = _config(self.user, name="LiveCfg", mode="live",
                      capital=Decimal("10000"))
        cand = _cand(_bot(cfg), "PAPER1", qty=10.0, rule="paper_stage_rule",
                     venue="paper")
        out = plan_for(self.user, "paper", [cand])
        self.assertAlmostEqual(float(out["plan"].budget), 200.0, places=2)
        decision = out["decisions"][0][0]
        self.assertEqual(decision.outcome, "chosen")
        self.assertNotIn("budget —", decision.reason)

    def test_no_enabled_config_is_zero_on_both_venues_and_writes_no_plan(self):
        """Both denominators are 0 when nothing is enabled, and the fleet
        pass writes NOTHING: run_all_asset_bots builds its per-user work from
        the enabled configs, so a user with none is never reached and there
        is no plan to write. That is the existing behaviour and the fix must
        not turn an empty fleet into a budgeted one."""
        from bot_program.asset_engine.runner import run_all_asset_bots
        from bot_program.capital_desk import budget_for, venue_capital
        from bot_program.models import DeskPlan
        _config(self.user, name="Off1", mode="live", capital=Decimal("10000"),
                enabled=False)
        _config(self.user, name="Off2", mode="paper",
                capital=Decimal("20000"), enabled=False)
        with patch("bot_program.capital_truth.equity_drawdown",
                   return_value=None):
            for venue in ("live", "paper"):
                self.assertEqual(venue_capital(self.user, venue), 0.0)
                info = budget_for(self.user, venue)
                self.assertEqual(info["capital"], 0.0)
                self.assertEqual(info["budget"], 0.0)
        _component("pipeline_capital_desk")
        with patch(ROUTER, return_value=_client()):
            run_all_asset_bots()
        self.assertEqual(DeskPlan.objects.filter(user=self.user).count(), 0)

    def test_the_plan_stores_the_marginal_total_the_chooser_spent(self):
        """REGRESSION (adversarial review, 2026-09-12): DeskPlan stored only
        `new_risk_chosen`, the RAW sum of risk-at-stop, while `choose` spends
        the budget in MARGINAL risk. /desk/ then drew the raw sum against a
        budget consumed in the other unit and could report 30 of 78 spent on
        a tick the chooser had stopped at the budget's own edge."""
        from bot_program.capital_desk import plan_for
        cfg = _config(self.user, name="MarginalCfg", mode="paper",
                      capital=Decimal("100000"))
        bot = _bot(cfg)
        cands = [_cand(bot, "MG1", qty=10.0, rule="mg_a"),
                 _cand(bot, "MG2", qty=10.0, rule="mg_b")]
        out = plan_for(self.user, "paper", cands)
        plan = out["plan"]
        # Two uncorrelated 50-dollar bets: the first costs 50 of marginal
        # risk, the second sqrt(2)x50 - 50 = 20.71. The chooser spent 70.71;
        # the account has 100.00 at stake if both stops are hit.
        self.assertAlmostEqual(float(plan.new_risk_chosen), 100.0, places=2)
        self.assertAlmostEqual(float(plan.new_risk_marginal),
                               50 * (2 ** 0.5), places=2)
        spent = sum(float(d.marginal_risk) * float(d.size_mult)
                    for d, _c in out["decisions"]
                    if d.outcome in ("chosen", "resized"))
        self.assertAlmostEqual(float(plan.new_risk_marginal), spent, places=2)
        self.assertNotEqual(float(plan.new_risk_marginal),
                            float(plan.new_risk_chosen),
                            "the two units must not be the same number here, "
                            "or this test proves nothing")

    def test_the_governor_shrinks_the_live_budget_only(self):
        from bot_program.capital_desk import budget_for
        _config(self.user, name="L", mode="live", capital=Decimal("10000"))
        _config(self.user, name="P", mode="paper", capital=Decimal("10000"))
        reading = {"drawdown_pct": 0.125, "value": 1.0, "hwm": 2.0}
        with patch("bot_program.capital_truth.equity_drawdown",
                   return_value=reading):
            live = budget_for(self.user, "live")
            paper = budget_for(self.user, "paper")
        self.assertLess(live["governor"], 1.0)
        self.assertAlmostEqual(live["budget"], 200.0 * live["governor"],
                               places=6)
        self.assertEqual(paper["governor"], 1.0)
        # 2% of both pools: the paper venue is backed by the paper config AND
        # the live one, whose paper-stage rules fill there.
        self.assertAlmostEqual(paper["budget"], 400.0, places=6)

    def test_no_reading_means_no_governor(self):
        from bot_program.capital_desk import budget_for
        _config(self.user, name="L2", mode="live", capital=Decimal("10000"))
        with patch("bot_program.capital_truth.equity_drawdown",
                   return_value=None):
            info = budget_for(self.user, "live")
        self.assertEqual(info["governor"], 1.0)
        self.assertAlmostEqual(info["budget"], 200.0, places=6)

    def test_the_open_book_is_taken_off_the_top(self):
        from bot_program.capital_desk import budget_for
        cfg = _config(self.user, name="P2", mode="paper",
                      capital=Decimal("10000"))
        _open_row(cfg, "BUD1", qty="10", entry="100", stop="95")
        info = budget_for(self.user, "paper")
        self.assertAlmostEqual(info["gross"], 200.0, places=6)
        self.assertAlmostEqual(info["book_risk"], 50.0, places=6)
        self.assertAlmostEqual(info["budget"], 150.0, places=6)


# ── 4. the choice ───────────────────────────────────────────────────────────

class ChooseTests(TestCase):
    def setUp(self):
        self.user = _user("desk_choose")
        self.cfg = _config(self.user, name="Chooser")
        self.bot = _bot(self.cfg)
        self.empty = {"rho": {}, "measured": set(), "n_bars": {},
                      "symbols": [], "pairs_total": 0}
        self.book = {"risk": 0.0, "entries": []}

    def _ev(self, key, *, measured=True, lane="config_live", n=12):
        return {"e_r": key if measured else None, "p_win": 0.5,
                "avg_win_r": 1.0, "avg_loss_r": -1.0, "n": n if measured else 0,
                "lane": lane if measured else "unmeasured",
                "window_days": 180, "measured": measured, "decaying": False,
                "reason": "", "rank_key": key}

    def _choose(self, cands, evs, *, budget, book=None, rho=None, gates=None):
        from bot_program.capital_desk import choose
        evidence = {id(c): e for c, e in zip(cands, evs)}
        return choose(cands, user=self.user, venue="paper",
                      book=book or self.book, rho=rho or self.empty,
                      budget=budget, evidence=evidence, gates=gates)

    def test_everything_fits_and_everything_is_chosen(self):
        a = _cand(self.bot, "FIT1", qty=10.0, rule="r_a")   # 50 of risk
        b = _cand(self.bot, "FIT2", qty=4.0, rule="r_b")    # 20 of risk
        plan = self._choose([a, b], [self._ev(0.5), self._ev(0.3)],
                            budget=500.0)
        self.assertEqual(plan["n_chosen"], 2)
        self.assertEqual(plan["n_displaced"], 0)
        self.assertAlmostEqual(plan["new_risk_chosen"], 70.0, places=6)
        # RANKED ON R PER UNIT OF RISK, not on R. FIT2's 0.3R costs 20 of
        # budget (0.015 per dollar); FIT1's 0.5R costs 50 (0.010). The
        # smaller, cheaper bet is offered the money first — that is the
        # "maximise gains" half of the ask doing its work, and it is why a
        # ladder ordered by expected R alone would be the wrong picture.
        ranks = [(d["cand"].symbol, d["rank"]) for d in plan["decisions"]]
        self.assertEqual(ranks, [("FIT2", 1), ("FIT1", 2)])

    def test_a_partial_fit_is_resized_never_clamped_up(self):
        # The share caps are off for this one: with a budget this tight they
        # would do the displacing and the budget mechanic under test would
        # never be reached. Their own behaviour is pinned below.
        a = _cand(self.bot, "RS1", qty=10.0, rule="r_a")   # 50 of risk
        b = _cand(self.bot, "RS2", qty=10.0, rule="r_b")   # 50 of risk
        with patch("bot_program.capital_desk.DESK_MAX_RULE_SHARE", 10.0), \
                patch("bot_program.capital_desk.DESK_MAX_CLASS_SHARE", 10.0):
            plan = self._choose([a, b], [self._ev(0.9), self._ev(0.8)],
                                budget=65.0)
        by_symbol = {d["cand"].symbol: d for d in plan["decisions"]}
        self.assertEqual(by_symbol["RS1"]["outcome"], "chosen")
        self.assertEqual(by_symbol["RS1"]["size_mult"], 1.0)
        self.assertEqual(by_symbol["RS2"]["outcome"], "resized")
        # Uncorrelated, so the second bet's MARGINAL risk is sqrt(2)x50 - 50,
        # not 50: diversification is what is left of the budget buying more
        # than the raw arithmetic says it should.
        self.assertAlmostEqual(by_symbol["RS2"]["marginal_risk"],
                               50 * (2 ** 0.5) - 50, places=6)
        self.assertAlmostEqual(by_symbol["RS2"]["size_mult"],
                               15.0 / (50 * (2 ** 0.5) - 50), places=6)
        self.assertLess(by_symbol["RS2"]["size_mult"], 1.0)

    def test_below_the_quarter_floor_it_is_displaced(self):
        from bot_program.capital_desk import DESK_MIN_MULT
        a = _cand(self.bot, "MIN1", qty=10.0, rule="r_a")
        b = _cand(self.bot, "MIN2", qty=10.0, rule="r_b")
        with patch("bot_program.capital_desk.DESK_MAX_RULE_SHARE", 10.0), \
                patch("bot_program.capital_desk.DESK_MAX_CLASS_SHARE", 10.0):
            plan = self._choose([a, b], [self._ev(0.9), self._ev(0.8)],
                                budget=52.0)
        by_symbol = {d["cand"].symbol: d for d in plan["decisions"]}
        self.assertEqual(by_symbol["MIN2"]["outcome"], "displaced")
        self.assertIn("budget", by_symbol["MIN2"]["reason"])
        self.assertIn(f"{DESK_MIN_MULT:.2f}", by_symbol["MIN2"]["reason"])

    def test_a_cap_never_bites_on_the_first_entry_of_a_bucket(self):
        """A 2% budget and a 2% entry: the cap must not switch the fleet off.

        Measured against the budget, ONE entry is 100% of a one-config
        fleet's allowance. A concentration cap that refused it would read on
        the page as a working limit while actually meaning "this bot never
        trades again".
        """
        cand = _cand(self.bot, "SOLO", qty=10.0, rule="lonely")
        plan = self._choose([cand], [self._ev(0.5)], budget=50.0)
        self.assertEqual(plan["decisions"][0]["outcome"], "chosen")
        self.assertEqual(plan["n_chosen"], 1)

    def test_the_rule_share_cap_bites(self):
        cands = [_cand(self.bot, f"RL{i}", qty=10.0, rule="one_rule")
                 for i in range(4)]
        plan = self._choose(cands, [self._ev(0.9 - i * 0.1) for i in range(4)],
                            budget=250.0)
        # 40% of 250 is 100 — two 50-dollar entries, no more.
        self.assertEqual(plan["n_chosen"], 2)
        refused = [d for d in plan["decisions"] if d["outcome"] == "displaced"]
        self.assertEqual(len(refused), 2)
        for row in refused:
            self.assertIn("rule_share", row["reason"])
            self.assertIn("one_rule", row["reason"])

    def test_the_class_share_cap_bites(self):
        cands = [_cand(self.bot, f"CL{i}", qty=10.0, rule=f"rule_{i}")
                 for i in range(5)]
        plan = self._choose(cands, [self._ev(0.9 - i * 0.05) for i in range(5)],
                            budget=250.0)
        # 60% of 250 is 150 — three entries of 50 in one class.
        self.assertEqual(plan["n_chosen"], 3)
        refused = [d for d in plan["decisions"] if d["outcome"] == "displaced"]
        self.assertTrue(all("class_share" in d["reason"] for d in refused))

    def test_the_persona_share_cap_bites(self):
        """A trading STYLE is a bucket the other two caps cannot see: four
        entries on four different rules, all taken by a scalp book, are one
        bet on intraday mean reversion continuing to work, and both the
        rule cap (one rule each) and the class cap (60%) wave it through.

        50% of 250 is 125 — two entries of 50, and the third is refused by
        name (2026-09-12).
        """
        from bot_program.capital_desk import DESK_MAX_PERSONA_SHARE
        cfg = _config(self.user, name="Scalper",
                      extras={"persona": "scalp"})
        bot = _bot(cfg)
        cands = [_cand(bot, f"PS{i}", qty=10.0, rule=f"rule_{i}")
                 for i in range(4)]
        plan = self._choose(cands, [self._ev(0.9 - i * 0.05) for i in range(4)],
                            budget=250.0)
        self.assertEqual(plan["n_chosen"], 2)
        refused = [d for d in plan["decisions"] if d["outcome"] == "displaced"]
        self.assertEqual(len(refused), 2)
        for row in refused:
            self.assertIn("persona_share", row["reason"])
            self.assertIn("scalp", row["reason"])
            self.assertIn(f"{DESK_MAX_PERSONA_SHARE * 100:.0f}%",
                          row["reason"])

    def test_a_config_wearing_no_persona_is_never_refused_by_that_cap(self):
        """There is nothing to concentrate: a fleet that has never heard of
        personalities chooses exactly as it did before they existed — the
        class cap does the displacing, at 60% and not at 50%."""
        cands = [_cand(self.bot, f"NP{i}", qty=10.0, rule=f"rule_{i}")
                 for i in range(4)]
        plan = self._choose(cands, [self._ev(0.9 - i * 0.05) for i in range(4)],
                            budget=250.0)
        self.assertEqual(plan["n_chosen"], 3)
        reasons = " ".join(d["reason"] for d in plan["decisions"])
        self.assertNotIn("persona_share", reasons)

    def test_one_expression_per_bet_across_configs(self):
        other = _config(self.user, name="Second")
        cand_a = _cand(self.bot, "DUP", qty=10.0)
        cand_b = _cand(_bot(other), "DUP", qty=10.0)
        plan = self._choose(
            [cand_a, cand_b],
            [self._ev(0.2, measured=False, lane="unmeasured"),
             self._ev(0.1, measured=True)],
            budget=500.0)
        by_cfg = {d["cand"].cfg_id: d for d in plan["decisions"]}
        self.assertEqual(by_cfg[other.id]["outcome"], "chosen",
                         "the measured lane keeps the bet even on a lower key")
        self.assertEqual(by_cfg[self.cfg.id]["outcome"], "duplicate")
        self.assertIn("duplicate", by_cfg[self.cfg.id]["reason"])
        self.assertEqual(plan["n_duplicate"], 1)

    def test_a_config_with_no_slot_left_is_refused(self):
        tight = _config(self.user, name="Tight", max_concurrent_positions=1)
        _open_row(tight, "HELD")
        cand = _cand(_bot(tight), "SLOT1", qty=1.0)
        plan = self._choose([cand], [self._ev(0.9)], budget=500.0)
        row = plan["decisions"][0]
        self.assertEqual(row["outcome"], "displaced")
        self.assertIn("config_halted", row["reason"])

    def test_a_closed_gate_at_plan_time_is_refused(self):
        cand = _cand(self.bot, "GATE1", qty=1.0)
        plan = self._choose([cand], [self._ev(0.9)], budget=500.0,
                            gates={self.cfg.id: (False, "daily loss reached")})
        row = plan["decisions"][0]
        self.assertEqual(row["outcome"], "displaced")
        self.assertIn("daily loss reached", row["reason"])

    def test_correlation_makes_the_second_bet_cost_more(self):
        from bot_program.capital_desk import choose
        a = _cand(self.bot, "CA", qty=10.0, rule="r_a")
        b = _cand(self.bot, "CB", qty=10.0, rule="r_b")
        evs = {id(a): self._ev(0.5), id(b): self._ev(0.4)}
        loose = {"rho": {("CA", "CB"): 0.0}, "measured": {("CA", "CB")},
                 "n_bars": {}, "symbols": ["CA", "CB"], "pairs_total": 1}
        tight = dict(loose, rho={("CA", "CB"): 0.95})
        plan_loose = choose([a, b], user=self.user, venue="paper",
                            book=self.book, rho=loose, budget=500.0,
                            evidence=evs)
        plan_tight = choose([a, b], user=self.user, venue="paper",
                            book=self.book, rho=tight, budget=500.0,
                            evidence=evs)
        second_loose = plan_loose["decisions"][1]["marginal_risk"]
        second_tight = plan_tight["decisions"][1]["marginal_risk"]
        self.assertLess(second_loose, second_tight)
        self.assertAlmostEqual(plan_tight["decisions"][1]["corr_max"], 0.95,
                               places=6)

    def test_an_opposite_bet_on_a_correlated_pair_is_nearly_free(self):
        from bot_program.capital_desk import choose
        a = _cand(self.bot, "HA", qty=10.0, rule="r_a")
        b = _cand(self.bot, "HB", qty=10.0, rule="r_b", direction="SELL")
        evs = {id(a): self._ev(0.5), id(b): self._ev(0.4)}
        tight = {"rho": {("HA", "HB"): 0.95}, "measured": {("HA", "HB")},
                 "n_bars": {}, "symbols": ["HA", "HB"], "pairs_total": 1}
        plan = choose([a, b], user=self.user, venue="paper", book=self.book,
                      rho=tight, budget=500.0, evidence=evs)
        self.assertLess(plan["decisions"][1]["marginal_risk"], 20.0)
        self.assertEqual(plan["n_chosen"], 2)

    def test_the_open_book_eats_the_budget_before_anyone_is_ranked(self):
        cand = _cand(self.bot, "BOOKED", qty=10.0)
        plan = self._choose([cand], [self._ev(0.9)], budget=10.0,
                            book={"risk": 190.0, "entries": []})
        self.assertEqual(plan["decisions"][0]["outcome"], "displaced")
        self.assertIn("budget", plan["decisions"][0]["reason"])


# ── 5. the two-phase pass ───────────────────────────────────────────────────

class TwoPhaseRunnerTests(TestCase):
    """The fleet pass, against the legacy loop it replaces."""

    def setUp(self):
        self.user = _user("desk_runner")
        self.cfg_a = _config(self.user, name="A Bot", symbols=["RUNA"])
        self.cfg_b = _config(self.user, name="B Bot", symbols=["RUNB"])
        _signal("RUNA", rule="run_rule_a")
        _signal("RUNB", rule="run_rule_b")

    def _legacy_rows(self):
        """What the loop does with the desk switched off."""
        from bot_program.asset_engine.runner import run_all_asset_bots
        from bot_program.models import AssetBotTrade
        with patch(ROUTER, return_value=_client()):
            run_all_asset_bots()
        rows = sorted((t.symbol, str(t.qty), str(t.entry_price))
                      for t in AssetBotTrade.objects.all())
        AssetBotTrade.objects.all().delete()
        return rows

    def test_component_off_is_the_legacy_loop_and_writes_no_desk_rows(self):
        from bot_program.asset_engine.runner import run_all_asset_bots
        from bot_program.models import AssetBotTrade, DeskPlan, DeskDecision
        with patch(ROUTER, return_value=_client()):
            out = run_all_asset_bots()
        self.assertEqual(AssetBotTrade.objects.count(), 2)
        self.assertEqual(DeskPlan.objects.count(), 0)
        self.assertEqual(DeskDecision.objects.count(), 0)
        self.assertNotIn("desk", out)

    def test_shadow_runs_the_fleet_exactly_as_the_legacy_loop(self):
        from bot_program.asset_engine.runner import run_all_asset_bots
        from bot_program.models import AssetBotTrade, DeskPlan, DeskDecision
        legacy = self._legacy_rows()

        _component("pipeline_capital_desk")
        with patch(ROUTER, return_value=_client()):
            run_all_asset_bots()
        desked = sorted((t.symbol, str(t.qty), str(t.entry_price))
                        for t in AssetBotTrade.objects.all())
        self.assertEqual(desked, legacy,
                         "shadow must change nothing the fleet does")

        plan = DeskPlan.objects.get()
        self.assertEqual(plan.mode, "shadow")
        self.assertEqual(plan.venue, "paper")
        self.assertEqual(plan.n_candidates, 2)
        self.assertEqual(DeskDecision.objects.count(), 2)
        for trade in AssetBotTrade.objects.all():
            meta = trade.metadata or {}
            self.assertEqual(meta["desk_plan_id"], plan.pk)
            self.assertEqual(meta["desk_mode"], "shadow")
            self.assertEqual(meta["desk_size_mult"], 1.0)
            self.assertIn("desk_lane", meta)
            self.assertIn("desk_risk_dollars_default", meta)
        linked = DeskDecision.objects.exclude(trade=None).count()
        self.assertEqual(linked, 2)

    def test_shadow_executes_even_what_it_displaced(self):
        """The counterfactual only grades if the fleet actually ran."""
        from bot_program.asset_engine.runner import run_all_asset_bots
        from bot_program.models import AssetBotTrade, DeskDecision
        _component("pipeline_capital_desk")
        # A budget of nothing displaces every candidate.
        with patch("bot_program.capital_desk.venue_capital",
                   return_value=0.0), \
                patch(ROUTER, return_value=_client()):
            run_all_asset_bots()
        self.assertEqual(
            set(DeskDecision.objects.values_list("outcome", flat=True)),
            {"displaced"})
        self.assertEqual(AssetBotTrade.objects.count(), 2,
                         "in shadow the fleet is untouched")
        for decision in DeskDecision.objects.all():
            self.assertGreater(float(decision.price), 0)
            self.assertIsNotNone(decision.stop)
            self.assertIsNotNone(decision.target)
            self.assertGreater(decision.horizon_hours, 0)

    def test_live_skips_the_displaced_and_logs_one_call(self):
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.runner import run_all_asset_bots
        from bot_program.models import AssetBotTrade, DeskPlan
        _component("pipeline_capital_desk")
        _component("capital_desk_mode_live")
        with patch("bot_program.capital_desk.venue_capital",
                   return_value=0.0), \
                patch("ai_agents.calibration.log_direction_prediction") as pred, \
                patch(ROUTER, return_value=_client()):
            run_all_asset_bots()
        self.assertEqual(AssetBotTrade.objects.count(), 0,
                         "in live the plan is obeyed")
        plan = DeskPlan.objects.get()
        self.assertEqual(plan.mode, "live")
        self.assertEqual(pred.call_count, 2)
        agents = {c.args[0] for c in pred.call_args_list}
        self.assertEqual(agents, {f"desk:{self.cfg_a.id}",
                                  f"desk:{self.cfg_b.id}"})
        for call in pred.call_args_list:
            self.assertLessEqual(len(call.args[0]), 50)
            self.assertIn("desk:displaced", call.kwargs["notes"])
        for cfg in (self.cfg_a, self.cfg_b):
            cfg.refresh_from_db()
            note = list(skips.last_by_symbol(cfg).values())[0]
            self.assertEqual(note["code"], skips.DESK_DISPLACED)
            self.assertIn(f"plan #{plan.pk}", note["detail"])

    def test_live_carries_the_multiplier_into_the_row(self):
        from bot_program.asset_engine.runner import run_all_asset_bots
        from bot_program.models import AssetBotTrade, DeskDecision
        _component("pipeline_capital_desk")
        _component("capital_desk_mode_live")
        legacy = {sym: (float(qty), float(px))
                  for sym, qty, px in self._legacy_rows()}
        # The stop is the config's 1.5%, so one entry's risk at stop is
        # qty x price x 0.015. A budget of 1.2 of those fits the first whole
        # and cuts the second.
        one = min(qty * px * 0.015 for qty, px in legacy.values())
        budget = 1.2 * one

        def fake_budget(user, venue, **kw):
            from bot_program.capital_desk import book_risk
            book = book_risk(user, venue)
            return {"budget": budget - book["risk"], "gross": budget,
                    "capital": 0.0, "book_risk": book["risk"],
                    "unmeasured_open": 0, "n_open": book["n_open"],
                    "entries": book["entries"], "governor": 1.0,
                    "drawdown_pct": None, "reason": "test"}

        with patch("bot_program.capital_desk.budget_for", fake_budget), \
                patch("bot_program.capital_desk.DESK_MAX_RULE_SHARE", 10.0), \
                patch("bot_program.capital_desk.DESK_MAX_CLASS_SHARE", 10.0), \
                patch(ROUTER, return_value=_client()):
            run_all_asset_bots()

        rows = {t.symbol: t for t in AssetBotTrade.objects.all()}
        resized = DeskDecision.objects.filter(outcome="resized").first()
        self.assertIsNotNone(resized, "one candidate must have been cut")
        self.assertLess(resized.size_mult, 1.0)
        self.assertGreaterEqual(resized.size_mult, 0.25)
        trade = rows[resized.symbol]
        self.assertLess(float(trade.qty), legacy[resized.symbol][0],
                        "the desk may only ever shrink a size")
        self.assertAlmostEqual(
            float(trade.metadata["desk_size_mult"]), resized.size_mult,
            places=6)
        self.assertEqual(float(resized.qty_final or 0), float(trade.qty))
        self.assertEqual(trade.metadata["desk_decision_id"], resized.pk)
        chosen = DeskDecision.objects.filter(outcome="chosen").first()
        self.assertIsNotNone(chosen)
        self.assertEqual(float(rows[chosen.symbol].qty),
                         legacy[chosen.symbol][0])

    def test_chosen_then_refused_when_the_gate_flips(self):
        from bot_program.asset_engine.runner import run_all_asset_bots
        from bot_program.models import AssetBotTrade, DeskDecision
        _component("pipeline_capital_desk")
        _component("capital_desk_mode_live")

        from bot_program.asset_engine.base import AssetBot
        calls = {"n": 0}
        real = AssetBot.can_open_new

        def flaky(self):
            calls["n"] += 1
            # Open for the proposal phase and the plan, shut afterwards.
            if calls["n"] > 4:
                return (False, "daily loss ceiling reached")
            return real(self)

        with patch.object(AssetBot, "can_open_new", flaky), \
                patch(ROUTER, return_value=_client()):
            run_all_asset_bots()
        self.assertEqual(AssetBotTrade.objects.count(), 0)
        outcomes = set(DeskDecision.objects.values_list("outcome", flat=True))
        self.assertEqual(outcomes, {"chosen_then_refused"})
        self.assertIn("daily loss",
                      DeskDecision.objects.first().reason)

    def test_a_desk_that_raises_fails_open(self):
        from bot_program.asset_engine.runner import run_all_asset_bots
        from bot_program.models import AssetBotTrade, DeskPlan
        _component("pipeline_capital_desk")
        _component("capital_desk_mode_live")
        with patch("bot_program.capital_desk.plan_for",
                   side_effect=RuntimeError("matrix exploded")), \
                patch(ROUTER, return_value=_client()):
            run_all_asset_bots()
        self.assertEqual(AssetBotTrade.objects.count(), 2,
                         "a broken desk must never stop the bots")
        plan = DeskPlan.objects.get()
        self.assertIn("matrix exploded", plan.error)
        self.assertEqual(plan.n_candidates, 0)

    def test_the_venues_never_share_a_plan(self):
        from bot_program.asset_engine.runner import run_all_asset_bots
        from bot_program.models import DeskPlan
        from signals.models import RuleControl
        RuleControl.objects.create(
            rule_name="run_rule_b", status="active",
            promotion_stage="live_full", stage_entered_at=timezone.now())
        self.cfg_b.mode = "live"
        self.cfg_b.save(update_fields=["mode"])
        _component("pipeline_capital_desk")
        with patch(ROUTER, return_value=_client()):
            run_all_asset_bots()
        venues = sorted(DeskPlan.objects.values_list("venue", flat=True))
        self.assertEqual(venues, ["live", "paper"])
        for plan in DeskPlan.objects.all():
            self.assertEqual(plan.n_candidates, 1)

    def test_the_desk_memory_does_not_re_decide_a_displacement(self):
        from bot_program.asset_engine.runner import run_all_asset_bots
        from bot_program.models import DeskDecision, AssetBotTrade
        _component("pipeline_capital_desk")
        _component("capital_desk_mode_live")
        with patch("bot_program.capital_desk.venue_capital",
                   return_value=0.0), \
                patch("ai_agents.calibration.log_direction_prediction"), \
                patch(ROUTER, return_value=_client()):
            run_all_asset_bots()
            first = DeskDecision.objects.count()
            run_all_asset_bots()
        self.assertEqual(DeskDecision.objects.count(), first,
                         "a remembered displacement writes no second row")
        self.assertEqual(AssetBotTrade.objects.count(), 0)


class ShadowChangesNothingTests(TestCase):
    """The adversarial review's first question: in SHADOW, is the row the
    fleet writes byte-for-byte the row it wrote before, and does anything
    the desk does reach the fleet?"""

    def setUp(self):
        self.user = _user("desk_shadow")
        self.cfg_a = _config(self.user, name="Shadow A", symbols=["SHDW1"])
        self.cfg_b = _config(self.user, name="Shadow B", symbols=["SHDW2"])
        _signal("SHDW1", rule="shadow_rule_a")
        _signal("SHDW2", rule="shadow_rule_b")

    @staticmethod
    def _rows():
        from bot_program.models import AssetBotTrade
        return {t.symbol: t for t in AssetBotTrade.objects.all()}

    def test_the_metadata_is_the_legacy_metadata_plus_the_desk_keys(self):
        """Every key the entry path wrote before is still there, with the
        same value, and the ONLY additions are the eight desk_* keys. A
        shadow that quietly changed a stop, a risk fraction or a cost check
        would be grading a counterfactual against a fleet it had already
        altered."""
        from bot_program.asset_engine.runner import run_all_asset_bots
        from bot_program.models import AssetBotTrade

        with patch(ROUTER, return_value=_client()):
            run_all_asset_bots()
        legacy = {sym: (row.side, row.qty, row.entry_price, row.stop_loss,
                        row.take_profit, row.paper, row.rule_name,
                        dict(row.metadata or {}))
                  for sym, row in self._rows().items()}
        self.assertEqual(set(legacy), {"SHDW1", "SHDW2"})
        AssetBotTrade.objects.all().delete()

        _component("pipeline_capital_desk")
        with patch(ROUTER, return_value=_client()):
            run_all_asset_bots()
        desked = self._rows()
        self.assertEqual(set(desked), set(legacy))
        for sym, row in desked.items():
            meta = dict(row.metadata or {})
            added = sorted(k for k in meta if k.startswith("desk_"))
            self.assertEqual(len(added), 8, f"{sym}: {added}")
            for key in added:
                meta.pop(key)
            self.assertEqual(
                (row.side, row.qty, row.entry_price, row.stop_loss,
                 row.take_profit, row.paper, row.rule_name, meta),
                legacy[sym],
                f"{sym}: shadow changed the row the fleet wrote")

    def test_a_displaced_decision_is_never_relabelled_after_the_fact(self):
        """REGRESSION (adversarial review, 2026-09-12): in SHADOW every
        candidate executes, displaced ones included, and the executing pass
        marked ANY decision whose execute returned nothing
        'chosen_then_refused'. That erased the displacement — the outcome
        the counterfactual resolver keys off — so the row would never be
        walked, never enter the default set, and the plan's own n_displaced
        would disagree with its rows on the ladder."""
        from bot_program.asset_engine import StockBot
        from bot_program.asset_engine.runner import run_all_asset_bots
        from bot_program.models import DeskDecision, DeskPlan

        _component("pipeline_capital_desk")
        with patch("bot_program.capital_desk.venue_capital",
                   return_value=0.0), \
                patch.object(StockBot, "execute_entry", return_value=None), \
                patch(ROUTER, return_value=_client()):
            run_all_asset_bots()

        outcomes = sorted(DeskDecision.objects.values_list("outcome",
                                                           flat=True))
        self.assertEqual(outcomes, ["displaced", "displaced"])
        plan = DeskPlan.objects.get()
        self.assertEqual(
            plan.n_displaced,
            DeskDecision.objects.filter(outcome="displaced").count(),
            "the plan's counts must agree with its own rows")

    def test_one_bot_raising_on_execute_does_not_stop_the_fleet(self):
        """REGRESSION (adversarial review, 2026-09-12): `tick()` wrapped
        every scan_symbol in a try, so a bot that threw on one entry cost
        that entry and nothing else. Unwrapped in the desked pass, the same
        exception escaped the per-user loop, the fleet pass and the Celery
        task — one bad symbol would stop every remaining config of every
        remaining user, in SHADOW as well as live."""
        from bot_program.asset_engine import StockBot
        from bot_program.asset_engine.runner import run_all_asset_bots
        from bot_program.models import AssetBotTrade, DeskDecision

        _component("pipeline_capital_desk")
        real = StockBot.execute_entry

        def boom(bot, cand, *, size_mult=1.0):
            if cand.symbol == "SHDW1":
                raise RuntimeError("the broker client exploded")
            return real(bot, cand, size_mult=size_mult)

        with patch.object(StockBot, "execute_entry", boom), \
                patch(ROUTER, return_value=_client()):
            out = run_all_asset_bots()

        self.assertEqual(out["status"], "ok")
        self.assertEqual(
            [t.symbol for t in AssetBotTrade.objects.all()], ["SHDW2"],
            "the second bot must still have traded")
        wrecked = DeskDecision.objects.get(symbol="SHDW1")
        self.assertEqual(wrecked.outcome, "chosen_then_refused")


class SingleConfigTickIsUntouchedTests(TestCase):
    def test_run_now_still_ticks_one_config_the_old_way(self):
        from bot_program.asset_engine.runner import run_asset_bot_tick
        from bot_program.models import AssetBotTrade, DeskPlan
        user = _user("desk_one")
        cfg = _config(user, name="One", symbols=["ONE1"])
        _signal("ONE1", rule="one_rule")
        _component("pipeline_capital_desk")
        _component("capital_desk_mode_live")
        with patch(ROUTER, return_value=_client()):
            out = run_asset_bot_tick(cfg.id)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(AssetBotTrade.objects.count(), 1)
        self.assertEqual(DeskPlan.objects.count(), 0,
                         "a single tick is not a fleet — nothing to rank")
