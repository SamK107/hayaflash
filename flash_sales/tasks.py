"""Taches Celery pour la gestion automatique des ventes flash."""
from __future__ import annotations

import logging

from celery import shared_task
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="flash_sales.auto_open_scheduled_sales", ignore_result=True)
def auto_open_scheduled_sales() -> None:
    """Ouvre automatiquement les ventes dont start_time est atteint."""
    from flash_sales.models import FlashSale, FlashSaleStatus

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
            logger.info("FlashSale %s [%s] SCHEDULED -> LIVE (auto)", sale.pk, sale.title)
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
