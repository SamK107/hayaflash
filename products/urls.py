from django.urls import path
from . import views

app_name = "products"

urlpatterns = [
    path("<int:sale_pk>/products/create/", views.product_create_view, name="create"),
    path("<int:sale_pk>/products/<int:pk>/edit/", views.product_edit_view, name="edit"),
]
