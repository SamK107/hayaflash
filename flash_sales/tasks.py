"""Taches Celery pour la gestion automatique des ventes flash."""

from __future__ import annotations

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


def _record_open_refusal(sale, reason: str) -> None:
    """Journalise (une seule fois) le refus d'ouverture automatique d'une vente."""
    from core.models import AuditLog, audit

    action = "flashsale.open_refused"
    already = AuditLog.objects.filter(
        action=action, entity_type="FlashSale", entity_id=sale.pk
    ).exists()
    if already:
        return
    logger.warning(
        "FlashSale %s [%s] ouverture auto REFUSEE (vendeur %s) : %s",
        sale.pk,
        sale.title,
        sale.owner_id,
        reason,
    )
    audit(action, entity_type="FlashSale", entity_id=sale.pk, reason=reason)


@shared_task(name="flash_sales.auto_open_scheduled_sales", ignore_result=True)
def auto_open_scheduled_sales() -> None:
    """Ouvre automatiquement les ventes dont start_time est atteint."""
    from flash_sales.models import FlashSale, FlashSaleStatus, SaleOpeningRefused

    now = timezone.now()
    to_open = FlashSale.objects.filter(
        status=FlashSaleStatus.SCHEDULED,
        start_time__lte=now,
        end_time__gt=now,
    )
    count = 0
    for sale in to_open:
        try:
            sale.open_sale()
            count += 1
            logger.info(
                "FlashSale %s [%s] SCHEDULED -> LIVE (auto)", sale.pk, sale.title
            )
        except SaleOpeningRefused as exc:
            # Regle metier (quota, 3/jour, duree) : la vente reste SCHEDULED.
            # Beat repasse chaque minute : on ne trace qu'une fois par vente.
            _record_open_refusal(sale, str(exc))
        except Exception as exc:
            logger.error("Erreur ouverture auto FlashSale %s : %s", sale.pk, exc)

    if count:
        logger.info("auto_open_scheduled_sales : %d vente(s) ouvertes", count)


@shared_task(name="flash_sales.auto_close_live_sales", ignore_result=True)
def auto_close_live_sales() -> None:
    """Ferme automatiquement les ventes dont end_time est atteint."""
    from flash_sales.models import FlashSale, FlashSaleStatus

    now = timezone.now()
    to_close = FlashSale.objects.filter(
        status=FlashSaleStatus.LIVE,
        end_time__lte=now,
    )
    count = 0
    for sale in to_close:
        try:
            sale.close_sale()
            count += 1
            logger.info("FlashSale %s [%s] LIVE -> CLOSED (auto)", sale.pk, sale.title)
        except Exception as exc:
            logger.error("Erreur fermeture auto FlashSale %s : %s", sale.pk, exc)

    if count:
        logger.info("auto_close_live_sales : %d vente(s) fermees", count)


@shared_task(name="flash_sales.send_pending_sale_reminders", ignore_result=True)
def send_pending_sale_reminders() -> None:
    """
    Envoie un rappel SMS aux inscrits (SaleInterest) dont la vente programmée
    ouvre dans l'heure qui vient, et qui n'ont pas encore été relancés.

    Idempotent : chaque SaleInterest n'est relancé qu'une seule fois grâce au
    champ `reminded_at`.
    """
    from flash_sales.models import FlashSaleStatus, SaleInterest
    from notifications.tasks import send_sale_reminder

    now = timezone.now()
    window_end = now + timedelta(hours=1)

    pending = SaleInterest.objects.filter(
        reminded_at__isnull=True,
        flash_sale__status=FlashSaleStatus.SCHEDULED,
        flash_sale__start_time__gt=now,
        flash_sale__start_time__lte=window_end,
    ).select_related("flash_sale")

    count = 0
    for interest in pending:
        try:
            send_sale_reminder.delay(interest.flash_sale_id, interest.phone)
            interest.reminded_at = now
            interest.save(update_fields=["reminded_at"])
            count += 1
        except Exception as exc:
            logger.error(
                "Erreur envoi rappel SaleInterest %s (vente %s) : %s",
                interest.pk,
                interest.flash_sale_id,
                exc,
            )

    if count:
        logger.info("send_pending_sale_reminders : %d rappel(s) envoye(s)", count)
