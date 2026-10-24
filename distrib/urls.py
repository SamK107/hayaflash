from django.urls import path

from . import views, views_pilotage

app_name = "distrib"

urlpatterns = [
    path("", views.home, name="home"),
    path("connexion/", views.connexion, name="connexion"),
    path("revendeurs/", views.resellers, name="resellers"),
    path("revendeurs/<int:pk>/revoquer/", views.reseller_revoke, name="reseller_revoke"),
    path("invitation/<int:pk>/", views.invitation, name="invitation"),
    path("mes-grossistes/", views.my_wholesalers, name="my_wholesalers"),
    path("pilotage/", views_pilotage.pilotage_home, name="pilotage"),
    path("pilotage/grossistes/nouveau/", views_pilotage.pilotage_distributor_create, name="pilotage_distributor_create"),
]
