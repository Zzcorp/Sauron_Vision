"""The manual ticket is never refused for rounding to zero (2026-11-06).

The operator: "j'ai toujours en stock cette empechement: Sized to zero — the
risk budget does not cover one tradeable unit at this stop distance.
debride la machine quand il s'agit du manuel". The manual lane follows the
whole account, and on a small account the 0.25% risk budget bought less
than one whole share of most stocks at a sane stop: the preview refused the
ticket BEFORE the dialog opened, and the operator never got to choose.

The manual ticket now starts, when the risk-based size rounds to zero, from
the SMALLEST SIZE the venue takes (the venue's own minimum on a live ticket
when it is known, else one step of this platform's granularity), and:

- proposes it with a note in plain words when its risk at the stop is
  within the 7% hard cap of the pool, so the dialog opens and the operator
  decides (with his PIN on a live ticket);
- refuses only when even that smallest size is past the hard cap, with
  words naming the size, the risk and the cap;
- sends at execute exactly the size the preview proposed, or the size the
  operator typed, never another one;
- keeps every other gate (the notional cap, the pool, MAX SINGLE POSITION,
  the PIN, the 7% cap at the size actually sent);
- floors nothing that is not a rounding (no rate, a stop-floor skip);
- leaves the bots alone: they still refuse a size of zero.

And, after the review (2026-11-06):

- the send goes out at the size the ticket SHOWED: the dialog sends back
  the size it showed when the operator left it alone (shown_qty) and
  whether it was raised above the budget (shown_raised); an automatic size
  the send raises — to the smallest size or to the broker's minimum — and
  the ticket did not show refuses, nothing sent;
- the dialog holds the broker's minimum at a moved stop, as the send does,
  and the money it prints before the PIN follows the stop;
- the venue's minimum rounded up to this platform's step is not called the
  venue's own; the ledger, the position page and the confirmation say
  which smallest size it was, at the stop actually sent;
- the dialog refuses a size past MAX SINGLE POSITION before the PIN.

Every broker here is a fake: no network.

Run with:  python manage.py test tests.test_manual_smallest_size
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.serializers.json import DjangoJSONEncoder
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_take_trade_live import (ROUTER, _arm_live, _components_on,
                                        _fake_live_client, _filled_response,
                                        _quote, _signal)

FLOOR = "bot_program.manual_trade._venue_min_qty"
#: the venue's own floor, read through the real _venue_min_qty
VENUE_FLOOR = "bot_program.asset_engine.base.AssetBot._venue_size_floor"
NODE = shutil.which("node")
#: an invented stock, priced so that one whole share is far more than the
#: 0.25% budget of a small pool buys
STOCK = "FLOORCO"


def _sent_qty(fake):
    call = fake.market_order.call_args
    return float(call.kwargs.get("quantity", call.args[2]))


# ── 1. paper: one step of the platform's granularity ─────────────────────────

class ThePaperTicketTests(TestCase):
    """A PAPER forex lane on a 50 pool: 0.25% is 0.125 of risk, and a 0.3%
    EURUSD stop (0.0033 a unit) buys 38 units, which the 100-unit forex
    step rounds to zero. One step, 100 units, risks 0.33: 0.66% of the
    pool, inside the 7% cap (3.50)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("floor_p",
                                                        password="x")

    def setUp(self):
        from bot_program.manual_trade import manual_config_for
        self.fx = _quote("EURUSD", 1.10, asset_class="forex")
        self.cfg = manual_config_for(self.user, "forex")
        self.cfg.capital = Decimal("50")
        self.cfg.save(update_fields=["capital"])

    def _sig(self):
        return _signal(self.fx, entry=1.10, stop=1.0967, target=1.1066)

    def test_the_signal_ticket_proposes_one_step_with_the_note(self):
        from bot_program.manual_trade import preview_take_trade
        p = preview_take_trade(self.user, self._sig())
        self.assertNotIn("error", p, p)
        self.assertEqual(p["qty"], 100.0)
        floor = p["smallest_size"]
        self.assertEqual(floor["qty"], 100.0)
        self.assertEqual(floor["source"], "step")
        self.assertAlmostEqual(floor["risk"], 0.33, places=6)
        self.assertEqual(floor["note"], (
            "Raised to the smallest size the paper venue takes: 100 units. "
            "At this stop it risks 0.33 USD (0.66% of the pool), more than "
            "the 0.25% a ticket risks by default."))
        # the rest of the ticket is the raised size's
        self.assertAlmostEqual(p["notional"], 110.0, places=2)
        self.assertTrue(p["sufficient"])
        self.assertEqual(p["max_qty"], 100.0)
        # the budget stays the budget: the size the stop buys at 0.25%
        self.assertAlmostEqual(p["risk_dollars"], 0.125, places=6)

    def test_the_signal_ticket_books_exactly_the_proposed_size(self):
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        out = execute_take_trade(self.user, self._sig())
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out["qty"], 100.0)
        self.assertEqual(out["sized_by"], "smallest_size")
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertEqual(float(trade.qty), 100.0)
        self.assertEqual(trade.metadata["size_source"], "smallest_size")
        # the adverse paper fill, not the mark: R is what was risked
        fill = float(trade.entry_price)
        self.assertGreater(fill, 1.10)
        self.assertAlmostEqual(trade.metadata["risk_dollars"],
                               round(100 * (fill - 1.0967), 6), places=6)
        rec = trade.metadata["smallest_size"]
        self.assertEqual(rec["qty"], 100.0)
        self.assertEqual(rec["source"], "step")
        self.assertIn("Raised to the smallest size the paper venue takes",
                      rec["note"])

    def test_the_instrument_ticket_proposes_and_books_it_too(self):
        from bot_program.manual_trade import (execute_asset_trade,
                                              preview_asset_trade)
        from bot_program.models import AssetBotTrade
        p = preview_asset_trade(self.user, self.fx, "BUY")
        self.assertNotIn("error", p, p)
        self.assertEqual(p["qty"], 100.0)
        self.assertIn("Raised to the smallest size the paper venue takes: "
                      "100 units.", p["smallest_size"]["note"])
        out = execute_asset_trade(self.user, self.fx, "BUY")
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out["sized_by"], "smallest_size")
        self.assertEqual(float(AssetBotTrade.objects.get(
            pk=out["trade_id"]).qty), 100.0)

    def test_a_smallest_size_past_the_hard_cap_is_refused_in_words(self):
        """A 4 pool: the cap is 0.28, and one step risks 0.33."""
        from bot_program.manual_trade import (execute_take_trade,
                                              preview_take_trade)
        from bot_program.models import AssetBotTrade
        self.cfg.capital = Decimal("4")
        self.cfg.save(update_fields=["capital"])
        p = preview_take_trade(self.user, self._sig())
        self.assertEqual(p.get("error"), (
            "Even the smallest size the paper venue takes, 100 units, risks "
            "0.33 USD at this stop — past the hard cap of 0.28 USD (7% of "
            "the 4.00 USD pool); the 0.25% risk budget sizes this ticket to "
            "zero. Widen the pool or tighten the stop. Nothing was booked"))
        out = execute_take_trade(self.user, self._sig())
        self.assertEqual(out.get("error"), p["error"])
        self.assertEqual(AssetBotTrade.objects.count(), 0)

    def test_no_rate_is_not_a_rounding_and_is_still_refused(self):
        """ForexBot's 0.0 value per unit is "no fresh rate": it sizes to
        zero rather than to a wrong number, and no smallest size is
        proposed against a rate nobody has."""
        from bot_program.manual_trade import preview_take_trade
        with patch("bot_program.asset_engine.forex_bot.ForexBot"
                   "._value_per_unit", return_value=0.0):
            p = preview_take_trade(self.user, self._sig())
        self.assertEqual(p.get("error"),
                         "Sized to zero — the risk budget does not cover one "
                         "tradeable unit at this stop distance")

    def test_no_rate_at_the_send_refuses_the_smallest_size_too(self):
        """The rate went stale between the preview and the send: the
        smallest size is not sent at a value per unit of zero."""
        from bot_program.manual_trade import _judge_ticket, preview_take_trade
        p = preview_take_trade(self.user, self._sig())
        self.assertEqual(p["smallest_size"]["qty"], 100.0)
        with patch("bot_program.asset_engine.forex_bot.ForexBot"
                   "._value_per_unit", return_value=0.0):
            out = _judge_ticket(self.user, self.cfg, self.fx, "BUY", "forex",
                                p, live=False, available=p["available"])
        self.assertEqual(out.get("error"),
                         "Sized to zero at the adjusted fill price")

    def test_a_stop_floor_skip_is_not_a_rounding_and_is_still_refused(self):
        """extras['on_stop_floor'] = 'skip' refuses a stop inside the floor
        the risk budget and the notional cap imply: a policy, kept."""
        from bot_program.manual_trade import preview_take_trade
        self.cfg.extras = {"on_stop_floor": "skip"}
        self.cfg.save(update_fields=["extras"])
        p = preview_take_trade(self.user, _signal(
            self.fx, entry=1.10, stop=1.09945, target=1.1066))
        self.assertEqual(p.get("error"),
                         "Sized to zero — the risk budget does not cover one "
                         "tradeable unit at this stop distance")


# ── 2. live: the venue's minimum, else one step ──────────────────────────────

class TheLiveTicketTests(TestCase):
    """A LIVE stock lane on a 400 pool, on a fake broker: one whole share of
    a 150 stock at a 2% stop risks 3.00, and 0.25% of 400 is 1.00. The
    lane's own knobs carry a whole share (notional 1.0, single 100%); the
    7% cap is 28.00."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("floor_l",
                                                        password="x")

    def setUp(self):
        cache.clear()
        self.inst = _quote(STOCK, 150, asset_class="stock")
        _components_on()
        self.cfg = _arm_live(self.user, "stock")
        self.cfg.capital = Decimal("400")
        self.cfg.extras = {"max_notional_fraction": 1.0,
                           "max_single_position_pct": 100.0}
        self.cfg.save(update_fields=["capital", "extras"])

    def _fake(self, qty="1"):
        fake = _fake_live_client(_filled_response(
            symbol=STOCK, executedQty=qty, avgPrice="150"))
        fake.ticker.return_value = {"lastPrice": "150"}
        return fake

    def _sig(self, stop=147, target=156):
        return _signal(self.inst, entry=150, stop=stop, target=target)

    def test_a_whole_share_inside_the_cap_is_proposed_with_the_note(self):
        from bot_program.manual_trade import preview_take_trade
        with patch(ROUTER, return_value=self._fake()), \
                patch(FLOOR, return_value=(None, "unstated")):
            p = preview_take_trade(self.user, self._sig())
        self.assertNotIn("error", p, p)
        self.assertEqual(p["venue"], "live")
        self.assertTrue(p["requires_pin"])
        self.assertEqual(p["qty"], 1.0)
        floor = p["smallest_size"]
        self.assertEqual((floor["qty"], floor["source"]), (1.0, "step"))
        self.assertAlmostEqual(floor["risk"], 3.0, places=6)
        # one step of this platform's granularity is not the venue's
        # minimum, and is not called one
        self.assertIn("Raised to the smallest size this platform sends to ",
                      floor["note"])
        self.assertIn("own minimum was not read): 1 unit. At this stop it "
                      "risks 3.00 USD (0.75% of the pool), more than the "
                      "0.25% a ticket risks by default.", floor["note"])
        self.assertNotIn(" takes: ", floor["note"])
        self.assertEqual(p["max_qty"], 2.0)

    def test_execute_sends_the_proposed_share_and_records_it(self):
        from bot_program.manual_trade import execute_take_trade
        from bot_program.models import AssetBotTrade
        fake = self._fake()
        with patch(ROUTER, return_value=fake), \
                patch(FLOOR, return_value=(None, "unstated")):
            out = execute_take_trade(self.user, self._sig(), pin_ok=True)
        self.assertTrue(out.get("ok"), out)
        fake.market_order.assert_called_once()
        self.assertEqual(_sent_qty(fake), 1.0)
        self.assertEqual(out["sized_by"], "smallest_size")
        self.assertAlmostEqual(out["risk_dollars"], 3.0, places=6)
        trade = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertEqual(trade.metadata["size_source"], "smallest_size")
        self.assertEqual(trade.metadata["smallest_size"]["qty"], 1.0)

    def test_a_known_venue_minimum_is_where_it_starts(self):
        from bot_program.manual_trade import (execute_take_trade,
                                              preview_take_trade)
        with patch(ROUTER, return_value=self._fake()), \
                patch(FLOOR, return_value=(2.0, "")):
            p = preview_take_trade(self.user, self._sig())
        self.assertNotIn("error", p, p)
        self.assertEqual(p["qty"], 2.0)
        self.assertEqual(p["smallest_size"]["source"], "venue_minimum")
        self.assertRegex(p["smallest_size"]["note"],
                         r"^Raised to the smallest size \S+ takes: 2 units\. "
                         r"At this stop it risks 6\.00 USD \(1\.50% of the "
                         r"pool\), more than the 0\.25% a ticket risks by "
                         r"default\.$")
        self.assertEqual(p["venue_min_qty"], 2.0)
        self.assertEqual(p["venue_min_note"], "")
        fake = self._fake(qty="2")
        with patch(ROUTER, return_value=fake), \
                patch(FLOOR, return_value=(2.0, "")):
            out = execute_take_trade(self.user, self._sig(), pin_ok=True)
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(_sent_qty(fake), 2.0)
        self.assertEqual(out["sized_by"], "smallest_size")

    def test_the_instrument_ticket_sends_the_proposed_share(self):
        from bot_program.manual_trade import (execute_asset_trade,
                                              preview_asset_trade)
        with patch(ROUTER, return_value=self._fake()), \
                patch(FLOOR, return_value=(None, "unstated")):
            p = preview_asset_trade(self.user, self.inst, "BUY")
        self.assertNotIn("error", p, p)
        self.assertEqual(p["qty"], 1.0)
        self.assertIn("1 unit. At this stop it risks 2.25 USD",
                      p["smallest_size"]["note"])
        fake = self._fake()
        with patch(ROUTER, return_value=fake), \
                patch(FLOOR, return_value=(None, "unstated")):
            out = execute_asset_trade(self.user, self.inst, "BUY",
                                      pin_ok=True)
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(_sent_qty(fake), 1.0)
        self.assertEqual(out["sized_by"], "smallest_size")

    def test_a_share_past_the_hard_cap_is_refused_and_nothing_is_sent(self):
        """A 200 pool (cap 14.00) and a 10% stop: one share risks 15.00."""
        from bot_program.manual_trade import (execute_take_trade,
                                              preview_take_trade)
        self.cfg.capital = Decimal("200")
        self.cfg.save(update_fields=["capital"])
        sig = self._sig(stop=135, target=200)
        with patch(ROUTER, return_value=self._fake()), \
                patch(FLOOR, return_value=(None, "unstated")):
            p = preview_take_trade(self.user, sig)
        err = p.get("error", "")
        self.assertIn("1 unit, risks 15.00 USD at this stop — past the hard "
                      "cap of 14.00 USD (7% of the 200.00 USD pool)", err)
        self.assertTrue(err.endswith("Nothing was sent"), err)
        fake = self._fake()
        with patch(ROUTER, return_value=fake), \
                patch(FLOOR, return_value=(None, "unstated")):
            out = execute_take_trade(self.user, sig, pin_ok=True)
        self.assertEqual(out.get("error"), err)
        fake.market_order.assert_not_called()

    def test_a_typed_size_is_sent_as_typed(self):
        from bot_program.manual_trade import execute_take_trade
        fake = self._fake(qty="2")
        with patch(ROUTER, return_value=fake), \
                patch(FLOOR, return_value=(None, "unstated")):
            out = execute_take_trade(self.user, self._sig(), qty="2",
                                     pin_ok=True)
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(_sent_qty(fake), 2.0)
        self.assertEqual(out["sized_by"], "operator")

    def test_a_moved_stop_keeps_the_smallest_size(self):
        """A 200 pool (cap 14.00), the target far: the operator moves the
        stop to 140 and leaves the size alone. 0.25% (0.50) still buys no
        share there, so the share is sent, risking 10.00 at that stop."""
        from bot_program.manual_trade import execute_take_trade
        self.cfg.capital = Decimal("200")
        self.cfg.save(update_fields=["capital"])
        fake = self._fake()
        with patch(ROUTER, return_value=fake), \
                patch(FLOOR, return_value=(None, "unstated")):
            out = execute_take_trade(self.user, self._sig(target=200),
                                     stop=140, pin_ok=True)
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(_sent_qty(fake), 1.0)
        self.assertEqual(out["sized_by"], "smallest_size")
        self.assertAlmostEqual(out["risk_dollars"], 10.0, places=6)

    def test_a_moved_stop_that_takes_the_share_past_the_cap_is_refused(self):
        """The same ticket with the stop moved to 135: one share risks
        15.00, past the 14.00 cap — refused in the smallest size's words."""
        from bot_program.manual_trade import execute_take_trade
        self.cfg.capital = Decimal("200")
        self.cfg.save(update_fields=["capital"])
        fake = self._fake()
        with patch(ROUTER, return_value=fake), \
                patch(FLOOR, return_value=(None, "unstated")):
            out = execute_take_trade(self.user, self._sig(target=200),
                                     stop=135, pin_ok=True)
        self.assertIn("1 unit, risks 15.00 USD at this stop — past the hard "
                      "cap of 14.00 USD (7% of the 200.00 USD pool)",
                      out.get("error", ""))
        fake.market_order.assert_not_called()

    def test_every_other_gate_still_binds_on_the_raised_size(self):
        """Without the lane's own knobs the stock notional cap is 20% of the
        pool (80.00): the dialog opens on the share, its size control stops
        at zero, and the send refuses it — nothing is sent."""
        from bot_program.manual_trade import (execute_take_trade,
                                              preview_take_trade)
        self.cfg.extras = {}
        self.cfg.save(update_fields=["extras"])
        with patch(ROUTER, return_value=self._fake()), \
                patch(FLOOR, return_value=(None, "unstated")):
            p = preview_take_trade(self.user, self._sig())
        self.assertNotIn("error", p, p)
        self.assertEqual(p["qty"], 1.0)
        self.assertEqual(p["max_qty"], 0.0)
        fake = self._fake()
        with patch(ROUTER, return_value=fake), \
                patch(FLOOR, return_value=(None, "unstated")):
            out = execute_take_trade(self.user, self._sig(), pin_ok=True)
        self.assertIn("of notional — past the $80.00 this class allows",
                      out.get("error", ""))
        fake.market_order.assert_not_called()

    def test_the_pin_is_still_demanded(self):
        from bot_program.manual_trade import execute_take_trade
        fake = self._fake()
        with patch(ROUTER, return_value=fake), \
                patch(FLOOR, return_value=(None, "unstated")):
            out = execute_take_trade(self.user, self._sig())
        self.assertIn("PIN", out.get("error", ""))
        fake.market_order.assert_not_called()


# ── 3. the bots are not touched ──────────────────────────────────────────────

class TheBotsStillRefuseTests(TestCase):
    """A LIVE StockBot on a 100 pool: 0.25% is 0.25 of risk, under one
    whole share of AAPL at 100 behind a 1.5% stop. Nobody is there to
    agree to a larger size, so the bot skips it as it always has."""

    def setUp(self):
        from tests.test_entry_quote import (_book, _instrument, _live_cfg,
                                            _signal as _bot_signal, _user)
        self.user = _user("floor_bot")
        self.cfg = _live_cfg(self.user, name="FLOORBOT")
        self.cfg.capital = Decimal("100")
        self.cfg.save(update_fields=["capital"])
        _bot_signal(_instrument(), rule="floor_rule")
        _book(self.user)

    def test_a_bot_still_skips_a_size_of_zero(self):
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.stock_bot import StockBot
        from tests.test_entry_quote import ROUTER as BOT_ROUTER
        from tests.test_entry_quote import _mock_client
        client = _mock_client("100.00")
        client.ticker.return_value = {"lastPrice": "100.00", "bid": "99.99",
                                      "ask": "100.01", "symbol": "AAPL"}
        with patch(BOT_ROUTER, return_value=client):
            cand = StockBot(self.cfg).propose_entry("AAPL")
        self.assertIsNone(cand)
        self.cfg.refresh_from_db()
        note = skips.last_by_symbol(self.cfg)["AAPL"]
        self.assertEqual(note["code"], skips.SIZED_TO_ZERO)
        client.market_order.assert_not_called()


# ── 4. what the operator reads ───────────────────────────────────────────────

class TheDialogSaysItTests(SimpleTestCase):
    """The dialog shows the raise and its money before the PIN, keeps the
    smallest size when the stop moves (as the send does), and the
    confirmation names the size it sent."""

    def _src(self):
        from pathlib import Path

        from django.conf import settings
        return (Path(settings.BASE_DIR) / "templates" / "base.html"
                ).read_text(encoding="utf-8")

    def test_the_dialog_reads_the_smallest_size(self):
        src = self._src()
        fn = src[src.index("function sizeDialog(p)"):]
        fn = fn[:fn.index("function tradeFlow(")]
        self.assertIn("p.smallest_size", fn)
        auto = fn[fn.index("function autoQty()"):]
        auto = auto[:auto.index("/* ── The verdict, previewed")]
        self.assertIn("smallestQty", auto)
        self.assertIn("q < smallestQty", auto)
        # a moved stop says the size is held, not that the budget is
        self.assertIn("SIZE HELD AT THE SMALLEST SIZE", fn)
        # the note, and the broker's minimum's own note, before the PIN
        self.assertIn("(p.smallest_size && p.smallest_size.note) || "
                      "p.venue_min_note", fn)
        box = fn[fn.index("SIZE RAISED ABOVE THE RISK BUDGET"):]
        box = box[:box.index("'</div>'")]
        self.assertIn("esc(raisedNote)", box)
        self.assertIn("A warning, not a block", box)
        self.assertIn("with your trading PIN", box)
        self.assertIn('data-role="smallestsize"', fn)
        # ...and beside the PIN and the go button
        self.assertIn('data-role="smallestsizenotice"', fn)
        self.assertIn("sizeHtml + sideNotes + pinHtml", fn)

    def test_the_confirmation_names_the_smallest_size(self):
        src = self._src()
        flow = src[src.index("function tradeFlow("):]
        flow = flow[:flow.index("window.svTakeTrade = function")]
        self.assertIn("res.sized_by === 'smallest_size'", flow)


class TheHordeSaysItTests(TestCase):
    """The position's page names the size's source: yours, the risk budget,
    or the smallest size the venue takes."""

    def test_the_size_line(self):
        from bot_program.models import AssetBotTrade
        from bot_program.manual_trade import manual_config_for
        from dashboard.horde import _mission
        user = get_user_model().objects.create_user("floor_h", password="x")
        cfg = manual_config_for(user, "stock")
        seen = {}
        for src in ("smallest_size", "operator", "risk_budget"):
            t = AssetBotTrade.objects.create(
                config=cfg, asset_class="stock", symbol=STOCK, side="BUY",
                qty=Decimal("1"), entry_price=Decimal("150"),
                stop_loss=Decimal("147"), take_profit=Decimal("156"),
                status="OPEN", paper=True, rule_name="manual_take",
                metadata={"manual": True, "size_source": src,
                          "initial_stop_loss": 147.0})
            lines = _mission(t, True, None, "stock",
                             timezone.now() + timedelta(seconds=1))["at_entry"]
            seen[src] = [ln["t"] for ln in lines if ln["label"] == "Size"]
        self.assertEqual(seen, {
            "smallest_size": ["the smallest size the venue takes"],
            "operator": ["yours"], "risk_budget": ["the risk budget"]})


# ── 5. the size the ticket showed is the size sent (review, 2026-11-06) ──────

class _LiveStock(TestCase):
    """A LIVE stock lane on a fake broker, one invented 150 stock; the
    lane's own knobs carry a whole share (notional 1.0, single 100%)."""

    capital = "400"
    extras = {"max_notional_fraction": 1.0, "max_single_position_pct": 100.0}

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(
            "floor_" + cls.__name__.lower()[:20], password="x")

    def setUp(self):
        cache.clear()
        self.inst = _quote(STOCK, 150, asset_class="stock")
        _components_on()
        self.cfg = _arm_live(self.user, "stock")
        self.cfg.capital = Decimal(self.capital)
        self.cfg.extras = dict(self.extras)
        self.cfg.save(update_fields=["capital", "extras"])

    def _fake(self, qty="1", px="150"):
        fake = _fake_live_client(_filled_response(
            symbol=STOCK, executedQty=qty, avgPrice=px))
        fake.ticker.return_value = {"lastPrice": px}
        return fake

    def _sig(self, stop=147, target=156):
        return _signal(self.inst, entry=150, stop=stop, target=target)

    def _preview(self, floor=(None, "unstated"), sig=None):
        from bot_program.manual_trade import preview_take_trade
        with patch(ROUTER, return_value=self._fake()), \
                patch(FLOOR, return_value=floor):
            p = preview_take_trade(self.user, sig or self._sig())
        self.assertNotIn("error", p, p)
        return p

    def _send(self, fake, floor=(None, "unstated"), sig=None, **kw):
        from bot_program.manual_trade import execute_take_trade
        with patch(ROUTER, return_value=fake), \
                patch(FLOOR, return_value=floor):
            return execute_take_trade(self.user, sig or self._sig(),
                                      pin_ok=True, **kw)


class TheSentSizeIsTheShownSizeTests(_LiveStock):
    """The send re-runs the preview under its lock, and an eToro minimum
    the dialog could not read (a 429 is not cached) can be read there: the
    ticket showed one share and two went out. The dialog now sends back the
    size it showed (shown_qty) and whether it was raised above the budget
    (shown_raised); an automatic size the send raises goes out only when it
    is that size, shown as raised."""

    def test_a_minimum_read_since_the_ticket_refuses_the_send(self):
        from bot_program.models import AssetBotTrade
        p = self._preview(floor=(None, "eligibility answered 429"))
        self.assertEqual(p["qty"], 1.0)
        self.assertEqual(p["smallest_size"]["source"], "step")
        fake = self._fake(qty="2")
        out = self._send(fake, floor=(2.0, ""), shown_qty=1.0,
                         shown_raised=True)
        err = out.get("error", "")
        self.assertTrue(err.startswith(
            "The size changed since the ticket was shown: 1 unit then, 2 "
            "units now — the smallest size "), err)
        self.assertIn(" — risking 6.00 USD (1.50% of the pool). Nothing was "
                      "sent: open the ticket again to see it before you "
                      "confirm", err)
        fake.market_order.assert_not_called()
        self.assertEqual(AssetBotTrade.objects.count(), 0)

    def test_the_shown_size_goes_out_when_nothing_moved(self):
        self._preview()
        fake = self._fake()
        out = self._send(fake, shown_qty=1.0, shown_raised=True)
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(_sent_qty(fake), 1.0)
        self.assertEqual(out["sized_by"], "smallest_size")

    def test_a_budget_size_the_send_would_raise_is_refused(self):
        """A 1,200 pool: 0.25% (3.00) buys one share behind a 147 stop at
        150, no raise. The mark moves to 151 before the send: the budget
        buys none there, and the share would go out risking 4.00 — above
        the budget, never shown. It was refused before the smallest size
        existed, and it is again."""
        self.cfg.capital = Decimal("1200")
        self.cfg.save(update_fields=["capital"])
        sig = self._sig(target=170)
        p = self._preview(sig=sig)
        self.assertEqual(p["qty"], 1.0)
        self.assertIsNone(p["smallest_size"])
        _quote(STOCK, 151, asset_class="stock")
        fake = self._fake(px="151")
        out = self._send(fake, sig=sig, shown_qty=1.0, shown_raised=False)
        err = out.get("error", "")
        self.assertTrue(err.startswith(
            "The ticket showed 1 unit sized by the risk budget; at the send "
            "the budget buys less than the smallest size "), err)
        self.assertIn(", so it would go out at 1 unit, risking 4.00 USD "
                      "(0.33% of the pool) — more than the budget, and the "
                      "ticket did not say so. Nothing was sent: open the "
                      "ticket again to see it before you confirm", err)
        fake.market_order.assert_not_called()

    def test_the_brokers_minimum_read_since_refuses_too(self):
        """The 2026-10-01 raise, the same gap: a 4,000 pool sizes three
        shares from the budget; the broker's minimum of five, unread at
        the dialog and read at the send, would have sent five."""
        self.cfg.capital = Decimal("4000")
        self.cfg.save(update_fields=["capital"])
        p = self._preview()
        self.assertEqual((p["qty"], p["venue_min_note"]), (3.0, ""))
        fake = self._fake(qty="5")
        out = self._send(fake, floor=(5.0, ""), shown_qty=3.0,
                         shown_raised=False)
        self.assertEqual(out.get("error"), (
            "The ticket showed 3 units sized by the risk budget; at the send "
            "the budget buys less than the broker's minimum for FLOORCO, so "
            "it would go out at 5 units, risking 15.00 USD (0.38% of the "
            "pool) — more than the budget, and the ticket did not say so. "
            "Nothing was sent: open the ticket again to see it before you "
            "confirm"))
        fake.market_order.assert_not_called()

    def test_a_brokers_minimum_that_moved_since_refuses(self):
        self.cfg.capital = Decimal("4000")
        self.cfg.save(update_fields=["capital"])
        p = self._preview(floor=(5.0, ""))
        self.assertEqual(p["qty"], 5.0)
        self.assertIn("Raised from 3 to 5 units", p["venue_min_note"])
        fake = self._fake(qty="6")
        out = self._send(fake, floor=(6.0, ""), shown_qty=5.0,
                         shown_raised=True)
        self.assertEqual(out.get("error"), (
            "The size changed since the ticket was shown: 5 units then, 6 "
            "units now — the broker's minimum for FLOORCO — risking 18.00 "
            "USD (0.45% of the pool). Nothing was sent: open the ticket "
            "again to see it before you confirm"))
        fake.market_order.assert_not_called()
        # ...and the minimum the ticket showed goes out as shown
        fake = self._fake(qty="5")
        out = self._send(fake, floor=(5.0, ""), shown_qty=5.0,
                         shown_raised=True)
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(_sent_qty(fake), 5.0)

    def test_a_typed_size_is_the_operators_whatever_was_shown(self):
        fake = self._fake(qty="2")
        out = self._send(fake, floor=(2.0, ""), qty="2")
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(_sent_qty(fake), 2.0)
        self.assertEqual(out["sized_by"], "operator")


class TheForexStepThenTheMinimumTests(TestCase):
    """A LIVE forex lane on a 400 pool: the dialog could not read eToro's
    minimum and showed one 100-unit step; the send's own preview read it
    as 1,000 units. Shown 100, sent 1,000 — refused now."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("floor_fx_shown",
                                                        password="x")

    def setUp(self):
        cache.clear()
        _components_on()
        self.cfg = _arm_live(self.user, "forex")
        self.cfg.capital = Decimal("400")
        self.cfg.extras = {"max_single_position_pct": 100.0}
        self.cfg.save(update_fields=["capital", "extras"])
        self.fx = _quote("EURUSD", "1.10", asset_class="forex")

    def test_shown_one_step_read_a_thousand_units_refuses(self):
        from bot_program.manual_trade import (execute_take_trade,
                                              preview_take_trade)
        sig = _signal(self.fx, entry=1.10, stop=1.0725, target=1.16)
        fake = _fake_live_client(_filled_response(
            symbol="EURUSD", executedQty="1000", avgPrice="1.10"))
        fake.ticker.return_value = {"lastPrice": "1.10"}
        with patch(ROUTER, return_value=fake), \
                patch(FLOOR, return_value=(None, "answered 429")):
            p = preview_take_trade(self.user, sig)
        self.assertEqual(p["qty"], 100.0)
        with patch(ROUTER, return_value=fake), \
                patch(FLOOR, return_value=(1000.0, "")):
            out = execute_take_trade(self.user, sig, pin_ok=True,
                                     shown_qty=100.0, shown_raised=True)
        self.assertIn("The size changed since the ticket was shown: 100 "
                      "units then, 1000 units now", out.get("error", ""))
        fake.market_order.assert_not_called()


class TheLedgerSaysWhatWasSentTests(_LiveStock):
    """The ledger, the position page and the confirmation name the smallest
    size the ticket went at, and what it risked at the stop actually
    sent."""

    def test_a_tighter_stop_under_the_minimum_keeps_the_smallest_size(self):
        """Raised to the broker's minimum of two; the operator tightens the
        stop to 149 and the budget buys one, under the minimum: the dialog
        holds two, and the send sends two — as the smallest size, said so
        in the ledger, not as the risk budget."""
        from bot_program.models import AssetBotTrade
        p = self._preview(floor=(2.0, ""))
        self.assertEqual((p["qty"], p["smallest_size"]["source"]),
                         (2.0, "venue_minimum"))
        fake = self._fake(qty="2")
        out = self._send(fake, floor=(2.0, ""), stop=149)
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(_sent_qty(fake), 2.0)
        self.assertEqual(out["sized_by"], "smallest_size")
        meta = AssetBotTrade.objects.get(pk=out["trade_id"]).metadata
        self.assertEqual(meta["size_source"], "smallest_size")
        self.assertEqual(meta["smallest_size"]["source"], "venue_minimum")
        self.assertAlmostEqual(meta["risk_dollars"], 2.0, places=6)
        self.assertIn("2 units. At this stop it risks 2.00 USD (0.50% of "
                      "the pool)", meta["smallest_size"]["note"])

    def test_the_ledger_records_the_risk_at_the_stop_sent(self):
        """A 200 pool, the stop moved to 140: the entry's record says what
        the share risked there, not at the planned stop."""
        from bot_program.models import AssetBotTrade
        self.cfg.capital = Decimal("200")
        self.cfg.save(update_fields=["capital"])
        fake = self._fake()
        out = self._send(fake, sig=self._sig(target=200), stop=140)
        self.assertTrue(out.get("ok"), out)
        rec = AssetBotTrade.objects.get(
            pk=out["trade_id"]).metadata["smallest_size"]
        self.assertAlmostEqual(rec["risk"], 10.0, places=6)
        self.assertAlmostEqual(rec["risk_pct"], 5.0, places=4)
        self.assertIn("1 unit. At this stop it risks 10.00 USD (5.00% of the "
                      "pool), more than the 0.25% a ticket risks by "
                      "default.", rec["note"])

    def test_the_confirmation_and_the_ledger_say_which_smallest_size(self):
        """One step of this platform's granularity on a live venue whose
        minimum was not read is not "the smallest size the venue takes"."""
        from bot_program.models import AssetBotTrade
        fake = self._fake()
        out = self._send(fake)
        self.assertTrue(out.get("ok"), out)
        self.assertRegex(out["size_words"],
                         r"^the smallest size this platform sends to \S+$")
        rec = AssetBotTrade.objects.get(
            pk=out["trade_id"]).metadata["smallest_size"]
        self.assertEqual(rec["words"], out["size_words"])
        self.assertEqual(rec["source"], "step")

    def test_an_ordinary_ticket_carries_no_size_words(self):
        self.cfg.capital = Decimal("1200")
        self.cfg.save(update_fields=["capital"])
        fake = self._fake()
        out = self._send(fake, sig=self._sig(target=170))
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(out["sized_by"], "risk_budget")
        self.assertEqual(out["size_words"], "")


class TheStepIsNotCalledTheVenuesMinimumTests(_LiveStock):
    """eToro's floor on a stock is money (10 USD): 0.0667 of a 150 share.
    This lane sends whole shares on a live stock, so the minimum rounds up
    to one share — this platform's step, not the venue's minimum, and the
    words say so."""

    def _read(self, floor_units):
        from bot_program.manual_trade import preview_take_trade
        with patch(ROUTER, return_value=self._fake()), \
                patch(VENUE_FLOOR, return_value=(floor_units, "")):
            p = preview_take_trade(self.user, self._sig())
        self.assertNotIn("error", p, p)
        return p

    def test_a_minimum_rounded_up_to_the_step_says_so(self):
        p = self._read(10.0 / 150.0)
        self.assertEqual(p["venue_min_qty"], 1.0)
        rec = p["smallest_size"]
        self.assertEqual(rec["source"], "venue_minimum")
        self.assertRegex(rec["note"], (
            r"^Raised to the smallest size this platform sends that (\S+) "
            r"takes \(\1's own minimum is 0\.06667 units, about 10\.00 "
            r"USD\): 1 unit\. At this stop it risks 3\.00 USD \(0\.75% of "
            r"the pool\), more than the 0\.25% a ticket risks by default\.$"))
        self.assertRegex(rec["words"],
                         r"^the smallest size this platform sends that \S+ "
                         r"takes$")

    def test_an_exact_minimum_is_the_venues_own(self):
        p = self._read(2.0)
        rec = p["smallest_size"]
        self.assertRegex(rec["note"], r"^Raised to the smallest size \S+ "
                                      r"takes: 2 units\. ")
        self.assertRegex(rec["words"], r"^the smallest size \S+ takes$")

    def test_the_brokers_minimum_note_says_its_own_figure(self):
        """The 2026-10-01 note, which the dialog now prints: a minimum of
        4.5 shares is five in whole shares, and the note says both."""
        self.cfg.capital = Decimal("4000")
        self.cfg.save(update_fields=["capital"])
        p = self._read(4.5)
        self.assertEqual(p["venue_min_note"], (
            "Raised from 3 to 5 units: the broker refuses a FLOORCO order "
            "under 4.5 units (about 675 USD), and 5 is the smallest size "
            "this platform sends above that. It risks 15.00 at the stop "
            "instead of 10.00."))


class TheViewCarriesTheShownSizeTests(TestCase):
    """The execute views parse shown_qty and shown_raised and hand them
    down; a paper ticket refuses a raise it did not show, in words."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("floor_view",
                                                        password="x")

    def setUp(self):
        from bot_program.manual_trade import manual_config_for
        self.fx = _quote("EURUSD", 1.10, asset_class="forex")
        cfg = manual_config_for(self.user, "forex")
        cfg.capital = Decimal("50")
        cfg.save(update_fields=["capital"])

    def test_the_body_parser(self):
        from django.test import RequestFactory

        from dashboard.views import _parse_trade_body

        def parse(body):
            req = RequestFactory().post("/x", data=json.dumps(body),
                                        content_type="application/json")
            return _parse_trade_body(req)

        out, err = parse({})
        self.assertIsNone(err)
        self.assertIsNone(out["shown_qty"])
        self.assertIsNone(out["shown_raised"])
        out, _ = parse({"shown_qty": 100, "shown_raised": True})
        self.assertEqual((out["shown_qty"], out["shown_raised"]),
                         (100.0, True))
        out, _ = parse({"shown_qty": "2.5", "shown_raised": False})
        self.assertEqual((out["shown_qty"], out["shown_raised"]),
                         (2.5, False))
        for bad in ({"shown_qty": "x"}, {"shown_qty": True},
                    {"shown_raised": "yes"}, {"shown_raised": 1}):
            out, err = parse(bad)
            self.assertIsNone(out, bad)
            self.assertIn("shown_", err)

    def test_the_instrument_view_passes_it_through(self):
        self.client.force_login(self.user)
        url = "/instruments/EURUSD/take-trade/"
        res = self.client.post(url, json.dumps({
            "side": "BUY", "shown_qty": 100, "shown_raised": False}),
            content_type="application/json").json()
        err = res.get("error", "")
        self.assertTrue(err.startswith(
            "The ticket showed 100 units sized by the risk budget; at the "
            "send the budget buys less than the smallest size the paper "
            "venue takes, so it would go out at 100 units"), err)
        self.assertTrue(err.endswith(
            "Nothing was booked: open the ticket again to see it before you "
            "confirm"), err)
        res = self.client.post(url, json.dumps({
            "side": "BUY", "shown_qty": 100, "shown_raised": True}),
            content_type="application/json").json()
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(res["qty"], 100.0)
        self.assertEqual(res["size_words"],
                         "the smallest size the paper venue takes")


class TheHordeNamesWhichSmallestSizeTests(TestCase):

    def test_the_size_line_reads_the_words(self):
        from bot_program.manual_trade import manual_config_for
        from bot_program.models import AssetBotTrade
        from dashboard.horde import _mission
        user = get_user_model().objects.create_user("floor_h2", password="x")
        cfg = manual_config_for(user, "stock")

        def line(meta, paper):
            t = AssetBotTrade.objects.create(
                config=cfg, asset_class="stock", symbol=STOCK, side="BUY",
                qty=Decimal("1"), entry_price=Decimal("150"),
                stop_loss=Decimal("147"), take_profit=Decimal("156"),
                status="OPEN", paper=paper, rule_name="manual_take",
                metadata={"manual": True, "size_source": "smallest_size",
                          "initial_stop_loss": 147.0, **meta})
            lines = _mission(t, True, None, "stock",
                             timezone.now() + timedelta(seconds=1))["at_entry"]
            return [ln["t"] for ln in lines if ln["label"] == "Size"]

        self.assertEqual(line({"smallest_size": {
            "words": "the smallest size this platform sends to eToro",
            "source": "step"}}, paper=False),
            ["the smallest size this platform sends to eToro"])
        # a row from before the words: one live step is the platform's
        self.assertEqual(line({"smallest_size": {"source": "step"}},
                              paper=False),
                         ["the smallest size this platform sends"])
        self.assertEqual(line({"smallest_size": {"source": "venue_minimum"}},
                              paper=False),
                         ["the smallest size the venue takes"])


# ── 6. the dialog, run (node, with the server's own previews) ───────────────

#: Runs the ticket dialog's real code (templates/base.html, sizeDialog)
#: against the least of a document it touches, with a preview the server
#: produced, through the operator's steps; prints what the operator reads
#: after each step and what the dialog sends.
DIALOG_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const [, , srcPath, payloadPath, stepsPath] = process.argv;
let host = null;
function makeEl(tag) {
  const el = {
    tagName: tag, className: '', attrs: {}, _html: '', handlers: {}, _q: {},
    style: {}, dataset: {}, value: '', textContent: '', disabled: false,
    hidden: false,
    classList: { _s: new Set(),
      toggle(c, on) { if (on === undefined) on = !this._s.has(c);
                      if (on) this._s.add(c); else this._s.delete(c); return on; },
      add(c) { this._s.add(c); }, remove(c) { this._s.delete(c); },
      contains(c) { return this._s.has(c); } },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    addEventListener(ev, fn) { (this.handlers[ev] = this.handlers[ev] || []).push(fn); },
    fire(ev) {
      if (ev === 'click' && this.disabled) return;
      (this.handlers[ev] || []).forEach((f) => f({ target: this, preventDefault() {} }));
    },
    focus() { document.activeElement = this; },
    querySelector(sel) {
      const m = /\[data-role="([^"]+)"\]/.exec(sel);
      if (!m) return null;
      const role = m[1];
      const at = this._html.indexOf('data-role="' + role + '"');
      if (at === -1) return null;
      if (!this._q[role]) {
        const e = makeEl('x');
        const tag = this._html.slice(this._html.lastIndexOf('<', at),
                                     this._html.indexOf('>', at) + 1);
        const v = /\bvalue="([^"]*)"/.exec(tag);
        if (v) e.value = v[1];
        e.hidden = /\shidden[\s>=]/.test(tag);
        this._q[role] = e;
      }
      return this._q[role];
    },
    querySelectorAll() { return []; },
    get innerHTML() { return this._html; },
    set innerHTML(v) { this._html = String(v); this._q = {}; },
    parentNode: null,
  };
  return el;
}
global.window = global;
global.document = {
  createElement: makeEl, activeElement: null, cookie: '',
  body: { appendChild(e) { e.parentNode = this; host = e; }, removeChild() {} },
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {},
  querySelector() { return null; }, querySelectorAll() { return []; },
};
global.SV = { overlay: { open() {}, close() {}, alert() {} } };
global.fetch = () => new Promise(() => {});
global.setTimeout = () => 0;
global.clearTimeout = () => {};
global.CustomEvent = function () {};
vm.runInThisContext(fs.readFileSync(srcPath, 'utf8'));

const p = JSON.parse(fs.readFileSync(payloadPath, 'utf8'));
const steps = JSON.parse(fs.readFileSync(stepsPath, 'utf8'));
const strip = (s) => String(s).replace(/<[^>]+>/g, ' ').replace(/&quot;/g, '"')
  .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&')
  .replace(/\s+/g, ' ').trim();
let sent = null;
window.__sizeDialog(p).then((v) => { sent = v; });
const q = (r) => host.querySelector('[data-role="' + r + '"]');
function snap(label) {
  const box = q('smallestsize'), words = q('raisedwords'),
        notice = q('smallestsizenotice');
  return {
    step: label,
    qty: q('qty') ? q('qty').value : null,
    ok_disabled: q('ok').disabled,
    size_line: q('out') ? strip(q('out').innerHTML) : '',
    levels_line: q('lvlout') ? strip(q('lvlout').innerHTML) : '',
    box: box ? !box.hidden : null,
    box_words: words ? strip(words.textContent) : null,
    notice: notice ? !notice.hidden : null,
    notice_words: notice ? strip(notice.textContent) : null,
  };
}
const snaps = [snap('opened')];
for (const [what, val] of steps) {
  if (what === 'stop') { q('stop').value = String(val); q('stop').fire('input'); }
  else if (what === 'qty') {
    document.activeElement = q('qty'); q('qty').value = String(val);
    q('qty').fire('input');
  }
  else if (what === 'reset') { q('reset').fire('click'); }
  else if (what === 'pin') { q('pin').value = String(val); q('pin').fire('input'); }
  else if (what === 'ok') { q('ok').fire('click'); }
  document.activeElement = null;
  snaps.push(snap(what + ' ' + (val === undefined ? '' : val)));
}
setImmediate(() => process.stdout.write(JSON.stringify({ snaps, sent })));
"""


def _dialog_source():
    """The page script that holds sizeDialog, exposing it."""
    src = (Path(settings.BASE_DIR) / "templates" / "base.html"
           ).read_text(encoding="utf-8")
    at = src.index("function sizeDialog(p)")
    start = src.rindex("(function () {", 0, at)
    end = src.index("})();", src.index("window.svCloseTrade", at))
    return src[start:end] + "window.__sizeDialog = sizeDialog;\n})();\n"


def _drive(payload, steps):
    tmp = Path(tempfile.mkdtemp(prefix="sv-ticket-"))
    try:
        (tmp / "dialog.js").write_text(_dialog_source(), encoding="utf-8")
        (tmp / "run.js").write_text(DIALOG_HARNESS, encoding="utf-8")
        (tmp / "p.json").write_text(json.dumps(payload, cls=DjangoJSONEncoder),
                                    encoding="utf-8")
        (tmp / "steps.json").write_text(json.dumps(steps), encoding="utf-8")
        proc = subprocess.run(
            [NODE, str(tmp / "run.js"), str(tmp / "dialog.js"),
             str(tmp / "p.json"), str(tmp / "steps.json")],
            capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise AssertionError(f"the dialog did not run: {proc.stderr}")
        return json.loads(proc.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@unittest.skipUnless(NODE, "node is not installed")
class TheDialogHoldsTheBrokersMinimumTests(_LiveStock):
    """A 4,000 pool: the budget (10.00) buys three shares behind a 147
    stop, and the broker's minimum is five — the server raised the ticket
    to five. The operator widens the stop to 144 and leaves the size: the
    send lifts the budget's size back to the minimum, so the dialog holds
    five too, says so, and prints what five risk there."""

    capital = "4000"

    def test_the_dialog_shows_and_sends_what_the_send_sends(self):
        sig = self._sig(target=200)
        p = self._preview(floor=(5.0, ""), sig=sig)
        self.assertEqual(p["qty"], 5.0)
        got = _drive(p, [["stop", 144], ["pin", "1234"], ["ok"]])
        moved = got["snaps"][1]
        self.assertEqual(moved["qty"], "5")
        self.assertIn("SIZE HELD AT THE BROKER'S MINIMUM — 5 units; the "
                      "risk follows the stop", moved["size_line"])
        self.assertTrue(moved["box"])
        self.assertEqual(moved["box_words"], (
            "Raised to the broker's minimum for FLOORCO: 5 units. At this "
            "stop it risks $30.00 (0.75% of the pool), more than the 0.25% "
            "a ticket risks by default."))
        self.assertTrue(moved["notice"])
        sent = got["sent"]
        self.assertIsNone(sent["qty"])
        self.assertEqual(sent["stop"], 144)
        self.assertEqual((sent["shown_qty"], sent["shown_raised"]),
                         (5, True))
        # ...and the send sends it
        fake = self._fake(qty="5")
        out = self._send(fake, floor=(5.0, ""), sig=sig, stop=sent["stop"],
                         shown_qty=sent["shown_qty"],
                         shown_raised=sent["shown_raised"])
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(_sent_qty(fake), 5.0)


@unittest.skipUnless(NODE, "node is not installed")
class TheRaisedRiskFollowsTheStopTests(_LiveStock):
    """A 200 pool: the smallest size, one share, risks 3.00 behind the
    planned 147 stop. The box before the PIN said 3.00 whatever the stop
    became; it follows the stop now, and goes away when the size is no
    longer the raised one."""

    capital = "200"

    def test_the_box_and_the_pin_line_follow_the_size_and_the_stop(self):
        sig = self._sig(target=200)
        p = self._preview(sig=sig)
        got = _drive(p, [["stop", 140], ["qty", 2], ["reset"],
                         ["stop", 149.5], ["pin", "1234"], ["ok"]])
        opened, wide, typed, reset, tight = got["snaps"][:5]
        self.assertTrue(opened["box"])
        self.assertEqual(opened["box_words"], p["smallest_size"]["note"])
        self.assertIn("risks 3.00 USD (1.50% of the pool)",
                      opened["box_words"])
        self.assertTrue(opened["notice"])
        self.assertIn("1 unit, risking $3.00 (1.50% of the pool) at this "
                      "stop", opened["notice_words"])
        # the stop widened to 140: the share risks 10.00 there
        self.assertTrue(wide["box"])
        self.assertTrue(wide["box_words"].startswith(
            "Raised to the smallest size this platform sends to "),
            wide["box_words"])
        self.assertTrue(wide["box_words"].endswith(
            "1 unit. At this stop it risks $10.00 (5.00% of the pool), more "
            "than the 0.25% a ticket risks by default."), wide["box_words"])
        self.assertIn("1 unit, risking $10.00 (5.00% of the pool) at this "
                      "stop", wide["notice_words"])
        # a size typed by hand is not the raised one
        self.assertFalse(typed["box"])
        self.assertFalse(typed["notice"])
        self.assertTrue(reset["box"])
        self.assertIn("$10.00 (5.00% of the pool)", reset["box_words"])
        # a stop tight enough for the budget to buy the share: no raise
        self.assertFalse(tight["box"])
        self.assertFalse(tight["notice"])
        self.assertIn("SIZE FOLLOWS THE STOP", tight["size_line"])
        sent = got["sent"]
        self.assertEqual((sent["qty"], sent["stop"]), (None, 149.5))
        self.assertEqual((sent["shown_qty"], sent["shown_raised"]),
                         (1, False))
        fake = self._fake()
        out = self._send(fake, sig=sig, stop=sent["stop"],
                         shown_qty=sent["shown_qty"],
                         shown_raised=sent["shown_raised"])
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(_sent_qty(fake), 1.0)
        self.assertEqual(out["sized_by"], "risk_budget")


@unittest.skipUnless(NODE, "node is not installed")
class TheDialogMeetsMaxSinglePositionTests(_LiveStock):
    """A 400 pool whose single position may hold 20% (80.00): one share of
    the 150 stock is past it. The send refuses it after the PIN; the
    dialog now refuses it before, in the same terms."""

    extras = {"max_notional_fraction": 1.0, "max_single_position_pct": 20.0}

    def test_the_button_stays_off_with_the_reason(self):
        p = self._preview()
        self.assertEqual((p["qty"], p["max_qty"]), (1.0, 0.0))
        got = _drive(p, [["pin", "1234"]])
        pinned = got["snaps"][1]
        self.assertTrue(pinned["ok_disabled"])
        self.assertIn("1 units ties up $150.00 — past the $80.00 a single "
                      "position may hold (20% of the $400.00 manual pool).",
                      pinned["size_line"])
        fake = self._fake()
        out = self._send(fake)
        self.assertIn("past the 80.00 a single position may hold",
                      out.get("error", ""))
        fake.market_order.assert_not_called()


class TheDialogSendsWhatItShowedTests(SimpleTestCase):

    def test_the_flow_carries_the_shown_size_and_the_words(self):
        src = (Path(settings.BASE_DIR) / "templates" / "base.html"
               ).read_text(encoding="utf-8")
        fn = src[src.index("function sizeDialog(p)"):]
        fn = fn[:fn.index("function tradeFlow(")]
        ok = fn[fn.index("okBtn.addEventListener('click'"):]
        ok = ok[:ok.index("host.querySelector('[data-role=\"cancel\"]')")]
        self.assertIn("shown_qty:", ok)
        self.assertIn("shown_raised:", ok)
        flow = src[src.index("function tradeFlow("):]
        flow = flow[:flow.index("window.svTakeTrade = function")]
        send = flow[:flow.index("fetch(executeUrl")]
        self.assertIn("body.shown_qty = choice.shown_qty;", send)
        self.assertIn("body.shown_raised = !!choice.shown_raised;", send)
        # the confirmation names the smallest size the server says it was
        self.assertIn("res.size_words", flow)
        judge = fn[fn.index("function judgeSize(q)"):]
        judge = judge[:judge.index("/* ── Markup")]
        self.assertIn("a single position may hold", judge)
