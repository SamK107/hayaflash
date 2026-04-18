"""
Shared Django settings for HayaFlash (no environment-specific toggles here).
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv



BASE_DIR = Path(__file__).resolve().parent.parent.parent
load_dotenv(BASE_DIR / ".env", override=False)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
}

def _csv(name: str, default: str = "") -> list[str]:
    raw = os.environ.get(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def _trailing_slash(url: str) -> str:
    return url if url.endswith("/") else f"{url}/"


ENV = os.environ.get("ENV", "dev").strip().lower()

SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "django_htmx",
    "core",
    "accounts",
    "flash_sales",
    "orders",
    "products",
    "subscriptions",
    "analytics",
    "notifications",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
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
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
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

REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.AllowAny",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
}

CORS_ALLOWED_ORIGINS = _csv("CORS_ALLOWED_ORIGINS")

if os.environ.get("EMAIL_BACKEND"):
    EMAIL_BACKEND = os.environ["EMAIL_BACKEND"]
if os.environ.get("DEFAULT_FROM_EMAIL"):
    DEFAULT_FROM_EMAIL = os.environ["DEFAULT_FROM_EMAIL"]


SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
