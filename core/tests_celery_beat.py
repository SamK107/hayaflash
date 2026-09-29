"""F-20 : beat est lance avec DatabaseScheduler (docker-compose.production.yml)
-> django_celery_beat doit etre installee, et le planning doit contenir
l'auto-close des ventes (RM-10 : toutes les 60 s).

Les settings de test sont autonomes (test.py ne dérive pas de base.py) : on lit
donc explicitement config.settings.base, la configuration réellement déployée.
"""

from __future__ import annotations

import importlib

from django.apps import apps
from django.conf import settings
from django.test import SimpleTestCase, TransactionTestCase

base = importlib.import_module("config.settings.base")


class CeleryBeatConfigTests(SimpleTestCase):
    def test_django_celery_beat_is_installed_in_prod_settings(self):
        self.assertIn("django_celery_beat", base.INSTALLED_APPS)

    def test_django_celery_beat_is_installed_in_test_settings(self):
        self.assertIn("django_celery_beat", settings.INSTALLED_APPS)
        self.assertTrue(apps.is_installed("django_celery_beat"))

    def test_auto_close_is_scheduled_every_60_seconds(self):
        entries = [
            e
            for e in base.CELERY_BEAT_SCHEDULE.values()
            if e["task"] == "flash_sales.auto_close_live_sales"
        ]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["schedule"], 60.0)

    def test_every_scheduled_task_is_defined(self):
        # Import direct des modules de taches (et non app.tasks / import_default_modules,
        # qui reconfigurent le logging global de Celery et perturbent d'autres tests).
        names = set()
        for module_name in (
            "flash_sales.tasks",
            "subscriptions.tasks",
            "core.tasks",
        ):
            module = importlib.import_module(module_name)
            for attr in vars(module).values():
                if hasattr(attr, "delay") and hasattr(attr, "name"):
                    names.add(attr.name)
        for name, entry in base.CELERY_BEAT_SCHEDULE.items():
            self.assertIn(entry["task"], names, f"tache inconnue pour {name}")


class DatabaseSchedulerTests(TransactionTestCase):
    def test_database_scheduler_loads_auto_close(self):
        from config.celery import app
        from django_celery_beat.schedulers import DatabaseScheduler

        app.conf.beat_schedule = base.CELERY_BEAT_SCHEDULE
        scheduler = DatabaseScheduler(app=app)
        self.assertIn("auto-close-live-sales", scheduler.schedule)
        entry = scheduler.schedule["auto-close-live-sales"]
        self.assertEqual(entry.task, "flash_sales.auto_close_live_sales")
        self.assertEqual(entry.schedule.run_every.total_seconds(), 60)
