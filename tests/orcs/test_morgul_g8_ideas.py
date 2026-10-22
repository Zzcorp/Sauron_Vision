"""MORGUL G8 AND THE ORCS' IDEAS (bot_program/morgul.check_duplicates, spec
§4.5): the legs of one idea are one position, never a duplicate; two
ideas still are; an unstamped book is judged exactly as before; Morgul
sends nothing new.

Run with:  python manage.py test tests.orcs.test_morgul_g8_ideas
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from tests.orcs.helpers import _config, _user


def _open(cfg, *, idea=None, symbol="EURUSD"):
    from bot_program.models import AssetBotTrade
    meta = {"broker": "etoro", "broker_env": "live"}
    if idea is not None:
        meta["orc"] = {"idea": idea, "leg": 1, "kind": "root",
                       "parent_rule": "r"}
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="forex", symbol=symbol, side="BUY",
        qty=Decimal("1000"), entry_price=Decimal("1.1"),
        stop_loss=Decimal("1.09"), status="OPEN", paper=False,
        metadata=meta)


class G8Tests(TestCase):

    def setUp(self):
        self.cfg = _config(_user("g8_orc"), "forex", mode="live")

    def _findings(self):
        from bot_program import morgul
        g = SimpleNamespace(finding=lambda subject, **kw: {"subject": subject,
                                                           **kw})
        return morgul.check_duplicates({}, g)

    def test_unstamped_unchanged(self):
        _open(self.cfg)
        self.assertEqual(self._findings(), [])
        _open(self.cfg)
        found = self._findings()
        self.assertEqual(len(found), 1)
        self.assertIn("Open live rows: 2", found[0]["facts"][0])

    def test_two_legs_one_idea_not_duplicate(self):
        _open(self.cfg, idea=7)
        _open(self.cfg, idea=7)
        self.assertEqual(self._findings(), [])

    def test_two_ideas_still_duplicate(self):
        a = _open(self.cfg, idea=7)
        b = _open(self.cfg, idea=8)
        found = self._findings()
        self.assertEqual(len(found), 1)
        self.assertIn(f"#{a.pk}", found[0]["facts"][0])
        self.assertIn(f"#{b.pk}", found[0]["facts"][0])
        _open(self.cfg, idea=7)
        self.assertEqual(len(self._findings()), 1)
        mixed = _config(_user("g8_mixed"), "forex", mode="live")
        _open(mixed, idea=9, symbol="GBPUSD")
        _open(mixed, symbol="GBPUSD")
        self.assertEqual(len(self._findings()), 2,
                         "an unstamped row beside an idea is a duplicate")

    def test_no_new_send(self):
        _open(self.cfg, idea=7)
        _open(self.cfg, idea=8)
        with patch("bot_program.notifications.dispatch_notification") as d, \
                patch("bot_program.notifications.notify_staff") as staff:
            self._findings()
        d.assert_not_called()
        staff.assert_not_called()
