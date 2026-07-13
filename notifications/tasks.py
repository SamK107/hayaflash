"""Taches Celery pour les notifications."""

from __future__ import annotations

import logging

from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(name="notifications.send_order_confirmation", ignore_result=True)
def send_order_confirmation(order_id: int) -> None:
    """Envoie une confirmation SMS apres creation de commande."""
    from orders.models import Order
    from notifications.services.dispatcher import send_notification

    try:
        order = (
            Order.service_objects.select_related("flash_sale")
            .prefetch_related("items")
            .get(pk=order_id)
        )
    except Order.DoesNotExist:
        logger.warning("Order %s introuvable pour notification", order_id)
        return

    total = int(order.total_amount) if order.total_amount else 0
    message = (
        f"HayaFlash — Commande #{order.pk} enregistree !\n"
        f"Total : {total:,} FCFA\n"
        f"Paiement a la livraison. Merci {order.customer_name} !"
    )
    send_notification(
        recipient_phone=order.customer_phone,
        message=message,
        channel="sms",
    )
    logger.info("Notification envoyee pour commande #%s", order_id)


@shared_task(name="notifications.send_sale_reminder", ignore_result=True)
def send_sale_reminder(flash_sale_id: int, phone: str) -> None:
    """Rappel SMS 1h avant l'ouverture d'une vente."""
    from flash_sales.models import FlashSale
    from notifications.services.dispatcher import send_notification

    try:
        sale = FlashSale.objects.get(pk=flash_sale_id)
    except FlashSale.DoesNotExist:
        logger.warning("FlashSale %s introuvable pour rappel", flash_sale_id)
        return

    message = (
        f"HayaFlash — Rappel !\n"
        f"La vente {sale.title} commence dans 1 heure !\n"
        f"Lien : https://hayaflash.com/f/{sale.public_slug}/"
    )
    send_notification(recipient_phone=phone, message=message, channel="sms")
