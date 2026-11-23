"""Suspension et reactivation d'une boutique par l'equipe (admin).

Une suspension bascule ``SellerProfile.is_active`` : la boutique disparait du
Marche et ne peut plus creer de vente (flash_sales/services/crud.py). Rien n'est
supprime. Chaque action laisse une entree ``AuditLog`` (qui, quand, motif).

Ce service ne touche ni le compte utilisateur (connexion), ni l'abonnement, ni
les ventes deja ouvertes : ce sont des decisions distinctes.
"""

from __future__ import annotations

from django.db import transaction

from accounts.models import SellerProfile
from core.models import AuditLog

MAX_REASON_LENGTH = 300
SUSPEND_ACTION = "shop.suspended"
REACTIVATE_ACTION = "shop.reactivated"


class SuspensionError(ValueError):
    """Refus metier (motif absent, deja dans cet etat) : message destine a l'equipe."""


def _set_active(shop: SellerProfile, *, active: bool, actor, reason: str, ip: str | None) -> None:
    reason = (reason or "").strip()
    if not reason:
        raise SuspensionError("Le motif est obligatoire.")
    if len(reason) > MAX_REASON_LENGTH:
        raise SuspensionError(f"Le motif ne dépasse pas {MAX_REASON_LENGTH} caractères.")

    with transaction.atomic():
        locked = SellerProfile.objects.select_for_update().get(pk=shop.pk)
        if locked.is_active == active:
            state = "active" if active else "suspendue"
            raise SuspensionError(f"La boutique est déjà {state}.")
        locked.is_active = active
        locked.save(update_fields=["is_active", "updated_at"])
        AuditLog.objects.create(
            actor=actor if getattr(actor, "pk", None) else None,
            action=REACTIVATE_ACTION if active else SUSPEND_ACTION,
            entity_type="SellerProfile",
            entity_id=shop.pk,
            metadata={"reason": reason, "seller_code": locked.seller_code},
            ip_address=ip,
        )
    shop.is_active = active


def suspend_shop(shop: SellerProfile, *, actor, reason: str, ip: str | None = None) -> None:
    _set_active(shop, active=False, actor=actor, reason=reason, ip=ip)


def reactivate_shop(shop: SellerProfile, *, actor, reason: str, ip: str | None = None) -> None:
    _set_active(shop, active=True, actor=actor, reason=reason, ip=ip)
