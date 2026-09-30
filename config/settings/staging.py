"""Staging: PostgreSQL, no DEBUG, strict configuration from environment."""

from __future__ import annotations


from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK as BASE_REST_FRAMEWORK
from ._sentry import init_sentry
from .base import ENVIRONMENT, REDIS_URL, SECRET_KEY, SENTRY_DSN, _csv  # noqa: F401

# Proxy de confiance pour l'IP client (F-26) : meme chaine qu'en prod (Nginx hote
# -> Nginx du conteneur -> Gunicorn), voir prod.py.
TRUSTED_PROXY_NETWORKS = _csv(
    "TRUSTED_PROXY_NETWORKS", "172.16.0.0/12,10.0.0.0/8,192.168.0.0/16"
)

# ── Sentry ────────────────────────────────────────────────────────────────────
# Opt-in : actif seulement si SENTRY_DSN est defini dans le .env de staging.
# Meme projet Sentry que la prod possible, separe par environment="staging".
init_sentry(SENTRY_DSN, environment="staging")

DEBUG = False

# Sans Redis, les caches seraient LocMem PAR PROCESSUS (3 workers Gunicorn) :
# verrous axes, limites de debit et honeypot perdraient leur efficacite sans
# aucune erreur visible. On refuse donc de demarrer (F anti-bot, decision 8).
if not REDIS_URL:
    raise ImproperlyConfigured(
        "REDIS_URL must be set in the environment for staging (shared cache: "
        "axes lockouts and rate limits need it across Gunicorn workers)."
    )

if ENVIRONMENT == "prod":
    raise ImproperlyConfigured(
        "ENVIRONMENT=prod must use config.settings.prod, not staging."
    )

if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY must be set in the environment for staging.")

ALLOWED_HOSTS = _csv("ALLOWED_HOSTS")
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "ALLOWED_HOSTS must be set (comma-separated) for staging."
    )

CORS_ALLOW_ALL_ORIGINS = False

csrf_origins = _csv("CSRF_TRUSTED_ORIGINS")
if csrf_origins:
    CSRF_TRUSTED_ORIGINS = csrf_origins

REST_FRAMEWORK = {
    **BASE_REST_FRAMEWORK,
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
}
