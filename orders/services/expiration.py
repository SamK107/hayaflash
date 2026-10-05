"""Expiration des commandes jamais confirmées (F-59).

``create_order`` réserve le stock dès la création d'une commande (statut
« En attente »). Sans suite, un client — ou un bot — peut vider une vente sans
jamais être livré. Toute commande restée en attente plus de
``settings.ORDER_PENDING_EXPIRY_HOURS`` heures passe en « Annulé » et rend son
stock, une seule fois.

La quantité à rendre se déduit des mouvements de stock de la commande
(réservations moins libérations déjà faites), pas des lignes : c'est ce qui rend
la tâche rejouable sans double retour, et sans effet sur une commande ancienne
qui n'aurait jamais réservé de stock.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

from core.models import audit
from orders.models import Order, OrderStatus
from orders.services.dashboard import invalidate_seller_kpi_cache
from products.models import Product, StockMovement

logger = logging.getLogger(__name__)

EXPIRY_NOTE = "Expiration automatique : commande jamais confirmée"


def _candidate_ids(cutoff: datetime) -> list[int]:
    return list(
        Order.service_objects.filter(status=OrderStatus.PENDING, created_at__lt=cutoff)
        .order_by("created_at")
        .values_list("pk", flat=True)
    )


def _expire_one(order_id: int, cutoff: datetime) -> Order | None:
    """Annule une commande et rend son stock, sous verrou. None si plus éligible."""
    with transaction.atomic():
        # Relecture sous verrou : une commande confirmée (ou déjà expirée) entre la
        # sélection et ici n'est plus PENDING et n'est pas touchée.
        order = (
            Order.service_objects.select_for_update(of=("self",))
            .select_related("flash_sale__owner__user")
            .filter(pk=order_id, status=OrderStatus.PENDING, created_at__lt=cutoff)
            .first()
        )
        if order is None:
            return None

        net_by_product = {
            row["product_id"]: row["net"]
            for row in StockMovement.objects.filter(order=order)
            .values("product_id")
            .annotate(net=Sum("quantity_change"))
        }
        # Même ordre de verrouillage que create_order (produits triés) : pas d'interblocage.
        released: dict[int, int] = {}
        for product_id in sorted(net_by_product):
            to_return = -int(net_by_product[product_id])
            if to_return <= 0:
                continue
            Product.objects.select_for_update().filter(pk=product_id).first()
            Product.objects.filter(pk=product_id).update(
                stock_available=F("stock_available") + to_return
            )
            StockMovement.objects.create(
                product_id=product_id,
                order=order,
                quantity_change=to_return,
                movement_type=StockMovement.MovementType.RELEASE,
                notes=EXPIRY_NOTE,
            )
            released[product_id] = to_return

        order.status = OrderStatus.CANCELLED
        order.save(update_fields=["status", "updated_at"])
        audit(
            "order.expired",
            entity_type="Order",
            entity_id=order.pk,
            flash_sale_id=order.flash_sale_id,
            expiry_hours=settings.ORDER_PENDING_EXPIRY_HOURS,
            stock_released={str(pid): qty for pid, qty in released.items()},
        )
        return order


def expire_pending_orders(*, now: datetime | None = None) -> int:
    """Expire les commandes en attente depuis plus de 48 h. Retourne leur nombre."""
    now = now or timezone.now()
    cutoff = now - timedelta(hours=settings.ORDER_PENDING_EXPIRY_HOURS)
    expired = 0
    sellers: dict[int, object] = {}
    for order_id in _candidate_ids(cutoff):
        try:
            order = _expire_one(order_id, cutoff)
        except Exception:
            logger.exception("Expiration de la commande %s impossible", order_id)
            continue
        if order is None:
            continue
        expired += 1
        if order.flash_sale_id:
            user = order.flash_sale.owner.user
            sellers[user.pk] = user
    for user in sellers.values():
        invalidate_seller_kpi_cache(user)
    if expired:
        logger.info("expire_pending_orders : %d commande(s) expirée(s)", expired)
    return expired
