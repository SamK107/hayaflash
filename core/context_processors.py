"""Context processors globaux pour HayaFlash."""
from __future__ import annotations


def seller_interests_count(request):
    """
    Injecte `interests_count` dans tous les templates.
    Vaut 0 si l'utilisateur n'est pas authentifié ou n'a pas de profil vendeur.
    """
    if not request.user.is_authenticated:
        return {"interests_count": 0}
    try:
        seller = request.user.seller_profile
    except Exception:
        return {"interests_count": 0}

    from flash_sales.models import SaleInterest
    count = SaleInterest.objects.filter(flash_sale__owner=seller).count()
    return {"interests_count": count}
