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

    # ── Cross-asset orchestrator (Phase 15) ──────────
    # User-controlled gate that prevents stacking themed exposure across asset
    # classes (e.g. simultaneously long crypto + long EUR + short USD futures
    # is one bet on dollar weakness, not three trades). Disabled by default;
    # turn on when you want the system to refuse new entries that push your
    # net theme exposure past your thresholds. Closes are never gated.
    cross_asset_orchestrator_enabled = models.BooleanField(default=False,
        help_text="Refuse new bot entries that stack same-theme exposure across asset classes.")
    max_usd_theme_exposure = models.FloatField(default=3.0,
        help_text="Max |net USD-theme units| across open positions. Each position contributes ±1.")
    max_equity_theme_exposure = models.FloatField(default=3.0,
        help_text="Max |net equity-beta units| across open positions. Each position contributes ±1.")
    # Phase 24 — extra dimensions, opt-in (set to 0 to disable individually).
    max_vol_theme_exposure = models.FloatField(default=0.0,
        help_text="Max long-volatility (long-premium options) positions stacked. 0 = disabled.")
    max_currency_exposure = models.FloatField(default=0.0,
        help_text="Max |net exposure| to any single currency from forex pairs. 0 = disabled.")
    max_sector_exposure = models.IntegerField(default=0,
        help_text="Max concurrent stock/option positions in any single sector. 0 = disabled.")
    # Phase 25 — when True, theme contributions are scaled by position notional
    # relative to the config's default position size. A 2x-sized position
    # contributes ±2 to its themes; default-sized = ±1; clamped to [0.1, 5.0].
    size_weighted_orchestrator = models.BooleanField(default=False,
        help_text="Weight orchestrator theme contributions by position notional. Off = each position contributes ±1.")

    # Phase 27 — tax-lot accounting method. Used by tax_lots.close_lots_for
    # when a trade closes to decide which open lot(s) to consume first.
    TAX_LOT_METHOD_CHOICES = [
        ("FIFO", "FIFO — First In, First Out (US default)"),
        ("LIFO", "LIFO — Last In, First Out"),
        ("HIFO", "HIFO — Highest Cost In, First Out (tax-loss optimal)"),
    ]
    tax_lot_method = models.CharField(
        max_length=4, choices=TAX_LOT_METHOD_CHOICES, default="FIFO",
        help_text="Lot-consumption order on sales for cost-basis bookkeeping.")

    # ── Meta ─────────────────────────────────────────
    # ── Theme ────────────────────────────────────
    theme_mode = models.CharField(max_length=10, default="dark", choices=[
        ("dark", "Dark Mode"),
        ("light", "Light Mode"),
    ])

    access_pin_hash = models.CharField(max_length=128, blank=True, default="", help_text="Hashed PIN code (2nd-factor)")
    # ── Idle PIN lock ────────────────────────────────
    # After this many minutes without activity the session is flagged
    # pin_locked (core/idle_lock.py) and the operator must re-enter the
    # PIN. Only ever engages when a PIN is set — without one there would
    # be nothing that could release the lock.
    IDLE_LOCK_MINUTES_CHOICES = [
        (5, "5 minutes"),
        (10, "10 minutes"),
        (15, "15 minutes"),
        (30, "30 minutes"),
        (60, "1 hour"),
    ]
    idle_lock_enabled = models.BooleanField(default=True,
        help_text="Lock the session behind the PIN after a period of inactivity.")
    idle_lock_minutes = models.PositiveSmallIntegerField(
        default=10, choices=IDLE_LOCK_MINUTES_CHOICES,
        help_text="Minutes of inactivity before the PIN lock engages.")
    # Null = the guided platform tour has not been finished or skipped —
    # it autostarts once on the next page load. A timestamp (not a bool)
    # so we know WHEN, and so every pre-existing user sees it once too.
    tour_completed_at = models.DateTimeField(
        null=True, blank=True,
        help_text="When the guided platform tour was finished or skipped. "
                  "Null = show once on next login.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Trader Profile"
        verbose_name_plural = "Trader Profiles"

    def __str__(self):
        return f"{self.user.username}'s Trading Profile"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # The idle-lock middleware caches (armed, minutes) per user to
        # avoid a query per request while a session sits idle. Setting a
        # PIN or changing the window has to take effect now, not when
        # that cache happens to expire.
        try:
            from django.core.cache import cache
            cache.delete(f"idlelock:cfg:{self.user_id}")
        except Exception:  # noqa: BLE001 — a dead cache must not block a save
            pass

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

    # ── Trading PIN ──────────────────────────────────────────────────
    # The PIN is the second factor on every money-arming action: flipping a
    # bot to live, changing broker credentials, releasing the kill switch.
    # A fresh superuser has no TraderProfile row at all, so these have to
    # work from nothing.

    def set_pin(self, raw_pin: str) -> None:
        """Store a new PIN. Hashed with Django's password hasher — the raw
        value is never written anywhere, including the audit log."""
        from django.contrib.auth.hashers import make_password
        self.access_pin_hash = make_password(raw_pin)

    def check_pin(self, raw_pin: str) -> bool:
        """Verify a PIN. False when no PIN has been set — an unset PIN must
        never read as 'anything matches'."""
        from django.contrib.auth.hashers import check_password
        if not self.access_pin_hash:
            return False
        return check_password(raw_pin or "", self.access_pin_hash)

    @property
    def has_pin(self) -> bool:
        return bool(self.access_pin_hash)


def get_or_create_profile(user):
    """The profile for `user`, creating it if this is the first look.

    Nothing creates TraderProfile rows on signup — there is no post_save
    receiver — so every caller has to be able to make one. Without this the
    PIN modal raised ImportError, which a bare `except` downgraded to a
    cosmetic 'profile module unavailable', and no PIN could ever be set on a
    fresh install. No PIN means no bot can be armed live.
    """
    profile, _ = TraderProfile.objects.get_or_create(user=user)
    return profile
