"""Macro signal rules: yield curve, DXY, FRED surprises."""
from datetime import timedelta
from django.utils import timezone


class YieldCurveInversionRule:
    name = "yield_curve_inversion_flip"
    signal_type = "macro"

    # The two legs of the 2s10s spread, as FRED spells them.
    TEN_YEAR = "DGS10"
    TWO_YEAR = "DGS2"

    def _last_values(self, series_id, n=5):
        """The n most recent observed values for a FRED series, newest first.

        Reads MacroObservation, NOT a `MacroSeries` model — there has never
        been one. The import of that name raised ImportError into a bare
        except that returned None, so this rule fired exactly zero times in
        the life of the codebase while looking perfectly healthy from the
        outside. There is no try/except here on purpose: if the query cannot
        run, SignalEngine.scan_instrument logs the rule by name at ERROR,
        which is how a broken macro rule is supposed to surface.
        """
        from market_data.models import MacroObservation
        return list(MacroObservation.objects
                    .filter(indicator__series_id=series_id)
                    .order_by("-date")
                    .values_list("value", flat=True)[:n])

    def evaluate(self, instrument):
        """Detect 2s10s slope crossing zero."""
        ten = self._last_values(self.TEN_YEAR)
        two = self._last_values(self.TWO_YEAR)
        if len(ten) < 2 or len(two) < 2:
            return None
        slope_now = float(ten[0]) - float(two[0])
        slope_prev = float(ten[1]) - float(two[1])
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
