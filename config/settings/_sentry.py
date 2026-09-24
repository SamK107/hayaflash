"""Initialisation Sentry partagee par prod.py et staging.py.

Jamais actif sans SENTRY_DSN dans l'environnement. L'etiquette `environment`
separe prod et staging dans le meme projet Sentry (filtrage + regles d'alerte
distinctes) -- voir GOVERNANCE_SECURITE.md categorie 1.
"""

from __future__ import annotations

import logging
import os


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
    )
