"""Restitution du stock réservé par une commande (expiration, annulation par la vendeuse).

La quantité à rendre se déduit des mouvements de stock de la commande
(réservations moins libérations déjà faites), pas des lignes : c'est ce qui rend
l'opération rejouable sans double retour, et sans effet sur une commande ancienne
qui n'aurait jamais réservé de stock. À appeler dans une transaction, la commande
étant déjà verrouillée.
"""

from __future__ import annotations

from django.db.models import F, Sum

from orders.models import Order
from products.models import Product, StockMovement


def release_order_stock(order: Order, note: str) -> dict[int, int]:
    """Rend le stock de ``order`` ; retourne {product_id: quantité rendue}."""
    net_by_product = {
        row["product_id"]: row["net"]
        for row in StockMovement.objects.filter(order=order)
        .values("product_id")
        .annotate(net=Sum("quantity_change"))
    }
    released: dict[int, int] = {}
    # Même ordre de verrouillage que create_order (produits triés) : pas d'interblocage.
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
            notes=note,
        )
        released[product_id] = to_return
    return released
