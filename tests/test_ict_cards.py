"""The five ICT setups reach the feed as cards, and cannot lie on the way.

Mitigation blocks, optimal trade entry, the Judas swing, the Silver Bullet and
SMT divergence were each built, tested and callable, and each returned a `setup`
string `SmcSignal.SETUP_CHOICES` could not store — so `scan_symbol` could find
them and `persist_cards` could not keep them. Five detectors running every 900
seconds and emitting nothing.

What this file holds them to:

  * `SetupChoicesAndDetectorsMatch` — the model may not advertise a setup no
    detector emits, and no detector may emit one the model cannot store. That
    pairing is the defect itself: "SFP" sat in `SETUP_CHOICES` for months with
    nothing able to produce it, and the five below spent their first weeks on
    the other side of the same gap.

  * One end-to-end test per setup, each on a hand-built frame where the right
    answer is known before the code runs, checking the card carries what every
    other card carries: an entry, a stop, a target, a thesis that says something
    the setup name does not, and a hit rate that is MEASURED or absent.

  * `TheTrailAddsUp` — the card's own summary reads "How this scored N/100", so
    the terms under it have to reach N. Five new setups run through the same
    displacement, bias and inducement terms, which is exactly where that
    arithmetic breaks if a term is applied outside `apply_conviction_term`.

  * `AClosedThroughBlockIsNotAZone` — the confirmed review finding. A mitigation
    block price has closed through is not a zone, and was still being offered as
    a live retest.

  * `SmtNeedsTwoCorrelatedInstruments` — the one setup here that needs a second
    frame, and the measurement that keeps it from reading a "divergence" between
    two charts that never moved together.

Run with:  python manage.py test tests.test_ict_cards
"""
import re

import pandas as pd
from django.test import SimpleTestCase, TestCase, override_settings
from unittest.mock import patch


# ── fixtures ────────────────────────────────────────────────────────────────

def frame(bars, start="2024-07-01", freq="15min", tz="UTC"):
    """DataFrame from (open, high, low, close) tuples on a UTC index."""
    idx = pd.date_range(start, periods=len(bars), freq=freq, tz=tz)
    return pd.DataFrame(
        [{"open": o, "high": h, "low": l, "close": c, "volume": 1.0}
         for o, h, l, c in bars],
        index=idx,
    )


def quiet(n, price=100.0):
    """n identical one-point-range bars — enough to warm ATR up to ~1.0."""
    return [(price, price + 0.5, price - 0.5, price) for _ in range(n)]


def zigzag(points, n, wick=0.3):
    """Bars interpolated between (bar_index, close) control points."""
    closes = []
    for i in range(n):
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            if x0 <= i <= x1:
                closes.append(y0 + (y1 - y0) * (i - x0) / (x1 - x0))
                break
        else:
            closes.append(points[-1][1])
    bars, prev = [], points[0][1]
    for close in closes:
        bars.append((prev, max(prev, close) + wick, min(prev, close) - wick, close))
        prev = close
    return bars


def swings_of(df):
    from signals.smc.pivots import classify_swings, get_swings
    return classify_swings(get_swings(df))


# Low 94.5, high 110.5, a higher low at 99.8 that never trades through 94.5,
# then a close above 110.5. The block is the 99.8-101.2 candle at index 12 and
# bar 21 comes back to tag it. Shared with tests.test_ict_primitives, which
# tests the same shape one layer down.
MITIGATION_BARS = [
    (100, 100.3, 99.7, 100), (100, 100.3, 99.7, 100), (100, 100.3, 99.7, 100),
    (100, 100.3, 98.8, 99), (99, 99.2, 94.5, 95), (95, 99.3, 94.9, 99),
    (99, 103.3, 98.8, 103), (103, 107.3, 102.8, 107), (107, 110.5, 106.8, 110),
    (110, 110.2, 105.8, 106), (106, 106.2, 102.8, 103), (103, 103.2, 100.8, 101),
    (101, 101.2, 99.8, 100), (100, 103.2, 99.9, 103), (103, 106.2, 102.8, 106),
    (106, 109.2, 105.8, 109), (109, 112.2, 108.8, 112), (112, 112.2, 109.8, 110),
    (110, 110.2, 106.8, 107), (107, 107.2, 103.8, 104), (104, 104.2, 101.5, 102),
    (102, 102.2, 100.5, 101),
]

# A 100->120 impulse, then a retrace that lands the last bar in the 62-79% band.
IMPULSE_CLOSES = [
    110.0, 109.5, 109.0, 108.5, 108.0, 107.5, 107.0, 106.5, 106.0, 105.5,
    105.0, 104.5, 104.0, 103.5, 103.0, 102.0, 101.0, 100.2, 106.0, 112.0,
    117.0, 119.8, 116.0, 113.0, 111.0, 109.5, 108.5, 107.5, 106.5, 106.0,
]

JUDAS_PRE = quiet(10) + [
    (100, 100.3, 98.0, 98), (98, 98.3, 96.5, 97), (97, 97.2, 95.5, 96),
    (96, 97.3, 95.8, 97), (97, 98.3, 96.8, 98), (98, 99.3, 97.8, 99),
] + quiet(8)
# Opens at 100.00, runs to 102.30 in the first half of the window, then trades
# back through the open and keeps going.
JUDAS_SESSION = [
    (100, 100.8, 99.8, 100.7), (100.7, 101.6, 100.5, 101.5),
    (101.5, 102.3, 101.2, 102.0), (102.0, 102.1, 100.8, 101.0),
    (101.0, 101.2, 99.5, 99.8), (99.8, 100.0, 98.5, 98.8),
    (98.8, 99.0, 97.8, 98.0), (98.0, 98.2, 97.0, 97.2),
    (97.2, 97.4, 96.5, 96.8), (96.8, 97.0, 96.0, 96.3),
    (96.3, 96.5, 95.8, 96.0), (96.0, 96.6, 95.9, 96.5),
]

# 14:00-14:45 UTC is 10:00-10:45 New York in summer: the AM Silver Bullet hour.
SB_SESSION = [
    (100, 100.5, 99.5, 100),          # the gap's left bar, high 100.5
    (100, 104.5, 99.9, 104.2),        # displacement
    (104.2, 105.0, 101.0, 104.5),     # right bar, low 101.0 -> gap 100.5-101.0
    (104.5, 104.7, 103.0, 103.2),
]
SB_RETRACE = [
    (103.2, 103.4, 102.0, 102.2), (102.2, 102.4, 101.5, 101.8),
    (101.8, 102.2, 100.8, 101.5),     # the last bar taps the gap
]

# The leader takes its 110.30 high at bar 56; the laggard's matching window
# tops out lower than its own previous one. Everything before bar 56 is shared,
# which is what makes the two correlate at 0.95.
SMT_LEADER = [(0, 100), (8, 110), (16, 102), (24, 112), (32, 104),
              (40, 110), (48, 102), (56, 116), (61, 108)]
SMT_LAGGARD = [(0, 100), (8, 110), (16, 102), (24, 112), (32, 104),
               (40, 111), (48, 102), (56, 108), (61, 104)]


def mitigation_frame():
    """52 bars of 4h ending on the bar that tags the mitigation block."""
    return frame(quiet(30) + MITIGATION_BARS, start="2024-07-01", freq="4h")


def ote_frame():
    """54 bars of 4h ending inside the 62-79% band of a 100->120 impulse."""
    bars, prev = [], 110.5
    for close in IMPULSE_CLOSES:
        bars.append((prev, max(prev, close) + 0.2, min(prev, close) - 0.2, close))
        prev = close
    return frame(quiet(24, 110.5) + bars, start="2024-07-01", freq="4h")


def judas_frame(tail=()):
    """60 bars of 15m ending on the last bar of the London window.

    Bars 48-59 are 06:00-08:45 UTC, which is 02:00-04:45 New York in summer.
    `tail` pushes the session into the past, which is what `_on_this_bar` is
    for.
    """
    return frame(quiet(24) + JUDAS_PRE + JUDAS_SESSION + list(tail),
                 start="2024-06-30 18:00", freq="15min")


def silver_bullet_frame():
    """55 bars of 15m ending on the bar that trades back into the window's gap."""
    return frame(quiet(48) + SB_SESSION + SB_RETRACE,
                 start="2024-07-01 02:00", freq="15min")


def smt_frames():
    """(leader, laggard) — 62 shared 4h bars with one divergence near the end."""
    return (frame(zigzag(SMT_LEADER, 62), freq="4h"),
            frame(zigzag(SMT_LAGGARD, 62), freq="4h"))


def flat_frame(bars=120):
    """A quiet 4h series: no pivots, no gaps, nothing for a detector to find."""
    return frame(quiet(bars), start="2024-01-01", freq="4h")


def card_for(cards, setup):
    """The card for one setup in a scan result, or None."""
    return next((c for c in cards if c["setup"] == setup), None)


def trail_total(reasons):
    """Sum the conviction terms a card lists, the way a reader would.

    Every line ends in a signed number except the "base N" opener and the lines
    stating a term was not measurable and therefore moved nothing.
    """
    total = 0
    for reason in reasons:
        if reason.startswith("base "):
            total += int(reason.split()[1])
            continue
        term = re.search(r"([+-]\d+)$", reason)
        if term:
            total += int(term.group(1))
    return total


def every_fixture_card():
    """One scan per fixture, flattened — the whole surface these tests cover."""
    from signals.rules.smc_rules import scan_symbol

    leader, laggard = smt_frames()
    cards = []
    for tf, df, partner in (("4h", mitigation_frame(), None),
                            ("4h", ote_frame(), None),
                            ("15m", judas_frame(), None),
                            ("15m", silver_bullet_frame(), None),
                            ("4h", leader, laggard)):
        cards += scan_symbol("AAA", tf, df=df, partner_df=partner,
                             smt_partner="BBB")
    return cards


# ── the model and the detectors describe the same feed ──────────────────────

def emitted_setup_names():
    """Every `"setup": "X"` literal the SMC detector modules can produce."""
    import ast
    import importlib
    import inspect
    import pkgutil

    import signals.smc
    from signals.rules import smc_rules

    modules = [smc_rules]
    for info in pkgutil.iter_modules(signals.smc.__path__):
        modules.append(importlib.import_module("signals.smc.%s" % info.name))

    names = set()
    for module in modules:
        for node in ast.walk(ast.parse(inspect.getsource(module))):
            if not isinstance(node, ast.Dict):
                continue
            for key, value in zip(node.keys, node.values):
                if (isinstance(key, ast.Constant) and key.value == "setup"
                        and isinstance(value, ast.Constant)
                        and isinstance(value.value, str)):
                    names.add(value.value)
    return names


class SetupChoicesAndDetectorsMatch(SimpleTestCase):
    """A choice no detector emits is a promise nothing keeps; a setup no choice
    names cannot be stored at all. Both were true here at once."""

    def test_every_advertised_setup_has_a_detector_behind_it(self):
        from signals.models_smc import SmcSignal

        advertised = set(dict(SmcSignal.SETUP_CHOICES))
        orphans = sorted(advertised - emitted_setup_names())
        self.assertEqual(
            orphans, [],
            "SETUP_CHOICES advertises %r and no detector emits it. The feed "
            "offers the filter, `setup_performance_summary` groups by it and "
            "no scan can ever store one — which is exactly the state 'SFP' sat "
            "in for months." % orphans)

    def test_every_detector_setup_can_be_stored(self):
        from signals.models_smc import SmcSignal

        advertised = set(dict(SmcSignal.SETUP_CHOICES))
        unstorable = sorted(emitted_setup_names() - advertised)
        self.assertEqual(
            unstorable, [],
            "%r comes out of a detector and SETUP_CHOICES cannot name it, so "
            "`scan_symbol` finds the setup and `persist_cards` drops it on the "
            "floor" % unstorable)

    def test_the_five_ict_setups_are_among_them(self):
        """Named explicitly, so deleting the wiring fails here rather than
        silently shrinking a set comparison on both sides at once."""
        from signals.models_smc import SmcSignal

        advertised = set(dict(SmcSignal.SETUP_CHOICES))
        for setup in ("MITIGATION_BLOCK", "OTE", "JUDAS_SWING",
                      "SILVER_BULLET", "SMT_DIVERGENCE"):
            self.assertIn(setup, advertised)
            self.assertIn(setup, emitted_setup_names())

    def test_the_migration_carries_the_same_list(self):
        """A choices change Django never wrote down leaves `makemigrations`
        reporting a phantom change on every deploy."""
        import importlib

        from signals.models_smc import SmcSignal

        migration = importlib.import_module(
            "signals.migrations.0017_smcsignal_ict_setups").Migration
        field = migration.operations[0].field
        self.assertEqual([tuple(c) for c in field.choices],
                         [tuple(c) for c in SmcSignal.SETUP_CHOICES])


# ── one end-to-end test per setup ───────────────────────────────────────────

class CardsEachSetupProduces(SimpleTestCase):
    def assert_card_is_tradeable(self, card, direction):
        """Every field a reader acts on, present and pointing the right way."""
        self.assertEqual(card["direction"], direction)
        if direction == "LONG":
            self.assertLess(card["stop"], card["entry"])
            self.assertGreater(card["target"], card["entry"])
        else:
            self.assertGreater(card["stop"], card["entry"])
            self.assertLess(card["target"], card["entry"])
        self.assertGreater(card["r_multiple"], 0)
        self.assertTrue(card["invalidation"])
        self.assertTrue(card["why_now"])
        # The fallback `build_card` writes when no template names the setup.
        # It repeats the setup name and the entry and says nothing else.
        self.assertNotEqual(
            card["thesis"],
            "%s setup at %.4f" % (card["setup"], card["entry"]),
            "the card fell through to the generic thesis")

    def test_a_mitigation_block_retest_becomes_a_card(self):
        from signals.rules.smc_rules import scan_symbol
        card = card_for(scan_symbol("AAA", "4h", df=mitigation_frame()),
                        "MITIGATION_BLOCK")
        self.assertIsNotNone(card)
        self.assert_card_is_tradeable(card, "LONG")
        self.assertAlmostEqual(card["entry"], 100.5)      # middle of the zone
        self.assertLess(card["stop"], 99.8)               # clear of the origin
        # The clause that makes it a MITIGATION block and not a breaker: the
        # structure shifted without the swing being taken out first, so the
        # traders offside are getting out flat rather than trapped.
        self.assertIn("without the market ever sweeping it", card["thesis"])

    def test_an_optimal_trade_entry_becomes_a_card(self):
        from signals.rules.smc_rules import scan_symbol
        card = card_for(scan_symbol("AAA", "4h", df=ote_frame()), "OTE")
        self.assertIsNotNone(card)
        self.assert_card_is_tradeable(card, "LONG")
        self.assertAlmostEqual(card["entry"], 105.9)      # 70.5% of 100->120
        self.assertAlmostEqual(card["target"], 120.0)     # the leg's extreme
        self.assertIn("70.5% sweet spot", card["thesis"])

    def test_a_judas_swing_becomes_a_card(self):
        from signals.rules.smc_rules import scan_symbol
        card = card_for(scan_symbol("AAA", "15m", df=judas_frame()),
                        "JUDAS_SWING")
        self.assertIsNotNone(card)
        self.assert_card_is_tradeable(card, "SHORT")
        self.assertAlmostEqual(card["entry"], 101.15)     # midpoint of the trap
        self.assertIn("london", card["thesis"])
        # The London window IS a killzone, and the card says it scored for it.
        self.assertTrue(any("london killzone" in r for r in card["reasons"]),
                        card["reasons"])

    def test_a_silver_bullet_becomes_a_card(self):
        from signals.rules.smc_rules import scan_symbol
        card = card_for(scan_symbol("AAA", "15m", df=silver_bullet_frame()),
                        "SILVER_BULLET")
        self.assertIsNotNone(card)
        self.assert_card_is_tradeable(card, "LONG")
        self.assertAlmostEqual(card["entry"], 100.75)     # consequent encroachment
        self.assertAlmostEqual(card["target"], 105.0)     # the displacement high
        self.assertIn("silver bullet am", card["thesis"])

    def test_a_silver_bullet_does_not_fire_on_its_own_creation_bar(self):
        """The gap is (a, b, c) and `gap["idx"]` is b, so the bar that
        COMPLETES the gap is one bar old by that measure. It used to qualify
        as a retest — and the touch test passes there by definition, since
        the bull zone's top IS that bar's low. Every gap therefore published
        a card one bar before a retracement could exist, and persistence
        dedupe then swallowed the real retest when it arrived."""
        from signals.rules.smc_rules import scan_symbol
        from signals.smc.session_setups import detect_silver_bullet_fvgs

        frame = silver_bullet_frame()
        gaps = detect_silver_bullet_fvgs(frame)
        self.assertTrue(gaps, "no silver-bullet FVG in the fixture — drifted")

        # `idx` is b, the middle bar, so the gap is COMPLETE at b + 1. A scan
        # ending exactly there has seen the gap and nothing after it, so there
        # is no bar in which a retest could have happened.
        completion = gaps[0]["idx"] + 1
        window = frame.iloc[:completion + 1]
        self.assertIsNone(
            card_for(scan_symbol("AAA", "15m", df=window), "SILVER_BULLET"),
            "a card was published on the bar that completed the gap, one "
            "bar before any retracement could exist")

        # And the real retest still produces one, so the guard did not simply
        # switch the setup off.
        self.assertIsNotNone(
            card_for(scan_symbol("AAA", "15m", df=frame), "SILVER_BULLET"))

    def test_an_smt_divergence_becomes_a_card(self):
        from signals.rules.smc_rules import scan_symbol
        leader, laggard = smt_frames()
        card = card_for(
            scan_symbol("AAA", "4h", df=leader, partner_df=laggard,
                        smt_partner="BBB"),
            "SMT_DIVERGENCE")
        self.assertIsNotNone(card)
        self.assert_card_is_tradeable(card, "SHORT")
        self.assertIn("BBB", card["thesis"])
        self.assertIn("correlated", card["thesis"])

    def test_a_four_hour_frame_produces_no_session_setups(self):
        """Not a gap in the wiring: a one-hour Silver Bullet window cannot hold
        three consecutive 4h bars and a three-hour London window cannot hold the
        three a Judas needs, so on the frame this scan usually runs both are
        correctly and permanently silent."""
        from signals.rules.smc_rules import scan_symbol
        setups = [c["setup"] for c in scan_symbol("AAA", "4h", df=ote_frame())]
        self.assertNotIn("JUDAS_SWING", setups)
        self.assertNotIn("SILVER_BULLET", setups)

    def test_a_quiet_market_still_produces_no_cards(self):
        """Thirteen detectors now, and a flat series must still find nothing."""
        from signals.rules.smc_rules import scan_symbol
        self.assertEqual(scan_symbol("AAA", "4h", df=flat_frame()), [])


# ── the card cannot lie ─────────────────────────────────────────────────────

class TheTrailAddsUp(SimpleTestCase):
    def test_every_new_card_sums_to_its_own_conviction(self):
        """The card's summary says "How this scored N/100" and invites the
        arithmetic to be checked."""
        for card in every_fixture_card():
            self.assertEqual(
                trail_total(card["reasons"]), card["conviction"],
                "%s trail does not sum to its own conviction: %r"
                % (card["setup"], card["reasons"]))

    def test_every_new_card_reports_its_hit_rate_as_unmeasured(self):
        """Nothing has closed, so there is no rate — and no card may invent
        one. This is the mistake the platform already made and corrected: the
        strategy author's published numbers rendered as this platform's own
        measured record."""
        for card in every_fixture_card():
            self.assertIsNone(card["hit_rate_30d"], card["setup"])
            self.assertTrue(
                any("not empirical" in r or "not measured" in r
                    for r in card["reasons"]),
                "%s says nothing about its own record: %r"
                % (card["setup"], card["reasons"]))

    def test_every_new_card_fits_the_columns_it_is_stored_in(self):
        """A thesis over 280 characters is a card that saves on SQLite and
        raises on Postgres."""
        from signals.models_smc import SmcSignal

        for field in ("headline", "thesis", "invalidation"):
            limit = SmcSignal._meta.get_field(field).max_length
            for card in every_fixture_card():
                self.assertLessEqual(
                    len(card[field]), limit,
                    "%s %s is %d characters, over the %d the column holds"
                    % (card["setup"], field, len(card[field]), limit))

    def test_the_thesis_says_something_the_setup_name_does_not(self):
        """`explain.templates` has no line for these five, so `build_card`
        falls through to "OTE setup at 105.9000". Each detector writes its own
        from the numbers it measured, and the shared table still wins wherever
        it has a line."""
        from signals.explain.templates import THESIS_TEMPLATES

        for card in every_fixture_card():
            if card["setup"] in THESIS_TEMPLATES:
                continue
            self.assertNotEqual(
                card["thesis"],
                "%s setup at %.4f" % (card["setup"], card["entry"]))
            self.assertGreater(len(card["thesis"]), 60, card["thesis"])


class CardsSurviveTheDatabase(TestCase):
    """The migration is the whole point: five setups the column could not name."""

    def test_the_five_setups_persist(self):
        from signals.models_smc import SmcSignal
        from signals.rules.smc_rules import persist_cards

        stored = set()
        for card in every_fixture_card():
            persist_cards([card], "AAA", card["timeframe"])
        for row in SmcSignal.objects.all():
            stored.add(row.setup)
        for setup in ("MITIGATION_BLOCK", "OTE", "JUDAS_SWING",
                      "SILVER_BULLET", "SMT_DIVERGENCE"):
            self.assertIn(setup, stored)

    def test_a_stored_card_passes_its_own_validation(self):
        """`full_clean` is where a setup outside SETUP_CHOICES actually fails —
        the column takes any 32 characters, the choices are what the admin, the
        model forms and every ValidationError path check against."""
        from signals.models_smc import SmcSignal
        from signals.rules.smc_rules import persist_cards

        for card in every_fixture_card():
            persist_cards([card], "AAA", card["timeframe"])
        for row in SmcSignal.objects.all():
            row.full_clean()

    def test_a_rescan_of_the_same_bar_stores_one_row(self):
        """Every detector evaluates the last bar and both schedulers re-scan
        it. The five new ones are no exception."""
        from signals.models_smc import SmcSignal
        from signals.rules.smc_rules import scan_symbol, persist_cards

        cards = scan_symbol("AAA", "4h", df=mitigation_frame())
        persist_cards(cards, "AAA", "4h")
        persist_cards(cards, "AAA", "4h")
        self.assertEqual(
            SmcSignal.objects.filter(setup="MITIGATION_BLOCK").count(), 1)


# ── the confirmed review finding ────────────────────────────────────────────

class AClosedThroughBlockIsNotAZone(SimpleTestCase):
    """A mitigation block that is closed through after its first touch was
    never marked invalidated, so the retest detector went on offering it. The
    walk used to stop at the first bar that tagged the zone, which is the one
    bar after which the interesting question starts."""

    def bars(self):
        return quiet(30) + MITIGATION_BARS + [
            (101, 101.2, 98.0, 98.5),      # closes under the zone: it is done
            (98.5, 100.5, 100.0, 100.2),   # and price comes back into it anyway
        ]

    def blocks(self, bars):
        from signals.smc.mitigation import detect_mitigation_blocks
        from signals.smc.structure import detect_market_structure_breaks

        df = frame(bars, start="2024-07-01", freq="4h")
        swings = swings_of(df)
        breaks = detect_market_structure_breaks(df, swings)
        return df, swings, detect_mitigation_blocks(df, swings, breaks)

    def test_a_touch_and_a_close_through_are_both_recorded(self):
        """Two independent facts about one zone. The old walk could only ever
        report one of them, because it stopped at whichever came first."""
        df, swings, blocks = self.blocks(self.bars())
        block = blocks[0]
        self.assertTrue(block["mitigated"])
        self.assertEqual(block["mitigated_idx"], 51)
        self.assertTrue(block["invalidated"])
        self.assertEqual(block["invalidated_idx"], 52)

    def test_the_dead_zone_is_no_longer_offered(self):
        from signals.smc.mitigation import detect_mitigation_retest_setups
        df, swings, blocks = self.blocks(self.bars())
        live = detect_mitigation_retest_setups(df, blocks, swings, current_idx=51)
        self.assertEqual(len(live), 1, "the fixture must produce a retest at "
                                       "bar 51, or the next assertion is empty")
        self.assertEqual(
            detect_mitigation_retest_setups(df, blocks, swings, current_idx=53),
            [],
            "price closed through this zone at bar 52 and it is still being "
            "offered as a live retest")

    def test_a_zone_price_never_closed_through_stays_live(self):
        """The other half: the fix must not retire a block on the touch."""
        df, swings, blocks = self.blocks(quiet(30) + MITIGATION_BARS)
        block = blocks[0]
        self.assertTrue(block["mitigated"])
        self.assertFalse(block["invalidated"])
        self.assertIsNone(block["invalidated_idx"])


class MitigationBlocksCannotHaveAnInducement(SimpleTestCase):
    """Why `inducement_for` does not ask the question of a mitigation block.

    `detect_mitigation_blocks` draws the zone on the LAST swing of its type
    before the break, and `find_inducement` looks for a swing of that same type
    between the zone and the break. There is never one — a swing there would
    have been picked as the origin instead — and the origin swing itself sits on
    the far side of the zone, where the separation test refuses it. If that ever
    stops being true, this test fails and the scan should start asking.
    """

    def test_no_pool_is_findable_in_front_of_any_block(self):
        from signals.smc.dataframe import synthetic_ohlcv
        from signals.smc.inducement import find_inducement
        from signals.smc.mitigation import detect_mitigation_blocks
        from signals.smc.pivots import atr
        from signals.smc.structure import detect_market_structure_breaks

        seen = 0
        for seed in range(40):
            df = synthetic_ohlcv(bars=300, seed=seed)
            swings = swings_of(df)
            breaks = detect_market_structure_breaks(df, swings)
            atr_values = atr(df)
            for block in detect_mitigation_blocks(df, swings, breaks):
                seen += 1
                self.assertIsNone(
                    find_inducement(
                        df, swings, block["low"], block["high"], block["idx"],
                        block.get("created_by_break_idx"),
                        "LONG" if block["type"] == "MB_BULL" else "SHORT",
                        atr_values=atr_values),
                    "a mitigation block has a pool in front of it after all — "
                    "`smc_rules.inducement_for` should stop skipping them")
        self.assertGreater(seen, 20, "the sweep found almost no blocks, so it "
                                     "proves nothing")

    def test_a_mitigation_card_still_scores_its_displacement(self):
        """The other three post-build terms do apply to it: the block is drawn
        from a structure break like an order block is."""
        from signals.rules.smc_rules import scan_symbol
        card = card_for(scan_symbol("AAA", "4h", df=mitigation_frame()),
                        "MITIGATION_BLOCK")
        self.assertTrue(any("displaced" in r for r in card["reasons"]),
                        card["reasons"])
        self.assertIsNotNone(card["ict"]["displacement"])
        self.assertTrue(card["ict"]["displacement"]["displaced"])


# ── only the current bar is publishable ─────────────────────────────────────

class OnlyTheBarTheScanIsStandingOn(SimpleTestCase):
    def test_a_finished_session_is_not_published_as_a_live_card(self):
        """`detect_judas_swings` reports every session in the frame, which a
        backtest wants and a live scan may not publish: a card for a London
        session three weeks ago is an idea nobody can take, and `persist_cards`
        would store the oldest of them and drop the rest as duplicates."""
        from signals.rules.smc_rules import scan_symbol
        from signals.smc.session_setups import detect_judas_swings

        stale = judas_frame(tail=quiet(12, 96.5))
        found = detect_judas_swings(stale, swings_of(stale))
        self.assertEqual(len(found), 1, "the detector must still find it, or "
                                        "this tests the fixture not the filter")
        self.assertLess(found[0]["trigger_idx"], len(stale) - 1)
        self.assertIsNone(
            card_for(scan_symbol("AAA", "15m", df=stale), "JUDAS_SWING"))

    def test_the_same_session_on_its_own_last_bar_is_published(self):
        from signals.rules.smc_rules import scan_symbol
        self.assertIsNotNone(
            card_for(scan_symbol("AAA", "15m", df=judas_frame()),
                     "JUDAS_SWING"))


# ── SMT needs two instruments, and needs them to be related ─────────────────

class SmtNeedsTwoCorrelatedInstruments(SimpleTestCase):
    def setUp(self):
        self.leader, self.laggard = smt_frames()
        self.swings = swings_of(self.leader)

    def test_the_correlation_is_measured_not_assumed(self):
        from signals.smc.smt import measured_correlation
        self.assertGreater(measured_correlation(self.leader, self.laggard), 0.9)

    def test_an_unmeasurable_correlation_is_none_and_not_zero(self):
        """A flat partner has no variance to correlate against. 0.0 there would
        read as a measured absence of any relationship, which would let a caller
        treat "could not check" as "checked, and they are unrelated"."""
        from signals.smc.smt import measured_correlation
        self.assertIsNone(
            measured_correlation(self.leader, frame(quiet(62), freq="4h")))

    def test_a_divergence_between_unrelated_charts_is_not_offered(self):
        from signals.smc.smt import detect_smt_divergence, detect_smt_setups
        self.assertTrue(detect_smt_divergence(self.leader, self.laggard, "A", "B"),
                        "the divergence itself must still be found, or the "
                        "refusal below is about the wrong thing")
        self.assertEqual(
            detect_smt_setups(self.leader, self.swings, self.laggard, "A", "B",
                              min_correlation=0.99),
            [])

    def test_no_partner_frame_means_no_smt_read_and_no_error(self):
        from signals.rules.smc_rules import scan_symbol
        self.assertIsNone(
            card_for(scan_symbol("AAA", "4h", df=self.leader), "SMT_DIVERGENCE"))

    def test_the_scan_reads_the_same_levels_whatever_comes_after(self):
        """The divergence pivot needs three bars after it to be confirmed, so
        this is precisely where a scan can end up reading past its own bar. The
        answer at bar 61 must not depend on the frame holding bar 75."""
        from signals.smc.smt import detect_smt_setups

        longer_lead = frame(zigzag(SMT_LEADER + [(75, 130)], 76), freq="4h")
        longer_lag = frame(zigzag(SMT_LAGGARD + [(75, 130)], 76), freq="4h")
        clipped = detect_smt_setups(longer_lead, swings_of(longer_lead),
                                    longer_lag, "A", "B", current_idx=61)
        live = detect_smt_setups(self.leader, self.swings, self.laggard, "A", "B")
        self.assertTrue(live)
        self.assertEqual(
            [(s["direction"], round(s["entry"], 6), round(s["stop"], 6))
             for s in clipped],
            [(s["direction"], round(s["entry"], 6), round(s["stop"], 6))
             for s in live])

    def test_a_stale_divergence_is_not_a_setup(self):
        from signals.smc.smt import SMT_MAX_AGE_BARS, detect_smt_setups
        events = detect_smt_setups(self.leader, self.swings, self.laggard,
                                   "A", "B")
        self.assertTrue(events)
        self.assertLessEqual(events[0]["smt"]["age_bars"], SMT_MAX_AGE_BARS)
        self.assertEqual(
            detect_smt_setups(self.leader, self.swings, self.laggard, "A", "B",
                              max_age_bars=1),
            [])


class SmtPartnerLookup(SimpleTestCase):
    def test_a_symbol_with_no_partner_costs_no_second_read(self):
        """The lookup is what keeps SMT cheap: most symbols never load a second
        frame at all."""
        from signals.rules.smc_rules import scan_symbol, smt_partner_for

        self.assertIsNone(smt_partner_for("NOTHING_LIKE_THIS"))
        with patch("signals.smc.dataframe.load_ohlcv") as load:
            scan_symbol("NOTHING_LIKE_THIS", "4h", df=flat_frame())
        load.assert_not_called()

    def test_a_paired_symbol_loads_exactly_one_partner_frame(self):
        from signals.rules.smc_rules import scan_symbol

        with patch("signals.smc.dataframe.load_ohlcv", return_value=None) as load:
            scan_symbol("ES", "4h", df=flat_frame(), bars=300)
        load.assert_called_once_with("NQ", "4h", 300)

    def test_settings_win_over_the_built_in_candidates(self):
        from signals.rules.smc_rules import smt_partner_for

        with override_settings(SMC_SMT_PARTNERS={"ES": "YM", "AAA": "BBB"}):
            self.assertEqual(smt_partner_for("ES"), "YM")
            self.assertEqual(smt_partner_for("AAA"), "BBB")
        with override_settings(SMC_SMT_PARTNERS={"ES": None}):
            self.assertIsNone(smt_partner_for("ES"))
