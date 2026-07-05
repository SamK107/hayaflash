from __future__ import annotations

import os
import uuid

from django.conf import settings

from payments.models import PaymentTransaction, PaymentTransactionStatus


def _simulate_failure() -> bool:
    raw = getattr(
        settings,
        "PAYMENTS_MOCK_SIMULATE_FAILURE",
        None,
    )
    if raw is not None:
        return bool(raw)
    return os.environ.get("PAYMENTS_MOCK_SIMULATE_FAILURE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def initiate_mock_charge(transaction: PaymentTransaction, phone: str) -> dict[str, str]:
    """
    Fake Mobile Money initiation.

    Assigns a deterministic-looking ``provider_reference`` and optionally marks the
    transaction failed immediately (testing only).
    """
    provider_reference = f"mock-{transaction.id.hex[:12]}-{uuid.uuid4().hex[:8]}"
    transaction.provider_reference = provider_reference

    if _simulate_failure():
        transaction.status = PaymentTransactionStatus.FAILED
        transaction.save(
            update_fields=["provider_reference", "status", "updated_at"],
        )
        return {
            "provider_reference": provider_reference,
            "status": PaymentTransactionStatus.FAILED,
            "detail": "mock_provider simulated failure",
        }

    transaction.save(update_fields=["provider_reference", "updated_at"])
    return {
        "provider_reference": provider_reference,
        "status": PaymentTransactionStatus.PENDING,
        "detail": "mock_provider pending; POST webhook to finalize",
        "phone_hint": phone[-4:] if len(phone) >= 4 else phone,
    }
