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
