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
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")

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

# Security headers for production
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True

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
STATICFILES_STORAGE = "whitenoise.storage.CompressedStaticFilesStorage"

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
        "balanced": os.getenv("AI_MODEL_BALANCED", "claude-sonnet-4-20250514"),
        "deep": os.getenv("AI_MODEL_DEEP", "claude-opus-4-6"),
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

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "intro"
LOGOUT_REDIRECT_URL = "login"

# ============================================================
# Logging — structured JSON in production, readable in dev
# ============================================================
from core.logging_config import build_logging_config  # noqa: E402
LOGGING = build_logging_config(debug=DEBUG)
