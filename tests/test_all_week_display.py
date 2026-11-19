"""eToro's ALL-WEEK INSTRUMENTS ON THE SCREENS: the helper and its words
(2026-11-19). Display only; money direction none.

The operator, 2026-11-19: yes, the screens say "open 24/7 at eToro" at the
weekend for eToro's all-week instruments; the bots keep no new entry at
the weekend, for now. eToro's own pages (its market-hours page, the
English page as indexed about 2026-11-02, read 2026-11-19) list the
regular GOLD (18), OIL (17), SILVER (19) and NATGAS (22) as open 24/7,
with breaks in GMT: daily 22:00-23:00, Friday 22:00-22:30, and Saturday
22:00-22:15 for OIL and NATGAS; its commodities page names SPX500 (27)
and NSDQ100 (28) too, with no break times. EURUSD is unsettled and keeps
the weekday week.

  * market_data.shut_bars.all_week_state(instrument, now): open, or in
    one of eToro's breaks with its reopening, for the ids of
    ALL_WEEK_ETORO_IDS only (keyed by eToro's id, resolved from a
    platform symbol through VENUE_ID_PINS, no network); the breaks sit
    beside the ids, keyed the same way.
  * market_data.all_week_display: what the screens say instead of
    Sauron's own words: "open · eToro 24/7" while Sauron's clock is shut
    for a day or more (the weekend), "pause · eToro reopens 23:00 UTC" in
    a break, "bots: no weekend entries, by your choice" while the bots'
    own clock refuses (the four commodities only), the paper venue's
    wait, and the market badge's own row.

Every instant is fixed; nothing reads the wall clock, the network or a
model. The oil platform symbol is read from its pin (eToro id 17), never
written here.

Run with:  python manage.py test tests.test_all_week_display
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

UTC = dt_tz.utc
FRI_2130 = datetime(2026, 11, 20, 21, 30, tzinfo=UTC)
FRI_2210 = datetime(2026, 11, 20, 22, 10, tzinfo=UTC)
FRI_2240 = datetime(2026, 11, 20, 22, 40, tzinfo=UTC)
SAT_1500 = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)
SAT_2205 = datetime(2026, 11, 21, 22, 5, tzinfo=UTC)
SAT_2220 = datetime(2026, 11, 21, 22, 20, tzinfo=UTC)
SUN_2230 = datetime(2026, 11, 22, 22, 30, tzinfo=UTC)
SUN_2305 = datetime(2026, 11, 22, 23, 5, tzinfo=UTC)
TUE_1500 = datetime(2026, 11, 24, 15, 0, tzinfo=UTC)
TUE_2230 = datetime(2026, 11, 24, 22, 30, tzinfo=UTC)

#: The instruments as the catalogue keeps them (class, exchange).
ROWS = {"XAUUSD": ("commodity", "COMEX"), "XAGUSD": ("commodity", "COMEX"),
        "NGUSD": ("commodity", "NYMEX"), "SPX500": ("index", "CME"),
        "NSDQ100": ("index", "CME"), "EURUSD": ("forex", "FOREX"),
        "GBPUSD": ("forex", "FOREX"), "HGUSD": ("commodity", "COMEX"),
        "BTCUSD": ("crypto", "CRYPTO")}
#: Written out here from eToro's own list (never read from shut_bars).
ALL_WEEK = ("XAUUSD", "XAGUSD", "NGUSD", "SPX500", "NSDQ100")
WEEKDAY_ONLY = ("EURUSD", "GBPUSD", "HGUSD", "BTCUSD")


def oil():
    """The platform symbol eToro's OIL (17) is pinned to, read from the
    pin (etoro_client.PINNED_SYMBOL)."""
    from bot_program.engine.etoro_client import PINNED_SYMBOL
    return PINNED_SYMBOL[17]


def inst(symbol):
    cls, exch = ROWS.get(symbol, ("commodity", "NYMEX"))
    return SimpleNamespace(symbol=symbol, asset_class=cls, exchange=exch)


def gates(test, *, display=True, rail=True, entry=True):
    """Turn the suite's switched-off clocks back on (tests/__init__.py)
    for one test: the screens' all-week words, the rail's market clock
    and the bots' entry clock."""
    for target, on in (("market_data.all_week_display.GATE", display),
                       ("signals.market_hold.GATE", rail),
                       ("bot_program.entry_timing.GATE", entry)):
        p = mock.patch(target, on)
        p.start()
        test.addCleanup(p.stop)


class TheHelperTests(SimpleTestCase):
    """shut_bars.all_week_state: eToro open, or in one of its published
    breaks with the reopening, keyed by eToro's id."""

    def state(self, symbol, now):
        from market_data.shut_bars import all_week_state
        return all_week_state(inst(symbol), now)

    def test_saturday_afternoon_every_all_week_instrument_is_open(self):
        for sym in ALL_WEEK + (oil(),):
            with self.subTest(sym if sym != oil() else "eToro id 17"):
                st = self.state(sym, SAT_1500)
                self.assertEqual(st["state"], "open")
                self.assertIsNone(st["reopens"])

    def test_friday_2210_is_the_friday_break_until_2230(self):
        for sym in ("XAUUSD", "XAGUSD", "NGUSD", oil()):
            with self.subTest(sym if sym != oil() else "eToro id 17"):
                st = self.state(sym, FRI_2210)
                self.assertEqual(st["state"], "pause")
                self.assertEqual(st["since"],
                                 datetime(2026, 11, 20, 22, 0, tzinfo=UTC))
                self.assertEqual(st["reopens"],
                                 datetime(2026, 11, 20, 22, 30, tzinfo=UTC))
        self.assertEqual(self.state("XAUUSD", FRI_2240)["state"], "open")

    def test_saturday_2205_is_a_break_for_oil_and_natural_gas_only(self):
        for sym in ("NGUSD", oil()):
            with self.subTest(sym if sym != oil() else "eToro id 17"):
                st = self.state(sym, SAT_2205)
                self.assertEqual(st["state"], "pause")
                self.assertEqual(st["reopens"],
                                 datetime(2026, 11, 21, 22, 15, tzinfo=UTC))
                self.assertEqual(self.state(sym, SAT_2220)["state"], "open")
        for sym in ("XAUUSD", "XAGUSD", "SPX500", "NSDQ100"):
            with self.subTest(sym):
                self.assertEqual(self.state(sym, SAT_2205)["state"], "open")

    def test_a_weekday(self):
        for sym in ("XAUUSD", "NGUSD"):
            with self.subTest(sym):
                self.assertEqual(self.state(sym, TUE_1500)["state"], "open")
                st = self.state(sym, TUE_2230)
                self.assertEqual((st["state"], st["reopens"]), (
                    "pause", datetime(2026, 11, 24, 23, 0, tzinfo=UTC)))
        sun = self.state("XAUUSD", SUN_2230)
        self.assertEqual((sun["state"], sun["reopens"]), (
            "pause", datetime(2026, 11, 22, 23, 0, tzinfo=UTC)))

    def test_eurusd_and_every_weekday_market_is_not_all_week(self):
        for sym in WEEKDAY_ONLY:
            for now in (SAT_1500, TUE_1500, TUE_2230):
                with self.subTest(sym=sym, now=now):
                    self.assertIsNone(self.state(sym, now))

    def test_the_indices_breaks_are_not_published_so_none_is_invented(self):
        for sym in ("SPX500", "NSDQ100"):
            for now in (FRI_2210, TUE_2230, SUN_2230):
                with self.subTest(sym=sym, now=now):
                    st = self.state(sym, now)
                    self.assertEqual(st["state"], "open")
                    self.assertFalse(st["breaks_published"])
                    self.assertIsNone(st["next_pause"])

    def test_the_next_break_while_open(self):
        st = self.state("XAUUSD", SAT_1500)
        self.assertEqual(st["next_pause"], (
            datetime(2026, 11, 22, 22, 0, tzinfo=UTC),
            datetime(2026, 11, 22, 23, 0, tzinfo=UTC)))
        st = self.state("NGUSD", SAT_1500)
        self.assertEqual(st["next_pause"][0],
                         datetime(2026, 11, 21, 22, 0, tzinfo=UTC))

    def test_keyed_by_etoros_id_beside_the_one_list(self):
        """The breaks are keyed by the same ids as the one list, and the
        id is resolved as the bar rule resolves it (one helper)."""
        from market_data.shut_bars import (ALL_WEEK_BREAKS_UTC,
                                           ALL_WEEK_ETORO_IDS,
                                           all_week_etoro_id, all_week_state,
                                           trades_all_week)
        self.assertLessEqual(set(ALL_WEEK_BREAKS_UTC),
                             set(ALL_WEEK_ETORO_IDS))
        self.assertEqual(set(ALL_WEEK_BREAKS_UTC), {17, 18, 19, 22})
        for week in ALL_WEEK_BREAKS_UTC.values():
            self.assertEqual(len(week), 7, "one entry per weekday")
        self.assertEqual(all_week_etoro_id("XAUUSD"), 18)
        self.assertEqual(all_week_etoro_id(oil()), 17)
        self.assertEqual(all_week_etoro_id(inst("SPX500")), 27)
        self.assertIsNone(all_week_etoro_id("GOLD"),
                          "the catalogue's GOLD is a stock, not eToro's 18")
        for sym in ALL_WEEK + WEEKDAY_ONLY + (oil(), "AAPL", "", None):
            with self.subTest(sym=sym):
                self.assertEqual(trades_all_week(sym),
                                 all_week_etoro_id(sym) is not None)
        self.assertEqual(all_week_state(etoro_id=22, now=SAT_2205)["state"],
                         "pause")
        self.assertIsNone(all_week_state(etoro_id=21, now=SAT_1500))

    def test_a_naive_clock_is_utc_and_nothing_raises(self):
        from market_data.shut_bars import all_week_state
        naive = all_week_state("XAUUSD", FRI_2210.replace(tzinfo=None))
        self.assertEqual(naive["state"], "pause")
        self.assertIsNone(all_week_state(None, SAT_1500))
        self.assertIsNone(all_week_state(object(), SAT_1500))


class TheWordsTests(SimpleTestCase):
    """all_week_display.week: what the screens say instead, and when they
    keep Sauron's own words."""

    def setUp(self):
        gates(self)

    def week(self, symbol, now):
        from market_data.all_week_display import week
        return week(inst(symbol), now)

    def test_saturday_afternoon_gold_reads_open_and_the_bots_choice(self):
        wk = self.week("XAUUSD", SAT_1500)
        self.assertEqual(wk["state"], "open")
        self.assertEqual(wk["label"], "open · eToro 24/7")
        self.assertEqual(wk["bots"], "bots: no weekend entries, by your choice")
        self.assertEqual(wk["paper"],
                         "paper: waits for CME's open, Sun 23:00 UTC")
        self.assertEqual(wk["until"], datetime(2026, 11, 22, 23, 0,
                                               tzinfo=UTC))
        self.assertEqual(wk["hint"],
                         "breaks 22:00-23:00 UTC daily, Fri 22:00-22:30")
        for sym in ("XAGUSD", "NGUSD", oil()):
            with self.subTest(sym if sym != oil() else "eToro id 17"):
                other = self.week(sym, SAT_1500)
                self.assertEqual((other["label"], other["bots"]), (
                    "open · eToro 24/7",
                    "bots: no weekend entries, by your choice"))
        self.assertEqual(
            self.week("NGUSD", SAT_1500)["hint"],
            "breaks 22:00-23:00 UTC daily, Fri 22:00-22:30, Sat 22:00-22:15")

    def test_the_indices_read_open_and_never_the_bots_line(self):
        """An index is no SHUT class: the bots' clock does not refuse it at
        the weekend, so no screen may say it does (the build map's W1)."""
        for sym in ("SPX500", "NSDQ100"):
            with self.subTest(sym):
                wk = self.week(sym, SAT_1500)
                self.assertEqual(wk["label"], "open · eToro 24/7")
                self.assertEqual(wk["bots"], "")
                self.assertEqual(wk["hint"],
                                 "short breaks; times not published")

    def test_a_break_reads_pause_and_its_reopening(self):
        wk = self.week("XAUUSD", FRI_2210)
        self.assertEqual(wk["state"], "pause")
        self.assertEqual(wk["label"], "pause · eToro reopens 22:30 UTC")
        self.assertEqual(wk["opens"], "eToro reopens 22:30 UTC")
        self.assertEqual(wk["after"], "open · eToro 24/7",
                         "Sauron's clock is still shut at 22:30")
        gas = self.week("NGUSD", SAT_2205)
        self.assertEqual(gas["label"], "pause · eToro reopens 22:15 UTC")
        self.assertEqual(self.week("XAUUSD", SAT_2205)["label"],
                         "open · eToro 24/7")
        sun = self.week("XAUUSD", SUN_2230)
        self.assertEqual((sun["label"], sun["after"]),
                         ("pause · eToro reopens 23:00 UTC", ""))

    def test_a_weekday_pause_has_no_bots_line(self):
        wk = self.week("XAUUSD", TUE_2230)
        self.assertEqual(wk["label"], "pause · eToro reopens 23:00 UTC")
        self.assertEqual((wk["bots"], wk["after"]), ("", ""))

    def test_sauron_keeps_its_own_words_otherwise(self):
        for sym, now in (("XAUUSD", TUE_1500), ("XAUUSD", FRI_2130),
                         ("XAUUSD", SUN_2305), ("SPX500", TUE_1500),
                         ("SPX500", TUE_2230)):
            with self.subTest(sym=sym, now=now):
                self.assertIsNone(self.week(sym, now))
        for sym in WEEKDAY_ONLY:
            for now in (SAT_1500, FRI_2210, TUE_2230):
                with self.subTest(sym=sym, now=now):
                    self.assertIsNone(self.week(sym, now))

    def test_the_bots_line_follows_the_bots_clock(self):
        """Read off entry_timing's own refusal: with that clock off, no
        line claims a hold."""
        with mock.patch("bot_program.entry_timing.GATE", False):
            self.assertEqual(self.week("XAUUSD", SAT_1500)["bots"], "")

    def test_gate_off_is_saurons_own_words(self):
        from market_data import all_week_display as d
        with mock.patch.object(d, "GATE", False):
            self.assertIsNone(d.week(inst("XAUUSD"), SAT_1500))
            self.assertEqual(d.badge_rows(SAT_1500), [])
            market = {"session": "CME", "is_open": False}
            self.assertIs(d.badge(inst("XAUUSD"), market, SAT_1500), market)

    def test_never_raises(self):
        from market_data import all_week_display as d
        with mock.patch("market_data.all_week_display.own_shut",
                        side_effect=RuntimeError("clock")):
            self.assertIsNone(d.week(inst("XAUUSD"), SAT_1500))
        self.assertIsNone(d.week(None, SAT_1500))


class TheAnnouncementLabelTests(SimpleTestCase):

    def setUp(self):
        gates(self)

    def label(self, symbol, now):
        from market_data.all_week_display import label
        return label(inst(symbol), now)

    def test_the_label(self):
        self.assertEqual(self.label("XAUUSD", SAT_1500),
                         "open · eToro 24/7 · bots: no weekend entries, "
                         "by your choice")
        self.assertEqual(self.label("SPX500", SAT_1500), "open · eToro 24/7")
        self.assertEqual(self.label("NGUSD", SAT_2205),
                         "pause · eToro reopens 22:15 UTC · bots: no weekend "
                         "entries, by your choice")
        self.assertEqual(self.label("XAUUSD", TUE_2230),
                         "pause · eToro reopens 23:00 UTC")
        self.assertEqual(self.label("XAUUSD", TUE_1500), "")

    def test_every_other_instrument_keeps_the_rails_words(self):
        from signals.market_hold import shut_label
        for sym in WEEKDAY_ONLY + ("SPX500",):
            for now in (SAT_1500, TUE_2230, TUE_1500):
                if sym == "SPX500" and now == SAT_1500:
                    continue
                with self.subTest(sym=sym, now=now):
                    self.assertEqual(self.label(sym, now),
                                     shut_label(inst(sym), now=now))
        self.assertEqual(self.label("HGUSD", SAT_1500),
                         "market shut · opens Sun 23:00 UTC")


class TheBadgeTests(SimpleTestCase):

    def setUp(self):
        gates(self)

    def test_the_badge_is_etoros_own_under_its_own_code(self):
        from core.exchange_status import market_status_for
        from market_data.all_week_display import badge
        market = market_status_for("commodity", "COMEX", now_utc=SAT_1500,
                                   symbol="XAUUSD")
        self.assertFalse(market["is_open"], "CME is shut: the guards' clock")
        b = badge(inst("XAUUSD"), market, SAT_1500)
        self.assertEqual((b["session"], b["is_open"], b["word"]),
                         ("ETORO247_18", True, "24/7"))
        self.assertEqual(b["title"], "open · eToro 24/7 (breaks 22:00-23:00 "
                                     "UTC daily, Fri 22:00-22:30)")
        self.assertFalse(market["is_open"], "the clock's own row untouched")
        p = badge(inst("XAUUSD"), market, FRI_2210)
        self.assertEqual((p["is_open"], p["pause"], p["word"], p["title"]),
                         (False, True, "PAUSE",
                          "pause · eToro reopens 22:30 UTC"))
        spx = badge(inst("SPX500"), market_status_for(
            "index", "CME", now_utc=SAT_1500, symbol="SPX500"), SAT_1500)
        self.assertEqual((spx["session"], spx["word"], spx["title"]), (
            "ETORO247_27", "24/7",
            "open · eToro 24/7 (short breaks; times not published)"))

    def test_every_other_badge_is_untouched(self):
        from core.exchange_status import market_status_for
        from market_data.all_week_display import badge
        for sym in WEEKDAY_ONLY:
            cls, exch = ROWS[sym]
            market = market_status_for(cls, exch, now_utc=SAT_1500,
                                       symbol=sym)
            with self.subTest(sym):
                self.assertIs(badge(inst(sym), market, SAT_1500), market)

    def test_the_pollers_rows(self):
        from market_data.all_week_display import badge_rows
        rows = {r["code"]: r for r in badge_rows(SAT_2205)}
        self.assertEqual(set(rows), {"ETORO247_17", "ETORO247_18",
                                     "ETORO247_19", "ETORO247_22",
                                     "ETORO247_27", "ETORO247_28"})
        self.assertEqual(rows["ETORO247_22"]["word"], "PAUSE")
        self.assertEqual(rows["ETORO247_17"]["title"],
                         "pause · eToro reopens 22:15 UTC")
        self.assertEqual(rows["ETORO247_18"]["word"], "24/7")


class TheOnePricePayloadTests(SimpleTestCase):
    """all_week_display.payload / shut: the one price's own shapes."""

    def setUp(self):
        gates(self)

    def test_open_carries_the_words_until_saurons_reopening_and_the_next_break(self):
        from market_data.all_week_display import payload, week
        wk = payload(week(inst("NGUSD"), SAT_1500))
        self.assertEqual(wk["open"], "open · eToro 24/7")
        self.assertEqual(wk["until"], datetime(2026, 11, 22, 23, 0,
                                               tzinfo=UTC))
        self.assertEqual(wk["np"]["since"],
                         datetime(2026, 11, 21, 22, 0, tzinfo=UTC))
        self.assertEqual(wk["np"]["label"], "pause · eToro reopens 22:15 UTC")
        self.assertEqual(wk["np"]["word"], "pause")

    def test_a_pause_is_a_shut_with_the_word_pause(self):
        from market_data.all_week_display import shut, week
        sh = shut(week(inst("XAUUSD"), FRI_2210))
        self.assertEqual(sh["word"], "pause")
        self.assertEqual(sh["opens"], "eToro reopens 22:30 UTC")
        self.assertEqual(sh["reopens"] - sh["since"], timedelta(minutes=30))
        self.assertIsNone(shut(week(inst("XAUUSD"), SAT_1500)))
