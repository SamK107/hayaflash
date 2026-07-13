"""Production: PostgreSQL, strict hosts, no DEBUG, JSON API only."""

from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK as BASE_REST_FRAMEWORK
from .base import SECRET_KEY, SENTRY_DSN, _csv  # noqa: F401

# ── Sentry ────────────────────────────────────────────────────────────────────
if SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration
    import logging

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[
            DjangoIntegration(transaction_style="url"),
            CeleryIntegration(monitor_beat_tasks=True),
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        profiles_sample_rate=float(
            os.environ.get("SENTRY_PROFILES_SAMPLE_RATE", "0.05")
        ),
        environment="prod",
        send_default_pii=False,
    )

DEBUG = False

if not SECRET_KEY:
    raise ImproperlyConfigured(
        "SECRET_KEY must be set in the environment for production."
    )

try:
    raw_hosts = os.environ["ALLOWED_HOSTS"]
except KeyError as exc:
    raise ImproperlyConfigured(
        "ALLOWED_HOSTS must be set in the environment for production "
        "(comma-separated list)."
    ) from exc

ALLOWED_HOSTS = [h.strip() for h in raw_hosts.split(",") if h.strip()]
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "ALLOWED_HOSTS must contain at least one non-empty hostname."
    )

CORS_ALLOW_ALL_ORIGINS = False

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "true").lower() in (
    "1",
    "true",
    "yes",
)
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"

# HSTS — 1 an, sous-domaines inclus, preload
SECURE_HSTS_SECONDS = 31_536_000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

# Divers headers sécurité
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"

csrf_origins = _csv("CSRF_TRUSTED_ORIGINS")
if csrf_origins:
    CSRF_TRUSTED_ORIGINS = csrf_origins

REST_FRAMEWORK = {
    **BASE_REST_FRAMEWORK,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}
