"""THE ENTRY PATH AT THE SEND: main's own defects, found by the venue
floor's three reviews (2026-11-12) and fixed one by one.

The desk's pass proposes every candidate of every config, then sends them:
whatever the proposal judged can have moved by the time an order leaves.
Each class here pins one rule read again at the send, with the switch of
the venue floor OFF (main's own path), on the synthetic entries of
tests/bot_venue_floor_harness.py (EURUSD, USDJPY, BTCUSD at invented
prices, round invented pools; no broker, no model, no HTTP):

  * one position per config and symbol: two candidates of one config and
    one symbol in one pass send one order, not two.

Run with:  python manage.py test tests.test_entry_at_the_send
"""
from unittest import mock

from django.test import TestCase

from tests import bot_venue_floor_harness as H


def _propose_and_send(cfg, the_venue):
    """The runner's own two phases for one config (runner._propose_phase,
    then runner._execute_one for each candidate in the order proposed: the
    desk's shadow mode, and its fail-open path)."""
    from bot_program.asset_engine import runner
    cands = []
    with mock.patch(H.ROUTER, return_value=the_venue), \
            mock.patch("time.sleep"), \
            mock.patch("bot_program.notifications.notify_bot_fill_open"):
        bot = runner._propose_phase(
            cfg, signal_stats={}, candidates=cands,
            not_desked={"paper": [], "live": []}, summaries=[])
        results = [runner._execute_one(bot, cand, mult=1.0, plan=None,
                                       decision=None, opened=[], halted={})
                   for cand in cands]
    cfg.refresh_from_db()
    return bot, cands, results


class OnePositionPerConfigAndSymbolTests(TestCase):
    """B. The proposal refuses a symbol its config already holds
    (ALREADY_OPEN) or may hold (an order in doubt), but every candidate of
    a pass is proposed before any is sent: two candidates of one config
    and one symbol both passed it with no row on the books, and the send's
    duplicate gate (risk_gate.duplicate_state) leaves the asker's own
    config out by design. The first sent is kept, the other sends
    nothing."""

    def _world(self, tag, **changes):
        H.switch(H.SWITCH, None)
        H.switch(H.LEVERAGE, True)
        world = H.arm("crypto_clear", tag, **changes)
        cfg = world["cfg"]
        # the symbol listed twice: two candidates in one pass
        cfg.symbols = [world["symbol"], world["symbol"]]
        cfg.save(update_fields=["symbols"])
        return world

    def test_two_candidates_of_one_config_and_symbol_send_one_order(self):
        """BTCUSD at 50,000, a 1,000 pool: 0.001 BTC each. The first is
        sent and booked; the second meets the row the first wrote. A
        second config of the account on the same symbol and side is
        refused by the duplicate gate, as it always was: one expression
        per bet across configs is intended, and unchanged."""
        from bot_program.models import AssetBotTrade
        world = self._world("twice")
        cfg = world["cfg"]
        v = H.venue(world["price"], world["table"])
        _bot, cands, results = _propose_and_send(cfg, v)
        self.assertEqual([c.symbol for c in cands], ["BTCUSD", "BTCUSD"])
        self.assertEqual(v.market_order.call_count, 1)
        self.assertIsNotNone(results[0])
        self.assertIsNone(results[1])
        self.assertEqual(
            AssetBotTrade.objects.filter(config=cfg, symbol="BTCUSD").count(),
            1)
        skip = cfg.extras["skips"]["BTCUSD"]
        self.assertEqual(skip["code"], "already_open")
        self.assertEqual(
            skip["detail"],
            "a position is already on: this config opened BTCUSD after this "
            "entry was proposed (one position per config and symbol) — "
            "nothing sent")
        # another config of the account, the same symbol and side
        other = H._live_cfg(world["user"], "crypto", name="F other")
        other.symbols = ["BTCUSD"]
        other.capital = cfg.capital
        other.stop_loss_pct, other.take_profit_pct = (cfg.stop_loss_pct,
                                                      cfg.take_profit_pct)
        other.save()
        v2 = H.venue(world["price"], world["table"])
        _propose_and_send(other, v2)
        v2.market_order.assert_not_called()
        dup = other.extras["skips"]["BTCUSD"]
        self.assertEqual(dup["code"], "gate_blocked")
        self.assertTrue(dup["detail"].startswith(
            "BTCUSD long is already on the real-money book via "), dup)

    def test_an_order_in_doubt_holds_the_second_candidate(self):
        """The first order did not come back: it MAY be live at eToro, and
        no row says so (the note on the config does). The second candidate
        of the same config and symbol sends nothing: a second order could
        be a second position."""
        world = self._world("doubt")
        cfg = world["cfg"]
        err = RuntimeError("the request did not come back")
        err.in_doubt, err.reference = True, "ref-7"
        v = H.venue(world["price"], world["table"], raises=err)
        with mock.patch("bot_program.notifications.notify_staff"):
            _bot, cands, results = _propose_and_send(cfg, v)
        self.assertEqual(len(cands), 2)
        self.assertEqual(v.market_order.call_count, 1)
        self.assertEqual(results, [None, None])
        skip = cfg.extras["skips"]["BTCUSD"]
        self.assertEqual(skip["code"], "order_in_doubt")
        self.assertTrue(skip["detail"].startswith(
            "an order under reference ref-7 may already be live (since "),
            skip)
        self.assertTrue(skip["detail"].endswith(
            ": sent after this entry was proposed — nothing sent"), skip)
