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

from django.core.cache import cache

logger = logging.getLogger(__name__)

KEY_PREFIX = "rl:"


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
