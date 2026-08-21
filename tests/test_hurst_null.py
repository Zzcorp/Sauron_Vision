"""Hurst has to read 0.5 on a coin flip, or every threshold above it is noise.

The operator's briefing spent days building strategy on this number —
"seven of eight probes read Hurst above 0.55", "FX clustered 0.62-0.65",
"HGUSD at 0.652, decisively trending", "suspend every fade rule until
median Hurst breaks 0.55".

None of it measured the market. The estimator ran uncorrected rescaled
range over lags 2..20, and short-lag R/S grows faster than sqrt(n) even on
pure noise. Measured over 400 synthetic random walks of 150 bars, the old
estimator had a median of 0.653 and read >= 0.55 — this platform's
"trending" threshold — ONE HUNDRED PERCENT of the time. HGUSD's 0.652 sat
one thousandth BELOW the random-walk median.

So the fix is not a threshold, it is the null: R/S is divided by the
expected R/S of an independent series of the same length before the
regression, which recentres a coin flip on 0.5 where every caller already
assumed it was.

Run with:  python manage.py test tests.test_hurst_null
"""
import random
import statistics

from django.test import SimpleTestCase


def _walk(n, seed, drift=0.0, revert=0.0, sigma=0.01):
    rnd = random.Random(seed)
    price, out, prev = 100.0, [100.0], 0.0
    for _ in range(n - 1):
        step = drift + rnd.gauss(0, sigma) - revert * prev
        prev = step
        price *= (1 + step)
        out.append(price)
    return out


def _median_h(gen, runs=300, max_lag=20):
    from signals.quant_primitives import hurst_exponent
    vals = [hurst_exponent(gen(s), max_lag=max_lag) for s in range(runs)]
    vals = [v for v in vals if v is not None]
    assert vals, "the estimator returned nothing for every run"
    return statistics.median(vals), vals


class TheNullIsAHalfTests(SimpleTestCase):
    """The property the whole module rests on."""

    def test_a_pure_random_walk_reads_one_half(self):
        med, _ = _median_h(lambda s: _walk(150, s))
        self.assertAlmostEqual(med, 0.5, delta=0.05,
                               msg=f"random walk reads {med:.3f}, not ~0.5")

    def test_it_holds_at_a_longer_history_too(self):
        med, _ = _median_h(lambda s: _walk(300, s))
        self.assertAlmostEqual(med, 0.5, delta=0.05)

    def test_noise_is_almost_never_called_trending(self):
        """The exact regression: the old estimator called it trending 100%
        of the time, which is what made "seven of eight probes above 0.55"
        a statement about the estimator rather than about the market."""
        _, vals = _median_h(lambda s: _walk(150, s))
        share = sum(1 for v in vals if v >= 0.55) / len(vals)
        self.assertLess(share, 0.25,
                        f"{share:.0%} of coin flips read as trending")

    def test_a_coin_flip_labels_as_random(self):
        from signals.quant_primitives import hurst_regime_label
        med, _ = _median_h(lambda s: _walk(150, s))
        self.assertEqual(hurst_regime_label(med), "random")


class ItStillDetectsWhatItIsForTests(SimpleTestCase):
    def test_a_mean_reverting_series_reads_below_the_null(self):
        med, _ = _median_h(lambda s: _walk(150, s, revert=0.7))
        self.assertLess(med, 0.45, f"mean reversion reads {med:.3f}")

    def test_it_is_labelled_mean_reverting(self):
        from signals.quant_primitives import hurst_regime_label
        med, _ = _median_h(lambda s: _walk(150, s, revert=0.7))
        self.assertEqual(hurst_regime_label(med), "mean_reverting")

    def test_drift_alone_is_NOT_persistence(self):
        """Hurst measures whether INCREMENTS persist, not direction. A
        random walk with drift has independent increments and must read
        0.5 — which is why "the tape is trending" was never a question
        this number could answer, corrected or not."""
        med, _ = _median_h(lambda s: _walk(150, s, drift=0.004))
        self.assertAlmostEqual(med, 0.5, delta=0.06)


class TheNullTableTests(SimpleTestCase):
    def test_every_lag_the_estimator_uses_is_measured(self):
        """max_lag defaults to 20 and the loop runs lags 2..max_lag, so a
        gap in the table would silently fall back to the asymptotic form
        exactly where it is least accurate."""
        from signals.quant_primitives import EXPECTED_RS
        for lag in range(2, 21):
            self.assertIn(lag, EXPECTED_RS, f"lag {lag} is not measured")

    def test_it_is_monotonic(self):
        """R/S grows with the window. A dip would be a transcription slip."""
        from signals.quant_primitives import EXPECTED_RS
        lags = sorted(EXPECTED_RS)
        for a, b in zip(lags, lags[1:]):
            self.assertLess(EXPECTED_RS[a], EXPECTED_RS[b], f"{a} -> {b}")

    def test_beyond_the_table_it_degrades_to_the_asymptotic_form(self):
        from signals.quant_primitives import _expected_rs
        self.assertIsNotNone(_expected_rs(500))
        self.assertGreater(_expected_rs(500), _expected_rs(64))

    def test_below_two_there_is_no_range_to_expect(self):
        from signals.quant_primitives import _expected_rs
        self.assertIsNone(_expected_rs(1))


class ItStillRefusesWhatItCannotMeasureTests(SimpleTestCase):
    def test_too_short_a_series_is_none_and_not_a_guess(self):
        from signals.quant_primitives import hurst_exponent
        self.assertIsNone(hurst_exponent([100.0] * 10, max_lag=20))

    def test_a_flat_series_does_not_crash(self):
        from signals.quant_primitives import hurst_exponent
        self.assertIsNone(hurst_exponent([100.0] * 200, max_lag=20))

    def test_unknown_stays_unknown(self):
        from signals.quant_primitives import hurst_regime_label
        self.assertEqual(hurst_regime_label(None), "unknown")
