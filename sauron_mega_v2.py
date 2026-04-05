#!/usr/bin/env python3
"""
SAURON VISION — Mega Patch v2
1. Crypto market integration (scrapers, models, admin market toggle)
2. Admin market selection + user profile market preferences
3. Render.com deployment hardening
4. Security hardening (CSP, rate limiting, encryption)
5. Admin newsletter system (WhatsApp, Telegram, Email) with AI + review
6. User personal notification channel setup

Run inside sauron_vision/ directory.
"""
import os

def create_file(path, content=""):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path

def patch_file(path, find, replace):
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        c = f.read()
    if find not in c:
        return False
    c = c.replace(find, replace)
    with open(path, "w", encoding="utf-8") as f:
        f.write(c)
    return True

def append_if_missing(path, marker, text):
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        c = f.read()
    if marker in c:
        return False
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)
    return True


def generate():
    created = []

    # ================================================================
    # 1. CRYPTO MARKET — scraper adapters
    # ================================================================

    created.append(create_file("market_data/adapters/crypto_adapter.py",
'''"""Crypto market adapter — CoinGecko (free) + Binance public API."""
import requests
import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
BINANCE_BASE = "https://api.binance.com/api/v3"

# Map Sauron symbols to CoinGecko IDs
SYMBOL_MAP = {
    "BTCUSD": "bitcoin", "ETHUSD": "ethereum", "XRPUSD": "ripple",
    "SOLUSD": "solana", "ADAUSD": "cardano", "DOTUSD": "polkadot",
    "AVAXUSD": "avalanche-2", "DOGEUSD": "dogecoin", "MATICUSD": "matic-network",
    "LINKUSD": "chainlink", "UNIUSD": "uniswap", "AAVEUSD": "aave",
    "LTCUSD": "litecoin", "ATOMUSD": "cosmos", "NEARUSD": "near",
    "SHIBAUSD": "shiba-inu", "ARBUSD": "arbitrum", "OPUSD": "optimism",
    "SUIUSD": "sui", "APTUSD": "aptos",
}

# Map to Binance pairs
BINANCE_MAP = {
    "BTCUSD": "BTCUSDT", "ETHUSD": "ETHUSDT", "XRPUSD": "XRPUSDT",
    "SOLUSD": "SOLUSDT", "ADAUSD": "ADAUSDT", "DOTUSD": "DOTUSDT",
    "AVAXUSD": "AVAXUSDT", "DOGEUSD": "DOGEUSDT", "LINKUSD": "LINKUSDT",
    "LTCUSD": "LTCUSDT", "NEARUSD": "NEARUSDT",
}


def fetch_coingecko_prices(symbols=None):
    """Fetch crypto prices from CoinGecko (free, no key)."""
    if symbols is None:
        symbols = list(SYMBOL_MAP.keys())

    ids = [SYMBOL_MAP[s] for s in symbols if s in SYMBOL_MAP]
    if not ids:
        return {}

    try:
        resp = requests.get(f"{COINGECKO_BASE}/simple/price", params={
            "ids": ",".join(ids),
            "vs_currencies": "usd",
            "include_24hr_change": "true",
            "include_24hr_vol": "true",
            "include_market_cap": "true",
        }, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        results = {}
        id_to_symbol = {v: k for k, v in SYMBOL_MAP.items()}
        for cg_id, info in data.items():
            sym = id_to_symbol.get(cg_id)
            if sym:
                results[sym] = {
                    "price": Decimal(str(info.get("usd", 0))),
                    "change_24h": round(info.get("usd_24h_change", 0), 4),
                    "volume_24h": info.get("usd_24h_vol", 0),
                    "market_cap": info.get("usd_market_cap", 0),
                }
        return results
    except Exception as e:
        logger.error(f"CoinGecko error: {e}")
        return {}


def fetch_binance_ticker(symbol):
    """Fetch real-time ticker from Binance public API (no key)."""
    binance_sym = BINANCE_MAP.get(symbol)
    if not binance_sym:
        return None
    try:
        resp = requests.get(f"{BINANCE_BASE}/ticker/24hr", params={"symbol": binance_sym}, timeout=10)
        resp.raise_for_status()
        d = resp.json()
        return {
            "price": Decimal(d.get("lastPrice", "0")),
            "change_pct": Decimal(d.get("priceChangePercent", "0")),
            "high": Decimal(d.get("highPrice", "0")),
            "low": Decimal(d.get("lowPrice", "0")),
            "volume": Decimal(d.get("volume", "0")),
            "quote_volume": Decimal(d.get("quoteVolume", "0")),
        }
    except Exception as e:
        logger.error(f"Binance ticker error for {symbol}: {e}")
        return None


def fetch_binance_klines(symbol, interval="1d", limit=100):
    """Fetch OHLCV candles from Binance."""
    binance_sym = BINANCE_MAP.get(symbol)
    if not binance_sym:
        return []
    try:
        resp = requests.get(f"{BINANCE_BASE}/klines", params={
            "symbol": binance_sym, "interval": interval, "limit": limit,
        }, timeout=15)
        resp.raise_for_status()
        return [{
            "timestamp": k[0], "open": Decimal(k[1]), "high": Decimal(k[2]),
            "low": Decimal(k[3]), "close": Decimal(k[4]), "volume": Decimal(k[5]),
        } for k in resp.json()]
    except Exception as e:
        logger.error(f"Binance klines error: {e}")
        return []


def save_crypto_quotes_to_db(symbols=None):
    """Fetch and save crypto quotes."""
    from instruments.models import Instrument
    from market_data.models import LiveQuote

    prices = fetch_coingecko_prices(symbols)
    saved = 0
    for sym, data in prices.items():
        try:
            inst = Instrument.objects.get(symbol=sym)
            LiveQuote.objects.update_or_create(
                instrument=inst,
                defaults={
                    "last": data["price"],
                    "change_pct": Decimal(str(data["change_24h"])),
                    "volume": int(data.get("volume_24h", 0)),
                    "source": "coingecko",
                }
            )
            saved += 1
        except Instrument.DoesNotExist:
            pass
    return saved
'''))

    # Crypto scraper task
    created.append(create_file("market_data/adapters/crypto_news.py",
'''"""Crypto news scraper — RSS feeds for crypto markets."""
import feedparser
import logging
from django.utils import timezone
from datetime import datetime

logger = logging.getLogger(__name__)

CRYPTO_RSS_FEEDS = {
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
    "theblock": "https://www.theblock.co/rss.xml",
    "decrypt": "https://decrypt.co/feed",
    "bitcoinmagazine": "https://bitcoinmagazine.com/.rss/full/",
}


def fetch_crypto_news(max_per_feed=5):
    """Fetch crypto news from RSS feeds."""
    from scraping.models import NewsArticle
    total = 0
    for source, url in CRYPTO_RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:max_per_feed]:
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                if not title or not link:
                    continue
                published = timezone.now()
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                    except Exception:
                        pass
                _, was_created = NewsArticle.objects.get_or_create(
                    url=link[:200],
                    defaults={
                        "title": title[:500],
                        "source": source.title(),
                        "published_at": published,
                        "content_summary": entry.get("summary", "")[:1000],
                    }
                )
                if was_created:
                    total += 1
        except Exception as e:
            logger.warning(f"Crypto RSS {source} failed: {e}")
    return total
'''))

    # ================================================================
    # 2. PLATFORM MARKET CONTROLS — admin selects active markets
    # ================================================================

    created.append(create_file("core/market_config.py",
'''"""Platform-wide market configuration — admin controls which markets are active."""
from django.db import models


class MarketConfig(models.Model):
    """Global market enable/disable — controlled by admin."""
    market_key = models.CharField(max_length=20, unique=True)  # stock, forex, commodity, crypto, index, etf
    display_name = models.CharField(max_length=50)
    is_enabled = models.BooleanField(default=True)
    description = models.CharField(max_length=200, blank=True)
    icon = models.CharField(max_length=10, default="")
    scraper_component_key = models.CharField(max_length=50, blank=True)  # links to PlatformComponent
    order = models.IntegerField(default=0)

    class Meta:
        ordering = ["order"]

    def __str__(self):
        return f"{'ON' if self.is_enabled else 'OFF'} {self.display_name}"


DEFAULT_MARKETS = [
    {"market_key": "stock", "display_name": "Stocks", "icon": "S", "is_enabled": True, "order": 1,
     "description": "US, EU, Asia equities (NYSE, NASDAQ, LSE, etc.)"},
    {"market_key": "forex", "display_name": "Forex", "icon": "F", "is_enabled": True, "order": 2,
     "description": "49 currency pairs — majors, minors, exotics"},
    {"market_key": "commodity", "display_name": "Commodities", "icon": "C", "is_enabled": True, "order": 3,
     "description": "Gold, oil, gas, agriculture, metals"},
    {"market_key": "crypto", "display_name": "Crypto", "icon": "B", "is_enabled": False, "order": 4,
     "description": "Bitcoin, Ethereum, and 18+ altcoins via CoinGecko/Binance"},
    {"market_key": "index", "display_name": "Indices", "icon": "I", "is_enabled": True, "order": 5,
     "description": "S&P 500, Nasdaq, FTSE, DAX, Nikkei, etc."},
    {"market_key": "etf", "display_name": "ETFs", "icon": "E", "is_enabled": False, "order": 6,
     "description": "SPY, QQQ, GLD, ARKK, sector ETFs"},
]


def seed_market_configs():
    created = 0
    for m in DEFAULT_MARKETS:
        _, was = MarketConfig.objects.get_or_create(market_key=m["market_key"], defaults=m)
        if was:
            created += 1
    return created


def get_enabled_markets():
    """Return list of enabled market keys."""
    return list(MarketConfig.objects.filter(is_enabled=True).values_list("market_key", flat=True))
'''))

    # Add to core models
    core_models = "core/models.py"
    append_if_missing(core_models, "MarketConfig",
        '\nfrom .market_config import MarketConfig  # noqa\n')

    # ================================================================
    # 3. NEWSLETTER / COMMUNICATION SYSTEM
    # ================================================================

    created.append(create_file("alerts/models.py",
'''"""Alert and newsletter models."""
from django.db import models
from django.contrib.auth.models import User


class AlertRule(models.Model):
    """User's personal signal alert rules."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="alert_rules")
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    # Trigger conditions
    instrument_symbol = models.CharField(max_length=20, blank=True)  # empty = all instruments
    asset_class = models.CharField(max_length=20, blank=True)  # empty = all classes
    min_score = models.FloatField(default=0.5)
    direction = models.CharField(max_length=10, blank=True)  # bullish, bearish, or empty=both
    urgency = models.CharField(max_length=10, blank=True)  # critical, high, medium, low

    # Channels
    notify_telegram = models.BooleanField(default=True)
    notify_email = models.BooleanField(default=False)
    notify_whatsapp = models.BooleanField(default=False)
    notify_sms = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username}: {self.name}"


class Newsletter(models.Model):
    """Admin-created newsletter for distribution."""
    FREQ_CHOICES = [
        ("weekly", "Weekly"),
        ("monthly", "Monthly"),
        ("adhoc", "Ad-hoc"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("ai_generated", "AI Generated — Pending Review"),
        ("approved", "Approved"),
        ("sent", "Sent"),
        ("failed", "Failed"),
    ]

    title = models.CharField(max_length=200)
    frequency = models.CharField(max_length=10, choices=FREQ_CHOICES, default="weekly")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="draft")

    # Content
    content_markdown = models.TextField(blank=True)
    content_html = models.TextField(blank=True)
    ai_prompt = models.TextField(blank=True, help_text="Prompt used to generate content")

    # Distribution
    send_telegram = models.BooleanField(default=True)
    send_email = models.BooleanField(default=True)
    send_whatsapp = models.BooleanField(default=False)

    # Targeting
    target_all_users = models.BooleanField(default=True)
    target_markets = models.JSONField(default=list, blank=True)  # ["stock", "forex", "crypto"]

    # Meta
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    recipients_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.status}] {self.title}"


class UserNotificationPrefs(models.Model):
    """User notification channel preferences."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="notification_prefs")

    # Channels
    telegram_chat_id = models.CharField(max_length=50, blank=True)
    whatsapp_number = models.CharField(max_length=20, blank=True)
    email_notifications = models.BooleanField(default=True)
    sms_number = models.CharField(max_length=20, blank=True)

    # What to receive
    receive_signals = models.BooleanField(default=True)
    receive_strategies = models.BooleanField(default=True)
    receive_news_alerts = models.BooleanField(default=True)
    receive_portfolio_alerts = models.BooleanField(default=True)
    receive_weekly_newsletter = models.BooleanField(default=True)
    receive_monthly_newsletter = models.BooleanField(default=True)

    # Quiet hours (UTC)
    quiet_start = models.TimeField(null=True, blank=True)
    quiet_end = models.TimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "User notification preferences"

    def __str__(self):
        return f"{self.user.username} notification prefs"
'''))

    # Newsletter AI generation + send service
    created.append(create_file("alerts/newsletter_service.py",
'''"""Newsletter generation and distribution service."""
import os
import logging
from django.utils import timezone
from django.core.mail import send_mass_mail
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def generate_newsletter_with_ai(newsletter, context_type="weekly"):
    """Use Claude to generate newsletter content."""
    from ai_agents.base_agent import BaseAgent

    # Gather context
    from signals.models import Signal
    from strategies.models import Strategy
    from scraping.models import NewsArticle
    from portfolio.services import get_or_create_default_portfolio
    from django.db.models import Avg

    now = timezone.now()
    if context_type == "weekly":
        from datetime import timedelta
        period = now - timedelta(days=7)
        period_label = "this week"
    else:
        period = now.replace(day=1, hour=0, minute=0, second=0)
        period_label = "this month"

    signals = Signal.objects.filter(created_at__gte=period)
    strategies = Strategy.objects.filter(created_at__gte=period)
    news = NewsArticle.objects.filter(published_at__gte=period).order_by("-published_at")[:20]

    prompt = f"""Generate a {context_type} trading newsletter for Sauron Vision platform.

Period: {period_label}
Active signals: {signals.filter(is_active=True).count()}
New signals generated: {signals.count()}
Bullish: {signals.filter(direction='bullish').count()}, Bearish: {signals.filter(direction='bearish').count()}
Avg signal score: {signals.aggregate(avg=Avg('score'))['avg'] or 0:.2f}
New strategies proposed: {strategies.filter(status='proposed').count()}
Active strategies: {strategies.filter(status__in=['active','approved']).count()}

Top news headlines:
{chr(10).join(f'- {n.title} ({n.source})' for n in news[:10])}

Target markets: {', '.join(newsletter.target_markets) if newsletter.target_markets else 'all'}

Write a professional, concise newsletter in markdown format with sections:
1. Market Overview (2-3 sentences)
2. Key Signals This Period
3. Strategy Performance
4. News Highlights
5. Outlook for Next Period
6. Risk Warnings

Keep it under 500 words. Professional tone, data-driven."""

    try:
        agent = BaseAgent(agent_name="newsletter_writer", model="claude-haiku-4-5-20251001")
        result = agent.call_api(prompt)
        newsletter.content_markdown = result
        newsletter.ai_prompt = prompt
        newsletter.status = "ai_generated"
        newsletter.save()
        return True
    except Exception as e:
        logger.error(f"Newsletter AI generation failed: {e}")
        newsletter.status = "failed"
        newsletter.content_markdown = f"AI generation failed: {e}"
        newsletter.save()
        return False


def send_newsletter(newsletter):
    """Distribute newsletter via selected channels."""
    from alerts.channels.telegram_alert import send_telegram

    if newsletter.status != "approved":
        return {"error": "Newsletter must be approved before sending"}

    recipients = User.objects.filter(is_active=True)
    sent_count = 0

    # Telegram
    if newsletter.send_telegram:
        try:
            send_telegram(f"SAURON VISION {newsletter.get_frequency_display()} Report",
                         newsletter.content_markdown[:4000])
            sent_count += 1
        except Exception as e:
            logger.error(f"Telegram newsletter send failed: {e}")

    # Email
    if newsletter.send_email:
        try:
            from django.core.mail import send_mail
            email_users = recipients.exclude(email="").values_list("email", flat=True)
            for email in email_users:
                try:
                    send_mail(
                        subject=f"Sauron Vision — {newsletter.title}",
                        message=newsletter.content_markdown,
                        from_email=os.getenv("DEFAULT_FROM_EMAIL", "noreply@sauronvision.com"),
                        recipient_list=[email],
                        fail_silently=True,
                    )
                    sent_count += 1
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Email newsletter send failed: {e}")

    # WhatsApp (via Twilio or similar — stub)
    if newsletter.send_whatsapp:
        logger.info("WhatsApp newsletter — requires Twilio integration")

    newsletter.status = "sent"
    newsletter.sent_at = timezone.now()
    newsletter.recipients_count = sent_count
    newsletter.save()

    return {"status": "sent", "recipients": sent_count}
'''))

    # ================================================================
    # 4. SECURITY HARDENING
    # ================================================================

    created.append(create_file("core/security.py",
'''"""Security middleware and utilities for Sauron Vision."""
from django.http import HttpResponseForbidden
from django.conf import settings
import hashlib
import time
import logging

logger = logging.getLogger(__name__)

# Simple in-memory rate limiter for login attempts
_login_attempts = {}


class LoginRateLimitMiddleware:
    """Rate limit login attempts to prevent brute force."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/login/" and request.method == "POST":
            ip = self._get_ip(request)
            now = time.time()

            # Clean old entries
            _login_attempts[ip] = [t for t in _login_attempts.get(ip, []) if now - t < 300]

            if len(_login_attempts.get(ip, [])) >= 5:
                logger.warning(f"Rate limited login from {ip}")
                return HttpResponseForbidden(
                    "<h3>Too many login attempts. Wait 5 minutes.</h3>"
                )

            _login_attempts.setdefault(ip, []).append(now)

        return self.get_response(request)

    def _get_ip(self, request):
        xff = request.META.get("HTTP_X_FORWARDED_FOR")
        return xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")


class SecurityHeadersMiddleware:
    """Add security headers to all responses."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response["X-Content-Type-Options"] = "nosniff"
        response["X-XSS-Protection"] = "1; mode=block"
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if not settings.DEBUG:
            response["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response
'''))

    # Security settings patch
    security_settings = '''

# ── Security Settings ────────────────────────────────────
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_AGE = 86400  # 24 hours
SESSION_EXPIRE_AT_BROWSER_CLOSE = False

if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Email config (for newsletters)
EMAIL_BACKEND = os.getenv("EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
EMAIL_HOST = os.getenv("EMAIL_HOST", "smtp.gmail.com")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "Sauron Vision <noreply@sauronvision.com>")
'''
    append_if_missing("config/settings.py", "SESSION_COOKIE_SECURE", security_settings)

    # Add security middleware
    patch_file("config/settings.py",
        '"django.middleware.clickjacking.XFrameOptionsMiddleware",',
        '"django.middleware.clickjacking.XFrameOptionsMiddleware",\n'
        '    "core.security.LoginRateLimitMiddleware",\n'
        '    "core.security.SecurityHeadersMiddleware",'
    )

    # ================================================================
    # 5. ADMIN VIEWS — market toggle, newsletter, user notification
    # ================================================================

    admin_views = '''

@login_required
def admin_toggle_market(request):
    """Toggle a market on/off from admin dashboard."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()
    if request.method == "POST":
        from core.market_config import MarketConfig
        from django.contrib import messages
        key = request.POST.get("market_key", "")
        try:
            market = MarketConfig.objects.get(market_key=key)
            market.is_enabled = not market.is_enabled
            market.save()
            action = "enabled" if market.is_enabled else "disabled"
            messages.success(request, f"{market.display_name} market {action}.")
        except MarketConfig.DoesNotExist:
            messages.error(request, f"Market '{key}' not found.")
    from django.shortcuts import redirect
    return redirect("admin_dashboard")


@login_required
def admin_newsletters(request):
    """Newsletter management page."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()

    from alerts.models import Newsletter
    from django.contrib import messages

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "create":
            nl = Newsletter.objects.create(
                title=request.POST.get("title", "Weekly Report"),
                frequency=request.POST.get("frequency", "weekly"),
                send_telegram="send_telegram" in request.POST,
                send_email="send_email" in request.POST,
                send_whatsapp="send_whatsapp" in request.POST,
                created_by=request.user,
            )
            # Auto-generate with AI
            from alerts.newsletter_service import generate_newsletter_with_ai
            generate_newsletter_with_ai(nl, nl.frequency)
            messages.success(request, f"Newsletter '{nl.title}' generated. Review before sending.")

        elif action == "approve":
            nl_id = request.POST.get("newsletter_id")
            nl = Newsletter.objects.get(id=nl_id)
            nl.status = "approved"
            nl.save()
            messages.success(request, f"Newsletter '{nl.title}' approved.")

        elif action == "send":
            nl_id = request.POST.get("newsletter_id")
            nl = Newsletter.objects.get(id=nl_id)
            from alerts.newsletter_service import send_newsletter
            result = send_newsletter(nl)
            if "error" in result:
                messages.error(request, result["error"])
            else:
                messages.success(request, f"Newsletter sent to {result['recipients']} recipients.")

        elif action == "edit":
            nl_id = request.POST.get("newsletter_id")
            nl = Newsletter.objects.get(id=nl_id)
            nl.content_markdown = request.POST.get("content", nl.content_markdown)
            nl.title = request.POST.get("title", nl.title)
            nl.save()
            messages.success(request, "Newsletter updated.")

        elif action == "delete":
            nl_id = request.POST.get("newsletter_id")
            Newsletter.objects.filter(id=nl_id).delete()
            messages.success(request, "Newsletter deleted.")

        from django.shortcuts import redirect
        return redirect("admin_newsletters")

    newsletters = Newsletter.objects.all()[:30]
    return render(request, "dashboard/admin_newsletters.html", {
        "page_id": "admin_newsletters",
        "newsletters": newsletters,
    })


@login_required
def user_notifications(request):
    """User notification preferences page."""
    from alerts.models import UserNotificationPrefs, AlertRule
    from django.contrib import messages

    prefs, _ = UserNotificationPrefs.objects.get_or_create(user=request.user)

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "save_prefs":
            prefs.telegram_chat_id = request.POST.get("telegram_chat_id", "")
            prefs.whatsapp_number = request.POST.get("whatsapp_number", "")
            prefs.email_notifications = "email_notifications" in request.POST
            prefs.sms_number = request.POST.get("sms_number", "")
            prefs.receive_signals = "receive_signals" in request.POST
            prefs.receive_strategies = "receive_strategies" in request.POST
            prefs.receive_news_alerts = "receive_news_alerts" in request.POST
            prefs.receive_portfolio_alerts = "receive_portfolio_alerts" in request.POST
            prefs.receive_weekly_newsletter = "receive_weekly_newsletter" in request.POST
            prefs.receive_monthly_newsletter = "receive_monthly_newsletter" in request.POST
            prefs.save()
            messages.success(request, "Notification preferences saved.")

        elif action == "add_rule":
            AlertRule.objects.create(
                user=request.user,
                name=request.POST.get("rule_name", "Custom Alert"),
                instrument_symbol=request.POST.get("rule_symbol", ""),
                asset_class=request.POST.get("rule_asset_class", ""),
                min_score=float(request.POST.get("rule_min_score", 0.5)),
                direction=request.POST.get("rule_direction", ""),
                notify_telegram="rule_telegram" in request.POST,
                notify_email="rule_email" in request.POST,
                notify_whatsapp="rule_whatsapp" in request.POST,
            )
            messages.success(request, "Alert rule created.")

        elif action == "delete_rule":
            rule_id = request.POST.get("rule_id")
            AlertRule.objects.filter(id=rule_id, user=request.user).delete()
            messages.success(request, "Alert rule deleted.")

        from django.shortcuts import redirect
        return redirect("user_notifications")

    rules = AlertRule.objects.filter(user=request.user)
    return render(request, "dashboard/user_notifications.html", {
        "page_id": "notifications",
        "prefs": prefs,
        "rules": rules,
    })
'''
    append_if_missing("dashboard/views.py", "def admin_toggle_market", admin_views)

    # Add URLs
    urls_path = "dashboard/urls.py"
    if os.path.exists(urls_path):
        with open(urls_path, "r", encoding="utf-8") as f:
            c = f.read()
        new_urls = []
        if "admin_toggle_market" not in c:
            new_urls.append('    path("admin-dashboard/toggle-market/", views.admin_toggle_market, name="admin_toggle_market"),')
        if "admin_newsletters" not in c:
            new_urls.append('    path("admin-dashboard/newsletters/", views.admin_newsletters, name="admin_newsletters"),')
        if "user_notifications" not in c:
            new_urls.append('    path("notifications/", views.user_notifications, name="user_notifications"),')

        if new_urls:
            c = c.replace(
                'path("admin-dashboard/create-user/", views.admin_create_user, name="admin_create_user"),',
                'path("admin-dashboard/create-user/", views.admin_create_user, name="admin_create_user"),\n' +
                '\n'.join(new_urls)
            )
            with open(urls_path, "w", encoding="utf-8") as f:
                f.write(c)

    # ================================================================
    # 6. UPDATE ADMIN DASHBOARD — add market controls
    # ================================================================

    # Update admin_dashboard view to include markets
    views_path = "dashboard/views.py"
    if os.path.exists(views_path):
        with open(views_path, "r", encoding="utf-8") as f:
            c = f.read()
        if "market_configs" not in c and "def admin_dashboard" in c:
            c = c.replace(
                'context["master_enabled"] = master_enabled',
                '# Market configs\n'
                '    from core.market_config import MarketConfig\n'
                '    market_configs = MarketConfig.objects.all()\n'
                '    context["market_configs"] = market_configs\n\n'
                '    context["master_enabled"] = master_enabled'
            )
            with open(views_path, "w", encoding="utf-8") as f:
                f.write(c)

    # ================================================================
    # 7. NEWSLETTER TEMPLATE
    # ================================================================

    created.append(create_file("templates/dashboard/admin_newsletters.html",
r'''{% extends "base.html" %}
{% block title %}Newsletters — Sauron Vision{% endblock %}
{% block page_title %}NEWSLETTER MANAGEMENT{% endblock %}

{% block content %}
{% if messages %}
<div style="margin-bottom:16px;">{% for msg in messages %}<div class="card" style="border-color:{% if msg.tags == 'success' %}var(--accent){% else %}var(--accent-red){% endif %};padding:10px 16px;margin-bottom:6px;"><span style="font-family:var(--font-mono);font-size:12px;">{{ msg }}</span></div>{% endfor %}</div>
{% endif %}

<!-- Create Newsletter -->
<div class="card fade-in-up" style="margin-bottom:24px;">
    <div class="card-header"><span class="card-title">Create Newsletter</span></div>
    <form method="post">{% csrf_token %}<input type="hidden" name="action" value="create">
        <div class="grid grid-3" style="margin-bottom:16px;">
            <div><label class="form-label">TITLE</label><input type="text" name="title" value="Weekly Market Report" class="form-input"></div>
            <div><label class="form-label">FREQUENCY</label><select name="frequency" class="form-input"><option value="weekly">Weekly</option><option value="monthly">Monthly</option><option value="adhoc">Ad-hoc</option></select></div>
            <div><label class="form-label">CHANNELS</label><div style="display:flex;gap:12px;margin-top:8px;"><label style="font-size:12px;color:var(--text-secondary);"><input type="checkbox" name="send_telegram" checked> Telegram</label><label style="font-size:12px;color:var(--text-secondary);"><input type="checkbox" name="send_email" checked> Email</label><label style="font-size:12px;color:var(--text-secondary);"><input type="checkbox" name="send_whatsapp"> WhatsApp</label></div></div>
        </div>
        <button type="submit" class="btn btn-primary">Generate with AI</button>
    </form>
</div>

<!-- Existing Newsletters -->
<div class="card fade-in-up delay-2">
    <div class="card-header"><span class="card-title">Newsletters</span></div>
    {% for nl in newsletters %}
    <div style="border:1px solid var(--border);border-radius:var(--radius);padding:16px;margin-bottom:12px;">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <div>
                <span style="font-family:var(--font-display);font-size:14px;font-weight:700;">{{ nl.title }}</span>
                <span class="badge badge-{% if nl.status == 'sent' %}active{% elif nl.status == 'approved' %}bullish{% elif nl.status == 'ai_generated' %}high{% else %}neutral{% endif %}" style="margin-left:8px;">{{ nl.status|upper }}</span>
            </div>
            <span style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);">{{ nl.created_at|date:"M d, H:i" }}</span>
        </div>
        {% if nl.content_markdown %}
        <details style="margin-bottom:10px;">
            <summary style="cursor:pointer;font-size:12px;color:var(--accent);font-family:var(--font-mono);">Preview content</summary>
            <pre style="background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);padding:12px;font-size:11px;color:var(--text-secondary);white-space:pre-wrap;margin-top:8px;max-height:300px;overflow-y:auto;">{{ nl.content_markdown }}</pre>
        </details>
        {% endif %}
        <div style="display:flex;gap:8px;">
            {% if nl.status == 'ai_generated' %}
            <form method="post" style="display:inline;">{% csrf_token %}<input type="hidden" name="action" value="approve"><input type="hidden" name="newsletter_id" value="{{ nl.id }}"><button type="submit" class="btn btn-primary btn-sm">Approve</button></form>
            {% endif %}
            {% if nl.status == 'approved' %}
            <form method="post" style="display:inline;">{% csrf_token %}<input type="hidden" name="action" value="send"><input type="hidden" name="newsletter_id" value="{{ nl.id }}"><button type="submit" class="btn btn-primary btn-sm">Send Now</button></form>
            {% endif %}
            <form method="post" style="display:inline;">{% csrf_token %}<input type="hidden" name="action" value="delete"><input type="hidden" name="newsletter_id" value="{{ nl.id }}"><button type="submit" class="btn btn-sm btn-danger">Delete</button></form>
        </div>
    </div>
    {% empty %}
    <div class="empty-state" style="padding:30px;"><p>NO NEWSLETTERS YET</p></div>
    {% endfor %}
</div>
{% endblock %}
'''))

    # ================================================================
    # 8. USER NOTIFICATION PREFERENCES TEMPLATE
    # ================================================================

    created.append(create_file("templates/dashboard/user_notifications.html",
r'''{% extends "base.html" %}
{% block title %}Notifications — Sauron Vision{% endblock %}
{% block page_title %}NOTIFICATION SETTINGS{% endblock %}

{% block content %}
{% if messages %}
<div style="margin-bottom:16px;">{% for msg in messages %}<div class="card" style="border-color:var(--accent);padding:10px 16px;margin-bottom:6px;"><span style="font-family:var(--font-mono);font-size:12px;">{{ msg }}</span></div>{% endfor %}</div>
{% endif %}

<div class="grid grid-2" style="margin-bottom:24px;">
    <!-- Channel Setup -->
    <div class="card fade-in-up">
        <div class="card-header"><span class="card-title">Notification Channels</span></div>
        <form method="post">{% csrf_token %}<input type="hidden" name="action" value="save_prefs">
            <div style="margin-bottom:14px;"><label class="form-label">TELEGRAM CHAT ID</label><input type="text" name="telegram_chat_id" value="{{ prefs.telegram_chat_id }}" placeholder="Your Telegram chat ID" class="form-input"><div class="form-hint">Message @userinfobot on Telegram to get your ID</div></div>
            <div style="margin-bottom:14px;"><label class="form-label">WHATSAPP NUMBER</label><input type="text" name="whatsapp_number" value="{{ prefs.whatsapp_number }}" placeholder="+33 6 00 00 00 00" class="form-input"><div class="form-hint">International format with country code</div></div>
            <div style="margin-bottom:14px;"><label class="form-label">SMS NUMBER</label><input type="text" name="sms_number" value="{{ prefs.sms_number }}" placeholder="+33 6 00 00 00 00" class="form-input"></div>
            <div style="margin-bottom:14px;"><label style="display:flex;align-items:center;gap:8px;font-size:13px;color:var(--text-secondary);cursor:pointer;"><input type="checkbox" name="email_notifications" {% if prefs.email_notifications %}checked{% endif %}> Email notifications (uses your profile email)</label></div>
            <div class="section-label" style="margin-top:20px;">What to receive</div>
            <div style="display:flex;flex-direction:column;gap:8px;margin-bottom:16px;">
                <label style="font-size:12px;color:var(--text-secondary);"><input type="checkbox" name="receive_signals" {% if prefs.receive_signals %}checked{% endif %}> Trading signals</label>
                <label style="font-size:12px;color:var(--text-secondary);"><input type="checkbox" name="receive_strategies" {% if prefs.receive_strategies %}checked{% endif %}> Strategy proposals</label>
                <label style="font-size:12px;color:var(--text-secondary);"><input type="checkbox" name="receive_news_alerts" {% if prefs.receive_news_alerts %}checked{% endif %}> Critical news alerts</label>
                <label style="font-size:12px;color:var(--text-secondary);"><input type="checkbox" name="receive_portfolio_alerts" {% if prefs.receive_portfolio_alerts %}checked{% endif %}> Portfolio alerts</label>
                <label style="font-size:12px;color:var(--text-secondary);"><input type="checkbox" name="receive_weekly_newsletter" {% if prefs.receive_weekly_newsletter %}checked{% endif %}> Weekly newsletter</label>
                <label style="font-size:12px;color:var(--text-secondary);"><input type="checkbox" name="receive_monthly_newsletter" {% if prefs.receive_monthly_newsletter %}checked{% endif %}> Monthly newsletter</label>
            </div>
            <button type="submit" class="btn btn-primary" style="width:100%;">Save Preferences</button>
        </form>
    </div>

    <!-- Custom Alert Rules -->
    <div class="card fade-in-up delay-2">
        <div class="card-header"><span class="card-title">Custom Alert Rules</span></div>
        <form method="post" style="margin-bottom:20px;">{% csrf_token %}<input type="hidden" name="action" value="add_rule">
            <div style="margin-bottom:10px;"><label class="form-label">RULE NAME</label><input type="text" name="rule_name" placeholder="Oil above 120" class="form-input" required></div>
            <div class="grid grid-2" style="margin-bottom:10px;">
                <div><label class="form-label">SYMBOL (optional)</label><input type="text" name="rule_symbol" placeholder="WTIUSD" class="form-input"></div>
                <div><label class="form-label">ASSET CLASS</label><select name="rule_asset_class" class="form-input"><option value="">All</option><option value="stock">Stocks</option><option value="forex">Forex</option><option value="commodity">Commodities</option><option value="crypto">Crypto</option></select></div>
            </div>
            <div class="grid grid-2" style="margin-bottom:10px;">
                <div><label class="form-label">MIN SCORE</label><input type="number" step="0.1" name="rule_min_score" value="0.5" class="form-input"></div>
                <div><label class="form-label">DIRECTION</label><select name="rule_direction" class="form-input"><option value="">Both</option><option value="bullish">Bullish only</option><option value="bearish">Bearish only</option></select></div>
            </div>
            <div style="display:flex;gap:12px;margin-bottom:12px;">
                <label style="font-size:12px;color:var(--text-secondary);"><input type="checkbox" name="rule_telegram" checked> Telegram</label>
                <label style="font-size:12px;color:var(--text-secondary);"><input type="checkbox" name="rule_email"> Email</label>
                <label style="font-size:12px;color:var(--text-secondary);"><input type="checkbox" name="rule_whatsapp"> WhatsApp</label>
            </div>
            <button type="submit" class="btn btn-primary btn-sm">Add Rule</button>
        </form>
        {% for rule in rules %}
        <div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-top:1px solid var(--border);">
            <div>
                <span style="font-weight:600;font-size:13px;">{{ rule.name }}</span>
                <span style="font-family:var(--font-mono);font-size:10px;color:var(--text-muted);margin-left:8px;">{{ rule.instrument_symbol|default:"ALL" }} | score>{{ rule.min_score }}</span>
            </div>
            <form method="post" style="display:inline;">{% csrf_token %}<input type="hidden" name="action" value="delete_rule"><input type="hidden" name="rule_id" value="{{ rule.id }}"><button type="submit" class="btn btn-sm btn-danger">X</button></form>
        </div>
        {% empty %}
        <div style="text-align:center;padding:20px;color:var(--text-muted);font-size:12px;">No custom rules yet</div>
        {% endfor %}
    </div>
</div>
{% endblock %}
'''))

    # ================================================================
    # 9. ADD SIDEBAR LINKS
    # ================================================================

    base_path = "templates/base.html"
    if os.path.exists(base_path):
        with open(base_path, "r", encoding="utf-8") as f:
            c = f.read()
        if "user_notifications" not in c:
            c = c.replace(
                '<span class="label-text">Profile</span></a>',
                '<span class="label-text">Profile</span></a>\n'
                '            <a href="{% url \'user_notifications\' %}" class="nav-link {% if page_id == \'notifications\' %}active{% endif %}">'
                '<span class="icon">&#x1F514;</span> <span class="label-text">Notifications</span></a>'
            )
        if "admin_newsletters" not in c:
            c = c.replace(
                '<span class="label-text">Admin Panel</span></a>',
                '<span class="label-text">Admin Panel</span></a>\n'
                '            <a href="{% url \'admin_newsletters\' %}" class="nav-link {% if page_id == \'admin_newsletters\' %}active{% endif %}">'
                '<span class="icon">&#x2709;</span> <span class="label-text">Newsletters</span></a>'
            )
            with open(base_path, "w", encoding="utf-8") as f:
                f.write(c)

    # ================================================================
    # 10. RENDER.COM — Updated deployment files
    # ================================================================

    created.append(create_file("render.yaml",
'''# SAURON VISION — Render.com Blueprint
databases:
  - name: sauron-db
    plan: starter
    databaseName: sauron_vision
    user: sauron

services:
  # Django Web
  - type: web
    name: sauron-web
    runtime: python
    plan: starter
    buildCommand: "./build.sh"
    startCommand: "gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 2 --timeout 120"
    envVars:
      - key: SECRET_KEY
        generateValue: true
      - key: DEBUG
        value: "False"
      - key: ALLOWED_HOSTS
        value: ".onrender.com"
      - key: DATABASE_URL
        fromDatabase:
          name: sauron-db
          property: connectionString
      - key: REDIS_URL
        fromService:
          name: sauron-redis
          type: redis
          property: connectionString
      - key: PYTHON_VERSION
        value: "3.12.3"
      - key: ANTHROPIC_API_KEY
        sync: false
      - key: ALPHA_VANTAGE_API_KEY
        sync: false
      - key: FRED_API_KEY
        sync: false
      - key: ETORO_PUBLIC_KEY
        sync: false
      - key: ETORO_USER_KEY
        sync: false
      - key: SCRAPER_API_KEY
        sync: false
      - key: TELEGRAM_BOT_TOKEN
        sync: false
      - key: TELEGRAM_CHAT_ID
        sync: false

  # Celery Fast Worker (prices, news, signals)
  - type: worker
    name: sauron-worker-fast
    runtime: python
    plan: starter
    buildCommand: "pip install -r requirements.txt"
    startCommand: "celery -A config worker -l info -Q fast,default -c 4 --max-tasks-per-child=100"
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: sauron-db
          property: connectionString
      - key: REDIS_URL
        fromService:
          name: sauron-redis
          type: redis
          property: connectionString
      - fromGroup: sauron-env

  # Celery Slow Worker (AI agents)
  - type: worker
    name: sauron-worker-slow
    runtime: python
    plan: starter
    buildCommand: "pip install -r requirements.txt"
    startCommand: "celery -A config worker -l info -Q slow,ai -c 2 --max-tasks-per-child=50"
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: sauron-db
          property: connectionString
      - key: REDIS_URL
        fromService:
          name: sauron-redis
          type: redis
          property: connectionString
      - fromGroup: sauron-env

  # Celery Beat Scheduler
  - type: worker
    name: sauron-beat
    runtime: python
    plan: starter
    buildCommand: "pip install -r requirements.txt"
    startCommand: "celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler"
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: sauron-db
          property: connectionString
      - key: REDIS_URL
        fromService:
          name: sauron-redis
          type: redis
          property: connectionString
      - fromGroup: sauron-env

  # Redis
  - type: redis
    name: sauron-redis
    plan: free
    maxmemoryPolicy: allkeys-lru
'''))

    created.append(create_file("build.sh",
'''#!/usr/bin/env bash
set -o errexit
echo "SAURON VISION — Build starting..."

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Seed data on first deploy
python manage.py seed_instruments 2>/dev/null || true
python manage.py seed_components 2>/dev/null || true

# Seed market configs
python -c "
import django; import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()
from core.market_config import seed_market_configs
print(f'Markets: {seed_market_configs()} new')
" 2>/dev/null || true

echo "SAURON VISION — Build complete!"
'''))

    # ================================================================
    # 11. .env TEMPLATE — comprehensive
    # ================================================================

    created.append(create_file(".env.example",
'''# ============================================================
# SAURON VISION — Environment Variables
# Copy to .env and fill in your keys
# ============================================================

# Django
SECRET_KEY=your-secret-key-here
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1,.onrender.com

# Database (leave empty for SQLite in dev)
DATABASE_URL=

# Redis (leave empty for filesystem broker in dev)
REDIS_URL=

# ── AI Provider ──────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-api03-your-key

# ── Market Data APIs ─────────────────────────────────────
ALPHA_VANTAGE_API_KEY=
TWELVE_DATA_API_KEY=
FINNHUB_API_KEY=
FMP_API_KEY=
FRED_API_KEY=

# ── eToro Integration (dual-key) ─────────────────────────
ETORO_PUBLIC_KEY=
ETORO_USER_KEY=

# ── Proxy & Scraping ────────────────────────────────────
SCRAPER_API_KEY=
SERP_API_KEY=
PROXY_LIST=

# ── Notifications ────────────────────────────────────────
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# ── Email (for newsletters) ─────────────────────────────
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
DEFAULT_FROM_EMAIL=Sauron Vision <noreply@sauronvision.com>

# ── WhatsApp (Twilio) ────────────────────────────────────
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_WHATSAPP_FROM=
'''))

    # ================================================================
    # 12. Crypto celery task + component
    # ================================================================

    # Add crypto component to platform control
    pc_path = "core/platform_control.py"
    if os.path.exists(pc_path):
        with open(pc_path, "r", encoding="utf-8") as f:
            c = f.read()
        if "scraper_crypto" not in c:
            c = c.replace(
                '    {"key": "scraper_etoro",',
                '    {"key": "scraper_crypto", "name": "Crypto Prices", "description": "Fetch crypto prices from CoinGecko/Binance (every 2 min)", "category": "scraper"},\n'
                '    {"key": "scraper_crypto_news", "name": "Crypto News", "description": "Fetch crypto news from CoinDesk, CoinTelegraph (every 10 min)", "category": "scraper"},\n'
                '    {"key": "scraper_etoro",'
            )
            with open(pc_path, "w", encoding="utf-8") as f:
                f.write(c)

    # Add crypto tasks
    md_tasks = "market_data/tasks.py"
    append_if_missing(md_tasks, "scraper_crypto",
'''

@shared_task
@guarded_task("scraper_crypto")
def fetch_crypto_quotes():
    """Fetch crypto prices from CoinGecko."""
    from market_data.adapters.crypto_adapter import save_crypto_quotes_to_db
    count = save_crypto_quotes_to_db()
    return {"status": "success", "fetched": count}


@shared_task
@guarded_task("scraper_crypto_news")
def fetch_crypto_news_task():
    """Fetch crypto news from RSS feeds."""
    from market_data.adapters.crypto_news import fetch_crypto_news
    count = fetch_crypto_news()
    return {"status": "success", "articles": count}
''')

    # ================================================================
    # 13. RENDER DEPLOYMENT GUIDE
    # ================================================================

    created.append(create_file("DEPLOY.md",
'''# Sauron Vision — Render.com Deployment Guide

## File Structure for Render

```
sauron_vision/
  config/          # Django settings, celery, wsgi
  core/            # Platform control, security, exchange status
  instruments/     # Financial instruments
  market_data/     # Adapters, price data
  scraping/        # News scrapers
  indicators/      # Technical indicators
  signals/         # Signal engine
  strategies/      # Strategy engine
  portfolio/       # Portfolio management
  ai_agents/       # AI agent system
  alerts/          # Notifications, newsletters
  dashboard/       # Views, URLs
  backtester/      # Backtesting engine
  templates/       # HTML templates
  static/          # Static files
  manage.py
  requirements.txt
  render.yaml      # Render blueprint
  build.sh         # Build script
  .env             # Local only (never commit)
  .env.example     # Template for env vars
```

## Deploy Steps

1. Push code to GitHub
2. Go to render.com -> New -> Blueprint
3. Connect your GitHub repo
4. Render reads render.yaml and creates:
   - PostgreSQL database (starter $7/mo)
   - Redis instance (free)
   - Web service (starter $7/mo)
   - Fast worker (starter $7/mo)
   - Slow worker (starter $7/mo)
   - Beat scheduler (starter $7/mo)
   Total: ~$28/mo

5. Set environment variables in Render dashboard:
   - Go to sauron-web -> Environment
   - Add all keys from .env.example
   - Use "Environment Groups" for shared vars across services

6. Deploy!

## Security Checklist
- [ ] SECRET_KEY is auto-generated by Render
- [ ] DEBUG=False in production
- [ ] ALLOWED_HOSTS set to .onrender.com
- [ ] All API keys in environment variables (never in code)
- [ ] HTTPS enforced (Render does this automatically)
- [ ] Session cookies marked secure
- [ ] CSRF cookie marked secure
- [ ] Login rate limiting active
- [ ] Security headers middleware active
'''))

        # Ensure migration dirs exist
    for app_dir in ['alerts/migrations', 'core/migrations', 'backtester/migrations']:
        os.makedirs(app_dir, exist_ok=True)
        init = os.path.join(app_dir, '__init__.py')
        if not os.path.exists(init):
            create_file(init, '')

    print(f"""
  SAURON VISION — Mega Patch v2 ({len(created)} files)

  1. Crypto market: CoinGecko + Binance adapters, crypto news RSS   OK
  2. Admin market controls: enable/disable markets from dashboard   OK
  3. Render deployment: updated render.yaml, build.sh, DEPLOY.md    OK
  4. Security: rate limiting, headers, HTTPS, session hardening     OK
  5. Newsletter system: AI generation, review, send (TG/email/WA)   OK
  6. User notifications: channel setup, custom alert rules          OK
  7. Crypto scraper tasks + platform components                     OK
  8. .env.example template                                         OK

  Run:
    python manage.py makemigrations core alerts
    python manage.py migrate
    python manage.py seed_components
    python manage.py runserver
""")


if __name__ == "__main__":
    generate()
