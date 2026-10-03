"""The early-close warning: closing a winner short of its own target
(bot_program/manual_close.early_close_advisory, 2026-10-02).

The week's book: 12 of 15 winners closed by hand at +0.28R on average —
several in one minute through "close all" — against losers that ran their
full -1R. The operator asked for a warning that leaves the last choice to
them: the dialog names the R now, the target, what the position has
already seen and whether it is protected, and the button only gains
"ANYWAY".

Run with:  python manage.py test tests.test_early_close_warning
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _instrument(symbol="BTCUSD", asset_class="crypto"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _quote(symbol, last, asset_class="crypto"):
    from market_data.models import LiveQuote
    inst = _instrument(symbol, asset_class)
    LiveQuote.objects.update_or_create(
        instrument=inst, defaults={"last": Decimal(str(last)),
                                   "source": "binance_public"})
    return inst


def _cfg(user, name="manual"):
    from bot_program.models import AssetBotConfig
    return AssetBotConfig.objects.create(
        user=user, asset_class="crypto", name=name, enabled=True,
        mode="paper", symbols=[], capital=Decimal("10000"))


def _trade(cfg, *, rule="manual_take", status="OPEN", side="BUY",
           entry=100, stop=99, target=102, care=None, r=None, reason="",
           days=1):
    from bot_program.models import AssetBotTrade
    meta = {"initial_stop_loss": float(stop), "value_per_unit": 1.0}
    if care is not None:
        meta["care"] = care
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class="crypto", symbol="BTCUSD", side=side,
        qty=Decimal("1"), entry_price=Decimal(str(entry)),
        stop_loss=Decimal(str(stop)), take_profit=Decimal(str(target)),
        status=status, paper=True, rule_name=rule, realized_r=r,
        reason=reason, metadata=meta)
    if status == "CLOSED":
        AssetBotTrade.objects.filter(pk=t.pk).update(
            closed_at=timezone.now() - timedelta(days=days))
    return t


class TheAdvisoryTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("ec_u", password="x")
        cls.cfg = _cfg(cls.user)

    def setUp(self):
        cache.clear()

    def _adv(self, trade, r):
        from bot_program.manual_close import early_close_advisory
        return early_close_advisory(trade, r)

    def test_a_winner_short_of_its_target_is_warned(self):
        adv = self._adv(_trade(self.cfg), 0.28)
        self.assertTrue(adv["warn"])
        self.assertEqual(adv["target_r"], 2.0)
        self.assertIn("+0.28R now, its target is +2.00R", adv["reason"])
        self.assertIn("break-even once it reaches +1R", adv["reason"])
        self.assertIn("the choice is yours", adv["reason"])

    def test_a_loser_or_a_scratch_is_not_warned(self):
        t = _trade(self.cfg)
        self.assertFalse(self._adv(t, -0.5)["warn"])
        self.assertFalse(self._adv(t, 0.0)["warn"])
        self.assertFalse(self._adv(t, None)["warn"])

    def test_a_winner_at_or_past_its_target_is_not_warned(self):
        self.assertFalse(self._adv(_trade(self.cfg), 2.1)["warn"])

    def test_a_short_is_measured_the_other_way(self):
        t = _trade(self.cfg, side="SELL", entry=100, stop=101, target=97)
        adv = self._adv(t, 0.5)
        self.assertTrue(adv["warn"])
        self.assertEqual(adv["target_r"], 3.0)

    def test_what_it_has_seen_and_its_protection_are_said(self):
        t = _trade(self.cfg, care={"mfe_r": 1.4, "soft_stop": 100.1,
                                   "soft_why": "breakeven"})
        adv = self._adv(t, 0.3)
        self.assertIn("It has already been +1.40R.", adv["reason"])
        self.assertIn("protected", adv["reason"])
        self.assertNotIn("once it reaches +1R", adv["reason"])

    def test_the_lane_payoff_is_quoted_once_the_sample_is_enough(self):
        from bot_program.manual_close import EARLY_CLOSE_MIN_SAMPLE
        for i in range(EARLY_CLOSE_MIN_SAMPLE):
            _trade(self.cfg, status="CLOSED",
                   r=(0.3 if i % 3 else -1.0), reason="x")
        # a bots row must not enter the manual lane's numbers
        _trade(self.cfg, rule="golden_cross", status="CLOSED", r=-5.0)
        adv = self._adv(_trade(self.cfg), 0.28)
        self.assertIn("your hand-taken winners averaged +0.30R", adv["reason"])
        self.assertIn("must average", adv["reason"])

    def test_a_thin_lane_is_not_quoted(self):
        _trade(self.cfg, status="CLOSED", r=0.3)
        adv = self._adv(_trade(self.cfg), 0.28)
        self.assertTrue(adv["warn"])
        self.assertNotIn("averaged", adv["reason"])


class ThePreviewCarriesItTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("ec_p", password="x")

    def setUp(self):
        cache.clear()

    def test_the_close_preview_and_close_all_carry_it(self):
        from bot_program.manual_close import preview_close
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        from signals.models import Signal
        inst = _quote("BTCUSD", 60000)
        sig = Signal.objects.create(
            instrument=inst, signal_type="technical", direction="bullish",
            urgency="high", title="t", description="d", rule_name="r",
            score=0.8, sub_scores={}, price_at_signal=Decimal("60000"),
            suggested_entry=Decimal("60000"), suggested_stop=Decimal("59100"),
            suggested_target=Decimal("61800"), is_active=True)
        out = execute_take_trade(self.user, sig)
        self.assertTrue(out.get("ok"), out)
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        _quote("BTCUSD", 60400)          # a winner, short of 61800
        p = preview_close(self.user, trade)
        self.assertNotIn("error", p)
        self.assertGreater(p["r"], 0)
        self.assertTrue(p["early_close"]["warn"], p["early_close"])

        self.client.force_login(self.user)
        resp = self.client.post("/positions/close-all/preview/",
                                HTTP_HOST="127.0.0.1")
        body = resp.json()
        self.assertEqual(body["early_count"], 1)
        self.assertEqual(body["early"][0]["symbol"], "BTCUSD")


class TheDialogsRenderItTests(SimpleTestCase):

    @staticmethod
    def _read(*parts):
        from pathlib import Path
        from django.conf import settings
        return Path(settings.BASE_DIR, *parts).read_text(encoding="utf-8")

    def test_the_overlay_renders_a_warning_block(self):
        js = self._read("static", "js", "sv-overlay.js")
        self.assertIn("opts.warn && opts.warn.text", js)
        self.assertIn('data-role="warn"', js)

    def test_single_close_all_and_selected_say_it_and_never_block(self):
        base = self._read("templates", "base.html")
        self.assertIn("CLOSING A WINNER EARLY", base)
        self.assertIn("(early ? ' ANYWAY' : '')", base)
        plist = self._read("templates", "dashboard", "positions_list.html")
        self.assertIn("earlyWarn(p)", plist)
        self.assertIn('(early ? " ANYWAY" : "")', plist)
        sel = self._read("static", "js", "sv-close-advice.js")
        self.assertIn("WINNER(S) EARLY", sel)
        self.assertIn('(earlyN ? " ANYWAY" : "")', sel)
