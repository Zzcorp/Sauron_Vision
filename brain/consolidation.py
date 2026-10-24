"""Phase 38.4 — nightly consolidation.

Once per day (03:00 UTC), this task:

  1. Reads the day's BrainObservations + new Hypotheses + resolved Hypotheses
     + most recent BrainReport.
  2. Promotes settled facts into KnowledgeNodes (regime, theme states,
     rule states, persistent anomalies, narrative threads).
  3. Prunes BrainObservations older than 7 days that didn't lead to a
     hypothesis or knowledge update.
  4. Writes a ConsolidationRun summary row.

Why this matters: it's the *forgetting* mechanism. Without compaction, the
observation queue grows unboundedly and agents drown in noise. The graph
keeps the *signal* (load-bearing facts) and discards the rest.

This is pure-Python — no Claude calls. Cheap and deterministic.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)


PRUNE_OBSERVATIONS_OLDER_THAN_DAYS = 7
PRUNE_RESOLVED_HYPOTHESES_OLDER_THAN_DAYS = 30


def _consolidate_regime() -> tuple[bool, bool]:
    """Update the global regime KnowledgeNode from the most recent BrainReport.

    Returns (added, superseded) — each True iff the corresponding action ran.
    """
    from .models import BrainReport
    from .knowledge_models import KnowledgeNode

    report = (BrainReport.objects.filter(error="")
              .order_by("-created_at").first())
    if report is None:
        return False, False

    current = KnowledgeNode.current(KnowledgeNode.KIND_REGIME, "portfolio")
    new_payload = {
        "label": report.regime_label,
        "confidence": report.regime_confidence,
        "as_of": report.created_at.isoformat(),
        "source_report_id": report.id,
    }
    # No-op if state hasn't changed (same label + within ε on confidence).
    if (current and current.payload.get("label") == report.regime_label
            and abs(current.payload.get("confidence", 0)
                     - report.regime_confidence) < 0.05):
        return False, False
    KnowledgeNode.upsert(
        kind=KnowledgeNode.KIND_REGIME, key="portfolio",
        payload=new_payload, confidence=report.regime_confidence,
        source="sauron_mind",
    )
    return True, current is not None


def _consolidate_theme_states() -> tuple[int, int]:
    """For each theme in the most recent BrainReport's theme_pressures, upsert
    a KnowledgeNode `theme_state:<theme>` whose payload tracks the pressure."""
    from .models import BrainReport
    from .knowledge_models import KnowledgeNode

    report = (BrainReport.objects.filter(error="")
              .order_by("-created_at").first())
    if report is None or not report.theme_pressures:
        return 0, 0

    added = superseded = 0
    for theme, pressure in (report.theme_pressures or {}).items():
        try:
            p = float(pressure)
        except (TypeError, ValueError):
            continue
        current = KnowledgeNode.current(KnowledgeNode.KIND_THEME_STATE, theme)
        if current and abs(current.payload.get("pressure", 0) - p) < 0.1:
            continue
        KnowledgeNode.upsert(
            kind=KnowledgeNode.KIND_THEME_STATE, key=str(theme),
            payload={"pressure": p, "as_of": report.created_at.isoformat()},
            confidence=p, source="sauron_mind",
        )
        added += 1
        if current is not None:
            superseded += 1
    return added, superseded


#: How many scheduled passes in a row must see a fresh report that no
#: longer names a paused or watched rule before the pass releases it
#: (2026-10-24): three nights, one a night, so one empty or malformed
#: overlay can never release anything. A night with no fresh report counts
#: nothing (a Mind that is down keeps its pauses).
RELEASE_AFTER_MISSES = 3

#: A miss is counted once per report and once per night: never twice
#: against the same report, never twice within this many hours. And a
#: releasing pass runs at most once in this many hours: any other run in
#: between (the admin's "Run selected tasks", a second beat, a `celery
#: call`) adds and re-affirms only, as the staff button does. No PIN stands
#: behind those doors, so they must never be able to bring a release
#: forward (2026-10-24).
NIGHT_SPACING_HOURS = 20

#: The words a releasing pass's notes carry, read back by the spacing above.
RELEASING_PASS_MARK = "releasing pass"

#: When no report is fresh at a pass, the newest clean report of the past
#: day (this many hours plus the window, so since the previous scheduled
#: pass) still adds or tightens: a pause the Mind said before it went
#: quiet is remembered, never re-affirmed, counted or released from
#: (2026-10-24).
LAST_REPORT_HOURS = 24

#: The kinds of the audit rows a release writes (bot_program/audit_models,
#: 20 characters at most).
AUDIT_RELEASE = "rule_state_release"
AUDIT_CLEAR = "rule_state_clear"

#: What a release says when the rule's RuleControl row cannot be read.
STAGE_UNREADABLE = ("stage unreadable: check RuleControl, it may reach "
                    "real money")

#: The door that keeps a rule off real money whatever the Mind says, for
#: any rule (2026-10-24): the demote on /promotions/ (superuser; one stage
#: per press). /brain/ draws a lever only for a rule its latest report
#: names at watch or pause, so a released rule has none there.
KEEP_OFF_WORDS = ("To take one off real money whatever the Mind says, "
                  "demote it on /promotions/ (superuser, one stage per "
                  "press: live_full takes two; the automatic promotions "
                  "may raise it again on proof).")


def rule_reach(rule_name: str) -> dict:
    """Where a released rule can trade: its RuleControl status and stage,
    and whether that stage reaches real money (signals/rule_actuator.py's
    stage_policy: no row is the paper venue only). Names only."""
    out = {"control_status": "", "stage": "", "real_money": False,
           "words": "no promotion record (paper venue only)"}
    try:
        from signals.models_control import RuleControl
        row = (RuleControl.objects.filter(rule_name=rule_name)
               .values("status", "promotion_stage").first())
    except Exception:  # noqa: BLE001 — a read for words, never a gate
        # Unknown is said as unknown: a failed read must never read as
        # "paper only" for a rule that may be at live_full.
        out.update(real_money=None, words=STAGE_UNREADABLE)
        return out
    if not row:
        return out
    stage = str(row["promotion_stage"] or "")
    status = str(row["status"] or "")
    out.update(control_status=status, stage=stage,
               real_money=stage in ("live_small", "live_full"))
    out["words"] = (f"stage {stage}"
                    + (": real money" if out["real_money"] else "")
                    + (f", RuleControl {status}" if status and status != "active"
                       else ""))
    return out


def write_rule_state(rule_name: str, payload: dict, *, source: str,
                     confidence: float = 0.7, expect_pk=None):
    """Append one rule_state version under a row lock on the current one,
    or None when the current node is no longer the one the caller read
    (`expect_pk`; a racing writer got there first, and this caller must
    read again). `KnowledgeNode.upsert` alone is not atomic: a clear racing
    the 03:00 pass could leave two current versions."""
    from django.db import transaction
    from .knowledge_models import KnowledgeNode
    with transaction.atomic():
        locked = (KnowledgeNode.objects.select_for_update()
                  .filter(kind=KnowledgeNode.KIND_RULE_STATE,
                          key=str(rule_name), superseded_by__isnull=True)
                  .first())
        if (locked.pk if locked else None) != expect_pk:
            return None
        return KnowledgeNode.upsert(
            kind=KnowledgeNode.KIND_RULE_STATE, key=str(rule_name),
            payload=payload, confidence=confidence, source=source)


def _touch_rule_state(node, changes: dict) -> bool:
    """Bookkeeping on the CURRENT version in place (when the Mind last
    affirmed it, how many fresh nights have since not named it): not a new
    state, so not a new version. False when the node was superseded."""
    from .knowledge_models import KnowledgeNode
    payload = dict(node.payload or {})
    payload.update(changes)
    n = (KnowledgeNode.objects
         .filter(pk=node.pk, superseded_by__isnull=True)
         .update(payload=payload))
    return bool(n)


def _rule_counts(out=None) -> dict:
    """The rule pass's counters, in the caller's dict when it passes one
    (consolidate_now owns it, so a release written before a later step
    raises is still announced). `released_rules` is never reset: what is
    on it was written."""
    out = out if out is not None else {}
    out.update(fresh=False, last_report_age_min=None, added=0, superseded=0,
               reaffirmed=0, missed=0, released=0)
    out.setdefault("released_rules", [])
    return out


def _tighten_from_last_report(now, window: int, out: dict) -> None:
    """No report is fresh at this pass: the Mind is quiet (feed gate,
    spend guard, provider errors). Its last clean report of the past day
    (LAST_REPORT_HOURS plus the window) still ADDS or TIGHTENS a node, so
    a pause it said before it went quiet keeps binding through the outage
    ("a Mind that is down keeps its pauses"). Nothing is re-affirmed,
    counted or released from it, and a node version newer than that
    report (a release or a superuser's clear since) is left as it is."""
    from .context import BINDING_STATUSES, STATUS_RANK
    from .knowledge_models import KnowledgeNode
    from .models import BrainReport

    oldest = now - timedelta(hours=LAST_REPORT_HOURS, minutes=window)
    report = (BrainReport.objects.filter(error="", created_at__gte=oldest)
              .order_by("-created_at").first())
    if report is None:
        return
    age = int((now - report.created_at).total_seconds() // 60)
    out["last_report_age_min"] = age
    overlay = report.rule_status_overlay
    overlay = overlay if isinstance(overlay, dict) else {}
    venues = report.rule_status_venue
    venues = venues if isinstance(venues, dict) else {}
    as_of = report.created_at.isoformat()
    for rule, status in overlay.items():
        if status not in BINDING_STATUSES:
            continue
        rule = str(rule)
        current = KnowledgeNode.current(KnowledgeNode.KIND_RULE_STATE, rule)
        cur_status = (str((current.payload or {}).get("status") or "allow")
                      if current else "allow")
        if STATUS_RANK[status] <= STATUS_RANK.get(cur_status, 0):
            continue
        if current is not None and current.created_at >= report.created_at:
            continue
        new = write_rule_state(
            rule, {"status": status, "as_of": as_of, "affirmed_at": as_of,
                   "misses": 0, "source_report_id": report.id,
                   "venue": str(venues.get(rule) or ""),
                   "why": (f"the Mind's last report ({age} min old at the "
                           f"pass; none was fresh)")},
            source="sauron_mind", expect_pk=current.pk if current else None)
        if new is not None:
            out["added"] += 1
            if current is not None:
                out["superseded"] += 1


def _consolidate_rule_states(*, releases: bool = False, out=None) -> dict:
    """The Mind's memory of its pauses, from its FRESH word.

    The newest clean report younger than the contract's window
    (brain.context.mind_fresh_minutes) is read. None: the last clean report
    of the past day may only add or tighten (_tighten_from_last_report),
    and nothing is re-affirmed, counted or released. Then, per rule:

      * named watch or pause_recommended at the node's own status: the node
        is re-affirmed in place (affirmed_at, misses 0, venue);
      * named at another status: a new version (a new node, a tighter
        one, or with `releases` a looser one);
      * named "active" while the node binds: with `releases`, an "allow"
        version;
      * a binding node the report does not name: with `releases`, one miss
        in place, once per report and once per NIGHT_SPACING_HOURS, and on
        the RELEASE_AFTER_MISSES-th an "allow" version.

    Without `releases` (the staff button, critique H3) nothing is ever
    loosened or counted: it adds and re-affirms only. Every loosening is
    appended to `out["released_rules"]` the moment it is written, for the
    audit rows and the staff notice; `out` is the caller's, so a later
    step raising never hides a release already on disk.
    """
    from .context import (BINDING_STATUSES, STATUS_RANK, _parse_iso,
                          mind_fresh_minutes)
    from .knowledge_models import KnowledgeNode
    from .models import BrainReport

    out = _rule_counts(out)
    now = timezone.now()
    window = mind_fresh_minutes()
    cutoff = now - timedelta(minutes=window)
    report = (BrainReport.objects.filter(error="", created_at__gte=cutoff)
              .order_by("-created_at").first())
    if report is None:
        _tighten_from_last_report(now, window, out)
        return out
    out["fresh"] = True
    overlay = report.rule_status_overlay
    overlay = overlay if isinstance(overlay, dict) else {}
    venues = report.rule_status_venue
    venues = venues if isinstance(venues, dict) else {}
    as_of = report.created_at.isoformat()
    named = {str(rule): status for rule, status in overlay.items()
             if status in (*BINDING_STATUSES, "active")}

    def release(node, why, now_status="allow"):
        was = dict(node.payload or {})
        new = write_rule_state(
            node.key,
            {"status": now_status, "as_of": as_of, "affirmed_at": as_of,
             "misses": 0, "source_report_id": report.id,
             "venue": str(venues.get(node.key) or "") if now_status != "allow"
             else "",
             "why": why, "was_status": str(was.get("status") or "")},
            source="sauron_mind", expect_pk=node.pk)
        if new is None:
            return
        out["released"] += 1
        out["superseded"] += 1
        out["released_rules"].append({
            "rule_name": node.key, "was_status": str(was.get("status") or ""),
            "was_version": node.version, "now_status": now_status,
            "why": why})

    for rule, status in named.items():
        current = KnowledgeNode.current(KnowledgeNode.KIND_RULE_STATE, rule)
        cur_status = str((current.payload or {}).get("status") or "allow") \
            if current else "allow"
        if status == "active":
            if releases and current and cur_status in BINDING_STATUSES:
                release(current, "the Mind's latest fresh report says active")
            continue
        if current and cur_status == status:
            if _touch_rule_state(current, {
                    "affirmed_at": as_of, "misses": 0,
                    "source_report_id": report.id,
                    "venue": str(venues.get(rule) or "")}):
                out["reaffirmed"] += 1
            continue
        looser = (current is not None
                  and STATUS_RANK.get(status, 0) < STATUS_RANK.get(cur_status, 0))
        if looser:
            if releases:
                release(current, f"the Mind's latest fresh report says {status}",
                        now_status=status)
            continue
        new = write_rule_state(
            rule, {"status": status, "as_of": as_of, "affirmed_at": as_of,
                   "misses": 0, "source_report_id": report.id,
                   "venue": str(venues.get(rule) or "")},
            source="sauron_mind", expect_pk=current.pk if current else None)
        if new is not None:
            out["added"] += 1
            if current is not None:
                out["superseded"] += 1

    if not releases:
        return out
    binding = (KnowledgeNode.objects
               .filter(kind=KnowledgeNode.KIND_RULE_STATE,
                       superseded_by__isnull=True)
               .exclude(key__in=list(named)))
    spacing = timedelta(hours=NIGHT_SPACING_HOURS)
    for node in binding:
        payload = node.payload if isinstance(node.payload, dict) else {}
        if payload.get("status") not in BINDING_STATUSES:
            continue
        # One miss per report and one per night: a run repeated against
        # the same report, or within the night, counts nothing more.
        if payload.get("last_missed_report_id") == report.id:
            continue
        last_missed = _parse_iso(payload.get("last_missed_at"))
        if last_missed is not None and now - last_missed < spacing:
            continue
        try:
            misses = max(0, int(payload.get("misses") or 0)) + 1
        except (TypeError, ValueError):
            misses = 1
        if misses >= RELEASE_AFTER_MISSES:
            last = payload.get("affirmed_at") or payload.get("as_of") or "?"
            release(node, (f"not named in {RELEASE_AFTER_MISSES} fresh "
                           f"nightly reports in a row (last affirmed {last})"))
        elif _touch_rule_state(node, {"misses": misses,
                                      "last_missed_report_id": report.id,
                                      "last_missed_at": now.isoformat()}):
            out["missed"] += 1
    return out


def _announce_releases(released: list) -> None:
    """One audit row per release and ONE staff notice for the night,
    naming each rule and where it can trade now. Names and statuses only.
    Fenced: a release that happened is never undone by its announcement."""
    if not released:
        return
    lines = []
    for r in released:
        reach = rule_reach(r["rule_name"])
        try:
            from bot_program.audit import record_event
            record_event(AUDIT_RELEASE, {
                **r, "promotion_stage": reach["stage"],
                "control_status": reach["control_status"],
                "real_money": reach["real_money"]})
        except Exception as e:  # noqa: BLE001
            logger.warning("[consolidation] release audit failed: %s",
                           type(e).__name__)
        blocks = ("its entries are no longer blocked"
                  if r["was_status"] == "pause_recommended"
                  else "no longer watched")
        lines.append(f"{r['rule_name']}: {r['was_status']} -> "
                     f"{r['now_status']} ({r['why']}); {blocks}; "
                     f"{reach['words']}")
    try:
        from bot_program.notifications import notify_staff
        n = len(released)
        notify_staff(
            title=f"Sauron's Mind released {n} rule{'s' if n != 1 else ''}",
            body=("\n".join(lines)
                  + "\nA released rule still passes the stage, proof and "
                    "posture gates. " + KEEP_OFF_WORDS),
            url="/knowledge/", cooldown_hours=1)
    except Exception as e:  # noqa: BLE001
        logger.warning("[consolidation] release notice failed: %s",
                       type(e).__name__)


def _consolidate_anomalies(min_count: int = 3) -> tuple[int, int]:
    """If the same `anomaly_detected` observation kind has fired ≥ `min_count`
    times in the last 24h with the same `payload['key']`, promote to a
    KnowledgeNode `anomaly:<key>`. Otherwise let it fade."""
    from .models import BrainObservation
    from .knowledge_models import KnowledgeNode

    cutoff = timezone.now() - timedelta(hours=24)
    obs = list(BrainObservation.objects
               .filter(kind="anomaly_detected", created_at__gte=cutoff)
               .values_list("payload", flat=True))
    counter = Counter()
    for p in obs:
        key = (p or {}).get("key") if isinstance(p, dict) else None
        if key:
            counter[key] += 1

    added = superseded = 0
    for key, count in counter.items():
        if count < min_count:
            continue
        current = KnowledgeNode.current(KnowledgeNode.KIND_ANOMALY, key)
        new_payload = {
            "key": key, "occurrences_24h": count,
            "promoted_at": timezone.now().isoformat(),
        }
        if current and current.payload.get("occurrences_24h") == count:
            continue
        KnowledgeNode.upsert(
            kind=KnowledgeNode.KIND_ANOMALY, key=str(key),
            payload=new_payload, confidence=min(1.0, count / 10),
            source="consolidation",
        )
        added += 1
        if current is not None:
            superseded += 1
    return added, superseded


def _prune_observations() -> int:
    """Delete BrainObservations older than the cutoff that have already been
    consumed by the brain (so we don't drop unconsumed events)."""
    from .models import BrainObservation
    cutoff = timezone.now() - timedelta(days=PRUNE_OBSERVATIONS_OLDER_THAN_DAYS)
    deleted, _ = (BrainObservation.objects
                  .filter(created_at__lt=cutoff,
                           consumed_by_brain_at__isnull=False)
                  .delete())
    return deleted


def _rule_notes(rules: dict, releases: bool, held_by=None) -> str:
    """The rule_state line of the run's notes. A releasing pass that read
    a fresh report says RELEASING_PASS_MARK: the next run within
    NIGHT_SPACING_HOURS reads it and releases nothing."""
    if not rules.get("fresh"):
        if rules.get("last_report_age_min") is not None:
            return (f"rules: no fresh report; +{rules.get('added', 0)} from "
                    f"the last report ({rules['last_report_age_min']} min "
                    f"old), nothing re-affirmed, counted or released")
        return "rules: no fresh report, nothing re-affirmed or released"
    line = (f"rules: +{rules['added']}/sup {rules['superseded']}"
            f"/re-affirmed {rules['reaffirmed']}")
    if held_by is not None:
        return line + f" ({held_by}: this run releases nothing)"
    if not releases:
        return line + " (manual run: releases nothing)"
    return (line + f"/missed {rules['missed']}"
            f"/released {rules['released']} ({RELEASING_PASS_MARK})")


def _releasing_pass_hold(now):
    """Why a run asked to release must not, or None: a releasing pass that
    read a fresh report finished within NIGHT_SPACING_HOURS. An unreadable
    run history holds too (the fail-safe side)."""
    from .knowledge_models import ConsolidationRun
    try:
        last = (ConsolidationRun.objects
                .filter(finished_at__gte=now - timedelta(
                    hours=NIGHT_SPACING_HOURS),
                        notes__contains=RELEASING_PASS_MARK)
                .order_by("-finished_at").values_list("finished_at",
                                                      flat=True).first())
    except Exception:  # noqa: BLE001 — unknown is held, never released
        return "the last releasing pass could not be read"
    if last is None:
        return None
    hours = int((now - last).total_seconds() // 3600)
    return f"a releasing pass ran {hours} h ago"


def consolidate_now(*, releases: bool = False) -> dict:
    """Run one consolidation cycle. Always returns a summary dict; on
    irrecoverable error the ConsolidationRun gets an `error` field stamped.

    `releases` is the scheduled 03:00 beat's alone (brain.tasks.
    run_consolidation): only that pass may loosen a rule_state node. The
    staff button runs without it (no PIN behind it, critique H3). A run
    asked to release within NIGHT_SPACING_HOURS of a releasing pass (the
    admin's "Run selected tasks", a second beat) releases nothing either.
    Every release written is announced, even when a later step raises."""
    from .knowledge_models import ConsolidationRun

    held_by = None
    if releases:
        held_by = _releasing_pass_hold(timezone.now())
        if held_by is not None:
            releases = False

    run = ConsolidationRun.objects.create()

    # Grading runs FIRST and outside the consolidation block. It used to
    # sit after five graph steps inside their shared `try`, so any one of
    # them raising meant not a single hypothesis was graded that night —
    # silently, and the market's own dashboard would look exactly as it
    # does on a healthy day. Grading owes nothing to the graph.
    resolution = {}
    try:
        from .hypotheses import resolve_due
        resolution = resolve_due()
    except Exception as e:  # pragma: no cover
        logger.warning("[consolidation] resolve_due failed: %s", e)
    n_resolved = (resolution.get("confirmed", 0)
                  + resolution.get("refuted", 0))

    # The rule pass writes into this dict as it goes: a release on disk is
    # on its list before any later step can raise.
    rules = _rule_counts()
    try:
        regime_added, regime_superseded = _consolidate_regime()
        theme_added, theme_superseded = _consolidate_theme_states()
        _consolidate_rule_states(releases=releases, out=rules)
        rule_added, rule_superseded = rules["added"], rules["superseded"]
        anomaly_added, anomaly_superseded = _consolidate_anomalies()
        pruned = _prune_observations()

        run.n_observations_pruned = pruned
        run.n_hypotheses_resolved = n_resolved
        run.n_nodes_added = (
            int(regime_added) + theme_added + rule_added + anomaly_added)
        run.n_nodes_superseded = (
            int(regime_superseded) + theme_superseded
            + rule_superseded + anomaly_superseded)

        # Phase-46 — critic dissent-rate sanity check (best-effort).
        critic_check = {}
        try:
            from .health import maybe_alert_critic_dissent_rate
            critic_check = maybe_alert_critic_dissent_rate()
        except Exception as e:  # pragma: no cover
            logger.warning("[consolidation] critic health check failed: %s", e)

        # Phase-57 — operator override-rate sanity check across tracked agents.
        try:
            from .health import maybe_alert_override_rates
            maybe_alert_override_rates()
        except Exception as e:  # pragma: no cover
            logger.warning("[consolidation] override health check failed: %s", e)

        run.notes = (
            f"regime: +{int(regime_added)}/sup {int(regime_superseded)}; "
            f"themes: +{theme_added}/sup {theme_superseded}; "
            f"{_rule_notes(rules, releases, held_by)}; "
            f"anomalies: +{anomaly_added}/sup {anomaly_superseded}; "
            f"pruned: {pruned} obs; "
            f"critic_dissent={critic_check.get('dissent_rate')}"
            f" ({critic_check.get('direction', 'n/a')}); "
            # The counters the run used to throw away. A resolver that
            # crashes deterministically reports `skipped` on every pass
            # forever, and with only confirmed+refuted recorded that
            # stuck row was invisible — the night grading breaks looks
            # identical to a quiet night.
            f"graded: {n_resolved} decided, "
            f"{resolution.get('unresolvable', 0)} unresolvable, "
            f"{resolution.get('deferred', 0)} deferred, "
            f"{resolution.get('skipped', 0)} skipped"
        )
    except Exception as e:
        logger.warning("[consolidation] failed: %s", e)
        run.error = str(e)[:1000]
        if rules.get("fresh"):
            # what the rule pass did before the failure, the releasing
            # mark included: a retry within the night releases nothing
            run.notes = _rule_notes(rules, releases, held_by)
    finally:
        run.finished_at = timezone.now()
        run.save()
    # After the run is saved: every release written is announced, whatever
    # step raised after it (an audit row and the one staff notice).
    _announce_releases(rules.get("released_rules") or [])

    return {
        "ok": not bool(run.error),
        "run_id": run.id,
        "n_nodes_added": run.n_nodes_added,
        "n_nodes_superseded": run.n_nodes_superseded,
        "n_hypotheses_resolved": run.n_hypotheses_resolved,
        "n_observations_pruned": run.n_observations_pruned,
        "notes": run.notes,
        "error": run.error,
    }
