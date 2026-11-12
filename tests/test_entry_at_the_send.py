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
    eToro refused an order that reached it, whoever reads the refusal;
  * eToro's minimum at the order: eToro's own figure in units for a pair
    whose base is the dollar, any other pair at the rate read at the
    order.

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

    def test_a_note_another_process_wrote_holds_the_send(self):
        """The bot reads its config once, when the pass builds it. An order
        sent for this config by another process since (an admin "run now"
        tick, a pass that outlived the fleet's lock) left its in-doubt note
        in the database, not on this copy: the send reads the note there,
        and the note stands (the review of 2026-11-12)."""
        from bot_program.models import AssetBotConfig
        H.switch(H.SWITCH, None)
        H.switch(H.LEVERAGE, True)
        world = H.arm("crypto_clear", "stored")
        cfg = world["cfg"]

        def another_process():
            row = AssetBotConfig.objects.get(pk=cfg.pk)
            row.extras = dict(row.extras or {}, entry_in_doubt={
                "BTCUSD": {"reference": "ref-9",
                           "at": timezone.now().isoformat(), "side": "BUY"}})
            row.save(update_fields=["extras"])
        with mock.patch("bot_program.notifications.notify_staff"):
            out = H.run(world, between=another_process)
        self.assertIsNotNone(out.cand)
        self.assertIsNone(out.res)
        self.assertEqual(H.orders(out), [])
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "order_in_doubt")
        self.assertTrue(skip["detail"].startswith(
            "an order under reference ref-9 may already be live (since "),
            skip)
        self.assertEqual(
            out.cfg.extras["entry_in_doubt"]["BTCUSD"]["reference"], "ref-9")

    def _other(self, world, name="F other"):
        """Another live config of the account on the world's symbol, its
        pool and legs the world config's own."""
        cfg = world["cfg"]
        other = H._live_cfg(world["user"], "crypto", name=name)
        other.symbols = [world["symbol"]]
        other.capital = cfg.capital
        other.stop_loss_pct, other.take_profit_pct = (cfg.stop_loss_pct,
                                                      cfg.take_profit_pct)
        other.save()
        return other

    def test_another_configs_order_in_doubt_holds_the_same_bet(self):
        """Config A's order did not come back: it MAY be live at eToro, and
        no row says so, only the note on A. The duplicate gate reads rows,
        so config B of the same account met no holder and sent the same
        bet, in the same pass and on the next (main's own; the review of
        2026-11-12). B now sends nothing on the symbol and side while A's
        note is fresh: at the send, and at the proposal of the next
        pass."""
        from bot_program.asset_engine.base import make_bot
        H.switch(H.SWITCH, None)
        H.switch(H.LEVERAGE, True)
        world = H.arm("crypto_clear", "elsewhere")
        cfg_a = world["cfg"]
        cfg_b = self._other(world)
        err = RuntimeError("the request did not come back")
        err.in_doubt, err.reference = True, "ref-7"
        v_a = H.venue(world["price"], world["table"], raises=err)
        v_b = H.venue(world["price"], world["table"])
        venues = {cfg_a.pk: v_a, cfg_b.pk: v_b}

        def route(user, symbol, cfg=None, *args, **kwargs):
            return venues[cfg.pk]
        bot_a, bot_b = make_bot(cfg_a), make_bot(cfg_b)
        with mock.patch(H.ROUTER, side_effect=route), \
                mock.patch("time.sleep"), \
                mock.patch("bot_program.notifications.notify_staff"), \
                mock.patch("bot_program.notifications.notify_bot_fill_open"):
            cand_a = bot_a.propose_entry("BTCUSD")
            cand_b = bot_b.propose_entry("BTCUSD")
            self.assertIsNotNone(cand_a)
            self.assertIsNotNone(cand_b, cfg_b.extras.get("skips"))
            self.assertIsNone(bot_a.execute_entry(cand_a))   # in doubt
            res_b = bot_b.execute_entry(cand_b)
            # the next pass: B proposes again while A's note is fresh
            again_b = make_bot(cfg_b).propose_entry("BTCUSD")
        cfg_a.refresh_from_db()
        cfg_b.refresh_from_db()
        self.assertEqual(v_a.market_order.call_count, 1)
        v_b.market_order.assert_not_called()
        self.assertIsNone(res_b)
        self.assertIsNone(again_b)
        note = cfg_a.extras["entry_in_doubt"]["BTCUSD"]
        self.assertEqual((note["reference"], note["side"]), ("ref-7", "BUY"))
        skip = cfg_b.extras["skips"]["BTCUSD"]
        self.assertEqual(skip["code"], "order_in_doubt")
        self.assertTrue(skip["detail"].startswith(
            f"BTCUSD long: an order of config #{cfg_a.pk} under reference "
            f"ref-7 may already be live (since "), skip)
        self.assertTrue(skip["detail"].endswith(
            "a second ticket could double that bet; nothing sent"), skip)

    def test_an_order_in_doubt_elsewhere_holds_its_own_side(self):
        """One expression per symbol AND SIDE across configs, as the
        duplicate gate counts a row: a note on a long holds a long, not a
        short. A note written before the side was kept holds both; a note
        past IN_DOUBT_QUIET_HOURS holds nothing; the asker's own note is
        the proposal's (ORDER_IN_DOUBT there), not this reader's."""
        from datetime import timedelta
        from bot_program.asset_engine.base import make_bot
        from bot_program.models import AssetBotConfig
        world = H.arm("crypto_clear", "sides")
        cfg_a = world["cfg"]
        bot = make_bot(self._other(world))

        def note_on_a(**note):
            AssetBotConfig.objects.filter(pk=cfg_a.pk).update(
                extras=dict(cfg_a.extras or {}, entry_in_doubt={
                    "BTCUSD": dict({"reference": "ref-s",
                                    "at": timezone.now().isoformat()},
                                   **note)}))
        note_on_a(side="BUY")
        held = bot._in_doubt_elsewhere("BTCUSD", side="BUY")
        self.assertEqual((held["config_id"], held["reference"]),
                         (cfg_a.pk, "ref-s"))
        self.assertIsNone(bot._in_doubt_elsewhere("BTCUSD", side="SELL"))
        self.assertIsNone(bot._in_doubt_elsewhere("ETHUSD", side="BUY"))
        note_on_a()
        self.assertEqual(
            bot._in_doubt_elsewhere("BTCUSD", side="SELL")["config_id"],
            cfg_a.pk)
        note_on_a(side="BUY", at=(timezone.now() - timedelta(
            hours=bot.IN_DOUBT_QUIET_HOURS + 1)).isoformat())
        self.assertIsNone(bot._in_doubt_elsewhere("BTCUSD", side="BUY"))
        mine = make_bot(cfg_a)
        note_on_a(side="BUY")
        self.assertIsNone(mine._in_doubt_elsewhere("BTCUSD", side="BUY"))


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

    def test_a_refusal_whose_words_say_not_sent_is_still_a_refusal(self):
        """eToro's answer rides the exception's words ("eToro refused
        (400): " and the start of its body), and a body may say anything,
        "was not sent" included. It is still eToro's refusal of an order
        that reached it: noted, and the same order does not go out on the
        next pass (the review of 2026-11-12)."""
        world = self._world("words")
        out = H.run(world, the_venue=H.venue(
            world["price"], world["table"], raises=RuntimeError(
                'eToro refused (400): {"errorCode": 746, "errorMessage": '
                '"the order was not sent to the market"}')))
        self.assertEqual(len(H.orders(out)), 1)
        self.assertIn("leverage_refusals", out.cfg.extras, H.skip_of(out))
        self.assertEqual(
            out.cfg.extras["leverage_refusals"]["EURUSD"]["leverage"], 10)
        again = H.run(world)
        self.assertEqual(H.orders(again), [])
        self.assertEqual(H.skip_of(again)["code"], "leverage_refused")

    def test_a_row_cancelled_or_expired_at_the_poll_is_no_refusal(self):
        """eToro refuses an order with Rejected and an errorCode. Canceled
        is the answer to a withdrawal (Sauron's own whose answer was not
        read, measured 202 then Canceled; the operator's, in the app), and
        Expired an order that lapsed: neither refuses this order at this
        multiplier. The row is cancelled as before, no 12-hour note is
        written, and the next pass may send again (the review of
        2026-11-12): for a levered row, and for a raised one."""
        from tests.test_bot_venue_floor import _on
        working = {"orderId": "o-9", "status": "NEW", "working": True,
                   "executedQty": "0"}
        for status in ("Canceled", "Expired"):
            for kind in ("levered", "raised"):
                with self.subTest(status=status, kind=kind):
                    tag = f"poll_{kind}_{status.lower()}"
                    world = (self._world(tag) if kind == "levered"
                             else _on("forex_under_min", tag=tag))
                    v = H.venue(world["price"], world["table"],
                                fill=working)
                    with mock.patch("bot_program.notifications."
                                    "notify_staff"):
                        out = H.run(world, the_venue=v)
                    (row,) = H.trade_rows(out)
                    self.assertTrue(row.metadata.get("entry_working"))
                    v.order_status = (lambda oid, s=status: {
                        "state": "dead", "status": s, "filled": 0})
                    out.bot._poll_working_entry(row, v)
                    out.cfg.refresh_from_db()
                    row.refresh_from_db()
                    self.assertNotIn("leverage_refusals", out.cfg.extras)
                    self.assertNotIn(row.status, ("OPEN", "CLOSE_PENDING"))
                    again = H.run(world)
                    self.assertEqual(len(H.orders(again)), 1,
                                     H.skip_of(again))


def _pair_row(iid, symbol):
    """An eligibility row for a forex pair the harness does not carry,
    as forex is measured (a 1,000 USD minimum exposure)."""
    return H._row(iid, symbol, [
        H._lev("cfd", "long", [1], max_sl=100, min_amount=25),
        H._lev("cfd", "long", [2, 5, 10, 20, 30], min_amount=25),
        H._lev("cfd", "short", [1, 2, 5, 10, 20, 30], min_amount=25)],
        min_exposure=1000)


class TheMinimumAtTheOrderTests(TestCase):
    """E. main's own check of eToro's minimum at the order (the venue
    floor's switch OFF; ON, a size that clears the minimum meets the same
    check). eToro states its minimum in dollars, and the order turned it
    into units with the candidate's price and a SECOND read of the
    platform's dollar rate: a bot whose own size was exactly the minimum
    could be refused on the noise between the two feeds. For a pair whose
    base is the dollar, eToro's figure in units: no price and no rate in
    it. Any other pair is judged at the rate read at the order, the one
    nearest eToro's own (the review of 2026-11-12 measured the proposal's
    rate, minutes older, agreeing less with eToro on crosses)."""

    def _world(self, tag, symbol, price, pool, **changes):
        H.switch(H.SWITCH, None)
        H.switch(H.LEVERAGE, True)
        table = H.rows(**{symbol: _pair_row(1005, symbol)})
        return H.arm("forex_under_min", tag, symbol=symbol, price=price,
                     pool=pool, table=table, **changes)

    def test_a_pair_whose_base_is_the_dollar_at_exactly_the_minimum_goes(
            self):
        """USDJPY at 150.00, a 6,000 pool, a 1.5% stop: the risk budget
        (15.00 at the stop, at the platform's yen rate of 1/150.03) sizes
        1,000 units. N units of USDJPY are N dollars of exposure, so
        eToro's 1,000 USD minimum is 1,000 units; turned into units through
        eToro's price and the platform's rate it read 1,000.2, and the
        bot's own 1,000 were refused. Now they are sent, at the bot's own
        size. A size under eToro's figure is still refused, with its
        numbers."""
        def yen(bot):
            bot._value_per_unit = lambda symbol: 1 / 150.03
        out = H.run(self._world("jpy", "USDJPY", "150.00", "6000"),
                    prepare=yen)
        self.assertEqual(out.cand.qty_default, 1000.0)
        self.assertIsNotNone(out.res, H.skip_of(out))
        self.assertEqual([o[:3] for o in H.orders(out)],
                         [["USDJPY", "BUY", 1000.0]])
        under = H.run(self._world("jpy_under", "USDJPY", "150.00", "6000"),
                      prepare=yen, size_mult=0.9)
        self.assertEqual(H.orders(under), [])
        skip = H.skip_of(under)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertTrue(skip["detail"].startswith(
            "sized 900 units from the stop distance; this venue's minimum "
            "is 1000. "), skip)

    def test_a_cross_is_judged_at_the_rate_read_at_the_order(self):
        """EURGBP at 0.8500, Fractional Units on (forex by the unit), a
        6,005 pool: the risk budget sizes 927 units at the proposal's pound
        rate of 1.2700, where eToro's minimum is 926.36 units. The
        platform's rate reads 1.2690 when the order is built, and eToro
        judges a cross at its own rate at the order: there 927 units are
        999.9 USD (927 x 0.85 x 1.2690), under its 1,000, and the minimum
        is 927.085. Refused before the POST, as main refused it; the next
        pass sizes again at the new rate. (Changed on purpose by the
        review of 2026-11-12: this test pinned the order SENT at the
        proposal's rate, minutes older, and eToro refuses such an order
        after the POST, which at 10x also writes the 12-hour note.) The
        other way, a rate that rose by the order clears the minimum
        there: sent."""
        rate = {"v": 1.2700}
        out = H.run(
            self._world("gbp", "EURGBP", "0.8500", "6005", fractions=True),
            prepare=lambda bot: setattr(
                bot, "_value_per_unit", lambda symbol: rate["v"]),
            between=lambda: rate.update(v=1.2690))
        self.assertEqual(out.cand.qty_default, 927.0)
        self.assertIsNone(out.res)
        self.assertEqual(H.orders(out), [])
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertTrue(skip["detail"].startswith(
            "sized 927 units from the stop distance; this venue's minimum "
            "is 927.085. "), skip)
        # the rate rose between the proposal and the order
        rate["v"] = 1.2690
        up = H.run(
            self._world("gbp_up", "EURGBP", "0.8500", "6002",
                        fractions=True),
            prepare=lambda bot: setattr(
                bot, "_value_per_unit", lambda symbol: rate["v"]),
            between=lambda: rate.update(v=1.2700))
        self.assertEqual(up.cand.qty_default, 927.0)
        self.assertIsNotNone(up.res, H.skip_of(up))
        self.assertEqual([o[:3] for o in H.orders(up)],
                         [["EURGBP", "BUY", 927.0]])
