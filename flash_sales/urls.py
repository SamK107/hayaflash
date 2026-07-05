from django.urls import path
from . import views

app_name = "flash_sales"

urlpatterns = [
    path("", views.flash_sale_list_view, name="list"),
    path("create/", views.flash_sale_create_view, name="create"),
    path("<int:pk>/", views.flash_sale_detail_view, name="detail"),
    path("<int:pk>/edit/", views.flash_sale_edit_view, name="edit"),
    path("<int:pk>/open/", views.flash_sale_open_view, name="open"),
    path("<int:pk>/close/", views.flash_sale_close_view, name="close"),
    path("<int:pk>/cancel/", views.flash_sale_cancel_view, name="cancel"),
]
