"""Staging: PostgreSQL, no DEBUG, strict configuration from environment."""
from __future__ import annotations

import os

from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK as BASE_REST_FRAMEWORK
from .base import ENVIRONMENT, SECRET_KEY  # noqa: F401

DEBUG = False

if ENVIRONMENT == "prod":
    raise ImproperlyConfigured(
        "ENVIRONMENT=prod must use config.settings.prod, not staging."
    )

if not SECRET_KEY:
    raise ImproperlyConfigured(
        "SECRET_KEY must be set in the environment for staging."
    )

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
