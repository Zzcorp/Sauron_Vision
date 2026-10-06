"""THE ENTRY TIMING (2026-10-06, the operator asked for more resilience and
smartness in taking positions): no new entry in the minutes when the price
is not a market price, and no attack into a scheduled print.

  ROLLOVER      forex, commodities, indices: ROLLOVER_NY, New York time.
  OPEN SETTLE   the first OPEN_SETTLE_MINUTES after any modelled open —
                for forex, the first quarter hour of the week.
  CLOSE GUARD   a stock or ETF in the last CLOSE_GUARD_MINUTES before its
                exchange closes (early closes kept); every class that shuts,
                in Friday's last hour before the weekend.
  THE PRINT     position_care.event_for's window at entry.
  THE ATTACK    a print within EVENT_ATTACK_HOURS caps the tier at STANDARD.

The bot lane refuses (skips.BAD_TIMING) at the proposal and again before
the order; the TAKE TRADE ticket warns and stays pressable. The suite runs
with the gate OFF (tests/__init__.py); these tests turn it on at a fixed
clock.

Run with:  python manage.py test tests.test_entry_timing
"""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from bot_program import entry_timing as et

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _ny(y, m, d, hh, mm):
    """An aware instant from New York wall time (DST follows)."""
    return datetime(y, m, d, hh, mm, tzinfo=NY).astimezone(UTC)


def _ev(now, minutes, title="CPI", currency="USD", earnings=False):
    return {"at": now + timedelta(minutes=minutes), "title": title,
            "currency": currency, "earnings": earnings}


def _on():
    return mock.patch.object(et, "GATE", True)


# a Tuesday in winter (New York = UTC-5) and one in summer (UTC-4)
WINTER_TUE = (2026, 1, 13)
SUMMER_TUE = (2026, 7, 14)
WINTER_FRI = (2026, 1, 16)


class TheConstantsTests(SimpleTestCase):

    def test_the_windows(self):
        from datetime import time as dtime
        self.assertEqual(et.ROLLOVER_NY, (dtime(16, 50), dtime(17, 10)))
        self.assertEqual(et.ROLLOVER_CLASSES,
                         frozenset({"forex", "commodity", "index"}))
        self.assertEqual((et.OPEN_SETTLE_MINUTES, et.CLOSE_GUARD_MINUTES),
                         (15, 10))
        self.assertEqual(et.CLOSE_GUARD_CLASSES, frozenset({"stock", "etf"}))
        self.assertEqual((et.EVENT_ATTACK_HOURS, et.EVENT_ATTACK_CAP),
                         (3, "STANDARD"))

    def test_the_suite_runs_with_the_gate_off_and_off_is_open(self):
        self.assertFalse(et.GATE)
        v = et.verdict("EURUSD", "forex", now=_ny(*WINTER_TUE, 16, 55),
                       events=[_ev(_ny(*WINTER_TUE, 16, 55), 10)])
        self.assertEqual(v, {"ok": True, "code": "", "why": "", "until": None,
                             "attack": None})


class TheRolloverTests(SimpleTestCase):

    def test_forex_commodities_and_indices_in_the_window_winter_and_summer(self):
        with _on():
            for day in (WINTER_TUE, SUMMER_TUE):
                for cls, sym in (("forex", "EURUSD"), ("commodity", "XAUUSD"),
                                 ("index", "SPX500")):
                    with self.subTest(day=day, cls=cls):
                        v = et.verdict(sym, cls, now=_ny(*day, 16, 55),
                                       events=[])
                        self.assertFalse(v["ok"])
                        self.assertEqual(v["code"], et.ROLLOVER)
                        self.assertIn("rolls over at 17:00 New York", v["why"])
                        # a commodity clears when CME reopens from its
                        # 16:00-17:00 CT break (18:00 New York) and settles
                        from datetime import time as dtime
                        want = (dtime(18, 15) if cls == "commodity"
                                else et.ROLLOVER_NY[1])
                        self.assertEqual(v["until"].astimezone(NY).time(),
                                         want)

    def test_the_edges_and_the_classes_that_do_not_roll(self):
        with _on():
            self.assertTrue(et.verdict("EURUSD", "forex",
                                       now=_ny(*WINTER_TUE, 16, 49),
                                       events=[])["ok"])
            self.assertTrue(et.verdict("EURUSD", "forex",
                                       now=_ny(*WINTER_TUE, 17, 10),
                                       events=[])["ok"])
            self.assertEqual(et.verdict("EURUSD", "forex",
                                        now=_ny(*WINTER_TUE, 17, 9),
                                        events=[])["code"], et.ROLLOVER)
            # crypto never rolls; a stock at 16:55 New York is a shut
            # market, which is nobody's business here
            self.assertTrue(et.verdict("BTCUSD", "crypto",
                                       now=_ny(*WINTER_TUE, 16, 55),
                                       events=[])["ok"])
            self.assertTrue(et.verdict("AAPL", "stock", exchange="NASDAQ",
                                       now=_ny(*WINTER_TUE, 16, 55),
                                       events=[])["ok"])


class TheRolloverOnAShutVenueTests(SimpleTestCase):
    """Review 2026-10-06: the rollover answers while the venue is in its
    own break, so the hour it clears is the venue's reopening plus its
    settling quarter hour, never the window's end inside a shut venue."""

    def test_cme_metals_clear_after_the_daily_break_and_its_settle(self):
        # Tuesday 17:05 New York: CME is in its 16:00-17:00 CT break and
        # reopens at 17:00 CT = 18:00 New York = 23:00 UTC in winter
        with _on():
            v = et.verdict("XAUUSD", "commodity", exchange="COMEX",
                           now=_ny(*WINTER_TUE, 17, 5), events=[])
        self.assertEqual(v["code"], et.ROLLOVER)
        self.assertEqual(v["until"],
                         datetime(2026, 1, 13, 23, 15, tzinfo=UTC))
        self.assertIn("resume Tuesday 23:15 UTC, once the venue reopens "
                      "and settles", v["why"])

    def test_a_venue_open_at_the_windows_end_keeps_it(self):
        with _on():
            v = et.verdict("EURUSD", "forex", exchange="FOREX",
                           now=_ny(*WINTER_TUE, 16, 55), events=[])
        self.assertEqual(v["until"], _ny(*WINTER_TUE, 17, 10))
        self.assertNotIn("once the venue reopens", v["why"])

    def test_the_hour_comes_first_in_the_words(self):
        """why_no_trade prints 88 characters of a skip's detail."""
        with _on():
            roll = et.verdict("EURUSD", "forex", exchange="FOREX",
                              now=_ny(*WINTER_TUE, 16, 55), events=[])
            settle = et.verdict("AAPL", "stock", exchange="NASDAQ",
                                now=_ny(*WINTER_TUE, 9, 40), events=[])
        self.assertIn("resume Tuesday 22:10 UTC", roll["why"][:88])
        self.assertIn("resume Tuesday 14:45 UTC", settle["why"][:88])

    def test_an_unreadable_advisory_is_logged(self):
        with mock.patch.object(et, "verdict", side_effect=RuntimeError("x")), \
                self.assertLogs("bot_program.entry_timing", level="WARNING"):
            self.assertTrue(et.advisory("EURUSD", "forex")["ok"])


class TheOpenSettleTests(SimpleTestCase):

    def test_the_first_quarter_hour_of_a_stock_session(self):
        with _on():
            v = et.verdict("AAPL", "stock", exchange="NASDAQ",
                           now=_ny(*WINTER_TUE, 9, 40), events=[])
            self.assertFalse(v["ok"])
            self.assertEqual(v["code"], et.OPEN_SETTLE)
            self.assertIn("opened at Tuesday 14:30 UTC", v["why"])
            self.assertIn("resume Tuesday 14:45 UTC", v["why"])
            self.assertEqual(v["until"], _ny(*WINTER_TUE, 9, 45))
            self.assertTrue(et.verdict("AAPL", "stock", exchange="NASDAQ",
                                       now=_ny(*WINTER_TUE, 9, 45),
                                       events=[])["ok"])

    def test_the_first_quarter_hour_of_the_forex_week(self):
        # Sunday 2026-01-18: the week opens at 17:00 New York = 22:00 UTC
        with _on():
            v = et.verdict("EURUSD", "forex", exchange="FOREX",
                           now=datetime(2026, 1, 18, 22, 5, tzinfo=UTC),
                           events=[])
            self.assertEqual(v["code"], et.OPEN_SETTLE)
            self.assertIn("Sunday 22:00 UTC", v["why"])
            self.assertTrue(et.verdict("EURUSD", "forex", exchange="FOREX",
                                       now=datetime(2026, 1, 18, 22, 20,
                                                    tzinfo=UTC),
                                       events=[])["ok"])

    def test_a_shut_market_is_not_judged_here(self):
        with _on():
            # Saturday forex, a stock at 03:00 New York
            self.assertTrue(et.verdict("EURUSD", "forex", exchange="FOREX",
                                       now=datetime(2026, 1, 17, 12, 0,
                                                    tzinfo=UTC),
                                       events=[])["ok"])
            self.assertTrue(et.verdict("AAPL", "stock", exchange="NASDAQ",
                                       now=_ny(*WINTER_TUE, 3, 0),
                                       events=[])["ok"])


class TheCloseGuardTests(SimpleTestCase):

    def test_the_last_ten_minutes_of_a_stock_session(self):
        with _on():
            v = et.verdict("AAPL", "stock", exchange="NASDAQ",
                           now=_ny(*WINTER_TUE, 15, 55), events=[])
            self.assertFalse(v["ok"])
            self.assertEqual(v["code"], et.CLOSE_GUARD)
            self.assertIn("closes at Tuesday 21:00 UTC", v["why"])
            self.assertEqual(v["until"], _ny(*WINTER_TUE, 16, 0))
            self.assertTrue(et.verdict("AAPL", "stock", exchange="NASDAQ",
                                       now=_ny(*WINTER_TUE, 15, 45),
                                       events=[])["ok"])
            # an ETF on the NYSE, same rule; a forex pair has no daily close
            self.assertEqual(et.verdict("SPY", "etf", exchange="NYSE",
                                        now=_ny(*WINTER_TUE, 15, 55),
                                        events=[])["code"], et.CLOSE_GUARD)
            self.assertTrue(et.verdict("EURUSD", "forex", exchange="FOREX",
                                       now=_ny(*WINTER_TUE, 15, 55),
                                       events=[])["ok"])

    def test_an_early_close_is_kept(self):
        # Friday 2026-11-27, the 13:00 New York early close
        with _on():
            v = et.verdict("AAPL", "stock", exchange="NASDAQ",
                           now=_ny(2026, 11, 27, 12, 55), events=[])
            self.assertEqual(v["code"], et.CLOSE_GUARD)
            self.assertIn("closes at Friday 18:00 UTC", v["why"])
            # after it the market is shut: not judged here
            self.assertTrue(et.verdict("AAPL", "stock", exchange="NASDAQ",
                                       now=_ny(2026, 11, 27, 13, 5),
                                       events=[])["ok"])

    def test_fridays_last_hour_before_the_weekend(self):
        with _on():
            v = et.verdict("EURUSD", "forex", exchange="FOREX",
                           now=_ny(*WINTER_FRI, 16, 0), events=[])
            self.assertEqual(v["code"], et.WEEKEND)
            self.assertIn("Friday's last hour before the weekend", v["why"])
            # Friday 16:50-17:00 is the weekend window's, never a rollover
            # that would name a resume hour inside the shut weekend
            v = et.verdict("EURUSD", "forex", exchange="FOREX",
                           now=_ny(*WINTER_FRI, 16, 55), events=[])
            self.assertEqual(v["code"], et.WEEKEND)
            self.assertNotIn("resume Friday", v["why"])
            self.assertIsNone(et.rollover(_ny(*WINTER_FRI, 16, 55), "forex"))
            self.assertIsNone(et.rollover(_ny(2026, 7, 17, 16, 55), "index"))
            # a stock: 15:00-16:00 New York on Friday
            self.assertEqual(et.verdict("AAPL", "stock", exchange="NASDAQ",
                                        now=_ny(*WINTER_FRI, 15, 10),
                                        events=[])["code"], et.WEEKEND)
            self.assertTrue(et.verdict("AAPL", "stock", exchange="NASDAQ",
                                       now=_ny(*WINTER_FRI, 14, 50),
                                       events=[])["ok"])
            # Thursday at the same hour: nothing
            self.assertTrue(et.verdict("EURUSD", "forex", exchange="FOREX",
                                       now=_ny(2026, 1, 15, 16, 0),
                                       events=[])["ok"])


class ThePrintTests(SimpleTestCase):

    def setUp(self):
        self.now = _ny(*WINTER_TUE, 10, 0)

    def test_a_print_in_the_window_refuses_with_the_cares_matching(self):
        with _on():
            v = et.verdict("EURUSD", "forex", now=self.now,
                           events=[_ev(self.now, 30)])
            self.assertFalse(v["ok"])
            self.assertEqual(v["code"], et.EVENT)
            self.assertIn("high-impact print CPI in 30 min", v["why"])
            self.assertIn("60 min before to 15 min after", v["why"])
            self.assertEqual(v["until"], self.now + timedelta(minutes=45))
            # the minutes after, too
            self.assertEqual(et.verdict("EURUSD", "forex", now=self.now,
                                        events=[_ev(self.now, -10)])["code"],
                             et.EVENT)
            # a currency the pair does not carry: nothing
            self.assertTrue(et.verdict("GBPJPY", "forex", now=self.now,
                                       events=[_ev(self.now, 30)])["ok"])
            # the home currency reaches a stock and a crypto row
            self.assertEqual(et.verdict("AAPL", "stock", exchange="NASDAQ",
                                        now=self.now,
                                        events=[_ev(self.now, 30)])["code"],
                             et.EVENT)
            self.assertEqual(et.verdict("BTCUSD", "crypto", now=self.now,
                                        events=[_ev(self.now, 30)])["code"],
                             et.EVENT)

    def test_a_print_within_three_hours_caps_the_attack(self):
        with _on():
            v = et.verdict("EURUSD", "forex", now=self.now,
                           events=[_ev(self.now, 120)])
            self.assertTrue(v["ok"])
            self.assertEqual(v["attack"]["cap"], "STANDARD")
            self.assertIn("attack capped at STANDARD: CPI in 120 min",
                          v["attack"]["why"])
            # past three hours: no cap; another currency: no cap
            self.assertIsNone(et.verdict("EURUSD", "forex", now=self.now,
                                         events=[_ev(self.now, 200)])["attack"])
            self.assertIsNone(et.verdict("GBPJPY", "forex", now=self.now,
                                         events=[_ev(self.now, 120)])["attack"])
            self.assertIn("in 2.5 h", et.verdict(
                "AAPL", "stock", exchange="NASDAQ", now=self.now,
                events=[_ev(self.now, 150)])["attack"]["why"])

    def test_a_stocks_own_earnings_refuse(self):
        with _on():
            v = et.verdict("AAPL", "stock", exchange="NASDAQ", now=self.now,
                           events=[_ev(self.now, 20 * 60, title="AAPL earnings",
                                       currency="AAPL", earnings=True)])
            self.assertEqual(v["code"], et.EVENT)
            self.assertIn("AAPL earnings in 20 h", v["why"])
            self.assertIn("own earnings within 24 h", v["why"])
            # another stock's earnings: nothing
            self.assertTrue(et.verdict("MSFT", "stock", exchange="NASDAQ",
                                       now=self.now,
                                       events=[_ev(self.now, 20 * 60,
                                                   title="AAPL earnings",
                                                   currency="AAPL",
                                                   earnings=True)])["ok"])

    def test_options_are_never_judged(self):
        with _on():
            self.assertTrue(et.verdict("AAPL", "options", now=self.now,
                                       events=[_ev(self.now, 30)])["ok"])

    def test_the_clock_comes_before_the_calendar(self):
        with _on():
            v = et.verdict("EURUSD", "forex", now=_ny(*WINTER_TUE, 16, 55),
                           events=[_ev(_ny(*WINTER_TUE, 16, 55), 30)])
            self.assertEqual(v["code"], et.ROLLOVER)


class NothingUnreadableRefusesTests(SimpleTestCase):

    def test_an_unreadable_clock_or_calendar_refuses_nothing(self):
        with _on(), \
                mock.patch("core.exchange_status.market_clock",
                           side_effect=RuntimeError("no clock")), \
                self.assertLogs("bot_program.entry_timing", level="WARNING"):
            v = et.verdict("AAPL", "stock", exchange="NASDAQ",
                           now=_ny(*WINTER_TUE, 9, 40), events=[])
        self.assertTrue(v["ok"])
        with _on(), \
                mock.patch("bot_program.position_care.event_for",
                           side_effect=RuntimeError("no calendar")), \
                self.assertLogs("bot_program.entry_timing", level="WARNING"):
            v = et.verdict("EURUSD", "forex", now=_ny(*WINTER_TUE, 10, 0),
                           events=[_ev(_ny(*WINTER_TUE, 10, 0), 30)])
        self.assertTrue(v["ok"])

    def test_the_advisory_shape(self):
        with _on():
            adv = et.advisory("EURUSD", "forex", now=_ny(*WINTER_TUE, 16, 55))
            self.assertFalse(adv["ok"])
            self.assertIn("rolls over", adv["reason"])
            self.assertEqual(adv["attack"], "")
        with mock.patch.object(et, "verdict", side_effect=RuntimeError("x")):
            self.assertEqual(et.advisory("EURUSD", "forex"),
                             {"ok": True, "reason": "", "attack": ""})


# ── the calendar read, three hours deep ───────────────────────────────────

class TheCalendarHorizonTests(TestCase):

    def setUp(self):
        from market_data.models import EconomicEvent
        self.now = timezone.now()
        for minutes, title in ((30, "CPI"), (120, "FOMC"), (400, "Far")):
            EconomicEvent.objects.create(
                title=title, country="US", datetime=self.now + timedelta(
                    minutes=minutes), impact="high", currency_affected="USD",
                source="forexfactory")

    def test_the_default_window_and_the_deep_read_cache_apart(self):
        from bot_program import position_care as pc
        cache = {}
        near = pc.upcoming_events(self.now, cache=cache)
        self.assertEqual([e["title"] for e in near], ["CPI"])
        deep = pc.upcoming_events(self.now, cache=cache, horizon_minutes=180)
        self.assertEqual([e["title"] for e in deep], ["CPI", "FOMC"])
        self.assertEqual(set(cache), {pc.EVENT_CACHE_KEY,
                                      f"{pc.EVENT_CACHE_KEY}:180"})
        row = SimpleNamespace(symbol="EURUSD", asset_class="forex")
        self.assertEqual(pc.event_for(row, self.now, deep)["title"], "CPI")
        self.assertEqual(pc.event_for(row, self.now, deep[1:],
                                      before_minutes=180)["title"], "FOMC")
        self.assertIsNone(pc.event_for(row, self.now, deep[1:]))

    def test_the_verdict_reads_the_calendar_itself_when_given_none(self):
        with _on():
            v = et.verdict("EURUSD", "forex", now=self.now, cache={})
            self.assertEqual(v["code"], et.EVENT)
            self.assertIn("CPI in 30 min", v["why"])


# ── the bot lane ──────────────────────────────────────────────────────────

REFUSED = {"ok": False, "code": "ROLLOVER", "why": "the forex market rolls "
           "over at 17:00 New York — new entries resume Tuesday 22:10 UTC",
           "until": None, "attack": None}
CAPPED = {"ok": True, "code": "", "why": "", "until": None,
          "attack": {"cap": "STANDARD",
                     "why": "attack capped at STANDARD: CPI in 120 min, "
                            "inside 3 h of a print"}}


class TheProposalIsRefusedOnTheClockTests(TestCase):

    def setUp(self):
        from tests.test_entry_quote import _book, _instrument, _live_cfg, _signal, _user
        from instruments.models import Instrument
        self.user = _user("tm_prop")
        self.cfg = _live_cfg(self.user, name="TM")
        inst = _instrument()
        # the venue travels with the symbol: the gate is asked on the
        # INSTRUMENT's class and exchange, the router's own key
        Instrument.objects.filter(pk=inst.pk).update(exchange="NASDAQ")
        _signal(inst, rule="tm_rule")
        _book(self.user)

    def _propose(self, verdict):
        from tests.test_entry_quote import ROUTER, _mock_client
        from bot_program.asset_engine.stock_bot import StockBot
        self.bot = StockBot(self.cfg)
        client = _mock_client("100.00")
        client.ticker.return_value = {"lastPrice": "100.00", "bid": "99.98",
                                      "ask": "100.02", "symbol": "AAPL"}
        with mock.patch(ROUTER, return_value=client), \
                mock.patch("bot_program.entry_timing.verdict",
                           return_value=verdict) as v:
            cand = self.bot.propose_entry("AAPL")
        return cand, v

    def test_a_refusal_is_a_bad_timing_skip_before_the_levels(self):
        from bot_program.asset_engine import skips
        with mock.patch("bot_program.asset_engine.risk_levels.stop_and_target"
                        ) as levels, \
                self.assertLogs("bot_program.asset_engine.base",
                                level="WARNING") as caught:
            cand, v = self._propose(REFUSED)
        self.assertIsNone(cand)
        levels.assert_not_called()
        self.assertIn("entry refused on the clock", "\n".join(caught.output))
        self.assertEqual(v.call_args.args[:2], ("AAPL", "stock"))
        self.assertEqual(v.call_args.kwargs["exchange"], "NASDAQ")
        self.cfg.refresh_from_db()
        note = skips.last_by_symbol(self.cfg)["AAPL"]
        self.assertEqual(note["code"], skips.BAD_TIMING)
        self.assertIn("rolls over at 17:00 New York", note["detail"])
        self.assertEqual(self.bot._timing_verdict["AAPL"], REFUSED)

    def test_an_open_verdict_proposes(self):
        cand, _v = self._propose({"ok": True, "code": "", "why": "",
                                  "until": None, "attack": None})
        self.assertIsNotNone(cand)


class TheAttackIsCappedBeforeAPrintTests(TestCase):

    def setUp(self):
        from bot_program.asset_engine.stock_bot import StockBot
        from tests.test_attack_mode import _instrument, _live_cfg, _user
        self.user = _user("tm_cap")
        _instrument("AAPL", "stock")
        self.cfg = _live_cfg(self.user, name="TMC")
        self.cfg.extras = {"leverage": "auto", "risk_per_trade_pct": 7}
        self.cfg.save(update_fields=["extras"])
        self.bot = StockBot(self.cfg)

    def _tier(self, score, verdict):
        from tests.test_attack_mode import DETAIL, _decision, _record
        self.bot._timing_verdict = {"AAPL": verdict}
        with mock.patch(DETAIL, return_value=_record(40, 0.60, 0.35)):
            return self.bot._attack_tier("AAPL", _decision(score))

    def test_a_strong_or_high_score_is_held_at_standard(self):
        for score in (0.80, 0.95):
            with self.subTest(score=score):
                out = self._tier(score, CAPPED)
                self.assertEqual((out["tier"], out["capped"]),
                                 ("STANDARD", True))
                self.assertAlmostEqual(out["risk_fraction"], 0.035)
                self.assertIn("attack capped at STANDARD: CPI in 120 min",
                              out["why"])

    def test_nothing_changes_without_a_cap_or_on_a_standard_score(self):
        out = self._tier(0.95, {"ok": True, "attack": None})
        self.assertEqual((out["tier"], out["capped"]), ("HIGH", False))
        out = self._tier(0.70, CAPPED)
        self.assertEqual((out["tier"], out["capped"]), ("STANDARD", False))
        self.bot._timing_verdict = {}
        self.assertEqual(self._tier(0.95, None)["tier"], "HIGH")


class TheWiringTests(SimpleTestCase):

    def test_the_gate_sits_after_the_quote_and_before_the_cost(self):
        import inspect
        from bot_program.asset_engine.base import AssetBot
        src = inspect.getsource(AssetBot.propose_entry)
        quote = src.index("self._entry_quote_gate(symbol, tk, client)")
        gate = src.index("self._entry_timing_gate(symbol)")
        cost = src.index("charge = cost_to_charge(self.cfg, symbol, tk)")
        self.assertLess(quote, gate)
        self.assertLess(gate, cost)
        src = inspect.getsource(AssetBot.execute_entry)
        # before the billed debate (review 2026-10-06), and again on the
        # fresh clock after the last look, just before the order
        first = src.index("self._entry_timing_gate(symbol)")
        debate = src.index("debate_candidate(self, cand, qty)")
        look = src.index("self._last_look(client, symbol, decision.direction,")
        again = src.rindex("self._entry_timing_gate(symbol)")
        order = src.index("order_kwargs = {")
        self.assertLess(first, debate)
        self.assertLess(look, again)
        self.assertLess(again, order)
        self.assertNotEqual(first, again)

    def test_the_skip_code_has_its_advice_and_its_words(self):
        import inspect
        from bot_program.asset_engine import skips
        from bot_program.telegram_eye import SKIP_WORDS
        self.assertEqual(skips.BAD_TIMING, "bad_timing")
        self.assertIn("BAD_TIMING:", inspect.getsource(skips.diagnose))
        self.assertIn("bad_timing", SKIP_WORDS)
        self.assertIn("clock said no", SKIP_WORDS["bad_timing"])

    def test_the_suite_switch_is_declared_beside_the_paper_gates(self):
        from pathlib import Path
        from django.conf import settings
        src = (Path(settings.BASE_DIR) / "tests" / "__init__.py").read_text(
            encoding="utf-8")
        self.assertIn("_entry_timing.GATE = False", src)


# ── the manual lane ───────────────────────────────────────────────────────

class TheManualLaneTests(SimpleTestCase):

    def test_the_advisory_warns_and_never_refuses(self):
        from bot_program.manual_trade import timing_advisory
        inst = SimpleNamespace(symbol="EURUSD", asset_class="forex",
                               exchange="FOREX")
        with mock.patch("bot_program.entry_timing.verdict",
                        return_value=REFUSED) as v:
            adv = timing_advisory(inst)
        self.assertEqual(adv, {"ok": False, "reason": REFUSED["why"],
                               "attack": ""})
        self.assertEqual(v.call_args.args, ("EURUSD", "forex"))
        self.assertEqual(v.call_args.kwargs["exchange"], "FOREX")
        with mock.patch("bot_program.entry_timing.verdict",
                        side_effect=RuntimeError("x")):
            self.assertTrue(timing_advisory(inst)["ok"])

    def test_the_preview_the_booking_and_the_popup_carry_it_without_blocking(self):
        from pathlib import Path
        from django.conf import settings
        base = Path(settings.BASE_DIR)
        manual = (base / "bot_program" / "manual_trade.py").read_text(
            encoding="utf-8")
        self.assertIn('"timing_advisory": timing_advisory(inst),', manual)
        self.assertIn('extra["timing_advisory_at_entry"]', manual)
        html = (base / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertIn("p.timing_advisory", html)
        self.assertIn("BAD TIMING FOR AN ENTRY", html)
        self.assertIn("A warning, not a block: the bots refuse an entry at",
                      html)
        expr = html.split("okBtn.disabled = ", 1)[1].split(";", 1)[0]
        self.assertNotIn("timingAdv", expr)
        self.assertNotIn("timing_advisory", expr)
