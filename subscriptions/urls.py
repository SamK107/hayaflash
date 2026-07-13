from django.urls import path
from . import views

app_name = "subscriptions"

urlpatterns = [
    path("abonnement/",                          views.subscription_view,     name="subscription"),
    path("abonnement/checkout/<str:plan>/",      views.checkout_view,         name="checkout"),
    path("abonnement/retour/<uuid:payment_id>/", views.payment_return_view,   name="payment_return"),
    path("abonnement/annule/<uuid:payment_id>/", views.payment_cancel_view,   name="payment_cancel"),
    path("abonnement/callback/",                 views.payment_callback_view, name="payment_callback"),
    path("abonnement/debug-om/",                 views.om_debug_view,         name="om_debug"),
]
