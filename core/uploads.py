"""Noms de fichiers uploades generes cote serveur (F-03).

Le nom fourni par le client n'est jamais conserve (caracteres dangereux,
donnees personnelles, collisions) : nom aleatoire, extension d'origine
(minuscule, alphanumerique) conservee pour que le type servi reste correct.
"""

from __future__ import annotations

import os
import re
import uuid

from django.utils import timezone
from django.utils.deconstruct import deconstructible


@deconstructible
class RandomUploadPath:
    """`upload_to` appelable : `<directory>[/YYYY/MM/DD]/<uuid4 hex>.<ext>`."""

    def __init__(self, directory: str, dated: bool = False):
        self.directory = directory.strip("/")
        self.dated = dated

    def __call__(self, instance, filename: str) -> str:
        ext = os.path.splitext(filename or "")[1].lower().lstrip(".")
        ext = re.sub(r"[^a-z0-9]", "", ext)[:10]
        name = uuid.uuid4().hex + (f".{ext}" if ext else "")
        parts = [self.directory]
        if self.dated:
            parts.append(timezone.now().strftime("%Y/%m/%d"))
        parts.append(name)
        return "/".join(parts)
