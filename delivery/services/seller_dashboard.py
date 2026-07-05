from __future__ import annotations

from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import DecimalField, Prefetch, Q, Sum, Value
from django.db.models.functions import Coalesce

from delivery.models import Delivery
from delivery.services.delivery import advance_delivery
from flash_sales.models import FlashSale
from orders.models import Order, OrderItem, OrderStatus

_STATUS_SORT = {
    Delivery.Status.PENDING: 0,
    Delivery.Status.ASSIGNED: 1,
    Delivery.Status.IN_TRANSIT: 2,
    Delivery.Status.FAILED: 3,
    Delivery.Status.DELIVERED: 4,
}


def _tenant_deliveries(*, user, flash_sale_id: int):
    return (
        Delivery.objects.filter(
            order__flash_sale_id=flash_sale_id,
            order__flash_sale__owner__user=user,
        )
        .select_related("order", "order__flash_sale")
        .prefetch_related(
            Prefetch(
                "order__items",
                queryset=OrderItem.objects.select_related("product"),
            )
        )
    )


def _get_owned_flash_sale(*, user, flash_sale_id: int) -> FlashSale | None:
    return FlashSale.objects.filter(pk=flash_sale_id, owner__user=user).first()


def resolve_delivery_dashboard_page(
    *,
    user,
    flash_sale_id: int | None,
) -> dict[str, Any]:
    flash_sales = (
        FlashSale.objects.filter(owner__user=user)
        .select_related("owner")
        .order_by("-created_at")[:20]
    )
    if flash_sale_id is None:
        return {
            "page_error": "Sélectionnez une vente flash pour voir les livraisons.",
            "flash_sale": None,
            "flash_sales": flash_sales,
            "selected_flash_sale_id": "",
            "can_view": False,
        }

    flash_sale = _get_owned_flash_sale(user=user, flash_sale_id=flash_sale_id)
    if flash_sale is None:
        return {
            "page_error": "Vente introuvable ou accès non autorisé.",
            "flash_sale": None,
            "flash_sales": flash_sales,
            "selected_flash_sale_id": str(flash_sale_id),
            "can_view": False,
        }

    return {
        "page_error": "",
        "flash_sale": flash_sale,
        "flash_sales": flash_sales,
        "selected_flash_sale_id": str(flash_sale_id),
        "can_view": True,
    }


def get_delivery_summary(*, user, flash_sale_id: int) -> dict[str, Any]:
    if _get_owned_flash_sale(user=user, flash_sale_id=flash_sale_id) is None:
        raise PermissionDenied("Flash sale not found or not accessible.")

    qs = _tenant_deliveries(user=user, flash_sale_id=flash_sale_id)
    pending = qs.filter(
        status__in=[Delivery.Status.PENDING, Delivery.Status.ASSIGNED]
    ).count()
    in_transit = qs.filter(status=Delivery.Status.IN_TRANSIT).count()
    delivered = qs.filter(status=Delivery.Status.DELIVERED).count()
    failed = qs.filter(status=Delivery.Status.FAILED).count()

    cod_agg = qs.aggregate(
        collected=Coalesce(
            Sum("cod_amount", filter=Q(cod_collected=True)),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
        pending_total=Coalesce(
            Sum("cod_amount", filter=Q(cod_collected=False)),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ),
    )

    return {
        "total_orders": qs.count(),
        "pending": pending,
        "in_transit": in_transit,
        "delivered": delivered,
        "failed": failed,
        "total_cod_pending": cod_agg["pending_total"] or Decimal("0.00"),
        "total_cod_collected": cod_agg["collected"] or Decimal("0.00"),
    }


def _action_flags(*, order: Order, delivery: Delivery) -> dict[str, bool]:
    return {
        "can_confirm": order.status == OrderStatus.PENDING
        and delivery.status == Delivery.Status.PENDING,
        "can_start_delivery": order.status == OrderStatus.CONFIRMED
        and delivery.status in (Delivery.Status.PENDING, Delivery.Status.ASSIGNED),
        "can_mark_delivered": order.status == OrderStatus.OUT_FOR_DELIVERY
        and delivery.status == Delivery.Status.IN_TRANSIT,
        "can_mark_failed": delivery.status
        in (
            Delivery.Status.PENDING,
            Delivery.Status.ASSIGNED,
            Delivery.Status.IN_TRANSIT,
        ),
        "can_cancel_order": False,
    }


def _row_dict_from_delivery(delivery: Delivery) -> dict[str, Any]:
    order = delivery.order
    return {
        "delivery": delivery,
        "order": order,
        "customer_name": order.customer_name or "",
        "customer_phone": order.customer_phone or "",
        "address_text": delivery.address_text,
        "maps_url": delivery.get_maps_url(),
        "waze_url": delivery.get_waze_url(),
        "cod_amount": delivery.cod_amount,
        "cod_collected": delivery.cod_collected,
        "status_label": delivery.get_status_display(),
        "assigned_to": delivery.assigned_to or "",
        **_action_flags(order=order, delivery=delivery),
    }


def _apply_status_filter(qs, status_filter: str | None):
    if not status_filter or status_filter == "all":
        return qs
    if status_filter == "pending":
        return qs.exclude(
            status__in=[
                Delivery.Status.IN_TRANSIT,
                Delivery.Status.DELIVERED,
                Delivery.Status.FAILED,
            ]
        )
    if status_filter == "in_transit":
        return qs.filter(status=Delivery.Status.IN_TRANSIT)
    if status_filter == "delivered":
        return qs.filter(status=Delivery.Status.DELIVERED)
    if status_filter == "failed":
        return qs.filter(status=Delivery.Status.FAILED)
    return qs


def list_delivery_rows(
    *,
    user,
    flash_sale_id: int,
    status_filter: str | None = None,
) -> list[dict[str, Any]]:
    if _get_owned_flash_sale(user=user, flash_sale_id=flash_sale_id) is None:
        raise PermissionDenied("Flash sale not found or not accessible.")

    qs = _apply_status_filter(
        _tenant_deliveries(user=user, flash_sale_id=flash_sale_id),
        status_filter,
    )
    deliveries = list(qs)
    deliveries.sort(
        key=lambda d: (
            _STATUS_SORT.get(d.status, 99),
            -d.created_at.timestamp(),
        )
    )
    return [_row_dict_from_delivery(d) for d in deliveries]


def get_delivery_row_context(*, user, delivery_id: UUID) -> dict[str, Any] | None:
    delivery = (
        Delivery.objects.filter(
            pk=delivery_id,
            order__flash_sale__owner__user=user,
        )
        .select_related("order", "order__flash_sale")
        .prefetch_related(
            Prefetch(
                "order__items",
                queryset=OrderItem.objects.select_related("product"),
            )
        )
        .first()
    )
    if delivery is None:
        return None
    return _row_dict_from_delivery(delivery)


def _parse_cod_collected(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        raise ValidationError({"cod_collected": "This field is required."})
    return str(raw).strip().lower() in ("true", "1", "yes", "on")


def apply_delivery_action_from_form(
    *,
    user,
    delivery_id: UUID,
    action: str,
    form_data: dict[str, Any],
) -> Delivery:
    """Thin HTMX wrapper around ``advance_delivery()``."""
    payload: dict[str, Any] = {}
    if action == "start_delivery":
        assigned = form_data.get("assigned_to")
        if not isinstance(assigned, str) or not assigned.strip():
            raise ValidationError({"assigned_to": "Courier name is required."})
        payload["assigned_to"] = assigned.strip()
    elif action == "mark_delivered":
        if "cod_collected" not in form_data:
            raise ValidationError({"cod_collected": "This field is required."})
        payload["cod_collected"] = _parse_cod_collected(form_data.get("cod_collected"))

    delivery = advance_delivery(
        user=user,
        delivery_id=delivery_id,
        action=action,
        payload=payload,
    )
    delivery.refresh_from_db()
    return delivery
