#!/usr/bin/env python3
"""
SAURON VISION — Patch v3
1. Favicon fix (inline data URI fallback)
2. Perfected globe-eye SVG (globe touches eye bounds)
3. Account setup: capital, positions, eToro connect
4. Getting Started guide page
"""
import os, base64

def create_file(path, content=""):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path

def generate():
    created = []

    # ================================================================
    # PERFECTED GLOBE-EYE SVG (reusable)
    # Globe sphere perfectly inscribed touching top/bottom of eye
    # ================================================================

    GLOBE_EYE_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 400">
  <!-- Eye outer shape -->
  <path d="M 0,200 Q 120,20 260,60 Q 370,30 400,40 Q 430,30 540,60 Q 680,20 800,200 Q 680,380 540,340 Q 430,370 400,360 Q 370,370 260,340 Q 120,380 0,200Z" fill="none" stroke="#00e868" stroke-width="2"/>
  <path d="M 20,200 Q 140,50 280,80 Q 380,50 400,60 Q 420,50 520,80 Q 660,50 780,200 Q 660,350 520,320 Q 420,350 400,340 Q 380,350 280,320 Q 140,350 20,200Z" fill="none" stroke="#00e868" stroke-width="0.6" opacity="0.3"/>
  <!-- Iris circle -->
  <circle cx="400" cy="200" r="155" fill="none" stroke="#00e868" stroke-width="1.2" opacity="0.5"/>
  <!-- GLOBE — r=155 touching top(45) and bottom(355) of eye -->
  <circle cx="400" cy="200" r="155" fill="none" stroke="#00e868" stroke-width="0.3" opacity="0.15"/>
  <!-- Globe meridians (rotate in animation) -->
  <g class="globe-spin">
    <ellipse cx="400" cy="200" rx="50" ry="155" fill="none" stroke="#00e868" stroke-width="0.6" opacity="0.35"/>
    <ellipse cx="400" cy="200" rx="100" ry="155" fill="none" stroke="#00e868" stroke-width="0.5" opacity="0.25"/>
    <ellipse cx="400" cy="200" rx="140" ry="155" fill="none" stroke="#00e868" stroke-width="0.4" opacity="0.2"/>
    <ellipse cx="400" cy="200" rx="25" ry="155" fill="none" stroke="#00e868" stroke-width="0.4" opacity="0.2" transform="rotate(20 400 200)"/>
    <ellipse cx="400" cy="200" rx="75" ry="155" fill="none" stroke="#00e868" stroke-width="0.4" opacity="0.2" transform="rotate(-15 400 200)"/>
    <ellipse cx="400" cy="200" rx="120" ry="155" fill="none" stroke="#00e868" stroke-width="0.3" opacity="0.15" transform="rotate(10 400 200)"/>
    <!-- Latitude lines clipped to globe -->
    <line x1="245" y1="120" x2="555" y2="120" stroke="#00e868" stroke-width="0.4" opacity="0.2"/>
    <line x1="248" y1="155" x2="552" y2="155" stroke="#00e868" stroke-width="0.35" opacity="0.18"/>
    <line x1="245" y1="200" x2="555" y2="200" stroke="#00e868" stroke-width="0.5" opacity="0.3"/>
    <line x1="248" y1="245" x2="552" y2="245" stroke="#00e868" stroke-width="0.35" opacity="0.18"/>
    <line x1="245" y1="280" x2="555" y2="280" stroke="#00e868" stroke-width="0.4" opacity="0.2"/>
  </g>
  <!-- Pupil -->
  <circle cx="400" cy="200" r="55" fill="none" stroke="#00e868" stroke-width="2"/>
  <circle cx="400" cy="200" r="22" fill="#00e868" opacity="0.1"/>
  <circle cx="400" cy="200" r="8" fill="#00e868" opacity="0.25"/>
  <!-- Eye corners -->
  <line x1="0" y1="200" x2="50" y2="200" stroke="#00e868" stroke-width="0.5" opacity="0.3"/>
  <line x1="750" y1="200" x2="800" y2="200" stroke="#00e868" stroke-width="0.5" opacity="0.3"/>
</svg>'''

    # Favicon: eye-shaped, no globe needed at 32px
    FAVICON_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <path d="M2,32 Q16,8 32,14 Q48,8 62,32 Q48,56 32,50 Q16,56 2,32Z" fill="none" stroke="#00e868" stroke-width="2.5"/>
  <circle cx="32" cy="32" r="12" fill="none" stroke="#00e868" stroke-width="2"/>
  <circle cx="32" cy="32" r="5" fill="#00e868"/>
  <ellipse cx="32" cy="32" rx="4" ry="12" fill="none" stroke="#00e868" stroke-width="0.8" opacity="0.5"/>
  <ellipse cx="32" cy="32" rx="9" ry="12" fill="none" stroke="#00e868" stroke-width="0.5" opacity="0.3"/>
</svg>'''

    # Create favicon as static file
    created.append(create_file("static/favicon.svg", FAVICON_SVG))

    # Base64-encoded for inline use in templates (guarantees it works)
    favicon_b64 = base64.b64encode(FAVICON_SVG.encode()).decode()

    # OG image
    created.append(create_file("static/og-image.svg", '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 630">
  <rect width="1200" height="630" fill="#030806"/>
  <g transform="translate(200,135) scale(1,1.1)">
    <path d="M 0,200 Q 120,20 260,60 Q 370,30 400,40 Q 430,30 540,60 Q 680,20 800,200 Q 680,380 540,340 Q 430,370 400,360 Q 370,370 260,340 Q 120,380 0,200Z" fill="none" stroke="#00e868" stroke-width="2" opacity="0.5"/>
    <circle cx="400" cy="200" r="155" fill="none" stroke="#00e868" stroke-width="1" opacity="0.3"/>
    <ellipse cx="400" cy="200" rx="50" ry="155" fill="none" stroke="#00e868" stroke-width="0.6" opacity="0.3"/>
    <ellipse cx="400" cy="200" rx="100" ry="155" fill="none" stroke="#00e868" stroke-width="0.5" opacity="0.2"/>
    <line x1="245" y1="120" x2="555" y2="120" stroke="#00e868" stroke-width="0.4" opacity="0.15"/>
    <line x1="245" y1="200" x2="555" y2="200" stroke="#00e868" stroke-width="0.5" opacity="0.2"/>
    <line x1="245" y1="280" x2="555" y2="280" stroke="#00e868" stroke-width="0.4" opacity="0.15"/>
    <circle cx="400" cy="200" r="55" fill="none" stroke="#00e868" stroke-width="2" opacity="0.5"/>
    <circle cx="400" cy="200" r="8" fill="#00e868" opacity="0.3"/>
  </g>
  <text x="600" y="510" text-anchor="middle" font-family="sans-serif" font-size="48" font-weight="900" letter-spacing="12" fill="#00e868">SAURON VISION</text>
  <text x="600" y="550" text-anchor="middle" font-family="monospace" font-size="16" letter-spacing="4" fill="#2a5038">TRADING INTELLIGENCE PLATFORM</text>
</svg>'''))

    # ================================================================
    # SETTINGS PATCH — add STATICFILES_DIRS
    # ================================================================

    created.append(create_file("config/_staticfiles_patch.py", '''"""
ADD THIS TO config/settings.py if not already present,
right after the STATIC_URL line:

STATICFILES_DIRS = [BASE_DIR / "static"]
"""
'''))

    # ================================================================
    # eTORO ADAPTER
    # ================================================================

    created.append(create_file("market_data/adapters/etoro_adapter.py", '''"""eToro API adapter — portfolio sync, positions, trading."""
import os
import requests
import logging

logger = logging.getLogger(__name__)

API_KEY = os.getenv("ETORO_API_KEY", "")
BASE_URL = "https://api.etoro.com"  # Official eToro API


class EtoroClient:
    """Client for eToro Public API."""

    def __init__(self, api_key=None):
        self.api_key = api_key or API_KEY
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            })

    def is_configured(self):
        return bool(self.api_key)

    def get_portfolio(self):
        """Fetch current portfolio positions from eToro."""
        try:
            resp = self.session.get(f"{BASE_URL}/api/v1/portfolio")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"eToro portfolio fetch failed: {e}")
            return None

    def get_positions(self):
        """Fetch open positions."""
        try:
            resp = self.session.get(f"{BASE_URL}/api/v1/positions")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"eToro positions fetch failed: {e}")
            return None

    def get_account_balance(self):
        """Fetch account balance and equity."""
        try:
            resp = self.session.get(f"{BASE_URL}/api/v1/account/balance")
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"eToro balance fetch failed: {e}")
            return None


def sync_etoro_positions():
    """Sync eToro positions into Sauron Vision portfolio."""
    from instruments.models import Instrument
    from portfolio.models import Position
    from portfolio.services import get_or_create_default_portfolio
    from django.utils import timezone

    client = EtoroClient()
    if not client.is_configured():
        logger.warning("eToro API key not configured")
        return {"status": "not_configured"}

    positions_data = client.get_positions()
    if not positions_data:
        return {"status": "fetch_failed"}

    portfolio = get_or_create_default_portfolio()
    synced = 0

    for pos in positions_data.get("positions", []):
        symbol = pos.get("symbol", "")
        instrument, _ = Instrument.objects.get_or_create(
            symbol=symbol,
            defaults={
                "name": pos.get("name", symbol),
                "asset_class": "stock",
                "exchange": "ETORO",
                "is_active": True,
            }
        )

        Position.objects.update_or_create(
            portfolio=portfolio,
            instrument=instrument,
            closed_at__isnull=True,
            defaults={
                "direction": "long" if pos.get("isBuy", True) else "short",
                "quantity": pos.get("amount", 0),
                "entry_price": pos.get("openRate", 0),
                "current_price": pos.get("currentRate", 0),
                "stop_loss": pos.get("stopLossRate"),
                "take_profit": pos.get("takeProfitRate"),
                "unrealized_pnl": pos.get("netProfit", 0),
                "unrealized_pnl_pct": pos.get("netProfitPercentage", 0),
                "opened_at": timezone.now(),
            }
        )
        synced += 1

    # Sync balance
    balance = client.get_account_balance()
    if balance:
        portfolio.current_value = balance.get("equity", portfolio.current_value)
        portfolio.cash_available = balance.get("availableBalance", portfolio.cash_available)
        portfolio.save()

    return {"status": "success", "synced": synced}
'''))

    # ================================================================
    # SETUP VIEWS + TEMPLATES
    # ================================================================

    created.append(create_file("templates/dashboard/setup.html", r'''{% extends "base.html" %}
{% block title %}Setup — Sauron Vision{% endblock %}
{% block page_title %}⚙ ACCOUNT SETUP{% endblock %}

{% block content %}
{% if messages %}
<div style="margin-bottom: 20px;">
    {% for msg in messages %}
    <div class="card" style="border-color: {% if msg.tags == 'success' %}var(--accent){% else %}var(--accent-red){% endif %}; padding: 12px 20px; margin-bottom: 8px;">
        <span style="font-family: var(--font-mono); font-size: 13px;">
            {% if msg.tags == 'success' %}✓{% else %}⚠{% endif %} {{ msg }}
        </span>
    </div>
    {% endfor %}
</div>
{% endif %}

<div class="grid grid-2" style="margin-bottom: 24px;">
    <!-- Portfolio Capital -->
    <div class="card fade-in-up delay-1">
        <div class="card-header"><span class="card-title">◎ Portfolio Capital</span></div>
        <form method="post" action="{% url 'setup' %}">
            {% csrf_token %}
            <input type="hidden" name="action" value="update_capital">
            <div style="margin-bottom: 16px;">
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">INITIAL CAPITAL (€)</label>
                <input type="number" step="0.01" name="initial_capital" value="{{ portfolio.initial_capital }}"
                    style="width:100%;padding:10px 14px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:14px;outline:none;">
            </div>
            <div style="margin-bottom: 16px;">
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">CURRENT VALUE (€)</label>
                <input type="number" step="0.01" name="current_value" value="{{ portfolio.current_value }}"
                    style="width:100%;padding:10px 14px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:14px;outline:none;">
            </div>
            <div style="margin-bottom: 16px;">
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">CASH AVAILABLE (€)</label>
                <input type="number" step="0.01" name="cash_available" value="{{ portfolio.cash_available }}"
                    style="width:100%;padding:10px 14px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:14px;outline:none;">
            </div>
            <div style="margin-bottom: 16px;">
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">BASE CURRENCY</label>
                <select name="currency" style="width:100%;padding:10px 14px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:14px;">
                    <option value="EUR" {% if portfolio.currency == "EUR" %}selected{% endif %}>EUR</option>
                    <option value="USD" {% if portfolio.currency == "USD" %}selected{% endif %}>USD</option>
                    <option value="GBP" {% if portfolio.currency == "GBP" %}selected{% endif %}>GBP</option>
                </select>
            </div>
            <button type="submit" class="btn btn-primary" style="width:100%;">Save Capital Settings</button>
        </form>
    </div>

    <!-- Risk Limits -->
    <div class="card fade-in-up delay-2">
        <div class="card-header"><span class="card-title">⚠ Risk Limits</span></div>
        <form method="post" action="{% url 'setup' %}">
            {% csrf_token %}
            <input type="hidden" name="action" value="update_risk">
            <div style="margin-bottom: 16px;">
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">MAX TOTAL EXPOSURE (%)</label>
                <input type="number" step="1" name="max_exposure" value="{{ portfolio.max_total_exposure_pct }}"
                    style="width:100%;padding:10px 14px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:14px;outline:none;">
            </div>
            <div style="margin-bottom: 16px;">
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">MAX SINGLE POSITION (%)</label>
                <input type="number" step="1" name="max_position" value="{{ portfolio.max_single_position_pct }}"
                    style="width:100%;padding:10px 14px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:14px;outline:none;">
            </div>
            <div style="margin-bottom: 16px;">
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">MAX DAILY LOSS (%)</label>
                <input type="number" step="0.1" name="max_daily_loss" value="{{ portfolio.max_daily_loss_pct }}"
                    style="width:100%;padding:10px 14px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:14px;outline:none;">
            </div>
            <div style="margin-bottom: 16px;">
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">MAX CORRELATION THRESHOLD</label>
                <input type="number" step="0.05" name="max_correlation" value="{{ portfolio.max_correlation_threshold }}"
                    style="width:100%;padding:10px 14px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:14px;outline:none;">
            </div>
            <button type="submit" class="btn btn-primary" style="width:100%;">Save Risk Limits</button>
        </form>
    </div>
</div>

<!-- eToro Connection -->
<div class="card fade-in-up delay-3" style="margin-bottom: 24px;">
    <div class="card-header">
        <span class="card-title">🔗 eToro Integration</span>
        {% if etoro_connected %}
        <span class="badge badge-active">CONNECTED</span>
        {% else %}
        <span class="badge badge-low">NOT CONNECTED</span>
        {% endif %}
    </div>
    <p style="color:var(--text-secondary);margin-bottom:16px;font-size:14px;">
        Connect your eToro account to automatically sync positions, balance, and P&L into Sauron Vision.
    </p>
    <form method="post" action="{% url 'setup' %}">
        {% csrf_token %}
        <input type="hidden" name="action" value="connect_etoro">
        <div style="margin-bottom: 16px;">
            <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">ETORO API KEY</label>
            <input type="password" name="etoro_api_key" value="{{ etoro_key_masked }}" placeholder="Paste your eToro API key"
                style="width:100%;padding:10px 14px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:14px;outline:none;">
            <div style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted);margin-top:6px;">
                Get your key: eToro Web → Settings → API → Generate API Key
                (<a href="https://api-portal.etoro.com" target="_blank" style="color:var(--accent);">docs</a>)
            </div>
        </div>
        <div style="display:flex;gap:12px;">
            <button type="submit" class="btn btn-primary">Save & Connect</button>
            {% if etoro_connected %}
            <button type="submit" name="action" value="sync_etoro" class="btn">⟳ Sync Positions Now</button>
            {% endif %}
        </div>
    </form>
</div>

<!-- Manual Position Entry -->
<div class="card fade-in-up delay-4" style="margin-bottom: 24px;">
    <div class="card-header"><span class="card-title">▣ Add Manual Position</span></div>
    <form method="post" action="{% url 'setup' %}">
        {% csrf_token %}
        <input type="hidden" name="action" value="add_position">
        <div class="grid grid-4" style="margin-bottom: 16px;">
            <div>
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">SYMBOL</label>
                <input type="text" name="symbol" placeholder="AAPL" required
                    style="width:100%;padding:10px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:14px;outline:none;">
            </div>
            <div>
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">DIRECTION</label>
                <select name="direction" style="width:100%;padding:10px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:14px;">
                    <option value="long">LONG</option>
                    <option value="short">SHORT</option>
                </select>
            </div>
            <div>
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">QUANTITY</label>
                <input type="number" step="0.0001" name="quantity" placeholder="10" required
                    style="width:100%;padding:10px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:14px;outline:none;">
            </div>
            <div>
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">ENTRY PRICE</label>
                <input type="number" step="0.0001" name="entry_price" placeholder="150.00" required
                    style="width:100%;padding:10px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:14px;outline:none;">
            </div>
        </div>
        <div class="grid grid-3" style="margin-bottom: 16px;">
            <div>
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">STOP LOSS (optional)</label>
                <input type="number" step="0.0001" name="stop_loss" placeholder=""
                    style="width:100%;padding:10px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:14px;outline:none;">
            </div>
            <div>
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">TAKE PROFIT (optional)</label>
                <input type="number" step="0.0001" name="take_profit" placeholder=""
                    style="width:100%;padding:10px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:14px;outline:none;">
            </div>
            <div>
                <label style="display:block;font-family:var(--font-mono);font-size:10px;letter-spacing:2px;color:var(--text-muted);margin-bottom:6px;">ASSET CLASS</label>
                <select name="asset_class" style="width:100%;padding:10px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);color:var(--text-primary);font-family:var(--font-mono);font-size:14px;">
                    <option value="stock">Stock</option>
                    <option value="forex">Forex</option>
                    <option value="commodity">Commodity</option>
                    <option value="crypto">Crypto</option>
                    <option value="etf">ETF</option>
                </select>
            </div>
        </div>
        <button type="submit" class="btn btn-primary">Add Position</button>
    </form>
</div>

<!-- API Keys Status -->
<div class="card fade-in-up delay-5">
    <div class="card-header"><span class="card-title">🔑 API Keys Status</span></div>
    <div class="table-wrapper">
    <table>
        <thead><tr><th>Service</th><th>Status</th><th>Where to Get</th></tr></thead>
        <tbody>
        {% for key in api_keys %}
        <tr>
            <td>{{ key.name }}</td>
            <td>{% if key.configured %}<span style="color:var(--accent);">● CONFIGURED</span>{% else %}<span style="color:var(--text-muted);">○ NOT SET</span>{% endif %}</td>
            <td><a href="{{ key.url }}" target="_blank" style="color:var(--accent);font-size:12px;">{{ key.url_label }}</a></td>
        </tr>
        {% endfor %}
        </tbody>
    </table>
    </div>
    <div style="margin-top:16px;font-family:var(--font-mono);font-size:12px;color:var(--text-muted);">
        Set keys in your <code>.env</code> file or Render Environment tab. <a href="{% url 'getting_started' %}" style="color:var(--accent);">See Getting Started guide →</a>
    </div>
</div>
{% endblock %}
'''))

    # ================================================================
    # GETTING STARTED PAGE
    # ================================================================

    created.append(create_file("templates/dashboard/getting_started.html", r'''{% extends "base.html" %}
{% block title %}Getting Started — Sauron Vision{% endblock %}
{% block page_title %}📡 GETTING STARTED{% endblock %}

{% block content %}
<div class="card fade-in-up" style="margin-bottom: 24px;">
    <div class="card-header"><span class="card-title">Step 1 — Get Your API Keys</span></div>
    <div style="font-size:14px;line-height:1.9;">
        <p style="margin-bottom:16px;color:var(--text-secondary);">Sauron Vision needs API keys to fetch market data and run AI analysis. Here's where to get each one:</p>

        <div style="margin-bottom:20px;padding:16px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);">
            <div style="font-family:var(--font-display);font-size:13px;color:var(--accent);margin-bottom:8px;">ANTHROPIC (Claude AI) — Required</div>
            <ol style="padding-left:20px;color:var(--text-secondary);font-size:13px;">
                <li>Go to <a href="https://console.anthropic.com" target="_blank" style="color:var(--accent);">console.anthropic.com</a></li>
                <li>Create an account or log in</li>
                <li>Go to <strong>API Keys</strong> → <strong>Create Key</strong></li>
                <li>Copy the key and paste it as <code>ANTHROPIC_API_KEY</code> in your <code>.env</code> file</li>
                <li>Add credit ($5-10 to start) under <strong>Billing</strong></li>
            </ol>
            <div style="font-family:var(--font-mono);font-size:11px;color:var(--text-muted);margin-top:8px;">
                Note: This is separate from your Claude Max subscription. The API is pay-per-use.
            </div>
        </div>

        <div style="margin-bottom:20px;padding:16px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);">
            <div style="font-family:var(--font-display);font-size:13px;color:var(--accent);margin-bottom:8px;">ALPHA VANTAGE — Required (Free)</div>
            <ol style="padding-left:20px;color:var(--text-secondary);font-size:13px;">
                <li>Go to <a href="https://www.alphavantage.co/support/#api-key" target="_blank" style="color:var(--accent);">alphavantage.co/support</a></li>
                <li>Fill in the form → instant free API key</li>
                <li>Set as <code>ALPHA_VANTAGE_API_KEY</code> in <code>.env</code></li>
            </ol>
        </div>

        <div style="margin-bottom:20px;padding:16px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);">
            <div style="font-family:var(--font-display);font-size:13px;color:var(--accent);margin-bottom:8px;">FRED (Macro Data) — Recommended (Free)</div>
            <ol style="padding-left:20px;color:var(--text-secondary);font-size:13px;">
                <li>Go to <a href="https://fred.stlouisfed.org/docs/api/api_key.html" target="_blank" style="color:var(--accent);">FRED API Key page</a></li>
                <li>Create a FRED account → request API key</li>
                <li>Set as <code>FRED_API_KEY</code></li>
            </ol>
        </div>

        <div style="margin-bottom:20px;padding:16px;background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);">
            <div style="font-family:var(--font-display);font-size:13px;color:var(--accent);margin-bottom:8px;">eTORO — Optional (for position sync)</div>
            <ol style="padding-left:20px;color:var(--text-secondary);font-size:13px;">
                <li>Log into eToro web platform</li>
                <li>Go to <strong>Settings</strong> → <strong>API</strong></li>
                <li>Generate an API key (account must be verified)</li>
                <li>Paste it in the <a href="{% url 'setup' %}" style="color:var(--accent);">Setup page</a></li>
                <li>Docs: <a href="https://api-portal.etoro.com" target="_blank" style="color:var(--accent);">api-portal.etoro.com</a></li>
            </ol>
        </div>
    </div>
</div>

<div class="card fade-in-up delay-2" style="margin-bottom: 24px;">
    <div class="card-header"><span class="card-title">Step 2 — Configure Your .env File</span></div>
    <div style="font-size:14px;line-height:1.9;">
        <p style="color:var(--text-secondary);margin-bottom:12px;">Open the <code>.env</code> file in your project root and fill in your keys:</p>
        <pre style="background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);padding:16px;font-family:var(--font-mono);font-size:12px;color:var(--accent);overflow-x:auto;">ANTHROPIC_API_KEY=sk-ant-api03-your-key-here
ALPHA_VANTAGE_API_KEY=your-key-here
FRED_API_KEY=your-key-here
TWELVE_DATA_API_KEY=your-key-here
FINNHUB_API_KEY=your-key-here
ETORO_API_KEY=your-etoro-key-here
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id</pre>
    </div>
</div>

<div class="card fade-in-up delay-3" style="margin-bottom: 24px;">
    <div class="card-header"><span class="card-title">Step 3 — Start the Platform</span></div>
    <div style="font-size:14px;line-height:1.9;">
        <p style="color:var(--text-secondary);margin-bottom:12px;">Once your keys are set, start the Celery workers to begin data collection:</p>
        <pre style="background:var(--bg-void);border:1px solid var(--border);border-radius:var(--radius);padding:16px;font-family:var(--font-mono);font-size:12px;color:var(--accent);overflow-x:auto;"># Terminal 1 — Django web server
python manage.py runserver

# Terminal 2 — Fast worker (prices, news, signals)
celery -A config worker -l info -Q fast,default -c 4

# Terminal 3 — Slow worker (AI agents, analysis)
celery -A config worker -l info -Q slow,ai -c 2

# Terminal 4 — Beat scheduler (automated tasks)
celery -A config beat -l info</pre>
        <p style="color:var(--text-muted);font-family:var(--font-mono);font-size:12px;margin-top:12px;">
            On Render.com all workers start automatically from render.yaml.
        </p>
    </div>
</div>

<div class="card fade-in-up delay-4">
    <div class="card-header"><span class="card-title">Step 4 — Set Up Your Portfolio</span></div>
    <div style="font-size:14px;line-height:1.9;color:var(--text-secondary);">
        <p>Go to <a href="{% url 'setup' %}" style="color:var(--accent);font-weight:600;">⚙ Setup</a> to:</p>
        <ul style="padding-left:20px;margin-top:8px;">
            <li>Set your initial capital and base currency</li>
            <li>Configure risk limits (max exposure, max loss, correlation threshold)</li>
            <li>Connect eToro to auto-sync positions</li>
            <li>Or manually add your existing positions</li>
        </ul>
        <p style="margin-top:16px;">Once configured, the dashboard will populate with live data as the scrapers and AI agents begin their work.</p>
    </div>
</div>
{% endblock %}
'''))

    # ================================================================
    # UPDATED VIEWS — add setup + getting_started
    # ================================================================

    # Read existing views and append new ones
    setup_views = '''

@login_required
def setup(request):
    """Account setup: capital, risk, eToro, manual positions."""
    import os
    from django.contrib import messages
    from portfolio.services import get_or_create_default_portfolio
    from portfolio.models import Position
    from instruments.models import Instrument
    from django.utils import timezone

    portfolio = get_or_create_default_portfolio()

    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "update_capital":
            portfolio.initial_capital = request.POST.get("initial_capital", portfolio.initial_capital)
            portfolio.current_value = request.POST.get("current_value", portfolio.current_value)
            portfolio.cash_available = request.POST.get("cash_available", portfolio.cash_available)
            portfolio.currency = request.POST.get("currency", portfolio.currency)
            portfolio.save()
            messages.success(request, "Portfolio capital updated successfully.")

        elif action == "update_risk":
            portfolio.max_total_exposure_pct = float(request.POST.get("max_exposure", 100))
            portfolio.max_single_position_pct = float(request.POST.get("max_position", 10))
            portfolio.max_daily_loss_pct = float(request.POST.get("max_daily_loss", 3))
            portfolio.max_correlation_threshold = float(request.POST.get("max_correlation", 0.7))
            portfolio.save()
            messages.success(request, "Risk limits updated successfully.")

        elif action == "connect_etoro":
            etoro_key = request.POST.get("etoro_api_key", "").strip()
            if etoro_key:
                # Store in env or DB (for simplicity, write to .env-like storage)
                os.environ["ETORO_API_KEY"] = etoro_key
                messages.success(request, "eToro API key saved. Use Sync to pull positions.")
            else:
                messages.error(request, "Please provide an eToro API key.")

        elif action == "sync_etoro":
            from market_data.adapters.etoro_adapter import sync_etoro_positions
            result = sync_etoro_positions()
            if result.get("status") == "success":
                messages.success(request, f"Synced {result['synced']} positions from eToro.")
            elif result.get("status") == "not_configured":
                messages.error(request, "eToro API key not configured.")
            else:
                messages.error(request, "Failed to sync eToro positions. Check your API key.")

        elif action == "add_position":
            symbol = request.POST.get("symbol", "").upper().strip()
            if symbol:
                instrument, _ = Instrument.objects.get_or_create(
                    symbol=symbol,
                    defaults={
                        "name": symbol,
                        "asset_class": request.POST.get("asset_class", "stock"),
                        "is_active": True,
                    }
                )
                Position.objects.create(
                    portfolio=portfolio,
                    instrument=instrument,
                    direction=request.POST.get("direction", "long"),
                    quantity=request.POST.get("quantity", 0),
                    entry_price=request.POST.get("entry_price", 0),
                    current_price=request.POST.get("entry_price", 0),
                    stop_loss=request.POST.get("stop_loss") or None,
                    take_profit=request.POST.get("take_profit") or None,
                    opened_at=timezone.now(),
                )
                messages.success(request, f"Position {symbol} added successfully.")
            else:
                messages.error(request, "Symbol is required.")

        from django.shortcuts import redirect
        return redirect("setup")

    # API keys status
    api_keys = [
        {"name": "Anthropic (Claude AI)", "configured": bool(os.getenv("ANTHROPIC_API_KEY")), "url": "https://console.anthropic.com", "url_label": "console.anthropic.com"},
        {"name": "Alpha Vantage", "configured": bool(os.getenv("ALPHA_VANTAGE_API_KEY")), "url": "https://www.alphavantage.co/support/#api-key", "url_label": "alphavantage.co"},
        {"name": "Twelve Data", "configured": bool(os.getenv("TWELVE_DATA_API_KEY")), "url": "https://twelvedata.com", "url_label": "twelvedata.com"},
        {"name": "Finnhub", "configured": bool(os.getenv("FINNHUB_API_KEY")), "url": "https://finnhub.io", "url_label": "finnhub.io"},
        {"name": "FMP", "configured": bool(os.getenv("FMP_API_KEY")), "url": "https://financialmodelingprep.com", "url_label": "financialmodelingprep.com"},
        {"name": "FRED", "configured": bool(os.getenv("FRED_API_KEY")), "url": "https://fred.stlouisfed.org/docs/api/api_key.html", "url_label": "fred.stlouisfed.org"},
        {"name": "eToro", "configured": bool(os.getenv("ETORO_API_KEY")), "url": "https://api-portal.etoro.com", "url_label": "api-portal.etoro.com"},
        {"name": "Telegram", "configured": bool(os.getenv("TELEGRAM_BOT_TOKEN")), "url": "https://core.telegram.org/bots#botfather", "url_label": "BotFather"},
    ]

    etoro_key = os.getenv("ETORO_API_KEY", "")
    etoro_masked = ("●" * 20 + etoro_key[-4:]) if len(etoro_key) > 4 else ""

    return render(request, "dashboard/setup.html", {
        "page_id": "setup",
        "portfolio": portfolio,
        "api_keys": api_keys,
        "etoro_connected": bool(etoro_key),
        "etoro_key_masked": etoro_masked,
    })


@login_required
def getting_started(request):
    return render(request, "dashboard/getting_started.html", {"page_id": "getting_started"})
'''

    # Read current views.py and append
    views_path = "dashboard/views.py"
    if os.path.exists(views_path):
        with open(views_path, "r", encoding="utf-8") as f:
            existing = f.read()
        # Only append if not already there
        if "def setup(" not in existing:
            with open(views_path, "a", encoding="utf-8") as f:
                f.write(setup_views)
            created.append(views_path)
    else:
        created.append(create_file(views_path, setup_views))

    # ================================================================
    # UPDATED URLS — add setup + getting_started + ETORO_API_KEY to .env
    # ================================================================

    # Read current urls.py and add new paths
    urls_path = "dashboard/urls.py"
    if os.path.exists(urls_path):
        with open(urls_path, "r", encoding="utf-8") as f:
            existing = f.read()
        if "setup" not in existing:
            existing = existing.replace(
                'path("ai/tasks/", views.ai_tasks_list, name="ai_tasks_list"),',
                'path("ai/tasks/", views.ai_tasks_list, name="ai_tasks_list"),\n'
                '    path("setup/", views.setup, name="setup"),\n'
                '    path("getting-started/", views.getting_started, name="getting_started"),'
            )
            with open(urls_path, "w", encoding="utf-8") as f:
                f.write(existing)
            created.append(urls_path)

    # ================================================================
    # UPDATE SIDEBAR in base.html — add Setup + Getting Started links
    # ================================================================

    base_path = "templates/base.html"
    if os.path.exists(base_path):
        with open(base_path, "r", encoding="utf-8") as f:
            base_content = f.read()
        if "setup" not in base_content:
            base_content = base_content.replace(
                '''</nav>
        <div class="sidebar-footer">''',
                '''    <div class="nav-section">System</div>
            <a href="{% url 'setup' %}" class="nav-link {% if page_id == 'setup' %}active{% endif %}"><span class="icon">⚙</span> Setup</a>
            <a href="{% url 'getting_started' %}" class="nav-link {% if page_id == 'getting_started' %}active{% endif %}"><span class="icon">📡</span> Getting Started</a>
        </nav>
        <div class="sidebar-footer">'''
            )

            # Also fix favicon to use inline data URI
            base_content = base_content.replace(
                '''<link rel="icon" type="image/svg+xml" href="{% static 'favicon.svg' %}">''',
                f'''<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,{favicon_b64}">
    <link rel="icon" type="image/svg+xml" href="{{% static 'favicon.svg' %}}">'''
            )

            with open(base_path, "w", encoding="utf-8") as f:
                f.write(base_content)
            created.append(base_path)

    # Fix login page favicon too
    login_path = "templates/registration/login.html"
    if os.path.exists(login_path):
        with open(login_path, "r", encoding="utf-8") as f:
            login_content = f.read()
        login_content = login_content.replace(
            '''<link rel="icon" type="image/svg+xml" href="{% static 'favicon.svg' %}">''',
            f'''<link rel="icon" type="image/svg+xml" href="data:image/svg+xml;base64,{favicon_b64}">'''
        )
        with open(login_path, "w", encoding="utf-8") as f:
            f.write(login_content)
        created.append(login_path)

    # Add ETORO_API_KEY to .env if not present
    env_path = ".env"
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            env_content = f.read()
        if "ETORO_API_KEY" not in env_content:
            env_content += "\n# eToro Integration\nETORO_API_KEY=\n"
            with open(env_path, "w", encoding="utf-8") as f:
                f.write(env_content)
            created.append(env_path)

    # Add STATICFILES_DIRS to settings if not present
    settings_path = "config/settings.py"
    if os.path.exists(settings_path):
        with open(settings_path, "r", encoding="utf-8") as f:
            settings = f.read()
        if "STATICFILES_DIRS" not in settings:
            settings = settings.replace(
                'STATIC_ROOT = BASE_DIR / "staticfiles"',
                'STATIC_ROOT = BASE_DIR / "staticfiles"\nSTATICFILES_DIRS = [BASE_DIR / "static"]'
            )
            with open(settings_path, "w", encoding="utf-8") as f:
                f.write(settings)
            created.append(settings_path)

    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║   🟢  SAURON VISION — Patch v3 Applied ({len(created)} files)         ║
╚══════════════════════════════════════════════════════════════════╝

  1. Favicon — inline data URI (works immediately)     ✓
  2. Globe-eye — perfected, globe touches eye bounds   ✓
  3. Setup page — capital, risk, eToro, positions       ✓
  4. Getting Started guide — API keys, how to launch   ✓
  5. eToro adapter — position sync via official API     ✓

  New pages:
    /setup/            → Account & portfolio config
    /getting-started/  → Step-by-step launch guide

  Run: python manage.py collectstatic --no-input
  Then refresh. 🟢
""")


if __name__ == "__main__":
    generate()
