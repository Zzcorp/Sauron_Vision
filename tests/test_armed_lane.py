"""Phase 37 — the lane that can actually trade learns structure, order,
seasonality and carry.

Why this file exists
--------------------

`signals/evaluators_advanced.py` is the ONLY evaluator lane that can open a
position. The richer `signals/smc` package writes SmcSignal cards that
`rule_adapter.is_smc_card` deliberately drops before the Signal table, so
anything missing from the advanced evaluators is missing from trading no matter
how well the SMC lane sees it. Three things were missing:

  1. STRUCTURE. Not one of the seventeen Phase 34-36 kinds detected a break of
     structure, a CHoCH, a breaker or equal highs. `advanced_smc_long` — the
     setup `rule_adapter` names as the substitute for SMC cards — was therefore
     an unordered BAG: "a bullish sweep happened AND a bullish FVG exists
     somewhere in the last 5 days AND volume is 1.5x", in any order, on any
     leg. ICT is a SEQUENCE model and the lane could not express sequence at
     all. `EventSequenceTests.test_the_same_two_events_in_the_wrong_order_do_not_match`
     is the whole point of the phase in one method.

  2. CALENDAR. PriceData timestamps were never read as evidence.

  3. CARRY. FundingRate was traded only as a contrarian z-score
     (`funding_rate_extreme`), never as the payment stream it is.

Plus the `order_block` repair: it had no structural anchor, so "price is near
the block" meant a block chosen by an assignment-order accident rather than by
a rule, and every red candle in an uptrend qualified as one.

Run with:  python manage.py test tests.test_armed_lane
"""
import math
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.test import TestCase


# ── Fixture helpers ────────────────────────────────────────────────────────

def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


# Every structure fixture is dated from one fixed instant rather than from
# `timezone.now()`. The seasonality evaluators bucket by CALENDAR position, so a
# fixture anchored to the wall clock would put its bars in different weekday
# buckets on different days and the suite would pass or fail by the date it ran.
_ANCHOR = datetime(2024, 1, 2, 12, 0, tzinfo=dt_timezone.utc)   # a Tuesday


def _seed_bars_from(instrument, bars, start=_ANCHOR, timeframe="1d"):
    """Seed (open, high, low, close, volume) tuples one interval apart from
    `start`. Returns the list of timestamps written, oldest first."""
    from market_data.models import PriceData
    step = timedelta(days=1) if timeframe == "1d" else timedelta(hours=1)
    rows, stamps = [], []
    for i, (o, h, lo, c, v) in enumerate(bars):
        ts = start + step * i
        stamps.append(ts)
        rows.append(PriceData(
            instrument=instrument, timeframe=timeframe, timestamp=ts,
            open=Decimal(str(round(o, 8))), high=Decimal(str(round(h, 8))),
            low=Decimal(str(round(lo, 8))), close=Decimal(str(round(c, 8))),
            volume=int(v), source="test",
        ))
    PriceData.objects.bulk_create(rows)
    return stamps


def _sine_bars(n, base=100.0, amp=4.0, period=8, vol=1000):
    """A clean zig-zag whose crests and troughs are confirmable fractal swings.

    Period 8 with `SWING_FRACTAL_STRENGTH` = 3 puts a strict extreme at the
    centre of every 7-bar window, which is what `smc.pivots.find_pivots`
    requires: flat or noisy fixtures produce NO pivots (ties lose to
    `argmax() == left`) and therefore no structure at all, which is a very easy
    way to write a structure test that proves nothing.

    Swing highs land at 104.2 (bars 10, 18, 26, 34…), lows at 95.8.
    """
    out = []
    for i in range(n):
        c = base + amp * math.sin(2 * math.pi * i / period)
        o = base + amp * math.sin(2 * math.pi * (i - 1) / period)
        out.append((o, max(o, c) + 0.2, min(o, c) - 0.2, c, vol))
    return out


def _now_after(stamps, extra_hours=1):
    """An instant just after the last seeded bar."""
    return stamps[-1] + timedelta(hours=extra_hours)


# Bars used by the sequence fixtures. Named because the ORDER they are placed
# in is the entire subject of those tests.
_SWEEP_BAR = (100.0, 100.5, 93.0, 100.0, 3000)   # takes out the 95.8 swing low
_UP_1 = (100.0, 103.0, 99.5, 102.5, 2000)
_UP_2 = (102.5, 106.0, 102.0, 105.0, 2000)
_BREAK_BAR = (105.0, 108.0, 104.5, 107.0, 3000)  # closes above the 104.2 swing
_DOWN_1 = (107.0, 107.5, 101.0, 102.0, 1500)
_DOWN_2 = (102.0, 102.5, 99.0, 100.0, 1500)


# ══════════════════════════════════════════════════════════════════════════
# 1. Market structure — the concept the armed lane had no detector for
# ══════════════════════════════════════════════════════════════════════════

class MarketStructureBreakTests(TestCase):
    def test_a_close_beyond_a_confirmed_swing_high_is_a_bullish_bos(self):
        from signals.evaluators_advanced import _eval_market_structure_break
        inst = _instrument("MSB1")
        stamps = _seed_bars_from(inst, _sine_bars(40) + [
            (104.0, 110.0, 103.5, 109.0, 3000),   # the break
            (109.0, 109.5, 108.5, 109.0, 1500),
        ])
        res = _eval_market_structure_break(
            {"direction": "bullish", "event": "bos", "lookback": 90,
             "max_age": 5, "timeframe": "1d"}, inst, _now_after(stamps))
        self.assertTrue(res["matched"], res["details"])
        self.assertEqual(res["details"]["type"], "BOS_UP")
        self.assertEqual(res["details"]["broken_swing_price"], 104.2)
        self.assertEqual(res["details"]["age_bars"], 1)
        # 4.8 of displacement against a 2.4 median bar range: two full ranges,
        # so the strength term saturates and only recency is left below 1.0.
        self.assertGreaterEqual(res["details"]["displacement_ranges"], 1.9)
        self.assertGreater(res["score"], 0.9)

    def test_a_zigzag_that_never_takes_out_a_swing_breaks_no_structure(self):
        """The half that matters for a setup: the sweeps and gaps this lane
        already detected are all present in an intact range, and a range is
        precisely where the old bag-of-legs form fired."""
        from signals.evaluators_advanced import _eval_market_structure_break
        inst = _instrument("MSB2")
        stamps = _seed_bars_from(inst, _sine_bars(40))
        res = _eval_market_structure_break(
            {"direction": "bullish", "event": "bos", "lookback": 90,
             "max_age": 5}, inst, _now_after(stamps))
        self.assertFalse(res["matched"])
        self.assertEqual(res["details"]["n_breaks"], 0)
        # It saw the market — eight confirmed swings — and found no break. That
        # is a measurement, not a data failure, and `details` has to let an
        # operator tell the two apart.
        self.assertEqual(res["details"]["n_swings"], 8)

    def test_choch_needs_a_break_that_contradicts_the_previous_one(self):
        """BOS says the direction continued; CHoCH says it changed. A setup
        buying a reversal wants the second, and the seeded `advanced_smc_long`
        asks for exactly that."""
        from signals.evaluators_advanced import _eval_market_structure_break
        inst = _instrument("MSB3")
        stamps = _seed_bars_from(inst, _sine_bars(40) + [
            (97.0, 97.5, 92.0, 93.0, 3000),      # closes under the 95.8 lows
            (93.0, 107.0, 92.5, 106.0, 3000),    # then back over the 104.2 highs
        ])
        now = _now_after(stamps)
        base = {"direction": "bullish", "lookback": 90, "max_age": 5}
        choch = _eval_market_structure_break({**base, "event": "choch"}, inst, now)
        self.assertTrue(choch["matched"], choch["details"])
        self.assertTrue(choch["details"]["choch"])
        self.assertEqual(choch["details"]["age_bars"], 0)

    def test_a_plain_bos_is_not_reported_as_a_choch(self):
        from signals.evaluators_advanced import _eval_market_structure_break
        inst = _instrument("MSB4")
        stamps = _seed_bars_from(inst, _sine_bars(40) + [
            (104.0, 110.0, 103.5, 109.0, 3000),
            (109.0, 109.5, 108.5, 109.0, 1500),
        ])
        now = _now_after(stamps)
        base = {"direction": "bullish", "lookback": 90, "max_age": 5}
        self.assertTrue(_eval_market_structure_break(
            {**base, "event": "bos"}, inst, now)["matched"])
        self.assertFalse(_eval_market_structure_break(
            {**base, "event": "choch"}, inst, now)["matched"])

    def test_a_bos_that_is_not_a_choch_is_not_reported_as_no_bos_at_all(self):
        """The no-match has to name WHICH filter rejected the window.

        This tape holds four fresh BOS_UPs — one close took out four equal
        swing highs — and not one of them changes character, because nothing
        broke downward first. Reported as "no BOS_UP in the last 5 bars" that
        is simply false, and it sends whoever is debugging a silent `choch` leg
        looking for a break that is sitting in the data in front of them.
        """
        from signals.evaluators_advanced import _eval_market_structure_break
        inst = _instrument("MSB9")
        stamps = _seed_bars_from(inst, _sine_bars(40) + [
            (104.0, 110.0, 103.5, 109.0, 3000),
            (109.0, 109.5, 108.5, 109.0, 1500),
        ])
        res = _eval_market_structure_break(
            {"direction": "bullish", "event": "choch", "lookback": 90,
             "max_age": 5}, inst, _now_after(stamps))
        self.assertFalse(res["matched"])
        self.assertEqual(res["details"]["n_fresh_of_type"], 4)
        self.assertIn("none of them a change of character",
                      res["details"]["reason"])
        self.assertNotIn("no BOS_UP", res["details"]["reason"])

    def test_a_market_with_no_break_at_all_still_says_exactly_that(self):
        """The other side of the same message: nothing broke, and the count
        that says so is zero rather than absent."""
        from signals.evaluators_advanced import _eval_market_structure_break
        inst = _instrument("MSB10")
        stamps = _seed_bars_from(inst, _sine_bars(40))
        res = _eval_market_structure_break(
            {"direction": "bullish", "event": "choch", "lookback": 90,
             "max_age": 5}, inst, _now_after(stamps))
        self.assertFalse(res["matched"])
        self.assertEqual(res["details"]["n_fresh_of_type"], 0)
        self.assertIn("no BOS_UP in the last 5 bars", res["details"]["reason"])

    def test_a_break_older_than_max_age_is_not_a_fresh_break(self):
        from signals.evaluators_advanced import _eval_market_structure_break
        inst = _instrument("MSB5")
        drift = [(109.0, 109.5, 108.5, 109.0, 1000)] * 8
        stamps = _seed_bars_from(inst, _sine_bars(40) + [
            (104.0, 110.0, 103.5, 109.0, 3000)] + drift)
        res = _eval_market_structure_break(
            {"direction": "bullish", "event": "bos", "lookback": 90,
             "max_age": 5}, inst, _now_after(stamps))
        self.assertFalse(res["matched"])
        self.assertGreater(res["details"]["n_breaks"], 0)

    def test_the_break_is_bounded_by_now_not_by_the_wall_clock(self):
        """A replay must not be handed the bar that broke structure tomorrow.
        `smc.dataframe.load_ohlcv` takes the last N rows with no upper bound,
        which is why this lane builds its frame from `_recent_bars` instead."""
        from signals.evaluators_advanced import _eval_market_structure_break
        inst = _instrument("MSB6")
        stamps = _seed_bars_from(inst, _sine_bars(40) + [
            (104.0, 110.0, 103.5, 109.0, 3000)])
        params = {"direction": "bullish", "event": "bos", "lookback": 90,
                  "max_age": 5}
        after = _eval_market_structure_break(params, inst, _now_after(stamps))
        self.assertTrue(after["matched"])
        # The same call standing one bar before the break.
        before = _eval_market_structure_break(
            params, inst, stamps[-2] + timedelta(hours=1))
        self.assertFalse(before["matched"], before["details"])

    def test_an_unreadable_market_says_so_instead_of_saying_no_break(self):
        from signals.evaluators_advanced import _eval_market_structure_break
        inst = _instrument("MSB7")
        _seed_bars_from(inst, _sine_bars(4))
        res = _eval_market_structure_break(
            {"direction": "bullish", "lookback": 90}, inst,
            _ANCHOR + timedelta(days=5))
        self.assertFalse(res["matched"])
        self.assertIn("bars", res["details"]["reason"])

    def test_an_out_of_vocabulary_direction_does_not_select_a_branch(self):
        """Two-branch evaluators in this file treat an unrecognised value as the
        ELSE branch, so a typo inverts the condition rather than silencing it."""
        from signals.evaluators_advanced import _eval_market_structure_break
        inst = _instrument("MSB8")
        stamps = _seed_bars_from(inst, _sine_bars(40))
        res = _eval_market_structure_break(
            {"direction": "up", "event": "bos"}, inst, _now_after(stamps))
        self.assertFalse(res["matched"])
        self.assertIn("direction", res["details"]["reason"])


# ══════════════════════════════════════════════════════════════════════════
# 2. ORDER between events — the gap the phase exists to close
# ══════════════════════════════════════════════════════════════════════════

class EventSequenceTests(TestCase):
    def _right_order(self, symbol):
        inst = _instrument(symbol)
        stamps = _seed_bars_from(inst, _sine_bars(36) + [
            _SWEEP_BAR, _UP_1, _UP_2, _BREAK_BAR])
        return inst, _now_after(stamps)

    def _wrong_order(self, symbol):
        """The SAME two events, both inside the window, both fresh — reversed."""
        inst = _instrument(symbol)
        stamps = _seed_bars_from(inst, _sine_bars(36) + [
            _BREAK_BAR, _DOWN_1, _DOWN_2, _SWEEP_BAR])
        return inst, _now_after(stamps)

    _SEQ = {"first": "sweep", "then": "structure_break", "direction": "bullish",
            "lookback": 90, "max_gap_bars": 8, "max_age": 5, "timeframe": "1d"}

    def test_sweep_then_break_is_the_setup(self):
        from signals.evaluators_advanced import _eval_event_sequence
        inst, now = self._right_order("SEQ1")
        res = _eval_event_sequence(dict(self._SEQ), inst, now)
        self.assertTrue(res["matched"], res["details"])
        self.assertEqual(res["details"]["trigger_idx"], 36)
        self.assertEqual(res["details"]["confirmation_idx"], 38)
        self.assertEqual(res["details"]["gap_bars"], 2)

    def test_the_same_two_events_in_the_wrong_order_do_not_match(self):
        """THE test for this phase.

        Both events are present, both are fresh, and both of the standalone
        legs the setup used to be built from fire on this bar. Only the ORDER
        is different — break first, sweep second — which is not a reversal but
        a trend that got tested and held: the opposite trade. The old
        bag-of-legs form of `advanced_smc_long` scored this identically to the
        real setup, and nothing in the lane could tell them apart.
        """
        from signals.evaluators_advanced import (
            _eval_event_sequence, _eval_liquidity_sweep,
            _eval_market_structure_break,
        )
        inst, now = self._wrong_order("SEQ2")

        # The two legs, asked separately, both say yes — as they did before.
        self.assertTrue(_eval_liquidity_sweep(
            {"direction": "bullish_sweep", "lookback": 20, "wick_pct": 0.3},
            inst, now)["matched"])
        self.assertTrue(_eval_market_structure_break(
            {"direction": "bullish", "event": "bos", "lookback": 90,
             "max_age": 5}, inst, now)["matched"])

        res = _eval_event_sequence(dict(self._SEQ), inst, now)
        self.assertFalse(res["matched"], res["details"])
        # And it names WHY: the confirmation is there, the trigger is not
        # before it. A bare "no match" would be indistinguishable from a quiet
        # tape, which is the thing an operator most needs to tell apart.
        self.assertEqual(res["details"]["confirmation_idx"], 36)
        self.assertIn("with no sweep", res["details"]["reason"])

    def test_the_gap_between_the_two_events_is_bounded(self):
        """Ordering alone is not the claim. A sweep eighty bars before a break
        is two unrelated events, and `max_gap_bars` is what says so."""
        from signals.evaluators_advanced import _eval_event_sequence
        inst, now = self._right_order("SEQ3")
        res = _eval_event_sequence({**self._SEQ, "max_gap_bars": 1}, inst, now)
        self.assertFalse(res["matched"])
        self.assertIn("1 bars before it", res["details"]["reason"])

    def test_a_break_that_followed_the_sweep_immediately_scores_higher(self):
        """Same tolerance, same freshness, different gap. A break one bar after
        the sweep is one move; a break several bars later is two events that
        happen to be adjacent, and the score has to separate them."""
        from signals.evaluators_advanced import _eval_event_sequence
        gap1 = _instrument("SEQ4A")
        stamps1 = _seed_bars_from(gap1, _sine_bars(36) + [
            (99.0, 100.0, 98.5, 99.5, 1000), _SWEEP_BAR, _BREAK_BAR,
            (107.0, 107.5, 106.5, 107.0, 1500)])
        gap2 = _instrument("SEQ4B")
        stamps2 = _seed_bars_from(gap2, _sine_bars(36) + [
            _SWEEP_BAR, _UP_1, _BREAK_BAR,
            (107.0, 107.5, 106.5, 107.0, 1500)])
        tight = _eval_event_sequence(dict(self._SEQ), gap1, _now_after(stamps1))
        loose = _eval_event_sequence(dict(self._SEQ), gap2, _now_after(stamps2))
        self.assertTrue(tight["matched"] and loose["matched"])
        self.assertEqual(tight["details"]["gap_bars"], 1)
        self.assertEqual(loose["details"]["gap_bars"], 2)
        self.assertEqual(tight["details"]["age_bars"],
                         loose["details"]["age_bars"])
        self.assertGreater(tight["score"], loose["score"])

    def test_a_bullish_sequence_is_not_a_bearish_one(self):
        from signals.evaluators_advanced import _eval_event_sequence
        inst, now = self._right_order("SEQ5")
        res = _eval_event_sequence({**self._SEQ, "direction": "bearish"},
                                   inst, now)
        self.assertFalse(res["matched"])

    def test_an_unknown_event_name_is_named_rather_than_silently_inert(self):
        """A leg that can never fire and never complains is the defect class
        `test_seed_param_integrity` exists for; the registry can only check the
        values it was handed, so the evaluator checks too."""
        from signals.evaluators_advanced import _eval_event_sequence
        inst, now = self._right_order("SEQ6")
        res = _eval_event_sequence({**self._SEQ, "first": "orderblock"},
                                   inst, now)
        self.assertFalse(res["matched"])
        self.assertIn("orderblock", res["details"]["reason"])
        self.assertIn("sweep", res["details"]["accepted"])

    def test_a_zero_gap_is_refused_because_two_events_cannot_be_ordered_on_one_bar(self):
        from signals.evaluators_advanced import _eval_event_sequence
        inst, now = self._right_order("SEQ7")
        res = _eval_event_sequence({**self._SEQ, "max_gap_bars": 0}, inst, now)
        self.assertFalse(res["matched"])
        self.assertIn("max_gap_bars", res["details"]["reason"])


# ══════════════════════════════════════════════════════════════════════════
# 3. order_block — a structural anchor, and a rule instead of an accident
# ══════════════════════════════════════════════════════════════════════════

def _two_block_bars():
    """Two candidate bullish order blocks, the second higher and later.

    Block A is a red candle at 99.2 whose rally clears a flat 100 shelf; block
    B is a red candle at 102.2 whose rally clears block A's own impulse high.
    Price then returns to block B. Only one of them can be "the" block.
    """
    pad = [(100.0, 100.0, 100.0, 100.0, 1000)] * 12          # 0..11
    return pad + [
        (100.0, 100.2, 99.0, 99.2, 1200),                     # 12  block A
        (99.3, 102.5, 99.2, 102.0, 2000),                     # 13
        (102.0, 103.5, 101.8, 103.0, 2000),                   # 14
        (103.0, 104.5, 102.8, 104.0, 2000),                   # 15
        (104.0, 104.2, 103.0, 103.2, 1200),                   # 16
        (103.2, 103.5, 102.8, 103.0, 1200),                   # 17
        (103.0, 103.2, 102.0, 102.2, 1200),                   # 18  block B
        (102.3, 106.0, 102.2, 105.5, 2200),                   # 19
        (105.5, 107.5, 105.2, 107.0, 2200),                   # 20
        (107.0, 108.5, 106.8, 108.0, 2200),                   # 21
        (108.0, 108.2, 102.4, 102.6, 1800),                   # 22  back to B
    ]


def _unanchored_bars():
    """A red candle and a 3% rally that breaks nothing.

    Price has fallen from 120 to 101, so the level that has been capping it is
    110 and the bounce tops out at 103. Under the old evaluator this matched:
    a red candle, a rally past `min_impulse_pct`, and a last close sitting on
    the block. It is a bounce inside a downtrend, not an order block.
    """
    pad = [(120.0 - i, 120.0 - i, 120.0 - i, 120.0 - i, 1000) for i in range(20)]
    return pad + [
        (101.0, 101.1, 100.0, 100.2, 1200),                   # 20  red candle
        (100.3, 102.5, 100.2, 102.0, 2000),
        (102.0, 103.0, 101.8, 102.8, 2000),
        (102.8, 103.2, 102.0, 102.5, 2000),
        (102.5, 102.6, 100.5, 100.7, 1500),                   # back on the block
    ]


class OrderBlockTests(TestCase):
    _PARAMS = {"direction": "bullish", "lookback": 30, "impulse_window": 3,
               "min_impulse_pct": 1.5, "proximity_pct": 2.0}

    def test_the_most_recent_anchored_block_is_the_one_returned(self):
        """The old loop walked oldest-to-newest and never broke, so which block
        survived was an artefact of assignment order — legible only by tracing
        the overwrite, and silently inverted by any refactor that reversed the
        walk. It has to be a rule: an order block is a level price is expected
        to RETURN to, and the oldest one in a thirty-bar window is a level
        nobody is defending any more."""
        from signals.evaluators_advanced import _eval_order_block
        inst = _instrument("OBN1")
        stamps = _seed_bars_from(inst, _two_block_bars())
        res = _eval_order_block(dict(self._PARAMS), inst, _now_after(stamps))
        self.assertTrue(res["matched"], res["details"])
        self.assertAlmostEqual(res["details"]["block_mid"], 102.6, places=6)
        self.assertNotAlmostEqual(res["details"]["block_mid"], 99.6, places=6)
        self.assertEqual(res["details"]["age_bars"], 4)

    def test_an_impulse_that_broke_nothing_is_not_an_order_block(self):
        from signals.evaluators_advanced import _eval_order_block
        inst = _instrument("OBN2")
        stamps = _seed_bars_from(inst, _unanchored_bars())
        res = _eval_order_block(dict(self._PARAMS), inst, _now_after(stamps))
        self.assertFalse(res["matched"], res["details"])
        self.assertIn("structurally-anchored", res["details"]["reason"])
        # "none found" and "one found, which broke nothing" are different
        # markets, and the operator tuning min_impulse_pct needs to know which.
        self.assertEqual(res["details"]["unanchored_candidates"], 1)

    def test_the_anchor_level_is_reported_so_the_rejection_is_checkable(self):
        from signals.evaluators_advanced import _eval_order_block
        inst = _instrument("OBN3")
        stamps = _seed_bars_from(inst, _two_block_bars())
        res = _eval_order_block(dict(self._PARAMS), inst, _now_after(stamps))
        # Block B's impulse had to close above block A's impulse high of 104.5.
        self.assertAlmostEqual(res["details"]["structure_level"], 104.5, places=6)

    def test_a_flat_tape_still_produces_no_block(self):
        from signals.evaluators_advanced import _eval_order_block
        inst = _instrument("OBN4")
        stamps = _seed_bars_from(inst, [(100.0, 100.0, 100.0, 100.0, 1000)] * 40)
        res = _eval_order_block({"direction": "bullish"}, inst,
                                _now_after(stamps))
        self.assertFalse(res["matched"])
        self.assertEqual(res["details"]["unanchored_candidates"], 0)


# ══════════════════════════════════════════════════════════════════════════
# 4. Seasonality — the evidence that was already in the timestamps
# ══════════════════════════════════════════════════════════════════════════

def _seed_calendar_series(inst, n_days, bump, predicate, start=_ANCHOR):
    """Daily bars where a bar matching `predicate(ts)` returns `bump` percent
    over the previous close and every other bar returns exactly zero."""
    bars, close = [], 100.0
    stamps = []
    for i in range(n_days):
        ts = start + timedelta(days=i)
        if i and predicate(ts):
            close = close * (1.0 + bump / 100.0)
        bars.append((close, close, close, close, 1000))
        stamps.append(ts)
    _seed_bars_from(inst, bars, start=start)
    return stamps


class SeasonalBiasTests(TestCase):
    def test_a_measured_weekday_edge_on_the_symbols_own_history_matches(self):
        from signals.evaluators_advanced import _eval_seasonal_bias
        inst = _instrument("SEA1")
        stamps = _seed_calendar_series(
            inst, 400, bump=1.0, predicate=lambda ts: ts.weekday() == 1)
        now = max(ts for ts in stamps if ts.weekday() == 1)
        res = _eval_seasonal_bias(
            {"mode": "day_of_week", "direction": "bullish",
             "lookback_days": 400, "min_observations": 30,
             "min_edge_pct": 0.05, "timeframe": "1d"}, inst, now)
        self.assertTrue(res["matched"], res["details"])
        self.assertEqual(res["details"]["bucket"], "Tuesday")
        self.assertTrue(res["details"]["measured"])
        self.assertGreaterEqual(res["details"]["n_observations"], 30)
        self.assertAlmostEqual(res["details"]["mean_return_pct"], 1.0, places=4)
        self.assertEqual(res["details"]["share_positive"], 1.0)
        self.assertEqual(res["details"]["tz"], "UTC")

    def test_a_bucket_with_too_few_observations_is_reported_not_scored(self):
        """A seasonal edge from five observations is not an edge. The evaluator
        has to say that rather than score it — and `mean_return_pct` is None,
        not 0.0, because nothing was measured and a confident zero would read
        on the flag as 'we looked and there is no effect'."""
        from signals.evaluators_advanced import _eval_seasonal_bias
        inst = _instrument("SEA2")
        stamps = _seed_calendar_series(
            inst, 36, bump=1.0, predicate=lambda ts: ts.weekday() == 1)
        now = max(ts for ts in stamps if ts.weekday() == 1)
        res = _eval_seasonal_bias(
            {"mode": "day_of_week", "direction": "bullish",
             "lookback_days": 400, "min_observations": 20,
             "min_edge_pct": 0.05}, inst, now)
        self.assertFalse(res["matched"])
        self.assertEqual(res["score"], 0.0)
        self.assertFalse(res["details"]["measured"])
        self.assertIsNone(res["details"]["mean_return_pct"])
        self.assertIsNone(res["details"]["t_stat"])
        self.assertEqual(res["details"]["n_observations"], 5)
        self.assertIn("anecdote", res["details"]["reason"])

    def test_the_direction_is_a_branch_the_setup_has_to_ask_for(self):
        """`scan_setup` writes `setup.direction` verbatim into the Signal, so a
        bullish setup carrying a leg that also accepts a negative mean would
        publish half its flags upside-down."""
        from signals.evaluators_advanced import _eval_seasonal_bias
        inst = _instrument("SEA3")
        stamps = _seed_calendar_series(
            inst, 400, bump=-1.0, predicate=lambda ts: ts.weekday() == 4)
        now = max(ts for ts in stamps if ts.weekday() == 4)
        params = {"mode": "day_of_week", "lookback_days": 400,
                  "min_observations": 30, "min_edge_pct": 0.05}
        bear = _eval_seasonal_bias({**params, "direction": "bearish"}, inst, now)
        bull = _eval_seasonal_bias({**params, "direction": "bullish"}, inst, now)
        self.assertTrue(bear["matched"], bear["details"])
        self.assertEqual(bear["details"]["bucket"], "Friday")
        self.assertFalse(bull["matched"])

    def test_a_bucket_the_symbol_shows_nothing_in_does_not_match(self):
        from signals.evaluators_advanced import _eval_seasonal_bias
        inst = _instrument("SEA4")
        stamps = _seed_calendar_series(
            inst, 400, bump=1.0, predicate=lambda ts: ts.weekday() == 1)
        now = max(ts for ts in stamps if ts.weekday() == 3)   # a Thursday
        res = _eval_seasonal_bias(
            {"mode": "day_of_week", "direction": "bullish",
             "lookback_days": 400, "min_observations": 30,
             "min_edge_pct": 0.05}, inst, now)
        self.assertFalse(res["matched"])
        self.assertTrue(res["details"]["measured"])
        self.assertEqual(res["details"]["mean_return_pct"], 0.0)

    def test_turn_of_month_buckets_the_boundary_not_the_calendar_month(self):
        from signals.evaluators_advanced import (
            TURN_OF_MONTH_WINDOW_DAYS, _eval_seasonal_bias,
        )
        self.assertEqual(TURN_OF_MONTH_WINDOW_DAYS, 3)
        inst = _instrument("SEA5")
        import calendar as _cal

        def at_turn(ts):
            last = _cal.monthrange(ts.year, ts.month)[1]
            return ts.day <= 3 or ts.day > last - 3

        stamps = _seed_calendar_series(inst, 400, bump=0.4, predicate=at_turn)
        now = max(ts for ts in stamps if ts.day <= 3)
        res = _eval_seasonal_bias(
            {"mode": "turn_of_month", "direction": "bullish",
             "lookback_days": 1095, "min_observations": 30,
             "min_edge_pct": 0.05}, inst, now)
        self.assertTrue(res["matched"], res["details"])
        self.assertEqual(res["details"]["bucket"], "turn")
        self.assertAlmostEqual(res["details"]["mean_return_pct"], 0.4, places=4)

    def test_turn_of_month_declines_every_day_that_is_not_the_turn(self):
        """The bucket a calendar setup must never be scored on.

        `turn_of_month` splits the year in two and only one half is the claim.
        "rest" is every ordinary mid-month day, so its mean is the
        instrument's drift with the calendar effect removed — and on anything
        in a multi-year uptrend that mean is reliably positive and tight. This
        tape is the extreme case: it rises 0.4% EVERY day, so the "rest"
        bucket has ~270 observations, a t-statistic in the hundreds and no
        seasonality in it whatsoever. Scored, it made
        `advanced_seasonal_turn_long` an ordinary trend setup wearing a
        calendar label, taking trades on the 15th.
        """
        from signals.evaluators_advanced import _eval_seasonal_bias
        inst = _instrument("SEA9")
        stamps = _seed_calendar_series(inst, 400, bump=0.4,
                                        predicate=lambda ts: True)
        params = {"mode": "turn_of_month", "direction": "bullish",
                  "lookback_days": 1095, "min_observations": 30,
                  "min_edge_pct": 0.05}
        mid_month = max(ts for ts in stamps if ts.day == 15)
        res = _eval_seasonal_bias(params, inst, mid_month)
        self.assertFalse(res["matched"])
        self.assertEqual(res["score"], 0.0)
        self.assertEqual(res["details"]["bucket"], "rest")
        self.assertFalse(res["details"]["measured"])
        # Nothing was measured, so nothing is reported as a number. A 0.0 here
        # would read on the flag as "we looked at the calendar effect and
        # there is none", which is a different and untrue statement.
        self.assertIsNone(res["details"]["mean_return_pct"])
        self.assertIsNone(res["details"]["t_stat"])
        self.assertIsNone(res["details"]["n_observations"])
        self.assertIn("not in the turn_of_month window", res["details"]["reason"])

        # Same tape, same params, asked at the turn: it fires. The refusal is
        # about WHEN the question was asked, not about the data.
        at_turn = max(ts for ts in stamps if ts.day <= 3)
        turn = _eval_seasonal_bias(params, inst, at_turn)
        self.assertTrue(turn["matched"], turn["details"])
        self.assertEqual(turn["details"]["bucket"], "turn")

    def test_month_of_year_is_the_mode_the_sample_size_check_exists_for(self):
        """`n_observations` counts BARS in the bucket, not seasons. A month
        bucket over three years holds ~60 daily returns and THREE Februaries,
        so its bar count overstates how much independent evidence there is —
        which is exactly why the seed pack does not seed this mode and why a
        setup that wants it has to raise `min_observations` deliberately. Asked
        for more than the window can hold, the evaluator reports the count and
        declines to average it."""
        from signals.evaluators_advanced import _eval_seasonal_bias
        inst = _instrument("SEA6")
        stamps = _seed_calendar_series(
            inst, 400, bump=0.5, predicate=lambda ts: ts.month == 1)
        now = stamps[-1]
        res = _eval_seasonal_bias(
            {"mode": "month_of_year", "direction": "bullish",
             "lookback_days": 1095, "min_observations": 200,
             "min_edge_pct": 0.05}, inst, now)
        self.assertFalse(res["matched"])
        self.assertFalse(res["details"]["measured"])
        self.assertIsNone(res["details"]["mean_return_pct"])
        self.assertLess(res["details"]["n_observations"], 200)

    def test_time_of_day_buckets_by_utc_hour_on_intraday_bars(self):
        from signals.evaluators_advanced import _eval_seasonal_bias
        inst = _instrument("SEA7")
        bars, close, stamps = [], 100.0, []
        for i in range(24 * 30):
            ts = _ANCHOR + timedelta(hours=i)
            if i and ts.hour == 13:
                close = close * 1.005
            bars.append((close, close, close, close, 1000))
            stamps.append(ts)
        _seed_bars_from(inst, bars, timeframe="1h")
        now = max(ts for ts in stamps if ts.hour == 13)
        res = _eval_seasonal_bias(
            {"mode": "time_of_day", "direction": "bullish",
             "lookback_days": 60, "min_observations": 20,
             "min_edge_pct": 0.05, "timeframe": "1h"}, inst, now)
        self.assertTrue(res["matched"], res["details"])
        self.assertEqual(res["details"]["bucket"], "13:00Z")
        self.assertGreaterEqual(res["details"]["n_observations"], 20)

    def test_an_unknown_mode_names_the_vocabulary_it_wanted(self):
        from signals.evaluators_advanced import _eval_seasonal_bias
        inst = _instrument("SEA8")
        stamps = _seed_calendar_series(
            inst, 60, bump=1.0, predicate=lambda ts: ts.weekday() == 1)
        res = _eval_seasonal_bias({"mode": "quarter"}, inst, stamps[-1])
        self.assertFalse(res["matched"])
        self.assertIn("day_of_week", res["details"]["accepted"])


# ══════════════════════════════════════════════════════════════════════════
# 5. Funding carry — the same table `funding_rate_extreme` reads, the other way
# ══════════════════════════════════════════════════════════════════════════

_FUNDING_START = datetime(2025, 6, 1, tzinfo=dt_timezone.utc)


def _seed_funding(symbol, rate_for_day, days, per_day=8, start=_FUNDING_START):
    """`rate_for_day(day_index, row_index)` -> the 8-hourly funding rate."""
    from market_data.models import FundingRate
    rows, idx = [], 0
    for d in range(days):
        for h in range(0, 24, 24 // per_day):
            rows.append(FundingRate(
                symbol=symbol, mark_price=Decimal("60000"),
                index_price=Decimal("60000"),
                funding_rate=Decimal(str(rate_for_day(d, idx))),
                timestamp=start + timedelta(days=d, hours=h)))
            idx += 1
    FundingRate.objects.bulk_create(rows)
    return start + timedelta(days=days)


class FundingCarryTests(TestCase):
    _PARAMS = {"direction": "collect_short", "lookback_days": 14,
               "min_annualized_pct": 20.0, "min_persistence": 0.85,
               "min_days_covered": 10}

    def test_persistent_positive_funding_pays_the_short(self):
        from signals.evaluators_advanced import _eval_funding_carry
        inst = _instrument("BTCUSDT", asset_class="crypto")
        now = _seed_funding("BTCUSDT", lambda d, i: 0.0008, days=20)
        res = _eval_funding_carry(dict(self._PARAMS), inst, now)
        self.assertTrue(res["matched"], res["details"])
        self.assertEqual(res["details"]["persistence"], 1.0)
        self.assertEqual(res["details"]["days_covered"], 14)
        # 0.08%/8h × 3 × 365 = 87.6%/yr, and 8x Binance's 0.01% base rate.
        self.assertAlmostEqual(res["details"]["annualized_pct"], 87.6, places=1)
        self.assertAlmostEqual(res["details"]["base_rate_multiple"], 8.0, places=3)

    def test_the_long_side_of_the_same_tape_collects_nothing(self):
        from signals.evaluators_advanced import _eval_funding_carry
        inst = _instrument("BTCUSDT", asset_class="crypto")
        now = _seed_funding("BTCUSDT", lambda d, i: 0.0008, days=20)
        res = _eval_funding_carry({**self._PARAMS, "direction": "collect_long"},
                                  inst, now)
        self.assertFalse(res["matched"])

    def test_a_big_average_built_out_of_spikes_is_not_carry(self):
        """Carry is a payment stream, not a mean. This tape's annualised figure
        clears the threshold comfortably and it still must not fire: funding
        pays the short on only two settlements in five, so on the other three
        the position is paying to be on. Averaging hides that; persistence is
        the term that sees it."""
        from signals.evaluators_advanced import _eval_funding_carry
        inst = _instrument("ETHUSDT", asset_class="crypto")
        now = _seed_funding("ETHUSDT",
                            lambda d, i: (0.0015 if i % 5 < 2 else -0.0002),
                            days=20)
        res = _eval_funding_carry(dict(self._PARAMS), inst, now)
        self.assertFalse(res["matched"], res["details"])
        self.assertGreater(res["details"]["annualized_pct"],
                           self._PARAMS["min_annualized_pct"])
        self.assertLess(res["details"]["persistence"],
                        self._PARAMS["min_persistence"])
        self.assertGreater(res["details"]["persistence"], 0.3)

    def test_a_tick_by_tick_feed_is_still_measured_over_the_whole_window(self):
        """FundingRate is a TICK table, not a settlement table.

        `stream_binance_futures.save_funding` writes a row per @markPrice
        message — thousands a day per symbol against the three settlements a
        day the rate actually changes on — and `cleanup_funding` keeps 60 days
        of them. So the evaluator must not pull the window into memory, and it
        equally must not solve that with a LIMIT: the newest N rows of this
        feed are a few hours, which would collapse `days_covered` and make the
        leg refuse the symbols that are best covered. This seeds an hourly
        feed — 336 rows in the window — and asks for the numbers that a
        truncated read would get wrong.
        """
        from signals.evaluators_advanced import _eval_funding_carry
        inst = _instrument("DENSEUSDT", asset_class="crypto")
        now = _seed_funding("DENSEUSDT", lambda d, i: 0.0008, days=16,
                            per_day=24)
        res = _eval_funding_carry(dict(self._PARAMS), inst, now)
        self.assertTrue(res["matched"], res["details"])
        self.assertEqual(res["details"]["n_snapshots"], 14 * 24)
        self.assertEqual(res["details"]["days_covered"], 14)
        self.assertEqual(res["details"]["persistence"], 1.0)
        self.assertAlmostEqual(res["details"]["annualized_pct"], 87.6, places=1)

    def test_persistence_on_a_dense_feed_counts_every_tick_not_a_sample(self):
        """The other half of the aggregate: the paying-side count and the mean
        have to describe the same rows the snapshot count does. Funding pays
        the short on two ticks in five here, so the leg must refuse whatever
        the annualised figure looks like."""
        from signals.evaluators_advanced import _eval_funding_carry
        inst = _instrument("DENSE2USDT", asset_class="crypto")
        now = _seed_funding("DENSE2USDT",
                            lambda d, i: (0.0015 if i % 5 < 2 else -0.0002),
                            days=16, per_day=24)
        res = _eval_funding_carry(dict(self._PARAMS), inst, now)
        self.assertFalse(res["matched"], res["details"])
        self.assertEqual(res["details"]["n_snapshots"], 14 * 24)
        # 134 of the window's 336 ticks are on the paying side — a fraction of
        # the whole window, not of whatever tail a truncated read would see.
        self.assertEqual(res["details"]["persistence"], round(134 / 336, 4))
        self.assertLess(res["details"]["persistence"],
                        self._PARAMS["min_persistence"])
        self.assertGreater(res["details"]["annualized_pct"],
                           self._PARAMS["min_annualized_pct"])

    def test_an_afternoon_of_snapshots_is_not_a_fortnights_carry(self):
        from signals.evaluators_advanced import _eval_funding_carry
        inst = _instrument("SOLUSDT", asset_class="crypto")
        _seed_funding("SOLUSDT", lambda d, i: 0.0008, days=2, per_day=24)
        now = _FUNDING_START + timedelta(days=14)
        res = _eval_funding_carry(dict(self._PARAMS), inst, now)
        self.assertFalse(res["matched"])
        self.assertFalse(res["details"]["measured"])
        self.assertIsNone(res["details"]["annualized_pct"])
        self.assertEqual(res["details"]["days_covered"], 2)

    def test_a_symbol_the_funding_feed_does_not_carry_says_so(self):
        """FundingRate is keyed by the EXCHANGE's perp symbol and has no FK to
        Instrument, so an install storing 'BTCUSD' finds nothing under Binance's
        'BTCUSDT'. A zero-row read must not look like a market with no skew."""
        from signals.evaluators_advanced import _eval_funding_carry
        inst = _instrument("BTCUSD", asset_class="crypto")
        now = _seed_funding("BTCUSDT", lambda d, i: 0.0008, days=20)
        res = _eval_funding_carry(dict(self._PARAMS), inst, now)
        self.assertFalse(res["matched"])
        self.assertEqual(res["details"]["n_snapshots"], 0)
        self.assertEqual(res["details"]["symbol"], "BTCUSD")

    def test_the_carry_window_is_bounded_by_now(self):
        from signals.evaluators_advanced import _eval_funding_carry
        inst = _instrument("BTCUSDT", asset_class="crypto")
        _seed_funding("BTCUSDT", lambda d, i: 0.0008, days=20)
        res = _eval_funding_carry(dict(self._PARAMS), inst,
                                  _FUNDING_START - timedelta(days=1))
        self.assertFalse(res["matched"])
        self.assertEqual(res["details"]["n_snapshots"], 0)

    def test_carry_and_the_contrarian_z_score_can_point_opposite_ways(self):
        """Documented on purpose, because two setups on one table pointing
        opposite ways is fine if the platform knows it and dangerous if it does
        not.

        Funding sat at 0.08% for four weeks and has just eased to 0.02%. The
        z-score of the latest print against its own 30-day mean is far below
        -2.5, so `FundingExtremeRule` publishes LONG ('crowded shorts'). Funding
        is still positive and still persistent, so `funding_carry` publishes
        SHORT. Neither is wrong: one measures the DEVIATION over hours, the
        other the LEVEL over weeks. `AssetBot.decide()` votes by headcount, so
        the reviewer needs `details["measures"]` to see at a glance that the two
        cards are one dataset read two ways.
        """
        from signals.evaluators_advanced import _eval_funding_carry
        from signals.rules.flow_rules import _zscore
        from market_data.models import FundingRate
        inst = _instrument("BTCUSDT", asset_class="crypto")
        now = _seed_funding("BTCUSDT",
                            lambda d, i: (0.0002 if d >= 28 else 0.0008),
                            days=30)

        rates = [float(r) for r in FundingRate.objects
                 .filter(symbol="BTCUSDT").order_by("timestamp")
                 .values_list("funding_rate", flat=True)]
        z = _zscore(rates)
        self.assertLess(z, -2.5, "the contrarian lane would read this as LONG")

        carry = _eval_funding_carry(dict(self._PARAMS), inst, now)
        self.assertTrue(carry["matched"], carry["details"])
        self.assertEqual(carry["details"]["measures"], "level_and_persistence")
        self.assertGreater(carry["details"]["annualized_pct"], 20.0)

    def test_the_snapshot_floor_agrees_with_the_lane_it_shares_a_table_with(self):
        """`FundingExtremeRule` refuses below 30 rows. Two readings of one table
        disagreeing about when the table has anything to say would let one lane
        trade a symbol the other considers uncovered."""
        from signals.evaluators_advanced import MIN_FUNDING_SNAPSHOTS
        self.assertEqual(MIN_FUNDING_SNAPSHOTS, 30)

    def test_the_threshold_sits_above_binances_own_base_rate(self):
        """0.01%/8h is the level funding reverts to with no positioning skew at
        all; it annualises to ~11%. A default at or below that would fire on a
        neutral market and call it carry."""
        from signals.evaluators_advanced import (
            FUNDING_BASE_RATE, FUNDING_INTERVALS_PER_DAY, _eval_funding_carry,
        )
        base_annualized = FUNDING_BASE_RATE * FUNDING_INTERVALS_PER_DAY * 365 * 100
        self.assertAlmostEqual(base_annualized, 10.95, places=2)
        inst = _instrument("BASEUSDT", asset_class="crypto")
        now = _seed_funding("BASEUSDT", lambda d, i: FUNDING_BASE_RATE, days=20)
        # Default min_annualized_pct (15.0), i.e. no threshold supplied.
        res = _eval_funding_carry({"direction": "collect_short",
                                   "lookback_days": 14}, inst, now)
        self.assertFalse(res["matched"], res["details"])
        self.assertLess(res["details"]["annualized_pct"], 15.0)


# ══════════════════════════════════════════════════════════════════════════
# 6. The seed pack: the new kinds actually reach the lane that can trade
# ══════════════════════════════════════════════════════════════════════════

class ArmedLaneSeedTests(TestCase):
    def _advanced(self):
        from signals.management.commands.seed_advanced_strategies import (
            _setup_definitions,
        )
        return {s["name"]: s for s in _setup_definitions()}

    def test_every_phase_37_kind_is_registered(self):
        from signals.opportunity_scanner import has_kind
        from signals.evaluators_advanced import ADVANCED_EVALUATORS
        for kind in ("market_structure_break", "event_sequence",
                     "seasonal_bias", "funding_carry"):
            with self.subTest(kind=kind):
                self.assertTrue(has_kind(kind))
                self.assertIn(kind, ADVANCED_EVALUATORS)

    def test_both_smc_setups_now_carry_a_structure_leg(self):
        """The lane `rule_adapter` names as the tradeable substitute for SMC
        cards is the one that had no structure at all."""
        specs = self._advanced()
        for name, direction in (("advanced_smc_long", "bullish"),
                                ("advanced_smc_short", "bearish")):
            with self.subTest(setup=name):
                kinds = {c["kind"]: c for c in specs[name]["conditions"]}
                self.assertIn("event_sequence", kinds)
                self.assertIn("market_structure_break", kinds)
                seq = kinds["event_sequence"]["params"]
                self.assertEqual(seq["first"], "sweep")
                self.assertEqual(seq["then"], "structure_break")
                self.assertEqual(seq["direction"], direction)
                self.assertEqual(
                    kinds["market_structure_break"]["params"]["direction"],
                    direction)

    def test_the_two_new_families_are_seeded_as_setups(self):
        """An evaluator no setup carries is still missing from trading."""
        specs = self._advanced()
        self.assertIn("advanced_seasonal_turn_long", specs)
        self.assertIn("advanced_funding_carry_short", specs)
        seasonal = {c["kind"] for c
                    in specs["advanced_seasonal_turn_long"]["conditions"]}
        carry = {c["kind"] for c
                 in specs["advanced_funding_carry_short"]["conditions"]}
        self.assertIn("seasonal_bias", seasonal)
        self.assertIn("funding_carry", carry)

    def test_every_new_seeded_condition_passes_the_param_guard(self):
        """The same check `test_seed_param_integrity` applies to the whole pack,
        pinned here too so this slice is self-checking: a param key the
        evaluator never reads makes the condition run on defaults, and a value
        outside the vocabulary selects the opposite branch."""
        from signals.opportunity_scanner import (
            has_kind, invalid_param_values, unknown_param_keys,
            unknown_sizing_keys,
        )
        new = ("advanced_smc_long", "advanced_smc_short",
               "advanced_seasonal_turn_long", "advanced_funding_carry_short")
        specs = self._advanced()
        for name in new:
            spec = specs[name]
            self.assertEqual(unknown_sizing_keys(spec.get("sizing") or {}), [])
            for cond in spec["conditions"]:
                kind = cond["kind"]
                params = cond.get("params") or {}
                with self.subTest(setup=name, kind=kind):
                    self.assertTrue(has_kind(kind))
                    self.assertEqual(unknown_param_keys(kind, params), [])
                    self.assertEqual(invalid_param_values(kind, params), [])

    def test_the_seasonal_leg_asks_for_a_window_that_can_hold_its_sample(self):
        """`min_observations` is only honest if the seeded `lookback_days` can
        actually contain that many of the bucket. Turn-of-month is six calendar
        days a month, so 1095 days holds ~216 of them on crypto and ~150 on a
        five-day instrument — comfortably past 30. The same window on
        `month_of_year` would hold three, which is why the pack does not seed
        that mode."""
        from signals.evaluators_advanced import TURN_OF_MONTH_WINDOW_DAYS
        leg = next(c for c in
                   self._advanced()["advanced_seasonal_turn_long"]["conditions"]
                   if c["kind"] == "seasonal_bias")
        p = leg["params"]
        self.assertEqual(p["mode"], "turn_of_month")
        turn_days_per_month = TURN_OF_MONTH_WINDOW_DAYS * 2
        months = p["lookback_days"] / 30.44
        weekday_fraction = 5 / 7          # the worst case in this universe
        self.assertGreater(months * turn_days_per_month * weekday_fraction,
                           p["min_observations"] * 2)

    def test_the_seeded_seasonal_setup_is_dark_on_days_that_are_not_the_turn(self):
        """End to end, on the tape that used to fool it: an instrument that
        rises 0.4% every single day.

        Every leg of `advanced_seasonal_turn_long` says yes on such a tape —
        price is above its 50-day MA, the 5% tail is nowhere near -6%, and the
        calendar bucket has a large positive mean — but on the 15th the bucket
        being measured is "rest", which is the drift and not a season. The
        setup has to be dark on those days and live at the turn, or it is a
        momentum setup with a calendar-shaped name.
        """
        from signals.models_opportunity import OpportunitySetup
        from signals.opportunity_scanner import scan_setup
        spec = self._advanced()["advanced_seasonal_turn_long"]
        setup = OpportunitySetup.objects.create(
            name=spec["name"], description=spec["description"],
            direction=spec["direction"], asset_classes=spec["asset_classes"],
            conditions=spec["conditions"],
            min_match_score=spec["min_match_score"],
            suggested_horizon_days=spec["suggested_horizon_days"],
            sizing=spec.get("sizing", {}), is_active=True)
        inst = _instrument("SEASONFIRE", asset_class="stock")
        stamps = _seed_calendar_series(inst, 400, bump=0.4,
                                        predicate=lambda ts: True)

        mid_month = max(ts for ts in stamps if ts.day == 15)
        quiet = scan_setup(setup, inst, now=mid_month, as_of=True, emit=False)
        self.assertFalse(quiet["matched"], msg=f"score={quiet.get('score')}")
        seasonal = next(c for c in quiet["conditions"]
                        if c["kind"] == "seasonal_bias")
        self.assertEqual(seasonal["details"]["bucket"], "rest")
        self.assertFalse(seasonal["details"]["measured"])

        at_turn = max(ts for ts in stamps if ts.day <= 3)
        live = scan_setup(setup, inst, now=at_turn, as_of=True, emit=False)
        self.assertTrue(live["matched"], msg=f"score={live.get('score')}")

    def test_the_seasonal_trend_filter_is_a_gate_not_a_weighted_leg(self):
        """Two reasons, and both matter. "Not in a downtrend" is a precondition
        of a calendar thesis — no seasonal reading makes buying the turn of the
        month into a falling tape the same trade. And `above_ma` scores
        (last-ma)/ma × 5, so as a weighted leg it would contribute ~0.15 while
        occupying 0.8 of the denominator: a fixed penalty on every match rather
        than a filter."""
        leg = next(c for c in
                   self._advanced()["advanced_seasonal_turn_long"]["conditions"]
                   if c["kind"] == "price_pattern")
        self.assertTrue(leg.get("gate"))
        self.assertNotIn("weight", leg)

    def test_the_carry_leg_asks_for_more_than_the_base_funding_rate(self):
        from signals.evaluators_advanced import (
            FUNDING_BASE_RATE, FUNDING_INTERVALS_PER_DAY,
        )
        leg = next(c for c in
                   self._advanced()["advanced_funding_carry_short"]["conditions"]
                   if c["kind"] == "funding_carry")
        base_annualized = FUNDING_BASE_RATE * FUNDING_INTERVALS_PER_DAY * 365 * 100
        self.assertGreater(leg["params"]["min_annualized_pct"], base_annualized)

    def test_no_advanced_setup_outlives_the_time_stop_of_a_class_it_trades(self):
        """A horizon longer than its class ceiling is a thesis the engine
        cannot let run.

        `DEFAULT_MAX_HOLD_HOURS` flattens an unresolved position with reason
        TIME, and crypto's ceiling is 192h — the pack's longest crypto thesis
        plus one day of slack, on a 24/7 calendar with no weekends to absorb
        it. A 14-day carry horizon under that ceiling is stopped on day 8, six
        days before the window it was measured over closes: it can never
        realise the edge it claims, and every trade that would have worked
        resolves as a TIME exit and is graded against the rule that opened it.
        Read from the pack rather than listed, so this fires on the next setup
        rather than on the next audit.
        """
        from bot_program.asset_models import AssetBotConfig
        for spec in self._advanced().values():
            for asset_class in spec["asset_classes"]:
                with self.subTest(setup=spec["name"], asset_class=asset_class):
                    ceiling = AssetBotConfig.default_max_hold_hours(asset_class)
                    self.assertLessEqual(
                        spec["suggested_horizon_days"] * 24.0, ceiling,
                        msg=(f"{spec['name']} declares "
                             f"{spec['suggested_horizon_days']}d on "
                             f"{asset_class}, whose time stop is {ceiling}h"))

    def test_the_carry_horizon_is_a_holding_period_not_the_measurement_window(self):
        """The carry leg measures a fortnight of funding and the position is
        held for a week, and that is not a contradiction: carry accrues per
        settlement, so half the window is half the carry at the same rate.
        What the horizon may NOT do is outlive the crypto time stop, which is
        what pins it at seven days."""
        spec = self._advanced()["advanced_funding_carry_short"]
        leg = next(c for c in spec["conditions"] if c["kind"] == "funding_carry")
        self.assertEqual(spec["asset_classes"], ["crypto"])
        self.assertEqual(spec["suggested_horizon_days"], 7)
        self.assertEqual(leg["params"]["lookback_days"], 14)

    def test_the_carry_setup_names_its_target_instead_of_defaulting_to_2r(self):
        """`_suggested_levels` reads stop_pct and target_rr and nothing else, so
        an omitted target_rr silently becomes 2.0 — grading a carry trade
        against a move it never forecast."""
        sizing = self._advanced()["advanced_funding_carry_short"]["sizing"]
        self.assertIn("target_rr", sizing)
        self.assertEqual(sizing["target_rr"], 1.0)

    def test_the_setups_no_longer_carry_a_leg_that_cannot_fire_with_the_others(self):
        """`liquidity_sweep` reads the CURRENT bar only, while `event_sequence`
        requires the sweep STRICTLY BEFORE the break. Both firing at once would
        need one bar to be simultaneously the sweep and a bar before the break.
        Keeping it would have parked dead weight in the denominator on every bar
        the setup could ever match — the same arithmetic incompatibility
        `starter_commodity_vol_compression` was repaired for."""
        for name in ("advanced_smc_long", "advanced_smc_short"):
            with self.subTest(setup=name):
                kinds = {c["kind"] for c in self._advanced()[name]["conditions"]}
                self.assertNotIn("liquidity_sweep", kinds)

    def _armed_smc_setup(self):
        from signals.models_opportunity import OpportunitySetup
        spec = self._advanced()["advanced_smc_long"]
        return OpportunitySetup.objects.create(
            name=spec["name"], description=spec["description"],
            direction=spec["direction"], asset_classes=spec["asset_classes"],
            conditions=spec["conditions"],
            min_match_score=spec["min_match_score"],
            suggested_horizon_days=spec["suggested_horizon_days"],
            sizing=spec.get("sizing", {}), is_active=True)

    # The full thesis in bars: an intact range, a downside break, a sweep of the
    # lows that closes back inside, then a rally that breaks the range highs —
    # which contradicts the downside break and is therefore a CHoCH. The break
    # bar carries 6x volume and leaves an imbalance behind it.
    _CHOCH_SEQUENCE = [
        (96.0, 96.5, 92.0, 93.0, 3000),      # 36 — closes under the 95.8 lows
        (94.0, 96.5, 90.0, 96.0, 3500),      # 37 — sweeps them, closes inside
        (96.0, 105.0, 95.8, 104.0, 6000),    # 38 — impulse
        (104.5, 109.0, 104.3, 108.0, 6000),  # 39 — closes over the 104.2 highs
    ]

    def test_a_seeded_smc_setup_fires_on_the_sequence_it_now_describes(self):
        """A setup nobody has shown can fire is a setup that cannot fire, and
        two new legs joined the denominator here."""
        from signals.opportunity_scanner import scan_setup
        setup = self._armed_smc_setup()
        inst = _instrument("SEQFIRE", asset_class="stock")
        stamps = _seed_bars_from(inst, _sine_bars(36) + self._CHOCH_SEQUENCE)
        res = scan_setup(setup, inst, now=_now_after(stamps), as_of=True,
                         emit=False)
        legs = {c["kind"]: c for c in res["conditions"]}
        self.assertTrue(legs["event_sequence"]["matched"],
                        legs["event_sequence"]["details"])
        self.assertTrue(legs["market_structure_break"]["matched"],
                        legs["market_structure_break"]["details"])
        self.assertTrue(res["matched"], msg=f"score={res.get('score')}")
        self.assertGreater(res["score"], 0.9)

    def test_the_same_setup_refuses_the_range_it_used_to_buy(self):
        """The behaviour change, stated as a market. A sweep of the lows inside
        an intact range — no downside break before it, no upside break after —
        is what the bag-of-legs form scored, and it is a reclaim inside a range
        rather than a reversal of anything."""
        from signals.opportunity_scanner import scan_setup
        setup = self._armed_smc_setup()
        inst = _instrument("RANGEONLY", asset_class="stock")
        stamps = _seed_bars_from(inst, _sine_bars(36) + [
            _SWEEP_BAR,
            (100.0, 101.5, 99.5, 101.0, 2000),
            (101.0, 102.5, 100.5, 102.0, 4000),
            (102.0, 103.5, 101.5, 103.0, 6000),   # never clears the 104.2 highs
        ])
        res = scan_setup(setup, inst, now=_now_after(stamps), as_of=True,
                         emit=False)
        self.assertFalse(res["matched"], msg=f"score={res.get('score')}")
