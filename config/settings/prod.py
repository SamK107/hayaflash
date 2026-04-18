"""Production-oriented settings (PostgreSQL, strict cookies, JSON API)."""
from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK as BASE_REST_FRAMEWORK
from .base import SECRET_KEY, _csv  # noqa: F401

DEBUG = False

if not SECRET_KEY:
    raise ImproperlyConfigured(
        "SECRET_KEY must be set in the environment for production."
    )

ALLOWED_HOSTS = _csv("ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "ALLOWED_HOSTS must be set (comma-separated) for production."
    )

db_name = (os.environ.get("DB_NAME") or os.environ.get("POSTGRES_DB") or "").strip()
db_user = (os.environ.get("DB_USER") or os.environ.get("POSTGRES_USER") or "").strip()
db_password = os.environ.get("DB_PASSWORD") or os.environ.get(
    "POSTGRES_PASSWORD", ""
)
db_host = (
    os.environ.get("DB_HOST")
    or os.environ.get("POSTGRES_HOST")
    or "localhost"
).strip()
db_port = (
    os.environ.get("DB_PORT") or os.environ.get("POSTGRES_PORT") or "5432"
).strip()

missing_db: list[str] = []
if not db_name:
    missing_db.append("DB_NAME (or legacy POSTGRES_DB)")
if not db_user:
    missing_db.append("DB_USER (or legacy POSTGRES_USER)")
if not db_password:
    missing_db.append("DB_PASSWORD (or legacy POSTGRES_PASSWORD)")
if missing_db:
    raise ImproperlyConfigured(
        "PostgreSQL settings are required in production: " + ", ".join(missing_db)
    )

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": db_name,
        "USER": db_user,
        "PASSWORD": db_password,
        "HOST": db_host,
        "PORT": db_port,
        "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "600")),
    }
}

CORS_ALLOW_ALL_ORIGINS = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.environ.get(
    "SECURE_SSL_REDIRECT", "true"
).lower() in ("1", "true", "yes")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

csrf_origins = _csv("CSRF_TRUSTED_ORIGINS")
if csrf_origins:
    CSRF_TRUSTED_ORIGINS = csrf_origins

REST_FRAMEWORK = {
    **BASE_REST_FRAMEWORK,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}
