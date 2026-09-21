from django.urls import path
from . import views

app_name = "products"

urlpatterns = [
    path("<int:sale_pk>/products/create/", views.product_create_view, name="create"),
    path("<int:sale_pk>/products/<int:pk>/edit/", views.product_edit_view, name="edit"),
    path(
        "<int:flash_sale_pk>/quick-publish/",
        views.quick_publish_view,
        name="quick_publish",
    ),
    path(
        "admin/sellers/<int:seller_id>/<int:flash_sale_pk>/quick-publish/",
        views.admin_quick_publish_view,
        name="admin_quick_publish",
    ),
]
