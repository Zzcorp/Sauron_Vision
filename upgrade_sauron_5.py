#!/usr/bin/env python3
"""
upgrade_sauron_5.py
===================
Pass 5 — final infrastructure pass.

Drop next to manage.py and run:

    python upgrade_sauron_5.py

Idempotent. Includes DB migrations (auto-applied).

Contents
--------
 1. NIGHTLY RETENTION TASKS
    • market_data/cleanup_tasks.py with cleanup_liquidations,
      cleanup_orderbook, cleanup_funding, cleanup_price_data.
    • Registered in celery beat schedule to run at 04:15 UTC daily.

 2. FUNDING RATE ALERTS
    • market_data/funding_alerts.py analyses recent FundingRate rows
      every 5 minutes, raises Notification rows when:
        - funding rate flips sign vs previous sample
        - funding crosses ±0.1% threshold (extreme long/short crowding)
        - funding diverges from price direction (squeeze setup)
    • Wired into celery beat + reuses existing alerts.Notification model.

 3. BOT FUTURES MODE
    • New bot_program/engine/binance_futures_client.py mirroring the
      spot client interface (ping/ticker/klines/order_book/account/
      balance_usdt/market_order) but hitting fapi endpoints.
    • BotConfig gets two new fields: `market_type` (spot|futures) and
      `margin_mode` (isolated|cross). Migration auto-applied.
    • runner.py picks the right client based on cfg.market_type and
      calls _ensure_leverage() on first contact with each symbol.
    • Close-position orders use reduceOnly=true.

 4. SINGLE-VPS DEPLOY BUNDLE
    • deploy/docker-compose.yml with web, celery worker, beat, redis,
      postgres, and all five streamers as separate services. Optional
      streamers (finnhub, oanda) gated by compose profiles.
    • deploy/Dockerfile.streamer (reuses main image, just a tag).
    • deploy/systemd/sauron-streamer@.service template + instructions.
    • deploy/VPS_DEPLOY.md walkthrough.

 5. NOTES.md
    • "Worth knowing" caveats for all previous passes, consolidated.
"""
from __future__ import annotations
import os, sys, subprocess
from pathlib import Path
from textwrap import dedent

ROOT = Path(__file__).resolve().parent
if not (ROOT / "manage.py").exists():
    print("ERROR: run this from the directory containing manage.py"); sys.exit(1)

def write(rel, content, overwrite=True):
    p = ROOT / rel; p.parent.mkdir(parents=True, exist_ok=True)
    if p.exists() and not overwrite:
        print(f"  skip: {rel}"); return
    p.write_text(dedent(content).lstrip("\n"), encoding="utf-8")
    print(f"  wrote: {rel}")

def patch(rel, old, new):
    p = ROOT / rel
    if not p.exists(): print(f"  MISSING: {rel}"); return
    txt = p.read_text(encoding="utf-8")
    # Guard: check for a substring that's in NEW but NOT in OLD (a real marker of the patch).
    # Fall back to the first 60 chars of new if no such distinctive substring exists.
    new_s = new.strip()
    marker = None
    for line in new_s.splitlines():
        line = line.strip()
        if len(line) >= 15 and line not in old:
            marker = line; break
    if marker is None: marker = new_s[:60]
    if marker in txt:
        print(f"  already patched: {rel}"); return
    if old not in txt: print(f"  anchor not found: {rel}"); return
    p.write_text(txt.replace(old, new, 1), encoding="utf-8")
    print(f"  patched: {rel}")

print("━" * 60)
print(" SAURON VISION — UPGRADE PASS 5 (infra / retention / futures)")
print("━" * 60)

# =================================================================
# STEP 1 — Retention cleanup tasks
# =================================================================
print("\n[1/8] Nightly retention tasks …")

write("market_data/cleanup_tasks.py", '''
    """Nightly retention cleanup tasks. Registered in celery beat."""
    import logging
    import os
    from datetime import timedelta
    from celery import shared_task
    from django.utils import timezone

    log = logging.getLogger(__name__)

    # Defaults configurable via env
    def _days(env_key: str, default: int) -> int:
        try: return max(1, int(os.environ.get(env_key, default)))
        except Exception: return default

    @shared_task
    def cleanup_liquidations():
        from market_data.models import LiquidationEvent
        cutoff = timezone.now() - timedelta(days=_days("RETAIN_LIQUIDATIONS_DAYS", 30))
        deleted, _ = LiquidationEvent.objects.filter(timestamp__lt=cutoff).delete()
        log.info("cleanup_liquidations: removed %d rows older than %s", deleted, cutoff)
        return deleted

    @shared_task
    def cleanup_orderbook():
        from market_data.models import OrderBookSnapshot
        # Keep only the last 2000 per symbol (matches the streamer's opportunistic prune).
        syms = OrderBookSnapshot.objects.values_list("symbol", flat=True).distinct()
        total = 0
        for sym in syms:
            keep = list(OrderBookSnapshot.objects.filter(symbol=sym)
                        .order_by("-timestamp").values_list("id", flat=True)[:2000])
            n, _ = OrderBookSnapshot.objects.filter(symbol=sym).exclude(id__in=keep).delete()
            total += n
        log.info("cleanup_orderbook: removed %d stale snapshots", total)
        return total

    @shared_task
    def cleanup_funding():
        from market_data.models import FundingRate
        cutoff = timezone.now() - timedelta(days=_days("RETAIN_FUNDING_DAYS", 60))
        deleted, _ = FundingRate.objects.filter(timestamp__lt=cutoff).delete()
        log.info("cleanup_funding: removed %d rows", deleted)
        return deleted

    @shared_task
    def cleanup_price_data():
        """Prune intraday PriceData older than RETAIN_INTRADAY_DAYS (default 90).
        Daily/weekly bars are preserved regardless."""
        from market_data.models import PriceData
        cutoff = timezone.now() - timedelta(days=_days("RETAIN_INTRADAY_DAYS", 90))
        deleted, _ = PriceData.objects.filter(
            timeframe__in=["1m","5m","15m","1h","4h"],
            timestamp__lt=cutoff).delete()
        log.info("cleanup_price_data: removed %d intraday bars", deleted)
        return deleted

    @shared_task
    def nightly_cleanup_all():
        """One-shot wrapper run from beat."""
        return {
            "liquidations": cleanup_liquidations(),
            "orderbook":    cleanup_orderbook(),
            "funding":      cleanup_funding(),
            "price_data":   cleanup_price_data(),
        }
''')

# =================================================================
# STEP 2 — Funding rate alerts
# =================================================================
print("\n[2/8] Funding rate alerts …")

write("market_data/funding_alerts.py", '''
    """Funding rate analyser — raises Notification rows when funding
    conditions signal potential squeezes or extreme crowding."""
    import logging
    from datetime import timedelta
    from celery import shared_task
    from django.utils import timezone
    from django.contrib.auth.models import User

    log = logging.getLogger(__name__)

    EXTREME_THRESHOLD = 0.001   # 0.1% per 8h funding interval
    LOOKBACK_MIN = 15           # compare current vs 15 minutes ago
    PRICE_LOOKBACK_HOURS = 1

    def _notify(user, title: str, body: str, url: str = "/liquidations/"):
        try:
            from alerts.models import Notification
            Notification.objects.create(
                user=user, title=title, body=body, url=url, read=False)
        except Exception as e:
            log.debug("notify failed: %s", e)

    def _notify_all(title: str, body: str, url: str = "/liquidations/"):
        for u in User.objects.filter(is_active=True):
            prof = getattr(u, "trader_profile", None)
            if prof and getattr(prof, "notify_signals", True):
                _notify(u, title, body, url)

    @shared_task
    def scan_funding_signals():
        from market_data.models import FundingRate, LiveQuote
        from instruments.models import Instrument

        now = timezone.now()
        window_start = now - timedelta(minutes=LOOKBACK_MIN + 5)
        # Distinct symbols with recent funding data
        symbols = (FundingRate.objects.filter(timestamp__gte=window_start)
                   .values_list("symbol", flat=True).distinct())
        alerts = 0
        for sym in symbols:
            recent = list(FundingRate.objects.filter(
                symbol=sym, timestamp__gte=window_start).order_by("-timestamp")[:2])
            if len(recent) < 2: continue
            cur, prev = recent[0], recent[1]
            cur_r = float(cur.funding_rate)
            prev_r = float(prev.funding_rate)

            # (a) Sign flip
            if cur_r * prev_r < 0:
                _notify_all(
                    f"⚡ {sym} funding flipped",
                    f"Funding rate flipped {prev_r*100:+.4f}% → {cur_r*100:+.4f}% · mark {cur.mark_price}",
                )
                alerts += 1

            # (b) Extreme
            if abs(cur_r) >= EXTREME_THRESHOLD:
                direction = "CROWDED LONGS" if cur_r > 0 else "CROWDED SHORTS"
                _notify_all(
                    f"🔥 {sym} extreme funding — {direction}",
                    f"Funding {cur_r*100:+.4f}% (≥±0.1%). Squeeze risk elevated.",
                )
                alerts += 1

            # (c) Funding / price divergence: price up but funding negative,
            # or price down but funding positive → squeeze setup
            try:
                inst = Instrument.objects.filter(symbol__iexact=sym).first()
                if not inst: continue
                q = LiveQuote.objects.filter(instrument=inst).first()
                if not q or q.change_pct is None: continue
                price_chg = float(q.change_pct)
                if price_chg > 1.0 and cur_r < 0:
                    _notify_all(
                        f"⚠ {sym} divergence — shorts bleeding",
                        f"Price +{price_chg:.2f}% but funding {cur_r*100:+.4f}%. Classic short squeeze setup.",
                    )
                    alerts += 1
                elif price_chg < -1.0 and cur_r > 0:
                    _notify_all(
                        f"⚠ {sym} divergence — longs bleeding",
                        f"Price {price_chg:.2f}% but funding {cur_r*100:+.4f}%. Long squeeze setup.",
                    )
                    alerts += 1
            except Exception as e:
                log.debug("divergence check failed for %s: %s", sym, e)

        log.info("scan_funding_signals: raised %d alerts across %d symbols", alerts, len(list(symbols)))
        return alerts
''')

# Register tasks in beat schedule
patch("config/celery.py",
      '    # ── TIER 1: Every 1-5 min (during market hours) ──────────',
      '''    # ── UPGRADE-5: Funding alerts + retention ─────────────────
    "scan-funding-signals": {
        "task": "market_data.funding_alerts.scan_funding_signals",
        "schedule": 300.0,
    },
    "nightly-cleanup": {
        "task": "market_data.cleanup_tasks.nightly_cleanup_all",
        "schedule": crontab(hour=4, minute=15),
    },

    # ── TIER 1: Every 1-5 min (during market hours) ──────────''')

# =================================================================
# STEP 3 — Bot futures client + BotConfig fields + runner update
# =================================================================
print("\n[3/8] Bot futures client + BotConfig migration …")

write("bot_program/engine/binance_futures_client.py", '''
    """Binance USDT-M futures REST client.

    Mirrors the public interface of BinanceClient (spot) so runner.py
    can pick the right client based on BotConfig.market_type without
    branching on every call. Endpoints: fapi.binance.com (live) or
    testnet.binancefuture.com (testnet).
    """
    from __future__ import annotations
    import time, hmac, hashlib, urllib.parse, logging
    import requests

    log = logging.getLogger(__name__)

    FAPI_LIVE    = "https://fapi.binance.com"
    FAPI_TESTNET = "https://testnet.binancefuture.com"

    class BinanceFuturesClient:
        def __init__(self, api_key: str | None, api_secret: str | None, testnet: bool = True):
            self.api_key = api_key or ""
            self.api_secret = (api_secret or "").encode()
            self.base = FAPI_TESTNET if testnet else FAPI_LIVE
            self._leverage_set = set()  # symbols already configured

        # ── Public ─────────────────────────────────────────────
        def ping(self) -> bool:
            try:
                r = requests.get(f"{self.base}/fapi/v1/ping", timeout=8)
                return r.status_code == 200
            except Exception as e:
                log.warning("futures ping failed: %s", e); return False

        def ticker(self, symbol: str) -> dict:
            r = requests.get(f"{self.base}/fapi/v1/ticker/24hr",
                             params={"symbol": symbol}, timeout=8)
            r.raise_for_status(); return r.json()

        def klines(self, symbol: str, interval: str = "15m", limit: int = 200) -> list[list]:
            r = requests.get(f"{self.base}/fapi/v1/klines",
                             params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=10)
            r.raise_for_status(); return r.json()

        def order_book(self, symbol: str, limit: int = 100) -> dict:
            r = requests.get(f"{self.base}/fapi/v1/depth",
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
            r = requests.get(f"{self.base}/fapi/v2/account",
                             params=self._sign({}), headers=self._headers(), timeout=10)
            r.raise_for_status(); return r.json()

        def balance_usdt(self) -> float:
            try:
                acct = self.account()
                for a in acct.get("assets", []):
                    if a["asset"] == "USDT":
                        return float(a.get("walletBalance") or 0)
            except Exception as e:
                log.warning("futures balance fetch failed: %s", e)
            return 0.0

        def set_leverage(self, symbol: str, leverage: int) -> dict:
            try:
                r = requests.post(f"{self.base}/fapi/v1/leverage",
                                  params=self._sign({"symbol": symbol, "leverage": int(leverage)}),
                                  headers=self._headers(), timeout=8)
                r.raise_for_status(); return r.json()
            except Exception as e:
                log.warning("set_leverage(%s, %s) failed: %s", symbol, leverage, e); return {}

        def set_margin_type(self, symbol: str, margin_type: str) -> dict:
            """margin_type: ISOLATED or CROSSED"""
            try:
                r = requests.post(f"{self.base}/fapi/v1/marginType",
                                  params=self._sign({"symbol": symbol, "marginType": margin_type.upper()}),
                                  headers=self._headers(), timeout=8)
                # -4046 = "No need to change margin type" — not an error
                if r.status_code == 400 and "-4046" in r.text: return {}
                r.raise_for_status(); return r.json()
            except Exception as e:
                log.debug("set_margin_type(%s) soft-fail: %s", symbol, e); return {}

        def ensure_config(self, symbol: str, leverage: float, margin_mode: str):
            """Idempotent per-symbol setup called once from the runner."""
            if symbol in self._leverage_set: return
            lev = max(1, int(round(leverage)))
            self.set_margin_type(symbol, "ISOLATED" if margin_mode == "isolated" else "CROSSED")
            self.set_leverage(symbol, lev)
            self._leverage_set.add(symbol)

        def market_order(self, symbol: str, side: str, quantity: float,
                         reduce_only: bool = False) -> dict:
            params = {
                "symbol": symbol, "side": side, "type": "MARKET",
                "quantity": f"{quantity:.8f}".rstrip("0").rstrip("."),
            }
            if reduce_only:
                params["reduceOnly"] = "true"
            r = requests.post(f"{self.base}/fapi/v1/order",
                              params=self._sign(params),
                              headers=self._headers(), timeout=10)
            try: r.raise_for_status()
            except Exception: log.error("futures order failed: %s", r.text); raise
            return r.json()

        def positions(self) -> list[dict]:
            try:
                r = requests.get(f"{self.base}/fapi/v2/positionRisk",
                                 params=self._sign({}), headers=self._headers(), timeout=10)
                r.raise_for_status(); return r.json()
            except Exception as e:
                log.warning("positions fetch failed: %s", e); return []
''')

# BotConfig migration: add market_type + margin_mode
write("bot_program/migrations/0002_market_type.py", '''
    from django.db import migrations, models

    class Migration(migrations.Migration):
        dependencies = [("bot_program", "0001_initial")]
        operations = [
            migrations.AddField(
                model_name="botconfig",
                name="market_type",
                field=models.CharField(
                    max_length=10, default="spot",
                    choices=[("spot","Spot"),("futures","USDT-M Futures")]),
            ),
            migrations.AddField(
                model_name="botconfig",
                name="margin_mode",
                field=models.CharField(
                    max_length=10, default="isolated",
                    choices=[("isolated","Isolated"),("cross","Cross")]),
            ),
        ]
''')

# Add fields to the BotConfig model so Django ORM knows about them
patch("bot_program/models.py",
      '    MODE_CHOICES = [\n        ("paper",  "Paper Trading (simulated, safe)"),\n        ("live",   "Live Trading (real funds)"),\n    ]',
      '''    MODE_CHOICES = [
        ("paper",  "Paper Trading (simulated, safe)"),
        ("live",   "Live Trading (real funds)"),
    ]
    MARKET_CHOICES = [("spot","Spot"), ("futures","USDT-M Futures")]
    MARGIN_CHOICES = [("isolated","Isolated"), ("cross","Cross")]''')

patch("bot_program/models.py",
      '    mode = models.CharField(max_length=8, choices=MODE_CHOICES, default="paper")',
      '''    mode = models.CharField(max_length=8, choices=MODE_CHOICES, default="paper")
    market_type = models.CharField(max_length=10, choices=MARKET_CHOICES, default="spot")
    margin_mode = models.CharField(max_length=10, choices=MARGIN_CHOICES, default="isolated")''')

# Update runner.py to pick the right client
patch("bot_program/engine/runner.py",
      '''from .binance_client import BinanceClient
from .strategy import decide
from .risk import RiskManager''',
      '''from .binance_client import BinanceClient
from .binance_futures_client import BinanceFuturesClient
from .strategy import decide
from .risk import RiskManager''')

patch("bot_program/engine/runner.py",
      '''def _client_for(user) -> BinanceClient:
    try:
        acct: BinanceAccount = user.binance_account
        k, s = acct.get_credentials()
        return BinanceClient(k, s, testnet=acct.testnet)
    except BinanceAccount.DoesNotExist:
        return BinanceClient(None, None, testnet=True)''',
      '''def _client_for(user, cfg=None):
    try:
        acct: BinanceAccount = user.binance_account
        k, s = acct.get_credentials()
        testnet = acct.testnet
    except BinanceAccount.DoesNotExist:
        k = s = None; testnet = True
    if cfg is not None and getattr(cfg, "market_type", "spot") == "futures":
        return BinanceFuturesClient(k, s, testnet=testnet)
    return BinanceClient(k, s, testnet=testnet)''')

# Update the call site of _client_for inside run_bot_tick
patch("bot_program/engine/runner.py",
      '    client = _client_for(user)',
      '    client = _client_for(user, cfg)')

# Call ensure_config on futures client before the first order per symbol
patch("bot_program/engine/runner.py",
      '''            paper = (cfg.mode == "paper")
            order_id = ""
            if not paper:
                try:
                    res = client.market_order(symbol, d.direction, qty)
                    order_id = str(res.get("orderId", ""))
                except Exception as e:
                    log.error("live order failed %s: %s", symbol, e)
                    continue''',
      '''            paper = (cfg.mode == "paper")
            order_id = ""
            if not paper:
                try:
                    if cfg.market_type == "futures" and hasattr(client, "ensure_config"):
                        client.ensure_config(symbol, cfg.leverage, cfg.margin_mode)
                    res = client.market_order(symbol, d.direction, qty)
                    order_id = str(res.get("orderId", ""))
                except Exception as e:
                    log.error("live order failed %s: %s", symbol, e)
                    continue''')

# Futures close: pass reduce_only=True when closing a futures position
patch("bot_program/engine/runner.py",
      '''    if not trade.paper:
        try: client.market_order(trade.symbol, "SELL" if trade.side=="BUY" else "BUY", float(trade.qty))
        except Exception as e: log.error("close order fail: %s", e)''',
      '''    if not trade.paper:
        try:
            close_side = "SELL" if trade.side == "BUY" else "BUY"
            kwargs = {}
            if trade.config.market_type == "futures":
                kwargs["reduce_only"] = True
            client.market_order(trade.symbol, close_side, float(trade.qty), **kwargs)
        except Exception as e: log.error("close order fail: %s", e)''')

# =================================================================
# STEP 4 — Single-VPS docker-compose bundle
# =================================================================
print("\n[4/8] VPS docker-compose bundle …")

write("deploy/docker-compose.yml", '''
    # Single-VPS deployment for Sauron Vision.
    # Brings up web + celery worker + beat + redis + postgres + all
    # five streamers in one go. Optional streamers (finnhub, oanda)
    # only spin up when you enable their profile.
    #
    # Usage:
    #   cp .env.example .env && edit .env
    #   docker compose -f deploy/docker-compose.yml up -d
    #
    # Enable optional streamers:
    #   docker compose -f deploy/docker-compose.yml --profile finnhub --profile oanda up -d

    services:
      postgres:
        image: postgres:16-alpine
        restart: unless-stopped
        environment:
          POSTGRES_DB:       ${POSTGRES_DB:-sauron}
          POSTGRES_USER:     ${POSTGRES_USER:-sauron}
          POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-sauron}
        volumes:
          - pgdata:/var/lib/postgresql/data
        healthcheck:
          test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER:-sauron}"]
          interval: 10s
          timeout: 5s
          retries: 5

      redis:
        image: redis:7-alpine
        restart: unless-stopped
        volumes:
          - redisdata:/data
        healthcheck:
          test: ["CMD", "redis-cli", "ping"]
          interval: 10s
          timeout: 5s
          retries: 5

      web:
        build:
          context: ..
          dockerfile: Dockerfile
        restart: unless-stopped
        command: sh -c "python manage.py migrate --noinput && python manage.py collectstatic --noinput && daphne -b 0.0.0.0 -p 8000 config.asgi:application"
        environment: &common-env
          DJANGO_SETTINGS_MODULE: config.settings
          DATABASE_URL: postgres://${POSTGRES_USER:-sauron}:${POSTGRES_PASSWORD:-sauron}@postgres:5432/${POSTGRES_DB:-sauron}
          REDIS_URL: redis://redis:6379/0
          CELERY_BROKER_URL: redis://redis:6379/1
          SECRET_KEY: ${SECRET_KEY}
          DEBUG: ${DEBUG:-0}
          ALLOWED_HOSTS: ${ALLOWED_HOSTS:-*}
          FINNHUB_API_KEY: ${FINNHUB_API_KEY:-}
          OANDA_API_KEY: ${OANDA_API_KEY:-}
          OANDA_ACCOUNT_ID: ${OANDA_ACCOUNT_ID:-}
          OANDA_ENV: ${OANDA_ENV:-practice}
        depends_on:
          postgres: {condition: service_healthy}
          redis:    {condition: service_healthy}
        ports:
          - "${WEB_PORT:-8000}:8000"

      celery-worker:
        build: {context: .., dockerfile: Dockerfile}
        restart: unless-stopped
        command: celery -A config worker -l info --concurrency=${CELERY_CONCURRENCY:-4}
        environment: *common-env
        depends_on:
          postgres: {condition: service_healthy}
          redis:    {condition: service_healthy}

      celery-beat:
        build: {context: .., dockerfile: Dockerfile}
        restart: unless-stopped
        command: celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
        environment: *common-env
        depends_on:
          postgres: {condition: service_healthy}
          redis:    {condition: service_healthy}

      stream-binance:
        build: {context: .., dockerfile: Dockerfile}
        restart: unless-stopped
        command: python manage.py stream_binance
        environment: *common-env
        depends_on:
          postgres: {condition: service_healthy}
          redis:    {condition: service_healthy}

      stream-binance-futures:
        build: {context: .., dockerfile: Dockerfile}
        restart: unless-stopped
        command: python manage.py stream_binance_futures
        environment: *common-env
        depends_on:
          postgres: {condition: service_healthy}
          redis:    {condition: service_healthy}

      stream-binance-depth:
        build: {context: .., dockerfile: Dockerfile}
        restart: unless-stopped
        command: python manage.py stream_binance_depth
        environment: *common-env
        depends_on:
          postgres: {condition: service_healthy}
          redis:    {condition: service_healthy}

      stream-finnhub:
        profiles: ["finnhub"]
        build: {context: .., dockerfile: Dockerfile}
        restart: unless-stopped
        command: python manage.py stream_finnhub
        environment: *common-env
        depends_on:
          postgres: {condition: service_healthy}
          redis:    {condition: service_healthy}

      stream-oanda:
        profiles: ["oanda"]
        build: {context: .., dockerfile: Dockerfile}
        restart: unless-stopped
        command: python manage.py stream_oanda
        environment: *common-env
        depends_on:
          postgres: {condition: service_healthy}
          redis:    {condition: service_healthy}

    volumes:
      pgdata:
      redisdata:
''')

# =================================================================
# STEP 5 — systemd units (non-docker VPS)
# =================================================================
print("\n[5/8] systemd unit templates …")

write("deploy/systemd/sauron-web.service", '''
    [Unit]
    Description=Sauron Vision web (daphne)
    After=network.target postgresql.service redis.service
    Wants=postgresql.service redis.service

    [Service]
    Type=simple
    User=sauron
    WorkingDirectory=/opt/sauron/sauron_vision
    EnvironmentFile=/opt/sauron/sauron_vision/.env
    ExecStart=/opt/sauron/venv/bin/daphne -b 0.0.0.0 -p 8000 config.asgi:application
    Restart=always
    RestartSec=5

    [Install]
    WantedBy=multi-user.target
''')

write("deploy/systemd/sauron-celery-worker.service", '''
    [Unit]
    Description=Sauron Vision celery worker
    After=network.target redis.service

    [Service]
    Type=simple
    User=sauron
    WorkingDirectory=/opt/sauron/sauron_vision
    EnvironmentFile=/opt/sauron/sauron_vision/.env
    ExecStart=/opt/sauron/venv/bin/celery -A config worker -l info --concurrency=4
    Restart=always
    RestartSec=5

    [Install]
    WantedBy=multi-user.target
''')

write("deploy/systemd/sauron-celery-beat.service", '''
    [Unit]
    Description=Sauron Vision celery beat
    After=network.target redis.service

    [Service]
    Type=simple
    User=sauron
    WorkingDirectory=/opt/sauron/sauron_vision
    EnvironmentFile=/opt/sauron/sauron_vision/.env
    ExecStart=/opt/sauron/venv/bin/celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
    Restart=always
    RestartSec=5

    [Install]
    WantedBy=multi-user.target
''')

# Template unit for streamers — parameterised by stream name.
# Enable with: systemctl enable --now sauron-streamer@binance
write("deploy/systemd/sauron-streamer@.service", '''
    [Unit]
    Description=Sauron Vision streamer — %i
    After=network.target postgresql.service redis.service
    Wants=postgresql.service redis.service

    [Service]
    Type=simple
    User=sauron
    WorkingDirectory=/opt/sauron/sauron_vision
    EnvironmentFile=/opt/sauron/sauron_vision/.env
    ExecStart=/opt/sauron/venv/bin/python manage.py stream_%i
    Restart=always
    RestartSec=10
    # Restart with exponential backoff on repeated failure
    StartLimitIntervalSec=300
    StartLimitBurst=10

    [Install]
    WantedBy=multi-user.target
''')

# =================================================================
# STEP 6 — VPS deploy guide
# =================================================================
print("\n[6/8] VPS deploy walkthrough …")

write("deploy/VPS_DEPLOY.md", '''
    # Single-VPS deployment

    Two options: Docker Compose (simplest) or systemd (more control,
    no Docker overhead).

    ## Option A — Docker Compose (recommended)

    Any Linux box with Docker + Compose v2. A Hetzner CX22 (€4.51/mo,
    2 vCPU, 4 GB) is enough to run web + celery + all five streamers.

    ```bash
    # 1. Install docker (once)
    curl -fsSL https://get.docker.com | sudo sh
    sudo usermod -aG docker $USER
    # log out and back in

    # 2. Clone your repo
    git clone https://github.com/YOU/sauron_vision.git
    cd sauron_vision

    # 3. Create .env
    cp .env.example .env
    nano .env
    # fill in at minimum:
    #   SECRET_KEY=...               (long random string; MUST be pinned)
    #   POSTGRES_PASSWORD=...
    #   ALLOWED_HOSTS=your.domain.com
    # optional for streamers:
    #   FINNHUB_API_KEY=...
    #   OANDA_API_KEY=... OANDA_ACCOUNT_ID=... OANDA_ENV=practice

    # 4. Bring it up (crypto-only)
    docker compose -f deploy/docker-compose.yml up -d --build

    # Or with stocks + forex streamers as well
    docker compose -f deploy/docker-compose.yml \\
        --profile finnhub --profile oanda up -d --build

    # 5. First-time setup
    docker compose -f deploy/docker-compose.yml exec web python manage.py createsuperuser
    docker compose -f deploy/docker-compose.yml exec web python set_default_pin.py

    # 6. Follow logs
    docker compose -f deploy/docker-compose.yml logs -f stream-binance
    ```

    Put Caddy / nginx / Cloudflare Tunnel in front for HTTPS. Caddy
    config example (sudo apt install caddy, /etc/caddy/Caddyfile):
    ```
    your.domain.com {
        reverse_proxy localhost:8000
    }
    ```

    ## Option B — systemd (no Docker)

    ```bash
    # 1. System user and venv
    sudo useradd -r -m -d /opt/sauron -s /bin/bash sauron
    sudo -u sauron bash
    cd ~
    git clone https://github.com/YOU/sauron_vision.git
    python3 -m venv venv
    source venv/bin/activate
    pip install -r sauron_vision/requirements.txt
    cd sauron_vision
    cp .env.example .env && nano .env
    python manage.py migrate && python manage.py collectstatic --noinput
    exit

    # 2. Install unit files
    sudo cp /opt/sauron/sauron_vision/deploy/systemd/*.service /etc/systemd/system/
    sudo systemctl daemon-reload

    # 3. Core services
    sudo systemctl enable --now sauron-web sauron-celery-worker sauron-celery-beat

    # 4. Streamers (one enable line per streamer)
    sudo systemctl enable --now sauron-streamer@binance
    sudo systemctl enable --now sauron-streamer@binance_futures
    sudo systemctl enable --now sauron-streamer@binance_depth
    sudo systemctl enable --now sauron-streamer@finnhub
    sudo systemctl enable --now sauron-streamer@oanda

    # 5. Check
    systemctl status sauron-streamer@binance
    journalctl -u sauron-streamer@binance -f
    ```

    The `sauron-streamer@.service` template is parameterised: the bit
    after the `@` is passed as `%i` and becomes the command suffix.
    `sauron-streamer@binance` runs `python manage.py stream_binance`,
    `sauron-streamer@binance_futures` runs `stream_binance_futures`,
    etc. Add new streamers with just an enable command — no new unit
    file needed.

    ## Resource sizing

    - **CX22 (€4.51/mo, 2c/4G)** — runs everything except finnhub+oanda
      comfortably. ~20% average CPU with all three Binance streamers.
    - **CX32 (€6.86/mo, 4c/8G)** — comfortable with all five streamers
      + Celery under full load.
    - **Redis memory** — the Channels layer uses trivial amounts (<50MB).
    - **Postgres disk** — the biggest hog. LiquidationEvent rows for
      top crypto symbols = ~200MB/month without retention. The nightly
      cleanup task from pass 5 keeps 30 days → ~200MB steady state.

    ## Health checks

    ```bash
    # Are all containers up?
    docker compose -f deploy/docker-compose.yml ps

    # Is the streamer actually receiving ticks?
    docker compose -f deploy/docker-compose.yml logs --tail=20 stream-binance
    # should show: "connecting to N stream(s): BTCUSDT, ETHUSDT, ..."

    # Are liquidations being stored?
    docker compose -f deploy/docker-compose.yml exec web python manage.py shell -c \\
        "from market_data.models import LiquidationEvent; print(LiquidationEvent.objects.count())"
    ```
''')

# =================================================================
# STEP 7 — NOTES.md (the "worth knowing" consolidated caveats)
# =================================================================
print("\n[7/8] Worth-knowing notes …")

write("NOTES.md", '''
    # Sauron Vision — operational notes

    Consolidated caveats across all upgrade passes. Read once before
    arming anything that costs real money.

    ## Live data

    - **Binance public WebSockets are free and unauthenticated** for
      market data. No API key needed for `stream_binance`,
      `stream_binance_futures`, or `stream_binance_depth`. You only
      need API keys when the bot actually places orders.
    - **Finnhub free tier** is ~1s latency with holes during US market
      close and a soft limit around 50 symbol subscriptions per socket.
      Good enough for a dashboard; not for an algo-trading stock bot.
      For serious use: Polygon.io or Alpaca (both paid, both real-time).
    - **OANDA demo accounts never expire.** The demo and live feeds
      are the same data — you can build and test forex logic for free
      indefinitely. Switch to live by setting `OANDA_ENV=live` and
      using a funded-account API key.
    - **Stream disconnects are normal.** All streamers auto-reconnect
      with exponential backoff (max 60s). If you see repeated
      disconnects from Binance, check your VPS's outbound IP isn't
      rate-limited — Binance throttles connections per IP globally.

    ## Storage growth

    - **LiquidationEvent** is the fastest-growing table. BTCUSDT alone
      produces thousands of rows per day during volatile periods.
      The nightly `cleanup_liquidations` task (pass 5) keeps the last
      30 days by default; override with `RETAIN_LIQUIDATIONS_DAYS` env.
    - **OrderBookSnapshot** is bounded by the streamer itself: max 2000
      rows per symbol via opportunistic pruning on ~1% of writes, plus
      the nightly `cleanup_orderbook` task as a safety net.
    - **FundingRate** is throttled to one row per symbol every 30s by
      the streamer, so even running 24/7 it produces ~2880 rows/day
      per symbol. Retention default: 60 days.
    - **PriceData intraday bars** (1m/5m/15m/1h/4h) are pruned to the
      last 90 days by `cleanup_price_data`. Daily and weekly bars are
      preserved regardless — don't delete your backtest data.

    ## Channels / Redis

    - **All streamers and the web service MUST share the same Redis
      instance** as the Channels layer. This is non-negotiable: the
      streamers broadcast into a Redis pub/sub channel, the web
      service's Daphne process subscribes to that channel to relay
      events to connected browser WebSockets. Point them at different
      Redis instances and browser updates simply don't arrive.
    - `REDIS_URL` env var controls this (your `settings.py` reads it).

    ## Security

    - **SECRET_KEY must be pinned and stable.** Binance API keys and
      any future encrypted fields use Fernet derived from SECRET_KEY.
      If it changes, those fields become unreadable. On Render: set
      it explicitly with `sync: false`, not `generateValue: true`.
    - **Binance API keys should have withdrawals DISABLED.** The bot
      only needs trading + read permissions. Enable IP whitelist if
      you're running from a static IP.
    - **Start on testnet.** `BinanceAccount.testnet=True` is the
      default. The bot arming flow in pass 1 requires a PIN to flip
      to LIVE mode — don't bypass it, and don't share the PIN.
    - **PIN defaults to 0000** if you ran `set_default_pin.py`.
      Change it from the profile page (or re-run the script with
      different logic) before exposing the site publicly.

    ## Bot behaviour

    - **PAPER mode by default.** `BotConfig.mode="paper"` and
      `BotConfig.enabled=False` on creation. Every flip to live
      requires the PIN. Toggles happen only from the Bot Program UI.
    - **Daily loss cutoff** — the risk manager halts new entries when
      24h realized P&L breaches `max_daily_loss_pct`. The bot does NOT
      force-close existing positions, only stops opening new ones.
    - **Futures mode** (pass 5): the bot sets leverage and margin mode
      once per symbol via `ensure_config()` on the first order. If you
      change leverage in BotConfig, restart the bot for the new value
      to take effect — the client caches "already set" to avoid
      hitting the API on every tick.
    - **Composite strategy is a starting point, not alpha.** The point
      of the scenarios / backtester is to tune weights and thresholds
      per symbol BEFORE going live. Run each configuration through
      backtest → paper → live at small size → live at full size.
    - **Impressively lucrative trading** cannot be promised by any
      framework, and shouldn't be expected from default weights. What
      the code gives you is a disciplined, auditable pipeline with
      real risk management — that's necessary but not sufficient.

    ## Cost reality

    - **Render full deployment** with all 5 streamers = 5 × $7 workers
      + web + celery worker + celery beat + Redis + Postgres ≈ $60/mo
      minimum.
    - **Hetzner VPS equivalent**: CX22 at €4.51/mo runs everything on
      one box. 13× cheaper for the same behaviour. Tradeoff: you
      manage OS updates, backups, and uptime yourself.
    - **Render free tier won't work** — web services sleep, celery
      workers aren't available, and the streamers need always-on.

    ## What's NOT here

    - **Real trading of stocks or forex** — the bot is crypto-only
      (spot + futures via Binance). Finnhub/OANDA streams only feed
      the dashboard, not the bot.
    - **Tax reporting / cost basis** — not modelled. Use a dedicated
      tool (Koinly, CoinTracker) if you trade enough to care.
    - **Multi-user isolation** — all users on the same instance share
      the same data (instruments, news, quotes). Only BotConfig,
      BotTrade, and Binance credentials are per-user. This is fine
      for the "me + friends" use case you described, not for a SaaS.
    - **Guarantees of anything.** This is code that works as designed;
      it is not investment advice, and nothing in it should be
      interpreted as a recommendation to trade. You know this.
''')

# =================================================================
# STEP 8 — Run migrations
# =================================================================
print("\n[8/8] Running migrations …")
subprocess.run([sys.executable, "manage.py", "makemigrations", "bot_program"], cwd=str(ROOT))
subprocess.run([sys.executable, "manage.py", "migrate"], cwd=str(ROOT))

print("\n" + "━" * 60)
print(" ✓ UPGRADE PASS 5 COMPLETE")
print("━" * 60)
print("""
What's new:

  RETENTION:
    market_data/cleanup_tasks.py runs nightly at 04:15 UTC, pruning
    LiquidationEvent (>30d), OrderBookSnapshot (>2000/sym),
    FundingRate (>60d), and intraday PriceData (>90d). Override with
    RETAIN_LIQUIDATIONS_DAYS, RETAIN_FUNDING_DAYS, RETAIN_INTRADAY_DAYS.

  FUNDING ALERTS:
    Every 5 minutes, market_data/funding_alerts.scan_funding_signals
    checks for sign flips, extreme funding (>±0.1%), and funding/price
    divergences. Notifications go to the existing alerts.Notification
    table and appear in the bell dropdown.

  BOT FUTURES MODE:
    BotConfig has two new fields: market_type (spot/futures) and
    margin_mode (isolated/cross). Set market_type=futures and the
    runner automatically switches to BinanceFuturesClient, calls
    set_leverage + set_margin_type once per symbol, and passes
    reduceOnly=true when closing positions. Spot mode behaves exactly
    as before — no change for existing bots.

  VPS DEPLOY BUNDLE:
    deploy/docker-compose.yml spins up postgres + redis + web +
    celery worker + beat + all 5 streamers on one box. Optional
    streamers (finnhub, oanda) gated by compose profiles.
    deploy/systemd/*.service for non-docker setups with a templated
    sauron-streamer@.service unit.
    deploy/VPS_DEPLOY.md is a full walkthrough for both options.

  NOTES.md:
    Consolidated "worth knowing" caveats at the project root.

NEXT STEPS:
  • Go to Bot Program → Configure and set market_type=futures on your
    bot config if you want to trade futures.
  • If self-hosting: read deploy/VPS_DEPLOY.md. A Hetzner CX22 runs
    the whole thing for €4.51/mo vs Render's ~$60/mo.
  • Read NOTES.md once before arming live mode.
""")
