"""Service SMS — Orange SMS Gateway Mali."""

import logging

import requests
from django.conf import settings

from core.services.rate_limit import phone_fingerprint

logger = logging.getLogger(__name__)


def sms_enabled() -> bool:
    """Vrai seulement si les SMS sont explicitement actives (inactifs au lancement, D3)."""
    return bool(getattr(settings, "SMS_NOTIFICATIONS_ENABLED", False))


def send_sms(phone: str, message: str) -> bool:
    """Envoie un SMS via la gateway Orange Mali (inactif par defaut, voir sms_enabled)."""
    if not sms_enabled():
        return False
    api_key = getattr(settings, "ORANGE_SMS_API_KEY", "").strip()
    base_url = getattr(settings, "ORANGE_SMS_BASE_URL", "").strip()

    if not api_key or not base_url:
        logger.warning(
            "SMS non configure (ORANGE_SMS_API_KEY ou ORANGE_SMS_BASE_URL manquant) "
            "— SMS non envoyé à %s",
            phone_fingerprint(phone),
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
        logger.info("SMS envoye a %s", phone_fingerprint(phone))
        return True
    except Exception as exc:
        # Le texte de l'exception peut contenir le numero : type seulement.
        logger.error(
            "Erreur envoi SMS a %s : %s", phone_fingerprint(phone), type(exc).__name__
        )
        return False
