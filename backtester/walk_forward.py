"""Rolling out-of-sample evaluation.

Each window runs a FRESH engine over a test slice it has never seen, so
every result is out-of-sample by construction — nothing is fitted, so
nothing can be overfitted. What the windows measure is whether an edge
holds across time rather than living in one favourable stretch.

WHAT THE PRECEDING WINDOW IS FOR
The bars before each test slice are warm-up, not training. `decide()` needs
`lookback` bars of history before it can say anything, and `engine_v2`
refuses a dataset shorter than `lookback + 10` outright:

    if common_index is None or len(common_index) < lookback + 10:
        return self._results()

This function used to compute `train_start`/`train_end`, report them in
every result dict, and then slice the TEST RANGE ONLY. On its own defaults
that meant:

    test_days=30 on 4h bars ->  180 bars, needs 210 -> nothing returned
    test_days=30 on 1d bars ->   30 bars, needs 210 -> nothing returned

Every window came back empty, and an empty window reads as "no trades in
this period" rather than "this harness cannot run". Where the count did
clear — an hourly series — the first `lookback` bars of each window still
produced no signal, because the indicators had no history behind them, so
trade counts were understated by a fixed slice of every window.

The fix is to feed the engine the preceding bars AND the test bars, then
score only what falls inside the test range. The lookback warms up on
history the trades are not counted from, which is what "out-of-sample"
was supposed to mean.

NOTE ON RESULTS PREDATING 2026-08-28
Discard them. `decide()`'s news leg read the last twelve hours of headlines
measured from the machine clock, so every historical bar was scored against
that day's news — lookahead, not noise. It takes `as_of` now and
`engine_v2` passes the bar's timestamp.
"""
from datetime import timedelta


def walk_forward(dataframes, engine_factory, warmup_days=180, test_days=30,
                 step_days=30, lookback=200):
    """Walk a rolling warm-up/test window across the dataset.

    engine_factory: callable returning a fresh engine per window, so no
                    state — and no fitted parameter — crosses a boundary.

    Returns one dict per window. `n_bars_scored` and `warmup_bars` are
    reported so a window that produced nothing can be told apart from one
    that could not run: the first is a result, the second is a gap.
    """
    if not dataframes:
        return []
    first_idx = min(df.index[0] for df in dataframes.values())
    last_idx = max(df.index[-1] for df in dataframes.values())

    results = []
    cursor = first_idx + timedelta(days=warmup_days)
    while cursor + timedelta(days=test_days) <= last_idx:
        warmup_start = cursor - timedelta(days=warmup_days)
        test_start = cursor
        test_end = cursor + timedelta(days=test_days)

        # Warm-up AND test. The engine needs `lookback` bars of history
        # before its first signal; handing it the test slice alone is what
        # made every window on a daily or 4h series come back empty.
        windows = {
            sym: df[(df.index >= warmup_start) & (df.index < test_end)]
            for sym, df in dataframes.items()
        }
        scored = {
            sym: df[(df.index >= test_start) & (df.index < test_end)]
            for sym, df in dataframes.items()
        }
        # A symbol whose window cannot clear the engine's own floor is
        # dropped by NAME below rather than silently shrinking the universe.
        usable = {s: d for s, d in windows.items() if len(d) >= lookback + 10}
        dropped = sorted(set(windows) - set(usable))
        if not usable:
            cursor += timedelta(days=step_days)
            results.append({
                "warmup_start": warmup_start, "test_start": test_start,
                "test_end": test_end, "metrics": None, "n_trades": 0,
                "n_bars_scored": 0, "warmup_bars": 0,
                "skipped": "no symbol had enough history to warm up",
                "dropped_symbols": dropped,
            })
            continue

        engine = engine_factory()
        result = engine.run(usable, lookback=lookback)

        # Only trades OPENED inside the test range count. A trade the
        # warm-up opened is history the window did not choose to take.
        trades = [t for t in (result.get("trades") or [])
                  if _in_range(t, test_start, test_end)]

        results.append({
            "warmup_start": warmup_start,
            "test_start": test_start,
            "test_end": test_end,
            "metrics": result.get("metrics"),
            "n_trades": len(trades),
            "trades": trades,
            "n_bars_scored": max((len(d) for d in scored.values()),
                                 default=0),
            "warmup_bars": max((len(d) for d in usable.values()), default=0)
                           - max((len(d) for d in scored.values()), default=0),
            "dropped_symbols": dropped,
        })
        cursor += timedelta(days=step_days)

    return results


def _in_range(trade, start, end) -> bool:
    """Was this trade opened inside the scored window?

    Tolerant about shape: engines on this platform have used `opened_at`,
    `entry_time` and `at` for the same field, and a walk-forward that
    silently counted none of them would report a clean zero.
    """
    for key in ("opened_at", "entry_time", "at", "time"):
        got = trade.get(key) if isinstance(trade, dict) else \
            getattr(trade, key, None)
        if got is None:
            continue
        try:
            return start <= got < end
        except TypeError:
            continue
    # No timestamp to judge by: counted, because dropping a trade for a
    # missing field would understate the window rather than admit the gap.
    return True
