"""Reconciliation must finalise a broker-side exit the same way the bot does.

`reconcile_asset._close_as_orphan` is the finaliser for every exit the broker
performs on its own — which is all stock and forex trades, because their stops
rest at the broker and `manage_positions` skips protected rows. It marked the
row CLOSED and graded it, but never consumed the tax lot the entry opened and
never appended the close to the hash-chained audit log.

What that cost: the TaxLot from the entry kept its full `qty_remaining`
forever, so the next sale of the same symbol consumed THAT lot instead of its
own — cost basis off by a whole position, in the same direction, for every
close after it, while /tax-lots/ still listed shares that had already been
sold. The audit chain held an open with no matching close for the majority of
live trades.

These tests pin the ledger side of the close, not the mechanics of how the
orphan was detected.

Run with:  python manage.py test tests.test_reconcile_orphan_ledgers
"""
from decimal import Decimal
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


def _user(name="rc_u"):
    return User.objects.create_user(username=name, password="x")


def _cfg(user, asset_class="stock", **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        enabled=True, mode="live", symbols=["AAPL"],
        capital=Decimal("100000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
        entry_score_min=0.6, min_signals_for_entry=1,
    )
    defaults.update(kw)
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class,
        name=defaults.pop("name", "RC"), **defaults,
    )


def _live_trade(cfg, *, symbol="AAPL", side="BUY", qty=100, entry=150,
                status="OPEN", metadata=None):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal(str(qty)), entry_price=Decimal(str(entry)),
        stop_loss=Decimal("145"), take_profit=Decimal("170"),
        status=status, paper=False, rule_name="R1",
        metadata=metadata or {},
    )


class _FlatBroker:
    """A broker that reports no open positions and a live last price."""

    def __init__(self, last="145"):
        self.last = last
        self.cancelled = []

    def get_positions(self):
        return []

    def ticker(self, symbol):
        return {"lastPrice": self.last}

    def cancel_order(self, oid):
        self.cancelled.append(oid)
        return {"status": "CANCELLED"}


class ReconciledOrphanLedgerTests(TestCase):
    def setUp(self):
        self.user = _user("rc_ledger")
        self.cfg = _cfg(self.user)
        self.broker = _FlatBroker(last="145")

    def _reconcile(self, broker=None):
        from bot_program import reconcile_asset
        with mock.patch("bot_program.engine.broker_router.client_for_symbol",
                        return_value=broker or self.broker):
            return reconcile_asset.reconcile_user(self.user)

    def test_a_broker_side_stop_out_consumes_the_lot_its_entry_opened(self):
        from bot_program.tax_lots import open_lot
        from bot_program.models import TaxLotConsumption

        trade = _live_trade(self.cfg, qty=100, entry=150)
        lot = open_lot(trade)
        self.assertEqual(lot.qty_remaining, Decimal("100"))

        out = self._reconcile()
        self.assertEqual(out["closed_as_orphan"], 1)

        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")

        lot.refresh_from_db()
        self.assertEqual(lot.qty_remaining, Decimal("0"))
        self.assertIsNotNone(lot.closed_at)

        cons = list(TaxLotConsumption.objects.filter(lot=lot))
        self.assertEqual(len(cons), 1)
        self.assertEqual(cons[0].qty_consumed, Decimal("100"))
        # Stopped out at 145 against a 150 basis: -500 realised.
        self.assertEqual(cons[0].realized_gain, Decimal("-500.0000"))
        self.assertEqual(cons[0].consuming_trade_id, trade.id)

    def test_a_broker_side_stop_out_appends_a_close_to_the_audit_chain(self):
        from bot_program.audit import verify_chain
        from bot_program.audit_models import AuditLogEntry

        trade = _live_trade(self.cfg)
        self._reconcile()
        trade.refresh_from_db()

        closes = [e for e in AuditLogEntry.objects.filter(kind="trade_close")
                  if e.data.get("trade_id") == trade.id]
        self.assertEqual(len(closes), 1)
        self.assertEqual(Decimal(closes[0].data["exit_price"]), trade.exit_price)
        self.assertEqual(closes[0].data["mode"], "live")
        # Graded before the audit entry is written, so the outcome travels
        # with it rather than being recorded as blank.
        self.assertTrue(closes[0].data["outcome"])
        self.assertTrue(verify_chain()["ok"])

    def test_the_next_sale_of_a_symbol_is_not_booked_against_the_reconciled_lot(self):
        """The cost-basis corruption: an unconsumed lot poisons every later close."""
        from bot_program.tax_lots import open_lot, close_lots_for
        from bot_program.models import TaxLot

        first = _live_trade(self.cfg, qty=100, entry=150)
        lot_a = open_lot(first)
        self._reconcile()  # broker stop fires at 145, reconciliation books it

        # Second position in the same symbol, closed by the bot itself.
        second = _live_trade(self.cfg, qty=100, entry=160)
        lot_b = open_lot(second)
        second.exit_price = Decimal("170")
        second.status = "CLOSED"
        second.closed_at = timezone.now()
        second.save()
        cons = close_lots_for(second)

        self.assertEqual(len(cons), 1)
        self.assertEqual(cons[0].lot_id, lot_b.pk)
        # (170 - 160) * 100 = 1,000 — the real gain on the shares sold. With
        # lot A left open, FIFO would have walked it first and booked 2,000.
        self.assertEqual(cons[0].realized_gain, Decimal("1000.0000"))

        self.assertEqual(TaxLot.objects.filter(user=self.user,
                                               qty_remaining__gt=0).count(), 0)

    def test_a_failing_tax_ledger_does_not_leave_the_row_open(self):
        """Ledger work is bookkeeping — it must never strand a closed position."""
        from bot_program.tax_lots import open_lot

        trade = _live_trade(self.cfg)
        open_lot(trade)
        with mock.patch("bot_program.tax_lots.close_lots_for",
                        side_effect=RuntimeError("ledger down")):
            out = self._reconcile()
        self.assertEqual(out["closed_as_orphan"], 1)
        trade.refresh_from_db()
        self.assertEqual(trade.status, "CLOSED")
        self.assertIsNotNone(trade.closed_at)

    def test_a_paper_row_is_not_reconciled_and_keeps_its_lot(self):
        """Paper trades have no broker to answer for them; nothing is consumed."""
        from bot_program.models import AssetBotTrade, TaxLotConsumption
        from bot_program.tax_lots import open_lot

        trade = _live_trade(self.cfg)
        AssetBotTrade.objects.filter(pk=trade.pk).update(paper=True)
        trade.refresh_from_db()
        lot = open_lot(trade)

        out = self._reconcile()
        self.assertEqual(out["checked"], 0)
        lot.refresh_from_db()
        self.assertEqual(lot.qty_remaining, Decimal("100"))
        self.assertEqual(TaxLotConsumption.objects.count(), 0)
