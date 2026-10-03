"""F-89 : toute tache doit partir dans une file ECOUTEE par le worker.

Constat (staging, 03/10) : le worker ecoute `-Q default,flash_sales,notifications`
alors que rien ne definissait task_default_queue : les taches sans file explicite
partaient dans « celery », jamais consommee (9 489 messages en attente, aucune tache
periodique executee, /health/ « celery: missing »).

Les settings de test sont autonomes (test.py ne derive pas de base.py) : on construit
donc une application Celery a partir de config.settings.base, la configuration deployee.
"""

from __future__ import annotations

import importlib
import re
from pathlib import Path

from celery import Celery
from django.conf import settings
from django.test import SimpleTestCase

base = importlib.import_module("config.settings.base")

TASK_MODULES = (
    "core.tasks",
    "flash_sales.tasks",
    "notifications.tasks",
    "subscriptions.tasks",
)
COMPOSE_FILES = ("docker-compose.production.yml", "docker-compose.yml")


def _worker_queues_from_compose(filename: str) -> set[str]:
    text = (Path(settings.BASE_DIR) / filename).read_text(encoding="utf-8")
    line = next(
        (ln for ln in text.splitlines() if "celery -A config worker" in ln and "command" in ln),
        None,
    )
    assert line is not None, f"{filename}: commande du worker introuvable"
    match = re.search(r"(?:-Q|--queues)[ =](\S+)", line)
    assert match, f"{filename}: le worker n'a pas de -Q ({line.strip()})"
    return set(match.group(1).split(","))


def _deployed_app() -> Celery:
    app = Celery("hayaflash-check")
    app.config_from_object(base, namespace="CELERY")
    return app


def _all_task_names() -> set[str]:
    names = {entry["task"] for entry in base.CELERY_BEAT_SCHEDULE.values()}
    for module_name in TASK_MODULES:
        module = importlib.import_module(module_name)
        for attr in vars(module).values():
            if hasattr(attr, "delay") and hasattr(attr, "name"):
                names.add(attr.name)
    return names


class WorkerQueuesSourceOfTruthTests(SimpleTestCase):
    def test_constant_matches_every_compose_worker_command(self) -> None:
        for filename in COMPOSE_FILES:
            self.assertEqual(
                _worker_queues_from_compose(filename),
                set(base.CELERY_WORKER_QUEUES),
                filename,
            )

    def test_default_queue_is_listened_by_the_worker(self) -> None:
        self.assertEqual(base.CELERY_TASK_DEFAULT_QUEUE, "default")
        self.assertIn(base.CELERY_TASK_DEFAULT_QUEUE, base.CELERY_WORKER_QUEUES)


class TaskRoutingTests(SimpleTestCase):
    """Routage reel de Celery (app.amqp.router), sans broker."""

    def _queue_of(self, app: Celery, task_name: str, options: dict | None = None) -> str:
        route = app.amqp.router.route(dict(options or {}), task_name)
        return route["queue"].name

    def test_there_are_tasks_to_check(self) -> None:
        names = _all_task_names()
        for expected in (
            "core.celery_heartbeat",
            "flash_sales.auto_open_scheduled_sales",
            "flash_sales.auto_close_live_sales",
            "flash_sales.send_pending_sale_reminders",
            "notifications.send_sale_reminder",
            "notifications.send_order_confirmation",
            "subscriptions.check_pending_orange_payments",
        ):
            self.assertIn(expected, names)

    def test_every_task_is_routed_to_a_queue_the_worker_listens_to(self) -> None:
        app = _deployed_app()
        listened = set(base.CELERY_WORKER_QUEUES)
        unlistened = {
            name: self._queue_of(app, name)
            for name in sorted(_all_task_names())
            if self._queue_of(app, name) not in listened
        }
        self.assertEqual(unlistened, {}, "taches routees vers une file non ecoutee")

    def test_task_without_explicit_queue_goes_to_default(self) -> None:
        app = _deployed_app()
        self.assertEqual(self._queue_of(app, "core.celery_heartbeat"), "default")
        self.assertEqual(self._queue_of(app, "notifications.send_sale_reminder"), "default")

    def test_explicit_queues_are_unchanged(self) -> None:
        app = _deployed_app()
        for queue in ("flash_sales", "notifications"):
            self.assertEqual(
                self._queue_of(app, "flash_sales.auto_open_scheduled_sales", {"queue": queue}),
                queue,
            )
