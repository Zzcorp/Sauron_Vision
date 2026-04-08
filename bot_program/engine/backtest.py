"""Scenario backtest runner — replays historical klines through the strategy."""
from __future__ import annotations
from decimal import Decimal
from datetime import datetime
from django.utils import timezone
from .binance_client import BinanceClient
from .strategy import decide

def run_scenario(scenario):
    from ..models import BotScenario, BotConfig
    cfg: BotConfig = scenario.user.bot_config
    params = scenario.params or {}
    # Apply overrides to a dict (don't persist)
    weights = cfg.normalized_weights()
    for k, v in params.items():
        if k in weights: weights[k] = float(v)
    entry_min = float(params.get("entry_score_min", cfg.entry_score_min))
    sl_pct = float(params.get("stop_loss_pct", cfg.stop_loss_pct))
    tp_pct = float(params.get("take_profit_pct", cfg.take_profit_pct))
    pos_pct = float(params.get("position_size_pct", cfg.position_size_pct))

    client = BinanceClient(None, None, testnet=True)
    equity = float(scenario.initial_capital)
    peak = equity
    max_dd = 0.0
    curve = []
    trades = []
    wins = 0
    n = 0

    for symbol in scenario.symbols:
        try:
            raw = client.klines(symbol, interval="1h", limit=1000)
        except Exception as e:
            continue
        ohlcv = [[float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in raw]

        position = None  # dict
        for i in range(60, len(ohlcv)):
            window = ohlcv[:i+1]
            d = decide(symbol, window, {"bids":[], "asks":[]}, weights, entry_min, entry_min*0.5,
                       atr_mult_sl=sl_pct/1.0, atr_mult_tp=tp_pct/1.0)
            price = window[-1][3]

            if position:
                # Check SL/TP
                hit_sl = (position["side"]=="BUY" and price <= position["sl"]) or \
                         (position["side"]=="SELL" and price >= position["sl"])
                hit_tp = (position["side"]=="BUY" and price >= position["tp"]) or \
                         (position["side"]=="SELL" and price <= position["tp"])
                if hit_sl or hit_tp:
                    pnl = (price - position["entry"]) * position["qty"] if position["side"]=="BUY" \
                          else (position["entry"] - price) * position["qty"]
                    equity += pnl
                    n += 1
                    if pnl > 0: wins += 1
                    trades.append({"symbol":symbol, "side":position["side"],
                                   "entry":position["entry"], "exit":price,
                                   "pnl":round(pnl,2), "reason":"TP" if hit_tp else "SL"})
                    position = None
            else:
                if d.direction in ("BUY","SELL"):
                    dollars = equity * (pos_pct/100)
                    qty = dollars / price if price else 0
                    sl = price*(1-sl_pct/100) if d.direction=="BUY" else price*(1+sl_pct/100)
                    tp = price*(1+tp_pct/100) if d.direction=="BUY" else price*(1-tp_pct/100)
                    position = {"side":d.direction, "entry":price, "qty":qty, "sl":sl, "tp":tp}

            peak = max(peak, equity)
            dd = (peak - equity) / peak * 100 if peak else 0
            max_dd = max(max_dd, dd)
            curve.append(round(equity, 2))

    scenario.final_equity = Decimal(str(round(equity, 2)))
    scenario.total_return_pct = round((equity / float(scenario.initial_capital) - 1) * 100, 2) if scenario.initial_capital else 0
    scenario.max_drawdown_pct = round(max_dd, 2)
    scenario.win_rate = round((wins / n * 100) if n else 0, 2)
    scenario.num_trades = n
    scenario.equity_curve = curve[-500:]
    scenario.trades_log = trades[-200:]
    # Very rough Sharpe
    if len(curve) > 2:
        import statistics
        returns = [(curve[i]/curve[i-1]-1) for i in range(1, len(curve)) if curve[i-1]]
        if returns and statistics.pstdev(returns):
            scenario.sharpe = round(statistics.mean(returns)/statistics.pstdev(returns) * (252**0.5), 2)
    scenario.finished_at = timezone.now()
    scenario.save()
    return scenario
