"""Activité des vendeurs recommandés (calculée à la lecture, aucune tâche planifiée).

Un vendeur est « actif » à partir de sa première commande non annulée sur une vente
non annulée ; cette date est sa date d'activation.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from django.db.models import Min

from flash_sales.models import FlashSaleStatus
from orders.models import Order, OrderStatus


def activation_dates(seller_ids: Iterable[int]) -> dict[int, datetime]:
    """seller_id -> date de sa première commande non annulée (vente non annulée)."""
    ids = list(seller_ids)
    if not ids:
        return {}
    rows = (
        Order.service_objects.filter(flash_sale__owner_id__in=ids)
        .exclude(status=OrderStatus.CANCELLED)
        .exclude(flash_sale__status=FlashSaleStatus.CANCELLED)
        .values("flash_sale__owner_id")
        .annotate(first=Min("created_at"))
    )
    return {r["flash_sale__owner_id"]: r["first"] for r in rows}
