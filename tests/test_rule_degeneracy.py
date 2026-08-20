"""Is `rule_degeneracy` real? — the two pairs the strategist briefing named.

The briefing said:

    rule_degeneracy — advanced_smc_long vs advanced_smc_short: Jaccard 1.0 on
    fair_value_gap / liquidity_sweep / relative_volume. Watch for both firing
    on the same bar — that's a net-zero-minus-spread trade. Same pathology on
    starter_commodity_vol_compression vs starter_stock_mean_reversion.

Both halves are tested here, and they come out differently.

THE SMC PAIR is reachable. Jaccard 1.0 is measured on condition KINDS, which
overstates it — the params carry opposite directions and only relative_volume
is direction-neutral, so the honest overlap is 0.14 — but one market shape
does make both setups match on the same instrument at the same instant: a
whipsaw that sweeps the lows, breaks structure UP, sweeps the highs and breaks
structure back DOWN inside the five-bar window both setups read. A CPI/FOMC
session. `DoubleSweepIsReachableTests` builds it.

That shape is a SESSION and not a single bar, which is itself a consequence of
the setups carrying structure. No bar can be both a BOS_UP and a BOS_DOWN: the
breaking bar must close ABOVE the swing high and BELOW the swing low, so that
high has to sit under that low — while every bar between the swings and the
break must close under the high (or the upside break printed earlier) and over
the low (or the downside one did), which needs the high above the low. A
fractal pivot needs three bars to its right, so those in-between bars always
exist. The old one-outside-bar version of this fixture reached both setups only
while they were unordered bags of sweeps, gaps and volume.

What follows from that is NOT the trade the briefing feared. Nothing in the
engine will take both sides: `AssetBot.decide()` returns one BotDecision per
symbol per tick, its headcount path vetoes outright on any disagreement, its
weighted path nets the two sides to ~0, and `scan_symbol` refuses a second
entry while one is on. `EngineRefusesBothSidesTests` pins all three.

What DID follow is the scanner publishing a bullish and a bearish Signal on
one instrument at one instant — two rules each graded on a coin flip, feeding
noise back into the expectancy weights that decide the next entry.
`ContradictionGuardTests` covers the guard added to `scan_all_setups`.

THE STARTER PAIR is not degenerate at all, and the briefing is wrong about it
three times over: both setups are BULLISH (so there is no opposite trade to
be had), their asset_classes are disjoint (so no instrument is ever scored by
both), and their price legs are arithmetically incompatible on any series.
`StarterPairIsNotDegenerateTests` proves each.

Run with:  python manage.py test tests.test_rule_degeneracy
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone


# ── Helpers ───────────────────────────────────────────────────────────────

def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _seed_bars(instrument, bars, end=None, timeframe="1d"):
    """Seed PriceData rows from (open, high, low, close, volume) tuples,
    oldest first, one day apart, ending one day before `end`."""
    from market_data.models import PriceData
    end = end or timezone.now()
    rows = []
    for i, (o, h, lo, c, v) in enumerate(bars):
        rows.append(PriceData(
            instrument=instrument, timeframe=timeframe,
            timestamp=end - timedelta(days=len(bars) - i),
            open=Decimal(str(o)), high=Decimal(str(h)), low=Decimal(str(lo)),
            close=Decimal(str(c)), volume=int(v), source="test",
        ))
    PriceData.objects.bulk_create(rows)


def _setup(name, pack="advanced"):
    """The OpportunitySetup row exactly as the seeder writes it, active."""
    from signals.models_opportunity import OpportunitySetup
    if pack == "advanced":
        from signals.management.commands import seed_advanced_strategies as mod
    else:
        from signals.management.commands import seed_strategies as mod
    spec = next(s for s in mod._setup_definitions() if s["name"] == name)
    return OpportunitySetup.objects.create(
        name=spec["name"], description=spec["description"],
        direction=spec["direction"], asset_classes=spec["asset_classes"],
        conditions=spec["conditions"], min_match_score=spec["min_match_score"],
        suggested_horizon_days=spec["suggested_horizon_days"],
        sizing=spec.get("sizing", {}), is_active=True,
    )


# The 22 bars of context before the interesting ones: a zigzag that RISES to a
# peak, sells off through a swing low — that sell-off is the downside break of
# structure both later CHoCHs are measured against — bottoms at 100.05, and
# grinds back up into a 102.55 shelf.
#
# It is a zigzag rather than filler for a hard reason. `smc.pivots.find_pivots`
# marks bar i a swing high only when its high is the strict max of the seven-bar
# window centred on it AND `argmax() == left`, so a repeated bar loses every tie
# to the earlier copy of itself: a block of identical filler bars produces ZERO
# swings, and with no swings there are no structure breaks, no sweeps to order
# against them, and nothing for either smc setup to score. A fixture like that
# does not test the contradiction guard, it just fails to reach it.
_COIL = [
    (103.6, 104.15, 103.45, 104.0, 1000),    # 0
    (104.0, 104.55, 103.85, 104.4, 1000),    # 1
    (104.4, 104.95, 104.25, 104.8, 1000),    # 2
    (104.8, 104.95, 104.05, 104.2, 1000),    # 3
    (104.2, 104.35, 103.45, 103.6, 1000),    # 4
    (103.6, 103.75, 102.85, 103.0, 1000),    # 5
    (103.0, 103.15, 102.45, 102.6, 1000),    # 6  — swing LOW at 102.45
    (102.6, 103.15, 102.45, 103.0, 1000),    # 7
    (103.0, 103.55, 102.85, 103.4, 1000),    # 8
    (103.4, 103.55, 102.85, 103.0, 1000),    # 9
    (103.0, 103.15, 102.25, 102.4, 1000),    # 10 — closes under it: BOS_DOWN
    (102.4, 102.55, 101.65, 101.8, 1000),    # 11
    (101.8, 101.95, 101.05, 101.2, 1000),    # 12
    (101.2, 101.35, 100.45, 100.6, 1000),    # 13
    (100.6, 100.75, 100.05, 100.2, 1000),    # 14 — swing LOW at 100.05
    (100.2, 100.75, 100.05, 100.6, 1000),    # 15
    (100.6, 101.35, 100.45, 101.2, 1000),    # 16
    (101.2, 101.95, 101.05, 101.8, 1000),    # 17
    (101.8, 102.55, 101.65, 102.4, 1000),    # 18 — swing HIGH at 102.55
    (102.4, 102.55, 101.85, 102.0, 1000),    # 19
    (102.0, 102.15, 101.45, 101.6, 1000),    # 20
    (101.6, 101.75, 101.05, 101.2, 1000),    # 21
]

# Wicks below the 100.05 swing low and closes back above it — the stop-hunt the
# bullish sequence needs BEFORE its break, not on the same bar as it.
_SWEEP_LOW_BAR = (101.2, 101.3, 98.0, 101.0, 1000)
# Closes at 103.6, through the 102.55 shelf. The prior break was to the DOWNSIDE
# (bar 10), so this one contradicts it and is tagged CHoCH.
_BOS_UP_BAR = (101.0, 103.75, 100.95, 103.6, 1000)
# Back through the shelf and rejected: the mirror stop-hunt, one bar before the
# downside break.
_SWEEP_HIGH_BAR = (103.6, 104.5, 102.3, 102.4, 1000)
# The whipsaw bar. Driven down through 98.0 and up through 104.5 — both sides of
# every level the last twenty bars laid down — closing at 99.0, under the 100.05
# swing low, which is a bearish CHoCH against the upside break two bars back.
# Volume is 4x the 20-bar average, which is direction-neutral.
_WHIPSAW_BAR = (102.4, 110.0, 92.5, 99.0, 4000)


def _double_sweep_bars():
    """The market shape that makes advanced_smc_long AND advanced_smc_short
    both match on the same instrument at the same instant.

    It is a SESSION, not a bar, and that is a consequence of the setups
    carrying structure: one bar cannot be both a BOS_UP and a BOS_DOWN (the
    module docstring works through why). What is reachable, and what this
    fixture builds, is a whipsaw across four bars: lows swept, structure broken
    UP, highs swept, structure broken DOWN, all inside the five-bar freshness
    window both setups ask for. A CPI print into a coil does exactly this.

    Both setups clear 0.65 on the last bar — the long on a break two bars back,
    the short on the break that just printed — so the pass has a genuine
    bullish-and-bearish disagreement to suppress.
    """
    return _COIL + [_SWEEP_LOW_BAR, _BOS_UP_BAR, _SWEEP_HIGH_BAR, _WHIPSAW_BAR]


def _bullish_sweep_only_bars():
    """The same coil with only the DOWNSIDE swept: the lows are taken out and
    reclaimed, structure breaks upward, and nothing breaks it back down.

    advanced_smc_long scores 0.93; advanced_smc_short reaches 0.23 — a bearish
    imbalance left in the coil plus the direction-neutral volume leg, with both
    structure legs at zero — and stays far below its 0.65 bar.

    Used to show the guard suppresses a contradiction where one exists and
    nothing else.
    """
    return _COIL + [
        _SWEEP_LOW_BAR,
        (101.0, 102.6, 100.95, 102.5, 1000),    # stops under the 102.55 shelf
        (102.5, 104.0, 102.4, 103.8, 4000),     # and then breaks it, on volume
    ]


def _user(name="degen_user"):
    return User.objects.create_user(username=name, password="x")


def _config(user, asset_class="stock", **overrides):
    from bot_program.models import AssetBotConfig
    defaults = dict(
        user=user, asset_class=asset_class, name="Degeneracy Bot",
        enabled=True, mode="paper", symbols=[],
        capital=Decimal("10000"), base_currency="USD",
        position_size_pct=2.0, max_concurrent_positions=5,
        max_daily_loss_pct=2.0, stop_loss_pct=1.5, take_profit_pct=3.0,
        entry_score_min=0.6, min_signals_for_entry=1, cool_down_minutes=0,
    )
    defaults.update(overrides)
    return AssetBotConfig.objects.create(**defaults)


def _signal(symbol, direction, score, rule, asset_class="stock"):
    from signals.models import Signal
    return Signal.objects.create(
        instrument=_instrument(symbol, asset_class), signal_type="composite",
        direction=direction, urgency="medium",
        title=f"{symbol} {direction}", description="t",
        rule_name=rule, score=score, sub_scores={},
        price_at_signal=Decimal("100"), suggested_entry=Decimal("100"),
        suggested_stop=Decimal("95"), suggested_target=Decimal("110"),
    )


# ══════════════════════════════════════════════════════════════════════════
# 1. The claim, tested: can both smc setups match the same instant?
# ══════════════════════════════════════════════════════════════════════════

class DoubleSweepIsReachableTests(TestCase):
    """Yes — and this is the exact market shape that does it.

    The sweep and imbalance halves are tested on ONE bar, because one bar
    genuinely can carry both of those; the two setups' own verdicts are tested
    on the whipsaw session, because since they carry structure they can only
    disagree across bars. Both halves matter: the first is why the sweep and
    gap legs never separated the pair, the second is what the guard has to
    catch.
    """

    def test_one_bar_can_sweep_both_sides_of_the_same_coil(self):
        from signals.evaluators_advanced import _eval_liquidity_sweep
        inst = _instrument("SWEEP1")
        _seed_bars(inst, _double_sweep_bars())
        now = timezone.now()
        params = {"lookback": 20, "wick_pct": 0.3}

        up = _eval_liquidity_sweep({**params, "direction": "bullish_sweep"},
                                   inst, now)
        down = _eval_liquidity_sweep({**params, "direction": "bearish_sweep"},
                                     inst, now)
        self.assertTrue(up["matched"], up["details"])
        self.assertTrue(down["matched"], down["details"])
        # The levels are the extremes of the 20 bars before the whipsaw, which
        # are the two stop-hunt bars' own wicks: 98.0 below, 104.5 above.
        self.assertEqual(up["details"]["swing_low"], 98.0)
        self.assertEqual(down["details"]["swing_high"], 104.5)
        # Both wicks are ~31% of the bar, so both clear wick_pct with room.
        self.assertGreaterEqual(up["details"]["wick_ratio"], 0.3)
        self.assertGreaterEqual(down["details"]["wick_ratio"], 0.3)

    def test_where_the_bar_closes_is_what_decides_how_many_sides_can_claim_it(self):
        """The narrowness of the shape, stated exactly. Both wicks can be
        present on any wide bar; what makes BOTH sweeps claim it is the close
        landing back inside the range the prior twenty bars laid down. Close
        above the swing high and only the bullish sweep survives (the bearish
        one needs close < swing_high); close below the swing low and only the
        bearish one does.

        So the market shape is not "a volatile bar" — it is a full round trip
        through both stop pools that ends where it started.
        """
        from signals.evaluators_advanced import _eval_liquidity_sweep
        bull = {"direction": "bullish_sweep", "lookback": 20, "wick_pct": 0.3}
        bear = {"direction": "bearish_sweep", "lookback": 20, "wick_pct": 0.3}
        expected = {
            102.0: (True, True),    # back inside the coil — both claim it
            107.0: (True, False),   # closed above the high — an upside break
            97.0: (False, True),    # closed below the low — a downside break
        }
        for i, (close, (want_bull, want_bear)) in enumerate(expected.items()):
            with self.subTest(close=close):
                inst = _instrument(f"SWEEPCLOSE{i}")
                bars = _double_sweep_bars()
                bars[-1] = (102.4, 110.0, 92.5, close, 4000)
                _seed_bars(inst, bars)
                now = timezone.now()
                self.assertEqual(
                    _eval_liquidity_sweep(bull, inst, now)["matched"], want_bull)
                self.assertEqual(
                    _eval_liquidity_sweep(bear, inst, now)["matched"], want_bear)

    def test_both_imbalance_directions_live_in_the_same_five_bar_window(self):
        """fair_value_gap scans up to `max_age` triples and returns the first
        hit, so one window can hold a bullish gap and a bearish gap at once —
        the FVG legs do not separate the two setups either."""
        from signals.evaluators_advanced import _eval_fair_value_gap
        inst = _instrument("FVGBOTH")
        _seed_bars(inst, _double_sweep_bars())
        now = timezone.now()
        up = _eval_fair_value_gap({"direction": "bullish", "max_age": 5},
                                  inst, now)
        down = _eval_fair_value_gap({"direction": "bearish", "max_age": 5},
                                    inst, now)
        self.assertTrue(up["matched"], up["details"])
        self.assertTrue(down["matched"], down["details"])

    def test_each_setup_on_its_own_flags_that_instrument(self):
        """Scored one at a time — which is what `scan_setup` does for any
        direct caller — both setups clear 0.65 on the same bar. Nothing in
        the per-pair path can see the problem, because the problem is a
        property of the pair.

        The two scores are pinned rather than merely compared to the bar,
        because their SHAPE is the finding. The short is the fresher read: its
        break printed on the current bar, so both its recency terms are 1.0.
        The long's break is two bars back, which costs it a third of each
        recency term (4/6) and lands it at 0.796. Neither can reach 1.00 while
        the other matches — one bar cannot carry both breaks — so a pair of
        perfect scores is no longer the thing to look for.
        """
        from signals.opportunity_scanner import scan_setup
        inst = _instrument("SMCPAIR")
        _seed_bars(inst, _double_sweep_bars())
        long_res = scan_setup(_setup("advanced_smc_long"), inst,
                              now=timezone.now(), as_of=False)
        short_res = scan_setup(_setup("advanced_smc_short"), inst,
                               now=timezone.now(), as_of=False)
        self.assertTrue(long_res["matched"])
        self.assertTrue(short_res["matched"])
        self.assertAlmostEqual(long_res["score"], 0.7961, places=3)
        self.assertAlmostEqual(short_res["score"], 0.885, places=3)


# ══════════════════════════════════════════════════════════════════════════
# 2. The guard: one pass does not publish both sides
# ══════════════════════════════════════════════════════════════════════════

class ContradictionGuardTests(TestCase):
    """`scan_all_setups` defers publication until the whole pass is scored,
    then drops every match on an instrument its setups disagree about."""

    def test_the_pass_publishes_neither_side_of_a_contradiction(self):
        from signals.models import OpportunityFlag, Signal
        from signals.opportunity_scanner import scan_all_setups
        inst = _instrument("WHIPSAW")
        _seed_bars(inst, _double_sweep_bars())
        _setup("advanced_smc_long")
        _setup("advanced_smc_short")

        result = scan_all_setups()

        self.assertEqual(result["matches"], 0)
        self.assertEqual(result["contradiction_skipped"], 2)
        # Fail towards NOT trading: no flag, and — the part that matters —
        # no Signal, because a Signal is what the bots actually vote on.
        self.assertEqual(OpportunityFlag.objects.count(), 0)
        self.assertEqual(
            Signal.objects.filter(instrument=inst).count(), 0,
            msg="a bullish and a bearish Signal at one instant grade two "
                "rules on a coin flip and feed that back into the weights")

    def test_neither_side_wins_by_sorting_first(self):
        """Suppressing whichever match arrived second would hand the trade to
        whichever setup happened to sort first — which is arbitrary, and worse
        than either honest answer. Both orderings publish nothing."""
        from signals.models import Signal
        from signals.opportunity_scanner import scan_all_setups
        inst = _instrument("WHIPSAW2")
        _seed_bars(inst, _double_sweep_bars())
        long_setup = _setup("advanced_smc_long")
        short_setup = _setup("advanced_smc_short")
        # Setups are iterated in name order; rename so the bearish one leads.
        long_setup.name = "zz_smc_long"
        long_setup.save(update_fields=["name"])
        short_setup.name = "aa_smc_short"
        short_setup.save(update_fields=["name"])

        result = scan_all_setups()
        self.assertEqual(result["matches"], 0)
        self.assertEqual(result["contradiction_skipped"], 2)
        self.assertEqual(Signal.objects.filter(instrument=inst).count(), 0)

    def test_the_suppression_is_scoped_to_the_instrument_that_disagreed(self):
        """A whipsaw on one symbol must not silence a clean setup on another —
        the guard is per instrument, not per pass."""
        from signals.models import OpportunityFlag
        from signals.opportunity_scanner import scan_all_setups
        whip = _instrument("WHIPSAW3")
        clean = _instrument("CLEANLONG")
        _seed_bars(whip, _double_sweep_bars())
        _seed_bars(clean, _bullish_sweep_only_bars())
        _setup("advanced_smc_long")
        _setup("advanced_smc_short")

        result = scan_all_setups()

        self.assertEqual(result["contradiction_skipped"], 2)
        self.assertEqual(result["matches"], 1)
        flags = list(OpportunityFlag.objects.all())
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0].instrument_id, clean.id)
        self.assertEqual(flags[0].direction, "bullish")

    def test_setups_that_agree_are_not_suppressed(self):
        """Two setups pointing the same way at one instrument is
        CONFIRMATION, and the guard must leave it completely alone."""
        from signals.models import OpportunityFlag
        from signals.opportunity_scanner import scan_all_setups
        inst = _instrument("AGREE1")
        _seed_bars(inst, _double_sweep_bars())
        long_setup = _setup("advanced_smc_long")
        twin = _setup("advanced_smc_short")
        # Same conditions as the long, published under a second name.
        twin.direction = "bullish"
        twin.conditions = long_setup.conditions
        twin.save(update_fields=["direction", "conditions"])

        result = scan_all_setups()

        self.assertEqual(result["contradiction_skipped"], 0)
        self.assertEqual(result["matches"], 2)
        self.assertEqual(OpportunityFlag.objects.count(), 2)

    def test_a_neutral_setup_contradicts_nothing(self):
        """Only bullish-vs-bearish is a contradiction. A neutral setup states
        no direction, so it cannot be on the other side of one."""
        from signals.opportunity_scanner import scan_all_setups
        inst = _instrument("NEUTRAL1")
        _seed_bars(inst, _double_sweep_bars())
        _setup("advanced_smc_long")
        short_setup = _setup("advanced_smc_short")
        short_setup.direction = "neutral"
        short_setup.save(update_fields=["direction"])

        result = scan_all_setups()
        self.assertEqual(result["contradiction_skipped"], 0)
        self.assertEqual(result["matches"], 2)

    def test_the_counters_still_account_for_every_evaluation(self):
        """`contradiction_skipped` names pairs that reached the composite, so
        it is a sub-count of `scored` like `no_price_data` — it must not
        appear in the partition of `evaluations` or the identity the operator
        reads the funnel by stops adding up."""
        from signals.opportunity_scanner import scan_all_setups
        _seed_bars(_instrument("ACCT1"), _double_sweep_bars())
        _instrument("ACCTX", asset_class="commodity")   # outside both setups
        _setup("advanced_smc_long")
        _setup("advanced_smc_short")

        result = scan_all_setups()

        self.assertEqual(
            result["scored"] + result["asset_class_skipped"]
            + result["gate_skipped"] + result["errors"],
            result["evaluations"],
        )
        self.assertEqual(result["asset_class_skipped"], 2)
        self.assertEqual(result["scored"], 2)
        self.assertEqual(result["contradiction_skipped"], 2)

    def test_the_new_keys_do_not_recolour_a_healthy_scan(self):
        """`judge_result` reads a bare `skipped` as "not configured" and
        parsed/stored/... as work counts; a new counter named into either
        vocabulary would turn every suppressed whipsaw into a component
        health warning."""
        from core.task_gate import judge_result
        from signals.opportunity_scanner import scan_all_setups
        _seed_bars(_instrument("HEALTH1"), _double_sweep_bars())
        _setup("advanced_smc_long")
        _setup("advanced_smc_short")

        result = scan_all_setups()

        self.assertEqual(judge_result(result)[0], "success")
        WORK_AND_DONE = {"parsed", "attempted", "stored", "written", "saved",
                         "fetched", "observations_saved", "bars_saved",
                         "articles", "skipped"}
        self.assertEqual(set(result) & WORK_AND_DONE, set())

    def test_emit_false_scores_the_pair_and_writes_nothing(self):
        """The deferral is what makes the symmetric answer possible, so the
        no-write half of it is worth pinning on its own."""
        from signals.models import OpportunityFlag, Signal
        from signals.opportunity_scanner import scan_setup
        inst = _instrument("DRY1")
        _seed_bars(inst, _double_sweep_bars())
        res = scan_setup(_setup("advanced_smc_long"), inst,
                         now=timezone.now(), as_of=False, emit=False)
        self.assertTrue(res["matched"])
        self.assertTrue(res["pending"])
        self.assertAlmostEqual(res["score"], 0.7961, places=3)
        self.assertEqual(res["last_price"], 99.0)
        self.assertEqual(OpportunityFlag.objects.count(), 0)
        self.assertEqual(Signal.objects.count(), 0)


# ══════════════════════════════════════════════════════════════════════════
# 3. The engine already refuses to take both sides
# ══════════════════════════════════════════════════════════════════════════

class EngineRefusesBothSidesTests(TestCase):
    """The briefing's "net-zero-minus-spread TRADE" does not exist. Three
    independent things in `bot_program/asset_engine/base.py` stop it, and one
    of them alone would be enough. Nothing was added here; these pin what is
    already load-bearing so a later edit cannot quietly remove it."""

    def test_the_weighted_path_nets_two_opposite_signals_to_hold(self):
        """`decide()`'s default path subtracts the opposing side instead of
        vetoing it. On a genuine contradiction the two sides cancel and the
        net falls under min_net_weight — so the whipsaw bar produces no
        entry, in either direction."""
        from bot_program.asset_engine import StockBot
        cfg = _config(_user("weighted_u"), symbols=["ENG1"])
        _signal("ENG1", "bullish", 0.95, "advanced_smc_long")
        _signal("ENG1", "bearish", 0.95, "advanced_smc_short")
        decision = StockBot(cfg).decide("ENG1")
        self.assertEqual(decision.direction, "HOLD")

    def test_the_headcount_path_vetoes_outright(self):
        """With weighting opted out, `and not bearish` is a hard veto — any
        disagreement at all is a HOLD, whatever the scores."""
        from bot_program.asset_engine import StockBot
        cfg = _config(_user("headcount_u"), symbols=["ENG2"],
                      extras={"use_weighted_consensus": False})
        _signal("ENG2", "bullish", 0.99, "advanced_smc_long")
        _signal("ENG2", "bearish", 0.61, "advanced_smc_short")
        decision = StockBot(cfg).decide("ENG2")
        self.assertEqual(decision.direction, "HOLD")

    def test_lopsided_evidence_picks_a_side_it_never_takes_both(self):
        """The structural reason both sides are unreachable: `decide()`
        returns ONE BotDecision and `scan_symbol` consults it once per symbol
        per tick, so there is no code path that opens two.

        This is also the residual harm the netting leaves behind, named
        honestly: when one rule has earned a much heavier weight than its
        mirror, the net clears the threshold and a full-size entry is taken
        on a bar that carried no directional information at all. One trade,
        not two — a worse entry, not a self-cancelling pair. The scanner-side
        guard is what stops that pair of Signals existing in the first place."""
        from unittest import mock
        from bot_program.asset_engine import StockBot
        cfg = _config(_user("lopsided_u"), symbols=["ENG3"])
        _signal("ENG3", "bullish", 0.95, "advanced_smc_long")
        _signal("ENG3", "bearish", 0.95, "advanced_smc_short")
        weights = {"advanced_smc_long": 2.0, "advanced_smc_short": 0.25}
        with mock.patch("bot_program.asset_engine.aggregation.rule_weight",
                        side_effect=lambda rule, *a, **kw: weights.get(rule, 1.0)):
            decision = StockBot(cfg).decide("ENG3")
        self.assertEqual(decision.direction, "BUY")

    def test_scan_symbol_refuses_a_second_entry_while_one_is_on(self):
        """The backstop, for the case where two ticks disagree rather than two
        setups: an open position on the symbol ends the scan before `decide()`
        is ever consulted, so the reversal cannot be stacked on top."""
        from bot_program.asset_engine import StockBot
        from bot_program.asset_engine import skips
        from bot_program.models import AssetBotTrade
        cfg = _config(_user("already_u"), symbols=["ENG4"])
        _instrument("ENG4")
        AssetBotTrade.objects.create(
            config=cfg, asset_class="stock", symbol="ENG4", side="BUY",
            qty=Decimal("1"), entry_price=Decimal("100"), status="OPEN",
        )
        _signal("ENG4", "bearish", 0.99, "advanced_smc_short")

        self.assertIsNone(StockBot(cfg).scan_symbol("ENG4"))
        cfg.refresh_from_db()
        self.assertEqual(skips.last_by_symbol(cfg)["ENG4"]["code"],
                         skips.ALREADY_OPEN)
        self.assertEqual(AssetBotTrade.objects.filter(config=cfg).count(), 1)


# ══════════════════════════════════════════════════════════════════════════
# 4. The starter pair: the briefing is wrong three times over
# ══════════════════════════════════════════════════════════════════════════

class StarterPairIsNotDegenerateTests(TestCase):
    """starter_commodity_vol_compression vs starter_stock_mean_reversion is
    Jaccard 1.0 on kinds and nothing else. There is no market shape under
    which they produce opposite trades on one instrument, because there is no
    market shape under which they meet."""

    def test_both_setups_are_bullish_so_neither_can_oppose_the_other(self):
        a = _setup("starter_commodity_vol_compression", pack="starter")
        b = _setup("starter_stock_mean_reversion", pack="starter")
        self.assertEqual(a.direction, "bullish")
        self.assertEqual(b.direction, "bullish")

    def test_their_universes_are_disjoint_so_they_never_meet(self):
        """asset_class is a single field on Instrument, so no row is both a
        commodity and a stock. `scan_setup`'s asset-class gate drops each
        setup on the other's symbols before a single condition is read."""
        a = _setup("starter_commodity_vol_compression", pack="starter")
        b = _setup("starter_stock_mean_reversion", pack="starter")
        self.assertEqual(set(a.asset_classes) & set(b.asset_classes), set())

    def test_breakout_high_and_below_ma_cannot_both_match_one_series(self):
        """The arithmetic, which holds for every possible series: breakout_high
        needs the last close above all 20 priors, and below_ma's mean is taken
        over the last close plus 19 of those same priors — so a close above
        every prior is necessarily above their mean. One excludes the other."""
        from signals.opportunity_scanner import _eval_price_pattern
        now = timezone.now()

        rally = _instrument("STARTER_UP")
        _seed_bars(rally, [(p, p, p, p, 1000)
                           for p in (100.0 + i * 0.5 for i in range(40))])
        breakout = _eval_price_pattern(
            {"pattern": "breakout_high", "lookback": 20}, rally, now)
        below = _eval_price_pattern(
            {"pattern": "below_ma", "ma_period": 20}, rally, now)
        self.assertTrue(breakout["matched"])
        self.assertFalse(below["matched"])

        washout = _instrument("STARTER_DOWN")
        _seed_bars(washout, [(p, p, p, p, 1000)
                             for p in (100.0 - i * 0.4 for i in range(40))])
        self.assertFalse(_eval_price_pattern(
            {"pattern": "breakout_high", "lookback": 20}, washout, now)["matched"])
        self.assertTrue(_eval_price_pattern(
            {"pattern": "below_ma", "ma_period": 20}, washout, now)["matched"])

    def test_a_pass_over_both_universes_reports_no_contradiction(self):
        """End to end: one commodity, one stock, both setups active. The
        guard has nothing to do, which is the correct answer."""
        from signals.opportunity_scanner import scan_all_setups
        _setup("starter_commodity_vol_compression", pack="starter")
        _setup("starter_stock_mean_reversion", pack="starter")
        _seed_bars(_instrument("WTIUSD", asset_class="commodity"),
                   [(p, p, p, p, 1000)
                    for p in (70.0 + i * 0.1 for i in range(40))])
        _seed_bars(_instrument("STK1", asset_class="stock"),
                   [(p, p, p, p, 1000)
                    for p in (100.0 - i * 0.4 for i in range(40))])

        result = scan_all_setups()

        self.assertEqual(result["contradiction_skipped"], 0)
        # Each setup was gated off the other's instrument by asset class.
        self.assertEqual(result["asset_class_skipped"], 2)


# ══════════════════════════════════════════════════════════════════════════
# 5. Making the overlap visible, honestly
# ══════════════════════════════════════════════════════════════════════════

class ConditionOverlapTests(TestCase):
    """`setup_overlap` is the number the briefing should have quoted. The gap
    between `kind_jaccard` and `jaccard` IS the finding, so both are reported
    rather than the second silently replacing the first."""

    def test_the_smc_pair_reads_1_00_on_kinds_and_0_14_once_direction_counts(self):
        """Four kinds each, all four shared, so a kind-only audit still calls
        them one rule twice. Direction-aware, one of the eight fingerprints is
        common — the pair grew a structure leg and a sequence leg since this
        was 0.20, and both of those point a direction, so the honest overlap
        fell as the setups became more different from each other."""
        from signals.opportunity_scanner import setup_overlap
        ov = setup_overlap(_setup("advanced_smc_long"),
                           _setup("advanced_smc_short"))
        self.assertEqual(ov["kind_jaccard"], 1.0)
        self.assertEqual(ov["jaccard"], 0.1429)          # one of seven
        # Only the direction-neutral leg is genuinely shared.
        self.assertEqual(ov["shared"], ["relative_volume"])
        self.assertTrue(ov["opposite_direction"])
        self.assertTrue(ov["shares_universe"])

    def test_the_starter_pair_shares_nothing_at_all(self):
        from signals.opportunity_scanner import setup_overlap
        ov = setup_overlap(_setup("starter_commodity_vol_compression",
                                  pack="starter"),
                           _setup("starter_stock_mean_reversion",
                                  pack="starter"))
        self.assertEqual(ov["kind_jaccard"], 1.0)
        self.assertEqual(ov["jaccard"], 0.0)
        self.assertEqual(ov["shared"], [])
        self.assertFalse(ov["shares_universe"])
        self.assertFalse(ov["opposite_direction"])

    def test_a_real_duplicate_still_scores_1_00(self):
        """The metric has to be capable of saying yes, or it is just a way of
        making every pair look fine."""
        from signals.models_opportunity import OpportunitySetup
        from signals.opportunity_scanner import setup_overlap
        a = _setup("advanced_smc_long")
        b = OpportunitySetup.objects.create(
            name="advanced_smc_long_copy", description="", direction="bullish",
            asset_classes=list(a.asset_classes), conditions=a.conditions,
            min_match_score=a.min_match_score, suggested_horizon_days=5,
            sizing={}, is_active=True,
        )
        ov = setup_overlap(a, b)
        self.assertEqual(ov["jaccard"], 1.0)
        self.assertEqual(ov["kind_jaccard"], 1.0)
        self.assertEqual(ov["only_a"], [])
        self.assertEqual(ov["only_b"], [])

    def test_tuning_params_are_not_identity(self):
        """Two setups differing only in threshold ARE the same detector, and
        folding lookbacks into the fingerprint would hide that behind a low
        score — the failure opposite to the one being fixed."""
        from signals.models_opportunity import OpportunitySetup
        from signals.opportunity_scanner import setup_overlap
        a = _setup("advanced_smc_long")
        loosened = []
        for cond in a.conditions:
            cond = dict(cond, params=dict(cond["params"]))
            if "lookback" in cond["params"]:
                cond["params"]["lookback"] = 40
            if "threshold" in cond["params"]:
                cond["params"]["threshold"] = 3.0
            loosened.append(cond)
        b = OpportunitySetup.objects.create(
            name="advanced_smc_long_loose", description="", direction="bullish",
            asset_classes=list(a.asset_classes), conditions=loosened,
            min_match_score=a.min_match_score, suggested_horizon_days=5,
            sizing={}, is_active=True,
        )
        self.assertEqual(setup_overlap(a, b)["jaccard"], 1.0)

    def test_a_gate_is_a_universe_not_a_leg(self):
        """Two setups sharing only `quote_currency: USD` have nothing in
        common but where they run, and must not read as overlapping."""
        from signals.models_opportunity import OpportunitySetup
        from signals.opportunity_scanner import setup_overlap
        common_gate = {"kind": "quote_currency",
                       "params": {"currency": "USD"}, "gate": True}
        a = OpportunitySetup.objects.create(
            name="gate_a", description="", direction="bullish",
            asset_classes=["forex"],
            conditions=[common_gate,
                        {"kind": "price_pattern",
                         "params": {"pattern": "breakout_high"}, "weight": 1.0}],
            min_match_score=0.6, suggested_horizon_days=5, sizing={},
        )
        b = OpportunitySetup.objects.create(
            name="gate_b", description="", direction="bearish",
            asset_classes=["forex"],
            conditions=[common_gate,
                        {"kind": "hurst_regime",
                         "params": {"regime": "trending"}, "weight": 1.0}],
            min_match_score=0.6, suggested_horizon_days=5, sizing={},
        )
        ov = setup_overlap(a, b)
        self.assertEqual(ov["shared"], [])
        self.assertEqual(ov["jaccard"], 0.0)

    def test_nothing_to_compare_reads_unknown_not_zero(self):
        """A setup with no scoring conditions has an UNMEASURED overlap. 0.0
        would claim it was measured and found disjoint, and an operator
        retires rules on that number."""
        from signals.models_opportunity import OpportunitySetup
        from signals.opportunity_scanner import setup_overlap
        empty_a = OpportunitySetup.objects.create(
            name="empty_a", description="", direction="bullish",
            asset_classes=[], conditions=[], min_match_score=0.6,
            suggested_horizon_days=5, sizing={})
        empty_b = OpportunitySetup.objects.create(
            name="empty_b", description="", direction="bearish",
            asset_classes=[], conditions=[], min_match_score=0.6,
            suggested_horizon_days=5, sizing={})
        ov = setup_overlap(empty_a, empty_b)
        self.assertIsNone(ov["jaccard"])
        self.assertIsNone(ov["kind_jaccard"])

    def test_a_direction_free_kind_fingerprints_as_itself(self):
        from signals.opportunity_scanner import condition_fingerprint
        self.assertEqual(
            condition_fingerprint({"kind": "relative_volume",
                                   "params": {"period": 20, "threshold": 1.5}}),
            "relative_volume")
        self.assertEqual(
            condition_fingerprint({"kind": "liquidity_sweep",
                                   "params": {"direction": "bearish_sweep",
                                              "lookback": 20}}),
            "liquidity_sweep[direction=bearish_sweep]")
