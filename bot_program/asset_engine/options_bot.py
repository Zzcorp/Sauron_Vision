"""OptionsBot — Phase-14.

Trades options contracts driven by the same Phase-1 Signal stream the other
asset-class bots consume. Where a StockBot would buy AAPL on a bullish
signal, the OptionsBot picks an AAPL call (or put for bearish) by:

  1. `decide(underlying)` — calls the default Signal-vote logic on the
     underlying symbol. BUY/SELL becomes a long-call/long-put preference.
  2. `select_contract(underlying, direction)` — finds the best matching
     OptionContract row by target delta and DTE (days to expiry).
  3. Greeks-aware sizing — caps notional exposure using delta and the
     contract multiplier, and enforces a max premium per contract.
  4. Expiry-close gate — refuses to open inside `min_dte`, and when an
     OPEN trade is within `close_before_dte`, force-closes it.

Routing always goes through IBKR via broker_router (Alpaca/OANDA don't trade
options at scale). When IBKR is unavailable, broker_router falls back to
PaperTrader, so paper mode works without an IBKR connection.

Configuration via `AssetBotConfig.extras`:
  target_delta:       float   default 0.40 (long-call); inverted for puts
  delta_tolerance:    float   default 0.10 — accepted strike window
  min_dte:            int     default 14   — refuse new entries with <14d to expiry
  max_dte:            int     default 60   — refuse new entries with >60d to expiry
  close_before_dte:   int     default 5    — force-close open positions within 5d
  max_premium_per_contract: float default 5.00  USD per contract (cap on absurd
                                                bid/ask spreads); 0 disables
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from django.utils import timezone

from .base import AssetBot, BotDecision

logger = logging.getLogger(__name__)


DEFAULT_TARGET_DELTA = 0.40
DEFAULT_DELTA_TOLERANCE = 0.10
DEFAULT_MIN_DTE = 14
DEFAULT_MAX_DTE = 60
DEFAULT_CLOSE_BEFORE_DTE = 5
DEFAULT_MAX_PREMIUM_PER_CONTRACT = 5.0  # in $, multiplied by 100 = $500/contract


class OptionsBot(AssetBot):
    """Bot for buying long calls/puts driven by Phase-1 Signals.

    NB: long premium only. Selling premium (covered calls, credit spreads,
    naked shorts) is intentionally out of scope — it requires margin
    handling, assignment risk, and a different risk model.
    """

    asset_class = "options"

    # ── extras helpers ───────────────────────────────────────────────────

    def _extras(self) -> dict:
        return self.cfg.extras or {}

    def _target_delta(self) -> float:
        return float(self._extras().get("target_delta", DEFAULT_TARGET_DELTA))

    def _delta_tolerance(self) -> float:
        return float(self._extras().get("delta_tolerance", DEFAULT_DELTA_TOLERANCE))

    def _min_dte(self) -> int:
        return int(self._extras().get("min_dte", DEFAULT_MIN_DTE))

    def _max_dte(self) -> int:
        return int(self._extras().get("max_dte", DEFAULT_MAX_DTE))

    def _close_before_dte(self) -> int:
        return int(self._extras().get("close_before_dte", DEFAULT_CLOSE_BEFORE_DTE))

    def _max_premium(self) -> float:
        return float(self._extras().get(
            "max_premium_per_contract", DEFAULT_MAX_PREMIUM_PER_CONTRACT))

    # ── decide(): defer to base, then translate direction → call/put ────

    def decide(self, underlying: str) -> BotDecision:
        """Use the default signal-vote logic on the underlying.

        BUY  → long call
        SELL → long put (we still report direction='BUY' to base.scan_symbol
               since we always *buy* premium; put-vs-call is recorded in
               metadata.right).
        """
        return super().decide(underlying)

    # ── contract selection ──────────────────────────────────────────────

    def select_contract(self, underlying: str, direction: str):
        """Pick the OptionContract that best matches target_delta + DTE.

        Returns the matching `OptionContract` row, or None if nothing is
        eligible. Direction is "BUY" (call) or "SELL" (put).

        Selection logic:
          1. Filter contracts by underlying + right (C for BUY, P for SELL).
          2. Keep only expiries inside [min_dte, max_dte].
          3. Among remaining, pick the one whose |delta| is closest to
             target_delta and within delta_tolerance.
          4. Tie-break: nearest expiry within the window (lower theta drag).
          5. Reject if |bid/ask|, premium > max_premium_per_contract.
        """
        from instruments.models import Instrument
        from bot_program.options_models import OptionContract

        inst = Instrument.objects.filter(symbol=underlying).first()
        if inst is None:
            return None

        right = "C" if direction == "BUY" else "P"
        target = self._target_delta()
        if right == "P":
            target = -target  # puts have negative delta
        tol = self._delta_tolerance()

        today = timezone.now().date()
        min_exp = today + timedelta(days=self._min_dte())
        max_exp = today + timedelta(days=self._max_dte())

        qs = OptionContract.objects.filter(
            underlying=inst, right=right,
            expiry__gte=min_exp, expiry__lte=max_exp,
        )

        # Filter to delta-bearing contracts; reject if delta missing.
        candidates = []
        for c in qs:
            if c.delta is None:
                continue
            if abs(c.delta - target) > tol:
                continue
            # Premium cap (mid of bid/ask, fall back to last_price).
            mid = self._mid_price(c)
            cap = self._max_premium()
            if cap > 0 and mid is not None and float(mid) > cap:
                continue
            candidates.append(c)

        if not candidates:
            return None

        # Closest delta first; tie-break with nearest expiry.
        candidates.sort(key=lambda c: (abs(c.delta - target),
                                        (c.expiry - today).days))
        return candidates[0]

    @staticmethod
    def _mid_price(contract) -> Optional[Decimal]:
        if contract.bid and contract.ask:
            return (Decimal(contract.bid) + Decimal(contract.ask)) / Decimal(2)
        if contract.last_price:
            return Decimal(contract.last_price)
        return None

    # ── sizing: contract count, not shares ──────────────────────────────

    def position_size(self, price: float) -> float:
        """Number of CONTRACTS (not shares) to buy at `price` (= premium per share).

        Each contract represents `multiplier` (default 100) shares, so the
        notional is price * multiplier per contract. We size against capital,
        capped by max_concurrent_positions × max_premium budget.
        """
        cap = float(self.cfg.capital)
        dollars = cap * (self.cfg.position_size_pct / 100.0)
        if price <= 0:
            return 0.0
        # Conservatively assume multiplier 100 here — actual sizing happens
        # against a specific OptionContract in scan_symbol.
        contract_cost = price * 100
        n = int(dollars / contract_cost) if contract_cost > 0 else 0
        return float(max(n, 0))

    # ── per-symbol scan: select contract, then open a paper/IBKR trade ──

    def scan_symbol(self, symbol: str) -> Optional[dict]:
        """Override base.scan_symbol to:
          - call decide(underlying)
          - pick a contract
          - record contract details in trade.metadata
          - size in CONTRACTS, not shares
          - route through broker_router (which routes options→IBKR)
        """
        from bot_program.models import AssetBotTrade
        from bot_program.engine.broker_router import client_for_symbol

        # Skip if there's already an OPEN trade for this underlying.
        if AssetBotTrade.objects.filter(
                config=self.cfg, symbol=symbol, status="OPEN").exists():
            return None

        # Cooldown gate (same as base).
        cool = self.cfg.cool_down_minutes or 0
        if cool > 0:
            recent = AssetBotTrade.objects.filter(
                config=self.cfg, symbol=symbol, status="CLOSED",
                closed_at__gte=timezone.now() - timedelta(minutes=cool),
            ).exists()
            if recent:
                return None

        decision = self.decide(symbol)
        if decision.direction == "HOLD":
            return None

        contract = self.select_contract(symbol, decision.direction)
        if contract is None:
            return None

        # Phase-15 orchestrator gate. Long calls = +equity; long puts = -equity.
        # We always BUY premium → side="BUY", right comes from the chosen contract.
        try:
            from bot_program.orchestrator import gate_new_entry
            allowed, reason = gate_new_entry(
                self.user, "options", symbol, "BUY", right=contract.right,
            )
            if not allowed:
                logger.info("[options_bot] orchestrator declined %s %s: %s",
                            symbol, contract.right, reason)
                return None
        except Exception as e:
            logger.warning("[options_bot] orchestrator check failed for %s: %s",
                           symbol, e)

        mid = self._mid_price(contract)
        if mid is None or mid <= 0:
            return None
        premium = float(mid)

        # Number of contracts: size against position_size_pct, premium × multiplier.
        cap = float(self.cfg.capital)
        dollars = cap * (self.cfg.position_size_pct / 100.0)
        contract_cost = premium * float(contract.multiplier or 100)
        n_contracts = int(dollars / contract_cost) if contract_cost > 0 else 0
        if n_contracts <= 0:
            return None

        # Greeks-aware cap: don't accumulate more than ~1× share-equivalent
        # delta exposure than the position_size_pct would buy in shares.
        # |delta| × n_contracts × multiplier should stay <= dollars / underlying_px.
        if contract.delta is not None and contract.delta != 0:
            delta_per_contract = abs(contract.delta) * float(contract.multiplier or 100)
            # Hard cap: if a single contract already exceeds 2× our notional
            # share-equivalent budget (deep ITM), skip.
            if delta_per_contract * premium > dollars * 2:
                return None

        client = client_for_symbol(self.user, symbol, self.cfg)

        sl = premium * (1 - self.cfg.stop_loss_pct / 100)
        tp = premium * (1 + self.cfg.take_profit_pct / 100)

        paper = (self.cfg.mode == "paper")
        order_id = ""
        if not paper:
            try:
                if hasattr(client, "market_order_option"):
                    res = client.market_order_option(
                        underlying=symbol,
                        strike=float(contract.strike),
                        expiry=contract.expiry.strftime("%Y-%m-%d"),
                        right=contract.right,
                        side="BUY",
                        contracts=n_contracts,
                    )
                else:
                    # Fallback: regular market_order using the OCC symbol if any.
                    res = client.market_order(
                        contract.symbol or symbol, "BUY", n_contracts,
                    )
                order_id = str(res.get("orderId", ""))
            except Exception as e:
                logger.error("[options_bot] live order failed for %s: %s", symbol, e)
                return None

        trade = AssetBotTrade.objects.create(
            config=self.cfg, asset_class=self.asset_class,
            symbol=symbol, side="BUY",  # always long premium
            qty=Decimal(str(n_contracts)),
            entry_price=Decimal(str(round(premium, 4))),
            stop_loss=Decimal(str(round(sl, 4))),
            take_profit=Decimal(str(round(tp, 4))),
            composite_score=decision.score,
            reason=" · ".join(decision.reasons)[:1000],
            rule_name=decision.rule_name,
            paper=paper, broker_order_id=order_id,
            metadata={
                "right": contract.right,
                "strike": float(contract.strike),
                "expiry": contract.expiry.isoformat(),
                "multiplier": int(contract.multiplier or 100),
                "delta_at_entry": contract.delta,
                "iv_at_entry": contract.iv,
                "occ_symbol": contract.symbol or "",
                "underlying_signal_direction": decision.direction,
            },
        )
        return {"trade_id": trade.id, "symbol": symbol,
                "right": contract.right, "strike": float(contract.strike),
                "expiry": contract.expiry.isoformat(),
                "contracts": n_contracts, "premium": premium,
                "score": decision.score}

    # ── manage_positions: add expiry-close gate on top of base SL/TP ────

    def manage_positions(self) -> int:
        """Run base SL/TP management, then force-close anything within
        `close_before_dte` of expiry to avoid theta cliff and assignment risk.
        """
        closed = super().manage_positions()

        from bot_program.models import AssetBotTrade
        from bot_program.engine.broker_router import client_for_symbol

        cutoff = timezone.now().date() + timedelta(days=self._close_before_dte())
        for trade in AssetBotTrade.objects.filter(config=self.cfg, status="OPEN"):
            try:
                meta = trade.metadata or {}
                exp_str = meta.get("expiry")
                if not exp_str:
                    continue
                from datetime import date
                exp = date.fromisoformat(exp_str)
                if exp <= cutoff:
                    client = client_for_symbol(self.user, trade.symbol, self.cfg)
                    # Re-mark current premium (best effort; fall back to entry).
                    try:
                        tk = client.ticker(trade.symbol)
                        price = Decimal(str(tk.get("lastPrice", "0") or "0"))
                    except Exception:
                        price = trade.entry_price
                    if price <= 0:
                        price = trade.entry_price
                    self._close_trade(trade, price, client, reason="EXPIRY_CLOSE")
                    closed += 1
            except Exception as e:
                logger.warning("[options_bot] expiry-close check failed for %s: %s",
                               trade.symbol, e)
        return closed
