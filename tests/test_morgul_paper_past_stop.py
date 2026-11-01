"""Morgul notes an open paper row far past its stop (2026-10-08).

A paper row sat OPEN for weeks with its mark ever further past its stop and
nothing said so until the tick that booked it at -8.12R. G12 (the stop
overshoot) now also NOTES an open PAPER row whose mark is more than 1.2R
(scorecard.OVERSHOOT_R) past its stop: a note in the report `manage.py
morgul` prints, never a finding, never a brake, never a message, in R and
prices only. Demo and live rows are never noted here (a real stop rests at
the broker; G2 and G10 watch those).

Run with:  python manage.py test tests.test_morgul_paper_past_stop
"""
import re
from datetime import timedelta
from decimal import Decimal as D
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone

from bot_program import morgul

ENTRY, STOP = D("1.34991"), D("1.34690")
RISK = ENTRY - STOP


def _cfg(user, *, enabled=True, mode="paper"):
    from bot_program.asset_models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="forex", name=f"fx {mode}", enabled=enabled,
        mode=mode, capital=D("10000"), symbols=["GBPUSD"])


def _open(cfg, *, paper=True, metadata=None, side="BUY", stop=STOP,
          entry=ENTRY):
    from bot_program.asset_models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class="forex", symbol="GBPUSD", side=side,
        qty=D("1000"), entry_price=entry, stop_loss=stop,
        take_profit=D("1.36"), paper=paper, status="OPEN",
        pnl=D("-123.45"),
        metadata=dict({"initial_stop_loss": float(stop)}, **(metadata or {})))


def _mark(price):
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    inst, _ = Instrument.objects.get_or_create(
        symbol="GBPUSD", defaults={"asset_class": "forex", "name": "GBPUSD"})
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": price, "source": "test"})


class PaperFarPastItsStopTests(TestCase):
    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user("mo_paper", password="x")

    def _run(self):
        ctx = morgul.Context(timezone.now())
        g = morgul.GUARD["stop_overshoot"]
        return ctx, g.check(ctx, g)

    def _notes(self, ctx):
        return [n for n in ctx.notes if "past its stop" in n]

    def test_the_minus_eight_shape_is_noted_never_alarmed(self):
        from tests.test_brake_keeps_managing import _tick
        _tick(True)
        t = _open(_cfg(self.user, enabled=False))
        _mark(D("1.32549"))
        ctx, found = self._run()
        self.assertEqual(found, [])
        (note,) = self._notes(ctx)
        self.assertIn(f"#{t.pk}", note)
        self.assertIn("7.1R past its stop", note)
        self.assertIn("1.3469", note)
        self.assertIn("1.32549", note)
        self.assertIn("off, with no record of who", note)
        self.assertIn("its paper exits still run every tick", note)
        # no money figure: the -123.45 pnl never reaches the words, nor a
        # currency (the symbol GBPUSD aside)
        words = note.replace("GBPUSD", "")
        for sign in ("$", "€", "£", "123", "USD", "EUR", "GBP"):
            self.assertNotIn(sign, words)

    def test_1_3r_past_is_noted_1_1r_is_not(self):
        cfg = _cfg(self.user)
        _open(cfg)
        _mark(STOP - RISK * D("1.3"))
        ctx, _found = self._run()
        self.assertEqual(len(self._notes(ctx)), 1)
        _mark(STOP - RISK * D("1.1"))
        ctx, _found = self._run()
        self.assertEqual(self._notes(ctx), [])

    def test_a_short_is_measured_the_other_way(self):
        cfg = _cfg(self.user)
        _open(cfg, side="SELL", entry=D("1.34691"), stop=D("1.34992"))
        _mark(D("1.35500"))
        ctx, _found = self._run()
        (note,) = self._notes(ctx)
        self.assertIn("1.7R past its stop", note)

    def test_demo_and_live_rows_are_never_noted(self):
        live = _cfg(self.user, mode="live")
        _open(live, paper=False, metadata={"broker": "etoro",
                                           "broker_env": "live"})
        _open(live, paper=False, metadata={"broker": "etoro",
                                           "broker_env": "paper"})
        _mark(D("1.32549"))
        ctx, found = self._run()
        self.assertEqual(self._notes(ctx), [])
        self.assertEqual(found, [])

    def test_with_no_price_the_row_is_not_judged(self):
        _open(_cfg(self.user))
        ctx, _found = self._run()
        self.assertEqual(self._notes(ctx), [])
        self.assertTrue(any("not judged" in n for n in ctx.notes))

    def test_the_bot_tick_off_is_said(self):
        _open(_cfg(self.user))
        _mark(D("1.32549"))
        with patch("bot_program.manual_trade._tick_manages",
                   return_value=False):
            ctx, _found = self._run()
        (note,) = self._notes(ctx)
        self.assertIn("the bot tick is off: nothing manages it", note)

    def test_the_lines_are_capped(self):
        cfg = _cfg(self.user)
        for _ in range(7):
            _open(cfg)
        _mark(D("1.32549"))
        ctx, _found = self._run()
        self.assertEqual(len(self._notes(ctx)), 5)
        self.assertTrue(any(re.search(r"\+2 more", n) for n in ctx.notes))

    def test_still_twelve_guards_and_g12_never_brakes(self):
        # twelve since G13, the short read-back (2026-10-31)
        self.assertEqual(len(morgul.GUARDS), 12)
        self.assertFalse(morgul.GUARD["stop_overshoot"].brake)

    def test_a_note_is_never_sent(self):
        _open(_cfg(self.user))
        _mark(D("1.32549"))
        with patch("bot_program.notifications._send_telegram",
                   return_value=True) as send:
            report = morgul.cycle(send=True,
                                  guards=[morgul.GUARD["stop_overshoot"]])
        send.assert_not_called()
        self.assertEqual(report.findings, [])
        self.assertEqual(report.messages, [])
        self.assertTrue(any("past its stop" in n for n in report.ctx.notes))
        rendered = "\n".join(morgul.render_report(report))
        self.assertIn("7.1R past its stop", rendered)
