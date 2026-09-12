"""The Horizon page — /horizon/ (2026-09-12).

The latest OK 5-10 year view: its summary, the sectors with their tilts
and the calls each thesis was held to (with the grade the calibration
has given so far), the asset-class tilts with the factor the share
allocator derives from them, the run history with its cost, and the
agent's own grade record. Superusers get a Run now form that says what
it costs before they press it.

Every read is fenced, as on /shares/: a page that 500s because one
table is unreadable hides the view the operator came to read.
"""
import logging
from types import SimpleNamespace

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

logger = logging.getLogger(__name__)


def _call_rows(view):
    """[{symbol, direction, horizon_hours, confidence, why, state, reason,
    actual, move, deadline}] per sector key, the grade state read off
    AgentPrediction.

    Matched on (symbol, horizon_hours) — brain.horizon.call_key — never on
    the symbol alone: this map was symbol -> one prediction, so a symbol
    carrying a 6- and a 12-month call rendered BOTH with the registered
    call's state, and the unregistered one showed the other's deadline as
    its own (2026-09-12). A call the annotation marks unregistered, or one
    with no prediction row of its own, renders 'not registered' with the
    reason and no date.
    """
    from brain.horizon import call_drop_reason, call_key, view_predictions

    preds = {}
    try:
        preds = view_predictions(view)
    except Exception as e:  # noqa: BLE001
        logger.warning("[horizon page] predictions unreadable: %s", e)

    out = {}
    for sector in view.sectors or []:
        rows = []
        for c in sector.get("calls") or []:
            p = preds.get(call_key(c))
            row = {"symbol": c.get("symbol"), "direction": c.get("direction"),
                   "horizon_hours": c.get("horizon_hours"),
                   "horizon_months": round(float(c.get("horizon_hours") or 0)
                                           / 730.0),
                   "confidence": c.get("confidence"), "why": c.get("why"),
                   "state": "unregistered", "reason": "", "actual": "",
                   "move": None, "deadline": None}
            if c.get("registered") is False or p is None:
                # '' on a view written before the annotation existed: the
                # badge still renders, without a reason it cannot know.
                row["reason"] = call_drop_reason(c)
            else:
                row["deadline"] = p.expected_resolution_at
                if p.was_correct is True:
                    row["state"] = "right"
                elif p.was_correct is False:
                    row["state"] = "wrong"
                elif p.evaluated_at:
                    row["state"] = "ungraded"
                else:
                    row["state"] = "pending"
                row["actual"] = p.actual_value
                row["move"] = p.score
            rows.append(row)
        out[sector.get("key")] = rows
    return out


@login_required
def horizon_dashboard(request):
    from brain.horizon import HORIZON_UNIVERSE, SECTOR_NAMES, grade_record
    from brain.horizon_models import HorizonView
    from bot_program.share_allocator import (HORIZON_MAX_AGE_DAYS,
                                             HORIZON_TILT_STEP, horizon_for)

    view, stale, sectors, tilts, calls_by_sector = None, False, [], [], {}
    try:
        view = (HorizonView.objects.filter(status=HorizonView.STATUS_OK)
                .order_by("-created_at").first())
    except Exception as e:  # noqa: BLE001
        logger.warning("[horizon page] view unreadable: %s", e)
    if view is not None:
        stale = view.age_days > HORIZON_MAX_AGE_DAYS
        try:
            calls_by_sector = _call_rows(view)
        except Exception as e:  # noqa: BLE001
            logger.warning("[horizon page] calls unreadable: %s", e)
        for s in view.sectors or []:
            key = s.get("key")
            sectors.append({
                "key": key, "name": SECTOR_NAMES.get(key, key),
                "tilt": s.get("tilt"), "confidence": s.get("confidence"),
                "thesis_md": s.get("thesis_md") or "",
                "drivers": s.get("structural_drivers") or [],
                "risks": s.get("risks") or [],
                "catalysts": s.get("catalysts") or [],
                "calls": calls_by_sector.get(key, []),
            })
        for ac in sorted((view.asset_class_tilts or {}).keys()):
            slot = view.asset_class_tilts.get(ac) or {}
            try:
                hz = horizon_for(SimpleNamespace(asset_class=ac), view)
                factor = hz["factor"]
            except Exception:  # noqa: BLE001
                factor = None
            tilts.append({"asset_class": ac, "tilt": slot.get("tilt"),
                          "confidence": slot.get("confidence"),
                          "why": slot.get("why") or "", "factor": factor})

    history = []
    try:
        history = list(HorizonView.objects.all().order_by("-created_at")[:20])
    except Exception as e:  # noqa: BLE001
        logger.warning("[horizon page] history unreadable: %s", e)

    record = {"n_total": 0, "n_graded": 0, "n_correct": 0, "n_pending": 0,
              "brier": None, "trust": 1.0, "measured": False,
              "min_sample": 10}
    try:
        record = grade_record()
    except Exception as e:  # noqa: BLE001
        logger.warning("[horizon page] grade record unreadable: %s", e)

    context = {
        "page_id": "horizon",
        "view": view,
        "stale": stale,
        "max_age_days": HORIZON_MAX_AGE_DAYS,
        "tilt_step_pct": round(HORIZON_TILT_STEP * 100),
        "sectors": sectors,
        "tilts": tilts,
        "history": history,
        "record": record,
        "universe": HORIZON_UNIVERSE,
        "is_admin": request.user.is_superuser,
    }
    return render(request, "dashboard/horizon.html", context)
