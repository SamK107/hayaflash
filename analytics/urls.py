from django.urls import path

from analytics import views

urlpatterns = [
    path("s/<slug:slug>/", views.seller_public_page, name="public_seller"),
    path("f/<slug:slug>/", views.flash_sale_public_page, name="public_flash_sale"),
    path(
        "f/<slug:slug>/interest/", views.flash_sale_interest, name="flash_sale_interest"
    ),
    path("track/wa/", views.track_whatsapp_share, name="track_whatsapp_share"),
]
