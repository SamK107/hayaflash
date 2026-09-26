"""
API v1 URLConf (scaffolding).

Domain routes will be added per app when implemented.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.cache import cache
from django.db import connections
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.urls import include, path
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter

from core.tasks import CELERY_HEARTBEAT_CACHE_KEY
from orders.api import api_v1_orders_create
from flash_sales.api import flash_sale_list_api, flash_sale_detail_api
from products.api import FlashSaleProductViewSet

router = DefaultRouter()

logger = logging.getLogger(__name__)


def _celery_check() -> str:
    """Etat de beat + worker d'apres le battement core.celery_heartbeat.

    "skipped" sans Celery reel (tests/dev eager, ou pas de REDIS_URL : le
    cache LocMem n'est pas partage entre le worker et le web, le battement y
    serait invisible). Sinon "ok" / "stale" (battement plus vieux que
    HEALTH_CELERY_MAX_AGE) / "missing" (aucun battement depuis 600 s, ou
    jamais recu).
    """
    if getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False) or not getattr(
        settings, "REDIS_URL", ""
    ):
        return "skipped"
    raw = cache.get(CELERY_HEARTBEAT_CACHE_KEY)
    beat_at = parse_datetime(raw) if raw else None
    if beat_at is None:
        logger.error("Healthcheck: aucun battement Celery (beat ou worker arrete ?)")
        return "missing"
    age = (timezone.now() - beat_at).total_seconds()
    if age > settings.HEALTH_CELERY_MAX_AGE:
        logger.error(
            "Healthcheck: battement Celery perime (%.0f s > %s s) — beat ou worker arrete ?",
            age,
            settings.HEALTH_CELERY_MAX_AGE,
        )
        return "stale"
    return "ok"


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
    #
    # Celery (beat + worker) : informatif par defaut, voir
    # HEALTH_CELERY_REQUIRED dans config/settings/base.py pour le pourquoi.
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

    try:
        checks["celery"] = _celery_check()
    except Exception:
        logger.exception("Healthcheck: lecture du battement Celery echouee")
        checks["celery"] = "error"
    if checks["celery"] in ("stale", "missing", "error") and settings.HEALTH_CELERY_REQUIRED:
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
    # Publication rapide (catalogue produits reutilisable entre ventes) --
    # namespace distinct du router DRF generique ci-dessous : ce sont des
    # actions metier (catalog/bulk-update/...), pas du CRUD ModelViewSet.
    path(
        "flash-sales/<int:flash_sale_pk>/products/catalog/",
        FlashSaleProductViewSet.as_view({"get": "catalog"}),
        name="flashsaleproduct-catalog",
    ),
    path(
        "flash-sales/<int:flash_sale_pk>/products/bulk-update/",
        FlashSaleProductViewSet.as_view({"post": "bulk_update"}),
        name="flashsaleproduct-bulk-update",
    ),
    path(
        "flash-sales/<int:flash_sale_pk>/products/duplicate-from/",
        FlashSaleProductViewSet.as_view({"post": "duplicate_from"}),
        name="flashsaleproduct-duplicate-from",
    ),
    path(
        "flash-sales/<int:flash_sale_pk>/products/bulk-upload-images/",
        FlashSaleProductViewSet.as_view({"post": "bulk_upload_images"}),
        name="flashsaleproduct-bulk-upload-images",
    ),
    path(
        "flash-sales/<int:flash_sale_pk>/products/assign-image/",
        FlashSaleProductViewSet.as_view({"post": "assign_image"}),
        name="flashsaleproduct-assign-image",
    ),
    path(
        "flash-sales/<int:flash_sale_pk>/products/archive-product/",
        FlashSaleProductViewSet.as_view({"post": "archive_product"}),
        name="flashsaleproduct-archive-product",
    ),
    path(
        "flash-sales/<int:flash_sale_pk>/products/delete-product/",
        FlashSaleProductViewSet.as_view({"post": "delete_product"}),
        name="flashsaleproduct-delete-product",
    ),
    path("", include(router.urls)),
]
