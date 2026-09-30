"""Aides de test partagees (formulaires proteges par core/services/honeypot.py)."""

from __future__ import annotations

import time

from core.services import honeypot


def honeypot_ok(age_seconds: float = 60) -> dict[str, str]:
    """Champs d'un formulaire rempli par un humain (jeton affiche il y a ``age_seconds``)."""
    return {honeypot.TIMESTAMP_FIELD: honeypot.make_token(time.time() - age_seconds)}
