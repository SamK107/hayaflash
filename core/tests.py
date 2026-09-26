from __future__ import annotations

from unittest.mock import patch

from datetime import timedelta

from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from core.tasks import CELERY_HEARTBEAT_CACHE_KEY, celery_heartbeat


@override_settings(
    CELERY_TASK_ALWAYS_EAGER=False,
    REDIS_URL="redis://test",
    HEALTH_CELERY_MAX_AGE=180,
    HEALTH_CELERY_REQUIRED=False,
)
class CeleryHealthCheckTests(TestCase):
    """Check "celery" de /health/ : battement core.celery_heartbeat dans le cache.

    Informatif par defaut (200 meme si stale/missing) : un 503 ferait echouer
    le HEALTHCHECK Docker / smoke_test.sh avant le premier battement apres un
    deploiement -> rollback automatique d'une release saine.
    """

    def setUp(self) -> None:
        cache.delete(CELERY_HEARTBEAT_CACHE_KEY)

    def _get(self):
        resp = Client().get("/health/")
        return resp, resp.json()

    def test_heartbeat_task_writes_timestamp(self) -> None:
        celery_heartbeat()
        self.assertIsNotNone(cache.get(CELERY_HEARTBEAT_CACHE_KEY))

    def test_ok_when_recent_heartbeat(self) -> None:
        celery_heartbeat()
        resp, body = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["checks"]["celery"], "ok")
        self.assertEqual(body["status"], "ok")

    def test_stale_is_reported_but_stays_200(self) -> None:
        old = (timezone.now() - timedelta(seconds=400)).isoformat()
        cache.set(CELERY_HEARTBEAT_CACHE_KEY, old, timeout=600)
        with self.assertLogs("config.api_urls", level="ERROR"):
            resp, body = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["checks"]["celery"], "stale")
        self.assertEqual(body["status"], "ok")

    def test_missing_is_reported_but_stays_200(self) -> None:
        with self.assertLogs("config.api_urls", level="ERROR"):
            resp, body = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["checks"]["celery"], "missing")

    @override_settings(HEALTH_CELERY_REQUIRED=True)
    def test_required_turns_stale_into_503(self) -> None:
        old = (timezone.now() - timedelta(seconds=400)).isoformat()
        cache.set(CELERY_HEARTBEAT_CACHE_KEY, old, timeout=600)
        with self.assertLogs("config.api_urls", level="ERROR"):
            resp, body = self._get()
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(body["status"], "degraded")
        self.assertEqual(body["checks"]["celery"], "stale")

    @override_settings(HEALTH_CELERY_REQUIRED=True)
    def test_required_turns_missing_into_503(self) -> None:
        with self.assertLogs("config.api_urls", level="ERROR"):
            resp, _body = self._get()
        self.assertEqual(resp.status_code, 503)

    def test_cache_exception_on_heartbeat_is_isolated(self) -> None:
        real_get = cache.get

        def flaky_get(key, *args, **kwargs):
            if key == CELERY_HEARTBEAT_CACHE_KEY:
                raise ConnectionError("panne simulee")
            return real_get(key, *args, **kwargs)

        with patch("config.api_urls.cache.get", side_effect=flaky_get):
            with self.assertLogs("config.api_urls", level="ERROR"):
                resp, body = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(body["checks"]["celery"], "error")
        self.assertEqual(body["checks"]["database"], "ok")
        self.assertEqual(body["checks"]["cache"], "ok")

    @override_settings(REDIS_URL="")
    def test_skipped_without_shared_cache(self) -> None:
        _resp, body = self._get()
        self.assertEqual(body["checks"]["celery"], "skipped")


class RootHealthEndpointTests(TestCase):
    """
    Garde-fou : Dockerfile HEALTHCHECK, docker-compose.production.yml et
    infra/nginx/prod.conf ciblent tous /health/ a la racine (pas /api/v1/health/,
    ou vit la vue reelle). Sans cet alias racine (config/urls.py), le healthcheck
    infra 404 silencieusement — jamais marque "unhealthy", juste faux. Le view
    doit aussi rester accessible anonymement (AllowAny explicite dans
    config/api_urls.py) malgre DEFAULT_PERMISSION_CLASSES=IsAuthenticated.
    """

    def test_root_health_returns_200(self) -> None:
        resp = Client().get("/health/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body.get("status"), "ok")
        # Settings de test : Celery eager -> check "celery" saute.
        self.assertEqual(
            body["checks"], {"database": "ok", "cache": "ok", "celery": "skipped"}
        )

    def test_health_returns_503_when_database_down(self) -> None:
        with patch(
            "django.db.backends.utils.CursorWrapper.execute",
            side_effect=Exception("panne simulee"),
        ):
            resp = Client().get("/health/")
        self.assertEqual(resp.status_code, 503)
        body = resp.json()
        self.assertEqual(body.get("status"), "degraded")
        self.assertEqual(body["checks"]["database"], "error")

    def test_health_returns_503_when_cache_down(self) -> None:
        with patch(
            "django.core.cache.cache.set", side_effect=Exception("panne simulee")
        ):
            resp = Client().get("/health/")
        self.assertEqual(resp.status_code, 503)
        body = resp.json()
        self.assertEqual(body.get("status"), "degraded")
        self.assertEqual(body["checks"]["cache"], "error")

    def test_health_still_anonymous_and_accessible_when_degraded(self) -> None:
        with patch(
            "django.db.backends.utils.CursorWrapper.execute",
            side_effect=Exception("panne simulee"),
        ):
            resp = Client().get("/health/")
        self.assertIn(resp.status_code, (200, 503))
        self.assertNotEqual(resp.status_code, 403)
