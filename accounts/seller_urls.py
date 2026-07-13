"""
Routes HTML vendeur — profil et paramètres.
Montées sous /seller/ dans config/urls.py.
Import lazy : aucun import de modèle/vue au niveau module.
"""

from django.urls import path


def _profile_view(request, *args, **kwargs):
    from accounts.views import seller_profile_edit

    return seller_profile_edit(request, *args, **kwargs)


def _settings_view(request, *args, **kwargs):
    from accounts.views import seller_settings

    return seller_settings(request, *args, **kwargs)


urlpatterns = [
    path("profil/", _profile_view, name="seller_profile"),
    path("parametres/", _settings_view, name="seller_settings"),
]
