from django.urls import path

from orders.views import client_order_page
from flash_sales.public_views import public_flash_sale_calendar, public_flash_sale_detail

from . import views

urlpatterns = [
    path("order/", client_order_page, name="client_order"),
    path("ventes/", public_flash_sale_calendar, name="flash_sale_calendar"),
    path("ventes/<slug:slug>/", public_flash_sale_detail, name="flash_sale_public_detail"),
    path("", views.home, name="home"),
    path("login/", views.LoginPageView.as_view(), name="login"),
    path("register/", views.RegisterPageView.as_view(), name="register"),
]
