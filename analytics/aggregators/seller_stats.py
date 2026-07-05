from __future__ import annotations

from django.db.models import Count, Sum

from analytics.services.cache import get_cached_stats, seller_stats_key, set_cached_stats
from orders.models import OrderItem


def get_seller_public_stats(seller_id: int) -> dict[str, int]:
    """
    Aggregated seller stats (cached). Safe for public pages — no PII.
    """
    key = seller_stats_key(seller_id)
    cached = get_cached_stats(key)
    if cached is not None:
        return cached

    row = OrderItem.objects.filter(order__flash_sale__owner_id=seller_id).aggregate(
        total_orders=Count("order_id", distinct=True),
        products_sold=Sum("quantity"),
    )
    stats = {
        "total_orders": int(row["total_orders"] or 0),
        "products_sold": int(row["products_sold"] or 0),
    }
    set_cached_stats(key, stats)
    return stats
