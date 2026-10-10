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
import hmac
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
REGISTER_PHONE_RATE_LIMIT_MESSAGE = "Trop de tentatives avec ce numéro. Réessayez dans quelques minutes."
ORDER_RATE_LIMIT_MESSAGE = "Trop de commandes avec ce numéro. Réessayez dans quelques minutes."


def _phone_digest(phone: str | None) -> str:
    return hashlib.sha256((phone or "").encode("utf-8")).hexdigest()[:16]


def phone_fingerprint(phone: str | None) -> str:
    """Empreinte ``tel:<sha256 tronque>`` d'un numero, pour les journaux (F-36).

    A utiliser dans tout ``logger.*`` / ``print`` a la place du numero : meme
    empreinte que dans ``phone_key``, donc un incident se recoupe avec les
    compteurs de limitation sans jamais ecrire le numero. Le numero stocke en
    base et le texte du SMS ne sont pas concernes.
    """
    return f"tel:{_phone_digest(phone)}"


def ip_fingerprint(ip: str | None) -> str:
    """Empreinte SALEE d'une IP (HMAC-SHA256 avec SECRET_KEY, tronquee a 16 hex).

    Pour stocker ou comparer une IP sans jamais l'ecrire en clair (programme
    partenaires). Contrairement a ``phone_fingerprint`` (non salee, F-98), elle ne
    se retrouve pas par enumeration sans la cle secrete.
    """
    mac = hmac.new(settings.SECRET_KEY.encode("utf-8"), f"ip:{ip or ''}".encode("utf-8"), hashlib.sha256)
    return mac.hexdigest()[:16]


def phone_key(scope: str, normalized_phone: str) -> str:
    """Cle ``<scope>:phone:<sha256 tronque>`` : jamais le numero en clair."""
    return f"{scope}:phone:{_phone_digest(normalized_phone)}"


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


def referral_ip_limited(request: HttpRequest) -> bool:
    """Limite par IP sur le lien de recommandation /r/<code>/."""
    return _limited(f"referral:ip:{get_client_ip(request)}", "RATELIMIT_REFERRAL_IP")


def partner_link_ip_limited(request: HttpRequest) -> bool:
    """Limite par IP sur les pages publiques par lien prive des partenaires."""
    return _limited(f"partnerlink:ip:{get_client_ip(request)}", "RATELIMIT_PARTNER_LINK_IP")


def login_ip_limited(request: HttpRequest) -> bool:
    return _limited(f"login:ip:{get_client_ip(request)}", "RATELIMIT_LOGIN_IP")


def register_ip_limited(request: HttpRequest) -> bool:
    return _limited(f"register:ip:{get_client_ip(request)}", "RATELIMIT_REGISTER_IP")


def register_phone_limited(normalized_phone: str) -> bool:
    """Limite par numero a l'inscription (F-15). Meme reponse que le numero
    existe ou non : le compteur ne depend que de la saisie."""
    return _limited(phone_key("register", normalized_phone), "RATELIMIT_REGISTER_PHONE")


def order_phone_limited(phone: str) -> bool:
    """Limite par acheteur. Cle = 8 derniers chiffres (numero malien local) :
    ``+22370000001``, ``70 00 00 01`` et ``0022370000001`` partagent un quota."""
    digits = re.sub(r"\D", "", phone)[-8:] or phone
    return _limited(phone_key("order", digits), "RATELIMIT_ORDER_PHONE")
