"""Acceptation en ligne (ou écrite, saisie par l'équipe) des documents du programme.

Une acceptation fige le texte rendu, son empreinte, le nom saisi, l'empreinte salée de
l'IP et la méthode ; elle est immuable. Les effets sur le partenaire (essai, contrat) se
font dans la même transaction.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import audit
from partners import legal_docs
from partners.models import (
    SLOT_HOLDING_STATUSES,
    AcceptanceDocType,
    AcceptanceMethod,
    OutboundMessage,
    Partner,
    PartnerAcceptance,
    PartnerPhase,
    PartnerStatus,
)
from partners.services.dates import add_months

FULL_PLACES_MESSAGE = "Les places sont actuellement toutes attribuées."
NAME_MESSAGE = "Indiquez votre nom complet."
CHECKBOX_MESSAGE = "Cochez la case pour confirmer que vous avez lu et accepté le document."


def places_left() -> int:
    """Places de fondateur restantes (actives ou en pause, sous contrat)."""
    taken = Partner.objects.filter(
        is_founder=True, status__in=SLOT_HOLDING_STATUSES, phase=PartnerPhase.CONTRACT
    ).count()
    return max(0, settings.PARTNER_FOUNDER_SLOTS - taken)


def has_accepted(partner: Partner, doc_type: str) -> bool:
    return PartnerAcceptance.objects.filter(
        partner=partner, doc_type=doc_type, doc_version=legal_docs.DOCS[doc_type]["version"]
    ).exists()


def pending_document(partner: Partner) -> str | None:
    """Document que le partenaire doit lire et accepter maintenant, ou None.

    - prospect ou phase « aucune » : la lettre d'essai ;
    - phase essai, invitation envoyée (message « envoi_conditions ») : les conditions.
    """
    if partner.status in (PartnerStatus.ENDED, PartnerStatus.SLOT_RELEASED):
        return None
    if partner.phase == PartnerPhase.NONE or partner.status == PartnerStatus.PROSPECT:
        return None if has_accepted(partner, "trial_letter") else "trial_letter"
    if partner.phase == PartnerPhase.TRIAL:
        invited = OutboundMessage.objects.filter(partner=partner, template_key="envoi_conditions").exists()
        if invited and not has_accepted(partner, "program_terms"):
            return "program_terms"
    return None


def _apply_effects(partner: Partner, doc_type: str, accepted_on, optional: dict) -> None:
    if doc_type == AcceptanceDocType.TRIAL_LETTER:
        partner.cite_shop_consent = bool(optional.get("cite_shop"))
        if partner.phase == PartnerPhase.NONE:
            partner.phase = PartnerPhase.TRIAL
            partner.trial_start = partner.trial_start or accepted_on
            partner.trial_end = partner.trial_start + timedelta(days=settings.PARTNER_TRIAL_DAYS)
        if partner.status == PartnerStatus.PROSPECT:
            partner.status = PartnerStatus.ACTIVE
    else:
        partner.phase = PartnerPhase.CONTRACT
        partner.contract_start = accepted_on
        partner.contract_end = add_months(accepted_on, settings.PARTNER_CONTRACT_MONTHS)
        partner.is_founder = True  # le contrat occupe une place
        if partner.status == PartnerStatus.PROSPECT:
            partner.status = PartnerStatus.ACTIVE
    partner.save()


def accept_document(
    partner: Partner,
    doc_type: str,
    *,
    signer_name: str,
    ip_hash: str = "",
    method: str = AcceptanceMethod.ONLINE,
    manual_reference: str = "",
    accepted_at=None,
    optional_consents: dict | None = None,
) -> tuple[PartnerAcceptance, bool]:
    """Enregistre l'acceptation. Retourne (acceptation, créée). Idempotent par (partenaire, document, version)."""
    if doc_type not in legal_docs.DOCS:
        raise ValidationError("Document inconnu.")
    version = legal_docs.DOCS[doc_type]["version"]
    signer_name = (signer_name or "").strip()
    if len(signer_name) < 2:
        raise ValidationError(NAME_MESSAGE)
    online = method == AcceptanceMethod.ONLINE
    if online and not legal_docs.acceptance_allowed(doc_type):
        raise ValidationError(legal_docs.INCOMPLETE_MESSAGE)
    accepted_at = accepted_at or timezone.now()
    optional = dict(optional_consents or {})

    with transaction.atomic():
        locked = Partner.objects.select_for_update().get(pk=partner.pk)
        existing = PartnerAcceptance.objects.filter(
            partner=locked, doc_type=doc_type, doc_version=version
        ).first()
        if existing is not None:
            return existing, False
        if doc_type == AcceptanceDocType.PROGRAM_TERMS and places_left() <= 0:
            raise ValidationError(FULL_PLACES_MESSAGE)
        snapshot = legal_docs.canonical_text(legal_docs.render_document(doc_type, locked))
        try:
            with transaction.atomic():
                acceptance = PartnerAcceptance.objects.create(
                    partner=locked,
                    doc_type=doc_type,
                    doc_version=version,
                    text_snapshot=snapshot,
                    text_sha256=legal_docs.sha256_of(snapshot),
                    signer_name=signer_name[:160],
                    accepted_at=accepted_at,
                    ip_hash=ip_hash,
                    method=method,
                    manual_reference=manual_reference.strip(),
                    optional_consents=optional,
                )
        except IntegrityError:  # double envoi simultané
            return PartnerAcceptance.objects.get(partner=locked, doc_type=doc_type, doc_version=version), False
        try:
            _apply_effects(locked, doc_type, timezone.localtime(accepted_at).date(), optional)
        except ValidationError:
            raise ValidationError(FULL_PLACES_MESSAGE) from None
        audit(
            "partner.document_accepted",
            entity_type="Partner",
            entity_id=locked.pk,
            doc_type=doc_type,
            doc_version=version,
            method=method,
            text_sha256=acceptance.text_sha256,
        )
    partner.refresh_from_db()
    return acceptance, True
