from __future__ import annotations

from django.urls import path

from delivery import views as delivery_views
from orders import views

app_name = "orders"

urlpatterns = [
    path("seller/dashboard/", views.seller_dashboard, name="seller_dashboard"),
    path(
        "seller/dashboard/partials/kpi/",
        views.seller_dashboard_kpi_partial,
        name="seller_dashboard_kpi",
    ),
    path(
        "seller/dashboard/partials/orders/",
        views.seller_dashboard_orders_partial,
        name="seller_dashboard_orders",
    ),
    path(
        "seller/dashboard/orders/<int:order_id>/advance-status/",
        views.seller_order_advance_status,
        name="seller_order_advance_status",
    ),
    path(
        "seller/deliveries/",
        delivery_views.seller_deliveries_dashboard,
        name="seller_deliveries_dashboard",
    ),
    path(
        "seller/deliveries/partials/summary/",
        delivery_views.seller_deliveries_summary_partial,
        name="seller_deliveries_summary",
    ),
    path(
        "seller/deliveries/partials/list/",
        delivery_views.seller_deliveries_list_partial,
        name="seller_deliveries_list",
    ),
    path(
        "seller/deliveries/<uuid:delivery_id>/action/",
        delivery_views.seller_delivery_action,
        name="seller_delivery_action",
    ),
]
