from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from django.conf import settings
from django.db import transaction

from payments.models import PaymentTransaction, PaymentTransactionStatus
from payments.services.ledger import append_balanced_entries_for_success


class WebhookProcessingError(Exception):
    """Maps to HTTP error responses from the webhook view."""

    def __init__(self, message: str, *, code: str = "invalid") -> None:
        super().__init__(message)
        self.code = code


def verify_webhook_signature(
    secret: str, raw_body: bytes, signature_header: str | None
) -> None:
    if not secret:
        raise WebhookProcessingError(
            "Webhook secret not configured.",
            code="misconfigured",
        )
    if not signature_header:
        raise WebhookProcessingError("Missing signature header.", code="signature")
    prefix = "sha256="
    if not signature_header.startswith(prefix):
        raise WebhookProcessingError("Invalid signature format.", code="signature")
    supplied_hex = signature_header[len(prefix) :].strip()
    expected = hmac.new(
        secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, supplied_hex):
        raise WebhookProcessingError("Invalid signature.", code="signature")


def _normalize_provider_status(raw: Any) -> str:
    if not isinstance(raw, str):
        raise WebhookProcessingError("status must be a string.")
    v = raw.strip().lower()
    if v in ("success", "succeeded", "ok", "completed"):
        return PaymentTransactionStatus.SUCCESS
    if v in ("failed", "error", "declined"):
        return PaymentTransactionStatus.FAILED
    raise WebhookProcessingError("Unsupported status value.")


def parse_webhook_json(raw_body: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WebhookProcessingError("Invalid JSON body.") from exc
    if not isinstance(parsed, dict):
        raise WebhookProcessingError("Webhook body must be a JSON object.")
    return parsed


def apply_provider_webhook(
    *,
    raw_body: bytes,
    signature_header: str | None,
) -> PaymentTransaction:
    """
    Verify signature, lock payment row, apply status transition and ledger under one atomic block.

    Idempotent for SUCCESS replays and duplicate deliveries.
    """
    secret = getattr(settings, "PAYMENTS_WEBHOOK_SECRET", "") or ""
    verify_webhook_signature(secret, raw_body, signature_header)

    payload = parse_webhook_json(raw_body)
    transaction_id = payload.get("transaction_id")
    status_raw = payload.get("status")

    if not isinstance(transaction_id, str) or not transaction_id.strip():
        raise WebhookProcessingError("transaction_id is required.")

    incoming_status = _normalize_provider_status(status_raw)

    with transaction.atomic():
        pt = (
            PaymentTransaction.objects.select_for_update()
            .filter(provider_reference=transaction_id.strip())
            .first()
        )
        if pt is None:
            raise WebhookProcessingError("Unknown transaction_id.", code="not_found")

        if pt.status == PaymentTransactionStatus.SUCCESS:
            return pt

        if incoming_status == PaymentTransactionStatus.SUCCESS:
            if pt.status != PaymentTransactionStatus.PENDING:
                return pt
            pt.status = PaymentTransactionStatus.SUCCESS
            pt.save(update_fields=["status", "updated_at"])
            append_balanced_entries_for_success(pt)
            return pt

        # FAILED path
        if pt.status == PaymentTransactionStatus.SUCCESS:
            return pt
        if pt.status == PaymentTransactionStatus.FAILED:
            return pt
        pt.status = PaymentTransactionStatus.FAILED
        pt.save(update_fields=["status", "updated_at"])
        return pt
