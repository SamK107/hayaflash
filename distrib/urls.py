from django.urls import path

from . import views, views_catalog, views_pilotage

app_name = "distrib"

urlpatterns = [
    path("", views.home, name="home"),
    path("connexion/", views.connexion, name="connexion"),
    path("revendeurs/", views.resellers, name="resellers"),
    path("revendeurs/<int:pk>/revoquer/", views.reseller_revoke, name="reseller_revoke"),
    path("invitation/<int:pk>/", views.invitation, name="invitation"),
    path("mes-grossistes/", views.my_wholesalers, name="my_wholesalers"),
    path("catalogue/", views_catalog.catalog_list, name="catalog"),
    path("catalogue/nouveau/", views_catalog.catalog_create, name="catalog_create"),
    path("catalogue/<int:pk>/", views_catalog.catalog_edit, name="catalog_edit"),
    path("catalogue/<int:pk>/photos/", views_catalog.catalog_image_add, name="catalog_image_add"),
    path("catalogue/<int:pk>/photos/<int:image_pk>/retirer/", views_catalog.catalog_image_delete, name="catalog_image_delete"),
    path("pilotage/", views_pilotage.pilotage_home, name="pilotage"),
    path("pilotage/grossistes/nouveau/", views_pilotage.pilotage_distributor_create, name="pilotage_distributor_create"),
]
