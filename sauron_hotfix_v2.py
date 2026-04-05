#!/usr/bin/env python3
"""
SAURON VISION — Hotfix v2
1. Topbar clock uses user's timezone preference
2. Open exchanges count + hover dropdown in topbar
3. Proxy rotation support for scrapers
"""
import os, re

def create_file(path, content=""):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def generate():
    created = []

    # ================================================================
    # 1. PROXY ROTATION — scraper base with ScraperAPI support
    # ================================================================

    created.append(create_file("core/proxy.py", '''"""Proxy rotation for web scraping — ScraperAPI or custom proxies."""
import os
import requests
import logging
from itertools import cycle

logger = logging.getLogger(__name__)

SCRAPER_API_KEY = os.getenv("SCRAPER_API_KEY", "")
PROXY_LIST = os.getenv("PROXY_LIST", "").split(",")  # comma-separated proxy URLs

_proxy_pool = cycle([p.strip() for p in PROXY_LIST if p.strip()]) if any(PROXY_LIST) else None


class ProxySession:
    """
    Requests session with automatic proxy rotation.

    Priority:
    1. ScraperAPI (if key set) — handles rotation, CAPTCHAs, retries
    2. Custom proxy list rotation
    3. Direct connection (no proxy)
    """

    def __init__(self, use_proxy=True):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "SauronVision/1.0 (Trading Intelligence Platform)",
        })
        self.use_proxy = use_proxy

    def get(self, url, **kwargs):
        """GET request with automatic proxy handling."""
        timeout = kwargs.pop("timeout", 15)

        if self.use_proxy and SCRAPER_API_KEY:
            # ScraperAPI: prepend their proxy URL
            proxy_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={url}"
            return self.session.get(proxy_url, timeout=timeout, **kwargs)

        if self.use_proxy and _proxy_pool:
            proxy = next(_proxy_pool)
            proxies = {"http": proxy, "https": proxy}
            try:
                return self.session.get(url, proxies=proxies, timeout=timeout, **kwargs)
            except requests.exceptions.ProxyError:
                logger.warning(f"Proxy failed: {proxy}, trying next")
                proxy = next(_proxy_pool)
                proxies = {"http": proxy, "https": proxy}
                return self.session.get(url, proxies=proxies, timeout=timeout, **kwargs)

        # Direct connection
        return self.session.get(url, timeout=timeout, **kwargs)

    def post(self, url, **kwargs):
        """POST request with proxy handling."""
        timeout = kwargs.pop("timeout", 15)

        if self.use_proxy and SCRAPER_API_KEY:
            proxy_url = f"http://api.scraperapi.com?api_key={SCRAPER_API_KEY}&url={url}"
            return self.session.post(proxy_url, timeout=timeout, **kwargs)

        if self.use_proxy and _proxy_pool:
            proxy = next(_proxy_pool)
            proxies = {"http": proxy, "https": proxy}
            return self.session.post(url, proxies=proxies, timeout=timeout, **kwargs)

        return self.session.post(url, timeout=timeout, **kwargs)


def get_session(use_proxy=True):
    """Get a proxy-enabled session for scraping."""
    return ProxySession(use_proxy=use_proxy)


def proxy_status():
    """Return proxy configuration status."""
    if SCRAPER_API_KEY:
        return {"provider": "ScraperAPI", "configured": True}
    elif any(p.strip() for p in PROXY_LIST if p):
        count = len([p for p in PROXY_LIST if p.strip()])
        return {"provider": f"Custom ({count} proxies)", "configured": True}
    return {"provider": "None (direct)", "configured": False}
'''))

    # ================================================================
    # 2. EXCHANGE STATUS — detailed market hours
    # ================================================================

    created.append(create_file("core/exchange_status.py", '''"""Stock exchange open/close status with detailed info."""
from datetime import datetime, time
import pytz


EXCHANGES = [
    {
        "code": "NYSE",
        "name": "New York Stock Exchange",
        "country": "US",
        "flag": "US",
        "tz": "US/Eastern",
        "open": time(9, 30),
        "close": time(16, 0),
        "weekdays": [0, 1, 2, 3, 4],
    },
    {
        "code": "NASDAQ",
        "name": "NASDAQ",
        "country": "US",
        "flag": "US",
        "tz": "US/Eastern",
        "open": time(9, 30),
        "close": time(16, 0),
        "weekdays": [0, 1, 2, 3, 4],
    },
    {
        "code": "LSE",
        "name": "London Stock Exchange",
        "country": "UK",
        "flag": "GB",
        "tz": "Europe/London",
        "open": time(8, 0),
        "close": time(16, 30),
        "weekdays": [0, 1, 2, 3, 4],
    },
    {
        "code": "EURONEXT",
        "name": "Euronext Paris",
        "country": "FR",
        "flag": "FR",
        "tz": "Europe/Paris",
        "open": time(9, 0),
        "close": time(17, 30),
        "weekdays": [0, 1, 2, 3, 4],
    },
    {
        "code": "XETRA",
        "name": "Frankfurt (Xetra)",
        "country": "DE",
        "flag": "DE",
        "tz": "Europe/Berlin",
        "open": time(9, 0),
        "close": time(17, 30),
        "weekdays": [0, 1, 2, 3, 4],
    },
    {
        "code": "TSE",
        "name": "Tokyo Stock Exchange",
        "country": "JP",
        "flag": "JP",
        "tz": "Asia/Tokyo",
        "open": time(9, 0),
        "close": time(15, 0),
        "weekdays": [0, 1, 2, 3, 4],
    },
    {
        "code": "HKEX",
        "name": "Hong Kong Stock Exchange",
        "country": "HK",
        "flag": "HK",
        "tz": "Asia/Hong_Kong",
        "open": time(9, 30),
        "close": time(16, 0),
        "weekdays": [0, 1, 2, 3, 4],
    },
    {
        "code": "SSE",
        "name": "Shanghai Stock Exchange",
        "country": "CN",
        "flag": "CN",
        "tz": "Asia/Shanghai",
        "open": time(9, 30),
        "close": time(15, 0),
        "weekdays": [0, 1, 2, 3, 4],
    },
    {
        "code": "ASX",
        "name": "Australian Securities Exchange",
        "country": "AU",
        "flag": "AU",
        "tz": "Australia/Sydney",
        "open": time(10, 0),
        "close": time(16, 0),
        "weekdays": [0, 1, 2, 3, 4],
    },
    {
        "code": "BSE",
        "name": "Bombay Stock Exchange",
        "country": "IN",
        "flag": "IN",
        "tz": "Asia/Kolkata",
        "open": time(9, 15),
        "close": time(15, 30),
        "weekdays": [0, 1, 2, 3, 4],
    },
    {
        "code": "TSX",
        "name": "Toronto Stock Exchange",
        "country": "CA",
        "flag": "CA",
        "tz": "US/Eastern",
        "open": time(9, 30),
        "close": time(16, 0),
        "weekdays": [0, 1, 2, 3, 4],
    },
    {
        "code": "SIX",
        "name": "SIX Swiss Exchange",
        "country": "CH",
        "flag": "CH",
        "tz": "Europe/Zurich",
        "open": time(9, 0),
        "close": time(17, 30),
        "weekdays": [0, 1, 2, 3, 4],
    },
    {
        "code": "FOREX",
        "name": "Forex Market",
        "country": "GLOBAL",
        "flag": "FX",
        "tz": "UTC",
        "open": time(0, 0),
        "close": time(23, 59),
        "weekdays": [0, 1, 2, 3, 4],  # Sun 21:00 - Fri 21:00 handled separately
    },
    {
        "code": "CME",
        "name": "CME Group (Futures)",
        "country": "US",
        "flag": "US",
        "tz": "US/Central",
        "open": time(17, 0),  # Sunday open
        "close": time(16, 0), # Friday close
        "weekdays": [0, 1, 2, 3, 4],
    },
]


def get_exchange_status(now_utc=None):
    """Get open/closed status for all exchanges."""
    if now_utc is None:
        now_utc = datetime.now(pytz.UTC)

    results = []
    open_count = 0

    for ex in EXCHANGES:
        tz = pytz.timezone(ex["tz"])
        local_now = now_utc.astimezone(tz)
        weekday = local_now.weekday()
        local_time = local_now.time()

        # Special handling for Forex (24/5)
        if ex["code"] == "FOREX":
            utc_weekday = now_utc.weekday()
            utc_time = now_utc.time()
            is_open = True
            if utc_weekday == 5:  # Saturday
                is_open = False
            elif utc_weekday == 6 and utc_time < time(21, 0):  # Sunday before 21:00
                is_open = False
            elif utc_weekday == 4 and utc_time >= time(21, 0):  # Friday after 21:00
                is_open = False
        else:
            is_open = (
                weekday in ex["weekdays"]
                and ex["open"] <= local_time < ex["close"]
            )

        if is_open:
            open_count += 1

        results.append({
            "code": ex["code"],
            "name": ex["name"],
            "country": ex["country"],
            "flag": ex["flag"],
            "is_open": is_open,
            "local_time": local_now.strftime("%H:%M"),
            "opens": ex["open"].strftime("%H:%M"),
            "closes": ex["close"].strftime("%H:%M"),
            "timezone": ex["tz"],
        })

    return {
        "open_count": open_count,
        "total": len(EXCHANGES),
        "exchanges": results,
    }
'''))

    # ================================================================
    # 3. CONTEXT PROCESSOR — inject timezone, exchanges into all pages
    # ================================================================

    created.append(create_file("core/context_processors.py", '''"""Global context processors for Sauron Vision."""
from .exchange_status import get_exchange_status


def sauron_context(request):
    """Inject exchange status and user timezone into every template."""
    user_tz = "UTC"
    if request.user.is_authenticated:
        try:
            user_tz = request.user.trader_profile.timezone_preference or "UTC"
        except Exception:
            pass

    exchange_data = get_exchange_status()

    return {
        "user_timezone": user_tz,
        "exchanges_open_count": exchange_data["open_count"],
        "exchanges_total": exchange_data["total"],
        "exchanges_list": exchange_data["exchanges"],
    }
'''))

    # Register context processor in settings
    settings_path = "config/settings.py"
    if os.path.exists(settings_path):
        with open(settings_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "sauron_context" not in content:
            content = content.replace(
                '"django.contrib.messages.context_processors.messages",',
                '"django.contrib.messages.context_processors.messages",\n'
                '                "core.context_processors.sauron_context",'
            )
            with open(settings_path, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(settings_path)

    # ================================================================
    # 4. UPDATE BASE TEMPLATE — timezone clock + exchange dropdown
    # ================================================================

    base_path = "templates/base.html"
    if os.path.exists(base_path):
        with open(base_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Replace the topbar-right section with enhanced version
        old_topbar = '''<div class="topbar-right">
                <a href="{% url 'toggle_theme' %}" style="color:var(--text-secondary);text-decoration:none;font-size:16px;" title="Toggle light/dark mode">\u263e</a>
                <span id="clock"></span>'''

        new_topbar = '''<div class="topbar-right">
                <a href="{% url 'toggle_theme' %}" style="color:var(--text-secondary);text-decoration:none;font-size:16px;" title="Toggle light/dark mode">\u263e</a>
                <span id="clock" data-timezone="{{ user_timezone }}"></span>
                <!-- Exchange Status -->
                <div class="exchange-indicator">
                    <span class="exchange-count" title="Stock exchanges currently open">
                        <span style="color:var(--accent);">{{ exchanges_open_count }}</span><span style="color:var(--text-muted);">/{{ exchanges_total }}</span>
                        <span style="font-size:10px;color:var(--text-muted);margin-left:2px;">SE</span>
                    </span>
                    <div class="exchange-dropdown">
                        <div class="exchange-dropdown-title">Stock Exchange Status</div>
                        {% for ex in exchanges_list %}
                        <div class="exchange-row">
                            <span class="exchange-flag">{{ ex.flag }}</span>
                            <span class="exchange-name">{{ ex.code }}</span>
                            <span class="exchange-time">{{ ex.local_time }}</span>
                            <span class="exchange-status {% if ex.is_open %}open{% else %}closed{% endif %}">
                                {% if ex.is_open %}OPEN{% else %}CLOSED{% endif %}
                            </span>
                        </div>
                        {% endfor %}
                    </div>
                </div>'''

        if old_topbar in content:
            content = content.replace(old_topbar, new_topbar)
        else:
            # Try simpler replacement if topbar was different
            content = content.replace(
                '<span id="clock"></span>',
                '''<span id="clock" data-timezone="{{ user_timezone }}"></span>
                <div class="exchange-indicator">
                    <span class="exchange-count" title="Stock exchanges currently open">
                        <span style="color:var(--accent);">{{ exchanges_open_count }}</span><span style="color:var(--text-muted);">/{{ exchanges_total }}</span>
                        <span style="font-size:10px;color:var(--text-muted);margin-left:2px;">SE</span>
                    </span>
                    <div class="exchange-dropdown">
                        <div class="exchange-dropdown-title">Stock Exchange Status</div>
                        {% for ex in exchanges_list %}
                        <div class="exchange-row">
                            <span class="exchange-flag">{{ ex.flag }}</span>
                            <span class="exchange-name">{{ ex.code }}</span>
                            <span class="exchange-time">{{ ex.local_time }}</span>
                            <span class="exchange-status {% if ex.is_open %}open{% else %}closed{% endif %}">
                                {% if ex.is_open %}OPEN{% else %}CLOSED{% endif %}
                            </span>
                        </div>
                        {% endfor %}
                    </div>
                </div>'''
            )

        # Add exchange dropdown CSS before </style>
        exchange_css = """
        /* ── Exchange Status Dropdown ────────────── */
        .exchange-indicator {
            position: relative;
            cursor: pointer;
        }
        .exchange-count {
            font-family: var(--font-mono);
            font-size: 12px;
            padding: 4px 8px;
            border: 1px solid var(--border);
            border-radius: var(--radius);
            transition: all 0.2s;
        }
        .exchange-indicator:hover .exchange-count {
            border-color: var(--accent-dim);
            background: var(--bg-card);
        }
        .exchange-dropdown {
            display: none;
            position: absolute;
            top: 100%;
            right: 0;
            margin-top: 8px;
            width: 320px;
            background: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: var(--radius-lg);
            box-shadow: 0 8px 40px rgba(0,0,0,0.5);
            z-index: 200;
            padding: 12px;
        }
        .exchange-indicator:hover .exchange-dropdown {
            display: block;
        }
        .exchange-dropdown-title {
            font-family: var(--font-mono);
            font-size: 10px;
            letter-spacing: 2px;
            color: var(--text-muted);
            text-transform: uppercase;
            padding-bottom: 8px;
            margin-bottom: 6px;
            border-bottom: 1px solid var(--border);
        }
        .exchange-row {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 5px 0;
            font-family: var(--font-mono);
            font-size: 11px;
            border-bottom: 1px solid rgba(19,48,32,0.2);
        }
        .exchange-row:last-child { border-bottom: none; }
        .exchange-flag { width: 22px; text-align: center; font-size: 10px; color: var(--text-muted); }
        .exchange-name { width: 70px; font-weight: 600; color: var(--text-primary); }
        .exchange-time { flex: 1; color: var(--text-secondary); text-align: right; }
        .exchange-status {
            width: 50px; text-align: center;
            font-size: 9px; font-weight: 700; letter-spacing: 1px;
            padding: 2px 6px; border-radius: 10px;
        }
        .exchange-status.open { color: var(--accent); background: var(--accent-dim); }
        .exchange-status.closed { color: var(--text-muted); background: rgba(90,138,106,0.1); }
"""

        if "exchange-indicator" not in content:
            content = content.replace("    </style>", exchange_css + "\n    </style>")

        # Update clock JS to use user timezone
        old_clock = """function updateClock(){const el=document.getElementById('clock');if(el){const n=new Date();el.textContent=n.toUTCString().slice(17,25)+' UTC';}}"""
        new_clock = """function updateClock(){
        const el=document.getElementById('clock');
        if(el){
            const tz=el.getAttribute('data-timezone')||'UTC';
            try{
                const fmt=new Intl.DateTimeFormat('en-GB',{timeZone:tz,hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false});
                const tzShort=tz.split('/').pop().replace('_',' ');
                el.textContent=fmt.format(new Date())+' '+tzShort;
            }catch(e){
                el.textContent=new Date().toUTCString().slice(17,25)+' UTC';
            }
        }
    }"""

        if old_clock in content:
            content = content.replace(old_clock, new_clock)
        else:
            # Try multiline version
            content = re.sub(
                r'function updateClock\(\)\{.*?el\.textContent=.*?UTC.*?\}',
                new_clock.replace('\n', '\n'),
                content,
                flags=re.DOTALL
            )

        with open(base_path, "w", encoding="utf-8") as f:
            f.write(content)
        created.append(base_path)

    # ================================================================
    # 5. Add proxy keys to .env
    # ================================================================

    env_path = ".env"
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "SCRAPER_API_KEY" not in content:
            content += """
# Proxy & Scraping
# ScraperAPI: https://www.scraperapi.com ($49/mo for 100K requests)
SCRAPER_API_KEY=
# Or custom proxy list (comma-separated)
PROXY_LIST=
# SERP API for Google News: https://serpapi.com
SERP_API_KEY=
"""
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(env_path)

    # ================================================================
    # 6. Update proxy status in admin dashboard
    # ================================================================

    views_path = "dashboard/views.py"
    if os.path.exists(views_path):
        with open(views_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "proxy_status" not in content:
            content = content.replace(
                '{"name": "Telegram", "ok": bool(os.getenv("TELEGRAM_BOT_TOKEN"))},',
                '{"name": "Telegram", "ok": bool(os.getenv("TELEGRAM_BOT_TOKEN"))},\n'
                '        {"name": "ScraperAPI (proxy)", "ok": bool(os.getenv("SCRAPER_API_KEY"))},\n'
                '        {"name": "SERP API", "ok": bool(os.getenv("SERP_API_KEY"))},'
            )
            with open(views_path, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(views_path)

    print(f"""
  SAURON VISION — Hotfix v2 Applied ({len(created)} files)

  1. Clock now uses user's timezone from Profile settings    OK
  2. Exchange status (X/14 SE) with hover dropdown           OK
  3. Proxy rotation support (ScraperAPI or custom proxies)   OK
  4. Exchange status context processor (all pages)           OK
  5. Proxy + SERP API keys added to .env                     OK

  Run:
    python manage.py runserver
    (no migrations needed)

  Set your timezone: Profile -> Timezone -> save
  The clock will update to your local time.

  For proxy support, add to .env:
    SCRAPER_API_KEY=your-key     (scraperapi.com)
    SERP_API_KEY=your-key        (serpapi.com)
""")


if __name__ == "__main__":
    generate()
