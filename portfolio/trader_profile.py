"""Trader profile model — personal info + trading preferences."""
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
    # ── Theme ────────────────────────────────────
    theme_mode = models.CharField(max_length=10, default="dark", choices=[
        ("dark", "Dark Mode"),
        ("light", "Light Mode"),
    ])

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
