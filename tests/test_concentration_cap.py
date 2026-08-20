"""One bet is a symbol and a side, not a ticket.

The platform's own briefing found it three days running: five open XAUUSD
longs, four of them hand-taken, 42% of the book on one instrument that has
no regime probe at all. Every one of those clips was individually inside the
single-position ceiling — nothing was adding them up, so the operator was
refused nothing, a clip at a time, until one adverse print would hit the
book five times at once.

The ceiling is DERIVED from the per-ticket one rather than being a second
knob, so the two cannot drift apart, and it allows two full clips because
scaling into a winner is a real thing a discretionary trader does. Five is a
different bet wearing the same name.

Run with:  python manage.py test tests.test_concentration_cap
"""
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase


def _user(name="conc_u"):
    return get_user_model().objects.create_user(name, password="x")


def _instrument(symbol="XAUUSD", asset_class="commodity"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "is_active": True})
    return inst


def _cfg(user, capital="10000"):
    from bot_program.manual_trade import manual_config_for
    cfg = manual_config_for(user, "commodity")
    cfg.capital = Decimal(capital)
    cfg.save(update_fields=["capital"])
    return cfg


def _clip(cfg, *, symbol="XAUUSD", side="BUY", qty="1", entry="1000"):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal(qty), entry_price=Decimal(entry), status="OPEN",
        paper=True, rule_name="manual_take",
        metadata={"manual": True, "value_per_unit": 1.0})


class ClipAllowanceTests(SimpleTestCase):
    def test_the_ceiling_is_derived_not_a_second_knob(self):
        """Two independent percentages would drift and the operator would
        have to reason about which one bit."""
        from portfolio.risk_gate import CONCENTRATION_CLIP_ALLOWANCE
        self.assertGreater(CONCENTRATION_CLIP_ALLOWANCE, 1.0,
                           "an allowance of 1 bans scaling in outright")
        self.assertEqual(CONCENTRATION_CLIP_ALLOWANCE, 2.0)


class SymbolSideExposureTests(TestCase):
    def setUp(self):
        self.user = _user()
        self.cfg = _cfg(self.user)
        _instrument()

    def test_it_sums_every_clip_on_the_side(self):
        from portfolio.risk_gate import symbol_side_exposure
        _clip(self.cfg)
        _clip(self.cfg)
        held = symbol_side_exposure(self.user, "XAUUSD", "BUY")
        self.assertEqual(held["n"], 2)
        self.assertEqual(held["committed"], 2000.0)

    def test_the_other_side_is_a_different_bet(self):
        from portfolio.risk_gate import symbol_side_exposure
        _clip(self.cfg, side="BUY")
        _clip(self.cfg, side="SELL")
        self.assertEqual(
            symbol_side_exposure(self.user, "XAUUSD", "BUY")["n"], 1)

    def test_another_symbol_is_a_different_bet(self):
        from portfolio.risk_gate import symbol_side_exposure
        _instrument("SILVER")
        _clip(self.cfg)
        _clip(self.cfg, symbol="SILVER")
        self.assertEqual(
            symbol_side_exposure(self.user, "XAUUSD", "BUY")["n"], 1)

    def test_a_close_pending_clip_is_still_exposure(self):
        from bot_program.models import AssetBotTrade
        from portfolio.risk_gate import symbol_side_exposure
        clip = _clip(self.cfg)
        AssetBotTrade.objects.filter(pk=clip.pk).update(status="CLOSE_PENDING")
        self.assertEqual(
            symbol_side_exposure(self.user, "XAUUSD", "BUY")["n"], 1)


class ConcentrationGateTests(TestCase):
    """20% of a 10,000 pool is 2,000 a clip, so the bet ceiling is 4,000."""

    def setUp(self):
        self.user = _user("conc_gate")
        self.cfg = _cfg(self.user)
        _instrument()
        from portfolio.risk_gate import limits_book
        book = limits_book()
        book.current_value = Decimal("10000")
        book.max_single_position_pct = 20.0
        book.save(update_fields=["current_value", "max_single_position_pct"])

    def _state(self, notional):
        from portfolio.risk_gate import concentration_state
        return concentration_state(
            self.user, symbol="XAUUSD", side="BUY",
            asset_class="commodity", notional=notional,
            capital_base=10000.0, base_label="manual pool")

    def test_a_first_clip_is_fine(self):
        self.assertTrue(self._state(1500.0)["ok"])

    def test_a_second_clip_is_still_fine(self):
        """Adding to a winner is a decision, not an accident."""
        _clip(self.cfg, qty="1.5")
        self.assertTrue(self._state(1500.0)["ok"])

    def test_a_third_clip_is_refused(self):
        """The gold pile-on, stopped where it starts being a different bet."""
        _clip(self.cfg, qty="1.5")
        _clip(self.cfg, qty="1.5")
        state = self._state(1500.0)
        self.assertFalse(state["ok"])
        self.assertIn("XAUUSD", state["reason"])
        self.assertIn("2 open ticket(s)", state["reason"])

    def test_the_refusal_shows_the_arithmetic(self):
        _clip(self.cfg, qty="2")
        _clip(self.cfg, qty="2")
        reason = self._state(1500.0)["reason"]
        self.assertIn("4,000.00", reason)   # the ceiling
        self.assertIn("clips of 20%", reason)

    def test_the_opposite_side_does_not_count_against_it(self):
        _clip(self.cfg, qty="2", side="SELL")
        _clip(self.cfg, qty="2", side="SELL")
        self.assertTrue(self._state(1500.0)["ok"])

    def test_an_unset_book_value_is_not_a_ceiling_of_zero(self):
        from portfolio.risk_gate import concentration_state
        state = concentration_state(
            self.user, symbol="XAUUSD", side="BUY", asset_class="commodity",
            notional=1500.0, capital_base=0.0, base_label="manual pool")
        self.assertTrue(state["ok"])
        self.assertIn("never been set", state["reason"])


class DiscretionaryPathTests(TestCase):
    """End to end, on the path that built the pile."""

    def setUp(self):
        self.user = _user("conc_path")
        self.cfg = _cfg(self.user)
        self.inst = _instrument()
        from market_data.models import LiveQuote
        LiveQuote.objects.update_or_create(
            instrument=self.inst,
            defaults={"last": Decimal("1000"), "source": "test"})
        from portfolio.risk_gate import limits_book
        book = limits_book()
        book.current_value = Decimal("10000")
        book.max_single_position_pct = 20.0
        book.save(update_fields=["current_value", "max_single_position_pct"])

    def test_a_third_clip_is_refused_before_anything_is_liquidated(self):
        """The refusal must not arrive AFTER an irreversible funding close —
        that costs the operator the position and the trade for one click."""
        from bot_program.manual_trade import execute_asset_trade
        _clip(self.cfg, qty="2")
        _clip(self.cfg, qty="2")
        out = execute_asset_trade(self.user, self.inst, "BUY")
        self.assertIn("error", out)
        self.assertIn("XAUUSD", out["error"])
        self.assertEqual(out.get("closed", []), [],
                         "something was liquidated before the refusal")


class AdvisoryIsReportedTests(TestCase):
    """`brain_rule_advisory` was consulted on the BOT path and never here, so
    the platform could conclude that hand-taken entries were its only
    negative-expectancy rule, raise `pause_recommended`, and the discretionary
    path would go on firing without ever mentioning it."""

    def test_the_preview_carries_the_advisory(self):
        from unittest.mock import patch
        from bot_program.manual_trade import _manual_rule_advisory
        with patch("brain.context.brain_rule_advisory",
                   return_value=("pause_recommended", "negative expectancy")):
            out = _manual_rule_advisory()
        self.assertTrue(out["flagged"])
        self.assertIn("expectancy", out["reason"])

    def test_a_clean_advisory_is_not_flagged(self):
        from unittest.mock import patch
        from bot_program.manual_trade import _manual_rule_advisory
        with patch("brain.context.brain_rule_advisory",
                   return_value=("allow", "")):
            self.assertFalse(_manual_rule_advisory()["flagged"])

    def test_an_unavailable_brain_never_blocks_a_trade(self):
        """Advice is advice. A control-plane hiccup must not stop a trade."""
        from unittest.mock import patch
        from bot_program.manual_trade import _manual_rule_advisory
        with patch("brain.context.brain_rule_advisory",
                   side_effect=RuntimeError("brain down")):
            out = _manual_rule_advisory()
        self.assertEqual(out["status"], "unknown")
        self.assertFalse(out["flagged"])
