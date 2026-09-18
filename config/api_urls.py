"""
API v1 URLConf (scaffolding).

Domain routes will be added per app when implemented.
"""

from __future__ import annotations

import logging

from django.core.cache import cache
from django.db import connections
from django.urls import include, path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter

from orders.api import api_v1_orders_create
from flash_sales.api import flash_sale_list_api, flash_sale_detail_api

router = DefaultRouter()

logger = logging.getLogger(__name__)


@api_view(["GET"])
@permission_classes([AllowAny])
def health(_request):
    # Un healthcheck doit rester accessible anonymement : Docker HEALTHCHECK,
    # Nginx (proxy interne) et infra/scripts/deploy.sh/smoke_test.sh l'appellent
    # sans authentification. Sans cet override, DEFAULT_PERMISSION_CLASSES =
    # IsAuthenticated (config/settings/base.py) le fait 403 systematiquement —
    # aucun de ces appelants n'a de session/token.
    #
    # Verifie DB + cache (Redis en staging/prod) plutot qu'un 200 statique :
    # un "vert" qui ne prouve rien masque une DB ou un Redis down (voir
    # GOVERNANCE_SECURITE.md categorie 2). Chaque check est isole dans son
    # propre try/except — une exception de driver (psycopg2, redis) ne doit
    # jamais faire planter le healthcheck lui-meme en 500.
    checks = {}
    healthy = True

    try:
        with connections["default"].cursor() as cursor:
            cursor.execute("SELECT 1")
        checks["database"] = "ok"
    except Exception:
        logger.exception("Healthcheck: connexion base de donnees echouee")
        checks["database"] = "error"
        healthy = False

    try:
        marker = "healthcheck-ping"
        cache.set(marker, "1", timeout=5)
        if cache.get(marker) != "1":
            raise ConnectionError("cache round-trip mismatch")
        checks["cache"] = "ok"
    except Exception:
        logger.exception("Healthcheck: connexion cache echouee")
        checks["cache"] = "error"
        healthy = False

    status_code = 200 if healthy else 503
    return Response(
        {
            "status": "ok" if healthy else "degraded",
            "service": "HayaFlash",
            "checks": checks,
        },
        status=status_code,
    )


urlpatterns = [
    path("health/", health, name="api-health"),
    path("accounts/", include(("accounts.urls", "accounts"), namespace="accounts")),
    path("orders/", api_v1_orders_create, name="api-v1-orders"),
    path("delivery/", include("delivery.urls")),
    path("payments/", include("payments.urls")),
    path("flash-sales/", flash_sale_list_api, name="api-flash-sales-list"),
    path(
        "flash-sales/<slug:slug>/", flash_sale_detail_api, name="api-flash-sales-detail"
    ),
    path("", include(router.urls)),
]
