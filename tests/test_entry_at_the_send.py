"""THE ENTRY PATH AT THE SEND: main's own defects, found by the venue
floor's three reviews (2026-11-12) and fixed one by one.

The desk's pass proposes every candidate of every config, then sends them:
whatever the proposal judged can have moved by the time an order leaves.
Each class here pins one rule read again at the send, with the switch of
the venue floor OFF (main's own path), on the synthetic entries of
tests/bot_venue_floor_harness.py (EURUSD, USDJPY, BTCUSD at invented
prices, round invented pools; no broker, no model, no HTTP):

  * one position per config and symbol: two candidates of one config and
    one symbol in one pass send one order, not two;
  * MAX DAILY LOSS read again at the send for every entry: a candidate
    proposed before the day crossed the limit, never judged elite, is not
    sent;
  * the 12-hour note after a refused levered order: written exactly when
    eToro refused an order that reached it, whoever reads the refusal.

Run with:  python manage.py test tests.test_entry_at_the_send
"""
import contextlib
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone

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


class TheDailyLossAtTheSendTests(TestCase):
    """C. MAX DAILY LOSS read again at the send, for every entry. Past the
    limit (and above the absolute stop) only an entry judged elite opens,
    at half its size, and the proposal is what judges it. A candidate
    proposed while the day was inside the limit was never judged: the desk
    sends minutes after it proposes, and a stop-out booked in between
    crosses the limit. The venue floor's fix read the day again at the
    send for a raised entry only."""

    def _world(self, tag):
        H.switch(H.SWITCH, None)
        H.switch(H.LEVERAGE, True)
        H.limit(max_daily_loss_pct=3.0)
        return H.arm("crypto_clear", tag)

    def _book_a_loss(self, world, pnl):
        """Another live config of the account closes at a loss."""
        from bot_program.models import AssetBotTrade
        other = H._live_cfg(world["user"], "crypto", name="F loser")
        AssetBotTrade.objects.create(
            config=other, asset_class="crypto", symbol="ETHUSD", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("2000"),
            exit_price=Decimal(str(2000 + pnl)), stop_loss=Decimal("1900"),
            take_profit=Decimal("2300"), status="CLOSED", paper=False,
            pnl=Decimal(str(pnl)), closed_at=timezone.now())

    def _phases(self, world, *, between=None, elite=None):
        """The runner's two phases for the world's config: propose, then
        (after `between`) send. `elite` stands in for the elite verdict
        the proposal reads (AssetBot._elite_verdict)."""
        from bot_program.asset_engine import runner
        from bot_program.asset_engine.base import AssetBot
        H._clear_eligibility()
        v = H.venue(world["price"], world["table"])
        cands = []
        verdict = (mock.patch.object(AssetBot, "_elite_verdict",
                                     return_value=dict(elite))
                   if elite is not None else contextlib.nullcontext())
        with mock.patch(H.ROUTER, return_value=v), \
                mock.patch("time.sleep"), verdict, \
                mock.patch("bot_program.notifications.notify_bot_fill_open"):
            bot = runner._propose_phase(
                world["cfg"], signal_stats={}, candidates=cands,
                not_desked={"paper": [], "live": []}, summaries=[])
            if between is not None:
                between()
            res = [runner._execute_one(bot, c, mult=1.0, plan=None,
                                       decision=None, opened=[], halted={})
                   for c in cands]
        world["cfg"].refresh_from_db()
        return bot, cands, res, v

    def test_a_candidate_not_judged_elite_is_not_sent_once_the_day_crossed(
            self):
        """Pool 1,000: MAX DAILY LOSS 3% is 30, the absolute stop 45.
        BTCUSD is proposed while the day is flat, at the bot's own 0.001;
        another config's stop-out of 35 is booked before the send. The send
        finds the day past the limit, and the candidate was never judged
        elite: nothing sent. A candidate proposed past the limit and judged
        elite still goes, at half its size, stamped elite."""
        from bot_program.models import AssetBotTrade
        world = self._world("crossed")
        bot, cands, res, v = self._phases(
            world, between=lambda: self._book_a_loss(world, -35))
        self.assertEqual([(c.symbol, c.qty_default) for c in cands],
                         [("BTCUSD", 0.001)])
        self.assertFalse((getattr(cands[0], "elite", None) or {}).get(
            "elite"))
        self.assertTrue(bot._elite_only)
        self.assertEqual(res, [None])
        v.market_order.assert_not_called()
        self.assertEqual(
            AssetBotTrade.objects.filter(config=world["cfg"]).count(), 0)
        skip = world["cfg"].extras["skips"]["BTCUSD"]
        self.assertEqual(skip["code"], "gate_blocked")
        self.assertEqual(
            skip["detail"],
            "the day went past the daily loss limit after this entry was "
            "proposed: past it only an entry judged elite opens, and this "
            "one was not — nothing sent")
        # the elite path, unchanged: proposed past the limit, judged
        # elite, sent at half its size and stamped
        world = self._world("elite")
        self._book_a_loss(world, -35)
        bot, cands, res, v = self._phases(
            world, elite={"elite": True, "why": "synthetic: a measured edge",
                          "net_rr": 2.5, "n": 30})
        self.assertEqual([(c.symbol, c.qty_default) for c in cands],
                         [("BTCUSD", 0.0005)])
        self.assertIsNotNone(res[0], world["cfg"].extras.get("skips"))
        self.assertEqual([c.args[:3] for c in v.market_order.call_args_list],
                         [("BTCUSD", "BUY", 0.0005)])
        (row,) = AssetBotTrade.objects.filter(config=world["cfg"])
        self.assertIs(row.metadata.get("elite_past_daily_stop"), True)


class TheTwelveHourNoteTests(TestCase):
    """D. The 12-hour note after a refused order (LEVERAGE_QUIET_HOURS):
    one levered or raised order per quiet, not one per pass. Written
    exactly when eToro refused an order that reached it, whoever reads the
    refusal: the order's own answer, the order's exception, or the
    working-entry poll a pass later. An order that never reached eToro is
    no refusal."""

    def _world(self, tag):
        """EURUSD typed at 10x on a 10,000 pool: the bot's own 1,500 units
        clear eToro's minimum, so main sends them (nothing is raised)."""
        H.switch(H.SWITCH, None)
        H.switch(H.LEVERAGE, True)
        return H.arm("forex_typed_leverage", tag, pool="10000")

    def test_a_levered_refusal_read_by_the_working_poll_is_noted(self):
        """eToro accepts the order and the lookup is not read in time: the
        row is WORKING. The next pass's poll reads eToro's refusal: noted
        like a refusal at the order, and the same order does not go out
        again on the pass after. An unlevered row's refusal keeps main's
        memory (no note at 1x), as at the order."""
        world = self._world("poll")
        v = H.venue(world["price"], world["table"], fill={
            "orderId": "o-9", "status": "NEW", "working": True,
            "executedQty": "0"})
        with mock.patch("bot_program.notifications.notify_staff"):
            out = H.run(world, the_venue=v)
        (row,) = H.trade_rows(out)
        self.assertTrue(row.metadata.get("entry_working"), row.metadata)
        self.assertEqual(row.metadata.get("leverage"), 10)
        self.assertNotIn("venue_floor", row.metadata)
        self.assertNotIn("leverage_refusals", out.cfg.extras)
        v.order_status = lambda oid: {
            "state": "dead", "status": "Rejected", "filled": 0,
            "refusal": "errorCode 999"}
        out.bot._poll_working_entry(row, v)
        out.cfg.refresh_from_db()
        notes = out.cfg.extras.get("leverage_refusals") or {}
        self.assertIn("EURUSD", notes, out.cfg.extras)
        self.assertEqual(notes["EURUSD"]["leverage"], 10)
        self.assertEqual(notes["EURUSD"]["why"],
                         "broker reported Rejected: errorCode 999")
        again = H.run(world)
        self.assertEqual(H.orders(again), [])
        skip = H.skip_of(again)
        self.assertEqual(skip["code"], "leverage_refused")
        self.assertTrue(skip["detail"].startswith(
            "at 10x: eToro refused EURUSD 0.0h ago (broker reported "
            "Rejected: errorCode 999); quiet for 12h"), skip)
        # an unlevered row refused at the poll: no note, as at the order
        world = self._world("poll1x")
        world["cfg"].extras = {"session_filter_disabled": True}
        world["cfg"].save(update_fields=["extras"])
        H.limit(max_single_position_pct=100, max_pledged_pct=100)
        v = H.venue(world["price"], world["table"], fill={
            "orderId": "o-8", "status": "NEW", "working": True,
            "executedQty": "0"})
        out = H.run(world, the_venue=v)
        (row,) = H.trade_rows(out)
        self.assertNotIn("leverage", row.metadata)
        v.order_status = lambda oid: {
            "state": "dead", "status": "Rejected", "filled": 0}
        out.bot._poll_working_entry(row, v)
        out.cfg.refresh_from_db()
        self.assertNotIn("leverage_refusals", out.cfg.extras)

    def test_an_order_that_never_reached_etoro_writes_no_note(self):
        """The connection was never made, the adapter refused the order
        before its POST, or it could not name the instrument: eToro refused
        nothing. No 12-hour note, and the next pass may send it (after a
        failed POST the venue's health holds new entries for its own
        quiet). An order eToro answered with a refusal is noted, as
        before."""
        never = (
            ("unsent", RuntimeError(
                "eToro unreachable (ConnectionError): the order for EURUSD "
                "was not sent — refused")),
            ("prepost", ValueError(
                "eToro NOT SENT: leverage 10 is past this adapter's 5 "
                "ceiling (EURUSD BUY). The cap is on what leaves the box")),
            ("unnamed", LookupError(
                "eToro knows no instrument spelled 'EURUSD'")))
        for tag, err in never:
            with self.subTest(tag):
                world = self._world(tag)
                out = H.run(world, the_venue=H.venue(
                    world["price"], world["table"], raises=err))
                self.assertEqual(len(H.orders(out)), 1)
                self.assertEqual(H.skip_of(out)["code"], "order_error")
                self.assertNotIn("leverage_refusals", out.cfg.extras)
                again = H.run(world)
                self.assertEqual(len(H.orders(again)), 1)
        # it reached eToro, and eToro refused it: noted
        world = self._world("reached")
        out = H.run(world, the_venue=H.venue(
            world["price"], world["table"],
            raises=RuntimeError('eToro refused (400): {"errorCode": 720}')))
        self.assertEqual(
            out.cfg.extras["leverage_refusals"]["EURUSD"]["leverage"], 10)
