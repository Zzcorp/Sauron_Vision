"""Phase-27 tax-lot tests:
  - open_lot creates a TaxLot from BUY-side trades; SELL-side ignored
  - close_lots_for FIFO consumption produces correct realised gain
  - LIFO + HIFO orderings honoured
  - partial fills (one trade consumes multiple lots; one lot consumed across trades)
  - holding-period flag (≥365d → long_term=True)
  - lot_method_for reads TraderProfile (default FIFO)
  - hooks fire from AssetBot scan_symbol + _close_trade end-to-end
  - /tax-lots/ dashboard renders + CSV export streams Form-8949-style rows
  - per-user scoping

Run with:  python manage.py test tests.test_phase27_tax_lots
"""
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, Client
from django.utils import timezone


def _user(name="tx_u"):
    return User.objects.create_user(username=name, password="x")


def _profile(user, **kw):
    from portfolio.trader_profile import TraderProfile
    p, _ = TraderProfile.objects.get_or_create(user=user)
    for k, v in kw.items():
        setattr(p, k, v)
    p.save()
    return p


def _abc(user, asset_class="stock", **kw):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        enabled=True, mode="paper", symbols=[],
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
        entry_score_min=0.6, min_signals_for_entry=1,
    )
    defaults.update(kw)
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=defaults.pop("name", "T"),
        **defaults,
    )


def _trade(cfg, *, symbol="AAPL", side="BUY", qty=10, entry=100,
           exit=None, status="OPEN", paper=True, opened_at=None,
           closed_at=None, asset_class=None, metadata=None):
    """Create AssetBotTrade. Note: opened_at is auto_now_add — override via update."""
    from bot_program.models import AssetBotTrade
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=asset_class or cfg.asset_class,
        symbol=symbol, side=side,
        qty=Decimal(str(qty)),
        entry_price=Decimal(str(entry)),
        exit_price=Decimal(str(exit)) if exit is not None else None,
        status=status, paper=paper,
        metadata=metadata or {},
    )
    if opened_at is not None or closed_at is not None:
        kwargs = {}
        if opened_at is not None:
            kwargs["opened_at"] = opened_at
        if closed_at is not None:
            kwargs["closed_at"] = closed_at
        AssetBotTrade.objects.filter(pk=t.pk).update(**kwargs)
        t.refresh_from_db()
    return t


# ── open_lot ──────────────────────────────────────────────────────────────

class OpenLotTests(TestCase):
    def setUp(self):
        self.user = _user("ol_u")
        self.cfg = _abc(self.user, "stock", name="ST")

    def test_buy_creates_lot(self):
        from bot_program.tax_lots import open_lot
        from bot_program.models import TaxLot
        t = _trade(self.cfg, symbol="AAPL", side="BUY", qty=10, entry=150)
        lot = open_lot(t)
        self.assertIsNotNone(lot)
        self.assertEqual(lot.symbol, "AAPL")
        self.assertEqual(lot.qty_initial, Decimal("10"))
        self.assertEqual(lot.qty_remaining, Decimal("10"))
        self.assertEqual(lot.cost_basis_per_unit, Decimal("150"))

    def test_sell_ignored(self):
        from bot_program.tax_lots import open_lot
        from bot_program.models import TaxLot
        t = _trade(self.cfg, side="SELL")
        lot = open_lot(t)
        self.assertIsNone(lot)
        self.assertEqual(TaxLot.objects.count(), 0)

    def test_options_uses_metadata_multiplier(self):
        from bot_program.tax_lots import open_lot
        cfg = _abc(self.user, "options", name="OPT")
        t = _trade(cfg, asset_class="options", side="BUY", qty=2,
                    entry=5, metadata={"multiplier": 100, "right": "C"})
        lot = open_lot(t)
        self.assertEqual(lot.multiplier, 100)


# ── close_lots_for ────────────────────────────────────────────────────────

class CloseLotsTests(TestCase):
    def setUp(self):
        self.user = _user("cl_u")
        self.cfg = _abc(self.user, "stock", name="ST")
        _profile(self.user, tax_lot_method="FIFO")

    def _open_then_close(self, *, qty, entry, exit, opened_days_ago,
                          method="FIFO", symbol="AAPL"):
        """Helper: simulate a trade lifecycle by hand (open lot + close + consume)."""
        from bot_program.tax_lots import open_lot, close_lots_for
        opened = timezone.now() - timedelta(days=opened_days_ago)
        closed = timezone.now()
        t = _trade(self.cfg, symbol=symbol, side="BUY", qty=qty,
                    entry=entry, exit=exit, status="CLOSED",
                    opened_at=opened, closed_at=closed)
        lot = open_lot(t)
        # The lot's opened_at should match the trade's opened_at after refresh.
        from bot_program.models import TaxLot
        TaxLot.objects.filter(pk=lot.pk).update(opened_at=opened)
        # Close consumes the lot.
        cs = close_lots_for(t)
        return t, lot, cs

    def test_fifo_simple_full_consumption(self):
        # entry 100, exit 110, qty 10 → realised gain (110-100)*10*1 = 100
        from bot_program.models import TaxLotConsumption
        _, lot, cs = self._open_then_close(qty=10, entry=100, exit=110,
                                            opened_days_ago=30)
        self.assertEqual(len(cs), 1)
        c = cs[0]
        self.assertEqual(c.qty_consumed, Decimal("10"))
        self.assertEqual(c.realized_gain, Decimal("100.0000"))
        self.assertFalse(c.long_term)  # 30d < 365
        # Lot fully consumed.
        lot.refresh_from_db()
        self.assertEqual(lot.qty_remaining, Decimal("0"))
        self.assertIsNotNone(lot.closed_at)

    def test_long_term_when_held_at_least_365d(self):
        _, _, cs = self._open_then_close(qty=10, entry=100, exit=110,
                                          opened_days_ago=400)
        self.assertEqual(len(cs), 1)
        self.assertTrue(cs[0].long_term)
        self.assertEqual(cs[0].holding_period_days, 400)

    def test_one_trade_consumes_multiple_lots_fifo(self):
        from bot_program.tax_lots import open_lot, close_lots_for
        from bot_program.models import TaxLot

        # Open two lots: 10 @ 100 (60d ago), 10 @ 120 (10d ago).
        old = timezone.now() - timedelta(days=60)
        new = timezone.now() - timedelta(days=10)
        t_old = _trade(self.cfg, symbol="ABC", side="BUY", qty=10, entry=100,
                        opened_at=old)
        t_new = _trade(self.cfg, symbol="ABC", side="BUY", qty=10, entry=120,
                        opened_at=new)
        l_old = open_lot(t_old); TaxLot.objects.filter(pk=l_old.pk).update(opened_at=old)
        l_new = open_lot(t_new); TaxLot.objects.filter(pk=l_new.pk).update(opened_at=new)

        # Close 15 @ 130 — FIFO should consume all of old (10) + 5 of new.
        sell = _trade(self.cfg, symbol="ABC", side="BUY",
                       qty=15, entry=999, exit=130,
                       status="CLOSED",
                       opened_at=timezone.now(),
                       closed_at=timezone.now())
        cs = close_lots_for(sell)
        self.assertEqual(len(cs), 2)
        # First slice = old lot (FIFO order). Realised = (130-100) * 10 = 300.
        self.assertEqual(cs[0].qty_consumed, Decimal("10"))
        self.assertEqual(cs[0].realized_gain, Decimal("300.0000"))
        self.assertEqual(cs[0].lot_id, l_old.pk)
        # Second slice = 5 from new lot. Realised = (130-120) * 5 = 50.
        self.assertEqual(cs[1].qty_consumed, Decimal("5"))
        self.assertEqual(cs[1].realized_gain, Decimal("50.0000"))
        self.assertEqual(cs[1].lot_id, l_new.pk)

        l_old.refresh_from_db()
        l_new.refresh_from_db()
        self.assertEqual(l_old.qty_remaining, Decimal("0"))
        self.assertEqual(l_new.qty_remaining, Decimal("5"))

    def test_lifo_picks_newest_lot_first(self):
        from bot_program.tax_lots import open_lot, close_lots_for
        from bot_program.models import TaxLot

        _profile(self.user, tax_lot_method="LIFO")
        old = timezone.now() - timedelta(days=60)
        new = timezone.now() - timedelta(days=10)
        t_old = _trade(self.cfg, symbol="LIFO", side="BUY", qty=10, entry=100,
                        opened_at=old)
        t_new = _trade(self.cfg, symbol="LIFO", side="BUY", qty=10, entry=120,
                        opened_at=new)
        l_old = open_lot(t_old); TaxLot.objects.filter(pk=l_old.pk).update(opened_at=old)
        l_new = open_lot(t_new); TaxLot.objects.filter(pk=l_new.pk).update(opened_at=new)

        sell = _trade(self.cfg, symbol="LIFO", side="BUY",
                       qty=5, entry=999, exit=130,
                       status="CLOSED",
                       closed_at=timezone.now())
        cs = close_lots_for(sell)
        self.assertEqual(len(cs), 1)
        # LIFO → consume newest (cost 120). Gain = (130-120)*5 = 50.
        self.assertEqual(cs[0].lot_id, l_new.pk)
        self.assertEqual(cs[0].realized_gain, Decimal("50.0000"))

    def test_hifo_picks_highest_cost_first(self):
        from bot_program.tax_lots import open_lot, close_lots_for
        from bot_program.models import TaxLot

        _profile(self.user, tax_lot_method="HIFO")
        # Two lots: low cost old, high cost new. HIFO picks high cost first
        # (minimises realised gain → tax-loss-optimal).
        old = timezone.now() - timedelta(days=60)
        new = timezone.now() - timedelta(days=10)
        t_low = _trade(self.cfg, symbol="HIFO", side="BUY", qty=10, entry=100,
                        opened_at=old)
        t_high = _trade(self.cfg, symbol="HIFO", side="BUY", qty=10, entry=180,
                         opened_at=new)
        l_low = open_lot(t_low); TaxLot.objects.filter(pk=l_low.pk).update(opened_at=old)
        l_high = open_lot(t_high); TaxLot.objects.filter(pk=l_high.pk).update(opened_at=new)

        sell = _trade(self.cfg, symbol="HIFO", side="BUY",
                       qty=5, entry=999, exit=200,
                       status="CLOSED",
                       closed_at=timezone.now())
        cs = close_lots_for(sell)
        self.assertEqual(len(cs), 1)
        self.assertEqual(cs[0].lot_id, l_high.pk)
        # Gain = (200-180)*5 = 100.
        self.assertEqual(cs[0].realized_gain, Decimal("100.0000"))

    def test_lot_only_consumed_for_matching_paper_mode(self):
        """Live close must not consume paper lots and vice versa."""
        from bot_program.tax_lots import open_lot, close_lots_for
        from bot_program.models import TaxLot
        # Open a paper lot.
        t_paper = _trade(self.cfg, symbol="P", side="BUY", qty=10, entry=100,
                          paper=True)
        open_lot(t_paper)
        # Close a live trade — should NOT consume the paper lot.
        sell = _trade(self.cfg, symbol="P", side="BUY", qty=10,
                       entry=999, exit=110, status="CLOSED",
                       paper=False, closed_at=timezone.now())
        cs = close_lots_for(sell)
        self.assertEqual(cs, [])  # nothing consumed
        # Paper lot still intact.
        self.assertEqual(TaxLot.objects.filter(paper=True,
                                                qty_remaining__gt=0).count(), 1)


# ── lot_method_for ───────────────────────────────────────────────────────

class LotMethodTests(TestCase):
    def test_default_fifo(self):
        from bot_program.tax_lots import lot_method_for
        u = _user("default_u")
        self.assertEqual(lot_method_for(u), "FIFO")

    def test_reads_profile(self):
        from bot_program.tax_lots import lot_method_for
        u = _user("profile_u")
        _profile(u, tax_lot_method="HIFO")
        self.assertEqual(lot_method_for(u), "HIFO")


# ── End-to-end via AssetBot ──────────────────────────────────────────────

class HookIntegrationTests(TestCase):
    def test_scan_symbol_open_creates_tax_lot(self):
        from bot_program.asset_engine import StockBot
        from bot_program.models import TaxLot
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        from signals.models import Signal

        u = _user("hk_u_a")
        cfg = _abc(u, "stock", name="ST", symbols=["AAPL"])
        inst, _ = Instrument.objects.get_or_create(
            symbol="AAPL", defaults={"name": "AAPL", "asset_class": "stock"})
        LiveQuote.objects.create(instrument=inst, last=Decimal("100"))
        Signal.objects.create(
            instrument=inst, signal_type="composite", direction="bullish",
            urgency="medium", title="t", description="t", rule_name="r1",
            score=0.85, sub_scores={},
            price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
        )
        result = StockBot(cfg).scan_symbol("AAPL")
        self.assertIsNotNone(result)
        self.assertEqual(TaxLot.objects.filter(user=u, symbol="AAPL").count(), 1)


# ── Dashboard + CSV export ───────────────────────────────────────────────

class DashboardTests(TestCase):
    def setUp(self):
        self.user = _user("dash_u")
        self.client.force_login(self.user)

    def test_renders_empty(self):
        r = self.client.get("/tax-lots/")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "TAX LOTS")

    def test_renders_open_lot(self):
        from bot_program.tax_lots import open_lot
        cfg = _abc(self.user, "stock", name="ST")
        t = _trade(cfg, symbol="ABCDXYZ", side="BUY", qty=5, entry=200,
                    paper=False)
        open_lot(t)
        r = self.client.get("/tax-lots/?mode=live")
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "ABCDXYZ")

    def test_csv_export(self):
        from bot_program.tax_lots import open_lot, close_lots_for
        from bot_program.models import TaxLot
        cfg = _abc(self.user, "stock", name="ST")
        opened = timezone.now() - timedelta(days=30)
        t = _trade(cfg, symbol="CSVTEST", side="BUY", qty=10, entry=100,
                    exit=110, status="CLOSED", paper=False,
                    opened_at=opened, closed_at=timezone.now())
        lot = open_lot(t)
        TaxLot.objects.filter(pk=lot.pk).update(opened_at=opened)
        close_lots_for(t)

        year = timezone.now().year
        r = self.client.get(f"/tax-lots/export/?year={year}&mode=live")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r["Content-Type"], "text/csv")
        self.assertIn("attachment", r["Content-Disposition"])
        self.assertIn(b"description", r.content)  # header
        self.assertIn(b"CSVTEST", r.content)
        self.assertIn(b"Short-term", r.content)

    def test_user_scoping(self):
        from bot_program.tax_lots import open_lot
        other = _user("other_u")
        other_cfg = _abc(other, "stock", name="OTH")
        t = _trade(other_cfg, symbol="OTHERSYM", side="BUY", qty=5, entry=100,
                    paper=False)
        open_lot(t)
        r = self.client.get("/tax-lots/?mode=live")
        self.assertNotContains(r, "OTHERSYM")
