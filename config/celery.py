"""Celery application for HayaFlash.

Usage:
    celery -A config worker -l info
    celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler
"""

from __future__ import annotations

import os

from celery import Celery

# Utiliser les settings Django pour Celery
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("hayaflash")

# Lire la config depuis Django settings (clés préfixées CELERY_)
app.config_from_object("django.conf:settings", namespace="CELERY")

# Auto-découverte des tâches dans chaque app Django
app.autodiscover_tasks()


@app.task(bind=True, ignore_result=True)
def debug_task(self):
    print(f"Request: {self.request!r}")  # noqa: T201
