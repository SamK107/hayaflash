"""Garde-fous sur config/settings/prod.py (importe avec un environnement factice)."""

from __future__ import annotations

import importlib
import os
import sys

import pytest

PROD_ENV = {
    "ENVIRONMENT": "prod",
    "SECRET_KEY": "test-only-prod-secret-key",
    "ALLOWED_HOSTS": "hayaflash.example",
    # Seulement parsee (dj_database_url), aucune connexion n'est ouverte.
    "DATABASE_URL": "postgres://user:pass@localhost:5432/hayaflash",
    "DEBUG": "false",
    # Definies (meme vides) pour que load_dotenv(override=False) de base.py
    # n'y injecte pas les valeurs d'un .env local.
    # Obligatoire en prod (garde dans prod.py) ; seulement parsee, aucune connexion.
    "REDIS_URL": "redis://localhost:6379/1",
    "SENTRY_DSN": "",
}


@pytest.fixture
def prod_settings(monkeypatch):
    """Importe config.settings.prod puis restaure os.environ et sys.modules."""
    saved_environ = dict(os.environ)
    saved_modules = {
        name: mod for name, mod in sys.modules.items() if name.startswith("config.settings.")
    }
    for key, value in PROD_ENV.items():
        monkeypatch.setenv(key, value)
    for name in ("config.settings.prod", "config.settings.base"):
        sys.modules.pop(name, None)
    try:
        yield importlib.import_module("config.settings.prod")
    finally:
        for name in [n for n in sys.modules if n.startswith("config.settings.")]:
            if name not in saved_modules:
                del sys.modules[name]
        sys.modules.update(saved_modules)
        os.environ.clear()
        os.environ.update(saved_environ)


def test_prod_csrf_cookie_is_readable_by_js(prod_settings):
    # static/js/hf-base.js, hf-seller.js et hf-public.js lisent csrftoken dans
    # document.cookie pour l'en-tete X-CSRFToken (HTMX + fetch) : un cookie
    # HttpOnly ferait echouer toutes ces requetes en 403 en production.
    assert prod_settings.ENVIRONMENT == "prod"
    assert prod_settings.CSRF_COOKIE_HTTPONLY is False
    assert prod_settings.CSRF_COOKIE_SECURE is True


@pytest.mark.parametrize("module", ["prod", "staging"])
def test_prod_and_staging_refuse_to_start_without_redis(monkeypatch, module):
    """Sans REDIS_URL : caches LocMem par worker -> axes / rate limit inefficaces en silence."""
    from django.core.exceptions import ImproperlyConfigured

    saved_environ = dict(os.environ)
    saved_modules = {
        name: mod for name, mod in sys.modules.items() if name.startswith("config.settings.")
    }
    env = {**PROD_ENV, "REDIS_URL": ""}
    if module == "staging":
        env["ENVIRONMENT"] = "staging"
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for name in (f"config.settings.{module}", "config.settings.base"):
        sys.modules.pop(name, None)
    try:
        with pytest.raises(ImproperlyConfigured, match="REDIS_URL"):
            importlib.import_module(f"config.settings.{module}")
    finally:
        for name in [n for n in sys.modules if n.startswith("config.settings.")]:
            if name not in saved_modules:
                del sys.modules[name]
        sys.modules.update(saved_modules)
        os.environ.clear()
        os.environ.update(saved_environ)
