"""Seeded-condition param integrity + as-of correctness.

The defect this file exists to prevent
--------------------------------------

Every evaluator reads its params with `.get(key, default)`. A seeded key the
evaluator never reads therefore produces no error, no warning and no log line —
the condition just runs on defaults, or fails a required-param check and returns
matched=False forever. Twelve setups were seeded and activated on the live
platform with five of the six starter setups carrying such keys, which is why
the platform reported zero rule track records while the tape trended.

`test_phase31_strategy_seed` already asserted that each condition's `kind` is
registered. That check passes for every one of those five setups. The kind was
never the problem; the params were.

The guard here closes that hole in five steps:

  1. every registered kind declares the param keys it consumes, next to
     `register_kind` (`PARAM_KEYS` in signals.opportunity_scanner);
  2. the declaration is verified against the evaluator's own source by AST —
     so a declaration cannot drift from the function it describes;
  3. every seeded condition, starter pack and advanced pack, is asserted to
     carry only declared keys;
  4. keys are not enough, so the closed VALUE vocabularies are declared too
     (`PARAM_CHOICES`) and asserted the same way. `pattern: "rsi_oversold"`
     passes every key check and is inert forever, and on a two-branch
     evaluator an unrecognised `direction` does not go quiet — it selects the
     opposite branch;
  5. `sizing` never passes through the registry at all, so `SIZING_KEYS`
     declares what the level builder reads and both packs are checked against
     it.

Plus, per repaired setup, a test that builds fixture data and proves the setup
now MATCHES end-to-end: a setup that cannot be made to match in a test cannot
match in production either.

Plus as-of tests for the evaluators that used to read present-day state
regardless of the `now` they were handed, and for the price lookup that used
to decide "is this a replay" from elapsed wall clock.

Plus re-seed tests: pressing the admin panel's Seed Strategies button is the
only way a repaired condition reaches a row that already exists, so a re-run
has to refresh definitions without touching promotion stage, pause state,
allocator budget, notes, or whether a setup is armed.

Run with:  python manage.py test tests.test_seed_param_integrity
"""
import ast
import inspect
import textwrap
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone


# ── Fixture helpers ────────────────────────────────────────────────────────

def _instrument(symbol, asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class},
    )
    return inst


def _seed_prices(instrument, closes, end=None, volume=1000):
    """Daily bars, oldest first, one per day ending just before `end`."""
    from market_data.models import PriceData
    end = end or timezone.now()
    rows = []
    for i, c in enumerate(closes):
        ts = end - timedelta(days=len(closes) - i)
        rows.append(PriceData(
            instrument=instrument, timeframe="1d", timestamp=ts,
            open=Decimal(str(c)), high=Decimal(str(c)), low=Decimal(str(c)),
            close=Decimal(str(c)), volume=volume, source="test",
        ))
    PriceData.objects.bulk_create(rows)


def _seed_macro(series_id, observations, last_value=None):
    """observations: [(date, value), ...].

    `last_value` defaults to the newest observation's value, which is what the
    two columns look like on an observation date's FIRST appearance — NOT an
    invariant. The FRED ingest writes history rows with get_or_create and
    reassigns last_value unconditionally, so a revision under the same
    observation date leaves them disagreeing; pass `last_value` explicitly to
    build that world.
    """
    from market_data.models import MacroIndicator, MacroObservation
    indicator = MacroIndicator.objects.create(
        series_id=series_id, name=series_id, category="macro", frequency="daily",
    )
    for d, v in observations:
        MacroObservation.objects.create(indicator=indicator, date=d, value=Decimal(str(v)))
    if observations:
        newest = max(observations, key=lambda o: o[0])
        indicator.last_value = Decimal(str(last_value if last_value is not None else newest[1]))
        indicator.last_date = newest[0]
        indicator.save()
    return indicator


# FRED dates a quarterly observation at the QUARTER START and BEA publishes the
# advance estimate ~30 days after the quarter ENDS. Any test that seeds a
# quarterly series has to respect both, or it proves something about a world
# that cannot exist: an observation dated ten days ago would need BEA to have
# published a quarter before that quarter began.
GDP_RELEASE_LAG_DAYS = 30


def _quarter_start(d):
    from datetime import date
    return date(d.year, ((d.month - 1) // 3) * 3 + 1, 1)


def _quarter_end(q):
    from datetime import date
    return date(q.year + 1, 1, 1) if q.month == 10 else date(q.year, q.month + 3, 1)


def _released_quarter_starts(today, n):
    """The `n` most recent quarter starts BEA would have published by `today`,
    oldest first."""
    from datetime import timedelta
    out = []
    q = _quarter_start(today)
    while len(out) < n:
        if _quarter_end(q) + timedelta(days=GDP_RELEASE_LAG_DAYS) <= today:
            out.append(q)
        q = _quarter_start(q - timedelta(days=1))
    return list(reversed(out))


def _seed_cot(instrument, report_date, nc_long, nc_short):
    from scraping.models import COTReport
    return COTReport.objects.create(
        instrument=instrument, report_date=report_date,
        commercial_long=nc_short, commercial_short=nc_long,
        non_commercial_long=nc_long, non_commercial_short=nc_short,
        open_interest=nc_long + nc_short,
        net_speculative=nc_long - nc_short,
    )


def _seed_news(symbol, count, sentiment=0.5):
    from scraping.models import NewsArticle
    NewsArticle.objects.bulk_create([
        NewsArticle(
            title=f"{symbol} beats earnings, guidance raised ({i})",
            source="test", url=f"http://example.com/{symbol}/{i}",
            published_at=timezone.now() - timedelta(hours=i + 1),
            content_summary=f"Coverage of {symbol}.",
            ai_sentiment_score=sentiment,
        )
        for i in range(count)
    ])


def _seeded_conditions():
    """(pack, setup_name, condition) for every condition in every seed pack."""
    from signals.management.commands import seed_strategies, seed_advanced_strategies
    out = []
    for pack, mod in (("starter", seed_strategies), ("advanced", seed_advanced_strategies)):
        for spec in mod._setup_definitions():
            for cond in spec["conditions"]:
                out.append((pack, spec["name"], cond))
    return out


def _setup_from_seed(name):
    """Build the OpportunitySetup row exactly as the seeder would, active."""
    from signals.management.commands import seed_strategies
    from signals.models_opportunity import OpportunitySetup
    spec = next(s for s in seed_strategies._setup_definitions() if s["name"] == name)
    return OpportunitySetup.objects.create(
        name=spec["name"], description=spec["description"],
        direction=spec["direction"], asset_classes=spec["asset_classes"],
        conditions=spec["conditions"], min_match_score=spec["min_match_score"],
        suggested_horizon_days=spec["suggested_horizon_days"],
        sizing=spec.get("sizing", {}), is_active=True,
    )


# ── The guard ──────────────────────────────────────────────────────────────

def _dict_keys_read_by(fn, arg_name):
    """Every literal key `fn` pulls out of its `arg_name` argument.

    Evaluators read params exactly one way — `(params or {}).get("key", ...)`
    — so the AST tells us what the function actually consumes without anyone
    having to keep a list in their head. Raises on a non-literal key, because a
    computed key is a read this guard cannot see and must not silently ignore.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    keys = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "get"):
            continue
        target = func.value
        if isinstance(target, ast.BoolOp) and isinstance(target.op, ast.Or):
            target = target.values[0]
        if not (isinstance(target, ast.Name) and target.id == arg_name):
            continue
        if not node.args:
            continue
        key = node.args[0]
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
            raise AssertionError(
                f"{fn.__name__} reads {arg_name} with a non-literal key; the "
                f"guard cannot introspect it"
            )
        keys.add(key.value)
    return keys


def _params_keys_read_by(fn):
    return _dict_keys_read_by(fn, "params")


class ParamDeclarationGuardTests(TestCase):
    def test_every_registered_kind_declares_its_param_keys(self):
        from signals.opportunity_scanner import EVALUATOR_REGISTRY, PARAM_KEYS
        missing = sorted(set(EVALUATOR_REGISTRY) - set(PARAM_KEYS))
        self.assertEqual(
            missing, [],
            msg=("register_kind(..., params=(...)) is how a seeded condition "
                 f"gets checked at all; these kinds declare nothing: {missing}"),
        )

    def test_declarations_match_what_each_evaluator_reads(self):
        from signals.opportunity_scanner import EVALUATOR_REGISTRY, PARAM_KEYS
        for kind, fn in sorted(EVALUATOR_REGISTRY.items()):
            with self.subTest(kind=kind):
                actual = _params_keys_read_by(fn)
                self.assertEqual(
                    PARAM_KEYS[kind], frozenset(actual),
                    msg=(f"{kind}: declared {sorted(PARAM_KEYS[kind])} but "
                         f"{fn.__name__} reads {sorted(actual)}"),
                )

    def test_seeded_conditions_reference_registered_kinds(self):
        from signals.opportunity_scanner import EVALUATOR_REGISTRY
        for pack, name, cond in _seeded_conditions():
            with self.subTest(pack=pack, setup=name, kind=cond.get("kind")):
                self.assertIn(cond.get("kind"), EVALUATOR_REGISTRY)

    def test_every_seeded_param_key_is_one_the_evaluator_reads(self):
        """The check that would have caught all five inert starter setups."""
        from signals.opportunity_scanner import param_keys, unknown_param_keys
        for pack, name, cond in _seeded_conditions():
            kind = cond.get("kind")
            with self.subTest(pack=pack, setup=name, kind=kind):
                unknown = unknown_param_keys(kind, cond.get("params") or {})
                self.assertEqual(
                    unknown, [],
                    msg=(f"{name} → {kind} seeds {unknown}, which the evaluator "
                         f"never reads: the condition silently runs on defaults "
                         f"or can never match. Accepted: {sorted(param_keys(kind))}"),
                )

    def test_unknown_kind_reports_every_key_as_unconsumed(self):
        from signals.opportunity_scanner import unknown_param_keys
        self.assertEqual(unknown_param_keys("no_such_kind", {"a": 1, "b": 2}), ["a", "b"])

    def test_every_declared_choice_appears_in_the_evaluator_it_describes(self):
        """A vocabulary that names a value the function never mentions is a
        typo, and a typo here is worse than no declaration: it would reject the
        value the evaluator does accept."""
        from signals.opportunity_scanner import EVALUATOR_REGISTRY, PARAM_CHOICES
        for kind, declared in sorted(PARAM_CHOICES.items()):
            source = inspect.getsource(EVALUATOR_REGISTRY[kind])
            for key, values in sorted(declared.items()):
                for value in sorted(values):
                    with self.subTest(kind=kind, key=key, value=value):
                        self.assertIn(
                            f'"{value}"', source,
                            msg=(f"{kind} declares {key}={value!r} but the "
                                 f"evaluator's source never mentions it"),
                        )

    def test_every_seeded_param_value_is_one_the_evaluator_branches_on(self):
        """Keys were never the whole story. `direction: "long_increasing"` on
        cot_report and `pattern: "rsi_oversold"` on price_pattern both pass the
        key check and are both permanently inert — and on the two-branch
        evaluators an unrecognised value does not go quiet, it silently selects
        the opposite branch."""
        from signals.opportunity_scanner import invalid_param_values
        for pack, name, cond in _seeded_conditions():
            kind = cond.get("kind")
            with self.subTest(pack=pack, setup=name, kind=kind):
                self.assertEqual(
                    invalid_param_values(kind, cond.get("params") or {}), [],
                )

    def test_an_out_of_vocabulary_value_is_reported(self):
        from signals.opportunity_scanner import invalid_param_values
        self.assertTrue(invalid_param_values(
            "price_pattern", {"pattern": "rsi_oversold"}))
        self.assertTrue(invalid_param_values(
            "cot_report", {"direction": "long_increasing"}))
        self.assertEqual(invalid_param_values(
            "cot_report", {"direction": "long_extreme", "min_ratio": 0.25}), [])


class SizingKeyGuardTests(TestCase):
    """`sizing` never passes through the evaluator registry, so it inherited
    none of the param guard's protection — which is how six seeded setups
    shipped a `target_pct` nothing reads."""

    def test_sizing_declaration_matches_what_suggested_levels_reads(self):
        from signals.opportunity_scanner import SIZING_KEYS, _suggested_levels
        self.assertEqual(
            SIZING_KEYS, frozenset(_dict_keys_read_by(_suggested_levels, "sizing")),
        )

    def test_no_seeded_setup_carries_a_sizing_key_nobody_reads(self):
        from signals.management.commands import (
            seed_strategies, seed_advanced_strategies,
        )
        from signals.opportunity_scanner import unknown_sizing_keys
        for pack, mod in (("starter", seed_strategies),
                          ("advanced", seed_advanced_strategies)):
            for spec in mod._setup_definitions():
                with self.subTest(pack=pack, setup=spec["name"]):
                    self.assertEqual(
                        unknown_sizing_keys(spec.get("sizing") or {}), [],
                        msg=("a sizing key the level builder ignores is a "
                             "target the seed only appears to specify"),
                    )

    def test_seeded_targets_are_the_ratios_the_old_percentages_asked_for(self):
        """The three that were wrong: forex_breakout graded to +2.0% against an
        intended +2.5%, vol_compression to +10.0% against +12.0%, and
        usd_weakness to +4.0% against +6.0%, because target_rr fell to its 2.0
        default every time."""
        from signals.management.commands.seed_strategies import _setup_definitions
        expected = {
            "starter_stock_momentum": 2.0,
            "starter_stock_mean_reversion": 2.0,
            "starter_forex_breakout": 2.5,
            "starter_news_event_bullish": 2.0,
            "starter_commodity_vol_compression": 2.4,
            "starter_usd_weakness_macro": 3.0,
        }
        for spec in _setup_definitions():
            with self.subTest(setup=spec["name"]):
                self.assertAlmostEqual(
                    spec["sizing"]["target_rr"], expected[spec["name"]], places=6)

    def test_the_suggested_target_reaches_the_level_the_seed_asked_for(self):
        from signals.opportunity_scanner import _suggested_levels
        entry, stop, target = _suggested_levels(
            "bullish", 100.0, {"stop_pct": 1.0, "target_rr": 2.5})
        self.assertAlmostEqual(stop, 99.0, places=6)
        self.assertAlmostEqual(target, 102.5, places=6)


# ── Repaired setups can now match ──────────────────────────────────────────

class RepairedSetupMatchTests(TestCase):
    """One per starter setup: fixture data satisfying the conditions must
    produce an OpportunityFlag. Each of these failed before the repair."""

    def _scan(self, setup, inst):
        from signals.opportunity_scanner import scan_setup
        result = scan_setup(setup, inst)
        self.assertTrue(
            result.get("matched"),
            msg=(f"{setup.name} did not match: score={result.get('score')} "
                 f"conditions={result.get('conditions')}"),
        )
        return result

    def test_stock_momentum_matches_on_breakout_plus_rising_gdp(self):
        setup = _setup_from_seed("starter_stock_momentum")
        inst = _instrument("MOM1", asset_class="stock")
        # 61+ closes: the 60-bar breakout needs them, and used to be handed 55.
        _seed_prices(inst, [100.0 + i * 0.5 for i in range(80)])
        today = timezone.now().date()
        # Real FRED dating. The old fixture seeded a print dated ten days ago,
        # which BEA cannot produce, and that impossible spacing was the only
        # reason this test passed while the leg was dead in production. Two
        # prints is the evaluator's minimum and the calendar's worst case;
        # GDPReleaseCalendarTests proves the seeded window always holds them.
        quarters = _released_quarter_starts(today, 2)
        _seed_macro("GDP", [(q, 27000 + 200 * i) for i, q in enumerate(quarters)])
        result = self._scan(setup, inst)
        kinds = {c["kind"]: c for c in result["conditions"]}
        self.assertTrue(kinds["macro_trend"]["matched"])
        breakout = [c for c in result["conditions"]
                    if c["kind"] == "price_pattern"
                    and c["details"].get("prior_high") is not None]
        self.assertTrue(breakout and breakout[0]["matched"])

    def test_stock_mean_reversion_matches_on_violent_selloff(self):
        setup = _setup_from_seed("starter_stock_mean_reversion")
        inst = _instrument("MR1", asset_class="stock")
        # Zigzag around a steep decline: far below the 20-MA on >2%/day vol.
        closes = [100.0 * (0.95 ** i) * (1.06 if i % 2 == 0 else 0.94)
                  for i in range(30)]
        _seed_prices(inst, closes)
        result = self._scan(setup, inst)
        vol = next(c for c in result["conditions"] if c["kind"] == "volatility_regime")
        self.assertTrue(vol["matched"])
        self.assertGreaterEqual(vol["details"]["daily_vol_pct"], 2.0)

    def test_forex_breakout_matches_on_trending_pair(self):
        setup = _setup_from_seed("starter_forex_breakout")
        inst = _instrument("EURUSD1", asset_class="forex")
        _seed_prices(inst, [1.0000 + i * 0.0010 for i in range(60)])
        self._scan(setup, inst)

    def test_news_event_matches_on_catalyst_day(self):
        setup = _setup_from_seed("starter_news_event_bullish")
        inst = _instrument("NEWSX", asset_class="stock")
        _seed_prices(inst, [100.0] * 15 + [102.0, 104.0, 106.0, 108.0, 125.0])
        _seed_news("NEWSX", count=6, sentiment=0.9)
        result = self._scan(setup, inst)
        self.assertTrue(next(c for c in result["conditions"]
                             if c["kind"] == "news_volume")["matched"])
        self.assertTrue(next(c for c in result["conditions"]
                             if c["kind"] == "news_sentiment")["matched"])

    def test_commodity_vol_compression_matches_on_quiet_range_break(self):
        setup = _setup_from_seed("starter_commodity_vol_compression")
        inst = _instrument("XAUUSD1", asset_class="commodity")
        # A quiet grind, then the range breaks — compression into expansion.
        _seed_prices(inst, [100.0 + i * 0.05 for i in range(29)] + [103.0])
        result = self._scan(setup, inst)
        vol = next(c for c in result["conditions"] if c["kind"] == "volatility_regime")
        self.assertTrue(vol["matched"])
        self.assertEqual(vol["details"]["direction"], "below")

    def test_commodity_vol_compression_rejects_a_noisy_breakout(self):
        """The direction fix has to bite: the same breakout on a wild tape is
        exactly what this setup used to score highest."""
        from signals.opportunity_scanner import scan_setup
        setup = _setup_from_seed("starter_commodity_vol_compression")
        inst = _instrument("WTIUSD1", asset_class="commodity")
        closes = [100.0 * (1.08 if i % 2 == 0 else 0.94) for i in range(29)] + [200.0]
        _seed_prices(inst, closes)
        result = scan_setup(setup, inst)
        self.assertFalse(result.get("matched"))

    def _usd_weakness_world(self, symbol, *, seed_macro=True):
        """A tape where the dollar is unambiguously weak: 2y yield falling,
        specs net long the foreign contract currency.

        MacroIndicator.series_id is unique, so a caller sweeping several
        symbols seeds DGS2 once.
        """
        inst = _instrument(symbol, asset_class="forex")
        _seed_prices(inst, [1.05 + i * 0.001 for i in range(30)])
        today = timezone.now().date()
        if seed_macro:
            _seed_macro("DGS2", [(today - timedelta(days=50), 4.50),
                                 (today - timedelta(days=2), 4.00)])
        _seed_cot(inst, today - timedelta(days=5), nc_long=140000, nc_short=60000)
        return inst

    def test_usd_weakness_matches_on_falling_2y_plus_long_cot(self):
        setup = _setup_from_seed("starter_usd_weakness_macro")
        inst = self._usd_weakness_world("EURUSD")
        result = self._scan(setup, inst)
        self.assertTrue(next(c for c in result["conditions"]
                             if c["kind"] == "macro_trend")["matched"])
        self.assertTrue(next(c for c in result["conditions"]
                             if c["kind"] == "cot_report")["matched"])

    def test_usd_weakness_is_gated_off_usd_base_pairs(self):
        """The identical dollar-weakness evidence on USDJPY. Every leg fires;
        the setup must still produce nothing, because its one fixed
        direction='bullish' would be the exact inverse of its thesis on a pair
        the dollar is the BASE of."""
        from signals.opportunity_scanner import scan_setup
        from signals.models import Signal
        setup = _setup_from_seed("starter_usd_weakness_macro")
        inst = self._usd_weakness_world("USDJPY")
        result = scan_setup(setup, inst)
        self.assertFalse(result.get("matched"))
        self.assertEqual(result.get("reason"), "gate_failed")
        self.assertFalse(Signal.objects.filter(rule_name=setup.name).exists())

    def test_usd_weakness_gate_covers_every_usd_base_pair_in_its_universe(self):
        from signals.opportunity_scanner import scan_setup
        setup = _setup_from_seed("starter_usd_weakness_macro")
        for i, symbol in enumerate(("USDJPY", "USDCHF", "USDCAD", "USDMXN")):
            with self.subTest(symbol=symbol):
                inst = self._usd_weakness_world(symbol, seed_macro=(i == 0))
                result = scan_setup(setup, inst)
                self.assertFalse(result.get("matched"))

    def test_usd_weakness_gate_contributes_no_score_of_its_own(self):
        """A gate says WHERE, not how strongly. If it were weighted, the
        exclusion would rest on an arithmetic balance instead of a rule."""
        setup = _setup_from_seed("starter_usd_weakness_macro")
        inst = self._usd_weakness_world("EURUSD")
        result = self._scan(setup, inst)
        gate = next(c for c in result["conditions"]
                    if c["kind"] == "quote_currency")
        self.assertTrue(gate["gate"])
        # Only the two evidence legs (1.5 + 1.0) are in the denominator, so a
        # full match is exactly 1.0 rather than diluted by the gate's weight.
        self.assertEqual(result["score"], 1.0)

    def test_every_starter_setup_is_covered_by_a_match_test(self):
        """A setup added to the pack without a proof-of-match test is a setup
        nobody has shown can fire."""
        from signals.management.commands.seed_strategies import _setup_definitions
        covered = {
            "starter_stock_momentum", "starter_stock_mean_reversion",
            "starter_forex_breakout", "starter_news_event_bullish",
            "starter_commodity_vol_compression", "starter_usd_weakness_macro",
        }
        self.assertEqual({s["name"] for s in _setup_definitions()}, covered)


# ── As-of correctness ──────────────────────────────────────────────────────

class AsOfBoundaryTests(TestCase):
    """Four evaluators used to read present-day state whatever `now` said.
    Live scanning passes now=timezone.now(), so these bounds are no-ops there;
    they are what stops a replay from trading on data it could not have had."""

    def test_macro_regime_reads_the_value_as_of_now(self):
        from signals.opportunity_scanner import _eval_macro_regime
        today = timezone.now().date()
        _seed_macro("VIXCLS", [(today - timedelta(days=10), 12.0),
                               (today - timedelta(days=1), 40.0)])
        inst = _instrument("ASOF1")
        as_of = timezone.now() - timedelta(days=5)
        res = _eval_macro_regime(
            {"series_id": "VIXCLS", "direction": "above", "threshold": 30.0},
            inst, as_of,
        )
        self.assertFalse(res["matched"])
        self.assertEqual(res["details"]["value"], 12.0)
        self.assertEqual(res["details"]["last_date"], str(today - timedelta(days=10)))

    def test_macro_regime_still_sees_the_latest_print_when_live(self):
        from signals.opportunity_scanner import _eval_macro_regime
        today = timezone.now().date()
        _seed_macro("VIXCLS", [(today - timedelta(days=10), 12.0),
                               (today - timedelta(days=1), 40.0)])
        res = _eval_macro_regime(
            {"series_id": "VIXCLS", "direction": "above", "threshold": 30.0},
            _instrument("ASOF2"), timezone.now(),
        )
        self.assertTrue(res["matched"])
        self.assertEqual(res["details"]["value"], 40.0)

    def test_macro_regime_declines_to_answer_from_last_value_alone(self):
        """last_value has no history. With no observation behind it, unmatched
        is the honest answer — not today's number dressed as `now`'s."""
        from market_data.models import MacroIndicator
        from signals.opportunity_scanner import _eval_macro_regime
        MacroIndicator.objects.create(
            series_id="FEDFUNDS", name="Federal Funds Rate", category="macro",
            frequency="monthly", last_value=Decimal("5.25"),
            last_date=timezone.now().date(),
        )
        res = _eval_macro_regime(
            {"series_id": "FEDFUNDS", "direction": "above", "threshold": 1.0},
            _instrument("ASOF3"), timezone.now(),
        )
        self.assertFalse(res["matched"])
        self.assertIn("no observation", res["details"]["reason"])

    def test_macro_trend_ignores_observations_after_now(self):
        from signals.opportunity_scanner import _eval_macro_trend
        today = timezone.now().date()
        _seed_macro("M2SL", [(today - timedelta(days=50), 100.0),
                             (today - timedelta(days=40), 101.0),
                             (today - timedelta(days=1), 500.0)])
        as_of = timezone.now() - timedelta(days=20)
        res = _eval_macro_trend(
            {"series_id": "M2SL", "direction": "rising", "lookback_days": 60,
             "min_change_pct": 5.0},
            _instrument("ASOF4"), as_of,
        )
        self.assertFalse(res["matched"])
        self.assertEqual(res["details"]["n_observations"], 2)
        self.assertEqual(res["details"]["last_value"], 101.0)

    def test_cot_report_uses_the_newest_report_as_of_now(self):
        from signals.opportunity_scanner import _eval_cot_report
        inst = _instrument("ASOF5", asset_class="commodity")
        today = timezone.now().date()
        _seed_cot(inst, today - timedelta(days=30), nc_long=150000, nc_short=50000)
        _seed_cot(inst, today - timedelta(days=1), nc_long=50000, nc_short=150000)
        as_of = timezone.now() - timedelta(days=10)
        res = _eval_cot_report({"direction": "long_extreme", "min_ratio": 0.25},
                               inst, as_of)
        self.assertTrue(res["matched"])
        self.assertEqual(res["details"]["report_date"], str(today - timedelta(days=30)))

    def test_cot_report_sees_the_newest_report_when_live(self):
        from signals.opportunity_scanner import _eval_cot_report
        inst = _instrument("ASOF6", asset_class="commodity")
        today = timezone.now().date()
        _seed_cot(inst, today - timedelta(days=30), nc_long=150000, nc_short=50000)
        _seed_cot(inst, today - timedelta(days=1), nc_long=50000, nc_short=150000)
        res = _eval_cot_report({"direction": "long_extreme", "min_ratio": 0.25},
                               inst, timezone.now())
        self.assertFalse(res["matched"])
        self.assertEqual(res["details"]["report_date"], str(today - timedelta(days=1)))

    def test_smart_money_divergence_pairs_the_slope_with_an_as_of_report(self):
        from signals.evaluators_advanced import _eval_smart_money_divergence
        inst = _instrument("ASOF7", asset_class="commodity")
        today = timezone.now().date()
        as_of = timezone.now() - timedelta(days=10)
        # Rising price up to `as_of`; specs short as of then, long afterwards.
        _seed_prices(inst, [100.0 + i * 0.5 for i in range(40)], end=as_of)
        _seed_cot(inst, today - timedelta(days=30), nc_long=50000, nc_short=150000)
        _seed_cot(inst, today - timedelta(days=1), nc_long=150000, nc_short=50000)
        res = _eval_smart_money_divergence(
            {"slope_lookback": 20, "slope_threshold": 0.0005, "min_ratio": 0.3},
            inst, as_of,
        )
        self.assertTrue(res["matched"], msg=res["details"])
        self.assertEqual(res["details"]["report_date"], str(today - timedelta(days=30)))
        self.assertEqual(res["details"]["direction"], "price_up_smart_short")

    def test_last_price_will_not_hand_a_replay_the_live_quote(self):
        from market_data.models import LiveQuote
        from signals.opportunity_scanner import _last_price
        inst = _instrument("ASOF8")
        LiveQuote.objects.create(instrument=inst, last=Decimal("42.0"), source="test")
        self.assertEqual(_last_price(inst, timezone.now()), 42.0)
        self.assertIsNone(
            _last_price(inst, timezone.now() - timedelta(days=30), as_of=True))

    def test_last_price_asks_the_caller_instead_of_the_clock(self):
        """The replay guard used to read `now < wall_clock - 5min`. A live
        sweep pins one `now` for the whole pass, so every instrument reached
        after minute five silently lost its LiveQuote and its match — the scan
        result became a function of how long the scan took."""
        from market_data.models import LiveQuote
        from signals.opportunity_scanner import _last_price
        inst = _instrument("ASOF9")
        LiveQuote.objects.create(instrument=inst, last=Decimal("42.0"), source="test")
        an_hour_into_the_pass = timezone.now() - timedelta(hours=1)
        self.assertEqual(_last_price(inst, an_hour_into_the_pass), 42.0)
        self.assertIsNone(_last_price(inst, an_hour_into_the_pass, as_of=True))

    def test_scan_all_setups_hands_every_pair_the_same_as_of(self):
        """Whatever the pass decides, it decides once."""
        from unittest import mock
        from signals.opportunity_scanner import scan_all_setups
        _setup_from_seed("starter_forex_breakout")
        _instrument("EURUSD", asset_class="forex")
        _instrument("GBPUSD", asset_class="forex")
        with mock.patch("signals.opportunity_scanner.scan_setup") as scan:
            scan.return_value = {"matched": False}
            scan_all_setups()
        self.assertTrue(scan.call_args_list)
        flags = {c.kwargs["as_of"] for c in scan.call_args_list}
        nows = {c.kwargs["now"] for c in scan.call_args_list}
        self.assertEqual(flags, {False})
        self.assertEqual(len(nows), 1)

    def test_a_caller_that_names_its_own_instant_is_treated_as_a_replay(self):
        from signals.opportunity_scanner import scan_all_setups
        from unittest import mock
        _setup_from_seed("starter_forex_breakout")
        _instrument("EURUSD", asset_class="forex")
        with mock.patch("signals.opportunity_scanner.scan_setup") as scan:
            scan.return_value = {"matched": False}
            scan_all_setups(now=timezone.now() - timedelta(days=30))
        self.assertEqual({c.kwargs["as_of"] for c in scan.call_args_list}, {True})

    def test_macro_regime_prefers_the_revision_on_the_live_path(self):
        """FRED revises a print in place under the SAME observation date. The
        ingest writes history with get_or_create, so only last_value moves —
        reading the history row alone would answer with the first print."""
        from signals.opportunity_scanner import _eval_macro_regime
        today = timezone.now().date()
        _seed_macro("GDP", [(today - timedelta(days=120), 27000.0)],
                    last_value=27400.0)
        res = _eval_macro_regime(
            {"series_id": "GDP", "direction": "above", "threshold": 27200.0},
            _instrument("REV1"), timezone.now(),
        )
        self.assertTrue(res["matched"])
        self.assertEqual(res["details"]["value"], 27400.0)
        self.assertTrue(res["details"]["revised"])

    def test_macro_regime_gives_a_replay_the_frozen_print(self):
        """The same revision must not reach a replay: last_value carries no
        vintage, so a past `now` gets the row that was on file."""
        from signals.opportunity_scanner import _eval_macro_regime
        today = timezone.now().date()
        _seed_macro("GDP", [(today - timedelta(days=120), 27000.0)],
                    last_value=27400.0)
        res = _eval_macro_regime(
            {"series_id": "GDP", "direction": "above", "threshold": 27200.0},
            _instrument("REV2"), timezone.now() - timedelta(days=30),
        )
        self.assertFalse(res["matched"])
        self.assertEqual(res["details"]["value"], 27000.0)
        self.assertFalse(res["details"]["revised"])

    def test_the_scan_loop_flag_beats_the_calendar_fallback(self):
        """`as_of` is the caller's word, and it has to outrank any clock-derived
        guess — a live pass that started before UTC midnight is still live."""
        from signals.opportunity_scanner import _eval_macro_regime
        today = timezone.now().date()
        _seed_macro("GDP", [(today - timedelta(days=120), 27000.0)],
                    last_value=27400.0)
        yesterday = timezone.now() - timedelta(days=1)
        live = _eval_macro_regime(
            {"series_id": "GDP", "direction": "above", "threshold": 27200.0},
            _instrument("REV4"), yesterday, as_of=False)
        self.assertEqual(live["details"]["value"], 27400.0)
        replay = _eval_macro_regime(
            {"series_id": "GDP", "direction": "above", "threshold": 27200.0},
            _instrument("REV5"), yesterday, as_of=True)
        self.assertEqual(replay["details"]["value"], 27000.0)

    def test_macro_regime_ignores_last_value_from_a_different_date(self):
        """last_value describes `last_date` and nothing else. Pointing at a
        date the history does not carry makes it a different observation, not
        a revision of the newest row — so it must not be substituted in."""
        from signals.opportunity_scanner import _eval_macro_regime
        today = timezone.now().date()
        indicator = _seed_macro("VIXCLS", [(today - timedelta(days=10), 12.0)])
        indicator.last_value = Decimal("40.0")
        indicator.last_date = today
        indicator.save()
        res = _eval_macro_regime(
            {"series_id": "VIXCLS", "direction": "above", "threshold": 30.0},
            _instrument("REV3"), timezone.now(),
        )
        self.assertFalse(res["matched"])
        self.assertEqual(res["details"]["value"], 12.0)
        self.assertFalse(res["details"]["revised"])


# ── The evaluator-side inertness this pack also hid ────────────────────────

class BreakoutLookbackWindowTests(TestCase):
    def test_breakout_window_covers_the_requested_lookback(self):
        """The fetch used to be sized from ma_period alone, capping it at 55
        bars — so a 60-bar breakout could never see its own range."""
        from signals.opportunity_scanner import _eval_price_pattern
        inst = _instrument("BRK1")
        _seed_prices(inst, [100.0] * 70 + [150.0])
        res = _eval_price_pattern({"pattern": "breakout_high", "lookback": 60},
                                  inst, timezone.now())
        self.assertTrue(res["matched"], msg=res["details"])
        self.assertEqual(res["details"]["prior_high"], 100.0)


# ── The FRED release calendar the GDP leg has to survive ───────────────────

class GDPReleaseCalendarTests(TestCase):
    """The GDP confirmation leg was inert ~69% of the year and nothing caught
    it, because the fixture seeded a spacing FRED can never produce."""

    def _released_prints_in_window(self, day, lookback_days):
        from datetime import date
        cutoff = day - timedelta(days=lookback_days)
        n = 0
        for year in range(day.year - 3, day.year + 1):
            for month in (1, 4, 7, 10):
                q = date(year, month, 1)
                published = _quarter_end(q) + timedelta(days=GDP_RELEASE_LAG_DAYS)
                if cutoff <= q <= day and published <= day:
                    n += 1
        return n

    def test_the_seeded_window_holds_two_released_prints_every_day(self):
        """macro_trend scores 0 below two rows in the window, and the scoreless
        leg stays in the denominator — so a window holding one print does not
        merely add nothing, it raises the bar on the legs that remain."""
        from datetime import date
        from signals.management.commands.seed_strategies import _setup_definitions
        spec = next(s for s in _setup_definitions()
                    if s["name"] == "starter_stock_momentum")
        leg = next(c for c in spec["conditions"]
                   if c["kind"] == "macro_trend"
                   and c["params"]["series_id"] == "GDP")
        lookback = leg["params"]["lookback_days"]

        day = date(2026, 1, 1)
        dead = []
        while day < date(2031, 1, 1):
            if self._released_prints_in_window(day, lookback) < 2:
                dead.append(day)
            day += timedelta(days=1)
        self.assertEqual(
            dead[:5], [],
            msg=(f"lookback_days={lookback} leaves {len(dead)} days on which "
                 f"the GDP leg cannot score, e.g. {dead[:5]}"),
        )

    def test_the_old_240_day_window_would_fail_this(self):
        """Pins the arithmetic itself, so the floor cannot be lowered back by
        someone reading 240 as a safe 'about two quarters'."""
        from datetime import date
        day = date(2026, 1, 1)
        dead = 0
        total = 0
        while day < date(2031, 1, 1):
            total += 1
            if self._released_prints_in_window(day, 240) < 2:
                dead += 1
            day += timedelta(days=1)
        self.assertGreater(dead / total, 0.6)

    def test_the_fixture_dates_are_ones_bea_could_actually_publish(self):
        """An observation dated ten days ago would require BEA to publish a
        quarter before that quarter began."""
        today = timezone.now().date()
        for q in _released_quarter_starts(today, 4):
            with self.subTest(quarter=q):
                self.assertLessEqual(
                    _quarter_end(q) + timedelta(days=GDP_RELEASE_LAG_DAYS), today)
                self.assertGreaterEqual((today - q).days, 121)


# ── Gates: where a setup applies, not how strongly it fires ────────────────

class GateConditionTests(TestCase):
    def _setup(self, conditions, name="gate_test"):
        from signals.models_opportunity import OpportunitySetup
        return OpportunitySetup.objects.create(
            name=name, description="", direction="bullish",
            asset_classes=["stock"], conditions=conditions,
            min_match_score=0.5, suggested_horizon_days=5,
            sizing={"stop_pct": 1.0, "target_rr": 2.0}, is_active=True)

    def test_a_failed_gate_skips_the_pair_without_scoring_it(self):
        from signals.opportunity_scanner import scan_setup
        setup = self._setup([
            {"kind": "quote_currency", "params": {"currency": "USD"},
             "gate": True},
            {"kind": "price_pattern",
             "params": {"pattern": "above_ma", "ma_period": 5}, "weight": 1.0},
        ])
        inst = _instrument("XAUEUR", asset_class="stock")
        _seed_prices(inst, [100.0 + i for i in range(20)])
        res = scan_setup(setup, inst)
        self.assertFalse(res.get("matched"))
        self.assertEqual(res.get("reason"), "gate_failed")

    def test_an_unevaluable_gate_fails_closed(self):
        """A gate that cannot be answered must stay shut: the alternative is a
        setup quietly firing on the symbols it was written to exclude."""
        from signals.opportunity_scanner import scan_setup
        setup = self._setup([
            {"kind": "no_such_evaluator", "params": {}, "gate": True},
            {"kind": "price_pattern",
             "params": {"pattern": "above_ma", "ma_period": 5}, "weight": 1.0},
        ], name="gate_unknown")
        inst = _instrument("GATEX", asset_class="stock")
        _seed_prices(inst, [100.0 + i for i in range(20)])
        res = scan_setup(setup, inst)
        self.assertFalse(res.get("matched"))
        self.assertEqual(res.get("reason"), "gate_failed")

    def test_quote_currency_reads_the_symbol_not_the_currency_column(self):
        """Instrument.currency is seeded to the literal "USD" for every forex
        pair and every commodity, so it carries no quote-convention at all."""
        from signals.opportunity_scanner import _eval_quote_currency
        now = timezone.now()
        for symbol, expected in (("EURUSD", True), ("XAUUSD", True),
                                 ("WHEATUSD", True), ("USDJPY", False),
                                 ("XAUEUR", False), ("EURGBP", False)):
            with self.subTest(symbol=symbol):
                inst = _instrument(symbol, asset_class="forex")
                res = _eval_quote_currency({"currency": "USD"}, inst, now)
                self.assertEqual(res["matched"], expected)

    def test_a_symbol_with_no_currency_suffix_stays_outside_the_universe(self):
        """LUMBER, OATS and RICE carry no quote convention in the symbol. A
        gate must not guess one — unmatched is the fail-closed answer."""
        from signals.opportunity_scanner import _eval_quote_currency
        for symbol in ("LUMBER", "OATS", "RICE", "ORANGEJUICE", "USD"):
            with self.subTest(symbol=symbol):
                res = _eval_quote_currency(
                    {"currency": "USD"},
                    _instrument(symbol, asset_class="commodity"), timezone.now())
                self.assertFalse(res["matched"])


# ── COT is denominated in the CONTRACT's currency, not the symbol's ────────

class CotContractFrameTests(TestCase):
    """`MARKET_NAME_MAP` sends 'JAPANESE YEN' to USDJPY, 'SWISS FRANC' to
    USDCHF, 'CANADIAN DOLLAR' to USDCAD and 'MEXICAN PESO' to USDMXN, and the
    ingest writes `net_speculative = nc_long - nc_short` through verbatim. Net
    long the yen contract is net SHORT USDJPY, so every reader that took the
    column at face value inverted its own test on exactly those four symbols —
    manufacturing divergences where positioning and price agreed and scoring
    the genuine ones at zero.

    The fix is a SIGN, not the `quote_currency` gate its sibling setup uses.
    starter_usd_weakness_macro is gated because its thesis is about the DOLLAR,
    so "USD-quoted" is the universe it means. advanced_smart_money_pivot's
    thesis is about positioning versus price on any COT-covered market: gating
    it to a USD suffix would drop the ten commodities and two genuine cross
    contracts (EURGBP, EURJPY) whose column already reads right-way-up, to fix
    four symbols.
    """

    def test_the_sign_is_flipped_only_where_the_dollar_is_the_base(self):
        from signals.opportunity_scanner import cot_sign
        for symbol in ("USDJPY", "USDCHF", "USDCAD", "USDMXN"):
            with self.subTest(symbol=symbol):
                self.assertEqual(
                    cot_sign(_instrument(symbol, asset_class="forex")), -1)
        for symbol in ("EURUSD", "GBPUSD", "AUDUSD", "NZDUSD",
                       "EURGBP", "EURJPY"):
            with self.subTest(symbol=symbol):
                self.assertEqual(
                    cot_sign(_instrument(symbol, asset_class="forex")), 1)
        for symbol, cls in (("XAUUSD", "commodity"), ("OATS", "commodity"),
                            ("LUMBER", "commodity"), ("BTCUSD", "crypto"),
                            ("DXY", "index")):
            with self.subTest(symbol=symbol):
                self.assertEqual(
                    cot_sign(_instrument(symbol, asset_class=cls)), 1)

    def test_the_asset_class_guard_stops_a_ticker_being_read_as_a_pair(self):
        """Nothing distinguishes a currency prefix from the head of a ticker,
        so the flip is asked for only where the symbol really is a pair."""
        from signals.opportunity_scanner import cot_sign
        self.assertEqual(
            cot_sign(_instrument("USDCRN", asset_class="commodity")), 1)

    def test_the_same_book_reads_long_on_eurusd_and_short_on_usdjpy(self):
        from signals.opportunity_scanner import _eval_cot_report
        today = timezone.now().date()
        now = timezone.now()
        params = {"direction": "long_extreme", "min_ratio": 0.25}
        eurusd = _instrument("EURUSD", asset_class="forex")
        usdjpy = _instrument("USDJPY", asset_class="forex")
        # Identical CFTC rows: specs heavily net long the contract currency.
        for inst in (eurusd, usdjpy):
            _seed_cot(inst, today - timedelta(days=3),
                      nc_long=150000, nc_short=50000)
        self.assertTrue(_eval_cot_report(params, eurusd, now)["matched"])
        self.assertFalse(_eval_cot_report(params, usdjpy, now)["matched"])
        short = _eval_cot_report(
            {"direction": "short_extreme", "min_ratio": 0.25}, usdjpy, now)
        self.assertTrue(short["matched"])
        self.assertTrue(short["details"]["contract_frame_flipped"])
        self.assertLess(short["details"]["net_speculative"], 0)

    def _divergence_world(self, symbol, asset_class, *, rising, contract_long):
        step = 0.5 if rising else -0.5
        inst = _instrument(symbol, asset_class=asset_class)
        _seed_prices(inst, [100.0 + i * step for i in range(40)])
        long_n, short_n = ((150000, 50000) if contract_long else (50000, 150000))
        _seed_cot(inst, timezone.now().date() - timedelta(days=3),
                  nc_long=long_n, nc_short=short_n)
        return inst

    def test_a_divergence_that_never_existed_is_no_longer_manufactured(self):
        """USDJPY rising while the contract is net SHORT the yen. In the
        symbol's frame that is specs net LONG a rising pair — no divergence at
        all. Read raw it looked like the textbook 'price up, smart money short'
        and scored the leg's full weight."""
        from signals.evaluators_advanced import _eval_smart_money_divergence
        inst = self._divergence_world("USDJPY", "forex",
                                      rising=True, contract_long=False)
        res = _eval_smart_money_divergence(
            {"slope_lookback": 20, "slope_threshold": 0.0005,
             "min_ratio": 0.3, "direction": "any"}, inst, timezone.now())
        self.assertFalse(res["matched"], msg=res["details"])

    def test_the_real_divergence_on_a_usd_base_pair_is_now_seen(self):
        """The damage was symmetric: genuine USDJPY divergences scored zero."""
        from signals.evaluators_advanced import _eval_smart_money_divergence
        inst = self._divergence_world("USDJPY", "forex",
                                      rising=False, contract_long=False)
        res = _eval_smart_money_divergence(
            {"slope_lookback": 20, "slope_threshold": 0.0005,
             "min_ratio": 0.3, "direction": "bullish"}, inst, timezone.now())
        self.assertTrue(res["matched"], msg=res["details"])
        self.assertEqual(res["details"]["direction"], "price_down_smart_long")
        self.assertTrue(res["details"]["contract_frame_flipped"])

    def test_a_usd_quoted_pair_is_left_alone(self):
        from signals.evaluators_advanced import _eval_smart_money_divergence
        inst = self._divergence_world("EURUSD", "forex",
                                      rising=False, contract_long=True)
        res = _eval_smart_money_divergence(
            {"slope_lookback": 20, "slope_threshold": 0.0005,
             "min_ratio": 0.3, "direction": "bullish"}, inst, timezone.now())
        self.assertTrue(res["matched"], msg=res["details"])
        self.assertFalse(res["details"]["contract_frame_flipped"])

    def test_the_leg_refuses_the_branch_the_setup_does_not_trade(self):
        """`scan_setup` writes `setup.direction` verbatim into the Signal and
        the flag. A setup pinned to bullish that accepted both branches
        published half its flags upside-down."""
        from signals.evaluators_advanced import _eval_smart_money_divergence
        inst = self._divergence_world("XAUUSD", "commodity",
                                      rising=True, contract_long=False)
        base = {"slope_lookback": 20, "slope_threshold": 0.0005, "min_ratio": 0.3}
        self.assertTrue(_eval_smart_money_divergence(
            {**base, "direction": "bearish"}, inst, timezone.now())["matched"])
        self.assertFalse(_eval_smart_money_divergence(
            {**base, "direction": "bullish"}, inst, timezone.now())["matched"])
        self.assertTrue(_eval_smart_money_divergence(
            {**base, "direction": "any"}, inst, timezone.now())["matched"])

    def test_every_seeded_divergence_leg_names_its_setups_direction(self):
        """The defect class in one sentence: a condition whose meaning points a
        direction, inside a setup that publishes one fixed direction."""
        from signals.management.commands import (
            seed_advanced_strategies, seed_strategies,
        )
        seen = 0
        for mod in (seed_strategies, seed_advanced_strategies):
            for spec in mod._setup_definitions():
                for cond in spec["conditions"]:
                    if cond.get("kind") != "smart_money_divergence":
                        continue
                    seen += 1
                    with self.subTest(setup=spec["name"]):
                        self.assertEqual(
                            (cond.get("params") or {}).get("direction"),
                            spec["direction"],
                        )
        self.assertEqual(seen, 1)


# ── Re-seeding must not overwrite what the operator or the engine decided ──

class SeedPreservesOperatorStateTests(TestCase):
    """The admin panel offers both seeders behind one button, and pressing it
    is the only way repaired conditions reach rows that already exist.
    Re-running used to demote every promoted rule to research — where
    SIZE_FACTORS is 0.0, so it stops trading — with no PromotionEvent written,
    clear admin pauses back to full size, and reset the allocator's budget."""

    def _reseed(self):
        from signals.management.commands import (
            seed_strategies, seed_advanced_strategies,
        )
        seed_strategies.seed_setups()
        seed_advanced_strategies.seed_setups()

    def test_a_promoted_rule_keeps_its_stage_through_a_reseed(self):
        from signals.models_control import RuleControl
        self._reseed()
        entered = timezone.now() - timedelta(days=40)
        RuleControl.objects.filter(rule_name="starter_stock_momentum").update(
            promotion_stage="live_full", stage_entered_at=entered,
            stage_baseline_expectancy=0.35)
        self._reseed()
        rule = RuleControl.objects.get(rule_name="starter_stock_momentum")
        self.assertEqual(rule.promotion_stage, "live_full")
        self.assertEqual(rule.stage_entered_at, entered)
        self.assertEqual(rule.stage_baseline_expectancy, 0.35)

    def test_an_admin_pause_survives_a_reseed(self):
        from signals.models_control import RuleControl
        self._reseed()
        until = timezone.now() + timedelta(days=30)
        RuleControl.objects.filter(rule_name="advanced_smc_long").update(
            status="paused", weight_multiplier=0.0, paused_until=until,
            notes="Paused by RuleAction #7 on 2026-08-01")
        self._reseed()
        rule = RuleControl.objects.get(rule_name="advanced_smc_long")
        self.assertEqual(rule.status, "paused")
        self.assertEqual(rule.weight_multiplier, 0.0)
        self.assertEqual(rule.paused_until, until)
        self.assertIn("RuleAction #7", rule.notes)
        self.assertFalse(rule.is_effectively_active())

    def test_a_reduced_rule_is_not_restored_to_full_size(self):
        from signals.models_control import RuleControl
        self._reseed()
        RuleControl.objects.filter(rule_name="starter_forex_breakout").update(
            status="reduced", weight_multiplier=0.5)
        self._reseed()
        rule = RuleControl.objects.get(rule_name="starter_forex_breakout")
        self.assertEqual(rule.status, "reduced")
        self.assertEqual(rule.weight_multiplier, 0.5)

    def test_the_allocator_budget_survives_a_reseed(self):
        from signals.models_control import RuleControl
        self._reseed()
        RuleControl.objects.filter(
            rule_name="starter_news_event_bullish").update(allocator_weight=0.25)
        self._reseed()
        self.assertEqual(
            RuleControl.objects.get(
                rule_name="starter_news_event_bullish").allocator_weight, 0.25)

    def test_a_reseed_does_refresh_the_definition(self):
        """The whole point of pressing the button: repaired conditions and the
        seed-owned parameter keys have to actually land."""
        from signals.models_control import RuleControl
        from signals.models_opportunity import OpportunitySetup
        from signals.management.commands.seed_strategies import _setup_definitions
        self._reseed()
        OpportunitySetup.objects.filter(name="starter_stock_momentum").update(
            conditions=[], min_match_score=0.01, description="stale")
        RuleControl.objects.filter(rule_name="starter_stock_momentum").update(
            parameters={"min_match_score": 0.01, "tuned_by_evolution": 7})
        self._reseed()
        spec = next(s for s in _setup_definitions()
                    if s["name"] == "starter_stock_momentum")
        setup = OpportunitySetup.objects.get(name="starter_stock_momentum")
        self.assertEqual(setup.conditions, spec["conditions"])
        self.assertEqual(setup.min_match_score, spec["min_match_score"])
        rule = RuleControl.objects.get(rule_name="starter_stock_momentum")
        self.assertEqual(rule.parameters["min_match_score"],
                         spec["min_match_score"])
        # Foreign keys in the shared column are merged around, not clobbered.
        self.assertEqual(rule.parameters["tuned_by_evolution"], 7)

    def test_an_armed_setup_stays_armed_through_a_reseed_of_either_pack(self):
        from signals.models_opportunity import OpportunitySetup
        self._reseed()
        OpportunitySetup.objects.filter(
            name__in=["starter_forex_breakout", "advanced_news_fade"],
        ).update(is_active=True)
        self._reseed()
        for name in ("starter_forex_breakout", "advanced_news_fade"):
            with self.subTest(setup=name):
                self.assertTrue(
                    OpportunitySetup.objects.get(name=name).is_active,
                    msg="a re-run without --activate disarmed an armed setup")

    def test_both_packs_still_create_their_rows_on_a_fresh_install(self):
        from signals.models_control import RuleControl
        from signals.models_opportunity import OpportunitySetup
        self._reseed()
        self.assertEqual(RuleControl.objects.count(), 12)
        self.assertEqual(OpportunitySetup.objects.count(), 12)
        for rule in RuleControl.objects.all():
            with self.subTest(rule=rule.rule_name):
                self.assertEqual(rule.promotion_stage, "research")
                self.assertEqual(rule.status, "active")
        self.assertEqual(
            OpportunitySetup.objects.filter(is_active=True).count(), 0)


# ── The guard reaches the paths that author setups at runtime ──────────────

class GeneratorParamGuardTests(TestCase):
    """PARAM_KEYS had zero production callers: it protected the two static
    seed packs and nothing that writes a setup while the platform is running.
    The LLM generator wrote OpportunitySetup rows from model output with no
    param check of any kind."""

    def _proposal(self, conditions, **extra):
        base = {
            "name_slug": "guard_test", "rationale_md": "x",
            "direction": "bullish", "asset_classes": ["stock"],
            "conditions": conditions, "min_match_score": 0.6,
            "suggested_horizon_days": 5,
        }
        base.update(extra)
        return base

    def test_a_param_key_the_evaluator_never_reads_is_rejected(self):
        from brain.strategy_generator import validate_proposal
        ok, why = validate_proposal(self._proposal(
            [{"kind": "volatility_regime", "params": {"regime": "low"},
              "weight": 1.0}]))
        self.assertFalse(ok)
        self.assertIn("regime", why)

    def test_a_value_outside_the_vocabulary_is_rejected(self):
        """`{"regime": "low"}` did not merely do nothing — the evaluator fell
        to direction="above", scoring the volatility EXPANSION a compression
        setup exists to front-run."""
        from brain.strategy_generator import validate_proposal
        ok, why = validate_proposal(self._proposal(
            [{"kind": "volatility_regime",
              "params": {"period": 20, "direction": "sideways",
                         "threshold_pct": 2.0},
              "weight": 1.0}]))
        self.assertFalse(ok)
        self.assertIn("sideways", why)

    def test_a_dead_sizing_key_is_rejected(self):
        from brain.strategy_generator import validate_proposal
        ok, why = validate_proposal(self._proposal(
            [{"kind": "price_pattern", "params": {"pattern": "above_ma"},
              "weight": 1.0}],
            sizing={"stop_pct": 2.0, "target_pct": 4.0}))
        self.assertFalse(ok)
        self.assertIn("target_pct", why)

    def test_a_well_formed_proposal_still_validates(self):
        from brain.strategy_generator import validate_proposal
        ok, why = validate_proposal(self._proposal(
            [{"kind": "price_pattern",
              "params": {"pattern": "breakout_high", "lookback": 20},
              "weight": 1.5},
             {"kind": "hurst_regime",
              "params": {"regime": "trending", "lookback": 120},
              "weight": 0.7}],
            sizing={"stop_pct": 2.0, "target_rr": 2.5}))
        self.assertTrue(ok, why)

    def test_the_generator_is_told_the_vocabulary_it_must_copy(self):
        """The model used to be handed evaluator NAMES only, so it had nothing
        to copy params from and invented them."""
        from brain.strategy_generator import _build_generation_snapshot
        snap = _build_generation_snapshot()
        entry = next(e for e in snap["available_evaluators"]
                     if e["kind"] == "volatility_regime")
        self.assertEqual(sorted(entry["params"]),
                         ["direction", "period", "threshold_pct"])
        self.assertEqual(entry["choices"]["direction"], ["above", "below"])
        self.assertEqual(snap["accepted_sizing_keys"], ["stop_pct", "target_rr"])

    def test_the_pattern_miner_translation_table_is_held_to_the_same_check(self):
        """The third path that authors setups at runtime. It happens to be
        clean; nothing was asserting it, so nothing kept it clean."""
        from signals.opportunity_scanner import (
            has_kind, invalid_param_values, unknown_param_keys,
        )
        from signals.pattern_miner import FEATURE_TO_CONDITION
        for feature, cond in sorted(FEATURE_TO_CONDITION.items()):
            with self.subTest(feature=feature):
                kind = cond["kind"]
                self.assertTrue(has_kind(kind))
                params = cond.get("params") or {}
                self.assertEqual(unknown_param_keys(kind, params), [])
                self.assertEqual(invalid_param_values(kind, params), [])

    def test_approval_re_checks_before_arming(self):
        """Approval is the step that makes a setup scan, and the reviewer is
        shown a rationale rather than a param audit."""
        from brain.strategy_generator import _persist_proposal, approve_proposal
        from signals.models_opportunity import OpportunitySetup
        proposal = _persist_proposal(
            self._proposal([{"kind": "price_pattern",
                             "params": {"pattern": "above_ma"},
                             "weight": 1.0}], name_slug="approve_guard"),
            model="t", tokens_in=0, tokens_out=0, cost_usd=0.0)
        self.assertIsNotNone(proposal)
        OpportunitySetup.objects.filter(pk=proposal.setup_id).update(
            conditions=[{"kind": "price_pattern",
                         "params": {"pattern": "rsi_oversold"}, "weight": 1.0}])
        proposal.setup.refresh_from_db()
        self.assertFalse(approve_proposal(proposal, reviewed_by="me"))
        proposal.setup.refresh_from_db()
        self.assertFalse(proposal.setup.is_active)
