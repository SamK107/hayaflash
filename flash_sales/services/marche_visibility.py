"""Regle unique de visibilite des boutiques sur le Marche (/ventes/).

Toute requete du Marche (listing, vitrine, produits du moment, entree de
l'accueil, statistiques) passe par ``marche_shop_q`` : une boutique suspendue
(``SellerProfile.is_active`` a faux) disparait de toutes les surfaces.

``prefix`` indique le chemin vers la boutique depuis le modele interroge :
``"owner"`` pour FlashSale, ``"flash_sale__owner"`` pour FlashSaleProduct ou
Order, ``"order__flash_sale__owner"`` pour Delivery.
"""

from __future__ import annotations

from django.conf import settings
from django.db.models import Q

# Niveau minimal (SellerProfile.TrustLevel.BASIC) quand MARKET_REQUIRE_VERIFIED est actif.
MARKET_MIN_TRUST_LEVEL = 1


def marche_shop_q(prefix: str = "owner") -> Q:
    """Boutiques visibles sur le Marché : active, et vérifiée si le drapeau l'exige.

    Lu à chaque appel (settings.MARKET_REQUIRE_VERIFIED), donc surchargeable en test.
    """
    q = Q(**{f"{prefix}__is_active": True})
    if settings.MARKET_REQUIRE_VERIFIED:
        q &= Q(**{f"{prefix}__trust_level__gte": MARKET_MIN_TRUST_LEVEL})
    return q
