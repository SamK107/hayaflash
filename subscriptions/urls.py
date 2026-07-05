from django.urls import path
from . import views

app_name = "subscriptions"

urlpatterns = [
    path("abonnement/", views.subscription_view, name="subscription"),
]
