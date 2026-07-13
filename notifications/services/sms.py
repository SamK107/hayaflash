"""Service SMS — Orange SMS Gateway Mali."""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def send_sms(phone: str, message: str) -> bool:
    """Envoie un SMS via la gateway Orange Mali."""
    api_key = getattr(settings, "ORANGE_SMS_API_KEY", "").strip()
    base_url = getattr(settings, "ORANGE_SMS_BASE_URL", "").strip()

    if not api_key or not base_url:
        logger.warning(
            "SMS non configure (ORANGE_SMS_API_KEY ou ORANGE_SMS_BASE_URL manquant) "
            "— SMS non envoye a %s",
            phone,
        )
        return False

    try:
        resp = requests.post(
            f"{base_url}/sms/send",
            json={"recipient": phone, "message": message},
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("SMS envoye a %s", phone)
        return True
    except Exception as exc:
        logger.error("Erreur envoi SMS a %s : %s", phone, exc)
        return False
