"""A winner that becomes a loser, and the two rules that stop it.

A Brent position ran into profit and was booked as a loss: price came
back through entry and hit the stop exactly where it had been placed at
entry. Nothing was ever going to move it. `trail_pct` existed but
defaults to 0, is exposed in no interface, and there was no break-even
rule at all.

Both rules obey the same invariants, and the tests below are mostly
about those rather than about the happy path:

  * a stop only ever TIGHTENS — loosening one turns a defined loss into
    an open-ended one;
  * R is measured against the stop the trade OPENED with, never the one
    these rules just moved, or risk and reward become the same quantity
    and every managed winner scores ~1R;
  * a stop is never placed on the wrong side of the mark, which would
    close the position at market on the next tick and book it as a
    stop-out the thesis never took.

Run with:  python manage.py test tests.test_stop_rules
"""
from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase


class _Trade:
    """Enough of an AssetBotTrade to exercise the pure rules."""

    def __init__(self, side="BUY", entry="100", stop="98", initial=None):
        self.id = 1
        self.side = side
        self.symbol = "BRNUSD"
        self.entry_price = Decimal(entry)
        self.stop_loss = Decimal(stop)
        self.metadata = {"initial_stop_loss": float(initial or stop)}
        self.saved = 0

    def save(self, update_fields=None):
        self.saved += 1


class RIsMeasuredFromTheOpeningStopTests(SimpleTestCase):
    def test_one_r_is_the_distance_to_the_frozen_stop(self):
        from bot_program.engine.trailing import unrealised_r
        t = _Trade(entry="100", stop="98")            # 1R = 2.00
        self.assertEqual(unrealised_r(t, Decimal("102")), Decimal("1"))
        self.assertEqual(unrealised_r(t, Decimal("104")), Decimal("2"))

    def test_a_moved_stop_does_not_change_r(self):
        """The whole reason grading freezes it: measuring against a stop
        these rules just moved makes every managed winner score 1R."""
        from bot_program.engine.trailing import unrealised_r
        t = _Trade(entry="100", stop="98")
        t.stop_loss = Decimal("101")                  # already trailed
        self.assertEqual(unrealised_r(t, Decimal("104")), Decimal("2"))

    def test_a_short_measures_the_other_way(self):
        from bot_program.engine.trailing import unrealised_r
        t = _Trade(side="SELL", entry="100", stop="102")
        self.assertEqual(unrealised_r(t, Decimal("98")), Decimal("1"))

    def test_no_frozen_stop_means_no_answer(self):
        """None, not zero — a caller must not act on a guess."""
        from bot_program.engine.trailing import unrealised_r
        t = _Trade()
        t.metadata = {}
        self.assertIsNone(unrealised_r(t, Decimal("104")))

    def test_a_zero_width_risk_is_not_a_denominator(self):
        from bot_program.engine.trailing import unrealised_r
        t = _Trade(entry="100", stop="100")
        self.assertIsNone(unrealised_r(t, Decimal("104")))


class BreakEvenTests(SimpleTestCase):
    def test_it_does_not_fire_before_the_trigger(self):
        from bot_program.engine.trailing import apply_breakeven
        t = _Trade(entry="100", stop="98")            # 1R = 2.00
        self.assertFalse(apply_breakeven(t, Decimal("101"), at_r=1.0))
        self.assertEqual(t.stop_loss, Decimal("98"))

    def test_it_moves_the_stop_to_entry_at_the_trigger(self):
        from bot_program.engine.trailing import apply_breakeven
        t = _Trade(entry="100", stop="98")
        self.assertTrue(apply_breakeven(t, Decimal("102"), at_r=1.0))
        self.assertEqual(t.stop_loss, Decimal("100"))

    def test_the_buffer_puts_the_exit_past_its_own_costs(self):
        """A stop exactly at entry still books a small loss once the
        spread and both commissions come out of it."""
        from bot_program.engine.trailing import apply_breakeven
        t = _Trade(entry="100", stop="98")
        apply_breakeven(t, Decimal("102"), at_r=1.0, buffer_r=0.1)
        self.assertEqual(t.stop_loss, Decimal("100.2"))   # entry + 0.1R

    def test_a_short_breaks_even_below_entry(self):
        from bot_program.engine.trailing import apply_breakeven
        t = _Trade(side="SELL", entry="100", stop="102")
        apply_breakeven(t, Decimal("98"), at_r=1.0, buffer_r=0.1)
        self.assertEqual(t.stop_loss, Decimal("99.8"))

    def test_it_fires_only_once(self):
        """Re-running it would drag a trailed stop back toward entry."""
        from bot_program.engine.trailing import apply_breakeven
        t = _Trade(entry="100", stop="98")
        self.assertTrue(apply_breakeven(t, Decimal("102"), at_r=1.0))
        t.stop_loss = Decimal("103")                   # trailed on since
        self.assertFalse(apply_breakeven(t, Decimal("106"), at_r=1.0))
        self.assertEqual(t.stop_loss, Decimal("103"))

    def test_it_never_loosens_an_already_tighter_stop(self):
        from bot_program.engine.trailing import apply_breakeven
        t = _Trade(entry="100", stop="98")
        t.stop_loss = Decimal("101")
        self.assertFalse(apply_breakeven(t, Decimal("102"), at_r=1.0))
        self.assertEqual(t.stop_loss, Decimal("101"))

    def test_a_refused_move_stays_re_armable(self):
        """Refusing must not silently disarm the rule for good."""
        from bot_program.engine.trailing import apply_breakeven
        t = _Trade(entry="100", stop="98")
        t.stop_loss = Decimal("101")
        apply_breakeven(t, Decimal("102"), at_r=1.0)
        self.assertNotIn("breakeven_armed", t.metadata)

    def test_off_by_default(self):
        from bot_program.engine.trailing import apply_breakeven
        t = _Trade()
        self.assertFalse(apply_breakeven(t, Decimal("110"), at_r=0))


class AStopNeverLandsPastTheMarkTests(SimpleTestCase):
    """The guard a live trade taught: a stop on the wrong side of price
    closes at market next tick and books a loss nobody took."""

    def test_breakeven_is_refused_when_the_buffer_overshoots(self):
        from bot_program.engine.trailing import apply_breakeven
        t = _Trade(entry="100", stop="98")
        # 5R of buffer would put the stop at 110 with the mark at 102.
        self.assertFalse(apply_breakeven(t, Decimal("102"), at_r=1.0,
                                         buffer_r=5))
        self.assertEqual(t.stop_loss, Decimal("98"))

    def test_the_same_holds_for_a_short(self):
        from bot_program.engine.trailing import apply_breakeven
        t = _Trade(side="SELL", entry="100", stop="102")
        self.assertFalse(apply_breakeven(t, Decimal("98"), at_r=1.0,
                                         buffer_r=5))
        self.assertEqual(t.stop_loss, Decimal("102"))


class TrailingTests(SimpleTestCase):
    def test_it_still_ratchets(self):
        from bot_program.engine.trailing import update_trailing_stop
        t = _Trade(entry="100", stop="98")
        self.assertTrue(update_trailing_stop(t, Decimal("110"), 5.0))
        self.assertEqual(t.stop_loss, Decimal("104.50"))

    def test_it_never_loosens(self):
        from bot_program.engine.trailing import update_trailing_stop
        t = _Trade(entry="100", stop="98")
        update_trailing_stop(t, Decimal("110"), 5.0)      # -> 104.50
        self.assertFalse(update_trailing_stop(t, Decimal("106"), 5.0))
        self.assertEqual(t.stop_loss, Decimal("104.50"))

    def test_start_r_delays_the_ratchet(self):
        """Trailing from the first tick in profit turns a position that
        has barely moved into a scratch on the first pullback."""
        from bot_program.engine.trailing import update_trailing_stop
        t = _Trade(entry="100", stop="98")               # 1R = 2.00
        self.assertFalse(update_trailing_stop(t, Decimal("101"), 5.0,
                                              start_r=1.0))
        self.assertTrue(update_trailing_stop(t, Decimal("104"), 1.0,
                                             start_r=1.0))

    def test_start_r_defaults_to_the_old_behaviour(self):
        from bot_program.engine.trailing import update_trailing_stop
        t = _Trade(entry="100", stop="98")
        self.assertTrue(update_trailing_stop(t, Decimal("110"), 5.0))

    def test_a_short_trails_downward(self):
        from bot_program.engine.trailing import update_trailing_stop
        t = _Trade(side="SELL", entry="100", stop="102")
        self.assertTrue(update_trailing_stop(t, Decimal("90"), 5.0))
        self.assertEqual(t.stop_loss, Decimal("94.50"))

    def test_off_by_default(self):
        from bot_program.engine.trailing import update_trailing_stop
        t = _Trade()
        self.assertFalse(update_trailing_stop(t, Decimal("110"), 0))


class TheMovesAreRecordedOnTheRowTests(SimpleTestCase):
    def test_a_move_says_why_and_where(self):
        from bot_program.engine.trailing import apply_breakeven
        t = _Trade(entry="100", stop="98")
        apply_breakeven(t, Decimal("102"), at_r=1.0)
        moves = t.metadata["stop_moves"]
        self.assertEqual(moves[-1]["why"], "breakeven")
        self.assertEqual(Decimal(moves[-1]["to"]), Decimal("100"))

    def test_the_log_is_bounded(self):
        """This runs every tick on an open position and the row is read
        by the UI."""
        from bot_program.engine.trailing import update_trailing_stop
        t = _Trade(entry="100", stop="98")
        for i in range(40):
            update_trailing_stop(t, Decimal(110 + i), 5.0)
        self.assertLessEqual(len(t.metadata["stop_moves"]), 20)


class TheBrentCaseTests(SimpleTestCase):
    """The trade that prompted this: long, ran to +2R, gave it all back."""

    def _run(self, path, **knobs):
        from bot_program.engine.trailing import (
            apply_breakeven, update_trailing_stop,
        )
        t = _Trade(entry="100", stop="98")            # 1R = 2.00
        for px in path:
            px = Decimal(str(px))
            if knobs.get("at_r"):
                apply_breakeven(t, px, knobs["at_r"],
                                knobs.get("buffer_r", 0))
            if knobs.get("trail_pct"):
                update_trailing_stop(t, px, knobs["trail_pct"],
                                     knobs.get("start_r", 0))
            hit = (px <= t.stop_loss if t.side == "BUY"
                   else px >= t.stop_loss)
            if hit:
                return t.stop_loss
        return None

    def test_with_nothing_configured_it_gives_everything_back(self):
        """What actually happened."""
        exit_at = self._run([101, 103, 104, 102, 99, 97])
        self.assertEqual(exit_at, Decimal("98"))       # the original stop

    def test_breakeven_turns_it_into_a_scratch(self):
        exit_at = self._run([101, 103, 104, 102, 99, 97],
                            at_r=1.0, buffer_r=0.1)
        self.assertEqual(exit_at, Decimal("100.2"))    # entry + costs

    def test_trailing_keeps_part_of_the_run(self):
        exit_at = self._run([101, 103, 104, 102, 99, 97],
                            at_r=1.0, buffer_r=0.1, trail_pct=2.0,
                            start_r=1.0)
        self.assertIsNotNone(exit_at)
        self.assertGreater(exit_at, Decimal("100.2"))


class ATrailNeverRatchetsOnALoserTests(SimpleTestCase):
    """The gate the rewrite dropped.

    base.py used to require the position be in profit before trailing,
    and the rewrite leaned on start_r instead — which defaults to 0. With
    a TIGHT trail_pct the candidate can still land above a losing long's
    stop and be accepted as "tighter", so the stop marches up on a trade
    that is DOWN and cuts it early.
    """

    def test_a_small_trail_does_not_tighten_a_losing_long(self):
        from bot_program.engine.trailing import update_trailing_stop
        t = _Trade(entry="100", stop="98")
        # 99 * (1 - 0.005) = 98.505, which IS tighter than 98.
        self.assertFalse(update_trailing_stop(t, Decimal("99"), 0.5))
        self.assertEqual(t.stop_loss, Decimal("98"))

    def test_a_small_trail_does_not_tighten_a_losing_short(self):
        from bot_program.engine.trailing import update_trailing_stop
        t = _Trade(side="SELL", entry="100", stop="102")
        self.assertFalse(update_trailing_stop(t, Decimal("101"), 0.5))
        self.assertEqual(t.stop_loss, Decimal("102"))

    def test_exactly_at_entry_is_not_profit(self):
        from bot_program.engine.trailing import update_trailing_stop
        t = _Trade(entry="100", stop="98")
        self.assertFalse(update_trailing_stop(t, Decimal("100"), 0.5))

    def test_in_profit_still_trails(self):
        from bot_program.engine.trailing import update_trailing_stop
        t = _Trade(entry="100", stop="98")
        self.assertTrue(update_trailing_stop(t, Decimal("101"), 0.5))
        self.assertEqual(t.stop_loss, Decimal("100.495"))


class TheRefusalReachesProductionTests(TestCase):
    """Run the REAL entry point, not the helper.

    The first version of this work put the broker-protected disclosure
    inside `_update_trailing_stop` — which `manage_positions` never
    reaches for a protected row, because it `continue`s five lines
    earlier. The pre-existing test called `_update_trailing_stop`
    DIRECTLY, so it passed green against code production could not
    execute, and reported success for a warning that could never fire.

    A live IBKR or OANDA config is exactly where that matters: the
    operator fills in "Break-even at 1.0R", saves, and every bracketed
    position keeps running to its entry stop in total silence. The form
    promising stop management is what makes the silence dangerous.
    """

    def _bot_and_trade(self, extras, protected=True):
        from decimal import Decimal as D

        from django.contrib.auth.models import User
        from django.utils import timezone as tz

        from bot_program.asset_engine.stock_bot import StockBot
        from bot_program.models import AssetBotConfig, AssetBotTrade

        user = User.objects.create_user("inert_u", password="x")
        cfg = AssetBotConfig.objects.create(
            user=user, asset_class="stock", name="INERT", mode="paper",
            symbols=["AAPL"], capital=D("10000"), enabled=True, extras=extras)
        meta = {"initial_stop_loss": 98.0}
        if protected:
            meta["protected"] = True
        trade = AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="AAPL", side="BUY",
            qty=D("10"), entry_price=D("100"), stop_loss=D("98"),
            take_profit=D("110"), status="OPEN", paper=True,
            metadata=meta, opened_at=tz.now())
        return StockBot(cfg), trade

    def _run(self, bot, mark="104"):
        from decimal import Decimal as D
        from unittest.mock import MagicMock, patch

        with patch("bot_program.engine.broker_router.client_for_symbol",
                   return_value=MagicMock()), \
                patch.object(type(bot), "_is_paper_client",
                             return_value=False), \
                patch.object(type(bot), "_mark_price", return_value=D(mark)):
            bot.manage_positions()

    def test_a_protected_row_is_stamped_through_the_real_path(self):
        bot, trade = self._bot_and_trade({"breakeven_at_r": 1.0})
        self._run(bot)
        trade.refresh_from_db()
        self.assertEqual(trade.metadata.get("stop_rules_inert"),
                         "broker_protected")

    def test_the_broker_held_stop_is_not_moved(self):
        """The refusal must still refuse — this is a disclosure, not a
        licence to move a stop the broker owns."""
        from decimal import Decimal as D
        bot, trade = self._bot_and_trade({"breakeven_at_r": 1.0})
        self._run(bot)
        trade.refresh_from_db()
        self.assertEqual(trade.stop_loss, D("98"))

    def test_a_config_with_no_stop_rules_is_not_warned(self):
        """A config that never asked for one is owed no warning about it."""
        bot, trade = self._bot_and_trade({})
        self._run(bot)
        trade.refresh_from_db()
        self.assertNotIn("stop_rules_inert", trade.metadata)

    def test_an_unprotected_row_actually_moves_its_stop(self):
        """The other half: where the rules DO apply, they apply."""
        from decimal import Decimal as D
        bot, trade = self._bot_and_trade({"breakeven_at_r": 1.0},
                                         protected=False)
        self._run(bot, mark="104")
        trade.refresh_from_db()
        self.assertEqual(trade.stop_loss, D("100"))
        self.assertNotIn("stop_rules_inert", trade.metadata)


class SavingTheFormDoesNotDisarmTheRulesTests(TestCase):
    """"Blank means leave as-is" has to be true of the DICT too.

    The bot config form is a create-or-overwrite: it posts the whole
    extras blob from a box that defaults to "{}". So saving it to change
    one unrelated number replaced every stored key with nothing — which
    would switch these stop rules back off on the very next edit,
    silently, which is precisely the failure they exist to prevent.
    """

    def setUp(self):
        from django.contrib.auth.models import User
        self.user = User.objects.create_superuser("frm_u", "f@x.x", "x")
        self.client.force_login(self.user)

    def _post(self, **over):
        data = {"asset_class": "stock", "name": "FORM", "mode": "paper",
                "symbols": "[]", "extras": "{}", "capital": "10000",
                "position_size_pct": "2", "max_concurrent_positions": "5",
                "max_daily_loss_pct": "2"}
        data.update(over)
        return self.client.post("/admin-dashboard/asset-bots/create/", data)

    def _extras(self):
        from bot_program.models import AssetBotConfig
        return AssetBotConfig.objects.get(user=self.user, name="FORM").extras

    def test_the_knobs_are_stored(self):
        self._post(breakeven_at_r="1.0", trail_pct="2.0")
        self.assertEqual(self._extras().get("breakeven_at_r"), 1.0)
        self.assertEqual(self._extras().get("trail_pct"), 2.0)

    def test_a_later_save_does_not_wipe_them(self):
        """The whole point: change the capital, keep the stop rules."""
        self._post(breakeven_at_r="1.0", trail_pct="2.0")
        self._post(capital="20000")
        self.assertEqual(self._extras().get("breakeven_at_r"), 1.0)
        self.assertEqual(self._extras().get("trail_pct"), 2.0)

    def test_an_explicit_zero_turns_a_rule_off(self):
        self._post(breakeven_at_r="1.0")
        self._post(breakeven_at_r="0")
        self.assertEqual(self._extras().get("breakeven_at_r"), 0.0)

    def test_a_key_set_through_the_json_box_survives_too(self):
        self._post(extras='{"max_signal_age_hours": 8}')
        self._post(trail_pct="2.0")
        self.assertEqual(self._extras().get("max_signal_age_hours"), 8)
        self.assertEqual(self._extras().get("trail_pct"), 2.0)

    def test_a_negative_value_is_refused(self):
        resp = self._post(trail_pct="-1")
        self.assertEqual(resp.status_code, 302)
        from bot_program.models import AssetBotConfig
        self.assertFalse(
            AssetBotConfig.objects.filter(user=self.user, name="FORM").exists())
