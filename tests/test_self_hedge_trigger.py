"""Holding both sides of one instrument is a state nothing could see.

The platform's own briefing found it in the live book: USDCHF held BUY by
`manual_take` and SELL by `bollinger_squeeze_breakout`, at the same time, by
the same operator. The position watcher's concentration trigger reads the
correlation audit, which answers "how many rules hold this same symbol and
SAME side" — the doubling-up case. The opposite case is the more expensive
one (the pair is flat and still paying both spreads to sit there) and was
visible to nothing.

Run with:  python manage.py test tests.test_self_hedge_trigger
"""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase

from brain.position_review import _self_hedge, evaluate_triggers


def _cfg(user, asset_class="forex"):
    from bot_program.models import AssetBotConfig
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class=asset_class, name="hedge test",
        defaults={"capital": Decimal("10000")})
    return cfg


def _open(cfg, *, symbol="USDCHF", side="BUY", rule="manual_take"):
    from bot_program.models import AssetBotTrade
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol=symbol, side=side,
        qty=Decimal("1000"), entry_price=Decimal("0.9"),
        stop_loss=Decimal("0.89"), status="OPEN", paper=True,
        rule_name=rule, metadata={"initial_stop_loss": 0.89})


def _row(trade, user):
    """The normalised shape `_self_hedge` reads."""
    from brain.position_review import _side_label, _dir_sign, BOOK_BOT
    return {"book": BOOK_BOT, "position_id": trade.id,
            "symbol": trade.symbol, "side": _side_label(trade.side),
            "dir_sign": _dir_sign(trade.side), "user": user,
            "rule_name": trade.rule_name, "qty": float(trade.qty),
            "asset_class": trade.asset_class}


class SelfHedgeDetectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("hedger")
        self.cfg = _cfg(self.user)

    def test_the_opposite_leg_is_found(self):
        long_leg = _open(self.cfg, side="BUY", rule="manual_take")
        _open(self.cfg, side="SELL", rule="bollinger_squeeze_breakout")
        found = _self_hedge(_row(long_leg, self.user))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["side"], "SELL")
        self.assertEqual(found[0]["rule_name"], "bollinger_squeeze_breakout")

    def test_a_position_is_not_its_own_hedge(self):
        only = _open(self.cfg, side="BUY")
        self.assertEqual(_self_hedge(_row(only, self.user)), [])

    def test_two_longs_are_not_a_hedge(self):
        """That is the concentration case, and T11 already owns it."""
        first = _open(self.cfg, side="BUY", rule="a")
        _open(self.cfg, side="BUY", rule="b")
        self.assertEqual(_self_hedge(_row(first, self.user)), [])

    def test_a_different_symbol_is_not_a_hedge(self):
        mine = _open(self.cfg, symbol="USDCHF", side="BUY")
        _open(self.cfg, symbol="EURUSD", side="SELL")
        self.assertEqual(_self_hedge(_row(mine, self.user)), [])

    def test_another_operators_short_is_not_my_hedge(self):
        """Two people each running their own side of a pair is two people
        trading, not one book paying to be flat."""
        other = User.objects.create_user("someone_else")
        mine = _open(self.cfg, side="BUY")
        _open(_cfg(other), side="SELL")
        self.assertEqual(_self_hedge(_row(mine, self.user)), [])

    def test_a_closed_opposite_leg_does_not_count(self):
        from bot_program.models import AssetBotTrade
        mine = _open(self.cfg, side="BUY")
        gone = _open(self.cfg, side="SELL")
        AssetBotTrade.objects.filter(pk=gone.pk).update(status="CLOSED")
        self.assertEqual(_self_hedge(_row(mine, self.user)), [])

    def test_the_cache_is_built_once_and_reused(self):
        _open(self.cfg, side="BUY")
        second = _open(self.cfg, side="SELL")
        cache: dict = {}
        _self_hedge(_row(second, self.user), cache)
        self.assertIn("book_by_symbol", cache)
        # A second call must not re-read the book — the pass measures every
        # position and a per-position scan is what the cache exists to stop.
        with self.assertNumQueries(0):
            _self_hedge(_row(second, self.user), cache)


class SelfHedgeTriggerTests(TestCase):
    def _facts(self, hedges):
        return {"side": "BUY", "stale_quote": False, "self_hedge": hedges,
                "unrealized_r": 0.1, "r_to_stop": 1.1, "r_to_target": 1.9,
                "age_days": 1.0}

    def test_it_fires_and_names_the_other_leg(self):
        fired = evaluate_triggers(self._facts([
            {"book": "bot", "position_id": 42, "side": "SELL",
             "rule_name": "bollinger_squeeze_breakout", "qty": 1000.0}]))
        codes = [t["code"] for t in fired]
        self.assertIn("self_hedge", codes)
        text = next(t["text"] for t in fired if t["code"] == "self_hedge")
        self.assertIn("#42", text)
        self.assertIn("bollinger_squeeze_breakout", text)

    def test_it_stays_quiet_with_no_opposing_leg(self):
        fired = evaluate_triggers(self._facts([]))
        self.assertNotIn("self_hedge", [t["code"] for t in fired])

    def test_a_stale_mark_evaluates_nothing_at_all(self):
        """No verdict on a fossil — the module's standing rule outranks
        this trigger like every other."""
        facts = self._facts([{"book": "bot", "position_id": 1, "side": "SELL",
                              "rule_name": "r", "qty": 1.0}])
        facts["stale_quote"] = True
        self.assertEqual(evaluate_triggers(facts), [])
