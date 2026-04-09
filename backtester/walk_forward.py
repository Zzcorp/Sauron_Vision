"""Walk-forward backtest harness for parameter robustness."""
from datetime import timedelta


def walk_forward(dataframes, engine_factory, train_days=180, test_days=30, step_days=30):
    """Walk a rolling train/test window across the dataset.

    engine_factory: callable that returns a fresh BacktestEngineV2 each window.
                    (Lets you optimize weights on train, evaluate on test.)
    Returns a list of per-window result dicts.
    """
    if not dataframes:
        return []
    first_idx = min(df.index[0] for df in dataframes.values())
    last_idx = max(df.index[-1] for df in dataframes.values())

    results = []
    cursor = first_idx + timedelta(days=train_days)
    while cursor + timedelta(days=test_days) <= last_idx:
        train_start = cursor - timedelta(days=train_days)
        train_end = cursor
        test_start = cursor
        test_end = cursor + timedelta(days=test_days)

        test_dfs = {
            sym: df[(df.index >= test_start) & (df.index < test_end)]
            for sym, df in dataframes.items()
        }
        test_dfs = {k: v for k, v in test_dfs.items() if len(v) > 50}
        if not test_dfs:
            cursor += timedelta(days=step_days)
            continue

        engine = engine_factory()
        result = engine.run(test_dfs)
        results.append({
            "train_start": train_start, "train_end": train_end,
            "test_start": test_start, "test_end": test_end,
            "metrics": result["metrics"],
            "n_trades": len(result["trades"]),
        })
        cursor += timedelta(days=step_days)

    return results
