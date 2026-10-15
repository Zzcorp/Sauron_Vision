"""The Big Money Board's surfaces: the page, the ticket note, the morning
brief, the command, and the registry it joins (spec §2.10-§2.13).

Run with:  python manage.py test tests.test_big_money_surfaces
"""
from datetime import date, timedelta
from datetime import timezone as dt_tz
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone
from django.utils.html import escape

from bigmoney import words as W
from bigmoney.score import store_board
from tests.test_big_money_board import (fake_board, fake_cell, instrument,
                                        seed_equity_and_bonds)

UTC = dt_tz.utc
NOTE = "/api/big-money/note/"


def _switch(on=True):
    from core.platform_control import PlatformComponent, seed_components
    seed_components()
    PlatformComponent.objects.filter(
        key__in=("platform_master", "big_money_board")).update(is_enabled=on)


def _stored(now=None, **kw):
    """A read stored as the task would, computed `now` (default: now)."""
    now = now or timezone.now()
    with mock.patch("django.utils.timezone.now", return_value=now):
        store_board(fake_board(now=now, **kw))


ROWS_FIXTURE = {
    "us_equities": {"lean": -0.5, "lean_label": W.LEANS_DOWN,
                    "lean_from": ["month-end rebalancing"],
                    "risk": ["heavy long"],
                    "cells": {"rebalance": fake_cell(
                        "rebalance", "us_equities", score=-1.0,
                        words="Equities ran ahead of bonds this month (+3.7 sd).",
                        frm="month-end rebalancing"),
                        "crowding": fake_cell("crowding", "us_equities",
                                              score=0.7, flag="heavy long",
                                              side="long", degree="heavy",
                                              words="Speculators heavy long "
                                                    "(COT index 85, report Tue 20 Oct)."),
                        "cta": fake_cell("cta", "us_equities", score=1.0,
                                         words="Trend followers are long.",
                                         short="long on 3 of three horizons"),
                        "vrp": fake_cell("vrp", "us_equities", state="unread",
                                         why="FRED key not set (FRED_API_KEY): "
                                             "VIXCLS unread")}},
    "us_dollar": {"lean": 0.6, "lean_label": W.LEANS_UP,
                  "lean_from": ["month-end hedge flows at the fix"],
                  "cells": {"fx_fix": fake_cell("fx_fix", "us_dollar", score=0.6)}},
    "crude_oil": {"lean": None, "lean_label": W.UNREAD,
                  "unread": ["COT: no report for WTIUSD (no futures market "
                             "maps to it)"],
                  "cells": {"cot_change": fake_cell(
                      "cot_change", "crude_oil", state="unread",
                      why="COT: no report for WTIUSD (no futures market maps "
                          "to it)")}},
    "gold": {"lean": 0.1, "lean_label": W.NO_CLEAR_LEAN},
}
INSTRUMENTS_FIXTURE = {
    "EURUSD": {"fx_fix": fake_cell("fx_fix", "EURUSD", score=-0.5, foreign=-0.5,
                                   ccy="EUR", z=1.2,
                                   words="The Euro Stoxx 50 beat the S&P 500."),
               "_lean": {"lean": -0.5, "label": W.LEANS_DOWN,
                         "from": ["month-end hedge flows at the fix"]}},
    "XAGUSD": {"cot_change": fake_cell("cot_change", "XAGUSD", score=-0.8),
               "_lean": {"lean": -0.8, "label": W.LEANS_DOWN,
                         "from": ["the speculators' weekly change, faded"],
                         "risk": ["crowded long"]}},
}
GLOBAL_FIXTURE = {
    "calendar": fake_cell("calendar", "global", events=[
        {"date": (timezone.now().date() + timedelta(days=3)).isoformat(),
         "event": W.EV_MONTH_END, "rows": ["us_equities", "us_dollar"],
         "kind": "computed", "source_url": "", "checked": "", "play": "",
         "directional": False, "forced": True},
        {"date": (timezone.now().date() + timedelta(days=5)).isoformat(),
         "event": W.EV_FOMC, "rows": ["us_equities"], "kind": "announced",
         "source_url": "https://www.federalreserve.gov/monetarypolicy/"
                       "fomccalendars.htm", "checked": "2026-10-09",
         "play": W.PLAY_EVENT_RISK, "directional": False, "forced": False}]),
    "tide": fake_cell("tide", "global", score=0.5, tide_state="adding",
                      words="Dollar liquidity: adding over 4 weeks."),
    "stress": fake_cell("stress", "global", state="unread",
                        why=W.R_NOT_REPLAYED),
    "_sources": [{"input": "SPX500", "newest": "2026-10-23", "age": 0,
                  "bound": 4, "state": "fresh"}],
}


def _full(**kw):
    _stored(rows=ROWS_FIXTURE, instruments=INSTRUMENTS_FIXTURE,
            global_cells=GLOBAL_FIXTURE, **kw)


class PageTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user("bm_u", password="x")
        self.client.force_login(self.user)

    def test_an_empty_database_renders_dashes(self):
        resp = self.client.get("/big-money/")
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(W.EMPTY, body)
        self.assertIn(W.LEDE, body)
        self.assertIn(W.DASH, body)
        self.assertIn(W.SECTION_NOT, body)
        self.assertIn("<title>Big Money · Sauron Vision", body)

    def test_with_a_read_the_markets_and_their_why(self):
        _switch(True)
        _full()
        body = self.client.get("/big-money/").content.decode()
        self.assertIn("US equities", body)
        self.assertIn(W.LEANS_DOWN, body)
        self.assertIn("Equities ran ahead of bonds", body)
        self.assertIn("Strong evidence", body)
        self.assertIn("counts in the lean", body)
        self.assertIn("unread: FRED key not set (FRED_API_KEY): VIXCLS unread",
                      body)
        self.assertIn(W.DOLLAR_HINT, body)
        self.assertIn(W.CRYPTO_NOTE, body)
        self.assertIn("XAGUSD", body)
        self.assertIn("FOMC decision", body)
        self.assertIn("fomccalendars.htm", body)
        self.assertIn(escape(W.TIDE_NOTE), body)
        self.assertIn(W.R_NOT_REPLAYED, body)
        self.assertNotIn(W.OFF.split(".")[0], body)

    def test_the_phone_tier_stacks_each_market_into_a_card(self):
        _switch(True)
        _full()
        body = self.client.get("/big-money/", HTTP_USER_AGENT=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)")).content.decode()
        self.assertIn('class="sv-perf-table sv-stack bm-world"', body)
        for h in W.HEADERS_WORLD:
            self.assertIn(f'data-label="{escape(h)}"', body)

    def test_switch_off_says_so_and_shows_the_newest(self):
        _switch(False)
        _full()
        body = self.client.get("/big-money/").content.decode()
        self.assertIn("The board is off. The newest read below is from", body)
        self.assertIn("Equities ran ahead of bonds", body)

    def test_a_stale_read_is_shown_not_current(self):
        _switch(True)
        _full(now=timezone.now() - timedelta(hours=40))
        body = self.client.get("/big-money/").content.decode()
        self.assertIn("hours old: shown, not current.", body)

    def test_the_record_and_the_cost_line(self):
        from tests.test_big_money_board import plant_record
        plant_record("rebalance", "us_equities", 45, proxy="SPX500")
        instrument("SPX500")
        body = self.client.get("/big-money/").content.decode()
        self.assertIn(W.VERDICT_AGAINST, body)
        self.assertIn(W.ZEROED, body)
        self.assertIn("round trip for index: 8 bp", body)

    def test_login_is_required(self):
        self.client.logout()
        self.assertEqual(self.client.get("/big-money/").status_code, 302)
        self.assertEqual(self.client.get(NOTE + "?symbol=SPX500&side=BUY")
                         .status_code, 302)

    def test_the_nav_links_the_page(self):
        """◆, not the spec's ◈: that glyph is Signals', and the rail refuses
        a shared shape (tests/test_nav_grouping.py)."""
        body = self.client.get("/big-money/").content.decode()
        self.assertIn('href="/big-money/"', body)
        self.assertIn("<span class=\"icon\">◆</span> <span class=\"label-text\">"
                      "Big Money</span>", body)
        self.assertIn("◆ BIG MONEY", body)


class TicketNoteTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user("bm_t", password="x")
        self.client.force_login(self.user)
        _switch(True)
        instrument("SPX500")
        instrument("USDCAD", "forex")
        instrument("EURUSD", "forex")
        instrument("EURCHF", "forex")
        instrument("XAGUSD", "commodity")
        instrument("SAP", "stock", "XETRA")

    def _note(self, symbol, side):
        resp = self.client.get(NOTE, {"symbol": symbol, "side": side})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(set(data), {"ok", "words", "as_of", "label", "suffix"})
        self.assertEqual(data["label"], "BIG MONEY")
        self.assertEqual(data["suffix"], "Information, never a gate.")
        return data

    def test_with_and_against(self):
        _full()
        against = self._note("SPX500", "BUY")
        self.assertTrue(against["ok"])
        self.assertTrue(against["words"].startswith(
            "US equities: Leans down this week (month-end rebalancing). "
            "Your buy is against it."), against)
        self.assertIn(" Crowding: Speculators heavy long", against["words"])
        self.assertIn(" Trend followers: long on 3 of three horizons.",
                      against["words"])
        self.assertIn(" Ahead: Month-end", against["words"])
        self.assertIn(" UTC.", against["words"])
        self.assertIn("Your sell is with it.", self._note("SPX500", "SELL")["words"])

    def test_the_pair_form(self):
        _full()
        words = self._note("USDCAD", "BUY")["words"]
        self.assertTrue(words.startswith(
            "Dollar: leans up this week (month-end hedge flows at the fix). "
            "Your buy of USDCAD buys the dollar: with it."), words)

    def test_the_fix_pair_form(self):
        _full()
        words = self._note("EURUSD", "SELL")["words"]
        self.assertTrue(words.startswith(
            "EURUSD: the month-end fix leans against EUR (+1.2 sd). Your sell "
            "is with it."), words)

    def test_a_commodity(self):
        _full()
        words = self._note("XAGUSD", "BUY")["words"]
        self.assertTrue(words.startswith(
            "XAGUSD: leans down this week (the speculators' weekly change, "
            "faded). Your buy is against it."), words)

    def test_no_clear_lean_and_unread(self):
        _full()
        instrument("GLD", "etf")
        instrument("WTIUSD", "commodity")
        self.assertTrue(self._note("GLD", "BUY")["words"].startswith(
            "Gold: no clear lean this week. Your buy meets no lean."))
        self.assertTrue(self._note("WTIUSD", "BUY")["words"].startswith(
            "Unread: COT: no report for WTIUSD"))

    def test_outside_the_board(self):
        _full()
        self.assertEqual(self._note("SAP", "BUY")["words"], W.TICKET_OUTSIDE)
        self.assertEqual(self._note("EURCHF", "BUY")["words"], W.TICKET_OUTSIDE)

    def test_off(self):
        _full()
        _switch(False)
        self.assertEqual(self._note("SPX500", "BUY")["words"], W.TICKET_OFF)

    def test_stale_and_none(self):
        self.assertEqual(self._note("SPX500", "BUY")["words"], W.TICKET_NONE)
        _full(now=timezone.now() - timedelta(hours=40))
        words = self._note("SPX500", "BUY")["words"]
        self.assertTrue(words.startswith("The newest read is "), words)
        self.assertTrue(words.endswith("hours old: not shown as current."))

    def test_an_error_is_said(self):
        _full()
        with mock.patch("bigmoney.read.newest", side_effect=RuntimeError("x")):
            data = self._note("SPX500", "BUY")
        self.assertFalse(data["ok"])
        self.assertEqual(data["words"], "The board could not be read (RuntimeError).")

    def test_the_ticket_fills_its_own_slot_after_rendering(self):
        """Never inside the order preview: _execute calls _preview."""
        from django.conf import settings
        from pathlib import Path
        base = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")
        self.assertIn('class="sz-note sz-bigmoney" data-role="bigmoney"', base)
        self.assertIn("fetch('/api/big-money/note/?symbol='", base)
        self.assertIn("setTimeout(function () { if (ctl) ctl.abort(); }, 3000)",
                      base)
        src = (Path(settings.BASE_DIR) / "bot_program" / "manual_trade.py"
               ).read_text(encoding="utf-8")
        self.assertNotIn("bigmoney", src)


class BriefTests(TestCase):

    def _morning(self):
        from alerts.scheduled_digests import digest_lines, generate_morning_digest
        with mock.patch("alerts.digest_book.add_book"):
            digest = generate_morning_digest()
        return digest, [str(x) for x in digest_lines(digest)]

    def test_absent_while_off(self):
        _switch(False)
        _full()
        digest, _ = self._morning()
        self.assertNotIn("big_money", digest["sections"])

    def test_present_when_on(self):
        _switch(True)
        _full()
        digest, lines = self._morning()
        section = digest["sections"]["big_money"]["lines"]
        self.assertIn("• US equities: leans down this week (month-end "
                      "rebalancing) · heavy long", section)
        self.assertIn("• XAGUSD: leans down this week (the speculators' weekly "
                      "change, faded)", section)
        self.assertTrue(any(s.startswith("• Ahead: Month-end") for s in section))
        self.assertTrue(any(s.startswith("• Unread: ") for s in section))
        self.assertEqual(len(section), 9)       # six markets, one more, two tails
        self.assertIn("Big money", lines)

    def test_the_tide_takes_the_free_line(self):
        from bigmoney.read import brief_lines
        _switch(True)
        _stored(rows=ROWS_FIXTURE, global_cells=GLOBAL_FIXTURE)
        self.assertIn("• Tide: dollar liquidity adding over 4 weeks (context, "
                      "weak evidence)", brief_lines())

    def test_a_stale_read_is_not_shown(self):
        from bigmoney.read import brief_lines
        _full(now=timezone.now() - timedelta(hours=40))
        lines = brief_lines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith("hours old: not shown"))

    def test_no_read_yet(self):
        from bigmoney.read import brief_lines
        self.assertEqual(brief_lines(), ["• No read yet"])


class RegistryTests(TestCase):

    def test_the_switch_seeds_off_fits_and_moves_no_money(self):
        from core.platform_control import (BULK_ENABLE_EXEMPT, DEFAULT_COMPONENTS,
                                           LIVE_MONEY_SWITCHES, PlatformComponent,
                                           seed_components)
        seed_components()
        row = PlatformComponent.objects.get(key="big_money_board")
        self.assertFalse(row.is_enabled)
        self.assertEqual(row.category, "pipeline")
        comp = [c for c in DEFAULT_COMPONENTS if c["key"] == "big_money_board"][0]
        self.assertLessEqual(len(comp["description"]), 300)
        self.assertNotIn("big_money_board", LIVE_MONEY_SWITCHES)
        self.assertNotIn("big_money_board", BULK_ENABLE_EXEMPT)

    def test_the_beat_the_stage_the_wiring_and_the_route(self):
        from celery.app.routes import MapRoute
        from celery.schedules import crontab
        from config.celery import app
        from core.day_of_sauron import STAGE_OF
        from dashboard.views_topology import WIRING, _expected_cadence
        beat = app.conf.beat_schedule
        am, pm = beat["big-money-board"], beat["big-money-board-evening"]
        for entry in (am, pm):
            self.assertEqual(entry["task"], "bigmoney.tasks.compute_big_money_board")
            self.assertIsInstance(entry["schedule"], crontab)
        self.assertEqual(am["kwargs"], {"run": "morning"})
        self.assertEqual(pm["kwargs"], {"run": "evening"})
        self.assertEqual(am["schedule"].hour, {5})
        self.assertEqual(am["schedule"].minute, {20})
        self.assertEqual(pm["schedule"].hour, {23})
        self.assertEqual(pm["schedule"].day_of_week, {1, 2, 3, 4, 5})
        self.assertEqual(STAGE_OF["big-money-board"][0], "think")
        self.assertEqual(STAGE_OF["big-money-board-evening"][0], "think")
        node = WIRING["big_money_board"]
        self.assertEqual(node["task"], "bigmoney.tasks.compute_big_money_board")
        self.assertEqual(node["pages"], ["/big-money/"])
        for key in node["feeds"]:
            self.assertIn(key, WIRING)
        self.assertEqual(_expected_cadence("big_money_board"), 86400.0)
        self.assertEqual(
            (MapRoute(app.conf.task_routes)(
                "bigmoney.tasks.compute_big_money_board") or {}).get("queue"),
            "slow")

    def test_the_task_is_registered(self):
        from config.celery import app
        app.loader.import_default_modules()
        self.assertIn("bigmoney.tasks.compute_big_money_board", set(app.tasks))

    def test_the_five_fred_series_are_fetched_but_never_reach_the_horizon(self):
        """The monthly horizon puts every FRED_SERIES entry, without units,
        into the snapshot whose class tilts size live pools
        (brain/horizon.py _read_macro): the board's liquidity series are
        fetched by the FRED task beside that list, never inside it."""
        from core.constants import FRED_SERIES
        from core.platform_control import PlatformComponent, seed_components
        from market_data.tasks import fetch_fred_updates
        five = ("WALCL", "WTREGEN", "RRPONTSYD", "WRESBAL", "WMTSECL1")
        for s in five:
            self.assertNotIn(s, FRED_SERIES)
        seed_components()
        PlatformComponent.objects.filter(
            key__in=("platform_master", "scraper_fred")).update(is_enabled=True)
        with mock.patch("market_data.adapters.fred_adapter.save_series_to_db",
                        return_value={"parsed": 1,
                                      "observations_saved": 1}) as save:
            out = fetch_fred_updates.run()
        fetched = [c.args[0] for c in save.call_args_list]
        for s in five + ("VIXCLS", "VXVCLS", "BAMLH0A0HYM2"):
            self.assertIn(s, fetched)
        self.assertEqual(len(fetched), len(set(fetched)))
        self.assertTrue(set(FRED_SERIES) <= set(fetched))
        self.assertEqual(out["status"], "success")

    def test_the_crypto_daily_close_runs_before_the_morning_read(self):
        from celery.app.routes import MapRoute
        from config.celery import app
        from core.day_of_sauron import STAGE_OF
        from market_data.tasks import fetch_eod_crypto
        beat = app.conf.beat_schedule
        entry = beat["fetch-eod-crypto"]
        self.assertEqual(entry["task"], "market_data.tasks.fetch_eod_crypto")
        self.assertEqual((entry["schedule"].hour, entry["schedule"].minute),
                         ({0}, {10}))
        am = beat["big-money-board"]["schedule"]
        self.assertLess((0, 10), (min(am.hour), min(am.minute)))
        self.assertEqual(STAGE_OF["fetch-eod-crypto"][0], "see")
        self.assertEqual(fetch_eod_crypto.run.component_key, "scraper_eod")
        self.assertEqual((MapRoute(app.conf.task_routes)(
            "market_data.tasks.fetch_eod_crypto") or {}).get("queue"), "slow")

    def test_the_cot_is_read_again_after_a_monday_release(self):
        from celery.schedules import crontab
        from config.celery import app
        from core.day_of_sauron import STAGE_OF
        entry = app.conf.beat_schedule["fetch-cot-reports-after-monday"]
        self.assertEqual(entry["task"], "scraping.tasks.fetch_cot_reports")
        self.assertIsInstance(entry["schedule"], crontab)
        self.assertEqual(entry["schedule"].day_of_week, {2})       # Tuesday
        self.assertEqual((entry["schedule"].hour, entry["schedule"].minute),
                         ({0}, {10}))
        self.assertEqual(STAGE_OF["fetch-cot-reports-after-monday"][0], "see")


class CryptoDailyCloseTests(TestCase):
    """market_data.tasks.fetch_eod_crypto: the crypto 1d bar nothing else
    on the beat writes. Binance is mocked: no network."""

    def setUp(self):
        from core.platform_control import PlatformComponent, seed_components
        seed_components()
        PlatformComponent.objects.filter(
            key__in=("platform_master", "scraper_eod")).update(is_enabled=True)
        instrument("BTCUSD", "crypto")
        instrument("ETHUSD", "crypto")

    def _kline(self, day, close):
        from datetime import datetime, time
        ms = int(datetime.combine(day, time(0), tzinfo=UTC).timestamp() * 1000)
        return [ms, str(close), str(close), str(close), str(close), "10.5",
                ms + 86_399_999]

    def _feed(self, rows_by_symbol):
        feed = mock.Mock()
        feed.klines.side_effect = (
            lambda sym, interval, limit: rows_by_symbol.get(sym, []))
        return feed

    def test_it_writes_the_daily_bars_and_keeps_the_rows_verdict(self):
        from bigmoney.inputs import Store
        from core.platform_control import PlatformComponent
        from market_data.models import PriceData
        from market_data.tasks import fetch_eod_crypto
        PlatformComponent.objects.filter(key="scraper_eod").update(
            last_status="warning", last_message="the 22:30 pass")
        feed = self._feed({
            "BTCUSDT": [self._kline(date(2026, 10, 8), 61000),
                        self._kline(date(2026, 10, 9), 62000)],
            "ETHUSDT": [self._kline(date(2026, 10, 9), 2400)]})
        with mock.patch("market_data.public_feed.public_feed_for",
                        return_value=feed), \
                mock.patch("market_data.bot_bars._venue_symbol",
                           side_effect=lambda client, s: s[:-3] + "USDT"):
            out = fetch_eod_crypto.run()
        self.assertEqual(out["bars_saved"], 3)
        self.assertTrue(out.get("idle"))
        bars = PriceData.objects.filter(instrument__symbol="BTCUSD",
                                        timeframe="1d")
        self.assertEqual(bars.count(), 2)
        self.assertEqual(set(bars.values_list("source", flat=True)),
                         {"binance_public"})
        self.assertEqual(Store().close_on_or_before("BTCUSD", date(2026, 10, 9)),
                         (date(2026, 10, 9), 62000.0))
        self.assertEqual(feed.klines.call_args.kwargs["interval"], "1d")
        row = PlatformComponent.objects.get(key="scraper_eod")
        self.assertEqual((row.last_status, row.last_message),
                         ("warning", "the 22:30 pass"))

    def test_a_missed_board_close_is_a_warning_in_its_own_words(self):
        from core.platform_control import PlatformComponent
        from core.task_gate import judge_result
        from market_data.tasks import fetch_eod_crypto

        def boom(sym, interval, limit):
            raise ConnectionError("binance down")
        feed = mock.Mock()
        feed.klines.side_effect = boom
        with mock.patch("market_data.public_feed.public_feed_for",
                        return_value=feed):
            out = fetch_eod_crypto.run()
        self.assertEqual(out["status"], "warning")
        self.assertTrue(out["reason"].startswith(
            "crypto daily close: no Binance daily bar for BTCUSD, ETHUSD"),
            out["reason"])
        self.assertEqual(judge_result(out), ("warning", out["reason"]))
        self.assertEqual(PlatformComponent.objects.get(
            key="scraper_eod").last_status, "warning")

    def test_the_adapter_stores_units(self):
        from market_data.adapters import fred_adapter as fa
        from market_data.models import MacroIndicator
        info = {"id": "RRPONTSYD", "title": "Overnight Reverse Repo",
                "frequency": "D", "units": "Billions of U.S. Dollars",
                "last_updated": ""}
        with mock.patch.dict("os.environ", {"FRED_API_KEY": "test-key"}), \
                mock.patch.object(fa, "fetch_series_info", return_value=info), \
                mock.patch.object(fa, "fetch_series", return_value=[]) as fs:
            fa.save_series_to_db("RRPONTSYD")
            self.assertEqual(fs.call_args.kwargs["limit"], 500)
            fa.save_series_to_db("RRPONTSYD", limit=2000)
            self.assertEqual(fs.call_args.kwargs["limit"], 2000)
        ind = MacroIndicator.objects.get(series_id="RRPONTSYD")
        self.assertEqual(ind.metadata["units"], "Billions of U.S. Dollars")
        with mock.patch.dict("os.environ", {"FRED_API_KEY": "test-key"}), \
                mock.patch.object(fa, "fetch_series_info", return_value=None), \
                mock.patch.object(fa, "fetch_series", return_value=[]):
            fa.save_series_to_db("RRPONTSYD")
        ind.refresh_from_db()
        self.assertEqual(ind.metadata["units"], "Billions of U.S. Dollars")


class CommandTests(TestCase):

    def _run(self, *args):
        out = StringIO()
        call_command("big_money", *args, stdout=out)
        return out.getvalue()

    def test_show_with_nothing(self):
        self.assertIn("No read yet.", self._run("show"))

    def test_show_a_read(self):
        _full()
        out = self._run("show", "--row", "us_equities")
        self.assertIn("US equities: Leans down (month-end rebalancing)", out)
        self.assertIn("risk: heavy long", out)

    def test_symbols_prints_the_backfill_line(self):
        out = self._run("symbols")
        self.assertTrue(out.startswith("python manage.py backfill_bars --symbols "
                                       "SPX500,AGG,TLT,DXY,XAUUSD,WTIUSD,BTCUSD,"
                                       "SPY,UUP,GLD,USO,IBIT,STOXX50,FTSE100,"
                                       "NIKKEI225,ASX200,EURUSD,GBPUSD,USDJPY,"
                                       "AUDUSD"), out)
        self.assertIn(" --intervals 1d --bars 1600", out)

    def test_replay_and_fred_history_ask_first(self):
        self.assertIn("--yes runs it",
                      self._run("replay", "--from", "2026-10-01",
                                "--to", "2026-10-09"))
        self.assertIn("--yes runs it", self._run("fred-history"))
        with mock.patch.dict("os.environ", {"FRED_API_KEY": ""}):
            with self.assertRaises(CommandError):
                self._run("fred-history", "--yes")

    def test_fred_history_pulls_two_thousand(self):
        with mock.patch.dict("os.environ", {"FRED_API_KEY": "k"}), \
                mock.patch("market_data.adapters.fred_adapter.save_series_to_db",
                           return_value={"parsed": 3, "created": 3,
                                         "revised": 0}) as save:
            out = self._run("fred-history", "--yes")
        self.assertEqual(save.call_count, 8)
        self.assertEqual({c.kwargs["limit"] for c in save.call_args_list}, {2000})
        self.assertIn("WALCL: 3 observations", out)

    def test_compute_stores_a_manual_read(self):
        from bigmoney.models import BigMoneyRead
        seed_equity_and_bonds()
        out = self._run("compute")
        self.assertIn("stored as manual", out)
        self.assertEqual(set(BigMoneyRead.objects.values_list("run", flat=True)),
                         {"manual"})
        self.assertFalse(BigMoneyRead.objects.filter(replayed=True).exists())

    def test_compute_reads_with_the_runs_rules_and_stores_manual(self):
        """--run evening reads with the evening's rules (the read's own run)
        and is still stored as manual: never a morning or evening row."""
        from bigmoney.models import BigMoneyRead
        from bigmoney.read import read_board as real_read_board
        seed_equity_and_bonds()
        with mock.patch("bigmoney.read.read_board",
                        wraps=real_read_board) as rb:
            out = self._run("compute", "--run", "evening")
        self.assertEqual(rb.call_args.kwargs["run"], "evening")
        self.assertIn("(evening rules) stored as manual", out)
        self.assertEqual(set(BigMoneyRead.objects.values_list("run", flat=True)),
                         {"manual"})
        with mock.patch("bigmoney.read.read_board",
                        wraps=real_read_board) as rb:
            self._run("compute")
        self.assertEqual(rb.call_args.kwargs["run"], "morning")

    def test_a_past_date_is_read_point_in_time(self):
        from bigmoney.models import BigMoneyRead
        seed_equity_and_bonds()
        past = (timezone.now() - timedelta(days=20)).date()
        out = self._run("compute", "--date", past.isoformat())
        self.assertIn("point in time", out)
        self.assertTrue(BigMoneyRead.objects.filter(
            replayed=True, as_of=past, run="manual").exists())

    def test_a_future_date_is_refused_and_nothing_stored(self):
        """A live row dated in the future would shadow every beat read on
        the page, the brief and the ticket until that day passed."""
        from bigmoney.models import BigMoneyRead
        future = (timezone.now() + timedelta(days=30)).date()
        with self.assertRaises(CommandError) as cm:
            self._run("compute", "--date", future.isoformat())
        self.assertIn("is after the live as-of day", str(cm.exception))
        self.assertFalse(BigMoneyRead.objects.exists())

    def test_replay_writes_replayed_rows(self):
        from bigmoney.models import BigMoneyRead
        seed_equity_and_bonds()
        out = self._run("replay", "--from", "2026-10-22", "--to", "2026-10-27",
                        "--yes")
        self.assertIn("Replayed 4 days", out)
        self.assertEqual(BigMoneyRead.objects.filter(replayed=False).count(), 0)
        self.assertEqual(sorted({r.as_of for r in BigMoneyRead.objects.all()}),
                         [date(2026, 10, 22), date(2026, 10, 23),
                          date(2026, 10, 26), date(2026, 10, 27)])
        reb = BigMoneyRead.objects.get(as_of=date(2026, 10, 23), row="us_equities")
        self.assertEqual(reb.cells["rebalance"]["state"], "read")
        self.assertEqual(reb.cells["stress"]["why"] if "stress" in reb.cells
                         else W.R_NOT_REPLAYED, W.R_NOT_REPLAYED)
        g = BigMoneyRead.objects.get(as_of=date(2026, 10, 23), row="global")
        self.assertEqual(g.cells["stress"]["why"], W.R_NOT_REPLAYED)
        self.assertEqual(g.run, "replay")

    def test_record_prints_both_records(self):
        out = self._run("record")
        self.assertIn("Live record", out)
        self.assertIn("Replayed record", out)


class ContractTests(TestCase):
    """bigmoney.read's contract (spec §2.12): what PR2 and PR8 build on.
    Every function answers; none raises."""

    def test_market_for_a_row_and_an_instrument(self):
        from bigmoney.read import market
        _full()
        eq = market("us_equities")
        self.assertTrue(eq["ok"])
        self.assertEqual(eq["label"], W.LEANS_DOWN)
        self.assertEqual(eq["from"], ["month-end rebalancing"])
        self.assertEqual(eq["risk"], ["heavy long"])
        self.assertEqual(eq["record"], [])
        ag = market("XAGUSD")
        self.assertTrue(ag["ok"])
        self.assertEqual(ag["label"], W.LEANS_DOWN)
        self.assertEqual(ag["risk"], ["crowded long"])
        self.assertFalse(market("NOPE")["ok"])

    def test_a_read_that_fails_is_said_on_the_ticket(self):
        from bigmoney.read import ticket_words
        _switch(True)
        failed = {"ok": False, "reads": {},
                  "reason": "The board could not be read (OperationalError)."}
        with mock.patch("bigmoney.read.newest", return_value=failed):
            self.assertEqual(ticket_words("SPX500", "BUY")["words"],
                             failed["reason"])

    def test_blind_names_every_unread_input_once(self):
        from bigmoney.read import blind
        _full()
        reasons = [b["reason"] for b in blind()]
        self.assertIn("COT: no report for WTIUSD (no futures market maps to it)",
                      reasons)
        self.assertEqual(len(reasons), len(set(reasons)))

    def test_ahead_without_a_read_computes_from_the_rules(self):
        from bigmoney.read import ahead
        rows = ahead(40)
        self.assertTrue(rows)
        self.assertTrue(any(e["event"] == W.EV_MONTH_END for e in rows))
        today = timezone.now().date().isoformat()
        self.assertTrue(all(e["date"] >= today for e in rows))

    def test_newest_reads_the_live_rows_only(self):
        """A replay run up to yesterday writes replayed rows dated after the
        live read, and later: the page, the brief and the ticket still read
        the live rows (spec §2.7: never pooled)."""
        from bigmoney.read import brief_lines, newest, ticket_words
        _switch(True)
        _stored(as_of=date(2026, 10, 8), rows=ROWS_FIXTURE,
                now=timezone.now() - timedelta(hours=1))
        _stored(as_of=date(2026, 10, 9), replayed=True, run="replay",
                rows={"us_equities": {"lean": 0.9, "lean_label": W.LEANS_UP,
                                      "lean_from": ["replayed"]}})
        head = newest(max_age_h=None)
        self.assertEqual(head["as_of"], date(2026, 10, 8))
        self.assertEqual(head["reads"]["us_equities"].lean_label, W.LEANS_DOWN)
        lines = brief_lines(head=head | {"ok": True})
        self.assertIn("• US equities: leans down this week (month-end "
                      "rebalancing) · heavy long", lines)
        self.assertTrue(ticket_words("SPX500", "BUY")["words"].startswith(
            "US equities: Leans down this week"))

    def test_newest_refuses_an_old_read_with_the_reason(self):
        from bigmoney.read import newest
        _full(now=timezone.now() - timedelta(hours=31))
        head = newest()
        self.assertFalse(head["ok"])
        self.assertTrue(head["reads"])
        self.assertTrue(head["reason"].startswith("The newest read is 31 hours"))
        self.assertTrue(newest(max_age_h=None)["ok"])
