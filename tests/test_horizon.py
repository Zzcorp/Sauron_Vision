"""HORIZON — the 5-10 year sector synthesis (2026-09-12).

The operator's ask: "syntheses of sectors and their development over
5-10 years, to guard against those risks." A slow, structural view, read
by the share allocator as a WEAK prior (5% per tilt point × confidence,
±10% at most) and held to account by graded calls at 6 and 12 months
like every other agent. These pin: the snapshot degrades block by block;
a garbled answer is a rejected row with its raw text, never a view; the
calls keep their 8760 h horizon while every other caller still clamps at
1440; the allocator folds the factor in as the fifth term and names it;
the page, the button, the command, the component, the beat, the wiring.

Run with:  python manage.py test tests.test_horizon
"""
import json
from datetime import timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

User = get_user_model()
REPO = Path(settings.BASE_DIR)


# ── fixtures ─────────────────────────────────────────────────────────────

def _instrument(symbol, asset_class="etf"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _bar(inst, when, close, timeframe="1d"):
    from market_data.models import PriceData
    return PriceData.objects.create(
        instrument=inst, timeframe=timeframe, timestamp=when,
        open=close, high=close, low=close, close=Decimal(str(close)),
        volume=1, source="test")


def _daily_history(inst, n=400, start=100.0):
    """`n` daily closes ending yesterday, rising 0.1/day — 400 so the 1y
    return window (365 calendar days) is covered and the 3y one is not."""
    now = timezone.now().replace(minute=0, second=0, microsecond=0)
    for i in range(n):
        _bar(inst, now - timedelta(days=n - i), start + 0.1 * i)


def _good_view(**over):
    view = {
        "as_of": "2026-09-12", "horizon_years": 5,
        "summary_md": "XLK return_1y +0.18: the capex cycle is structural.",
        "sectors": [
            {"key": "technology", "thesis_md": "AI capex for a decade.",
             "structural_drivers": ["capex"], "risks": ["valuation"],
             "catalysts": ["earnings"], "tilt": 2, "confidence": 0.8,
             "calls": [{"symbol": "XLK", "direction": "up",
                        "horizon_hours": 8760, "confidence": 0.7,
                        "why": "capex"}]},
            {"key": "energy", "thesis_md": "Transition drag.",
             "structural_drivers": [], "risks": ["policy"], "catalysts": [],
             "tilt": -1, "confidence": 0.5,
             "calls": [{"symbol": "XLE", "direction": "down",
                        "horizon_hours": 4380, "confidence": 0.55,
                        "why": "drag"}]},
        ],
        "asset_classes": [
            {"asset_class": "stock", "tilt": 1, "confidence": 0.8,
             "why": "equities compound"},
            {"asset_class": "crypto", "tilt": -2, "confidence": 0.5,
             "why": "regulation"},
        ],
        "regime_claims": [{"claim": "Rates stay above 3%",
                           "horizon_hours": 8760, "confidence": 0.6}],
    }
    view.update(over)
    return view


def _stub_horizon(parsed, *, raw=None, cost=1.2, fail=None):
    """Patch HorizonAgent.__init__ like tests.test_frontier_imagination
    ._stub_generator: a provider that answers `parsed` (or `raw`), and
    writes the AgentTask ledger row the real provider would."""
    text = raw if raw is not None else json.dumps(parsed)
    usage = {"input_tokens": 20000, "output_tokens": 4000, "cost_usd": cost}

    def _complete(**kw):
        from ai_agents.models import AgentTask
        if fail is not None:
            raise fail
        AgentTask.objects.create(
            agent=kw.get("agent_name", "unattributed"), provider="stub",
            model=kw.get("model", "claude-stub"), prompt_summary="p",
            cost_usd=Decimal(str(cost)), success=True,
            structured_output={"source_ref": kw.get("source_ref", ""),
                               "effort": kw.get("effort")})
        return text, usage

    def patched_init(self, *a, **kw):
        self.agent_name = "horizon"
        self.provider_name = "stub"
        self.model = "claude-stub"
        self.effort = "high"                 # the frontier tier's default
        self.provider = MagicMock()
        self.provider.complete = MagicMock(side_effect=_complete)
    return patch("brain.horizon.HorizonAgent.__init__", patched_init)


def _ok_view_row(tilts=None, *, days_ago=0.0, status="ok", sectors=None):
    from brain.horizon_models import HorizonView
    row = HorizonView.objects.create(
        status=status, horizon_years=5, summary_md="s",
        sectors=sectors if sectors is not None else _good_view()["sectors"],
        asset_class_tilts=tilts if tilts is not None else {
            "stock": {"tilt": 1, "confidence": 0.8, "why": "w"}},
        regime_claims=_good_view()["regime_claims"],
        model_used="claude-stub", cost_usd=Decimal("1.2"))
    if days_ago:
        HorizonView.objects.filter(pk=row.pk).update(
            created_at=timezone.now() - timedelta(days=days_ago))
        row.refresh_from_db()
    return row


class _Universe:
    """XLK and XLE in the catalogue with a year of daily bars."""

    def _seed_universe(self):
        for sym in ("XLK", "XLE"):
            _daily_history(_instrument(sym))


# ── the snapshot ─────────────────────────────────────────────────────────

class SnapshotTests(_Universe, TestCase):

    def test_blocks_degrade_independently_and_the_run_proceeds(self):
        from brain import horizon
        from brain.horizon_models import HorizonView
        self._seed_universe()
        with patch.object(horizon, "_read_macro",
                          side_effect=RuntimeError("fred table gone")):
            snap = horizon._build_horizon_snapshot()
            self.assertIn("unreadable", snap["macro"]["error"])
            self.assertIn("fred table gone", snap["macro"]["error"])
            self.assertIn("as_of", snap["macro"])
            # The other blocks are untouched and stamped.
            for name in ("universe", "evidence", "brain", "previous_view"):
                self.assertNotIn("error", snap[name], name)
                self.assertIn("as_of", snap[name])
                self.assertIn("age_hours", snap[name])
            with _stub_horizon(_good_view()):
                out = horizon.run_horizon_now()
        self.assertTrue(out["ok"])
        self.assertEqual(HorizonView.objects.get().status, "ok")

    def test_the_universe_reports_returns_or_says_no_daily_history(self):
        from brain.horizon import HORIZON_UNIVERSE, _read_universe
        self._seed_universe()
        _instrument("XLF")                       # in the catalogue, no bars
        block = _read_universe()
        rows = {r["key"]: r for r in block["sectors"]}
        self.assertEqual(len(rows), len(HORIZON_UNIVERSE))
        self.assertTrue(rows["technology"]["in_catalogue"])
        self.assertGreater(rows["technology"]["last_close"], 0)
        self.assertIsNotNone(rows["technology"]["return_1y"])
        self.assertIsNone(rows["technology"]["return_3y"])   # not covered
        self.assertEqual(rows["financials"]["history"], "no daily history")
        self.assertFalse(rows["gold"]["in_catalogue"])
        self.assertEqual(rows["gold"]["history"], "not in the catalogue")
        self.assertIsNotNone(block["age_hours"])

    def test_gold_prefers_the_spelling_the_catalogue_holds(self):
        from brain.horizon import gold_symbol, universe_symbols
        self.assertEqual(gold_symbol(), "GLD")           # neither: the constant
        _instrument("GLDM")
        self.assertEqual(gold_symbol(), "GLDM")
        self.assertEqual(universe_symbols()["gold"], "GLDM")
        _instrument("GLD")
        self.assertEqual(gold_symbol(), "GLD")           # both: GLD

    def test_macro_lists_present_series_and_says_absent_otherwise(self):
        from core.constants import FRED_SERIES
        from brain.horizon import _read_macro
        from market_data.models import MacroIndicator, MacroObservation
        ind = MacroIndicator.objects.create(series_id="DGS10", name="10y",
                                            category="rates", frequency="d")
        MacroObservation.objects.create(indicator=ind,
                                        date=timezone.now().date(),
                                        value=Decimal("4.25"))
        block = _read_macro()
        self.assertEqual(set(block["series"]), set(FRED_SERIES))
        self.assertEqual(block["series"]["DGS10"]["value"], 4.25)
        self.assertEqual(block["series"]["FEDFUNDS"]["value"], "absent")

    def test_the_previous_view_and_its_record_are_in_the_snapshot(self):
        from ai_agents.models import AgentPrediction
        from brain.horizon import _read_previous
        self.assertEqual(_read_previous()["view"], "absent (first run)")
        row = _ok_view_row()
        AgentPrediction.objects.create(
            agent="horizon", prediction_type="direction",
            predicted_value="up", instrument_symbol="XLK", confidence=0.7,
            was_correct=True, actual_value="up", score=0.1,
            evaluated_at=timezone.now(),
            expected_resolution_at=timezone.now(), horizon_hours=8760.0)
        block = _read_previous()
        self.assertEqual(block["view"]["id"], row.pk)
        self.assertEqual(block["view"]["sector_tilts"]["technology"]["tilt"], 2)
        self.assertEqual(block["record"]["calls_graded"], 1)
        self.assertEqual(block["record"]["calls_correct"], 1)


# ── parse_response ───────────────────────────────────────────────────────

class ParseResponseTests(SimpleTestCase):

    def _parse(self, data):
        from brain.horizon import HorizonAgent
        agent = HorizonAgent.__new__(HorizonAgent)
        return agent.parse_response(json.dumps(data) if not isinstance(data, str)
                                    else data)

    def test_a_good_answer_is_normalised(self):
        out = self._parse(_good_view())
        self.assertEqual(out["horizon_years"], 5)
        self.assertEqual([s["key"] for s in out["sectors"]],
                         ["technology", "energy"])
        self.assertEqual(out["sectors"][0]["calls"][0]["horizon_hours"], 8760)
        self.assertEqual(out["asset_classes"][1]["tilt"], -2)
        # Code fences are tolerated, like every other agent's parser.
        fenced = "```json\n" + json.dumps(_good_view()) + "\n```"
        self.assertEqual(self._parse(fenced)["horizon_years"], 5)

    def test_non_json_and_non_dict_are_rejected(self):
        with self.assertRaises(ValueError):
            self._parse("not json at all")
        with self.assertRaises(ValueError):
            self._parse([1, 2])

    def test_an_unknown_sector_key_is_rejected(self):
        bad = _good_view()
        bad["sectors"][0]["key"] = "semiconductors"
        with self.assertRaisesRegex(ValueError, "unknown sector key"):
            self._parse(bad)

    def test_a_tilt_outside_minus2_plus2_is_rejected(self):
        bad = _good_view()
        bad["sectors"][0]["tilt"] = 3
        with self.assertRaisesRegex(ValueError, "tilt 3 outside"):
            self._parse(bad)
        bad = _good_view()
        bad["asset_classes"][0]["tilt"] = -2.5
        with self.assertRaisesRegex(ValueError, "not an integer"):
            self._parse(bad)

    def test_a_confidence_outside_0_1_is_rejected(self):
        bad = _good_view()
        bad["sectors"][1]["confidence"] = 1.4
        with self.assertRaisesRegex(ValueError, "confidence"):
            self._parse(bad)
        bad = _good_view()
        bad["sectors"][0]["calls"][0]["confidence"] = -0.1
        with self.assertRaisesRegex(ValueError, "confidence"):
            self._parse(bad)

    def test_a_horizon_that_is_not_6_or_12_months_is_rejected(self):
        bad = _good_view()
        bad["sectors"][0]["calls"][0]["horizon_hours"] = 720
        with self.assertRaisesRegex(ValueError, "horizon_hours"):
            self._parse(bad)
        bad = _good_view()
        bad["regime_claims"][0]["horizon_hours"] = 24
        with self.assertRaisesRegex(ValueError, "horizon_hours"):
            self._parse(bad)

    def test_an_unknown_asset_class_or_horizon_years_is_rejected(self):
        bad = _good_view()
        bad["asset_classes"][0]["asset_class"] = "bond"
        with self.assertRaisesRegex(ValueError, "unknown asset_class"):
            self._parse(bad)
        bad = _good_view(horizon_years=7)
        with self.assertRaisesRegex(ValueError, "horizon_years"):
            self._parse(bad)

    def test_an_infinite_number_is_a_value_error_not_an_overflow(self):
        """json.loads accepts `Infinity` and `1e999`; int(inf) raises
        OverflowError, which the run's rejection path did not catch."""
        good = json.dumps(_good_view())
        self.assertIn('"tilt": 2', good)
        with self.assertRaisesRegex(ValueError, "tilt"):
            self._parse(good.replace('"tilt": 2', '"tilt": Infinity', 1))
        with self.assertRaisesRegex(ValueError, "tilt"):
            self._parse(good.replace('"tilt": 1', '"tilt": -1e999', 1))
        with self.assertRaisesRegex(ValueError, "horizon_years"):
            self._parse(good.replace('"horizon_years": 5',
                                     '"horizon_years": 1e999', 1))

    def test_the_prompt_carries_the_doctrine_and_the_schema(self):
        from brain.horizon import HorizonAgent
        prompt = HorizonAgent.get_system_prompt(HorizonAgent.__new__(HorizonAgent))
        self.assertIn("Respond ONLY with valid JSON", prompt)
        self.assertIn('"regime_claims"', prompt)
        self.assertIn("4380", prompt)
        self.assertIn("previous_view", prompt)
        self.assertEqual(HorizonAgent.agent_name, "horizon")
        self.assertLessEqual(len(HorizonAgent.agent_name), 30)
        self.assertEqual(HorizonAgent.default_tier, "frontier")


# ── the run ──────────────────────────────────────────────────────────────

class RunTests(_Universe, TestCase):

    def test_a_good_run_persists_an_ok_view_and_its_calls(self):
        from ai_agents.models import AgentPrediction, AgentTask
        from brain.horizon import run_horizon_now
        from brain.horizon_models import HorizonView
        self._seed_universe()
        with _stub_horizon(_good_view()):
            out = run_horizon_now()
        self.assertTrue(out["ok"])
        view = HorizonView.objects.get()
        self.assertEqual(view.status, "ok")
        self.assertEqual(view.horizon_years, 5)
        self.assertEqual(view.asset_class_tilts["stock"],
                         {"tilt": 1, "confidence": 0.8, "why": "equities compound"})
        self.assertEqual(view.model_used, "claude-stub")
        self.assertEqual(float(view.cost_usd), 1.2)
        self.assertEqual(view.tokens_in, 20000)
        self.assertEqual(view.calls_registered, 2)
        self.assertEqual(view.calls_dropped, 0)
        self.assertEqual(view.raw, "")
        # The 12-month call keeps its horizon — not clamped to 1440 h.
        rows = {p.instrument_symbol: p for p in
                AgentPrediction.objects.filter(agent="horizon")}
        self.assertEqual(rows["XLK"].horizon_hours, 8760.0)
        self.assertEqual(rows["XLE"].horizon_hours, 4380.0)
        self.assertEqual(rows["XLK"].predicted_value, "up")
        self.assertAlmostEqual(
            (rows["XLK"].expected_resolution_at - view.created_at
             ).total_seconds() / 3600, 8760.0, places=1)
        # The ledger row rides through the provider with the view's ref.
        task = AgentTask.objects.get(agent="horizon")
        self.assertEqual(task.structured_output["source_ref"],
                         f"HorizonView:{view.pk}")

    def test_a_duplicate_symbol_call_is_dropped_and_counted(self):
        from ai_agents.models import AgentPrediction
        from brain.horizon import run_horizon_now
        from brain.horizon_models import HorizonView
        self._seed_universe()
        data = _good_view()
        data["sectors"][1]["calls"].append(
            {"symbol": "XLK", "direction": "down", "horizon_hours": 4380,
             "confidence": 0.5, "why": "second opinion"})
        with _stub_horizon(data):
            out = run_horizon_now()
        self.assertEqual(out["calls_registered"], 2)
        self.assertEqual(out["calls_dropped"], 1)
        self.assertEqual(out["calls_dropped_duplicate"], 1)
        view = HorizonView.objects.get()
        self.assertEqual((view.calls_registered, view.calls_dropped), (2, 1))
        self.assertEqual(AgentPrediction.objects.filter(
            agent="horizon", instrument_symbol="XLK").count(), 1)

    def test_a_friday_close_is_the_reference_when_no_fresh_mark_exists(self):
        """A monthly run on the 1st can land on a Monday with Friday's bar
        as the newest — 60+ hours old, outside mark_for_symbol's window."""
        from ai_agents.models import AgentPrediction
        from brain.horizon import run_horizon_now
        inst = _instrument("XLK")
        now = timezone.now()
        for i in range(260):
            _bar(inst, now - timedelta(days=3 + i), 100.0 - 0.1 * i)
        data = _good_view()
        data["sectors"] = [data["sectors"][0]]
        with _stub_horizon(data):
            out = run_horizon_now()
        self.assertEqual(out["calls_registered"], 1)
        pred = AgentPrediction.objects.get(agent="horizon")
        self.assertEqual(float(pred.reference_price), 100.0)

    def test_rejected_output_keeps_status_rejected_and_the_raw_text(self):
        from ai_agents.models import AgentPrediction
        from brain.horizon import run_horizon_now
        from brain.horizon_models import HorizonView
        self._seed_universe()
        bad = _good_view()
        bad["sectors"][0]["tilt"] = 5
        with _stub_horizon(bad):
            out = run_horizon_now()
        self.assertFalse(out["ok"])
        self.assertEqual(out["outcome"], "rejected")
        view = HorizonView.objects.get()
        self.assertEqual(view.status, "rejected")
        self.assertIn("tilt 5 outside", view.error)
        self.assertIn('"tilt": 5', view.raw)
        self.assertEqual(float(view.cost_usd), 1.2)   # the paid call is booked
        self.assertEqual(view.sectors, [])
        self.assertEqual(AgentPrediction.objects.count(), 0)
        # Non-JSON is the same outcome, and the raw is capped.
        with _stub_horizon(None, raw="x" * 30000):
            run_horizon_now()
        self.assertEqual(len(HorizonView.objects.order_by("-pk").first().raw),
                         20000)

    def test_a_parser_crash_is_a_rejected_row_never_a_stuck_running_row(self):
        """An answer whose tilt is `Infinity` raised OverflowError out of
        run_horizon_now — 'never raises' broken, the row left `running`
        forever, the paid text unsaved."""
        from brain.horizon import run_horizon_now
        from brain.horizon_models import HorizonView
        self._seed_universe()
        raw = json.dumps(_good_view()).replace('"tilt": 2', '"tilt": Infinity', 1)
        with _stub_horizon(None, raw=raw):
            out = run_horizon_now()                  # must not raise
        self.assertEqual(out["outcome"], "rejected")
        view = HorizonView.objects.get()
        self.assertEqual(view.status, "rejected")
        self.assertIn("Infinity", view.raw)
        self.assertIn("tilt", view.error)
        self.assertEqual(float(view.cost_usd), 1.2)
        # Any parser exception lands the same way, not only ValueError.
        with _stub_horizon(_good_view()), patch(
                "brain.horizon.HorizonAgent.parse_response",
                side_effect=RuntimeError("parser bug")):
            out = run_horizon_now()
        self.assertEqual(out["outcome"], "rejected")
        crashed = HorizonView.objects.order_by("-pk").first()
        self.assertEqual(crashed.status, "rejected")
        self.assertIn("parser bug", crashed.error)
        self.assertIn('"technology"', crashed.raw)
        self.assertFalse(HorizonView.objects.filter(status="running").exists())

    def test_a_stale_daily_close_is_not_a_reference(self):
        """The Friday-close fallback stops at REFERENCE_MAX_AGE_DAYS: a
        feed that died a month ago has no price to measure a call from,
        so the call is dropped and counted, not graded from a ghost."""
        from ai_agents.models import AgentPrediction
        from brain.horizon import REFERENCE_MAX_AGE_DAYS, run_horizon_now
        self.assertEqual(REFERENCE_MAX_AGE_DAYS, 7)
        inst = _instrument("XLK")
        now = timezone.now()
        for i in range(260):
            _bar(inst, now - timedelta(days=30 + i), 100.0 - 0.1 * i)
        data = _good_view()
        data["sectors"] = [data["sectors"][0]]
        with _stub_horizon(data):
            out = run_horizon_now()
        self.assertTrue(out["ok"])                  # the view stands
        self.assertEqual(out["calls_registered"], 0)
        self.assertEqual(out["calls_dropped_unregistered"], 1)
        self.assertEqual(out["calls_dropped"], 1)
        self.assertEqual(AgentPrediction.objects.count(), 0)

    def test_the_call_carries_the_tier_effort_like_base_agent_run(self):
        from ai_agents.models import AgentTask
        from brain.horizon import run_horizon_now
        self._seed_universe()
        with _stub_horizon(_good_view()):
            run_horizon_now()
        self.assertEqual(AgentTask.objects.get(agent="horizon")
                         .structured_output["effort"], "high")

    def test_a_provider_error_is_an_error_row_written_before_the_call(self):
        from brain.horizon import run_horizon_now
        from brain.horizon_models import HorizonView
        with _stub_horizon(None, fail=RuntimeError("api down")):
            out = run_horizon_now()
        self.assertFalse(out["ok"])
        view = HorizonView.objects.get()
        self.assertEqual(view.status, "error")
        self.assertIn("api down", view.error)
        self.assertIsNotNone(view.snapshot_as_of)

    def test_latest_view_respects_age_and_status(self):
        from brain.horizon_models import latest_view
        self.assertIsNone(latest_view())
        _ok_view_row(status="rejected")
        _ok_view_row(status="error")
        _ok_view_row(status="running")
        self.assertIsNone(latest_view())
        old = _ok_view_row(days_ago=50)
        self.assertIsNone(latest_view(max_age_days=45))
        self.assertEqual(latest_view(max_age_days=60).pk, old.pk)
        fresh = _ok_view_row(days_ago=3)
        self.assertEqual(latest_view().pk, fresh.pk)


# ── the allocator prior ──────────────────────────────────────────────────

class HorizonFactorTests(TestCase):

    def test_factor_maths_and_neutral_reasons(self):
        from bot_program.share_allocator import (HORIZON_MAX_AGE_DAYS,
                                                 HORIZON_TILT_STEP,
                                                 horizon_for)
        from brain.horizon_models import DEFAULT_MAX_AGE_DAYS
        self.assertEqual(HORIZON_TILT_STEP, 0.05)
        self.assertEqual(HORIZON_MAX_AGE_DAYS, 45)
        self.assertEqual(DEFAULT_MAX_AGE_DAYS, HORIZON_MAX_AGE_DAYS)
        stock = SimpleNamespace(asset_class="stock")
        # No view: neutral, with the reason.
        hz = horizon_for(stock, None)
        self.assertEqual(hz["factor"], 1.0)
        self.assertIn("no horizon view", hz["reason"])
        view = _ok_view_row({
            "stock": {"tilt": 1, "confidence": 0.8, "why": "w"},
            "crypto": {"tilt": -2, "confidence": 1.0, "why": "w"},
            "forex": {"tilt": 2, "confidence": 1.0, "why": "w"},
            "cfd": {"tilt": 9, "confidence": 3.0, "why": "hand-edited"}})
        hz = horizon_for(stock, view)
        self.assertAlmostEqual(hz["factor"], 1.04)
        self.assertEqual((hz["tilt"], hz["confidence"]), (1, 0.8))
        self.assertEqual(hz["label"], "stock tilt +1, conf 0.8")
        self.assertAlmostEqual(
            horizon_for(SimpleNamespace(asset_class="crypto"), view)["factor"],
            0.90)
        self.assertAlmostEqual(
            horizon_for(SimpleNamespace(asset_class="forex"), view)["factor"],
            1.10)
        # Clamped again on the way out: ±10% at most, whatever the row says.
        self.assertAlmostEqual(
            horizon_for(SimpleNamespace(asset_class="cfd"), view)["factor"],
            1.10)
        # A class the view did not tilt is neutral, with the reason.
        hz = horizon_for(SimpleNamespace(asset_class="commodity"), view)
        self.assertEqual(hz["factor"], 1.0)
        self.assertIn("no commodity tilt", hz["reason"])

    def test_a_stale_view_is_neutral_with_the_reason(self):
        from bot_program.share_allocator import horizon_for
        view = _ok_view_row(days_ago=50)
        hz = horizon_for(SimpleNamespace(asset_class="stock"), view)
        self.assertEqual(hz["factor"], 1.0)
        self.assertIn("50d old", hz["reason"])
        self.assertIn("neutral", hz["reason"])


class AllocatorFoldsTheFactorTests(TestCase):
    """The raw product carries the fifth factor and the why names it."""

    def setUp(self):
        from bot_program.models import AssetBotConfig, IBKRAccount
        self.user = User.objects.create_user("hz_u", password="x")
        acct = IBKRAccount.objects.create(user=self.user, port=4003,
                                          is_primary_for_stocks=True)
        acct.set_credentials("U1234567")
        acct.username_enc, acct.password_enc = "x", "y"
        acct.last_equity = Decimal("2000.00")
        acct.last_equity_currency = "EUR"
        acct.last_equity_at = timezone.now()
        acct.save()
        self.a = AssetBotConfig.objects.create(
            user=self.user, asset_class="stock", name="alpha_stock",
            mode="live", enabled=True, symbols=["AAPL"],
            capital=Decimal("1000"),
            extras={"capital_tracks_broker": True, "account_share_pct": 50})
        self.b = AssetBotConfig.objects.create(
            user=self.user, asset_class="crypto", name="beta_crypto",
            mode="live", enabled=True, symbols=["BTCUSD"],
            capital=Decimal("1000"),
            extras={"capital_tracks_broker": True, "account_share_pct": 50})

    def test_the_raw_product_includes_the_factor_and_the_why_names_it(self):
        from bot_program.share_allocator import propose_share_plan_with_reason
        _ok_view_row({"stock": {"tilt": 2, "confidence": 1.0, "why": "w"},
                      "crypto": {"tilt": -2, "confidence": 1.0, "why": "w"}})
        plan, reason = propose_share_plan_with_reason(self.user)
        self.assertIsNotNone(plan, reason)
        ia, ib = plan.inputs[str(self.a.pk)], plan.inputs[str(self.b.pk)]
        self.assertAlmostEqual(ia["horizon"]["factor"], 1.10)
        self.assertAlmostEqual(ib["horizon"]["factor"], 0.90)
        # Every other factor is neutral here, so raw is current × horizon,
        # normalised: 55 : 45 of the deployable 100.
        self.assertAlmostEqual(ia["raw"], 55.0, places=2)
        self.assertAlmostEqual(ib["raw"], 45.0, places=2)
        self.assertIn("× horizon 1.10 (stock tilt +2, conf 1.0)", ia["why"])
        self.assertIn("× horizon 0.90 (crypto tilt -2, conf 1.0)", ib["why"])
        self.assertIn("× news", ia["why"])
        self.assertLess(ia["why"].index("× news"), ia["why"].index("× horizon"))

    def test_no_view_reads_neutral_and_says_so(self):
        from bot_program.share_allocator import propose_share_plan_with_reason
        plan, reason = propose_share_plan_with_reason(self.user)
        self.assertIsNotNone(plan, reason)
        ia = plan.inputs[str(self.a.pk)]
        self.assertEqual(ia["horizon"]["factor"], 1.0)
        self.assertIn("× horizon 1.00 (no view)", ia["why"])
        self.assertAlmostEqual(ia["raw"], 50.0, places=2)

    def test_a_dead_horizon_reader_costs_a_factor_not_the_plan(self):
        from bot_program import share_allocator
        with patch("brain.horizon_models.latest_view",
                   side_effect=RuntimeError("table missing")):
            plan, reason = share_allocator.propose_share_plan_with_reason(
                self.user)
        self.assertIsNotNone(plan, reason)
        ia = plan.inputs[str(self.a.pk)]
        self.assertEqual(ia["horizon"]["factor"], 1.0)
        self.assertIn("table missing", ia["horizon"]["reason"])

    def test_the_shares_page_and_command_name_the_prior(self):
        from bot_program.share_allocator import propose_share_plan_with_reason
        view = _ok_view_row({"stock": {"tilt": 1, "confidence": 0.8, "why": "w"}})
        propose_share_plan_with_reason(self.user)
        self.client.force_login(self.user)
        html = self.client.get("/shares/").content.decode()
        self.assertIn("× news × horizon", html)
        self.assertIn(f"view #{view.pk}", html)
        self.assertIn("stock +1 → ×1.04", html)
        self.assertIn("× horizon 1.04 (stock tilt +1, conf 0.8)", html)
        out = StringIO()
        call_command("shares", "list", stdout=out)
        text = out.getvalue()
        self.assertIn(f"horizon prior: view #{view.pk}", text)
        self.assertIn("stock +1 -> x1.04", text)
        self.assertIn("× horizon 1.04", text)


class ExistingCallersStillClampTests(TestCase):

    def test_clamp_horizon_keeps_the_sixty_day_ceiling_by_default(self):
        from ai_agents.calibration import (DIRECTION_MAX_HORIZON_H,
                                           clamp_horizon)
        self.assertEqual(DIRECTION_MAX_HORIZON_H, 1440.0)
        self.assertEqual(clamp_horizon(8760), 1440.0)
        self.assertEqual(clamp_horizon(8760, max_horizon_hours=8760), 8760.0)
        self.assertEqual(clamp_horizon(20000, max_horizon_hours=8760), 8760.0)
        self.assertEqual(clamp_horizon("x", 12.0, max_horizon_hours=8760), 12.0)

    def test_register_calls_and_the_advisor_still_clamp_at_1440(self):
        from ai_agents.calibration import (log_direction_prediction,
                                           register_calls)
        from ai_agents.models import AgentPrediction
        inst = _instrument("AAPL", "stock")
        _bar(inst, timezone.now() - timedelta(hours=1), 100.0, "1h")
        _instrument("MSFT", "stock")
        _bar(_instrument("MSFT", "stock"), timezone.now() - timedelta(hours=1),
             50.0, "1h")
        self.assertEqual(register_calls("daily_briefing", [
            {"symbol": "AAPL", "direction": "up", "horizon_hours": 8760,
             "confidence": 0.6}]), 1)
        self.assertEqual(AgentPrediction.objects.get(
            instrument_symbol="AAPL").horizon_hours, 1440.0)
        pred = log_direction_prediction("strategy_advisor", "MSFT", "down",
                                        horizon_hours=8760)
        self.assertEqual(pred.horizon_hours, 1440.0)


# ── the page and the button ──────────────────────────────────────────────

class HorizonPageTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("hz_view", password="x")
        self.admin = User.objects.create_user("hz_admin", password="x",
                                              is_staff=True, is_superuser=True)

    def test_the_page_renders_without_a_view(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse("horizon_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "NO HORIZON VIEW YET")
        self.assertContains(resp, "Horizon")
        self.assertNotContains(resp, "Run now")
        self.assertContains(resp, "needs 10 graded calls")

    def test_the_page_renders_the_view_its_calls_and_the_factor(self):
        from ai_agents.models import AgentPrediction
        view = _ok_view_row({"stock": {"tilt": 1, "confidence": 0.8,
                                       "why": "compound"}})
        AgentPrediction.objects.create(
            agent="horizon", prediction_type="direction", predicted_value="up",
            instrument_symbol="XLK", confidence=0.7,
            expected_resolution_at=timezone.now() + timedelta(hours=8760),
            reference_price=Decimal("100"), horizon_hours=8760.0)
        AgentPrediction.objects.create(
            agent="horizon", prediction_type="direction", predicted_value="down",
            instrument_symbol="XLE", confidence=0.55, was_correct=False,
            actual_value="up", score=-0.05, evaluated_at=timezone.now(),
            expected_resolution_at=timezone.now(), horizon_hours=4380.0)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("horizon_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f"#{view.pk}")
        self.assertContains(resp, "Technology")
        self.assertContains(resp, "AI capex for a decade.")
        self.assertContains(resp, "XLK UP · 12m")
        self.assertContains(resp, "pending until")
        self.assertContains(resp, "XLE DOWN · 6m")
        self.assertContains(resp, "&#10007; up")
        self.assertContains(resp, "×1.040")
        self.assertContains(resp, "compound")
        self.assertContains(resp, "claude-stub")

    def test_the_run_now_button_is_for_superusers_only(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("horizon_dashboard"))
        self.assertContains(resp, "~1.5 USD on the frontier model")
        self.assertContains(resp, reverse("hq_run_horizon"))
        self.assertContains(resp, 'data-run-job="Horizon synthesis"')
        staff = User.objects.create_user("hz_staff", password="x", is_staff=True)
        self.client.force_login(staff)
        resp = self.client.get(reverse("horizon_dashboard"))
        self.assertNotContains(resp, reverse("hq_run_horizon"))

    def test_a_non_superuser_post_is_403(self):
        from brain.horizon_models import HorizonView
        staff = User.objects.create_user("hz_staff2", password="x",
                                         is_staff=True)
        self.client.force_login(staff)
        resp = self.client.post(reverse("hq_run_horizon"))
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(HorizonView.objects.exists())

    def test_a_superuser_post_runs_and_flashes_the_cost(self):
        from brain.horizon_models import HorizonView
        for sym in ("XLK", "XLE"):
            _daily_history(_instrument(sym))
        self.client.force_login(self.admin)
        with _stub_horizon(_good_view(), cost=1.37):
            resp = self.client.post(reverse("hq_run_horizon"), follow=True)
        self.assertEqual(resp.redirect_chain[-1][0], "/horizon/")
        flashes = " ".join(str(m) for m in resp.context["messages"])
        view = HorizonView.objects.get()
        self.assertIn(f"view #{view.pk} written", flashes)
        self.assertIn("1.37 USD", flashes)
        self.assertIn("2 call(s) registered", flashes)

    def test_the_stale_view_is_marked_on_the_page(self):
        _ok_view_row(days_ago=60)
        self.client.force_login(self.user)
        resp = self.client.get(reverse("horizon_dashboard"))
        self.assertContains(resp, "STALE")
        self.assertContains(resp, "the allocator reads it as neutral")


# ── the command ──────────────────────────────────────────────────────────

class CommandTests(TestCase):

    def _run(self, *args):
        out = StringIO()
        call_command("horizon", *args, stdout=out)
        return out.getvalue()

    def test_list_and_show_and_grade(self):
        from ai_agents.models import AgentPrediction
        self.assertIn("none yet", self._run("list"))
        self.assertIn("no OK view yet", self._run("show"))
        view = _ok_view_row({"stock": {"tilt": 1, "confidence": 0.8,
                                       "why": "compound"}})
        rejected = _ok_view_row(status="rejected", sectors=[])
        rejected.raw, rejected.error = '{"tilt": 5}', "tilt 5 outside -2..2"
        rejected.save()
        AgentPrediction.objects.create(
            agent="horizon", prediction_type="direction", predicted_value="up",
            instrument_symbol="XLK", confidence=0.7, was_correct=True,
            actual_value="up", score=0.12, evaluated_at=timezone.now(),
            expected_resolution_at=timezone.now(), horizon_hours=8760.0)
        text = self._run("list")
        self.assertIn(f"#{view.pk}", text)
        self.assertIn("OK", text)
        self.assertIn("REJECTED", text)
        self.assertIn("claude-stub", text)
        self.assertIn("1.200 USD", text)
        self.assertIn("0 registered / 0 dropped", text)
        text = self._run("show")
        self.assertIn("Technology", text)
        self.assertIn("tilt +2", text)
        self.assertIn("call XLK UP 12m", text)
        self.assertIn("RIGHT (up, move +0.1200)", text)
        self.assertIn("call XLE DOWN 6m", text)
        self.assertIn("not registered", text)
        self.assertIn("stock      tilt +1  conf 0.80  -> factor x1.040", text)
        self.assertIn("Rates stay above 3%", text)
        text = self._run("show", str(rejected.pk))
        self.assertIn("REJECTED", text)
        self.assertIn('{"tilt": 5}', text)
        text = self._run("grade")
        self.assertIn("1 call(s), 1 graded (1 right)", text)
        self.assertIn("brier — (needs 10 graded calls)", text)
        self.assertIn("trust — (unmeasured)", text)

    def test_run_without_yes_prints_the_cost_and_does_nothing(self):
        from brain.horizon_models import HorizonView
        text = self._run("run")
        self.assertIn("~1.5 USD", text)
        self.assertIn("nothing run", text)
        self.assertFalse(HorizonView.objects.exists())

    def test_run_with_yes_calls_the_same_function_the_view_calls(self):
        from brain.horizon_models import HorizonView
        for sym in ("XLK", "XLE"):
            _daily_history(_instrument(sym))
        with _stub_horizon(_good_view()):
            text = self._run("run", "--yes")
        view = HorizonView.objects.get()
        self.assertEqual(view.status, "ok")
        self.assertIn(f"view #{view.pk} OK", text)
        self.assertIn("2 call(s) registered", text)
        self.assertIn("Technology", text)            # show follows the run

    def test_the_command_is_in_the_ops_registry(self):
        from core import ops_commands
        entry = ops_commands.get("horizon")
        self.assertIsNotNone(entry)
        self.assertEqual(entry["category"], "decide")
        self.assertFalse(ops_commands.is_runnable(entry))
        self.assertEqual(entry["mirrors"], "/horizon/")


# ── the wiring ───────────────────────────────────────────────────────────

class WiringTests(SimpleTestCase):

    def test_the_component_is_registered_off_by_default_and_fits(self):
        from core.platform_control import DEFAULT_COMPONENTS
        entry = next(c for c in DEFAULT_COMPONENTS if c["key"] == "agent_horizon")
        self.assertEqual(entry["category"], "agent")
        self.assertLessEqual(len(entry["description"]), 300)
        self.assertLessEqual(len(entry["name"]), 100)
        self.assertIn("1.5 USD", entry["description"])
        self.assertIn("10%", entry["description"])

    def test_the_beat_runs_monthly_and_the_task_is_registered(self):
        from celery.schedules import crontab
        from config.celery import app
        entry = app.conf.beat_schedule["sauron-horizon-monthly"]
        self.assertEqual(entry["task"], "brain.tasks.run_horizon")
        self.assertEqual(entry["schedule"], crontab(day_of_month=1, hour=4,
                                                    minute=45))
        app.loader.import_default_modules()
        app.finalize()
        self.assertIn("brain.tasks.run_horizon", set(app.tasks))

    def test_the_wiring_feeds_resolve_and_declare_the_cadence(self):
        from dashboard.views_topology import WIRING, _expected_cadence, _fmt_cadence
        node = WIRING["agent_horizon"]
        self.assertEqual(node["task"], "brain.tasks.run_horizon")
        self.assertEqual(node["layer"], "learn")
        self.assertEqual(node["writes"], ["HorizonView", "AgentPrediction"])
        for key in node["feeds"]:
            self.assertIn(key, WIRING, key)
        self.assertEqual(set(node["feeds"]),
                         {"pipeline_share_allocator", "pipeline_calibration"})
        self.assertEqual(node["pages"], ["/horizon/"])
        self.assertEqual(_expected_cadence("agent_horizon"), 2678400.0)
        self.assertEqual(_fmt_cadence(2678400), "monthly")
        self.assertEqual(_fmt_cadence(604800), "weekly")

    def test_the_task_is_budgeted_on_the_frontier_tier_inside_the_gate(self):
        src = (REPO / "brain" / "tasks.py").read_text(encoding="utf-8")
        self.assertIn('@shared_task(name="brain.tasks.run_horizon")\n'
                      '@guarded_task("agent_horizon")\n'
                      '@spend_guard(tier="frontier", estimated_usd=1.5)\n'
                      'def run_horizon', src)

    def test_the_agent_is_pickable_on_the_models_page_and_in_the_ledger_table(self):
        from dashboard.views_ai_models import AGENT_GROUPS
        from tests.test_llm_ledger_truth import BYPASS_SITES
        rows = {name: tier for _, rs in AGENT_GROUPS for name, _, tier in rs}
        self.assertEqual(rows.get("horizon"), "frontier")
        self.assertEqual(BYPASS_SITES.get("brain/horizon.py"), "agent.agent_name")

    def test_the_nav_and_the_runbook_know_the_page(self):
        base = (REPO / "templates" / "base.html").read_text(encoding="utf-8")
        self.assertIn("{% url 'horizon_dashboard' %}", base)
        self.assertLess(base.index("shares_dashboard"), base.index("horizon_dashboard"))
        runbook = (REPO / "deploy" / "RUNBOOK.md").read_text(encoding="utf-8")
        self.assertIn("Horizon: the 5-10 year view", runbook)
        self.assertIn("component on agent_horizon", runbook)
        self.assertIn("horizon run --yes", runbook)
        self.assertIn("±10% at most", runbook)


class GatedTaskTests(TestCase):

    def test_the_task_skips_when_the_component_is_off(self):
        from brain.tasks import run_horizon
        from brain.horizon_models import HorizonView
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.create(key="platform_master", name="m",
                                         category="system", is_enabled=True)
        PlatformComponent.objects.create(key="agent_horizon", name="h",
                                         category="agent", is_enabled=False)
        out = run_horizon()
        self.assertEqual(out["status"], "skipped")
        self.assertFalse(HorizonView.objects.exists())
