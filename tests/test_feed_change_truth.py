"""A streamer that does not know the day's change must not write one.

`change_pct` is the field every reader on this platform renders as the
change on the DAY: the headband cells, the watchlist rail, the ticker
bar. Two of the three streamers were filling it with something else.

  * `stream_oanda` computed the move since the LAST TICK and stored it,
    then broadcast a hardcoded 0 over the socket. A tick-over-tick delta
    on a forex mid is a pip or two, so the day column flattened to
    +0.00% for every pair the moment the stream came up — and the socket
    half painted an actual zero on top of it.

  * `stream_finnhub` did the same delta, wrote LiveQuote DIRECTLY
    (skipping the source-precedence guard and the zero-price refusal),
    and stamped source "finnhub" — not a key in SOURCE_PRIORITY, so a
    real-time exchange print landed on the default tier of 50 instead of
    the 90 reserved for `finnhub_ws`, below ibkr and alpaca.

`stream_binance` is the shape to copy: its @ticker payload carries a
true 24h "P", so it has something honest to say and says it.

Run with:  python manage.py test tests.test_feed_change_truth
"""
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase, TestCase


def _cmd(name):
    return (Path(settings.BASE_DIR) / "market_data" / "management"
            / "commands" / (name + ".py")).read_text(encoding="utf-8")


class NoStreamerInventsADayChangeTests(SimpleTestCase):
    def test_oanda_does_not_store_a_tick_delta(self):
        src = _cmd("stream_oanda")
        self.assertNotIn("(mid - prev_last) / prev_last", src)
        self.assertNotIn("change_pct=round(change_pct, 4)", src)

    def test_oanda_does_not_broadcast_a_zero(self):
        src = _cmd("stream_oanda")
        self.assertNotIn("broadcast(sym, mid, 0,", src)
        self.assertIn("broadcast(sym, mid, None,", src)

    def test_finnhub_does_not_store_a_tick_delta(self):
        src = _cmd("stream_finnhub")
        self.assertNotIn("(last - prev_last) / prev_last", src)

    def test_finnhub_does_not_broadcast_a_zero(self):
        src = _cmd("stream_finnhub")
        self.assertIn("broadcast(sym, last, None, vol)", src)

    def test_binance_still_sends_its_real_twentyfour_hour_change(self):
        """The one streamer that HAS a day change must keep writing it."""
        src = _cmd("stream_binance")
        self.assertIn('d.get("P")', src)
        self.assertIn("change_pct=change_pct", src)


class EveryStreamerGoesThroughTheOneWriterTests(SimpleTestCase):
    def test_no_streamer_writes_livequote_directly(self):
        """Writing the model directly skips the source-precedence guard
        and the zero/negative price refusal — the two things that make
        this table worth reading."""
        for name in ("stream_oanda", "stream_finnhub", "stream_binance",
                     "stream_binance_futures"):
            src = _cmd(name)
            self.assertNotIn("LiveQuote.objects.update_or_create", src, name)

    def test_finnhub_claims_the_tier_the_table_reserves_for_it(self):
        from market_data.quotes import SOURCE_PRIORITY
        src = _cmd("stream_finnhub")
        self.assertIn('source="finnhub_ws"', src)
        self.assertNotIn('source="finnhub"', src)
        self.assertIn("finnhub_ws", SOURCE_PRIORITY)

    def test_every_streamer_source_is_a_known_tier(self):
        """A source the table does not know falls to DEFAULT_PRIORITY,
        which for a real-time stream is a demotion nobody intended."""
        import re

        from market_data.quotes import SOURCE_PRIORITY
        for name in ("stream_oanda", "stream_finnhub", "stream_binance"):
            for src_name in re.findall(r'source="([a-z_]+)"', _cmd(name)):
                self.assertIn(src_name, SOURCE_PRIORITY,
                              f"{name} writes an unranked source")


class TheColumnKeepsWhatThePollerMeasuredTests(TestCase):
    """write_quote already does the right thing with None — this pins it,
    because the whole fix rests on it."""

    def setUp(self):
        from instruments.models import Instrument
        self.inst = Instrument.objects.create(
            symbol="EURUSD", name="Euro", asset_class="forex", is_active=True)

    def test_a_stream_tick_updates_price_and_leaves_the_day_change(self):
        from market_data.models import LiveQuote
        from market_data.quotes import write_quote

        write_quote("EURUSD", last=Decimal("1.0800"), source="oanda",
                    change_pct=Decimal("0.42"))
        write_quote("EURUSD", last=Decimal("1.0850"), source="oanda_stream",
                    bid=Decimal("1.0849"), ask=Decimal("1.0851"))

        row = LiveQuote.objects.get(instrument=self.inst)
        self.assertEqual(Decimal(str(row.last)), Decimal("1.0850"))
        self.assertEqual(Decimal(str(row.change_pct)), Decimal("0.42"),
                         "the stream flattened a day change it never measured")

    def test_a_source_that_measured_one_still_writes_it(self):
        from market_data.models import LiveQuote
        from market_data.quotes import write_quote

        write_quote("EURUSD", last=Decimal("1.0800"), source="oanda",
                    change_pct=Decimal("0.42"))
        write_quote("EURUSD", last=Decimal("1.0900"), source="oanda",
                    change_pct=Decimal("1.35"))
        row = LiveQuote.objects.get(instrument=self.inst)
        self.assertEqual(Decimal(str(row.change_pct)), Decimal("1.35"))


class ThePainterLeavesAnUnmeasuredColumnAloneTests(SimpleTestCase):
    """applyTick did `+d.change_pct || 0`, which turns a deliberate null
    into a real-looking 0.00% across all three price surfaces."""

    def _shell(self):
        return (Path(settings.BASE_DIR) / "templates" / "base.html").read_text(
            encoding="utf-8")

    def test_the_painter_distinguishes_absent_from_zero(self):
        seg = self._shell().split("function applyTick")[1][:900]
        self.assertIn("hasPct", seg)
        self.assertNotIn("const pct = +d.change_pct || 0;", seg)

    def test_all_three_price_surfaces_respect_it(self):
        """Headband cell, watchlist rail, ticker bar — a real zero is a
        legitimate value, so the guard has to be on presence."""
        seg = self._shell().split("function applyTick")[1][:2600]
        for guard in ("if (chg && hasPct)", "if (chgEl && hasPct)",
                      "if (c && hasPct)"):
            self.assertIn(guard, seg)

    def test_the_price_itself_is_never_gated_on_the_change(self):
        """The tick's whole point is the price. It must paint regardless
        of whether the source knew a day change."""
        seg = self._shell().split("function applyTick")[1][:2600]
        self.assertIn("val.textContent = last.toFixed(2); flash(val);", seg)
        self.assertIn("lastEl.textContent = last.toFixed(4); flash(lastEl);", seg)
