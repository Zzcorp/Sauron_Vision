"""Plan 1.4, 1.5, 2.2 — the SMC card tells the truth about itself.

Three defects, one surface:

  1.4  The "30d hit" on every card was a literal dict copied from the
       strategy author's PDF (RP_BREAKER 0.76, RANGE_MSB_SD 0.61, ...). It
       was written to SmcSignal.rule_hit_rate_30d, rendered as the platform's
       own measured record, and fed into the conviction bonus that the feed
       sorts by — so on day one, with nothing closed, the dashboard ranked
       setups by a marketing number and called it evidence.

  1.5  persist_cards created a row unconditionally while every detector
       evaluates the LAST bar, so the 900s SignalEngine pass and the 1800s
       universe scan stored the same live setup roughly 18 times per 4h bar.
       Beyond the clutter: duplicates share a conviction, so one setup fills
       the feed, and they multiply n_closed, which is what decides whether a
       hit rate is empirical yet — five copies of one event flipped it.

  2.2  sessions.py, liquidity.find_equal_levels/detect_sfp and
       structure.premium_discount had ZERO callers repo-wide, and
       SETUP_CHOICES advertised an "SFP" no detector could emit.

Run with:  python manage.py test tests.test_smc_card_honesty
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.utils import timezone


# 12:00 UTC on a January day is 07:00 in New York: the dead hour between the
# London killzone (02:00-05:00 NY) and the New York AM one (08:30-11:00 NY).
# Tests isolating some other term trigger here so the killzone bonus stays out
# of the sum. The fixed-UTC table this slice stopped scoring from calls this
# same instant "ny_open" — see DaylightSavingDrift below.
BAR_ONE = datetime(2024, 1, 15, 12, 0, tzinfo=dt_timezone.utc)
BAR_TWO = BAR_ONE + timedelta(hours=4)

# 09:00 in New York, once in each season — the same hour of the same trading
# day, both inside the AM killzone, an hour apart in UTC. That gap is the
# whole reason the killzone term is anchored to New York.
WINTER_KILLZONE_BAR = datetime(2024, 1, 15, 14, 0, tzinfo=dt_timezone.utc)
SUMMER_KILLZONE_BAR = datetime(2024, 7, 15, 13, 0, tzinfo=dt_timezone.utc)


def _trail_total(reasons):
    """Sum the conviction terms a card lists, the way a reader would.

    Every line the scorers write ends in a signed number, except the "base N"
    opener and the lines that state a term was not measurable and therefore
    moved nothing. The card's own <summary> says "How this scored N/100", so
    this total is what the card is claiming — and it has to match.
    """
    import re

    total = 0
    for reason in reasons:
        if reason.startswith("base "):
            total += int(reason.split()[1])
            continue
        term = re.search(r"([+-]\d+)$", reason)
        if term:
            total += int(term.group(1))
    return total


# ── fixtures ────────────────────────────────────────────────────────────────

def _card(**over):
    """The shape scan_symbol hands to persist_cards."""
    card = {
        "symbol": "AAA", "timeframe": "4h",
        "setup": "OB_RETEST", "direction": "LONG",
        "headline": "AAA LONG · Order block retest · 4h",
        "thesis": "Unbroken order block being retested.",
        "why_now": "Order block 99.0-100.0 retested.",
        "invalidation": "close below 99.0000",
        "entry": 100.0, "stop": 99.0, "target": 103.0, "r_multiple": 3.0,
        "chips": {"structure": 1, "momentum": 0, "flow": 0,
                  "macro": 0, "sentiment": 0},
        "conviction": 60,
        "components": ["order_block", "retest"],
        "reasons": ["base 30", "1 confluence chip(s) +10"],
        "ict": {"killzone": "ny_open", "zone": "discount"},
        "hit_rate_30d": None, "hit_rate_n": 0,
        "trigger_ts": BAR_ONE,
    }
    card.update(over)
    return card


def _closed_signal(setup="RP_BREAKER", status="TARGET_HIT", realized_r=2.0,
                   bar=None):
    """A closed SmcSignal — the only thing a measured hit rate may count."""
    from signals.models_smc import SmcSignal
    return SmcSignal.objects.create(
        symbol="AAA", timeframe="4h", setup=setup, direction="SHORT",
        headline="h", thesis="t", why_now="w", invalidation="i",
        entry=100.0, stop=101.0, target=98.0, r_multiple=2.0,
        status=status, closed_at=timezone.now(), realized_r=realized_r,
        trigger_ts=bar,
    )


def _flat_frame(bars=120, start="2024-01-01 00:00"):
    """A quiet series: no pivots, no gaps, nothing for a detector to find."""
    import pandas as pd
    idx = pd.date_range(start, periods=bars, freq="4h", tz="UTC")
    return pd.DataFrame({
        "open": [100.0] * bars,
        "high": [100.5] * bars,
        "low": [99.5] * bars,
        "close": [100.0] * bars,
        "volume": [1000.0] * bars,
    }, index=idx)


def _sfp_frame():
    """A swing high at bar 100, and a last bar that fails to hold above it.

    The wick is 94% of the bar's range, well past the 0.6 that separates an
    SFP from an ordinary sweep, and the close is back under the swept swing.
    """
    df = _flat_frame()
    last = len(df) - 1
    df.iloc[90, df.columns.get_loc("low")] = 95.0     # swing low
    df.iloc[100, df.columns.get_loc("high")] = 105.0  # swing high to be taken
    df.iloc[last, df.columns.get_loc("high")] = 106.0
    df.iloc[last, df.columns.get_loc("low")] = 99.8
    df.iloc[last, df.columns.get_loc("open")] = 100.0
    df.iloc[last, df.columns.get_loc("close")] = 100.2
    return df


def _setup(**over):
    """A raw detector setup, the input side of evaluate_ict_context."""
    s = {
        "setup": "OB_RETEST", "direction": "LONG",
        "entry": 105.0, "stop": 99.0, "target": 115.0, "r_multiple": 1.7,
        "trigger_ts": BAR_ONE,
        "components": ["order_block", "retest"],
    }
    s.update(over)
    return s


# ── 1.4 — the hit rate is measured or it is absent ──────────────────────────

class PublishedPriorsAreGone(SimpleTestCase):
    def test_the_scanner_carries_no_table_of_per_setup_constants(self):
        """The literal `{"RP_BREAKER": 0.76, ...}` is the defect itself.

        Matched on shape rather than on the numbers, so the module docstring
        can keep naming them as the thing that was removed — and so the guard
        still fires if they come back as 76.0, or as expectancies, or under
        any other name.
        """
        import ast
        import inspect

        from signals.models_smc import SmcSignal
        from signals.rules import smc_rules

        names = dict(SmcSignal.SETUP_CHOICES)
        offenders = [
            ast.dump(node)[:120]
            for node in ast.walk(ast.parse(inspect.getsource(smc_rules)))
            if isinstance(node, ast.Dict)
            and any(isinstance(k, ast.Constant) and k.value in names
                    for k in node.keys)
        ]
        self.assertEqual(
            offenders, [],
            "a per-setup constant table is back in the scanner. The numbers "
            "that used to live there were the strategy author's published "
            "claims, and the card rendered them as this platform's own "
            "measured 30d record and sorted the feed by them: %r" % offenders)

    def test_a_card_with_no_evidence_reports_none(self):
        from signals.explain.formatter import build_card
        card = build_card(_setup(), "AAA", "4h", hit_rate=None, hit_rate_n=0)
        self.assertIsNone(card["hit_rate_30d"])
        self.assertEqual(card["hit_rate_n"], 0)
        self.assertTrue(any("not empirical yet" in r for r in card["reasons"]))

    def test_an_unmeasurable_record_is_not_a_zero(self):
        """n=None (could not read) must not read as n=0 (nothing closed)."""
        from signals.explain.formatter import build_card
        card = build_card(_setup(), "AAA", "4h", hit_rate=None, hit_rate_n=None)
        self.assertIsNone(card["hit_rate_n"])
        self.assertTrue(any("record unavailable" in r for r in card["reasons"]),
                        card["reasons"])

    def test_no_hit_rate_means_no_conviction_bonus(self):
        from signals.explain.formatter import score_conviction, CONVICTION_BASE
        chips = {"structure": 0, "momentum": 0, "flow": 0,
                 "macro": 0, "sentiment": 0}
        flat = _setup(r_multiple=0)
        unmeasured, _ = score_conviction(chips, flat, hit_rate=None, hit_rate_n=0)
        measured, _ = score_conviction(chips, flat, hit_rate=0.76, hit_rate_n=9)
        self.assertEqual(unmeasured, CONVICTION_BASE)
        self.assertGreater(
            measured, unmeasured,
            "a measured edge should lift conviction — but only a measured one")


class MeasuredHitRates(TestCase):
    def test_hit_rate_is_counted_from_closed_cards(self):
        from signals.rules.smc_rules import measured_hit_rates
        for i in range(3):
            _closed_signal(status="TARGET_HIT", realized_r=2.0,
                           bar=BAR_ONE + timedelta(hours=4 * i))
        for i in range(3, 6):
            _closed_signal(status="STOPPED", realized_r=-1.0,
                           bar=BAR_ONE + timedelta(hours=4 * i))
        rates = measured_hit_rates()
        self.assertEqual(rates["RP_BREAKER"], (0.5, 6))

    def test_a_thin_sample_is_not_a_hit_rate(self):
        """Two closed cards is noise wearing a percent sign."""
        from signals.rules.smc_rules import measured_hit_rates
        _closed_signal(status="TARGET_HIT", bar=BAR_ONE)
        _closed_signal(status="STOPPED", realized_r=-1.0, bar=BAR_TWO)
        hit_rate, n_closed = measured_hit_rates()["RP_BREAKER"]
        self.assertIsNone(hit_rate)
        self.assertEqual(n_closed, 2)

    def test_an_unreadable_record_reports_nothing_not_zero(self):
        from signals.rules import smc_rules
        with patch("signals.performance.setup_performance_summary",
                   side_effect=RuntimeError("db down")):
            self.assertIsNone(smc_rules.measured_hit_rates())

    def test_the_scan_stores_the_rate_and_the_sample_behind_it(self):
        from signals.models_smc import SmcSignal
        from signals.rules.smc_rules import persist_cards
        persist_cards([_card(hit_rate_30d=0.62, hit_rate_n=8)], "AAA", "4h")
        row = SmcSignal.objects.get()
        self.assertEqual(row.rule_hit_rate_30d, 0.62)
        self.assertEqual(row.rule_hit_rate_n, 8)

    def test_a_fresh_scan_persists_no_hit_rate_at_all(self):
        """End to end on an empty database: the feed's first cards are blank."""
        from signals.models_smc import SmcSignal
        from signals.rules.smc_rules import scan_symbol, persist_cards
        cards = scan_symbol("AAA", "4h", df=_sfp_frame())
        self.assertTrue(cards)
        persist_cards(cards, "AAA", "4h")
        for row in SmcSignal.objects.all():
            self.assertIsNone(row.rule_hit_rate_30d)
            self.assertEqual(row.rule_hit_rate_n, 0)


class PriorsAlreadyInTheDatabase(TestCase):
    """Deleting the table only stops NEW rows carrying it.

    Every value `rule_hit_rate_30d` holds on a deployed database was written
    by the one thing that ever set it — the PDF prior table in `scan_symbol`.
    The card template renders that column under a "Measured on N closed cards"
    tooltip, so a deploy that stops writing priors and leaves the stored ones
    alone goes on publishing 0.76 as this platform's own record. Migration
    0016 scrubs them; these are the two cases it has to tell apart.
    """

    def _clear(self):
        from importlib import import_module

        from django.apps import apps as app_registry
        migration = import_module(
            "signals.migrations.0016_smcsignal_dedupe_and_hit_rate_sample")
        # The real registry stands in for the migration's historical one: the
        # two fields this touches are identical in both.
        migration.clear_published_priors(app_registry, None)

    def _row(self, rate, sample, bar):
        from signals.models_smc import SmcSignal
        row = _closed_signal(bar=bar)
        SmcSignal.objects.filter(pk=row.pk).update(
            rule_hit_rate_30d=rate, rule_hit_rate_n=sample)
        return row

    def test_a_rate_with_no_sample_behind_it_is_cleared(self):
        row = self._row(0.76, None, BAR_ONE)
        self._clear()
        row.refresh_from_db()
        self.assertIsNone(
            row.rule_hit_rate_30d,
            "a hit rate with no sample size is a published prior — the "
            "sample column shipped in the same migration, so nothing this "
            "platform measured can be missing it")

    def test_a_measured_rate_survives(self):
        row = self._row(0.5, 9, BAR_TWO)
        self._clear()
        row.refresh_from_db()
        self.assertEqual(row.rule_hit_rate_30d, 0.5)
        self.assertEqual(row.rule_hit_rate_n, 9)

    def test_a_row_that_never_claimed_a_rate_is_untouched(self):
        row = self._row(None, 0, BAR_ONE + timedelta(hours=8))
        self._clear()
        row.refresh_from_db()
        self.assertIsNone(row.rule_hit_rate_30d)
        self.assertEqual(row.rule_hit_rate_n, 0)


class CardRendersTheGap(SimpleTestCase):
    """The template is where a missing measurement becomes visible."""

    def _render(self, **over):
        row = SimpleNamespace(
            direction="LONG", status="ACTIVE", setup="OB_RETEST",
            headline="AAA LONG", thesis="t", entry=100.0, stop=99.0,
            target=103.0, r_multiple=3.0, chip_structure=1, chip_momentum=0,
            chip_flow=0, chip_macro=0, chip_sentiment=0, conviction=60,
            invalidation="close below 99", reasons=["base 30"],
            rule_hit_rate_30d=None, rule_hit_rate_n=0,
        )
        for k, v in over.items():
            setattr(row, k, v)
        return render_to_string("dashboard/_signal_cards.html",
                                {"signals": [row]})

    def test_an_unmeasured_rate_renders_an_em_dash(self):
        self.assertIn("— 30d hit", self._render())

    def test_a_measured_zero_still_renders(self):
        """The old truthiness test hid 0.00 — a real, and very bad, record."""
        html = self._render(rule_hit_rate_30d=0.0, rule_hit_rate_n=7)
        self.assertIn("0.00 30d hit", html)
        self.assertNotIn("— 30d hit", html)

    def test_the_conviction_is_traceable_on_the_card(self):
        html = self._render(reasons=["base 30", "1 confluence chip(s) +10"])
        self.assertIn("1 confluence chip(s) +10", html)


# ── 1.5 — one setup, one row ────────────────────────────────────────────────

class DuplicateCards(TestCase):
    def test_rescanning_the_same_bar_stores_one_row(self):
        from signals.models_smc import SmcSignal
        from signals.rules.smc_rules import persist_cards
        first = persist_cards([_card()], "AAA", "4h")
        second = persist_cards([_card()], "AAA", "4h")
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(SmcSignal.objects.count(), 1)

    def test_the_database_refuses_a_second_row_for_the_same_bar(self):
        """Not just the pre-check: after the first card closes, the open-card
        guard no longer applies and only the constraint stands between an
        18-pass bar and 18 rows."""
        from signals.models_smc import SmcSignal
        from signals.rules.smc_rules import persist_cards
        persist_cards([_card()], "AAA", "4h")
        SmcSignal.objects.update(status="STOPPED", realized_r=-1.0,
                                 closed_at=timezone.now())
        self.assertEqual(persist_cards([_card()], "AAA", "4h"), [])
        self.assertEqual(SmcSignal.objects.count(), 1)

    def test_two_zones_of_one_setup_on_one_bar_collapse(self):
        """Same setup, same direction, same bar, different level — one idea."""
        from signals.models_smc import SmcSignal
        from signals.rules.smc_rules import persist_cards
        persist_cards([_card(entry=100.0), _card(entry=100.4)], "AAA", "4h")
        self.assertEqual(SmcSignal.objects.count(), 1)

    def test_a_later_bar_is_blocked_while_the_first_card_is_open(self):
        """One zone retested on three consecutive bars is one trade idea."""
        from signals.models_smc import SmcSignal
        from signals.rules.smc_rules import persist_cards
        persist_cards([_card(trigger_ts=BAR_ONE)], "AAA", "4h")
        persist_cards([_card(trigger_ts=BAR_TWO)], "AAA", "4h")
        self.assertEqual(SmcSignal.objects.count(), 1)

    def test_a_later_bar_is_stored_once_the_first_card_closes(self):
        from signals.models_smc import SmcSignal
        from signals.rules.smc_rules import persist_cards
        persist_cards([_card(trigger_ts=BAR_ONE)], "AAA", "4h")
        SmcSignal.objects.update(status="TARGET_HIT", realized_r=3.0,
                                 closed_at=timezone.now())
        persist_cards([_card(trigger_ts=BAR_TWO)], "AAA", "4h")
        self.assertEqual(SmcSignal.objects.count(), 2)

    def test_other_setups_and_directions_are_not_collateral(self):
        from signals.models_smc import SmcSignal
        from signals.rules.smc_rules import persist_cards
        persist_cards([
            _card(),
            _card(direction="SHORT"),
            _card(setup="FVG_TAP"),
            _card(timeframe="1h"),
        ], "AAA", "4h")
        # timeframe comes from the persist_cards argument, so that last card
        # is a duplicate of the first — three distinct ideas, not four.
        self.assertEqual(SmcSignal.objects.count(), 3)

    def test_duplicates_no_longer_inflate_the_empirical_threshold(self):
        """The reason 1.5 has to land before 1.4: n_closed is the gate."""
        from signals.models_smc import SmcSignal
        from signals.performance import setup_performance_summary
        from signals.rules.smc_rules import persist_cards
        for _ in range(6):
            persist_cards([_card(setup="RP_BREAKER", direction="SHORT")],
                          "AAA", "4h")
        SmcSignal.objects.update(status="TARGET_HIT", realized_r=2.0,
                                 closed_at=timezone.now())
        summary = setup_performance_summary(days=30)
        self.assertEqual(summary["RP_BREAKER"]["n_closed"], 1)
        self.assertFalse(
            summary["RP_BREAKER"]["is_empirical"],
            "six scans of one bar must not be six pieces of evidence")


# ── 2.2 — the ICT primitives are wired in ───────────────────────────────────

class IctPrimitivesHaveCallers(SimpleTestCase):
    def test_the_scanner_calls_all_three_dead_modules(self):
        import inspect

        from signals.rules import smc_rules
        src = inspect.getsource(smc_rules)
        # `in_ny_session` rather than `in_killzone`: the scanner scores the
        # NY-anchored session model, because the fixed-UTC one it replaced is
        # an hour out from November to March. See DaylightSavingDrift.
        for name in ("in_ny_session", "find_equal_levels", "detect_sfp",
                     "premium_discount"):
            self.assertIn(name, src,
                          "%s is what separates ICT from generic pattern "
                          "matching; it had no caller repo-wide" % name)

    def test_the_filters_default_on(self):
        from signals.rules.smc_rules import ict_filters_enabled
        self.assertTrue(ict_filters_enabled())

    def test_the_filters_can_be_switched_off(self):
        from django.test import override_settings
        from signals.rules.smc_rules import ict_filters_enabled
        with override_settings(SMC_ICT_FILTERS=False):
            self.assertFalse(ict_filters_enabled())


class KillzoneScoring(SimpleTestCase):
    def test_a_setup_inside_a_killzone_scores_higher(self):
        from signals.rules.smc_rules import evaluate_ict_context, KILLZONE_BONUS
        ny = evaluate_ict_context(
            _setup(trigger_ts=WINTER_KILLZONE_BAR), [], None)
        self.assertEqual(ny["killzone"], "ny_am")
        self.assertEqual(ny["adjust"], KILLZONE_BONUS)
        self.assertTrue(any("ny am killzone" in r for r in ny["reasons"]))

    def test_a_setup_outside_every_killzone_is_scored_not_dropped(self):
        """Two or three of the six 4h bar opens sit in a killzone depending on
        the season; gating on it would delete a third of the feed over what is
        really intraday timing."""
        from signals.rules.smc_rules import evaluate_ict_context
        ict = evaluate_ict_context(_setup(trigger_ts=BAR_ONE), [], None)
        self.assertIsNone(ict["killzone"])
        self.assertEqual(ict["adjust"], 0)
        self.assertIsNone(ict["refused"])

    def test_the_lunch_hour_is_not_a_killzone(self):
        """ICT's New York lunch is the hour it teaches you to sit out, so it
        is in the session table but not in KILLZONE_SESSIONS."""
        from signals.rules.smc_rules import KILLZONE_SESSIONS, killzone_for
        from signals.smc.sessions import ICT_SESSIONS_NY
        self.assertIn("ny_lunch", ICT_SESSIONS_NY)
        self.assertNotIn("ny_lunch", KILLZONE_SESSIONS)
        lunch = datetime(2024, 1, 15, 17, 30, tzinfo=dt_timezone.utc)  # 12:30 NY
        self.assertEqual(killzone_for(lunch), (None, True))

    def test_an_unanswerable_killzone_is_not_a_missed_one(self):
        """No tz database is 'not checked', which the trail has to say out
        loud — a guessed offset would be wrong for eight months a year."""
        from signals.rules import smc_rules
        with patch("signals.smc.sessions.new_york_timezone", return_value=None):
            ict = smc_rules.evaluate_ict_context(
                _setup(trigger_ts=WINTER_KILLZONE_BAR), [], None)
        self.assertIsNone(ict["killzone"])
        self.assertEqual(ict["adjust"], 0)
        self.assertTrue(any("killzone not checked" in r for r in ict["reasons"]),
                        ict["reasons"])


class DaylightSavingDrift(SimpleTestCase):
    """The killzone term is anchored to New York, not to a fixed UTC clock.

    `sessions.KILLZONES_UTC` nails its windows to UTC, and New York moves an
    hour on the first Sunday in November and back on the second Sunday in
    March. Every scan in between scored the wrong hour.
    """

    def _killzone(self, ts):
        from signals.rules.smc_rules import evaluate_ict_context
        return evaluate_ict_context(_setup(trigger_ts=ts), [], None)["killzone"]

    def test_the_same_new_york_hour_scores_the_same_in_both_seasons(self):
        self.assertEqual(self._killzone(WINTER_KILLZONE_BAR), "ny_am")
        self.assertEqual(self._killzone(SUMMER_KILLZONE_BAR), "ny_am")

    def test_a_winter_hour_the_fixed_table_called_the_ny_open_is_dead(self):
        from signals.rules.smc_rules import evaluate_ict_context
        from signals.smc.sessions import in_killzone

        # The superseded model's answer, pinned so the regression is visible:
        # 12:00 UTC in January is 07:00 in New York, an hour and a half before
        # the AM killzone opens, and the fixed table calls it the NY open.
        self.assertEqual(in_killzone(BAR_ONE), "ny_open")

        ict = evaluate_ict_context(_setup(trigger_ts=BAR_ONE), [], None)
        self.assertIsNone(ict["killzone"])
        self.assertEqual(ict["adjust"], 0)
        self.assertTrue(any("outside every killzone" in r
                            for r in ict["reasons"]), ict["reasons"])

    def test_the_fixed_table_cannot_tell_the_two_seasons_apart(self):
        """Both stamps are 'ny_open' on the UTC clock; only one of them is
        09:00 in New York, and the NY-anchored term knows which."""
        from signals.smc.sessions import in_killzone
        self.assertEqual(in_killzone(BAR_ONE), "ny_open")
        self.assertEqual(in_killzone(WINTER_KILLZONE_BAR), "ny_open")
        self.assertIsNone(self._killzone(BAR_ONE))
        self.assertEqual(self._killzone(WINTER_KILLZONE_BAR), "ny_am")


class EqualLevelsScoring(SimpleTestCase):
    """`find_equal_levels` clusters the WHOLE frame, so every fixture here
    carries the swing list the cluster indexes into — that list is what dates
    the cluster against the sweep."""

    SWEEP = {"type": "SWEEP_HIGH", "swept_price": 100.0, "wick_high": 101.0,
             "close": 99.0, "idx": 90}

    # Three equal highs, all printed well before bar 90: liquidity that was
    # genuinely resting there when the sweep ran.
    PRIOR = [{"idx": 40, "type": "H", "price": 100.0},
             {"idx": 60, "type": "H", "price": 100.05},
             {"idx": 70, "type": "H", "price": 100.1}]

    def _ict(self, clusters, swings=None):
        from signals.rules.smc_rules import evaluate_ict_context
        # BAR_ONE is a dead hour, so the killzone term stays out of `adjust`
        # and every number below belongs to the liquidity term alone.
        return evaluate_ict_context(
            _setup(trigger_ts=BAR_ONE, sweep=self.SWEEP), clusters, None,
            self.PRIOR if swings is None else swings)

    def test_taking_a_cluster_of_equal_highs_scores_higher(self):
        from signals.rules.smc_rules import EQUAL_LEVELS_BONUS
        ict = self._ict([{"type": "EQH", "price": 100.05, "count": 3,
                          "swing_indices": [0, 1, 2]}])
        self.assertEqual(ict["adjust"], EQUAL_LEVELS_BONUS)
        self.assertEqual(ict["equal_levels"]["count"], 3)
        self.assertTrue(any("equal highs" in r for r in ict["reasons"]))

    def test_a_cluster_the_sweep_never_reached_scores_nothing(self):
        far = [{"idx": 40, "type": "H", "price": 101.5},
               {"idx": 70, "type": "H", "price": 101.5}]
        ict = self._ict([{"type": "EQH", "price": 101.5, "count": 2,
                          "swing_indices": [0, 1]}], swings=far)
        self.assertEqual(ict["adjust"], 0)
        self.assertIsNone(ict["equal_levels"])

    def test_equal_lows_do_not_credit_a_high_sweep(self):
        lows = [{"idx": 40, "type": "L", "price": 100.0},
                {"idx": 70, "type": "L", "price": 100.0}]
        ict = self._ict([{"type": "EQL", "price": 100.0, "count": 2,
                          "swing_indices": [0, 1]}], swings=lows)
        self.assertEqual(ict["adjust"], 0)

    def test_a_cluster_that_formed_after_the_sweep_is_not_liquidity_it_took(self):
        """LOOKAHEAD. The cluster is at the swept price and would match on
        price alone, but both its swings printed after bar 90 — at the moment
        of the sweep those stops did not exist to be taken, and paying +12 for
        them scores the future into every backtest."""
        later = [{"idx": 95, "type": "H", "price": 100.0},
                 {"idx": 110, "type": "H", "price": 100.1}]
        ict = self._ict([{"type": "EQH", "price": 100.05, "count": 2,
                          "swing_indices": [0, 1]}], swings=later)
        self.assertEqual(ict["adjust"], 0)
        self.assertIsNone(ict["equal_levels"])
        self.assertTrue(any("when the sweep ran" in r for r in ict["reasons"]),
                        ict["reasons"])

    def test_one_swing_on_the_chart_is_a_level_not_engineered_liquidity(self):
        """The bonus is for a double top's worth of stops. One prior swing and
        one that printed later is a single high, whatever the whole-frame
        clustering later made of it."""
        from signals.rules.smc_rules import EQUAL_LEVELS_MIN_MEMBERS
        self.assertEqual(EQUAL_LEVELS_MIN_MEMBERS, 2)
        mixed = [{"idx": 40, "type": "H", "price": 100.0},
                 {"idx": 110, "type": "H", "price": 100.1}]
        ict = self._ict([{"type": "EQH", "price": 100.05, "count": 2,
                          "swing_indices": [0, 1]}], swings=mixed)
        self.assertEqual(ict["adjust"], 0)
        self.assertIsNone(ict["equal_levels"])

    def test_the_price_reported_is_the_cluster_as_it_stood(self):
        """A later swing must not drag the reported level onto the sweep: the
        price on the card is the average of the members that existed."""
        drifted = [{"idx": 40, "type": "H", "price": 100.0},
                   {"idx": 70, "type": "H", "price": 100.05},
                   {"idx": 110, "type": "H", "price": 100.9}]
        ict = self._ict([{"type": "EQH", "price": 100.316, "count": 3,
                          "swing_indices": [0, 1, 2]}], swings=drifted)
        self.assertEqual(ict["equal_levels"]["count"], 2)
        self.assertAlmostEqual(ict["equal_levels"]["price"], 100.025, places=4)

    def test_an_undateable_sweep_earns_nothing(self):
        """No bar index on the sweep means the cluster cannot be dated, and an
        undated cluster is the lookahead this guard refuses."""
        undated = dict(self.SWEEP)
        undated.pop("idx")
        from signals.rules.smc_rules import evaluate_ict_context
        ict = evaluate_ict_context(
            _setup(trigger_ts=BAR_ONE, sweep=undated),
            [{"type": "EQH", "price": 100.05, "count": 3,
              "swing_indices": [0, 1, 2]}], None, self.PRIOR)
        self.assertEqual(ict["adjust"], 0)
        self.assertTrue(any("not dateable" in r for r in ict["reasons"]),
                        ict["reasons"])


class PremiumDiscount(SimpleTestCase):
    LEG = (110.0, 100.0)  # (high, low)

    def _ict(self, **over):
        from signals.rules.smc_rules import evaluate_ict_context
        # BAR_ONE is a dead hour in New York, so `adjust` below is the
        # premium/discount term and nothing else.
        over.setdefault("trigger_ts", BAR_ONE)
        return evaluate_ict_context(_setup(**over), [], self.LEG)

    def test_a_long_deep_in_premium_is_refused(self):
        ict = self._ict(direction="LONG", entry=108.5)
        self.assertIsNotNone(ict["refused"])
        self.assertEqual(ict["zone"], "premium")

    def test_a_short_deep_in_discount_is_refused(self):
        ict = self._ict(direction="SHORT", entry=101.5)
        self.assertIsNotNone(ict["refused"])
        self.assertEqual(ict["zone"], "discount")

    def test_the_wrong_side_short_of_the_quartile_is_penalised(self):
        from signals.rules.smc_rules import PD_WRONG_SIDE_PENALTY
        ict = self._ict(direction="LONG", entry=107.0)
        self.assertIsNone(ict["refused"])
        self.assertEqual(ict["adjust"], -PD_WRONG_SIDE_PENALTY)

    def test_a_long_in_discount_is_left_alone(self):
        ict = self._ict(direction="LONG", entry=102.0)
        self.assertIsNone(ict["refused"])
        self.assertEqual(ict["adjust"], 0)
        self.assertEqual(ict["zone"], "discount")

    def test_a_short_in_premium_is_left_alone(self):
        ict = self._ict(direction="SHORT", entry=108.0)
        self.assertIsNone(ict["refused"])
        self.assertEqual(ict["adjust"], 0)

    def test_an_unmeasurable_leg_reports_nothing(self):
        """No leg is not equilibrium — the card must not claim a reading."""
        from signals.rules.smc_rules import evaluate_ict_context, dealing_range
        ict = evaluate_ict_context(_setup(), [], None)
        self.assertIsNone(ict["zone"])
        self.assertIsNone(ict["zone_pos"])
        self.assertIsNone(dealing_range([{"type": "H", "price": 10.0}]))


class SfpSetups(TestCase):
    def test_the_model_can_finally_emit_the_setup_it_advertises(self):
        from signals.models_smc import SmcSignal
        from signals.rules.smc_rules import scan_symbol
        self.assertIn("SFP", dict(SmcSignal.SETUP_CHOICES))
        setups = {c["setup"] for c in scan_symbol("AAA", "4h", df=_sfp_frame())}
        self.assertIn("SFP", setups)

    def test_the_sfp_card_fades_the_failure(self):
        from signals.rules.smc_rules import scan_symbol
        card = next(c for c in scan_symbol("AAA", "4h", df=_sfp_frame())
                    if c["setup"] == "SFP")
        self.assertEqual(card["direction"], "SHORT")
        self.assertGreater(card["stop"], card["entry"])
        self.assertLess(card["target"], card["entry"])
        self.assertIn("failed to hold", card["thesis"])

    def test_a_stale_failure_is_not_a_setup(self):
        """The SFP is traded on the reclaim; three bars later it is history."""
        from signals.rules.smc_rules import detect_sfp_setups, SFP_MAX_AGE_BARS
        df = _sfp_frame()
        sweep = {"idx": len(df) - 1 - SFP_MAX_AGE_BARS - 1,
                 "type": "SWEEP_HIGH", "swept_price": 105.0,
                 "wick_high": 106.0, "close": 100.2}
        self.assertEqual(detect_sfp_setups(df, [], [sweep]), [])


class IctFiltersEndToEnd(TestCase):
    def test_a_scan_records_why_each_card_scored_what_it_did(self):
        from signals.rules.smc_rules import scan_symbol
        for card in scan_symbol("AAA", "4h", df=_sfp_frame()):
            self.assertTrue(card["reasons"])
            self.assertIn("base 30", card["reasons"][0])
            self.assertIsNotNone(card["ict"])

    def test_switching_the_filters_off_leaves_the_detectors_alone(self):
        from signals.rules.smc_rules import scan_symbol
        cards = scan_symbol("AAA", "4h", df=_sfp_frame(), ict_filters=False)
        self.assertTrue(cards)
        for card in cards:
            self.assertIsNone(card["ict"])
            self.assertFalse(any("killzone" in r for r in card["reasons"]))

    def test_the_ict_context_is_persisted_with_the_card(self):
        from signals.models_smc import SmcSignal
        from signals.rules.smc_rules import scan_symbol, persist_cards
        cards = scan_symbol("AAA", "4h", df=_sfp_frame())
        persist_cards(cards, "AAA", "4h")
        row = SmcSignal.objects.filter(setup="SFP").get()
        self.assertIn("ict", row.raw)
        self.assertIn("zone", row.raw["ict"])
        self.assertTrue(row.reasons)

    def test_the_trail_adds_up_to_the_number_on_the_card(self):
        """The card's <summary> says "How this scored N/100"; the terms under
        it have to reach N."""
        from signals.rules.smc_rules import scan_symbol
        for card in scan_symbol("AAA", "4h", df=_sfp_frame()):
            self.assertEqual(
                _trail_total(card["reasons"]), card["conviction"],
                "%s trail does not sum to its own conviction: %r"
                % (card["setup"], card["reasons"]))

    def test_a_quiet_market_produces_no_cards(self):
        """The fixtures are doing work — a flat series must find nothing."""
        from signals.rules.smc_rules import scan_symbol
        self.assertEqual(scan_symbol("AAA", "4h", df=_flat_frame()), [])


# ── the MTF pass scores in the open ─────────────────────────────────────────

class HigherTimeframeBoostIsOnTheCard(SimpleTestCase):
    """`signals.mtf` is the path the 1800s universe scan actually runs.

    It moved conviction and lit a MACRO chip after `build_card` had already
    written the reasons trail, so every production card carried a conviction
    its own listed terms fell short of and a chip nothing explained — under a
    heading that invites the reader to check the arithmetic.
    """

    BASE_REASONS = ["base 30", "1 confluence chip(s) +10",
                    "3.00R geometry +20"]

    def _scan(self, direction="LONG", trend="up", conviction=60):
        from signals import mtf

        def one_card(symbol, timeframe=None, bars=None):
            if timeframe != "4h":
                return []
            return [{
                "symbol": symbol, "timeframe": timeframe, "setup": "OB_RETEST",
                "direction": direction, "conviction": conviction,
                "chips": {"structure": 1, "momentum": 0, "flow": 0,
                          "macro": 0, "sentiment": 0},
                "components": ["order_block", "retest"],
                "reasons": list(self.BASE_REASONS),
            }]

        with patch.object(mtf, "scan_symbol", side_effect=one_card), \
                patch.object(mtf, "htf_trend", return_value=trend):
            cards = mtf.scan_symbol_mtf("AAA", timeframes=["4h", "1d"])
        return cards[0]

    def test_agreement_is_written_into_the_trail(self):
        from signals.mtf import HTF_AGREE_BONUS
        card = self._scan(direction="LONG", trend="up")
        self.assertEqual(card["conviction"], 60 + HTF_AGREE_BONUS)
        self.assertEqual(_trail_total(card["reasons"]), card["conviction"])
        self.assertTrue(any("agrees with the LONG" in r
                            for r in card["reasons"]), card["reasons"])

    def test_the_macro_chip_the_trail_lights_is_the_chip_it_stores(self):
        card = self._scan(direction="LONG", trend="up")
        self.assertEqual(card["chips"]["macro"], 1)
        self.assertTrue(any("macro chip on" in r for r in card["reasons"]),
                        card["reasons"])

    def test_conflict_is_written_into_the_trail(self):
        from signals.mtf import HTF_CONFLICT_PENALTY
        card = self._scan(direction="LONG", trend="down")
        self.assertEqual(card["conviction"], 60 - HTF_CONFLICT_PENALTY)
        self.assertEqual(_trail_total(card["reasons"]), card["conviction"])
        self.assertEqual(card["chips"]["macro"], -1)

    def test_a_neutral_higher_timeframe_still_says_it_looked(self):
        card = self._scan(direction="LONG", trend="range")
        self.assertEqual(card["conviction"], 60)
        self.assertEqual(_trail_total(card["reasons"]), 60)
        self.assertEqual(card["chips"]["macro"], 0)
        self.assertTrue(any("no higher-timeframe verdict" in r
                            for r in card["reasons"]), card["reasons"])

    def test_a_clamped_boost_reports_what_it_actually_moved(self):
        """A card at 94 gains 6 from a +12 bonus, not 12 — and the trail has
        to say 6, or the sum breaks in the other direction."""
        card = self._scan(direction="LONG", trend="up", conviction=94)
        self.assertEqual(card["conviction"], 100)
        self.assertTrue(any(r.endswith("+6") for r in card["reasons"]),
                        card["reasons"])
