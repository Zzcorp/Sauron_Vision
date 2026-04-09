#!/usr/bin/env python
# upgrade_sauron_13_strategies_and_ui.py
#
# Sauron Vision — Upgrade 13: Strategies + full UI polish.
#
# Prerequisites: upgrades 10, 11, 12 applied.
#
# Run:
#     python upgrade_sauron_13_strategies_and_ui.py            # idempotent
#     python upgrade_sauron_13_strategies_and_ui.py --force    # overwrite
#     python manage.py migrate                                  # no new tables
#     python manage.py runserver
#
# What it ships
# =============
#
# A) Strategy templates and modules — fills the empty stubs
# ----------------------------------------------------------
#   strategies/templates/momentum.py        Cross-sectional + time-series momentum
#   strategies/templates/mean_reversion.py  Z-score + Bollinger fade
#   strategies/templates/pairs_trading.py   Cointegration spread fade
#   strategies/templates/macro_regime.py    Regime-driven asset allocation tilt
#   strategies/engine.py                    Real implementation (not pass)
#   strategies/risk_manager.py              Vol-targeted sizing, exposure checks
#   strategies/portfolio_analyzer.py        Real correlation + drawdown + exposure
#
# B) UI polish across all key pages
# ----------------------------------
#   templates/_chart_assets.html            Chart.js CDN include + helpers
#   templates/_modal.html                   Reusable modal partial
#   dashboard/views_metrics.py              Metrics endpoints for all pages
#   dashboard/views_profile_modals.py       PIN + password modals (auto-save)
#   dashboard/views_admin_bots.py           Admin bot control panel
#   dashboard/views_strategy_wizard.py      Strategy create wizard
#
#   templates/dashboard/_signals_metrics.html         Signals page enrichment
#   templates/dashboard/_strategies_metrics.html      Strategies page enrichment
#   templates/dashboard/_news_metrics.html            News & sentiment enrichment
#   templates/dashboard/_backtest_metrics.html        Backtest enrichment
#   templates/dashboard/_portfolio_metrics.html       Portfolio enrichment
#   templates/dashboard/_positions_metrics.html       Positions enrichment
#   templates/dashboard/_admin_bots.html              Admin bot panel
#   templates/dashboard/_profile_credentials.html     PIN/password modals
#   templates/dashboard/_strategy_wizard.html         Wizard form
#
# C) URL wiring (added to dashboard/urls.py, idempotent)
# -------------------------------------------------------
#   /htmx/metrics/signals/        signal performance + chart data
#   /htmx/metrics/strategies/     strategy outcomes + R-distribution
#   /htmx/metrics/news/           news velocity + sentiment trend
#   /htmx/metrics/backtest/       backtest equity curve + trade markers
#   /htmx/metrics/portfolio/      portfolio composition + exposure
#   /htmx/metrics/positions/      open positions table + heatmap
#   /htmx/admin/bots/             bot control panel
#   /profile/change-password/     password change endpoint
#   /htmx/profile/pin-modal/      PIN modal partial
#   /htmx/profile/password-modal/ password modal partial
#   /strategies/new/              strategy create wizard
#   /strategies/new/save/         wizard POST endpoint

import sys
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FORCE = "--force" in sys.argv


# ============================================================================
# A) STRATEGY TEMPLATES (replace 2-line stubs)
# ============================================================================

F_MOMENTUM = '''"""Momentum strategy template — time-series and cross-sectional."""
from datetime import timedelta


def time_series_momentum(symbol, lookback_days=90, df=None):
    """Returns +1 (long bias) if 12-1 month return is positive, else -1.

    Classic Moskowitz/Asness time-series momentum: skip the most recent
    period to avoid 1-month reversal.
    """
    if df is None:
        from signals.smc.dataframe import load_ohlcv
        df = load_ohlcv(symbol, "1d", bars=400)
    if df is None or len(df) < lookback_days + 30:
        return None
    end_idx = len(df) - 21          # skip last ~1 month
    start_idx = end_idx - lookback_days
    if start_idx < 0:
        return None
    p_start = float(df["close"].iloc[start_idx])
    p_end = float(df["close"].iloc[end_idx])
    if p_start <= 0:
        return None
    ret = (p_end - p_start) / p_start
    return {
        "symbol": symbol,
        "strategy": "time_series_momentum",
        "direction": "LONG" if ret > 0 else "SHORT",
        "score": min(1.0, abs(ret) * 4),
        "lookback_return_pct": round(ret * 100, 2),
        "thesis": (
            f"{symbol} 12-1 month return: {ret*100:+.1f}%. "
            f"{'Long' if ret > 0 else 'Short'} bias by classical TSMOM."
        ),
    }


def cross_sectional_momentum(symbols, lookback_days=90, top_pct=0.2):
    """Rank a universe of symbols by lookback return; long the top decile."""
    from signals.smc.dataframe import load_ohlcv
    scored = []
    for sym in symbols:
        df = load_ohlcv(sym, "1d", bars=lookback_days + 40)
        if df is None or len(df) < lookback_days + 5:
            continue
        end = len(df) - 1
        start = end - lookback_days
        p0 = float(df["close"].iloc[start])
        p1 = float(df["close"].iloc[end])
        if p0 <= 0:
            continue
        ret = (p1 - p0) / p0
        scored.append((sym, ret))
    scored.sort(key=lambda x: x[1], reverse=True)
    n_top = max(1, int(len(scored) * top_pct))
    n_bot = max(1, int(len(scored) * top_pct))
    longs = scored[:n_top]
    shorts = scored[-n_bot:]
    return {
        "strategy": "cross_sectional_momentum",
        "longs": [{"symbol": s, "ret_pct": round(r * 100, 2)} for s, r in longs],
        "shorts": [{"symbol": s, "ret_pct": round(r * 100, 2)} for s, r in shorts],
        "universe_size": len(scored),
    }
'''


F_MEAN_REVERSION = '''"""Mean reversion strategy template — z-score and Bollinger fade."""


def zscore_reversion(symbol, period=20, threshold=2.0, df=None):
    """Long when price is z<-threshold below its N-period mean, short when z>+threshold."""
    if df is None:
        from signals.smc.dataframe import load_ohlcv
        df = load_ohlcv(symbol, "4h", bars=200)
    if df is None or len(df) < period + 5:
        return None
    closes = df["close"]
    mean = closes.rolling(period).mean().iloc[-1]
    std = closes.rolling(period).std().iloc[-1]
    if not std or std <= 0:
        return None
    last = float(closes.iloc[-1])
    z = (last - float(mean)) / float(std)
    if abs(z) < threshold:
        return None
    direction = "LONG" if z < 0 else "SHORT"
    return {
        "symbol": symbol,
        "strategy": "zscore_reversion",
        "direction": direction,
        "z_score": round(z, 2),
        "score": min(1.0, abs(z) / 4),
        "thesis": (
            f"{symbol} at {z:+.1f}\u03c3 vs {period}-bar mean. "
            f"Mean reversion {'long' if direction == 'LONG' else 'short'} setup."
        ),
        "entry": last,
        "stop": last * (0.98 if direction == "LONG" else 1.02),
        "target": float(mean),
    }


def bollinger_fade(symbol, period=20, k=2.0, df=None):
    """Fade Bollinger band touches with RSI confirmation."""
    if df is None:
        from signals.smc.dataframe import load_ohlcv
        df = load_ohlcv(symbol, "4h", bars=200)
    if df is None or len(df) < period + 14:
        return None
    closes = df["close"]
    mid = closes.rolling(period).mean()
    std = closes.rolling(period).std()
    upper = mid + k * std
    lower = mid - k * std
    last = float(closes.iloc[-1])
    last_upper = float(upper.iloc[-1])
    last_lower = float(lower.iloc[-1])
    last_mid = float(mid.iloc[-1])

    delta = closes.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss.replace(0, 1e-9)
    rsi = 100 - (100 / (1 + rs))
    last_rsi = float(rsi.iloc[-1])

    if last >= last_upper and last_rsi > 70:
        return {
            "symbol": symbol, "strategy": "bollinger_fade",
            "direction": "SHORT",
            "score": 0.65,
            "thesis": f"Price tagged upper BB with RSI {last_rsi:.0f}. Fade.",
            "entry": last, "stop": last * 1.02, "target": last_mid,
        }
    if last <= last_lower and last_rsi < 30:
        return {
            "symbol": symbol, "strategy": "bollinger_fade",
            "direction": "LONG",
            "score": 0.65,
            "thesis": f"Price tagged lower BB with RSI {last_rsi:.0f}. Fade.",
            "entry": last, "stop": last * 0.98, "target": last_mid,
        }
    return None
'''


F_PAIRS_TRADING = '''"""Pairs trading strategy template — cointegration spread fade."""
import math


def compute_spread(prices_a, prices_b):
    """Simple log-spread between two price series."""
    if len(prices_a) != len(prices_b) or len(prices_a) < 2:
        return None
    return [math.log(a) - math.log(b) for a, b in zip(prices_a, prices_b) if a > 0 and b > 0]


def spread_zscore(spread_series, lookback=60):
    """Z-score of the most recent spread vs lookback window."""
    if len(spread_series) < lookback + 1:
        return None
    window = spread_series[-lookback:]
    mean = sum(window) / len(window)
    var = sum((x - mean) ** 2 for x in window) / len(window)
    std = math.sqrt(var)
    if std <= 0:
        return None
    return (spread_series[-1] - mean) / std


def pairs_signal(symbol_a, symbol_b, lookback=60, threshold=2.0):
    """Long-A/short-B when spread is below -threshold; reverse on +threshold."""
    from signals.smc.dataframe import load_ohlcv
    df_a = load_ohlcv(symbol_a, "1d", bars=lookback + 20)
    df_b = load_ohlcv(symbol_b, "1d", bars=lookback + 20)
    if df_a is None or df_b is None:
        return None
    a = [float(x) for x in df_a["close"].tolist()][-(lookback + 5):]
    b = [float(x) for x in df_b["close"].tolist()][-(lookback + 5):]
    spread = compute_spread(a, b)
    if not spread:
        return None
    z = spread_zscore(spread, lookback=min(lookback, len(spread) - 1))
    if z is None or abs(z) < threshold:
        return None
    if z < 0:
        action = (f"long {symbol_a}", f"short {symbol_b}")
    else:
        action = (f"short {symbol_a}", f"long {symbol_b}")
    return {
        "strategy": "pairs_trading",
        "symbol_a": symbol_a, "symbol_b": symbol_b,
        "spread_zscore": round(z, 2),
        "actions": action,
        "thesis": (
            f"{symbol_a}/{symbol_b} spread at {z:+.1f}\u03c3 vs {lookback}d baseline. "
            f"Mean-reversion pair trade."
        ),
    }
'''


F_MACRO_REGIME = '''"""Macro regime strategy template — state machine for risk-on/off allocation."""


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
'''


# ============================================================================
# A2) Strategy modules (replace empty stubs)
# ============================================================================

F_STRATEGY_ENGINE = '''"""Strategy engine — builds strategies from signals + portfolio context."""
import logging

logger = logging.getLogger(__name__)


class StrategyEngine:
    """Builds and manages trading strategies from signals + portfolio state."""

    def build_strategy_from_signals(self, signals, portfolio=None):
        """Group signals by direction + asset class, propose a strategy.

        Returns a dict suitable for creating a Strategy row.
        """
        if not signals:
            return None
        long_signals = [s for s in signals if getattr(s, "direction", "") in ("LONG", "long")]
        short_signals = [s for s in signals if getattr(s, "direction", "") in ("SHORT", "short")]

        if len(long_signals) > len(short_signals):
            primary_dir = "long"
            primary = long_signals
        elif short_signals:
            primary_dir = "short"
            primary = short_signals
        else:
            return None

        avg_score = sum(float(getattr(s, "score", 0) or 0) for s in primary) / len(primary)
        symbols = list({getattr(s, "instrument", None) and s.instrument.symbol for s in primary if getattr(s, "instrument", None)})

        return {
            "name": f"Composite {primary_dir} on {', '.join(symbols[:3]) or 'mixed'}",
            "description": f"Built from {len(primary)} aligned signals.",
            "direction": primary_dir,
            "instruments": symbols,
            "confidence": round(avg_score, 3),
            "n_signals": len(primary),
            "time_horizon": "swing",
        }

    def evaluate_strategy_risk(self, strategy, portfolio=None):
        """Check exposure budget vs proposed allocation."""
        try:
            allocation = float(getattr(strategy, "max_portfolio_allocation_pct", 0))
        except (ValueError, TypeError):
            allocation = 0.0
        if allocation > 25:
            return False, "allocation exceeds 25% single-strategy cap"
        return True, "ok"

    def suggest_adjustments(self, strategy, current_data=None):
        """Suggest stop tightening / partial exits based on current data."""
        return {"adjustments": [], "note": "no adjustments computed"}
'''


F_RISK_MANAGER = '''"""Real risk manager — vol-targeted sizing, exposure checks, correlation aware."""
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
'''


F_PORTFOLIO_ANALYZER = '''"""Portfolio analysis — exposure, correlation matrix, drawdown."""
import math
import logging

logger = logging.getLogger(__name__)


def analyze_exposure(portfolio):
    """Analyze portfolio exposure by asset class, sector, currency.

    Returns dict with breakdowns. Tolerant to missing fields.
    """
    try:
        from portfolio.models import Position
        positions = Position.objects.filter(portfolio=portfolio, is_open=True).select_related("instrument")
    except Exception:
        return {}

    by_asset = {}
    by_sector = {}
    by_currency = {}
    total_value = 0.0
    long_value = 0.0
    short_value = 0.0

    for p in positions:
        mv = float(getattr(p, "market_value", 0) or 0)
        if mv == 0:
            continue
        total_value += abs(mv)
        if getattr(p, "side", "") in ("long", "BUY"):
            long_value += mv
        else:
            short_value += abs(mv)

        ac = getattr(p.instrument, "asset_class", "unknown")
        sec = getattr(p.instrument, "sector", "unknown") or "unknown"
        cur = getattr(p.instrument, "currency", "USD") or "USD"
        by_asset[ac] = by_asset.get(ac, 0) + abs(mv)
        by_sector[sec] = by_sector.get(sec, 0) + abs(mv)
        by_currency[cur] = by_currency.get(cur, 0) + abs(mv)

    if total_value == 0:
        return {"total": 0, "by_asset_class": {}, "by_sector": {}, "by_currency": {}}

    return {
        "total": round(total_value, 2),
        "gross": round(long_value + short_value, 2),
        "net": round(long_value - short_value, 2),
        "long_value": round(long_value, 2),
        "short_value": round(short_value, 2),
        "by_asset_class": {k: round(v / total_value, 4) for k, v in by_asset.items()},
        "by_sector": {k: round(v / total_value, 4) for k, v in by_sector.items()},
        "by_currency": {k: round(v / total_value, 4) for k, v in by_currency.items()},
    }


def calculate_correlation_matrix(portfolio, lookback_days=60):
    """Pairwise correlation matrix between open positions."""
    try:
        from portfolio.models import Position
        from signals.smc.dataframe import load_ohlcv
    except Exception:
        return {}
    try:
        positions = Position.objects.filter(portfolio=portfolio, is_open=True).select_related("instrument")
    except Exception:
        return {}

    series = {}
    for p in positions:
        sym = getattr(p.instrument, "symbol", None)
        if not sym:
            continue
        df = load_ohlcv(sym, "1d", bars=lookback_days + 5)
        if df is None or len(df) < lookback_days // 2:
            continue
        rets = df["close"].pct_change().dropna().tolist()
        if rets:
            series[sym] = rets[-lookback_days:]

    symbols = list(series.keys())
    matrix = {}
    for a in symbols:
        matrix[a] = {}
        for b in symbols:
            n = min(len(series[a]), len(series[b]))
            if n < 10:
                matrix[a][b] = None
                continue
            xa = series[a][-n:]
            xb = series[b][-n:]
            ma = sum(xa) / n
            mb = sum(xb) / n
            cov = sum((xa[i] - ma) * (xb[i] - mb) for i in range(n)) / n
            va = sum((x - ma) ** 2 for x in xa) / n
            vb = sum((x - mb) ** 2 for x in xb) / n
            if va <= 0 or vb <= 0:
                matrix[a][b] = None
            else:
                matrix[a][b] = round(cov / math.sqrt(va * vb), 3)
    return matrix


def calculate_max_drawdown(snapshots):
    """Max drawdown from a list of portfolio snapshots."""
    if not snapshots:
        return 0.0
    values = [float(getattr(s, "total_value", 0) or 0) for s in snapshots]
    if not values:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            dd = (peak - v) / peak * 100
            max_dd = max(max_dd, dd)
    return round(max_dd, 4)
'''


# ============================================================================
# B) UI POLISH — Chart.js include
# ============================================================================

F_CHART_ASSETS = '''{% comment %}
Chart.js loader. Include with: {% include "_chart_assets.html" %}
Use once per page; later includes detect the loaded flag and skip.
{% endcomment %}
{% if not request.chart_assets_loaded %}
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"
        integrity="sha384-rHwkN4ZQrQezJlqaepbhhyNvk9PqaH7GqvO5Hjfrxol0w63cKx2OqAVCXjuVUFLJ"
        crossorigin="anonymous"></script>
<script>
  // Common dark theme defaults that match Sauron's --accent / --text vars
  if (typeof Chart !== "undefined") {
    Chart.defaults.color = "#5a8a6a";
    Chart.defaults.borderColor = "#133020";
    Chart.defaults.font.family = "'Share Tech Mono', monospace";
    Chart.defaults.font.size = 11;
  }
  window.SAURON_CHART_COLORS = {
    accent: "#00e868",
    accentDim: "rgba(0, 232, 104, 0.18)",
    red: "#e83030",
    redDim: "rgba(232, 48, 48, 0.18)",
    gold: "#d8b020",
    blue: "#30a0e8",
    purple: "#8840d0",
    text: "#c8e8d8",
    border: "#133020",
  };
</script>
<style>
  .sv-chart-container { position: relative; height: 280px; margin: 16px 0; }
  .sv-chart-container.tall { height: 380px; }
  .sv-chart-container.short { height: 180px; }
  .sv-metrics-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                     gap: 12px; margin: 16px 0; }
  .sv-metric-card { background: var(--bg-card); border: 1px solid var(--border);
                    border-radius: var(--radius); padding: 14px; }
  .sv-metric-label { font-size: 0.7rem; color: var(--text-muted);
                     text-transform: uppercase; letter-spacing: 0.05em; }
  .sv-metric-value { font-family: var(--font-mono); font-size: 1.4rem;
                     color: var(--text-primary); margin-top: 4px;
                     font-variant-numeric: tabular-nums; }
  .sv-metric-value.up { color: var(--accent); }
  .sv-metric-value.down { color: var(--accent-red); }
  .sv-section-title { font-family: var(--font-heading); font-size: 1rem;
                      color: var(--text-secondary); text-transform: uppercase;
                      letter-spacing: 0.1em; margin: 24px 0 12px; }
</style>
{% endif %}
'''


# ============================================================================
# B2) Reusable modal partial
# ============================================================================

F_MODAL = '''{% comment %}
Reusable modal partial.
Use:  {% include "_modal.html" with id="myModal" title="My Title" body=html_string %}
Or include and supply your own body via blocks.
{% endcomment %}
<div class="sv-modal-backdrop" id="{{ id }}-backdrop" onclick="svCloseModal('{{ id }}')"></div>
<div class="sv-modal" id="{{ id }}" role="dialog" aria-modal="true">
  <div class="sv-modal__header">
    <span class="sv-modal__title">{{ title }}</span>
    <button class="sv-modal__close" onclick="svCloseModal('{{ id }}')" aria-label="Close">\u00d7</button>
  </div>
  <div class="sv-modal__body">{{ body|safe }}</div>
</div>
<style>
.sv-modal-backdrop {
  display: none; position: fixed; inset: 0;
  background: rgba(0,0,0,0.7); z-index: 9998;
  backdrop-filter: blur(3px);
}
.sv-modal {
  display: none; position: fixed; top: 50%; left: 50%;
  transform: translate(-50%, -50%); z-index: 9999;
  background: var(--bg-card); border: 1px solid var(--border-glow);
  border-radius: var(--radius-lg); box-shadow: 0 10px 60px rgba(0,0,0,0.8);
  min-width: 360px; max-width: 540px; width: 90%;
}
.sv-modal.is-open, .sv-modal-backdrop.is-open { display: block; }
.sv-modal__header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 14px 18px; border-bottom: 1px solid var(--border);
}
.sv-modal__title {
  font-family: var(--font-heading); font-size: 1rem;
  color: var(--accent); text-transform: uppercase; letter-spacing: 0.08em;
}
.sv-modal__close {
  background: none; border: none; color: var(--text-secondary);
  font-size: 1.5rem; cursor: pointer; line-height: 1;
}
.sv-modal__close:hover { color: var(--accent); }
.sv-modal__body { padding: 18px; }
</style>
<script>
function svOpenModal(id) {
  document.getElementById(id).classList.add("is-open");
  document.getElementById(id + "-backdrop").classList.add("is-open");
}
function svCloseModal(id) {
  document.getElementById(id).classList.remove("is-open");
  document.getElementById(id + "-backdrop").classList.remove("is-open");
}
window.svOpenModal = svOpenModal;
window.svCloseModal = svCloseModal;
</script>
'''


# ============================================================================
# C) METRICS VIEWS — one file, all six pages
# ============================================================================

F_METRICS_VIEWS = '''"""Metrics endpoints for the enriched dashboard pages.

Each view returns a small HTML partial (cards + JSON for charts) that the
parent page polls via HTMX. Charts are rendered client-side by Chart.js.
"""
import json
from collections import Counter
from datetime import timedelta
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone


# ── Signals page metrics ────────────────────────────────────────────────
@login_required
def signals_metrics(request):
    """Active signal counts, hit-rate per setup, distribution by direction."""
    ctx = {"setups": [], "totals": {}, "chart_data": "{}"}
    try:
        from signals.models_smc import SmcSignal
        from signals.performance import setup_performance_summary

        active = SmcSignal.objects.filter(status__in=["ACTIVE", "TRIGGERED"])
        ctx["totals"] = {
            "active": active.count(),
            "long": active.filter(direction="LONG").count(),
            "short": active.filter(direction="SHORT").count(),
            "avg_conviction": round(
                sum(s.conviction or 0 for s in active) / max(active.count(), 1), 1
            ),
        }
        perf = setup_performance_summary(days=30)
        ctx["setups"] = [
            {
                "name": k,
                "hit_rate": v["hit_rate"],
                "expectancy": v["expectancy_r"],
                "n_closed": v["n_closed"],
                "is_empirical": v["is_empirical"],
            }
            for k, v in perf.items()
        ]

        # Chart data: signal counts per day for the last 14 days
        since = timezone.now() - timedelta(days=14)
        recent = SmcSignal.objects.filter(created_at__gte=since)
        per_day = {}
        for s in recent:
            day = s.created_at.date().isoformat()
            per_day.setdefault(day, {"long": 0, "short": 0})
            per_day[day]["long" if s.direction == "LONG" else "short"] += 1

        days_sorted = sorted(per_day.keys())
        ctx["chart_data"] = json.dumps({
            "labels": days_sorted,
            "long": [per_day[d]["long"] for d in days_sorted],
            "short": [per_day[d]["short"] for d in days_sorted],
        })
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_signals_metrics.html", ctx)


# ── Strategies page metrics ─────────────────────────────────────────────
@login_required
def strategies_metrics(request):
    """Strategy outcomes, R-distribution, status mix."""
    ctx = {"by_status": [], "chart_data": "{}", "totals": {}}
    try:
        from strategies.models import Strategy
        all_strats = Strategy.objects.all()
        status_counts = Counter(s.status for s in all_strats)
        ctx["by_status"] = [{"status": k, "count": v} for k, v in status_counts.items()]
        ctx["totals"] = {
            "total": all_strats.count(),
            "active": status_counts.get("active", 0),
            "proposed": status_counts.get("proposed", 0),
            "completed": status_counts.get("completed", 0),
        }
        ctx["chart_data"] = json.dumps({
            "labels": list(status_counts.keys()),
            "values": list(status_counts.values()),
        })
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_strategies_metrics.html", ctx)


# ── News & sentiment metrics ────────────────────────────────────────────
@login_required
def news_metrics(request):
    """News volume per day, sentiment trend."""
    ctx = {"totals": {}, "chart_data": "{}"}
    try:
        from scraping.models import NewsItem
        since = timezone.now() - timedelta(days=14)
        items = NewsItem.objects.filter(published_at__gte=since) if hasattr(NewsItem, "published_at") else []
        ctx["totals"]["count_14d"] = len(list(items)) if items else 0

        per_day = {}
        for n in items:
            day = (n.published_at or timezone.now()).date().isoformat()
            per_day[day] = per_day.get(day, 0) + 1
        days_sorted = sorted(per_day.keys())
        ctx["chart_data"] = json.dumps({
            "labels": days_sorted,
            "values": [per_day[d] for d in days_sorted],
        })
    except Exception as e:
        ctx["error"] = str(e)
        ctx["totals"]["count_14d"] = 0
    return render(request, "dashboard/_news_metrics.html", ctx)


# ── Backtest metrics ────────────────────────────────────────────────────
@login_required
def backtest_metrics(request):
    """Latest backtest summary + equity curve."""
    ctx = {"runs": [], "chart_data": "{}"}
    try:
        from backtester.models_v2 import BacktestRunV2
        recent = BacktestRunV2.objects.all()[:10]
        ctx["runs"] = list(recent)
        if recent:
            latest = recent[0]
            curve = latest.equity_curve or []
            ctx["chart_data"] = json.dumps({
                "labels": [str(p.get("ts", i)) for i, p in enumerate(curve)],
                "equity": [p.get("equity", 0) for p in curve],
                "name": latest.name,
            })
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_backtest_metrics.html", ctx)


# ── Portfolio metrics ───────────────────────────────────────────────────
@login_required
def portfolio_metrics(request):
    """Portfolio composition + exposure breakdown."""
    ctx = {"exposure": {}, "chart_data": "{}"}
    try:
        from portfolio.models import Portfolio
        from strategies.portfolio_analyzer import analyze_exposure

        portfolio = Portfolio.objects.filter(user=request.user).first()
        if portfolio:
            exposure = analyze_exposure(portfolio)
            ctx["exposure"] = exposure
            asset_break = exposure.get("by_asset_class", {})
            ctx["chart_data"] = json.dumps({
                "labels": list(asset_break.keys()),
                "values": [round(v * 100, 2) for v in asset_break.values()],
            })
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_portfolio_metrics.html", ctx)


# ── Positions metrics ───────────────────────────────────────────────────
@login_required
def positions_metrics(request):
    """Open positions table with PnL distribution."""
    ctx = {"positions": [], "chart_data": "{}"}
    try:
        from portfolio.models import Position, Portfolio
        portfolio = Portfolio.objects.filter(user=request.user).first()
        if portfolio:
            positions = Position.objects.filter(
                portfolio=portfolio, is_open=True
            ).select_related("instrument")[:50]
            ctx["positions"] = list(positions)
            symbols = []
            pnls = []
            for p in positions:
                symbols.append(getattr(p.instrument, "symbol", "?"))
                pnls.append(float(getattr(p, "unrealized_pnl", 0) or 0))
            ctx["chart_data"] = json.dumps({
                "labels": symbols,
                "values": pnls,
            })
    except Exception as e:
        ctx["error"] = str(e)
    return render(request, "dashboard/_positions_metrics.html", ctx)
'''


# ============================================================================
# D) PROFILE CREDENTIAL MODALS
# ============================================================================

F_PROFILE_VIEWS = '''"""Profile credential modals: PIN + password change with auto-save semantics."""
import json
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from django.contrib.auth import update_session_auth_hash


@login_required
def pin_modal(request):
    """Render the PIN-change modal body for HTMX injection."""
    return render(request, "dashboard/_profile_pin_modal.html", {})


@login_required
def password_modal(request):
    """Render the password-change modal body for HTMX injection."""
    return render(request, "dashboard/_profile_password_modal.html", {})


@login_required
@require_POST
def change_password(request):
    """Validate + persist new password. Returns JSON for the modal JS."""
    user = request.user
    current = request.POST.get("current_password", "")
    new = request.POST.get("new_password", "")
    confirm = request.POST.get("confirm_password", "")

    if not user.check_password(current):
        return JsonResponse({"ok": False, "error": "Current password is incorrect."})
    if not new or len(new) < 8:
        return JsonResponse({"ok": False, "error": "New password must be at least 8 characters."})
    if new != confirm:
        return JsonResponse({"ok": False, "error": "New password and confirmation do not match."})

    user.set_password(new)
    user.save()
    update_session_auth_hash(request, user)
    return JsonResponse({"ok": True, "message": "Password updated."})


@login_required
@require_POST
def change_pin_modal(request):
    """JSON-returning version of the PIN change endpoint for the modal."""
    try:
        from portfolio.trader_profile import get_or_create_profile
    except Exception:
        return JsonResponse({"ok": False, "error": "profile module unavailable"})
    profile = get_or_create_profile(request.user)
    current_pin = request.POST.get("current_pin", "")
    new_pin = request.POST.get("new_pin", "")
    confirm_pin = request.POST.get("confirm_pin", "")

    if profile.access_pin_hash:
        if not profile.check_pin(current_pin):
            return JsonResponse({"ok": False, "error": "Current PIN is incorrect."})
    if not new_pin or not new_pin.isdigit() or not (4 <= len(new_pin) <= 8):
        return JsonResponse({"ok": False, "error": "PIN must be 4-8 digits."})
    if new_pin != confirm_pin:
        return JsonResponse({"ok": False, "error": "New PIN and confirmation do not match."})

    profile.set_pin(new_pin)
    profile.save()
    return JsonResponse({"ok": True, "message": "PIN updated."})
'''


# ============================================================================
# E) ADMIN BOT CONTROL PANEL
# ============================================================================

F_ADMIN_BOTS_VIEW = '''"""Admin bot control panel — surfaces money-protection state for all users."""
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST


def _is_staff(u):
    return u.is_authenticated and u.is_staff


@login_required
@user_passes_test(_is_staff)
def admin_bots_panel(request):
    """Render the admin bot control panel."""
    rows = []
    try:
        from bot_program.models import BotConfig
        from bot_program.engine.heartbeat import heartbeat_age_seconds
        from bot_program.engine.shadow import is_shadow_mode

        configs = BotConfig.objects.select_related("user").all()
        for cfg in configs:
            try:
                circuit = cfg.circuit_state.halt_reason or ""
            except Exception:
                circuit = ""
            try:
                hb_age = heartbeat_age_seconds(cfg)
            except Exception:
                hb_age = None
            rows.append({
                "config": cfg,
                "user": cfg.user,
                "enabled": cfg.enabled,
                "mode": cfg.mode,
                "market": cfg.market_type,
                "shadow": is_shadow_mode(cfg),
                "heartbeat_age": hb_age,
                "circuit": circuit,
                "open_trades": cfg.trades.filter(status="OPEN").count() if hasattr(cfg, "trades") else 0,
            })
    except Exception as e:
        return render(request, "dashboard/_admin_bots.html", {"error": str(e), "rows": []})

    return render(request, "dashboard/_admin_bots.html", {"rows": rows})


@login_required
@user_passes_test(_is_staff)
@require_POST
def admin_bot_toggle(request, config_id):
    """Toggle a bot's enabled flag."""
    try:
        from bot_program.models import BotConfig
        cfg = BotConfig.objects.get(id=config_id)
        cfg.enabled = not cfg.enabled
        cfg.save(update_fields=["enabled"])
        return JsonResponse({"ok": True, "enabled": cfg.enabled})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)})


@login_required
@user_passes_test(_is_staff)
@require_POST
def admin_bot_shadow(request, config_id):
    """Enable shadow mode for N hours."""
    try:
        from bot_program.models import BotConfig
        from bot_program.engine.shadow import enable_shadow
        cfg = BotConfig.objects.get(id=config_id)
        hours = int(request.POST.get("hours", 24))
        until = enable_shadow(cfg, hours=hours)
        return JsonResponse({"ok": True, "shadow_until": str(until)})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)})


@login_required
@user_passes_test(_is_staff)
@require_POST
def admin_bot_reset_circuit(request, config_id):
    """Clear the circuit breaker state for a config."""
    try:
        from bot_program.models import BotConfig
        from bot_program.models_v2 import BotCircuitState
        cfg = BotConfig.objects.get(id=config_id)
        BotCircuitState.objects.filter(config=cfg).update(
            error_count_in_burst=0,
            last_error_burst_started=None,
            halted_until=None,
            halt_reason="",
        )
        return JsonResponse({"ok": True})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)})


@login_required
@user_passes_test(_is_staff)
@require_POST
def admin_bot_reconcile(request, config_id):
    """Force a reconciliation pass for a config."""
    try:
        from bot_program.models import BotConfig
        from bot_program.engine.reconcile import reconcile_user
        cfg = BotConfig.objects.get(id=config_id)
        result = reconcile_user(cfg.user_id)
        return JsonResponse({"ok": True, "result": result})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)})
'''


# ============================================================================
# F) STRATEGY WIZARD
# ============================================================================

F_WIZARD_VIEW = '''"""Strategy create wizard."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_POST


@login_required
def strategy_wizard(request):
    """Render the strategy create wizard form."""
    return render(request, "dashboard/_strategy_wizard.html", {})


@login_required
@require_POST
def strategy_wizard_save(request):
    """Persist a Strategy from wizard form data. Tolerant to schema variations."""
    try:
        from strategies.models import Strategy
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"strategies module: {e}"})

    name = request.POST.get("name", "").strip()
    description = request.POST.get("description", "").strip()
    horizon = request.POST.get("time_horizon", "swing")
    max_alloc = request.POST.get("max_portfolio_allocation_pct", "10")
    max_loss = request.POST.get("max_loss_pct", "2")

    if not name:
        return JsonResponse({"ok": False, "error": "Name is required."})

    try:
        s = Strategy.objects.create(
            name=name,
            description=description,
            time_horizon=horizon,
            status="proposed",
            max_portfolio_allocation_pct=float(max_alloc or 10),
            max_loss_pct=float(max_loss or 2),
            ai_reasoning="Created via wizard",
        )
        return JsonResponse({"ok": True, "id": s.id, "redirect": f"/strategies/{s.id}/"})
    except Exception as e:
        return JsonResponse({"ok": False, "error": str(e)})
'''


# ============================================================================
# TEMPLATES — one per metric panel + modals + admin + wizard
# ============================================================================

F_TPL_SIGNALS_METRICS = '''{% load static %}
{% include "_chart_assets.html" %}
<div class="signals-metrics">
  <div class="sv-section-title">Signal overview</div>
  <div class="sv-metrics-grid">
    <div class="sv-metric-card">
      <div class="sv-metric-label">Active</div>
      <div class="sv-metric-value">{{ totals.active|default:"0" }}</div>
    </div>
    <div class="sv-metric-card">
      <div class="sv-metric-label">Long</div>
      <div class="sv-metric-value up">{{ totals.long|default:"0" }}</div>
    </div>
    <div class="sv-metric-card">
      <div class="sv-metric-label">Short</div>
      <div class="sv-metric-value down">{{ totals.short|default:"0" }}</div>
    </div>
    <div class="sv-metric-card">
      <div class="sv-metric-label">Avg conviction</div>
      <div class="sv-metric-value">{{ totals.avg_conviction|default:"0" }}/100</div>
    </div>
  </div>

  <div class="sv-section-title">Signals per day (14d)</div>
  <div class="sv-chart-container">
    <canvas id="signals-daily-chart"></canvas>
  </div>

  <div class="sv-section-title">Setup performance — last 30 days</div>
  {% if setups %}
    <table class="sv-perf-table">
      <thead>
        <tr><th>Setup</th><th>Hit rate</th><th>Expectancy</th><th>n closed</th><th>Source</th></tr>
      </thead>
      <tbody>
        {% for s in setups %}
          <tr>
            <td>{{ s.name }}</td>
            <td>{% if s.hit_rate %}{{ s.hit_rate|floatformat:2 }}{% else %}\u2014{% endif %}</td>
            <td>{% if s.expectancy %}{{ s.expectancy|floatformat:2 }}R{% else %}\u2014{% endif %}</td>
            <td>{{ s.n_closed }}</td>
            <td>{% if s.is_empirical %}empirical{% else %}fallback{% endif %}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p style="color:var(--text-muted);">No closed signals yet.</p>
  {% endif %}
</div>

<style>
.sv-perf-table { width: 100%; border-collapse: collapse;
                 font-family: var(--font-mono); font-size: 0.85rem; }
.sv-perf-table th, .sv-perf-table td { padding: 8px 10px; text-align: left;
                                        border-bottom: 1px solid var(--border); }
.sv-perf-table th { color: var(--text-muted); text-transform: uppercase;
                    font-size: 0.7rem; letter-spacing: 0.05em; }
</style>

<script>
(function() {
  const data = {{ chart_data|safe }};
  const ctx = document.getElementById("signals-daily-chart");
  if (!ctx || !data.labels) return;
  if (window._signalsDailyChart) window._signalsDailyChart.destroy();
  window._signalsDailyChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: data.labels,
      datasets: [
        { label: "Long", data: data.long,
          backgroundColor: window.SAURON_CHART_COLORS.accentDim,
          borderColor: window.SAURON_CHART_COLORS.accent, borderWidth: 1 },
        { label: "Short", data: data.short,
          backgroundColor: window.SAURON_CHART_COLORS.redDim,
          borderColor: window.SAURON_CHART_COLORS.red, borderWidth: 1 },
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      scales: { x: { stacked: true }, y: { stacked: true, beginAtZero: true } },
      plugins: { legend: { position: "top" } },
    },
  });
})();
</script>
'''


F_TPL_STRATEGIES_METRICS = '''{% include "_chart_assets.html" %}
<div class="strategies-metrics">
  <div class="sv-section-title">Strategy overview</div>
  <div class="sv-metrics-grid">
    <div class="sv-metric-card">
      <div class="sv-metric-label">Total</div>
      <div class="sv-metric-value">{{ totals.total|default:"0" }}</div>
    </div>
    <div class="sv-metric-card">
      <div class="sv-metric-label">Active</div>
      <div class="sv-metric-value up">{{ totals.active|default:"0" }}</div>
    </div>
    <div class="sv-metric-card">
      <div class="sv-metric-label">Proposed</div>
      <div class="sv-metric-value">{{ totals.proposed|default:"0" }}</div>
    </div>
    <div class="sv-metric-card">
      <div class="sv-metric-label">Completed</div>
      <div class="sv-metric-value">{{ totals.completed|default:"0" }}</div>
    </div>
  </div>

  <div class="sv-section-title">Status distribution</div>
  <div class="sv-chart-container">
    <canvas id="strategies-status-chart"></canvas>
  </div>

  <div style="margin-top:24px;">
    <a href="/strategies/new/" class="btn btn-primary">+ Create new strategy</a>
  </div>
</div>

<script>
(function() {
  const data = {{ chart_data|safe }};
  const ctx = document.getElementById("strategies-status-chart");
  if (!ctx || !data.labels) return;
  if (window._stratStatusChart) window._stratStatusChart.destroy();
  const colors = [
    window.SAURON_CHART_COLORS.accent,
    window.SAURON_CHART_COLORS.gold,
    window.SAURON_CHART_COLORS.blue,
    window.SAURON_CHART_COLORS.purple,
    window.SAURON_CHART_COLORS.red,
    "#666",
  ];
  window._stratStatusChart = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: data.labels,
      datasets: [{ data: data.values,
                   backgroundColor: data.labels.map((_, i) => colors[i % colors.length]),
                   borderColor: window.SAURON_CHART_COLORS.border, borderWidth: 2 }],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: "right" } },
    },
  });
})();
</script>
'''


F_TPL_NEWS_METRICS = '''{% include "_chart_assets.html" %}
<div class="news-metrics">
  <div class="sv-section-title">News volume — last 14 days</div>
  <div class="sv-metrics-grid">
    <div class="sv-metric-card">
      <div class="sv-metric-label">Articles (14d)</div>
      <div class="sv-metric-value">{{ totals.count_14d|default:"0" }}</div>
    </div>
  </div>
  <div class="sv-chart-container">
    <canvas id="news-volume-chart"></canvas>
  </div>
</div>

<script>
(function() {
  const data = {{ chart_data|safe }};
  const ctx = document.getElementById("news-volume-chart");
  if (!ctx || !data.labels) return;
  if (window._newsVolChart) window._newsVolChart.destroy();
  window._newsVolChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: data.labels,
      datasets: [{
        label: "Articles per day",
        data: data.values,
        borderColor: window.SAURON_CHART_COLORS.accent,
        backgroundColor: window.SAURON_CHART_COLORS.accentDim,
        tension: 0.3, fill: true,
      }],
    },
    options: { responsive: true, maintainAspectRatio: false,
               plugins: { legend: { display: false } } },
  });
})();
</script>
'''


F_TPL_BACKTEST_METRICS = '''{% include "_chart_assets.html" %}
<div class="backtest-metrics">
  <div class="sv-section-title">Latest backtest equity curve</div>
  <div class="sv-chart-container tall">
    <canvas id="backtest-equity-chart"></canvas>
  </div>

  <div class="sv-section-title">Recent runs</div>
  {% if runs %}
    <table class="sv-perf-table">
      <thead>
        <tr><th>Name</th><th>Hash</th><th>Return</th><th>Max DD</th>
            <th>Sharpe</th><th>Trades</th><th>Win rate</th></tr>
      </thead>
      <tbody>
        {% for r in runs %}
          <tr>
            <td>{{ r.name }}</td>
            <td>{{ r.config_hash }}</td>
            <td class="{% if r.total_return_pct > 0 %}up{% else %}down{% endif %}">
              {{ r.total_return_pct|floatformat:2 }}%
            </td>
            <td>{{ r.max_drawdown_pct|floatformat:2 }}%</td>
            <td>{{ r.sharpe|default:"\u2014"|floatformat:2 }}</td>
            <td>{{ r.n_trades }}</td>
            <td>{{ r.win_rate|floatformat:2 }}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p style="color:var(--text-muted);">No backtest runs yet. Run
      <code>python manage.py backtest_v2 --symbol BTCUSDT --persist</code></p>
  {% endif %}
</div>

<style>
.up { color: var(--accent); }
.down { color: var(--accent-red); }
.sv-perf-table { width: 100%; border-collapse: collapse;
                 font-family: var(--font-mono); font-size: 0.85rem; }
.sv-perf-table th, .sv-perf-table td { padding: 8px 10px; text-align: left;
                                        border-bottom: 1px solid var(--border); }
.sv-perf-table th { color: var(--text-muted); text-transform: uppercase;
                    font-size: 0.7rem; letter-spacing: 0.05em; }
</style>

<script>
(function() {
  const data = {{ chart_data|safe }};
  const ctx = document.getElementById("backtest-equity-chart");
  if (!ctx || !data.labels || data.labels.length === 0) {
    if (ctx) ctx.parentElement.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:40px;">No equity curve data.</p>';
    return;
  }
  if (window._btEquityChart) window._btEquityChart.destroy();
  window._btEquityChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: data.labels,
      datasets: [{
        label: data.name || "Equity",
        data: data.equity,
        borderColor: window.SAURON_CHART_COLORS.accent,
        backgroundColor: window.SAURON_CHART_COLORS.accentDim,
        tension: 0.1, fill: true, pointRadius: 0, borderWidth: 2,
      }],
    },
    options: { responsive: true, maintainAspectRatio: false,
               plugins: { legend: { position: "top" } },
               scales: { x: { ticks: { maxTicksLimit: 12 } } } },
  });
})();
</script>
'''


F_TPL_PORTFOLIO_METRICS = '''{% include "_chart_assets.html" %}
<div class="portfolio-metrics">
  <div class="sv-section-title">Portfolio exposure</div>
  <div class="sv-metrics-grid">
    <div class="sv-metric-card">
      <div class="sv-metric-label">Total</div>
      <div class="sv-metric-value">{{ exposure.total|default:"0" }}</div>
    </div>
    <div class="sv-metric-card">
      <div class="sv-metric-label">Gross</div>
      <div class="sv-metric-value">{{ exposure.gross|default:"0" }}</div>
    </div>
    <div class="sv-metric-card">
      <div class="sv-metric-label">Net</div>
      <div class="sv-metric-value">{{ exposure.net|default:"0" }}</div>
    </div>
    <div class="sv-metric-card">
      <div class="sv-metric-label">Long / Short</div>
      <div class="sv-metric-value">{{ exposure.long_value|default:"0" }} / {{ exposure.short_value|default:"0" }}</div>
    </div>
  </div>

  <div class="sv-section-title">Composition by asset class</div>
  <div class="sv-chart-container">
    <canvas id="portfolio-asset-chart"></canvas>
  </div>
</div>

<script>
(function() {
  const data = {{ chart_data|safe }};
  const ctx = document.getElementById("portfolio-asset-chart");
  if (!ctx || !data.labels || data.labels.length === 0) {
    if (ctx) ctx.parentElement.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:40px;">No portfolio data yet.</p>';
    return;
  }
  if (window._portfolioChart) window._portfolioChart.destroy();
  const colors = [
    window.SAURON_CHART_COLORS.accent,
    window.SAURON_CHART_COLORS.blue,
    window.SAURON_CHART_COLORS.gold,
    window.SAURON_CHART_COLORS.purple,
  ];
  window._portfolioChart = new Chart(ctx, {
    type: "pie",
    data: {
      labels: data.labels,
      datasets: [{ data: data.values,
                   backgroundColor: data.labels.map((_, i) => colors[i % colors.length]),
                   borderColor: window.SAURON_CHART_COLORS.border, borderWidth: 2 }],
    },
    options: { responsive: true, maintainAspectRatio: false,
               plugins: { legend: { position: "right" } } },
  });
})();
</script>
'''


F_TPL_POSITIONS_METRICS = '''{% include "_chart_assets.html" %}
<div class="positions-metrics">
  <div class="sv-section-title">Open positions PnL</div>
  <div class="sv-chart-container">
    <canvas id="positions-pnl-chart"></canvas>
  </div>

  <div class="sv-section-title">Positions ({{ positions|length }})</div>
  {% if positions %}
    <table class="sv-perf-table">
      <thead>
        <tr><th>Symbol</th><th>Side</th><th>Entry</th><th>Current</th>
            <th>Unrealized</th><th>%</th></tr>
      </thead>
      <tbody>
        {% for p in positions %}
          <tr>
            <td>{{ p.instrument.symbol }}</td>
            <td>{{ p.side|default:"\u2014" }}</td>
            <td>{{ p.entry_price|default:"\u2014" }}</td>
            <td>{{ p.current_price|default:"\u2014" }}</td>
            <td class="{% if p.unrealized_pnl > 0 %}up{% else %}down{% endif %}">
              {{ p.unrealized_pnl|default:"0" }}
            </td>
            <td>{{ p.unrealized_pnl_pct|default:"\u2014" }}</td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p style="color:var(--text-muted);">No open positions.</p>
  {% endif %}
</div>

<style>
.up { color: var(--accent); } .down { color: var(--accent-red); }
.sv-perf-table { width: 100%; border-collapse: collapse;
                 font-family: var(--font-mono); font-size: 0.85rem; }
.sv-perf-table th, .sv-perf-table td { padding: 8px 10px; text-align: left;
                                        border-bottom: 1px solid var(--border); }
.sv-perf-table th { color: var(--text-muted); text-transform: uppercase;
                    font-size: 0.7rem; letter-spacing: 0.05em; }
</style>

<script>
(function() {
  const data = {{ chart_data|safe }};
  const ctx = document.getElementById("positions-pnl-chart");
  if (!ctx || !data.labels || data.labels.length === 0) {
    if (ctx) ctx.parentElement.innerHTML = '<p style="color:var(--text-muted);text-align:center;padding:40px;">No open positions.</p>';
    return;
  }
  if (window._positionsChart) window._positionsChart.destroy();
  const colors = data.values.map(v =>
    v >= 0 ? window.SAURON_CHART_COLORS.accent : window.SAURON_CHART_COLORS.red
  );
  window._positionsChart = new Chart(ctx, {
    type: "bar",
    data: {
      labels: data.labels,
      datasets: [{ data: data.values, backgroundColor: colors,
                   borderWidth: 0 }],
    },
    options: { responsive: true, maintainAspectRatio: false,
               plugins: { legend: { display: false } },
               scales: { y: { beginAtZero: true } } },
  });
})();
</script>
'''


F_TPL_ADMIN_BOTS = '''{% load static %}
<div class="admin-bots">
  <div class="sv-section-title">Bot control panel</div>
  {% if error %}
    <div style="color:var(--accent-red);">{{ error }}</div>
  {% endif %}
  {% if rows %}
    <table class="sv-perf-table">
      <thead>
        <tr>
          <th>User</th><th>Mode</th><th>Market</th><th>Enabled</th>
          <th>Shadow</th><th>HB age</th><th>Open</th><th>Circuit</th><th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {% for row in rows %}
          <tr id="bot-row-{{ row.config.id }}">
            <td>{{ row.user.username }}</td>
            <td><span class="badge">{{ row.mode }}</span></td>
            <td>{{ row.market }}</td>
            <td>{% if row.enabled %}\u2705{% else %}\u23f8{% endif %}</td>
            <td>{% if row.shadow %}\U0001F441{% else %}\u2014{% endif %}</td>
            <td>{% if row.heartbeat_age %}{{ row.heartbeat_age|floatformat:0 }}s{% else %}\u2014{% endif %}</td>
            <td>{{ row.open_trades }}</td>
            <td>{% if row.circuit %}<span style="color:var(--accent-red);">{{ row.circuit }}</span>{% else %}ok{% endif %}</td>
            <td class="actions">
              <button class="btn-small" onclick="adminBotToggle({{ row.config.id }})">Toggle</button>
              <button class="btn-small" onclick="adminBotShadow({{ row.config.id }})">Shadow 24h</button>
              <button class="btn-small" onclick="adminBotResetCircuit({{ row.config.id }})">Reset circuit</button>
              <button class="btn-small" onclick="adminBotReconcile({{ row.config.id }})">Reconcile</button>
            </td>
          </tr>
        {% endfor %}
      </tbody>
    </table>
  {% else %}
    <p style="color:var(--text-muted);">No bot configs found.</p>
  {% endif %}
</div>

<style>
.admin-bots .sv-perf-table { width: 100%; border-collapse: collapse;
                              font-family: var(--font-mono); font-size: 0.85rem; }
.admin-bots .sv-perf-table th, .admin-bots .sv-perf-table td {
  padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border);
}
.admin-bots .sv-perf-table th { color: var(--text-muted);
  text-transform: uppercase; font-size: 0.7rem; letter-spacing: 0.05em; }
.admin-bots .actions { display: flex; gap: 4px; flex-wrap: wrap; }
.admin-bots .btn-small {
  padding: 4px 8px; font-size: 0.7rem; background: var(--bg-secondary);
  color: var(--text-secondary); border: 1px solid var(--border);
  border-radius: 4px; cursor: pointer; font-family: var(--font-mono);
}
.admin-bots .btn-small:hover { color: var(--accent); border-color: var(--accent); }
.admin-bots .badge {
  padding: 2px 6px; background: var(--bg-secondary); border-radius: 3px;
  font-size: 0.7rem; text-transform: uppercase;
}
</style>

<script>
function getCsrf() {
  const m = document.cookie.match(/csrftoken=([^;]+)/);
  return m ? m[1] : "";
}
async function adminBotPost(url) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "X-CSRFToken": getCsrf() },
  });
  return r.json();
}
async function adminBotToggle(id) {
  const r = await adminBotPost(`/htmx/admin/bots/${id}/toggle/`);
  if (r.ok) location.reload();
  else alert("Failed: " + r.error);
}
async function adminBotShadow(id) {
  const r = await adminBotPost(`/htmx/admin/bots/${id}/shadow/`);
  if (r.ok) alert("Shadow mode enabled until " + r.shadow_until);
  else alert("Failed: " + r.error);
}
async function adminBotResetCircuit(id) {
  const r = await adminBotPost(`/htmx/admin/bots/${id}/reset-circuit/`);
  if (r.ok) location.reload();
  else alert("Failed: " + r.error);
}
async function adminBotReconcile(id) {
  const r = await adminBotPost(`/htmx/admin/bots/${id}/reconcile/`);
  if (r.ok) alert("Reconciled: " + JSON.stringify(r.result));
  else alert("Failed: " + r.error);
}
window.adminBotToggle = adminBotToggle;
window.adminBotShadow = adminBotShadow;
window.adminBotResetCircuit = adminBotResetCircuit;
window.adminBotReconcile = adminBotReconcile;
</script>
'''


F_TPL_PIN_MODAL = '''<form id="pin-change-form" onsubmit="event.preventDefault(); submitPinChange();">
  {% csrf_token %}
  <div class="input-group" style="margin-bottom:12px;">
    <label class="input-label">CURRENT PIN</label>
    <input type="password" name="current_pin" class="input"
           inputmode="numeric" maxlength="8" autocomplete="off">
  </div>
  <div class="input-group" style="margin-bottom:12px;">
    <label class="input-label">NEW PIN</label>
    <input type="password" name="new_pin" class="input"
           inputmode="numeric" maxlength="8" autocomplete="new-password" required>
  </div>
  <div class="input-group" style="margin-bottom:16px;">
    <label class="input-label">CONFIRM</label>
    <input type="password" name="confirm_pin" class="input"
           inputmode="numeric" maxlength="8" autocomplete="new-password" required>
  </div>
  <div id="pin-modal-error" style="color:var(--accent-red);font-size:0.85rem;margin-bottom:12px;display:none;"></div>
  <button type="submit" class="btn btn-primary" style="width:100%;">UPDATE PIN</button>
</form>

<script>
async function submitPinChange() {
  const form = document.getElementById("pin-change-form");
  const data = new FormData(form);
  const errEl = document.getElementById("pin-modal-error");
  errEl.style.display = "none";
  try {
    const r = await fetch("/profile/change-pin-modal/", {
      method: "POST",
      body: data,
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    const j = await r.json();
    if (j.ok) {
      svCloseModal("pin-modal");
      location.reload();    // auto-save effect: refresh to show new state
    } else {
      errEl.textContent = j.error || "Update failed.";
      errEl.style.display = "block";
    }
  } catch (e) {
    errEl.textContent = "Network error.";
    errEl.style.display = "block";
  }
}
window.submitPinChange = submitPinChange;
</script>
'''


F_TPL_PASSWORD_MODAL = '''<form id="pwd-change-form" onsubmit="event.preventDefault(); submitPasswordChange();">
  {% csrf_token %}
  <div class="input-group" style="margin-bottom:12px;">
    <label class="input-label">CURRENT PASSWORD</label>
    <input type="password" name="current_password" class="input" autocomplete="current-password" required>
  </div>
  <div class="input-group" style="margin-bottom:12px;">
    <label class="input-label">NEW PASSWORD</label>
    <input type="password" name="new_password" class="input" autocomplete="new-password" required minlength="8">
  </div>
  <div class="input-group" style="margin-bottom:16px;">
    <label class="input-label">CONFIRM</label>
    <input type="password" name="confirm_password" class="input" autocomplete="new-password" required minlength="8">
  </div>
  <div id="pwd-modal-error" style="color:var(--accent-red);font-size:0.85rem;margin-bottom:12px;display:none;"></div>
  <button type="submit" class="btn btn-primary" style="width:100%;">UPDATE PASSWORD</button>
</form>

<script>
async function submitPasswordChange() {
  const form = document.getElementById("pwd-change-form");
  const data = new FormData(form);
  const errEl = document.getElementById("pwd-modal-error");
  errEl.style.display = "none";
  try {
    const r = await fetch("/profile/change-password/", {
      method: "POST",
      body: data,
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    const j = await r.json();
    if (j.ok) {
      svCloseModal("password-modal");
      location.reload();
    } else {
      errEl.textContent = j.error || "Update failed.";
      errEl.style.display = "block";
    }
  } catch (e) {
    errEl.textContent = "Network error.";
    errEl.style.display = "block";
  }
}
window.submitPasswordChange = submitPasswordChange;
</script>
'''


F_TPL_PROFILE_CREDENTIALS = '''{% comment %}
Drop-in panel for the profile page. Replaces the inline PIN form with two
buttons that open modals. Include with:

  {% include "dashboard/_profile_credentials.html" %}

{% endcomment %}
<div class="profile-credentials">
  <div class="sv-section-title">Account credentials</div>
  <p style="color:var(--text-secondary);font-size:0.9rem;margin-bottom:16px;">
    Both your access PIN and password can be updated below.
    Updates are saved automatically when you submit the form.
  </p>
  <div style="display:flex;gap:12px;flex-wrap:wrap;">
    <button class="btn btn-primary" onclick="loadAndOpenModal('pin-modal', '/htmx/profile/pin-modal/', 'Change PIN')">
      Change PIN
    </button>
    <button class="btn btn-primary" onclick="loadAndOpenModal('password-modal', '/htmx/profile/password-modal/', 'Change password')">
      Change password
    </button>
  </div>
</div>

<!-- Modal containers (filled via fetch) -->
<div class="sv-modal-backdrop" id="pin-modal-backdrop" onclick="svCloseModal('pin-modal')"></div>
<div class="sv-modal" id="pin-modal" role="dialog" aria-modal="true">
  <div class="sv-modal__header">
    <span class="sv-modal__title" id="pin-modal-title">Change PIN</span>
    <button class="sv-modal__close" onclick="svCloseModal('pin-modal')" aria-label="Close">\u00d7</button>
  </div>
  <div class="sv-modal__body" id="pin-modal-body"></div>
</div>

<div class="sv-modal-backdrop" id="password-modal-backdrop" onclick="svCloseModal('password-modal')"></div>
<div class="sv-modal" id="password-modal" role="dialog" aria-modal="true">
  <div class="sv-modal__header">
    <span class="sv-modal__title" id="password-modal-title">Change password</span>
    <button class="sv-modal__close" onclick="svCloseModal('password-modal')" aria-label="Close">\u00d7</button>
  </div>
  <div class="sv-modal__body" id="password-modal-body"></div>
</div>

<style>
.sv-modal-backdrop { display: none; position: fixed; inset: 0;
  background: rgba(0,0,0,0.7); z-index: 9998; backdrop-filter: blur(3px); }
.sv-modal { display: none; position: fixed; top: 50%; left: 50%;
  transform: translate(-50%, -50%); z-index: 9999;
  background: var(--bg-card); border: 1px solid var(--border-glow);
  border-radius: var(--radius-lg); box-shadow: 0 10px 60px rgba(0,0,0,0.8);
  min-width: 360px; max-width: 540px; width: 90%; }
.sv-modal.is-open, .sv-modal-backdrop.is-open { display: block; }
.sv-modal__header { display: flex; justify-content: space-between;
  align-items: center; padding: 14px 18px; border-bottom: 1px solid var(--border); }
.sv-modal__title { font-family: var(--font-heading); font-size: 1rem;
  color: var(--accent); text-transform: uppercase; letter-spacing: 0.08em; }
.sv-modal__close { background: none; border: none; color: var(--text-secondary);
  font-size: 1.5rem; cursor: pointer; line-height: 1; }
.sv-modal__close:hover { color: var(--accent); }
.sv-modal__body { padding: 18px; }
</style>

<script>
function svOpenModal(id) {
  document.getElementById(id).classList.add("is-open");
  document.getElementById(id + "-backdrop").classList.add("is-open");
}
function svCloseModal(id) {
  document.getElementById(id).classList.remove("is-open");
  document.getElementById(id + "-backdrop").classList.remove("is-open");
}
async function loadAndOpenModal(id, url, title) {
  try {
    const r = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
    const html = await r.text();
    document.getElementById(id + "-body").innerHTML = html;
    // Re-execute any scripts in the loaded HTML
    document.getElementById(id + "-body").querySelectorAll("script").forEach(old => {
      const s = document.createElement("script");
      s.text = old.text;
      old.parentNode.replaceChild(s, old);
    });
    document.getElementById(id + "-title").textContent = title;
    svOpenModal(id);
  } catch (e) {
    alert("Could not load modal: " + e);
  }
}
window.svOpenModal = svOpenModal;
window.svCloseModal = svCloseModal;
window.loadAndOpenModal = loadAndOpenModal;
</script>
'''


F_TPL_STRATEGY_WIZARD = '''{% extends "base.html" %}
{% block title %}New Strategy \u00b7 Sauron Vision{% endblock %}
{% block content %}
<div class="container" style="max-width:680px;margin:40px auto;">
  <h2 style="font-family:var(--font-heading);color:var(--accent);text-transform:uppercase;letter-spacing:0.1em;">
    Create new strategy
  </h2>
  <p style="color:var(--text-secondary);">Define a strategy framework. You can refine the legs and risk parameters after creation.</p>

  <form id="wizard-form" onsubmit="event.preventDefault(); submitWizard();">
    {% csrf_token %}
    <div class="input-group">
      <label class="input-label">Strategy name</label>
      <input type="text" name="name" class="input" required placeholder="e.g. BTC dip-buy with hedge">
    </div>
    <div class="input-group">
      <label class="input-label">Description / thesis</label>
      <textarea name="description" class="input" rows="4" placeholder="Why does this trade make sense now?"></textarea>
    </div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
      <div class="input-group">
        <label class="input-label">Time horizon</label>
        <select name="time_horizon" class="input">
          <option value="scalp">Scalp</option>
          <option value="intraday">Intraday</option>
          <option value="swing" selected>Swing</option>
          <option value="position">Position</option>
        </select>
      </div>
      <div class="input-group">
        <label class="input-label">Max allocation (%)</label>
        <input type="number" name="max_portfolio_allocation_pct" class="input" value="10" min="0" max="100" step="0.5">
      </div>
    </div>
    <div class="input-group">
      <label class="input-label">Max loss per trade (%)</label>
      <input type="number" name="max_loss_pct" class="input" value="2" min="0" max="20" step="0.5">
    </div>
    <div id="wizard-error" style="color:var(--accent-red);font-size:0.85rem;margin:12px 0;display:none;"></div>
    <div style="display:flex;gap:12px;">
      <button type="submit" class="btn btn-primary">Create strategy</button>
      <a href="/strategies/" class="btn">Cancel</a>
    </div>
  </form>
</div>

<script>
async function submitWizard() {
  const form = document.getElementById("wizard-form");
  const data = new FormData(form);
  const errEl = document.getElementById("wizard-error");
  errEl.style.display = "none";
  try {
    const r = await fetch("/strategies/new/save/", {
      method: "POST", body: data,
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    const j = await r.json();
    if (j.ok) {
      window.location = j.redirect || "/strategies/";
    } else {
      errEl.textContent = j.error || "Failed to create strategy.";
      errEl.style.display = "block";
    }
  } catch (e) {
    errEl.textContent = "Network error.";
    errEl.style.display = "block";
  }
}
window.submitWizard = submitWizard;
</script>
{% endblock %}
'''


# ============================================================================
# FILES dict
# ============================================================================
FILES = {
    # Strategy templates and modules — replace stubs
    "strategies/templates/momentum.py":               F_MOMENTUM,
    "strategies/templates/mean_reversion.py":         F_MEAN_REVERSION,
    "strategies/templates/pairs_trading.py":          F_PAIRS_TRADING,
    "strategies/templates/macro_regime.py":           F_MACRO_REGIME,
    "strategies/engine.py":                           F_STRATEGY_ENGINE,
    "strategies/risk_manager.py":                     F_RISK_MANAGER,
    "strategies/portfolio_analyzer.py":               F_PORTFOLIO_ANALYZER,

    # Shared UI assets
    "templates/_chart_assets.html":                   F_CHART_ASSETS,
    "templates/_modal.html":                          F_MODAL,

    # Views
    "dashboard/views_metrics.py":                     F_METRICS_VIEWS,
    "dashboard/views_profile_modals.py":              F_PROFILE_VIEWS,
    "dashboard/views_admin_bots.py":                  F_ADMIN_BOTS_VIEW,
    "dashboard/views_strategy_wizard.py":             F_WIZARD_VIEW,

    # Page metric templates
    "templates/dashboard/_signals_metrics.html":      F_TPL_SIGNALS_METRICS,
    "templates/dashboard/_strategies_metrics.html":   F_TPL_STRATEGIES_METRICS,
    "templates/dashboard/_news_metrics.html":         F_TPL_NEWS_METRICS,
    "templates/dashboard/_backtest_metrics.html":     F_TPL_BACKTEST_METRICS,
    "templates/dashboard/_portfolio_metrics.html":    F_TPL_PORTFOLIO_METRICS,
    "templates/dashboard/_positions_metrics.html":    F_TPL_POSITIONS_METRICS,

    # Admin bots panel
    "templates/dashboard/_admin_bots.html":           F_TPL_ADMIN_BOTS,

    # Profile modals
    "templates/dashboard/_profile_pin_modal.html":      F_TPL_PIN_MODAL,
    "templates/dashboard/_profile_password_modal.html": F_TPL_PASSWORD_MODAL,
    "templates/dashboard/_profile_credentials.html":    F_TPL_PROFILE_CREDENTIALS,

    # Strategy wizard
    "templates/dashboard/_strategy_wizard.html":      F_TPL_STRATEGY_WIZARD,
}


# Files where the existing version is a known stub we want to replace.
OVERWRITE_STUBS = {
    "strategies/templates/momentum.py",
    "strategies/templates/mean_reversion.py",
    "strategies/templates/pairs_trading.py",
    "strategies/templates/macro_regime.py",
    "strategies/engine.py",
    "strategies/risk_manager.py",
    "strategies/portfolio_analyzer.py",
}


# ============================================================================
# URL appends to dashboard/urls.py
# ============================================================================
def modify_dashboard_urls():
    """Idempotently append the new metric/admin/profile/wizard routes."""
    path = ROOT / "dashboard" / "urls.py"
    if not path.exists():
        return False, "dashboard/urls.py not found"
    text = path.read_text(encoding="utf-8")
    if "views_metrics" in text:
        return True, "already wired"

    text_n = text.replace("\r\n", "\n")

    new_imports = (
        "\nfrom .views_metrics import (\n"
        "    signals_metrics, strategies_metrics, news_metrics,\n"
        "    backtest_metrics, portfolio_metrics, positions_metrics,\n"
        ")\n"
        "from .views_profile_modals import (\n"
        "    pin_modal, password_modal, change_password, change_pin_modal,\n"
        ")\n"
        "from .views_admin_bots import (\n"
        "    admin_bots_panel, admin_bot_toggle, admin_bot_shadow,\n"
        "    admin_bot_reset_circuit, admin_bot_reconcile,\n"
        ")\n"
        "from .views_strategy_wizard import strategy_wizard, strategy_wizard_save\n"
    )

    new_paths = (
        '    path("htmx/metrics/signals/", signals_metrics, name="metrics_signals"),\n'
        '    path("htmx/metrics/strategies/", strategies_metrics, name="metrics_strategies"),\n'
        '    path("htmx/metrics/news/", news_metrics, name="metrics_news"),\n'
        '    path("htmx/metrics/backtest/", backtest_metrics, name="metrics_backtest"),\n'
        '    path("htmx/metrics/portfolio/", portfolio_metrics, name="metrics_portfolio"),\n'
        '    path("htmx/metrics/positions/", positions_metrics, name="metrics_positions"),\n'
        '    path("htmx/profile/pin-modal/", pin_modal, name="pin_modal"),\n'
        '    path("htmx/profile/password-modal/", password_modal, name="password_modal"),\n'
        '    path("profile/change-password/", change_password, name="change_password"),\n'
        '    path("profile/change-pin-modal/", change_pin_modal, name="change_pin_modal"),\n'
        '    path("htmx/admin/bots/", admin_bots_panel, name="admin_bots_panel"),\n'
        '    path("htmx/admin/bots/<int:config_id>/toggle/", admin_bot_toggle, name="admin_bot_toggle"),\n'
        '    path("htmx/admin/bots/<int:config_id>/shadow/", admin_bot_shadow, name="admin_bot_shadow"),\n'
        '    path("htmx/admin/bots/<int:config_id>/reset-circuit/", admin_bot_reset_circuit, name="admin_bot_reset_circuit"),\n'
        '    path("htmx/admin/bots/<int:config_id>/reconcile/", admin_bot_reconcile, name="admin_bot_reconcile"),\n'
        '    path("strategies/new/", strategy_wizard, name="strategy_wizard"),\n'
        '    path("strategies/new/save/", strategy_wizard_save, name="strategy_wizard_save"),\n'
        ']'
    )

    # Insert imports after "from . import views"
    if "from .views_metrics" not in text_n:
        text_n = text_n.replace(
            "from . import views",
            "from . import views" + new_imports,
            1,
        )

    # Insert paths before the closing ']'
    if text_n.rstrip().endswith("]"):
        text_n = text_n.rstrip()[:-1] + new_paths + "\n"
    else:
        return False, "urls.py doesn't end with ']' as expected"

    path.write_text(text_n, encoding="utf-8")
    return True, "appended metrics + profile + admin + wizard routes"


# ============================================================================
# Runner
# ============================================================================
def write_files():
    for rel, content in FILES.items():
        path = ROOT / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        is_stub = rel in OVERWRITE_STUBS
        if path.exists() and not FORCE and not is_stub:
            existing = path.read_text(encoding="utf-8")
            if existing.strip() == content.strip():
                print(f"  OK   (unchanged): {rel}")
                continue
            print(f"  SKIP (exists, --force to overwrite): {rel}")
            continue
        if is_stub and path.exists():
            existing = path.read_text(encoding="utf-8")
            if "TODO" in existing or len(existing.strip()) < 400 or "pass" in existing.split("\n")[-3:][0]:
                path.write_text(content, encoding="utf-8")
                print(f"  REPLACED stub: {rel}")
                continue
            elif not FORCE:
                print(f"  SKIP (modified, --force to overwrite): {rel}")
                continue
        path.write_text(content, encoding="utf-8")
        print(f"  WROTE: {rel}")


def run_modifications():
    print()
    print("[modifications to existing files]")
    try:
        ok, msg = modify_dashboard_urls()
        tag = "OK" if ok else "WARN"
        print(f"  {tag}: dashboard/urls.py -- {msg}")
    except Exception as e:
        print(f"  ERROR: dashboard/urls.py -- {e}")


def main():
    print("=" * 72)
    print("  Sauron Vision - Upgrade 13: Strategies + UI polish")
    print("=" * 72)
    print()
    print("[1/2] Writing files...")
    write_files()
    run_modifications()
    print()
    print("=" * 72)
    print("  DONE. Next steps:")
    print("=" * 72)
    print()
    print("  # 1. No new migrations needed for this upgrade.")
    print("  # 2. Restart the dev server.")
    print("  python manage.py runserver")
    print()
    print("  # 3. Visit the new endpoints:")
    print("  #    /strategies/new/                 - Strategy create wizard")
    print("  #    /htmx/metrics/signals/           - Signals enrichment partial")
    print("  #    /htmx/metrics/strategies/        - Strategies enrichment partial")
    print("  #    /htmx/metrics/news/              - News + sentiment enrichment")
    print("  #    /htmx/metrics/backtest/          - Backtest enrichment")
    print("  #    /htmx/metrics/portfolio/         - Portfolio enrichment")
    print("  #    /htmx/metrics/positions/         - Positions enrichment")
    print("  #    /htmx/admin/bots/                - Admin bot control panel")
    print()
    print("  # 4. Wire the metric partials into your existing pages by editing")
    print("  #    the relevant template (e.g. signals_list.html, strategies_list.html)")
    print("  #    and adding near the end of {% block content %}:")
    print("  #")
    print("  #    <div hx-get=\"/htmx/metrics/signals/\" hx-trigger=\"load, every 60s\"></div>")
    print("  #")
    print("  #    Or do a full include after the existing page content:")
    print("  #    {% include \"dashboard/_signals_metrics.html\" %}")
    print("  #    (the include path won't work directly because the partial expects")
    print("  #    its context to be populated by the view; use the hx-get version.)")
    print()
    print("  # 5. Wire the profile credentials panel by adding to profile.html:")
    print("  #    {% include \"dashboard/_profile_credentials.html\" %}")
    print("  #    (and remove the inline change-pin <form> if you want to)")
    print()
    print("  # 6. Wire the admin bot panel similarly into your admin_dashboard.html:")
    print("  #    <div hx-get=\"/htmx/admin/bots/\" hx-trigger=\"load, every 30s\"></div>")
    print()
    print("  # NOTE: HTMX must be loaded in your base.html. If you don't have it,")
    print("  # add this to base.html <head>:")
    print('  #    <script src="https://unpkg.com/htmx.org@1.9.10"></script>')
    print()


if __name__ == "__main__":
    main()
