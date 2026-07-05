"""Verification des limites par plan."""
from __future__ import annotations

from django.utils import timezone

FREE_MONTHLY_SALES_LIMIT = 3


def get_or_create_subscription(seller):
    """Retourne (ou cree) l'abonnement du vendeur."""
    from subscriptions.models import Subscription, Plan
    sub, _ = Subscription.objects.get_or_create(
        seller=seller,
        defaults={"plan": Plan.FREE},
    )
    return sub


def can_create_flash_sale(seller) -> tuple[bool, str]:
    """
    Retourne (True, "") si le vendeur peut creer une vente,
    (False, message_erreur) sinon.
    """
    sub = get_or_create_subscription(seller)
    if sub.is_pro:
        return True, ""

    from flash_sales.models import FlashSale
    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    count = FlashSale.objects.filter(
        owner=seller,
        created_at__gte=month_start,
    ).count()

    if count >= FREE_MONTHLY_SALES_LIMIT:
        return False, (
            f"Vous avez atteint la limite de {FREE_MONTHLY_SALES_LIMIT} ventes par mois "
            f"sur le plan Gratuit. Passez au plan Pro pour des ventes illimitees."
        )
    return True, ""
