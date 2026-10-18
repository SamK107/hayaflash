"""Initialisation Sentry partagee par prod.py et staging.py.

Jamais actif sans SENTRY_DSN dans l'environnement. L'etiquette `environment`
separe prod et staging dans le meme projet Sentry (filtrage + regles d'alerte
distinctes) -- voir GOVERNANCE_SECURITE.md categorie 1.
"""

from __future__ import annotations

import logging
import os
import re

REDACTED_PHONE = "[telephone]"
REDACTED_EMAIL = "[email]"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# International : +223 70 12 34 56, 00223 70123456, +33 6 12 34 56 78...
_INTL_PHONE_RE = re.compile(r"(?<![\w])(?:\+|00)\d[\d ().\-]{6,17}\d")
# National malien a 8 chiffres, avec ou sans separateurs (espace ou point).
_NATIONAL_PHONE_RE = re.compile(r"(?<![\w.+])\d{2}(?:[ .]?\d{2}){3}(?![\w])")

# Cles techniques dont la valeur ressemble a un numero (dates, identifiants).
_SKIP_KEYS = frozenset(
    {"timestamp", "start_timestamp", "event_id", "trace_id", "span_id", "release",
     "sdk", "platform", "level", "type", "category", "lineno", "abs_path",
     "filename", "module", "function"}
)


def scrub_text(value: str) -> str:
    """Masque e-mails et numeros de telephone dans une chaine."""
    value = _EMAIL_RE.sub(REDACTED_EMAIL, value)
    value = _INTL_PHONE_RE.sub(REDACTED_PHONE, value)
    return _NATIONAL_PHONE_RE.sub(REDACTED_PHONE, value)


def _scrub(obj):
    if isinstance(obj, str):
        return scrub_text(obj)
    if isinstance(obj, dict):
        return {
            k: (v if k in _SKIP_KEYS else _scrub(v)) for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return type(obj)(_scrub(v) for v in obj)
    return obj


def before_send(event, hint):
    """Masque les donnees personnelles de l'evenement (message, exception, requete...)."""
    return _scrub(event)


def before_breadcrumb(crumb, hint):
    return _scrub(crumb)


def init_sentry(dsn: str, environment: str) -> None:
    if not dsn:
        return

    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=dsn,
        integrations=[
            DjangoIntegration(transaction_style="url"),
            CeleryIntegration(monitor_beat_tasks=True),
            # event_level=ERROR : c'est ce qui transforme les logger.error() des
            # webhooks paiement en alertes (categorie 8).
            LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
        ],
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        profiles_sample_rate=float(
            os.environ.get("SENTRY_PROFILES_SAMPLE_RATE", "0.05")
        ),
        environment=environment,
        release=os.environ.get("APP_RELEASE") or None,
        send_default_pii=False,
        include_local_variables=False,
        before_send=before_send,
        before_breadcrumb=before_breadcrumb,
    )
