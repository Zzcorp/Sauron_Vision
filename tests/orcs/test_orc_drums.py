"""THE WAR DRUMS IN O1 (bot_program/orcs/drums.py pure, drum_bus.py; spec
§4.7): published by code from facts it already writes, routed by code
within one user, journaled on the receivers as DR facts. No wake: with
`orcs_drums` ON a routed drum only adds W12 to the receiver's next
detected wake. A payload carries prices and ATR only, never an idea's R,
money or note.

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
                drums.payload_print(title="US CPI m/m", ccy="USD", x=2.1),
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

    def test_a_sweep_drums_once_per_level_and_says_it_was_reclaimed(self):
        """A menu sweep is smart_money.sweep_read's: a wick through the
        level and a close back inside it on the same bar, so the drum says
        "swept, then reclaimed"; once per (user, symbol, tf, level)."""
        from bot_program.orcs import drum_bus, drums
        from bot_program.orcs.menu import Level, Menu
        from bot_program.orcs.models import OrcDrum
        self._fx("EURUSD")
        menu = Menu(symbol="EURUSD", as_of=NOW, levels=[
            Level(id="SW4h-H1", kind="sweep", tf="4h", side="above",
                  price=1.1050, stop=None),
            Level(id="S4h-H1", kind="swing", tf="4h", side="above",
                  price=1.1080, stop=None)])
        with patch("bot_program.orcs.menu.symbol_levels",
                   return_value=menu), \
                patch.object(drum_bus, "_level_breaks", return_value={}):
            drum_bus.hourly_market(NOW)
            drum_bus.hourly_market(NOW + timedelta(hours=1))
        got = list(OrcDrum.objects.filter(kind="sweep"))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].payload["side"], "high")
        line = drums.line({"kind": "sweep", "symbol": "EURUSD",
                           "payload": got[0].payload}, "same symbol", "DR1")
        self.assertIn("was swept, then reclaimed", line)

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

    def test_w12_only_with_orcs_drums_on(self):
        from bot_program.orcs import drum_bus
        from bot_program.orcs.models import Orc
        a = self._fx("EURUSD")
        b = self._fx("EURUSD")
        drum_bus.publish("lock", user=self.user, symbol="EURUSD",
                         asset_class="forex", origin=f"orc:{a.pk}", orc=a,
                         payload={"what": "break-even armed",
                                  "price": "1.10020"}, at=NOW)
        drum_bus.route(NOW)
        self.assertFalse((Orc.objects.get(pk=b.pk).seen or {})
                         .get("wake_pending"), "OFF: recorded, wakes nobody")
        _switch("orcs_drums", True)
        drum_bus.publish("lock", user=self.user, symbol="EURUSD",
                         asset_class="forex", origin=f"orc:{a.pk}", orc=a,
                         payload={"what": "an event lock",
                                  "price": "1.10020"},
                         at=NOW + timedelta(hours=1))
        drum_bus.route(NOW + timedelta(hours=1))
        pending = Orc.objects.get(pk=b.pk).seen["wake_pending"]
        self.assertEqual([r["code"] for r in pending["reasons"]], ["W12"])

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
