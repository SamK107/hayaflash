from __future__ import annotations

from django.urls import path

from delivery import api

urlpatterns = [
    path("", api.api_v1_delivery_list, name="api-v1-delivery-list"),
    path(
        "<uuid:delivery_id>/advance/",
        api.api_v1_delivery_advance,
        name="api-v1-delivery-advance",
    ),
]
