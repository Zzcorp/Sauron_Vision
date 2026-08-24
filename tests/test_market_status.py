"""Every instrument answers to exactly one session clock, and the pages
that show it stay true without a reload.

`Instrument.exchange` holds seed strings — NYMEX, CBOT, EUREX, LME —
that mostly have no row in `core.exchange_status.EXCHANGES`, so anything
asking "is this instrument's market open" either missed silently or never
asked. `session_code_for` / `market_status_for` give the one mapping;
the instrument page badge and the topbar's N/14 SE indicator render it;
`/api/exchange-status/` + sv-market-status.js keep both moving, because
a tab left open across the New York close kept advertising NYSE OPEN on
a platform whose every other cell moves on its own.

Run with:  python manage.py test tests.test_market_status
"""
from datetime import datetime

import pytz
from django.contrib.auth.models import User
from django.test import TestCase

from core.exchange_status import (
    EXCHANGES,
    get_exchange_status,
    market_status_for,
    session_code_for,
)

# Fixed clocks — session state IS clock state. Saturday noon UTC: every
# venue in EXCHANGES is shut. Wednesday 15:00 UTC: New York 11:00,
# London 16:00, Globex mid-day, the FX week open. Sunday 15:00 UTC
# (10:00 CT) and Friday 23:00 UTC (18:00 CT) sit inside the Globex
# weekend — the two windows the CME row used to call OPEN, which would
# have fed Friday's frozen prints to the anomaly scan all Sunday.
SATURDAY = datetime(2026, 8, 22, 12, 0, tzinfo=pytz.UTC)
SUNDAY = datetime(2026, 8, 23, 15, 0, tzinfo=pytz.UTC)
SUNDAY_EVENING = datetime(2026, 8, 23, 23, 30, tzinfo=pytz.UTC)  # 18:30 CT
FRIDAY_EVENING = datetime(2026, 8, 21, 23, 0, tzinfo=pytz.UTC)   # 18:00 CT
WEDNESDAY = datetime(2026, 8, 19, 15, 0, tzinfo=pytz.UTC)


def _instrument(symbol, asset_class="stock", exchange=""):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class,
                                 "exchange": exchange})
    return inst


class SessionCodeTests(TestCase):
    """The venue-string → session-row mapping, including every alias the
    seed data actually writes."""

    def test_direct_exchange_codes_pass_through(self):
        self.assertEqual(session_code_for("stock", "NASDAQ"), "NASDAQ")
        self.assertEqual(session_code_for("stock", "NYSE"), "NYSE")
        self.assertEqual(session_code_for("forex", "FOREX"), "FOREX")
        self.assertEqual(session_code_for("index", "CME"), "CME")

    def test_cme_group_and_ice_keep_the_globex_clock(self):
        for venue in ("NYMEX", "COMEX", "CBOT", "ICE"):
            self.assertEqual(session_code_for("commodity", venue), "CME",
                             f"{venue} is (or keeps the hours of) CME Group")

    def test_the_other_seeded_venues_map_to_their_clocks(self):
        self.assertEqual(session_code_for("commodity", "LME"), "LSE")
        self.assertEqual(session_code_for("index", "EUREX"), "XETRA")
        self.assertEqual(session_code_for("index", "OSE"), "TSE")
        self.assertEqual(session_code_for("stock", "BME"), "EURONEXT")

    def test_crypto_wins_over_any_venue_string(self):
        """The seeds write exchange="CRYPTO"; no session row will ever
        exist for it, and none is needed — there is no clock."""
        self.assertEqual(session_code_for("crypto", "CRYPTO"), "CRYPTO")
        self.assertEqual(session_code_for("crypto", ""), "CRYPTO")
        self.assertEqual(session_code_for("crypto", "BINANCE"), "CRYPTO")

    def test_unknown_venues_fall_back_by_asset_class(self):
        self.assertEqual(session_code_for("stock", "MYSTERY"), "NYSE")
        self.assertEqual(session_code_for("etf", ""), "NYSE")
        self.assertEqual(session_code_for("commodity", ""), "CME")
        self.assertEqual(session_code_for("forex", ""), "FOREX")

    def test_every_alias_lands_on_a_real_exchanges_row(self):
        """An alias to a renamed row would silently un-map a venue —
        the exact miss this module replaces."""
        from core.exchange_status import (ASSET_CLASS_DEFAULT_SESSION,
                                          SESSION_ALIASES)
        codes = {ex["code"] for ex in EXCHANGES}
        for target in SESSION_ALIASES.values():
            self.assertIn(target, codes)
        for ac, target in ASSET_CLASS_DEFAULT_SESSION.items():
            if target != "CRYPTO":
                self.assertIn(target, codes, f"default for {ac}")


class MarketStatusForTests(TestCase):
    def test_saturday_everything_is_closed_except_crypto(self):
        for ac, venue in (("stock", "NASDAQ"), ("forex", "FOREX"),
                          ("commodity", "CBOT")):
            status = market_status_for(ac, venue, now_utc=SATURDAY)
            self.assertFalse(status["is_open"], f"{venue} on a Saturday")
            self.assertEqual(status["next_state"], "opens")
        crypto = market_status_for("crypto", "CRYPTO", now_utc=SATURDAY)
        self.assertTrue(crypto["is_open"])
        self.assertEqual(crypto["session"], "CRYPTO")

    def test_globex_weekend_is_closed_on_both_edges(self):
        """The review catch: the CME row modelled only the daily break, so
        Sunday daytime and Friday evening read OPEN — and the session
        aliases had just routed every futures venue and every commodity
        through that row. Saturday alone was right, and Saturday alone
        was tested."""
        for now, label in ((SUNDAY, "Sunday daytime"),
                           (FRIDAY_EVENING, "Friday evening")):
            status = market_status_for("commodity", "CBOT", now_utc=now)
            self.assertFalse(status["is_open"], f"Globex on {label}")
            self.assertEqual(status["next_state"], "opens")
        # Sunday 10:00 CT opens the same day at 17:00 CT — seven hours,
        # not _time_until's "skip to Monday" answer.
        sunday = market_status_for("commodity", "NYMEX", now_utc=SUNDAY)
        self.assertEqual(sunday["time_until_change"], "7h 0m")

    def test_globex_sunday_evening_is_open(self):
        """17:00 CT Sunday starts the week; 18:30 CT is a live tape."""
        status = market_status_for("commodity", "COMEX",
                                   now_utc=SUNDAY_EVENING)
        self.assertTrue(status["is_open"])
        self.assertEqual(status["next_state"], "closes")

    def test_saturday_countdowns_point_at_the_real_next_open(self):
        """Globex reopens SUNDAY 17:00 CT — 1d 10h from Saturday noon
        UTC. The generic helper skips Sunday as a non-trading day, which
        is right for NYSE (Monday, 2d 1h) and was a day wrong here."""
        cme = market_status_for("commodity", "CBOT", now_utc=SATURDAY)
        self.assertEqual(cme["time_until_change"], "1d 10h")
        nyse = market_status_for("stock", "NYSE", now_utc=SATURDAY)
        self.assertEqual(nyse["time_until_change"], "2d 1h")

    def test_wednesday_midsession_is_open(self):
        status = market_status_for("stock", "NASDAQ", now_utc=WEDNESDAY)
        self.assertTrue(status["is_open"])
        self.assertEqual(status["session"], "NASDAQ")
        self.assertEqual(status["name"], "NASDAQ")
        self.assertEqual(status["next_state"], "closes")
        self.assertTrue(status["time_until_change"])

    def test_the_session_key_names_the_clock_actually_consulted(self):
        """A defaulted or aliased clock must be visible as itself, not
        pass as the venue's own."""
        status = market_status_for("commodity", "NYMEX", now_utc=WEDNESDAY)
        self.assertEqual(status["session"], "CME")
        self.assertEqual(status["code"], "CME")

    def test_a_precomputed_status_is_reused_not_recomputed(self):
        """The anomaly scan walks every quote; fourteen timezones once."""
        status = get_exchange_status(WEDNESDAY)
        direct = market_status_for("stock", "NYSE", now_utc=WEDNESDAY)
        shared = market_status_for("stock", "NYSE", _status=status)
        self.assertEqual(direct["is_open"], shared["is_open"])
        self.assertEqual(direct["time_until_change"],
                         shared["time_until_change"])


class ExchangeStatusEndpointTests(TestCase):
    """/api/exchange-status/ — what sv-market-status.js polls."""

    def setUp(self):
        self.user = User.objects.create_user("se_live_op", password="x")

    def test_login_is_required(self):
        """Session state is clock arithmetic, but the payload shape and
        the polling cadence are the platform's own — the public wall
        gets its sessions from wall_facts, not from here."""
        resp = self.client.get("/api/exchange-status/")
        self.assertEqual(resp.status_code, 302)

    def test_payload_carries_every_session_row(self):
        self.client.force_login(self.user)
        resp = self.client.get("/api/exchange-status/")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total"], len(EXCHANGES))
        payload_codes = {row["code"] for row in data["exchanges"]}
        self.assertEqual(payload_codes, {ex["code"] for ex in EXCHANGES})
        for row in data["exchanges"]:
            for key in ("is_open", "local_time", "time_until_change",
                        "next_state", "name"):
                self.assertIn(key, row)


class MarketBadgeOnPageTests(TestCase):
    """The instrument page says which market it answers to and whether
    that market is open — and carries the hook the poller repaints."""

    def setUp(self):
        self.user = User.objects.create_user("badge_op", password="x")
        self.client.force_login(self.user)

    def test_stock_page_names_its_session(self):
        _instrument("AAPL", "stock", "NASDAQ")
        resp = self.client.get("/instruments/AAPL/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-market-session="NASDAQ"')
        self.assertContains(resp, "dtl-mkt")

    def test_crypto_page_is_always_open(self):
        _instrument("BTCUSD", "crypto", "CRYPTO")
        resp = self.client.get("/instruments/BTCUSD/")
        self.assertContains(resp, 'data-market-session="CRYPTO"')
        # The badge's own class attribute, not the stylesheet: the CSS
        # block spells it dot-joined (.dtl-mkt.mk-open), so a bare
        # "mk-open" matched every page and asserted nothing.
        self.assertContains(resp, 'class="dtl-mkt mk-open"')
        self.assertContains(resp, "Crypto · OPEN")

    def test_the_badge_sits_in_the_price_hero_not_the_metadata_line(self):
        """The first cut put it in detail-meta, a line nobody's eye lands
        on — and the operator asked where the open/closed state was while
        it was already on the page. The badge renders BEFORE the
        detail-meta div: next to the price, where a number with no market
        state next to it would read as live."""
        _instrument("AAPL", "stock", "NASDAQ")
        resp = self.client.get("/instruments/AAPL/")
        body = resp.content.decode()
        self.assertLess(body.index("dtl-mkt"), body.index("detail-meta"))

    def test_the_instruments_list_states_each_rows_market(self):
        """The table-level answer: every row carries the compact cell the
        poller repaints, so a frozen Friday close cannot sit in an
        open-looking row."""
        _instrument("AAPL", "stock", "NASDAQ")
        _instrument("BTCUSD", "crypto", "CRYPTO")
        resp = self.client.get("/instruments/")
        self.assertContains(resp, "<th>Market</th>")
        self.assertContains(resp, 'data-market-session="NASDAQ"')
        self.assertContains(resp, "data-market-compact")
        # Crypto has no clock: the honest label is 24/7, always open.
        self.assertContains(resp, 'data-market-session="CRYPTO"')
        self.assertContains(resp, "24/7")

    def test_topbar_carries_the_live_hooks(self):
        """The SE indicator's count and rows are addressable, and the
        poller script ships — without these the JS finds nothing and the
        indicator silently reverts to a render-time constant."""
        _instrument("AAPL", "stock", "NASDAQ")
        resp = self.client.get("/instruments/AAPL/")
        self.assertContains(resp, "data-ex-open-count")
        self.assertContains(resp, 'data-ex-code="NYSE"')
        self.assertContains(resp, "js/sv-market-status.js")
