from django.urls import path

from payments.api import initiate_payment_view, payment_webhook_view

urlpatterns = [
    path("initiate/", initiate_payment_view, name="payments-initiate"),
    path("webhook/", payment_webhook_view, name="payments-webhook"),
]
