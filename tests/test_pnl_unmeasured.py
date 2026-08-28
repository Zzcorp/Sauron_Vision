"""Unmeasured is not zero, and now the column can say so.

Stock and forex stops rest at the broker, so reconciliation is the exit
path for most of those trades. When nothing could price the exit it booked
the ENTRY price — a P&L of exactly 0.00 on a trade that may have cost real
money. That zero is invisible to the 24h daily-loss gate, which is the one
number an operator trusts to stop the day, and it enters the promotion
track record as a break-even that never happened.

`pnl` was `default=0` and not nullable, so the fact rode in a metadata flag
every reader had to remember to check. One reader did. It is NULL now, and
the difference shows up wherever a number is derived:

    Sum()      skips NULLs — a total of what was actually measured
    pnl__gt=0  excludes them — an unmeasured trade is not a win
    Count(pnl) counts the measured ones — the denominator that matches

Run with:  python manage.py test tests.test_pnl_unmeasured
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _cfg(user, name="U", mode="paper"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="stock", name=name, mode=mode,
        symbols=["AAPL"], capital=Decimal("10000"), enabled=True)


def _closed(cfg, pnl, hours_ago=1, paper=False):
    from bot_program.models import AssetBotTrade
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
        qty=Decimal("10"), entry_price=Decimal("100"),
        exit_price=Decimal("95") if pnl is not None else None,
        pnl=pnl, status="CLOSED", paper=paper,
        opened_at=timezone.now() - timedelta(hours=hours_ago + 1))
    t.closed_at = timezone.now() - timedelta(hours=hours_ago)
    t.save(update_fields=["closed_at"])
    return t


class TheColumnCanHoldTheFactTests(TestCase):

    def test_a_null_pnl_is_storable(self):
        from bot_program.models import AssetBotTrade
        user = User.objects.create_user("pnl_u1", password="x")
        t = _closed(_cfg(user), None)
        self.assertIsNone(AssetBotTrade.objects.get(pk=t.pk).pnl)

    def test_an_open_trade_still_defaults_to_zero(self):
        """Not unmeasured — a position that has realised nothing has
        realised zero, and the default is right for that case."""
        from bot_program.models import AssetBotTrade
        user = User.objects.create_user("pnl_u2", password="x")
        t = AssetBotTrade.objects.create(
            config=_cfg(user), asset_class="stock", symbol="AAPL",
            side="BUY", qty=Decimal("1"), entry_price=Decimal("100"),
            status="OPEN", opened_at=timezone.now())
        self.assertEqual(t.pnl, 0)


class TheDailyLossGateStopsCountingAScratchTests(TestCase):
    """The whole reason for the migration."""

    def setUp(self):
        self.user = User.objects.create_user("pnl_gate_u", password="x")
        self.cfg = _cfg(self.user)

    def test_an_unmeasured_close_is_unmeasured_not_flat(self):
        from portfolio.risk_gate import limits_book, realized_since
        _closed(self.cfg, None)
        w = realized_since(self.user, limits_book())
        self.assertEqual(w["unmeasured"], 1)

    def test_it_does_not_dilute_a_real_loss(self):
        """A -450 stop-out beside an unmeasured close must still read -450,
        not -450 averaged against a zero nobody measured."""
        from portfolio.risk_gate import limits_book, realized_since
        _closed(self.cfg, Decimal("-450"))
        _closed(self.cfg, None)
        w = realized_since(self.user, limits_book())
        self.assertEqual(w["realized"], -450.0)
        self.assertEqual(w["unmeasured"], 1)

    def test_a_book_of_nothing_but_unmeasured_closes_is_unknown(self):
        """Not flat. A confident 0.00 is how a losing day gets waved
        through."""
        from portfolio.risk_gate import limits_book, realized_since
        _closed(self.cfg, None)
        _closed(self.cfg, None)
        self.assertIsNone(realized_since(self.user, limits_book())["realized"])

    def test_rows_written_before_the_migration_are_still_honoured(self):
        """They carry the fabricated zero AND the metadata flag, and no
        backfill can recover a price nobody had."""
        from portfolio.risk_gate import limits_book, realized_since
        t = _closed(self.cfg, Decimal("0"))
        t.metadata = {"exit_price_unavailable": True}
        t.save(update_fields=["metadata"])
        self.assertEqual(realized_since(self.user, limits_book())["unmeasured"], 1)


class GradingAbstainsRatherThanScoringAZeroTests(TestCase):
    """`or 0` fed a trade whose result nobody knows into realized_r, the
    promotion gate and the meta-allocator — three places that read a
    break-even as evidence."""

    def test_an_unmeasured_trade_gets_no_r_multiple(self):
        """Asserted by GRADING one, not by grepping for the guard — the
        expression this used to search for was rewritten by the very next
        fix, and a test that pins source text fails on a correct refactor
        while passing on a broken one."""
        from bot_program.bot_grading import grade_bot_trade
        from bot_program.models import AssetBotTrade
        user = User.objects.create_user("pnl_grade_u", password="x")
        cfg = _cfg(user)
        t = _closed(cfg, None)
        t.stop_loss = Decimal("95")
        t.exit_price = Decimal("95")
        t.save(update_fields=["stop_loss", "exit_price"])

        grade_bot_trade(t)
        row = AssetBotTrade.objects.get(pk=t.pk)
        self.assertIsNone(row.realized_r,
                          "an R multiple derived from a P&L nobody measured")

    def test_a_measured_trade_still_grades(self):
        """The abstention must not become a refusal to grade anything."""
        from bot_program.bot_grading import grade_bot_trade
        from bot_program.models import AssetBotTrade
        user = User.objects.create_user("pnl_grade_u2", password="x")
        cfg = _cfg(user)
        t = _closed(cfg, Decimal("-50"))
        t.stop_loss = Decimal("95")
        t.exit_price = Decimal("95")
        t.save(update_fields=["stop_loss", "exit_price"])

        grade_bot_trade(t)
        row = AssetBotTrade.objects.get(pk=t.pk)
        self.assertIsNotNone(row.realized_r)


class TheDerivedNumbersGetHonestDenominatorsTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("pnl_agg_u", password="x")
        self.cfg = _cfg(self.user)

    def test_sum_skips_nulls_which_is_what_we_want(self):
        from django.db.models import Count, Sum

        from bot_program.models import AssetBotTrade
        _closed(self.cfg, Decimal("-450"))
        _closed(self.cfg, None)
        agg = AssetBotTrade.objects.filter(config=self.cfg).aggregate(
            s=Sum("pnl"), n=Count("id"), measured=Count("pnl"))
        self.assertEqual(agg["s"], Decimal("-450"))
        self.assertEqual(agg["n"], 2)
        # The denominator that matches the sum. Dividing -450 by 2 would
        # report an average loss of 225 on one trade that lost 450.
        self.assertEqual(agg["measured"], 1)

    def test_an_unmeasured_trade_is_not_counted_as_a_win(self):
        from django.db.models import Count, Q

        from bot_program.models import AssetBotTrade
        _closed(self.cfg, None)
        wins = AssetBotTrade.objects.filter(config=self.cfg).aggregate(
            w=Count("id", filter=Q(pnl__gt=0)))["w"]
        self.assertEqual(wins, 0)

    def test_the_equity_curve_skips_rather_than_steps_by_zero(self):
        """A flat step draws a line where the truth is a gap, and because
        the series is CUMULATIVE every point after it inherits the error."""
        from dashboard.views_bot_charts import (
            _equity_series, unmeasured_count,
        )
        trades = [_closed(self.cfg, Decimal("100")),
                  _closed(self.cfg, None),
                  _closed(self.cfg, Decimal("50"))]
        points = _equity_series(trades, 1000.0)
        self.assertEqual(points[-1]["equity"], 1150.0)
        self.assertEqual(len(points), 3)      # start + the two measured
        self.assertEqual(unmeasured_count(trades), 1)


class ReconciliationWritesTheNullTests(TestCase):
    """The writer that produced the fabricated zero in the first place."""

    def test_an_unpriceable_orphan_gets_a_null_pnl(self):
        from unittest.mock import MagicMock, patch

        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import _close_as_orphan
        user = User.objects.create_user("pnl_rec_u", password="x")
        cfg = _cfg(user, mode="live")
        trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"), status="OPEN",
            paper=False, opened_at=timezone.now())
        client = MagicMock()
        client.ticker.return_value = {}
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            _close_as_orphan(trade)
        row = AssetBotTrade.objects.get(pk=trade.pk)
        self.assertEqual(row.status, "CLOSED")
        self.assertIsNone(row.pnl)
        self.assertTrue(row.metadata.get("exit_price_unavailable"))

    def test_a_priceable_orphan_still_books_a_number(self):
        from unittest.mock import MagicMock, patch

        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import _close_as_orphan
        user = User.objects.create_user("pnl_rec_u2", password="x")
        cfg = _cfg(user, mode="live")
        trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("10"), entry_price=Decimal("100"), status="OPEN",
            paper=False, opened_at=timezone.now())
        client = MagicMock()
        client.ticker.return_value = {"lastPrice": "95"}
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            _close_as_orphan(trade)
        row = AssetBotTrade.objects.get(pk=trade.pk)
        self.assertIsNotNone(row.pnl)
        self.assertEqual(row.pnl, Decimal("-50.0000"))


class TheOtherReadersOfTheColumnTests(TestCase):
    """Making a column nullable is only half the work; the other half is
    every reader that never expected one. These four were found by grepping
    for arithmetic on `.pnl` after the migration, and two of them were worse
    than the bug the migration fixed."""

    def setUp(self):
        self.user = User.objects.create_user("pnl_rdr_u", password="x")
        self.cfg = _cfg(self.user)

    # ── the entry preflight, which used to raise ───────────────────────
    def test_the_daily_loss_gate_does_not_crash_on_an_unmeasured_close(self):
        """`sum((t.pnl for t in closed), Decimal(0))` raised TypeError, and
        this generator is the daily-loss gate inside can_open_new()."""
        from bot_program.asset_engine.stock_bot import StockBot
        _closed(self.cfg, None)
        ok, reason = StockBot(self.cfg).can_open_new()
        self.assertIsInstance(ok, bool)

    def test_the_gate_says_it_is_blind_rather_than_ok(self):
        """A confident "ok" from a gate that could not read half its input
        is the reassuring answer, which is the one that gets an operator
        hurt."""
        from bot_program.asset_engine.stock_bot import StockBot
        _closed(self.cfg, None)
        ok, reason = StockBot(self.cfg).can_open_new()
        # Asserted unconditionally. `if ok:` around these would let the test
        # pass by never running them.
        self.assertTrue(ok, reason)
        self.assertIn("UNCHECKED", reason)
        self.assertIn("could not be priced", reason)

    def test_a_measured_breach_still_halts_beside_an_unmeasured_row(self):
        """Abstaining must not become permissiveness: what WAS measured
        still has to be able to trip the floor."""
        from bot_program.asset_engine.stock_bot import StockBot
        self.cfg.max_daily_loss_pct = 1.0       # 1% of 10_000 == 100
        self.cfg.halt_on_drawdown = True
        self.cfg.save()
        _closed(self.cfg, Decimal("-500"))
        _closed(self.cfg, None)
        ok, reason = StockBot(self.cfg).can_open_new()
        self.assertFalse(ok)
        self.assertIn("daily loss limit", reason)

    # ── the consecutive-loss breaker, which used to be defused ─────────
    def test_an_unmeasured_row_no_longer_breaks_a_losing_streak(self):
        """It was coerced to Decimal("0"), which is not < 0, so it hit the
        `else: break`. Three real losses with one unpriceable close among
        them reported a streak of one — and unpriceable exits cluster when
        the broker link is sick, which is when a bot is most likely to be
        bleeding."""
        from bot_program.asset_engine.safety import CircuitBreakers
        self.cfg.extras = {"max_loss_streak": 3}
        self.cfg.save()
        _closed(self.cfg, Decimal("-10"), hours_ago=4)
        _closed(self.cfg, Decimal("-10"), hours_ago=3)
        _closed(self.cfg, None, hours_ago=2)
        _closed(self.cfg, Decimal("-10"), hours_ago=1)
        ok, reason = CircuitBreakers(self.cfg).check_consecutive_losses()
        self.assertFalse(ok, "the streak was broken by an unmeasured row")
        self.assertIn("unmeasured", reason)

    def test_a_winning_trade_still_breaks_the_streak(self):
        """The skip is for unknowns only. A measured WIN is real evidence
        that the run of losses ended, and must still reset the count."""
        from bot_program.asset_engine.safety import CircuitBreakers
        self.cfg.extras = {"max_loss_streak": 3}
        self.cfg.save()
        _closed(self.cfg, Decimal("-10"), hours_ago=4)
        _closed(self.cfg, Decimal("-10"), hours_ago=3)
        _closed(self.cfg, Decimal("25"), hours_ago=2)
        _closed(self.cfg, Decimal("-10"), hours_ago=1)
        ok, _ = CircuitBreakers(self.cfg).check_consecutive_losses()
        self.assertTrue(ok)

    # ── the portfolio row, which used to print a confident 0.00 ────────
    def test_the_portfolio_row_shows_no_number_rather_than_zero(self):
        from portfolio.services import _trade_to_position
        row = _trade_to_position(_closed(self.cfg, None), {}, {})
        self.assertIsNone(row.unrealized_pnl)
        self.assertIsNone(row.unrealized_pnl_pct)
        self.assertIsNone(row.pnl_on_capital_pct)

    def test_a_measured_close_still_shows_its_number(self):
        from portfolio.services import _trade_to_position
        row = _trade_to_position(_closed(self.cfg, Decimal("-50")), {}, {})
        self.assertEqual(row.unrealized_pnl, -50.0)
