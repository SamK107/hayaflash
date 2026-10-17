"""Miniatures WebP generees a la demande pour les pages publiques legeres (Marche).

Les photos produits sont stockees a 1600 px max (``image_optimize``) : trop
lourdes pour une vitrine sur 3G. Une miniature (200 px vignettes, 480 px image
principale) est creee au premier besoin a cote de l'original
(``<dossier>/thumbs/<taille>/<nom>.webp``) puis reutilisee : aucune migration,
aucun champ de modele. Les dimensions sont mises en cache (1 jour) pour ne pas
rouvrir le fichier a chaque calcul du snapshot.

Best-effort : en cas d'echec (fichier absent, format illisible) on renvoie None
et l'appelant affiche un bloc de couleur ; l'original n'est jamais servi.
"""

from __future__ import annotations

import io
import logging
import posixpath

from django.core.cache import cache
from django.core.files.base import ContentFile

logger = logging.getLogger(__name__)

THUMB_SMALL = 200
THUMB_MAIN = 480
THUMB_SIZES = (THUMB_SMALL, THUMB_MAIN)
WEBP_QUALITY = 78
_OK_TTL = 86400
_FAIL_TTL = 300


def thumbnail_name(name: str, size: int) -> str:
    directory, base = posixpath.split(name.replace("\\", "/"))
    stem = posixpath.splitext(base)[0]
    return posixpath.join(directory, "thumbs", str(size), f"{stem}.webp")


def _cache_key(name: str, size: int) -> str:
    return f"hf:thumb:{size}:{name}"


def _generate(field_file, target: str, size: int) -> dict:
    from PIL import Image, ImageOps

    storage = field_file.storage
    if not storage.exists(target):
        with storage.open(field_file.name, "rb") as fh:
            img = Image.open(fh)
            img = ImageOps.exif_transpose(img)
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            img.thumbnail((size, size), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, "WEBP", quality=WEBP_QUALITY, method=4)
        storage.save(target, ContentFile(buf.getvalue()))
    with storage.open(target, "rb") as fh:
        width, height = Image.open(fh).size
    return {"url": storage.url(target), "width": width, "height": height}


def get_thumbnail(field_file, size: int) -> dict | None:
    """``{"url", "width", "height"}`` de la miniature WebP, ou None."""
    if not field_file or not field_file.name:
        return None
    key = _cache_key(field_file.name, size)
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    try:
        info = _generate(field_file, thumbnail_name(field_file.name, size), size)
    except Exception:  # noqa: BLE001 - best-effort, jamais bloquant
        logger.warning("thumbnail failed name=%s size=%s", field_file.name, size, exc_info=True)
        cache.set(key, {}, _FAIL_TTL)
        return None
    cache.set(key, info, _OK_TTL)
    return info


def delete_thumbnails(field_file) -> None:
    """Supprime les miniatures d'un fichier (avant la suppression de l'original)."""
    if not field_file or not field_file.name:
        return
    for size in THUMB_SIZES:
        try:
            field_file.storage.delete(thumbnail_name(field_file.name, size))
        except Exception:  # noqa: BLE001
            logger.warning("thumbnail delete failed name=%s", field_file.name, exc_info=True)
        cache.delete(_cache_key(field_file.name, size))
