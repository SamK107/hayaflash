"""Inscrits « M'alerter » a prevenir pour la prochaine vente d'un vendeur (F-81).

Les ``SaleInterest`` restent lies a la vente visitee (souvent terminee). Ce service
les regroupe par vendeur, tous statuts de vente confondus, dedoublonnes par numero
normalise. Aucun envoi automatique : le vendeur contacte lui-meme chaque inscrit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from accounts.services.users import normalize_phone
from flash_sales.models import FlashSale, FlashSaleStatus, SaleInterest

# Numero local malien a 8 chiffres (ex. « 70 00 00 01 ») -> indicatif du Mali.
DEFAULT_COUNTRY_CODE = "223"
LOCAL_NUMBER_LENGTH = 8
_SEPARATORS_RE = re.compile(r"[\s().\-]")


@dataclass(frozen=True)
class Invitee:
    name: str
    phone: str  # tel que saisi (le plus recent)
    phone_e164: str | None  # chiffres seuls, sans « + », None si a verifier
    signed_up_at: datetime


def normalize_whatsapp_number(raw: str) -> str | None:
    """Numero au format wa.me (E.164 sans « + »), ou None s'il est inexploitable."""
    if not isinstance(raw, str):
        return None
    cleaned = _SEPARATORS_RE.sub("", normalize_phone(raw))
    if cleaned.startswith("+"):
        digits = cleaned[1:]
    elif cleaned.startswith("00"):
        digits = cleaned[2:]
    elif cleaned.isdigit() and len(cleaned) == LOCAL_NUMBER_LENGTH:
        digits = DEFAULT_COUNTRY_CODE + cleaned
    else:
        return None
    if not digits.isdigit() or not 10 <= len(digits) <= 15:
        return None
    return digits


def next_scheduled_sale(seller, *, now: datetime | None = None) -> FlashSale | None:
    """Prochaine vente programmee du vendeur (la plus proche), ou None."""
    now = now or timezone.now()
    return (
        FlashSale.objects.filter(
            owner=seller, status=FlashSaleStatus.SCHEDULED, end_time__gt=now
        )
        .order_by("start_time")
        .first()
    )


def interests_to_notify(seller) -> list[Invitee]:
    """Inscrits du vendeur (toutes ses ventes), un par numero, les plus recents d'abord."""
    rows = SaleInterest.objects.filter(flash_sale__owner=seller).order_by(
        "-created_at", "-pk"
    )
    seen: dict[str, dict] = {}
    for row in rows:  # du plus recent au plus ancien
        e164 = normalize_whatsapp_number(row.phone)
        key = e164 or _SEPARATORS_RE.sub("", row.phone)
        entry = seen.get(key)
        if entry is None:
            seen[key] = {
                "name": row.name,
                "phone": row.phone,
                "e164": e164,
                "at": row.created_at,
            }
        elif not entry["name"] and row.name:
            entry["name"] = row.name  # garde un nom si une inscription plus ancienne en a un
    return [
        Invitee(name=e["name"], phone=e["phone"], phone_e164=e["e164"], signed_up_at=e["at"])
        for e in seen.values()
    ]
