"""Masquage du jeton des liens privés du programme partenaires dans les journaux (F-109).

Le jeton fait partie de l'URL `/partenaires/d/<jeton>/` : tout journal qui reprend un chemin, une ligne de requête
ou un Referer le contiendrait. Ce module est sans dépendance (ni Django ni Gunicorn) : il sert au filtre de
journalisation de Django, au journal d'accès Gunicorn (config/gunicorn_logging.py) et à ses tests.
"""

from __future__ import annotations

import logging
import re

MASK = "***"
# Le jeton va jusqu'au prochain « / », espace, « ? », « # » ou guillemet.
PRIVATE_TOKEN_RE = re.compile(r"(/partenaires/d/)[^/\s?#\"']+")


def mask_private_tokens(value):
    """Remplace le jeton par `***` dans une chaîne ; toute autre valeur est rendue telle quelle."""
    if isinstance(value, str):
        return PRIVATE_TOKEN_RE.sub(r"\g<1>" + MASK, value)
    return value


class MaskPrivateTokensFilter(logging.Filter):
    """Filtre de journalisation : masque le jeton dans le message et ses arguments. Ne supprime jamais un
    enregistrement et ne lève jamais."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = mask_private_tokens(record.msg)
            args = record.args
            if isinstance(args, tuple):
                record.args = tuple(mask_private_tokens(a) for a in args)
            elif isinstance(args, dict):
                record.args = {k: mask_private_tokens(v) for k, v in args.items()}
        except Exception:  # noqa: BLE001 -- un filtre de journal ne doit jamais casser une requête
            pass
        return True
