"""THE ENGINE'S TWO HOOKS FOR THE PRICE OF A CLOSE NOBODY SAW (2026-10-07,
PR50; bot_program/venue_exit.py, tests/test_venue_exit.py).

NVDA #131: at 11:07:59 the manage tick saw 237.9, beyond the 238.03 stop
eToro held, and the 11:15 reconcile booked the close at the last mark
(238.16). The reconcile can now book it AT the level, and only on
evidence the engine itself wrote:
  * the tick's CROSSING stamp (AssetBot.manage_positions ->
    venue_exit.note_crossing): the first accepted mark beyond the stop or
    the target eToro holds since it last showed the position open, written
    right after the venue mark, inside the same real-row block, with no
    "if protected:" around it;
  * the stop move's "when" (AssetBot._move_broker_stop): the moment the
    venue accepted a new level, so a crossing of the OLD level is never
    evidence for the new one (venue_exit._level_changed_at).

Build spec tests 36, 39 and 41; the rest of the reconcile part lives in
tests/test_venue_exit.py, whose fixtures these borrow.

Run with:  python manage.py test tests.test_venue_exit_hooks
"""
import inspect
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from tests.test_venue_exit import ROUTER, Base


class TheTickStampTests(Base):

    def _tick(self, bot, client):
        with mock.patch(ROUTER, return_value=client), \
                mock.patch("bot_program.mark_sanity.check",
                           return_value={"ok": True}):
            bot.manage_positions()

    def test_the_tick_stamps_the_first_crossing(self):
        from bot_program import venue_exit
        from bot_program.asset_engine.base import make_bot
        t = self._nvda()
        bot = make_bot(self.cfg)
        client = mock.MagicMock(spec=["ticker"])
        # a mark short of the stop (238.03) and the target (245.50): nothing
        client.ticker.return_value = {"lastPrice": "239.4", "symbol": "NVDA"}
        self._tick(bot, client)
        t.refresh_from_db()
        self.assertNotIn(venue_exit.CROSSED_KEY, t.metadata)
        # the first mark beyond the stop eToro holds is kept
        client.ticker.return_value = {"lastPrice": "237.9", "symbol": "NVDA"}
        before = timezone.now()
        self._tick(bot, client)
        t.refresh_from_db()
        first = t.metadata[venue_exit.CROSSED_KEY]
        self.assertEqual((first["level"], first["price"], first["mark"]),
                         ("stop", 238.03, 237.9))
        self.assertGreaterEqual(parse_datetime(first["at"]), before)
        # a second, lower tick of the same episode keeps the first
        client.ticker.return_value = {"lastPrice": "237.5", "symbol": "NVDA"}
        self._tick(bot, client)
        t.refresh_from_db()
        self.assertEqual(t.metadata[venue_exit.CROSSED_KEY], first)
        # the venue mark the stamp follows was written on the same tick
        self.assertIn("venue_mark", t.metadata)


class TheWiringTests(SimpleTestCase):

    def test_the_crossing_sits_after_the_venue_mark_and_before_the_vanished_check(self):
        from bot_program.asset_engine import base
        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.manage_positions)
        gate = src.index('mark_sanity.check(self, trade, price, client)["ok"]')
        stamp = src.index("venue_mark.stamp(trade, price")
        cross = src.index("venue_exit.note_crossing(trade, price)")
        vanished = src.index("self._protection_vanished(trade, client)")
        self.assertLess(gate, stamp)
        self.assertLess(stamp, cross)
        self.assertLess(cross, vanished)
        self.assertEqual(src.count("venue_exit.note_crossing("), 1)
        # inside the venue mark's own real-row block, at its indentation,
        # and under no "if protected:" (an unprotected row's level is read
        # by note_crossing itself)
        block = src.rindex("if not trade.paper:", 0, stamp)
        self.assertNotIn("if protected", src[block:cross])

        def indent(at):
            line = src[src.rindex("\n", 0, at) + 1:at]
            return len(line) - len(line.lstrip())
        self.assertEqual(indent(cross), indent(stamp))
        # imported where it is used: base.py loads without venue_exit
        top = [ln for ln in inspect.getsource(base).splitlines()
               if ln.startswith(("import ", "from "))]
        self.assertFalse([ln for ln in top if "venue_exit" in ln], top)
        self.assertIn("from bot_program import venue_exit", src[stamp:cross])
        # the care still comes before the first protected-only branch
        # (tests/test_aragorn.py)
        self.assertLess(src.index("_care(self, trade, price, client)"),
                        src.index("if protected:\n"))


class TheStopMoveTimeTests(Base):

    def _client(self, ok=True):
        client = mock.MagicMock(spec=["modify_protective", "ticker"])
        client.modify_protective.side_effect = (
            lambda oid, price: {"ok": True, "price": price} if ok
            else {"ok": False, "reason": "eToro refused (400)"})
        return client

    def test_an_accepted_stop_move_carries_its_time(self):
        from bot_program import venue_exit
        from bot_program.asset_engine.base import make_bot
        t = self._nvda()
        bot = make_bot(self.cfg)
        self.assertIsNone(venue_exit._level_changed_at(t))
        before = timezone.now()
        self.assertTrue(bot._move_broker_stop(t, 240.1, self._client(),
                                              Decimal("238.5"), "trail"))
        after = timezone.now()
        t.refresh_from_db()
        move = t.metadata["stop_moves"][-1]
        self.assertEqual((move["to"], move["asked"], move["at"], move["why"]),
                         ("238.5", "238.5", "240.1", "trail:broker"),
                         "\"at\" stays the mark the move was made at")
        when = parse_datetime(move["when"])
        self.assertTrue(timezone.is_aware(when))
        self.assertTrue(before <= when <= after, (before, when, after))
        self.assertEqual(t.stop_loss, Decimal("238.5"))
        # the reconcile reads it: a level that changed at `when`
        self.assertEqual(venue_exit._level_changed_at(t), when)
        # a refused move writes no move and no time
        self.assertFalse(bot._move_broker_stop(t, 241.0, self._client(False),
                                               Decimal("239.0"), "trail"))
        t.refresh_from_db()
        self.assertEqual(len(t.metadata["stop_moves"]), 1)
        self.assertEqual(t.metadata["stop_moves"][-1], move)
