from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.LoginPageView.as_view(), name="login"),
    path("register/", views.RegisterPageView.as_view(), name="register"),
]
