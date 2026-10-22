from django.urls import path

from . import views

app_name = "assist"

urlpatterns = [
    path("<int:seller_id>/", views.assist_start, name="start"),
    path("<int:seller_id>/vente/<int:sale_pk>/produits/", views.assist_products, name="products"),
    path("<int:seller_id>/vente/<int:sale_pk>/fin/", views.assist_done, name="done"),
]
