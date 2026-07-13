from django.urls import path
from . import views

urlpatterns = [
    path("", views.seller_home_view, name="seller_home"),
]
