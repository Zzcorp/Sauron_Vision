"""THE MIRROR: a tightened soft stop is copied onto the venue's stop
(2026-10-04, the operator asked for more resilience on open positions).

The position care's soft stop lived on the platform only: with Celery down
or the VPS gone, eToro knew the disaster stop sent at entry and nothing
else. Now a REAL row whose stop rests at the venue gets every TIGHTER soft
stop copied onto the venue's stop through the engine's one mover
(AssetBot._move_broker_stop -> client.modify_protective), tighten-only, at
the instrument's printed precision; the level taken is written on the row
and journaled, a refusal is written and asked again only when the lock
moves or after MIRROR_RETRY_MINUTES. Never a paper row, never with a
close, never without the venue's handle.

Run with:  python manage.py test tests.test_care_mirror
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_aragorn import _switch
from tests.test_risk_limits_bind import _config
from tests.test_scale_out import _trade


def _client(ok=True, reason="eToro refused (400): stop too close to the rate"):
    """A venue whose stop mover accepts (`ok`) or refuses with `reason`."""
    client = mock.MagicMock(spec=["modify_protective", "ticker"])

    def move(oid, price):
        if ok:
            return {"ok": True, "price": price}
        return {"ok": False, "reason": reason}

    client.modify_protective.side_effect = move
    return client


class TheMirrorTests(TestCase):
    """Entry 100, sent stop 98: +1R is 102, the break-even lock 100.2, the
    trail at +2R (mark 104) 102."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("mirror_u", password="x")
        self.cfg = _config(self.user, symbols=["BTCUSD"])
        _switch("aragorn")
        from bot_program.asset_engine.base import make_bot
        self.bot = make_bot(self.cfg)

    def _real(self, symbol="BTCUSD", **meta):
        return _trade(self.cfg, paper=False, symbol=symbol,
                      meta={"protected": True, "protective_trade_id": "P1",
                            **meta})

    def _care(self, trade, price, client, bot=None):
        from bot_program.position_care import care
        return care(bot or self.bot, trade, price, client)

    def test_the_break_even_lock_follows_onto_the_venue_once_then_the_trail(self):
        from bot_program.aragorn_models import AragornAction
        t = self._real()
        client = _client()
        self.assertEqual(self._care(t, 102.2, client), "",
                         "the row stays with the tick")
        client.modify_protective.assert_called_once()
        oid, level = client.modify_protective.call_args.args
        self.assertEqual((oid, float(level)), ("P1", 100.2))
        t.refresh_from_db()
        self.assertEqual(t.stop_loss, Decimal("100.2"), "the row says what the "
                         "venue took")
        care = t.metadata["care"]
        self.assertEqual((care["soft_stop"], care["venue_stop"]), (100.2, 100.2))
        self.assertNotIn("venue_stop_refusal", care)
        self.assertEqual(t.metadata["initial_stop_loss"], 98.0,
                         "the risk denominator never moves")
        self.assertEqual(t.metadata["stop_moves"][-1]["why"],
                         "care breakeven:broker")
        act = AragornAction.objects.get(kind="care_mirror")
        self.assertEqual((act.trade_id, act.symbol), (t.id, "BTCUSD"))
        self.assertIn("REAL MONEY", act.detail)
        self.assertEqual(act.stats["venue_stop"], 100.2)
        # the next tick, the same lock: nothing sent
        self._care(t, 102.3, client)
        self.assertEqual(client.modify_protective.call_count, 1)
        # the trail moves the lock to 102: sent again, once
        self._care(t, 104.0, client)
        self.assertEqual(client.modify_protective.call_count, 2)
        self.assertEqual(float(client.modify_protective.call_args.args[1]), 102.0)
        t.refresh_from_db()
        self.assertEqual(t.stop_loss, Decimal("102"))
        self.assertEqual(t.metadata["care"]["venue_stop"], 102.0)
        self.assertEqual(AragornAction.objects.filter(kind="care_mirror").count(), 2)
        # a pullback that keeps the lock: nothing
        self._care(t, 103.5, client)
        self.assertEqual(client.modify_protective.call_count, 2)

    def test_never_a_paper_row_an_unprotected_row_or_a_venue_that_cannot_move(self):
        client = _client()
        paper = _trade(self.cfg)
        self._care(paper, 102.2, client)
        client.modify_protective.assert_not_called()
        paper.refresh_from_db()
        self.assertEqual(paper.metadata["care"]["soft_stop"], 100.2)
        self.assertNotIn("venue_stop", paper.metadata["care"])
        bare = _trade(self.cfg, paper=False, symbol="ETHUSD")      # no handle
        self._care(bare, 102.2, client)
        client.modify_protective.assert_not_called()
        bare.refresh_from_db()
        self.assertEqual(bare.stop_loss, Decimal("98"))
        self.assertNotIn("venue_stop", bare.metadata["care"])
        dumb = mock.MagicMock(spec=["ticker"])                    # no mover
        t = self._real(symbol="LTCUSD")
        self._care(t, 102.2, dumb)
        t.refresh_from_db()
        self.assertEqual(t.stop_loss, Decimal("98"))
        self.assertEqual(t.metadata["care"]["soft_stop"], 100.2)
        self.assertNotIn("venue_stop", t.metadata["care"])

    def test_a_refusal_is_written_and_asked_again_when_the_lock_moves_or_the_pacing_passes(self):
        from bot_program.aragorn_models import AragornAction
        from bot_program.position_care import MIRROR_RETRY_MINUTES
        t = self._real()
        client = _client(ok=False)
        self._care(t, 102.2, client)
        self.assertEqual(client.modify_protective.call_count, 1)
        t.refresh_from_db()
        self.assertEqual(t.stop_loss, Decimal("98"), "a refused move changes "
                         "nothing on the row")
        care = t.metadata["care"]
        self.assertIn("stop too close", care["venue_stop_refusal"])
        self.assertNotIn("venue_stop", care)
        self.assertEqual(care["venue_asked_for"], 100.2)
        self.assertEqual(care["soft_stop"], 100.2, "the platform's lock stands")
        self.assertFalse(AragornAction.objects.filter(kind="care_mirror").exists())
        # the same lock a tick later: not asked again
        self._care(t, 102.1, client)
        self.assertEqual(client.modify_protective.call_count, 1)
        # the lock moves (the trail at +2R): asked again
        self._care(t, 104.0, client)
        self.assertEqual(client.modify_protective.call_count, 2)
        self.assertEqual(float(client.modify_protective.call_args.args[1]), 102.0)
        # the same lock, under the pacing: not asked
        self._care(t, 103.9, client)
        self.assertEqual(client.modify_protective.call_count, 2)
        # the pacing passes: asked once more
        t.refresh_from_db()
        meta = dict(t.metadata)
        meta["care"] = {**meta["care"], "venue_asked_at": (
            timezone.now() - timedelta(minutes=MIRROR_RETRY_MINUTES + 1)
        ).isoformat()}
        t.metadata = meta
        t.save(update_fields=["metadata"])
        self._care(t, 103.9, client)
        self.assertEqual(client.modify_protective.call_count, 3)
        # and the venue that finally takes it clears the refusal
        t.refresh_from_db()
        meta = dict(t.metadata)
        meta["care"] = {**meta["care"], "venue_asked_at": (
            timezone.now() - timedelta(minutes=MIRROR_RETRY_MINUTES + 1)
        ).isoformat()}
        t.metadata = meta
        t.save(update_fields=["metadata"])
        taker = _client()
        self._care(t, 103.8, taker)
        taker.modify_protective.assert_called_once()
        t.refresh_from_db()
        self.assertEqual(t.stop_loss, Decimal("102"))
        self.assertEqual(t.metadata["care"]["venue_stop"], 102.0)
        self.assertNotIn("venue_stop_refusal", t.metadata["care"])

    def test_tighten_only_a_venue_stop_already_tighter_is_left_alone(self):
        """The operator moved the venue stop to 101 by hand: the break-even
        lock at 100.2 is looser and is never sent; the trail past 101 is."""
        t = self._real()
        t.stop_loss = Decimal("101")
        t.save(update_fields=["stop_loss"])
        client = _client()
        self._care(t, 102.2, client)
        client.modify_protective.assert_not_called()
        t.refresh_from_db()
        self.assertEqual(t.stop_loss, Decimal("101"))
        care = t.metadata["care"]
        self.assertEqual((care["soft_stop"], care["venue_stop"]), (100.2, 101.0))
        self.assertNotIn("venue_stop_refusal", care)
        self._care(t, 102.5, client)
        client.modify_protective.assert_not_called()
        self._care(t, 104.0, client)                       # trail 102 > 101
        client.modify_protective.assert_called_once()
        self.assertEqual(float(client.modify_protective.call_args.args[1]), 102.0)
        t.refresh_from_db()
        self.assertEqual(t.metadata["care"]["venue_stop"], 102.0)

    def test_a_close_is_never_mirrored(self):
        t = self._real(care={"peak": 102.5, "soft_stop": 100.2,
                             "soft_why": "breakeven"})
        client = _client()
        with mock.patch("bot_program.position_care._venue_still_holds",
                        return_value=True), \
                mock.patch.object(type(self.bot), "_close_trade",
                                  return_value=True):
            self.assertEqual(self._care(t, 100.1, client), "closed")
        client.modify_protective.assert_not_called()

    def test_the_manual_lane_is_mirrored_too(self):
        from bot_program.asset_engine.base import make_bot
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
        manual = _config(self.user, name=MANUAL_CONFIG_NAME, symbols=[])
        t = _trade(manual, paper=False,
                   meta={"protected": True, "protective_trade_id": "M1"})
        client = _client()
        self._care(t, 102.2, client, bot=make_bot(manual))
        client.modify_protective.assert_called_once()
        self.assertEqual(client.modify_protective.call_args.args, ("M1", 100.2))
        t.refresh_from_db()
        self.assertEqual(t.stop_loss, Decimal("100.2"))

    def test_the_level_goes_at_the_instruments_precision(self):
        """A forex lock computed to eight decimals is sent at the pair's
        five (three on a yen cross); the row says what the venue took."""
        from bot_program.asset_engine.base import make_bot
        fx = _config(self.user, asset_class="forex", name="fx",
                     symbols=["EURUSD"])
        # entry 1.17, stop 1.16667: risk 0.00333, lock = 1.17 + 0.000333
        t = _trade(fx, paper=False, symbol="EURUSD", cls="forex", qty="1000",
                   entry="1.17", stop="1.16667",
                   meta={"protected": True, "protective_trade_id": "F1"})
        client = _client()
        self._care(t, 1.1745, client, bot=make_bot(fx))          # about +1.35R
        client.modify_protective.assert_called_once()
        oid, level = client.modify_protective.call_args.args
        self.assertEqual(oid, "F1")
        self.assertEqual(str(level), "1.17033")
        t.refresh_from_db()
        self.assertEqual(t.stop_loss, Decimal("1.17033"))
        self.assertEqual(t.metadata["care"]["venue_stop"], 1.17033)

    def test_a_missing_risk_denominator_is_stamped_before_the_stop_moves(self):
        """A row without initial_stop_loss measures R from its stop_loss;
        once the venue stop has moved that would inflate every R. The sent
        stop is stamped first."""
        t = self._real()
        meta = dict(t.metadata)
        meta.pop("initial_stop_loss")
        t.metadata = meta
        t.save(update_fields=["metadata"])
        client = _client()
        self._care(t, 102.2, client)
        client.modify_protective.assert_called_once()
        t.refresh_from_db()
        self.assertEqual(t.stop_loss, Decimal("100.2"))
        self.assertEqual(t.metadata["initial_stop_loss"], 98.0)
        # the next tick reads the same R: the lock has not moved, nothing sent
        self._care(t, 102.3, client)
        self.assertEqual(client.modify_protective.call_count, 1)
        t.refresh_from_db()
        self.assertEqual(t.metadata["care"]["soft_stop"], 100.2)

    def test_a_mover_that_raises_leaves_the_soft_stop_and_the_row(self):
        t = self._real()
        client = mock.MagicMock(spec=["modify_protective", "ticker"])
        client.modify_protective.side_effect = RuntimeError("session gone")
        self.assertEqual(self._care(t, 102.2, client), "")
        t.refresh_from_db()
        self.assertEqual(t.stop_loss, Decimal("98"))
        care = t.metadata["care"]
        self.assertEqual(care["soft_stop"], 100.2)
        self.assertIn("session gone", care["venue_stop_refusal"])
        self.assertNotIn("venue_stop", care)


class TheWiringTests(SimpleTestCase):

    def test_the_constant(self):
        from bot_program.position_care import MIRROR_RETRY_MINUTES
        self.assertEqual(MIRROR_RETRY_MINUTES, 30)

    def test_one_mover_for_the_knobs_and_the_mirror(self):
        import inspect

        from bot_program import position_care
        from bot_program.asset_engine.base import AssetBot
        knobs = inspect.getsource(AssetBot._manage_broker_stop)
        self.assertIn("return self._move_broker_stop(trade, price, client, "
                      "candidate, why)", knobs)
        self.assertNotIn("modify_protective", knobs,
                         "the knob path no longer talks to the venue itself")
        mover = inspect.getsource(AssetBot._move_broker_stop)
        self.assertIn('getattr(client, "modify_protective", None)', mover)
        mirror = inspect.getsource(position_care._mirror_to_venue)
        self.assertIn("bot._move_broker_stop(trade, price, client, candidate",
                      mirror)
        self.assertIn("is_improvement(trade, candidate, price)", mirror)

    def test_the_mirror_runs_on_a_hold_of_a_real_row_only(self):
        import inspect

        from bot_program import position_care
        src = inspect.getsource(position_care.care)
        hold = src.index('if decision["action"] != "close":')
        mirror = src.index("_mirror_to_venue(bot, trade, price, client, decision)")
        self.assertGreater(mirror, hold, "the mirror follows the hold branch")
        self.assertIn("if not trade.paper:", src[hold:mirror])
