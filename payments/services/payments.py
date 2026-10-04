from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from orders.models import Order, OrderStatus
from payments.models import (
    PaymentProvider,
    PaymentTransaction,
    PaymentTransactionStatus,
)
from payments.services.mock_provider import initiate_mock_charge


def _normalize_phone(value: str) -> str:
    return "".join(ch for ch in value.strip() if not ch.isspace())


def order_payable_total(order: Order) -> Decimal:
    total = Decimal("0")
    for line in order.items.all():
        total += line.price_snapshot * line.quantity
    return total


def _require_provider(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValidationError({"provider": "Doit être un texte non vide."})
    choice_values = {c for c, _ in PaymentProvider.choices}
    v = raw.strip()
    if v not in choice_values:
        raise ValidationError(
            {"provider": f"Fournisseur invalide. Valeurs autorisées : {sorted(choice_values)}."},
        )
    return v


def _parse_client_reference(raw: Any) -> uuid.UUID | None:
    if raw is None:
        return None
    if isinstance(raw, uuid.UUID):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        raise ValidationError({"client_reference": "Doit être un UUID sous forme de texte."})
    try:
        return uuid.UUID(raw.strip())
    except ValueError as exc:
        raise ValidationError({"client_reference": "Doit être un UUID valide."}) from exc


def initiate_payment_for_order(
    *,
    order_id: Any,
    phone: Any,
    provider: Any,
    client_reference: Any = None,
) -> tuple[PaymentTransaction, dict[str, Any]]:
    """
    Create (or return) a pending ``PaymentTransaction`` and run the mock provider.

    Idempotent on ``client_reference`` (unique): same key returns the same row.
    """
    # bool est une sous-classe de int : `true` (JSON) ciblait sinon la commande n° 1.
    if isinstance(order_id, bool) or not isinstance(order_id, int) or order_id < 1:
        raise ValidationError({"order_id": "Doit être un entier positif."})
    if not isinstance(phone, str) or not phone.strip():
        raise ValidationError({"phone": "Doit être un texte non vide."})

    provider_code = _require_provider(provider)
    client_ref = _parse_client_reference(client_reference)
    phone_n = _normalize_phone(phone)

    with transaction.atomic():
        if client_ref is not None:
            existing = (
                PaymentTransaction.objects.select_for_update()
                .filter(client_reference=client_ref)
                .first()
            )
            if existing is not None:
                return existing, {"idempotent_replay": True}

        try:
            order = (
                Order.objects.select_for_update()
                .prefetch_related("items")
                .get(pk=order_id)
            )
        except Order.DoesNotExist as exc:
            raise ValidationError({"order_id": "Commande introuvable."}) from exc

        if order.status != OrderStatus.PENDING:
            raise ValidationError(
                {"order_id": "Only pending orders can be paid."},
            )

        computed = order_payable_total(order)
        if computed <= 0:
            raise ValidationError(
                {"order_id": "Le total de la commande doit être supérieur à zéro."}
            )

        order_phone = _normalize_phone(order.customer_phone or "")
        if not order_phone or order_phone != phone_n:
            raise ValidationError({"phone": "Ne correspond pas au téléphone du client de la commande."})

        client_uuid = client_ref if client_ref is not None else uuid.uuid4()

        try:
            pt = PaymentTransaction.objects.create(
                order=order,
                amount=computed,
                currency="XOF",
                provider=provider_code,
                status=PaymentTransactionStatus.PENDING,
                client_reference=client_uuid,
                payer_phone=phone_n,
            )
        except IntegrityError:
            if client_ref is None:
                raise
            pt = PaymentTransaction.objects.select_for_update().get(
                client_reference=client_ref,
            )
            return pt, {"idempotent_replay": True}

        payload = initiate_mock_charge(pt, phone_n)
        pt.refresh_from_db()
        return pt, payload


def payment_public_snapshot(pt: PaymentTransaction) -> dict[str, Any]:
    return {
        "id": str(pt.id),
        "order_id": pt.order_id,
        "amount": str(pt.amount),
        "currency": pt.currency,
        "provider": pt.provider,
        "status": pt.status,
        "provider_reference": pt.provider_reference,
        "client_reference": str(pt.client_reference),
        "created_at": pt.created_at.isoformat(),
        "updated_at": pt.updated_at.isoformat(),
    }
