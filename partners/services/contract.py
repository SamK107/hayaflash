"""Contrat d'un an : seuil trimestriel et libération de place.

Trimestres de 3 mois à partir du début du contrat. Un trimestre CLOS est « rempli »
si au moins un parrainage valide (non signalé, téléphone différent de celui du
partenaire) est devenu actif dans ce trimestre. Le premier trimestre n'est jamais
manqué. Tout est calculé à la lecture : aucune tâche Celery.
"""

from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import audit
from partners.models import Partner, PartnerPhase, PartnerStatus, Referral
from partners.services.activity import activation_dates
from partners.services.dates import add_months

QUARTER_MONTHS = 3
PARTNER_QUARTERS = 4  # contrat d'un an = 4 trimestres
WARNING_AFTER = 1
RELEASABLE_AFTER = 2


def _status_from_days(partner: Partner, activated_days: list[date], today: date) -> dict:
    count = PARTNER_QUARTERS
    # Le seuil ne démarre qu'avec le contrat : un prospect ou un partenaire en essai n'est
    # jamais jugé (les trimestres restent « non clos »).
    judged = partner.phase in (PartnerPhase.CONTRACT, PartnerPhase.ENDED)
    quarters = []
    for index in range(count):
        start = add_months(partner.contract_start, index * QUARTER_MONTHS)
        end = add_months(partner.contract_start, (index + 1) * QUARTER_MONTHS)
        closed = judged and end <= today
        filled = any(start <= day < end for day in activated_days)
        quarters.append(
            {
                "index": index + 1,
                "start": start,
                "end": end,
                "closed": closed,
                "filled": filled,
                # Le premier trimestre n'est jamais manqué ; un trimestre en cours non plus.
                "missed": closed and index > 0 and not filled,
            }
        )

    consecutive = 0
    for quarter in reversed([q for q in quarters if q["closed"]]):
        if quarter["missed"]:
            consecutive += 1
        else:
            break
    return {
        "quarters": quarters,
        "consecutive_missed": consecutive,
        "warning": consecutive >= WARNING_AFTER,
        "releasable": consecutive >= RELEASABLE_AFTER,
    }


def quarterly_status(partner: Partner, *, today: date | None = None) -> dict:
    """Trimestres, manqués consécutifs, avertissement (1) et place libérable (2)."""
    return quarterly_statuses([partner], today=today)[partner.pk]


def quarterly_statuses(partners, *, today: date | None = None) -> dict[int, dict]:
    """Même calcul pour plusieurs partenaires, en 2 requêtes au total (pas de N+1)."""
    today = today or timezone.localdate()
    partners = list(partners)
    by_partner: dict[int, list[int]] = {p.pk: [] for p in partners}
    phones = {p.pk: p.phone for p in partners}
    rows = Referral.objects.filter(partner__in=partners, flagged=False).values_list(
        "partner_id", "seller_id", "seller__user__phone"
    )
    for partner_id, seller_id, seller_phone in rows:
        if seller_phone != phones[partner_id]:
            by_partner[partner_id].append(seller_id)
    activated = activation_dates({s for ids in by_partner.values() for s in ids})
    result = {}
    for partner in partners:
        days = [
            timezone.localtime(activated[s]).date()
            for s in by_partner[partner.pk]
            if s in activated
        ]
        result[partner.pk] = _status_from_days(partner, days, today)
    return result


def release_slot(partner: Partner, *, actor=None, today: date | None = None) -> Partner:
    """Libère la place du partenaire si le seuil trimestriel est atteint (audit)."""
    with transaction.atomic():
        locked = Partner.objects.select_for_update().get(pk=partner.pk)
        if locked.status == PartnerStatus.SLOT_RELEASED:
            raise ValidationError("La place de ce partenaire est déjà libérée.")
        status = quarterly_status(locked, today=today)
        if not status["releasable"]:
            raise ValidationError(
                "Le seuil n'est pas atteint : la place ne peut être libérée qu'après "
                f"{RELEASABLE_AFTER} trimestres consécutifs sans nouveau vendeur actif."
            )
        locked.status = PartnerStatus.SLOT_RELEASED
        locked.save()
        audit(
            "partner.slot_released",
            entity_type="Partner",
            entity_id=locked.pk,
            actor=actor,
            consecutive_missed=status["consecutive_missed"],
        )
    partner.status = locked.status
    return locked
