"""Nothing ever swept broker → database.

Reconciliation walks rows and asks the broker about each one. The other
direction was never walked, so a position the broker HOLDS that no row
claims is invisible platform-wide:

  - uncounted by every exposure and daily-loss gate
  - carrying no bot-side stop, because bot-side management iterates rows
  - untouched by the kill switch, whose "flatten everything" iterates
    AssetBotTrade rows and never asks the broker whether it is actually flat

The entry path manufactures exactly that state. If `market_order` reaches
the broker but the response is lost — a read timeout on Alpaca's POST, a
socket drop during `_await_fill`, a TWS disconnect after `placeOrder` —
`base.py` logs and returns None, writing no row. The units are real and
nothing here knows.

The old crypto engine had a `found_unknown` counter for precisely this; the
asset path dropped the capability.

REPORTS, never closes: the operator may have opened the position by hand,
and an automated system that flattens what it does not recognise is worse
than one that says so.

Run with:  python manage.py test tests.test_unclaimed_positions
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _cfg(user, **kw):
    from bot_program.models import AssetBotConfig
    opts = dict(user=user, asset_class="stock", name="U", mode="live",
                symbols=["AAPL"], capital=Decimal("10000"), enabled=True)
    opts.update(kw)
    return AssetBotConfig.objects.create(**opts)


def _open_row(cfg, symbol="AAPL"):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="stock", symbol=symbol, side="BUY",
        qty=Decimal("10"), entry_price=Decimal("100"), status="OPEN",
        paper=False, opened_at=timezone.now())


def _client(symbols):
    c = MagicMock()
    c.get_positions.return_value = [{"symbol": s} for s in symbols]
    return c


class TheSweepFindsWhatNoRowClaimsTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("sweep_u", password="x")
        self.cfg = _cfg(self.user)

    def _sweep(self, client):
        from bot_program.reconcile_asset import reconcile_unknown_positions
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=client):
            return reconcile_unknown_positions(self.user)

    def test_a_position_no_row_claims_is_reported(self):
        out = self._sweep(_client(["AAPL", "TSLA"]))
        self.assertEqual(out["unclaimed"], 2)
        self.assertIn("TSLA", out["symbols"])

    def test_a_claimed_position_is_not_reported(self):
        _open_row(self.cfg, "AAPL")
        out = self._sweep(_client(["AAPL"]))
        self.assertEqual(out["unclaimed"], 0)

    def test_only_the_unclaimed_half_is_named(self):
        _open_row(self.cfg, "AAPL")
        out = self._sweep(_client(["AAPL", "NVDA"]))
        self.assertEqual(out["symbols"], ["NVDA"])

    def test_symbol_case_does_not_invent_an_unclaimed_position(self):
        """The broker's casing is not ours, and a false alarm here trains
        the operator to ignore the real one."""
        _open_row(self.cfg, "AAPL")
        out = self._sweep(_client(["aapl"]))
        self.assertEqual(out["unclaimed"], 0)

    def test_an_unreadable_broker_is_not_a_clean_sweep(self):
        """UNREADABLE is not EMPTY. Reporting "no unclaimed positions" for
        a book nobody could read is the reassuring answer."""
        c = MagicMock()
        c.get_positions.side_effect = RuntimeError("socket gone")
        out = self._sweep(c)
        self.assertEqual(out["broker_unavailable"], 1)
        self.assertEqual(out["unclaimed"], 0)

    def test_a_client_with_no_positions_api_is_not_a_clean_sweep(self):
        c = MagicMock(spec=["ticker"])
        out = self._sweep(c)
        self.assertEqual(out["broker_unavailable"], 1)

    def test_it_never_closes_anything(self):
        """Deliberately. The operator may have opened it by hand, and a
        system that flattens what it does not recognise is more dangerous
        than one that reports it."""
        from bot_program.models import AssetBotTrade
        _open_row(self.cfg, "AAPL")
        self._sweep(_client(["AAPL", "TSLA"]))
        self.assertEqual(
            AssetBotTrade.objects.filter(status="OPEN").count(), 1)

    def test_the_operator_is_told(self):
        with patch("bot_program.notifications.notify_unclaimed_position",
                   return_value=True) as m:
            self._sweep(_client(["GME"]))
        self.assertTrue(m.called)
        self.assertIn("GME", m.call_args.kwargs["symbols"])

    def test_a_paper_config_is_not_swept(self):
        """Paper positions live nowhere but here, so the broker has no
        opinion about them and every symbol would read as unclaimed."""
        from bot_program.models import AssetBotConfig
        AssetBotConfig.objects.filter(pk=self.cfg.pk).update(mode="paper")
        out = self._sweep(_client(["AAPL", "TSLA"]))
        self.assertEqual(out["checked"], 0)


class TheSweepReachesUsersWithNoRowsAtAllTests(TestCase):
    """The case it exists for: a user whose ONLY broker position is one no
    row claims has no open rows, so the row-driven walk skips them."""

    def test_a_user_with_no_open_rows_is_still_swept(self):
        from bot_program.reconcile_asset import reconcile_all_users
        user = User.objects.create_user("sweep_norows", password="x")
        _cfg(user)
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=_client(["ORPHAN1"])):
            totals = reconcile_all_users()
        self.assertEqual(totals["unclaimed"], 1)

    def test_a_user_with_neither_rows_nor_live_configs_is_skipped(self):
        from bot_program.reconcile_asset import reconcile_all_users
        User.objects.create_user("sweep_idle", password="x")
        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=_client(["X"])):
            totals = reconcile_all_users()
        self.assertEqual(totals["unclaimed"], 0)

    def test_a_sweep_failure_does_not_cost_the_row_reconciliation(self):
        from bot_program.reconcile_asset import reconcile_all_users
        user = User.objects.create_user("sweep_boom", password="x")
        cfg = _cfg(user)
        _open_row(cfg, "AAPL")
        with patch("bot_program.reconcile_asset.reconcile_unknown_positions",
                   side_effect=RuntimeError("boom")), \
             patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=_client(["AAPL"])):
            totals = reconcile_all_users()
        self.assertEqual(totals["users"], 1)
        self.assertGreaterEqual(totals["errors"], 1)
