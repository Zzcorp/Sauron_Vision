"""THE ORCS' BARS (market_data/bot_bars._orc_held, spec §5.2, §6.1, §1.6):
with the `orcs` switch OFF the bar refresh asks exactly what it asked
before. ON, every config's pass comes first and asks exactly what it asks
OFF: the Orcs' parts come LAST (the real ideas whose row closed while an
arm still walks its bars, then the living paper ideas under the paper cap
and the dead ones still walking their tail), cut by the pass's deadline
like a config, stamping no venue mark, and leaving the watchlist the very
`unreached` set it gets OFF and a `covered` set that also holds what an
Orc part reached (the venue owns that series). A 429 in an Orc part can
therefore never send a config's decision bars to the public feed, nor
take a config's place in the pass's dedup. An idea a bar past its tail
cap asks nothing more.

No 1d candle is asked: the Orcs' daily frame is the venue's own 4h bars
grouped by UTC day (bot_program/orcs/bars.py), so no second daily grid
sits beside the nightly EOD bars that every unfiltered 1d reader reads.

Run with:  python manage.py test tests.orcs.test_orc_bar_refresh
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from unittest.mock import patch

from tests.orcs.helpers import _on, _switch
from tests.test_bars_etoro_quota import H, _Base, _Wire


class _DayWire(_Wire):
    ENUM = {**_Wire.ENUM, "OneDay": 24 * H}


def _orc_for(row, *, army="line", tracks_open=True):
    """An Orc on `row`, written directly (the birth is tested elsewhere)."""
    from bot_program.orcs.models import Orc, OrcLeg, OrcSeat, OrcTrack
    seat, _ = OrcSeat.objects.get_or_create(
        venue="paper" if row.paper else "live",
        asset_class=row.asset_class, rule_key="*")
    orc = Orc.objects.create(
        seat=seat, user=row.config.user, config=row.config, root_trade=row,
        symbol=row.symbol, side=row.side, asset_class=row.asset_class,
        paper=row.paper, army_type=army,
        state="dead" if row.status != "OPEN" else "born")
    OrcLeg.objects.create(orc=orc, trade=row, kind="root", seq=1)
    OrcTrack.objects.create(orc=orc, arm="care", state={}, open=tracks_open)
    return orc


def _yf_daily(symbol, days=30):
    """The nightly EOD job's 1d bars (yfinance, Yahoo's anchor): what every
    unfiltered 1d reader reads today."""
    from instruments.models import Instrument
    from market_data.models import PriceData
    inst = Instrument.objects.get(symbol=symbol)
    today = datetime.now(dt_tz.utc).replace(hour=4, minute=0, second=0,
                                            microsecond=0)
    for d in range(days, 0, -1):
        PriceData.objects.create(
            instrument=inst, timeframe="1d",
            timestamp=today - timedelta(days=d), open=Decimal("100"),
            high=Decimal("101"), low=Decimal("99"), close=Decimal("100.5"),
            volume=1, source="yfinance")


class _OrcBase(_Base):
    SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "AAPL", "SPY", "XAUUSD",
               "MSFT")

    def setUp(self):
        super().setUp()
        from instruments.models import Instrument
        for sym, cls in (("AAPL", "stock"), ("SPY", "etf"),
                         ("XAUUSD", "commodity"), ("MSFT", "stock")):
            Instrument.objects.filter(symbol=sym).update(asset_class=cls)
        ids = {s: 1000 + i for i, s in enumerate(self.SYMBOLS)}
        ids["XAUUSD"] = 18          # gold is pinned (VENUE_ID_PINS)
        self.wire = _DayWire(ids)
        _switch("platform_master")

    def _row(self, symbol, cls, *, paper=False, status="OPEN", cfg=None):
        from bot_program.models import AssetBotTrade
        cfg = cfg or self._cfg([], mode="paper" if paper else "live",
                               name=f"lane {symbol} {paper}",
                               asset_class=cls)
        return AssetBotTrade.objects.create(
            config=cfg, asset_class=cls, symbol=symbol, side="BUY",
            status=status, qty=Decimal("1"), entry_price=Decimal("100"),
            stop_loss=Decimal("98"), take_profit=Decimal("110"), paper=paper)

    def _iid(self, symbol):
        return f"/instruments/{self.wire.ids[symbol]}/"

    def _asked(self, symbol, enum):
        return [u for u in self.wire.candle_calls()
                if self._iid(symbol) in u and f"/{enum}/" in u]

    def _order(self):
        order = []
        for u in self.wire.candle_calls():
            sym = next(s for s in self.SYMBOLS if self._iid(s) in u)
            if sym not in order:
                order.append(sym)
        return order

    def _reset(self):
        """A fresh pass: no bar stored, no memo, no wire call recorded."""
        from django.core.cache import cache

        from bot_program import venue_health
        from bot_program.engine import etoro_client as ec
        from market_data.models import PriceData
        PriceData.objects.all().delete()
        cache.clear()
        venue_health.reset()
        for memo in (ec._SEARCH_IDS, ec._SEARCH_NO, ec._RATE_PAUSE):
            memo.clear()
        self.wire.calls = []
        self.feed.calls = []
        from tests.test_bars_etoro_quota import _Clock
        self.clock = _Clock()

    def _wl(self):
        """What the watchlist was handed, but for its bound `stop` (the
        pass's own deadline method, a new object every pass) and O1c's
        `also` (the board of market symbols that joins the held part while
        `orcs` is ON; tests/orcs/test_orc_tape.py pins it, and that it is
        absent OFF)."""
        kw = dict(self.wl.call_args.kwargs)
        kw.pop("stop", None)
        kw.pop("also", None)
        return kw

    def _late_after(self, n_clients):
        """`_client_for` that moves the pass's clock past its deadline on
        its n-th call: everything the pass asks after that is cut."""
        from market_data import bot_bars
        clock, seen = self.clock, {"n": 0}

        def late(*a, **k):
            seen["n"] += 1
            if seen["n"] == n_clients:
                clock.t += bot_bars.BARS_PASS_MAX_S
            return self._client()
        return late


class TheSwitchOffTests(_OrcBase):

    def test_off_requests_byte_identical_with_orc_rows_present(self):
        from bot_program.orcs.models import Orc
        _on(False)
        self._cfg(["EURUSD"], mode="live", name="A live")
        self._cfg(["GBPUSD"], name="B paper")
        _orc_for(self._row("AAPL", "stock"))
        _orc_for(self._row("XAUUSD", "commodity", status="CLOSED"),
                 army="olog_hai")
        _orc_for(self._row("SPY", "etf", paper=True))
        with_orcs = self._run()
        calls = list(self.wire.calls)
        wl = self._wl()
        self._reset()
        Orc.objects.all().delete()
        without = self._run()
        self.assertEqual(calls, self.wire.calls)
        self.assertEqual(with_orcs, without)
        self.assertEqual(wl, self._wl())
        self.assertFalse(any("/OneDay/" in u for u in calls))
        self.assertNotIn("orcs", with_orcs)


class TheOrcPartsTests(_OrcBase):

    def setUp(self):
        super().setUp()
        _on()

    def test_on_no_daily_candle_is_asked_and_no_second_daily_grid(self):
        from market_data.models import PriceData
        _yf_daily("AAPL")
        _orc_for(self._row("AAPL", "stock"))
        _orc_for(self._row("SPY", "etf", paper=True))
        _orc_for(self._row("XAUUSD", "commodity", status="CLOSED"),
                 army="olog_hai")
        _orc_for(self._row("EURUSD", "forex"), army="olog_hai")
        daily = list(PriceData.objects.filter(timeframe="1d")
                     .values_list("pk", "source", "timestamp"))
        self._run()
        self.assertFalse(any("/OneDay/" in u for u in self.wire.calls),
                         "no 1d candle is asked")
        self.assertEqual(list(PriceData.objects.filter(timeframe="1d")
                              .values_list("pk", "source", "timestamp")),
                         daily, "the 1d series is the EOD job's alone")
        self.assertTrue(self._asked("XAUUSD", "FourHours"),
                        "the closed idea's 4h, from which its 1d is read")

    def test_a_closed_row_with_an_open_track_stays_until_the_track_closes(
            self):
        from bot_program.orcs.models import OrcTrack
        orc = _orc_for(self._row("GBPUSD", "forex", status="CLOSED"))
        self._run()
        self.assertEqual(len(self._asked("GBPUSD", "FourHours")), 1)
        self.assertEqual(len(self._asked("GBPUSD", "OneHour")), 1)
        self._reset()
        OrcTrack.objects.filter(orc=orc).update(open=False)
        self._run()
        self.assertEqual(self.wire.candle_calls(), [])

    def test_an_open_real_idea_asks_nothing_of_its_own(self):
        """An open real row is the configs' and the held rows' to refresh:
        the Orc part adds no request for it."""
        _orc_for(self._row("AAPL", "stock"))
        _orc_for(self._row("XAUUSD", "commodity"), army="olog_hai")
        self._run()
        self.assertEqual(len(self._asked("AAPL", "FourHours")), 1,
                         "once, by the held real rows")
        self.assertEqual(len(self._asked("XAUUSD", "FourHours")), 1)

    def test_paper_orc_symbols_join_capped(self):
        from bot_program.orcs.models import OrcSetting
        _orc_for(self._row("GBPUSD", "forex", paper=True))
        _orc_for(self._row("USDJPY", "forex", paper=True))
        self._run()
        self.assertTrue(self._asked("GBPUSD", "OneHour"))
        self.assertTrue(self._asked("USDJPY", "OneHour"))
        self._reset()
        OrcSetting.objects.create(key="max_paper_orcs", value=1)
        self._run()
        self.assertTrue(self._asked("GBPUSD", "OneHour"))
        self.assertEqual(self._asked("USDJPY", "OneHour"), [],
                         "the paper cap bounds the part")

    def _fleet(self):
        live = self._cfg(["EURUSD"], mode="live", name="A live")
        self._cfg(["MSFT"], name="Z paper", asset_class="stock")
        _orc_for(self._row("GBPUSD", "forex", status="CLOSED"))
        _orc_for(self._row("USDJPY", "forex", paper=True))
        return live

    def test_on_every_config_asks_exactly_what_it_asks_off(self):
        self._fleet()
        _on(False)
        off = self._run()
        calls_off = list(self.wire.calls)
        wl_off = self._wl()
        self._reset()
        _on(True)
        on = self._run()
        self.assertEqual(self.wire.calls[:len(calls_off)], calls_off,
                         "every config's requests, in the same order")
        extra = self.wire.calls[len(calls_off):]
        self.assertTrue(extra, "the Orcs' parts asked after them")
        self.assertTrue(all(self._iid("GBPUSD") in u or self._iid("USDJPY")
                            in u for u in extra if "/candles/" in u))
        for key in ("configs", "symbols", "bars", "deduped",
                    "not_reached", "errors", "fallback"):
            self.assertEqual(on[key], off[key], key)
        self.assertEqual(on["orcs"]["symbols"], 2)
        wl_on = self._wl()
        self.assertEqual(wl_on.pop("covered"),
                         wl_off.pop("covered") | {"GBPUSD", "USDJPY"},
                         "the venue owns what an Orc part reached")
        self.assertEqual(wl_on, wl_off)

    def test_orc_parts_come_last_and_are_cut_by_the_deadline(self):
        self._fleet()
        self._run()
        self.assertEqual(self._order(), ["EURUSD", "MSFT", "GBPUSD",
                                         "USDJPY"])
        self._reset()
        # the clock passes the deadline at the last config's client: that
        # config is still served (its eToro ask past the candle budget goes
        # to the public feed, as OFF), the Orcs' parts are cut
        out = self._run(client_for=self._late_after(2))
        self.assertEqual(out["not_reached"], 0, "no config was cut")
        self.assertIn(("MSFT", "4h"), self.feed.calls)
        self.assertEqual(out["orcs"]["not_reached"], 2)
        self.assertEqual(self._asked("GBPUSD", "FourHours")
                         + self._asked("USDJPY", "FourHours"), [])
        self.assertFalse([c for c in self.feed.calls
                          if c[0] in ("GBPUSD", "USDJPY")],
                         "the Orcs' parts are cut like a config")

    def test_on_an_orc_429_never_sends_a_config_to_the_public_feed(self):
        _orc_for(self._row("GBPUSD", "forex", status="CLOSED"))
        self.wire.refuse.add(("GBPUSD", "FourHours"))
        self._cfg(["EURUSD"], mode="live", name="A live")
        out = self._run()
        self.assertEqual(len(self._asked("EURUSD", "FourHours")), 1)
        self.assertEqual(len(self._asked("EURUSD", "OneHour")), 1)
        self.assertNotIn("EURUSD", [s for s, _tf in self.feed.calls],
                         "the live config's bars are the venue's")
        self.assertIn("429", out["etoro_stopped"])
        self.assertIn("GBPUSD", out["etoro_stopped"])

    def test_on_open_real_rows_keep_their_candle_stamp(self):
        """A closed real row's arm still walks EURUSD, which a live config
        trades: the config fetches first, so its candles stamp the venue
        mark on the open real rows, and the Orc part is deduped."""
        from market_data import bot_bars
        live = self._cfg(["EURUSD"], mode="live", name="A live")
        _orc_for(self._row("EURUSD", "forex", status="CLOSED", cfg=live))
        with patch.object(bot_bars, "_stamp_venue_rows",
                          return_value=0) as stamp:
            out = self._run()
        stamped = {(c.args[1], c.args[2]) for c in stamp.call_args_list}
        self.assertEqual(stamped, {("EURUSD", "4h"), ("EURUSD", "1h")})
        self.assertEqual(len(self._asked("EURUSD", "FourHours")), 1)
        self.assertEqual(out["orcs"]["deduped"], 2)

    def test_orc_candles_stamp_no_venue_mark(self):
        from market_data import bot_bars
        _orc_for(self._row("GBPUSD", "forex", status="CLOSED"))
        self._cfg(["EURUSD"], mode="live", name="A live")
        with patch.object(bot_bars, "_stamp_venue_rows",
                          return_value=0) as stamp:
            self._run()
        stamped = {(c.args[1], c.args[2]) for c in stamp.call_args_list}
        self.assertIn(("EURUSD", "4h"), stamped)
        self.assertTrue(self._asked("GBPUSD", "FourHours"),
                        "the Orc part ran")
        self.assertFalse([s for s in stamped if s[0] == "GBPUSD"],
                         "the Orcs' candles stamp no venue mark")

    def test_on_a_cut_config_symbol_keeps_its_watchlist_fallback(self):
        """A paper config the deadline cut: its symbol is unreached and
        the watchlist's to fill, ON exactly as OFF, though a paper Orc
        reads the same symbol."""
        self._cfg(["EURUSD"], mode="live", name="A live")
        b = self._cfg(["GBPUSD"], name="B paper")
        _orc_for(self._row("GBPUSD", "forex", paper=True, cfg=b))
        _on(False)
        self._run(client_for=self._late_after(1))
        wl_off = self._wl()
        self.assertEqual(wl_off["unreached"], {"GBPUSD"})
        self._reset()
        _on(True)
        self._run(client_for=self._late_after(1))
        self.assertEqual(self._wl(), wl_off)


# ── the review's findings (2026-10-22), each failing before its fix ──────

class _KlinesFeed:
    """The keyless public feed, answering a full window on the hour grid
    (the watchlist's held part writes it)."""
    _sv_public_feed = True

    def __init__(self):
        self.calls = []

    def klines(self, symbol, interval="1h", limit=200, **kw):
        self.calls.append((symbol, interval))
        step = H if interval == "1h" else 4 * H
        now = int(datetime.now(dt_tz.utc).timestamp() * 1000)
        last = (now // step) * step
        return [[last - (limit - 1 - i) * step, "1.3", "1.4", "1.2", "1.35",
                 "5"] for i in range(limit)]


class TheVenueOwnsWhatAnOrcReachedTests(_OrcBase):
    """THE WATCHLIST NEVER OVERWRITES AN ORC'S VENUE BARS. A paper Orc on a
    symbol no config lists, held by an open row: the Orc part wrote
    eToro's window, then the watchlist's held part wrote the public feed's
    over it in the same pass, and the next pass asked eToro the whole
    window again."""

    def _pass(self):
        from market_data import bot_bars
        feed = _KlinesFeed()
        with patch.object(bot_bars, "_client_for", side_effect=self._client), \
                patch.object(bot_bars, "_public_market_data_client",
                             return_value=feed), \
                patch("market_data.public_feed.public_feed_for",
                      return_value=feed), \
                patch.object(bot_bars, "_mono", self.clock.mono), \
                patch.object(bot_bars, "_candle_sleep", self.clock.sleep):
            bot_bars.refresh_bot_bars()
        return feed

    def test_a_paper_orc_symbol_no_config_lists_stays_the_venues(self):
        from bot_program.orcs import bars
        from market_data.models import PriceData
        _on()
        lane = self._cfg([], name="paper lane")
        _orc_for(self._row("USDJPY", "forex", paper=True, cfg=lane))
        asked = []
        for _ in range(2):
            self.wire.calls = []
            feed = self._pass()
            asked.append(self._asked("USDJPY", "OneHour"))
            self.assertEqual(set(PriceData.objects.filter(
                instrument__symbol="USDJPY", timeframe="1h")
                .values_list("source", flat=True)), {"etoro"})
            self.assertNotIn(("USDJPY", "1h"), feed.calls,
                             "the watchlist leaves the venue's series alone")
        self.assertEqual(len(asked[1]), 1)
        self.assertNotEqual(asked[1], asked[0],
                            "the second pass asks only what is new")
        f = bars.frame("USDJPY", "1h", asset_class="forex")
        self.assertEqual(f.source, "etoro")


class TheOrcSlotsTests(_OrcBase):
    """THE PAPER CAP BOUNDS THE LIVING IDEAS (§5.2). Dead paper ideas whose
    arms still walk their tail are older, so they took the slots first and
    the newest living ideas lost their venue bars."""

    def _paper_orc(self, cfg, symbol, *, dead=False, born=None):
        from bot_program.orcs.models import Orc
        from instruments.models import Instrument
        Instrument.objects.get_or_create(
            symbol=symbol, defaults={"name": symbol, "asset_class": "forex"})
        orc = _orc_for(self._row(symbol, "forex", paper=True, cfg=cfg,
                                 status="CLOSED" if dead else "OPEN"))
        Orc.objects.filter(pk=orc.pk).update(born_at=born or orc.born_at)
        return orc

    def test_the_cap_counts_living_ideas_and_the_tailing_ones_come_on_top(
            self):
        from datetime import timedelta

        from django.utils import timezone

        from bot_program.orcs.models import OrcSetting
        from market_data.bot_bars import _orc_held
        OrcSetting.objects.create(key="max_paper_orcs", value=3)
        cfg = self._cfg([], name="paper")
        now = timezone.now()
        for i in range(2):
            self._paper_orc(cfg, f"OLD{i}", dead=True,
                            born=now - timedelta(hours=10 + i))
        for i in range(3):
            self._paper_orc(cfg, f"NEW{i}", born=now - timedelta(minutes=i))
        got = sorted(s for h in _orc_held("paper") for s in h.symbols)
        self.assertEqual(got, ["NEW0", "NEW1", "NEW2", "OLD0", "OLD1"])

    def test_an_idea_past_its_cap_asks_nothing_more(self):
        from datetime import timedelta

        from django.utils import timezone

        from bot_program.models import AssetBotTrade
        from bot_program.orcs.models import Orc
        from market_data.bot_bars import _orc_held
        now = timezone.now()
        stuck = _orc_for(self._row("GBPUSD", "forex", status="CLOSED"))
        Orc.objects.filter(pk=stuck.pk).update(
            born_at=now - timedelta(days=30))
        AssetBotTrade.objects.filter(pk=stuck.root_trade_id).update(
            closed_at=now - timedelta(days=29))
        fresh = _orc_for(self._row("USDJPY", "forex", status="CLOSED"))
        AssetBotTrade.objects.filter(pk=fresh.root_trade_id).update(
            closed_at=now - timedelta(hours=1))
        self.assertEqual([h.symbols for h in _orc_held("real")], [["USDJPY"]])
        paper = self._paper_orc(self._cfg([], name="p"), "EURUSD", dead=True,
                                born=now - timedelta(days=30))
        AssetBotTrade.objects.filter(pk=paper.root_trade_id).update(
            closed_at=now - timedelta(days=29))
        self.assertEqual(_orc_held("paper"), [])
