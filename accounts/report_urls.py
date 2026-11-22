from django.urls import path

from accounts.report_views import shop_report_view

urlpatterns = [
    path("signaler/<slug:slug>/", shop_report_view, name="shop_report"),
]
