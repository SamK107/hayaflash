"""Inscrits « M'alerter » a prevenir pour la prochaine vente d'un vendeur (F-81).

Les ``SaleInterest`` restent lies a la vente visitee (souvent terminee). Ce service
les regroupe par vendeur, tous statuts de vente confondus, dedoublonnes par numero
normalise. Aucun envoi automatique : le vendeur contacte lui-meme chaque inscrit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from urllib.parse import quote

from django.utils import timezone
from django.utils.formats import date_format

from accounts.services.users import normalize_phone
from flash_sales.models import FlashSale, FlashSaleStatus, SaleInterest

_SEPARATORS_RE = re.compile(r"[\s().\-]")


@dataclass(frozen=True)
class Invitee:
    name: str
    phone: str  # tel que saisi (le plus recent)
    phone_e164: str | None  # chiffres seuls, sans « + », None si a verifier
    signed_up_at: datetime
    key: str = ""  # cle de dedoublonnage (numero normalise, ou numero brut sans separateurs)
    contacted_at: datetime | None = None  # inscription la plus recente

    @property
    def dom_id(self) -> str:
        return re.sub(r"\W", "", self.key)


def normalize_whatsapp_number(raw: str) -> str | None:
    """Numero au format wa.me (E.164 sans « + »), ou None s'il est inexploitable.

    Seul un numero deja international (+… ou 00…) donne un lien : on ne devine
    jamais un pays a partir d'un numero nu.
    """
    if not isinstance(raw, str):
        return None
    cleaned = _SEPARATORS_RE.sub("", normalize_phone(raw))
    if cleaned.startswith("+"):
        digits = cleaned[1:]
    elif cleaned.startswith("00"):
        digits = cleaned[2:]
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


def _dedup_key(phone: str) -> str:
    return normalize_whatsapp_number(phone) or _SEPARATORS_RE.sub("", phone)


def mark_contacted(seller, key: str, *, now: datetime | None = None) -> int:
    """Marque « prevenu » toutes les inscriptions du vendeur ayant ce numero normalise.

    Ne touche JAMAIS les inscrits d'un autre vendeur. Retourne le nombre de lignes.
    """
    now = now or timezone.now()
    ids = [
        row.pk
        for row in SaleInterest.objects.filter(flash_sale__owner=seller)
        if _dedup_key(row.phone) == key
    ]
    if not ids:
        return 0
    return SaleInterest.objects.filter(pk__in=ids, flash_sale__owner=seller).update(
        contacted_at=now
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
                "contacted_at": row.contacted_at,  # ligne la plus recente
                "key": key,
            }
        elif not entry["name"] and row.name:
            entry["name"] = row.name  # garde un nom si une inscription plus ancienne en a un
    return [
        Invitee(
            name=e["name"],
            phone=e["phone"],
            phone_e164=e["e164"],
            signed_up_at=e["at"],
            key=e["key"],
            contacted_at=e["contacted_at"],
        )
        for e in seen.values()
    ]


def seller_display_name(seller) -> str:
    return (seller.business_name or seller.user.display_name or "Vendeur").strip()


def _opening_label(sale: FlashSale) -> str:
    start = timezone.localtime(sale.start_time)
    day = date_format(start, "l j F")
    hour = f"{start.hour} h" if start.minute == 0 else f"{start.hour} h {start.minute:02d}"
    return f"{day} à {hour}"


def build_whatsapp_message(
    *, invitee: Invitee, seller_name: str, sale: FlashSale, sale_url: str
) -> str:
    first_name = invitee.name.split()[0] if invitee.name.strip() else ""
    greeting = f"Bonjour {first_name}," if first_name else "Bonjour,"
    return (
        f"{greeting} {seller_name} lance une vente flash : {sale.title}. "
        f"Ouverture {_opening_label(sale)}. "
        f"Commandez ici : {sale_url}"
    )


def whatsapp_link(invitee: Invitee, message: str) -> str | None:
    if not invitee.phone_e164:
        return None
    return f"https://wa.me/{invitee.phone_e164}?text={quote(message, safe='')}"


def _notify_row(invitee: Invitee, *, seller_name: str, sale: FlashSale, sale_url: str) -> dict:
    message = build_whatsapp_message(
        invitee=invitee, seller_name=seller_name, sale=sale, sale_url=sale_url
    )
    return {"invitee": invitee, "link": whatsapp_link(invitee, message)}


def build_notify_row(seller, key: str, *, build_sale_url) -> dict | None:
    """Ligne d'un inscrit (apres marquage) ; ``link`` vaut None s'il n'y a plus de vente."""
    invitee = next((i for i in interests_to_notify(seller) if i.key == key), None)
    if invitee is None:
        return None
    sale = next_scheduled_sale(seller)
    if sale is None:
        return {"invitee": invitee, "link": None}
    return _notify_row(
        invitee,
        seller_name=seller_display_name(seller),
        sale=sale,
        sale_url=build_sale_url(sale),
    )


def build_notify_context(seller, *, build_sale_url) -> dict:
    """Contexte du bloc « Prévenir vos inscrits » (liste de liens individuels)."""
    sale = next_scheduled_sale(seller)
    if sale is None:
        return {
            "notify_sale": None,
            "notify_rows": [],
            "notify_no_sale_message": (
                "Vous n'avez aucune vente programmée. Programmez votre prochaine "
                "vente pour pouvoir prévenir vos inscrits."
            ),
        }
    sale_url = build_sale_url(sale)
    name = seller_display_name(seller)
    rows = [
        _notify_row(invitee, seller_name=name, sale=sale, sale_url=sale_url)
        for invitee in interests_to_notify(seller)
    ]
    return {
        "notify_sale": sale,
        "notify_opening": _opening_label(sale),
        "notify_rows": rows,
        "notify_no_sale_message": "",
    }
