"""THE VENUE FLOOR FOR BOTS (2026-11-12).

The operator, 2026-11-12: "je veux tous mes bots live right now", "qu'il
soit smart pour s'ajuster au marché et y pouvoir rentrer tout du moins". His
bots almost never open: a bot risks 0.25% of its pool per trade, and on a
small account the size that gives is under eToro's minimum exposure on
forex, indices and commodities, or rounds to zero on stocks. The skips say
so: venue_min_size, sized_to_zero.

The floor: with the live-money switch bots_venue_floor_live ON, a bot's
order that is under the venue's smallest size opens AT that size, when the
risk of that size at the stop is at most MAX BOT FLOOR RISK (%) of its pool
(the /setup/ card, default 2, never above the 7% hard cap) and its notional
is inside the class's cap, and every other gate still passes on the raised
size. A bot with no multiplier of its own lets the attack mode's chooser
pick one for a floor entry; a typed multiplier is kept.

Pinned here, on synthetic entries (tests/bot_venue_floor_harness.py):

  * OFF, and with no row at all: every decision, size, skip, word, stored
    row and request is the one main gave, recorded on main before the floor
    touched the entry path (tests/bot_venue_floor_golden.json;
    BOT_FLOOR_RECORD=1 records it);
  * ON: forex, index, commodity, stock and crypto under the minimum open at
    the smallest size under the ceiling, and are refused with the words
    that say why over it; an unmeasured minimum never floors;
  * every other gate on the raised size, one test a gate;
  * the leverage rule; EUR- and USD-labelled pools; a probation size; the
    quiets; the desk's cut; the switch turned off before the send;
  * the row, the audit row and the fill message of a floored entry;
  * a paper config and a live config's paper-stage entry, unchanged.

Run with:  python manage.py test tests.test_bot_venue_floor
"""
import json
import os
from decimal import Decimal
from pathlib import Path
from unittest import mock

from django.test import TestCase

from tests import bot_venue_floor_harness as H

RECORD = os.environ.get("BOT_FLOOR_RECORD") == "1"
GOLDEN_FILE = Path(__file__).with_name("bot_venue_floor_golden.json")


def _golden() -> dict:
    return json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))


def _table(state, tag) -> dict:
    """Every scenario's snapshot with the floor's switch in `state` (None:
    no row, False: OFF, True: ON) and the live leverage switch ON."""
    H.switch(H.SWITCH, state)
    H.switch(H.LEVERAGE, True)
    return {name: H.snapshot(H.run(H.arm(name, tag)))
            for name in H.SCENARIOS}


# ── OFF is main ─────────────────────────────────────────────────────────

class TheSwitchOffIsMainTests(TestCase):
    """Money direction with the switch OFF: none. The table of synthetic
    entries, across the five classes, decided exactly as main decided it."""

    maxDiff = None

    def test_with_no_row_every_entry_is_mains(self):
        first = _table(None, "a")
        if RECORD:
            # recorded on main: stable across two runs, then written
            self.assertEqual(first, _table(None, "b"))
            GOLDEN_FILE.write_text(
                json.dumps(first, indent=1, sort_keys=True) + "\n",
                encoding="utf-8")
            return
        golden = _golden()
        self.assertEqual(sorted(first), sorted(golden))
        for name in H.SCENARIOS:
            self.assertEqual(first[name], golden[name], name)

    def test_with_the_row_off_every_entry_is_mains(self):
        if RECORD:
            self.skipTest("recording")
        table = _table(False, "off")
        golden = _golden()
        for name in H.SCENARIOS:
            self.assertEqual(table[name], golden[name], name)

    def test_the_table_covers_the_five_classes_and_both_refusals(self):
        """The golden itself: main refuses these entries where the operator
        saw it refuse them (venue_min_size, sized_to_zero), opens the ones
        the venue takes, and books a paper row where the stage says paper."""
        if RECORD:
            self.skipTest("recording")
        golden = _golden()
        self.assertEqual(
            {H.SCENARIOS[n]["icls"] for n in golden},
            {"forex", "index", "commodity", "stock", "crypto"})
        codes = {n: golden[n]["skip"].get("code") for n in golden}
        for name in ("forex_under_min", "forex_typed_leverage",
                     "forex_auto_leverage", "commodity_under_min",
                     "index_under_min", "crypto_under_min",
                     "forex_probation"):
            self.assertEqual(codes[name], "venue_min_size", name)
            self.assertEqual(golden[name]["orders"], [], name)
        for name in ("index_whole_units", "stock_under_one_share",
                     "stock_unread_row"):
            self.assertEqual(codes[name], "sized_to_zero", name)
            self.assertEqual(golden[name]["orders"], [], name)
        for name in ("crypto_clear", "stock_clear"):
            self.assertEqual(len(golden[name]["orders"]), 1, name)
            self.assertEqual(len(golden[name]["trades"]), 1, name)
        for name in ("forex_paper_stage", "forex_paper_config"):
            self.assertEqual(golden[name]["orders"], [], name)
            self.assertEqual([t["paper"] for t in golden[name]["trades"]],
                             [True], name)
        # nothing main stores names the floor
        self.assertNotIn("venue_floor", json.dumps(golden))
        self.assertNotIn("smallest size", json.dumps(golden))


# ── ON ──────────────────────────────────────────────────────────────────

FRENCH = (" le ", " la ", " les ", " des ", " du ", " une ", " est ",
          " pour ", " avec ", " sur ", " vous ", "é", "è", "ê", "à ", "ç",
          "ù")


def _on(name, tag="on", *, leverage=True, **changes):
    """One scenario's world with the floor's switch ON (and the live
    leverage switch as stated)."""
    world = H.arm(name, tag, **changes)
    H.switch(H.SWITCH, True)
    H.switch(H.LEVERAGE, leverage)
    return world


def _floor_of(row):
    return (row.metadata or {}).get("venue_floor")


class _On(TestCase):
    maxDiff = None

    def assertOpened(self, out, *, qty, leverage=None):
        """One order of `qty` left, one row holds it, and it is floored."""
        self.assertIsNotNone(out.res, H.skip_of(out))
        sent = H.orders(out)
        self.assertEqual(len(sent), 1, sent)
        self.assertEqual(sent[0][2], qty)
        if leverage is None or leverage <= 1:
            self.assertNotIn("leverage", sent[0][3])
        else:
            self.assertEqual(sent[0][3]["leverage"], leverage)
        rows = H.trade_rows(out)
        self.assertEqual(len(rows), 1)
        self.assertEqual(float(rows[0].qty), qty)
        self.assertFalse(rows[0].paper)
        self.assertIs(_floor_of(rows[0])["floored"], True)
        return rows[0]

    def assertNothingSent(self, out):
        self.assertIsNone(out.res)
        self.assertEqual(H.orders(out), [])
        self.assertEqual(H.trade_rows(out), [])


class TheFloorOpensTests(_On):
    """An order under the venue's smallest size opens at that size."""

    def test_forex_under_the_minimum_opens_at_the_smallest_size(self):
        """EURUSD at 1.0800, a 2,000 pool, a 1.5% stop: the risk budget
        sizes 300 units (324 USD), eToro's minimum is 1,000 USD: 925.93
        units, 1,000 on the forex bot's 100-unit step. At the stop that is
        16.20, 0.81% of the pool, under the 2% ceiling."""
        out = H.run(_on("forex_under_min"))
        self.assertEqual(out.cand.qty_default, 1000.0)
        self.assertAlmostEqual(out.cand.risk_dollars_default, 16.2)
        self.assertAlmostEqual(out.cand.notional_default, 1080.0)
        row = self.assertOpened(out, qty=1000.0, leverage=20)
        floor = _floor_of(row)
        self.assertEqual(floor["replaced_qty"], 300.0)
        self.assertEqual(floor["qty"], 1000.0)
        self.assertAlmostEqual(floor["venue_min_units"], 925.925926, places=5)
        self.assertEqual(floor["risk_pct"], 0.81)
        self.assertEqual(floor["normal_risk_pct"], 0.25)
        self.assertEqual(floor["replaced_risk_pct"], 0.243)
        self.assertEqual(floor["ceiling_pct"], 2.0)
        self.assertEqual(floor["notional_x_pool"], 0.54)
        self.assertEqual(H.skip_of(out), {})
        # nothing reached the wire: the row, the quote and the order are
        # the venue's stated answers
        self.assertEqual(out.venue.wire.calls, [])

    def test_a_commodity_under_the_minimum_opens_at_the_smallest_size(self):
        """XAUUSD at 2,000, a 1,000 pool: 0.0833 units sized, 0.5 is the
        minimum; 15.00 at the stop, 1.5% of the pool."""
        out = H.run(_on("commodity_under_min"))
        row = self.assertOpened(out, qty=0.5, leverage=10)
        floor = _floor_of(row)
        self.assertEqual(floor["replaced_qty"], 0.0833)
        self.assertEqual(floor["risk_pct"], 1.5)
        self.assertEqual(floor["notional_x_pool"], 1.0)

    def test_an_index_under_the_minimum_opens_at_the_smallest_size(self):
        """NAS100 at 20,000 in a stock config, eToro's fractions on:
        0.0083 units sized, 0.05 is the minimum; 15.00 at the stop."""
        out = H.run(_on("index_under_min"))
        row = self.assertOpened(out, qty=0.05, leverage=20)
        floor = _floor_of(row)
        self.assertEqual(floor["replaced_qty"], 0.0083)
        self.assertEqual(floor["risk_pct"], 1.5)
        self.assertIs(row.metadata["fractional_units"], True)

    def test_a_stock_whose_budget_buys_under_one_share_opens_at_one(self):
        """AAPL at 100, a 1,000 pool, a 5% stop: the budget buys half a
        share, which a live stock config rounds to zero (sized_to_zero on
        main). eToro's minimum is 10 USD, a tenth of a share: the smallest
        size this bot sends is one whole share, 5.00 at the stop, 0.5%."""
        out = H.run(_on("stock_under_one_share"))
        self.assertEqual(out.cand.qty_default, 1.0)
        row = self.assertOpened(out, qty=1.0, leverage=5)
        floor = _floor_of(row)
        self.assertEqual(floor["replaced_qty"], 0.0)
        self.assertEqual(floor["qty"], 1.0)
        self.assertAlmostEqual(floor["venue_min_units"], 0.1)
        self.assertEqual(floor["risk_pct"], 0.5)
        self.assertEqual(floor["replaced_risk_pct"], 0.0)

    def test_crypto_under_the_minimum_opens_at_the_smallest_size(self):
        """BTCUSD at 50,000 with a 0.02% risk setting: 0.00008 sized, 10
        USD is 0.0002; the chooser finds no multiplier whose margin eToro
        takes and settles on the unlevered order."""
        out = H.run(_on("crypto_under_min"))
        row = self.assertOpened(out, qty=0.0002, leverage=1)
        floor = _floor_of(row)
        self.assertEqual(floor["replaced_qty"], 8e-05)
        self.assertEqual(floor["risk_pct"], 0.05)
        self.assertEqual(floor["normal_risk_pct"], 0.02)
        self.assertEqual(floor["leverage"], 1)

    def test_a_size_the_venue_takes_is_untouched(self):
        """Above the minimum nothing is raised: with the switch ON these
        entries are main's, to the stored key (the proposal only reads the
        row it reads at the send, once more)."""
        golden = _golden()
        for name in ("crypto_clear", "stock_clear"):
            snap = H.snapshot(H.run(_on(name)))
            asked = snap.pop("rows_asked")
            want = dict(golden[name])
            self.assertGreater(len(asked), len(want.pop("rows_asked")))
            self.assertEqual(snap, want, name)

    def test_the_smallest_size_is_the_hand_tickets(self):
        """ONE floor function for both lanes: on the same client, price
        and step, the hand ticket's minimum (manual_trade._venue_min_qty
        over AssetBot._venue_size_floor) is the size the bot opens at."""
        from bot_program.manual_trade import _venue_min_qty
        for name, step in (("forex_under_min", 100.0),
                           ("commodity_under_min", 1e-4),
                           ("index_under_min", 1e-4),
                           ("stock_under_one_share", 1.0),
                           ("crypto_under_min", 1e-8)):
            world = _on(name, tag="hand")
            out = H.run(world)
            hand, why = _venue_min_qty(
                H.venue(world["price"], world["table"]), world["symbol"],
                float(world["price"]),
                out.bot._value_per_unit(world["symbol"]), step)
            self.assertEqual(why, "", name)
            self.assertAlmostEqual(out.cand.qty_default, hand, places=9,
                                   msg=name)

    def test_the_step_is_the_bots_own_rounding(self):
        """The smallest size sits on the step the bot's _round_qty keeps
        with the venue's fraction answer, so the second rounding at the
        send does not move it."""
        from bot_program.asset_engine.base import make_bot
        want = {("forex", None): 100.0, ("forex", False): 100.0,
                ("forex", True): 1.0, ("stock", None): 1.0,
                ("stock", False): 1.0, ("stock", True): 1e-4,
                ("commodity", None): 1e-4, ("commodity", True): 1e-4,
                ("crypto", None): 1e-8, ("crypto", True): 1e-8}
        names = {"forex": "forex_under_min", "stock": "stock_clear",
                 "commodity": "commodity_under_min",
                 "crypto": "crypto_clear"}
        bots = {cls: make_bot(H.arm(name, "step")["cfg"])
                for cls, name in names.items()}
        for (cls, fractional), step in want.items():
            bot = bots[cls]
            self.assertEqual(bot._floor_step(100.0, fractional), step,
                             (cls, fractional))
            for k in (1, 3, 17):
                self.assertAlmostEqual(
                    bot._round_qty(k * step, 100.0, fractional=fractional),
                    k * step, places=12, msg=(cls, fractional, k))


class TheCeilingTests(_On):
    """MAX BOT FLOOR RISK bounds the raise; past it the old refusal
    stands, and its words say why."""

    def test_over_the_ceiling_keeps_venue_min_size_and_says_why(self):
        world = _on("forex_under_min")
        H.ceiling(0.5)
        out = H.run(world)
        self.assertEqual(out.cand.qty_default, 300.0)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertTrue(skip["detail"].startswith(
            "the venue's smallest size would risk 0.81% of the pool, above "
            "your 0.5% ceiling (MAX BOT FLOOR RISK): sized 300 units from "
            "the stop distance; this venue's minimum is 925.926."), skip)
        # the reason sits inside what why_no_trade prints of a detail
        self.assertIn("above your 0.5% ceiling", skip["detail"][:88])

    def test_over_the_ceiling_keeps_sized_to_zero_and_says_why(self):
        """NAS100 in a stock config without fractions: the smallest size
        this bot sends is one whole unit, 20,000 USD: 300.00 at the stop,
        30% of the pool."""
        out = H.run(_on("index_whole_units"))
        self.assertIsNone(out.cand)
        self.assertNothingSent(out)
        self.assertEqual(H.skip_of(out), {
            "code": "sized_to_zero",
            "detail": ("the venue's smallest size would risk 30.00% of the "
                       "pool, above your 2% ceiling (MAX BOT FLOOR RISK): "
                       "risk budget 0.25% of 1000 is below one tradeable "
                       "unit")})

    def test_a_risk_at_the_ceiling_opens(self):
        world = _on("forex_under_min")
        H.ceiling(0.81)
        self.assertOpened(H.run(world), qty=1000.0, leverage=20)

    def test_the_default_is_two_percent(self):
        """The same commodity on a 700 pool: 15.00 at the stop is 2.14%."""
        world = _on("commodity_under_min", pool="700")
        out = H.run(world)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertTrue(skip["detail"].startswith(
            "the venue's smallest size would risk 2.14% of the pool, above "
            "your 2% ceiling (MAX BOT FLOOR RISK): "), skip)

    def test_the_class_notional_cap_binds_the_floor(self):
        """A 400 USD share on a 1,000 pool: one share risks 20.00, 2% of
        the pool, and is 0.4 times the pool, where sizing never lets a
        stock position pass 0.2 times. Not raised."""
        out = H.run(_on("stock_under_one_share", price="400.00"))
        self.assertNothingSent(out)
        self.assertEqual(H.skip_of(out), {
            "code": "sized_to_zero",
            "detail": ("the venue's smallest size is 0.4 times the pool, "
                       "above the 0.2 times this class may carry: risk "
                       "budget 0.25% of 1000 is below one tradeable unit")})

    def test_a_setting_that_cannot_be_read_raises_nothing(self):
        """A value past the card's bounds (only a write past the card puts
        one there) is no ceiling: no floor entry at all."""
        world = _on("forex_under_min")
        H.ceiling(25.0)
        out = H.run(world)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertTrue(skip["detail"].startswith(
            "MAX BOT FLOOR RISK cannot be read, so nothing is raised to "
            "the venue's smallest size: "), skip)


class TheUnmeasuredMinimumTests(_On):
    """A minimum the venue does not state is never guessed."""

    def test_an_unmeasured_minimum_never_floors(self):
        """The row is typed in another currency: the minimum reads
        unmeasured, and the entry is main's, to the stored key."""
        snap = H.snapshot(H.run(_on("forex_unmeasured")))
        want = dict(_golden()["forex_unmeasured"])
        self.assertGreater(len(snap.pop("rows_asked")),
                           len(want.pop("rows_asked")))
        self.assertEqual(snap, want)

    def test_an_unread_row_never_floors_a_size_of_zero(self):
        out = H.run(_on("stock_unread_row"))
        self.assertNothingSent(out)
        self.assertEqual(H.skip_of(out), {
            "code": "sized_to_zero",
            "detail": ("the venue's smallest size is unread, so nothing is "
                       "raised to it: risk budget 0.25% of 1000 is below "
                       "one tradeable unit")})

    def test_an_operator_declared_floor_is_not_raised_to(self):
        """extras['venue_min_notional'] is the operator's own figure, a
        labelled state of the floor function: it refuses before the order,
        as on main, and is never a size to raise to."""
        world = _on("stock_unread_row",
                    extras={"venue_min_notional": 150})
        out = H.run(world)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "sized_to_zero")
        self.assertTrue(skip["detail"].startswith(
            "the venue's smallest size is unread, so nothing is raised to "
            "it: "), skip)

    def test_no_dollar_rate_never_floors(self):
        """A forex pair with no fresh dollar rate sizes to zero rather
        than to a wrong number: zero before any rounding, so nothing is
        raised and the venue's row is not asked for it."""
        world = _on("forex_under_min")
        out = H.run(world, prepare=lambda bot: setattr(
            bot, "_value_per_unit", lambda symbol: 0.0))
        self.assertNothingSent(out)
        self.assertEqual(out.venue.asked, [])
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "sized_to_zero")
        self.assertTrue(skip["detail"].startswith(
            "the size was zero before any rounding, so nothing is raised "
            "to the venue's smallest size: "), skip)

    def test_a_risk_setting_of_zero_never_floors(self):
        """A bot whose own risk per trade is zero sizes nothing by its
        operator's choice: that is a decision, not a small pool."""
        zero = {"session_filter_disabled": True, "risk_per_trade_pct": 0}
        out = H.run(_on("forex_under_min", extras=zero))
        self.assertIsNone(out.cand)
        self.assertNothingSent(out)
        self.assertEqual(out.venue.asked, [])
        self.assertEqual(H.skip_of(out), {
            "code": "sized_to_zero",
            "detail": ("the size was zero before any rounding, so nothing "
                       "is raised to the venue's smallest size: risk "
                       "budget 0.00% of 2000 is below one tradeable "
                       "unit")})

    def test_a_setup_its_stop_floor_skipped_never_floors(self):
        """extras["on_stop_floor"] = "skip": a stop tighter than the stop
        floor is the operator's refusal of the setup, and stays one."""
        skipping = {"on_stop_floor": "skip"}
        out = H.run(_on("stock_under_one_share", sl=1.0, tp=3.0,
                        extras=skipping))
        self.assertIsNone(out.cand)
        self.assertNothingSent(out)
        self.assertEqual(out.venue.asked, [])
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "sized_to_zero")
        self.assertTrue(skip["detail"].startswith(
            "the size was zero before any rounding, so nothing is raised "
            "to the venue's smallest size: "), skip)


class EveryOtherGateTests(_On):
    """Each gate judges the RAISED size: at the risk-sized quantity main
    passes the gate (and then refuses for the venue's minimum), and the
    smallest size is refused by the gate itself, with the gate's words."""

    def _main_code(self, name, tag, **changes):
        """What main's refusal is for the same entry (the switch OFF)."""
        world = H.arm(name, tag, **changes)
        H.switch(H.SWITCH, False)
        H.switch(H.LEVERAGE, True)
        return H.skip_of(H.run(world)).get("code")

    def test_max_single_position(self):
        """A typed 10x: 1,080 USD pledges 108.00, past 5% of the 2,000
        pool; the risk-sized 324 USD pledged 32.40 and passed."""
        typed = {"session_filter_disabled": True, "leverage": 10}
        H.limit(max_single_position_pct=5)
        self.assertEqual(self._main_code("forex_under_min", "m",
                                         extras=typed), "venue_min_size")
        out = H.run(_on("forex_under_min", extras=typed))
        self.assertNothingSent(out)
        self.assertEqual(H.skip_of(out), {
            "code": "gate_blocked",
            "detail": ("at the venue's smallest size: this position ties "
                       "up 108.00 — past the 100.00 a single position may "
                       "hold (5% of the 2,000.00 bot pool)")})

    def test_max_open_risk(self):
        H.limit(max_open_risk_pct=0.5)
        self.assertEqual(self._main_code("forex_under_min", "m"),
                         "venue_min_size")
        out = H.run(_on("forex_under_min"))
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "gate_blocked")
        self.assertTrue(skip["detail"].startswith(
            "at the venue's smallest size: open risk limit: 0.00 at the "
            "stops of 0 open position(s) + 16.20 for this entry against a "
            "10.00 ceiling"), skip)

    def test_max_notional_multiple(self):
        H.limit(max_notional_multiple=0.3)
        self.assertEqual(self._main_code("forex_under_min", "m"),
                         "venue_min_size")
        out = H.run(_on("forex_under_min"))
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "gate_blocked")
        self.assertTrue(skip["detail"].startswith(
            "at the venue's smallest size: 1,080.00 of notional open with "
            "this entry"), skip)
        self.assertIn("the cap is 0.3x (600.00)", skip["detail"])

    def test_past_the_daily_loss_limit_nothing_is_raised(self):
        """The daily loss rule is unchanged: past the limit an elite entry
        goes at half its size, never raised, and a candidate that is not
        elite is refused as before."""
        def past(elite):
            def prepare(bot):
                bot._elite_only = "book risk limits: daily loss limit hit"
                bot._elite_verdict = lambda *a, **k: {"elite": elite,
                                                      "why": "its record"}
            return prepare
        out = H.run(_on("forex_under_min", tag="elite"),
                    prepare=past(True))
        self.assertEqual(out.cand.qty_default, 200.0)   # half of 308.6
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertTrue(skip["detail"].startswith(
            "past the daily loss limit no entry is raised to the venue's "
            "smallest size: sized 200 units from the stop distance"), skip)
        out = H.run(_on("forex_under_min", tag="not_elite"),
                    prepare=past(False))
        self.assertIsNone(out.cand)
        self.assertEqual(H.skip_of(out), {
            "code": "gate_blocked",
            "detail": ("book risk limits: daily loss limit hit — not "
                       "elite: its record")})

    def test_free_cash(self):
        """The cash gate reads the smallest size at the multiplier sent:
        1,080 USD at 20x needs 54.00 of margin, and 10.00 is free."""
        out = H.run(_on("forex_under_min", cash="10"))
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "leverage_refused")
        self.assertTrue(skip["detail"].startswith(
            "at the venue's smallest size: at 20x: EURUSD needs 54.00 USD "
            "of margin and 10.00 is free"), skip)

    def test_the_pledge_ceiling(self):
        """960.00 already pledged of a 2,000 account: 54.00 more is 51%,
        past MAX ACCOUNT PLEDGED (50)."""
        out = H.run(_on("forex_under_min", used="960"))
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "leverage_refused")
        self.assertTrue(skip["detail"].startswith(
            "at the venue's smallest size: at 20x: the account would be "
            "51% pledged after EURUSD"), skip)

    def test_etoros_maximum_units(self):
        table = H.rows()
        table["EURUSD"] = dict(table["EURUSD"], maxUnitsPerOrder=500)
        self.assertEqual(self._main_code("forex_under_min", "m",
                                         table=table), "venue_min_size")
        out = H.run(_on("forex_under_min", table=table))
        self.assertNothingSent(out)
        self.assertEqual(H.skip_of(out), {
            "code": "eligibility_refused",
            "detail": ("at the venue's smallest size: sized 1000 units; "
                       "eToro's maxUnitsPerOrder for EURUSD is 500 — "
                       "refused, not clamped (a clamp is a different "
                       "trade)")})

    def test_the_venues_fee(self):
        """One AAPL share is 100 USD and eToro takes 1.00 USD a side: 2%
        of it. With a 10% target the reward to risk falls under 1.5 after
        that fee, and the fee filter refuses the smallest size."""
        out = H.run(_on("stock_under_one_share", tp=10.0))
        self.assertEqual(out.cand.qty_default, 1.0)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "cost_filter")
        self.assertTrue(skip["detail"].startswith(
            "at the venue's smallest size: reward:risk falls to "), skip)
        self.assertIn("eToro takes 1.00 USD on each side of a stock order: "
                      "2.00 on 100.00", skip["detail"])

    def test_a_duplicate_is_still_refused(self):
        from bot_program.models import AssetBotTrade
        world = _on("forex_under_min")
        other = H._live_cfg(world["user"], "forex", name="F held")
        AssetBotTrade.objects.create(
            config=other, asset_class="forex", symbol="EURUSD", side="BUY",
            qty=Decimal("100"), entry_price=Decimal("1.08"),
            stop_loss=Decimal("1.07"), take_profit=Decimal("1.10"),
            status="OPEN", paper=False)
        out = H.run(world)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "gate_blocked")
        self.assertIn("is already on the", skip["detail"])

    def test_the_last_look(self):
        """The price moved more than half-way to the stop between the
        proposal and the order: nothing is sent."""
        world = _on("forex_under_min")
        the_venue = H.venue(world["price"], world["table"])
        the_venue.ticker = mock.MagicMock(side_effect=[
            {"lastPrice": "1.0800"}, {"lastPrice": "1.0700"}])
        out = H.run(world, the_venue=the_venue)
        self.assertEqual(out.cand.qty_default, 1000.0)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "gate_blocked")
        self.assertIn("of the way", skip["detail"])


class TheLeverageRuleTests(_On):
    """No setting: the chooser picks for a floor entry. A typed number is
    kept. Every existing leverage rule holds."""

    def test_no_setting_lets_the_chooser_pick(self):
        """30x would put the 1.5% stop at 45% of the margin, past the
        headroom of the assumed band: 20x, the next on eToro's list."""
        out = H.run(_on("forex_under_min"))
        row = self.assertOpened(out, qty=1000.0, leverage=20)
        self.assertEqual(row.metadata["leverage"], 20)
        floor = _floor_of(row)
        self.assertEqual(floor["leverage"], 20)
        self.assertEqual(floor["leverage_by"], "chooser")
        self.assertTrue(floor["leverage_why"].startswith(
            "auto: 20x — the highest on EURUSD's LIVE long/cfd list "
            "[2, 5, 10, 20, 30] inside the forex ceiling (30x)"), floor)
        # the risk half of the attack mode is not applied: no tier
        self.assertNotIn("attack", row.metadata)
        self.assertEqual(row.metadata["risk_fraction"], 0.0025)
        # nothing is written on the config: the next entry is asked again
        self.assertNotIn("leverage", out.cfg.extras)

    def test_a_typed_number_is_kept(self):
        typed = {"session_filter_disabled": True, "leverage": 10}
        out = H.run(_on("forex_under_min", extras=typed))
        row = self.assertOpened(out, qty=1000.0, leverage=10)
        self.assertEqual(row.metadata["leverage"], 10)
        self.assertEqual(_floor_of(row)["leverage_by"], "typed")
        self.assertEqual(_floor_of(row)["leverage"], 10)

    def test_the_attack_mode_keeps_its_own_rule(self):
        """An "auto" config is the attack mode it was: its tier sized the
        risk (STRONG, three quarters: a high score with no measured edge),
        its chooser picks, and the floor raises the 200 units it sized."""
        out = H.run(_on("forex_auto_leverage"))
        row = self.assertOpened(out, qty=1000.0, leverage=20)
        self.assertEqual(row.metadata["attack"]["tier"], "STRONG")
        self.assertEqual(row.metadata["attack"]["leverage"], 20)
        floor = _floor_of(row)
        self.assertEqual(floor["replaced_qty"], 200.0)
        self.assertEqual(floor["leverage_by"], "auto")
        self.assertNotIn("leverage_why", floor)
        self.assertEqual(floor["normal_risk_pct"], 0.1875)
        self.assertEqual(row.metadata["risk_fraction"], 0.001875)

    def test_the_live_leverage_switch_off_refuses_a_typed_number(self):
        """The existing refusal, word for word: nothing at 10, nothing at
        1."""
        typed = {"session_filter_disabled": True, "leverage": 10}
        out = H.run(_on("forex_under_min", leverage=False, extras=typed))
        self.assertEqual(out.cand.qty_default, 1000.0)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "leverage_refused")
        self.assertTrue(skip["detail"].startswith(
            "at the venue's smallest size: at 10x: etoro_leverage_live is "
            "OFF"), skip)

    def test_the_live_leverage_switch_off_the_chooser_answers_one(self):
        """With the switch OFF the chooser answers 1x, and MAX SINGLE
        POSITION counts the whole 1,080 USD: past 20% of the pool."""
        out = H.run(_on("forex_under_min", leverage=False))
        self.assertNothingSent(out)
        self.assertEqual(H.skip_of(out), {
            "code": "gate_blocked",
            "detail": ("at the venue's smallest size: this position ties "
                       "up 1,080.00 — past the 400.00 a single position "
                       "may hold (20% of the 2,000.00 bot pool)")})

    def test_unlevered_it_opens_when_every_gate_passes_at_one(self):
        H.limit(max_single_position_pct=100, max_pledged_pct=100)
        out = H.run(_on("forex_under_min", leverage=False))
        row = self.assertOpened(out, qty=1000.0, leverage=1)
        self.assertEqual(row.metadata["leverage"], 1)
        floor = _floor_of(row)
        self.assertEqual(floor["leverage"], 1)
        self.assertIn("etoro_leverage_live is OFF", floor["leverage_why"])

    def test_max_bot_leverage_bounds_the_chooser(self):
        H.limit(max_bot_leverage=5)
        out = H.run(_on("forex_under_min"))
        row = self.assertOpened(out, qty=1000.0, leverage=5)
        self.assertIn("capped at 5x by MAX BOT LEVERAGE",
                      _floor_of(row)["leverage_why"])

    def test_the_pick_meets_max_single_position_again(self):
        """The proposal counts the most the chooser could pick (30x:
        36.00); the pick is 20x, 54.00, past 2.5% of the pool: refused at
        the multiplier sent, and the words name it."""
        H.limit(max_single_position_pct=2.5)
        out = H.run(_on("forex_under_min"))
        self.assertEqual(out.cand.qty_default, 1000.0)
        self.assertNothingSent(out)
        self.assertEqual(H.skip_of(out), {
            "code": "gate_blocked",
            "detail": ("at the venue's smallest size: at 20x: this "
                       "position ties up 54.00 — past the 50.00 a single "
                       "position may hold (2.5% of the 2,000.00 bot "
                       "pool)")})


class ThePoolsCurrencyTests(_On):
    """The floor's risk is computed as every existing risk check computes
    it: units x the stop distance x the value per unit, against the pool's
    figure. The label is not read."""

    def test_a_eur_and_a_usd_label_get_the_same_floor(self):
        usd = H.run(_on("forex_under_min", tag="usd", currency="USD"))
        eur = H.run(_on("forex_under_min", tag="eur", currency="EUR"))
        for out in (usd, eur):
            self.assertEqual(out.cand.qty_default, 1000.0)
            self.assertAlmostEqual(out.cand.risk_dollars_default, 16.2)
            self.assertEqual(out.cand.venue_floor["record"]["risk_pct"],
                             0.81)
        self.assertEqual(usd.cand.venue_floor["record"],
                         eur.cand.venue_floor["record"])
        self.assertOpened(usd, qty=1000.0, leverage=20)

    def test_a_label_that_is_not_the_accounts_is_still_refused_at_the_cash_gate(
            self):
        """A DEFECT OF MAIN, recorded and not fixed here: the account sync
        writes the account's figure into a follower's pool and never its
        label, and the cash gate refuses every eToro order of a pool
        labelled in another currency than the account. A floor entry meets
        the same refusal."""
        eur = H.run(_on("forex_under_min", tag="eur", currency="EUR"))
        self.assertNothingSent(eur)
        skip = H.skip_of(eur)
        self.assertEqual(skip["code"], "leverage_refused")
        self.assertTrue(skip["detail"].startswith(
            "at the venue's smallest size: at 20x: pool in EUR against "
            "cash read in USD — nothing here converts; refused"), skip)


class TheStageAndProofTests(_On):

    def test_a_probation_size_is_raised_and_recorded(self):
        """A live_small rule enters at a quarter: 77 units, 100 on the
        step. Raised to the smallest size like any other, inside the
        ceiling, and the row says which factor had cut it."""
        out = H.run(_on("forex_probation"))
        row = self.assertOpened(out, qty=1000.0, leverage=20)
        floor = _floor_of(row)
        self.assertEqual(floor["replaced_qty"], 100.0)
        self.assertEqual(floor["stage_factor"], 0.25)
        self.assertEqual(floor["proof_cut"], 1.0)
        self.assertEqual(floor["risk_pct"], 0.81)
        self.assertEqual(floor["normal_risk_pct"], 0.25)
        self.assertEqual(floor["replaced_risk_pct"], 0.081)
        self.assertEqual(row.metadata["promotion_stage"], "live_small")

    def test_an_unproven_rules_cut_is_recorded(self):
        """SIZE BY PROOF on (the suite runs with it off): an unproven
        live_full rule is cut to a quarter by the proving ground, the
        floor raises it, and the row keeps the proof's cut."""
        from backtester.proving import proof
        world = _on("forex_under_min")
        verdict = {"tier": proof.REDUCED, "multiplier": 0.25,
                   "words": "no verdict yet", "record": {}}

        def prepare(bot):
            bot._proof_gate = lambda symbol, decision: dict(verdict)
        with mock.patch.object(proof, "GATE", True):
            out = H.run(world, prepare=prepare)
        row = self.assertOpened(out, qty=1000.0, leverage=20)
        floor = _floor_of(row)
        self.assertEqual(floor["replaced_qty"], 100.0)
        self.assertEqual(floor["proof_cut"], 0.25)
        self.assertEqual(floor["stage_factor"], 0.25)


class TheQuietsTests(_On):

    def test_the_24_hour_quiet_is_untouched(self):
        """A symbol whose fractional size eToro refused is quiet for 24
        hours at the top of the proposal, before any size exists: main's
        words, and the venue's row is not even read."""
        from django.utils import timezone
        details = {}
        for state, tag in ((False, "off"), (True, "on")):
            world = H.arm("forex_under_min", tag)
            H.switch(H.SWITCH, state)
            H.switch(H.LEVERAGE, True)
            cfg = world["cfg"]
            cfg.extras = dict(cfg.extras, entry_fraction_refused={
                "EURUSD": {"words": "errorCode 720",
                           "at": timezone.now().isoformat()}})
            cfg.save(update_fields=["extras"])
            out = H.run(world)
            self.assertIsNone(out.cand)
            self.assertEqual(out.venue.asked, [])
            skip = H.skip_of(out)
            self.assertEqual(skip["code"], "venue_min_size")
            details[state] = _scrubbed(skip["detail"])
        self.assertEqual(details[True], details[False])
        self.assertIn("quiet for 24h", details[True])

    def test_a_floored_order_etoro_refuses_is_quiet_for_12_hours(self):
        """One order per 12 hours, not one per pass: the refusal is noted
        (the existing note), and while it is fresh nothing is raised."""
        world = _on("forex_under_min")
        refused = {"orderId": "o-1", "status": "REJECTED",
                   "executedQty": "0", "refusal": "errorCode 720"}
        out = H.run(world, the_venue=H.venue(world["price"], world["table"],
                                             fill=refused))
        self.assertEqual(len(H.orders(out)), 1)
        self.assertEqual(H.trade_rows(out), [])
        self.assertEqual(H.skip_of(out)["code"], "order_rejected")
        note = out.cfg.extras["leverage_refusals"]["EURUSD"]
        self.assertEqual(note["leverage"], 20)
        # the next pass: not raised, nothing sent, and the words say why
        again = H.run(world)
        self.assertEqual(again.cand.qty_default, 300.0)
        self.assertEqual(H.orders(again), [])
        skip = H.skip_of(again)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertTrue(skip["detail"].startswith(
            "eToro refused EURUSD 0.0h ago, so nothing is raised to the "
            "venue's smallest size for 12h: "), skip)

    def test_an_unlevered_floored_order_refused_is_noted_too(self):
        """At 1x main keeps no note of a refused order; a floored one is
        noted all the same, so it is not sent again on the next pass."""
        H.limit(max_single_position_pct=100, max_pledged_pct=100)
        world = _on("forex_under_min", leverage=False)
        out = H.run(world, the_venue=H.venue(
            world["price"], world["table"],
            raises=RuntimeError("eToro refused (400): not now")))
        self.assertEqual(len(H.orders(out)), 1)
        self.assertEqual(H.skip_of(out)["code"], "order_error")
        self.assertEqual(
            out.cfg.extras["leverage_refusals"]["EURUSD"]["leverage"], 1)
        again = H.run(world)
        self.assertEqual(H.orders(again), [])
        self.assertEqual(again.cand.qty_default, 300.0)

    def test_an_order_main_would_send_keeps_mains_memory(self):
        """Not floored, refused at 1x: no note, as on main."""
        world = _on("crypto_clear")
        out = H.run(world, the_venue=H.venue(
            world["price"], world["table"],
            fill={"orderId": "o-1", "status": "REJECTED",
                  "executedQty": "0"}))
        self.assertEqual(H.skip_of(out)["code"], "order_rejected")
        self.assertNotIn("leverage_refusals", out.cfg.extras)


class TheSendChecksTests(_On):
    """Nothing is raised at the send; a floored candidate is checked again
    on the client the order goes through."""

    def test_the_desks_cut_wins(self):
        """The capital desk may only shrink: half of the smallest size is
        under the minimum, and it is refused, never raised again."""
        out = H.run(_on("forex_under_min"), size_mult=0.5)
        self.assertEqual(out.cand.qty_default, 1000.0)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertTrue(skip["detail"].startswith(
            "raised to the venue's smallest size at the proposal and under "
            "it at the order: sized 500 units"), skip)

    def test_the_switch_turned_off_before_the_order_sends_nothing(self):
        out = H.run(_on("forex_under_min"),
                    between=lambda: H.switch(H.SWITCH, False))
        self.assertEqual(out.cand.qty_default, 1000.0)
        self.assertNothingSent(out)
        self.assertEqual(H.skip_of(out), {
            "code": "venue_min_size",
            "detail": ("bots_venue_floor_live was turned off after this "
                       "entry was raised to the venue's smallest size — "
                       "nothing sent")})

    def test_the_ceiling_lowered_before_the_order_sends_nothing(self):
        out = H.run(_on("forex_under_min"),
                    between=lambda: H.ceiling(0.5))
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertTrue(skip["detail"].startswith(
            "the venue's smallest size would risk 0.81% of the pool, above "
            "your 0.5% ceiling (MAX BOT FLOOR RISK)"), skip)

    def test_a_minimum_unread_at_the_order_sends_nothing(self):
        world = _on("stock_under_one_share")
        out = H.run(world,
                    between=lambda: world["table"].pop("AAPL", None))
        self.assertEqual(out.cand.qty_default, 1.0)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertTrue(skip["detail"].startswith(
            "the venue's smallest size was read at the proposal and is "
            "unread at the order — nothing sent"), skip)

    def test_another_venue_at_the_order_sends_nothing(self):
        """The route moved between the proposal and the order (a box
        unticked on /brokers/): the size was raised to eToro's minimum,
        nobody else's, so a venue that states a minimum of its own, even
        the same one, is sent nothing."""
        class OtherVenue(mock.MagicMock):
            def min_tradable(self, symbol):
                return 1000.0
        other = OtherVenue()
        other.ticker = mock.MagicMock(return_value={"lastPrice": "1.0800"})
        other.get_positions = mock.MagicMock(return_value=[])
        world = _on("forex_under_min")
        the_venue = H.venue(world["price"], world["table"])
        from bot_program.asset_engine.base import make_bot
        bot = make_bot(world["cfg"])
        with mock.patch(H.ROUTER, return_value=the_venue):
            cand = bot.propose_entry("EURUSD")
        self.assertEqual(cand.qty_default, 1000.0)
        with mock.patch(H.ROUTER, return_value=other), \
                mock.patch("time.sleep"):
            self.assertIsNone(bot.execute_entry(cand))
        other.market_order.assert_not_called()
        the_venue.market_order.assert_not_called()
        world["cfg"].refresh_from_db()
        skip = world["cfg"].extras["skips"]["EURUSD"]
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertEqual(
            skip["detail"],
            "raised to eToro's smallest size at the proposal, and the "
            "order would go to another venue now — nothing sent")

    def test_a_minimum_that_moved_before_the_order_sends_nothing(self):
        world = _on("forex_under_min")

        def moved():
            world["table"]["EURUSD"] = dict(world["table"]["EURUSD"],
                                            minPositionExposure=500)
        out = H.run(world, between=moved)
        self.assertNothingSent(out)
        skip = H.skip_of(out)
        self.assertEqual(skip["code"], "venue_min_size")
        self.assertTrue(skip["detail"].startswith(
            "the venue's smallest size moved between the proposal and the "
            "order (1000 units then, 500 now) — nothing sent"), skip)


class TheRecordAndWordsTests(_On):
    """A floored entry says so: on the row, in the audit log and in the
    fill message."""

    def test_the_row_carries_the_whole_record(self):
        out = H.run(_on("forex_under_min"))
        row = self.assertOpened(out, qty=1000.0, leverage=20)
        floor = dict(_floor_of(row))
        why = floor.pop("leverage_why")
        self.assertTrue(why.startswith("auto: 20x"), why)
        self.assertAlmostEqual(floor.pop("venue_min_units"), 925.925926,
                               places=5)
        self.assertEqual(floor, {
            "floored": True, "replaced_qty": 300.0, "qty": 1000.0,
            "risk_pct": 0.81, "normal_risk_pct": 0.25,
            "replaced_risk_pct": 0.243, "ceiling_pct": 2.0,
            "notional_x_pool": 0.54, "stage_factor": 1.0, "proof_cut": 1.0,
            "leverage": 20, "leverage_by": "chooser"})
        # the sizer's own numbers stay the bot's normal budget
        self.assertEqual(row.metadata["risk_fraction"], 0.0025)
        self.assertEqual(row.metadata["risk_dollars"], 5.0)

    def test_the_audit_row_says_it_was_floored(self):
        from bot_program.audit_models import AuditLogEntry
        out = H.run(_on("forex_under_min"))
        row = self.assertOpened(out, qty=1000.0, leverage=20)
        entry = AuditLogEntry.objects.filter(
            user=out.cfg.user, kind="trade_open").get()
        self.assertEqual(entry.data["trade_id"], row.id)
        self.assertEqual(entry.data["qty"], "1000.0")
        self.assertEqual(entry.data["venue_floor"], _floor_of(row))

    def test_the_fill_message_says_it_in_plain_words(self):
        from bot_program.notifications import fill_open_message
        out = H.run(_on("forex_under_min"))
        row = self.assertOpened(out, qty=1000.0, leverage=20)
        line = ("Smallest size: raised to 1,000 units, the least eToro "
                "takes, from the 300 units the risk budget sized · 0.81% "
                "of the pool at risk, against this bot's usual 0.25% · 20x "
                "chosen automatically")
        self.assertEqual(out.note.call_args.kwargs["floor"], line)
        message = fill_open_message(
            asset_class="forex", symbol="EURUSD", side="BUY", qty=row.qty,
            entry_price=row.entry_price, rule_name=row.rule_name,
            trade=row, **out.bot._fill_words(row))
        self.assertIn(line, message["lines"])
        self.assertEqual(sum("Smallest size" in x
                             for x in message["lines"]), 1)
        text = " ".join([message["title"], message["summary"],
                         *message["lines"]])
        for bad in FRENCH + ("None", "Decimal(", "{", "}"):
            self.assertNotIn(bad, f" {text} ", bad)

    def test_a_size_that_rounded_to_zero_says_so(self):
        out = H.run(_on("stock_under_one_share"))
        self.assertOpened(out, qty=1.0, leverage=5)
        self.assertEqual(
            out.note.call_args.kwargs["floor"],
            "Smallest size: raised to 1 share, the least eToro takes; the "
            "risk budget sized less than one · 0.50% of the pool at risk, "
            "against this bot's usual 0.25% · 5x chosen automatically")

    def test_a_typed_multiplier_is_not_called_chosen(self):
        typed = {"session_filter_disabled": True, "leverage": 10}
        out = H.run(_on("forex_under_min", extras=typed))
        self.assertOpened(out, qty=1000.0, leverage=10)
        self.assertEqual(
            out.note.call_args.kwargs["floor"],
            "Smallest size: raised to 1,000 units, the least eToro takes, "
            "from the 300 units the risk budget sized · 0.81% of the pool "
            "at risk, against this bot's usual 0.25%")

    def test_an_entry_that_was_not_floored_says_nothing(self):
        out = H.run(_on("stock_clear"))
        self.assertIsNotNone(out.res)
        self.assertNotIn("floor", out.note.call_args.kwargs)
        row = H.trade_rows(out)[0]
        self.assertNotIn("venue_floor", row.metadata)
        self.assertEqual(out.bot._fill_words(row),
                         {"attack": "", "stop_moved": "", "slippage": ""})

    def test_the_notifier_carries_the_line_to_the_bell_and_telegram(self):
        """notify_bot_fill_open with the engine's own floor line: one
        message, the line among its lines, for Telegram and the bell."""
        from bot_program import notifications
        out = H.run(_on("commodity_under_min"))
        row = self.assertOpened(out, qty=0.5, leverage=10)
        words = out.bot._fill_words(row)
        self.assertTrue(words["floor"].startswith(
            "Smallest size: raised to 0.5 units, the least eToro takes, "
            "from the 0.0833 units the risk budget sized · 1.5% of the "
            "pool at risk, against this bot's usual 0.25% · 10x chosen "
            "automatically"), words)
        with mock.patch.object(notifications, "dispatch_notification",
                               return_value=True) as send:
            notifications.notify_bot_fill_open(
                out.cfg.user, asset_class="commodity", symbol="XAUUSD",
                side="BUY", qty=row.qty, entry_price=row.entry_price,
                rule_name=row.rule_name, trade=row, trade_id=row.id,
                **words)
        sent = send.call_args.kwargs
        self.assertIn(words["floor"], sent["telegram"]["lines"])
        self.assertIn(words["floor"], sent["row_data"]["items"])


class TheUnchangedLanesTests(_On):
    """A paper config and a live config's paper-stage entry: unchanged,
    with the switch ON, to the stored key and the request."""

    def test_a_paper_config_is_mains(self):
        """The paper venue has no minimum: 300 units are booked as a
        simulated trade, as on main."""
        snap = H.snapshot(H.run(_on("forex_paper_config")))
        self.assertEqual(snap, _golden()["forex_paper_config"])

    def test_a_live_configs_paper_stage_entry_is_mains(self):
        """A rule at the paper stage books a simulated row on the live
        config, at the risk-sized 300 units: no order, no floor, and the
        venue's row is not read."""
        snap = H.snapshot(H.run(_on("forex_paper_stage")))
        self.assertEqual(snap, _golden()["forex_paper_stage"])
        self.assertEqual(snap["rows_asked"], [])

    def test_the_hand_tickets_config_is_never_floored(self):
        """A config named "manual" is the TAKE TRADE lane's own: the hand
        ticket has its own floor, and the bots' never reads it."""
        from bot_program.asset_engine.base import make_bot
        from bot_program.manual_trade import MANUAL_CONFIG_NAME
        world = _on("forex_under_min")
        cfg = world["cfg"]
        cfg.name = MANUAL_CONFIG_NAME
        cfg.save(update_fields=["name"])
        the_venue = H.venue(world["price"], world["table"])
        verdict = make_bot(cfg)._venue_floor(
            the_venue, "EURUSD", stage={"force_paper": False}, qty=300.0,
            price=1.08, sl=1.0638, sizing={"risk_fraction": 0.0025},
            fractional=None)
        self.assertEqual(verdict, {"state": "off"})
        self.assertEqual(the_venue.asked, [])


def _scrubbed(text):
    return H.scrub(text)
