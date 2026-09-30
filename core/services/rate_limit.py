"""Limite de debit simple sur le cache Django (Redis en prod, LocMem en test).

Principe : ne jamais bloquer un vrai vendeur a tort.
- fail-open : si le cache est indisponible (Redis tombe), on journalise et on
  laisse passer ;
- cles prefixees ``rl:`` ; un numero de telephone n'apparait jamais en clair
  dans une cle (sha256 tronque, voir ``phone_key``).

Modele de reference : ``orders/services/client_order.py``
(``enforce_public_order_rate_limit``), lu mais ni importe ni modifie.
"""

from __future__ import annotations

import hashlib
import logging
import re

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest

from core.services.client_ip import get_client_ip

logger = logging.getLogger(__name__)

KEY_PREFIX = "rl:"

LOGIN_RATE_LIMIT_MESSAGE = "Trop de tentatives. Réessayez dans quelques minutes."
REGISTER_RATE_LIMIT_MESSAGE = "Trop d'inscriptions depuis ce réseau. Réessayez plus tard."
ORDER_RATE_LIMIT_MESSAGE = "Trop de commandes avec ce numéro. Réessayez dans quelques minutes."


def phone_key(scope: str, normalized_phone: str) -> str:
    """Cle ``<scope>:phone:<sha256 tronque>`` : jamais le numero en clair."""
    digest = hashlib.sha256(normalized_phone.encode("utf-8")).hexdigest()[:16]
    return f"{scope}:phone:{digest}"


def hit(key: str, *, limit: int, window_seconds: int) -> bool:
    """Compte une tentative ; True si la limite est DEPASSEE (> limit).

    La fenetre demarre a la 1re tentative (cache.add ne remet pas le
    compteur a zero s'il existe deja).
    """
    full_key = KEY_PREFIX + key
    try:
        cache.add(full_key, 0, window_seconds)
        try:
            count = cache.incr(full_key)
        except ValueError:
            # Cle expiree entre add() et incr() : on repart d'une fenetre neuve.
            cache.set(full_key, 1, window_seconds)
            count = 1
    except Exception:
        logger.warning("Rate limit indisponible (cache) : %s laisse passer.", key.split(":")[0], exc_info=True)
        return False
    return count > limit


def is_limited(key: str, *, limit: int) -> bool:
    """Lecture seule : True si le compteur a deja atteint ``limit``."""
    try:
        count = cache.get(KEY_PREFIX + key) or 0
    except Exception:
        logger.warning("Rate limit indisponible (cache) : %s laisse passer.", key.split(":")[0], exc_info=True)
        return False
    return count >= limit


def reset(key: str) -> None:
    """Remet le compteur a zero (ex. apres une connexion reussie)."""
    try:
        cache.delete(KEY_PREFIX + key)
    except Exception:
        logger.warning("Rate limit indisponible (cache) : reset ignore.", exc_info=True)


# ── Limites applicatives (valeurs : settings.RATELIMIT_*) ─────────────────────
# Desactivables globalement par settings.RATELIMIT_ENABLE (tests). Les cles
# login/register sont partagees entre le formulaire HTML et l'API DRF : changer
# de route ne donne pas un second quota.


def _limited(key: str, setting: str) -> bool:
    if not settings.RATELIMIT_ENABLE:
        return False
    limit, window = getattr(settings, setting)
    return hit(key, limit=limit, window_seconds=window)


def login_ip_limited(request: HttpRequest) -> bool:
    return _limited(f"login:ip:{get_client_ip(request)}", "RATELIMIT_LOGIN_IP")


def register_ip_limited(request: HttpRequest) -> bool:
    return _limited(f"register:ip:{get_client_ip(request)}", "RATELIMIT_REGISTER_IP")


def order_phone_limited(phone: str) -> bool:
    """Limite par acheteur. Cle = 8 derniers chiffres (numero malien local) :
    ``+22370000001``, ``70 00 00 01`` et ``0022370000001`` partagent un quota."""
    digits = re.sub(r"\D", "", phone)[-8:] or phone
    return _limited(phone_key("order", digits), "RATELIMIT_ORDER_PHONE")
