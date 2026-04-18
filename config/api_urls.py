"""
API v1 URLConf (scaffolding).

Domain routes will be added per app when implemented.
"""
from __future__ import annotations

from django.urls import include, path
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework.routers import DefaultRouter

router = DefaultRouter()


@api_view(["GET"])
def health(_request):
    return Response({"status": "ok", "service": "HayaFlash"})


urlpatterns = [
    path("health/", health, name="api-health"),
    path("accounts/", include(("accounts.urls", "accounts"), namespace="accounts")),
    path("", include(router.urls)),
]
