"""Morgul G12: a real-money stop that did not hold (2026-10-02).

The week's book carried two paper stops that did not hold, -8.12R (GBPUSD)
and -1.84R (AAPL): positions nobody watched while their market ran past
the stop. On real money the operator wants to hear of it at once. A LIVE
close of the last 24 h worse than -1.2R (scorecard.OVERSHOOT_R) is a
critical finding, said once, in R and prices — never a money figure — and
never a brake: the position is already closed.

Run with:  python manage.py test tests.test_morgul_overshoot
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from bot_program import morgul
from bot_program.scorecard import OVERSHOOT_R


def _cfg(user, mode="live"):
    from bot_program.asset_models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="forex", name="fx", enabled=True, mode=mode,
        capital=Decimal("10000"), symbols=[])


def _closed(cfg, r, *, paper=False, hours_ago=2, metadata=None):
    from bot_program.asset_models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="forex", symbol="GBPUSD", side="BUY",
        qty=Decimal("1000"), entry_price=Decimal("1.34991"),
        stop_loss=Decimal("1.34690"), exit_price=Decimal("1.32549"),
        pnl=Decimal("-20"), paper=paper, status="CLOSED", realized_r=r,
        closed_at=timezone.now() - timedelta(hours=hours_ago),
        metadata=dict({"initial_stop_loss": 1.3469}, **(metadata or {})))


class StopOvershootTests(TestCase):

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = get_user_model().objects.create_user("mo_u", password="x")

    def _run(self):
        ctx = morgul.Context(timezone.now())
        g = morgul.GUARD["stop_overshoot"]
        return ctx, g.check(ctx, g)

    def test_a_live_close_past_the_line_is_a_critical_event(self):
        t = _closed(_cfg(self.user), -8.12)
        _ctx, found = self._run()
        self.assertEqual([f.subject for f in found], [f"trade:{t.pk}"])
        f = found[0]
        self.assertEqual(f.severity, "critical")
        self.assertTrue(f.event)
        self.assertFalse(f.brakes)
        text = " ".join(f.facts)
        self.assertIn("-8.12R, past -1.2R", text)
        self.assertIn("1.3469", text)
        self.assertIn("did not hold", text)
        # no money figure: the -20 pnl never reaches the words
        self.assertNotIn("20", text.replace("2026", ""))

    def test_a_full_stop_is_not_an_overshoot(self):
        cfg = _cfg(self.user)
        _closed(cfg, -1.05)
        _closed(cfg, -OVERSHOOT_R)
        self.assertEqual(self._run()[1], [])

    def test_paper_and_demo_are_counted_not_alarmed(self):
        cfg = _cfg(self.user)
        _closed(cfg, -8.12, paper=True)
        _closed(cfg, -3.0, metadata={"broker_env": "paper"})
        ctx, found = self._run()
        self.assertEqual(found, [])
        self.assertTrue(any("2 paper or demo closes" in n for n in ctx.notes),
                        ctx.notes)

    def test_older_than_a_day_is_not_said_again(self):
        _closed(_cfg(self.user), -3.0, hours_ago=30)
        self.assertEqual(self._run()[1], [])

    def test_it_never_brakes(self):
        self.assertFalse(morgul.GUARD["stop_overshoot"].brake)
