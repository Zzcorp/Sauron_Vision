"""The leverage column (2026-10-03): the operator, "add leverage used by
position on the line of cells in positions page and please maybe
portfolio too".

The fact already existed for the dwell card (views._pos_leverage: the
broker's multiplier on an eToro row, the class's margin model otherwise);
it now stands in its own column on /positions/ and /portfolio/. "" is a
leverage nobody can establish and prints as a dash, never as 1.

Run with:  python manage.py test tests.test_leverage_column
"""
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase


def _read(*parts):
    from pathlib import Path
    from django.conf import settings
    return Path(settings.BASE_DIR, *parts).read_text(encoding="utf-8")


class TheMapTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        from instruments.models import Instrument
        cls.user = get_user_model().objects.create_user("lev_u", password="x")
        cfg = AssetBotConfig.objects.create(
            user=cls.user, asset_class="stock", name="live_stock",
            mode="live", symbols=[], capital=Decimal("1000"), enabled=True)
        cls.levered = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="NVDA", side="BUY",
            qty=Decimal("6"), entry_price=Decimal("237.6"), status="OPEN",
            paper=False, rule_name="manual_take",
            metadata={"broker": "etoro", "broker_env": "live",
                      "leverage": 5, "value_per_unit": 1.0})
        cls.cash = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN",
            paper=True, rule_name="r1", metadata={"value_per_unit": 1.0})
        cls.fx = Instrument.objects.create(symbol="EURUSD", name="EURUSD",
                                           asset_class="forex")

    def test_the_row_s_own_multiplier_the_class_model_and_the_unknown(self):
        from dashboard.views import _leverage_map
        rows = [
            SimpleNamespace(source="bot", trade_id=self.levered.id),
            SimpleNamespace(source="bot", trade_id=self.cash.id),
            SimpleNamespace(source="position", pk=7, instrument=self.fx),
            SimpleNamespace(source="position", pk=8, instrument=None),
        ]
        levs = _leverage_map(rows)
        self.assertEqual(levs[f"bot-{self.levered.id}"], "5")
        self.assertEqual(levs[f"bot-{self.cash.id}"], "1")
        self.assertEqual(levs["pos-7"], "30")      # forex: 1/30 margin
        self.assertEqual(levs["pos-8"], "")        # no class: unknown

    def test_the_live_row_carries_it(self):
        from dashboard.views import _live_row
        row = SimpleNamespace(
            source="bot", trade_id=self.levered.id, pk=None,
            entry_price=Decimal("237.6"), current_price=Decimal("233.84"),
            stop_loss=Decimal("232"), take_profit=Decimal("244"),
            direction="long", quantity=Decimal("6"), unrealized_pnl=None,
            unrealized_pnl_pct=None, instrument=None, opened_at=None,
            status="OPEN", paper=False)
        out = _live_row(row, {}, {f"bot-{self.levered.id}": "5"})
        self.assertEqual(out["leverage"], "5")
        self.assertEqual(_live_row(row, {})["leverage"], "")


class TheColumnsTests(SimpleTestCase):

    def test_positions_prints_it_beside_capital(self):
        html = _read("templates", "dashboard", "positions_list.html")
        self.assertIn(">Lev</th>", html)
        self.assertIn('data-label="Lev"', html)
        self.assertIn("{{ d.leverage }}x", html)
        self.assertIn('cols=16 scope="pos"', html)

    def test_portfolio_prints_it_beside_qty(self):
        html = _read("templates", "dashboard", "portfolio_overview.html")
        self.assertIn(">lev</th>", html)
        self.assertIn("{{ p.leverage }}x", html)
        self.assertIn('cols=11 scope="pf"', html)

    def test_an_unknown_leverage_is_a_dash_never_one(self):
        for page in ("positions_list.html", "portfolio_overview.html"):
            html = _read("templates", "dashboard", page)
            seg = html[html.index("pos-lev-cell"):][:400]
            self.assertIn("sv-unknown", seg)
