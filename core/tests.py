from __future__ import annotations

from unittest.mock import patch

from django.test import Client, TestCase


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
        self.assertEqual(body["checks"], {"database": "ok", "cache": "ok"})

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
