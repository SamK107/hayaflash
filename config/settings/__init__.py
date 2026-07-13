"""
Django settings package for HayaFlash.

Do not import ``config.settings`` directly for runtime configuration.
Set ``DJANGO_SETTINGS_MODULE`` to one of:

- ``config.settings.dev`` — local SQLite, DEBUG on
- ``config.settings.staging`` — PostgreSQL, DEBUG off
- ``config.settings.prod`` — PostgreSQL, DEBUG off, strict security

``manage.py`` defaults to ``config.settings.dev``; WSGI/ASGI default to
``config.settings.prod`` unless ``DJANGO_SETTINGS_MODULE`` is already set
(e.g. from the process environment or ``.env`` loaded in ``manage.py``).
"""

import os

ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")

SETTINGS_MAP = {
    "dev": "config.settings.dev",
    "staging": "config.settings.staging",
    "prod": "config.settings.prod",
}

os.environ.setdefault(
    "DJANGO_SETTINGS_MODULE", SETTINGS_MAP.get(ENVIRONMENT, "config.settings.dev")
)
