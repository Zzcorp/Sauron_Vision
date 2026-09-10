"""No prose without a claim the platform can grade.

Five prediction kinds existed and none was a price direction, though the
model's own comment listed it first. Every agent that talked about a
symbol — the strategy advisor's long/short legs, the anomaly scan, the
three prose briefings — talked into a void: prose, or a table nothing
read, and a trust score with nothing to score. The strategist then read
that agent's trust as "unresolvable" for as long as the platform ran.

A direction call is the smallest falsifiable claim here: a symbol, up or
down, a horizon, and the price it was measured from. It resolves against
the first bar at or after the deadline, with no model in the loop. The
advisor's legs register one per leg; the anomaly scan registers the ones
it gives a direction; the three briefings end with a calls block and every
call in it is registered. The calibration page shows the ledger.

Run with:  python manage.py test tests.test_gradable_calls
"""
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase
from django.utils import timezone


class TheVocabularyTests(SimpleTestCase):

    def test_directions_are_normalised(self):
        from ai_agents.calibration import normalise_direction
        for word in ("up", "long", "BUY", "Bullish", "higher"):
            self.assertEqual(normalise_direction(word), "up", word)
        for word in ("down", "short", "sell", "bearish"):
            self.assertEqual(normalise_direction(word), "down", word)
        self.assertIsNone(normalise_direction("hedge"))
        self.assertIsNone(normalise_direction(None))

    def test_horizons_are_clamped_and_named(self):
        from ai_agents.calibration import (DIRECTION_MAX_HORIZON_H,
                                           HORIZON_HOURS_FOR, clamp_horizon)
        self.assertEqual(clamp_horizon(24), 24.0)
        self.assertEqual(clamp_horizon("x", 12.0), 12.0)
        self.assertEqual(clamp_horizon(0.01), 1.0)
        self.assertEqual(clamp_horizon(10 ** 6), DIRECTION_MAX_HORIZON_H)
        self.assertLess(HORIZON_HOURS_FOR["scalp"], HORIZON_HOURS_FOR["swing"])
        self.assertLess(HORIZON_HOURS_FOR["swing"],
                        HORIZON_HOURS_FOR["position"])

    def test_calls_are_read_from_the_last_fenced_block(self):
        from ai_agents.calibration import extract_calls
        text = ("Market Overview: ...\n```json\n{\"calls\": []}\n```\n"
                "More prose.\n```json\n{\"calls\": [{\"symbol\": \"AAPL\", "
                "\"direction\": \"up\", \"horizon_hours\": 24}, 7]}\n```")
        calls = extract_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["symbol"], "AAPL")

    def test_prose_without_a_block_yields_nothing_and_never_raises(self):
        from ai_agents.calibration import extract_calls
        self.assertEqual(extract_calls("Just prose."), [])
        self.assertEqual(extract_calls("```json\n{not json}\n```"), [])
        self.assertEqual(extract_calls(None), [])

    def test_every_prose_agent_is_told_to_end_with_calls(self):
        src = (Path(settings.BASE_DIR) / "ai_agents" / "tasks.py"
               ).read_text(encoding="utf-8")
        self.assertGreaterEqual(src.count("+ CALLS_INSTRUCTION"), 2)
        weekly = (Path(settings.BASE_DIR) / "ai_agents" / "agents"
                  / "weekly_reviewer.py").read_text(encoding="utf-8")
        self.assertIn("CALLS_INSTRUCTION", weekly)
        anomaly = (Path(settings.BASE_DIR) / "ai_agents" / "agents"
                   / "anomaly_detector.py").read_text(encoding="utf-8")
        self.assertIn("expected_direction", anomaly)
        self.assertIn("horizon_hours", anomaly)

    def test_the_instruction_asks_for_the_shape_the_parser_reads(self):
        from ai_agents.calibration import CALLS_INSTRUCTION, extract_calls
        self.assertIn('"calls"', CALLS_INSTRUCTION)
        example = CALLS_INSTRUCTION.split("shape: ")[1].split(" — ")[0]
        self.assertEqual(len(extract_calls(f"```json\n{example}\n```")), 1)


def _instrument(symbol="AAPL", asset_class="stock"):
    from instruments.models import Instrument
    inst, _ = Instrument.objects.get_or_create(
        symbol=symbol, defaults={"name": symbol, "asset_class": asset_class})
    return inst


def _bar(inst, when, close, timeframe="1h"):
    from market_data.models import PriceData
    return PriceData.objects.create(
        instrument=inst, timeframe=timeframe, timestamp=when,
        open=close, high=close, low=close, close=Decimal(str(close)),
        volume=1, source="test")


class RegisteringACallTests(TestCase):

    def setUp(self):
        self.inst = _instrument("AAPL")
        self.now = timezone.now()
        _bar(self.inst, self.now - timedelta(hours=1), 100.0)

    def _log(self, **kw):
        from ai_agents.calibration import log_direction_prediction
        args = dict(agent="strategy_advisor", symbol="aapl", direction="long",
                    horizon_hours=24, confidence=0.7, notes="thesis")
        args.update(kw)
        return log_direction_prediction(**args)

    def test_a_call_carries_everything_its_grade_needs(self):
        pred = self._log()
        self.assertIsNotNone(pred)
        self.assertEqual(pred.prediction_type, "direction")
        self.assertEqual(pred.predicted_value, "up")
        self.assertEqual(pred.instrument_symbol, "AAPL")
        self.assertEqual(float(pred.reference_price), 100.0)
        self.assertEqual(pred.horizon_hours, 24.0)
        self.assertAlmostEqual(
            (pred.expected_resolution_at - self.now).total_seconds() / 3600,
            24.0, places=2)
        self.assertEqual(pred.confidence, 0.7)
        self.assertIsNone(pred.was_correct)

    def test_a_fresh_quote_beats_the_bar_as_the_reference(self):
        from market_data.models import LiveQuote
        LiveQuote.objects.create(instrument=self.inst, last=Decimal("101.5"),
                                 source="test")
        self.assertEqual(float(self._log().reference_price), 101.5)

    def test_no_direction_no_symbol_no_price_means_no_row(self):
        from ai_agents.models import AgentPrediction
        self.assertIsNone(self._log(direction="hedge"))
        self.assertIsNone(self._log(symbol="NOPE"))
        _instrument("MUTE")                     # exists, but no price at all
        self.assertIsNone(self._log(symbol="MUTE"))
        self.assertEqual(AgentPrediction.objects.count(), 0)

    def test_one_live_call_per_agent_per_symbol(self):
        """An hourly scan re-detects the same condition every hour."""
        from ai_agents.models import AgentPrediction
        self.assertIsNotNone(self._log())
        self.assertIsNone(self._log())
        self.assertIsNotNone(self._log(agent="anomaly_detector"))
        self.assertEqual(AgentPrediction.objects.count(), 2)

    def test_a_proposal_registers_one_call_per_directional_leg(self):
        from ai_agents.calibration import register_proposal_calls
        from ai_agents.models import AgentPrediction
        _instrument("MSFT")
        _bar(_instrument("MSFT"), self.now - timedelta(hours=1), 50.0)
        n = register_proposal_calls("strategy_advisor", {
            "thesis": "rotation", "time_horizon": "swing", "confidence": 0.8,
            "instruments": [{"symbol": "AAPL", "action": "long"},
                            {"symbol": "MSFT", "action": "short"},
                            {"symbol": "GLD", "action": "hedge"}]})
        self.assertEqual(n, 2)
        rows = {p.instrument_symbol: p for p in AgentPrediction.objects.all()}
        self.assertEqual(rows["AAPL"].horizon_hours, 120.0)
        self.assertEqual(rows["MSFT"].predicted_value, "down")
        self.assertEqual(rows["AAPL"].confidence, 0.8)

    def test_a_briefings_calls_block_is_registered(self):
        from ai_agents.calibration import extract_calls, register_calls
        text = ("prose\n```json\n{\"calls\": [{\"symbol\": \"AAPL\", "
                "\"direction\": \"down\", \"horizon_hours\": 48, "
                "\"confidence\": 0.55, \"why\": \"tired\"}]}\n```")
        self.assertEqual(register_calls("daily_briefing",
                                        extract_calls(text)), 1)


class GradingACallTests(TestCase):

    def setUp(self):
        self.inst = _instrument("AAPL")
        self.made = timezone.now() - timedelta(hours=30)
        self.deadline = self.made + timedelta(hours=24)

    def _call(self, direction="up", reference=100.0):
        from ai_agents.models import AgentPrediction
        return AgentPrediction.objects.create(
            agent="strategy_advisor", prediction_type="direction",
            predicted_value=direction, instrument_symbol="AAPL",
            confidence=0.6, expected_resolution_at=self.deadline,
            reference_price=Decimal(str(reference)), horizon_hours=24.0)

    def _resolve(self):
        from ai_agents.calibration import resolve_pending_predictions
        return resolve_pending_predictions()

    def test_a_correct_call_is_graded_with_its_move(self):
        pred = self._call("up")
        _bar(self.inst, self.deadline + timedelta(minutes=30), 103.0)
        out = self._resolve()
        pred.refresh_from_db()
        self.assertEqual(out["by_type"].get("direction"), 1)
        self.assertTrue(pred.was_correct)
        self.assertEqual(pred.actual_value, "up")
        self.assertAlmostEqual(pred.score, 0.03, places=4)
        self.assertIn("100 -> 103", pred.evaluation_notes)

    def test_a_wrong_call_scores_its_loss_in_the_claimed_direction(self):
        pred = self._call("down")
        _bar(self.inst, self.deadline + timedelta(minutes=30), 103.0)
        self._resolve()
        pred.refresh_from_db()
        self.assertFalse(pred.was_correct)
        self.assertAlmostEqual(pred.score, -0.03, places=4)

    def test_flat_is_a_miss_for_a_directional_claim(self):
        pred = self._call("up")
        _bar(self.inst, self.deadline + timedelta(minutes=30), 100.05)
        self._resolve()
        pred.refresh_from_db()
        self.assertFalse(pred.was_correct)
        self.assertEqual(pred.actual_value, "flat")

    def test_the_first_bar_at_or_after_the_deadline_decides(self):
        pred = self._call("up")
        _bar(self.inst, self.deadline - timedelta(hours=2), 120.0)   # before
        _bar(self.inst, self.deadline + timedelta(hours=1), 99.0)    # decides
        _bar(self.inst, self.deadline + timedelta(hours=5), 130.0)   # later
        self._resolve()
        pred.refresh_from_db()
        self.assertEqual(pred.actual_value, "down")

    def test_no_bar_yet_means_wait_not_wrong(self):
        pred = self._call("up")
        self._resolve()                       # 6h past the deadline, no bar
        pred.refresh_from_db()
        self.assertIsNone(pred.was_correct)
        self.assertIsNone(pred.evaluated_at)

    def test_no_bar_within_the_grace_window_is_ungraded_not_wrong(self):
        from ai_agents.calibration import DIRECTION_GRACE_HOURS
        pred = self._call("up")
        pred.expected_resolution_at = timezone.now() - timedelta(
            hours=DIRECTION_GRACE_HOURS + 1)
        pred.save()
        self._resolve()
        pred.refresh_from_db()
        self.assertIsNone(pred.was_correct)
        self.assertEqual(pred.actual_value, "ungradeable_no_bar")
        self.assertIsNotNone(pred.evaluated_at)
        # And it is not walked again every night.
        out = self._resolve()
        self.assertEqual(out["failed"], 0)

    def test_ungraded_calls_do_not_touch_the_trust_score(self):
        from ai_agents.calibration import trust_adjustment_for
        pred = self._call("up")
        pred.expected_resolution_at = timezone.now() - timedelta(days=5)
        pred.save()
        self._resolve()
        self.assertEqual(trust_adjustment_for("strategy_advisor"), 1.0)


class TheLedgerIsShownTests(TestCase):

    def test_the_calibration_page_lists_the_calls(self):
        from ai_agents.models import AgentPrediction
        _instrument("AAPL")
        AgentPrediction.objects.create(
            agent="daily_briefing", prediction_type="direction",
            predicted_value="up", instrument_symbol="AAPL", confidence=0.6,
            expected_resolution_at=timezone.now() + timedelta(hours=24),
            reference_price=Decimal("100"), horizon_hours=24.0)
        user = User.objects.create_user("cal_u", password="x")
        client = Client()
        client.force_login(user)
        html = client.get("/calibration/").content.decode()
        self.assertIn("Calls ledger", html)
        self.assertIn("daily_briefing", html)
        self.assertIn("UP · 0.60", html)
        self.assertIn("pending", html)
