"""Livestock, lumber, grains and softs keep their own hours, and every clock
on the platform knows it.

Read off the live box on 2026-09-17 at 05:54 CT: paper_readiness reported
"CME is OPEN and 3 symbol(s) have a 4h bar up to 18.9h old — the feed has
stopped for them: LEANHOGS, LIVECATTLE, LUMBER". The feed had not stopped.
CME livestock trades Monday-Friday 08:30-13:05 CT and CME lumber (LBR)
09:00-15:05 CT — no Globex overnight — so at 05:54 CT all three were SHUT
and their bar of 16:00 UTC Wednesday was the correct last bar. One "CME"
row for the whole group had called a shut market open, and the report
blamed the feed. The same row also carried CBOT grains (a 13:20-19:00 CT
gap) and ICE softs (daytime New York sessions; cotton wraps midnight),
which would have produced the same line every evening.

Hours read at the source on 2026-09-17: CME Group contract specifications
and the CME Lumber FAQ ("9:00 a.m. - 3:05 p.m. CT"); the CBOT grain fact
card ("7:00 p.m. - 7:45 a.m. CT, Sun - Fri" and "8:30 a.m. - 1:20 p.m.
CT"); the ICE product pages (coffee 4:15 AM - 1:30 PM, cocoa 4:45 AM -
1:30 PM, sugar 3:30 AM - 1:00 PM, FCOJ 8:00 AM - 2:00 PM, cotton 9:00 PM -
2:20 PM, New York time).

WHAT THESE TESTS CONFRONT

  * The resolver against those schedules: fixed clocks on the very
    Thursday of the reading — before the livestock open, mid-session,
    after the livestock close while lumber still trades, after the
    lumber close, inside the grain gap, and inside cotton's overnight.
  * The product clock against the venue clock at the same instant: gold
    on the Globex row is OPEN while lean hogs are SHUT.
  * Every path that reads the clock against the DB row it builds: the
    readiness report (the emitter of the bad line) with a seeded bar and
    a patched clock; the preflight command; the instrument page; the JSON
    endpoint the badge poller reads; the anomaly scan at a fixed now_utc.
    Round one of this fix passed on a hand-built row while the emitter's
    own query carried no symbol — that is the test that was missing.
  * The world-exchange strip against the table: EXCHANGES did not grow,
    the poller's payload carries the products beside it, and every caller
    that passes no symbol gets the venue's answer exactly as before.
  * The preflight's clock against the `now` it is given: "05:54 CT is
    shut" and "11:00 CT is open" cannot both hold if the clock is read at
    the wall.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from unittest import mock

import pytz
from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase

from bot_program import campaign_readiness as pr
from bot_program.management.commands.preflight_live import (
    _bar_verdict, _market_note)
from core.exchange_status import (
    EXCHANGES, PRODUCT_SESSIONS, SYMBOL_VENUE, _product_status,
    get_exchange_status, market_status_for, product_sessions_status,
    session_code_for)

UTC = pytz.UTC
# The reading: Thursday 2026-09-17, 10:54 UTC = 05:54 CDT = 06:54 EDT.
THU_0554_CT = datetime(2026, 9, 17, 10, 54, tzinfo=UTC)
THU_1100_CT = datetime(2026, 9, 17, 16, 0, tzinfo=UTC)
THU_1330_CT = datetime(2026, 9, 17, 18, 30, tzinfo=UTC)   # hogs shut 13:05
THU_1510_CT = datetime(2026, 9, 17, 20, 10, tzinfo=UTC)   # lumber shut 15:05
THU_1530_CT = datetime(2026, 9, 17, 20, 30, tzinfo=UTC)
THU_1730_CT = datetime(2026, 9, 17, 22, 30, tzinfo=UTC)   # grain gap; Globex open
THU_2000_CT = datetime(2026, 9, 18, 1, 0, tzinfo=UTC)     # grains overnight
FRI_1330_CT = datetime(2026, 9, 18, 18, 30, tzinfo=UTC)   # livestock weekend
FRI_2200_ET = datetime(2026, 9, 19, 2, 0, tzinfo=UTC)     # cotton: no Friday open
SATURDAY = datetime(2026, 9, 19, 15, 0, tzinfo=UTC)

LIVESTOCK = ("LEANHOGS", "LIVECATTLE")
GRAINS = ("WHEATUSD", "CORNUSD", "SOYUSD", "OATS", "RICE")
DAY_SOFTS = ("COFFEEUSD", "COCOAUSD", "SUGARUSD")


def status(symbol, when, exchange="CME", asset_class="commodity"):
    return market_status_for(asset_class, exchange, now_utc=when, symbol=symbol)


def is_open(symbol, when, **kw):
    return status(symbol, when, **kw)["is_open"]


class TheResolverTests(SimpleTestCase):

    def test_the_symbol_picks_the_product_session(self):
        self.assertEqual(session_code_for("commodity", "CME", "LEANHOGS"),
                         "CME_LIVESTOCK")
        self.assertEqual(session_code_for("commodity", "CME", "LIVECATTLE"),
                         "CME_LIVESTOCK")
        self.assertEqual(session_code_for("commodity", "CME", "lumber"),
                         "CME_LUMBER")
        self.assertEqual(session_code_for("commodity", "CBOT", "CORNUSD"),
                         "CBOT_GRAINS")
        self.assertEqual(session_code_for("commodity", "ICE", "COTTONUSD"),
                         "ICE_COTTON")
        self.assertEqual(session_code_for("commodity", "ICE", "KCUSD"),
                         "ICE_COFFEE")

    def test_cash_index_symbols_keep_the_cash_markets_clock(self):
        self.assertEqual(session_code_for("index", "CME", "SPX500"), "NYSE")
        self.assertEqual(session_code_for("index", "CME", "RUSSELL2000"), "NYSE")
        self.assertEqual(session_code_for("index", "ICE", "FTSE100"), "LSE")

    def test_without_a_symbol_the_venue_answers_as_before(self):
        self.assertEqual(session_code_for("commodity", "CME"), "CME")
        self.assertEqual(session_code_for("commodity", "CBOT"), "CME")
        self.assertEqual(session_code_for("commodity", "ICE"), "CME")
        self.assertEqual(session_code_for("commodity", "CME", "XAUUSD"), "CME")
        # Brent is ICE Europe and keeps hours within minutes of Globex
        self.assertEqual(session_code_for("commodity", "ICE", "BRNUSD"), "CME")

    def test_crypto_still_wins_over_everything(self):
        self.assertEqual(session_code_for("crypto", "CME", "LEANHOGS"), "CRYPTO")

    def test_the_strip_did_not_grow_but_the_poller_sees_the_products(self):
        """PRODUCT_SESSIONS is not EXCHANGES: no new world-exchange badge,
        no change to the topbar's N/14 — and product_sessions_status()
        carries every product code exactly once for the badge poller."""
        codes = {ex["code"] for ex in EXCHANGES}
        product_codes = {p["code"] for p in PRODUCT_SESSIONS.values()}
        self.assertFalse(codes & product_codes)
        self.assertEqual(get_exchange_status(THU_1100_CT)["total"], len(EXCHANGES))
        rows = product_sessions_status(THU_1100_CT)
        self.assertEqual([r["code"] for r in rows], sorted(
            [r["code"] for r in rows], key=[r["code"] for r in rows].index))
        self.assertEqual({r["code"] for r in rows}, product_codes)
        self.assertEqual(len(rows), len(product_codes))
        for v in SYMBOL_VENUE.values():
            self.assertIn(v, codes)


class TheClockTests(SimpleTestCase):

    def test_before_the_open_livestock_and_lumber_are_shut_while_globex_is_open(self):
        for sym in LIVESTOCK + ("LUMBER",):
            with self.subTest(sym):
                m = status(sym, THU_0554_CT)
                self.assertFalse(m["is_open"], m)
                self.assertEqual(m["next_state"], "opens")
        gold = status("XAUUSD", THU_0554_CT)
        self.assertTrue(gold["is_open"], gold)
        self.assertEqual(gold["session"], "CME")

    def test_grains_are_open_overnight_and_shut_in_the_afternoon_gap(self):
        for sym in GRAINS:
            with self.subTest(sym):
                self.assertTrue(is_open(sym, THU_0554_CT, exchange="CBOT"))   # 19:00→07:45
                self.assertTrue(is_open(sym, THU_1100_CT, exchange="CBOT"))   # 08:30→13:20
                self.assertFalse(is_open(sym, THU_1730_CT, exchange="CBOT"))  # the gap
                self.assertTrue(is_open(sym, THU_2000_CT, exchange="CBOT"))
        # the Globex row is OPEN at 17:30 CT — that is the false blocker
        self.assertTrue(is_open("XAUUSD", THU_1730_CT))

    def test_mid_session_everything_daytime_is_open(self):
        for sym in LIVESTOCK + ("LUMBER",) + DAY_SOFTS + ("ORANGEJUICE",):
            with self.subTest(sym):
                self.assertTrue(is_open(sym, THU_1100_CT, exchange="ICE"))

    def test_after_the_livestock_close_lumber_still_trades_until_1505(self):
        for sym in LIVESTOCK:
            with self.subTest(sym):
                self.assertFalse(is_open(sym, THU_1330_CT))
        self.assertTrue(is_open("LUMBER", THU_1330_CT))
        self.assertFalse(is_open("LUMBER", THU_1510_CT))
        self.assertFalse(is_open("LUMBER", THU_1530_CT))

    def test_softs_keep_new_york_daytime_and_cotton_wraps_midnight(self):
        # 06:54 ET: coffee (04:15), cocoa (04:45), sugar (03:30) open; OJ (08:00) not yet
        self.assertTrue(is_open("COFFEEUSD", THU_0554_CT, exchange="ICE"))
        self.assertTrue(is_open("COCOAUSD", THU_0554_CT, exchange="ICE"))
        self.assertTrue(is_open("SUGARUSD", THU_0554_CT, exchange="ICE"))
        self.assertFalse(is_open("ORANGEJUICE", THU_0554_CT, exchange="ICE"))
        # cotton opened Wednesday 21:00 ET and runs to Thursday 14:20 ET
        self.assertTrue(is_open("COTTONUSD", THU_0554_CT, exchange="ICE"))
        # 15:00 ET (THU_1400_CT): every soft is shut, cotton included
        at_1500_et = datetime(2026, 9, 17, 19, 0, tzinfo=UTC)
        for sym in DAY_SOFTS + ("ORANGEJUICE", "COTTONUSD"):
            with self.subTest(sym):
                self.assertFalse(is_open(sym, at_1500_et, exchange="ICE"))
        # 22:00 ET Thursday: cotton is back (Friday's session), coffee is not
        at_2200_et = datetime(2026, 9, 18, 2, 0, tzinfo=UTC)
        self.assertTrue(is_open("COTTONUSD", at_2200_et, exchange="ICE"))
        self.assertFalse(is_open("COFFEEUSD", at_2200_et, exchange="ICE"))
        # 22:00 ET Friday: no Saturday session, so no Friday-evening open
        self.assertFalse(is_open("COTTONUSD", FRI_2200_ET, exchange="ICE"))

    def test_saturday_everything_is_shut(self):
        for sym in LIVESTOCK + ("LUMBER",) + GRAINS + DAY_SOFTS + (
                "ORANGEJUICE", "COTTONUSD"):
            with self.subTest(sym):
                self.assertFalse(is_open(sym, SATURDAY, exchange="ICE"))

    def test_the_session_key_names_the_product_clock_and_its_hours(self):
        m = status("LEANHOGS", THU_0554_CT)
        self.assertEqual(m["session"], "CME_LIVESTOCK")
        self.assertEqual((m["opens"], m["closes"]), ("08:30", "13:05"))
        self.assertEqual(m["local_time"], "05:54")
        lumber = status("LUMBER", THU_0554_CT)
        self.assertEqual((lumber["opens"], lumber["closes"]), ("09:00", "15:05"))
        # in the grain gap the countdown names the evening segment
        corn = status("CORNUSD", THU_1730_CT, exchange="CBOT")
        self.assertEqual((corn["opens"], corn["closes"]), ("19:00", "07:45"))
        self.assertEqual(corn["time_until_change"], "1h 30m")

    def test_the_weekend_countdown_points_at_monday(self):
        m = status("LEANHOGS", FRI_1330_CT)
        self.assertFalse(m["is_open"])
        self.assertEqual(m["next_state"], "opens")
        self.assertEqual(m["time_until_change"], "2d 19h")

    def test_a_precomputed_status_does_not_hide_the_product(self):
        """Callers that paid for get_exchange_status() once (the anomaly
        scan, the instruments list) pass it back in; the product answer
        must still win over the venue row it carries."""
        pre = get_exchange_status(THU_0554_CT)
        m = market_status_for("commodity", "CME", now_utc=THU_0554_CT,
                              _status=pre, symbol="LIVECATTLE")
        self.assertFalse(m["is_open"])
        self.assertEqual(m["session"], "CME_LIVESTOCK")

    def test_product_status_reads_the_now_it_is_given(self):
        for p in {p["code"]: p for p in PRODUCT_SESSIONS.values()}.values():
            with self.subTest(p["code"]):
                self.assertFalse(_product_status(p, SATURDAY)["is_open"])


class ThePreflightNoteTests(SimpleTestCase):
    """The exact reading of 2026-09-17, re-run against the fixed clock."""

    def _row(self, sym, exchange="CME"):
        return {"instrument__asset_class": "commodity",
                "instrument__exchange": exchange, "instrument__symbol": sym}

    def test_an_18h_livestock_bar_before_the_open_is_a_shut_market(self):
        newest = THU_0554_CT - timedelta(hours=18.9)
        for sym in LIVESTOCK + ("LUMBER",):
            with self.subTest(sym):
                note = _market_note(self._row(sym), newest, THU_0554_CT)
                self.assertIn("shut", note)
                self.assertIn("resolves nothing", note)
                self.assertNotIn("OPEN", note)
                kind, _name, _age = _bar_verdict(self._row(sym), newest,
                                                 THU_0554_CT)
                self.assertEqual(kind, "shut_stale", kind)

    def test_gold_on_the_same_morning_is_still_read_as_open(self):
        note = _market_note(self._row("XAUUSD"),
                            THU_0554_CT - timedelta(hours=2.9), THU_0554_CT)
        self.assertIn("open", note)
        self.assertNotIn("shut", note)

    def test_corn_in_the_afternoon_gap_is_shut_not_late(self):
        newest = THU_1730_CT - timedelta(hours=6.5)
        kind, name, _age = _bar_verdict(self._row("CORNUSD", "CBOT"), newest,
                                        THU_1730_CT)
        self.assertEqual((kind, name), ("shut_stale", "CBOT_GRAINS"))

    def test_a_stale_livestock_bar_while_its_session_is_open_is_still_late(self):
        """The fix must not excuse a genuinely dead feed: mid-session, an
        18.9h bar on lean hogs is late, and says so."""
        newest = THU_1100_CT - timedelta(hours=18.9)
        note = _market_note(self._row("LEANHOGS"), newest, THU_1100_CT)
        self.assertIn("OPEN", note)
        kind, _n, _a = _bar_verdict(self._row("LEANHOGS"), newest, THU_1100_CT)
        self.assertEqual(kind, "late_open")


def _seed_leanhogs(user, mode, when, age_hours=18.9):
    from bot_program.models import AssetBotConfig, IBKRAccount
    from instruments.models import Instrument
    from market_data.models import PriceData
    if mode == "live":
        # The preflight arms LIVE configs against a broker it can read;
        # the same seed tests/test_bar_age_reads_the_market.py uses.
        acct = IBKRAccount.objects.create(user=user, port=4004)
        acct.set_credentials("DU1234567")
        acct.username_enc, acct.password_enc = "x", "y"
        acct.last_equity = Decimal("10000")
        acct.last_equity_currency = "EUR"
        acct.last_equity_at = when
        acct.save()
    AssetBotConfig.objects.create(
        user=user, asset_class="commodity", name="meats", mode=mode,
        symbols=["LEANHOGS"], capital=Decimal("10000"), base_currency="EUR",
        enabled=True)
    inst, _ = Instrument.objects.get_or_create(
        symbol="LEANHOGS", defaults={"name": "Lean Hogs",
                                     "asset_class": "commodity",
                                     "exchange": "CME"})
    PriceData.objects.create(
        instrument=inst, timeframe="4h",
        timestamp=when - timedelta(hours=age_hours),
        open=1, high=2, low=1, close=Decimal("90"), volume=10, source="test")
    return inst


class TheReportThatBlamedTheFeedTests(TestCase):
    """paper_readiness builds its OWN row query. Round one fixed the
    preflight's and passed on a hand-built row; this is the emitter."""

    def setUp(self):
        self.user = User.objects.create_user("pr_clock_u", password="x")
        _seed_leanhogs(self.user, "paper", THU_0554_CT)

    def test_the_readiness_report_reads_the_product_clock(self):
        with mock.patch("django.utils.timezone.now", return_value=THU_0554_CT):
            report = pr.readiness()
        self.assertFalse(
            any("is OPEN" in b and "LEANHOGS" in b for b in report["blockers"]),
            report["blockers"])
        bars = dict(report["sections"])["BARS FOR ENABLED CONFIGS"]
        line = next(r for r in bars if r[0] == "LEANHOGS")
        self.assertIn("CME_LIVESTOCK", line[2], line)
        self.assertIn("shut", line[2], line)

    def test_both_row_queries_carry_the_symbol(self):
        """Source-read: remove "instrument__symbol" from either .values()
        and every clock test above still passes on its hand-built rows."""
        from bot_program.management.commands import preflight_live
        for module in (pr, preflight_live):
            src = Path(module.__file__).read_text(encoding="utf-8")
            self.assertIn('"instrument__symbol"', src, module.__name__)


class ThePreflightCommandTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("pf_clock_u", password="x")
        _seed_leanhogs(self.user, "live", THU_0554_CT)

    def test_the_command_says_shut_for_the_same_row(self):
        out = StringIO()
        with mock.patch("django.utils.timezone.now", return_value=THU_0554_CT):
            call_command("preflight_live", stdout=out)
        body = out.getvalue()
        lines = [ln for ln in body.splitlines()
                 if "LEANHOGS" in ln and "newest 4h bar" in ln]
        self.assertTrue(lines, body)
        self.assertIn("CME_LIVESTOCK shut", lines[0])
        self.assertNotIn("OPEN", lines[0])


class ThePagesAndThePollerTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("badge_clock_u", password="x")
        self.client.force_login(self.user)
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol="LEANHOGS", defaults={"name": "Lean Hogs",
                                         "asset_class": "commodity",
                                         "exchange": "CME"})

    def test_the_instrument_page_names_the_product_session(self):
        resp = self.client.get("/instruments/LEANHOGS/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-market-session="CME_LIVESTOCK"')
        self.assertContains(resp, "CME Livestock")

    def test_the_json_endpoint_carries_products_beside_the_strip(self):
        data = self.client.get("/api/exchange-status/").json()
        self.assertEqual(data["total"], len(EXCHANGES))
        self.assertEqual({r["code"] for r in data["exchanges"]},
                         {ex["code"] for ex in EXCHANGES})
        self.assertEqual({r["code"] for r in data["products"]},
                         {p["code"] for p in PRODUCT_SESSIONS.values()})
        for row in data["products"]:
            for key in ("is_open", "local_time", "time_until_change",
                        "next_state", "name"):
                self.assertIn(key, row)

    def test_the_poller_indexes_the_products(self):
        """Source-read: a badge keyed on a product code must repaint like
        any other, or it freezes at first paint."""
        from django.conf import settings
        js = Path(settings.BASE_DIR) / "static" / "js" / "sv-market-status.js"
        self.assertIn("d.products", js.read_text(encoding="utf-8"))


class TheAnomalyScanTests(TestCase):
    """The scan drops quotes whose market is shut. A livestock quote is
    judged by ITS session, at the now_utc the scan was given."""

    def _run(self, now):
        """Judge at `now`, with every quote five minutes old AT `now`.
        auto_now stamps the wall clock on save; the fixed instants here
        are later today than the wall, so an unstamped quote would read
        as stale for the wrong reason. .update() bypasses auto_now."""
        from ai_agents.tasks import _fresh_open_quotes
        from market_data.models import LiveQuote
        LiveQuote.objects.update(updated_at=now - timedelta(minutes=5))
        return _fresh_open_quotes(
            LiveQuote.objects.select_related("instrument").all(), now)

    def _quote(self, symbol, exchange):
        from tests.test_anomaly_market_hours import _instrument, _quote
        return _quote(_instrument(symbol, "commodity", exchange))

    def test_a_livestock_quote_is_kept_in_session_and_dropped_after(self):
        self._quote("LEANHOGS", "CME")
        self._quote("XAUUSD", "COMEX")
        kept, dropped_closed, _stale = self._run(THU_1100_CT)
        self.assertEqual({q.instrument.symbol for q in kept},
                         {"LEANHOGS", "XAUUSD"})
        self.assertEqual(dropped_closed, 0)
        kept, dropped_closed, _stale = self._run(THU_1330_CT)
        self.assertEqual({q.instrument.symbol for q in kept}, {"XAUUSD"})
        self.assertEqual(dropped_closed, 1)
