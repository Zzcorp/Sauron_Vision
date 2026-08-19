"""CLI: re-open hypotheses that were refuted by a measurement failure.

Before the grading fix, `brain.hypotheses._resolve_regime_holds` compared the
claimed regime against `BrainReport.regime_label` even when that label was
REGIME_UNKNOWN — the "we could not classify it" sentinel. A claim of
"trending" graded against a non-measurement came out REFUTED with the note
`actual=unknown`. `_resolve_anomaly_persists` did the same with `no_node`,
and `brain.calibration` stamped `was_correct=False` on predictions it simply
had no reading for.

Those rows are still on the books, still dragging every Brier-derived trust
score, and still visible to the auto-demoter (which kills rules whose birth
hypothesis was OUTCOME_REFUTED). This command re-opens exactly them to
OUTCOME_UNRESOLVABLE, which the calibration maths excludes.

Safety:
  - dry-run by default; nothing is written without --apply
  - idempotent: a repaired row no longer matches the selectors
  - the past is never rewritten. Each correction appends a NEW
    `hypothesis_resolution_corrected` entry to the hash-chained audit log
    beside the original `hypothesis_resolved` entry, so the mis-grade and its
    correction both stay readable and the chain still verifies.

Usage:
    python manage.py repair_hypothesis_grading            # report only
    python manage.py repair_hypothesis_grading --apply    # write
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q
from django.utils import timezone


# Notes written by the old resolvers when they graded a non-measurement.
# `actual=unknown` is the exact legacy note format; the fixed resolver writes
# `actual=X expected=Y`, so no repaired or newly-graded row can match these.
LEGACY_REGIME_NOTE = "actual=unknown"
LEGACY_ANOMALY_NOTE = "no_node"

# AgentPrediction.actual_value strings that were never a measurement. Only
# brain.calibration and the hypothesis mirror ever wrote these — Signal-backed
# grades store hit_target / stopped_out / expired, so nothing genuine matches.
PREDICTION_UNGRADEABLE_ACTUALS = {
    "no_report_after_deadline",   # calibration: nothing witnessed the deadline
    "no_recent_data",             # calibration: rule had no closed trades
    "summary_unavailable",        # calibration: grading module import failed
    "actual=unknown",             # hypothesis mirror of the same failure
}

# A bare "unknown" is only the regime sentinel when it came from the regime
# resolver — scoped so no future prediction type can be caught by accident.
PREDICTION_UNGRADEABLE_Q = (
    Q(actual_value__in=PREDICTION_UNGRADEABLE_ACTUALS)
    | Q(prediction_type="regime_persistence", actual_value="unknown")
)


def _mis_refuted_reason(hyp) -> str:
    """Return why this refuted row is a mis-grade, or "" if it is genuine.

    Deliberately narrow: it matches only the note shapes the buggy resolvers
    produced. A hypothesis that was refuted by a real measurement reads
    `actual=risk_off ...` or `confidence=0.31` and is left exactly as it is.
    """
    kind = (hyp.resolution_criteria or {}).get("kind")
    note = (hyp.resolution_notes or "").strip()

    if kind == "regime_holds":
        # Legacy note was the whole field; tolerate trailing text but require
        # the actual token to be the not-measured sentinel.
        first = note.split()[0] if note else ""
        if first != LEGACY_REGIME_NOTE:
            return ""
        expected = (hyp.resolution_criteria or {}).get("regime") or "?"
        if expected == "unknown":
            # The old resolver would have CONFIRMED this (unknown == unknown),
            # so a refuted row here is an inconsistent record. Re-open rather
            # than promote it — we won't award a hit we can't account for.
            return ("claimed 'unknown' against actual=unknown yet landed "
                    "refuted — an inconsistent grade, not a measurement")
        return (f"claim '{expected}' was graded against actual=unknown, the "
                f"not-measured sentinel — no measurement of the regime exists")

    if kind == "anomaly_persists":
        if note != LEGACY_ANOMALY_NOTE:
            return ""
        key = (hyp.resolution_criteria or {}).get("anomaly_key") or "?"
        return (f"anomaly '{key}' was never recorded in the knowledge graph — "
                f"a gap in the record, not evidence it faded")

    return ""


class Command(BaseCommand):
    help = ("Re-open hypotheses refuted by a measurement failure "
            "(actual=unknown / no_node) to unresolvable. Dry-run unless --apply.")

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true",
            help="Write the corrections. Without it the command only reports.",
        )

    # ── Reporting helpers ────────────────────────────────────────────────

    def _rule(self):
        self.stdout.write("=" * 78)

    def handle(self, *args, **opts):
        from brain.knowledge_models import Hypothesis
        from ai_agents.models import AgentPrediction

        apply_ = bool(opts.get("apply"))

        # ── Scan ─────────────────────────────────────────────────────────
        targets = []
        for hyp in (Hypothesis.objects
                    .filter(outcome=Hypothesis.OUTCOME_REFUTED)
                    .order_by("id")):
            reason = _mis_refuted_reason(hyp)
            if reason:
                targets.append((hyp, reason))

        linked_pred_ids = {
            h.agent_prediction_id for h, _ in targets if h.agent_prediction_id
        }
        # Predictions the mirror already stamped False for an ungraded claim.
        mirrored = list(AgentPrediction.objects.filter(
            id__in=linked_pred_ids, was_correct=False))
        # Predictions brain.calibration graded off a non-measurement directly.
        standalone = list(AgentPrediction.objects
                          .filter(PREDICTION_UNGRADEABLE_Q, was_correct=False)
                          .exclude(id__in=linked_pred_ids)
                          .order_by("id"))

        # ── Report ───────────────────────────────────────────────────────
        self._rule()
        mode = "APPLY" if apply_ else "DRY RUN"
        self.stdout.write(f"  repair_hypothesis_grading — {mode}")
        self._rule()

        if not targets and not standalone:
            self.stdout.write(self.style.SUCCESS(
                "  Nothing to repair: no hypothesis was refuted by a "
                "measurement failure, and no prediction was scored off one."))
            self._rule()
            return

        if targets:
            self.stdout.write(f"  Hypotheses refuted by a non-measurement: "
                              f"{len(targets)}")
            self.stdout.write("")
            for hyp, reason in targets:
                self.stdout.write(
                    f"  #{hyp.id:<6} [{hyp.source_agent}] "
                    f"conf={hyp.confidence:.2f}  {hyp.claim_text[:52]}")
                self.stdout.write(f"          note: {hyp.resolution_notes[:70]}")
                self.stdout.write(f"          why:  {reason}")
            self.stdout.write("")

        if mirrored:
            self.stdout.write(
                f"  Linked AgentPredictions stamped wrong by the mirror: "
                f"{len(mirrored)} (ids {sorted(p.id for p in mirrored)})")
        if standalone:
            self.stdout.write(
                f"  AgentPredictions graded off a non-measurement by "
                f"brain.calibration: {len(standalone)}")
            for p in standalone[:20]:
                self.stdout.write(
                    f"    #{p.id:<6} {p.agent}/{p.prediction_type} "
                    f"predicted={p.predicted_value[:24]} "
                    f"actual={p.actual_value[:28]}")
            if len(standalone) > 20:
                self.stdout.write(f"    … and {len(standalone) - 20} more")
        self.stdout.write("")

        # Per-agent trust before, so the operator can see the number move.
        agents = sorted({h.source_agent for h, _ in targets}
                        | {p.agent for p in standalone})
        before = self._trust_snapshot(agents)

        if not apply_:
            self.stdout.write(self.style.WARNING(
                "  DRY RUN — nothing written. Re-run with --apply to repair."))
            self.stdout.write("  Trust scores as they stand (corrupted):")
            for line in self._format_trust(before):
                self.stdout.write(line)
            self._rule()
            return

        # ── Apply ────────────────────────────────────────────────────────
        n_hyp, n_pred, n_audit = self._apply(targets, mirrored, standalone)

        self.stdout.write(self.style.SUCCESS(
            f"  Repaired {n_hyp} hypothes{'is' if n_hyp == 1 else 'es'} to "
            f"unresolvable, un-evaluated {n_pred} prediction(s), "
            f"appended {n_audit} audit correction(s)."))
        after = self._trust_snapshot(agents)
        self.stdout.write("  Trust scores (before -> after):")
        for line in self._format_trust(after, before=before):
            self.stdout.write(line)

        # The chain must still verify — corrections are appends, not edits.
        try:
            from bot_program.audit import verify_chain
            chk = verify_chain()
            if chk.get("ok"):
                self.stdout.write(self.style.SUCCESS(
                    f"  Audit chain verifies across {chk.get('verified')} entries."))
            else:
                self.stdout.write(self.style.ERROR(
                    f"  Audit chain reports breaks: {chk.get('breaks')}"))
        except Exception as e:  # pragma: no cover - audit is best-effort
            self.stdout.write(self.style.WARNING(
                f"  Could not verify audit chain: {e}"))
        self._rule()

    # ── Write path ───────────────────────────────────────────────────────

    def _apply(self, targets, mirrored, standalone) -> tuple[int, int, int]:
        """Perform the corrections. Returns (hypotheses, predictions, audits)."""
        from brain.knowledge_models import Hypothesis

        now = timezone.now()
        stamp = now.strftime("%Y-%m-%d %H:%M")
        mirrored_by_id = {p.id: p for p in mirrored}
        n_audit = 0

        with transaction.atomic():
            for hyp, reason in targets:
                previous_outcome = hyp.outcome
                previous_notes = hyp.resolution_notes or ""
                hyp.outcome = Hypothesis.OUTCOME_UNRESOLVABLE
                # Keep the original note — the operator needs to see what the
                # resolver claimed — and append what we changed and why.
                hyp.resolution_notes = (
                    f"{previous_notes}\n[{stamp}] repair_hypothesis_grading: "
                    f"re-opened refuted -> unresolvable. {reason}").strip()
                hyp.save(update_fields=["outcome", "resolution_notes"])

                pred = mirrored_by_id.get(hyp.agent_prediction_id)
                if pred is not None:
                    self._unevaluate(pred, stamp, reason)

                if self._audit_correction(
                        hypothesis=hyp, previous_outcome=previous_outcome,
                        previous_notes=previous_notes, reason=reason,
                        prediction_id=(pred.id if pred is not None else None)):
                    n_audit += 1

            for pred in standalone:
                reason = (f"graded off '{pred.actual_value}', which is a "
                          f"not-measured sentinel, not an observation")
                self._unevaluate(pred, stamp, reason)
                if self._audit_correction(
                        hypothesis=None, previous_outcome="was_correct=False",
                        previous_notes=pred.actual_value or "", reason=reason,
                        prediction_id=pred.id, agent=pred.agent):
                    n_audit += 1

        return len(targets), len(mirrored) + len(standalone), n_audit

    @staticmethod
    def _unevaluate(pred, stamp: str, reason: str) -> None:
        """Return a prediction to unevaluated so the Brier maths skips it.

        `was_correct=None` is the model's own "not yet evaluated" state, which
        every calibration consumer filters on — this removes the row from the
        score without inventing a correct answer for it.
        """
        pred.was_correct = None
        pred.evaluated_at = None
        pred.evaluation_notes = (
            f"{pred.evaluation_notes or ''}\n[{stamp}] "
            f"repair_hypothesis_grading: un-evaluated — {reason}").strip()
        pred.save(update_fields=["was_correct", "evaluated_at",
                                 "evaluation_notes"])

    @staticmethod
    def _audit_correction(*, hypothesis, previous_outcome: str,
                          previous_notes: str, reason: str,
                          prediction_id=None, agent: str = "") -> bool:
        """Append a correction entry to the hash chain.

        We never touch the original `hypothesis_resolved` entry: the log is
        hash-chained, so editing history would break verification AND destroy
        the evidence that the mis-grade happened. A correction is a new link.
        """
        try:
            from bot_program.audit import record_event
            data = {
                "hypothesis_id": getattr(hypothesis, "id", None),
                "source_agent": getattr(hypothesis, "source_agent", agent),
                "claim_text": (getattr(hypothesis, "claim_text", "") or "")[:300],
                "previous_outcome": previous_outcome,
                "corrected_outcome": (
                    "unresolvable" if hypothesis is not None else "unevaluated"),
                "previous_resolution_notes": (previous_notes or "")[:300],
                "reason": reason[:300],
                "agent_prediction_id": prediction_id,
                "corrected_by": "repair_hypothesis_grading",
            }
            return record_event("hypothesis_resolution_corrected", data) is not None
        except Exception:  # pragma: no cover - audit never blocks the repair
            return False

    # ── Trust reporting ──────────────────────────────────────────────────

    @staticmethod
    def _trust_snapshot(agents) -> dict:
        from brain.hypotheses import agent_trust_score
        from brain.context import _brain_trust_score
        snap = {}
        for a in agents:
            try:
                snap[a] = agent_trust_score(a)
            except Exception:  # pragma: no cover
                snap[a] = None
        try:
            snap["(brain predictions)"] = _brain_trust_score()
        except Exception:  # pragma: no cover
            snap["(brain predictions)"] = None
        return snap

    @staticmethod
    def _format_trust(snap: dict, *, before: dict = None) -> list[str]:
        lines = []
        for agent, score in snap.items():
            # Unknown renders as an em-dash — never as 0, which reads as
            # "measured and terrible" rather than "no data".
            now_s = "—" if score is None else f"{score:.4f}"
            if before is None:
                lines.append(f"    {agent:<24} {now_s}")
                continue
            prev = before.get(agent)
            prev_s = "—" if prev is None else f"{prev:.4f}"
            lines.append(f"    {agent:<24} {prev_s} -> {now_s}")
        return lines
