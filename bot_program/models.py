"""Bot Program models — Binance link, bot config, trades, scenarios."""
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
import base64, hashlib, json

def _derive_key(material: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(material.encode()).digest())


def _fernet_keys() -> list:
    """Keys to try when decrypting, newest first.

    Broker credentials used to be encrypted with a key derived from
    SECRET_KEY, which made two ordinary operations destructive: rotating
    SECRET_KEY (normal security hygiene) and moving to a new host (which
    regenerates it) both left every stored credential permanently
    unreadable — and, worse, silently routed live bots to PaperTrader.

    FERNET_KEY is now the key of record. The SECRET_KEY-derived key is kept
    as a read-only fallback so existing rows keep working; anything saved
    afterwards is written with FERNET_KEY. Set FERNET_KEY before migrating
    hosts and credentials survive the move.
    """
    keys = []
    configured = getattr(settings, "FERNET_KEY", "") or ""
    if configured:
        # Accept either a real Fernet key or arbitrary material we hash.
        try:
            Fernet(configured.encode())
            keys.append(configured.encode())
        except Exception:
            keys.append(_derive_key(configured))
    keys.append(_derive_key(getattr(settings, "SECRET_KEY", "sauron-default")))
    return keys


def _fernet() -> Fernet:
    """Cipher used for WRITING — always the preferred (first) key."""
    return Fernet(_fernet_keys()[0])


def _decrypt(token: str) -> str:
    """Decrypt with any known key, so rows written under the old
    SECRET_KEY-derived key keep working after FERNET_KEY is introduced."""
    if not token:
        return ""
    for key in _fernet_keys():
        try:
            return Fernet(key).decrypt(token.encode()).decode()
        except (InvalidToken, Exception):
            continue
    return ""

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
        key = _decrypt(self.api_key_enc)
        secret = _decrypt(self.api_secret_enc)
        return (key, secret) if key and secret else (None, None)

    def __str__(self): return f"{self.user.username} · Binance ({'testnet' if self.testnet else 'live'})"


class OANDAAccount(models.Model):
    """Encrypted OANDA v20 trading credentials — Phase-4 forex execution.

    Mirrors `BinanceAccount` so a user can have one Binance + one OANDA + one
    Alpaca account simultaneously, each routing different asset classes.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="oanda_account")
    label = models.CharField(max_length=60, default="Main")
    api_key_enc = models.TextField(blank=True)
    account_id_enc = models.TextField(blank=True)
    practice = models.BooleanField(default=True, help_text="Use OANDA practice (demo) endpoint.")
    connected = models.BooleanField(default=False)
    last_sync = models.DateTimeField(null=True, blank=True)
    last_balance = models.DecimalField(max_digits=18, decimal_places=4, default=0,
                                       help_text="In account base currency.")
    created_at = models.DateTimeField(auto_now_add=True)

    def set_credentials(self, api_key: str, account_id: str):
        f = _fernet()
        self.api_key_enc = f.encrypt(api_key.encode()).decode()
        self.account_id_enc = f.encrypt(account_id.encode()).decode()

    def get_credentials(self) -> "tuple[str, str] | tuple[None, None]":
        if not self.api_key_enc:
            return (None, None)
        key = _decrypt(self.api_key_enc)
        account_id = _decrypt(self.account_id_enc)
        return (key, account_id) if key and account_id else (None, None)

    def __str__(self):
        return f"{self.user.username} · OANDA ({'practice' if self.practice else 'live'})"


class IBKRAccount(models.Model):
    """Phase-14 Interactive Brokers connection — TWS / IB Gateway socket.

    IBKR's API is socket-based: TWS or IB Gateway must run on the deployment
    host (or a reachable host) and be configured to accept API connections.
    The `account_id_enc` is encrypted at rest because it identifies the
    customer's funded account; the client_id is just an integer namespace
    that lets multiple processes connect to the same TWS without colliding.

    Default ports:
        7497  TWS paper  | 7496  TWS live
        4002  Gateway paper | 4001  Gateway live
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE,
                                 related_name="ibkr_account")
    label = models.CharField(max_length=60, default="Main")

    host = models.CharField(max_length=120, default="127.0.0.1")
    port = models.IntegerField(default=7497,
        help_text="7497=TWS paper, 7496=TWS live, 4002=Gateway paper, 4001=Gateway live.")
    client_id = models.IntegerField(default=1,
        help_text="API client ID. Allows multiple connections to the same TWS.")
    account_id_enc = models.TextField(blank=True)

    paper = models.BooleanField(default=True,
        help_text="Informational — actual paper/live behaviour follows TWS port.")

    # Per-asset-class routing preferences. When set, IBKR routing OVERRIDES
    # the default broker_router mapping (Alpaca/OANDA/etc.).
    is_primary_for_stocks = models.BooleanField(default=False)
    is_primary_for_forex = models.BooleanField(default=False)
    is_primary_for_options = models.BooleanField(default=True,
        help_text="IBKR is the default for options since Alpaca/OANDA don't trade them at scale.")
    is_primary_for_commodity = models.BooleanField(default=False,
        help_text="IBKR routes futures via FUT contracts; commodity bot still defers to PaperTrader unless this is on.")
    is_primary_for_cfd = models.BooleanField(default=False,
        help_text="IBKR CFD trading — indices, commodities, shares. NOT available to US residents (IBKR LLC blocks CFDs); UK/EU/SG/HK accounts only.")

    connected = models.BooleanField(default=False)
    last_sync = models.DateTimeField(null=True, blank=True)
    last_balance_usd = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def set_credentials(self, account_id: str):
        """Only the IBKR account ID is encrypted — host/port/client_id are not secret."""
        f = _fernet()
        self.account_id_enc = f.encrypt(account_id.encode()).decode()

    def get_account_id(self) -> "str | None":
        if not self.account_id_enc:
            return None
        return _decrypt(self.account_id_enc) or None

    def is_primary_for(self, asset_class: str) -> bool:
        return bool({
            "stock": self.is_primary_for_stocks,
            "etf": self.is_primary_for_stocks,
            "index": self.is_primary_for_stocks,
            "forex": self.is_primary_for_forex,
            "options": self.is_primary_for_options,
            "commodity": self.is_primary_for_commodity,
            "cfd": self.is_primary_for_cfd,
        }.get(asset_class, False))

    def __str__(self):
        return f"{self.user.username} · IBKR @ {self.host}:{self.port} ({'paper' if self.paper else 'live'})"


class AlpacaAccount(models.Model):
    """Encrypted Alpaca v2 trading credentials — Phase-4 stock execution."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="alpaca_account")
    label = models.CharField(max_length=60, default="Main")
    api_key_enc = models.TextField(blank=True)
    api_secret_enc = models.TextField(blank=True)
    paper = models.BooleanField(default=True, help_text="Use Alpaca paper endpoint.")
    connected = models.BooleanField(default=False)
    last_sync = models.DateTimeField(null=True, blank=True)
    last_balance_usd = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def set_credentials(self, api_key: str, api_secret: str):
        f = _fernet()
        self.api_key_enc = f.encrypt(api_key.encode()).decode()
        self.api_secret_enc = f.encrypt(api_secret.encode()).decode()

    def get_credentials(self) -> "tuple[str, str] | tuple[None, None]":
        if not self.api_key_enc:
            return (None, None)
        key = _decrypt(self.api_key_enc)
        secret = _decrypt(self.api_secret_enc)
        return (key, secret) if key and secret else (None, None)

    def __str__(self):
        return f"{self.user.username} · Alpaca ({'paper' if self.paper else 'live'})"


class BotConfig(models.Model):
    """One bot configuration per user. Defines strategy weights & risk."""
    MODE_CHOICES = [
        ("paper",  "Paper Trading (simulated, safe)"),
        ("live",   "Live Trading (real funds)"),
    ]
    MARKET_CHOICES = [("spot","Spot"), ("futures","USDT-M Futures")]
    MARGIN_CHOICES = [("isolated","Isolated"), ("cross","Cross")]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="bot_config")
    name = models.CharField(max_length=80, default="Sauron Bot")
    enabled = models.BooleanField(default=False)
    mode = models.CharField(max_length=8, choices=MODE_CHOICES, default="paper")
    market_type = models.CharField(max_length=10, choices=MARKET_CHOICES, default="spot")
    margin_mode = models.CharField(max_length=10, choices=MARGIN_CHOICES, default="isolated")

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

    class Meta:
        # One config per user (OneToOne), listed admin-wide — order by owner.
        ordering = ["user__username"]

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

from .models_v2 import (  # noqa: F401
    BotHeartbeat, BotCircuitState, BotShadowState,
    BotShadowAction, BotSymbolOverride,
)
from .asset_models import AssetBotConfig, AssetBotTrade  # noqa: F401
from .options_models import OptionContract  # noqa: F401
from .orchestrator_models import OrchestratorEvent  # noqa: F401
from .backtest_models import BotBacktestRun  # noqa: F401
from .track_record_models import RuleTrackRecordAlert  # noqa: F401
from .audit_models import AuditLogEntry  # noqa: F401
from .tax_lot_models import TaxLot, TaxLotConsumption  # noqa: F401
