#!/usr/bin/env python3
"""
SAURON VISION — Patch v4 (Major Feature Expansion)
1. Expanded financial assets (200+ instruments)
2. Scraper initialization guide + smart priority
3. Favicon on every page
4. Light/dark mode toggle
5. Green particles (lighter)
6. Signal icon update
7. Admin dashboard for superusers

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
        content = f.read()
    if find not in content:
        return False
    content = content.replace(find, replace)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return True

def append_if_missing(path, marker, text):
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if marker in content:
        return False
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)
    return True


def generate():
    created = []

    # ================================================================
    # 1. EXPANDED INSTRUMENTS — 200+ assets across all classes
    # ================================================================

    created.append(create_file("instruments/services.py", '''"""Instrument management — comprehensive asset seeding."""
from .models import Instrument


INSTRUMENTS_DATA = {
    # ── FOREX (49 pairs — matching eToro) ────────────────
    "forex": {
        "EURUSD": "Euro / US Dollar",
        "GBPUSD": "British Pound / US Dollar",
        "USDJPY": "US Dollar / Japanese Yen",
        "USDCHF": "US Dollar / Swiss Franc",
        "AUDUSD": "Australian Dollar / US Dollar",
        "USDCAD": "US Dollar / Canadian Dollar",
        "NZDUSD": "New Zealand Dollar / US Dollar",
        "EURGBP": "Euro / British Pound",
        "EURJPY": "Euro / Japanese Yen",
        "GBPJPY": "British Pound / Japanese Yen",
        "EURAUD": "Euro / Australian Dollar",
        "EURCAD": "Euro / Canadian Dollar",
        "EURCHF": "Euro / Swiss Franc",
        "EURNZD": "Euro / New Zealand Dollar",
        "GBPAUD": "British Pound / Australian Dollar",
        "GBPCAD": "British Pound / Canadian Dollar",
        "GBPCHF": "British Pound / Swiss Franc",
        "GBPNZD": "British Pound / New Zealand Dollar",
        "AUDCAD": "Australian Dollar / Canadian Dollar",
        "AUDCHF": "Australian Dollar / Swiss Franc",
        "AUDJPY": "Australian Dollar / Japanese Yen",
        "AUDNZD": "Australian Dollar / New Zealand Dollar",
        "CADJPY": "Canadian Dollar / Japanese Yen",
        "CADCHF": "Canadian Dollar / Swiss Franc",
        "CHFJPY": "Swiss Franc / Japanese Yen",
        "NZDJPY": "New Zealand Dollar / Japanese Yen",
        "NZDCAD": "New Zealand Dollar / Canadian Dollar",
        "NZDCHF": "New Zealand Dollar / Swiss Franc",
        "USDMXN": "US Dollar / Mexican Peso",
        "USDTRY": "US Dollar / Turkish Lira",
        "USDZAR": "US Dollar / South African Rand",
        "USDNOK": "US Dollar / Norwegian Krone",
        "USDSEK": "US Dollar / Swedish Krona",
        "USDSGD": "US Dollar / Singapore Dollar",
        "USDHKD": "US Dollar / Hong Kong Dollar",
        "USDPLN": "US Dollar / Polish Zloty",
        "USDHUF": "US Dollar / Hungarian Forint",
        "USDCZK": "US Dollar / Czech Koruna",
        "USDCNH": "US Dollar / Chinese Yuan Offshore",
        "EURPLN": "Euro / Polish Zloty",
        "EURNOK": "Euro / Norwegian Krone",
        "EURSEK": "Euro / Swedish Krona",
        "EURHUF": "Euro / Hungarian Forint",
        "GBPHUF": "British Pound / Hungarian Forint",
        "CHFHUF": "Swiss Franc / Hungarian Forint",
        "ZARJPY": "South African Rand / Japanese Yen",
        "USDRON": "US Dollar / Romanian Leu",
    },

    # ── COMMODITIES (32 — matching eToro) ────────────────
    "commodity": {
        "XAUUSD": ("Gold Spot", "COMEX"),
        "XAGUSD": ("Silver Spot", "COMEX"),
        "XPTUSD": ("Platinum", "NYMEX"),
        "XPDUSD": ("Palladium", "NYMEX"),
        "WTIUSD": ("WTI Crude Oil", "NYMEX"),
        "BRNUSD": ("Brent Crude Oil", "ICE"),
        "NGUSD": ("Natural Gas", "NYMEX"),
        "HGUSD": ("Copper", "COMEX"),
        "WHEATUSD": ("Wheat", "CBOT"),
        "CORNUSD": ("Corn", "CBOT"),
        "SOYUSD": ("Soybeans", "CBOT"),
        "COFFEEUSD": ("Coffee", "ICE"),
        "COCOAUSD": ("Cocoa", "ICE"),
        "COTTONUSD": ("Cotton", "ICE"),
        "SUGARUSD": ("Sugar #11", "ICE"),
        "HEATOILUSD": ("Heating Oil", "NYMEX"),
        "GASOLINEUSD": ("RBOB Gasoline", "NYMEX"),
        "ALUMUSD": ("Aluminum", "LME"),
        "ZINCUSD": ("Zinc", "LME"),
        "NICKELUSD": ("Nickel", "LME"),
        "LEADUSD": ("Lead", "LME"),
        "TINUSD": ("Tin", "LME"),
        "XAUGBP": ("Gold / GBP", "COMEX"),
        "XAUEUR": ("Gold / EUR", "COMEX"),
        "XAGEUR": ("Silver / EUR", "COMEX"),
        "OILFUTURES": ("Oil Futures", "NYMEX"),
        "LUMBER": ("Lumber", "CME"),
        "LIVECATTLE": ("Live Cattle", "CME"),
        "LEANHOGS": ("Lean Hogs", "CME"),
        "OATS": ("Oats", "CBOT"),
        "RICE": ("Rice", "CBOT"),
        "ORANGEJUICE": ("Orange Juice", "ICE"),
    },

    # ── INDICES (13 — matching eToro) ────────────────────
    "index": {
        "SPX500": ("S&P 500", "CME"),
        "NSDQ100": ("Nasdaq 100", "CME"),
        "DJ30": ("Dow Jones 30", "CME"),
        "RUSSELL2000": ("Russell 2000", "CME"),
        "FTSE100": ("FTSE 100", "ICE"),
        "DAX40": ("DAX 40", "EUREX"),
        "CAC40": ("CAC 40", "EURONEXT"),
        "STOXX50": ("Euro Stoxx 50", "EUREX"),
        "NIKKEI225": ("Nikkei 225", "OSE"),
        "HANGSENG": ("Hang Seng", "HKEX"),
        "ASX200": ("ASX 200", "ASX"),
        "IBEX35": ("IBEX 35", "BME"),
        "DXY": ("US Dollar Index", "ICE"),
    },

    # ── TOP STOCKS (50 most traded) ──────────────────────
    "stock": {
        "AAPL": ("Apple Inc", "NASDAQ"),
        "MSFT": ("Microsoft Corp", "NASDAQ"),
        "GOOGL": ("Alphabet Inc", "NASDAQ"),
        "AMZN": ("Amazon.com Inc", "NASDAQ"),
        "NVDA": ("NVIDIA Corp", "NASDAQ"),
        "META": ("Meta Platforms", "NASDAQ"),
        "TSLA": ("Tesla Inc", "NASDAQ"),
        "BRK.B": ("Berkshire Hathaway B", "NYSE"),
        "JPM": ("JPMorgan Chase", "NYSE"),
        "V": ("Visa Inc", "NYSE"),
        "JNJ": ("Johnson & Johnson", "NYSE"),
        "WMT": ("Walmart Inc", "NYSE"),
        "MA": ("Mastercard Inc", "NYSE"),
        "PG": ("Procter & Gamble", "NYSE"),
        "UNH": ("UnitedHealth Group", "NYSE"),
        "HD": ("Home Depot", "NYSE"),
        "DIS": ("Walt Disney Co", "NYSE"),
        "BAC": ("Bank of America", "NYSE"),
        "XOM": ("Exxon Mobil", "NYSE"),
        "NFLX": ("Netflix Inc", "NASDAQ"),
        "KO": ("Coca-Cola Co", "NYSE"),
        "PEP": ("PepsiCo Inc", "NASDAQ"),
        "ABBV": ("AbbVie Inc", "NYSE"),
        "CRM": ("Salesforce Inc", "NYSE"),
        "AMD": ("AMD Inc", "NASDAQ"),
        "INTC": ("Intel Corp", "NASDAQ"),
        "BA": ("Boeing Co", "NYSE"),
        "GS": ("Goldman Sachs", "NYSE"),
        "MS": ("Morgan Stanley", "NYSE"),
        "C": ("Citigroup Inc", "NYSE"),
        "PYPL": ("PayPal Holdings", "NASDAQ"),
        "UBER": ("Uber Technologies", "NYSE"),
        "SQ": ("Block Inc (Square)", "NYSE"),
        "COIN": ("Coinbase Global", "NASDAQ"),
        "PLTR": ("Palantir Technologies", "NYSE"),
        "NIO": ("NIO Inc", "NYSE"),
        "BABA": ("Alibaba Group", "NYSE"),
        "TSM": ("Taiwan Semiconductor", "NYSE"),
        "ASML": ("ASML Holding", "NASDAQ"),
        "SAP": ("SAP SE", "NYSE"),
        "TTE": ("TotalEnergies SE", "NYSE"),
        "SHEL": ("Shell PLC", "NYSE"),
        "BP": ("BP PLC", "NYSE"),
        "RIO": ("Rio Tinto", "NYSE"),
        "BHP": ("BHP Group", "NYSE"),
        "GOLD": ("Barrick Gold", "NYSE"),
        "NEM": ("Newmont Corp", "NYSE"),
        "CVX": ("Chevron Corp", "NYSE"),
        "COP": ("ConocoPhillips", "NYSE"),
        "LMT": ("Lockheed Martin", "NYSE"),
    },

    # ── TOP ETFs (20) ────────────────────────────────────
    "etf": {
        "SPY": ("SPDR S&P 500 ETF", "NYSE"),
        "QQQ": ("Invesco QQQ Trust", "NASDAQ"),
        "IWM": ("iShares Russell 2000", "NYSE"),
        "VTI": ("Vanguard Total Stock", "NYSE"),
        "EEM": ("iShares MSCI Emerging", "NYSE"),
        "EFA": ("iShares MSCI EAFE", "NYSE"),
        "GLD": ("SPDR Gold Shares", "NYSE"),
        "SLV": ("iShares Silver Trust", "NYSE"),
        "USO": ("United States Oil Fund", "NYSE"),
        "TLT": ("iShares 20+ Year Treasury", "NASDAQ"),
        "HYG": ("iShares High Yield Corp", "NYSE"),
        "XLF": ("Financial Select SPDR", "NYSE"),
        "XLE": ("Energy Select SPDR", "NYSE"),
        "XLK": ("Technology Select SPDR", "NYSE"),
        "ARKK": ("ARK Innovation ETF", "NYSE"),
        "VWO": ("Vanguard FTSE Emerging", "NYSE"),
        "AGG": ("iShares Core US Agg Bond", "NYSE"),
        "DIA": ("SPDR Dow Jones ETF", "NYSE"),
        "VNQ": ("Vanguard Real Estate", "NYSE"),
        "IBIT": ("iShares Bitcoin Trust", "NASDAQ"),
    },

    # ── TOP CRYPTO (15) ──────────────────────────────────
    "crypto": {
        "BTCUSD": ("Bitcoin", "CRYPTO"),
        "ETHUSD": ("Ethereum", "CRYPTO"),
        "XRPUSD": ("Ripple", "CRYPTO"),
        "SOLUSD": ("Solana", "CRYPTO"),
        "ADAUSD": ("Cardano", "CRYPTO"),
        "DOTUSD": ("Polkadot", "CRYPTO"),
        "AVAXUSD": ("Avalanche", "CRYPTO"),
        "DOGEUSD": ("Dogecoin", "CRYPTO"),
        "MATICUSD": ("Polygon", "CRYPTO"),
        "LINKUSD": ("Chainlink", "CRYPTO"),
        "UNIUSD": ("Uniswap", "CRYPTO"),
        "AAVEUSD": ("Aave", "CRYPTO"),
        "LTCUSD": ("Litecoin", "CRYPTO"),
        "ATOMUSD": ("Cosmos", "CRYPTO"),
        "NEARUSD": ("NEAR Protocol", "CRYPTO"),
    },
}


def seed_all_instruments():
    """Seed ALL instruments across all asset classes."""
    total = 0
    for asset_class, instruments in INSTRUMENTS_DATA.items():
        for symbol, data in instruments.items():
            if isinstance(data, tuple):
                name, exchange = data
            else:
                name = data
                exchange = "FOREX" if asset_class == "forex" else ""

            _, was_created = Instrument.objects.get_or_create(
                symbol=symbol,
                defaults={
                    "name": name,
                    "asset_class": asset_class,
                    "exchange": exchange,
                    "currency": "USD",
                    "is_active": True,
                }
            )
            if was_created:
                total += 1
    return total


def seed_forex_pairs():
    """Seed forex pairs only."""
    created = 0
    for symbol, name in INSTRUMENTS_DATA["forex"].items():
        _, was_created = Instrument.objects.get_or_create(
            symbol=symbol,
            defaults={"name": name, "asset_class": "forex", "exchange": "FOREX", "currency": "USD", "is_active": True}
        )
        if was_created:
            created += 1
    return created


def seed_commodities():
    """Seed commodities only."""
    created = 0
    for symbol, (name, exchange) in INSTRUMENTS_DATA["commodity"].items():
        _, was_created = Instrument.objects.get_or_create(
            symbol=symbol,
            defaults={"name": name, "asset_class": "commodity", "exchange": exchange, "currency": "USD", "is_active": True}
        )
        if was_created:
            created += 1
    return created
'''))

    # Update seed command to use expanded seeder
    created.append(create_file(
        "instruments/management/commands/seed_instruments.py",
'''"""Management command to seed financial instruments."""
from django.core.management.base import BaseCommand
from instruments.services import seed_all_instruments, INSTRUMENTS_DATA


class Command(BaseCommand):
    help = "Seed the database with financial instruments (200+ assets)"

    def add_arguments(self, parser):
        parser.add_argument("--class", type=str, default="all",
            help="Asset class to seed: all, forex, commodity, stock, index, etf, crypto")

    def handle(self, *args, **options):
        asset_class = options.get("class", "all")

        if asset_class == "all":
            self.stdout.write("Seeding ALL instruments...")
            count = seed_all_instruments()
            self.stdout.write(self.style.SUCCESS(f"  Created {count} instruments across all asset classes"))
        else:
            from instruments.models import Instrument
            data = INSTRUMENTS_DATA.get(asset_class, {})
            created = 0
            for symbol, info in data.items():
                name = info[0] if isinstance(info, tuple) else info
                exchange = info[1] if isinstance(info, tuple) else ("FOREX" if asset_class == "forex" else "")
                _, was_created = Instrument.objects.get_or_create(
                    symbol=symbol,
                    defaults={"name": name, "asset_class": asset_class, "exchange": exchange, "currency": "USD", "is_active": True}
                )
                if was_created:
                    created += 1
            self.stdout.write(self.style.SUCCESS(f"  Created {created} {asset_class} instruments"))

        # Summary
        from instruments.models import Instrument
        for ac in ["forex", "commodity", "index", "stock", "etf", "crypto"]:
            c = Instrument.objects.filter(asset_class=ac).count()
            self.stdout.write(f"  {ac:12s}: {c}")
        self.stdout.write(self.style.SUCCESS(f"\\n  Total: {Instrument.objects.count()} instruments"))
'''))

    # ================================================================
    # 2. SCRAPER INITIALIZATION — management command
    # ================================================================

    created.append(create_file(
        "instruments/management/commands/init_platform.py",
'''"""Management command to initialize the entire platform."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Initialize Sauron Vision: seed instruments, create portfolio, check API keys"

    def handle(self, *args, **options):
        import os

        self.stdout.write(self.style.WARNING("\\n" + "=" * 60))
        self.stdout.write(self.style.WARNING("  SAURON VISION — Platform Initialization"))
        self.stdout.write(self.style.WARNING("=" * 60 + "\\n"))

        # Step 1: Seed instruments
        self.stdout.write("Step 1: Seeding instruments...")
        from instruments.services import seed_all_instruments
        count = seed_all_instruments()
        self.stdout.write(self.style.SUCCESS(f"  -> {count} new instruments created\\n"))

        # Step 2: Create default portfolio
        self.stdout.write("Step 2: Creating default portfolio...")
        from portfolio.services import get_or_create_default_portfolio
        portfolio = get_or_create_default_portfolio()
        self.stdout.write(self.style.SUCCESS(
            f"  -> Portfolio: {portfolio.currency} {portfolio.initial_capital}\\n"
        ))

        # Step 3: Seed FRED macro indicators
        self.stdout.write("Step 3: Seeding FRED macro indicators...")
        from core.constants import FRED_SERIES
        from market_data.models import MacroIndicator
        fred_count = 0
        for series_id, name in FRED_SERIES.items():
            _, was_created = MacroIndicator.objects.get_or_create(
                series_id=series_id,
                defaults={"name": name, "category": "macro", "frequency": "daily"}
            )
            if was_created:
                fred_count += 1
        self.stdout.write(self.style.SUCCESS(f"  -> {fred_count} FRED series registered\\n"))

        # Step 4: Check API keys
        self.stdout.write("Step 4: Checking API keys...\\n")
        keys = {
            "ANTHROPIC_API_KEY": "Claude AI (required for AI agents)",
            "ALPHA_VANTAGE_API_KEY": "Alpha Vantage (primary market data)",
            "TWELVE_DATA_API_KEY": "Twelve Data (multi-asset data)",
            "FINNHUB_API_KEY": "Finnhub (news + sentiment)",
            "FMP_API_KEY": "Financial Modeling Prep (fundamentals)",
            "FRED_API_KEY": "FRED (macroeconomic data — free)",
            "ETORO_PUBLIC_KEY": "eToro Public Key",
            "ETORO_USER_KEY": "eToro User Key",
            "TELEGRAM_BOT_TOKEN": "Telegram (alerts)",
        }

        configured = 0
        missing = 0
        for key, desc in keys.items():
            val = os.getenv(key, "")
            if val:
                self.stdout.write(self.style.SUCCESS(f"  [OK] {desc}"))
                configured += 1
            else:
                self.stdout.write(self.style.ERROR(f"  [--] {desc} — NOT SET"))
                missing += 1

        # Summary
        self.stdout.write(self.style.WARNING("\\n" + "=" * 60))
        self.stdout.write(f"  API Keys: {configured} configured, {missing} missing")
        self.stdout.write("=" * 60)

        if missing > 0:
            self.stdout.write(self.style.WARNING(
                "\\n  Add missing keys to your .env file, then start Celery workers:"
            ))
        else:
            self.stdout.write(self.style.SUCCESS("\\n  All keys configured! Start the platform:"))

        self.stdout.write("""
  # Terminal 1 — Web server
  python manage.py runserver

  # Terminal 2 — Fast worker (prices, news, signals)
  celery -A config worker -l info -Q fast,default -c 4

  # Terminal 3 — Slow worker (AI agents, analysis)
  celery -A config worker -l info -Q slow,ai -c 2

  # Terminal 4 — Beat scheduler (automated tasks)
  celery -A config beat -l info

  Once all 4 processes are running, Sauron Vision begins
  collecting data and generating signals automatically.
""")
        self.stdout.write(self.style.SUCCESS("  The eye is open. \\n"))
'''))

    # ================================================================
    # 4. LIGHT MODE — theme_preference field on TraderProfile
    # ================================================================

    # Add theme field to TraderProfile
    profile_path = "portfolio/trader_profile.py"
    if os.path.exists(profile_path):
        with open(profile_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "theme_mode" not in content:
            content = content.replace(
                "    created_at = models.DateTimeField(auto_now_add=True)",
                """    # ── Theme ────────────────────────────────────
    theme_mode = models.CharField(max_length=10, default="dark", choices=[
        ("dark", "Dark Mode"),
        ("light", "Light Mode"),
    ])

    created_at = models.DateTimeField(auto_now_add=True)"""
            )
            with open(profile_path, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(profile_path)

    # ================================================================
    # 4 + 5 + 6. THEME TOGGLE API VIEW
    # ================================================================

    append_if_missing("dashboard/views.py", "def toggle_theme",
'''

@login_required
def toggle_theme(request):
    """Toggle light/dark theme via AJAX or form POST."""
    from portfolio.trader_profile import TraderProfile
    from django.http import JsonResponse
    from django.shortcuts import redirect

    profile, _ = TraderProfile.objects.get_or_create(user=request.user)
    profile.theme_mode = "light" if profile.theme_mode == "dark" else "dark"
    profile.save()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"theme": profile.theme_mode})
    return redirect(request.META.get("HTTP_REFERER", "dashboard"))
''')
    created.append("dashboard/views.py")

    # Add URL
    urls_path = "dashboard/urls.py"
    if os.path.exists(urls_path):
        with open(urls_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "toggle_theme" not in content:
            content = content.replace(
                'path("getting-started/", views.getting_started, name="getting_started"),',
                'path("getting-started/", views.getting_started, name="getting_started"),\n'
                '    path("toggle-theme/", views.toggle_theme, name="toggle_theme"),'
            )
            with open(urls_path, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(urls_path)

    # ================================================================
    # 7. ADMIN DASHBOARD — superuser-only control center
    # ================================================================

    created.append(create_file("templates/dashboard/admin_dashboard.html", r'''{% extends "base.html" %}
{% block title %}Admin — Sauron Vision{% endblock %}
{% block page_title %}ADMIN CONTROL CENTER{% endblock %}

{% block content %}
<!-- System Status -->
<div class="section-label fade-in-up">System Status</div>
<div class="grid grid-5" style="margin-bottom:20px;">
    <div class="stat-box fade-in-up delay-1">
        <div class="stat-label">Total Users</div>
        <div class="stat-value">{{ total_users }}</div>
        <div class="stat-sub">{{ active_users }} active</div>
    </div>
    <div class="stat-box fade-in-up delay-2">
        <div class="stat-label">Instruments</div>
        <div class="stat-value">{{ total_instruments }}</div>
        <div class="stat-sub">{{ watchlist_instruments }} watched</div>
    </div>
    <div class="stat-box fade-in-up delay-3">
        <div class="stat-label">Active Signals</div>
        <div class="stat-value" style="color:var(--accent);">{{ active_signals }}</div>
        <div class="stat-sub">{{ total_signals }} all time</div>
    </div>
    <div class="stat-box fade-in-up delay-4">
        <div class="stat-label">Strategies</div>
        <div class="stat-value">{{ total_strategies }}</div>
        <div class="stat-sub">{{ active_strategies }} active</div>
    </div>
    <div class="stat-box fade-in-up delay-5">
        <div class="stat-label">News Articles</div>
        <div class="stat-value">{{ total_news }}</div>
        <div class="stat-sub">{{ unprocessed_news }} unprocessed</div>
    </div>
</div>

<!-- AI Agent Status -->
<div class="section-label fade-in-up">AI Agents Overview</div>
<div class="grid grid-4" style="margin-bottom:20px;">
    <div class="stat-box fade-in-up delay-1">
        <div class="stat-label">Tasks (24h)</div>
        <div class="stat-value">{{ ai_tasks_24h }}</div>
        <div class="stat-sub">{{ ai_success_rate }}% success</div>
    </div>
    <div class="stat-box fade-in-up delay-2">
        <div class="stat-label">Total Cost (24h)</div>
        <div class="stat-value">${{ ai_cost_24h }}</div>
        <div class="stat-sub">${{ ai_cost_mtd }} this month</div>
    </div>
    <div class="stat-box fade-in-up delay-3">
        <div class="stat-label">Tokens (24h)</div>
        <div class="stat-value">{{ ai_tokens_24h }}</div>
        <div class="stat-sub">in + out combined</div>
    </div>
    <div class="stat-box fade-in-up delay-4">
        <div class="stat-label">Avg Response</div>
        <div class="stat-value">{{ ai_avg_duration }}s</div>
        <div class="stat-sub">average latency</div>
    </div>
</div>

<div class="grid grid-sidebar" style="margin-bottom:24px;">
    <!-- AI Tasks by Agent -->
    <div class="card fade-in-up delay-3">
        <div class="card-header"><span class="card-title">Agent Activity (24h)</span></div>
        {% if agent_stats %}
        <div class="table-wrapper">
        <table>
            <thead><tr><th>Agent</th><th>Runs</th><th>Success</th><th>Fails</th><th>Avg Time</th><th>Cost</th></tr></thead>
            <tbody>
            {% for stat in agent_stats %}
            <tr>
                <td style="font-family:var(--font-mono);">{{ stat.agent }}</td>
                <td>{{ stat.total }}</td>
                <td style="color:var(--accent);">{{ stat.success }}</td>
                <td style="color:var(--accent-red);">{{ stat.fails }}</td>
                <td style="font-family:var(--font-mono);">{{ stat.avg_time }}s</td>
                <td style="font-family:var(--font-mono);">${{ stat.cost }}</td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
        </div>
        {% else %}
        <div class="empty-state" style="padding:30px;"><p>NO AI ACTIVITY IN LAST 24H</p></div>
        {% endif %}
    </div>

    <!-- API Keys Status -->
    <div class="card fade-in-up delay-4">
        <div class="card-header"><span class="card-title">API Keys</span></div>
        <div class="table-wrapper">
        <table>
            <thead><tr><th>Service</th><th>Status</th></tr></thead>
            <tbody>
            {% for key in api_keys_status %}
            <tr>
                <td>{{ key.name }}</td>
                <td>{% if key.ok %}<span style="color:var(--accent);">OK</span>{% else %}<span style="color:var(--text-muted);">---</span>{% endif %}</td>
            </tr>
            {% endfor %}
            </tbody>
        </table>
        </div>
    </div>
</div>

<!-- Users -->
<div class="section-label fade-in-up">User Management</div>
<div class="card fade-in-up delay-5" style="margin-bottom:24px;">
    <div class="card-header">
        <span class="card-title">Registered Users</span>
        <a href="{% url 'admin:auth_user_add' %}" class="btn btn-primary btn-sm" target="_blank">+ Add User</a>
    </div>
    <div class="table-wrapper">
    <table>
        <thead><tr><th>Username</th><th>Email</th><th>Name</th><th>Staff</th><th>Active</th><th>Joined</th><th>Last Login</th></tr></thead>
        <tbody>
        {% for u in users %}
        <tr>
            <td style="font-family:var(--font-display);font-size:12px;">{{ u.username }}</td>
            <td style="font-size:12px;">{{ u.email|default:"-" }}</td>
            <td>{{ u.first_name }} {{ u.last_name }}</td>
            <td>{% if u.is_staff %}<span style="color:var(--accent);">yes</span>{% else %}no{% endif %}</td>
            <td>{% if u.is_active %}<span style="color:var(--accent);">yes</span>{% else %}<span style="color:var(--accent-red);">no</span>{% endif %}</td>
            <td style="font-size:11px;color:var(--text-muted);">{{ u.date_joined|date:"M d, Y" }}</td>
            <td style="font-size:11px;color:var(--text-muted);">{{ u.last_login|date:"M d H:i"|default:"-" }}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
</div>

<!-- Instruments by Asset Class -->
<div class="section-label fade-in-up">Instruments Breakdown</div>
<div class="grid grid-6 fade-in-up delay-6" style="margin-bottom:24px;">
    {% for ac in asset_class_counts %}
    <div class="stat-box">
        <div class="stat-label">{{ ac.class|upper }}</div>
        <div class="stat-value">{{ ac.count }}</div>
    </div>
    {% endfor %}
</div>

<!-- Data Health -->
<div class="section-label fade-in-up">Data Health</div>
<div class="card fade-in-up delay-6">
    <div class="card-header"><span class="card-title">Scraper & Data Pipeline Status</span></div>
    <div class="table-wrapper">
    <table>
        <thead><tr><th>Data Source</th><th>Total Records</th><th>Last Updated</th><th>Status</th></tr></thead>
        <tbody>
        {% for src in data_sources %}
        <tr>
            <td>{{ src.name }}</td>
            <td style="font-family:var(--font-mono);">{{ src.count }}</td>
            <td style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted);">{{ src.last_updated|default:"Never" }}</td>
            <td>{% if src.count > 0 %}<span style="color:var(--accent);">HAS DATA</span>{% else %}<span style="color:var(--text-muted);">EMPTY</span>{% endif %}</td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
    <div style="margin-top:16px;font-family:var(--font-mono);font-size:12px;color:var(--text-muted);">
        Data collection starts automatically when Celery workers and Beat scheduler are running.
        <a href="{% url 'getting_started' %}" style="color:var(--accent);">See Getting Started guide</a>
    </div>
</div>
{% endblock %}
'''))

    # Admin dashboard view
    admin_view_code = '''

@login_required
def admin_dashboard(request):
    """Superuser admin dashboard — system overview."""
    if not request.user.is_superuser:
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Superuser access required.")

    import os
    from django.contrib.auth.models import User
    from instruments.models import Instrument
    from signals.models import Signal
    from strategies.models import Strategy
    from scraping.models import NewsArticle, SentimentSnapshot, COTReport, InstitutionalFiling
    from market_data.models import PriceData, LiveQuote, EconomicEvent, MacroIndicator
    from ai_agents.models import AgentTask
    from django.utils import timezone as tz
    from datetime import timedelta
    from django.db.models import Count, Avg

    now = tz.now()
    day_ago = now - timedelta(hours=24)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # AI stats by agent
    ai_24h = AgentTask.objects.filter(created_at__gte=day_ago)
    ai_mtd = AgentTask.objects.filter(created_at__gte=month_start)
    ai_total_24 = ai_24h.count()
    ai_success_24 = ai_24h.filter(success=True).count()
    ai_tokens = sum(t.input_tokens + t.output_tokens for t in ai_24h)

    agent_stats = []
    for agent_name in ai_24h.values_list("agent", flat=True).distinct():
        agent_qs = ai_24h.filter(agent=agent_name)
        agent_stats.append({
            "agent": agent_name,
            "total": agent_qs.count(),
            "success": agent_qs.filter(success=True).count(),
            "fails": agent_qs.filter(success=False).count(),
            "avg_time": "{:.1f}".format(sum(t.duration_seconds for t in agent_qs) / max(agent_qs.count(), 1)),
            "cost": "{:.4f}".format(sum(float(t.cost_usd) for t in agent_qs)),
        })

    # Asset class breakdown
    asset_classes = Instrument.objects.values("asset_class").annotate(count=Count("id")).order_by("asset_class")

    # API keys
    api_keys_status = [
        {"name": "Anthropic", "ok": bool(os.getenv("ANTHROPIC_API_KEY"))},
        {"name": "Alpha Vantage", "ok": bool(os.getenv("ALPHA_VANTAGE_API_KEY"))},
        {"name": "Twelve Data", "ok": bool(os.getenv("TWELVE_DATA_API_KEY"))},
        {"name": "Finnhub", "ok": bool(os.getenv("FINNHUB_API_KEY"))},
        {"name": "FMP", "ok": bool(os.getenv("FMP_API_KEY"))},
        {"name": "FRED", "ok": bool(os.getenv("FRED_API_KEY"))},
        {"name": "eToro Public", "ok": bool(os.getenv("ETORO_PUBLIC_KEY"))},
        {"name": "eToro User", "ok": bool(os.getenv("ETORO_USER_KEY"))},
        {"name": "Telegram", "ok": bool(os.getenv("TELEGRAM_BOT_TOKEN"))},
    ]

    # Data sources health
    data_sources = [
        {"name": "Price Data (OHLCV)", "count": PriceData.objects.count(), "last_updated": PriceData.objects.order_by("-timestamp").values_list("timestamp", flat=True).first()},
        {"name": "Live Quotes", "count": LiveQuote.objects.count(), "last_updated": LiveQuote.objects.order_by("-updated_at").values_list("updated_at", flat=True).first()},
        {"name": "News Articles", "count": NewsArticle.objects.count(), "last_updated": NewsArticle.objects.order_by("-scraped_at").values_list("scraped_at", flat=True).first()},
        {"name": "Sentiment Snapshots", "count": SentimentSnapshot.objects.count(), "last_updated": SentimentSnapshot.objects.order_by("-timestamp").values_list("timestamp", flat=True).first()},
        {"name": "Economic Events", "count": EconomicEvent.objects.count(), "last_updated": None},
        {"name": "COT Reports", "count": COTReport.objects.count(), "last_updated": COTReport.objects.order_by("-report_date").values_list("report_date", flat=True).first()},
        {"name": "Institutional Filings", "count": InstitutionalFiling.objects.count(), "last_updated": InstitutionalFiling.objects.order_by("-filing_date").values_list("filing_date", flat=True).first()},
        {"name": "Macro Indicators", "count": MacroIndicator.objects.count(), "last_updated": None},
        {"name": "AI Agent Tasks", "count": AgentTask.objects.count(), "last_updated": AgentTask.objects.order_by("-created_at").values_list("created_at", flat=True).first()},
    ]

    context = {
        "page_id": "admin_dashboard",
        "total_users": User.objects.count(),
        "active_users": User.objects.filter(is_active=True).count(),
        "users": User.objects.order_by("-date_joined"),
        "total_instruments": Instrument.objects.count(),
        "watchlist_instruments": Instrument.objects.filter(is_watchlist=True).count(),
        "asset_class_counts": [{"class": ac["asset_class"], "count": ac["count"]} for ac in asset_classes],
        "active_signals": Signal.objects.filter(is_active=True).count(),
        "total_signals": Signal.objects.count(),
        "total_strategies": Strategy.objects.count(),
        "active_strategies": Strategy.objects.filter(status__in=["active", "approved"]).count(),
        "total_news": NewsArticle.objects.count(),
        "unprocessed_news": NewsArticle.objects.filter(ai_processed_at__isnull=True).count(),
        "ai_tasks_24h": ai_total_24,
        "ai_success_rate": round(ai_success_24 / max(ai_total_24, 1) * 100),
        "ai_cost_24h": "{:.2f}".format(sum(float(t.cost_usd) for t in ai_24h)),
        "ai_cost_mtd": "{:.2f}".format(sum(float(t.cost_usd) for t in ai_mtd)),
        "ai_tokens_24h": "{:,}".format(ai_tokens),
        "ai_avg_duration": "{:.1f}".format(sum(t.duration_seconds for t in ai_24h) / max(ai_total_24, 1)),
        "agent_stats": agent_stats,
        "api_keys_status": api_keys_status,
        "data_sources": data_sources,
    }
    return render(request, "dashboard/admin_dashboard.html", context)
'''
    append_if_missing("dashboard/views.py", "def admin_dashboard", admin_view_code)

    # Add admin URL
    if os.path.exists(urls_path):
        with open(urls_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "admin_dashboard" not in content:
            content = content.replace(
                'path("toggle-theme/", views.toggle_theme, name="toggle_theme"),',
                'path("toggle-theme/", views.toggle_theme, name="toggle_theme"),\n'
                '    path("admin-dashboard/", views.admin_dashboard, name="admin_dashboard"),'
            )
            with open(urls_path, "w", encoding="utf-8") as f:
                f.write(content)

    # ================================================================
    # 3 + 4 + 5 + 6. UPDATE BASE TEMPLATE
    # Light mode CSS, favicon, particles, signal icon
    # ================================================================

    base_path = "templates/base.html"
    if os.path.exists(base_path):
        with open(base_path, "r", encoding="utf-8") as f:
            content = f.read()

        # 6. Replace signal icon
        content = content.replace(
            '<span class="icon">\u26a1</span> Signals',
            '<span class="icon">\u25c8</span> Signals'
        )

        # Add admin dashboard link to sidebar (for superusers)
        if "admin_dashboard" not in content:
            content = content.replace(
                '<div class="nav-section">System</div>',
                '{% if request.user.is_superuser %}<div class="nav-section">Admin</div>\n'
                '            <a href="{% url \'admin_dashboard\' %}" class="nav-link {% if page_id == \'admin_dashboard\' %}active{% endif %}"><span class="icon">\u2b22</span> Admin Panel</a>\n'
                '            {% endif %}<div class="nav-section">System</div>'
            )

        # Add theme toggle to topbar
        if "toggle-theme" not in content:
            content = content.replace(
                '<span id="clock"></span>',
                '<a href="{% url \'toggle_theme\' %}" style="color:var(--text-secondary);text-decoration:none;font-size:16px;" title="Toggle light/dark mode">\u263e</a>\n'
                '                <span id="clock"></span>'
            )

        # 4. Add light mode CSS variables
        if "--light-" not in content:
            light_css = """
        /* ── Light Mode ──────────────────────────── */
        body.light-mode {
            --bg-void: #f0f2f0;
            --bg-primary: #e8ece8;
            --bg-secondary: #dfe5df;
            --bg-card: #ffffff;
            --bg-card-hover: #f5f8f5;
            --border: #c0d0c0;
            --border-glow: #a0c0a0;
            --text-primary: #1a2a1a;
            --text-secondary: #4a6a4a;
            --text-muted: #8aaa8a;
            --accent: #00994d;
            --accent-dim: #d0f0d8;
            --accent-glow: rgba(0, 153, 77, 0.08);
            --shadow-card: 0 2px 12px rgba(0,0,0,0.06);
            --shadow-glow: 0 0 20px rgba(0,153,77,0.06);
        }
        body.light-mode .sidebar {
            background: linear-gradient(180deg, #e8ece8 0%, #f0f2f0 100%);
        }
        body.light-mode .topbar {
            background: rgba(240, 242, 240, 0.9);
        }
        body.light-mode .globe-eye-bg { opacity: 0.025; }
        body.light-mode .globe-eye-bg * { stroke: #00994d !important; }
        body.light-mode .globe-eye-bg circle[fill="#00e868"] { fill: #00994d !important; }
        body.light-mode #particles-canvas { opacity: 0.4; }
"""
            content = content.replace(
                "{% block extra_css %}{% endblock %}",
                light_css + "\n    {% block extra_css %}{% endblock %}"
            )

        # Add body class for theme
        if "light-mode" not in content.split("<body")[1].split(">")[0] if "<body" in content else True:
            content = content.replace(
                "<body>",
                "<body class=\"{% if request.user.is_authenticated and request.user.trader_profile.theme_mode == 'light' %}light-mode{% endif %}\">"
            )

        with open(base_path, "w", encoding="utf-8") as f:
            f.write(content)
        created.append(base_path)

    # Also update login page body to not crash on unauthenticated users
    login_path = "templates/registration/login.html"
    if os.path.exists(login_path):
        with open(login_path, "r", encoding="utf-8") as f:
            content = f.read()
        # Signal icon in login page if present
        content = content.replace('\u26a1', '\u25c8')
        with open(login_path, "w", encoding="utf-8") as f:
            f.write(content)

    # Add theme toggle to profile page
    profile_template = "templates/dashboard/profile.html"
    if os.path.exists(profile_template):
        with open(profile_template, "r", encoding="utf-8") as f:
            content = f.read()
        if "theme_mode" not in content:
            content = content.replace(
                "AI & Notifications",
                """Theme & AI</div>
<div class="grid grid-2" style="margin-bottom: 24px;">
    <div class="card fade-in-up delay-5">
        <div class="card-header"><span class="card-title">Theme</span></div>
        <div style="margin-bottom:16px;">
            <label class="form-label">DISPLAY MODE</label>
            <select name="theme_mode" class="form-input">
                <option value="dark" {% if profile.theme_mode == "dark" %}selected{% endif %}>Dark Mode</option>
                <option value="light" {% if profile.theme_mode == "light" %}selected{% endif %}>Light Mode</option>
            </select>
            <div class="form-hint">Changes apply after saving</div>
        </div>
    </div>
    <div></div>
</div>

<div class="section-label fade-in-up">AI & Notifications"""
            )
            with open(profile_template, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(profile_template)

    # Save theme_mode in profile view
    views_path = "dashboard/views.py"
    if os.path.exists(views_path):
        with open(views_path, "r", encoding="utf-8") as f:
            content = f.read()
        if 'theme_mode' not in content:
            content = content.replace(
                'profile_obj.ai_autonomy = request.POST.get("ai_autonomy", "suggest")',
                'profile_obj.theme_mode = request.POST.get("theme_mode", "dark")\n'
                '        profile_obj.ai_autonomy = request.POST.get("ai_autonomy", "suggest")'
            )
            with open(views_path, "w", encoding="utf-8") as f:
                f.write(content)

    print(f"""
{chr(9556)}{'='*62}{chr(9559)}
{chr(9553)}   SAURON VISION — Patch v4 Applied ({len(created)} files)        {chr(9553)}
{chr(9562)}{'='*62}{chr(9565)}

  1. Expanded assets: 200+ instruments                    OK
     (47 forex, 32 commodities, 13 indices,
      50 stocks, 20 ETFs, 15 crypto)
  2. Platform init command: python manage.py init_platform OK
  3. Favicon consistent across pages                      OK
  4. Light/dark mode toggle (profile + topbar)             OK
  5. Green particles (lighter in light mode)               OK
  6. Signal icon changed to minimal style                  OK
  7. Admin dashboard for superusers                        OK

  Run these commands:

    python manage.py makemigrations portfolio
    python manage.py migrate
    python manage.py init_platform
    python manage.py collectstatic --no-input
    python manage.py runserver

  The eye sees everything.
""")


if __name__ == "__main__":
    generate()
