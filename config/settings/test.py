"""Settings pour CI et tests automatisés."""
from __future__ import annotations

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
    "accounts.backends.PhoneAuthBackend",
    "django.contrib.auth.backends.ModelBackend",
]

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "Africa/Bamako"
LANGUAGE_CODE = "fr-fr"

LOGGING = {"version": 1, "disable_existing_loggers": True}

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
