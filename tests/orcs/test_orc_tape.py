"""THE ORCS' BOARD AND TAPE IN THE BAR REFRESH (market_data/bot_bars.py,
spec §5.2a item 3, MK2, IN12, §1.6): while `orcs` is ON the board's
symbols are fetched by the watchlist AFTER its starred part (the keyless
feed, 4h and 1h), cut by the deadline like it, skipped in a late pass;
the held part is exactly what it is OFF. US10Y has no instrument and
drops silently. The eToro 15m and 5m candles
of the live Orcs' symbols, then the board's, run only with `orcs_tape` ON
AND a recorded headroom measurement: after every config and the Orcs'
4h/1h parts, cut by the deadline, within the measured budget, stopping at
the first 429, with no public-feed fallback and no venue mark stamped.
The Mercenaries' own 5-minute beat stands aside while a bar pass runs
and gives way to one that starts, at its next candle read.

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

    def test_the_board_never_joins_the_held_part(self):
        """Review (O1c): a late pass reaches every held symbol, the one
        part never cut (it carries the fallback bars of the config
        symbols the deadline cut), and no board symbol; a pass in time
        fetches the held part, then the stars, then the board."""
        from market_data import bot_bars
        from tests.orcs.helpers import _inst
        from tests.test_bars_etoro_quota import _Feed
        _inst("USDCHF", "forex")
        _inst("XRPUSD", "crypto")
        feed = _Feed()

        def run(**kw):
            feed.calls = []
            with patch("market_data.public_feed.public_feed_for",
                       return_value=feed), \
                    patch("brain.synthesizer._held_symbols",
                          return_value=["USDCHF", "XRPUSD"]):
                bot_bars.refresh_watchlist_bars(also=["XAUUSD", "EURUSD"],
                                                starred=False, **kw)
            return [s for s, _i in feed.calls]
        late = run(stop=lambda: True)
        self.assertEqual(sorted(set(late)), ["USDCHF", "XRPUSD"],
                         "a late pass: the held part, no board symbol")
        order = run(stop=lambda: False)
        self.assertEqual(list(dict.fromkeys(order)),
                         ["USDCHF", "XRPUSD", "XAUUSD", "EURUSD"])

    def test_a_late_pass_hands_the_watchlist_no_board(self):
        _on()
        self._cfg(["GBPUSD"], name="B paper")
        self._run(client_for=self._late_after(1))
        self.assertNotIn("also", self.wl.call_args.kwargs)


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

    def test_gives_way_to_a_bar_pass_at_every_read(self):
        """Review (O1c): a bar pass that starts while the tape runs ends
        the tape at its next candle read: two candle loops on one account
        key never ask eToro at once."""
        from django.core.cache import cache

        from market_data.tasks import BARS_LOCK_KEY

        class _BarPassStarts(_TapeWire):
            def get(self, url, **kw):
                out = super().get(url, **kw)
                if "/history/candles" in url:
                    cache.set(BARS_LOCK_KEY, "a bar pass", 60)
                return out
        self.wire = _BarPassStarts(self.wire.ids)
        out = self._beat()
        self.assertEqual(len(self._tape_calls()), 1,
                         "no second read once a bar pass holds its lock")
        self.assertIn("a bar pass started", out["etoro_stopped"])

    def test_the_bar_pass_itself_never_yields(self):
        from market_data.bot_bars import _CandlePass
        self.assertIsNone(_CandlePass().yield_to)

    def test_no_mercenary_is_a_counted_pass_not_idle(self):
        """The task is the only writer of the orcs_tape row: a pass with no
        Mercenary holding a position is a success that read nothing, so
        the row moves and the digest never says it has never run."""
        from bot_program.orcs.models import Orc
        from core.platform_control import get_component
        Orc.objects.filter(army_type="mercenaries").update(
            army_type="orcs")
        out = self._beat()
        self.assertNotIn("idle", out)
        self.assertEqual((out["status"], out["symbols"]), ("success", 0))
        self.assertEqual(self._tape_calls(), [])
        row = get_component("orcs_tape")
        self.assertIsNotNone(row.last_run_at)
        self.assertEqual(row.last_status, "success")

    def test_stands_aside_while_the_bar_refresh_runs(self):
        from django.core.cache import cache

        from market_data.tasks import BARS_LOCK_KEY
        cache.set(BARS_LOCK_KEY, "x", 60)
        out = self._beat()
        self.assertIn("idle", out)
        self.assertEqual(self.wire.calls, [])
        self.assertEqual(cache.get(BARS_LOCK_KEY), "x", "never takes it")

    def test_unmeasured_warns_and_orcs_off_skips_never_idle(self):
        """The task is the only writer of the orcs_tape row
        (core/task_gate.py): every outcome but the lock stand-aside is a
        counted pass, so the digest never lists it as never run."""
        from bot_program.orcs.models import OrcSetting
        OrcSetting.objects.filter(key="etoro_candle_headroom").delete()
        out = self._beat()
        self.assertNotIn("idle", out)
        self.assertEqual(out["status"], "warning")
        self.assertIn("headroom is not measured", out["reason"])
        _measured()
        _on(False)
        out = self._beat()
        self.assertEqual((out["status"], out["reason"]),
                         ("skipped", "orcs_disabled"))
        self.assertEqual(self.wire.calls, [])
        _switch("orcs_tape", False)
        self.assertEqual(self._beat()["status"], "skipped")
