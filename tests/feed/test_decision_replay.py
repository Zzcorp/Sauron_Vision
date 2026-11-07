"""THE DECISION REPLAY: TODAY'S MONEY DECISIONS, GOLDEN (the eToro feed
spec, F1, §5.10, A6/A7/A15; 2026-11-07).

"Money direction: none. Replay proves equality with today." Each scenario
below runs the REAL consumer code of one money path (the registry of §5.10:
M1 tick, M2 mark sanity, M5 CLOSE, M6 kill switch, M7 drain, M8 reconcile,
M9 valuation and booking, M17 the daily-loss gate, the P&L display) on the
harness's fakes (tests/feed/harness.py) — a fixed clock, a fake eToro that
records every request and refuses every write it is not told to accept,
fake LiveQuote writers — and compares what it decided with GOLDEN: the
decisions main made on 2026-11-07, recorded BEFORE F1 touched a money
path. F1's source rule and its harm counters must leave every line equal.

The timelines are the §5.10 rows that exist before the feed does:
  T10  an outside quote absent, stale, disagreeing, agreeing, the venue's
       own, a stand-in;
  T18  every eToro price dead (the ticker raises);
  T19  an exit with no price across the daily-loss gate;
  T21  the interim eToro writer on, out-ranked by a stream, held, back;
and two named regressions: the stale-quote valuation gap (a real row
valued at another feed's quote of any age once its stamp is 15 minutes
old) and a future standing in for a CFD.

Every request the fake eToro saw is part of the golden decision, and no
scenario's write is accepted unless it says so. With the feed absent and
every switch OFF (A15), money_price refuses each purpose.

Recording: FEED_REPLAY_RECORD=1 prints each scenario's decisions instead of
asserting (how GOLDEN was made). Run with:
    python manage.py test tests.feed.test_decision_replay
"""
import json
import os
from types import SimpleNamespace
from unittest import mock

from django.test import TestCase

from tests.feed import harness as H

RECORD = os.environ.get("FEED_REPLAY_RECORD") == "1"

#: TODAY'S DECISIONS (recorded 2026-11-07 on main ede54d0, before F1
#: touched a money path: FEED_REPLAY_RECORD=1). A line changes only
#: with a money change, its switch and its own pull request.
GOLDEN = {'a15_door': {'closing_buy': 'switch_off',
              'closing_sell': 'switch_off',
              'conversion_usd': 'switch_off',
              'executable_buy': 'switch_off',
              'executable_sell': 'switch_off'},
 'm1_tick': {'confirmed': {'closed': 0,
                           'last_mark': 1.0801,
                           'row': {'exit_fill_source': 'mark',
                                   'exit_mark_age_s': None,
                                   'exit_price': None,
                                   'inferred': None,
                                   'pnl': '0',
                                   'status': 'CLOSE_PENDING',
                                   'unpriced': False},
                           'suspect': False},
             'inside_the_levels': {'closed': 0,
                                   'last_mark': 1.1,
                                   'row': {'exit_fill_source': None,
                                           'exit_mark_age_s': None,
                                           'exit_price': None,
                                           'inferred': None,
                                           'pnl': '0',
                                           'status': 'OPEN',
                                           'unpriced': False},
                                   'suspect': False},
             'jump_through_the_stop': {'closed': 0,
                                       'last_mark': 1.1,
                                       'row': {'exit_fill_source': None,
                                               'exit_mark_age_s': None,
                                               'exit_price': None,
                                               'inferred': None,
                                               'pnl': '0',
                                               'status': 'OPEN',
                                               'unpriced': False},
                                       'suspect': True},
             'requests': ['ticker', 'ticker', 'ticker', 'close_position']},
 'm2_jump': {'accepted': {'last_mark': 1.1,
                          'ok': True,
                          'suspect': False,
                          'why': ''},
             'confirmed': {'last_mark': 1.1101,
                           'ok': True,
                           'suspect': False,
                           'why': ''},
             'jump': {'last_mark': 1.1,
                      'ok': False,
                      'suspect': True,
                      'why': 'suspect mark: the mark 1.11 is 0.9% from the '
                             'last accepted 1.1 (bar 0.5%); print 1 of 2'}},
 'm2_stand_in': {'check': {'last_mark': None,
                           'ok': False,
                           'suspect': True,
                           'why': "suspect mark: the venue's mark 2000 is "
                                  "4.8% from the platform's quote 2100 "
                                  '(bar 2.0%)'},
                 'second_opinion': 2100.0},
 'm2_t10': {'absent': {'check': {'last_mark': 1.1,
                                 'ok': True,
                                 'suspect': False,
                                 'why': ''},
                       'second_opinion': None},
            'agreeing_stream': {'check': {'last_mark': 1.1,
                                          'ok': True,
                                          'suspect': False,
                                          'why': ''},
                                'second_opinion': 1.102},
            'disagreeing_poller': {'check': {'last_mark': None,
                                             'ok': False,
                                             'suspect': True,
                                             'why': 'suspect mark: the '
                                                    "venue's mark 1.1 is "
                                                    '0.9% from the '
                                                    "platform's quote 1.11 "
                                                    '(bar 0.5%)'},
                                   'second_opinion': 1.11},
            'disagreeing_stream': {'check': {'last_mark': None,
                                             'ok': False,
                                             'suspect': True,
                                             'why': 'suspect mark: the '
                                                    "venue's mark 1.1 is "
                                                    '0.9% from the '
                                                    "platform's quote 1.11 "
                                                    '(bar 0.5%)'},
                                   'second_opinion': 1.11},
            'stale_stream': {'check': {'last_mark': 1.1,
                                       'ok': True,
                                       'suspect': False,
                                       'why': ''},
                             'second_opinion': None},
            'venue_own_interim': {'check': {'last_mark': 1.1,
                                            'ok': True,
                                            'suspect': False,
                                            'why': ''},
                                  'second_opinion': None}},
 'm5_dead': {'execute': {'error': 'No usable price mark for EURUSD — the '
                                  'position is still OPEN rather than '
                                  'booked at a price nobody quoted',
                         'still_open': True},
             'preview': 'No usable price mark for EURUSD — closing now '
                        'would book the exit at a price nobody quoted',
             'requests': ['ticker', 'ticker'],
             'row': {'exit_fill_source': None,
                     'exit_mark_age_s': None,
                     'exit_price': None,
                     'inferred': None,
                     'pnl': '0',
                     'status': 'OPEN',
                     'unpriced': False},
             'writes': 0},
 'm5_live': {'execute': {'error': 'The broker rejected the close for '
                                  'EURUSD. The position is STILL OPEN at '
                                  'the broker; the row is CLOSE_PENDING '
                                  'and the retry task will keep trying '
                                  'every 5 minutes',
                         'pending': True,
                         'trade_id': True},
             'requests': ['ticker', 'close_position'],
             'row': {'exit_fill_source': 'mark',
                     'exit_mark_age_s': None,
                     'exit_price': None,
                     'inferred': None,
                     'pnl': '0',
                     'status': 'CLOSE_PENDING',
                     'unpriced': False}},
 'm6_dead': {'accept': {'raised': 'RuntimeError',
                        'requests': ['ticker',
                                     'get_positions',
                                     'close_position'],
                        'row': {'exit_fill_source': 'mark',
                                'exit_mark_age_s': None,
                                'exit_price': None,
                                'inferred': None,
                                'pnl': '0',
                                'status': 'CLOSE_PENDING',
                                'unpriced': False}},
             'fail': {'raised': 'FakeWriteRefused',
                      'requests': ['ticker',
                                   'get_positions',
                                   'close_position'],
                      'row': {'exit_fill_source': None,
                              'exit_mark_age_s': None,
                              'exit_price': None,
                              'inferred': None,
                              'pnl': '0',
                              'status': 'OPEN',
                              'unpriced': False}}},
 'm7_drain': {'closed': True,
              'requests': ['get_positions', 'ticker'],
              'row': {'exit_fill_source': 'mark',
                      'exit_mark_age_s': None,
                      'exit_price': '1.099',
                      'inferred': None,
                      'pnl': '-0.001',
                      'status': 'CLOSED',
                      'unpriced': False}},
 'm8_reconcile': {'booked': True,
                  'requests': ['ticker'],
                  'row': {'exit_fill_source': 'mark',
                          'exit_mark_age_s': None,
                          'exit_price': '1.098',
                          'inferred': True,
                          'pnl': '-0.002',
                          'status': 'CLOSED',
                          'unpriced': False}},
 'm9_gap': {'fresh_stamp': {'bookable': True,
                            'for_booking': {'age_s': 60,
                                            'price': '1.0999',
                                            'source': 'venue',
                                            'stand_in': ''},
                            'resolve': {'age_s': 60,
                                        'price': '1.0999',
                                        'source': 'venue',
                                        'stand_in': ''}},
            'quote_newer_than_stamp': {'bookable': True,
                                       'for_booking': {'age_s': 600,
                                                       'price': '1.105',
                                                       'source': 'quote',
                                                       'stand_in': ''},
                                       'resolve': {'age_s': 600,
                                                   'price': '1.105',
                                                   'source': 'quote',
                                                   'stand_in': ''}},
            'quote_older_than_stamp': {'bookable': True,
                                       'for_booking': {'age_s': 1200,
                                                       'price': '1.0999',
                                                       'source': 'venue_stale',
                                                       'stand_in': ''},
                                       'resolve': {'age_s': 1200,
                                                   'price': '1.0999',
                                                   'source': 'venue_stale',
                                                   'stand_in': ''}}},
 'm9_stand_in': {'answers': {'bookable': False,
                             'for_booking': None,
                             'resolve': {'age_s': 7200,
                                         'price': '2000',
                                         'source': 'venue_stale',
                                         'stand_in': 'future'}},
                 'no_stamp': {'bookable': False,
                              'for_booking': None,
                              'resolve': {'age_s': None,
                                          'price': None,
                                          'source': 'awaiting_venue',
                                          'stand_in': 'future'}}},
 't19_gate': {'live_n': 1,
              'live_realized': -50.0,
              'n': 1,
              'realized': -50.0,
              'unmeasured': 1},
 't21': {'after_hold': {'last': '1.1006',
                        'pnl_tier2_side': ['1.1005', 'bid'],
                        'second_opinion': None,
                        'source': 'etoro',
                        'stand_in_waived': True},
         'after_interim': {'last': '1.1',
                           'pnl_tier2_side': ['1.0999', 'bid'],
                           'second_opinion': None,
                           'source': 'etoro',
                           'stand_in_waived': True},
         'after_stream': {'last': '1.1002',
                          'pnl_tier2_side': None,
                          'second_opinion': 1.1002,
                          'source': 'oanda_stream',
                          'stand_in_waived': True},
         'interim_back_after_hold': True,
         'interim_refused_while_held': False,
         'interim_writes': True,
         'poller_refused': False,
         'resolve': {'age_s': 0,
                     'price': '1.1006',
                     'source': 'quote',
                     'stand_in': ''},
         'stream_takes': True}}


class _Replay(TestCase):

    def setUp(self):
        self.clock = H.FakeClock()
        self.clock.__enter__()
        self.addCleanup(self.clock.__exit__, None, None, None)
        # every scenario's market reads OPEN on the venue's own clock
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

    def _row(self, symbol="EURUSD", cls="forex", **kw):
        if not hasattr(self, "owner"):
            self.owner = H.user("replay_owner")
            self.cfgs = {}
        if cls not in self.cfgs:
            self.cfgs[cls] = H.live_config(self.owner, cls)
        H.instrument(symbol, cls)
        defaults = {"forex": dict(entry="1.1000", stop="1.0900",
                                  target="1.1200"),
                    "commodity": dict(entry="2000", stop="1950",
                                      target="2100"),
                    "crypto": dict(entry="50000", stop="48000",
                                   target="54000")}[cls]
        defaults.update(kw)
        return H.real_row(self.cfgs[cls], symbol, **defaults)


# ── M9: valuation and booking (resolve, bookable, for_booking) ───────────

class TheValuationReplayTests(_Replay):

    def _answers(self, trade, quote):
        from bot_program import venue_mark
        mk = venue_mark.resolve(trade, quote)
        return {"resolve": H.mark_of(mk),
                "bookable": venue_mark.bookable(mk, trade),
                "for_booking": H.mark_of(venue_mark.for_booking(trade,
                                                                quote))}

    def test_m9_the_stale_quote_gap(self):
        """A real row whose eToro stamp is 20 minutes old is valued at
        another feed's quote, of any age, provided it is not older than
        the stamp (harm 6); an older quote leaves the stale stamp."""
        out = {}
        t = self._row(meta=H.stamp("1.1000", age_s=1200, clock=self.clock,
                                   bid="1.0999", ask="1.1001"))
        H.write_live_quote("EURUSD", source="yfinance", last="1.1050",
                           clock=self.clock, age_s=600)
        out["quote_newer_than_stamp"] = self._answers(t, H.live_quote(
            "EURUSD"))
        H.write_live_quote("EURUSD", source="yfinance", last="1.1050",
                           clock=self.clock, age_s=3 * 3600)
        out["quote_older_than_stamp"] = self._answers(t, H.live_quote(
            "EURUSD"))
        fresh = self._row(meta=H.stamp("1.1000", age_s=60, clock=self.clock,
                                       bid="1.0999", ask="1.1001"))
        out["fresh_stamp"] = self._answers(fresh, H.live_quote("EURUSD"))
        self.golden("m9_gap", out)

    def test_m9_a_future_stands_in_for_a_cfd(self):
        out = {}
        t = self._row("XAUUSD", "commodity",
                      meta=H.stamp("2000", age_s=7200, clock=self.clock))
        H.write_live_quote("XAUUSD", source="yfinance", last="2010",
                           clock=self.clock, asset_class="commodity")
        q = H.live_quote("XAUUSD")
        out["answers"] = self._answers(t, q)
        bare = self._row("XAUUSD", "commodity")
        out["no_stamp"] = self._answers(bare, q)
        self.golden("m9_stand_in", out)


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
        states = (
            ("absent", None),
            ("stale_stream", dict(source="oanda_stream", last="1.1100",
                                  age_s=1000)),
            ("disagreeing_stream", dict(source="oanda_stream",
                                        last="1.1100")),
            ("agreeing_stream", dict(source="oanda_stream", last="1.1020")),
            ("venue_own_interim", dict(source="etoro", last="1.1100")),
            ("disagreeing_poller", dict(source="yfinance", last="1.1100")),
        )
        out = {}
        for name, quote in states:
            from market_data.models import LiveQuote
            LiveQuote.objects.filter(instrument__symbol="EURUSD").delete()
            if quote:
                H.write_live_quote("EURUSD", clock=self.clock, **quote)
            t = self._row()
            out[name] = {"second_opinion": second_opinion("EURUSD"),
                         "check": self._check(t, 1.1)}
        self.golden("m2_t10", out)

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


# ── T21: the interim eToro writer and every reader of its row ────────────

class TheInterimWriterReplayTests(_Replay):

    def _readers(self, trade):
        from bot_program.mark_sanity import second_opinion
        from bot_program.venue_mark import quote_stand_in
        from portfolio.services import _etoro_side
        q = H.live_quote("EURUSD")
        side = _etoro_side(trade, q, self.clock.now)
        return {"source": q.source if q else None,
                "last": H.num(q.last) if q else None,
                "second_opinion": second_opinion("EURUSD"),
                "stand_in_waived": quote_stand_in("EURUSD", q,
                                                  carrier="etoro") == "",
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
            "writes": len(etoro.writes_sent)})

    def test_m5_close_with_a_rate_sends_and_waits(self):
        from bot_program.manual_close import execute_close
        t = self._row()
        etoro = H.EtoroTrader({"EURUSD": H.tick("1.0990")}, writes="accept")
        with H.route_to(etoro):
            out = execute_close(t.config.user, t, pin_ok=True)
        out["trade_id"] = out.get("trade_id") == t.id
        self.golden("m5_live", {"execute": out, "row": H.row_state(t),
                                "requests": etoro.methods})

    def test_m6_kill_switch_sends_with_every_price_dead(self):
        from bot_program.engine.kill_switch import _close_asset_trade
        out = {}
        for writes in ("fail", "accept"):
            t = self._row(position_id=f"p-{writes}")
            etoro = H.EtoroTrader(writes=writes)
            raised = None
            with H.route_to(etoro):
                try:
                    _close_asset_trade(t, self.clock.now)
                except Exception as e:  # noqa: BLE001 — the decision
                    raised = type(e).__name__
            out[writes] = {"raised": raised, "row": H.row_state(t),
                           "requests": etoro.methods}
        self.golden("m6_dead", out)


# ── M7, M8: the drain and the reconcile book an exit ─────────────────────

class TheBookingReplayTests(_Replay):

    def test_m7_the_drain_books_at_the_mark(self):
        from bot_program.pending_closes import retry_trade_close
        t = self._row(status="CLOSE_PENDING")
        etoro = H.EtoroTrader({"EURUSD": H.tick("1.0990")}, positions=[])
        with H.route_to(etoro):
            closed = retry_trade_close(t)
        self.golden("m7_drain", {"closed": closed, "row": H.row_state(t),
                                 "requests": etoro.methods})

    def test_m8_the_reconcile_books_an_outside_quote(self):
        from bot_program.reconcile_asset import _close_as_orphan
        t = self._row()
        H.write_live_quote("EURUSD", source="oanda_stream", last="1.0980",
                           bid="1.0979", ask="1.0981", clock=self.clock)
        etoro = H.EtoroTrader()
        with H.route_to(etoro):
            booked = _close_as_orphan(t)
        self.golden("m8_reconcile", {"booked": booked, "row": H.row_state(t),
                                     "requests": etoro.methods})


# ── M17: the daily-loss gate (T19) ───────────────────────────────────────

class TheGateReplayTests(_Replay):

    def test_t19_an_unpriced_exit_is_unmeasured(self):
        from decimal import Decimal

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
