"""Validation des fichiers uploades (F-02).

Trois controles sur chaque champ : extension (liste blanche), taille max, et
CONTENU reel (signature binaire) -- le `content_type` declare par le client est
falsifiable et n'est jamais utilise.

Les validateurs de champ ne tournent qu'a `full_clean()` (formulaires, admin,
serializers) : tout code qui ecrit un fichier sans `full_clean()` doit appeler
`validate_file_field()`.
"""

from __future__ import annotations

import os

from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.utils.deconstruct import deconstructible

MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 Mo (aligne sur FILE_UPLOAD_MAX_MEMORY_SIZE)
# Meme plafond que les images, volontairement sous `client_max_body_size 10M`
# (Nginx) : Django rejette proprement avant qu'un 413 brut n'arrive.
MAX_AUDIO_BYTES = MAX_IMAGE_BYTES

IMAGE_EXTENSIONS = ("jpg", "jpeg", "png", "webp")
AUDIO_EXTENSIONS = ("webm", "ogg", "mp3", "m4a", "wav")

# Formats reels acceptes (verifies par Pillow). Pas de correspondance stricte
# extension <-> format pour les images : les telephones/OS renomment souvent
# (.jpg contenant du PNG) ; l'extension reste sur liste blanche et le contenu
# doit etre une vraie image d'un de ces formats.
_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}


def _mo(n: int) -> str:
    return f"{n / (1024 * 1024):g} Mo"


@deconstructible
class MaxFileSizeValidator:
    def __init__(self, max_bytes: int):
        self.max_bytes = max_bytes

    def __call__(self, file) -> None:
        if file.size > self.max_bytes:
            raise ValidationError(
                f"Fichier trop volumineux (maximum {_mo(self.max_bytes)}).",
                code="file_too_large",
            )

    def __eq__(self, other) -> bool:
        return isinstance(other, MaxFileSizeValidator) and other.max_bytes == self.max_bytes


def _head(file, n: int = 16) -> bytes:
    try:
        file.seek(0)
        data = file.read(n)
        file.seek(0)
    except (AttributeError, ValueError, OSError):
        return b""
    return data if isinstance(data, bytes) else b""


def _audio_kind(head: bytes) -> str | None:
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "webm"
    if head.startswith(b"OggS"):
        return "ogg"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "wav"
    if head[4:8] == b"ftyp":
        return "m4a"
    if head.startswith(b"ID3") or (
        len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0
    ):
        return "mp3"
    return None


def validate_audio_content(file) -> None:
    """La signature binaire doit correspondre a l'extension annoncee."""
    ext = os.path.splitext(file.name or "")[1].lower().lstrip(".")
    kind = _audio_kind(_head(file))
    if kind is None or kind != ext:
        raise ValidationError(
            "Le contenu du fichier ne correspond pas à un enregistrement audio valide.",
            code="invalid_audio_content",
        )


def validate_image_content(file) -> None:
    """Pillow doit decoder le fichier et y reconnaitre un format image autorise."""
    from PIL import Image

    try:
        file.seek(0)
        with Image.open(file) as img:
            fmt = img.format
            # load() plutot que verify() : decode reellement les pixels (rejette un
            # fichier tronque/corrompu) sans exiger des CRC PNG parfaits ; le meme
            # decodage est de toute facon fait par core.services.image_optimize.
            img.load()
        file.seek(0)
    except Exception:
        raise ValidationError(
            "Le fichier n'est pas une image valide.", code="invalid_image_content"
        )
    if fmt not in _IMAGE_FORMATS:
        raise ValidationError(
            "Format d'image non accepté (JPEG, PNG ou WebP).",
            code="invalid_image_content",
        )


IMAGE_VALIDATORS = [
    FileExtensionValidator(allowed_extensions=IMAGE_EXTENSIONS),
    MaxFileSizeValidator(MAX_IMAGE_BYTES),
    validate_image_content,
]
AUDIO_VALIDATORS = [
    FileExtensionValidator(allowed_extensions=AUDIO_EXTENSIONS),
    MaxFileSizeValidator(MAX_AUDIO_BYTES),
    validate_audio_content,
]


def validate_file_field(instance, field_name: str, file=None) -> None:
    """Execute les validateurs du champ (pour les chemins d'ecriture sans
    `full_clean()`). Leve `ValidationError`."""
    field = instance._meta.get_field(field_name)
    field.run_validators(file if file is not None else getattr(instance, field_name))
