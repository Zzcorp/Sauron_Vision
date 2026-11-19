"""The chart's levels and positioning words are measured from the one price
(2026-11-19).

The operator, 2026-11-19: "il y a un probleme d'affichage des prix sur
certaines charts ... sur d'autres pareil.... fix it". The chart's living
levels and its positioning caption (dashboard.views._chart_levels,
_chart_positioning) took their mark from the instrument's LiveQuote row.
For gold routed to eToro that row is Yahoo's GC=F, the front-month future
(eToro's quote read skips stand-ins), while the price line, the hero and
the position lines beside them are eToro's price: the reproduction drew
the 4150 round number as a level "below" the mark, 0.1 ATR away, with
eToro's price 25 points under it, and a caption measuring the recent low
from the future.

Now, for the chart's copy only: when the route is a venue and the
LiveQuote is a stand-in, the mark is the reply's one price (`now`,
market_data.one_quote), and the chart's two caches keep that copy under a
key of its own, so a routed reader and an unrouted one never share one.
The bars the levels are read from are unchanged, and living_levels and
positioning_map, which the care, the ticket and the Orcs call with their
own marks, are untouched.

Invented prices only: Yahoo's GC=F at 4152.24, eToro's ask at 4124.54,
eToro's 4h gold bars between 4126 and 4166.

Run with:  python manage.py test tests.test_chart_levels_mark
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase

from tests.one_quote_fixture import T, held, instrument, quote, stamp

ETORO_ASK = 4124.54
YAHOO_LAST = 4152.24


def _route(name):
    """The router's answer for every symbol (no account, no request)."""
    return mock.patch(
        "bot_program.engine.broker_router.broker_name_for_symbol",
        return_value=name)


def _gold_4h_bars(inst):
    """60 invented eToro 4h bars of gold up to T, a slow swing between
    4126 and 4166; the last five keep over 4130, so the recent low sits
    between eToro's price and Yahoo's."""
    from market_data.models import PriceData
    end = T.replace(hour=T.hour - T.hour % 4, minute=0, second=0,
                    microsecond=0)
    wave = [0, 4, 8, 11, 13, 14, 13, 11, 8, 4, 0, -4, -7, -9, -10, -9, -7,
            -4, 0, 4]
    rows = []
    for i in range(60):
        mid = 4144 + wave[i % len(wave)]
        if i >= 55:
            mid = 4144 + (i - 55)
        o, c = (mid - 2, mid + 2) if i % 2 else (mid + 2, mid - 2)
        hi, lo = max(o, c) + 6, min(o, c) - 6
        rows.append(PriceData(
            instrument=inst, timeframe="4h", source="etoro",
            timestamp=end - timedelta(hours=4 * (59 - i)),
            open=Decimal(o), high=Decimal(hi), low=Decimal(lo),
            close=Decimal(c), volume=100))
    PriceData.objects.bulk_create(rows)


class _Gold(TestCase):
    """Gold: a REAL eToro short marked at eToro's ask 4124.54 (40 s old),
    the LiveQuote Yahoo's GC=F at 4152.24, the clock held at T."""

    def setUp(self):
        cache.clear()
        self.user = get_user_model().objects.create_user(
            "lvl_mark", password="x", is_staff=True)
        self.inst = instrument("XAUUSD")
        quote("XAUUSD", str(YAHOO_LAST), "yfinance", 90)
        held(self.user, "XAUUSD", side="SELL", qty="1", entry="4186.97",
             vm=stamp("4124.30", "4124.04", str(ETORO_ASK), 40))
        _gold_4h_bars(self.inst)
        for p in (mock.patch("django.utils.timezone.now", return_value=T),
                  mock.patch("market_data.one_quote.now", return_value=T),
                  mock.patch("market_data.public_feed.public_feed_for",
                             return_value=None)):
            p.start()
            self.addCleanup(p.stop)
        self.client.force_login(self.user)

    def chart(self, route):
        with _route(route):
            resp = self.client.get("/api/chart-data/", {
                "symbol": "XAUUSD", "timeframe": "4h", "overlays": "1"})
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    @staticmethod
    def atr():
        from bot_program.smart_money import living_levels
        return living_levels("XAUUSD")["atr"]

    @staticmethod
    def level(body, price, kind="round number"):
        got = [lv for lv in body["levels"]
               if lv["kind"] == kind and abs(lv["price"] - price) < 1e-9]
        assert len(got) == 1, (price, kind, body["levels"])
        return got[0]


class TheMarkIsTheOnePriceTests(_Gold):

    def test_the_reply_s_one_price_is_etoros_ask(self):
        body = self.chart("etoro")
        self.assertEqual(body["now"]["v"], ETORO_ASK)
        self.assertEqual(body["now"]["fam"], "etoro")

    def test_the_round_number_is_measured_from_etoros_price(self):
        body = self.chart("etoro")
        r = self.level(body, 4150.0)
        self.assertEqual(r["side"], "above")
        self.assertEqual(r["atr_away"],
                         round((4150.0 - ETORO_ASK) / self.atr(), 2))
        for lv in body["levels"]:
            self.assertEqual(lv["side"],
                             "below" if lv["price"] < ETORO_ASK else "above",
                             lv)

    def test_the_positioning_caption_is_measured_from_etoros_price(self):
        body = self.chart("etoro")
        pos = body["positioning"]
        self.assertTrue(pos["ok"], pos)
        above, below = pos["stops"]["above"], pos["stops"]["below"]
        self.assertGreater(above["price"], ETORO_ASK)
        self.assertEqual(above["atr_away"],
                         round((above["price"] - ETORO_ASK) / self.atr(), 2))
        # the recent low (over 4130) is above eToro's price: no stop under
        # it on that side any more
        self.assertTrue(below is None or below["price"] < ETORO_ASK, below)

    def test_a_routed_reader_after_an_unrouted_one_gets_its_own_copy(self):
        first = self.chart("paper")
        self.assertEqual(self.level(first, 4150.0)["side"], "below")
        second = self.chart("etoro")
        self.assertEqual(self.level(second, 4150.0)["side"], "above")


class WhatDoesNotMoveTests(_Gold):

    def test_not_routed_the_mark_is_the_live_quote(self):
        body = self.chart("paper")
        r = self.level(body, 4150.0)
        self.assertEqual(r["side"], "below")
        self.assertEqual(r["atr_away"],
                         round((YAHOO_LAST - 4150.0) / self.atr(), 2))

    def test_an_unrouted_reader_after_a_routed_one_gets_its_own_copy(self):
        self.chart("etoro")
        body = self.chart("paper")
        self.assertEqual(self.level(body, 4150.0)["side"], "below")
        below = body["positioning"]["stops"]["below"]
        self.assertEqual(below["atr_away"],
                         round((YAHOO_LAST - below["price"]) / self.atr(), 2))

    def test_the_levels_read_takes_its_own_marks_elsewhere(self):
        """living_levels and positioning_map are pure reads with no cache:
        a caller's mark is its own (the care, the ticket, the Orcs)."""
        from bot_program.positioning import positioning_map
        from bot_program.smart_money import living_levels
        self.chart("etoro")
        read = living_levels("XAUUSD", YAHOO_LAST)
        self.assertEqual(read["price"], YAHOO_LAST)
        pm = positioning_map("XAUUSD", asset_class="commodity",
                             mark=YAHOO_LAST)
        self.assertEqual(pm["mark"], YAHOO_LAST)
