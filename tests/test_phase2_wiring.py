"""Tests for the Phase-2 wiring fixes (post-completion of Phase 2.0):
  - bot_program.engine.runner._apply_risk_gate     — gate scale applied to bot qty
  - portfolio.tasks.create_daily_snapshot          — populates correlation_matrix

Run with:  python manage.py test tests.test_phase2_wiring
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import numpy as np
from django.test import TestCase
from django.utils import timezone


def _instrument(symbol, asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _seed_prices(instrument, returns, base=100.0):
    from market_data.models import PriceData
    now = timezone.now()
    price = base
    rows = []
    for i, r in enumerate(returns):
        nxt = price * (1 + r)
        ts = now - timedelta(days=len(returns) - i)
        rows.append(PriceData(
            instrument=instrument, timeframe="1d", timestamp=ts,
            open=Decimal(str(round(price, 6))),
            high=Decimal(str(round(max(price, nxt), 6))),
            low=Decimal(str(round(min(price, nxt), 6))),
            close=Decimal(str(round(nxt, 6))),
            volume=0, source="test",
        ))
        price = nxt
    PriceData.objects.bulk_create(rows)


class ApplyRiskGateTests(TestCase):
    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_user(username="botgateuser", password="x")

    def test_missing_instrument_keeps_qty(self):
        """If the bot's symbol has no Instrument record, gate is skipped, qty unchanged."""
        from bot_program.engine.runner import _apply_risk_gate
        new_qty, reason = _apply_risk_gate(self.user, "UNKNOWN_SYMBOL_XYZ", qty=1.0, price=100)
        self.assertEqual(new_qty, 1.0)
        self.assertIn("no Instrument", reason)

    def test_gate_applies_correlation_scale_when_correlated_position_open(self):
        """If a correlated position is already open, the gate scales qty down."""
        from bot_program.engine.runner import _apply_risk_gate
        from portfolio.services import get_or_create_default_portfolio
        from portfolio.models import Position

        # Two highly-correlated instruments, one already open.
        rng = np.random.RandomState(2026)
        rs = list(rng.normal(0, 0.01, 60))
        cand = _instrument("BTCUSDT")
        peer = _instrument("ETHUSDT")
        _seed_prices(cand, rs)
        _seed_prices(peer, rs)  # corr ≈ 1.0
        portfolio = get_or_create_default_portfolio(user=self.user)
        Position.objects.create(
            portfolio=portfolio, instrument=peer,
            direction="long", quantity=Decimal("1"),
            entry_price=Decimal("100"), current_price=Decimal("100"),
            opened_at=timezone.now(),
        )

        new_qty, reason = _apply_risk_gate(self.user, "BTCUSDT", qty=1.0, price=100.0)
        self.assertLess(new_qty, 1.0)
        self.assertIn("scale", reason)


@patch("core.task_gate.is_component_enabled", return_value=True)
@patch("core.task_gate.get_component", return_value=None)
class DailySnapshotCorrelationTests(TestCase):
    """The snapshot task is gated by `core.task_gate`; we patch the gate open."""

    def test_correlation_matrix_written_when_positions_exist(self, _mock_get, _mock_enabled):
        from portfolio.tasks import create_daily_snapshot
        from portfolio.services import get_or_create_default_portfolio
        from portfolio.models import Position, PortfolioSnapshot
        from market_data.models import LiveQuote

        rng = np.random.RandomState(11)
        rs = list(rng.normal(0, 0.01, 60))
        a = _instrument("SNAP_A")
        b = _instrument("SNAP_B")
        _seed_prices(a, rs)
        _seed_prices(b, [-r for r in rs])  # anti-correlated

        portfolio = get_or_create_default_portfolio()
        for inst in (a, b):
            Position.objects.create(
                portfolio=portfolio, instrument=inst,
                direction="long", quantity=Decimal("1"),
                entry_price=Decimal("100"), current_price=Decimal("100"),
                opened_at=timezone.now(),
            )
            # A snapshot needs a book it can VALUE, and a book is valued
            # from LiveQuote alone — `Position.current_price` is not a mark
            # the platform trusts, because the Setup form writes entry_price
            # into it verbatim. Without a quote these two rows are honestly
            # unpriced, the book is unmeasurable, and no snapshot is written
            # for it to carry a correlation matrix.
            LiveQuote.objects.update_or_create(
                instrument=inst,
                defaults={"last": Decimal("100"), "source": "test"})

        result = create_daily_snapshot()
        self.assertEqual(result["status"], "ok")

        snap = PortfolioSnapshot.objects.get(id=result["snapshot_id"])
        cm = snap.correlation_matrix
        self.assertIn("symbols", cm)
        self.assertIn("matrix", cm)
        self.assertEqual(set(cm["symbols"]), {"SNAP_A", "SNAP_B"})
        i = cm["symbols"].index("SNAP_A")
        j = cm["symbols"].index("SNAP_B")
        self.assertAlmostEqual(cm["matrix"][i][j], -1.0, places=2)

    def test_correlation_matrix_empty_when_no_positions(self, _mock_get, _mock_enabled):
        from portfolio.tasks import create_daily_snapshot
        from portfolio.models import PortfolioSnapshot

        result = create_daily_snapshot()
        snap = PortfolioSnapshot.objects.get(id=result["snapshot_id"])
        self.assertEqual(snap.correlation_matrix.get("symbols", []), [])
