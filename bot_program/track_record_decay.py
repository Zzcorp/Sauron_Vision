"""Phase-26 track-record decay detection.

Compares each (user, rule_name, asset_class)'s last `RECENT_DAYS` of bot-trade
performance against the prior `BASELINE_DAYS` window. Flags a rule as
decaying when one or more of:

  • avg_r drop:      baseline avg_r − recent avg_r > AVG_R_DROP
  • win_rate drop:   baseline win_rate − recent win_rate > WR_DROP
  • gone negative:   recent avg_r < 0 while baseline avg_r > 0

Sample-size gates protect against noise from a few bad trades:
  • recent  needs ≥ MIN_RECENT_N graded trades
  • baseline needs ≥ MIN_BASELINE_N graded trades

Dedupe: when an open `RuleTrackRecordAlert` exists for the same key within
`COOLDOWN_DAYS`, no new alert is fired. When the rule recovers (recent ≥
baseline within tolerance), the most recent open alert is `resolved_at`-stamped.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from django.utils import timezone

logger = logging.getLogger(__name__)


# ── Tunables ──────────────────────────────────────────────────────────────

RECENT_DAYS = 7
BASELINE_DAYS = 30
MIN_RECENT_N = 5
MIN_BASELINE_N = 10
AVG_R_DROP = 0.5     # baseline 0.5R, recent -0.1R = drop 0.6R → flag
WR_DROP = 0.15       # 15 percentage points
COOLDOWN_DAYS = 7


# ── Per-user check ────────────────────────────────────────────────────────

def check_user_decay(user) -> dict:
    """Run the decay detector for one user.

    Returns: {alerts_fired: int, resolved: int, checked: int}
    """
    from .bot_grading import bot_performance_summary
    from .track_record_models import RuleTrackRecordAlert
    from .notifications import notify_track_record_decay

    now = timezone.now()
    baseline_since = now - timedelta(days=BASELINE_DAYS)
    recent_since = now - timedelta(days=RECENT_DAYS)

    recent_rows = bot_performance_summary(
        user=user, since=recent_since, min_n=1)
    baseline_rows = bot_performance_summary(
        user=user, since=baseline_since, min_n=1)

    recent_by_key = {(r["rule_name"], r["asset_class"]): r for r in recent_rows}
    baseline_by_key = {(r["rule_name"], r["asset_class"]): r for r in baseline_rows}

    alerts_fired = 0
    resolved = 0
    checked = 0

    # Walk every (rule, asset_class) seen in the baseline window — recent
    # might be empty (no fresh trades) which is itself worth knowing.
    for key, b in baseline_by_key.items():
        checked += 1
        rule_name, asset_class = key
        r = recent_by_key.get(key)

        # Need enough samples to draw any conclusion at all.
        if b["n"] < MIN_BASELINE_N:
            continue

        # If no recent trades, can't claim decay or recovery — skip.
        if r is None or r["n"] < MIN_RECENT_N:
            continue

        triggers = []
        avg_r_drop = b["avg_r"] - r["avg_r"]
        wr_drop = b["win_rate"] - r["win_rate"]
        if avg_r_drop > AVG_R_DROP:
            triggers.append("avg_r_drop")
        if wr_drop > WR_DROP:
            triggers.append("win_rate_drop")
        if r["avg_r"] < 0 and b["avg_r"] > 0:
            triggers.append("gone_negative")

        # Open alert in cooldown window — used both for dedupe and resolution.
        cooldown_cutoff = now - timedelta(days=COOLDOWN_DAYS)
        existing = (RuleTrackRecordAlert.objects
                    .filter(user=user, rule_name=rule_name,
                             asset_class=asset_class,
                             resolved_at__isnull=True)
                    .order_by("-detected_at").first())

        if triggers:
            # Decay detected — fire alert if outside cooldown / no open one.
            if existing and existing.detected_at >= cooldown_cutoff:
                continue  # still inside cooldown
            alert = RuleTrackRecordAlert.objects.create(
                user=user, rule_name=rule_name, asset_class=asset_class,
                recent_n=r["n"], recent_avg_r=r["avg_r"],
                recent_win_rate=r["win_rate"],
                baseline_n=b["n"], baseline_avg_r=b["avg_r"],
                baseline_win_rate=b["win_rate"],
                triggers=triggers,
            )
            try:
                from brain.observations import record_observation
                record_observation(
                    kind="rule_decayed",
                    payload={
                        "rule_name": rule_name, "asset_class": asset_class,
                        "triggers": triggers,
                        "recent_avg_r": r["avg_r"], "baseline_avg_r": b["avg_r"],
                        "recent_n": r["n"], "baseline_n": b["n"],
                    },
                    source="track_record_decay",
                )
            except Exception:
                pass
            ok = False
            try:
                ok = notify_track_record_decay(
                    user, rule_name=rule_name, asset_class=asset_class,
                    recent_avg_r=r["avg_r"], baseline_avg_r=b["avg_r"],
                    recent_n=r["n"], triggers=triggers,
                )
            except Exception as e:
                logger.warning("decay notification failed: %s", e)
            if ok:
                alert.alerted_at = timezone.now()
                alert.save(update_fields=["alerted_at"])
            alerts_fired += 1
        else:
            # No decay — if there's an open alert, mark it resolved.
            if existing is not None:
                existing.resolved_at = timezone.now()
                existing.save(update_fields=["resolved_at"])
                resolved += 1

    return {"alerts_fired": alerts_fired, "resolved": resolved,
            "checked": checked}


# ── All users — entry point for Celery ────────────────────────────────────

def check_all_users_decay() -> dict:
    """Walk every user with at least one graded bot trade in the baseline
    window. Returns aggregate summary.
    """
    from django.contrib.auth.models import User
    from .models import AssetBotTrade

    cutoff = timezone.now() - timedelta(days=BASELINE_DAYS)
    user_ids = sorted(set(
        AssetBotTrade.objects
        .filter(status="CLOSED", closed_at__gte=cutoff)
        .exclude(rule_name="")
        .values_list("config__user_id", flat=True)
    ))

    totals = {"users": 0, "alerts_fired": 0, "resolved": 0, "checked": 0}
    for uid in user_ids:
        try:
            u = User.objects.get(id=uid)
        except User.DoesNotExist:
            continue
        try:
            r = check_user_decay(u)
            totals["users"] += 1
            totals["alerts_fired"] += r.get("alerts_fired", 0)
            totals["resolved"] += r.get("resolved", 0)
            totals["checked"] += r.get("checked", 0)
        except Exception as e:
            logger.warning("decay check failed for user=%s: %s", uid, e)
    return totals
