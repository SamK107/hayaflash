"""
Shared Django settings for HayaFlash.

Environment-specific values live in dev.py, staging.py, and prod.py.
Select the module with DJANGO_SETTINGS_MODULE (see .env.example).
"""

from __future__ import annotations

import os
from datetime import timedelta
from importlib.util import find_spec
from pathlib import Path

import dj_database_url
from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env", override=False)

# Canonical environment label: dev | staging | prod (legacy: ENV)
ENVIRONMENT = (
    os.environ.get("ENVIRONMENT", os.environ.get("ENV", "dev")).strip().lower()
)


def require_env(var: str) -> str:
    value = os.environ.get(var)
    if not value:
        raise ImproperlyConfigured(f"Missing required env var: {var}")
    return value


if ENVIRONMENT in ("staging", "prod"):
    SECRET_KEY = require_env("SECRET_KEY").strip()
else:
    SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "accounts": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "orders": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "flash_sales": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
        "delivery": {"handlers": ["console"], "level": "DEBUG", "propagate": False},
    },
}

# -----------------------------------------------------------------------------
# Cache (OTP, rate limits): LocMem in dev by default; Redis when REDIS_URL is set.
# Staging/production should set REDIS_URL so all workers share OTP state (required
# for multi-process / multi-node). Without Redis, LocMem is per-process only.
# -----------------------------------------------------------------------------
REDIS_URL = (os.environ.get("REDIS_URL") or "").strip()
if REDIS_URL:
    if find_spec("django_redis") is None:
        raise ImproperlyConfigured(
            "REDIS_URL is set but django-redis is not installed. "
            "Install django-redis or unset REDIS_URL to use LocMemCache."
        )
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
            },
        },
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "unique-snowflake",
        },
    }


def _csv(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _trailing_slash(url: str) -> str:
    return url if url.endswith("/") else f"{url}/"


def _env_bool(name: str, *, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _conn_max_age() -> int:
    try:
        return int(os.environ.get("DB_CONN_MAX_AGE", "60"))
    except ValueError as exc:
        raise ImproperlyConfigured("DB_CONN_MAX_AGE must be an integer.") from exc


# Default False at import time; dev settings module forces True after import.
DEBUG = _env_bool("DEBUG", default="false")


def postgresql_database(*, conn_max_age: int) -> dict[str, dict]:
    """
    Build ``DATABASES`` using DB_* variables only (no DATABASE_URL).
    Used when DATABASE_URL is unset and ENVIRONMENT is staging or prod,
    or when dev explicitly configures DB_* without DATABASE_URL (optional).
    """
    required = ("DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST")
    missing = [k for k in required if not (os.environ.get(k) or "").strip()]
    if missing:
        raise ImproperlyConfigured(
            "PostgreSQL via DB_* requires: "
            + ", ".join(missing)
            + ". Set DATABASE_URL or all DB_* variables."
        )
    return {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["DB_NAME"].strip(),
            "USER": os.environ["DB_USER"].strip(),
            "PASSWORD": os.environ["DB_PASSWORD"],
            "HOST": os.environ["DB_HOST"].strip(),
            "PORT": (os.environ.get("DB_PORT") or "5432").strip(),
            "CONN_MAX_AGE": conn_max_age,
        }
    }


def resolve_databases() -> dict[str, dict]:
    """
    Resolve ``DATABASES``: DATABASE_URL wins; dev defaults to SQLite;
    staging/prod require PostgreSQL (URL or DB_*).
    """
    conn_max = _conn_max_age()
    raw_url = (os.environ.get("DATABASE_URL") or "").strip()
    if raw_url:
        parsed = dj_database_url.parse(
            raw_url,
            conn_max_age=conn_max,
        )
        if not parsed.get("ENGINE"):
            raise ImproperlyConfigured(
                "DATABASE_URL is set but could not be parsed (missing ENGINE)."
            )
        return {"default": parsed}
    if ENVIRONMENT == "dev":
        sqlite_name = os.environ.get("DEV_SQLITE_NAME", "db_dev.sqlite3")
        return {
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": BASE_DIR / sqlite_name,
            }
        }
    return postgresql_database(conn_max_age=conn_max)


DATABASES = resolve_databases()
# Observability tag for logs / APM (ignored by built-in database backends).
DATABASES["default"]["ENV"] = ENVIRONMENT

if not DATABASES.get("default", {}).get("ENGINE"):
    raise ImproperlyConfigured("DATABASES['default'] is missing ENGINE.")

_engine = DATABASES["default"]["ENGINE"]
if ENVIRONMENT in ("staging", "prod"):
    if "postgresql" not in _engine:
        raise ImproperlyConfigured(
            "PostgreSQL is required for staging and production. "
            "Use a postgres:// DATABASE_URL or django.db.backends.postgresql via DB_*."
        )

if ENVIRONMENT == "prod" and DEBUG:
    raise ImproperlyConfigured("DEBUG must be False in production.")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sitemaps",
    "rest_framework",
    "corsheaders",
    "django_htmx",
    "axes",
    "core",
    "accounts",
    "flash_sales",
    "orders",
    "payments",
    "products",
    "subscriptions",
    "analytics",
    "sslserver",
    "notifications",
    "delivery",
    # Requis par `celery beat --scheduler django_celery_beat.schedulers:DatabaseScheduler`
    # (docker-compose.production.yml) : sans lui, beat ne demarre pas (F-20).
    "django_celery_beat",
]

PAYMENTS_WEBHOOK_SECRET = (os.environ.get("PAYMENTS_WEBHOOK_SECRET") or "").strip()
PAYMENTS_MOCK_SIMULATE_FAILURE = _env_bool(
    "PAYMENTS_MOCK_SIMULATE_FAILURE",
    default="false",
)

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "csp.middleware.CSPMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    # Dernier de la liste (recommandation django-axes) : remplace la reponse par
    # la page de verrouillage quand axes a bloque la tentative.
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.seller_interests_count",
                "core.context_processors.active_live_sale",
                "core.context_processors.pwa_install",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTHENTICATION_BACKENDS = [
    # Axes en premier : il refuse (PermissionDenied) avant toute verification
    # du mot de passe quand le couple telephone + IP est verrouille.
    "axes.backends.AxesStandaloneBackend",
    "accounts.backends.PhoneAuthBackend",
    "django.contrib.auth.backends.ModelBackend",
]

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/seller/"
LOGOUT_REDIRECT_URL = "/"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "accounts.validators.FrenchUserAttributeSimilarityValidator",
        # Le modele User n'a ni username ni email : similarite avec le numero et le nom.
        "OPTIONS": {"user_attributes": ("phone", "display_name")},
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

# Argon2 — plus robuste que PBKDF2 par défaut (DJANGO_REFERENCE)
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Bamako"
USE_I18N = True
USE_TZ = True

STATIC_URL = _trailing_slash(os.environ.get("STATIC_URL") or "static/")
STATIC_ROOT = (
    Path(os.environ["STATIC_ROOT"].strip())
    if (os.environ.get("STATIC_ROOT") or "").strip()
    else BASE_DIR / "staticfiles"
)
STATICFILES_DIRS: list[Path] = []
_static_dir = BASE_DIR / "static"
if _static_dir.is_dir():
    STATICFILES_DIRS.append(_static_dir)

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = _trailing_slash(os.environ.get("MEDIA_URL") or "media/")
MEDIA_ROOT = (
    Path(os.environ["MEDIA_ROOT"].strip())
    if (os.environ.get("MEDIA_ROOT") or "").strip()
    else BASE_DIR / "media"
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
AUTH_USER_MODEL = "accounts.User"

# Public base URL f
# ---------------------------------------------------------------------------
EMAIL_BACKEND = os.environ.get(
    "EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend"
)
if os.environ.get("DEFAULT_FROM_EMAIL"):
    DEFAULT_FROM_EMAIL = os.environ["DEFAULT_FROM_EMAIL"]

SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# ── Content-Security-Policy ──────────────────────────────────────────────────
# Policy definie dans config/settings/_csp.py (partagee avec test.py, qui ne
# charge pas base.py) : voir ce fichier pour le detail et l'historique.
from ._csp import (  # noqa: E402, F401 -- settings re-exportes
    CSP_BASE_URI,
    CSP_CONNECT_SRC,
    CSP_DEFAULT_SRC,
    CSP_FONT_SRC,
    CSP_FRAME_ANCESTORS,
    CSP_IMG_SRC,
    CSP_MANIFEST_SRC,
    CSP_MEDIA_SRC,
    CSP_OBJECT_SRC,
    CSP_REPORT_ONLY,
    CSP_REPORT_URI,
    CSP_SCRIPT_SRC,
    CSP_STYLE_SRC,
    CSP_WORKER_SRC,
)

DATABASE_ROUTERS = ["config.db_router.DefaultRouter"]

# Upload limits — photos produits max 5 Mo
DATA_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024

# ── Celery ────────────────────────────────────────────────────────────────────
CELERY_BROKER_URL = REDIS_URL or "redis://localhost:6379/0"
CELERY_RESULT_BACKEND = REDIS_URL or "redis://localhost:6379/0"
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
# Files ecoutees par le worker : source unique, verifiee contre la commande `-Q` de
# docker-compose*.yml (core/tests_celery_queues.py). F-89 : sans file par defaut
# explicite, les taches partaient dans « celery », que personne ne consommait.
CELERY_WORKER_QUEUES = ("default", "flash_sales", "notifications")
CELERY_TASK_DEFAULT_QUEUE = "default"
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 30 * 60
CELERY_BEAT_SCHEDULE = {
    "auto-open-scheduled-sales": {
        "task": "flash_sales.auto_open_scheduled_sales",
        "schedule": 60.0,
    },
    "auto-close-live-sales": {
        "task": "flash_sales.auto_close_live_sales",
        "schedule": 60.0,
    },
    "send-pending-sale-reminders": {
        "task": "flash_sales.send_pending_sale_reminders",
        "schedule": 300.0,
    },
    # Filet de securite du webhook Orange Money : verifie les paiements en
    # attente (< 24 h) via l'API transactionstatus et active ceux reussis.
    "check-pending-orange-payments": {
        "task": "subscriptions.check_pending_orange_payments",
        "schedule": 300.0,
    },
    # Sonde de /health/ (check "celery") : ecrit un timestamp dans le cache.
    "celery-heartbeat": {
        "task": "core.celery_heartbeat",
        "schedule": 60.0,
    },
}

# ── Healthcheck Celery (config/api_urls.py:health) ────────────────────────────
# Age max (s) du dernier battement core.celery_heartbeat avant "stale".
# 180 s = 3 battements manques (planifies toutes les 60 s).
HEALTH_CELERY_MAX_AGE = int(os.environ.get("HEALTH_CELERY_MAX_AGE", "180"))
# False par defaut : un Celery "stale"/"missing" est signale dans le JSON et
# loggue en ERROR (-> Sentry), mais /health/ reste 200. En 503, le HEALTHCHECK
# Docker et infra/scripts/smoke_test.sh echoueraient juste apres un deploiement,
# avant le premier battement du worker -> rollback automatique de deploy.sh sur
# une release saine. A passer a True seulement si un monitoring externe doit
# alerter sur Celery via le code HTTP.
HEALTH_CELERY_REQUIRED = _env_bool("HEALTH_CELERY_REQUIRED")

# ── IP client derriere proxy (F-26) ───────────────────────────────────────────
# Reseaux (CIDR) dont l'en-tete X-Real-IP est cru : les proxys DE CONFIANCE qui
# parlent directement a Gunicorn. Vide (defaut, dev/test) = aucun en-tete cru,
# on n'utilise que REMOTE_ADDR. Lu par core/services/client_ip.py.
TRUSTED_PROXY_NETWORKS = _csv("TRUSTED_PROXY_NETWORKS")

# ── Anti-bot : verrouillage du login (django-axes) ────────────────────────────
# Verrou sur la COMBINAISON telephone + IP, jamais le telephone seul : sinon
# n'importe qui pourrait bloquer un vendeur en pleine vente. L'IP vient de
# l'unique extraction du projet (core/services/client_ip.py), pas de ipware.
AXES_ENABLED = True
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=30)
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_USERNAME_CALLABLE = "core.services.axes_hooks.lockout_username"
AXES_CLIENT_IP_CALLABLE = "core.services.client_ip.get_client_ip"
AXES_LOCKOUT_CALLABLE = "core.services.axes_hooks.lockout_response"
AXES_LOCKOUT_MESSAGE = (
    "Trop de tentatives. Réessayez dans 30 minutes ou contactez le support "
    "WhatsApp depuis votre numéro inscrit."
)

# ── Anti-bot : limites de debit Django (core/services/rate_limit.py) ──────────
# (maximum, fenetre en secondes). Par IP sur login/inscription ; par NUMERO de
# telephone acheteur sur les commandes (CGNAT : une IP mobile malienne est
# partagee par beaucoup d'acheteurs, donc pas de limite fine par IP la-bas).
RATELIMIT_ENABLE = True
RATELIMIT_LOGIN_IP = (10, 60)
RATELIMIT_REGISTER_IP = (5, 60 * 60)
# F-15 : par numero (cle hachee), en plus de l'IP. 5 tentatives / 30 min : assez pour
# les fautes de frappe d'un vrai vendeur, bien en deca d'un martelage. Cle par numero
# et non par IP : derriere un CGNAT malien, beaucoup d'utilisateurs partagent une IP.
RATELIMIT_REGISTER_PHONE = (5, 30 * 60)
RATELIMIT_ORDER_PHONE = (10, 10 * 60)

# ── Django REST Framework ─────────────────────────────────────────────────────
# ── Django REST Framework ─────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Variantes qui identifient le client via core.services.client_ip (F-26),
    # et non via l'en-tete X-Forwarded-For brut que DRF lirait par defaut.
    "DEFAULT_THROTTLE_CLASSES": [
        "core.throttling.TrustedProxyAnonRateThrottle",
        "core.throttling.TrustedProxyUserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "anon": "30/minute",
        "user": "100/minute",
    },
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
        "rest_framework.parsers.FormParser",
    ],
}

# ── Notifications SMS ─────────────────────────────────────────────────────────
ORANGE_SMS_API_KEY = (os.environ.get("ORANGE_SMS_API_KEY") or "").strip()
ORANGE_SMS_BASE_URL = (
    os.environ.get("ORANGE_SMS_BASE_URL") or "https://api.orange.com/smsmessaging/v1"
).strip()

# ── Orange Money Paiement (abonnements) ───────────────────────────────────────
ORANGE_MONEY_CLIENT_ID = (os.environ.get("ORANGE_ML_CLIENT_ID") or "").strip()
ORANGE_MONEY_CLIENT_SECRET = (os.environ.get("ORANGE_ML_CLIENT_SECRET") or "").strip()
ORANGE_MONEY_MERCHANT_KEY = (os.environ.get("ORANGE_ML_MERCHANT_KEY") or "").strip()
# URLs de callback Orange Money — stables entre dev (ngrok) et prod (VPS).
# En dev : ORANGE_ML_BASE_URL=https://xxxx.ngrok-free.app
# En prod : les 3 URLs specifiques ci-dessous prennent le dessus.
ORANGE_MONEY_BASE_URL = (os.environ.get("ORANGE_ML_BASE_URL") or "").strip().rstrip("/")
# URLs fixes de retour/annulation/webhook (doivent etre HTTPS publiques)
# Si definies, elles remplacent les URLs calculees dynamiquement.
ORANGE_MONEY_RETURN_URL = (os.environ.get("ORANGE_ML_RETURN_URL") or "").strip()
ORANGE_MONEY_CANCEL_URL = (os.environ.get("ORANGE_ML_CANCEL_URL") or "").strip()
ORANGE_MONEY_NOTIFY_URL = (os.environ.get("ORANGE_ML_NOTIFY_URL") or "").strip()
ORANGE_MONEY_RETURN_URL = (os.environ.get("ORANGE_ML_RETURN_URL") or "").strip()
ORANGE_MONEY_CANCEL_URL = (os.environ.get("ORANGE_ML_CANCEL_URL") or "").strip()
ORANGE_MONEY_NOTIFY_URL = (os.environ.get("ORANGE_ML_NOTIFY_URL") or "").strip()

# ── Sentry DSN (production uniquement) ───────────────────────────────────────
SENTRY_DSN = (os.environ.get("SENTRY_DSN") or "").strip()

# Note: do not open DB connections here — Django is still binding settings to
# ``django.db.connections`` during import. Use ``python manage.py migrate`` or a
# deployment probe to verify connectivity after startup.
