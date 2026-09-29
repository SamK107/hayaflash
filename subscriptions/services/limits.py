"""Verification des limites par plan (quota mensuel de ventes).

Limites lues dans subscriptions/services/plans.py (PlanConfig en base, valeurs
de secours si la base est indisponible). L'appelant
flash_sales.services.crud.can_seller_create_sale reste fail-closed : toute
exception ici bloque la creation.
"""

from __future__ import annotations

from django.utils import timezone

from subscriptions.models import Plan
from subscriptions.services.plans import get_monthly_limit, quota_label


def get_or_create_subscription(seller):
    """Retourne (ou cree) l'abonnement du vendeur."""
    from subscriptions.models import Subscription

    sub, _ = Subscription.objects.get_or_create(
        seller=seller,
        defaults={"plan": Plan.FREE},
    )
    return sub


def count_sales_this_month(seller, exclude_pk: int | None = None) -> int:
    """Ventes du mois comptant pour le quota.

    ``exclude_pk`` retire une vente du decompte : a l'ouverture d'une vente deja
    creee, elle ne doit pas etre comptee contre elle-meme.

    Une vente CANCELLED libere son slot : le vendeur ne doit pas etre penalise
    pour une vente annulee avant qu'elle ne se tienne (coherent avec la regle
    "3 ventes/jour" de FlashSaleForm, qui exclut deja CANCELLED).
    """
    from flash_sales.models import FlashSale, FlashSaleStatus

    now = timezone.now()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    qs = FlashSale.objects.filter(owner=seller, created_at__gte=month_start).exclude(
        status=FlashSaleStatus.CANCELLED
    )
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.count()


def get_sale_quota(seller, exclude_pk: int | None = None) -> dict:
    """Retourne les infos de quota pour la page liste."""
    sub = get_or_create_subscription(seller)

    # Plan effectif : un abonnement expire retombe sur le plan FREE (sub.plan
    # peut rester "pro" tant que personne ne retrograde l'enregistrement).
    effective_plan = Plan.FREE if sub.is_expired else sub.plan
    limit = get_monthly_limit(effective_plan)
    count = count_sales_this_month(seller, exclude_pk) if limit is not None else 0

    base = {
        "is_pro": sub.is_pro,
        "is_medium": sub.is_medium,
        "is_paid": sub.is_paid,
        "plan": effective_plan,
        # Libelle affichable (« Gratuit », « Medium », « Pro ») : ne jamais
        # afficher le code du plan (« Free ») a l'utilisateur.
        "plan_label": Plan(effective_plan).label,
        "monthly_count": count,
        "monthly_limit": limit,
    }
    if limit is not None and count >= limit:
        if effective_plan == Plan.PRO:
            upsell = "Contactez le support pour augmenter votre limite."
        else:
            upsell = f"Passez au plan Pro : {quota_label(Plan.PRO).lower()}."
        return {
            **base,
            "can_create": False,
            "reason": f"Vous avez utilisé {count}/{limit} ventes ce mois-ci. {upsell}",
        }
    return {**base, "can_create": True, "reason": ""}


def can_create_flash_sale(seller, exclude_pk: int | None = None) -> tuple[bool, str]:
    """Retourne (True, '') ou (False, message_erreur)."""
    q = get_sale_quota(seller, exclude_pk)
    return q["can_create"], q["reason"]
