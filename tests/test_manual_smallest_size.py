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

Every broker here is a fake: no network.

Run with:  python manage.py test tests.test_manual_smallest_size
"""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from tests.test_take_trade_live import (ROUTER, _arm_live, _components_on,
                                        _fake_live_client, _filled_response,
                                        _quote, _signal)

FLOOR = "bot_program.manual_trade._venue_min_qty"
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
