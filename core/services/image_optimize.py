"""
Redimensionnement best-effort des images uploadées (couvertures de vente,
photos produits) avant écriture en storage.

Objectif : éviter de servir aux clients (souvent en 3G/4G) une photo prise
telle quelle par un smartphone (parfois 10-15 Mpx / plusieurs Mo) alors que la
plus grande taille d'affichage réelle sur le site fait quelques centaines de
pixels de large.

Design volontairement conservateur, à l'image du reste du code (cf.
`delivery._attach_audio_note()` pour l'audio client) :
- best-effort : un échec de traitement ne bloque JAMAIS la sauvegarde du
  modèle — on logge et on garde le fichier original tel quel.
- idempotent : si l'image est déjà sous la taille cible, on ne touche à rien
  (sûr même si la fonction est appelée plusieurs fois sur le même fichier).
- ne change pas le format d'origine (une image PNG reste un PNG, une image
  JPEG reste une JPEG) pour ne pas modifier de comportement ailleurs
  (transparence, urls, content-type) au-delà de la taille du fichier.
"""

from __future__ import annotations

import io
import logging

from django.core.files.base import ContentFile
from django.db.models.fields.files import FieldFile

logger = logging.getLogger(__name__)

DEFAULT_MAX_DIMENSION = 1600  # px, sur le plus grand côté
DEFAULT_JPEG_QUALITY = 82


def resize_uploaded_image(
    field_file: FieldFile,
    *,
    max_dimension: int = DEFAULT_MAX_DIMENSION,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
) -> None:
    """
    Redimensionne `field_file` en place (avant écriture en storage) si sa plus
    grande dimension dépasse `max_dimension`. No-op silencieux si :
    - il n'y a pas de fichier,
    - le fichier est déjà dans les clous,
    - Pillow n'arrive pas à l'ouvrir/le traiter (ne bloque jamais l'upload).

    À appeler uniquement sur un fichier fraîchement assigné et pas encore
    committé en storage (``field_file._committed is False``), avant
    ``super().save()`` du modèle.
    """
    if not field_file:
        return

    try:
        from PIL import Image, ImageOps
    except ImportError:
        logger.warning("Pillow indisponible — image non redimensionnée.")
        return

    try:
        field_file.seek(0)
        image = Image.open(field_file)
        image.load()
    except Exception:
        logger.exception(
            "Image illisible, redimensionnement ignoré (fichier conservé tel quel)."
        )
        return

    try:
        width, height = image.size
        if max(width, height) <= max_dimension:
            return  # déjà sous la taille cible — no-op

        # Respecte l'orientation EXIF avant de redimensionner (sinon une
        # photo prise en portrait sur mobile peut ressortir pivotée).
        image = ImageOps.exif_transpose(image)

        original_format = (image.format or "JPEG").upper()
        image.thumbnail((max_dimension, max_dimension), Image.LANCZOS)

        buffer = io.BytesIO()
        save_kwargs = {}
        if original_format in ("JPEG", "JPG"):
            if image.mode not in ("RGB", "L"):
                image = image.convert("RGB")
            save_kwargs = {"quality": jpeg_quality, "optimize": True}
            original_format = "JPEG"
        elif original_format == "PNG":
            save_kwargs = {"optimize": True}
        elif original_format == "WEBP":
            save_kwargs = {"quality": jpeg_quality}

        image.save(buffer, format=original_format, **save_kwargs)
        buffer.seek(0)

        name = field_file.name
        field_file.file = ContentFile(buffer.read())
        field_file.name = name
    except Exception:
        logger.exception(
            "Échec du redimensionnement, fichier original conservé tel quel."
        )


def is_pending_upload(field_file: FieldFile) -> bool:
    """
    True si `field_file` porte un fichier fraîchement assigné (formulaire,
    admin, management command) qui n'a pas encore été écrit en storage.
    Permet de ne traiter que les nouveaux uploads, jamais les instances
    rechargées depuis la base (évite un retraitement inutile à chaque save()).
    """
    return bool(field_file) and getattr(field_file, "_committed", True) is False
