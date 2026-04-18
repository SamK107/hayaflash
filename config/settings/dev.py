"""Local development settings (SQLite by default)."""
from __future__ import annotations

import os
import warnings

from django.core.management.utils import get_random_secret_key

from .base import *  # noqa: F403
from .base import BASE_DIR, SECRET_KEY, _csv  # noqa: F401

DEBUG = os.environ.get("DEBUG", "true").lower() in ("1", "true", "yes")

if not SECRET_KEY:
    SECRET_KEY = get_random_secret_key()
    warnings.warn(
        "SECRET_KEY is not set (e.g. missing .env). Using an ephemeral key for "
        "this process only. Copy .env.example to .env and set SECRET_KEY for "
        "stable sessions and the same behavior as teammates.",
        UserWarning,
        stacklevel=1,
    )

ALLOWED_HOSTS = _csv("ALLOWED_HOSTS", "localhost,127.0.0.1")

# Use a dedicated dev DB file so an older `db.sqlite3` (migrated before
# AUTH_USER_MODEL) does not block `migrate` with InconsistentMigrationHistory.
# Remove `db.sqlite3` manually when you no longer need that legacy file.
_sqlite_name = os.environ.get("DEV_SQLITE_NAME", "local.sqlite3")
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / _sqlite_name,
    }
}

CORS_ALLOW_ALL_ORIGINS = True
if not os.environ.get("EMAIL_BACKEND"):
    EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

STORAGES = {
    **STORAGES,
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}
