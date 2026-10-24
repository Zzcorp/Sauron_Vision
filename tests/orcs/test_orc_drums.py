"""THE WAR DRUMS IN O1 (bot_program/orcs/drums.py pure, drum_bus.py; spec
§4.7): published by code from facts it already writes, routed by code
within one user, journaled on the receivers as DR facts. No wake: with
`orcs_drums` ON or OFF a routed drum is a journal fact and nothing else
(drum wakes are O2's). A payload carries prices and ATR only, never an
idea's R, money or note, and never a calendar title.

Run with:  python manage.py test tests.orcs.test_orc_drums
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from tests.orcs.helpers import _config, _on, _row, _switch, _user, born

NOW = datetime(2026, 10, 21, 15, 0, tzinfo=dt_tz.utc)


def _idea(orc_id, symbol, cls, side="BUY"):
    return {"orc_id": orc_id, "symbol": symbol, "asset_class": cls,
            "side": side}


class TheReachTests(SimpleTestCase):

    MATRIX = {"rho": {("EURUSD", "GBPUSD"): 0.82, ("AUDUSD", "EURUSD"): 0.0,
                      ("EURUSD", "NZDJPY"): 0.75},
              "measured": {("EURUSD", "GBPUSD"), ("EURUSD", "NZDJPY")}}
    FACTORS = {"USD": ("XAUUSD", "EURUSD", "USDJPY", "SPX500", "NSDQ100")}

    def _drum(self, **kw):
        base = {"symbol": "EURUSD", "asset_class": "forex", "orc_id": 1,
                "hop": 0, "kind": "stop_hit"}
        base.update(kw)
        return base

    def test_the_routing_order_and_the_relations(self):
        from bot_program.orcs.drums import reach
        ideas = [_idea(1, "EURUSD", "forex"), _idea(2, "EURUSD", "forex"),
                 _idea(3, "GBPUSD", "forex"), _idea(4, "AUDUSD", "forex"),
                 _idea(5, "SPX500", "index"), _idea(6, "BTCUSD", "crypto"),
                 _idea(7, "NZDJPY", "forex")]
        got = dict(reach(self._drum(), ideas, self.MATRIX, self.FACTORS))
        self.assertNotIn(1, got, "the origin idea is excluded")
        self.assertEqual(got[2], "same symbol")
        self.assertEqual(got[3], "correlate, rho +0.82")
        self.assertEqual(got[4], "the USD leg", "an unmeasured rho is not a "
                                                "correlate; the leg routes")
        self.assertEqual(got[5], "the USD factor")
        self.assertEqual(got[7], "correlate, rho +0.75")
        self.assertNotIn(6, got)

    def test_an_unmeasured_pair_never_routes(self):
        from bot_program.orcs.drums import reach
        matrix = {"rho": {("BTCUSD", "ETHUSD"): 0.95}, "measured": set()}
        self.assertEqual(reach(self._drum(symbol="BTCUSD",
                                          asset_class="crypto"),
                               [_idea(9, "ETHUSD", "crypto")], matrix, {}),
                         [])

    def test_a_commodity_complex(self):
        from bot_program.orcs.drums import reach
        got = reach(self._drum(symbol="XAUUSD", asset_class="commodity"),
                    [_idea(2, "XAGUSD", "commodity")], {}, {})
        self.assertEqual(got, [(2, "the precious complex")])

    def test_hop_two_is_recorded_not_routed(self):
        from bot_program.orcs.constants import DRUM_MAX_HOP
        from bot_program.orcs.drums import reach
        self.assertEqual(DRUM_MAX_HOP, 2)
        ideas = [_idea(2, "EURUSD", "forex")]
        self.assertTrue(reach(self._drum(hop=1), ideas, {}, {}))
        self.assertEqual(reach(self._drum(hop=2), ideas, {}, {}), [])

    def test_payloads_carry_prices_and_atr_only(self):
        from bot_program.orcs import drums
        for payload in (
                drums.payload_stop_hit(stop=1.0832, at=NOW, beyond_atr=0.6),
                drums.payload_lock(what="break-even armed", price=1.0832),
                drums.payload_level_break(symbols=["EURUSD", "GBPUSD"],
                                          bar_end=NOW),
                drums.payload_news_shock(move_atr=1.3, minutes=12,
                                         article=7, corroborated=True),
                drums.payload_print(event=7, ccy="USD", x=2.1),
                drums.payload_sweep(tf="4h", side="high", price=1.09,
                                    reclaimed=True),
                drums.payload_thesis(why="a predicate met")):
            for key in payload:
                self.assertNotIn(key.lower(), ("r", "pnl", "money", "note",
                                               "r_now", "realized_r",
                                               "orc"))
                self.assertFalse(key.endswith("_r"), key)

    def test_the_lines(self):
        from bot_program.orcs.drums import line
        d = {"kind": "stop_hit", "symbol": "EURUSD", "hop": 0,
             "payload": {"stop": "1.08320", "at": NOW.isoformat(),
                         "beyond_atr": 0.6}}
        self.assertEqual(line(d, "same symbol", "DR3"),
                         "DR3: a stop at 1.08320 was hit on EURUSD at 15:00 "
                         "UTC; the price is 0.6 x ATR(1h) beyond it (same "
                         "symbol, hop 0).")
        d = {"kind": "news_shock", "symbol": "EURUSD", "hop": 0,
             "payload": {"move_atr": 1.3, "minutes": 12, "article": 7}}
        self.assertEqual(line(d, "same symbol", "DR4"),
                         "DR4: EURUSD moved 1.3 x ATR(1h) in 12 min after an "
                         "urgent headline (N7, untrusted) (same symbol).")
        d = {"kind": "level_break", "symbol": "EURUSD", "hop": 0,
             "payload": {"symbols": ["EURUSD", "GBPUSD"]}}
        self.assertEqual(line(d, "the USD leg", "DR5"),
                         "DR5: a 4h close beyond a structure level on "
                         "EURUSD, GBPUSD (the USD leg).")

    def test_a_wave_joins_within_fifteen_minutes(self):
        from bot_program.orcs.drums import wave_of
        open_ = [{"wave_id": "w1", "kind": "lock", "symbol": "EURUSD",
                  "at": NOW}]
        self.assertEqual(wave_of("lock", "EURUSD", NOW + timedelta(
            minutes=14), open_), "w1")
        self.assertNotEqual(wave_of("lock", "EURUSD", NOW + timedelta(
            minutes=16), open_), "w1")
        self.assertNotEqual(wave_of("stop_hit", "EURUSD", NOW, open_), "w1")


class _Bus(TestCase):

    def setUp(self):
        _switch("aragorn")
        _on()
        self.user = _user("orc_drums")
        self.other = _user("orc_drums_b")
        self.fx = _config(self.user, "forex", name="fx")

    def _fx(self, symbol, *, cfg=None, user_cfg=None):
        return born(self, _row(cfg or self.fx, symbol=symbol, cls="forex",
                               entry="1.10", stop="1.09", target="1.12"))


class ThePublishersTests(_Bus):

    def test_lock_on_transitions_only_never_a_trail_step(self):
        from bot_program.orcs import drum_bus
        from bot_program.orcs.models import OrcDrum
        orc = self._fx("EURUSD")
        row = orc.root_trade
        n = drum_bus.on_tick(orc, row, {"care_stop": [4, "trail"]},
                             {"care_stop": [5, "trail"]})
        self.assertEqual(n, 0, "a trail step drums nothing")
        n = drum_bus.on_tick(orc, row, {"care_stop": None},
                             {"care_stop": [0, "breakeven"]})
        self.assertEqual(n, 1)
        n = drum_bus.on_tick(orc, row, {"care_stop": [0, "breakeven"]},
                             {"care_stop": [0, "breakeven"]})
        self.assertEqual(n, 0)
        n = drum_bus.on_tick(orc, row, {"care_stop": [0, "breakeven"]},
                             {"care_stop": [0, "event lock (beyond the "
                                               "crowd)"]})
        self.assertEqual(n, 1)
        n = drum_bus.on_tick(orc, row, {"venue_refused": None},
                             {"venue_refused": 2})
        self.assertEqual(n, 1)
        self.assertEqual(OrcDrum.objects.filter(kind="lock").count(), 3)
        for d in OrcDrum.objects.all():
            self.assertEqual((d.user_id, d.orc_id, d.hop),
                             (self.user.pk, orc.pk, 0))

    def test_thesis_turned(self):
        from bot_program.orcs import drum_bus
        from bot_program.orcs.models import OrcDrum
        orc = self._fx("EURUSD")
        drum_bus.on_tick(orc, orc.root_trade, {"thesis": ["hold", None]},
                         {"thesis": ["exit", None]})
        drum_bus.on_tick(orc, orc.root_trade, {"predicates": {}},
                         {"predicates": {"time::": {"state": "met"}}})
        drum_bus.on_tick(orc, orc.root_trade,
                         {"predicates": {"time::": {"state": "met"}}},
                         {"predicates": {"time::": {"state": "met"}}})
        self.assertEqual(OrcDrum.objects.filter(kind="thesis_turned").count(),
                         2)

    def test_stop_hit_from_the_venue_stop_and_the_care_soft_stop(self):
        from bot_program.orcs import drum_bus
        from bot_program.orcs.ghost import RealExit
        from bot_program.orcs.models import OrcDrum
        orc = self._fx("EURUSD")
        row = orc.root_trade
        for kind, why, want in (("venue_stop", "", 1), ("care", "trail", 1),
                                ("care", "weekend cut", 0),
                                ("care", "event cut", 0), ("hand", "", 0)):
            OrcDrum.objects.all().delete()
            with patch("bot_program.orcs.ghost.real_exit_of",
                       return_value=RealExit(kind, level=1.0905, at=NOW,
                                             why=why)):
                drum_bus.on_close(orc, row)
            with self.subTest(kind=kind, why=why):
                self.assertEqual(OrcDrum.objects.filter(
                    kind="stop_hit").count(), want)
        with patch("bot_program.orcs.ghost.real_exit_of",
                   return_value=RealExit("venue_stop", level=1.0905, at=NOW)):
            drum_bus.on_close(orc, row)
            drum_bus.on_close(orc, row)
        self.assertEqual(OrcDrum.objects.filter(kind="stop_hit").count(), 1,
                         "once per leg")

    def test_the_care_cuts_and_clocks_drum_nothing_its_locks_drum(self):
        """As the care really closes a row (metadata["care_exit"], outcome
        stopped_out, read by ghost.real_exit_of unpatched): a weekend cut,
        an event cut and the no-progress clock are not stops; a trail or a
        break-even lock is."""
        from django.utils import timezone

        from bot_program.models import AssetBotTrade
        from bot_program.orcs import drum_bus
        from bot_program.orcs.models import OrcDrum
        for care_exit, want in (("weekend cut", 0), ("event cut", 0),
                                ("no progress", 0), ("trail", 1),
                                ("breakeven (beyond the crowd)", 1)):
            orc = self._fx("EURUSD")
            row = orc.root_trade
            meta = dict(row.metadata or {})
            meta["care_exit"] = care_exit
            AssetBotTrade.objects.filter(pk=row.pk).update(
                status="CLOSED", outcome="stopped_out", exit_price=1.0950,
                reason="closed:SL", closed_at=timezone.now(), metadata=meta)
            row.refresh_from_db()
            OrcDrum.objects.all().delete()
            drum_bus.on_close(orc, row)
            with self.subTest(care_exit=care_exit):
                self.assertEqual(OrcDrum.objects.filter(
                    kind="stop_hit").count(), want)

    def test_a_sweep_line_says_it_was_reclaimed(self):
        """A sweep is smart_money.sweep_read's: a wick through the level
        and a close back inside it on the same bar, so the drum says
        "swept, then reclaimed" (TheSweepOnFinalBarsTests: once per
        sweeping bar, on final bars only)."""
        from bot_program.orcs import drums
        line = drums.line({"kind": "sweep", "symbol": "EURUSD",
                           "payload": drums.payload_sweep(
                               tf="4h", side="high", price="1.10500",
                               reclaimed=True)}, "same symbol", "DR1")
        self.assertEqual(line, "DR1: EURUSD: the 4h high at 1.10500 was "
                               "swept, then reclaimed (same symbol).")

    def test_one_level_break_per_class_per_bar(self):
        from bot_program.orcs import drum_bus
        from bot_program.orcs.models import OrcDrum
        self._fx("EURUSD")
        self._fx("GBPUSD")
        end = datetime(2026, 10, 21, 12, 0, tzinfo=dt_tz.utc)
        breaks = {(self.user.pk, "forex", end): ["EURUSD", "GBPUSD"]}
        with patch.object(drum_bus, "_level_breaks", return_value=breaks):
            drum_bus.hourly_market(NOW)
            drum_bus.hourly_market(NOW + timedelta(minutes=5))
        drums = list(OrcDrum.objects.filter(kind="level_break"))
        self.assertEqual(len(drums), 1)
        self.assertEqual(drums[0].payload["symbols"], ["EURUSD", "GBPUSD"])

    def test_news_shock_only_when_price_corroborates(self):
        from bot_program.orcs.drum_bus import corroborated
        at = NOW
        ring = [(at - timedelta(minutes=5), 1.1000),
                (at + timedelta(minutes=5), 1.1004),
                (at + timedelta(minutes=10), 1.1013)]
        ok, move, minutes = corroborated(ring, at, atr1h=0.0010)
        self.assertTrue(ok)
        self.assertAlmostEqual(move, 1.3, places=1)
        self.assertEqual(minutes, 10)
        ok, move, _ = corroborated(ring[:2], at, atr1h=0.0010)
        self.assertFalse(ok)
        late = ring[:1] + [(at + timedelta(minutes=20), 1.1050)]
        self.assertFalse(corroborated(late, at, atr1h=0.0010)[0],
                         "a move after 15 minutes is not the headline's")
        self.assertFalse(corroborated(ring, at, atr1h=None)[0])

    def test_an_uncorroborated_shock_is_stored_and_reaches_nobody(self):
        from bot_program.orcs import drum_bus
        from bot_program.orcs.models import OrcDrum
        self._fx("EURUSD")
        self._fx("GBPUSD")
        shock = drum_bus.publish(
            "news_shock", user=self.user, symbol="EURUSD",
            asset_class="forex", origin="code",
            payload={"move_atr": None, "minutes": None, "article": 7,
                     "corroborated": False}, at=NOW)
        drum_bus.route(NOW)
        shock.refresh_from_db()
        self.assertIsNotNone(shock.routed_at)
        self.assertEqual(shock.reach, [])
        self.assertEqual(OrcDrum.objects.count(), 1)


class TheRoutingTests(_Bus):

    def test_routed_within_the_user_as_dr_facts_once_per_wave(self):
        from bot_program.orcs import drum_bus
        from bot_program.orcs.models import OrcJournal
        a = self._fx("EURUSD")
        b = self._fx("EURUSD")
        c = self._fx("USDJPY")
        theirs = born(self, _row(_config(self.other, "forex", name="o"),
                                 symbol="EURUSD", cls="forex", entry="1.10",
                                 stop="1.09", target="1.12"))
        d = drum_bus.publish("stop_hit", user=self.user, symbol="EURUSD",
                             asset_class="forex", origin=f"orc:{a.pk}",
                             orc=a, payload={"stop": "1.09050",
                                             "at": NOW.isoformat(),
                                             "beyond_atr": 0.6}, at=NOW)
        n = drum_bus.route(NOW)
        self.assertEqual(n, 2)
        d.refresh_from_db()
        self.assertEqual(sorted(r["orc"] for r in d.reach),
                         sorted([b.pk, c.pk]))
        lines = {e.orc_id: e for e in OrcJournal.objects.filter(kind="drum")}
        self.assertNotIn(a.pk, lines, "the origin hears nothing")
        self.assertNotIn(theirs.pk, lines, "another user's book is private")
        self.assertTrue(lines[b.pk].fact_id.startswith("DR"))
        self.assertIn("(same symbol, hop 0)", lines[b.pk].headline)
        self.assertIn("the USD leg", lines[c.pk].headline)
        self.assertEqual(lines[b.pk].body["fk"], "drum")
        # one per (wave, Orc): a second drum of the same wave adds nothing
        drum_bus.publish("stop_hit", user=self.user, symbol="EURUSD",
                         asset_class="forex", origin=f"orc:{a.pk}", orc=a,
                         wave_id=d.wave_id,
                         payload={"stop": "1.09040", "at": NOW.isoformat(),
                                  "beyond_atr": 0.7}, at=NOW)
        drum_bus.route(NOW + timedelta(minutes=1))
        self.assertEqual(OrcJournal.objects.filter(kind="drum").count(), 2)
        self.assertEqual(drum_bus.route(NOW + timedelta(minutes=2)), 0)

    def test_the_card_shows_the_drums_heard(self):
        from bot_program.orcs import drum_bus
        from bot_program.orcs.models import Orc
        a = self._fx("EURUSD")
        b = self._fx("EURUSD")
        drum_bus.publish("lock", user=self.user, symbol="EURUSD",
                         asset_class="forex", origin=f"orc:{a.pk}", orc=a,
                         payload={"what": "break-even armed",
                                  "price": "1.10020"}, at=NOW)
        drum_bus.route(NOW)
        card = Orc.objects.get(pk=b.pk).card
        self.assertEqual(card["drums"][-1]["from_symbol"], "EURUSD")
        self.assertEqual(card["drums"][-1]["kind_t"], "a lock")

    def test_orcs_drums_on_or_off_a_delivery_wakes_nobody_in_o1(self):
        """§4.7 "Rollout" and §11: in O1 drums are published and routed as
        journal facts only; drum wakes (W12) are O2's. With `orcs_drums`
        ON, as OFF, a routed drum leaves the receiver's pending wake
        untouched and the receiver hears it as a DR fact."""
        from bot_program.orcs import drum_bus
        from bot_program.orcs.models import Orc, OrcJournal
        a = self._fx("EURUSD")
        b = self._fx("EURUSD")
        for on, at in ((False, NOW), (True, NOW + timedelta(hours=1))):
            _switch("orcs_drums", on)
            drum_bus.publish("lock", user=self.user, symbol="EURUSD",
                             asset_class="forex", origin=f"orc:{a.pk}", orc=a,
                             payload={"what": "an event lock",
                                      "price": "1.10020"}, at=at)
            with patch.object(drum_bus, "_urgent_for",
                              return_value=True) as urgent:
                self.assertEqual(drum_bus.route(at), 1)
            with self.subTest(orcs_drums=on):
                self.assertFalse((Orc.objects.get(pk=b.pk).seen or {})
                                 .get("wake_pending"))
                urgent.assert_not_called()
        self.assertEqual(OrcJournal.objects.filter(kind="drum",
                                                   orc=b).count(), 2)

    def test_a_dead_orc_hears_no_drum(self):
        from bot_program.models import AssetBotTrade
        from bot_program.orcs import drum_bus
        from bot_program.orcs.models import Orc, OrcJournal
        a = self._fx("EURUSD")
        b = self._fx("EURUSD")
        Orc.objects.filter(pk=b.pk).update(state="dead")
        AssetBotTrade.objects.filter(pk=b.root_trade_id).update(
            status="CLOSED", exit_price=Decimal("1.1"))
        drum_bus.publish("lock", user=self.user, symbol="EURUSD",
                         asset_class="forex", origin=f"orc:{a.pk}", orc=a,
                         payload={"what": "break-even armed",
                                  "price": "1.10020"}, at=NOW)
        drum_bus.route(NOW)
        self.assertEqual(OrcJournal.objects.filter(kind="drum").count(), 0)


class TheLevelBreakTests(_Bus):
    """Review (O1c): a coalesced level_break reaches the Orcs of EVERY
    symbol it lists, and a symbol whose 4h bar turned final only at a
    later pass joins the wave in a drum of its own, once."""

    def setUp(self):
        super().setUp()
        self.st = _config(self.user, "stock", name="st")

    def _stock(self, symbol):
        return born(self, _row(self.st, symbol=symbol, cls="stock"))

    def _heard(self):
        from bot_program.orcs.models import OrcJournal
        return dict(OrcJournal.objects.filter(kind="drum")
                    .values_list("orc_id", "body__relation"))

    def test_every_listed_symbol_is_reached(self):
        from bot_program.orcs import drum_bus
        a, m = self._stock("AAPL"), self._stock("MSFT")
        end = datetime(2026, 10, 21, 12, 0, tzinfo=dt_tz.utc)
        with patch.object(drum_bus, "_level_breaks", return_value={
                (self.user.pk, "stock", end): ["AAPL", "MSFT"]}), \
                patch.object(drum_bus, "_sweeps", return_value=[]):
            drum_bus.hourly_market(NOW)
        drum_bus.route(NOW)
        self.assertEqual(self._heard(), {a.pk: "same symbol",
                                         m.pk: "same symbol"})

    def test_a_symbol_final_one_pass_later_joins_the_wave_once(self):
        from bot_program.orcs import drum_bus
        from bot_program.orcs.models import OrcDrum
        a, m = self._stock("AAPL"), self._stock("MSFT")
        end = datetime(2026, 10, 21, 12, 0, tzinfo=dt_tz.utc)
        key = (self.user.pk, "stock", end)
        for at, listed in ((NOW, ["AAPL"]),
                           (NOW + timedelta(hours=1), ["AAPL", "MSFT"]),
                           (NOW + timedelta(hours=2), ["AAPL", "MSFT"])):
            with patch.object(drum_bus, "_level_breaks",
                              return_value={key: listed}), \
                    patch.object(drum_bus, "_sweeps", return_value=[]):
                drum_bus.hourly_market(at)
            drum_bus.route(at)
        drums = list(OrcDrum.objects.filter(kind="level_break")
                     .order_by("id"))
        self.assertEqual([d.payload["symbols"] for d in drums],
                         [["AAPL"], ["MSFT"]])
        self.assertEqual({d.wave_id for d in drums},
                         {f"lb:{self.user.pk}:stock:2026102112"})
        self.assertEqual(self._heard(), {a.pk: "same symbol",
                                         m.pk: "same symbol"})

    def test_a_break_on_real_final_4h_bars(self):
        """No patch on _level_breaks: the newest FINAL 4h close crossed a
        swing high of the menu as it stood before that bar."""
        from bot_program.orcs import drum_bus
        from tests.orcs.helpers import _bars, _wave
        cfg = _config(self.user, name="cr")
        born(self, _row(cfg))
        ohlc = _wave(80, base=100.0, amp=2.0, period=12)
        last_close = ohlc[-1][3]
        ohlc.append((last_close, 108.0, last_close - 0.1, 107.5))
        start = NOW - timedelta(hours=4 * len(ohlc))
        _bars("BTCUSD", "4h", ohlc, start=start)
        at = NOW + timedelta(minutes=13)
        got = drum_bus._level_breaks(at)
        self.assertEqual(list(got.values()), [["BTCUSD"]], got)
        (uid, cls, end), = got
        self.assertEqual((uid, cls, end), (self.user.pk, "crypto", NOW))
        flat = [(last_close, last_close + 0.1, last_close - 0.1, last_close)]
        _bars("BTCUSD", "4h", flat, start=NOW - timedelta(hours=4))
        self.assertEqual(drum_bus._level_breaks(at), {},
                         "a bar that crosses nothing drums nothing")


class TheSweepOnFinalBarsTests(_Bus):
    """Review (O1c): the forming 4h bar's wick through a swing high, with
    the price back under it, is no sweep until that bar closes back
    inside; then it drums once."""

    OHLC = ([(100, 101, 99, 100)] * 29
            + [(101, 103, 100, 102), (102, 105, 101, 104),
               (104, 107, 103, 106), (106, 110, 105, 108),
               (108, 109, 104, 105), (105, 107, 103, 104),
               (104, 106, 102, 105), (105, 106, 103, 104),
               (104, 106, 103, 105), (105, 106, 104, 105)]
            + [(105, 111, 104.5, 105)])

    def test_no_sweep_off_a_forming_bar_then_one_once_it_closed(self):
        from bot_program.orcs import drum_bus
        from bot_program.orcs.models import OrcDrum
        from tests.orcs.helpers import _bars
        cfg = _config(self.user, name="cr")
        born(self, _row(cfg))
        opened = datetime(2026, 10, 21, 12, 0, tzinfo=dt_tz.utc)
        start = opened - timedelta(hours=4 * (len(self.OHLC) - 1))
        _bars("BTCUSD", "4h", self.OHLC, start=start)
        with patch.object(drum_bus, "_level_breaks", return_value={}):
            drum_bus.hourly_market(datetime(2026, 10, 21, 15, 0,
                                            tzinfo=dt_tz.utc))
        self.assertEqual(OrcDrum.objects.filter(kind="sweep").count(), 0,
                         "the 12:00 bar is still forming at 15:00")
        closed = opened + timedelta(hours=4, minutes=13)
        with patch.object(drum_bus, "_level_breaks", return_value={}):
            drum_bus.hourly_market(closed)
            drum_bus.hourly_market(closed + timedelta(hours=1))
        got = list(OrcDrum.objects.filter(kind="sweep"))
        self.assertEqual(len(got), 1, "once per sweeping bar")
        self.assertEqual((got[0].payload["side"], got[0].payload["price"],
                          got[0].payload["reclaimed"]),
                         ("high", "110.00", True))
        self.assertTrue(got[0].wave_id.endswith(":4h:2026102116:h"),
                        got[0].wave_id)


class TheCensusDrumTests(_Bus):
    """The census's market drums on the database, unpatched where it can
    be: the LiveQuote ring is sampled by the census itself, a headline
    waits for the price, a print is measured against its own history."""

    def _quote(self, symbol, last):
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        inst, _ = Instrument.objects.get_or_create(
            symbol=symbol, defaults={"name": symbol, "asset_class": "forex"})
        LiveQuote.objects.update_or_create(instrument=inst,
                                           defaults={"last": last})
        return inst

    def _headline(self, inst, at):
        from scraping.models import NewsArticle
        art = NewsArticle.objects.create(
            title="ECB shock", source="x", url=f"http://x/{at:%H%M}",
            published_at=at, ai_urgency="high")
        art.ai_affected_instruments.add(inst)
        return art

    def test_a_news_shock_the_census_ring_corroborates(self):
        from django.core.cache import cache

        from bot_program.orcs import drum_bus
        from bot_program.orcs.models import OrcDrum, OrcJournal
        cache.clear()
        self.addCleanup(cache.clear)
        a = self._fx("EURUSD")
        b = self._fx("EURUSD")
        inst = self._quote("EURUSD", 1.1000)
        with patch.object(drum_bus, "_atr1h", return_value=0.0010):
            drum_bus.census_market(NOW - timedelta(minutes=5))   # samples
            self._headline(inst, NOW - timedelta(minutes=2))
            self._quote("EURUSD", 1.1015)
            n = drum_bus.census_market(NOW + timedelta(minutes=5))
        self.assertEqual(n, 1)
        d = OrcDrum.objects.get(kind="news_shock")
        self.assertTrue(d.payload["corroborated"])
        self.assertAlmostEqual(d.payload["move_atr"], 1.5, places=1)
        drum_bus.route(NOW + timedelta(minutes=5))
        heard = set(OrcJournal.objects.filter(kind="drum")
                    .values_list("orc_id", flat=True))
        self.assertEqual(heard, {a.pk, b.pk}, "origin is code: both hear")

    def test_a_shock_waits_for_the_price_then_is_stored_unrouted(self):
        from django.core.cache import cache

        from bot_program.orcs import drum_bus
        from bot_program.orcs.models import OrcDrum, OrcJournal
        cache.clear()
        self.addCleanup(cache.clear)
        self._fx("EURUSD")
        inst = self._quote("EURUSD", 1.1000)
        self._headline(inst, NOW - timedelta(minutes=5))
        with patch.object(drum_bus, "_atr1h", return_value=0.0010):
            self.assertEqual(drum_bus.census_market(NOW), 0,
                             "five minutes: the price may still speak")
            self.assertEqual(drum_bus.census_market(
                NOW + timedelta(minutes=11)), 1)
        d = OrcDrum.objects.get(kind="news_shock")
        self.assertFalse(d.payload["corroborated"])
        drum_bus.route(NOW + timedelta(minutes=11))
        self.assertEqual(OrcJournal.objects.filter(kind="drum").count(), 0)

    def test_a_print_surprise_against_its_own_history(self):
        from market_data.models import EconomicEvent

        from bot_program.orcs import drum_bus
        from bot_program.orcs.models import OrcDrum, OrcJournal
        a = self._fx("EURUSD")
        for i in range(9):
            EconomicEvent.objects.create(
                title="CPI m/m", country="US", impact="High",
                currency_affected="USD", source="forexfactory",
                datetime=NOW - timedelta(days=30 * (i + 1)),
                actual="0.3%", forecast="0.2%")
        ev = EconomicEvent.objects.create(
            title="CPI m/m", country="US", impact="High",
            currency_affected="USD", source="forexfactory",
            datetime=NOW - timedelta(minutes=30), actual="0.7%",
            forecast="0.2%")
        self.assertEqual(drum_bus.census_market(NOW), 1)
        self.assertEqual(drum_bus.census_market(NOW), 0, "once")
        d = OrcDrum.objects.get(kind="print_surprise")
        self.assertEqual(d.payload, {"event": ev.pk, "ccy": "USD",
                                     "x_median": 5.0})
        drum_bus.route(NOW)
        line = OrcJournal.objects.get(kind="drum", orc=a).headline
        self.assertEqual(line, f"DR1: the USD print C{ev.pk} printed 5.0 x "
                               f"its median surprise (the USD leg).")

    def test_the_census_runs_the_market_drums(self):
        from bot_program.orcs import census, drum_bus
        self._fx("EURUSD")
        with patch.object(drum_bus, "census_market", return_value=2) as cm:
            out = census.run(NOW)
        cm.assert_called_once_with(NOW)
        self.assertEqual(out["drums_published"], 2)

    def test_a_standing_venue_refusal_drums_once(self):
        from bot_program.orcs import drum_bus
        orc = self._fx("EURUSD")
        row = orc.root_trade
        seq = [None, 2, 2, 2]
        n = [drum_bus.on_tick(orc, row, {"venue_refused": b},
                              {"venue_refused": a})
             for b, a in zip(seq, seq[1:])]
        self.assertEqual(n, [1, 0, 0])
