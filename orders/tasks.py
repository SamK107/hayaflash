"""Tâches Celery des commandes."""

from __future__ import annotations

from celery import shared_task

from orders.services.expiration import expire_pending_orders


@shared_task(name="orders.expire_pending_orders", ignore_result=True)
def expire_pending_orders_task() -> None:
    """F-59 : annule les commandes en attente depuis plus de 48 h et rend leur stock.

    Aucune file imposée : file par défaut (« default »), écoutée par le worker (F-89).
    """
    expire_pending_orders()
