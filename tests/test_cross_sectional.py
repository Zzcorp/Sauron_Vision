"""Cross-sectional ranking — the first strategy family on this platform that
asks a question about a FIELD instead of about one chart.

What is being defended here
---------------------------

Every evaluator before this one is per-instrument and absolute: is IT above ITS
moving average, is ITS realized vol above 2%. A rank is not that shape. "Top
decile of its asset class" is a statement about an instrument's position among
others, so the evaluator contract had to widen — and every kind that came
before had to keep working untouched while it did.

Five things can go wrong with a rank, and each has tests below.

  1. The contract widens badly — a **kwargs sink, a shim, a default field
     constructed for evaluators that ignore it. The opt-in is by parameter
     name, resolved once at registration, so a kind that does not declare
     `field` is still called with exactly three arguments.

  2. The field lies about what it measured. An instrument with no window is
     NOT MEASURED and leaves the field; zero-filling it would drop it into the
     middle of a momentum table and at the calm end of a volatility one, and
     would keep the field's SIZE up — which is the number the thin-field
     refusal is watching. A member whose feed simply STOPPED lies in a subtler
     way: it has a full window, and the window ends weeks before everybody
     else's, so ranking it is a comparison between two different days.

  3. The field is thin and the rank pretends anyway. A "top decile" of four
     instruments is not a decile: the fraction rounds up to one name and a cut
     meant to exclude nine tenths excludes three symbols. The setup must
     refuse, and a setup must not be able to talk the floor down.

  4. The rank reads past `now`. A per-instrument lookahead bug corrupts one
     score; a field-wide one corrupts an ORDERING, so every instrument the
     winner was picked over is wrong too and the flag still looks well-formed.

  5. The refusal is scored. A rank that declined to answer and a rank that
     answered "no" are not the same number, and `scan_setup` averages both.
     Counted as a measured zero, a refusal takes its `weight` into the
     denominator and halves the evidence of every leg that did measure.

Plus the sector-rotation model, which is where the same measurement lives on
the dashboard side and which carried five defects of its own: an unbounded
upper bound on every query, a momentum comparison between windows of different
lengths, a leaders/laggards split that named the same sector as both, a pace
divided by calendar days while the return spanned trading bars, and two means
taken over two different sets of members.

Run with:  python manage.py test tests.test_cross_sectional
"""
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import TestCase
from django.utils import timezone


# ── Fixtures ───────────────────────────────────────────────────────────────

def _instrument(symbol, asset_class="stock", sector=""):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol,
        defaults={"name": symbol, "asset_class": asset_class, "sector": sector},
    )
    return inst


def _seed_daily(instrument, closes, end=None):
    """One daily bar per calendar day, oldest first, the LAST one landing on
    `end` so a scan pinned at `end` sees the whole series."""
    from market_data.models import PriceData
    end = end or timezone.now()
    PriceData.objects.bulk_create([
        PriceData(
            instrument=instrument, timeframe="1d",
            timestamp=end - timedelta(days=len(closes) - 1 - i),
            open=Decimal(str(round(c, 8))), high=Decimal(str(round(c, 8))),
            low=Decimal(str(round(c, 8))), close=Decimal(str(round(c, 8))),
            volume=1000, source="test",
        )
        for i, c in enumerate(closes)
    ])


def _seed_offsets(instrument, closes, offsets, now):
    """Bars at explicit day-offsets before `now`, oldest first.

    `_seed_daily` puts one bar on every calendar day, which is exactly what
    hides a bars-per-calendar-day bug: with that fixture the two counts are the
    same number. This one lets a window be sparse in one stretch and dense in
    another, which is what a real five-day-a-week tape looks like next to a
    thirty-day window.
    """
    from market_data.models import PriceData
    PriceData.objects.bulk_create([
        PriceData(
            instrument=instrument, timeframe="1d",
            timestamp=now - timedelta(days=offset),
            open=Decimal(str(round(c, 8))), high=Decimal(str(round(c, 8))),
            low=Decimal(str(round(c, 8))), close=Decimal(str(round(c, 8))),
            volume=1000, source="test",
        )
        for c, offset in zip(closes, offsets)
    ])


def _ramp(start, total_return, bars):
    """`bars + 1` closes walking from `start` to `start * (1 + total_return)`.

    Deliberately linear rather than compounding: a series that compounds at a
    fixed rate has exactly zero log-return variance, which `_rank_vol_pct`
    refuses as unmeasurable — correctly, and unhelpfully as a fixture.
    """
    end = start * (1.0 + total_return)
    return [start + (end - start) * i / bars for i in range(bars + 1)]


def _rank_setup(name, conditions, *, asset_classes=("stock",),
                min_match_score=0.5, direction="bullish"):
    from signals.models_opportunity import OpportunitySetup
    return OpportunitySetup.objects.create(
        name=name, description="", direction=direction,
        asset_classes=list(asset_classes), conditions=conditions,
        min_match_score=min_match_score, suggested_horizon_days=5,
        sizing={"stop_pct": 2.0, "target_rr": 2.0}, is_active=True,
    )


def _rank_condition(**params):
    return {"kind": "cross_sectional_rank", "params": params, "weight": 1.0}


class RankFixtureMixin:
    """A field of `n` stocks whose 20-bar returns are 1%, 2%, ... n%."""

    LOOKBACK = 20

    def _field_of(self, n, prefix="F", asset_class="stock", now=None,
                  first_pct=1.0):
        now = now or timezone.now()
        made = []
        for i in range(n):
            inst = _instrument(f"{prefix}{i:02d}", asset_class=asset_class)
            _seed_daily(inst, _ramp(100.0, (first_pct + i) / 100.0,
                                    self.LOOKBACK), end=now)
            made.append(inst)
        return made

    def _rank(self, instrument, *, now=None, field=None, **params):
        from signals.opportunity_scanner import _eval_cross_sectional_rank
        params.setdefault("lookback", self.LOOKBACK)
        return _eval_cross_sectional_rank(
            params, instrument, now or timezone.now(), field=field)


# ── 1. The widened contract ────────────────────────────────────────────────

class EvaluatorContractTests(TestCase):
    """The widening had to be invisible to every kind that predates it."""

    def _register_probe(self, kind, fn, **kwargs):
        """Register an evaluator for the duration of one test.

        Cleanup is not optional: the param-declaration guard in
        tests.test_seed_param_integrity walks EVALUATOR_REGISTRY, so a probe
        left behind would be audited as if it were a shipped kind.
        """
        from signals import opportunity_scanner as scanner
        scanner.register_kind(kind, fn, **kwargs)
        def _drop():
            for registry in (scanner.EVALUATOR_REGISTRY, scanner.PARAM_KEYS,
                             scanner.PARAM_CHOICES, scanner.ACCEPTS_AS_OF,
                             scanner.ACCEPTS_FIELD):
                registry.pop(kind, None)
        self.addCleanup(_drop)

    def test_every_kind_that_predates_the_field_still_declines_it(self):
        from signals.opportunity_scanner import ACCEPTS_FIELD, EVALUATOR_REGISTRY
        wants = sorted(kind for kind, wanted in ACCEPTS_FIELD.items()
                       if wanted and kind in EVALUATOR_REGISTRY)
        self.assertEqual(wants, ["cross_sectional_rank"])
        # Every registered kind has an answer, so the scan loop's `.get(kind)`
        # is never reading a hole it invented a default for. Asserted one way
        # only: other suites register probe evaluators and tear down the
        # registries they knew about, so a stale entry here is a leftover
        # rather than a defect — a stale key is never read, because the loop
        # only asks about kinds it just found in EVALUATOR_REGISTRY.
        self.assertLessEqual(set(EVALUATOR_REGISTRY), set(ACCEPTS_FIELD))

    def test_a_three_argument_evaluator_is_called_with_three_arguments(self):
        from signals.opportunity_scanner import scan_setup
        seen = []

        def _probe(params, instrument, now):
            seen.append((params, instrument, now))
            return {"matched": True, "score": 1.0, "details": {}}

        self._register_probe("probe_plain", _probe, params=())
        inst = _instrument("PROBE1")
        _seed_daily(inst, _ramp(100.0, 0.05, 20))
        scan_setup(_rank_setup("probe_plain_setup",
                               [{"kind": "probe_plain", "params": {},
                                 "weight": 1.0}]), inst)
        self.assertEqual(len(seen), 1)

    def test_an_evaluator_can_take_both_keywords(self):
        """`as_of` and `field` answer different questions and must compose."""
        from signals.opportunity_scanner import CrossSectionalField, scan_setup
        seen = {}

        def _probe(params, instrument, now, *, as_of=None, field=None):
            seen["as_of"] = as_of
            seen["field"] = field
            return {"matched": True, "score": 1.0, "details": {}}

        self._register_probe("probe_both", _probe, params=())
        inst = _instrument("PROBE2")
        _seed_daily(inst, _ramp(100.0, 0.05, 20))
        setup = _rank_setup("probe_both_setup",
                            [{"kind": "probe_both", "params": {}, "weight": 1.0}])
        scan_setup(setup, inst, now=timezone.now(), as_of=False)
        self.assertIs(seen["as_of"], False)
        self.assertIsInstance(seen["field"], CrossSectionalField)

    def test_a_setup_with_no_rank_condition_never_builds_a_field(self):
        """The field is built on demand, so the absolute kinds pay nothing for
        a capability they do not use."""
        from signals import opportunity_scanner as scanner
        inst = _instrument("NOFIELD")
        _seed_daily(inst, _ramp(100.0, 0.10, 30))
        with mock.patch.object(scanner, "_field_closes") as closes:
            scanner.scan_setup(
                _rank_setup("plain_setup",
                            [{"kind": "price_pattern",
                              "params": {"pattern": "above_ma", "ma_period": 5},
                              "weight": 1.0}]),
                inst)
        closes.assert_not_called()

    def test_the_rank_kind_declares_its_params_and_vocabularies(self):
        from signals.opportunity_scanner import (
            invalid_param_values, param_choices, param_keys, unknown_param_keys,
        )
        self.assertEqual(
            sorted(param_keys("cross_sectional_rank")),
            ["lookback", "metric", "min_field", "scope", "select_pct",
             "short_lookback", "side"])
        choices = param_choices("cross_sectional_rank")
        self.assertEqual(sorted(choices["side"]), ["bottom", "top"])
        self.assertEqual(sorted(choices["scope"]), ["asset_class", "universe"])
        params = {"metric": "momentum", "side": "top", "scope": "asset_class",
                  "lookback": 60, "select_pct": 0.1}
        self.assertEqual(unknown_param_keys("cross_sectional_rank", params), [])
        self.assertEqual(invalid_param_values("cross_sectional_rank", params), [])
        self.assertTrue(invalid_param_values(
            "cross_sectional_rank", {"metric": "relative_strength"}))

    def test_the_two_ends_of_a_rank_are_not_the_same_detector(self):
        """`condition_fingerprint` folds in the params an evaluator branches
        on, and a rank branches on all three. A top-decile and a bottom-decile
        setup are mirror images, and reporting them as one rule twice is how a
        long/short pair gets half of itself retired as a duplicate."""
        from signals.opportunity_scanner import condition_fingerprint
        top = condition_fingerprint(_rank_condition(
            metric="momentum", side="top", scope="asset_class"))
        bottom = condition_fingerprint(_rank_condition(
            metric="momentum", side="bottom", scope="asset_class"))
        self.assertNotEqual(top, bottom)
        self.assertIn("side=top", top)
        self.assertIn("metric=momentum", top)


# ── 2. The field measures honestly ─────────────────────────────────────────

class FieldMeasurementTests(RankFixtureMixin, TestCase):

    def test_the_field_reads_no_bar_past_the_pinned_instant(self):
        """The universe-wide form of the cardinal rule. The later bars would
        reverse this instrument's rank, which is the point: a field that reads
        one bar too far is wrong about every instrument it ordered."""
        from signals.opportunity_scanner import CrossSectionalField
        now = timezone.now()
        inst = _instrument("ASOF_RANK")
        # Flat to `now`, then a spike. A field pinned at `now` must see 0%.
        _seed_daily(inst, _ramp(100.0, 0.0, self.LOOKBACK) + [100.0, 180.0],
                    end=now + timedelta(days=2))
        values = CrossSectionalField([inst], now=now).values(
            "momentum", lookback=self.LOOKBACK)
        self.assertAlmostEqual(values[inst.id], 0.0, places=6)

    def test_an_instrument_without_a_full_window_leaves_the_field(self):
        """Absent, not zero. Zero would rank it mid-table on momentum and
        best-in-class on volatility, and would keep the field size up."""
        from signals.opportunity_scanner import CrossSectionalField
        now = timezone.now()
        full = _instrument("FULLWIN")
        short = _instrument("SHORTWIN")
        _seed_daily(full, _ramp(100.0, 0.10, self.LOOKBACK), end=now)
        _seed_daily(short, _ramp(100.0, 0.10, 3), end=now)
        values = CrossSectionalField([full, short], now=now).values(
            "momentum", lookback=self.LOOKBACK)
        self.assertIn(full.id, values)
        self.assertNotIn(short.id, values)

    def test_a_stale_series_is_not_ranked_against_a_current_one(self):
        """Sixty bars spread over two years are not comparable to sixty bars
        from the last three months, so the window has a lower bound too."""
        from signals.opportunity_scanner import CrossSectionalField
        now = timezone.now()
        stale = _instrument("STALE")
        _seed_daily(stale, _ramp(100.0, 0.30, self.LOOKBACK),
                    end=now - timedelta(days=400))
        values = CrossSectionalField([stale], now=now).values(
            "momentum", lookback=self.LOOKBACK)
        self.assertEqual(values, {})

    def test_a_member_whose_feed_stopped_leaves_the_field(self):
        """The stale case the lower bound cannot see. Twenty-one dense bars,
        every one of them inside the window's own `need * 2` reach — and all of
        them finished three weeks before `now`. Its return is not wrong, it is
        about a different day, and ranking it against instruments measured to
        `now` is ordering two dates against each other."""
        from signals.opportunity_scanner import CrossSectionalField
        now = timezone.now()
        live = _instrument("LIVEFEED")
        dead = _instrument("DEADFEED")
        _seed_daily(live, _ramp(100.0, 0.10, self.LOOKBACK), end=now)
        _seed_daily(dead, _ramp(100.0, 0.30, self.LOOKBACK),
                    end=now - timedelta(days=20))
        field = CrossSectionalField([live, dead], now=now)
        values = field.values("momentum", lookback=self.LOOKBACK)
        # Left in, DEADFEED's +30% would have outranked every live member.
        self.assertEqual(set(values), {live.id})
        self.assertIn(dead.id, field.stale(self.LOOKBACK))

    def test_a_long_weekend_does_not_evict_a_live_feed(self):
        """The cut has to survive a market being shut. A weekend flanked by
        holidays puts several calendar days between two consecutive bars, and a
        freshness rule tighter than that would empty the field every Monday."""
        from signals.opportunity_scanner import CrossSectionalField
        now = timezone.now()
        shut = _instrument("LONGWEEKEND")
        _seed_daily(shut, _ramp(100.0, 0.10, self.LOOKBACK),
                    end=now - timedelta(days=4))
        field = CrossSectionalField([shut], now=now)
        self.assertIn(shut.id, field.values("momentum", lookback=self.LOOKBACK))
        self.assertEqual(field.stale(self.LOOKBACK), {})

    def test_the_field_never_falls_back_to_the_live_quote(self):
        """A field where some members are marked at their last close and others
        at a live tick is not a cross-section at one instant."""
        from market_data.models import LiveQuote
        from signals.opportunity_scanner import CrossSectionalField
        quoted = _instrument("QUOTED")
        LiveQuote.objects.create(instrument=quoted, last=Decimal("42.0"),
                                 source="test")
        values = CrossSectionalField([quoted], now=timezone.now()).values(
            "momentum", lookback=self.LOOKBACK)
        self.assertEqual(values, {})

    def test_a_series_with_no_measurable_variance_leaves_the_field(self):
        """A fixed-rate compounding series has exactly zero log-return
        variance, and `pstdev` answers with ~1e-16 of float residue. Taken at
        face value it makes risk-adjusted momentum ~1e15 — top of every
        table — and makes a volatility rank read it as the calmest market."""
        from signals.opportunity_scanner import CrossSectionalField
        now = timezone.now()
        geometric = _instrument("GEOMETRIC")
        _seed_daily(geometric, [100.0 * (1.01 ** i)
                                for i in range(self.LOOKBACK + 1)], end=now)
        field = CrossSectionalField([geometric], now=now)
        self.assertEqual(field.values("volatility", lookback=self.LOOKBACK), {})
        self.assertEqual(
            field.values("risk_adjusted_momentum", lookback=self.LOOKBACK), {})
        # Its RETURN is still perfectly measurable — only the risk is not.
        self.assertIn(geometric.id,
                      field.values("momentum", lookback=self.LOOKBACK))

    def test_the_field_prices_the_universe_once_per_pass(self):
        """Two setups ranking the same window must be handed one ordering, and
        must not pay for it twice."""
        from signals import opportunity_scanner as scanner
        self._field_of(12)
        for name in ("rank_a", "rank_b"):
            _rank_setup(name, [_rank_condition(metric="momentum",
                                               lookback=self.LOOKBACK)])
        real = scanner._field_closes
        calls = []

        def _counting(*args, **kwargs):
            calls.append(args)
            return real(*args, **kwargs)

        with mock.patch.object(scanner, "_field_closes", _counting):
            scanner.scan_all_setups()
        self.assertEqual(len(calls), 1)

    def test_the_pass_hands_every_pair_the_same_field(self):
        from signals.opportunity_scanner import CrossSectionalField, scan_all_setups
        self._field_of(3)
        _rank_setup("one_field", [_rank_condition(metric="momentum")])
        with mock.patch("signals.opportunity_scanner.scan_setup") as scan:
            scan.return_value = {"matched": False}
            scan_all_setups()
        fields = {id(c.kwargs["field"]) for c in scan.call_args_list}
        self.assertEqual(len(fields), 1)
        self.assertIsInstance(scan.call_args_list[0].kwargs["field"],
                              CrossSectionalField)

    def test_the_pass_pins_the_field_to_the_now_it_replays(self):
        from signals.opportunity_scanner import scan_all_setups
        replay = timezone.now() - timedelta(days=10)
        with mock.patch("signals.opportunity_scanner.scan_setup") as scan:
            scan.return_value = {"matched": False}
            _instrument("PINNED")
            _rank_setup("pinned", [_rank_condition(metric="momentum")])
            scan_all_setups(now=replay)
        self.assertEqual(scan.call_args_list[0].kwargs["field"].now, replay)


# ── 3. The measurements themselves ─────────────────────────────────────────

class RankMetricTests(RankFixtureMixin, TestCase):

    def _values(self, instruments, metric, **kwargs):
        from signals.opportunity_scanner import CrossSectionalField
        now = kwargs.pop("now", None) or timezone.now()
        return CrossSectionalField(instruments, now=now).values(
            metric, lookback=self.LOOKBACK, **kwargs)

    def test_momentum_is_the_trailing_return(self):
        now = timezone.now()
        inst = _instrument("MOMX")
        _seed_daily(inst, _ramp(100.0, 0.25, self.LOOKBACK), end=now)
        values = self._values([inst], "momentum", now=now)
        self.assertAlmostEqual(values[inst.id], 0.25, places=6)

    def test_risk_adjusted_momentum_demotes_the_volatile_winner(self):
        """The name that moved furthest is not the name that moved furthest for
        its risk, and a raw-return decile is largely a high-beta decile."""
        now = timezone.now()
        wild = _instrument("WILD")
        steady = _instrument("STEADY")
        # +30% on a tape that whips ±8% a bar, vs +12% on one that ticks ±0.5%.
        # Both endpoints sit on the same phase of the alternation, so each
        # series lands on exactly the return it advertises.
        _seed_daily(wild, [100.0 * (1 + 0.30 * i / self.LOOKBACK)
                           * (1.08 if i % 2 else 0.92)
                           for i in range(self.LOOKBACK + 1)], end=now)
        _seed_daily(steady, [100.0 * (1 + 0.12 * i / self.LOOKBACK)
                             * (1.005 if i % 2 else 0.995)
                             for i in range(self.LOOKBACK + 1)], end=now)
        raw = self._values([wild, steady], "momentum", now=now)
        adjusted = self._values([wild, steady], "risk_adjusted_momentum", now=now)
        self.assertGreater(raw[wild.id], raw[steady.id])
        self.assertGreater(adjusted[steady.id], adjusted[wild.id])

    def test_a_steady_tape_accelerates_by_exactly_nothing(self):
        """The baseline the metric is measured against, and the reason it is
        built on log returns: a tape advancing the same percentage every bar
        has one pace, and dividing its compounding SIMPLE return by the bar
        count would still have scored it as decelerating."""
        now = timezone.now()
        steady = _instrument("STEADYPACE")
        _seed_daily(steady, [100.0 * (1.004 ** i)
                             for i in range(self.LOOKBACK + 1)], end=now)
        values = self._values([steady], "acceleration", now=now,
                              short_lookback=5)
        self.assertAlmostEqual(values[steady.id], 0.0, places=6)

    def test_a_recent_burst_reads_as_acceleration_despite_a_smaller_total(self):
        now = timezone.now()
        burst = _instrument("BURST")
        # Fifteen flat-ish bars, then five that run: the five-bar TOTAL (+6%)
        # is far below the twenty-bar total (+7%), which is exactly the shape
        # the old total-vs-total comparison called `decelerating`.
        closes = _ramp(100.0, 0.01, 15) + _ramp(101.0, 0.0594, 5)[1:]
        _seed_daily(burst, closes, end=now)
        values = self._values([burst], "acceleration", now=now, short_lookback=5)
        self.assertGreater(values[burst.id], 0.0)

    def test_acceleration_refuses_a_short_window_it_cannot_fit(self):
        now = timezone.now()
        inst = _instrument("ACCELBAD")
        _seed_daily(inst, _ramp(100.0, 0.10, self.LOOKBACK), end=now)
        for short in (1, self.LOOKBACK + 5):
            with self.subTest(short_lookback=short):
                self.assertEqual(
                    self._values([inst], "acceleration", now=now,
                                 short_lookback=short), {})


# ── 4. A thin field is refused, not fudged ─────────────────────────────────

class ThinFieldTests(RankFixtureMixin, TestCase):

    def test_a_top_decile_of_four_is_refused(self):
        """Four names cannot carry a decile. `int(4 * 0.10)` is 0 and rounding
        it up would name the single best instrument while still calling itself
        a tenth of the field."""
        field = self._field_of(4)
        res = self._rank(field[-1], metric="momentum", side="top",
                         select_pct=0.10)
        self.assertFalse(res["matched"])
        self.assertEqual(res["score"], 0.0)
        self.assertEqual(res["details"]["field_size"], 4)
        self.assertIn("floor", res["details"]["reason"])

    def test_a_setup_cannot_talk_the_floor_down(self):
        """A defence a caller can dial down is not a defence."""
        field = self._field_of(4)
        res = self._rank(field[-1], metric="momentum", select_pct=0.25,
                         min_field=2)
        self.assertFalse(res["matched"])
        self.assertEqual(res["details"]["min_field"], 10)

    def test_a_setup_can_raise_the_floor(self):
        field = self._field_of(20)
        res = self._rank(field[-1], metric="momentum", select_pct=0.10,
                         min_field=50)
        self.assertFalse(res["matched"])
        self.assertIn("50-instrument floor", res["details"]["reason"])

    def test_a_fraction_that_names_nobody_is_refused(self):
        """Twelve instruments and a 5% slice: the cut selects nobody, and the
        alternative — rounding up to one — is a twelfth dressed as a twentieth."""
        field = self._field_of(12)
        res = self._rank(field[-1], metric="momentum", select_pct=0.05)
        self.assertFalse(res["matched"])
        self.assertEqual(res["details"]["selected"], 0)
        self.assertIn("does not name a whole instrument",
                      res["details"]["reason"])

    def test_a_majority_is_not_a_selection(self):
        field = self._field_of(20)
        res = self._rank(field[-1], metric="momentum", select_pct=0.6)
        self.assertFalse(res["matched"])
        self.assertIn("select_pct", res["details"]["reason"])

    def test_an_unmeasured_instrument_is_unranked_and_not_last(self):
        """Its feed went quiet; the market did not tell us it is the worst."""
        now = timezone.now()
        self._field_of(12, now=now)
        quiet = _instrument("QUIET")
        _seed_daily(quiet, _ramp(100.0, 0.05, 3), end=now)
        res = self._rank(quiet, metric="momentum", now=now)
        self.assertFalse(res["matched"])
        self.assertNotIn("rank", res["details"])
        self.assertEqual(res["details"]["reason"], "no full window for this instrument")
        # And it did not pad the field it failed to join.
        self.assertEqual(res["details"]["field_size"], 12)

    def test_a_stalled_feed_is_told_apart_from_a_short_history(self):
        """Both are unranked and neither is last, but they are different
        problems for whoever reads the flag: one is an ingest to restart, the
        other is a symbol that has not traded long enough to rank yet."""
        now = timezone.now()
        self._field_of(12, now=now)
        stalled = _instrument("STALLED")
        _seed_daily(stalled, _ramp(100.0, 0.40, self.LOOKBACK),
                    end=now - timedelta(days=15))
        res = self._rank(stalled, metric="momentum", now=now)
        self.assertFalse(res["matched"])
        self.assertIs(res["measured"], False)
        self.assertNotIn("rank", res["details"])
        self.assertIn("staleness cut", res["details"]["reason"])
        # And it did not pad the field it failed to join.
        self.assertEqual(res["details"]["field_size"], 12)

    def test_an_instrument_outside_the_field_says_so(self):
        from signals.opportunity_scanner import CrossSectionalField
        now = timezone.now()
        field = self._field_of(12, now=now)
        outsider = _instrument("OUTSIDER")
        _seed_daily(outsider, _ramp(100.0, 0.99, self.LOOKBACK), end=now)
        res = self._rank(outsider, metric="momentum", now=now,
                         field=CrossSectionalField(field, now=now))
        self.assertFalse(res["matched"])
        self.assertEqual(res["details"]["reason"], "outside the ranked field")


# ── 4b. A refusal is not a measured zero ───────────────────────────────────

class UnmeasuredLegTests(RankFixtureMixin, TestCase):
    """`scan_setup` averages `score * weight` over `weight`. A leg that never
    measured anything belongs in neither half of that fraction."""

    PRICE_LEG = {"kind": "price_pattern",
                 "params": {"pattern": "above_ma", "ma_period": 5},
                 "weight": 1.0}

    def _two_leg(self, name, instrument, now, **rank_params):
        """A rank leg beside a moving-average leg, scored and never emitted."""
        from signals.opportunity_scanner import scan_setup
        rank_params.setdefault("lookback", self.LOOKBACK)
        setup = _rank_setup(name,
                            [_rank_condition(**rank_params), dict(self.PRICE_LEG)],
                            min_match_score=0.9)
        res = scan_setup(setup, instrument, now=now, as_of=False, emit=False)
        legs = {c["kind"]: c for c in res["conditions"]}
        return res, legs["cross_sectional_rank"], legs["price_pattern"]

    def test_a_refused_rank_does_not_dilute_the_leg_that_measured(self):
        """Six names are under the ten-instrument floor, so the rank declines
        to answer. Scored as a zero it took its weight into the denominator
        with it and halved the moving-average leg's evidence — a refusal to
        rank silently voting against every other condition in the setup."""
        now = timezone.now()
        field = self._field_of(6, now=now)
        res, rank_leg, price_leg = self._two_leg(
            "rank_refused_plus_price", field[-1], now,
            metric="momentum", select_pct=0.10)
        self.assertIs(rank_leg["measured"], False)
        self.assertIn("floor", rank_leg["details"]["reason"])
        self.assertGreater(price_leg["score"], 0.0)
        self.assertEqual(res["score"], round(price_leg["score"], 4))

    def test_a_ranked_miss_still_weighs_as_the_measured_zero_it_is(self):
        """The mirror of the fix, and the half that must not move. An
        instrument the rank actually looked at and placed below the cut is
        evidence against the setup, so its zero belongs in the average."""
        now = timezone.now()
        field = self._field_of(20, now=now)
        res, rank_leg, price_leg = self._two_leg(
            "rank_missed_plus_price", field[0], now,
            metric="momentum", side="top", select_pct=0.10)
        self.assertIs(rank_leg["measured"], True)
        self.assertEqual(rank_leg["score"], 0.0)
        self.assertEqual(res["score"], round(price_leg["score"] / 2, 4))

    def test_a_setup_whose_only_leg_refused_cannot_match_at_any_threshold(self):
        """Nothing measured is not a composite of zero. A setup whose bar sits
        at zero would otherwise read the hole as a bar it cleared and publish a
        flag built on no evidence at all."""
        from signals.opportunity_scanner import scan_setup
        now = timezone.now()
        field = self._field_of(6, now=now)
        setup = _rank_setup("rank_only_thin",
                            [_rank_condition(metric="momentum",
                                             lookback=self.LOOKBACK)],
                            min_match_score=0.0)
        res = scan_setup(setup, field[-1], now=now, as_of=False, emit=False)
        self.assertFalse(res["matched"])

    def test_a_gate_that_could_not_measure_still_fails_closed(self):
        """The refusal must not become a way past a gate. A universe check that
        declined to answer says nothing about whether the setup applies here,
        and the fail-towards-not-trading answer is that it does not."""
        from signals.opportunity_scanner import scan_setup
        now = timezone.now()
        field = self._field_of(6, now=now)
        setup = _rank_setup(
            "rank_gate_thin",
            [dict(_rank_condition(metric="momentum", select_pct=0.10,
                                  lookback=self.LOOKBACK), gate=True),
             dict(self.PRICE_LEG)],
            min_match_score=0.0)
        res = scan_setup(setup, field[-1], now=now, as_of=False, emit=False)
        self.assertEqual(res.get("reason"), "gate_failed")


# ── 5. The ranking itself ──────────────────────────────────────────────────

class RankSelectionTests(RankFixtureMixin, TestCase):

    def test_the_top_decile_takes_the_top_tenth_and_stops(self):
        now = timezone.now()
        field = self._field_of(20, now=now)  # returns 1%..20%
        best, second, third = field[19], field[18], field[17]
        for inst, expected_rank, expected in ((best, 1, True),
                                              (second, 2, True),
                                              (third, 3, False)):
            with self.subTest(symbol=inst.symbol):
                res = self._rank(inst, metric="momentum", side="top",
                                 select_pct=0.10, now=now)
                self.assertEqual(res["details"]["selected"], 2)
                self.assertEqual(res["details"]["rank"], expected_rank)
                self.assertEqual(res["matched"], expected)

    def test_the_bottom_side_selects_the_weakest(self):
        now = timezone.now()
        field = self._field_of(20, now=now)
        worst, best = field[0], field[19]
        self.assertTrue(self._rank(worst, metric="momentum", side="bottom",
                                   select_pct=0.10, now=now)["matched"])
        self.assertFalse(self._rank(best, metric="momentum", side="bottom",
                                    select_pct=0.10, now=now)["matched"])

    def test_tied_instruments_share_a_rank(self):
        """Whichever of two identical numbers clears the cut would otherwise be
        decided by row order, which is not a fact about the market."""
        now = timezone.now()
        field = self._field_of(20, now=now)
        # Give the third-best the same return as the second-best: both now sit
        # at rank 2 in a two-name slice, and both are taken.
        from market_data.models import PriceData
        PriceData.objects.filter(instrument=field[17]).delete()
        _seed_daily(field[17], _ramp(100.0, 0.19, self.LOOKBACK), end=now)
        ranks = {}
        for inst in (field[19], field[18], field[17]):
            res = self._rank(inst, metric="momentum", side="top",
                             select_pct=0.10, now=now)
            ranks[inst.symbol] = (res["details"]["rank"], res["matched"])
        self.assertEqual(ranks[field[18].symbol], (2, True))
        self.assertEqual(ranks[field[17].symbol], (2, True))
        self.assertEqual(ranks[field[19].symbol], (1, True))

    def test_the_score_is_the_fraction_of_the_field_beaten(self):
        """"In the top decile" is a claim about 90% of the field, and that is
        the number the composite should weight."""
        now = timezone.now()
        field = self._field_of(20, now=now)
        best = self._rank(field[19], metric="momentum", select_pct=0.10, now=now)
        second = self._rank(field[18], metric="momentum", select_pct=0.10, now=now)
        self.assertEqual(best["score"], 1.0)
        self.assertAlmostEqual(second["score"], 18 / 19, places=4)

    def test_an_unmatched_rank_scores_zero(self):
        """`scan_setup` weights `score` whether or not `matched` is set, so a
        near-miss that kept its percentile would push composites over the line
        on a condition that did not fire."""
        now = timezone.now()
        field = self._field_of(20, now=now)
        res = self._rank(field[17], metric="momentum", select_pct=0.10, now=now)
        self.assertFalse(res["matched"])
        self.assertEqual(res["score"], 0.0)


# ── 6. Which field, and refusing to guess ──────────────────────────────────

class RankScopeTests(RankFixtureMixin, TestCase):

    def _mixed(self, now):
        stocks = self._field_of(12, prefix="S", asset_class="stock", now=now)
        # Crypto returns of 101%..112% — every one of them beats every stock.
        cryptos = self._field_of(12, prefix="C", asset_class="crypto", now=now,
                                 first_pct=101.0)
        return stocks, cryptos

    def test_asset_class_scope_ranks_only_against_the_same_class(self):
        """A mixed field does not rank momentum, it ranks asset class: a
        sixty-bar return puts crypto above every equity and every equity above
        every major pair, so a universe decile is a list of whatever moves
        most, restated daily."""
        now = timezone.now()
        stocks, _ = self._mixed(now)
        res = self._rank(stocks[11], metric="momentum", scope="asset_class",
                         select_pct=0.10, now=now)
        self.assertTrue(res["matched"])
        self.assertEqual(res["details"]["field_size"], 12)
        self.assertEqual(res["details"]["rank"], 1)

    def test_universe_scope_ranks_against_everything(self):
        now = timezone.now()
        stocks, cryptos = self._mixed(now)
        res = self._rank(stocks[11], metric="momentum", scope="universe",
                         select_pct=0.10, now=now)
        self.assertFalse(res["matched"])
        self.assertEqual(res["details"]["field_size"], 24)
        self.assertEqual(res["details"]["rank"], 13)
        self.assertTrue(self._rank(cryptos[11], metric="momentum",
                                   scope="universe", select_pct=0.10,
                                   now=now)["matched"])

    def test_an_unrecognised_value_is_refused_and_not_defaulted(self):
        """On a two-branch evaluator a typo does not go quiet — it selects the
        other branch. A typo'd `side` here would rank the weakest names as the
        strongest and publish a flag that looks entirely well-formed."""
        now = timezone.now()
        field = self._field_of(12, now=now)
        for params, expected in (
            ({"side": "hightest"}, "unknown side"),
            ({"scope": "sector"}, "unknown scope"),
            ({"metric": "relative_strength"}, "unknown metric"),
        ):
            with self.subTest(**params):
                res = self._rank(field[-1], now=now, **params)
                self.assertFalse(res["matched"])
                self.assertIn(expected, res["details"]["reason"])

    def test_a_non_numeric_threshold_is_reported_not_raised(self):
        now = timezone.now()
        field = self._field_of(12, now=now)
        res = self._rank(field[-1], metric="momentum", select_pct="a lot",
                         now=now)
        self.assertFalse(res["matched"])
        self.assertIn("non-numeric", res["details"]["reason"])


# ── 7. End to end: a rank becomes a Signal ─────────────────────────────────

class RankingSetupEndToEndTests(RankFixtureMixin, TestCase):
    """The whole point of plan item 3.2 — the platform could rank nothing, and
    `sector_rotation` computed a ranking that reached a read-only view and
    never a Signal."""

    def test_a_ranking_setup_flags_only_the_top_slice(self):
        from signals.models import OpportunityFlag, Signal
        from signals.opportunity_scanner import scan_all_setups
        field = self._field_of(20)
        _rank_setup("rank_top_decile",
                    [_rank_condition(metric="momentum", side="top",
                                     select_pct=0.10, lookback=self.LOOKBACK)])
        result = scan_all_setups()
        self.assertEqual(result["matches"], 2)
        flagged = set(OpportunityFlag.objects.values_list(
            "instrument__symbol", flat=True))
        self.assertEqual(flagged, {field[19].symbol, field[18].symbol})
        # And it flows through the Signal lane like any other setup's match,
        # tagged with the setup name the whole Phase-1-9 chain keys on.
        self.assertEqual(
            Signal.objects.filter(rule_name="rank_top_decile").count(), 2)

    def test_a_thin_universe_publishes_nothing_at_all(self):
        """Refuse rather than pretend, all the way out to the flag table."""
        from signals.models import OpportunityFlag
        from signals.opportunity_scanner import scan_all_setups
        self._field_of(6)
        _rank_setup("rank_thin",
                    [_rank_condition(metric="momentum", select_pct=0.10,
                                     lookback=self.LOOKBACK)])
        result = scan_all_setups()
        self.assertEqual(result["matches"], 0)
        # Scored, not gated or skipped — the pair was evaluated and the
        # condition declined to answer.
        self.assertEqual(result["scored"], 6)
        self.assertFalse(OpportunityFlag.objects.exists())

    def test_a_rank_can_gate_a_setup_instead_of_scoring_it(self):
        """`gate: true` works on the new kind for free, which is the test that
        the widening did not carve out a special path for it."""
        from signals.opportunity_scanner import scan_setup
        now = timezone.now()
        field = self._field_of(20, now=now)
        setup = _rank_setup(
            "rank_gated",
            [dict(_rank_condition(metric="momentum", side="top",
                                  select_pct=0.10, lookback=self.LOOKBACK),
                  gate=True),
             {"kind": "price_pattern",
              "params": {"pattern": "above_ma", "ma_period": 5},
              "weight": 1.0}],
            min_match_score=0.05)
        blocked = scan_setup(setup, field[0], now=now, as_of=False, emit=False)
        self.assertEqual(blocked.get("reason"), "gate_failed")
        allowed = scan_setup(setup, field[19], now=now, as_of=False, emit=False)
        self.assertTrue(allowed.get("matched"), msg=allowed)
        self.assertEqual(len(allowed["conditions"]), 2)
        # A gate contributes no score and no denominator, so the composite is
        # the moving-average leg alone — not an average of it with a rank.
        price_leg = next(c for c in allowed["conditions"]
                         if c["kind"] == "price_pattern")
        self.assertEqual(allowed["score"], round(price_leg["score"], 4))


# ── 8. Sector rotation: the dashboard side of the same measurement ─────────

class SectorRotationTests(TestCase):
    """Untested before this file, and carrying five defects: unbounded
    queries, a momentum comparison between windows of different lengths,
    leaders/laggards slices that could name the same sector twice, a pace
    divided by calendar days while the return spanned trading bars, and two
    means taken over two different sets of members."""

    def _sector(self, sector, symbols, total_return, now, *, lookback=30):
        made = []
        for symbol in symbols:
            inst = _instrument(symbol, asset_class="stock", sector=sector)
            _seed_daily(inst, _ramp(100.0, total_return, lookback), end=now)
            made.append(inst)
        return made

    def _paced(self, symbol, sector, long_return, short_return, now,
               *, long_days=30, short_days=5):
        """A member whose 30-day return is `long_return` and whose LAST five
        days are `short_return` of it."""
        inst = _instrument(symbol, asset_class="stock", sector=sector)
        end_price = 100.0 * (1.0 + long_return)
        short_start = end_price / (1.0 + short_return)
        head = [100.0 + (short_start - 100.0) * i / (long_days - short_days)
                for i in range(long_days - short_days + 1)]
        tail = [short_start + (end_price - short_start) * i / short_days
                for i in range(1, short_days + 1)]
        _seed_daily(inst, head + tail, end=now)
        return inst

    def test_an_unlabelled_universe_is_a_configuration_fact_not_a_flat_market(self):
        from signals.sector_rotation import SectorRotationModel
        _instrument("NOSECTOR", asset_class="stock")
        result = SectorRotationModel().analyze(now=timezone.now())
        self.assertEqual(result["error"], "no_sector_data")
        self.assertIn("sector label", result["detail"])

    def test_returns_stop_at_the_pinned_instant(self):
        from signals.sector_rotation import SectorRotationModel
        now = timezone.now()
        inst = _instrument("PINNEDSEC", asset_class="stock", sector="Energy")
        _seed_daily(inst, _ramp(100.0, 0.05, 30) + [200.0],
                    end=now + timedelta(days=1))
        result = SectorRotationModel().analyze(now=now)
        self.assertAlmostEqual(result["sector_performance"]["Energy"], 0.05,
                               places=3)

    def test_a_faster_recent_pace_is_no_longer_called_decelerating(self):
        """+9% over thirty bars with +2% of it in the last five is 0.40% a bar
        recently against 0.29% a bar overall. Comparing the TOTALS said the
        opposite, and it said it about every sector in an uptrend."""
        from signals.sector_rotation import SectorRotationModel
        now = timezone.now()
        self._paced("PACE1", "Technology", 0.09, 0.02, now)
        result = SectorRotationModel().analyze(lookback_days=30, now=now)
        self.assertEqual(result["momentum"]["Technology"], "accelerating")

    def test_a_genuinely_slowing_sector_still_reads_as_slowing(self):
        from signals.sector_rotation import SectorRotationModel
        now = timezone.now()
        # +9% over thirty bars, only +0.2% of it in the last five: 0.04% a bar
        # against 0.29% a bar.
        self._paced("PACE2", "Utilities", 0.09, 0.002, now)
        result = SectorRotationModel().analyze(lookback_days=30, now=now)
        self.assertEqual(result["momentum"]["Utilities"], "decelerating")

    def test_the_reversal_labels_are_reachable_at_all(self):
        """Tested after the accelerating/decelerating pair, `short > 0 > long`
        always matched `short > long and short > 0` first — so `reversing_up`
        and `reversing_down` were labels the function could never return."""
        from signals.sector_rotation import SectorRotationModel
        now = timezone.now()
        self._paced("REV1", "Materials", -0.05, 0.02, now)
        self._paced("REV2", "Real Estate", 0.05, -0.02, now)
        momentum = SectorRotationModel().analyze(
            lookback_days=30, now=now)["momentum"]
        self.assertEqual(momentum["Materials"], "reversing_up")
        self.assertEqual(momentum["Real Estate"], "reversing_down")

    def test_a_pace_is_counted_in_bars_not_in_calendar_days(self):
        """The two windows do not hold the same number of bars per calendar
        day. This member's bars are every other day for the first stretch and
        daily for the last five, so the thirty-day window carries seventeen
        steps and the five-day window carries five.

        Its per-BAR pace genuinely slows — 0.26%/bar over the whole window
        against 0.20%/bar in the recent one. Divide each total by its window's
        calendar length instead and the sparse half drags the long figure down
        to 0.15%/day against 0.20%/day, and a sector that is losing pace reads
        as `accelerating`. Dividing by the window was supposed to remove the
        window-length dependence; by calendar days it just relabels it.
        """
        from signals.sector_rotation import SectorRotationModel
        now = timezone.now()
        long_total, short_total = 0.045, 0.010
        early = (1.0 + long_total) / (1.0 + short_total)
        closes = [100.0 * early ** (i / 12) for i in range(13)]
        closes += [closes[12] * (1.0 + short_total) ** (i / 5)
                   for i in range(1, 6)]
        offsets = list(range(29, 6, -2)) + [5, 4, 3, 2, 1, 0]
        inst = _instrument("UNEVEN", asset_class="stock",
                           sector="Financial Services")
        _seed_offsets(inst, closes, offsets, now)
        result = SectorRotationModel().analyze(lookback_days=30, now=now)
        self.assertAlmostEqual(
            result["sector_performance"]["Financial Services"], long_total,
            places=4)
        self.assertEqual(result["momentum"]["Financial Services"],
                         "decelerating")

    def test_the_two_paces_describe_the_same_members(self):
        """`_sector_stats` averages whichever members it could measure, so a
        member with thirty days of history and nothing in the last five sits in
        one window's mean and not the other's. Compared, those two means are
        two differently composed sectors wearing one name."""
        from signals.sector_rotation import SectorRotationModel
        now = timezone.now()
        # Measured in both windows, and speeding up on its own.
        self._paced("BOTHWIN", "Financial Services", 0.09, 0.02, now)
        # Thirty days of history that stops six days ago: inside the long
        # window, absent from the short one. Its -60% pulls the unpaired long
        # mean negative, and the sector then reads `reversing_up` — a label
        # made of one member's recent pace and a different member's long one.
        halted = _instrument("HALTED", asset_class="stock",
                             sector="Financial Services")
        _seed_daily(halted, _ramp(100.0, -0.60, 19), end=now - timedelta(days=6))
        result = SectorRotationModel().analyze(lookback_days=30, now=now)
        self.assertEqual(result["momentum"]["Financial Services"],
                         "accelerating")
        # The performance table still counts it. That is a single-window
        # measurement with nothing to be paired against, and the member really
        # is in the window it reports.
        self.assertEqual(result["sector_members"]["Financial Services"], 2)

    def test_leaders_and_laggards_never_name_the_same_sector(self):
        """Three sectors, top three and bottom three: every sector was both a
        leader and a laggard, and the suggestions rotated out of a sector and
        into itself."""
        from signals.sector_rotation import SectorRotationModel
        now = timezone.now()
        for i, sector in enumerate(("Technology", "Energy", "Utilities")):
            self._sector(sector, [f"{sector[:4]}{j}" for j in range(3)],
                         0.02 * (i + 1), now)
        result = SectorRotationModel().analyze(lookback_days=30, now=now)
        self.assertEqual(
            set(result["leading_sectors"]) & set(result["lagging_sectors"]),
            set())
        self.assertEqual(len(result["leading_sectors"]), 1)
        self.assertEqual(len(result["lagging_sectors"]), 1)

    def test_a_one_stock_sector_is_reported_but_not_acted_on(self):
        """"Energy +4%" means something different across eleven names than
        across one, and the mean alone cannot tell them apart."""
        from signals.sector_rotation import SectorRotationModel
        now = timezone.now()
        self._sector("Technology", ["TECHA", "TECHB", "TECHC"], 0.02, now)
        self._sector("Energy", ["ENERA", "ENERB", "ENERC"], 0.01, now)
        self._sector("Utilities", ["UTILA"], 0.90, now)
        result = SectorRotationModel().analyze(lookback_days=30, now=now)
        self.assertIn("Utilities", result["sector_performance"])
        self.assertEqual(result["sector_members"]["Utilities"], 1)
        self.assertNotIn("Utilities", result["leading_sectors"])
        self.assertNotIn("Utilities", result["lagging_sectors"])

    def test_an_unmeasurable_member_is_not_counted_as_a_flat_one(self):
        """Averaging a zero in for the member with no history drags a +10%
        sector to +6.7% and reports it over three names instead of two."""
        from signals.sector_rotation import SectorRotationModel
        now = timezone.now()
        self._sector("Healthcare", ["HLTHA", "HLTHB"], 0.10, now)
        stub = _instrument("HLTHC", asset_class="stock", sector="Healthcare")
        _seed_daily(stub, [100.0], end=now)
        result = SectorRotationModel().analyze(lookback_days=30, now=now)
        self.assertAlmostEqual(result["sector_performance"]["Healthcare"], 0.10,
                               places=4)
        self.assertEqual(result["sector_members"]["Healthcare"], 2)

    def test_the_direction_read_is_withheld_on_a_table_too_short_to_read(self):
        """The test asks whether two of the TOP THREE belong to a risk group.
        With three sectors the top three IS the table, so the answer describes
        our coverage rather than the market's."""
        from signals.sector_rotation import SectorRotationModel
        now = timezone.now()
        for i, sector in enumerate(("Technology", "Industrials")):
            self._sector(sector, [f"D{i}{j}" for j in range(3)], 0.03, now)
        result = SectorRotationModel().analyze(lookback_days=30, now=now)
        self.assertEqual(result["rotation_direction"], "unknown")

    def test_the_dashboard_and_the_rank_measure_a_window_the_same_way(self):
        """One implementation of "what is a return, and when is there not one"
        behind both, so a sector table and a rank cannot disagree about it."""
        from signals.opportunity_scanner import window_return
        self.assertIsNone(window_return([100.0]))
        self.assertIsNone(window_return([0.0, 110.0]))
        self.assertAlmostEqual(window_return([100.0, 105.0, 110.0]), 0.10,
                               places=9)
