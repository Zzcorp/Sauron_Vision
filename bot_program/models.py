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
        4004  docker Gateway paper (socat) | 4003  docker Gateway live (socat)
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE,
                                 related_name="ibkr_account")
    label = models.CharField(max_length=60, default="Main")

    host = models.CharField(max_length=120, default="127.0.0.1")
    port = models.IntegerField(default=7497,
        help_text="7497=TWS paper, 7496=TWS live, 4002=Gateway paper, 4001=Gateway live. DOCKERISED Gateway (the deploy stack): 4004=paper, 4003=live - the image relays through socat and refuses 4001/4002 from other containers.")
    client_id = models.IntegerField(default=1,
        help_text="BASE API client ID — must be UNIQUE per account and below "
                  "100. Sauron opens several sockets at once (trading, data "
                  "feed, connection test) and derives a distinct id for each "
                  "from this number. When two connections ask for the SAME "
                  "id, IBKR REFUSES the second (error 326) — it does not "
                  "evict the first. So a collision looks like a broker that "
                  "will not answer, never like a session that was stolen, "
                  "and the trading id is held exclusively for that reason.")
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

    # The last BROKER reading, written only by the sync_broker_account
    # beat task — never on a render or entry path. Nullable ON PURPOSE:
    # NULL is "never measured", which `last_balance_usd` above cannot say
    # (its default=0 renders an unmeasured account as an emptied one —
    # the reason that column is dead and stays dead). The currency rides
    # with the value because a UK ISA is GBP, the platform book defaults
    # to EUR, and this platform has no FX conversion anywhere by design —
    # an unlabelled equity becomes a number behind the wrong symbol.
    last_equity = models.DecimalField(max_digits=18, decimal_places=2,
                                      null=True, blank=True)
    last_equity_currency = models.CharField(max_length=8, blank=True,
                                            default="")
    last_equity_at = models.DateTimeField(null=True, blank=True)
    # The account's holdings as the broker values them (broker_portfolio()
    # rows, verbatim). A DISPLAY snapshot only: nothing imports these into
    # Position or AssetBotTrade — importing would double-count every
    # bot-opened position, since unified_open_positions concatenates the
    # two row sets with no dedup key.
    broker_positions = models.JSONField(null=True, blank=True)
    broker_positions_at = models.DateTimeField(null=True, blank=True)

    # The Gateway LOGIN. Sauron itself never authenticates to IBKR — it
    # connects to a socket that is already logged in — so these exist
    # only so IBC can sign the Gateway container in at boot. They live
    # here rather than in .env because the database is the one place
    # that is encrypted at rest, backed up, and editable by the account's
    # owner; `render_ibkr_env` writes them out when a slot is (re)started.
    username_enc = models.TextField(blank=True)
    password_enc = models.TextField(blank=True)

    # Which Gateway container serves this login. IBKR permits ONE session
    # per username, so separate logins need separate containers — but
    # accounts UNDER one login share a slot, and `account_id` is what
    # decides where an order lands. 1 is `ibgateway`, 2 is `ibgateway-2`.
    gateway_slot = models.PositiveSmallIntegerField(
        default=1,
        help_text="Which ibgateway container serves this login (1-5). "
                  "Logins that differ need different slots; accounts under "
                  "the SAME login should share one.")

    def set_credentials(self, account_id: str):
        """Only the IBKR account ID is encrypted — host/port/client_id are not secret."""
        f = _fernet()
        self.account_id_enc = f.encrypt(account_id.encode()).decode()

    def set_login(self, username: str, password: str):
        """Store the Gateway login. Blank leaves the stored value alone.

        Blank-means-keep matters on a form nobody wants to retype a
        password into: an edit to the routing checkboxes must not wipe
        the credential that logs the container in.
        """
        f = _fernet()
        if username:
            self.username_enc = f.encrypt(username.encode()).decode()
        if password:
            self.password_enc = f.encrypt(password.encode()).decode()

    def get_login(self) -> tuple:
        """(username, password), either possibly None."""
        return (_decrypt(self.username_enc) or None if self.username_enc
                else None,
                _decrypt(self.password_enc) or None if self.password_enc
                else None)

    @property
    def has_login(self) -> bool:
        return bool(self.username_enc and self.password_enc)

    @property
    def gateway_host(self) -> str:
        """The compose service name for this account's slot."""
        n = int(self.gateway_slot or 1)
        return "ibgateway" if n <= 1 else f"ibgateway-{n}"

    @property
    def env_prefix(self) -> str:
        """The .env variable prefix compose reads for this slot."""
        n = int(self.gateway_slot or 1)
        return "IBKR" if n <= 1 else f"IBKR{n}"

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

    #: The four ports IBKR ships. The socket you connect to IS the account
    #: you trade — there is no second switch inside the API — so these are
    #: the only fact on this model that decides whose money moves.
    # 4003/4004 are the containerised Gateway's SOCAT relay ports, and for
    # the dockerised deployment they are the ONLY ports that work. The
    # gnzsnz/ib-gateway image binds the Gateway's own 4001/4002 to the
    # container's 127.0.0.1 and relays them out through socat as
    # 4003 (-> 4001, live) and 4004 (-> 4002, paper) — so from the web
    # container, ibgateway:4001 answers CONNECTION REFUSED forever, even
    # after a perfect login. This platform's runbook pointed at 4001/4002
    # for weeks; the operator's first real Gateway proved it wrong.
    # The relay preserves the live/paper split, so the port keeps deciding
    # the environment — which is the property everything here rests on.
    PAPER_PORTS = {7497: "TWS", 4002: "IB Gateway",
                   4004: "IB Gateway (docker/socat)"}
    LIVE_PORTS = {7496: "TWS", 4001: "IB Gateway",
                  4003: "IB Gateway (docker/socat)"}

    @property
    def env(self) -> "str | None":
        """"paper", "live", or None when the port is not one IBKR ships.

        None is the important answer and it is NOT paper. An operator who
        has remapped the socket, or typed 7946 for 7496, is in a state this
        platform cannot classify — and a mistake in this direction sends a
        real order to a real account. Everything that renders this must show
        the unknown as an unknown and refuse to call it safe.
        """
        if self.port in self.PAPER_PORTS:
            return "paper"
        if self.port in self.LIVE_PORTS:
            return "live"
        return None

    @property
    def is_live(self) -> bool:
        """True ONLY for a port known to be live. An unknown port is not
        live for the purposes of a label — but see `env_is_certain`: it is
        not safe either, and the two questions have different answers."""
        return self.env == "live"

    @property
    def env_is_certain(self) -> bool:
        return self.env is not None

    @property
    def env_label(self) -> str:
        """What to print beside this connection, for humans."""
        if self.env is None:
            return f"UNKNOWN PORT {self.port}"
        return f"{self.env.upper()} · {(self.PAPER_PORTS | self.LIVE_PORTS)[self.port]}"

    @property
    def paper_flag_disagrees(self) -> bool:
        """The stored `paper` checkbox says one thing and the port another.

        The checkbox is documented as informational, so the port wins — but
        a disagreement means somebody believes something false about which
        account they are pointed at, and that is worth saying out loud
        rather than silently resolving.
        """
        return self.env is not None and self.paper != (self.env == "paper")

    def __str__(self):
        return f"{self.user.username} · IBKR @ {self.host}:{self.port} ({self.env or 'unknown port'})"


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


class EtoroAccount(models.Model):
    """Encrypted eToro API credentials (2026-09-17).

    eToro authenticates with two LONG-LIVED keys sent as headers on every
    request — `x-api-key` and `x-user-key` — not with OAuth. So unlike Saxo
    below there is no token to refresh and no daily human: a server holds
    the two strings and is done. That is the property IBKR refuses retail
    clients, and the reason this row exists.

    `demo` mirrors `paper` / `practice` / `testnet` on the other rows in
    shape only. Measured 2026-09-23: ONE eToro pair opens both worlds, so
    this flag does not describe the keys — it IS the switch, the `demo/`
    URL segment the adapter writes (etoro_client._seg). The /brokers/ save
    is the only page that writes it, and its demo -> live flip is guarded
    (dashboard/views_brokers.demo_untick_refusals).
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE,
                                related_name="etoro_account")
    label = models.CharField(max_length=60, default="Main")
    api_key_enc = models.TextField(blank=True)
    user_key_enc = models.TextField(blank=True)
    demo = models.BooleanField(
        default=True, help_text="Keys for eToro's demo (virtual) portfolio.")
    # Routing opt-ins, one per asset class, all OFF on arrival — the same
    # shape as IBKRAccount.is_primary_for_*. broker_router consults these
    # BEFORE IBKR's, so a flag here wins when both are set: retiring IBKR
    # is the stated direction, and the newer broker taking precedence is
    # what "retiring" means in routing terms. No options / cfd flag: those
    # two classes are forced to IBKR in the router today, and lifting that
    # is a separate, named change.
    is_primary_for_stocks = models.BooleanField(
        default=False, help_text="Route stocks, ETFs and indices here.")
    is_primary_for_forex = models.BooleanField(default=False)
    is_primary_for_commodity = models.BooleanField(default=False)
    is_primary_for_crypto = models.BooleanField(default=False)
    connected = models.BooleanField(default=False)
    last_sync = models.DateTimeField(null=True, blank=True)
    # The reading cells, in IBKRAccount's exact shape (2026-09-17): the nine
    # broker_backed() call sites read these five names and nothing that is
    # IBKR-specific, so an eToro row wearing them is a book the pages, the
    # preflight and the drawdown governor can read without change. Written
    # only by sync_etoro_accounts, from one broker call, with its age.
    last_equity = models.DecimalField(max_digits=18, decimal_places=2,
                                      null=True, blank=True)
    last_equity_currency = models.CharField(max_length=8, blank=True,
                                            default="")
    last_equity_at = models.DateTimeField(null=True, blank=True)
    broker_positions = models.JSONField(default=list, blank=True)
    broker_positions_at = models.DateTimeField(null=True, blank=True)
    # THE MARGIN CELLS (2026-09-23), from the same aggregate read as the
    # equity, written only by sync_etoro_accounts (EtoroTrader.margin_cells).
    # `last_available_cash` is what the venue will lend against next;
    # `last_used_margin` is what it already holds. None = never read (three
    # states; 0 is a measurement). Read by asset_engine/base.py
    # ::_leverage_headroom before a levered order, by preflight §3 and §4;
    # read by nothing at leverage 1, where the venue's refusal stays the
    # only margin gate. In the account's currency (last_equity_currency).
    last_available_cash = models.DecimalField(max_digits=18, decimal_places=2,
                                              null=True, blank=True)
    last_used_margin = models.DecimalField(max_digits=18, decimal_places=2,
                                           null=True, blank=True)
    last_margin_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def env_label(self) -> str:
        """What to print beside this connection, for humans.

        Every row that can be the book needs it: capital_truth.broker_view()
        reads it with NO guard, and this row has been bookable since
        2026-09-17 without it — which would have raised AttributeError on
        /portfolio/, /positions/, /setup/, /command/ and in preflight_live
        the moment an operator ticked one primary-for box.
        """
        return "DEMO" if self.demo else "LIVE"

    def is_primary_for(self, asset_class: str) -> bool:
        return bool({
            "stock": self.is_primary_for_stocks,
            "etf": self.is_primary_for_stocks,
            "index": self.is_primary_for_stocks,
            "forex": self.is_primary_for_forex,
            "commodity": self.is_primary_for_commodity,
            "crypto": self.is_primary_for_crypto,
        }.get(asset_class, False))

    def set_credentials(self, api_key: str, user_key: str):
        f = _fernet()
        self.api_key_enc = f.encrypt(api_key.encode()).decode()
        self.user_key_enc = f.encrypt(user_key.encode()).decode()

    def get_credentials(self) -> "tuple[str, str] | tuple[None, None]":
        if not self.api_key_enc:
            return (None, None)
        key = _decrypt(self.api_key_enc)
        user_key = _decrypt(self.user_key_enc)
        return (key, user_key) if key and user_key else (None, None)

    def __str__(self):
        return f"{self.user.username} · eToro ({'demo' if self.demo else 'live'})"


class SaxoAccount(models.Model):
    """Encrypted Saxo OpenAPI application + OAuth session (2026-09-17).

    Two layers, and they must not be confused:

      * The APPLICATION — `app_key` / `app_secret` / `redirect_uri` — is
        what the operator registers once on Saxo's developer portal. It
        identifies Sauron to Saxo. It never expires.
      * The SESSION — `access_token` / `refresh_token` — is what the OAuth
        authorization-code flow produces after the operator signs in once
        through a browser. The access token lives ~20 minutes; the refresh
        token renews it without a human. This is the whole reason Saxo was
        chosen over IBKR, whose retail API has no such thing.

    The session fields are blank until the operator has signed in once
    through /brokers/saxo/connect/. A blank refresh token means "registered,
    never connected" — or "lost", when session_lost_at says the keeper gave
    the session up — and the page says which, rather than reporting a
    broker that has never answered as connected.

    `sim` mirrors the other rows' environment flag. Saxo issues DIFFERENT
    app keys for SIM and LIVE; the operator registers twice.
    """
    user = models.OneToOneField(User, on_delete=models.CASCADE,
                                related_name="saxo_account")
    label = models.CharField(max_length=60, default="Main")
    app_key_enc = models.TextField(blank=True)
    app_secret_enc = models.TextField(blank=True)
    # Not a secret: it is printed in the browser's address bar during the
    # OAuth redirect. Stored plain so a mismatch can be read off the row.
    redirect_uri = models.CharField(max_length=300, blank=True)
    sim = models.BooleanField(
        default=True, help_text="Keys registered on Saxo's SIM environment.")
    # WHICH ASSET CLASSES THIS ACCOUNT HOLDS. Default OFF, every one: a
    # keyed and connected Saxo row that no operator has claimed anything
    # for is READ (its equity is a fact worth storing) and TRADED ON BY
    # NOTHING. The router consults is_primary_for(); the page shows which
    # classes are claimed; two rows claiming the same class is reported as
    # the configuration mistake it is, and Saxo wins — see
    # bot_program/engine/broker_router.py.
    is_primary_for_stocks = models.BooleanField(
        default=False,
        # The label has to say what the box DOES. Indices ride on this one
        # boolean, and Saxo prices an index as a leveraged CFD — so a box
        # promising stocks and ETFs would have moved 13 index symbols to a
        # CFD without saying so. eToro's identical flag already names
        # indices and Saxo's own commodity box already says CFD.
        help_text="Route stock, ETF and index orders to Saxo. An index "
                  "reaches Saxo as a CFD (CfdOnIndex), the way commodities "
                  "do.")
    is_primary_for_forex = models.BooleanField(default=False)
    is_primary_for_commodity = models.BooleanField(default=False)
    is_primary_for_crypto = models.BooleanField(default=False)
    access_token_enc = models.TextField(blank=True)
    refresh_token_enc = models.TextField(blank=True)
    token_expires_at = models.DateTimeField(null=True, blank=True)
    # When the REFRESH token itself dies (2 400 s after it was issued, and
    # it rotates on every refresh). The refresh task reads this to tell a
    # transient failure — retry next cycle — from a lost session, which
    # needs one browser sign-in again. Documented on Saxo's code-grant page;
    # tests/test_saxo_oauth.py pins the numbers.
    refresh_expires_at = models.DateTimeField(null=True, blank=True)
    # Set by the keeper when it gives a session up (refresh token past its
    # life, or Saxo refused the rotation); cleared by the next sign-in. The
    # page reads them so "lost — sign in again" and "never signed in" are
    # two different lines, not one. Reason is capped at 120 for Postgres.
    session_lost_at = models.DateTimeField(null=True, blank=True)
    session_lost_reason = models.CharField(max_length=120, blank=True)
    connected = models.BooleanField(default=False)
    last_sync = models.DateTimeField(null=True, blank=True)
    # THE READING CELLS, in IBKRAccount's exact shape. The sync task is
    # the only writer; every reader — capital_truth, the share allocator's
    # drawdown governor, the preflight, /brokers/, /treasury/ — reads these
    # cached columns and never the broker, because a broker round trip
    # does not belong on a render path. NULL means "never measured", which
    # is not zero: the pages render an em dash.
    last_equity = models.DecimalField(max_digits=18, decimal_places=2,
                                      null=True, blank=True)
    last_equity_currency = models.CharField(max_length=8, blank=True,
                                            default="")
    last_equity_at = models.DateTimeField(null=True, blank=True)
    broker_positions = models.JSONField(default=list, blank=True)
    broker_positions_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def env_label(self) -> str:
        """What to print beside this connection, for humans.

        IBKRAccount has had this since the beginning and
        capital_truth.broker_view() reads it with NO guard — so every row
        that can be the book must have it, or /portfolio/, /positions/,
        /setup/, /command/ and `preflight_live` raise AttributeError the
        moment that row becomes the book. Saxo's environment is the app
        key's, not a port's.
        """
        return "SIM" if self.sim else "LIVE"

    def is_primary_for(self, asset_class: str) -> bool:
        """Does this account hold `asset_class`? The router's question, and
        the one the page renders. Unknown classes are never claimed."""
        return bool({
            "stock": self.is_primary_for_stocks,
            "etf": self.is_primary_for_stocks,
            # IBKR and eToro have always mapped index onto the stocks
            # boolean; Saxo was the only one of the three that could not
            # carry an index symbol at all — at the venue whose own adapter
            # says "indices are CFDs on Saxo's retail side" and whose
            # ASSET_TYPE_FOR_CLASS maps index to CfdOnIndex. The divergence
            # that closes: broker_vision attributes a row by the CONFIG's
            # class while the router asks the INSTRUMENT's, so a Saxo row
            # flagged for stocks would have had /treasury/ print "saxo" for
            # a row holding SPX500 while the close went to IBKR.
            "index": self.is_primary_for_stocks,
            "forex": self.is_primary_for_forex,
            "commodity": self.is_primary_for_commodity,
            "crypto": self.is_primary_for_crypto,
        }.get(asset_class, False))

    def set_credentials(self, app_key: str, app_secret: str):
        f = _fernet()
        self.app_key_enc = f.encrypt(app_key.encode()).decode()
        self.app_secret_enc = f.encrypt(app_secret.encode()).decode()

    def get_credentials(self) -> "tuple[str, str] | tuple[None, None]":
        if not self.app_key_enc:
            return (None, None)
        key = _decrypt(self.app_key_enc)
        secret = _decrypt(self.app_secret_enc)
        return (key, secret) if key and secret else (None, None)

    def set_tokens(self, access_token: str, refresh_token: str, expires_at,
                   refresh_expires_at=None):
        f = _fernet()
        self.access_token_enc = f.encrypt(access_token.encode()).decode()
        self.refresh_token_enc = f.encrypt(refresh_token.encode()).decode()
        self.token_expires_at = expires_at
        self.refresh_expires_at = refresh_expires_at

    def get_access_token(self) -> "str | None":
        return _decrypt(self.access_token_enc) if self.access_token_enc else None

    def clear_session(self):
        """The session is gone — the refresh token died or Saxo refused it.
        Clearing the tokens is what makes the page say "sign in again"
        instead of showing a session that will never answer."""
        self.access_token_enc = ""
        self.refresh_token_enc = ""
        self.token_expires_at = None
        self.refresh_expires_at = None
        self.connected = False

    def get_refresh_token(self) -> "str | None":
        return _decrypt(self.refresh_token_enc) if self.refresh_token_enc else None

    @property
    def has_session(self) -> bool:
        """Registered is not connected. Only a refresh token means the OAuth
        flow completed once and the server can renew on its own."""
        return bool(self.refresh_token_enc)

    def session_alive(self, now=None) -> bool:
        """has_session AND the refresh token is not past its life. A row
        whose deadline is unknown counts as alive until the keeper's next
        attempt says otherwise — it cannot be proven dead from here."""
        if not self.has_session:
            return False
        if self.refresh_expires_at is None:
            return True
        return (now or timezone.now()) < self.refresh_expires_at

    def access_token_valid(self, now=None, margin_s: int = 60) -> bool:
        """The bearer can be presented right now with `margin_s` to spare.
        Written for the adapter: a token that dies mid-request is a 401
        nobody can explain, so the margin errs on refreshing early."""
        from datetime import timedelta
        if not self.access_token_enc or self.token_expires_at is None:
            return False
        return (now or timezone.now()) + timedelta(seconds=margin_s) < self.token_expires_at

    def mark_session_lost(self, reason: str, now=None):
        """The keeper gave the session up: clear it and say when and why."""
        self.clear_session()
        self.session_lost_at = now or timezone.now()
        self.session_lost_reason = (reason or "")[:120]

    def __str__(self):
        return f"{self.user.username} · Saxo ({'sim' if self.sim else 'live'})"


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
from .equity_models import BrokerEquityReading  # noqa: F401
from .share_models import SharePlan  # noqa: F401
from .desk_models import DeskPlan, DeskDecision  # noqa: F401
