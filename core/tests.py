from __future__ import annotations

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
        self.assertEqual(resp.json().get("status"), "ok")
