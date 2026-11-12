"""THE VENUE FLOOR FOR BOTS: what its three reviews found (2026-11-12).

Three lenses read the floor before it was offered: money and limits, the
venue's truth and its failure paths, the switch and the words. Each test
here pins one finding they confirmed, on the synthetic entries of
tests/bot_venue_floor_harness.py (EURUSD, USDJPY, XAUUSD, NAS100, AAPL,
BTCUSD at invented prices, round invented pools; no broker, no model, no
HTTP):

  * the daily loss rule read again at the send;
  * the 12-hour quiet of a refused order, shared by the account's bots,
    written by the working-entry poll too, and never set for an order
    that did not leave;
  * the headroom above eToro's minimum, the quote read again before the
    order, one dollar rate per entry, a pair whose base is the dollar;
  * eToro's minimum margin under a typed multiplier; an instrument typed
    whole; an instrument not quoted in dollars;
  * the words: whose size it is, the desk's cut, the ceiling's lever on
    the bell, a detail that fits its 200 characters, the multiplier and
    the nightly fee of a raised entry;
  * a failure in the floor's own code never raises and never silences a
    fill; and the places no test pinned (the value per unit, a refusal at
    1x, a switch that cannot be read).

Run with:  python manage.py test tests.test_bot_venue_floor_review
"""
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

from django.utils import timezone

from tests import bot_venue_floor_harness as H
from tests.test_bot_venue_floor import FRENCH, _On, _floor_of, _on

REFUSED = {"orderId": "o-1", "status": "REJECTED", "executedQty": "0",
           "refusal": "errorCode 720"}


def _bot(world):
    from bot_program.asset_engine.base import make_bot
    return make_bot(world["cfg"])


def _bell(user, part="will not take this size"):
    from alerts.models import Notification
    return [n.body for n in Notification.objects.filter(
        user=user, title__contains=part).order_by("id")]


def _vpu(value):
    return lambda bot: setattr(bot, "_value_per_unit", lambda symbol: value)


def _second_bot(world, name="F second"):
    """Another live bot of the SAME account on the same symbol."""
    first = world["cfg"]
    cfg = H._live_cfg(world["user"], first.asset_class, name=name)
    cfg.symbols = list(first.symbols)
    cfg.capital = first.capital
    cfg.base_currency = first.base_currency
    cfg.stop_loss_pct = first.stop_loss_pct
    cfg.take_profit_pct = first.take_profit_pct
    cfg.extras = dict(world.get("extras") or {})
    cfg.save()
    return dict(world, cfg=cfg)


# ── money and limits ────────────────────────────────────────────────────

class TheDailyLossAtTheSendTests(_On):
    """Past MAX DAILY LOSS nothing goes out at a raised size, and the rule
    is read again at the send: the desk executes minutes after it
    proposes, and a stop-out booked in between crosses the limit."""

    def test_the_real_runner_sends_nothing_once_the_day_crossed(self):
        """The runner's own two phases. Pool 2,000: the limit is 3% (60),
        the absolute stop 90. EURUSD is proposed at the raised 1,000
        units; another config's stop-out of 70 is booked; the send then
        finds the day in the elite band and sends nothing."""
        from bot_program.asset_engine import runner
        from bot_program.models import AssetBotTrade
        H.limit(max_single_position_pct=20, max_open_risk_pct=15,
                max_notional_multiple=4.0, max_pledged_pct=50,
                max_bot_leverage=None, max_daily_loss_pct=3.0)
        world = _on("forex_under_min", tag="race")
        cfg, user = world["cfg"], world["user"]
        H._clear_eligibility()
        v = H.venue(world["price"], world["table"])
        cands = []
        with mock.patch(H.ROUTER, return_value=v), \
                mock.patch("time.sleep"), \
                mock.patch("bot_program.notifications.notify_bot_fill_open"):
            bot = runner._propose_phase(
                cfg, signal_stats={}, candidates=cands,
                not_desked={"paper": [], "live": []}, summaries=[])
            self.assertEqual([(c.symbol, c.qty_default) for c in cands],
                             [("EURUSD", 1000.0)])
            self.assertEqual(getattr(bot, "_elite_only", ""), "")
            other = H._live_cfg(user, "forex", name="F other")
            AssetBotTrade.objects.create(
                config=other, asset_class="forex", symbol="GBPUSD",
                side="BUY", qty=Decimal("1000"),
                entry_price=Decimal("1.27"), exit_price=Decimal("1.20"),
                stop_loss=Decimal("1.20"), take_profit=Decimal("1.40"),
                status="CLOSED", paper=False, pnl=Decimal("-70"),
                closed_at=timezone.now())
            runner._execute_one(bot, cands[0], mult=1.0, plan=None,
                                decision=None, opened=[], halted={})
        self.assertTrue(bot._elite_only)
        v.market_order.assert_not_called()
        cfg.refresh_from_db()
        self.assertEqual(
            AssetBotTrade.objects.filter(config=cfg).count(), 0)
        skip = cfg.extras["skips"]["EURUSD"]
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertEqual(
            skip["detail"],
            "the day went past the daily loss limit after this entry was "
            "raised to the venue's smallest size — nothing sent")

    def test_a_day_inside_the_limit_still_sends(self):
        """The same two phases with nothing booked in between."""
        from bot_program.asset_engine import runner
        world = _on("forex_under_min", tag="calm")
        H._clear_eligibility()
        v = H.venue(world["price"], world["table"])
        cands = []
        with mock.patch(H.ROUTER, return_value=v), \
                mock.patch("time.sleep"), \
                mock.patch("bot_program.notifications.notify_bot_fill_open"):
            bot = runner._propose_phase(
                world["cfg"], signal_stats={}, candidates=cands,
                not_desked={"paper": [], "live": []}, summaries=[])
            runner._execute_one(bot, cands[0], mult=1.0, plan=None,
                                decision=None, opened=[], halted={})
        self.assertEqual(v.market_order.call_count, 1)


class TheQuietAcrossBotsTests(_On):
    """One refused order quiets the symbol for every bot of the account:
    a refusal leaves no row, so nothing else stops the next bot sending
    the same order."""

    def test_a_refusal_on_one_bot_quiets_the_accounts_other_bots(self):
        world = _on("forex_under_min", tag="acct")
        out = H.run(world, the_venue=H.venue(world["price"], world["table"],
                                             fill=REFUSED))
        self.assertEqual(len(H.orders(out)), 1)
        again = H.run(_second_bot(world))
        self.assertEqual(H.orders(again), [])
        self.assertEqual(again.cand.qty_default, 300.0)
        skip = H.skip_of(again)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertTrue(skip["detail"].startswith(
            "eToro refused EURUSD 0.0h ago on another bot of this account: "
            "nothing is raised to the venue's smallest size until 12h after "
            "it: "), skip)
        self.assertLess(len(skip["detail"]), 200)
        # another account is not quieted by it
        elsewhere = H.run(_on("forex_under_min", tag="elsewhere"))
        self.assertOpened(elsewhere, qty=1000.0, leverage=20)

    def test_its_own_refusal_says_until_when(self):
        world = _on("forex_under_min", tag="own")
        H.run(world, the_venue=H.venue(world["price"], world["table"],
                                       fill=REFUSED))
        skip = H.skip_of(H.run(world))
        self.assertTrue(skip["detail"].startswith(
            "eToro refused EURUSD 0.0h ago: nothing is raised to the "
            "venue's smallest size until 12h after it: "), skip)

    def test_a_refusal_noted_after_the_proposal_stops_the_send(self):
        """The desk's pass proposes for every bot, then sends: the first
        bot's refusal is on the books when the second bot's order would
        leave."""
        world = _on("forex_under_min", tag="acct2")
        second = _second_bot(world)

        def refused_meanwhile():
            first = world["cfg"]
            first.refresh_from_db()
            first.extras = dict(first.extras, leverage_refusals={
                "EURUSD": {"leverage": 20, "why": "broker status REJECTED",
                           "at": timezone.now().isoformat()}})
            first.save(update_fields=["extras"])
        out = H.run(second, between=refused_meanwhile)
        self.assertEqual(out.cand.qty_default, 1000.0)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertEqual(
            skip["detail"],
            "eToro refused EURUSD 0.0h ago on another bot of this account "
            "— nothing sent at the venue's smallest size")


class TheQuoteCurrencyTests(_On):
    """Outside forex the engine counts a point of price as one dollar. An
    instrument quoted in another currency has its risk off by the rate:
    never raised, never guessed."""

    def test_a_stock_not_quoted_in_dollars_is_never_raised(self):
        from instruments.models import Instrument
        world = _on("stock_under_one_share", tag="eur")
        Instrument.objects.filter(symbol="AAPL").update(currency="EUR")
        out = H.run(world)
        self.assertIsNone(out.cand)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "sized_to_zero")
        self.assertTrue(skip["detail"].startswith(
            "AAPL is not quoted in US dollars, so the risk of the venue's "
            "smallest size cannot be judged and nothing is raised: "), skip)

    def test_an_index_whose_quote_currency_is_unmeasured_is_never_raised(self):
        from bot_program.engine.etoro_client import VENUE_QUOTE_UNMEASURED
        world = _on("index_under_min", tag="unq")
        symbol = VENUE_QUOTE_UNMEASURED[0]
        H._instrument(symbol, "index")
        table = dict(world["table"])
        table[symbol] = dict(table["NAS100"])
        verdict = _bot(world)._venue_floor(
            H.venue("20000.00", table), symbol,
            stage={"force_paper": False}, qty=0.0083, price=20000.0,
            sl=19700.0, sizing={"risk_fraction": 0.0025,
                                "value_per_unit": 1.0},
            fractional=True, sized=0.00833)
        self.assertEqual(verdict["state"], "refused")
        self.assertIn("is not quoted in US dollars", verdict["lead"])


class TheDeskAtTheSendTests(_On):
    """The words of a raised entry the desk's multiplier moved."""

    def test_a_multiplier_above_one_names_the_multiplier(self):
        out = H.run(_on("forex_under_min", tag="m15"), size_mult=1.5)
        self.assertNothingSent(out)
        self.assertEqual(H.skip_of(out), {
            "code": "venue_min_size",
            "detail": ("the capital desk's multiplier (1.5x) changed the "
                       "size raised at the proposal (1000 units then, 1500 "
                       "now) — nothing sent")})

    def test_a_cut_to_zero_says_the_desk_cut_it(self):
        out = H.run(_on("stock_under_one_share", tag="cut0"), size_mult=0.4)
        self.assertEqual(out.cand.qty_default, 1.0)
        self.assertNothingSent(out)
        self.assertEqual(H.skip_of(out), {
            "code": "sized_to_zero",
            "detail": ("raised to the venue's smallest size at the proposal "
                       "and cut by the capital desk: risk budget 0.25% of "
                       "1000 is below one tradeable unit")})

    def test_a_cut_under_the_minimum_names_the_desk_on_the_bell_too(self):
        out = H.run(_on("forex_under_min", tag="cut"), size_mult=0.5)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip, {
            "code": "venue_min_size",
            "detail": ("raised to the venue's smallest size at the proposal "
                       "and cut under it by the capital desk: sized 500 "
                       "units; this venue's minimum is 925.926")})
        (body,) = _bell(out.cfg.user)
        self.assertIn("the capital desk", body)
        self.assertIn("/desk/", body)
        for untrue in ("from its stop distance", "a different trade",
                       "risk_per_trade_pct"):
            self.assertNotIn(untrue, body)


class TheRecordedFactorsTests(_On):

    def test_the_allocator_and_the_correlation_factors_are_on_the_row(self):
        """Half the size by the allocator: 154 units, 200 on the step."""
        with mock.patch("signals.rule_actuator.admin_allocator_multiplier",
                        return_value=0.5):
            out = H.run(_on("forex_under_min", tag="alloc"))
        row = self.assertOpened(out, qty=1000.0, leverage=20)
        floor = _floor_of(row)
        self.assertEqual(floor["replaced_qty"], 200.0)
        self.assertEqual(floor["allocator_mult"], 0.5)
        self.assertEqual(floor["corr_scale"], 1.0)


# ── the venue's truth ───────────────────────────────────────────────────

class TheHeadroomTests(_On):
    """The raised size sits one percent above eToro's minimum, so a quote
    a hair lower at the order is still above it; and the quote is read
    again before the order."""

    def test_a_fine_step_sits_one_percent_above_etoros_minimum(self):
        for name, qty, lev in (("commodity_under_min", 0.505, 10),
                               ("index_under_min", 0.0505, 20),
                               ("crypto_under_min", 0.000202, 1)):
            row = self.assertOpened(H.run(_on(name, tag="head")), qty=qty,
                                    leverage=lev)
            self.assertEqual(_floor_of(row)["headroom_pct"], 1.0, name)

    def test_the_headroom_is_inside_the_ceiling(self):
        """XAUUSD: 0.505 units risk 15.15 at the stop. On a 757 pool that
        is 2.0013%: refused; on 758, 1.9987%: opened."""
        out = H.run(_on("commodity_under_min", tag="h757", pool="757"))
        self.assertNothingSent(out)
        self.assertTrue(H.skip_of(out)["detail"].startswith(
            "the venue's smallest size would risk 2.0013% of the pool, "
            "above your 2% ceiling (MAX BOT FLOOR RISK): "), H.skip_of(out))
        self.assertOpened(
            H.run(_on("commodity_under_min", tag="h758", pool="758")),
            qty=0.505, leverage=10)

    def test_a_quote_lower_at_the_order_sends_nothing_and_quiets_nothing(self):
        """BTCUSD raised to 0.000202 at 50,000 (10.10 USD). At the order
        the quote is 49,250: 9.95 USD, under eToro's 10. No order, and no
        quiet: the next pass asks again at the new price."""
        world = _on("crypto_under_min", tag="lower")
        v = H.venue(world["price"], world["table"])

        def lower():
            v.ticker.return_value = {"lastPrice": "49250.00"}
        out = H.run(world, the_venue=v, between=lower)
        self.assertEqual(out.cand.qty_default, 0.000202)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertTrue(skip["detail"].startswith(
            "raised to the venue's smallest size at the proposal, and the "
            "quote is lower at the order: "), skip)
        for quiet in ("leverage_refusals", "entry_fraction_refused"):
            self.assertNotIn(quiet, out.cfg.extras)
        self.assertEqual(_bell(out.cfg.user), [])

    def test_a_sell_at_the_bid_still_clears_the_minimum(self):
        """EURUSD short, eToro's fractions on: 926 units are the minimum
        at 1.0800, 936 with the headroom. Sold at a bid of 1.0795 that is
        1,010.41 USD: sent."""
        world = _on("forex_under_min", tag="sell", direction="bearish",
                    fractions=True)
        v = H.venue(world["price"], world["table"])

        def quoted():
            v.ticker.return_value = {"lastPrice": "1.0800", "bid": "1.0795",
                                     "ask": "1.0805"}
        out = H.run(world, the_venue=v, between=quoted)
        self.assertIsNotNone(out.res, H.skip_of(out))
        (sent,) = H.orders(out)
        self.assertEqual(sent[1:3], ["SELL", 936.0])
        floor = _floor_of(H.trade_rows(out)[0])
        self.assertIs(floor["floored"], True)
        self.assertEqual(floor["replaced_qty"], 309.0)

    def test_a_720_refusal_of_a_raised_fraction_is_not_a_fractions_quiet(self):
        """errorCode 720 is eToro's minimum, not a refused fraction: the
        12-hour note stands, the 24-hour fraction quiet and its bell (whose
        remedies do not apply to a raised order) are not set."""
        world = _on("index_under_min", tag="720")
        refused = dict(REFUSED, refusal="errorCode 720: amount 999.9 is "
                                        "under the minimum 1000")
        out = H.run(world, the_venue=H.venue(world["price"], world["table"],
                                             fill=refused))
        self.assertEqual(H.skip_of(out)["code"], "order_rejected")
        self.assertIn("NAS100", out.cfg.extras["leverage_refusals"])
        self.assertNotIn("entry_fraction_refused", out.cfg.extras)
        self.assertEqual(_bell(out.cfg.user, "fractional size"), [])


class TheOneRateTests(_On):
    """One dollar rate per entry: the minimum is turned into units with
    the rate the entry was sized on, at the proposal and at the order."""

    def test_the_rate_of_the_proposal_is_the_rate_at_the_order(self):
        rate = {"v": 1.25}
        world = _on("forex_under_min", tag="rate", fractions=True)

        def prepare(bot):
            bot._value_per_unit = lambda symbol: rate["v"]
        out = H.run(world, prepare=prepare,
                    between=lambda: rate.update(v=1.2513))
        self.assertIsNotNone(out.res, H.skip_of(out))
        self.assertEqual(H.orders(out)[0][2], out.cand.qty_default)

    def test_a_pair_whose_base_is_the_dollar_opens_at_etoros_figure(self):
        """N units of USDJPY are N dollars whatever the price: eToro's
        1,000 USD is 1,000 units, with no price, no rate and no headroom.
        The platform's own yen rate, a hair off eToro's price on either
        side, moves nothing."""
        table = H.rows(USDJPY=H._row(1005, "USDJPY", [
            H._lev("cfd", "long", [1], max_sl=100, min_amount=25),
            H._lev("cfd", "long", [2, 5, 10, 20, 30], min_amount=25),
            H._lev("cfd", "short", [1, 2, 5, 10, 20, 30], min_amount=25)],
            min_exposure=1000))
        rate = {"v": 1 / 150.03}
        world = _on("forex_under_min", tag="jpy", symbol="USDJPY",
                    price="150.00", table=table)

        def prepare(bot):
            bot._value_per_unit = lambda symbol: rate["v"]
        out = H.run(world, prepare=prepare,
                    between=lambda: rate.update(v=1 / 149.97))
        row = self.assertOpened(out, qty=1000.0, leverage=20)
        floor = _floor_of(row)
        self.assertEqual(floor["venue_min_units"], 1000.0)
        self.assertEqual(floor["headroom_pct"], 0.0)
        self.assertTrue(out.note.call_args.kwargs["floor"].startswith(
            "Smallest size: raised to 1,000 units, the least eToro takes, "
            "from the 300 units the risk budget sized"),
            out.note.call_args.kwargs["floor"])


class TheWorkingPollTests(_On):

    def test_a_refusal_read_by_the_working_poll_is_noted(self):
        """eToro accepts the order and the lookup is not read in time: the
        row is WORKING. The next pass reads the refusal there. Noted like
        a refusal at the order: one order per 12 hours, not one a pass."""
        world = _on("forex_under_min", tag="poll")
        v = H.venue(world["price"], world["table"], fill={
            "orderId": "o-9", "status": "NEW", "working": True,
            "executedQty": "0"})
        out = H.run(world, the_venue=v)
        (row,) = H.trade_rows(out)
        self.assertTrue(row.metadata.get("entry_working"), row.metadata)
        self.assertIs(_floor_of(row)["floored"], True)
        self.assertNotIn("leverage_refusals", out.cfg.extras)
        v.order_status = lambda oid: {
            "state": "dead", "status": "Rejected", "filled": 0,
            "refusal": "errorCode 720"}
        out.bot._poll_working_entry(row, v)
        out.cfg.refresh_from_db()
        note = out.cfg.extras["leverage_refusals"]["EURUSD"]
        self.assertEqual(note["leverage"], 20)
        self.assertIn("Rejected", note["why"])
        again = H.run(world)
        self.assertEqual(H.orders(again), [])
        self.assertEqual(again.cand.qty_default, 300.0)


class TheMinimumMarginTests(_On):

    def test_a_typed_multiplier_is_raised_to_etoros_minimum_margin(self):
        """BTCUSD typed at 2x: 10 USD of exposure pledges 5, under eToro's
        printed minimum margin of 10. The smallest order eToro takes at 2x
        is 20 USD: 0.0004, and 0.000404 with the headroom."""
        typed = {"risk_per_trade_pct": 0.02, "leverage": 2}
        out = H.run(_on("crypto_under_min", tag="m2", extras=typed))
        row = self.assertOpened(out, qty=0.000404, leverage=2)
        floor = _floor_of(row)
        self.assertEqual(floor["margin_lev"], 2)
        self.assertAlmostEqual(floor["margin_min_units"], 0.0004)
        self.assertAlmostEqual(floor["venue_min_units"], 0.0002)
        self.assertEqual(floor["risk_pct"], 0.101)
        self.assertIn("raised to 0.000404 units, eToro's minimum at 2x "
                      "plus 1%", out.note.call_args.kwargs["floor"])

    def test_with_no_multiplier_the_chooser_reads_it_as_before(self):
        row = self.assertOpened(H.run(_on("crypto_under_min", tag="m1")),
                                qty=0.000202, leverage=1)
        self.assertNotIn("margin_lev", _floor_of(row))


class TheStepTests(_On):

    def test_an_instrument_typed_whole_is_never_raised_to_a_fraction(self):
        """eToro's row types an instrument's units "whole" or
        "fractional". A commodity or a crypto bot rounds to a fraction
        whatever it says; the floor never raises to one."""
        for name in ("commodity_under_min", "crypto_clear"):
            bot = _bot(H.arm(name, "whole"))
            self.assertEqual(bot._floor_step(100.0, False), 1.0, name)
            self.assertEqual(bot._floor_size(0.505, 100.0, False), 1.0, name)
            self.assertLess(bot._floor_step(100.0, None), 1.0, name)


class ThePostureCapTests(_On):

    def test_the_postures_cap_steps_down_to_etoros_list(self):
        """A stressed market caps the multiplier at 15x. eToro lists 2, 5,
        10, 20 and 30: the raised entry goes at 10x, it is not refused for
        a 15x eToro does not list."""
        world = _on("forex_under_min", tag="posture")

        def prepare(bot):
            bot._posture_leverage = lambda symbol, side, lev: (
                (15, "posture stress: with trend capped at 15x (asked "
                     f"{lev}x)") if lev and lev > 15 else (lev, ""))
        out = H.run(world, prepare=prepare)
        row = self.assertOpened(out, qty=1000.0, leverage=10)
        self.assertEqual(
            row.metadata["posture_leverage"],
            "posture stress: with trend capped at 15x (asked 20x): 10x, "
            "the highest under 15x on eToro's LIVE list")
        self.assertEqual(_floor_of(row)["leverage"], 10)


class TheNotesOfAnOrderTests(_On):

    def test_an_order_that_never_left_is_not_a_refusal(self):
        """The connection was never made: eToro refused nothing, and the
        venue's health already holds new entries. No 12-hour note."""
        world = _on("forex_under_min", tag="unsent")
        out = H.run(world, the_venue=H.venue(
            world["price"], world["table"],
            raises=RuntimeError("eToro unreachable (ConnectionError): the "
                                "order for EURUSD was not sent — refused")))
        self.assertEqual(len(H.orders(out)), 1)
        self.assertEqual(H.skip_of(out)["code"], "order_error")
        self.assertNotIn("leverage_refusals", out.cfg.extras)

    def test_an_order_in_doubt_names_the_raised_size(self):
        """No row will say later that the size was raised: the alert
        does."""
        world = _on("forex_under_min", tag="doubt")
        err = RuntimeError("the request did not come back")
        err.in_doubt, err.reference = True, "ref-1"
        with mock.patch("bot_program.notifications.notify_staff") as staff:
            out = H.run(world, the_venue=H.venue(
                world["price"], world["table"], raises=err))
        self.assertEqual(H.skip_of(out)["code"], "order_in_doubt")
        self.assertIn("The order was 1000 units at 20x, raised to the "
                      "venue's smallest size.", staff.call_args.kwargs["body"])

    def test_a_chooser_that_settles_on_one_leaves_no_typed_one(self):
        """A row whose config carries no multiplier has no leverage stamp:
        absent is a state, never a typed 1. The floor's record keeps what
        the chooser settled on."""
        row = self.assertOpened(H.run(_on("crypto_under_min", tag="one")),
                                qty=0.000202, leverage=1)
        self.assertNotIn("leverage", row.metadata)
        self.assertEqual(_floor_of(row)["leverage"], 1)
        self.assertEqual(_floor_of(row)["leverage_by"], "chooser")

    def test_an_unlevered_floored_order_etoro_rejects_is_noted_too(self):
        """eToro ANSWERS the order with a refusal (no exception), at 1x:
        noted, and not sent again on the next pass."""
        H.limit(max_single_position_pct=100, max_pledged_pct=100)
        world = _on("forex_under_min", tag="rej1", leverage=False)
        out = H.run(world, the_venue=H.venue(world["price"], world["table"],
                                             fill=REFUSED))
        self.assertEqual(len(H.orders(out)), 1)
        self.assertEqual(H.skip_of(out)["code"], "order_rejected")
        self.assertEqual(
            out.cfg.extras["leverage_refusals"]["EURUSD"]["leverage"], 1)
        again = H.run(world)
        self.assertEqual(H.orders(again), [])
        self.assertEqual(again.cand.qty_default, 300.0)


class TheFailuresTests(_On):
    """A failure in the floor's own code never raises a size, never sends
    one unchecked and never silences a fill."""

    def test_a_failure_at_the_proposal_leaves_mains_refusal(self):
        world = _on("forex_under_min", tag="x1")

        def prepare(bot):
            bot._floor_size = mock.MagicMock(side_effect=RuntimeError("no"))
        with self.assertLogs("bot_program.asset_engine.base",
                             level="ERROR"):
            out = H.run(world, prepare=prepare)
        self.assertEqual(out.cand.qty_default, 300.0)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertTrue(skip["detail"].startswith(
            "sized 300 units from the stop distance; this venue's minimum "
            "is 925.926. Refused rather than traded at 925.926"), skip)

    def test_a_failure_at_the_order_sends_nothing(self):
        world = _on("forex_under_min", tag="x2")
        box = {}

        def between():
            box["bot"]._floor_bounds = mock.MagicMock(
                side_effect=RuntimeError("no"))
        with self.assertLogs("bot_program.asset_engine.base",
                             level="ERROR"):
            out = H.run(world, prepare=lambda bot: box.update(bot=bot),
                        between=between)
        self.assertEqual(out.cand.qty_default, 1000.0)
        self.assertNothingSent(out)
        self.assertEqual(H.skip_of(out), {
            "code": "venue_min_size",
            "detail": ("the venue floor could not be checked at the order "
                       "— nothing sent")})

    def test_a_failure_in_the_floors_line_keeps_the_fill_message(self):
        world = _on("forex_under_min", tag="x3")

        def prepare(bot):
            bot._floor_line = mock.MagicMock(side_effect=RuntimeError("no"))
        out = H.run(world, prepare=prepare)
        self.assertOpened(out, qty=1000.0, leverage=20)
        self.assertEqual(out.note.call_count, 1)
        self.assertNotIn("floor", out.note.call_args.kwargs)


# ── the words ───────────────────────────────────────────────────────────

class WhoseSizeItIsTests(_On):
    """eToro is credited only with eToro's own figure. A size this bot's
    step rounded up is this bot's, and the words name eToro's minimum
    beside it and the switch that lowers the step."""

    def test_a_whole_share_is_this_bots_smallest_size(self):
        out = H.run(_on("stock_under_one_share", tag="w1"))
        self.assertOpened(out, qty=1.0, leverage=5)
        self.assertEqual(
            out.note.call_args.kwargs["floor"],
            "Smallest size: raised to 1 share, the least this bot sends "
            "that eToro takes (eToro's own minimum is 0.1 shares; whole "
            "shares while Fractional Units is off); the risk budget sized "
            "less than this bot's smallest step · 0.50% of the pool at "
            "risk, against this bot's usual 0.25% · 5x chosen "
            "automatically, as a CFD: eToro charges a fee each night it "
            "is held")

    def test_a_forex_step_is_this_bots_too(self):
        out = H.run(_on("forex_under_min", tag="w2"))
        self.assertOpened(out, qty=1000.0, leverage=20)
        self.assertEqual(
            out.note.call_args.kwargs["floor"],
            "Smallest size: raised to 1,000 units, the least this bot "
            "sends that eToro takes (eToro's own minimum is 925.9 units; "
            "steps of 100 while Fractional Units is off), from the 300 "
            "units the risk budget sized · 0.81% of the pool at risk, "
            "against this bot's usual 0.25% · 20x chosen automatically")

    def test_etoros_own_minimum_is_called_etoros(self):
        out = H.run(_on("commodity_under_min", tag="w3"))
        self.assertOpened(out, qty=0.505, leverage=10)
        self.assertEqual(
            out.note.call_args.kwargs["floor"],
            "Smallest size: raised to 0.505 units, eToro's minimum plus "
            "1%, from the 0.0833 units the risk budget sized · 1.5% of the "
            "pool at risk, against this bot's usual 0.25% · 10x chosen "
            "automatically")

    def test_a_raised_stock_buy_says_it_is_a_cfd(self):
        """A stock buy is the share itself at 1x and a CFD above it, with
        a fee each night. The row keeps the settlement; the line says it.
        A forex entry is a CFD at any multiplier: nothing to add."""
        out = H.run(_on("stock_under_one_share", tag="cfd"))
        row = self.assertOpened(out, qty=1.0, leverage=5)
        floor = _floor_of(row)
        self.assertEqual(floor["settlement"], "cfd")
        self.assertIs(floor["cfd_by_leverage"], True)
        fx = self.assertOpened(H.run(_on("forex_under_min", tag="cfd")),
                               qty=1000.0, leverage=20)
        self.assertEqual(_floor_of(fx)["settlement"], "cfd")
        self.assertNotIn("cfd_by_leverage", _floor_of(fx))

    def test_the_line_after_a_smaller_fill_and_a_rewritten_stop(self):
        bot = _bot(_on("forex_under_min", tag="line"))
        floor = {"floored": True, "qty": 1000.0, "replaced_qty": 300.0,
                 "venue_min_units": 925.925926, "risk_pct": 0.81,
                 "normal_risk_pct": 0.25, "headroom_pct": 1.0,
                 "step": 100.0, "leverage": 20, "leverage_by": "chooser"}
        trade = SimpleNamespace(
            metadata={"broker": "etoro", "value_per_unit": 1.0,
                      "stop_rewritten_by_venue": {"sent": 1.0638},
                      "venue_floor": floor},
            asset_class="forex", symbol="EURUSD", qty=Decimal("400"),
            entry_price=Decimal("1.08"), stop_loss=Decimal("1.0638"))
        line = bot._floor_line(floor, trade)
        self.assertIn(" · eToro filled 400 units of it · ", line)
        self.assertIn("0.32% of the pool at risk at the stop sent, "
                      "against this bot's usual 0.25%", line)

    def test_no_jargon_and_no_french_in_the_lines(self):
        from tests.test_telegram_v2 import jargon
        for name in ("forex_under_min", "stock_under_one_share",
                     "commodity_under_min", "index_under_min",
                     "crypto_under_min"):
            out = H.run(_on(name, tag="plain"))
            line = out.note.call_args.kwargs["floor"]
            self.assertEqual(jargon(line), [], line)
            for bad in FRENCH + ("None", "Decimal(", "{", "}"):
                self.assertNotIn(bad, f" {line} ", line)

    def test_the_refusal_of_a_whole_unit_names_etoros_minimum(self):
        """NAS100 in a stock config without fractions: 30% is the risk of
        one whole unit, this bot's step. eToro's own minimum, 0.05 unit,
        would risk 1.5%."""
        out = H.run(_on("index_whole_units", tag="w4"))
        self.assertIsNone(out.cand)
        skip = H.skip_of(out)
        self.assertEqual(skip, {
            "code": "sized_to_zero",
            "detail": ("this bot's smallest size would risk 30.00% of the "
                       "pool, above your 2% ceiling (MAX BOT FLOOR RISK; "
                       "eToro's minimum is 0.05 units, Fractional Units "
                       "off): sized under one unit")})
        self.assertIn("above your 2% ceiling", skip["detail"][:88])


class TheBellAndTheDetailTests(_On):

    def test_over_the_ceiling_the_detail_fits_and_the_bell_names_the_lever(
            self):
        world = _on("forex_under_min", tag="bell")
        H.ceiling(0.5)
        out = H.run(world)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertEqual(
            skip["detail"],
            "this bot's smallest size would risk 0.81% of the pool, above "
            "your 0.5% ceiling (MAX BOT FLOOR RISK; eToro's minimum is "
            "925.9 units, Fractional Units off): sized 300 units")
        self.assertIn("above your 0.5% ceiling", skip["detail"][:88])
        (body,) = _bell(out.cfg.user)
        self.assertIn("above your 0.5% ceiling (MAX BOT FLOOR RISK", body)
        self.assertIn("a higher MAX BOT FLOOR RISK on /setup/ (up to 7)",
                      body)
        for untrue in ("a different trade", "risk_per_trade_pct"):
            self.assertNotIn(untrue, body)

    def test_with_the_switch_off_the_bell_is_mains(self):
        world = H.arm("forex_under_min", "bell_off")
        H.switch(H.SWITCH, False)
        H.switch(H.LEVERAGE, True)
        out = H.run(world)
        (body,) = _bell(out.cfg.user)
        self.assertIn("which is a different trade", body)
        self.assertNotIn("MAX BOT FLOOR RISK", body)

    def test_the_skip_advice_knows_the_floor(self):
        from bot_program.asset_engine import skips
        world = _on("forex_under_min", tag="adv")
        H.ceiling(0.5)
        out = H.run(world)
        told = skips.diagnose(out.cfg)
        self.assertTrue(told.endswith(
            ". The venue floor is ON: the detail says why this one was "
            "not raised"), told)
        H.switch(H.SWITCH, False)
        self.assertNotIn("venue floor", skips.diagnose(out.cfg))


# ── what no test pinned ─────────────────────────────────────────────────

class TheValuePerUnitTests(_On):
    """The floor's units, risk and notional all carry the value per unit
    (the quote currency's dollar rate on a forex pair). Every instrument
    of the harness is quoted in USD (1.0), so nothing pinned it."""

    def test_the_minimum_the_risk_and_the_notional_carry_it(self):
        """As if EURUSD's quote currency were worth 1.25 USD: eToro's
        1,000 USD is 740.74 units, 800 on the step; at the stop 800 x
        0.0162 x 1.25 = 16.20, 0.81% of the pool; 1,080.00 of notional,
        0.54 times the pool."""
        out = H.run(_on("forex_under_min", tag="vpu"), prepare=_vpu(1.25))
        row = self.assertOpened(out, qty=800.0, leverage=20)
        floor = _floor_of(row)
        self.assertAlmostEqual(floor["venue_min_units"], 740.740741,
                               places=5)
        self.assertEqual(floor["risk_pct"], 0.81)
        self.assertEqual(floor["notional_x_pool"], 0.54)
        self.assertEqual(row.metadata["value_per_unit"], 1.25)

    def test_the_ceiling_judges_the_risk_in_dollars(self):
        """The risk without the value per unit (800 x 0.0162 = 12.96,
        0.65%) would pass a 0.7% ceiling."""
        world = _on("forex_under_min", tag="vpu_c")
        H.ceiling(0.7)
        out = H.run(world, prepare=_vpu(1.25))
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertTrue(skip["detail"].startswith(
            "this bot's smallest size would risk 0.81% of the pool, above "
            "your 0.7% ceiling (MAX BOT FLOOR RISK; "), skip)

    def test_the_class_cap_judges_the_notional_in_dollars(self):
        """The notional without the value per unit (800 x 1.08 = 864.00,
        0.43 times) would pass a 0.5 cap."""
        capped = {"session_filter_disabled": True,
                  "max_notional_fraction": 0.5}
        out = H.run(_on("forex_under_min", tag="vpu_n", extras=capped),
                    prepare=_vpu(1.25))
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertTrue(skip["detail"].startswith(
            "this bot's smallest size is 0.540 times the pool, above the "
            "0.5 times this class may carry ("), skip)


class TheSwitchThatCannotBeReadTests(_On):

    def test_a_row_that_cannot_be_read_is_off(self):
        """Never on by a failure."""
        from bot_program.asset_engine import base
        world = _on("forex_under_min", tag="unread")
        with mock.patch("core.platform_control.is_component_enabled",
                        side_effect=RuntimeError("no row can be read")):
            with self.assertLogs("bot_program.asset_engine.base",
                                 level="WARNING") as logs:
                self.assertIs(base.venue_floor_on(), False)
            self.assertIn("read as OFF", logs.output[0])
            verdict = _bot(world)._venue_floor(
                H.venue(world["price"], world["table"]), "EURUSD",
                stage={"force_paper": False}, qty=300.0, price=1.08,
                sl=1.0638, sizing={"risk_fraction": 0.0025}, sized=308.6)
        self.assertEqual(verdict, {"state": "off"})


class TheUnpinnedPlacesTests(_On):

    def test_another_venue_is_never_asked_at_the_proposal(self):
        """eToro only: another adapter that states a minimum of its own is
        not raised to, and is not asked."""
        class OtherVenue(mock.MagicMock):
            def min_tradable(self, symbol):
                raise AssertionError("asked")
        verdict = _bot(_on("forex_under_min", tag="oth"))._venue_floor(
            OtherVenue(), "EURUSD", stage={"force_paper": False}, qty=300.0,
            price=1.08, sl=1.0638, sizing={"risk_fraction": 0.0025},
            sized=308.6)
        self.assertEqual(verdict, {"state": "off"})

    def test_a_cap_lowered_between_two_reads_says_the_chooser_picked(self):
        """The chooser bounds its pick by MAX BOT LEVERAGE; the cap is
        read again after it. A cap the operator lowered in between is
        applied, and the words name whose number it lowers."""
        H.limit(max_bot_leverage=5)
        world = _on("forex_under_min", tag="cap")
        sent, note = _bot(world)._bot_cap_leverage(
            H.venue(world["price"], world["table"]), "EURUSD", "BUY", 20,
            picked=True)
        self.assertEqual(sent, 5)
        self.assertEqual(note["why"], "capped at 5x by MAX BOT LEVERAGE "
                                      "(the chooser picked 20x)")

    def test_the_debates_cut_keeps_the_choosers_multiplier(self):
        """The trade debate cuts a raised XAUUSD entry by half a percent:
        0.5025 units still clear eToro's 0.5. The multiplier is chosen
        again for the cut size, by the chooser, as for the raised one."""
        world = _on("commodity_under_min", tag="debate")
        v = H.venue(world["price"], world["table"])
        v.demo = 1      # truthy, and not the demo world the debate skips
        verdict = {"on": True, "ran": True, "binding": True, "scale": 0.995,
                   "why": "cut", "executioner": {}, "champion": {},
                   "champion_wins": True}
        with mock.patch("ai_agents.agents.trade_debate.debate_candidate",
                        return_value=verdict):
            out = H.run(world, the_venue=v)
        self.assertIsNotNone(out.res, H.skip_of(out))
        (sent,) = H.orders(out)
        self.assertEqual(sent[2], 0.5025)
        self.assertEqual(sent[3]["leverage"], 10)
        # the row keeps both sizes, and the line says which was sent
        floor = _floor_of(H.trade_rows(out)[0])
        self.assertEqual((floor["qty"], floor["sent_qty"]), (0.505, 0.5025))
        self.assertIn(" · cut to 0.5025 units before the order · ",
                      out.note.call_args.kwargs["floor"])
        self.assertNotIn("filled", out.note.call_args.kwargs["floor"])

    def test_a_debate_cut_under_the_minimum_sends_nothing(self):
        """Half of a raised size is under eToro's minimum: nothing is
        sent, never a second raise."""
        world = _on("commodity_under_min", tag="debate2")
        v = H.venue(world["price"], world["table"])
        v.demo = 1
        verdict = {"on": True, "ran": True, "binding": True, "scale": 0.5,
                   "why": "cut", "executioner": {}, "champion": {},
                   "champion_wins": True}
        with mock.patch("ai_agents.agents.trade_debate.debate_candidate",
                        return_value=verdict):
            out = H.run(world, the_venue=v)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "sized_to_zero")
        self.assertIn("the Executioner cut it to 0.5x", skip["detail"])


class WhatTheRunbookSaysTests(_On):
    """Two sentences of the RUNBOOK's section, pinned."""

    def test_max_bot_leverage_one_keeps_a_raised_entry_unlevered(self):
        """The share itself, not a CFD: no multiplier, no nightly fee."""
        H.limit(max_bot_leverage=1)
        out = H.run(_on("stock_under_one_share", tag="cap1"))
        row = self.assertOpened(out, qty=1.0, leverage=1)
        floor = _floor_of(row)
        self.assertEqual(floor["settlement"], "real")
        self.assertNotIn("cfd_by_leverage", floor)
        self.assertNotIn("CFD", out.note.call_args.kwargs["floor"])
        self.assertNotIn("chosen automatically",
                         out.note.call_args.kwargs["floor"])

    def test_with_fractions_on_a_stocks_minimum_does_not_carry_the_fee(self):
        """AAPL with eToro's fractions on and a budget under 10 USD:
        raised to 0.101 share, 10.10 USD, on which eToro's 1.00 USD a side
        is a fifth. The fee filter refuses it, on the raised size."""
        tiny = {"risk_per_trade_pct": 0.02}
        out = H.run(_on("stock_under_one_share", tag="fee", fractions=True,
                        extras=tiny))
        self.assertEqual(out.cand.qty_default, 0.101)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "cost_filter")
        self.assertTrue(skip["detail"].startswith(
            "at the venue's smallest size: "), skip)
        self.assertIn("2.00 on 10.10", skip["detail"])
