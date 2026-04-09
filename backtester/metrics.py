"""Backtest performance metrics."""
import math


def compute_metrics(trades, equity_curve, initial_capital):
    """Compute the full performance metric suite."""
    if not trades:
        return {"n_trades": 0, "note": "no trades"}

    pnls = [t.pnl for t in trades]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    n = len(trades)
    n_wins = len(wins)
    n_losses = len(losses)

    total_return = (sum(pnls) / initial_capital) * 100
    win_rate = n_wins / n if n else 0

    avg_win = sum(wins) / n_wins if n_wins else 0
    avg_loss = sum(losses) / n_losses if n_losses else 0

    profit_factor = (sum(wins) / abs(sum(losses))) if losses else float("inf")
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

    sharpe = _sharpe(equity_curve)
    sortino = _sortino(equity_curve)
    max_dd = _max_dd(equity_curve)
    calmar = (total_return / max_dd) if max_dd > 0 else float("inf")
    ulcer = _ulcer(equity_curve)
    longest_loss_streak = _longest_streak(pnls, lambda p: p < 0)
    longest_win_streak = _longest_streak(pnls, lambda p: p > 0)

    r_multiples = [t.r_multiple for t in trades if t.r_multiple is not None]
    avg_r = sum(r_multiples) / len(r_multiples) if r_multiples else 0

    return {
        "n_trades": n,
        "n_wins": n_wins,
        "n_losses": n_losses,
        "win_rate": round(win_rate, 4),
        "total_return_pct": round(total_return, 4),
        "avg_win": round(avg_win, 4),
        "avg_loss": round(avg_loss, 4),
        "profit_factor": round(profit_factor, 4) if profit_factor != float("inf") else None,
        "expectancy_per_trade": round(expectancy, 4),
        "expectancy_R": round(avg_r, 3),
        "sharpe": round(sharpe, 4) if sharpe is not None else None,
        "sortino": round(sortino, 4) if sortino is not None else None,
        "max_drawdown_pct": round(max_dd, 4),
        "calmar": round(calmar, 4) if calmar != float("inf") else None,
        "ulcer_index": round(ulcer, 4),
        "longest_win_streak": longest_win_streak,
        "longest_loss_streak": longest_loss_streak,
    }


def _equity_returns(equity_curve):
    if len(equity_curve) < 2:
        return []
    returns = []
    for i in range(1, len(equity_curve)):
        prev = equity_curve[i - 1]["equity"]
        cur = equity_curve[i]["equity"]
        if prev > 0:
            returns.append((cur - prev) / prev)
    return returns


def _sharpe(equity_curve, periods_per_year=365 * 6):
    """Annualized Sharpe (assumes 4h bars by default: 6 per day, 365 days)."""
    rets = _equity_returns(equity_curve)
    if len(rets) < 10:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / len(rets)
    std = math.sqrt(var)
    if std == 0:
        return None
    return (mean / std) * math.sqrt(periods_per_year)


def _sortino(equity_curve, periods_per_year=365 * 6):
    rets = _equity_returns(equity_curve)
    if len(rets) < 10:
        return None
    mean = sum(rets) / len(rets)
    downside = [r for r in rets if r < 0]
    if not downside:
        return None
    dvar = sum(r ** 2 for r in downside) / len(downside)
    dstd = math.sqrt(dvar)
    if dstd == 0:
        return None
    return (mean / dstd) * math.sqrt(periods_per_year)


def _max_dd(equity_curve):
    if not equity_curve:
        return 0
    peak = equity_curve[0]["equity"]
    max_dd = 0
    for p in equity_curve:
        if p["equity"] > peak:
            peak = p["equity"]
        dd = (peak - p["equity"]) / peak * 100 if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _ulcer(equity_curve):
    if not equity_curve:
        return 0
    peak = equity_curve[0]["equity"]
    sq_dd = []
    for p in equity_curve:
        if p["equity"] > peak:
            peak = p["equity"]
        dd_pct = (peak - p["equity"]) / peak * 100 if peak > 0 else 0
        sq_dd.append(dd_pct ** 2)
    return math.sqrt(sum(sq_dd) / len(sq_dd))


def _longest_streak(values, predicate):
    longest = 0
    current = 0
    for v in values:
        if predicate(v):
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest
