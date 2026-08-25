"""Macro regime strategy template — state machine for risk-on/off allocation."""


REGIMES = {
    "risk_on":      {"risk_assets": 0.8, "defensive": 0.2, "cash": 0.0},
    "late_cycle":   {"risk_assets": 0.5, "defensive": 0.3, "cash": 0.2},
    "risk_off":     {"risk_assets": 0.2, "defensive": 0.4, "cash": 0.4},
    "recession":    {"risk_assets": 0.1, "defensive": 0.5, "cash": 0.4},
}


def _latest(series_id):
    """Latest observed value for a FRED series as a float, or None.

    Reads MacroObservation. The previous version imported `MacroSeries`, a
    model that has never existed in market_data.models, and swallowed the
    ImportError — so detect_regime() returned the constant "risk_on" on every
    call since the file was written, and regime_allocation() has been handing
    out an 80% risk-asset tilt no matter what the curve or the VIX did. No
    try/except here: if the query cannot run the caller needs to hear about
    it rather than be told the world is calm.
    """
    from market_data.models import MacroObservation
    row = (MacroObservation.objects
           .filter(indicator__series_id=series_id)
           .order_by("-date")
           .values_list("value", flat=True)
           .first())
    return None if row is None else float(row)


def detect_regime():
    """Detect current macro regime from a few key indicators.

    Falls back to 'risk_on' when the series are simply absent — a fresh
    database has no FRED history, and that is a data gap, not a call.
    Inputs (when available):
      - 2s10s yield curve slope (negative -> recession risk)
      - VIX level (>25 -> risk_off)
    """
    ten = _latest("DGS10")
    two = _latest("DGS2")
    slope = None if (ten is None or two is None) else ten - two
    vix = _latest("VIXCLS")

    if slope is not None and slope < -0.5 and vix is not None and vix > 25:
        return "recession"
    if slope is not None and slope < 0:
        return "late_cycle"
    if vix is not None and vix > 25:
        return "risk_off"
    return "risk_on"


def regime_allocation():
    """Return suggested allocation dict for the current regime."""
    regime = detect_regime()
    return {
        "regime": regime,
        "allocation": REGIMES[regime],
        "thesis": f"Macro regime: {regime}. Tilt toward {'defensive' if regime in ('risk_off', 'recession') else 'risk assets'}.",
    }
