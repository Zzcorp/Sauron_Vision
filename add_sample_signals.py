#!/usr/bin/env python
"""
add_sample_signals.py
Seeds 5 trading signals. Two are "very interesting" high-conviction plays
(one forex, one options) with a $5,000 minimum-investment sizing note.

Run from project root:
    python add_sample_signals.py

Re-runnable: deactivates any prior sample signals with the same rule_name
before creating the new batch so duplicates don't pile up.
"""
import os, sys, django
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from instruments.models import Instrument
from signals.models import Signal
from core.constants import AssetClass, Direction, Urgency

MIN_INVESTMENT_USD = 5000

INSTRUMENTS = [
    {
        "symbol": "EURUSD",
        "name": "Euro / US Dollar",
        "asset_class": AssetClass.FOREX,
        "currency": "USD",
    },
    {
        "symbol": "SPY_250620C470",
        "name": "SPY 20-Jun-25 $470 Call",
        "asset_class": AssetClass.OPTIONS,
        "currency": "USD",
        "metadata": {"underlying": "SPY", "strike": 470, "expiry": "2025-06-20", "type": "call"},
    },
    {
        "symbol": "GBPJPY",
        "name": "British Pound / Japanese Yen",
        "asset_class": AssetClass.FOREX,
        "currency": "JPY",
    },
    {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "asset_class": AssetClass.STOCK,
        "currency": "USD",
        "exchange": "NASDAQ",
    },
    {
        "symbol": "XAUUSD",
        "name": "Gold Spot / USD",
        "asset_class": AssetClass.COMMODITY,
        "currency": "USD",
    },
]

SIGNALS = [
    # ---- 2 "VERY INTERESTING" high-conviction plays (5K MIN) ----
    {
        "symbol": "EURUSD",
        "rule_name": "sv_sample_forex_breakout_hc",
        "signal_type": "composite",
        "direction": Direction.BULLISH,
        "urgency": Urgency.CRITICAL,
        "title": "EUR/USD Bullish Breakout — 5K MIN · Very High Conviction",
        "description": (
            "Multi-timeframe confluence: H4 bullish market structure shift, "
            "London-session liquidity sweep of 1.0820 lows, and institutional "
            "order block retest at 1.0855. DXY rejecting 105.80 resistance. "
            "Minimum sizing $5,000 to absorb 45-pip stop with meaningful R."
        ),
        "score": 0.92,
        "sub_scores": {
            "structure": 0.95, "momentum": 0.88, "flow": 0.90,
            "macro": 0.86, "sentiment": 0.82,
            "min_investment_usd": MIN_INVESTMENT_USD,
            "featured": True,
        },
        "price_at_signal": Decimal("1.08552"),
        "suggested_entry": Decimal("1.08580"),
        "suggested_stop": Decimal("1.08130"),
        "suggested_target": Decimal("1.09650"),
        "risk_reward_ratio": 2.38,
        "portfolio_impact": "★ High-conviction — $5,000 minimum investment recommended.",
    },
    {
        "symbol": "SPY_250620C470",
        "rule_name": "sv_sample_options_gamma_squeeze_hc",
        "signal_type": "flow",
        "direction": Direction.BULLISH,
        "urgency": Urgency.CRITICAL,
        "title": "SPY $470C Jun-20 — Gamma Squeeze · 5K MIN · Very High Conviction",
        "description": (
            "Unusual call flow: 18,400 contracts @ ask on the $470 strike, "
            "4.2x 20-day avg. Dealer positioning pinned short gamma above "
            "465; underlying SPY reclaimed VWAP on expanding volume. "
            "Minimum $5,000 sized to survive theta drag and widen IV crush buffer."
        ),
        "score": 0.89,
        "sub_scores": {
            "flow": 0.96, "gamma": 0.92, "iv_rank": 0.28,
            "delta": 0.54, "theta_per_day_pct": -1.8,
            "min_investment_usd": MIN_INVESTMENT_USD,
            "featured": True,
        },
        "price_at_signal": Decimal("4.85"),
        "suggested_entry": Decimal("4.90"),
        "suggested_stop": Decimal("2.80"),
        "suggested_target": Decimal("9.20"),
        "risk_reward_ratio": 2.05,
        "portfolio_impact": "★ High-conviction — $5,000 minimum investment recommended.",
    },
    # ---- 3 standard signals ----
    {
        "symbol": "GBPJPY",
        "rule_name": "sv_sample_forex_range_fade",
        "signal_type": "technical",
        "direction": Direction.BEARISH,
        "urgency": Urgency.MEDIUM,
        "title": "GBP/JPY Range Rejection at 192.80",
        "description": (
            "Fourth rejection of the 192.80 supply zone on H1. RSI divergence "
            "printing; BOJ jawboning risk into Asia session."
        ),
        "score": 0.68,
        "sub_scores": {"structure": 0.70, "momentum": 0.65, "sentiment": 0.72},
        "price_at_signal": Decimal("192.74"),
        "suggested_entry": Decimal("192.70"),
        "suggested_stop": Decimal("193.05"),
        "suggested_target": Decimal("191.85"),
        "risk_reward_ratio": 2.43,
    },
    {
        "symbol": "AAPL",
        "rule_name": "sv_sample_stock_earnings_run",
        "signal_type": "fundamental",
        "direction": Direction.BULLISH,
        "urgency": Urgency.HIGH,
        "title": "AAPL — Pre-Earnings Drift Setup",
        "description": (
            "Seasonal pre-earnings drift; options skew flattening. Services "
            "revenue whisper strong, Services margin at 74%. Entry on "
            "pullback to 20-EMA."
        ),
        "score": 0.74,
        "sub_scores": {"fundamentals": 0.80, "seasonality": 0.76, "momentum": 0.68},
        "price_at_signal": Decimal("184.25"),
        "suggested_entry": Decimal("183.40"),
        "suggested_stop": Decimal("178.90"),
        "suggested_target": Decimal("194.00"),
        "risk_reward_ratio": 2.36,
    },
    {
        "symbol": "XAUUSD",
        "rule_name": "sv_sample_gold_macro_hedge",
        "signal_type": "macro",
        "direction": Direction.BULLISH,
        "urgency": Urgency.MEDIUM,
        "title": "Gold — Real Yields Rolling Over",
        "description": (
            "10Y TIPS breaking below 1.85% with DXY softening. Central bank "
            "net buying remains elevated YTD. Classic macro tailwind."
        ),
        "score": 0.71,
        "sub_scores": {"macro": 0.78, "flow": 0.70, "sentiment": 0.66},
        "price_at_signal": Decimal("2358.40"),
        "suggested_entry": Decimal("2352.00"),
        "suggested_stop": Decimal("2322.00"),
        "suggested_target": Decimal("2420.00"),
        "risk_reward_ratio": 2.27,
    },
]


def ensure_instrument(spec):
    defaults = {k: v for k, v in spec.items() if k != "symbol"}
    inst, created = Instrument.objects.get_or_create(
        symbol=spec["symbol"], defaults=defaults
    )
    return inst, created


def main():
    # Ensure instruments exist
    for spec in INSTRUMENTS:
        inst, created = ensure_instrument(spec)
        print(("  + " if created else "  · ") + f"{inst.symbol} ({inst.get_asset_class_display()})")

    # Deactivate prior runs so re-running doesn't pile up duplicates
    prior = Signal.objects.filter(
        rule_name__in=[s["rule_name"] for s in SIGNALS], is_active=True
    )
    deactivated = prior.update(is_active=False, outcome="manual_close")
    if deactivated:
        print(f"\nDeactivated {deactivated} prior sample signal(s).")

    # Create fresh signals
    print("\nCreating signals:")
    for spec in SIGNALS:
        inst = Instrument.objects.get(symbol=spec["symbol"])
        payload = {k: v for k, v in spec.items() if k != "symbol"}
        sig = Signal.objects.create(instrument=inst, **payload)
        star = "*" if spec["sub_scores"].get("featured") else " "
        line = f"  {star} [{sig.urgency.upper():8}] {sig.instrument.symbol:20} {sig.title[:60]}"
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode("ascii", "replace").decode("ascii"))

    print(f"\nDone. Created {len(SIGNALS)} signals "
          f"(2 flagged featured @ ${MIN_INVESTMENT_USD:,} minimum).")


if __name__ == "__main__":
    main()
