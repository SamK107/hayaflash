"""Commandes non honorees et blocage d'un numero (F-59 / decision D2).

Regle : un numero de cliente ne peut plus passer de nouvelle commande apres
``UNHONORED_ORDERS_THRESHOLD`` livraisons refusees ou injoignables (livraison
marquee « Echec » par la vendeuse) sur ``UNHONORED_WINDOW_DAYS`` jours glissants.

- La cle du numero est celle de la limite de debit : 8 derniers chiffres, donc
  ``+22370000001`` et ``70 00 00 01`` comptent pareil.
- Une commande annulee par la vendeuse ne compte pas.
- Une vendeuse debloque le numero pour SA boutique, l'administration pour toutes :
  seuls les echecs posterieurs au deblocage comptent ensuite.
- Verification a la commande : deux requetes indexees, aucune jointure lourde.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import timedelta

from django.db.models import Count, Max, Q
from django.utils import timezone

from orders.models import Order, OrderStatus, PhoneUnblock, UnhonoredOrder

UNHONORED_ORDERS_THRESHOLD = 3
UNHONORED_WINDOW_DAYS = 30

PHONE_BLOCKED_MESSAGE = (
    "Ce numéro ne peut plus commander pour le moment. Contacte la boutique."
)


def phone_key(phone: str | None) -> str:
    """8 derniers chiffres du numero (cle commune avec la limite de debit)."""
    return re.sub(r"\D", "", phone or "")[-8:]


def _window_start():
    return timezone.now() - timedelta(days=UNHONORED_WINDOW_DAYS)


def record_unhonored_order(order: Order) -> UnhonoredOrder | None:
    """Enregistre l'echec de livraison de ``order`` (idempotent). None sans numero."""
    key = phone_key(order.customer_phone)
    if not key:
        return None
    seller_id = order.flash_sale.owner_id if order.flash_sale_id else None
    record, _ = UnhonoredOrder.objects.get_or_create(
        order=order, defaults={"phone_key": key, "seller_id": seller_id}
    )
    return record


def blocked_phone_keys(keys: Iterable[str], seller_id: int | None) -> set[str]:
    """Parmi ``keys``, ceux qui sont bloques pour la boutique ``seller_id``.

    Deux requetes quel que soit le nombre de cles (utilise aussi par la liste
    des commandes du vendeur).
    """
    keys = {k for k in keys if k}
    if not keys:
        return set()
    since = _window_start()
    counted = dict(
        UnhonoredOrder.objects.filter(phone_key__in=keys, created_at__gte=since)
        .exclude(order__status=OrderStatus.CANCELLED)
        .values("phone_key")
        .annotate(n=Count("pk"))
        .values_list("phone_key", "n")
    )
    candidates = {k for k, n in counted.items() if n >= UNHONORED_ORDERS_THRESHOLD}
    if not candidates:
        return set()
    # Dernier deblocage applicable (global, ou propre a cette boutique) par numero.
    scope = Q(seller__isnull=True)
    if seller_id is not None:
        scope |= Q(seller_id=seller_id)
    last_unblock = dict(
        PhoneUnblock.objects.filter(scope, phone_key__in=candidates)
        .values("phone_key")
        .annotate(last=Max("created_at"))
        .values_list("phone_key", "last")
    )
    blocked = set()
    for key in candidates:
        floor = max(since, last_unblock[key]) if key in last_unblock else since
        n = (
            UnhonoredOrder.objects.filter(phone_key=key, created_at__gt=floor)
            .exclude(order__status=OrderStatus.CANCELLED)
            .count()
            if key in last_unblock
            else counted[key]
        )
        if n >= UNHONORED_ORDERS_THRESHOLD:
            blocked.add(key)
    return blocked


def is_phone_blocked(phone: str | None, seller_id: int | None = None) -> bool:
    key = phone_key(phone)
    return bool(key) and key in blocked_phone_keys([key], seller_id)


def unblock_phone(phone: str | None, *, by_user=None, seller=None) -> PhoneUnblock | None:
    """Debloque un numero (``seller`` = sa boutique ; None = global, administration)."""
    key = phone_key(phone)
    if not key:
        return None
    return PhoneUnblock.objects.create(phone_key=key, seller=seller, created_by=by_user)
