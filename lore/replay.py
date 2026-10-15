"""The replay line: Sauron's proving ground, read by code, on a card.

The newest ProvingVerdict per linked family and direction under the setup
memory's own filter (backtester/proving/memory.py: policy care, no filter,
not generated, 4h) and its ProvingTrade rows. Simulated history on past
bars, never live trading, and nothing about any account. No verdict, no
line. At most two lines a card.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

MAX_LINES = 2
TIMEFRAME = "4h"


def replay_lines(families, *, timeframe: str = TIMEFRAME,
                 max_lines: int = MAX_LINES) -> list:
    if not families:
        return []
    try:
        from backtester.models_proving import ProvingTrade, ProvingVerdict
        from backtester.proving.families import LONG, SHORT
    except Exception:  # noqa: BLE001 — the proving ground is optional here
        return []
    lines = []
    try:
        for family in families:
            for direction in (LONG, SHORT):
                verdict = (ProvingVerdict.objects
                           .filter(family=family, direction=direction,
                                   policy="care", filter="none",
                                   generated=False, timeframe=timeframe)
                           .order_by("-created_at").first())
                if verdict is None:
                    continue
                rs = list(ProvingTrade.objects.filter(verdict=verdict)
                          .values_list("r", flat=True))
                n = len(rs)
                if n:
                    avg = sum(rs) / n
                elif verdict.trades_n and verdict.expectancy is not None:
                    n, avg = verdict.trades_n, float(verdict.expectancy)
                else:
                    continue
                lines.append(
                    f"{family} {direction}, {verdict.asset_class}, "
                    f"{verdict.timeframe}: {avg:+.2f}R a trade over {n} "
                    f"trades (run {verdict.run_id}, "
                    f"{verdict.created_at:%Y-%m-%d}).")
                if len(lines) >= max_lines:
                    return lines
    except Exception as e:  # noqa: BLE001 — a card never fails on a replay
        logger.debug("[lore replay] unavailable: %s", type(e).__name__)
        return lines
    return lines
