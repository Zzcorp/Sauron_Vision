"""THE DECISION REPLAY: TODAY'S MONEY DECISIONS, GOLDEN (the eToro feed
spec, F1, §5.10, A6/A7/A15; 2026-11-07).

"Money direction: none. Replay proves equality with today." Each scenario
below runs the REAL consumer code of one adapter of the §5.10 registry
(ADAPTERS: the display and the money paths M1-M19) on the harness's fakes
(tests/feed/harness.py) — a fixed clock, a fake eToro whose surface is the
real client's, that records every request with its arguments and refuses
every write it is not told to accept, fake LiveQuote writers — and
compares what it decided with GOLDEN (tests/feed/replay_golden.json): the
decisions main made, recorded on main BEFORE F1 touched a money path. F1's
source rule and its harm counters must leave every line equal.

THE COMPLETENESS PINS (§5.10). Every registered adapter has a golden run;
every golden run belongs to a registered adapter and a timeline; every
timeline that exists before the feed (TIMELINES, phase "F1") has a run,
and the rest name the phase that brings them; every LiveQuote read in a
money module names its adapter (tests/feed/test_feed_pins.py ratchet).

The timelines that exist before the feed:
  T7   the weekend and the Sunday reopen (the venue's own clock, unpatched),
       crypto through the weekend;
  T10  an outside quote absent, stale, disagreeing, agreeing, the venue's
       own, a poller's, a stand-in;
  T18  every eToro price dead (the ticker raises);
  T19  an exit with no price across the daily-loss gate;
  T21  the interim eToro writer on, out-ranked by a stream, held, back —
       on a forex pair and on an index CFD whose outside quote is its cash
       index;
and the named regressions: the stale-quote valuation gap (a real row
valued at another feed's quote of any age once its stamp is 15 minutes
old), a future standing in for a commodity CFD, and an index CFD held
overnight against a re-stamped cash close. The index CFD is synthetic
(IDX500, mapped for the scenario to a synthetic cash index, "^IDX"), so
the cash-index branches run on no real instrument.

With the feed absent and every switch OFF (A15), money_price refuses each
purpose.

Recording: FEED_REPLAY_RECORD=1 prints each scenario's decisions instead of
asserting (how GOLDEN was made, on main). Run with:
    python manage.py test tests.feed.test_decision_replay
"""
import json
import os
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase

from tests.feed import harness as H

RECORD = os.environ.get("FEED_REPLAY_RECORD") == "1"
GOLDEN_FILE = Path(__file__).with_name("replay_golden.json")
#: TODAY'S DECISIONS (recorded on main, before F1 touched a money path:
#: FEED_REPLAY_RECORD=1). A line changes only with a money change, its
#: switch and its own pull request.
GOLDEN = json.loads(GOLDEN_FILE.read_text(encoding="utf-8"))

#: §5.10's registry: the display and the nineteen money paths, each with
#: the golden runs that replay it.
ADAPTERS = {
    "display": ("the P&L tier and the main cell's valuation",
                ("t21", "t21_index", "m9_gap")),
    "M1": ("the tick, care and SL/TP", ("m1_tick",)),
    "M2": ("mark sanity", ("m2_t10", "m2_jump", "m2_stand_in",
                           "regression_index_overnight")),
    "M3": ("the bot's entry gate", ("m3_entry_gate",)),
    "M4": ("the ticket's quote advisory", ("m4_ticket",)),
    "M5": ("the CLOSE button", ("m5_dead", "m5_live")),
    "M6": ("the kill switch", ("m6_kill_switch",)),
    "M7": ("the drain", ("m7_drain",)),
    "M8": ("the reconcile", ("m8_reconcile",)),
    "M9": ("resolve, bookable, for_booking", (
        "m9_gap", "m9_stand_in", "t7_weekend", "regression_index_overnight")),
    "M10": ("the level editor", ("m10_levels",)),
    "M11": ("the position review", ("m11_review",)),
    "M12": ("the conversion", ("m12_conversion",)),
    "M13": ("stress and posture", ("m13_stress",)),
    "M14": ("Morgul's heartbeat", ("m14_morgul",)),
    "M15": ("price alerts", ("m15_alerts",)),
    "M16": ("paper", ("m16_paper", "t7_weekend")),
    "M17": ("book value and the daily-loss gate", ("t19_gate",)),
    "M18": ("the NL trader (the legacy rows close through M6's price read)",
            ("m18_nl_trader",)),
    "M19": ("the Orcs", ("m19_orcs",)),
}
#: §5.10's timelines: the golden runs of those that exist before the feed,
#: and the phase that brings each of the others (the feed's stream, REST,
#: transitions, /pnl, switches).
TIMELINES = {
    "T1": "F6", "T2": "F6", "T3": "F6", "T4": "F6", "T5": "F6",
    "T6": ("F1", ("m1_tick", "m2_jump")),
    "T7": ("F1", ("t7_weekend",)),
    "T8": "F6", "T9": "F6",
    "T10": ("F1", ("m2_t10", "m2_stand_in", "m3_entry_gate", "m4_ticket",
                   "m8_reconcile", "m9_gap", "m9_stand_in", "m10_levels",
                   "m11_review", "m12_conversion", "m13_stress",
                   "m14_morgul", "m15_alerts", "m16_paper",
                   "m18_nl_trader", "m19_orcs",
                   "regression_index_overnight")),
    "T11": "F10", "T12": "F4", "T13": "F3", "T14": "F6", "T15": "F6",
    "T16": "F9", "T17": "F6",
    "T18": ("F1", ("m5_dead", "m5_live", "m6_kill_switch", "m7_drain")),
    "T19": ("F1", ("t19_gate",)),
    "T20": "F6",
    "T21": ("F1", ("t21", "t21_index")),
    "T22": "F6", "T23": "F2b", "T24": "F4",
    "A15": ("F1", ("a15_door",)),
}

#: The synthetic index CFD and the synthetic cash index Yahoo would quote
#: in its place (public_feed.YF_SYMBOL_MAP, patched for the scenario).
INDEX_CFD = "IDX500"
CASH_INDEX = "^IDX"

#: T10's states of the outside quote, written by the real write_quote.
OUTSIDE_STATES = (
    ("absent", None),
    ("stale_stream", dict(source="oanda_stream", last="1.1100",
                          bid="1.1099", ask="1.1101", age_s=1000)),
    ("agreeing_stream", dict(source="oanda_stream", last="1.1002",
                             bid="1.1001", ask="1.1003")),
    ("disagreeing_stream", dict(source="oanda_stream", last="1.1100",
                                bid="1.1099", ask="1.1101")),
    ("venue_own_interim", dict(source="etoro", last="1.1001",
                               bid="1.1000", ask="1.1002")),
    ("disagreeing_poller", dict(source="yfinance", last="1.1100")),
    ("stale_poller", dict(source="yfinance", last="1.1100", age_s=4000)),
)


def _iso(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


class _Replay(TestCase):

    #: the venue's own clock (venue_mark.market_shut) reads OPEN unless a
    #: scenario runs it for real (the weekend)
    PATCH_MARKET_SHUT = True
    START = H.T0

    def setUp(self):
        self.clock = H.FakeClock(start=self.START)
        self.clock.__enter__()
        self.addCleanup(self.clock.__exit__, None, None, None)
        if self.PATCH_MARKET_SHUT:
            p = mock.patch("bot_program.venue_mark.market_shut",
                           return_value=None)
            p.start()
            self.addCleanup(p.stop)

    def golden(self, name, observed):
        observed = json.loads(json.dumps(observed, default=str))
        if RECORD:
            print("\nGOLDEN " + json.dumps({name: observed}, sort_keys=True))
            return
        self.assertIn(name, GOLDEN, f"no golden decision for {name}")
        self.assertEqual(observed, GOLDEN[name], name)

    def _owner(self):
        if not hasattr(self, "owner"):
            self.owner = H.user("replay_owner")
            self.cfgs = {}
        return self.owner

    def _cfg(self, cls):
        self._owner()
        if cls not in self.cfgs:
            self.cfgs[cls] = H.live_config(self.owner, cls)
        return self.cfgs[cls]

    def _row(self, symbol="EURUSD", cls="forex", **kw):
        cfg = self._cfg(cls)
        H.instrument(symbol, cls)
        defaults = {"forex": dict(entry="1.1000", stop="1.0900",
                                  target="1.1200"),
                    "commodity": dict(entry="2000", stop="1950",
                                      target="2100"),
                    "index": dict(entry="5000", stop="4900",
                                  target="5200"),
                    "crypto": dict(entry="50000", stop="48000",
                                   target="54000")}[cls]
        defaults.update(kw)
        return H.real_row(cfg, symbol, **defaults)

    def _states(self, symbol, cls, read, states=OUTSIDE_STATES):
        """{state: read()} over T10's states of `symbol`'s outside quote."""
        from market_data.models import LiveQuote
        out = {}
        for name, quote in states:
            LiveQuote.objects.filter(instrument__symbol=symbol).delete()
            if quote:
                H.write_live_quote(symbol, clock=self.clock, asset_class=cls,
                                   **quote)
            out[name] = read()
        return out


# ── M9: valuation and booking (resolve, bookable, for_booking) ───────────

def _answers(trade, quote):
    from bot_program import venue_mark
    mk = venue_mark.resolve(trade, quote)
    return {"resolve": H.mark_of(mk),
            "bookable": venue_mark.bookable(mk, trade),
            "for_booking": H.mark_of(venue_mark.for_booking(trade, quote))}


class TheValuationReplayTests(_Replay):

    def test_m9_the_stale_quote_gap(self):
        """A real row whose eToro stamp is 20 minutes old is valued at
        another feed's quote, of any age, provided it is not older than
        the stamp (harm 6); an older quote leaves the stale stamp."""
        out = {}
        t = self._row(meta=H.stamp("1.1000", age_s=1200, clock=self.clock,
                                   bid="1.0999", ask="1.1001"))
        H.write_live_quote("EURUSD", source="yfinance", last="1.1050",
                           clock=self.clock, age_s=600)
        out["quote_newer_than_stamp"] = _answers(t, H.live_quote("EURUSD"))
        H.write_live_quote("EURUSD", source="yfinance", last="1.1050",
                           clock=self.clock, age_s=3 * 3600)
        out["quote_older_than_stamp"] = _answers(t, H.live_quote("EURUSD"))
        fresh = self._row(meta=H.stamp("1.1000", age_s=60, clock=self.clock,
                                       bid="1.0999", ask="1.1001"))
        out["fresh_stamp"] = _answers(fresh, H.live_quote("EURUSD"))
        self.golden("m9_gap", out)

    def test_m9_a_future_stands_in_for_a_cfd(self):
        out = {}
        t = self._row("XAUUSD", "commodity",
                      meta=H.stamp("2000", age_s=7200, clock=self.clock))
        H.write_live_quote("XAUUSD", source="yfinance", last="2010",
                           clock=self.clock, asset_class="commodity")
        q = H.live_quote("XAUUSD")
        out["answers"] = _answers(t, q)
        bare = self._row("XAUUSD", "commodity")
        out["no_stamp"] = _answers(bare, q)
        self.golden("m9_stand_in", out)


class TheIndexOvernightReplayTests(_Replay):
    """The named regression: an index CFD held overnight against its cash
    index's close, re-stamped as fresh by the poller. The CFD trades
    through the cash market's night; the cash close is another instrument
    (a stand-in) that mark sanity takes as a second opinion today (harm
    2)."""

    PATCH_MARKET_SHUT = False

    def test_the_index_cfd_overnight(self):
        from bot_program import mark_sanity, venue_mark
        from market_data.public_feed import YF_SYMBOL_MAP
        with mock.patch.dict(YF_SYMBOL_MAP, {INDEX_CFD: CASH_INDEX}):
            t = self._row(INDEX_CFD, "index",
                          meta=H.stamp("5000", age_s=3600, clock=self.clock,
                                       bid="4999", ask="5001"))
            H.write_live_quote(INDEX_CFD, source="yfinance", last="4900",
                               clock=self.clock, asset_class="index")
            q = H.live_quote(INDEX_CFD)
            bot = SimpleNamespace(cfg=t.config)
            verdict = mark_sanity.check(bot, t, 5000.0, None)
            shut = venue_mark.market_shut(t)
            self.golden("regression_index_overnight", {
                "stand_in": venue_mark.quote_stand_in(INDEX_CFD, q,
                                                      carrier="etoro"),
                "second_opinion": mark_sanity.second_opinion(INDEX_CFD),
                "check": {"ok": verdict["ok"], "why": verdict["why"]},
                "market_shut": None if shut is None else {
                    k: _iso(v) for k, v in shut.items()},
                "answers": _answers(t, q)})


# ── M1: the manage tick on a real eToro row ──────────────────────────────

class TheTickReplayTests(_Replay):

    def _pass(self, bot, trade):
        closed = bot.manage_positions()
        care = (H.row_state(trade), (type(trade).objects.get(pk=trade.pk)
                                     .metadata or {}).get("care") or {})
        return {"closed": closed, "row": care[0],
                "last_mark": care[1].get("last_mark"),
                "suspect": bool(care[1].get("mark_suspect"))}

    def test_m1_a_jump_through_the_stop_waits_then_closes(self):
        """The tick reads eToro's rate, judges it, and closes on the stop
        only once a second print confirms the jump (T6 today: one tick
        later)."""
        from bot_program.asset_engine.base import make_bot
        t = self._row()
        bot = make_bot(t.config)
        etoro = H.EtoroTrader({"EURUSD": H.tick("1.1000")}, writes="accept")
        out = {}
        with H.route_to(etoro):
            out["inside_the_levels"] = self._pass(bot, t)
            self.clock.advance(60)
            etoro.rates["EURUSD"] = H.tick("1.0800")
            out["jump_through_the_stop"] = self._pass(bot, t)
            self.clock.advance(60)
            etoro.rates["EURUSD"] = H.tick("1.0801")
            out["confirmed"] = self._pass(bot, t)
        out["requests"] = etoro.methods
        out["writes"] = etoro.writes_sent
        self.golden("m1_tick", out)


# ── M2: mark sanity and its second opinion (T10) ─────────────────────────

class TheMarkSanityReplayTests(_Replay):

    def _check(self, trade, price):
        from bot_program import mark_sanity
        bot = SimpleNamespace(cfg=trade.config)
        v = mark_sanity.check(bot, trade, price, None)
        trade.refresh_from_db()
        care = (trade.metadata or {}).get("care") or {}
        return {"ok": v["ok"], "why": v["why"],
                "suspect": bool(care.get("mark_suspect")),
                "last_mark": care.get("last_mark")}

    def test_t10_every_state_of_the_outside_quote(self):
        from bot_program.mark_sanity import second_opinion

        def read():
            t = self._row()
            return {"second_opinion": second_opinion("EURUSD"),
                    "check": self._check(t, 1.1)}
        self.golden("m2_t10", self._states("EURUSD", "forex", read))

    def test_m2_a_jump_waits_for_its_second_print(self):
        t = self._row()
        out = {"accepted": self._check(t, 1.1)}
        self.clock.advance(60)
        out["jump"] = self._check(t, 1.11)
        self.clock.advance(60)
        out["confirmed"] = self._check(t, 1.1101)
        self.golden("m2_jump", out)

    def test_m2_a_stand_in_quote_still_disagrees_today(self):
        """A future standing in for a CFD is a second opinion today (no
        stand-in check; harm 2)."""
        from bot_program.mark_sanity import second_opinion
        H.write_live_quote("XAUUSD", source="yfinance", last="2100",
                           clock=self.clock, asset_class="commodity")
        t = self._row("XAUUSD", "commodity")
        self.golden("m2_stand_in", {
            "second_opinion": second_opinion("XAUUSD"),
            "check": self._check(t, 2000.0)})


# ── M3, M4: the bot's entry gate and the ticket's advisory (T10) ─────────

class TheEntryReplayTests(_Replay):

    def test_m3_the_entry_gate_on_every_outside_quote(self):
        from bot_program.asset_engine.base import make_bot
        bot = make_bot(self._cfg("forex"))
        etoro = H.EtoroTrader()
        H.instrument("EURUSD", "forex")

        def gate():
            g = bot._entry_quote_gate("EURUSD", H.tick("1.1000"), etoro,
                                      stop=1.09)
            return {"ok": g["ok"], "why": g["why"],
                    "unread": bool(g.get("unread"))}
        out = self._states("EURUSD", "forex", gate)
        out["requests"] = etoro.methods
        self.golden("m3_entry_gate", out)

    def test_m4_the_tickets_quote_advisory(self):
        from bot_program.manual_trade import quote_advisory
        etoro = H.EtoroTrader()
        H.instrument("EURUSD", "forex")

        def advice():
            return quote_advisory(H.tick("1.1000"), "forex", "EURUSD",
                                  stop=1.09, live=True, client=etoro)
        out = self._states("EURUSD", "forex", advice)
        out["requests"] = etoro.methods
        self.golden("m4_ticket", out)


# ── M10, M11: the level editor and the position review (T10) ─────────────

class TheLevelAndReviewReplayTests(_Replay):

    def test_m10_the_level_editor(self):
        from bot_program import adjust_levels
        out = {}
        for name, meta in (("stale_stamp", H.stamp(
                "1.1000", age_s=1200, clock=self.clock, bid="1.0999",
                ask="1.1001")), ("fresh_stamp", H.stamp(
                "1.1000", age_s=60, clock=self.clock, bid="1.0999",
                ask="1.1001")), ("no_stamp", None)):
            t = self._row(meta=meta)

            def levels(t=t):
                mark = adjust_levels._mark_for(t)
                return {"mark": H.num(mark), "reasons": [
                    str(r) for r in adjust_levels.validate_levels(
                        t, Decimal("1.0950"), Decimal("1.1150"))]}
            out[name] = self._states("EURUSD", "forex", levels)
        self.golden("m10_levels", out)

    def test_m11_the_position_review(self):
        from brain.position_review import BOOK_BOT, _venue_mark_for
        out = {}
        for symbol, cls, price in (("EURUSD", "forex", "1.1000"),
                                   ("XAUUSD", "commodity", "2000")):
            pos = {"book": BOOK_BOT, "paper": False, "symbol": symbol,
                   "asset_class": cls, "dir_sign": 1,
                   "metadata": H.stamp(price, age_s=1200, clock=self.clock)}

            def review(pos=pos):
                got = _venue_mark_for(pos)
                return None if got is None else [H.num(got[0]), got[1]]
            states = OUTSIDE_STATES if cls == "forex" else (
                ("absent", None),
                ("future", dict(source="yfinance", last="2010")))
            H.instrument(symbol, cls)
            out[symbol] = self._states(symbol, cls, review, states)
        self.golden("m11_review", out)


# ── M12, M13: the conversion and the stress series (T10) ─────────────────

class TheConversionAndStressReplayTests(_Replay):

    def _bar(self, symbol, cls, close, *, hours_ago, timeframe="1h"):
        from market_data.models import PriceData
        PriceData.objects.create(
            instrument=H.instrument(symbol, cls), timeframe=timeframe,
            timestamp=self.clock.ago(hours_ago * 3600), open=close, high=close,
            low=close, close=close, volume=0, source="replay")

    def test_m12_the_conversion(self):
        from bot_program.asset_engine.forex_bot import quote_ccy_usd_rate
        H.instrument("EURUSD", "forex")
        out = {"without_a_bar": self._states(
            "EURUSD", "forex", lambda: quote_ccy_usd_rate("EUR"))}
        self._bar("EURUSD", "forex", Decimal("1.0900"), hours_ago=2)
        out["with_a_bar"] = self._states(
            "EURUSD", "forex", lambda: quote_ccy_usd_rate("EUR"))
        self.golden("m12_conversion", out)

    def test_m13_the_stress_series(self):
        from bot_program.market_stress import _daily_closes
        for i, close in enumerate(("1990", "1995", "2000")):
            self._bar("XAUUSD", "commodity", Decimal(close),
                      hours_ago=24 * (3 - i), timeframe="1d")
        states = (("absent", None),
                  ("fresh_future", dict(source="yfinance", last="2010")),
                  ("old_future", dict(source="yfinance", last="2010",
                                      age_s=7200)),
                  ("interim", dict(source="etoro", last="2005",
                                   bid="2004", ask="2006")))
        self.golden("m13_stress", self._states(
            "XAUUSD", "commodity", lambda: _daily_closes("XAUUSD")[-4:],
            states))


# ── M14, M15, M16: Morgul, the alerts, paper (T10) ───────────────────────

class TheWatchersReplayTests(_Replay):

    def _component(self, key, last_run=None):
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.update_or_create(
            key=key, defaults={"name": key, "category": "system",
                               "is_enabled": True, "last_run_at": last_run})

    def test_m14_morguls_heartbeat(self):
        from bot_program import morgul
        cfg = self._cfg("forex")
        cfg.symbols = ["EURUSD"]
        cfg.extras = {"last_tick_at": self.clock.ago(120).isoformat()}
        cfg.save(update_fields=["symbols", "extras"])
        self._component("platform_master")
        self._component("pipeline_asset_bots", last_run=self.clock.ago(120))
        H.instrument("EURUSD", "forex")

        def heartbeat():
            ctx = morgul.Context(self.clock.now, False)
            guard = morgul.GUARD["heartbeat"]
            return sorted([f.subject, f.title, f.facts]
                          for f in guard.check(ctx, guard))
        states = OUTSIDE_STATES + (
            ("old_stream", dict(source="oanda_stream", last="1.1002",
                                age_s=3 * 3600)),)
        self.golden("m14_morgul", self._states("EURUSD", "forex", heartbeat,
                                               states))

    def test_m15_price_alerts(self):
        from alerts.models import PriceAlert, check_price_alerts
        inst = H.instrument("EURUSD", "forex")
        alert = PriceAlert.objects.create(
            user=self._owner(), instrument=inst, condition="above",
            target_price=Decimal("1.1050"), notify_telegram=False,
            notify_email=False)

        def fire():
            PriceAlert.objects.filter(pk=alert.pk).update(
                triggered=False, triggered_at=None)
            check_price_alerts()
            return PriceAlert.objects.get(pk=alert.pk).triggered
        self.golden("m15_alerts", self._states("EURUSD", "forex", fire))

    def test_m16_paper(self):
        from bot_program.engine.paper_trader import PaperTrader
        cfg = self._cfg("forex")
        pt = PaperTrader(cfg)
        H.instrument("EURUSD", "forex")

        def paper():
            tk = pt.ticker("EURUSD")
            return {k: tk.get(k) for k in ("lastPrice", "bid", "ask",
                                           "market_shut")
                    if isinstance(tk, dict) and k in tk}
        self.golden("m16_paper", self._states("EURUSD", "forex", paper))


# ── M18, M19: the NL trader and the Orcs (T10) ───────────────────────────

class TheTraderAndOrcsReplayTests(_Replay):

    def test_m18_the_nl_trader(self):
        from bot_program.nl_trader import NLTradeParser
        from portfolio.models import Position
        owner = self._owner()
        H.instrument("EURUSD", "forex")

        def order():
            Position.objects.all().delete()
            r = NLTradeParser().execute(
                {"action": "buy", "symbol": "EURUSD", "confidence": 0.9,
                 "quantity": 1}, owner)
            pos = Position.objects.filter(closed_at__isnull=True).first()
            return {"status": r.get("status"), "message": r.get("message"),
                    "entry": None if pos is None else H.num(pos.entry_price)}
        self.golden("m18_nl_trader", self._states("EURUSD", "forex", order))

    def test_m19_the_orcs(self):
        from bot_program.orcs import (dossier, drum_bus, grading, situation,
                                      sources)
        t = self._row(meta=H.stamp("1.1000", age_s=1200, clock=self.clock))

        def orcs():
            src, age, m, q = dossier._mark(t, 1.1, self.clock.now)
            return {"quote": sources.quote("EURUSD"),
                    "quotes": sources.quotes(["EURUSD"]),
                    "drum_last": drum_bus._last("EURUSD"),
                    "usd_per_eur": grading._usd_per("EUR"),
                    "spread": list(situation._spread(t) or ()),
                    "dossier_mark": [src, age, m,
                                     getattr(q, "source", None)]}
        self.golden("m19_orcs", self._states("EURUSD", "forex", orcs))


# ── T21: the interim eToro writer and every reader of its row ────────────

class TheInterimWriterReplayTests(_Replay):

    def _readers(self, trade, symbol="EURUSD"):
        from bot_program.mark_sanity import second_opinion
        from bot_program.venue_mark import quote_stand_in
        from portfolio.services import _etoro_side
        q = H.live_quote(symbol)
        side = _etoro_side(trade, q, self.clock.now)
        return {"source": q.source if q else None,
                "last": H.num(q.last) if q else None,
                "second_opinion": second_opinion(symbol),
                "stand_in": quote_stand_in(symbol, q, carrier="etoro"),
                "pnl_tier2_side": (None if side is None
                                   else [H.num(side[0]), side[2]])}

    def test_t21_on_out_ranked_held_and_back(self):
        t = self._row(meta=H.stamp("1.1000", age_s=1200, clock=self.clock))
        steps = {}
        steps["interim_writes"] = H.write_live_quote(
            "EURUSD", source="etoro", last="1.1000", bid="1.0999",
            ask="1.1001", clock=self.clock)
        steps["after_interim"] = self._readers(t)
        steps["poller_refused"] = H.write_live_quote(
            "EURUSD", source="yfinance", last="1.1050", clock=self.clock)
        self.clock.advance(5)
        steps["stream_takes"] = H.write_live_quote(
            "EURUSD", source="oanda_stream", last="1.1002", bid="1.1001",
            ask="1.1003", clock=self.clock)
        steps["after_stream"] = self._readers(t)
        self.clock.advance(30)
        steps["interim_refused_while_held"] = H.write_live_quote(
            "EURUSD", source="etoro", last="1.1004", bid="1.1003",
            ask="1.1005", clock=self.clock)
        self.clock.advance(301)
        steps["interim_back_after_hold"] = H.write_live_quote(
            "EURUSD", source="etoro", last="1.1006", bid="1.1005",
            ask="1.1007", clock=self.clock)
        steps["after_hold"] = self._readers(t)
        from bot_program import venue_mark
        steps["resolve"] = H.mark_of(venue_mark.resolve(
            t, H.live_quote("EURUSD")))
        self.golden("t21", steps)

    def test_t21_on_an_index_cfd_whose_outside_quote_is_its_cash_index(self):
        """The stand-in check is waived only for the venue's own write:
        while the interim writer holds the row, eToro's quote values the
        CFD; once the poller takes the row back, its cash index is another
        instrument (stand-in "cash index") — and still mark sanity's second
        opinion (harm 2)."""
        from bot_program import venue_mark
        from market_data.public_feed import YF_SYMBOL_MAP
        with mock.patch.dict(YF_SYMBOL_MAP, {INDEX_CFD: CASH_INDEX}):
            t = self._row(INDEX_CFD, "index",
                          meta=H.stamp("5000", age_s=1200, clock=self.clock))
            steps = {}
            steps["interim_writes"] = H.write_live_quote(
                INDEX_CFD, source="etoro", last="5000", bid="4999",
                ask="5001", clock=self.clock, asset_class="index")
            steps["after_interim"] = self._readers(t, INDEX_CFD)
            steps["resolve_interim"] = H.mark_of(venue_mark.resolve(
                t, H.live_quote(INDEX_CFD)))
            steps["poller_refused"] = H.write_live_quote(
                INDEX_CFD, source="yfinance", last="4900", clock=self.clock,
                asset_class="index")
            self.clock.advance(301)
            steps["poller_takes_after_hold"] = H.write_live_quote(
                INDEX_CFD, source="yfinance", last="4900", clock=self.clock,
                asset_class="index")
            steps["after_poller"] = self._readers(t, INDEX_CFD)
            steps["resolve_poller"] = H.mark_of(venue_mark.resolve(
                t, H.live_quote(INDEX_CFD)))
            self.golden("t21_index", steps)


# ── T7: the weekend and the Sunday reopen, the venue's clock unpatched ───

class TheWeekendReplayTests(_Replay):

    PATCH_MARKET_SHUT = False
    #: Saturday 2026-11-07 12:00 UTC
    START = datetime(2026, 11, 7, 12, 0, tzinfo=dt_tz.utc)

    def _reads(self, trade, symbol, cls):
        from bot_program import venue_mark
        from bot_program.engine.paper_trader import PaperTrader
        shut = venue_mark.market_shut(trade)
        q = H.live_quote(symbol)
        tk = PaperTrader(trade.config).ticker(symbol)
        return {"market_shut": None if shut is None else {
                    k: _iso(v) for k, v in shut.items()},
                "answers": _answers(trade, q),
                "paper": {k: tk.get(k) for k in ("lastPrice", "market_shut")
                          if isinstance(tk, dict) and k in tk}}

    def test_t7_friday_close_weekend_and_sunday_reopen(self):
        friday_close = datetime(2026, 11, 6, 21, 55, tzinfo=dt_tz.utc)
        fx = self._row(meta={"venue_mark": {
            "price": 1.1, "at": friday_close.isoformat(), "source": "etoro",
            "via": "tick", "bid": 1.0999, "ask": 1.1001}})
        btc = self._row("BTCUSD", "crypto", meta=H.stamp(
            "50000", age_s=1800, clock=self.clock, bid="49990",
            ask="50010"))
        # the poller re-stamps Friday's close on Saturday
        H.write_live_quote("EURUSD", source="yfinance", last="1.1003",
                           clock=self.clock)
        H.write_live_quote("BTCUSD", source="binance_public", last="50100",
                           clock=self.clock, asset_class="crypto")
        out = {"saturday": {"EURUSD": self._reads(fx, "EURUSD", "forex"),
                            "BTCUSD": self._reads(btc, "BTCUSD", "crypto")}}
        # Sunday 22:02 UTC: the FX week has reopened, its settle running
        self.clock.now = datetime(2026, 11, 8, 22, 2, tzinfo=dt_tz.utc)
        out["sunday_reopen"] = {"EURUSD": self._reads(fx, "EURUSD", "forex")}
        self.golden("t7_weekend", out)


# ── T18: every eToro price dead — the CLOSE button and the kill switch ───

class TheDeadPricesReplayTests(_Replay):

    def test_m5_close_refuses_with_no_mark(self):
        from bot_program.manual_close import execute_close, preview_close
        t = self._row()
        etoro = H.EtoroTrader()
        with H.route_to(etoro):
            p = preview_close(t.config.user, t)
            out = execute_close(t.config.user, t, pin_ok=True)
        self.golden("m5_dead", {
            "preview": p.get("error"), "execute": out,
            "row": H.row_state(t), "requests": etoro.methods,
            "writes": etoro.writes_sent})

    def test_m5_close_with_a_rate_sends_and_waits(self):
        from bot_program.manual_close import execute_close
        t = self._row()
        etoro = H.EtoroTrader({"EURUSD": H.tick("1.0990")}, writes="accept")
        with H.route_to(etoro):
            out = execute_close(t.config.user, t, pin_ok=True)
        out["trade_id"] = out.get("trade_id") == t.id
        self.golden("m5_live", {"execute": out, "row": H.row_state(t),
                                "requests": etoro.methods,
                                "writes": etoro.writes_sent})

    def test_m6_the_kill_switch_sends_with_every_price_dead(self):
        """execute_kill_switch itself — its decorators, its sweep — with
        every eToro price dead: the close is sent all the same."""
        from bot_program.engine.kill_switch import execute_kill_switch
        from bot_program.models import AssetBotTrade
        out = {}
        for writes in ("fail", "accept"):
            AssetBotTrade.objects.all().delete()
            t = self._row(position_id=f"p-{writes}")
            etoro = H.EtoroTrader(writes=writes)
            with H.route_to(etoro):
                r = execute_kill_switch(self._owner(), reason="replay")
            out[writes] = {"closed": r["asset_positions_closed"],
                           "errors": len(r["errors"]),
                           "row": H.row_state(t),
                           "requests": etoro.methods,
                           "writes": etoro.writes_sent}
        self.golden("m6_kill_switch", out)


# ── M7, M8: the drain and the reconcile book an exit ─────────────────────

class TheBookingReplayTests(_Replay):

    def test_m7_the_drain_books_at_the_mark(self):
        from bot_program.pending_closes import retry_trade_close
        t = self._row(status="CLOSE_PENDING")
        etoro = H.EtoroTrader({"EURUSD": H.tick("1.0990")}, positions=[])
        with H.route_to(etoro):
            closed = retry_trade_close(t)
        self.golden("m7_drain", {"closed": closed, "row": H.row_state(t),
                                 "requests": etoro.methods,
                                 "writes": etoro.writes_sent})

    def test_m8_the_reconcile_books_an_outside_quote(self):
        from bot_program.models import AssetBotTrade
        from bot_program.reconcile_asset import _close_as_orphan

        def orphan():
            AssetBotTrade.objects.all().delete()
            t = self._row()
            etoro = H.EtoroTrader()
            with H.route_to(etoro):
                booked = _close_as_orphan(t)
            return {"booked": booked, "row": H.row_state(t),
                    "requests": etoro.methods}
        self.golden("m8_reconcile", self._states("EURUSD", "forex", orphan))


# ── M17: the daily-loss gate (T19) ───────────────────────────────────────

class TheGateReplayTests(_Replay):

    def test_t19_an_unpriced_exit_is_unmeasured(self):
        from portfolio.risk_gate import realized_since
        from portfolio.services import get_or_create_default_portfolio
        priced = self._row()
        unpriced = self._row(position_id="p-2")
        for row, pnl, meta in ((priced, Decimal("-50"), {}),
                               (unpriced, None,
                                {"exit_price_unavailable": True})):
            row.status = "CLOSED"
            row.exit_price = Decimal("1.0950")
            row.pnl = pnl
            row.closed_at = self.clock.ago(3600)
            row.metadata = {**row.metadata, **meta}
            row.save()
        r = realized_since(self.owner,
                           get_or_create_default_portfolio(user=self.owner))
        self.golden("t19_gate", {k: r.get(k) for k in (
            "realized", "live_realized", "live_n", "unmeasured", "n")})


# ── A15: with the feed absent and every switch OFF ───────────────────────

class TheDoorIsShutReplayTests(_Replay):

    def test_money_price_refuses_every_purpose(self):
        from market_data import venue_quotes as vq
        answers = {}
        for name, purpose in (("closing_buy", vq.closing("BUY")),
                              ("closing_sell", vq.closing("SELL")),
                              ("executable_buy", vq.executable("BUY")),
                              ("executable_sell", vq.executable("SELL")),
                              ("conversion_usd", vq.conversion("USD"))):
            a = vq.money_price("EURUSD", purpose, now=self.clock.now)
            answers[name] = getattr(a, "reason", "a price")
        self.golden("a15_door", answers)


# ── the completeness pins (§5.10) ────────────────────────────────────────

class TheRegistryIsCompleteTests(SimpleTestCase):

    def _runs(self):
        """Every golden run a scenario of this file produces."""
        import re
        src = Path(__file__).read_text(encoding="utf-8")
        return set(re.findall(r'self\.golden\(\s*"([a-z0-9_]+)"', src))

    def test_the_registry_is_the_specs_twenty(self):
        self.assertEqual(set(ADAPTERS), {"display"} | {
            f"M{i}" for i in range(1, 20)})

    def test_every_adapter_has_a_golden_run(self):
        runs = self._runs()
        for adapter, (_what, names) in ADAPTERS.items():
            with self.subTest(adapter=adapter):
                self.assertTrue(names, adapter)
                for name in names:
                    self.assertIn(name, GOLDEN, f"{adapter}: {name}")
                    self.assertIn(name, runs, f"{adapter}: {name}")

    def test_every_golden_run_is_registered_and_on_a_timeline(self):
        registered = {n for _w, names in ADAPTERS.values() for n in names}
        on_timeline = {n for v in TIMELINES.values() if isinstance(v, tuple)
                       for n in v[1]}
        for name in GOLDEN:
            with self.subTest(name=name):
                self.assertTrue(name in registered or name == "a15_door",
                                name)
                self.assertIn(name, on_timeline, name)
        self.assertEqual(set(GOLDEN), self._runs())

    def test_every_timeline_has_a_run_or_names_its_phase(self):
        phases = {"F1", "F2a", "F2b", "F3", "F4", "F6", "F9", "F10"}
        self.assertEqual({k for k in TIMELINES if k.startswith("T")},
                         {f"T{i}" for i in range(1, 25)})
        for timeline, entry in TIMELINES.items():
            with self.subTest(timeline=timeline):
                if isinstance(entry, tuple):
                    phase, names = entry
                    self.assertEqual(phase, "F1")
                    self.assertTrue(names)
                    for name in names:
                        self.assertIn(name, GOLDEN, f"{timeline}: {name}")
                else:
                    self.assertIn(entry, phases - {"F1"}, timeline)
