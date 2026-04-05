#!/usr/bin/env python3
"""
SAURON VISION — Patch v3.1
Profile setup: personal info + trading profile/preferences
Run inside sauron_vision/ directory.
"""
import os

def create_file(path, content=""):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path

def patch_file(path, marker, insertion):
    """Insert text into existing file if marker not already present."""
    if not os.path.exists(path):
        return False
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    if marker in content:
        return False
    return content  # Return content for caller to modify

def generate():
    created = []

    # ================================================================
    # 1. TRADER PROFILE MODEL
    # ================================================================

    created.append(create_file("portfolio/trader_profile.py", '''"""Trader profile model — personal info + trading preferences."""
from django.db import models
from django.contrib.auth.models import User


class TraderProfile(models.Model):
    """Extended user profile for trading preferences."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="trader_profile")

    # ── Personal Info ────────────────────────────────
    display_name = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True, help_text="Short bio or trading motto")
    location = models.CharField(max_length=100, blank=True)
    timezone_preference = models.CharField(max_length=50, default="UTC")
    phone = models.CharField(max_length=30, blank=True)

    # ── Trading Profile ──────────────────────────────
    EXPERIENCE_CHOICES = [
        ("beginner", "Beginner (< 1 year)"),
        ("intermediate", "Intermediate (1–3 years)"),
        ("advanced", "Advanced (3–7 years)"),
        ("expert", "Expert (7+ years)"),
        ("professional", "Professional / Institutional"),
    ]

    STYLE_CHOICES = [
        ("scalper", "Scalper (seconds–minutes)"),
        ("day_trader", "Day Trader (intraday)"),
        ("swing_trader", "Swing Trader (days–weeks)"),
        ("position_trader", "Position Trader (weeks–months)"),
        ("investor", "Long-Term Investor (months–years)"),
        ("hybrid", "Hybrid / Multi-timeframe"),
    ]

    RISK_CHOICES = [
        ("conservative", "Conservative — Capital preservation first"),
        ("moderate", "Moderate — Balanced growth and safety"),
        ("aggressive", "Aggressive — High returns, accept volatility"),
        ("very_aggressive", "Very Aggressive — Maximum growth, high risk tolerance"),
    ]

    ANALYSIS_CHOICES = [
        ("technical", "Primarily Technical Analysis"),
        ("fundamental", "Primarily Fundamental Analysis"),
        ("quantitative", "Quantitative / Algorithmic"),
        ("sentiment", "Sentiment / News-Driven"),
        ("mixed", "Mixed Approach"),
    ]

    experience_level = models.CharField(max_length=20, choices=EXPERIENCE_CHOICES, default="intermediate")
    trading_style = models.CharField(max_length=20, choices=STYLE_CHOICES, default="swing_trader")
    risk_appetite = models.CharField(max_length=20, choices=RISK_CHOICES, default="moderate")
    analysis_approach = models.CharField(max_length=20, choices=ANALYSIS_CHOICES, default="mixed")

    # ── Market Preferences ───────────────────────────
    trade_stocks = models.BooleanField(default=True)
    trade_forex = models.BooleanField(default=True)
    trade_commodities = models.BooleanField(default=True)
    trade_crypto = models.BooleanField(default=False)
    trade_indices = models.BooleanField(default=False)
    trade_bonds = models.BooleanField(default=False)

    # ── Session Preferences ──────────────────────────
    SESSION_CHOICES = [
        ("asian", "Asian Session (Tokyo)"),
        ("european", "European Session (London)"),
        ("american", "American Session (New York)"),
        ("all", "All Sessions"),
    ]
    preferred_session = models.CharField(max_length=20, choices=SESSION_CHOICES, default="european")
    available_hours_per_day = models.FloatField(default=2.0, help_text="Hours per day available for trading")

    # ── Goals & Targets ──────────────────────────────
    monthly_return_target_pct = models.FloatField(default=3.0)
    max_acceptable_drawdown_pct = models.FloatField(default=10.0)
    annual_income_target = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # ── Notification Preferences ─────────────────────
    notify_signals = models.BooleanField(default=True, help_text="Get alerts for new trading signals")
    notify_strategies = models.BooleanField(default=True, help_text="Get alerts for strategy proposals")
    notify_news_critical = models.BooleanField(default=True, help_text="Get alerts for critical market news")
    notify_portfolio = models.BooleanField(default=True, help_text="Get alerts for portfolio changes")
    notify_weekly_review = models.BooleanField(default=True, help_text="Receive weekly AI review")
    notify_channel = models.CharField(max_length=20, default="telegram", choices=[
        ("telegram", "Telegram"),
        ("email", "Email"),
        ("discord", "Discord"),
        ("none", "No notifications"),
    ])

    # ── AI Preferences ───────────────────────────────
    ai_autonomy = models.CharField(max_length=20, default="suggest", choices=[
        ("observe", "Observe Only — AI watches, I decide everything"),
        ("suggest", "Suggest — AI proposes, I approve/reject"),
        ("semi_auto", "Semi-Auto — AI executes low-risk, I approve high-risk"),
        ("full_auto", "Full Auto — AI manages within my risk parameters"),
    ])
    ai_commentary_detail = models.CharField(max_length=20, default="detailed", choices=[
        ("brief", "Brief — Key points only"),
        ("detailed", "Detailed — Full analysis with reasoning"),
        ("comprehensive", "Comprehensive — Deep dive with alternatives"),
    ])

    # ── Meta ─────────────────────────────────────────
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Trader Profile"
        verbose_name_plural = "Trader Profiles"

    def __str__(self):
        return f"{self.user.username}'s Trading Profile"

    @property
    def markets_traded(self):
        markets = []
        if self.trade_stocks: markets.append("Stocks")
        if self.trade_forex: markets.append("Forex")
        if self.trade_commodities: markets.append("Commodities")
        if self.trade_crypto: markets.append("Crypto")
        if self.trade_indices: markets.append("Indices")
        if self.trade_bonds: markets.append("Bonds")
        return markets
'''))

    # ================================================================
    # 2. ADMIN REGISTRATION
    # ================================================================

    # Append to portfolio/admin.py
    admin_path = "portfolio/admin.py"
    if os.path.exists(admin_path):
        with open(admin_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "TraderProfile" not in content:
            content += '''

from .trader_profile import TraderProfile

@admin.register(TraderProfile)
class TraderProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "display_name", "experience_level", "trading_style", "risk_appetite"]
    list_filter = ["experience_level", "trading_style", "risk_appetite"]
'''
            with open(admin_path, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(admin_path)

    # ================================================================
    # 3. PROFILE TEMPLATE
    # ================================================================

    created.append(create_file("templates/dashboard/profile.html", r'''{% extends "base.html" %}
{% block title %}Profile — Sauron Vision{% endblock %}
{% block page_title %}◉ OPERATOR PROFILE{% endblock %}

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

<form method="post" action="{% url 'profile' %}">
{% csrf_token %}

<!-- ── Personal Info ─────────────────────────────── -->
<div class="section-label fade-in-up">Personal Information</div>
<div class="grid grid-2" style="margin-bottom: 24px;">
    <div class="card fade-in-up delay-1">
        <div class="card-header"><span class="card-title">◉ Identity</span></div>

        <div style="margin-bottom:16px;">
            <label class="form-label">USERNAME</label>
            <input type="text" value="{{ user.username }}" disabled class="form-input" style="opacity:0.5;">
            <div class="form-hint">Cannot be changed</div>
        </div>

        <div style="margin-bottom:16px;">
            <label class="form-label">DISPLAY NAME</label>
            <input type="text" name="display_name" value="{{ profile.display_name }}" placeholder="Your trading alias" class="form-input">
        </div>

        <div style="margin-bottom:16px;">
            <label class="form-label">EMAIL</label>
            <input type="email" name="email" value="{{ user.email }}" class="form-input">
        </div>

        <div style="margin-bottom:16px;">
            <label class="form-label">FIRST NAME</label>
            <input type="text" name="first_name" value="{{ user.first_name }}" class="form-input">
        </div>

        <div style="margin-bottom:16px;">
            <label class="form-label">LAST NAME</label>
            <input type="text" name="last_name" value="{{ user.last_name }}" class="form-input">
        </div>
    </div>

    <div class="card fade-in-up delay-2">
        <div class="card-header"><span class="card-title">◈ Details</span></div>

        <div style="margin-bottom:16px;">
            <label class="form-label">LOCATION</label>
            <input type="text" name="location" value="{{ profile.location }}" placeholder="City, Country" class="form-input">
        </div>

        <div style="margin-bottom:16px;">
            <label class="form-label">PHONE (optional)</label>
            <input type="text" name="phone" value="{{ profile.phone }}" placeholder="+33 6 00 00 00 00" class="form-input">
        </div>

        <div style="margin-bottom:16px;">
            <label class="form-label">TIMEZONE</label>
            <select name="timezone_preference" class="form-input">
                {% for tz in timezones %}
                <option value="{{ tz }}" {% if profile.timezone_preference == tz %}selected{% endif %}>{{ tz }}</option>
                {% endfor %}
            </select>
        </div>

        <div style="margin-bottom:16px;">
            <label class="form-label">BIO / TRADING MOTTO</label>
            <textarea name="bio" rows="3" class="form-input" placeholder="Your trading philosophy...">{{ profile.bio }}</textarea>
        </div>
    </div>
</div>

<!-- ── Trading Profile ───────────────────────────── -->
<div class="section-label fade-in-up">Trading Profile</div>
<div class="grid grid-2" style="margin-bottom: 24px;">
    <div class="card fade-in-up delay-3">
        <div class="card-header"><span class="card-title">⬡ Style & Experience</span></div>

        <div style="margin-bottom:16px;">
            <label class="form-label">EXPERIENCE LEVEL</label>
            <select name="experience_level" class="form-input">
                {% for val, label in experience_choices %}
                <option value="{{ val }}" {% if profile.experience_level == val %}selected{% endif %}>{{ label }}</option>
                {% endfor %}
            </select>
        </div>

        <div style="margin-bottom:16px;">
            <label class="form-label">TRADING STYLE</label>
            <select name="trading_style" class="form-input">
                {% for val, label in style_choices %}
                <option value="{{ val }}" {% if profile.trading_style == val %}selected{% endif %}>{{ label }}</option>
                {% endfor %}
            </select>
        </div>

        <div style="margin-bottom:16px;">
            <label class="form-label">RISK APPETITE</label>
            <select name="risk_appetite" class="form-input">
                {% for val, label in risk_choices %}
                <option value="{{ val }}" {% if profile.risk_appetite == val %}selected{% endif %}>{{ label }}</option>
                {% endfor %}
            </select>
        </div>

        <div style="margin-bottom:16px;">
            <label class="form-label">ANALYSIS APPROACH</label>
            <select name="analysis_approach" class="form-input">
                {% for val, label in analysis_choices %}
                <option value="{{ val }}" {% if profile.analysis_approach == val %}selected{% endif %}>{{ label }}</option>
                {% endfor %}
            </select>
        </div>

        <div style="margin-bottom:16px;">
            <label class="form-label">PREFERRED SESSION</label>
            <select name="preferred_session" class="form-input">
                {% for val, label in session_choices %}
                <option value="{{ val }}" {% if profile.preferred_session == val %}selected{% endif %}>{{ label }}</option>
                {% endfor %}
            </select>
        </div>

        <div style="margin-bottom:16px;">
            <label class="form-label">HOURS AVAILABLE PER DAY</label>
            <input type="number" step="0.5" name="available_hours_per_day" value="{{ profile.available_hours_per_day }}" class="form-input">
        </div>
    </div>

    <div class="card fade-in-up delay-4">
        <div class="card-header"><span class="card-title">◆ Markets & Goals</span></div>

        <div style="margin-bottom:18px;">
            <label class="form-label">MARKETS I TRADE</label>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-top:6px;">
                <label class="toggle-label"><input type="checkbox" name="trade_stocks" {% if profile.trade_stocks %}checked{% endif %}> <span>Stocks</span></label>
                <label class="toggle-label"><input type="checkbox" name="trade_forex" {% if profile.trade_forex %}checked{% endif %}> <span>Forex</span></label>
                <label class="toggle-label"><input type="checkbox" name="trade_commodities" {% if profile.trade_commodities %}checked{% endif %}> <span>Commodities</span></label>
                <label class="toggle-label"><input type="checkbox" name="trade_crypto" {% if profile.trade_crypto %}checked{% endif %}> <span>Crypto</span></label>
                <label class="toggle-label"><input type="checkbox" name="trade_indices" {% if profile.trade_indices %}checked{% endif %}> <span>Indices</span></label>
                <label class="toggle-label"><input type="checkbox" name="trade_bonds" {% if profile.trade_bonds %}checked{% endif %}> <span>Bonds</span></label>
            </div>
        </div>

        <div style="margin-bottom:16px;">
            <label class="form-label">MONTHLY RETURN TARGET (%)</label>
            <input type="number" step="0.5" name="monthly_return_target_pct" value="{{ profile.monthly_return_target_pct }}" class="form-input">
        </div>

        <div style="margin-bottom:16px;">
            <label class="form-label">MAX ACCEPTABLE DRAWDOWN (%)</label>
            <input type="number" step="1" name="max_acceptable_drawdown_pct" value="{{ profile.max_acceptable_drawdown_pct }}" class="form-input">
        </div>

        <div style="margin-bottom:16px;">
            <label class="form-label">ANNUAL INCOME TARGET (€)</label>
            <input type="number" step="100" name="annual_income_target" value="{{ profile.annual_income_target|floatformat:0 }}" placeholder="0 = no target" class="form-input">
        </div>
    </div>
</div>

<!-- ── AI & Notification Preferences ─────────────── -->
<div class="section-label fade-in-up">AI & Notifications</div>
<div class="grid grid-2" style="margin-bottom: 24px;">
    <div class="card fade-in-up delay-5">
        <div class="card-header"><span class="card-title">◬ AI Behavior</span></div>

        <div style="margin-bottom:16px;">
            <label class="form-label">AI AUTONOMY LEVEL</label>
            <select name="ai_autonomy" class="form-input">
                <option value="observe" {% if profile.ai_autonomy == "observe" %}selected{% endif %}>Observe Only — AI watches, I decide everything</option>
                <option value="suggest" {% if profile.ai_autonomy == "suggest" %}selected{% endif %}>Suggest — AI proposes, I approve/reject</option>
                <option value="semi_auto" {% if profile.ai_autonomy == "semi_auto" %}selected{% endif %}>Semi-Auto — AI executes low-risk, I approve high-risk</option>
                <option value="full_auto" {% if profile.ai_autonomy == "full_auto" %}selected{% endif %}>Full Auto — AI manages within my risk parameters</option>
            </select>
            <div class="form-hint">Controls how much autonomy AI agents have over your portfolio</div>
        </div>

        <div style="margin-bottom:16px;">
            <label class="form-label">AI COMMENTARY DETAIL</label>
            <select name="ai_commentary_detail" class="form-input">
                <option value="brief" {% if profile.ai_commentary_detail == "brief" %}selected{% endif %}>Brief — Key points only</option>
                <option value="detailed" {% if profile.ai_commentary_detail == "detailed" %}selected{% endif %}>Detailed — Full analysis with reasoning</option>
                <option value="comprehensive" {% if profile.ai_commentary_detail == "comprehensive" %}selected{% endif %}>Comprehensive — Deep dive with alternatives</option>
            </select>
            <div class="form-hint">How verbose AI agents are in their reports and briefings</div>
        </div>
    </div>

    <div class="card fade-in-up delay-6">
        <div class="card-header"><span class="card-title">🔔 Notifications</span></div>

        <div style="margin-bottom:16px;">
            <label class="form-label">NOTIFICATION CHANNEL</label>
            <select name="notify_channel" class="form-input">
                <option value="telegram" {% if profile.notify_channel == "telegram" %}selected{% endif %}>Telegram</option>
                <option value="email" {% if profile.notify_channel == "email" %}selected{% endif %}>Email</option>
                <option value="discord" {% if profile.notify_channel == "discord" %}selected{% endif %}>Discord</option>
                <option value="none" {% if profile.notify_channel == "none" %}selected{% endif %}>No notifications</option>
            </select>
        </div>

        <div style="margin-bottom:18px;">
            <label class="form-label">WHAT TO NOTIFY</label>
            <div style="display:flex;flex-direction:column;gap:10px;margin-top:6px;">
                <label class="toggle-label"><input type="checkbox" name="notify_signals" {% if profile.notify_signals %}checked{% endif %}> <span>New trading signals</span></label>
                <label class="toggle-label"><input type="checkbox" name="notify_strategies" {% if profile.notify_strategies %}checked{% endif %}> <span>Strategy proposals</span></label>
                <label class="toggle-label"><input type="checkbox" name="notify_news_critical" {% if profile.notify_news_critical %}checked{% endif %}> <span>Critical market news</span></label>
                <label class="toggle-label"><input type="checkbox" name="notify_portfolio" {% if profile.notify_portfolio %}checked{% endif %}> <span>Portfolio changes & alerts</span></label>
                <label class="toggle-label"><input type="checkbox" name="notify_weekly_review" {% if profile.notify_weekly_review %}checked{% endif %}> <span>Weekly AI review</span></label>
            </div>
        </div>
    </div>
</div>

<div class="fade-in-up delay-6" style="text-align:center;padding:8px 0 40px;">
    <button type="submit" class="btn btn-primary" style="padding:14px 48px;font-size:14px;letter-spacing:3px;">
        SAVE PROFILE
    </button>
</div>

</form>

{% block extra_css %}
<style>
    .form-label {
        display: block;
        font-family: var(--font-mono); font-size: 10px;
        letter-spacing: 2px; color: var(--text-muted);
        text-transform: uppercase; margin-bottom: 6px;
    }
    .form-input {
        width: 100%; padding: 10px 14px;
        background: var(--bg-void); border: 1px solid var(--border);
        border-radius: var(--radius); color: var(--text-primary);
        font-family: var(--font-mono); font-size: 13px; outline: none;
        transition: border-color 0.2s;
    }
    .form-input:focus { border-color: var(--accent); box-shadow: 0 0 12px rgba(0,232,104,0.08); }
    textarea.form-input { font-family: var(--font-body); font-size: 14px; resize: vertical; }
    select.form-input { cursor: pointer; }
    .form-hint {
        font-family: var(--font-mono); font-size: 10px;
        color: var(--text-muted); margin-top: 4px; letter-spacing: 0.5px;
    }
    .toggle-label {
        display: flex; align-items: center; gap: 10px;
        font-size: 13px; color: var(--text-secondary); cursor: pointer;
        padding: 6px 10px; border-radius: var(--radius);
        transition: background 0.15s;
    }
    .toggle-label:hover { background: var(--bg-card-hover); }
    .toggle-label input[type="checkbox"] {
        appearance: none; -webkit-appearance: none;
        width: 18px; height: 18px; border: 1px solid var(--border);
        border-radius: 4px; background: var(--bg-void);
        cursor: pointer; position: relative; flex-shrink: 0;
    }
    .toggle-label input[type="checkbox"]:checked {
        background: var(--accent-dim); border-color: var(--accent);
    }
    .toggle-label input[type="checkbox"]:checked::after {
        content: '✓'; position: absolute; top: 0; left: 3px;
        font-size: 13px; color: var(--accent);
    }
    .toggle-label input[type="checkbox"]:checked + span { color: var(--text-primary); }
</style>
{% endblock %}
{% endblock %}
'''))

    # ================================================================
    # 4. PROFILE VIEW
    # ================================================================

    profile_view_code = '''

@login_required
def profile(request):
    """User profile: personal info + trading preferences."""
    from django.contrib import messages
    from portfolio.trader_profile import TraderProfile

    profile_obj, _ = TraderProfile.objects.get_or_create(user=request.user)

    if request.method == "POST":
        # Personal info (on User model)
        request.user.email = request.POST.get("email", request.user.email)
        request.user.first_name = request.POST.get("first_name", "")
        request.user.last_name = request.POST.get("last_name", "")
        request.user.save()

        # Profile fields
        profile_obj.display_name = request.POST.get("display_name", "")
        profile_obj.bio = request.POST.get("bio", "")
        profile_obj.location = request.POST.get("location", "")
        profile_obj.phone = request.POST.get("phone", "")
        profile_obj.timezone_preference = request.POST.get("timezone_preference", "UTC")

        # Trading profile
        profile_obj.experience_level = request.POST.get("experience_level", "intermediate")
        profile_obj.trading_style = request.POST.get("trading_style", "swing_trader")
        profile_obj.risk_appetite = request.POST.get("risk_appetite", "moderate")
        profile_obj.analysis_approach = request.POST.get("analysis_approach", "mixed")
        profile_obj.preferred_session = request.POST.get("preferred_session", "european")
        profile_obj.available_hours_per_day = float(request.POST.get("available_hours_per_day", 2))

        # Markets
        profile_obj.trade_stocks = "trade_stocks" in request.POST
        profile_obj.trade_forex = "trade_forex" in request.POST
        profile_obj.trade_commodities = "trade_commodities" in request.POST
        profile_obj.trade_crypto = "trade_crypto" in request.POST
        profile_obj.trade_indices = "trade_indices" in request.POST
        profile_obj.trade_bonds = "trade_bonds" in request.POST

        # Goals
        profile_obj.monthly_return_target_pct = float(request.POST.get("monthly_return_target_pct", 3))
        profile_obj.max_acceptable_drawdown_pct = float(request.POST.get("max_acceptable_drawdown_pct", 10))
        profile_obj.annual_income_target = request.POST.get("annual_income_target", 0) or 0

        # AI
        profile_obj.ai_autonomy = request.POST.get("ai_autonomy", "suggest")
        profile_obj.ai_commentary_detail = request.POST.get("ai_commentary_detail", "detailed")

        # Notifications
        profile_obj.notify_channel = request.POST.get("notify_channel", "telegram")
        profile_obj.notify_signals = "notify_signals" in request.POST
        profile_obj.notify_strategies = "notify_strategies" in request.POST
        profile_obj.notify_news_critical = "notify_news_critical" in request.POST
        profile_obj.notify_portfolio = "notify_portfolio" in request.POST
        profile_obj.notify_weekly_review = "notify_weekly_review" in request.POST

        profile_obj.save()
        messages.success(request, "Profile updated successfully.")

        from django.shortcuts import redirect
        return redirect("profile")

    # Common timezones
    timezones = [
        "UTC", "Europe/Paris", "Europe/London", "Europe/Berlin", "Europe/Zurich",
        "US/Eastern", "US/Central", "US/Pacific",
        "Asia/Tokyo", "Asia/Shanghai", "Asia/Singapore", "Asia/Dubai",
        "Australia/Sydney", "Pacific/Auckland",
    ]

    return render(request, "dashboard/profile.html", {
        "page_id": "profile",
        "profile": profile_obj,
        "timezones": timezones,
        "experience_choices": TraderProfile.EXPERIENCE_CHOICES,
        "style_choices": TraderProfile.STYLE_CHOICES,
        "risk_choices": TraderProfile.RISK_CHOICES,
        "analysis_choices": TraderProfile.ANALYSIS_CHOICES,
        "session_choices": TraderProfile.SESSION_CHOICES,
    })
'''

    # Append view to dashboard/views.py
    views_path = "dashboard/views.py"
    if os.path.exists(views_path):
        with open(views_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "def profile(" not in content:
            with open(views_path, "a", encoding="utf-8") as f:
                f.write(profile_view_code)
            created.append(views_path)

    # ================================================================
    # 5. ADD URL
    # ================================================================

    urls_path = "dashboard/urls.py"
    if os.path.exists(urls_path):
        with open(urls_path, "r", encoding="utf-8") as f:
            content = f.read()
        if '"profile"' not in content:
            content = content.replace(
                'path("setup/", views.setup, name="setup"),',
                'path("profile/", views.profile, name="profile"),\n'
                '    path("setup/", views.setup, name="setup"),'
            )
            with open(urls_path, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(urls_path)

    # ================================================================
    # 6. ADD SIDEBAR LINK
    # ================================================================

    base_path = "templates/base.html"
    if os.path.exists(base_path):
        with open(base_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "profile" not in content:
            content = content.replace(
                '''<div class="nav-section">System</div>''',
                '''<div class="nav-section">System</div>
            <a href="{% url 'profile' %}" class="nav-link {% if page_id == 'profile' %}active{% endif %}"><span class="icon">◉</span> Profile</a>'''
            )
            with open(base_path, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(base_path)

    # ================================================================
    # 7. ADD DISPLAY NAME TO TOPBAR
    # ================================================================

    if os.path.exists(base_path):
        with open(base_path, "r", encoding="utf-8") as f:
            content = f.read()
        if "trader_profile" not in content:
            content = content.replace(
                '{{ request.user.username|upper }}',
                '{% if request.user.trader_profile.display_name %}{{ request.user.trader_profile.display_name }}{% else %}{{ request.user.username|upper }}{% endif %}'
            )
            with open(base_path, "w", encoding="utf-8") as f:
                f.write(content)
            created.append(base_path)

    print(f"""
╔══════════════════════════════════════════════════════════════════╗
║   🟢  SAURON VISION — Patch v3.1 Applied ({len(created)} files)       ║
╚══════════════════════════════════════════════════════════════════╝

  New:
    portfolio/trader_profile.py     → TraderProfile model
    templates/dashboard/profile.html → Full profile page
    /profile/ URL + sidebar link    → Profile in navigation

  Profile sections:
    ◉ Identity — name, email, location, timezone, bio
    ⬡ Trading Style — experience, style, risk, analysis approach
    ◆ Markets & Goals — asset classes, targets, drawdown limits
    ◬ AI Behavior — autonomy level, commentary detail
    🔔 Notifications — channel, what to alert

  IMPORTANT — run these commands:

    python manage.py makemigrations portfolio
    python manage.py migrate
    python manage.py runserver

  The eye watches over your profile. 🟢
""")


if __name__ == "__main__":
    generate()
