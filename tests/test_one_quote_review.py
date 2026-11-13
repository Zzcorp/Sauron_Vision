"""ONE PRICE EVERYWHERE: the review's fixes, on the server (2026-11-12).

Two reviews measured the branch in Chromium and in the code (scratchpad
onequote/review_consistency.md, review_money-cost.md). What they found on
the server side, each pinned here on the synthetic fixture
(tests/one_quote_fixture.py, the clock held):

  * the position page's "Price now" printed the valuation's older stamp
    (1.08447) while the band on the same page printed eToro's newer read
    (1.08715): it is now the one price, a painted cell with its words,
    and its 15 s fragment carries its own quote block;
  * a region sweep (/positions/live/, /portfolio/live/) carried no quote
    block, so the painter put the page-load price back over the server's
    newer one; every sweep now carries the payloads of what it printed,
    and a fragment carries ONLY what it printed (the rail partial carried
    78 KB of headband answers at 237 symbols);
  * the market clock was read 565 times for 237 symbols (170 ms): it is
    read once per session now;
  * a shut market said "closed" only where a words cell exists, its time
    was Sauron's read after the close, and a previous close sat in the
    outside slot as a current quote;
  * the relay pushed held instruments only: a row a poller wrote for an
    instrument nobody holds reached each tab on its own sweep;
  * sparks never said whose bars they draw; leftover day-change cells
    printed a bare red "%" and a falling arrow with no change;
  * the figures beside a price (since entry, the card's distances, the
    rail's reward to risk) and the hovers stayed at the render's price;
  * the Horde dossier's peers were never repainted;
  * the news page asked the rule once per symbol.

Run with:  python manage.py test tests.test_one_quote_review
"""
import re
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from tests.one_quote_fixture import (
    T, daily_bar, instrument, previous_close_event, quote, seed_measured,
    stamp)
from tests.test_one_quote_screens import HOST, _parse, _Screens

#: Saturday 14 November 2026, 10:00 UTC: the forex week is shut.
SAT = datetime(2026, 11, 14, 10, 0, tzinfo=dt_tz.utc)


def _ms(dt):
    return int(round(dt.timestamp() * 1000))


def _syms(blocks):
    out = set()
    for b in blocks:
        out |= set((b.get("q") or {}).keys())
    return out


def _summary(html):
    """The position page's summary section (_position_summary.html)."""
    m = re.search(r'<section class="pd-sum.*?</section>', html, re.S)
    assert m, "no summary section"
    return m.group(0)


class ThePositionPageTests(_Screens):
    """C1: /forensics/<id>/ "Price now" is the one price."""

    def _newer_poll(self):
        """The stamp 180 s old, eToro's polled row 5 s old: the rule shows
        the poll's bid (1.08500), the valuation keeps the stamp's
        (1.08447, venue_mark.resolve prefers a stamp under 900 s)."""
        t = self.rows["EURUSD"]
        meta = dict(t.metadata)
        meta["venue_mark"] = stamp("1.08452", "1.08447", "1.08457", 180)
        t.metadata = meta
        t.save(update_fields=["metadata"])
        quote("EURUSD", "1.08505", "etoro", 5, bid="1.08500", ask="1.08510")
        return t

    def test_price_now_is_the_one_price(self):
        t = self._newer_poll()
        sh = self.shown()["EURUSD"]
        self.assertEqual(sh.text("bid"), "1.08500")
        html = self.page(f"/forensics/{t.id}/")
        self.check_cells(f"/forensics/{t.id}/", html)
        cells, blocks = _parse(_summary(html))
        cur = [c for c in cells if c["sym"] == "EURUSD" and c["f"] == "price"]
        self.assertEqual([c["text"] for c in cur], ["1.08500"], cells)
        self.assertEqual(cur[0]["side"], "bid")
        self.assertIn("valued for profit and loss at 1.08447",
                      cur[0]["attrs"].get("title", ""))
        words = [c["text"] for c in cells
                 if c["sym"] == "EURUSD" and c["f"] == "words"]
        self.assertEqual(words, [sh.words(T, side="bid")])
        self.assertEqual(words, ["eToro bid · 5 s"])
        self.assertTrue(blocks, "the summary carries its own block")
        self.assertEqual(blocks[0]["q"]["EURUSD"], sh.payload())

    def test_the_fifteen_second_fragment_carries_its_block(self):
        t = self._newer_poll()
        sh = self.shown()["EURUSD"]
        html = self.page(f"/forensics/{t.id}/live/")
        cells, blocks = _parse(_summary(html))
        self.assertIn("1.08500", [c["text"] for c in cells
                                  if c["sym"] == "EURUSD"])
        self.assertTrue(blocks, "the fragment the page swaps carries a block")
        self.assertEqual(blocks[0]["q"]["EURUSD"], sh.payload())


class TheSweepsTests(_Screens):
    """C2 / MC1 and MC5: a sweep and a fragment carry the block of what
    they printed, and only that."""

    def test_a_region_sweep_carries_the_block_of_its_rows(self):
        for url in ("/positions/live/", "/portfolio/live/"):
            r = self.client.get(url, HTTP_HOST=HOST, HTTP_X_SV_SWEEP="1")
            self.assertEqual(r.status_code, 200, url)
            html = r.content.decode("utf-8")
            cells, blocks = self.check_cells(url, html)
            syms = _syms(blocks)
            with self.subTest(url=url):
                self.assertTrue({"EURUSD", "XAUUSD", "AAPL"} <= syms, syms)
                self.assertNotIn("GBPUSD", syms,
                                 "the sweep prints no headband: its answer "
                                 "is not in the block")
                printed = {c["sym"].upper() for c in cells}
                self.assertLessEqual(syms, printed)

    def test_a_fragment_carries_only_what_it_printed(self):
        html = self.page("/command/tab/portfolio/")
        _cells, blocks = _parse(html)
        syms = _syms(blocks)
        self.assertIn("EURUSD", syms)
        self.assertNotIn("GBPUSD", syms, syms)

    def test_a_full_page_still_carries_its_shell(self):
        html = self.page("/positions/")
        _cells, blocks = _parse(html)
        self.assertIn("GBPUSD", _syms(blocks))


class TheClockIsReadOncePerSessionTests(TestCase):
    """MC2: 237 symbols read the market clock 565 times (170 ms)."""

    def setUp(self):
        from instruments.models import Instrument
        from market_data.models import LiveQuote
        self.syms = []
        for i in range(40):
            sym = "Q%02dUSD" % i
            inst = Instrument.objects.create(
                symbol=sym, name=sym, asset_class="forex", exchange="FX",
                currency="USD", is_active=True)
            LiveQuote.objects.create(instrument=inst, last=Decimal("1.1"),
                                     source="yfinance",
                                     change_pct=Decimal("0"), volume=0)
            self.syms.append(sym)
        for sym, exch in (("QAAPL", "NASDAQ"), ("QLSE", "LSE")):
            inst = Instrument.objects.create(
                symbol=sym, name=sym, asset_class="stock", exchange=exch,
                currency="USD", is_active=True)
            LiveQuote.objects.create(instrument=inst, last=Decimal("10"),
                                     source="yfinance",
                                     change_pct=Decimal("0"), volume=0)

    def _count(self, symbols):
        from core import exchange_status
        from market_data.one_quote import shown_many
        real = exchange_status.market_clock
        calls = []

        def counting(*a, **k):
            calls.append((a, k))
            return real(*a, **k)
        with mock.patch("core.exchange_status.market_clock", counting), \
                mock.patch("signals.market_hold.market_clock", counting), \
                mock.patch("signals.market_hold.GATE", True):
            out = shown_many(symbols, user=None, now=T)
        return out, calls

    def test_forty_pairs_read_the_forex_clock_once(self):
        out, calls = self._count(self.syms)
        self.assertEqual(len(out), 40)
        self.assertEqual({sh.state for sh in out.values()}, {"delayed"})
        self.assertLessEqual(len(calls), 3, len(calls))

    def test_two_venues_keep_their_own_clocks(self):
        """Thursday 19:13 UTC: NASDAQ trades, London is shut."""
        out, _calls = self._count(["QAAPL", "QLSE"])
        self.assertEqual(out["QAAPL"].state, "delayed")
        self.assertEqual(out["QLSE"].state, "shut")


class TheShutMarketTests(TestCase):
    """C7, C8, C9, C10, C17."""

    def setUp(self):
        self.user = get_user_model().objects.create_user("oq_shut",
                                                         password="x")
        self.rows = seed_measured(self.user)
        for p in (mock.patch("signals.market_hold.GATE", True),):
            p.start()
            self.addCleanup(p.stop)

    def _restamp(self, at):
        t = self.rows["EURUSD"]
        meta = dict(t.metadata)
        meta["venue_mark"] = stamp("1.08452", "1.08447", "1.08457", 0, at=at)
        t.metadata = meta
        t.save(update_fields=["metadata"])

    def test_the_payload_carries_the_reopening(self):
        from market_data.one_quote import shown
        from signals.market_hold import market_state
        sh = shown("EURUSD", user=self.user, now=SAT)
        self.assertEqual(sh.state, "shut")
        reopens = market_state(instrument("EURUSD"), now=SAT)["reopens"]
        self.assertEqual(sh.payload()["shut"]["reopens"], _ms(reopens))

    def test_a_reading_taken_after_the_close_is_dated_by_the_close(self):
        from core.exchange_status import market_clock
        from market_data.one_quote import shown
        # The clock shuts the FX week at the earlier of its two closes
        # (Friday 21:00 UTC); eToro trades it to 17:00 New York, 22:00 UTC
        # in November: a Saturday re-stamp of Friday's price is dated by
        # the venue's close.
        closed = market_clock("forex", "FX", symbol="EURUSD",
                              now_utc=SAT)["closed"]
        self.assertEqual(closed, datetime(2026, 11, 13, 21, 0,
                                          tzinfo=dt_tz.utc))
        self._restamp(SAT - timedelta(hours=1))      # read on Saturday
        sh = shown("EURUSD", user=self.user, now=SAT)
        self.assertEqual(sh.shut["since"], datetime(2026, 11, 13, 22, 0,
                                                    tzinfo=dt_tz.utc))
        self.assertEqual(sh.words(SAT),
                         "closed · eToro bid Fri 13 Nov 22:00 · opens Sun "
                         "22:00 UTC")
        self.assertEqual(sh.field_text("asof", now_at=SAT), "22:00:00 UTC ·")
        self.assertEqual(sh.field_text("age", now_at=SAT),
                         "closed · opens Sun 22:00 UTC")

    def test_a_previous_close_in_the_slot_says_so(self):
        from market_data.one_quote import shown
        quote("XAUUSD", "2671.30", "yfinance", 30, at=T)
        previous_close_event("XAUUSD", T - timedelta(seconds=30))
        daily_bar("XAUUSD", datetime(2026, 11, 11, tzinfo=dt_tz.utc),
                  "2671.30")
        sh = shown("XAUUSD", user=self.user, now=T)
        self.assertEqual(sh.text("bid"), "2648.30")
        self.assertTrue(sh.slot.get("prev"))
        self.assertIsNone(sh.slot.get("gap"))
        self.assertEqual(sh.slot.get("at"),
                         _ms(datetime(2026, 11, 11, tzinfo=dt_tz.utc)))
        self.assertEqual(sh.slot_text(T),
                         "Yahoo GC=F, the front-month future previous close "
                         "2671.30 · Wed 11 Nov")

    def test_the_headband_card_says_closed(self):
        self.client.force_login(self.user)
        with mock.patch("django.utils.timezone.now", return_value=SAT), \
                mock.patch("market_data.one_quote.now", return_value=SAT):
            r = self.client.get("/positions/", HTTP_HOST=HOST)
        cells, _ = _parse(r.content.decode("utf-8"))
        ages = {c["text"] for c in cells
                if c["sym"] == "EURUSD" and c["f"] == "age"}
        self.assertEqual(ages, {"closed · opens Sun 22:00 UTC"})
        prices = [c for c in cells if c["sym"] == "EURUSD"
                  and c["f"] == "price" and not c["side"]]
        self.assertTrue(prices)
        for c in prices:
            self.assertIn("data-q-title", c["attrs"], c["attrs"])
            self.assertTrue(c["attrs"].get("title", "").startswith(
                "closed · eToro bid"), c["attrs"])


class _Layer:
    def __init__(self):
        self.sent = []

    async def group_send(self, group, message):
        self.sent.append((group, message))


class TheRelayTests(TestCase):
    """C14 and C3: the relay reaches the rows nobody holds, and repairs a
    lost push once a minute."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user("oq_relay2",
                                                         password="x")
        self.rows = seed_measured(self.user)
        self.layer = _Layer()
        self.now = [T]
        for p in (mock.patch("market_data.one_quote.now",
                             side_effect=lambda: self.now[0]),
                  mock.patch("channels.layers.get_channel_layer",
                             return_value=self.layer)):
            p.start()
            self.addCleanup(p.stop)

    def run_relay(self):
        from market_data.tasks import relay_held_quotes
        fn = relay_held_quotes
        while hasattr(fn, "__wrapped__"):
            fn = fn.__wrapped__
        return fn()

    def sent(self):
        out = {}
        for _g, m in self.layer.sent:
            out[m["data"]["symbol"]] = m["data"]
        self.layer.sent.clear()
        return out

    def test_a_row_a_poller_wrote_is_pushed_to_every_tab(self):
        self.run_relay()
        self.assertEqual(sorted(self.sent()), ["AAPL", "EURUSD", "XAUUSD"])
        self.now[0] = T + timedelta(seconds=10)
        quote("GBPUSD", "1.29500", "yfinance", 0,
              at=T + timedelta(seconds=5), chg="-0.15")
        self.run_relay()
        got = self.sent()
        self.assertEqual(sorted(got), ["GBPUSD"])
        self.assertEqual(got["GBPUSD"]["q"]["p"], "1.29500")
        self.assertEqual(got["GBPUSD"]["q"]["auth"], "reference")
        self.now[0] = T + timedelta(seconds=20)
        self.run_relay()
        self.assertEqual(self.sent(), {}, "pushed once")

    def test_a_streams_row_is_left_to_its_own_ticks(self):
        self.run_relay()
        self.sent()
        self.now[0] = T + timedelta(seconds=10)
        quote("USDJPY", "151.260", "oanda_stream", 0,
              at=T + timedelta(seconds=5), bid="151.255", ask="151.265")
        self.run_relay()
        self.assertEqual(self.sent(), {})

    def test_every_sixth_run_sends_every_held_symbol_again(self):
        counts = []
        for i in range(6):
            self.now[0] = T + timedelta(seconds=10 * i)
            self.run_relay()
            counts.append(len(self.sent()))
        self.assertEqual(counts, [3, 0, 0, 0, 0, 3])


class TheSparksSayWhoseBarsTests(_Screens):
    """C11."""

    def setUp(self):
        super().setUp()
        for days, close in ((2, "1.08300"), (1, "1.08480")):
            daily_bar("EURUSD", T - timedelta(days=days), close)
        cache.clear()

    def test_every_spark_names_its_bars(self):
        html = self.page("/positions/")
        tags = re.findall(r"<(?:span|div)\b[^>]*\bdata-q-spark=\"EURUSD\"[^>]*>",
                          html)
        self.assertGreaterEqual(len(tags), 2, tags)
        for t in tags:
            self.assertIn('data-q-bars="Yahoo EURUSD=X daily closes"', t)

    def test_the_position_card_spark_names_its_bars(self):
        html = self.page("/positions/")
        rows = re.findall(r"<tr\b[^>]*data-pos-q=\"EURUSD\"[^>]*>", html, re.S)
        self.assertTrue(rows)
        for t in rows:
            self.assertIn('data-pos-spark-fam="yahoo"', t)
            self.assertIn('data-pos-spark-bars="Yahoo EURUSD=X daily closes"', t)


class TheDayChangeLeftoversTests(_Screens):
    """C12: no bare "%" and no falling arrow beside a price that has no
    day change of its own source (eToro's)."""

    def test_no_bare_percent_and_no_falling_arrow(self):
        html = self.page("/positions/")
        self.assertIsNone(re.search(r">\s*%\s*<", html),
                          "a bare % beside a price with no change")
        seen = 0
        for m in re.finditer(r'<span class="dh-pop-price"[^>]*>', html):
            if 'data-q="EURUSD"' not in m.group(0):
                continue
            before = html[max(0, m.start() - 700):m.start()]
            badge = re.findall(r'dh-pop-badge[^>]*>\s*(\S)', before)
            self.assertTrue(badge, before[-300:])
            self.assertNotIn(badge[-1], ("▼", "▲"), before[-300:])
            after = html[m.end():m.end() + 600]
            pct = re.search(r'<span class="dh-pop-pct[^>]*>([^<]*)<', after)
            self.assertTrue(pct, after)
            self.assertEqual(pct.group(1).strip(), "—")
            seen += 1
        self.assertGreaterEqual(seen, 2, "the headband card and the rail card")

    def test_the_hover_preview_paints_the_day_change(self):
        from pathlib import Path

        from django.conf import settings
        base = (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")
        self.assertNotIn("${data.change_pct || 0}%", base)
        self.assertRegex(base, r'preview-row"><span class="lbl">CHANGE</span>'
                               r'<span class="val" data-q="\$\{data\.symbol\}" '
                               r'data-q-f="chg"')


class TheHoversFollowThePriceTests(_Screens):
    """C13: a cell's hover is painted with the price."""

    def test_the_current_cell_title_is_the_engines(self):
        from market_data.one_quote import field_words
        html = self.page("/positions/")
        cells, _ = _parse(html)
        cur = [c for c in cells if c["sym"] == "EURUSD" and c["f"] == "price"
               and c["side"] == "bid" and "pos-price" in
               c["attrs"].get("class", "")]
        self.assertTrue(cur)
        p = self.shown()["EURUSD"].payload()
        for c in cur:
            self.assertIn("data-q-title", c["attrs"])
            self.assertEqual(c["attrs"]["title"], field_words(
                p, "title", _ms(T), side="bid", attrs=c["attrs"]))

    def test_the_horde_mark_carries_its_tail(self):
        board = self.json("/api/horde/")
        seats = [s for g in board["groups"] for s in g["seats"]]
        mark = {s["symbol"]: s["mark"] for s in seats}["EURUSD"]
        self.assertIn("tail", mark)
        from market_data.one_quote import field_words
        p = self.shown()["EURUSD"].payload()
        self.assertEqual(mark["title"], field_words(
            p, "title", _ms(T), side="bid",
            attrs={"data-q-title": mark["tail"]}))


class TheFiguresBesideThePriceTests(_Screens):
    """C6: since entry, the card's distances and reward to risk now are
    worked out from the price shown, and painted with it."""

    def test_since_entry_is_a_painted_cell(self):
        from market_data.one_quote import field_words
        html = self.page("/positions/")
        cells, _ = _parse(html)
        since = [c for c in cells if c["sym"] == "EURUSD" and c["f"] == "since"]
        self.assertTrue(since)
        p = self.shown()["EURUSD"].payload()
        for c in since:
            self.assertEqual(c["attrs"].get("data-q-ref"), "1.08210")
            self.assertEqual(c["side"], "bid")
            self.assertEqual(c["text"], "+0.22% since entry")
            self.assertEqual(c["text"], field_words(
                p, "since", _ms(T), side="bid", attrs=c["attrs"]))

    def test_the_card_distances_are_at_the_price_shown(self):
        t = self.rows["EURUSD"]
        meta = dict(t.metadata)
        meta["venue_mark"] = stamp("1.08452", "1.08447", "1.08457", 180)
        t.metadata = meta
        t.save(update_fields=["metadata"])
        quote("EURUSD", "1.08505", "etoro", 5, bid="1.08500", ask="1.08510")
        html = self.page("/positions/")
        row = re.search(r"<tr\b[^>]*data-pos-q=\"EURUSD\"[^>]*>", html, re.S)
        self.assertTrue(row)
        tag = row.group(0)
        want = "{:.2f}".format(abs(1.08900 - 1.08500) / 1.08500 * 100)
        self.assertIn(f'data-pos-target-pct="{want}"', tag)
        self.assertIn('data-pos-mark="1.08500"', tag)

    def test_reward_to_risk_now_is_a_painted_cell(self):
        from instruments.models import Instrument
        from market_data.one_quote import field_words
        from signals.models import Signal
        Signal.objects.create(
            instrument=Instrument.objects.get(symbol="EURUSD"),
            signal_type="technical", direction="bullish", urgency="medium",
            title="EURUSD fixture signal", description="fixture",
            rule_name="ema_cross", score=0.72, sub_scores={},
            price_at_signal=Decimal("1.08400"),
            suggested_entry=Decimal("1.08400"),
            suggested_stop=Decimal("1.07900"),
            suggested_target=Decimal("1.08900"), risk_reward_ratio=1.0,
            is_active=True)
        html = self.page("/partials/signal-rail/")
        cells, _ = _parse(html)
        rr = [c for c in cells if c["sym"] == "EURUSD" and c["f"] == "rr"]
        self.assertEqual(len(rr), 1, cells)
        a = rr[0]["attrs"]
        self.assertEqual((a.get("data-q-o"), a.get("data-q-stop"),
                          a.get("data-q-target")),
                         ("BUY", "1.07900", "1.08900"))
        p = self.shown()["EURUSD"].payload()
        self.assertEqual(rr[0]["text"], field_words(p, "rr", _ms(T),
                                                    attrs=a))
        self.assertEqual(rr[0]["text"], "0.83")


class TheDossierPeersTests(_Screens):
    """C18: the dossier's peers are painted cells, with their block."""

    def test_the_peers_are_painted_cells(self):
        board = self.json("/api/horde/")
        seats = {s["symbol"]: s for g in board["groups"] for s in g["seats"]}
        d = self.json("/api/horde/?seat=" + seats["XAUUSD"]["key"])
        peers = {p["symbol"]: p for p in d["instruments"]["peers"]}
        self.assertIn("EURUSD", peers)
        self.assertEqual(peers["EURUSD"]["q"], {"s": "EURUSD", "side": "bid"})
        self.assertEqual(peers["EURUSD"]["last_t"], "1.08447")
        self.assertEqual(d["quotes"]["q"]["EURUSD"],
                         self.shown()["EURUSD"].payload())


class TheNewsPageAsksOnceTests(TestCase):
    """MC10: the news page's price cells asked the rule once per symbol."""

    def setUp(self):
        from scraping.models import NewsArticle
        self.user = get_user_model().objects.create_user("oq_news",
                                                         password="x")
        self.client.force_login(self.user)
        self.article = NewsArticle.objects.create(
            title="A fixture headline", source="Fixture",
            url="https://www.example.com/oq/1",
            published_at=T - timedelta(hours=2))
        from market_data.models import LiveQuote
        for sym in ("QNWA", "QNWB", "QNWC"):
            # Not starred, not in the band: nothing asks for them before
            # the page's own rows do.
            inst = instrument(sym, watch=False)
            LiveQuote.objects.create(instrument=inst, last=Decimal("10.00"),
                                     source="yfinance",
                                     change_pct=Decimal("0"), volume=0)
            self.article.ai_affected_instruments.add(inst)

    def test_one_read_for_every_row(self):
        from market_data import one_quote
        real = one_quote.shown_many
        asked = []

        def counting(symbols, **kw):
            asked.append(sorted(str(s).upper() for s in symbols))
            return real(symbols, **kw)
        with mock.patch("market_data.one_quote.shown_many", counting), \
                mock.patch("market_data.one_quote.now", return_value=T):
            r = self.client.get(f"/news/{self.article.pk}/", HTTP_HOST=HOST)
        self.assertEqual(r.status_code, 200)
        mine = [a for a in asked if set(a) & {"QNWA", "QNWB", "QNWC"}]
        self.assertEqual(len(mine), 1, asked)
        self.assertEqual(set(mine[0]) & {"QNWA", "QNWB", "QNWC"},
                         {"QNWA", "QNWB", "QNWC"})
