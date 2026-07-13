"""Verification des limites par plan."""
from __future__ import annotations

from django.utils import timezone

from subscriptions.models import Plan, PLAN_MONTHLY_SALES_LIMIT

FREE_MONTHLY_SALES_LIMIT = PLAN_MONTHLY_SALES_LIMIT[Plan.FREE]


def get_or_create_subscription(seller):
    """Retourne (ou cree) l'abonnement du vendeur."""
    from subscriptions.models import Subscription
    sub, _ = Subscription.objects.get_or_create(
        seller=seller,
        defaults={"plan": Plan.FREE},
    )
    return sub


def get_sale_quota(seller) -> dict:
    """
    Retourne les infos de quota pour la page liste.
    """
    sub = get_or_create_subscription(seller)

    # Plan PRO illimite
    if sub.is_pro:
        return {
            "can_create": True,
            "is_pro":     True,
            "is_medium":  False,
            "is_paid":    True,
            "plan":       Plan.PRO,
            "monthly_count": 0,
            "monthly_limit": None,
            "reason": "",
        }

    # Compter les ventes du mois
    from flash_sales.models import FlashSale
    now         = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    count = FlashSale.objects.filter(
        owner=seller,
        created_at__gte=month_start,
    ).count()

    limit = PLAN_MONTHLY_SALES_LIMIT.get(sub.plan, FREE_MONTHLY_SALES_LIMIT)

    if limit is not None and count >= limit:
        return {
            "can_create": False,
            "is_pro":     False,
            "is_medium":  sub.is_medium,
            "is_paid":    sub.is_paid,
            "plan":       sub.plan,
            "monthly_count": count,
            "monthly_limit": limit,
            "reason": (
                f"Vous avez utilise {count}/{limit} ventes ce mois-ci. "
                f"Passez au plan Pro pour des ventes illimitees."
            ),
        }

    return {
        "can_create": True,
        "is_pro":     False,
        "is_medium":  sub.is_medium,
        "is_paid":    sub.is_paid,
        "plan":       sub.plan,
        "monthly_count": count,
        "monthly_limit": limit,
        "reason": "",
    }


def can_create_flash_sale(seller) -> tuple[bool, str]:
    """Retourne (True, '') ou (False, message_erreur)."""
    q = get_sale_quota(seller)
    return q["can_create"], q["reason"]
