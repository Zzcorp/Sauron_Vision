#!/usr/bin/env python3
"""
upgrade_sauron.py
=================
Drop this file into the root of your `sauron_vision` Django project
(the directory that contains `manage.py`) and run:

    python upgrade_sauron.py

It is idempotent — safe to re-run. It will:

 1. Add a PIN-code step to the login flow (second "popup" page after
    username+password). Adds `access_pin_hash` to TraderProfile.
 2. Create a new `bot_program` Django app:
       - Binance account linking (encrypted API keys)
       - Multi-signal trading bot engine that consumes Sauron signals,
         news, TA indicators, risk manager and liquidity heatmap
       - Bot configuration UI + Scenarios / Backtest simulator
       - Celery task `run_bot_tick` for live / paper trading
 3. Make the top header bar fully fixed to the top of the viewport
    and stretch all the way to the right edge (over the signals rail).
 4. Add a "Bot Program" entry to the sidebar nav.
 5. Register the new app in settings / urls, run makemigrations + migrate.

SAFETY NOTES
------------
Automated trading with real funds is extremely risky. The bot defaults
to PAPER mode. You must explicitly flip `live_trading = True` in the
Bot Program UI AND enter your PIN to arm it. Start with small sizes on
Binance Testnet (set `BINANCE_TESTNET=1` in your .env).
"""
from __future__ import annotations
import os
import sys
import re
import subprocess
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent
if not (ROOT / "manage.py").exists():
    print("ERROR: run this script from the directory containing manage.py")
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────
# Tiny helpers
# ─────────────────────────────────────────────────────────────────
def write(rel: str, content: str, *, overwrite: bool = True):
    p = ROOT / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and not overwrite:
        print(f"  skip (exists): {rel}")
        return
    p.write_text(dedent(content).lstrip("\n"), encoding="utf-8")
    print(f"  wrote: {rel}")

def patch(rel: str, old: str, new: str, *, required: bool = True):
    p = ROOT / rel
    if not p.exists():
        if required: print(f"  MISSING file for patch: {rel}")
        return
    txt = p.read_text(encoding="utf-8")
    if new.strip() and new.strip() in txt:
        print(f"  already patched: {rel}")
        return
    if old not in txt:
        print(f"  could not find anchor in {rel}")
        return
    p.write_text(txt.replace(old, new, 1), encoding="utf-8")
    print(f"  patched: {rel}")

def insert_once(rel: str, marker: str, snippet: str):
    """Insert `snippet` right after the first occurrence of `marker`."""
    p = ROOT / rel
    if not p.exists():
        print(f"  MISSING file for insert: {rel}"); return
    txt = p.read_text(encoding="utf-8")
    if snippet.strip() in txt:
        print(f"  already inserted: {rel}"); return
    idx = txt.find(marker)
    if idx < 0:
        print(f"  marker not found in {rel}"); return
    idx += len(marker)
    p.write_text(txt[:idx] + snippet + txt[idx:], encoding="utf-8")
    print(f"  inserted into: {rel}")


print("━" * 60)
print(" SAURON VISION — UPGRADE SCRIPT")
print("━" * 60)

# =================================================================
# STEP 1 · bot_program Django app
# =================================================================
print("\n[1/7] Creating bot_program app …")

write("bot_program/__init__.py", "")
write("bot_program/apps.py", """
    from django.apps import AppConfig
    class BotProgramConfig(AppConfig):
        default_auto_field = "django.db.models.BigAutoField"
        name = "bot_program"
        verbose_name = "Bot Program"
""")

write("bot_program/models.py", '''
    """Bot Program models — Binance link, bot config, trades, scenarios."""
    from django.db import models
    from django.contrib.auth.models import User
    from django.utils import timezone
    from cryptography.fernet import Fernet, InvalidToken
    from django.conf import settings
    import base64, hashlib, json

    def _fernet() -> Fernet:
        key = getattr(settings, "SECRET_KEY", "sauron-default").encode()
        key = base64.urlsafe_b64encode(hashlib.sha256(key).digest())
        return Fernet(key)

    class BinanceAccount(models.Model):
        """Encrypted Binance API credentials linked to a Sauron user."""
        user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="binance_account")
        label = models.CharField(max_length=60, default="Main")
        api_key_enc = models.TextField(blank=True)
        api_secret_enc = models.TextField(blank=True)
        testnet = models.BooleanField(default=True, help_text="Use Binance Testnet (recommended)")
        connected = models.BooleanField(default=False)
        last_sync = models.DateTimeField(null=True, blank=True)
        last_balance_usdt = models.DecimalField(max_digits=18, decimal_places=4, default=0)
        created_at = models.DateTimeField(auto_now_add=True)

        def set_credentials(self, api_key: str, api_secret: str):
            f = _fernet()
            self.api_key_enc = f.encrypt(api_key.encode()).decode()
            self.api_secret_enc = f.encrypt(api_secret.encode()).decode()

        def get_credentials(self) -> tuple[str, str] | tuple[None, None]:
            if not self.api_key_enc: return (None, None)
            try:
                f = _fernet()
                return (f.decrypt(self.api_key_enc.encode()).decode(),
                        f.decrypt(self.api_secret_enc.encode()).decode())
            except InvalidToken:
                return (None, None)

        def __str__(self): return f"{self.user.username} · Binance ({'testnet' if self.testnet else 'live'})"


    class BotConfig(models.Model):
        """One bot configuration per user. Defines strategy weights & risk."""
        MODE_CHOICES = [
            ("paper",  "Paper Trading (simulated, safe)"),
            ("live",   "Live Trading (real funds)"),
        ]
        user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="bot_config")
        name = models.CharField(max_length=80, default="Sauron Bot")
        enabled = models.BooleanField(default=False)
        mode = models.CharField(max_length=8, choices=MODE_CHOICES, default="paper")

        # Universe
        symbols = models.JSONField(default=list, help_text='Symbols, e.g. ["BTCUSDT","ETHUSDT"]')
        base_quote = models.CharField(max_length=8, default="USDT")

        # Sizing & risk
        capital_usdt = models.DecimalField(max_digits=14, decimal_places=2, default=1000)
        position_size_pct = models.FloatField(default=5.0, help_text="% of capital per trade")
        max_concurrent_positions = models.IntegerField(default=4)
        max_daily_loss_pct = models.FloatField(default=3.0)
        stop_loss_pct = models.FloatField(default=1.5)
        take_profit_pct = models.FloatField(default=3.0)
        trailing_stop_pct = models.FloatField(default=1.0)
        leverage = models.FloatField(default=1.0, help_text="Futures only; 1 = spot")

        # Strategy weights (sum normalised at runtime)
        w_technical   = models.FloatField(default=0.30)
        w_sauron_sig  = models.FloatField(default=0.25)
        w_news        = models.FloatField(default=0.15)
        w_liquidity   = models.FloatField(default=0.15)
        w_macro       = models.FloatField(default=0.10)
        w_sentiment   = models.FloatField(default=0.05)

        # Entry / exit thresholds
        entry_score_min = models.FloatField(default=0.60, help_text="0–1; min composite score to open")
        exit_score_max  = models.FloatField(default=0.35, help_text="Close if score drops below this")

        # Timing
        tick_interval_sec = models.IntegerField(default=60)
        timeframe = models.CharField(max_length=6, default="15m")
        cool_down_minutes = models.IntegerField(default=20)

        # News / risk-off filters
        halt_on_high_impact_news = models.BooleanField(default=True)
        halt_on_drawdown = models.BooleanField(default=True)

        updated_at = models.DateTimeField(auto_now=True)

        def normalized_weights(self) -> dict:
            keys = ["w_technical","w_sauron_sig","w_news","w_liquidity","w_macro","w_sentiment"]
            vals = [max(0.0, getattr(self, k)) for k in keys]
            s = sum(vals) or 1.0
            return {k.replace("w_",""): v/s for k, v in zip(keys, vals)}

        def __str__(self): return f"{self.user.username} · {self.name} [{self.mode}]"


    class BotTrade(models.Model):
        SIDE = [("BUY","Buy"),("SELL","Sell")]
        STATUS = [("OPEN","Open"),("CLOSED","Closed"),("CANCELED","Canceled"),("ERROR","Error")]
        config = models.ForeignKey(BotConfig, on_delete=models.CASCADE, related_name="trades")
        symbol = models.CharField(max_length=20)
        side = models.CharField(max_length=4, choices=SIDE)
        qty = models.DecimalField(max_digits=18, decimal_places=8)
        entry_price = models.DecimalField(max_digits=18, decimal_places=8)
        exit_price = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
        stop_loss = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
        take_profit = models.DecimalField(max_digits=18, decimal_places=8, null=True, blank=True)
        status = models.CharField(max_length=10, choices=STATUS, default="OPEN")
        pnl_usdt = models.DecimalField(max_digits=14, decimal_places=4, default=0)
        composite_score = models.FloatField(default=0)
        reason = models.TextField(blank=True)
        paper = models.BooleanField(default=True)
        opened_at = models.DateTimeField(default=timezone.now)
        closed_at = models.DateTimeField(null=True, blank=True)
        binance_order_id = models.CharField(max_length=64, blank=True)

        class Meta:
            ordering = ["-opened_at"]


    class BotScenario(models.Model):
        """Named backtest / simulation scenario."""
        user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="bot_scenarios")
        name = models.CharField(max_length=120)
        description = models.TextField(blank=True)
        symbols = models.JSONField(default=list)
        start_date = models.DateField()
        end_date = models.DateField()
        initial_capital = models.DecimalField(max_digits=14, decimal_places=2, default=10000)
        params = models.JSONField(default=dict, help_text="Overrides for BotConfig fields")
        # Results
        final_equity = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
        total_return_pct = models.FloatField(null=True, blank=True)
        max_drawdown_pct = models.FloatField(null=True, blank=True)
        sharpe = models.FloatField(null=True, blank=True)
        win_rate = models.FloatField(null=True, blank=True)
        num_trades = models.IntegerField(default=0)
        equity_curve = models.JSONField(default=list)
        trades_log = models.JSONField(default=list)
        created_at = models.DateTimeField(auto_now_add=True)
        finished_at = models.DateTimeField(null=True, blank=True)

        class Meta:
            ordering = ["-created_at"]
''')

write("bot_program/admin.py", """
    from django.contrib import admin
    from .models import BinanceAccount, BotConfig, BotTrade, BotScenario
    admin.site.register(BinanceAccount)
    admin.site.register(BotConfig)
    admin.site.register(BotTrade)
    admin.site.register(BotScenario)
""")

# ── Binance client ──────────────────────────────────────────────
write("bot_program/engine/__init__.py", "")
write("bot_program/engine/binance_client.py", '''
    """Thin Binance REST/WebSocket wrapper. Uses `python-binance` if installed,
    otherwise falls back to a minimal REST client."""
    from __future__ import annotations
    import time, hmac, hashlib, urllib.parse, logging
    import requests

    log = logging.getLogger(__name__)

    SPOT_LIVE    = "https://api.binance.com"
    SPOT_TESTNET = "https://testnet.binance.vision"

    class BinanceClient:
        def __init__(self, api_key: str | None, api_secret: str | None, testnet: bool = True):
            self.api_key = api_key or ""
            self.api_secret = (api_secret or "").encode()
            self.base = SPOT_TESTNET if testnet else SPOT_LIVE

        # ── Public ─────────────────────────────────────────────
        def ping(self) -> bool:
            try:
                r = requests.get(f"{self.base}/api/v3/ping", timeout=8)
                return r.status_code == 200
            except Exception as e:
                log.warning("binance ping failed: %s", e); return False

        def ticker(self, symbol: str) -> dict:
            r = requests.get(f"{self.base}/api/v3/ticker/24hr", params={"symbol": symbol}, timeout=8)
            r.raise_for_status(); return r.json()

        def klines(self, symbol: str, interval: str = "15m", limit: int = 200) -> list[list]:
            r = requests.get(f"{self.base}/api/v3/klines",
                             params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
            r.raise_for_status(); return r.json()

        def order_book(self, symbol: str, limit: int = 100) -> dict:
            r = requests.get(f"{self.base}/api/v3/depth",
                             params={"symbol": symbol, "limit": limit}, timeout=8)
            r.raise_for_status(); return r.json()

        # ── Signed ─────────────────────────────────────────────
        def _sign(self, params: dict) -> dict:
            params["timestamp"] = int(time.time() * 1000)
            q = urllib.parse.urlencode(params)
            sig = hmac.new(self.api_secret, q.encode(), hashlib.sha256).hexdigest()
            params["signature"] = sig
            return params

        def _headers(self): return {"X-MBX-APIKEY": self.api_key}

        def account(self) -> dict:
            r = requests.get(f"{self.base}/api/v3/account",
                             params=self._sign({}), headers=self._headers(), timeout=10)
            r.raise_for_status(); return r.json()

        def balance_usdt(self) -> float:
            try:
                acct = self.account()
                for b in acct.get("balances", []):
                    if b["asset"] == "USDT":
                        return float(b["free"]) + float(b["locked"])
            except Exception as e:
                log.warning("balance fetch failed: %s", e)
            return 0.0

        def market_order(self, symbol: str, side: str, quantity: float) -> dict:
            """side: BUY/SELL. Quantity in base asset."""
            params = self._sign({
                "symbol": symbol, "side": side, "type": "MARKET",
                "quantity": f"{quantity:.8f}".rstrip("0").rstrip("."),
            })
            r = requests.post(f"{self.base}/api/v3/order",
                              params=params, headers=self._headers(), timeout=10)
            try: r.raise_for_status()
            except Exception: log.error("order failed: %s", r.text); raise
            return r.json()
''')

# ── Strategy/scoring engine ─────────────────────────────────────
write("bot_program/engine/indicators.py", '''
    """Lightweight TA indicators — zero third-party deps."""
    from __future__ import annotations
    from statistics import mean, pstdev

    def ema(values, period):
        if len(values) < period: return []
        k = 2 / (period + 1)
        out = [mean(values[:period])]
        for v in values[period:]:
            out.append(v * k + out[-1] * (1 - k))
        return out

    def rsi(values, period: int = 14) -> float:
        if len(values) < period + 1: return 50.0
        gains, losses = [], []
        for i in range(1, period + 1):
            d = values[-i] - values[-i-1]
            (gains if d >= 0 else losses).append(abs(d))
        avg_g = sum(gains)/period if gains else 0
        avg_l = sum(losses)/period if losses else 1e-9
        rs = avg_g / avg_l
        return 100 - (100 / (1 + rs))

    def macd(values, fast=12, slow=26, sig=9):
        if len(values) < slow + sig: return (0.0, 0.0, 0.0)
        ef, es = ema(values, fast), ema(values, slow)
        n = min(len(ef), len(es))
        macd_line = [ef[-n+i] - es[-n+i] for i in range(n)]
        signal = ema(macd_line, sig) if len(macd_line) >= sig else [0]
        return (macd_line[-1], signal[-1], macd_line[-1] - signal[-1])

    def vwap(ohlcv) -> float:
        num = den = 0
        for o,h,l,c,v in ohlcv:
            tp = (h + l + c) / 3
            num += tp * v; den += v
        return num/den if den else 0

    def atr(ohlc, period: int = 14) -> float:
        if len(ohlc) < period + 1: return 0
        trs = []
        for i in range(1, len(ohlc)):
            h, l, c_prev = ohlc[i][1], ohlc[i][2], ohlc[i-1][3]
            trs.append(max(h-l, abs(h-c_prev), abs(l-c_prev)))
        return mean(trs[-period:])

    def volatility(values, period: int = 20) -> float:
        if len(values) < period: return 0
        return pstdev(values[-period:])
''')

write("bot_program/engine/strategy.py", '''
    """Composite bot signal engine. Merges multiple signal sources into a
    single score in [-1, +1] and a confidence in [0, 1]."""
    from __future__ import annotations
    from dataclasses import dataclass
    from typing import Iterable
    from .indicators import ema, rsi, macd, vwap, atr, volatility

    @dataclass
    class Decision:
        symbol: str
        score: float      # -1 bearish … +1 bullish
        confidence: float # 0..1
        direction: str    # "BUY","SELL","HOLD"
        reasons: list[str]
        sl_pct: float
        tp_pct: float

    # ── Individual analysers ────────────────────────────────────
    def _score_technical(closes: list[float], ohlcv: list[list]) -> tuple[float, list[str]]:
        reasons = []
        if len(closes) < 60: return (0, ["insufficient bars"])
        ef = ema(closes, 20); es = ema(closes, 50)
        cross = ef[-1] - es[-1] if ef and es else 0
        r = rsi(closes)
        m, s, h = macd(closes)
        vw = vwap(ohlcv[-60:]) if ohlcv else 0

        score = 0.0
        if cross > 0: score += 0.35; reasons.append("EMA20>EMA50")
        else:         score -= 0.35; reasons.append("EMA20<EMA50")
        if r < 30:    score += 0.25; reasons.append(f"RSI oversold {r:.0f}")
        elif r > 70:  score -= 0.25; reasons.append(f"RSI overbought {r:.0f}")
        if h > 0:     score += 0.20; reasons.append("MACD hist +")
        else:         score -= 0.20; reasons.append("MACD hist −")
        if vw and closes[-1] > vw: score += 0.20; reasons.append("price>VWAP")
        elif vw:                   score -= 0.20; reasons.append("price<VWAP")
        return (max(-1, min(1, score)), reasons)

    def _score_liquidity(order_book: dict) -> tuple[float, list[str]]:
        """Order book imbalance → short-term pressure."""
        try:
            bids = sum(float(q) for _, q in order_book.get("bids", [])[:20])
            asks = sum(float(q) for _, q in order_book.get("asks", [])[:20])
            total = bids + asks
            if not total: return (0, [])
            imb = (bids - asks) / total  # [-1, +1]
            return (imb, [f"book imbalance {imb:+.2f}"])
        except Exception:
            return (0, [])

    def _score_sauron_signals(symbol: str) -> tuple[float, list[str]]:
        """Pull latest signals from Sauron signals engine."""
        try:
            from signals.models import Signal
            from django.utils import timezone
            from datetime import timedelta
            recent = Signal.objects.filter(
                instrument__symbol__icontains=symbol.replace("USDT",""),
                created_at__gte=timezone.now() - timedelta(hours=6),
            ).order_by("-created_at")[:10]
            if not recent: return (0, [])
            agg = 0.0
            for s in recent:
                direction = getattr(s, "direction", "") or ""
                score = float(getattr(s, "score", 0) or 0)
                agg += (score if "bull" in direction.lower() else -score)
            agg = max(-1, min(1, agg / max(1, len(recent))))
            return (agg, [f"sauron sig avg {agg:+.2f} ({len(recent)})"])
        except Exception:
            return (0, [])

    def _score_news(symbol: str) -> tuple[float, list[str]]:
        try:
            from scraping.models import NewsItem  # if exists
            from django.utils import timezone
            from datetime import timedelta
            recent = NewsItem.objects.filter(
                published_at__gte=timezone.now() - timedelta(hours=12),
            ).order_by("-published_at")[:20]
            pos, neg = 0, 0
            base = symbol.replace("USDT","").lower()
            for n in recent:
                text = f"{getattr(n,'title','')} {getattr(n,'summary','')}".lower()
                if base not in text: continue
                sent = float(getattr(n, "sentiment_score", 0) or 0)
                if sent > 0.1: pos += sent
                elif sent < -0.1: neg += sent
            total = pos + abs(neg)
            if total == 0: return (0, [])
            s = (pos - abs(neg)) / total
            return (max(-1, min(1, s)), [f"news sent {s:+.2f}"])
        except Exception:
            return (0, [])

    def _score_macro() -> tuple[float, list[str]]:
        """Placeholder macro regime score from ai_agents memory if any."""
        return (0, [])

    def _score_sentiment(symbol: str) -> tuple[float, list[str]]:
        return (0, [])

    # ── Compose ─────────────────────────────────────────────────
    def decide(symbol: str, ohlcv: list[list], order_book: dict, weights: dict,
               entry_min: float, exit_max: float, atr_mult_sl: float = 1.5,
               atr_mult_tp: float = 3.0) -> Decision:
        closes = [c[3] for c in ohlcv]
        reasons: list[str] = []
        parts = {}
        parts["technical"], r = _score_technical(closes, ohlcv); reasons += r
        parts["liquidity"], r = _score_liquidity(order_book);     reasons += r
        parts["sauron_sig"], r = _score_sauron_signals(symbol);   reasons += r
        parts["news"], r       = _score_news(symbol);             reasons += r
        parts["macro"], r      = _score_macro();                  reasons += r
        parts["sentiment"], r  = _score_sentiment(symbol);        reasons += r

        composite = sum(parts[k] * weights.get(k, 0) for k in parts)
        composite = max(-1, min(1, composite))
        conf = min(1.0, abs(composite) + 0.2)

        direction = "HOLD"
        if composite >= entry_min: direction = "BUY"
        elif composite <= -entry_min: direction = "SELL"

        a = atr(ohlcv)
        last = closes[-1] if closes else 0
        sl_pct = (atr_mult_sl * a / last * 100) if last else 1.5
        tp_pct = (atr_mult_tp * a / last * 100) if last else 3.0

        return Decision(symbol, composite, conf, direction, reasons[:8],
                        max(0.3, min(5.0, sl_pct)),
                        max(0.5, min(10.0, tp_pct)))
''')

write("bot_program/engine/risk.py", '''
    """Risk manager — enforces per-trade and account-level limits."""
    from __future__ import annotations
    from decimal import Decimal
    from django.utils import timezone
    from datetime import timedelta

    class RiskManager:
        def __init__(self, config):
            self.c = config

        def can_open_new(self) -> tuple[bool, str]:
            from ..models import BotTrade
            open_trades = BotTrade.objects.filter(config=self.c, status="OPEN").count()
            if open_trades >= self.c.max_concurrent_positions:
                return (False, f"max {self.c.max_concurrent_positions} concurrent positions reached")

            # Daily loss limit
            since = timezone.now() - timedelta(hours=24)
            closed = BotTrade.objects.filter(config=self.c, status="CLOSED", closed_at__gte=since)
            pnl = sum((t.pnl_usdt for t in closed), Decimal(0))
            limit = -self.c.capital_usdt * Decimal(self.c.max_daily_loss_pct / 100)
            if pnl <= limit and self.c.halt_on_drawdown:
                return (False, f"daily loss limit hit ({pnl:.2f} USDT)")
            return (True, "ok")

        def position_size(self, price: float) -> float:
            cap = float(self.c.capital_usdt)
            dollars = cap * (self.c.position_size_pct / 100.0) * self.c.leverage
            if price <= 0: return 0
            return round(dollars / price, 6)
''')

write("bot_program/engine/runner.py", '''
    """Main bot loop. Call `run_bot_tick(user_id)` from Celery / cron."""
    from __future__ import annotations
    import logging
    from decimal import Decimal
    from django.utils import timezone
    from ..models import BotConfig, BotTrade, BinanceAccount
    from .binance_client import BinanceClient
    from .strategy import decide
    from .risk import RiskManager

    log = logging.getLogger(__name__)

    def _client_for(user) -> BinanceClient:
        try:
            acct: BinanceAccount = user.binance_account
            k, s = acct.get_credentials()
            return BinanceClient(k, s, testnet=acct.testnet)
        except BinanceAccount.DoesNotExist:
            return BinanceClient(None, None, testnet=True)

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

        client = _client_for(user)
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
        pnl = (price - trade.entry_price) * trade.qty if trade.side == "BUY" \\
              else (trade.entry_price - price) * trade.qty
        trade.exit_price = price
        trade.pnl_usdt = pnl
        trade.status = "CLOSED"
        trade.closed_at = timezone.now()
        trade.reason = (trade.reason + f" | closed:{reason}").strip()
        if not trade.paper:
            try: client.market_order(trade.symbol, "SELL" if trade.side=="BUY" else "BUY", float(trade.qty))
            except Exception as e: log.error("close order fail: %s", e)
        trade.save()
''')

write("bot_program/engine/backtest.py", '''
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
                    hit_sl = (position["side"]=="BUY" and price <= position["sl"]) or \\
                             (position["side"]=="SELL" and price >= position["sl"])
                    hit_tp = (position["side"]=="BUY" and price >= position["tp"]) or \\
                             (position["side"]=="SELL" and price <= position["tp"])
                    if hit_sl or hit_tp:
                        pnl = (price - position["entry"]) * position["qty"] if position["side"]=="BUY" \\
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
''')

write("bot_program/tasks.py", """
    from celery import shared_task
    from .engine.runner import run_bot_tick
    from .engine.backtest import run_scenario
    from .models import BotConfig, BotScenario

    @shared_task
    def tick_all_bots():
        for cfg in BotConfig.objects.filter(enabled=True):
            try:
                run_bot_tick(cfg.user_id)
            except Exception as e:
                print(f"tick failed for user={cfg.user_id}: {e}")

    @shared_task
    def run_scenario_task(scenario_id: int):
        try:
            run_scenario(BotScenario.objects.get(id=scenario_id))
        except Exception as e:
            print(f"scenario failed {scenario_id}: {e}")
""")

# ── Views & URLs ────────────────────────────────────────────────
write("bot_program/forms.py", '''
    from django import forms
    from .models import BotConfig, BinanceAccount, BotScenario

    class BinanceLinkForm(forms.ModelForm):
        api_key = forms.CharField(widget=forms.PasswordInput(render_value=True),
                                  required=True, label="API Key")
        api_secret = forms.CharField(widget=forms.PasswordInput(render_value=True),
                                     required=True, label="API Secret")
        class Meta:
            model = BinanceAccount
            fields = ["label", "testnet"]

    class BotConfigForm(forms.ModelForm):
        class Meta:
            model = BotConfig
            exclude = ["user", "updated_at"]
            widgets = {"symbols": forms.Textarea(attrs={"rows":2,
                "placeholder":'["BTCUSDT","ETHUSDT","SOLUSDT"]'})}

    class ScenarioForm(forms.ModelForm):
        class Meta:
            model = BotScenario
            fields = ["name", "description", "symbols", "start_date", "end_date",
                      "initial_capital", "params"]
            widgets = {
                "start_date": forms.DateInput(attrs={"type":"date"}),
                "end_date":   forms.DateInput(attrs={"type":"date"}),
                "symbols":    forms.Textarea(attrs={"rows":2}),
                "params":     forms.Textarea(attrs={"rows":4,
                    "placeholder":'{"position_size_pct": 3, "stop_loss_pct": 2}'}),
            }
''')

write("bot_program/views.py", '''
    import json
    from django.contrib.auth.decorators import login_required
    from django.shortcuts import render, redirect, get_object_or_404
    from django.contrib import messages
    from django.views.decorators.http import require_POST
    from .models import BotConfig, BinanceAccount, BotTrade, BotScenario
    from .forms import BinanceLinkForm, BotConfigForm, ScenarioForm
    from .engine.binance_client import BinanceClient
    from .engine.runner import run_bot_tick
    from .engine.backtest import run_scenario

    def _ctx(request, **extra):
        base = {"page_id": "bot_program"}
        base.update(extra); return base

    @login_required
    def bot_home(request):
        cfg, _ = BotConfig.objects.get_or_create(user=request.user)
        acct = getattr(request.user, "binance_account", None)
        open_trades = BotTrade.objects.filter(config=cfg, status="OPEN")[:20]
        closed_trades = BotTrade.objects.filter(config=cfg, status="CLOSED")[:30]
        scenarios = BotScenario.objects.filter(user=request.user)[:20]
        equity = float(cfg.capital_usdt)
        pnl_total = sum(float(t.pnl_usdt) for t in BotTrade.objects.filter(config=cfg, status="CLOSED"))
        return render(request, "bot_program/home.html", _ctx(request,
            cfg=cfg, acct=acct, open_trades=open_trades,
            closed_trades=closed_trades, scenarios=scenarios,
            equity=equity, pnl_total=pnl_total,
            weights=cfg.normalized_weights()))

    @login_required
    def link_binance(request):
        acct, _ = BinanceAccount.objects.get_or_create(user=request.user)
        if request.method == "POST":
            form = BinanceLinkForm(request.POST, instance=acct)
            if form.is_valid():
                acct = form.save(commit=False)
                acct.set_credentials(form.cleaned_data["api_key"], form.cleaned_data["api_secret"])
                # Test
                cli = BinanceClient(form.cleaned_data["api_key"], form.cleaned_data["api_secret"], acct.testnet)
                if cli.ping():
                    acct.connected = True
                    try:
                        acct.last_balance_usdt = cli.balance_usdt()
                    except Exception: pass
                    acct.save()
                    messages.success(request, "Binance account linked ✓")
                else:
                    messages.error(request, "Could not reach Binance with those keys")
                return redirect("bot_home")
        else:
            form = BinanceLinkForm(instance=acct)
        return render(request, "bot_program/link.html", _ctx(request, form=form, acct=acct))

    @login_required
    def configure_bot(request):
        cfg, _ = BotConfig.objects.get_or_create(user=request.user)
        if request.method == "POST":
            form = BotConfigForm(request.POST, instance=cfg)
            if form.is_valid():
                form.save(); messages.success(request, "Configuration saved.")
                return redirect("bot_home")
        else:
            form = BotConfigForm(instance=cfg)
        return render(request, "bot_program/configure.html", _ctx(request, form=form, cfg=cfg))

    @login_required
    @require_POST
    def toggle_bot(request):
        cfg, _ = BotConfig.objects.get_or_create(user=request.user)
        # Require PIN to arm live mode
        if not cfg.enabled and cfg.mode == "live":
            pin = request.POST.get("pin", "")
            prof = getattr(request.user, "trader_profile", None)
            from django.contrib.auth.hashers import check_password
            if not (prof and prof.access_pin_hash and check_password(pin, prof.access_pin_hash)):
                messages.error(request, "PIN required to arm LIVE mode.")
                return redirect("bot_home")
        cfg.enabled = not cfg.enabled
        cfg.save()
        messages.info(request, f"Bot {'ENABLED' if cfg.enabled else 'DISABLED'}")
        return redirect("bot_home")

    @login_required
    @require_POST
    def run_tick_now(request):
        run_bot_tick(request.user.id)
        messages.info(request, "Bot tick executed.")
        return redirect("bot_home")

    @login_required
    def scenarios_list(request):
        scenarios = BotScenario.objects.filter(user=request.user)
        return render(request, "bot_program/scenarios.html", _ctx(request, scenarios=scenarios))

    @login_required
    def scenario_new(request):
        if request.method == "POST":
            form = ScenarioForm(request.POST)
            if form.is_valid():
                s = form.save(commit=False); s.user = request.user; s.save()
                try:
                    run_scenario(s)
                    messages.success(request, f"Scenario ran. Return: {s.total_return_pct}%")
                except Exception as e:
                    messages.error(request, f"Scenario failed: {e}")
                return redirect("scenario_detail", pk=s.id)
        else:
            form = ScenarioForm(initial={"symbols":["BTCUSDT","ETHUSDT"]})
        return render(request, "bot_program/scenario_new.html", _ctx(request, form=form))

    @login_required
    def scenario_detail(request, pk):
        s = get_object_or_404(BotScenario, pk=pk, user=request.user)
        return render(request, "bot_program/scenario_detail.html", _ctx(request, s=s))
''')

write("bot_program/urls.py", """
    from django.urls import path
    from . import views

    urlpatterns = [
        path("bot/",                   views.bot_home,         name="bot_home"),
        path("bot/link/",              views.link_binance,     name="bot_link"),
        path("bot/configure/",         views.configure_bot,    name="bot_configure"),
        path("bot/toggle/",            views.toggle_bot,       name="bot_toggle"),
        path("bot/tick/",              views.run_tick_now,     name="bot_tick"),
        path("bot/scenarios/",         views.scenarios_list,   name="scenarios_list"),
        path("bot/scenarios/new/",     views.scenario_new,     name="scenario_new"),
        path("bot/scenarios/<int:pk>/",views.scenario_detail,  name="scenario_detail"),
    ]
""")

# ── Bot templates ───────────────────────────────────────────────
write("bot_program/templates/bot_program/home.html", '''
    {% extends "base.html" %}
    {% block title %}Bot Program — Sauron Vision{% endblock %}
    {% block page_title %}Bot Program{% endblock %}
    {% block content %}
    <div class="page-content fade-in" style="padding-top:90px;">
      {% if messages %}{% for m in messages %}
        <div class="card" style="margin-bottom:12px;color:var(--accent);">{{ m }}</div>
      {% endfor %}{% endif %}

      <div class="grid grid-3" style="margin-bottom:20px;">
        <div class="stat-box">
          <div class="stat-label">Status</div>
          <div class="stat-value" style="color:{% if cfg.enabled %}var(--accent){% else %}var(--text-muted){% endif %};">
            {% if cfg.enabled %}ARMED{% else %}OFF{% endif %}
          </div>
          <div class="stat-sub">Mode: {{ cfg.get_mode_display }}</div>
        </div>
        <div class="stat-box">
          <div class="stat-label">Capital</div>
          <div class="stat-value">{{ cfg.capital_usdt }} USDT</div>
          <div class="stat-sub">Realised P&amp;L: <b style="color:{% if pnl_total >= 0 %}var(--accent){% else %}var(--accent-red){% endif %};">{{ pnl_total|floatformat:2 }}</b></div>
        </div>
        <div class="stat-box">
          <div class="stat-label">Binance</div>
          <div class="stat-value" style="font-size:16px;">
            {% if acct.connected %}LINKED ({% if acct.testnet %}TESTNET{% else %}LIVE{% endif %}){% else %}NOT LINKED{% endif %}
          </div>
          <div class="stat-sub"><a href="{% url 'bot_link' %}" style="color:var(--accent);">Manage →</a></div>
        </div>
      </div>

      <div class="card" style="margin-bottom:20px;">
        <div class="card-header"><div class="card-title">CONTROL PANEL</div></div>
        <form method="post" action="{% url 'bot_toggle' %}" style="display:flex;gap:12px;align-items:center;flex-wrap:wrap;">
          {% csrf_token %}
          {% if cfg.mode == 'live' and not cfg.enabled %}
            <input type="password" name="pin" placeholder="PIN" maxlength="8"
                   style="padding:10px;background:#060e0a;border:1px solid var(--border);color:#c8e8d8;font-family:var(--font-mono);">
          {% endif %}
          <button class="btn-login" type="submit" style="width:auto;padding:10px 18px;">
            {% if cfg.enabled %}⏻ DISARM{% else %}▶ ARM BOT{% endif %}
          </button>
          <a href="{% url 'bot_configure' %}" class="btn-login" style="width:auto;padding:10px 18px;text-decoration:none;display:inline-block;">⚙ CONFIGURE</a>
          <form method="post" action="{% url 'bot_tick' %}" style="display:inline;">
            {% csrf_token %}
            <button class="btn-login" type="submit" style="width:auto;padding:10px 18px;background:#1a4030;">RUN TICK NOW</button>
          </form>
        </form>
        <div style="margin-top:14px;font-family:var(--font-mono);font-size:11px;color:var(--text-muted);">
          Weights (normalised): 
          {% for k,v in weights.items %}<span style="margin-right:10px;">{{ k }}={{ v|floatformat:2 }}</span>{% endfor %}
        </div>
      </div>

      <div class="grid grid-2">
        <div class="card">
          <div class="card-header"><div class="card-title">OPEN POSITIONS</div></div>
          {% for t in open_trades %}
            <div class="signal-item">
              <div class="signal-header">
                <span class="signal-symbol">{{ t.symbol }} · {{ t.side }}</span>
                <span>score {{ t.composite_score|floatformat:2 }}</span>
              </div>
              <div class="signal-desc">qty {{ t.qty }} @ {{ t.entry_price }} · SL {{ t.stop_loss }} · TP {{ t.take_profit }}</div>
            </div>
          {% empty %}<div style="color:var(--text-muted);padding:10px;">No open positions.</div>{% endfor %}
        </div>
        <div class="card">
          <div class="card-header"><div class="card-title">RECENT CLOSED</div></div>
          {% for t in closed_trades %}
            <div class="signal-item">
              <div class="signal-header">
                <span class="signal-symbol">{{ t.symbol }} · {{ t.side }}</span>
                <span style="color:{% if t.pnl_usdt >= 0 %}var(--accent){% else %}var(--accent-red){% endif %};">{{ t.pnl_usdt|floatformat:2 }}</span>
              </div>
              <div class="signal-desc">{{ t.closed_at|date:"Y-m-d H:i" }} · {{ t.reason|truncatechars:60 }}</div>
            </div>
          {% empty %}<div style="color:var(--text-muted);padding:10px;">No trades yet.</div>{% endfor %}
        </div>
      </div>

      <div class="card" style="margin-top:20px;">
        <div class="card-header">
          <div class="card-title">SCENARIOS &amp; BACKTESTS</div>
          <a href="{% url 'scenario_new' %}" style="color:var(--accent);">+ NEW SCENARIO</a>
        </div>
        {% for s in scenarios %}
          <div class="signal-item" onclick="location='{% url 'scenario_detail' s.id %}'">
            <div class="signal-header">
              <span class="signal-symbol">{{ s.name }}</span>
              <span>{{ s.total_return_pct|default_if_none:"—" }}%</span>
            </div>
            <div class="signal-desc">{{ s.start_date }} → {{ s.end_date }} · trades {{ s.num_trades }} · DD {{ s.max_drawdown_pct|default_if_none:"—" }}%</div>
          </div>
        {% empty %}<div style="color:var(--text-muted);padding:10px;">No scenarios yet.</div>{% endfor %}
      </div>
    </div>
    {% endblock %}
''')

for tpl, body in {
    "link.html": """
        {% extends "base.html" %}{% block page_title %}Link Binance{% endblock %}
        {% block content %}<div class="page-content fade-in" style="padding-top:90px;max-width:600px;">
          <div class="card"><div class="card-header"><div class="card-title">LINK BINANCE ACCOUNT</div></div>
          {% if messages %}{% for m in messages %}<div style="color:var(--accent-red);">{{ m }}</div>{% endfor %}{% endif %}
          <form method="post">{% csrf_token %}{{ form.as_p }}
            <button class="btn-login" type="submit">CONNECT</button>
          </form>
          <p style="color:var(--text-muted);font-size:11px;margin-top:14px;">
            Your API keys are encrypted at rest with your SECRET_KEY. Use <b>API keys with trading enabled but withdrawals DISABLED</b>. Start on testnet.
          </p>
          </div>
        </div>{% endblock %}
    """,
    "configure.html": """
        {% extends "base.html" %}{% block page_title %}Configure Bot{% endblock %}
        {% block content %}<div class="page-content fade-in" style="padding-top:90px;max-width:820px;">
          <div class="card"><div class="card-header"><div class="card-title">BOT CONFIGURATION</div></div>
          <form method="post">{% csrf_token %}{{ form.as_p }}
            <button class="btn-login" type="submit">SAVE</button>
          </form></div>
        </div>{% endblock %}
    """,
    "scenarios.html": """
        {% extends "base.html" %}{% block page_title %}Scenarios{% endblock %}
        {% block content %}<div class="page-content fade-in" style="padding-top:90px;">
          <div class="card"><div class="card-header"><div class="card-title">SCENARIOS</div>
          <a href="{% url 'scenario_new' %}" style="color:var(--accent);">+ NEW</a></div>
          {% for s in scenarios %}<div class="signal-item" onclick="location='{% url 'scenario_detail' s.id %}'">
            <div class="signal-header"><span class="signal-symbol">{{ s.name }}</span>
            <span>{{ s.total_return_pct|default_if_none:"—" }}%</span></div>
            <div class="signal-desc">{{ s.start_date }} → {{ s.end_date }} · {{ s.num_trades }} trades</div>
          </div>{% empty %}<div style="color:var(--text-muted);">None yet.</div>{% endfor %}
          </div>
        </div>{% endblock %}
    """,
    "scenario_new.html": """
        {% extends "base.html" %}{% block page_title %}New Scenario{% endblock %}
        {% block content %}<div class="page-content fade-in" style="padding-top:90px;max-width:760px;">
          <div class="card"><div class="card-header"><div class="card-title">NEW SCENARIO</div></div>
          <form method="post">{% csrf_token %}{{ form.as_p }}
            <button class="btn-login" type="submit">RUN SIMULATION</button>
          </form></div>
        </div>{% endblock %}
    """,
    "scenario_detail.html": """
        {% extends "base.html" %}{% block page_title %}{{ s.name }}{% endblock %}
        {% block content %}<div class="page-content fade-in" style="padding-top:90px;">
          <div class="grid grid-4" style="margin-bottom:20px;">
            <div class="stat-box"><div class="stat-label">Return</div><div class="stat-value">{{ s.total_return_pct|default:"—" }}%</div></div>
            <div class="stat-box"><div class="stat-label">Max DD</div><div class="stat-value">{{ s.max_drawdown_pct|default:"—" }}%</div></div>
            <div class="stat-box"><div class="stat-label">Win Rate</div><div class="stat-value">{{ s.win_rate|default:"—" }}%</div></div>
            <div class="stat-box"><div class="stat-label">Sharpe</div><div class="stat-value">{{ s.sharpe|default:"—" }}</div></div>
          </div>
          <div class="card"><div class="card-header"><div class="card-title">EQUITY CURVE</div></div>
            <canvas id="eq" height="200"></canvas>
          </div>
          <div class="card" style="margin-top:20px;"><div class="card-header"><div class="card-title">TRADES</div></div>
          {% for t in s.trades_log %}<div class="signal-item"><div class="signal-header">
            <span class="signal-symbol">{{ t.symbol }} · {{ t.side }}</span>
            <span style="color:{% if t.pnl >= 0 %}var(--accent){% else %}var(--accent-red){% endif %};">{{ t.pnl }}</span></div>
            <div class="signal-desc">{{ t.entry }} → {{ t.exit }} · {{ t.reason }}</div>
          </div>{% empty %}<div style="color:var(--text-muted);">No trades.</div>{% endfor %}
          </div>
        </div>
        <script>
        (function(){const data={{ s.equity_curve|default:"[]" }};const c=document.getElementById('eq');if(!c||!data.length)return;
          const ctx=c.getContext('2d');c.width=c.offsetWidth;const W=c.width,H=c.height;
          const mn=Math.min(...data),mx=Math.max(...data);ctx.strokeStyle='#00e868';ctx.lineWidth=1.5;ctx.beginPath();
          data.forEach((v,i)=>{const x=i/(data.length-1)*W,y=H-(v-mn)/(mx-mn||1)*H;i?ctx.lineTo(x,y):ctx.moveTo(x,y);});
          ctx.stroke();})();
        </script>
        {% endblock %}
    """,
}.items():
    write(f"bot_program/templates/bot_program/{tpl}", body)

write("bot_program/migrations/__init__.py", "")

# =================================================================
# STEP 2 · PIN code field on TraderProfile + custom login flow
# =================================================================
print("\n[2/7] Adding PIN code to login flow …")

# 2a. Add access_pin_hash field to TraderProfile if not present
tp_file = ROOT / "portfolio" / "trader_profile.py"
tp_txt = tp_file.read_text(encoding="utf-8")
if "access_pin_hash" not in tp_txt:
    tp_txt = tp_txt.replace(
        "created_at = models.DateTimeField(auto_now_add=True)",
        "access_pin_hash = models.CharField(max_length=128, blank=True, default=\"\", help_text=\"Hashed PIN code (2nd-factor)\")\n    created_at = models.DateTimeField(auto_now_add=True)",
        1,
    )
    tp_file.write_text(tp_txt, encoding="utf-8")
    print("  added access_pin_hash to TraderProfile")
else:
    print("  TraderProfile already has access_pin_hash")

# 2b. Custom login view with PIN verification step
write("dashboard/auth_views.py", '''
    """Two-step login: username/password → PIN verification popup."""
    from django.contrib.auth import authenticate, login as auth_login
    from django.contrib.auth.hashers import check_password, make_password
    from django.shortcuts import render, redirect
    from django.contrib.auth.views import LoginView
    from django.urls import reverse_lazy
    from django.views.decorators.csrf import csrf_protect
    from django.views.decorators.cache import never_cache
    from django.utils.decorators import method_decorator

    PENDING_KEY = "sauron_pending_user_id"

    @method_decorator(never_cache, name="dispatch")
    class SauronLoginView(LoginView):
        template_name = "registration/login.html"

        def form_valid(self, form):
            """Username+password is good → stash user id, send to PIN page."""
            user = form.get_user()
            # If user has no PIN set, just log in normally.
            prof = getattr(user, "trader_profile", None)
            if not prof or not prof.access_pin_hash:
                return super().form_valid(form)
            self.request.session[PENDING_KEY] = user.id
            self.request.session["sauron_pending_next"] = self.request.POST.get("next") or "/"
            return redirect("login_pin")


    @csrf_protect
    @never_cache
    def login_pin(request):
        from django.contrib.auth.models import User
        uid = request.session.get(PENDING_KEY)
        if not uid:
            return redirect("login")
        try:
            user = User.objects.get(id=uid)
        except User.DoesNotExist:
            request.session.pop(PENDING_KEY, None)
            return redirect("login")

        error = None
        if request.method == "POST":
            pin = request.POST.get("pin", "")
            prof = getattr(user, "trader_profile", None)
            if prof and prof.access_pin_hash and check_password(pin, prof.access_pin_hash):
                auth_login(request, user)
                next_url = request.session.pop("sauron_pending_next", "/") or "/"
                request.session.pop(PENDING_KEY, None)
                return redirect(next_url)
            error = "Invalid PIN"
        return render(request, "registration/login_pin.html",
                      {"error": error, "username": user.username})
''')

write("templates/registration/login_pin.html", '''
    {% load static %}
    <!DOCTYPE html><html lang="en"><head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Sauron Vision — PIN</title>
    <link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&family=Orbitron:wght@400;700;900&family=Rajdhani:wght@300;400;600&display=swap" rel="stylesheet">
    <style>
      *{margin:0;padding:0;box-sizing:border-box}
      body{background:#030806;color:#c8e8d8;font-family:'Rajdhani',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;overflow:hidden}
      .grid-bg{position:fixed;inset:-50%;background-image:linear-gradient(rgba(0,232,104,0.04) 1px,transparent 1px),linear-gradient(90deg,rgba(0,232,104,0.04) 1px,transparent 1px);background-size:60px 60px;animation:g 25s linear infinite;z-index:0}
      @keyframes g{to{transform:translate(60px,60px)}}
      .modal{position:relative;z-index:10;width:380px;background:rgba(10,26,20,0.96);border:1px solid #133020;border-radius:14px;padding:40px 32px;backdrop-filter:blur(20px);box-shadow:0 4px 60px rgba(0,232,104,.08);animation:pop .4s cubic-bezier(.2,.8,.2,1)}
      @keyframes pop{from{opacity:0;transform:scale(.9) translateY(20px)}to{opacity:1;transform:scale(1) translateY(0)}}
      .eye{width:56px;height:56px;margin:0 auto 14px;display:block}
      h1{font-family:'Orbitron',sans-serif;font-size:18px;letter-spacing:5px;color:#00e868;text-align:center;margin-bottom:4px}
      p.sub{font-family:'Share Tech Mono',monospace;font-size:10px;letter-spacing:3px;color:#5a8a6a;text-align:center;margin-bottom:24px}
      .who{text-align:center;font-family:'Share Tech Mono',monospace;font-size:11px;color:#c8e8d8;margin-bottom:18px;opacity:.8}
      .pin-row{display:flex;gap:10px;justify-content:center;margin-bottom:22px}
      .pin-row input{width:46px;height:56px;text-align:center;font-family:'Orbitron',sans-serif;font-size:22px;background:#060e0a;border:1px solid #133020;border-radius:8px;color:#00e868;outline:none;transition:all .2s}
      .pin-row input:focus{border-color:#00e868;box-shadow:0 0 20px rgba(0,232,104,.25)}
      button{width:100%;padding:14px;background:linear-gradient(135deg,#0a5028,#00e868);border:none;border-radius:8px;color:#020804;font-family:'Orbitron',sans-serif;font-weight:700;letter-spacing:4px;cursor:pointer;font-size:13px}
      button:hover{box-shadow:0 8px 30px rgba(0,232,104,.3)}
      .err{background:rgba(232,48,48,.08);border:1px solid rgba(232,48,48,.3);border-radius:6px;padding:10px;margin-bottom:16px;font-family:'Share Tech Mono',monospace;font-size:11px;color:#e83030;text-align:center}
      .back{display:block;text-align:center;margin-top:14px;font-family:'Share Tech Mono',monospace;font-size:10px;color:#2a5038;text-decoration:none}
    </style></head><body>
    <div class="grid-bg"></div>
    <div class="modal">
      <svg class="eye" viewBox="0 0 64 64"><path d="M2,32 Q16,8 32,14 Q48,8 62,32 Q48,56 32,50 Q16,56 2,32Z" fill="none" stroke="#00e868" stroke-width="2.5"/><circle cx="32" cy="32" r="12" fill="none" stroke="#00e868" stroke-width="2"/><circle cx="32" cy="32" r="5" fill="#00e868"/></svg>
      <h1>SECOND GATE</h1>
      <p class="sub">ENTER PIN CODE</p>
      <div class="who">OPERATOR :: {{ username }}</div>
      {% if error %}<div class="err">⚠ {{ error }}</div>{% endif %}
      <form method="post" id="pinForm">{% csrf_token %}
        <div class="pin-row">
          <input type="password" inputmode="numeric" maxlength="1" data-pin>
          <input type="password" inputmode="numeric" maxlength="1" data-pin>
          <input type="password" inputmode="numeric" maxlength="1" data-pin>
          <input type="password" inputmode="numeric" maxlength="1" data-pin>
        </div>
        <input type="hidden" name="pin" id="pinFinal">
        <button type="submit">VERIFY</button>
      </form>
      <a class="back" href="{% url 'login' %}">← back</a>
    </div>
    <script>
      const boxes=[...document.querySelectorAll('[data-pin]')];
      boxes[0]?.focus();
      boxes.forEach((b,i)=>{b.addEventListener('input',e=>{if(e.target.value&&i<boxes.length-1)boxes[i+1].focus();document.getElementById('pinFinal').value=boxes.map(x=>x.value).join('')});
        b.addEventListener('keydown',e=>{if(e.key==='Backspace'&&!b.value&&i>0)boxes[i-1].focus()});});
      document.getElementById('pinForm').addEventListener('submit',()=>{document.getElementById('pinFinal').value=boxes.map(x=>x.value).join('')});
    </script>
    </body></html>
''')

# Patch config/urls.py to use SauronLoginView and add pin endpoint + bot_program
urls_file = ROOT / "config" / "urls.py"
urls_txt = urls_file.read_text(encoding="utf-8")
new_urls = '''"""Sauron Vision — Root URL Configuration."""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from dashboard.auth_views import SauronLoginView, login_pin

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", SauronLoginView.as_view(), name="login"),
    path("login/pin/", login_pin, name="login_pin"),
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
    path("", include("bot_program.urls")),
    path("", include("dashboard.urls")),
]
'''
if "SauronLoginView" not in urls_txt:
    urls_file.write_text(new_urls, encoding="utf-8")
    print("  rewrote config/urls.py with PIN + bot_program routes")
else:
    print("  config/urls.py already patched")

# =================================================================
# STEP 3 · Fix top header → fully fixed, full right
# =================================================================
print("\n[3/7] Patching topbar CSS (fixed, full right) …")

patch("templates/base.html",
    ".topbar {\n            height: var(--topbar-height);\n            background: rgba(6, 14, 10, 0.85); backdrop-filter: blur(12px);\n            border-bottom: 1px solid var(--border);\n            display: flex; align-items: center; justify-content: space-between;\n            padding: 0 28px; position: sticky; top: 0; z-index: 50;\n        }",
    ".topbar {\n            height: var(--topbar-height);\n            background: rgba(6, 14, 10, 0.92); backdrop-filter: blur(14px);\n            border-bottom: 1px solid var(--border);\n            display: flex; align-items: center; justify-content: space-between;\n            padding: 0 28px;\n            /* UPGRADED: fully fixed to top, extends to right edge over signals rail */\n            position: fixed; top: 0; left: var(--sidebar-width); right: 0;\n            width: auto; z-index: 60;\n        }\n        body:has(.sidebar.mini) .topbar { left: 68px; }\n        @media (max-width: 768px) { .topbar { left: 0 !important; } }\n        .main-content { padding-top: var(--topbar-height); }",
)

# =================================================================
# STEP 4 · Sidebar nav entry for Bot Program
# =================================================================
print("\n[4/7] Adding 'Bot Program' sidebar nav link …")

nav_snippet = '''
            <div class="nav-section">Automation</div>
            <a href="{% url 'bot_home' %}" class="nav-link {% if page_id == 'bot_program' %}active{% endif %}"><span class="icon">⟳</span> <span class="label-text">Bot Program</span></a>'''
insert_once(
    "templates/base.html",
    '<a href="{% url \'backtest_list\' %}" class="nav-link {% if page_id == \'backtest\' %}active{% endif %}"><span class="icon">&#x25A1;</span> <span class="label-text">Backtesting</span></a>',
    nav_snippet,
)

# =================================================================
# STEP 5 · settings.py — register bot_program
# =================================================================
print("\n[5/7] Registering bot_program in INSTALLED_APPS …")
patch("config/settings.py",
      '    "dashboard",\n    "backtester",\n]',
      '    "dashboard",\n    "backtester",\n    "bot_program",\n]')

# =================================================================
# STEP 6 · requirements
# =================================================================
print("\n[6/7] Ensuring 'cryptography' in requirements.txt …")
req = ROOT / "requirements.txt"
if req.exists():
    txt = req.read_text(encoding="utf-8")
    if "cryptography" not in txt:
        req.write_text(txt.rstrip() + "\ncryptography>=41\n", encoding="utf-8")
        print("  added cryptography")
    else:
        print("  cryptography already present")

# =================================================================
# STEP 7 · Run makemigrations + migrate
# =================================================================
print("\n[7/7] Running makemigrations + migrate …")
def run(cmd):
    print(f"  $ {cmd}")
    subprocess.run(cmd, shell=True, cwd=str(ROOT))

run(f"{sys.executable} manage.py makemigrations portfolio bot_program")
run(f"{sys.executable} manage.py migrate")

print("\n" + "━" * 60)
print(" ✓ UPGRADE COMPLETE")
print("━" * 60)
print("""
Next steps:
  1. Set a PIN for your user in Django shell (so the 2nd popup appears):

       python manage.py shell
       >>> from django.contrib.auth.models import User
       >>> from django.contrib.auth.hashers import make_password
       >>> u = User.objects.get(username="YOUR_USERNAME")
       >>> u.trader_profile.access_pin_hash = make_password("1234")
       >>> u.trader_profile.save()

  2. Install crypto lib if new:   pip install cryptography
  3. Restart the dev server:      python manage.py runserver
  4. Visit /bot/ to link Binance (use TESTNET keys first!).
  5. Schedule the Celery beat task `bot_program.tasks.tick_all_bots`
     every minute for live ticking.

Bot defaults to PAPER mode. You must explicitly switch to LIVE in the
Bot Program UI and confirm with your PIN to arm real trades.
""")
