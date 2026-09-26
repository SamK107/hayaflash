"""Taches Celery transverses (hors domaine metier)."""

from __future__ import annotations

from celery import shared_task
from django.core.cache import cache
from django.utils import timezone

# Cle lue par config/api_urls.py:health (check "celery").
CELERY_HEARTBEAT_CACHE_KEY = "celery:heartbeat"
CELERY_HEARTBEAT_TIMEOUT = 600


@shared_task(name="core.celery_heartbeat", ignore_result=True)
def celery_heartbeat() -> str:
    """Battement planifie par beat (CELERY_BEAT_SCHEDULE, 60 s), execute par le worker.

    Une valeur recente dans le cache prouve que beat planifie ET qu'un worker
    consomme la file : si l'un des deux est arrete, le timestamp vieillit et
    /health/ passe le check "celery" en "stale" (puis "missing" apres 600 s).
    """
    now = timezone.now().isoformat()
    cache.set(CELERY_HEARTBEAT_CACHE_KEY, now, timeout=CELERY_HEARTBEAT_TIMEOUT)
    return now
