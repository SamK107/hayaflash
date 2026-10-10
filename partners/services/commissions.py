"""Commissions de recommandation : calcul au paiement d'abonnement, annulation.

Formules (FCFA entiers, arrondi à l'inférieur, RM-12) :
    net        = floor(montant * (100 - ORANGE_RETENTION_PERCENT) / 100)
    commission = floor(net * pourcentage_du_partenaire / 100)
Exemples : 2 000 -> 1 980 -> 594 ; 5 000 -> 4 950 -> 1 485.

Fenêtre : 12 mois à partir du PREMIER paiement du vendeur recommandé. Un paiement
postérieur à ``commission_ends_at`` ne génère rien. Les droits acquis survivent à
la fin ou à la libération de la place du partenaire.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import audit
from partners.models import (
    CommissionEntry,
    CommissionStatus,
    PartnerAcceptance,
    PartnerPhase,
    Referral,
)
from partners.services.dates import add_months
from subscriptions.services.platform_reporting import revenue_payments

logger = logging.getLogger(__name__)


def compute_amounts(gross_fcfa: int, percent: int) -> tuple[int, int]:
    """(net, commission) en FCFA entiers, arrondis à l'inférieur."""
    net = gross_fcfa * (100 - settings.ORANGE_RETENTION_PERCENT) // 100
    commission = net * percent // 100
    return net, commission


def _terms_in_force(partner, paid_at) -> bool:
    """Un paiement ne génère une commission que si les conditions du programme sont acceptées.

    - le partenaire doit être sous contrat (ou, une fois le contrat terminé, avoir été sous
      contrat : droits acquis, article 6.3) : jamais en essai, jamais « aucune » ;
    - une acceptation « program_terms » doit exister ;
    - le paiement doit avoir été encaissé À PARTIR de l'acceptation (jamais avant).
    """
    if partner.phase not in (PartnerPhase.CONTRACT, PartnerPhase.ENDED):
        return False
    acceptance = (
        PartnerAcceptance.objects.filter(partner=partner, doc_type="program_terms")
        .order_by("accepted_at")
        .first()
    )
    return acceptance is not None and paid_at >= acceptance.accepted_at


def record_for_payment(payment) -> CommissionEntry | None:
    """Crée (une seule fois) la commission d'un paiement d'abonnement réellement encaissé.

    Ignore : vendeur sans inscription via un lien, paiement de test (RM-17), montant nul, paiement
    non réussi EN BASE (l'objet en mémoire ne suffit pas), ligne déjà existante,
    paiement hors fenêtre de 12 mois, partenaire sans contrat accepté ou paiement encaissé avant
    l'acceptation des conditions (bloc H6). Idempotent. À appeler sous le verrou du paiement.
    """
    with transaction.atomic():
        fresh = revenue_payments().filter(pk=payment.pk).first()
        if fresh is None or fresh.amount <= 0:
            return None
        existing = CommissionEntry.objects.filter(payment_id=fresh.pk).first()
        if existing is not None:
            return existing
        referral = (
            Referral.objects.select_for_update(of=("self",))
            .select_related("partner")
            .filter(seller_id=fresh.seller_id)
            .first()
        )
        if referral is None:
            return None
        when = fresh.paid_at or timezone.now()
        if not _terms_in_force(referral.partner, when):
            return None
        if referral.first_paid_at is None:
            referral.first_paid_at = when
            referral.commission_ends_at = add_months(when, settings.PARTNER_COMMISSION_MONTHS)
            referral.save(update_fields=["first_paid_at", "commission_ends_at"])
        elif when > referral.commission_ends_at:
            return None
        percent = referral.partner.commission_percent
        net, commission = compute_amounts(fresh.amount, percent)
        return CommissionEntry.objects.create(
            referral=referral,
            payment=fresh,
            gross_fcfa=fresh.amount,
            net_fcfa=net,
            percent=percent,
            commission_fcfa=commission,
        )


def cancel_entry(entry: CommissionEntry, reason: str, *, actor=None) -> CommissionEntry:
    """Annule une commission (trace d'audit). Une ligne versée ne s'annule pas seule."""
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("Indiquez le motif de l'annulation.")
    with transaction.atomic():
        locked = CommissionEntry.objects.select_for_update().get(pk=entry.pk)
        if locked.status == CommissionStatus.CANCELLED:
            return locked
        if locked.status == CommissionStatus.PAID or locked.payout_id is not None:
            raise ValidationError(
                "Cette commission est déjà versée ou incluse dans un versement : elle ne peut "
                "pas être annulée sans contrepartie. Régularisez d'abord le versement."
            )
        locked.status = CommissionStatus.CANCELLED
        locked.save(update_fields=["status"])
        audit(
            "partner.commission_cancelled",
            entity_type="CommissionEntry",
            entity_id=locked.pk,
            actor=actor,
            reason=reason,
            commission_fcfa=locked.commission_fcfa,
        )
    entry.status = CommissionStatus.CANCELLED
    return locked
