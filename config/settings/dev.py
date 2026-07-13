"""Local development: SQLite (or DATABASE_URL), DEBUG enabled."""

from __future__ import annotations

import os
import warnings

from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key

from .base import *  # noqa: F403
from .base import ENVIRONMENT, SECRET_KEY, _csv  # noqa: F401

if ENVIRONMENT == "prod":
    raise ImproperlyConfigured(
        "ENVIRONMENT=prod is incompatible with config.settings.dev. "
        "Use config.settings.prod and DJANGO_SETTINGS_MODULE=config.settings.prod."
    )

DEBUG = True

if not SECRET_KEY:
    SECRET_KEY = get_random_secret_key()
    warnings.warn(
        "SECRET_KEY is not set (e.g. missing .env). Using an ephemeral key for "
        "this process only. Copy .env.example to .env and set SECRET_KEY for "
        "stable sessions and the same behavior as teammates.",
        UserWarning,
        stacklevel=1,
    )

ALLOWED_HOSTS = _csv("ALLOWED_HOSTS", "localhost,127.0.0.1,10.248.111.89")

CORS_ALLOW_ALL_ORIGINS = True
if not os.environ.get("EMAIL_BACKEND"):
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Debug Toolbar (desactive — decommenter pour reactiver)
# INSTALLED_APPS = INSTALLED_APPS + ["debug_toolbar"]  # noqa: F405
# MIDDLEWARE = [  # noqa: F405
#     "debug_toolbar.middleware.DebugToolbarMiddleware",
#     *MIDDLEWARE,  # noqa: F405
# ]
# INTERNAL_IPS = ["127.0.0.1", "::1"]

# Celery synchrone en dev si pas de Redis
