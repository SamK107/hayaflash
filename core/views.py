from django.shortcuts import render
from django.views.generic import TemplateView


def home(request):
    return render(request, "core/home.html")


class LoginPageView(TemplateView):
    template_name = "accounts/login.html"


class RegisterPageView(TemplateView):
    template_name = "accounts/register.html"
