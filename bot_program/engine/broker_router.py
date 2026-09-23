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


# Stamped on a PaperTrader handed back because the exclusive IBKR trading
# session was held by ANOTHER process — not because credentials are missing.
# Nothing reached the broker, so a caller with a bounded retry budget must
# not spend one, and no message may tell the operator their connection is
# broken. `session_busy()` is how a caller asks.
SESSION_BUSY = "ibkr_session_busy"


def session_busy(client) -> bool:
    """True when this client is a stand-in for a session another process
    holds — i.e. nothing was sent and nothing is wrong with the broker."""
    return getattr(client, "_sv_unavailable", "") == SESSION_BUSY


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


def _ibkr_client_for(user, cfg, purpose: str = "trade"):
    """The IBKRTrader this process shares for `user` and `purpose`.

    Falls back to paper when IBKR is unavailable: no IBKRAccount, no
    `ib_insync`, no stored account id, or no free clientId slot. The
    session itself comes from ibkr_sessions — one per process and purpose,
    reused across ticks — never a fresh socket per call.
    """
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
        if not account_id:
            # No credential — the same refusal the Binance and OANDA
            # branches make above, and the one that makes the HQ
            # "disconnect" button mean something. Clearing account_id_enc
            # was NOT enough on its own: this function went on returning a
            # live IBKRTrader aimed at the same host:port, the routing
            # overrides survived the disconnect, and options and CFDs reach
            # here unconditionally whatever those overrides say. An empty
            # account id does not stop an order either — TWS falls back to
            # whichever account the session is logged into, which on a live
            # socket is the funded one.
            log.info("[router] IBKR account has no id (disconnected?) — paper")
            return _paper_client(cfg)
        from .ibkr_sessions import acquire_trader
        trader = acquire_trader(acct.host, acct.port, acct.client_id, purpose,
                                account_id=account_id, paper=acct.paper)
        if trader is None:
            # BUSY, not misconfigured. Another process holds the exclusive
            # trading session; the broker itself is fine and nothing was
            # asked of it. The distinction matters downstream: a close that
            # was never ATTEMPTED must not count toward an abandon budget,
            # and the operator must not be told their credentials are
            # broken. The marker rides on the PaperTrader because that is
            # what every caller receives.
            log.error("[router] the IBKR %s session is held by another "
                      "process — paper (nothing was sent)", purpose)
            paper = _paper_client(cfg)
            try:
                paper._sv_unavailable = SESSION_BUSY
            except Exception:  # noqa: BLE001
                pass
            return paper
        return trader
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

#: The order the three flagged venues are consulted in. One tuple, read by
#: the router, by capital_truth.broker_backed and by the pages, so "which
#: broker carries this class" has exactly one answer everywhere.
VENUE_PRECEDENCE = ("saxo", "etoro", "ibkr")


def _saxo_overrides(user, asset_class: str) -> bool:
    """True iff the user has a SaxoAccount that is_primary_for(asset_class).

    Checked FIRST (2026-09-19): Saxo holds the real listing where eToro
    holds a CFD on it, so when both are flagged for a class Saxo carries
    it. A keyed row with no flag carries nothing.
    """
    try:
        acct = getattr(user, "saxo_account", None)
        return bool(acct and acct.is_primary_for(asset_class))
    except Exception:
        return False


def _saxo_client_for(user, cfg, symbol: str):
    """SaxoTrader from the user's row, or PaperTrader when it cannot be.

    Same posture as the eToro branch: no application, no live session, or
    an unreadable row means paper — and a live-mode config handed a
    PaperTrader is refused by asset_engine, loudly, rather than trading
    somewhere the operator did not choose.

    The ROW decides the world, not the config: a SIM application serves a
    live config with SIM, because the keys are what Saxo authenticates. That
    rule is kept on purpose — refusing it would mean no order can ever reach
    Saxo SIM, and the facts only SIM can settle would stay unsettled until
    real money was on the line — but it is announced, here and at the entry,
    because the row it books says paper=False either way.
    """
    try:
        from bot_program.models import SaxoAccount
        acct: SaxoAccount = user.saxo_account
        if not acct.get_credentials()[0]:
            log.info("[router] %s: no Saxo application — paper", symbol)
            return _paper_client(cfg)
        if not acct.session_alive():
            log.warning("[router] %s: Saxo session not alive — paper. Sign "
                        "in again at /brokers/", symbol)
            return _paper_client(cfg)
        if acct.sim and getattr(cfg, "mode", "") == "live":
            log.warning("[router] %s: live config %s is placing on the Saxo "
                        "SIMULATOR — the fill is a rehearsal and the row is "
                        "booked as live history. preflight_live blocks on "
                        "this; untick SIM on /brokers/ for real orders",
                        symbol, getattr(cfg, "id", "?"))
        from .saxo_client import SaxoTrader
        return SaxoTrader(acct)
    except Exception as e:
        log.warning("[router] %s: SaxoAccount unavailable (%s) — paper",
                    symbol, e)
        return _paper_client(cfg)


def _etoro_overrides(user, asset_class: str) -> bool:
    """True iff the user has an EtoroAccount that is_primary_for(asset_class).

    Checked BEFORE _ibkr_overrides on purpose (2026-09-17): when both are
    flagged for a class, eToro carries it. Retiring IBKR is the stated
    direction, and the router is where that direction becomes a fact.
    """
    try:
        acct = getattr(user, "etoro_account", None)
        return bool(acct and acct.is_primary_for(asset_class))
    except Exception:
        return False


def _etoro_client_for(user, cfg, symbol: str):
    """EtoroTrader from the user's row, or PaperTrader when it cannot be.

    Same posture as the OANDA branch: no credentials means paper, and a
    live-mode config gets a PaperTrader back — which asset_engine refuses
    to trade against, loudly. A row flagged Demo routes to eToro's demo
    world even for a live config: the row's Demo flag decides the world,
    not the config — and not the keys either. Measured 2026-09-23: one
    eToro pair answered 200 on BOTH worlds, so the flag alone picks the
    `demo/` URL segment (etoro_client._seg), and the same pair trades real
    money the moment Demo is unticked on /brokers/ (a guarded save).
    """
    try:
        from bot_program.models import EtoroAccount
        acct: EtoroAccount = user.etoro_account
        k, u = acct.get_credentials()
        if not (k and u):
            log.info("[router] %s: no eToro creds — paper", symbol)
            return _paper_client(cfg)
        if acct.demo and getattr(cfg, "mode", "") == "live":
            log.warning("[router] %s: live config %s is placing on the eToro "
                        "DEMO portfolio — the fill is a rehearsal and the row "
                        "is booked as live history. preflight_live blocks on "
                        "this; unticking Demo on /brokers/ sends the SAME "
                        "pair to the live world and the next order is real "
                        "money",
                        symbol, getattr(cfg, "id", "?"))
        from .etoro_client import EtoroTrader
        return EtoroTrader(k, u, env="demo" if acct.demo else "live")
    except Exception as e:
        log.warning("[router] %s: EtoroAccount unavailable (%s) — paper",
                    symbol, e)
        return _paper_client(cfg)


def client_for_symbol(user, symbol: str, cfg=None, purpose: str = "trade"):
    """Return a broker client capable of trading `symbol` for `user`.

    Always returns *some* client — falls back to PaperTrader rather than None,
    so callers don't need to null-check on every loop. PaperTrader honours the
    same duck-typed interface as the live brokers.

    `purpose` matters to IBKR only: "trade" is the session orders go
    through; a caller that only reads bars passes "data" so the bar writer
    and the trader never share a clientId (see ibkr_sessions).
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
    # eToro opt-in, before IBKR's: the newer broker wins when both are set.
    # options / cfd never reach here with a True — EtoroAccount has no flag
    # for either — so the forced-IBKR rule below still holds for them.
    # VENUE_PRECEDENCE in code: Saxo, then eToro, then IBKR.
    if _saxo_overrides(user, asset_class):
        return _saxo_client_for(user, cfg, symbol)

    if _etoro_overrides(user, asset_class):
        return _etoro_client_for(user, cfg, symbol)

    if asset_class in ("options", "cfd") or _ibkr_overrides(user, asset_class):
        return _ibkr_client_for(user, cfg, purpose)

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
    if _saxo_overrides(user, asset_class):
        return "saxo"
    if _etoro_overrides(user, asset_class):
        return "etoro"
    if asset_class in ("options", "cfd") or _ibkr_overrides(user, asset_class):
        return "ibkr"
    return _broker_for_asset_class(asset_class)
