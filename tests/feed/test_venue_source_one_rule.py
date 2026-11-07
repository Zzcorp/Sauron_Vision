"""ONE VENUE-SOURCE RULE, EXACTLY TODAY'S ANSWERS (the eToro feed spec, F1,
§3.2 item 3, harm 27, P-b.3; 2026-11-07).

Three tests answered "did eToro write this quote?" before F1:

  T1  venue_mark.quote_stand_in: the quote's source equals the row's
      carrier, in any case, untrimmed — generic over every carrier;
  T2  mark_sanity.second_opinion: the source starts with "etoro"
      (VENUE_SOURCES), in any case, untrimmed;
  T3  portfolio.services._is_etoro_source: "etoro", or "etoro_" / "etoro-"
      and a channel, trimmed, in any case.

F1 replaces the three with market_data.venue_quotes.is_venue_source. The
spec's own rule is T3's (the CHANNEL reading), and it would change answers:
T1's for "etoro_ws", padded names and — for an OANDA or Binance row —
"oanda_stream", "binance_ws" and "binance_public", which those streams and
pollers write today; T2's for "etorox"-like names and a leading space. So
each caller keeps its own answer through its reading (EXACT, PREFIX,
CHANNEL), and this table proves it: every caller's new answer equals its
old one for every input below — every source the code base writes (found
by scanning the writers, so a new writer fails here until it is listed),
every feed and priority key, the spec's channel names, every carrier key,
empty, None, padded and near-miss names, and five case variants of each.
The differences the spec's rule would have made are listed and pinned
(EXPECTED_DIFFERENCES); none is a source a writer uses for an eToro row
today.

Run with:  python manage.py test tests.feed.test_venue_source_one_rule
"""
import ast
import re
from datetime import datetime, timedelta, timezone as dt_tz
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase

BASE = Path(settings.BASE_DIR)
NOW = datetime(2026, 11, 4, 12, 0, tzinfo=dt_tz.utc)


# ── today's three tests, frozen verbatim (main ede54d0) ──────────────────

def old_t1_waived(source, carrier) -> bool:
    """venue_mark.quote_stand_in's test (a quote object is present)."""
    return bool(carrier and
                str(source or "").lower() == str(carrier).lower())


def old_t2_venue(source) -> bool:
    """mark_sanity.second_opinion's test (VENUE_SOURCES = ("etoro",))."""
    src = str(source or "").lower()
    return any(src.startswith(v) for v in ("etoro",))


def old_t3_etoro(source) -> bool:
    """portfolio.services._is_etoro_source."""
    s = str(source or "").strip().lower()
    return s == "etoro" or s.startswith(("etoro" + "_", "etoro" + "-"))


# ── the table ────────────────────────────────────────────────────────────

#: Every LiveQuote source the code base writes today (2026-11-07): the
#: streams, IBKR's hourly feed, eToro's interim quotes beat and legacy Sync
#: button, and the pollers. test_the_table_holds_every_written_source
#: finds them in the writers' code.
WRITTEN = ("binance_ws", "finnhub_ws", "oanda_stream", "ibkr", "etoro",
           "coingecko", "alpha_vantage", "yfinance", "binance_public")
#: The carriers a row can name (engine/capabilities.ADAPTER_CLASS_KEYS),
#: and "" (unknown).
CARRIERS = ("alpaca", "binance", "binance_futures", "etoro", "ibkr", "oanda",
            "paper", "saxo", "")
#: Names the spec, the cache and the P&L tiers use, and near misses.
SPEC_NAMES = ("etoro_ws", "etoro_rest", "etoro (legacy sync)",
              "etoro_rates", "etoro_quote", "etoro-legacy", "etoro_")
EDGES = ("", " ", "etor", "etorox", "xetoro", "e_toro", "etoro.x",
         "etoro x", " etoro", "etoro ", "\tetoro_ws", "etoro\n", "ETORO",
         "eToro", "EToro_WS", "unknown", "test", "venue", "oanda", "binance",
         "alpaca", "twelve_data", "fmp", "yfinance_public", "etoro_rates ")


def _variants(s):
    return {s, s.lower(), s.upper(), s.title(), s.swapcase(),
            s.capitalize()}


def table():
    """Every input, de-duplicated, None included."""
    from market_data.feeds import FEEDS
    from market_data.quotes import SOURCE_PRIORITY
    base = set(WRITTEN) | set(CARRIERS) | set(SPEC_NAMES) | set(EDGES)
    base |= set(SOURCE_PRIORITY) | {f["key"] for f in FEEDS}
    out = set()
    for s in base:
        out |= _variants(s)
    return [None] + sorted(out)


def _written_variants():
    out = set()
    for s in WRITTEN:
        out |= _variants(s)
    return out


#: Where the spec's rule (the CHANNEL reading, T3's) would have changed an
#: answer today — kept as it was, and listed. T1 pairs are
#: (source, carrier), T2's single sources, all lowered.
EXPECTED_DIFFERENCES = {
    "T1": {
        # an eToro row: the spec's channel names and padded names
        ("etoro_ws", "etoro"), ("etoro_rest", "etoro"),
        ("etoro_rates", "etoro"), ("etoro_quote", "etoro"),
        ("etoro-legacy", "etoro"), ("etoro_", "etoro"),
        (" etoro", "etoro"), ("etoro ", "etoro"), ("\tetoro_ws", "etoro"),
        ("etoro\n", "etoro"), ("etoro_rates ", "etoro"),
        # an OANDA or Binance row: the streams and pollers write these
        ("oanda_stream", "oanda"), ("binance_ws", "binance"),
        ("binance_public", "binance"), ("binance_futures", "binance"),
    },
    "T2": {"etorox", "etoro.x", "etoro x", "etoro (legacy sync)",
           " etoro", "\tetoro_ws"},
    "T3": set(),
}


class TheTableTests(SimpleTestCase):

    def test_the_table_holds_every_written_source(self):
        """Every literal source a writer hands write_quote, the interim
        beat's SOURCE and the legacy adapter's, found in the code."""
        found = set()
        for path in sorted(BASE.rglob("*.py")):
            rel = path.relative_to(BASE)
            if rel.parts[0] in ("tests", "venv", "node_modules") \
                    or "migrations" in rel.parts or ".claude" in rel.parts:
                continue
            text = path.read_text(encoding="utf-8")
            if "write_quote" not in text:
                continue
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(
                        node.func, "id", getattr(node.func, "attr", "")) \
                        == "write_quote":
                    for kw in node.keywords:
                        if kw.arg == "source" and isinstance(
                                kw.value, ast.Constant):
                            found.add(kw.value.value)
            for m in re.finditer(r'^SOURCE = "([^"]+)"', text, re.M):
                found.add(m.group(1))
        self.assertEqual(found, set(WRITTEN),
                         "a writer's source is missing from WRITTEN")

    def test_the_carriers_are_the_adapters(self):
        from bot_program.engine.capabilities import ADAPTER_CLASS_KEYS
        self.assertEqual(set(CARRIERS) - {""},
                         set(ADAPTER_CLASS_KEYS.values()))

    def test_the_table_size(self):
        self.assertGreater(len(table()), 120)


# ── each caller, old beside new ──────────────────────────────────────────

class ThePredicatesTests(SimpleTestCase):
    """The readings themselves, against the frozen tests, every input."""

    def test_t1_exact_reading_equals_today(self):
        from market_data.venue_quotes import EXACT, is_venue_source
        n = 0
        for s in table():
            for c in CARRIERS:
                for carrier in _variants(c) | {None}:
                    n += 1
                    new = bool(carrier) and is_venue_source(
                        s, carrier, reading=EXACT)
                    self.assertEqual(new, old_t1_waived(s, carrier),
                                     (s, carrier))
        self.assertGreater(n, 4500)

    def test_t2_prefix_reading_equals_today(self):
        from bot_program.mark_sanity import VENUE_SOURCES
        from market_data.venue_quotes import PREFIX, is_venue_source
        self.assertEqual(VENUE_SOURCES, ("etoro",))
        for s in table():
            new = any(is_venue_source(s, v, reading=PREFIX)
                      for v in VENUE_SOURCES)
            self.assertEqual(new, old_t2_venue(s), s)

    def test_t3_channel_reading_equals_today(self):
        from market_data.venue_quotes import is_venue_source
        for s in table():
            self.assertEqual(is_venue_source(s), old_t3_etoro(s), s)

    def test_the_specs_rule_would_change_exactly_these(self):
        """The CHANNEL reading, applied at T1 and T2, against today."""
        from market_data.venue_quotes import is_venue_source
        diffs = {"T1": set(), "T2": set(), "T3": set()}
        for s in table():
            for c in CARRIERS:
                if bool(c) and is_venue_source(s, c) != old_t1_waived(s, c):
                    diffs["T1"].add((str(s).lower(), c))
            if is_venue_source(s) != old_t2_venue(s):
                diffs["T2"].add(str(s).lower())
            if is_venue_source(s) != old_t3_etoro(s):
                diffs["T3"].add(str(s).lower())
        self.assertEqual(diffs, EXPECTED_DIFFERENCES)

    def test_no_kept_difference_touches_an_etoro_row_today(self):
        """For an eToro row, no source a writer uses today is among the
        differences; the T1 pairs a writer does use are other carriers'
        (an OANDA row's oanda_stream quote, a Binance row's binance_ws or
        binance_public), where the spec's rule would have waived the
        stand-in check and today's does not."""
        written = _written_variants()
        for s, c in EXPECTED_DIFFERENCES["T1"]:
            if c == "etoro":
                self.assertNotIn(s, {w.lower() for w in written}, s)
        seen_today = {(s, c) for s, c in EXPECTED_DIFFERENCES["T1"]
                      if s in {w.lower() for w in written}}
        self.assertEqual(seen_today, {("oanda_stream", "oanda"),
                                      ("binance_ws", "binance"),
                                      ("binance_public", "binance")})
        for s in EXPECTED_DIFFERENCES["T2"]:
            self.assertNotIn(s, {w.lower() for w in written}, s)


class TheCallersTests(TestCase):
    """The real callers, old beside new, every input."""

    def test_t1_quote_stand_in_is_todays(self):
        from bot_program.venue_mark import quote_stand_in
        from market_data.public_feed import yf_stand_in
        n = 0
        for symbol in ("XAUUSD", "EURUSD"):
            for s in table():
                for carrier in CARRIERS + ("ETORO", "Ibkr"):
                    q = SimpleNamespace(source=s)
                    old = "" if old_t1_waived(s, carrier) \
                        else yf_stand_in(symbol)
                    self.assertEqual(quote_stand_in(symbol, q,
                                                    carrier=carrier),
                                     old, (symbol, s, carrier))
                    n += 1
            self.assertEqual(quote_stand_in(symbol, None, carrier="etoro"),
                             yf_stand_in(symbol))
        self.assertGreater(n, 2800)

    def test_t2_second_opinion_is_todays(self):
        from bot_program.mark_sanity import second_opinion
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        inst = Instrument.objects.create(symbol="EURUSD", name="EURUSD",
                                         asset_class="forex")
        q = LiveQuote.objects.create(instrument=inst, last=Decimal("1.1"),
                                     source="yfinance")
        n = 0
        for s in table():
            if s is None:
                continue                     # a NOT NULL column
            LiveQuote.objects.filter(pk=q.pk).update(source=s)
            got = second_opinion("EURUSD")
            self.assertEqual(got is None, old_t2_venue(s), s)
            n += 1
        self.assertGreater(n, 120)

    def test_t3_the_pnl_tier_is_todays(self):
        from portfolio.services import _etoro_side
        trade = SimpleNamespace(side="BUY")
        for s in table():
            q = SimpleNamespace(source=s, bid=Decimal("1.1"),
                                ask=Decimal("1.1002"),
                                updated_at=NOW - timedelta(seconds=5))
            got = _etoro_side(trade, q, NOW)
            self.assertEqual(got is not None, old_t3_etoro(s), s)


class TheOneRuleIsAskedTests(TestCase):
    """Each caller asks is_venue_source, with its reading — and no caller
    keeps a test of its own."""

    def _spy(self):
        from market_data import venue_quotes
        real = venue_quotes.is_venue_source
        calls = []

        def spy(*a, **k):
            calls.append((a, k))
            return real(*a, **k)
        return mock.patch.object(venue_quotes, "is_venue_source",
                                 side_effect=spy), calls

    def test_t1_asks_the_exact_reading(self):
        from bot_program.venue_mark import quote_stand_in
        p, calls = self._spy()
        with p:
            self.assertEqual(quote_stand_in(
                "XAUUSD", SimpleNamespace(source="etoro"), carrier="etoro"),
                "")
        self.assertEqual(calls, [(("etoro", "etoro"), {"reading": "exact"})])

    def test_t2_asks_the_prefix_reading(self):
        from bot_program.mark_sanity import second_opinion
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        inst = Instrument.objects.create(symbol="EURUSD", name="EURUSD",
                                         asset_class="forex")
        LiveQuote.objects.create(instrument=inst, last=Decimal("1.1"),
                                 source="etoro")
        p, calls = self._spy()
        with p:
            self.assertIsNone(second_opinion("EURUSD"))
        self.assertEqual(calls, [(("etoro", "etoro"),
                                  {"reading": "prefix"})])

    def test_t3_asks_the_channel_reading(self):
        from portfolio.services import _etoro_side
        p, calls = self._spy()
        q = SimpleNamespace(source="etoro", bid=Decimal("1.1"),
                            ask=Decimal("1.1002"), updated_at=NOW)
        with p:
            self.assertIsNotNone(_etoro_side(SimpleNamespace(side="SELL"),
                                             q, NOW))
        self.assertEqual(calls, [(("etoro",), {})])

    def test_no_caller_keeps_a_test_of_its_own(self):
        import inspect

        from bot_program import mark_sanity, venue_mark
        from portfolio import services
        t1 = inspect.getsource(venue_mark.quote_stand_in)
        self.assertNotIn(".lower() ==", t1)
        t2 = inspect.getsource(mark_sanity.second_opinion)
        self.assertNotIn(".startswith(", t2)
        self.assertFalse(hasattr(services, "_is_etoro_source"),
                         "the P&L tier asks is_venue_source itself")
        t3 = inspect.getsource(services._etoro_side)
        self.assertIn("is_venue_source(", t3)
