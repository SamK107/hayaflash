"""Rattachement d'un grossiste Distrib à un partenaire (D9), saisi par l'équipe.

Une seule fonction publique : :func:`attribute_distributor`. Elle n'est branchée sur aucun
parcours public. Aucune commission n'est calculée ici : la part du partenaire sur Distrib se
calcule à la main, par relevé (D9). Un grossiste rattaché n'a pas de vendeuse (`seller` vide).
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import audit
from partners.models import (
    AcceptanceDocType,
    Partner,
    PartnerAcceptance,
    PartnerStatus,
    Referral,
    ReferralSource,
)


class DistributorAttributionError(ValueError):
    """Attribution refusée (doublon, source inconnue). Le message est affichable en français."""


def partner_can_bring_distributor(partner: Partner) -> bool:
    """Partenaire actif (statut « Actif ») ayant accepté les conditions du programme, non invalidées."""
    if partner.status != PartnerStatus.ACTIVE:
        return False
    return PartnerAcceptance.objects.filter(
        partner=partner,
        doc_type=AcceptanceDocType.PROGRAM_TERMS,
        invalidation__isnull=True,
    ).exists()


def existing_partner_referral(distributor) -> Referral | None:
    """L'attribution déjà enregistrée pour ce grossiste, ou None."""
    if distributor is None or distributor.pk is None:
        return None
    return Referral.objects.select_related("partner").filter(distributor=distributor).first()


def attribute_distributor(
    *,
    partner: Partner,
    distributor,
    source: str = ReferralSource.MANUAL,
    attributed_at=None,
    actor=None,
) -> Referral:
    """Enregistre que ``distributor`` est amené par ``partner``.

    Refuse (``DistributorAttributionError``) si le grossiste est déjà rattaché, à n'importe
    quel partenaire : une attribution ne se déplace jamais. Écrit une entrée d'audit dans la
    même transaction que la création.
    """
    if source not in ReferralSource.values:
        raise DistributorAttributionError("Source d'attribution inconnue.")
    if not partner_can_bring_distributor(partner):
        raise DistributorAttributionError(
            "Seul un partenaire actif, ayant accepté les conditions du programme, peut amener un grossiste."
        )
    try:
        with transaction.atomic():
            if Referral.objects.select_for_update().filter(distributor=distributor).exists():
                raise DistributorAttributionError("Ce grossiste est déjà rattaché à un partenaire.")
            referral = Referral.objects.create(
                partner=partner,
                distributor=distributor,
                source=source,
                attributed_at=attributed_at or timezone.now(),
            )
            audit(
                "partner.distributor_attributed",
                entity_type="Referral",
                entity_id=referral.pk,
                actor=actor,
                partner_id=partner.pk,
                distributor_id=distributor.pk,
                source=source,
            )
    except IntegrityError as exc:
        # Filet de sécurité : la contrainte unique tranche en cas de course entre deux saisies.
        raise DistributorAttributionError("Ce grossiste est déjà rattaché à un partenaire.") from exc
    return referral
