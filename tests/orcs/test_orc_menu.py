"""THE MENU (bot_program/orcs/menu.py, spec §5.2): the levels an Orc may
name, from the venue's own bars, with deterministic ids and stops beyond
the crowd; the basis fallback when the venue holds no frame.

Run with:  python manage.py test tests.orcs.test_orc_menu
"""
import re
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from unittest.mock import patch

from django.test import TestCase

from tests.orcs.helpers import _bars, _wave

T0 = datetime(2026, 8, 1, 0, 0, tzinfo=dt_tz.utc)
N4, N1 = 90, 120
NOW = T0 + timedelta(hours=4 * N4)


def _venue(symbol="BTCUSD", *, source="etoro", base=100.0, cls="crypto"):
    _bars(symbol, "4h", _wave(N4, base=base, amp=3.0, period=14), start=T0,
          source=source, asset_class=cls)
    _bars(symbol, "1h", _wave(N1, base=base, amp=1.5, period=10),
          start=NOW - timedelta(hours=N1), source=source, asset_class=cls)


class TheMenuTests(TestCase):

    def test_levels_from_living_levels_on_venue_bars(self):
        from bot_program import smart_money as sm
        from bot_program.orcs.bars import frame
        from bot_program.orcs.menu import symbol_levels
        _venue()
        menu = symbol_levels("BTCUSD", "crypto", now=NOW)
        self.assertEqual(menu.source, "etoro")
        self.assertEqual(sorted(menu.tfs), ["1d", "1h", "4h"],
                         "the 1d is the venue's 4h by UTC day")
        self.assertTrue(menu.levels)
        self.assertTrue(all(lv.source in ("etoro", "") for lv in menu.levels))
        f = frame("BTCUSD", "4h", asset_class="crypto", now=NOW)
        living = sm.living_levels("BTCUSD", f.last_close, timeframe="4h",
                                  bars=(f.df, f.swings))
        prices = {round(r["price"], 2) for r in living["levels"]
                  if r["kind"] == "swing low"}
        mine = {lv.price for lv in menu.levels
                if lv.tf == "4h" and lv.kind == "swing" and lv.side == "below"}
        self.assertTrue(mine)
        self.assertEqual(mine, prices)
        self.assertGreater(menu.atr["4h"], 0)

    def test_ids_deterministic(self):
        from bot_program.orcs.menu import symbol_levels
        _venue()
        a = symbol_levels("BTCUSD", "crypto", now=NOW)
        b = symbol_levels("BTCUSD", "crypto", now=NOW)
        self.assertEqual([(lv.id, lv.price, lv.stop) for lv in a.levels],
                         [(lv.id, lv.price, lv.stop) for lv in b.levels])
        pattern = re.compile(r"^(S|P|SW)(1h|4h|1d)-[LH]\d+$|^RC(1h|4h|1d)-[LH]$"
                             r"|^RN-\d+$")
        for lv in a.levels:
            self.assertRegex(lv.id, pattern)
        self.assertEqual(len({lv.id for lv in a.levels}), len(a.levels))
        lows = sorted((lv for lv in a.levels
                       if lv.id.startswith("S4h-L")),
                      key=lambda lv: int(lv.id.split("L")[-1]))
        close = 100.0
        from bot_program.orcs.bars import frame
        close = frame("BTCUSD", "4h", asset_class="crypto",
                      now=NOW).last_close
        dists = [abs(lv.price - close) for lv in lows]
        self.assertEqual(dists, sorted(dists), "1 is the nearest")

    def test_stops_beyond_the_crowd_snapped(self):
        from bot_program import smart_money as sm
        from bot_program.orcs.menu import symbol_levels
        _venue()
        menu = symbol_levels("BTCUSD", "crypto", now=NOW)
        atr = {"1h": menu.atr["1h"], "4h": menu.atr["4h"]}
        for lv in menu.levels:
            if lv.kind == "round" or lv.stop is None:
                continue
            a = atr[lv.tf]
            if lv.side == "below":
                self.assertLessEqual(lv.stop,
                                     lv.price - sm.HUNT_DEPTH_ATR * a + 0.01)
            else:
                self.assertGreaterEqual(lv.stop,
                                        lv.price + sm.HUNT_DEPTH_ATR * a - 0.01)
            self.assertEqual(lv.stop, round(lv.stop, 2), "printed precision")

    def test_1d_is_the_venues_4h_by_day_and_only_when_fresh(self):
        """No 1d candle is stored for the venue: the menu's 1d is the
        venue's 4h bars grouped by UTC day; 1d rows stored under the
        venue's name (none are written now) are never read; and a stale
        venue drops the 1d with the rest."""
        from bot_program.orcs.menu import symbol_levels
        _venue()
        # sixty more days of the venue's 4h bars before the frame's own
        _bars("BTCUSD", "4h", _wave(360, amp=3.0, period=14),
              start=T0 - timedelta(days=60))
        _bars("BTCUSD", "1d", [500.0] * 70, start=NOW - timedelta(days=70),
              source="etoro")
        fresh = symbol_levels("BTCUSD", "crypto", now=NOW)
        self.assertIn("1d", fresh.tfs)
        self.assertTrue(fresh.fresh["1d"])
        self.assertEqual(fresh.n["1d"], 75, "the 4h bars' seventy-five days")
        daily = [lv for lv in fresh.levels if lv.tf == "1d"]
        self.assertTrue(daily)
        self.assertTrue(all(lv.price < 200 for lv in daily),
                        "never the stored 1d rows")
        stale = symbol_levels("BTCUSD", "crypto",
                              now=NOW + timedelta(days=5))
        self.assertNotIn("1d", stale.tfs)
        self.assertFalse(stale.fresh["1d"])
        self.assertTrue(any(w.startswith("no fresh 1d bars")
                            for w in stale.why))

    def test_basis_shift_and_suppression_when_unstable_or_unmeasured(self):
        from bot_program.orcs.bars import frame
        from bot_program.orcs.menu import BASIS_SHIFTED, symbol_levels
        _venue("XAUUSD", source="yfinance_public", base=2600.0, cls="crypto")
        close = frame("XAUUSD", "1h", asset_class="crypto",
                      now=NOW).last_close
        mark = close + 5.0
        bare = symbol_levels("XAUUSD", "crypto", now=NOW, mark=mark)
        self.assertEqual(bare.source, BASIS_SHIFTED)
        self.assertFalse([lv for lv in bare.levels if lv.kind != "round"],
                         "unmeasured basis: no structure level")
        self.assertTrue(any("unmeasured (0 of 10" in w for w in bare.why))
        noisy = symbol_levels("XAUUSD", "crypto", now=NOW, mark=mark,
                              basis_samples=[5, -20, 30, -5, 40, 0, 25,
                                             -30, 10, 50])
        self.assertTrue(any("unstable" in w for w in noisy.why))
        self.assertFalse([lv for lv in noisy.levels if lv.kind != "round"])
        steady = symbol_levels("XAUUSD", "crypto", now=NOW, mark=mark,
                               basis_samples=[5.0] * 10)
        shifted = [lv for lv in steady.levels if lv.kind == "swing"]
        self.assertTrue(shifted)
        plain = symbol_levels("XAUUSD", "crypto", now=NOW,
                              basis_samples=[5.0] * 10)
        base = {lv.id: lv.price for lv in plain.levels if lv.kind == "swing"}
        for lv in shifted:
            if lv.id in base:
                self.assertAlmostEqual(lv.price, base[lv.id] + 5.0, places=1)

    def test_be_and_care_per_idea_in_R(self):
        from bot_program.orcs.menu import Level, Menu, for_idea
        menu = Menu(symbol="BTCUSD", as_of=NOW, source="etoro",
                    atr={"4h": 2.0, "1h": 1.0},
                    levels=[Level(id="S4h-L1", kind="swing", tf="4h",
                                  side="below", price=97.0, stop=96.0)])
        rows = for_idea(menu, side="BUY", entry=100.0, risk_per_unit=2.0,
                        mark=101.0, care_state={"soft_stop": 100.2,
                                                "soft_why": "breakeven",
                                                "venue_stop": 100.5},
                        cf=0.001)
        by = {r["id"]: r for r in rows}
        self.assertAlmostEqual(by["S4h-L1"]["r_away"], -2.0)
        self.assertAlmostEqual(by["S4h-L1"]["atr_away"], -2.0)
        self.assertAlmostEqual(by["BE"]["price"], 100.1)
        self.assertAlmostEqual(by["CARE"]["price"], 100.2)
        self.assertAlmostEqual(by["CARE"]["r_away"], -0.4)
        self.assertAlmostEqual(by["EFF"]["price"], 100.5,
                               msg="the tighter of the care and the venue")
        short = for_idea(menu, side="SELL", entry=100.0, risk_per_unit=2.0,
                         mark=99.0, care_state={}, cf=0.001)
        by = {r["id"]: r for r in short}
        self.assertAlmostEqual(by["BE"]["price"], 99.9)
        self.assertNotIn("CARE", by)

    def test_living_levels_default_unchanged(self):
        from bot_program import smart_money as sm
        _venue()
        with patch.object(sm, "_bars", wraps=sm._bars) as spy:
            plain = sm.living_levels("BTCUSD", 100.0)
        spy.assert_called_once_with("BTCUSD", "4h")
        df, swings = sm._bars("BTCUSD", "4h")
        given = sm.living_levels("BTCUSD", 100.0, bars=(df, swings))
        self.assertEqual(plain, given)
