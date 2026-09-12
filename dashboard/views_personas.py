"""The three trader personalities — /personas/.

Three columns side by side: what each personality is for, how long it
holds, the knobs that DIFFER between them (highlighted; a table the
operator has to diff by eye is a table nobody reads), the share band it
claims in the account allocator, the weight it puts on the 5-10 year
prior, and the window its record is graded over. Under each, the configs
wearing it with their live and paper record over that persona's OWN
window, and a plain sentence saying what that record means.

THE MATRIX (2026-09-12) sits above them: three personalities × six
regimes, each cell the factor that regime puts on that personality's
share band AND THE LANE THAT SPOKE — measured evidence, an unproven
prior, or neutral. Nobody knows yet which personality suits which tape,
so the platform does not pretend to: it says which cells it has learned
and which are still guesses, and the count under the table is how the
operator watches the guesses retire.

Read-only. The Apply form (superusers) posts to
views_admin_hq.hq_apply_persona, which asks the trading PIN when the
config is live — applying re-sizes real risk on the next entry.

Every read is fenced the way /shares/ is: a page that 500s because the
evidence ledger is mid-migration hides the one screen that explains why
a bot is trading the way it is.
"""
import logging

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

logger = logging.getLogger(__name__)


#: The venue the matrix is read on. LIVE, and never pooled with paper:
#: the whole point of the matrix is to size a LIVE book, and a paper fill
#: is charged a modelled half-spread with no resting stop at a broker.
#: `persona mix --venue paper` is where the other half is read.
MATRIX_VENUE = "live"


def _mix_matrix(user) -> tuple:
    """([row], mix, error) — THE MATRIX: three personalities × six regimes.

    Each cell is the factor the allocator would apply to that
    personality's share band in that regime, WITH THE LANE THAT SPOKE:

      measured  configs wearing it cleared the platform's sample floor
                while the platform RECORDED that regime. Evidence.
      prior     a small, unproven, deliberately-labelled guess. It is
                what the page exists to retire.
      neutral   1.0 — nothing measured and no prior says anything.

    The counts under the table are the point of the whole screen: the
    operator can see at a glance how many of the eighteen cells the
    platform has actually learned and how many are still guesswork. A
    matrix with no lane on it would read as eighteen findings.

    Fenced like every other read on this page: the presets above are
    exact whatever the brain or the trade table is doing, and a page that
    500s because the mix is mid-migration hides them.
    """
    blank = {"regime": "unknown", "confidence": 0.0, "age_minutes": None,
             "source": "", "venue": MATRIX_VENUE, "measured": 0,
             "n_cells": 0, "n_measured": 0, "n_prior": 0, "n_neutral": 0,
             "n_guesses": 0}
    try:
        from bot_program.persona_mix import (MAX_BAND_SHIFT_PCT, REGIMES,
                                             current_mix, mix_factor,
                                             shift_band)
        from bot_program.personas import PERSONA_KEYS, PERSONAS
        mix = dict(current_mix(user, venue=MATRIX_VENUE))
    except Exception as e:  # noqa: BLE001 — the presets render regardless
        logger.warning("[personas page] mix unreadable: %s", e)
        return [], blank, (f"The regime mix could not be read ({e}). The "
                           f"presets and the record above are unaffected — "
                           f"only the matrix is missing.")

    cells = mix.get("cells") or {}
    counts = {"measured": 0, "prior": 0, "neutral": 0}
    rows = []
    for key in PERSONA_KEYS:
        persona = PERSONAS[key]
        lo, hi = persona.share_floor_pct, persona.share_ceiling_pct
        row = {"key": key, "label": persona.label, "cells": []}
        for regime in REGIMES:
            f = mix_factor(key, regime, venue=MATRIX_VENUE,
                           record=(cells.get(key) or {}).get(regime))
            counts[f["lane"]] = counts.get(f["lane"], 0) + 1
            band = shift_band(lo, hi, f["factor"])
            row["cells"].append({
                "regime": regime, "factor": f["factor"], "lane": f["lane"],
                "n": f["n"], "reason": f["reason"],
                "measured": f["lane"] == "measured",
                "current": regime == mix.get("regime"),
                # What the factor actually DOES, in the units the operator
                # allocates in: a bare "1.09" says nothing about a band.
                "band": f"{band[0]:g}–{band[1]:g}%",
            })
        rows.append(row)

    total = sum(counts.values())
    mix.update({
        "n_cells": total,
        "n_measured": counts["measured"],
        "n_prior": counts["prior"],
        "n_neutral": counts["neutral"],
        # A neutral cell is a guess too — it is the guess that nothing
        # matters here — so anything not measured counts as unlearned.
        "n_guesses": total - counts["measured"],
        "max_shift": MAX_BAND_SHIFT_PCT,
        "venue": MATRIX_VENUE,
    })
    return rows, mix, ""


@login_required
def personas_dashboard(request):
    from bot_program.personas import (PERSONA_KEYS, PERSONAS,
                                      PERSONA_ASSET_CLASSES)

    rows, rows_error = [], ""
    try:
        from bot_program.evidence import persona_rows
        rows = persona_rows()
    except Exception as e:  # noqa: BLE001 — the page renders regardless
        logger.warning("[personas page] grade unreadable: %s", e)
        rows_error = (f"The persona grade could not be read ({e}). The "
                      f"presets below are still exact; only the record is "
                      f"missing.")
        rows = [{"key": k, "label": p.label, "purpose": p.purpose,
                 "holding": p.holding, "evidence_days": p.evidence_days,
                 "horizon_weight": p.horizon_weight,
                 "share_floor_pct": p.share_floor_pct,
                 "share_ceiling_pct": p.share_ceiling_pct,
                 "n_configs": 0, "names": [], "configs": [],
                 "live": {"n": 0, "r_sum": None, "win_rate": None,
                          "measured": False},
                 "paper": {"n": 0, "r_sum": None, "win_rate": None,
                           "measured": False},
                 "measured": False,
                 "sentence": "The record could not be read."}
                for k, p in PERSONAS.items()]

    knobs = []
    try:
        from bot_program.personas import knob_matrix
        knobs = knob_matrix()
    except Exception as e:  # noqa: BLE001
        logger.warning("[personas page] knob matrix unreadable: %s", e)

    # The share band drawn as a small bar: left offset and width as
    # percentages of the account, so the three bands are comparable by eye
    # on one axis rather than three numbers the reader has to subtract.
    by_key = {k["knob"]: k for k in knobs}
    for row in rows:
        lo = float(row["share_floor_pct"])
        hi = float(row["share_ceiling_pct"])
        row["band_left"] = round(lo, 2)
        row["band_width"] = round(max(0.0, hi - lo), 2)
        # Per-column knobs, so the template never has to index a dict by a
        # variable key — Django cannot, and the workaround is always a
        # custom filter nobody remembers exists.
        row["knobs"] = [
            {"knob": name, "kind": k["kind"], "differs": k["differs"],
             "value": k["values"].get(row["key"]),
             "why": k["why"].get(row["key"], "")}
            for name, k in by_key.items()
        ]

    # Configs that wear NO persona: named, because an operator asking
    # "which personality is this bot?" must not read an empty answer as
    # "swing" — today every one of them is the un-preset default.
    unworn, unworn_error = [], ""
    try:
        from bot_program.models import AssetBotConfig
        from bot_program.personas import persona_of
        unworn = [c for c in
                  AssetBotConfig.objects.select_related("user")
                  .order_by("asset_class", "name")
                  if not persona_of(c)]
    except Exception as e:  # noqa: BLE001
        logger.warning("[personas page] configs unreadable: %s", e)
        unworn_error = f"The config list could not be read ({e})."

    min_n = 10
    try:
        from bot_program.evidence import MIN_EVIDENCE_N
        min_n = MIN_EVIDENCE_N
    except Exception:  # noqa: BLE001
        pass

    matrix, mix, mix_error = _mix_matrix(request.user)

    return render(request, "dashboard/personas.html", {
        "page_id": "personas",
        "rows": rows,
        "rows_error": rows_error,
        "knobs": knobs,
        "keys": list(PERSONA_KEYS),
        "unworn": unworn,
        "unworn_error": unworn_error,
        "min_n": min_n,
        "asset_classes": ", ".join(PERSONA_ASSET_CLASSES),
        "is_admin": request.user.is_superuser,
        "matrix": matrix,
        "mix": mix,
        "mix_error": mix_error,
    })
