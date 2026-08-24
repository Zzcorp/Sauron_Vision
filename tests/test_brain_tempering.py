"""The brain learns patience: escalating anomaly backoff, regime hysteresis.

A standing condition — the same RVOL spike, the same narrative gap — used
to re-alert every 90 minutes, ~16 near-identical observations a day. Now
each repeat doubles the quiet period up to a 6-hour ceiling, chosen so a
truly standing anomaly still crosses consolidation's >=3-fires/24h
promotion bar. And the regime label, which flipped three times in a day
on 0.4-confidence votes, now demands conviction (>=0.65) or persistence
(two consecutive votes) before a flip between known labels stands.

Run with:  python manage.py test tests.test_brain_tempering
"""
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone


def _fire(det="rvol_spike", key="TSLA", minutes_ago=0):
    from brain.models import BrainObservation
    obs = BrainObservation.objects.create(
        kind="anomaly_detected",
        payload={"detector": det, "key": key},
        source_agent="anomaly_scanner",
    )
    if minutes_ago:
        BrainObservation.objects.filter(id=obs.id).update(
            created_at=timezone.now() - timedelta(minutes=minutes_ago))
    return obs


class BackoffLadderTests(TestCase):
    def test_the_ladder_reads_90_180_then_the_cap(self):
        from brain.anomaly_scanner import (BACKOFF_CAP_MINUTES,
                                           _backoff_minutes)
        self.assertEqual(_backoff_minutes(0), 90)
        self.assertEqual(_backoff_minutes(1), 180)
        self.assertEqual(_backoff_minutes(2), 360)
        self.assertEqual(_backoff_minutes(7), BACKOFF_CAP_MINUTES)

    def test_the_cap_keeps_the_promotion_bar_reachable(self):
        """Consolidation promotes at >=3 fires/24h, and emissions land on
        the 30-min beat grid — real spacing is cap + up to one tick, so
        the guaranteed count is floor(1440 / (cap + 30)), which stays
        >= 3 only while the cap is <= 450. The 6h cap gives 4 with
        margin; this trips before a raised cap silently starves the
        promotion it exists to feed."""
        from brain.anomaly_scanner import BACKOFF_CAP_MINUTES
        self.assertLessEqual(BACKOFF_CAP_MINUTES, 6 * 60)
        self.assertGreaterEqual(1440 // (BACKOFF_CAP_MINUTES + 30), 3)

    def test_a_fresh_anomaly_emits_and_an_immediate_repeat_does_not(self):
        from brain.anomaly_scanner import _emit_anomalies
        self.assertEqual(_emit_anomalies(
            [{"detector": "rvol_spike", "key": "TSLA"}]), 1)
        self.assertEqual(_emit_anomalies(
            [{"detector": "rvol_spike", "key": "TSLA"}]), 0)

    def test_the_familiar_90_still_greets_a_first_repeat(self):
        """One prior fire: the hold is the old 90 minutes, exactly as
        the module promises — a fresh anomaly re-alerts as before."""
        from brain.anomaly_scanner import _emit_anomalies
        _fire(key="TSLA", minutes_ago=60)
        self.assertEqual(_emit_anomalies(
            [{"detector": "rvol_spike", "key": "TSLA"}]), 0)
        _fire(key="NVDA", minutes_ago=100)
        self.assertEqual(_emit_anomalies(
            [{"detector": "rvol_spike", "key": "NVDA"}]), 1)

    def test_the_second_repeat_waits_out_the_doubled_window(self):
        """Two prior fires: the flat 90-min dedupe would re-emit at
        100 minutes, the 180-min escalated hold must not."""
        from brain.anomaly_scanner import _emit_anomalies
        _fire(minutes_ago=200)
        _fire(minutes_ago=100)
        self.assertEqual(_emit_anomalies(
            [{"detector": "rvol_spike", "key": "TSLA"}]), 0)

    def test_the_doubled_window_reopens_once_served(self):
        from brain.anomaly_scanner import _emit_anomalies
        _fire(minutes_ago=400)
        _fire(minutes_ago=200)  # two prior fires, hold is 180 — served
        self.assertEqual(_emit_anomalies(
            [{"detector": "rvol_spike", "key": "TSLA"}]), 1)

    def test_a_seasoned_repeat_sits_behind_the_cap(self):
        """Three fires today, latest 5h ago — inside the 6h ceiling."""
        from brain.anomaly_scanner import _emit_anomalies
        _fire(minutes_ago=20 * 60)
        _fire(minutes_ago=12 * 60)
        _fire(minutes_ago=5 * 60)
        self.assertEqual(_emit_anomalies(
            [{"detector": "rvol_spike", "key": "TSLA"}]), 0)

    def test_distinct_keys_never_share_a_hold(self):
        from brain.anomaly_scanner import _emit_anomalies
        _fire(key="TSLA", minutes_ago=30)
        self.assertEqual(_emit_anomalies(
            [{"detector": "rvol_spike", "key": "NVDA"}]), 1)


class DetectorKeyTests(TestCase):
    """The ladder and the promotion counter are only as honest as the
    keys they aggregate by."""

    def _src(self, rel):
        from pathlib import Path

        from django.conf import settings
        return (Path(settings.BASE_DIR) / "brain" / rel).read_text(
            encoding="utf-8")

    def test_midnight_does_not_reset_the_ladder(self):
        """A dated key restarted escalation — and split a late-day
        condition's fires across two keys, under the promotion bar —
        every UTC midnight. Only the event-like regime flip keeps its
        date; standing-condition detectors are date-blind."""
        src = self._src("anomaly_scanner.py")
        self.assertNotIn("%Y%m%d", src.split("def detect_rvol_spike")[1]
                         .split("def detect_")[0])
        self.assertNotIn(
            "%Y%m%d",
            src.split("def detect_narrative_price_divergence")[1]
            .split("def detect_")[0])
        self.assertIn("%Y%m%d", src.split("def detect_brain_regime_flip")[1]
                      .split("def detect_")[0])

    def test_pair_detectors_do_not_share_a_key_namespace(self):
        """Consolidation counts per KEY alone; two detectors emitting the
        same rule-pair key pooled fire counts into a mongrel node."""
        src = self._src("correlation_audit.py")
        self.assertIn('f"sigoverlap:{names[0]}__VS__{names[1]}"', src)
        self.assertIn('f"retcorr:{names[0]}__VS__{names[1]}"', src)


class RegimeHysteresisTests(TestCase):
    def _report(self, label="trending", conf=0.8, minutes_ago=30):
        from brain.models import BrainReport
        rep = BrainReport.objects.create(
            regime_label=label, regime_confidence=conf)
        if minutes_ago:
            BrainReport.objects.filter(id=rep.id).update(
                created_at=timezone.now() - timedelta(minutes=minutes_ago))
        return rep

    def _vote(self, label, conf=0.5, minutes_ago=30):
        from brain.models import BrainObservation
        obs = BrainObservation.objects.create(
            kind="regime_vote",
            payload={"label": label, "confidence": conf},
            source_agent="synthesizer",
            consumed_by_brain_at=timezone.now(),
        )
        if minutes_ago:
            BrainObservation.objects.filter(id=obs.id).update(
                created_at=timezone.now() - timedelta(minutes=minutes_ago))
        return obs

    def test_a_held_flip_repeats_the_standing_report_exactly(self):
        """Same label AND same confidence: the knowledge-graph upsert
        no-ops on an exact repeat, so a noisy dissenting vote publishes
        nothing. (Dragging the confidence down to the dissent's — the
        first draft — republished the node on every wiggle, the very
        churn this gate exists to stop.)"""
        from brain.synthesizer import _apply_regime_hysteresis
        self._report("trending", conf=0.8)
        label, conf = _apply_regime_hysteresis("risk_off", 0.45)
        self.assertEqual((label, conf), ("trending", 0.8))

    def test_a_confident_flip_stands_alone(self):
        from brain.synthesizer import _apply_regime_hysteresis
        self._report("trending", conf=0.8)
        label, conf = _apply_regime_hysteresis("risk_off", 0.7)
        self.assertEqual((label, conf), ("risk_off", 0.7))

    def test_the_second_consecutive_vote_carries_the_flip(self):
        from brain.synthesizer import _apply_regime_hysteresis
        self._report("trending", conf=0.8)
        self._vote("risk_off", minutes_ago=30)
        label, _ = _apply_regime_hysteresis("risk_off", 0.45)
        self.assertEqual(label, "risk_off")

    def test_a_stale_vote_confirms_nothing(self):
        from brain.synthesizer import (VOTE_CONFIRM_WINDOW_MINUTES,
                                       _apply_regime_hysteresis)
        self._report("trending", conf=0.8)
        self._vote("risk_off",
                   minutes_ago=VOTE_CONFIRM_WINDOW_MINUTES + 10)
        label, _ = _apply_regime_hysteresis("risk_off", 0.45)
        self.assertEqual(label, "trending")

    def test_unknown_passes_freely_both_ways(self):
        """A blackout reading is not a regime worth defending — and a
        recovery from blackout must not be held hostage to it."""
        from brain.synthesizer import _apply_regime_hysteresis
        self._report("unknown", conf=0.0)
        self.assertEqual(
            _apply_regime_hysteresis("trending", 0.4)[0], "trending")
        from brain.models import BrainReport
        BrainReport.objects.all().delete()
        self._report("trending", conf=0.8)
        self.assertEqual(
            _apply_regime_hysteresis("unknown", 0.0)[0], "unknown")

    def test_a_blackout_cannot_launder_a_flip(self):
        """A malformed parse clamps to unknown; one weak vote later the
        standing regime would be gone — flips OUT of a blackout are
        gated against the last KNOWN label, and a weak stranger stays
        unconfirmed: the report keeps saying unknown."""
        from brain.synthesizer import _apply_regime_hysteresis
        self._report("trending", conf=0.8, minutes_ago=60)
        self._report("unknown", conf=0.0, minutes_ago=30)
        label, _ = _apply_regime_hysteresis("risk_off", 0.3)
        self.assertEqual(label, "unknown")

    def test_recovery_from_blackout_to_the_known_label_is_free(self):
        """Returning to the regime we last knew is recovery, not a flip
        — it must not be held hostage to the blackout's confidence."""
        from brain.synthesizer import _apply_regime_hysteresis
        self._report("trending", conf=0.8, minutes_ago=60)
        self._report("unknown", conf=0.0, minutes_ago=30)
        label, conf = _apply_regime_hysteresis("trending", 0.3)
        self.assertEqual((label, conf), ("trending", 0.3))

    def test_the_newest_vote_governs_the_confirmation(self):
        """An old agreeing vote must not outrank a newer disagreeing one
        — the confirmation is the IMMEDIATELY-prior cadence's raw vote,
        not anything favorable within the window."""
        from brain.synthesizer import _apply_regime_hysteresis
        self._report("trending", conf=0.8)
        self._vote("risk_off", minutes_ago=110)
        self._vote("trending", minutes_ago=50)
        label, _ = _apply_regime_hysteresis("risk_off", 0.45)
        self.assertEqual(label, "trending")

    def test_the_first_report_ever_takes_the_vote_as_given(self):
        from brain.synthesizer import _apply_regime_hysteresis
        self.assertEqual(
            _apply_regime_hysteresis("risk_off", 0.3)[0], "risk_off")

    def test_the_vote_goes_on_record_pre_consumed(self):
        """An unconsumed vote would be fed straight back into the next
        synthesis — the brain eating its own echo."""
        from brain.models import BrainObservation
        from brain.synthesizer import _record_regime_vote
        _record_regime_vote("trending", 0.55)
        vote = BrainObservation.objects.get(kind="regime_vote")
        self.assertIsNotNone(vote.consumed_by_brain_at)
        self.assertEqual(vote.payload["label"], "trending")

    def test_persist_report_routes_the_raw_vote_through_hysteresis(self):
        """End-to-end: a held flip stores the standing label on the
        report AND records the raw vote for the next cadence to read."""
        from brain.models import BrainObservation
        from brain.synthesizer import _persist_report
        self._report("trending", conf=0.8)
        rep = _persist_report(
            {"regime_label": "risk_off", "regime_confidence": 0.4},
            {}, model="t", tokens_in=0, tokens_out=0, cost_usd=0,
            n_consumed=0)
        self.assertEqual(rep.regime_label, "trending")
        vote = BrainObservation.objects.filter(kind="regime_vote").latest(
            "created_at")
        self.assertEqual(vote.payload["label"], "risk_off")

    def test_an_errored_synthesis_neither_votes_nor_holds(self):
        """error != "" writes the unknown default straight through and
        records no vote — a failed parse is not an opinion."""
        from brain.models import BrainObservation
        from brain.synthesizer import _persist_report
        self._report("trending", conf=0.8)
        rep = _persist_report({}, {}, model="t", tokens_in=0,
                              tokens_out=0, cost_usd=0, n_consumed=0,
                              error="boom")
        self.assertEqual(rep.regime_label, "unknown")
        self.assertEqual(
            BrainObservation.objects.filter(kind="regime_vote").count(), 0)
