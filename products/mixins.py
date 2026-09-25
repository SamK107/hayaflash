"""Verification d'appartenance vendeur, centralisee pour les vues/API
"Publication rapide" (evite de repeter `get_object_or_404(..., owner=seller)`
dans chaque vue comme le fait le code historique).

Supporte aussi le mode admin/support (staff Django agissant pour le compte
d'un vendeur via `?seller_id=<id>`), utilise par la page
admin_quick_publish_view / templates/products/quick_publish.html en mode
"is_admin"."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404


class SellerOwnershipMixin:
    """A utiliser dans une APIView/ViewSet DRF (self.request disponible)."""

    def get_seller_profile(self):
        user = self.request.user
        if hasattr(user, "seller_profile"):
            return user.seller_profile

        if user.is_staff:
            seller_id = self.request.query_params.get("seller_id")
            if seller_id:
                from accounts.models import SellerProfile

                return get_object_or_404(SellerProfile, pk=seller_id)

        raise PermissionDenied(
            "Ce compte n'est pas un compte vendeur (ou seller_id manquant pour un accès admin)."
        )

    def get_owned_flash_sale(self, flash_sale_pk):
        from flash_sales.models import FlashSale

        seller = self.get_seller_profile()
        return get_object_or_404(FlashSale, pk=flash_sale_pk, owner=seller)

    def check_product_ownership(self, product):
        if product.owner_id != self.get_seller_profile().pk:
            raise PermissionDenied("Ce produit n'appartient pas a ce vendeur.")
        return product
