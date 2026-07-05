"""
API v1 URLConf (scaffolding).

Domain routes will be added per app when implemented.
"""
from __future__ import annotations

from django.urls import include, path
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter

from orders.api import api_v1_orders_create
from flash_sales.api import flash_sale_list_api, flash_sale_detail_api

router = DefaultRouter()


@api_view(["GET"])
def health(_request):
    return Response({"status": "ok", "service": "HayaFlash"})


urlpatterns = [
    path("health/", health, name="api-health"),
    path("accounts/", include(("accounts.urls", "accounts"), namespace="accounts")),
    path("orders/", api_v1_orders_create, name="api-v1-orders"),
    path("delivery/", include("delivery.urls")),
    path("payments/", include("payments.urls")),
    path("flash-sales/", flash_sale_list_api, name="api-flash-sales-list"),
    path("flash-sales/<slug:slug>/", flash_sale_detail_api, name="api-flash-sales-detail"),
    path("", include(router.urls)),
]
