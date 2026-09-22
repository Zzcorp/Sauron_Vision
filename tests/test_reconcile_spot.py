"""AN EMPTY DICT IT NEVER FILLED READ AS AN EMPTY BOOK — AND CLOSED EVERY ROW.

`engine/reconcile.reconcile_user` filled `exchange_positions` only when the
config was FUTURES and the client had a `positions` method. On a SPOT config —
the default, and the first entry in MARKET_CHOICES — that branch never ran, the
dict stayed empty, and step 1 booked CLOSED every open row whose symbol was
"not in exchange_positions", at the ticker mark, stamped
`reconcile:closed_externally`. The whole open book wiped in the database while
the positions sat at the venue.

Binance spot publishes no position list at all: a spot BALANCE is not a
position, which is why BinanceClient has no `positions` method. So the question
cannot be asked here — which is a third state, not an empty answer.

Reachable by hand from admin_bot_reconcile (staff, POST) and
`manage.py bot_reconcile --user`.
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase


def _setup(*, market="spot", symbol="BTCUSDT"):
    from bot_program.models import BotConfig, BotTrade
    user = User.objects.create_user(username="rc_" + market, password="x")
    cfg = BotConfig.objects.create(
        user=user, capital_usdt=Decimal("1000"), mode="live",
        market_type=market)
    trade = BotTrade.objects.create(
        config=cfg, symbol=symbol, side="BUY", qty=Decimal("1"),
        entry_price=Decimal("100"), stop_loss=Decimal("95"),
        take_profit=Decimal("110"), paper=False, status="OPEN")
    return user, cfg, trade


def _run(user, client):
    from bot_program.engine.reconcile import reconcile_user
    with mock.patch("bot_program.engine.runner._client_for",
                    return_value=client):
        return reconcile_user(user.id)


def _client(positions=None, *, has_positions=True, raises=None):
    c = mock.MagicMock()
    c.ticker = mock.MagicMock(return_value={"lastPrice": "105"})
    if not has_positions:
        del c.positions
    elif raises is not None:
        c.positions = mock.MagicMock(side_effect=raises)
    else:
        c.positions = mock.MagicMock(return_value=list(positions or []))
    return c


class AnUnreadableBookClosesNothing(TestCase):

    def test_a_spot_config_reconciles_nothing_and_says_why(self):
        """The whole defect, in one assertion: the row must survive."""
        user, _cfg, trade = _setup(market="spot")
        out = _run(user, _client([]))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIsNone(trade.exit_price)
        self.assertEqual(out["closed_orphans"], 0)
        self.assertIn("skipped", out)
        self.assertIn("position list", out["skipped"])
        self.assertEqual(out["open_rows"], 1)

    def test_a_client_without_a_position_list_reconciles_nothing(self):
        user, _cfg, trade = _setup(market="futures")
        out = _run(user, _client(has_positions=False))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertIn("skipped", out)

    def test_a_read_that_raises_is_still_an_error_and_closes_nothing(self):
        user, _cfg, trade = _setup(market="futures")
        out = _run(user, _client(raises=RuntimeError("503")))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(out, {"error": "exchange query failed"})


class AReadableBookStillReconciles(TestCase):
    """The regression guard: the futures path must not go inert."""

    def test_a_row_the_venue_no_longer_holds_is_closed(self):
        user, _cfg, trade = _setup(market="futures")
        out = _run(user, _client([]))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(out["closed_orphans"], 1)
        self.assertIn("reconcile:closed_externally", trade.reason)
        self.assertEqual(trade.exit_price, Decimal("105"))

    def test_a_row_the_venue_still_holds_is_left_open(self):
        user, _cfg, trade = _setup(market="futures")
        out = _run(user, _client([
            {"symbol": "BTCUSDT", "positionAmt": "1", "entryPrice": "100"}]))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(out["closed_orphans"], 0)
        self.assertEqual(out["found_unknown_positions"], 0)

    def test_a_position_no_row_claims_is_still_counted(self):
        user, _cfg, trade = _setup(market="futures")
        out = _run(user, _client([
            {"symbol": "BTCUSDT", "positionAmt": "1", "entryPrice": "100"},
            {"symbol": "ETHUSDT", "positionAmt": "5", "entryPrice": "20"}]))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(out["found_unknown_positions"], 1)

    def test_a_flat_reported_position_does_not_hold_a_row_open(self):
        """positionAmt 0 is the venue saying the position is gone."""
        user, _cfg, trade = _setup(market="futures")
        out = _run(user, _client([
            {"symbol": "BTCUSDT", "positionAmt": "0", "entryPrice": "100"}]))
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(out["closed_orphans"], 1)
