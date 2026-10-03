"""The "no Sauron signal behind this trade" warning on the instrument-view
ticket (bot_program/manual_trade.signal_backing_advisory, 2026-10-02).

The week's live book: five tickets taken from an instrument view, with no
signal behind them, made -1.98R; the hand-taken trades taken ON a signal
made +1.95R over nine. The operator asked for warnings that leave the last
choice to them: the ticket says so, records it, and is never refused.

Run with:  python manage.py test tests.test_signal_backing_warning
"""
from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from bot_program.manual_trade import (SIGNAL_BACKING_HOURS,
                                      SIGNAL_BACKING_MIN_SAMPLE,
                                      signal_backing_advisory)


def _quote(symbol, last, asset_class="crypto"):
    from instruments.models import Instrument
    from market_data.models import LiveQuote
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "binance_public"})
    return inst


def _signal(inst, direction="bullish", *, hours_ago=0, active=True):
    from signals.models import Signal
    s = Signal.objects.create(
        instrument=inst, signal_type="technical", direction=direction,
        urgency="high", title="t", description="d", rule_name="rsi_x",
        score=0.8, sub_scores={}, price_at_signal=Decimal("60000"),
        suggested_entry=Decimal("60000"), suggested_stop=Decimal("59100"),
        suggested_target=Decimal("61800"), is_active=active)
    Signal.objects.filter(pk=s.pk).update(
        created_at=timezone.now() - timedelta(hours=hours_ago))
    return s


class TheAdvisoryTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("sb_u", password="x")

    def setUp(self):
        self.inst = _quote("BTCUSD", 60000)

    def test_no_signal_is_warned(self):
        adv = signal_backing_advisory(self.user, self.inst, "BUY")
        self.assertFalse(adv["ok"])
        self.assertIn("No Sauron signal backs this ticket", adv["reason"])
        self.assertIn("bullish", adv["reason"])

    def test_a_recent_signal_in_the_ticket_s_direction_backs_it(self):
        _signal(self.inst, hours_ago=2)
        adv = signal_backing_advisory(self.user, self.inst, "BUY")
        self.assertTrue(adv["ok"])
        self.assertEqual(adv["signals"], ["rsi_x"])

    def test_the_wrong_direction_an_old_or_a_dead_signal_does_not(self):
        _signal(self.inst, "bearish")
        _signal(self.inst, hours_ago=SIGNAL_BACKING_HOURS + 1)
        _signal(self.inst, active=False)
        self.assertFalse(
            signal_backing_advisory(self.user, self.inst, "BUY")["ok"])
        self.assertTrue(
            signal_backing_advisory(self.user, self.inst, "SELL")["ok"])

    def test_a_signal_ticket_is_backed_by_definition(self):
        sig = _signal(self.inst, hours_ago=SIGNAL_BACKING_HOURS + 5)
        adv = signal_backing_advisory(self.user, self.inst, "BUY", sig)
        self.assertTrue(adv["ok"])

    def test_the_operator_s_own_record_is_quoted_once_there_is_one(self):
        from bot_program.models import AssetBotConfig, AssetBotTrade
        cfg = AssetBotConfig.objects.create(
            user=self.user, asset_class="crypto", name="manual",
            mode="paper", symbols=[], capital=Decimal("1000"), enabled=True)
        for i in range(SIGNAL_BACKING_MIN_SAMPLE):
            for sid, r in ((101, 0.4), (None, -0.4)):
                t = AssetBotTrade.objects.create(
                    config=cfg, asset_class="crypto", symbol="BTCUSD",
                    side="BUY", qty=Decimal("1"), entry_price=Decimal("1"),
                    status="CLOSED", paper=True, rule_name="manual_take",
                    realized_r=r, metadata={"signal_id": sid})
                AssetBotTrade.objects.filter(pk=t.pk).update(
                    closed_at=timezone.now() - timedelta(days=1))
        adv = signal_backing_advisory(self.user, self.inst, "BUY")
        self.assertIn("+0.40R a trade on a signal (5)", adv["reason"])
        self.assertIn("-0.40R without one (5)", adv["reason"])

        out = StringIO()
        call_command("scorecard", "--by", "signal", stdout=out)
        self.assertIn("── signal without a signal", out.getvalue())
        self.assertIn("── signal on a signal", out.getvalue())


class TheTicketCarriesItTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("sb_t", password="x")

    def test_an_instrument_view_ticket_is_warned_booked_and_recorded(self):
        from bot_program.manual_trade import (execute_asset_trade,
                                              preview_asset_trade)
        from bot_program.models import AssetBotTrade
        inst = _quote("BTCUSD", 60000)
        p = preview_asset_trade(self.user, inst, "BUY")
        self.assertNotIn("error", p)
        self.assertFalse(p["signal_backing"]["ok"])
        out = execute_asset_trade(self.user, inst, "BUY")
        self.assertTrue(out.get("ok"), out)
        meta = AssetBotTrade.objects.get(pk=out["trade_id"]).metadata
        self.assertEqual(meta["signal_backing_at_entry"],
                         {"ok": False, "signals": []})


class ThePopupRendersItTests(SimpleTestCase):

    def test_the_warning_is_rendered(self):
        from pathlib import Path
        from django.conf import settings
        html = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")
        self.assertIn("p.signal_backing", html)
        self.assertIn("NO SAURON SIGNAL ", html)
