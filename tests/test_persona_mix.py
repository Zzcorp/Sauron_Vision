"""THE MIX MOVES WITH THE MARKET — the regime-at-open join and the lanes.

The operator's ask was "make the three personalities interact
continuously — under certain market states some personalities should be
used more". The answer this platform gives is NOT a belief about which
personality suits which tape (nobody knows that yet, and this deployment
has ten graded signals and no config that has ever worn a personality).
It is a two-lane machine: MEASURED beats PRIOR beats NEUTRAL, every
answer records which lane spoke and with what n, and the priors retire
cell by cell as evidence arrives.

What these tests exist to stop, and the first one is the whole chantier:

  - THE REGIME READ AT THE WRONG TIME. A trade that opened on Tuesday was
    opened into Tuesday's tape. Reading the CURRENT BrainReport for it
    would stamp every trade in history with this morning's label: every
    cell of the matrix would fill with one regime, the measured lane
    would look like it was working, and it would be measuring nothing.
    The join is on opened_at against the report that existed THEN, and
    these tests build a week of reports to prove it.
  - a query per trade. `regime_series` is one query and a bisect; a pass
    over hundreds of fills that called `regime_at` per row would hammer a
    table the synthesizer writes to every half hour.
  - a gap or an overlap in the stretches. A trade that opened in a gap
    would silently vanish from every cell; one in an overlap would be
    counted twice, in two different regimes.
  - a failed synthesis read as a measurement. A BrainReport carrying an
    `error` defaults its regime_label to 'unknown', and counting it would
    record "the market was unclassifiable" where the truth is "the run
    crashed".
  - PAPER AND LIVE POOLED. Two different measurements of the same
    personality, not two samples of one.
  - a thin cell that acts. Below MIN_EVIDENCE_N there is no avg_r at all,
    so nothing downstream can multiply by three fills' worth of luck.
  - a prior that stops being small, or that survives its own evidence. A
    measured cell REPLACES its prior entirely, and every factor this
    module can produce lands inside [0.75, 1.25].
  - a regime flip that jolts the book. The band's width is preserved and
    its centre moves at most MAX_BAND_SHIFT_PCT points.

Run with:  python manage.py test tests.test_persona_mix
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

User = get_user_model()


# ── fixtures ────────────────────────────────────────────────────────────

def _user(name="mixer"):
    return User.objects.create_user(username=name, password="x")


def _cfg(user, *, name="bot", persona="", asset_class="stock", mode="paper",
         symbols=("AAPL",), extras=None):
    """A config, optionally WEARING a persona (the extras key personas.py
    stamps — written directly so these tests do not depend on
    apply_persona's refusals)."""
    from bot_program.models import AssetBotConfig
    from bot_program.personas import PERSONA_EXTRAS_KEY
    ex = dict(extras or {})
    if persona:
        ex[PERSONA_EXTRAS_KEY] = persona
    return AssetBotConfig.objects.create(
        user=user, asset_class=asset_class, name=name, mode=mode,
        enabled=True, symbols=list(symbols), capital=Decimal("1000"),
        extras=ex)


def _fill(cfg, r, *, opened, closed=None, paper=False, rule="r1",
          outcome="hit_target"):
    """A graded closed fill with an EXPLICIT opened_at.

    `opened_at` is auto_now_add and `closed_at` is not, so both are
    written back with an UPDATE — the whole module joins on opened_at and
    a fixture that could not set it would test nothing.
    """
    from bot_program.models import AssetBotTrade
    t = AssetBotTrade.objects.create(
        config=cfg, asset_class=cfg.asset_class, symbol="AAPL", side="BUY",
        qty=Decimal("1"), entry_price=Decimal("100"),
        exit_price=Decimal("101"), status="CLOSED", pnl=Decimal("1"),
        rule_name=rule, paper=paper, realized_r=r, outcome=outcome)
    AssetBotTrade.objects.filter(pk=t.pk).update(
        opened_at=opened, closed_at=closed or (opened + timedelta(hours=2)))
    t.refresh_from_db()
    return t


def _report(label, *, at, confidence=0.8, error=""):
    """A BrainReport stamped at `at` — created_at is auto_now_add."""
    from brain.models import BrainReport
    rep = BrainReport.objects.create(regime_label=label,
                                     regime_confidence=confidence,
                                     error=error)
    BrainReport.objects.filter(pk=rep.pk).update(created_at=at)
    rep.refresh_from_db()
    return rep


# ── 1. The regime the platform RECORDED, not the one showing now ────────

class RegimeAtOpenTests(TestCase):
    """The join this whole chantier stands on."""

    def setUp(self):
        self.now = timezone.now()
        self.d = lambda n: self.now - timedelta(days=n)

    def test_the_vocabulary_is_the_models_own(self):
        """REGIMES is BrainReport's own choices, not a list invented here.

        If the model ever grows or renames a regime, this fails instead of
        the matrix quietly dropping a column and the priors keying on a
        label nothing writes any more.
        """
        from bot_program import persona_mix as mix
        from brain.models import BrainReport
        self.assertEqual(set(mix.REGIMES),
                         {v for v, _ in BrainReport.REGIME_CHOICES})
        self.assertEqual(mix.REGIME_UNKNOWN, BrainReport.REGIME_UNKNOWN)
        # And every one of them is a token brain.hypotheses recognises —
        # the same vocabulary the synthesizer's own claims are graded in.
        from brain.hypotheses import canonical_regime
        for reg in mix.REGIMES:
            self.assertEqual(canonical_regime(reg), reg)

    def test_a_trade_reads_the_regime_of_the_day_it_opened(self):
        """Three reports across a week; a trade opened on day two reads
        DAY TWO'S label, never today's."""
        from bot_program.persona_mix import regime_at
        _report("trending", at=self.d(5))
        _report("mean_reverting", at=self.d(4))
        _report("risk_on", at=self.d(1))
        # day two of the week = between the 4-day-old and the 1-day-old
        # report, so what the platform was recording then is
        # mean_reverting — and what it records NOW is risk_on.
        self.assertEqual(regime_at(self.d(3)), "mean_reverting")
        self.assertEqual(regime_at(self.d(4) + timedelta(hours=1)),
                         "mean_reverting")
        self.assertEqual(regime_at(self.d(4) - timedelta(hours=1)),
                         "trending")
        self.assertEqual(regime_at(self.now), "risk_on")
        self.assertNotEqual(regime_at(self.d(3)), regime_at(self.now))

    def test_a_report_with_an_error_is_skipped(self):
        """A crashed synthesis recorded nothing. Its default label
        ('unknown') must not overwrite the last real reading."""
        from bot_program.persona_mix import regime_at
        _report("trending", at=self.d(3))
        _report("risk_off", at=self.d(2), error="anthropic timeout")
        self.assertEqual(regime_at(self.d(1)), "trending")

    def test_no_report_at_all_is_unknown(self):
        from bot_program.persona_mix import regime_at
        self.assertEqual(regime_at(self.now), "unknown")
        # And a moment BEFORE the first report ever written is unknown
        # too — the platform recorded nothing then, which is not a state
        # of the market.
        _report("trending", at=self.d(2))
        self.assertEqual(regime_at(self.d(5)), "unknown")

    def test_an_unmappable_label_reads_as_unknown(self):
        """A hand-edited row saying 'sideways chop' is not a sixth regime
        with no prior and no measurement — it is no reading."""
        from bot_program.persona_mix import regime_at
        _report("sideways chop", at=self.d(2))
        self.assertEqual(regime_at(self.d(1)), "unknown")


class RegimeSeriesTests(TestCase):
    """One query and a bisect, and the stretches tile the window."""

    def setUp(self):
        self.now = timezone.now()
        self.d = lambda n: self.now - timedelta(days=n)
        _report("trending", at=self.d(6))
        _report("mean_reverting", at=self.d(4))
        _report("risk_off", at=self.d(2), error="boom")   # skipped
        _report("risk_on", at=self.d(1))

    def test_the_series_costs_exactly_one_query(self):
        from bot_program.persona_mix import regime_series
        with self.assertNumQueries(1):
            series = regime_series(self.d(5), self.now)
        self.assertTrue(series)

    def test_a_pass_over_many_trades_costs_one_query_and_a_bisect(self):
        """The reason the series exists: `regime_at` per row would be one
        query per row."""
        from bot_program.persona_mix import regime_in_series, regime_series
        opens = [self.d(5) + timedelta(hours=h) for h in range(0, 110, 2)]
        with self.assertNumQueries(1):
            series = regime_series(min(opens), self.now)
            labels = [regime_in_series(series, o) for o in opens]
        self.assertEqual(len(labels), len(opens))
        self.assertTrue(set(labels) <= set(("trending", "mean_reverting",
                                            "risk_on")))

    def test_stretches_tile_the_window_with_no_gap_and_no_overlap(self):
        from bot_program.persona_mix import regime_series
        since, until = self.d(5), self.now
        series = regime_series(since, until)
        self.assertGreaterEqual(len(series), 3)
        self.assertEqual(series[0][0], since)
        self.assertEqual(series[-1][1], until)
        for (a_from, a_to, _l, _c), (b_from, _bt, _bl, _bc) in zip(
                series, series[1:]):
            self.assertLess(a_from, a_to, "a zero-width stretch is a hole "
                                          "a bisect can land inside")
            self.assertEqual(a_to, b_from, "a gap loses every trade opened "
                                           "in it; an overlap counts one "
                                           "trade in two regimes")

    def test_the_head_stretch_carries_the_label_in_force_before_the_window(self):
        """The window opens mid-regime. The stretch before the first
        report INSIDE it is what the platform was recording then — read
        from the report BEFORE `since`, not blanked to unknown."""
        from bot_program.persona_mix import regime_series
        series = regime_series(self.d(5), self.now)
        self.assertEqual(series[0][2], "trending")
        self.assertEqual(series[-1][2], "risk_on")
        # The errored report is nowhere in the series.
        self.assertNotIn("risk_off", [s[2] for s in series])

    def test_a_window_older_than_every_report_starts_unknown(self):
        from bot_program.persona_mix import regime_series
        series = regime_series(self.d(9), self.now)
        self.assertEqual(series[0][2], "unknown")

    def test_series_and_regime_at_agree(self):
        """Two readers of the same fact must never disagree — the page
        uses one and a single-row caller the other."""
        from bot_program.persona_mix import (regime_at, regime_in_series,
                                             regime_series)
        series = regime_series(self.d(7), self.now)
        for hours in (1, 30, 60, 100, 150):
            when = self.d(7) + timedelta(hours=hours)
            self.assertEqual(regime_in_series(series, when), regime_at(when),
                             f"disagreement at +{hours}h")


# ── 2. What each personality earned in each regime ──────────────────────

class PersonaRegimeRecordTests(TestCase):

    def setUp(self):
        self.now = timezone.now()
        self.d = lambda n: self.now - timedelta(days=n)
        self.user = _user()
        # A fortnight of tape: mean_reverting until day 6, then trending.
        _report("mean_reverting", at=self.d(14))
        _report("trending", at=self.d(6))
        self.scalp = _cfg(self.user, name="fast", persona="scalp")
        self.swing = _cfg(self.user, name="slow", persona="swing")
        self.bare = _cfg(self.user, name="plain")          # no persona

    def _record(self, key, regime, **kw):
        from bot_program.persona_mix import persona_regime_record
        return persona_regime_record(key, regime, now=self.now, **kw)

    def test_only_configs_wearing_that_persona_are_counted(self):
        for i in range(12):
            _fill(self.scalp, 0.5, opened=self.d(10) + timedelta(hours=i))
        for i in range(12):
            _fill(self.bare, 9.0, opened=self.d(10) + timedelta(hours=i))
        rec = self._record("scalp", "mean_reverting")
        self.assertEqual(rec["n"], 12)
        self.assertAlmostEqual(rec["avg_r"], 0.5, places=6)
        # The persona-less config's spectacular record belongs to nobody.
        self.assertEqual(self._record("swing", "mean_reverting")["n"], 0)

    def test_only_trades_whose_OPEN_fell_in_that_regime_count(self):
        """The join, again, from the record's side: a trade that opened in
        the range and closed in the trend is a RANGE trade."""
        for i in range(11):
            _fill(self.scalp, 1.0, opened=self.d(10) + timedelta(hours=i),
                  closed=self.d(2))          # closed well into the trend
        for i in range(11):
            _fill(self.scalp, -1.0, opened=self.d(4) + timedelta(hours=i))
        mr = self._record("scalp", "mean_reverting")
        tr = self._record("scalp", "trending")
        self.assertEqual(mr["n"], 11)
        self.assertAlmostEqual(mr["avg_r"], 1.0, places=6)
        self.assertEqual(tr["n"], 11)
        self.assertAlmostEqual(tr["avg_r"], -1.0, places=6)

    def test_live_and_paper_are_never_pooled(self):
        for i in range(11):
            _fill(self.scalp, 1.0, opened=self.d(10) + timedelta(hours=i),
                  paper=False)
        for i in range(11):
            _fill(self.scalp, -2.0, opened=self.d(10) + timedelta(hours=i),
                  paper=True)
        live = self._record("scalp", "mean_reverting", venue="live")
        paper = self._record("scalp", "mean_reverting", venue="paper")
        self.assertEqual((live["n"], paper["n"]), (11, 11))
        self.assertAlmostEqual(live["avg_r"], 1.0, places=6)
        self.assertAlmostEqual(paper["avg_r"], -2.0, places=6)
        self.assertIn("live", live["reason"])
        self.assertIn("paper", paper["reason"])
        # Pooling is refused outright, not defaulted.
        with self.assertRaises(ValueError):
            self._record("scalp", "mean_reverting", venue="all")

    def test_below_the_floor_there_is_no_average_at_all(self):
        from bot_program.evidence import MIN_EVIDENCE_N
        for i in range(MIN_EVIDENCE_N - 1):
            _fill(self.scalp, 3.0, opened=self.d(10) + timedelta(hours=i))
        rec = self._record("scalp", "mean_reverting")
        self.assertEqual(rec["n"], MIN_EVIDENCE_N - 1)
        self.assertFalse(rec["measured"])
        self.assertIsNone(rec["avg_r"], "three fills of luck must not be "
                                        "multipliable")
        self.assertIsNone(rec["win_rate"])
        self.assertIn(str(MIN_EVIDENCE_N), rec["reason"])

    def test_an_empty_cell_is_unmeasured_and_not_zero(self):
        rec = self._record("position", "trending")
        self.assertEqual(rec["n"], 0)
        self.assertFalse(rec["measured"])
        self.assertIsNone(rec["avg_r"])
        self.assertIsNone(rec["r_sum"], "0.0R reads as 'broke even', which "
                                        "is a claim")
        self.assertIn("not zero", rec["reason"])

    def test_ungraded_and_hand_taken_rows_are_excluded(self):
        for i in range(11):
            _fill(self.scalp, 1.0, opened=self.d(10) + timedelta(hours=i),
                  rule="manual_take")
        for i in range(11):
            _fill(self.scalp, 1.0, opened=self.d(10) + timedelta(hours=i),
                  outcome="")
        self.assertEqual(self._record("scalp", "mean_reverting")["n"], 0)

    def test_each_persona_is_windowed_by_its_own_evidence_days(self):
        """21 days of scalps is a sample; 21 days of position trades is
        one trade. A fill 60 days old is inside swing's window and
        outside scalp's."""
        from bot_program.personas import PERSONAS
        _report("trending", at=self.d(200))
        scalp_old = _cfg(self.user, name="fast2", persona="scalp")
        swing_old = _cfg(self.user, name="slow2", persona="swing")
        for i in range(11):
            when = self.d(60) + timedelta(hours=i)
            _fill(scalp_old, 1.0, opened=when, closed=when + timedelta(hours=1))
            _fill(swing_old, 1.0, opened=when, closed=when + timedelta(hours=1))
        scalp_rec = self._record("scalp", "trending")
        swing_rec = self._record("swing", "trending")
        self.assertEqual(scalp_rec["days"], PERSONAS["scalp"].evidence_days)
        self.assertEqual(swing_rec["days"], PERSONAS["swing"].evidence_days)
        self.assertEqual(scalp_rec["n"], 0, "60-day-old fills are outside a "
                                            "21-day scalp window")
        self.assertEqual(swing_rec["n"], 11)
        # An explicit window still wins outright.
        self.assertEqual(self._record("scalp", "trending", days=365)["n"], 11)

    def test_an_unknown_persona_is_an_empty_record_not_a_crash(self):
        rec = self._record("daytrader", "trending")
        self.assertEqual(rec["n"], 0)
        self.assertFalse(rec["measured"])
        self.assertIn("no persona named", rec["reason"])

    def test_the_matrix_covers_every_cell(self):
        from bot_program.persona_mix import REGIMES, record_matrix
        from bot_program.personas import PERSONA_KEYS
        for i in range(11):
            _fill(self.scalp, 0.8, opened=self.d(10) + timedelta(hours=i))
        matrix = record_matrix(venue="live", now=self.now)
        self.assertEqual(set(matrix), set(PERSONA_KEYS))
        for key in PERSONA_KEYS:
            self.assertEqual(set(matrix[key]), set(REGIMES))
        self.assertTrue(matrix["scalp"]["mean_reverting"]["measured"])
        self.assertFalse(matrix["scalp"]["trending"]["measured"])
        # And the matrix agrees with the single-cell reader, or the page
        # and the plan would print two different numbers.
        single = self._record("scalp", "mean_reverting")
        self.assertEqual(single["n"], matrix["scalp"]["mean_reverting"]["n"])
        self.assertAlmostEqual(single["avg_r"],
                               matrix["scalp"]["mean_reverting"]["avg_r"],
                               places=9)


# ── 3. The factor, and the three lanes ──────────────────────────────────

class MixFactorTests(TestCase):

    def setUp(self):
        self.now = timezone.now()
        self.d = lambda n: self.now - timedelta(days=n)
        self.user = _user()
        _report("mean_reverting", at=self.d(14))
        self.scalp = _cfg(self.user, name="fast", persona="scalp")

    def _factor(self, key, regime, **kw):
        from bot_program.persona_mix import mix_factor
        return mix_factor(key, regime, now=self.now, **kw)

    def test_measured_beats_prior(self):
        """The prior for scalp in mean_reverting is +0.6 (a 1.09 factor).
        Eleven losing fills must turn that DOWN, not be averaged with it."""
        from bot_program.persona_mix import PRIORS, PRIOR_STRENGTH
        prior_factor = 1.0 + PRIORS[("scalp", "mean_reverting")] * PRIOR_STRENGTH
        for i in range(11):
            _fill(self.scalp, -0.8, opened=self.d(10) + timedelta(hours=i))
        out = self._factor("scalp", "mean_reverting")
        self.assertEqual(out["lane"], "measured")
        self.assertEqual(out["n"], 11)
        self.assertAlmostEqual(out["avg_r"], -0.8, places=6)
        self.assertAlmostEqual(out["factor"], 1.0 - 0.8 * 0.25, places=6)
        self.assertLess(out["factor"], 1.0)
        self.assertLess(out["factor"], prior_factor,
                        "a measured cell REPLACES its prior — it is not "
                        "blended with it")

    def test_prior_beats_neutral(self):
        from bot_program.persona_mix import PRIORS, PRIOR_STRENGTH
        out = self._factor("scalp", "mean_reverting")
        self.assertEqual(out["lane"], "prior")
        self.assertAlmostEqual(
            out["factor"],
            1.0 + PRIORS[("scalp", "mean_reverting")] * PRIOR_STRENGTH,
            places=9)
        self.assertNotEqual(out["factor"], 1.0)
        self.assertIn("unproven", out["reason"])

    def test_a_thin_cell_still_reads_as_the_prior(self):
        """Nine fills is not evidence. The prior holds and the reason says
        the lane is still a guess."""
        for i in range(9):
            _fill(self.scalp, -5.0, opened=self.d(10) + timedelta(hours=i))
        out = self._factor("scalp", "mean_reverting")
        self.assertEqual(out["lane"], "prior")
        self.assertIsNone(out["avg_r"])
        self.assertGreater(out["factor"], 1.0)

    def test_an_unknown_regime_is_exactly_one(self):
        """Not 'about one'. 'unknown' is the absence of a reading, and
        nothing may move a band on it — measured or not."""
        for i in range(20):
            _fill(self.scalp, 2.0, opened=self.d(10) + timedelta(hours=i))
        out = self._factor("scalp", "unknown")
        self.assertEqual(out["factor"], 1.0)
        self.assertEqual(out["lane"], "neutral")
        self.assertIn("absence of a reading", out["reason"])

    def test_every_factor_lands_inside_the_bound(self):
        """A ten-R month cannot double a band."""
        from bot_program.persona_mix import (MAX_TILT, PRIORS, REGIMES,
                                             mix_factor)
        from bot_program.personas import PERSONA_KEYS
        for i in range(15):
            _fill(self.scalp, 12.0, opened=self.d(10) + timedelta(hours=i))
        hot = self._factor("scalp", "mean_reverting")
        self.assertEqual(hot["lane"], "measured")
        self.assertAlmostEqual(hot["factor"], 1.0 + MAX_TILT, places=9)
        for key in PERSONA_KEYS:
            for reg in REGIMES:
                f = mix_factor(key, reg, now=self.now)["factor"]
                self.assertGreaterEqual(f, 1.0 - MAX_TILT)
                self.assertLessEqual(f, 1.0 + MAX_TILT)
        # And no prior in the table is bigger than the mechanism allows.
        for tilt in PRIORS.values():
            self.assertLessEqual(abs(tilt), 1.0)

    def test_the_reason_names_the_lane_and_the_n(self):
        for i in range(11):
            _fill(self.scalp, 0.42, opened=self.d(10) + timedelta(hours=i))
        measured = self._factor("scalp", "mean_reverting")
        self.assertTrue(measured["reason"].startswith("measured:"))
        self.assertIn("11", measured["reason"])
        self.assertIn("+0.42R", measured["reason"])
        self.assertIn("mean_reverting", measured["reason"])
        prior = self._factor("position", "mean_reverting")
        self.assertTrue(prior["reason"].startswith("prior (unproven):"))
        neutral = self._factor("swing", "unknown")
        self.assertTrue(neutral["reason"].startswith("neutral:"))

    def test_every_prior_cell_carries_a_stated_why(self):
        """A prior with no reason is a magic number, and a magic number
        nobody can argue with is one nobody can retire."""
        from bot_program.persona_mix import PRIORS, PRIOR_WHY
        from bot_program.personas import PERSONA_KEYS
        from bot_program.persona_mix import REGIMES
        for key in PERSONA_KEYS:
            for reg in REGIMES:
                self.assertIn((key, reg), PRIORS)
                self.assertTrue(str(PRIOR_WHY.get((key, reg)) or "").strip(),
                                f"{key}/{reg} has a tilt and no stated why")


class CurrentMixTests(TestCase):
    """One call the allocator, the page and the command all share."""

    def setUp(self):
        self.now = timezone.now()
        self.d = lambda n: self.now - timedelta(days=n)
        self.user = _user()
        self.scalp = _cfg(self.user, name="fast", persona="scalp")

    def test_an_empty_platform_is_all_neutral_and_does_not_crash(self):
        from bot_program.persona_mix import current_mix
        out = current_mix(self.user, now=self.now)
        self.assertEqual(out["regime"], "unknown")
        self.assertEqual(out["measured"], 0)
        self.assertEqual(set(out["personas"]), {"scalp", "swing", "position"})
        for d in out["personas"].values():
            self.assertEqual(d["factor"], 1.0)
            self.assertEqual(d["lane"], "neutral")
        self.assertIn("no brain report", out["source"])
        self.assertEqual(out["bands"]["swing"], (20.0, 60.0))

    def test_it_reads_the_current_regime_and_agrees_with_mix_factor(self):
        from bot_program.persona_mix import current_mix, mix_factor
        _report("trending", at=self.d(3), confidence=0.72)
        out = current_mix(self.user, now=self.now)
        self.assertEqual(out["regime"], "trending")
        self.assertAlmostEqual(out["confidence"], 0.72, places=6)
        self.assertIn("BrainReport #", out["source"])
        self.assertGreaterEqual(out["age_minutes"], 0)
        for key, d in out["personas"].items():
            self.assertEqual(d["lane"], "prior")
            self.assertAlmostEqual(
                d["factor"],
                mix_factor(key, "trending", now=self.now)["factor"],
                places=9,
                msg="the page and the plan must never print two numbers")

    def test_a_measured_cell_is_counted_as_measured(self):
        from bot_program.persona_mix import current_mix
        _report("trending", at=self.d(20))
        for i in range(11):
            _fill(self.scalp, 0.6, opened=self.d(10) + timedelta(hours=i))
        out = current_mix(self.user, now=self.now)
        self.assertEqual(out["regime"], "trending")
        self.assertEqual(out["personas"]["scalp"]["lane"], "measured")
        self.assertEqual(out["measured"], 1)
        self.assertEqual(out["personas"]["swing"]["lane"], "prior")


# ── 4. How far a regime may move a band ─────────────────────────────────

class ShiftBandTests(TestCase):
    """Pure arithmetic. The allocator calls this inside `bounds_for`; the
    bound it enforces is why a regime flip can never jolt the book."""

    def test_the_width_is_preserved_and_the_centre_moves(self):
        from bot_program.persona_mix import shift_band
        lo, hi = shift_band(20.0, 60.0, 1.05)
        self.assertAlmostEqual(hi - lo, 40.0, places=6)
        self.assertAlmostEqual(lo, 22.0, places=6)
        self.assertAlmostEqual(hi, 62.0, places=6)

    def test_the_shift_is_clamped_to_five_points(self):
        """A factor of 1.15 on swing (20-60) asks for +6 and gets +5 —
        25-65, never 40-80."""
        from bot_program.persona_mix import MAX_BAND_SHIFT_PCT, shift_band
        self.assertEqual(MAX_BAND_SHIFT_PCT, 5.0)
        lo, hi = shift_band(20.0, 60.0, 1.15)
        self.assertAlmostEqual(lo, 25.0, places=6)
        self.assertAlmostEqual(hi, 65.0, places=6)
        lo, hi = shift_band(20.0, 60.0, 0.75)
        self.assertAlmostEqual(lo, 15.0, places=6)
        self.assertAlmostEqual(hi, 55.0, places=6)
        self.assertAlmostEqual(hi - lo, 40.0, places=6)

    def test_a_factor_of_one_changes_nothing(self):
        from bot_program.persona_mix import shift_band
        for band in ((5.0, 25.0), (20.0, 60.0), (15.0, 50.0)):
            self.assertEqual(shift_band(*band, 1.0), band)

    def test_the_band_stays_inside_the_account(self):
        """bounds_for refuses a band outside 0 < floor <= ceiling <= 100
        and falls back to the 2-60 DEFAULTS — which would undo the
        persona band entirely, the one outcome worse than not shifting."""
        from bot_program.persona_mix import shift_band
        lo, hi = shift_band(1.0, 3.0, 0.1)
        self.assertGreater(lo, 0.0)
        self.assertLessEqual(hi, 100.0)
        self.assertLessEqual(lo, hi)
        lo, hi = shift_band(97.0, 99.5, 1.5)
        self.assertLessEqual(hi, 100.0)
        self.assertGreater(lo, 0.0)

    def test_every_persona_band_survives_every_possible_factor(self):
        """Whatever the mix says, the band handed to the allocator is one
        `bounds_for` will accept."""
        from bot_program.persona_mix import MAX_TILT, shift_band
        from bot_program.personas import PERSONAS
        for p in PERSONAS.values():
            for f in (1.0 - MAX_TILT, 0.9, 1.0, 1.1, 1.0 + MAX_TILT):
                lo, hi = shift_band(p.share_floor_pct,
                                    p.share_ceiling_pct, f)
                self.assertTrue(0.0 < lo <= hi <= 100.0,
                                f"{p.key} at ×{f} -> {lo}/{hi}")
                self.assertAlmostEqual(
                    hi - lo,
                    p.share_ceiling_pct - p.share_floor_pct, places=6)


# ── 5. The allocator uses the mix — and only where it may ───────────────

def _acct(user, equity="2000.00", currency="EUR"):
    """A broker-backed account with a FRESH reading; without one the
    proposer refuses before it reaches a single band."""
    from bot_program.models import IBKRAccount
    acct = IBKRAccount.objects.create(user=user, port=4003,
                                      is_primary_for_stocks=True)
    acct.set_credentials("U1234567")
    acct.username_enc, acct.password_enc = "x", "y"
    acct.last_equity = Decimal(equity)
    acct.last_equity_currency = currency
    acct.last_equity_at = timezone.now()
    acct.save()
    return acct


def _follower(user, *, name, persona="", share=None, **extras):
    """A LIVE pool that follows the account — what the allocator sizes."""
    ex = dict(extras)
    ex["capital_tracks_broker"] = True
    if share is not None:
        ex["account_share_pct"] = share
    return _cfg(user, name=name, persona=persona, mode="live", extras=ex)


class ANoPersonaConfigProposesExactlyWhatItDidBeforeTests(TestCase):
    """THE BINDING REQUIREMENT of this chantier, and the first test
    written for it.

    Every config on this deployment wears no personality at all. If the
    mix could move one point of one of their shares, this feature would
    have changed the live book on the strength of a table of guesses
    nobody has tested — the one thing it was built not to do. So: propose
    with the mix UNREACHABLE (the allocator exactly as it was), propose
    again with it reachable, and demand the two inputs rows be equal key
    for key and string for string.
    """

    def setUp(self):
        self.user = _user("noper")
        _acct(self.user)

    def _propose(self):
        from bot_program.share_allocator import propose_share_plan
        return propose_share_plan(self.user)

    def test_the_numbers_are_identical_with_and_without_the_mix(self):
        from unittest.mock import patch
        # mean_reverting carries the loudest priors in the table
        # (+0.6 / +0.3 / -0.6): if the mix could leak onto a config with
        # no personality, this is the tape where it would show.
        _report("mean_reverting", at=timezone.now() - timedelta(hours=1))
        a = _follower(self.user, name="a", share=40)
        b = _follower(self.user, name="b", share=60)
        with patch("bot_program.persona_mix.current_mix",
                   side_effect=RuntimeError("mix unreachable")):
            before = self._propose()
        after = self._propose()
        self.assertIsNotNone(before)
        self.assertIsNotNone(after)
        self.assertEqual(before.targets, after.targets)
        for cfg in (a, b):
            k = str(cfg.pk)
            self.assertEqual(before.inputs[k], after.inputs[k],
                             f"{cfg.name}'s inputs row moved")
            self.assertNotIn("mix", after.inputs[k])
            self.assertNotIn("mix", after.inputs[k]["why"])
            self.assertEqual(after.inputs[k]["floor"], 2.0)
            self.assertEqual(after.inputs[k]["ceiling"], 60.0)

    def test_a_mix_reader_that_fails_costs_the_shift_and_not_the_plan(self):
        from unittest.mock import patch
        _report("trending", at=timezone.now() - timedelta(hours=1))
        s = _follower(self.user, name="sw", persona="swing", share=100)
        with patch("bot_program.persona_mix.current_mix",
                   side_effect=RuntimeError("brain on fire")):
            plan = self._propose()
        self.assertIsNotNone(plan)
        self.assertIn("mix reader failed", plan.notes)
        self.assertIn("persona bands unshifted", plan.notes)
        row = plan.inputs[str(s.pk)]
        # The persona band exactly as the preset declares it.
        self.assertEqual((row["floor"], row["ceiling"]), (20.0, 60.0))
        self.assertNotIn("mix", row)

    def test_the_plan_notes_name_the_regime_and_count_the_lanes(self):
        _report("mean_reverting", at=timezone.now() - timedelta(hours=1))
        _follower(self.user, name="sw", persona="swing", share=100)
        plan = self._propose()
        self.assertIn("mix: regime mean_reverting", plan.notes)
        self.assertIn("0 of 3 personalities measured", plan.notes)
        self.assertIn("3 on an UNPROVEN prior", plan.notes)


class TheAllocatorMovesTheBandTests(TestCase):
    """The band's CENTRE moves, its WIDTH never does, and the shift is
    clamped — in the allocator, not only in `shift_band`'s own tests."""

    def setUp(self):
        self.user = _user("bander")
        _acct(self.user)

    def _propose(self):
        from bot_program.share_allocator import propose_share_plan
        return propose_share_plan(self.user)

    def test_a_prior_shifts_the_centre_and_keeps_the_width(self):
        from bot_program.persona_mix import (PRIOR_STRENGTH, PRIORS,
                                             shift_band)
        _report("mean_reverting", at=timezone.now() - timedelta(hours=1))
        s = _follower(self.user, name="sw", persona="swing", share=50)
        p = _follower(self.user, name="po", persona="position", share=50)
        plan = self._propose()
        for cfg, key, band in ((s, "swing", (20.0, 60.0)),
                               (p, "position", (15.0, 50.0))):
            row = plan.inputs[str(cfg.pk)]
            factor = 1.0 + PRIORS[(key, "mean_reverting")] * PRIOR_STRENGTH
            lo, hi = shift_band(band[0], band[1], factor)
            self.assertAlmostEqual(row["floor"], lo, places=6)
            self.assertAlmostEqual(row["ceiling"], hi, places=6)
            self.assertAlmostEqual(row["ceiling"] - row["floor"],
                                   band[1] - band[0], places=6)
            self.assertAlmostEqual(row["mix"]["factor"], factor, places=9)
            self.assertEqual(row["mix"]["lane"], "prior")
            self.assertEqual(row["mix"]["regime"], "mean_reverting")
            self.assertTrue(row["mix"]["applied"])
            self.assertIn("unproven", row["mix"]["reason"])
        # swing is tilted UP by the range prior and position DOWN, which
        # is the operator's whole ask: different angles of attack on one
        # tape, from the same three personalities.
        self.assertGreater(plan.inputs[str(s.pk)]["mix"]["factor"], 1.0)
        self.assertLess(plan.inputs[str(p.pk)]["mix"]["factor"], 1.0)

    def test_the_why_sentence_and_the_inputs_carry_the_mix(self):
        from bot_program.persona_mix import PRIOR_STRENGTH, PRIORS
        _report("mean_reverting", at=timezone.now() - timedelta(hours=1))
        s = _follower(self.user, name="sw", persona="swing", share=100)
        plan = self._propose()
        row = plan.inputs[str(s.pk)]
        factor = 1.0 + PRIORS[("swing", "mean_reverting")] * PRIOR_STRENGTH
        self.assertIn(f"mix {factor:.2f} (prior, mean_reverting)",
                      row["why"])
        for key in ("factor", "lane", "n", "reason", "regime", "band",
                    "band_before", "applied"):
            self.assertIn(key, row["mix"])
        self.assertEqual(row["mix"]["band_before"], [20.0, 60.0])
        self.assertEqual(row["mix"]["band"], [row["floor"], row["ceiling"]])

    def test_a_measured_cell_shifts_the_band_and_the_shift_is_clamped(self):
        """Ten +3R live fills opened while the platform recorded
        `trending` pin the factor at MAX_TILT (1.25). That asks swing's
        centre (40) for +10 points of the account and gets +5 — 25-65,
        never 40-80."""
        from bot_program.evidence import MIN_EVIDENCE_N
        from bot_program.persona_mix import MAX_TILT
        opened = timezone.now() - timedelta(days=5)
        _report("trending", at=timezone.now() - timedelta(days=10))
        s = _follower(self.user, name="sw", persona="swing", share=100)
        for _ in range(MIN_EVIDENCE_N):
            _fill(s, Decimal("3.0"), opened=opened, paper=False)
        plan = self._propose()
        row = plan.inputs[str(s.pk)]
        self.assertEqual(row["mix"]["lane"], "measured")
        self.assertEqual(row["mix"]["n"], MIN_EVIDENCE_N)
        self.assertAlmostEqual(row["mix"]["factor"], 1.0 + MAX_TILT, places=9)
        self.assertAlmostEqual(row["floor"], 25.0, places=6)
        self.assertAlmostEqual(row["ceiling"], 65.0, places=6)
        self.assertAlmostEqual(row["ceiling"] - row["floor"], 40.0, places=6)
        self.assertIn("measured", row["why"])

    def test_an_explicit_extras_band_still_wins(self):
        _report("mean_reverting", at=timezone.now() - timedelta(hours=1))
        s = _follower(self.user, name="sw", persona="swing", share=50,
                      share_floor_pct=10, share_ceiling_pct=70)
        _follower(self.user, name="plain", share=50)
        plan = self._propose()
        row = plan.inputs[str(s.pk)]
        self.assertEqual((row["floor"], row["ceiling"]), (10.0, 70.0))
        self.assertFalse(row["mix"]["applied"])
        self.assertIn("the explicit band wins", row["why"])

    def test_half_an_explicit_band_is_still_an_explicit_band(self):
        """A human typed one of the two numbers. Shifting the other half
        by a regime would leave a band nobody could attribute to either
        of them."""
        from bot_program.persona_mix import current_mix
        from bot_program.share_allocator import bounds_for
        _report("mean_reverting", at=timezone.now() - timedelta(hours=1))
        cfg = _follower(self.user, name="sw", persona="swing", share=50,
                        share_ceiling_pct=70)
        mix = current_mix(self.user)
        lo, hi, _why = bounds_for(cfg, mix=mix)
        self.assertEqual((lo, hi), (20.0, 70.0))

    def test_the_manual_lane_still_has_no_ceiling(self):
        """The exemption that keeps the operator's own pool uncapped wins
        over a personality AND over the mix — it is case 1 of the
        precedence, and nothing below it may reach that pool."""
        from bot_program.persona_mix import current_mix
        from bot_program.share_allocator import bounds_for
        try:
            from bot_program.manual_trade import MANUAL_CONFIG_NAME
        except Exception:  # noqa: BLE001
            MANUAL_CONFIG_NAME = "manual"
        _report("mean_reverting", at=timezone.now() - timedelta(hours=1))
        cfg = _follower(self.user, name=MANUAL_CONFIG_NAME, persona="scalp",
                        share=80)
        cfg.symbols = []
        cfg.save()
        mix = current_mix(self.user)
        lo, hi, _why = bounds_for(cfg, mix=mix)
        self.assertEqual(hi, 100.0)

    def test_a_regime_flip_cannot_move_a_share_past_the_daily_cap(self):
        """The mix moves the BAND. Everything under it — the water-fill,
        the half-way smoothing, the 10-point daily cap, the hysteresis —
        still binds, so the largest move a flip can produce in one plan
        is MAX_CHANGE_PCT_PER_DAY."""
        from bot_program.share_allocator import MAX_CHANGE_PCT_PER_DAY
        sc = _follower(self.user, name="sc", persona="scalp", share=50)
        po = _follower(self.user, name="po", persona="position", share=50)
        quiet = self._propose()                  # no report -> unknown
        self.assertEqual(quiet.inputs[str(sc.pk)]["mix"]["lane"], "neutral")
        self.assertEqual((quiet.inputs[str(sc.pk)]["floor"],
                          quiet.inputs[str(sc.pk)]["ceiling"]), (5.0, 25.0))
        _report("mean_reverting", at=timezone.now() - timedelta(minutes=5))
        flipped = self._propose()
        # The band DID move — without this the test proves nothing.
        self.assertNotEqual((flipped.inputs[str(sc.pk)]["floor"],
                             flipped.inputs[str(sc.pk)]["ceiling"]),
                            (5.0, 25.0))
        for cfg in (sc, po):
            k = str(cfg.pk)
            move = abs(float(flipped.targets[k])
                       - float(flipped.current_shares[k]))
            self.assertLessEqual(move, MAX_CHANGE_PCT_PER_DAY + 1e-9,
                                 f"{cfg.name} moved {move:.2f} points")
        # scalp's band fell far below its 50% share: the CAP, not the
        # band, is what set the target.
        self.assertAlmostEqual(float(flipped.targets[str(sc.pk)]), 40.0,
                               places=2)


# ── 6. The matrix on /personas/ ─────────────────────────────────────────

class TheMatrixPageTests(TestCase):
    """The page that tells the operator what the platform has actually
    learned — and, far more often, what it has not."""

    def setUp(self):
        from django.urls import reverse
        self.user = _user("looker")
        self.url = reverse("personas_dashboard")
        self.client.force_login(self.user)

    def test_an_empty_platform_renders_all_prior_without_crashing(self):
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("The mix moves with the market", body)
        self.assertIn("prior", body)
        self.assertIn("18 of the 18 cells are still guesses", body)
        self.assertNotIn("measured n=", body)

    def test_a_measured_cell_is_visually_distinct_and_carries_its_n(self):
        from bot_program.evidence import MIN_EVIDENCE_N
        opened = timezone.now() - timedelta(days=5)
        _report("trending", at=timezone.now() - timedelta(days=10))
        cfg = _cfg(self.user, name="sw", persona="swing", mode="live")
        for _ in range(MIN_EVIDENCE_N):
            _fill(cfg, Decimal("1.0"), opened=opened, paper=False)
        body = self.client.get(self.url).content.decode()
        self.assertIn(f"measured n={MIN_EVIDENCE_N}", body)
        self.assertIn("font-weight: 700", body)      # measured is bold
        self.assertIn("font-style: italic", body)    # a prior is not
        self.assertIn("17 of the 18 cells are still guesses", body)
        self.assertIn("now", body)                   # the current column

    def test_the_page_survives_a_mix_that_cannot_be_read(self):
        from unittest.mock import patch
        with patch("bot_program.persona_mix.current_mix",
                   side_effect=RuntimeError("brain on fire")):
            resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("The regime mix could not be read", body)
        # The presets are still exact — that is why the page is fenced.
        self.assertIn("atr_timeframe", body)


# ── 7. `persona mix` ────────────────────────────────────────────────────

class ThePersonaMixCommandTests(TestCase):

    def _run(self, *args):
        from io import StringIO

        from django.core.management import call_command
        out = StringIO()
        call_command("persona", "mix", *args, stdout=out)
        return out.getvalue()

    def test_it_prints_the_matrix_and_the_current_regime(self):
        from bot_program.persona_mix import REGIMES
        from bot_program.personas import PERSONA_KEYS
        _report("mean_reverting", at=timezone.now() - timedelta(minutes=20),
                confidence=0.71)
        body = self._run()
        self.assertIn("recorded regime: mean_reverting", body)
        self.assertIn("confidence 0.71", body)
        self.assertIn("minutes old", body)
        for regime in REGIMES:
            self.assertIn(regime, body)
        for key in PERSONA_KEYS:
            self.assertIn(key, body)
        self.assertIn("18 of the 18 cells are still guesses", body)
        self.assertIn("prior (unproven)", body)
        self.assertIn("MEAN_REVERTING (recorded now)", body)

    def test_a_measured_cell_is_marked_and_counted(self):
        from bot_program.evidence import MIN_EVIDENCE_N
        user = _user("cmd")
        opened = timezone.now() - timedelta(days=5)
        _report("trending", at=timezone.now() - timedelta(days=10))
        cfg = _cfg(user, name="sw", persona="swing", mode="live")
        for _ in range(MIN_EVIDENCE_N):
            _fill(cfg, Decimal("1.0"), opened=opened, paper=False)
        body = self._run()
        self.assertIn(f"*n{MIN_EVIDENCE_N}", body)
        self.assertIn("17 of the 18 cells are still guesses", body)
        self.assertIn("1 measured (*)", body)
        self.assertIn("measured: swing earned", body)

    def test_paper_is_never_pooled_with_live(self):
        from bot_program.evidence import MIN_EVIDENCE_N
        user = _user("cmd2")
        opened = timezone.now() - timedelta(days=5)
        _report("trending", at=timezone.now() - timedelta(days=10))
        cfg = _cfg(user, name="sw", persona="swing", mode="paper")
        for _ in range(MIN_EVIDENCE_N):
            _fill(cfg, Decimal("1.0"), opened=opened, paper=True)
        self.assertIn("18 of the 18 cells are still guesses", self._run())
        paper = self._run("--venue", "paper")
        self.assertIn("17 of the 18 cells are still guesses", paper)
        self.assertIn("venue:           paper", paper)

    def test_a_what_if_regime_is_labelled_as_one(self):
        _report("risk_on", at=timezone.now() - timedelta(minutes=20))
        body = self._run("--regime", "blow_off")
        self.assertIn("recorded regime: risk_on", body)
        self.assertIn("BLOW_OFF (a what-if", body)

    def test_an_unknown_regime_name_is_refused(self):
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError) as caught:
            self._run("--regime", "melt_up")
        self.assertIn("no regime named", str(caught.exception))


# ── 8. The adversarial pass (2026-09-12) ────────────────────────────────
#
# Everything below was written by the review of the two stages above, and
# every one of these tests failed, or could not have failed, before it.


class TheAllocatorJoinsTheRegimeAtEntryTests(TestCase):
    """THE DEFECT THAT WOULD MAKE EVERY MEASURED CELL A FICTION.

    The unit tests above prove `persona_regime_record` joins on the
    trade's OPEN. Nothing proved it end to end, because every test that
    produced a measured cell for the allocator, the page or the command
    used a tape whose regime at entry WAS the current regime — so an
    implementation that read today's BrainReport for every trade in
    history would have passed all of them, every cell of the matrix would
    have filled with one label, and the measured lane would have looked
    like it was working while measuring nothing.

    Here the tape flips between the entry and the plan, so the two
    readings differ and only the right one passes.
    """

    def setUp(self):
        self.user = _user("joiner")
        _acct(self.user)

    def test_a_measured_cell_belongs_to_the_regime_the_trade_OPENED_in(self):
        from bot_program.evidence import MIN_EVIDENCE_N
        from bot_program.persona_mix import (MAX_TILT, PRIOR_STRENGTH, PRIORS,
                                             persona_regime_record)
        from bot_program.share_allocator import propose_share_plan
        now = timezone.now()
        # A fortnight of range, then yesterday the tape turned.
        _report("mean_reverting", at=now - timedelta(days=20))
        _report("trending", at=now - timedelta(days=1))
        s = _follower(self.user, name="sw", persona="swing", share=50)
        _follower(self.user, name="b", share=50)
        # Ten fat winners, every one OPENED in the range and closed after
        # the flip — the trades a current-regime join would hand to
        # `trending` and call evidence.
        for i in range(MIN_EVIDENCE_N):
            _fill(s, Decimal("3.0"),
                  opened=now - timedelta(days=10, hours=i),
                  closed=now - timedelta(hours=6), paper=False)
        mr = persona_regime_record("swing", "mean_reverting", now=now)
        tr = persona_regime_record("swing", "trending", now=now)
        self.assertTrue(mr["measured"])
        self.assertEqual(mr["n"], MIN_EVIDENCE_N)
        self.assertEqual(tr["n"], 0,
                         "a trade that OPENED in the range is a range "
                         "trade, whatever the tape did while it was held")
        plan = propose_share_plan(self.user)
        row = plan.inputs[str(s.pk)]
        self.assertEqual(row["mix"]["regime"], "trending")
        self.assertEqual(row["mix"]["lane"], "prior",
                         "the tape is trending and nothing has been "
                         "measured IN trending — reading today's label "
                         "for a trade opened a fortnight ago is what "
                         "would make this cell 'measured'")
        self.assertAlmostEqual(
            row["mix"]["factor"],
            1.0 + PRIORS[("swing", "trending")] * PRIOR_STRENGTH, places=9)
        self.assertNotAlmostEqual(row["mix"]["factor"], 1.0 + MAX_TILT,
                                  places=6)
        self.assertIn("unproven", row["mix"]["reason"])
        self.assertIn("(prior, trending)", row["why"])


class TheManualLaneIsNeverReportedAsShiftedTests(TestCase):
    """The plan must not claim a band it did not set.

    `bounds_for`'s precedence puts the MANUAL LANE above the persona
    band, so the shift that moves that band never runs on the operator's
    hand-taken pool. The plan reported it as applied anyway and printed
    "× mix 1.09 (prior, mean_reverting) on the band 5–25 → 2–100%" — the
    exemption's own numbers, over the mix's name, on the single most
    sensitive pool on the platform.
    """

    def setUp(self):
        self.user = _user("handlane")
        _acct(self.user)

    def test_a_persona_on_the_manual_lane_is_reported_as_not_applied(self):
        from bot_program.share_allocator import propose_share_plan
        try:
            from bot_program.manual_trade import MANUAL_CONFIG_NAME
        except Exception:  # noqa: BLE001
            MANUAL_CONFIG_NAME = "manual"
        _report("mean_reverting", at=timezone.now() - timedelta(hours=1))
        hand = _follower(self.user, name=MANUAL_CONFIG_NAME, persona="scalp",
                         share=60)
        hand.symbols = []
        hand.save()
        _follower(self.user, name="bot", persona="swing", share=40)
        plan = propose_share_plan(self.user)
        self.assertIsNotNone(plan)
        row = plan.inputs[str(hand.pk)]
        # The exemption still wins outright — that part was never broken.
        self.assertEqual((row["floor"], row["ceiling"]), (2.0, 100.0))
        # And the plan says so, naming the rule that won.
        self.assertFalse(row["mix"]["applied"])
        self.assertEqual(row["mix"]["outranked_by"], "the manual lane")
        self.assertIn("not applied, the manual lane wins", row["why"])
        self.assertNotIn("the explicit band wins", row["why"],
                         "nobody typed a band on this pool")
        self.assertNotIn("→ 2–100%", row["why"],
                         "the mix did not move this band to 2–100%; the "
                         "manual-lane exemption did")

    def test_an_explicit_band_still_names_the_explicit_band(self):
        """The other branch of the same sentence, so the fix above cannot
        silently rename the winner an operator actually typed."""
        from bot_program.share_allocator import propose_share_plan
        _report("mean_reverting", at=timezone.now() - timedelta(hours=1))
        s = _follower(self.user, name="sw", persona="swing", share=50,
                      share_floor_pct=10, share_ceiling_pct=70)
        _follower(self.user, name="plain", share=50)
        row = propose_share_plan(self.user).inputs[str(s.pk)]
        self.assertEqual((row["floor"], row["ceiling"]), (10.0, 70.0))
        self.assertEqual(row["mix"]["outranked_by"], "the explicit band")
        self.assertIn("not applied, the explicit band wins", row["why"])


class TheRegimeIsReadOncePerProposalTests(TestCase):
    """One reading for the whole plan.

    Two followers that read two BrainReports inside one proposal could be
    sized against two different tapes, and a per-config read would repeat
    the eighteen-cell record for every pool on the account.
    """

    def setUp(self):
        self.user = _user("once")
        _acct(self.user)

    def test_current_mix_is_called_exactly_once_however_many_followers(self):
        from unittest.mock import patch

        import bot_program.persona_mix as pm
        from bot_program.share_allocator import propose_share_plan
        _report("mean_reverting", at=timezone.now() - timedelta(hours=1))
        made = []
        for i, key in enumerate(("scalp", "swing", "position", "swing")):
            made.append(_follower(self.user, name=f"f{i}", persona=key,
                                  share=25))
        with patch("bot_program.persona_mix.current_mix",
                   wraps=pm.current_mix) as spy:
            plan = propose_share_plan(self.user)
        self.assertIsNotNone(plan)
        self.assertEqual(spy.call_count, 1,
                         "the regime is read once per PROPOSAL, never once "
                         "per config — four followers must not read four "
                         "regimes")
        # And the one reading reached every one of them.
        for cfg in made:
            row = plan.inputs[str(cfg.pk)]
            self.assertEqual(row["mix"]["regime"], "mean_reverting")

    def test_the_matrix_costs_a_bounded_number_of_queries(self):
        """Eighteen cells must not cost eighteen passes over the trades.

        One BrainReport read, one pass over the configs, then per persona
        its fills and the regime stretches those fills opened in.
        """
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        from bot_program.persona_mix import current_mix
        now = timezone.now()
        _report("trending", at=now - timedelta(days=3))
        for i, key in enumerate(("scalp", "swing", "position")):
            cfg = _follower(self.user, name=f"g{i}", persona=key, share=30)
            for j in range(3):
                _fill(cfg, Decimal("0.5"),
                      opened=now - timedelta(days=2, hours=j), paper=False)
        with CaptureQueriesContext(connection) as ctx:
            current_mix(self.user)
        n = len(ctx.captured_queries)
        self.assertLessEqual(n, 8, f"the mix cost {n} queries — the matrix "
                                   f"is one report, one config pass and two "
                                   f"per persona, not one per cell")


class TheNoPersonaNumbersArePinnedTests(TestCase):
    """Not "the same as the other run" — THE NUMBERS, written out.

    A regression that moved both runs of a before/after comparison
    together would satisfy that comparison and nothing else. These are
    the targets the allocator proposes for a persona-less fleet, typed
    out from the arithmetic the module documents: two followers at 40%
    and 60%, every factor 1.0, the water-fill a no-op inside the 2–60%
    defaults, the half-way smoothing a no-op, and the hysteresis holding
    each at exactly its current share.
    """

    def setUp(self):
        self.user = _user("pinned")
        _acct(self.user)

    def test_the_targets_are_exactly_forty_and_sixty(self):
        from bot_program.share_allocator import propose_share_plan
        # mean_reverting is the loudest column in the prior table.
        _report("mean_reverting", at=timezone.now() - timedelta(hours=1))
        a = _follower(self.user, name="a", share=40)
        b = _follower(self.user, name="b", share=60)
        plan = propose_share_plan(self.user)
        self.assertIsNotNone(plan)
        self.assertAlmostEqual(float(plan.targets[str(a.pk)]), 40.0, places=6)
        self.assertAlmostEqual(float(plan.targets[str(b.pk)]), 60.0, places=6)
        for cfg in (a, b):
            row = plan.inputs[str(cfg.pk)]
            self.assertEqual((row["floor"], row["ceiling"]), (2.0, 60.0))
            self.assertTrue(row["held"])
            self.assertEqual(row["persona"], "")
            self.assertNotIn("mix", row)
            self.assertNotIn("mix", row["why"])

    def test_a_no_persona_config_on_a_mixed_fleet_carries_no_mix_row(self):
        """Half the fleet wears a personality and the other half does not.

        The bare pool still gets no factor, no 'mix' key and the
        platform's own default band: the mix reads a persona or it reads
        nothing. Its TARGET can still move — an account is one pool and
        the water-fill shares one hundred points across everything on it,
        exactly as a sibling's declared persona band already moved it
        before the mix existed. What must never happen is the mix being
        APPLIED to a config that wears nothing.
        """
        from bot_program.share_allocator import (DEFAULT_CEILING_PCT,
                                                 DEFAULT_FLOOR_PCT,
                                                 propose_share_plan)
        _report("mean_reverting", at=timezone.now() - timedelta(hours=1))
        worn = _follower(self.user, name="sw", persona="swing", share=50)
        bare = _follower(self.user, name="plain", share=50)
        plan = propose_share_plan(self.user)
        bare_row = plan.inputs[str(bare.pk)]
        self.assertNotIn("mix", bare_row)
        self.assertEqual(bare_row["persona"], "")
        self.assertEqual((bare_row["floor"], bare_row["ceiling"]),
                         (DEFAULT_FLOOR_PCT, DEFAULT_CEILING_PCT))
        self.assertNotIn("mix", bare_row["why"])
        self.assertTrue(plan.inputs[str(worn.pk)]["mix"]["applied"])


class NoFactorMovesABandFurtherThanTheCapTests(TestCase):
    """The bound, over every band and every factor the module can make.

    `shift_band` clamps the shift and then REPAIRS a band that fell off
    the end of the account by moving both of its ends — a second move,
    after the clamp. This asserts the two together still land inside
    MAX_BAND_SHIFT_PCT, so no path through that function can hand the
    allocator a band the operator was never told about.
    """

    def test_the_centre_never_moves_more_than_the_cap_for_any_band(self):
        from bot_program.persona_mix import (MAX_BAND_SHIFT_PCT, MAX_TILT,
                                             shift_band)
        bands = [(5.0, 25.0), (20.0, 60.0), (15.0, 50.0), (2.0, 60.0),
                 (0.5, 4.0), (80.0, 99.0), (1.0, 100.0), (40.0, 40.0),
                 (0.01, 0.02)]
        factors = [1.0 - MAX_TILT, 0.85, 0.91, 1.0, 1.09, 1.15,
                   1.0 + MAX_TILT]
        for lo, hi in bands:
            for f in factors:
                nlo, nhi = shift_band(lo, hi, f)
                moved = abs(((nlo + nhi) / 2.0) - ((lo + hi) / 2.0))
                self.assertLessEqual(
                    moved, MAX_BAND_SHIFT_PCT + 1e-6,
                    f"{lo}-{hi} at ×{f} moved its centre {moved:.4f} pt")
                self.assertAlmostEqual(
                    nhi - nlo, hi - lo, places=6,
                    msg=f"{lo}-{hi} at ×{f} changed width")
                self.assertTrue(0.0 < nlo <= nhi <= 100.0,
                                f"{lo}-{hi} at ×{f} -> {nlo}/{nhi} is a band "
                                f"bounds_for would refuse")


class TheThreeSurfacesPrintOneFactorTests(TestCase):
    """The plan, the page and the command, on the same measured cell.

    Three readers of one number is three places it can drift. They all go
    through `current_mix`; this is the test that says so out loud, and it
    compares the SENTENCE, not a rounded figure, so a surface that
    recomputed the cell its own way would be caught even if its rounding
    happened to agree.
    """

    def setUp(self):
        self.user = _user("agree")
        _acct(self.user)

    def test_the_plan_the_page_and_the_command_agree_on_a_measured_cell(self):
        from io import StringIO

        from django.core.management import call_command
        from django.urls import reverse

        from bot_program.evidence import MIN_EVIDENCE_N
        from bot_program.share_allocator import propose_share_plan
        now = timezone.now()
        _report("trending", at=now - timedelta(days=10))
        s = _follower(self.user, name="sw", persona="swing", share=60)
        _follower(self.user, name="b", share=40)
        for i in range(MIN_EVIDENCE_N):
            _fill(s, Decimal("0.4"), opened=now - timedelta(days=5, hours=i),
                  paper=False)
        plan = propose_share_plan(self.user)
        cell = plan.inputs[str(s.pk)]["mix"]
        self.assertEqual(cell["lane"], "measured")
        self.assertEqual(cell["n"], MIN_EVIDENCE_N)
        reason, printed = cell["reason"], f"{float(cell['factor']):.2f}"

        out = StringIO()
        call_command("persona", "mix", stdout=out)
        body = out.getvalue()
        self.assertIn(f"{printed}*n{MIN_EVIDENCE_N}", body)
        self.assertIn(reason, body)

        self.client.force_login(self.user)
        page = self.client.get(reverse("personas_dashboard")).content.decode()
        self.assertIn(f"measured n={MIN_EVIDENCE_N}", page)
        self.assertIn(reason, page,
                      "the page must print the sentence the plan acted on, "
                      "not one it worked out for itself")


class TheBoundaryOfAStretchTests(TestCase):
    """The half-open edge, to the microsecond.

    The stretches are [from, to): a report is in force AT its own
    timestamp. An off-by-one here would file every trade that opened on
    the half-hour — the moment the synthesizer writes — into the regime
    that had just ended.
    """

    def test_a_trade_opened_at_the_exact_instant_of_a_report_reads_it(self):
        from bot_program.persona_mix import (labels_in_series, regime_at,
                                             regime_series)
        now = timezone.now()
        flip = now - timedelta(days=3)
        _report("mean_reverting", at=now - timedelta(days=9))
        _report("trending", at=flip)
        series = regime_series(now - timedelta(days=9), now)
        tick = timedelta(microseconds=1)
        self.assertEqual(labels_in_series(series, [flip])[0], "trending")
        self.assertEqual(labels_in_series(series, [flip - tick])[0],
                         "mean_reverting")
        self.assertEqual(labels_in_series(series, [flip + tick])[0],
                         "trending")
        # The bisect and the single-row reader agree at the edge too.
        self.assertEqual(regime_at(flip), "trending")
        self.assertEqual(regime_at(flip - tick), "mean_reverting")
        # No zero-width stretch anywhere, including the last one — a
        # bisect landing inside one would answer for a window of no time.
        self.assertEqual(series[-1][1], now)
        for a_from, a_to, _l, _c in series:
            self.assertLess(a_from, a_to)
