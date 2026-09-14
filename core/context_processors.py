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


def active_live_sale(request):
    """
    Injecte `active_sale` (la premiere vente LIVE du vendeur, ou None) dans
    tous les templates — utilise par le badge "LIVE" de partials/_nav_seller.html.

    Trouve mort lors de l'audit des routes : le badge referencait `active_sale`
    (jamais defini nulle part, seul `active_sales` — pluriel — existait dans le
    contexte de seller_home_view) et un lien vers `flash_sales:live` (URL
    inexistante) — le bloc {% if %} etant toujours faux, ca ne crashait jamais,
    mais le badge n'est jamais apparu.
    """
    if not request.user.is_authenticated:
        return {"active_sale": None}
    try:
        seller = request.user.seller_profile
    except Exception:
        return {"active_sale": None}

    from flash_sales.models import FlashSale, FlashSaleStatus

    sale = (
        FlashSale.objects.filter(owner=seller, status=FlashSaleStatus.LIVE)
        .order_by("start_time")
        .first()
    )
    return {"active_sale": sale}
