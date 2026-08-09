"""
Sauron Vision — Django Settings
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.getenv("SECRET_KEY", "insecure-dev-key-change-me")
DEBUG = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")
# Split and STRIP: "a.com, b.com" otherwise yields " b.com", which matches
# no request and answers every page on the second name with a bare 400.
ALLOWED_HOSTS = [h.strip() for h
                in os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
                if h.strip()]

# Key for broker-credential encryption at rest (bot_program.models).
# Kept SEPARATE from SECRET_KEY so rotating the latter — or moving to a new
# host, which regenerates it — cannot make every stored broker credential
# permanently undecryptable. Generate with:
#   python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
FERNET_KEY = os.getenv("FERNET_KEY", "")

# Render.com auto-provides this
RENDER_EXTERNAL_HOSTNAME = os.getenv("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

# CSRF trusted origins (needed for Render HTTPS)
CSRF_TRUSTED_ORIGINS = []
if not DEBUG:
    CSRF_TRUSTED_ORIGINS = [
        f"https://{host}" for host in ALLOWED_HOSTS if host and not host.startswith(".")
    ]
    # Also allow wildcard subdomains
    CSRF_TRUSTED_ORIGINS.append("https://*.onrender.com")

# The container healthcheck probes http://127.0.0.1:8000/healthz/ from
# inside the container, so the loopback names must be allowed or every probe
# is a 400 DisallowedHost and the service reports unhealthy forever. This
# widens nothing publicly: Caddy is the only listener exposed, and it
# forwards the real Host.
for _local in ("127.0.0.1", "localhost"):
    if _local not in ALLOWED_HOSTS:
        ALLOWED_HOSTS.append(_local)

# Security headers for production
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    # ...but not for the health probe. It speaks plain HTTP to the loopback
    # and would otherwise be answered with a 301 to https on port 8000,
    # where nothing is listening. TLS terminates at Caddy, one hop earlier.
    SECURE_REDIRECT_EXEMPT = [r"^healthz/?$"]
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

# ============================================================
# Phase 33 — Sentry error tracking (no-op when SENTRY_DSN unset)
# ============================================================
SENTRY_DSN = os.getenv("SENTRY_DSN", "").strip()
if SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.django import DjangoIntegration
        from sentry_sdk.integrations.celery import CeleryIntegration
        from sentry_sdk.integrations.redis import RedisIntegration
        sentry_sdk.init(
            dsn=SENTRY_DSN,
            integrations=[
                DjangoIntegration(),
                CeleryIntegration(),
                RedisIntegration(),
            ],
            # Sample 10% of transactions for perf monitoring; tune in prod.
            traces_sample_rate=float(os.getenv("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
            # Don't send PII — Sauron handles broker credentials.
            send_default_pii=False,
            environment=os.getenv("SENTRY_ENVIRONMENT", "production"),
            release=os.getenv("SENTRY_RELEASE") or None,
        )
    except ImportError:
        # sentry-sdk not installed — silently skip. Document in requirements.
        pass

# ============================================================
# Applications
# ============================================================
INSTALLED_APPS = [
    "daphne",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "rest_framework",
    "corsheaders",
    "django_filters",
    "django_celery_beat",
    "django_celery_results",
    "channels",
    # Sauron Vision apps
    "core",
    "instruments",
    "market_data",
    "scraping",
    "indicators",
    "signals",
    "strategies",
    "portfolio",
    "ai_agents",
    "alerts",
    "dashboard",
    "backtester",
    "bot_program",
    "brain",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "core.middleware.CorrelationIdMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.security.LoginRateLimitMiddleware",
    "core.security.SecurityHeadersMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.sauron_context",
                "core.context_ui.ui_extras"
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ============================================================
# Database — Render (DATABASE_URL), PostgreSQL, or SQLite
# ============================================================
DATABASE_URL = os.getenv("DATABASE_URL")
DB_ENGINE = os.getenv("DB_ENGINE", "auto")  # "postgresql", "sqlite", or "auto"

if DATABASE_URL:
    # Render.com and other PaaS provide DATABASE_URL
    import dj_database_url
    DATABASES = {
        "default": dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
elif DB_ENGINE == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
elif DB_ENGINE == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("DB_NAME", "sauron_vision"),
            "USER": os.getenv("DB_USER", "sauron"),
            "PASSWORD": os.getenv("DB_PASSWORD", "change-me"),
            "HOST": os.getenv("DB_HOST", "localhost"),
            "PORT": os.getenv("DB_PORT", "5432"),
        }
    }
else:
    # Auto-detect: try PostgreSQL, fall back to SQLite
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect((os.getenv("DB_HOST", "localhost"), int(os.getenv("DB_PORT", "5432"))))
        s.close()
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.postgresql",
                "NAME": os.getenv("DB_NAME", "sauron_vision"),
                "USER": os.getenv("DB_USER", "sauron"),
                "PASSWORD": os.getenv("DB_PASSWORD", "change-me"),
                "HOST": os.getenv("DB_HOST", "localhost"),
                "PORT": os.getenv("DB_PORT", "5432"),
            }
        }
    except (ConnectionRefusedError, OSError):
        DATABASES = {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": BASE_DIR / "db.sqlite3",
            }
        }
        if DEBUG:
            import sys
            print("[ Sauron Vision ] PostgreSQL not available — using SQLite for development", file=sys.stderr)

# ============================================================
# Cache / Channels — Redis if available, in-memory fallback
# ============================================================
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# In production Redis is a hard dependency, not something to degrade away from.
#
# This probe runs ONCE, at import. It exists so a developer with no Redis can
# still run the app, and that convenience is actively dangerous in production:
# if a container starts while Redis is briefly unreachable — a host reboot,
# which unattended-upgrades will cause — the process silently pins itself to a
# LocMemCache, an InMemoryChannelLayer and a filesystem:// Celery broker for
# its entire lifetime. It reports healthy. Beat then publishes into a private
# per-container queue no worker reads, WebSockets stop crossing processes, and
# retry_pending_closes — the only drain for a stranded live position — never
# runs again. Nothing is logged, because the notices below are DEBUG-only.
#
# Failing loudly instead lets Celery do what it is designed to do: report the
# connection error and retry until Redis is back.
if DEBUG:
    try:
        from urllib.parse import urlparse as _urlparse
        import socket as _sock
        _parsed = _urlparse(REDIS_URL)
        _redis_host = _parsed.hostname or "localhost"
        _redis_port = _parsed.port or 6379
        _rs = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
        _rs.settimeout(2)
        _rs.connect((_redis_host, _redis_port))
        _rs.close()
        _redis_available = True
    except (ConnectionRefusedError, OSError, ValueError):
        _redis_available = False
else:
    _redis_available = True

if _redis_available:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        }
    }
    if DEBUG:
        import sys
        print("[ Sauron Vision ] Redis not available — using in-memory cache for development", file=sys.stderr)

if _redis_available:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [REDIS_URL],
            },
        },
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        },
    }

# ============================================================
# Celery
# ============================================================
if _redis_available:
    CELERY_BROKER_URL = REDIS_URL
else:
    # Filesystem broker fallback for development without Redis
    CELERY_BROKER_URL = "filesystem://"
    CELERY_BROKER_TRANSPORT_OPTIONS = {
        "data_folder_in": str(BASE_DIR / ".celery" / "out"),
        "data_folder_out": str(BASE_DIR / ".celery" / "out"),
        "data_folder_processed": str(BASE_DIR / ".celery" / "processed"),
    }
    os.makedirs(BASE_DIR / ".celery" / "out", exist_ok=True)
    os.makedirs(BASE_DIR / ".celery" / "processed", exist_ok=True)
    if DEBUG:
        import sys
        print("[ Sauron Vision ] Redis not available — Celery using filesystem broker", file=sys.stderr)
# A worker started before Redis is reachable must wait, not exit. Celery 6
# changed this default, which is why requirements.txt pins below 6.
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_RESULT_BACKEND = "django-db"
CELERY_CACHE_BACKEND = "default"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "UTC"
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

# ============================================================
# REST Framework
# ============================================================
REST_FRAMEWORK = {
    # Authenticated-by-default. Every API view requires a logged-in session
    # unless it explicitly opts out with permission_classes = [AllowAny].
    # The dashboard is server-rendered and login-gated, so its in-page JS calls
    # carry the session cookie and authenticate via SessionAuthentication.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

# ============================================================
# CORS
# ============================================================
CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
]

# ============================================================
# Static & Media
# ============================================================
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
# ============================================================
# Email — digests, strategist briefings, newsletters
# ============================================================
# .env.production.example documented EMAIL_* for months while settings.py
# defined none of it, so Django fell back to SMTP localhost:25 and every
# production email silently failed.
EMAIL_HOST = os.getenv("EMAIL_HOST", "")
EMAIL_PORT = int(os.getenv("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.getenv("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.getenv("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.getenv("EMAIL_USE_TLS", "True").lower() in ("true", "1", "yes")
EMAIL_USE_SSL = os.getenv("EMAIL_USE_SSL", "False").lower() in ("true", "1", "yes")
EMAIL_TIMEOUT = int(os.getenv("EMAIL_TIMEOUT", "20"))
DEFAULT_FROM_EMAIL = os.getenv("DEFAULT_FROM_EMAIL", "noreply@sauronvision.com")
SERVER_EMAIL = DEFAULT_FROM_EMAIL

# With no SMTP host configured, print to the console instead of pretending
# to send: a visible no-op beats a silent failure.
if not EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
else:
    EMAIL_BACKEND = os.getenv(
        "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")


# Django 5.1 removed STATICFILES_STORAGE — the STORAGES dict is the only
# setting WhiteNoise reads now; the old name was silently ignored, so prod
# was serving uncompressed, unhashed static files.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# ============================================================
# Auth
# ============================================================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ============================================================
# i18n
# ============================================================
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ============================================================
# Sauron Vision — AI Configuration
# ============================================================
AI_CONFIG = {
    "default_provider": os.getenv("AI_DEFAULT_PROVIDER", "claude"),
    "models": {
        "fast": os.getenv("AI_MODEL_FAST", "claude-haiku-4-5-20251001"),
        # claude-sonnet-4-20250514 retired 2026-06-15 (404s); sonnet-5 is the
        # designated drop-in. opus-5 is the current Opus at the same price as 4.8.
        "balanced": os.getenv("AI_MODEL_BALANCED", "claude-sonnet-5"),
        "deep": os.getenv("AI_MODEL_DEEP", "claude-opus-5"),
    },
    "providers": {
        "claude": {
            "api_key": os.getenv("ANTHROPIC_API_KEY", ""),
        },
        "openai": {
            "api_key": os.getenv("OPENAI_API_KEY", ""),
        },
        "ollama": {
            "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
        },
    },
    "batch_api_enabled": True,
    "prompt_caching_enabled": True,
    "max_retries": 3,
    "timeout_seconds": 60,
}

# ============================================================
# Sauron Vision — Portfolio Configuration
# ============================================================
PORTFOLIO_CONFIG = {
    "base_currency": os.getenv("PORTFOLIO_BASE_CURRENCY", "EUR"),
    "initial_capital": float(os.getenv("PORTFOLIO_INITIAL_CAPITAL", "10000")),
    "max_total_exposure_pct": 100.0,
    "max_single_position_pct": 10.0,
    "max_sector_exposure_pct": 30.0,
    "max_correlation_threshold": 0.7,
    "max_daily_loss_pct": 3.0,
}

LOGIN_URL = "the_wall"
LOGIN_REDIRECT_URL = "intro"
LOGOUT_REDIRECT_URL = "the_wall"

# ============================================================
# Logging — structured JSON in production, readable in dev
# ============================================================
from core.logging_config import build_logging_config  # noqa: E402
LOGGING = build_logging_config(debug=DEBUG)
