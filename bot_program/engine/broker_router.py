"""Broker routing — Phase-4.

Given a user + symbol, return the right broker client. The router falls back to
PaperTrader whenever:
  - the bot config is in paper mode
  - the symbol's broker has no credentials configured
  - the broker's testnet/practice/paper switch is on

This is the single integration point for multi-asset execution. Adding a new
broker means: build the adapter, add a credential model, register the routing
case here.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)


# ── helpers ─────────────────────────────────────────────────────────────────

def _instrument_for(symbol: str):
    """Look up the Instrument record for `symbol`, or None."""
    from instruments.models import Instrument
    return Instrument.objects.filter(symbol=symbol).first()


def _broker_for_asset_class(asset_class: str) -> str:
    """Map an asset_class to the broker name we route to.

    Returns one of: "binance", "binance_futures", "oanda", "alpaca", "paper".
    """
    if asset_class == "crypto":
        return "binance"      # BinanceClient (spot) — futures handled separately
    if asset_class == "forex":
        return "oanda"
    if asset_class in ("stock", "etf", "index"):
        return "alpaca"
    if asset_class == "commodity":
        # Commodities reach price feeds via Twelve Data / FMP; no live execution
        # broker is wired today. Fall back to paper.
        return "paper"
    return "paper"


def _paper_client(cfg) -> "PaperTrader":
    from .paper_trader import PaperTrader
    return PaperTrader(cfg)


def _ibkr_client_for(user, cfg):
    """Return an IBKRTrader instance for `user`. Falls back to paper if IBKR
    is unavailable (no creds, no `ib_insync`, or ping fails)."""
    try:
        from bot_program.models import IBKRAccount
        acct = getattr(user, "ibkr_account", None)
        if acct is None:
            log.info("[router] no IBKRAccount on user — paper")
            return _paper_client(cfg)
        from .ibkr_client import IBKRTrader, is_ibkr_available
        if not is_ibkr_available():
            log.info("[router] ib_insync not installed — paper")
            return _paper_client(cfg)
        account_id = acct.get_account_id() or ""
        return IBKRTrader(
            host=acct.host, port=acct.port, client_id=acct.client_id,
            account_id=account_id, paper=acct.paper,
        )
    except Exception as e:
        log.warning("[router] IBKR client construction failed (%s) — paper", e)
        return _paper_client(cfg)


def _ibkr_overrides(user, asset_class: str) -> bool:
    """True iff the user has an IBKRAccount that is_primary_for(asset_class)."""
    try:
        acct = getattr(user, "ibkr_account", None)
        return bool(acct and acct.is_primary_for(asset_class))
    except Exception:
        return False


# ── public ─────────────────────────────────────────────────────────────────

def client_for_symbol(user, symbol: str, cfg=None):
    """Return a broker client capable of trading `symbol` for `user`.

    Always returns *some* client — falls back to PaperTrader rather than None,
    so callers don't need to null-check on every loop. PaperTrader honours the
    same duck-typed interface as the live brokers.
    """
    # Paper mode short-circuits — never reach live brokers.
    if cfg is not None and getattr(cfg, "mode", "paper") == "paper":
        return _paper_client(cfg)

    inst = _instrument_for(symbol)
    asset_class = (inst.asset_class if inst else "crypto")  # default to crypto for legacy bot symbols

    # IBKR opt-in override: when the user has flipped is_primary_for_<asset_class>
    # on their IBKRAccount, route through IBKR instead of the default broker.
    # Options + CFDs always go through IBKR by default — no other wired broker
    # handles either at scale.
    if asset_class in ("options", "cfd") or _ibkr_overrides(user, asset_class):
        return _ibkr_client_for(user, cfg)

    broker = _broker_for_asset_class(asset_class)

    # ── crypto via Binance (spot or futures) ───────────────────────────────
    if broker == "binance":
        try:
            from bot_program.models import BinanceAccount
            acct: BinanceAccount = user.binance_account
            k, s = acct.get_credentials()
            if not (k and s):
                log.info("[router] %s: no Binance creds — paper", symbol)
                return _paper_client(cfg)
            if acct.testnet:
                log.info("[router] %s: Binance testnet — paper", symbol)
                return _paper_client(cfg)
            if cfg is not None and getattr(cfg, "market_type", "spot") == "futures":
                from .binance_futures_client import BinanceFuturesClient
                return BinanceFuturesClient(k, s, testnet=False)
            from .binance_client import BinanceClient
            return BinanceClient(k, s, testnet=False)
        except Exception as e:
            log.warning("[router] %s: BinanceAccount unavailable (%s) — paper", symbol, e)
            return _paper_client(cfg)

    # ── forex via OANDA ───────────────────────────────────────────────────
    if broker == "oanda":
        try:
            from bot_program.models import OANDAAccount
            acct: OANDAAccount = user.oanda_account
            k, account_id = acct.get_credentials()
            if not (k and account_id):
                log.info("[router] %s: no OANDA creds — paper", symbol)
                return _paper_client(cfg)
            if acct.practice:
                # Practice IS live API on OANDA's demo endpoint — we still route
                # there since orders behave realistically. If the bot is in
                # live mode but OANDA is in practice, we honour OANDA practice.
                from .oanda_client import OANDATrader
                return OANDATrader(k, account_id, env="practice")
            from .oanda_client import OANDATrader
            return OANDATrader(k, account_id, env="live")
        except Exception as e:
            log.warning("[router] %s: OANDAAccount unavailable (%s) — paper", symbol, e)
            return _paper_client(cfg)

    # ── stocks/etfs via Alpaca ─────────────────────────────────────────────
    if broker == "alpaca":
        try:
            from bot_program.models import AlpacaAccount
            acct: AlpacaAccount = user.alpaca_account
            k, s = acct.get_credentials()
            if not (k and s):
                log.info("[router] %s: no Alpaca creds — paper", symbol)
                return _paper_client(cfg)
            from .alpaca_client import AlpacaTrader
            return AlpacaTrader(k, s, env="paper" if acct.paper else "live")
        except Exception as e:
            log.warning("[router] %s: AlpacaAccount unavailable (%s) — paper", symbol, e)
            return _paper_client(cfg)

    # ── default: paper ─────────────────────────────────────────────────────
    return _paper_client(cfg)


def broker_name_for_symbol(user, symbol: str, cfg=None) -> str:
    """Human-readable name of the broker that *would* be selected — for logs
    and the dashboard, without instantiating the client."""
    if cfg is not None and getattr(cfg, "mode", "paper") == "paper":
        return "paper"
    inst = _instrument_for(symbol)
    if inst is None:
        return "paper"
    asset_class = inst.asset_class
    if asset_class in ("options", "cfd") or _ibkr_overrides(user, asset_class):
        return "ibkr"
    return _broker_for_asset_class(asset_class)
