from __future__ import annotations

import base64
import binascii
import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from delivery.models import Delivery
from delivery.services.validation import validate_delivery_input
from orders.models import Order, OrderStatus

logger = logging.getLogger(__name__)


def compute_order_total(order: Order) -> Decimal:
    """Sum of price_snapshot * quantity on order line items."""
    agg = order.items.aggregate(
        total=Coalesce(
            Sum(F("price_snapshot") * F("quantity")),
            Value(Decimal("0.00")),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )
    )
    return agg["total"] or Decimal("0.00")


def _attach_audio_note(delivery: Delivery, audio_base64: str, order_id: int) -> None:
    """
    Best-effort: decode and attach the client's voice note. A malformed or
    corrupt recording must never block order/delivery creation.
    """
    try:
        raw = base64.b64decode(audio_base64, validate=True)
    except (binascii.Error, ValueError):
        logger.warning("delivery_audio_note_decode_failed order_id=%s", order_id)
        return
    if not raw:
        return
    delivery.audio_note.save(
        f"order_{order_id}_localisation.webm",
        ContentFile(raw),
        save=True,
    )


def create_delivery_for_order(
    *, order: Order, delivery_data: dict[str, Any]
) -> Delivery:
    """
    Create Delivery for an order inside the same atomic transaction as create_order().
    Idempotent when delivery already exists for the order.
    """
    existing = Delivery.objects.filter(order_id=order.pk).first()
    if existing is not None:
        return existing

    audio_base64 = delivery_data.get("audio_base64")
    cleaned = validate_delivery_input(delivery_data)
    cod_amount = compute_order_total(order)

    delivery = Delivery.objects.create(
        order=order,
        address_text=cleaned["address_text"],
        latitude=cleaned["latitude"],
        longitude=cleaned["longitude"],
        geo_accuracy=cleaned["geo_accuracy"],
        geo_method=cleaned["geo_method"],
        delivery_notes=cleaned["delivery_notes"],
        status=Delivery.Status.PENDING,
        cod_amount=cod_amount,
    )

    if audio_base64:
        _attach_audio_note(delivery, audio_base64, order.pk)

    return delivery


def delivery_public_snapshot(delivery: Delivery) -> dict[str, Any]:
    """Public-safe delivery fields for POST /orders/ response."""
    return {
        "delivery_id": str(delivery.pk),
        "address_text": delivery.address_text,
        "maps_url": delivery.get_maps_url(),
        "waze_url": delivery.get_waze_url(),
        "status": delivery.status,
    }


def _delivery_queryset_for_seller(*, user, flash_sale_id: int):
    return (
        Delivery.objects.filter(
            order__flash_sale_id=flash_sale_id,
            order__flash_sale__owner__user=user,
        )
        .select_related("order")
        .order_by("-created_at")
    )


def _delivery_result_row(delivery: Delivery) -> dict[str, Any]:
    order = delivery.order
    return {
        "delivery_id": str(delivery.pk),
        "order_id": order.pk,
        "order_number": f"ORD-{order.pk:03d}",
        "customer_name": order.customer_name or "",
        "customer_phone": order.customer_phone or "",
        "address_text": delivery.address_text,
        "latitude": str(delivery.latitude) if delivery.latitude is not None else None,
        "longitude": str(delivery.longitude)
        if delivery.longitude is not None
        else None,
        "maps_url": delivery.get_maps_url(),
        "waze_url": delivery.get_waze_url(),
        "delivery_notes": delivery.delivery_notes,
        "status": delivery.status,
        "cod_amount": str(delivery.cod_amount),
        "cod_collected": delivery.cod_collected,
        "assigned_to": delivery.assigned_to or None,
    }


def list_seller_deliveries(
    *,
    user,
    flash_sale_id: int,
    status: str | None = None,
) -> dict[str, Any]:
    """Tenant-scoped delivery list for seller API."""
    from flash_sales.models import FlashSale

    flash_sale = FlashSale.objects.filter(
        pk=flash_sale_id,
        owner__user=user,
    ).first()
    if flash_sale is None:
        raise PermissionDenied("Flash sale not found or not accessible.")

    qs = _delivery_queryset_for_seller(user=user, flash_sale_id=flash_sale_id)
    if status:
        qs = qs.filter(status=status)

    all_for_sale = _delivery_queryset_for_seller(user=user, flash_sale_id=flash_sale_id)
    pending = all_for_sale.filter(status=Delivery.Status.PENDING).count()
    in_transit = all_for_sale.filter(status=Delivery.Status.IN_TRANSIT).count()
    delivered = all_for_sale.filter(status=Delivery.Status.DELIVERED).count()

    cod_agg = all_for_sale.aggregate(
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

    results = [_delivery_result_row(d) for d in qs]
    return {
        "count": len(results),
        "summary": {
            "pending": pending,
            "in_transit": in_transit,
            "delivered": delivered,
            "total_cod_collected": str(cod_agg["collected"] or Decimal("0.00")),
            "total_cod_pending": str(cod_agg["pending_total"] or Decimal("0.00")),
        },
        "results": results,
    }


def advance_delivery(
    *,
    user,
    delivery_id: UUID,
    action: str,
    payload: dict[str, Any] | None = None,
) -> Delivery:
    """
    Advance order + delivery workflow for authenticated seller.
    """
    payload = payload or {}
    now = timezone.now()

    with transaction.atomic():
        delivery = (
            Delivery.objects.select_for_update()
            .select_related("order__flash_sale__owner__user")
            .filter(pk=delivery_id)
            .first()
        )
        if delivery is None:
            raise PermissionDenied("Delivery not found.")

        order = (
            Order.service_objects.select_for_update()
            .filter(pk=delivery.order_id)
            .first()
        )
        if order is None:
            raise PermissionDenied("Order not found.")

        owner_user = delivery.order.flash_sale.owner.user
        if owner_user.pk != user.pk:
            raise PermissionDenied("Not allowed.")

        order_before = order.status
        delivery_before = delivery.status

        if action == "confirm":
            if order.status != OrderStatus.PENDING:
                raise ValidationError(
                    "Order cannot be confirmed from its current status."
                )
            order.status = OrderStatus.CONFIRMED
            order.save(update_fields=["status", "updated_at"])

        elif action == "start_delivery":
            assigned_to = payload.get("assigned_to")
            if not isinstance(assigned_to, str) or not assigned_to.strip():
                raise ValidationError({"assigned_to": "Courier name is required."})
            if order.status != OrderStatus.CONFIRMED:
                raise ValidationError(
                    "Order must be confirmed before starting delivery."
                )
            order.status = OrderStatus.OUT_FOR_DELIVERY
            order.save(update_fields=["status", "updated_at"])
            delivery.status = Delivery.Status.IN_TRANSIT
            delivery.assigned_to = assigned_to.strip()[:200]
            delivery.scheduled_at = now
            delivery.save(
                update_fields=[
                    "status",
                    "assigned_to",
                    "scheduled_at",
                    "updated_at",
                ]
            )

        elif action == "mark_delivered":
            if "cod_collected" not in payload:
                raise ValidationError({"cod_collected": "This field is required."})
            cod_collected = payload.get("cod_collected")
            if not isinstance(cod_collected, bool):
                raise ValidationError({"cod_collected": "Must be a boolean."})
            if order.status != OrderStatus.OUT_FOR_DELIVERY:
                raise ValidationError(
                    "Order must be out for delivery before marking delivered."
                )
            order.status = OrderStatus.DELIVERED
            order.save(update_fields=["status", "updated_at"])
            delivery.status = Delivery.Status.DELIVERED
            delivery.delivered_at = now
            delivery.cod_collected = cod_collected
            if cod_collected:
                delivery.cod_collected_at = now
                delivery.cod_confirmed_by = user
            delivery.save(
                update_fields=[
                    "status",
                    "delivered_at",
                    "cod_collected",
                    "cod_collected_at",
                    "cod_confirmed_by",
                    "updated_at",
                ]
            )

        elif action == "mark_failed":
            if delivery.status not in (
                Delivery.Status.PENDING,
                Delivery.Status.ASSIGNED,
                Delivery.Status.IN_TRANSIT,
            ):
                raise ValidationError(
                    "Delivery cannot be marked failed from its current status."
                )
            delivery.status = Delivery.Status.FAILED
            delivery.save(update_fields=["status", "updated_at"])

        else:
            raise ValidationError({"action": f"Unknown action: {action}"})

        logger.info(
            "delivery_advance actor_id=%s order_id=%s delivery_id=%s action=%s "
            "order_status=%s->%s delivery_status=%s->%s",
            user.pk,
            order.pk,
            delivery.pk,
            action,
            order_before,
            order.status,
            delivery_before,
            delivery.status,
        )

    from orders.services.dashboard import invalidate_seller_kpi_cache

    invalidate_seller_kpi_cache(user)
    delivery.refresh_from_db()
    order.refresh_from_db()
    return delivery
