"""Macro signal rules: yield curve, DXY, FRED surprises."""
from datetime import timedelta
from django.utils import timezone


class YieldCurveInversionRule:
    name = "yield_curve_inversion_flip"
    signal_type = "macro"

    def evaluate(self, instrument):
        """Detect 2s10s slope crossing zero.

        Reads from FRED-backed series if present (DGS10, DGS2). Tolerant
        to schema differences in market_data.MacroSeries.
        """
        try:
            from market_data.models import MacroSeries
        except Exception:
            return None
        try:
            ten = MacroSeries.objects.filter(series_id="DGS10").order_by("-date")[:5]
            two = MacroSeries.objects.filter(series_id="DGS2").order_by("-date")[:5]
        except Exception:
            return None
        if len(ten) < 2 or len(two) < 2:
            return None
        slope_now = float(ten[0].value) - float(two[0].value)
        slope_prev = float(ten[1].value) - float(two[1].value)
        if slope_prev < 0 and slope_now >= 0:
            return {
                "symbol": getattr(instrument, "symbol", "MACRO"),
                "rule": self.name,
                "direction": "SHORT",
                "score": 0.6,
                "headline": "MACRO · 2s10s yield curve un-inverted",
                "thesis": (
                    f"2s10s slope flipped from {slope_prev:+.2f} to {slope_now:+.2f}."
                    " Historically a recession-onset signal — risk-off bias."
                ),
            }
        return None


class DXYBreakoutRule:
    name = "dxy_breakout"
    signal_type = "macro"

    def evaluate(self, instrument):
        """DXY breaking 60-day high/low — signals USD strength regime change."""
        try:
            from signals.smc.dataframe import load_ohlcv
        except Exception:
            return None
        df = load_ohlcv("DXY", "1d", bars=80)
        if df is None or len(df) < 60:
            return None
        last = float(df["close"].iloc[-1])
        hi = float(df["high"].iloc[-60:-1].max())
        lo = float(df["low"].iloc[-60:-1].min())
        if last > hi:
            return {
                "symbol": "DXY",
                "rule": self.name,
                "direction": "LONG",
                "score": 0.55,
                "headline": "MACRO · DXY breaks 60d high",
                "thesis": "USD strength regime — historically bearish for risk assets.",
            }
        if last < lo:
            return {
                "symbol": "DXY",
                "rule": self.name,
                "direction": "SHORT",
                "score": 0.55,
                "headline": "MACRO · DXY breaks 60d low",
                "thesis": "USD weakness regime — historically bullish for risk assets.",
            }
        return None


def get_rules():
    return [YieldCurveInversionRule(), DXYBreakoutRule()]
