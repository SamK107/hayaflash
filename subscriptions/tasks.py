"""Taches Celery des abonnements."""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)

# Au-dela, Orange considere le paiement expire : inutile de l'interroger.
PENDING_CHECK_WINDOW = timedelta(hours=24)


@shared_task(name="subscriptions.check_pending_orange_payments", ignore_result=True)
def check_pending_orange_payments() -> dict:
    """Verifie aupres d'Orange les paiements en attente de moins de 24 h.

    Filet de securite du webhook (planifie toutes les 5 min, voir
    CELERY_BEAT_SCHEDULE) : un paiement reussi dont le webhook n'est jamais
    arrive est active quand meme, avec la meme activation idempotente.
    Un paiement en echec n'arrete pas les suivants.
    """
    from subscriptions.models import PaymentProvider, PaymentStatus, SubscriptionPayment
    from subscriptions.services.payment import sync_orange_payment_status

    since = timezone.now() - PENDING_CHECK_WINDOW
    pending = SubscriptionPayment.objects.filter(
        status=PaymentStatus.PENDING,
        provider=PaymentProvider.ORANGE,
        created_at__gte=since,
    ).order_by("created_at")

    counts: dict[str, int] = {}
    for payment in pending:
        try:
            status = sync_orange_payment_status(payment, source="celery") or "UNCHECKED"
        except Exception:  # garde-fou : sync ne leve pas, mais on ne s'arrete jamais
            logger.exception("check_pending_orange_payments : order_id=%s", payment.order_id)
            status = "ERROR"
        counts[status] = counts.get(status, 0) + 1

    if counts:
        logger.info("check_pending_orange_payments : %s", counts)
    return counts
