"""ONE PRICE EVERYWHERE: the rule (market_data.one_quote, 2026-11-12).

The operator, 2026-11-12: "all the prices dont seem to be the same at the
same time at all between the different rendering sources, bottom
headband, the horde (most accurate and recent it seems...)... they need to
be similar alltogether". One function now decides, for an instrument at a
moment, the price every screen shows; these pin what it decides:

  * a held instrument shows the NEWEST eToro reading Sauron holds (a row's
    venue stamp or the 30-second eToro quote row), at the side eToro
    values the holding at: the bid for longs, the ask for shorts, the mid
    when held both ways, the print for a reading without sides;
  * with no eToro reading, a held instrument shows the same instrument's
    quote labelled with its source, or "awaiting eToro" with the
    stand-in (a future, a cash index) only in the outside slot;
  * any other instrument shows its one LiveQuote row; a Yahoo previous
    close is said to be one, with its day; an outside row's time is
    clamped to its own market's shut;
  * a shut market says so, with the signal rail's words; the day change
    is only ever the price's own source's; the digits are px's;
  * one answer per symbol per response, three queries for forty symbols;
    the viewer's own rows decide what is held (demo world included), and
    an anonymous page holds nothing.

Synthetic fixtures only (tests/one_quote_fixture.py). Display only: no
money path reads any of this (tests/test_one_quote_pins.py).

Run with:  python manage.py test tests.test_one_quote_rule
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.template import Context, Template
from django.test import RequestFactory, SimpleTestCase, TestCase

from tests.one_quote_fixture import (T, daily_bar, held, instrument,
                                     previous_close_event, quote,
                                     seed_measured, stamp)


def _ms(dt):
    return int(round(dt.timestamp() * 1000))


class _Case(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("oq_rule", password="x")
        self.clock = mock.patch("market_data.one_quote.now", return_value=T)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def shown(self, symbol, user=None, at=T):
        from market_data.one_quote import shown
        return shown(symbol, user=self.user if user is None else user, now=at)


class TheNewestEtoroReadingTests(_Case):
    """A held instrument: the newest of the eToro readings Sauron holds."""

    def test_a_fresh_stamp_beats_an_older_polled_quote(self):
        seed_measured(self.user)
        s = self.shown("EURUSD")
        self.assertEqual((s.text(), s.source, s.auth, s.side),
                         ("1.08447", "etoro", "etoro", "bid"))
        self.assertEqual(s.at, T - timedelta(seconds=25))
        self.assertEqual(s.basis, "stamp:tick")
        self.assertEqual(s.words(T), "eToro bid · 25 s")

    def test_a_fresh_polled_quote_beats_an_older_stamp(self):
        quote("EURUSD", "1.08500", "etoro", 10, bid="1.08495", ask="1.08505")
        held(self.user, "EURUSD",
             vm=stamp("1.08452", "1.08447", "1.08457", 240))
        s = self.shown("EURUSD")
        self.assertEqual(s.text(), "1.08495")
        self.assertEqual((s.basis, s.via), ("etoro_poll", "poll"))
        self.assertEqual(s.words(T), "eToro bid · 10 s")
        self.assertIsNone(s.slot, "eToro's own row is no outside quote")

    def test_on_a_tie_the_stamp_wins(self):
        quote("EURUSD", "1.08500", "etoro", 30, bid="1.08495", ask="1.08505")
        held(self.user, "EURUSD",
             vm=stamp("1.08452", "1.08447", "1.08457", 30))
        self.assertEqual(self.shown("EURUSD").basis, "stamp:tick")

    def test_every_row_of_a_symbol_shows_one_reading(self):
        held(self.user, "EURUSD",
             vm=stamp("1.08452", "1.08447", "1.08457", 300))
        held(self.user, "EURUSD",
             vm=stamp("1.08470", "1.08465", "1.08475", 20))
        s = self.shown("EURUSD")
        self.assertEqual(s.text(), "1.08465")
        self.assertEqual(s.at, T - timedelta(seconds=20))

    def test_a_reading_older_than_four_days_is_none(self):
        held(self.user, "XAUUSD",
             vm=stamp("2648.55", "2648.30", "2648.80", 4 * 86400 + 60))
        s = self.shown("XAUUSD")
        self.assertIsNone(s.price)
        self.assertEqual(s.state, "none")
        self.assertEqual(s.words(T), "awaiting eToro")


class TheSideTests(_Case):
    """The side a compact cell prints is the side eToro values the
    holding at; a position's own cell prints its own closing side."""

    def test_longs_read_the_bid_and_shorts_the_ask(self):
        held(self.user, "EURUSD", side="BUY",
             vm=stamp("1.08452", "1.08447", "1.08457", 25))
        held(self.user, "GBPUSD", side="SELL",
             vm=stamp("1.29415", "1.29410", "1.29420", 25))
        self.assertEqual(self.shown("EURUSD").text(), "1.08447")
        g = self.shown("GBPUSD")
        self.assertEqual((g.side, g.text()), ("ask", "1.29420"))
        self.assertEqual(g.words(T), "eToro ask · 25 s")

    def test_held_both_ways_the_compact_cell_is_the_mid(self):
        held(self.user, "EURGBP", side="BUY",
             vm=stamp("0.86000", "0.85990", "0.86010", 25))
        held(self.user, "EURGBP", side="SELL")
        s = self.shown("EURGBP")
        self.assertEqual((s.side, s.text()), ("mid", "0.86000"))
        self.assertEqual(s.text("bid"), "0.85990")
        self.assertEqual(s.text("ask"), "0.86010")
        self.assertEqual(s.words(T), "eToro mid · 25 s")
        self.assertEqual(s.words(T, side="ask"), "eToro ask · 25 s")

    def test_a_sideless_candle_close_is_the_print(self):
        held(self.user, "XAUUSD",
             vm=stamp("2647.60", age_s=600, via="candle"))
        s = self.shown("XAUUSD")
        self.assertEqual((s.side, s.text(), s.basis),
                         ("last", "2647.60", "stamp:candle"))
        self.assertEqual(s.text("bid"), "2647.60", "no side: its print")
        self.assertEqual(s.words(T), "eToro last · 10 min")

    def test_closing_side(self):
        from market_data.one_quote import closing_side
        for d, want in (("BUY", "bid"), ("long", "bid"), ("LONG", "bid"),
                        ("SELL", "ask"), ("short", "ask"), ("", ""),
                        (None, "")):
            self.assertEqual(closing_side(d), want, d)


class NoEtoroReadingTests(_Case):

    def test_a_held_stand_in_awaits_etoro_and_keeps_yahoo_in_the_slot(self):
        quote("XAUUSD", "2671.30", "yfinance", 90)
        held(self.user, "XAUUSD")
        s = self.shown("XAUUSD")
        self.assertIsNone(s.price)
        self.assertEqual((s.state, s.auth), ("none", "etoro"))
        self.assertEqual(s.text(), "—")
        self.assertEqual(s.words(T), "awaiting eToro")
        self.assertEqual(s.slot["who"], "Yahoo GC=F, the front-month future")
        self.assertEqual(s.slot["p"], "2671.30")
        self.assertEqual(s.slot["si"], "future")

    def test_a_held_pair_shows_the_same_instruments_quote_with_its_source(self):
        quote("EURUSD", "1.08460", "oanda_stream", 5, bid="1.08455",
              ask="1.08465")
        held(self.user, "EURUSD")
        s = self.shown("EURUSD")
        self.assertEqual((s.text(), s.source, s.auth),
                         ("1.08460", "oanda_stream", "etoro"))
        self.assertEqual(s.words(T), "OANDA stream · live")
        self.assertEqual(s.text("bid"), "1.08455")

    def test_with_an_etoro_reading_the_outside_row_is_only_the_slot(self):
        seed_measured(self.user)
        s = self.shown("XAUUSD")
        self.assertEqual(s.text(), "2648.30")
        self.assertEqual(s.slot["p"], "2671.30")
        self.assertEqual(s.slot["gap"], "+0.87")
        self.assertEqual(
            s.slot_text(T),
            "Yahoo GC=F, the front-month future 2671.30 · 2 min · "
            "+0.87% vs eToro")


class UnheldTests(_Case):
    """Nobody holds it: its one LiveQuote row, as the rank rule left it."""

    def test_its_one_row(self):
        seed_measured(self.user)
        s = self.shown("GBPUSD")
        self.assertEqual((s.text(), s.source, s.auth, s.side),
                         ("1.29410", "yfinance", "reference", ""))
        self.assertEqual(s.who, "Yahoo GBPUSD=X")
        self.assertEqual(s.words(T), "Yahoo GBPUSD=X · 4 min")
        self.assertIsNone(s.slot)

    def test_no_row_is_no_price(self):
        instrument("USDJPY")
        s = self.shown("USDJPY")
        self.assertEqual((s.state, s.text(), s.words(T)),
                         ("none", "—", "no price"))

    def test_a_yahoo_previous_close_says_so_with_its_day(self):
        quote("GBPUSD", "1.29410", "yfinance", 60)
        daily_bar("GBPUSD", datetime(2026, 11, 11, tzinfo=dt_tz.utc),
                  "1.29410")
        previous_close_event("GBPUSD", T - timedelta(seconds=58))
        s = self.shown("GBPUSD")
        self.assertEqual(s.basis, "previous_close")
        self.assertEqual(s.words(T), "Yahoo GBPUSD=X previous close · Wed 11 Nov")
        self.assertEqual(s.text(), "1.29410", "the number stays, said")

    def test_the_event_is_f1s_own_kind(self):
        from bot_program.feed_harms import POLLER_PREVIOUS_CLOSE
        from market_data import one_quote
        self.assertEqual(one_quote.POLLER_PREVIOUS_CLOSE, POLLER_PREVIOUS_CLOSE)

    def test_an_older_previous_close_event_does_not_name_a_newer_write(self):
        quote("GBPUSD", "1.29410", "yfinance", 60)
        previous_close_event("GBPUSD", T - timedelta(seconds=600))
        self.assertEqual(self.shown("GBPUSD").basis, "quote")

    def test_an_overnight_cash_index_reads_its_true_age(self):
        """The index poller re-stamps a shut cash index while another
        market is open: its time is clamped to the cash close."""
        night = datetime(2026, 11, 12, 23, 45, tzinfo=dt_tz.utc)
        quote("SPX500", "6010.50", "yfinance", 60, at=night)
        s = self.shown("SPX500", at=night)
        self.assertEqual(s.at, datetime(2026, 11, 12, 21, 0, tzinfo=dt_tz.utc))
        self.assertEqual(s.words(night),
                         "Yahoo ^GSPC, the cash index · 3 h")

    def test_a_stream_is_live_within_its_class_bound(self):
        quote("GBPUSD", "1.29400", "oanda_stream", 5, bid="1.29395",
              ask="1.29405")
        s = self.shown("GBPUSD")
        self.assertEqual((s.state, s.live_s), ("live", 15))
        self.assertEqual(s.words(T), "OANDA stream · live")
        self.assertEqual(s.words(T + timedelta(seconds=11)),
                         "OANDA stream · 16 s")


class ShutMarketTests(_Case):
    """A shut market shows its last price, said so, with the rail's words."""

    def setUp(self):
        super().setUp()
        self.gate = mock.patch("signals.market_hold.GATE", True)
        self.gate.start()
        self.addCleanup(self.gate.stop)

    def test_a_forex_weekend(self):
        sat = datetime(2026, 11, 14, 12, 0, tzinfo=dt_tz.utc)
        friday = datetime(2026, 11, 13, 21, 58, tzinfo=dt_tz.utc)
        held(self.user, "EURUSD",
             vm=stamp("1.08452", "1.08447", "1.08457", at=friday))
        s = self.shown("EURUSD", at=sat)
        self.assertEqual(s.state, "shut")
        self.assertEqual(s.text(), "1.08447")
        self.assertEqual(
            s.words(sat),
            "closed · eToro bid Fri 13 Nov 21:58 · opens Sun 22:00 UTC")
        self.assertEqual(s.shut["label"], "market shut · opens Sun 22:00 UTC")

    def test_an_open_market_is_not_shut(self):
        seed_measured(self.user)
        self.assertEqual(self.shown("EURUSD").state, "delayed")


class DayChangeAndDigitsTests(_Case):

    def test_the_day_change_is_only_the_prices_own_source(self):
        seed_measured(self.user)
        self.assertIsNone(self.shown("EURUSD").chg, "eToro measured none")
        self.assertEqual(self.shown("EURUSD").chg_text(), "—")
        self.assertIsNone(self.shown("AAPL").chg)
        g = self.shown("GBPUSD")
        self.assertEqual(g.chg, Decimal("-0.21"))
        self.assertEqual(g.chg_text(), "-0.21%")
        quote("USDJPY", "151.234", "finnhub_ws", 30, chg="0.40",
              chg_src="yfinance")
        self.assertIsNone(self.shown("USDJPY").chg)

    def test_the_digits_are_px(self):
        from core.price_format import price_decimals
        seed_measured(self.user)
        quote("USDJPY", "151.2345", "yfinance", 30)
        for sym, want in (("EURUSD", 5), ("XAUUSD", 2), ("AAPL", 2),
                          ("GBPUSD", 5), ("USDJPY", 3)):
            s = self.shown(sym)
            self.assertEqual(s.dp, want, sym)
            self.assertEqual(s.dp, price_decimals(s.price, s.asset_class, sym))
        self.assertEqual(self.shown("USDJPY").text(), "151.234")


class WhoHoldsTests(_Case):

    def test_demo_world_rows_count_as_held(self):
        held(self.user, "EURUSD", world="demo",
             vm=stamp("1.08452", "1.08447", "1.08457", 25))
        self.assertEqual(self.shown("EURUSD").auth, "etoro")

    def test_another_users_rows_do_not_and_paper_rows_never(self):
        other = get_user_model().objects.create_user("oq_other", password="x")
        quote("EURUSD", "1.08390", "yfinance", 60)
        held(other, "EURUSD", vm=stamp("1.08452", "1.08447", "1.08457", 25))
        held(self.user, "EURUSD", paper=True, broker="paper")
        s = self.shown("EURUSD")
        self.assertEqual((s.auth, s.text()), ("reference", "1.08390"))

    def test_all_reads_every_users_rows_and_anonymous_none(self):
        from market_data.one_quote import ALL, held_symbols, shown
        other = get_user_model().objects.create_user("oq_other2", password="x")
        held(other, "EURUSD", vm=stamp("1.08452", "1.08447", "1.08457", 25))
        self.assertEqual(shown("EURUSD", user=ALL, now=T).auth, "etoro")
        self.assertEqual(shown("EURUSD", user=None, now=T).auth, "reference")
        self.assertEqual(shown("EURUSD", user=AnonymousUser(), now=T).auth,
                         "reference")
        self.assertEqual(held_symbols(ALL), ["EURUSD"])

    def test_a_closed_row_is_not_held(self):
        held(self.user, "EURUSD", status="CLOSED",
             vm=stamp("1.08452", "1.08447", "1.08457", 25))
        self.assertEqual(self.shown("EURUSD").auth, "reference")


class OneAnswerPerResponseTests(_Case):

    def test_for_request_memoises_one_answer_per_symbol(self):
        from market_data.one_quote import for_request
        seed_measured(self.user)
        req = RequestFactory().get("/")
        req.user = self.user
        reg = for_request(req)
        self.assertIs(for_request(req), reg)
        first = reg.get("EURUSD")
        quote("EURUSD", "1.09999", "etoro", 0, bid="1.09990", ask="1.10000")
        self.assertIs(reg.get("EURUSD"), first, "one answer per response")
        self.assertEqual(reg.now, T)

    def test_three_queries_for_forty_symbols(self):
        from market_data.one_quote import shown_many
        syms = [f"OQ{i:02d}" for i in range(38)]
        for i, sym in enumerate(syms):
            quote(sym, 100 + i, "yfinance" if i == 0 else "binance_public",
                  60)
        seed_measured(self.user)
        syms += ["EURUSD", "XAUUSD"]
        with self.assertNumQueries(3):
            got = shown_many(syms, user=self.user, now=T)
        self.assertEqual(len(got), 40)
        self.assertEqual(got["EURUSD"].text(), "1.08447")

    def test_the_payload_carries_no_age(self):
        seed_measured(self.user)
        p = self.shown("EURUSD").payload()
        self.assertEqual(p["s"], "EURUSD")
        self.assertEqual((p["p"], p["b"], p["a"]),
                         ("1.08447", "1.08447", "1.08457"))
        self.assertEqual(p["v"], 1.08447)
        self.assertEqual(p["at"], _ms(T - timedelta(seconds=25)))
        self.assertEqual((p["src"], p["who"], p["auth"], p["side"],
                          p["state"], p["dp"]),
                         ("etoro", "eToro", "etoro", "bid", "delayed", 5))
        self.assertNotIn("age", p)
        self.assertNotIn("age_s", p)


class TheTagsTests(_Case):

    def render(self, src, user=None):
        req = RequestFactory().get("/")
        req.user = user or self.user
        return Template("{% load quote_tags %}" + src).render(
            Context({"request": req}))

    def test_q_prints_the_rule_and_q_json_carries_what_was_printed(self):
        import json
        import re
        seed_measured(self.user)
        out = self.render(
            '{% q "EURUSD" %}|{% q "EURUSD" side="SELL" %}|'
            '{% q "EURUSD" "words" %}|{% q "GBPUSD" "who" %}|'
            '{{ "short"|q_side }}{% q_json %}{% q_json %}')
        head, _, block = out.partition("<script")
        self.assertEqual(head, "1.08447|1.08457|eToro bid · 25 s|"
                               "Yahoo GBPUSD=X|ask")
        self.assertEqual(out.count("data-sv-quotes"), 1,
                         "a symbol is written once per response")
        body = re.search(r">(.*)</script>", "<script" + block).group(1)
        data = json.loads(body)
        self.assertEqual(data["t"], _ms(T))
        self.assertEqual(sorted(data["q"]), ["EURUSD", "GBPUSD"])
        self.assertEqual(data["q"]["EURUSD"]["p"], "1.08447")

    def test_the_block_cannot_close_its_script(self):
        from market_data.one_quote import json_script
        out = json_script({"q": {"X": {"who": "</script><b>&"}}})
        self.assertEqual(out.count("</script>"), 1)
        self.assertNotIn("<b>", out)

    def test_an_anonymous_page_holds_nothing(self):
        seed_measured(self.user)
        out = self.render('{% q "EURUSD" %}', user=AnonymousUser())
        self.assertEqual(out, "1.08390")


class TheGrammarTests(SimpleTestCase):

    def test_the_age_grammar_is_the_hordes(self):
        from bot_program.venue_mark import age_words as horde
        from market_data.one_quote import age_words
        for s in (0, 40, 89, 90, 150, 210, 5399, 5400, 172799, 172800,
                  400000):
            self.assertEqual(age_words(s), horde(s), s)

    def test_when_and_day_words(self):
        from market_data.one_quote import day_words, when_words
        fri = datetime(2026, 11, 13, 21, 58, tzinfo=dt_tz.utc)
        self.assertEqual(when_words(fri, fri + timedelta(hours=1)), "21:58")
        self.assertEqual(when_words(fri, fri + timedelta(hours=3)),
                         "Fri 13 Nov 21:58")
        self.assertEqual(day_words(fri), "Fri 13 Nov")
