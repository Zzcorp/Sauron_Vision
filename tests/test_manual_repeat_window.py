"""A second identical manual order inside a minute is a second CLICK.

The platform's own briefing found it in the live book: four `manual_take`
XAUUSD BUY tickets inside eight seconds, identical qty and identical entry,
about 42% of open exposure in one trade wearing four tickets — and every
risk reading downstream counting four independent bets. The signal path had
been deduped on metadata["signal_id"] since it was written; the signal-LESS
path (the instrument view's BUY/SELL) has no signal id, so it had no guard
at all.

A window, not a ban: scaling in is a real thing an operator does on
purpose, so the refusal expires and says when.

Run with:  python manage.py test tests.test_manual_repeat_window
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from bot_program.manual_trade import (MANUAL_REPEAT_WINDOW_SECONDS,
                                      MANUAL_RULE, manual_config_for)


def _open(cfg, *, symbol="XAUUSD", side="BUY", status="OPEN"):
    """One manual ticket, at the exact size and entry the live book showed."""
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal("0.4191"), entry_price=Decimal("4547.118"),
        status=status, paper=True, rule_name=MANUAL_RULE,
        metadata={"manual": True, "signal_id": None})


class RepeatWindowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("dbl_click", password="x")
        self.cfg = manual_config_for(self.user, "commodity")
        from instruments.models import Instrument
        self.inst, _ = Instrument.objects.get_or_create(
            symbol="XAUUSD",
            defaults={"name": "Gold", "asset_class": "commodity",
                      "is_active": True})

    def _backdate(self, trade, seconds):
        from datetime import timedelta
        from bot_program.models import AssetBotTrade
        AssetBotTrade.objects.filter(pk=trade.pk).update(
            opened_at=timezone.now() - timedelta(seconds=seconds))

    def _execute(self):
        from bot_program.manual_trade import execute_asset_trade
        return execute_asset_trade(self.user, self.inst, "BUY")

    def test_an_identical_order_seconds_later_is_refused(self):
        first = _open(self.cfg)
        self._backdate(first, 8)          # the live case: 8 seconds apart
        result = self._execute()
        self.assertIn("error", result)
        self.assertIn(str(first.id), result["error"])
        self.assertIn("double-click", result["error"])

    def test_the_refusal_says_how_long_to_wait(self):
        first = _open(self.cfg)
        self._backdate(first, 8)
        error = self._execute()["error"]
        # Not a dead end: the deliberate second entry is a wait, not a
        # mystery, so the remaining window is named.
        self.assertRegex(error, r"try again in \d+s")

    def test_past_the_window_a_deliberate_second_entry_is_allowed(self):
        """Scaling in is a real decision — the guard must expire."""
        first = _open(self.cfg)
        self._backdate(first, MANUAL_REPEAT_WINDOW_SECONDS + 30)
        result = self._execute()
        # It may still fail for an unrelated reason (no mark in a bare test
        # DB) — what must NOT happen is the duplicate refusal.
        self.assertNotIn("double-click", result.get("error", ""))

    def test_the_other_side_is_not_a_duplicate(self):
        """Long then short is a reversal, not a double-click. It has its own
        problems (the briefing found a self-hedge) but this guard is not the
        place to decide that — refusing it here would silently block a
        legitimate flip."""
        first = _open(self.cfg, side="SELL")
        self._backdate(first, 5)
        self.assertNotIn("double-click", self._execute().get("error", ""))

    def test_a_different_symbol_is_not_a_duplicate(self):
        first = _open(self.cfg, symbol="COFFEEUSD")
        self._backdate(first, 5)
        self.assertNotIn("double-click", self._execute().get("error", ""))

    def test_a_closed_position_does_not_block_a_new_one(self):
        """Closed and reopened inside a minute is a decision, not a stutter."""
        first = _open(self.cfg, status="CLOSED")
        self._backdate(first, 5)
        self.assertNotIn("double-click", self._execute().get("error", ""))


class SignalPathUnchangedTests(TestCase):
    """The signal path's dedupe has no window and must not grow one — one
    idea is one position for as long as that position is open."""

    def test_a_signal_taken_an_hour_ago_is_still_taken(self):
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        from instruments.models import Instrument
        from signals.models import Signal
        user = User.objects.create_user("sig_dbl", password="x")
        cfg = manual_config_for(user, "commodity")
        inst, _ = Instrument.objects.get_or_create(
            symbol="XAGUSD",
            defaults={"name": "Silver", "asset_class": "commodity",
                      "is_active": True})
        signal = Signal.objects.create(
            instrument=inst, rule_name="r", title="t", direction="bullish",
            score=0.9, is_active=True, price_at_signal=Decimal("30"))
        trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="commodity", symbol="XAGUSD", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("30"), status="OPEN",
            paper=True, rule_name=MANUAL_RULE,
            metadata={"manual": True, "signal_id": signal.id})
        from datetime import timedelta
        AssetBotTrade.objects.filter(pk=trade.pk).update(
            opened_at=timezone.now() - timedelta(hours=1))
        result = execute_take_trade(user, signal)
        self.assertIn("already taken", result.get("error", ""))
