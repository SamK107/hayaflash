from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.core.cache import cache
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import (
    DecimalField,
    ExpressionWrapper,
    F,
    IntegerField,
    Prefetch,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce

from orders.models import Order, OrderItem, OrderStatus

KPI_CACHE_KEY = "kpi:seller:{user_id}"
KPI_CACHE_TTL_SECONDS = 4


def _seller_orders_queryset(user):
    return (
        Order.service_objects.filter(flash_sale__owner__user=user)
        .select_related("flash_sale")
        .prefetch_related(
            Prefetch(
                "items",
                queryset=OrderItem.objects.select_related("product"),
            )
        )
    )


def invalidate_seller_kpi_cache(user) -> None:
    cache.delete(KPI_CACHE_KEY.format(user_id=user.pk))


def get_dashboard_kpis(user) -> dict[str, Any]:
    """
    Agrégats pour le vendeur connecté.
    - total_orders  : toutes commandes non annulées
    - total_quantity: articles de toutes commandes non annulées
    - total_revenue : CA réel = uniquement les commandes "Livré et payé"
    - pending_revenue: CA potentiel = commandes en cours (confirmées + en livraison)
    """
    non_cancelled = Order.service_objects.filter(
        flash_sale__owner__user=user,
    ).exclude(status=OrderStatus.CANCELLED)

    total_orders = non_cancelled.count()

    revenue_expr = ExpressionWrapper(
        F("price_snapshot") * F("quantity"),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )

    # CA réel : seulement "Livré et payé"
    delivered_agg = (
        OrderItem.objects.filter(
            order__flash_sale__owner__user=user,
            order__status=OrderStatus.DELIVERED,
        )
        .aggregate(
            total_quantity=Coalesce(
                Sum("quantity"), Value(0, output_field=IntegerField())
            ),
            total_revenue=Coalesce(
                Sum(revenue_expr),
                Value(Decimal("0.00"),
                      output_field=DecimalField(max_digits=14, decimal_places=2)),
            ),
        )
    )

    # CA potentiel : commandes confirmées ou en livraison (pas encore encaissées)
    pending_revenue_agg = (
        OrderItem.objects.filter(
            order__flash_sale__owner__user=user,
            order__status__in=[OrderStatus.CONFIRMED, OrderStatus.OUT_FOR_DELIVERY],
        )
        .aggregate(
            pending_revenue=Coalesce(
                Sum(revenue_expr),
                Value(Decimal("0.00"),
                      output_field=DecimalField(max_digits=14, decimal_places=2)),
            )
        )
    )

    return {
        "total_orders":    total_orders,
        "total_quantity":  int(delivered_agg["total_quantity"] or 0),
        "total_revenue":   delivered_agg["total_revenue"] or Decimal("0.00"),
        "pending_revenue": pending_revenue_agg["pending_revenue"] or Decimal("0.00"),
    }


def get_dashboard_kpis_cached(user) -> dict[str, Any]:
    """KPI snapshot with short TTL (shared cache backend: LocMem or Redis)."""
    key = KPI_CACHE_KEY.format(user_id=user.pk)
    hit = cache.get(key)
    if hit is not None:
        return hit
    data = get_dashboard_kpis(user)
    cache.set(key, data, KPI_CACHE_TTL_SECONDS)
    return data


def get_dashboard_orders(user, *, limit: int = 20):
    """Latest orders for this seller, newest first."""
    return _seller_orders_queryset(user).order_by("-created_at")[:limit]


def _next_status(current: str) -> str | None:
    if current == OrderStatus.PENDING:
        return OrderStatus.CONFIRMED
    if current == OrderStatus.CONFIRMED:
        return OrderStatus.OUT_FOR_DELIVERY
    if current == OrderStatus.OUT_FOR_DELIVERY:
        return OrderStatus.DELIVERED
    return None


def _row_dict_for_order(order: Order) -> dict[str, Any]:
    nxt = _next_status(order.status)
    return {
        "order": order,
        "can_advance": nxt is not None,
        "next_status": nxt or "",
        "next_status_label": (
            dict(OrderStatus.choices).get(nxt, nxt) if nxt else ""
        ),
    }


def list_dashboard_order_rows(user, *, limit: int = 20) -> list[dict[str, Any]]:
    """Pre-built rows for templates (no branching logic in HTML)."""
    return [_row_dict_for_order(o) for o in get_dashboard_orders(user, limit=limit)]


def get_order_row_context(user, order_id: int) -> dict[str, Any] | None:
    """Single order row context for HTMX partial swap."""
    order = _seller_orders_queryset(user).filter(pk=order_id).first()
    if order is None:
        return None
    return _row_dict_for_order(order)


def _sync_delivery_for_order(*, order: Order, new_status: str, user) -> None:
    """
    Garde Delivery.status en cohérence quand l'order avance depuis le dashboard Commandes.
    Évite le désynchronisation Delivery=PENDING / Order=DELIVERED.
    """
    try:
        from delivery.models import Delivery
        from django.utils import timezone
        now = timezone.now()

        delivery = Delivery.objects.filter(order_id=order.pk).first()
        if delivery is None:
            return

        if new_status == OrderStatus.OUT_FOR_DELIVERY and delivery.status in (
            Delivery.Status.PENDING, Delivery.Status.ASSIGNED
        ):
            delivery.status = Delivery.Status.IN_TRANSIT
            delivery.scheduled_at = now
            delivery.save(update_fields=["status", "scheduled_at", "updated_at"])

        elif new_status == OrderStatus.DELIVERED and delivery.status != Delivery.Status.DELIVERED:
            delivery.status = Delivery.Status.DELIVERED
            delivery.delivered_at = now
            delivery.cod_collected = True
            delivery.cod_collected_at = now
            delivery.cod_confirmed_by = user
            delivery.save(update_fields=[
                "status", "delivered_at", "cod_collected",
                "cod_collected_at", "cod_confirmed_by", "updated_at",
            ])
    except Exception:
        pass  # Ne jamais bloquer l'avancement d'une commande pour une sync delivery


def advance_order_status(*, user, order_id: int) -> Order:
    """
    Move order one step: pending → confirmed → out_for_delivery → delivered.

    V1 live dashboard keeps this simplified 1-click flow during the sale.
    Post-live COD workflow uses ``delivery.services.advance_delivery`` via
    la page Livraisons (logistique post-vente).
    """
    order = (
        Order.service_objects.select_related("flash_sale__owner__user")
        .filter(pk=order_id, flash_sale__owner__user=user)
        .first()
    )
    if order is None:
        raise PermissionDenied("Order not found or not accessible.")

    nxt = _next_status(order.status)
    if nxt is None:
        raise ValidationError(
            "This order cannot be advanced from its current status."
        )

    order.status = nxt
    order.save(update_fields=["status", "updated_at"])
    _sync_delivery_for_order(order=order, new_status=nxt, user=user)
    invalidate_seller_kpi_cache(user)
    return order
