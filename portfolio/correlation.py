"""Correlation engine — Phase 2 risk depth.

Computes pairwise return correlation across instruments using `PriceData`
daily bars. Used by:
  - PositionSizer.correlation_aware_size — scale down when correlated positions
    are already open.
  - Portfolio risk gate — block opening yet another position highly correlated
    with the existing book.
  - PortfolioSnapshot.correlation_matrix — nightly snapshot for the dashboard
    (the field exists but was never populated).

The Portfolio model has a `max_correlation_threshold` field (default 0.7) that
this module reads as the cap for "highly correlated."
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Iterable

import numpy as np
from django.utils import timezone

import logging
logger = logging.getLogger(__name__)


DEFAULT_LOOKBACK_DAYS = 90   # ~one quarter of trading days
MIN_OBSERVATIONS = 20        # below this, treat correlation as undefined


@dataclass
class CorrelationMatrix:
    """Pairwise correlation matrix across a set of instruments."""
    symbols: list[str]
    matrix: list[list[float]]              # symmetric N×N, diag = 1.0
    n_observations: int
    lookback_days: int
    missing: list[str] = field(default_factory=list)

    def get(self, a: str, b: str) -> float | None:
        """Correlation between symbol *a* and *b*. None if either is missing."""
        try:
            i = self.symbols.index(a)
            j = self.symbols.index(b)
        except ValueError:
            return None
        return self.matrix[i][j]

    def to_dict(self) -> dict:
        """JSON-serializable form for PortfolioSnapshot.correlation_matrix."""
        return {
            "symbols": list(self.symbols),
            "matrix": self.matrix,
            "n_observations": self.n_observations,
            "lookback_days": self.lookback_days,
            "missing": list(self.missing),
        }


def _fetch_returns(instrument, lookback_days: int) -> np.ndarray:
    """Daily simple returns for an instrument over the lookback. Empty if missing."""
    from market_data.models import PriceData
    cutoff = timezone.now() - timedelta(days=lookback_days)
    closes = list(
        PriceData.objects
        .filter(instrument=instrument, timeframe="1d", timestamp__gte=cutoff)
        .order_by("timestamp")
        .values_list("close", flat=True)
    )
    if len(closes) < 2:
        return np.array([])
    arr = np.array([float(c) for c in closes])
    return np.diff(arr) / arr[:-1]


def compute_correlation(
    instruments: Iterable,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> CorrelationMatrix:
    """Pairwise return-correlation across the given instruments.

    Returns a CorrelationMatrix. Instruments without enough history are listed
    in `.missing` and excluded from the matrix.
    """
    instruments = list(instruments)
    if not instruments:
        return CorrelationMatrix([], [], 0, lookback_days)

    series_by_symbol: dict[str, np.ndarray] = {}
    missing: list[str] = []
    for inst in instruments:
        r = _fetch_returns(inst, lookback_days)
        if len(r) < MIN_OBSERVATIONS:
            missing.append(inst.symbol)
            continue
        series_by_symbol[inst.symbol] = r

    if len(series_by_symbol) < 2:
        return CorrelationMatrix(
            list(series_by_symbol.keys()),
            [[1.0]] if series_by_symbol else [],
            int(min((len(v) for v in series_by_symbol.values()), default=0)),
            lookback_days,
            missing=missing,
        )

    # Align all series to the minimum length (most-recent N observations).
    min_len = min(len(v) for v in series_by_symbol.values())
    symbols = list(series_by_symbol.keys())
    aligned = np.vstack([series_by_symbol[s][-min_len:] for s in symbols])
    corr = np.corrcoef(aligned)
    # Replace NaN (zero-variance series) with 0 off-diagonal, 1 on-diagonal.
    corr = np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(corr, 1.0)

    return CorrelationMatrix(
        symbols=symbols,
        matrix=[[round(float(x), 6) for x in row] for row in corr],
        n_observations=int(min_len),
        lookback_days=lookback_days,
        missing=missing,
    )


def portfolio_correlation(portfolio, lookback_days: int = DEFAULT_LOOKBACK_DAYS) -> CorrelationMatrix:
    """Correlation matrix across a portfolio's open positions."""
    from portfolio.models import Position
    instruments = list(
        Position.objects
        .filter(portfolio=portfolio, closed_at__isnull=True)
        .values_list("instrument", flat=True)
    )
    if not instruments:
        return CorrelationMatrix([], [], 0, lookback_days)

    from instruments.models import Instrument
    insts = list(Instrument.objects.filter(id__in=instruments))
    return compute_correlation(insts, lookback_days=lookback_days)


def max_correlation_to_open_book(
    portfolio,
    candidate_instrument,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> tuple[float | None, str | None]:
    """Highest pairwise correlation between *candidate* and any open position.

    Returns (corr, peer_symbol) — or (None, None) if undefined (no positions, or
    insufficient history for either side). Used by the risk gate.
    """
    from portfolio.models import Position
    from instruments.models import Instrument

    open_inst_ids = list(
        Position.objects
        .filter(portfolio=portfolio, closed_at__isnull=True)
        .values_list("instrument", flat=True)
    )
    if not open_inst_ids:
        return None, None

    open_insts = list(Instrument.objects.filter(id__in=open_inst_ids))
    cm = compute_correlation([candidate_instrument, *open_insts], lookback_days=lookback_days)

    if candidate_instrument.symbol not in cm.symbols:
        return None, None

    peers = [s for s in cm.symbols if s != candidate_instrument.symbol]
    if not peers:
        return None, None

    best_peer = None
    best_corr = 0.0
    best_abs = -1.0
    for peer in peers:
        corr = cm.get(candidate_instrument.symbol, peer)
        if corr is None:
            continue
        if abs(corr) > best_abs:
            best_abs, best_corr, best_peer = abs(corr), corr, peer

    if best_peer is None:
        return None, None
    return float(best_corr), best_peer
