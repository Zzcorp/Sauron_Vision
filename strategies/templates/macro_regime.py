"""Macro regime strategy template — state machine for risk-on/off allocation."""


REGIMES = {
    "risk_on":      {"risk_assets": 0.8, "defensive": 0.2, "cash": 0.0},
    "late_cycle":   {"risk_assets": 0.5, "defensive": 0.3, "cash": 0.2},
    "risk_off":     {"risk_assets": 0.2, "defensive": 0.4, "cash": 0.4},
    "recession":    {"risk_assets": 0.1, "defensive": 0.5, "cash": 0.4},
}


def detect_regime():
    """Detect current macro regime from a few key indicators.

    Tolerant: returns 'risk_on' as default if data sources are missing.
    Inputs (when available):
      - 2s10s yield curve slope (negative -> recession risk)
      - VIX level (>20 -> risk_off)
      - DXY trend
    """
    try:
        from market_data.models import MacroSeries
    except Exception:
        return "risk_on"

    slope = None
    vix = None
    try:
        ten = MacroSeries.objects.filter(series_id="DGS10").order_by("-date").first()
        two = MacroSeries.objects.filter(series_id="DGS2").order_by("-date").first()
        if ten and two:
            slope = float(ten.value) - float(two.value)
    except Exception:
        pass
    try:
        v = MacroSeries.objects.filter(series_id="VIXCLS").order_by("-date").first()
        if v:
            vix = float(v.value)
    except Exception:
        pass

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
