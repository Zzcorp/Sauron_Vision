"""Real risk manager — vol-targeted sizing, exposure checks, correlation aware."""
import logging
import math

logger = logging.getLogger(__name__)


class RiskManager:
    """Portfolio risk management engine."""

    def calculate_position_size(self, portfolio, instrument, stop_distance, risk_pct=1.0):
        """Risk-based position size: risk_pct of equity per stop distance."""
        equity = float(getattr(portfolio, "current_value", 0) or 0)
        risk_amount = equity * (risk_pct / 100)
        if stop_distance <= 0:
            return 0
        return round(risk_amount / stop_distance, 6)

    def vol_targeted_size(self, portfolio, instrument_returns, target_vol=0.15):
        """Volatility-targeted sizing.

        size = (target_annual_vol / realized_annual_vol) * equity
        """
        equity = float(getattr(portfolio, "current_value", 0) or 0)
        if not instrument_returns or len(instrument_returns) < 10:
            return 0
        mean = sum(instrument_returns) / len(instrument_returns)
        var = sum((r - mean) ** 2 for r in instrument_returns) / len(instrument_returns)
        realized_vol = math.sqrt(var) * math.sqrt(365)
        if realized_vol <= 0:
            return 0
        return round(equity * (target_vol / realized_vol), 4)

    def check_exposure_limits(self, portfolio, proposed_position):
        """Check whether a proposed position would violate exposure limits.

        Returns (allowed, list_of_reasons).
        """
        reasons = []
        equity = float(getattr(portfolio, "current_value", 0) or 1)
        proposed_notional = float(proposed_position.get("notional", 0) or 0)

        if proposed_notional / equity > 0.25:
            reasons.append("single position exceeds 25% of equity")

        try:
            from portfolio.models import Position
            open_pos = Position.objects.filter(portfolio=portfolio, is_open=True)
            total_exposure = sum(float(p.market_value or 0) for p in open_pos)
            if (total_exposure + proposed_notional) / equity > 1.0:
                reasons.append("total exposure would exceed 100% of equity (no leverage budget)")
        except Exception:
            pass

        return (len(reasons) == 0, reasons)

    def calculate_correlation_impact(self, portfolio, new_instrument):
        """Average correlation of new_instrument with existing portfolio positions."""
        try:
            from portfolio.models import Position
            from signals.smc.dataframe import load_ohlcv
        except Exception:
            return 0.0
        try:
            open_pos = Position.objects.filter(portfolio=portfolio, is_open=True).select_related("instrument")
        except Exception:
            return 0.0
        if not open_pos:
            return 0.0

        new_df = load_ohlcv(getattr(new_instrument, "symbol", ""), "1d", bars=60)
        if new_df is None or len(new_df) < 30:
            return 0.0
        new_returns = new_df["close"].pct_change().dropna().tolist()

        correlations = []
        for p in open_pos:
            sym = getattr(p.instrument, "symbol", "")
            if not sym:
                continue
            df = load_ohlcv(sym, "1d", bars=60)
            if df is None or len(df) < 30:
                continue
            other_returns = df["close"].pct_change().dropna().tolist()
            n = min(len(new_returns), len(other_returns))
            if n < 10:
                continue
            a = new_returns[-n:]
            b = other_returns[-n:]
            ma = sum(a) / n
            mb = sum(b) / n
            cov = sum((a[i] - ma) * (b[i] - mb) for i in range(n)) / n
            va = sum((x - ma) ** 2 for x in a) / n
            vb = sum((x - mb) ** 2 for x in b) / n
            if va <= 0 or vb <= 0:
                continue
            corr = cov / math.sqrt(va * vb)
            correlations.append(corr)

        return round(sum(correlations) / len(correlations), 3) if correlations else 0.0
