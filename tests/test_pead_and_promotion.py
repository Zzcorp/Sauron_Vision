"""Post-earnings drift as a held position, and why a seeded strategy is silent.

Two things that had nothing to do with each other until you tried to use the
first one.

PEAD (`signals.evaluators_advanced._eval_pead`). The event family this platform
had — earnings_surprise, news_volume, calendar_event — could only express a
same-day reaction. `pead` is the first leg whose thesis is the HOLDING PERIOD,
so the tests here are as much about what it refuses as about what it fires on:

  - a print inside its own reaction window is not traded
  - a print the calendar has SCHEDULED but that has not happened is invisible,
    however completely its row is filled in — this is the lookahead case, and
    the table's whole purpose is to hold future rows
  - a blank `actual` is not an EPS of zero
  - a zero estimate is not an infinite surprise
  - the three quantities the literature sorts on and this schema cannot supply
    are reported as None with the reason, never substituted
  - the volume leg beside it averages bars from BEFORE the print, so the
    multiple the seed states means the same thing on day five of the entry
    window as it does on day one

Promotion visibility (`dashboard.views._trade_gates`). `OpportunitySetup
.is_active` seeds False and `RuleControl.promotion_stage` seeds "research",
which `rule_actuator.stage_policy` resolves to may_trade=False. So a freshly
seeded strategy cannot trade, by design — and no page said so, which is a
different bug from the design. The operator armed a strategy, watched nothing
happen, and had nowhere to learn which of the two switches was holding it.
Covered here: the card names both, names them only when they apply, and the
page's restatement of `stage_policy` is asserted equal to the real thing.

Run with:  python manage.py test tests.test_pead_and_promotion
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone


# A pinned instant, because every assertion here is about the distance in hours
# between a print and a scan. `timezone.now()` would make the age of the
# fixture depend on the clock the suite happens to run on.
NOW = datetime(2026, 3, 12, 12, 0, tzinfo=dt_timezone.utc)
# 21:00Z is what `earnings_calendar._SESSION_UTC` maps FMP's "amc" to, so the
# fixture prints at the hour the scraper would really have written.
PRINT_AT = datetime(2026, 3, 10, 21, 0, tzinfo=dt_timezone.utc)


# ── Fixtures ──────────────────────────────────────────────────────────────

def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _daily_bars(instrument, closes, volumes, last_day):
    """One bar per calendar day at 00:00Z, oldest first, ending on `last_day`.

    Timestamped at the start of the session on purpose: that is how a daily bar
    reaches PriceData, and it is the reason `_move_since_print` splits on the
    print's DAY rather than on its timestamp.
    """
    from market_data.models import PriceData
    day = last_day.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for i, (c, v) in enumerate(zip(closes, volumes)):
        ts = day - timedelta(days=len(closes) - 1 - i)
        rows.append(PriceData(
            instrument=instrument, timeframe="1d", timestamp=ts,
            open=Decimal(str(c)), high=Decimal(str(c)), low=Decimal(str(c)),
            close=Decimal(str(c)), volume=int(v), source="test"))
    PriceData.objects.bulk_create(rows)


def _drift_tape(symbol="PEADCO", *, gap_to=118.0, tail=(119.0, 120.0)):
    """Sixty rising daily bars, then an earnings gap and two days of drift.

    The last three bars are the print day and the two after it, which is the
    window the seeded setup enters in.
    """
    inst = _instrument(symbol)
    closes = [100.0 + 0.2 * i for i in range(57)] + [gap_to, *tail]
    volumes = [1000] * 57 + [5000, 2500, 2000]
    _daily_bars(inst, closes, volumes, NOW)
    return inst


def _drift_tape_at(symbol, *, post_closes, post_volumes, quiet_volume=1000):
    """A quiet rising tape, then the print day and every session after it.

    `post_closes[0]` and `post_volumes[0]` are the PRINT DAY's own bar, so the
    length of those tuples says how deep into the entry window a scan at NOW
    is landing. The tape is padded to sixty bars because the volume leg wants
    twenty of them plus the offset that keeps the average clear of the print.
    """
    inst = _instrument(symbol)
    quiet = 60 - len(post_closes)
    closes = [100.0 + 0.2 * i for i in range(quiet)] + list(post_closes)
    volumes = [quiet_volume] * quiet + list(post_volumes)
    _daily_bars(inst, closes, volumes, NOW)
    return inst


def _print_instant(n_post_bars):
    """The 21:00Z print whose calendar day owns the first of `n_post_bars`."""
    return (NOW.replace(hour=21, minute=0, second=0, microsecond=0)
            - timedelta(days=n_post_bars - 1))


def _earnings(symbol, when, actual, forecast, *, source="fmp"):
    """An EconomicEvent shaped exactly as `_persist_earnings` writes one."""
    from market_data.models import EconomicEvent
    return EconomicEvent.objects.create(
        source=source, title=f"{symbol} Earnings", country="US",
        datetime=when, impact="high", currency_affected=symbol[:10],
        actual="" if actual is None else str(actual),
        forecast="" if forecast is None else str(forecast))


def _pead(inst, **params):
    from signals.evaluators_advanced import _eval_pead
    base = {"direction": "bullish", "min_surprise_pct": 10.0,
            "min_age_hours": 24, "max_age_days": 5}
    return _eval_pead({**base, **params}, inst, NOW)


# ══════════════════════════════════════════════════════════════════════════
# 1. PEAD — what it fires on
# ══════════════════════════════════════════════════════════════════════════

class PeadMatchTests(TestCase):
    def test_a_beat_held_past_its_reaction_bar_matches(self):
        inst = _drift_tape("PEAD_HIT")
        _earnings("PEAD_HIT", PRINT_AT, 1.25, 1.00)
        r = _pead(inst)
        self.assertTrue(r["matched"])
        d = r["details"]
        self.assertAlmostEqual(d["surprise_pct"], 25.0, places=4)
        self.assertAlmostEqual(d["age_hours"], 39.0, places=2)
        self.assertEqual(d["printed_at"], PRINT_AT.isoformat())
        # 39h into a 24h..120h window.
        self.assertAlmostEqual(d["freshness_term"], (120 - 39) / 96, places=3)
        # 25% against a 10% bar is past the doubling point, so the size term
        # is capped rather than proportional.
        self.assertEqual(d["size_term"], 1.0)

    def test_the_move_it_reports_is_the_one_since_the_print(self):
        """Endpoints, not just a percentage: the split is on the print's DAY,
        so the reaction session is on the far side of it."""
        inst = _drift_tape("PEAD_MOVE")
        _earnings("PEAD_MOVE", PRINT_AT, 1.25, 1.00)
        d = _pead(inst)["details"]
        # bars[56] is 2026-03-09, the last session before the print day.
        self.assertAlmostEqual(d["pre_print_close"], 111.2, places=6)
        self.assertAlmostEqual(d["last_close"], 120.0, places=6)
        self.assertAlmostEqual(d["move_since_print_pct"],
                               (120.0 / 111.2 - 1) * 100, places=3)
        self.assertEqual(d["n_bars_since_print"], 3)

    def test_the_score_decays_across_the_entry_window(self):
        """Same surprise, later entry: the drift already given away is not
        worth what the drift still to come is."""
        early = _drift_tape("PEAD_EARLY")
        _earnings("PEAD_EARLY", NOW - timedelta(hours=30), 1.25, 1.00)
        late = _drift_tape("PEAD_LATE")
        _earnings("PEAD_LATE", NOW - timedelta(hours=110), 1.25, 1.00)
        self.assertGreater(_pead(early)["score"], _pead(late)["score"])
        self.assertTrue(_pead(late)["matched"], "the late one still matched")

    def test_a_bearish_leg_wants_a_miss_not_a_beat(self):
        inst = _drift_tape("PEAD_DIR")
        _earnings("PEAD_DIR", PRINT_AT, 1.25, 1.00)
        r = _pead(inst, direction="bearish")
        self.assertFalse(r["matched"])
        self.assertIn("bearish", r["details"]["reason"])


# ══════════════════════════════════════════════════════════════════════════
# 2. PEAD — what it refuses, and how honestly
# ══════════════════════════════════════════════════════════════════════════

class PeadRefusalTests(TestCase):
    def test_a_print_inside_its_own_reaction_is_not_traded(self):
        """The announcement bar is the trade this leg exists NOT to take."""
        inst = _drift_tape("PEAD_FRESH")
        _earnings("PEAD_FRESH", NOW - timedelta(hours=6), 1.25, 1.00)
        r = _pead(inst)
        self.assertFalse(r["matched"])
        self.assertIn("reaction", r["details"]["reason"])
        # Not measured, and therefore None — the window decides on the calendar
        # alone and price was never read.
        self.assertIsNone(r["details"]["move_since_print_pct"])

    def test_a_print_past_the_window_is_late_not_wrong(self):
        inst = _drift_tape("PEAD_STALE")
        _earnings("PEAD_STALE", NOW - timedelta(days=9), 1.25, 1.00)
        r = _pead(inst)
        self.assertFalse(r["matched"])
        self.assertIn("late", r["details"]["reason"])
        # The surprise is still reported: the print was real, it is the ENTRY
        # that is refused, and a card that hid the number would say otherwise.
        self.assertAlmostEqual(r["details"]["surprise_pct"], 25.0, places=4)

    def test_a_scheduled_print_is_invisible_however_full_its_row_is(self):
        """LOOKAHEAD. This table's purpose is to hold FUTURE rows — the
        calendar fetches [today, today+14] — so an unbounded "latest earnings"
        query returns a print that has not happened."""
        inst = _drift_tape("PEAD_AHEAD")
        _earnings("PEAD_AHEAD", NOW + timedelta(days=2), 9.99, 1.00)
        r = _pead(inst)
        self.assertFalse(r["matched"])
        self.assertEqual(r["details"]["n_rows"], 0)
        self.assertIsNone(r["details"]["surprise_pct"])

    def test_the_past_print_is_used_even_when_a_louder_one_is_scheduled(self):
        inst = _drift_tape("PEAD_BOTH")
        _earnings("PEAD_BOTH", PRINT_AT, 1.25, 1.00)
        _earnings("PEAD_BOTH", NOW + timedelta(days=30), 9.99, 1.00)
        d = _pead(inst)["details"]
        self.assertEqual(d["printed_at"], PRINT_AT.isoformat())
        self.assertAlmostEqual(d["surprise_pct"], 25.0, places=4)

    def test_a_blank_actual_is_not_an_eps_of_zero(self):
        """`float(raw or 0)` would read "not reported yet" as "earned nothing"
        — a total miss against a positive estimate, pointing short."""
        inst = _drift_tape("PEAD_BLANK")
        _earnings("PEAD_BLANK", PRINT_AT, None, 1.00)
        r = _pead(inst, direction="bearish")
        self.assertFalse(r["matched"])
        self.assertIsNone(r["details"]["surprise_pct"])
        self.assertFalse(r["details"]["measured"])
        self.assertEqual(r["details"]["n_rows"], 1)
        self.assertIn("backfill", r["details"]["reason"])

    def test_a_zero_estimate_is_not_an_infinite_surprise(self):
        inst = _drift_tape("PEAD_ZERO")
        _earnings("PEAD_ZERO", PRINT_AT, 0.40, 0.00)
        r = _pead(inst)
        self.assertFalse(r["matched"])
        self.assertIsNone(r["details"]["surprise_pct"])

    def test_another_issuers_row_carrying_the_ticker_is_not_this_ones_print(self):
        """A one-letter ticker is a substring of half the calendar's titles.
        The blackout accepts the symbol that loosely and is right to — a false
        match there declines a trade — while here it would take one, so the
        title is matched whole. "FDX Earnings" is the case that separates
        them: it satisfies a substring test on "F" and belongs to someone
        else."""
        inst = _drift_tape("F")
        _earnings("FDX", PRINT_AT, 9.99, 1.00)
        from market_data.models import EconomicEvent
        EconomicEvent.objects.create(
            source="fmp", title="US Nonfarm Payrolls", country="US",
            datetime=PRINT_AT, impact="high", currency_affected="USD",
            actual="250", forecast="180")
        r = _pead(inst)
        self.assertFalse(r["matched"])
        self.assertEqual(r["details"]["n_rows"], 0)

    def test_a_beat_the_market_faded_does_not_clear_the_move_leg(self):
        inst = _drift_tape("PEAD_FADE", gap_to=104.0, tail=(102.0, 100.0))
        _earnings("PEAD_FADE", PRINT_AT, 1.25, 1.00)
        r = _pead(inst, min_move_pct=1.0)
        self.assertFalse(r["matched"])
        self.assertLess(r["details"]["move_since_print_pct"], 0)
        self.assertIn("not moved with the surprise", r["details"]["reason"])

    def test_an_unmeasured_move_cannot_satisfy_a_requirement_about_the_move(self):
        """The one branch where reading None as 0.0 would be a trade rather
        than a missing number."""
        inst = _instrument("PEAD_NOBARS")
        _earnings("PEAD_NOBARS", PRINT_AT, 1.25, 1.00)
        r = _pead(inst, min_move_pct=1.0)
        self.assertFalse(r["matched"])
        self.assertIsNone(r["details"]["move_since_print_pct"])
        self.assertIn("not measured", r["details"]["reason"])

    def test_an_empty_entry_window_is_named_rather_than_silently_dark(self):
        inst = _drift_tape("PEAD_WINDOW")
        _earnings("PEAD_WINDOW", PRINT_AT, 1.25, 1.00)
        r = _pead(inst, min_age_hours=48, max_age_days=1)
        self.assertFalse(r["matched"])
        self.assertIn("empty entry window", r["details"]["reason"])

    def test_a_bad_direction_is_refused_not_flipped(self):
        inst = _drift_tape("PEAD_BADDIR")
        _earnings("PEAD_BADDIR", PRINT_AT, 1.25, 1.00)
        r = _pead(inst, direction="up")
        self.assertFalse(r["matched"])
        self.assertIn("unknown direction", r["details"]["reason"])


class PeadHonestyTests(TestCase):
    """What the schema cannot supply is reported as None, with the reason."""

    def setUp(self):
        self.inst = _drift_tape("PEAD_HONEST")
        _earnings("PEAD_HONEST", PRINT_AT, 1.25, 1.00)

    def test_the_three_unmeasurable_quantities_are_none_on_a_match(self):
        d = _pead(self.inst)["details"]
        for key in ("surprise_percentile", "pre_announcement_drift_pct",
                    "announcement_reaction_pct"):
            with self.subTest(key=key):
                self.assertIn(key, d)
                self.assertIsNone(d[key])
        self.assertIn("SUE", d["unmeasured_because"])

    def test_the_refusal_is_checkable_rather_than_asserted(self):
        """A percentile needs a history. The count of prior prints carrying an
        EPS pair is reported so a reader can see there is none."""
        d = _pead(self.inst)["details"]
        self.assertEqual(d["n_prior_prints_with_eps"], 0)
        _earnings("PEAD_HONEST", PRINT_AT - timedelta(days=91), 1.10, 1.00)
        self.assertEqual(_pead(self.inst)["details"]["n_prior_prints_with_eps"], 1)

    def test_a_newer_print_with_no_eps_yet_is_a_data_gap_not_a_quiet_market(self):
        _earnings("PEAD_HONEST", NOW - timedelta(hours=2), None, 1.30)
        d = _pead(self.inst)["details"]
        self.assertEqual(d["n_newer_prints_without_eps"], 1)
        self.assertEqual(d["printed_at"], PRINT_AT.isoformat())


# ══════════════════════════════════════════════════════════════════════════
# 3. The seeded setup — registered, horizon-legal, and it actually fires
# ══════════════════════════════════════════════════════════════════════════

class PeadSeedTests(TestCase):
    def _spec(self):
        from signals.management.commands.seed_advanced_strategies import (
            _setup_definitions,
        )
        return next(s for s in _setup_definitions()
                    if s["name"] == "advanced_pead_drift_long")

    def test_the_kind_is_registered_and_listed(self):
        from signals.opportunity_scanner import has_kind
        from signals.evaluators_advanced import ADVANCED_EVALUATORS
        self.assertTrue(has_kind("pead"))
        self.assertIn("pead", ADVANCED_EVALUATORS)

    def test_a_setup_carries_it_into_the_lane_that_can_trade(self):
        """An evaluator no setup carries is still missing from trading."""
        spec = self._spec()
        self.assertIn("pead", {c["kind"] for c in spec["conditions"]})
        self.assertEqual(spec["asset_classes"], ["stock"])

    def test_its_horizon_fits_the_stock_class_time_stop(self):
        """A setup whose horizon outlives its class ceiling is flattened with
        reason TIME before its own thesis can resolve, and every winner is
        recorded as an exit the thesis never asked for."""
        from bot_program.asset_models import DEFAULT_MAX_HOLD_HOURS
        spec = self._spec()
        horizon_hours = spec["suggested_horizon_days"] * 24.0
        for asset_class in spec["asset_classes"]:
            with self.subTest(asset_class=asset_class):
                self.assertLess(
                    horizon_hours, DEFAULT_MAX_HOLD_HOURS[asset_class],
                    "the ceiling must OUTLIVE the horizon, not equal it — a "
                    "ceiling equal to the horizon cuts the trade at the "
                    "instant the horizon resolves")

    def test_the_seeded_leg_concedes_the_gap_and_asks_price_to_agree(self):
        """The two params that make this a DRIFT setup rather than an
        earnings-reaction one: entry a full day after the print, and a move
        since it that points the same way as the surprise."""
        params = {c["kind"]: c.get("params", {})
                  for c in self._spec()["conditions"]}["pead"]
        self.assertGreaterEqual(params["min_age_hours"], 24)
        self.assertGreater(params["min_move_pct"], 0)

    def test_the_seeded_setup_fires_on_a_real_drift_tape(self):
        """End to end through `scan_setup`: the composite the scanner computes
        clears the bar the seed declares."""
        from signals.models_opportunity import OpportunitySetup
        from signals.opportunity_scanner import scan_setup
        spec = self._spec()
        inst = _drift_tape("PEAD_SCAN")
        _earnings("PEAD_SCAN", PRINT_AT, 1.25, 1.00)
        setup = OpportunitySetup.objects.create(
            name=spec["name"], description=spec["description"],
            direction=spec["direction"], asset_classes=spec["asset_classes"],
            conditions=spec["conditions"],
            min_match_score=spec["min_match_score"],
            suggested_horizon_days=spec["suggested_horizon_days"],
            sizing=spec["sizing"], is_active=True)
        res = scan_setup(setup, inst, now=NOW, emit=False)
        self.assertTrue(res["matched"], res)
        self.assertGreaterEqual(res["score"], spec["min_match_score"])

    def test_the_thesis_leg_cannot_carry_the_setup_alone(self):
        """A print nobody is trading is a print nobody is accumulating into —
        so a full-score surprise with volume back at average is refused."""
        from signals.models_opportunity import OpportunitySetup
        from signals.opportunity_scanner import scan_setup
        spec = self._spec()
        inst = _instrument("PEAD_QUIET")
        closes = [100.0 + 0.2 * i for i in range(57)] + [118.0, 119.0, 120.0]
        _daily_bars(inst, closes, [1000] * 60, NOW)
        _earnings("PEAD_QUIET", PRINT_AT, 1.25, 1.00)
        setup = OpportunitySetup.objects.create(
            name=spec["name"], description=spec["description"],
            direction=spec["direction"], asset_classes=spec["asset_classes"],
            conditions=spec["conditions"],
            min_match_score=spec["min_match_score"],
            suggested_horizon_days=spec["suggested_horizon_days"],
            sizing=spec["sizing"], is_active=True)
        res = scan_setup(setup, inst, now=NOW, emit=False)
        self.assertFalse(res["matched"], res)

    def test_it_still_fires_deep_into_the_window_it_declares(self):
        """Four days out, on twice the quiet tape, with a +25% beat. The
        volume leg had been reading that same tape at 1.44x, because its
        average ran through the print's own spike — so the later a scan
        landed, the more volume the setup demanded, on exactly the days its
        thesis says the drift is least crowded."""
        from signals.models_opportunity import OpportunitySetup
        from signals.opportunity_scanner import scan_setup
        spec = self._spec()
        inst = _drift_tape_at(
            "PEAD_DAY4",
            post_closes=(118.0, 119.0, 119.5, 120.0, 120.5),
            post_volumes=(5000, 2500, 2200, 2000, 2000))
        _earnings("PEAD_DAY4", _print_instant(5), 1.25, 1.00)
        setup = OpportunitySetup.objects.create(
            name=spec["name"], description=spec["description"],
            direction=spec["direction"], asset_classes=spec["asset_classes"],
            conditions=spec["conditions"],
            min_match_score=spec["min_match_score"],
            suggested_horizon_days=spec["suggested_horizon_days"],
            sizing=spec["sizing"], is_active=True)
        res = scan_setup(setup, inst, now=NOW, emit=False)
        self.assertTrue(res["matched"], res)
        self.assertGreaterEqual(res["score"], spec["min_match_score"])
        vol = next(c for c in res["conditions"]
                   if c["kind"] == "relative_volume")
        self.assertAlmostEqual(vol["details"]["ratio"], 2.0, places=4)


class PeadVolumeBaselineTests(TestCase):
    """The volume leg cannot measure the print against itself.

    `relative_volume` averages the bars sitting immediately behind the current
    one. Three days into this setup's entry window that average has already
    swallowed the announcement bar and the fat sessions trailing it, which
    lifts the divisor — so a leg written as 1.3x asks for close to 1.8x of the
    quiet tape, and asks for MORE the later the scan lands. `baseline_offset`
    moves the window back past the whole event stretch so the stated multiple
    means one thing on every day of the window.
    """

    def _conditions(self):
        from signals.management.commands.seed_advanced_strategies import (
            _setup_definitions,
        )
        spec = next(s for s in _setup_definitions()
                    if s["name"] == "advanced_pead_drift_long")
        return {c["kind"]: c for c in spec["conditions"]}

    def _leg_params(self):
        return dict(self._conditions()["relative_volume"]["params"])

    def test_the_offset_clears_the_print_bar_from_the_last_day_of_the_window(self):
        """One daily bar per calendar day, so `max_age_days` bounds how many
        bars a scan can sit past the print; the print's own bar is the one
        beyond that. An offset short of the sum would put the announcement
        back in the average on the oldest entries the setup accepts."""
        conds = self._conditions()
        self.assertGreaterEqual(
            self._leg_params()["baseline_offset"],
            conds["pead"]["params"]["max_age_days"] + 1)

    def test_the_average_is_taken_from_before_the_print(self):
        from signals.evaluators_advanced import _eval_relative_volume
        inst = _drift_tape_at(
            "PEAD_BASE",
            post_closes=(118.0, 119.0, 119.5, 120.0, 120.5),
            post_volumes=(5000, 2500, 2200, 2000, 2000))
        d = _eval_relative_volume(self._leg_params(), inst, NOW)["details"]
        self.assertEqual(d["avg_volume"], 1000.0)
        self.assertAlmostEqual(d["ratio"], 2.0, places=4)

    def test_an_average_that_runs_through_the_print_asks_for_far_more(self):
        """The defect, measured rather than asserted: the same bar reads 1.44x
        instead of 2x, which is the seeded 1.3x demanding 1.8x of the tape it
        was written against."""
        from signals.evaluators_advanced import _eval_relative_volume
        inst = _drift_tape_at(
            "PEAD_INFLATED",
            post_closes=(118.0, 119.0, 119.5, 120.0, 120.5),
            post_volumes=(5000, 2500, 2200, 2000, 2000))
        params = self._leg_params()
        d = _eval_relative_volume({**params, "baseline_offset": 0},
                                  inst, NOW)["details"]
        self.assertAlmostEqual(d["ratio"], 1.4440, places=3)
        effective = params["threshold"] * d["avg_volume"] / 1000.0
        self.assertGreater(effective, 1.7)

    def test_a_late_entry_at_the_stated_multiple_clears_the_leg(self):
        """1.4x the quiet tape on day four is what 1.3 says it accepts. Read
        against a baseline holding the print it came to 1.03x and was refused
        — the half of the entry window this setup exists to trade."""
        from signals.evaluators_advanced import _eval_relative_volume
        inst = _drift_tape_at(
            "PEAD_LATE_VOL",
            post_closes=(118.0, 119.0, 119.5, 120.0, 120.5),
            post_volumes=(5000, 2500, 2000, 1700, 1400))
        params = self._leg_params()
        self.assertTrue(_eval_relative_volume(params, inst, NOW)["matched"])
        self.assertFalse(_eval_relative_volume(
            {**params, "baseline_offset": 0}, inst, NOW)["matched"])

    def test_the_offset_is_opt_in_and_absent_means_the_old_window(self):
        """Every other seeded volume leg reads a spike ON the event bar, where
        an offset would push the average away from the tape it should compare
        to. Defaulting to zero is what keeps this a PEAD repair rather than a
        silent change to the three other setups carrying this kind and to the
        anomaly scanner's RVOL detector."""
        from signals.evaluators_advanced import _eval_relative_volume
        inst = _drift_tape_at(
            "PEAD_DEFAULT",
            post_closes=(118.0, 119.0, 119.5, 120.0, 120.5),
            post_volumes=(5000, 2500, 2200, 2000, 2000))
        plain = _eval_relative_volume({"period": 20, "threshold": 1.3},
                                      inst, NOW)["details"]
        explicit = _eval_relative_volume(
            {"period": 20, "threshold": 1.3, "baseline_offset": 0},
            inst, NOW)["details"]
        self.assertEqual(plain["avg_volume"], explicit["avg_volume"])
        self.assertEqual(plain["baseline_offset"], 0)


# ══════════════════════════════════════════════════════════════════════════
# 4. Promotion visibility — both switches, on the page that lists setups
# ══════════════════════════════════════════════════════════════════════════

def _rule(name, stage="research", *, status="active", paused_until=None):
    from signals.models_control import RuleControl
    return RuleControl.objects.create(
        rule_name=name, status=status, promotion_stage=stage,
        stage_entered_at=timezone.now(), paused_until=paused_until)


def _setup_row(name, *, active=False):
    from signals.models_opportunity import OpportunitySetup
    return OpportunitySetup.objects.create(
        name=name, direction="bullish", asset_classes=["stock"],
        is_active=active,
        conditions=[{"kind": "price_pattern", "params": {"ma_period": 50}}])


class StageRestatementTests(TestCase):
    """The page restates `stage_policy` instead of calling it, to hold the
    ladder's fixed query budget. The restatement has to be the same rule."""

    def test_it_agrees_with_stage_policy_on_every_stage(self):
        from dashboard.views import _stage_verdict
        from signals.promotion_pipeline import STAGE_ORDER
        from signals.rule_actuator import stage_policy
        for stage in STAGE_ORDER:
            with self.subTest(stage=stage):
                _rule(f"verdict_{stage}", stage)
                real = stage_policy(f"verdict_{stage}")
                mine = _stage_verdict(stage)
                self.assertEqual(mine["may_trade"], real["may_trade"])
                self.assertEqual(mine["force_paper"], real["force_paper"])

    def test_it_agrees_on_a_stage_the_pipeline_does_not_recognise(self):
        """`stage_policy` falls back to PAPER rather than to silence, so a page
        drawing an unrecognised stage as "nothing happens" would be backwards."""
        from dashboard.views import _stage_verdict
        from signals.rule_actuator import stage_policy
        _rule("verdict_unknown", "banana")
        real = stage_policy("verdict_unknown")
        mine = _stage_verdict("banana")
        self.assertEqual(mine["may_trade"], real["may_trade"])
        self.assertEqual(mine["force_paper"], real["force_paper"])
        self.assertTrue(mine["may_trade"])
        self.assertFalse(mine["known"])


class TradeGateTests(TestCase):
    def _gates(self, ctrl, setup):
        from dashboard.views import _trade_gates
        return _trade_gates(ctrl, setup, timezone.now())

    def test_a_freshly_seeded_pair_names_both_switches(self):
        g = self._gates(_rule("fresh"), _setup_row("fresh", active=False))
        self.assertFalse(g["can_trade"])
        self.assertEqual([b["chip"] for b in g["blockers"]],
                         ["NOT SCANNED", "NO ORDERS"])
        for b in g["blockers"]:
            with self.subTest(chip=b["chip"]):
                self.assertTrue(b["fix"], "a blocker with no action is a dead end")

    def test_arming_alone_leaves_the_stage_holding_it(self):
        g = self._gates(_rule("armed_only"), _setup_row("armed_only", active=True))
        self.assertFalse(g["can_trade"])
        self.assertEqual([b["chip"] for b in g["blockers"]], ["NO ORDERS"])

    def test_promoting_alone_leaves_the_scanner_holding_it(self):
        g = self._gates(_rule("promoted_only", "paper"),
                        _setup_row("promoted_only", active=False))
        self.assertFalse(g["can_trade"])
        self.assertEqual([b["chip"] for b in g["blockers"]], ["NOT SCANNED"])

    def test_both_cleared_and_the_paper_venue_is_still_stated(self):
        g = self._gates(_rule("both", "paper"), _setup_row("both", active=True))
        self.assertTrue(g["can_trade"])
        self.assertEqual(g["blockers"], [])
        self.assertTrue(any("paper venue" in c for c in g["caveats"]))

    def test_a_rule_with_no_setup_is_not_given_a_switch_it_has_not_got(self):
        """Its conditions live in engine code — there is no arming flag to
        find, and printing DISARMED would send the operator hunting for one."""
        g = self._gates(_rule("code_rule", "live_full"), None)
        self.assertIsNone(g["armed"])
        self.assertTrue(g["can_trade"])
        self.assertEqual(g["blockers"], [])

    def test_a_paused_engine_rule_says_its_signals_are_dropped(self):
        ctrl = _rule("paused_code_rule", "live_full", status="paused")
        g = self._gates(ctrl, None)
        self.assertFalse(g["can_trade"])
        self.assertEqual([b["chip"] for b in g["blockers"]], ["SIGNALS DROPPED"])

    def test_a_pause_does_not_claim_to_stop_a_setup_backed_rule(self):
        """The asymmetry is real: `is_rule_active` is read where the rule
        engine writes signals and nowhere else — not by the opportunity
        scanner, not by `stage_policy`, and `admin_allocator_multiplier`
        honours weight_multiplier only when status == "reduced". Saying
        "paused, therefore stopped" would be the page lying."""
        ctrl = _rule("paused_setup_rule", "live_full", status="paused")
        g = self._gates(ctrl, _setup_row("paused_setup_rule", active=True))
        self.assertTrue(g["can_trade"])
        self.assertEqual(g["blockers"], [])
        self.assertTrue(any("keeps scanning" in c for c in g["caveats"]))

    def test_an_elapsed_pause_is_not_a_pause(self):
        ctrl = _rule("elapsed", "live_full", status="paused",
                     paused_until=timezone.now() - timedelta(days=1))
        g = self._gates(ctrl, None)
        self.assertTrue(g["can_trade"])
        self.assertEqual(g["caveats"], [])


class StrategiesPagePromotionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("promo_u", password="x")

    def setUp(self):
        self.client.force_login(self.user)

    def _get(self):
        return self.client.get(reverse("strategies_list"), HTTP_HOST="127.0.0.1")

    def _cards(self, resp):
        return {c["rule"]: c for g in resp.context["stage_groups"]
                for c in g["cards"]}

    def test_a_seeded_pack_says_on_the_page_that_none_of_it_can_trade(self):
        from signals.management.commands.seed_advanced_strategies import seed_setups
        seed_setups(activate=False)
        resp = self._get()
        self.assertEqual(resp.context["n_can_trade"], 0)
        self.assertGreater(resp.context["n_rules"], 0)
        for name, card in self._cards(resp).items():
            with self.subTest(rule=name):
                self.assertFalse(card["trade"]["can_trade"])
                self.assertEqual(
                    [b["chip"] for b in card["trade"]["blockers"]],
                    ["NOT SCANNED", "NO ORDERS"])

    def test_the_card_prints_the_field_and_the_action_that_clears_it(self):
        _rule("visible_rule")
        _setup_row("visible_rule", active=False)
        body = self._get().content.decode("utf-8", "replace")
        one_line = " ".join(body.split())
        self.assertIn('data-can-trade="0"', body)
        self.assertIn("OpportunitySetup.is_active = False", one_line)
        self.assertIn("RuleControl.promotion_stage = research", one_line)
        self.assertIn("--activate", one_line)
        self.assertIn("promotion pipeline", one_line)

    def test_a_tradeable_rule_says_so_rather_than_going_quiet(self):
        _rule("live_rule", "live_full")
        _setup_row("live_rule", active=True)
        resp = self._get()
        self.assertEqual(resp.context["n_can_trade"], 1)
        body = resp.content.decode("utf-8", "replace")
        self.assertIn('data-can-trade="1"', body)
        # The chip, not the strip label — "MAY TRADE" heads a cell on every
        # render, so asserting the bare words would pass on a blocked card too.
        self.assertIn('<span class="sv-chip sv-chip--bullish">MAY TRADE</span>',
                      body)

    def test_the_headline_counts_ladder_rules_only(self):
        """An armed setup with no ladder row can also trade — `stage_policy`
        reads a missing row as paper — but it has no card, and folding it in
        would make this number irreconcilable with the stage counts beside it."""
        _rule("counted", "live_full")
        _setup_row("counted", active=True)
        _setup_row("orphan_armed", active=True)
        resp = self._get()
        self.assertEqual(resp.context["n_can_trade"], 1)
        self.assertEqual([s["name"] for s in resp.context["unbacked_setups"]],
                         ["orphan_armed"])

    def test_resolving_the_switches_costs_no_extra_query(self):
        """The ladder's budget is fixed at 7 whatever the rule count, which is
        why the page restates `stage_policy` instead of calling it per card."""
        from dashboard.views import _promotion_ladder
        for i in range(20):
            _rule(f"budget_pead_{i}")
            _setup_row(f"budget_pead_{i}", active=i % 2 == 0)
        with self.assertNumQueries(7):
            _promotion_ladder()
