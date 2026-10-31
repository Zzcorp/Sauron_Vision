"""SHORTS BY HAND ON EVERY CLASS eToro ALLOWS (2026-10-31).

The operator, 2026-10-31: "je veux les short possible entierement svp"
(I want shorts fully possible, please). Until then the TAKE TRADE lane
sent a SELL at eToro on stock and forex only (base.ETORO_SHORT_PROVEN):
an ETF, a commodity or a crypto short was refused AFTER the trading PIN,
and an index had no manual lane at all.

What changes, and only on the hand-taken lane:

  * THE TICKET WARNS BEFORE THE PIN. A live eToro SELL whose class has no
    short round trip pinned carries `short_advisory` ("First shorts on
    <class> at eToro are not measured yet ..."). The PIN door, every other
    gate, the venue minimum, the in-doubt handling and the venue health
    stay exactly as they are.
  * THE ORDER GOES. AssetBot._etoro_entry_refusal waives the SHORT token
    for this lane alone (waive_short_proof=True); a class whose own proof
    is not pinned is refused all the same, and THE BOTS KEEP THE GATE.
  * THE POSITION IS READ BACK at the fill (bot_program/short_readback.py):
    the fill's own orders:lookup body, or one GET by the order id when no
    body is in hand: the side, units, leverage, the position id, its state
    and its settlement against what was sent. A clean read is recorded as
    a measured short (EtoroShortObservation); anything else flags the row
    (metadata["short_readback"]), sounds Morgul at once (morgul.say_now:
    the staff chats and the alarm chat) and stands as Morgul's G13 finding
    while the row is open. A read eToro did not answer is read once more
    on the next tick, and alarms only if that read fails too.
  * AN INDEX TICKET rides the stock manual pool, the pool the bots already
    trade SPX500 from.

Run with:  python manage.py test tests.test_manual_shorts
"""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from tests.test_take_trade_live import (ROUTER, _arm_live, _components_on,
                                        _filled_response, _quote, _signal)

#: A bearish BTCUSD signal whose levels bracket the 60,000 mark.
BEAR = {"direction": "bearish", "entry": 60000, "stop": 60900,
        "target": 58200}
SHORTS = "bot_program.asset_engine.base.ETORO_SHORT_PROVEN"
PROVEN = "bot_program.asset_engine.base.ETORO_PROVEN"
EYE_SEND = "bot_program.telegram_eye._send"
ALARM_SEND = "bot_program.alarm.send_alarm"
RECIPIENTS = "bot_program.morgul.recipients"
WARNING = ("First shorts on crypto at eToro are not measured yet. The "
           "platform reads the position back right after the fill and "
           "alarms at once if eToro holds something else.")
#: G13's title by what the read-back found (2026-10-31): the alarm chat
#: hears the title alone, so each says what was found.
MISMATCH_TITLE = "Morgul — eToro holds a short other than the one sent"
MISSING_TITLE = "Morgul — eToro shows no position for a short just sent"
UNREAD_TITLE = "Morgul — a short just sent could not be read back from eToro"


def _short_lookup(*, order=7, position=900001, units=0.0004, avg=60000.0,
                  side="short", leverage=1, settlement="CFD", state="open",
                  status_id=3, executions=True, symbol="BTC", iid=100000,
                  fees=0.0):
    """orders:lookup of one filled SELL, in the shape the demo short
    round trips printed (tests/test_etoro_client.py CLASS_SHORT_PROOFS),
    with made-up ids and no account keys."""
    first = {"positionId": position, "state": state,
             "remainingUnits": units, "stopLossRate": 60900.0,
             "takeProfitRate": 58200.0,
             "openingData": {"openTime": "2026-10-31T12:00:00.100Z",
                             "orderId": order,
                             "executionTime": "2026-10-31T12:00:00.200Z",
                             "units": units, "avgPrice": avg, "fees": fees,
                             "marketSpread": 12.0, "markup": 0.5}}
    return {"orderId": order, "action": "open", "transaction": "sell",
            "type": "mkt",
            "status": {"id": status_id, "name": "Filled", "errorCode": 0},
            "asset": {"symbol": symbol, "instrumentId": iid,
                      "currency": "USD", "settlementType": settlement,
                      "leverage": leverage, "side": side},
            "requestedAmount": round(units * avg, 2),
            "requestedUnits": units, "totalCosts": fees,
            "openStopLossRate": 60900.0, "openTakeProfitRate": 58200.0,
            "positionExecutions": [first] if executions else [],
            "requestTime": "2026-10-31T12:00:00.100Z",
            "lastUpdate": "2026-10-31T12:00:00.250Z"}


class _EtoroShortBase(TestCase):
    """The live crypto manual lane on the REAL eToro adapter (demo world)
    over a fake wire — capabilities.adapter_key reads the class name, so
    only the real adapter meets the gate and the read-back."""

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("ms_u", password="x")

    def setUp(self):
        cache.clear()
        self.inst = _quote("BTCUSD", 60000)
        _components_on()
        self.cfg = _arm_live(self.user)
        from tests.test_etoro_client import _clear_eligibility
        _clear_eligibility()
        self.addCleanup(_clear_eligibility)

    def _etoro(self):
        from tests.test_etoro_client import ELIG_BTC, SEARCH_BTC, _client
        t, fake = _client([SEARCH_BTC, ELIG_BTC])
        p = patch.object(t, "ticker", return_value={"lastPrice": "60000"})
        p.start()
        self.addCleanup(p.stop)
        return t, fake

    def _cells(self):
        from tests.test_etoro_leverage import _account
        return _account(self.user, cash=100000)

    def _send(self, *, side="SELL", lookup=None, units_scale=1.0,
              response=None, pin_ok=True, signal=None, in_hand=True):
        """Execute a hand-taken ticket on the real adapter. market_order is
        the fill (`response`); the orders:lookup GET answers `lookup`
        (kwargs of _short_lookup, units = what was SENT x `units_scale`),
        or a (status, body) pair as given. A 200 body also rides the fill
        as the real adapter's raw["lookup"] (the body its fill poll last
        read) unless `in_hand` is False."""
        from bot_program.manual_trade import execute_take_trade
        from tests.test_etoro_client import _lookup_router
        t, fake = self._etoro()
        sent = {}

        def market_order(symbol, order_side, qty, **kw):
            sent.update(symbol=symbol, side=order_side, qty=qty, kw=kw)
            if isinstance(lookup, tuple):
                answer = lookup
            else:
                answer = (200, _short_lookup(units=qty * units_scale,
                                             **(lookup or {})))
            _lookup_router(fake, by_order=answer)
            res = _filled_response(side=order_side, executedQty=str(qty),
                                   avgPrice="60000", positionId="900001")
            if in_hand and answer[0] == 200:
                res["raw"] = {"lookup": answer[1]}
            res.update(response or {})
            return res

        sig = signal or _signal(self.inst, **(BEAR if side == "SELL"
                                              else {}))
        with patch.object(t, "market_order", side_effect=market_order), \
                patch(ROUTER, return_value=t):
            out = execute_take_trade(self.user, sig, pin_ok=pin_ok)
        return out, sent, fake

    @staticmethod
    def _lookups(fake):
        return [c for c in fake.calls
                if c[0] == "GET" and "orders:lookup" in str(c[1])]


class TheTicketWarnsBeforeThePinTests(_EtoroShortBase):

    def test_an_unmeasured_class_short_warns_in_the_preview(self):
        """crypto has no short round trip pinned (ETORO_SHORT_PROVEN is
        stock and forex): the live eToro SELL ticket previews — no error,
        the PIN still asked — and says the class's first shorts are not
        measured, in these words."""
        from bot_program.manual_trade import preview_take_trade
        t, _fake = self._etoro()
        with patch(ROUTER, return_value=t):
            p = preview_take_trade(self.user, _signal(self.inst, **BEAR))
        self.assertNotIn("error", p, p)
        self.assertTrue(p["requires_pin"])
        self.assertEqual(p["short_advisory"],
                         {"ok": False, "class": "crypto", "reason": WARNING})

    def test_a_measured_short_a_long_and_a_paper_ticket_say_nothing(self):
        from bot_program.manual_trade import preview_take_trade
        quiet = {"ok": True, "class": "", "reason": ""}
        t, _fake = self._etoro()
        with patch(ROUTER, return_value=t), \
                patch(SHORTS, frozenset({"crypto", "forex", "stock"})):
            p = preview_take_trade(self.user, _signal(self.inst, **BEAR))
        self.assertEqual(p["short_advisory"], quiet)
        with patch(ROUTER, return_value=t):
            p = preview_take_trade(self.user, _signal(self.inst))
        self.assertEqual(p["short_advisory"], quiet)
        self.cfg.mode = "paper"
        self.cfg.save(update_fields=["mode"])
        p = preview_take_trade(self.user, _signal(self.inst, **BEAR))
        self.assertNotIn("error", p, p)
        self.assertEqual(p["short_advisory"], quiet)

    def test_the_popup_prints_it_above_the_pin(self):
        from pathlib import Path

        from django.conf import settings
        src = Path(settings.BASE_DIR, "templates", "base.html").read_text()
        self.assertIn("var shortAdv = p.short_advisory || {};", src)
        self.assertIn("FIRST SHORT ON THIS CLASS AT eTORO", src)
        warn = src.index("var shortAdv = p.short_advisory || {};")
        self.assertLess(warn, src.index("var pinHtml = live"))
        self.assertIn("(res.readback_note ? '  ·  ⚠ ' + res.readback_note "
                      ": '')", src)


class TheLaneSendsTheShortTests(_EtoroShortBase):

    def test_an_unmeasured_class_short_is_sent_with_the_pin(self):
        """The order that was refused after the PIN until 2026-10-31
        ("no demo fill-and-close proof pinned for ['short_crypto']") now
        goes: one market_order, SELL, and the row is a SELL."""
        from bot_program.models import AssetBotTrade
        self._cells()
        out, sent, _fake = self._send()
        self.assertTrue(out.get("ok"), out)
        self.assertEqual((sent["symbol"], sent["side"]), ("BTCUSD", "SELL"))
        self.assertNotIn("leverage", sent["kw"], "a short goes at 1x")
        row = AssetBotTrade.objects.get(pk=out["trade_id"])
        self.assertEqual(row.side, "SELL")
        self.assertFalse(row.paper)
        self.assertEqual(row.metadata["short_advisory_at_entry"],
                         {"ok": False, "class": "crypto", "reason": WARNING})

    def test_the_pin_door_stays(self):
        out, sent, _fake = self._send(pin_ok=False)
        self.assertIn("PIN", out["error"])
        self.assertEqual(sent, {})

    def test_a_class_proof_is_never_waived(self):
        """Only the SHORT token is waived: a class whose own fill-and-close
        is not pinned is refused after the PIN as before, naming it."""
        self._cells()
        with patch(PROVEN, frozenset({"stock"})):
            out, sent, _fake = self._send()
        self.assertIn("eToro refusal (gate_blocked)", out["error"])
        self.assertIn("['crypto']", out["error"])
        self.assertNotIn("short_crypto", out["error"])
        self.assertEqual(sent, {})

    def test_the_headroom_still_refuses(self):
        """Every other gate stays: with no cells stored the account's
        headroom refuses before any order, as it does for a long."""
        out, sent, _fake = self._send()
        self.assertTrue(out["error"].startswith(
            "eToro refusal (leverage_refused): at 1x: "), out["error"])
        self.assertEqual(sent, {})


class TheReadBackTests(_EtoroShortBase):

    def setUp(self):
        super().setUp()
        self._cells()
        self.eye = patch(EYE_SEND, return_value=True)
        self.alarm = patch(ALARM_SEND, return_value=True)
        self.people = patch(RECIPIENTS, return_value=[self._staff()])
        self.eye_send = self.eye.start()
        self.alarm_send = self.alarm.start()
        self.people.start()
        for p in (self.eye, self.alarm, self.people):
            self.addCleanup(p.stop)

    def _staff(self):
        user, _ = get_user_model().objects.get_or_create(
            username="ms_staff", defaults={"is_staff": True})
        return user

    def _row(self, out):
        from bot_program.models import AssetBotTrade
        return AssetBotTrade.objects.get(pk=out["trade_id"])

    def test_a_clean_read_back_is_recorded_as_a_measured_short(self):
        """The fill's own orders:lookup body (market_order's raw["lookup"])
        is judged: no second GET spends the 20-per-60-s quota the fill
        poll has just used."""
        from bot_program.models import EtoroShortObservation
        out, sent, fake = self._send()
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(self._lookups(fake), [],
                         "the lookup in hand is judged: no second GET")
        row = self._row(out)
        rb = row.metadata["short_readback"]
        self.assertEqual((rb["ok"], rb["state"]), (True, "clean"))
        self.assertEqual(rb["held"]["side"], "short")
        self.assertEqual(out["short_readback"]["state"], "clean")
        self.assertNotIn("readback_note", out)
        ob = EtoroShortObservation.objects.get()
        self.assertEqual(ob.trade_id, row.pk)
        self.assertEqual((ob.asset_class, ob.symbol, ob.venue_symbol,
                          ob.instrument_id, ob.world, ob.side,
                          ob.settlement, ob.leverage),
                         ("crypto", "BTCUSD", "BTC", 100000, "demo", "short",
                          "CFD", 1))
        self.assertEqual((ob.order_id, ob.position_id), ("7", "900001"))
        self.assertAlmostEqual(float(ob.units), sent["qty"], places=8)
        self.assertEqual(float(ob.open_rate), 60000.0)
        self.assertEqual(float(ob.fees), 0.0)
        self.assertEqual(ob.opened_at.isoformat(),
                         "2026-10-31T12:00:00.100000+00:00")
        self.assertNotIn("accountId", ob.lookup)
        self.eye_send.assert_not_called()
        self.alarm_send.assert_not_called()

    def test_with_no_lookup_in_hand_one_get_reads_it_back(self):
        out, _sent, fake = self._send(in_hand=False)
        self.assertTrue(out.get("ok"), out)
        lookups = self._lookups(fake)
        self.assertEqual(len(lookups), 1, "one read-back GET")
        self.assertEqual(lookups[0][2]["params"], {"orderId": "7"})
        rb = self._row(out).metadata["short_readback"]
        self.assertEqual((rb["ok"], rb["state"]), (True, "clean"))
        self.alarm_send.assert_not_called()

    def _assert_alarmed(self, out, state, fact, title=MISMATCH_TITLE):
        from bot_program.models import EtoroShortObservation
        self.assertTrue(out.get("ok"), out)
        rb = self._row(out).metadata["short_readback"]
        self.assertEqual((rb["ok"], rb["state"]), (False, state))
        self.assertTrue(any(fact in f for f in rb["facts"]), rb["facts"])
        self.assertIn(fact, out["readback_note"])
        self.assertIn("Morgul has sounded the alarm", out["readback_note"])
        self.assertFalse(EtoroShortObservation.objects.exists())
        self.eye_send.assert_called_once()
        reply = self.eye_send.call_args.args[1]
        self.assertEqual(reply.title, title)
        self.assertIn("Severity: critical", reply.lines)
        self.assertTrue(any(fact in ln for ln in reply.lines), reply.lines)
        self.alarm_send.assert_called_once()
        heard = self.alarm_send.call_args.args[0]
        self.assertIn(title.split("—", 1)[1].strip(), heard)

    def test_a_long_where_a_short_was_sent_alarms_at_once(self):
        out, _sent, _fake = self._send(lookup={"side": "long"})
        self._assert_alarmed(out, "mismatch",
                             "eToro holds it as a long, not a short")

    def test_other_units_alarm(self):
        out, _sent, _fake = self._send(units_scale=0.5)
        self._assert_alarmed(out, "mismatch", "units, not the")

    def test_another_multiplier_alarms(self):
        out, _sent, _fake = self._send(lookup={"leverage": 2})
        self._assert_alarmed(out, "mismatch",
                             "eToro holds it at 2x, not the 1x sent")

    def test_another_position_alarms(self):
        out, _sent, _fake = self._send(lookup={"position": 900777})
        self._assert_alarmed(out, "mismatch",
                             "eToro names another position than the fill")

    def test_a_real_settlement_alarms(self):
        out, _sent, _fake = self._send(lookup={"settlement": "REAL"})
        self._assert_alarmed(out, "mismatch",
                             "eToro settled it REAL; a short is a CFD")

    def test_no_position_alarms(self):
        """A Filled body with no position is not judged off the fill: one
        GET asks, and eToro shows no position. Its title says that, never
        "eToro holds a short other than the one sent"."""
        out, _sent, _fake = self._send(lookup={"executions": False})
        self._assert_alarmed(out, "missing",
                             "eToro shows no position for this order",
                             title=MISSING_TITLE)

    def _tick(self, row, answer):
        """One tick of the lane that holds the row (manage_positions), its
        orders:lookup GET answering `answer`, a (status, body) pair."""
        from bot_program.asset_engine.base import make_bot
        from tests.test_etoro_client import _lookup_router
        t, fake = self._etoro()
        _lookup_router(fake, by_order=answer)
        with patch(ROUTER, return_value=t):
            make_bot(row.config).manage_positions()
        row.refresh_from_db()
        return fake

    def test_an_unanswered_read_back_waits_for_one_more_read(self):
        """A read eToro did not answer (a 500, a 429 off the quota the fill
        poll has just used) says nothing of the position: the row is not
        flagged, no alarm sounds, G13 stays quiet, and the confirmation
        says the next tick reads it once more."""
        from bot_program import morgul
        out, _sent, fake = self._send(lookup=(500, {}))
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(len(self._lookups(fake)), 1)
        rb = self._row(out).metadata["short_readback"]
        self.assertEqual((rb["ok"], rb["state"], rb["reads"]),
                         (None, "unread", 1))
        self.assertEqual(out["readback_note"],
                         "Not read back from eToro after the fill: eToro did "
                         "not answer the read by the order id; the next tick "
                         "reads it once more. Morgul sounds if that read "
                         "fails too, or finds eToro holding something "
                         "else.")
        self.eye_send.assert_not_called()
        self.alarm_send.assert_not_called()
        _ctx, findings, failed = morgul.collect(
            guards=[morgul.GUARD["short_readback"]])
        self.assertEqual((findings, failed), ([], []))

    def test_a_500_then_a_clean_read_leaves_the_row_clean_and_silent(self):
        from bot_program.models import EtoroShortObservation
        out, sent, _fake = self._send(lookup=(500, {}))
        row = self._row(out)
        fake = self._tick(row, (200, _short_lookup(units=sent["qty"])))
        lookups = self._lookups(fake)
        self.assertEqual(len(lookups), 1, "read once more, by the order id")
        self.assertEqual(lookups[0][2]["params"], {"orderId": "7"})
        rb = row.metadata["short_readback"]
        self.assertEqual((rb["ok"], rb["state"]), (True, "clean"))
        self.assertEqual(rb["sent"]["position_id"], "900001",
                         "the fill's position id is still compared")
        self.assertEqual(EtoroShortObservation.objects.get().trade_id, row.pk)
        self.eye_send.assert_not_called()
        self.alarm_send.assert_not_called()
        # read: the next tick does not ask again
        fake = self._tick(row, (200, _short_lookup(units=sent["qty"])))
        self.assertEqual(self._lookups(fake), [])

    def test_a_second_unanswered_read_alarms_in_its_own_words(self):
        """Both reads unanswered: the alarm says the short could not be
        read back, never that eToro holds something else, and offers no
        "Close position" (nothing is known to be wrong with it)."""
        from bot_program import morgul, short_readback
        out, sent, _fake = self._send(lookup=(500, {}))
        row = self._row(out)
        self._tick(row, (429, {}))
        rb = row.metadata["short_readback"]
        self.assertEqual((rb["ok"], rb["state"], rb["reads"]),
                         (False, "unread", 2))
        self.assertEqual(rb["facts"], ["eToro answered neither read by the "
                                       "order id; nothing reads it again"])
        self.assertEqual(short_readback.words(rb),
                         "Not read back from eToro after the fill: eToro "
                         "answered neither read by the order id; nothing "
                         "reads it again.")
        self.eye_send.assert_called_once()
        reply = self.eye_send.call_args.args[1]
        self.assertEqual(reply.title, UNREAD_TITLE)
        self.alarm_send.assert_called_once()
        self.assertIn("a short just sent could not be read back from eToro",
                      self.alarm_send.call_args.args[0])
        self.assertIsNone(self.alarm_send.call_args.kwargs.get("button"))
        (f,) = morgul.collect(guards=[morgul.GUARD["short_readback"]])[1]
        self.assertEqual(f.title, UNREAD_TITLE)
        self.assertIsNone(morgul.close_button(f))
        # said: no third read
        fake = self._tick(row, (200, _short_lookup(units=sent["qty"])))
        self.assertEqual(self._lookups(fake), [])

    def test_a_measured_short_and_a_long_are_not_read_back(self):
        from bot_program.models import EtoroShortObservation
        with patch(SHORTS, frozenset({"crypto", "forex", "stock"})):
            out, _sent, fake = self._send()
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(self._lookups(fake), [])
        self.assertNotIn("short_readback", self._row(out).metadata)
        cache.clear()
        out, _sent, fake = self._send(side="BUY")
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(self._lookups(fake), [])
        self.assertNotIn("short_readback", self._row(out).metadata)
        self.assertFalse(EtoroShortObservation.objects.exists())

    def test_a_working_short_is_read_back_when_it_fills(self):
        """A SELL eToro holds unfilled is booked WORKING with its read-back
        pending; the tick's fill (AssetBot._finish_working_entry) reads
        it back off the fill's own reading — no second GET."""
        from bot_program.asset_engine.base import make_bot
        from bot_program.models import EtoroShortObservation
        from tests.test_etoro_client import _client, _lookup_router
        out, sent, _fake = self._send(response={
            "status": "PENDING", "executedQty": "0.0", "avgPrice": "0.0",
            "working": True})
        self.assertTrue(out.get("working"), out)
        row = self._row(out)
        self.assertEqual(row.metadata["short_readback"]["state"], "pending")
        self.assertFalse(EtoroShortObservation.objects.exists())
        t, fake = _client([])
        _lookup_router(fake, by_order=(200, _short_lookup(units=sent["qty"])))
        st = t.order_status("7")
        before = len(self._lookups(fake))
        make_bot(row.config)._finish_working_entry(
            row, t, qty=st["filled"], price=st["avgPrice"], source="broker",
            venue=st)
        row.refresh_from_db()
        self.assertEqual(row.metadata["short_readback"]["state"], "clean")
        self.assertEqual(len(self._lookups(fake)), before)
        self.assertEqual(EtoroShortObservation.objects.get().trade_id, row.pk)


def _live_short(user, *, meta=None, rule="manual_take", symbol="BTCUSD",
                cls="crypto"):
    from bot_program.models import AssetBotConfig, AssetBotTrade
    from tests.test_take_trade_live import _instrument
    _instrument(symbol, cls)
    cfg, _ = AssetBotConfig.objects.get_or_create(
        user=user, asset_class=cls, name="manual",
        defaults={"mode": "live", "symbols": [], "enabled": True})
    md = {"broker": "etoro", "broker_env": "paper", "manual": True,
          "initial_stop_loss": 60900.0}
    md.update(meta or {})
    return AssetBotTrade.objects.create(
        config=cfg, asset_class=cls, symbol=symbol, side="SELL",
        qty=Decimal("0.0004"), entry_price=Decimal("60000"),
        stop_loss=Decimal("60900"), take_profit=Decimal("58200"),
        status="OPEN", paper=False, rule_name=rule, metadata=md)


FLAGGED = {"ok": False, "state": "mismatch",
           "facts": ["eToro holds it as a long, not a short"]}


class MorgulHearsTheReadBackTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user("ms_m", password="x")

    def setUp(self):
        cache.clear()

    def _run(self, key):
        from bot_program import morgul
        _ctx, findings, failed = morgul.collect(guards=[morgul.GUARD[key]])
        self.assertEqual(failed, [])
        return findings

    def test_g13_finds_a_flagged_open_short_and_offers_its_close(self):
        from bot_program import morgul
        row = _live_short(self.user, meta={"short_readback": FLAGGED})
        _live_short(self.user, symbol="ETHUSD",
                    meta={"short_readback": {"ok": True, "state": "clean",
                                             "facts": []}})
        (f,) = self._run("short_readback")
        self.assertEqual((f.subject, f.severity), (f"trade:{row.pk}",
                                                   "critical"))
        self.assertIn("eToro holds it as a long, not a short", f.facts)
        self.assertFalse(f.brakes, "a read-back never brakes")
        self.assertIsNotNone(morgul.close_button(f))
        row.status = "CLOSED"
        row.save(update_fields=["status"])
        self.assertEqual(self._run("short_readback"), [])

    def test_g13_titles_say_what_the_read_back_found(self):
        """The alarm chat hears the title and the label alone
        (alarm._finding_alarm): each state carries its own title. Only a
        short eToro is known to hold otherwise, or not at all, offers its
        "Close position"."""
        from bot_program import morgul
        rows = {}
        for symbol, state, fact in (
                ("BTCUSD", "mismatch", "eToro holds it as a long, not a "
                                       "short"),
                ("ETHUSD", "missing", "eToro shows no position for this "
                                      "order"),
                ("SOLUSD", "unread", "eToro answered neither read by the "
                                     "order id; nothing reads it again")):
            rows[state] = _live_short(self.user, symbol=symbol, meta={
                "short_readback": {"ok": False, "state": state,
                                   "facts": [fact]}})
        got = {f.subject: f for f in self._run("short_readback")}
        for state, title, closable in (("mismatch", MISMATCH_TITLE, True),
                                       ("missing", MISSING_TITLE, True),
                                       ("unread", UNREAD_TITLE, False)):
            f = got[f"trade:{rows[state].pk}"]
            self.assertEqual(f.title, title, state)
            self.assertEqual(morgul.close_button(f) is not None, closable,
                             state)

    def test_g13_says_an_unanswered_short_no_tick_has_read_again(self):
        """A read eToro did not answer waits for the next tick's read; a
        lane that no longer ticks never reads it again, so once
        READ_AGAIN_GRACE_S has passed G13 says it, in the unread words."""
        from datetime import timedelta

        from django.utils import timezone

        from bot_program import morgul, short_readback
        once = {"ok": None, "state": "unread", "reads": 1,
                "facts": ["eToro did not answer the read by the order id; "
                          "the next tick reads it once more"],
                "at": timezone.now().isoformat()}
        row = _live_short(self.user, meta={"short_readback": once})
        self.assertEqual(self._run("short_readback"), [])
        old = timezone.now() - timedelta(
            seconds=short_readback.READ_AGAIN_GRACE_S + 60)
        row.metadata = dict(row.metadata,
                            short_readback=dict(once, at=old.isoformat()))
        row.save(update_fields=["metadata"])
        (f,) = self._run("short_readback")
        self.assertEqual((f.title, f.severity), (UNREAD_TITLE, "critical"))
        self.assertIn("eToro did not answer the read by the order id, and "
                      "no tick has read it again in 15 minutes", f.facts)
        self.assertIsNone(morgul.close_button(f))

    def test_g5_leaves_a_hand_taken_short_to_the_read_back(self):
        """G5 still names a BOT's short on a class with no short proof; a
        hand-taken one is the operator's, warned before the PIN and read
        back at the fill (G13), never "past its proof"."""
        _live_short(self.user)
        self.assertEqual(self._run("proofs"), [])
        bot = _live_short(self.user, symbol="ETHUSD", rule="some_rule",
                          meta={"manual": False})
        (f,) = self._run("proofs")
        self.assertEqual(f.subject, f"trade:{bot.pk}")
        self.assertTrue(any("short" in x.lower() for x in f.facts), f.facts)

    def test_say_now_tells_the_staff_and_the_alarm_chat_once(self):
        from bot_program import morgul
        staff = get_user_model().objects.create_user("ms_staff2",
                                                     password="x",
                                                     is_staff=True)
        row = _live_short(self.user, meta={"short_readback": FLAGGED})
        with patch(RECIPIENTS, return_value=[staff]), \
                patch(EYE_SEND, return_value=True) as eye_send, \
                patch(ALARM_SEND, return_value=True) as alarm_send:
            said = morgul.say_now(morgul.short_readback_finding(row))
            self.assertEqual(said["delivered"], 1)
            eye_send.assert_called_once()
            alarm_send.assert_called_once()
            # the alarm chat hears the title and the label, never the facts
            self.assertEqual(alarm_send.call_args.args[1],
                             [morgul._trade_label(row),
                              "Morgul watches it; details on /health/."])
            # the beat that follows does not say it again
            report = morgul.cycle(send=True,
                                  guards=[morgul.GUARD["short_readback"]])
        self.assertEqual(report.result["findings"], 1)
        self.assertEqual(report.result["due"], 0)
        self.assertEqual(eye_send.call_count, 1)


class TheIndexLaneTests(_EtoroShortBase):
    """An index ticket rides the stock manual pool (EXECUTABLE_CLASS),
    the pool the bots trade SPX500 from; the gate keys on "index"."""

    def test_a_live_index_short_previews_with_the_warning(self):
        from bot_program.manual_trade import preview_asset_trade
        from tests.test_etoro_client import (_client, _elig_route, _elig_row,
                                             _lev)
        cfg = _arm_live(self.user, "stock")
        # a pool whose risk covers one whole unit of an index near 6,000
        cfg.capital = Decimal("100000")
        cfg.save(update_fields=["capital"])
        idx = _quote("SPX500", 6000, asset_class="index")
        row = _elig_row(27, "SPX500", [_lev("cfd", "long", [1, 2, 5]),
                                       _lev("cfd", "short", [1, 2, 5])],
                        min_exposure=1000)
        t, _fake = _client([("GET", "/market-data/search", 200,
                             [{"instrumentId": 27,
                               "internalSymbolFull": "SPX500"}]),
                            _elig_route([row])])
        with patch.object(t, "ticker", return_value={"lastPrice": "6000"}), \
                patch(ROUTER, return_value=t):
            p = preview_asset_trade(self.user, idx, "SELL")
        self.assertNotIn("error", p, p)
        self.assertEqual(p["asset_class"], "stock")
        self.assertFalse(p["short_advisory"]["ok"])
        self.assertTrue(p["short_advisory"]["reason"].startswith(
            "First shorts on indices at eToro are not measured yet."))

    def test_an_index_whose_quote_currency_is_unread_is_still_refused(self):
        """Step 1b stays whatever is waived: FTSE100 is sized as USD and
        its quote currency is unread (VENUE_QUOTE_UNMEASURED)."""
        from bot_program.asset_engine import skips
        from bot_program.asset_engine.base import AssetBot
        from tests.test_etoro_client import _client
        t, _ = _client([])
        code, why = AssetBot._etoro_entry_refusal(
            t, "FTSE100", "SELL", 1.0, 8000.0, "index",
            waive_short_proof=True)
        self.assertEqual(code, skips.GATE_BLOCKED)
        self.assertIn("quote currency unread", why)
