"""Dispatcher central de notifications."""

import logging

from django.utils import timezone

from notifications.models import Notification

logger = logging.getLogger(__name__)


def send_notification(
    *,
    recipient_phone: str,
    message: str,
    channel: str = Notification.Channel.SMS,
) -> Notification:
    """Cree et envoie une notification. Retourne l'objet Notification."""
    notif = Notification.objects.create(
        recipient_phone=recipient_phone,
        channel=channel,
        message=message,
    )
    success = False
    try:
        if channel == Notification.Channel.SMS:
            from .sms import send_sms

            success = send_sms(recipient_phone, message)
        elif channel == Notification.Channel.WHATSAPP:
            # WhatsApp Business API — V1.1
            # En V1 : log uniquement, le lien wa.me est utilise cote client
            logger.info(
                "WhatsApp (V1 log only) -> %s : %s", recipient_phone, message[:80]
            )
            success = True
        else:
            logger.warning("Canal inconnu : %s", channel)

        notif.status = (
            Notification.Status.SENT if success else Notification.Status.FAILED
        )
        notif.sent_at = timezone.now() if success else None
        notif.save(update_fields=["status", "sent_at", "updated_at"])
    except Exception as exc:
        notif.status = Notification.Status.FAILED
        notif.error_message = str(exc)[:500]
        notif.save(update_fields=["status", "error_message", "updated_at"])

    return notif
