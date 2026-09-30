"""Anti-bot des formulaires publics : champ piege + horodatage signe.

Deux signaux, tous deux rejetes avec le MEME message generique (l'appelant ne
dit jamais pourquoi) :
- champ piege (``website``) rempli : un humain ne le voit pas, un robot le remplit ;
- jeton d'affichage (``form_ts``, signe par ``django.core.signing``) absent,
  altere, expire (> 2 h) ou soumis trop vite (< 3 s apres l'affichage).

Utilisation : ``{% honeypot_fields %}`` (templatetag ``hf_honeypot``) dans le
``<form>``, puis ``honeypot.is_bot_submission(request.POST)`` dans la vue.
"""

from __future__ import annotations

import logging
import time
from typing import Mapping

from django.core import signing

logger = logging.getLogger(__name__)

HONEYPOT_FIELD = "website"
TIMESTAMP_FIELD = "form_ts"
MIN_FILL_SECONDS = 3
MAX_AGE_SECONDS = 2 * 60 * 60
SALT = "hayaflash.honeypot.v1"

GENERIC_ERROR = (
    "Impossible de créer le compte pour le moment. Vérifiez vos informations et réessayez."
)


def make_token(issued_at: float | None = None) -> str:
    """Jeton signe portant l'heure d'affichage (``issued_at`` : tests uniquement)."""
    return signing.dumps({"t": time.time() if issued_at is None else issued_at}, salt=SALT)


def rejection_reason(data: Mapping[str, str]) -> str | None:
    """Code interne du rejet (journaux seulement), ou None si la soumission est saine."""
    if (data.get(HONEYPOT_FIELD) or "").strip():
        return "trap_filled"
    token = data.get(TIMESTAMP_FIELD) or ""
    try:
        payload = signing.loads(token, salt=SALT, max_age=MAX_AGE_SECONDS)
        issued_at = float(payload["t"])
    except signing.SignatureExpired:
        return "token_expired"
    except (signing.BadSignature, KeyError, TypeError, ValueError):
        return "token_invalid"
    if time.time() - issued_at < MIN_FILL_SECONDS:
        return "too_fast"
    return None


def is_bot_submission(data: Mapping[str, str]) -> bool:
    return rejection_reason(data) is not None
