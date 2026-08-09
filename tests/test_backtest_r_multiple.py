"""The backtester's R-multiple must survive a trailing stop.

Same defect as the live grader had: `_check_exits` ratchets
`pos.stop_loss`, and `_close_position` measured risk against that mutated
value — so pnl and risk became the same quantity and every trailing
winner scored ~1R no matter how far the move actually ran.

(The automated promotion gate uses a different path —
signals.evolution_backtest, whose R-multiples come from per-rule
evaluators — so this engine is not what gates money automatically. It is
what `manage.py backtest_v2` and the dashboard report, which is what a
human reads before deciding a strategy is worth funding. A number that
says 1R for every trailing win makes a strategy that trails look
identical to one that doesn't.)

Run with:  python manage.py test tests.test_backtest_r_multiple
"""
from django.test import SimpleTestCase


def _engine():
    from backtester.engine_v2 import BacktestEngineV2
    # No slippage or spread: this test is about the risk denominator, and a
    # fill adjustment would blur the arithmetic it checks.
    return BacktestEngineV2(initial_capital=10_000.0, spread_bps=0.0,
                            impact_bps=0.0)


def _bar(high, low):
    return {"high": high, "low": low, "open": low, "close": high,
            "volume": 1000}


class IntrabarLookAheadTests(SimpleTestCase):
    """A bar gives you a high and a low but not their order. Ratcheting the
    stop on this bar's high and then testing this bar's low against the new
    level assumes the high came first — a coin flip the backtest always
    won, converting round-trip bars into exits at the trailed price."""

    def test_the_trail_does_not_close_the_bar_that_set_it(self):
        eng = _engine()
        eng._open_position("BTCUSD", "BUY", 100.0, 1.0, 98.0, 200.0, 0,
                           "t0", None)
        # High 109 would trail the stop to 106.82; the same bar's low of
        # 100 is below that, but nothing says the high came first.
        eng._check_exits("BTCUSD", _bar(109.0, 100.0), 1, "t1", trail_pct=2.0)
        self.assertEqual(eng.trades, [])
        self.assertIn("BTCUSD", eng.open_positions)

    def test_the_next_bar_does_close_against_the_new_stop(self):
        eng = _engine()
        eng._open_position("BTCUSD", "BUY", 100.0, 1.0, 98.0, 200.0, 0,
                           "t0", None)
        eng._check_exits("BTCUSD", _bar(109.0, 108.0), 1, "t1", trail_pct=2.0)
        eng._check_exits("BTCUSD", _bar(107.5, 105.0), 2, "t2", trail_pct=2.0)
        self.assertEqual(len(eng.trades), 1)
        self.assertEqual(eng.trades[0].exit_reason, "SL")

    def test_the_opening_stop_still_fires_on_the_first_bar(self):
        """Ordering the trail after the exit check must not delay a stop
        that was already in place when the bar opened."""
        eng = _engine()
        eng._open_position("BTCUSD", "BUY", 100.0, 1.0, 98.0, 110.0, 0,
                           "t0", None)
        eng._check_exits("BTCUSD", _bar(101.0, 97.0), 1, "t1", trail_pct=2.0)
        self.assertEqual(len(eng.trades), 1)
        self.assertAlmostEqual(eng.trades[0].r_multiple, -1.0, places=2)


class TrailingStopRMultipleTests(SimpleTestCase):
    def test_a_trailed_winner_reports_its_real_multiple(self):
        eng = _engine()
        # Entry 100, stop 98 -> 2.00 of risk per unit. Target far away so
        # the trail is what closes it.
        eng._open_position("BTCUSD", "BUY", 100.0, 1.0, 98.0, 200.0, 0,
                           "t0", None)
        # Price runs to 109; a 2% trail ratchets the stop to 106.82.
        eng._check_exits("BTCUSD", _bar(109.0, 100.0), 1, "t1", trail_pct=2.0)
        # Next bar dips through the trailed stop.
        eng._check_exits("BTCUSD", _bar(107.5, 106.0), 2, "t2", trail_pct=2.0)

        self.assertEqual(len(eng.trades), 1)
        trade = eng.trades[0]
        self.assertEqual(trade.exit_reason, "SL")
        # Exit 106.82, entry 100 -> 6.82 gain on 2.00 of risk = 3.41R.
        # Measured against the trailed stop it would be ~1.0R.
        self.assertAlmostEqual(trade.r_multiple, 3.41, places=1)

    def test_a_short_trailed_winner_reports_its_real_multiple(self):
        eng = _engine()
        eng._open_position("BTCUSD", "SELL", 100.0, 1.0, 102.0, 50.0, 0,
                           "t0", None)
        eng._check_exits("BTCUSD", _bar(100.0, 91.0), 1, "t1", trail_pct=2.0)
        eng._check_exits("BTCUSD", _bar(93.5, 92.0), 2, "t2", trail_pct=2.0)

        self.assertEqual(len(eng.trades), 1)
        trade = eng.trades[0]
        self.assertEqual(trade.exit_reason, "SL")
        # Exit 92.82, entry 100 -> 7.18 gain on 2.00 of risk, short side.
        self.assertGreater(trade.r_multiple, 3.0)

    def test_an_untrailed_stop_out_is_still_minus_one_r(self):
        eng = _engine()
        eng._open_position("BTCUSD", "BUY", 100.0, 1.0, 98.0, 110.0, 0,
                           "t0", None)
        eng._check_exits("BTCUSD", _bar(100.5, 97.0), 1, "t1", trail_pct=0.0)
        self.assertAlmostEqual(eng.trades[0].r_multiple, -1.0, places=2)

    def test_trailing_still_protects_the_position(self):
        """The fix must not stop the trail from doing its job — the stop
        still ratchets up and still closes the trade."""
        eng = _engine()
        eng._open_position("BTCUSD", "BUY", 100.0, 1.0, 98.0, 200.0, 0,
                           "t0", None)
        eng._check_exits("BTCUSD", _bar(109.0, 100.0), 1, "t1", trail_pct=2.0)
        pos = eng.open_positions["BTCUSD"]
        self.assertAlmostEqual(pos.stop_loss, 106.82, places=2)
        self.assertAlmostEqual(pos.initial_stop_loss, 98.0, places=2)

    def test_a_position_without_the_field_falls_back(self):
        """Defensive: a position built by older code has 0.0 there, and 0.0
        as a stop would make risk equal the entry price — a 100x understated
        R. The fallback has to be the live stop, not the zero."""
        from backtester.engine_v2 import BacktestPosition
        eng = _engine()
        pos = BacktestPosition(symbol="X", side="BUY", entry_price=100.0,
                               qty=1.0, stop_loss=98.0, take_profit=110.0,
                               entry_idx=0, entry_ts="t0")
        eng.open_positions["X"] = pos
        eng._close_position(pos, 104.0, "t1", "TP")
        self.assertAlmostEqual(eng.trades[0].r_multiple, 2.0, places=2)
