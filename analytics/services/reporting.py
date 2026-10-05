from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, DecimalField, ExpressionWrapper, F, Q, Sum
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone

from orders.models import OrderItem, OrderStatus
from orders.services.dashboard import collected_q


def _revenue_expr() -> ExpressionWrapper:
    return ExpressionWrapper(
        F("price_snapshot") * F("quantity"),
        output_field=DecimalField(max_digits=14, decimal_places=0),
    )


# F-95 : tout le CA de l'analytique = « Encaissé » des cartes de la page Commandes
# (F-94), via la même définition `collected_q`. Une commande livrée mais non
# encaissée, ou livrée sans livraison, n'entre dans aucun total ni classement.
def _collected_items():
    return OrderItem.objects.filter(collected_q("order__"))


def get_flash_sale_stats(flash_sale_id: int) -> dict:
    """Statistiques détaillées pour une vente flash (commandes encaissées)."""
    delivered_items = _collected_items().filter(order__flash_sale_id=flash_sale_id)
    agg = delivered_items.aggregate(
        total_quantity=Sum("quantity"),
        total_revenue=Sum(_revenue_expr()),
        total_orders=Count("order_id", distinct=True),
        unique_customers=Count("order__customer_phone", distinct=True),
    )
    return {
        "total_orders": agg["total_orders"] or 0,
        "total_quantity": agg["total_quantity"] or 0,
        "total_revenue": agg["total_revenue"] or 0,
        "unique_customers": agg["unique_customers"] or 0,
    }


def get_revenue_timeline(seller_id: int, days: int = 30) -> list[dict]:
    """Timeline de CA par jour sur `days` jours (commandes encaissées)."""
    start_date = timezone.now() - timedelta(days=days)
    rows = (
        _collected_items().filter(
            order__flash_sale__owner_id=seller_id,
            order__created_at__gte=start_date,
        )
        .annotate(day=TruncDate("order__created_at"))
        .values("day")
        .annotate(revenue=Sum(_revenue_expr()), orders=Count("order_id", distinct=True))
        .order_by("day")
    )
    return [
        {"day": str(r["day"]), "revenue": float(r["revenue"] or 0), "orders": r["orders"]}
        for r in rows
    ]


def get_revenue_timeline_monthly(seller_id: int) -> list[dict]:
    """Timeline mensuelle sur 12 mois (PRO)."""
    start_date = timezone.now() - timedelta(days=365)
    rows = (
        _collected_items().filter(
            order__flash_sale__owner_id=seller_id,
            order__created_at__gte=start_date,
        )
        .annotate(month=TruncMonth("order__created_at"))
        .values("month")
        .annotate(revenue=Sum(_revenue_expr()), orders=Count("order_id", distinct=True))
        .order_by("month")
    )
    return [
        {"month": r["month"].strftime("%Y-%m"), "revenue": float(r["revenue"] or 0), "orders": r["orders"]}
        for r in rows
    ]


def get_top_products(seller_id: int, limit: int = 5) -> list[dict]:
    """Top produits encaissés par quantité."""
    rows = (
        _collected_items().filter(order__flash_sale__owner_id=seller_id)
        .values("product_name_snapshot")
        .annotate(
            total_sold=Sum("quantity"),
            total_revenue=Sum(_revenue_expr()),
        )
        .order_by("-total_sold")[:limit]
    )
    return list(rows)


def get_sales_by_flash(seller_id: int) -> list[dict]:
    """Détail CA + commandes par vente flash terminée (PRO)."""
    from flash_sales.models import FlashSale, FlashSaleStatus

    sales = list(
        FlashSale.objects.filter(
            owner_id=seller_id,
            status__in=[FlashSaleStatus.COMPLETED, FlashSaleStatus.CLOSED],
        )
        .annotate(
            order_count=Count("orders", filter=~Q(orders__status=OrderStatus.CANCELLED))
        )
        .values("pk", "title", "start_time", "order_count")
        .order_by("-start_time")
    )
    revenue_by_sale = dict(
        _collected_items().filter(order__flash_sale_id__in=[s["pk"] for s in sales])
        .values("order__flash_sale_id")
        .annotate(revenue=Sum(_revenue_expr()))
        .values_list("order__flash_sale_id", "revenue")
    )
    for sale in sales:
        sale["revenue"] = revenue_by_sale.get(sale["pk"]) or 0
    return sales
