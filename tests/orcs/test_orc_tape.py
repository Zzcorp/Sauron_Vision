"""THE ORCS' BOARD AND TAPE IN THE BAR REFRESH (market_data/bot_bars.py,
spec §5.2a item 3, MK2, IN12, §1.6): while `orcs` is ON the board's
symbols join the watchlist's held part (the keyless feed, 4h and 1h);
US10Y has no instrument and drops silently. The eToro 15m and 5m candles
of the live Orcs' symbols, then the board's, run only with `orcs_tape` ON
AND a recorded headroom measurement: after every config and the Orcs'
4h/1h parts, cut by the deadline, within the measured budget, stopping at
the first 429, with no public-feed fallback and no venue mark stamped.
The Mercenaries' own 5-minute beat stands aside while a bar pass runs.

Run with:  python manage.py test tests.orcs.test_orc_tape
"""
from unittest.mock import patch

from tests.orcs.helpers import _on, _switch
from tests.orcs.test_orc_bar_refresh import _orc_for, _OrcBase
from tests.test_bars_etoro_quota import H, _Wire

MIN = 60_000


class _TapeWire(_Wire):
    ENUM = {**_Wire.ENUM, "OneDay": 24 * H, "FifteenMinutes": 15 * MIN,
            "FiveMinutes": 5 * MIN}


def _measured(per_pass=4):
    from bot_program.orcs.models import OrcSetting
    OrcSetting.objects.update_or_create(
        key="etoro_candle_headroom",
        defaults={"value": {"tape_per_pass": per_pass, "world": "live",
                            "clean_per_min": 30.0}})


class _Tape(_OrcBase):

    def setUp(self):
        super().setUp()
        self.wire = _TapeWire(self.wire.ids)

    def _tape_calls(self):
        return [u for u in self.wire.candle_calls()
                if "/FifteenMinutes/" in u or "/FiveMinutes/" in u]


class TheBoardTests(_Tape):

    def test_the_board_joins_the_watchlist_only_while_on(self):
        _on(False)
        self._cfg(["GBPUSD"], name="B paper")
        self._run()
        off = dict(self.wl.call_args.kwargs)
        self.assertNotIn("also", off, "OFF: the watchlist is asked as before")
        self._reset()
        _on()
        out = self._run()
        also = self.wl.call_args.kwargs["also"]
        self.assertEqual(list(also), ["XAUUSD", "EURUSD", "USDJPY"],
                         "the board's order, those with an instrument")
        self.assertNotIn("US10Y", also)
        self.assertEqual(out["errors"], 0, "US10Y drops silently")

    def test_off_the_real_watchlist_asks_no_board_symbol(self):
        """refresh_watchlist_bars NOT patched: OFF, the keyless feed is
        asked for the held and starred symbols only, whatever board
        instruments exist; ON, the board joins the held part."""
        from market_data import bot_bars
        from tests.test_bars_etoro_quota import _Feed
        _on(False)
        self._cfg(["GBPUSD"], name="B paper")
        feed = _Feed()

        def run():
            with patch.object(bot_bars, "_client_for",
                              side_effect=self._client), \
                    patch.object(bot_bars, "_public_market_data_client",
                                 return_value=self.feed), \
                    patch.object(bot_bars, "_mono", self.clock.mono), \
                    patch.object(bot_bars, "_candle_sleep", self.clock.sleep), \
                    patch("market_data.public_feed.public_feed_for",
                          return_value=feed), \
                    patch("brain.synthesizer._held_symbols",
                          return_value=[]):
                return bot_bars.refresh_bot_bars()
        run()
        self.assertEqual(feed.calls, [], "OFF: no board symbol is asked")
        self._reset()
        _on()
        run()
        self.assertEqual(sorted({s for s, _i in feed.calls}),
                         ["EURUSD", "USDJPY", "XAUUSD"])

    def test_the_watchlist_fetches_the_board_from_the_keyless_feed(self):
        from market_data import bot_bars
        from tests.test_bars_etoro_quota import _Feed
        feed = _Feed()
        with patch("market_data.public_feed.public_feed_for",
                   return_value=feed), \
                patch("brain.synthesizer._held_symbols", return_value=[]):
            bot_bars.refresh_watchlist_bars(also=["XAUUSD"], starred=False)
        self.assertEqual(feed.calls, [("XAUUSD", "4h"), ("XAUUSD", "1h")])
        feed.calls = []
        with patch("market_data.public_feed.public_feed_for",
                   return_value=feed), \
                patch("brain.synthesizer._held_symbols", return_value=[]):
            bot_bars.refresh_watchlist_bars(starred=False)
        self.assertEqual(feed.calls, [])


class TheTapeTests(_Tape):

    def setUp(self):
        super().setUp()
        _on()
        _switch("orcs_tape", True)
        self.cfg = self._cfg(["GBPUSD"], name="B paper")
        _orc_for(self._row("AAPL", "stock"))

    def test_off_until_measured(self):
        self._run()
        self.assertEqual(self._tape_calls(), [])
        self._reset()
        _measured()
        self._run()
        self.assertTrue(self._tape_calls())

    def test_off_without_the_switch_even_measured(self):
        _measured()
        _switch("orcs_tape", False)
        self._run()
        self.assertEqual(self._tape_calls(), [])

    def test_last_in_the_pass_within_the_budget_orcs_first(self):
        _measured(per_pass=4)
        out = self._run()
        calls = self.wire.candle_calls()
        tape = self._tape_calls()
        first = calls.index(tape[0])
        self.assertTrue(all("/FourHours/" in u or "/OneHour/" in u
                            for u in calls[:first]))
        self.assertEqual(len(tape), 4, "the measured budget")
        self.assertIn(self._iid("AAPL"), tape[0], "a live Orc's symbol first")
        self.assertIn(self._iid("XAUUSD"), tape[2], "then the board")
        self.assertEqual(out["orcs_tape"]["asked"], 4)

    def test_stops_at_the_first_429_with_no_fallback(self):
        _measured(per_pass=10)
        self.wire.refuse = {("AAPL", "FifteenMinutes")}
        self._run()
        self.assertEqual(len(self._tape_calls()), 1)
        self.assertFalse([c for c in self.feed.calls
                          if c[1] in ("15m", "5m")], "no public feed")

    def test_cut_by_the_deadline(self):
        _measured(per_pass=10)
        self._run(client_for=self._late_after(2))
        self.assertEqual(self._tape_calls(), [])

    def test_no_venue_mark_is_stamped(self):
        from market_data import bot_bars
        _measured(per_pass=10)
        with patch.object(bot_bars, "_stamp_venue_rows",
                          wraps=bot_bars._stamp_venue_rows) as stamp:
            self._run()
        self.assertFalse([c for c in stamp.call_args_list
                          if c.args[2] in ("15m", "5m")])

    def test_a_non_etoro_client_is_skipped_never_the_feed(self):
        from tests.test_bars_etoro_quota import _Feed
        _measured(per_pass=10)
        feed = _Feed()
        with patch("market_data.bot_bars._client_for", return_value=feed), \
                patch("market_data.bot_bars._public_market_data_client",
                      return_value=self.feed), \
                patch("market_data.bot_bars.refresh_watchlist_bars",
                      return_value={}):
            from market_data import bot_bars
            out = bot_bars.refresh_bot_bars()
        self.assertFalse([c for c in feed.calls if c[1] in ("15m", "5m")])
        self.assertGreaterEqual(out["orcs_tape"]["venue_only_skipped"], 1)


class TheMercenaryBeatTests(_Tape):

    def setUp(self):
        super().setUp()
        _on()
        _switch("orcs_tape", True)
        _measured(per_pass=10)
        _orc_for(self._row("EURUSD", "forex"), army="mercenaries")
        _orc_for(self._row("AAPL", "stock"))

    def _beat(self):
        from market_data import bot_bars
        from market_data.tasks import refresh_orc_tape_task
        with patch.object(bot_bars, "_client_for", side_effect=self._client), \
                patch.object(bot_bars, "_mono", self.clock.mono), \
                patch.object(bot_bars, "_candle_sleep", self.clock.sleep):
            return refresh_orc_tape_task()

    def test_the_mercenaries_symbols_only(self):
        out = self._beat()
        tape = self._tape_calls()
        self.assertEqual(len(tape), 2)
        self.assertTrue(all(self._iid("EURUSD") in u for u in tape))
        self.assertEqual(out["status"], "success")

    def test_stands_aside_while_the_bar_refresh_runs(self):
        from django.core.cache import cache

        from market_data.tasks import BARS_LOCK_KEY
        cache.set(BARS_LOCK_KEY, "x", 60)
        out = self._beat()
        self.assertIn("idle", out)
        self.assertEqual(self.wire.calls, [])
        self.assertEqual(cache.get(BARS_LOCK_KEY), "x", "never takes it")

    def test_skipped_while_unmeasured_or_orcs_off(self):
        from bot_program.orcs.models import OrcSetting
        OrcSetting.objects.filter(key="etoro_candle_headroom").delete()
        self.assertIn("idle", self._beat())
        _measured()
        _on(False)
        self.assertIn("idle", self._beat())
        self.assertEqual(self.wire.calls, [])
        _switch("orcs_tape", False)
        self.assertEqual(self._beat()["status"], "skipped")
