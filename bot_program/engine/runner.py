"""Main bot loop. Call `run_bot_tick(user_id)` from Celery / cron.

Phase-4 update: per-symbol broker routing. Crypto symbols route to Binance,
forex to OANDA, stocks to Alpaca. Paper mode (or missing credentials) routes
to PaperTrader. See `bot_program.engine.broker_router`.
"""
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
from .broker_router import client_for_symbol, broker_name_for_symbol

log = logging.getLogger(__name__)

def _client_for(user, cfg=None):
    """Legacy account-wide client selector — used for the position-management
    pass that touches existing BotTrades (which are still crypto-only today)."""
    if cfg is not None and getattr(cfg, "mode", "paper") == "paper":
        log.info("[PAPER] Paper trading mode active for %s", user.username)
        return PaperTrader(cfg)

    try:
        acct: BinanceAccount = user.binance_account
        k, s = acct.get_credentials()
        testnet = acct.testnet
        if testnet:
            log.info("[PAPER] Testnet mode — using PaperTrader for %s", user.username)
            return PaperTrader(cfg)
    except BinanceAccount.DoesNotExist:
        log.warning("[PAPER] No BinanceAccount for %s — using PaperTrader", user.username)
        return PaperTrader(cfg)

    if cfg is not None and getattr(cfg, "market_type", "spot") == "futures":
        return BinanceFuturesClient(k, s, testnet=False)
    return BinanceClient(k, s, testnet=False)

def _parse_klines(raw: list[list]) -> list[list]:
    # [openTime, open, high, low, close, volume, closeTime, ...]
    return [[float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])] for r in raw]


def _apply_risk_gate(user, symbol: str, qty: float, price: float) -> tuple[float, str]:
    """Apply the Phase-2 risk gate (correlation + decay) on top of the bot's qty.

    Phase-3: when the `feature_ai_pretrade_gate` PlatformComponent is enabled,
    the gate also calls Claude's PreTradeSanityAgent. Off by default — admin
    toggles it from the dashboard. Costs Claude tokens and adds 1–3s latency.

    Best-effort: if anything goes wrong (instrument missing, portfolio init,
    etc.) we keep the original qty and log a warning. The gate must never
    halt trading on its own malfunction — the in-place RiskManager already
    enforces hard limits.

    Returns (new_qty, reason).
    """
    try:
        from instruments.models import Instrument
        from portfolio.services import get_or_create_default_portfolio
        from portfolio.risk_gate import evaluate_proposed_trade
        from core.platform_control import is_component_enabled

        instrument = Instrument.objects.filter(symbol=symbol).first()
        if instrument is None:
            return qty, "no Instrument record for symbol — gate skipped"

        portfolio = get_or_create_default_portfolio(user=user)
        use_ai = is_component_enabled("feature_ai_pretrade_gate")
        gate = evaluate_proposed_trade(
            portfolio, instrument,
            intended_size_usd=qty * price,
            use_ai_check=use_ai,
            ai_context=None,  # admin-supplied context could plug in here
        )
        scale = float(gate.get("scale", 1.0))
        ai_tag = " ai=on" if use_ai else ""
        if scale >= 0.999:
            return qty, f"gate ok (scale=1.0{ai_tag})"
        return qty * scale, f"gate scale={scale:.2f}{ai_tag}: {' / '.join(gate.get('reasons', []))}"
    except Exception as e:
        log.warning("[risk_gate] evaluation failed for %s: %s — keeping intended qty", symbol, e)
        return qty, f"gate error: {e}"

def run_bot_tick(user_id: int):
    from django.contrib.auth.models import User
    try:
        user = User.objects.get(id=user_id)
        cfg = user.bot_config
    except Exception as e:
        log.warning("no config for user %s: %s", user_id, e); return

    if not cfg.enabled:
        log.info("bot disabled for %s", user.username); return

    rm = RiskManager(cfg)
    weights = cfg.normalized_weights()

    # 1. Manage existing positions (SL/TP) — Phase-4: route per-symbol so a
    #    forex BotTrade's SL/TP check uses OANDA, a stock BotTrade uses Alpaca.
    for t in BotTrade.objects.filter(config=cfg, status="OPEN"):
        try:
            sym_client = client_for_symbol(user, t.symbol, cfg)
            tk = sym_client.ticker(t.symbol)
            price = Decimal(tk["lastPrice"])
            hit_sl = (t.side == "BUY" and price <= t.stop_loss) or (t.side == "SELL" and price >= t.stop_loss)
            hit_tp = (t.side == "BUY" and price >= t.take_profit) or (t.side == "SELL" and price <= t.take_profit)
            if hit_sl or hit_tp:
                _close(t, price, sym_client, "TP" if hit_tp else "SL")
        except Exception as e:
            log.warning("manage fail %s: %s", t.symbol, e)

    # 2. Scan universe for new entries
    ok, reason = rm.can_open_new()
    if not ok:
        log.info("no new entries: %s", reason); return

    for symbol in cfg.symbols:
        try:
            # Phase-4: route per-symbol so forex symbols hit OANDA, stocks hit
            # Alpaca, etc. Falls back to PaperTrader when creds are missing.
            sym_client = client_for_symbol(user, symbol, cfg)
            broker_name = broker_name_for_symbol(user, symbol, cfg)
            raw = sym_client.klines(symbol, interval=cfg.timeframe, limit=200)
            ohlcv = _parse_klines(raw)
            ob = sym_client.order_book(symbol, limit=50)
            d = decide(symbol, ohlcv, ob, weights,
                       entry_min=cfg.entry_score_min, exit_max=cfg.exit_score_max)
            log.info("[%s] %s broker=%s score=%.2f dir=%s",
                     user.username, symbol, broker_name, d.score, d.direction)

            if d.direction == "HOLD": continue
            # Skip duplicates
            if BotTrade.objects.filter(config=cfg, symbol=symbol, status="OPEN").exists():
                continue

            price = float(ohlcv[-1][3])
            qty = rm.position_size(price)
            if qty <= 0: continue

            qty, gate_reason = _apply_risk_gate(user, symbol, qty, price)
            log.info("[%s] %s gate: %s", user.username, symbol, gate_reason)
            if qty <= 0: continue

            sl = price * (1 - d.sl_pct/100) if d.direction == "BUY" else price * (1 + d.sl_pct/100)
            tp = price * (1 + d.tp_pct/100) if d.direction == "BUY" else price * (1 - d.tp_pct/100)

            paper = (cfg.mode == "paper")
            order_id = ""
            if not paper:
                # Money-safety: live mode + router fell back to PaperTrader
                # (dead/missing creds) — refuse rather than record a paper
                # fill as a live trade.
                if isinstance(sym_client, PaperTrader):
                    log.error("LIVE bot for %s fell back to PaperTrader on %s "
                              "(missing/invalid broker credentials?) — skipping",
                              user.username, symbol)
                    continue
                try:
                    if cfg.market_type == "futures" and hasattr(sym_client, "ensure_config"):
                        sym_client.ensure_config(symbol, cfg.leverage, cfg.margin_mode)
                    res = sym_client.market_order(symbol, d.direction, qty)
                    order_id = str(res.get("orderId", ""))
                except Exception as e:
                    log.error("live order failed %s (%s): %s", symbol, broker_name, e)
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

def _close(trade: BotTrade, price: Decimal, client, reason: str):
    """Close a BotTrade. The `client` is the broker that owns the symbol —
    crypto uses Binance(Futures)Client, forex uses OANDATrader, stocks use
    AlpacaTrader. Duck-typed: only `market_order` is needed."""
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
            if trade.config.market_type == "futures" and hasattr(client, "ensure_config"):
                # `reduce_only` is a Binance-Futures-only kwarg.
                kwargs["reduce_only"] = True
            client.market_order(trade.symbol, close_side, float(trade.qty), **kwargs)
        except Exception as e:
            log.error("close order fail: %s", e)
    trade.save()
