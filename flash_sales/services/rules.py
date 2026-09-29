"""Regles metier des ventes flash : SOURCE UNIQUE (F-29 / F-31).

- quota mensuel selon le plan (FREE 3 / MEDIUM 10 / PRO illimite), fail-closed ;
- 3 ventes par jour maximum (tout statut sauf CANCELLED) ;
- duree maximale de 2 h.

Appele par TOUS les chemins : create_flash_sale, update_flash_sale,
clone_flash_sale, FlashSale.open_sale (donc aussi l'auto-open Celery) et le
formulaire vendeur. Ne pas reecrire ces controles ailleurs.

"Jour" = jour calendaire de `start_time` dans le fuseau du projet (TIME_ZONE,
Africa/Bamako).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

# Nom de logger historique : le fail-closed du quota etait logue par crud.py
# (alertes / tests existants filtrent dessus) — on le conserve.
logger = logging.getLogger("flash_sales.services.crud")

MAX_DURATION_MINUTES = 120  # 2 heures — maximum autorise par l'app
MAX_DAILY_SALES = 3  # max 3 ventes par jour


class SaleRuleError(ValidationError):
    """Une regle metier refuse l'operation (message destine au vendeur)."""


def can_seller_create_sale(seller, exclude_pk: int | None = None) -> tuple[bool, str]:
    """Quota mensuel du plan. Fail-closed : toute exception refuse."""
    try:
        from subscriptions.services.limits import can_create_flash_sale

        return can_create_flash_sale(seller, exclude_pk)
    except Exception:
        # Fail-closed : une panne cote subscriptions (DB, bug futur, migration
        # cassee) ne doit jamais desactiver silencieusement le quota.
        logger.exception("Quota check failed for seller %s", getattr(seller, "pk", seller))
        return False, "Impossible de vérifier votre quota. Réessayez."


def check_monthly_quota(seller, *, exclude_pk: int | None = None) -> None:
    ok, reason = can_seller_create_sale(seller, exclude_pk)
    if not ok:
        raise SaleRuleError(reason)


def check_duration(start_time: datetime, end_time: datetime) -> None:
    if end_time <= start_time:
        raise SaleRuleError("La date de fin doit être après la date de début.")
    if end_time - start_time > timedelta(minutes=MAX_DURATION_MINUTES):
        raise SaleRuleError(
            "Une vente flash dure 2 heures au maximum "
            f"({MAX_DURATION_MINUTES} minutes)."
        )


def count_sales_on_day(seller, start_time: datetime, exclude_pk: int | None = None) -> int:
    """Ventes du vendeur le meme jour (fuseau du projet), hors CANCELLED."""
    from flash_sales.models import FlashSale, FlashSaleStatus

    local = timezone.localtime(start_time)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    qs = FlashSale.objects.filter(
        owner=seller,
        start_time__gte=day_start,
        start_time__lt=day_start + timedelta(days=1),
    ).exclude(status=FlashSaleStatus.CANCELLED)
    if exclude_pk is not None:
        qs = qs.exclude(pk=exclude_pk)
    return qs.count()


def check_daily_limit(seller, start_time: datetime, *, exclude_pk: int | None = None) -> None:
    if count_sales_on_day(seller, start_time, exclude_pk) >= MAX_DAILY_SALES:
        raise SaleRuleError(
            f"Vous avez déjà {MAX_DAILY_SALES} ventes ce jour-là. "
            f"Maximum {MAX_DAILY_SALES} ventes flash par jour."
        )


def enforce_creation_rules(seller, start_time, end_time, *, exclude_pk=None, quota=True) -> None:
    """Toutes les regles, pour une vente qui va etre creee ou modifiee.

    `quota=False` pour une modification (la vente est deja comptee).
    """
    check_duration(start_time, end_time)
    check_daily_limit(seller, start_time, exclude_pk=exclude_pk)
    if quota:
        check_monthly_quota(seller, exclude_pk=exclude_pk)


def enforce_opening_rules(sale, start_time=None, end_time=None) -> None:
    """Defense en profondeur au passage a LIVE (manuel ou Celery).

    La vente est deja comptee dans le quota du mois : on l'exclut de son propre
    decompte (« hors cette vente, hors CANCELLED »).
    """
    enforce_creation_rules(
        sale.owner,
        start_time or sale.start_time,
        end_time or sale.end_time,
        exclude_pk=sale.pk,
    )
