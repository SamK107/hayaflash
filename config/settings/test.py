"""Settings pour CI et tests automatisés."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

# Base minimale sans charger .env
BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = "django-insecure-test-key-not-for-production"
DEBUG = False
ALLOWED_HOSTS = ["*"]
ENVIRONMENT = "test"

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
THIRD_PARTY_APPS = [
    "rest_framework",
    "corsheaders",
    "django_htmx",
    "axes",  # desactive globalement ci-dessous (AXES_ENABLED), actif dans core/tests_axes.py
    "django_celery_beat",  # F-20 : parite avec base.py (DatabaseScheduler)
]
LOCAL_APPS = [
    "core",
    "accounts",
    "flash_sales",
    "orders",
    "payments",
    "products",
    "subscriptions",
    "analytics",
    "notifications",
    "delivery",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "axes.middleware.AxesMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

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
                # Manquaient tous les deux ici (settings/test.py ne herite pas
                # de base.py, cf. commentaire en tete de fichier) — decouvert
                # en testant le fix du badge LIVE : interests_count et
                # active_sale n'etaient donc jamais reellement exerces par
                # la suite de tests malgre leur presence en prod/dev.
                "core.context_processors.seller_interests_count",
                "core.context_processors.active_live_sale",
                "core.context_processors.pwa_install",
            ],
        },
    },
]

# DB en mémoire — rapide, isolée
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Pas de Redis en CI
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "test-cache",
    }
}

# Celery synchrone en tests (pas de worker nécessaire)
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
CELERY_RESULT_BACKEND = "cache+memory://"

# Emails capturés en mémoire
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

# F-17 : parite avec base.py (validateurs appliques aux NOUVELLES saisies :
# inscription et changement de mot de passe, jamais a la connexion).
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "accounts.validators.FrenchUserAttributeSimilarityValidator",
        "OPTIONS": {"user_attributes": ("phone", "display_name")},
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 8},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# Password hasher rapide pour les tests
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

# Fichiers en mémoire
DEFAULT_FILE_STORAGE = "django.core.files.storage.InMemoryStorage"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media_test"

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = []

AUTH_USER_MODEL = "accounts.User"
AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "accounts.backends.PhoneAuthBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Anti-bot : memes reglages que base.py, mais coupes par defaut (les tests qui
# enchainent des echecs de connexion ne doivent pas se verrouiller entre eux).
AXES_ENABLED = False
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
# Coupe en test (les tests dedies l'activent via override_settings).
RATELIMIT_ENABLE = False
RATELIMIT_LOGIN_IP = (10, 60)
RATELIMIT_REGISTER_IP = (5, 60 * 60)
RATELIMIT_ORDER_PHONE = (10, 10 * 60)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "Africa/Bamako"
LANGUAGE_CODE = "fr-fr"

LOGGING = {"version": 1, "disable_existing_loggers": True}

# Meme policy CSP que base.py (le middleware n'est pas dans MIDDLEWARE ici :
# core/tests_csp.py l'ajoute avec modify_settings).
from ._csp import *  # noqa: E402,F401,F403

# Healthcheck Celery (valeurs de base.py ; check "skipped" en eager)
HEALTH_CELERY_MAX_AGE = 180
HEALTH_CELERY_REQUIRED = False

# HayaFlash
HAYAFLASH_PUBLIC_BASE_URL = "http://testserver"
VIRAL_STATS_CACHE_SECONDS = 0
VIRAL_PAGE_VERSION_TTL_SECONDS = 0
PAYMENTS_WEBHOOK_SECRET = "test-webhook-secret"
PAYMENTS_MOCK_SIMULATE_FAILURE = False
ORANGE_SMS_API_KEY = ""
ORANGE_SMS_BASE_URL = ""
SENTRY_DSN = ""

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    # Throttle désactivé en tests
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}

CORS_ALLOWED_ORIGINS = []
X_FRAME_OPTIONS = "DENY"
DATABASE_ROUTERS = ["config.db_router.DefaultRouter"]
