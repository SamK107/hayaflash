from __future__ import annotations

import base64
import binascii
import logging
from decimal import Decimal
from typing import Any
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.db.models import DecimalField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.validators import validate_file_field
from delivery.models import Delivery
from delivery.services.validation import validate_delivery_input
from orders.models import Order, OrderStatus

logger = logging.getLogger(__name__)


def compute_order_total(order: Order) -> Decimal:
    """Sum of price_snapshot * quantity on order line items."""
    agg = order.items.aggregate(
        total=Coalesce(
            Sum(F("price_snapshot") * F("quantity")),
            Value(Decimal("0")),
            output_field=DecimalField(max_digits=14, decimal_places=0),
        )
    )
    return agg["total"] or Decimal("0")


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
    audio = SimpleUploadedFile(
        f"order_{order_id}_localisation.webm", raw, content_type="audio/webm"
    )
    try:
        validate_file_field(delivery, "audio_note", audio)  # F-02
    except ValidationError:
        logger.warning("delivery_audio_note_invalid order_id=%s", order_id)
        return
    delivery.audio_note.save(audio.name, ContentFile(raw), save=True)


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


LEGACY_ADDRESS = "Adresse non renseignée (commande ancienne) : appeler le client"


def ensure_delivery_for_order(order: Order) -> tuple[Delivery, bool]:
    """Fiche de livraison de ``order`` ; la crée si elle manque (commande ancienne).

    Une commande sans fiche passait d'étape dans Commandes mais restait invisible
    et inactive sur la page Livraison. Idempotent. Retourne (fiche, créée).
    Le montant à encaisser est recalculé depuis les lignes de la commande.
    """
    existing = Delivery.objects.filter(order_id=order.pk).first()
    if existing is not None:
        return existing, False
    delivery = Delivery.objects.create(
        order=order,
        address_text=LEGACY_ADDRESS,
        status=Delivery.Status.PENDING,
        cod_amount=compute_order_total(order),
    )
    return delivery, True


def ensure_deliveries_for_sale(flash_sale_id: int) -> int:
    """Crée les fiches manquantes des commandes (non annulées) d'une vente. Retourne le nombre créé."""
    created = 0
    orders = Order.service_objects.filter(
        flash_sale_id=flash_sale_id, delivery__isnull=True
    ).exclude(status=OrderStatus.CANCELLED)
    for order in orders:
        _, was_created = ensure_delivery_for_order(order)
        created += int(was_created)
    return created


def delivery_public_snapshot(delivery: Delivery) -> dict[str, Any]:
    """Public-safe delivery fields for POST /orders/ response."""
    return {
        "delivery_id": str(delivery.pk),
        "address_text": delivery.address_text,
        "maps_url": delivery.get_maps_url(),
        "waze_url": delivery.get_waze_url(),
        "status": delivery.status,
    }


CANCELLED_ORDER_MESSAGE = (
    "Cette commande est annulée : aucune action de livraison n'est possible."
)


def live_deliveries_q(prefix: str = "order__") -> Q:
    """Définition unique (F-99) des livraisons qui comptent : commande NON annulée.

    La livraison d'une commande annulée (par exemple expirée, F-59) garde son statut
    `pending` : sans ce filtre elle gonflerait « À encaisser », les compteurs et les
    listes. ``prefix`` = chemin vers la commande (``"order__"`` pour ``Delivery``).
    """
    return ~Q(**{f"{prefix}status": OrderStatus.CANCELLED})


def cancelled_deliveries_q(prefix: str = "order__") -> Q:
    return Q(**{f"{prefix}status": OrderStatus.CANCELLED})


def _delivery_queryset_for_seller(*, user, flash_sale_id: int):
    return (
        Delivery.objects.filter(
            live_deliveries_q(),
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
        raise PermissionDenied("Vente flash introuvable ou inaccessible.")

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
            Value(Decimal("0")),
            output_field=DecimalField(max_digits=14, decimal_places=0),
        ),
        pending_total=Coalesce(
            Sum("cod_amount", filter=Q(cod_collected=False)),
            Value(Decimal("0")),
            output_field=DecimalField(max_digits=14, decimal_places=0),
        ),
    )

    results = [_delivery_result_row(d) for d in qs]
    return {
        "count": len(results),
        "summary": {
            "pending": pending,
            "in_transit": in_transit,
            "delivered": delivered,
            "total_cod_collected": str(cod_agg["collected"] or Decimal("0")),
            "total_cod_pending": str(cod_agg["pending_total"] or Decimal("0")),
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
            Delivery.objects.select_for_update(of=("self",))
            .select_related("order__flash_sale__owner__user")
            .filter(pk=delivery_id)
            .first()
        )
        if delivery is None:
            raise PermissionDenied("Livraison introuvable.")

        order = (
            Order.service_objects.select_for_update()
            .filter(pk=delivery.order_id)
            .first()
        )
        if order is None:
            raise PermissionDenied("Commande introuvable.")

        owner_user = delivery.order.flash_sale.owner.user
        if owner_user.pk != user.pk:
            raise PermissionDenied("Action non autorisée.")

        if order.status == OrderStatus.CANCELLED:
            raise ValidationError(CANCELLED_ORDER_MESSAGE)

        order_before = order.status
        delivery_before = delivery.status

        if action == "confirm":
            if order.status != OrderStatus.PENDING:
                raise ValidationError(
                    "Cette commande ne peut plus être confirmée dans son état actuel."
                )
            order.status = OrderStatus.CONFIRMED
            order.save(update_fields=["status", "updated_at"])

        elif action == "cancel":
            # Annulation par la vendeuse : seulement avant la mise en livraison.
            if order.status not in (OrderStatus.PENDING, OrderStatus.CONFIRMED) or (
                delivery.status not in (Delivery.Status.PENDING, Delivery.Status.ASSIGNED)
            ):
                raise ValidationError(
                    "Cette commande ne peut plus être annulée : la livraison a déjà commencé."
                )
            from core.models import audit
            from orders.services.stock_release import release_order_stock

            released = release_order_stock(order, "Annulation par la vendeuse")
            order.status = OrderStatus.CANCELLED
            order.save(update_fields=["status", "updated_at"])
            audit(
                "order.cancelled_by_seller",
                entity_type="Order",
                entity_id=order.pk,
                actor=user,
                flash_sale_id=order.flash_sale_id,
                stock_released={str(pid): qty for pid, qty in released.items()},
            )

        elif action == "start_delivery":
            assigned_to = payload.get("assigned_to")
            if not isinstance(assigned_to, str) or not assigned_to.strip():
                raise ValidationError({"assigned_to": "Indiquez le nom du livreur."})
            if order.status != OrderStatus.CONFIRMED:
                raise ValidationError(
                    "La commande doit être confirmée avant de démarrer la livraison."
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
                raise ValidationError({"cod_collected": "Indiquez si le paiement à la livraison a été encaissé."})
            cod_collected = payload.get("cod_collected")
            if not isinstance(cod_collected, bool):
                raise ValidationError({"cod_collected": "Valeur d'encaissement invalide."})
            if order.status != OrderStatus.OUT_FOR_DELIVERY:
                raise ValidationError(
                    "La commande doit être en cours de livraison avant d'être marquée livrée."
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
            if order.status not in (OrderStatus.CONFIRMED, OrderStatus.OUT_FOR_DELIVERY):
                raise ValidationError(
                    "Confirme d'abord la commande dans Commandes avant de signaler un échec."
                )
            if delivery.status not in (
                Delivery.Status.PENDING,
                Delivery.Status.ASSIGNED,
                Delivery.Status.IN_TRANSIT,
            ):
                raise ValidationError(
                    "Cette livraison ne peut plus être marquée en échec dans son état actuel."
                )
            delivery.status = Delivery.Status.FAILED
            delivery.save(update_fields=["status", "updated_at"])
            # F-59 / D2 : livraison refusee ou cliente injoignable = commande non
            # honoree, comptee pour le blocage du numero apres 3 echecs en 30 jours.
            from orders.services.unhonored import record_unhonored_order

            record_unhonored_order(order)

        else:
            raise ValidationError({"action": f"Action inconnue : {action}."})

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


ORDER_PAGE_ACTIONS = ("confirm", "cancel")
LATER_STEPS_MESSAGE = (
    "La livraison se gère sur la page Livraison : ouvre-la depuis la carte de la commande."
)


def apply_order_action(*, user, order_id: int, action: str) -> Delivery:
    """Action de la page Commandes (Confirmer, Annuler) : même service que la page Livraison.

    Toute transition passe par ``advance_delivery`` : une seule règle de statuts,
    et l'enregistrement des échecs (F-59) ne peut pas être contourné. Les étapes de
    livraison (livreur, en livraison, livré, échec) sont refusées ici
    (``PermissionDenied``). Crée la fiche de livraison d'une commande ancienne si besoin.
    """
    if action not in ORDER_PAGE_ACTIONS:
        raise PermissionDenied(LATER_STEPS_MESSAGE)
    order = (
        Order.service_objects.select_related("flash_sale__owner__user")
        .filter(pk=order_id, flash_sale__owner__user=user)
        .first()
    )
    if order is None:
        raise PermissionDenied("Commande introuvable ou inaccessible.")
    if order.status == OrderStatus.CANCELLED:
        raise ValidationError(CANCELLED_ORDER_MESSAGE)
    delivery, _ = ensure_delivery_for_order(order)
    return advance_delivery(user=user, delivery_id=delivery.pk, action=action)
