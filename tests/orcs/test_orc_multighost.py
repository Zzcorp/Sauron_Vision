"""THE MULTI-GHOST (bot_program/orcs/ghost._policy_walk, spec §6.1):
chandelier3 and staged from simulate.EXIT_POLICIES, walked on the same 4h
bars with the proving ground's own discipline, so an arm and the proving
ground agree on the same bars; and forward only (§6.2): an arm walks the
bars that open at or after its seed, never the history before its birth.

Run with:  python manage.py test tests.orcs.test_orc_multighost
"""
from datetime import datetime, timedelta
from datetime import timezone as dt_tz

import numpy as np
import pandas as pd
from django.test import SimpleTestCase, TestCase

T0 = datetime(2026, 6, 1, 0, 0, tzinfo=dt_tz.utc)


def _df(closes, *, wick=0.6):
    idx = pd.DatetimeIndex([T0 + timedelta(hours=4 * i)
                            for i in range(len(closes))])
    closes = np.asarray(closes, dtype=float)
    opens = np.concatenate([[closes[0]], closes[:-1]])
    return pd.DataFrame({"open": opens,
                         "high": np.maximum(opens, closes) + wick,
                         "low": np.minimum(opens, closes) - wick,
                         "close": closes, "volume": 0.0}, index=idx)


def _frame(df):
    from bot_program.orcs.bars import Frame
    return Frame(symbol="BTCUSD", tf="4h", df=df, swings=[], source="etoro",
                 newest_end=df.index[-1].to_pydatetime() + timedelta(hours=4),
                 fresh=True, n=len(df))


def _state_like_simulate(df, t, policy, cls="crypto"):
    """The arm seeded exactly as simulate opens its trade at bar t + 1."""
    from backtester.proving.families import atr
    from backtester.proving.simulate import _engine_constants
    k = _engine_constants(cls)
    a = atr(df).to_numpy()
    e_i = t + 1
    entry = float(df["open"].values[e_i])
    lo, hi = k["band"]
    risk = min(max(a[t] * k["stop_mult"] / entry, lo), hi) * entry
    ratio = k["target_mult"] / k["stop_mult"]
    at = df.index[e_i].to_pydatetime()
    return {"policy": policy, "side": "BUY", "entry": entry, "rpu": risk,
            "qty": 1.0, "qty_open": 1.0, "banked": [], "cf": 0.0,
            "ceiling": None, "target": entry + ratio * risk,
            "soft": entry - risk, "soft_why": "stop", "mfe": 0.0,
            "extreme": entry, "since": at.isoformat(),
            "bar_at": at.isoformat(), "entry_bar": True,
            "opened_at": at.isoformat(),
            "asset_class": cls, "bar_sources": []}


class TheSimulateMatchTests(SimpleTestCase):

    def _paths(self):
        rng = np.random.default_rng(7)
        base = list(100 + np.cumsum(rng.normal(0, 0.4, 40)))
        up = [base[-1] + 0.9 * i for i in range(1, 14)]
        down = [up[-1] - 1.4 * i for i in range(1, 16)]
        flat = [base[-1] + rng.normal(0, 0.2) for _ in range(40)]
        grind = [base[-1] + 0.3 * i for i in range(1, 13)]
        slide = [grind[-1] - 0.8 * i for i in range(1, 16)]
        return {"trend then fall": base + up + down,
                "drift": base + flat,
                "grind then slide": base + grind + slide}

    def test_chandelier3_and_staged_match_simulate_on_the_same_bars(self):
        from backtester.proving.simulate import simulate

        from bot_program.orcs.ghost import _policy_walk
        for name, closes in self._paths().items():
            df = _df(closes)
            t = 39
            fires = np.zeros(len(df), dtype=bool)
            fires[t] = True
            for policy in ("chandelier3", "staged"):
                with self.subTest(path=name, policy=policy):
                    sim = simulate(df, fires, "long", asset_class="crypto",
                                   timeframe="4h", policy=policy)
                    state = _state_like_simulate(df, t, policy)
                    end = df.index[-1].to_pydatetime() + timedelta(hours=4)
                    out = _policy_walk(state, _frame(df), end)
                    if not sim["trades"]:
                        self.assertIsNone(out, "both still open")
                        continue
                    trade = sim["trades"][0]
                    self.assertIsNotNone(out)
                    self.assertAlmostEqual(out["level"], trade["exit"],
                                           places=9)
                    self.assertEqual(out["reason"], trade["reason"])

    def test_locks_bind_from_the_next_bar(self):
        from bot_program.orcs.ghost import _policy_bar
        from backtester.proving.simulate import _engine_constants
        k = _engine_constants("crypto")
        st = {"policy": "staged", "side": "BUY", "entry": 100.0, "rpu": 2.0,
              "cf": 0.0, "soft": 98.0, "soft_why": "stop", "target": None,
              "mfe": 0.0, "extreme": 100.0, "since": T0.isoformat(),
              "asset_class": "crypto"}
        bar = {"ts": T0, "end": T0 + timedelta(hours=4), "open": 100.0,
               "high": 107.0, "low": 103.0, "close": 106.0}
        self.assertIsNone(_policy_bar(st, bar, 1.0, k),
                          "the new high's lock does not bind its own bar")
        self.assertEqual((st["soft"], st["soft_why"]), (103.5, "half kept"))
        bar2 = {"ts": T0 + timedelta(hours=4), "end": T0 + timedelta(hours=8),
                "open": 105.0, "high": 105.5, "low": 103.0, "close": 104.0}
        out = _policy_bar(st, bar2, 1.0, k)
        self.assertEqual((out["level"], out["reason"]), (103.5, "half kept"))

    def test_tie_to_stop_gap_at_open(self):
        from bot_program.orcs.ghost import _policy_bar
        from backtester.proving.simulate import _engine_constants
        k = _engine_constants("crypto")

        def st():
            return {"policy": "chandelier3", "side": "BUY", "entry": 100.0,
                    "rpu": 2.0, "cf": 0.0, "soft": 98.0, "soft_why": "stop",
                    "target": 104.0, "mfe": 0.0, "extreme": 100.0,
                    "since": T0.isoformat(), "asset_class": "crypto"}
        tie = {"ts": T0, "end": T0 + timedelta(hours=4), "open": 100.0,
               "high": 104.5, "low": 97.5, "close": 101.0}
        out = _policy_bar(st(), tie, 1.0, k)
        self.assertEqual((out["level"], out["reason"]), (98.0, "stop"),
                         "both in one bar: the stop")
        gap = {"ts": T0, "end": T0 + timedelta(hours=4), "open": 97.0,
               "high": 97.5, "low": 96.0, "close": 96.5}
        out = _policy_bar(st(), gap, 1.0, k)
        self.assertEqual((out["level"], out["reason"]), (97.0, "gap stop"),
                         "a gap fills at the open")
        self.assertLess(out["px"], 98.0)


class TheForwardOnlyTests(TestCase):
    """AN ADOPTED IDEA WALKS ONLY ITS OWN FUTURE. Seeded with no bar,
    a policy arm walked the row's whole history from its open, with the
    stop the care had trailed since: an idea adopted with its stop at 104
    exited on a dip to 101 three days before it was born."""

    NOW = datetime(2026, 10, 14, 12, 0, tzinfo=dt_tz.utc)     # Wednesday

    def setUp(self):
        from tests.orcs.helpers import _config, _on, _switch, _user
        _on()
        _switch("aragorn")
        self.cfg = _config(_user("orc_forward"))

    def test_adopted_policy_arm_walks_only_bars_after_its_seed(self):
        from decimal import Decimal

        from bot_program.models import AssetBotTrade
        from tests.orcs.helpers import _bars, _row, born, drive, tracks_of
        opened = self.NOW - timedelta(hours=72)
        row = _row(self.cfg, stop="98", meta={"care": {
            "peak": 106.0, "worst": 99.5, "soft_stop": 104.0,
            "soft_why": "trail", "mfe_r": 3.0,
            "since": opened.isoformat()}})
        AssetBotTrade.objects.filter(pk=row.pk).update(
            opened_at=opened, stop_loss=Decimal("104"))
        row.refresh_from_db()
        # the history: a dip to 100.9 on day one, then up to 105.5
        history = [(100, 100.5, 99.8, 100.2), (100.2, 101, 100.9, 101),
                   (101, 101.5, 100.9, 101.2)] + [
            (101 + i * 0.3, 101.5 + i * 0.3, 100.95 + i * 0.3,
             101.3 + i * 0.3) for i in range(15)]
        _bars("BTCUSD", "4h", history, start=opened)
        orc = born(self, row, adopted=True, at=self.NOW)
        for arm in ("chandelier3", "staged"):
            self.assertEqual(tracks_of(orc)[arm].state["bar_at"],
                             self.NOW.isoformat(), "seeded at its birth")
        _bars("BTCUSD", "4h", [(105.5, 105.8, 105.3, 105.6)] * 2,
              start=self.NOW)
        # the refresh's pass after 08:00+8h made the second bar final
        drive(self, self.cfg, row, [(self.NOW + timedelta(hours=8,
                                                          minutes=15),
                                     "105.6")])
        for arm in ("chandelier3", "staged"):
            t = tracks_of(orc)[arm]
            self.assertTrue(t.open, f"{arm}: {t.exit_why} at {t.exit_at}")
            self.assertEqual(t.state["bar_at"], (self.NOW + timedelta(
                hours=8)).isoformat(), "the two bars after its birth")
            self.assertEqual(t.state["since"], opened.isoformat(),
                             "the care's own clock is kept")
