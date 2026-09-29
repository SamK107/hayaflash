"""Settings de test sur PostgreSQL (tests de concurrence, parite avec la prod)."""
import os

from .test import *  # noqa: F401,F403

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("TEST_PG_NAME", "hayaflash_test"),
        "USER": os.environ.get("TEST_PG_USER", "postgres"),
        "PASSWORD": os.environ.get("TEST_PG_PASSWORD", "test"),
        "HOST": os.environ.get("TEST_PG_HOST", "127.0.0.1"),
        "PORT": os.environ.get("TEST_PG_PORT", "55432"),
    }
}
