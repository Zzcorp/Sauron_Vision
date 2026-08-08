"""Phase 1 → Phase 2 bridge: derive Kelly inputs from realized signal history.

The existing `PositionSizer.kelly_criterion` takes win_rate / avg_win / avg_loss
as caller-supplied parameters — totally disconnected from what the system
actually achieved. Phase 1 added `Signal.realized_r`; this module turns that
history into honest Kelly inputs per rule_name.

Usage:
    inputs = kelly_inputs_for_rule("sv_sample_forex_breakout_hc", days=180)
    # → {"win_rate": 0.62, "avg_win_pct": 1.85, "avg_loss_pct": 1.0, "n": 24, ...}

    sizing = PositionSizer(portfolio).kelly_criterion(
        win_rate=inputs["win_rate"],
        avg_win_pct=inputs["avg_win_pct"],
        avg_loss_pct=inputs["avg_loss_pct"],
    )

R-multiples (-1, +RR) are used directly as the win/loss magnitudes — units of R.
"""
from datetime import timedelta
from django.utils import timezone


# Below this sample size, fall back to a flat conservative Kelly.
MIN_KELLY_SAMPLE = 10
FALLBACK = {
    "win_rate": 0.5, "avg_win_pct": 1.0, "avg_loss_pct": 1.0,
    "n": 0, "is_empirical": False,
    "source": "fallback (insufficient history)",
}


def kelly_inputs_for_rule(rule_name: str, days: int = 180) -> dict:
    """Derive Kelly inputs from `Signal.realized_r` for the given rule.

    Returns dict with keys: win_rate, avg_win_pct, avg_loss_pct, n, is_empirical, source.
    `avg_win_pct` and `avg_loss_pct` are in R-units (so 1.0 == 1R risked).
    """
    from signals.models import Signal

    cutoff = timezone.now() - timedelta(days=days)
    qs = Signal.objects.filter(
        rule_name=rule_name, is_active=False,
        realized_r__isnull=False, expired_at__gte=cutoff,
    )
    rs = list(qs.values_list("realized_r", flat=True))

    if len(rs) < MIN_KELLY_SAMPLE:
        return {**FALLBACK, "n": len(rs),
                "source": f"fallback (n={len(rs)} < min {MIN_KELLY_SAMPLE})"}

    wins = [r for r in rs if r > 0]
    losses = [abs(r) for r in rs if r < 0]
    n_total = len(wins) + len(losses)
    if n_total == 0:
        return {**FALLBACK, "n": 0, "source": "fallback (all zero realized_r)"}

    win_rate = len(wins) / n_total
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 1.0
    return {
        "win_rate": round(win_rate, 4),
        "avg_win_pct": round(avg_win, 4),
        "avg_loss_pct": round(avg_loss, 4),
        "n": n_total,
        "is_empirical": True,
        "source": f"realized_r over {days}d (n={n_total})",
    }


def kelly_size_for_rule(portfolio, rule_name: str, days: int = 180) -> dict:
    """End-to-end: derive Kelly inputs from history, then ask PositionSizer for the recommendation.

    Returns the PositionSizer.kelly_criterion output augmented with the inputs and source.
    """
    from portfolio.position_sizing import PositionSizer

    inputs = kelly_inputs_for_rule(rule_name, days=days)
    sizer = PositionSizer(portfolio)
    sizing = sizer.kelly_criterion(
        win_rate=inputs["win_rate"],
        avg_win_pct=inputs["avg_win_pct"],
        avg_loss_pct=inputs["avg_loss_pct"],
    )
    return {**sizing, "inputs": inputs}
