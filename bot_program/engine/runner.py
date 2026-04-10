"""Main bot loop. Call `run_bot_tick(user_id)` from Celery / cron."""
from __future__ import annotations
import logging
from decimal import Decimal
from django.utils import timezone
from ..models import BotConfig, BotTrade, BinanceAccount
from .binance_client import BinanceClient
from .binance_futures_client import BinanceFuturesClient
from .paper_trader import PaperTrader
from .strategy import decide
from .risk import RiskManager

log = logging.getLogger(__name__)

def _client_for(user, cfg=None):
    # Paper mode: use PaperTrader regardless of account state
    if cfg is not None and getattr(cfg, "mode", "paper") == "paper":
        log.info("[PAPER] Paper trading mode active for %s", user.username)
        return PaperTrader(cfg)

    try:
        acct: BinanceAccount = user.binance_account
        k, s = acct.get_credentials()
        testnet = acct.testnet
        # Testnet account also gets PaperTrader
        if testnet:
            log.info("[PAPER] Testnet mode — using PaperTrader for %s", user.username)
            return PaperTrader(cfg)
    except BinanceAccount.DoesNotExist:
        # No account configured — fall back to paper trading
        log.warning("[PAPER] No BinanceAccount for %s — using PaperTrader", user.username)
        return PaperTrader(cfg)

    if cfg is not None and getattr(cfg, "market_type", "spot") == "futures":
        return BinanceFuturesClient(k, s, testnet=False)
    return BinanceClient(k, s, testnet=False)

def _parse_klines(raw: list[list]) -> list[list]:
    # [openTime, open, high, low, close, volume, closeTime, ...]
    return [[float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in raw]

def run_bot_tick(user_id: int):
    from django.contrib.auth.models import User
    try:
        user = User.objects.get(id=user_id)
        cfg = user.bot_config
    except Exception as e:
        log.warning("no config for user %s: %s", user_id, e); return

    if not cfg.enabled:
        log.info("bot disabled for %s", user.username); return

    client = _client_for(user, cfg)
    if not client.ping():
        log.warning("binance unreachable"); return

    rm = RiskManager(cfg)
    weights = cfg.normalized_weights()

    # 1. Manage existing positions (SL/TP)
    for t in BotTrade.objects.filter(config=cfg, status="OPEN"):
        try:
            tk = client.ticker(t.symbol)
            price = Decimal(tk["lastPrice"])
            hit_sl = (t.side == "BUY" and price <= t.stop_loss) or (t.side == "SELL" and price >= t.stop_loss)
            hit_tp = (t.side == "BUY" and price >= t.take_profit) or (t.side == "SELL" and price <= t.take_profit)
            if hit_sl or hit_tp:
                _close(t, price, client, "TP" if hit_tp else "SL")
        except Exception as e:
            log.warning("manage fail %s: %s", t.symbol, e)

    # 2. Scan universe for new entries
    ok, reason = rm.can_open_new()
    if not ok:
        log.info("no new entries: %s", reason); return

    for symbol in cfg.symbols:
        try:
            raw = client.klines(symbol, interval=cfg.timeframe, limit=200)
            ohlcv = _parse_klines(raw)
            ob = client.order_book(symbol, limit=50)
            d = decide(symbol, ohlcv, ob, weights,
                       entry_min=cfg.entry_score_min, exit_max=cfg.exit_score_max)
            log.info("[%s] %s score=%.2f dir=%s", user.username, symbol, d.score, d.direction)

            if d.direction == "HOLD": continue
            # Skip duplicates
            if BotTrade.objects.filter(config=cfg, symbol=symbol, status="OPEN").exists():
                continue

            price = float(ohlcv[-1][3])
            qty = rm.position_size(price)
            if qty <= 0: continue

            sl = price * (1 - d.sl_pct/100) if d.direction == "BUY" else price * (1 + d.sl_pct/100)
            tp = price * (1 + d.tp_pct/100) if d.direction == "BUY" else price * (1 - d.tp_pct/100)

            paper = (cfg.mode == "paper")
            order_id = ""
            if not paper:
                try:
                    if cfg.market_type == "futures" and hasattr(client, "ensure_config"):
                        client.ensure_config(symbol, cfg.leverage, cfg.margin_mode)
                    res = client.market_order(symbol, d.direction, qty)
                    order_id = str(res.get("orderId", ""))
                except Exception as e:
                    log.error("live order failed %s: %s", symbol, e)
                    continue

            BotTrade.objects.create(
                config=cfg, symbol=symbol, side=d.direction,
                qty=Decimal(str(qty)), entry_price=Decimal(str(price)),
                stop_loss=Decimal(str(sl)), take_profit=Decimal(str(tp)),
                composite_score=d.score, reason=" · ".join(d.reasons),
                paper=paper, binance_order_id=order_id,
            )

            ok, reason = rm.can_open_new()
            if not ok: break
        except Exception as e:
            log.exception("scan fail %s: %s", symbol, e)

def _close(trade: BotTrade, price: Decimal, client: BinanceClient, reason: str):
    pnl = (price - trade.entry_price) * trade.qty if trade.side == "BUY" \
          else (trade.entry_price - price) * trade.qty
    trade.exit_price = price
    trade.pnl_usdt = pnl
    trade.status = "CLOSED"
    trade.closed_at = timezone.now()
    trade.reason = (trade.reason + f" | closed:{reason}").strip()
    if not trade.paper:
        try:
            close_side = "SELL" if trade.side == "BUY" else "BUY"
            kwargs = {}
            if trade.config.market_type == "futures":
                kwargs["reduce_only"] = True
            client.market_order(trade.symbol, close_side, float(trade.qty), **kwargs)
        except Exception as e: log.error("close order fail: %s", e)
    trade.save()
