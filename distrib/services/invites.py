"""Invitations de revendeurs et consentement (spec §5.2, principe 5 : jamais de rattachement
sans acceptation explicite, jamais de blocage d'inscription)."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from core.models import audit
from distrib.models import Distributor, ResellerInvite

Status = ResellerInvite.Status


def invite_reseller(*, distributor: Distributor, display_name: str, phone: str) -> ResellerInvite:
    """Ajoute un numero a la liste du grossiste (ou relance un refus / une revocation)."""
    display_name = (display_name or "").strip()
    if not display_name:
        raise ValidationError("Indiquez le nom du revendeur.")
    if phone == distributor.user.phone:
        raise ValidationError("Vous ne pouvez pas vous inviter vous-même.")

    with transaction.atomic():
        invite = (
            ResellerInvite.objects.select_for_update()
            .filter(distributor=distributor, phone=phone)
            .first()
        )
        if invite is None:
            return ResellerInvite.objects.create(
                distributor=distributor, display_name=display_name, phone=phone
            )
        if invite.status == Status.ACCEPTED:
            raise ValidationError("Ce revendeur est déjà rattaché à votre liste.")
        if invite.status == Status.INVITED:
            raise ValidationError("Ce numéro est déjà invité : en attente de sa réponse.")
        # Refus ou revocation : nouvelle invitation, il devra de nouveau consentir.
        invite.status = Status.INVITED
        invite.display_name = display_name
        invite.seller = None
        invite.invited_at = timezone.now()
        invite.answered_at = None
        invite.save(update_fields=["status", "display_name", "seller", "invited_at", "answered_at"])
        return invite


def revoke_invite(*, invite: ResellerInvite, actor=None) -> ResellerInvite:
    """Revoque : plus de nouvelle importation ni allocation ; les commandes en cours restent suivies."""
    with transaction.atomic():
        invite = ResellerInvite.objects.select_for_update().get(pk=invite.pk)
        if invite.status in (Status.REVOKED, Status.DECLINED):
            raise ValidationError("Ce revendeur n'est plus dans votre liste.")
        invite.status = Status.REVOKED
        invite.answered_at = timezone.now()
        invite.save(update_fields=["status", "answered_at"])
        audit(
            "distrib.invite_revoked",
            entity_type="ResellerInvite",
            entity_id=invite.pk,
            actor=actor,
            distributor_id=invite.distributor_id,
        )
    return invite


def pending_invites_for(user):
    """Invitations en attente adressees au numero de cet utilisateur (E.164 exact)."""
    if not getattr(user, "is_authenticated", False) or not user.phone:
        return ResellerInvite.objects.none()
    return ResellerInvite.objects.filter(
        phone=user.phone, status=Status.INVITED, distributor__is_active=True
    ).select_related("distributor")


def accepted_invites_for(seller):
    return ResellerInvite.objects.filter(seller=seller, status=Status.ACCEPTED).select_related(
        "distributor"
    )


def answer_invite(*, invite: ResellerInvite, user, accept: bool) -> ResellerInvite:
    """Reponse du revendeur : seul le titulaire du numero invite, et une seule fois."""
    seller = getattr(user, "seller_profile", None)
    if seller is None or invite.phone != user.phone:
        raise PermissionDenied
    with transaction.atomic():
        invite = ResellerInvite.objects.select_for_update().get(pk=invite.pk)
        if invite.status != Status.INVITED or not invite.distributor.is_active:
            raise ValidationError("Cette invitation n'est plus valable.")
        invite.status = Status.ACCEPTED if accept else Status.DECLINED
        invite.seller = seller if accept else None
        invite.answered_at = timezone.now()
        invite.save(update_fields=["status", "seller", "answered_at"])
        audit(
            "distrib.invite_accepted" if accept else "distrib.invite_declined",
            entity_type="ResellerInvite",
            entity_id=invite.pk,
            actor=user,
            distributor_id=invite.distributor_id,
        )
    return invite
