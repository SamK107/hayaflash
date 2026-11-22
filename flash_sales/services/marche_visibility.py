"""Regle unique de visibilite des boutiques sur le Marche (/ventes/).

Toute requete du Marche (listing, vitrine, produits du moment, entree de
l'accueil, statistiques) passe par ``marche_shop_q`` : une boutique suspendue
(``SellerProfile.is_active`` a faux) disparait de toutes les surfaces.

``prefix`` indique le chemin vers la boutique depuis le modele interroge :
``"owner"`` pour FlashSale, ``"flash_sale__owner"`` pour FlashSaleProduct ou
Order, ``"order__flash_sale__owner"`` pour Delivery.
"""

from __future__ import annotations

from django.db.models import Q


def marche_shop_q(prefix: str = "owner") -> Q:
    return Q(**{f"{prefix}__is_active": True})
